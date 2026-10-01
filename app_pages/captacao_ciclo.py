"""Captação de Demandas — "Ciclo" (Etapa 0: fundação, somente leitura).

Mostra o ciclo de captação em `data/captacao/captacao.db` (fase calculada pela data,
datas e contagem de demandas por situação). Ainda não há cadastro de ciclo, unidades nem
demandas por esta interface — chegam nas etapas seguintes do plano. Sem o banco ou sem
ciclo cadastrado, a página diz isso em vez de falhar.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from src.captacao import regras
from src.captacao.schema import CAMINHO_BANCO_PADRAO, conectar
from src.ui_theme import render_page_header

FASE_ROTULOS = {
    "RASCUNHO": "Rascunho (em preparação)",
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


def _data(texto: str | None) -> date | None:
    return date.fromisoformat(texto) if texto else None


def _formatar(dia: date | None) -> str:
    return dia.strftime("%d/%m/%Y") if dia else "—"


render_page_header(
    "Captação de Demandas — Ciclo",
    "Período de captação das demandas das unidades para a Proposta Orçamentária.",
    "Captação",
)

if not CAMINHO_BANCO_PADRAO.exists():
    st.info("A base da Captação de Demandas ainda não foi criada: nenhum ciclo cadastrado.")
    st.stop()

conexao = conectar()
try:
    ciclos = conexao.execute("SELECT * FROM ciclo ORDER BY exercicio DESC").fetchall()
    if not ciclos:
        st.info("Nenhum ciclo de captação cadastrado.")
        st.stop()

    ciclo = ciclos[0]
    hoje = date.today()
    abertura, encerramento = _data(ciclo["abertura"]), _data(ciclo["encerramento"])
    fase = regras.fase_por_data(ciclo["fase"], abertura, encerramento, hoje)

    with st.container(border=True):
        st.subheader(f"Ciclo de captação {ciclo['exercicio']}")
        st.caption(f"Fase: {FASE_ROTULOS.get(fase, fase)}")
        colunas = st.columns(4)
        colunas[0].metric("Abertura do registro", _formatar(abertura))
        colunas[1].metric("Encerramento do registro", _formatar(encerramento))
        colunas[2].metric("Validação pela chefia até", _formatar(_data(ciclo["prazo_validacao"])))
        colunas[3].metric("Devolutiva prevista", _formatar(_data(ciclo["devolutiva_prevista"])))

    with st.container(border=True):
        st.subheader("Demandas por situação")
        contagens = {
            linha["situacao"]: linha["total"]
            for linha in conexao.execute(
                "SELECT situacao, COUNT(*) AS total FROM demanda"
                " WHERE ciclo_id = ? AND excluida_em IS NULL GROUP BY situacao",
                (ciclo["id"],),
            )
        }
        colunas = st.columns(len(SITUACAO_ROTULOS))
        for coluna, (situacao, rotulo) in zip(colunas, SITUACAO_ROTULOS.items()):
            coluna.metric(rotulo, contagens.get(situacao, 0))
finally:
    conexao.close()
