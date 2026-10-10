"""Painel de Emendas Parlamentares com histórico estático e execução por PTRES.

A carga inicial preserva todos os exercícios disponíveis. Atualizações pelo
uploader são aceitas somente para 2026 em diante e são compostas por ano, sem
apagar os exercícios históricos. Empenhado, Liquidado e Pago de 2026+ vêm da
Execução Anual quando existe vínculo por ``(exercício, RP, PTRES)``.
"""

from __future__ import annotations

import html as html_lib
from collections.abc import Iterable
from datetime import date, datetime

import pandas as pd
import streamlit as st

from src import acompanhamento_emendas as acomp
from src import ajustes_dotacao_emendas as ajustes
from src.acompanhamento_emendas import STATUS_OUTRO, STATUS_SUGERIDOS, ErroAcompanhamento
from src.ajustes_dotacao_emendas import ErroAjusteDotacao, ptres_com_uma_emenda
from src.ui_cadastro import celula_principal, celula_suave, celula_valor, chip
from src.ui_cadastro import css as css_cadastro
from src.design_tokens import (
    ACCENT,
    ACCENT_LINE,
    ACCENT_SOFT,
    ACCENT_STRONG,
    BORDER,
    BORDER_SOFT,
    CARD_PAD,
    FONT_BODY,
    FONT_HEADING,
    NEGATIVE,
    POSITIVE,
    RADIUS,
    SIZE,
    SPACE,
    SURFACE,
    TEXT,
    TEXT_MUTED,
    TRACK,
    WARNING,
)
from src.emendas_parlamentares import (
    ANO_INICIO_ATUALIZACAO,
    ErroPoliticaImportacao,
    ErroVinculoEmenda,
    RPS_EMENDA,
    carregar_emendas_cadastradas,
    compor_relatorio_com_cadastros,
    divergencias_dotacao,
    normalizar_ptres_texto,
    nova_emenda_acompanhamento,
    salvar,
    vincular_execucao_emendas,
)
from src.importacao_emendas import (
    DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_EMENDAS,
    NOME_PONTEIRO as PONTEIRO_EMENDAS,
    Manifesto as ManifestoEmendas,
    carregar_atual as carregar_emendas_atual,
)
from src.importacao_execucao import (
    DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_EXECUCAO,
    NOME_PONTEIRO as PONTEIRO_EXECUCAO,
    Manifesto as ManifestoExecucao,
    carregar_atual as carregar_execucao_atual,
)
from src.importacao_dotacao import (
    DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_DOTACAO,
    NOME_PONTEIRO as PONTEIRO_DOTACAO,
    Manifesto as ManifestoDotacao,
    carregar_atual as carregar_dotacao_atual,
)
from src.ui_theme import format_brl_full, render_page_header
from src.vinculos_emendas import carregar_eventos_vinculo, compor_relatorio_com_vinculos


