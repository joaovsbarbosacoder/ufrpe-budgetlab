"""Gerenciamento de Prazos — cadastro manual de datas, com alerta por proximidade.

Layout redesenhado em 10/09/2026 a partir de `LAYOUT.md` (anexado pelo usuário, protótipo
`Gerenciamento de Prazos.dc.html`): cabeçalho com botão "+ Novo prazo", faixa de KPIs, uma
linha de filtros sempre visível (busca + tipo + responsável + prioridade + status), grade de
cards (3 colunas fixas — Streamlit não tem `auto-fit` nativo) e formulário em `st.dialog`
(equivalente mais próximo do drawer lateral do protótipo).

Pedido explícito: NÃO deriva de Contratos (vigência/termo final) nem de Bolsas (necessidade
de reforço de empenho) — o usuário cadastra o próprio prazo, tipicamente uma vez no início do
exercício, e a tela avisa conforme a data se aproxima. Leitura/gravação em
`src/prazos_orcamentarios.py`; esta página só monta a interface.

Persistido em disco (`data/prazos_orcamentarios/`, um JSON por prazo) — decisão confirmada
com o usuário (regra do projeto: nenhuma persistência nova sem aprovação explícita, ver
AGENTS.md) para o cadastro sobreviver a reiniciar o app ao longo do exercício.

DECISÃO CONFIRMADA (10/09/2026, via AskUserQuestion, não presumida): o layout de referência
sugeria um limiar FIXO de 7 dias para "Vencendo". O usuário optou por MANTER a antecedência
própria de cada prazo (`dias_antecedencia`, pedido explícito anterior — "licitação precisa de
meses de aviso, tarefa simples de dias") — só os RÓTULOS de criticidade vieram do layout novo
("Em dia"/"Vencendo"/"Atrasado"/"Concluído"), a regra por trás (`_classificar` em
`prazos_orcamentarios.py`) continua a mesma de antes.

Clique no card inteiro não abre o formulário (Streamlit não tem `onClick` em container
arbitrário) — um botão "Editar" discreto dentro do card faz esse papel; o checkbox de
conclusão é um controle separado e imediato (grava e re-executa assim que muda).

Resumo de alerta também aparece em `app_pages/home.py` (card só visível quando há
atrasado/vencendo — pedido explícito), lendo os mesmos dados por
`carregar_prazos`/`prazos_com_criticidade` — os rótulos usados lá foram atualizados junto.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from src import google_agenda, prazos_sincronizacao
from src.google_agenda import ErroGoogleAgenda
from src.design_tokens import ACCENT, FONT_HEADING, NEGATIVE, POSITIVE, TEXT_MUTED, WARNING
from src.prazos_orcamentarios import (
    CRITICIDADE_ATRASADO,
    CRITICIDADE_CONCLUIDO,
    CRITICIDADE_EM_DIA,
    CRITICIDADE_VENCENDO,
    DIAS_ANTECEDENCIA_PADRAO,
    DIRETORIO_PADRAO,
    PRIORIDADES_PRAZO,
    TIPOS_PRAZO,
    ErroPrazoOrcamentario,
    carregar_prazos,
    editar,
    excluir,
    novo_prazo,
    prazos_com_criticidade,
    salvar,
)
from src.ui_theme import render_alert, render_metric_grid, render_page_header

CRITICIDADE_COR = {
    CRITICIDADE_ATRASADO: NEGATIVE, CRITICIDADE_VENCENDO: WARNING,
    CRITICIDADE_EM_DIA: POSITIVE, CRITICIDADE_CONCLUIDO: TEXT_MUTED,
}
_TODOS_TIPOS = "Todos os tipos"
_TODOS_RESPONSAVEIS = "Todos"
_TODAS_PRIORIDADES = "Todas"
_STATUS_PENDENTES = "Pendentes"
_STATUS_CONCLUIDOS = "Concluídos"
_STATUS_TODOS = "Todos"

_CHAVES_FILTRO = ("pp_filtro_busca", "pp_filtro_tipo", "pp_filtro_responsavel", "pp_filtro_prioridade")


def _html(valor: object) -> str:
    """Texto do usuário ou de terceiros (título de reunião do Google, copiado para o prazo
    por "Transformar em prazo") dentro de HTML com `unsafe_allow_html=True`: sempre escapado,
    nunca interpretado como marcação."""

    return html.escape(str(valor))


def _markdown(valor: object) -> str:
    """Como `_html`, para texto que fica fora de bloco HTML (onde o markdown é interpretado):
    também escapa os caracteres de formatação (`**` do título aparecia literal ou quebrava o
    negrito)."""

    return re.sub(r"([\\`*_\[\]{}()#+\-.!|~>])", r"\\\1", _html(valor))


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
        .pp-tipo {{
            font-family: {FONT_HEADING}; font-size: 11px; letter-spacing: .05em;
            text-transform: uppercase; color: {ACCENT};
        }}
        .pp-titulo {{ font-weight: 600; margin: 2px 0 6px; }}
        .pp-desc {{ color: {TEXT_MUTED}; font-size: 12.5px; margin-bottom: 8px; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _badge(texto: str, cor: str) -> str:
    return f"<span class='pp-badge' style='background:{cor}22;color:{cor}'>{texto}</span>"


def _texto_vencimento(row) -> str:
    if row["concluido"]:
        return "Concluído"
    dias = int(row["dias_para_vencer"])
    data_fmt = row["data_prazo"].strftime("%d/%m/%Y")
    if dias < 0:
        return f"Venceu há {abs(dias)}d — {data_fmt}"
    return f"Vence em {dias}d — {data_fmt}"


def _truncar(texto: str, tamanho: int = 90) -> str:
    texto = texto.strip()
    return texto if len(texto) <= tamanho else texto[:tamanho].rstrip() + "…"


def _formulario(prazo_existente, sugestao: dict | None = None) -> None:
    """Campos comuns do formulário de prazo — chamado tanto por `_dialogo_novo` quanto por
    `_dialogo_editar` (só o título do `st.dialog` muda; Streamlit exige um texto estático por
    decorator, não dá pra ter um único dialog com título dinâmico). `sugestao` (evento do
    Google Agenda, botão "Transformar em prazo") só pré-preenche título, data e descrição de
    um prazo NOVO."""

    if prazo_existente is not None:
        prefixo = f"pp_form_{prazo_existente['id']}"
    elif sugestao is not None:
        prefixo = f"pp_form_evento_{sugestao['id']}"
    else:
        prefixo = "pp_form_novo"
    sugestao = sugestao or {}
    titulo = st.text_input(
        "Título do prazo",
        value=prazo_existente["titulo"] if prazo_existente is not None else sugestao.get("titulo", ""),
        placeholder="ex.: Prestação de contas — Convênio 12/2026", key=f"{prefixo}_titulo",
    )
    c1, c2 = st.columns(2)
    tipo = c1.selectbox(
        "Tipo", TIPOS_PRAZO,
        index=TIPOS_PRAZO.index(prazo_existente["tipo"]) if prazo_existente is not None else 1,
        key=f"{prefixo}_tipo",
    )
    categoria = c2.text_input(
        "Categoria", value=prazo_existente["categoria"] if prazo_existente is not None else "",
        placeholder="ex.: SIAFI, PROPLAD", key=f"{prefixo}_categoria",
    )
    c3, c4 = st.columns(2)
    data_prazo = c3.date_input(
        "Vencimento",
        value=prazo_existente["data_prazo"] if prazo_existente is not None else sugestao.get("data_inicio"),
        format="DD/MM/YYYY", key=f"{prefixo}_data",
    )
    prioridade = c4.selectbox(
        "Prioridade", PRIORIDADES_PRAZO,
        index=PRIORIDADES_PRAZO.index(prazo_existente["prioridade"]) if prazo_existente is not None else 1,
        key=f"{prefixo}_prioridade",
    )
    dias_antecedencia = st.number_input(
        "Avisar com (dias de antecedência)", min_value=0,
        value=int(prazo_existente["dias_antecedencia"]) if prazo_existente is not None else DIAS_ANTECEDENCIA_PADRAO,
        step=5, key=f"{prefixo}_antecedencia",
        help="Quantos dias antes do vencimento este prazo específico deve entrar em \"Vencendo\".",
    )
    responsavel = st.text_input(
        "Responsável", value=prazo_existente["responsavel"] if prazo_existente is not None else "",
        key=f"{prefixo}_responsavel",
    )
    descricao = st.text_area(
        "Descrição",
        value=prazo_existente["descricao"] if prazo_existente is not None else sugestao.get("descricao", ""),
        key=f"{prefixo}_descricao",
    )
    concluido = st.checkbox(
        "Concluído", value=bool(prazo_existente["concluido"]) if prazo_existente is not None else False,
        key=f"{prefixo}_concluido",
    )

    if prazo_existente is not None:
        col_excluir, _, col_salvar = st.columns([1, 2, 1])
        with col_excluir.popover("Excluir", use_container_width=True):
            st.write(f"Excluir **{prazo_existente['titulo']}** definitivamente?")
            if st.button("Confirmar exclusão", key=f"{prefixo}_confirmar_exclusao"):
                excluir(prazo_existente["id"])
                st.rerun()
    else:
        col_salvar = st.container()

    if col_salvar.button("Salvar", key=f"{prefixo}_salvar", type="primary",
                          use_container_width=True, icon=":material/save:"):
        try:
            candidato = novo_prazo(titulo, data_prazo, descricao, responsavel,
                                    int(dias_antecedencia), tipo, categoria, prioridade)
        except ErroPrazoOrcamentario as erro:
            st.error(str(erro))
            return
        candidato["concluido"] = bool(concluido)
        if prazo_existente is not None:
            editar(prazo_existente["id"], candidato)
        else:
            salvar(candidato)
        st.rerun()


@st.dialog("Novo prazo")
def _dialogo_novo(sugestao: dict | None = None) -> None:
    _formulario(None, sugestao)


@st.dialog("Editar prazo")
def _dialogo_editar(row) -> None:
    _formulario(row)


def _render_card(row) -> None:
    cor = CRITICIDADE_COR.get(row["criticidade"], TEXT_MUTED)
    chave_card = f"pp_card_{row['id']}"
    with st.container(border=True, key=chave_card):
        if row["concluido"]:
            st.markdown(
                f"<style>.st-key-{chave_card} {{opacity:.55;}}</style>", unsafe_allow_html=True,
            )
        c1, c2 = st.columns([1, 4])
        concluido_novo = c1.checkbox(
            "Concluído", value=bool(row["concluido"]), key=f"pp_check_{row['id']}",
            label_visibility="collapsed",
        )
        c2.markdown(f"<div style='text-align:right'>{_badge(row['criticidade'], cor)}</div>", unsafe_allow_html=True)
        if concluido_novo != row["concluido"]:
            editar(row["id"], {"concluido": bool(concluido_novo)})
            st.rerun()

        rotulo_tipo = row["tipo"] + (f" · {row['categoria']}" if row["categoria"] else "")
        st.markdown(f"<div class='pp-tipo'>{_html(rotulo_tipo)}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='pp-titulo'>{_html(row['titulo'])}</div>", unsafe_allow_html=True)
        if row["descricao"]:
            st.markdown(f"<div class='pp-desc'>{_html(_truncar(row['descricao']))}</div>", unsafe_allow_html=True)

        c3, c4 = st.columns(2)
        # <span> no início da linha não abre bloco HTML: o markdown é interpretado → `_markdown`
        c3.markdown(f"<span style='font-size:12px'>{_markdown(_dash(row['responsavel']))}</span>", unsafe_allow_html=True)
        c4.markdown(
            f"<div style='text-align:right;font-size:12px;color:{cor}'>{_texto_vencimento(row)}</div>",
            unsafe_allow_html=True,
        )
        if st.button("Editar", key=f"pp_editar_{row['id']}", use_container_width=True, icon=":material/edit:"):
            _dialogo_editar(row)


# ---------------------------------------------------------------------- página
_FUSO = ZoneInfo(google_agenda.FUSO)
_RESPOSTAS = {"accepted": "Aceito", "declined": "Recusado", "tentative": "Talvez", "needsAction": "Pendente"}


@st.cache_data(ttl=300, show_spinner=False)
def _eventos_proximos(dias: int = 30) -> list[dict]:
    """Cache de 5 min: o Streamlit reexecuta a página a cada clique."""

    agora = datetime.now(_FUSO)
    return google_agenda.cliente().listar_eventos(agora, agora + timedelta(days=dias))


def _executar_sincronizacao() -> None:
    """A tentativa é registrada ANTES de sincronizar: sem rede, uma falha não pode fazer cada
    clique da página chamar a API de novo (limite de 5 min vale para tentativas). O erro fica
    na sessão para o aviso continuar visível durante o intervalo."""

    st.session_state["pp_google_ultima_sync"] = datetime.now(_FUSO)
    try:
        resumo = prazos_sincronizacao.sincronizar(google_agenda.cliente())
    except (ErroGoogleAgenda, prazos_sincronizacao.ErroSincronizacao) as erro:
        st.session_state["pp_google_erro_sync"] = str(erro)
        return
    st.session_state.pop("pp_google_erro_sync", None)
    try:
        prazos_sincronizacao.salvar_resumo(resumo)
    except OSError as erro:
        # a sincronização já foi feita; só o registro em disco falhou (ex.: arquivo aberto)
        st.session_state["pp_google_aviso"] = (
            f"Sincronização feita, mas o resumo não pôde ser gravado ({erro}). "
            "Ele será gravado na próxima sincronização."
        )
    _eventos_proximos.clear()


def _render_resumo_sincronizacao() -> None:
    resumo = prazos_sincronizacao.carregar_ultimo_resumo()
    if resumo is None:
        st.caption("Ainda não sincronizado.")
        return
    quando = datetime.fromisoformat(resumo["executado_em"]).astimezone(_FUSO).strftime("%d/%m/%Y %H:%M")
    partes = [
        f"{len(resumo['criados'])} criado(s)",
        f"{len(resumo['atualizados_no_google'])} atualizado(s) no Google",
        f"{len(resumo['atualizados_no_budgetlab'])} atualizado(s) aqui",
        f"{len(resumo['concluidos_por_exclusao'])} concluído(s) por exclusão no Google",
        f"{len(resumo['eventos_excluidos'])} evento(s) excluído(s)",
    ]
    st.caption(f"Última sincronização: {quando} — " + " · ".join(partes))
    if resumo["conflitos"] or resumo["erros"]:
        with st.expander(f"{len(resumo['conflitos'])} conflito(s) · {len(resumo['erros'])} erro(s)"):
            for conflito in resumo["conflitos"]:
                st.markdown(
                    f"**{conflito['titulo']}** — venceu {conflito['vencedor']}. "
                    f"BudgetLab: `{conflito['valor_budgetlab']}` · Google: `{conflito['valor_google']}`"
                )
            for erro in resumo["erros"]:
                st.markdown(f"- {erro}")
            st.caption(
                "Histórico de todas as sincronizações com alteração, conflito ou erro em "
                f"'{google_agenda.DIRETORIO_PADRAO / prazos_sincronizacao.ARQUIVO_HISTORICO}'."
            )


def _render_conexao() -> str:
    """Bloco "Google Agenda". Devolve a situação da conexão."""

    situacao = google_agenda.situacao_conexao()
    with st.container(border=True):
        st.markdown("<div class='pp-label'>Google Agenda</div>", unsafe_allow_html=True)
        if "pp_google_aviso" in st.session_state:
            render_alert(st.session_state.pop("pp_google_aviso"), "warning")
        if situacao == "sem_credenciais":
            st.markdown(
                "Integração não configurada. Siga o passo a passo em `docs/google_agenda.md` "
                f"e coloque o `credentials.json` em `{google_agenda.DIRETORIO_PADRAO}`."
            )
        elif situacao == "desconectado":
            if st.button("Conectar ao Google Agenda", icon=":material/link:"):
                try:
                    google_agenda.conectar()
                except ErroGoogleAgenda as erro:
                    render_alert(str(erro), "error")
                else:
                    _eventos_proximos.clear()
                    st.rerun()
        else:
            ultima = st.session_state.get("pp_google_ultima_sync")
            if prazos_sincronizacao.sincronizacao_devida(ultima, datetime.now(_FUSO)):
                _executar_sincronizacao()
            c1, c2 = st.columns([1, 1])
            if c1.button("Sincronizar agora", icon=":material/sync:", use_container_width=True):
                _executar_sincronizacao()
                st.rerun()
            if c2.button("Desconectar", icon=":material/link_off:", use_container_width=True):
                if not google_agenda.desconectar():
                    # o token local já foi apagado; só a revogação no Google não foi confirmada
                    st.session_state["pp_google_aviso"] = (
                        "Desconectado neste computador, mas o Google não confirmou a revogação do "
                        "acesso (sem internet?). Para garantir, remova o \"UFRPE BudgetLab\" em "
                        "https://myaccount.google.com/permissions."
                    )
                st.session_state.pop("pp_google_erro_sync", None)
                _eventos_proximos.clear()
                st.rerun()
            if "pp_google_erro_sync" in st.session_state:
                render_alert(
                    f"Sincronização com o Google Agenda não realizada: {st.session_state['pp_google_erro_sync']}",
                    "error",
                )
            if "pp_google_aviso" in st.session_state:  # gerado pela sincronização logo acima
                render_alert(st.session_state.pop("pp_google_aviso"), "warning")
            _render_resumo_sincronizacao()
    return situacao


def _render_agenda() -> None:
    with st.expander("Agenda — próximos 30 dias", expanded=False):
        try:
            eventos = _eventos_proximos()
        except ErroGoogleAgenda as erro:
            render_alert(str(erro), "error")
            return
        if not eventos:
            st.info("Nenhum evento nos próximos 30 dias.")
            return
        dia_atual = None
        for evento in eventos:
            if evento["data_inicio"] != dia_atual:
                dia_atual = evento["data_inicio"]
                st.markdown(f"<div class='pp-label'>{dia_atual.strftime('%d/%m/%Y')}</div>", unsafe_allow_html=True)
            e_prazo = evento["prazo_id"] is not None
            rotulo = _badge("Prazo", ACCENT) if e_prazo else _badge("Reunião/evento", TEXT_MUTED)
            horario = "Dia inteiro" if evento["hora_inicio"] is None else evento["hora_inicio"].strftime("%H:%M")
            detalhes = [horario]
            if not e_prazo and evento["organizador"]:
                detalhes.append(evento["organizador"])
            if evento["minha_resposta"]:
                detalhes.append(_RESPOSTAS.get(evento["minha_resposta"], evento["minha_resposta"]))
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            # título e organizador vêm de terceiros (convites): sempre texto, nunca marcação
            c1.markdown(
                f"{rotulo} **{_markdown(evento['titulo'].strip() or '(sem título)')}** "
                f"<span style='color:{TEXT_MUTED};font-size:12px'>{' · '.join(_markdown(d) for d in detalhes)}</span>",
                unsafe_allow_html=True,
            )
            if not e_prazo and c2.button("Transformar em prazo", key=f"pp_evento_{evento['id']}",
                                          use_container_width=True):
                _dialogo_novo(evento)


_inject_css()

col_titulo, col_botao = st.columns([5, 1], vertical_alignment="bottom")
with col_titulo:
    render_page_header(
        "Gerenciamento de Prazos",
        "Cadastre um prazo do exercício e acompanhe o alerta conforme a data se aproxima.",
        "Prazos",
    )
with col_botao:
    if st.button("+ Novo prazo", type="primary", use_container_width=True, icon=":material/add_alert:"):
        _dialogo_novo()

situacao_google = _render_conexao()
if situacao_google == "conectado":
    _render_agenda()

prazos_brutos = carregar_prazos()
prazos = prazos_com_criticidade(prazos_brutos)

if prazos.empty:
    st.info("Nenhum prazo cadastrado ainda — use \"+ Novo prazo\" para começar.")
    st.stop()

pendentes = prazos[~prazos["concluido"]]
atrasados = int((pendentes["criticidade"] == CRITICIDADE_ATRASADO).sum())
vencendo = int((pendentes["criticidade"] == CRITICIDADE_VENCENDO).sum())

if atrasados:
    render_alert(f"{atrasados} prazo(s) atrasado(s) sem conclusão.", "error")
elif vencendo:
    render_alert(f"{vencendo} prazo(s) vencendo — dentro da antecedência escolhida para cada um.", "warning")
else:
    render_alert("Nenhum prazo pendente atrasado ou dentro da antecedência de alerta.", "success")

render_metric_grid(
    [
        {"label": "Prazos pendentes", "value": str(len(pendentes))},
        {"label": "Atrasados", "value": str(atrasados)},
        {"label": "Vencendo", "value": str(vencendo)},
        {"label": "Concluídos", "value": str(int(prazos["concluido"].sum()))},
    ],
    columns=4,
)

# --- filtros (sempre visíveis, uma linha) -----------------------------------
opcoes_responsavel = sorted({r for r in prazos["responsavel"] if r})

c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1], vertical_alignment="bottom")
busca = c1.text_input("Busca", key="pp_filtro_busca", placeholder="Título ou categoria...")
tipo_filtro = c2.selectbox("Tipo", [_TODOS_TIPOS, *TIPOS_PRAZO], key="pp_filtro_tipo")
responsavel_filtro = c3.selectbox("Responsável", [_TODOS_RESPONSAVEIS, *opcoes_responsavel], key="pp_filtro_responsavel")
prioridade_filtro = c4.selectbox("Prioridade", [_TODAS_PRIORIDADES, *PRIORIDADES_PRAZO], key="pp_filtro_prioridade")
if c5.button("Limpar", use_container_width=True):
    for chave in _CHAVES_FILTRO:
        st.session_state.pop(chave, None)
    st.rerun()

status_tab = st.segmented_control(
    "Status", [_STATUS_PENDENTES, _STATUS_CONCLUIDOS, _STATUS_TODOS],
    default=_STATUS_PENDENTES, key="pp_status_tab", label_visibility="collapsed",
)
status_tab = status_tab or _STATUS_PENDENTES

if status_tab == _STATUS_PENDENTES:
    base_status = prazos[~prazos["concluido"]]
elif status_tab == _STATUS_CONCLUIDOS:
    base_status = prazos[prazos["concluido"]]
else:
    base_status = prazos

visiveis = base_status
if busca.strip():
    termo = busca.strip().lower()
    visiveis = visiveis[
        visiveis["titulo"].str.lower().str.contains(termo, regex=False)
        | visiveis["categoria"].str.lower().str.contains(termo, regex=False)
    ]
if tipo_filtro != _TODOS_TIPOS:
    visiveis = visiveis[visiveis["tipo"] == tipo_filtro]
if responsavel_filtro != _TODOS_RESPONSAVEIS:
    visiveis = visiveis[visiveis["responsavel"] == responsavel_filtro]
if prioridade_filtro != _TODAS_PRIORIDADES:
    visiveis = visiveis[visiveis["prioridade"] == prioridade_filtro]

st.caption(f"{len(visiveis)} de {len(base_status)} prazos exibidos")

# --- grade de cards -----------------------------------------------------------
if visiveis.empty:
    st.info("Nenhum prazo encontrado para os filtros atuais.")
else:
    colunas = st.columns(3)
    for indice, (_, row) in enumerate(visiveis.iterrows()):
        with colunas[indice % 3]:
            _render_card(row)

st.caption(
    f"Cadastro manual, persistido em '{DIRETORIO_PADRAO}' — sobrevive a reiniciar o app. "
    "Não deriva de Contratos nem de Bolsas: cada prazo é registrado aqui, um a um, com sua "
    "própria antecedência de alerta."
)
