"""Resultado Orçamentário — a dotação das células escolhidas cobre o que ainda falta empenhar?

Pedido explícito do usuário (08/10/2026): o usuário marca um "bolsão" de células da Dotação Anual
(IDUSO, resultado primário, ação, PTRES, plano orçamentário, grupo de despesa e fonte detalhada) e a
página mostra `Resultado = Dotação Atualizada das células − Empenhado nas células − Necessidade de
empenho até dezembro`. A regra está em `src/resultado_orcamentario.py`; a persistência (seleção de
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
  * Necessidade de Contratos e Bolsas = relatório "Projeção pela Execução" SEM contrato antecessor
    (spec §10a: a escolha do antecessor na página de Contratos não é gravada). Nota sob a Necessidade
    de Contratos.
  * Liquidação por Competência ausente/ilegível, ou exercício sem cadastro de Contratos/Bolsas: a
    necessidade daquela origem fica INDISPONÍVEL ("—"), nunca zero, e o resultado fica incompleto.
  * Arquivo de seleção ou de despesas corrompido: erro visível e os botões de gravar ficam
    desabilitados (a página não grava por cima). Despesas ilegíveis também deixam o resultado
    incompleto — a página não sabe quanto elas somam.
  * Resultado exatamente zero aparece como "Equilíbrio" (o protótipo só tinha Superávit/Déficit; zero
    não é superávit — nulo, zero e negativo são estados distintos neste projeto).
"""

from __future__ import annotations

