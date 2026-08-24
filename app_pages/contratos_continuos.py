"""Contratos Contínuos — necessidade de empenho e saldo, cruzado com a Execução Anual.

Adaptação do handoff de design (`painel_bolsas.py`, versão "cartão com rótulo pequeno acima
de cada campo" — mesmo padrão já aplicado em `app_pages/bolsas_auxilios.py`, replicado aqui
para Contratos Contínuos) para os leitores e a regra de saldo já aprovados e testados neste
projeto (`src/contratos_continuos.py`, `src/necessidade_empenho.py`,
`src/execucao_anual.py::saldo_por_ne`) — não `data_loader_contratos.py`/`design_tokens.py`
de handoffs anteriores.

Cada contrato × item de licitação é um cartão (`st.expander`, minimizado por padrão — mesmo
padrão de `app_pages/bolsas_auxilios.py`, aplicado aqui) com todos os campos editáveis inline
— sem rolagem horizontal, os campos quebram em linhas dentro do próprio cartão. Rótulo
pequeno (`.cc-label`, maiúsculo, discreto) acima de cada campo — nem rótulo nativo grande do
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
  * "Remover" oculta o cartão só nesta sessão (não apaga da planilha de origem).
  * "+ Novo contrato" é um `st.popover` compacto no canto superior direito, ao lado do
    título — não um `st.expander` de largura total abaixo dele (mesmo padrão de
    `bolsas_auxilios.py`). Grava em `st.session_state`, sem persistência entre sessões.
  * `_aplicar_edicoes_da_sessao` sobrepõe, no DataFrame usado pelos quadros acima da lista,
    os valores já editados em cada cartão e recalcula `despesa_anual`/`meses_a_empenhar`/
    `valor_a_empenhar` a partir deles — sem isso, editar um campo só mudava o que aparecia
    dentro do próprio cartão, nunca nos KPIs, no Resumo Consolidado nem na Cobertura
    Orçamentária (mesmo bug relatado e corrigido primeiro em `bolsas_auxilios.py`). Roda
    antes de `com_saldo_execucao`, pelo mesmo motivo de lá.
  * "Carteira de contratos" minimizada por padrão (pedido explícito) — só 3 cartões
    (`QTD_INICIAL_CARTEIRA`) de início, com "Ver mais" revelando o resto de uma vez, não em
    lotes como o padrão incremental de `app_pages/contratos_vigencia.py`
    (`QTD_INCREMENTO_LISTA`) — aqui o pedido foi "se eu quiser ver todos os outros, eu clico",
    um clique único para tudo. Mesmo padrão estendido ao "Resumo Consolidado" (pedido
    explícito em seguida): só as linhas visíveis (`QTD_INICIAL_RESUMO`) são limitadas — os
    totais do card (cabeçalho e rodapé) sempre somam o conjunto inteiro, nunca só o exibido.
  * Quadro "Empenhado × Liquidado" (pedido explícito) — mesmo layout HTML do Resumo
    Consolidado (`.cc-resumo-*`, mesma minimização "Ver mais"), comparando por NE o valor
    empenhado total contra o liquidado (`indice_liquidado_por_ne_curta`, novo em
    `src/execucao_anual.py`), abrangendo todos os contratos filtrados — inclusive os sem NE
    (aparecem com "sem NE" no lugar de liquidado/saldo). O saldo mostrado é o mesmo
    `saldo_execucao` (empenhada − liquidada) já usado no resto da página, só rotulado "Sobra"
    (≥ 0) ou "Insuficiência" (< 0, liquidado passou do empenhado) — não é uma conta nova.
"""

from __future__ import annotations

import html as html_lib
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src.contratos_continuos import com_meses_pagos, com_saldo_execucao, ler_contratos_continuos
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
from src.execucao_anual import agregar_por_ne, indice_liquidado_por_ne_curta, ler_execucao_anual, saldo_por_ne
from src.importacao_dotacao import Manifesto as ManifestoDotacao
from src.importacao_dotacao import ler_dotacao_anual
from src.importacao_execucao import Manifesto
from src.necessidade_empenho import calcular_necessidade_empenho
from src.ui_theme import format_brl_compact, render_metric_grid, render_page_header

