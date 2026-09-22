"""
Leitura e normalização da planilha de Bolsas e Auxílios (PROAD).

Camada: regra específica de base (não é leitor genérico, não é analítica, não é interface).
Depende só de pandas/openpyxl. Não importa Streamlit.

Origem: planilha de trabalho mantida manualmente (`BOLSAS E AUXÍLIOS 2026 - AGO A DEZ.xlsx`),
não um export único e estável — casamento de colunas por NOME normalizado (sem acento,
maiúsculo), mesmo motivo de `src/contratos_continuos.py`.

Aba lida: "Bolsas e auxílios" (cabeçalho na 4ª linha da planilha — 3 linhas de título acima).
Granularidade: uma linha por processo × item de despesa (programa de bolsa/auxílio) ligado a
um empenho — NÃO uma linha por bolsista individual: esta planilha não tem nome/CPF de
beneficiário, só a quantidade agregada (`qtd_efetiva`) por programa.

A última linha da aba original é um total ("TOTAIS"), sem `processo` — é descartada aqui
(não é uma linha de dado) e não replicada como validação nesta função pura.

`MESES A EMPENHAR`/`EMPENHAR (R$)` da origem ficam de fora do esquema: ao contrário de
Contratos Contínuos (sempre vazias), aqui têm valor, mas são um flag manual 0/1 sem relação
numérica com `meses_empenhados`/`meses_liquidados` — não a mesma lógica de negócio. A conta
real (mesma de `MESES DE SALDO`, validada célula a célula contra a origem) é recalculada aqui
como `meses_a_empenhar`/`valor_a_empenhar` via `src/necessidade_empenho.py`.

`SALDO NO EMPENHO (TG)` (colado manualmente na aba Base TG desta planilha) vira
`saldo_colado_planilha` — ver `com_saldo_execucao` para o saldo autoritativo, derivado da
Execução Mensal já validada do projeto.

Contrato público:
    ler_bolsas_auxilios(caminho) -> pd.DataFrame
    com_saldo_execucao(df, por_ne_execucao) -> pd.DataFrame
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

from src.execucao_ne_utils import (
    indice_liquidado_por_ne_curta,
    indice_saldo_por_ne_curta,
    indice_valor_empenhado_por_ne_curta,
)
from src.necessidade_empenho import calcular_necessidade_empenho

NOME_ABA = "Bolsas e auxílios"
LINHA_CABECALHO = 3  # 0-indexada: cabeçalho é a 4ª linha da planilha

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
#: da origem que não aparecem aqui são descartadas: ANULAR (R$) (quase todo nulo), e
#: MESES A EMPENHAR/EMPENHAR (R$) (ver docstring do módulo).
COLUNAS_ORIGEM = {
    "PROCESSO": "processo",
    "ITEM DE DESPESA": "programa_bolsa",
    "UNIDADE": "unidade_cod",
    "ACAO": "acao_cod",
    "PTRES": "ptres",
    "FONTE": "fonte_cod",
    "ND": "natureza_despesa_cod",
    "UGR": "ugr_cod",
    "PI": "pi_cod",
    "EMPENHO": "ne_curta",
    "S/N": "tem_saldo",
    "MESES DE SALDO": "meses_de_saldo",
    "MESES EMPENHADOS": "meses_empenhados",
    "MESES LIQUIDADOS": "meses_liquidados",
    "MESES NO ANO": "meses_no_ano",
    "QUANT. INICIAL": "qtd_inicial",
    "QUANT. EFETIVA DE BOLSAS": "qtd_efetiva",
    "VALOR UNITARIO": "valor_unitario",
    "VALOR MENSAL": "valor_mensal",
    "VALOR ANUAL": "valor_anual",
    "VALOR EMPENHADO (TG)": "valor_empenhado_tg",
    "SALDO NO EMPENHO (TG)": "saldo_colado_planilha",
    "SITUACAO TG": "situacao_tg",
    "OCORRENCIAS TG": "ocorrencias_tg",
}

_COLUNAS_TEXTO = {
    "processo", "programa_bolsa", "unidade_cod", "acao_cod", "ptres", "fonte_cod",
    "natureza_despesa_cod", "ugr_cod", "pi_cod", "ne_curta", "situacao_tg",
}
_COLUNAS_NUMERICAS = {
    "meses_de_saldo", "meses_empenhados", "meses_liquidados", "meses_no_ano",
    "qtd_inicial", "qtd_efetiva", "valor_unitario", "valor_mensal", "valor_anual",
    "valor_empenhado_tg", "saldo_colado_planilha", "ocorrencias_tg",
}


def ler_bolsas_auxilios(caminho: str | Path) -> pd.DataFrame:
    """Lê a aba "Bolsas e auxílios" e devolve o DataFrame normalizado, com as colunas
    derivadas `meses_a_empenhar`/`valor_a_empenhar` (ver docstring do módulo). Não liga com a
    Execução Mensal — para isso, `com_saldo_execucao`."""

    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(caminho)

    bruto = pd.read_excel(caminho, sheet_name=NOME_ABA, header=LINHA_CABECALHO, dtype=object)

    normalizados = {coluna: _normalizar(coluna) for coluna in bruto.columns}
    faltando = set(COLUNAS_ORIGEM) - set(normalizados.values())
    if faltando:
        raise ErroLayoutBase(
            f"Colunas ausentes na aba {NOME_ABA!r} de {caminho.name}: {sorted(faltando)}. "
            "O layout da planilha mudou."
        )

    mapa = {origem: COLUNAS_ORIGEM[norm] for origem, norm in normalizados.items() if norm in COLUNAS_ORIGEM}
    df = bruto.rename(columns=mapa)[list(mapa.values())].copy()

    # linha "TOTAIS" e linhas em branco: nenhuma delas tem PROCESSO preenchido.
    df = df.dropna(subset=["processo"]).reset_index(drop=True)

    for coluna in _COLUNAS_TEXTO:
        df[coluna] = df[coluna].astype("string").str.strip()

    for coluna in _COLUNAS_NUMERICAS:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")

    df["tem_saldo"] = df["tem_saldo"].str.upper().eq("S")
    df.loc[df["ne_curta"].isin(_SENTINELAS_SEM_EMPENHO), "ne_curta"] = pd.NA

    df["meses_a_empenhar"], df["valor_a_empenhar"] = calcular_necessidade_empenho(
        df["meses_empenhados"], df["meses_liquidados"], df["valor_mensal"]
    )

    return df


def _diverge(execucao: pd.Series, planilha: pd.Series, tolerancia: float = 0.01) -> pd.Series:
    tem_os_dois = execucao.notna() & planilha.notna()
    diferenca = (execucao - planilha).abs()
    resultado = pd.Series(pd.NA, index=execucao.index, dtype="boolean")
    resultado.loc[tem_os_dois] = diferenca[tem_os_dois] > tolerancia
    return resultado


def com_saldo_execucao(df: pd.DataFrame, por_ne_execucao: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta, via `ne_curta`, dois pares de campos buscados na Execução Mensal já
    validada do projeto: `saldo_execucao`/`diverge_saldo` (contra `saldo_colado_planilha`) e
    `valor_empenhado_execucao`/`diverge_valor_empenhado` (contra `valor_empenhado_tg`) —
    ambos com divergência True quando a diferença passa de R$ 0,01. `por_ne_execucao` é o
    resultado de `execucao_ne_utils.saldo_por_ne(tesouro_execucao_mensal.agregar_por_ne(...))`.

    NE sem correspondência na Execução (ou linha sem `ne_curta`, processo ainda sem empenho)
    fica com os quatro campos nulos — não é erro, é ausência de dado para comparar. Uma linha
    por NE nesta base (ver docstring do módulo), então a comparação é direta, sem precisar
    somar por NE como em `contratos_continuos.com_saldo_execucao`.

    Também recalcula `meses_a_empenhar`/`valor_a_empenhar` (a "Necessidade de Empenho") a
    partir da Execução Mensal em vez das colunas manuais `meses_empenhados`/`meses_liquidados`
    da planilha, para todo processo cuja NE já foi encontrada acima: `valor_liquidado_execucao`
    (novo campo, via `indice_liquidado_por_ne_curta`) e `valor_empenhado_execucao` ÷
    `valor_mensal` viram `meses_liquidados_execucao`/`meses_empenhados_execucao` — fração
    exata, sem arredondar (decisão confirmada com o usuário; mesmo critério de
    `contratos_continuos.com_saldo_execucao`). Assim a Necessidade de Empenho atualiza sozinha
    a cada reimportação de Execução Mensal, sem precisar tocar na planilha de Bolsas. Processo
    sem NE, ou com NE ainda não encontrada na Execução carregada, mantém
    `meses_empenhados`/`meses_liquidados` da planilha (fallback inalterado) — `necessidade_via`
    (novo campo) marca "execucao" ou "planilha" conforme a fonte usada em cada linha, para a
    interface deixar isso visível.
    """
    resultado = df.copy()

    indice_saldo = indice_saldo_por_ne_curta(por_ne_execucao)
    resultado["saldo_execucao"] = resultado["ne_curta"].map(indice_saldo)
    resultado["diverge_saldo"] = _diverge(resultado["saldo_execucao"], resultado["saldo_colado_planilha"])

    indice_valor_empenhado = indice_valor_empenhado_por_ne_curta(por_ne_execucao)
    resultado["valor_empenhado_execucao"] = resultado["ne_curta"].map(indice_valor_empenhado)
    resultado["diverge_valor_empenhado"] = _diverge(resultado["valor_empenhado_execucao"], resultado["valor_empenhado_tg"])

    indice_liquidado = indice_liquidado_por_ne_curta(por_ne_execucao)
    resultado["valor_liquidado_execucao"] = resultado["ne_curta"].map(indice_liquidado)

    tem_base_para_calculo = (
        resultado["valor_empenhado_execucao"].notna()
        & resultado["valor_liquidado_execucao"].notna()
        & resultado["valor_mensal"].notna()
        & (resultado["valor_mensal"] != 0)
    )

    meses_empenhados_execucao = resultado["valor_empenhado_execucao"] / resultado["valor_mensal"]
    meses_liquidados_execucao = resultado["valor_liquidado_execucao"] / resultado["valor_mensal"]
    resultado["meses_empenhados_execucao"] = meses_empenhados_execucao.where(tem_base_para_calculo)
    resultado["meses_liquidados_execucao"] = meses_liquidados_execucao.where(tem_base_para_calculo)

    meses_a_empenhar_execucao, valor_a_empenhar_execucao = calcular_necessidade_empenho(
        meses_empenhados_execucao, meses_liquidados_execucao, resultado["valor_mensal"]
    )
    resultado["meses_a_empenhar"] = resultado["meses_a_empenhar"].where(~tem_base_para_calculo, meses_a_empenhar_execucao)
    resultado["valor_a_empenhar"] = resultado["valor_a_empenhar"].where(~tem_base_para_calculo, valor_a_empenhar_execucao)
    resultado["necessidade_via"] = pd.Series("planilha", index=resultado.index).where(~tem_base_para_calculo, "execucao")

    return resultado
