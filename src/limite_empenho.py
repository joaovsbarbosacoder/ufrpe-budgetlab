"""Limite de Empenho — controle da cota orçamentária liberada por período (Discricionário).

Reproduz a lógica da planilha de referência que a PROPLAD extrai periodicamente ("COTA <ano>
- Discricionário - Saldo disponível a empenhar") — decisão do usuário (22/09/2026): calcular
ao vivo a partir das bases já importadas (Dotação Anual + Execução Mensal), em vez de
reimportar aquele arquivo a cada liberação de cota.

Fórmula confirmada contra a planilha de referência (bate em todas as linhas, sem exceção,
inclusive nas linhas "Total" por Iduso):
    Limite liberado = Dotação Atualizada × fração do período (ex.: 9/12, liberada pela PROPLAD)
    Saldo disponível a empenhar = Limite liberado − Despesas Empenhadas

A fração NÃO é derivada do calendário (não é necessariamente "mês atual / 12") — é um número
que a PROPLAD libera e informa por fora; por isso é sempre um parâmetro explícito desta
função, nunca calculado aqui a partir de uma data.

ESCOPO "DISCRICIONÁRIO" (decisão do usuário, 22/09/2026 — escolha de negócio explícita, não
uma regra derivável sozinha dos dados; mudar isso exige nova confirmação):
  - Exclui despesas de pessoal: Grupo de Despesa (GND) = 1.
  - Exclui emendas parlamentares: Resultado Primário = 6 (mesmo código de
    `src.alertas_gerenciais.RP_EMENDA_COM_DOTACAO`).
  - Só Fonte de Recursos "000" (RECURSOS LIVRES DA UNIÃO). A Dotação Anual só tem a Fonte
    DETALHADA (10 dígitos, ex. "1000000000"), não a curta usada na Execução — o usuário
    confirmou que o 1º dígito da fonte detalhada indica o exercício (corrente/anterior) e os
    3 dígitos seguintes SÃO o próprio código curto de fonte usado na Execução. Por isso o
    filtro em Dotação é `fonte_recursos_detalhada_codigo[1:4] == "000"`, equivalente (mesma
    granularidade, não uma aproximação) a `fonte_cod == "000"` na Execução.

GRANULARIDADE: mesma da planilha de referência — uma linha por (Iduso, Resultado Primário,
Ação de Governo, PTRES, Plano Orçamentário, Grupo Despesa). Empenhado vem de
`src.tesouro_execucao_mensal.valor_empenhado_por_bloco` (já deduplicado — nunca a soma direta
das linhas brutas, ver docstring daquele módulo).

UNIVERSO DE AÇÃO/PTRES (decisão do usuário, 22/09/2026): o cruzamento Dotação×Empenhado é
`left`, ANCORADO em Dotação — de propósito, para o conjunto de Ação/PTRES desta tabela ser o
MESMO que aparece em "Painel por Ação" (`app_pages/painel_acoes.py`, também só Dotação Anual).
Uma combinação com Empenhado mas sem nenhuma linha de Dotação correspondente (lacuna de
carregamento já documentada em `src.alertas_gerenciais.acoes_com_deficit`) não aparece aqui —
ela também não apareceria em Painel por Ação, então não há "limite" nenhum a controlar para
ela nesta ferramenta. Dotação sem nenhum Empenhado ainda no ano aparece normalmente, com
Empenhado = 0 (zero de verdade: "ainda não empenhou", não "não sei quanto foi empenhado").

EXERCÍCIO: sempre o corrente (ano da data de extração do manifesto de Dotação Anual — mesma
convenção de `ano_extracao` em `app_pages/painel_acoes.py`/`src/alertas_gerenciais.py`), nunca
um exercício passado — pedido explícito do usuário: cota liberada só faz sentido para o
exercício em andamento.
"""

from __future__ import annotations

from fractions import Fraction

import pandas as pd

from src.dotacao_anual_analysis import KNOWN_ITEM_INDICATORS, build_dotacao_anual_subdivision_analysis
from src.tesouro_execucao_mensal import valor_empenhado_por_bloco

