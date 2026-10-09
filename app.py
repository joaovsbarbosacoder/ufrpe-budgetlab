import base64
from pathlib import Path

import streamlit as st

from src import cache_bases
from src.ui_theme import apply_theme

_LOGO_B64 = base64.b64encode(Path("assets/ufrpe_logo.png").read_bytes()).decode()

st.set_page_config(
    page_title="UFRPE BudgetLab",
    page_icon="📊",
    layout="wide",
)

apply_theme()
# Bases já lidas guardadas em Parquet (data/processed/cache_bases/), chaveadas pelo conteúdo do arquivo e
# pelo código do leitor — ver src/cache_bases.py. Sem pyarrow, segue lendo as planilhas normalmente.
cache_bases.ativar_no_app()

st.sidebar.markdown(
    f'<div class="ufrpe-sidebar-brand">'
    f'<img src="data:image/png;base64,{_LOGO_B64}" alt="Brasão da UFRPE" />'
    f'<div><strong>UFRPE</strong><span>BudgetLab</span></div></div>',
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
                "app_pages/painel_acoes.py",
                title="Painel por Ação",
                icon="🟪",
            ),
            st.Page(
                "app_pages/limite_empenho.py",
                title="Limite de Empenho",
                icon="🧮",
            ),
            st.Page(
                "app_pages/resultado_orcamentario.py",
                title="Resultado Orçamentário",
                icon="⚖️",
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
            st.Page(
                "app_pages/despesas_pessoal.py",
                title="Despesas de Pessoal",
                icon="🧑‍🏫",
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
                "app_pages/diario_oficial.py",
                title="Diário Oficial (DOU)",
                icon="📰",
            ),
            st.Page(
                "app_pages/painel_prazos.py",
                title="Gerenciamento de Prazos",
                icon="⏰",
            ),
            st.Page(
                "app_pages/glossario.py",
                title="Glossário",
                icon="📖",
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
        # Acompanhamento de TEDs — 6 páginas (layout adaptado de um handoff de design, ver
        # docstring de cada app_pages/teds_*.py): drill-down do detalhe do TED acontece dentro
        # de "TEDs" via st.session_state, não como página própria (ver teds_lista.py).
        "TEDs": [
            st.Page(
                "app_pages/teds_visao_geral.py",
                title="Visão geral",
                icon="🏠",
            ),
            st.Page(
                "app_pages/teds_lista.py",
                title="TEDs",
                icon="🧾",
            ),
            st.Page(
                "app_pages/teds_conciliacao.py",
                title="Conciliação",
                icon="🔁",
            ),
            st.Page(
                "app_pages/teds_celulas.py",
                title="Células NC × NE",
                icon="🧩",
            ),
            st.Page(
                "app_pages/teds_central_alertas.py",
                title="Alertas",
                icon="🔔",
            ),
            st.Page(
                "app_pages/teds_importacoes.py",
                title="Importações",
                icon="☁️",
            ),
            st.Page(
                "app_pages/teds_configuracoes.py",
                title="Configurações",
                icon="⚙️",
            ),
        ],
        # Novo módulo de escrita (não leitura de base do Tesouro): setores registram
        # demandas orçamentárias e a PROPLAD consolida. Seção própria entre "Contratos" e
        # "Administração" — "Administração" precisa continuar por último (ver comentário
        # abaixo), então a nova seção entra antes dela, não depois.
        "Demandas Orçamentárias": [
            # Novo modelo de captação (src/captacao/, SQLite) — substitui as duas páginas
            # abaixo, que saem quando "Minhas demandas" e "Consolidação" novas existirem
            # (etapas 5/6 e 9 do plano); até lá ficam para não deixar o setor sem formulário.
            st.Page(
                "app_pages/captacao_ciclo.py",
                title="Ciclo de Captação",
                icon="🗓️",
            ),
            st.Page(
                "app_pages/captacao_unidades.py",
                title="Unidades da Captação",
                icon="🏛️",
            ),
            st.Page(
                "app_pages/captacao_planos.py",
                title="Planos de Referência",
                icon="🎯",
            ),
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
            st.Page(
                "app_pages/backup_dados.py",
                title="Backup dos dados",
                icon="💾",
            ),
        ],
    },
    position="sidebar",
    # `expanded=False` (padrão do Streamlit) trunca a lista de páginas a partir de 12 e coloca
    # o resto atrás de um botão "View N more" — passamos de 12 pra 14 páginas ao adicionar
    # Emendas Parlamentares/Alertas Gerenciais e isso escondeu Contratos — Vigência, Minhas
    # Demandas, Proposta Consolidada e Atualizar Planilhas sem nenhum aviso. `True` mantém
    # todas sempre visíveis na navegação lateral persistente.
    expanded=True,
)

page.run()
