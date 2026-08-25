"""Consulta de Empenhos — navegação e busca no nível da Nota de Empenho (NE).

Adaptação do handoff de design (`consulta-empenhos.dc.html` / `painel_execucao.py`) para a
base de Execução Anual já integrada (`src/execucao_anual.py`), lida a partir do manifesto atual
— não do carregador hipotético do handoff (`data_loader_execucao.py`), que assumia uma
planilha achatada com uma linha por NE e colunas `Empenhado`/`Liquidado`/`Pago` diretas. A base
real mistura linhas de empenho e de item de execução (ver `docs/base_execucao_anual.md`, seção
3); `agregar_por_ne()` (`src/execucao_anual.py`) resolve isso somando cada NE preservando
nulo ≠ zero, com a mesma granularidade de todas as outras páginas desta base.

Layout replica o handoff de perto: barra de filtros (busca + 4 rápidos, incluindo Exercício),
filtros avançados recolhíveis, faixa de KPIs em grade com hairlines, duas colunas — lista +
consolidação à esquerda, painel de detalhe da NE selecionada + resumo do grupo marcado à
direita. Os tokens de cor/tipografia são os reais do projeto (`src/design_tokens.py`), não os
do pacote de handoff (que tinha fonte e paleta próprias, divergentes do app já em produção).

Diferenças deliberadas em relação ao handoff:
  * Filtros recortam a base linha a linha, como as demais páginas da Execução Anual — não o
    resumo por NE. Isso inclui Natureza Detalhada/Subitem, que dentro de uma NE podem ter mais
    de um valor (uma NE pode ser lançada em mais de uma classificação); filtrar por um deles
    restringe às linhas daquele valor antes de agregar.
  * A lista usa cartões HTML com revelação progressiva ("Ver mais"), não `st.dataframe`: o
    visual de grade do `st.dataframe` (renderizado em canvas pelo glide-data-grid, fora do
    alcance do CSS do app) lia como planilha, destoando do restante do painel. Mostrar poucos
    cartões por vez (8, crescendo 8 a 8) evita o risco de desempenho que o README do handoff
    sinalizava para um `st.button` por linha — a base real tem 3.700 NEs (o protótipo tinha 12
    registros fictícios), mas só os cartões já revelados existem na página.
  * Cada cartão tem uma caixa de seleção própria, independente do botão "Ver": o botão troca a
    NE exibida no painel de detalhe (seleção única); a caixa marca a NE para o cartão "Resumo
    do grupo selecionado" (seleção múltipla, para comparar/somar um subconjunto escolhido).

O mecanismo de filtro (busca + rápidos + avançados, cascata de opções) foi extraído para
`src/ui_filtros_execucao.py` (pedido explícito) — compartilhado com
`app_pages/empenhos_execucao_retardada.py`, inclusive as 16 tuplas de campo
(`CAMPOS_RAPIDOS_EXECUCAO`/`CAMPOS_AVANCADOS_EXECUCAO`, reexportadas aqui como
`FILTER_FIELDS_RAPIDOS`/`FILTER_FIELDS_AVANCADOS` para não quebrar quem já importava esses
nomes desta página). `_PREFIXO_FILTRO = "consulta_empenhos"` preserva as mesmas chaves de
`st.session_state` de antes da extração.

FILTRO COMBINADO (pedido explícito posterior, aplicado às duas páginas que usam este
mecanismo): cada campo agora é um `st.multiselect`, não mais um dropdown "Todos"/valor único
— reverte a decisão original desta página de usar seleção única "de propósito" (documentada
antes só no código, nunca neste docstring). Ver `src/ui_filtros_execucao.py` para o porquê.
"""

from __future__ import annotations

import html as html_lib
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.design_tokens import (
    ACCENT,
    ACCENT_SOFT,
    ACCENT_STRONG,
    BORDER,
    BORDER_SOFT,
    FONT_BODY,
    FONT_HEADING,
    SIZE,
    SPACE,
    SURFACE,
    TEXT,
    TEXT_FAINT,
    TEXT_MUTED,
    TRACK,
)
from src.execucao_anual import (
    agregar_por_ne,
    detalhar_nota_empenho,
    ler_execucao_anual,
    ne_curta as _ne_curta_execucao,
    saldo_por_ne,
)
from src.importacao_execucao import Manifesto
from src.ui_filtros_execucao import CAMPOS_AVANCADOS_EXECUCAO, CAMPOS_EXECUCAO, CAMPOS_RAPIDOS_EXECUCAO, apply_filters
from src.ui_filtros_execucao import limpar_filtros as _limpar_filtros_compartilhado
from src.ui_filtros_execucao import render_filtros_avancados as _render_filtros_avancados_compartilhado
from src.ui_filtros_execucao import render_filtros_rapidos as _render_filtros_rapidos_compartilhado
from src.ui_theme import format_brl_compact, render_page_header


DIRETORIO_DADOS_BRUTOS = Path("data/raw")