DIRETORIO_DADOS_BRUTOS = Path("data/raw")
CAMINHO_PLANILHA = DIRETORIO_DADOS_BRUTOS / "SERVIÇOS CONTÍNUOS - 2026 - AGO A DEZ.xlsm"
CAMINHO_PAGAMENTOS = DIRETORIO_DADOS_BRUTOS / "CONTRATOS - CONTROLE 2020 - Pagamentos.xlsx"

COLUNAS_BUSCA = [
    "contrato_numero", "fornecedor", "tipo_despesa", "tipo_contrato", "acao_cod",
    "pi_cod", "unidade_cod", "processo_contratacao", "processo_empenho", "ne_curta",
]

STATUS_OPCOES = ["ATIVO", "VENCIDO"]


@st.cache_data(show_spinner="Lendo a planilha de Contratos Contínuos...")
def _cached_leitura(caminho: str, mtime: float) -> pd.DataFrame:
    """`mtime` só participa da chave de cache — força reler se o arquivo mudar."""

    return ler_contratos_continuos(caminho)


@st.cache_data(show_spinner="Lendo a base de Execução Anual...")
def _cached_por_ne_execucao(caminho: str, mtime: float) -> pd.DataFrame:
    return saldo_por_ne(agregar_por_ne(ler_execucao_anual(caminho)))


@st.cache_data(show_spinner="Lendo a planilha de Pagamentos de Contratos...")
def _cached_meses_pagos_por_contrato(caminho: str, mtime: float) -> pd.DataFrame:
    """Meses pagos + último mês pago por contrato (número normalizado), a partir da planilha
    de Pagamentos — complemento opcional (mesmo padrão de `_cached_dotacao_por_ptres`): sem
    ela, os campos ficam nulos e o resto da tela continua funcionando normal."""

    return meses_pagos_por_contrato(ler_pagamentos(caminho))


