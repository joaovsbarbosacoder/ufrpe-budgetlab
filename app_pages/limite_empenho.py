"""Limite de Empenho — cota orçamentária discricionária liberada por período.

Pedido explícito do usuário (22/09/2026): reproduzir a planilha que a PROPLAD extrai
periodicamente ("COTA <ano> - Discricionário - Saldo disponível a empenhar") — mesmas 4
colunas de valor (Dotação Atualizada, Despesas Empenhadas, Limite liberado, Saldo disponível
a empenhar), mesma fórmula (Limite = Dotação × fração; Saldo = Limite − Empenhado), calculada
ao vivo a partir de Dotação Anual + Execução Mensal já importadas — não uma reimportação
periódica daquele arquivo (decisão do usuário). Regra completa, incluindo o porquê do escopo
"Discricionário" (exclui pessoal e emendas, só Fonte de Recursos "000") e como a Fonte
Detalhada da Dotação (10 dígitos) equivale à Fonte curta da Execução (3 dígitos) — dígito
inicial = indicador de exercício, os 3 seguintes = o próprio código curto —, ver
`src/limite_empenho.py`.

A fração liberada (ex. "9/12") NUNCA é calculada a partir do calendário — é um número que a
PROPLAD comunica por fora do sistema; por isso é sempre um campo editável nesta página, com o
último valor usado preservado na sessão.

Ajustes pedidos pelo usuário em 22/09/2026, após a primeira versão:
  * Sem seletor de exercício — sempre o corrente (ano da extração do manifesto de Dotação
    Anual, mesma convenção de `app_pages/painel_acoes.py`). Olhar exercício passado não faz
    sentido para uma cota liberada, que só existe para o ano em andamento.
  * O universo de Ação/PTRES precisa ser o mesmo de "Painel por Ação" (só Dotação) — por isso
    `saldo_disponivel_a_empenhar` agora ancora o cruzamento em Dotação (não mais um outer
    join); uma combinação só presente na Execução não aparece mais aqui.
  * BUG CORRIGIDO (relatado com prints pelo usuário): mesmo ancorado em Dotação, ainda
    apareciam combinações "fantasma" — dimensões que só tinham dado em outro ano, sem
    nenhum dos 4 indicadores (inicial/suplementar/atualizada/cancelada) preenchido no ano
    pedido. Corrigido reaproveitando `build_dotacao_anual_subdivision_analysis` +
    `has_any_indicator`, o mesmo filtro que "Painel por Ação" já usa — ver
    `src/limite_empenho.py`.

REDESENHO VISUAL (pedido explícito do usuário, 22/09/2026, a partir de um mockup enviado por
imagem — "Painel orçamentário"): cartões de KPI com % de referência, painel de barras "Limite
por ação" (Empenhado vs. Disponível), painel "Saldo por grupo de despesa", cartão "Pontos de
atenção" com os piores saldos negativos, e tabela "Detalhamento por PTRES" com selo de
Situação, ordenada do menor saldo para o maior. Só a CAMADA DE APRESENTAÇÃO mudou — nenhuma
coluna, filtro de escopo ou regra de agregação de `src/limite_empenho.py` foi alterada; os
filtros de Resultado Primário/Ação/GND desta página operam sobre o `DataFrame` já calculado
por `saldo_disponivel_a_empenhar`, sem reabrir o cruzamento Dotação×Execução.

Decisões tomadas para adaptar o mockup sem violar as regras permanentes do projeto (nunca
descartar dado financeiro silenciosamente):
  * O mockup mostra "8 de 32 registros" na tabela — isso sugeriria truncar a lista. Em vez
    disso, a tabela mostra TODOS os registros do recorte. Primeira versão usava um cartão com
    altura fixa e rolagem interna; pedido explícito do usuário (22/09/2026) trocou isso por
    exibição completa, sem corte — a rolagem passa a ser a da própria página, não de uma caixa
    interna (`overflow: visible` em `.le-table-scroll`, cabeçalho de colunas não fica mais
    "grudado" no topo por seção, já que não há mais caixa com rolagem própria para grudar).
  * O painel de barras por ação agrupa as ações menores num item "Outras (N ações)" — é só
    uma agregação de apresentação (a soma bate com o total, nada é somado fora da tabela
    detalhada abaixo), mesmo princípio já usado no filtro `has_any_indicator`.
  * O filtro "Fonte" do mockup é fixo em "000 — Recursos Livres da União" (não um seletor
    real): o escopo Discricionário desta ferramenta já restringe TODA a base a essa única
    fonte (ver `src/limite_empenho.py`), então um seletor com outras opções seria enganoso.
  * A situação "Saldo baixo" (selo amarelo) é uma HEURÍSTICA DE EXIBIÇÃO, não uma regra de
    negócio confirmada com o usuário — ver `_LIMIAR_SALDO_BAIXO_PCT` abaixo. Sinalizado aqui
    porque o AGENTS.md pede para não presumir regra orçamentária sem confirmação; o limiar é
    fácil de ajustar (ou remover) quando o usuário validar o valor certo.

AGRUPAMENTO POR IDUSO/AÇÃO na tabela "Detalhamento por PTRES" (pedido explícito do usuário,
22/09/2026, com duas perguntas de confirmação respondidas antes de implementar):
  * Confirmado com dados reais: as 29 linhas atuais se dividem só entre IDUSO 0 e IDUSO 8 —
    ações desses dois grupos têm um limite GLOBAL que pode ser compartilhado entre elas. A
    tabela agora agrupa por IDUSO (com um resumo "Limite/Saldo compartilhado" = soma de todo
    o grupo) e, dentro de cada IDUSO, por Ação — escolha do usuário: "resumo do grupo +
    detalhe individual" (não a opção que recalcularia a Situação de cada PTRES pelo saldo do
    grupo). Isso não muda NENHUM valor calculado por `src/limite_empenho.py`: o "Limite
    compartilhado"/"Saldo compartilhado" do resumo é matematicamente a soma dos valores
    individuais já mostrados nas linhas (a fórmula linha-a-linha é linear na fração), só
    reapresentado como total do grupo — Situação de cada PTRES continua vindo do saldo
    daquele PTRES, sem alteração.
  * "Eliminar a exibição de RP1" (Resultado Primário = 1, "PRIMARIO OBRIGATORIO") — o usuário
    escolheu excluí-lo de TODA a ferramenta (KPIs, gráficos, tabela), não só desta tabela, já
    que incluir despesa obrigatória numa ferramenta "Discricionária" era inconsistente com o
    próprio escopo dela. Implementado em `src/limite_empenho.py` (mesmo tratamento já dado a
    emendas parlamentares, RP=6), não nesta página — ver `RESULTADO_PRIMARIO_OBRIGATORIO`
    naquele módulo.

PERSISTÊNCIA DA FRAÇÃO EM DISCO (pedido explícito do usuário, 22/09/2026, após reportar "ao
atualizar a página, ele volta pra o 12"): `st.session_state` sozinho só sobrevive DENTRO de uma
sessão do navegador — um F5 cria uma sessão nova, então a fração sempre voltava ao padrão
12/12. O usuário aprovou explicitamente persistir em arquivo (AGENTS.md exige essa aprovação
antes de qualquer persistência) — ver `src/limite_empenho_preferencias.py`. A fração agora é
lida do disco na primeira renderização da sessão (não a cada rerun) e regravada só quando o
valor efetivamente muda, para não gerar I/O a cada interação não relacionada na página (trocar
um filtro, por exemplo).

FAIXA DOS CAMPOS DE FRAÇÃO (pedido explícito do usuário, 22/09/2026): os campos numerador e
denominador não têm mais `min_value`/`max_value` fixos em 1-12 — aquela faixa era uma suposição
nossa (o exemplo "9/12" da planilha de referência), não uma regra confirmada com a PROPLAD. O
único valor bloqueado é denominador = 0 (indefinido matematicamente — `Fraction` lançaria
`ZeroDivisionError`), com aviso explícito em vez de deixar a página quebrar.

REMANEJAMENTO ENTRE IDUSOs (pedido explícito do usuário, 28/09/2026): saldo de limite de um
IDUSO pode ser remanejado temporariamente para outro, e desfeito quando o usuário quiser. Regra
e persistência em `src/limite_empenho_remanejamentos.py` (gravação em disco aprovada pelo
usuário). Nesta página o ajuste aparece só no resumo de cada IDUSO da tabela "Detalhamento por
PTRES" (limite/saldo ajustados + original lado a lado); linhas de PTRES, Situação, KPIs e
gráficos continuam com os valores calculados — o total geral não muda, porque remanejamento é
soma zero. Escolha do usuário: com qualquer filtro ativo o ajuste NÃO é aplicado (o resumo
passaria a mostrar só parte do grupo), e a página avisa que há remanejamentos em vigor.
"""

