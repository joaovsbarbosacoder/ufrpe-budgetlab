"""
Linha do tempo por competência de um contrato: Liquidação por Competência (relatório do Tesouro) × instrumentos de
cobrança do Contratos.gov (11/10/2026).

Camada: regra pura (pandas/datetime; sem Streamlit, sem I/O). Somente LEITURA. Pedido do usuário: dentro do cadastro
de cada contrato de Contínuos, seletor de exercício e, mês a mês, a liquidação do relatório e, abaixo, as notas do
gov — os dois quando houver, "sem registro" no que faltar; quando só houver nota, o elemento de despesa do empenho
(o relatório não traz competência dos empenhos de DEA, elemento 92).

Regras (decisões do usuário, 11/10/2026):
  * Todas as NEs do contrato (as do Contratos.gov e a do cadastro) entram no cálculo; a escolha de quais ficam em
    evidência é um FILTRO POR MÊS (`filtrar_mes`), com padrão nas NEs da 20RK (`padrao_do_mes`). O que fica fora do
    filtro é mostrado como valor "fora do filtro" — nada some em silêncio.
  * Notas: só as liquidadas (com data de liquidação); valor por NE (`empenhos`); competência por `referencias`.
    1 competência → o valor de cada NE; 1 NE → o valor de cada competência; várias × várias → rateio proporcional
    (marcado). Nota com mesmo número, valor e NEs de outra do contrato = duplicada: sinalizada e contada uma vez.
  * Relatório e notas NUNCA são somados entre si: aparecem lado a lado, com a diferença.
  * CONCILIAÇÃO DE DUPLICIDADES (`ajustar_mes`, decisão do usuário 11/10/2026): as diferenças costumam ser notas
    canceladas/substituídas cujo cancelamento não foi informado no Contratos.gov. Por NE, quando as notas somam MAIS que
    o relatório, procura-se a MENOR combinação de notas cuja retirada fecha o relatório (tolerância R$ 1): combinação
    única = "provável cancelamento não informado" (retirada só na SUGESTÃO, em memória); mais de uma = ambíguo (as
    alternativas são mostradas, nunca se desempata); nenhuma = sem conclusão. Notas a MENOS que o relatório não são
    cancelamento e nada se infere. Nada é gravado nem alterado no dado do gov.

Contrato público:
    ItemNota, MesConciliado, EmpenhoInfo, AjusteMes
    ajustar_mes(mes) -> AjusteMes
    empenhos_do_contrato(empenhos_gov, contrato_id, ne_cadastro=None, natureza_cadastro=None) -> dict[ne, EmpenhoInfo]
    nes_do_mes(mes) -> list[str]
    padrao_do_mes(mes, empenhos) -> list[str]
    filtrar_mes(mes, selecionadas) -> MesConciliado
    naturezas_20rk(empenhos_gov, contrato_id, ne_cadastro=None, natureza_cadastro=None) -> dict[ne, natureza | None]
    itens_das_notas(faturas, naturezas) -> (DataFrame, fora_do_recorte: int)
    conciliar_exercicio(ano, relatorio, itens, naturezas) -> list[MesConciliado]
    exercicios_disponiveis(relatorio, itens, naturezas) -> list[int]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from itertools import combinations

import pandas as pd

TOLERANCIA = 1.0  # R$: diferença até este valor = "batem"

COLUNAS_ITENS = ["ne", "ano", "mes", "valor", "nota", "fatura_id", "rateada", "duplicada"]


@dataclass(frozen=True)
class EmpenhoInfo:
    natureza: str | None  # "339092 - DESPESAS ..."; None = não identificada
    plano_interno: str | None  # "M20RKG01SCN - GESTAO ..."; None = sem plano interno
    da_20rk: bool = False  # plano interno com "20RK", ou a NE do próprio cadastro de Contínuos

    @property
    def acao(self) -> str:
        """"20RK" quando é; senão o código do plano interno (ex.: "L20RLP01SCN"); "—" sem plano interno."""
        if self.da_20rk:
            return "20RK"
        return (self.plano_interno or "—").split(" - ")[0].strip() or "—"

    @property
    def elemento(self) -> str | None:
        codigo = (self.natureza or "")[:6]
        return codigo[4:6] if len(codigo) == 6 and codigo.isdigit() else None


@dataclass(frozen=True)
class ItemNota:
    ne: str
    valor: float
    nota: str
    rateada: bool
    duplicada: bool
    natureza: str | None  # ex.: "339092 - DESPESAS DE EXERCICIOS ANTERIORES"; None = não identificado

    @property
    def elemento(self) -> str | None:
        codigo = (self.natureza or "")[:6]
        return codigo[4:6] if len(codigo) == 6 and codigo.isdigit() else None


@dataclass(frozen=True)
class MesConciliado:
    ano: int
    mes: int
    relatorio: float | None  # None = sem registro no relatório
    relatorio_por_ne: dict[str, float] = field(default_factory=dict)
    notas: float | None = None  # None = sem registro de nota (duplicadas não somam)
    itens: list[ItemNota] = field(default_factory=list)
    #: valor (relatório + notas) das NEs desmarcadas no filtro do mês; `None` = nenhuma NE fora
    fora_do_filtro_relatorio: float | None = None
    fora_do_filtro_notas: float | None = None
    nes_fora: tuple[str, ...] = ()

    @property
    def situacao(self) -> str:
        if self.relatorio is None and self.notas is None:
            return "sem_registro"
        if self.notas is None:
            return "so_relatorio"
        if self.relatorio is None:
            return "so_notas"
        return "batem" if abs(self.relatorio - self.notas) <= TOLERANCIA else "divergem"

    @property
    def diferenca(self) -> float | None:
        if self.relatorio is None or self.notas is None:
            return None
        return self.notas - self.relatorio


MAX_NOTAS_BUSCA = 16  # acima disso a busca de combinações não é feita (sem conclusão)
MAX_RETIRADAS = 6


@dataclass(frozen=True)
class AjusteMes:
    """Resultado da conciliação de duplicidades de um mês. Índices referem-se a `MesConciliado.itens`."""

    #: notas sugeridas como canceladas (combinação ÚNICA por NE)
    retiradas: tuple[int, ...] = ()
    #: por NE ambígua: as combinações possíveis
    alternativas: tuple[tuple[str, tuple[tuple[int, ...], ...]], ...] = ()
    #: soma das notas válidas sem as retiradas (None = sem nota)
    notas_ajustadas: float | None = None
    situacao: str = "sem_ajuste"  # sem_ajuste | batem_ajustado | ambiguo


def _melhores_combinacoes(valores: list[float], alvo: float) -> list[tuple[int, ...]]:
    """As combinações de MENOR tamanho cuja soma é `alvo` (±TOLERANCIA); vazio se não houver (ou muitas notas)."""
    if len(valores) > MAX_NOTAS_BUSCA:
        return []
    for k in range(1, min(len(valores), MAX_RETIRADAS) + 1):
        achadas = [c for c in combinations(range(len(valores)), k) if abs(sum(valores[i] for i in c) - alvo) <= TOLERANCIA]
        if achadas:
            return achadas
    return []


def ajustar_mes(mes: "MesConciliado") -> AjusteMes:
    """Conciliação de duplicidades do mês (já filtrado): ver docstring do módulo."""

    retiradas: list[int] = []
    alternativas: list[tuple[str, tuple[tuple[int, ...], ...]]] = []
    for ne, rel in mes.relatorio_por_ne.items():
        indices = [i for i, item in enumerate(mes.itens) if item.ne == ne and not item.duplicada]
        total = sum(mes.itens[i].valor for i in indices)
        if not indices or total - rel <= TOLERANCIA:
            continue  # sem nota, ou notas já batem / a menos: nada a inferir
        combos = _melhores_combinacoes([mes.itens[i].valor for i in indices], total - rel)
        if len(combos) == 1:
            retiradas += [indices[j] for j in combos[0]]
        elif len(combos) > 1:
            alternativas.append((ne, tuple(tuple(indices[j] for j in c) for c in combos)))
    if not retiradas and not alternativas:
        return AjusteMes(notas_ajustadas=mes.notas)
    validos = [item.valor for i, item in enumerate(mes.itens) if not item.duplicada and i not in set(retiradas)]
    ajustadas = sum(validos) if validos else None
    if alternativas:
        situacao = "ambiguo"
    elif mes.relatorio is not None and ajustadas is not None and abs(ajustadas - mes.relatorio) <= TOLERANCIA:
        situacao = "batem_ajustado"
    else:
        situacao = "sem_ajuste"
    return AjusteMes(tuple(sorted(retiradas)), tuple(alternativas), ajustadas, situacao)


def _vazio(valor: object) -> bool:
    return valor is None or (isinstance(valor, float) and pd.isna(valor))


def empenhos_do_contrato(
    empenhos_gov: pd.DataFrame | None, contrato_id: object, ne_cadastro: object = None, natureza_cadastro: object = None,
) -> dict[str, EmpenhoInfo]:
    """TODAS as NEs do contrato no Contratos.gov (com natureza e plano interno) e a NE do cadastro de Contínuos (que é da
    20RK por definição, mesmo sem par no gov)."""

    resultado: dict[str, EmpenhoInfo] = {}
    if empenhos_gov is not None and not empenhos_gov.empty and not _vazio(contrato_id):
        recorte = empenhos_gov[empenhos_gov["contrato_id"].astype(str) == str(contrato_id)]
        for _, empenho in recorte.iterrows():
            if _vazio(empenho.get("ne")):
                continue
            natureza, pi = empenho.get("natureza_despesa"), empenho.get("plano_interno")
            resultado[str(empenho["ne"])] = EmpenhoInfo(
                None if _vazio(natureza) else str(natureza), None if _vazio(pi) else str(pi), "20RK" in str(pi or ""),
            )
    if not _vazio(ne_cadastro) and str(ne_cadastro).strip():
        ne = str(ne_cadastro).strip()
        atual = resultado.get(ne)
        natureza = atual.natureza if atual and atual.natureza else (None if _vazio(natureza_cadastro) else str(natureza_cadastro))
        resultado[ne] = EmpenhoInfo(natureza, atual.plano_interno if atual else None, True)
    return resultado


def nes_do_mes(mes: "MesConciliado") -> list[str]:
    """NEs que aparecem no mês em qualquer das fontes (relatório ou notas), em ordem."""
    return sorted(set(mes.relatorio_por_ne) | {item.ne for item in mes.itens})


def padrao_do_mes(mes: "MesConciliado", empenhos: dict[str, EmpenhoInfo]) -> list[str]:
    """Seleção inicial do filtro do mês: as NEs da 20RK que aparecem nele; se não houver nenhuma, todas."""
    presentes = nes_do_mes(mes)
    da_20rk = [ne for ne in presentes if empenhos.get(ne) is not None and empenhos[ne].da_20rk]
    return da_20rk or presentes


def filtrar_mes(mes: "MesConciliado", selecionadas) -> "MesConciliado":
    """O mês só com as NEs `selecionadas`: relatório e notas recalculados (as duplicadas não somam); o valor das NEs
    desmarcadas fica em `fora_do_filtro_*`. Seleção vazia = tudo fora."""

    escolhidas = set(selecionadas)
    rel = {ne: v for ne, v in mes.relatorio_por_ne.items() if ne in escolhidas}
    itens = [item for item in mes.itens if item.ne in escolhidas]
    fora_rel = [v for ne, v in mes.relatorio_por_ne.items() if ne not in escolhidas]
    fora_itens = [item for item in mes.itens if item.ne not in escolhidas and not item.duplicada]
    validas = [item.valor for item in itens if not item.duplicada]
    nes_fora = sorted((set(mes.relatorio_por_ne) | {i.ne for i in mes.itens}) - escolhidas)
    return MesConciliado(
        ano=mes.ano, mes=mes.mes, relatorio=sum(rel.values()) if rel else None, relatorio_por_ne=rel,
        notas=sum(validas) if validas else None, itens=itens,
        fora_do_filtro_relatorio=sum(fora_rel) if fora_rel else None,
        fora_do_filtro_notas=sum(i.valor for i in fora_itens) if fora_itens else None,
        nes_fora=tuple(nes_fora),
    )


def naturezas_20rk(
    empenhos_gov: pd.DataFrame | None, contrato_id: object, ne_cadastro: object = None, natureza_cadastro: object = None,
) -> dict[str, str | None]:
    """NEs da 20RK do contrato → natureza de despesa (texto do gov, ex. "339092 - DESPESAS ..."). A NE do cadastro de
    Contínuos (parcela 20RK por definição) entra mesmo sem par no gov, com a natureza do cadastro (ou nula)."""

    resultado: dict[str, str | None] = {}
    if empenhos_gov is not None and not empenhos_gov.empty and not _vazio(contrato_id):
        recorte = empenhos_gov[empenhos_gov["contrato_id"].astype(str) == str(contrato_id)]
        for _, empenho in recorte.iterrows():
            if "20RK" in str(empenho.get("plano_interno") or "") and not _vazio(empenho.get("ne")):
                natureza = empenho.get("natureza_despesa")
                resultado[str(empenho["ne"])] = None if _vazio(natureza) else str(natureza)
    if not _vazio(ne_cadastro) and str(ne_cadastro).strip():
        ne = str(ne_cadastro).strip()
        if resultado.get(ne) is None:
            resultado[ne] = None if _vazio(natureza_cadastro) else str(natureza_cadastro)
    return resultado


def itens_das_notas(faturas: pd.DataFrame | None, naturezas: dict[str, str | None]) -> tuple[pd.DataFrame, int]:
    """Uma linha por (NE do recorte, competência, nota) das notas liquidadas, e quantas notas liquidadas ficaram fora
    do recorte (nenhuma NE da 20RK do contrato)."""

    if faturas is None or faturas.empty:
        return pd.DataFrame(columns=COLUNAS_ITENS), 0
    liquidadas = faturas[faturas["data_liquidacao"].apply(lambda d: isinstance(d, date))]
    linhas, fora, vistas = [], 0, set()
    for _, nota in liquidadas.sort_values("fatura_id").iterrows():
        empenhos = [(ne, float(v)) for ne, _, v in nota["empenhos"] if ne and not _vazio(v)]
        referencias = [(a, m, float(v)) for a, m, v in nota["referencias"] if not _vazio(v)]
        if not any(ne in naturezas for ne, _ in empenhos):
            fora += 1
            continue
        if not referencias:
            continue
        assinatura = (nota["numero"], nota["valor"], tuple(sorted(ne for ne, _ in empenhos)))
        duplicada = assinatura in vistas
        vistas.add(assinatura)
        rateada = len(empenhos) > 1 and len(referencias) > 1
        total_refs = sum(v for _, _, v in referencias)
        for ne, valor_ne in empenhos:
            if ne not in naturezas:
                continue
            for ano, mes, valor_ref in referencias:
                if len(referencias) == 1:
                    parte = valor_ne
                elif len(empenhos) == 1:
                    parte = valor_ref
                else:
                    parte = valor_ne * valor_ref / total_refs if total_refs else 0.0
                linhas.append({
                    "ne": ne, "ano": int(ano), "mes": int(mes), "valor": parte, "nota": str(nota["numero"] or "—"),
                    "fatura_id": str(nota["fatura_id"]), "rateada": rateada, "duplicada": duplicada,
                })
    return pd.DataFrame(linhas, columns=COLUNAS_ITENS), fora


def _relatorio_do_contrato(relatorio: pd.DataFrame | None, nes: set[str]) -> pd.DataFrame:
    """`relatorio` = Liquidação por Competência por (NE, mês) com `ne_curta`, `ano_mes` (AAAAMM) e `valor`."""
    if relatorio is None or relatorio.empty or not nes:
        return pd.DataFrame(columns=["ne_curta", "ano_mes", "valor"])
    return relatorio[relatorio["ne_curta"].isin(nes)]


def conciliar_exercicio(
    ano: int, relatorio: pd.DataFrame | None, itens: pd.DataFrame, naturezas: dict[str, str | None],
) -> list[MesConciliado]:
    """Os 12 meses do exercício: relatório (soma das NEs do recorte) e notas (sem as duplicadas), com o detalhe por NE."""

    rel = _relatorio_do_contrato(relatorio, set(naturezas))
    meses = []
    for mes in range(1, 13):
        rel_mes = rel[rel["ano_mes"].astype(int) == ano * 100 + mes]
        por_ne = {str(ne): float(v) for ne, v in rel_mes.groupby("ne_curta")["valor"].sum().items()}
        notas_mes = itens[(itens["ano"] == ano) & (itens["mes"] == mes)] if not itens.empty else itens
        lista = [
            ItemNota(str(r.ne), float(r.valor), str(r.nota), bool(r.rateada), bool(r.duplicada), naturezas.get(str(r.ne)))
            for r in notas_mes.itertuples()
        ]
        validas = [i.valor for i in lista if not i.duplicada]
        meses.append(MesConciliado(
            ano=ano, mes=mes, relatorio=sum(por_ne.values()) if por_ne else None, relatorio_por_ne=por_ne,
            notas=sum(validas) if validas else None, itens=lista,
        ))
    return meses


def exercicios_disponiveis(relatorio: pd.DataFrame | None, itens: pd.DataFrame, naturezas: dict[str, str | None]) -> list[int]:
    """Anos com dado em alguma das fontes, do mais recente ao mais antigo."""
    anos = {int(a) // 100 for a in _relatorio_do_contrato(relatorio, set(naturezas))["ano_mes"]}
    if not itens.empty:
        anos |= {int(a) for a in itens["ano"]}
    return sorted(anos, reverse=True)
