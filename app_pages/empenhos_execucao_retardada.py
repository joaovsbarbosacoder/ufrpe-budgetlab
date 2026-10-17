"""Empenhos com Execução Retardada — NEs com saldo alto (empenhado sem liquidar), para
priorizar a baixa/liquidação de empenhos represados.

FONTE DE DADOS (troca deliberada, 22/09/2026, pedido explícito: "os filtros da seção consulta
de empenho sejam replicados na seção execução retardada"): esta página lia da Execução ANUAL
(`src/execucao_anual.py::ler_execucao_anual`) — mesma base ainda usada por Contratos Contínuos
e Bolsas. Passou a ler da Execução MENSAL (`src/tesouro_execucao_mensal.py`, BI CPOC), via
`Manifesto.atual()`/`carregar_atual()` de `src/importacao_execucao_mensal.py` — mesma troca já
feita em `app_pages/consulta_empenhos.py` em 21/09/2026, pelo mesmo motivo: só a base mensal
tem as dimensões `NE - Informação Complementar`/`Unidade Orçamentária`
(`_CAMPO_NE_INFORMACAO_COMPLEMENTAR`/`_CAMPO_UNIDADE_ORCAMENTARIA`, acrescentadas aos filtros
avançados fora do módulo compartilhado, mesmo padrão de `consulta_empenhos.py` — ver comentário
ao lado de `CAMPOS_AVANCADOS_PAGINA`), sem as quais não havia como replicar os mesmos filtros
daquela página aqui. `agregar_por_ne()` (agora a versão de `src/tesouro_execucao_mensal.py`)
tem o mesmo contrato de saída da versão antiga (mesmos nomes de coluna, inclusive
`subitem_resumo`) — troca de fonte não exigiu reescrever o resto da página, só a
leitura/gating/cache no rodapé do script e os 2 campos novos nos filtros avançados.
`saldo_por_ne`/`detalhar_nota_empenho` continuam vindo de `src/execucao_anual.py` sem
alteração: são genéricos (só dependem de `empenhada`/`liquidada`/`ne_ccor`/`linha_origem`),
confirmado que a base mensal também tem essas colunas. Consequência aceita explicitamente
(mesma de `consulta_empenhos.py`): a Execução Mensal só cobre 2024 em diante — 2023 não
aparece mais nesta página até essa base ganhar uma importação cobrindo aquele exercício.
Reimportar pela página "Atualizar Planilhas", card "Execução Mensal".

Esquema aprovado antes da implementação original (ver histórico da conversa):
  * Exercício vigente pré-selecionado no filtro "Exercício", usando a MESMA convenção já
    estabelecida em `execucao_orcamentaria.py`/`dotacao_orcamentaria.py`/`painel_acoes.py`:
    `ano_extracao = datetime.fromisoformat(manifesto.data_extracao).year` (ano da data de
    extração do manifesto, não `datetime.now().year`). Só define o valor padrão na primeira
    renderização (`if chave not in st.session_state`) — depois disso o usuário troca livre.
  * Filtro de escopo (busca + 4 rápidos + 13+2 avançados) — reaproveitado de
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
    passou por três rodadas de ajuste: a primeira versão combinava os dois sempre com E; a
    segunda trocou por um botão exclusivo (só um corte ativo por vez), que não permitia "os
    dois clicados" (pedido explícito de correção); a terceira fixou OU quando os dois estão
    ligados (passa quem atende qualquer um dos ativos). Versão atual (pedido explícito,
    22/09/2026): com os dois cortes ligados ao mesmo tempo, um `st.segmented_control` ("E"/
    "OU", padrão "OU" — preserva o comportamento já validado) deixa escolher se o destaque
    exige os dois cortes ao mesmo tempo (E, restringe) ou qualquer um deles (OU, amplia). Só
    aparece quando os dois toggles estão ligados — com só um ativo, E e OU dão o mesmo
    resultado, então o seletor seria só ruído. Nenhum toggle ligado continua sendo um estado
    válido (não hardcoded pra sempre ter pelo menos um) — a tela avisa e não mostra tabela, em
    vez de decidir um corte padrão escondido.
  * Faixa única de destaque (não duas faixas "irrisória"/"relevante" separadas — decisão já
    tomada na proposta aprovada, pelo trade-off de simplicidade): abaixo do corte vira só uma
    linha agregada informativa ("+ N empenhos abaixo do corte, somando R$X"), não uma segunda
    tabela.
  * Detalhe do empenho abre por um botão "Ver" por linha — pedido explícito de ajuste: a
    primeira versão usava seleção de linha em `st.dataframe` com o detalhe renderizado abaixo,
    que não ficou claro como resposta ao clique. Era um pop-up (`@st.dialog`); desde 17/10/2026
    é um painel lateral do componente da página (ver LAYOUT abaixo), com o mesmo conteúdo.
  * Visualização "Em destaque" (padrão) / "Todos no escopo" (pedido explícito, 28/09/2026: a
    página não mostrava todas as NEs do escopo, só as acima do corte): "Todos" lista todas as
    NEs de `visivel`, com coluna "Corte" (✓ passa / vazio não passa / "—" nenhum corte ligado).
    Lista paginada em `TAMANHO_PAGINA` linhas (o escopo chega a milhares de NEs). Relatório em
    PDF e Excel (`src/relatorio_empenhos_retardada.py`) com a lista exibida — a visualização
    escolhida, todas as páginas — mais procedência, cortes e filtros aplicados.
  * Indicadores gerenciais no topo — eram `render_metric_grid` (`src/ui_theme.py`); desde
    17/10/2026 são o cartão de resumo do componente da página (ver LAYOUT abaixo).
  * Fora de escopo, por pedido explícito: nenhum cálculo de ritmo/atraso temporal (% liquidado
    vs. % do exercício decorrido).

LAYOUT (17/10/2026, pedido explícito: "o layout continua totalmente diferente" do mockup aprovado,
opção "a página inteira, filtros incluídos"): abaixo do cabeçalho, a página é um único componente
Streamlit `components.v2` (`src/ui_empenhos_retardada_componente.py`, HTML/CSS/JS em
`src/assets/empenhos_retardada/`) com filtros, resumo, cortes, tabela ordenável pelo cabeçalho,
agrupamento e painel lateral de detalhe. Toda decisão sobre O QUE aparece (cascata dos filtros,
cortes, lista, paginação, detalhe) mora em `src/empenhos_retardada_tela.py`, sem Streamlit e
testada em `tests/test_empenhos_retardada_tela.py`; esta página só guarda o estado da tela em
`st.session_state`, aplica as ações que o componente devolve e oferece os downloads (botões
nativos — o componente não gera arquivo). Os filtros desta página deixaram de usar os widgets de
`src/ui_filtros_execucao.py` (Consulta de Empenhos continua usando), mas a regra é a mesma
(`option_mapping`/`apply_filters` reaproveitados).

Não altera `src/execucao_anual.py`, `src/tesouro_execucao_mensal.py`, os leitores de
Contratos/Bolsas, nem a lógica de saldo já validada — só lê e reaproveita.
"""