#: namespace de `st.session_state` para o filtro compartilhado (`src/ui_filtros_execucao.py`)
#: — mesmo prefixo usado nas chaves desde antes da extração, para não invalidar estado de
#: sessão já em uso.
_PREFIXO_FILTRO = "consulta_empenhos"

# as 16 dimensões em si (rápidos + avançados) agora vivem em `src/ui_filtros_execucao.py`
# (`CAMPOS_RAPIDOS_EXECUCAO`/`CAMPOS_AVANCADOS_EXECUCAO`) — compartilhadas com
# `app_pages/empenhos_execucao_retardada.py`, não redeclaradas aqui.
FILTER_FIELDS_RAPIDOS = CAMPOS_RAPIDOS_EXECUCAO
FILTER_FIELDS_AVANCADOS = CAMPOS_AVANCADOS_EXECUCAO
FILTER_FIELDS = CAMPOS_EXECUCAO

DIMENSOES_CONSOLIDACAO = {
    "Ação de Governo": ("acao_cod", "acao_desc"),
    "Natureza de Despesa": ("natureza_despesa_cod", "natureza_despesa_desc"),
    "UGR - Gestão": ("ugr_cod", "ugr_desc"),
    "Fonte de Recursos": ("fonte_cod", "fonte_desc"),
    "Grupo de Despesa": ("gnd_cod", "gnd_desc"),
    "Favorecido": ("ne_favorecido", None),
    "Número do Processo": ("processo_ne", None),
}

ORDENS = ("Maior saldo de empenho", "Maior valor empenhado", "Menor % liquidado", "Nº da NE")

QTD_INICIAL_LISTA = 8  # cartões mostrados de início — lista enxuta, não os milhares de NEs do recorte
QTD_INCREMENTO_LISTA = 8  # quantos cartões a mais cada clique em "Ver mais" revela

QTD_INICIAL_CONSOLIDACAO = 8  # grupos mostrados de início na "Consolidação do escopo"
QTD_INCREMENTO_CONSOLIDACAO = 8

COLUNAS_BUSCA = [
    "ne_ccor", "ne_descricao", "ne_favorecido", "natureza_detalhada_label",
    "pi_cod", "ptres", "acao_desc", "fonte_desc", "processo_ne",
]


def _esc(value: object) -> str:
    return html_lib.escape(str(value))


def _ne_exibicao(ne_ccor: object, ano: object) -> str:
    """Omite o prefixo do órgão/UG antes do ano (`execucao_anual.ne_curta`) — o padrão usual
    de exibição de NE começa no ano (ex.: "2023NE000974"), não no órgão. Só acrescenta o
    tratamento de nulo, específico desta página."""

    if pd.isna(ne_ccor) or pd.isna(ano):
        return "—" if pd.isna(ne_ccor) else str(ne_ccor)
    return _ne_curta_execucao(str(ne_ccor))


def _num(value: object) -> str:
    """Dígitos agrupados estilo pt-BR (sem R$, sem decimais) — mesmo padrão de
    `painel_acoes.py`, para tabelas densas em vez do `NumberColumn` do Streamlit
    (que não agrupa milhares)."""

    if pd.isna(value):
        return "—"
    return f"{round(float(value)):,}".replace(",", ".")


@st.cache_data(show_spinner="Lendo a base de Execução Anual...")
def _cached_leitura(caminho: str, mtime: float) -> pd.DataFrame:
    """`mtime` só participa da chave de cache — força reler se o arquivo mudar."""

    return ler_execucao_anual(caminho)


# Mecanismo de filtro (busca + rápidos + avançados) extraído para `src/ui_filtros_execucao.py`
# — compartilhado com `app_pages/empenhos_execucao_retardada.py`. Wrappers finos abaixo só
# fixam `FILTER_FIELDS`/`_PREFIXO_FILTRO` desta página, sem duplicar lógica.
def _apply_filters(dataframe: pd.DataFrame, selections: dict[str, list[object]]) -> pd.DataFrame:
    return apply_filters(dataframe, FILTER_FIELDS, selections)


def _render_filtros_rapidos(dataframe: pd.DataFrame, source_key: str) -> dict[str, list[object]]:
    return _render_filtros_rapidos_compartilhado(
        dataframe, FILTER_FIELDS_RAPIDOS, FILTER_FIELDS, _PREFIXO_FILTRO, source_key
    )


def _render_filtros_avancados(dataframe: pd.DataFrame, source_key: str, selections: dict[str, list[object]]) -> None:
    _render_filtros_avancados_compartilhado(
        dataframe, FILTER_FIELDS_AVANCADOS, FILTER_FIELDS, _PREFIXO_FILTRO, source_key, selections
    )


def _limpar_filtros(source_key: str) -> None:
    _limpar_filtros_compartilhado(FILTER_FIELDS, _PREFIXO_FILTRO, source_key)


