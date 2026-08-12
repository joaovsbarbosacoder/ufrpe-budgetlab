"""Página inicial do UFRPE BudgetLab."""

import streamlit as st

from src.ui_theme import render_page_header

render_page_header(
    "UFRPE BudgetLab",
    "Ambiente institucional para gestão e análise orçamentária.",
    "Gestão orçamentária",
)

with st.container(border=True):
    st.subheader("Visão geral")
    st.write(
        "Importe bases do Tesouro Gerencial para inspecionar, normalizar e "
        "analisar informações orçamentárias com rastreabilidade."
    )

with st.container(border=True):
    st.subheader("Módulos disponíveis")
    st.markdown(
        "- Importação de bases em memória\n"
        "- Dotação Orçamentária validada\n"
        "- Execução da Despesa validada"
    )

st.caption("As funcionalidades futuras serão habilitadas conforme suas regras de negócio forem confirmadas.")
