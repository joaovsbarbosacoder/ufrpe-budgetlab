"""Alertas Gerenciais — painel de exceções, sem gráficos e sem filtros.

Duas das 8 categorias já são calculadas de verdade a partir de Dotação Anual x Execução
Anual (`src/alertas_gerenciais.py`) — pedido explícito de integrar "ao que for possível":

- **Ações com déficit projetado**: Ação de Governo onde o Empenhado (UGR Gestão UFRPE) já
  supera a Dotação Atualizada do exercício em andamento.
- **Recursos de emendas parlamentares não executados**: saldo a empenhar do Resultado
  Primário 6 (o único RP de emenda que a Dotação Anual desta extração realmente tem — RP 7/8
  só existem na Execução, sem dotação correspondente ainda).

As outras 6 categorias continuam fictícias/placeholder: Fonte de Recursos da Dotação (10
dígitos) e da Execução (3 dígitos) são esquemas diferentes sem tabela de correspondência
neste projeto (não dá pra cruzar saldo por fonte sem inventar uma equivalência); Contratos,
Bolsas, DEA e Créditos dependem de critérios de corte ainda não definidos com a PROPLAD (README
do handoff original). Continuam marcadas como tal na tela, não misturadas com as 2 reais.

Sem `main()`/`st.set_page_config` próprios (`app.py` já chama isso uma única vez — mesmo
padrão de `app_pages/contratos_vigencia.py`).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.alertas_gerenciais import acoes_com_deficit, ano_extracao_execucao, emendas_rp6_nao_executadas
from src.design_tokens import BORDER, FONT_HEADING, NEGATIVE, POSITIVE, SURFACE, TEXT_MUTED, WARNING
from src.importacao_dotacao import DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_DOTACAO
from src.importacao_dotacao import Manifesto as ManifestoDotacao
from src.importacao_dotacao import NOME_PONTEIRO as PONTEIRO_DOTACAO
from src.importacao_dotacao import carregar_atual as carregar_dotacao_atual
from src.importacao_execucao import DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_EXECUCAO
from src.importacao_execucao import Manifesto as ManifestoExecucao
from src.importacao_execucao import NOME_PONTEIRO as PONTEIRO_EXECUCAO
from src.importacao_execucao import carregar_atual as carregar_execucao_atual
from src.ui_theme import render_page_header

CATEGORIAS_PLACEHOLDER = [
    {
        "titulo": "Fontes de recurso prestes a esgotar",
        "unidade": "fontes",
        "severidade": "Atenção",
        "cor": WARNING,
        "real": False,
        "itens": [
            {"nome": "Fonte 1050000000", "detalhe": "8% de saldo restante", "valor": 94_000},
            {"nome": "Fonte 1000000000", "detalhe": "11% de saldo restante", "valor": 210_000},
        ],
    },
    {
        "titulo": "Contratos sem cobertura orçamentária até dezembro",
        "unidade": "contratos",
        "severidade": "Crítico",
        "cor": NEGATIVE,
        "real": False,
        "itens": [
            {"nome": "Contrato 032/2021 — Vigilância Nordeste Segurança S.A.", "detalhe": "Cobertura garantida só até outubro", "valor": 175_200},
            {"nome": "Contrato 018/2023 — Limpeza Total Serviços", "detalhe": "Cobertura garantida só até setembro", "valor": 88_400},
        ],
    },
    {
        "titulo": "Bolsas sem saldo suficiente",
        "unidade": "bolsas",
        "severidade": "Atenção",
        "cor": WARNING,
        "real": False,
        "itens": [
            {"nome": "Bolsa Permanência — CAPECA", "detalhe": "Saldo cobre até novembro", "valor": 42_000},
            {"nome": "Bolsa Monitoria — PRAE", "detalhe": "Saldo cobre até outubro", "valor": 18_500},
        ],
    },
    {
        "titulo": "Empenhos próximos do vencimento",
        "unidade": "empenhos",
        "severidade": "Atenção",
        "cor": WARNING,
        "real": False,
        "itens": [
            {"nome": "26NE000180", "detalhe": "Vence em 14 dias — saldo não liquidado", "valor": 18_994},
            {"nome": "26NE000205", "detalhe": "Vence em 22 dias — saldo não liquidado", "valor": 94_210},
        ],
    },
    {
        "titulo": "DEA elevado",
        "unidade": "unidades",
        "severidade": "Crítico",
        "cor": NEGATIVE,
        "real": False,
        "itens": [
            {"nome": "PROGEST", "detalhe": "DEA acima do limite de referência da unidade", "valor": 402_000},
        ],
    },
    {
        "titulo": "Créditos orçamentários pendentes de utilização",
        "unidade": "créditos",
        "severidade": "Ok",
        "cor": POSITIVE,
        "real": False,
        "itens": [],
    },
]

ORDEM_SEVERIDADE = {"Crítico": 0, "Atenção": 1, "Ok": 2}


@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def _cached_dotacao(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    return carregar_dotacao_atual()


@st.cache_data(show_spinner="Lendo a base de Execução Anual...")
def _cached_execucao(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    return carregar_execucao_atual()


def _brl(valor: float) -> str:
    return "R$ " + f"{round(valor):,.0f}".replace(",", ".")


def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .ag-tag {{
            font-family: {FONT_HEADING}; font-size: 10px; letter-spacing: 0.08em;
            text-transform: uppercase; padding: 3px 8px; border-radius: 999px;
            border: 1px solid currentColor; display: inline-block;
        }}
        .ag-real {{
            font-family: {FONT_HEADING}; font-size: 9.5px; letter-spacing: 0.06em;
            text-transform: uppercase; color: {TEXT_MUTED};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.dialog("Itens em alerta")
def _abrir_categoria(categoria: dict) -> None:
    st.markdown(
        f"<span class='ag-tag' style='color:{categoria['cor']}'>{categoria['severidade']}</span>",
        unsafe_allow_html=True,
    )
    st.subheader(categoria["titulo"])
    total = sum(item["valor"] for item in categoria["itens"])
    st.caption(f"{len(categoria['itens'])} {categoria['unidade']} · {_brl(total)} em risco")
    if not categoria["real"]:
        st.caption("⚠ Dado fictício/placeholder — critério ainda não definido com a PROPLAD.")
    st.divider()
    for item in categoria["itens"]:
        coluna_nome, coluna_valor = st.columns([4, 1])
        coluna_nome.markdown(
            f"**{item['nome']}**  \n<span style='color:{TEXT_MUTED};font-size:12px'>{item['detalhe']}</span>",
            unsafe_allow_html=True,
        )
        coluna_valor.markdown(
            f"<div style='text-align:right;font-family:{FONT_HEADING}'>{_brl(item['valor'])}</div>",
            unsafe_allow_html=True,
        )


render_page_header(
    "Alertas Gerenciais",
    "Painel de exceções — só aparece o que precisa de ação.",
)
_inject_css()

manifesto_dotacao = ManifestoDotacao.atual()
manifesto_execucao = ManifestoExecucao.atual()

categorias_reais: list[dict] = []
if manifesto_dotacao is not None and manifesto_execucao is not None:
    caminho_dotacao = DIR_MANIFESTOS_DOTACAO / PONTEIRO_DOTACAO
    caminho_execucao = DIR_MANIFESTOS_EXECUCAO / PONTEIRO_EXECUCAO
    dotacao = _cached_dotacao(str(caminho_dotacao), caminho_dotacao.stat().st_mtime)
    execucao = _cached_execucao(str(caminho_execucao), caminho_execucao.stat().st_mtime)
    ano = ano_extracao_execucao(manifesto_execucao)

    itens_deficit = acoes_com_deficit(dotacao, execucao, ano)
    categorias_reais.append(
        {
            "titulo": "Ações com déficit projetado",
            "unidade": "ações",
            "severidade": "Crítico" if itens_deficit else "Ok",
            "cor": NEGATIVE if itens_deficit else POSITIVE,
            "real": True,
            "itens": itens_deficit,
        }
    )

    itens_emendas = emendas_rp6_nao_executadas(dotacao, execucao, ano)
    categorias_reais.append(
        {
            "titulo": "Recursos de emendas parlamentares não executados",
            "unidade": "emendas",
            "severidade": "Atenção" if itens_emendas else "Ok",
            "cor": WARNING if itens_emendas else POSITIVE,
            "real": True,
            "itens": itens_emendas,
        }
    )
else:
    st.info(
        "'Ações com déficit projetado' e 'Recursos de emendas parlamentares não executados' "
        "cruzariam Dotação Anual e Execução Anual reais, mas uma das duas bases ainda não foi "
        "importada — aparecem como as demais categorias abaixo, fictícias/placeholder, até lá."
    )
    categorias_reais = [
        {**categoria, "real": False}
        for categoria in [
            {"titulo": "Ações com déficit projetado", "unidade": "ações", "severidade": "Crítico", "cor": NEGATIVE, "itens": [
                {"nome": "20RK — Funcionamento de IFES", "detalhe": "Projeção de gasto excede a dotação atualizada", "valor": 340_000},
            ]},
            {"titulo": "Recursos de emendas parlamentares não executados", "unidade": "emendas", "severidade": "Atenção", "cor": WARNING, "itens": [
                {"nome": "Emenda 20120040 — Sen. João Falcão", "detalhe": "Parada há 95 dias em TED", "valor": 1_800_000},
            ]},
        ]
    ]

CATEGORIAS = categorias_reais + CATEGORIAS_PLACEHOLDER

ordenadas = sorted(CATEGORIAS, key=lambda categoria: (ORDEM_SEVERIDADE[categoria["severidade"]], -len(categoria["itens"])))
total_itens = sum(len(categoria["itens"]) for categoria in CATEGORIAS)
total_criticos = sum(len(categoria["itens"]) for categoria in CATEGORIAS if categoria["severidade"] == "Crítico")
total_atencao = sum(len(categoria["itens"]) for categoria in CATEGORIAS if categoria["severidade"] == "Atenção")

colunas_kpi = st.columns(3)
colunas_kpi[0].metric("Itens em alerta", total_itens)
colunas_kpi[1].metric("Críticos", total_criticos)
colunas_kpi[2].metric("Em atenção", total_atencao)

colunas = st.columns(2)
for indice, categoria in enumerate(ordenadas):
    with colunas[indice % 2]:
        with st.container(border=True):
            coluna_titulo, coluna_tag = st.columns([4, 1])
            coluna_titulo.markdown(f"**{categoria['titulo']}**")
            coluna_tag.markdown(
                f"<span class='ag-tag' style='color:{categoria['cor']}'>{categoria['severidade']}</span>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<span class='ag-real'>Dado real (Dotação x Execução)</span>"
                if categoria["real"]
                else "<span class='ag-real'>Fictício/placeholder</span>",
                unsafe_allow_html=True,
            )
            total = sum(item["valor"] for item in categoria["itens"])
            st.markdown(
                f"<div style='font-family:{FONT_HEADING};font-size:32px;color:{categoria['cor']}'>"
                f"{len(categoria['itens'])}"
                f"<span style='font-size:12px;color:{TEXT_MUTED};text-transform:uppercase'> {categoria['unidade']}</span>"
                "</div>",
                unsafe_allow_html=True,
            )
            st.caption(f"{_brl(total)} em risco" if categoria["itens"] else "Nenhum item — checagem em dia")
            if categoria["itens"]:
                if st.button("Ver lista", key=f"alertas_categoria_{indice}"):
                    _abrir_categoria(categoria)

st.caption(
    "Sem gráficos e sem filtros — página de varredura. 'Ações com déficit projetado' e "
    "'Recursos de emendas parlamentares não executados' já cruzam Dotação x Execução reais; "
    "as demais categorias continuam fictícias/placeholder até seus critérios de corte serem "
    "definidos com a PROPLAD."
)
