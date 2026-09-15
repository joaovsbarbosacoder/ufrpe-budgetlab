"""Contratos Contínuos — necessidade de empenho e saldo, cruzado com a Execução Anual.

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
`src/execucao_anual.py::saldo_por_ne`) — não `data_loader_contratos.py`/`design_tokens.py`
de handoffs anteriores.

Cada contrato é um cartão (`st.expander`, minimizado por padrão — mesmo padrão de
`app_pages/bolsas_auxilios.py`, aplicado aqui) com todos os campos editáveis inline — sem
rolagem horizontal, os campos quebram em linhas dentro do próprio cartão. Rótulo pequeno
(`.cc-label`, maiúsculo, discreto) acima de cada campo — nem rótulo nativo grande do
Streamlit, nem campo sem rótulo nenhum: editável não é sinônimo de caixa grande, mas também
não fica sem indicação do que é.

Antes da lista, um card único "Resumo Consolidado — por NE" lista, uma linha por NE (não por
item de licitação nem um total agregado — ver `_render_resumo_consolidado`), o valor
empenhado, o saldo (Execução Anual) e a necessidade de empenho até o fim do exercício. Itens
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
    Consolidado usa `despesa_mensal × meses restantes até dezembro` só para a "Necessidade
    até Dezembro" agregada — mesma ressalva de `bolsas_auxilios.py`: não substitui nem se
    confunde com "Empenhar" por cartão.
  * Para contratos cuja NE já foi encontrada na Execução Anual, `meses_empenhados`/
    `meses_liquidados` deixam de vir da planilha e passam a vir da própria Execução Anual
    (`com_saldo_execucao`, campos `meses_empenhados_execucao`/`meses_liquidados_execucao`) —
    pedido explícito do usuário para não depender de atualizar a planilha de Contratos
    Contínuos só para refletir um novo saldo/liquidado. Os dois campos do cartão viram
    exibição (rótulo "(Execução Anual)"), não mais editáveis, nesse caso — editar deixaria de
    ter efeito no "Empenhar" mostrado. Sem NE encontrada, os campos continuam editáveis como
    sempre, seedados pela planilha (fallback inalterado).
  * `saldo_execucao` e `valor_empenhado_execucao` (autoritativos, vindos da Execução Anual)
    são fixos — não editáveis (lidos da Execução Anual, não desta planilha) — e visíveis
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
    "Resumo Consolidado" — não é `st.dataframe` (cara de planilha) — com CSS próprio
    (`.cc-resumo-*`, mesmo padrão de `.bls-resumo-*` em `bolsas_auxilios.py`).
  * Os tokens de cor/tipografia são os reais do projeto (`src/design_tokens.py`).
  * KPIs no topo, por pedido explícito: Despesa Anual Total, Despesa Mensal, Número de
    Contratos, Necessidade de Empenho Total — os demais já aprovados antes (Saldo via
    Execução Anual, Contratos Ativos/Vencidos, Saldo Divergente) saíram do topo. Saldo e
    divergência continuam visíveis por cartão e no Resumo Consolidado, só não aparecem mais
    como contagem agregada na entrada da tela (mesmo pedido já atendido em
    `bolsas_auxilios.py`).
  * "Remover" apaga o item em definitivo do cadastro nativo (pedido explícito de
    desvinculação de planilha tornou o cadastro a fonte de verdade) — pede confirmação num
    segundo clique antes de excluir de fato, mesmo critério de `bolsas_auxilios.py`.
  * "+ Novo contrato" é um `st.popover` compacto no canto superior direito, ao lado do
    título — não um `st.expander` de largura total abaixo dele (mesmo padrão de
    `bolsas_auxilios.py`). Grava direto no cadastro nativo do exercício em tela, sobrevive a
    fechar o navegador.
  * Edição inline de cada cartão só grava no cadastro nativo quando o botão "💾 Salvar" do
    próprio cartão é clicado — mesmo critério de `bolsas_auxilios.py`.
  * `_aplicar_edicoes_da_sessao` sobrepõe, no DataFrame usado pelos quadros acima da lista,
    os valores já editados em cada cartão e recalcula `despesa_anual`/`meses_a_empenhar`/
    `valor_a_empenhar` a partir deles — sem isso, editar um campo só mudava o que aparecia
    dentro do próprio cartão, nunca nos KPIs, no Resumo Consolidado nem na Cobertura
    Orçamentária (mesmo bug relatado e corrigido primeiro em `bolsas_auxilios.py`). Roda
    antes de `com_saldo_execucao`, pelo mesmo motivo de lá.
  * "Carteira de contratos" minimizada por padrão — só 3 cartões (`QTD_INICIAL_CARTEIRA`) de
    início, com "Ver mais" revelando `QTD_INCREMENTO_CARTEIRA` (10) a mais por clique — mesmo
    padrão incremental de `app_pages/contratos_vigencia.py`/`app_pages/consulta_empenhos.py`.
    Originalmente era "um clique revela tudo de uma vez" (pedido explícito), mas virou
    incremental depois (pedido explícito de correção): cada cartão tem ~20 widgets ao vivo
    (cresceu desde a versão original com "Itens de Licitação"/"Início da Execução"), e revelar
    ~40 cartões de uma vez sobrecarregava o navegador o bastante pra "Ver mais" ficar
    lento/travado e o último cartão às vezes aparecer cortado a meio-render. "Ver menos"
    devolve ao estado minimizado. Mesmo padrão estendido ao "Resumo Consolidado" (pedido
    explícito em seguida): só as linhas visíveis (`QTD_INICIAL_RESUMO`) são limitadas — os
    totais do card (cabeçalho e rodapé) sempre somam o conjunto inteiro, nunca só o exibido.
  * Quadro "Empenhado × Liquidado" (pedido explícito) — mesmo layout HTML do Resumo
    Consolidado (`.cc-resumo-*`, mesma minimização "Ver mais"), comparando por NE o valor
    empenhado total contra o liquidado (`indice_liquidado_por_ne_curta`, novo em
    `src/execucao_anual.py`, ou `indice_liquidado_competencia` quando a base de competência
    está disponível — ver LIQUIDADO POR COMPETÊNCIA abaixo), abrangendo todos os contratos
    filtrados — inclusive os sem NE (aparecem com "sem NE" no lugar de liquidado/saldo). O
    saldo mostrado é o mesmo `saldo_execucao` (empenhada − liquidada por LANÇAMENTO, sempre
    via Execução Anual — não muda com a competência, é o saldo formal usado também na
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
por mês/total de LANÇAMENTO (Execução Anual/Mensal) pelo de COMPETÊNCIA (mês de referência —
`src/liquidacao_competencia.py`) quando `data/raw/Liquidação por Competência.xlsx` está
disponível; sem o arquivo, os três voltam ao comportamento anterior (liquidado por
lançamento), mesma lógica de ausência silenciosa das outras bases de trabalho desta página.
`saldo_execucao`/divergência contra a planilha (TG) NUNCA usam competência — são conceitos de
saldo formal, sempre por lançamento.
"""

from __future__ import annotations

import html as html_lib
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src.contratos_continuos import com_meses_pagos, com_saldo_execucao
from src.contratos_continuos_cadastro import (
    anos_disponiveis,
    atualizar_contrato,
    carregar_contratos,
    como_dataframe,
    duplicar_exercicio,
    excluir_contrato,
    excluir_exercicio,
    novo_contrato,
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
)
from src.execucao_anual import (
    agregar_por_ne,
    indice_liquidado_por_ne_curta,
    ne_curta as _ne_curta_execucao,
    saldo_por_ne,
)
from src.importacao_dotacao import Manifesto as ManifestoDotacao
from src.importacao_dotacao import NOME_PONTEIRO as NOME_PONTEIRO_DOTACAO
from src.importacao_dotacao import carregar_atual as carregar_dotacao_atual
from src.importacao_execucao import DIRETORIO_MANIFESTOS_PADRAO, Manifesto
from src.importacao_execucao import NOME_PONTEIRO as NOME_PONTEIRO_EXECUCAO
from src.importacao_execucao import carregar_atual as carregar_execucao_atual
from src.liquidacao_competencia import ler_liquidacao_competencia, liquidado_por_ne, liquidado_por_ne_e_mes
from src.necessidade_empenho import calcular_necessidade_empenho
from src.relatorio_reforco_empenho import CONTRATOS_CONTINUOS as RELATORIO_CONTRATOS_CONTINUOS
from src.tesouro_execucao_mensal import (
    ler_execucao_mensal,
    linha_do_tempo_por_ne,
    primeiro_mes_com_empenho_por_ne,
)
from src.ui_linha_do_tempo import MESES_ABREV, abrir_linha_do_tempo
from src.ui_relatorio_reforco_empenho import render_botao_relatorio
from src.ui_theme import format_brl_compact, render_metric_grid, render_page_header

DIRETORIO_DADOS_BRUTOS = Path("data/raw")
CAMINHO_PAGAMENTOS = DIRETORIO_DADOS_BRUTOS / "CONTRATOS - CONTROLE 2020 - Pagamentos.xlsx"
#: mesmo arquivo usado por app_pages/consulta_empenhos.py/bolsas_auxilios.py para a linha do
#: tempo mensal — base MENSAL (só 2026+), sem importação versionada ainda.
CAMINHO_EXECUCAO_MENSAL = Path("data/raw") / "BI CPOC - EXEC. DESPESAS - Mensal.xlsx"
#: mesmo arquivo usado por app_pages/consulta_empenhos.py (ver ali o porquê da troca) — usada
#: aqui para "Necessidade de Empenho" (ver `com_saldo_execucao`, parâmetro
#: `indice_liquidado_competencia`). Ausência do arquivo não impede o resto da página: a conta
#: volta a usar o liquidado por lançamento da Execução Anual (comportamento anterior a este
#: pedido).
CAMINHO_LIQUIDACAO_COMPETENCIA = Path("data/raw") / "Liquidação por Competência.xlsx"

