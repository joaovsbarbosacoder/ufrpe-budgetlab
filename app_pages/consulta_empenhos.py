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

BUSCA POR ITEM (pedido explícito posterior): a busca livre agora também encontra empenhos
pelo item/produto/rubrica dentro deles (ex.: "papel filme"), não só pelos campos da NE em si
— dado que só existe na base MENSAL (`src/tesouro_execucao_mensal.py`, `docs/
base_execucao_mensal.md`), cobrindo só 2026+, lida de um arquivo fixo em `data/raw/`
(`CAMINHO_EXECUCAO_MENSAL`) sem importação versionada ainda. `_cached_itens_por_ne` resume,
por NE, o texto de todos os itens distintos encontrados (`ne_item_desc`); a busca (linha a
linha em `_dataframe_restrito_a_busca` e no "seguro" `_aplicar_busca` por NE) passa a marcar
como batendo tanto NE cujos campos de sempre contêm o termo quanto NE cujo texto de itens
contém — sem essa base disponível (arquivo ausente ou 2023-2025, fora do período coberto), a
busca continua exatamente como antes. O painel de detalhe (`_render_detalhe`) ganhou uma
seção listando os itens da NE selecionada, quando existem (aberta por padrão — fechada,
passava batido).

SELETOR DE NE (pedido explícito posterior): "Notas de Empenho (NE)" é um `st.multiselect`
próprio desta página (`_opcoes_ne`), fora do mecanismo genérico de filtros (que não suporta
renderização condicional) — só aparece depois que o usuário escolhe ao menos um Exercício nos
filtros rápidos, logo abaixo deles (pedido explícito: estava depois do expander "Filtros por
atributo" antes, passava batido). As opções refletem só os filtros rápidos (Exercício/Ação/
UGR/GND) neste ponto do script, não os 12 avançados (renderizados depois) — o resultado final
(após escolher uma NE) ainda cruza com eles, só a lista de opções da caixa em si não se
restringe por eles.

LINHA DO TEMPO MENSAL (pedido explícito posterior): pop-up (`src.ui_linha_do_tempo.
abrir_linha_do_tempo`, `st.dialog`) com Empenhado/Liquidado/Pago por mês de uma NE — acionado
por um botão dentro do painel de detalhe (`_render_detalhe`), separado da seleção de qual NE
está em detalhe (ver item abaixo). Só aparece para NE com dado na base MENSAL (2026+,
`_cached_linha_do_tempo` → `src.tesouro_execucao_mensal.linha_do_tempo_por_ne`); some
silenciosamente para as demais (2023-2025 ou sem a base mensal disponível). O próprio pop-up
foi extraído para `src/ui_linha_do_tempo.py` (pedido explícito posterior: mesmo formato
reaproveitado por `app_pages/bolsas_auxilios.py`) — o CSS `.ce-tempo-*` que ele usa continua
injetado aqui (`_inject_css`), não no módulo compartilhado (Streamlit não carrega CSS
injetado numa página anterior ao navegar para outra).

