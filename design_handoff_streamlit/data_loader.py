"""Leitura da base de dotação (BI CPOC - DOTAÇÃO - Por Ano.xlsx).

A planilha traz os atributos nas colunas A–M e, a partir de N, quatro colunas de
valor por exercício, na ordem: inicial, suplementar, atualizada, cancelada.
As células de atributo vêm mescladas no Excel (só a primeira linha do bloco
preenchida), por isso o forward fill é obrigatório antes de qualquer agrupamento.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

ATTR_COLS = {          # índice da coluna no Excel -> (campo, parte)
    0: ("iduso", "cod"), 1: ("iduso", "nome"),
    2: ("rp", "cod"), 3: ("rp", "nome"),
    4: ("gnd", "cod"), 5: ("gnd", "nome"),
    6: ("acao", "cod"), 7: ("acao", "nome"),
    8: ("ptres", "cod"),
    9: ("fonte", "cod"), 10: ("fonte", "nome"),
    11: ("po", "cod"), 12: ("po", "nome"),
}
FIRST_VALUE_COL = 13
YEARS = ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]
MEASURES = ["ini", "sup", "atu", "can"]     # ordem das 4 colunas de cada ano
HEADER_ROWS = 3                              # linhas de cabeçalho a descartar


@st.cache_data(show_spinner=False)
def carregar_base(caminho: str) -> pd.DataFrame:
    """Devolve um DataFrame longo: uma linha por (lançamento, exercício)."""
    bruto = pd.read_excel(caminho, header=None, skiprows=HEADER_ROWS, dtype=object)

    attrs = bruto.iloc[:, : FIRST_VALUE_COL].copy()
    attrs = attrs.replace(r"^\s*$", pd.NA, regex=True).ffill()
    attrs.columns = [f"{campo}_{parte}" for campo, parte in ATTR_COLS.values()]
    for c in attrs.columns:
        attrs[c] = attrs[c].astype("string").str.strip().fillna("")

    registros = []
    for pos, ano in enumerate(YEARS):
        base = FIRST_VALUE_COL + pos * 4
        vals = bruto.iloc[:, base : base + 4].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        vals.columns = MEASURES
        bloco = pd.concat([attrs.reset_index(drop=True), vals.reset_index(drop=True)], axis=1)
        bloco["ano"] = ano
        registros.append(bloco)

    df = pd.concat(registros, ignore_index=True)
    df = df[df[MEASURES].abs().sum(axis=1) > 0]           # descarta anos sem dotação
    df = df[df["acao_cod"] != ""]
    return df.reset_index(drop=True)


# Conferência: soma de 'atu' por ano na base de referência.
TOTAIS_ESPERADOS = {
    "2020": 661_615_140, "2021": 654_455_308, "2022": 656_031_880,
    "2023": 734_927_983, "2024": 747_154_183, "2025": 851_526_938,
    "2026": 921_773_967,
}


def conferir(df: pd.DataFrame) -> dict[str, tuple[float, int, bool]]:
    """Compara os totais lidos com a conferência (tolerância de R$ 1)."""
    out = {}
    for ano, esperado in TOTAIS_ESPERADOS.items():
        lido = float(df.loc[df["ano"] == ano, "atu"].sum())
        out[ano] = (lido, esperado, abs(lido - esperado) < 1)
    return out