from __future__ import annotations

from datetime import datetime
import gc

import streamlit as st

from src.empenhos_retardada_tela import (
    OPCOES_AGRUPAMENTO,
    ORDENACAO_PADRAO,
    SENTIDO_ASC,
    VISAO_TODOS,
    aplicar_acao,
    estado_inicial,
    montar_tela,
)
from src.importacao_execucao_mensal import DIRETORIO_MANIFESTOS_PADRAO, NOME_PONTEIRO, Manifesto, carregar_atual
from src.relatorio_empenhos_retardada import ContextoRelatorio, gerar_pdf, gerar_xlsx
from src.ui_empenhos_retardada_componente import renderizar
from src.ui_filtros_execucao import CAMPOS_AVANCADOS_EXECUCAO, CAMPOS_RAPIDOS_EXECUCAO, CampoFiltro
from src.ui_theme import render_page_header

#: namespace de `st.session_state` desta página — distinto do de Consulta de Empenhos.
_PREFIXO_FILTRO = "empenhos_retardada"

# Pedido explícito (22/09/2026): paridade de filtros com `app_pages/consulta_empenhos.py`,
# que desde 21/09/2026 lê da Execução MENSAL (ver docstring do módulo) e acrescenta 2 dimensões
# avançadas que só existem naquela base (`ne_informacao_complementar`,
# `unidade_orcamentaria_cod`/`_desc`). Consequência aceita (mesma da Consulta de Empenhos): a
# Execução Mensal só cobre 2024 em diante — 2023 deixa de aparecer nesta página.
_CAMPO_NE_INFORMACAO_COMPLEMENTAR: CampoFiltro = (
    "ne_informacao_complementar", "NE - Informação Complementar", "ne_informacao_complementar", None,
)
_CAMPO_UNIDADE_ORCAMENTARIA: CampoFiltro = (
    "unidade_orcamentaria", "Unidade Orçamentária", "unidade_orcamentaria_cod", "unidade_orcamentaria_desc",
)
CAMPOS_AVANCADOS_PAGINA = CAMPOS_AVANCADOS_EXECUCAO + (_CAMPO_NE_INFORMACAO_COMPLEMENTAR, _CAMPO_UNIDADE_ORCAMENTARIA)
CAMPOS_PAGINA = CAMPOS_RAPIDOS_EXECUCAO + CAMPOS_AVANCADOS_PAGINA


