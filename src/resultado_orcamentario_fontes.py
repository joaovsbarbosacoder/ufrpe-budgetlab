"""Montagem compartilhada de Contratos Contínuos e Bolsas e Auxílios para o "Resultado Orçamentário".

Extraída de `app_pages/contratos_continuos.py` e `app_pages/bolsas_auxilios.py` (08/10/2026): a nova
página precisa das mesmas tabelas derivadas e dos mesmos relatórios "Projeção pela Execução" que essas
duas páginas já montam. Refatoração pura — a lógica é a que estava nas páginas, sem alteração; as páginas
passaram a chamar estas funções para que os números nunca divirjam.
"""

from __future__ import annotations

import pandas as pd

from src import bolsas_auxilios as _bolsas
from src import contratos_continuos as _contratos
from src.projecao_execucao_bolsas import entrada_relatorio as _entrada_projecao_bolsas
from src.relatorio_necessidade_empenho import necessidade_por_ne
from src.relatorio_projecao_execucao import BOLSAS_AUXILIOS, RelatorioProjecaoExecucao, montar_relatorio


def tabela_contratos(
    cadastro: pd.DataFrame,
    por_ne_execucao: pd.DataFrame,
    indice_liquidado_competencia: pd.Series | None,
    sugestao_inicio_por_ne: pd.Series,
    meses_pagos: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Cadastro de Contratos Contínuos com as colunas derivadas que a página monta.

    `meses_pagos` (opcional): Pagamentos de Contratos por contrato (`com_meses_pagos`). É só de exibição,
    mas a página o aplica ENTRE `com_saldo_execucao` e as colunas derivadas; a posição é preservada aqui
    para que as colunas da tabela fiquem na mesma ordem de antes (decisão de 08/10/2026: aplicar depois
    reordenaria as colunas). Sem ele (caso do Resultado Orçamentário), a tabela não ganha `meses_pagos`."""

    dataframe = _contratos.com_saldo_execucao(cadastro, por_ne_execucao, indice_liquidado_competencia)
    if meses_pagos is not None:
        dataframe = _contratos.com_meses_pagos(dataframe, meses_pagos)

    # "Início da Execução" (mês do primeiro empenho de cada NE, auto-detectado da base mensal) e
    # valor empenhado autoritativo — só para a sugestão inicial "por calendário" do Relatório de
    # Reforço (pedido explícito, ver `src.necessidade_empenho.necessidade_ate_mes_vigente`);
    # nenhum outro quadro da página usa essas duas colunas.
    dataframe["valor_empenhado_autoritativo"] = dataframe["valor_empenhado_execucao"].fillna(dataframe["valor_empenhado"])
    # mesmo padrão de fallback usado no resto da página (ex. linha 1193, divergência de saldo) —
    # autoritativo (Execução Mensal) com o valor colado na planilha como reserva. Usado só para
    # evidenciar o saldo na tela do Relatório de Reforço/Anulação (pedido explícito).
    dataframe["saldo_autoritativo"] = dataframe["saldo_execucao"].fillna(dataframe["saldo_colado_planilha"])
    dataframe["inicio_execucao_efetivo"] = dataframe["inicio_execucao_mes"].fillna(
        dataframe["ne_curta"].map(sugestao_inicio_por_ne)
    )
    # Contrato SUSPENSO (06/10/2026): Despesa anual/Cobertura por PTRES passam a usar o já empenhado e o
    # "Saldo a liquidar (execução)" vira zero — ver `src.contratos_continuos.com_efeitos_da_suspensao`.
    return _contratos.com_efeitos_da_suspensao(dataframe)


def tabela_bolsas(
    cadastro: pd.DataFrame,
    por_ne_execucao: pd.DataFrame,
    sugestao_inicio_por_ne: pd.Series,
) -> pd.DataFrame:
    """Cadastro de Bolsas e Auxílios com as colunas derivadas que a página monta."""

    dataframe = _bolsas.com_saldo_execucao(cadastro, por_ne_execucao)

    # "Início da Execução" (mês do primeiro empenho de cada NE, auto-detectado da base mensal) e
    # valor empenhado autoritativo — só para a sugestão inicial "por calendário" do Relatório de
    # Reforço (pedido explícito, ver `src.necessidade_empenho.necessidade_ate_mes_vigente`) e, o início,
    # também como reserva para situar os meses de cada bolsa no relatório "Projeção pela execução"
    # (07/10/2026; lá o automático prefere o primeiro mês com liquidação por competência).
    dataframe["valor_empenhado_autoritativo"] = dataframe["valor_empenhado_execucao"].fillna(dataframe["valor_empenhado_tg"])
    # mesmo padrão de fallback do Resumo Consolidado (`_render_resumo_consolidado`) — autoritativo
    # (Execução Mensal) com o valor colado na planilha como reserva. Usado só para evidenciar o
    # saldo na tela do Relatório de Reforço/Anulação (pedido explícito), nenhum outro quadro usa.
    dataframe["saldo_autoritativo"] = dataframe["saldo_execucao"].fillna(dataframe["saldo_colado_planilha"])
    dataframe["inicio_execucao_efetivo"] = dataframe["inicio_execucao_mes"].fillna(
        dataframe["ne_curta"].map(sugestao_inicio_por_ne)
    )
    return dataframe


def projecao_contratos(
    tabela: pd.DataFrame,
    competencia: pd.DataFrame,
    exercicio: int,
    mes_referencia: int,
    antecessores: dict[str, str] | None = None,
) -> tuple[RelatorioProjecaoExecucao, pd.DataFrame]:
    """`(relatorio, sem_ne)` do "Projeção pela Execução" de Contratos. A necessidade vem de
    `necessidade_por_ne(tabela, None, exercicio)` — só LÊ o que o resto da página já calcula.
    `antecessores` (herança do fator para NE sem histórico) é escolhido na UI de Contratos; o Resultado
    Orçamentário não passa nenhum."""

    por_ne, sem_ne = necessidade_por_ne(tabela, None, exercicio)
    relatorio = montar_relatorio(por_ne, sem_ne, competencia, exercicio, mes_referencia, antecessores)
    return relatorio, sem_ne


def projecao_bolsas(
    tabela: pd.DataFrame,
    competencia: pd.DataFrame,
    exercicio: int,
    mes_referencia: int,
) -> tuple[RelatorioProjecaoExecucao, pd.DataFrame]:
    """`(relatorio, sem_ne)` do "Projeção pela Execução" de Bolsas e Auxílios (custos mensais e rótulos
    próprios, sem contrato antecessor)."""

    por_ne, sem_ne, custos = _entrada_projecao_bolsas(tabela, competencia, exercicio)
    relatorio = montar_relatorio(
        por_ne, sem_ne, competencia, exercicio, mes_referencia, custos=custos, rotulos=BOLSAS_AUXILIOS,
    )
    # Correção (08/10/2026, revisão final): em Bolsas o valor da necessidade dos itens sem NE vive na coluna
    # privada `_necessidade`; renomeia para `necessidade` (contrato do aviso e da tela). A página de Bolsas
    # não usa este quadro, só o Resultado Orçamentário.
    return relatorio, sem_ne.rename(columns={"_necessidade": "necessidade"})
