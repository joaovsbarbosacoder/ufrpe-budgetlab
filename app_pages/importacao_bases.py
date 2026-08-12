"""Importação em memória com reconhecimento e validação gerencial das bases."""

from __future__ import annotations

import streamlit as st

from src.dotacao_anual_analysis import (
    DOTACAO_ANUAL_ANALYSIS_SESSION_KEY,
    prepare_validated_dotacao_anual_dataset,
)
from src.excel_importer import list_excel_sheets
from src.tesouro_dotacao_anual_workbook import (
    DotacaoAnualWorkbookResult,
    process_dotacao_anual_workbook,
)
from src.ui_theme import render_alert, render_page_header


@st.cache_data(show_spinner=False, max_entries=10)
def _cached_sheet_names(file_content: bytes, filename: str) -> list[str]:
    return list_excel_sheets(file_content, filename)


@st.cache_data(show_spinner=False, max_entries=3)
def _cached_dotacao_anual_workbook(
    file_content: bytes, filename: str
) -> DotacaoAnualWorkbookResult:
    return process_dotacao_anual_workbook(file_content, filename)


def _format_file_size(size_in_bytes: int) -> str:
    if size_in_bytes < 1024:
        return f"{size_in_bytes} bytes"
    if size_in_bytes < 1024**2:
        return f"{size_in_bytes / 1024:.1f} KB"
    return f"{size_in_bytes / 1024**2:.1f} MB"


render_page_header(
    "Importação de Bases",
    "As bases são analisadas somente em memória; os arquivos originais não são alterados.",
    "Importação",
)

uploaded_file = st.file_uploader(
    "Arquivo Excel",
    type=["xlsx", "xls"],
    help="Formatos aceitos: .xlsx e .xls.",
)

if uploaded_file is None:
    st.info("Selecione um arquivo Excel para iniciar a importação.")
    st.stop()

file_content = uploaded_file.getvalue()
try:
    sheet_names = _cached_sheet_names(file_content, uploaded_file.name)
except Exception as error:
    st.error(f"Não foi possível ler o arquivo: {error}")
    st.stop()

with st.container(border=True):
    st.caption("Arquivo selecionado")
    st.write(f"**Nome:** {uploaded_file.name}")
    st.write(f"**Tamanho:** {_format_file_size(uploaded_file.size)}")
    st.write(f"**Abas disponíveis:** {', '.join(sheet_names)}")

try:
    with st.spinner("Reconhecendo a estrutura de Dotação Anual..."):
        dotacao_anual_workbook_result = _cached_dotacao_anual_workbook(
            file_content, uploaded_file.name
        )
except Exception as error:
    st.session_state.pop(DOTACAO_ANUAL_ANALYSIS_SESSION_KEY, None)
    st.warning(f"Não foi possível processar a base de Dotação Anual: {error}")
else:
    if dotacao_anual_workbook_result.recognized_sheets:
        render_alert("Base de Dotação Anual reconhecida.", "success")
        if dotacao_anual_workbook_result.integrity_approved:
            try:
                anual_dataset = prepare_validated_dotacao_anual_dataset(
                    dotacao_anual_workbook_result, file_content
                )
            except ValueError as error:
                st.session_state.pop(DOTACAO_ANUAL_ANALYSIS_SESSION_KEY, None)
                st.error(f"A base não pôde ser disponibilizada para análise: {error}")
            else:
                st.session_state[DOTACAO_ANUAL_ANALYSIS_SESSION_KEY] = anual_dataset
                render_alert("Validação aprovada.", "success")
                anos = sorted(
                    str(int(value))
                    for value in anual_dataset.normalized_data["ano_lancamento"]
                    .dropna()
                    .unique()
                )
                st.caption(f"Anos: {', '.join(anos) or 'não informado'}")
        else:
            st.session_state.pop(DOTACAO_ANUAL_ANALYSIS_SESSION_KEY, None)
            render_alert(
                "A validação da Dotação Anual encontrou inconsistências.", "error"
            )
    else:
        st.info(
            "Nenhuma informação corresponde à estrutura confirmada de Dotação Anual."
        )
