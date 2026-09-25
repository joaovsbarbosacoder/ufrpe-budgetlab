"""Componentes visuais reutilizáveis do UFRPE BudgetLab."""

from __future__ import annotations

import math
import numbers
from html import escape

import pandas as pd
import streamlit as st

from src import design_tokens


def _theme_css() -> str:
    """Monta o CSS global a partir da identidade visual clara e fixa."""
    d = design_tokens
    return f"""
<style>
    :root {{ color-scheme: light; }}
    html, body, [class*="css"] {{ font-family: {d.FONT_BODY}; }}
    [data-testid="stAppViewContainer"] {{
        background: linear-gradient(135deg, {d.BG_GRADIENT_EDGE} 0%, {d.BG} 42%, {d.BG} 100%);
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
    .block-container {{ max-width: 1680px; padding: 1rem 1.35rem 3.25rem; }}
    [data-testid="stAppViewContainer"] h1 {{
        font-family: {d.FONT_HEADING};
        font-size: clamp(1.8rem, 2.2vw, 2.35rem);
        font-weight: 750;
        letter-spacing: -0.035em;
        line-height: 1.08;
    }}
    [data-testid="stAppViewContainer"] h2,
    [data-testid="stAppViewContainer"] h3 {{
        font-family: {d.FONT_HEADING};
        font-weight: 700;
        letter-spacing: -0.02em;
    }}
    .ufrpe-page-context {{
        color: {d.ACCENT}; font-size: 0.72rem; font-weight: 750;
        letter-spacing: 0.09em; margin: 0 0 0.18rem; text-transform: uppercase;
    }}
    .ufrpe-page-subtitle {{
        color: {d.TEXT_MUTED}; font-size: 0.94rem; line-height: 1.45;
        margin: -0.3rem 0 1.05rem;
    }}
    [data-testid="stMetric"] {{
        background: transparent;
        border: 0;
        border-radius: 0;
        padding: 0.2rem 0.1rem;
        box-shadow: none;
    }}
    [data-testid="stMetricValue"] {{ font-weight: 750; letter-spacing: -0.035em; color: {d.TEXT}; }}
    [data-testid="stMetricLabel"] {{ color: {d.TEXT_MUTED}; font-weight: 600; }}
    .ufrpe-metric-icon {{
        width: 42px; height: 42px; border-radius: 50%; display: grid; place-items: center;
        float: left; margin: 0.2rem 0.75rem 0.35rem 0; color: #fff; font-size: 1.15rem;
        font-weight: 800; background: var(--tone); box-shadow: inset 0 -7px 14px rgba(0,0,0,.08);
    }}
    [data-testid="stDataFrame"] {{
        border: 1px solid {d.BORDER};
        border-radius: {d.RADIUS};
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(11, 53, 87, 0.05);
    }}
    [data-testid="stDataFrame"] [role="columnheader"] {{
        background: {d.SURFACE_ALT} !important;
        color: {d.TEXT} !important;
        font-weight: 700 !important;
    }}
    /* Navegação institucional persistente, como nas referências: a estrutura do
       produto fica sempre visível e o conteúdo não se desloca ao passar o mouse. */
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {d.SIDEBAR_BG_TOP} 0%, {d.SIDEBAR_BG} 52%, {d.SIDEBAR_BG_BOTTOM} 100%);
        border-right: 0;
        min-width: 15.5rem !important;
        width: 15.5rem !important;
        box-shadow: 3px 0 14px rgba(7, 19, 61, 0.10);
    }}
    /* Em janelas até ~1400px CSS (zoom de 100% em notebook), 15.5rem de menu + margens
       deixavam menos de 1100px para o conteúdo e cortavam as tabelas largas. */
    @media (max-width: 1400px) {{
        [data-testid="stSidebar"] {{ min-width: 13rem !important; width: 13rem !important; }}
        .block-container {{ padding-left: 0.75rem; padding-right: 0.75rem; }}
    }}
    [data-testid="stSidebarContent"] {{
        overflow-x: hidden;
        opacity: 1;
    }}
    [data-testid="stSidebar"] div[style*="cursor: col-resize"] {{
        display: none !important;
        pointer-events: none !important;
    }}
    .ufrpe-sidebar-brand {{
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 1rem 1rem 0.85rem;
        margin: 0 0.3rem 0.35rem;
        border-bottom: 1px solid rgba(255,255,255,0.13);
    }}
    .ufrpe-sidebar-brand img {{
        height: 3rem !important;
        max-height: 3rem !important;
        width: auto !important;
        max-width: none !important;
        display: block;
    }}
    .ufrpe-sidebar-brand div {{ display: grid; line-height: 1.05; }}
    .ufrpe-sidebar-brand strong {{ color: white; font-size: 1.08rem; letter-spacing: 0.02em; }}
    .ufrpe-sidebar-brand span {{ color: {d.SIDEBAR_TEXT_MUTED}; font-size: 0.9rem; margin-top: 0.22rem; }}
    [data-testid="stSidebarNav"] {{ padding-top: 0.25rem; }}
    [data-testid="stSidebarNavLink"] {{
        min-height: 2.8rem;
        margin: 0.1rem 0.45rem;
        padding-left: 0.8rem;
        border-radius: {d.RADIUS_SM};
        border-left: 3px solid transparent;
        color: {d.SIDEBAR_TEXT} !important;
    }}
    [data-testid="stSidebarNavLink"] * {{ color: {d.SIDEBAR_TEXT} !important; }}
    /* Nomes longos ("Limite de Empenho", "Consulta de Empenhos") apareciam cortados com
       reticências; quebram em duas linhas em vez de truncar. */
    [data-testid="stSidebarNavLink"] {{ height: auto; padding-block: 0.3rem; }}
    [data-testid="stSidebarNavLink"] * {{
        white-space: normal !important; overflow: visible !important;
        text-overflow: clip !important; overflow-wrap: anywhere;
    }}
    [data-testid="stSidebarNavLink"]:hover {{ background: rgba(255,255,255,0.08); }}
    [data-testid="stSidebarNavLink"][aria-current="page"] {{
        background: {d.SIDEBAR_ACTIVE};
        border-left-color: {d.SIDEBAR_ACTIVE_BORDER};
        color: white !important;
    }}
    [data-testid="stNavSectionHeader"] {{
        color: {d.SIDEBAR_TEXT_MUTED} !important;
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        padding: 1rem 1.15rem 0.25rem;
    }}
    /* Avisos (st.info/success/warning/error) — os componentes MAIS usados do sistema
       (~100 chamadas). Antes daqui só tinham raio/espessura de borda; o fundo vinha do
       tema fixo do config.toml e ficava escuro no modo claro.

       Inspecionei o bundle JS do Streamlit (.venv/.../streamlit/static/static/js) para
       confirmar isto por evidência, não suposição: os 4 estados (info/success/warning/
       error) compartilham o MESMO testid (`stAlert`) e recebem a cor por uma prop
       `kind` de styled-components (prefixo interno, nunca vira atributo do HTML
       renderizado — ver `AlertElement.*.js`). Não existe seletor CSS que distinga um
       do outro; as tentativas anteriores (`[kind=...]`, `stAlertContent*`) eram
       suposição e nunca casavam com nada. O ícone de cada aviso, por outro lado, JÁ
       vem colorido pelo próprio Streamlit (confirmado nos prints do usuário — checkmark
       verde, alerta laranja) — ele carrega o sinal semântico; aqui só precisa de fundo
       neutro e texto legível nos dois temas. */
    [data-testid="stAlert"] {{
        border-radius: {d.RADIUS};
        border-width: 1px;
        border-style: solid;
        background-color: {d.SURFACE_ALT};
        border-color: {d.BORDER};
        color: {d.TEXT};
    }}
    [data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {{ color: {d.TEXT} !important; }}
    [data-testid="stExpander"] {{
        background: {d.SURFACE};
        border: 1px solid {d.BORDER};
        border-radius: {d.RADIUS};
    }}
    [data-testid="stVerticalBlockBorderWrapper"] {{
        background: {d.SURFACE};
        border: 1px solid {d.BORDER};
        border-radius: {d.RADIUS};
        box-shadow: 0 3px 12px rgba(11, 53, 87, 0.06);
    }}
    /* `stTab` é o testid real de cada aba (confirmado no bundle, `index.*.js`) — não
       `button[role="tab"]` aninhado sob `stTabs`, que não corresponde à estrutura desta
       versão. `aria-selected` é atributo de acessibilidade de verdade (diferente das
       props `$isActive` de estilo, essas sim invisíveis ao CSS — ver comentário do
       checkbox acima), por isso funciona aqui para marcar a aba ativa. */
    [data-testid="stTab"] {{ color: {d.TEXT_MUTED}; }}
    [data-testid="stTab"][aria-selected="true"] {{ color: {d.ACCENT}; }}
    [data-testid="stTabs"] [role="tablist"] {{ border-bottom: 1px solid {d.BORDER}; gap: 0.4rem; }}
    [data-testid="stTab"] {{ min-height: 2.8rem; padding-inline: 1rem; font-weight: 650; }}
    [data-testid="stMultiSelectTagsContainer"] {{ flex-wrap: wrap; row-gap: 0.35rem; }}

    * {{ scrollbar-color: {d.ACCENT} transparent; scrollbar-width: auto; }}
    ::-webkit-scrollbar {{ width: 16px; height: 16px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{
        background-color: {d.ACCENT};
        border-radius: 999px;
        border: 3px solid {d.BG};
        background-clip: padding-box;
        min-height: 48px;
    }}
    ::-webkit-scrollbar-thumb:hover {{
        background-color: {d.ACCENT_STRONG};
        background-clip: padding-box;
    }}

    /* Texto genérico do Streamlit (título, cabeçalhos, markdown, legendas, rótulos de
       widget) — o Streamlit pinta isso pela cor fixa de .streamlit/config.toml (tema
       escuro, não controlado por este alternador em tempo real): sem esta cobertura,
       ficava cinza-claro quase ilegível sobre o fundo claro (reportado pelo usuário —
       texto "lavado", sem contraste).

       IMPORTANTE — por que só os CONTÊINERES levam cor aqui, e sem `!important`:
       o texto colorido do próprio app (valores positivos/negativos, códigos, destaques
       dos KPIs) é escrito em HTML injetado, que o Streamlit coloca DENTRO de um
       `stMarkdownContainer`. Pintar os descendentes (`p`, `span`, `li`) com `!important`
       apagaria justamente essas cores — o oposto do pedido ("sem abrir mão de itens
       coloridos"). Pintando só o contêiner, o valor desce por HERANÇA: todo elemento que
       tem cor própria declarada mantém a sua, e só o que não tem herda a cor do tema. */
    [data-testid="stAppViewContainer"],
    [data-testid="stMarkdownContainer"] {{ color: {d.TEXT}; }}
    /* Títulos e rótulos de widget não têm cor semântica em nenhuma página, então podem
       ser fixados direto — o Streamlit define a cor deles explicitamente e a herança
       sozinha não venceria. */
    [data-testid="stAppViewContainer"] h1,
    [data-testid="stAppViewContainer"] h2,
    [data-testid="stAppViewContainer"] h3,
    [data-testid="stAppViewContainer"] h4,
    [data-testid="stAppViewContainer"] h5,
    [data-testid="stAppViewContainer"] h6,
    [data-testid="stHeading"] {{ color: {d.TEXT} !important; }}
    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p {{ color: {d.TEXT_MUTED} !important; }}
    [data-testid="stWidgetLabel"] p {{ color: {d.TEXT} !important; }}
    [data-testid="stTextInput"] [data-testid="stWidgetLabel"] p,
    [data-testid="stTextArea"] [data-testid="stWidgetLabel"] p,
    [data-testid="stNumberInput"] [data-testid="stWidgetLabel"] p,
    [data-testid="stSelectbox"] [data-testid="stWidgetLabel"] p,
    [data-testid="stMultiSelect"] [data-testid="stWidgetLabel"] p {{
        color: {d.TEXT_MUTED} !important;
        font-size: 0.68rem;
        font-weight: 750;
        letter-spacing: 0.045em;
        text-transform: uppercase;
    }}

    /* Widgets nativos (texto/seleção/botão/checkbox) — cobertura explícita para manter
       contraste consistente sobre as superfícies claras. */
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stNumberInput"] input {{
        background: {d.SURFACE} !important;
        color: {d.TEXT} !important;
        border-color: {d.BORDER} !important;
        border-radius: {d.RADIUS_SM} !important;
    }}
    /* Caixa fechada do selectbox/multiselect. Esta versão do Streamlit NÃO usa mais
       BaseWeb aqui (confirmado no bundle: `Selectbox.*.js`/`Multiselect.*.js` usam
       React Aria + styled-components, sem nenhum atributo `data-baseweb` — a regra
       anterior mirava algo que não existe nesta versão, por isso nunca funcionou). A
       caixa em si é um `<input>` comum dentro do contêiner com testid estável. `:has(> input)`
       alcança somente a camada visual da caixa, sem pintar também o fundo atrás do rótulo,
       e continua independente das classes geradas (essas mudam a cada build). */
    [data-testid="stSelectbox"] div:has(> input),
    [data-testid="stMultiSelect"] div:has(> input) {{
        background-color: {d.SURFACE} !important;
        border-color: {d.BORDER} !important;
        border-radius: {d.RADIUS_SM} !important;
    }}
    [data-testid="stSelectbox"] input,
    [data-testid="stSelectbox"] *,
    [data-testid="stMultiSelect"] input,
    [data-testid="stMultiSelect"] * {{
        color: {d.TEXT} !important;
    }}
    /* Menu suspenso de opções — testid próprio e ESTÁVEL (confirmado no bundle),
       renderizado num portal fora da árvore do widget, por isso o seletor solto no
       topo do documento em vez de aninhado sob `stSelectbox`. Nomes diferentes entre
       selectbox (seleção única) e multiselect (múltipla): `stSelectboxVirtualDropdown`
       vs. `stMultiSelectDropdown`. */
    [data-testid="stSelectboxVirtualDropdown"],
    [data-testid="stMultiSelectDropdown"] {{
        background-color: {d.SURFACE} !important;
        border: 1px solid {d.BORDER} !important;
    }}
    [data-testid="stSelectboxVirtualDropdown"] *,
    [data-testid="stMultiSelectDropdown"] * {{ color: {d.TEXT} !important; }}
    [data-testid="stSelectboxVirtualDropdown"] [aria-selected="true"],
    [data-testid="stMultiSelectDropdown"] [aria-selected="true"] {{
        background-color: {d.ACCENT_SOFT} !important;
    }}
    [data-testid="stButton"] button, [data-testid="stFormSubmitButton"] button {{
        background: {d.SURFACE} !important;
        border-color: {d.BORDER} !important;
        min-height: 2.55rem;
        border-radius: {d.RADIUS_SM};
        font-weight: 700;
        box-shadow: none;
    }}
    /* O rótulo do botão é um elemento próprio dentro dele (o Streamlit define a cor
       lá, não no <button>) — daí a cor precisar descer para os descendentes. */
    [data-testid="stButton"] button, [data-testid="stButton"] button *,
    [data-testid="stFormSubmitButton"] button, [data-testid="stFormSubmitButton"] button * {{
        color: {d.TEXT} !important;
    }}
    /* Botão primário (ex.: a NE selecionada na lista de Consulta de Empenhos) continua
       na cor de acento, com texto branco — é o sinal visual de "selecionado". */
    [data-testid="stButton"] button[kind="primary"],
    [data-testid="stButton"] button[kind="primary"] *,
    [data-testid="stFormSubmitButton"] button[kind="primary"],
    [data-testid="stFormSubmitButton"] button[kind="primary"] * {{
        background: {d.ACCENT} !important;
        color: #FFFFFF !important;
        border-color: {d.ACCENT} !important;
    }}
    [data-testid="stButton"] button[kind="primary"],
    [data-testid="stFormSubmitButton"] button[kind="primary"] {{
        background: linear-gradient(180deg, {d.ACCENT} 0%, {d.ACCENT_STRONG} 100%) !important;
        border-color: {d.ACCENT_STRONG} !important;
        box-shadow: 0 4px 10px rgba(9, 105, 218, 0.16);
    }}
    [data-testid="stCheckbox"] label p, [data-testid="stRadio"] label p {{ color: {d.TEXT}; }}
    /* Segmented control / pills (ex.: seletor "Indicador" em Dotação Orçamentária). O
       testid real (confirmado no bundle, `ButtonGroup.*.js`) é `stButtonGroup` — NÃO
       `stSegmentedControl`, que não existe nesta versão (mesmo componente atende
       `st.segmented_control` e `st.pills`); daí o retângulo sem nenhum texto visível
       no print do usuário, a regra antiga nunca alcançava o elemento certo. O estado
       "selecionado" de cada opção é uma prop interna de styled-components (prefixo
       `$`, nunca vira atributo do HTML) — sem seletor CSS possível para isolar só a
       opção ativa; cobre-se o grupo inteiro de modo uniforme. */
    [data-testid="stButtonGroup"],
    [data-testid="stButtonGroup"] button {{
        background: {d.SURFACE} !important;
        color: {d.TEXT} !important;
        border-color: {d.BORDER} !important;
    }}
    [data-testid="stButtonGroup"] button * {{ color: {d.TEXT} !important; }}
    /* `st.toggle` usa o MESMO testid do checkbox nesta versão (confirmado no bundle,
       `Checkbox.*.js`) — não existe `stToggle` separado; a regra antiga nunca casava. */
    [data-testid="stCheckbox"] p {{ color: {d.TEXT} !important; }}
    /* Demais variantes de botão — só `stButton`/`stFormSubmitButton` estavam cobertos, e
       os outros três ficavam como retângulos escuros sem texto visível no modo claro
       (reportado pelo usuário). `stPopover` é só o gatilho — o painel que ele abre ao
       clicar é `stPopoverBody` (testid próprio, confirmado no bundle; estava faltando
       aqui, por isso o pop-up "+ Cadastrar" continuava escuro mesmo com o botão certo). */
    [data-testid="stDownloadButton"] button,
    [data-testid="stLinkButton"] a,
    [data-testid="stPopover"] button {{
        background: {d.SURFACE} !important;
        color: {d.TEXT} !important;
        border-color: {d.BORDER} !important;
    }}
    [data-testid="stDownloadButton"] button *,
    [data-testid="stPopover"] button * {{ color: {d.TEXT} !important; }}
    /* Mesmo motivo do `stDialog` logo abaixo (varredura de `div` filhos, não só o
       próprio testid): o painel visível pode ser um `<div>` interno sem nome próprio. */
    [data-testid="stPopoverBody"],
    [data-testid="stPopoverBody"] div {{
        background: {d.SURFACE} !important;
        border-color: {d.BORDER} !important;
    }}
    [data-testid="stPopoverBody"] * {{ color: {d.TEXT} !important; }}

    /* Formulário e envio de arquivo (st.form / st.file_uploader): contêineres com fundo
       próprio vindo do tema fixo do Streamlit. */
    [data-testid="stForm"] {{
        background: {d.SURFACE};
        border: 1px solid {d.BORDER};
        border-radius: {d.RADIUS};
    }}
    [data-testid="stProgress"] > div > div > div {{
        background: linear-gradient(90deg, {d.ACCENT} 0%, {d.ACCENT_STRONG} 100%) !important;
    }}
    [data-testid="stMetric"] {{ min-height: 4.25rem; }}
    [data-testid="stMetricValue"] {{ font-size: 1.55rem; }}
    [data-testid="stFileUploader"] section,
    [data-testid="stFileUploaderDropzone"] {{
        background: {d.SURFACE_ALT} !important;
        border-color: {d.BORDER} !important;
        color: {d.TEXT} !important;
    }}
    [data-testid="stFileUploader"] section * {{ color: {d.TEXT} !important; }}

    /* Spinner de carregamento (st.spinner e o `show_spinner=` dos caches) — aparecia como
       uma caixa preta com o texto ilegível no modo claro. */
    [data-testid="stSpinner"] {{ background: transparent !important; color: {d.TEXT_MUTED} !important; }}
    [data-testid="stSpinner"] * {{ color: {d.TEXT_MUTED} !important; }}

    /* Pop-ups modais: `stDialog` (st.dialog — Linha do tempo mensal, edição de cadastro
       etc.) e `stClearCacheDialog`/`stUnsupportedBrowserDialog`/`stVideoRecordedDialog`
       (diálogos internos do PRÓPRIO Streamlit, ex.: "Clear caches" no menu ⋮ — mesmo
       componente por baixo, `nu()` no bundle, mas com um `<div>` de rótulo próprio por
       fora). `stDialog` é só o testid do WRAPPER de posicionamento (React Aria Dialog);
       o cartão branco/escuro visível de verdade é um `<div>` FILHO sem testid próprio
       (confirmado pelo usuário: pintar só o wrapper não bastou — o cartão por cima
       continuava escuro). Por isso a varredura de todos os `div` descendentes aqui,
       mesmo padrão já usado no selectbox por motivo idêntico. */
    [data-testid="stDialog"],
    [data-testid="stDialog"] div,
    [data-testid="stClearCacheDialog"] div,
    [data-testid="stUnsupportedBrowserDialog"] div,
    [data-testid="stVideoRecordedDialog"] div {{
        background: {d.SURFACE} !important;
        border-color: {d.BORDER} !important;
    }}
    [data-testid="stDialog"] *,
    [data-testid="stClearCacheDialog"] *,
    [data-testid="stUnsupportedBrowserDialog"] *,
    [data-testid="stVideoRecordedDialog"] * {{
        color: {d.TEXT} !important;
    }}
    [data-testid="stDialog"] button,
    [data-testid="stClearCacheDialog"] button {{
        background: {d.SURFACE_ALT} !important;
        border: 1px solid {d.BORDER} !important;
    }}

    hr, [data-testid="stDivider"] hr {{ border-color: {d.BORDER}; }}

    /* Quadrado do checkbox/toggle e círculo do radio: o estado marcado/ligado é uma prop
       interna de styled-components (prefixo `$isSelected`, confirmado em `Checkbox.*.js`)
       que nunca chega ao DOM como atributo — não há seletor CSS possível para isolar só
       o estado marcado (a tentativa anterior com `input:checked`/`[aria-checked]` mirava
       uma estrutura que não existe aqui). Cobre-se com um fundo neutro sempre visível nos
       dois estados; o check em si é um `<svg>` renderizado condicionalmente (só existe no
       DOM quando marcado), que já aparece por cima com contraste suficiente. */
    [data-testid="stCheckbox"] svg, [data-testid="stRadio"] svg {{ color: {d.ACCENT}; }}

    /* Link de navegação para outra página (st.page_link). */
    [data-testid="stPageLink"] a, [data-testid="stPageLink"] a * {{ color: {d.ACCENT} !important; }}

    /* Rede de segurança para o que nenhuma regra acima alcançou. `:where()` zera a
       especificidade de propósito: qualquer cor declarada por uma página (ou pelo
       próprio Streamlit) vence esta regra, que só existe para nada ficar sem cor
       definida e acabar caindo no padrão escuro herdado do config.toml. */
    :where([data-testid="stAppViewContainer"]) :where(p, li, label, td, th) {{ color: {d.TEXT}; }}
</style>
"""


