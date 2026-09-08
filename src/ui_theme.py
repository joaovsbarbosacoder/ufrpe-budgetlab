"""Componentes visuais reutilizáveis do UFRPE BudgetLab."""

from __future__ import annotations

import math
import numbers

import pandas as pd
import streamlit as st

from src.design_tokens import (
    ACCENT,
    ACCENT_SOFT,
    ACCENT_STRONG,
    BG,
    BG_GRADIENT_EDGE,
    BORDER,
    RADIUS,
    SIDEBAR_BG,
    SURFACE,
    TEXT,
    TEXT_MUTED,
)


_THEME_CSS = f"""
<style>
    [data-testid="stAppViewContainer"] {{
        background: radial-gradient(circle at top left, {BG_GRADIENT_EDGE} 0%, {BG} 55%);
    }}
    /* Antes do menu ir pra lateral, esse cabeçalho tinha a barra de navegação do topo dentro
       dele — o fundo escuro semi-transparente disfarçava como parte dela. Sem a navegação
       ali, ele sobrava como uma faixa com tom diferente do resto do painel (pedido explícito
       pra corrigir) — transparente deixa o gradiente de fundo do app aparecer por trás,
       igual ao restante da página; só o botão "Deploy"/menu "⋮" continuam visíveis. */
    [data-testid="stHeader"] {{
        background: transparent;
        position: static !important;
    }}
    .block-container {{ max-width: 1480px; padding-top: 1rem; padding-bottom: 3.25rem; }}
    [data-testid="stMetric"] {{
        background: transparent;
        border: 0;
        border-radius: 0;
        padding: 0.15rem 0;
        box-shadow: none;
    }}
    [data-testid="stMetricValue"] {{ font-weight: 650; letter-spacing: -0.02em; color: {TEXT}; }}
    [data-testid="stMetricLabel"] {{ color: {TEXT_MUTED}; font-weight: 600; }}
    [data-testid="stDataFrame"] {{ border: 1px solid {BORDER}; border-radius: {RADIUS}; overflow: hidden; }}
    /* Barra lateral escondida por padrão (pedido explícito) — só uma fresta de 0,5rem na
       borda esquerda pra servir de área de hover; expande pra largura confortável ao
       encostar o mouse nela. min-width/width juntos porque o Streamlit define os dois via
       style inline (ver stSidebar); só max-width não bastava para vencer o width inline. */
    [data-testid="stSidebar"] {{
        background: {SIDEBAR_BG};
        border-right: 1px solid {BORDER};
        min-width: 0.5rem !important;
        width: 0.5rem !important;
        transition: width 0.18s ease, min-width 0.18s ease;
    }}
    [data-testid="stSidebar"]:hover {{
        min-width: 21rem !important;
        width: 21rem !important;
    }}
    /* O conteúdo (ícones, nav, logo) só aparece junto com a expansão — sem isso, a fresta de
       0,5rem ainda mostraria uma lasca cortada dos ícones por baixo do overflow:hidden. */
    [data-testid="stSidebarContent"] {{
        overflow-x: hidden;
        opacity: 0;
        transition: opacity 0.12s ease;
    }}
    [data-testid="stSidebar"]:hover [data-testid="stSidebarContent"] {{ opacity: 1; }}
    /* Alça nativa de redimensionar a sidebar (div com cursor:col-resize bem na borda) — some
       o tamanho normal do trilho, mas arrastá-la sem querer destrava um tamanho intermediário
       "grudado" e sua barra de destaque (cor de acento) fica sólida por cima da fresta — a
       barra azul sólida que quebrou o layout. Sem sentido mesmo com o trilho de largura fixa
       controlada por CSS: o usuário não deveria conseguir redimensionar manualmente. */
    [data-testid="stSidebar"] div[style*="cursor: col-resize"] {{
        display: none !important;
        pointer-events: none !important;
    }}
    /* Logo institucional no topo da lateral, injetada via markdown (não usamos st.logo: o
       componente nativo zera a largura do próprio slot de cabeçalho quando detecta a sidebar
       estreita — ele decide colapsar medindo a largura real do contêiner no momento do
       primeiro render, não o estado de :hover, e nunca mais volta a mostrar a imagem depois
       disso). position:fixed tira a logo do fluxo do conteúdo da sidebar (que só cresce por
       :hover via CSS, sem disparar o mecanismo de colapso nativo do Streamlit) e a ancora no
       canto superior esquerdo, sempre visível tanto no trilho estreito quanto expandido;
       padding-top no nav abre espaço pra ela não ficar por cima do primeiro item ("Início").
       Tamanho acompanha o :hover do próprio trilho (pedido explícito: pequena quando fechado,
       maior — proporcional — quando abre): a versão fechada fica bem dentro dos 4.5rem do
       trilho pra não vazar sobre a borda pro conteúdo principal (5.75rem fixos vazavam ~7px
       além da borda); a versão expandida usa a folga extra dos 21rem abertos. */
    .ufrpe-sidebar-logo {{
        position: fixed;
        top: 0.85rem;
        left: 1.05rem;
        z-index: 999;
    }}
    .ufrpe-sidebar-logo img {{
        height: 3.75rem !important;
        max-height: 3.75rem !important;
        width: auto !important;
        max-width: none !important;
        display: block;
        transition: height 0.18s ease, max-height 0.18s ease;
    }}
    [data-testid="stSidebar"]:hover .ufrpe-sidebar-logo img {{
        height: 6.5rem !important;
        max-height: 6.5rem !important;
    }}
    [data-testid="stSidebarNav"] {{ padding-top: 5rem; transition: padding-top 0.18s ease; }}
    [data-testid="stSidebar"]:hover [data-testid="stSidebarNav"] {{ padding-top: 8rem; }}
    [data-testid="stSidebarNavLink"] {{ border-radius: 10px; }}
    [data-testid="stSidebarNavLink"][aria-current="page"] {{
        background: {ACCENT_SOFT};
        color: {ACCENT};
    }}
    /* Rótulo de cada item some no estado estreito (só o ícone fica visível) e o cabeçalho
       de seção ("Contratos", "Administração") também — reaparecem ao passar o mouse. Largura
       de hover generosa (21rem) + nowrap: o pedido explícito era não voltar a cortar/quebrar
       o texto dos itens quando exibidos (ex.: "Empenhos com Execução Retardada"). */
    [data-testid="stSidebarNavLink"] span[label] {{
        display: inline-block;
        max-width: 0;
        opacity: 0;
        overflow: hidden;
        white-space: nowrap;
        transition: max-width 0.18s ease, opacity 0.12s ease;
    }}
    [data-testid="stSidebarNavLink"] span[label] p {{
        white-space: nowrap;
        overflow: visible;
        text-overflow: clip;
    }}
    [data-testid="stNavSectionHeader"] {{
        opacity: 0;
        max-height: 0;
        overflow: hidden;
        white-space: nowrap;
        transition: opacity 0.12s ease, max-height 0.18s ease;
    }}
    [data-testid="stSidebar"]:hover [data-testid="stSidebarNavLink"] span[label] {{
        max-width: 16rem;
        opacity: 1;
    }}
    [data-testid="stSidebar"]:hover [data-testid="stNavSectionHeader"] {{
        opacity: 1;
        max-height: 2.5rem;
    }}
    [data-testid="stAlert"] {{ border-radius: {RADIUS}; border-width: 1px; }}
    [data-testid="stExpander"] {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS};
    }}
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 16px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    }}
    [data-testid="stTabs"] button[role="tab"] {{ color: {TEXT_MUTED}; }}
    [data-testid="stTabs"] button[aria-selected="true"] {{ color: {ACCENT}; }}
    [data-testid="stMultiSelectTagsContainer"] {{ flex-wrap: wrap; row-gap: 0.35rem; }}

    * {{ scrollbar-color: {ACCENT} transparent; scrollbar-width: auto; }}
    ::-webkit-scrollbar {{ width: 40px; height: 40px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{
        background-color: {ACCENT};
        border-radius: 999px;
        border: 10px solid {BG};
        background-clip: padding-box;
        min-height: 96px;
    }}
    ::-webkit-scrollbar-thumb:hover {{
        background-color: {ACCENT_STRONG};
        background-clip: padding-box;
    }}
</style>
"""


