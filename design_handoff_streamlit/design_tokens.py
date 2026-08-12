"""Tokens de design consolidados — fonte única para o painel.

Coloque em src/design_tokens.py e importe em ui_theme.py, nas páginas e nos gráficos
Plotly. Objetivo: nunca mais repetir hexadecimal solto.
"""

# --- Cor (tema escuro, acento azul já usado no config.toml) ---------------
BG            = "#0E1117"   # fundo da página (Streamlit base)
SURFACE       = "#161B22"   # fundo de card / sidebar
SURFACE_ALT   = "#1C2229"   # linha zebrada / hover
BORDER        = "#2A313A"   # hairline de card e cabeçalho de tabela
BORDER_SOFT   = "rgba(255,255,255,0.07)"  # separador entre linhas da tabela

TEXT          = "#E6EDF3"   # texto principal
TEXT_MUTED    = "#8B949E"   # rótulos, códigos, metadados
TEXT_FAINT    = "#6E7681"   # placeholders, "—"

ACCENT        = "#4C8DFF"   # acento
ACCENT_STRONG = "#7FB0FF"   # números de destaque sobre fundo escuro
ACCENT_SOFT   = "rgba(76,141,255,0.12)"   # fills e hovers tintados
ACCENT_LINE   = "rgba(76,141,255,0.35)"   # borda de tag

POSITIVE      = "#3FB950"   # suplementação
NEGATIVE      = "#F85149"   # cancelamento / remanejamento negativo

# --- Tipografia ----------------------------------------------------------
FONT_BODY     = '"Barlow", "Segoe UI", system-ui, sans-serif'
FONT_HEADING  = '"Barlow Condensed", "Barlow", system-ui, sans-serif'
FONT_MONO_NUM = 'font-variant-numeric: tabular-nums;'

SIZE = {
    "micro": "10px", "code": "10.5px", "label": "11px", "meta": "11.5px",
    "small": "12.5px", "body": "13.5px", "value": "13px", "value_strong": "14px",
    "card_title": "23px", "metric": "29px", "brand": "21px",
}
TRACK = {"tight": "0.06em", "label": "0.12em", "kicker": "0.16em"}

# --- Espaçamento / forma -------------------------------------------------
SPACE = {"xs": "6px", "sm": "10px", "md": "14px", "lg": "18px", "xl": "22px", "xxl": "32px"}
RADIUS = "4px"          # mantém o raio do config.toml
CARD_PAD = "18px 20px 16px"
TABLE_MIN_WIDTH = "1200px"

# --- Grade da tabela de subdivisões (uma definição, três usos) ------------
SUBDIV_COLUMNS = (
    "minmax(220px, 1.6fr) minmax(150px, 1.1fr) "
    "92px 88px 74px 66px 104px 96px 104px 116px"
)
SUBDIV_GAP = "10px"

# --- Plotly (se voltar a haver gráficos em outras páginas) ---------------
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Barlow, system-ui, sans-serif", color=TEXT, size=12),
    colorway=[ACCENT, ACCENT_STRONG, POSITIVE, NEGATIVE, TEXT_MUTED],
    xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
    yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
    margin=dict(l=8, r=8, t=28, b=8),
)