def apply_theme() -> None:
    """Aplica a identidade visual clara e fixa em toda a sessão."""

    st.markdown(_theme_css(), unsafe_allow_html=True)


def render_page_header(title: str, subtitle: str | None = None, context: str | None = None) -> None:
    """Exibe cabeçalho consistente, sem alterar dados ou estado da página."""

    if context:
        st.markdown(f'<div class="ufrpe-page-context">{context}</div>', unsafe_allow_html=True)
    st.title(title)
    if subtitle:
        st.markdown(f'<div class="ufrpe-page-subtitle">{subtitle}</div>', unsafe_allow_html=True)


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
                icon, tone = _metric_visual(metric)
                st.markdown(
                    f'<div class="ufrpe-metric-icon" style="--tone:{escape(tone)}">{escape(icon)}</div>',
                    unsafe_allow_html=True,
                )
                st.metric(
                    str(metric["label"]),
                    str(metric["value"]),
                    help=metric.get("help"),
                )
                subtitle = metric.get("subtitle")
                if subtitle:
                    st.caption(str(subtitle))


def _metric_visual(metric: dict[str, object]) -> tuple[str, str]:
    """Ícone e cor semânticos para os cartões compartilhados, sem alterar seus dados."""

    if metric.get("icon") or metric.get("tone"):
        return str(metric.get("icon", "▥")), str(metric.get("tone", design_tokens.ACCENT))
    label = str(metric.get("label", "")).casefold()
    if any(word in label for word in ("alert", "crít", "rejeit", "vencid", "déficit")):
        return "!", design_tokens.NEGATIVE
    if any(word in label for word in ("aviso", "atenção", "empenhad", "pendente", "prazo")):
        return "!", design_tokens.WARNING
    if any(word in label for word in ("disponível", "aceit", "pago", "liquid", "conclu", "execução")):
        return "✓", design_tokens.POSITIVE
    return "▥", design_tokens.ACCENT


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