import gc
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
    soma_ou_nulo,
)
from src.resultado_orcamentario_cadastro import ArquivoCorrompido, CelulaChave, DespesaManual
from src.resultado_orcamentario_fontes import projecao_bolsas, projecao_contratos, tabela_bolsas, tabela_contratos
from src.tesouro_execucao_mensal import agregar_por_ne, linha_do_tempo_por_ne, primeiro_mes_com_empenho_por_ne
from src.ui_cadastro import formatar_brl
from src.ui_resultado_orcamentario import (
    ESTILO_CELULAS,
    LinhaComposicao,
    html_bloco,
    html_cabecalho_acao,
    html_cartoes,
    html_celula,
    html_dotacao_acao,
    html_rodape_totais,
)
from src.ui_theme import currency_column, render_page_header


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
) -> tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame, str | None, list[str]]:
    """`(cadastro com colunas derivadas, linhas da projeção ou None, sem_ne, motivo da indisponibilidade,
    avisos do relatório de projeção)`.

    Exercício sem cadastro ou Liquidação por Competência indisponível: linhas `None` (necessidade
    indisponível, não zero) e um motivo para o aviso."""

    vazio = pd.DataFrame(columns=["ne_curta"])
    modulo = cadastro_contratos if origem == ORIGEM_CONTRATOS else cadastro_bolsas
    if exercicio not in modulo.anos_disponiveis():
        return vazio, None, vazio, f"não há cadastro de {origem} para o exercício {exercicio}", []
    if origem == ORIGEM_CONTRATOS:
        dados = cadastro_contratos.como_dataframe(cadastro_contratos.carregar_contratos(exercicio), exercicio)
        tabela = tabela_contratos(dados, por_ne_execucao, indice_competencia, sugestao_inicio)
    else:
        dados = cadastro_bolsas.como_dataframe(cadastro_bolsas.carregar_programas(exercicio))
        tabela = tabela_bolsas(dados, por_ne_execucao, sugestao_inicio)
    if competencia is None:
        return tabela, None, vazio, "a Liquidação por Competência não está disponível", []
    if origem == ORIGEM_CONTRATOS:
        # Sem `antecessores` de propósito (spec §10a): NE sem histórico = fator 1, valor mensal cheio.
        relatorio, sem_ne = projecao_contratos(tabela, competencia, exercicio, mes_referencia)
    else:
        relatorio, sem_ne = projecao_bolsas(tabela, competencia, exercicio, mes_referencia)
    return tabela, relatorio.linhas, sem_ne, None, relatorio.avisos


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
def _render_cartoes(res: ResultadoOrcamentario, qtd_selecionadas: int, qtd_celulas: int) -> None:
    """Cartões no desenho do protótipo (08/10/2026): o do Resultado com borda, fundo e selo pela situação."""

    necessidades = list(res.necessidade.values())
    necessidade_total = None if any(v is None for v in necessidades) else float(sum(necessidades))
    if res.resultado is None:
        rodape = "Nenhuma célula selecionada" if not qtd_selecionadas else "Resultado incompleto — ver Avisos"
    else:
        rodape = f"{_pct(res.resultado, res.dotacao)} da dotação selecionada"
    st.html(
        html_cartoes(
            res.dotacao, f"{qtd_selecionadas} de {qtd_celulas} células selecionadas",
            res.empenhado_total, necessidade_total, res.resultado, rodape,
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


def _tabela_necessidade(linhas: pd.DataFrame, por_ne: pd.DataFrame, origem: str) -> pd.DataFrame:
    selecionadas = set(por_ne.loc[por_ne["celula_selecionada"], "ne_curta"])
    com_empenho = set(por_ne["ne_curta"])

    def _situacao(ne: object) -> str:
        if ne in selecionadas:
            return "selecionada"
        return "não selecionada" if ne in com_empenho else "sem empenho no exercício"

    if origem == ORIGEM_CONTRATOS:
        colunas = {"ne_curta": "NE", "contrato_numero": "Contrato", "fornecedor": "Fornecedor"}
    else:
        # na projeção de Bolsas o programa vem na coluna `fornecedor` (ver `src.projecao_execucao_bolsas`)
        colunas = {"ne_curta": "NE", "fornecedor": "Programa"}
    tabela = linhas[[*colunas, "fator", "necessidade_execucao"]].rename(
        columns={**colunas, "fator": "Fator", "necessidade_execucao": "Necessidade"}
    )
    tabela["Célula da NE"] = linhas["ne_curta"].map(_situacao)
    return tabela.reset_index(drop=True)


def _render_composicao(
    res: ResultadoOrcamentario,
    linhas_contratos: pd.DataFrame | None,
    linhas_bolsas: pd.DataFrame | None,
    despesas: list[DespesaManual],
) -> None:
    """Composição no desenho do protótipo (08/10/2026): linhas compactas com % e valor à direita, barra
    de proporção e o detalhe por NE (ou por despesa) ao abrir a linha. Os avisos da projeção ficam na
    seção Avisos."""

    col_empenhado, col_necessidade = st.columns(2)
    with col_empenhado:
        # -0,00 (resíduo de ponto flutuante) aparece como 0,00
        diferenca = round(res.diferenca_conferencia, 2) + 0.0
        fecha = abs(res.diferenca_conferencia) < TOLERANCIA_CONFERENCIA
        rodape = (
            "✓ Soma das linhas = empenhado total das células" if fecha
            else "✗ Soma das linhas não fecha com o empenhado total das células"
        ) + f" · diferença {formatar_brl(diferenca)}"
        st.html(
            html_bloco(
                "Empenhado nas células selecionadas",
                [
                    LinhaComposicao(
                        origem, res.empenhado[origem], _tabela_empenhado(res.empenhado_por_ne, origem),
                        ("Empenhado",), "Nenhuma NE desta origem nas células selecionadas.",
                    )
                    for origem in ORIGENS_EMPENHADO
                ],
                res.empenhado_total, "Total empenhado", rodape, "ok" if fecha else "erro",
            )
        )

    with col_necessidade:
        total = None if any(v is None for v in res.necessidade.values()) else float(sum(res.necessidade.values()))
        linhas_bloco = []
        for origem, linhas in ((ORIGEM_CONTRATOS, linhas_contratos), (ORIGEM_BOLSAS, linhas_bolsas)):
            if linhas is None:
                detalhe, vazio = None, "Indisponível — ver Avisos."
            else:
                detalhe, vazio = _tabela_necessidade(linhas, res.empenhado_por_ne, origem), "Nenhuma NE com necessidade."
            linhas_bloco.append(LinhaComposicao(origem, res.necessidade[origem], detalhe, ("Necessidade",), vazio))
        manual = pd.DataFrame({"Descrição": [d.descricao for d in despesas], "Valor": [d.valor for d in despesas]})
        linhas_bloco.append(
            LinhaComposicao(
                OUTRAS_DESPESAS, res.necessidade[OUTRAS_DESPESAS], manual, ("Valor",),
                "Nenhuma despesa cadastrada — ver a seção Outras despesas previstas.",
            )
        )
        st.html(
            html_bloco(
                "Necessidade de empenho até dezembro", linhas_bloco, total, "Total da necessidade",
                "Vale para todas as NEs, inclusive as de células não selecionadas. Projeção sem contrato "
                "antecessor: NE com menos de 3 meses fechados é projetada pelo valor mensal cheio.",
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
        "Necessidade: projeção pela execução"
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
if CAMINHO_LIQUIDACAO_COMPETENCIA.exists():
    try:
        indice_competencia, competencia = _cached_liquidacao_competencia(
            str(CAMINHO_LIQUIDACAO_COMPETENCIA), CAMINHO_LIQUIDACAO_COMPETENCIA.stat().st_mtime
        )
    except Exception as erro:
        avisos_extras.append(f"Não foi possível ler a Liquidação por Competência ({erro}).")
else:
    avisos_extras.append(f"Liquidação por Competência não encontrada ('{CAMINHO_LIQUIDACAO_COMPETENCIA}').")

mes_referencia = mes_referencia_do_exercicio(data_execucao.date(), exercicio)
fontes: dict[str, tuple[pd.DataFrame, pd.DataFrame | None, pd.DataFrame, list[str]]] = {}
for origem in (ORIGEM_CONTRATOS, ORIGEM_BOLSAS):
    try:
        tabela, linhas, sem_ne, motivo, avisos_projecao = _necessidade(
            origem, exercicio, por_ne_execucao, sugestao_inicio, indice_competencia, competencia, mes_referencia,
        )
    except Exception as erro:
        tabela, linhas, sem_ne, motivo, avisos_projecao = (
            pd.DataFrame(columns=["ne_curta"]), None, pd.DataFrame(), f"erro de leitura ({erro})", [],
        )
    if motivo:
        avisos_extras.append(f"Necessidade de {origem} indisponível: {motivo}.")
    fontes[origem] = (tabela, linhas, sem_ne, avisos_projecao)

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

# Cartões e Composição ficam no topo, mas dependem da seleção em edição (tabela mais abaixo):
# containers reservados aqui e preenchidos no fim.
area_cartoes = st.container()
st.subheader("2. Composição")
st.caption("Clique em uma linha para ver o detalhe por NE ou por despesa.")
area_composicao = st.container()

# --------------------------------------------------------------- Células
# Layout do protótipo aprovado em 08/10/2026 (`docs/superpowers/specs/2026-10-08-resultado-orcamentario-celulas-mockup.html`):
# células agrupadas por Ação, uma caixa de marcar por célula, "Marcar todas" por Ação, busca, filtro de
# selecionadas e rodapé fixo com os totais e "Salvar seleção". Substitui a tabela editável, que
# parecia uma planilha e mostrava os valores fora do formato brasileiro.
st.subheader("3. Células que fazem frente às despesas")
st.caption(
    "Marque as células da Dotação Anual que entram como recurso. As ações com célula marcada ficam abertas e "
    'destacadas. A seleção fica gravada por exercício ("Salvar seleção").'
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
    so_selecionadas = st.checkbox("Mostrar só as selecionadas", key="ro_so_selecionadas")

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
        with st.expander(rotulo,expanded=bool(qtd_selecionadas or busca or so_selecionadas)):
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
st.subheader(f"4. {OUTRAS_DESPESAS}")
st.caption(
    "Despesas que não estão em Contratos nem em Bolsas e ainda vão ser empenhadas no exercício. "
    "A célula é só informativa: não muda a conta."
)
if _CHAVE_FLASH in st.session_state:
    st.success(st.session_state.pop(_CHAVE_FLASH))

if despesas:
    # Editar/Excluir em cada linha, como no protótipo (08/10/2026); antes era um seletor separado.
    larguras = [3, 2.2, 2.4, 1.4, 0.8, 0.8]
    for coluna, titulo in zip(st.columns(larguras), ("Descrição", "Observação", "Célula (informativa)", "Valor a empenhar")):
        coluna.caption(f"**{titulo}**")
    for despesa in despesas:
        col_desc, col_obs, col_cel, col_valor, col_editar, col_excluir = st.columns(
            larguras, vertical_alignment="center"
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
    st.caption(_sem_latex(f"Total: {formatar_brl(sum(d.valor for d in despesas))}"))
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

# --------------------------------------------------------------- conta e topo
tabela_contratos_df, linhas_contratos, sem_ne_contratos, avisos_projecao_contratos = fontes[ORIGEM_CONTRATOS]
tabela_bolsas_df, linhas_bolsas, sem_ne_bolsas, avisos_projecao_bolsas = fontes[ORIGEM_BOLSAS]
resultado = calcular_resultado(
    celulas, empenhado, selecao_atual, tabela_contratos_df, tabela_bolsas_df,
    linhas_contratos, linhas_bolsas, sem_ne_contratos, sem_ne_bolsas, despesas,
)
if not despesas_legiveis:
    resultado = replace(
        resultado,
        necessidade={**resultado.necessidade, OUTRAS_DESPESAS: None},
        resultado=None,
        incompleto=bool(selecao_atual),
        avisos=[*resultado.avisos, "Outras despesas previstas ilegíveis: resultado incompleto."],
    )

with area_cartoes:
    _render_cartoes(resultado, len(marcadas), len(celulas))
with area_composicao:
    _render_composicao(resultado, linhas_contratos, linhas_bolsas, despesas)

# --------------------------------------------------------------- Avisos
st.subheader("5. Avisos")
# Avisos da projeção (fator baixo, meses em aberto…) ficam aqui, como no protótipo (08/10/2026).
avisos_projecao = [
    f"Projeção de {origem}: {aviso}"
    for origem, lista in ((ORIGEM_CONTRATOS, avisos_projecao_contratos), (ORIGEM_BOLSAS, avisos_projecao_bolsas))
    for aviso in lista
]
for aviso in [*resultado.avisos, *avisos_extras, *avisos_projecao]:
    if aviso.startswith("Nenhuma célula selecionada"):
        st.info(_sem_latex(aviso))
    else:
        st.warning(_sem_latex(aviso))
for origem, sem_ne in ((ORIGEM_CONTRATOS, sem_ne_contratos), (ORIGEM_BOLSAS, sem_ne_bolsas)):
    if sem_ne is not None and len(sem_ne):
        colunas = [
            c for c in ("contrato_numero", "fornecedor", "programa_bolsa", "processo", "valor_mensal", "necessidade")
            if c in sem_ne.columns
        ]
        with st.expander(f"Ver {origem} sem NE ({len(sem_ne)})"):
            st.dataframe(
                sem_ne[colunas], hide_index=True, width="stretch",
                column_config={
                    c: currency_column(c) for c in ("valor_mensal", "necessidade") if c in colunas
                },
            )
st.info(
    "As extrações de Dotação Anual e de Execução Mensal são independentes: Dotação de "
    f"{data_dotacao:%d/%m/%Y} (hash {manifesto_dotacao.sha256[:8]}) e Execução Mensal de "
    f"{data_execucao:%d/%m/%Y} (hash {manifesto_execucao.sha256[:8]}). Confira as datas antes de usar o resultado."
)

gc.collect()  # ver o comentário no início da página
