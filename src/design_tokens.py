"""Tokens da única identidade visual clara do UFRPE BudgetLab.

Consumido por `ui_theme.py`, pelas páginas com componentes HTML e pelos
gráficos. As cores são constantes: o sistema não possui modo escuro nem
estado de sessão relacionado a tema.
"""

from __future__ import annotations

# Cores de status específicas do handoff "Acompanhamento de Pessoal".
PESSOAL_NEGATIVE = "#F85149"
PESSOAL_POSITIVE = "#3FB950"

# --- Cores fixas ------------------------------------------------------------
BG = "#F5F8FC"
BG_GRADIENT_EDGE = "#EDF4FB"
SIDEBAR_BG = "#0B3557"
SIDEBAR_BG_TOP = "#0D4268"
SIDEBAR_BG_BOTTOM = "#082B49"
SIDEBAR_TEXT = "#EAF3FA"
SIDEBAR_TEXT_MUTED = "#94B7D4"
SIDEBAR_ACTIVE = "#166FCA"
SIDEBAR_ACTIVE_BORDER = "#8CC7FF"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F0F5FA"
BORDER = "#D3DFEC"
BORDER_SOFT = "rgba(11,53,87,0.08)"
TEXT = "#07133D"
TEXT_MUTED = "#526584"
TEXT_FAINT = "#7C8DA8"
ACCENT = "#0969DA"
ACCENT_STRONG = "#0757B8"
ACCENT_SOFT = "rgba(9,105,218,0.10)"
ACCENT_LINE = "rgba(9,105,218,0.32)"
POSITIVE = "#0A8F3D"
NEGATIVE = "#D20A16"
WARNING = "#C96A00"
POSITIVE_SOFT = "rgba(10,143,61,0.11)"
NEGATIVE_SOFT = "rgba(210,10,22,0.09)"
WARNING_SOFT = "rgba(201,106,0,0.11)"

# --- Tipografia (não varia por tema) ----------------------------------------
FONT_BODY = '"Inter", "Segoe UI", system-ui, sans-serif'
FONT_HEADING = '"Inter", "Segoe UI Semibold", "Segoe UI", system-ui, sans-serif'
FONT_MONO_NUM = "font-variant-numeric: tabular-nums;"

SIZE = {
    "micro": "10px", "code": "10.5px", "label": "11px", "meta": "11.5px",
    "small": "12.5px", "body": "13.5px", "value": "13px", "value_strong": "14px",
    "card_title": "23px", "metric": "29px", "brand": "21px",
}
TRACK = {"tight": "0.06em", "label": "0.12em", "kicker": "0.16em"}

# --- Espaçamento / forma (não varia por tema) -------------------------------
SPACE = {"xs": "6px", "sm": "10px", "md": "14px", "lg": "18px", "xl": "22px", "xxl": "32px"}
RADIUS = "8px"
RADIUS_SM = "6px"
CARD_PAD = "16px 18px"

# Soma das larguras mínimas de SUBDIV_COLUMNS + os 9 espaçamentos de
# SUBDIV_GAP entre elas — mantém as duas constantes coerentes entre si em
# vez de um número solto maior que o necessário (o que forçava rolagem
# horizontal mesmo quando a tabela cabia no cartão).
TABLE_MIN_WIDTH = "1000px"

# --- Grade da tabela de subdivisões (uma definição, todos os usos) --------
SUBDIV_COLUMNS = (
    "minmax(150px, 1.4fr) minmax(110px, 1fr) "
    "minmax(110px, 0.8fr) minmax(100px, 0.7fr) 46px 64px 92px 88px 96px 104px"
)
SUBDIV_GAP = "6px"


def plotly_layout() -> dict:
    """Layout-base claro para gráficos Plotly."""
    return dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_BODY, color=TEXT, size=12),
        colorway=[ACCENT, ACCENT_STRONG, POSITIVE, NEGATIVE, TEXT_MUTED],
        xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        margin=dict(l=8, r=8, t=28, b=8),
    )
