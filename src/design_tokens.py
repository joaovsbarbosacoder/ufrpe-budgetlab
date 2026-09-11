"""Tokens de design consolidados — fonte única de cor, tipografia e espaçamento.

Consumido por `ui_theme.py` (CSS global), pelas páginas que usam HTML
injetado (ex.: `app_pages/painel_acoes.py`) e pelos gráficos Plotly.
Objetivo: nunca repetir hexadecimal solto fora deste arquivo.

TEMA CLARO/ESCURO (pedido explícito — alternador na barra lateral, ver
`src/ui_theme.py::render_theme_toggle`): os tokens de COR abaixo (não os de
tipografia/espaçamento/forma, que não variam por tema) são reatribuídos a
cada execução de página pela chamada central `aplicar_paleta()`, feita em
`ui_theme.py::apply_theme()` — por sua vez chamada em `app.py` ANTES de
`page.run()` escolher e executar a página da vez.

Isso funciona porque o Streamlit reexecuta cada arquivo de página inteiro a
cada interação (inclusive suas linhas `from src.design_tokens import ...`)
— o valor lido nessa importação é sempre o corrente no momento do rerun,
já que este módulo já teve seus atributos reatribuídos por `aplicar_paleta()`
um pouco antes, em `app.py`. Página nenhuma precisa saber que o tema existe.

Um MÓDULO DE APOIO (não uma página — carregado uma única vez por processo,
`from X import Y` nele congela o valor de `Y` daquele momento pra sempre)
que precise refletir o tema atual dentro de uma função NÃO pode importar os
tokens de cor por nome no topo do arquivo: precisa acessar
`design_tokens.<TOKEN>` (atributo do módulo, resolvido no momento da
chamada) dentro da própria função. Ver `src/ui_linha_do_tempo.py` e
`src/ui_theme.py` como exemplos já corrigidos dessa forma.
"""

from __future__ import annotations

import streamlit as st

# --- Tema: chave de sessão e paletas de cor ---------------------------------

CHAVE_TEMA = "ufrpe_tema"
TEMA_PADRAO = "escuro"

# Cores de status específicas do handoff "Acompanhamento de Pessoal". Elas
# permanecem fixas nos dois temas para conservar a identidade visual do HTML.
PESSOAL_NEGATIVE = "#F85149"
PESSOAL_POSITIVE = "#3FB950"

#: Paleta escura (valores originais do projeto, inalterados).
_PALETA_ESCURA: dict[str, str] = {
    "BG": "#0B1220",
    "BG_GRADIENT_EDGE": "#101A2E",
    "SIDEBAR_BG": "#0E1626",
    "SURFACE": "#121B2D",
    "SURFACE_ALT": "#1C2537",
    "BORDER": "#232E45",
    "BORDER_SOFT": "rgba(255,255,255,0.07)",
    "TEXT": "#E7ECF5",
    "TEXT_MUTED": "#93A1B8",
    "TEXT_FAINT": "#6E7994",
    "ACCENT": "#4C8DFF",
    "ACCENT_STRONG": "#7FB0FF",
    "ACCENT_SOFT": "rgba(76,141,255,0.14)",
    "ACCENT_LINE": "rgba(76,141,255,0.35)",
    "POSITIVE": "#22C55E",
    "NEGATIVE": "#F0576B",
    "WARNING": "#F5A524",
    # Fundos tingidos dos avisos (st.info/success/warning/error) — cor mantida
    # (pedido explícito: "sem abrir mão de itens coloridos"), só com opacidade
    # baixa o bastante para o texto por cima continuar legível.
    "POSITIVE_SOFT": "rgba(34,197,94,0.14)",
    "NEGATIVE_SOFT": "rgba(240,87,107,0.14)",
    "WARNING_SOFT": "rgba(245,165,36,0.14)",
}

