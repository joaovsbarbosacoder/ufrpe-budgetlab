"""Bolsas e Auxílios — necessidade de empenho e saldo, cruzado com a Execução Mensal.

CADASTRO NATIVO, MULTI-EXERCÍCIO (pedido explícito): esta página não lê mais a planilha de
Bolsas e Auxílios — os programas vivem em `src/bolsas_auxilios_cadastro.py`
(`data/bolsas_auxilios/<ano>/<id>.json`, um arquivo por programa, agrupado por exercício). O
exercício 2026 foi migrado uma única vez a partir da planilha então em uso
(`bolsas_auxilios_cadastro.migrar_de_planilha`); dali em diante toda edição, programa novo ou
remoção grava direto no cadastro nativo, sem depender de reimportar Excel. Um seletor de
exercício no topo troca qual ano está em tela; "Duplicar cadastro" copia a identidade/
classificação dos programas do exercício atual para o próximo (execução em branco — o vínculo
com a Execução Mensal se refaz quando o usuário digitar o novo número de empenho), suportando
gerar 2028, 2029... a partir de qualquer exercício mais recente, não só 2026→2027. Exercícios
anteriores continuam navegáveis como histórico (nunca substituídos). `com_saldo_execucao` já é
multi-ano por natureza (`ne_curta` embute o ano, "2027NE000123" nunca colide com "2026NE..."),
então nenhuma mudança foi necessária ali.

LINHA DO TEMPO MENSAL NO RESUMO CONSOLIDADO (pedido explícito): cada bolsa listada em
"Resumo Consolidado" é clicável quando sua NE (`ne_curta`) tem dado na base MENSAL (2024+,
`_cached_linha_do_tempo` → `src.tesouro_execucao_mensal.linha_do_tempo_por_ne`) — abre o
mesmo pop-up "Linha do tempo mensal" de `app_pages/consulta_empenhos.py`
(`src/ui_linha_do_tempo.py`, compartilhado: "mesmo formato implementado na consulta de
empenhos", pedido explícito). Bolsa sem NE ou sem dado mensal aparece como texto simples, sem
botão. Isso forçou trocar o cartão de "Resumo Consolidado" de uma única tabela HTML
(`st.markdown`) para `st.container(border=True)` com um `st.button` de verdade por linha — ver
`_render_resumo_consolidado` — porque HTML puro não dispara evento Python, então não dá pra
ter um botão clicável dentro de um bloco de HTML injetado de uma vez só.

Adaptação do handoff de design (`painel_bolsas.py`, versão "cartão com rótulo pequeno acima
de cada campo") para os leitores e a regra de saldo já aprovados e testados neste projeto
(`src/bolsas_auxilios.py`, `src/necessidade_empenho.py`,
`src/execucao_ne_utils.py::saldo_por_ne`) — não os `data_loader_bolsas.py`/`design_tokens.py`
sugeridos no pacote de handoff.

Cada programa é um cartão (`st.expander`, minimizado por padrão — um cadastro para consultar
por cima e abrir só quando precisar editar) com todos os campos editáveis inline — sem
rolagem horizontal, os campos quebram em linhas dentro do próprio cartão. Rótulo pequeno
(`.bls-label`, maiúsculo, discreto) acima de cada campo — nem rótulo nativo grande do
Streamlit, nem campo sem rótulo nenhum: editável não é sinônimo de caixa grande, mas também
não fica sem indicação do que é.

`_aplicar_edicoes_da_sessao` sobrepõe, no DataFrame usado pelos quadros acima da lista, os
valores já editados em cada cartão (lidos de `st.session_state`, sem redesenhar widgets) e
recalcula `valor_mensal`/`valor_anual`/`meses_a_empenhar`/`valor_a_empenhar` a partir deles.
Uma divergência financeira explicitamente preservada da migração prevalece sobre a fórmula
de quantidade × valor unitário até um desses dois campos ser editado —
sem isso, editar um campo só mudava o que aparecia dentro do próprio cartão, nunca nos KPIs,
no Resumo Consolidado nem na Cobertura Orçamentária por PTRES (bug relatado explicitamente:
"Alterei uma informação no cadastro de bolsa e a alteração não foi refletida nos quadros
superiores"). Roda antes de `com_saldo_execucao`, para uma edição no campo NE também
atualizar `saldo_execucao`/`valor_empenhado_execucao` daquela linha, não só os campos que a
planilha já trazia prontos.

Antes da lista, um card único "Resumo Consolidado — por Bolsa" lista, uma linha por bolsa (não
um total agregado), o valor mensal, o valor empenhado, o saldo (Execução Mensal) e a
necessidade de empenho até o fim do exercício de cada programa — esta última É a métrica de
calendário
(`valor_mensal × meses restantes até dezembro`) que a "Diferença deliberada" abaixo explica
por que NÃO virou a fórmula de "Empenhar" de cada cartão: aqui ela tem um propósito diferente
(projeção por bolsa até dezembro), não substitui a fórmula validada por cartão (que mede
atraso já ocorrido, não projeção futura).

Depois dele, a seção "Cobertura Orçamentária por PTRES" cruza a Dotação Atualizada
disponível (base de Dotação Anual, `src/importacao_dotacao.py`) contra a despesa anual
estimada das bolsas (`valor_anual`), usando o PTRES como referencial comum — ele existe tanto
na Dotação Anual quanto no cadastro de cada bolsa/programa. Um cartão por Ação de Governo,
com uma subdivisão por Plano Orçamentário/PTRES dentro de cada um — mesmo padrão visual de
`app_pages/painel_acoes.py` ("fique parecido com o card da dotação", pedido explícito), não
uma tabela achatada só de PTRES (primeira versão desta seção) nem os gráficos que vieram
antes dela (donut de situação + ranking de necessidade de reforço, rejeitados explicitamente
— "Não gostei do que foi feito").

Diferenças deliberadas em relação ao handoff:
  * "Empenhar"/"Meses de saldo" não vêm de `valor_mensal × "meses restantes até dezembro"`
    (métrica prospectiva de calendário nunca validada neste projeto) — vêm de
    `meses_empenhados − meses_liquidados` (`src/necessidade_empenho.py`, fórmula da coluna
    "MESES DE SALDO" da planilha, validada linha a linha contra a origem). Como o cartão do
    handoff não tinha campos para Meses Empenhados/Liquidados, acrescentei uma linha extra
    para os dois, editáveis como o resto.
  * Para processos cuja NE já foi encontrada na Execução Mensal, `meses_empenhados`/
    `meses_liquidados` deixam de vir da planilha e passam a vir da própria Execução Mensal
    (`com_saldo_execucao`, campos `meses_empenhados_execucao`/`meses_liquidados_execucao`) —
    pedido explícito do usuário para não depender de atualizar a planilha de Bolsas só para
    refletir um novo saldo/liquidado. Os dois campos do cartão viram exibição (rótulo
    "(Execução Mensal)"), não mais editáveis, nesse caso. Sem NE encontrada, continuam
    editáveis como sempre, seedados pela planilha (fallback inalterado; mesmo critério de
    `contratos_continuos.py`).
  * `saldo_execucao` e `valor_empenhado_execucao` (autoritativos, vindos da Execução Mensal)
    não existiam no handoff (foi desenhado antes dessa integração). Pedido explícito
    ("faça com que os dados acompanhem a Execução Mensal"): quando a NE já foi encontrada lá,
    "Saldo (R$)" e "Empenhado (R$)" do cartão passam a EXIBIR o valor da Execução Mensal
    diretamente (rótulo "(Execução Mensal)", não editável) — mesmo critério já usado para
    Meses Empenhados/Liquidados (ver bullet acima), em vez do valor antigo de mostrar os dois
    lado a lado com uma tag "Diverge"/"Bate" quando discordavam. Com o cartão passando a
    exibir sempre o número autoritativo, não sobra o que divergir dali; a tag de status virou
    "Via Execução Mensal"/"Sem Execução" (se nenhuma NE foi encontrada lá, os campos
    continuam editáveis a partir da planilha, fallback inalterado). O "Valor Empenhado" do
    Resumo Consolidado usa `valor_empenhado_execucao`, com `valor_empenhado_tg` (planilha)
    como reserva só para NE sem correspondência na Execução — mesmo padrão de fallback do
    saldo, e mesmo critério que o cartão agora segue.
  * Cada programa é um `st.expander` (minimizado por padrão), não um `st.container(border=True)`
    sempre aberto — o chrome de borda/raio vem de graça do CSS global do app
    (`src/ui_theme.py::_THEME_CSS`, que já estiliza `[data-testid="stExpander"]`), então não
    precisa de CSS próprio escopado como antes.
  * O card "Resumo Consolidado" NÃO é um `st.dataframe` (cara de planilha) — é HTML injetado
    com o mesmo padrão de `app_pages/painel_acoes.py` (`.po-*`: cartão com cabeçalho/kicker/
    métrica em destaque + grade CSS `.po-row`/`.po-head`/`.po-foot`), reaproveitado aqui com
    prefixo próprio `.bls-resumo-*` (classes de nome global — como não há um `st.container`
    envolvendo o card, não precisa nem pode ser escopado por `st-key-...`; os nomes já são
    específicos o bastante para não colidir com `.po-*`/`.bls-*` de outras páginas). Lista uma
    linha por bolsa (não um total único) e usa `valor_mensal × meses ainda devidos no ano`
    (`meses_no_ano − meses já empenhados, nunca calendário puro — ver
    `_render_resumo_consolidado`, corrigido depois de um bug real: bolsa "parcela única" já
    paga continuava pedindo reforço só por causa do calendário) para a "Necessidade até
    Dezembro". Ela não substitui nem se confunde com "Empenhar" por cartão (que continua vindo
    de `meses_empenhados − meses_liquidados`, ver bullet acima): "Empenhar" mede atraso já
    ocorrido; "Necessidade até Dezembro" projeta o gasto restante do exercício.
  * Os tokens de cor/tipografia são os reais do projeto (`src/design_tokens.py`), não os do
    pacote de handoff.
  * KPIs no topo: Despesa Anual Total, Valor Mensal, Necessidade de Reforço, Programas e
    Saldo via Execução Mensal — "Beneficiários Efetivos" saiu por pedido explícito (trocado
    por Despesa Anual Total, mesmo rótulo já usado em `contratos_continuos.py`). "Sem
    Empenho/Não Localizado" e "Saldo Divergente" também saíram do topo antes, por pedido
    explícito — continuam visíveis por cartão (tag vermelha "Sem Empenho"/"Não Localizado"/
    "Diverge"), só não aparecem mais como contagem agregada na entrada da tela.
  * "Remover" apaga o programa em definitivo do cadastro nativo (pedido explícito de
    desvinculação de planilha tornou o cadastro a fonte de verdade — não sobra "planilha de
    origem" para preservar) — pede confirmação num segundo clique antes de excluir de fato.
  * "+ Novo programa" é um `st.popover` compacto no canto superior direito, ao lado do
    título — não um `st.expander` de largura total abaixo dele. Grava direto no cadastro
    nativo do exercício em tela (`src/bolsas_auxilios_cadastro.py`), sobrevive a fechar o
    navegador. Não tem nome/CPF de bolsista: a granularidade real da base é por programa, não
    por beneficiário (ver `src/bolsas_auxilios.py`).
  * Edição inline de cada cartão só grava no cadastro nativo quando o botão "💾 Salvar" do
    próprio cartão é clicado — os campos ficam editáveis e refletem nos quadros acima (KPIs,
    Resumo Consolidado) a cada tecla via `_aplicar_edicoes_da_sessao`, mas isso é só o estado
    da sessão; sem clicar em salvar, fechar a aba perde a edição (mesmo padrão de confirmação
    explícita já usado no Relatório de Reforço de Empenho).
"""