from __future__ import annotations

import html as html_lib
from datetime import datetime
from decimal import Decimal
from fractions import Fraction

import pandas as pd
import streamlit as st

from src import design_tokens as dt
from src.importacao_dotacao import DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_DOTACAO
from src.importacao_dotacao import Manifesto as ManifestoDotacao
from src.importacao_dotacao import NOME_PONTEIRO as PONTEIRO_DOTACAO
from src.importacao_dotacao import carregar_atual as carregar_dotacao_atual
from src.importacao_execucao_mensal import DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_EXECUCAO_MENSAL
from src.importacao_execucao_mensal import Manifesto as ManifestoExecucaoMensal
from src.importacao_execucao_mensal import NOME_PONTEIRO as PONTEIRO_EXECUCAO_MENSAL
from src.importacao_execucao_mensal import carregar_atual as carregar_execucao_mensal_atual
from src.limite_empenho import saldo_disponivel_a_empenhar
from src.limite_empenho_preferencias import carregar_fracao_liberada, salvar_fracao_liberada
from src.limite_empenho_remanejamentos import (
    Remanejamento,
    RemanejamentoInvalido,
    carregar_remanejamentos,
    desfazer_remanejamento,
    limite_por_iduso_com_remanejamentos,
    registrar_remanejamento,
    remanejamentos_ativos,
)
from src.ui_theme import format_brl_compact, format_brl_full, render_metric_grid, render_page_header

#: heurística de EXIBIÇÃO (não regra de negócio confirmada, ver docstring do módulo): abaixo
#: desta fração do limite liberado, um saldo ainda positivo aparece como "Saldo baixo" em vez
#: de "Disponível". Ajuste livremente até o usuário confirmar o valor certo.
_LIMIAR_SALDO_BAIXO_PCT = 0.10

#: quantos exemplos aparecem no cartão "Pontos de atenção" — a lista completa está sempre na
#: tabela "Detalhamento por PTRES" logo abaixo (nenhum registro fica só nesta prévia).
_MAX_EXEMPLOS_ATENCAO = 5

#: quantas ações aparecem nomeadas no painel de barras; o restante entra em "Outras" (só
#: agregação de apresentação — ver docstring do módulo).
_MAX_ACOES_BARRAS = 6

_TEXTO_FONTE_FIXA = "000 — Recursos Livres da União"


@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def _cached_dotacao(caminho_ponteiro: str, sha_manifesto: str) -> pd.DataFrame:
    return carregar_dotacao_atual()


@st.cache_data(show_spinner="Lendo a base de Execução Mensal...")
def _cached_execucao_mensal(caminho_ponteiro: str, sha_manifesto: str) -> pd.DataFrame:
    return carregar_execucao_mensal_atual()


# --------------------------------------------------------------- formatação
def _esc(value: object) -> str:
    return html_lib.escape("" if value is None or pd.isna(value) else str(value))


def _fmt_pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:.1f}".replace(".", ",") + "%"


def _pct_of(numerator: object, denominator: object) -> str:
    if pd.isna(numerator) or pd.isna(denominator) or not denominator:
        return "—"
    return _fmt_pct(float(numerator) / float(denominator) * 100)