#: Paleta clara — mesma família de matizes (azul de acento, verde/vermelho/
#: âmbar de status), reequilibrada para contraste sobre fundo claro. Note
#: que ACCENT_STRONG aqui é mais ESCURO que ACCENT (inverso da paleta
#: escura, onde "mais forte" é mais CLARO): sobre fundo branco, contraste
#: maior vem de escurecer, não de clarear.
_PALETA_CLARA: dict[str, str] = {
    "BG": "#F4F6FB",
    "BG_GRADIENT_EDGE": "#E9EEF9",
    "SIDEBAR_BG": "#EEF2F9",
    "SURFACE": "#FFFFFF",
    "SURFACE_ALT": "#EEF2F9",
    "BORDER": "#D8DFEC",
    "BORDER_SOFT": "rgba(15,23,42,0.08)",
    "TEXT": "#101828",
    "TEXT_MUTED": "#5B6578",
    "TEXT_FAINT": "#8891A3",
    "ACCENT": "#2F6FE0",
    "ACCENT_STRONG": "#1D4ED8",
    "ACCENT_SOFT": "rgba(47,111,224,0.10)",
    "ACCENT_LINE": "rgba(47,111,224,0.35)",
    "POSITIVE": "#16A34A",
    "NEGATIVE": "#DC2626",
    "WARNING": "#D97706",
    "POSITIVE_SOFT": "rgba(22,163,74,0.12)",
    "NEGATIVE_SOFT": "rgba(220,38,38,0.10)",
    "WARNING_SOFT": "rgba(217,119,6,0.12)",
}

assert set(_PALETA_ESCURA) == set(_PALETA_CLARA), (
    "Paletas clara/escura precisam ter exatamente o mesmo conjunto de tokens de cor."
)


def tema_atual() -> str:
    """`"escuro"` ou `"claro"` — o tema da sessão atual (padrão: escuro)."""
    return st.session_state.get(CHAVE_TEMA, TEMA_PADRAO)


def alternar_tema() -> None:
    """Troca o tema da sessão atual (escuro <-> claro). Não redesenha nada
    sozinho — quem chama ainda precisa pedir um `st.rerun()` em seguida."""
    st.session_state[CHAVE_TEMA] = "claro" if tema_atual() == "escuro" else "escuro"


def aplicar_paleta() -> None:
    """Reatribui os tokens de COR deste módulo conforme o tema atual da
    sessão. Chamada central: `ui_theme.py::apply_theme()`, rodada em
    `app.py` antes de `page.run()` executar a página escolhida — depois
    disso, qualquer `from src.design_tokens import TEXT` (etc.) feito por
    uma página já lê o valor correto neste mesmo rerun."""
    paleta = _PALETA_CLARA if tema_atual() == "claro" else _PALETA_ESCURA
    globals().update(paleta)


# Valores padrão (tema escuro) já vinculados na primeira carga do módulo —
# garante um valor sensato mesmo se algo ler um token antes da primeira
# chamada de `aplicar_paleta()` num processo novo.
globals().update(_PALETA_ESCURA)

# --- Tipografia (não varia por tema) ----------------------------------------
FONT_BODY = '"Segoe UI", system-ui, sans-serif'
FONT_HEADING = '"Segoe UI Semibold", "Segoe UI", system-ui, sans-serif'
FONT_MONO_NUM = "font-variant-numeric: tabular-nums;"

SIZE = {
    "micro": "10px", "code": "10.5px", "label": "11px", "meta": "11.5px",
    "small": "12.5px", "body": "13.5px", "value": "13px", "value_strong": "14px",
    "card_title": "23px", "metric": "29px", "brand": "21px",
}
TRACK = {"tight": "0.06em", "label": "0.12em", "kicker": "0.16em"}

# --- Espaçamento / forma (não varia por tema) -------------------------------
SPACE = {"xs": "6px", "sm": "10px", "md": "14px", "lg": "18px", "xl": "22px", "xxl": "32px"}
RADIUS = "14px"  # raio dos cartões do app (mais arredondado que o do handoff)
RADIUS_SM = "10px"
CARD_PAD = "18px 20px 16px"

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
    """Layout-base para gráficos Plotly, com as cores do TEMA ATUAL — função
    (não mais um dict fixo) porque as cores variam por tema; construir um
    layout novo a cada gráfico, nunca guardar o retorno num objeto de
    módulo carregado uma única vez (mesmo motivo do docstring do topo)."""
    return dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_BODY, color=TEXT, size=12),
        colorway=[ACCENT, ACCENT_STRONG, POSITIVE, NEGATIVE, TEXT_MUTED],
        xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        margin=dict(l=8, r=8, t=28, b=8),
    )
