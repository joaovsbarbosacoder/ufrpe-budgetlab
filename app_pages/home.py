"""Painel inicial do UFRPE BudgetLab.

Resume apenas estados observáveis no ambiente local: disponibilidade das bases
cadastradas e prazos orçamentários. Não calcula totais financeiros nem presume
regras entre bases diferentes. Layout repaginado em 28/10/2026 (indicadores em
cartões, lista de prazos, estado de cada base e atalhos por área); os dados e as
regras são os mesmos de antes.
"""

from datetime import datetime
from pathlib import Path

import streamlit as st

from src import ui_home as hm
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
from src.ui_theme import render_page_header

#: prazos listados no painel da página inicial (os mais urgentes; o resto fica em Gerenciamento de Prazos).
PRAZOS_NA_LISTA = 5


def _estado_bases() -> list[tuple[str, bool, datetime | None]]:
    """Disponibilidade e atualização de cada base, sem abrir as planilhas."""

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
    return estados


def _resumo_bases(estados) -> tuple[int, int, list[str], datetime | None]:
    ausentes = [nome for nome, disponivel, _ in estados if not disponivel]
    datas = [data for _, disponivel, data in estados if disponivel and data is not None]
    return len(estados) - len(ausentes), len(estados), ausentes, max(datas, default=None)


def _prazos():
    """(pendentes, atrasados, vencendo, lista dos mais urgentes) — a ordenação vem de `prazos_com_criticidade`."""
    prazos = prazos_com_criticidade(carregar_prazos())
    if prazos.empty:
        return 0, 0, 0, []
    pendentes = prazos[~prazos["concluido"]]
    atrasados = int((pendentes["criticidade"] == CRITICIDADE_ATRASADO).sum())
    vencendo = int((pendentes["criticidade"] == CRITICIDADE_VENCENDO).sum())
    lista = pendentes.head(PRAZOS_NA_LISTA).to_dict("records")
    return len(pendentes), atrasados, vencendo, lista


estados_bases = _estado_bases()
bases_disponiveis, bases_cadastradas, bases_ausentes, ultima_atualizacao = _resumo_bases(estados_bases)
prazos_pendentes, prazos_atrasados, prazos_vencendo, proximos_prazos = _prazos()

render_page_header(
    "Visão geral",
    "Acompanhamento integrado das bases e rotinas orçamentárias da UFRPE.",
    "Gestão orçamentária",
)

chips = []
if ultima_atualizacao is not None:
    chips.append(hm.chip(f"Atualização mais recente entre as bases: {ultima_atualizacao:%d/%m/%Y às %H:%M}", "azul"))
else:
    chips.append(hm.chip("Nenhuma base local disponível para identificar a última atualização", "cinza"))
if bases_ausentes:
    chips.append(hm.chip("Bases ainda não disponíveis: " + ", ".join(bases_ausentes), "laranja"))
else:
    chips.append(hm.chip("Todas as bases cadastradas estão disponíveis localmente", "verde"))
if prazos_atrasados:
    chips.append(hm.chip(f"{prazos_atrasados} prazo(s) orçamentário(s) atrasado(s) requer(em) atenção", "vermelho"))
elif prazos_vencendo:
    chips.append(hm.chip(f"{prazos_vencendo} prazo(s) na antecedência de alerta configurada", "laranja"))
elif prazos_pendentes:
    chips.append(hm.chip("Nenhum prazo pendente está em situação de alerta", "verde"))
else:
    chips.append(hm.chip("Nenhum prazo orçamentário pendente cadastrado", "cinza"))
st.html(hm.CSS + hm.faixa(chips))

st.html(hm.kpis([
    {"rotulo": "Bases disponíveis", "valor": bases_disponiveis, "complemento": f"de {bases_cadastradas}",
     "sub": "Bases versionadas com manifesto e planilhas de trabalho encontradas localmente.",
     "tom": "verde" if not bases_ausentes else "laranja"},
    {"rotulo": "Prazos pendentes", "valor": prazos_pendentes,
     "sub": "Prazos cadastrados que ainda não foram concluídos.", "tom": "azul"},
    {"rotulo": "Atrasados", "valor": prazos_atrasados,
     "sub": "Prazos pendentes cuja data já passou.", "tom": "vermelho" if prazos_atrasados else "verde"},
    {"rotulo": "Vencendo", "valor": prazos_vencendo,
     "sub": "Prazos dentro da antecedência configurada em cada cadastro.", "tom": "laranja" if prazos_vencendo else "verde"},
]))

st.html(hm.paineis(hm.painel_prazos(proximos_prazos, prazos_pendentes), hm.painel_bases(estados_bases)))
st.page_link("app_pages/painel_prazos.py", label="Abrir Gerenciamento de Prazos", icon=":material/event_upcoming:")

st.html(hm.secao(
    "Acessos rápidos",
    "Abra diretamente as áreas mais utilizadas. Cada módulo mantém sua própria fonte e rastreabilidade.",
))

#: (ícone, título, descrição, tom, [(página, rótulo, ícone do link)])
GRUPOS = [
    ("▦", "Planejamento e execução", "Acompanhamento por ação e limite de empenho.", "azul", [
        ("app_pages/painel_acoes.py", "Painel por ação", ":material/dashboard:"),
        ("app_pages/limite_empenho.py", "Limite de empenho", ":material/rule:"),
        ("app_pages/resultado_orcamentario.py", "Resultado orçamentário", ":material/balance:"),
    ]),
    ("☰", "Operação", "Consultas detalhadas e despesas recorrentes.", "verde", [
        ("app_pages/consulta_empenhos.py", "Consulta de empenhos", ":material/receipt_long:"),
        ("app_pages/empenhos_execucao_retardada.py", "Empenhos com execução retardada", ":material/schedule:"),
        ("app_pages/bolsas_auxilios.py", "Bolsas e auxílios", ":material/school:"),
        ("app_pages/despesas_pessoal.py", "Despesas de pessoal", ":material/groups:"),
    ]),
    ("◎", "Gestão e controle", "Alertas, prazos, Diário Oficial e emendas.", "laranja", [
        ("app_pages/alertas_gerenciais.py", "Alertas gerenciais", ":material/notifications:"),
        ("app_pages/painel_prazos.py", "Gerenciamento de prazos", ":material/event_upcoming:"),
        ("app_pages/diario_oficial.py", "Diário Oficial (DOU)", ":material/newspaper:"),
        ("app_pages/emendas_parlamentares.py", "Emendas parlamentares", ":material/account_balance:"),
    ]),
    ("✎", "Contratos, TEDs e dados", "Contratos, acompanhamento de TEDs e atualização das fontes.", "cinza", [
        ("app_pages/contratos.py", "Contratos", ":material/description:"),
        ("app_pages/contratos_continuos.py", "Contratos contínuos", ":material/handshake:"),
        ("app_pages/teds_visao_geral.py", "TEDs — visão geral", ":material/home:"),
        ("app_pages/atualizar_planilhas.py", "Atualizar planilhas", ":material/upload_file:"),
    ]),
]

colunas = st.columns(len(GRUPOS), vertical_alignment="top")
for coluna, (icone, titulo, descricao, tom, links) in zip(colunas, GRUPOS):
    with coluna.container(border=True, height="stretch"):
        st.html(hm.cabecalho_grupo(icone, titulo, descricao, tom))
        for pagina, rotulo, icone_link in links:
            st.page_link(pagina, label=rotulo, icon=icone_link)

st.caption(
    "Os indicadores desta página representam disponibilidade local e prazos cadastrados; "
    "não combinam valores financeiros entre bases com datas de extração diferentes."
)