# ------------------------------------------------------------------- estilos
def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .le-filter-row {{ margin-bottom: {dt.SPACE['sm']}; }}
        .le-legend {{ display: flex; gap: {dt.SPACE['lg']}; margin: -0.3rem 0 {dt.SPACE['md']}; }}
        .le-legend-item {{
            display: inline-flex; align-items: center; gap: 6px;
            font-size: {dt.SIZE['small']}; color: {dt.TEXT_MUTED};
        }}
        .le-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
        .le-bar-list {{ display: flex; flex-direction: column; gap: {dt.SPACE['md']}; }}
        .le-bar-row {{
            display: grid; grid-template-columns: minmax(120px, 1fr) 220px 92px;
            gap: {dt.SPACE['md']}; align-items: center;
        }}
        .le-bar-cod {{ font-family: {dt.FONT_HEADING}; font-weight: 700; font-size: {dt.SIZE['value']}; color: {dt.TEXT}; }}
        .le-bar-desc {{
            font-size: {dt.SIZE['small']}; color: {dt.TEXT_MUTED}; white-space: nowrap;
            overflow: hidden; text-overflow: ellipsis;
        }}
        .le-bar-track {{
            position: relative; width: 220px; height: 10px; border-radius: 999px;
            background: {dt.BORDER_SOFT}; overflow: hidden;
        }}
        .le-bar-fill {{ position: absolute; top: 0; left: 0; height: 100%; display: flex; }}
        .le-bar-fill-empenhado {{ height: 100%; background: {dt.POSITIVE}; }}
        .le-bar-fill-disponivel {{ height: 100%; background: {dt.BORDER}; }}
        .le-bar-valor {{
            text-align: right; font-variant-numeric: tabular-nums; font-size: {dt.SIZE['value']};
            color: {dt.TEXT}; white-space: nowrap;
        }}
        .le-gnd-row {{ margin-bottom: {dt.SPACE['md']}; }}
        .le-gnd-row:last-child {{ margin-bottom: 0; }}
        .le-gnd-head {{ display: flex; justify-content: space-between; gap: {dt.SPACE['sm']}; margin-bottom: 4px; }}
        .le-gnd-label {{ font-size: {dt.SIZE['small']}; color: {dt.TEXT}; font-weight: 600; }}
        .le-gnd-valor {{ font-size: {dt.SIZE['small']}; color: {dt.TEXT}; font-variant-numeric: tabular-nums; white-space: nowrap; }}
        .le-gnd-track {{
            width: 100%; height: 8px; border-radius: 999px; background: {dt.BORDER_SOFT}; overflow: hidden;
        }}
        .le-gnd-fill {{ height: 100%; background: {dt.POSITIVE}; border-radius: 999px; }}
        .le-gnd-pct {{ margin-top: 3px; font-size: {dt.SIZE['micro']}; color: {dt.TEXT_MUTED}; }}
        .le-attention-banner {{
            background: {dt.NEGATIVE_SOFT}; border-radius: {dt.RADIUS_SM}; padding: 10px 12px;
            font-size: {dt.SIZE['body']}; color: {dt.NEGATIVE}; margin-bottom: {dt.SPACE['md']};
        }}
        .le-attention-count {{ font-weight: 800; font-size: {dt.SIZE['value_strong']}; }}
        .le-attention-total {{ font-weight: 700; }}
        .le-attention-ok {{ font-size: {dt.SIZE['small']}; color: {dt.TEXT_MUTED}; }}
        .le-attention-item {{ padding: 8px 0; border-top: 1px solid {dt.BORDER_SOFT}; }}
        .le-attention-item:first-of-type {{ border-top: 0; }}
        .le-attention-item-head {{ display: flex; justify-content: space-between; gap: {dt.SPACE['sm']}; }}
        .le-attention-ptres {{ font-weight: 700; font-size: {dt.SIZE['small']}; color: {dt.TEXT}; }}
        .le-attention-valor {{ font-weight: 700; font-size: {dt.SIZE['small']}; color: {dt.NEGATIVE}; white-space: nowrap; }}
        .le-attention-desc {{ margin-top: 2px; font-size: {dt.SIZE['micro']}; color: {dt.TEXT_MUTED}; }}
        .le-badge {{
            display: inline-block; padding: 2px 10px; border-radius: 999px;
            font-size: {dt.SIZE['micro']}; font-weight: 750; letter-spacing: 0.02em; white-space: nowrap;
        }}
        .le-badge-exceeded {{ color: {dt.NEGATIVE}; background: {dt.NEGATIVE_SOFT}; }}
        .le-badge-low {{ color: {dt.WARNING}; background: {dt.WARNING_SOFT}; }}
        .le-badge-ok {{ color: {dt.POSITIVE}; background: {dt.POSITIVE_SOFT}; }}
        .le-badge-null {{ color: {dt.TEXT_MUTED}; background: {dt.SURFACE_ALT}; }}
        .le-table-scroll {{ overflow: visible; }}
        .le-iduso-section {{ margin-bottom: {dt.SPACE['xl']}; }}
        .le-iduso-section:last-child {{ margin-bottom: 0; }}
        .le-iduso-head {{
            background: {dt.ACCENT_SOFT}; border-radius: {dt.RADIUS_SM}; padding: 10px 14px;
            margin-bottom: {dt.SPACE['sm']}; display: flex; flex-wrap: wrap;
            justify-content: space-between; align-items: center; gap: {dt.SPACE['md']};
        }}
        .le-iduso-title {{ font-family: {dt.FONT_HEADING}; font-weight: 700; color: {dt.TEXT}; font-size: {dt.SIZE['value_strong']}; }}
        .le-iduso-stats {{ display: flex; gap: {dt.SPACE['lg']}; flex-wrap: wrap; font-size: {dt.SIZE['small']}; color: {dt.TEXT_MUTED}; }}
        .le-iduso-stats strong {{ color: {dt.TEXT}; font-weight: 700; }}
        .le-acao-section {{ margin: 4px 0 {dt.SPACE['md']}; }}
        .le-acao-head {{
            display: flex; justify-content: space-between; gap: {dt.SPACE['sm']};
            padding: 6px 2px; border-bottom: 1px dashed {dt.BORDER}; margin-bottom: 4px;
        }}
        .le-acao-title {{ font-weight: 700; font-size: {dt.SIZE['small']}; color: {dt.ACCENT_STRONG}; }}
        .le-acao-subtotal {{ font-size: {dt.SIZE['micro']}; color: {dt.TEXT_MUTED}; white-space: nowrap; }}
        .le-table-head, .le-table-row {{
            display: grid;
            grid-template-columns: minmax(70px, 0.6fr) minmax(200px, 1.8fr) 46px
                minmax(140px, 1fr) minmax(140px, 1fr) minmax(140px, 1fr) minmax(140px, 1fr)
                minmax(120px, 0.95fr);
            gap: {dt.SPACE['sm']}; align-items: center;
        }}
        .le-table-head {{
            background: {dt.SURFACE};
            padding-bottom: {dt.SPACE['xs']}; border-bottom: 1px solid {dt.BORDER};
            font-family: {dt.FONT_HEADING}; font-size: {dt.SIZE['micro']};
            letter-spacing: 0.08em; text-transform: uppercase; color: {dt.TEXT_MUTED};
        }}
        .le-table-row {{ padding: 9px 0; border-bottom: 1px solid {dt.BORDER_SOFT}; }}
        .le-table-ptres {{ font-family: {dt.FONT_HEADING}; font-weight: 700; color: {dt.TEXT}; }}
        .le-table-po {{ font-size: {dt.SIZE['small']}; color: {dt.TEXT}; overflow-wrap: anywhere; }}
        .le-table-po-cod {{ color: {dt.TEXT_MUTED}; }}
        .le-table-val {{ text-align: right; font-variant-numeric: tabular-nums; font-size: {dt.SIZE['small']}; color: {dt.TEXT}; white-space: nowrap; }}
        .le-negativo {{ color: {dt.NEGATIVE}; font-weight: 700; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# -------------------------------------------------------------------- filtros
def _opcoes(dataframe: pd.DataFrame, coluna_cod: str, coluna_desc: str) -> dict[str, object]:
    pares = dataframe[[coluna_cod, coluna_desc]].drop_duplicates()
    pares = pares.sort_values(coluna_cod, na_position="last", kind="stable")
    opcoes: dict[str, object] = {}
    for cod, desc in pares.itertuples(index=False):
        if pd.isna(cod):
            continue
        label = str(cod) if pd.isna(desc) or str(desc) == str(cod) else f"{cod} — {desc}"
        opcoes[label] = cod
    return opcoes


def _render_filtros(resultado: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Devolve o recorte filtrado e se há algum filtro ativo (remanejamentos entre IDUSOs só
    são aplicados ao resumo do grupo sem filtro — ver docstring do módulo)."""

    opcoes_rp = _opcoes(resultado, "resultado_primario_cod", "resultado_primario_desc")
    opcoes_acao = _opcoes(resultado, "acao_cod", "acao_desc")
    opcoes_gnd = _opcoes(resultado, "gnd_cod", "gnd_desc")

    col_rp, col_acao, col_gnd, col_fonte, col_limpar = st.columns([1.1, 1.4, 1.1, 1, 0.8])
    with col_rp:
        rotulo_rp = st.selectbox("Resultado Primário", ["Todos"] + list(opcoes_rp), key="le_filtro_rp")
    with col_acao:
        rotulo_acao = st.selectbox("Ação de Governo", ["Todas"] + list(opcoes_acao), key="le_filtro_acao")
    with col_gnd:
        rotulo_gnd = st.selectbox("Grupo de Despesa", ["Todos"] + list(opcoes_gnd), key="le_filtro_gnd")
    with col_fonte:
        st.selectbox(
            "Fonte", [_TEXTO_FONTE_FIXA], key="le_filtro_fonte_fixa", disabled=True,
            help='Escopo fixo desta ferramenta ("Discricionário"): todo o recorte já é só '
            'Fonte de Recursos "000" — Recursos Livres da União. Não é um filtro real porque '
            "não haveria outra opção para escolher (ver docstring de src/limite_empenho.py).",
        )
    with col_limpar:
        st.markdown("<div style='height: 1.7rem'></div>", unsafe_allow_html=True)
        if st.button("Limpar filtros", key="le_limpar_filtros", width="stretch"):
            for chave in ("le_filtro_rp", "le_filtro_acao", "le_filtro_gnd"):
                st.session_state.pop(chave, None)
            st.rerun()

    filtrado = resultado
    if rotulo_rp != "Todos":
        filtrado = filtrado[filtrado["resultado_primario_cod"] == opcoes_rp[rotulo_rp]]
    if rotulo_acao != "Todas":
        filtrado = filtrado[filtrado["acao_cod"] == opcoes_acao[rotulo_acao]]
    if rotulo_gnd != "Todos":
        filtrado = filtrado[filtrado["gnd_cod"] == opcoes_gnd[rotulo_gnd]]
    filtro_ativo = (rotulo_rp, rotulo_acao, rotulo_gnd) != ("Todos", "Todas", "Todos")
    return filtrado, filtro_ativo


# --------------------------------------------------------- painel: por ação
def _render_barras_acao(filtrado: pd.DataFrame, numerador: int, denominador: int) -> None:
    st.markdown(f"##### Limite {numerador}/{denominador} por ação")
    st.caption("Composição entre valores empenhados e saldo disponível")
    st.markdown(
        '<div class="le-legend">'
        f'<span class="le-legend-item"><span class="le-dot" style="background:{dt.POSITIVE}"></span>Empenhado</span>'
        f'<span class="le-legend-item"><span class="le-dot" style="background:{dt.BORDER}"></span>Disponível</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    agrupado = (
        filtrado.groupby(["acao_cod", "acao_desc"], dropna=False, sort=False)[
            ["limite_liberado", "empenhada", "saldo_disponivel"]
        ]
        .sum(min_count=1)
        .reset_index()
    )
    for coluna in ("limite_liberado", "empenhada", "saldo_disponivel"):
        agrupado[coluna] = agrupado[coluna].fillna(0.0)
    agrupado = agrupado.sort_values("limite_liberado", ascending=False, kind="stable")

    principais = agrupado.head(_MAX_ACOES_BARRAS)
    restante = agrupado.iloc[_MAX_ACOES_BARRAS:]

    registros = [
        {
            "rotulo": row["acao_cod"],
            "descricao": row["acao_desc"] if pd.notna(row["acao_desc"]) else "",
            "limite": float(row["limite_liberado"]),
            "empenhado": float(row["empenhada"]),
        }
        for _, row in principais.iterrows()
    ]
    if not restante.empty:
        registros.append(
            {
                "rotulo": "Outras",
                "descricao": f"{len(restante)} ações",
                "limite": float(restante["limite_liberado"].sum()),
                "empenhado": float(restante["empenhada"].sum()),
            }
        )

    maximo = max((registro["limite"] for registro in registros), default=0.0) or 1.0
    linhas_html = []
    for registro in registros:
        escala_pct = max(min(registro["limite"] / maximo * 100, 100.0), 2.0)
        if registro["limite"] > 0:
            empenhado_pct = max(min(registro["empenhado"] / registro["limite"] * 100, 100.0), 0.0)
        else:
            empenhado_pct = 100.0 if registro["empenhado"] > 0 else 0.0
        disponivel_pct = max(100.0 - empenhado_pct, 0.0)
        linhas_html.append(
            f'<div class="le-bar-row">'
            f'<div><div class="le-bar-cod">{_esc(registro["rotulo"])}</div>'
            f'<div class="le-bar-desc" title="{_esc(registro["descricao"])}">{_esc(registro["descricao"])}</div></div>'
            f'<div class="le-bar-track"><div class="le-bar-fill" style="width:{escala_pct:.1f}%">'
            f'<div class="le-bar-fill-empenhado" style="width:{empenhado_pct:.1f}%"></div>'
            f'<div class="le-bar-fill-disponivel" style="width:{disponivel_pct:.1f}%"></div>'
            f"</div></div>"
            f'<div class="le-bar-valor">{format_brl_compact(registro["limite"])}</div>'
            f"</div>"
        )
    st.markdown(f'<div class="le-bar-list">{"".join(linhas_html)}</div>', unsafe_allow_html=True)


# -------------------------------------------------------- painel: saldo GND
def _render_saldo_gnd(filtrado: pd.DataFrame) -> None:
    st.markdown("##### Saldo por grupo de despesa")
    st.caption("Participação no saldo filtrado (grupos com saldo positivo)")

    agrupado = (
        filtrado.groupby(["gnd_cod", "gnd_desc"], dropna=False, sort=False)["saldo_disponivel"]
        .sum(min_count=1)
        .reset_index()
    )
    agrupado["saldo_disponivel"] = agrupado["saldo_disponivel"].fillna(0.0)
    positivos = agrupado[agrupado["saldo_disponivel"] > 0].sort_values("saldo_disponivel", ascending=False)
    if positivos.empty:
        st.caption("Nenhum grupo de despesa com saldo positivo no recorte atual.")
        return

    total_positivo = float(positivos["saldo_disponivel"].sum())
    linhas_html = []
    for _, row in positivos.iterrows():
        pct = (float(row["saldo_disponivel"]) / total_positivo * 100) if total_positivo else 0.0
        descricao = row["gnd_desc"] if pd.notna(row["gnd_desc"]) else ""
        linhas_html.append(
            '<div class="le-gnd-row">'
            '<div class="le-gnd-head">'
            f'<span class="le-gnd-label">GND {_esc(row["gnd_cod"])} · {_esc(descricao)}</span>'
            f'<span class="le-gnd-valor">{format_brl_compact(row["saldo_disponivel"])}</span>'
            "</div>"
            f'<div class="le-gnd-track"><div class="le-gnd-fill" style="width:{pct:.1f}%"></div></div>'
            f'<div class="le-gnd-pct">{_fmt_pct(pct)} do saldo positivo</div>'
            "</div>"
        )
    st.markdown("".join(linhas_html), unsafe_allow_html=True)


# ------------------------------------------------- painel: pontos de atenção
def _render_pontos_atencao(filtrado: pd.DataFrame, numerador: int, denominador: int) -> None:
    st.markdown("##### Pontos de atenção")
    st.caption(f"Registros que ultrapassaram o limite {numerador}/{denominador}")

    negativos = filtrado[filtrado["saldo_disponivel"] < 0].sort_values("saldo_disponivel", kind="stable")
    if negativos.empty:
        st.markdown(
            '<div class="le-attention-ok">Nenhum registro ultrapassou o limite no recorte atual.</div>',
            unsafe_allow_html=True,
        )
        return

    total_negativo = float(negativos["saldo_disponivel"].sum())
    st.markdown(
        '<div class="le-attention-banner">'
        f'<span class="le-attention-count">{len(negativos)}</span> registro(s) negativo(s) · '
        f'<span class="le-attention-total">{format_brl_compact(total_negativo)}</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    exemplos_html = []
    for _, row in negativos.head(_MAX_EXEMPLOS_ATENCAO).iterrows():
        descricao = row["acao_desc"] if pd.notna(row["acao_desc"]) else ""
        exemplos_html.append(
            '<div class="le-attention-item">'
            '<div class="le-attention-item-head">'
            f'<span class="le-attention-ptres">{_esc(row["ptres"])} · {_esc(row["acao_cod"])}</span>'
            f'<span class="le-attention-valor">{format_brl_compact(row["saldo_disponivel"])}</span>'
            "</div>"
            f'<div class="le-attention-desc">{_esc(descricao)} — fonte {_TEXTO_FONTE_FIXA}</div>'
            "</div>"
        )
    st.markdown("".join(exemplos_html), unsafe_allow_html=True)

    if len(negativos) > _MAX_EXEMPLOS_ATENCAO:
        st.caption(
            f"+ {len(negativos) - _MAX_EXEMPLOS_ATENCAO} registro(s) negativo(s) — lista "
            "completa, com todos os campos, na tabela abaixo."
        )


# ------------------------------------------------ tabela: detalhamento PTRES
def _situacao(row: pd.Series) -> tuple[str, str]:
    if pd.isna(row["dotacao_atualizada"]):
        return "Sem Dotação", "le-badge-null"
    saldo = row["saldo_disponivel"]
    if pd.isna(saldo) or saldo < 0:
        return "Limite excedido", "le-badge-exceeded"
    limite = row["limite_liberado"]
    if pd.notna(limite) and limite > 0 and (saldo / limite) < _LIMIAR_SALDO_BAIXO_PCT:
        return "Saldo baixo", "le-badge-low"
    return "Disponível", "le-badge-ok"


def _html_linha_ptres(row: pd.Series) -> str:
    texto_situacao, classe_situacao = _situacao(row)
    po_desc = row["po_desc"] if pd.notna(row["po_desc"]) else ""
    saldo_negativo = pd.notna(row["saldo_disponivel"]) and row["saldo_disponivel"] < 0
    return (
        '<div class="le-table-row">'
        f'<span class="le-table-ptres">{_esc(row["ptres"])}</span>'
        f'<span class="le-table-po"><span class="le-table-po-cod">{_esc(row["po_cod"])}</span> — {_esc(po_desc)}</span>'
        f'<span>{_esc(row["gnd_cod"])}</span>'
        f'<span class="le-table-val">{format_brl_full(row["dotacao_atualizada"])}</span>'
        f'<span class="le-table-val">{format_brl_full(row["empenhada"])}</span>'
        f'<span class="le-table-val">{format_brl_full(row["limite_liberado"])}</span>'
        f'<span class="le-table-val{" le-negativo" if saldo_negativo else ""}">{format_brl_full(row["saldo_disponivel"])}</span>'
        f'<span><span class="le-badge {classe_situacao}">{texto_situacao}</span></span>'
        "</div>"
    )


def _html_bloco_acao(acao_cod: object, acao_desc: object, dados_acao: pd.DataFrame) -> str:
    totais = dados_acao[["limite_liberado", "saldo_disponivel"]].sum()
    descricao = acao_desc if pd.notna(acao_desc) else ""
    saldo_negativo = pd.notna(totais["saldo_disponivel"]) and totais["saldo_disponivel"] < 0
    cabecalho_acao = (
        '<div class="le-acao-head">'
        f'<span class="le-acao-title">{_esc(acao_cod)} — {_esc(descricao)}</span>'
        f'<span class="le-acao-subtotal">Limite {format_brl_full(totais["limite_liberado"])} · '
        f'Saldo <span class="{"le-negativo" if saldo_negativo else ""}">{format_brl_full(totais["saldo_disponivel"])}</span></span>'
        "</div>"
    )
    ordenado = dados_acao.sort_values("saldo_disponivel", ascending=True, na_position="last", kind="stable")
    linhas = "".join(_html_linha_ptres(row) for _, row in ordenado.iterrows())
    return f'<div class="le-acao-section">{cabecalho_acao}{linhas}</div>'


def _html_bloco_iduso(
    iduso_cod: object,
    iduso_desc: object,
    dados_iduso: pd.DataFrame,
    cabecalho_colunas: str,
    ajuste: pd.Series | None = None,
) -> str:
    """`ajuste` é a linha deste IDUSO em `limite_por_iduso_com_remanejamentos` — só passada
    quando não há filtro ativo e há remanejamento líquido diferente de zero."""

    totais = dados_iduso[["dotacao_atualizada", "empenhada", "limite_liberado", "saldo_disponivel"]].sum()
    descricao = iduso_desc if pd.notna(iduso_desc) else ""
    limite_exibido, saldo_exibido = totais["limite_liberado"], totais["saldo_disponivel"]
    detalhe_remanejamento = ""
    if ajuste is not None:
        limite_exibido, saldo_exibido = ajuste["limite_ajustado"], ajuste["saldo_ajustado"]
        remanejado = float(ajuste["remanejado_liquido"])
        sinal = "+" if remanejado > 0 else "−"
        detalhe_remanejamento = (
            f'<span>Remanejado <strong>{sinal}{format_brl_full(abs(remanejado))}</strong> '
            f'(limite original {format_brl_full(totais["limite_liberado"])} · saldo original '
            f'{format_brl_full(totais["saldo_disponivel"])})</span>'
        )
    saldo_negativo = pd.notna(saldo_exibido) and saldo_exibido < 0
    rotulo_ajustado = " ajustado" if ajuste is not None else ""
    resumo = (
        '<div class="le-iduso-head">'
        f'<div class="le-iduso-title">IDUSO {_esc(iduso_cod)} — {_esc(descricao)}</div>'
        '<div class="le-iduso-stats">'
        f'<span>Dotação <strong>{format_brl_full(totais["dotacao_atualizada"])}</strong></span>'
        f'<span>Empenhado <strong>{format_brl_full(totais["empenhada"])}</strong></span>'
        f'<span>Limite compartilhado{rotulo_ajustado} <strong>{format_brl_full(limite_exibido)}</strong></span>'
        f'<span>Saldo compartilhado{rotulo_ajustado} <strong class="{"le-negativo" if saldo_negativo else ""}">{format_brl_full(saldo_exibido)}</strong></span>'
        f"{detalhe_remanejamento}"
        "</div></div>"
    )

    totais_por_acao = (
        dados_iduso.groupby(["acao_cod", "acao_desc"], dropna=False, sort=False)["limite_liberado"]
        .sum(min_count=1)
        .fillna(0.0)
        .sort_values(ascending=False)
    )
    blocos_acao = "".join(
        _html_bloco_acao(acao_cod, acao_desc, dados_iduso[dados_iduso["acao_cod"] == acao_cod])
        for acao_cod, acao_desc in totais_por_acao.index
    )
    return f'<div class="le-iduso-section">{resumo}{cabecalho_colunas}{blocos_acao}</div>'


def _render_tabela_ptres(filtrado: pd.DataFrame, ajustes_iduso: pd.DataFrame | None = None) -> None:
    """`ajustes_iduso`: saída de `limite_por_iduso_com_remanejamentos` indexada por
    `iduso_cod`, ou `None` quando os remanejamentos não se aplicam ao recorte (filtro ativo)."""

    st.markdown("##### Detalhamento por PTRES")
    st.caption(
        "Agrupado por IDUSO (limite compartilhado entre as ações do grupo) e por Ação · "
        f"dentro de cada ação, prioridade para menores saldos disponíveis · "
        f"{len(filtrado)} registro(s) no recorte"
    )

    cabecalho_colunas = (
        '<div class="le-table-head">'
        "<span>PTRES</span><span>Plano Orçamentário</span><span>GND</span>"
        '<span style="text-align:right">Dotação</span><span style="text-align:right">Empenhado</span>'
        '<span style="text-align:right">Limite</span><span style="text-align:right">Saldo</span>'
        "<span>Situação</span></div>"
    )

    totais_por_iduso = (
        filtrado.groupby(["iduso_cod", "iduso_desc"], dropna=False, sort=False)["limite_liberado"]
        .sum(min_count=1)
        .fillna(0.0)
        .sort_values(ascending=False)
    )
    def _ajuste(iduso_cod: object) -> pd.Series | None:
        if ajustes_iduso is None or pd.isna(iduso_cod) or str(iduso_cod) not in ajustes_iduso.index:
            return None
        linha = ajustes_iduso.loc[str(iduso_cod)]
        return linha if float(linha["remanejado_liquido"]) != 0 else None

    blocos_iduso = "".join(
        _html_bloco_iduso(
            iduso_cod, iduso_desc, filtrado[filtrado["iduso_cod"] == iduso_cod], cabecalho_colunas,
            _ajuste(iduso_cod),
        )
        for iduso_cod, iduso_desc in totais_por_iduso.index
    )
    st.markdown(f'<div class="le-table-scroll">{blocos_iduso}</div>', unsafe_allow_html=True)


# ------------------------------------------ painel: remanejamento entre IDUSOs
def _rotulo_iduso(iduso_cod: str, descricoes: dict[str, str]) -> str:
    descricao = descricoes.get(iduso_cod)
    return f"IDUSO {iduso_cod} — {descricao}" if descricao else f"IDUSO {iduso_cod}"


def _render_remanejamentos(
    resultado: pd.DataFrame, ano: int, ativos: list[Remanejamento], ajustes_iduso: pd.DataFrame
) -> None:
    st.markdown("##### Remanejamento de limite entre IDUSOs")
    st.caption(
        "Move saldo de limite de um IDUSO para outro, temporariamente. Muda só o limite "
        "compartilhado do grupo — o limite de cada ação/PTRES continua o calculado. Fica salvo "
        "em disco até ser desfeito."
    )

    descricoes = {
        str(cod): (str(desc) if pd.notna(desc) else "")
        for cod, desc in resultado[["iduso_cod", "iduso_desc"]].drop_duplicates().itertuples(index=False)
        if pd.notna(cod)
    }
    idusos = sorted(descricoes)

    if len(idusos) < 2:
        st.caption("É preciso haver ao menos dois IDUSOs no escopo para remanejar limite.")
    else:
        with st.form("le_form_remanejamento", clear_on_submit=True):
            col_origem, col_destino, col_valor = st.columns([1.4, 1.4, 1])
            with col_origem:
                origem = st.selectbox("De (origem)", idusos, format_func=lambda c: _rotulo_iduso(c, descricoes))
            with col_destino:
                destino = st.selectbox(
                    "Para (destino)", idusos, index=1, format_func=lambda c: _rotulo_iduso(c, descricoes)
                )
            with col_valor:
                valor = st.number_input("Valor (R$)", min_value=0.0, value=0.0, step=1000.0, format="%.2f")
            observacao = st.text_input("Observação (opcional)")
            enviado = st.form_submit_button("Registrar remanejamento")
        if enviado:
            try:
                registrar_remanejamento(ano, origem, destino, Decimal(f"{valor:.2f}"), observacao)
            except RemanejamentoInvalido as error:
                st.error(str(error))
            else:
                st.rerun()

    for _, linha in ajustes_iduso.iterrows():
        if float(linha["remanejado_liquido"]) < 0 and pd.notna(linha["saldo_ajustado"]) and linha["saldo_ajustado"] < 0:
            st.warning(
                f"IDUSO {linha['iduso_cod']} cedeu mais limite do que tinha de saldo — saldo "
                f"compartilhado ajustado: {format_brl_full(linha['saldo_ajustado'])}."
            )

    if not ativos:
        st.caption(f"Nenhum remanejamento em vigor para {ano}.")
        return
    st.markdown("###### Em vigor")
    for item in ativos:
        col_texto, col_botao = st.columns([5, 1])
        with col_texto:
            observacao = f" — {item.observacao}" if item.observacao else ""
            st.markdown(
                f"**{format_brl_full(float(item.valor))}** de "
                f"{_rotulo_iduso(item.iduso_origem, descricoes)} → "
                f"{_rotulo_iduso(item.iduso_destino, descricoes)}{observacao}  \n"
                f"<span style='color:{dt.TEXT_MUTED}; font-size:{dt.SIZE['micro']}'>"
                f"registrado em {_esc(item.criado_em[:16].replace('T', ' '))} UTC</span>",
                unsafe_allow_html=True,
            )
        with col_botao:
            if st.button("Desfazer", key=f"le_desfazer_{item.id}", width="stretch"):
                try:
                    desfazer_remanejamento(item.id)
                except RemanejamentoInvalido as error:
                    st.error(str(error))
                else:
                    st.rerun()


# ---------------------------------------------------------------------- página
render_page_header(
    "Limite de Empenho",
    "Cota orçamentária discricionária liberada por período — Dotação Atualizada × fração "
    "liberada, comparada ao Empenhado.",
    "Planejamento",
)

manifesto_dotacao = ManifestoDotacao.atual()
manifesto_execucao_mensal = ManifestoExecucaoMensal.atual()
if manifesto_dotacao is None or manifesto_execucao_mensal is None:
    st.info(
        "Esta página precisa da Dotação Anual e da Execução Mensal já importadas (menu "
        '"Atualizar Planilhas"). Falta: '
        + ", ".join(
            nome for nome, ok in (
                ("Dotação Anual", manifesto_dotacao is not None),
                ("Execução Mensal", manifesto_execucao_mensal is not None),
            )
            if not ok
        )
        + "."
    )
    st.stop()

caminho_ponteiro_dotacao = DIR_MANIFESTOS_DOTACAO / PONTEIRO_DOTACAO
caminho_ponteiro_execucao_mensal = DIR_MANIFESTOS_EXECUCAO_MENSAL / PONTEIRO_EXECUCAO_MENSAL
try:
    dotacao = _cached_dotacao(str(caminho_ponteiro_dotacao), manifesto_dotacao.sha256)
    execucao_mensal = _cached_execucao_mensal(str(caminho_ponteiro_execucao_mensal), manifesto_execucao_mensal.sha256)
except Exception as error:
    st.error(f"Não foi possível ler as bases necessárias: {error}")
    st.stop()

ano = datetime.fromisoformat(manifesto_dotacao.data_extracao).year
if ano not in set(execucao_mensal["ano"].dropna().unique().tolist()):
    st.warning(
        f"A Execução Mensal não tem nenhum dado para {ano} — Despesas Empenhadas vai "
        "aparecer como R$ 0,00 em toda a tabela, não porque nada foi empenhado, mas porque "
        "esse exercício ainda não está nessa base."
    )

_inject_css()

col_titulo, col_exercicio = st.columns([4, 1])
with col_titulo:
    st.caption(
        f"Exercício {ano} (corrente, conforme a extração da Dotação Anual) — cota liberada "
        "só existe para o exercício em andamento, não há seleção de anos passados."
    )
with col_exercicio:
    st.markdown(
        f'<div style="text-align:right"><span class="le-badge le-badge-ok">Exercício {ano}</span></div>',
        unsafe_allow_html=True,
    )

# Lida do disco só na primeira renderização desta sessão (não a cada rerun) — depois disso
# `st.session_state`, via `key=`, é quem manda, exatamente como no resto da página. Isso é o
# que faz a fração sobreviver a um F5 (que cria uma sessão nova, sem essas chaves ainda): sem
# isso no session_state, os widgets abaixo cairiam no padrão 12/12 outra vez.
if "limite_empenho_numerador" not in st.session_state:
    fracao_salva_em_disco = carregar_fracao_liberada()
    st.session_state["limite_empenho_numerador"] = fracao_salva_em_disco[0] if fracao_salva_em_disco else 12
    st.session_state["limite_empenho_denominador"] = fracao_salva_em_disco[1] if fracao_salva_em_disco else 12
    st.session_state["_limite_empenho_fracao_gravada"] = fracao_salva_em_disco

col_num, col_den = st.columns([1, 1])
with col_num:
    # `value=` NÃO é passado de propósito: com `key=` sozinho, o Streamlit já persiste o
    # valor em `st.session_state["limite_empenho_numerador"]` sozinho, usando `value` só na
    # primeira renderização (quando a chave ainda não existe — e aqui ela já foi semeada
    # acima, a partir do disco). Passar `value=st.session_state.get(chave, 12)` JUNTO com
    # `key=` (bug relatado pelo usuário, 22/09/2026: "o campo não guarda o dado após
    # atualização") faz o Streamlit reavaliar `value` a cada rerun a partir do próprio
    # session_state — se outro widget da página disparar um rerun antes do número digitado
    # ser "confirmado" (Enter/Tab), o valor em edição podia ser sobrescrito de volta pelo
    # `value` reavaliado. Mesmo padrão corrigido abaixo, no denominador. Um `value=12` fixo
    # também não é passado: com a chave já semeada via session_state, o Streamlit registra o
    # aviso "created with a default value but also had its value set via the Session State
    # API" a cada abertura da página (28/09/2026). Sem `value`, `step=1` mantém o tipo inteiro.
    numerador = st.number_input(
        # Sem min_value/max_value de propósito (pedido explícito do usuário, 22/09/2026): a
        # PROPLAD não está necessariamente presa a uma escala "de 1 a 12" — o limite antigo de
        # 1-12 era uma suposição nossa, não uma regra confirmada. O único valor que quebraria a
        # conta (denominador = 0) é bloqueado abaixo, depois dos dois campos, com aviso
        # explícito em vez de deixar a página quebrar com ZeroDivisionError.
        "Fração liberada — numerador", step=1,
        key="limite_empenho_numerador",
        help='A fração que a PROPLAD comunica a cada liberação de cota (ex.: "9/12"). '
        "Nunca é calculada por este sistema — atualize aqui quando chegar uma nova liberação. "
        "Fica salva em disco, sobrevive a uma atualização de página. Sem faixa fixa — aceita "
        "qualquer valor.",
    )
with col_den:
    denominador = st.number_input(
        "Fração liberada — denominador", step=1,
        key="limite_empenho_denominador",
    )

if denominador == 0:
    st.error(
        "O denominador da fração não pode ser zero — não dá pra calcular Limite/Saldo com "
        "isso. Ajuste o valor acima antes de continuar."
    )
    st.stop()
if numerador > denominador:
    st.warning('O numerador da fração é maior que o denominador (ex.: "13/12") — confira os valores.')
if numerador < 0 or denominador < 0:
    st.warning("Fração com valor negativo — confira se é isso mesmo que a PROPLAD comunicou.")

# Só grava em disco quando o valor efetivamente muda (comparado ao que já está persistido) —
# evita escrever a cada rerun disparado por algo sem relação (trocar um filtro, por exemplo).
_fracao_atual = (int(numerador), int(denominador))
if _fracao_atual != st.session_state.get("_limite_empenho_fracao_gravada"):
    salvar_fracao_liberada(*_fracao_atual)
    st.session_state["_limite_empenho_fracao_gravada"] = _fracao_atual

fracao = Fraction(int(numerador), int(denominador))
resultado = saldo_disponivel_a_empenhar(dotacao, execucao_mensal, int(ano), fracao)
if resultado.empty:
    st.info("Nenhuma combinação Ação/PTRES no escopo discricionário para este exercício.")
    st.stop()

try:
    remanejamentos_em_vigor = remanejamentos_ativos(carregar_remanejamentos(), int(ano))
except ValueError as error:
    st.error(
        f"{error} — os limites por IDUSO não podem ser exibidos sem saber quais remanejamentos "
        "estão em vigor. Corrija ou restaure o arquivo antes de continuar."
    )
    st.stop()
ajustes_iduso = limite_por_iduso_com_remanejamentos(resultado, remanejamentos_em_vigor)

with st.container(border=True):
    st.markdown("###### Filtros")
    filtrado, filtro_ativo = _render_filtros(resultado)

ausentes = ajustes_iduso.loc[ajustes_iduso["ausente_da_base"], "iduso_cod"].tolist()
if ausentes:
    st.warning(
        "Há remanejamento em vigor envolvendo IDUSO sem nenhuma linha no escopo atual: "
        + ", ".join(ausentes)
        + ". O valor não aparece em nenhum resumo de grupo — confira ou desfaça o remanejamento."
    )
if filtro_ativo and remanejamentos_em_vigor:
    st.info(
        "Há remanejamento(s) entre IDUSOs em vigor, mas eles só são aplicados ao resumo do "
        "grupo sem filtros — com filtro ativo, o resumo mostra só parte do IDUSO."
    )

if filtrado.empty:
    st.warning("Nenhum registro corresponde à combinação de filtros selecionada.")
    st.stop()

sem_valor_dotacao = int(filtrado["dotacao_atualizada"].isna().sum())
if sem_valor_dotacao:
    st.warning(
        f"{sem_valor_dotacao} combinação(ões) Ação/PTRES têm uma linha de Dotação nesta base, "
        "mas o valor de Dotação Atualizada em si é nulo na extração — Limite e Saldo ficam em "
        "branco para elas (não dá pra liberar cota de um valor que não se conhece)."
    )

totais = filtrado[["dotacao_atualizada", "empenhada", "limite_liberado", "saldo_disponivel"]].sum()
saldo_total = float(totais["saldo_disponivel"]) if pd.notna(totais["saldo_disponivel"]) else 0.0

render_metric_grid(
    [
        {
            "label": "Dotação Atualizada",
            "value": format_brl_compact(totais["dotacao_atualizada"]),
            "subtitle": f"{len(filtrado)} registro(s) no recorte",
            "icon": "▥", "tone": dt.ACCENT,
        },
        {
            "label": "Despesas Empenhadas",
            "value": format_brl_compact(totais["empenhada"]),
            "subtitle": f"{_pct_of(totais['empenhada'], totais['dotacao_atualizada'])} da dotação",
            "icon": "!", "tone": dt.WARNING,
        },
        {
            "label": f"Limite {numerador}/{denominador}",
            "value": format_brl_compact(totais["limite_liberado"]),
            "subtitle": f"{_pct_of(totais['limite_liberado'], totais['dotacao_atualizada'])} da dotação",
            "icon": "▥", "tone": dt.ACCENT,
        },
        {
            "label": "Saldo Disponível",
            "value": format_brl_compact(totais["saldo_disponivel"]),
            "subtitle": f"{_pct_of(totais['saldo_disponivel'], totais['limite_liberado'])} do limite",
            "icon": "✓" if saldo_total >= 0 else "!",
            "tone": dt.POSITIVE if saldo_total >= 0 else dt.NEGATIVE,
        },
    ],
    columns=4,
)

col_esquerda, col_direita = st.columns([2, 1])
with col_esquerda:
    with st.container(border=True):
        _render_barras_acao(filtrado, int(numerador), int(denominador))
with col_direita:
    with st.container(border=True):
        _render_saldo_gnd(filtrado)
    with st.container(border=True):
        _render_pontos_atencao(filtrado, int(numerador), int(denominador))

with st.container(border=True):
    _render_remanejamentos(resultado, int(ano), remanejamentos_em_vigor, ajustes_iduso)

with st.container(border=True):
    _render_tabela_ptres(filtrado, None if filtro_ativo else ajustes_iduso.set_index("iduso_cod"))

data_extracao_dotacao = manifesto_dotacao.data_extracao[:10]
data_extracao_execucao = manifesto_execucao_mensal.data_extracao[:10]
st.caption(
    f"Dotação Anual: extração de {data_extracao_dotacao}, hash {manifesto_dotacao.sha256[:8]} · "
    f"Execução Mensal: extração de {data_extracao_execucao}, hash {manifesto_execucao_mensal.sha256[:8]}. "
    "Fração liberada informada manualmente, não deduzida do calendário."
)
