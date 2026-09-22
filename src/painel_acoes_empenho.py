"""Cruzamento entre Dotação Anual (por subdivisão, `src.dotacao_anual_analysis`) e
Execução Anual (Empenhada, `src.execucao_anual`) — usado só por "Painel por Ação de
Governo" (`app_pages/painel_acoes.py`) para mostrar o valor atualmente empenhado ao
lado de cada subdivisão de dotação.

Camada: regra de negócio pura — não lê arquivo, não importa Streamlit. Consome os
DataFrames já normalizados por `dotacao_anual_analysis.build_dotacao_anual_subdivision_analysis`
e `src.importacao_execucao.carregar_atual()`.

DECISÃO CONFIRMADA PELO USUÁRIO (22/09/2026) — a Fonte de Recursos não usa o mesmo
código nas duas bases: Dotação Anual traz "Fonte de Recursos Detalhada" (10 dígitos),
Execução Anual traz "Fonte de Recursos" (3 dígitos). Testei empiricamente a hipótese
óbvia (pegar os dígitos [1:4] do código de 10 dígitos) contra a base real ANTES de
perguntar: só bateu em 31% dos casos — não é um padrão confiável sozinho. O usuário
explicou a regra real: o 1º dígito do código de 10 dígitos é um QUALIFICADOR de
exercício (1 = recurso do exercício corrente; 3 = recursos de exercícios anteriores —
"basicamente a mesma fonte", só muda o exercício de origem do recurso); outros valores
do 1º dígito (0, 8, na base real) indicam dotação de uma fonte que ainda não teve
nenhuma despesa empenhada — não é falha de mapeamento, é ausência real de execução
para aquela fonte. Confirmado contra a base real: 100% dos 16 códigos com 1º dígito
1 ou 3 batem exatamente com um `fonte_cod` da Execução Anual (`derivar_fonte_execucao`
usa [1:4] sempre — o dígito é só descartado, nunca precisa ser 1 ou 3 explicitamente
checado: quando não bate, o merge simplesmente não encontra correspondência, o mesmo
efeito de "sem execução ainda").

ACHADO — colisão de Fonte Detalhada: 32 de 245 combinações (Ação/PTRES/PO/GND/RP/IDUSO)
têm MAIS de um código de Fonte Detalhada mapeando para a MESMA Fonte de 3 dígitos (ex.:
"1050000000" e "1050000390" ambos viram "050"). Nesses casos as duas linhas de
subdivisão mostram o MESMO valor empenhado (não dá pra desagregar abaixo da Fonte de 3
dígitos — é o nível real da Execução). Por isso o TOTAL por Ação nunca é a soma da
coluna exibida por subdivisão (somaria esse valor em dobro nas combinações que colidem)
— sempre recalculado direto da Execução Anual, sem passar pelas linhas de subdivisão
(`empenhado_total_por_acao`).
"""

from __future__ import annotations

import pandas as pd

from src.execucao_anual import agregar

#: dimensões usadas no cruzamento por subdivisão — mesmo código nas duas bases (Ação,
#: PTRES, Plano Orçamentário, Grupo de Despesa, Resultado Primário, IDUSO). Chave =
#: coluna em `dotacao_anual_analysis.SUBDIVISION_DIMENSION_COLUMNS`, valor = coluna
#: correspondente em `src.execucao_anual` (ver `src.execucao_anual.COLUNAS`).
DIMENSOES_CRUZAMENTO: dict[str, str] = {
    "acao_codigo": "acao_cod",
    "ptres_codigo": "ptres",
    "plano_orcamentario_codigo": "po_cod",
    "grupo_despesa_codigo": "gnd_cod",
    "resultado_primario_codigo": "resultado_primario_cod",
    "iduso_codigo": "iduso_cod",
}

_COLUNA_FONTE_DOTACAO = "fonte_recursos_detalhada_codigo"
_COLUNA_FONTE_EXECUCAO = "fonte_cod"
_COLUNA_FONTE_DERIVADA = "_fonte_cod_derivada_de_dotacao"


def derivar_fonte_execucao(fonte_recursos_detalhada_codigo: pd.Series) -> pd.Series:
    """Fonte de Recursos (3 dígitos, mesmo código da Execução Anual) a partir da Fonte
    de Recursos Detalhada (10 dígitos) da Dotação Anual — dígitos 2 a 4 (posição
    `[1:4]`), descartando o 1º dígito (qualificador de exercício — ver docstring do
    módulo). Preserva nulo: uma Fonte Detalhada ausente devolve nulo, não a string
    "None"/"nan"."""

    codigos = fonte_recursos_detalhada_codigo.astype("string")
    return codigos.str.slice(1, 4)


def anexar_empenhado_por_subdivisao(
    subdivisoes: pd.DataFrame, execucao_df: pd.DataFrame, ano: int,
) -> pd.DataFrame:
    """Devolve uma CÓPIA de `subdivisoes` com uma coluna nova `empenhada` — soma da
    Empenhada da Execução Anual do exercício `ano`, na mesma combinação de dimensões
    da subdivisão (`DIMENSOES_CRUZAMENTO` + Fonte derivada, ver `derivar_fonte_execucao`).
    Nulo quando a combinação não tem nenhum empenho lançado (dotação sem despesa
    vinculada ainda — nulo, não zero, mesmo princípio do resto do projeto).

    NÃO usar esta coluna para somar um total por Ação — ver `empenhado_total_por_acao`
    (colisões de Fonte Detalhada fariam um mesmo valor de Execução ser somado mais de
    uma vez, ver docstring do módulo)."""

    exec_ano = execucao_df.loc[execucao_df["ano"] == ano]
    colunas_cruzamento_execucao = [*DIMENSOES_CRUZAMENTO.values(), _COLUNA_FONTE_EXECUCAO]
    agregado = agregar(exec_ano, por=colunas_cruzamento_execucao, incluir_ano=False)

    resultado = subdivisoes.copy()
    resultado[_COLUNA_FONTE_DERIVADA] = derivar_fonte_execucao(resultado[_COLUNA_FONTE_DOTACAO])

    colunas_dotacao = [*DIMENSOES_CRUZAMENTO.keys(), _COLUNA_FONTE_DERIVADA]
    colunas_execucao = [*DIMENSOES_CRUZAMENTO.values(), _COLUNA_FONTE_EXECUCAO]
    juntado = resultado.merge(
        agregado[[*colunas_execucao, "empenhada"]],
        how="left", left_on=colunas_dotacao, right_on=colunas_execucao,
        suffixes=("", "_execucao"),
    )
    colunas_extras = [_COLUNA_FONTE_DERIVADA, *[c for c in colunas_execucao if c not in colunas_dotacao]]
    return juntado.drop(columns=colunas_extras)


def empenhado_total_por_acao(execucao_df: pd.DataFrame, ano: int) -> pd.Series:
    """Empenhada total do exercício `ano`, por Ação — cálculo INDEPENDENTE das linhas
    de subdivisão (nunca some a coluna `empenhada` de `anexar_empenhado_por_subdivisao`
    para obter o total: colisões de Fonte Detalhada duplicariam valor, ver docstring do
    módulo). `pd.Series` indexada por `acao_cod`."""

    exec_ano = execucao_df.loc[execucao_df["ano"] == ano]
    agregado = agregar(exec_ano, por=["acao_cod"], incluir_ano=False)
    return agregado.set_index("acao_cod")["empenhada"]