from __future__ import annotations

import html as html_lib
from pathlib import Path

import pandas as pd
import streamlit as st

from src.bolsas_auxilios import com_saldo_execucao
from src.bolsas_auxilios_cadastro import (
    anos_disponiveis,
    atualizar_programa,
    carregar_programas,
    como_dataframe,
    duplicar_exercicio,
    excluir_exercicio,
    excluir_programa,
    novo_programa,
    salvar_programa,
)
from src.design_tokens import (
    ACCENT,
    ACCENT_STRONG,
    BORDER,
    BORDER_SOFT,
    CARD_PAD,
    FONT_BODY,
    FONT_HEADING,
    NEGATIVE,
    POSITIVE,
    RADIUS,
    SIZE,
    SPACE,
    SURFACE,
    TEXT,
    TEXT_MUTED,
    TRACK,
    WARNING,
)
from src.execucao_ne_utils import ne_curta as _ne_curta_execucao, saldo_por_ne
from src.importacao_dotacao import DIRETORIO_MANIFESTOS_PADRAO, Manifesto as ManifestoDotacao
from src.importacao_dotacao import NOME_PONTEIRO as NOME_PONTEIRO_DOTACAO
from src.importacao_dotacao import carregar_atual as carregar_dotacao_atual
from src.importacao_execucao_mensal import DIRETORIO_MANIFESTOS_PADRAO as DIRETORIO_MANIFESTOS_EXECUCAO_MENSAL
from src.importacao_execucao_mensal import Manifesto as ManifestoExecucaoMensal
from src.importacao_execucao_mensal import NOME_PONTEIRO as NOME_PONTEIRO_EXECUCAO_MENSAL
from src.importacao_execucao_mensal import carregar_atual as carregar_execucao_mensal_atual
from src.necessidade_empenho import calcular_necessidade_empenho
from src.relatorio_reforco_empenho import BOLSAS_AUXILIOS as RELATORIO_BOLSAS_AUXILIOS
from src.tesouro_execucao_mensal import agregar_por_ne, linha_do_tempo_por_ne, primeiro_mes_com_empenho_por_ne
from src.ui_linha_do_tempo import BASE_LIQUIDADO_EXECUCAO_MENSAL, MESES_ABREV, abrir_linha_do_tempo
from src.ui_relatorio_reforco_empenho import render_botao_relatorio
from src.ui_theme import format_brl_compact, render_metric_grid, render_page_header

COLUNAS_BUSCA = ["processo", "programa_bolsa", "unidade_cod", "acao_cod", "pi_cod", "ne_curta"]

SITUACAO_OPCOES = ["ATUALIZADO", "SEM EMPENHO", "NÃO LOCALIZADO"]


@st.cache_data(show_spinner="Lendo a linha do tempo mensal...")
def _cached_linha_do_tempo(caminho_ponteiro: str, sha_manifesto: str) -> pd.DataFrame:
    """Empenhado/Liquidado/Pago por (NE, mês), a partir da base MENSAL (`carregar_atual`,
    importação versionada — ver `src/importacao_execucao_mensal.py`) — com `ne_curta` (forma
    "2026NE000123", ver `src.execucao_ne_utils.ne_curta`) acrescentada, pra poder ligar com o
    `ne_curta` já usado no cadastro de Bolsas (`src/bolsas_auxilios.py`). Pop-up "Linha do
    tempo mensal" (`src/ui_linha_do_tempo.py`), pedido explícito: mesmo formato de
    `app_pages/consulta_empenhos.py`. `caminho_ponteiro`/`sha_manifesto` só participam da
    chave de cache."""

    tempo = linha_do_tempo_por_ne(carregar_execucao_mensal_atual())
    tempo["ne_curta"] = tempo["ne_ccor"].apply(_ne_curta_execucao)
    return tempo


