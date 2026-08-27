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
    /* Barra lateral em modo "trilho de ícones" por padrão (pedido explícito) — estreita o
       bastante pra caber só o ícone de cada página, expande pra largura confortável ao
       passar o mouse por cima. min-width/width juntos porque o Streamlit define os dois via
       style inline (ver stSidebar); só max-width não bastava para vencer o width inline. */
    [data-testid="stSidebar"] {{
        background: {SIDEBAR_BG};
        border-right: 1px solid {BORDER};
        min-width: 4.5rem !important;
        width: 4.5rem !important;
        transition: width 0.18s ease, min-width 0.18s ease;
    }}
    [data-testid="stSidebar"]:hover {{
        min-width: 21rem !important;
        width: 21rem !important;
    }}
    [data-testid="stSidebarContent"] {{ overflow-x: hidden; }}
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
