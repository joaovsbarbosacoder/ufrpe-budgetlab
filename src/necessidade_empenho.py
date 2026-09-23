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

from datetime import date

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


def necessidade_ate_mes_vigente(
    valor_mensal: pd.Series, valor_empenhado: pd.Series, inicio_execucao_mes: pd.Series,
    ano_referencia: int,
    hoje: date | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Quanto falta empenhar para acompanhar o calendário até o mês vigente — métrica
    diferente de `calcular_necessidade_empenho` (que compara empenhado × liquidado, execução
    real). Pedido explícito: "parametrize o sistema para que ele fique pronto para empenhar o
    que falta para o mês vigente" (ex.: despesa anual R$ 120 mil, já empenhado R$ 70 mil,
    estamos em outubro → deveria estar empenhado R$ 100 mil → sugestão R$ 30 mil).

    `inicio_execucao_mes` é o mês (1-12) em que a NE recebeu o primeiro empenho DENTRO do
    exercício `ano_referencia` — auto-detectado a partir da base mensal (`src.
    tesouro_execucao_mensal.primeiro_mes_com_empenho_por_ne`) ou informado manualmente no
    cadastro, quando o usuário perceber um erro na detecção (ver
    `app_pages/bolsas_auxilios.py`/`app_pages/contratos_continuos.py::_render_card`). Meses
    decorridos contados de forma inclusiva a partir desse mês (mês de início conta como 1º
    mês) — mesmo critério de calendário (ano civil, não vigência do contrato) já usado em
    "Necessidade até Dezembro" no Resumo Consolidado.

    `ano_referencia` é o exercício do cadastro sendo calculado (não necessariamente o ano
    corrente) — corrige um bug real na virada de exercício: sem ele, um cadastro de 2026 ainda
    não duplicado para 2027 (`src.cadastro_por_exercicio`, duplicação é manual) calculava
    `hoje.month - inicio_execucao_mes + 1` misturando o mês real de HOJE (já em 2027) com um
    `inicio_execucao_mes` de 2026 — para uma NE iniciada em outubro, isso dava `1 - 10 + 1 =
    -8`, sempre limitado (`clip`) a zero, subestimando a sugestão silenciosamente, sem nenhum
    aviso na tela. Regra: `hoje.year` só entra na conta quando bate com `ano_referencia`
    (exercício em andamento, comportamento de sempre); se `hoje` já passou do exercício
    (`ano_referencia` encerrado), o exercício inteiro já decorreu — usa dezembro (12) como mês
    vigente, não o mês real de hoje, que pertence a outro exercício.

    Nunca fica negativo: já ter empenhado mais do que o alvo do mês vigente não sugere
    "desempenhar", vira zero (mesmo critério de "Necessidade até Dezembro"). Usada só na
    sugestão inicial do Relatório de Reforço de Empenho (pedido explícito de escopo) — o
    "Meses de Saldo"/"Empenhar" de cada cartão continua vindo de
    `calcular_necessidade_empenho`, inalterado.
    """
    hoje = hoje or date.today()
    mes_vigente = 12 if hoje.year > ano_referencia else max(0, min(hoje.month, 12))
    if hoje.year < ano_referencia:
        mes_vigente = 0
    meses_decorridos = (mes_vigente - inicio_execucao_mes + 1).clip(lower=0)
    meses_empenhados_equivalente = valor_empenhado / valor_mensal.replace(0, pd.NA)
    meses_sugeridos = (meses_decorridos - meses_empenhados_equivalente).clip(lower=0)
    valor_sugerido = meses_sugeridos * valor_mensal
    return meses_sugeridos, valor_sugerido