#: código do Grupo de Despesa "Pessoal e Encargos Sociais" — excluído do escopo discricionário.
GND_PESSOAL = "1"

#: mesmo código de `src.alertas_gerenciais.RP_EMENDA_COM_DOTACAO` — não importado de lá de
#: propósito (aquele módulo é específico de Alertas Gerenciais; duplicar uma constante de 1
#: caractere é mais simples que criar uma dependência cruzada entre duas regras de negócio
#: independentes que só coincidem em usar o mesmo código).
RESULTADO_PRIMARIO_EMENDA = "6"

#: Fonte de Recursos "RECURSOS LIVRES DA UNIÃO" — código curto (Execução) e os 3 dígitos
#: centrais equivalentes dentro da Fonte Detalhada (Dotação), ver docstring do módulo.
FONTE_LIVRE_UNIAO = "000"

#: colunas de dimensão do resultado — mesma ordem/granularidade da planilha de referência.
COLUNAS_DIMENSAO = [
    "iduso_cod", "iduso_desc",
    "resultado_primario_cod", "resultado_primario_desc",
    "acao_cod", "acao_desc",
    "ptres",
    "po_cod", "po_desc",
    "gnd_cod", "gnd_desc",
]

_COLUNAS_GRUPO_DOTACAO = [
    "iduso_codigo", "iduso_descricao",
    "resultado_primario_codigo", "resultado_primario_descricao",
    "acao_codigo", "acao_descricao",
    "ptres_codigo",
    "plano_orcamentario_codigo", "plano_orcamentario_descricao",
    "grupo_despesa_codigo", "grupo_despesa_descricao",
]

_COLUNAS_GRUPO_EXECUCAO = [
    "iduso_cod", "iduso_desc",
    "resultado_primario_cod", "resultado_primario_desc",
    "acao_cod", "acao_desc",
    "ptres",
    "po_cod", "po_desc",
    "gnd_cod", "gnd_desc",
]


def _dotacao_atualizada_no_escopo(dotacao: pd.DataFrame, ano: int) -> pd.DataFrame:
    """Dotação Atualizada agregada na granularidade do módulo, já restrita ao escopo
    discricionário — reaproveita `build_dotacao_anual_subdivision_analysis`
    (`src/dotacao_anual_analysis.py`, a mesma função de `app_pages/painel_acoes.py`), não uma
    agregação própria: essa função soma TODOS os 4 indicadores conhecidos por subdivisão
    (não só `dotacao_atualizada`), o que é necessário para replicar o mesmo filtro de
    "subdivisão vazia" que o Painel por Ação já aplica (ver `has_any_indicator` abaixo) — bug
    real encontrado pelo usuário (22/09/2026): filtrar direto por
    `item_informacao_codigo == "dotacao_atualizada"` ANTES de agregar descartava os outros 3
    indicadores, então uma combinação de dimensões que só existe na base porque teve dado em
    OUTRO ano (não no `ano` pedido) continuava aparecendo aqui com Dotação Atualizada nula —
    o Painel por Ação nunca mostra essa combinação (`app_pages/painel_acoes.py`, comentário
    "não descarta dado, só a apresentação omite linhas vazias"), e esta ferramenta precisa do
    mesmo universo dele."""

    fonte_curta = dotacao["fonte_recursos_detalhada_codigo"].astype("string").str.slice(1, 4)
    no_escopo = dotacao.loc[
        (dotacao["ano_lancamento"] == ano)
        & (dotacao["grupo_despesa_codigo"] != GND_PESSOAL)
        & (dotacao["resultado_primario_codigo"] != RESULTADO_PRIMARIO_EMENDA)
        & (fonte_curta == FONTE_LIVRE_UNIAO)
    ]

    subdivisoes = build_dotacao_anual_subdivision_analysis(no_escopo)
    tem_algum_indicador = subdivisoes[list(KNOWN_ITEM_INDICATORS)].notna().any(axis=1)
    subdivisoes = subdivisoes.loc[tem_algum_indicador]

    agregado = subdivisoes[_COLUNAS_GRUPO_DOTACAO + ["dotacao_atualizada"]].copy()
    return agregado


