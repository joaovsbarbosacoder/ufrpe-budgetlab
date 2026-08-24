"""
Necessidade de empenho — regra de negócio compartilhada por Contratos Contínuos e Bolsas.

Camada: regra específica de negócio, não leitor, não interface. Depende só de pandas.

Contexto: as duas planilhas de origem têm uma coluna "MESES A EMPENHAR"/"EMPENHAR (R$)" que,
na prática, está vazia (Contratos Contínuos) ou preenchida à mão de forma inconsistente
(Bolsas) — não é uma fórmula confiável em nenhuma das duas. A fórmula real e validada contra
dado de verdade é a de "MESES DE SALDO" nas duas planilhas: `meses_empenhados - meses_liquidados`
(confirmado célula a célula nas duas bases — ver histórico da conversa). Este módulo recalcula
essa mesma conta como `meses_a_empenhar`, para não depender do campo manual da origem.
"""

from __future__ import annotations

import pandas as pd


def calcular_necessidade_empenho(
    meses_empenhados: pd.Series, meses_liquidados: pd.Series, valor_mensal: pd.Series
) -> tuple[pd.Series, pd.Series]:
    """meses_a_empenhar = meses_empenhados − meses_liquidados; valor_a_empenhar = valor_mensal × meses_a_empenhar.

    Mesma fórmula da coluna "MESES DE SALDO" já existente nas duas planilhas de origem
    (Contratos Contínuos e Bolsas), recalculada aqui para não depender do campo manual
    "MESES A EMPENHAR"/"EMPENHAR (R$)" de cada uma (vazio ou inconsistente na origem).
    """
    meses_a_empenhar = meses_empenhados - meses_liquidados
    valor_a_empenhar = valor_mensal * meses_a_empenhar
    return meses_a_empenhar, valor_a_empenhar
