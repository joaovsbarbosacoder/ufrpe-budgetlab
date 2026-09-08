"""Painel de Prazos Orçamentários — cadastro manual de datas, com alerta por proximidade.

Pedido explícito: NÃO deriva de Contratos (vigência/termo final) nem de Bolsas (necessidade
de reforço de empenho) — o usuário cadastra o próprio prazo (ex.: prestação de contas, envio
de relatório, prazo de empenho de uma fonte específica), tipicamente uma vez no início do
exercício, e a tela avisa conforme a data se aproxima. Leitura/gravação em
`src/prazos_orcamentarios.py`; esta página só monta o formulário e a lista.

Persistido em disco (`data/prazos_orcamentarios/`, um JSON por prazo) — decisão confirmada
com o usuário (regra do projeto: nenhuma persistência nova sem aprovação explícita, ver
AGENTS.md) para o cadastro sobreviver a reiniciar o app ao longo do exercício.

Cada prazo tem sua própria antecedência de alerta (`dias_antecedencia`, pedido explícito) —
não uma régua fixa: "Em alerta" significa dentro dos N dias que o próprio prazo escolheu, não
um limiar igual pra todo mundo (ver `src.prazos_orcamentarios._classificar`).

Resumo de alerta também aparece em `app_pages/home.py` (card só visível quando há vencido/em
alerta — pedido explícito), lendo os mesmos dados por `carregar_prazos`/`prazos_com_criticidade`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.design_tokens import FONT_HEADING, NEGATIVE, POSITIVE, TEXT_MUTED, WARNING
from src.prazos_orcamentarios import (
    DIAS_ANTECEDENCIA_PADRAO,
    DIRETORIO_PADRAO,
    atualizar,
    carregar_prazos,
    excluir,
    novo_prazo,
    prazos_com_criticidade,
    salvar,
)
from src.ui_theme import render_alert, render_metric_grid, render_page_header

CRITICIDADE_COR = {
    "Vencido": NEGATIVE, "Em alerta": WARNING, "No prazo": POSITIVE, "Concluído": TEXT_MUTED,
}


def _dash(valor: object) -> str:
    return "—" if (valor is None or (isinstance(valor, float) and pd.isna(valor)) or valor == "") else str(valor)


def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .pp-label {{
            font-family: {FONT_HEADING}; font-size: 11px; letter-spacing: 0.1em;
            text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .pp-badge {{
            display: inline-block; font-family: {FONT_HEADING}; font-size: 9.5px;
            letter-spacing: .04em; text-transform: uppercase; padding: 2px 7px;
            border-radius: 3px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _badge(texto: str, cor: str) -> str:
    return f"<span class='pp-badge' style='background:{cor}22;color:{cor}'>{texto}</span>"


def _render_formulario_novo_prazo() -> None:
    with st.form("pp_novo_prazo", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 1, 1])
        titulo = c1.text_input("Título do prazo", placeholder="ex.: Prestação de contas — Convênio 12/2026")
        data_prazo = c2.date_input("Data", value=None, format="DD/MM/YYYY")
        dias_antecedencia = c3.number_input(
            "Avisar com (dias)", min_value=0, value=DIAS_ANTECEDENCIA_PADRAO, step=5,
            help="Quantos dias antes do prazo você quer começar a receber alerta.",
        )
        c4, c5 = st.columns(2)
        responsavel = c4.text_input("Responsável (opcional)")
        descricao = c5.text_input("Observação (opcional)")
        if st.form_submit_button("Cadastrar prazo", icon=":material/add_alert:"):
            if not titulo.strip() or data_prazo is None:
                st.error("Informe ao menos o título e a data do prazo.")
            else:
                salvar(novo_prazo(titulo, data_prazo, descricao, responsavel, int(dias_antecedencia)))
                st.rerun()


def _prazo_bruto_editavel(row: pd.Series) -> dict:
    """`row` vem de `prazos_com_criticidade` (colunas derivadas `dias_para_vencer`/
    `criticidade` incluídas, `data_prazo` como `datetime.date`, `concluido`/`dias_antecedencia`
    possivelmente numpy — json.dumps não serializa nenhum desses tipos numpy, então este dict
    só tem os campos que `atualizar`/`salvar` esperam gravar, já convertidos."""

    bruto = dict(row.drop(labels=["dias_para_vencer", "criticidade"]))
    bruto["data_prazo"] = row["data_prazo"].isoformat()
    bruto["concluido"] = bool(row["concluido"])
    bruto["dias_antecedencia"] = int(row["dias_antecedencia"])
    return bruto


@st.dialog("Editar prazo")
def _abrir_editar(row: pd.Series) -> None:
    k = f"pp_edit_{row['id']}"
    titulo = st.text_input("Título do prazo", value=row["titulo"], key=f"{k}_titulo")
    c1, c2 = st.columns(2)
    data_prazo = c1.date_input("Data", value=row["data_prazo"], format="DD/MM/YYYY", key=f"{k}_data")
    dias_antecedencia = c2.number_input(
        "Avisar com (dias)", min_value=0, value=int(row["dias_antecedencia"]), step=5, key=f"{k}_antecedencia",
        help="Quantos dias antes do prazo você quer começar a receber alerta.",
    )
    c3, c4 = st.columns(2)
    # `responsavel`/`descricao` sempre chegam como string (possivelmente vazia — ver
    # `novo_prazo`), nunca NaN/None: não precisam do tratamento de `_dash` usado na listagem.
    responsavel = c3.text_input("Responsável (opcional)", value=row["responsavel"], key=f"{k}_resp")
    descricao = c4.text_input("Observação (opcional)", value=row["descricao"], key=f"{k}_desc")
    if st.button("Salvar alterações", key=f"{k}_salvar", icon=":material/save:"):
        if not titulo.strip() or data_prazo is None:
            st.error("Informe ao menos o título e a data do prazo.")
        else:
            bruto = _prazo_bruto_editavel(row)
            bruto["titulo"] = titulo.strip()
            bruto["data_prazo"] = data_prazo.isoformat()
            bruto["dias_antecedencia"] = int(dias_antecedencia)
            bruto["responsavel"] = responsavel.strip()
            bruto["descricao"] = descricao.strip()
            atualizar(bruto)
            st.rerun()


def _acoes_prazo(row: pd.Series) -> None:
    c1, c2, c3, c4 = st.columns(4)
    rotulo_concluir = "Reabrir" if row["concluido"] else "Concluir"
    if c1.button(rotulo_concluir, key=f"pp_toggle_{row['id']}", use_container_width=True):
        bruto = _prazo_bruto_editavel(row)
        bruto["concluido"] = not bruto["concluido"]
        atualizar(bruto)
        st.rerun()
    if c2.button("Editar", key=f"pp_editar_{row['id']}", use_container_width=True):
        _abrir_editar(row)
    if c3.button("Duplicar", key=f"pp_duplicar_{row['id']}", use_container_width=True):
        # cópia começa sempre pendente (concluido=False), mesmo duplicando um prazo já
        # concluído — o caso mais comum de duplicar é justamente reabrir a mesma exigência
        # para o próximo ciclo (ex.: prestação de contas anual), não repetir uma já feita.
        salvar(
            novo_prazo(
                f"{row['titulo']} (cópia)", row["data_prazo"], row["descricao"], row["responsavel"],
                int(row["dias_antecedencia"]),
            )
        )
        st.rerun()
    with c4.popover("Excluir", use_container_width=True):
        st.write(f"Excluir **{row['titulo']}** definitivamente?")
        if st.button("Confirmar exclusão", key=f"pp_excluir_{row['id']}"):
            excluir(row["id"])
            st.rerun()


def _render_lista(prazos: pd.DataFrame) -> None:
    for _, row in prazos.iterrows():
        cor = CRITICIDADE_COR.get(row["criticidade"], TEXT_MUTED)
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"**{row['titulo']}**")
            c2.markdown(f"<div style='text-align:right'>{_badge(row['criticidade'], cor)}</div>", unsafe_allow_html=True)

            c3, c4, c5, c6 = st.columns(4)
            c3.markdown("<span class='pp-label'>Data</span>", unsafe_allow_html=True)
            c3.write(row["data_prazo"].strftime("%d/%m/%Y"))
            c4.markdown("<span class='pp-label'>Dias</span>", unsafe_allow_html=True)
            dias = row["dias_para_vencer"]
            c4.write(f"Vencido há {abs(int(dias))}d" if dias < 0 else f"{int(dias)}d")
            c5.markdown("<span class='pp-label'>Avisar com</span>", unsafe_allow_html=True)
            c5.write(f"{int(row['dias_antecedencia'])}d de antecedência")
            c6.markdown("<span class='pp-label'>Responsável</span>", unsafe_allow_html=True)
            c6.write(_dash(row["responsavel"]))

            if _dash(row["descricao"]) != "—":
                st.caption(row["descricao"])

            _acoes_prazo(row)


# ---------------------------------------------------------------------- página
render_page_header(
    "Painel de Prazos Orçamentários",
    "Cadastre um prazo do exercício e acompanhe o alerta conforme a data se aproxima.",
    "Prazos",
)
_inject_css()

st.markdown("#### Novo prazo")
_render_formulario_novo_prazo()

prazos_brutos = carregar_prazos()
prazos = prazos_com_criticidade(prazos_brutos)

if prazos.empty:
    st.info("Nenhum prazo cadastrado ainda — use o formulário acima para começar.")
    st.stop()

pendentes = prazos[~prazos["concluido"]]
vencidos = int((pendentes["criticidade"] == "Vencido").sum())
em_alerta = int((pendentes["criticidade"] == "Em alerta").sum())

if vencidos:
    render_alert(f"{vencidos} prazo(s) vencido(s) sem conclusão.", "error")
elif em_alerta:
    render_alert(f"{em_alerta} prazo(s) em alerta — dentro da antecedência escolhida para cada um.", "warning")
else:
    render_alert("Nenhum prazo pendente vencido ou dentro da antecedência de alerta.", "success")

render_metric_grid(
    [
        {"label": "Prazos cadastrados", "value": str(len(prazos))},
        {"label": "Vencidos", "value": str(vencidos)},
        {"label": "Em alerta", "value": str(em_alerta)},
        {"label": "Concluídos", "value": str(int(prazos["concluido"].sum()))},
    ],
    columns=4,
)

st.markdown("#### Prazos")
mostrar_concluidos = st.checkbox("Mostrar concluídos", key="pp_mostrar_concluidos")
visiveis = prazos if mostrar_concluidos else prazos[~prazos["concluido"]]

if visiveis.empty:
    st.caption("Nenhum prazo pendente — todos os cadastrados já foram concluídos.")
else:
    _render_lista(visiveis)

st.caption(
    f"Cadastro manual, persistido em '{DIRETORIO_PADRAO}' — sobrevive a reiniciar o app. "
    "Não deriva de Contratos nem de Bolsas: cada prazo é registrado aqui, um a um, com sua "
    "própria antecedência de alerta."
)