COLUNAS_BUSCA = [
    "contrato_numero", "fornecedor", "tipo_despesa", "tipo_contrato", "acao_cod",
    "pi_cod", "unidade_cod", "processo_contratacao", "processo_empenho", "ne_curta",
]

STATUS_OPCOES = ["ATIVO", "VENCIDO"]


@st.cache_data(show_spinner="Lendo a base de Execução Anual...")
def _cached_por_ne_execucao(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    """`caminho_ponteiro`/`mtime_ponteiro` só participam da chave de cache — força reler
    quando o manifesto atual mudar. `carregar_atual` já devolve a base composta por ano (ver
    `src/importacao_execucao.py`)."""

    return saldo_por_ne(agregar_por_ne(carregar_execucao_atual()))


@st.cache_data(show_spinner="Lendo a linha do tempo mensal...")
def _cached_linha_do_tempo(caminho: str, mtime: float) -> pd.DataFrame:
    """Empenhado/Liquidado/Pago por (NE, mês), a partir da base MENSAL — com `ne_curta`
    acrescentada, pra poder ligar com o `ne_curta` já usado nos contratos. Pop-up "Linha do
    tempo mensal" (`src/ui_linha_do_tempo.py`), mesmo formato de
    `app_pages/bolsas_auxilios.py`/`app_pages/consulta_empenhos.py`. `mtime` só participa da
    chave de cache."""

    tempo = linha_do_tempo_por_ne(ler_execucao_mensal(caminho))
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


def _meses_restantes_no_ano(hoje: date | None = None) -> int:
    """Meses restantes até dezembro (inclusive o atual) — só para o Resumo Consolidado, não
    para a fórmula por cartão (ver docstring do módulo)."""

    hoje = hoje or date.today()
    return max(1, 12 - hoje.month + 1)


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
        /* Resumo Consolidado: mesmo padrão de cartão + grade HTML de app_pages/painel_acoes.py
           (.po-*) e app_pages/bolsas_auxilios.py (.bls-resumo-*), com prefixo próprio
           (.cc-resumo-*) — não é um st.dataframe: grade fixa, tipografia do projeto, sem cara
           de planilha.

           Pedido explícito posterior: cada NE virou um `st.button` clicável (abre pop-up de
           linha do tempo mensal, mesma função de `bolsas_auxilios.py`/`_render_resumo_consolidado`
           — ver `src/ui_linha_do_tempo.py`) — por isso o cartão externo trocou de
           `<div class="cc-resumo-card">` pra `st.container(border=True, key="cc_resumo_card")`:
           não dá pra ter um `st.button` clicável dentro de HTML injetado via `st.markdown` num
           único bloco.

           Pedido explícito de correção posterior: cabeçalho/linhas/rodapé do Resumo
           Consolidado viraram `st.columns` de verdade — mesma largura relativa nos três
           (`_LARGURAS_RESUMO` em `_render_resumo_consolidado`), com uma célula HTML dentro de
           cada coluna (`.cc-resumo-col-label`/`.cc-resumo-cell*`) — em vez de um cabeçalho em
           grade (`.cc-resumo-head-row`) prometendo colunas alinhadas que a linha de dados
           (`.cc-resumo-info`, flex-wrap solto) não respeitava ("muita informação no meio",
           sem alinhar com o cabeçalho). `.cc-resumo-card`/`.cc-resumo-head-row`/`.cc-resumo-foot`
           (grade) continuam em uso só pelo card "Empenhado × Liquidado"
           (`_render_empenhado_liquidado`, não alterado neste pedido — ainda é HTML injetado
           via `st.markdown` num bloco só, não `st.container`, porque não tem nenhum widget
           clicável dentro). */
        .cc-resumo-card {{
            border: 1px solid {BORDER}; border-radius: {RADIUS};
            background: {SURFACE}; padding: {CARD_PAD}; margin-bottom: {SPACE['xl']};
        }}
        .cc-resumo-head {{
            display: grid; grid-template-columns: minmax(0,1fr) auto;
            gap: 24px; align-items: start; margin-bottom: {SPACE['md']};
        }}
        .cc-resumo-kicker {{
            font-family: {FONT_HEADING}; font-size: {SIZE['value']};
            letter-spacing: {TRACK['kicker']}; color: {ACCENT}; text-transform: uppercase;
        }}
        .cc-resumo-title {{
            margin: 3px 0 0; font-family: {FONT_HEADING}; font-weight: 600;
            font-size: {SIZE['card_title']}; line-height: 1.12; color: {TEXT};
        }}
        .cc-resumo-metric-label {{
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: {TRACK['label']}; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .cc-resumo-metric {{
            font-family: {FONT_HEADING}; font-size: {SIZE['metric']}; line-height: 1.1;
            color: {ACCENT_STRONG}; font-variant-numeric: tabular-nums;
        }}
        .cc-resumo-row, .cc-resumo-head-row, .cc-resumo-foot {{
            display: grid; grid-template-columns: minmax(200px,2fr) 120px 120px 150px 120px;
            gap: 10px;
        }}
        .cc-resumo-head-row {{
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .cc-resumo-row {{
            padding: 9px 0; border-bottom: 1px solid {BORDER_SOFT}; align-items: baseline;
        }}
        .cc-resumo-foot {{ padding-top: 9px; font-family: {FONT_HEADING}; align-items: baseline; }}
        .st-key-cc_resumo_card button {{ justify-content: flex-start; text-align: left; }}
        .cc-resumo-nome-simples {{
            font-family: {FONT_BODY}; font-size: {SIZE['body']}; color: {TEXT};
            padding: 8px 0;
        }}
        .cc-resumo-col-label {{
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
        }}
        .cc-resumo-cell {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED}; padding: 8px 0;
        }}
        .cc-resumo-cell-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
            padding: 8px 0;
        }}
        .cc-resumo-name {{ font-family: {FONT_BODY}; font-size: {SIZE['body']}; line-height: 1.25; color: {TEXT}; }}
        .cc-resumo-code {{
            font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: {TRACK['label']}; color: {TEXT_MUTED};
        }}
        .cc-resumo-val {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED};
        }}
        .cc-resumo-val-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
        }}
        .cc-resumo-foot-label {{
            font-size: {SIZE['label']}; letter-spacing: {TRACK['label']};
            text-transform: uppercase; color: {TEXT_MUTED};
        }}
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
        /* Cobertura Orçamentária por PTRES: um cartão por Ação, mesmo padrão visual de
           app_pages/painel_acoes.py (.po-*) e app_pages/bolsas_auxilios.py (.bls-dotacao-*),
           reaproveitado aqui com prefixo próprio (.cc-dotacao-*). */
        .cc-dotacao-card {{
            border: 1px solid {BORDER}; border-radius: {RADIUS};
            background: {SURFACE}; padding: {CARD_PAD}; margin-bottom: {SPACE['lg']};
        }}
        .cc-dotacao-card-head {{
            display: grid; grid-template-columns: minmax(0,1fr) auto;
            gap: 24px; align-items: start; margin-bottom: {SPACE['md']};
        }}
        .cc-dotacao-kicker {{
            font-family: {FONT_HEADING}; font-size: {SIZE['value']};
            letter-spacing: {TRACK['kicker']}; color: {ACCENT}; text-transform: uppercase;
        }}
        .cc-dotacao-title {{
            margin: 3px 0 0; font-family: {FONT_HEADING}; font-weight: 600;
            font-size: {SIZE['card_title']}; line-height: 1.12; color: {TEXT};
            text-transform: uppercase; text-wrap: pretty;
        }}
        .cc-dotacao-metric-label {{
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: {TRACK['label']}; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .cc-dotacao-metric {{
            font-family: {FONT_HEADING}; font-size: {SIZE['metric']}; line-height: 1.1;
            font-variant-numeric: tabular-nums;
        }}
        .cc-dotacao-scroll {{ overflow-x: auto; padding-bottom: 2px; }}
        .cc-dotacao-row, .cc-dotacao-head-row, .cc-dotacao-foot {{
            display: grid; grid-template-columns: minmax(200px,2fr) 90px 130px 130px 130px;
            gap: 10px; min-width: 700px;
        }}
        .cc-dotacao-head-row {{
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .cc-dotacao-row {{
            padding: 9px 0; border-bottom: 1px solid {BORDER_SOFT}; align-items: baseline;
        }}
        .cc-dotacao-foot {{ padding-top: 9px; font-family: {FONT_HEADING}; align-items: baseline; }}
        .cc-dotacao-name {{ font-family: {FONT_BODY}; font-size: {SIZE['small']}; line-height: 1.25; color: {TEXT}; }}
        .cc-dotacao-code {{
            font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: {TRACK['label']}; color: {TEXT_MUTED};
        }}
        .cc-dotacao-flat {{
            font-family: {FONT_HEADING}; font-size: {SIZE['small']};
            letter-spacing: 0.08em; color: {TEXT_MUTED};
        }}
        .cc-dotacao-val {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED};
        }}
        .cc-dotacao-val-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums;
        }}
        .cc-dotacao-foot-label {{
            font-size: {SIZE['label']}; letter-spacing: {TRACK['label']};
            text-transform: uppercase; color: {TEXT_MUTED};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _campo_texto(col, label: str, valor: str, key: str) -> str:
    col.markdown(f"<div class='cc-label'>{label}</div>", unsafe_allow_html=True)
    return col.text_input(label, value=valor, key=key, label_visibility="collapsed")


def _campo_numero(col, label: str, valor: float, key: str, step: float = 1.0, fmt: str | None = None, min_value: float | None = None) -> float:
    col.markdown(f"<div class='cc-label'>{label}</div>", unsafe_allow_html=True)
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
    Reforço (`necessidade_ate_mes_vigente`) — mesmo campo/critério de
    `app_pages/bolsas_auxilios.py::_campo_inicio_execucao` (pedido explícito): "Automático"
    (`None` persistido) usa `sugestao_auto` (mês do primeiro empenho daquela NE, detectado a
    partir da base mensal); selecionar um mês específico grava um override manual."""

    col.markdown("<div class='cc-label'>Início da Execução</div>", unsafe_allow_html=True)
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
    pipeline (Execução Anual quando disponível, planilha como fallback — ver
    `com_saldo_execucao`); recalcular aqui a partir de `meses_empenhados`/`meses_liquidados`
    mostraria um número desatualizado sempre que a Execução Anual estiver disponível."""

    fornecedor = _ou_vazio(linha["fornecedor"]) or "(sem fornecedor)"
    numero = _ou_vazio(linha["contrato_numero"])
    valor_a_empenhar = _ou_zero(linha["valor_a_empenhar"])
    status_bruto = linha["status_contrato"]
    if pd.notna(status_bruto) and status_bruto == "VENCIDO":
        emoji = "🔴"
    elif valor_a_empenhar > 0:
        emoji = "🟡"
    else:
        emoji = "🟢"
    partes = [emoji, fornecedor]
    if numero:
        partes.append(f"— Nº {numero}")
    partes.append(f"· {_brl(valor_a_empenhar)}")
    return " ".join(partes)


def _render_card(
    linha: pd.Series, ano_exercicio: int, source_key: str, sugestao_inicio_por_ne: pd.Series,
) -> None:
    # `ano_exercicio` (parâmetro) != `ano` (variável local abaixo, campo "Ano" do contrato em
    # si) — nomes diferentes de propósito, para não colidir.
    id_contrato = str(linha["id"])
    k = f"cc_{source_key}_{id_contrato}"

    with st.expander(_rotulo_expander(linha), expanded=False):
        c_item, c_sit = st.columns([3, 1])
        fornecedor = _campo_texto(c_item, "Fornecedor", _ou_vazio(linha["fornecedor"]), f"{k}_fornecedor")
        c_sit.markdown("<div class='cc-label'>Status</div>", unsafe_allow_html=True)
        status_bruto = linha["status_contrato"]
        status_atual = status_bruto if pd.notna(status_bruto) and status_bruto in STATUS_OPCOES else "ATIVO"
        status = c_sit.selectbox(
            "Status", STATUS_OPCOES, index=STATUS_OPCOES.index(status_atual),
            key=f"{k}_status", label_visibility="collapsed",
        )

        r1 = st.columns(5)
        numero = _campo_texto(r1[0], "Nº Contrato", _ou_vazio(linha["contrato_numero"]), f"{k}_numero")
        ano = _campo_numero(r1[1], "Ano", _ou_zero(linha["ano_contrato"]) or 2026, f"{k}_ano", step=1.0, fmt="%d", min_value=2000.0)
        cnpj = _campo_texto(r1[2], "CNPJ/CPF", _ou_vazio(linha["fornecedor_cnpj_cpf"]), f"{k}_cnpj")
        tipo_despesa = _campo_texto(r1[3], "Tipo de Despesa", _ou_vazio(linha["tipo_despesa"]), f"{k}_tipodespesa")
        unidade = _campo_texto(r1[4], "Unidade", _ou_vazio(linha["unidade_cod"]), f"{k}_unidade")

        r2 = st.columns(5)
        acao = _campo_texto(r2[0], "Ação", _ou_vazio(linha["acao_cod"]), f"{k}_acao")
        ptres = _campo_texto(r2[1], "PTRES", _ou_vazio(linha["ptres"]), f"{k}_ptres")
        nd = _campo_texto(r2[2], "ND", _ou_vazio(linha["natureza_despesa_cod"]), f"{k}_nd")
        ugr = _campo_texto(r2[3], "UGR", _ou_vazio(linha["ugr_cod"]), f"{k}_ugr")
        pi = _campo_texto(r2[4], "PI", _ou_vazio(linha["pi_cod"]), f"{k}_pi")

        r3 = st.columns(4)
        ne_curta = _campo_texto(r3[0], "Empenho (NE)", _ou_vazio(linha["ne_curta"]), f"{k}_ne")
        # sem min_value=0.0: a base real tem meses_liquidados negativo em pelo menos um
        # registro (anulação/ajuste retroativo) — um piso de zero quebraria a leitura desse
        # valor já existente na origem.
        despesa_mensal = _campo_numero(r3[1], "Despesa Mensal Total (R$)", _ou_zero(linha["despesa_mensal"]), f"{k}_despmensal", step=100.0)
        valor_empenhado = _campo_numero(r3[2], "Empenhado (R$)", _ou_zero(linha["valor_empenhado"]), f"{k}_empenhado", step=100.0)
        saldo_planilha = _campo_numero(r3[3], "Saldo TG (R$)", _ou_zero(linha["saldo_colado_planilha"]), f"{k}_saldotg", step=100.0)

        r4 = st.columns(4)
        # Quando a NE já foi encontrada na Execução Anual, `meses_empenhados_execucao`/
        # `meses_liquidados_execucao` (ver `com_saldo_execucao`) substituem os campos manuais
        # da planilha na conta de "Empenhar" — os dois viram exibição, não mais editáveis,
        # para não sugerir que digitar ali teria algum efeito (deixaria de ter, e o cartão
        # voltaria a mostrar um número diferente do quadro "Resumo Consolidado" acima, o mesmo
        # bug de "dois quadros com meses a empenhar diferentes" já corrigido no relatório de
        # reforço de empenho). Sem NE na Execução, os campos continuam editáveis como sempre.
        via_execucao = pd.notna(linha["meses_empenhados_execucao"])
        if via_execucao:
            meses_empenhados = float(linha["meses_empenhados_execucao"])
            meses_liquidados = float(linha["meses_liquidados_execucao"])
            r4[0].markdown("<div class='cc-label'>Meses Empenhados (Execução Anual)</div>", unsafe_allow_html=True)
            r4[0].markdown(f"<div class='cc-calc'>{_num(meses_empenhados)}</div>", unsafe_allow_html=True)
            rotulo_liquidados = (
                "Meses Liquidados (Competência)"
                if bool(linha["liquidado_via_competencia"])
                else "Meses Liquidados (Execução Anual)"
            )
            r4[1].markdown(f"<div class='cc-label'>{rotulo_liquidados}</div>", unsafe_allow_html=True)
            r4[1].markdown(f"<div class='cc-calc'>{_num(meses_liquidados)}</div>", unsafe_allow_html=True)
            meses_empenhados_persistir = _ou_zero(linha["meses_empenhados"])
            meses_liquidados_persistir = _ou_zero(linha["meses_liquidados"])
        else:
            meses_empenhados = _campo_numero(r4[0], "Meses Empenhados", _ou_zero(linha["meses_empenhados"]), f"{k}_mesesemp", step=0.1)
            meses_liquidados = _campo_numero(r4[1], "Meses Liquidados", _ou_zero(linha["meses_liquidados"]), f"{k}_mesesliq", step=0.1)
            meses_empenhados_persistir = meses_empenhados
            meses_liquidados_persistir = meses_liquidados

        despesa_anual = despesa_mensal * 12
        meses_a_empenhar, valor_a_empenhar = calcular_necessidade_empenho(
            meses_empenhados, meses_liquidados, despesa_mensal
        )

        r4[2].markdown("<div class='cc-label'>Despesa Anual</div>", unsafe_allow_html=True)
        r4[2].markdown(f"<div class='cc-calc'>{_brl(despesa_anual)}</div>", unsafe_allow_html=True)
        r4[3].markdown("<div class='cc-label'>Meses de Saldo</div>", unsafe_allow_html=True)
        r4[3].markdown(f"<div class='cc-calc'>{_num(meses_a_empenhar)}</div>", unsafe_allow_html=True)

        r5 = st.columns(4)
        rotulo_empenhar = "Empenhar (Execução Anual)" if via_execucao else "Empenhar (planilha)"
        r5[0].markdown(f"<div class='cc-label'>{rotulo_empenhar}</div>", unsafe_allow_html=True)
        r5[0].markdown(f"<div class='cc-calc strong'>{_brl(valor_a_empenhar)}</div>", unsafe_allow_html=True)

        saldo_execucao = linha["saldo_execucao"]
        diverge_saldo = pd.notna(saldo_execucao) and abs(saldo_execucao - saldo_planilha) > 0.01
        r5[1].markdown("<div class='cc-label'>Saldo (Execução Anual)</div>", unsafe_allow_html=True)
        r5[1].markdown(f"<div class='cc-calc'>{_brl(saldo_execucao) if pd.notna(saldo_execucao) else 'sem NE'}</div>", unsafe_allow_html=True)

        # valor_empenhado_execucao é sempre no nível da NE inteira (mesmo valor repetido em
        # todo item do mesmo contrato/NE) — diverge_valor_empenhado já vem pronto de
        # com_saldo_execucao (comparado contra a SOMA dos itens da NE, não o item desta
        # linha), não recalculado aqui a partir do widget editável (que é só o valor do item:
        # comparar item contra total geraria falsa divergência em todo contrato com vários
        # itens, mesmo problema já evitado para saldo/SALDO TG ATUALIZADO).
        valor_empenhado_execucao = linha["valor_empenhado_execucao"]
        diverge_valor_empenhado = bool(linha["diverge_valor_empenhado"]) if pd.notna(linha["diverge_valor_empenhado"]) else False
        r5[2].markdown("<div class='cc-label'>Empenhado (Execução Anual) · NE</div>", unsafe_allow_html=True)
        r5[2].markdown(f"<div class='cc-calc'>{_brl(valor_empenhado_execucao) if pd.notna(valor_empenhado_execucao) else 'sem NE'}</div>", unsafe_allow_html=True)

        # Indicador INDEPENDENTE de meses_liquidados (campo manual acima, r4): quantos meses
        # distintos tiveram pagamento efetivamente registrado na planilha de Pagamentos e qual
        # foi o mais recente — casado pelo número de contrato normalizado (ver
        # `com_meses_pagos`), não pela NE. Liquidação e pagamento são estágios orçamentários
        # diferentes; este campo não corrige nem substitui "Meses Liquidados", é só mais um
        # dado para cruzar. "sem dado" quando o contrato não tem correspondência confiável na
        # planilha de Pagamentos (não é erro, ver docstring de `com_meses_pagos`).
        meses_pagos = linha["meses_pagos"]
        ultimo_mes_pago = linha["ultimo_mes_pago"]
        r5[3].markdown("<div class='cc-label'>Meses Pagos (Pagamentos) · último mês</div>", unsafe_allow_html=True)
        texto_meses_pagos = (
            f"{_num(meses_pagos)} · {_fmt_mes(ultimo_mes_pago)}" if pd.notna(meses_pagos) else "sem dado"
        )
        r5[3].markdown(f"<div class='cc-calc'>{texto_meses_pagos}</div>", unsafe_allow_html=True)

        sugestao_inicio = sugestao_inicio_por_ne.get(linha["ne_curta"]) if pd.notna(linha["ne_curta"]) else None
        col_inicio, _ = st.columns([1, 3])
        inicio_execucao_mes_editado = _campo_inicio_execucao(
            col_inicio, linha["inicio_execucao_mes"], sugestao_inicio, f"{k}_inicio",
        )

        # Itens de licitação — rateiam "Despesa Mensal Total" entre si (pedido explícito: no
        # SIAFI o reforço de empenho é por item, mas a liquidação não é dividida por item; o
        # item não é uma entidade própria com seu saldo/status, só um percentual do contrato,
        # usado só na hora de montar o Relatório de Reforço — ver
        # `src/relatorio_reforco_empenho.py::_linhas_expandidas_por_item`). Lista dinâmica em
        # `st.session_state` (não widgets nativos direto — precisa suportar adicionar/remover
        # linha), inicializada uma vez a partir do registro e só sincronizada de volta pra ele
        # ao clicar "Salvar".
        st.markdown("<div class='cc-label'>Itens de Licitação — rateio da Despesa Mensal (%)</div>", unsafe_allow_html=True)
        itens_key = f"{k}_itens"
        if itens_key not in st.session_state:
            origem = linha["itens"] if isinstance(linha["itens"], list) and linha["itens"] else [{"numero": 1, "percentual": 100.0}]
            st.session_state[itens_key] = [dict(item) for item in origem]
        itens_sessao = st.session_state[itens_key]

        for posicao in range(len(itens_sessao)):
            item = itens_sessao[posicao]
            c_num, c_pct, c_rem = st.columns([1, 2, 1])
            novo_numero = c_num.number_input(
                "Item", value=int(item["numero"]), step=1, min_value=1,
                key=f"{itens_key}_{posicao}_num", label_visibility="collapsed",
            )
            novo_percentual = c_pct.number_input(
                "%", value=float(item["percentual"]), step=1.0, min_value=0.0, max_value=100.0,
                key=f"{itens_key}_{posicao}_pct", label_visibility="collapsed",
            )
            itens_sessao[posicao] = {"numero": int(novo_numero), "percentual": float(novo_percentual)}
            if len(itens_sessao) > 1 and c_rem.button("✕ remover", key=f"{itens_key}_{posicao}_rem", use_container_width=True):
                itens_sessao.pop(posicao)
                st.rerun()

        soma_percentuais = sum(item["percentual"] for item in itens_sessao)
        cor_soma = POSITIVE if abs(soma_percentuais - 100) < 0.05 else NEGATIVE
        c_soma, c_add = st.columns([3, 1])
        c_soma.markdown(
            f"<div class='cc-calc' style='color:{cor_soma}'>Soma dos percentuais: {soma_percentuais:.1f}% "
            "(precisa fechar em 100% para salvar)</div>",
            unsafe_allow_html=True,
        )
        if c_add.button("+ Item", key=f"{itens_key}_add", use_container_width=True):
            proximo_numero = max((item["numero"] for item in itens_sessao), default=0) + 1
            itens_sessao.append({"numero": proximo_numero, "percentual": 0.0})
            st.rerun()

        eh_ativo = status == "ATIVO"
        tag_status_txt, tag_status_cls = ("Ativo", "ok") if eh_ativo else ("Vencido", "bad")
        if pd.isna(saldo_execucao):
            tag_div_txt, tag_div_cls = "Sem Execução", "bad"
        elif diverge_saldo or diverge_valor_empenhado:
            tag_div_txt, tag_div_cls = "Diverge", "bad"
        else:
            tag_div_txt, tag_div_cls = "Bate", "ok"

        f1, f2, f3 = st.columns([4, 1, 1])
        f1.markdown(
            f"<span class='cc-tag {tag_status_cls}'>{tag_status_txt}</span>"
            f"<span class='cc-tag {tag_div_cls}'>{tag_div_txt}</span>",
            unsafe_allow_html=True,
        )
        if f2.button("💾 Salvar", key=f"{k}_salvar", use_container_width=True):
            if abs(soma_percentuais - 100) > 0.5:
                st.error(f"A soma dos percentuais dos itens precisa fechar em 100% (está em {soma_percentuais:.1f}%).")
            else:
                atualizado = {
                    **linha.to_dict(),
                    "fornecedor": fornecedor or None, "status_contrato": status,
                    "contrato_numero": numero or None, "ano_contrato": ano,
                    "fornecedor_cnpj_cpf": cnpj or None, "tipo_despesa": tipo_despesa or None,
                    "unidade_cod": unidade or None, "acao_cod": acao or None, "ptres": ptres or None,
                    "natureza_despesa_cod": nd or None, "ugr_cod": ugr or None, "pi_cod": pi or None,
                    "ne_curta": ne_curta.strip() or None, "despesa_mensal": despesa_mensal,
                    "valor_empenhado": valor_empenhado, "saldo_colado_planilha": saldo_planilha,
                    "meses_empenhados": meses_empenhados_persistir, "meses_liquidados": meses_liquidados_persistir,
                    "itens": [dict(item) for item in itens_sessao],
                    "inicio_execucao_mes": inicio_execucao_mes_editado,
                }
                for chave_extra in (
                    "despesa_anual", "meses_a_empenhar", "valor_a_empenhar", "saldo_execucao",
                    "diverge_saldo", "valor_empenhado_execucao", "diverge_valor_empenhado",
                    "valor_liquidado_execucao", "liquidado_via_competencia", "valor_empenhado_planilha_total_ne",
                    "despesa_mensal_total_ne", "meses_empenhados_execucao", "meses_liquidados_execucao",
                    "necessidade_via", "meses_pagos", "ultimo_mes_pago", "contrato_normalizado",
                    "tem_varios_itens", "inicio_execucao_efetivo", "valor_empenhado_autoritativo",
                ):
                    atualizado.pop(chave_extra, None)
                atualizar_contrato(ano_exercicio, atualizado)
                st.session_state.pop(itens_key, None)
                st.success("Contrato salvo.")
                st.rerun()

        confirmar_key = f"{k}_confirmar_exclusao"
        if st.session_state.get(confirmar_key):
            if f3.button("Confirmar exclusão?", key=f"{k}_remover_confirmar", use_container_width=True, type="primary"):
                excluir_contrato(ano_exercicio, id_contrato)
                st.session_state.pop(confirmar_key, None)
                st.rerun()
        else:
            if f3.button("Remover", key=f"{k}_remover", use_container_width=True):
                st.session_state[confirmar_key] = True
                st.rerun()


def _render_novo_contrato(ano_exercicio: int, source_key: str) -> None:
    """"+ Novo contrato" — popover compacto no canto superior direito da tela (mesmo padrão
    de `bolsas_auxilios.py`), não um expander de largura total. Grava direto no cadastro
    nativo do exercício em tela (`src/contratos_continuos_cadastro.py`).

    `ano_exercicio` (parâmetro, o exercício em tela) != `ano` (campo do formulário abaixo, o
    ano do próprio contrato) — nomes diferentes de propósito, para não colidir."""

    with st.popover("+ Novo contrato", icon=":material/add:", width=380):
        with st.form(f"contratos_continuos_form_{source_key}", clear_on_submit=True):
            numero = st.text_input("Nº contrato")
            fornecedor = st.text_input("Fornecedor")
            c1, c2 = st.columns(2)
            ano = c1.number_input("Ano", min_value=2000, max_value=2100, value=2026, step=1)
            status = c2.selectbox("Status", STATUS_OPCOES)
            c3, c4 = st.columns(2)
            cnpj = c3.text_input("CNPJ/CPF")
            tipo_despesa = c4.text_input("Tipo de despesa")
            c5, c6 = st.columns(2)
            unidade = c5.text_input("Unidade")
            acao = c6.text_input("Ação")
            c7, c8 = st.columns(2)
            ptres = c7.text_input("PTRES")
            nd = c8.text_input("ND")
            c9, c10 = st.columns(2)
            ugr = c9.text_input("UGR")
            pi = c10.text_input("PI")
            c11, c12 = st.columns(2)
            ne_curta = c11.text_input("NE (opcional)", placeholder="ex. 2026NE000999")
            despesa_mensal = c12.number_input("Despesa mensal (R$)", min_value=0.0, step=100.0)
            c13, c14 = st.columns(2)
            valor_empenhado = c13.number_input("Valor empenhado (R$)", min_value=0.0, step=100.0)
            saldo_colado = c14.number_input("Saldo colado na planilha (R$)", min_value=0.0, step=100.0)
            c15, c16 = st.columns(2)
            meses_empenhados = c15.number_input("Meses empenhados", min_value=0.0, step=0.1)
            meses_liquidados = c16.number_input("Meses liquidados", min_value=0.0, step=0.1)

            if st.form_submit_button("Adicionar contrato"):
                if not numero or not fornecedor:
                    st.error("Informe ao menos o número do contrato e o fornecedor.")
                else:
                    registro = novo_contrato(
                        contrato_numero=numero, ano_contrato=ano, status_contrato=status,
                        fornecedor=fornecedor, fornecedor_cnpj_cpf=cnpj, tipo_despesa=tipo_despesa,
                        unidade_cod=unidade, acao_cod=acao, ptres=ptres,
                        natureza_despesa_cod=nd, ugr_cod=ugr, pi_cod=pi,
                        ne_curta=ne_curta.strip() or None, despesa_mensal=despesa_mensal,
                        valor_empenhado=valor_empenhado, saldo_colado_planilha=saldo_colado,
                        meses_empenhados=meses_empenhados, meses_liquidados=meses_liquidados,
                    )
                    salvar_contrato(ano_exercicio, registro)
                    st.success("Contrato cadastrado.")
                    st.rerun()


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


def _html_valor_resumo(valor: object, forte: bool = False) -> str:
    classe = "cc-resumo-cell-strong" if forte else "cc-resumo-cell"
    texto = "sem NE" if pd.isna(valor) else _brl(valor)
    return f'<div class="{classe}">{texto}</div>'


#: larguras relativas usadas por `st.columns` no cabeçalho de rótulos, em cada linha e no
#: rodapé do Resumo Consolidado — as três precisam ser exatamente as mesmas pra alinhar.
_LARGURAS_RESUMO = [2.2, 1, 1, 1.2, 1]

#: mesmo padrão de "Ver mais" de um clique só (não incremental) já usado na Carteira de
#: contratos abaixo — pedido explícito estendido para este card também.
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
    key_prefix: str,
) -> tuple[str, pd.DataFrame] | None:
    """Cabeçalho + uma linha por item de `linhas` (mesmas colunas do Resumo Consolidado) —
    compartilhado entre a visão inline do card (só as `QTD_INICIAL_RESUMO` primeiras) e o
    pop-up "Ver mais" (`_abrir_resumo_completo`, todas as linhas), pedido explícito posterior,
    pra não duplicar a lógica de linha clicável/legenda da "Linha do tempo mensal" nos dois
    lugares. `key_prefix` diferencia as chaves dos botões entre as duas superfícies (a mesma
    NE pode aparecer nas duas ao mesmo tempo — card por trás, pop-up por cima).

    NÃO abre o pop-up "Linha do tempo mensal" sozinha — devolve `(legenda, tempo_ne)` quando
    alguma linha foi clicada nesta execução (`None` caso contrário) e deixa o chamador decidir
    como abrir: `abrir_linha_do_tempo` direto (pop-up de verdade) quando o chamador está fora
    de qualquer dialog, ou via `st.session_state` + `st.rerun()` quando o chamador já está
    dentro de um pop-up aberto — Streamlit não permite dialog dentro de dialog (ver
    `_abrir_resumo_completo`, que usa a segunda opção)."""

    cabecalho = st.columns(_LARGURAS_RESUMO)
    cabecalho[0].markdown('<div class="cc-resumo-col-label">Fornecedor / Contrato</div>', unsafe_allow_html=True)
    cabecalho[1].markdown('<div class="cc-resumo-col-label" style="text-align:right">Valor Empenhado</div>', unsafe_allow_html=True)
    cabecalho[2].markdown('<div class="cc-resumo-col-label" style="text-align:right">Saldo</div>', unsafe_allow_html=True)
    cabecalho[3].markdown('<div class="cc-resumo-col-label" style="text-align:right">Necessidade até Dez.</div>', unsafe_allow_html=True)
    cabecalho[4].markdown('<div class="cc-resumo-col-label" style="text-align:right">Meses Liquidados</div>', unsafe_allow_html=True)

    clicado: tuple[str, pd.DataFrame] | None = None
    for fornecedor, contrato_numero, ne_curta_linha, valor_empenhado, saldo, necessidade, meses_liquidados, ultimo_mes_liquidado in linhas:
        rotulo = f"{_dash(fornecedor)} — {_dash(contrato_numero)}"
        clicavel = pd.notna(ne_curta_linha) and ne_curta_linha in nes_com_tempo
        linha = st.columns(_LARGURAS_RESUMO, vertical_alignment="center")
        if clicavel:
            if linha[0].button(rotulo, key=f"{key_prefix}_tempo_{source_key}_{ne_curta_linha}", use_container_width=True):
                tempo_ne = tempo_por_ne_curta[tempo_por_ne_curta["ne_curta"] == ne_curta_linha]
                if liquidacao_competencia_por_mes is not None:
                    tempo_ne = _tempo_com_liquidacao_por_competencia(
                        tempo_ne, ne_curta_linha, liquidacao_competencia_por_mes
                    )
                    legenda = (
                        f"{_dash(fornecedor)} (NE {ne_curta_linha}) — Empenhado e Pago por mês de "
                        "lançamento (Execução Mensal); Liquidado por mês de competência (Liquidação "
                        "por Competência), não por mês de lançamento."
                    )
                else:
                    legenda = f"{_dash(fornecedor)} (NE {ne_curta_linha}) — base mensal (2026+)."
                clicado = (legenda, tempo_ne)
        else:
            linha[0].markdown(f'<div class="cc-resumo-nome-simples">{_esc(rotulo)}</div>', unsafe_allow_html=True)
        linha[1].markdown(_html_valor_resumo(valor_empenhado), unsafe_allow_html=True)
        linha[2].markdown(_html_valor_resumo(saldo), unsafe_allow_html=True)
        linha[3].markdown(_html_valor_resumo(necessidade, forte=True), unsafe_allow_html=True)
        linha[4].markdown(f'<div class="cc-resumo-cell">{_texto_meses_liquidados(meses_liquidados, ultimo_mes_liquidado)}</div>', unsafe_allow_html=True)
    return clicado


def _render_rodape_resumo(valor_empenhado_total: float, saldo_total: float, necessidade_total: float) -> None:
    rodape = st.columns(_LARGURAS_RESUMO)
    rodape[0].markdown('<div class="cc-resumo-foot-label">Total</div>', unsafe_allow_html=True)
    rodape[1].markdown(_html_valor_resumo(valor_empenhado_total), unsafe_allow_html=True)
    rodape[2].markdown(_html_valor_resumo(saldo_total), unsafe_allow_html=True)
    rodape[3].markdown(_html_valor_resumo(necessidade_total, forte=True), unsafe_allow_html=True)
    rodape[4].markdown("", unsafe_allow_html=True)


@st.dialog("Resumo Consolidado — todas as NEs/contratos", width="large")
def _abrir_resumo_completo(
    linhas: list[tuple],
    totais: tuple[float, float, float],
    tempo_por_ne_curta: pd.DataFrame | None,
    liquidacao_competencia_por_mes: pd.DataFrame | None,
    nes_com_tempo: set[str],
    source_key: str,
) -> None:
    """Pop-up com TODAS as linhas do Resumo Consolidado (pedido explícito posterior: "Ver
    mais" deixou de expandir a lista dentro do próprio card — virou este pop-up, mesmo padrão
    de `abrir_linha_do_tempo`/`src/ui_linha_do_tempo.py`). Reaproveita `_render_linhas_resumo`
    (mesmas colunas/mesma NE clicável do card) e `_render_rodape_resumo` (mesmos totais do
    conjunto inteiro, já calculados por `_render_resumo_consolidado`, não recalculados aqui).

    Clicar numa NE aqui NÃO embute a "Linha do tempo mensal" dentro deste mesmo pop-up
    (Streamlit proíbe abrir um `st.dialog` dentro de outro já aberto —
    `StreamlitAPIException: Dialogs may not be nested inside other dialogs`; era assim antes,
    mas o usuário pediu pop-up de verdade, não embutido abaixo do Total). Em vez disso, guarda
    a seleção em `st.session_state` e fecha este pop-up (`st.rerun()` de dentro de um dialog o
    fecha); `_render_resumo_consolidado`, fora de qualquer dialog, lê essa seleção pendente no
    rerun seguinte e chama `abrir_linha_do_tempo` — um pop-up de verdade, substituindo o "Ver
    mais" em vez de empilhar os dois."""

    valor_empenhado_total, saldo_total, necessidade_total = totais
    st.caption(f"{len(linhas)} {'NE/contrato' if len(linhas) == 1 else 'NEs/contratos'}")
    clicado = _render_linhas_resumo(
        linhas, tempo_por_ne_curta, liquidacao_competencia_por_mes, nes_com_tempo, source_key,
        key_prefix="cc_resumo_completo",
    )
    _render_rodape_resumo(valor_empenhado_total, saldo_total, necessidade_total)
    if clicado is not None:
        st.session_state[f"cc_resumo_tempo_pendente_{source_key}"] = clicado
        st.rerun()


def _render_resumo_consolidado(
    filtrado: pd.DataFrame,
    meses_restantes: int,
    tempo_por_ne_curta: pd.DataFrame | None,
    source_key: str,
    liquidacao_competencia_por_mes: pd.DataFrame | None = None,
    meses_liquidados_por_ne: pd.DataFrame | None = None,
) -> None:
    """Card único, visível de início (antes de abrir qualquer cartão), listando — uma linha
    por NE, não por item de licitação nem um total agregado — o valor empenhado, o saldo e a
    necessidade de empenho até dezembro. Diferente de `bolsas_auxilios.py` (1 linha == 1
    bolsa == 1 NE), aqui um contrato pode ter vários itens de licitação na mesma NE — agrupa-
    se por NE antes de listar, mesma unidade já usada por `_somar_unico_por_ne`/
    `_contar_unico_por_ne`, para não repetir a mesma NE várias vezes nem contar seu saldo mais
    de uma vez. Itens sem NE (contrato ainda sem empenho) aparecem à parte, um por linha, já
    que não há NE para agrupar — e nunca são clicáveis (não há NE pra buscar na base mensal).

    Pedido explícito: cada NE com dado na base MENSAL (2026+) é clicável — abre o mesmo pop-up
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
    `saldo_execucao` de sempre (Execução Anual, por lançamento), nunca mistura as duas dentro
    do mesmo NE. Antes este card usava sempre `saldo_execucao`, inconsistente com o resto da
    página (que já mostrava Liquidado por competência) — corrigido a pedido do usuário.

    Minimizado por padrão (`QTD_INICIAL_RESUMO`, pedido explícito) — o card sempre mostra só
    as `QTD_INICIAL_RESUMO` primeiras linhas; os totais do card (cabeçalho e rodapé) somam
    sempre o conjunto inteiro (`por_ne`/`sem_ne` completos), não só o que está à mostra.

    "Ver mais" abre um pop-up com a lista completa (`_abrir_resumo_completo`, pedido explícito
    posterior — antes expandia a lista dentro do próprio card; virou pop-up para não empurrar
    o resto da página pra baixo com dezenas de linhas). Card e pop-up reaproveitam a mesma
    renderização de linha (`_render_linhas_resumo`) e de rodapé (`_render_rodape_resumo`).

    Coluna "Meses Liquidados" (pedido explícito posterior — antes "Meses Pagos", vinda da
    planilha separada de Pagamentos): agora vem de `meses_liquidados_por_ne`
    (`_meses_liquidados_por_ne_curta`, Liquidação por Competência) — quantos meses a NE já tem
    de liquidação apurada por competência, não quantos meses tiveram pagamento registrado."""

    if meses_liquidados_por_ne is None:
        meses_liquidados_por_ne = pd.DataFrame(columns=_COLUNAS_MESES_LIQUIDADOS)

    com_ne = filtrado.dropna(subset=["ne_curta"])
    sem_ne = filtrado[filtrado["ne_curta"].isna()].copy()

    por_ne = com_ne.groupby("ne_curta", sort=False).agg(
        fornecedor=("fornecedor", "first"),
        contrato_numero=("contrato_numero", "first"),
        despesa_mensal=("despesa_mensal", "sum"),
        valor_empenhado_execucao=("valor_empenhado_execucao", "first"),
        valor_empenhado_planilha_total_ne=("valor_empenhado_planilha_total_ne", "first"),
        valor_liquidado_execucao=("valor_liquidado_execucao", "first"),
        liquidado_via_competencia=("liquidado_via_competencia", "first"),
        saldo_execucao=("saldo_execucao", "first"),
        saldo_colado_planilha=("saldo_colado_planilha", "first"),
    ).reset_index()
    por_ne = por_ne.merge(meses_liquidados_por_ne, on="ne_curta", how="left")
    por_ne["valor_empenhado_exibido"] = por_ne["valor_empenhado_execucao"].fillna(por_ne["valor_empenhado_planilha_total_ne"])

    # Saldo usado na Necessidade até Dezembro (pedido explícito posterior): por NE com
    # competência apurada (`liquidado_via_competencia` E `valor_liquidado_execucao` notna —
    # ver `com_saldo_execucao`), Empenhado − Liquidado por COMPETÊNCIA, não por lançamento;
    # sem competência para aquela NE (arquivo ausente, ou NE sem nenhuma linha apurada ainda),
    # cai no `saldo_execucao` de sempre (Execução Anual, por lançamento) — mesmo critério de
    # fallback por linha já usado em `com_saldo_execucao`, nunca mistura as duas dentro do
    # mesmo NE. Diferente do quadro "Empenhado × Liquidado" (saldo sempre por lançamento, ali
    # por ser o saldo formal comparado contra o TG): aqui não há essa comparação, então o
    # saldo pode acompanhar a fonte mais correta do Liquidado sem gerar contradição visível.
    usa_competencia_na_necessidade = por_ne["liquidado_via_competencia"].fillna(False) & por_ne["valor_liquidado_execucao"].notna()
    saldo_competencia = por_ne["valor_empenhado_exibido"] - por_ne["valor_liquidado_execucao"]
    saldo_lancamento_fallback = por_ne["saldo_execucao"].fillna(por_ne["saldo_colado_planilha"]).fillna(0.0)
    por_ne["saldo_para_necessidade"] = saldo_competencia.where(usa_competencia_na_necessidade, saldo_lancamento_fallback)
    por_ne["necessidade"] = (por_ne["despesa_mensal"] * meses_restantes - por_ne["saldo_para_necessidade"]).clip(lower=0)
    algum_ne_via_competencia = bool(usa_competencia_na_necessidade.any())

    sem_ne["valor_empenhado_exibido"] = sem_ne["valor_empenhado"]
    sem_ne["necessidade"] = (sem_ne["despesa_mensal"] * meses_restantes).clip(lower=0)

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

    saldo_total = por_ne["saldo_para_necessidade"].sum()
    visiveis = linhas[:QTD_INICIAL_RESUMO]

    with st.container(border=True, key="cc_resumo_card"):
        st.markdown(
            f"""
            <div class="cc-resumo-head">
              <div style="min-width:0">
                <div class="cc-resumo-kicker">RESUMO CONSOLIDADO</div>
                <div class="cc-resumo-title">Necessidade de Empenho por NE</div>
              </div>
              <div style="text-align:right">
                <div class="cc-resumo-metric-label">Necessidade até Dezembro ({meses_restantes}m)</div>
                <div class="cc-resumo-metric">{_brl(necessidade_total)}</div>
                <div class="cc-resumo-metric-label" style="margin-top:4px">
                  {total_linhas} {"NE/contrato" if total_linhas == 1 else "NEs/contratos"}
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if algum_ne_via_competencia:
            st.caption(
                "Saldo/Necessidade usa Liquidado por competência (mês de referência) para as NEs com "
                "competência já apurada; sem competência para a NE, continua por lançamento (Execução Anual)."
            )
        clicado = _render_linhas_resumo(
            visiveis, tempo_por_ne_curta, liquidacao_competencia_por_mes, nes_com_tempo, source_key,
            key_prefix="cc_resumo",
        )
        _render_rodape_resumo(valor_empenhado_total, saldo_total, necessidade_total)

    if clicado is not None:
        abrir_linha_do_tempo(*clicado)

    if total_linhas > QTD_INICIAL_RESUMO:
        st.caption(f"Mostrando {QTD_INICIAL_RESUMO} de {total_linhas} linhas no resumo")
        if st.button("Ver mais", key=f"cc_resumo_ver_mais_{source_key}"):
            _abrir_resumo_completo(
                linhas, (valor_empenhado_total, saldo_total, necessidade_total),
                tempo_por_ne_curta, liquidacao_competencia_por_mes, nes_com_tempo, source_key,
            )
    elif total_linhas:
        st.caption(f"Mostrando todas as {total_linhas} linhas no resumo")

    # NE clicada dentro do pop-up "Ver mais" (`_abrir_resumo_completo`, fora deste `with`,
    # já fechado pelo `st.rerun()` de dentro do dialog) — abre a "Linha do tempo mensal" como
    # pop-up de verdade aqui fora, em vez de embutida abaixo do Total dentro do "Ver mais".
    pendente_key = f"cc_resumo_tempo_pendente_{source_key}"
    pendente = st.session_state.pop(pendente_key, None)
    if pendente is not None:
        abrir_linha_do_tempo(*pendente)


def _html_linha_empenhado_liquidado(
    principal: object, secundario: object, empenhado: object, liquidado: object, saldo: object,
    meses_liquidados: object = pd.NA, ultimo_mes_liquidado: object = pd.NA,
) -> str:
    empenhado_texto = "sem NE" if pd.isna(empenhado) else _brl(empenhado)
    if pd.isna(saldo):
        saldo_html = f'<span class="cc-resumo-val-strong">sem NE</span>'
        liquidado_texto = "sem NE"
    else:
        rotulo = "Sobra" if saldo >= 0 else "Insuficiência"
        cor = POSITIVE if saldo >= 0 else NEGATIVE
        saldo_html = f'<span class="cc-resumo-val-strong" style="color:{cor}">{_brl(saldo)} · {rotulo}</span>'
        liquidado_texto = _brl(liquidado)
    return (
        '<div class="cc-resumo-row">'
        f'<div><div class="cc-resumo-name">{_dash(principal)}</div><div class="cc-resumo-code">{_dash(secundario)}</div></div>'
        f'<span class="cc-resumo-val">{empenhado_texto}</span>'
        f'<span class="cc-resumo-val">{liquidado_texto}</span>'
        f"{saldo_html}"
        f'<span class="cc-resumo-val">{_texto_meses_liquidados(meses_liquidados, ultimo_mes_liquidado)}</span>'
        "</div>"
    )


def _render_empenhado_liquidado(
    filtrado: pd.DataFrame, indice_liquidado: pd.Series, source_key: str,
    meses_liquidados_por_ne: pd.DataFrame, via_competencia: bool = False,
) -> None:
    """Quadro comparando, por NE, o valor empenhado total contra o liquidado (pedido
    explícito) — mesmo layout do Resumo Consolidado acima (`.cc-resumo-*`), abrangendo TODOS
    os contratos filtrados, inclusive os sem NE (aparecem com "sem NE" no lugar de
    liquidado/saldo, já que não há NE para buscar na Execução Anual).

    `indice_liquidado`/`via_competencia` (pedido explícito posterior — ver LIQUIDADO POR
    COMPETÊNCIA na docstring do módulo): Liquidação por Competência quando disponível,
    Execução Anual (por lançamento) como fallback — mesma fonte de `com_saldo_execucao`.

    O saldo é o mesmo `saldo_execucao` (empenhada − liquidada por LANÇAMENTO, sempre via
    Execução Anual — nunca muda com `via_competencia`) já usado no resto da página, não uma
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
    linhas_html = "".join(_html_linha_empenhado_liquidado(*linha) for linha in visiveis)

    rotulo_total = "Sobra" if saldo_total >= 0 else "Insuficiência"
    cor_total = POSITIVE if saldo_total >= 0 else NEGATIVE
    rotulo_liquidado = "Liquidado (Competência)" if via_competencia else "Liquidado (Execução Anual)"
    # Sem indentação/quebra de linha própria de propósito: um `st.markdown` com HTML
    # interpreta 4+ espaços no início de uma linha como bloco de código (regra do Markdown,
    # não do Streamlit) — uma string de várias linhas indentada aqui aparecia crua na tela em
    # vez de renderizada (bug já visto: o HTML do aviso apareceu como texto solto no card).
    nota_competencia = (
        '<div class="cc-resumo-metric-label" style="margin:4px 0 8px 0">'
        "Liquidado por competência (mês de referência) — Saldo continua Empenhado − Liquidado "
        "por lançamento (Execução Anual, mesmo saldo formal do resto da página); as duas colunas "
        "não somam entre si."
        "</div>"
        if via_competencia
        else ""
    )

    st.markdown(
        f"""
        <div class="cc-resumo-card">
          <div class="cc-resumo-head">
            <div style="min-width:0">
              <div class="cc-resumo-kicker">EMPENHADO × LIQUIDADO</div>
              <div class="cc-resumo-title">Sobra ou Insuficiência no Empenho, por NE</div>
            </div>
            <div style="text-align:right">
              <div class="cc-resumo-metric-label">Saldo Total ({rotulo_total})</div>
              <div class="cc-resumo-metric" style="color:{cor_total}">{_brl(saldo_total)}</div>
              <div class="cc-resumo-metric-label" style="margin-top:4px">
                {total_linhas} {"NE/contrato" if total_linhas == 1 else "NEs/contratos"}
              </div>
            </div>
          </div>
          {nota_competencia}
          <div class="cc-resumo-scroll">
            <div class="cc-resumo-head-row">
              <span>Fornecedor / Contrato</span>
              <span style="text-align:right">Empenhado</span>
              <span style="text-align:right">{rotulo_liquidado}</span>
              <span style="text-align:right">Saldo</span>
              <span style="text-align:right">Meses Liquidados</span>
            </div>
            {linhas_html}
            <div class="cc-resumo-foot">
              <span class="cc-resumo-foot-label">Total</span>
              <span class="cc-resumo-val">{_brl(empenhado_total)}</span>
              <span class="cc-resumo-val">{_brl(liquidado_total)}</span>
              <span class="cc-resumo-val-strong" style="color:{cor_total}">{_brl(saldo_total)}</span>
              <span class="cc-resumo-val"></span>
            </div>
          </div>
        </div>
        """,
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


_CABECALHO_DOTACAO = [
    ("Plano orçamentário", ""), ("PTRES", ""),
    ("Dotação atualizada", "right"), ("Despesa estimada", "right"), ("Saldo", "right"),
]


def _html_cabecalho_dotacao() -> str:
    celulas = "".join(
        f'<span style="text-align:{alinhamento or "left"}">{texto}</span>'
        for texto, alinhamento in _CABECALHO_DOTACAO
    )
    return f'<div class="cc-dotacao-head-row">{celulas}</div>'


def _par_dotacao(nome: object, codigo: object, prefixo: str = "") -> str:
    nome_texto = "(não informado)" if pd.isna(nome) else _esc(nome)
    return (
        f'<div><div class="cc-dotacao-name">{nome_texto}</div>'
        f'<div class="cc-dotacao-code">{prefixo}{_dash(codigo)}</div></div>'
    )


def _html_linha_dotacao(linha: pd.Series) -> str:
    dotacao, despesa = linha["dotacao_atualizada"], linha["despesa_estimada"]
    dotacao_texto = "sem dotação" if pd.isna(dotacao) else _brl(dotacao)
    if pd.isna(dotacao):
        saldo_html = "<span class='cc-dotacao-val-strong'>—</span>"
    else:
        saldo = float(dotacao) - despesa
        cor = POSITIVE if saldo >= 0 else NEGATIVE
        saldo_html = f"<span class='cc-dotacao-val-strong' style='color:{cor}'>{_brl(saldo)}</span>"
    return (
        '<div class="cc-dotacao-row">'
        + _par_dotacao(linha["plano_orcamentario_descricao"], linha["plano_orcamentario_codigo"], "PO ")
        + f'<span class="cc-dotacao-flat">{_dash(linha["ptres_codigo"])}</span>'
        + f'<span class="cc-dotacao-val">{dotacao_texto}</span>'
        + f'<span class="cc-dotacao-val">{_brl(despesa)}</span>'
        + saldo_html
        + "</div>"
    )


def _render_card_dotacao(codigo: object, nome: object, grupo: pd.DataFrame) -> None:
    """Um cartão por Ação de Governo, com uma subdivisão por PTRES (Plano Orçamentário +
    PTRES) dentro — mesmo padrão visual de `app_pages/painel_acoes.py::_render_card`,
    reaproveitado aqui (e em `bolsas_auxilios.py`) com prefixo próprio `.cc-dotacao-*`."""

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
        <div class="cc-dotacao-card">
          <div class="cc-dotacao-card-head">
            <div style="min-width:0">
              <div class="cc-dotacao-kicker">AÇÃO DE GOVERNO {_esc(codigo)}</div>
              <div class="cc-dotacao-title">{_dash(nome)}</div>
            </div>
            <div style="text-align:right">
              <div class="cc-dotacao-metric-label">Saldo (Dotação − Despesa Estimada)</div>
              <div class="cc-dotacao-metric" style="color:{cor_total}">{saldo_texto}</div>
              <div class="cc-dotacao-metric-label" style="margin-top:4px">{n} PTRES</div>
            </div>
          </div>
          <div class="cc-dotacao-scroll">
            {_html_cabecalho_dotacao()}
            {linhas_html}
            <div class="cc-dotacao-foot">
              <span class="cc-dotacao-foot-label">Total da ação</span>
              <span class="cc-dotacao-val">{_brl(dotacao_total)}</span>
              <span class="cc-dotacao-val">{_brl(despesa_total)}</span>
              <span class="cc-dotacao-val-strong" style="color:{cor_total}">{saldo_texto}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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


#: sufixo da key do widget (ver `_render_card`) -> coluna do DataFrame que ele edita.
_CAMPOS_EDITAVEIS_NUMERICOS = {
    "ano": "ano_contrato", "despmensal": "despesa_mensal", "empenhado": "valor_empenhado",
    "saldotg": "saldo_colado_planilha", "mesesemp": "meses_empenhados", "mesesliq": "meses_liquidados",
}
_CAMPOS_EDITAVEIS_TEXTO = {
    "fornecedor": "fornecedor", "numero": "contrato_numero", "cnpj": "fornecedor_cnpj_cpf",
    "tipodespesa": "tipo_despesa", "unidade": "unidade_cod", "acao": "acao_cod", "ptres": "ptres",
    "nd": "natureza_despesa_cod", "ugr": "ugr_cod", "pi": "pi_cod", "ne": "ne_curta",
}


def _aplicar_edicoes_da_sessao(dataframe: pd.DataFrame, source_key: str) -> pd.DataFrame:
    """Sobrepõe, por linha, os valores já editados nos widgets de cada cartão (persistidos em
    `st.session_state` pela própria key do widget, ver `_render_card`) e recalcula os campos
    derivados a partir deles — sem isso, os quadros acima da lista (KPIs, Resumo Consolidado,
    Cobertura Orçamentária) ficavam presos ao valor original da planilha mesmo depois de uma
    edição inline no cartão. Mesmo padrão de
    `app_pages/bolsas_auxilios.py::_aplicar_edicoes_da_sessao`. Roda antes de
    `com_saldo_execucao`, para uma edição no campo NE também atualizar
    `saldo_execucao`/`valor_empenhado_execucao` daquela linha."""

    resultado = dataframe.copy()
    for indice, id_contrato in zip(resultado.index, resultado["id"]):
        k = f"cc_{source_key}_{id_contrato}"
        for sufixo, coluna in _CAMPOS_EDITAVEIS_NUMERICOS.items():
            valor = st.session_state.get(f"{k}_{sufixo}")
            if valor is not None:
                resultado.at[indice, coluna] = valor
        for sufixo, coluna in _CAMPOS_EDITAVEIS_TEXTO.items():
            valor = st.session_state.get(f"{k}_{sufixo}")
            if valor is not None:
                resultado.at[indice, coluna] = valor if valor != "" else pd.NA
        status = st.session_state.get(f"{k}_status")
        if status is not None:
            resultado.at[indice, "status_contrato"] = status

    # mesmas fórmulas usadas dentro do cartão (`_render_card`) e na leitura original
    # (`ler_contratos_continuos`) — reaproveitadas aqui, não reimplementadas.
    resultado["despesa_anual"] = resultado["despesa_mensal"] * 12
    resultado["meses_a_empenhar"], resultado["valor_a_empenhar"] = calcular_necessidade_empenho(
        resultado["meses_empenhados"], resultado["meses_liquidados"], resultado["despesa_mensal"]
    )
    return resultado


# ---------------------------------------------------------------------- página
_inject_css()

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
        "Necessidade de reforço de empenho por contrato, cruzado com a Execução Anual.",
        "Contratos",
    )
with col_novo:
    st.write("")
    _render_novo_contrato(ano_selecionado, source_key)

manifesto_execucao = Manifesto.atual()
if manifesto_execucao is None:
    st.info(
        "Nenhuma base de Execução Anual foi importada ainda — é dela que vem o saldo "
        "autoritativo por NE. Importe a Execução Anual antes de usar esta página."
    )
    st.stop()

caminho_ponteiro_execucao = DIRETORIO_MANIFESTOS_PADRAO / NOME_PONTEIRO_EXECUCAO

try:
    registros = carregar_contratos(ano_selecionado)
    dataframe = como_dataframe(registros)
    por_ne_execucao = _cached_por_ne_execucao(
        str(caminho_ponteiro_execucao), caminho_ponteiro_execucao.stat().st_mtime
    )
except Exception as error:
    st.error(f"Não foi possível ler os dados: {error}")
    st.stop()

# Base mensal (2026+) só para o pop-up "Linha do tempo mensal" do Resumo Consolidado —
# opcional: sem o arquivo, o resumo continua funcionando normal, só sem nenhuma NE clicável.
tempo_por_ne_curta: pd.DataFrame | None = None
if CAMINHO_EXECUCAO_MENSAL.exists():
    try:
        tempo_por_ne_curta = _cached_linha_do_tempo(
            str(CAMINHO_EXECUCAO_MENSAL), CAMINHO_EXECUCAO_MENSAL.stat().st_mtime
        )
    except Exception:
        tempo_por_ne_curta = None

# Liquidação por Competência, para "Necessidade de Empenho" (ver com_saldo_execucao) —
# opcional: sem o arquivo, a conta volta a usar o liquidado por lançamento da Execução Anual
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

dataframe = _aplicar_edicoes_da_sessao(dataframe, source_key)
dataframe = com_saldo_execucao(dataframe, por_ne_execucao, indice_liquidado_competencia)
dataframe = com_meses_pagos(dataframe, meses_pagos_por_contrato_df)

# "Início da Execução" (mês do primeiro empenho de cada NE, auto-detectado da base mensal) e
# valor empenhado autoritativo — só para a sugestão inicial "por calendário" do Relatório de
# Reforço (pedido explícito, ver `src.necessidade_empenho.necessidade_ate_mes_vigente`);
# nenhum outro quadro da página usa essas duas colunas.
if tempo_por_ne_curta is not None:
    sugestao_inicio_por_ne = primeiro_mes_com_empenho_por_ne(tempo_por_ne_curta)
else:
    sugestao_inicio_por_ne = pd.Series(dtype="Int64")
dataframe["valor_empenhado_autoritativo"] = dataframe["valor_empenhado_execucao"].fillna(dataframe["valor_empenhado"])
dataframe["inicio_execucao_efetivo"] = dataframe["inicio_execucao_mes"].fillna(
    dataframe["ne_curta"].map(sugestao_inicio_por_ne)
)

with col_relatorio:
    st.write("")
    render_botao_relatorio(dataframe, RELATORIO_CONTRATOS_CONTINUOS, f"continuos_{ano_selecionado}")

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

render_metric_grid(
    [
        {"label": "Despesa Anual Total", "value": format_brl_compact(filtrado["despesa_anual"].sum())},
        {"label": "Despesa Mensal", "value": format_brl_compact(filtrado["despesa_mensal"].sum())},
        {"label": "Número de Contratos", "value": str(filtrado["contrato_numero"].nunique())},
        {"label": "Necessidade de Empenho Total", "value": format_brl_compact(filtrado["valor_a_empenhar"].sum())},
    ],
    columns=4,
)

_render_resumo_consolidado(
    filtrado, _meses_restantes_no_ano(), tempo_por_ne_curta, source_key, liquidacao_competencia_por_mes,
    meses_liquidados_por_ne,
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
    st.subheader("Cobertura Orçamentária por PTRES")
    _render_quadro_dotacao(filtrado, dotacao_dimensoes, ano_exercicio_dotacao)
else:
    st.info(
        "Nenhuma base de Dotação Anual foi importada ainda — o quadro de cobertura "
        "orçamentária por PTRES depende dela. Importe a Dotação Anual para vê-lo aqui."
    )

st.subheader("Carteira de contratos")
st.caption("🟢 Ativo, sem necessidade de reforço · 🟡 Necessita reforço de empenho · 🔴 Vencido")

# minimizada por padrão — só QTD_INICIAL_CARTEIRA (3) cartões de início. "Ver mais" revela
# QTD_INCREMENTO_CARTEIRA (10) a mais por clique (não tudo de uma vez) — pedido explícito de
# correção: cada cartão tem ~20 widgets ao vivo ("Itens de Licitação"/"Início da Execução"
# aumentaram esse número desde a versão anterior), revelar os ~40 de uma vez sobrecarregava
# o navegador o bastante pra deixar "Ver mais" lento/travado e o último cartão às vezes
# aparecer cortado a meio-render — mesmo padrão incremental já usado em
# `app_pages/contratos_vigencia.py`/`app_pages/consulta_empenhos.py`.
QTD_INICIAL_CARTEIRA = 3
QTD_INCREMENTO_CARTEIRA = 10
qtd_visivel_key = f"cc_carteira_qtd_visivel_{source_key}"
qtd_visivel = st.session_state.get(qtd_visivel_key, QTD_INICIAL_CARTEIRA)
# ordem alfabética por fornecedor (pedido explícito) — case-insensitive, fornecedor em
# branco por último; só afeta esta lista (Resumo Consolidado/Empenhado × Liquidado/Cobertura
# Orçamentária já ordenam por conta própria a partir de `filtrado`, sem depender da ordem dele).
carteira_ordenada = filtrado.sort_values("fornecedor", key=lambda s: s.str.casefold(), na_position="last")
visiveis = carteira_ordenada.iloc[:qtd_visivel]

with st.container(key="cc_lista"):
    for _, linha in visiveis.iterrows():
        _render_card(linha, ano_selecionado, source_key, sugestao_inicio_por_ne)

if qtd_visivel < len(filtrado):
    st.caption(f"Mostrando {min(qtd_visivel, len(filtrado))} de {len(filtrado)} contratos")
    if st.button("Ver mais", key=f"cc_carteira_ver_mais_{source_key}"):
        st.session_state[qtd_visivel_key] = qtd_visivel + QTD_INCREMENTO_CARTEIRA
        st.rerun()
elif len(filtrado):
    st.caption(f"Mostrando todos os {len(filtrado)} contratos")
    if len(filtrado) > QTD_INICIAL_CARTEIRA and st.button("Ver menos", key=f"cc_carteira_ver_menos_{source_key}"):
        st.session_state[qtd_visivel_key] = QTD_INICIAL_CARTEIRA
        st.rerun()

st.caption(
    "Cadastro nativo de Contratos Contínuos (não depende mais de planilha) — uma linha por "
    "contrato × item de licitação. Saldo Execução vem da Execução Anual do projeto, cruzado "
    f"pela NE. Exercício em tela: {ano_selecionado}. Edição de cartão só é gravada ao clicar "
    "em '💾 Salvar'; '+ Novo contrato' e 'Remover' gravam/apagam de imediato."
)
