"""Bolsas e Auxílios — necessidade de empenho e saldo, cruzado com a Execução Anual.

Adaptação do handoff de design (`painel_bolsas.py`, versão "cartão com rótulo pequeno acima
de cada campo") para os leitores e a regra de saldo já aprovados e testados neste projeto
(`src/bolsas_auxilios.py`, `src/necessidade_empenho.py`,
`src/execucao_anual.py::saldo_por_ne`) — não os `data_loader_bolsas.py`/`design_tokens.py`
sugeridos no pacote de handoff.

Cada programa é um cartão (`st.expander`, minimizado por padrão — um cadastro para consultar
por cima e abrir só quando precisar editar) com todos os campos editáveis inline — sem
rolagem horizontal, os campos quebram em linhas dentro do próprio cartão. Rótulo pequeno
(`.bls-label`, maiúsculo, discreto) acima de cada campo — nem rótulo nativo grande do
Streamlit, nem campo sem rótulo nenhum: editável não é sinônimo de caixa grande, mas também
não fica sem indicação do que é.

`_aplicar_edicoes_da_sessao` sobrepõe, no DataFrame usado pelos quadros acima da lista, os
valores já editados em cada cartão (lidos de `st.session_state`, sem redesenhar widgets) e
recalcula `valor_mensal`/`valor_anual`/`meses_a_empenhar`/`valor_a_empenhar` a partir deles —
sem isso, editar um campo só mudava o que aparecia dentro do próprio cartão, nunca nos KPIs,
no Resumo Consolidado nem na Cobertura Orçamentária por PTRES (bug relatado explicitamente:
"Alterei uma informação no cadastro de bolsa e a alteração não foi refletida nos quadros
superiores"). Roda antes de `com_saldo_execucao`, para uma edição no campo NE também
atualizar `saldo_execucao`/`valor_empenhado_execucao` daquela linha, não só os campos que a
planilha já trazia prontos.

Antes da lista, um card único "Resumo Consolidado — por Bolsa" lista, uma linha por bolsa (não
um total agregado), o valor empenhado, o saldo (Execução Anual) e a necessidade de empenho até
o fim do exercício de cada programa — esta última É a métrica de calendário
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
  * Para processos cuja NE já foi encontrada na Execução Anual, `meses_empenhados`/
    `meses_liquidados` deixam de vir da planilha e passam a vir da própria Execução Anual
    (`com_saldo_execucao`, campos `meses_empenhados_execucao`/`meses_liquidados_execucao`) —
    pedido explícito do usuário para não depender de atualizar a planilha de Bolsas só para
    refletir um novo saldo/liquidado. Os dois campos do cartão viram exibição (rótulo
    "(Execução Anual)"), não mais editáveis, nesse caso. Sem NE encontrada, continuam
    editáveis como sempre, seedados pela planilha (fallback inalterado; mesmo critério de
    `contratos_continuos.py`).
  * `saldo_execucao` e `valor_empenhado_execucao` (autoritativos, vindos da Execução Anual)
    não existiam no handoff (foi desenhado antes dessa integração) — aparecem fixos (não
    editáveis) junto da tag de status, com divergência contra `saldo_colado_planilha`/
    `valor_empenhado_tg` sinalizada, não escondida. O "Valor Empenhado" do Resumo
    Consolidado usa `valor_empenhado_execucao`, com `valor_empenhado_tg` (planilha) como
    reserva só para NE sem correspondência na Execução — mesmo padrão de fallback do saldo.
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
    linha por bolsa (não um total único) e usa `valor_mensal × meses restantes até dezembro`
    para a "Necessidade até Dezembro" — a ÚNICA métrica de calendário desta página. Ela não
    substitui nem se confunde com "Empenhar" por cartão (que continua vindo de
    `meses_empenhados − meses_liquidados`, ver bullet acima): "Empenhar" mede atraso já
    ocorrido; "Necessidade até Dezembro" projeta o gasto restante do exercício.
  * Os tokens de cor/tipografia são os reais do projeto (`src/design_tokens.py`), não os do
    pacote de handoff.
  * KPIs no topo: Despesa Anual Total, Valor Mensal, Necessidade de Reforço, Programas e
    Saldo via Execução Anual — "Beneficiários Efetivos" saiu por pedido explícito (trocado
    por Despesa Anual Total, mesmo rótulo já usado em `contratos_continuos.py`). "Sem
    Empenho/Não Localizado" e "Saldo Divergente" também saíram do topo antes, por pedido
    explícito — continuam visíveis por cartão (tag vermelha "Sem Empenho"/"Não Localizado"/
    "Diverge"), só não aparecem mais como contagem agregada na entrada da tela.
  * "Remover" oculta o cartão só nesta sessão (não apaga da planilha de origem).
  * "+ Novo programa" é um `st.popover` compacto no canto superior direito, ao lado do
    título — não um `st.expander` de largura total abaixo dele. Grava em
    `st.session_state`, sem persistência entre sessões — mesma ressalva do README do
    handoff. Não tem nome/CPF de bolsista: a granularidade real da base é por programa, não
    por beneficiário (ver `src/bolsas_auxilios.py`).
"""

