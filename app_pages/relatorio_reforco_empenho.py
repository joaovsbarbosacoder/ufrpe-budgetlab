"""Relatório de Reforço de Empenho — Bolsas e Auxílios / Contratos Contínuos.

Monta a tabela no formato usado pela PROPLAD para pedidos de reforço de empenho (Processo,
Item de Despesa, Unidade, Ação, PTRES, Fonte, ND, UGR, PI, Empenho, Empenhar (R$); ver
histórico da conversa para os PDFs de referência) a partir das bases já lidas/validadas de
Bolsas e Auxílios e Contratos Contínuos (`src/relatorio_reforco_empenho.py`), e gera o PDF
final para download.

"Meses a Empenhar" é editável LINHA A LINHA (pedido explícito — personalizado por empenho,
não um número só para o processo inteiro): a tabela abaixo já vem preenchida com o valor
sugerido (`meses_a_empenhar`, calculado em `necessidade_empenho.py`), mas cada linha pode ser
ajustada livremente antes de gerar o PDF. "Empenhar (R$)" nunca é editado diretamente — é
sempre `meses × valor mensal` da própria linha, recalculado a cada edição, para os dois
campos nunca saírem de sincronia.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.bolsas_auxilios import ler_bolsas_auxilios
from src.contratos_continuos import ler_contratos_continuos
from src.relatorio_reforco_empenho import (
    BOLSAS_AUXILIOS,
    CONTRATOS_CONTINUOS,
    EspecificacaoRelatorio,
    gerar_pdf,
    linhas_para_processo,
    processos_disponiveis,
)
from src.ui_theme import format_brl_full, render_page_header

DIRETORIO_DADOS_BRUTOS = Path("data/raw")
CAMINHO_BOLSAS = DIRETORIO_DADOS_BRUTOS / "BOLSAS E AUXÍLIOS 2026 - AGO A DEZ.xlsx"
CAMINHO_CONTINUOS = DIRETORIO_DADOS_BRUTOS / "SERVIÇOS CONTÍNUOS - 2026 - AGO A DEZ.xlsm"

#: rótulo escolhido na tela -> (caminho da planilha, leitor, spec do relatório).
BASES: dict[str, tuple[Path, object, EspecificacaoRelatorio]] = {
    "Bolsas e Auxílios": (CAMINHO_BOLSAS, ler_bolsas_auxilios, BOLSAS_AUXILIOS),
    "Contratos Contínuos": (CAMINHO_CONTINUOS, ler_contratos_continuos, CONTRATOS_CONTINUOS),
}

_COLUNAS_EDITOR = {
    "item_despesa": "Item de Despesa", "unidade_cod": "Unidade", "acao_cod": "Ação",
    "ptres": "PTRES", "fonte_cod": "Fonte", "natureza_despesa_cod": "ND", "ugr_cod": "UGR",
    "pi_cod": "PI", "ne_curta": "Empenho", "meses_sugeridos": "Meses a Empenhar",
}
_COLUNAS_SOMENTE_LEITURA = [v for k, v in _COLUNAS_EDITOR.items() if k != "meses_sugeridos"]


@st.cache_data(show_spinner="Lendo a planilha de Bolsas e Auxílios...")
def _cached_bolsas(caminho: str, mtime: float) -> pd.DataFrame:
    return ler_bolsas_auxilios(caminho)


@st.cache_data(show_spinner="Lendo a planilha de Contratos Contínuos...")
def _cached_continuos(caminho: str, mtime: float) -> pd.DataFrame:
    return ler_contratos_continuos(caminho)


_LEITORES_CACHEADOS = {
    "Bolsas e Auxílios": _cached_bolsas,
    "Contratos Contínuos": _cached_continuos,
}


# ---------------------------------------------------------------------- página
render_page_header(
    "Relatório de Reforço de Empenho",
    "Bolsas e Auxílios ou Contratos Contínuos, por processo — meses a empenhar editável "
    "linha a linha, PDF pronto para o pedido de reforço.",
    "Contratos",
)

base_escolhida = st.radio("Base", list(BASES.keys()), horizontal=True, key="reforco_base")
caminho_planilha, _, spec = BASES[base_escolhida]

if not caminho_planilha.exists():
    st.info(f"A planilha de '{base_escolhida}' não foi encontrada em '{caminho_planilha}'.")
    st.stop()

try:
    dataframe = _LEITORES_CACHEADOS[base_escolhida](str(caminho_planilha), caminho_planilha.stat().st_mtime)
except Exception as error:
    st.error(f"Não foi possível ler '{base_escolhida}': {error}")
    st.stop()

processos = processos_disponiveis(dataframe, spec)
if not processos:
    st.warning("Nenhum processo com empenho reconhecível nesta base.")
    st.stop()

processo = st.selectbox("Processo", processos, key=f"reforco_processo_{base_escolhida}")

linhas = linhas_para_processo(dataframe, spec, processo)
if linhas.empty:
    st.warning("Nenhuma linha de empenho para este processo.")
    st.stop()

st.caption(
    "Ajuste \"Meses a Empenhar\" linha a linha — \"Empenhar (R$)\" é sempre recalculado "
    "(meses × valor mensal), nunca editado direto."
)

tabela_editor = linhas.rename(columns=_COLUNAS_EDITOR)[list(_COLUNAS_EDITOR.values())].copy()
tabela_editor["Meses a Empenhar"] = tabela_editor["Meses a Empenhar"].round(2)

editado = st.data_editor(
    tabela_editor,
    key=f"reforco_editor_{base_escolhida}_{processo}",
    disabled=_COLUNAS_SOMENTE_LEITURA,
    column_config={
        "Meses a Empenhar": st.column_config.NumberColumn(step=0.1, min_value=0.0, format="%.2f"),
    },
    hide_index=True,
    width="stretch",
)

linhas_finais = linhas.assign(
    empenhar=editado["Meses a Empenhar"].to_numpy() * linhas["valor_mensal"].to_numpy()
)

pre_visualizacao = pd.DataFrame(
    {
        "Item de Despesa": linhas_finais["item_despesa"],
        "Empenho": linhas_finais["ne_curta"],
        "Meses a Empenhar": editado["Meses a Empenhar"].to_numpy(),
        # string formatada (não NumberColumn) — column_config "R$ %.2f" usa ponto decimal
        # (padrão do printf do Streamlit), não o padrão pt-BR (vírgula) do resto do app.
        "Empenhar (R$)": linhas_finais["empenhar"].apply(format_brl_full),
    }
)
st.dataframe(pre_visualizacao, hide_index=True, width="stretch")

total = float(linhas_finais["empenhar"].sum())
st.metric("Total a Empenhar", format_brl_full(total))

pdf_bytes = gerar_pdf(spec, processo, linhas_finais)
nome_arquivo = f"reforco_empenho_{processo.replace('/', '-')}.pdf"
st.download_button(
    "Baixar PDF",
    data=pdf_bytes,
    file_name=nome_arquivo,
    mime="application/pdf",
    type="primary",
)
