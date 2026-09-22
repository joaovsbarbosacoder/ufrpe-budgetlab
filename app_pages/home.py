"""Painel inicial do UFRPE BudgetLab.

Resume apenas estados observáveis no ambiente local: disponibilidade das bases
cadastradas e prazos orçamentários. Não calcula totais financeiros nem presume
regras entre bases diferentes.
"""

from datetime import datetime
from pathlib import Path

import streamlit as st

from src.atualizar_planilhas import ESPECIFICACOES
from src.importacao_dotacao import Manifesto as ManifestoDotacao
from src.importacao_execucao import Manifesto as ManifestoExecucao
from src.importacao_execucao_mensal import Manifesto as ManifestoExecucaoMensal
from src.prazos_orcamentarios import (
    CRITICIDADE_ATRASADO,
    CRITICIDADE_VENCENDO,
    carregar_prazos,
    prazos_com_criticidade,
)
from src.ui_theme import render_metric_grid, render_page_header


def _resumo_bases() -> tuple[int, int, list[str], datetime | None]:
    """Disponibilidade e atualização das bases, sem abrir as planilhas."""

    estados: list[tuple[str, bool, datetime | None]] = []
    for nome, manifesto in (
        ("Execução Anual", ManifestoExecucao.atual()),
        ("Dotação Anual", ManifestoDotacao.atual()),
        ("Execução Mensal", ManifestoExecucaoMensal.atual()),
    ):
        atualizado_em = None
        if manifesto is not None:
            try:
                atualizado_em = datetime.fromisoformat(manifesto.data_extracao)
            except (TypeError, ValueError):
                atualizado_em = None
        estados.append((nome, manifesto is not None, atualizado_em))

    for especificacao in ESPECIFICACOES.values():
        caminho = Path(especificacao.caminho)
        atualizado_em = (
            datetime.fromtimestamp(caminho.stat().st_mtime)
            if caminho.exists()
            else None
        )
        estados.append((especificacao.nome, caminho.exists(), atualizado_em))

    ausentes = [nome for nome, disponivel, _ in estados if not disponivel]
    datas = [data for _, disponivel, data in estados if disponivel and data is not None]
    return len(estados) - len(ausentes), len(estados), ausentes, max(datas, default=None)


def _resumo_prazos() -> tuple[int, int, int]:
    prazos = prazos_com_criticidade(carregar_prazos())
    if prazos.empty:
        return 0, 0, 0
    pendentes = prazos[~prazos["concluido"]]
    atrasados = int((pendentes["criticidade"] == CRITICIDADE_ATRASADO).sum())
    vencendo = int((pendentes["criticidade"] == CRITICIDADE_VENCENDO).sum())
    return len(pendentes), atrasados, vencendo


bases_disponiveis, bases_cadastradas, bases_ausentes, ultima_atualizacao = _resumo_bases()
prazos_pendentes, prazos_atrasados, prazos_vencendo = _resumo_prazos()

render_page_header(
    "Visão geral",
    "Acompanhamento integrado das bases e rotinas orçamentárias da UFRPE.",
    "Gestão orçamentária",
)

if ultima_atualizacao is not None:
    st.caption(f"Atualização mais recente entre as bases: {ultima_atualizacao:%d/%m/%Y às %H:%M}")
else:
    st.caption("Nenhuma base local disponível para identificar a última atualização.")

render_metric_grid(
    [
        {
            "label": ":material/database: Bases disponíveis",
            "value": f"{bases_disponiveis} de {bases_cadastradas}",
            "help": "Bases versionadas com manifesto e planilhas de trabalho encontradas localmente.",
        },
        {
            "label": ":material/event_note: Prazos pendentes",
            "value": prazos_pendentes,
            "help": "Prazos cadastrados que ainda não foram concluídos.",
        },
        {
            "label": ":material/error: Atrasados",
            "value": prazos_atrasados,
            "help": "Prazos pendentes cuja data já passou.",
        },
        {
            "label": ":material/schedule: Vencendo",
            "value": prazos_vencendo,
            "help": "Prazos dentro da antecedência configurada em cada cadastro.",
        },
    ]
)

if bases_ausentes:
    st.warning(
        "Bases ainda não disponíveis: " + ", ".join(bases_ausentes) + ".",
        icon=":material/database_off:",
    )
else:
    st.success(
        "Todas as bases cadastradas estão disponíveis localmente.",
        icon=":material/check_circle:",
    )

if prazos_atrasados:
    st.error(
        f"{prazos_atrasados} prazo(s) orçamentário(s) atrasado(s) requer(em) atenção.",
        icon=":material/error:",
    )
elif prazos_vencendo:
    st.warning(
        f"{prazos_vencendo} prazo(s) entrou(aram) na antecedência de alerta configurada.",
        icon=":material/schedule:",
    )
elif prazos_pendentes:
    st.success(
        "Nenhum prazo pendente está em situação de alerta.",
        icon=":material/check_circle:",
    )
else:
    st.info("Nenhum prazo orçamentário pendente cadastrado.", icon=":material/info:")

st.subheader("Acessos rápidos")
st.caption(
    "Abra diretamente as áreas mais utilizadas. Cada módulo mantém sua "
    "própria fonte e rastreabilidade."
)

col_planejamento, col_operacao, col_gestao = st.columns(3, vertical_alignment="top")

with col_planejamento.container(border=True, height="stretch"):
    st.markdown("#### Planejamento e execução")
    st.caption("Acompanhamento por ação e limite de empenho.")
    st.page_link(
        "app_pages/painel_acoes.py",
        label="Painel por ação",
        icon=":material/dashboard:",
    )
    st.page_link(
        "app_pages/limite_empenho.py",
        label="Limite de empenho",
        icon=":material/rule:",
    )

with col_operacao.container(border=True, height="stretch"):
    st.markdown("#### Operação")
    st.caption("Consultas detalhadas e acompanhamento das despesas recorrentes.")
    st.page_link(
        "app_pages/consulta_empenhos.py",
        label="Consulta de empenhos",
        icon=":material/receipt_long:",
    )
    st.page_link(
        "app_pages/bolsas_auxilios.py",
        label="Bolsas e auxílios",
        icon=":material/school:",
    )
    st.page_link(
        "app_pages/despesas_pessoal.py",
        label="Despesas de pessoal",
        icon=":material/groups:",
    )

with col_gestao.container(border=True, height="stretch"):
    st.markdown("#### Gestão e controle")
    st.caption("Alertas, prazos e atualização controlada das fontes.")
    st.page_link(
        "app_pages/alertas_gerenciais.py",
        label="Alertas gerenciais",
        icon=":material/notifications:",
    )
    st.page_link(
        "app_pages/painel_prazos.py",
        label="Gerenciamento de prazos",
        icon=":material/event_upcoming:",
    )
    st.page_link(
        "app_pages/atualizar_planilhas.py",
        label="Atualizar planilhas",
        icon=":material/upload_file:",
    )

st.caption(
    "Os indicadores desta página representam disponibilidade local e prazos cadastrados; "
    "não combinam valores financeiros entre bases com datas de extração diferentes."
)