@st.cache_data(show_spinner="Lendo a base de Emendas...", max_entries=4)
def _cached_emendas(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    return carregar_emendas_atual()


@st.cache_data(show_spinner="Lendo a Execução Anual...", max_entries=4)
def _cached_execucao(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    return carregar_execucao_atual()


@st.cache_data(show_spinner="Lendo a Dotação Anual...", max_entries=4)
def _cached_dotacao(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame | None:
    return carregar_dotacao_atual()


def _valor_brl(valor: object) -> str:
    return "—" if valor is None or pd.isna(valor) else format_brl_full(float(valor))


def _brl_md(valor: object) -> str:
    """`_valor_brl` para texto em MARKDOWN (`st.markdown`/`st.caption`): escapa o `$`. Dois `$` no mesmo bloco viram
    delimitadores de fórmula e o texto sai quebrado ("R 300.000,00**"; conferido na tela real). Em HTML
    (`unsafe_allow_html`) não é preciso."""

    return _valor_brl(valor).replace("$", "\\$")


def _total(series: pd.Series) -> object:
    total = series.sum(min_count=1)
    return pd.NA if pd.isna(total) else float(total)


#: campo do DataFrame `emendas` -> key de `st.session_state` do respectivo `st.multiselect`.
_CAMPOS_FILTRO_EMENDAS = {
    "ano": "emendas_filtro_ano",
    "resultado_primario_cod": "emendas_filtro_rp",
    "parlamentar": "emendas_filtro_parlamentar",
    "tramitacao": "emendas_filtro_tramitacao",
}
TRAMITACAO_SEM_STATUS = "Sem status"


def _opcoes_filtro(dataframe: pd.DataFrame, campo: str) -> list[str]:
    if campo == "ano":
        return [str(ano) for ano in sorted(int(ano) for ano in dataframe[campo].dropna().unique())]
    return sorted(str(valor) for valor in dataframe[campo].dropna().unique())


def _selecoes_persistidas() -> dict[str, list[str]]:
    """Lê o que já está marcado em cada filtro (via `st.session_state`) para servir de base ao
    recorte cruzado de `_opcoes_disponiveis` — precisa ser lido ANTES de desenhar qualquer
    `st.multiselect` da rodada, senão um campo só enxergaria os campos desenhados antes dele
    (mesma cascata de mão única corrigida em `ui_filtros_execucao._todas_selecoes_atuais`)."""

    selecoes: dict[str, list[str]] = {}
    for campo, key in _CAMPOS_FILTRO_EMENDAS.items():
        valores = st.session_state.get(key, [])
        if valores:
            selecoes[campo] = valores
    return selecoes


def _opcoes_disponiveis(dataframe: pd.DataFrame, selecoes: dict[str, list[str]], campo: str) -> pd.DataFrame:
    """`dataframe` recortado pelos OUTROS filtros já selecionados (nunca pelo próprio `campo`,
    senão marcar um valor faria os demais valores já escolhidos no mesmo campo sumirem da
    lista) — assim escolher um Exercício já restringe as opções de RP e Parlamentar, e
    vice-versa, em qualquer ordem (pedido explícito: filtros combinados/cascata)."""

    filtrado = dataframe
    for outro_campo, valores in selecoes.items():
        if outro_campo == campo or not valores:
            continue
        filtrado = filtrado[filtrado[outro_campo].astype("string").isin(valores)]
    return filtrado


def _sanear_persistido(key: str, opcoes_validas: list[str]) -> None:
    """`st.multiselect` levanta erro se um valor persistido em `st.session_state` não estiver
    mais em `options` — a cascata muda as opções disponíveis a cada rerun conforme os outros
    filtros mudam, então precisa limpar antes de instanciar o widget."""

    persistido = st.session_state.get(key, [])
    valido = [valor for valor in persistido if valor in opcoes_validas]
    if valido != persistido:
        st.session_state[key] = valido


def _juntar_codigos(valores: object) -> str:
    if isinstance(valores, Iterable) and not isinstance(valores, (str, bytes)):
        return ", ".join(str(valor) for valor in valores)
    return "—" if valores is None or pd.isna(valores) else str(valores)


def _esc(value: object) -> str:
    return html_lib.escape(str(value))


def _resumo_tupla(valores: object) -> str:
    if not valores:
        return "—"
    return _esc(valores[0]) if len(valores) == 1 else f"{len(valores)} valores"


_ROTULOS_ORIGEM = {
    "relatorio_estatico": ("Histórico estático", TEXT_MUTED, "rgba(147,161,184,0.14)"),
    "execucao_anual": ("Execução Anual", POSITIVE, "rgba(34,197,94,0.14)"),
    "execucao_anual_parcial": ("Execução parcial", ACCENT, "rgba(9,105,218,0.12)"),
    # ainda sem execução é o estado NORMAL de uma emenda recente — azul, não vermelho (10/2026)
    "sem_execucao": ("Aguardando execução", ACCENT, "rgba(9,105,218,0.12)"),
}

CSS_REGISTRO = f"""
<style>
.em-bar {{ height: 7px; background: {TRACK}; border-radius: 99px; overflow: hidden; }}
.em-bar > i {{ display: block; height: 100%; background: {ACCENT}; border-radius: 99px; }}
.em-bar.cheia > i {{ background: {POSITIVE}; }}
.st-key-em_registro_scroll {{ max-height: 760px; overflow-y: auto; padding-right: 8px; }}
[class*="st-key-em_painel_"] {{ background: rgba(9,105,218,0.04); border: 1px solid {BORDER_SOFT}; border-radius: 16px;
    padding: 14px 16px 6px; margin: 2px 0 14px; }}
[class*="st-key-em_painel_"] .em-card {{ margin-bottom: 14px; }}
</style>
"""


def _badge(rotulo: str, cor: str, fundo: str) -> str:
    return (
        f'<span class="em-badge" style="color:{cor};background:{fundo};border-color:{cor}55">'
        f"{_esc(rotulo)}</span>"
    )


def _badge_origem(origem: object) -> str:
    rotulo, cor, fundo = _ROTULOS_ORIGEM.get(
        str(origem), (str(origem), TEXT_MUTED, "rgba(147,161,184,0.14)")
    )
    return _badge(rotulo, cor, fundo)


def _inject_css() -> None:
    """Cartões HTML no mesmo idioma visual de `app_pages/painel_acoes.py` (`.po-*`) e
    `app_pages/consulta_empenhos.py` (`.ce-cons-*`) — nenhuma lista principal do app usa
    `st.dataframe` puro (ver LAYOUT.md §2), então a lista de Emendas segue o mesmo padrão de
    cartão HTML em vez da grade cinza padrão do Streamlit."""

    st.markdown(
        f"""
        <style>
        .em-card {{
            border: 1px solid {BORDER}; border-radius: {RADIUS};
            background: {SURFACE}; padding: {CARD_PAD};
            margin-bottom: {SPACE['xl']};
        }}
        .em-card-head {{
            display: grid; grid-template-columns: minmax(0,1fr) auto;
            gap: 24px; align-items: start; margin-bottom: {SPACE['md']};
        }}
        .em-kicker {{
            font-family: {FONT_HEADING}; font-size: {SIZE['value']};
            letter-spacing: {TRACK['kicker']}; color: {ACCENT}; text-transform: uppercase;
        }}
        .em-title {{
            margin: 3px 0 8px; font-family: {FONT_HEADING}; font-weight: 600;
            font-size: {SIZE['card_title']}; line-height: 1.12; color: {TEXT};
        }}
        .em-tags {{ display: flex; flex-wrap: wrap; gap: {SPACE['xs']}; }}
        .em-tag {{
            font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
            border: 1px solid {ACCENT_LINE}; border-radius: {RADIUS};
            padding: 2px 7px; background: {ACCENT_SOFT};
        }}
        .em-badge {{
            display: inline-block; font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: 0.06em; text-transform: uppercase;
            border: 1px solid; border-radius: {RADIUS}; padding: 2px 7px; white-space: nowrap;
        }}
        .em-metric-label {{
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: {TRACK['label']}; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .em-metric {{
            font-family: {FONT_HEADING}; font-size: {SIZE['metric']}; line-height: 1.1;
            color: {ACCENT_STRONG}; font-variant-numeric: tabular-nums;
        }}
        .em-stats {{
            display: grid; grid-template-columns: repeat(4, minmax(0,1fr));
            gap: {SPACE['md']}; margin-bottom: {SPACE['md']};
            padding: {SPACE['sm']} 0; border-top: 1px solid {BORDER}; border-bottom: 1px solid {BORDER};
        }}
        .em-stat-label {{
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: {TRACK['label']}; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .em-stat-value {{
            font-family: {FONT_HEADING}; font-size: {SIZE['value_strong']}; font-weight: 600;
            color: {TEXT}; font-variant-numeric: tabular-nums;
        }}
        .em-scroll {{ overflow-x: auto; padding-bottom: 2px; }}
        .em-row, .em-head {{
            display: grid;
            grid-template-columns: minmax(70px,0.7fr) minmax(60px,0.6fr) minmax(130px,1.1fr)
                minmax(110px,1fr) minmax(110px,1fr) minmax(110px,1fr) minmax(110px,1fr);
            gap: 8px; min-width: 850px;
        }}
        .em-head {{
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .em-row {{ padding: 9px 0; border-bottom: 1px solid {BORDER_SOFT}; align-items: baseline; }}
        .em-flat {{
            font-family: {FONT_HEADING}; font-size: {SIZE['small']};
            letter-spacing: 0.08em; color: {TEXT_MUTED}; white-space: nowrap;
        }}
        .em-val {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED}; white-space: nowrap;
        }}
        .em-val-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
            white-space: nowrap;
        }}
        .em-empty {{
            font-family: {FONT_HEADING}; font-size: 16px; letter-spacing: 0.1em;
            text-transform: uppercase; color: {TEXT_MUTED}; padding: 40px 0;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _html_linha_ptres(r) -> str:
    return (
        '<div class="em-row">'
        f'<span class="em-flat">{_esc(r.ptres)}</span>'
        f'<span class="em-flat">{_esc(_juntar_codigos(r.gnds))}</span>'
        + _badge_origem(r.origem_valores)
        + f'<span class="em-val">{_esc(_valor_brl(r.dotacao_atualizada))}</span>'
        f'<span class="em-val">{_esc(_valor_brl(r.empenhada))}</span>'
        f'<span class="em-val">{_esc(_valor_brl(r.liquidada))}</span>'
        f'<span class="em-val-strong">{_esc(_valor_brl(r.paga))}</span>'
        "</div>"
    )


def _html_dotacao_anual(linha) -> str:
    """Linha informativa com a Dotação Anual por PTRES — só existe para exercícios dinâmicos
    quando a Dotação Anual foi carregada. Nunca substitui a dotação do relatório/cadastro."""
    if not hasattr(linha, "dotacao_anual_ptres") or int(linha.ano) < ANO_INICIO_ATUALIZACAO:
        return ""
    if int(linha.ptres_com_dotacao_anual) == 0:
        texto = "Dotação Anual (por PTRES): sem dotação correspondente"
    else:
        texto = (
            f"Dotação Anual (por PTRES): {_valor_brl(linha.dotacao_anual_ptres)} · "
            f"{int(linha.ptres_com_dotacao_anual)} de {int(linha.ptres_total)} PTRES com dotação"
        )
    aviso = (
        _badge("Difere do informado", WARNING, "rgba(245,165,36,0.14)")
        if bool(getattr(linha, "dotacao_divergencia_pendente", linha.dotacao_divergente))
        else ""
    )
    return f'<div class="em-tags" style="margin-bottom:8px"><span class="em-tag">{_esc(texto)}</span>{aviso}</div>'


def _render_card_emenda(linha, vinculos_da_emenda: pd.DataFrame, status_atual: str | None = None) -> None:
    parlamentar = (
        "(não informado)" if pd.isna(linha.parlamentar) else _esc(linha.parlamentar)
    )
    ptres_total = int(linha.ptres_total)
    decidida = (
        "dotacao_decisao_estado" in vinculos_da_emenda.columns
        and bool(vinculos_da_emenda["dotacao_decisao_estado"].eq("ativa").fillna(False).any())
    )
    tags_html = "".join(
        [
            f'<span class="em-tag">PTRES {_juntar_codigos(linha.ptres) if ptres_total == 1 else ptres_total}</span>',
            f'<span class="em-tag">GND {_resumo_tupla(linha.gnds)}</span>',
            _badge_origem(linha.origem_valores),
            *(['<span class="em-tag">dotação decidida</span>'] if decidida else []),
            *([f'<span class="em-tag">Tramitação: {_esc(status_atual)}</span>'] if status_atual else []),
        ]
    )
    original_relatorio = ""
    if decidida and hasattr(linha, "dotacao_relatorio"):
        original_relatorio = (
            f'<div class="em-metric-label">Relatório: {_esc(_valor_brl(linha.dotacao_relatorio))}</div>'
        )
    linhas_html = "".join(_html_linha_ptres(row) for row in vinculos_da_emenda.itertuples())
    # com um só PTRES a tabela repetiria exatamente os números do cabeçalho do cartão (10/2026)
    bloco_ptres = (
        '<div class="em-scroll"><div class="em-head">'
        '<span>PTRES</span><span>GND</span><span>Status</span>'
        '<span style="text-align:right">Dotação</span><span style="text-align:right">Empenhado</span>'
        '<span style="text-align:right">Liquidado</span><span style="text-align:right">Pago</span>'
        f'</div>{linhas_html}</div>'
        if ptres_total > 1
        else ""
    )

    st.markdown(
        f"""
        <div class="em-card">
          <div class="em-card-head">
            <div style="min-width:0">
              <div class="em-kicker">RP{_esc(linha.resultado_primario_cod)} · EXERCÍCIO {int(linha.ano)}</div>
              <div class="em-title">{_esc(linha.emenda_numero)} — {parlamentar}</div>
              <div class="em-tags">{tags_html}</div>
            </div>
            <div style="text-align:right">
              <div class="em-metric-label">Dotação atualizada</div>
              <div class="em-metric">{_esc(_valor_brl(linha.dotacao_atualizada))}</div>
              {original_relatorio}
            </div>
          </div>
          <div class="em-stats">
            <div>
              <div class="em-stat-label">Empenhado</div>
              <div class="em-stat-value">{_esc(_valor_brl(linha.empenhada))}</div>
            </div>
            <div>
              <div class="em-stat-label">Liquidado</div>
              <div class="em-stat-value">{_esc(_valor_brl(linha.liquidada))}</div>
            </div>
            <div>
              <div class="em-stat-label">Pago</div>
              <div class="em-stat-value">{_esc(_valor_brl(linha.paga))}</div>
            </div>
            <div>
              <div class="em-stat-label">PTRES c/ execução</div>
              <div class="em-stat-value">{int(linha.ptres_com_execucao)} de {ptres_total}</div>
            </div>
          </div>
          {_html_dotacao_anual(linha)}
          {bloco_ptres}
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.dialog("Cadastrar emenda")
def _dialog_cadastro_manual() -> None:
    st.caption(
        f"Cadastros manuais são permitidos somente a partir de "
        f"{ANO_INICIO_ATUALIZACAO}. Os PTRES serão reconciliados com a Execução Anual."
    )
    with st.form("emendas_cadastro_manual", border=False):
        exercicio = st.number_input(
            "Exercício",
            min_value=ANO_INICIO_ATUALIZACAO,
            step=1,
            value=ANO_INICIO_ATUALIZACAO,
        )
        rp_codigo = st.selectbox(
            "Resultado Primário",
            options=list(RPS_EMENDA),
            format_func=lambda codigo: f"RP{codigo} — {RPS_EMENDA[codigo]}",
        )
        numero = st.text_input("Número da emenda")
        parlamentar = st.text_input("Parlamentar")
        ptres_texto = st.text_area(
            "PTRES",
            placeholder="Separe múltiplos PTRES por vírgula ou quebra de linha",
        )
        gnd_codigo = st.text_input(
            "Código do GND",
            help="Código tratado como identificador; zeros iniciais são preservados.",
        )
        informar_dotacao = st.checkbox("Informar dotação atualizada")
        dotacao = st.number_input(
            "Dotação atualizada (R$)",
            step=1000.0,
            format="%.2f",
        )
        objeto = st.text_area("Objeto ou observação")
        destinatario = st.text_input(
            "Destinatário (opcional)",
            help="Com o responsável preenchido, objeto e destinatário também entram no acompanhamento da emenda.",
        )
        responsavel = st.text_input("Responsável")
        enviado = st.form_submit_button(
            "Cadastrar emenda",
            type="primary",
            icon=":material/add:",
        )

    if not enviado:
        return
    try:
        emenda = nova_emenda_acompanhamento(
            exercicio=int(exercicio),
            parlamentar=parlamentar,
            numero=numero,
            rp_codigo=rp_codigo,
            ptres=normalizar_ptres_texto(ptres_texto),
            gnd_codigo=gnd_codigo,
            dotacao_atualizada=float(dotacao) if informar_dotacao else None,
            objeto=objeto,
            responsavel=responsavel,
        )
        salvar(emenda)
    except (ErroPoliticaImportacao, ErroVinculoEmenda, OSError, ValueError) as error:
        st.error(str(error))
        return
    if objeto.strip() or destinatario.strip():
        chave_nova = (int(exercicio), str(rp_codigo), numero.strip())
        if responsavel.strip():
            try:
                acomp.definir_complemento(
                    chave=chave_nova, objeto=objeto, destinatario=destinatario, responsavel=responsavel,
                    motivo="Informado no cadastro da emenda.", chaves_validas={chave_nova},
                    diretorio=acomp.DIRETORIO_ACOMPANHAMENTO,
                )
            except (ErroAcompanhamento, OSError) as error:
                st.toast(f"Emenda cadastrada, mas objeto/destinatário não foram registrados no acompanhamento: {error}")
        else:
            st.toast("Emenda cadastrada. Informe o responsável para registrar objeto/destinatário no acompanhamento.")
    st.success("Emenda cadastrada e incluída na reconciliação.")
    st.rerun()


render_page_header(
    "Emendas Parlamentares",
    "Histórico preservado · atualizações 2026+ · execução conciliada por PTRES.",
)
_inject_css()
st.markdown(css_cadastro(), unsafe_allow_html=True)
st.markdown(CSS_REGISTRO, unsafe_allow_html=True)

manifesto_emendas = ManifestoEmendas.atual()
if manifesto_emendas is None:
    st.error(
        "A carga histórica inicial de Emendas ainda não foi registrada. "
        "Ela deve ser instalada uma única vez antes das atualizações de 2026+."
    )
    st.stop()

manifesto_execucao = ManifestoExecucao.atual()
if manifesto_execucao is None:
    st.info(
        "Importe a Execução Anual para reconciliar Empenhado, Liquidado e Pago "
        "das emendas de 2026 em diante."
    )
    st.stop()

caminho_ponteiro_emendas = DIR_MANIFESTOS_EMENDAS / PONTEIRO_EMENDAS
caminho_ponteiro_execucao = DIR_MANIFESTOS_EXECUCAO / PONTEIRO_EXECUCAO
relatorio_base = _cached_emendas(
    str(caminho_ponteiro_emendas),
    caminho_ponteiro_emendas.stat().st_mtime,
)
execucao = _cached_execucao(
    str(caminho_ponteiro_execucao),
    caminho_ponteiro_execucao.stat().st_mtime,
)

caminho_ponteiro_dotacao = DIR_MANIFESTOS_DOTACAO / PONTEIRO_DOTACAO
dotacao_anual = (
    _cached_dotacao(str(caminho_ponteiro_dotacao), caminho_ponteiro_dotacao.stat().st_mtime)
    if caminho_ponteiro_dotacao.exists()
    else None
)

try:
    cadastros_manuais = carregar_emendas_cadastradas()
    eventos_vinculo = carregar_eventos_vinculo()
    # decisões sobre divergência de dotação (10/2026): eventos imutáveis; ilegível/incoerente levanta erro
    decisoes_dotacao = ajustes.reconstruir_decisoes(ajustes.carregar_eventos(ajustes.DIRETORIO_AJUSTES))
    # acompanhamento manual (tramitação, objeto, destinatário): eventos imutáveis; ilegível/incoerente levanta erro
    eventos_acompanhamento = acomp.carregar_eventos(acomp.DIRETORIO_ACOMPANHAMENTO)
    tramitacao = acomp.reconstruir_tramitacao(eventos_acompanhamento)
    composicao = compor_relatorio_com_cadastros(
        relatorio_base,
        cadastros_manuais,
    )
    composicao_vinculos = compor_relatorio_com_vinculos(
        composicao.relatorio,
        cadastros_manuais,
        eventos_vinculo,
    )
    resultado = vincular_execucao_emendas(
        composicao_vinculos.relatorio, execucao, dotacao=dotacao_anual, decisoes_dotacao=decisoes_dotacao
    )
except (ErroPoliticaImportacao, ErroVinculoEmenda, ErroAjusteDotacao, ErroAcompanhamento) as error:
    st.error(f"Não foi possível consolidar as Emendas: {error}")
    st.stop()

# chaves das emendas existentes agora (relatório + cadastros manuais): o servidor valida contra elas
chaves_validas = {
    (int(r.ano), str(r.resultado_primario_cod), str(r.emenda_numero)) for r in resultado.emendas.itertuples()
}
status_por_chave = {
    (int(r.ano), str(r.resultado_primario_cod), str(r.emenda_numero)): r
    for r in acomp.status_atual(tramitacao).itertuples()
}
complemento_por_chave = {
    (int(r.ano), str(r.resultado_primario_cod), str(r.emenda_numero)): r
    for r in acomp.complemento_vigente(eventos_acompanhamento).itertuples()
}
orfaos_acompanhamento = acomp.orfaos(eventos_acompanhamento, chaves_validas)

with st.container(horizontal=True):
    if st.button(
        "Cadastrar emenda",
        type="primary",
        icon=":material/add:",
    ):
        _dialog_cadastro_manual()

emendas = resultado.emendas.copy()
# status atual da tramitação (manual) como coluna, para filtrar e mostrar no registro
emendas["tramitacao"] = [
    getattr(status_por_chave.get((int(ano), str(rp), str(numero))), "status", TRAMITACAO_SEM_STATUS)
    for ano, rp, numero in zip(emendas["ano"], emendas["resultado_primario_cod"], emendas["emenda_numero"])
]

# primeira abertura: só o exercício vigente (2026 em diante); o histórico fica a um clique (limpar o filtro)
if "emendas_filtro_ano_inicializado" not in st.session_state:
    st.session_state["emendas_filtro_ano_inicializado"] = True
    if _CAMPOS_FILTRO_EMENDAS["ano"] not in st.session_state:
        vigentes = [ano for ano in _opcoes_filtro(emendas, "ano") if int(ano) >= ANO_INICIO_ATUALIZACAO]
        if vigentes:
            st.session_state[_CAMPOS_FILTRO_EMENDAS["ano"]] = vigentes

with st.container(border=True):
    st.markdown("**Filtros**")
    col_ano, col_rp, col_parlamentar, col_tramitacao = st.columns(4)
    selecoes_persistidas = _selecoes_persistidas()

    with col_ano:
        opcoes_ano = _opcoes_filtro(_opcoes_disponiveis(emendas, selecoes_persistidas, "ano"), "ano")
        _sanear_persistido(_CAMPOS_FILTRO_EMENDAS["ano"], opcoes_ano)
        anos_selecionados = st.multiselect(
            "Exercício",
            options=opcoes_ano,
            key=_CAMPOS_FILTRO_EMENDAS["ano"],
            placeholder="Todos",
        )
    with col_rp:
        opcoes_rp = _opcoes_filtro(
            _opcoes_disponiveis(emendas, selecoes_persistidas, "resultado_primario_cod"),
            "resultado_primario_cod",
        )
        _sanear_persistido(_CAMPOS_FILTRO_EMENDAS["resultado_primario_cod"], opcoes_rp)
        rps_selecionados = st.multiselect(
            "Resultado Primário",
            options=opcoes_rp,
            format_func=lambda codigo: f"RP{codigo}",
            key=_CAMPOS_FILTRO_EMENDAS["resultado_primario_cod"],
            placeholder="Todos",
        )
    with col_parlamentar:
        opcoes_parlamentar = _opcoes_filtro(
            _opcoes_disponiveis(emendas, selecoes_persistidas, "parlamentar"), "parlamentar"
        )
        _sanear_persistido(_CAMPOS_FILTRO_EMENDAS["parlamentar"], opcoes_parlamentar)
        parlamentares_selecionados = st.multiselect(
            "Parlamentar",
            options=opcoes_parlamentar,
            key=_CAMPOS_FILTRO_EMENDAS["parlamentar"],
            placeholder="Todos",
        )
    with col_tramitacao:
        opcoes_tramitacao = _opcoes_filtro(
            _opcoes_disponiveis(emendas, selecoes_persistidas, "tramitacao"), "tramitacao"
        )
        _sanear_persistido(_CAMPOS_FILTRO_EMENDAS["tramitacao"], opcoes_tramitacao)
        tramitacoes_selecionadas = st.multiselect(
            "Tramitação",
            options=opcoes_tramitacao,
            key=_CAMPOS_FILTRO_EMENDAS["tramitacao"],
            placeholder="Todas",
        )

filtradas = emendas
if anos_selecionados:
    filtradas = filtradas[filtradas["ano"].astype("string").isin(anos_selecionados)]
if rps_selecionados:
    filtradas = filtradas[filtradas["resultado_primario_cod"].isin(rps_selecionados)]
if parlamentares_selecionados:
    filtradas = filtradas[filtradas["parlamentar"].isin(parlamentares_selecionados)]
if tramitacoes_selecionadas:
    filtradas = filtradas[filtradas["tramitacao"].isin(tramitacoes_selecionadas)]
filtradas = filtradas.copy()

if anos_selecionados and all(int(ano) >= ANO_INICIO_ATUALIZACAO for ano in anos_selecionados):
    historicas_ocultas = int((emendas["ano"] < ANO_INICIO_ATUALIZACAO).sum())
    if historicas_ocultas:
        st.caption(
            f"{historicas_ocultas} emenda(s) de exercícios anteriores a {ANO_INICIO_ATUALIZACAO} ocultas pelo "
            "filtro de Exercício — remova o filtro para ver o histórico."
        )

with st.container(horizontal=True):
    st.metric("Emendas", f"{len(filtradas):,}".replace(",", "."), border=True)
    st.metric(
        "Dotação atualizada",
        _valor_brl(_total(filtradas["dotacao_atualizada"])),
        border=True,
    )
    st.metric("Empenhado", _valor_brl(_total(filtradas["empenhada"])), border=True)
    st.metric("Liquidado", _valor_brl(_total(filtradas["liquidada"])), border=True)
    st.metric("Pago", _valor_brl(_total(filtradas["paga"])), border=True)


ROTULO_DECISAO = {
    "adotar_dotacao_anual": "Dotação Anual adotada",
    "manter_relatorio": "Relatório mantido",
    "valor_informado": "Valor informado",
}
ROTULO_ESTADO_DECISAO = {"ativa": "ativa", "obsoleta": "obsoleta", "sem_efeito": "sem efeito"}


def _data_hora(iso: str | None) -> str:
    if not iso:
        return "—"
    return datetime.fromisoformat(iso).astimezone().strftime("%d/%m/%Y %H:%M")


def _decisao_ativa(decisoes: list[dict], linha: pd.Series) -> dict | None:
    chave = (int(linha["ano"]), str(linha["resultado_primario_cod"]), str(linha["emenda_numero"]), str(linha["ptres"]))
    return next(
        (d for d in decisoes if not d["desfeita"]
         and (d["ano"], d["resultado_primario_cod"], d["emenda_numero"], d["ptres"]) == chave),
        None,
    )


@st.dialog("Resolver divergência de dotação")
def _dialogo_resolver_divergencia(linha: pd.Series, vinculos: pd.DataFrame, decisoes: list[dict]) -> None:
    """Decisão registrada sobre uma divergência de dotação (spec 2026-10-10-emendas-ajuste-dotacao). Nada é gravado
    ao abrir; só o botão de confirmação grava um evento imutável (quem, quando, valor anterior e novo). O relatório
    importado nunca é alterado e a decisão pode ser desfeita."""

    relatorio, anual, diferenca = linha["dotacao_atualizada"], linha["dotacao_anual_ptres"], linha["diferenca_dotacao"]
    st.markdown(
        f"Emenda **{linha['emenda_numero']}** · {linha['parlamentar']} · PTRES {linha['ptres']} · "
        f"exercício {int(linha['ano'])}"
    )
    st.markdown(
        f"Relatório de Emendas: **{_brl_md(relatorio)}**  \n"
        f"Dotação Anual (PTRES): **{_brl_md(anual)}**  \n"
        f"Diferença: **{_brl_md(diferenca)}**"
    )
    opcoes = {
        "adotar_dotacao_anual": f"Adotar a Dotação Anual ({_valor_brl(anual)})",
        "manter_relatorio": f"Manter o relatório ({_valor_brl(relatorio)})",
        "valor_informado": "Informar outro valor",
    }
    if not ptres_com_uma_emenda(vinculos, int(linha["ano"]), str(linha["resultado_primario_cod"]), str(linha["ptres"])):
        del opcoes["adotar_dotacao_anual"]
        st.caption(
            "Este PTRES tem mais de uma emenda: a Dotação Anual é do PTRES inteiro e não pode ser adotada como "
            "dotação de uma só. Mantenha o relatório ou informe o valor desta emenda."
        )
    anterior = _decisao_ativa(decisoes, linha)
    if anterior is not None:
        st.caption(
            f"Há uma decisão anterior ({_data_hora(anterior['registrado_em'])}), obsoleta: ela será desfeita e "
            "substituída por esta, e fica no histórico."
        )
    with st.form("emendas_resolver_dotacao", border=False):
        decisao = st.radio("Decisão", list(opcoes), format_func=opcoes.get)
        valor = st.number_input(
            "Valor (R$) — só para “Informar outro valor”", min_value=0.0, step=1000.0, format="%.2f", value=None,
            placeholder="deixe em branco nas outras opções",
        )
        justificativa = st.text_area("Justificativa", help="Obrigatória, no mínimo 10 caracteres.")
        responsavel = st.text_input("Responsável")
        st.caption(
            "A decisão fica registrada (quem, quando, valor anterior e novo), pode ser desfeita e o valor original "
            "do relatório continua guardado."
        )
        enviado = st.form_submit_button("Registrar decisão", type="primary", icon=":material/check:")
    if not enviado:
        return
    try:
        if anterior is not None:
            ajustes.desfazer_decisao(
                decisao_id=anterior["decisao_id"], responsavel=responsavel, diretorio=ajustes.DIRETORIO_AJUSTES,
                justificativa=f"Substituída por nova decisão (a anterior ficou obsoleta). {justificativa}".strip(),
            )
        ajustes.registrar_decisao(
            vinculos=vinculos, ano=int(linha["ano"]), resultado_primario_cod=str(linha["resultado_primario_cod"]),
            emenda_numero=str(linha["emenda_numero"]), ptres=str(linha["ptres"]), decisao=decisao,
            valor_informado=valor, justificativa=justificativa, responsavel=responsavel,
            diretorio=ajustes.DIRETORIO_AJUSTES,
        )
    except (ErroAjusteDotacao, OSError) as error:
        st.error(str(error))
        return
    st.toast("Decisão registrada.", icon=":material/check_circle:")
    st.rerun()


@st.dialog("Desfazer decisão de dotação")
def _dialogo_desfazer_decisao(decisao: dict) -> None:
    st.markdown(
        f"Emenda **{decisao['emenda_numero']}** · PTRES {decisao['ptres']} · "
        f"{ROTULO_DECISAO[decisao['decisao']]} (valor {_brl_md(decisao['valor_efetivo'])})"
    )
    st.caption("O registro original permanece no histórico; o desfazimento acrescenta um novo evento.")
    with st.form("emendas_desfazer_dotacao", border=False):
        justificativa = st.text_area("Justificativa", help="Obrigatória, no mínimo 10 caracteres.")
        responsavel = st.text_input("Responsável")
        enviado = st.form_submit_button("Desfazer decisão", type="primary")
    if not enviado:
        return
    try:
        ajustes.desfazer_decisao(
            decisao_id=decisao["decisao_id"], justificativa=justificativa, responsavel=responsavel,
            diretorio=ajustes.DIRETORIO_AJUSTES,
        )
    except (ErroAjusteDotacao, OSError) as error:
        st.error(str(error))
        return
    st.toast("Decisão desfeita.", icon=":material/undo:")
    st.rerun()


def _render_divergencias_dotacao(filtradas: pd.DataFrame, vinculos: pd.DataFrame, decisoes: list[dict]) -> None:
    """Lista os PTRES cuja Dotação informada difere da Dotação Anual — só das emendas filtradas e só as PENDENTES
    (decisão ativa encerra o alerta; decisão obsoleta o traz de volta, com aviso). Cada linha tem "Resolver"."""
    divergencias = divergencias_dotacao(vinculos)
    if divergencias.empty or filtradas.empty:
        return
    chaves = filtradas[["ano", "resultado_primario_cod", "emenda_numero"]].drop_duplicates()
    divergencias = divergencias.merge(chaves, on=["ano", "resultado_primario_cod", "emenda_numero"])
    if divergencias.empty:
        return
    with st.container(border=True):
        st.markdown(f"**Dotação informada ≠ Dotação Anual por PTRES** — {len(divergencias)} PTRES")
        st.caption(
            "Os dois valores são exibidos sem indicar qual está correto: não há regra definida "
            "de prevalência. Confira na origem antes de decidir."
        )
        st.caption("Use “Resolver” para registrar a decisão (fica guardada, com justificativa, e pode ser desfeita).")
        tabela = divergencias.assign(
            resultado_primario_cod=divergencias["resultado_primario_cod"].map("RP{}".format),
            dotacao_atualizada=divergencias["dotacao_atualizada"].map(_valor_brl),
            dotacao_anual_ptres=divergencias["dotacao_anual_ptres"].map(_valor_brl),
            diferenca_dotacao=divergencias["diferenca_dotacao"].map(_valor_brl),
        ).rename(
            columns={
                "ano": "Exercício",
                "resultado_primario_cod": "RP",
                "emenda_numero": "Emenda",
                "parlamentar": "Parlamentar",
                "ptres": "PTRES",
                "dotacao_atualizada": "Dotação informada",
                "dotacao_anual_ptres": "Dotação Anual (por PTRES)",
                "diferenca_dotacao": "Diferença",
            }
        )
        colunas_visiveis = [
            "Exercício", "RP", "Emenda", "Parlamentar", "PTRES",
            "Dotação informada", "Dotação Anual (por PTRES)", "Diferença",
        ]
        st.dataframe(tabela[colunas_visiveis], hide_index=True, width="stretch")
        for _, linha in divergencias.iterrows():
            anterior = _decisao_ativa(decisoes, linha)
            if anterior is not None and linha.get("dotacao_decisao_estado") == "obsoleta":
                st.caption(
                    f"Emenda {linha['emenda_numero']} · PTRES {linha['ptres']}: a decisão de "
                    f"{_data_hora(anterior['registrado_em'])} está obsoleta — o relatório mudou de "
                    f"{_brl_md(anterior['valor_relatorio'])} para {_brl_md(linha['dotacao_atualizada'])}. "
                    "Ela não está sendo aplicada."
                )
            chave = f"em_resolver_{int(linha['ano'])}_{linha['resultado_primario_cod']}_{linha['emenda_numero']}_{linha['ptres']}"
            if st.button(f"Resolver — emenda {linha['emenda_numero']} · PTRES {linha['ptres']}", key=chave, icon=":material/rule:"):
                _dialogo_resolver_divergencia(linha, vinculos, decisoes)


def _render_decisoes_dotacao(decisoes: list[dict]) -> None:
    """Histórico das decisões de dotação (ativas, obsoletas, sem efeito e desfeitas), com "Desfazer"."""
    if not decisoes:
        return
    ativas = [d for d in decisoes if not d["desfeita"]]
    with st.expander(f"Decisões de dotação ({len(ativas)} vigente(s) · {len(decisoes)} no histórico)"):
        for decisao in reversed(decisoes):
            linhas = [
                f"**{decisao['emenda_numero']}** · PTRES {decisao['ptres']} · exercício {decisao['ano']} — "
                f"{ROTULO_DECISAO[decisao['decisao']]}",
                f"Relatório {_brl_md(decisao['valor_relatorio'])} → **{_brl_md(decisao['valor_efetivo'])}** "
                f"(Dotação Anual na decisão: {_brl_md(decisao['valor_dotacao_anual'])})",
                f"“{decisao['justificativa']}” — {decisao['responsavel']}, {_data_hora(decisao['registrado_em'])}",
            ]
            if decisao["desfeita"]:
                linhas.append(
                    f"Desfeita por {decisao['desfeita_por']} em {_data_hora(decisao['desfeita_em'])}: "
                    f"{decisao['desfeita_motivo']}"
                )
            st.markdown("  \n".join(linhas))
            if not decisao["desfeita"] and st.button(
                "Desfazer", key=f"em_desfazer_{decisao['decisao_id']}", icon=":material/undo:"
            ):
                _dialogo_desfazer_decisao(decisao)


_ESPECIAIS_MARKDOWN = {ord(c): chr(92) + c for c in chr(92) + "`*_{}[]<>~$|"}


def _md(texto: object) -> str:
    """Texto de dado digitado pelo usuário para `st.markdown`: escapa os caracteres especiais do markdown (`$` inclusive,
    que em pares vira fórmula)."""

    return str(texto).translate(_ESPECIAIS_MARKDOWN)


def _fmt_data(valor: object) -> str:
    return "—" if valor is None or pd.isna(valor) else pd.Timestamp(valor).strftime("%d/%m/%Y")


def _texto_ou_nao_informado(valor: object) -> str:
    return "_não informado_" if valor is None or pd.isna(valor) else _md(valor)


@st.dialog("Registrar status da tramitação")
def _dialogo_registrar_status(chave: tuple, chaves_validas: set) -> None:
    """Registro de status (spec acompanhamento): lista sugerida + "Outro". Só o botão de confirmação grava um evento
    imutável; a data pode ser retroativa, nunca futura."""

    st.markdown(f"Emenda **{_md(chave[2])}** · RP{chave[1]} · exercício {chave[0]}")
    with st.form("emendas_registrar_status", border=False):
        status = st.selectbox("Status", [*STATUS_SUGERIDOS, STATUS_OUTRO])
        status_outro = st.text_input("Descrição do status (obrigatória se for “Outro”)")
        data_status = st.date_input("Data do status", value=date.today(), max_value=date.today(), format="DD/MM/YYYY")
        observacao = st.text_area("Observação", help="Opcional, até 500 caracteres.")
        responsavel = st.text_input("Responsável")
        enviado = st.form_submit_button("Registrar status", type="primary", icon=":material/check:")
    if not enviado:
        return
    try:
        acomp.registrar_status(
            chave=chave, status=status, status_outro=status_outro, data_status=data_status, observacao=observacao,
            responsavel=responsavel, chaves_validas=chaves_validas, diretorio=acomp.DIRETORIO_ACOMPANHAMENTO,
        )
    except (ErroAcompanhamento, OSError) as error:
        st.error(str(error))
        return
    st.toast("Status registrado.", icon=":material/check_circle:")
    st.rerun()


@st.dialog("Cancelar registro de status")
def _dialogo_cancelar_status(evento_id: str, rotulo: str) -> None:
    st.markdown(f"Cancelar o registro: **{_md(rotulo)}**")
    st.caption("O registro original permanece no histórico (riscado); o cancelamento acrescenta um novo evento.")
    with st.form("emendas_cancelar_status", border=False):
        motivo = st.text_area("Motivo", help="Obrigatório, no mínimo 10 caracteres.")
        responsavel = st.text_input("Responsável")
        enviado = st.form_submit_button("Cancelar registro", type="primary")
    if not enviado:
        return
    try:
        acomp.cancelar_status(
            evento_id=evento_id, motivo=motivo, responsavel=responsavel, diretorio=acomp.DIRETORIO_ACOMPANHAMENTO
        )
    except (ErroAcompanhamento, OSError) as error:
        st.error(str(error))
        return
    st.toast("Registro cancelado.", icon=":material/undo:")
    st.rerun()


@st.dialog("Objeto e destinatário")
def _dialogo_editar_complemento(chave: tuple, objeto_atual: object, destinatario_atual: object, chaves_validas: set) -> None:
    st.markdown(f"Emenda **{_md(chave[2])}** · RP{chave[1]} · exercício {chave[0]}")
    with st.form("emendas_editar_complemento", border=False):
        objeto = st.text_area("Objeto", value="" if pd.isna(objeto_atual) else str(objeto_atual), help="Até 500 caracteres.")
        destinatario = st.text_input(
            "Destinatário", value="" if pd.isna(destinatario_atual) else str(destinatario_atual), help="Até 200 caracteres."
        )
        motivo = st.text_input("Motivo da alteração (opcional)")
        responsavel = st.text_input("Responsável")
        st.caption("Campo em branco = não informado. Cada alteração fica registrada com o valor anterior.")
        enviado = st.form_submit_button("Salvar", type="primary", icon=":material/check:")
    if not enviado:
        return
    try:
        acomp.definir_complemento(
            chave=chave, objeto=objeto, destinatario=destinatario, responsavel=responsavel, motivo=motivo,
            chaves_validas=chaves_validas, diretorio=acomp.DIRETORIO_ACOMPANHAMENTO,
        )
    except (ErroAcompanhamento, OSError) as error:
        st.error(str(error))
        return
    st.toast("Objeto e destinatário registrados.", icon=":material/check_circle:")
    st.rerun()


def _render_acompanhamento(linha, tramitacao_emenda: pd.DataFrame, complemento, atual: str | None) -> None:
    """Acompanhamento manual da emenda: objeto, destinatário e histórico da tramitação (status atual + registros,
    inclusive os cancelados, riscados). Vale para qualquer exercício."""

    chave = (int(linha.ano), str(linha.resultado_primario_cod), str(linha.emenda_numero))
    chave_texto = f"{chave[0]}_{chave[1]}_{chave[2]}"
    objeto = getattr(complemento, "objeto", None)
    destinatario = getattr(complemento, "destinatario", None)
    with st.expander(f"Acompanhamento — {atual or 'sem status registrado'}"):
        st.markdown(
            f"**Objeto:** {_texto_ou_nao_informado(objeto)}  \n**Destinatário:** {_texto_ou_nao_informado(destinatario)}"
        )
        if st.button("Editar objeto e destinatário", key=f"em_complemento_{chave_texto}", icon=":material/edit:"):
            _dialogo_editar_complemento(
                chave, pd.NA if objeto is None else objeto, pd.NA if destinatario is None else destinatario, chaves_validas
            )
        st.markdown("**Tramitação**")
        if tramitacao_emenda.empty:
            st.caption("Nenhum status registrado.")
        for registro in tramitacao_emenda.iloc[::-1].itertuples():
            corpo = f"{_fmt_data(registro.data_status)} — **{_md(registro.status)}** · {_md(registro.responsavel)}"
            if registro.observacao:
                corpo += f" · {_md(registro.observacao)}"
            if registro.cancelado:
                corpo = (
                    f"~~{corpo}~~  \ncancelado por {_md(registro.cancelado_por)} em {_data_hora(registro.cancelado_em)}: "
                    f"{_md(registro.cancelado_motivo)}"
                )
            st.markdown(corpo)
            if not registro.cancelado and st.button(
                "Cancelar registro", key=f"em_cancelar_status_{registro.evento_id}", icon=":material/undo:"
            ):
                _dialogo_cancelar_status(registro.evento_id, f"{_fmt_data(registro.data_status)} — {registro.status}")
        if st.button("Registrar status", key=f"em_status_{chave_texto}", icon=":material/add:", type="primary"):
            _dialogo_registrar_status(chave, chaves_validas)


def _render_orfaos(orfaos: list[dict]) -> None:
    """Registros de acompanhamento cuja emenda não existe mais nos dados atuais: nada é escondido nem descartado."""

    if not orfaos:
        return
    with st.expander(f"Registros sem emenda correspondente ({len(orfaos)})"):
        st.caption("Estes registros continuam guardados, mas a emenda deixou de aparecer nos dados atuais.")
        for item in orfaos:
            st.markdown(
                f"**{_md(item['emenda_numero'])}** · RP{item['resultado_primario_cod']} · exercício {item['ano']} — "
                f"{_md(item['resumo'])} ({_md(item['responsavel'])}, {_data_hora(item['registrado_em'])})"
            )


_render_divergencias_dotacao(filtradas, resultado.vinculos, decisoes_dotacao)
_render_decisoes_dotacao(decisoes_dotacao)
_render_orfaos(orfaos_acompanhamento)

REGISTRO_PROPORCOES = [3.3, 0.9, 1.55, 2.0, 1.3, 1.3, 2.0, 1.0]
REGISTRO_CABECALHOS = [
    ("Emenda / Parlamentar", False), ("Exercício", False), ("Dotação", True), ("Executado (empenhado)", False),
    ("Liquidado", True), ("Pago", True), ("Situação", False), ("Ações", False),
]
#: origem dos valores -> (texto, tom) do chip de situação. Vermelho só para problema real; "aguardando execução"
#: é o estado normal de uma emenda recente.
SITUACAO_POR_ORIGEM = {
    "relatorio_estatico": ("Histórico", "neutro"),
    "sem_execucao": ("Aguardando execução", "info"),
    "execucao_anual_parcial": ("Execução parcial", "info"),
    "execucao_anual": ("Em execução", "ok"),
}


def _alternar_detalhe(chave_texto: str) -> None:
    """`on_click` do botão "Detalhes"/"Fechar": roda ANTES de a página ser redesenhada, então o rótulo do botão já
    sai certo (alternar depois de desenhar o botão deixava o rótulo uma interação atrasado)."""

    abertas = st.session_state.setdefault("em_abertas", [])
    if chave_texto in abertas:
        abertas.remove(chave_texto)
    else:
        abertas.append(chave_texto)


def _celula_execucao(empenhada: object, dotacao: object) -> str:
    """Barra de execução (empenhado ÷ dotação). Sem empenhado ou sem dotação positiva: sem barra preenchida e o
    valor (ou "—") — nulo nunca vira 0%."""

    if pd.isna(empenhada) or pd.isna(dotacao) or float(dotacao) <= 0:
        texto = "—" if pd.isna(empenhada) else _valor_brl(empenhada)
        percentual = 0.0
    else:
        percentual = min(100.0, float(empenhada) / float(dotacao) * 100)
        texto = f"{percentual:.0f}% · {_valor_brl(empenhada)}"
    cheia = " cheia" if percentual >= 99.5 else ""
    return (
        f'<div class="em-bar{cheia}"><i style="width:{percentual:.0f}%"></i></div>'
        f'<div class="cad-sub">{_esc(texto)}</div>'
    )


def _render_registro(
    filtradas: pd.DataFrame, vinculos: pd.DataFrame, status_por_chave: dict, complemento_por_chave: dict,
    tramitacao: pd.DataFrame,
) -> None:
    """Registro compacto de emendas (uma linha por emenda, no padrão de `src/ui_cadastro` usado em Contratos
    Contínuos). "Detalhes" abre, na própria linha, o cartão com os PTRES (se houver mais de um), as decisões de
    dotação e o acompanhamento. Mesmos números do cartão antigo; só a apresentação mudou."""

    ordenadas = filtradas.sort_values(["ano", "dotacao_atualizada"], ascending=[False, False], na_position="last")
    abertas = st.session_state.setdefault("em_abertas", [])
    st.markdown('<div class="cad-secao-titulo">Registro de emendas</div>', unsafe_allow_html=True)
    with st.container(key="cad_registro"):
        st.markdown(
            f'<div class="cad-contagem">{len(ordenadas)} emenda(s) · '
            f'{_esc(_valor_brl(_total(ordenadas["dotacao_atualizada"])))} de dotação</div>',
            unsafe_allow_html=True,
        )
        for coluna, (texto, direita) in zip(st.columns(REGISTRO_PROPORCOES), REGISTRO_CABECALHOS):
            coluna.markdown(
                f'<div class="cad-cabecalho{" direita" if direita else ""}">{texto}</div>', unsafe_allow_html=True
            )
        with st.container(key="em_registro_scroll"):
            for linha in ordenadas.itertuples():
                chave = (int(linha.ano), str(linha.resultado_primario_cod), str(linha.emenda_numero))
                chave_texto = f"{chave[0]}_{chave[1]}_{chave[2]}"
                vinculos_da_emenda = vinculos[
                    (vinculos["ano"] == linha.ano)
                    & (vinculos["resultado_primario_cod"] == linha.resultado_primario_cod)
                    & (vinculos["emenda_numero"] == linha.emenda_numero)
                    & (vinculos["autor_emenda"] == linha.autor_emenda)
                    & (vinculos["parlamentar"] == linha.parlamentar)
                ]
                status_emenda = status_por_chave.get(chave)
                status_texto = getattr(status_emenda, "status", None)
                pendente = bool(getattr(linha, "dotacao_divergencia_pendente", getattr(linha, "dotacao_divergente", False)))
                decidida = (
                    "dotacao_decisao_estado" in vinculos_da_emenda.columns
                    and bool(vinculos_da_emenda["dotacao_decisao_estado"].eq("ativa").fillna(False).any())
                )
                texto_situacao, tom = SITUACAO_POR_ORIGEM.get(str(linha.origem_valores), (str(linha.origem_valores), "neutro"))
                parlamentar = "(não informado)" if pd.isna(linha.parlamentar) else linha.parlamentar
                ptres_total = int(linha.ptres_total)
                subtitulo = f"RP{linha.resultado_primario_cod} · " + (
                    f"PTRES {_juntar_codigos(linha.ptres)}" if ptres_total == 1 else f"{ptres_total} PTRES"
                )
                with st.container(key=f"cad_linha_{chave_texto}"):
                    cel = st.columns(REGISTRO_PROPORCOES, vertical_alignment="center")
                    cel[0].markdown(celula_principal(f"{linha.emenda_numero} — {parlamentar}", subtitulo), unsafe_allow_html=True)
                    cel[1].markdown(celula_suave(int(linha.ano)), unsafe_allow_html=True)
                    dotacao_html = celula_valor(linha.dotacao_atualizada)
                    if decidida and hasattr(linha, "dotacao_relatorio"):
                        dotacao_html += (
                            f'<div class="cad-sub" style="text-align:right">relatório: {_esc(_valor_brl(linha.dotacao_relatorio))}</div>'
                        )
                    cel[2].markdown(dotacao_html, unsafe_allow_html=True)
                    cel[3].markdown(_celula_execucao(linha.empenhada, linha.dotacao_atualizada), unsafe_allow_html=True)
                    cel[4].markdown(celula_valor(linha.liquidada), unsafe_allow_html=True)
                    cel[5].markdown(celula_valor(linha.paga), unsafe_allow_html=True)
                    chips = chip(texto_situacao, tom)
                    if pendente:
                        chips += " " + chip("Divergência de dotação", "warn")
                    elif decidida:
                        chips += " " + chip("Dotação decidida", "ok")
                    cel[6].markdown(
                        chips + f'<div class="cad-sub">Tramitação: {_esc(status_texto or "—")}</div>', unsafe_allow_html=True
                    )
                    with cel[7]:
                        with st.container(key=f"cad_acoes_{chave_texto}"):
                            st.button(
                                "Fechar" if chave_texto in abertas else "Detalhes", key=f"em_detalhe_{chave_texto}",
                                use_container_width=True, on_click=_alternar_detalhe, args=(chave_texto,),
                            )
                if chave_texto in abertas:
                    with st.container(key=f"em_painel_{chave_texto}"):
                        _render_card_emenda(linha, vinculos_da_emenda, status_texto)
                        _render_acompanhamento(
                            linha,
                            tramitacao[
                                (tramitacao["ano"] == chave[0])
                                & (tramitacao["resultado_primario_cod"] == chave[1])
                                & (tramitacao["emenda_numero"] == chave[2])
                            ],
                            complemento_por_chave.get(chave),
                            status_texto,
                        )


if filtradas.empty:
    st.info("Nenhuma emenda corresponde aos filtros selecionados.")
else:
    _render_registro(filtradas, resultado.vinculos, status_por_chave, complemento_por_chave, tramitacao)

st.caption(
    f"Base de Emendas: {manifesto_emendas.rotulo} · hash "
    f"{manifesto_emendas.sha256[:8]} · Execução Anual: hash "
    f"{manifesto_execucao.sha256[:8]}"
    + (
        ""
        if dotacao_anual is None
        else f" · Dotação Anual: hash {ManifestoDotacao.atual().sha256[:8]}"
    )
    + ". Valores anteriores a 2026 permanecem "
    "estáticos; valores executados de 2026+ são conciliados por RP e PTRES."
)
