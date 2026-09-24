"""
Conciliação da célula orçamentária NC × NE dos TEDs (PTRES, fonte de recursos detalhada, natureza da
despesa de 6 dígitos e Plano Interno).

Para cada NE vinculada a um TED (`vinculo_ne`, vindo do extrato TED → NE do SIMEC), compara a célula da NE
(base de despesas do Tesouro Gerencial) com o CONJUNTO de células das NCs do mesmo TED e exercício
(relatórios de NC do Tesouro Gerencial: "Destaques Recebidos", até 2025, e "NC 2026"). Uma diferença é
um ALERTA PARA CONFERÊNCIA — nunca uma conclusão de uso irregular do crédito.

Três camadas, deliberadamente separadas:

  1. LEITORES das duas bases de NC do TG e extração das células das NEs (funções puras sobre DataFrame);
  2. CONCILIAÇÃO (`conciliar_celulas`, pura — só dataclasses, testável sem banco);
  3. INTEGRAÇÃO com o SQLite do módulo de TEDs (`carregar_conciliacao_celulas`,
     `sincronizar_alertas_celula_orcamentaria`).

Decisões (briefing do usuário, 24/09/2026; reproduzem a conferência preliminar em dados reais: 126 NEs →
116 correspondentes, 7 sem NC comparável, 3 divergentes):

  * A NC do extrato do SIMEC (`2025NC000408`) é ligada à NC do TG (`154003152792025NC000408`) pelo SUFIXO
    `AAAANCNNNNNN` — que sozinho NÃO é chave única (UGs diferentes repetem ano e número): desambigua-se pela
    TRANSFERÊNCIA SIAFI (`1AAMVG`) e, quando o SIMEC informa, pela UG emitente. NC do SIMEC com número
    abreviado (`700014`, sem ano) não tem como ser ligada: fica "ainda não identificada", nunca ausente.
  * Coincidência de célula NUNCA cria o vínculo de uma NE com um TED: só o extrato TED → NE (`vinculo_ne`).
  * NC de 2026: a mesma movimentação aparece nas células ORIGEM e DESTINO. Só DESTINO (o crédito recebido)
    entra na comparação; as duas ficam guardadas para rastreabilidade. Nada é somado entre elas.
  * Valores das NCs (Saldo / NC Célula - Valor) ficam guardados como INFORMAÇÃO, sem conciliação: em algumas
    NCs a soma direta não bate com o total do extrato. A comparação é por CÓDIGOS, não por valor.
  * Códigos são texto: zeros à esquerda preservados, apóstrofo inicial de exportação removido (`'-8`).
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pandas as pd

from src.execucao_ne_utils import ne_curta
from src.teds_alertas import Alerta, _gravar_alertas_novos
from src.teds_importacao_simec import LinhaRejeitada
from src.teds_normalizacao import (
    ColunaObrigatoriaAusente,
    normalizar_codigo,
    normalizar_nome_coluna,
    parse_valor_brl,
    valor_para_texto,
)

TIPO_NC_TG_HISTORICA = "tg_nc_destaques_recebidos"
TIPO_NC_TG_2026 = "tg_nc_2026"
TIPO_NE_CELULA_DIVERGE_NC = "ne_celula_diverge_nc"

ESTADO_CORRESPONDENTE = "Correspondente"
ESTADO_DIVERGENCIA = "Divergência para conferência"
ESTADO_BASE_INCOMPLETA = "NC não identificada ou base incompleta"

CAMPOS_CELULA = ("ptres", "fonte_detalhada", "natureza", "pi")
_ROTULO_CAMPO = {
    "ptres": "PTRES",
    "fonte_detalhada": "fonte de recursos detalhada",
    "natureza": "natureza da despesa",
    "pi": "Plano Interno (PI)",
}

_NC_COMPLETA = re.compile(r"^(\d{6})(\d{5})(\d{4}NC\d{6})$")
_NC_COM_ANO = re.compile(r"^\d{4}NC\d{6}$")
_NE_CURTA = re.compile(r"^\d{4}NE\d{6}$")

Celula = tuple[str, str, str, str]  # (ptres, fonte_detalhada, natureza, pi)


# --------------------------------------------------------------------------------------
# 1. Leitores
# --------------------------------------------------------------------------------------

def _cod(valor: Any) -> str:
    """Código como texto: sem apóstrofo inicial, sem `.0` de float, maiúsculas, zeros preservados."""

    if isinstance(valor, str):
        valor = valor.strip().lstrip("'").strip()
    return normalizar_codigo(valor)


@dataclass
class ResultadoLeituraNcTg:
    registros: list[dict[str, Any]] = field(default_factory=list)
    rejeitadas: list[LinhaRejeitada] = field(default_factory=list)
    linhas_lidas: int = 0


#: rótulos (linha 1 do cabeçalho) de cada campo, normalizados. As colunas de DESCRIÇÃO vêm sem título, logo
#: à direita da coluna de código — só a coluna de código é lida.
_MAPA_NC_TG_HISTORICA = {
    "nc": (normalizar_nome_coluna("NC"),),
    "transferencia": (normalizar_nome_coluna("NC - Transferência"),),
    "natureza": (normalizar_nome_coluna("Natureza Despesa"),),
    "ptres": (normalizar_nome_coluna("PTRES"),),
    "pi": (normalizar_nome_coluna("PI"),),
    "fonte_detalhada": (normalizar_nome_coluna("Fonte Recursos Detalhada"),),
}
_MAPA_NC_TG_2026 = {
    "nc": (normalizar_nome_coluna("NC"),),
    "transferencia": (normalizar_nome_coluna("NC - Transferência"),),
    "natureza": (normalizar_nome_coluna("NC Célula - Natureza Despesa"),),
    "ptres": (normalizar_nome_coluna("NC Célula - PTRES"),),
    "pi": (normalizar_nome_coluna("NC Célula - Plano Interno"),),
    "fonte_detalhada": (normalizar_nome_coluna("NC Célula - Fonte Recurso Det."),),
    "tipo_celula": (normalizar_nome_coluna("NC Célula - Tipo"),),
}
_OBRIGATORIOS_NC_TG_HISTORICA = ("nc", "transferencia", "natureza", "ptres", "pi", "fonte_detalhada")
_OBRIGATORIOS_NC_TG_2026 = _OBRIGATORIOS_NC_TG_HISTORICA + ("tipo_celula",)

#: coluna de valor (linha 3 do cabeçalho), quando existe
_VALOR_NC_TG_HISTORICA = (normalizar_nome_coluna("Saldo - Moeda Origem (Item Informação)"), "saldo_moeda_origem")
_VALOR_NC_TG_2026 = (normalizar_nome_coluna("NC Célula - Valor"), "nc_celula_valor")

LINHAS_CABECALHO = 3


def _layout_bruto(df: pd.DataFrame) -> pd.DataFrame:
    """As duas bases têm cabeçalho de 3 linhas. A página lê com `header=0`, então a linha 1 do cabeçalho
    virou o nome das colunas; um chamador que leia com `header=None` entrega tudo como dados. Aceita os dois:
    devolve sempre o layout "bruto" (linha 0 = rótulos)."""

    rotulos = [normalizar_nome_coluna(c) for c in df.columns]
    if "nc" in rotulos:  # header=0: os rótulos vieram para os nomes de coluna
        return pd.DataFrame([list(df.columns)] + df.astype(object).values.tolist())
    return df.reset_index(drop=True).astype(object)


def _indices(bruto: pd.DataFrame, mapa: dict[str, tuple[str, ...]]) -> dict[str, int]:
    achados: dict[str, int] = {}
    rotulos = [normalizar_nome_coluna(v) if not pd.isna(v) else "" for v in bruto.iloc[0].tolist()]
    for campo, variantes in mapa.items():
        for j, rotulo in enumerate(rotulos):
            if rotulo in variantes:
                achados[campo] = j
                break
    return achados


def _indice_valor(bruto: pd.DataFrame, variante: str) -> int | None:
    for linha in range(min(LINHAS_CABECALHO, len(bruto))):
        for j, v in enumerate(bruto.iloc[linha].tolist()):
            if not pd.isna(v) and normalizar_nome_coluna(v) == variante:
                return j
    return None


def _ler_nc_tg(
    df: pd.DataFrame,
    *,
    mapa: dict[str, tuple[str, ...]],
    obrigatorios: tuple[str, ...],
    valor: tuple[str, str],
    origem_relatorio: str,
) -> ResultadoLeituraNcTg:
    bruto = _layout_bruto(df)
    if bruto.empty:
        raise ColunaObrigatoriaAusente(list(obrigatorios), [])
    indices = _indices(bruto, mapa)
    faltando = [c for c in obrigatorios if c not in indices]
    if faltando:
        raise ColunaObrigatoriaAusente(faltando, [v for v in bruto.iloc[0].tolist() if not pd.isna(v)])
    indice_valor = _indice_valor(bruto, valor[0])

    resultado = ResultadoLeituraNcTg()
    agregados: dict[tuple, dict[str, Any]] = {}
    for posicao in range(LINHAS_CABECALHO, len(bruto)):
        linha = bruto.iloc[posicao].tolist()
        resultado.linhas_lidas += 1
        numero_linha = posicao + 1  # linha da planilha (1 = primeira linha do cabeçalho)
        nc = _cod(linha[indices["nc"]])
        casou = _NC_COMPLETA.match(nc)
        if not casou:
            resultado.rejeitadas.append(LinhaRejeitada(
                posicao, f"NC fora do formato UG+gestão+AAAANCNNNNNN: {nc!r}", {"linha_planilha": numero_linha}
            ))
            continue
        ug_emitente, _gestao, sufixo = casou.groups()
        codigos = {c: _cod(linha[indices[c]]) for c in CAMPOS_CELULA}
        tipo_celula = _cod(linha[indices["tipo_celula"]]) if "tipo_celula" in indices else ""
        transferencia = _cod(linha[indices["transferencia"]])
        chave = (nc, transferencia, tipo_celula, *(codigos[c] for c in CAMPOS_CELULA))

        valor_linha: Decimal | None = None
        if indice_valor is not None and not pd.isna(linha[indice_valor]):
            try:
                valor_linha = parse_valor_brl(linha[indice_valor])
            except ValueError:
                valor_linha = None

        agregado = agregados.get(chave)
        if agregado is None:
            agregado = agregados[chave] = {
                "nc_completa": nc, "sufixo_nc": sufixo, "ug_emitente": ug_emitente, "ano_emissao": int(sufixo[:4]),
                "transferencia": transferencia, "tipo_celula": tipo_celula, **codigos,
                "valor": None, "metrica_valor": valor[1] if indice_valor is not None else None,
                "quantidade_linhas": 0, "linhas_origem": [], "origem_relatorio": origem_relatorio,
            }
        agregado["quantidade_linhas"] += 1
        agregado["linhas_origem"].append(numero_linha)
        if valor_linha is not None:
            agregado["valor"] = (agregado["valor"] or Decimal("0")) + valor_linha
    resultado.registros = list(agregados.values())
    return resultado


def ler_nc_tg_historica(df: pd.DataFrame) -> ResultadoLeituraNcTg:
    """Relatório "Destaques Recebidos" do Tesouro Gerencial (NCs até 2025). Uma linha por classificação da NC
    (várias por NC); o valor guardado é o `Saldo - Moeda Origem`, SEM conciliação (ver o docstring do módulo)."""

    return _ler_nc_tg(
        df, mapa=_MAPA_NC_TG_HISTORICA, obrigatorios=_OBRIGATORIOS_NC_TG_HISTORICA, valor=_VALOR_NC_TG_HISTORICA,
        origem_relatorio=TIPO_NC_TG_HISTORICA,
    )


def ler_nc_tg_2026(df: pd.DataFrame) -> ResultadoLeituraNcTg:
    """Relatório de NCs de 2026 (atributos `NC Célula - ...`). A mesma movimentação aparece em células ORIGEM e
    DESTINO: as duas são guardadas (`tipo_celula`), mas só DESTINO entra na comparação."""

    return _ler_nc_tg(
        df, mapa=_MAPA_NC_TG_2026, obrigatorios=_OBRIGATORIOS_NC_TG_2026, valor=_VALOR_NC_TG_2026,
        origem_relatorio=TIPO_NC_TG_2026,
    )


@dataclass
class ResultadoCelulasNe:
    registros: list[dict[str, Any]] = field(default_factory=list)
    rejeitadas: list[LinhaRejeitada] = field(default_factory=list)


_COLUNAS_CELULA_NE = {
    "ptres": "ptres", "fonte_detalhada": "fonte_recursos_detalhada_cod",
    "natureza": "natureza_despesa_cod", "pi": "pi_cod",
}


def montar_ne_celulas(execucao_mensal: pd.DataFrame) -> ResultadoCelulasNe:
    """Células orçamentárias distintas de cada NE, a partir da Execução Mensal (base de despesas do TG).

    Usa a NATUREZA DE 6 DÍGITOS (`natureza_despesa_cod`) — a natureza detalhada e o subitem têm outra
    granularidade. Uma NE pode ter mais de uma célula (itens com classificações diferentes); nada é
    somado, só listado. `linhas_origem` são as linhas da planilha de origem que trouxeram a célula.
    Sem as colunas de célula no DataFrame, devolve resultado vazio (ver o comentário abaixo)."""

    resultado = ResultadoCelulasNe()
    if execucao_mensal is None or execucao_mensal.empty:
        return resultado
    exigidas = ["ne_ccor", "linha_origem", *_COLUNAS_CELULA_NE.values()]
    if any(c not in execucao_mensal.columns for c in exigidas):
        # Base sem as colunas de célula (não é o caso da Execução Mensal real, que sempre as traz): nenhuma
        # célula é gravada, e a página de Células avisa que não há célula de NE. Não aborta a sincronização
        # dos valores do Tesouro por causa desta etapa secundária.
        return resultado

    base = execucao_mensal[exigidas].drop_duplicates()
    agregados: dict[tuple, dict[str, Any]] = {}
    for ne_ccor, linha_origem, *valores in base.itertuples(index=False, name=None):
        if pd.isna(ne_ccor):
            continue
        numero_ne = ne_curta(str(ne_ccor))
        if not _NE_CURTA.match(numero_ne):
            resultado.rejeitadas.append(LinhaRejeitada(int(linha_origem), f"NE fora do formato: {ne_ccor!r}", {}))
            continue
        codigos = dict(zip(CAMPOS_CELULA, (_cod(v) for v in valores)))
        chave = (numero_ne, *(codigos[c] for c in CAMPOS_CELULA))
        agregado = agregados.setdefault(chave, {
            "numero_ne": numero_ne, "ug_emitente": str(ne_ccor)[:6], **codigos,
            "quantidade_linhas": 0, "linhas_origem": [],
        })
        agregado["quantidade_linhas"] += 1
        if int(linha_origem) not in agregado["linhas_origem"]:
            agregado["linhas_origem"].append(int(linha_origem))
    resultado.registros = list(agregados.values())
    return resultado


# --------------------------------------------------------------------------------------
# 2. Conciliação (pura)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class NcSimec:
    """Uma NC do extrato do SIMEC, já ligada ao TED. `ug_emitente` só quando o SIMEC informa."""

    chave_ted: str
    numero_nc: str
    codigo_siafi: str
    ug_emitente: str | None = None


@dataclass(frozen=True)
class CelulaNcTg:
    nc_completa: str
    sufixo_nc: str
    ug_emitente: str
    ano_emissao: int
    transferencia: str
    tipo_celula: str
    celula: Celula
    linhas_origem: tuple[int, ...] = ()


@dataclass(frozen=True)
class VinculoNe:
    chave_ted: str
    ted: str
    codigo_siafi: str
    chave_empenho: str
    numero_ne: str
    status_validacao: str = "ok"


@dataclass(frozen=True)
class CelulaNe:
    numero_ne: str
    celula: Celula
    linhas_origem: tuple[int, ...] = ()


@dataclass(frozen=True)
class ResultadoCelula:
    exercicio: int
    chave_ted: str
    ted: str
    transferencia: str
    chave_empenho: str
    numero_ne: str
    status_vinculo: str
    situacao: str
    motivo: str
    celula_ne: Celula | None
    ncs_consideradas: tuple[str, ...]
    ncs_nao_identificadas: int
    celulas_nc: tuple[Celula, ...]
    campos_divergentes: tuple[str, ...]
    valores_nas_ncs: dict[str, tuple[str, ...]]
    linhas_origem_nc: tuple[int, ...]
    linhas_origem_ne: tuple[int, ...]

    @property
    def comparacao_pode_estar_incompleta(self) -> bool:
        return self.ncs_nao_identificadas > 0


def _celula_texto(celula: Celula | None) -> str:
    if celula is None:
        return "—"
    return " | ".join(celula)


def _cell_candidates(nc: NcSimec, celulas_tg: list[CelulaNcTg]) -> list[CelulaNcTg]:
    """NC do TG que corresponde a uma NC do SIMEC: sufixo + transferência SIAFI (+ UG emitente, se o SIMEC a
    informa). O sufixo sozinho não basta. NC abreviada (sem ano) nunca casa."""

    if not _NC_COM_ANO.match(nc.numero_nc):
        return []
    encontradas = [
        c for c in celulas_tg
        if c.sufixo_nc == nc.numero_nc and c.transferencia.upper() == nc.codigo_siafi.upper()
        and (not nc.ug_emitente or c.ug_emitente == nc.ug_emitente)
    ]
    # 2026: só DESTINO (o crédito recebido); relatório histórico não tem tipo de célula.
    return [c for c in encontradas if c.tipo_celula in ("", "DESTINO")]


def conciliar_celulas(
    ncs_simec: list[NcSimec],
    celulas_tg: list[CelulaNcTg],
    vinculos: list[VinculoNe],
    celulas_ne: list[CelulaNe],
) -> list[ResultadoCelula]:
    """Um resultado por (vínculo TED × NE × célula da NE). Estados:

      * Correspondente — ao menos uma célula das NCs do TED/exercício com os 4 campos iguais aos da NE;
      * Divergência para conferência — há NCs comparáveis e nenhuma tem a combinação da NE (informa os campos);
      * NC não identificada ou base incompleta — faltam NCs comparáveis (ou a NE não tem célula na base). Isto
        NÃO é divergência da NE: ausência de dado nunca aparece como conformidade nem como irregularidade.
    """

    por_ted: dict[str, list[NcSimec]] = {}
    for nc in ncs_simec:
        por_ted.setdefault(nc.chave_ted, []).append(nc)
    tg_por_sufixo: dict[str, list[CelulaNcTg]] = {}
    for c in celulas_tg:
        tg_por_sufixo.setdefault(c.sufixo_nc, []).append(c)
    ne_por_numero: dict[str, list[CelulaNe]] = {}
    for c in celulas_ne:
        ne_por_numero.setdefault(c.numero_ne, []).append(c)

    resultados: list[ResultadoCelula] = []
    for v in sorted(vinculos, key=lambda x: (x.numero_ne, x.chave_ted)):
        exercicio = int(v.numero_ne[:4])
        ncs_do_ted = por_ted.get(v.chave_ted, [])
        do_exercicio = [n for n in ncs_do_ted if n.numero_nc[:4] == str(exercicio) and _NC_COM_ANO.match(n.numero_nc)]
        abreviadas = [n for n in ncs_do_ted if not _NC_COM_ANO.match(n.numero_nc)]

        consideradas: list[NcSimec] = []
        celulas_das_ncs: list[CelulaNcTg] = []
        for nc in do_exercicio:
            achadas = _cell_candidates(nc, tg_por_sufixo.get(nc.numero_nc, []))
            if achadas:
                consideradas.append(nc)
                celulas_das_ncs.extend(achadas)
        nao_identificadas = len(abreviadas) + (len(do_exercicio) - len(consideradas))
        conjunto = sorted({c.celula for c in celulas_das_ncs})
        linhas_nc = tuple(sorted({n for c in celulas_das_ncs for n in c.linhas_origem}))
        base = dict(
            exercicio=exercicio, chave_ted=v.chave_ted, ted=v.ted, transferencia=v.codigo_siafi,
            chave_empenho=v.chave_empenho, numero_ne=v.numero_ne, status_vinculo=v.status_validacao,
            ncs_consideradas=tuple(sorted({n.numero_nc for n in consideradas})),
            ncs_nao_identificadas=nao_identificadas, celulas_nc=tuple(conjunto), linhas_origem_nc=linhas_nc,
        )

        celulas_da_ne = ne_por_numero.get(v.numero_ne, [])
        if not celulas_da_ne:
            resultados.append(ResultadoCelula(
                **base, situacao=ESTADO_BASE_INCOMPLETA,
                motivo="A NE não tem célula orçamentária na base de despesas importada.",
                celula_ne=None, campos_divergentes=(), valores_nas_ncs={}, linhas_origem_ne=(),
            ))
            continue

        for cne in sorted(celulas_da_ne, key=lambda c: c.celula):
            if not conjunto:
                if not do_exercicio and not abreviadas:
                    motivo = f"O TED não tem NC do exercício {exercicio} no extrato do SIMEC."
                elif not do_exercicio:
                    motivo = (
                        f"O TED só tem NC com número abreviado (sem ano), ainda não identificada no Tesouro "
                        f"Gerencial: {len(abreviadas)} NC(s)."
                    )
                else:
                    motivo = (
                        f"Nenhuma das {len(do_exercicio)} NC(s) do exercício {exercicio} do TED foi localizada "
                        "no Tesouro Gerencial (por sufixo e transferência SIAFI)."
                    )
                resultados.append(ResultadoCelula(
                    **base, situacao=ESTADO_BASE_INCOMPLETA, motivo=motivo, celula_ne=cne.celula,
                    campos_divergentes=(), valores_nas_ncs={}, linhas_origem_ne=cne.linhas_origem,
                ))
                continue
            if cne.celula in conjunto:
                resultados.append(ResultadoCelula(
                    **base, situacao=ESTADO_CORRESPONDENTE,
                    motivo="Existe célula de NC do TED com os quatro campos iguais aos da NE.",
                    celula_ne=cne.celula, campos_divergentes=(), valores_nas_ncs={}, linhas_origem_ne=cne.linhas_origem,
                ))
                continue

            # célula da NC mais parecida (mais campos iguais); empate: a primeira na ordem, determinística
            melhor = max(conjunto, key=lambda c: sum(a == b for a, b in zip(c, cne.celula)))
            divergentes = tuple(
                campo for campo, a, b in zip(CAMPOS_CELULA, melhor, cne.celula) if a != b
            )
            valores: dict[str, tuple[str, ...]] = {}
            for campo in divergentes:
                posicao = CAMPOS_CELULA.index(campo)
                iguais_nos_outros = [
                    c for c in conjunto
                    if all(c[i] == cne.celula[i] for i in range(4) if i != posicao)
                ] or conjunto
                valores[campo] = tuple(sorted({c[posicao] for c in iguais_nos_outros}))
            nomes = ", ".join(_ROTULO_CAMPO[c] for c in divergentes)
            resultados.append(ResultadoCelula(
                **base, situacao=ESTADO_DIVERGENCIA,
                motivo=f"NE vinculada ao TED com {nomes} não encontrado(s) nas NCs localizadas.",
                celula_ne=cne.celula, campos_divergentes=divergentes, valores_nas_ncs=valores,
                linhas_origem_ne=cne.linhas_origem,
            ))
    return resultados


def gerar_alertas_celula(resultados: list[ResultadoCelula]) -> list[Alerta]:
    """Um alerta por (TED, NE) com ao menos uma divergência — só divergência gera alerta; "base incompleta"
    fica visível na tabela mas NÃO vira alerta (ausência de dado não é irregularidade)."""

    por_vinculo: dict[tuple[str, str], list[ResultadoCelula]] = {}
    for r in resultados:
        if r.situacao == ESTADO_DIVERGENCIA:
            por_vinculo.setdefault((r.chave_ted, r.chave_empenho), []).append(r)

    alertas: list[Alerta] = []
    for (chave_ted, chave_empenho), lista in sorted(por_vinculo.items()):
        primeiro = lista[0]
        partes = []
        for r in lista:
            detalhes = []
            for campo in r.campos_divergentes:
                indice = CAMPOS_CELULA.index(campo)
                achados = ", ".join(r.valores_nas_ncs.get(campo, ())) or "—"
                detalhes.append(
                    f"{_ROTULO_CAMPO[campo]} {r.celula_ne[indice]} (as NCs trazem: {achados})"
                )
            partes.append(f"célula da NE [{_celula_texto(r.celula_ne)}]: {'; '.join(detalhes)}")
        incompleta = (
            f" A comparação pode estar incompleta: {primeiro.ncs_nao_identificadas} NC(s) do TED ainda não "
            "identificada(s) no Tesouro Gerencial."
            if primeiro.comparacao_pode_estar_incompleta else ""
        )
        alertas.append(Alerta(
            tipo=TIPO_NE_CELULA_DIVERGE_NC, gravidade="alta", documento=f"{chave_ted}|{chave_empenho}",
            chave_ted=chave_ted,
            descricao=(
                f"NE {primeiro.numero_ne} vinculada ao TED {primeiro.ted} (transferência {primeiro.transferencia}, "
                f"exercício {primeiro.exercicio}): " + " | ".join(partes)
                + f". NCs consideradas: {', '.join(primeiro.ncs_consideradas)}."
                + incompleta
                + " Alerta para conferência: pode ser erro no detalhamento previsto — confirmar no processo e "
                "no SIAFI; não é conclusão de uso indevido do crédito."
            ),
        ))
    return alertas


_COLUNAS_TABELA = [
    "Exercício", "TED", "Transferência (SIAFI)", "NE", "Vínculo", "Situação", "Motivo",
    "Célula da NE (PTRES | fonte | natureza | PI)", "Campos divergentes", "Valores nas NCs para o campo divergente",
    "NCs consideradas", "NCs do TED ainda não identificadas no TG", "Células das NCs",
    "Linhas de origem (NC)", "Linhas de origem (NE)",
]


def resultados_para_tabela(resultados: list[ResultadoCelula]) -> pd.DataFrame:
    """Tabela rastreável e filtrável: mostra os códigos efetivamente comparados, as NCs consideradas e o motivo."""

    linhas = []
    for r in resultados:
        linhas.append({
            "Exercício": r.exercicio, "TED": r.ted, "Transferência (SIAFI)": r.transferencia, "NE": r.numero_ne,
            "Vínculo": r.status_vinculo, "Situação": r.situacao, "Motivo": r.motivo,
            "Célula da NE (PTRES | fonte | natureza | PI)": _celula_texto(r.celula_ne),
            "Campos divergentes": ", ".join(_ROTULO_CAMPO[c] for c in r.campos_divergentes),
            "Valores nas NCs para o campo divergente": "; ".join(
                f"{_ROTULO_CAMPO[c]}: {', '.join(v)}" for c, v in r.valores_nas_ncs.items()
            ),
            "NCs consideradas": ", ".join(r.ncs_consideradas),
            "NCs do TED ainda não identificadas no TG": r.ncs_nao_identificadas,
            "Células das NCs": " ; ".join(_celula_texto(c) for c in r.celulas_nc),
            "Linhas de origem (NC)": ", ".join(str(n) for n in r.linhas_origem_nc),
            "Linhas de origem (NE)": ", ".join(str(n) for n in r.linhas_origem_ne),
        })
    return pd.DataFrame(linhas, columns=_COLUNAS_TABELA)


# --------------------------------------------------------------------------------------
# 3. Integração com o banco de TEDs
# --------------------------------------------------------------------------------------

def carregar_conciliacao_celulas(conn: sqlite3.Connection) -> list[ResultadoCelula]:
    """Lê do SQLite as cinco fontes e concilia. Vínculos `descartado` (decisão humana sobre NE em mais de um
    TED) ficam de fora; `pendente` entra, com o status visível na tabela."""

    ncs_simec = [
        NcSimec(chave_ted, numero_nc, siafi, ug or None)
        for chave_ted, numero_nc, siafi, ug in conn.execute(
            "SELECT DISTINCT chave_ted, numero_nc, codigo_siafi, ug_emitente FROM documento_nc_linha "
            "WHERE chave_ted IS NOT NULL"
        ).fetchall()
    ]
    celulas_tg = [
        CelulaNcTg(nc, sufixo, ug, ano, transf, tipo, (ptres, fonte, natureza, pi), tuple(json.loads(linhas)))
        for nc, sufixo, ug, ano, transf, tipo, ptres, fonte, natureza, pi, linhas in conn.execute(
            "SELECT nc_completa, sufixo_nc, ug_emitente, ano_emissao, transferencia, tipo_celula, ptres, "
            "fonte_detalhada, natureza, pi, linhas_origem FROM nc_celula"
        ).fetchall()
    ]
    vinculos = [
        VinculoNe(chave_ted, ted, siafi, chave_empenho, numero_ne, status)
        for chave_ted, ted, siafi, chave_empenho, numero_ne, status in conn.execute(
            "SELECT v.chave_ted, t.ted, t.codigo_siafi, v.chave_empenho, v.numero_ne, v.status_validacao "
            "FROM vinculo_ne v JOIN ted t ON t.chave_ted = v.chave_ted WHERE v.status_validacao != 'descartado'"
        ).fetchall()
    ]
    celulas_ne = [
        CelulaNe(numero_ne, (ptres, fonte, natureza, pi), tuple(json.loads(linhas)))
        for numero_ne, ptres, fonte, natureza, pi, linhas in conn.execute(
            "SELECT numero_ne, ptres, fonte_detalhada, natureza, pi, linhas_origem FROM ne_celula"
        ).fetchall()
    ]
    return conciliar_celulas(ncs_simec, celulas_tg, vinculos, celulas_ne)


def sincronizar_alertas_celula_orcamentaria(conn: sqlite3.Connection) -> list[Alerta]:
    """Grava os alertas de divergência de célula ainda não sinalizados. Sem células de NC ou de NE importadas
    não há o que comparar (nenhum alerta). Nunca fecha alerta existente."""

    tem_nc = conn.execute("SELECT 1 FROM nc_celula LIMIT 1").fetchone() is not None
    tem_ne = conn.execute("SELECT 1 FROM ne_celula LIMIT 1").fetchone() is not None
    if not (tem_nc and tem_ne):
        return []
    return _gravar_alertas_novos(conn, gerar_alertas_celula(carregar_conciliacao_celulas(conn)))


def gravar_celulas_nc(conn: sqlite3.Connection, registros: list[dict[str, Any]], batch_id: int) -> None:
    conn.executemany(
        """
        INSERT INTO nc_celula
            (nc_completa, transferencia, tipo_celula, ptres, fonte_detalhada, natureza, pi, sufixo_nc,
             ug_emitente, ano_emissao, origem_relatorio, valor, metrica_valor, quantidade_linhas,
             linhas_origem, import_batch_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(nc_completa, transferencia, tipo_celula, ptres, fonte_detalhada, natureza, pi)
        DO UPDATE SET
            sufixo_nc = excluded.sufixo_nc, ug_emitente = excluded.ug_emitente,
            ano_emissao = excluded.ano_emissao, origem_relatorio = excluded.origem_relatorio,
            valor = excluded.valor, metrica_valor = excluded.metrica_valor,
            quantidade_linhas = excluded.quantidade_linhas, linhas_origem = excluded.linhas_origem,
            import_batch_id = excluded.import_batch_id
        """,
        [
            (
                r["nc_completa"], r["transferencia"], r["tipo_celula"], r["ptres"], r["fonte_detalhada"],
                r["natureza"], r["pi"], r["sufixo_nc"], r["ug_emitente"], r["ano_emissao"], r["origem_relatorio"],
                valor_para_texto(r["valor"]) if r["valor"] is not None else None, r["metrica_valor"],
                r["quantidade_linhas"], json.dumps(r["linhas_origem"]), batch_id,
            )
            for r in registros
        ],
    )


def gravar_celulas_ne(conn: sqlite3.Connection, registros: list[dict[str, Any]], batch_id: int) -> None:
    conn.executemany(
        """
        INSERT INTO ne_celula
            (numero_ne, ptres, fonte_detalhada, natureza, pi, ug_emitente, quantidade_linhas, linhas_origem,
             import_batch_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(numero_ne, ptres, fonte_detalhada, natureza, pi) DO UPDATE SET
            ug_emitente = excluded.ug_emitente, quantidade_linhas = excluded.quantidade_linhas,
            linhas_origem = excluded.linhas_origem, import_batch_id = excluded.import_batch_id
        """,
        [
            (
                r["numero_ne"], r["ptres"], r["fonte_detalhada"], r["natureza"], r["pi"], r["ug_emitente"],
                r["quantidade_linhas"], json.dumps(r["linhas_origem"]), batch_id,
            )
            for r in registros
        ],
    )
