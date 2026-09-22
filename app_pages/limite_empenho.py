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
"""

from __future__ import annotations

from datetime import datetime
from fractions import Fraction

import pandas as pd
import streamlit as st

from src.importacao_dotacao import DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_DOTACAO
from src.importacao_dotacao import Manifesto as ManifestoDotacao
from src.importacao_dotacao import NOME_PONTEIRO as PONTEIRO_DOTACAO
from src.importacao_dotacao import carregar_atual as carregar_dotacao_atual
from src.importacao_execucao_mensal import DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_EXECUCAO_MENSAL
from src.importacao_execucao_mensal import Manifesto as ManifestoExecucaoMensal
from src.importacao_execucao_mensal import NOME_PONTEIRO as PONTEIRO_EXECUCAO_MENSAL
from src.importacao_execucao_mensal import carregar_atual as carregar_execucao_mensal_atual
from src.limite_empenho import saldo_disponivel_a_empenhar
from src.ui_theme import format_brl_compact, render_metric_grid, render_page_header


@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def _cached_dotacao(caminho_ponteiro: str, sha_manifesto: str) -> pd.DataFrame:
    return carregar_dotacao_atual()


@st.cache_data(show_spinner="Lendo a base de Execução Mensal...")
def _cached_execucao_mensal(caminho_ponteiro: str, sha_manifesto: str) -> pd.DataFrame:
    return carregar_execucao_mensal_atual()


def _situacao(saldo: object) -> str:
    # saldo só fica nulo quando Dotação Atualizada em si é nula na origem (zero seria um
    # número real, não NaN — ver docstring de `src/limite_empenho.py`).
    if pd.isna(saldo):
        return "Sem valor de Dotação Atualizada"
    if float(saldo) < 0:
        return "Estourado"
    return "Dentro do limite"


def _render_tabela(resultado: pd.DataFrame) -> None:
    tabela = resultado.copy()
    tabela["Ação"] = tabela["acao_cod"] + " — " + tabela["acao_desc"].fillna("")
    tabela["PTRES"] = tabela["ptres"]
    tabela["Plano Orçamentário"] = tabela["po_cod"] + " — " + tabela["po_desc"].fillna("")
    tabela["GND"] = tabela["gnd_cod"] + " — " + tabela["gnd_desc"].fillna("")
    tabela["Situação"] = tabela["saldo_disponivel"].apply(_situacao)

    st.dataframe(
        tabela[
            [
                "Ação", "PTRES", "Plano Orçamentário", "GND",
                "dotacao_atualizada", "empenhada", "limite_liberado", "saldo_disponivel", "Situação",
            ]
        ].rename(
            columns={
                "dotacao_atualizada": "Dotação Atualizada",
                "empenhada": "Despesas Empenhadas",
                "limite_liberado": "Limite Liberado",
                "saldo_disponivel": "Saldo Disponível a Empenhar",
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Dotação Atualizada": st.column_config.NumberColumn(format="R$ %.2f"),
            "Despesas Empenhadas": st.column_config.NumberColumn(format="R$ %.2f"),
            "Limite Liberado": st.column_config.NumberColumn(format="R$ %.2f"),
            "Saldo Disponível a Empenhar": st.column_config.NumberColumn(format="R$ %.2f"),
        },
    )


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
st.caption(
    f"Exercício {ano} (corrente, conforme a extração da Dotação Anual) — cota liberada só "
    "existe para o exercício em andamento, não há seleção de anos passados."
)
if ano not in set(execucao_mensal["ano"].dropna().unique().tolist()):
    st.warning(
        f"A Execução Mensal não tem nenhum dado para {ano} — Despesas Empenhadas vai "
        "aparecer como R$ 0,00 em toda a tabela, não porque nada foi empenhado, mas porque "
        "esse exercício ainda não está nessa base."
    )

col_num, col_den = st.columns([1, 1])
with col_num:
    numerador = st.number_input(
        "Fração liberada — numerador", min_value=1, max_value=12,
        value=st.session_state.get("limite_empenho_numerador", 12), step=1,
        key="limite_empenho_numerador",
        help='A fração que a PROPLAD comunica a cada liberação de cota (ex.: "9/12"). '
        "Nunca é calculada por este sistema — atualize aqui quando chegar uma nova liberação.",
    )
with col_den:
    denominador = st.number_input(
        "Fração liberada — denominador", min_value=1, max_value=12,
        value=st.session_state.get("limite_empenho_denominador", 12), step=1,
        key="limite_empenho_denominador",
    )

if numerador > denominador:
    st.warning('O numerador da fração é maior que o denominador (ex.: "13/12") — confira os valores.')

fracao = Fraction(int(numerador), int(denominador))

resultado = saldo_disponivel_a_empenhar(dotacao, execucao_mensal, int(ano), fracao)
if resultado.empty:
    st.info("Nenhuma combinação Ação/PTRES no escopo discricionário para este exercício.")
    st.stop()

sem_valor_dotacao = resultado["dotacao_atualizada"].isna().sum()
estourados = (resultado["saldo_disponivel"] < 0).sum()

totais = resultado[["dotacao_atualizada", "empenhada", "limite_liberado", "saldo_disponivel"]].sum()

render_metric_grid(
    [
        {"label": "Dotação Atualizada", "value": format_brl_compact(float(totais["dotacao_atualizada"]))},
        {"label": "Despesas Empenhadas", "value": format_brl_compact(float(totais["empenhada"]))},
        {"label": f"Limite Liberado ({numerador}/{denominador})", "value": format_brl_compact(float(totais["limite_liberado"]))},
        {"label": "Saldo Disponível a Empenhar", "value": format_brl_compact(float(totais["saldo_disponivel"]))},
        {"label": "Estourados", "value": str(int(estourados))},
        {"label": "Sem valor de Dotação", "value": str(int(sem_valor_dotacao))},
    ],
    columns=6,
)

if sem_valor_dotacao:
    st.warning(
        f"{sem_valor_dotacao} combinação(ões) Ação/PTRES têm uma linha de Dotação nesta base, "
        "mas o valor de Dotação Atualizada em si é nulo na extração — Limite e Saldo ficam em "
        "branco para elas (não dá pra liberar cota de um valor que não se conhece)."
    )

with st.container(border=True):
    st.subheader("Saldo por Ação / PTRES")
    st.caption(
        "Escopo Discricionário: exclui despesas de pessoal (GND 1) e emendas parlamentares "
        '(Resultado Primário 6), só Fonte de Recursos "000" (Recursos Livres da União).'
    )
    _render_tabela(resultado)

data_extracao_dotacao = manifesto_dotacao.data_extracao[:10]
data_extracao_execucao = manifesto_execucao_mensal.data_extracao[:10]
st.caption(
    f"Dotação Anual: extração de {data_extracao_dotacao}, hash {manifesto_dotacao.sha256[:8]} · "
    f"Execução Mensal: extração de {data_extracao_execucao}, hash {manifesto_execucao_mensal.sha256[:8]}. "
    "Fração liberada informada manualmente, não deduzida do calendário."
)
