"""Despesa estimada por PTRES na "Cobertura orçamentária" de Contratos Contínuos, na base "projeção pela execução" (29/10/2026).

Mesmo critério já aplicado em Bolsas (`src/bolsas_despesa_estimada.py`): em vez da despesa anual contratual (despesa mensal × meses do
ano), a despesa do contrato é **já liquidado + projetado a realizar** da "Projeção pela execução" (`executado = valor empenhado −
saldo`, `projetado = projetado_execucao`), as mesmas medidas do Resultado Orçamentário.

Diferente de Bolsas, em Contratos nada é presumido nem descartado em silêncio. Ficam pela `despesa_anual` da página (e a tela diz
quantos) os contratos:

  * SUSPENSOS: já valem pelo que foi empenhado (`com_efeitos_da_suspensao`, decisão de 06/10/2026);
  * com ADITIVO PREVISTO: a despesa inclui o aditivo estimado, que a projeção pela execução não conhece;
  * com NE COMPARTILHADA por mais de uma linha: nenhum rateio é presumido (mesma regra da suspensão);
  * sem NE, sem linha no relatório ou com executado/projetado nulo (nulo não vira zero).

A NE compartilhada é detectada na tabela COMPLETA, não na filtrada pela busca: filtrar não pode transformar uma NE compartilhada em NE
de linha única. Regra pura: recebe DataFrames; não importa Streamlit nem lê arquivo.
"""

from __future__ import annotations

import pandas as pd

from src.bolsas_despesa_estimada import DespesaPorPtres
from src.contratos_continuos import DESPESA_CONTRATUAL


def _numerico(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce")


def despesa_estimada_por_ptres(
    filtrado: pd.DataFrame,
    linhas_projecao: pd.DataFrame | None,
    tabela_completa: pd.DataFrame | None = None,
) -> DespesaPorPtres:
    """`filtrado`: contratos com `ptres`, `ne_curta`, `despesa_anual`, `despesa_anual_base` e, se houver, `tem_aditivo_previsto`.
    `linhas_projecao`: `RelatorioProjecaoExecucao.linhas` (`ne_curta`, `valor_empenhado`, `saldo`, `projetado_execucao`) ou `None`
    (base contratual / projeção indisponível: tudo pela despesa anual). `tabela_completa`: a tabela antes da busca, para detectar NE
    compartilhada (padrão: `filtrado`)."""

    base = filtrado[["ptres", "ne_curta", "despesa_anual"]].copy()
    base["despesa_anual"] = _numerico(base["despesa_anual"])
    base["despesa"] = base["despesa_anual"]
    base["pela_execucao"] = False

    if linhas_projecao is not None and len(linhas_projecao):
        linhas = linhas_projecao.drop_duplicates("ne_curta").set_index("ne_curta")
        executado = _numerico(linhas["valor_empenhado"]) - _numerico(linhas["saldo"])
        total_ne = executado + _numerico(linhas["projetado_execucao"])  # nulo em qualquer parte deixa o total nulo
        valor_da_ne = base["ne_curta"].map(total_ne)

        universo = (tabela_completa if tabela_completa is not None else filtrado)["ne_curta"]
        compartilhadas = set(universo[universo.notna() & universo.duplicated(keep=False)])
        contratual = filtrado["despesa_anual_base"].eq(DESPESA_CONTRATUAL).fillna(False).astype(bool)
        com_aditivo = (
            filtrado["tem_aditivo_previsto"].fillna(False).astype(bool)
            if "tem_aditivo_previsto" in filtrado.columns else pd.Series(False, index=filtrado.index)
        )
        elegivel = (
            contratual & ~com_aditivo & base["ne_curta"].notna() & ~base["ne_curta"].isin(compartilhadas) & valor_da_ne.notna()
        )
        base.loc[elegivel, "despesa"] = valor_da_ne[elegivel]
        base.loc[elegivel, "pela_execucao"] = True

    despesa = base.groupby("ptres")["despesa"].sum(min_count=1).fillna(0.0)
    despesa.index.name = "ptres_codigo"
    return DespesaPorPtres(
        despesa=despesa,
        pela_execucao=int(base["pela_execucao"].sum()),
        pelo_cadastro=int((~base["pela_execucao"]).sum()),
        total_cadastro=float(base["despesa_anual"].sum()),
        total_estimado=float(base["despesa"].sum()),
    )
