import streamlit as st

from src.ui_theme import apply_theme

st.set_page_config(
    page_title="UFRPE BudgetLab",
    page_icon="📊",
    layout="wide",
)

apply_theme()

page = st.navigation(
    {
        # seção "" fica no início do menu, fora do agrupamento colapsável (ver docstring de
        # st.navigation) — mantém as páginas que não são sobre Contratos sem um nível extra
        # de clique.
        "": [
            st.Page("app_pages/home.py", title="Início", icon=":material/home:"),
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
            st.Page(
                "app_pages/consulta_empenhos.py",
                title="Consulta de Empenhos",
                icon=":material/receipt_long:",
            ),
            st.Page(
                "app_pages/empenhos_execucao_retardada.py",
                title="Empenhos com Execução Retardada",
                icon=":material/schedule:",
            ),
            st.Page(
                "app_pages/bolsas_auxilios.py",
                title="Bolsas e Auxílios",
                icon=":material/school:",
            ),
        ],
        # com position="top", uma seção nomeada vira um item colapsável só — Contratos
        # Contínuos e Contratos Vigência ficam como subdivisões de um único botão "Contratos"
        # (pedido explícito), em vez de dois itens soltos disputando espaço na barra.
        # "Contratos — Pagamentos" foi tirada do menu por pedido explícito (código mantido em
        # app_pages/contratos_pagamentos.py e src/contratos_pagamentos.py, pronta pra reativar
        # bastando devolver o st.Page abaixo).
        "Contratos": [
            st.Page(
                "app_pages/contratos_continuos.py",
                title="Contratos Contínuos",
                icon=":material/handshake:",
            ),
            st.Page(
                "app_pages/contratos_vigencia.py",
                title="Contratos — Vigência",
                icon=":material/event_upcoming:",
            ),
            st.Page(
                "app_pages/relatorio_reforco_empenho.py",
                title="Relatório de Reforço de Empenho",
                icon=":material/picture_as_pdf:",
            ),
        ],
    },
    position="top",
)

page.run()