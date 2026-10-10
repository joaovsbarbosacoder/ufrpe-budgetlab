"""Contratos Contínuos — necessidade de empenho e saldo, cruzado com a Execução Mensal.

CADASTRO NATIVO, MULTI-EXERCÍCIO (pedido explícito, mesmo tratamento já dado a
`app_pages/bolsas_auxilios.py`): esta página não lê mais a planilha de Contratos Contínuos —
os contratos vivem em `src/contratos_continuos_cadastro.py`
(`data/contratos_continuos/<ano>/<id>.json`). O exercício 2026 foi migrado uma única vez a
partir da planilha então em uso (`contratos_continuos_cadastro.migrar_de_planilha`); dali em
diante toda edição, contrato novo ou remoção grava direto no cadastro nativo. Um seletor de
exercício no topo troca qual ano está em tela; "Duplicar cadastro" copia identidade/
classificação de cada contrato para o próximo exercício (execução em branco), suportando
gerar 2028, 2029... a partir de qualquer exercício mais recente. Exercícios anteriores
continuam navegáveis como histórico. `meses_pagos`/`ultimo_mes_pago` continuam vindo da
planilha separada de Pagamentos (`com_meses_pagos`) — fora do escopo desta desvinculação.

GRANULARIDADE: 1 CONTRATO/NE, NÃO 1 ITEM DE LICITAÇÃO (pedido explícito de correção, decisão
de negócio confirmada com o usuário): diferente da planilha de origem (uma linha por contrato
× item), o cadastro nativo tem um registro por contrato/NE inteiro. Motivo: no SIAFI, o
reforço de empenho é feito por item de licitação, mas a LIQUIDAÇÃO não é dividida por item —
ela é sempre no nível da NE inteira. Saldo/status/liquidado são conceitos da NE, não do item;
um registro por item duplicava esses campos em vários cartões que precisavam ser editados em
sincronia (editar o saldo do Item 1 não atualizava o Item 2 do mesmo contrato — risco real de
inconsistência). O item de licitação não é uma entidade própria: é só o jeito de ratear
"Despesa Mensal Total" do contrato entre os itens, para saber quando o teto de cada um se
esgota e precisa de reforço — por isso mora dentro do cartão do contrato como uma lista
editável de percentuais (ver "Itens de Licitação" em `_render_card`, percentuais somando
100%), e só "aparece" (vira linha própria) na hora de montar o Relatório de Reforço de Empenho
(`src/relatorio_reforco_empenho.py::_linhas_expandidas_por_item`) — nunca nas telas de
cartão/Resumo Consolidado/Empenhado × Liquidado (que já operavam por NE via `groupby`; com 1
linha por NE de cada vez, esse `groupby` virou um no-op inofensivo, sem precisar de mudança).

Adaptação do handoff de design (`painel_bolsas.py`, versão "cartão com rótulo pequeno acima
de cada campo" — mesmo padrão já aplicado em `app_pages/bolsas_auxilios.py`, replicado aqui
para Contratos Contínuos) para os leitores e a regra de saldo já aprovados e testados neste
projeto (`src/contratos_continuos.py`, `src/necessidade_empenho.py`,
`src/execucao_ne_utils.py::saldo_por_ne`) — não `data_loader_contratos.py`/`design_tokens.py`
de handoffs anteriores.

Cada contrato é um cartão (`st.expander`, minimizado por padrão — mesmo padrão de
`app_pages/bolsas_auxilios.py`, aplicado aqui) com todos os campos editáveis inline — sem
rolagem horizontal, os campos quebram em linhas dentro do próprio cartão. Rótulo pequeno
(`.cc-label`, maiúsculo, discreto) acima de cada campo — nem rótulo nativo grande do
Streamlit, nem campo sem rótulo nenhum: editável não é sinônimo de caixa grande, mas também
não fica sem indicação do que é.

Antes da lista, um card único "Resumo Consolidado — por NE" lista, uma linha por NE (não por
item de licitação nem um total agregado — ver `_render_resumo_consolidado`), o valor
empenhado, o saldo (Execução Mensal) e a necessidade de empenho até o fim do exercício. Itens
sem NE (contrato ainda sem empenho) aparecem à parte, um por linha, já que não há NE para
agrupar. Mesmo padrão HTML de `app_pages/painel_acoes.py`, não `st.dataframe`.

Depois dele, a seção "Cobertura Orçamentária por PTRES" cruza a Dotação Atualizada
disponível (base de Dotação Anual, `src/importacao_dotacao.py`) contra a despesa anual
estimada dos contratos (`despesa_anual`), usando o PTRES como referencial comum. Um cartão
por Ação de Governo, com uma subdivisão por Plano Orçamentário/PTRES dentro de cada um —
mesmo padrão visual de `app_pages/painel_acoes.py` e de
`bolsas_auxilios.py::_render_quadro_dotacao`.

Diferenças deliberadas em relação aos handoffs anteriores:
  * "Empenhar"/"Meses de Saldo" não vêm de `despesa_mensal × "meses restantes até dezembro"`
    (métrica prospectiva de calendário nunca validada neste projeto) — vêm de
    `meses_empenhados − meses_liquidados` (`src/necessidade_empenho.py`, fórmula da coluna
    "MESES DE SALDO" da planilha, validada linha a linha contra a origem). O Resumo
    Consolidado usa `despesa_mensal × meses ainda devidos no ano` (`meses_no_ano − meses já
    empenhados, nunca calendário puro — corrigido depois de um bug real, ver
    `_render_resumo_consolidado`) só para a "Necessidade até Dezembro" agregada — mesma
    ressalva de `bolsas_auxilios.py`: não substitui nem se confunde com "Empenhar" por cartão.
  * Para contratos cuja NE já foi encontrada na Execução Mensal, `meses_empenhados`/
    `meses_liquidados` deixam de vir da planilha e passam a vir da própria Execução Mensal
    (`com_saldo_execucao`, campos `meses_empenhados_execucao`/`meses_liquidados_execucao`) —
    pedido explícito do usuário para não depender de atualizar a planilha de Contratos
    Contínuos só para refletir um novo saldo/liquidado. Os dois campos do cartão viram
    exibição (rótulo "(Execução Mensal)"), não mais editáveis, nesse caso — editar deixaria de
    ter efeito no "Empenhar" mostrado. Sem NE encontrada, os campos continuam editáveis como
    sempre, seedados pela planilha (fallback inalterado).
  * `saldo_execucao` e `valor_empenhado_execucao` (autoritativos, vindos da Execução Mensal)
    são fixos — não editáveis (lidos da Execução Mensal, não desta planilha) — e visíveis
    junto da tag de divergência contra `saldo_colado_planilha`/soma de `valor_empenhado` por
    NE, sinalizada, não escondida. `valor_empenhado_execucao` é sempre o total da NE inteira
    (mesmo valor repetido em todo item de um contrato com vários itens) — comparado contra a
    SOMA dos itens da NE (`valor_empenhado_planilha_total_ne`, calculado em
    `com_saldo_execucao`), não contra o valor do item desta linha, pelo mesmo motivo do
    `SALDO TOTAL TG` vs. `SALDO TG ATUALIZADO`: o valor de um item isolado é uma fração
    rateada, não comparável 1:1 com o total da Execução.
  * Cada item é um `st.expander` (minimizado por padrão), não um `st.container(border=True)`
    sempre aberto — o chrome de borda/raio vem de graça do CSS global do app
    (`src/ui_theme.py::_THEME_CSS`). O único `st.container(border=True)` restante é o card
    "Resumo Consolidado" (chave `cad_secao_resumo_cc_*`) — não é `st.dataframe` (cara de
    planilha). (Esse bullet descreve o desenho ANTERIOR; o cartão-expansor virou o registro em tabela
    abaixo, e o Resumo Consolidado ganhou o layout novo — ver SEÇÕES ANALÍTICAS.)
  * SEÇÕES ANALÍTICAS (pedido explícito, 05/10/2026: "aplique o mesmo layout para a Cobertura
    Orçamentária por PTRES, EMPENHADO × LIQUIDADO e RESUMO CONSOLIDADO"): as três seguem o mesmo
    desenho do registro (`src/ui_cadastro.py`) — cartão branco arredondado com kicker, título e destaque
    à direita, e linhas limpas com valores à direita. Resumo Consolidado: linhas de `st.columns` (a linha
    da NE com dado mensal ganhou um botão de ÍCONE para a "Linha do tempo mensal", mesmas chaves de
    antes); Empenhado × Liquidado e Cobertura por PTRES: tabelas HTML (`tabela_html`, `cartao_secao`,
    `cartao_cobertura_ptres`) — sem botões, uma única marcação por cartão. Dados e regras não mudaram.
  * Os tokens de cor/tipografia são os reais do projeto (`src/design_tokens.py`).
  * KPIs no topo, por pedido explícito: Despesa Anual Total, Despesa Mensal, Número de
    Contratos, Necessidade de Empenho Total — os demais já aprovados antes (Saldo via
    Execução Mensal, Contratos Ativos/Vencidos, Saldo Divergente) saíram do topo. Saldo e
    divergência continuam visíveis por cartão e no Resumo Consolidado, só não aparecem mais
    como contagem agregada na entrada da tela (mesmo pedido já atendido em
    `bolsas_auxilios.py`).
  * REPAGINAÇÃO DO CADASTRO (pedido explícito, 05/10/2026: "muita cara de planilha", seguindo o
    layout de referência): o topo vira um cartão-resumo com faixa de destaque e grade de
    indicadores; a antiga "Carteira de contratos" (cartões-expansores de campos soltos) vira o
    "Registro de contratos" — abas de situação com contagem (Todos, Ativo, Necessita reforço,
    Vencido, Suspenso), filtro de categoria, ordenação, linhas com título/subtítulo, valores à
    direita, situação em chip e ações por ícone. Componentes visuais em `src/ui_cadastro.py`
    (compartilhados com `bolsas_auxilios.py`). Os dados e as regras não mudaram.
  * "Editar" abre uma janela (`@st.dialog`) com os mesmos campos em seções (Identificação, Período
    de execução, Classificação orçamentária, Empenho e valores, Itens de licitação) e indicadores
    que recalculam ao vivo; só grava ao clicar em "Salvar". Dentro da janela, adicionar/remover
    item recarrega só o fragmento (`st.rerun(scope="fragment")`). Por isso a antiga edição ao vivo
    na sessão (`_aplicar_edicoes_da_sessao`) deixou de existir: o resumo reflete o cadastro gravado.
  * "Remover" pede confirmação numa janela antes de apagar o registro em definitivo do cadastro
    nativo (mesmo critério de `bolsas_auxilios.py`). "Novo contrato" é um botão principal no
    cabeçalho que abre uma janela com o formulário em seções.
  * O registro mostra 15 linhas (`QTD_INICIAL_REGISTRO`) e "Ver mais" revela todas num clique só
    (pedido explícito; antes eram +15 por clique), dentro de uma caixa com barra de rolagem. O
    "Resumo Consolidado" segue minimizado (`QTD_INICIAL_RESUMO`, "Ver mais" de um clique só, linhas numa
    caixa com rolagem): só as linhas visíveis são limitadas, os totais (cabeçalho e rodapé) sempre somam
    o conjunto inteiro filtrado.
  * Quadro "Empenhado × Liquidado" (pedido explícito) — mesmo layout do Resumo
    Consolidado (cartão + tabela com rolagem, mesma minimização "Ver mais"), comparando por NE o valor
    empenhado total contra o liquidado (`indice_liquidado_por_ne_curta`, em
    `src/execucao_ne_utils.py`, ou `indice_liquidado_competencia` quando a base de competência
    está disponível — ver LIQUIDADO POR COMPETÊNCIA abaixo), abrangendo todos os contratos
    filtrados — inclusive os sem NE (aparecem com "sem NE" no lugar de liquidado/saldo). O
    saldo mostrado é o mesmo `saldo_execucao` (empenhada − liquidada por LANÇAMENTO, sempre
    via Execução Mensal — não muda com a competência, é o saldo formal usado também na
    divergência contra o saldo colado da planilha/TG) já usado no resto da página, só rotulado
    "Sobra" (≥ 0) ou "Insuficiência" (< 0, liquidado passou do empenhado) — não é uma conta
    nova. Com Liquidado por competência, as três colunas do quadro (Empenhado, Liquidado,
    Saldo) deixam de bater aritmeticamente entre si (Saldo não é mais Empenhado − Liquidado
    exibido) — pedido explícito do usuário, mesmo assim: mostrar o Liquidado mais correto
    (competência) importa mais aqui do que a soma bater, mas o quadro deixa isso visível (nota
    abaixo do cabeçalho) para não parecer um erro de conta.

LIQUIDADO POR COMPETÊNCIA (pedido explícito posterior, ver `app_pages/consulta_empenhos.py`
para o desenho original): "Necessidade de Empenho" no cartão, o pop-up "Linha do tempo
mensal" do Resumo Consolidado, e o quadro "Empenhado × Liquidado" acima trocam o Liquidado
por mês/total de LANÇAMENTO (Execução Mensal/Mensal) pelo de COMPETÊNCIA (mês de referência —
`src/liquidacao_competencia.py`) quando `data/raw/Liquidação por Competência.xlsx` está
disponível; sem o arquivo, os três voltam ao comportamento anterior (liquidado por
lançamento), mesma lógica de ausência silenciosa das outras bases de trabalho desta página.
`saldo_execucao`/divergência contra a planilha (TG) NUNCA usam competência — são conceitos de
saldo formal, sempre por lançamento.
"""

from __future__ import annotations

import html as html_lib
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src import contratosgov_extracao
from src.contratos_aditivos import (
    aditivo_para_registro,
    dia_de_referencia,
    validar_aditivos,
    valor_vigente_em,
    vigencia_efetiva,
)
from src.contratos_cadastro import montar_contratos, montar_empenhos, montar_termos
from src.contratos_continuos import (
    SITUACAO_NECESSITA_REFORCO,
    SITUACAO_VIGENCIA_ENCERRADA,
    aditivo_sugerido,
    aditivos_pendentes,
    numero_do_termo,
    candidatos_novos,
    com_contratosgov,
    filtrar_candidatos,
    registro_novo_do_gov,
    situacao_contrato,
)
from src.contratos_continuos_cadastro import (
    anos_disponiveis,
    atualizar_contrato,
    carregar_contratos,
    como_dataframe,
    despesa_anual_pela_serie,
    duplicar_exercicio,
    excluir_contrato,
    excluir_exercicio,
    novo_contrato_do_formulario,
    salvar_contrato,
)
from src.contratos_pagamentos import MESES_ORDEM, meses_pagos_por_contrato, ler_pagamentos
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
    WARNING_SOFT,
)
from src.execucao_ne_utils import (
    indice_liquidado_por_ne_curta,
    ne_curta as _ne_curta_execucao,
    saldo_por_ne,
)
from src.importacao_dotacao import DIRETORIO_MANIFESTOS_PADRAO, Manifesto as ManifestoDotacao
from src.importacao_dotacao import NOME_PONTEIRO as NOME_PONTEIRO_DOTACAO
from src.importacao_dotacao import carregar_atual as carregar_dotacao_atual
from src.importacao_execucao_mensal import Manifesto as ManifestoExecucaoMensal
from src.importacao_execucao_mensal import NOME_PONTEIRO as NOME_PONTEIRO_EXECUCAO_MENSAL
from src.importacao_execucao_mensal import carregar_atual as carregar_execucao_mensal_atual
from src.liquidacao_competencia import ler_liquidacao_competencia, liquidado_por_ne, liquidado_por_ne_e_mes
from src.necessidade_empenho import calcular_necessidade_empenho
from src.relatorio_necessidade_empenho import ContextoRelatorioNecessidade
from src.relatorio_necessidade_empenho import gerar_pdf as gerar_pdf_necessidade
from src.relatorio_necessidade_empenho import gerar_xlsx as gerar_xlsx_necessidade
from src.relatorio_necessidade_empenho import montar_relatorio as montar_relatorio_necessidade
from src.relatorio_necessidade_empenho import (
    mes_referencia_do_exercicio,
    necessidade_por_linha,
    necessidade_por_ne,
    valor_estimado_em_previstos,
)
from src.relatorio_projecao_execucao import ContextoProjecaoExecucao, ORIGEM_EXECUCAO, ORIGEM_SEM_HISTORICO
from src.relatorio_projecao_execucao import fatores_por_ne as fatores_projecao_execucao
from src.relatorio_projecao_execucao import gerar_pdf as gerar_pdf_projecao_execucao
from src.relatorio_projecao_execucao import gerar_xlsx as gerar_xlsx_projecao_execucao
from src.resultado_orcamentario_fontes import projecao_contratos, tabela_contratos
from src.relatorio_reforco_empenho import CONTRATOS_CONTINUOS as RELATORIO_CONTRATOS_CONTINUOS
from src.tesouro_execucao_mensal import agregar_por_ne, linha_do_tempo_por_ne, primeiro_mes_com_empenho_por_ne
from src.ui_linha_do_tempo import (
    BASE_LIQUIDADO_COMPETENCIA,
    BASE_LIQUIDADO_EXECUCAO_MENSAL,
    MESES_ABREV,
    abrir_linha_do_tempo,
)
from src.ui_aditivos import acrescentar_aditivo, recarregar_fragmento, render_aba_aditivos
from src.ui_cadastro import (
    aviso_linha_do_tempo,
    cartao_cobertura_ptres,
    cartao_resumo,
    cartao_secao,
    celula_categoria,
    celula_principal,
    celula_saldo,
    celula_suave,
    celula_valor,
    chip,
    contagens_por_aba,
    formatar_brl,
    grade_indicadores,
    ordenar_por,
    tabela_html,
    topo_secao,
)
from src.ui_cadastro import css as css_cadastro
from src.ui_relatorio_reforco_empenho import render_botao_relatorio
from src.ui_reajuste import render_estimativa_reajuste
from src.ui_theme import render_page_header

