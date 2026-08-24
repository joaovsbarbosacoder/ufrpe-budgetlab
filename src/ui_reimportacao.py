"""Componente Streamlit reutilizável: seção "Reimportar base" para qualquer base com
importação versionada (ver `src/importacao_versionada.py`).

Extraído de `app_pages/execucao_orcamentaria.py` (a implementação original, específica da
Execução Anual) para ser reutilizado por outras bases que adotem o mesmo padrão. Duas origens
possíveis para o arquivo candidato, tratadas pelo mesmo pipeline de validação/delta a partir
daqui — pedido explícito, para não precisar clicar em "Procurar arquivo" toda vez que uma nova
extração chega:

  * PASTA DE ENTRADA — uma ÚNICA pasta compartilhada por todas as bases
    (`data/raw/_entrada/`, `EspecificacaoReimportacao.diretorio_entrada`), não uma por base.
    Decisão explícita pensando num fluxo futuro de atualização por e-mail (anexo cai numa
    pasta só, sem precisar rotear pelo assunto/remetente para a subpasta certa). Verificada a
    cada carregamento da página: CADA arquivo `.xlsx`/`.xls` ali é testado contra o leitor
    desta base (`spec.importar`, mesma checagem de layout que já existe para qualquer
    extração); arquivos que não passam nessa checagem são de outra base (ou não são uma
    extração válida) e ficam de fora, silenciosamente, PARA ESTA PÁGINA — outra página (com
    outra `spec`) pode reconhecê-los. Só quando exatamente um arquivo da pasta é reconhecido
    por esta base é que ele vira candidato: SE o delta contra a extração atual não tem
    retroatividade nem exercício removido, é aplicado automaticamente, sem exigir clique
    nenhum (o arquivo some da pasta de entrada, movido para `diretorio_dados_brutos`). SE tem
    retroatividade/remoção, a mesma trava de sempre entra em ação — mostra a prévia/comparação
    e exige o checkbox de confirmação antes de aplicar; o arquivo fica parado na pasta até
    alguém decidir. Mais de um arquivo reconhecido PARA ESTA BASE é ambíguo — nada é processado
    até sobrar só um (arquivos de outras bases na mesma pasta não contam para essa ambiguidade).
  * UPLOAD MANUAL (`st.file_uploader`, sempre disponível como alternativa) — mesmo fluxo de
    sempre: upload → staging (nunca sobrescreve a extração ativa antes de validar) → prévia →
    gravação direta se seguro, ou confirmação explícita se há retroatividade/remoção.

Em ambos os casos: substituição total, nunca merge; nada é gravado sem passar pela validação
de `importacao_versionada.importar`.
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

    @property
    def diretorio_entrada(self) -> Path:
        # UMA pasta só, compartilhada por todas as bases (não uma subpasta por base) — pensada
        # para um fluxo futuro de atualização por e-mail, onde o anexo cai direto aqui sem
        # precisar saber a qual base ele pertence. Cada base reconhece os arquivos que são seus
        # tentando o próprio leitor (ver `_render_pasta_de_entrada`), não pelo nome do arquivo
        # nem por uma subpasta fixa.
        return self.diretorio_dados_brutos / "_entrada"


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


def _formatar_diferenca(valor: float | None) -> str:
    # `valor` vem de `Delta._diferenca`, que devolve `None` quando "antes" ou "depois" é nulo
    # (medida ausente num dos lados, não uma mudança de 0 para algo) — nesse caso não há um
    # "+X"/"-X" com sentido, só o próprio "antes"/"depois" (já mostrados ao lado) contam a
    # história.
    if valor is None:
        return "sem comparação — valor nulo em um dos lados"
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
    *,
    ignorar_arquivo_ausente: bool = False,
) -> None:
    spec.diretorio_dados_brutos.mkdir(parents=True, exist_ok=True)
    destino = spec.diretorio_dados_brutos / manifesto_novo.arquivo
    try:
        shutil.move(str(staging_path), str(destino))
    except OSError:
        # Só esperado no caminho automático da pasta de entrada (`ignorar_arquivo_ausente`):
        # outra sessão Streamlit já moveu este mesmo arquivo entre o momento em que esta
        # sessão o reconheceu e o momento em que tentou movê-lo. A extração já foi aplicada
        # por essa outra sessão — não há nada a fazer aqui além de recarregar a página.
        if not ignorar_arquivo_ausente:
            raise
        st.info("Este arquivo já foi processado por outra sessão — recarregando.")
        st.rerun()
        return
    manifesto_novo.salvar(spec.diretorio_manifestos)
    st.session_state[geracao_key] = st.session_state.get(geracao_key, 0) + 1
    st.success("Importação concluída — a página vai recarregar com a nova extração.")
    st.rerun()


def _processar_candidato(
    spec: EspecificacaoReimportacao,
    resultado: ResultadoImportacao,
    staging_path: Path,
    geracao_key: str,
    geracao: int,
    *,
    aplicar_automatico: bool,
) -> None:
    """Prévia + validação + delta + gate — comum às duas origens (pasta de entrada e upload
    manual). `aplicar_automatico` só tem efeito quando o delta NÃO exige confirmação
    (`exige_confirmacao` devolve `None`): grava direto em vez de esperar um clique — é o que
    diferencia a pasta de entrada (automática quando segura) do upload manual (sempre pede o
    clique em "Confirmar importação", mesmo quando seguro, porque ali a intenção de atualizar
    já foi expressa ao escolher o arquivo, mas o clique final continua sendo o padrão
    existente). Retroatividade/exercício removido SEMPRE exige o checkbox de confirmação,
    nas duas origens — `aplicar_automatico` nunca pula esse gate.
    """

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

    if motivo_gate is None:
        if aplicar_automatico:
            st.info("Sem retroatividade nem exercício removido — aplicando automaticamente.")
            _efetivar_reimportacao(
                spec, staging_path, manifesto_novo, geracao_key, ignorar_arquivo_ausente=True
            )
            return
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


@st.cache_data(show_spinner=False)
def _cached_reconhecimento(
    _importar: Callable[..., ResultadoImportacao], prefixo_base: str, caminho: str, mtime: float
) -> ResultadoImportacao | None:
    """`_importar` não entra na chave de cache (prefixo `_`, convenção do Streamlit para
    argumento não hasheável) — por isso `prefixo_base` (`spec.prefixo_estado`) PRECISA entrar:
    a pasta de entrada é compartilhada por todas as bases, então o mesmo (caminho, mtime) é
    testado por várias `spec` diferentes; sem `prefixo_base` na chave, o resultado cacheado de
    uma base vazaria para outra que consultasse o mesmo arquivo. `mtime` participa para forçar
    reler se o arquivo mudar (ex.: alguém substitui o conteúdo sem trocar o nome) — devolve
    `None` (não a exceção) quando o arquivo não pertence a esta base, para caber no cache sem
    reexecutar a checagem a cada rerun."""
    try:
        return _importar(caminho, registrar=False)
    except Exception:
        return None


def _render_pasta_de_entrada(spec: EspecificacaoReimportacao, geracao_key: str, geracao: int) -> None:
    spec.diretorio_entrada.mkdir(parents=True, exist_ok=True)
    todos = sorted(
        p for p in spec.diretorio_entrada.iterdir() if p.is_file() and p.suffix.lower() in (".xlsx", ".xls")
    )

    with st.expander(f"Pasta de entrada: `{spec.diretorio_entrada}`", expanded=bool(todos)):
        st.caption(
            "Pasta compartilhada por todas as bases — solte a extração mais recente aqui (fora "
            "do navegador) para que cada página reconheça sozinha o que é seu ao carregar (pelo "
            "layout do arquivo, não pelo nome). Sem retroatividade nem exercício removido, é "
            "aplicada automaticamente; do contrário, pede a mesma confirmação de sempre aqui "
            "embaixo."
        )
        if not todos:
            st.write("Nenhum arquivo pendente.")
            return

        # Cada arquivo é testado contra o leitor DESTA base — o que não passa na checagem de
        # layout não é erro aqui, é só de outra base (ou inválido), e outra página com outra
        # `spec` pode reconhecê-lo. Só o resultado é reaproveitado para não ler o arquivo duas
        # vezes quando ele de fato pertence a esta base.
        reconhecidos: list[tuple[Path, ResultadoImportacao]] = []
        with st.spinner("Verificando arquivos na pasta de entrada..."):
            for arquivo in todos:
                resultado = _cached_reconhecimento(
                    spec.importar, spec.prefixo_estado, str(arquivo), arquivo.stat().st_mtime
                )
                if resultado is not None:
                    reconhecidos.append((arquivo, resultado))

        nao_reconhecidos = len(todos) - len(reconhecidos)
        if not reconhecidos:
            st.write(
                "Nenhum arquivo desta base pendente."
                + (f" ({nao_reconhecidos} arquivo(s) na pasta não são desta base.)" if nao_reconhecidos else "")
            )
            return
        if len(reconhecidos) > 1:
            nomes = ", ".join(a.name for a, _ in reconhecidos)
            st.warning(
                f"Há {len(reconhecidos)} arquivos nessa pasta reconhecidos como desta base "
                f"({nomes}) — deixe só o mais recente para que ele seja processado."
            )
            return

        arquivo, resultado = reconhecidos[0]
        st.write(f"Arquivo detectado: **{arquivo.name}**")
        _processar_candidato(spec, resultado, arquivo, geracao_key, geracao, aplicar_automatico=True)


def render_reimportacao(spec: EspecificacaoReimportacao) -> None:
    geracao_key = f"{spec.prefixo_estado}_geracao"
    geracao = st.session_state.setdefault(geracao_key, 0)

    _render_pasta_de_entrada(spec, geracao_key, geracao)

    st.caption(
        "Ou envie manualmente — substituição total: a extração enviada passa a valer para a "
        "base inteira. Nada é gravado até você confirmar — o arquivo fica em uma área "
        "temporária enquanto você revisa a prévia abaixo."
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

    staging_path = spec.diretorio_staging / uploaded_file.name
    _processar_candidato(spec, resultado, staging_path, geracao_key, geracao, aplicar_automatico=False)
