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
        "Cada base tem importação própria e versionada, com manifesto e "
        "rastreabilidade completa até a célula de origem. A reimportação "
        "acontece dentro da própria página de análise da base."
    )

with st.container(border=True):
    st.subheader("Módulos disponíveis")
    st.markdown(
        "- Dotação Orçamentária (Dotação Anual)\n"
        "- Painel por Ação de Governo (Dotação Anual)\n"
        "- Execução Orçamentária (Execução Anual)"
    )

st.caption("As funcionalidades futuras serão habilitadas conforme suas regras de negócio forem confirmadas.")
