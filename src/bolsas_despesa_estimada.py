"""Despesa estimada por PTRES na "Cobertura orçamentária" de Bolsas e Auxílios (pedido do usuário, 22/10/2026).

Antes, a despesa de cada PTRES era a soma do `valor_anual` cadastrado (valor mensal × 12 meses do ano), sem olhar a execução.
Isso superestimava a bolsa que só começou a ser paga depois de janeiro ou que pagou menos bolsistas em algum mês: no PEC-G
(Promisaes, PTRES 230404) eram R$ 44.784 contra R$ 36.076 realmente esperados (R$ 24.880 já liquidados + R$ 11.196 projetados).

Agora a despesa da bolsa que tem NE no relatório "Projeção pela execução" é `executado + projetado a realizar`, as mesmas
medidas que o Resultado Orçamentário usa: `executado = valor empenhado − saldo` e `projetado = projetado_execucao`. Bolsa sem NE,
sem linha no relatório ou com executado/projetado nulo continua pelo `valor_anual` do cadastro (nulo não vira zero, e nada deixa
de ser contado), e a contagem desse recurso volta para a tela. NE compartilhada por mais de uma bolsa é repartida pelo peso do
`valor_anual` de cada uma (partes iguais se não houver peso), para não contar a NE duas vezes.

Regra pura: recebe DataFrames e devolve o resultado; não importa Streamlit nem lê arquivo.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DespesaPorPtres:
    #: despesa estimada por PTRES (índice `ptres_codigo`)
    despesa: pd.Series
    #: bolsas cuja despesa veio da execução (executado + projetado)
    pela_execucao: int
    #: bolsas que ficaram pelo `valor_anual` do cadastro (sem NE, sem linha no relatório ou valor nulo)
    pelo_cadastro: int
    #: total pelo cadastro (valor anual cheio), para comparação
    total_cadastro: float
    total_estimado: float


def _numerico(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce")


def despesa_estimada_por_ptres(filtrado: pd.DataFrame, linhas_projecao: pd.DataFrame | None) -> DespesaPorPtres:
    """`filtrado`: cadastro de Bolsas com `ptres`, `ne_curta` e `valor_anual`. `linhas_projecao`: `RelatorioProjecaoExecucao.linhas`
    (`ne_curta`, `valor_empenhado`, `saldo`, `projetado_execucao`) ou `None` quando a projeção está indisponível."""

    base = filtrado[["ptres", "ne_curta", "valor_anual"]].copy()
    base["valor_anual"] = _numerico(base["valor_anual"])
    base["despesa"] = base["valor_anual"]
    base["pela_execucao"] = False

    if linhas_projecao is not None and len(linhas_projecao):
        linhas = linhas_projecao.drop_duplicates("ne_curta").set_index("ne_curta")
        executado = _numerico(linhas["valor_empenhado"]) - _numerico(linhas["saldo"])
        total_ne = executado + _numerico(linhas["projetado_execucao"])  # nulo em qualquer parte deixa o total nulo
        valor_da_ne = base["ne_curta"].map(total_ne)

        peso_ne = base.groupby("ne_curta")["valor_anual"].transform(lambda s: s.fillna(0).sum())
        quantidade_ne = base.groupby("ne_curta")["ne_curta"].transform("size")
        fracao = (base["valor_anual"].fillna(0) / peso_ne).where(peso_ne > 0, 1.0 / quantidade_ne)

        usa = base["ne_curta"].notna() & valor_da_ne.notna()
        base.loc[usa, "despesa"] = (valor_da_ne * fracao)[usa]
        base.loc[usa, "pela_execucao"] = True

    despesa = base.groupby("ptres")["despesa"].sum(min_count=1).fillna(0.0)
    despesa.index.name = "ptres_codigo"
    return DespesaPorPtres(
        despesa=despesa,
        pela_execucao=int(base["pela_execucao"].sum()),
        pelo_cadastro=int((~base["pela_execucao"]).sum()),
        total_cadastro=float(base["valor_anual"].sum()),
        total_estimado=float(base["despesa"].sum()),
    )