DIRETORIO_DADOS_BRUTOS = Path("data/raw")
CAMINHO_PAGAMENTOS = DIRETORIO_DADOS_BRUTOS / "CONTRATOS - CONTROLE 2020 - Pagamentos.xlsx"
#: mesmo arquivo usado por app_pages/consulta_empenhos.py (ver ali o porquê da troca) — usada
#: aqui para "Necessidade de Empenho" (ver `com_saldo_execucao`, parâmetro
#: `indice_liquidado_competencia`). Ausência do arquivo não impede o resto da página: a conta
#: volta a usar o liquidado por lançamento da Execução Mensal (comportamento anterior a este
#: pedido).
CAMINHO_LIQUIDACAO_COMPETENCIA = Path("data/raw") / "Liquidação por Competência.xlsx"

COLUNAS_BUSCA = [
    "contrato_numero", "fornecedor", "tipo_despesa", "tipo_contrato", "acao_cod",
    "pi_cod", "unidade_cod", "processo_contratacao", "processo_empenho", "ne_curta",
]

#: SUSPENSO (pedido explícito, 02/10/2026): mesmo vigente, o relatório de Necessidade de Empenho
#: não projeta nada para o contrato (`src/relatorio_necessidade_empenho.limite_de_projecao`).
STATUS_OPCOES = ["ATIVO", "VENCIDO", "SUSPENSO"]