@st.cache_data(show_spinner="Lendo a base de Execução Mensal...")
def _cached_leitura(caminho_ponteiro: str, sha_manifesto: str):
    """`caminho_ponteiro`/`sha_manifesto` só participam da chave de cache — força reler
    quando a extração atual mudar (mesmo padrão de `consulta_empenhos.py::_cached_leitura`). O
    DataFrame devolvido já é a base composta por ano (ver
    `importacao_execucao_mensal.carregar_atual`), não só o arquivo do manifesto atual."""

    return carregar_atual()


def chave_estado(source_key: str) -> str:
    return f"{_PREFIXO_FILTRO}_estado_{source_key}"


def chave_componente(source_key: str) -> str:
    return f"{_PREFIXO_FILTRO}_tela_{source_key}"


def _ao_agir(source_key: str) -> None:
    """Roda antes da reexecução, a cada ação no componente: aplica a ação ao estado da tela."""

    resultado = st.session_state.get(chave_componente(source_key)) or {}
    acao = resultado.get("acao") if hasattr(resultado, "get") else None
    estado = st.session_state.get(chave_estado(source_key))
    if estado is None or acao is None:
        return
    st.session_state[chave_estado(source_key)] = aplicar_acao(estado, acao, [c[0] for c in CAMPOS_PAGINA])


def _filtros_selecionados(estado: dict) -> list[tuple[str, list[str]]]:
    """(rótulo do filtro, rótulos selecionados) de cada campo com seleção — cabeçalho do relatório."""

    return [(rotulo, list(estado["filtros"][nome])) for nome, rotulo, _c, _d in CAMPOS_PAGINA if estado["filtros"].get(nome)]


# ---------------------------------------------------------------------- página
# Memória (07/10/2026): a cada interação o `st.cache_data` devolve CÓPIAS das bases (DataFrames
# inteiros), que ficam presas em referências circulares; o coletor do Python dispara pela quantidade de
# objetos, não pelo tamanho, e a sessão subia ~0,3 GB por interação (1,4 → 7,9 GB em 20). Coleta no
# início (lixo da interação anterior, em qualquer caminho — inclusive os `st.stop()`) e no fim. Custo
# ~0,1 s por coleta; nenhum dado é alterado (mesma correção da Consulta de Empenhos).
gc.collect()

