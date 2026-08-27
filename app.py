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
        # seção "" fica no início do menu, sem cabeçalho de grupo (ver docstring de
        # st.navigation) — mantém as páginas que não são sobre Contratos sem um nível extra
        # de agrupamento visual. Com position="sidebar" (pedido explícito, no lugar da barra
        # no topo), cada seção nomeada vira um cabeçalho na lateral, com as páginas listadas
        # uma abaixo da outra por baixo dele — não mais um dropdown por seção, como era com
        # position="top".
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
        # Contratos Contínuos e Contratos Vigência agrupadas sob um cabeçalho "Contratos"
        # (pedido explícito). "Contratos — Pagamentos" foi tirada do menu por pedido explícito
        # (código mantido em app_pages/contratos_pagamentos.py e
        # src/contratos_pagamentos.py, pronta pra reativar bastando devolver o st.Page abaixo).
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
        ],
        # último grupo da lateral, por pedido explícito ("o menu de reimportação no final") —
        # uma seção própria, não dentro de "" ou "Contratos", justamente para garantir que
        # fica depois de tudo (a ordem das seções na lateral segue a ordem das chaves aqui).
        "Administração": [
            st.Page(
                "app_pages/atualizar_planilhas.py",
                title="Atualizar Planilhas",
                icon=":material/upload_file:",
            ),
        ],
    },
    position="sidebar",
)

page.run()