@st.cache_data(show_spinner="Lendo a base de Execução Mensal...")
def _cached_por_ne_execucao(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    """Saldo autoritativo por NE, a partir da Execução MENSAL (2024+) — não mais a Anual (ver
    decisão de 22/09/2026, pedido do usuário: parar de depender da Execução Mensal).
    `agregar_por_ne` aqui é a de `src.tesouro_execucao_mensal` (soma correta entre meses e
    blocos, já deduplicada — ver docstring de lá), não a de `src.execucao_anual`.
    `caminho_ponteiro`/`mtime_ponteiro` só participam da chave de cache — força reler quando
    o manifesto atual mudar. `carregar_atual` já devolve a base composta por ano (ver
    `src/importacao_execucao_mensal.py`)."""

    return saldo_por_ne(agregar_por_ne(carregar_execucao_mensal_atual()))


@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def _cached_dotacao_por_ptres(caminho_ponteiro: str, mtime_ponteiro: float) -> tuple[pd.DataFrame, int]:
    """Uma linha por PTRES do exercício mais recente da base (a base traz vários anos —
    misturar exercícios inflaria a dotação de cada PTRES): Ação, Plano Orçamentário e Dotação
    Atualizada. Um PTRES pode, em tese, aparecer em mais de uma combinação de Ação/Plano
    Orçamentário — `first` por PTRES é uma simplificação aceitável aqui porque a verificação
    manual contra a extração de 14/08/2026 mostrou 1:1 para todos os PTRES usados pelas
    bolsas cadastradas; se isso mudar, o pior caso é mostrar só a primeira combinação
    encontrada, não um valor de dotação errado (a soma de `dotacao_atualizada` continua
    correta, agregada por PTRES independente da cardinalidade). `caminho_ponteiro`/
    `mtime_ponteiro` só participam da chave de cache — `carregar_atual` já devolve a base
    composta por ano (ver `src/importacao_dotacao.py`)."""

    dados = carregar_dotacao_atual()
    ano_exercicio = int(dados["ano_lancamento"].max())
    do_exercicio = dados[dados["ano_lancamento"] == ano_exercicio]

    dimensoes = do_exercicio.groupby("ptres_codigo", dropna=False).agg(
        acao_codigo=("acao_codigo", "first"),
        acao_descricao=("acao_descricao", "first"),
        plano_orcamentario_codigo=("plano_orcamentario_codigo", "first"),
        plano_orcamentario_descricao=("plano_orcamentario_descricao", "first"),
    )
    dotacao = do_exercicio[do_exercicio["item_informacao_codigo"] == "dotacao_atualizada"]
    dimensoes["dotacao_atualizada"] = dotacao.groupby("ptres_codigo")["valor_movimento_liquido"].sum(min_count=1)
    return dimensoes.reset_index(), ano_exercicio


def _ou_zero(value: object) -> float:
    return 0.0 if pd.isna(value) else float(value)


def _ou_vazio(value: object) -> str:
    return "" if pd.isna(value) else str(value)


def _esc(value: object) -> str:
    return html_lib.escape(str(value))


def _dash(value: object) -> str:
    return "—" if pd.isna(value) else _esc(value)


def _brl(value: object) -> str:
    if pd.isna(value):
        return "—"
    return "R$ " + f"{round(float(value)):,.0f}".replace(",", ".")


def _num(value: object) -> str:
    if pd.isna(value):
        return "—"
    return f"{round(float(value)):,}".replace(",", ".")


def _aplicar_busca(dataframe: pd.DataFrame, busca: str) -> pd.DataFrame:
    if not busca:
        return dataframe
    alvo = busca.strip().lower()
    mascara = pd.Series(False, index=dataframe.index)
    for coluna in COLUNAS_BUSCA:
        mascara = mascara | dataframe[coluna].astype("string").str.lower().str.contains(alvo, na=False, regex=False)
    return dataframe[mascara]


def _somar_unico_por_ne(dataframe: pd.DataFrame, coluna: str) -> float:
    unicos = dataframe.dropna(subset=["ne_curta"]).drop_duplicates("ne_curta")
    return float(unicos[coluna].sum())




def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .bls-label {{
            font-family: {FONT_HEADING}; font-size: 9.5px; letter-spacing: 0.08em;
            text-transform: uppercase; color: {TEXT_MUTED}; margin-bottom: -6px;
        }}
        .bls-calc {{ font-size: 13px; font-variant-numeric: tabular-nums; padding: 8px 0 2px; }}
        .bls-calc.strong {{ font-weight: 600; color: {ACCENT_STRONG}; }}
        .bls-tag {{
            display: inline-block; font-family: {FONT_HEADING}; font-size: 9.5px;
            letter-spacing: 0.06em; text-transform: uppercase; padding: 3px 8px;
            border-radius: 3px; margin: 1px 4px 1px 0;
        }}
        .bls-tag.ok {{ background: rgba(34,197,94,0.12); color: {POSITIVE}; }}
        .bls-tag.warn {{ background: rgba(245,165,36,0.12); color: {WARNING}; }}
        .bls-tag.bad {{ background: rgba(240,87,107,0.12); color: {NEGATIVE}; }}
        .bls-exec {{ font-size: 11px; color: {TEXT_MUTED}; }}
        /* Resumo Consolidado: cartão + grade HTML de app_pages/painel_acoes.py (.po-*), com
           prefixo próprio (.bls-resumo-*) — nao eh um st.dataframe: grade fixa, tipografia do
           projeto, sem cara de planilha (sem linhas zebradas nem grade do Excel).

           Pedido explícito posterior: cada bolsa virou um `st.button` clicável (abre pop-up
           de linha do tempo mensal, ver `_render_resumo_consolidado`/`src/ui_linha_do_tempo.py`)
           — por isso o cartão externo trocou de `<div class="bls-resumo-card">` pra
           `st.container(border=True, key="bls_resumo_card")`: não dá pra ter um `st.button`
           clicável dentro de HTML injetado via `st.markdown` num único bloco (HTML puro não
           dispara evento Python), então as linhas de bolsa precisam ser widgets de verdade,
           não mais uma grade HTML fixa igual à do cabeçalho/rodapé. `st.container(border=True)`
           já usa o mesmo tom/borda de `SURFACE`/`BORDER` globalmente (ver `src/ui_theme.py`),
           então o visual do cartão não muda. */
        .bls-resumo-head {{
            display: grid; grid-template-columns: minmax(0,1fr) auto;
            gap: 24px; align-items: start; margin-bottom: {SPACE['md']};
        }}
        .bls-resumo-kicker {{
            font-family: {FONT_HEADING}; font-size: {SIZE['value']};
            letter-spacing: {TRACK['kicker']}; color: {ACCENT}; text-transform: uppercase;
        }}
        .bls-resumo-title {{
            margin: 3px 0 0; font-family: {FONT_HEADING}; font-weight: 600;
            font-size: {SIZE['card_title']}; line-height: 1.12; color: {TEXT};
        }}
        .bls-resumo-metric-label {{
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: {TRACK['label']}; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .bls-resumo-metric {{
            font-family: {FONT_HEADING}; font-size: {SIZE['metric']}; line-height: 1.1;
            color: {ACCENT_STRONG}; font-variant-numeric: tabular-nums;
        }}
        /* Cabeçalho de rótulos, linhas e rodapé viraram `st.columns` de verdade — mesma
           largura relativa nos três (`_LARGURAS_RESUMO`) — em vez de uma grade HTML fixa
           (cabeçalho) + uma linha solta em flex-wrap (dados): o cabeçalho prometia colunas
           alinhadas que a linha de dados não respeitava (pedido explícito de correção —
           "muita informação no meio", sem alinhar com nada do cabeçalho). Cada célula ainda é
           HTML (`st.markdown`) dentro de cada coluna, só o layout que passou a ser nativo. */
        .st-key-bls_resumo_card button {{ justify-content: flex-start; text-align: left; }}
        /* Rolagem (pedido explícito) em vez de "Ver mais" — 5 bolsas visíveis por padrão;
           mesmo padrão de app_pages/consulta_empenhos.py::.st-key-ce_list_scroll, altura
           menor aqui (~5 linhas, não ~15: o Resumo Consolidado é um card de apoio, não a
           lista principal da tela). */
        .st-key-bls_resumo_scroll {{ max-height: 340px; overflow-y: auto; padding-right: 8px; }}
        .bls-resumo-nome-simples {{
            font-family: {FONT_BODY}; font-size: {SIZE['body']}; color: {TEXT};
            padding: 8px 0;
        }}
        .bls-resumo-col-label {{
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
        }}
        .bls-resumo-cell {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED}; padding: 8px 0;
        }}
        .bls-resumo-cell-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
            padding: 8px 0;
        }}
        .bls-resumo-foot-label {{
            font-size: {SIZE['label']}; letter-spacing: {TRACK['label']};
            text-transform: uppercase; color: {TEXT_MUTED}; padding-top: 9px;
        }}
        /* Pop-up "Linha do tempo mensal" (`src/ui_linha_do_tempo.py`) — mesmo formato de
           `app_pages/consulta_empenhos.py::_inject_css` (pedido explícito: "mesmo formato
           implementado na consulta de empenhos"). CSS duplicado de propósito: Streamlit não
           carrega o CSS injetado numa página anterior ao navegar para outra, cada página que
           usa esse pop-up precisa da sua própria cópia deste bloco. */
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
        /* Cobertura Orçamentária por PTRES: um cartão por Ação, mesmo padrão visual de
           app_pages/painel_acoes.py (.po-*), reaproveitado com prefixo próprio
           (.bls-dotacao-*) — 5 colunas (Plano Orçamentário, PTRES, Dotação, Despesa, Saldo),
           não as 4 de .bls-resumo-*, por isso não dá para reaproveitar a mesma classe. */
        .bls-dotacao-card {{
            border: 1px solid {BORDER}; border-radius: {RADIUS};
            background: {SURFACE}; padding: {CARD_PAD}; margin-bottom: {SPACE['lg']};
        }}
        .bls-dotacao-card-head {{
            display: grid; grid-template-columns: minmax(0,1fr) auto;
            gap: 24px; align-items: start; margin-bottom: {SPACE['md']};
        }}
        .bls-dotacao-kicker {{
            font-family: {FONT_HEADING}; font-size: {SIZE['value']};
            letter-spacing: {TRACK['kicker']}; color: {ACCENT}; text-transform: uppercase;
        }}
        .bls-dotacao-title {{
            margin: 3px 0 0; font-family: {FONT_HEADING}; font-weight: 600;
            font-size: {SIZE['card_title']}; line-height: 1.12; color: {TEXT};
            text-transform: uppercase; text-wrap: pretty;
        }}
        .bls-dotacao-metric-label {{
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: {TRACK['label']}; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .bls-dotacao-metric {{
            font-family: {FONT_HEADING}; font-size: {SIZE['metric']}; line-height: 1.1;
            font-variant-numeric: tabular-nums;
        }}
        .bls-dotacao-scroll {{ overflow-x: auto; padding-bottom: 2px; }}
        .bls-dotacao-row, .bls-dotacao-head-row, .bls-dotacao-foot {{
            display: grid; grid-template-columns: minmax(200px,2fr) 90px 130px 130px 130px;
            gap: 10px; min-width: 700px;
        }}
        .bls-dotacao-head-row {{
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .bls-dotacao-row {{
            padding: 9px 0; border-bottom: 1px solid {BORDER_SOFT}; align-items: baseline;
        }}
        .bls-dotacao-foot {{ padding-top: 9px; font-family: {FONT_HEADING}; align-items: baseline; }}
        .bls-dotacao-name {{ font-family: {FONT_BODY}; font-size: {SIZE['small']}; line-height: 1.25; color: {TEXT}; }}
        .bls-dotacao-code {{
            font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: {TRACK['label']}; color: {TEXT_MUTED};
        }}
        .bls-dotacao-flat {{
            font-family: {FONT_HEADING}; font-size: {SIZE['small']};
            letter-spacing: 0.08em; color: {TEXT_MUTED};
        }}
        .bls-dotacao-val {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED};
        }}
        .bls-dotacao-val-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums;
        }}
        .bls-dotacao-foot-label {{
            font-size: {SIZE['label']}; letter-spacing: {TRACK['label']};
            text-transform: uppercase; color: {TEXT_MUTED};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _campo_texto(col, label: str, valor: str, key: str) -> str:
    col.markdown(f"<div class='bls-label'>{label}</div>", unsafe_allow_html=True)
    return col.text_input(label, value=valor, key=key, label_visibility="collapsed")


def _campo_numero(col, label: str, valor: float, key: str, step: float = 1.0, fmt: str | None = None, min_value: float | None = None) -> float:
    col.markdown(f"<div class='bls-label'>{label}</div>", unsafe_allow_html=True)
    # format="%d" exige value/step/min_value inteiros — passar float com esse formato
    # dispara o aviso "NumberInput value below has type float, but format %d displays as
    # integer" do Streamlit.
    if fmt == "%d":
        valor, step = int(valor), int(step)
        min_value = int(min_value) if min_value is not None else None
    else:
        valor = float(valor)
    return col.number_input(label, value=valor, step=step, key=key, label_visibility="collapsed", format=fmt, min_value=min_value)


_OPCOES_INICIO_EXECUCAO = ["Automático"] + [MESES_ABREV[m] for m in range(1, 13)]


def _campo_inicio_execucao(col, valor_persistido: object, sugestao_auto: object, key: str) -> int | None:
    """"Início da Execução" (mês 1-12) usado só pela sugestão "por calendário" do Relatório de
    Reforço (`necessidade_ate_mes_vigente`) — pedido explícito: "o sistema faz essa análise
    [primeiro empenho] e usa a data do primeiro empenho como referencial..., mas também inclui
    o campo início e ele pode ser alterado caso eu perceba algum erro". "Automático" (`None`
    persistido) usa `sugestao_auto` (mês do primeiro empenho daquela NE, detectado a partir da
    base mensal — ver `_cached_linha_do_tempo`/`primeiro_mes_com_empenho_por_ne`) sempre que a
    página rodar, então nunca fica desatualizado; selecionar um mês específico grava um
    override manual, fixo até o usuário voltar pra "Automático"."""

    col.markdown("<div class='bls-label'>Início da Execução</div>", unsafe_allow_html=True)
    indice_atual = int(valor_persistido) if pd.notna(valor_persistido) else 0
    ajuda = (
        f"Detectado automaticamente pelo primeiro empenho: {MESES_ABREV[int(sugestao_auto)]}"
        if pd.notna(sugestao_auto)
        else "Sem dado suficiente na base mensal pra detectar automaticamente — informe o mês manualmente, se souber."
    )
    escolha = col.selectbox(
        "Início da Execução", _OPCOES_INICIO_EXECUCAO, index=indice_atual, key=key,
        label_visibility="collapsed", help=ajuda,
    )
    return None if escolha == "Automático" else _OPCOES_INICIO_EXECUCAO.index(escolha)


def _rotulo_expander(linha: pd.Series) -> str:
    """Prévia do cartão minimizado — a partir dos valores brutos da linha (não dos widgets,
    que só existem depois de abrir o expander). `valor_a_empenhar` já vem resolvido pelo
    pipeline (Execução Mensal quando disponível, planilha como fallback — ver
    `com_saldo_execucao`); recalcular aqui a partir de `meses_empenhados`/`meses_liquidados`
    mostraria um número desatualizado sempre que a Execução Mensal estiver disponível."""

    programa = _ou_vazio(linha["programa_bolsa"]) or "(sem item de despesa)"
    processo = _ou_vazio(linha["processo"])
    valor_a_empenhar = _ou_zero(linha["valor_a_empenhar"])
    situacao_bruta = linha["situacao_tg"]
    if pd.notna(situacao_bruta) and situacao_bruta in ("SEM EMPENHO", "NÃO LOCALIZADO"):
        emoji = "🔴"
    elif valor_a_empenhar > 0:
        emoji = "🟡"
    else:
        emoji = "🟢"
    partes = [emoji, programa]
    if processo:
        partes.append(f"— {processo}")
    partes.append(f"· {_brl(valor_a_empenhar)}")
    return " ".join(partes)


def _render_card(linha: pd.Series, ano: int, source_key: str, sugestao_inicio_por_ne: pd.Series) -> None:
    id_programa = str(linha["id"])
    k = f"bls_{source_key}_{id_programa}"

    with st.expander(_rotulo_expander(linha), expanded=False):
        c_item, c_sit = st.columns([3, 1])
        programa = _campo_texto(c_item, "Item de Despesa (Programa)", _ou_vazio(linha["programa_bolsa"]), f"{k}_programa")
        c_sit.markdown("<div class='bls-label'>Situação TG</div>", unsafe_allow_html=True)
        situacao_bruta = linha["situacao_tg"]
        situacao_atual = situacao_bruta if pd.notna(situacao_bruta) and situacao_bruta in SITUACAO_OPCOES else "ATUALIZADO"
        situacao = c_sit.selectbox(
            "Situação TG", SITUACAO_OPCOES, index=SITUACAO_OPCOES.index(situacao_atual),
            key=f"{k}_situacao", label_visibility="collapsed",
        )

        r1 = st.columns(5)
        processo = _campo_texto(r1[0], "Processo", _ou_vazio(linha["processo"]), f"{k}_processo")
        unidade = _campo_texto(r1[1], "Unidade", _ou_vazio(linha["unidade_cod"]), f"{k}_unidade")
        acao = _campo_texto(r1[2], "Ação", _ou_vazio(linha["acao_cod"]), f"{k}_acao")
        ptres = _campo_texto(r1[3], "PTRES", _ou_vazio(linha["ptres"]), f"{k}_ptres")
        fonte = _campo_texto(r1[4], "Fonte", _ou_vazio(linha["fonte_cod"]), f"{k}_fonte")

        r2 = st.columns(5)
        nd = _campo_texto(r2[0], "ND", _ou_vazio(linha["natureza_despesa_cod"]), f"{k}_nd")
        ugr = _campo_texto(r2[1], "UGR", _ou_vazio(linha["ugr_cod"]), f"{k}_ugr")
        pi = _campo_texto(r2[2], "PI", _ou_vazio(linha["pi_cod"]), f"{k}_pi")
        ne_curta = _campo_texto(r2[3], "Empenho (NE)", _ou_vazio(linha["ne_curta"]), f"{k}_ne")
        meses_no_ano = _campo_numero(r2[4], "Meses/Ano", _ou_zero(linha["meses_no_ano"]) or 12, f"{k}_mesesano", step=1.0, fmt="%d", min_value=1.0)

        r3 = st.columns(4)
        qtd_inicial = _campo_numero(r3[0], "Qtd. Inicial", _ou_zero(linha["qtd_inicial"]), f"{k}_qtdinicial", step=1.0, fmt="%d", min_value=0.0)
        qtd_efetiva = _campo_numero(r3[1], "Qtd. Efetiva", _ou_zero(linha["qtd_efetiva"]), f"{k}_qtdefetiva", step=1.0, fmt="%d", min_value=0.0)
        # sem min_value=0.0 daqui pra baixo: mesmo risco encontrado em Contratos Contínuos —
        # meses_empenhados/liquidados (e valores monetários) podem vir negativos na origem
        # (anulação/ajuste retroativo); um piso de zero quebraria a leitura desse dado real.
        valor_unitario = _campo_numero(r3[2], "Valor Unit. (R$)", _ou_zero(linha["valor_unitario"]), f"{k}_valorunit", step=10.0)

        # Empenhado/Saldo: mesmo critério de Meses Empenhados/Liquidados logo abaixo — com NE
        # já encontrada na Execução Mensal, o campo passa a EXIBIR o valor autoritativo (não
        # editável) em vez do valor colado na planilha, pedido explícito pra o cartão
        # acompanhar a Execução Mensal sempre que ela tiver o dado, não só nos quadros de
        # cima (Resumo Consolidado, KPIs). Sem NE encontrada, continua editável a partir da
        # planilha (fallback inalterado).
        valor_empenhado_execucao = linha["valor_empenhado_execucao"]
        via_execucao_valor_empenhado = pd.notna(valor_empenhado_execucao)
        if via_execucao_valor_empenhado:
            r3[3].markdown("<div class='bls-label'>Empenhado (Execução Mensal)</div>", unsafe_allow_html=True)
            r3[3].markdown(f"<div class='bls-calc'>{_brl(float(valor_empenhado_execucao))}</div>", unsafe_allow_html=True)
            valor_empenhado_tg_persistir = _ou_zero(linha["valor_empenhado_tg"])
        else:
            valor_empenhado_tg_persistir = _campo_numero(
                r3[3], "Empenhado (R$)", _ou_zero(linha["valor_empenhado_tg"]), f"{k}_valorempenhado", step=100.0
            )

        r4 = st.columns(4)
        # Mesmo critério de `app_pages/contratos_continuos.py::_render_card`: com NE já
        # encontrada na Execução Mensal, os campos manuais viram exibição (ver
        # `com_saldo_execucao`), não editáveis — digitar ali deixaria de ter efeito no
        # "Empenhar" mostrado, e reintroduziria o bug de dois quadros com números diferentes.
        via_execucao = pd.notna(linha["meses_empenhados_execucao"])
        if via_execucao:
            meses_empenhados = float(linha["meses_empenhados_execucao"])
            meses_liquidados = float(linha["meses_liquidados_execucao"])
            r4[0].markdown("<div class='bls-label'>Meses Empenhados (Execução Mensal)</div>", unsafe_allow_html=True)
            r4[0].markdown(f"<div class='bls-calc'>{_num(meses_empenhados)}</div>", unsafe_allow_html=True)
            r4[1].markdown("<div class='bls-label'>Meses Liquidados (Execução Mensal)</div>", unsafe_allow_html=True)
            r4[1].markdown(f"<div class='bls-calc'>{_num(meses_liquidados)}</div>", unsafe_allow_html=True)
            meses_empenhados_persistir = _ou_zero(linha["meses_empenhados"])
            meses_liquidados_persistir = _ou_zero(linha["meses_liquidados"])
        else:
            meses_empenhados = _campo_numero(r4[0], "Meses Empenhados", _ou_zero(linha["meses_empenhados"]), f"{k}_mesesemp", step=0.1)
            meses_liquidados = _campo_numero(r4[1], "Meses Liquidados", _ou_zero(linha["meses_liquidados"]), f"{k}_mesesliq", step=0.1)
            meses_empenhados_persistir = meses_empenhados
            meses_liquidados_persistir = meses_liquidados

        saldo_execucao = linha["saldo_execucao"]
        via_execucao_saldo = pd.notna(saldo_execucao)
        if via_execucao_saldo:
            r4[2].markdown("<div class='bls-label'>Saldo (Execução Mensal)</div>", unsafe_allow_html=True)
            r4[2].markdown(f"<div class='bls-calc'>{_brl(float(saldo_execucao))}</div>", unsafe_allow_html=True)
            saldo_colado_planilha_persistir = _ou_zero(linha["saldo_colado_planilha"])
        else:
            saldo_colado_planilha_persistir = _campo_numero(
                r4[2], "Saldo (R$)", _ou_zero(linha["saldo_colado_planilha"]), f"{k}_saldo", step=100.0
            )

        valor_mensal_excepcional = linha.get("valor_mensal_excepcional")
        valor_mensal = (
            float(valor_mensal_excepcional)
            if pd.notna(valor_mensal_excepcional)
            else qtd_efetiva * valor_unitario
        )
        meses_a_empenhar, valor_a_empenhar = calcular_necessidade_empenho(
            meses_empenhados, meses_liquidados, valor_mensal
        )

        rotulo_valor_mensal = (
            "Valor Mensal (informado)"
            if pd.notna(valor_mensal_excepcional)
            else "Valor Mensal"
        )
        r4[3].markdown(f"<div class='bls-label'>{rotulo_valor_mensal}</div>", unsafe_allow_html=True)
        r4[3].markdown(f"<div class='bls-calc'>{_brl(valor_mensal)}</div>", unsafe_allow_html=True)

        r5 = st.columns(3)
        r5[0].markdown("<div class='bls-label'>Meses de Saldo</div>", unsafe_allow_html=True)
        r5[0].markdown(f"<div class='bls-calc'>{_num(meses_a_empenhar)}</div>", unsafe_allow_html=True)
        rotulo_empenhar = "Empenhar (Execução Mensal)" if via_execucao else "Empenhar (planilha)"
        r5[1].markdown(f"<div class='bls-label'>{rotulo_empenhar}</div>", unsafe_allow_html=True)
        r5[1].markdown(f"<div class='bls-calc strong'>{_brl(valor_a_empenhar)}</div>", unsafe_allow_html=True)
        sugestao_inicio = sugestao_inicio_por_ne.get(linha["ne_curta"]) if pd.notna(linha["ne_curta"]) else None
        inicio_execucao_mes_editado = _campo_inicio_execucao(
            r5[2], linha["inicio_execucao_mes"], sugestao_inicio, f"{k}_inicio",
        )

        if situacao == "SEM EMPENHO":
            tag_txt, tag_cls = "Sem Empenho", "bad"
        elif situacao == "NÃO LOCALIZADO":
            tag_txt, tag_cls = "Não Localizado", "bad"
        elif valor_a_empenhar > 0:
            tag_txt, tag_cls = "Necessita Reforço", "warn"
        else:
            tag_txt, tag_cls = "Atualizado", "ok"
        # Sem "Diverge": Saldo/Empenhado agora exibem o valor da Execução Mensal diretamente
        # quando ela tem a NE (ver acima), não mais um campo separado colado da planilha ao
        # lado do valor autoritativo — não sobra o que comparar/divergir dentro do cartão.
        if via_execucao_saldo or via_execucao_valor_empenhado:
            tag_div_txt, tag_div_cls = "Via Execução Mensal", "ok"
        else:
            tag_div_txt, tag_div_cls = "Sem Execução", "warn"

        f1, f2, f3 = st.columns([4, 1, 1])
        f1.markdown(
            f"<span class='bls-tag {tag_cls}'>{tag_txt}</span>"
            f"<span class='bls-tag {tag_div_cls}'>{tag_div_txt}</span>",
            unsafe_allow_html=True,
        )
        if f2.button("💾 Salvar", key=f"{k}_salvar", use_container_width=True):
            atualizado = {
                **linha.to_dict(),
                "processo": processo or None, "programa_bolsa": programa or None,
                "unidade_cod": unidade or None, "acao_cod": acao or None, "ptres": ptres or None,
                "fonte_cod": fonte or None, "natureza_despesa_cod": nd or None, "ugr_cod": ugr or None,
                "pi_cod": pi or None, "ne_curta": ne_curta.strip() or None, "meses_no_ano": meses_no_ano,
                "qtd_inicial": qtd_inicial, "qtd_efetiva": qtd_efetiva, "valor_unitario": valor_unitario,
                "valor_mensal_excepcional": (
                    float(valor_mensal_excepcional) if pd.notna(valor_mensal_excepcional) else None
                ),
                "valor_empenhado_tg": valor_empenhado_tg_persistir,
                "saldo_colado_planilha": saldo_colado_planilha_persistir,
                "situacao_tg": situacao, "meses_empenhados": meses_empenhados_persistir,
                "meses_liquidados": meses_liquidados_persistir,
                "inicio_execucao_mes": inicio_execucao_mes_editado,
            }
            for chave_extra in ("valor_mensal", "valor_anual", "meses_a_empenhar", "valor_a_empenhar", "saldo_execucao", "valor_empenhado_execucao", "valor_liquidado_execucao", "diverge_saldo", "diverge_valor_empenhado", "meses_empenhados_execucao", "meses_liquidados_execucao", "necessidade_via", "inicio_execucao_efetivo", "valor_empenhado_autoritativo"):
                atualizado.pop(chave_extra, None)
            atualizar_programa(ano, atualizado)
            st.success("Programa salvo.")
            st.rerun()

        confirmar_key = f"{k}_confirmar_exclusao"
        if st.session_state.get(confirmar_key):
            if f3.button("Confirmar exclusão?", key=f"{k}_remover_confirmar", use_container_width=True, type="primary"):
                excluir_programa(ano, id_programa)
                st.session_state.pop(confirmar_key, None)
                st.rerun()
        else:
            if f3.button("Remover", key=f"{k}_remover", use_container_width=True):
                st.session_state[confirmar_key] = True
                st.rerun()


def _render_novo_programa(ano: int, source_key: str) -> None:
    """"+ Novo programa" — popover compacto no canto superior direito da tela (não um
    expander de largura total). Grava direto no cadastro nativo do exercício em tela
    (`src/bolsas_auxilios_cadastro.py`), sobrevive a fechar o navegador."""

    with st.popover("+ Novo programa", icon=":material/add:", width=380):
        with st.form(f"bolsas_auxilios_form_{source_key}", clear_on_submit=True):
            programa = st.text_input("Item de despesa (programa)")
            processo = st.text_input("Processo")
            c1, c2 = st.columns(2)
            unidade = c1.text_input("Unidade")
            acao = c2.text_input("Ação")
            c3, c4 = st.columns(2)
            ptres = c3.text_input("PTRES")
            fonte = c4.text_input("Fonte", value="1000")
            c5, c6 = st.columns(2)
            nd = c5.text_input("ND", value="339018")
            ugr = c6.text_input("UGR")
            c7, c8 = st.columns(2)
            pi = c7.text_input("PI")
            ne_curta = c8.text_input("NE (opcional)", placeholder="ex. 2026NE000999")
            c9, c10 = st.columns(2)
            meses_no_ano = c9.number_input("Meses no ano", min_value=1, max_value=12, value=12)
            qtd_inicial = c10.number_input("Qtd. inicial", min_value=0, step=1)
            c11, c12 = st.columns(2)
            qtd_efetiva = c11.number_input("Qtd. efetiva", min_value=0, step=1)
            valor_unitario = c12.number_input("Valor unitário (R$)", min_value=0.0, step=10.0)
            c13, c14 = st.columns(2)
            valor_empenhado = c13.number_input("Valor empenhado (R$)", min_value=0.0, step=100.0)
            saldo_colado = c14.number_input("Saldo colado na planilha (R$)", min_value=0.0, step=100.0)
            c15, c16 = st.columns(2)
            meses_empenhados = c15.number_input("Meses empenhados", min_value=0.0, step=0.1)
            meses_liquidados = c16.number_input("Meses liquidados", min_value=0.0, step=0.1)

            if st.form_submit_button("Adicionar programa"):
                if not programa or not qtd_efetiva or not valor_unitario:
                    st.error("Informe ao menos o item de despesa, quantidade efetiva e valor unitário.")
                else:
                    registro = novo_programa(
                        processo=processo or "—", programa_bolsa=programa, unidade_cod=unidade,
                        acao_cod=acao, ptres=ptres, fonte_cod=fonte, natureza_despesa_cod=nd,
                        ugr_cod=ugr, pi_cod=pi, ne_curta=ne_curta.strip() or None,
                        meses_no_ano=meses_no_ano, qtd_inicial=qtd_inicial, qtd_efetiva=qtd_efetiva,
                        valor_unitario=valor_unitario, valor_empenhado_tg=valor_empenhado,
                        saldo_colado_planilha=saldo_colado, situacao_tg="SEM EMPENHO",
                        meses_empenhados=meses_empenhados, meses_liquidados=meses_liquidados,
                    )
                    salvar_programa(ano, registro)
                    st.success("Programa cadastrado.")
                    st.rerun()


#: larguras relativas usadas por `st.columns` no cabeçalho de rótulos, em cada linha e no
#: rodapé do Resumo Consolidado — as três precisam ser exatamente as mesmas pra alinhar.
_LARGURAS_RESUMO = [2.4, 1, 1, 1, 1.3]


def _html_valor_resumo(valor: object, forte: bool = False) -> str:
    classe = "bls-resumo-cell-strong" if forte else "bls-resumo-cell"
    texto = "sem NE" if pd.isna(valor) else _brl(valor)
    return f'<div class="{classe}">{texto}</div>'


def _render_resumo_consolidado(
    filtrado: pd.DataFrame,
    tempo_por_ne_curta: pd.DataFrame | None,
    source_key: str,
) -> None:
    """Card único, visível de início (antes de abrir qualquer cartão), listando — uma linha por
    bolsa, não agregado num único total — o valor empenhado, o saldo e a necessidade de
    empenho até dezembro de cada programa.

    Pedido explícito: cada bolsa com NE encontrada na base MENSAL (2024+) é clicável — abre o
    mesmo pop-up "Linha do tempo mensal" de `app_pages/consulta_empenhos.py`
    (`src/ui_linha_do_tempo.py`, compartilhado). Bolsa sem NE ou sem dado mensal aparece como
    texto simples, sem botão — mesmo critério de "some silenciosamente" já usado lá.

    Cada linha é um `st.button` de verdade (não HTML): não dá pra ter um botão clicável dentro
    de um bloco de HTML injetado via `st.markdown` — HTML puro não dispara evento Python. O
    cartão em si virou `st.container(border=True)` pelo mesmo motivo (ver `_inject_css`)."""

    valor_mensal = filtrado["valor_mensal"].fillna(0.0)
    # valor empenhado autoritativo (Execução Mensal), com o valor colado na planilha como
    # reserva só para NE sem correspondência lá — mesmo padrão de fallback do saldo.
    valor_empenhado_exibido = filtrado["valor_empenhado_execucao"].fillna(filtrado["valor_empenhado_tg"])
    # Meses AINDA DEVIDOS no exercício (pedido explícito, corrige bug real relatado pelo
    # usuário: caso concreto AUXÍLIO BEXT — Parcela Única, `meses_no_ano=1`, já com sua única
    # parcela empenhada e liquidada, continuava mostrando necessidade pelos meses restantes do
    # CALENDÁRIO — 4 meses, R$ 280 mil — mesmo sem nenhum pagamento programado pra eles).
    # Substitui de vez o antigo "meses restantes até dezembro" GLOBAL (mesmo número pra toda
    # bolsa, sem olhar quantas ela já teve nem quantas tem no total — removido junto de
    # `_meses_restantes_no_ano`): cada bolsa tem seu próprio teto anual (`meses_no_ano`) menos
    # quanto dela já foi empenhado (`valor_empenhado ÷ valor_mensal`, mesma conta usada em
    # `necessidade_ate_mes_vigente` pro pop-up de Relatórios). Bolsa sem `meses_no_ano`
    # cadastrado (não deveria acontecer — campo obrigatório no cadastro) cai no padrão de 12
    # (mesmo critério "contínuo" de antes desta correção).
    meses_ja_empenhados = (valor_empenhado_exibido / valor_mensal.replace(0.0, pd.NA)).fillna(0.0)
    meses_restantes_da_bolsa = (filtrado["meses_no_ano"].fillna(12) - meses_ja_empenhados).clip(lower=0)
    necessidade_ate_dezembro = valor_mensal * meses_restantes_da_bolsa
    saldo_por_linha = filtrado["saldo_execucao"].fillna(filtrado["saldo_colado_planilha"]).fillna(0.0)
    empenhar_ate_fim = (necessidade_ate_dezembro - saldo_por_linha).clip(lower=0)

    ordenado = filtrado.assign(
        _necessidade=empenhar_ate_fim, _valor_empenhado=valor_empenhado_exibido, _valor_mensal=valor_mensal
    ).sort_values("_necessidade", ascending=False)
    necessidade_total = empenhar_ate_fim.sum()
    nes_com_tempo = set(tempo_por_ne_curta["ne_curta"]) if tempo_por_ne_curta is not None else set()

    with st.container(border=True, key="bls_resumo_card"):
        st.markdown(
            f"""
            <div class="bls-resumo-head">
              <div style="min-width:0">
                <div class="bls-resumo-kicker">RESUMO CONSOLIDADO</div>
                <div class="bls-resumo-title">Necessidade de Empenho por Bolsa</div>
              </div>
              <div style="text-align:right">
                <div class="bls-resumo-metric-label">Necessidade até Dezembro</div>
                <div class="bls-resumo-metric">{_brl(necessidade_total)}</div>
                <div class="bls-resumo-metric-label" style="margin-top:4px">
                  {len(filtrado)} {"bolsa" if len(filtrado) == 1 else "bolsas"}
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        cabecalho = st.columns(_LARGURAS_RESUMO)
        cabecalho[0].markdown('<div class="bls-resumo-col-label">Bolsa / Programa</div>', unsafe_allow_html=True)
        cabecalho[1].markdown('<div class="bls-resumo-col-label" style="text-align:right">Valor Mensal</div>', unsafe_allow_html=True)
        cabecalho[2].markdown('<div class="bls-resumo-col-label" style="text-align:right">Valor Empenhado</div>', unsafe_allow_html=True)
        cabecalho[3].markdown('<div class="bls-resumo-col-label" style="text-align:right">Saldo</div>', unsafe_allow_html=True)
        cabecalho[4].markdown('<div class="bls-resumo-col-label" style="text-align:right">Necessidade até Dez.</div>', unsafe_allow_html=True)

        # Pedido explícito: 5 bolsas visíveis por padrão; para ver mais, rolar — não "Ver
        # mais" clicado repetidamente (mesmo padrão de app_pages/consulta_empenhos.py: caixa
        # de altura fixa com `overflow-y: auto`, dimensionada pra ~5 linhas). Com 5 ou menos
        # bolsas no recorte, o conteúdo nem chega a estourar essa altura e a barra de rolagem
        # simplesmente não aparece sozinha — sem precisar de lógica condicional própria.
        with st.container(key="bls_resumo_scroll"):
            for indice, row in ordenado.iterrows():
                rotulo = f"{_dash(row['programa_bolsa'])} — {_dash(row['processo'])}"
                ne_curta_bolsa = row.get("ne_curta")
                clicavel = pd.notna(ne_curta_bolsa) and ne_curta_bolsa in nes_com_tempo
                linha = st.columns(_LARGURAS_RESUMO, vertical_alignment="center")
                if clicavel:
                    if linha[0].button(rotulo, key=f"bls_resumo_tempo_{source_key}_{row['id']}", use_container_width=True):
                        tempo_ne = tempo_por_ne_curta[tempo_por_ne_curta["ne_curta"] == ne_curta_bolsa]
                        legenda = f"{_dash(row['programa_bolsa'])} (NE {ne_curta_bolsa}) — Execução Mensal (BI CPOC)."
                        abrir_linha_do_tempo(legenda, tempo_ne, BASE_LIQUIDADO_EXECUCAO_MENSAL)
                else:
                    linha[0].markdown(f'<div class="bls-resumo-nome-simples">{_esc(rotulo)}</div>', unsafe_allow_html=True)
                linha[1].markdown(_html_valor_resumo(row["_valor_mensal"]), unsafe_allow_html=True)
                linha[2].markdown(_html_valor_resumo(row["_valor_empenhado"]), unsafe_allow_html=True)
                linha[3].markdown(_html_valor_resumo(row["saldo_execucao"]), unsafe_allow_html=True)
                linha[4].markdown(_html_valor_resumo(row["_necessidade"], forte=True), unsafe_allow_html=True)

        rodape = st.columns(_LARGURAS_RESUMO)
        rodape[0].markdown('<div class="bls-resumo-foot-label">Total</div>', unsafe_allow_html=True)
        rodape[1].markdown(_html_valor_resumo(valor_mensal.sum()), unsafe_allow_html=True)
        rodape[2].markdown(_html_valor_resumo(valor_empenhado_exibido.sum()), unsafe_allow_html=True)
        rodape[3].markdown(_html_valor_resumo(_somar_unico_por_ne(filtrado, "saldo_execucao")), unsafe_allow_html=True)
        rodape[4].markdown(_html_valor_resumo(necessidade_total, forte=True), unsafe_allow_html=True)


_CABECALHO_DOTACAO = [
    ("Plano orçamentário", ""), ("PTRES", ""),
    ("Dotação atualizada", "right"), ("Despesa estimada", "right"), ("Saldo", "right"),
]


def _html_cabecalho_dotacao() -> str:
    celulas = "".join(
        f'<span style="text-align:{alinhamento or "left"}">{texto}</span>'
        for texto, alinhamento in _CABECALHO_DOTACAO
    )
    return f'<div class="bls-dotacao-head-row">{celulas}</div>'


def _par_dotacao(nome: object, codigo: object, prefixo: str = "") -> str:
    nome_texto = "(não informado)" if pd.isna(nome) else _esc(nome)
    return (
        f'<div><div class="bls-dotacao-name">{nome_texto}</div>'
        f'<div class="bls-dotacao-code">{prefixo}{_dash(codigo)}</div></div>'
    )


def _html_linha_dotacao(linha: pd.Series) -> str:
    dotacao, despesa = linha["dotacao_atualizada"], linha["despesa_estimada"]
    dotacao_texto = "sem dotação" if pd.isna(dotacao) else _brl(dotacao)
    if pd.isna(dotacao):
        saldo_html = "<span class='bls-dotacao-val-strong'>—</span>"
    else:
        saldo = float(dotacao) - despesa
        cor = POSITIVE if saldo >= 0 else NEGATIVE
        saldo_html = f"<span class='bls-dotacao-val-strong' style='color:{cor}'>{_brl(saldo)}</span>"
    return (
        '<div class="bls-dotacao-row">'
        + _par_dotacao(linha["plano_orcamentario_descricao"], linha["plano_orcamentario_codigo"], "PO ")
        + f'<span class="bls-dotacao-flat">{_dash(linha["ptres_codigo"])}</span>'
        + f'<span class="bls-dotacao-val">{dotacao_texto}</span>'
        + f'<span class="bls-dotacao-val">{_brl(despesa)}</span>'
        + saldo_html
        + "</div>"
    )


def _render_card_dotacao(codigo: object, nome: object, grupo: pd.DataFrame) -> None:
    """Um cartão por Ação de Governo, com uma subdivisão por PTRES (Plano Orçamentário +
    PTRES) dentro — mesmo padrão visual de `app_pages/painel_acoes.py::_render_card`
    (cabeçalho com kicker/título/métrica em destaque + grade `.po-*`), reaproveitado aqui com
    prefixo próprio `.bls-dotacao-*` para não colidir com o CSS daquela página."""

    ordenado = grupo.sort_values("saldo", ascending=True)
    linhas_html = "".join(_html_linha_dotacao(linha) for _, linha in ordenado.iterrows())

    dotacao_total = grupo["dotacao_atualizada"].sum(min_count=1)
    despesa_total = grupo["despesa_estimada"].sum()
    saldo_total = grupo["saldo"].sum(min_count=1)
    saldo_texto = "sem dotação" if pd.isna(saldo_total) else _brl(saldo_total)
    cor_total = "inherit" if pd.isna(saldo_total) else (POSITIVE if saldo_total >= 0 else NEGATIVE)
    n = len(grupo)

    st.markdown(
        f"""
        <div class="bls-dotacao-card">
          <div class="bls-dotacao-card-head">
            <div style="min-width:0">
              <div class="bls-dotacao-kicker">AÇÃO DE GOVERNO {_esc(codigo)}</div>
              <div class="bls-dotacao-title">{_dash(nome)}</div>
            </div>
            <div style="text-align:right">
              <div class="bls-dotacao-metric-label">Saldo (Dotação − Despesa Estimada)</div>
              <div class="bls-dotacao-metric" style="color:{cor_total}">{saldo_texto}</div>
              <div class="bls-dotacao-metric-label" style="margin-top:4px">
                {n} {"PTRES" if n == 1 else "PTRES"}
              </div>
            </div>
          </div>
          <div class="bls-dotacao-scroll">
            {_html_cabecalho_dotacao()}
            {linhas_html}
            <div class="bls-dotacao-foot">
              <span class="bls-dotacao-foot-label">Total da ação</span>
              <span class="bls-dotacao-val">{_brl(dotacao_total)}</span>
              <span class="bls-dotacao-val">{_brl(despesa_total)}</span>
              <span class="bls-dotacao-val-strong" style="color:{cor_total}">{saldo_texto}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_quadro_dotacao(filtrado: pd.DataFrame, dotacao_dimensoes: pd.DataFrame, ano_exercicio: int) -> None:
    """Um cartão por Ação de Governo (mesmo padrão visual de `painel_acoes.py`), com uma
    subdivisão por Plano Orçamentário/PTRES dentro — cruza, para cada PTRES cadastrado nas
    bolsas (referencial comum entre a Dotação Anual e o cadastro de cada bolsa/programa), a
    Dotação Atualizada disponível contra a despesa anual estimada (`valor_anual`) das bolsas
    daquele PTRES."""

    despesa_por_ptres = filtrado.groupby("ptres")["valor_anual"].sum(min_count=1).fillna(0.0)
    despesa_por_ptres.index.name = "ptres_codigo"

    cruzado = dotacao_dimensoes.set_index("ptres_codigo").join(
        despesa_por_ptres.rename("despesa_estimada"), how="right"
    )
    cruzado = cruzado.reset_index()
    cruzado["saldo"] = cruzado["dotacao_atualizada"] - cruzado["despesa_estimada"]

    sem_dotacao = int(cruzado["dotacao_atualizada"].isna().sum())
    st.caption(
        f"{cruzado['acao_codigo'].nunique(dropna=True)} ações · {len(cruzado)} PTRES · exercício {ano_exercicio}"
        + (f" · {sem_dotacao} sem dotação encontrada" if sem_dotacao else "")
    )

    # ações mais deficitárias primeiro — mesmo critério de urgência do quadro anterior.
    ordem = (
        cruzado.groupby(["acao_codigo", "acao_descricao"], dropna=False)["saldo"]
        .sum(min_count=1)
        .fillna(float("-inf"))
        .sort_values()
        .index
    )
    for codigo, nome in ordem:
        grupo = cruzado[cruzado["acao_codigo"] == codigo]
        _render_card_dotacao(codigo, nome, grupo)


#: sufixo da key do widget (ver `_render_card`) -> coluna do DataFrame que ele edita.
_CAMPOS_EDITAVEIS_NUMERICOS = {
    "mesesano": "meses_no_ano", "qtdinicial": "qtd_inicial", "qtdefetiva": "qtd_efetiva",
    "valorunit": "valor_unitario", "valorempenhado": "valor_empenhado_tg",
    "mesesemp": "meses_empenhados", "mesesliq": "meses_liquidados", "saldo": "saldo_colado_planilha",
}
_CAMPOS_EDITAVEIS_TEXTO = {
    "programa": "programa_bolsa", "processo": "processo", "unidade": "unidade_cod",
    "acao": "acao_cod", "ptres": "ptres", "fonte": "fonte_cod", "nd": "natureza_despesa_cod",
    "ugr": "ugr_cod", "pi": "pi_cod", "ne": "ne_curta",
}


def _aplicar_edicoes_da_sessao(dataframe: pd.DataFrame, source_key: str) -> pd.DataFrame:
    """Sobrepõe, por linha, os valores já editados nos widgets de cada cartão (persistidos em
    `st.session_state` pela própria key do widget, ver `_render_card`) e recalcula os campos
    derivados a partir deles.

    Sem isso, os quadros acima da lista (KPIs, Resumo Consolidado, Cobertura Orçamentária)
    ficavam presos ao valor original da planilha mesmo depois de uma edição inline no
    cartão — eles são calculados a partir do DataFrame ANTES de `_render_card` desenhar os
    widgets, então uma edição só aparecia visualmente dentro do próprio cartão editado, nunca
    nos totais acima. Lê `st.session_state` diretamente (não chama os widgets de novo — isso
    duplicaria a key), então precisa vir depois de pelo menos uma renderização anterior dos
    cartões para ter efeito (na primeira execução da sessão, `session_state` ainda não tem
    nada e o resultado é idêntico ao original).
    """

    resultado = dataframe.copy()
    for indice, id_programa in zip(resultado.index, resultado["id"]):
        k = f"bls_{source_key}_{id_programa}"
        for sufixo, coluna in _CAMPOS_EDITAVEIS_NUMERICOS.items():
            valor = st.session_state.get(f"{k}_{sufixo}")
            if valor is not None:
                if coluna in ("qtd_efetiva", "valor_unitario"):
                    anterior = resultado.at[indice, coluna]
                    if pd.isna(anterior) or float(valor) != float(anterior):
                        resultado.at[indice, "valor_mensal_excepcional"] = pd.NA
                resultado.at[indice, coluna] = valor
        for sufixo, coluna in _CAMPOS_EDITAVEIS_TEXTO.items():
            valor = st.session_state.get(f"{k}_{sufixo}")
            if valor is not None:
                resultado.at[indice, coluna] = valor if valor != "" else pd.NA
        situacao = st.session_state.get(f"{k}_situacao")
        if situacao is not None:
            resultado.at[indice, "situacao_tg"] = situacao

    # Mesma regra usada dentro do cartão (`_render_card`): o valor excepcional preservado da
    # origem prevalece enquanto quantidade/valor unitário não forem editados; nos demais casos,
    # vale a fórmula. Assim, os totais acima nunca divergem do que cada cartão mostra.
    valor_calculado = resultado["qtd_efetiva"] * resultado["valor_unitario"]
    resultado["valor_mensal"] = resultado["valor_mensal_excepcional"].fillna(valor_calculado)
    resultado["valor_anual"] = resultado["valor_mensal"] * resultado["meses_no_ano"]
    resultado["meses_a_empenhar"], resultado["valor_a_empenhar"] = calcular_necessidade_empenho(
        resultado["meses_empenhados"], resultado["meses_liquidados"], resultado["valor_mensal"]
    )
    return resultado


# ---------------------------------------------------------------------- página
_inject_css()

anos = anos_disponiveis()
if not anos:
    st.warning(
        "Nenhum exercício cadastrado ainda no cadastro nativo de Bolsas e Auxílios "
        f"('{Path('data/bolsas_auxilios')}'). Rode a migração única a partir da planilha "
        "(`bolsas_auxilios_cadastro.migrar_de_planilha`) para criar o primeiro exercício."
    )
    st.stop()

ano_key = "bolsas_auxilios_ano_selecionado"
if st.session_state.get(ano_key) not in anos:
    st.session_state[ano_key] = max(anos)
ano_selecionado = st.session_state[ano_key]
source_key = str(ano_selecionado)

# Seletor de exercício — no topo da página, acima do título/Relatório/Novo programa (pedido
# explícito). Discreto: um botão por ano cadastrado (o selecionado em destaque), largura de
# coluna estreita (não `st.columns` de partes iguais — ficaria esticado) + um único menu "⋮"
# (pop-up, pedido explícito: "junte duplicar e excluir dentro de um menu") reunindo "Duplicar"
# (sempre do exercício mais recente para o próximo — generaliza "gerar 2028, 2029..." sem
# precisar estar vendo o ano mais recente) e "Excluir exercício" com uma caixa de seleção do
# ano a apagar (pedido explícito: "o botão excluir deve permitir a gente selecionar o ano"),
# em vez de só o ano em tela. O exercício mais antigo (migrado da planilha original) nunca
# aparece como opção de exclusão.
cols_ano = st.columns([1] * (len(anos) + 1) + [10])
for coluna, ano in zip(cols_ano, anos):
    if coluna.button(
        str(ano), key=f"bls_ano_{ano}",
        type="primary" if ano == ano_selecionado else "secondary", use_container_width=True,
    ):
        st.session_state[ano_key] = ano
        st.rerun()

origem_duplicar = max(anos)
destino_duplicar = origem_duplicar + 1
anos_excluiveis = [ano for ano in anos if ano != min(anos)]
with cols_ano[len(anos)]:
    with st.popover("⋮", help="Duplicar ou excluir um exercício", use_container_width=True):
        if st.button(
            f"Duplicar {origem_duplicar} → {destino_duplicar}",
            key=f"bls_duplicar_{destino_duplicar}", use_container_width=True,
            help="Copia identidade/classificação dos programas; execução fica em branco.",
        ):
            duplicar_exercicio(origem_duplicar, destino_duplicar)
            st.session_state[ano_key] = destino_duplicar
            st.success(f"Exercício {destino_duplicar} criado a partir de {origem_duplicar}.")
            st.rerun()

        if anos_excluiveis:
            st.markdown("---")
            ano_excluir = st.selectbox(
                "Excluir exercício", anos_excluiveis, key=f"bls_excluir_exercicio_escolha_{source_key}",
            )
            confirmar_exercicio_key = f"bls_confirmar_excluir_exercicio_{ano_excluir}"
            if st.session_state.get(confirmar_exercicio_key):
                if st.button(
                    f"Confirmar exclusão de {ano_excluir}?", key=f"bls_excluir_exercicio_confirmar_{ano_excluir}",
                    use_container_width=True, type="primary",
                ):
                    excluir_exercicio(ano_excluir)
                    st.session_state.pop(confirmar_exercicio_key, None)
                    if ano_excluir == ano_selecionado:
                        st.session_state[ano_key] = max(a for a in anos if a != ano_excluir)
                    st.success(f"Exercício {ano_excluir} excluído.")
                    st.rerun()
            else:
                if st.button(f"Excluir {ano_excluir}", key=f"bls_excluir_exercicio_{ano_excluir}", use_container_width=True):
                    st.session_state[confirmar_exercicio_key] = True
                    st.rerun()

col_titulo, col_relatorio, col_novo = st.columns([4, 1.4, 1])
with col_titulo:
    render_page_header(
        "Bolsas e Auxílios",
        "Necessidade de reforço de empenho por programa de bolsa/auxílio, cruzado com a Execução Mensal.",
        "Bolsas",
    )
with col_novo:
    st.write("")
    _render_novo_programa(ano_selecionado, source_key)

manifesto_execucao_mensal = ManifestoExecucaoMensal.atual()
if manifesto_execucao_mensal is None:
    st.info(
        "Nenhuma base de Execução Mensal foi importada ainda — é dela que vem o saldo "
        "autoritativo por NE. Importe a Execução Mensal antes de usar esta página."
    )
    st.stop()

caminho_ponteiro_execucao_mensal = DIRETORIO_MANIFESTOS_EXECUCAO_MENSAL / NOME_PONTEIRO_EXECUCAO_MENSAL

try:
    registros = carregar_programas(ano_selecionado)
    dataframe = como_dataframe(registros)
    por_ne_execucao = _cached_por_ne_execucao(
        str(caminho_ponteiro_execucao_mensal), caminho_ponteiro_execucao_mensal.stat().st_mtime
    )
except Exception as error:
    st.error(f"Não foi possível ler os dados: {error}")
    st.stop()

# Linha do tempo mensal (pop-up "Linha do tempo mensal" do Resumo Consolidado) usa a MESMA
# base já carregada acima para o saldo — reaproveita o manifesto já confirmado presente.
tempo_por_ne_curta: pd.DataFrame | None = None
if manifesto_execucao_mensal is not None:
    try:
        tempo_por_ne_curta = _cached_linha_do_tempo(
            str(caminho_ponteiro_execucao_mensal), manifesto_execucao_mensal.sha256
        )
    except Exception:
        tempo_por_ne_curta = None

# Dotação Anual, para o quadro "Cobertura Orçamentária por PTRES" — diferente da Execução
# Anual (obrigatória acima), essa base é só um complemento: sem ela, o quadro não aparece,
# mas o resto da tela (cartões, resumo, saldo via Execução) continua funcionando normal.
dotacao_dimensoes = None
ano_exercicio_dotacao = None
manifesto_dotacao = ManifestoDotacao.atual()
if manifesto_dotacao is not None:
    caminho_ponteiro_dotacao = DIRETORIO_MANIFESTOS_PADRAO / NOME_PONTEIRO_DOTACAO
    try:
        dotacao_dimensoes, ano_exercicio_dotacao = _cached_dotacao_por_ptres(
            str(caminho_ponteiro_dotacao), caminho_ponteiro_dotacao.stat().st_mtime
        )
    except Exception:
        dotacao_dimensoes = None

dataframe = _aplicar_edicoes_da_sessao(dataframe, source_key)
dataframe = com_saldo_execucao(dataframe, por_ne_execucao)

# "Início da Execução" (mês do primeiro empenho de cada NE, auto-detectado da base mensal) e
# valor empenhado autoritativo — só para a sugestão inicial "por calendário" do Relatório de
# Reforço (pedido explícito, ver `src.necessidade_empenho.necessidade_ate_mes_vigente`);
# nenhum outro quadro da página usa essas duas colunas.
if tempo_por_ne_curta is not None:
    sugestao_inicio_por_ne = primeiro_mes_com_empenho_por_ne(tempo_por_ne_curta)
else:
    sugestao_inicio_por_ne = pd.Series(dtype="Int64")
dataframe["valor_empenhado_autoritativo"] = dataframe["valor_empenhado_execucao"].fillna(dataframe["valor_empenhado_tg"])
# mesmo padrão de fallback do Resumo Consolidado (`_render_resumo_consolidado`) — autoritativo
# (Execução Mensal) com o valor colado na planilha como reserva. Usado só para evidenciar o
# saldo na tela do Relatório de Reforço/Anulação (pedido explícito), nenhum outro quadro usa.
dataframe["saldo_autoritativo"] = dataframe["saldo_execucao"].fillna(dataframe["saldo_colado_planilha"])
dataframe["inicio_execucao_efetivo"] = dataframe["inicio_execucao_mes"].fillna(
    dataframe["ne_curta"].map(sugestao_inicio_por_ne)
)

with col_relatorio:
    st.write("")
    render_botao_relatorio(dataframe, RELATORIO_BOLSAS_AUXILIOS, f"bolsas_{ano_selecionado}", ano_selecionado)

busca = st.text_input(
    "Buscar",
    key=f"bolsas_auxilios_busca_{source_key}",
    placeholder="Processo, programa, unidade, ação, PI, NE…",
)
filtrado = _aplicar_busca(dataframe, busca)

if filtrado.empty:
    if dataframe.empty:
        st.info(
            f"Nenhum programa cadastrado no exercício {ano_selecionado} ainda. Use "
            "'+ Novo programa' ou, se este for o exercício mais recente, 'Duplicar cadastro' "
            "acima para partir do exercício anterior."
        )
    else:
        st.warning("Nenhum registro corresponde à busca informada.")
    st.stop()

render_metric_grid(
    [
        {"label": "Despesa Anual Total", "value": format_brl_compact(filtrado["valor_anual"].sum())},
        {"label": "Valor Mensal", "value": format_brl_compact(filtrado["valor_mensal"].sum())},
        # "Necessidade de Reforço" saiu daqui (pedido explícito) — `valor_a_empenhar`, quando a
        # NE já vem da Execução Mensal, é matematicamente igual a `saldo_execucao`
        # (empenhado − liquidado nos dois, só chegando lá por contas diferentes — ver
        # `com_saldo_execucao`), então os dois cartões sempre mostravam o mesmo número. No
        # lugar, "Bolsas Ativas" soma `qtd_efetiva` (QUANT. EFETIVA DE BOLSAS da origem — já é,
        # por definição, a quantidade atual/em vigor, diferente de `qtd_inicial`), não uma
        # contagem de programas/linhas.
        {"label": "Bolsas Ativas", "value": str(int(filtrado["qtd_efetiva"].sum()))},
        {"label": "Programas", "value": str(len(filtrado))},
        {"label": "Saldo (Execução Mensal)", "value": format_brl_compact(_somar_unico_por_ne(filtrado, "saldo_execucao"))},
    ],
    columns=5,
)

_render_resumo_consolidado(filtrado, tempo_por_ne_curta, source_key)

if dotacao_dimensoes is not None:
    st.subheader("Cobertura Orçamentária por PTRES")
    _render_quadro_dotacao(filtrado, dotacao_dimensoes, ano_exercicio_dotacao)
else:
    st.info(
        "Nenhuma base de Dotação Anual foi importada ainda — o quadro de cobertura "
        "orçamentária por PTRES depende dela. Importe a Dotação Anual para vê-lo aqui."
    )

st.subheader("Programas, bolsas e auxílios")
st.caption("🟢 Atualizado · 🟡 Necessita reforço de empenho · 🔴 Sem empenho / Não localizado")

# minimizada por padrão (pedido explícito) — só QTD_INICIAL_LISTA (5) cartões de início,
# "Ver mais" revela o resto de uma vez, "Ver menos" devolve ao estado minimizado — mesmo
# padrão de app_pages/contratos_continuos.py::"Carteira de contratos" (lá o limite é 3, aqui
# foi pedido 5).
QTD_INICIAL_LISTA = 5
mostrar_todos_lista_key = f"bl_lista_mostrar_todos_{source_key}"
mostrar_todos_lista = st.session_state.get(mostrar_todos_lista_key, False)
visiveis_lista = filtrado if mostrar_todos_lista else filtrado.iloc[:QTD_INICIAL_LISTA]

with st.container(key="bl_lista"):
    for _, linha in visiveis_lista.iterrows():
        _render_card(linha, ano_selecionado, source_key, sugestao_inicio_por_ne)

if not mostrar_todos_lista and len(filtrado) > QTD_INICIAL_LISTA:
    st.caption(f"Mostrando {QTD_INICIAL_LISTA} de {len(filtrado)} programas")
    if st.button("Ver mais", key=f"bl_lista_ver_mais_{source_key}"):
        st.session_state[mostrar_todos_lista_key] = True
        st.rerun()
elif len(filtrado):
    st.caption(f"Mostrando todos os {len(filtrado)} programas")
    if len(filtrado) > QTD_INICIAL_LISTA and st.button("Ver menos", key=f"bl_lista_ver_menos_{source_key}"):
        st.session_state[mostrar_todos_lista_key] = False
        st.rerun()

st.caption(
    "Cadastro nativo de Bolsas e Auxílios (não depende mais de planilha) — uma linha por "
    "programa de bolsa/auxílio, não por bolsista individual (o cadastro não guarda nome/CPF "
    "de beneficiário). Saldo Execução vem da Execução Mensal do projeto, cruzado pela NE. "
    f"Exercício em tela: {ano_selecionado}. Edição de cartão só é gravada ao clicar em "
    "'💾 Salvar'; '+ Novo programa' e 'Remover' gravam/apagam de imediato."
)
