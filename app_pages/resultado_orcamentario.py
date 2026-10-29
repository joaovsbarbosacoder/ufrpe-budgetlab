"""Resultado Orçamentário — a dotação das células escolhidas cobre o que ainda falta empenhar?

Pedido explícito do usuário (08/10/2026): o usuário marca um "bolsão" de células da Dotação Anual
(IDUSO, resultado primário, ação, PTRES, plano orçamentário, grupo de despesa e fonte detalhada) e a
página mostra `Resultado = Dotação Atualizada das células − Executado − Projetado a realizar até dezembro`
(critério de 15/10/2026: Contratos e Bolsas pelo liquidado e pelo que falta da projeção, só as NEs com empenho nas
células marcadas; as demais origens pelo empenhado). A regra está em `src/resultado_orcamentario.py`; a persistência (seleção de
células e despesas manuais, aprovada pelo usuário em 08/10/2026) em
`src/resultado_orcamentario_cadastro.py`; a montagem de Contratos e Bolsas, compartilhada com as
páginas deles, em `src/resultado_orcamentario_fontes.py`. Especificação e protótipo de layout:
`docs/superpowers/specs/2026-10-08-resultado-orcamentario-design.md` e `...-mockup.html`. Esta página é
só apresentação: não recalcula nenhuma regra.

Decisões de tela (08/10/2026):
  * A conta reflete a seleção EM EDIÇÃO na tabela de células (como no protótipo, que recalcula ao
    marcar); "Salvar seleção" grava em disco. Enquanto não salvar, a página avisa "Alterações não
    salvas". Motivo: o usuário experimenta o bolsão antes de gravar. Como os cartões ficam acima da
    tabela, eles são desenhados em `st.container` reservados no topo e preenchidos no fim do script.
  * Executado e projetado de Contratos e Bolsas = relatório "Projeção pela Execução" SEM contrato antecessor
    (spec §10a: a escolha do antecessor na página de Contratos não é gravada).
  * Liquidação por Competência ausente/ilegível, ou exercício sem cadastro de Contratos/Bolsas: a
    projeção daquela origem fica INDISPONÍVEL ("—"), nunca zero, e o resultado fica incompleto.
  * Arquivo de seleção ou de despesas corrompido: erro visível e os botões de gravar ficam
    desabilitados (a página não grava por cima). Despesas ilegíveis também deixam o resultado
    incompleto — a página não sabe quanto elas somam.
  * Resultado exatamente zero aparece como "Equilíbrio" (o protótipo só tinha Superávit/Déficit; zero
    não é superávit — nulo, zero e negativo são estados distintos neste projeto).
"""

from __future__ import annotations

import gc
import hashlib
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src import bolsas_auxilios_cadastro as cadastro_bolsas
from src import contratos_continuos_cadastro as cadastro_contratos
from src import design_tokens as dt
from src import resultado_orcamentario_cadastro as cadastro
from src.execucao_ne_utils import ne_curta as _ne_curta_execucao, saldo_por_ne
from src.importacao_dotacao import DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_DOTACAO
from src.importacao_dotacao import Manifesto as ManifestoDotacao
from src.importacao_dotacao import NOME_PONTEIRO as PONTEIRO_DOTACAO
from src.importacao_dotacao import carregar_atual as carregar_dotacao_atual
from src.importacao_execucao_mensal import DIRETORIO_MANIFESTOS_PADRAO as DIR_MANIFESTOS_EXECUCAO_MENSAL
from src.importacao_execucao_mensal import Manifesto as ManifestoExecucaoMensal
from src.importacao_execucao_mensal import NOME_PONTEIRO as PONTEIRO_EXECUCAO_MENSAL
from src.importacao_execucao_mensal import carregar_atual as carregar_execucao_mensal_atual
from src.liquidacao_competencia import ler_liquidacao_competencia, liquidado_por_ne, liquidado_por_ne_e_mes
from src.liquidacao_consumo import competencia_pelo_consumo
from src import projecao_ajustes
from src.projecao_ajustes import ErroAjuste, ajustes_vigentes
from src.relatorio_necessidade_empenho import mes_referencia_do_exercicio
from src.resultado_orcamentario import (
    ORIGEM_BOLSAS,
    ORIGEM_CONTRATOS,
    ORIGEM_OUTROS,
    ORIGENS_EMPENHADO,
    OUTRAS_DESPESAS,
    TOLERANCIA_CONFERENCIA,
    ResultadoOrcamentario,
    calcular_resultado,
    celulas_da_dotacao,
    empenhado_por_ne_e_celula,
    separar_ativos_sem_ne,
    soma_ou_nulo,
)
from src.resultado_orcamentario_detalhe import detalhar_por_gnd_acao
from src.resultado_orcamentario_planos import planos_discricionarios, selecao_discricionaria
from src.resultado_orcamentario_relatorio import html_relatorio
from src.resultado_orcamentario_cadastro import ArquivoCorrompido, CelulaChave, DespesaManual, ReceitaPropria
from src import resultado_orcamentario_historico as historico_ro
from src.relatorio_projecao_execucao import RelatorioProjecaoExecucao
from src.resultado_orcamentario_fontes import projecao_bolsas, projecao_contratos, tabela_bolsas, tabela_contratos
from src.sobra_empenho import (
    ContextoSobra,
    gerar_xlsx as gerar_xlsx_sobra,
    resumo_da_sobra,
    sobra_por_ne,
)
from src.tesouro_execucao_mensal import agregar_por_ne, linha_do_tempo_por_ne, primeiro_mes_com_empenho_por_ne
from src.ui_cadastro import formatar_brl
from src.ui_resultado_planos import html_planos_discricionarios
from src.ui_resultado_orcamentario import (
    AGRUPAR_ACAO,
    AGRUPAR_GND,
    ESTILO_CELULAS,
    LinhaComposicao,
    html_bloco,
    html_cabecalho_acao,
    html_cartoes,
    html_celula,
    html_detalhe_gnd_acao,
    html_dotacao_acao,
    html_rodape_totais,
)
from src.ui_theme import currency_column, render_page_header


def _estilo_historico(df: pd.DataFrame, monetarias: tuple[str, ...], com_sinal: tuple[str, ...] = ()):
    """Styler só de apresentação: moeda em pt-BR, nulo como "—" e variações em verde (sobe) / vermelho (cai).

    Só apresentação: o DataFrame de origem (numérico) não é alterado; cores saem do valor original, sem arredondar."""

    def _moeda(v):
        return "—" if pd.isna(v) else formatar_brl(v)

    def _cor(v):
        if pd.isna(v) or v == 0:
            return "color: #6b7280"
        return "color: #15803d; font-weight: 600" if v > 0 else "color: #b91c1c; font-weight: 600"

    def _cor_situacao(v):
        if v == "Superávit":
            return "color: #15803d; font-weight: 600"
        if v == "Déficit":
            return "color: #b91c1c; font-weight: 600"
        return ""

    # O Streamlit mostra "None" para célula nula mesmo com na_rep; por isso a tabela exibida é de texto, já com "—".
    exibida = df.astype(object).copy()
    for c in df.columns:
        if c in monetarias:
            exibida[c] = [_moeda(v) for v in df[c]]
        else:
            exibida[c] = ["—" if pd.isna(v) else v for v in df[c]]
    estilos = pd.DataFrame("", index=df.index, columns=df.columns)
    for c in monetarias:
        estilos[c] = "text-align: right"
    for c in com_sinal:
        estilos[c] = [f"text-align: right; {_cor(v)}" for v in df[c]]
    if "Situação" in df.columns:
        estilos["Situação"] = [_cor_situacao(v) for v in df["Situação"]]
    return exibida.style.apply(lambda _: estilos, axis=None)


def _sem_latex(texto: str) -> str:
    """Escapa o "$" de "R$" (08/10/2026): o Markdown do Streamlit lê o trecho entre dois "$" como fórmula
    LaTeX e some com o cifrão quando um texto tem dois valores em reais (visto nos avisos da projeção)."""

    return texto.replace("$", "\\$")


#: mesmo arquivo de `app_pages/contratos_continuos.py` e `app_pages/bolsas_auxilios.py`.
CAMINHO_LIQUIDACAO_COMPETENCIA = Path("data/raw") / "Liquidação por Competência.xlsx"

_CHAVE_FLASH = "ro_mensagem"

#: colunas da tabela de células (rótulo exibido → coluna de `celulas_da_dotacao`), na ordem do protótipo.
_COLUNAS_CELULA = {
    "Iduso": "iduso_codigo",
    "RP": "resultado_primario_codigo",
    "Ação": "acao_codigo",
    "PTRES": "ptres_codigo",
    "PO": "plano_orcamentario_codigo",
    "GND": "grupo_despesa_codigo",
    "Fonte detalhada": "fonte_recursos_detalhada_codigo",
    "Descrição da ação": "acao_descricao",
}


# ------------------------------------------------------------------- leituras (cache)
@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def _cached_celulas_por_exercicio(caminho_ponteiro: str, mtime_ponteiro: float) -> dict[int, pd.DataFrame]:
    """Células (`celulas_da_dotacao`) de cada exercício presente na Dotação Anual. Guarda só o
    derivado, não a base inteira (memória: ver o comentário de `gc.collect()` no fim da página).
    `caminho_ponteiro`/`mtime_ponteiro` só participam da chave de cache."""

    dotacao = carregar_dotacao_atual()
    anos = sorted(int(ano) for ano in dotacao["ano_lancamento"].dropna().unique())
    return {ano: celulas_da_dotacao(dotacao, ano) for ano in anos}


