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

Cada programa é uma LINHA do "Registro de programas" (ver REPAGINAÇÃO abaixo); a edição de
todos os campos acontece numa janela (`_dialogo_editar_programa`) e só é gravada ao clicar em
"Salvar" — o resumo, os KPIs e a Cobertura Orçamentária por PTRES sempre refletem o cadastro gravado.
A divergência financeira explicitamente preservada da migração (`valor_mensal_excepcional`)
prevalece sobre a fórmula de quantidade × valor unitário até um desses dois campos ser editado
e salvo (`como_dataframe`, em `src/bolsas_auxilios_cadastro.py`, já calcula
`valor_mensal`/`valor_anual`/`meses_a_empenhar`/`valor_a_empenhar`).

CORREÇÃO DA NECESSIDADE (05/10/2026): a "Necessidade até Dezembro" do Resumo Consolidado e do
cartão-resumo deixou de subtrair o saldo — ele já está dentro do empenhado, e a regra anterior o
descontava duas vezes (mesma correção feita em Contratos Contínuos em 02/10/2026). Agora é
`valor mensal × meses restantes`, o que falta empenhar para cobrir o exercício
(`src/necessidade_empenho.py::necessidade_ate_dezembro`); o saldo segue exibido na coluna "Saldo".

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
  * REPAGINAÇÃO DO CADASTRO (pedido explícito, 05/10/2026: "muita cara de planilha", seguindo o
    layout de referência): o topo vira um cartão-resumo com faixa de destaque e grade de
    indicadores; a antiga lista de programas (cartões-expansores de campos soltos) vira o "Registro
    de programas" — abas de situação com contagem (Todos, Atualizado, Necessita reforço, Sem empenho,
    Não localizado), filtro de ação, ordenação, linhas com título/subtítulo, valores à direita,
    situação em chip e ações por ícone. Componentes visuais em `src/ui_cadastro.py` (compartilhados
    com `contratos_continuos.py`). Os dados e as regras não mudaram.
  * O card "Resumo Consolidado" NÃO é um `st.dataframe` (cara de planilha). Layout de 05/10/2026
    ("aplique o mesmo layout para a Cobertura Orçamentária por PTRES, EMPENHADO × LIQUIDADO e RESUMO
    CONSOLIDADO"): cartão branco arredondado (`st.container(border=True, key="cad_secao_resumo_bls_*")`,
    estilo em `src/ui_cadastro.py`) com kicker, título e destaque à direita; cada linha é um
    `st.columns` com título/subtítulo, valores à direita e, quando a NE tem dado mensal, um botão de
    ÍCONE para a "Linha do tempo mensal" (mesmas chaves de antes). A "Cobertura Orçamentária por PTRES"
    usa `cartao_cobertura_ptres`. Lista uma
    linha por bolsa (não um total único) e usa `valor_mensal × meses ainda devidos no ano`
    (`meses_no_ano − meses já empenhados, nunca calendário puro — ver
    `_render_resumo_consolidado`, corrigido depois de um bug real: bolsa "parcela única" já
    paga continuava pedindo reforço só por causa do calendário) para a "Necessidade até
    Dezembro". Ela não substitui nem se confunde com "Empenhar" por cartão (que continua vindo
    de `meses_empenhados − meses_liquidados`, ver bullet acima): "Empenhar" mede atraso já
    ocorrido; "Necessidade até Dezembro" projeta o gasto restante do exercício.
  * Os tokens de cor/tipografia são os reais do projeto (`src/design_tokens.py`), não os do
    pacote de handoff.
  * Topo: cartão-resumo com a faixa "Necessidade de empenho até dezembro" (a mesma conta do
    Resumo Consolidado, `_necessidade_ate_dezembro`) e a grade Despesa anual, Valor mensal, Bolsas
    ativas, Programas, Empenhado e Saldo via Execução Mensal. "Beneficiários Efetivos", "Sem
    Empenho/Não Localizado" e "Saldo Divergente" saíram do topo por pedidos anteriores; a situação
    continua visível em cada linha do registro.
  * "Editar" abre uma janela (`@st.dialog`) com os mesmos campos em seções (Identificação,
    Classificação orçamentária, Quantidade e valores, Empenho e execução) e indicadores que
    recalculam ao vivo; só grava ao clicar em "Salvar". Por isso a antiga edição ao vivo na sessão
    (`_aplicar_edicoes_da_sessao`) deixou de existir: o resumo reflete o cadastro gravado.
  * "Remover" pede confirmação numa janela antes de apagar o programa em definitivo do cadastro
    nativo (pedido explícito de desvinculação de planilha tornou o cadastro a fonte de verdade).
    "Novo programa" é um botão principal no cabeçalho que abre uma janela com o formulário em seções;
    grava direto no cadastro nativo do exercício em tela (`src/bolsas_auxilios_cadastro.py`). Não
    tem nome/CPF de bolsista: a granularidade real da base é por programa, não por beneficiário.
  * O registro mostra 15 linhas (`QTD_INICIAL_REGISTRO`) e "Ver mais" revela todas num clique só
    (pedido explícito; antes eram +15 por clique), dentro de uma caixa com barra de rolagem.
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
from src.necessidade_empenho import calcular_necessidade_empenho, necessidade_ate_dezembro
from src.relatorio_reforco_empenho import BOLSAS_AUXILIOS as RELATORIO_BOLSAS_AUXILIOS
from src.tesouro_execucao_mensal import agregar_por_ne, linha_do_tempo_por_ne, primeiro_mes_com_empenho_por_ne
from src.ui_cadastro import (
    aviso_linha_do_tempo,
    cartao_cobertura_ptres,
    cartao_resumo,
    celula_categoria,
    celula_principal,
    celula_valor,
    chip,
    contagens_por_aba,
    formatar_brl,
    grade_indicadores,
    ordenar_por,
    topo_secao,
)
from src.ui_cadastro import css as css_cadastro
from src.ui_linha_do_tempo import BASE_LIQUIDADO_EXECUCAO_MENSAL, MESES_ABREV, abrir_linha_do_tempo
from src.ui_relatorio_reforco_empenho import render_botao_relatorio
from src.ui_theme import render_page_header

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
        </style>
        """,
        unsafe_allow_html=True,
    )


_OPCOES_INICIO_EXECUCAO = ["Automático"] + [MESES_ABREV[m] for m in range(1, 13)]


def _secao(titulo: str) -> None:
    """Título de seção dentro das janelas de edição (`.cad-secao-dialogo`, ver `src/ui_cadastro.py`)."""

    st.markdown(f'<div class="cad-secao-dialogo">{titulo}</div>', unsafe_allow_html=True)


def _campo_inicio_execucao(col, valor_persistido: object, sugestao_auto: object, key: str) -> int | None:
    """"Início da Execução" (mês 1-12) usado só pela sugestão "por calendário" do Relatório de
    Reforço (`necessidade_ate_mes_vigente`) — mesmo campo/critério de
    `app_pages/contratos_continuos.py::_campo_inicio_execucao` (pedido explícito): "Automático"
    (`None` persistido) usa `sugestao_auto` (mês do primeiro empenho daquela NE, detectado a
    partir da base mensal); selecionar um mês específico grava um override manual."""

    indice_atual = int(valor_persistido) if pd.notna(valor_persistido) else 0
    ajuda = (
        f"Detectado automaticamente pelo primeiro empenho: {MESES_ABREV[int(sugestao_auto)]}"
        if pd.notna(sugestao_auto)
        else "Sem dado suficiente na base mensal pra detectar automaticamente — informe o mês manualmente, se souber."
    )
    escolha = col.selectbox(
        "Início da execução (mês)", _OPCOES_INICIO_EXECUCAO, index=indice_atual, key=key, help=ajuda,
    )
    return None if escolha == "Automático" else _OPCOES_INICIO_EXECUCAO.index(escolha)


def _situacao_exibida(situacao_bruta: object, valor_a_empenhar: object) -> tuple[str, str]:
    """(texto, tom) do chip de situação da linha — a mesma leitura das antigas tags do cartão:
    sem empenho, não localizado, necessita reforço (valor a empenhar > 0) ou atualizado."""

    if pd.notna(situacao_bruta) and situacao_bruta == "SEM EMPENHO":
        return "Sem empenho", "bad"
    if pd.notna(situacao_bruta) and situacao_bruta == "NÃO LOCALIZADO":
        return "Não localizado", "bad"
    if _ou_zero(valor_a_empenhar) > 0:
        return "Necessita reforço", "warn"
    return "Atualizado", "ok"


@st.dialog("Editar programa", width="large")
def _dialogo_editar_programa(linha: pd.Series, ano: int, source_key: str, sugestao_inicio: object) -> None:
    """Janela de edição de um programa de bolsa/auxílio (substitui o antigo cartão-expansor de campos
    soltos — pedido de 05/10/2026: "muita cara de planilha"). Mesmos campos, mesmas chaves de widget
    e a mesma regra de gravação de antes, agora em seções: Identificação, Classificação
    orçamentária, Quantidade e valores, Empenho e execução. Os indicadores do topo recalculam ao
    vivo com o que está digitado; nada é gravado até "Salvar"."""

    id_programa = str(linha["id"])
    k = f"bls_{source_key}_{id_programa}"
    topo = st.container()  # preenchido no fim, com os valores já calculados dos campos abaixo

    _secao("Identificação")
    c_prog, c_sit = st.columns([2.2, 1])
    programa = c_prog.text_input("Item de despesa (programa)", value=_ou_vazio(linha["programa_bolsa"]), key=f"{k}_programa")
    situacao_bruta = linha["situacao_tg"]
    situacao_atual = situacao_bruta if pd.notna(situacao_bruta) and situacao_bruta in SITUACAO_OPCOES else "ATUALIZADO"
    situacao = c_sit.selectbox(
        "Situação TG", SITUACAO_OPCOES, index=SITUACAO_OPCOES.index(situacao_atual), key=f"{k}_situacao",
    )
    # `processo` é o processo de empenho (o que o Relatório de Reforço agrupa) — ver
    # `src/bolsas_auxilios_cadastro.py::CAMPOS_IDENTIDADE`; o da contratação é campo à parte.
    c_proc_emp, c_proc_contr = st.columns(2)
    processo = c_proc_emp.text_input("Processo de empenho", value=_ou_vazio(linha["processo"]), key=f"{k}_processo")
    processo_contratacao = c_proc_contr.text_input(
        "Processo da contratação", value=_ou_vazio(linha["processo_contratacao"]), key=f"{k}_processo_contratacao",
    )

    _secao("Classificação orçamentária")
    q = st.columns(7)
    unidade = q[0].text_input("Unidade", value=_ou_vazio(linha["unidade_cod"]), key=f"{k}_unidade")
    acao = q[1].text_input("Ação", value=_ou_vazio(linha["acao_cod"]), key=f"{k}_acao")
    ptres = q[2].text_input("PTRES", value=_ou_vazio(linha["ptres"]), key=f"{k}_ptres")
    fonte = q[3].text_input("Fonte", value=_ou_vazio(linha["fonte_cod"]), key=f"{k}_fonte")
    nd = q[4].text_input("ND", value=_ou_vazio(linha["natureza_despesa_cod"]), key=f"{k}_nd")
    ugr = q[5].text_input("UGR", value=_ou_vazio(linha["ugr_cod"]), key=f"{k}_ugr")
    pi = q[6].text_input("PI", value=_ou_vazio(linha["pi_cod"]), key=f"{k}_pi")

    _secao("Quantidade e valores")
    v = st.columns(4)
    qtd_inicial = v[0].number_input(
        "Qtd. inicial", value=int(_ou_zero(linha["qtd_inicial"])), step=1, min_value=0, format="%d", key=f"{k}_qtdinicial",
    )
    qtd_efetiva = v[1].number_input(
        "Qtd. efetiva", value=int(_ou_zero(linha["qtd_efetiva"])), step=1, min_value=0, format="%d", key=f"{k}_qtdefetiva",
    )
    # sem min_value=0.0 daqui pra baixo: meses_empenhados/liquidados (e valores monetários) podem vir
    # negativos na origem (anulação/ajuste retroativo); um piso de zero quebraria a leitura desse dado.
    valor_unitario = v[2].number_input(
        "Valor unit. (R$)", value=float(_ou_zero(linha["valor_unitario"])), step=10.0, key=f"{k}_valorunit",
    )
    meses_no_ano = v[3].number_input(
        "Meses/ano", value=int(_ou_zero(linha["meses_no_ano"]) or 12), step=1, min_value=1, format="%d", key=f"{k}_mesesano",
    )

    _secao("Empenho e execução")
    e = st.columns(4)
    ne_curta = e[0].text_input("Empenho (NE)", value=_ou_vazio(linha["ne_curta"]), key=f"{k}_ne")

    # Empenhado/Saldo: com NE já encontrada na Execução Mensal, o valor autoritativo aparece nos
    # indicadores do topo (não editável) em vez do valor colado na planilha; sem NE encontrada, o campo
    # continua editável a partir da planilha (fallback inalterado).
    valor_empenhado_execucao = linha["valor_empenhado_execucao"]
    via_execucao_valor_empenhado = pd.notna(valor_empenhado_execucao)
    if via_execucao_valor_empenhado:
        valor_empenhado_tg_persistir = _ou_zero(linha["valor_empenhado_tg"])
    else:
        valor_empenhado_tg_persistir = e[1].number_input(
            "Empenhado (R$)", value=float(_ou_zero(linha["valor_empenhado_tg"])), step=100.0, key=f"{k}_valorempenhado",
        )

    saldo_execucao = linha["saldo_execucao"]
    via_execucao_saldo = pd.notna(saldo_execucao)
    if via_execucao_saldo:
        saldo_colado_planilha_persistir = _ou_zero(linha["saldo_colado_planilha"])
    else:
        saldo_colado_planilha_persistir = e[2].number_input(
            "Saldo (R$)", value=float(_ou_zero(linha["saldo_colado_planilha"])), step=100.0, key=f"{k}_saldo",
        )

    sugestao_inicio_mes = _campo_inicio_execucao(e[3], linha["inicio_execucao_mes"], sugestao_inicio, f"{k}_inicio")

    # Com NE já encontrada na Execução Mensal, os campos manuais de meses viram exibição (ver
    # `com_saldo_execucao`): digitar ali deixaria de ter efeito no "Empenhar" mostrado.
    via_execucao = pd.notna(linha["meses_empenhados_execucao"])
    if via_execucao:
        meses_empenhados = float(linha["meses_empenhados_execucao"])
        meses_liquidados = float(linha["meses_liquidados_execucao"])
        meses_empenhados_persistir = _ou_zero(linha["meses_empenhados"])
        meses_liquidados_persistir = _ou_zero(linha["meses_liquidados"])
    else:
        m = st.columns(4)
        meses_empenhados = m[0].number_input(
            "Meses empenhados", value=float(_ou_zero(linha["meses_empenhados"])), step=0.1, key=f"{k}_mesesemp",
        )
        meses_liquidados = m[1].number_input(
            "Meses liquidados", value=float(_ou_zero(linha["meses_liquidados"])), step=0.1, key=f"{k}_mesesliq",
        )
        meses_empenhados_persistir = meses_empenhados
        meses_liquidados_persistir = meses_liquidados

    valor_mensal_excepcional = linha.get("valor_mensal_excepcional")
    valor_mensal = (
        float(valor_mensal_excepcional) if pd.notna(valor_mensal_excepcional) else qtd_efetiva * valor_unitario
    )
    meses_a_empenhar, valor_a_empenhar = calcular_necessidade_empenho(meses_empenhados, meses_liquidados, valor_mensal)

    rotulo_valor_mensal = "Valor mensal (informado)" if pd.notna(valor_mensal_excepcional) else "Valor mensal"
    rotulo_empenhar = "A empenhar (Execução Mensal)" if via_execucao else "A empenhar (planilha)"
    with topo:
        st.markdown(
            grade_indicadores([
                (rotulo_empenhar, formatar_brl(valor_a_empenhar)),
                (rotulo_valor_mensal, formatar_brl(valor_mensal)),
                ("Valor anual", formatar_brl(valor_mensal * meses_no_ano)),
                ("Empenhado (Execução Mensal)", formatar_brl(valor_empenhado_execucao) if via_execucao_valor_empenhado else "sem NE"),
                ("Saldo (Execução Mensal)", formatar_brl(saldo_execucao) if via_execucao_saldo else "sem NE"),
                ("Meses de saldo", _num(meses_a_empenhar)),
            ]),
            unsafe_allow_html=True,
        )

    texto_situacao, tom_situacao = _situacao_exibida(situacao, valor_a_empenhar)
    # Sem "Diverge": Saldo/Empenhado exibem o valor da Execução Mensal diretamente quando ela tem a NE.
    if via_execucao_saldo or via_execucao_valor_empenhado:
        texto_exec, tom_exec = "Via Execução Mensal", "ok"
    else:
        texto_exec, tom_exec = "Sem Execução", "warn"

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    f_chips, f_salvar, f_cancelar = st.columns([3, 1, 1], vertical_alignment="center")
    f_chips.markdown(chip(texto_situacao, tom_situacao) + " " + chip(texto_exec, tom_exec), unsafe_allow_html=True)
    if f_cancelar.button("Cancelar", key=f"{k}_cancelar", use_container_width=True):
        st.rerun()
    if f_salvar.button("Salvar", key=f"{k}_salvar", type="primary", icon=":material/save:", use_container_width=True):
        atualizado = {
            **linha.to_dict(),
            "processo": processo or None, "processo_contratacao": processo_contratacao.strip() or None,
            "programa_bolsa": programa or None,
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
            "inicio_execucao_mes": sugestao_inicio_mes,
        }
        for chave_extra in (
            "valor_mensal", "valor_anual", "meses_a_empenhar", "valor_a_empenhar", "saldo_execucao",
            "valor_empenhado_execucao", "valor_liquidado_execucao", "diverge_saldo", "diverge_valor_empenhado",
            "meses_empenhados_execucao", "meses_liquidados_execucao", "necessidade_via",
            "inicio_execucao_efetivo", "valor_empenhado_autoritativo",
        ):
            atualizado.pop(chave_extra, None)
        atualizar_programa(ano, atualizado)
        st.toast("Programa salvo.", icon=":material/check_circle:")
        st.rerun()


@st.dialog("Remover programa")
def _dialogo_remover_programa(id_programa: str, rotulo: str, ano: int) -> None:
    """Confirmação de remoção (substitui o antigo "Remover" + "Confirmar exclusão?" do cartão).
    Remover apaga o registro do cadastro do exercício; não há como desfazer."""

    st.markdown(f"Remover **{rotulo}** do exercício {ano}?")
    st.caption("O registro é apagado do cadastro deste exercício. Não há como desfazer.")
    c_confirmar, c_cancelar = st.columns(2)
    if c_cancelar.button("Cancelar", key=f"bls_remover_cancelar_{id_programa}", use_container_width=True):
        st.rerun()
    if c_confirmar.button("Remover", key=f"bls_remover_confirmar_{id_programa}", type="primary", use_container_width=True):
        excluir_programa(ano, id_programa)
        st.toast("Programa removido.", icon=":material/delete:")
        st.rerun()


@st.dialog("Novo programa", width="large")
def _dialogo_novo_programa(ano: int, source_key: str) -> None:
    """Formulário de "+ Novo programa" em janela, organizado em seções (era um popover estreito com
    16 campos empilhados). Grava direto no cadastro nativo do exercício em tela
    (`src/bolsas_auxilios_cadastro.py`), sobrevive a fechar o navegador."""

    with st.form(f"bolsas_auxilios_form_{source_key}", clear_on_submit=True, border=False):
        _secao("Identificação")
        programa = st.text_input("Item de despesa (programa)")
        c1, c2 = st.columns(2)
        processo = c1.text_input("Processo de empenho")
        processo_contratacao = c2.text_input("Processo da contratação")

        _secao("Classificação orçamentária")
        q = st.columns(7)
        unidade = q[0].text_input("Unidade")
        acao = q[1].text_input("Ação")
        ptres = q[2].text_input("PTRES")
        fonte = q[3].text_input("Fonte", value="1000")
        nd = q[4].text_input("ND", value="339018")
        ugr = q[5].text_input("UGR")
        pi = q[6].text_input("PI")

        _secao("Quantidade e valores")
        v = st.columns(4)
        meses_no_ano = v[0].number_input("Meses no ano", min_value=1, max_value=12, value=12)
        qtd_inicial = v[1].number_input("Qtd. inicial", min_value=0, step=1)
        qtd_efetiva = v[2].number_input("Qtd. efetiva", min_value=0, step=1)
        valor_unitario = v[3].number_input("Valor unitário (R$)", min_value=0.0, step=10.0)

        _secao("Empenho e execução")
        e = st.columns(3)
        ne_curta = e[0].text_input("NE (opcional)", placeholder="ex. 2026NE000999")
        valor_empenhado = e[1].number_input("Valor empenhado (R$)", min_value=0.0, step=100.0)
        saldo_colado = e[2].number_input("Saldo colado na planilha (R$)", min_value=0.0, step=100.0)
        m = st.columns(3)
        meses_empenhados = m[0].number_input("Meses empenhados", min_value=0.0, step=0.1)
        meses_liquidados = m[1].number_input("Meses liquidados", min_value=0.0, step=0.1)

        if st.form_submit_button("Adicionar programa", type="primary", icon=":material/add:"):
            if not programa or not qtd_efetiva or not valor_unitario:
                st.error("Informe ao menos o item de despesa, quantidade efetiva e valor unitário.")
            else:
                registro = novo_programa(
                    processo=processo or "—", processo_contratacao=processo_contratacao.strip() or None,
                    programa_bolsa=programa, unidade_cod=unidade,
                    acao_cod=acao, ptres=ptres, fonte_cod=fonte, natureza_despesa_cod=nd,
                    ugr_cod=ugr, pi_cod=pi, ne_curta=ne_curta.strip() or None,
                    meses_no_ano=meses_no_ano, qtd_inicial=qtd_inicial, qtd_efetiva=qtd_efetiva,
                    valor_unitario=valor_unitario, valor_empenhado_tg=valor_empenhado,
                    saldo_colado_planilha=saldo_colado, situacao_tg="SEM EMPENHO",
                    meses_empenhados=meses_empenhados, meses_liquidados=meses_liquidados,
                )
                salvar_programa(ano, registro)
                st.toast("Programa cadastrado.", icon=":material/check_circle:")
                st.rerun()


def _render_novo_programa(ano: int, source_key: str) -> None:
    """Botão principal "Novo programa" (canto do cabeçalho), que abre `_dialogo_novo_programa`."""

    with st.container(key="cad_novo"):
        if st.button("Novo programa", icon=":material/add:", type="primary", use_container_width=True, key=f"bls_novo_{source_key}"):
            _dialogo_novo_programa(ano, source_key)


#: larguras relativas usadas por `st.columns` no cabeçalho de rótulos, em cada linha e no
#: rodapé do Resumo Consolidado — as três precisam ser exatamente as mesmas pra alinhar. A última
#: coluna é o botão de ícone da "Linha do tempo mensal".
_LARGURAS_RESUMO = [3.0, 1.2, 1.2, 1.2, 1.3, 0.8]
_CABECALHOS_RESUMO = [
    ("Programa / Processo", False), ("Valor mensal", True), ("Valor empenhado", True),
    ("Saldo", True), ("Necessidade até dez.", True), ("Linha do tempo", False),
]


def _necessidade_ate_dezembro(filtrado: pd.DataFrame) -> pd.DataFrame:
    """Necessidade até Dezembro de cada programa (regra do "Resumo Consolidado", extraída para ser a
    MESMA no cartão-resumo do topo): devolve `filtrado` com `_valor_mensal`, `_valor_empenhado` e
    `_necessidade`. Não altera a entrada."""

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
    #
    # CORREÇÃO (05/10/2026, "pode seguir com o ajuste da parte de bolsas"): a conta NÃO subtrai mais o
    # saldo (empenhado − liquidado) — ele já está dentro do empenhado, e abatê-lo de novo descontava o
    # mesmo valor duas vezes (mesma correção feita em Contratos Contínuos em 02/10/2026). O saldo continua
    # exibido na coluna "Saldo". Regra em `src.necessidade_empenho.necessidade_ate_dezembro`.
    _, empenhar_ate_fim = necessidade_ate_dezembro(valor_mensal, valor_empenhado_exibido, filtrado["meses_no_ano"])

    return filtrado.assign(
        _necessidade=empenhar_ate_fim, _valor_empenhado=valor_empenhado_exibido, _valor_mensal=valor_mensal
    )


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

    calculado = _necessidade_ate_dezembro(filtrado)
    valor_mensal = calculado["_valor_mensal"]
    valor_empenhado_exibido = calculado["_valor_empenhado"]
    empenhar_ate_fim = calculado["_necessidade"]
    ordenado = calculado.sort_values("_necessidade", ascending=False)
    necessidade_total = empenhar_ate_fim.sum()
    nes_com_tempo = set(tempo_por_ne_curta["ne_curta"]) if tempo_por_ne_curta is not None else set()
    aviso_tempo = aviso_linha_do_tempo(filtrado["ne_curta"], nes_com_tempo, tempo_por_ne_curta is not None)

    with st.container(border=True, key=f"cad_secao_resumo_bls_{source_key}"):
        st.markdown(
            topo_secao(
                "Necessidade de Empenho por Bolsa",
                None,
                {
                    "rotulo": "Necessidade até dezembro",
                    "valor": formatar_brl(necessidade_total),
                    "detalhe": f"{len(filtrado)} {'bolsa' if len(filtrado) == 1 else 'bolsas'}",
                    "tom": "warn" if necessidade_total > 0 else "ok",
                },
                kicker="RESUMO CONSOLIDADO",
            ),
            unsafe_allow_html=True,
        )
        if aviso_tempo:
            st.caption(aviso_tempo)
        cabecalho = st.columns(_LARGURAS_RESUMO)
        for coluna, (texto, a_direita) in zip(cabecalho, _CABECALHOS_RESUMO):
            coluna.markdown(
                f'<div class="cad-cabecalho{" direita" if a_direita else ""}">{texto}</div>', unsafe_allow_html=True
            )

        # Rolagem (pedido explícito) em vez de "Ver mais" — poucas bolsas visíveis por padrão (caixa de altura
        # fixa, `.st-key-bls_resumo_scroll` em `src/ui_cadastro.py`); com poucas bolsas no recorte o conteúdo nem
        # chega a estourar a altura e a barra de rolagem simplesmente não aparece.
        with st.container(key="bls_resumo_scroll"):
            for _, row in ordenado.iterrows():
                ne_curta_bolsa = row.get("ne_curta")
                clicavel = pd.notna(ne_curta_bolsa) and ne_curta_bolsa in nes_com_tempo
                processo = _ou_vazio(row["processo"])
                subtitulo = " · ".join(
                    parte for parte in (f"Processo {processo}" if processo else "", f"NE {ne_curta_bolsa}" if pd.notna(ne_curta_bolsa) else "sem NE") if parte
                )
                with st.container(key=f"cad_linha_resumo_bls_{source_key}_{row['id']}"):
                    linha = st.columns(_LARGURAS_RESUMO, vertical_alignment="center")
                    linha[0].markdown(
                        celula_principal(_ou_vazio(row["programa_bolsa"]) or "(sem item de despesa)", subtitulo), unsafe_allow_html=True
                    )
                    linha[1].markdown(celula_valor(row["_valor_mensal"]), unsafe_allow_html=True)
                    linha[2].markdown(celula_valor(row["_valor_empenhado"], vazio="sem NE"), unsafe_allow_html=True)
                    linha[3].markdown(celula_valor(row["saldo_execucao"], vazio="sem NE"), unsafe_allow_html=True)
                    linha[4].markdown(
                        celula_valor(row["_necessidade"], "warn" if _ou_zero(row["_necessidade"]) > 0 else None), unsafe_allow_html=True
                    )
                    if clicavel and linha[5].button(
                        "", icon=":material/show_chart:", key=f"bls_resumo_tempo_{source_key}_{row['id']}",
                        help="Abrir a linha do tempo mensal desta NE", use_container_width=True,
                    ):
                        tempo_ne = tempo_por_ne_curta[tempo_por_ne_curta["ne_curta"] == ne_curta_bolsa]
                        legenda = f"{_dash(row['programa_bolsa'])} (NE {ne_curta_bolsa}) — Execução Mensal (BI CPOC)."
                        abrir_linha_do_tempo(legenda, tempo_ne, BASE_LIQUIDADO_EXECUCAO_MENSAL)

        with st.container(key=f"cad_total_resumo_bls_{source_key}"):
            rodape = st.columns(_LARGURAS_RESUMO)
            rodape[0].markdown('<div class="cad-total-rotulo">Total</div>', unsafe_allow_html=True)
            rodape[1].markdown(celula_valor(valor_mensal.sum()), unsafe_allow_html=True)
            rodape[2].markdown(celula_valor(valor_empenhado_exibido.sum()), unsafe_allow_html=True)
            rodape[3].markdown(celula_valor(_somar_unico_por_ne(filtrado, "saldo_execucao"), vazio="sem NE"), unsafe_allow_html=True)
            rodape[4].markdown(
                celula_valor(necessidade_total, "warn" if necessidade_total > 0 else None), unsafe_allow_html=True
            )


def _render_card_dotacao(codigo: object, nome: object, grupo: pd.DataFrame) -> None:
    """Um cartão por Ação de Governo, com uma linha por Plano Orçamentário/PTRES — montagem do HTML em
    `src/ui_cadastro.py::cartao_cobertura_ptres`, compartilhada com `contratos_continuos.py` (layout de 05/10/2026)."""

    st.markdown(cartao_cobertura_ptres(codigo, nome, grupo), unsafe_allow_html=True)


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


# ---------------------------------------------------------------------- página
_inject_css()
st.markdown(css_cadastro(), unsafe_allow_html=True)

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

# Cartão-resumo do topo (pedido de 05/10/2026, layout de referência): faixa de destaque com a
# Necessidade até Dezembro — a MESMA conta do "Resumo Consolidado" (`_necessidade_ate_dezembro`) — e a
# grade de indicadores do exercício. Substitui a antiga linha de 5 métricas.
_necessidade_topo = _necessidade_ate_dezembro(filtrado)
_necessidade_topo_total = float(_necessidade_topo["_necessidade"].sum())
st.markdown(
    cartao_resumo(
        f"Bolsas e Auxílios {ano_selecionado}",
        "Despesa e empenho dos programas de bolsas e auxílios do exercício, cruzados com a Execução Mensal.",
        {
            "rotulo": "Necessidade de empenho até dezembro",
            "valor": formatar_brl(_necessidade_topo_total),
            "detalhe": f"{len(filtrado)} programa(s) considerados, conforme o Resumo Consolidado",
            "tom": "warn" if _necessidade_topo_total > 0 else "ok",
        },
        [
            ("Despesa anual", formatar_brl(filtrado["valor_anual"].sum())),
            ("Valor mensal", formatar_brl(filtrado["valor_mensal"].sum())),
            ("Bolsas ativas", str(int(filtrado["qtd_efetiva"].sum()))),
            ("Programas", str(len(filtrado))),
            ("Empenhado", formatar_brl(_necessidade_topo["_valor_empenhado"].sum())),
            ("Saldo (Execução Mensal)", formatar_brl(_somar_unico_por_ne(filtrado, "saldo_execucao"))),
        ],
    ),
    unsafe_allow_html=True,
)

_render_resumo_consolidado(filtrado, tempo_por_ne_curta, source_key)

if dotacao_dimensoes is not None:
    st.markdown('<div class="cad-secao-titulo">Cobertura orçamentária por PTRES</div>', unsafe_allow_html=True)
    _render_quadro_dotacao(filtrado, dotacao_dimensoes, ano_exercicio_dotacao)
else:
    st.info(
        "Nenhuma base de Dotação Anual foi importada ainda — o quadro de cobertura "
        "orçamentária por PTRES depende dela. Importe a Dotação Anual para vê-lo aqui."
    )

# ------------------------------------------------------------------ Registro de programas
# Repaginação de 05/10/2026 ("muita cara de planilha"): a antiga lista de cartões-expansores vira um
# REGISTRO em tabela, como na referência — abas de situação com contagem, filtro de ação, ordenação,
# linhas com título/subtítulo, valores à direita, situação em chip e ações por ícone. A edição acontece
# numa janela (`_dialogo_editar_programa`), a remoção numa confirmação. Mesmos dados, regras e gravação.
st.markdown('<div class="cad-secao-titulo">Registro de programas, bolsas e auxílios</div>', unsafe_allow_html=True)

_situacoes_linhas = [
    _situacao_exibida(situacao, necessidade)[0]
    for situacao, necessidade in zip(filtrado["situacao_tg"], filtrado["valor_a_empenhar"])
]
_situacao_serie = pd.Series(_situacoes_linhas, index=filtrado.index)
_mascaras_abas = {
    "Todos": pd.Series(True, index=filtrado.index),
    "Atualizado": _situacao_serie.eq("Atualizado"),
    "Necessita reforço": _situacao_serie.eq("Necessita reforço"),
    "Sem empenho": _situacao_serie.eq("Sem empenho"),
    "Não localizado": _situacao_serie.eq("Não localizado"),
}
_contagens_abas = contagens_por_aba(_mascaras_abas)

_ORDENACOES_REGISTRO = {
    "Programa (A–Z)": ("programa_bolsa", True),
    "Processo": ("processo", True),
    "Maior valor mensal": ("valor_mensal", False),
    "Maior valor a empenhar": ("valor_a_empenhar", False),
}
_PROPORCOES_REGISTRO = [3.0, 1.1, 0.9, 1.3, 1.3, 1.3, 1.85, 0.95]
_CABECALHOS_REGISTRO = [
    ("Programa / Processo", False), ("Ação", False), ("Bolsas", True), ("Valor mensal", True),
    ("Saldo", True), ("A empenhar", True), ("Situação", False), ("Ações", False),
]
QTD_INICIAL_REGISTRO = 15

with st.container(border=True, key="cad_registro"):
    c_abas, c_acao, c_ordem = st.columns([3.8, 1.2, 1.3], vertical_alignment="center")
    aba_escolhida = c_abas.segmented_control(
        "Situação", list(_mascaras_abas), default="Todos", key=f"cad_abas_bls_{source_key}",
        format_func=lambda rotulo: f"{rotulo} ({_contagens_abas[rotulo]})", label_visibility="collapsed",
    ) or "Todos"
    _acoes_gov = sorted(filtrado["acao_cod"].dropna().astype(str).unique(), key=str.casefold)
    acao_escolhida = c_acao.selectbox(
        "Ação", ["Todas as ações", *_acoes_gov], key=f"bls_acao_{source_key}", label_visibility="collapsed",
    )
    ordem_escolhida = c_ordem.selectbox(
        "Ordenar por", list(_ORDENACOES_REGISTRO), key=f"bls_ordem_{source_key}", label_visibility="collapsed",
    )

    registro = filtrado[_mascaras_abas[aba_escolhida]]
    if acao_escolhida != "Todas as ações":
        registro = registro[registro["acao_cod"].astype("string") == acao_escolhida]
    _coluna_ordem, _crescente = _ORDENACOES_REGISTRO[ordem_escolhida]
    registro = ordenar_por(registro, _coluna_ordem, _crescente)

    st.markdown(
        f'<div class="cad-contagem">{len(registro)} registro(s) · '
        f'{formatar_brl(registro["valor_mensal"].sum())} de valor mensal</div>',
        unsafe_allow_html=True,
    )

    mostrar_todos_key = f"bls_registro_mostrar_todos_{source_key}"
    mostrar_todos = st.session_state.get(mostrar_todos_key, False)
    qtd_registro = len(registro) if mostrar_todos else QTD_INICIAL_REGISTRO

    if registro.empty:
        st.markdown('<div class="cad-vazio">Nenhum programa nesta situação/ação.</div>', unsafe_allow_html=True)
    else:
        colunas_cabecalho = st.columns(_PROPORCOES_REGISTRO)
        for coluna, (texto, a_direita) in zip(colunas_cabecalho, _CABECALHOS_REGISTRO):
            coluna.markdown(
                f'<div class="cad-cabecalho{" direita" if a_direita else ""}">{texto}</div>', unsafe_allow_html=True
            )

    # Rolagem (pedido explícito): as linhas ficam numa caixa de altura máxima fixa
    # (`.st-key-bls_registro_scroll` em `src/ui_cadastro.py`), o cabeçalho fica fora dela.
    with st.container(key="bls_registro_scroll"):
        for _, linha in registro.iloc[:qtd_registro].iterrows():
            id_linha = str(linha["id"])
            with st.container(key=f"cad_linha_{id_linha}"):
                cel = st.columns(_PROPORCOES_REGISTRO, vertical_alignment="center")
                processo_linha = _ou_vazio(linha["processo"])
                ne_linha = _ou_vazio(linha["ne_curta"])
                subtitulo = " · ".join(parte for parte in (f"Processo {processo_linha}" if processo_linha else "", f"NE {ne_linha}" if ne_linha else "") if parte)
                texto_situacao, tom_situacao = _situacao_exibida(linha["situacao_tg"], linha["valor_a_empenhar"])
                a_empenhar_linha = _ou_zero(linha["valor_a_empenhar"])
                qtd_linha = linha["qtd_efetiva"]
                cel[0].markdown(celula_principal(_ou_vazio(linha["programa_bolsa"]) or "(sem item de despesa)", subtitulo), unsafe_allow_html=True)
                cel[1].markdown(celula_categoria(linha["acao_cod"]), unsafe_allow_html=True)
                cel[2].markdown(f'<div class="cad-valor">{int(qtd_linha) if pd.notna(qtd_linha) else "—"}</div>', unsafe_allow_html=True)
                cel[3].markdown(celula_valor(linha["valor_mensal"]), unsafe_allow_html=True)
                cel[4].markdown(celula_valor(linha["saldo_execucao"]), unsafe_allow_html=True)  # sem NE: "—", não zero
                cel[5].markdown(celula_valor(linha["valor_a_empenhar"], "warn" if a_empenhar_linha > 0 and tom_situacao == "warn" else None), unsafe_allow_html=True)
                cel[6].markdown(chip(texto_situacao, tom_situacao), unsafe_allow_html=True)
                with cel[7]:
                    with st.container(key=f"cad_acoes_{id_linha}"):
                        b_editar, b_remover = st.columns(2)
                        if b_editar.button("", icon=":material/edit:", key=f"bls_editar_{source_key}_{id_linha}", help="Editar programa", use_container_width=True):
                            _dialogo_editar_programa(
                                linha, ano_selecionado, source_key,
                                sugestao_inicio_por_ne.get(linha["ne_curta"]) if pd.notna(linha["ne_curta"]) else None,
                            )
                        if b_remover.button("", icon=":material/delete:", key=f"bls_remover_{source_key}_{id_linha}", help="Remover programa", use_container_width=True):
                            _dialogo_remover_programa(
                                id_linha, f"{_ou_vazio(linha['programa_bolsa']) or '(sem item de despesa)'} — {processo_linha or 's/ processo'}", ano_selecionado
                            )

    # "Ver mais" de um clique só (pedido explícito, antes revelava +15 por clique): mostra tudo.
    if not mostrar_todos and len(registro) > QTD_INICIAL_REGISTRO:
        c_mais, c_texto = st.columns([1, 3], vertical_alignment="center")
        c_texto.caption(f"Mostrando {QTD_INICIAL_REGISTRO} de {len(registro)} programas")
        if c_mais.button("Ver mais", key=f"bls_registro_mais_{source_key}"):
            st.session_state[mostrar_todos_key] = True
            st.rerun()
    elif mostrar_todos and len(registro) > QTD_INICIAL_REGISTRO:
        if st.button("Ver menos", key=f"bls_registro_menos_{source_key}"):
            st.session_state[mostrar_todos_key] = False
            st.rerun()

st.caption(
    "Cadastro nativo de Bolsas e Auxílios (não depende de planilha) — uma linha por programa de "
    "bolsa/auxílio, não por bolsista individual (o cadastro não guarda nome/CPF de beneficiário). "
    "Saldo e Empenhado vêm da Execução Mensal, cruzados pela NE. "
    f"Exercício em tela: {ano_selecionado}. A edição abre numa janela e só é gravada ao clicar em 'Salvar'; "
    "'Novo programa' e 'Remover' gravam/apagam ao confirmar."
)