from __future__ import annotations

import html as html_lib
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from src.bolsas_auxilios import com_saldo_execucao, ler_bolsas_auxilios
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
from src.execucao_anual import agregar_por_ne, saldo_por_ne
from src.importacao_dotacao import Manifesto as ManifestoDotacao
from src.importacao_dotacao import NOME_PONTEIRO as NOME_PONTEIRO_DOTACAO
from src.importacao_dotacao import carregar_atual as carregar_dotacao_atual
from src.importacao_execucao import DIRETORIO_MANIFESTOS_PADRAO, Manifesto
from src.importacao_execucao import NOME_PONTEIRO as NOME_PONTEIRO_EXECUCAO
from src.importacao_execucao import carregar_atual as carregar_execucao_atual
from src.necessidade_empenho import calcular_necessidade_empenho
from src.relatorio_reforco_empenho import BOLSAS_AUXILIOS as RELATORIO_BOLSAS_AUXILIOS
from src.ui_relatorio_reforco_empenho import render_botao_relatorio
from src.ui_theme import format_brl_compact, render_metric_grid, render_page_header

DIRETORIO_DADOS_BRUTOS = Path("data/raw")
CAMINHO_PLANILHA = DIRETORIO_DADOS_BRUTOS / "BOLSAS E AUXÍLIOS 2026 - AGO A DEZ.xlsx"

COLUNAS_BUSCA = ["processo", "programa_bolsa", "unidade_cod", "acao_cod", "pi_cod", "ne_curta"]

SITUACAO_OPCOES = ["ATUALIZADO", "SEM EMPENHO", "NÃO LOCALIZADO"]


@st.cache_data(show_spinner="Lendo a planilha de Bolsas e Auxílios...")
def _cached_leitura(caminho: str, mtime: float) -> pd.DataFrame:
    """`mtime` só participa da chave de cache — força reler se o arquivo mudar."""

    return ler_bolsas_auxilios(caminho)


