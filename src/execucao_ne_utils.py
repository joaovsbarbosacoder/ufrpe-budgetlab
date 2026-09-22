"""Ligação por Nota de Empenho (NE) entre a Execução da Despesa — Anual OU Mensal — e outras
bases que citam a NE sem o prefixo de órgão/UG (Contratos Contínuos, Bolsas e Auxílios,
Contratos — Pagamentos, Consulta de Empenhos, Empenhos com Execução Retardada).

Camada: regra de negócio pura — não lê arquivo, não importa Streamlit, não depende de qual
base (`src.execucao_anual`/`src.tesouro_execucao_mensal`) produziu o DataFrame recebido. Só
espera as colunas `ne_ccor`/`empenhada`/`liquidada`/`paga`/`linha_origem`, presentes nas duas.

HISTÓRICO (22/09/2026): estas funções moravam em `src/execucao_anual.py` — mas nunca
dependeram de nada específico da base Anual (nem `agregar_por_ne`, que CADA base já expõe
com a agregação certa pra sua própria granularidade — ver `execucao_anual.agregar_por_ne`/
`tesouro_execucao_mensal.agregar_por_ne`). Extraídas pra cá como pré-requisito da migração
pedida pelo usuário: Bolsas/Contratos Contínuos/Contratos Pagamentos pararam de depender da
Execução Anual, usando a Execução Mensal (2024+) como fonte — ver
`app_pages/bolsas_auxilios.py`, `app_pages/contratos_continuos.py`,
`app_pages/contratos_pagamentos.py`. Consulta de Empenhos e Empenhos com Execução Retardada já
liam a Mensal antes disso; só trocaram de onde importam estas funções.

Contrato público:
    ne_curta(ne_ccor) -> str
    saldo_por_ne(por_ne) -> pd.DataFrame
    indice_saldo_por_ne_curta(por_ne_com_saldo) -> pd.Series
    indice_valor_empenhado_por_ne_curta(por_ne) -> pd.Series
    indice_liquidado_por_ne_curta(por_ne) -> pd.Series
    indice_valor_pago_por_ne_curta(por_ne) -> pd.Series
    detalhar_nota_empenho(df, ne_ccor) -> pd.DataFrame
"""

from __future__ import annotations

import pandas as pd


def ne_curta(ne_ccor: str) -> str:
    """Forma curta da NE (ex. "2026NE000100"), a partir do `ne_ccor` completo.

    O ano usado no marcador de busca vem do próprio `ne_ccor` (posições 11-14) — NÃO do Ano
    Lançamento, que pode divergir em NE de resto a pagar. Usar o Ano Lançamento aqui fazia a
    busca falhar exatamente nesse caso e devolver o `ne_ccor` completo em vez da forma curta.

    O prefixo de órgão/UG antes do ano tem tamanho fixo nas duas bases (11 dígitos), mas a
    busca pelo marcador "{ano}NE" é mais robusta que uma fatia posicional fixa caso esse
    prefixo varie em alguma UG diferente no futuro.
    """
    marcador = f"{ne_ccor[11:15]}NE"
    posicao = ne_ccor.find(marcador)
    return ne_ccor[posicao:] if posicao != -1 else ne_ccor


def saldo_por_ne(por_ne: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta a coluna `saldo` (empenhado − liquidado) a um DataFrame já agregado por NE
    (`agregar_por_ne` de qualquer uma das duas bases).

    `liquidada` nula vira 0 só nesta conta — não em geral (`agregar_por_ne`/`agregar`
    preservam nulo ≠ zero) — porque saldo de empenho é por definição um saldo corrente: uma NE
    ainda não liquidada tem, por definição, R$ 0,00 liquidados até agora, não um valor
    desconhecido. Mesma regra usada em `app_pages/consulta_empenhos.py::_saldo_e_a_pagar`.
    """
    resultado = por_ne.copy()
    resultado["saldo"] = resultado["empenhada"] - resultado["liquidada"].fillna(0.0)
    return resultado


def _indice_por_ne_curta(por_ne: pd.DataFrame, coluna: str) -> pd.Series:
    indice = [ne_curta(ne_ccor) for ne_ccor in por_ne["ne_ccor"]]
    return pd.Series(por_ne[coluna].to_numpy(), index=indice)


def indice_saldo_por_ne_curta(por_ne_com_saldo: pd.DataFrame) -> pd.Series:
    """Série `saldo`, indexada pela forma curta da NE — pronta para `.map()` a partir de
    qualquer base externa que cite a NE sem o prefixo de órgão/UG (ver `ne_curta`).

    Recebe o resultado de `saldo_por_ne`, não `agregar_por_ne` puro — é preciso já ter a
    coluna `saldo`.
    """
    return _indice_por_ne_curta(por_ne_com_saldo, "saldo")


def indice_valor_empenhado_por_ne_curta(por_ne: pd.DataFrame) -> pd.Series:
    """Série `empenhada` (valor empenhado autoritativo por NE), indexada pela forma curta da
    NE — mesmo padrão de `indice_saldo_por_ne_curta`, para bases externas que precisem
    validar/atualizar o valor empenhado que colam manualmente contra a Execução.

    Recebe o resultado de `agregar_por_ne` (a coluna `empenhada` já existe ali; não precisa
    ter passado por `saldo_por_ne`, mas aceita o resultado dela também, já que só lê
    `empenhada`).
    """
    return _indice_por_ne_curta(por_ne, "empenhada")


def indice_liquidado_por_ne_curta(por_ne: pd.DataFrame) -> pd.Series:
    """Série `liquidada` (valor liquidado autoritativo, por NE), indexada pela forma curta da
    NE — mesmo padrão de `indice_valor_empenhado_por_ne_curta`, para bases externas
    compararem empenhado × liquidado por NE (ex. quadro "Empenhado × Liquidado" em
    `app_pages/contratos_continuos.py`).

    Recebe o resultado de `agregar_por_ne` (a coluna `liquidada` já existe ali).
    """
    return _indice_por_ne_curta(por_ne, "liquidada")


def indice_valor_pago_por_ne_curta(por_ne: pd.DataFrame) -> pd.Series:
    """Série `paga` (valor efetivamente pago, autoritativo, por NE), indexada pela forma
    curta da NE — mesmo padrão de `indice_valor_empenhado_por_ne_curta`, para bases externas
    (ex. `app_pages/contratos_pagamentos.py`) reconciliarem o total que registram para uma NE
    contra o valor oficial pago segundo a Execução.

    Recebe o resultado de `agregar_por_ne` (a coluna `paga` já existe ali).
    """
    return _indice_por_ne_curta(por_ne, "paga")


def detalhar_nota_empenho(df: pd.DataFrame, ne_ccor: str) -> pd.DataFrame:
    """Todas as linhas de uma NE (empenho + itens de execução), para rastreabilidade —
    ordenadas por `linha_origem` (ordem original da planilha de origem)."""
    return df.loc[df["ne_ccor"] == ne_ccor].sort_values("linha_origem")
