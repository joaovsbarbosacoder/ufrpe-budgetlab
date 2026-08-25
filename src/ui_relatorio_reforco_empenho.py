"""Pop-up "Relatório de Reforço de Empenho" — botão reutilizável em
`app_pages/bolsas_auxilios.py` e `app_pages/contratos_continuos.py` (pedido explícito: um
botão em cada página, não uma página separada condensando as duas bases).

Monta a tabela no formato usado pela PROPLAD para pedidos de reforço de empenho (Processo,
Item de Despesa, Unidade, Ação, PTRES, Fonte, ND, UGR, PI, Empenho, Empenhar (R$); ver
histórico da conversa para os PDFs de referência), a partir do DataFrame que a própria página
já leu (sem reler a planilha aqui — ver `render_botao_relatorio`), e gera o PDF final para
download dentro do pop-up.

"Meses a Empenhar" é editável LINHA A LINHA (pedido explícito — personalizado por empenho,
não um número só para o processo inteiro): a tabela já vem preenchida com o valor sugerido
(`meses_a_empenhar`, calculado em `necessidade_empenho.py`), mas cada linha pode ser ajustada
livremente antes de gerar o PDF. "Empenhar (R$)" nunca é editado diretamente — é sempre
`meses × valor mensal` da própria linha, recalculado a cada edição, para os dois campos nunca
saírem de sincronia.

Contrato público:
    render_botao_relatorio(df, spec, chave) -> None
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.relatorio_reforco_empenho import (
    EspecificacaoRelatorio,
    gerar_pdf,
    linhas_para_processo,
    processos_disponiveis,
)
from src.ui_theme import format_brl_full

_COLUNAS_EDITOR = {
    "item_despesa": "Item de Despesa", "unidade_cod": "Unidade", "acao_cod": "Ação",
    "ptres": "PTRES", "fonte_cod": "Fonte", "natureza_despesa_cod": "ND", "ugr_cod": "UGR",
    "pi_cod": "PI", "ne_curta": "Empenho", "meses_sugeridos": "Meses a Empenhar",
}
_COLUNAS_SOMENTE_LEITURA = [v for k, v in _COLUNAS_EDITOR.items() if k != "meses_sugeridos"]


@st.dialog("Relatório de Reforço de Empenho", width="large")
def _abrir_relatorio(df: pd.DataFrame, spec: EspecificacaoRelatorio, chave: str) -> None:
    processos = processos_disponiveis(df, spec)
    if not processos:
        st.warning("Nenhum processo com empenho reconhecível nesta base.")
        return

    processo = st.selectbox("Processo", processos, key=f"reforco_processo_{chave}")

    linhas = linhas_para_processo(df, spec, processo)
    if linhas.empty:
        st.warning("Nenhuma linha de empenho para este processo.")
        return

    st.caption(
        "Ajuste \"Meses a Empenhar\" linha a linha — \"Empenhar (R$)\" é sempre recalculado "
        "(meses × valor mensal), nunca editado direto."
    )

    tabela_editor = linhas.rename(columns=_COLUNAS_EDITOR)[list(_COLUNAS_EDITOR.values())].copy()
    tabela_editor["Meses a Empenhar"] = tabela_editor["Meses a Empenhar"].round(2)

    editado = st.data_editor(
        tabela_editor,
        key=f"reforco_editor_{chave}_{processo}",
        disabled=_COLUNAS_SOMENTE_LEITURA,
        column_config={
            # `step` PRECISA bater com as casas decimais de `format` — com step=0.1 e
            # format="%.2f", a célula chegou a EXIBIR o valor arredondado para a casa de
            # 0,1 (ex. "0.90") enquanto o valor de verdade usado no cálculo de "Empenhar
            # (R$)" era 0,92 (bug real observado: os dois quadros mostravam números
            # diferentes pro mesmo empenho). step=0.01 mantém exibição e cálculo em sincronia.
            "Meses a Empenhar": st.column_config.NumberColumn(step=0.01, min_value=0.0, format="%.2f"),
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
        key=f"reforco_download_{chave}_{processo}",
    )


def render_botao_relatorio(df: pd.DataFrame, spec: EspecificacaoRelatorio, chave: str) -> None:
    """Botão que abre o pop-up de emissão do relatório — chamar de dentro da página, com o
    DataFrame já lido por ela (não relê a planilha) e uma `chave` distinta por página
    (namespace de `st.session_state`, para as páginas conviverem sem colidir chaves de
    widget)."""

    if st.button("📄 Relatório de Reforço de Empenho", key=f"reforco_abrir_{chave}"):
        _abrir_relatorio(df, spec, chave)
