"""Tokens de design consolidados — fonte única de cor, tipografia e espaçamento.

Consumido por `ui_theme.py` (CSS global), pelas páginas que usam HTML
injetado (ex.: `app_pages/painel_acoes.py`) e pelos gráficos Plotly.
Objetivo: nunca repetir hexadecimal solto fora deste arquivo.
"""

# --- Cor (tema escuro, acento azul alinhado ao .streamlit/config.toml) ----
BG = "#0B1220"  # fundo da página (Streamlit base)
BG_GRADIENT_EDGE = "#101A2E"  # realce sutil do gradiente radial de fundo
SIDEBAR_BG = "#0E1626"  # fundo da sidebar (igual a [theme.sidebar] no config.toml)
SURFACE = "#121B2D"  # fundo de card / expander
SURFACE_ALT = "#1C2537"  # linha zebrada / hover
BORDER = "#232E45"  # hairline de card e cabeçalho de tabela
BORDER_SOFT = "rgba(255,255,255,0.07)"  # separador entre linhas da tabela

TEXT = "#E7ECF5"  # texto principal
TEXT_MUTED = "#93A1B8"  # rótulos, códigos, metadados
TEXT_FAINT = "#6E7994"  # placeholders, "—"

ACCENT = "#4C8DFF"  # acento (igual a primaryColor do config.toml)
ACCENT_STRONG = "#7FB0FF"  # números de destaque sobre fundo escuro
ACCENT_SOFT = "rgba(76,141,255,0.14)"  # fills e hovers tintados
ACCENT_LINE = "rgba(76,141,255,0.35)"  # borda de tag

POSITIVE = "#22C55E"  # suplementação
NEGATIVE = "#F0576B"  # cancelamento / remanejamento negativo
WARNING = "#F5A524"

# --- Tipografia ------------------------------------------------------------
FONT_BODY = '"Segoe UI", system-ui, sans-serif'
FONT_HEADING = '"Segoe UI Semibold", "Segoe UI", system-ui, sans-serif'
FONT_MONO_NUM = "font-variant-numeric: tabular-nums;"

SIZE = {
    "micro": "10px", "code": "10.5px", "label": "11px", "meta": "11.5px",
    "small": "12.5px", "body": "13.5px", "value": "13px", "value_strong": "14px",
    "card_title": "23px", "metric": "29px", "brand": "21px",
}
TRACK = {"tight": "0.06em", "label": "0.12em", "kicker": "0.16em"}

# --- Espaçamento / forma ----------------------------------------------------
SPACE = {"xs": "6px", "sm": "10px", "md": "14px", "lg": "18px", "xl": "22px", "xxl": "32px"}
RADIUS = "14px"  # raio dos cartões do app (mais arredondado que o do handoff)
RADIUS_SM = "10px"
CARD_PAD = "18px 20px 16px"

# Soma das larguras mínimas de SUBDIV_COLUMNS + os 9 espaçamentos de
# SUBDIV_GAP entre elas — mantém as duas constantes coerentes entre si em
# vez de um número solto maior que o necessário (o que forçava rolagem
# horizontal mesmo quando a tabela cabia no cartão).
TABLE_MIN_WIDTH = "830px"

# --- Grade da tabela de subdivisões (uma definição, todos os usos) --------
# Iduso/PTRES e as quatro colunas de valor foram encolhidas ao ponto de
# quase não sobrar espaço livre dentro de cada uma: como Iduso/PTRES são
# alinhados à esquerda e os valores à direita, uma coluna larga demais para
# o conteúdo típico (poucos dígitos) sobra como espaço em branco bem no
# meio da grade — o "vão" entre PTRES/Inicial e entre Cancelamento/
# Atualizada relatado. Colunas mais justas ao conteúdo real reduzem isso.
SUBDIV_COLUMNS = (
    "minmax(150px, 1.4fr) minmax(110px, 1fr) "
    "64px 60px 42px 44px 72px 72px 78px 84px"
)
SUBDIV_GAP = "6px"

# --- Plotly ------------------------------------------------------------------
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family=FONT_BODY, color=TEXT, size=12),
    colorway=[ACCENT, ACCENT_STRONG, POSITIVE, NEGATIVE, TEXT_MUTED],
    xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
    yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
    margin=dict(l=8, r=8, t=28, b=8),
)