@st.cache_data(show_spinner="Lendo a base de Execução Mensal...")
def _cached_execucao(
    caminho_ponteiro: str, mtime_ponteiro: float, exercicio: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """`(empenhado por NE e célula no exercício, saldo por NE, mês do primeiro empenho por NE)` — uma
    só leitura da Execução Mensal. Saldo e primeiro empenho são as mesmas entradas que as páginas de
    Contratos e Bolsas montam (`saldo_por_ne(agregar_por_ne(...))`, `primeiro_mes_com_empenho_por_ne`)."""

    execucao = carregar_execucao_mensal_atual()
    empenhado = empenhado_por_ne_e_celula(execucao, exercicio)
    por_ne_execucao = saldo_por_ne(agregar_por_ne(execucao))
    tempo = linha_do_tempo_por_ne(execucao)
    tempo["ne_curta"] = tempo["ne_ccor"].apply(_ne_curta_execucao)
    return empenhado, por_ne_execucao, primeiro_mes_com_empenho_por_ne(tempo)


@st.cache_data(show_spinner="Lendo a liquidação por mês de lançamento...")
def _cached_lancamento(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    """Liquidado por (NE, mês de LANÇAMENTO) da Execução Mensal, com `ne_curta` — usado só para medir pelo consumo
    do orçamento as NEs com competência em exercício posterior (`src/liquidacao_consumo.py`)."""

    tempo = linha_do_tempo_por_ne(carregar_execucao_mensal_atual())
    tempo["ne_curta"] = tempo["ne_ccor"].apply(_ne_curta_execucao)
    return tempo


@st.cache_data(show_spinner="Lendo a Liquidação por Competência...")
def _cached_liquidacao_competencia(caminho: str, mtime: float) -> tuple[pd.Series, pd.DataFrame]:
    """`(total liquidado por NE curta, liquidado por NE e mês com ne_curta)` — as duas leituras que
    `app_pages/contratos_continuos.py` faz em separado, aqui numa só. `mtime` só participa da chave."""

    base = ler_liquidacao_competencia(caminho)
    totais = liquidado_por_ne(base)
    indice = pd.Series(totais.to_numpy(), index=[_ne_curta_execucao(ne) for ne in totais.index])
    por_mes = liquidado_por_ne_e_mes(base)
    por_mes["ne_curta"] = por_mes["ne_ccor"].apply(_ne_curta_execucao)
    return indice, por_mes


# ------------------------------------------------------------------- formatação
def _pct(parte: float | None, total: float | None) -> str:
    if parte is None or total is None or pd.isna(parte) or pd.isna(total) or not total:
        return "—"
    return f"{parte / total * 100:.0f}%"


def _rotulo_celula(chave: CelulaChave | None) -> str:
    if chave is None:
        return "—"
    iduso, rp, acao, ptres, po, gnd, fonte = (("—" if p is None else p) for p in chave)
    return f"{acao} · PTRES {ptres} · PO {po} · GND {gnd} · Fonte {fonte} · IDUSO {iduso} · RP {rp}"


def _avisos_com_ok(avisos: list[str], escopo: str, exercicio: int) -> None:
    """Mostra os avisos, cada um com um "OK" que o tira da página (pedido de 20/10/2026).

    O OK é gravado por exercício (`avisos_ok.json`, persistência aprovada em 20/10/2026) e vale pelo TEXTO do aviso: se o
    fato muda (outro valor, outra NE), o texto muda e o aviso volta. "Mostrar avisos ocultados" desfaz. Arquivo ilegível:
    erro visível, nenhum aviso é ocultado e os botões não gravam por cima."""

    try:
        ocultos = cadastro.carregar_avisos_ok(exercicio, diretorio=cadastro.DIRETORIO_PADRAO)
        legivel = True
    except ArquivoCorrompido as erro:
        ocultos, legivel = set(), False
        st.error(f"{erro}. Os OK dos avisos não puderam ser lidos; corrija ou restaure o arquivo — a página não grava por cima.")
    unicos = list(dict.fromkeys(avisos))
    for aviso in [a for a in unicos if a not in ocultos]:
        coluna_texto, coluna_ok = st.columns([12, 1], vertical_alignment="center")
        with coluna_texto:
            if aviso.startswith("Nenhuma célula selecionada"):
                st.info(_sem_latex(aviso))
            else:
                st.warning(_sem_latex(aviso))
        digest = hashlib.sha1(f"{escopo}|{aviso}".encode("utf-8")).hexdigest()[:12]
        if coluna_ok.button(
            "OK", key=f"ro_aviso_ok_{exercicio}_{digest}", help="Dar ciência e ocultar este aviso", disabled=not legivel,
        ):
            cadastro.salvar_avisos_ok(exercicio, ocultos | {aviso}, diretorio=cadastro.DIRETORIO_PADRAO)
            st.rerun()
    escondidos = [a for a in unicos if a in ocultos]
    if escondidos and st.button(
        f"Mostrar {len(escondidos)} aviso(s) ocultado(s)", key=f"ro_aviso_mostrar_{exercicio}_{escopo}", type="tertiary",
    ):
        cadastro.salvar_avisos_ok(exercicio, ocultos - set(escondidos), diretorio=cadastro.DIRETORIO_PADRAO)
        st.rerun()


def _mensagem(texto: str) -> None:
    st.session_state[_CHAVE_FLASH] = texto


# ------------------------------------------------------------------- necessidade
def _necessidade(
    origem: str,
    exercicio: int,
    por_ne_execucao: pd.DataFrame,
    sugestao_inicio: pd.Series,
    indice_competencia: pd.Series | None,
    competencia: pd.DataFrame | None,
    mes_referencia: int,
    lancamento: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame, str | None, list[str], RelatorioProjecaoExecucao | None]:
    """`(cadastro com colunas derivadas, linhas da projeção ou None, sem_ne, motivo da indisponibilidade,
    avisos do relatório de projeção, relatório de projeção ou None)` — o relatório inteiro alimenta "Sobra prevista de
    empenho" (`src/sobra_empenho.py`).

    Exercício sem cadastro ou Liquidação por Competência indisponível: linhas `None` (necessidade
    indisponível, não zero) e um motivo para o aviso."""

    vazio = pd.DataFrame(columns=["ne_curta"])
    modulo = cadastro_contratos if origem == ORIGEM_CONTRATOS else cadastro_bolsas
    if exercicio not in modulo.anos_disponiveis():
        return vazio, None, vazio, f"não há cadastro de {origem} para o exercício {exercicio}", [], None
    if origem == ORIGEM_CONTRATOS:
        dados = cadastro_contratos.como_dataframe(cadastro_contratos.carregar_contratos(exercicio), exercicio)
        tabela = tabela_contratos(dados, por_ne_execucao, indice_competencia, sugestao_inicio)
    else:
        dados = cadastro_bolsas.como_dataframe(cadastro_bolsas.carregar_programas(exercicio))
        tabela = tabela_bolsas(dados, por_ne_execucao, sugestao_inicio)
    if competencia is None:
        return tabela, None, vazio, "a Liquidação por Competência não está disponível", [], None
    if origem == ORIGEM_CONTRATOS:
        # Sem `antecessores` de propósito (spec §10a): NE sem histórico = fator 1, valor mensal cheio.
        # Mesma troca da página de Contratos (13/10/2026): competência futura vale pelo mês do lançamento.
        pelo_consumo = competencia_pelo_consumo(competencia, lancamento, exercicio)
        # Ajustes manuais do esperado (14/10/2026): log ilegível → metodologia, avisado, e nada é gravado por cima.
        avisos_ajustes: list[str] = []
        try:
            ajustes = ajustes_vigentes(exercicio)
        except ErroAjuste as erro:
            ajustes = {}
            avisos_ajustes.append(f"Ajustes da projeção ilegíveis — usada a metodologia: {erro}")
        relatorio, sem_ne = projecao_contratos(
            tabela, pelo_consumo.dados, exercicio, mes_referencia, nes_pelo_lancamento=pelo_consumo.nes_trocadas,
            ajustes=ajustes,
        )
        return tabela, relatorio.linhas, sem_ne, None, [*avisos_ajustes, *pelo_consumo.avisos(), *relatorio.avisos], relatorio
    else:
        # Ajustes manuais de Bolsas (15/10/2026; pasta própria): log ilegível → metodologia, avisado, nada é gravado.
        avisos_ajustes_bolsas: list[str] = []
        try:
            ajustes_b = ajustes_vigentes(exercicio, projecao_ajustes.DIRETORIO_AJUSTES_BOLSAS)
        except ErroAjuste as erro:
            ajustes_b = {}
            avisos_ajustes_bolsas.append(f"Ajustes da projeção de Bolsas ilegíveis — usada a metodologia: {erro}")
        relatorio, sem_ne = projecao_bolsas(tabela, competencia, exercicio, mes_referencia, ajustes=ajustes_b)
        return tabela, relatorio.linhas, sem_ne, None, [*avisos_ajustes_bolsas, *relatorio.avisos], relatorio
    return tabela, relatorio.linhas, sem_ne, None, relatorio.avisos, relatorio


# ------------------------------------------------------------------- diálogos
def _opcoes_celula(chaves: list[CelulaChave], atual: CelulaChave | None = None) -> list[CelulaChave | None]:
    opcoes: list[CelulaChave | None] = [None, *chaves]
    # célula informativa que não existe mais na base continua como opção, para não sumir em silêncio
    if atual is not None and atual not in opcoes:
        opcoes.append(atual)
    return opcoes


@st.dialog("Editar despesa")
def _dialogo_editar(exercicio: int, despesa: DespesaManual, chaves: list[CelulaChave]) -> None:
    opcoes = _opcoes_celula(chaves, despesa.celula)
    with st.form("ro_editar_despesa"):
        descricao = st.text_input("Descrição", value=despesa.descricao)
        valor = st.number_input("Valor a empenhar (R$)", value=float(despesa.valor), min_value=0.0, step=100.0, format="%.2f")
        observacao = st.text_input("Observação", value=despesa.observacao or "")
        celula = st.selectbox(
            "Célula (informativa)", opcoes, index=opcoes.index(despesa.celula), format_func=_rotulo_celula,
        )
        if st.form_submit_button("Salvar", type="primary"):
            erros = cadastro.validar_despesa(descricao, valor)
            for erro in erros:
                st.error(erro)
            if not erros:
                try:
                    cadastro.atualizar_despesa(
                        exercicio, despesa.id, descricao, valor, observacao.strip() or None, celula,
                        diretorio=cadastro.DIRETORIO_PADRAO,
                    )
                except KeyError:
                    st.error("Esta despesa não existe mais (pode ter sido excluída em outra aba). Nada foi gravado.")
                except ArquivoCorrompido as erro:
                    st.error(f"{erro} — nada foi gravado.")
                else:
                    _mensagem(f'Despesa "{descricao.strip()}" atualizada.')
                    st.rerun()


def _alternar_consideracao(exercicio: int, id_despesa: str) -> None:
    """`on_change` da caixa "Considerar" de uma despesa: grava a escolha (não é edição: `atualizado_em` não muda)."""

    try:
        cadastro.definir_consideracao(
            exercicio, id_despesa, bool(st.session_state[f"ro_considerar_{id_despesa}"]), diretorio=cadastro.DIRETORIO_PADRAO,
        )
    except KeyError:
        _mensagem("Esta despesa não existe mais (pode ter sido excluída em outra aba). Nada foi gravado.")
    except ArquivoCorrompido as erro:
        _mensagem(f"{erro} — nada foi gravado.")


def _alternar_consideracao_receita(exercicio: int, id_receita: str) -> None:
    try:
        cadastro.definir_consideracao_receita(
            exercicio, id_receita, bool(st.session_state[f"ro_considerar_rec_{id_receita}"]), diretorio=cadastro.DIRETORIO_PADRAO,
        )
    except KeyError:
        _mensagem("Esta receita não existe mais (pode ter sido excluída em outra aba). Nada foi gravado.")
    except ArquivoCorrompido as erro:
        _mensagem(f"{erro} — nada foi gravado.")


@st.dialog("Excluir receita")
def _dialogo_excluir_receita(exercicio: int, receita: ReceitaPropria) -> None:
    st.write(f'Excluir "{receita.descricao}" ({formatar_brl(receita.valor)})? A exclusão não pode ser desfeita.')
    if st.button("Excluir", type="primary", key="ro_confirmar_exclusao_receita"):
        try:
            cadastro.excluir_receita(exercicio, receita.id, diretorio=cadastro.DIRETORIO_PADRAO)
        except ArquivoCorrompido as erro:
            st.error(f"{erro} — nada foi gravado.")
        else:
            _mensagem(f'Receita "{receita.descricao}" excluída.')
            st.rerun()


@st.dialog("Excluir despesa")
def _dialogo_excluir(exercicio: int, despesa: DespesaManual) -> None:
    st.write(f'Excluir "{despesa.descricao}" ({formatar_brl(despesa.valor)})? A exclusão não pode ser desfeita.')
    if st.button("Excluir", type="primary", key="ro_confirmar_exclusao"):
        try:
            cadastro.excluir_despesa(exercicio, despesa.id, diretorio=cadastro.DIRETORIO_PADRAO)
        except ArquivoCorrompido as erro:
            st.error(f"{erro} — nada foi gravado.")
        else:
            _mensagem(f'Despesa "{despesa.descricao}" excluída.')
            st.rerun()


# ------------------------------------------------------------------- seções
def _nota_limite_receita(res: ResultadoOrcamentario) -> str:
    """Rodapé do cartão de dotação quando a arrecadação própria limitou a dotação da fonte 1050 (22/10/2026)."""

    if res.receita_limite is None or res.dotacao is None or res.dotacao_integral is None:
        return ""
    reducao = res.dotacao_integral - res.dotacao
    return f" · fonte 1050 limitada pela arrecadação própria (−{formatar_brl(reducao)})" if reducao > 0.004 else ""


def _render_cartoes(res: ResultadoOrcamentario, qtd_selecionadas: int, qtd_celulas: int) -> None:
    """Cartões no desenho do protótipo (08/10/2026): o do Resultado com borda, fundo e selo pela situação."""

    if res.resultado is None:
        rodape = "Nenhuma célula selecionada" if not qtd_selecionadas else "Resultado incompleto — ver Avisos"
    else:
        rodape = f"{_pct(res.resultado, res.dotacao)} da dotação selecionada"
    st.html(
        html_cartoes(
            res.dotacao, f"{qtd_selecionadas} de {qtd_celulas} células selecionadas{_nota_limite_receita(res)}",
            res.executado_total, res.projetado_total, res.resultado, rodape,
        )
    )


def _tabela_empenhado(por_ne: pd.DataFrame, origem: str) -> pd.DataFrame:
    linhas = por_ne.loc[por_ne["celula_selecionada"] & (por_ne["origem"] == origem)]
    linhas = linhas.sort_values("empenhada", ascending=False, na_position="first")
    if origem == ORIGEM_CONTRATOS:
        colunas = {"ne_curta": "NE", "contrato_numero": "Contrato", "fornecedor": "Fornecedor"}
    elif origem == ORIGEM_BOLSAS:
        colunas = {"ne_curta": "NE", "programa_bolsa": "Programa"}
    else:
        colunas = {"ne_curta": "NE", "natureza_detalhada_desc": "Natureza", "ne_favorecido": "Favorecido"}
    tabela = linhas[[*colunas, "empenhada"]].rename(columns={**colunas, "empenhada": "Empenhado"})
    return tabela.reset_index(drop=True)


def _nomes_da_ne(linhas: pd.DataFrame | None, origem: str) -> pd.DataFrame:
    """`ne_curta` + colunas de identificação da NE (contrato/fornecedor; na projeção de Bolsas o programa vem em `fornecedor`)."""

    if linhas is None or linhas.empty:
        return pd.DataFrame(columns=["ne_curta", "Contrato", "Fornecedor", "Fator"] if origem == ORIGEM_CONTRATOS else ["ne_curta", "Programa", "Fator"])
    if origem == ORIGEM_CONTRATOS:
        nomes = linhas[["ne_curta", "contrato_numero", "fornecedor", "fator"]].rename(
            columns={"contrato_numero": "Contrato", "fornecedor": "Fornecedor", "fator": "Fator"}
        )
    else:
        nomes = linhas[["ne_curta", "fornecedor", "fator"]].rename(columns={"fornecedor": "Programa", "fator": "Fator"})
    return nomes.drop_duplicates("ne_curta")


def _tabela_executado(res: ResultadoOrcamentario, linhas: pd.DataFrame | None, origem: str) -> pd.DataFrame:
    """NEs de Contratos/Bolsas contadas na conta (empenho nas células marcadas) e o que cada uma já liquidou."""

    detalhe = res.consumo_por_ne.loc[res.consumo_por_ne["origem"] == origem, ["ne_curta", "executado"]]
    nomes = _nomes_da_ne(linhas, origem).drop(columns=["Fator"])
    tabela = detalhe.merge(nomes, on="ne_curta", how="left").sort_values("executado", ascending=False, na_position="first")
    colunas = ["NE", *[c for c in nomes.columns if c != "ne_curta"], "Executado"]
    return tabela.rename(columns={"ne_curta": "NE", "executado": "Executado"})[colunas].reset_index(drop=True)


def _tabela_projetado(
    res: ResultadoOrcamentario, linhas: pd.DataFrame | None, origem: str, ativos_sem_ne: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """NEs contadas na conta e o que falta da projeção de cada uma; contrato ATIVO sem NE (Contratos) entra pela necessidade
    contratual, com a NE em branco."""

    detalhe = res.consumo_por_ne.loc[res.consumo_por_ne["origem"] == origem, ["ne_curta", "projetado"]]
    nomes = _nomes_da_ne(linhas, origem)
    tabela = detalhe.merge(nomes, on="ne_curta", how="left").rename(columns={"ne_curta": "NE", "projetado": "Projetado"})
    colunas = ["NE", *[c for c in nomes.columns if c != "ne_curta"], "Projetado"]
    tabela = tabela[colunas]
    if origem == ORIGEM_CONTRATOS and ativos_sem_ne is not None and len(ativos_sem_ne) and "necessidade" in ativos_sem_ne:
        extras = pd.DataFrame({
            "NE": [None] * len(ativos_sem_ne),
            "Contrato": ativos_sem_ne.get("contrato_numero", pd.Series([None] * len(ativos_sem_ne))).to_numpy(),
            "Fornecedor": ativos_sem_ne.get("fornecedor", pd.Series([None] * len(ativos_sem_ne))).to_numpy(),
            "Fator": [None] * len(ativos_sem_ne),
            "Projetado": pd.to_numeric(ativos_sem_ne["necessidade"], errors="coerce").to_numpy(),
        })
        tabela = pd.concat([tabela, extras[colunas]], ignore_index=True)
    return tabela.sort_values("Projetado", ascending=False, na_position="first").reset_index(drop=True)


def _render_composicao(
    res: ResultadoOrcamentario,
    linhas_contratos: pd.DataFrame | None,
    linhas_bolsas: pd.DataFrame | None,
    despesas: list[DespesaManual],
    ativos_sem_ne: pd.DataFrame | None = None,
) -> None:
    """Composição no desenho do protótipo (08/10/2026): linhas compactas com % e valor à direita, barra
    de proporção e o detalhe por NE (ou por despesa) ao abrir a linha. Os avisos da projeção ficam na
    seção Avisos. Critério de 15/10/2026: Contratos e Bolsas pelo executado e pelo projetado a realizar."""

    linhas_por_origem = {ORIGEM_CONTRATOS: linhas_contratos, ORIGEM_BOLSAS: linhas_bolsas}
    col_executado, col_projetado = st.columns(2)
    with col_executado:
        # -0,00 (resíduo de ponto flutuante) aparece como 0,00
        diferenca = round(res.diferenca_conferencia, 2) + 0.0
        fecha = abs(res.diferenca_conferencia) < TOLERANCIA_CONFERENCIA
        rodape = (
            "✓ Empenhado das células confere com a Execução Mensal" if fecha
            else "✗ Empenhado das células não fecha com a Execução Mensal"
        ) + f" · diferença {formatar_brl(diferenca)}. Contratos e Bolsas: só NEs com empenho nas células marcadas."
        linhas_bloco = []
        for origem in ORIGENS_EMPENHADO:
            if origem in res.executado:
                linha = linhas_por_origem[origem]
                if res.executado[origem] is None:
                    linhas_bloco.append(LinhaComposicao(origem, None, None, ("Executado",), "Indisponível — ver Avisos."))
                else:
                    linhas_bloco.append(LinhaComposicao(
                        origem, res.executado[origem], _tabela_executado(res, linha, origem), ("Executado",),
                        "Nenhuma NE desta origem nas células selecionadas.",
                    ))
            else:
                linhas_bloco.append(LinhaComposicao(
                    origem, res.empenhado[origem], _tabela_empenhado(res.empenhado_por_ne, origem),
                    ("Empenhado",), "Nenhuma NE desta origem nas células selecionadas.",
                ))
        st.html(
            html_bloco(
                "Executado nas células selecionadas", linhas_bloco, res.executado_total, "Total executado",
                rodape, "ok" if fecha else "erro",
            )
        )

    with col_projetado:
        linhas_bloco = []
        for origem in (ORIGEM_CONTRATOS, ORIGEM_BOLSAS):
            linhas = linhas_por_origem[origem]
            if linhas is None:
                detalhe, vazio = None, "Indisponível — ver Avisos."
            else:
                detalhe = _tabela_projetado(res, linhas, origem, ativos_sem_ne)
                vazio = "Nenhuma NE com projeção nas células selecionadas."
            linhas_bloco.append(LinhaComposicao(origem, res.projetado[origem], detalhe, ("Projetado",), vazio))
        # a lista inteira fica à vista; só as marcadas "Considerada" entram no valor da linha (e do total)
        manual = pd.DataFrame({
            "Descrição": [d.descricao for d in despesas],
            "Situação": ["Considerada" if d.considerada else "Desconsiderada" for d in despesas],
            "Valor": [d.valor for d in despesas],
        })
        rotulo = OUTRAS_DESPESAS + (
            f" — {res.outras_desconsideradas_qtd} desconsiderada(s)" if res.outras_desconsideradas_qtd else ""
        )
        linhas_bloco.append(
            LinhaComposicao(
                rotulo, res.projetado[OUTRAS_DESPESAS], manual, ("Valor",),
                "Nenhuma despesa cadastrada — ver a seção Outras despesas previstas.",
            )
        )
        st.html(
            html_bloco(
                "Projetado a realizar até dezembro", linhas_bloco, res.projetado_total, "Total projetado",
                "O que falta da projeção pela execução (com os seus ajustes) nas NEs com empenho nas células marcadas. "
                "Projeção sem contrato antecessor: NE com menos de 3 meses fechados é projetada pelo valor mensal cheio. "
                "A necessidade de empenho continua nas páginas de Contratos e Bolsas.",
            )
        )


def _tabela_celulas(celulas: pd.DataFrame, empenhado: pd.DataFrame, selecao: set) -> pd.DataFrame:
    """Uma linha por célula, na ordem de `celulas`. Célula sem nenhum registro de empenho no
    exercício mostra Empenhado R$ 0,00 (nada empenhado, mesma convenção de `calcular_resultado`);
    célula com registro de valor nulo continua nula."""

    soma = empenhado.groupby("chave")["empenhada"].sum(min_count=1) if len(empenhado) else pd.Series(dtype="float64")
    tem_registro = celulas["chave"].isin(set(soma.index))
    emp = celulas["chave"].map(soma).astype("Float64")
    emp = emp.where(tem_registro, 0.0)
    tabela = pd.DataFrame({"Selecionar": celulas["chave"].isin(selecao).to_numpy()})
    for rotulo, coluna in _COLUNAS_CELULA.items():
        tabela[rotulo] = celulas[coluna].to_numpy()
    tabela["Dotação Atualizada"] = celulas["dotacao_atualizada"].to_numpy()
    tabela["Empenhado"] = emp.to_numpy()
    tabela["Saldo"] = (celulas["dotacao_atualizada"].astype("Float64") - emp).to_numpy()
    return tabela


# ---------------------------------------------------------------------- página
# Memória (mesma correção de `app_pages/limite_empenho.py`, 07/10/2026): coleta no início (lixo da
# interação anterior, inclusive dos `st.stop()`) e no fim. Nenhum dado é alterado.
gc.collect()

render_page_header(
    "Resultado Orçamentário",
    "A dotação das células selecionadas cobre o que ainda falta empenhar até dezembro?",
    "Planejamento",
)

manifesto_dotacao = ManifestoDotacao.atual()
manifesto_execucao = ManifestoExecucaoMensal.atual()
if manifesto_dotacao is None or manifesto_execucao is None:
    st.info(
        "Esta página precisa da Dotação Anual e da Execução Mensal já importadas (menu "
        '"Atualizar Planilhas"). Falta: '
        + ", ".join(
            nome for nome, ok in (
                ("Dotação Anual", manifesto_dotacao is not None),
                ("Execução Mensal", manifesto_execucao is not None),
            )
            if not ok
        )
        + "."
    )
    st.stop()

ponteiro_dotacao = DIR_MANIFESTOS_DOTACAO / PONTEIRO_DOTACAO
ponteiro_execucao = DIR_MANIFESTOS_EXECUCAO_MENSAL / PONTEIRO_EXECUCAO_MENSAL
try:
    celulas_por_exercicio = _cached_celulas_por_exercicio(str(ponteiro_dotacao), ponteiro_dotacao.stat().st_mtime)
except Exception as erro:
    st.error(f"Não foi possível ler a Dotação Anual: {erro}")
    st.stop()
anos = sorted(celulas_por_exercicio)
if not anos:
    st.info("A Dotação Anual importada não tem nenhum exercício.")
    st.stop()

data_dotacao = datetime.fromisoformat(manifesto_dotacao.data_extracao)
data_execucao = datetime.fromisoformat(manifesto_execucao.data_extracao)
ano_padrao = data_dotacao.year if data_dotacao.year in anos else max(anos)

col_exercicio, col_datas = st.columns([1, 5], vertical_alignment="bottom")
with col_exercicio:
    exercicio = int(
        st.selectbox(
            "Exercício", anos, index=anos.index(ano_padrao), key="ro_exercicio",
            format_func=lambda ano: f"{ano} (em andamento)" if ano == ano_padrao else str(ano),
        )
    )
with col_datas:
    st.caption(
        f"Dotação Anual · extração de {data_dotacao:%d/%m/%Y}  |  "
        f"Execução Mensal · extração de {data_execucao:%d/%m/%Y}  |  "
        "Executado e projetado: projeção pela execução"
    )

try:
    empenhado, por_ne_execucao, sugestao_inicio = _cached_execucao(
        str(ponteiro_execucao), ponteiro_execucao.stat().st_mtime, exercicio
    )
except Exception as erro:
    st.error(f"Não foi possível ler a Execução Mensal: {erro}")
    st.stop()

celulas = celulas_por_exercicio[exercicio]
chaves_celulas: list[CelulaChave] = list(celulas["chave"])

avisos_extras: list[str] = []
indice_competencia: pd.Series | None = None
competencia: pd.DataFrame | None = None
lancamento: pd.DataFrame | None = None
if CAMINHO_LIQUIDACAO_COMPETENCIA.exists():
    try:
        indice_competencia, competencia = _cached_liquidacao_competencia(
            str(CAMINHO_LIQUIDACAO_COMPETENCIA), CAMINHO_LIQUIDACAO_COMPETENCIA.stat().st_mtime
        )
        lancamento = _cached_lancamento(str(ponteiro_execucao), ponteiro_execucao.stat().st_mtime)
    except Exception as erro:
        avisos_extras.append(f"Não foi possível ler a Liquidação por Competência ({erro}).")
else:
    avisos_extras.append(f"Liquidação por Competência não encontrada ('{CAMINHO_LIQUIDACAO_COMPETENCIA}').")

mes_referencia = mes_referencia_do_exercicio(data_execucao.date(), exercicio)
fontes: dict[str, tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame, list[str], RelatorioProjecaoExecucao | None]] = {}
for origem in (ORIGEM_CONTRATOS, ORIGEM_BOLSAS):
    try:
        tabela, linhas, sem_ne, motivo, avisos_projecao, relatorio_projecao = _necessidade(
            origem, exercicio, por_ne_execucao, sugestao_inicio, indice_competencia, competencia, mes_referencia, lancamento,
        )
    except Exception as erro:
        tabela, linhas, sem_ne, motivo, avisos_projecao, relatorio_projecao = (
            pd.DataFrame(columns=["ne_curta"]), None, pd.DataFrame(), f"erro de leitura ({erro})", [], None,
        )
    if motivo:
        avisos_extras.append(f"Necessidade de {origem} indisponível: {motivo}.")
    fontes[origem] = (tabela, linhas, sem_ne, avisos_projecao, relatorio_projecao)

try:
    selecao_salva = cadastro.carregar_selecao(exercicio, diretorio=cadastro.DIRETORIO_PADRAO)
    selecao_legivel = True
except ArquivoCorrompido as erro:
    selecao_salva, selecao_legivel = [], False
    st.error(f"{erro}. A seleção gravada não pôde ser lida; corrija ou restaure o arquivo — a página não grava por cima.")

try:
    despesas = cadastro.carregar_despesas(exercicio, diretorio=cadastro.DIRETORIO_PADRAO)
    despesas_legiveis = True
except ArquivoCorrompido as erro:
    despesas, despesas_legiveis = [], False
    st.error(f"{erro}. As despesas manuais não puderam ser lidas; corrija ou restaure o arquivo — a página não grava por cima.")

try:
    receitas = cadastro.carregar_receitas(exercicio, diretorio=cadastro.DIRETORIO_PADRAO)
    receitas_legiveis = True
except ArquivoCorrompido as erro:
    receitas, receitas_legiveis = [], False
    st.error(f"{erro}. As receitas próprias não puderam ser lidas; corrija ou restaure o arquivo — a página não grava por cima.")

# Cartões e Composição ficam no topo, mas dependem da seleção em edição (tabela mais abaixo):
# containers reservados aqui e preenchidos no fim.
area_cartoes = st.container()
st.subheader("2. Composição")
st.caption("Clique em uma linha para ver o detalhe por NE ou por despesa.")
area_composicao = st.container()
st.subheader("3. Detalhamento por GND e Ação")
st.caption(
    "Dotação, executado, projetado a realizar e resultado das células marcadas, por Grupo de Despesa (GND) e Ação. "
    "Clique em um grupo para abrir."
)
area_detalhe = st.container()
st.subheader("Discricionário (RP2) por Plano Orçamentário")
st.caption(
    "Um quadro por Plano Orçamentário das Ações com Resultado Primário 2, agrupados por Ação. Considera todas as células do "
    "discricionário, marcadas ou não, com a mesma conta do resultado (executado, projetado a realizar e a fonte 1050 da 20RK "
    "limitada pela arrecadação própria)."
)
area_planos = st.container()

# --------------------------------------------------------------- Células
# Layout do protótipo aprovado em 08/10/2026 (`docs/superpowers/specs/2026-10-08-resultado-orcamentario-celulas-mockup.html`):
# células agrupadas por Ação, uma caixa de marcar por célula, "Marcar todas" por Ação, busca, filtro de
# selecionadas e rodapé fixo com os totais e "Salvar seleção". Substitui a tabela editável, que
# parecia uma planilha e mostrava os valores fora do formato brasileiro.
st.subheader("4. Células que fazem frente às despesas")
st.caption(
    'Marque as células da Dotação Anual que entram como recurso (abra "Ver células" em cada ação). As ações com '
    'célula marcada ficam destacadas. A seleção fica gravada por exercício ("Salvar seleção").'
)
_conjunto_celulas = set(chaves_celulas)
# Célula gravada que não existe mais na base é mantida na seleção (spec §6): aparece em Avisos.
ausentes_da_base = [chave for chave in selecao_salva if chave not in _conjunto_celulas]
# A seleção em edição vive em `session_state` (um conjunto de chaves), e não no estado de cada caixa:
# caixa escondida pelo filtro sai do estado do Streamlit, e a marcação não pode se perder com ela.
_CHAVE_SELECAO = f"ro_sel_{exercicio}"
if _CHAVE_SELECAO not in st.session_state:
    st.session_state[_CHAVE_SELECAO] = {chave for chave in selecao_salva if chave in _conjunto_celulas}
selecionadas: set = st.session_state[_CHAVE_SELECAO]
valores_celulas = _tabela_celulas(celulas, empenhado, set())


def _numero_ou_none(valor: object) -> float | None:
    return None if valor is None or pd.isna(valor) else float(valor)


def _chave_caixa(indice: int) -> str:
    return f"ro_cel_{exercicio}_{indice}"


def _ao_marcar(indice: int) -> None:
    chave = chaves_celulas[indice]
    if st.session_state[_chave_caixa(indice)]:
        selecionadas.add(chave)
    else:
        selecionadas.discard(chave)


def _marcar_acao(indices: list[int], marcar: bool) -> None:
    for indice in indices:
        if marcar:
            selecionadas.add(chaves_celulas[indice])
        else:
            selecionadas.discard(chaves_celulas[indice])
        st.session_state[_chave_caixa(indice)] = marcar


col_busca, col_so = st.columns([4, 2], vertical_alignment="center")
with col_busca:
    busca = st.text_input(
        "Buscar", key="ro_busca_celulas", placeholder="Buscar por ação, PTRES, PO ou descrição…",
        label_visibility="collapsed",
    ).strip().casefold()
with col_so:
    # A última escolha sobrevive à atualização da página (08/10/2026): lida do arquivo na 1ª execução
    # da sessão e gravada a cada mudança.
    if "ro_so_selecionadas" not in st.session_state:
        st.session_state["ro_so_selecionadas"] = cadastro.carregar_so_selecionadas(cadastro.DIRETORIO_PADRAO)
    so_selecionadas = st.checkbox(
        "Mostrar só as selecionadas", key="ro_so_selecionadas",
        on_change=lambda: cadastro.salvar_so_selecionadas(
            st.session_state["ro_so_selecionadas"], cadastro.DIRETORIO_PADRAO
        ),
    )

acoes = celulas["acao_codigo"].tolist()
descricoes = celulas["acao_descricao"].tolist()
ptres_celulas = celulas["ptres_codigo"].tolist()
po_celulas = celulas["plano_orcamentario_codigo"].tolist()
grupos: dict[str, list[int]] = {}
for indice, chave in enumerate(chaves_celulas):
    texto = " ".join(
        str(v) for v in (acoes[indice], ptres_celulas[indice], po_celulas[indice], descricoes[indice]) if v is not None
    ).casefold()
    if busca and busca not in texto:
        continue
    if so_selecionadas and chave not in selecionadas:
        continue
    grupos.setdefault(str(acoes[indice]), []).append(indice)

st.html(ESTILO_CELULAS)
if not grupos:
    st.caption("Nenhuma célula corresponde ao filtro.")
destaques: list[str] = []
for acao in sorted(grupos):
    indices = grupos[acao]
    qtd_selecionadas = sum(chaves_celulas[i] in selecionadas for i in indices)
    chave_cartao = f"ro_acao_{exercicio}_{acao}"
    if qtd_selecionadas:
        destaques.append(
            f".st-key-{chave_cartao}{{border-color:{dt.ACCENT} !important;box-shadow:0 0 0 1px {dt.ACCENT_SOFT}}}"
        )
    with st.container(border=True, key=chave_cartao):
        col_tit, col_dot, col_todas = st.columns([6, 2, 1.4], vertical_alignment="center")
        with col_tit:
            st.html(html_cabecalho_acao(acao, descricoes[indices[0]] or "", len(indices), qtd_selecionadas))
        with col_dot:
            st.html(html_dotacao_acao(soma_ou_nulo(valores_celulas["Dotação Atualizada"].iloc[indices])))
        todas = qtd_selecionadas == len(indices)
        with col_todas:
            st.button(
                "Desmarcar todas" if todas else "Marcar todas", key=f"ro_todas_{exercicio}_{acao}",
                on_click=_marcar_acao, args=(indices, not todas), disabled=not selecao_legivel, width="stretch",
            )
        rotulo = "Ver células" if len(indices) != 1 else "Ver célula"
        # Células recolhidas por padrão (pedido de 08/10/2026); só abrem sozinhas durante uma busca.
        with st.expander(rotulo, expanded=bool(busca)):
            for indice in indices:
                if _chave_caixa(indice) not in st.session_state:
                    st.session_state[_chave_caixa(indice)] = chaves_celulas[indice] in selecionadas
                col_caixa, col_info = st.columns([0.35, 9.65], vertical_alignment="center")
                with col_caixa:
                    st.checkbox(
                        "Selecionar", key=_chave_caixa(indice), on_change=_ao_marcar, args=(indice,),
                        label_visibility="collapsed", disabled=not selecao_legivel,
                    )
                with col_info:
                    linha = valores_celulas.iloc[indice]
                    st.html(
                        html_celula(
                            chaves_celulas[indice], _numero_ou_none(linha["Dotação Atualizada"]),
                            _numero_ou_none(linha["Empenhado"]), _numero_ou_none(linha["Saldo"]),
                        )
                    )
if destaques:
    st.html("<style>" + "".join(destaques) + "</style>")

marcadas = [chave for chave in chaves_celulas if chave in selecionadas]
selecao_atual: list[CelulaChave] = [*ausentes_da_base, *marcadas]
indices_marcados = [i for i, chave in enumerate(chaves_celulas) if chave in selecionadas]
totais = valores_celulas.iloc[indices_marcados]

# rodapé fixo: totais da seleção e "Salvar seleção" sempre visíveis ao rolar a lista
st.html(
    "<style>.st-key-ro_rodape_celulas{position:sticky;bottom:0;z-index:5;"
    f"background:{dt.SURFACE};box-shadow:0 -4px 16px rgba(7,19,61,.06)}}</style>"
)
with st.container(border=True, key="ro_rodape_celulas"):
    col_totais, col_estado, col_salvar = st.columns([5, 2.6, 1.4], vertical_alignment="center")
    with col_totais:
        st.html(
            html_rodape_totais(
                soma_ou_nulo(totais["Dotação Atualizada"]), soma_ou_nulo(totais["Empenhado"]),
                soma_ou_nulo(totais["Saldo"]),
            )
        )
    with col_salvar:
        salvar = st.button(
            "Salvar seleção", key="ro_salvar_selecao", type="primary", disabled=not selecao_legivel, width="stretch",
        )
    if salvar:
        cadastro.salvar_selecao(exercicio, selecao_atual, diretorio=cadastro.DIRETORIO_PADRAO)
        selecao_salva = list(selecao_atual)
    with col_estado:
        st.caption(f"**{len(marcadas)}** de {len(chaves_celulas)} células selecionadas")
        if salvar:
            st.caption("✓ Seleção gravada.")
        elif set(selecao_atual) != set(selecao_salva):
            st.caption("Alterações não salvas — o resultado acima já considera a seleção em edição.")
        else:
            arquivo_selecao = Path(cadastro.DIRETORIO_PADRAO) / str(exercicio) / "celulas.json"
            if arquivo_selecao.exists():
                st.caption(f"Última gravação: {datetime.fromtimestamp(arquivo_selecao.stat().st_mtime):%d/%m/%Y %H:%M}")
            else:
                st.caption("Nenhuma seleção gravada para este exercício.")

# --------------------------------------------------------------- Outras despesas previstas
st.subheader(f"5. {OUTRAS_DESPESAS}")
st.caption(
    "Despesas que não estão em Contratos nem em Bolsas e ainda vão ser empenhadas no exercício. "
    "A célula é só informativa: não muda a conta."
)
st.caption(
    'Marque "Considerar" em cada despesa que deve pesar no resultado. A desmarcada continua listada e editável, mas sai '
    "da conta (projetado, resultado, cartões e composição). A escolha de cada uma fica gravada, e o histórico diário "
    "registra quantas e quanto ficaram de fora."
)
if _CHAVE_FLASH in st.session_state:
    st.success(st.session_state.pop(_CHAVE_FLASH))

if despesas:
    # Editar/Excluir em cada linha, como no protótipo (08/10/2026); antes era um seletor separado.
    larguras = [1.1, 3, 2.2, 2.4, 1.4, 0.8, 0.8]
    for coluna, titulo in zip(
        st.columns(larguras), ("Considerar", "Descrição", "Observação", "Célula (informativa)", "Valor a empenhar")
    ):
        coluna.caption(f"**{titulo}**")
    for despesa in despesas:
        col_considerar, col_desc, col_obs, col_cel, col_valor, col_editar, col_excluir = st.columns(
            larguras, vertical_alignment="center"
        )
        col_considerar.checkbox(
            "Considerar", value=despesa.considerada, key=f"ro_considerar_{despesa.id}", label_visibility="collapsed",
            disabled=not despesas_legiveis, on_change=_alternar_consideracao, args=(exercicio, despesa.id),
            help="Desmarcada, a despesa fica listada mas não entra na conta do resultado.",
        )
        col_desc.markdown(_sem_latex(despesa.descricao))
        col_obs.markdown(_sem_latex(despesa.observacao or "—"))
        col_cel.caption(_rotulo_celula(despesa.celula))
        col_valor.markdown(_sem_latex(formatar_brl(despesa.valor)))
        with col_editar:
            if st.button("Editar", key=f"ro_editar_{despesa.id}", disabled=not despesas_legiveis, type="tertiary"):
                _dialogo_editar(exercicio, despesa, chaves_celulas)
        with col_excluir:
            if st.button("Excluir", key=f"ro_excluir_{despesa.id}", disabled=not despesas_legiveis, type="tertiary"):
                _dialogo_excluir(exercicio, despesa)
    st.caption(_sem_latex(
        f"Total cadastrado: {formatar_brl(sum(d.valor for d in despesas))} · "
        f"considerado no resultado: {formatar_brl(sum(d.valor for d in despesas if d.considerada))}"
    ))
elif despesas_legiveis:
    st.caption("Nenhuma despesa prevista cadastrada para este exercício.")

with st.form("ro_nova_despesa", clear_on_submit=True):
    col_desc, col_valor, col_obs, col_celula = st.columns([2, 1, 2, 1.4])
    with col_desc:
        nova_descricao = st.text_input("Descrição", key="ro_despesa_descricao", placeholder="Ex.: Aquisição de reagentes")
    with col_valor:
        novo_valor = st.number_input(
            "Valor a empenhar (R$)", key="ro_despesa_valor", value=None, min_value=0.0, step=100.0, format="%.2f",
        )
    with col_obs:
        nova_observacao = st.text_input("Observação", key="ro_despesa_observacao", placeholder="Opcional")
    with col_celula:
        nova_celula = st.selectbox(
            "Célula (opcional)", _opcoes_celula(chaves_celulas), key="ro_despesa_celula", format_func=_rotulo_celula,
        )
    incluir = st.form_submit_button("Incluir", type="primary", disabled=not despesas_legiveis)
if incluir:
    erros = cadastro.validar_despesa(nova_descricao, novo_valor)
    for erro in erros:
        st.error(erro)
    if not erros:
        try:
            cadastro.incluir_despesa(
                exercicio, nova_descricao, novo_valor, (nova_observacao or "").strip() or None, nova_celula,
                diretorio=cadastro.DIRETORIO_PADRAO,
            )
        except ArquivoCorrompido as erro:
            st.error(f"{erro} — nada foi gravado.")
        else:
            _mensagem(f'Despesa "{nova_descricao.strip()}" incluída.')
            st.rerun()


# --------------------------------------------------------------- Receitas próprias
st.subheader("Receitas próprias arrecadadas")
st.caption(
    "Arrecadação de receita própria informada à mão. A dotação da fonte 1050 é uma estimativa da arrecadação: a célula "
    "da ação 20RK, GND 3, fonte 1050000000 conta só até o valor informado aqui (o menor entre a dotação e a arrecadação). "
    "O valor não soma dotação por fora e só tem efeito com essa célula marcada na seção 4. "
    '"Considerar" desmarcado tira o lançamento da conta; sem nenhum considerado, a dotação conta inteira, com aviso.'
)

if receitas:
    for receita in receitas:
        col_ok, col_desc, col_obs, col_valor, col_acoes = st.columns([1, 4, 3, 2, 1], vertical_alignment="center")
        col_ok.checkbox(
            "Considerar", value=receita.considerada, key=f"ro_considerar_rec_{receita.id}", label_visibility="collapsed",
            disabled=not receitas_legiveis, on_change=_alternar_consideracao_receita, args=(exercicio, receita.id),
        )
        col_desc.markdown(_sem_latex(receita.descricao))
        col_obs.markdown(_sem_latex(receita.observacao or "—"))
        col_valor.markdown(_sem_latex(formatar_brl(receita.valor)))
        if col_acoes.button("Excluir", key=f"ro_excluir_rec_{receita.id}", disabled=not receitas_legiveis, type="tertiary"):
            _dialogo_excluir_receita(exercicio, receita)
    st.caption(
        f"Total cadastrado: {formatar_brl(sum(r.valor for r in receitas))} · "
        f"considerado no resultado: {formatar_brl(sum(r.valor for r in receitas if r.considerada))}"
    )
elif receitas_legiveis:
    st.caption("Nenhuma receita própria cadastrada para este exercício.")

with st.form("ro_nova_receita", clear_on_submit=True):
    _c_desc, _c_valor, _c_obs = st.columns([4, 2, 3])
    nova_rec_descricao = _c_desc.text_input("Descrição", key="ro_receita_descricao", placeholder="Ex.: Arrecadação fonte 050 — set/2026")
    nova_rec_valor = _c_valor.number_input(
        "Valor arrecadado (R$)", key="ro_receita_valor", value=None, min_value=0.0, step=100.0, format="%.2f",
    )
    nova_rec_observacao = _c_obs.text_input("Observação", key="ro_receita_observacao", placeholder="Opcional")
    incluir_receita = st.form_submit_button("Incluir receita", type="primary", disabled=not receitas_legiveis)
if incluir_receita:
    erros_rec = cadastro.validar_receita(nova_rec_descricao, nova_rec_valor)
    if erros_rec:
        for erro in erros_rec:
            st.error(erro)
    else:
        try:
            cadastro.incluir_receita(
                exercicio, nova_rec_descricao, nova_rec_valor, nova_rec_observacao.strip() or None,
                diretorio=cadastro.DIRETORIO_PADRAO,
            )
        except ArquivoCorrompido as erro:
            st.error(f"{erro} — nada foi gravado.")
        else:
            _mensagem(f'Receita "{nova_rec_descricao.strip()}" incluída.')
            st.rerun()

# --------------------------------------------------------------- conta e topo
tabela_contratos_df, linhas_contratos, sem_ne_contratos, avisos_projecao_contratos, relatorio_contratos = fontes[ORIGEM_CONTRATOS]
tabela_bolsas_df, linhas_bolsas, sem_ne_bolsas, avisos_projecao_bolsas, relatorio_bolsas = fontes[ORIGEM_BOLSAS]
# Sobra prevista de empenho (15/10/2026): informativa (seção 7); não entra na conta do resultado.
_relatorios_sobra = {
    nome: relatorio for nome, relatorio in (
        (ORIGEM_CONTRATOS, relatorio_contratos), (ORIGEM_BOLSAS, relatorio_bolsas),
    ) if relatorio is not None
}
_tabela_sobra = sobra_por_ne(_relatorios_sobra, data_execucao.date()) if _relatorios_sobra else None
# Interruptor da seção 4 (15/10/2026): desligado, as despesas continuam cadastradas e listadas, mas não entram na conta.
resultado = calcular_resultado(
    celulas, empenhado, selecao_atual, tabela_contratos_df, tabela_bolsas_df,
    linhas_contratos, linhas_bolsas, sem_ne_contratos, sem_ne_bolsas, despesas, receitas,
)
if not receitas_legiveis:
    resultado = replace(
        resultado, resultado=None, incompleto=bool(selecao_atual),
        avisos=[*resultado.avisos, "Receitas próprias ilegíveis: resultado incompleto."],
    )
if not despesas_legiveis:
    resultado = replace(
        resultado,
        projetado={**resultado.projetado, OUTRAS_DESPESAS: None},
        resultado=None,
        incompleto=bool(selecao_atual),
        avisos=[*resultado.avisos, "Outras despesas previstas ilegíveis: resultado incompleto."],
    )

# Histórico (13/10/2026): fotografia do dia, só do que está SALVO — a seleção em edição (não salva) não vira
# história —, com os arquivos de seleção e de despesas legíveis e ao menos uma célula marcada.
historico_fotografias: list[historico_ro.Fotografia] = []
historico_erro: str | None = None
try:
    historico_fotografias = historico_ro.carregar_historico(exercicio, diretorio=cadastro.DIRETORIO_PADRAO)
    if selecao_legivel and despesas_legiveis and selecao_atual and set(selecao_atual) == set(selecao_salva):
        if historico_ro.registrar(
            historico_ro.fotografar(
                resultado, exercicio, len(marcadas),
                dotacao_extracao=f"{data_dotacao:%d/%m/%Y}", dotacao_sha=manifesto_dotacao.sha256[:8],
                execucao_extracao=f"{data_execucao:%d/%m/%Y}", execucao_sha=manifesto_execucao.sha256[:8],
                dotacao_por_celula={
                    historico_ro.chave_celula(chave): (None if pd.isna(valor) else float(valor))
                    for chave, valor in zip(celulas["chave"], celulas["dotacao_atualizada"])
                    if chave in set(marcadas)
                },
            ),
            diretorio=cadastro.DIRETORIO_PADRAO,
        ):
            historico_fotografias = historico_ro.carregar_historico(exercicio, diretorio=cadastro.DIRETORIO_PADRAO)
except ArquivoCorrompido as erro:
    historico_erro = f"{erro}. O histórico não pôde ser lido; corrija ou restaure o arquivo — a página não grava por cima."

with area_cartoes:
    if resultado.outras_desconsideradas_qtd:
        st.warning(
            _sem_latex(
                f"Resultado SEM {resultado.outras_desconsideradas_qtd} de {len(despesas)} outras despesas previstas "
                f"({formatar_brl(resultado.outras_desconsideradas_valor)}): estão desconsideradas. Marque 'Considerar' em "
                "'Outras despesas previstas' (seção 5) para voltar a contá-las."
            )
        )
    if resultado.receitas_desconsideradas_qtd:
        st.warning(
            _sem_latex(
                f"Resultado SEM {resultado.receitas_desconsideradas_qtd} de {len(receitas)} receitas próprias "
                f"({formatar_brl(resultado.receitas_desconsideradas_valor)}): estão desconsideradas."
            )
        )
    _render_cartoes(resultado, len(marcadas), len(celulas))
with area_composicao:
    # contrato ATIVO sem NE entra no projetado (08/10/2026): aparece também no detalhe de Contratos,
    # para a tabela fechar com o total da linha
    ativos_sem_ne, _ = separar_ativos_sem_ne(sem_ne_contratos)
    _render_composicao(
        resultado, linhas_contratos, linhas_bolsas, despesas, ativos_sem_ne,
    )
with area_detalhe:
    # o controle segmentado do Streamlit não destaca a opção ativa no tema do projeto: marca-a com a cor de destaque
    st.html(
        f"<style>.st-key-ro_detalhe_agrupar button[aria-checked='true']{{background:{dt.ACCENT} !important;"
        f"color:#fff !important;border-color:{dt.ACCENT} !important}}"
        f".st-key-ro_detalhe_agrupar button[aria-checked='true'] *{{color:#fff !important}}</style>"
    )
    _col_modo, _col_abrir, _col_info = st.columns([2, 2, 3], vertical_alignment="center")
    with _col_modo:
        _agrupar = st.segmented_control(
            "Agrupar por", [AGRUPAR_GND, AGRUPAR_ACAO], default=AGRUPAR_GND, selection_mode="single",
            format_func=lambda v: "GND › Ação" if v == AGRUPAR_GND else "Ação › GND",
            key="ro_detalhe_agrupar", label_visibility="collapsed",
        ) or AGRUPAR_GND
    with _col_abrir:
        _c1, _c2 = st.columns(2)
        if _c1.button("Expandir tudo", key="ro_detalhe_expandir", type="tertiary"):
            st.session_state["ro_detalhe_abrir"] = True
        if _c2.button("Recolher tudo", key="ro_detalhe_recolher", type="tertiary"):
            st.session_state["ro_detalhe_abrir"] = False
    with _col_info:
        st.caption('Só as células marcadas na seção "Células" entram.')
    detalhe_gnd_acao = detalhar_por_gnd_acao(resultado, celulas, empenhado, selecao_atual, despesas, ativos_sem_ne)
    _total_detalhe = (
        detalhe_gnd_acao.dotacao, detalhe_gnd_acao.executado, detalhe_gnd_acao.projetado, detalhe_gnd_acao.resultado,
    )
    st.html(
        html_detalhe_gnd_acao(
            detalhe_gnd_acao.linhas, _total_detalhe, _agrupar,
            ("✓ A soma das linhas confere com os cartões" if detalhe_gnd_acao.fecha
             else "✗ A soma das linhas não fecha com os cartões")
            + f" · diferença {formatar_brl(round(detalhe_gnd_acao.diferenca_conferencia, 2) + 0.0)}",
            "ok" if detalhe_gnd_acao.fecha else "erro", st.session_state.get("ro_detalhe_abrir"),
        )
    )
    _avisos_com_ok(detalhe_gnd_acao.avisos, "detalhe", exercicio)

# Relatório (22/10/2026): HTML de uma folha A4 com os mesmos números da tela (cartões, composição, detalhamento, receitas e
# outras despesas), para imprimir ou salvar em PDF. Fica junto dos cartões.
_emitido_em = datetime.now()
with area_cartoes:
    st.download_button(
        "Baixar relatório (HTML para imprimir ou salvar em PDF)",
        data=html_relatorio(
            resultado, detalhe_gnd_acao, despesas, receitas, exercicio, len(marcadas), len(celulas), _emitido_em,
            nota_dotacao=_nota_limite_receita(resultado),
        ).encode("utf-8"),
        file_name=f"resultado_orcamentario_{exercicio}_{_emitido_em:%Y-%m-%d}.html",
        mime="text/html",
        key="ro_baixar_relatorio",
    )

# Quadros do discricionário por Plano Orçamentário (29/10/2026): seleção própria (todo o RP2), independente das células marcadas.
with area_planos:
    if not (despesas_legiveis and receitas_legiveis):
        st.warning("Quadros indisponíveis: o cadastro de despesas previstas ou de receitas próprias não pôde ser lido.")
    else:
        _resultado_rp2 = calcular_resultado(
            celulas, empenhado, selecao_discricionaria(celulas), tabela_contratos_df, tabela_bolsas_df,
            linhas_contratos, linhas_bolsas, sem_ne_contratos, sem_ne_bolsas, despesas, receitas,
        )
        _planos = planos_discricionarios(_resultado_rp2, celulas, empenhado, despesas, ativos_sem_ne)
        st.html(html_planos_discricionarios(_planos))
        _avisos_com_ok(_planos.avisos, "planos", exercicio)

# --------------------------------------------------------------- Avisos
st.subheader("6. Avisos")
# Avisos da projeção (fator baixo, meses em aberto…) ficam aqui, como no protótipo (08/10/2026).
avisos_projecao = [
    f"Projeção de {origem}: {aviso}"
    for origem, lista in ((ORIGEM_CONTRATOS, avisos_projecao_contratos), (ORIGEM_BOLSAS, avisos_projecao_bolsas))
    for aviso in lista
]
_avisos_com_ok([*resultado.avisos, *avisos_extras, *avisos_projecao], "geral", exercicio)
for origem, sem_ne in ((ORIGEM_CONTRATOS, sem_ne_contratos), (ORIGEM_BOLSAS, sem_ne_bolsas)):
    if sem_ne is not None and len(sem_ne):
        colunas = [
            c for c in (
                "contrato_numero", "fornecedor", "status_contrato", "programa_bolsa", "processo", "valor_mensal",
                "necessidade",
            )
            if c in sem_ne.columns
        ]
        with st.expander(f"Ver {origem} sem NE ({len(sem_ne)})"):
            st.dataframe(
                sem_ne[colunas], hide_index=True, width="stretch",
                column_config={
                    c: currency_column(c) for c in ("valor_mensal", "necessidade") if c in colunas
                },
            )
# --------------------------------------------------------------- Histórico
st.subheader("7. Histórico do resultado")
st.caption(
    "Uma fotografia por dia (a última do dia vale), gravada ao abrir a página com a seleção salva. Só existe a partir "
    "do primeiro registro: o passado anterior não é reconstruível. A variação mostra quanto cada componente da "
    "fórmula (Dotação − Executado − Projetado a realizar) moveu o resultado desde a fotografia anterior. Fotografias "
    "anteriores a 15/10/2026 usavam Empenhado − Necessidade + Anulação sugerida (coluna Critério)."
)
if historico_erro:
    st.error(historico_erro)
elif not historico_fotografias:
    st.info("Ainda não há fotografias neste exercício: elas passam a ser gravadas com a seleção de células salva.")
else:
    tabela_dias = historico_ro.tabela_historico(historico_fotografias)
    st.dataframe(
        _estilo_historico(tabela_dias, ("Resultado", "Variação"), ("Variação",)),
        hide_index=True, width="stretch",
        column_config={
            "Dia": st.column_config.TextColumn("Dia", width="small"),
            "Mudança de situação": st.column_config.TextColumn("Mudança de situação", width="medium"),
            "Células marcadas": st.column_config.TextColumn("Células marcadas", width="small"),
            "Outras despesas": st.column_config.TextColumn("Outras despesas", width="small"),
        },
    )
    mudancas_ro = historico_ro.mudancas(historico_fotografias)
    if not mudancas_ro:
        st.caption("Há só uma fotografia; a variação aparece a partir da segunda.")
    else:
        rotulos_dias = [f"{m.anterior.data} → {m.atual.data}" for m in mudancas_ro]
        escolha = st.selectbox("O que levou à alteração", rotulos_dias, key="ro_historico_periodo")
        mudanca = mudancas_ro[rotulos_dias.index(escolha)]
        if mudanca.variacao_resultado is None:
            st.caption("Resultado indisponível em uma das pontas: a variação do resultado não é calculável.")
        else:
            st.caption(f"Variação do resultado: {_sem_latex(formatar_brl(mudanca.variacao_resultado))}.")
        if mudanca.mudanca_de_criterio:
            st.warning(
                f"Critério da fórmula mudou entre estas fotografias ({mudanca.mudanca_de_criterio}): a variação de "
                "Contratos e Bolsas mistura a mudança de critério com a mudança real."
            )
        if mudanca.escolha_outras_despesas:
            st.warning(
                f"A escolha das outras despesas previstas mudou entre estas fotografias ({mudanca.escolha_outras_despesas}): "
                "a variação de 'Outras despesas previstas' abaixo vem dessa escolha, não de mudança nas despesas."
            )
        tabela_mud = historico_ro.tabela_mudanca(mudanca)
        if tabela_mud.empty:
            st.caption("Nenhum componente variou entre estas duas fotografias.")
        else:
            st.dataframe(
                _estilo_historico(
                    tabela_mud, ("Antes", "Depois", "Variação", "Efeito no resultado"),
                    ("Variação", "Efeito no resultado"),
                ),
                hide_index=True, width="stretch",
                column_config={"Grupo": st.column_config.TextColumn("Grupo", width="small")},
            )
        tabela_cel = historico_ro.tabela_celulas(mudanca)
        if tabela_cel is None:
            st.caption(
                "Detalhe da dotação por célula indisponível: alguma das duas fotografias é anterior a esse registro."
            )
        elif tabela_cel.empty:
            st.caption("A dotação de nenhuma célula marcada variou entre estas duas fotografias.")
        else:
            st.markdown("**Células que moveram a dotação**")
            st.dataframe(
                _estilo_historico(tabela_cel, ("Antes", "Depois", "Efeito na dotação"), ("Efeito na dotação",)),
                hide_index=True, width="stretch",
            )
        if mudanca.anterior.celulas_marcadas != mudanca.atual.celulas_marcadas:
            st.caption(
                f"Células marcadas: {mudanca.anterior.celulas_marcadas} → {mudanca.atual.celulas_marcadas}."
            )
        if (mudanca.anterior.dotacao_sha, mudanca.anterior.execucao_sha) != (
            mudanca.atual.dotacao_sha, mudanca.atual.execucao_sha
        ):
            st.caption(
                "Extrações diferentes entre as fotografias: Dotação "
                f"{mudanca.anterior.dotacao_extracao} → {mudanca.atual.dotacao_extracao}; Execução Mensal "
                f"{mudanca.anterior.execucao_extracao} → {mudanca.atual.execucao_extracao}."
            )

# --------------------------------------------------------------- Sobra prevista de empenho (15/10/2026)
st.subheader("8. Sobra prevista de empenho")
if _tabela_sobra is None:
    st.caption("Indisponível: a projeção pela execução de Contratos e Bolsas não pôde ser montada (ver os avisos).")
else:
    _resumo_sobra = resumo_da_sobra(_tabela_sobra)
    _total_sobra = _resumo_sobra.iloc[-1]
    st.caption(
        "Empenho que, pela projeção pela execução (com os seus ajustes), não será liquidado no exercício: saldo do empenho "
        "menos a despesa projetada até dezembro. É informativa: não entra na conta do resultado (que mede o executado e o "
        "projetado) e alimenta o relatório de Anulação."
    )
    st.markdown(
        _sem_latex(
            f"**{int(_total_sobra['Nº de NEs'])} NE(s) com sobra prevista, {formatar_brl(_total_sobra['Sobra prevista (R$)'])}** "
            f"(dessas NEs, se o fornecedor faturar o valor cheio do contrato: {formatar_brl(_total_sobra['Sobra pelo valor cheio (R$)'])})."
        )
    )
    st.dataframe(
        _resumo_sobra, hide_index=True, width="stretch",
        column_config={
            "Sobra prevista (R$)": currency_column("Sobra prevista (R$)"),
            "Sobra pelo valor cheio (R$)": currency_column("Sobra pelo valor cheio (R$)"),
        },
    )
    _contexto_sobra = ContextoSobra(
        exercicio=exercicio,
        execucao_mensal=f"extração {data_execucao:%d/%m/%Y} · sha {manifesto_execucao.sha256[:8]}",
        liquidacao_competencia=(
            f"{CAMINHO_LIQUIDACAO_COMPETENCIA.name} · modificado em "
            f"{datetime.fromtimestamp(CAMINHO_LIQUIDACAO_COMPETENCIA.stat().st_mtime):%d/%m/%Y %H:%M}"
            if CAMINHO_LIQUIDACAO_COMPETENCIA.exists() else "não encontrada"
        ),
        emitido_em=datetime.now().strftime("%d/%m/%Y %H:%M"),
    )
    st.download_button(
        "Baixar Excel — sobra prevista por NE",
        data=lambda: gerar_xlsx_sobra(_relatorios_sobra, data_execucao.date(), _contexto_sobra),
        file_name=f"sobra_prevista_empenho_{exercicio}_{datetime.now():%Y-%m-%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="ro_baixar_sobra",
    )

st.info(
    "As extrações de Dotação Anual e de Execução Mensal são independentes: Dotação de "
    f"{data_dotacao:%d/%m/%Y} (hash {manifesto_dotacao.sha256[:8]}) e Execução Mensal de "
    f"{data_execucao:%d/%m/%Y} (hash {manifesto_execucao.sha256[:8]}). Confira as datas antes de usar o resultado."
)

gc.collect()  # ver o comentário no início da página
