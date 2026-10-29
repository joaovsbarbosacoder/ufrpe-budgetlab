"""Leituras com cache e montagem da necessidade compartilhadas pelas páginas do Resultado Orçamentário e do Discricionário por
Plano (29/10/2026).

Código movido de `app_pages/resultado_orcamentario.py` sem alterar a lógica, para a página nova do discricionário não duplicar a
leitura das bases. `@st.cache_data` guarda só os derivados (memória). Camada de interface: importa Streamlit.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src import bolsas_auxilios_cadastro as cadastro_bolsas
from src import contratos_continuos_cadastro as cadastro_contratos
from src import projecao_ajustes
from src.execucao_ne_utils import ne_curta as _ne_curta_execucao, saldo_por_ne
from src.importacao_dotacao import carregar_atual as carregar_dotacao_atual
from src.importacao_execucao_mensal import carregar_atual as carregar_execucao_mensal_atual
from src.liquidacao_competencia import ler_liquidacao_competencia, liquidado_por_ne, liquidado_por_ne_e_mes
from src.liquidacao_consumo import competencia_pelo_consumo
from src.projecao_ajustes import ErroAjuste, ajustes_vigentes
from src.relatorio_projecao_execucao import RelatorioProjecaoExecucao
from src.resultado_orcamentario import (
    ORIGEM_CONTRATOS,
    celulas_da_dotacao,
    empenhado_por_ne_e_celula,
)
from src.resultado_orcamentario_fontes import projecao_bolsas, projecao_contratos, tabela_bolsas, tabela_contratos
from src.tesouro_execucao_mensal import agregar_por_ne, linha_do_tempo_por_ne, primeiro_mes_com_empenho_por_ne

#: mesmo arquivo de `app_pages/contratos_continuos.py` e `app_pages/bolsas_auxilios.py`.
CAMINHO_LIQUIDACAO_COMPETENCIA = Path("data/raw") / "Liquidação por Competência.xlsx"


# ------------------------------------------------------------------- leituras (cache)
@st.cache_data(show_spinner="Lendo a base de Dotação Anual...")
def cached_celulas_por_exercicio(caminho_ponteiro: str, mtime_ponteiro: float) -> dict[int, pd.DataFrame]:
    """Células (`celulas_da_dotacao`) de cada exercício presente na Dotação Anual. Guarda só o
    derivado, não a base inteira (memória: ver o comentário de `gc.collect()` no fim da página).
    `caminho_ponteiro`/`mtime_ponteiro` só participam da chave de cache."""

    dotacao = carregar_dotacao_atual()
    anos = sorted(int(ano) for ano in dotacao["ano_lancamento"].dropna().unique())
    return {ano: celulas_da_dotacao(dotacao, ano) for ano in anos}


@st.cache_data(show_spinner="Lendo a base de Execução Mensal...")
def cached_execucao(
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
def cached_lancamento(caminho_ponteiro: str, mtime_ponteiro: float) -> pd.DataFrame:
    """Liquidado por (NE, mês de LANÇAMENTO) da Execução Mensal, com `ne_curta` — usado só para medir pelo consumo
    do orçamento as NEs com competência em exercício posterior (`src/liquidacao_consumo.py`)."""

    tempo = linha_do_tempo_por_ne(carregar_execucao_mensal_atual())
    tempo["ne_curta"] = tempo["ne_ccor"].apply(_ne_curta_execucao)
    return tempo


@st.cache_data(show_spinner="Lendo a Liquidação por Competência...")
def cached_liquidacao_competencia(caminho: str, mtime: float) -> tuple[pd.Series, pd.DataFrame]:
    """`(total liquidado por NE curta, liquidado por NE e mês com ne_curta)` — as duas leituras que
    `app_pages/contratos_continuos.py` faz em separado, aqui numa só. `mtime` só participa da chave."""

    base = ler_liquidacao_competencia(caminho)
    totais = liquidado_por_ne(base)
    indice = pd.Series(totais.to_numpy(), index=[_ne_curta_execucao(ne) for ne in totais.index])
    por_mes = liquidado_por_ne_e_mes(base)
    por_mes["ne_curta"] = por_mes["ne_ccor"].apply(_ne_curta_execucao)
    return indice, por_mes


# ------------------------------------------------------------------- necessidade
def necessidade_origem(
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
