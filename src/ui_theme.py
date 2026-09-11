"""Componentes visuais reutilizáveis do UFRPE BudgetLab."""

from __future__ import annotations

import math
import numbers

import pandas as pd
import streamlit as st

from src import design_tokens


def _theme_css() -> str:
    """Monta o CSS global a partir dos tokens ATUAIS de `design_tokens` —
    função (não mais um texto fixo calculado uma única vez): como este
    módulo é carregado uma só vez por processo (`sys.modules`), um texto
    fixo montado no import ficaria travado no tema de quando o servidor
    subiu, ignorando trocas feitas depois pelo alternador de tema (ver
    `render_theme_toggle`). Os nomes abaixo são lidos como atributo do
    módulo (`design_tokens.TEXT`, não `from design_tokens import TEXT`) só
    por isso — mesmo tema do docstring de `design_tokens.py`.
    """
    d = design_tokens
    return f"""
<style>
    :root {{ color-scheme: {"dark" if design_tokens.tema_atual() == "escuro" else "light"}; }}
    [data-testid="stAppViewContainer"] {{
        background: radial-gradient(circle at top left, {d.BG_GRADIENT_EDGE} 0%, {d.BG} 55%);
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
    [data-testid="stMetricValue"] {{ font-weight: 650; letter-spacing: -0.02em; color: {d.TEXT}; }}
    [data-testid="stMetricLabel"] {{ color: {d.TEXT_MUTED}; font-weight: 600; }}
    [data-testid="stDataFrame"] {{ border: 1px solid {d.BORDER}; border-radius: {d.RADIUS}; overflow: hidden; }}
    /* Barra lateral escondida por padrão (pedido explícito) — só uma fresta de 0,5rem na
       borda esquerda pra servir de área de hover; expande pra largura confortável ao
       encostar o mouse nela. min-width/width juntos porque o Streamlit define os dois via
       style inline (ver stSidebar); só max-width não bastava para vencer o width inline. */
    [data-testid="stSidebar"] {{
        background: {d.SIDEBAR_BG};
        border-right: 1px solid {d.BORDER};
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
        background: {d.ACCENT_SOFT};
        color: {d.ACCENT};
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
        border-radius: 16px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    }}
    /* `stTab` é o testid real de cada aba (confirmado no bundle, `index.*.js`) — não
       `button[role="tab"]` aninhado sob `stTabs`, que não corresponde à estrutura desta
       versão. `aria-selected` é atributo de acessibilidade de verdade (diferente das
       props `$isActive` de estilo, essas sim invisíveis ao CSS — ver comentário do
       checkbox acima), por isso funciona aqui para marcar a aba ativa. */
    [data-testid="stTab"] {{ color: {d.TEXT_MUTED}; }}
    [data-testid="stTab"][aria-selected="true"] {{ color: {d.ACCENT}; }}
    [data-testid="stMultiSelectTagsContainer"] {{ flex-wrap: wrap; row-gap: 0.35rem; }}

    * {{ scrollbar-color: {d.ACCENT} transparent; scrollbar-width: auto; }}
    ::-webkit-scrollbar {{ width: 40px; height: 40px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{
        background-color: {d.ACCENT};
        border-radius: 999px;
        border: 10px solid {d.BG};
        background-clip: padding-box;
        min-height: 96px;
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

    /* Widgets nativos (texto/seleção/botão/checkbox) — mesmo motivo do bloco acima:
       precisam de cobertura própria aqui pra acompanhar claro/escuro. */
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea,
    [data-testid="stNumberInput"] input {{
        background: {d.SURFACE} !important;
        color: {d.TEXT} !important;
        border-color: {d.BORDER} !important;
    }}
    /* Caixa fechada do selectbox/multiselect. Esta versão do Streamlit NÃO usa mais
       BaseWeb aqui (confirmado no bundle: `Selectbox.*.js`/`Multiselect.*.js` usam
       React Aria + styled-components, sem nenhum atributo `data-baseweb` — a regra
       anterior mirava algo que não existe nesta versão, por isso nunca funcionou). A
       caixa em si é um `<input>` comum dentro do contêiner com testid estável; cobrir
       o contêiner e todos os seus `div` diretos (várias camadas, sem nome próprio)
       dá conta do fundo sem depender de uma classe gerada (essas mudam a cada build). */
    [data-testid="stSelectbox"],
    [data-testid="stSelectbox"] div,
    [data-testid="stMultiSelect"],
    [data-testid="stMultiSelect"] div {{
        background-color: {d.SURFACE} !important;
        border-color: {d.BORDER} !important;
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
    """Aplica tokens e ajustes visuais estáticos em toda a sessão Streamlit —
    primeiro reatribui a paleta de cor atual (`design_tokens.aplicar_paleta`,
    conforme o tema escolhido no alternador, ver `render_theme_toggle`), só
    depois monta e injeta o CSS: precisa vir nessa ordem porque `_theme_css()`
    lê os tokens já reatribuídos."""

    design_tokens.aplicar_paleta()
    st.markdown(_theme_css(), unsafe_allow_html=True)


def render_theme_toggle() -> None:
    """Botão na barra lateral para alternar entre tema claro e escuro (pedido
    explícito). Rótulo/ícone descrevem o tema PRA ONDE o clique leva (não o
    atual) — padrão usual desse tipo de alternador. Chamar depois de
    `apply_theme()` (mesma ordem de `app.py`), pra já refletir eventual troca
    feita nesta mesma rodada antes do próximo rerun."""

    indo_para_claro = design_tokens.tema_atual() == "escuro"
    rotulo = "☀️ Tema claro" if indo_para_claro else "🌙 Tema escuro"
    if st.sidebar.button(rotulo, key="ufrpe_alternar_tema", use_container_width=True):
        design_tokens.alternar_tema()
        st.rerun()


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