def _empenhado_no_escopo(execucao_mensal: pd.DataFrame, ano: int) -> pd.DataFrame:
    """Despesas Empenhadas (já deduplicadas por bloco) agregadas na granularidade do módulo,
    já restrita ao escopo discricionário. `execucao_mensal` é o DataFrame bruto devolvido por
    `src.importacao_execucao_mensal.carregar_atual`."""

    dedup = valor_empenhado_por_bloco(execucao_mensal.loc[execucao_mensal["ano"] == ano])
    no_escopo = dedup.loc[
        (dedup["gnd_cod"] != GND_PESSOAL)
        & (dedup["resultado_primario_cod"] != RESULTADO_PRIMARIO_EMENDA)
        & (dedup["fonte_cod"] == FONTE_LIVRE_UNIAO)
    ]

    agregado = (
        no_escopo.groupby(_COLUNAS_GRUPO_EXECUCAO, dropna=False)["empenhada"]
        .sum(min_count=1)
        .reset_index()
        .rename(columns={"empenhada": "empenhada"})
    )
    return agregado


def saldo_disponivel_a_empenhar(
    dotacao: pd.DataFrame,
    execucao_mensal: pd.DataFrame,
    ano: int,
    fracao: Fraction,
) -> pd.DataFrame:
    """Uma linha por (Iduso, Resultado Primário, Ação, PTRES, Plano Orçamentário, Grupo de
    Despesa), com Dotação Atualizada, Despesas Empenhadas, Limite liberado (Dotação × fração)
    e Saldo disponível a empenhar (Limite − Empenhado) — mesmo layout da planilha de
    referência da PROPLAD ("COTA <ano> - Discricionário - Saldo disponível a empenhar").

    `fracao` é sempre informada por quem chama (ex. `Fraction(9, 12)`) — não há como derivá-la
    do calendário, é a liberação que a PROPLAD comunica por fora do sistema.
    """

    dot = _dotacao_atualizada_no_escopo(dotacao, ano)
    emp = _empenhado_no_escopo(execucao_mensal, ano)

    # Ancorado em Dotação de propósito (pedido explícito do usuário, 22/09/2026): o universo
    # de Ação/PTRES desta tabela precisa ser o MESMO que aparece em "Painel por Ação" (também
    # Dotação Anual, sem cruzar com Execução) — uma combinação que só existe na Execução
    # (Empenhado sem nenhuma linha de Dotação correspondente) não apareceria lá, então não
    # faz sentido aparecer aqui como se tivesse um "limite" a controlar. Essa lacuna de
    # carregamento de dado já é sinalizada em Alertas Gerenciais; não é o objetivo desta
    # ferramenta reportá-la de novo.
    resultado = dot.merge(
        emp,
        left_on=["acao_codigo", "ptres_codigo", "plano_orcamentario_codigo", "grupo_despesa_codigo"],
        right_on=["acao_cod", "ptres", "po_cod", "gnd_cod"],
        how="left",
    )

    resultado["empenhada"] = resultado["empenhada"].astype("Float64").fillna(0.0)
    resultado["dotacao_atualizada"] = resultado["dotacao_atualizada"].astype("Float64")
    resultado["limite_liberado"] = resultado["dotacao_atualizada"] * float(fracao)
    resultado["saldo_disponivel"] = resultado["limite_liberado"] - resultado["empenhada"]

    colunas_finais = _COLUNAS_GRUPO_DOTACAO + [
        "dotacao_atualizada", "empenhada", "limite_liberado", "saldo_disponivel",
    ]
    return (
        resultado[colunas_finais]
        .rename(columns=dict(zip(_COLUNAS_GRUPO_DOTACAO, COLUNAS_DIMENSAO, strict=True)))
        .sort_values(COLUNAS_DIMENSAO, na_position="last", kind="stable")
        .reset_index(drop=True)
    )
