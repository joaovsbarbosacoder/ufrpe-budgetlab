"""Componente Streamlit reutilizável: seção "Reimportar base" para qualquer base com
importação versionada (ver `src/importacao_versionada.py`).

Extraído de `app_pages/execucao_orcamentaria.py` (a implementação original, específica da
Execução Anual) para ser reutilizado por outras bases que adotem o mesmo padrão. O fluxo é
sempre o mesmo, independente da base: upload → staging (nunca sobrescreve a extração ativa
antes de validar) → prévia com validação e delta, sem gravar nada → gravação direta se não há
retroatividade/remoção, ou confirmação explícita se há (`exige_confirmacao`, de
`importacao_versionada`) → substituição total.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import streamlit as st

from src.importacao_versionada import Manifesto, ResultadoImportacao, exige_confirmacao
from src.ui_theme import format_brl_full, render_alert


@dataclass(frozen=True)
class EspecificacaoReimportacao:
    """O que varia de uma base para outra nesta seção."""

    #: Namespace das chaves de widget/session_state desta seção (ex.: "execucao_anual_reimport").
    prefixo_estado: str
    diretorio_dados_brutos: Path
    diretorio_manifestos: Path
    medidas: Sequence[str]
    #: Mesma assinatura de `importacao_execucao.importar`: importar(caminho, diretorio_manifestos=, registrar=).
    importar: Callable[..., ResultadoImportacao]
    #: Linha de contagens da prévia — cada base decide quais das suas contagens mostrar.
    linhas_resumo: Callable[[Manifesto], str]
    formatar_medida: Callable[[str], str] = str.capitalize

    @property
    def diretorio_staging(self) -> Path:
        # Pouso temporário do upload até a confirmação — nunca sobrescreve o arquivo da
        # extração ativa antes de validar e (se necessário) confirmar.
        return self.diretorio_dados_brutos / "_staging"


def _preview_reimportacao(
    spec: EspecificacaoReimportacao, file_content: bytes, filename: str
) -> ResultadoImportacao:
    """Grava o upload em staging e roda leitura + validação + delta, sem gravar manifesto.

    Não é cacheado: o arquivo de staging precisa existir sempre que esta função rodar
    (inclusive de novo após um `st.checkbox`/`st.button` disparar um rerender), porque uma
    confirmação anterior pode ter movido o staging de uma extração já efetivada para
    `diretorio_dados_brutos` — cachear o resultado sem recriar o arquivo deixaria
    `_efetivar_reimportacao` sem o que mover.
    """

    spec.diretorio_staging.mkdir(parents=True, exist_ok=True)
    staging_path = spec.diretorio_staging / filename
    staging_path.write_bytes(file_content)
    return spec.importar(staging_path, registrar=False)


def _formatar_diferenca(valor: float) -> str:
    sinal = "+" if valor >= 0 else "-"
    return sinal + format_brl_full(abs(valor)).removeprefix("R$ ")


def _formatar_variacoes_retroativas(delta) -> list[str]:
    linhas = []
    for ano, medidas in sorted(delta.anos_alterados.items()):
        partes = ", ".join(
            f"{medida}: {format_brl_full(info['antes'])} → {format_brl_full(info['depois'])} "
            f"({_formatar_diferenca(info['diferenca'])})"
            for medida, info in medidas.items()
        )
        linhas.append(f"**{ano}** — {partes}")
    return linhas


def _efetivar_reimportacao(
    spec: EspecificacaoReimportacao,
    staging_path: Path,
    manifesto_novo: Manifesto,
    geracao_key: str,
) -> None:
    spec.diretorio_dados_brutos.mkdir(parents=True, exist_ok=True)
    destino = spec.diretorio_dados_brutos / manifesto_novo.arquivo
    shutil.move(str(staging_path), str(destino))
    manifesto_novo.salvar(spec.diretorio_manifestos)
    st.session_state[geracao_key] = st.session_state.get(geracao_key, 0) + 1
    st.success("Importação concluída — a página vai recarregar com a nova extração.")
    st.rerun()


def render_reimportacao(spec: EspecificacaoReimportacao) -> None:
    geracao_key = f"{spec.prefixo_estado}_geracao"
    geracao = st.session_state.setdefault(geracao_key, 0)

    st.caption(
        "Substituição total: a extração enviada passa a valer para a base inteira. "
        "Nada é gravado até você confirmar — o arquivo fica em uma área temporária "
        "enquanto você revisa a prévia abaixo."
    )
    uploaded_file = st.file_uploader(
        "Nova extração (.xlsx)",
        type=["xlsx", "xls"],
        key=f"{spec.prefixo_estado}_uploader_{geracao}",
    )
    if uploaded_file is None:
        return

    try:
        with st.spinner("Lendo e validando o arquivo enviado..."):
            resultado = _preview_reimportacao(spec, uploaded_file.getvalue(), uploaded_file.name)
    except Exception as error:
        st.error(f"Não foi possível ler o arquivo enviado: {error}")
        return

    manifesto_novo = resultado.manifesto
    validacao = resultado.validacao
    delta = resultado.delta

    st.write("**Contagens**")
    st.write(spec.linhas_resumo(manifesto_novo))

    st.write("**Totais**")
    st.write(
        " · ".join(
            f"{spec.formatar_medida(medida)}: {format_brl_full(manifesto_novo.totais[medida])}"
            for medida in spec.medidas
        )
    )

    if validacao.erros:
        st.error("Validação encontrou erro(s) — a importação está bloqueada:")
        for erro in validacao.erros:
            st.write(f"- {erro}")
        return

    render_alert("Validação aprovada.", "success")
    for alerta in validacao.alertas:
        st.warning(alerta)

    st.write("**Comparação com a extração atual**")
    for linha in delta.resumo_texto():
        st.write(f"- {linha}")

    if delta.mesma_extracao:
        st.info("Arquivo idêntico à extração atual — nada a gravar.")
        return

    motivo_gate = exige_confirmacao(delta)
    staging_path = spec.diretorio_staging / uploaded_file.name

    if motivo_gate is None:
        if st.button("Confirmar importação", type="primary"):
            _efetivar_reimportacao(spec, staging_path, manifesto_novo, geracao_key)
        return

    st.error(
        "Esta substituição altera dados já divulgados — confira com atenção antes de confirmar."
    )
    if motivo_gate.anos_retroativos:
        st.write("**Exercícios com valores alterados retroativamente:**")
        for linha in _formatar_variacoes_retroativas(delta):
            st.write(f"- {linha}")
    if motivo_gate.anos_removidos:
        st.write(
            "**Exercícios que somem do painel** (substituição total — deixam de existir): "
            + ", ".join(map(str, motivo_gate.anos_removidos))
        )

    confirmado = st.checkbox(
        "Entendo o impacto acima e confirmo a substituição, incluindo os exercícios "
        "fechados/removidos listados.",
        key=f"{spec.prefixo_estado}_confirma_{geracao}",
    )
    if st.button("Confirmar substituição", type="primary", disabled=not confirmado):
        _efetivar_reimportacao(spec, staging_path, manifesto_novo, geracao_key)
