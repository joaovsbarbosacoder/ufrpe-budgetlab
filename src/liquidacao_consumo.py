"""Liquidação por Competência "pelo consumo do orçamento" (13/10/2026).

Camada: regra de relatório. Não lê planilha nem importa Streamlit; só recebe DataFrames e devolve
DataFrames derivados (as entradas não são alteradas).

Problema: uma NE liquidada de UMA vez (um só documento) pode ter a competência espalhada por vários
meses, inclusive de exercícios seguintes (ex.: 2026NE000551, contrato anual pago antecipado: liquidado
em out/2026 com competência de out/2026 a set/2027). O empenho consome o orçamento de uma vez, mas a
competência mostra só uma fração por mês — e a Projeção pela Execução / Necessidade de Empenho, que
medem o consumo do orçamento, projetavam como se o contrato ainda tivesse quase tudo a liquidar.

REGRA (decisão do usuário, 13/10/2026): NE com liquidação cuja competência cai em exercício POSTERIOR
ao do relatório passa a ser medida pelo mês do LANÇAMENTO (Execução Mensal, coluna `liquidada`): a
liquidação inteira conta no mês em que foi lançada — SE o total lançado fecha com o total da competência da NE.
Total divergente (a Execução Mensal não cobre toda a competência): a NE fica pela competência e é sinalizada
(nada é descartado em silêncio). As demais NEs seguem pela competência, como antes.
A conciliação por competência (Contratos.gov) NÃO usa esta troca — continua pela competência.

Limite conhecido: a Execução Mensal dá o mês de lançamento por NE, não por documento; se a mesma NE
tiver outras liquidações de competência normal, todas passam a valer pelo mês do lançamento. NE sem
liquidação na Execução Mensal mantém a competência (não há mês de lançamento a usar) e é sinalizada.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class CompetenciaPeloConsumo:
    #: mesmo formato da entrada; as NEs trocadas trazem o liquidado por mês de lançamento
    dados: pd.DataFrame
    #: NEs (curtas) medidas pelo mês do lançamento
    nes_trocadas: list[str] = field(default_factory=list)
    #: NEs com competência futura que ficaram pela competência (sem liquidação na Execução Mensal)
    nes_sem_lancamento: list[str] = field(default_factory=list)
    #: NE com competência futura mantida pela competência porque os totais não fecham:
    #: NE → (total pela competência, total lançado na Execução Mensal)
    divergencias: dict[str, tuple[float, float]] = field(default_factory=dict)

    def avisos(self) -> list[str]:
        textos = []
        if self.nes_trocadas:
            textos.append(
                "Liquidação medida pelo mês do lançamento (competência em exercício posterior, o empenho consome "
                "o orçamento de uma vez): " + ", ".join(self.nes_trocadas) + "."
            )
        if self.nes_sem_lancamento:
            textos.append(
                "Competência em exercício posterior, mas sem liquidação na Execução Mensal — mantida a competência: "
                + ", ".join(self.nes_sem_lancamento) + "."
            )
        for ne, (competencia, lancamento) in self.divergencias.items():
            textos.append(
                f"{ne}: competência em exercício posterior, mas o total pela competência ({competencia:,.2f}) difere do "
                f"lançado na Execução Mensal ({lancamento:,.2f}) — mantida a competência."
            )
        return textos


def competencia_pelo_consumo(
    competencia: pd.DataFrame | None, lancamento: pd.DataFrame | None, exercicio: int,
) -> CompetenciaPeloConsumo | None:
    """`competencia`: `ne_curta`, `ano_mes` (AAAAMM), `valor` (+ demais colunas, preservadas) — Liquidação por
    Competência por (NE, mês). `lancamento`: `ne_curta`, `ano_mes`, `liquidada` — Execução Mensal por mês de
    lançamento. `None` na entrada devolve `None` (base indisponível)."""

    if competencia is None:
        return None
    if competencia.empty:
        return CompetenciaPeloConsumo(competencia.copy())

    ano = competencia["ano_mes"].astype("int64") // 100
    futuras = competencia[(ano > exercicio) & competencia["valor"].notna() & (competencia["valor"] != 0)]
    candidatas = sorted(futuras["ne_curta"].dropna().unique())
    if not candidatas:
        return CompetenciaPeloConsumo(competencia.copy())

    lancadas = pd.DataFrame(columns=["ne_ccor", "ne_curta", "ano_mes", "valor"])
    if lancamento is not None and not lancamento.empty:
        base = lancamento[lancamento["ne_curta"].isin(candidatas) & lancamento["liquidada"].notna()
                          & (lancamento["liquidada"] != 0)]
        renomeada = base.rename(columns={"liquidada": "valor"})
        lancadas = renomeada[[c for c in ("ne_ccor", "ne_curta", "ano_mes", "valor") if c in renomeada.columns]]

    com_lancamento = sorted(lancadas["ne_curta"].unique())
    sem_lancamento = [ne for ne in candidatas if ne not in com_lancamento]
    divergencias = {}
    trocadas = []
    for ne in com_lancamento:
        total_competencia = float(competencia.loc[competencia["ne_curta"] == ne, "valor"].sum())
        total_lancado = float(lancadas.loc[lancadas["ne_curta"] == ne, "valor"].sum())
        if abs(total_competencia - total_lancado) > 0.005:
            divergencias[ne] = (total_competencia, total_lancado)
        else:
            trocadas.append(ne)

    mantidas = competencia[~competencia["ne_curta"].isin(trocadas)]
    dados = (
        pd.concat([mantidas, lancadas[lancadas["ne_curta"].isin(trocadas)]], ignore_index=True)
        if trocadas else competencia.copy()
    )
    dados = dados.sort_values(["ne_curta", "ano_mes"], kind="stable").reset_index(drop=True)
    return CompetenciaPeloConsumo(dados, trocadas, sem_lancamento, divergencias)