def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .ce-kpis {{
            display: grid; grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 1px; background: {BORDER}; border: 1px solid {BORDER};
            margin: 4px 0 18px 0;
        }}
        .ce-kpi {{ background: {SURFACE}; padding: 11px 14px 12px 14px; }}
        .ce-kpi-label {{
            font-family: {FONT_HEADING}; font-size: 10px; letter-spacing: 0.14em;
            text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .ce-kpi-value {{
            font-family: {FONT_HEADING}; font-size: 24px; line-height: 1.1;
            font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
        }}
        .ce-detail-head {{ padding: 15px 18px 14px 18px; background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
        .ce-kicker {{
            font-family: {FONT_HEADING}; font-size: 10px; letter-spacing: 0.16em;
            text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .ce-ne {{
            font-family: {FONT_HEADING}; font-size: 17px; letter-spacing: 0.01em; color: {TEXT};
            line-height: 1.25; overflow-wrap: anywhere;
        }}
        .ce-favorecido {{ font-size: 12px; color: {TEXT_MUTED}; margin-top: 3px; overflow-wrap: anywhere; }}
        .st-key-ce_detail_metrics [data-testid="stMetricValue"] {{
            font-size: 18px; line-height: 1.2; overflow-wrap: anywhere;
        }}
        .st-key-ce_detail_metrics [data-testid="stMetricLabel"] {{ font-size: 10.5px; }}
        .ce-section-title {{
            font-family: {FONT_HEADING}; font-size: 10.5px; letter-spacing: 0.14em;
            text-transform: uppercase; color: {TEXT_MUTED}; padding-bottom: 6px;
            border-bottom: 1px solid {BORDER}; margin-top: 12px;
        }}
        .ce-cons-head, .ce-cons-row {{
            display: grid;
            grid-template-columns: minmax(140px, 2fr) 42px minmax(0, 88px) minmax(0, 88px) minmax(0, 88px) minmax(0, 96px);
            gap: 6px; align-items: baseline;
        }}
        .ce-cons-head {{
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .ce-cons-row {{ padding: 9px 0; border-bottom: 1px solid {BORDER_SOFT}; }}
        .ce-cons-name {{ font-family: {FONT_BODY}; font-size: {SIZE['body']}; line-height: 1.25; color: {TEXT}; }}
        .ce-cons-code {{
            font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: {TRACK['label']}; color: {TEXT_MUTED};
        }}
        .ce-cons-val {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED};
        }}
        .ce-cons-val-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
        }}
        .ce-list-head, .ce-list-row {{
            display: grid;
            grid-template-columns: minmax(220px, 3fr) 110px 110px 120px;
            gap: 10px; align-items: center;
        }}
        .ce-list-head {{
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .ce-list-row {{
            padding: 8px 0 8px 8px; border-bottom: 1px solid {BORDER_SOFT};
            border-left: 3px solid transparent;
        }}
        .ce-list-row.is-selected {{ background: {ACCENT_SOFT}; border-left-color: {ACCENT}; }}
        .ce-list-ne {{
            font-family: {FONT_HEADING}; font-size: {SIZE['body']};
            letter-spacing: {TRACK['tight']}; color: {TEXT};
        }}
        .ce-list-obj {{
            font-family: {FONT_BODY}; font-size: {SIZE['small']}; color: {TEXT_MUTED};
            margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .ce-list-fav {{
            font-family: {FONT_BODY}; font-size: {SIZE['code']}; color: {TEXT_FAINT};
            margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}
        .ce-list-val {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED};
        }}
        .ce-list-val-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
        }}
        .ce-list-pager {{
            text-align: center; margin-bottom: 6px; font-family: {FONT_HEADING};
            font-size: {SIZE['micro']}; letter-spacing: 0.08em; text-transform: uppercase;
            color: {TEXT_MUTED};
        }}
        .st-key-ce_list_mais, .st-key-ce_cons_mais {{ text-align: center; margin-top: 6px; }}
        .st-key-ce_list_mais button, .st-key-ce_cons_mais button {{
            padding: 2px 16px; min-height: 0; font-size: 12px; color: {TEXT_MUTED};
        }}
        .st-key-ce_list_select button {{
            padding: 0px 9px; min-height: 0; height: 26px; font-size: 11px;
            color: {TEXT_MUTED}; border-color: {BORDER};
        }}
        .st-key-ce_list_select button:hover {{ color: {ACCENT}; border-color: {ACCENT}; }}
        .st-key-ce_list_select [data-testid="stCheckbox"] {{ padding-top: 0; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_kpis(kpis: list[dict[str, str]], colunas: int = 6) -> None:
    celulas = "".join(
        f'<div class="ce-kpi"><div class="ce-kpi-label">{k["rotulo"]}</div>'
        f'<div class="ce-kpi-value">{k["valor"]}</div></div>'
        for k in kpis
    )
    st.markdown(
        f'<div class="ce-kpis" style="grid-template-columns: repeat({colunas}, minmax(0, 1fr));">{celulas}</div>',
        unsafe_allow_html=True,
    )


def _saldo_e_a_pagar(por_ne: pd.DataFrame) -> pd.DataFrame:
    """Saldo (empenhado − liquidado, via `execucao_anual.saldo_por_ne`) e a pagar
    (liquidado − pago, mesma regra de nulo-vira-zero, específica desta conta corrente —
    ver docstring de `saldo_por_ne`)."""
    resultado = saldo_por_ne(por_ne)
    liquidada_efetiva = resultado["liquidada"].fillna(0.0)
    paga_efetiva = resultado["paga"].fillna(0.0)
    resultado["a_pagar"] = liquidada_efetiva - paga_efetiva
    return resultado


def _aplicar_busca(por_ne: pd.DataFrame, busca: str) -> pd.DataFrame:
    if not busca:
        return por_ne
    alvo = busca.strip().lower()
    mascara = pd.Series(False, index=por_ne.index)
    for coluna in COLUNAS_BUSCA:
        mascara = mascara | por_ne[coluna].astype("string").str.lower().str.contains(alvo, na=False, regex=False)
    return por_ne[mascara]


def _dataframe_restrito_a_busca(dataframe: pd.DataFrame, busca: str) -> pd.DataFrame:
    """Linhas (nível de execução, não por NE) das NEs cujo agregado bate com a busca livre —
    usado ANTES de calcular as opções dos filtros rápidos/avançados (`_render_filtros_*`),
    para elas ficarem restritas ao que a busca já reduziu, em vez de sempre oferecerem
    opções do dataset inteiro (bug relatado: filtro mostrando atributo que não existe em
    nenhuma NE da busca atual).

    Filtra por `ne_ccor` (todas as linhas da NE, inclusive itens de execução), não linha a
    linha: `ne_descricao`/`ne_favorecido` só vêm preenchidos na linha de tipo "empenho" (ver
    `execucao_anual.py`) — filtrar linha a linha descartaria as linhas de item de execução da
    mesma NE mesmo quando ela bate na busca, quebrando `agregar_por_ne` (que soma linhas de
    todos os tipos) por falta de linha, não por real ausência de dado.
    """
    if not busca:
        return dataframe
    alvo = busca.strip().lower()
    mascara = pd.Series(False, index=dataframe.index)
    for coluna in COLUNAS_BUSCA:
        mascara = mascara | dataframe[coluna].astype("string").str.lower().str.contains(alvo, na=False, regex=False)
    nes_que_batem = set(dataframe.loc[mascara, "ne_ccor"])
    return dataframe[dataframe["ne_ccor"].isin(nes_que_batem)]


_LISTA_CABECALHO = "".join(
    f'<span style="text-align:{alinhamento}">{texto}</span>'
    for texto, alinhamento in (
        ("Nota de empenho", "left"), ("Empenhado", "right"),
        ("Liquidado", "right"), ("Saldo", "right"),
    )
)


def _html_linha_lista(linha: pd.Series, selecionado: bool) -> str:
    objeto = _esc(linha["ne_descricao"]) if pd.notna(linha["ne_descricao"]) else "(sem descrição)"
    favorecido = _esc(linha["ne_favorecido"]) if pd.notna(linha["ne_favorecido"]) else "(sem favorecido)"
    classe = "ce-list-row is-selected" if selecionado else "ce-list-row"
    return (
        f'<div class="{classe}">'
        f'<div><div class="ce-list-ne">{_esc(_ne_exibicao(linha["ne_ccor"], linha["ano"]))}</div>'
        f'<div class="ce-list-obj">{objeto}</div>'
        f'<div class="ce-list-fav">{favorecido}</div></div>'
        f'<span class="ce-list-val">{_num(linha["empenhada"])}</span>'
        f'<span class="ce-list-val">{_num(linha["liquidada"])}</span>'
        f'<span class="ce-list-val-strong">{_num(linha["saldo"])}</span>'
        "</div>"
    )


_LISTA_COLUNAS = (0.05, 0.07, 0.88)  # marcar (grupo) | ver (detalhe) | cartão


def _render_cartoes_lista(dados: pd.DataFrame, ne_selecionado: str, source_key: str) -> str | None:
    """Renderiza os cartões visíveis; devolve a NE clicada em "Ver" (se houve clique).

    A caixa de marcação é um `st.checkbox` independente por NE — sua leitura não passa por
    aqui: o chamador varre `st.session_state` depois de renderizar, porque cartões já
    revelados em cliques anteriores de "Ver mais" continuam marcáveis mesmo fora desta chamada.
    """

    ne_clicada = None
    with st.container(key="ce_list_select"):
        for _, linha in dados.iterrows():
            col_marca, col_botao, col_cartao = st.columns(_LISTA_COLUNAS, vertical_alignment="center")
            with col_marca:
                st.checkbox(
                    "Selecionar para o resumo do grupo",
                    key=f"consulta_empenhos_marca_{source_key}_{linha['ne_ccor']}",
                    label_visibility="collapsed",
                )
            with col_botao:
                if st.button("Ver", key=f"consulta_empenhos_ver_{source_key}_{linha['ne_ccor']}"):
                    ne_clicada = linha["ne_ccor"]
            with col_cartao:
                st.markdown(
                    _html_linha_lista(linha, selecionado=linha["ne_ccor"] == ne_selecionado),
                    unsafe_allow_html=True,
                )
    return ne_clicada


_CONSOLIDACAO_CABECALHO = (
    "".join(
        f'<span style="text-align:{alinhamento}">{texto}</span>'
        for texto, alinhamento in (
            ("Grupo", "left"), ("NEs", "right"), ("Empenhado", "right"),
            ("Liquidado", "right"), ("Pago", "right"), ("Saldo", "right"),
        )
    )
)


def _html_linha_consolidacao(nome: str, codigo: object, tem_codigo: bool, linha: pd.Series) -> str:
    if tem_codigo and pd.notna(codigo) and str(codigo) != nome:
        rotulo = f'<div class="ce-cons-name">{_esc(nome)}</div><div class="ce-cons-code">{_esc(codigo)}</div>'
    else:
        rotulo = f'<div class="ce-cons-name">{_esc(nome)}</div>'
    return (
        '<div class="ce-cons-row">'
        f"<div>{rotulo}</div>"
        f'<span class="ce-cons-val">{int(linha["qtd"])}</span>'
        f'<span class="ce-cons-val">{_num(linha["emp"])}</span>'
        f'<span class="ce-cons-val">{_num(linha["liq"])}</span>'
        f'<span class="ce-cons-val">{_num(linha["pag"])}</span>'
        f'<span class="ce-cons-val-strong">{_num(linha["saldo"])}</span>'
        "</div>"
    )


def _render_consolidacao(visivel: pd.DataFrame, source_key: str) -> None:
    dimensao = st.selectbox(
        "Agrupar por", options=list(DIMENSOES_CONSOLIDACAO), key=f"consulta_empenhos_dimensao_{source_key}"
    )
    coluna_cod, coluna_desc = DIMENSOES_CONSOLIDACAO[dimensao]

    colunas_grupo = [coluna_cod] if coluna_desc is None else [coluna_cod, coluna_desc]
    agrupado = (
        visivel.groupby(colunas_grupo, dropna=False)
        .agg(qtd=("ne_ccor", "count"), emp=("empenhada", lambda s: s.sum(min_count=1)),
             liq=("liquidada", lambda s: s.sum(min_count=1)), pag=("paga", lambda s: s.sum(min_count=1)))
        .reset_index()
    )
    if agrupado.empty:
        st.info("Nenhum empenho no recorte atual para consolidar.")
        return

    agrupado["saldo"] = agrupado["emp"] - agrupado["liq"].fillna(0.0)
    agrupado = agrupado.sort_values("emp", ascending=False, na_position="last")

    # Chave inclui a dimensão: trocar "Agrupar por" recomeça enxuto em vez de herdar quantos
    # grupos a dimensão anterior tinha revelado.
    mostrar_key = f"consulta_empenhos_cons_mostrar_{source_key}_{dimensao}"
    mostrar = st.session_state.get(mostrar_key, QTD_INICIAL_CONSOLIDACAO)
    if not isinstance(mostrar, int) or mostrar < QTD_INICIAL_CONSOLIDACAO:
        mostrar = QTD_INICIAL_CONSOLIDACAO
    mostrar = min(mostrar, len(agrupado))
    st.session_state[mostrar_key] = mostrar

    linhas = "".join(
        _html_linha_consolidacao(
            nome=(
                "(não informado)"
                if pd.isna(row[coluna_cod])
                else str(row[coluna_desc]) if coluna_desc and pd.notna(row[coluna_desc]) else str(row[coluna_cod])
            ),
            codigo=row[coluna_cod],
            tem_codigo=True,
            linha=row,
        )
        for _, row in agrupado.iloc[:mostrar].iterrows()
    )
    st.markdown(
        f'<div class="ce-cons-head">{_CONSOLIDACAO_CABECALHO}</div>{linhas}',
        unsafe_allow_html=True,
    )

    with st.container(key="ce_cons_mais"):
        if mostrar < len(agrupado):
            st.markdown(
                f'<div class="ce-list-pager">Mostrando {mostrar} de {len(agrupado)} grupos</div>',
                unsafe_allow_html=True,
            )
            if st.button("Ver mais", key=f"consulta_empenhos_cons_vermais_{source_key}_{dimensao}"):
                st.session_state[mostrar_key] = min(mostrar + QTD_INCREMENTO_CONSOLIDACAO, len(agrupado))
                st.rerun()
        else:
            st.markdown(
                f'<div class="ce-list-pager">Mostrando todos os {len(agrupado)} grupos</div>',
                unsafe_allow_html=True,
            )


def _render_resumo_grupo(visivel: pd.DataFrame, marcados: set[str], source_key: str) -> None:
    """KPIs agregados só das NEs marcadas na lista — "contexto de execução" do subconjunto
    que o usuário escolheu comparar, não do recorte de filtros inteiro (isso já é a faixa de
    KPIs do topo)."""

    if not marcados:
        st.caption("Marque a caixinha ao lado de um ou mais empenhos na lista para ver o resumo do grupo aqui.")
        return

    grupo = visivel[visivel["ne_ccor"].isin(marcados)]
    tem_dado_grupo = {m: bool(grupo[m].notna().any()) for m in ("empenhada", "liquidada", "paga")}
    totais_grupo: dict[str, float] = {}
    for _medida in ("empenhada", "liquidada", "paga"):
        _soma = grupo[_medida].sum(min_count=1)
        totais_grupo[_medida] = float(_soma) if pd.notna(_soma) else 0.0

    _render_kpis(
        [
            {"rotulo": "Selecionados", "valor": str(len(grupo))},
            {"rotulo": "Empenhado", "valor": format_brl_compact(totais_grupo["empenhada"]) if tem_dado_grupo["empenhada"] else "Sem registros"},
            {"rotulo": "Liquidado", "valor": format_brl_compact(totais_grupo["liquidada"]) if tem_dado_grupo["liquidada"] else "Sem registros"},
            {"rotulo": "Pago", "valor": format_brl_compact(totais_grupo["paga"]) if tem_dado_grupo["paga"] else "Sem registros"},
            {"rotulo": "Saldo de empenho", "valor": format_brl_compact(grupo["saldo"].sum())},
            {"rotulo": "A pagar", "valor": format_brl_compact(grupo["a_pagar"].sum())},
        ],
        colunas=2,
    )

    codigos = ", ".join(
        _ne_exibicao(linha["ne_ccor"], linha["ano"]) for _, linha in grupo.sort_values("ne_ccor").iterrows()
    )
    st.caption(f"NEs no grupo: {codigos}")

    if st.button("Limpar seleção do grupo", key=f"consulta_empenhos_limpar_grupo_{source_key}"):
        for ne in marcados:
            st.session_state.pop(f"consulta_empenhos_marca_{source_key}_{ne}", None)
        st.rerun()


def _render_detalhe(dataframe: pd.DataFrame, linha: pd.Series) -> None:
    st.markdown(
        f"""
        <div class="ce-detail-head">
          <div class="ce-kicker">Detalhamento da nota de empenho</div>
          <div class="ce-ne">{_esc(_ne_exibicao(linha['ne_ccor'], linha['ano']))}</div>
          <div class="ce-favorecido">{_esc(linha['ne_favorecido'])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write(linha["ne_descricao"])

    with st.container(key="ce_detail_metrics"):
        v1, v2 = st.columns(2)
        with v1:
            st.metric("Empenhado", format_brl_compact(linha["empenhada"]))
            st.metric("Pago", format_brl_compact(linha["paga"]) if pd.notna(linha["paga"]) else "Sem registros")
        with v2:
            st.metric("Liquidado", format_brl_compact(linha["liquidada"]) if pd.notna(linha["liquidada"]) else "Sem registros")
            st.metric("Saldo de empenho", format_brl_compact(linha["saldo"]))

    st.markdown('<div class="ce-section-title">Classificação da despesa</div>', unsafe_allow_html=True)
    st.caption(
        f"Categoria: {linha['categoria_economica_cod']} — {linha['categoria_economica_desc']}  \n"
        f"Grupo de Despesa: {linha['gnd_cod']} — {linha['gnd_desc']}  \n"
        f"Natureza de Despesa: {linha['natureza_despesa_cod']} — {linha['natureza_despesa_desc']}  \n"
        f"Natureza Detalhada: {linha['natureza_detalhada_label']}  \n"
        f"Subitem: {linha['subitem_resumo']}  \n"
        f"Elemento de Despesa: {linha['elemento_cod']} — {linha['elemento_desc']}"
    )

    st.markdown('<div class="ce-section-title">Programação orçamentária</div>', unsafe_allow_html=True)
    st.caption(
        f"Nº do Processo: {linha['processo_ne'] if pd.notna(linha['processo_ne']) else 'Não informado'}  \n"
        f"Ação de Governo: {linha['acao_cod']} — {linha['acao_desc']}  \n"
        f"Fonte de Recursos: {linha['fonte_cod']} — {linha['fonte_desc']}  \n"
        f"Resultado Primário Lei: {linha['resultado_primario_cod']} — {linha['resultado_primario_desc']}  \n"
        f"Iduso: {linha['iduso_cod']} — {linha['iduso_desc']}  \n"
        f"PI: {linha['pi_cod']} — {linha['pi_desc']}  \n"
        f"PTRES: {linha['ptres']}"
    )

    st.markdown('<div class="ce-section-title">Unidades</div>', unsafe_allow_html=True)
    st.caption(
        f"UG Executora: {linha['ug_executora_cod']} — {linha['ug_executora_desc']}  \n"
        f"UG Responsável: {linha['ug_responsavel_cod']} — {linha['ug_responsavel_desc']}  \n"
        f"UGR - Gestão: {linha['ugr_cod']} — {linha['ugr_desc']}"
    )

    with st.expander("Linhas de origem (rastreabilidade)"):
        origem = detalhar_nota_empenho(dataframe, linha["ne_ccor"])
        st.dataframe(
            origem[["linha_origem", "tipo_linha", "ano", "empenhada", "liquidada", "paga"]],
            hide_index=True,
            width="stretch",
        )


# ---------------------------------------------------------------------- página
cabecalho, acao_limpar = st.columns([5, 1], vertical_alignment="bottom")
with cabecalho:
    render_page_header(
        "Consulta de Empenhos",
        "Execução Anual da Despesa (BI CPOC), no nível da nota de empenho.",
        "Execução",
    )
_inject_css()

manifesto = Manifesto.atual()
if manifesto is None:
    st.info(
        "Nenhuma base de Execução Anual foi importada ainda. Rode a importação "
        "inicial (ver docs/base_execucao_anual.md) antes de usar esta página."
    )
    st.stop()

caminho_base = DIRETORIO_DADOS_BRUTOS / manifesto.arquivo
if not caminho_base.exists():
    st.error(f"O arquivo da extração atual do manifesto não foi encontrado em '{caminho_base}'.")
    st.stop()

try:
    dataframe = _cached_leitura(str(caminho_base), caminho_base.stat().st_mtime)
except Exception as error:
    st.error(f"Não foi possível ler a base de Execução Anual: {error}")
    st.stop()

source_key = manifesto.sha256[:12]

with acao_limpar:
    if st.button("Limpar filtros", key=f"consulta_empenhos_limpar_{source_key}"):
        _limpar_filtros(source_key)
        st.rerun()

busca_col, *_ = st.columns([2, 1, 1, 1, 1])
with busca_col:
    busca = st.text_input(
        "Busca livre",
        key=f"consulta_empenhos_busca_{source_key}",
        placeholder="NE, descrição, favorecido, natureza, PI, PTRES…",
    )

# a busca livre restringe as OPÇÕES dos filtros rápidos/avançados também, não só o resultado
# final — sem isso, os filtros ofereciam atributos de NEs fora da busca (bug relatado: opção
# aparecia sem nenhuma relação com os empenhos exibidos). Por `ne_ccor` (não linha a linha,
# ver docstring de `_dataframe_restrito_a_busca`), pra não perder linha de item de execução
# da mesma NE e quebrar a agregação por falta de linha, não por ausência real do dado.
dataframe_buscado = _dataframe_restrito_a_busca(dataframe, busca)
if busca and dataframe_buscado.empty:
    # sai aqui, antes do "Nenhum registro corresponde à combinação de filtros selecionada"
    # mais abaixo (que fala de FILTROS DE ATRIBUTO) — a causa da lista vazia é a busca, não
    # uma seleção de filtro, a mensagem precisa dizer a coisa certa.
    st.warning("Nenhum empenho encontrado com os filtros informados.")
    st.stop()

selections = _render_filtros_rapidos(dataframe_buscado, source_key)
with st.expander("Filtros por atributo (12 campos, cruzados) — combinações sem registro não aparecem nas listas"):
    _render_filtros_avancados(dataframe_buscado, source_key, selections)

filtrado = _apply_filters(dataframe_buscado, selections)
if filtrado.empty:
    st.warning("Nenhum registro corresponde à combinação de filtros selecionada.")
    st.stop()

por_ne = _saldo_e_a_pagar(agregar_por_ne(filtrado))
# `filtrado` já vem restrito à busca (via `dataframe_buscado`) — chamada mantida como rede de
# segurança (idempotente), não como o filtro principal.
visivel = _aplicar_busca(por_ne, busca)

if visivel.empty:
    st.warning("Nenhum empenho encontrado com os filtros informados.")
    st.stop()

tem_dado = {m: bool(visivel[m].notna().any()) for m in ("empenhada", "liquidada", "paga")}
totais = {}
for _medida in ("empenhada", "liquidada", "paga"):
    # `min_count=1` some devolve `pd.NA` (não `nan`) quando a coluna tem dtype "Float64"
    # nullable — como as três medidas têm aqui, por virem de `_para_numero()` em
    # execucao_anual.py. `float(pd.NA)` levanta TypeError; `pd.notna()` trata os dois
    # casos (NA e NaN) da mesma forma.
    _soma = visivel[_medida].sum(min_count=1)
    totais[_medida] = float(_soma) if pd.notna(_soma) else 0.0

_render_kpis(
    [
        {"rotulo": "Empenhos", "valor": str(len(visivel))},
        {"rotulo": "Empenhado", "valor": format_brl_compact(totais["empenhada"]) if tem_dado["empenhada"] else "Sem registros"},
        {"rotulo": "Liquidado", "valor": format_brl_compact(totais["liquidada"]) if tem_dado["liquidada"] else "Sem registros"},
        {"rotulo": "Pago", "valor": format_brl_compact(totais["paga"]) if tem_dado["paga"] else "Sem registros"},
        {"rotulo": "Saldo de empenho", "valor": format_brl_compact(visivel["saldo"].sum())},
        {"rotulo": "A pagar", "valor": format_brl_compact(visivel["a_pagar"].sum())},
    ]
)

coluna_principal, coluna_detalhe = st.columns([2, 1], gap="medium")

with coluna_principal:
    with st.container(border=True):
        col_titulo, col_ordem = st.columns([3, 1])
        with col_titulo:
            st.subheader("Empenhos no escopo")
            st.caption(
                f"{len(visivel)} de {len(por_ne)} notas no recorte de filtros · "
                f"{visivel['ne_favorecido'].nunique()} favorecidos distintos"
            )
        with col_ordem:
            ordem = st.selectbox("Ordenar", ORDENS, key=f"consulta_empenhos_ordem_{source_key}", label_visibility="collapsed")

        if ordem == "Maior valor empenhado":
            ordenado = visivel.sort_values("empenhada", ascending=False, na_position="last")
        elif ordem == "Menor % liquidado":
            proporcao = visivel["liquidada"].fillna(0.0) / visivel["empenhada"].replace(0, pd.NA)
            ordenado = visivel.assign(_p=proporcao).sort_values("_p", na_position="last")
        elif ordem == "Nº da NE":
            ordenado = visivel.sort_values("ne_ccor")
        else:
            ordenado = visivel.sort_values("saldo", ascending=False, na_position="last")
        ordenado = ordenado.reset_index(drop=True)

        selecionado_key = f"consulta_empenhos_selecionado_{source_key}"
        if st.session_state.get(selecionado_key) not in set(ordenado["ne_ccor"]):
            st.session_state[selecionado_key] = ordenado.iloc[0]["ne_ccor"]

        mostrar_key = f"consulta_empenhos_mostrar_{source_key}"
        mostrar = st.session_state.get(mostrar_key, QTD_INICIAL_LISTA)
        if not isinstance(mostrar, int) or mostrar < QTD_INICIAL_LISTA:
            mostrar = QTD_INICIAL_LISTA
        mostrar = min(mostrar, len(ordenado))
        st.session_state[mostrar_key] = mostrar

        dados_visiveis = ordenado.iloc[:mostrar]

        _, _, col_cabecalho_lista = st.columns(_LISTA_COLUNAS, vertical_alignment="center")
        with col_cabecalho_lista:
            st.markdown(f'<div class="ce-list-head">{_LISTA_CABECALHO}</div>', unsafe_allow_html=True)

        ne_clicada = _render_cartoes_lista(dados_visiveis, st.session_state[selecionado_key], source_key)
        if ne_clicada is not None:
            st.session_state[selecionado_key] = ne_clicada
            st.rerun()

        with st.container(key="ce_list_mais"):
            if mostrar < len(ordenado):
                st.markdown(
                    f'<div class="ce-list-pager">Mostrando {mostrar} de {len(ordenado)} notas</div>',
                    unsafe_allow_html=True,
                )
                if st.button("Ver mais", key=f"consulta_empenhos_vermais_{source_key}"):
                    st.session_state[mostrar_key] = min(mostrar + QTD_INCREMENTO_LISTA, len(ordenado))
                    st.rerun()
            else:
                st.markdown(
                    f'<div class="ce-list-pager">Mostrando todas as {len(ordenado)} notas</div>',
                    unsafe_allow_html=True,
                )

        selecionado = ordenado.loc[ordenado["ne_ccor"] == st.session_state[selecionado_key]].iloc[0]

    with st.container(border=True):
        st.subheader("Consolidação do escopo")
        st.caption("Subtotais dos empenhos filtrados pela dimensão escolhida.")
        _render_consolidacao(visivel, source_key)

# Marcações de grupo sobrevivem a cliques de "Ver mais": varre `session_state` inteiro em vez
# de só `dados_visiveis`, porque cartões revelados antes continuam com o `st.checkbox` deles
# guardando estado mesmo sem serem redesenhados nesta execução.
_prefixo_marca = f"consulta_empenhos_marca_{source_key}_"
marcados = {
    chave[len(_prefixo_marca):]
    for chave, valor in st.session_state.items()
    if chave.startswith(_prefixo_marca) and valor
} & set(ordenado["ne_ccor"])

with coluna_detalhe:
    with st.container(border=True):
        _render_detalhe(dataframe, selecionado)

    with st.container(border=True):
        st.subheader("Resumo do grupo selecionado")
        st.caption("Contexto agregado das NEs marcadas na lista, para comparar um subconjunto escolhido.")
        _render_resumo_grupo(visivel, marcados, source_key)

data_extracao_texto = datetime.fromisoformat(manifesto.data_extracao).strftime("%d/%m/%Y")
st.caption(f"Procedência: extração de {data_extracao_texto} · hash {manifesto.sha256[:8]}")
