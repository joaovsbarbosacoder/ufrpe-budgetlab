"""Captação de Demandas — "Ciclo" (Etapa 4): cadastro e acompanhamento do ciclo de captação.

Permite criar e editar o ciclo (datas, versões dos planos, regras, avisos), agendar, abrir e
encerrar manualmente e conceder prorrogação por unidade. A fase exibida é a EFETIVA
(armazenada + data, ver `src/captacao/ciclos.py`). Toda alteração exige o responsável e vai
ao histórico. O envio dos avisos por e-mail ainda não existe: os interruptores só são guardados.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src.captacao import auditoria, ciclos, unidades
from src.captacao.auditoria import ErroCadastro
from src.captacao.schema import conectar
from src.ui_theme import render_page_header

FASE_ROTULOS = {
    "RASCUNHO": "Em preparação",
    "AGENDADO": "Agendado",
    "ABERTO": "Aberto",
    "ENCERRADO": "Encerrado",
    "EM_ANALISE": "Em análise",
    "CONCLUIDO": "Concluído",
}
SITUACAO_ROTULOS = {
    "RASCUNHO": "Rascunho",
    "ENVIADA": "Enviada",
    "VALIDADA_CHEFIA": "Validada pela chefia",
    "VALIDADA_PROPLAD": "Validada pela PROPLAD",
    "INCLUIDA_PROPOSTA": "Incluída na proposta",
    "NAO_INCLUIDA": "Não incluída",
}
AVISO_ROTULOS = {
    "abertura": "E-mail aos representantes na abertura",
    "sete_dias": "Lembrete 7 dias antes do encerramento",
    "dois_dias": "Lembrete 2 dias antes, só para quem não enviou",
    "aviso_chefia": "Aviso às chefias quando houver demanda aguardando validação",
    "dia_encerramento": "Aviso no dia do encerramento",
}
SEM_VERSAO = "(nenhuma)"


def _data(texto: str | None) -> date | None:
    return date.fromisoformat(texto) if texto else None


def _formatar(dia: date | None) -> str:
    return dia.strftime("%d/%m/%Y") if dia else "—"


def _mostrar_erros(erro: ErroCadastro) -> None:
    for motivo in erro.erros:
        st.error(motivo)


def _campos_ciclo(conexao, chave: str, ciclo=None) -> dict:
    """Widgets dos dados editáveis do ciclo (dentro de um `st.form`); devolve o dict para o serviço."""

    def _valor_data(coluna):
        return _data(ciclo[coluna]) if ciclo is not None else None

    colunas = st.columns(2)
    datas = {
        "abertura": colunas[0].date_input("Abertura do registro", value=_valor_data("abertura"), format="DD/MM/YYYY", key=f"{chave}_abertura"),
        "encerramento": colunas[1].date_input("Encerramento do registro", value=_valor_data("encerramento"), format="DD/MM/YYYY", key=f"{chave}_encerramento"),
        "prazo_validacao": colunas[0].date_input("Validação pela chefia até", value=_valor_data("prazo_validacao"), format="DD/MM/YYYY", key=f"{chave}_validacao"),
        "devolutiva_prevista": colunas[1].date_input("Devolutiva prevista", value=_valor_data("devolutiva_prevista"), format="DD/MM/YYYY", key=f"{chave}_devolutiva"),
    }
    versoes_pdi = [SEM_VERSAO, *[r[0] for r in conexao.execute("SELECT DISTINCT versao_pdi FROM objetivo_pdi ORDER BY 1")]]
    versoes_pls = [SEM_VERSAO, *[r[0] for r in conexao.execute("SELECT DISTINCT versao_pls FROM meta_pls ORDER BY 1")]]

    def _indice(opcoes, valor):
        return opcoes.index(valor) if valor in opcoes else 0

    atual_pdi = ciclo["versao_pdi"] if ciclo is not None else None
    atual_pls = ciclo["versao_pls"] if ciclo is not None else None
    versao_pdi = colunas[0].selectbox("Versão do PDI", versoes_pdi, index=_indice(versoes_pdi, atual_pdi), key=f"{chave}_vpdi")
    versao_pls = colunas[1].selectbox("Versão do PLS", versoes_pls, index=_indice(versoes_pls, atual_pls), key=f"{chave}_vpls")

    permite = st.checkbox(
        "Permitir rascunhos antes da abertura",
        value=bool(ciclo["permite_rascunho_antecipado"]) if ciclo is not None else False,
        key=f"{chave}_antecipado",
    )
    somente_leitura = st.checkbox(
        "Após o encerramento, setores ficam em modo somente consulta",
        value=bool(ciclo["somente_leitura_apos"]) if ciclo is not None else True,
        key=f"{chave}_leitura",
    )
    guardados = ciclos.avisos_do_ciclo(ciclo) if ciclo is not None else ciclos.avisos_padrao()
    st.caption("Avisos automáticos (o envio por e-mail ainda não está implementado: os interruptores só ficam guardados).")
    avisos = {chave_aviso: st.checkbox(rotulo, value=guardados[chave_aviso], key=f"{chave}_aviso_{chave_aviso}") for chave_aviso, rotulo in AVISO_ROTULOS.items()}
    mensagem = st.text_area(
        "Mensagem de abertura (texto do e-mail)",
        value=(ciclo["mensagem_abertura"] or "") if ciclo is not None else "",
        key=f"{chave}_mensagem",
    )
    return {
        **datas,
        "versao_pdi": None if versao_pdi == SEM_VERSAO else versao_pdi,
        "versao_pls": None if versao_pls == SEM_VERSAO else versao_pls,
        "permite_rascunho_antecipado": permite,
        "somente_leitura_apos": somente_leitura,
        "avisos": avisos,
        "mensagem_abertura": mensagem,
    }


def _tabela_historico(registros) -> None:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Quando (UTC)": r["criado_em"][:19].replace("T", " "),
                    "Ação": r["acao"],
                    "Campo": r["campo"],
                    "Antes": r["antes"],
                    "Depois": r["depois"],
                    "Responsável": r["usuario"],
                }
                for r in registros
            ]
        ),
        hide_index=True,
        width="stretch",
    )


render_page_header(
    "Captação de Demandas — Ciclo",
    "Período de captação das demandas das unidades para a Proposta Orçamentária.",
    "Captação",
)

conexao = conectar()
try:
    hoje = date.today()
    responsavel = st.text_input(
        "Responsável pelas alterações",
        placeholder="Seu nome (registrado no histórico)",
        key="captacao_ciclo_responsavel",
    )
    sem_responsavel = not responsavel.strip()
    if sem_responsavel:
        st.info("Informe o responsável pelas alterações para criar, editar ou mudar a fase do ciclo.")

    todos = ciclos.listar_ciclos(conexao)

    with st.expander("Novo ciclo", expanded=not todos):
        with st.form(key="captacao_ciclo_novo"):
            exercicio = st.number_input("Exercício", min_value=2000, max_value=2100, value=hoje.year + 1, step=1, key="captacao_ciclo_novo_exercicio")
            dados_novo = _campos_ciclo(conexao, "captacao_ciclo_novo")
            criar = st.form_submit_button("Criar ciclo", type="primary", disabled=sem_responsavel)
        if criar:
            try:
                ciclos.criar_ciclo(conexao, int(exercicio), dados_novo, responsavel)
            except ErroCadastro as erro:
                _mostrar_erros(erro)
            else:
                st.toast(f"Ciclo {int(exercicio)} criado (em preparação).")
                st.rerun()

    if not todos:
        st.info("Nenhum ciclo de captação cadastrado. Crie o primeiro acima.")
        st.stop()

    por_id = {c["id"]: c for c in todos}
    ciclo_id = st.selectbox("Ciclo", list(por_id), format_func=lambda i: f"Ciclo {por_id[i]['exercicio']}", key="captacao_ciclo_selecao")
    ciclo = por_id[ciclo_id]
    fase = ciclos.fase_efetiva(ciclo, hoje)

    with st.container(border=True):
        st.subheader(f"Ciclo de captação {ciclo['exercicio']}")
        st.caption(f"Fase: {FASE_ROTULOS.get(fase, fase)}" + (f" (armazenada: {FASE_ROTULOS[ciclo['fase']]})" if fase != ciclo["fase"] else ""))
        colunas = st.columns(4)
        colunas[0].metric("Abertura do registro", _formatar(_data(ciclo["abertura"])))
        colunas[1].metric("Encerramento do registro", _formatar(_data(ciclo["encerramento"])))
        colunas[2].metric("Validação pela chefia até", _formatar(_data(ciclo["prazo_validacao"])))
        colunas[3].metric("Devolutiva prevista", _formatar(_data(ciclo["devolutiva_prevista"])))
        if not ciclo["versao_pdi"] or not ciclo["versao_pls"]:
            st.warning("Escolha as versões do PDI e do PLS (Planos de Referência) para as demandas poderem ser vinculadas.")

        acoes = st.columns(3)
        pode_agendar = ciclo["fase"] == "RASCUNHO"
        pode_abrir = ciclo["fase"] in ("RASCUNHO", "AGENDADO")
        pode_encerrar = ciclo["fase"] in ("AGENDADO", "ABERTO") and fase == "ABERTO"
        for coluna, rotulo, habilitado, acao in (
            (acoes[0], "Agendar ciclo", pode_agendar, lambda: ciclos.agendar_ciclo(conexao, ciclo_id, responsavel)),
            (acoes[1], "Abrir registro agora", pode_abrir, lambda: ciclos.abrir_agora(conexao, ciclo_id, responsavel, hoje)),
            (acoes[2], "Encerrar registro agora", pode_encerrar, lambda: ciclos.encerrar_agora(conexao, ciclo_id, responsavel, hoje)),
        ):
            if coluna.button(rotulo, disabled=sem_responsavel or not habilitado, key=f"captacao_ciclo_acao_{ciclo_id}_{rotulo}", width="stretch"):
                try:
                    acao()
                except ErroCadastro as erro:
                    _mostrar_erros(erro)
                else:
                    st.toast(f"{rotulo}: feito.")
                    st.rerun()

    with st.container(border=True):
        st.subheader("Demandas por situação")
        contagens = {
            linha["situacao"]: linha["total"]
            for linha in conexao.execute(
                "SELECT situacao, COUNT(*) AS total FROM demanda WHERE ciclo_id = ? AND excluida_em IS NULL GROUP BY situacao",
                (ciclo_id,),
            )
        }
        for coluna, (situacao, rotulo) in zip(st.columns(len(SITUACAO_ROTULOS)), SITUACAO_ROTULOS.items()):
            coluna.metric(rotulo, contagens.get(situacao, 0))

    with st.container(border=True):
        st.subheader("Editar ciclo")
        st.caption(
            "Com o ciclo aberto a data de abertura fica travada; depois do encerramento também a de encerramento. "
            "Para dar mais prazo a uma unidade, use a prorrogação abaixo."
        )
        with st.form(key=f"captacao_ciclo_editar_{ciclo_id}"):
            dados_edicao = _campos_ciclo(conexao, f"captacao_ciclo_edit_{ciclo_id}", ciclo)
            salvar = st.form_submit_button("Salvar alterações", type="primary", disabled=sem_responsavel)
        if salvar:
            try:
                alterados = ciclos.editar_ciclo(conexao, ciclo_id, dados_edicao, responsavel, hoje)
            except ErroCadastro as erro:
                _mostrar_erros(erro)
            else:
                st.success(f"Alterado: {', '.join(alterados)}." if alterados else "Nenhuma alteração a gravar.")
        with st.expander("Histórico deste ciclo"):
            _tabela_historico(auditoria.historico(conexao, "ciclo", ciclo_id))

    with st.container(border=True):
        st.subheader("Prorrogações por unidade")
        st.caption("Prazo individual, sem reabrir para todos. Motivo obrigatório; uma prorrogação por unidade.")
        existentes = ciclos.listar_prorrogacoes(conexao, ciclo_id)
        if existentes:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "UGR": p["ugr_codigo"],
                            "Unidade": p["unidade_nome"],
                            "Novo prazo": _formatar(_data(p["novo_prazo"])),
                            "Motivo": p["motivo"],
                            "Concedida por": p["concedida_por"],
                        }
                        for p in existentes
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("Nenhuma prorrogação concedida neste ciclo.")

        com_prorrogacao = {p["unidade_id"] for p in existentes}
        candidatas = [u for u in unidades.listar_unidades(conexao, apenas_ativas=True) if u["id"] not in com_prorrogacao]
        if not unidades.listar_unidades(conexao, apenas_ativas=True):
            st.info("Cadastre as unidades na página \"Unidades da Captação\" para poder prorrogar.")
        elif candidatas:
            with st.form(key=f"captacao_prorrogar_{ciclo_id}", clear_on_submit=True):
                unidade_id = st.selectbox(
                    "Unidade", [u["id"] for u in candidatas],
                    format_func={u["id"]: f"{u['ugr_codigo']} — {u['nome']}" for u in candidatas}.get,
                )
                novo_prazo = st.date_input("Novo prazo", value=None, format="DD/MM/YYYY")
                motivo = st.text_input("Motivo")
                conceder = st.form_submit_button("Conceder prorrogação", disabled=sem_responsavel)
            if conceder:
                try:
                    ciclos.conceder_prorrogacao(conexao, ciclo_id, unidade_id, novo_prazo, motivo, responsavel)
                except ErroCadastro as erro:
                    _mostrar_erros(erro)
                else:
                    st.toast("Prorrogação concedida.")
                    st.rerun()

        if existentes:
            with st.expander("Alterar prorrogação existente"):
                por_prorrogacao = {p["id"]: p for p in existentes}
                prorrogacao_id = st.selectbox(
                    "Prorrogação", list(por_prorrogacao),
                    format_func=lambda i: f"{por_prorrogacao[i]['ugr_codigo']} — {por_prorrogacao[i]['unidade_nome']}",
                    key=f"captacao_prorrogacao_sel_{ciclo_id}",
                )
                atual = por_prorrogacao[prorrogacao_id]
                with st.form(key=f"captacao_prorrogacao_form_{prorrogacao_id}"):
                    prazo_alterado = st.date_input("Novo prazo", value=_data(atual["novo_prazo"]), format="DD/MM/YYYY")
                    motivo_alterado = st.text_input("Motivo", value=atual["motivo"])
                    alterar = st.form_submit_button("Salvar prorrogação", disabled=sem_responsavel)
                if alterar:
                    try:
                        alterados = ciclos.alterar_prorrogacao(conexao, prorrogacao_id, prazo_alterado, motivo_alterado, responsavel)
                    except ErroCadastro as erro:
                        _mostrar_erros(erro)
                    else:
                        st.success(f"Alterado: {', '.join(alterados)}." if alterados else "Nenhuma alteração a gravar.")
                _tabela_historico(auditoria.historico(conexao, "prorrogacao", prorrogacao_id))
finally:
    conexao.close()
