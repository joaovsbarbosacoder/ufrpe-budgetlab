"""
Leitor da execução por empenho do Tesouro Gerencial, para o módulo de TEDs.

Dúvida sinalizada (AGENTS.md pede para não presumir regra de negócio não definida): o
briefing descreve DUAS bases do Tesouro Gerencial ("execução da despesa por empenho" e
"liquidação por competência") mas um único modelo de tabela (`execucao_tg`) com os campos
das duas misturados. Sem uma extração real em mãos, este leitor assume o cenário mais
permissivo — uma linha por (NE, documento hábil, documento contábil, competência) — e
`ano_competencia`/`mes_competencia`/`valor_competencia` ficam `None` quando a extração não
traz a granularidade de competência (arquivo de execução por empenho "puro"). Isso precisa
ser revisto assim que a extração real for importada.

A chave de relacionamento com o SIMEC é o número completo da NE (`numero_completo_ne`), que
deve bater com `src.teds_normalizacao.chave_empenho` depois de decompor UG/gestão/número —
ver `src.teds_normalizacao.decompor_numero_ne`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.teds_importacao_simec import LinhaRejeitada
from src.teds_normalizacao import (
    linha_origem as _linha_origem,
    mapear_colunas as _mapear_colunas,
    normalizar_codigo,
    normalizar_nome_coluna,
    parse_valor_brl,
    texto_coluna as _texto,
)


@dataclass
class ResultadoLeituraTG:
    registros: list[dict[str, Any]] = field(default_factory=list)
    rejeitadas: list[LinhaRejeitada] = field(default_factory=list)


_MAPA_EXECUCAO_TG = {
    "numero_completo_ne": (
        normalizar_nome_coluna("Número Completo NE"),
        normalizar_nome_coluna("Número da NE"),
        normalizar_nome_coluna("NE"),
    ),
    "favorecido": (normalizar_nome_coluna("Favorecido"),),
    "descricao": (normalizar_nome_coluna("Descrição"),),
    "empenhado": (normalizar_nome_coluna("Valor Empenhado"), normalizar_nome_coluna("Empenhado")),
    "liquidado": (normalizar_nome_coluna("Valor Liquidado"), normalizar_nome_coluna("Liquidado")),
    "pago": (normalizar_nome_coluna("Valor Pago"), normalizar_nome_coluna("Pago")),
    "documento_habil": (normalizar_nome_coluna("Documento Hábil"),),
    "documento_contabil": (normalizar_nome_coluna("Documento Contábil"),),
    "ano_competencia": (normalizar_nome_coluna("Ano Competência"), normalizar_nome_coluna("Ano de Referência")),
    "mes_competencia": (normalizar_nome_coluna("Mês Competência"), normalizar_nome_coluna("Mês de Referência")),
    "valor_competencia": (normalizar_nome_coluna("Valor Competência"),),
}

_CAMPOS_VALOR_OPCIONAIS = ("empenhado", "liquidado", "pago", "valor_competencia")


def _valor_opcional(linha: pd.Series, colunas: dict[str, str], campo: str):
    coluna = colunas.get(campo)
    if coluna is None or pd.isna(linha[coluna]):
        return None
    return parse_valor_brl(linha[coluna])


def _inteiro_opcional(linha: pd.Series, colunas: dict[str, str], campo: str):
    coluna = colunas.get(campo)
    if coluna is None or pd.isna(linha[coluna]):
        return None
    return int(float(linha[coluna]))


def ler_execucao_tg(df: pd.DataFrame) -> ResultadoLeituraTG:
    colunas = _mapear_colunas(df.columns, _MAPA_EXECUCAO_TG)
    resultado = ResultadoLeituraTG()

    if "numero_completo_ne" not in colunas:
        raise ValueError(
            "Coluna do número completo da NE não encontrada — layout do Tesouro Gerencial "
            "não confirmado; ajuste _MAPA_EXECUCAO_TG com o cabeçalho real da extração."
        )

    for indice, linha in df.iterrows():
        origem = _linha_origem(linha)
        numero_completo_ne = _texto(linha, colunas, "numero_completo_ne")
        if not numero_completo_ne:
            resultado.rejeitadas.append(
                LinhaRejeitada(indice, "sem número completo de NE (possível rodapé)", origem)
            )
            continue

        try:
            valores = {campo: _valor_opcional(linha, colunas, campo) for campo in _CAMPOS_VALOR_OPCIONAIS}
        except (ValueError, TypeError) as exc:
            resultado.rejeitadas.append(LinhaRejeitada(indice, str(exc), origem))
            continue

        registro = {
            "numero_completo_ne": normalizar_codigo(numero_completo_ne),
            "favorecido": _texto(linha, colunas, "favorecido") or None,
            "descricao": _texto(linha, colunas, "descricao") or None,
            "documento_habil": _texto(linha, colunas, "documento_habil") or None,
            "documento_contabil": _texto(linha, colunas, "documento_contabil") or None,
            "ano_competencia": _inteiro_opcional(linha, colunas, "ano_competencia"),
            "mes_competencia": _inteiro_opcional(linha, colunas, "mes_competencia"),
            "linha_origem": origem,
            **valores,
        }
        resultado.registros.append(registro)

    return resultado
