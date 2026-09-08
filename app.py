import base64
from pathlib import Path

import streamlit as st

from src.ui_theme import apply_theme

_LOGO_B64 = base64.b64encode(Path("assets/ufrpe_logo.png").read_bytes()).decode()

st.set_page_config(
    page_title="UFRPE BudgetLab",
    page_icon="📊",
    layout="wide",
)

apply_theme()

st.sidebar.markdown(
    f'<div class="ufrpe-sidebar-logo">'
    f'<img src="data:image/png;base64,{_LOGO_B64}" alt="UFRPE" /></div>',
    unsafe_allow_html=True,
)

page = st.navigation(
    {
        # seção "" fica no início do menu, sem cabeçalho de grupo (ver docstring de
        # st.navigation) — mantém as páginas que não são sobre Contratos sem um nível extra
        # de agrupamento visual. Com position="sidebar" (pedido explícito, no lugar da barra
        # no topo), cada seção nomeada vira um cabeçalho na lateral, com as páginas listadas
        # uma abaixo da outra por baixo dele — não mais um dropdown por seção, como era com
        # position="top".
        "": [
            st.Page("app_pages/home.py", title="Início", icon="🏠"),
            st.Page(
                "app_pages/dotacao_orcamentaria.py",
                title="Dotação Orçamentária",
                icon="📊",
            ),
            st.Page(
                "app_pages/painel_acoes.py",
                title="Painel por Ação",
                icon="🟪",
            ),
            st.Page(
                "app_pages/execucao_orcamentaria.py",
                title="Execução Orçamentária",
                icon="💳",
            ),
            st.Page(
                "app_pages/execucao_mensal.py",
                title="Execução Mensal",
                icon="🗓️",
            ),
            st.Page(
                "app_pages/consulta_empenhos.py",
                title="Consulta de Empenhos",
                icon="📋",
            ),
            st.Page(
                "app_pages/empenhos_execucao_retardada.py",
                title="Empenhos com Execução Retardada",
                icon="🕐",
            ),
            st.Page(
                "app_pages/bolsas_auxilios.py",
                title="Bolsas e Auxílios",
                icon="🎓",
            ),
            # Adaptadas do handoff de design (README em uploads/) — layout final, dado
            # fictício/placeholder de propósito (ver docstring de cada página): critérios de
            # alerta e cadastro de emendas ainda não foram definidos/validados com a PROPLAD.
            st.Page(
                "app_pages/emendas_parlamentares.py",
                title="Emendas Parlamentares",
                icon="🏛️",
            ),
            st.Page(
                "app_pages/alertas_gerenciais.py",
                title="Alertas Gerenciais",
                icon="🚨",
            ),
            st.Page(
                "app_pages/painel_prazos.py",
                title="Prazos Orçamentários",
                icon="⏰",
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
                icon="🤝",
            ),
            st.Page(
                "app_pages/contratos_vigencia.py",
                title="Contratos — Vigência",
                icon="📅",
            ),
        ],
        # Novo módulo de escrita (não leitura de base do Tesouro): setores registram
        # demandas orçamentárias e a PROPLAD consolida. Seção própria entre "Contratos" e
        # "Administração" — "Administração" precisa continuar por último (ver comentário
        # abaixo), então a nova seção entra antes dela, não depois.
        "Demandas Orçamentárias": [
            st.Page(
                "app_pages/demandas_minhas.py",
                title="Minhas Demandas",
                icon="📝",
            ),
            st.Page(
                "app_pages/demandas_consolidado.py",
                title="Proposta Consolidada",
                icon="🗂️",
            ),
        ],
        # último grupo da lateral, por pedido explícito ("o menu de reimportação no final") —
        # uma seção própria, não dentro de "" ou "Contratos", justamente para garantir que
        # fica depois de tudo (a ordem das seções na lateral segue a ordem das chaves aqui).
        "Administração": [
            st.Page(
                "app_pages/atualizar_planilhas.py",
                title="Atualizar Planilhas",
                icon="📤",
            ),
        ],
    },
    position="sidebar",
    # `expanded=False` (padrão do Streamlit) trunca a lista de páginas a partir de 12 e coloca
    # o resto atrás de um botão "View N more" — passamos de 12 pra 14 páginas ao adicionar
    # Emendas Parlamentares/Alertas Gerenciais e isso escondeu Contratos — Vigência, Minhas
    # Demandas, Proposta Consolidada e Atualizar Planilhas sem nenhum aviso. `True` mantém
    # todas sempre visíveis, coerente com o trilho de ícones (que já esconde tudo até o
    # hover — esconder página atrás de mais um clique em cima disso seria demais).
    expanded=True,
)

page.run()