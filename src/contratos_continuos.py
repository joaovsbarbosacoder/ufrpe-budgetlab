"""
Leitura e normalização da planilha de Contratos Contínuos (PROAD).

Camada: regra específica de base (não é leitor genérico, não é analítica, não é interface).
Depende só de pandas/openpyxl. Não importa Streamlit.

Origem: planilha de trabalho mantida manualmente (`SERVIÇOS CONTÍNUOS - 2026 - AGO A DEZ.xlsm`),
não um export único e estável como o BI CPOC da Execução Anual — por isso o casamento de
colunas é por NOME normalizado (sem acento, maiúsculo), não por posição: numa planilha editada
à mão a ordem das colunas muda com mais facilidade do que o texto do cabeçalho.

Aba lida: "Planilha atualizada". Granularidade: uma linha por contrato × item de
licitação/despesa dentro do empenho vigente — não uma linha por contrato, não por mês.

As colunas `MESES A EMPENHAR`/`EMPENHAR (R$)` da origem ficam de fora do esquema: estão
sempre vazias nesta planilha (conferido em 4 extrações diferentes) — a coluna real com a
mesma lógica de negócio é `MESES DE SALDO`, recalculada aqui como `meses_a_empenhar`/
`valor_a_empenhar` via `src/necessidade_empenho.py`, em vez de lida da origem.

`SALDO TOTAL TG` (o saldo colado manualmente na aba BASE_TG desta planilha, no nível da NE)
vira `saldo_colado_planilha` — não `SALDO TG ATUALIZADO`, que é o mesmo saldo rateado por
item de licitação quando o contrato tem mais de um (`% ITEM LIC.`); comparar essa fração
contra `saldo_execucao` (sempre no nível da NE inteira) geraria falsa divergência em todo
contrato com vários itens. Ver `com_saldo_execucao` para o saldo autoritativo, derivado da
Execução Anual já validada do projeto.

Contrato público:
    ler_contratos_continuos(caminho) -> pd.DataFrame
    com_saldo_execucao(df, por_ne_execucao) -> pd.DataFrame
    com_meses_pagos(df, meses_pagos) -> pd.DataFrame
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

from src.contratos_pagamentos import normalizar_numero_contrato
from src.execucao_anual import indice_saldo_por_ne_curta, indice_valor_empenhado_por_ne_curta
from src.necessidade_empenho import calcular_necessidade_empenho

NOME_ABA = "Planilha atualizada"

#: sentinelas de "sem empenho" usadas nesta planilha na coluna EMPENHO.
_SENTINELAS_SEM_EMPENHO = {"", "-", "0"}


class ErroLayoutBase(ValueError):
    """Cabeçalho da planilha sem as colunas esperadas — falhar cedo, nunca adivinhar."""


def _normalizar(texto: object) -> str:
    if texto is None:
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sem_acento).strip().upper()


#: cabeçalho normalizado (sem acento, maiúsculo) da origem -> nome interno da coluna. Colunas
#: da origem que não aparecem aqui são descartadas na leitura: HOJE (data da fórmula, não
#: dado), NECESSIDADE DE EMPENHO/MÊS ATUAL (métrica prospectiva de calendário, fora de escopo
#: por ora), OBSERVAÇÃO (sempre vazia nesta extração), ANULAR (R$)/SALDO ANTERIOR (quase todo
#: nulo), STATUS ATUALIZAÇÃO (housekeeping da automação da planilha, não do dado),
#: MESES A EMPENHAR/EMPENHAR (R$) (ver docstring do módulo), e SALDO TG ATUALIZADO (saldo por
#: item rateado — ver nota sobre `SALDO TOTAL TG` acima).
COLUNAS_ORIGEM = {
    "ANO CONTRATO": "ano_contrato",
    "NO CONTRATO": "contrato_numero",
    "NO PROCESSO CONTRATACAO": "processo_contratacao",
    "NO PROCESSO EMPENHO": "processo_empenho",
    "FORNECEDOR": "fornecedor",
    "TIPO": "tipo_contrato",
    "TIPO DE DESPESA": "tipo_despesa",
    "CNPJ/CPF FORNEC": "fornecedor_cnpj_cpf",
    "DT VIGENCIA CONTRATO": "vigencia_fim",
    "STATUS": "status_contrato",
    "UNIDADE": "unidade_cod",
    "ACAO": "acao_cod",
    "PTRES": "ptres",
    "FONTE": "fonte_cod",
    "ND": "natureza_despesa_cod",
    "UGR": "ugr_cod",
    "PI": "pi_cod",
    "VARIOS ITENS LIC.": "tem_varios_itens",
    "EMPENHO": "ne_curta",
    "MESES DE SALDO": "meses_de_saldo",
    "MESES EMPENHADOS": "meses_empenhados",
    "MESES LIQUIDADOS": "meses_liquidados",
    "ITEM LIC.": "item_licitacao",
    "%": "item_percentual",
    "DESPESA MENSAL": "despesa_mensal",
    "DESPESA ANUAL": "despesa_anual",
    "VALOR EMPENHADO": "valor_empenhado",
    "SALDO TOTAL TG": "saldo_colado_planilha",
}

_COLUNAS_TEXTO = {
    "contrato_numero", "processo_contratacao", "processo_empenho", "fornecedor",
    "tipo_contrato", "tipo_despesa", "fornecedor_cnpj_cpf", "status_contrato",
    "unidade_cod", "acao_cod", "ptres", "fonte_cod", "natureza_despesa_cod",
    "ugr_cod", "pi_cod", "ne_curta",
}
_COLUNAS_NUMERICAS = {
    "ano_contrato", "meses_de_saldo", "meses_empenhados", "meses_liquidados",
    "item_licitacao", "item_percentual", "despesa_mensal", "despesa_anual",
    "valor_empenhado", "saldo_colado_planilha",
}


def ler_contratos_continuos(caminho: str | Path) -> pd.DataFrame:
    """Lê a aba "Planilha atualizada" e devolve o DataFrame normalizado, com as colunas
    derivadas `meses_a_empenhar`/`valor_a_empenhar` (ver docstring do módulo). Não liga com a
    Execução Anual — para isso, `com_saldo_execucao`."""

    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(caminho)

    bruto = pd.read_excel(caminho, sheet_name=NOME_ABA, header=0, dtype=object)

    normalizados = {coluna: _normalizar(coluna) for coluna in bruto.columns}
    faltando = set(COLUNAS_ORIGEM) - set(normalizados.values())
    if faltando:
        raise ErroLayoutBase(
            f"Colunas ausentes na aba {NOME_ABA!r} de {caminho.name}: {sorted(faltando)}. "
            "O layout da planilha mudou."
        )

    mapa = {origem: COLUNAS_ORIGEM[norm] for origem, norm in normalizados.items() if norm in COLUNAS_ORIGEM}
    df = bruto.rename(columns=mapa)[list(mapa.values())].copy()

    # linhas em branco no fim da planilha de trabalho e a linha de total (soma de todas as
    # colunas monetárias, sem FORNECEDOR nem nenhuma outra coluna identificadora — só
    # "STATUS ATUALIZAÇÃO" preenchido com um resumo textual como "52 atualizados") não são
    # linha de dado; um `dropna(how="all")` não pega a linha de total (ela tem várias colunas
    # com valor, só não as identificadoras), mesmo bug já resolvido para Bolsas e Auxílios via
    # `processo` (ver `ler_bolsas_auxilios`). FORNECEDOR nunca é nulo em nenhuma linha real
    # desta planilha (conferido na extração de 13/08/2026).
    df = df.dropna(subset=["fornecedor"]).reset_index(drop=True)

    for coluna in _COLUNAS_TEXTO:
        df[coluna] = df[coluna].astype("string").str.strip()

    for coluna in _COLUNAS_NUMERICAS:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")

    df["vigencia_fim"] = pd.to_datetime(df["vigencia_fim"], errors="coerce")
    df["tem_varios_itens"] = df["tem_varios_itens"].str.upper().eq("SIM")
    df.loc[df["ne_curta"].isin(_SENTINELAS_SEM_EMPENHO), "ne_curta"] = pd.NA

    df["meses_a_empenhar"], df["valor_a_empenhar"] = calcular_necessidade_empenho(
        df["meses_empenhados"], df["meses_liquidados"], df["despesa_mensal"]
    )

    return df


def _diverge(execucao: pd.Series, planilha: pd.Series, tolerancia: float = 0.01) -> pd.Series:
    tem_os_dois = execucao.notna() & planilha.notna()
    diferenca = (execucao - planilha).abs()
    resultado = pd.Series(pd.NA, index=execucao.index, dtype="boolean")
    resultado.loc[tem_os_dois] = diferenca[tem_os_dois] > tolerancia
    return resultado


def com_saldo_execucao(df: pd.DataFrame, por_ne_execucao: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta, via `ne_curta`, dois pares de campos buscados na Execução Anual já
    validada do projeto: `saldo_execucao`/`diverge_saldo` (contra `saldo_colado_planilha`,
    sempre no nível da NE nos dois lados) e `valor_empenhado_execucao`/
    `diverge_valor_empenhado` (contra a soma de `valor_empenhado` por NE, não o valor da
    linha) — ambos com divergência True quando a diferença passa de R$ 0,01.
    `por_ne_execucao` é o resultado de `execucao_anual.saldo_por_ne(agregar_por_ne(...))`.

    `valor_empenhado` da planilha é rateado por item de licitação quando o contrato tem mais
    de um (mesmo problema de `SALDO TG ATUALIZADO` vs. `SALDO TOTAL TG`, ver docstring do
    módulo): comparar a Execução (sempre no nível da NE) contra o valor de um item isolado
    geraria falsa divergência em todo contrato com vários itens — soma-se por NE antes de
    comparar. `valor_empenhado_planilha_total_ne` (novo campo) é essa soma, repetida em todas
    as linhas da mesma NE; `valor_empenhado` da linha continua sendo o valor do item,
    inalterado.

    NE sem correspondência na Execução (ou linha sem `ne_curta`, contrato ainda sem empenho)
    fica com os campos de comparação nulos — não é erro, é ausência de dado para comparar.
    """
    resultado = df.copy()

    indice_saldo = indice_saldo_por_ne_curta(por_ne_execucao)
    resultado["saldo_execucao"] = resultado["ne_curta"].map(indice_saldo)
    resultado["diverge_saldo"] = _diverge(resultado["saldo_execucao"], resultado["saldo_colado_planilha"])

    indice_valor_empenhado = indice_valor_empenhado_por_ne_curta(por_ne_execucao)
    resultado["valor_empenhado_execucao"] = resultado["ne_curta"].map(indice_valor_empenhado)

    soma_planilha_por_ne = resultado.dropna(subset=["ne_curta"]).groupby("ne_curta")["valor_empenhado"].sum()
    resultado["valor_empenhado_planilha_total_ne"] = resultado["ne_curta"].map(soma_planilha_por_ne)
    resultado["diverge_valor_empenhado"] = _diverge(
        resultado["valor_empenhado_execucao"], resultado["valor_empenhado_planilha_total_ne"]
    )

    return resultado


