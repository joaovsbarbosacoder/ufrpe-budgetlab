"""Atualizar Planilhas — único lugar do app para atualizar qualquer base a partir de um
arquivo novo, versionada ou não (pedido explícito: "um lugar só pra receber as planilhas
atualizadas").

Duas famílias de base, cada uma com sua própria mecânica, mas juntas nesta página:

  * Execução Anual e Dotação Anual — importação VERSIONADA (manifesto, detecção de
    retroatividade/exercício removido, ver `src/importacao_versionada.py`). Reaproveita o
    componente já existente `src/ui_reimportacao.py::render_reimportacao`, que morava embutido
    no fim das páginas de análise "Execução Orçamentária"/"Dotação Orçamentária" (removidas em
    22/09/2026, pedido do usuário — ver histórico do git se precisar da referência) — as
    especificações agora vivem em `src/reimportacao_especificacoes.py` (só assim dá pra
    importar sem rodar a página de análise inteira como efeito colateral do import).
  * Contratos Contínuos, Bolsas e Auxílios, Contratos — Vigência, Contratos — Pagamentos —
    planilhas de trabalho SEM reimportação versionada (sem manifesto, sem detecção de delta).
    Cada envio é validado com o leitor da própria base antes de aceitar
    (`src/atualizar_planilhas.py::substituir_planilha`) — layout errado é rejeitado sem tocar
    no arquivo atual. A versão anterior é sempre preservada em `data/raw/_backup/` com carimbo
    de data/hora, nunca apagada.

Padrão de "mensagem sobrevive a um rerun" + key com contador (mesma família do truque de
geração usado em `src/ui_relatorio_reforco_empenho.py` para o `st.data_editor` dentro de um
`st.dialog`): sem isso, ou a mensagem de sucesso não aparece (o rerun acontece rápido demais
pro navegador mostrar o que foi renderizado antes dele) ou o `st.file_uploader` continua
mostrando o arquivo já processado depois do sucesso.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st

from src.atualizar_planilhas import ESPECIFICACOES, EspecificacaoBase, substituir_planilha
from src.importacao_dotacao import Manifesto as ManifestoDotacao
from src.importacao_dotacao import situacao_historico as situacao_historico_dotacao
from src.importacao_execucao import Manifesto as ManifestoExecucao
from src.importacao_execucao import situacao_historico as situacao_historico_execucao
from src.importacao_execucao_mensal import Manifesto as ManifestoExecucaoMensal
from src.importacao_execucao_mensal import situacao_historico as situacao_historico_execucao_mensal
from src.reimportacao_especificacoes import (
    ESPECIFICACAO_DOTACAO_ANUAL,
    ESPECIFICACAO_EXECUCAO_ANUAL,
    ESPECIFICACAO_EXECUCAO_MENSAL,
)
from src.ui_reimportacao import render_reimportacao
from src.ui_theme import render_page_header

render_page_header(
    "Atualizar Planilhas",
    "Único lugar do app para enviar uma planilha nova, versionada ou não. Cada envio é validado antes de aceitar.",
    "Administração",
)

st.subheader("Bases com reimportação versionada")
st.caption(
    "Execução Anual, Dotação Anual e Execução Mensal — manifesto próprio, com detecção de "
    "retroatividade e exercício removido antes de aplicar."
)


def _info_manifesto_atual(manifesto) -> str:
    if manifesto is None:
        return "nenhuma extração importada ainda"
    data = datetime.fromisoformat(manifesto.data_extracao).strftime("%d/%m/%Y")
    return f"extração atual: `{manifesto.arquivo}` · data da extração: {data}"


def _render_card_versionado(nome: str, manifesto_atual, spec, procedencia=None) -> None:
    with st.container(border=True):
        st.subheader(nome)
        st.caption(_info_manifesto_atual(manifesto_atual))
        if procedencia is not None:
            procedencia(spec)
        render_reimportacao(spec)


def _render_procedencia(situacao_historico, nome_base: str, spec) -> None:
    situacao = situacao_historico(spec.diretorio_dados_brutos, spec.diretorio_manifestos)
    if situacao.empty:
        return
    ausentes = situacao[~situacao["arquivo_presente"]]
    if not ausentes.empty:
        st.error(
            "Arquivo de origem ausente em data/raw/ — exercício(s) "
            + ", ".join(map(str, ausentes["exercicio"]))
            + f": as páginas que leem a {nome_base} vão falhar até o arquivo ser restaurado "
            "ou esses exercícios serem reimportados."
        )
    with st.expander("Procedência por exercício"):
        tabela = situacao.copy()
        tabela["data_extracao"] = tabela["data_extracao"].map(
            lambda valor: datetime.fromisoformat(valor).strftime("%d/%m/%Y")
        )
        tabela["arquivo_presente"] = tabela["arquivo_presente"].map({True: "sim", False: "AUSENTE"})
        st.dataframe(
            tabela.rename(
                columns={
                    "exercicio": "Exercício",
                    "data_extracao": "Data da extração",
                    "sha256_curto": "Hash",
                    "arquivo": "Arquivo",
                    "arquivo_presente": "Arquivo presente",
                }
            ),
            hide_index=True,
            width="stretch",
        )


_render_card_versionado(
    "Execução Orçamentária (Execução Anual)",
    ManifestoExecucao.atual(),
    ESPECIFICACAO_EXECUCAO_ANUAL,
    procedencia=lambda spec: _render_procedencia(situacao_historico_execucao, "Execução Anual", spec),
)
_render_card_versionado(
    "Dotação Orçamentária (Dotação Anual)",
    ManifestoDotacao.atual(),
    ESPECIFICACAO_DOTACAO_ANUAL,
    procedencia=lambda spec: _render_procedencia(situacao_historico_dotacao, "Dotação Anual", spec),
)
_render_card_versionado(
    "Execução Mensal",
    ManifestoExecucaoMensal.atual(),
    ESPECIFICACAO_EXECUCAO_MENSAL,
    procedencia=lambda spec: _render_procedencia(situacao_historico_execucao_mensal, "Execução Mensal", spec),
)

st.subheader("Planilhas de trabalho")
st.caption(
    "Contratos Contínuos, Bolsas e Auxílios, Contratos — Vigência, Contratos — Pagamentos e "
    "Liquidação por Competência — sem reimportação versionada: cada envio substitui o arquivo "
    "inteiro, com a versão anterior preservada em data/raw/_backup/."
)


def _fmt_mtime(caminho: Path) -> str:
    if not caminho.exists():
        return "arquivo não encontrado"
    return datetime.fromtimestamp(caminho.stat().st_mtime).strftime("%d/%m/%Y %H:%M")


def _render_card(spec: EspecificacaoBase) -> None:
    with st.container(border=True):
        st.subheader(spec.nome)
        st.caption(f"Arquivo atual: `{spec.caminho.name}` · última atualização: {_fmt_mtime(spec.caminho)}")

        mensagem_key = f"atualizar_planilhas_mensagem_{spec.chave}"
        mensagem = st.session_state.pop(mensagem_key, None)
        if mensagem is not None:
            st.success(mensagem)

        # a key do uploader muda a cada substituição bem-sucedida (contador "versao"), pra
        # ele voltar a ficar vazio depois de processar um arquivo — sem isso o widget
        # continuaria mostrando o arquivo já aceito indefinidamente (mesmo gotcha de
        # `st.data_editor` ignorar novo dado semeado numa key já usada).
        versao_key = f"atualizar_planilhas_versao_{spec.chave}"
        versao = st.session_state.setdefault(versao_key, 0)

        enviado = st.file_uploader(
            f"Nova planilha (.{spec.extensao})",
            type=[spec.extensao],
            key=f"atualizar_planilhas_upload_{spec.chave}_{versao}",
            label_visibility="collapsed",
        )
        if enviado is None:
            return

        if not st.button("Substituir planilha", key=f"atualizar_planilhas_confirmar_{spec.chave}_{versao}"):
            st.info('Arquivo selecionado. Clique em "Substituir planilha" para confirmar.')
            return

        with tempfile.TemporaryDirectory() as diretorio_tmp:
            caminho_tmp = Path(diretorio_tmp) / enviado.name
            caminho_tmp.write_bytes(enviado.getvalue())
            try:
                resultado = substituir_planilha(spec, caminho_tmp)
            except Exception as erro:
                st.error(f"Planilha rejeitada — o layout não bateu com o esperado: {erro}")
                return

        if resultado.caminho_backup is not None:
            st.session_state[mensagem_key] = (
                f"Planilha substituída — {resultado.linhas_lidas} linhas lidas. Versão "
                f"anterior preservada em `{resultado.caminho_backup}`."
            )
        else:
            st.session_state[mensagem_key] = (
                f"Planilha recebida — {resultado.linhas_lidas} linhas lidas "
                "(não havia versão anterior para preservar)."
            )
        st.session_state[versao_key] = versao + 1
        st.rerun()


for _spec in ESPECIFICACOES.values():
    _render_card(_spec)
