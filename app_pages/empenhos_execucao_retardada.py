"""Empenhos com Execução Retardada — NEs com saldo alto (empenhado sem liquidar), para
priorizar a baixa/liquidação de empenhos represados.

Esquema aprovado antes da implementação (ver histórico da conversa):
  * Fonte: `src/execucao_anual.py::ler_execucao_anual`, a partir do `Manifesto.atual()` — a
    mesma base já validada usada por Consulta de Empenhos, Contratos Contínuos e Bolsas. Não
    tem manifesto/leitor próprios.
  * Exercício vigente pré-selecionado no filtro "Exercício", usando a MESMA convenção já
    estabelecida em `execucao_orcamentaria.py`/`dotacao_orcamentaria.py`/`painel_acoes.py`:
    `ano_extracao = datetime.fromisoformat(manifesto.data_extracao).year` (ano da data de
    extração do manifesto, não `datetime.now().year`). Só define o valor padrão na primeira
    renderização (`if chave not in st.session_state`) — depois disso o usuário troca livre.
  * Filtro de escopo (busca + 4 rápidos + 12 avançados) — reaproveitado de
    `src/ui_filtros_execucao.py` (extraído de `app_pages/consulta_empenhos.py` no mesmo
    trabalho que criou esta página), aplicado linha a linha ANTES de agregar por NE — mesma
    ordem de Consulta de Empenhos, pelo mesmo motivo (Natureza Detalhada/Subitem podem variar
    dentro da mesma NE).
  * Granularidade: uma linha por NE, via `saldo_por_ne(agregar_por_ne(filtrado))` — reaproveitado
    sem alteração (`saldo = empenhada - liquidada.fillna(0.0)`, já testado em
    `tests/test_execucao_anual.py`). `percentual_saldo` (saldo / empenhada) é calculado só
    aqui, pois não existe em `execucao_anual.py`: NE com `empenhada` nula/zero mostra "—" no
    percentual em vez de ZeroDivisionError/inf — mas a linha continua na tabela (pode passar
    no corte em R$ mesmo sem corte percentual aplicável).
  * Dois cortes configuráveis na tela (não fixos no código): saldo mínimo em R$ e saldo
    mínimo em % do empenhado, cada um com seu próprio `st.toggle` ("Usar") independente —
    passou por duas rodadas de ajuste: a primeira versão combinava os dois sempre com E; a
    segunda trocou por um botão exclusivo (só um corte ativo por vez), que não permitia "os
    dois clicados" (pedido explícito de correção). Versão final: os dois toggles ligam/desligam
    livremente; com os dois ligados, o destaque combina com OU (passa quem atende qualquer um
    dos ativos — "ligar os dois" amplia o destaque, não restringe). Nenhum toggle ligado é um
    estado válido (não hardcoded pra sempre ter pelo menos um) — a tela avisa e não mostra
    tabela, em vez de decidir um corte padrão escondido.
  * Faixa única de destaque (não duas faixas "irrisória"/"relevante" separadas — decisão já
    tomada na proposta aprovada, pelo trade-off de simplicidade): abaixo do corte vira só uma
    linha agregada informativa ("+ N empenhos abaixo do corte, somando R$X"), não uma segunda
    tabela.
  * Detalhe do empenho abre num pop-up (`@st.dialog`, mesmo padrão de
    `contratos_vigencia.py::_abrir_detalhe`), acionado por um botão "Ver" por linha — pedido
    explícito de ajuste: a primeira versão usava seleção de linha em `st.dataframe` com o
    detalhe renderizado abaixo, que não ficou claro como resposta ao clique; o pop-up deixa
    inequívoco que o clique funcionou, sem navegar para aba/página separada.
  * Indicadores gerenciais no topo via `render_metric_grid` (`src/ui_theme.py`), mesmo padrão
    das demais páginas — não HTML customizado.
  * Fora de escopo, por pedido explícito: nenhum cálculo de ritmo/atraso temporal (% liquidado
    vs. % do exercício decorrido).

Não altera `src/execucao_anual.py`, os leitores de Contratos/Bolsas, nem a lógica de saldo já
validada — só lê e reaproveita.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.execucao_anual import agregar_por_ne, detalhar_nota_empenho, ler_execucao_anual, saldo_por_ne
from src.execucao_anual import ne_curta as _ne_curta_execucao
from src.importacao_execucao import Manifesto
from src.ui_filtros_execucao import (
    CAMPOS_AVANCADOS_EXECUCAO,
    CAMPOS_EXECUCAO,
    CAMPOS_RAPIDOS_EXECUCAO,
    apply_filters,
    limpar_filtros,
    render_filtros_avancados,
    render_filtros_rapidos,
)
from src.ui_theme import render_metric_grid, render_page_header

DIRETORIO_DADOS_BRUTOS = Path("data/raw")

#: namespace de `st.session_state` desta página no filtro compartilhado — distinto do de
#: Consulta de Empenhos, para as duas páginas conviverem sem colidir chaves.
_PREFIXO_FILTRO = "empenhos_retardada"

CORTE_RS_PADRAO = 10_000.0
CORTE_PCT_PADRAO = 20.0  # %

COLUNAS_BUSCA = [
    "ne_ccor", "ne_descricao", "ne_favorecido", "natureza_detalhada_label",
    "pi_cod", "ptres", "acao_desc", "fonte_desc", "processo_ne",
]


@st.cache_data(show_spinner="Lendo a base de Execução Anual...")
def _cached_leitura(caminho: str, mtime: float) -> pd.DataFrame:
    """`mtime` só participa da chave de cache — força reler se o arquivo mudar."""

    return ler_execucao_anual(caminho)


def _ne_exibicao(ne_ccor: object, ano: object) -> str:
    """Omite o prefixo do órgão/UG antes do ano — mesmo padrão de exibição de
    `consulta_empenhos.py::_ne_exibicao` ("2023NE000974", não o `ne_ccor` completo)."""

    if pd.isna(ne_ccor) or pd.isna(ano):
        return "—" if pd.isna(ne_ccor) else str(ne_ccor)
    return _ne_curta_execucao(str(ne_ccor))


def _aplicar_busca(por_ne: pd.DataFrame, busca: str) -> pd.DataFrame:
    if not busca:
        return por_ne
    alvo = busca.strip().lower()
    mascara = pd.Series(False, index=por_ne.index)
    for coluna in COLUNAS_BUSCA:
        if coluna in por_ne.columns:
            mascara = mascara | por_ne[coluna].astype("string").str.lower().str.contains(alvo, na=False, regex=False)
    return por_ne[mascara]


def _dataframe_restrito_a_busca(dataframe: pd.DataFrame, busca: str) -> pd.DataFrame:
    """Linhas (nível de execução, não por NE) das NEs cujo agregado bate com a busca livre —
    usado ANTES de calcular as opções dos filtros rápidos/avançados, para elas ficarem
    restritas ao que a busca já reduziu, em vez de sempre oferecerem opções do dataset
    inteiro (mesmo bug relatado e corrigido em `consulta_empenhos.py::_dataframe_restrito_a_busca`).

    Filtra por `ne_ccor` (todas as linhas da NE, inclusive itens de execução), não linha a
    linha — ver docstring de `consulta_empenhos.py::_dataframe_restrito_a_busca` para o motivo
    (linha a linha quebraria `agregar_por_ne` por falta de linha, não por ausência real do
    dado).
    """
    if not busca:
        return dataframe
    alvo = busca.strip().lower()
    mascara = pd.Series(False, index=dataframe.index)
    for coluna in COLUNAS_BUSCA:
        if coluna in dataframe.columns:
            mascara = mascara | dataframe[coluna].astype("string").str.lower().str.contains(alvo, na=False, regex=False)
    nes_que_batem = set(dataframe.loc[mascara, "ne_ccor"])
    return dataframe[dataframe["ne_ccor"].isin(nes_que_batem)]


def _brl(valor: object) -> str:
    """Mesmo padrão de formatação compacta em reais inteiros (sem centavos, ponto como
    separador de milhar) já usado em `contratos_pagamentos.py`/`contratos_continuos.py`."""

    if valor is None or pd.isna(valor):
        return "—"
    negativo = valor < 0
    texto = "R$ " + f"{abs(round(valor)):,.0f}".replace(",", ".")
    return ("−" if negativo else "") + texto


def _pct(valor: object) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    return f"{valor:.1f}%"


def _dash(valor: object) -> str:
    return "—" if pd.isna(valor) else str(valor)


@st.dialog("Detalhe do empenho", width="large")
def _abrir_detalhe(dataframe: pd.DataFrame, linha: pd.Series) -> None:
    """Todas as informações da NE clicada na tabela "Em destaque", num pop-up dentro da própria
    aba (pedido explícito — nem inline role-abaixo, nem aba/página separada). Mesmo conjunto de
    campos do painel de detalhe de `consulta_empenhos.py::_render_detalhe` (dimensões
    constantes por NE, ver `execucao_anual.py::_DIMENSOES_CONSTANTES_POR_NE`), mesmo padrão de
    `@st.dialog` já usado em `contratos_vigencia.py::_abrir_detalhe` — sem reaproveitar as
    classes CSS `.ce-*` daquela página (específicas dela), só com os widgets nativos do
    Streamlit."""

    st.markdown(f"##### {_ne_exibicao(linha['ne_ccor'], linha['ano'])}")
    st.caption(_dash(linha["ne_favorecido"]))
    if pd.notna(linha.get("ne_descricao")):
        st.write(linha["ne_descricao"])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Empenhado", _brl(linha["empenhada"]))
    m2.metric("Liquidado", _brl(linha["liquidada"]))
    m3.metric("Saldo", _brl(linha["saldo"]))
    m4.metric("% Saldo", _pct(linha["percentual_saldo"]))

    st.markdown("**Classificação da despesa**")
    st.caption(
        f"Categoria Econômica: {_dash(linha['categoria_economica_cod'])} — {_dash(linha['categoria_economica_desc'])}  \n"
        f"Grupo de Despesa: {_dash(linha['gnd_cod'])} — {_dash(linha['gnd_desc'])}  \n"
        f"Natureza de Despesa: {_dash(linha['natureza_despesa_cod'])} — {_dash(linha['natureza_despesa_desc'])}  \n"
        f"Natureza Detalhada: {_dash(linha['natureza_detalhada_label'])}  \n"
        f"Subitem: {_dash(linha['subitem_resumo'])}  \n"
        f"Elemento de Despesa: {_dash(linha['elemento_cod'])} — {_dash(linha['elemento_desc'])}"
    )

    st.markdown("**Programação orçamentária**")
    st.caption(
        f"Nº do Processo: {_dash(linha['processo_ne'])}  \n"
        f"Ação de Governo: {_dash(linha['acao_cod'])} — {_dash(linha['acao_desc'])}  \n"
        f"Fonte de Recursos: {_dash(linha['fonte_cod'])} — {_dash(linha['fonte_desc'])}  \n"
        f"Resultado Primário Lei: {_dash(linha['resultado_primario_cod'])} — {_dash(linha['resultado_primario_desc'])}  \n"
        f"Iduso: {_dash(linha['iduso_cod'])} — {_dash(linha['iduso_desc'])}  \n"
        f"PI: {_dash(linha['pi_cod'])} — {_dash(linha['pi_desc'])}  \n"
        f"PTRES: {_dash(linha['ptres'])}"
    )

    st.markdown("**Unidades**")
    st.caption(
        f"UG Executora: {_dash(linha['ug_executora_cod'])} — {_dash(linha['ug_executora_desc'])}  \n"
        f"UG Responsável: {_dash(linha['ug_responsavel_cod'])} — {_dash(linha['ug_responsavel_desc'])}  \n"
        f"UGR - Gestão: {_dash(linha['ugr_cod'])} — {_dash(linha['ugr_desc'])}"
    )

    with st.expander("Linhas de origem (rastreabilidade)"):
        origem = detalhar_nota_empenho(dataframe, linha["ne_ccor"])
        st.dataframe(
            origem[["linha_origem", "tipo_linha", "ano", "empenhada", "liquidada", "paga"]],
            hide_index=True,
            width="stretch",
        )


# ---------------------------------------------------------------------- página
render_page_header(
    "Empenhos com Execução Retardada",
    "Notas de empenho com saldo alto (empenhado ainda não liquidado) — priorização de baixa.",
    "Execução",
)

manifesto = Manifesto.atual()
if manifesto is None:
    st.info(
        "Nenhuma base de Execução Anual foi importada ainda. Rode a importação inicial "
        "(ver docs/base_execucao_anual.md) antes de usar esta página."
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
ano_extracao = datetime.fromisoformat(manifesto.data_extracao).year

# pré-seleciona o exercício vigente no filtro "Exercício" — só na primeira renderização
# (uma flag própria, não a ausência da chave do filtro): depois disso o usuário troca
# livremente e a escolha persiste entre reruns, como qualquer outro filtro — inclusive depois
# de um "Limpar filtros", que devolve Exercício para "Todos" como os demais campos, não para
# o ano vigente de novo (a flag sobrevive a `limpar_filtros`, que só apaga as chaves dos
# próprios campos de filtro, não marcadores auxiliares como este).
_ano_key = f"{_PREFIXO_FILTRO}_ano_{source_key}"
_ano_padrao_aplicado_key = f"{_PREFIXO_FILTRO}_ano_padrao_aplicado_{source_key}"
if not st.session_state.get(_ano_padrao_aplicado_key):
    st.session_state[_ano_key] = [str(ano_extracao)]  # multiselect: valor é sempre uma lista
    st.session_state[_ano_padrao_aplicado_key] = True

acao_limpar_col, *_ = st.columns([1, 4])
with acao_limpar_col:
    if st.button("Limpar filtros", key=f"{_PREFIXO_FILTRO}_limpar_{source_key}"):
        limpar_filtros(CAMPOS_EXECUCAO, _PREFIXO_FILTRO, source_key)
        st.rerun()

busca_col, *_ = st.columns([2, 1, 1, 1, 1])
with busca_col:
    busca = st.text_input(
        "Busca livre",
        key=f"{_PREFIXO_FILTRO}_busca_{source_key}",
        placeholder="NE, descrição, favorecido, natureza, PI, PTRES…",
    )
# a busca livre restringe as OPÇÕES dos filtros rápidos/avançados também, não só o resultado
# final — sem isso, os filtros ofereciam atributos de NEs fora da busca (bug relatado em
# consulta_empenhos.py, mesmo mecanismo de filtro aqui). Por `ne_ccor`, não linha a linha (ver
# docstring de `_dataframe_restrito_a_busca`).
dataframe_buscado = _dataframe_restrito_a_busca(dataframe, busca)
if busca and dataframe_buscado.empty:
    # sai aqui, antes do "Nenhum registro corresponde à combinação de filtros selecionada"
    # mais abaixo (que fala de FILTROS DE ATRIBUTO) — a causa da lista vazia é a busca, não
    # uma seleção de filtro, a mensagem precisa dizer a coisa certa.
    st.warning("Nenhum empenho encontrado com os filtros informados.")
    st.stop()

selections = render_filtros_rapidos(dataframe_buscado, CAMPOS_RAPIDOS_EXECUCAO, CAMPOS_EXECUCAO, _PREFIXO_FILTRO, source_key)
with st.expander("Filtros por atributo (12 campos, cruzados) — combinações sem registro não aparecem nas listas"):
    render_filtros_avancados(dataframe_buscado, CAMPOS_AVANCADOS_EXECUCAO, CAMPOS_EXECUCAO, _PREFIXO_FILTRO, source_key, selections)

filtrado = apply_filters(dataframe_buscado, CAMPOS_EXECUCAO, selections)
if filtrado.empty:
    st.warning("Nenhum registro corresponde à combinação de filtros selecionada.")
    st.stop()

por_ne = saldo_por_ne(agregar_por_ne(filtrado))
# `filtrado` já vem restrito à busca (via `dataframe_buscado`) — chamada mantida como rede de
# segurança (idempotente), não como o filtro principal.
visivel = _aplicar_busca(por_ne, busca)
if visivel.empty:
    st.warning("Nenhum empenho encontrado com os filtros informados.")
    st.stop()

# percentual de saldo — só aqui, não existe em execucao_anual.py. `empenhada` nula/zero vira
# denominador nulo (não ZeroDivisionError/inf); a linha continua em `visivel`, só o percentual
# fica "—" (ver `_pct`).
empenhado_valido = visivel["empenhada"].where(visivel["empenhada"].fillna(0) != 0)
visivel = visivel.assign(percentual_saldo=(visivel["saldo"] / empenhado_valido) * 100)

anos_no_recorte = visivel["ano"].dropna().astype(int).unique()
if ano_extracao in anos_no_recorte:
    st.caption(
        f"⚠ O recorte inclui {ano_extracao}, exercício em andamento na data da extração — "
        "saldo desse exercício ainda pode estar em movimento normal, não é necessariamente atraso."
    )

tem_empenhada = bool(visivel["empenhada"].notna().any())
tem_liquidada = bool(visivel["liquidada"].notna().any())
render_metric_grid(
    [
        {"label": "Empenhos no escopo", "value": str(len(visivel))},
        {
            "label": "Empenhado",
            "value": _brl(visivel["empenhada"].sum(min_count=1)) if tem_empenhada else "Sem registros",
        },
        {
            "label": "Liquidado",
            "value": _brl(visivel["liquidada"].sum(min_count=1)) if tem_liquidada else "Sem registros",
        },
        {"label": "Saldo total (empenhado − liquidado)", "value": _brl(visivel["saldo"].sum())},
    ],
    columns=4,
)

st.markdown("#### Cortes de destaque")
st.caption(
    "Ligue um corte, o outro, ou os dois ao mesmo tempo — com os dois ligados, entra em "
    "destaque quem passa de qualquer um deles."
)

corte_col1, corte_col2 = st.columns(2)
with corte_col1:
    sub_valor, sub_toggle = st.columns([3, 1], vertical_alignment="bottom")
    with sub_valor:
        corte_rs = st.number_input(
            "Saldo mínimo em R$",
            min_value=0.0,
            value=CORTE_RS_PADRAO,
            step=1000.0,
            key=f"{_PREFIXO_FILTRO}_corte_rs_{source_key}",
        )
    with sub_toggle:
        usar_rs = st.toggle(
            "Usar",
            value=True,
            key=f"{_PREFIXO_FILTRO}_usar_rs_{source_key}",
        )
with corte_col2:
    sub_valor, sub_toggle = st.columns([3, 1], vertical_alignment="bottom")
    with sub_valor:
        corte_pct = st.number_input(
            "Saldo mínimo em % do empenhado",
            min_value=0.0,
            max_value=1000.0,
            value=CORTE_PCT_PADRAO,
            step=5.0,
            key=f"{_PREFIXO_FILTRO}_corte_pct_{source_key}",
        )
    with sub_toggle:
        usar_pct = st.toggle(
            "Usar",
            value=False,
            key=f"{_PREFIXO_FILTRO}_usar_pct_{source_key}",
        )

# NE com saldo ou percentual nulo (empenhada nula/zero) nunca entra em destaque — não dá para
# confirmar que o saldo passa do corte sem saber o valor; `.fillna(False)` trata esse "não sei"
# como "não passa", não como erro. Os dois cortes ligados ao mesmo tempo combinam com OU —
# entra em destaque quem passa de qualquer um dos ativos (pedido explícito: "deixar os dois
# clicados" amplia o destaque, não restringe).
passa_rs = (visivel["saldo"] >= corte_rs).fillna(False)
passa_pct = (visivel["percentual_saldo"] >= corte_pct).fillna(False)
partes_ativas = []
descricoes_ativas = []
if usar_rs:
    partes_ativas.append(passa_rs)
    descricoes_ativas.append(f"saldo ≥ {_brl(corte_rs)}")
if usar_pct:
    partes_ativas.append(passa_pct)
    descricoes_ativas.append(f"saldo ≥ {corte_pct:.0f}% do valor empenhado")

if not partes_ativas:
    em_destaque_mascara = pd.Series(False, index=visivel.index)
    descricao_corte = None
else:
    em_destaque_mascara = partes_ativas[0]
    for parte in partes_ativas[1:]:
        em_destaque_mascara = em_destaque_mascara | parte
    descricao_corte = " ou ".join(descricoes_ativas)

em_destaque = visivel[em_destaque_mascara]
abaixo_do_corte = visivel[~em_destaque_mascara]

st.markdown("#### Em destaque")
if descricao_corte is None:
    st.warning("Ligue pelo menos um dos dois cortes acima para ver os empenhos em destaque.")
else:
    st.caption(f"{len(em_destaque)} de {len(visivel)} empenhos com {descricao_corte}.")

if em_destaque.empty:
    if descricao_corte is not None:
        st.info("Nenhum empenho passa do(s) corte(s) ligado(s) acima.")
else:
    ordenado = em_destaque.sort_values("saldo", ascending=False, na_position="last").reset_index(drop=True)
    cabecalho = st.columns([1.3, 2, 1.2, 1.2, 1.2, 0.9, 0.8])
    for coluna, rotulo in zip(cabecalho, ["NE", "Favorecido", "Empenhado", "Liquidado", "Saldo", "% Saldo", ""]):
        coluna.markdown(f"**{rotulo}**" if rotulo else "")
    for posicao, linha in ordenado.iterrows():
        c = st.columns([1.3, 2, 1.2, 1.2, 1.2, 0.9, 0.8])
        c[0].write(_ne_exibicao(linha["ne_ccor"], linha["ano"]))
        c[1].write(_dash(linha["ne_favorecido"]))
        c[2].write(_brl(linha["empenhada"]))
        c[3].write(_brl(linha["liquidada"]))
        c[4].write(_brl(linha["saldo"]))
        c[5].write(_pct(linha["percentual_saldo"]))
        if c[6].button("Ver", key=f"{_PREFIXO_FILTRO}_ver_{source_key}_{posicao}"):
            _abrir_detalhe(filtrado, linha)

if descricao_corte is not None and not abaixo_do_corte.empty:
    soma_abaixo = abaixo_do_corte["saldo"].sum()
    st.caption(f"+ {len(abaixo_do_corte)} empenhos abaixo do corte, somando {_brl(soma_abaixo)} de saldo.")

data_extracao_texto = datetime.fromisoformat(manifesto.data_extracao).strftime("%d/%m/%Y")
st.caption(f"Procedência: extração de {data_extracao_texto} · hash {manifesto.sha256[:8]}")