CARTÃO CLICÁVEL (pedido explícito posterior): o botão "Ver", antes numa coluna separada de
cada linha, foi removido — cada NE vira um único `st.button` de largura total (rótulo "NE —
objeto"), que É o cartão (`_render_cartoes_lista`/`_rotulo_botao_cartao`). Favorecido e
valores ficam numa linha HTML só informativa abaixo (`_html_linha_lista`), sem clique.
"Selecionado" usa `type="primary"` (cor de acento nativa do Streamlit), sem CSS próprio.

Tentativa anterior (relatada como quebrada pelo usuário, revertida): um `st.button`
transparente sobreposto a um `<div>` HTML via CSS `position: absolute`/`opacity: 0`. Passava
no `AppTest` (que só executa o script Python, não renderiza CSS) mas falhava no navegador
real — troca de abordagem para um botão nativo, visível, sem nenhum truque de posicionamento,
que não tem esse risco.
"""

from __future__ import annotations

import html as html_lib
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.design_tokens import (
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
    ne_curta as _ne_curta_execucao,
    saldo_por_ne,
)
from src.importacao_execucao import DIRETORIO_MANIFESTOS_PADRAO, NOME_PONTEIRO, Manifesto, carregar_atual
from src.tesouro_execucao_mensal import ler_execucao_mensal, linha_do_tempo_por_ne
from src.ui_filtros_execucao import CAMPOS_AVANCADOS_EXECUCAO, CAMPOS_EXECUCAO, CAMPOS_RAPIDOS_EXECUCAO, apply_filters
from src.ui_filtros_execucao import limpar_filtros as _limpar_filtros_compartilhado
from src.ui_filtros_execucao import render_filtros_avancados as _render_filtros_avancados_compartilhado
from src.ui_filtros_execucao import render_filtros_rapidos as _render_filtros_rapidos_compartilhado
from src.ui_linha_do_tempo import abrir_linha_do_tempo
from src.ui_theme import format_brl_compact, render_page_header


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

# Todas as 16 dimensões dos filtros (rápidos + avançados, `FILTER_FIELDS`) — pedido explícito
# pra "Consolidação do escopo" cobrir toda opção de filtro disponível, não só um subconjunto
# escolhido à mão (o que faltava antes: Exercício, Iduso, Resultado Primário Lei, Categoria
# Econômica, Elemento de Despesa, Natureza de Despesa Detalhada, Subitem, PI, PTRES, UG
# Executora e UG Responsável). "Ação de Governo" entra primeiro à mão (não a ordem natural de
# `FILTER_FIELDS`, que começa em "Exercício") só pra preservar a opção padrão de antes desta
# mudança — trocar o padrão silenciosamente já quebrou um teste que dependia dele ter grupos
# suficientes pra paginar. "Favorecido" continua por fora de `FILTER_FIELDS` (não é filtro
# nesta página) mas é útil como consolidação, então fica como extra ao final.
DIMENSOES_CONSOLIDACAO: dict[str, tuple[str, str | None]] = {
    "Ação de Governo": ("acao_cod", "acao_desc"),
}
for _name, _label, _code_column, _description_column in FILTER_FIELDS:
    DIMENSOES_CONSOLIDACAO.setdefault(_label, (_code_column, _description_column))
# Natureza Detalhada e Subitem existem em `agregar_por_ne` só como resumo (uma NE pode ter mais
# de uma classificação dentro dela — ver `_DIMENSOES_CONSTANTES_POR_NE`/`_resumo_classificacao`
# em `src/execucao_anual.py`): não há coluna `*_cod`/`*_desc` na base por NE, só
# `natureza_detalhada_label`/`subitem_resumo`. Sobrescreve as duas entradas herdadas de
# `FILTER_FIELDS` (que apontam pra colunas que só existem na base linha a linha, não na
# agregada) para não gerar KeyError ao consolidar por elas.
DIMENSOES_CONSOLIDACAO["Natureza de Despesa Detalhada"] = ("natureza_detalhada_label", None)
DIMENSOES_CONSOLIDACAO["Subitem"] = ("subitem_resumo", None)
DIMENSOES_CONSOLIDACAO["Favorecido"] = ("ne_favorecido", None)

#: dimensões do quadro "Consolidação Orçamentária do Grupo" (pedido explícito) — só as NEs
#: marcadas na lista, não o recorte de filtros inteiro (isso já é "Consolidação do escopo",
#: acima). Nesta ordem porque foi a ordem citada no pedido; ao contrário de
#: `DIMENSOES_CONSOLIDACAO`, aqui cada dimensão é um bloco recolhível próprio, não um único
#: dropdown "Agrupar por" — o grupo marcado costuma ser pequeno o bastante pra ver as 4 juntas.
DIMENSOES_CONSOLIDACAO_GRUPO = {
    "Elemento de Despesa": ("elemento_cod", "elemento_desc"),
    "Grupo de Despesa": ("gnd_cod", "gnd_desc"),
    "Ação de Governo": ("acao_cod", "acao_desc"),
    "UGR - Gestão": ("ugr_cod", "ugr_desc"),
}

ORDENS = ("Maior saldo de empenho", "Maior valor empenhado", "Menor % liquidado", "Nº da NE")

# Pedido explícito: rolagem em vez de clicar em "Ver mais" repetidamente. A lista fica dentro
# de uma caixa de altura fixa com rolagem própria (`.st-key-ce_list_scroll`, ver `_inject_css`)
# — até QTD_INICIAL_LISTA cartões são renderizados direto, sem precisar de nenhum clique; até
# aí, é só rolar. "Ver mais" continua existindo só como rede de segurança acima desse teto,
# pra nunca renderizar de uma vez as milhares de NEs de um recorte sem filtro nenhum (custo
# real: cada cartão é um `st.button`, um widget de verdade).
QTD_INICIAL_LISTA = 200
QTD_INCREMENTO_LISTA = 200

QTD_INICIAL_CONSOLIDACAO = 8  # grupos mostrados de início na "Consolidação do escopo"
QTD_INCREMENTO_CONSOLIDACAO = 8

COLUNAS_BUSCA = [
    "ne_ccor", "ne_descricao", "ne_favorecido", "natureza_detalhada_label",
    "pi_cod", "ptres", "acao_desc", "fonte_desc", "processo_ne",
]

#: base MENSAL (só 2026+, ver docs/base_execucao_mensal.md) — arquivo fixo em `data/raw/`,
#: sem importação versionada ainda (fora do escopo desta etapa). Usada só para a busca por
#: item; ausência do arquivo não impede o resto da página, só a busca por item.
CAMINHO_EXECUCAO_MENSAL = Path("data/raw") / "BI CPOC - EXEC. DESPESAS - Mensal.xlsx"


def _esc(value: object) -> str:
    return html_lib.escape(str(value))


def _ne_exibicao(ne_ccor: object, ano: object) -> str:
    """Omite o prefixo do órgão/UG antes do ano (`execucao_anual.ne_curta`) — o padrão usual
    de exibição de NE começa no ano (ex.: "2023NE000974"), não no órgão. Só acrescenta o
    tratamento de nulo, específico desta página."""

    if pd.isna(ne_ccor) or pd.isna(ano):
        return "—" if pd.isna(ne_ccor) else str(ne_ccor)
    return _ne_curta_execucao(str(ne_ccor))


def _opcoes_ne(dataframe: pd.DataFrame) -> dict[str, str]:
    """{"rótulo (NE curta — descrição)": ne_ccor} das NEs distintas em `dataframe` — para o
    seletor "Notas de Empenho (NE)" (pedido explícito: só aparece com Exercício selecionado,
    ver corpo da página). `dataframe` já deve vir recortado por Exercício e pelos demais
    filtros; sem isso a lista teria as ~3.700 NEs da base inteira.

    `ne_descricao` só vem preenchida de verdade na linha de tipo "empenho" (nas linhas de item
    de execução é sempre o marcador "NAO SE APLICA", ver docs/base_execucao_anual.md, seção
    3) — resolvida à parte por isso, não pelo primeiro valor que `drop_duplicates` encontrar
    (que podia ser a linha errada e mostrar "NAO SE APLICA" no rótulo)."""

    todas_nes = dataframe[["ne_ccor", "ano"]].dropna(subset=["ne_ccor"]).drop_duplicates(subset=["ne_ccor"])
    descricoes = (
        dataframe.loc[dataframe["tipo_linha"] == "empenho", ["ne_ccor", "ne_descricao"]]
        .drop_duplicates(subset=["ne_ccor"])
        .set_index("ne_ccor")["ne_descricao"]
    )
    mapping: dict[str, str] = {}
    for _, row in todas_nes.sort_values("ne_ccor").iterrows():
        rotulo_codigo = _ne_exibicao(row["ne_ccor"], row["ano"])
        descricao = descricoes.get(row["ne_ccor"])
        rotulo = f"{rotulo_codigo} — {descricao}" if pd.notna(descricao) and str(descricao).strip() else rotulo_codigo
        mapping[rotulo] = row["ne_ccor"]
    return mapping


def _num(value: object) -> str:
    """Dígitos agrupados estilo pt-BR (sem R$, sem decimais) — mesmo padrão de
    `painel_acoes.py`, para tabelas densas em vez do `NumberColumn` do Streamlit
    (que não agrupa milhares)."""

    if pd.isna(value):
        return "—"
    return f"{round(float(value)):,}".replace(",", ".")


@st.cache_data(show_spinner="Lendo a base de Execução Anual...")
def _cached_leitura(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    """`caminho_ponteiro`/`mtime_ponteiro` só participam da chave de cache — força reler
    quando o manifesto atual mudar. O DataFrame devolvido já é a base composta por ano (ver
    `importacao_execucao.carregar_atual`), não só o arquivo do manifesto atual."""

    return carregar_atual()


@st.cache_data(show_spinner="Lendo os itens de empenho (base mensal)...")
def _cached_itens_por_ne(caminho: str, mtime: float) -> pd.Series:
    """NE CCor -> texto de todos os itens distintos daquela NE (`ne_item_desc`, separados por
    " | "), a partir da base MENSAL — usada só para a busca por palavra-chave de item, nunca
    para valor financeiro (essa base não tem manifesto/importação versionada ainda). `mtime`
    só participa da chave de cache."""

    dados = ler_execucao_mensal(caminho)
    reais = dados.loc[dados["tem_item"], ["ne_ccor", "ne_item_desc"]].drop_duplicates()
    return reais.groupby("ne_ccor")["ne_item_desc"].agg(" | ".join)


@st.cache_data(show_spinner="Lendo a linha do tempo mensal...")
def _cached_linha_do_tempo(caminho: str, mtime: float) -> pd.DataFrame:
    """Empenhado/Liquidado/Pago por (NE, mês), a partir da base MENSAL — para o pop-up "Linha
    do tempo mensal" do painel de detalhe. Mesmo arquivo/`mtime` de `_cached_itens_por_ne`
    (lido de novo aqui, não reaproveitado: cada `st.cache_data` guarda seu próprio resultado
    por chamada; ambos ficam em cache após a primeira leitura de cada um nesta sessão)."""

    return linha_do_tempo_por_ne(ler_execucao_mensal(caminho))


def _nes_por_item(itens_por_ne: pd.Series | None, alvo: str) -> set[str]:
    """NEs cujo texto de itens contém `alvo` (já em minúsculas) — conjunto vazio se a base
    mensal não estiver disponível."""

    if itens_por_ne is None or itens_por_ne.empty:
        return set()
    mascara = itens_por_ne.str.lower().str.contains(alvo, na=False, regex=False)
    return set(itens_por_ne[mascara].index)


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
    # "Notas de Empenho (NE)" não é um dos 16 campos do mecanismo compartilhado (é específico
    # desta página, ver corpo dela) — precisa ser limpo à parte, senão "Limpar filtros"
    # deixaria uma seleção de NE travada em sessão.
    st.session_state.pop(f"consulta_empenhos_ne_{source_key}", None)


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
        /* Cartão da lista (pedido explícito: sem botão "Ver" separado, ver
           `_render_cartoes_lista`) — o `st.button` de cada NE É o cartão, um `st.button`
           nativo de verdade (não um botão invisível sobreposto a um `<div>` via CSS: essa
           tentativa anterior funcionava só no teste automatizado, que não renderiza CSS de
           verdade, e falhava no navegador real). "Selecionado" usa `type="primary"`, nativo
           do Streamlit — sem CSS próprio pra marcar isso. `.ce-list-info` é só o credor,
           abaixo do botão, sem clique — pedido explícito: sem valores (Empenhado/Liquidado/
           Pago) na lista.
        */
        .st-key-ce_list_select button {{ justify-content: flex-start; text-align: left; }}
        .ce-list-info {{
            padding: 2px 4px 10px 4px; border-bottom: 1px solid {BORDER_SOFT}; margin-bottom: 4px;
        }}
        .ce-list-fav {{
            font-family: {FONT_BODY}; font-size: {SIZE['code']}; color: {TEXT_FAINT};
        }}
        /* Rolagem (pedido explícito) em vez de "Ver mais" clicado repetidamente: a lista de
           cartões fica numa caixa de altura fixa (~15 linhas) com rolagem própria — abaixo
           de ~15 empenhos visíveis, o conteúdo nem chega a estourar essa altura e a barra de
           rolagem do navegador simplesmente não aparece sozinha (CSS `overflow-y: auto`),
           sem precisar de lógica condicional própria pra isso. */
        .st-key-ce_list_scroll {{
            max-height: 620px; overflow-y: auto; padding-right: 8px; margin-bottom: 4px;
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
        .st-key-ce_list_select [data-testid="stCheckbox"] {{ padding-top: 0; }}
        .ce-tempo-head, .ce-tempo-row {{
            display: grid; grid-template-columns: minmax(60px,1fr) minmax(0,140px) minmax(0,140px) minmax(0,140px);
            gap: 10px; align-items: baseline;
        }}
        .ce-tempo-head {{
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .ce-tempo-row {{ padding: 8px 0; border-bottom: 1px solid {BORDER_SOFT}; }}
        .ce-tempo-mes {{ font-family: {FONT_HEADING}; font-size: {SIZE['body']}; color: {TEXT}; }}
        .ce-tempo-val {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED};
        }}
        .ce-tempo-val-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
        }}
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


def _aplicar_busca(por_ne: pd.DataFrame, busca: str, itens_por_ne: pd.Series | None = None) -> pd.DataFrame:
    if not busca:
        return por_ne
    alvo = busca.strip().lower()
    mascara = pd.Series(False, index=por_ne.index)
    for coluna in COLUNAS_BUSCA:
        mascara = mascara | por_ne[coluna].astype("string").str.lower().str.contains(alvo, na=False, regex=False)
    mascara = mascara | por_ne["ne_ccor"].isin(_nes_por_item(itens_por_ne, alvo))
    return por_ne[mascara]


def _dataframe_restrito_a_busca(dataframe: pd.DataFrame, busca: str, itens_por_ne: pd.Series | None = None) -> pd.DataFrame:
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
    nes_que_batem = set(dataframe.loc[mascara, "ne_ccor"]) | _nes_por_item(itens_por_ne, alvo)
    return dataframe[dataframe["ne_ccor"].isin(nes_que_batem)]


def _rotulo_botao_cartao(linha: pd.Series) -> str:
    """Rótulo do botão de cada cartão (NE + objeto) — rótulo de `st.button` não quebra linha,
    por isso o objeto é truncado."""

    ne = _ne_exibicao(linha["ne_ccor"], linha["ano"])
    objeto = str(linha["ne_descricao"]) if pd.notna(linha["ne_descricao"]) else "(sem descrição)"
    if len(objeto) > 70:
        objeto = objeto[:67] + "..."
    return f"{ne} — {objeto}"


def _html_linha_lista(linha: pd.Series) -> str:
    """Linha só informativa (credor/favorecido), abaixo do botão do cartão — não é mais o alvo
    do clique (ver `_render_cartoes_lista`). Pedido explícito: sem valores (Empenhado/
    Liquidado/Pago) na lista — só número, descrição (no rótulo do botão) e credor aqui."""

    favorecido = _esc(linha["ne_favorecido"]) if pd.notna(linha["ne_favorecido"]) else "(sem favorecido)"
    return f'<div class="ce-list-info"><span class="ce-list-fav">{favorecido}</span></div>'


_LISTA_COLUNAS = (0.06, 0.94)  # marcar (grupo) | cartão (clicável, seleciona a NE pro detalhe)


def _render_cartoes_lista(dados: pd.DataFrame, ne_selecionado: str, source_key: str) -> str | None:
    """Renderiza os cartões visíveis; devolve a NE clicada (se houve clique).

    Pedido explícito: sem botão "Ver" separado — cada NE vira um único `st.button` de largura
    total (o rótulo já mostra NE + objeto), que É o cartão clicável. Tentativa anterior
    (botão invisível sobreposto a um `<div>` HTML via CSS) funcionava no `AppTest` — que não
    renderiza CSS de verdade, só executa o script Python — mas falhava no navegador real
    (relatado pelo usuário): um `st.button` de verdade, sem truque de posicionamento, não tem
    esse risco. `type="primary"` marca visualmente a NE selecionada com a cor de acento do
    tema, nativo do Streamlit — não precisa de CSS próprio pra isso. Favorecido e valores
    ficam numa linha HTML só informativa abaixo do botão (`_html_linha_lista`), sem clique.

    A caixa de marcação é um `st.checkbox` independente por NE — sua leitura não passa por
    aqui: o chamador varre `st.session_state` depois de renderizar, porque cartões já
    revelados em cliques anteriores de "Ver mais" continuam marcáveis mesmo fora desta chamada.
    """

    ne_clicada = None
    with st.container(key="ce_list_select"):
        for _, linha in dados.iterrows():
            col_marca, col_cartao = st.columns(_LISTA_COLUNAS, vertical_alignment="center")
            with col_marca:
                st.checkbox(
                    "Selecionar para o resumo do grupo",
                    key=f"consulta_empenhos_marca_{source_key}_{linha['ne_ccor']}",
                    label_visibility="collapsed",
                )
            with col_cartao:
                selecionado = linha["ne_ccor"] == ne_selecionado
                if st.button(
                    _rotulo_botao_cartao(linha),
                    key=f"consulta_empenhos_ver_{source_key}_{linha['ne_ccor']}",
                    type="primary" if selecionado else "secondary",
                    use_container_width=True,
                ):
                    ne_clicada = linha["ne_ccor"]
                st.markdown(_html_linha_lista(linha), unsafe_allow_html=True)
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


def _html_tabela_agrupada(dataframe: pd.DataFrame, coluna_cod: str, coluna_desc: str | None) -> str:
    """Mesma agregação/HTML de `_render_consolidacao`, mas sem paginação — usada no quadro do
    grupo marcado (`_render_consolidacao_grupo`), onde o grupo costuma ser pequeno o bastante
    (algumas NEs escolhidas à mão) pra não precisar de "Ver mais" dentro de cada dimensão."""

    colunas_grupo = [coluna_cod] if coluna_desc is None else [coluna_cod, coluna_desc]
    agrupado = (
        dataframe.groupby(colunas_grupo, dropna=False)
        .agg(qtd=("ne_ccor", "count"), emp=("empenhada", lambda s: s.sum(min_count=1)),
             liq=("liquidada", lambda s: s.sum(min_count=1)), pag=("paga", lambda s: s.sum(min_count=1)))
        .reset_index()
    )
    if agrupado.empty:
        return ""
    agrupado["saldo"] = agrupado["emp"] - agrupado["liq"].fillna(0.0)
    agrupado = agrupado.sort_values("emp", ascending=False, na_position="last")

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
        for _, row in agrupado.iterrows()
    )
    return f'<div class="ce-cons-head">{_CONSOLIDACAO_CABECALHO}</div>{linhas}'


def _render_consolidacao_grupo(grupo: pd.DataFrame) -> None:
    """Quadro "Consolidação Orçamentária do Grupo" (pedido explícito) — as NEs marcadas na
    lista, quebradas por 4 dimensões orçamentárias ao mesmo tempo (`DIMENSOES_CONSOLIDACAO_GRUPO`),
    um bloco recolhível (`st.expander`) por dimensão, para comparar mais de uma lado a lado
    abrindo os blocos que interessam — ao contrário de "Consolidação do escopo" (dropdown,
    uma dimensão de cada vez, sobre o recorte de filtros inteiro, não o grupo marcado)."""

    for rotulo, (coluna_cod, coluna_desc) in DIMENSOES_CONSOLIDACAO_GRUPO.items():
        with st.expander(rotulo):
            html = _html_tabela_agrupada(grupo, coluna_cod, coluna_desc)
            if html:
                st.markdown(html, unsafe_allow_html=True)
            else:
                st.caption("Nenhum empenho no grupo para consolidar.")


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


def _render_detalhe(
    linha: pd.Series,
    itens_por_ne: pd.Series | None = None,
    linha_do_tempo: pd.DataFrame | None = None,
) -> None:
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

    if linha_do_tempo is not None and linha["ne_ccor"] in set(linha_do_tempo["ne_ccor"]):
        if st.button("📈 Linha do tempo mensal", key=f"ce_tempo_{linha['ne_ccor']}", use_container_width=True):
            tempo_ne = linha_do_tempo[linha_do_tempo["ne_ccor"] == linha["ne_ccor"]]
            ne_exibicao = _ne_exibicao(linha["ne_ccor"], linha["ano"])
            abrir_linha_do_tempo(f"Nota de empenho {ne_exibicao} — base mensal (2026+).", tempo_ne)

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

    if itens_por_ne is not None and linha["ne_ccor"] in itens_por_ne.index:
        # aberto por padrão (pedido explícito) — fechado, passava batido: a NE selecionada ao
        # abrir a página já tem item mapeado na maioria das vezes, e o usuário não percebia.
        with st.expander("Itens do empenho (base mensal, 2026+)", expanded=True):
            for item in itens_por_ne.loc[linha["ne_ccor"]].split(" | "):
                st.markdown(f"- {_esc(item)}")


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

caminho_ponteiro = DIRETORIO_MANIFESTOS_PADRAO / NOME_PONTEIRO
try:
    dataframe = _cached_leitura(str(caminho_ponteiro), caminho_ponteiro.stat().st_mtime)
except Exception as error:
    st.error(f"Não foi possível ler a base de Execução Anual: {error}")
    st.stop()

# Base mensal (2026+) — opcional: sem o arquivo, a busca continua funcionando exatamente como
# antes (só sem encontrar por palavra-chave de item) e o botão "Linha do tempo mensal" some do
# painel de detalhe (ver `_render_detalhe`).
itens_por_ne: pd.Series | None = None
linha_do_tempo: pd.DataFrame | None = None
if CAMINHO_EXECUCAO_MENSAL.exists():
    try:
        itens_por_ne = _cached_itens_por_ne(
            str(CAMINHO_EXECUCAO_MENSAL), CAMINHO_EXECUCAO_MENSAL.stat().st_mtime
        )
        linha_do_tempo = _cached_linha_do_tempo(
            str(CAMINHO_EXECUCAO_MENSAL), CAMINHO_EXECUCAO_MENSAL.stat().st_mtime
        )
    except Exception:
        itens_por_ne = None
        linha_do_tempo = None

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
        placeholder="NE, descrição, favorecido, natureza, PI, PTRES, item (2026+)…",
    )

# a busca livre restringe as OPÇÕES dos filtros rápidos/avançados também, não só o resultado
# final — sem isso, os filtros ofereciam atributos de NEs fora da busca (bug relatado: opção
# aparecia sem nenhuma relação com os empenhos exibidos). Por `ne_ccor` (não linha a linha,
# ver docstring de `_dataframe_restrito_a_busca`), pra não perder linha de item de execução
# da mesma NE e quebrar a agregação por falta de linha, não por ausência real do dado.
dataframe_buscado = _dataframe_restrito_a_busca(dataframe, busca, itens_por_ne)
if busca and dataframe_buscado.empty:
    # sai aqui, antes do "Nenhum registro corresponde à combinação de filtros selecionada"
    # mais abaixo (que fala de FILTROS DE ATRIBUTO) — a causa da lista vazia é a busca, não
    # uma seleção de filtro, a mensagem precisa dizer a coisa certa.
    st.warning("Nenhum empenho encontrado com os filtros informados.")
    st.stop()

selections = _render_filtros_rapidos(dataframe_buscado, source_key)

# "Notas de Empenho (NE)" (pedido explícito): só aparece com Exercício selecionado — listar
# as ~3.700 NEs da base inteira sem esse recorte não seria útil (e ficaria pesado). Logo
# abaixo dos filtros rápidos (pedido explícito posterior: estava depois do expander "Filtros
# por atributo", de 12 campos — passava batido, tinha que rolar a página até lá). As opções
# refletem só os filtros rápidos (Exercício/Ação/UGR/GND) neste ponto, não os 12 avançados
# (renderizados só depois) — imprecisão aceitável: o resultado final, após escolher uma NE,
# ainda cruza com os filtros avançados (aplicados a `filtrado` mais abaixo), então nenhuma
# combinação incoerente chega a aparecer na lista/nos cards, só a lista de opções da própria
# caixa de NE é que não se restringe por eles.
ne_key = f"consulta_empenhos_ne_{source_key}"
ne_selecionadas: list[str] = []
if "ano" in selections:
    filtrado_rapido = _apply_filters(dataframe_buscado, selections)
    mapa_ne = _opcoes_ne(filtrado_rapido)
    persistido = st.session_state.get(ne_key, [])
    valido = [rotulo for rotulo in persistido if rotulo in mapa_ne]
    if valido != persistido:
        st.session_state[ne_key] = valido
    rotulos_ne = st.multiselect(
        "Notas de Empenho (NE)",
        options=list(mapa_ne),
        key=ne_key,
        help="Filtra para uma ou mais NEs específicas do recorte já filtrado pelos filtros rápidos acima.",
    )
    ne_selecionadas = [mapa_ne[rotulo] for rotulo in rotulos_ne]
else:
    # sem Exercício selecionado, não há lista — e qualquer seleção antiga (de quando havia um
    # Exercício escolhido) fica sem efeito e some da sessão, para não travar invisível.
    st.session_state.pop(ne_key, None)
    st.caption("Selecione um Exercício acima para filtrar por Nota de Empenho (NE) específica.")

with st.expander("Filtros por atributo (12 campos, cruzados) — combinações sem registro não aparecem nas listas"):
    _render_filtros_avancados(dataframe_buscado, source_key, selections)

filtrado = _apply_filters(dataframe_buscado, selections)
if ne_selecionadas:
    filtrado = filtrado[filtrado["ne_ccor"].isin(ne_selecionadas)]

if filtrado.empty:
    st.warning("Nenhum registro corresponde à combinação de filtros selecionada.")
    st.stop()

por_ne = _saldo_e_a_pagar(agregar_por_ne(filtrado))
# `filtrado` já vem restrito à busca (via `dataframe_buscado`) — chamada mantida como rede de
# segurança (idempotente), não como o filtro principal.
visivel = _aplicar_busca(por_ne, busca, itens_por_ne)

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

        # "Selecionar todos"/"Desmarcar todos" (pedido explícito) — alterna a marcação de
        # TODOS os empenhos atualmente exibidos (`dados_visiveis`, a lista revelada até agora
        # via "Ver mais", não o recorte de filtros inteiro — "exibidos" é a palavra-chave).
        # Rótulo e efeito dependem do estado atual: se todos já estão marcados, o clique
        # desmarca; caso contrário, marca todos (mesmo se alguns já estavam marcados).
        _prefixo_marca_lista = f"consulta_empenhos_marca_{source_key}_"
        todos_marcados_lista = len(dados_visiveis) > 0 and all(
            st.session_state.get(f"{_prefixo_marca_lista}{ne}", False) for ne in dados_visiveis["ne_ccor"]
        )
        _, col_selecionar_todos = st.columns([3, 1])
        with col_selecionar_todos:
            rotulo_selecionar_todos = "Desmarcar todos" if todos_marcados_lista else "Selecionar todos"
            if st.button(
                rotulo_selecionar_todos, key=f"consulta_empenhos_selecionar_todos_{source_key}",
                use_container_width=True,
            ):
                novo_valor = not todos_marcados_lista
                for ne in dados_visiveis["ne_ccor"]:
                    st.session_state[f"{_prefixo_marca_lista}{ne}"] = novo_valor
                st.rerun()


        with st.container(key="ce_list_scroll"):
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
        _render_detalhe(selecionado, itens_por_ne, linha_do_tempo)

    with st.container(border=True):
        st.subheader("Resumo do grupo selecionado")
        st.caption("Contexto agregado das NEs marcadas na lista, para comparar um subconjunto escolhido.")
        _render_resumo_grupo(visivel, marcados, source_key)

# Largura total (não dentro de `coluna_detalhe`, estreita demais pra 4 tabelas de atributo) —
# mesmas NEs marcadas do "Resumo do grupo selecionado" acima, quebradas por dimensão
# orçamentária (pedido explícito).
with st.container(border=True):
    st.subheader("Consolidação Orçamentária do Grupo")
    st.caption(
        "Elemento de Despesa, Grupo de Despesa, Ação de Governo e UGR das NEs marcadas na "
        "lista — um bloco por dimensão, abra o(s) que interessa(m) comparar."
    )
    if not marcados:
        st.caption("Marque a caixinha ao lado de um ou mais empenhos na lista para ver a consolidação aqui.")
    else:
        _render_consolidacao_grupo(visivel[visivel["ne_ccor"].isin(marcados)])

data_extracao_texto = datetime.fromisoformat(manifesto.data_extracao).strftime("%d/%m/%Y")
st.caption(f"Procedência: extração de {data_extracao_texto} · hash {manifesto.sha256[:8]}")