@st.cache_data(show_spinner="Lendo a base de Execução Mensal...")
def _cached_por_ne_execucao(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    """Saldo autoritativo por NE, a partir da Execução MENSAL (2024+) — não mais a Anual (ver
    decisão de 22/09/2026, pedido do usuário: parar de depender da Execução Anual).
    `caminho_ponteiro`/`mtime_ponteiro` só participam da chave de cache — força reler quando
    o manifesto atual mudar. `carregar_atual` já devolve a base composta por ano (ver
    `src/importacao_execucao_mensal.py`)."""

    return saldo_por_ne(agregar_por_ne(carregar_execucao_mensal_atual()))


@st.cache_data(show_spinner="Lendo a linha do tempo mensal...")
def _cached_linha_do_tempo(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    """Empenhado/Liquidado/Pago por (NE, mês), a partir da base MENSAL (`carregar_atual`,
    importação versionada — ver `src/importacao_execucao_mensal.py`) — com `ne_curta`
    acrescentada, pra poder ligar com o `ne_curta` já usado nos contratos. Pop-up "Linha do
    tempo mensal" (`src/ui_linha_do_tempo.py`), mesmo formato de
    `app_pages/bolsas_auxilios.py`/`app_pages/consulta_empenhos.py`. `caminho_ponteiro`/
    `mtime_ponteiro` só participam da chave de cache."""

    tempo = linha_do_tempo_por_ne(carregar_execucao_mensal_atual())
    tempo["ne_curta"] = tempo["ne_ccor"].apply(_ne_curta_execucao)
    return tempo


@st.cache_data(show_spinner="Lendo a Liquidação por Competência...")
def _cached_indice_liquidado_competencia(caminho: str, mtime: float) -> pd.Series:
    """Total liquidado por competência (todos os meses somados, ver
    `src.liquidacao_competencia.liquidado_por_ne`), indexado pela forma curta da NE — pronto
    pra `com_saldo_execucao(..., indice_liquidado_competencia=...)`. `mtime` só participa da
    chave de cache."""

    totais = liquidado_por_ne(ler_liquidacao_competencia(caminho))
    return pd.Series(totais.to_numpy(), index=[_ne_curta_execucao(ne) for ne in totais.index])


@st.cache_data(show_spinner="Lendo a Liquidação por Competência (mensal)...")
def _cached_liquidacao_competencia_por_mes(caminho: str, mtime: float) -> pd.DataFrame:
    """Liquidado por (NE, mês de referência/competência), com `ne_curta` acrescentada — para
    o pop-up "Linha do tempo mensal" do Resumo Consolidado (mesma troca de
    `app_pages/consulta_empenhos.py`: Liquidado por mês de competência em vez de por mês de
    lançamento — ver `_tempo_com_liquidacao_por_competencia`). Lido separado de
    `_cached_indice_liquidado_competencia` (mesmo arquivo, granularidade diferente): cada
    `st.cache_data` guarda seu próprio resultado, mesmo padrão de `_cached_itens_por_ne`/
    `_cached_linha_do_tempo` em `app_pages/consulta_empenhos.py`. `mtime` só participa da
    chave de cache."""

    tempo = liquidado_por_ne_e_mes(ler_liquidacao_competencia(caminho))
    tempo["ne_curta"] = tempo["ne_ccor"].apply(_ne_curta_execucao)
    return tempo


@st.cache_data(show_spinner="Lendo a planilha de Pagamentos de Contratos...")
def _cached_meses_pagos_por_contrato(caminho: str, mtime: float) -> pd.DataFrame:
    """Meses pagos + último mês pago por contrato (número normalizado), a partir da planilha
    de Pagamentos — complemento opcional (mesmo padrão de `_cached_dotacao_por_ptres`): sem
    ela, os campos ficam nulos e o resto da tela continua funcionando normal."""

    return meses_pagos_por_contrato(ler_pagamentos(caminho))


@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def _cached_dotacao_por_ptres(caminho_ponteiro: str, mtime_ponteiro: float) -> tuple[pd.DataFrame, int]:
    """Uma linha por PTRES do exercício mais recente da base (a base traz vários anos —
    misturar exercícios inflaria a dotação de cada PTRES): Ação, Plano Orçamentário e Dotação
    Atualizada. Mesmo padrão de `app_pages/bolsas_auxilios.py::_cached_dotacao_por_ptres`.
    `caminho_ponteiro`/`mtime_ponteiro` só participam da chave de cache — `carregar_atual` já
    devolve a base composta por ano (ver `src/importacao_dotacao.py`)."""

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


def _fmt_mes(valor: object) -> str:
    """"mmm/aa" a partir de um Timestamp truncado ao mês (`ultimo_mes_pago`) — mesmo padrão de
    `app_pages/contratos_pagamentos.py::_fmt_mes` (abreviação em português, não `strftime`)."""

    if valor is None or pd.isna(valor):
        return "—"
    return f"{MESES_ORDEM[valor.month - 1][:3]}/{valor.year % 100:02d}"


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
    """Soma `coluna` uma única vez por NE — evita contar `saldo_execucao` (repetido em cada
    item de um mesmo contrato/NE) mais de uma vez."""

    unicos = dataframe.dropna(subset=["ne_curta"]).drop_duplicates("ne_curta")
    return float(unicos[coluna].sum())


def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .cc-label {{
            font-family: {FONT_HEADING}; font-size: 9.5px; letter-spacing: 0.08em;
            text-transform: uppercase; color: {TEXT_MUTED}; margin-bottom: -6px;
        }}
        .cc-calc {{ font-size: 13px; font-variant-numeric: tabular-nums; padding: 8px 0 2px; }}
        .cc-calc.strong {{ font-weight: 600; color: {ACCENT_STRONG}; }}
        .cc-tag {{
            display: inline-block; font-family: {FONT_HEADING}; font-size: 9.5px;
            letter-spacing: 0.06em; text-transform: uppercase; padding: 3px 8px;
            border-radius: 3px; margin: 1px 4px 1px 0;
        }}
        .cc-tag.ok {{ background: rgba(34,197,94,0.12); color: {POSITIVE}; }}
        .cc-tag.bad {{ background: rgba(240,87,107,0.12); color: {NEGATIVE}; }}
        .cc-tag.warn {{ background: {WARNING_SOFT}; color: {WARNING}; }}
        /* Pop-up "Linha do tempo mensal" (`src/ui_linha_do_tempo.py`) — mesmo formato de
           `app_pages/consulta_empenhos.py`/`app_pages/bolsas_auxilios.py`. CSS duplicado de
           propósito: Streamlit não carrega o CSS injetado numa página anterior ao navegar
           para outra, cada página que usa esse pop-up precisa da sua própria cópia. */
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


def _data_ou_none(valor: object) -> date | None:
    """`vigencia_fim` do DataFrame (Timestamp/NaT) -> `date` do `st.date_input`; nulo vira
    `None` (campo vazio), nunca uma data presumida."""

    return None if valor is None or pd.isna(valor) else pd.Timestamp(valor).date()


_OPCOES_INICIO_EXECUCAO = ["Automático"] + [MESES_ABREV[m] for m in range(1, 13)]


def _secao(titulo: str) -> None:
    """Título de seção dentro das janelas de edição (`.cad-secao-dialogo`, ver `src/ui_cadastro.py`)."""

    st.markdown(f'<div class="cad-secao-dialogo">{titulo}</div>', unsafe_allow_html=True)


#: caracteres que o markdown interpreta; cada um ganha uma barra invertida na frente em `_md`.
_ESPECIAIS_MARKDOWN = {ord(c): chr(92) + c for c in chr(92) + "`*_{}[]<>~$|"}


def _md(texto: object) -> str:
    """Texto de dado externo para `st.markdown` SEM HTML: escapa os caracteres especiais do markdown. Dado do
    Contratos.gov (ex.: "C&C COMERCIO") não passa por HTML aqui — no markdown com `unsafe_allow_html` o Streamlit
    codificava o `&` duas vezes ("C&amp;C" na tela, conferido no navegador)."""

    return str(texto).translate(_ESPECIAIS_MARKDOWN)


def _ou_traco(valor: object) -> str:
    """Texto puro (SEM escape de HTML) ou "—" — para o que vai a `st.markdown` via `_md`."""

    return "—" if valor is None or pd.isna(valor) else str(valor)


def _fmt_data_gov(valor: object) -> str:
    dia = _data_ou_none(valor)
    return dia.strftime("%d/%m/%Y") if dia else "sem dado"


def _referencia_gov() -> date:
    """Data de referência da situação de vigência do gov: hoje, ou `contratos_referencia` em
    `st.session_state` (gancho só para testes determinísticos, o mesmo de `app_pages/contratos.py`)."""

    valor = st.session_state.get("contratos_referencia")
    return valor if isinstance(valor, date) else date.today()


def _carregar_gov(referencia: date) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
    """(contratos, termos, empenhos) da fotografia atual do Contratos.gov.br, ou `None` — com aviso explícito —
    se não houver fotografia ou ela não puder ser lida (mesmo critério de `app_pages/contratos.py`). A
    integração é complemento opcional: sem ela, a tela segue como antes, sem conciliação, sem exceção."""

    try:
        fotografia, _manifesto = contratosgov_extracao.carregar_atual()
        if fotografia is None:
            st.info(
                "Nenhuma fotografia do Contratos.gov.br foi gravada ainda — a conciliação de vigência e aditivos "
                "e a lista de contratos novos não aparecem. Faça a carga na página Contratos (aba Atualizar)."
            )
            return None
        return montar_contratos(fotografia, referencia), montar_termos(fotografia), montar_empenhos(fotografia)
    except Exception as erro:  # manifesto incompleto (TypeError), arquivo travado pelo Drive (OSError), dado inválido...
        st.warning(
            f"Não foi possível ler a fotografia do Contratos.gov.br ({erro}) — a conciliação de vigência e "
            "aditivos e a lista de contratos novos não aparecem."
        )
        return None


#: situacao_conciliacao (`com_contratosgov`) -> texto curto no subtítulo da linha do registro.
_TEXTO_CONCILIACAO = {
    "conciliado": "Gov: vigência confere",
    "divergente": "Gov: vigência diverge",
    "sem_par_no_contratosgov": "sem par no Contratos.gov",
    "conflito": "Gov: conflito de ligação",
    "sem_data_para_comparar": "Gov: vigência sem data",
}


def _texto_conciliacao(linha: pd.Series) -> str:
    """Trecho do subtítulo da linha com a conciliação e os aditivos do gov sem registro; vazio quando a
    integração não está carregada."""

    if "situacao_conciliacao" not in linha.index or pd.isna(linha["situacao_conciliacao"]):
        return ""
    partes = [_TEXTO_CONCILIACAO.get(linha["situacao_conciliacao"], "")]
    status = linha.get("status_contrato", pd.NA)
    status = "ATIVO" if pd.isna(status) else str(status).strip().upper()
    if str(linha.get("situacao_vigencia_gov")) == "encerrado" and status == "ATIVO":
        partes.append("contrato encerrado no gov")
    pendentes = linha["qtd_aditivos_pendentes"]
    if pd.notna(pendentes) and int(pendentes) > 0:
        partes.append(f"{int(pendentes)} aditivo(s) do gov sem registro")
    return " · ".join(parte for parte in partes if parte)


def _render_contratosgov_no_dialogo(
    linha: pd.Series, k: str, termos_gov: pd.DataFrame | None, aditivos_atuais: list | None = None
) -> None:
    """Seção "Contratos.gov" da janela de edição: vigência do cadastro × a do gov, histórico de termos e um botão
    "Registrar aditivo do gov" por aditivo sem registro. O botão SÓ pré-preenche a aba Aditivos (em
    `st.session_state`, via `acrescentar_aditivo`): nada é gravado até o "Salvar" da janela, e o valor mensal
    fica em branco (a parcela do gov é do contrato inteiro; Contínuos traz a parcela da ação 20RK).

    `aditivos_atuais` = os aditivos como estão digitados na aba Aditivos NESTA execução (a seção é desenhada
    depois da aba, num contêiner reservado antes dela): um aditivo digitado à mão ou recém-registrado já
    tira o termo da lista de pendentes, sem a defasagem de uma execução."""

    if termos_gov is None or "situacao_conciliacao" not in linha.index or pd.isna(linha["situacao_conciliacao"]):
        return
    _secao("Contratos.gov")
    if pd.isna(linha["contratosgov_id"]):
        if linha["situacao_conciliacao"] == "conflito":
            st.caption(
                "Conflito de ligação: a NE ou o número/CNPJ deste registro aponta mais de um contrato (ou "
                "contratos diferentes) no Contratos.gov — nada do gov é aplicado."
            )
        else:
            st.caption(
                "Este registro não tem par no Contratos.gov (nem a NE nem número + CNPJ/CPF casam com um contrato)."
            )
        return

    st.markdown(
        f"Vigência no cadastro (com aditivos): **{_fmt_data_gov(linha['vigencia_fim_efetiva'])}** · "
        f"no Contratos.gov: **{_fmt_data_gov(linha['vigencia_fim_contratosgov'])}** · "
        f"situação no gov: **{_md(linha['situacao_vigencia_gov'])}** · ligado por {_md(linha['ligacao_por'])}"
    )
    if pd.notna(linha["valor_parcela_contratosgov"]):
        st.caption(
            "Parcela no Contratos.gov (referência — contrato inteiro, não a parcela da ação 20RK): "
            f"{_brl(linha['valor_parcela_contratosgov'])}"
        )
    termos = termos_gov[termos_gov["contrato_id"].astype(str) == str(linha["contratosgov_id"])]
    st.dataframe(
        termos.sort_values("data_assinatura", na_position="last")[
            ["tipo", "numero", "qualificacao_termo", "data_assinatura", "vigencia_fim", "data_inicio_novo_valor"]
        ].rename(columns={
            "tipo": "Tipo", "numero": "Nº", "qualificacao_termo": "Qualificação", "data_assinatura": "Assinatura",
            "vigencia_fim": "Vigência (fim)", "data_inicio_novo_valor": "Início do novo valor",
        }),
        hide_index=True, width="stretch",
    )

    pendentes = aditivos_pendentes(linha["aditivos"] if aditivos_atuais is None else aditivos_atuais, termos)
    if pendentes.empty:
        st.caption("Todos os aditivos do Contratos.gov já têm registro neste contrato.")
        return
    for _, termo in pendentes.iterrows():
        if st.button(f"Registrar aditivo do gov ({numero_do_termo(termo)})", key=f"{k}_gov_registrar_{termo['termo_id']}"):
            acrescentar_aditivo(k, linha["aditivos"], aditivo_sugerido(termo))
            recarregar_fragmento()
    st.caption(
        "Nada é gravado até clicar em Salvar: o botão só pré-preenche a aba Aditivos — revise tipo, datas e "
        "vigência (o valor mensal fica em branco)."
    )


def _campo_inicio_execucao(col, valor_persistido: object, sugestao_auto: object, key: str) -> int | None:
    """"Início da Execução" por MÊS (1-12), usado pela sugestão "por calendário" do Relatório de
    Reforço e, quando informado, pela Necessidade de Empenho — mesmo campo/critério de
    `app_pages/bolsas_auxilios.py::_campo_inicio_execucao`: "Automático" (`None` persistido) usa
    `sugestao_auto` (mês do primeiro empenho da NE, detectado na base mensal) e não corta nada na
    Necessidade; escolher um mês grava um início manual."""

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


def _situacao(status_bruto: object, vigencia_fim_efetiva: object, necessidade: object) -> tuple[str, str]:
    """(texto, tom) do chip de situação da linha — regra em `src.contratos_continuos.situacao_contrato`
    (06/10/2026: o reforço passa a vir da Necessidade até dezembro, não do saldo, e entra "Vigência
    encerrada"). Status fora de `STATUS_OPCOES` conta como ATIVO."""

    status = status_bruto if pd.notna(status_bruto) and status_bruto in STATUS_OPCOES else "ATIVO"
    return situacao_contrato(status, vigencia_fim_efetiva, necessidade, date.today())


@st.dialog("Editar contrato", width="large")
def _dialogo_editar_contrato(
    linha: pd.Series, ano_exercicio: int, source_key: str, sugestao_inicio: object,
    termos_gov: pd.DataFrame | None = None,
) -> None:
    """Janela de edição de um contrato (substitui o antigo cartão-expansor de campos soltos —
    pedido de 05/10/2026: "muita cara de planilha"). Mesmos campos, mesmas chaves de widget e a
    mesma regra de gravação de antes, agora em seções: Identificação, Período de execução,
    Classificação orçamentária, Empenho e valores e Itens de licitação. Os indicadores do topo
    recalculam ao vivo com o que está digitado; nada é gravado até "Salvar".

    `ano_exercicio` (parâmetro) != `ano` (variável local abaixo, campo "Ano" do contrato em si) —
    nomes diferentes de propósito, para não colidir."""

    id_contrato = str(linha["id"])
    k = f"cc_{source_key}_{id_contrato}"
    topo = st.container()  # preenchido no fim, com os valores já calculados dos campos abaixo

    _secao("Identificação")
    c_forn, c_status, c_numero = st.columns([2.2, 1, 1])
    fornecedor = c_forn.text_input("Fornecedor", value=_ou_vazio(linha["fornecedor"]), key=f"{k}_fornecedor")
    status_bruto = linha["status_contrato"]
    status_atual = status_bruto if pd.notna(status_bruto) and status_bruto in STATUS_OPCOES else "ATIVO"
    status = c_status.selectbox(
        "Status", STATUS_OPCOES, index=STATUS_OPCOES.index(status_atual), key=f"{k}_status",
        help="SUSPENSO não gera necessidade, projeção nem sugestão de reforço a partir da data da suspensão "
             "(sem data, no exercício inteiro), mesmo vigente; a despesa anual passa a ser o já empenhado.",
    )
    numero = c_numero.text_input("Nº do contrato", value=_ou_vazio(linha["contrato_numero"]), key=f"{k}_numero")
    c_ano, c_cnpj, c_tipo = st.columns([1, 1.4, 1.4])
    ano = c_ano.number_input(
        "Ano", value=int(_ou_zero(linha["ano_contrato"]) or 2026), step=1, min_value=2000, format="%d", key=f"{k}_ano",
    )
    cnpj = c_cnpj.text_input("CNPJ/CPF", value=_ou_vazio(linha["fornecedor_cnpj_cpf"]), key=f"{k}_cnpj")
    tipo_despesa = c_tipo.text_input("Tipo de despesa", value=_ou_vazio(linha["tipo_despesa"]), key=f"{k}_tipodespesa")
    # Os dois processos já vinham da planilha de origem para o cadastro, mas não eram editáveis
    # (06/10/2026). O de empenho é o que o Relatório de Reforço agrupa (`coluna_processo`).
    c_proc_contr, c_proc_emp = st.columns(2)
    processo_contratacao = c_proc_contr.text_input(
        "Processo da contratação", value=_ou_vazio(linha["processo_contratacao"]), key=f"{k}_processo_contratacao",
    )
    processo_empenho = c_proc_emp.text_input(
        "Processo de empenho", value=_ou_vazio(linha["processo_empenho"]), key=f"{k}_processo_empenho",
    )

    gov_container = st.container()  # reservado aqui; preenchido depois da aba Aditivos (ver `_render_contratosgov_no_dialogo`)

    _secao("Período de execução")
    aba_periodo, aba_aditivos = st.tabs(["Período", "Aditivos"])
    with aba_aditivos:
        aditivos_editados = render_aba_aditivos(k, linha["aditivos"], linha["itens"])
        with gov_container:
            _render_contratosgov_no_dialogo(linha, k, termos_gov, aditivos_editados)
    with aba_periodo:
        p_vig, p_data, p_mes, p_meses = st.columns(4)
        # Vigência (fim) — a data de fim do cadastro limita a projeção do relatório de Necessidade de
        # Empenho (o mês final é proporcional) e manda sobre o status. Vazio = sem data (nulo, nunca
        # presumido).
        vigencia = p_vig.date_input(
            "Vigência (fim)", value=_data_ou_none(linha["vigencia_fim"]), format="DD/MM/YYYY",
            min_value=date(2000, 1, 1), max_value=date(2100, 12, 31), key=f"{k}_vigencia",
            help="Fim da vigência do contrato. A projeção do relatório de Necessidade de Empenho para neste "
                 "mês (proporcional aos dias) — a data manda sobre o status.",
        )
        vigencia_ef, definidor_vigencia = vigencia_efetiva(vigencia, aditivos_editados)
        if definidor_vigencia is not None:
            p_vig.caption(
                f"Vigência efetiva: {vigencia_ef:%d/%m/%Y} ({definidor_vigencia.numero or 'aditivo sem nº'}"
                + (", previsto)" if definidor_vigencia.previsto else ")")
            )
        # Início da execução por DATA — os meses anteriores ao início não contam na Necessidade de
        # Empenho e o mês inicial é proporcional aos dias. Manda sobre o mês escolhido ao lado.
        inicio_execucao_data_editada = p_data.date_input(
            "Início da execução (data)", value=_data_ou_none(linha["inicio_execucao_data"]), format="DD/MM/YYYY",
            min_value=date(2000, 1, 1), max_value=date(2100, 12, 31), key=f"{k}_inicio_data",
            help="Data em que o contrato começou a ser executado neste exercício. Os meses anteriores não entram "
                 "na Necessidade de Empenho e o mês inicial é proporcional aos dias. Se informada, vale mais "
                 "que o mês escolhido ao lado.",
        )
        inicio_execucao_mes_editado = _campo_inicio_execucao(p_mes, linha["inicio_execucao_mes"], sugestao_inicio, f"{k}_inicio")
        # meses_no_ano: total de meses que o contrato é pago no exercício — a maioria é 12 (contrato
        # "contínuo" de verdade), mas um contrato que só roda parte do ano tem menos.
        meses_no_ano = p_meses.number_input(
            "Meses no ano", value=int(_ou_zero(linha["meses_no_ano"]) or 12), step=1, min_value=1, format="%d",
            key=f"{k}_mesesano",
        )
        # Data da suspensão (06/10/2026) — só vale com o status SUSPENSO: a partir dela o contrato não gera
        # necessidade, projeção nem sugestão de reforço. Sem data, SUSPENSO vale para o exercício inteiro.
        p_susp, _ = st.columns([1, 3])
        data_suspensao = p_susp.date_input(
            "Data da suspensão", value=_data_ou_none(linha["data_suspensao"]), format="DD/MM/YYYY",
            min_value=date(2000, 1, 1), max_value=date(2100, 12, 31), key=f"{k}_suspensao",
            help="Só vale com o status SUSPENSO. A partir desta data o contrato não gera necessidade, projeção nem "
                 "sugestão de reforço; os meses anteriores seguem a regra normal. Sem data, a suspensão vale para "
                 "o exercício inteiro.",
        )
        if data_suspensao and status != "SUSPENSO":
            p_susp.caption("Sem efeito: o status não é SUSPENSO.")

    _secao("Classificação orçamentária")
    q = st.columns(6)
    unidade = q[0].text_input("Unidade", value=_ou_vazio(linha["unidade_cod"]), key=f"{k}_unidade")
    acao = q[1].text_input("Ação", value=_ou_vazio(linha["acao_cod"]), key=f"{k}_acao")
    ptres = q[2].text_input("PTRES", value=_ou_vazio(linha["ptres"]), key=f"{k}_ptres")
    nd = q[3].text_input("ND", value=_ou_vazio(linha["natureza_despesa_cod"]), key=f"{k}_nd")
    ugr = q[4].text_input("UGR", value=_ou_vazio(linha["ugr_cod"]), key=f"{k}_ugr")
    pi = q[5].text_input("PI", value=_ou_vazio(linha["pi_cod"]), key=f"{k}_pi")

    _secao("Empenho e valores")
    e = st.columns(4)
    ne_curta = e[0].text_input("Empenho (NE)", value=_ou_vazio(linha["ne_curta"]), key=f"{k}_ne")
    # sem min_value=0.0: a base real tem valores negativos em pelo menos um registro (anulação/ajuste
    # retroativo) — um piso de zero quebraria a leitura desse valor já existente na origem.
    despesa_mensal = e[1].number_input(
        "Despesa mensal total (R$)", value=float(_ou_zero(linha["despesa_mensal"])), step=100.0, key=f"{k}_despmensal",
    )
    valor_empenhado = e[2].number_input(
        "Empenhado (R$)", value=float(_ou_zero(linha["valor_empenhado"])), step=100.0, key=f"{k}_empenhado",
    )
    saldo_planilha = e[3].number_input(
        "Saldo TG (R$)", value=float(_ou_zero(linha["saldo_colado_planilha"])), step=100.0, key=f"{k}_saldotg",
    )

    # Quando a NE já foi encontrada na Execução Mensal, `meses_empenhados_execucao`/
    # `meses_liquidados_execucao` (ver `com_saldo_execucao`) substituem os campos manuais da
    # planilha na conta de "Empenhar" — viram exibição (nos indicadores do topo), não campos,
    # para não sugerir que digitar ali teria algum efeito. Sem NE na Execução, continuam editáveis.
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

    despesa_anual = despesa_anual_pela_serie(despesa_mensal, aditivos_editados, ano_exercicio, meses_no_ano)
    meses_a_empenhar, valor_a_empenhar = calcular_necessidade_empenho(meses_empenhados, meses_liquidados, despesa_mensal)
    if status == "SUSPENSO":  # mesma regra de `com_efeitos_da_suspensao`, com o que está digitado
        empenhado_execucao = linha["valor_empenhado_execucao"]
        despesa_anual = float(empenhado_execucao) if pd.notna(empenhado_execucao) else valor_empenhado
        meses_a_empenhar, valor_a_empenhar = 0.0, 0.0

    # Itens de licitação — rateiam "Despesa Mensal Total" entre si (no SIAFI o reforço de empenho é
    # por item, mas a liquidação não é dividida por item; o item não é uma entidade própria, só um
    # percentual do contrato, usado na hora de montar o Relatório de Reforço — ver
    # `src/relatorio_reforco_empenho.py::_linhas_expandidas_por_item`). Lista dinâmica em
    # `st.session_state`, inicializada uma vez a partir do registro e só gravada ao clicar "Salvar".
    # Dentro da janela, `st.rerun()` fecharia o diálogo: adicionar/remover item recarrega só o
    # fragmento da janela (`scope="fragment"`).
    _secao("Itens de licitação — rateio da despesa mensal (%)")
    itens_key = f"{k}_itens"
    if itens_key not in st.session_state:
        origem = linha["itens"] if isinstance(linha["itens"], list) and linha["itens"] else [{"numero": 1, "percentual": 100.0}]
        st.session_state[itens_key] = [dict(item) for item in origem]
    itens_sessao = st.session_state[itens_key]

    for posicao in range(len(itens_sessao)):
        item = itens_sessao[posicao]
        c_num, c_pct, c_rem = st.columns([1, 2, 1], vertical_alignment="bottom")
        novo_numero = c_num.number_input(
            "Item" if posicao == 0 else "Item ", value=int(item["numero"]), step=1, min_value=1,
            key=f"{itens_key}_{posicao}_num",
        )
        novo_percentual = c_pct.number_input(
            "Percentual (%)" if posicao == 0 else "Percentual (%) ", value=float(item["percentual"]), step=1.0,
            min_value=0.0, max_value=100.0, key=f"{itens_key}_{posicao}_pct",
        )
        itens_sessao[posicao] = {"numero": int(novo_numero), "percentual": float(novo_percentual)}
        if len(itens_sessao) > 1 and c_rem.button("Remover item", key=f"{itens_key}_{posicao}_rem", icon=":material/close:"):
            itens_sessao.pop(posicao)
            st.rerun(scope="fragment")

    soma_percentuais = sum(item["percentual"] for item in itens_sessao)
    cor_soma = POSITIVE if abs(soma_percentuais - 100) < 0.05 else NEGATIVE
    c_soma, c_add = st.columns([3, 1], vertical_alignment="center")
    c_soma.markdown(
        f"<div style='color:{cor_soma};font-size:14px'>Soma dos percentuais: {soma_percentuais:.1f}% "
        "(precisa fechar em 100% para salvar)</div>",
        unsafe_allow_html=True,
    )
    if c_add.button("Adicionar item", key=f"{itens_key}_add", icon=":material/add:"):
        proximo_numero = max((item["numero"] for item in itens_sessao), default=0) + 1
        itens_sessao.append({"numero": proximo_numero, "percentual": 0.0})
        st.rerun(scope="fragment")

    # Indicadores do topo (calculados acima, a partir do que está digitado).
    saldo_execucao = linha["saldo_execucao"]
    valor_empenhado_execucao = linha["valor_empenhado_execucao"]
    meses_pagos = linha["meses_pagos"]
    texto_meses_pagos = (
        f"{_num(meses_pagos)} · {_fmt_mes(linha['ultimo_mes_pago'])}" if pd.notna(meses_pagos) else "sem dado"
    )
    valor_vigente, definidor_valor = valor_vigente_em(despesa_mensal, aditivos_editados, dia_de_referencia(ano_exercicio))
    texto_valor_vigente = formatar_brl(valor_vigente) if valor_vigente is not None else "sem valor"
    if definidor_valor is not None:
        texto_valor_vigente += f" · {definidor_valor.numero or 'aditivo'}" + (" (previsto)" if definidor_valor.previsto else "")
    vigencia_efetiva_data, definidor_vig = vigencia_efetiva(vigencia, aditivos_editados)
    texto_vigencia_efetiva = vigencia_efetiva_data.strftime("%d/%m/%Y") if pd.notna(vigencia_efetiva_data) else "sem data"
    if definidor_vig is not None:
        texto_vigencia_efetiva += f" · {definidor_vig.numero or 'aditivo'}" + (" (previsto)" if definidor_vig.previsto else "")
    with topo:
        st.markdown(
            grade_indicadores([
                # mesma Necessidade até dezembro da coluna "A empenhar" do registro (cadastro gravado); o saldo
                # em meses, recalculado ao vivo, segue em "Meses de saldo"
                ("A empenhar (até dezembro)", formatar_brl(linha["necessidade_ate_dezembro"]) if pd.notna(linha["necessidade_ate_dezembro"]) else "sem dado"),
                ("Despesa anual (empenhado — suspenso)" if status == "SUSPENSO" else "Despesa anual", formatar_brl(despesa_anual)),
                ("Empenhado (Execução Mensal)", formatar_brl(valor_empenhado_execucao) if pd.notna(valor_empenhado_execucao) else "sem NE"),
                ("Saldo (Execução Mensal)", formatar_brl(saldo_execucao) if pd.notna(saldo_execucao) else "sem NE"),
                ("Meses de saldo", _num(meses_a_empenhar)),
                ("Valor mensal vigente", texto_valor_vigente),
                ("Vigência efetiva", texto_vigencia_efetiva),
                ("Meses pagos (Pagamentos) · último mês", texto_meses_pagos),
            ]),
            unsafe_allow_html=True,
        )

    # valor_empenhado_execucao é sempre no nível da NE inteira (mesmo valor em todo item do mesmo
    # contrato/NE) — `diverge_valor_empenhado` já vem pronto de `com_saldo_execucao` (comparado
    # contra a SOMA dos itens da NE, não o item desta linha).
    diverge_saldo = pd.notna(saldo_execucao) and abs(saldo_execucao - saldo_planilha) > 0.01
    diverge_valor_empenhado = bool(linha["diverge_valor_empenhado"]) if pd.notna(linha["diverge_valor_empenhado"]) else False
    # a necessidade é a do cadastro gravado (Resumo Consolidado); status e vigência, os digitados
    texto_situacao, tom_situacao = _situacao(status, vigencia_efetiva_data, linha["necessidade_ate_dezembro"])
    if pd.isna(saldo_execucao):
        texto_div, tom_div = "Sem Execução", "bad"
    elif diverge_saldo or diverge_valor_empenhado:
        texto_div, tom_div = "Diverge da Execução", "bad"
    else:
        texto_div, tom_div = "Bate com a Execução", "ok"

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    f_chips, f_salvar, f_cancelar = st.columns([3, 1, 1], vertical_alignment="center")
    f_chips.markdown(chip(texto_situacao, tom_situacao) + " " + chip(texto_div, tom_div), unsafe_allow_html=True)
    if f_cancelar.button("Cancelar", key=f"{k}_cancelar", use_container_width=True):
        st.session_state.pop(itens_key, None)
        st.session_state.pop(f"{k}_aditivos", None)
        st.rerun()
    if f_salvar.button("Salvar", key=f"{k}_salvar", type="primary", icon=":material/save:", use_container_width=True):
        erros_aditivos = validar_aditivos(aditivos_editados)
        if abs(soma_percentuais - 100) > 0.5:
            st.error(f"A soma dos percentuais dos itens precisa fechar em 100% (está em {soma_percentuais:.1f}%).")
        elif erros_aditivos:
            for erro in erros_aditivos:
                st.error(erro)
        else:
            atualizado = {
                **linha.to_dict(),
                "fornecedor": fornecedor or None, "status_contrato": status,
                "vigencia_fim": pd.Timestamp(vigencia) if vigencia else None,
                "contrato_numero": numero or None, "ano_contrato": ano,
                "processo_contratacao": processo_contratacao.strip() or None,
                "processo_empenho": processo_empenho.strip() or None,
                "fornecedor_cnpj_cpf": cnpj or None, "tipo_despesa": tipo_despesa or None,
                "unidade_cod": unidade or None, "acao_cod": acao or None, "ptres": ptres or None,
                "natureza_despesa_cod": nd or None, "ugr_cod": ugr or None, "pi_cod": pi or None,
                "ne_curta": ne_curta.strip() or None, "despesa_mensal": despesa_mensal,
                "meses_no_ano": meses_no_ano,
                "valor_empenhado": valor_empenhado, "saldo_colado_planilha": saldo_planilha,
                "meses_empenhados": meses_empenhados_persistir, "meses_liquidados": meses_liquidados_persistir,
                "itens": [dict(item) for item in itens_sessao],
                "inicio_execucao_mes": inicio_execucao_mes_editado,
                "inicio_execucao_data": pd.Timestamp(inicio_execucao_data_editada) if inicio_execucao_data_editada else None,
                "data_suspensao": pd.Timestamp(data_suspensao) if data_suspensao else None,
                "aditivos": [aditivo_para_registro(a) for a in aditivos_editados],
            }
            for chave_extra in (
                "despesa_anual", "meses_a_empenhar", "valor_a_empenhar", "saldo_execucao",
                "diverge_saldo", "valor_empenhado_execucao", "diverge_valor_empenhado",
                "valor_liquidado_execucao", "liquidado_via_competencia", "valor_empenhado_planilha_total_ne",
                "despesa_mensal_total_ne", "meses_empenhados_execucao", "meses_liquidados_execucao",
                "necessidade_via", "meses_pagos", "ultimo_mes_pago", "contrato_normalizado",
                "tem_varios_itens", "inicio_execucao_efetivo", "valor_empenhado_autoritativo",
                "despesa_anual_contratual", "despesa_anual_base",
                "vigencia_fim_efetiva", "valor_mensal_vigente", "tem_aditivo_previsto",
                "necessidade_ate_dezembro", "sem_liquidacao_confirmada",
            ):
                atualizado.pop(chave_extra, None)
            atualizar_contrato(ano_exercicio, atualizado)
            st.session_state.pop(itens_key, None)
            st.session_state.pop(f"{k}_aditivos", None)
            st.toast("Contrato salvo.", icon=":material/check_circle:")
            st.rerun()


@st.dialog("Remover contrato")
def _dialogo_remover_contrato(id_contrato: str, rotulo: str, ano_exercicio: int) -> None:
    """Confirmação de remoção (substitui o antigo "Remover" + "Confirmar exclusão?" do cartão).
    Remover apaga o registro do cadastro do exercício; não há como desfazer."""

    st.markdown(f"Remover **{rotulo}** do exercício {ano_exercicio}?")
    st.caption("O registro é apagado do cadastro deste exercício. Não há como desfazer.")
    c_confirmar, c_cancelar = st.columns(2)
    if c_cancelar.button("Cancelar", key=f"cc_remover_cancelar_{id_contrato}", use_container_width=True):
        st.rerun()
    if c_confirmar.button("Remover", key=f"cc_remover_confirmar_{id_contrato}", type="primary", use_container_width=True):
        excluir_contrato(ano_exercicio, id_contrato)
        st.toast("Contrato removido.", icon=":material/delete:")
        st.rerun()


@st.dialog("Novo contrato", width="large")
def _dialogo_novo_contrato(ano_exercicio: int, source_key: str, valores: dict | None = None) -> None:
    """Formulário de "+ Novo contrato" em janela, organizado em seções (era um popover estreito com
    20 campos empilhados). Grava direto no cadastro nativo do exercício em tela
    (`src/contratos_continuos_cadastro.py`).

    `ano_exercicio` (parâmetro, o exercício em tela) != `ano` (campo do formulário, o ano do
    próprio contrato) — nomes diferentes de propósito, para não colidir.

    `valores` (opcional, 10/2026): argumentos de `novo_contrato` já preenchidos a partir de um contrato do
    Contratos.gov (`registro_novo_do_gov`) — só o que o gov tem; o resto fica no padrão do formulário. Nada é
    gravado até "Adicionar contrato". `fonte_cod` não tem campo no formulário: segue direto para o registro."""

    valores = valores or {}
    if valores.get("fonte_cod"):
        st.caption(
            f"Fonte {valores['fonte_cod']} (da NE {valores.get('ne_curta') or '—'} escolhida no gov) vai junto com o "
            "contrato — o formulário não tem campo de fonte; se trocar a NE abaixo, a fonte continua a da NE escolhida."
        )
    with st.form(f"contratos_continuos_form_{source_key}", clear_on_submit=True, border=False):
        _secao("Identificação")
        c1, c2, c3 = st.columns([1, 2.2, 1])
        numero = c1.text_input("Nº do contrato", value=valores.get("contrato_numero") or "")
        fornecedor = c2.text_input("Fornecedor", value=valores.get("fornecedor") or "")
        ano = c3.number_input("Ano", min_value=2000, max_value=2100, value=int(valores.get("ano_contrato") or 2026), step=1)
        c4, c5, c6 = st.columns(3)
        cnpj = c4.text_input("CNPJ/CPF", value=valores.get("fornecedor_cnpj_cpf") or "")
        tipo_despesa = c5.text_input("Tipo de despesa")
        status = c6.selectbox("Status", STATUS_OPCOES)
        c7, c8 = st.columns(2)
        processo_contratacao = c7.text_input("Processo da contratação")
        processo_empenho = c8.text_input("Processo de empenho")

        _secao("Período de execução")
        p1, p2, p3 = st.columns(3)
        vigencia = p1.date_input(
            "Vigência (fim) — opcional", value=_data_ou_none(valores.get("vigencia_fim")), format="DD/MM/YYYY",
            min_value=date(2000, 1, 1), max_value=date(2100, 12, 31),
        )
        inicio_data = p2.date_input(
            "Início da execução — opcional", value=None, format="DD/MM/YYYY",
            min_value=date(2000, 1, 1), max_value=date(2100, 12, 31),
        )
        # meses_no_ano: total de meses que o contrato é pago no exercício — 12 por padrão (contrato
        # "contínuo" de verdade), menor para um contrato que só roda parte do ano.
        meses_no_ano = p3.number_input(
            "Meses no ano", min_value=1, max_value=12, value=None, placeholder="12",
            help="Em branco vale 12 (contrato contínuo o ano inteiro); menos, se só roda parte do ano.",
        )
        p4, _ = st.columns([1, 2])
        data_suspensao = p4.date_input(
            "Data da suspensão — opcional", value=None, format="DD/MM/YYYY",
            min_value=date(2000, 1, 1), max_value=date(2100, 12, 31),
            help="Só vale com o status SUSPENSO: a partir desta data o contrato não gera necessidade, projeção "
                 "nem sugestão de reforço.",
        )

        _secao("Classificação orçamentária")
        q = st.columns(5)
        unidade = q[0].text_input("Unidade")
        acao = q[1].text_input("Ação")
        ptres = q[2].text_input("PTRES")
        nd = q[3].text_input("ND", value=valores.get("natureza_despesa_cod") or "")
        ugr = q[4].text_input("UGR")
        pi = st.text_input("PI", value=valores.get("pi_cod") or "")

        _secao("Empenho e valores")
        e1, e2, e3 = st.columns(3)
        ne_curta = e1.text_input("NE (opcional)", value=valores.get("ne_curta") or "", placeholder="ex. 2026NE000999")
        # em branco = sem dado (nulo), não zero — decisão do usuário (10/2026); o zero precisa ser digitado
        despesa_mensal = e2.number_input("Despesa mensal (R$)", min_value=0.0, step=100.0, value=None, placeholder="em branco")
        valor_empenhado = e3.number_input("Valor empenhado (R$)", min_value=0.0, step=100.0, value=None, placeholder="em branco")
        e4, e5, e6 = st.columns(3)
        saldo_colado = e4.number_input("Saldo colado na planilha (R$)", min_value=0.0, step=100.0, value=None, placeholder="em branco")
        meses_empenhados = e5.number_input("Meses empenhados", min_value=0.0, step=0.1, value=None, placeholder="em branco")
        meses_liquidados = e6.number_input("Meses liquidados", min_value=0.0, step=0.1, value=None, placeholder="em branco")

        if st.form_submit_button("Adicionar contrato", type="primary", icon=":material/add:"):
            if not numero or not fornecedor:
                st.error("Informe ao menos o número do contrato e o fornecedor.")
            else:
                registro = novo_contrato_do_formulario(
                    contrato_numero=numero, ano_contrato=ano, status_contrato=status,
                    processo_contratacao=processo_contratacao.strip() or None,
                    processo_empenho=processo_empenho.strip() or None,
                    vigencia_fim=pd.Timestamp(vigencia) if vigencia else None,
                    inicio_execucao_data=pd.Timestamp(inicio_data) if inicio_data else None,
                    data_suspensao=pd.Timestamp(data_suspensao) if data_suspensao else None,
                    fornecedor=fornecedor, fornecedor_cnpj_cpf=cnpj, tipo_despesa=tipo_despesa,
                    unidade_cod=unidade, acao_cod=acao, ptres=ptres,
                    natureza_despesa_cod=nd, ugr_cod=ugr, pi_cod=pi, fonte_cod=valores.get("fonte_cod"),
                    ne_curta=ne_curta.strip() or None, despesa_mensal=despesa_mensal,
                    meses_no_ano=meses_no_ano,
                    valor_empenhado=valor_empenhado, saldo_colado_planilha=saldo_colado,
                    meses_empenhados=meses_empenhados, meses_liquidados=meses_liquidados,
                )
                salvar_contrato(ano_exercicio, registro)
                st.toast("Contrato cadastrado.", icon=":material/check_circle:")
                st.rerun()


def _render_novo_contrato(ano_exercicio: int, source_key: str) -> None:
    """Botão principal "Novo contrato" (canto do cabeçalho), que abre `_dialogo_novo_contrato`."""

    with st.container(key="cad_novo"):
        if st.button("Novo contrato", icon=":material/add:", type="primary", use_container_width=True, key=f"cc_novo_{source_key}"):
            _dialogo_novo_contrato(ano_exercicio, source_key)


def _render_novos_contratosgov(
    candidatos: pd.DataFrame, em_duvida: pd.DataFrame, ano_exercicio: int, source_key: str
) -> None:
    """"Novos no Contratos.gov" (10/2026): contratos vigentes do gov que ainda não estão no cadastro do exercício
    (`candidatos_novos` — o gov não informa se o contrato é contínuo, então todos os vigentes ausentes são
    listados e o usuário escolhe) e os que ficaram em dúvida (sem botão, com o motivo). "Incluir" abre a janela
    "Novo contrato" já preenchida com o que o gov tem (`registro_novo_do_gov`); nada é gravado até "Adicionar
    contrato". Contrato com várias NEs pede a escolha da NE (ND, PI e fonte vêm da NE escolhida); com uma só, ela
    é usada; sem empenhos, a NE fica em branco. A parcela do gov é só referência."""

    if candidatos.empty and em_duvida.empty:
        return
    rotulo = f"Novos no Contratos.gov ({len(candidatos)} candidato(s) · {len(em_duvida)} em dúvida)"
    with st.expander(rotulo, expanded=False):
        st.caption(
            "Contratos vigentes no Contratos.gov que ainda não estão no cadastro deste exercício (o gov não informa "
            "se o contrato é contínuo — você escolhe). “Incluir” abre o formulário de novo contrato já preenchido com "
            "o que o gov tem; nada é gravado até “Adicionar contrato”. A parcela do gov é só referência (contrato "
            "inteiro, não a parcela da ação 20RK)."
        )
        # busca e "ocultar parcela zero" só reduzem o que é MOSTRADO (`filtrar_candidatos`): quem é candidato e a
        # contagem do rótulo acima não mudam. Começam sem efeito.
        visiveis = candidatos
        if not candidatos.empty:
            coluna_busca, coluna_zero = st.columns([3, 2], vertical_alignment="bottom")
            busca = coluna_busca.text_input(
                "Buscar candidato", key=f"cc_gov_busca_{source_key}", placeholder="Número, fornecedor ou CNPJ/CPF"
            )
            ocultar_zero = coluna_zero.checkbox(
                "Ocultar contratos com parcela R$ 0 no gov", value=False, key=f"cc_gov_ocultar_zero_{source_key}",
                help="Esconde só quem tem parcela zero declarada no gov (acordos de cessão/cooperação, em geral). "
                     "Parcela sem dado continua aparecendo.",
            )
            visiveis = filtrar_candidatos(candidatos, busca, ocultar_zero)
            if len(visiveis) != len(candidatos):
                st.caption(f"Mostrando {len(visiveis)} de {len(candidatos)} candidato(s).")
        for _, candidato in visiveis.iterrows():
            contrato_id = candidato["contrato_id"]
            coluna_info, coluna_ne, coluna_botao = st.columns([4, 2, 1], vertical_alignment="center")
            parcela = _brl(float(candidato["valor_parcela"])) if pd.notna(candidato["valor_parcela"]) else "sem dado"
            coluna_info.markdown(
                f"**{_md(candidato['numero'])}** — {_md(_ou_traco(candidato['fornecedor_nome']))}"
                f" · vigência até {_fmt_data_gov(candidato['vigencia_fim'])} · parcela no gov (ref.) {parcela}"
            )
            nes = [item["ne"] for item in candidato["nes"]]
            ne_escolhida = nes[0] if len(nes) == 1 else None
            if len(nes) > 1:
                escolha = coluna_ne.selectbox(
                    "NE do contrato", ["—", *nes], key=f"cc_gov_ne_{contrato_id}", label_visibility="collapsed",
                )
                ne_escolhida = None if escolha == "—" else escolha
            elif nes:
                coluna_ne.caption(f"NE {nes[0]}")
            else:
                coluna_ne.caption("sem empenhos no gov")
            if coluna_botao.button("Incluir", key=f"cc_gov_incluir_{contrato_id}", use_container_width=True):
                _dialogo_novo_contrato(ano_exercicio, source_key, registro_novo_do_gov(candidato, ne_escolhida))
        if not em_duvida.empty:
            st.markdown("**Em dúvida — não incluídos automaticamente**")
            for _, candidato in em_duvida.iterrows():
                st.markdown(
                    f"**{_md(candidato['numero'])}** — {_md(_ou_traco(candidato['fornecedor_nome']))} · {_md(candidato['motivo'])}"
                )


def _texto_meses_liquidados(meses_liquidados: object, ultimo_mes_liquidado: object) -> str:
    """"7 · ago/26" a partir de `meses_liquidados`/`ultimo_mes_liquidado`
    (`_meses_liquidados_por_ne_curta`, Liquidação por Competência) — "sem dado" quando a NE não
    tem nenhum mês de competência com liquidação > 0 (não é "0 meses": ausência de dado, não
    liquidação zero). Usada só nas colunas "Meses Liquidados" do Resumo Consolidado/Empenhado
    × Liquidado (pedido explícito posterior: antes essa coluna vinha da planilha separada de
    Pagamentos — "Meses Pagos" — e virou este critério de competência; o detalhe "Meses Pagos
    (Pagamentos)" dentro de cada cartão continua vindo de `com_meses_pagos`, sem mudança, é uma
    métrica diferente)."""

    if pd.isna(meses_liquidados):
        return "sem dado"
    return f"{_num(meses_liquidados)} · {_fmt_mes(ultimo_mes_liquidado)}"


#: larguras relativas usadas por `st.columns` no cabeçalho de rótulos, em cada linha e no
#: rodapé do Resumo Consolidado — as três precisam ser exatamente as mesmas pra alinhar. A última
#: coluna é o botão de ícone da "Linha do tempo mensal".
_LARGURAS_RESUMO = [3.0, 1.3, 1.3, 1.4, 1.2, 0.8]
_CABECALHOS_RESUMO = [
    ("Fornecedor / Contrato", False), ("Valor empenhado", True), ("Saldo", True),
    ("Necessidade até dez.", True), ("Meses liquidados", False), ("Linha do tempo", False),
]

#: mesmo padrão de "Ver mais" de um clique só (não incremental) do registro de contratos abaixo —
#: pedido explícito estendido para este card também, com as linhas numa caixa com barra de rolagem.
QTD_INICIAL_RESUMO = 3


def _tempo_com_liquidacao_por_competencia(
    tempo_ne: pd.DataFrame, ne_curta_valor: str, competencia_por_ne_mes: pd.DataFrame
) -> pd.DataFrame:
    """Troca a coluna `liquidada` de `tempo_ne` (mês de LANÇAMENTO, Execução Mensal) pela
    liquidação por COMPETÊNCIA (mês de referência) da mesma NE — mesma lógica de
    `app_pages/consulta_empenhos.py::_tempo_com_liquidacao_por_competencia`, adaptada aqui
    pra indexar por `ne_curta` (não `ne_ccor`): esta página já trabalha com a forma curta em
    toda parte (cadastro nativo não guarda o `ne_ccor` completo). `empenhada`/`paga`
    continuam vindo da Execução Mensal, sem mudança; NE sem nenhuma linha de competência
    mostra Liquidado 0 em todo mês, sem cair de volta pro valor de lançamento (mesma decisão
    de v1 da Consulta de Empenhos)."""

    base = tempo_ne[["ano_mes", "empenhada", "paga"]]
    competencia_ne = competencia_por_ne_mes.loc[
        competencia_por_ne_mes["ne_curta"] == ne_curta_valor, ["ano_mes", "valor"]
    ].rename(columns={"valor": "liquidada"})

    combinado = pd.merge(base, competencia_ne, on="ano_mes", how="outer")
    combinado[["empenhada", "liquidada", "paga"]] = combinado[["empenhada", "liquidada", "paga"]].fillna(0.0)
    return combinado.sort_values("ano_mes").reset_index(drop=True)


_COLUNAS_MESES_LIQUIDADOS = ["ne_curta", "meses_liquidados", "ultimo_mes_liquidado"]


def _meses_liquidados_por_ne_curta(liquidacao_competencia_por_mes: pd.DataFrame | None) -> pd.DataFrame:
    """Quantidade de meses com Liquidação por Competência > 0, e o mais recente deles, por NE
    curta — pedido explícito posterior: a coluna "Meses Pagos" do Resumo Consolidado/Empenhado
    × Liquidado virou "Meses Liquidados", trocando a fonte da planilha separada de Pagamentos
    (`com_meses_pagos`) pela Liquidação por Competência — o que interessa ali agora é quantos
    meses a NE já teve liquidação apurada por competência, não quantos meses tiveram pagamento
    registrado. O detalhe "Meses Pagos (Pagamentos)" dentro de cada cartão (r5 do expander)
    continua vindo de `com_meses_pagos`, sem mudança — é uma métrica diferente, fora do escopo
    deste pedido.

    Mês com `valor` líquido ≤ 0 (só estorno, sem liquidação nova apurada naquele mês) não conta
    como "mês liquidado" — critério deliberado, para não contar como liquidação um mês que só
    teve cancelamento. Sem a base de competência (arquivo ausente), devolve um DataFrame vazio
    — toda NE cai em "sem dado" (`_texto_meses_liquidados`), mesma ausência silenciosa do resto
    da página."""

    if liquidacao_competencia_por_mes is None:
        return pd.DataFrame(columns=_COLUNAS_MESES_LIQUIDADOS)

    positivos = liquidacao_competencia_por_mes[liquidacao_competencia_por_mes["valor"] > 0]
    if positivos.empty:
        return pd.DataFrame(columns=_COLUNAS_MESES_LIQUIDADOS)

    agrupado = positivos.groupby("ne_curta")["ano_mes"].agg(meses_liquidados="count", ultimo_ano_mes="max").reset_index()
    agrupado["ultimo_mes_liquidado"] = pd.to_datetime(agrupado["ultimo_ano_mes"].astype(int).astype(str), format="%Y%m")
    return agrupado[_COLUNAS_MESES_LIQUIDADOS]


def _render_linhas_resumo(
    linhas: list[tuple],
    tempo_por_ne_curta: pd.DataFrame | None,
    liquidacao_competencia_por_mes: pd.DataFrame | None,
    nes_com_tempo: set[str],
    source_key: str,
) -> tuple[str, pd.DataFrame, str] | None:
    """Cabeçalho + uma linha por item de `linhas` (mesmas colunas do Resumo Consolidado). As linhas ficam numa
    caixa de altura máxima com barra de rolagem (`.st-key-cc_resumo_scroll` em `src/ui_cadastro.py`, pedido
    explícito — antes "Ver mais" abria um pop-up com a lista completa); o cabeçalho fica fora dela.

    Layout de 05/10/2026 (mesmo do registro dos cadastros, `src/ui_cadastro.py`): linha com título/subtítulo,
    valores à direita e, quando a NE tem dado na base mensal, um botão de ÍCONE na última coluna (antes a
    linha inteira era o botão). Chaves dos botões: `cc_resumo_tempo_{source_key}_{ne}`.

    NÃO abre o pop-up "Linha do tempo mensal" sozinha — devolve `(legenda, tempo_ne, base_liquidado)` quando
    alguma linha foi clicada nesta execução (`None` caso contrário) e o chamador chama `abrir_linha_do_tempo`
    fora do cartão."""

    cabecalho = st.columns(_LARGURAS_RESUMO)
    for coluna, (texto, a_direita) in zip(cabecalho, _CABECALHOS_RESUMO):
        coluna.markdown(
            f'<div class="cad-cabecalho{" direita" if a_direita else ""}">{texto}</div>', unsafe_allow_html=True
        )

    clicado: tuple[str, pd.DataFrame, str] | None = None
    with st.container(key="cc_resumo_scroll"):
        for posicao, (fornecedor, contrato_numero, ne_curta_linha, valor_empenhado, saldo, necessidade, meses_liquidados, ultimo_mes_liquidado) in enumerate(linhas):
            clicavel = pd.notna(ne_curta_linha) and ne_curta_linha in nes_com_tempo
            numero = _ou_vazio(contrato_numero)
            subtitulo = " · ".join(
                parte for parte in (f"Contrato {numero}" if numero else "", f"NE {ne_curta_linha}" if pd.notna(ne_curta_linha) else "sem NE") if parte
            )
            with st.container(key=f"cad_linha_cc_resumo_{source_key}_{posicao}"):
                linha = st.columns(_LARGURAS_RESUMO, vertical_alignment="center")
                linha[0].markdown(
                    celula_principal(_ou_vazio(fornecedor) or "(sem fornecedor)", subtitulo), unsafe_allow_html=True
                )
                linha[1].markdown(celula_valor(valor_empenhado, vazio="sem NE"), unsafe_allow_html=True)
                linha[2].markdown(celula_valor(saldo, vazio="sem NE"), unsafe_allow_html=True)
                linha[3].markdown(
                    celula_valor(necessidade, "warn" if _ou_zero(necessidade) > 0 else None, vazio="sem NE"), unsafe_allow_html=True
                )
                linha[4].markdown(
                    celula_suave(_texto_meses_liquidados(meses_liquidados, ultimo_mes_liquidado)), unsafe_allow_html=True
                )
                if clicavel and linha[5].button(
                    "", icon=":material/show_chart:", key=f"cc_resumo_tempo_{source_key}_{ne_curta_linha}",
                    help="Abrir a linha do tempo mensal desta NE", use_container_width=True,
                ):
                    tempo_ne = tempo_por_ne_curta[tempo_por_ne_curta["ne_curta"] == ne_curta_linha]
                    if liquidacao_competencia_por_mes is not None:
                        tempo_ne = _tempo_com_liquidacao_por_competencia(
                            tempo_ne, ne_curta_linha, liquidacao_competencia_por_mes
                        )
                        base_liquidado = BASE_LIQUIDADO_COMPETENCIA
                        legenda = (
                            f"{_dash(fornecedor)} (NE {ne_curta_linha}) — Empenhado e Pago por mês de "
                            "lançamento (Execução Mensal); Liquidado por mês de competência (Liquidação "
                            "por Competência), não por mês de lançamento."
                        )
                    else:
                        legenda = f"{_dash(fornecedor)} (NE {ne_curta_linha}) — Execução Mensal (BI CPOC)."
                        base_liquidado = BASE_LIQUIDADO_EXECUCAO_MENSAL
                    clicado = (legenda, tempo_ne, base_liquidado)
    return clicado


def _render_rodape_resumo(valor_empenhado_total: float, saldo_total: float, necessidade_total: float, key: str) -> None:
    """Linha de total do Resumo Consolidado (mesmas larguras do cabeçalho/linhas)."""

    with st.container(key=f"cad_total_{key}"):
        rodape = st.columns(_LARGURAS_RESUMO)
        rodape[0].markdown('<div class="cad-total-rotulo">Total</div>', unsafe_allow_html=True)
        rodape[1].markdown(celula_valor(valor_empenhado_total, vazio="sem NE"), unsafe_allow_html=True)
        rodape[2].markdown(celula_valor(saldo_total, vazio="sem NE"), unsafe_allow_html=True)
        rodape[3].markdown(
            celula_valor(necessidade_total, "warn" if _ou_zero(necessidade_total) > 0 else None), unsafe_allow_html=True
        )


def _render_resumo_consolidado(
    filtrado: pd.DataFrame,
    tempo_por_ne_curta: pd.DataFrame | None,
    source_key: str,
    liquidacao_competencia_por_mes: pd.DataFrame | None = None,
    meses_liquidados_por_ne: pd.DataFrame | None = None,
    ano_exercicio: int | None = None,
) -> None:
    """Card único, visível de início (antes de abrir qualquer cartão), listando — uma linha
    por NE, não por item de licitação nem um total agregado — o valor empenhado, o saldo e a
    necessidade de empenho até dezembro. Diferente de `bolsas_auxilios.py` (1 linha == 1
    bolsa == 1 NE), aqui um contrato pode ter vários itens de licitação na mesma NE — agrupa-
    se por NE antes de listar, mesma unidade já usada por `_somar_unico_por_ne`/
    `_contar_unico_por_ne`, para não repetir a mesma NE várias vezes nem contar seu saldo mais
    de uma vez. Itens sem NE (contrato ainda sem empenho) aparecem à parte, um por linha, já
    que não há NE para agrupar — e nunca são clicáveis (não há NE pra buscar na base mensal).

    Pedido explícito: cada NE com dado na base MENSAL (2024+) é clicável — abre o mesmo pop-up
    "Linha do tempo mensal" de `app_pages/bolsas_auxilios.py`/`app_pages/consulta_empenhos.py`
    (`src/ui_linha_do_tempo.py`, compartilhado). Cada linha é um `st.button` de verdade (não
    HTML) quando clicável — HTML puro não dispara evento Python — daí o cartão também ter
    virado `st.container(border=True)` (ver `_inject_css`).

    Liquidado por COMPETÊNCIA no pop-up (pedido explícito posterior, mesma troca de
    `app_pages/consulta_empenhos.py`): com `liquidacao_competencia_por_mes` disponível, o
    Liquidado mostrado no pop-up vem do mês de referência/competência, não mais do mês de
    lançamento — ver `_tempo_com_liquidacao_por_competencia`. Sem a base de competência, o
    pop-up volta ao comportamento anterior (Liquidado por lançamento).

    Saldo/Necessidade até Dezembro por COMPETÊNCIA (pedido explícito posterior — via
    `dataframe`/`filtrado`, que já chega com `valor_liquidado_execucao`/
    `liquidado_via_competencia` de `com_saldo_execucao`, não um parâmetro novo aqui): por NE
    com competência apurada, `saldo_para_necessidade` = Empenhado − Liquidado por
    COMPETÊNCIA, e é esse valor (não `saldo_execucao`) que aparece na coluna "Saldo" e alimenta
    "Necessidade até Dezembro" — as duas colunas deste card continuam batendo entre si. NE sem
    competência apurada (arquivo ausente, ou nenhuma linha ainda para aquela NE) cai no
    `saldo_execucao` de sempre (Execução Mensal, por lançamento), nunca mistura as duas dentro
    do mesmo NE. Antes este card usava sempre `saldo_execucao`, inconsistente com o resto da
    página (que já mostrava Liquidado por competência) — corrigido a pedido do usuário.

    Minimizado por padrão (`QTD_INICIAL_RESUMO`, pedido explícito) — o card sempre mostra só
    as `QTD_INICIAL_RESUMO` primeiras linhas; os totais do card (cabeçalho e rodapé) somam
    sempre o conjunto inteiro (`por_ne`/`sem_ne` completos), não só o que está à mostra.

    "Ver mais" (um clique só) mostra a lista completa dentro do próprio card, numa caixa com barra de
    rolagem (pedido explícito posterior — antes abria um pop-up; a rolagem também evita empurrar o
    resto da página pra baixo com dezenas de linhas). "Ver menos" volta às primeiras linhas.

    Coluna "Meses Liquidados" (pedido explícito posterior — antes "Meses Pagos", vinda da
    planilha separada de Pagamentos): agora vem de `meses_liquidados_por_ne`
    (`_meses_liquidados_por_ne_curta`, Liquidação por Competência) — quantos meses a NE já tem
    de liquidação apurada por competência, não quantos meses tiveram pagamento registrado.

    Meses AINDA DEVIDOS no exercício (pedido explícito, mesma correção de
    `app_pages/bolsas_auxilios.py::_render_resumo_consolidado` — ver lá para o caso real que
    motivou, AUXÍLIO BEXT parcela única): substitui o antigo "meses restantes até dezembro"
    GLOBAL (removido junto de `_meses_restantes_no_ano`) por um teto POR NE/CONTRATO
    (`meses_no_ano`, cadastro) menos quanto dele já foi empenhado (`valor_empenhado ÷
    despesa_mensal`) — sem isso, um contrato com vigência menor que o exercício (ou já com toda
    sua despesa anual empenhada) continuava sugerindo reforço só por causa do calendário. NE/
    contrato sem `meses_no_ano` cadastrado cai no padrão de 12 (mesmo critério "contínuo" de
    antes desta correção — a maioria dos contratos continua nesse padrão)."""

    # A regra (saldo por competência/lançamento, meses restantes, necessidade) vive em
    # `src/relatorio_necessidade_empenho.py::necessidade_por_ne` — a MESMA função alimenta o
    # relatório PDF/Excel logo abaixo do card, para tela e arquivo nunca divergirem.
    # Saldo usado na Necessidade até Dezembro (pedido explícito posterior): por NE com
    # competência apurada (`liquidado_via_competencia` E `valor_liquidado_execucao` notna —
    # ver `com_saldo_execucao`), Empenhado − Liquidado por COMPETÊNCIA, não por lançamento;
    # sem competência para aquela NE (arquivo ausente, ou NE sem nenhuma linha apurada ainda),
    # cai no `saldo_execucao` de sempre (Execução Mensal, por lançamento) — mesmo critério de
    # fallback por linha já usado em `com_saldo_execucao`, nunca mistura as duas dentro do
    # mesmo NE. Diferente do quadro "Empenhado × Liquidado" (saldo sempre por lançamento, ali
    # por ser o saldo formal comparado contra o TG): aqui não há essa comparação, então o
    # saldo pode acompanhar a fonte mais correta do Liquidado sem gerar contradição visível.
    por_ne, sem_ne = necessidade_por_ne(filtrado, meses_liquidados_por_ne, ano_exercicio)
    algum_ne_via_competencia = bool(
        (por_ne["liquidado_via_competencia"].fillna(False) & por_ne["valor_liquidado_execucao"].notna()).any()
    )

    linhas = [
        (
            row["fornecedor"], row["contrato_numero"], row["ne_curta"], row["valor_empenhado_exibido"],
            row["saldo_para_necessidade"], row["necessidade"], row["meses_liquidados"], row["ultimo_mes_liquidado"],
        )
        for _, row in por_ne.sort_values("necessidade", ascending=False).iterrows()
    ] + [
        (
            row["fornecedor"], row["contrato_numero"], pd.NA, row["valor_empenhado_exibido"],
            pd.NA, row["necessidade"], pd.NA, pd.NA,
        )
        for _, row in sem_ne.sort_values("necessidade", ascending=False).iterrows()
    ]

    necessidade_total = por_ne["necessidade"].sum() + sem_ne["necessidade"].sum()
    valor_empenhado_total = por_ne["valor_empenhado_exibido"].sum() + sem_ne["valor_empenhado_exibido"].sum()
    total_linhas = len(por_ne) + len(sem_ne)
    nes_com_tempo = set(tempo_por_ne_curta["ne_curta"]) if tempo_por_ne_curta is not None else set()
    aviso_tempo = aviso_linha_do_tempo(por_ne["ne_curta"], nes_com_tempo, tempo_por_ne_curta is not None)

    saldo_total = por_ne["saldo_para_necessidade"].sum()
    mostrar_todos_key = f"cc_resumo_mostrar_todos_{source_key}"
    mostrar_todos = st.session_state.get(mostrar_todos_key, False)
    visiveis = linhas if mostrar_todos else linhas[:QTD_INICIAL_RESUMO]

    with st.container(border=True, key=f"cad_secao_resumo_cc_{source_key}"):
        st.markdown(
            topo_secao(
                "Necessidade de Empenho por NE",
                None,
                {
                    "rotulo": "Necessidade até dezembro",
                    "valor": formatar_brl(necessidade_total),
                    "detalhe": f"{total_linhas} {'NE/contrato' if total_linhas == 1 else 'NEs/contratos'}",
                    "tom": "warn" if necessidade_total > 0 else "ok",
                },
                kicker="RESUMO CONSOLIDADO",
            ),
            unsafe_allow_html=True,
        )
        sem_necessidade_por_vigencia = int((por_ne["meses_vigentes"] == 0).sum() + (sem_ne["meses_vigentes"] == 0).sum())
        if ano_exercicio is not None:
            st.caption(
                "Necessidade = o que falta empenhar para cobrir os meses do exercício (despesa mensal × meses "
                "restantes). Respeita o início da execução e o fim da vigência (meses inicial e final "
                "proporcionais) e o status SUSPENSO"
                + (
                    f" — {sem_necessidade_por_vigencia} contrato(s) sem necessidade por estarem suspensos, "
                    "vencidos ou com a vigência encerrada."
                    if sem_necessidade_por_vigencia else "."
                )
            )
            if por_ne["inclui_previsto"].any() or sem_ne["inclui_previsto"].any():
                st.caption(
                    "A necessidade inclui valores estimados de aditivos previstos (ainda não assinados); "
                    "o relatório de Necessidade de Empenho os marca e lista nos avisos."
                )
        if algum_ne_via_competencia:
            st.caption(
                "Saldo/Necessidade usa Liquidado por competência (mês de referência) para as NEs com "
                "competência já apurada; sem competência para a NE, continua por lançamento (Execução Mensal)."
            )
        if aviso_tempo:
            st.caption(aviso_tempo)
        clicado = _render_linhas_resumo(
            visiveis, tempo_por_ne_curta, liquidacao_competencia_por_mes, nes_com_tempo, source_key,
        )
        _render_rodape_resumo(valor_empenhado_total, saldo_total, necessidade_total, key=f"resumo_cc_{source_key}")

    if clicado is not None:
        abrir_linha_do_tempo(*clicado)

    if not mostrar_todos and total_linhas > QTD_INICIAL_RESUMO:
        st.caption(f"Mostrando {QTD_INICIAL_RESUMO} de {total_linhas} linhas no resumo")
        if st.button("Ver mais", key=f"cc_resumo_ver_mais_{source_key}"):
            st.session_state[mostrar_todos_key] = True
            st.rerun()
    elif total_linhas:
        st.caption(f"Mostrando todas as {total_linhas} linhas no resumo")
        if total_linhas > QTD_INICIAL_RESUMO and st.button("Ver menos", key=f"cc_resumo_ver_menos_{source_key}"):
            st.session_state[mostrar_todos_key] = False
            st.rerun()


def _render_relatorio_necessidade(
    filtrado: pd.DataFrame,
    meses_liquidados_por_ne: pd.DataFrame | None,
    liquidacao_competencia_por_mes: pd.DataFrame | None,
    source_key: str,
    ano_exercicio: int,
    busca: str,
    manifesto: ManifestoExecucaoMensal,
    via_competencia: bool,
) -> None:
    """Botões PDF/Excel do relatório de Necessidade de Empenho até o fim do exercício (pedido
    explícito, 01/10/2026 — ver `src/relatorio_necessidade_empenho.py`): a versão exportável do
    card "Resumo Consolidado" acima, calculada pela MESMA função (`necessidade_por_ne`), sobre o
    mesmo recorte (`filtrado`, que respeita a busca). Os arquivos só são gerados no clique
    (`data=lambda`), mesmo padrão de `app_pages/consulta_empenhos.py`.

    Grade Jan–Dez por NE: Realizado (Liquidação por Competência) e, do primeiro mês sem
    liquidação até dezembro, Projetado (despesa mensal − saldo atual do empenho) — pedidos
    explícitos posteriores; o mês da extração da Execução Mensal (`mes_referencia_do_exercicio`)
    só entra para NE sem nenhuma competência."""

    por_ne, sem_ne = necessidade_por_ne(filtrado, meses_liquidados_por_ne, ano_exercicio)
    data_extracao = datetime.fromisoformat(manifesto.data_extracao)
    mes_referencia = mes_referencia_do_exercicio(data_extracao.date(), ano_exercicio)
    relatorio = montar_relatorio_necessidade(
        por_ne, sem_ne, liquidacao_competencia_por_mes if via_competencia else None, ano_exercicio, mes_referencia
    )

    if via_competencia and CAMINHO_LIQUIDACAO_COMPETENCIA.exists():
        modificado = datetime.fromtimestamp(CAMINHO_LIQUIDACAO_COMPETENCIA.stat().st_mtime)
        origem_competencia = f"{CAMINHO_LIQUIDACAO_COMPETENCIA.name} · modificado em {modificado:%d/%m/%Y %H:%M}"
    else:
        origem_competencia = None

    contexto = ContextoRelatorioNecessidade(
        exercicio=ano_exercicio,
        data_extracao=data_extracao.strftime("%d/%m/%Y"),
        hash_manifesto=manifesto.sha256[:8],
        data_emissao=datetime.now().strftime("%d/%m/%Y %H:%M"),
        origem_competencia=origem_competencia,
        busca=busca.strip(),
    )

    st.caption(
        "Relatório de Necessidade de Empenho até Dezembro, em grade Jan–Dez por NE: meses com "
        "liquidação por competência (Realizado) e, a partir do primeiro mês sem liquidação, a "
        "necessidade projetada mês a mês (despesa mensal − saldo atual do empenho no primeiro mês; "
        "despesa mensal cheia nos seguintes). Saldo atual do empenho em coluna própria. A necessidade "
        "projetada pode diferir da do Resumo Consolidado acima (calendário × meses restantes pelo "
        "empenhado); as duas estão no Resumo por NE do arquivo. A projeção para no fim da vigência do "
        "cadastro (mês final proporcional) e não ocorre em contratos SUSPENSOS. Respeita a busca."
    )
    nome_arquivo = f"necessidade_empenho_contratos_continuos_{ano_exercicio}_{datetime.now():%Y-%m-%d}"
    col_pdf, col_xlsx = st.columns(2)
    with col_pdf:
        st.download_button(
            "Baixar PDF",
            data=lambda: gerar_pdf_necessidade(relatorio, contexto),
            file_name=f"{nome_arquivo}.pdf",
            mime="application/pdf",
            type="primary",
            width="stretch",
            on_click="ignore",
            key=f"cc_necessidade_pdf_{source_key}",
        )
    with col_xlsx:
        st.download_button(
            "Baixar Excel",
            data=lambda: gerar_xlsx_necessidade(relatorio, contexto),
            file_name=f"{nome_arquivo}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            on_click="ignore",
            key=f"cc_necessidade_xlsx_{source_key}",
        )


def _render_relatorio_projecao_execucao(
    filtrado: pd.DataFrame,
    liquidacao_competencia_por_mes: pd.DataFrame | None,
    source_key: str,
    ano_exercicio: int,
    manifesto: ManifestoExecucaoMensal,
    via_competencia: bool,
) -> None:
    """Botões PDF/Excel do relatório SEPARADO "Projeção pela Execução" (pedido de 06/10/2026 —
    `src/relatorio_projecao_execucao.py`): a despesa projetada pelo fator de execução de cada NE, ao
    lado da projeção pelo valor contratado e da Necessidade até dezembro contratual. Só LÊ o que o
    resto da página já calcula (`necessidade_por_ne`); nada do que já existe muda. O contrato
    antecessor (herança do fator para NE sem histórico) é escolhido aqui, a cada emissão, e não é
    gravado no cadastro."""

    st.markdown('<div class="cad-secao-titulo">Projeção pela execução</div>', unsafe_allow_html=True)
    if not via_competencia or liquidacao_competencia_por_mes is None:
        st.caption(
            "Indisponível: o relatório mede a execução pela Liquidação por Competência "
            f"('{CAMINHO_LIQUIDACAO_COMPETENCIA}'), que não foi encontrada."
        )
        return

    por_ne, _ = necessidade_por_ne(filtrado, None, ano_exercicio)
    data_extracao = datetime.fromisoformat(manifesto.data_extracao)
    mes_referencia = mes_referencia_do_exercicio(data_extracao.date(), ano_exercicio)
    fatores = fatores_projecao_execucao(por_ne, liquidacao_competencia_por_mes, ano_exercicio, mes_referencia)
    rotulos = {
        linha["ne_curta"]: f"{linha['ne_curta']} — {_ou_vazio(linha['fornecedor']) or '(sem fornecedor)'}"
        + (f" — {linha['contrato_numero']}" if _ou_vazio(linha["contrato_numero"]) else "")
        for _, linha in por_ne.iterrows()
    }
    sem_historico = [ne for ne, fator in fatores.items() if fator.origem == ORIGEM_SEM_HISTORICO]
    candidatas = [ne for ne, fator in fatores.items() if fator.origem == ORIGEM_EXECUCAO]

    antecessores: dict[str, str] = {}
    if sem_historico and candidatas:
        with st.expander(f"Contrato antecessor (opcional) — {len(sem_historico)} NE(s) sem histórico de execução"):
            st.caption(
                "NE com menos de 3 meses fechados é projetada pelo valor mensal cheio. Se ela substitui um "
                "contrato anterior do mesmo serviço, escolha a NE dele para herdar o fator de execução. A "
                "escolha vale só para esta emissão (não é gravada no cadastro)."
            )
            for ne in sem_historico:
                escolha = st.selectbox(
                    rotulos[ne], ["(nenhum — valor cheio)", *candidatas],
                    format_func=lambda opcao: rotulos.get(opcao, opcao),
                    key=f"cc_projexec_antecessor_{source_key}_{ne}",
                )
                if escolha in fatores:
                    antecessores[ne] = escolha

    relatorio, _ = projecao_contratos(
        filtrado, liquidacao_competencia_por_mes, ano_exercicio, mes_referencia, antecessores
    )
    modificado = datetime.fromtimestamp(CAMINHO_LIQUIDACAO_COMPETENCIA.stat().st_mtime)
    contexto = ContextoProjecaoExecucao(
        exercicio=ano_exercicio,
        data_extracao=data_extracao.strftime("%d/%m/%Y"),
        hash_manifesto=manifesto.sha256[:8],
        data_emissao=datetime.now().strftime("%d/%m/%Y %H:%M"),
        origem_competencia=f"{CAMINHO_LIQUIDACAO_COMPETENCIA.name} · modificado em {modificado:%d/%m/%Y %H:%M}",
    )
    st.caption(
        "Relatório separado: projeta a despesa até dezembro pelo que cada contrato de fato liquida (fator de "
        "execução sobre o custo contratado, pela execução dos últimos 6 meses fechados), incluindo o restante "
        "dos meses ainda em aberto, e compara com a projeção pelo valor contratado e com a Necessidade até "
        f"dezembro contratual. Pela execução: necessidade de {formatar_brl(relatorio.total_necessidade_execucao)} "
        f"(contratual: {formatar_brl(relatorio.total_necessidade_contratual)}). Respeita a busca."
    )
    nome_arquivo = f"projecao_execucao_contratos_continuos_{ano_exercicio}_{datetime.now():%Y-%m-%d}"
    col_pdf, col_xlsx = st.columns(2)
    with col_pdf:
        st.download_button(
            "Baixar PDF", data=lambda: gerar_pdf_projecao_execucao(relatorio, contexto),
            file_name=f"{nome_arquivo}.pdf", mime="application/pdf", type="primary", width="stretch",
            on_click="ignore", key=f"cc_projexec_pdf_{source_key}",
        )
    with col_xlsx:
        st.download_button(
            "Baixar Excel", data=lambda: gerar_xlsx_projecao_execucao(relatorio, contexto),
            file_name=f"{nome_arquivo}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch", on_click="ignore", key=f"cc_projexec_xlsx_{source_key}",
        )


def _render_empenhado_liquidado(
    filtrado: pd.DataFrame, indice_liquidado: pd.Series, source_key: str,
    meses_liquidados_por_ne: pd.DataFrame, via_competencia: bool = False,
) -> None:
    """Quadro comparando, por NE, o valor empenhado total contra o liquidado (pedido
    explícito) — mesmo layout do Resumo Consolidado acima (`cartao_secao`), abrangendo TODOS
    os contratos filtrados, inclusive os sem NE (aparecem com "sem NE" no lugar de
    liquidado/saldo, já que não há NE para buscar na Execução Mensal).

    `indice_liquidado`/`via_competencia` (pedido explícito posterior — ver LIQUIDADO POR
    COMPETÊNCIA na docstring do módulo): Liquidação por Competência quando disponível,
    Execução Mensal (por lançamento) como fallback — mesma fonte de `com_saldo_execucao`.

    O saldo é o mesmo `saldo_execucao` (empenhada − liquidada por LANÇAMENTO, sempre via
    Execução Mensal — nunca muda com `via_competencia`) já usado no resto da página, não uma
    conta nova —, só reapresentado aqui lado a lado com o valor liquidado e rotulado "Sobra"
    (saldo ≥ 0, ainda há espaço no empenho) ou "Insuficiência" (saldo < 0, liquidado passou do
    empenhado — precisa de reforço de empenho). Com `via_competencia=True` as três colunas
    deixam de bater aritmeticamente (Saldo não é Empenhado − Liquidado exibido) — decisão
    explícita do usuário: o Liquidado mais correto importa mais que a soma fechar; uma nota
    abaixo do cabeçalho avisa disso.

    Coluna "Meses Liquidados" (pedido explícito posterior — antes "Meses Pagos", vinda da
    planilha separada de Pagamentos): vem de `meses_liquidados_por_ne`
    (`_meses_liquidados_por_ne_curta`, Liquidação por Competência) — mesma troca da coluna
    equivalente no Resumo Consolidado, pela mesma razão."""

    com_ne = filtrado.dropna(subset=["ne_curta"])
    sem_ne = filtrado[filtrado["ne_curta"].isna()]

    por_ne = com_ne.groupby("ne_curta", sort=False).agg(
        fornecedor=("fornecedor", "first"),
        contrato_numero=("contrato_numero", "first"),
        valor_empenhado_execucao=("valor_empenhado_execucao", "first"),
        valor_empenhado_planilha_total_ne=("valor_empenhado_planilha_total_ne", "first"),
        saldo_execucao=("saldo_execucao", "first"),
    ).reset_index()
    por_ne = por_ne.merge(meses_liquidados_por_ne, on="ne_curta", how="left")
    por_ne["empenhado_exibido"] = por_ne["valor_empenhado_execucao"].fillna(por_ne["valor_empenhado_planilha_total_ne"])
    por_ne["liquidado"] = por_ne["ne_curta"].map(indice_liquidado)

    linhas = [
        (
            row["fornecedor"], row["contrato_numero"], row["empenhado_exibido"], row["liquidado"],
            row["saldo_execucao"], row["meses_liquidados"], row["ultimo_mes_liquidado"],
        )
        for _, row in por_ne.sort_values("saldo_execucao", na_position="last").iterrows()
    ] + [
        (row["fornecedor"], row["contrato_numero"], row["valor_empenhado"], pd.NA, pd.NA, pd.NA, pd.NA)
        for _, row in sem_ne.iterrows()
    ]

    empenhado_total = por_ne["empenhado_exibido"].sum() + sem_ne["valor_empenhado"].sum()
    liquidado_total = por_ne["liquidado"].sum()
    saldo_total = _somar_unico_por_ne(filtrado, "saldo_execucao")
    total_linhas = len(linhas)

    mostrar_todos_key = f"cc_empliq_mostrar_todos_{source_key}"
    mostrar_todos = st.session_state.get(mostrar_todos_key, False)
    visiveis = linhas if mostrar_todos else linhas[:QTD_INICIAL_RESUMO]
    rotulo_total = "Sobra" if saldo_total >= 0 else "Insuficiência"
    tom_total = "ok" if saldo_total >= 0 else "bad"
    rotulo_liquidado = "Liquidado (Competência)" if via_competencia else "Liquidado (Execução Mensal)"
    descricao = (
        "Liquidado por competência (mês de referência) — Saldo continua Empenhado − Liquidado por lançamento "
        "(Execução Mensal, mesmo saldo formal do resto da página); as duas colunas não somam entre si."
        if via_competencia
        else None
    )

    linhas_tabela = []
    for fornecedor, contrato_numero, empenhado, liquidado, saldo, meses_liquidados, ultimo_mes_liquidado in visiveis:
        numero = _ou_vazio(contrato_numero)
        linhas_tabela.append([
            celula_principal(_ou_vazio(fornecedor) or "(sem fornecedor)", f"Contrato {numero}" if numero else None),
            celula_valor(empenhado, vazio="sem NE"),
            celula_valor(liquidado if pd.notna(saldo) else None, vazio="sem NE"),  # sem NE: sem o que buscar na Execução
            celula_saldo(saldo),
            celula_suave(_texto_meses_liquidados(meses_liquidados, ultimo_mes_liquidado)),
        ])
    tabela = tabela_html(
        [("Fornecedor / Contrato", False), ("Empenhado", True), (rotulo_liquidado, True), ("Saldo", True), ("Meses liquidados", False)],
        linhas_tabela, [3.0, 1.3, 1.4, 1.5, 1.2],
        rodape=[
            '<div class="cad-total-rotulo">Total</div>', celula_valor(empenhado_total), celula_valor(liquidado_total),
            celula_valor(saldo_total, tom_total), "",
        ],
        rolagem=True,  # pedido explícito: barra de rolagem em todo quadro com "Ver mais"
    )
    st.markdown(
        cartao_secao(
            "Sobra ou Insuficiência no Empenho, por NE",
            descricao,
            {
                "rotulo": f"Saldo total ({rotulo_total})",
                "valor": formatar_brl(saldo_total),
                "detalhe": f"{total_linhas} {'NE/contrato' if total_linhas == 1 else 'NEs/contratos'}",
                "tom": tom_total,
            },
            tabela,
            kicker="EMPENHADO × LIQUIDADO",
        ),
        unsafe_allow_html=True,
    )

    if not mostrar_todos and total_linhas > QTD_INICIAL_RESUMO:
        st.caption(f"Mostrando {QTD_INICIAL_RESUMO} de {total_linhas} linhas")
        if st.button("Ver mais", key=f"cc_empliq_ver_mais_{source_key}"):
            st.session_state[mostrar_todos_key] = True
            st.rerun()
    elif total_linhas:
        st.caption(f"Mostrando todas as {total_linhas} linhas")
        if total_linhas > QTD_INICIAL_RESUMO and st.button("Ver menos", key=f"cc_empliq_ver_menos_{source_key}"):
            st.session_state[mostrar_todos_key] = False
            st.rerun()


def _render_card_dotacao(codigo: object, nome: object, grupo: pd.DataFrame) -> None:
    """Um cartão por Ação de Governo, com uma linha por Plano Orçamentário/PTRES — montagem do HTML em
    `src/ui_cadastro.py::cartao_cobertura_ptres`, compartilhada com `bolsas_auxilios.py` (layout de 05/10/2026)."""

    st.markdown(cartao_cobertura_ptres(codigo, nome, grupo), unsafe_allow_html=True)


def _render_quadro_dotacao(filtrado: pd.DataFrame, dotacao_dimensoes: pd.DataFrame, ano_exercicio: int) -> None:
    """Um cartão por Ação de Governo, com uma subdivisão por Plano Orçamentário/PTRES dentro
    — cruza, para cada PTRES cadastrado nos contratos (referencial comum entre a Dotação
    Anual e o cadastro de cada contrato), a Dotação Atualizada disponível contra a despesa
    anual estimada (`despesa_anual`) dos contratos daquele PTRES. Mesmo padrão de
    `app_pages/bolsas_auxilios.py::_render_quadro_dotacao`."""

    despesa_por_ptres = filtrado.groupby("ptres")["despesa_anual"].sum(min_count=1).fillna(0.0)
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
        "Nenhum exercício cadastrado ainda no cadastro nativo de Contratos Contínuos "
        f"('{Path('data/contratos_continuos')}'). Rode a migração única a partir da planilha "
        "(`contratos_continuos_cadastro.migrar_de_planilha`) para criar o primeiro exercício."
    )
    st.stop()

ano_key = "contratos_continuos_ano_selecionado"
if st.session_state.get(ano_key) not in anos:
    st.session_state[ano_key] = max(anos)
ano_selecionado = st.session_state[ano_key]
source_key = str(ano_selecionado)

# Seletor de exercício — no topo da página, acima do título/Relatório/Novo contrato (pedido
# explícito). Discreto: um botão por ano cadastrado (o selecionado em destaque) + um único
# menu "⋮" (pop-up, pedido explícito) reunindo "Duplicar" (sempre do exercício mais recente
# para o próximo) e "Excluir exercício" com uma caixa de seleção do ano a apagar (pedido
# explícito), em vez de só o ano em tela. Mesmo padrão de app_pages/bolsas_auxilios.py. O
# exercício mais antigo (migrado da planilha original) nunca aparece como opção de exclusão.
cols_ano = st.columns([1] * (len(anos) + 1) + [10])
for coluna, ano_opcao in zip(cols_ano, anos):
    if coluna.button(
        str(ano_opcao), key=f"cc_ano_{ano_opcao}",
        type="primary" if ano_opcao == ano_selecionado else "secondary", use_container_width=True,
    ):
        st.session_state[ano_key] = ano_opcao
        st.rerun()

origem_duplicar = max(anos)
destino_duplicar = origem_duplicar + 1
anos_excluiveis = [ano for ano in anos if ano != min(anos)]
with cols_ano[len(anos)]:
    with st.popover("⋮", help="Duplicar ou excluir um exercício", use_container_width=True):
        if st.button(
            f"Duplicar {origem_duplicar} → {destino_duplicar}",
            key=f"cc_duplicar_{destino_duplicar}", use_container_width=True,
            help="Copia identidade/classificação dos contratos; execução fica em branco.",
        ):
            duplicar_exercicio(origem_duplicar, destino_duplicar)
            st.session_state[ano_key] = destino_duplicar
            st.success(f"Exercício {destino_duplicar} criado a partir de {origem_duplicar}.")
            st.rerun()

        if anos_excluiveis:
            st.markdown("---")
            ano_excluir = st.selectbox(
                "Excluir exercício", anos_excluiveis, key=f"cc_excluir_exercicio_escolha_{source_key}",
            )
            confirmar_exercicio_key = f"cc_confirmar_excluir_exercicio_{ano_excluir}"
            if st.session_state.get(confirmar_exercicio_key):
                if st.button(
                    f"Confirmar exclusão de {ano_excluir}?", key=f"cc_excluir_exercicio_confirmar_{ano_excluir}",
                    use_container_width=True, type="primary",
                ):
                    excluir_exercicio(ano_excluir)
                    st.session_state.pop(confirmar_exercicio_key, None)
                    if ano_excluir == ano_selecionado:
                        st.session_state[ano_key] = max(a for a in anos if a != ano_excluir)
                    st.success(f"Exercício {ano_excluir} excluído.")
                    st.rerun()
            else:
                if st.button(f"Excluir {ano_excluir}", key=f"cc_excluir_exercicio_{ano_excluir}", use_container_width=True):
                    st.session_state[confirmar_exercicio_key] = True
                    st.rerun()

col_titulo, col_relatorio, col_novo = st.columns([4, 1.4, 1])
with col_titulo:
    render_page_header(
        "Contratos Contínuos",
        "Necessidade de reforço de empenho por contrato, cruzado com a Execução Mensal.",
        "Contratos",
    )
with col_novo:
    st.write("")
    _render_novo_contrato(ano_selecionado, source_key)

manifesto_execucao_mensal = ManifestoExecucaoMensal.atual()
if manifesto_execucao_mensal is None:
    st.info(
        "Nenhuma base de Execução Mensal foi importada ainda — é dela que vem o saldo "
        "autoritativo por NE. Importe a Execução Mensal antes de usar esta página."
    )
    st.stop()

caminho_ponteiro_execucao_mensal = DIRETORIO_MANIFESTOS_PADRAO / NOME_PONTEIRO_EXECUCAO_MENSAL

try:
    registros = carregar_contratos(ano_selecionado)
    dataframe = como_dataframe(registros, ano_selecionado)
    por_ne_execucao = _cached_por_ne_execucao(
        str(caminho_ponteiro_execucao_mensal), caminho_ponteiro_execucao_mensal.stat().st_mtime
    )
except Exception as error:
    st.error(f"Não foi possível ler os dados: {error}")
    st.stop()

# Linha do tempo mensal (pop-up "Linha do tempo mensal" do Resumo Consolidado) usa a MESMA
# base já carregada acima para o saldo — reaproveita o manifesto já confirmado presente.
tempo_por_ne_curta: pd.DataFrame | None = None
try:
    tempo_por_ne_curta = _cached_linha_do_tempo(
        str(caminho_ponteiro_execucao_mensal), caminho_ponteiro_execucao_mensal.stat().st_mtime
    )
except Exception:
    tempo_por_ne_curta = None

# Liquidação por Competência, para "Necessidade de Empenho" (ver com_saldo_execucao) —
# opcional: sem o arquivo, a conta volta a usar o liquidado por lançamento da Execução Mensal
# (comportamento anterior a este pedido).
indice_liquidado_competencia: pd.Series | None = None
liquidacao_competencia_por_mes: pd.DataFrame | None = None
if CAMINHO_LIQUIDACAO_COMPETENCIA.exists():
    try:
        indice_liquidado_competencia = _cached_indice_liquidado_competencia(
            str(CAMINHO_LIQUIDACAO_COMPETENCIA), CAMINHO_LIQUIDACAO_COMPETENCIA.stat().st_mtime
        )
        liquidacao_competencia_por_mes = _cached_liquidacao_competencia_por_mes(
            str(CAMINHO_LIQUIDACAO_COMPETENCIA), CAMINHO_LIQUIDACAO_COMPETENCIA.stat().st_mtime
        )
    except Exception:
        indice_liquidado_competencia = None
        liquidacao_competencia_por_mes = None

# "Meses Liquidados" do Resumo Consolidado/Empenhado × Liquidado (pedido explícito posterior
# — antes "Meses Pagos", vinda da planilha de Pagamentos): quantos meses cada NE já tem de
# liquidação apurada por competência — ver `_meses_liquidados_por_ne_curta`. Vazio (toda NE
# "sem dado") quando a base de competência está indisponível, mesma lógica de ausência
# silenciosa de sempre.
meses_liquidados_por_ne = _meses_liquidados_por_ne_curta(liquidacao_competencia_por_mes)

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

# Pagamentos de Contratos, para "Meses Pagos"/"Último Mês Pago" nos cartões — mesmo padrão
# de complemento opcional da Dotação Anual acima: sem ela, os dois campos ficam nulos e o
# resto da tela continua funcionando normal.
if CAMINHO_PAGAMENTOS.exists():
    try:
        meses_pagos_por_contrato_df = _cached_meses_pagos_por_contrato(
            str(CAMINHO_PAGAMENTOS), CAMINHO_PAGAMENTOS.stat().st_mtime
        )
    except Exception:
        meses_pagos_por_contrato_df = pd.DataFrame(
            columns=["contrato_normalizado", "meses_pagos", "ultimo_mes_pago"]
        )
else:
    meses_pagos_por_contrato_df = pd.DataFrame(
        columns=["contrato_normalizado", "meses_pagos", "ultimo_mes_pago"]
    )

if tempo_por_ne_curta is not None:
    sugestao_inicio_por_ne = primeiro_mes_com_empenho_por_ne(tempo_por_ne_curta)
else:
    sugestao_inicio_por_ne = pd.Series(dtype="Int64")
# Colunas derivadas (saldo via Execução, autoritativos, início efetivo, efeitos da suspensão): montagem
# compartilhada com o Resultado Orçamentário em `src/resultado_orcamentario_fontes.py` (08/10/2026);
# os comentários de decisão foram junto.
dataframe = tabela_contratos(
    dataframe, por_ne_execucao, indice_liquidado_competencia, sugestao_inicio_por_ne,
    meses_pagos=meses_pagos_por_contrato_df,
)

# Integração com o Contratos.gov.br (10/2026): ligação por NE (depois número + CNPJ/CPF), conciliação de
# vigência e aditivos sem registro. Complemento opcional, em memória — ver `com_contratosgov`.
termos_gov = None
_inicio_por_gov: dict = {}
_gov = _carregar_gov(_referencia_gov())
if _gov is not None:
    _contratos_gov, termos_gov, _empenhos_gov = _gov
    _inicio_por_gov = dict(zip(_contratos_gov["contrato_id"].astype(str), _contratos_gov["vigencia_inicio"]))
    dataframe = com_contratosgov(dataframe, _contratos_gov, termos_gov, _empenhos_gov)
    _candidatos_gov, _em_duvida_gov = candidatos_novos(dataframe, _contratos_gov, _empenhos_gov)
    _render_novos_contratosgov(_candidatos_gov, _em_duvida_gov, ano_selecionado, source_key)

with col_relatorio:
    st.write("")
    render_botao_relatorio(dataframe, RELATORIO_CONTRATOS_CONTINUOS, f"continuos_{ano_selecionado}", ano_selecionado)

busca = st.text_input(
    "Buscar",
    key=f"contratos_continuos_busca_{source_key}",
    placeholder="Contrato, fornecedor, tipo de despesa, ação, PI, NE…",
)
filtrado = _aplicar_busca(dataframe, busca)

if filtrado.empty:
    if dataframe.empty:
        st.info(
            f"Nenhum contrato cadastrado no exercício {ano_selecionado} ainda. Use "
            "'+ Novo contrato' ou, se este for o exercício mais recente, 'Duplicar cadastro' "
            "acima para partir do exercício anterior."
        )
    else:
        st.warning("Nenhum contrato corresponde à busca informada.")
    st.stop()

# Cartão-resumo do topo (pedido de 05/10/2026, layout de referência): faixa de destaque com a
# Necessidade de Empenho até Dezembro — a MESMA conta do "Resumo Consolidado" (`necessidade_por_ne`) —
# e a grade de indicadores do exercício. Substitui a antiga linha de 4 métricas.
_por_ne_topo, _sem_ne_topo = necessidade_por_ne(filtrado, meses_liquidados_por_ne, ano_selecionado)
# "A empenhar" e situação do Registro de contratos (06/10/2026): a mesma Necessidade até dezembro do
# Resumo Consolidado, por linha (NE compartilhada: o valor da NE em cada linha dela).
filtrado = filtrado.assign(necessidade_ate_dezembro=necessidade_por_linha(filtrado, _por_ne_topo, _sem_ne_topo))
_necessidade_topo = float(_por_ne_topo["necessidade"].sum() + _sem_ne_topo["necessidade"].sum())
_estimado_previstos = valor_estimado_em_previstos(filtrado, meses_liquidados_por_ne, ano_selecionado)
_empenhado_topo = float(_por_ne_topo["valor_empenhado_exibido"].sum() + _sem_ne_topo["valor_empenhado_exibido"].sum())
st.markdown(
    cartao_resumo(
        f"Contratos Contínuos {ano_selecionado}",
        "Despesa e empenho dos contratos do exercício, cruzados com a Execução Mensal e a Liquidação por Competência.",
        {
            "rotulo": "Necessidade de empenho até dezembro",
            "valor": formatar_brl(_necessidade_topo),
            "detalhe": (
                f"{len(_por_ne_topo)} NE(s) e {len(_sem_ne_topo)} contrato(s) sem NE consideradas, "
                "conforme o Resumo Consolidado"
                + (
                    f" · inclui {formatar_brl(_estimado_previstos)} estimados em aditivos previstos"
                    if filtrado["tem_aditivo_previsto"].any() else ""
                )
            ),
            "tom": "warn" if _necessidade_topo > 0 else "ok",
        },
        [
            ("Despesa anual", formatar_brl(filtrado["despesa_anual"].sum())),
            ("Despesa mensal", formatar_brl(filtrado["despesa_mensal"].sum())),
            ("Contratos", str(filtrado["contrato_numero"].nunique())),
            ("Empenhado (por NE)", formatar_brl(_empenhado_topo)),
            ("Saldo (Execução Mensal)", formatar_brl(_somar_unico_por_ne(filtrado, "saldo_execucao"))),
            # 06/10/2026: era "A empenhar (execução)", mesmo nome da coluna do registro (Necessidade até dezembro)
            # medindo outra coisa — empenhado − liquidado em meses × despesa mensal, isto é, o saldo
            ("Saldo a liquidar (execução)", formatar_brl(filtrado["valor_a_empenhar"].sum())),
        ],
    ),
    unsafe_allow_html=True,
)

_render_resumo_consolidado(
    filtrado, tempo_por_ne_curta, source_key, liquidacao_competencia_por_mes,
    meses_liquidados_por_ne, ano_selecionado,
)
_render_relatorio_necessidade(
    filtrado, meses_liquidados_por_ne, liquidacao_competencia_por_mes, source_key, ano_selecionado, busca,
    manifesto_execucao_mensal, via_competencia=indice_liquidado_competencia is not None,
)
_render_relatorio_projecao_execucao(
    filtrado, liquidacao_competencia_por_mes, source_key, ano_selecionado, manifesto_execucao_mensal,
    via_competencia=indice_liquidado_competencia is not None,
)
# Estimativa de reajuste por competência (11/10/2026): cenário separado, só lê os contratos do exercício.
render_estimativa_reajuste(
    filtrado, registros, [r for _ano in anos_disponiveis() for r in carregar_contratos(_ano)], ano_selecionado,
    liquidacao_competencia_por_mes, _inicio_por_gov, source_key, _referencia_gov(),
)
if indice_liquidado_competencia is not None:
    _render_empenhado_liquidado(
        filtrado, indice_liquidado_competencia, source_key, meses_liquidados_por_ne, via_competencia=True
    )
else:
    _render_empenhado_liquidado(
        filtrado, indice_liquidado_por_ne_curta(por_ne_execucao), source_key, meses_liquidados_por_ne
    )

if dotacao_dimensoes is not None:
    st.markdown('<div class="cad-secao-titulo">Cobertura orçamentária por PTRES</div>', unsafe_allow_html=True)
    if filtrado["tem_aditivo_previsto"].any():
        st.caption("A despesa estimada por PTRES inclui aditivos previstos (valores estimados, ainda não assinados).")
    _render_quadro_dotacao(filtrado, dotacao_dimensoes, ano_exercicio_dotacao)
else:
    st.info(
        "Nenhuma base de Dotação Anual foi importada ainda — o quadro de cobertura "
        "orçamentária por PTRES depende dela. Importe a Dotação Anual para vê-lo aqui."
    )

# ------------------------------------------------------------------ Registro de contratos
# Repaginação de 05/10/2026 ("muita cara de planilha"): a antiga carteira de cartões-expansores vira
# um REGISTRO em tabela, como na referência — abas de situação com contagem, filtro de categoria,
# ordenação, linhas com título/subtítulo, valores à direita, situação em chip e ações por ícone. A
# edição acontece numa janela (`_dialogo_editar_contrato`), a remoção numa confirmação. Mesmos
# dados, mesmas regras e mesma gravação de antes.
st.markdown('<div class="cad-secao-titulo">Registro de contratos</div>', unsafe_allow_html=True)

_status_norm = filtrado["status_contrato"].where(filtrado["status_contrato"].isin(STATUS_OPCOES), "ATIVO")
_ativo = _status_norm.eq("ATIVO").fillna(False).astype(bool)
_situacao_registro = pd.Series(
    [
        _situacao(status, vigencia, necessidade)[0]
        for status, vigencia, necessidade in zip(
            filtrado["status_contrato"], filtrado["vigencia_fim_efetiva"], filtrado["necessidade_ate_dezembro"]
        )
    ],
    index=filtrado.index, dtype=object,
)
_mascaras_abas = {
    "Todos": pd.Series(True, index=filtrado.index),
    "Ativo": _ativo,
    "Necessita reforço": _situacao_registro.eq(SITUACAO_NECESSITA_REFORCO),
    "Vigência encerrada": _situacao_registro.eq(SITUACAO_VIGENCIA_ENCERRADA),
    "Vencido": _status_norm.eq("VENCIDO").fillna(False).astype(bool),
    "Suspenso": _status_norm.eq("SUSPENSO").fillna(False).astype(bool),
}
_contagens_abas = contagens_por_aba(_mascaras_abas)

_ORDENACOES_REGISTRO = {
    "Fornecedor (A–Z)": ("fornecedor", True),
    "Maior despesa mensal": ("despesa_mensal", False),
    "Maior valor a empenhar": ("necessidade_ate_dezembro", False),
    "Vigência mais próxima": ("vigencia_fim_efetiva", True),
}
_PROPORCOES_REGISTRO = [3.0, 1.45, 1.3, 1.3, 1.3, 1.15, 1.85, 0.95]
_CABECALHOS_REGISTRO = [
    ("Contrato / Fornecedor", False), ("Categoria", False), ("Despesa mensal", True), ("Saldo", True),
    ("A empenhar", True), ("Vigência", False), ("Situação", False), ("Ações", False),
]
QTD_INICIAL_REGISTRO = 15

with st.container(border=True, key="cad_registro"):
    c_abas, c_categoria, c_ordem = st.columns([3.6, 1.3, 1.3], vertical_alignment="center")
    aba_escolhida = c_abas.segmented_control(
        "Situação", list(_mascaras_abas), default="Todos", key=f"cad_abas_cc_{source_key}",
        format_func=lambda rotulo: f"{rotulo} ({_contagens_abas[rotulo]})", label_visibility="collapsed",
    ) or "Todos"
    _categorias = sorted(filtrado["tipo_despesa"].dropna().astype(str).unique(), key=str.casefold)
    categoria_escolhida = c_categoria.selectbox(
        "Categoria", ["Todas as categorias", *_categorias], key=f"cc_categoria_{source_key}", label_visibility="collapsed",
    )
    ordem_escolhida = c_ordem.selectbox(
        "Ordenar por", list(_ORDENACOES_REGISTRO), key=f"cc_ordem_{source_key}", label_visibility="collapsed",
    )

    registro = filtrado[_mascaras_abas[aba_escolhida]]
    if categoria_escolhida != "Todas as categorias":
        registro = registro[registro["tipo_despesa"].astype("string") == categoria_escolhida]
    _coluna_ordem, _crescente = _ORDENACOES_REGISTRO[ordem_escolhida]
    registro = ordenar_por(registro, _coluna_ordem, _crescente)

    st.markdown(
        f'<div class="cad-contagem">{len(registro)} registro(s) · '
        f'{formatar_brl(registro["despesa_mensal"].sum())} de despesa mensal</div>',
        unsafe_allow_html=True,
    )

    mostrar_todos_key = f"cc_registro_mostrar_todos_{source_key}"
    mostrar_todos = st.session_state.get(mostrar_todos_key, False)
    qtd_registro = len(registro) if mostrar_todos else QTD_INICIAL_REGISTRO

    if registro.empty:
        st.markdown('<div class="cad-vazio">Nenhum contrato nesta situação/categoria.</div>', unsafe_allow_html=True)
    else:
        colunas_cabecalho = st.columns(_PROPORCOES_REGISTRO)
        for coluna, (texto, a_direita) in zip(colunas_cabecalho, _CABECALHOS_REGISTRO):
            coluna.markdown(
                f'<div class="cad-cabecalho{" direita" if a_direita else ""}">{texto}</div>', unsafe_allow_html=True
            )

    # Rolagem (pedido explícito): as linhas ficam numa caixa de altura máxima fixa
    # (`.st-key-cc_registro_scroll` em `src/ui_cadastro.py`), o cabeçalho fica fora dela.
    with st.container(key="cc_registro_scroll"):
        for _, linha in registro.iloc[:qtd_registro].iterrows():
            id_linha = str(linha["id"])
            with st.container(key=f"cad_linha_{id_linha}"):
                cel = st.columns(_PROPORCOES_REGISTRO, vertical_alignment="center")
                numero_linha = _ou_vazio(linha["contrato_numero"])
                ne_linha = _ou_vazio(linha["ne_curta"])
                qtd_aditivos = len(linha["aditivos"])
                subtitulo = " · ".join(
                    parte for parte in (
                        f"Contrato {numero_linha}" if numero_linha else "", f"NE {ne_linha}" if ne_linha else "",
                        f"{qtd_aditivos} aditivo(s)" if qtd_aditivos else "", _texto_conciliacao(linha),
                    ) if parte
                )
                texto_situacao, tom_situacao = _situacao(
                    linha["status_contrato"], linha["vigencia_fim_efetiva"], linha["necessidade_ate_dezembro"]
                )
                a_empenhar_linha = _ou_zero(linha["necessidade_ate_dezembro"])
                cel[0].markdown(celula_principal(linha["fornecedor"] if _ou_vazio(linha["fornecedor"]) else "(sem fornecedor)", subtitulo), unsafe_allow_html=True)
                cel[1].markdown(celula_categoria(linha["tipo_despesa"]), unsafe_allow_html=True)
                cel[2].markdown(celula_valor(linha["despesa_mensal"]), unsafe_allow_html=True)
                cel[3].markdown(celula_valor(linha["saldo_execucao"]), unsafe_allow_html=True)  # sem NE: "—", não zero
                cel[4].markdown(
                    celula_valor(linha["necessidade_ate_dezembro"], "warn" if a_empenhar_linha > 0 else None),
                    unsafe_allow_html=True,
                )
                vigencia_linha = _data_ou_none(linha["vigencia_fim_efetiva"])
                texto_vigencia = vigencia_linha.strftime("%d/%m/%Y") if vigencia_linha else None
                if texto_vigencia and _data_ou_none(linha["vigencia_fim_efetiva"]) != _data_ou_none(linha["vigencia_fim"]):
                    texto_vigencia += " · TA"  # a vigência vem de um aditivo, não do contrato original
                if texto_vigencia and linha["tem_aditivo_previsto"]:
                    texto_vigencia += " · previsto"
                cel[5].markdown(celula_suave(texto_vigencia), unsafe_allow_html=True)
                cel[6].markdown(chip(texto_situacao, tom_situacao), unsafe_allow_html=True)
                with cel[7]:
                    with st.container(key=f"cad_acoes_{id_linha}"):
                        b_editar, b_remover = st.columns(2)
                        if b_editar.button("", icon=":material/edit:", key=f"cc_editar_{source_key}_{id_linha}", help="Editar contrato", use_container_width=True):
                            # os itens de licitação editados vivem em `st.session_state`; ao abrir de novo, parte do registro
                            st.session_state.pop(f"cc_{source_key}_{id_linha}_itens", None)
                            st.session_state.pop(f"cc_{source_key}_{id_linha}_aditivos", None)
                            _dialogo_editar_contrato(
                                linha, ano_selecionado, source_key,
                                sugestao_inicio_por_ne.get(linha["ne_curta"]) if pd.notna(linha["ne_curta"]) else None,
                                termos_gov,
                            )
                        if b_remover.button("", icon=":material/delete:", key=f"cc_remover_{source_key}_{id_linha}", help="Remover contrato", use_container_width=True):
                            _dialogo_remover_contrato(
                                id_linha, f"{_ou_vazio(linha['fornecedor']) or '(sem fornecedor)'} — {numero_linha or 's/ nº'}", ano_selecionado
                            )

    # "Ver mais" de um clique só (pedido explícito, antes revelava +15 por clique): mostra tudo.
    if not mostrar_todos and len(registro) > QTD_INICIAL_REGISTRO:
        c_mais, c_texto = st.columns([1, 3], vertical_alignment="center")
        c_texto.caption(f"Mostrando {QTD_INICIAL_REGISTRO} de {len(registro)} contratos")
        if c_mais.button("Ver mais", key=f"cc_registro_mais_{source_key}"):
            st.session_state[mostrar_todos_key] = True
            st.rerun()
    elif mostrar_todos and len(registro) > QTD_INICIAL_REGISTRO:
        if st.button("Ver menos", key=f"cc_registro_menos_{source_key}"):
            st.session_state[mostrar_todos_key] = False
            st.rerun()

st.caption(
    "Cadastro nativo de Contratos Contínuos (não depende de planilha) — uma linha por contrato; os itens de "
    "licitação rateiam a despesa mensal. Saldo e Empenhado vêm da Execução Mensal, cruzados pela NE. "
    f"Exercício em tela: {ano_selecionado}. A edição abre numa janela e só é gravada ao clicar em 'Salvar'; "
    "'Novo contrato' e 'Remover' gravam/apagam ao confirmar."
)
