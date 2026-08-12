import streamlit as st

from src.dotacao_anual_analysis import DOTACAO_ANUAL_ANALYSIS_SESSION_KEY
from src.ui_theme import apply_theme

st.set_page_config(
    page_title="UFRPE BudgetLab",
    page_icon="📊",
    layout="wide",
)

apply_theme()

st.session_state.setdefault(DOTACAO_ANUAL_ANALYSIS_SESSION_KEY, None)

page = st.navigation(
    [
        st.Page("app_pages/home.py", title="Início", icon=":material/home:"),
        st.Page(
            "app_pages/importacao_bases.py",
            title="Importação de Bases",
            icon=":material/upload_file:",
        ),
        st.Page(
            "app_pages/dotacao_orcamentaria.py",
            title="Dotação Orçamentária",
            icon=":material/monitoring:",
        ),
        st.Page(
            "app_pages/painel_acoes.py",
            title="Painel por Ação",
            icon=":material/grid_view:",
        ),
        st.Page(
            "app_pages/execucao_orcamentaria.py",
            title="Execução Orçamentária",
            icon=":material/payments:",
        ),
    ],
    position="top",
)

page.run()