@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def _cached_dotacao_por_ptres(caminho: str, mtime: float) -> tuple[pd.DataFrame, int]:
    """Uma linha por PTRES do exercício mais recente da base (a base traz vários anos —
    misturar exercícios inflaria a dotação de cada PTRES): Ação, Plano Orçamentário e Dotação
    Atualizada. Mesmo padrão de `app_pages/bolsas_auxilios.py::_cached_dotacao_por_ptres`."""

    dados = ler_dotacao_anual(caminho).workbook.consolidated_data
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
           de planilha. */
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
        .cc-resumo-scroll {{ overflow-x: auto; padding-bottom: 2px; }}
        .cc-resumo-row, .cc-resumo-head-row, .cc-resumo-foot {{
            display: grid; grid-template-columns: minmax(200px,2fr) 120px 120px 150px;
            gap: 10px; min-width: 560px;
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


def _rotulo_expander(linha: pd.Series) -> str:
    """Prévia do cartão minimizado — a partir dos valores brutos da linha (não dos widgets,
    que só existem depois de abrir o expander)."""

    fornecedor = _ou_vazio(linha["fornecedor"]) or "(sem fornecedor)"
    numero = _ou_vazio(linha["contrato_numero"])
    meses_a_empenhar, valor_a_empenhar = calcular_necessidade_empenho(
        _ou_zero(linha["meses_empenhados"]), _ou_zero(linha["meses_liquidados"]), _ou_zero(linha["despesa_mensal"])
    )
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


def _render_card(linha: pd.Series, source_key: str, removidos: set) -> None:
    indice = linha.name
    if indice in removidos:
        return
    k = f"cc_{source_key}_{indice}"

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
        despesa_mensal = _campo_numero(r3[1], "Despesa Mensal (R$)", _ou_zero(linha["despesa_mensal"]), f"{k}_despmensal", step=100.0)
        valor_empenhado = _campo_numero(r3[2], "Empenhado (R$)", _ou_zero(linha["valor_empenhado"]), f"{k}_empenhado", step=100.0)
        saldo_planilha = _campo_numero(r3[3], "Saldo TG (R$)", _ou_zero(linha["saldo_colado_planilha"]), f"{k}_saldotg", step=100.0)

        r4 = st.columns(4)
        meses_empenhados = _campo_numero(r4[0], "Meses Empenhados", _ou_zero(linha["meses_empenhados"]), f"{k}_mesesemp", step=0.1)
        meses_liquidados = _campo_numero(r4[1], "Meses Liquidados", _ou_zero(linha["meses_liquidados"]), f"{k}_mesesliq", step=0.1)

        despesa_anual = despesa_mensal * 12
        meses_a_empenhar, valor_a_empenhar = calcular_necessidade_empenho(
            meses_empenhados, meses_liquidados, despesa_mensal
        )

        r4[2].markdown("<div class='cc-label'>Despesa Anual</div>", unsafe_allow_html=True)
        r4[2].markdown(f"<div class='cc-calc'>{_brl(despesa_anual)}</div>", unsafe_allow_html=True)
        r4[3].markdown("<div class='cc-label'>Meses de Saldo</div>", unsafe_allow_html=True)
        r4[3].markdown(f"<div class='cc-calc'>{_num(meses_a_empenhar)}</div>", unsafe_allow_html=True)

        r5 = st.columns(4)
        r5[0].markdown("<div class='cc-label'>Empenhar</div>", unsafe_allow_html=True)
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

        eh_ativo = status == "ATIVO"
        tag_status_txt, tag_status_cls = ("Ativo", "ok") if eh_ativo else ("Vencido", "bad")
        if pd.isna(saldo_execucao):
            tag_div_txt, tag_div_cls = "Sem Execução", "bad"
        elif diverge_saldo or diverge_valor_empenhado:
            tag_div_txt, tag_div_cls = "Diverge", "bad"
        else:
            tag_div_txt, tag_div_cls = "Bate", "ok"

        f1, f2 = st.columns([4, 1])
        f1.markdown(
            f"<span class='cc-tag {tag_status_cls}'>{tag_status_txt}</span>"
            f"<span class='cc-tag {tag_div_cls}'>{tag_div_txt}</span>",
            unsafe_allow_html=True,
        )
        if f2.button("Remover", key=f"{k}_remover", use_container_width=True, help="Ocultar nesta sessão"):
            removidos.add(indice)
            st.session_state[f"cc_removidos_{source_key}"] = removidos
            st.rerun()


def _render_novo_contrato(source_key: str) -> None:
    """"+ Novo contrato" — popover compacto no canto superior direito da tela (mesmo padrão
    de `bolsas_auxilios.py`), não um expander de largura total; só nesta sessão
    (`st.session_state`), sem persistência em disco."""

    extra_key = f"contratos_continuos_extra_{source_key}"
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
                    extras = st.session_state.get(extra_key, [])
                    extras.append(
                        {
                            "contrato_numero": numero, "ano_contrato": ano, "status_contrato": status,
                            "fornecedor": fornecedor, "fornecedor_cnpj_cpf": cnpj, "tipo_despesa": tipo_despesa,
                            "unidade_cod": unidade, "acao_cod": acao, "ptres": ptres,
                            "natureza_despesa_cod": nd, "ugr_cod": ugr, "pi_cod": pi,
                            "ne_curta": ne_curta.strip() or pd.NA, "despesa_mensal": despesa_mensal,
                            "valor_empenhado": valor_empenhado, "saldo_colado_planilha": saldo_colado,
                            "meses_empenhados": meses_empenhados, "meses_liquidados": meses_liquidados,
                        }
                    )
                    st.session_state[extra_key] = extras
                    st.rerun()


def _html_linha_resumo(principal: object, secundario: object, valor_empenhado: float, saldo: object, necessidade: float) -> str:
    saldo_texto = "sem NE" if pd.isna(saldo) else _brl(saldo)
    return (
        '<div class="cc-resumo-row">'
        f'<div><div class="cc-resumo-name">{_dash(principal)}</div><div class="cc-resumo-code">{_dash(secundario)}</div></div>'
        f'<span class="cc-resumo-val">{_brl(valor_empenhado)}</span>'
        f'<span class="cc-resumo-val">{saldo_texto}</span>'
        f'<span class="cc-resumo-val-strong">{_brl(necessidade)}</span>'
        "</div>"
    )


#: mesmo padrão de "Ver mais" de um clique só (não incremental) já usado na Carteira de
#: contratos abaixo — pedido explícito estendido para este card também.
QTD_INICIAL_RESUMO = 3


def _render_resumo_consolidado(filtrado: pd.DataFrame, meses_restantes: int, source_key: str) -> None:
    """Card único, visível de início (antes de abrir qualquer cartão), listando — uma linha
    por NE, não por item de licitação nem um total agregado — o valor empenhado, o saldo e a
    necessidade de empenho até dezembro. Diferente de `bolsas_auxilios.py` (1 linha == 1
    bolsa == 1 NE), aqui um contrato pode ter vários itens de licitação na mesma NE — agrupa-
    se por NE antes de listar, mesma unidade já usada por `_somar_unico_por_ne`/
    `_contar_unico_por_ne`, para não repetir a mesma NE várias vezes nem contar seu saldo mais
    de uma vez. Itens sem NE (contrato ainda sem empenho) aparecem à parte, um por linha, já
    que não há NE para agrupar.

    Minimizado por padrão (`QTD_INICIAL_RESUMO`, pedido explícito) — só as linhas visíveis
    (`linhas_html`) são limitadas por "Ver mais"; os totais do card (cabeçalho e rodapé) somam
    sempre o conjunto inteiro (`por_ne`/`sem_ne` completos), não só o que está à mostra."""

    com_ne = filtrado.dropna(subset=["ne_curta"])
    sem_ne = filtrado[filtrado["ne_curta"].isna()].copy()

    por_ne = com_ne.groupby("ne_curta", sort=False).agg(
        fornecedor=("fornecedor", "first"),
        contrato_numero=("contrato_numero", "first"),
        despesa_mensal=("despesa_mensal", "sum"),
        valor_empenhado_execucao=("valor_empenhado_execucao", "first"),
        valor_empenhado_planilha_total_ne=("valor_empenhado_planilha_total_ne", "first"),
        saldo_execucao=("saldo_execucao", "first"),
        saldo_colado_planilha=("saldo_colado_planilha", "first"),
    ).reset_index()
    por_ne["valor_empenhado_exibido"] = por_ne["valor_empenhado_execucao"].fillna(por_ne["valor_empenhado_planilha_total_ne"])
    saldo_por_ne_fallback = por_ne["saldo_execucao"].fillna(por_ne["saldo_colado_planilha"]).fillna(0.0)
    por_ne["necessidade"] = (por_ne["despesa_mensal"] * meses_restantes - saldo_por_ne_fallback).clip(lower=0)

    sem_ne["valor_empenhado_exibido"] = sem_ne["valor_empenhado"]
    sem_ne["necessidade"] = (sem_ne["despesa_mensal"] * meses_restantes).clip(lower=0)

    linhas = [
        (row["fornecedor"], row["contrato_numero"], row["valor_empenhado_exibido"], row["saldo_execucao"], row["necessidade"])
        for _, row in por_ne.sort_values("necessidade", ascending=False).iterrows()
    ] + [
        (row["fornecedor"], row["contrato_numero"], row["valor_empenhado_exibido"], pd.NA, row["necessidade"])
        for _, row in sem_ne.sort_values("necessidade", ascending=False).iterrows()
    ]

    necessidade_total = por_ne["necessidade"].sum() + sem_ne["necessidade"].sum()
    valor_empenhado_total = por_ne["valor_empenhado_exibido"].sum() + sem_ne["valor_empenhado_exibido"].sum()
    total_linhas = len(por_ne) + len(sem_ne)

    mostrar_todos_key = f"cc_resumo_mostrar_todos_{source_key}"
    mostrar_todos = st.session_state.get(mostrar_todos_key, False)
    visiveis = linhas if mostrar_todos else linhas[:QTD_INICIAL_RESUMO]
    linhas_html = "".join(_html_linha_resumo(*linha) for linha in visiveis)

    st.markdown(
        f"""
        <div class="cc-resumo-card">
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
          <div class="cc-resumo-scroll">
            <div class="cc-resumo-head-row">
              <span>Fornecedor / Contrato</span>
              <span style="text-align:right">Valor Empenhado</span>
              <span style="text-align:right">Saldo</span>
              <span style="text-align:right">Necessidade até Dez.</span>
            </div>
            {linhas_html}
            <div class="cc-resumo-foot">
              <span class="cc-resumo-foot-label">Total</span>
              <span class="cc-resumo-val">{_brl(valor_empenhado_total)}</span>
              <span class="cc-resumo-val">{_brl(_somar_unico_por_ne(filtrado, 'saldo_execucao'))}</span>
              <span class="cc-resumo-val-strong">{_brl(necessidade_total)}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not mostrar_todos and total_linhas > QTD_INICIAL_RESUMO:
        st.caption(f"Mostrando {QTD_INICIAL_RESUMO} de {total_linhas} linhas no resumo")
        if st.button("Ver mais", key=f"cc_resumo_ver_mais_{source_key}"):
            st.session_state[mostrar_todos_key] = True
            st.rerun()
    elif total_linhas:
        st.caption(f"Mostrando todas as {total_linhas} linhas no resumo")


def _html_linha_empenhado_liquidado(principal: object, secundario: object, empenhado: object, liquidado: object, saldo: object) -> str:
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
        "</div>"
    )


def _render_empenhado_liquidado(filtrado: pd.DataFrame, indice_liquidado: pd.Series, source_key: str) -> None:
    """Quadro comparando, por NE, o valor empenhado total contra o liquidado (pedido
    explícito) — mesmo layout do Resumo Consolidado acima (`.cc-resumo-*`), abrangendo TODOS
    os contratos filtrados, inclusive os sem NE (aparecem com "sem NE" no lugar de
    liquidado/saldo, já que não há NE para buscar na Execução Anual).

    O saldo é o mesmo `saldo_execucao` (empenhada − liquidada) já usado no resto da página —
    não uma conta nova —, só reapresentado aqui lado a lado com o valor liquidado e rotulado
    "Sobra" (saldo ≥ 0, ainda há espaço no empenho) ou "Insuficiência" (saldo < 0, liquidado
    passou do empenhado — precisa de reforço de empenho)."""

    com_ne = filtrado.dropna(subset=["ne_curta"])
    sem_ne = filtrado[filtrado["ne_curta"].isna()]

    por_ne = com_ne.groupby("ne_curta", sort=False).agg(
        fornecedor=("fornecedor", "first"),
        contrato_numero=("contrato_numero", "first"),
        valor_empenhado_execucao=("valor_empenhado_execucao", "first"),
        valor_empenhado_planilha_total_ne=("valor_empenhado_planilha_total_ne", "first"),
        saldo_execucao=("saldo_execucao", "first"),
    ).reset_index()
    por_ne["empenhado_exibido"] = por_ne["valor_empenhado_execucao"].fillna(por_ne["valor_empenhado_planilha_total_ne"])
    por_ne["liquidado"] = por_ne["ne_curta"].map(indice_liquidado)

    linhas = [
        (row["fornecedor"], row["contrato_numero"], row["empenhado_exibido"], row["liquidado"], row["saldo_execucao"])
        for _, row in por_ne.sort_values("saldo_execucao", na_position="last").iterrows()
    ] + [
        (row["fornecedor"], row["contrato_numero"], row["valor_empenhado"], pd.NA, pd.NA)
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
          <div class="cc-resumo-scroll">
            <div class="cc-resumo-head-row">
              <span>Fornecedor / Contrato</span>
              <span style="text-align:right">Empenhado</span>
              <span style="text-align:right">Liquidado</span>
              <span style="text-align:right">Saldo</span>
            </div>
            {linhas_html}
            <div class="cc-resumo-foot">
              <span class="cc-resumo-foot-label">Total</span>
              <span class="cc-resumo-val">{_brl(empenhado_total)}</span>
              <span class="cc-resumo-val">{_brl(liquidado_total)}</span>
              <span class="cc-resumo-val-strong" style="color:{cor_total}">{_brl(saldo_total)}</span>
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
    for indice in resultado.index:
        k = f"cc_{source_key}_{indice}"
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


def _com_contratos_extra(dataframe: pd.DataFrame, source_key: str) -> pd.DataFrame:
    extras = st.session_state.get(f"contratos_continuos_extra_{source_key}", [])
    if not extras:
        return dataframe
    novos = pd.DataFrame(extras)
    return pd.concat([dataframe, novos], ignore_index=True)


# ---------------------------------------------------------------------- página
# "+ Novo contrato" fica ao lado do título, não abaixo dele — por isso o cabeçalho precisa de
# um source_key (mtime do arquivo) antes de qualquer outra checagem: sem arquivo não há como
# calcular esse mtime, então o popover só aparece quando a planilha existe.
col_titulo, col_novo = st.columns([5, 1])
with col_titulo:
    render_page_header(
        "Contratos Contínuos",
        "Necessidade de reforço de empenho por contrato, cruzado com a Execução Anual.",
        "Contratos",
    )
_inject_css()

if CAMINHO_PLANILHA.exists():
    source_key = CAMINHO_PLANILHA.stat().st_mtime_ns.__str__()[-12:]
    with col_novo:
        st.write("")
        _render_novo_contrato(source_key)
else:
    st.info(
        f"A planilha de Contratos Contínuos não foi encontrada em '{CAMINHO_PLANILHA}'. "
        "Copie a extração atual para essa pasta antes de usar esta página."
    )
    st.stop()

manifesto_execucao = Manifesto.atual()
if manifesto_execucao is None:
    st.info(
        "Nenhuma base de Execução Anual foi importada ainda — é dela que vem o saldo "
        "autoritativo por NE. Importe a Execução Anual antes de usar esta página."
    )
    st.stop()

caminho_execucao = DIRETORIO_DADOS_BRUTOS / manifesto_execucao.arquivo
if not caminho_execucao.exists():
    st.error(f"O arquivo da extração atual de Execução Anual não foi encontrado em '{caminho_execucao}'.")
    st.stop()

try:
    dataframe = _cached_leitura(str(CAMINHO_PLANILHA), CAMINHO_PLANILHA.stat().st_mtime)
    por_ne_execucao = _cached_por_ne_execucao(str(caminho_execucao), caminho_execucao.stat().st_mtime)
except Exception as error:
    st.error(f"Não foi possível ler os dados: {error}")
    st.stop()

# Dotação Anual, para o quadro "Cobertura Orçamentária por PTRES" — diferente da Execução
# Anual (obrigatória acima), essa base é só um complemento: sem ela, o quadro não aparece,
# mas o resto da tela (cartões, resumo, saldo via Execução) continua funcionando normal.
dotacao_dimensoes = None
ano_exercicio_dotacao = None
manifesto_dotacao = ManifestoDotacao.atual()
if manifesto_dotacao is not None:
    caminho_dotacao = DIRETORIO_DADOS_BRUTOS / manifesto_dotacao.arquivo
    if caminho_dotacao.exists():
        try:
            dotacao_dimensoes, ano_exercicio_dotacao = _cached_dotacao_por_ptres(
                str(caminho_dotacao), caminho_dotacao.stat().st_mtime
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

dataframe = _com_contratos_extra(dataframe, source_key)
dataframe = _aplicar_edicoes_da_sessao(dataframe, source_key)
dataframe = com_saldo_execucao(dataframe, por_ne_execucao)
dataframe = com_meses_pagos(dataframe, meses_pagos_por_contrato_df)

busca = st.text_input(
    "Buscar",
    key=f"contratos_continuos_busca_{source_key}",
    placeholder="Contrato, fornecedor, tipo de despesa, ação, PI, NE…",
)
filtrado = _aplicar_busca(dataframe, busca)

removidos_key = f"cc_removidos_{source_key}"
removidos = st.session_state.get(removidos_key, set())
filtrado = filtrado[~filtrado.index.isin(removidos)]

if filtrado.empty:
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

_render_resumo_consolidado(filtrado, _meses_restantes_no_ano(), source_key)
_render_empenhado_liquidado(filtrado, indice_liquidado_por_ne_curta(por_ne_execucao), source_key)

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

# minimizada por padrão (pedido explícito) — só QTD_INICIAL_CARTEIRA (3) cartões de início,
# "Ver mais" revela o resto de uma vez (não em lotes, ao contrário do padrão incremental de
# app_pages/contratos_vigencia.py — aqui o pedido foi "se eu quiser ver todos os outros, eu
# clico", um único clique para tudo, não vários).
QTD_INICIAL_CARTEIRA = 3
mostrar_todos_key = f"cc_carteira_mostrar_todos_{source_key}"
mostrar_todos = st.session_state.get(mostrar_todos_key, False)
visiveis = filtrado if mostrar_todos else filtrado.iloc[:QTD_INICIAL_CARTEIRA]

with st.container(key="cc_lista"):
    for _, linha in visiveis.iterrows():
        _render_card(linha, source_key, removidos)

if not mostrar_todos and len(filtrado) > QTD_INICIAL_CARTEIRA:
    st.caption(f"Mostrando {QTD_INICIAL_CARTEIRA} de {len(filtrado)} contratos")
    if st.button("Ver mais", key=f"cc_carteira_ver_mais_{source_key}"):
        st.session_state[mostrar_todos_key] = True
        st.rerun()
elif len(filtrado):
    st.caption(f"Mostrando todos os {len(filtrado)} contratos")

st.caption(
    "Base de Contratos Contínuos consolidada manualmente (não é uma extração única e "
    "versionada como Dotação/Execução Anual) — uma linha por contrato × item de licitação. "
    "Saldo Execução vem da Execução Anual do projeto, cruzado pela NE. Edições e contratos "
    "adicionados por '+ Novo contrato' existem só nesta sessão."
)