render_page_header(
    "Empenhos com Execução Retardada",
    "Notas de empenho com saldo alto (empenhado ainda não liquidado) — priorização de baixa.",
    "Execução",
)

manifesto = Manifesto.atual()
if manifesto is None:
    st.info(
        "Nenhuma base de Execução Mensal foi importada ainda. Envie a extração pela página "
        '"Atualizar Planilhas", card "Execução Mensal", antes de usar esta página.'
    )
    st.stop()

caminho_ponteiro = DIRETORIO_MANIFESTOS_PADRAO / NOME_PONTEIRO
try:
    dataframe = _cached_leitura(str(caminho_ponteiro), manifesto.sha256)
except Exception as error:
    st.error(f"Não foi possível ler a base de Execução Mensal: {error}")
    st.stop()

source_key = manifesto.sha256[:12]
ano_extracao = datetime.fromisoformat(manifesto.data_extracao).year
data_extracao_texto = datetime.fromisoformat(manifesto.data_extracao).strftime("%d/%m/%Y")

# Estado da tela: criado uma vez por extração, com o exercício vigente pré-selecionado (ver
# docstring); depois disso só muda pelas ações do usuário (`_ao_agir`).
st.session_state.setdefault(chave_estado(source_key), estado_inicial(ano_extracao))
dados, estado, lista = montar_tela(
    dataframe,
    st.session_state[chave_estado(source_key)],
    campos_rapidos=CAMPOS_RAPIDOS_EXECUCAO,
    campos_avancados=CAMPOS_AVANCADOS_PAGINA,
    ano_extracao=ano_extracao,
)
st.session_state[chave_estado(source_key)] = estado

renderizar(dados, key=chave_componente(source_key), ao_agir=lambda: _ao_agir(source_key))

# Relatório = a lista exibida (visão escolhida, todas as páginas, mesma ordem e agrupamento).
if lista is not None:
    todos = estado["visao"] == VISAO_TODOS
    ordem_padrao = estado["ordem"] == ORDENACAO_PADRAO and estado["sentido"] != SENTIDO_ASC
    contexto_relatorio = ContextoRelatorio(
        visualizacao=estado["visao"],
        descricao_corte=dados.get("descricao_corte"),
        data_extracao=data_extracao_texto,
        hash_manifesto=manifesto.sha256[:8],
        data_emissao=datetime.now().strftime("%d/%m/%Y %H:%M"),
        busca=(estado.get("busca") or "").strip(),
        filtros=_filtros_selecionados(estado),
        ordenacao="" if ordem_padrao else f"{estado['ordem']} ({'menor primeiro' if estado['sentido'] == SENTIDO_ASC else 'maior primeiro'})",
        agrupamento=estado["grupo"] if OPCOES_AGRUPAMENTO.get(estado["grupo"]) else "",
    )
    nome_arquivo = f"empenhos_execucao_retardada_{'todos' if todos else 'destaque'}_{manifesto.data_extracao[:10]}"
    with st.container(key="er_relatorio", horizontal=True, vertical_alignment="center"):
        st.caption(f"Relatório: {len(lista)} empenhos — mesma lista exibida acima ({estado['visao'].lower()}), todas as páginas.")
        st.download_button(
            "Baixar PDF",
            data=lambda: gerar_pdf(lista, contexto_relatorio),
            file_name=f"{nome_arquivo}.pdf",
            mime="application/pdf",
            type="primary",
            on_click="ignore",
            key=f"{_PREFIXO_FILTRO}_download_pdf_{source_key}",
        )
        st.download_button(
            "Baixar Excel",
            data=lambda: gerar_xlsx(lista, contexto_relatorio),
            file_name=f"{nome_arquivo}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            on_click="ignore",
            key=f"{_PREFIXO_FILTRO}_download_xlsx_{source_key}",
        )

st.caption(f"Procedência: extração de {data_extracao_texto} · hash {manifesto.sha256[:8]}")

gc.collect()  # ver o comentário no início da página