@st.cache_data(show_spinner="Lendo a base de Execução Anual...")
def _cached_por_ne_execucao(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    """`caminho_ponteiro`/`mtime_ponteiro` só participam da chave de cache — força reler
    quando o manifesto atual mudar. `carregar_atual` já devolve a base composta por ano (ver
    `src/importacao_execucao.py`)."""

    return saldo_por_ne(agregar_por_ne(carregar_execucao_atual()))


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


def _meses_restantes_no_ano(hoje: date | None = None) -> int:
    """Meses restantes até dezembro (inclusive o atual) — só para o Resumo Consolidado, não
    para a fórmula por cartão (ver docstring do módulo)."""

    hoje = hoje or date.today()
    return max(1, 12 - hoje.month + 1)


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
        /* Resumo Consolidado: mesmo padrão de cartão + grade HTML de app_pages/painel_acoes.py
           (.po-*), com prefixo próprio (.bls-resumo-*) — nao eh um st.dataframe: grade fixa,
           tipografia do projeto, sem cara de planilha (sem linhas zebradas nem grade do Excel). */
        .bls-resumo-card {{
            border: 1px solid {BORDER}; border-radius: {RADIUS};
            background: {SURFACE}; padding: {CARD_PAD}; margin-bottom: {SPACE['xl']};
        }}
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
        .bls-resumo-scroll {{ overflow-x: auto; padding-bottom: 2px; }}
        .bls-resumo-row, .bls-resumo-head-row, .bls-resumo-foot {{
            display: grid; grid-template-columns: minmax(200px,2fr) 120px 120px 150px;
            gap: 10px; min-width: 560px;
        }}
        .bls-resumo-head-row {{
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .bls-resumo-row {{
            padding: 9px 0; border-bottom: 1px solid {BORDER_SOFT}; align-items: baseline;
        }}
        .bls-resumo-foot {{ padding-top: 9px; font-family: {FONT_HEADING}; align-items: baseline; }}
        .bls-resumo-name {{ font-family: {FONT_BODY}; font-size: {SIZE['body']}; line-height: 1.25; color: {TEXT}; }}
        .bls-resumo-code {{
            font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: {TRACK['label']}; color: {TEXT_MUTED};
        }}
        .bls-resumo-val {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED};
        }}
        .bls-resumo-val-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
        }}
        .bls-resumo-foot-label {{
            font-size: {SIZE['label']}; letter-spacing: {TRACK['label']};
            text-transform: uppercase; color: {TEXT_MUTED};
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


def _rotulo_expander(linha: pd.Series) -> str:
    """Prévia do cartão minimizado — a partir dos valores brutos da linha (não dos widgets,
    que só existem depois de abrir o expander). `valor_a_empenhar` já vem resolvido pelo
    pipeline (Execução Anual quando disponível, planilha como fallback — ver
    `com_saldo_execucao`); recalcular aqui a partir de `meses_empenhados`/`meses_liquidados`
    mostraria um número desatualizado sempre que a Execução Anual estiver disponível."""

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


def _render_card(linha: pd.Series, source_key: str, removidos: set) -> None:
    indice = linha.name
    if indice in removidos:
        return
    k = f"bls_{source_key}_{indice}"

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
        valor_empenhado = _campo_numero(r3[3], "Empenhado (R$)", _ou_zero(linha["valor_empenhado_tg"]), f"{k}_valorempenhado", step=100.0)

        r4 = st.columns(4)
        # Mesmo critério de `app_pages/contratos_continuos.py::_render_card`: com NE já
        # encontrada na Execução Anual, os campos manuais viram exibição (ver
        # `com_saldo_execucao`), não editáveis — digitar ali deixaria de ter efeito no
        # "Empenhar" mostrado, e reintroduziria o bug de dois quadros com números diferentes.
        via_execucao = pd.notna(linha["meses_empenhados_execucao"])
        if via_execucao:
            meses_empenhados = float(linha["meses_empenhados_execucao"])
            meses_liquidados = float(linha["meses_liquidados_execucao"])
            r4[0].markdown("<div class='bls-label'>Meses Empenhados (Execução Anual)</div>", unsafe_allow_html=True)
            r4[0].markdown(f"<div class='bls-calc'>{_num(meses_empenhados)}</div>", unsafe_allow_html=True)
            r4[1].markdown("<div class='bls-label'>Meses Liquidados (Execução Anual)</div>", unsafe_allow_html=True)
            r4[1].markdown(f"<div class='bls-calc'>{_num(meses_liquidados)}</div>", unsafe_allow_html=True)
        else:
            meses_empenhados = _campo_numero(r4[0], "Meses Empenhados", _ou_zero(linha["meses_empenhados"]), f"{k}_mesesemp", step=0.1)
            meses_liquidados = _campo_numero(r4[1], "Meses Liquidados", _ou_zero(linha["meses_liquidados"]), f"{k}_mesesliq", step=0.1)
        saldo_planilha = _campo_numero(r4[2], "Saldo (R$)", _ou_zero(linha["saldo_colado_planilha"]), f"{k}_saldo", step=100.0)

        valor_mensal = qtd_efetiva * valor_unitario
        meses_a_empenhar, valor_a_empenhar = calcular_necessidade_empenho(
            meses_empenhados, meses_liquidados, valor_mensal
        )

        r4[3].markdown("<div class='bls-label'>Valor Mensal</div>", unsafe_allow_html=True)
        r4[3].markdown(f"<div class='bls-calc'>{_brl(valor_mensal)}</div>", unsafe_allow_html=True)

        r5 = st.columns(4)
        r5[0].markdown("<div class='bls-label'>Meses de Saldo</div>", unsafe_allow_html=True)
        r5[0].markdown(f"<div class='bls-calc'>{_num(meses_a_empenhar)}</div>", unsafe_allow_html=True)
        rotulo_empenhar = "Empenhar (Execução Anual)" if via_execucao else "Empenhar (planilha)"
        r5[1].markdown(f"<div class='bls-label'>{rotulo_empenhar}</div>", unsafe_allow_html=True)
        r5[1].markdown(f"<div class='bls-calc strong'>{_brl(valor_a_empenhar)}</div>", unsafe_allow_html=True)

        saldo_execucao = linha["saldo_execucao"]
        diverge_saldo = pd.notna(saldo_execucao) and abs(saldo_execucao - saldo_planilha) > 0.01
        r5[2].markdown("<div class='bls-label'>Saldo (Execução Anual)</div>", unsafe_allow_html=True)
        r5[2].markdown(f"<div class='bls-calc'>{_brl(saldo_execucao) if pd.notna(saldo_execucao) else 'sem NE'}</div>", unsafe_allow_html=True)

        valor_empenhado_execucao = linha["valor_empenhado_execucao"]
        diverge_valor_empenhado = pd.notna(valor_empenhado_execucao) and abs(valor_empenhado_execucao - valor_empenhado) > 0.01
        r5[3].markdown("<div class='bls-label'>Empenhado (Execução Anual)</div>", unsafe_allow_html=True)
        r5[3].markdown(f"<div class='bls-calc'>{_brl(valor_empenhado_execucao) if pd.notna(valor_empenhado_execucao) else 'sem NE'}</div>", unsafe_allow_html=True)

        if situacao == "SEM EMPENHO":
            tag_txt, tag_cls = "Sem Empenho", "bad"
        elif situacao == "NÃO LOCALIZADO":
            tag_txt, tag_cls = "Não Localizado", "bad"
        elif valor_a_empenhar > 0:
            tag_txt, tag_cls = "Necessita Reforço", "warn"
        else:
            tag_txt, tag_cls = "Atualizado", "ok"
        if pd.isna(saldo_execucao):
            tag_div_txt, tag_div_cls = "Sem Execução", "warn"
        elif diverge_saldo or diverge_valor_empenhado:
            tag_div_txt, tag_div_cls = "Diverge", "bad"
        else:
            tag_div_txt, tag_div_cls = "Bate", "ok"

        f1, f2 = st.columns([4, 1])
        f1.markdown(
            f"<span class='bls-tag {tag_cls}'>{tag_txt}</span>"
            f"<span class='bls-tag {tag_div_cls}'>{tag_div_txt}</span>",
            unsafe_allow_html=True,
        )
        if f2.button("Remover", key=f"{k}_remover", use_container_width=True):
            removidos.add(indice)
            st.session_state[f"bl_removidos_{source_key}"] = removidos
            st.rerun()


def _render_novo_programa(source_key: str) -> None:
    """"+ Novo programa" — popover compacto no canto superior direito da tela (não um
    expander de largura total), só nesta sessão (`st.session_state`), sem persistência em
    disco; mesma ressalva do README do handoff."""

    extra_key = f"bolsas_auxilios_extra_{source_key}"
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
                    extras = st.session_state.get(extra_key, [])
                    extras.append(
                        {
                            "processo": processo or "—", "programa_bolsa": programa, "unidade_cod": unidade,
                            "acao_cod": acao, "ptres": ptres, "fonte_cod": fonte, "natureza_despesa_cod": nd,
                            "ugr_cod": ugr, "pi_cod": pi, "ne_curta": ne_curta.strip() or pd.NA,
                            "meses_no_ano": meses_no_ano, "qtd_inicial": qtd_inicial, "qtd_efetiva": qtd_efetiva,
                            "valor_unitario": valor_unitario, "valor_empenhado_tg": valor_empenhado,
                            "saldo_colado_planilha": saldo_colado, "situacao_tg": "SEM EMPENHO",
                            "meses_empenhados": meses_empenhados, "meses_liquidados": meses_liquidados,
                        }
                    )
                    st.session_state[extra_key] = extras
                    st.rerun()


def _html_linha_resumo(programa: object, processo: object, valor_empenhado: float, saldo: object, necessidade: float) -> str:
    saldo_texto = "sem NE" if pd.isna(saldo) else _brl(saldo)
    return (
        '<div class="bls-resumo-row">'
        f'<div><div class="bls-resumo-name">{_dash(programa)}</div><div class="bls-resumo-code">{_dash(processo)}</div></div>'
        f'<span class="bls-resumo-val">{_brl(valor_empenhado)}</span>'
        f'<span class="bls-resumo-val">{saldo_texto}</span>'
        f'<span class="bls-resumo-val-strong">{_brl(necessidade)}</span>'
        "</div>"
    )


def _render_resumo_consolidado(filtrado: pd.DataFrame, meses_restantes: int) -> None:
    """Card único, visível de início (antes de abrir qualquer cartão), listando — uma linha por
    bolsa, não agregado num único total — o valor empenhado, o saldo e a necessidade de
    empenho até dezembro de cada programa. Mesmo padrão de cartão + grade HTML de
    `app_pages/painel_acoes.py`, não `st.dataframe` (que tem cara de planilha)."""

    valor_mensal = (filtrado["qtd_efetiva"] * filtrado["valor_unitario"]).fillna(0.0)
    necessidade_ate_dezembro = valor_mensal * meses_restantes
    saldo_por_linha = filtrado["saldo_execucao"].fillna(filtrado["saldo_colado_planilha"]).fillna(0.0)
    empenhar_ate_fim = (necessidade_ate_dezembro - saldo_por_linha).clip(lower=0)
    # valor empenhado autoritativo (Execução Anual), com o valor colado na planilha como
    # reserva só para NE sem correspondência lá — mesmo padrão de fallback do saldo.
    valor_empenhado_exibido = filtrado["valor_empenhado_execucao"].fillna(filtrado["valor_empenhado_tg"])

    ordenado = filtrado.assign(_necessidade=empenhar_ate_fim, _valor_empenhado=valor_empenhado_exibido).sort_values(
        "_necessidade", ascending=False
    )
    linhas_html = "".join(
        _html_linha_resumo(
            row["programa_bolsa"], row["processo"], row["_valor_empenhado"], row["saldo_execucao"], row["_necessidade"]
        )
        for _, row in ordenado.iterrows()
    )

    necessidade_total = empenhar_ate_fim.sum()

    st.markdown(
        f"""
        <div class="bls-resumo-card">
          <div class="bls-resumo-head">
            <div style="min-width:0">
              <div class="bls-resumo-kicker">RESUMO CONSOLIDADO</div>
              <div class="bls-resumo-title">Necessidade de Empenho por Bolsa</div>
            </div>
            <div style="text-align:right">
              <div class="bls-resumo-metric-label">Necessidade até Dezembro ({meses_restantes}m)</div>
              <div class="bls-resumo-metric">{_brl(necessidade_total)}</div>
              <div class="bls-resumo-metric-label" style="margin-top:4px">
                {len(filtrado)} {"bolsa" if len(filtrado) == 1 else "bolsas"}
              </div>
            </div>
          </div>
          <div class="bls-resumo-scroll">
            <div class="bls-resumo-head-row">
              <span>Bolsa / Programa</span>
              <span style="text-align:right">Valor Empenhado</span>
              <span style="text-align:right">Saldo</span>
              <span style="text-align:right">Necessidade até Dez.</span>
            </div>
            {linhas_html}
            <div class="bls-resumo-foot">
              <span class="bls-resumo-foot-label">Total</span>
              <span class="bls-resumo-val">{_brl(valor_empenhado_exibido.sum())}</span>
              <span class="bls-resumo-val">{_brl(_somar_unico_por_ne(filtrado, 'saldo_execucao'))}</span>
              <span class="bls-resumo-val-strong">{_brl(necessidade_total)}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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


def _com_programas_extra(dataframe: pd.DataFrame, source_key: str) -> pd.DataFrame:
    extras = st.session_state.get(f"bolsas_auxilios_extra_{source_key}", [])
    if not extras:
        return dataframe
    novos = pd.DataFrame(extras)
    return pd.concat([dataframe, novos], ignore_index=True)


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
    for indice in resultado.index:
        k = f"bls_{source_key}_{indice}"
        for sufixo, coluna in _CAMPOS_EDITAVEIS_NUMERICOS.items():
            valor = st.session_state.get(f"{k}_{sufixo}")
            if valor is not None:
                resultado.at[indice, coluna] = valor
        for sufixo, coluna in _CAMPOS_EDITAVEIS_TEXTO.items():
            valor = st.session_state.get(f"{k}_{sufixo}")
            if valor is not None:
                resultado.at[indice, coluna] = valor if valor != "" else pd.NA
        situacao = st.session_state.get(f"{k}_situacao")
        if situacao is not None:
            resultado.at[indice, "situacao_tg"] = situacao

    # mesmas fórmulas usadas dentro do cartão (`_render_card`) e na leitura original
    # (`ler_bolsas_auxilios`) — reaproveitadas aqui, não reimplementadas, para os totais
    # acima da lista nunca divergirem do que cada cartão mostra.
    resultado["valor_mensal"] = resultado["qtd_efetiva"] * resultado["valor_unitario"]
    resultado["valor_anual"] = resultado["valor_mensal"] * resultado["meses_no_ano"]
    resultado["meses_a_empenhar"], resultado["valor_a_empenhar"] = calcular_necessidade_empenho(
        resultado["meses_empenhados"], resultado["meses_liquidados"], resultado["valor_mensal"]
    )
    return resultado


# ---------------------------------------------------------------------- página
# "+ Novo programa" fica ao lado do título, não abaixo dele — por isso o cabeçalho precisa
# de um source_key (mtime do arquivo) antes de qualquer outra checagem: sem arquivo não há
# como calcular esse mtime, então o popover só aparece quando a planilha existe.
col_titulo, col_relatorio, col_novo = st.columns([4, 1.4, 1])
with col_titulo:
    render_page_header(
        "Bolsas e Auxílios",
        "Necessidade de reforço de empenho por programa de bolsa/auxílio, cruzado com a Execução Anual.",
        "Bolsas",
    )
_inject_css()

if CAMINHO_PLANILHA.exists():
    source_key = CAMINHO_PLANILHA.stat().st_mtime_ns.__str__()[-12:]
    with col_novo:
        st.write("")
        _render_novo_programa(source_key)
else:
    st.info(
        f"A planilha de Bolsas e Auxílios não foi encontrada em '{CAMINHO_PLANILHA}'. "
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

caminho_ponteiro_execucao = DIRETORIO_MANIFESTOS_PADRAO / NOME_PONTEIRO_EXECUCAO

try:
    dataframe = _cached_leitura(str(CAMINHO_PLANILHA), CAMINHO_PLANILHA.stat().st_mtime)
    por_ne_execucao = _cached_por_ne_execucao(
        str(caminho_ponteiro_execucao), caminho_ponteiro_execucao.stat().st_mtime
    )
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
    caminho_ponteiro_dotacao = DIRETORIO_MANIFESTOS_PADRAO / NOME_PONTEIRO_DOTACAO
    try:
        dotacao_dimensoes, ano_exercicio_dotacao = _cached_dotacao_por_ptres(
            str(caminho_ponteiro_dotacao), caminho_ponteiro_dotacao.stat().st_mtime
        )
    except Exception:
        dotacao_dimensoes = None

dataframe = _com_programas_extra(dataframe, source_key)
dataframe = _aplicar_edicoes_da_sessao(dataframe, source_key)
dataframe = com_saldo_execucao(dataframe, por_ne_execucao)

with col_relatorio:
    st.write("")
    render_botao_relatorio(dataframe, RELATORIO_BOLSAS_AUXILIOS, "bolsas")

busca = st.text_input(
    "Buscar",
    key=f"bolsas_auxilios_busca_{source_key}",
    placeholder="Processo, programa, unidade, ação, PI, NE…",
)
filtrado = _aplicar_busca(dataframe, busca)

removidos_key = f"bl_removidos_{source_key}"
removidos = st.session_state.get(removidos_key, set())
filtrado = filtrado[~filtrado.index.isin(removidos)]

if filtrado.empty:
    st.warning("Nenhum registro corresponde à busca informada.")
    st.stop()

render_metric_grid(
    [
        {"label": "Despesa Anual Total", "value": format_brl_compact(filtrado["valor_anual"].sum())},
        {"label": "Valor Mensal", "value": format_brl_compact((filtrado["qtd_efetiva"] * filtrado["valor_unitario"]).sum())},
        {"label": "Necessidade de Reforço", "value": format_brl_compact(filtrado["valor_a_empenhar"].sum())},
        {"label": "Programas", "value": str(len(filtrado))},
        {"label": "Saldo (Execução Anual)", "value": format_brl_compact(_somar_unico_por_ne(filtrado, "saldo_execucao"))},
    ],
    columns=5,
)

_render_resumo_consolidado(filtrado, _meses_restantes_no_ano())

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
        _render_card(linha, source_key, removidos)

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
    "Base de Bolsas e Auxílios consolidada manualmente (não é uma extração única e "
    "versionada como Dotação/Execução Anual) — uma linha por programa de bolsa/auxílio, não "
    "por bolsista individual (a planilha não traz nome/CPF de beneficiário). Saldo Execução "
    "vem da Execução Anual do projeto, cruzado pela NE. Edições e programas adicionados por "
    "'+ Novo programa' existem só nesta sessão."
)
