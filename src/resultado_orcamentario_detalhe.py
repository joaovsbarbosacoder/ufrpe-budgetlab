"""Detalhamento do Resultado Orçamentário por GND e Ação (pedido do usuário, 20/10/2026).

Só leitura e em memória: não altera `calcular_resultado`. Reparte, por (GND, Ação), os mesmos números que
os cartões mostram — dotação, executado, projetado a realizar e resultado — para que a soma das linhas
feche com o total do bolsão (a conferência é devolvida em `diferenca_conferencia`).

Onde cada valor cai (protótipo `docs/superpowers/specs/2026-10-20-resultado-orcamentario-gnd-acao-mockup.html`):
  * Dotação: célula marcada (GND = `grupo_despesa_codigo`, Ação = `acao_codigo`, ambos da chave da célula).
  * Executado das demais origens (DEA, Material de Consumo, Outros): empenhado da célula marcada.
  * Executado e projetado de Contratos e Bolsas: calculados por NE; a NE vai para a célula do seu empenho. NE com
    empenho em mais de uma célula é rateada pelo empenhado de cada célula (regra aprovada em 20/10/2026) e
    sinalizada em aviso. Se o rateio é impossível (empenhado nulo, negativo ou total zero em alguma célula) a NE
    vai para "Sem célula", em aviso — nunca é distribuída por palpite.
  * Parte de NE que está em célula NÃO marcada (a projeção é por NE e ela entra inteira na conta): linha
    "Fora das células marcadas", para o total fechar com os cartões.
  * Outras despesas previstas: célula informada no cadastro; sem célula → "Sem célula".
  * Contrato ATIVO sem NE (projetado pela necessidade contratual): "Sem célula".

Nulo continua nulo: um valor indisponível deixa nulo o grupo que ele alimenta (e o total), nunca vira zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.resultado_orcamentario import (
    ORIGEM_BOLSAS,
    ORIGEM_CONTRATOS,
    ORIGENS_CONSUMO,
    OUTRAS_DESPESAS,
    TOLERANCIA_CONFERENCIA,
    ResultadoOrcamentario,
    soma_ou_nulo,
)
from src.resultado_orcamentario_cadastro import CHAVE_CELULA, CelulaChave, DespesaManual

TIPO_CELULA = "celula"
TIPO_FORA = "fora_marcadas"
TIPO_SEM_CELULA = "sem_celula"

COLUNAS_DETALHE = [
    "tipo", "gnd", "gnd_descricao", "acao", "acao_descricao", "dotacao", "executado", "projetado", "resultado",
]

_IDX_ACAO = CHAVE_CELULA.index("acao_codigo")
_IDX_GND = CHAVE_CELULA.index("grupo_despesa_codigo")
_CAMPOS = ("dotacao", "executado", "projetado")


@dataclass
class DetalheGndAcao:
    linhas: pd.DataFrame
    #: totais das linhas (nulo se alguma linha tem o campo nulo)
    dotacao: float | None
    executado: float | None
    projetado: float | None
    resultado: float | None
    #: maior diferença absoluta entre estes totais e os do `ResultadoOrcamentario` (0,0 quando fecham)
    diferenca_conferencia: float
    avisos: list[str] = field(default_factory=list)

    @property
    def fecha(self) -> bool:
        return self.diferenca_conferencia < TOLERANCIA_CONFERENCIA


class _Balde:
    """Acumulador de um grupo: valor e marca de nulo por campo."""

    def __init__(self) -> None:
        self.valor = dict.fromkeys(_CAMPOS, 0.0)
        self.nulo = dict.fromkeys(_CAMPOS, False)

    def somar(self, campo: str, valor: float | None) -> None:
        if valor is None or pd.isna(valor):
            self.nulo[campo] = True
        else:
            self.valor[campo] += float(valor)

    def final(self, campo: str) -> float | None:
        return None if self.nulo[campo] else self.valor[campo]


def _chave_grupo(chave: CelulaChave) -> tuple[str | None, str | None]:
    return chave[_IDX_GND], chave[_IDX_ACAO]


def _descricoes(celulas: pd.DataFrame, codigo: str, descricao: str) -> dict[str, str]:
    if codigo not in celulas.columns or descricao not in celulas.columns:
        return {}
    base = celulas.dropna(subset=[codigo, descricao])
    return {str(c): str(d) for c, d in zip(base[codigo], base[descricao])}


def _pesos_da_ne(emp_da_ne: pd.DataFrame) -> dict[CelulaChave, float | None]:
    """Empenhado da NE por célula (soma das linhas de elemento); `None` se alguma linha da célula é nula."""

    pesos: dict[CelulaChave, float | None] = {}
    for chave, grupo in emp_da_ne.groupby("chave", sort=False):
        pesos[chave] = soma_ou_nulo(grupo["empenhada"])
    return pesos


def detalhar_por_gnd_acao(
    res: ResultadoOrcamentario,
    celulas: pd.DataFrame,
    empenhado: pd.DataFrame,
    selecao: list[CelulaChave],
    despesas_manuais: list[DespesaManual],
    ativos_sem_ne: pd.DataFrame | None = None,
) -> DetalheGndAcao:
    """Ver a docstring do módulo. `res` é o resultado já calculado (o detalhamento não recalcula a regra); os
    demais argumentos são os mesmos usados por `calcular_resultado`. `ativos_sem_ne`: contratos ATIVOS sem NE
    (`separar_ativos_sem_ne`), com a coluna `necessidade`."""

    avisos: list[str] = []
    marcadas = {tuple(c) for c in selecao if c[-1] is not None}
    baldes: dict[tuple, _Balde] = {}

    def balde(chave_balde: tuple) -> _Balde:
        return baldes.setdefault(chave_balde, _Balde())

    def balde_da_celula(chave: CelulaChave) -> _Balde:
        return balde((TIPO_CELULA, *_chave_grupo(chave))) if chave in marcadas else balde((TIPO_FORA,))

    sem_celula = (TIPO_SEM_CELULA,)

    # --- Dotação ---------------------------------------------------------------------------
    if len(celulas):
        for chave, dotacao in zip(celulas["chave"], celulas["dotacao_atualizada"]):
            if chave in marcadas:
                balde((TIPO_CELULA, *_chave_grupo(chave))).somar("dotacao", None if pd.isna(dotacao) else float(dotacao))
    for chave in marcadas:  # célula marcada sem Dotação na base: o grupo existe e fica sem dotação
        balde((TIPO_CELULA, *_chave_grupo(chave)))

    # --- Empenho por NE e célula --------------------------------------------------------------
    emp = empenhado.copy() if empenhado is not None else pd.DataFrame()
    for coluna in ("ne_curta", "chave", "elemento_cod", "empenhada"):
        if coluna not in emp.columns:
            emp[coluna] = pd.Series(dtype="object")
    emp["empenhada"] = pd.to_numeric(emp["empenhada"], errors="coerce")
    emp["ne_curta"] = emp["ne_curta"].astype(str)

    # --- Executado das demais origens: empenhado das células marcadas --------------------------
    def _elemento(valor: object) -> str | None:
        return None if pd.isna(valor) else str(valor)

    origem_por_ne_elemento = {
        (str(ne), _elemento(el)): origem
        for ne, el, origem in zip(res.empenhado_por_ne["ne_curta"], res.empenhado_por_ne["elemento_cod"], res.empenhado_por_ne["origem"])
    }
    for ne, chave, elemento, valor in zip(emp["ne_curta"], emp["chave"], emp["elemento_cod"], emp["empenhada"]):
        if chave not in marcadas:
            continue
        origem = origem_por_ne_elemento.get((ne, _elemento(elemento)))
        if origem in ORIGENS_CONSUMO:
            continue
        balde_da_celula(chave).somar("executado", None if pd.isna(valor) else float(valor))

    # --- Contratos e Bolsas: por NE, rateada pelo empenhado de cada célula -----------------------
    consumo = res.consumo_por_ne
    indisponivel = False  # projeção de Contratos ou Bolsas indisponível: nenhum grupo sabe a sua parte
    for origem in ORIGENS_CONSUMO:
        if res.executado.get(origem) is None:
            indisponivel = True
            avisos.append(f"{origem}: projeção indisponível; executado e projetado ficam sem valor em todos os grupos.")
    nes_rateadas: list[str] = []
    nes_sem_rateio: list[str] = []
    for ne, origem, executado, projetado in zip(
        consumo["ne_curta"], consumo["origem"], consumo["executado"], consumo["projetado"]
    ):
        ne = str(ne)
        pesos = _pesos_da_ne(emp.loc[emp["ne_curta"] == ne])
        if len(pesos) == 1:
            destinos = [(balde_da_celula(next(iter(pesos))), 1.0)]
        elif len(pesos) > 1 and all(p is not None and p >= 0 for p in pesos.values()) and sum(pesos.values()) > 0:
            total = sum(pesos.values())
            destinos = [(balde_da_celula(chave), peso / total) for chave, peso in pesos.items()]
            nes_rateadas.append(ne)
        else:
            destinos = [(balde(sem_celula), 1.0)]
            nes_sem_rateio.append(ne)
        for alvo, fracao in destinos:
            alvo.somar("executado", None if pd.isna(executado) else float(executado) * fracao)
            alvo.somar("projetado", None if pd.isna(projetado) else float(projetado) * fracao)
    if nes_rateadas:
        avisos.append(
            "NE com empenho em mais de uma célula tem o executado e o projetado rateados pelo empenhado de cada "
            "célula: " + ", ".join(nes_rateadas) + "."
        )
    if nes_sem_rateio:
        avisos.append(
            "NE sem célula identificável ou sem como ratear (empenhado nulo, negativo ou total zero) ficou em "
            "'Sem célula': " + ", ".join(nes_sem_rateio) + "."
        )

    # --- Contrato ATIVO sem NE (necessidade contratual): sem célula -------------------------------
    contratos_disponiveis = res.executado.get(ORIGEM_CONTRATOS) is not None
    if contratos_disponiveis and ativos_sem_ne is not None and len(ativos_sem_ne):
        projetado_ne = soma_ou_nulo(
            pd.to_numeric(consumo.loc[consumo["origem"] == ORIGEM_CONTRATOS, "projetado"], errors="coerce")
        )
        if projetado_ne is not None:  # mesma condição de `calcular_resultado`
            valor = (
                soma_ou_nulo(pd.to_numeric(ativos_sem_ne["necessidade"], errors="coerce"))
                if "necessidade" in ativos_sem_ne else None
            )
            balde(sem_celula).somar("projetado", valor)

    # --- Outras despesas previstas ------------------------------------------------------------------
    if res.projetado.get(OUTRAS_DESPESAS) is None:  # despesas ilegíveis: valor desconhecido
        balde(sem_celula).somar("projetado", None)
    else:
        for despesa in despesas_manuais:
            if not despesa.considerada:
                continue
            destino = balde(sem_celula) if despesa.celula is None else balde_da_celula(tuple(despesa.celula))
            destino.somar("projetado", despesa.valor)

    # --- Linhas e totais ----------------------------------------------------------------------------
    nome_gnd = _descricoes(celulas, "grupo_despesa_codigo", "grupo_despesa_descricao")
    nome_acao = _descricoes(celulas, "acao_codigo", "acao_descricao")
    registros = []
    for chave_balde, b in baldes.items():
        tipo = chave_balde[0]
        if tipo == TIPO_FORA and not any(b.valor.values()) and not any(b.nulo.values()):
            continue  # nada caiu fora das marcadas
        if tipo == TIPO_SEM_CELULA and not any(b.valor.values()) and not any(b.nulo.values()):
            continue
        gnd, acao = (chave_balde[1], chave_balde[2]) if tipo == TIPO_CELULA else (None, None)
        valores = {campo: b.final(campo) for campo in _CAMPOS}
        if indisponivel:
            valores["executado"] = valores["projetado"] = None
        resultado = None if any(v is None for v in valores.values()) else valores["dotacao"] - valores["executado"] - valores["projetado"]
        registros.append({
            "tipo": tipo, "gnd": gnd, "gnd_descricao": nome_gnd.get(str(gnd)) if gnd is not None else None,
            "acao": acao, "acao_descricao": nome_acao.get(str(acao)) if acao is not None else None,
            **valores, "resultado": resultado,
        })
    ordem = {TIPO_CELULA: 0, TIPO_FORA: 1, TIPO_SEM_CELULA: 2}
    registros.sort(key=lambda r: (ordem[r["tipo"]], str(r["gnd"] or ""), str(r["acao"] or "")))
    linhas = pd.DataFrame(registros, columns=COLUNAS_DETALHE)

    totais = {campo: soma_ou_nulo(linhas[campo].astype("float64")) if len(linhas) else 0.0 for campo in _CAMPOS}
    # o resultado total acompanha o cartão: se ele está indisponível (empenhado nulo, seleção vazia…), este também fica
    resultado_total = (
        None if res.resultado is None or any(v is None for v in totais.values())
        else totais["dotacao"] - totais["executado"] - totais["projetado"]
    )
    diferencas = [
        abs(detalhe - cartao)
        for detalhe, cartao in (
            (totais["dotacao"], res.dotacao), (totais["executado"], res.executado_total),
            (totais["projetado"], res.projetado_total), (resultado_total, None if res.resultado is None else res.resultado - res.receitas_proprias),
        )
        if detalhe is not None and cartao is not None
    ]
    detalhe = DetalheGndAcao(
        linhas=linhas, dotacao=totais["dotacao"], executado=totais["executado"], projetado=totais["projetado"],
        resultado=resultado_total, diferenca_conferencia=max(diferencas, default=0.0), avisos=avisos,
    )
    if not detalhe.fecha:
        detalhe.avisos.append(
            f"O detalhamento por GND e Ação não fecha com os cartões: diferença de R$ {detalhe.diferenca_conferencia:,.2f}."
        )
    return detalhe