def com_meses_pagos(df: pd.DataFrame, meses_pagos: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta `meses_pagos`/`ultimo_mes_pago`, buscados na planilha de Pagamentos de
    Contratos (`src.contratos_pagamentos.meses_pagos_por_contrato`) via `contrato_numero`
    normalizado (`normalizar_numero_contrato`, aplicada aqui também para casar com o mesmo
    formato canônico) — indicador INDEPENDENTE de quantos meses tiveram pagamento
    efetivamente registrado e qual foi o mais recente, não uma correção de `meses_liquidados`
    (campo manual desta planilha): liquidação e pagamento são estágios orçamentários
    diferentes, este campo não substitui aquele.

    Contrato sem número reconhecível (`contrato_numero` vazio/fora do padrão "<número ou
    SN>/<ano>") ou sem correspondência na planilha de Pagamentos fica com os dois campos
    nulos — não é erro, é ausência de dado para comparar (mesmo critério de
    `com_saldo_execucao`).
    """
    resultado = df.copy()
    resultado["contrato_normalizado"] = resultado["contrato_numero"].apply(normalizar_numero_contrato)
    indexado = meses_pagos.set_index("contrato_normalizado")
    resultado["meses_pagos"] = resultado["contrato_normalizado"].map(indexado["meses_pagos"])
    resultado["ultimo_mes_pago"] = resultado["contrato_normalizado"].map(indexado["ultimo_mes_pago"])
    return resultado