def apply_theme() -> None:
    """Aplica tokens e ajustes visuais estáticos em toda a sessão Streamlit."""

    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def render_page_header(title: str, subtitle: str | None = None, context: str | None = None) -> None:
    """Exibe cabeçalho consistente, sem alterar dados ou estado da página."""

    st.title(title)
    if subtitle:
        st.caption(subtitle)
    if context:
        st.badge(context, icon=":material/account_balance:", color="blue")


def render_alert(message: str, status: str = "info") -> None:
    """Faixa horizontal baseada em um estado funcional já calculado."""

    alerts = {
        "error": (st.error, ":material/error:"),
        "warning": (st.warning, ":material/warning:"),
        "success": (st.success, ":material/check_circle:"),
        "info": (st.info, ":material/info:"),
    }
    renderer, icon = alerts[status]
    renderer(message, icon=icon)


def render_metric_grid(metrics: list[dict[str, object]], columns: int = 4) -> None:
    """Exibe métricas em cartões responsivos, no máximo quatro por linha."""

    for start in range(0, len(metrics), columns):
        row = metrics[start : start + columns]
        grid = st.columns(len(row), vertical_alignment="top", border=True)
        for column, metric in zip(grid, row, strict=True):
            with column:
                st.metric(
                    str(metric["label"]),
                    str(metric["value"]),
                    help=metric.get("help"),
                )
                subtitle = metric.get("subtitle")
                if subtitle:
                    st.caption(str(subtitle))


def format_brl_compact(value: object) -> str:
    """Formata valor financeiro para leitura gerencial, preservando o sinal."""

    if _is_null(value):
        return "Valor nulo"
    amount = float(value)
    absolute = abs(amount)
    for divisor, suffix, decimals in ((1_000_000_000, "bi", 2), (1_000_000, "mi", 1), (1_000, "mil", 1)):
        if absolute >= divisor:
            return f"R$ {_format_number(amount / divisor, decimals)} {suffix}"
    return f"R$ {_format_number(amount, 2)}"


def format_brl_full(value: object) -> str:
    """Formata valor financeiro completo para conferência e reconciliação."""

    if _is_null(value):
        return "Valor nulo"
    return "R$ " + f"{float(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def currency_column(label: str = "Valor do movimento") -> st.column_config.NumberColumn:
    """Configuração comum para colunas monetárias completas em tabelas."""

    return st.column_config.NumberColumn(label, format="R$ %.2f")


def _format_number(value: float, decimals: int) -> str:
    text = f"{value:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return text.rstrip("0").rstrip(",") if "," in text else text


def _is_null(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        return math.isnan(float(value))
    result = pd.isna(value)
    try:
        return bool(result)
    except (TypeError, ValueError):
        return False
