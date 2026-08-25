"""Pop-up "Relatório de Reforço de Empenho" — botão reutilizável em
`app_pages/bolsas_auxilios.py` e `app_pages/contratos_continuos.py` (pedido explícito: um
botão em cada página, ao lado do botão de "+ Novo programa/contrato", não uma página separada
condensando as duas bases).

Uma tabela só (pedido explícito — nada de tabela de referência + tabela de edição separadas):
Item de Despesa / Empenho (só leitura) e Meses a Empenhar / Empenhar (R$) (as duas editáveis,
pedido explícito — as duas são campos personalizáveis, não só "Meses").

Regra de prioridade entre as duas colunas editáveis (pedido explícito): editar "Meses a
Empenhar" SEMPRE recalcula "Empenhar (R$)" (= meses × valor mensal da linha), mesmo que a
célula já tivesse um valor digitado à mão antes — a edição de meses vence. Editar "Empenhar
(R$)" direto fica valendo como está (sem alterar "Meses a Empenhar") até a próxima vez que
"Meses a Empenhar" for editado nessa mesma linha.

Implementado com um contador de "geração" que troca a key do `st.data_editor` quando há
edição de "Meses a Empenhar" — sem trocar a key, a célula "Empenhar (R$)" fica travada no
valor com que o widget nasceu, ignorando qualquer novo `tabela_editor` que passarmos depois. O
delta da edição é lido da key ATUAL logo no início desta função (resposta à interação que o
usuário acabou de commitar com Enter/Tab), e a troca de key acontece ANTES de desenhar o
widget — tudo dentro do MESMO rerun que o commit do usuário já disparou, sem precisar de
`st.rerun()` (que, chamado de dentro de `@st.dialog`, FECHA o pop-up inteiro em vez de só
re-renderizar — bug real observado antes desta versão).

Linha com "Meses a Empenhar" OU "Empenhar (R$)" igual a zero fica de fora do PDF (pedido
explícito — não há o que reforçar), mas continua visível/editável na tela (não é escondida da
edição, só do relatório final).

Contrato público:
    render_botao_relatorio(df, spec, chave) -> None
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.relatorio_reforco_empenho import (
    EspecificacaoRelatorio,
    excluir_linhas_zeradas,
    gerar_pdf_detalhado,
    gerar_pdf_resumido,
    linhas_para_processo,
    processos_disponiveis,
)
from src.ui_theme import format_brl_full


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

    # `\$` escapado: dois "R$" no mesmo texto viravam um par de delimitadores de fórmula
    # (o Markdown do Streamlit trata "$...$" como LaTeX) — bug real observado (texto saía
    # em itálico, com espaços comidos, entre o primeiro e o segundo "R$").
    st.caption(
        "Edite \"Meses a Empenhar\" (recalcula \"Empenhar (R\\$)\" automaticamente) OU digite "
        "direto em \"Empenhar (R\\$)\" para um valor personalizado — editar \"Meses a Empenhar\" "
        "de novo sempre sobrescreve o valor digitado direto. Linha com meses ou valor igual a "
        "zero não entra no PDF."
    )

    # `valores` é o estado de verdade (meses/empenhar por linha), independente do que o
    # widget mostra — precisa sobreviver a reruns sem se perder (por isso mora aqui, não é
    # recriado do zero a cada execução do script, só na primeira vez que este processo é
    # aberto).
    estado_key = f"reforco_valores_{chave}_{processo}"
    if estado_key not in st.session_state:
        meses_iniciais = linhas["meses_sugeridos"].round(2)
        st.session_state[estado_key] = pd.DataFrame(
            {
                "meses": meses_iniciais,
                "empenhar": (meses_iniciais * linhas["valor_mensal"]).round(2),
            }
        )
    valores = st.session_state[estado_key]

    # `geração` troca a key do editor quando uma edição de "Meses a Empenhar" pede um
    # recálculo visível na própria grade — sem trocar a key, a célula "Empenhar (R$)" fica
    # travada no valor com que o widget nasceu, ignorando qualquer novo `tabela_editor` que
    # passarmos depois (o `st.data_editor` só respeita o argumento inicial + o que o próprio
    # usuário editou NAQUELA key; um valor recalculado por nós não é "o que o usuário editou").
    # O delta é lido da key ATUAL, ANTES de decidir a key desta renderização — é a resposta à
    # interação que o usuário acabou de commitar (Enter/Tab), já disponível nesta mesma
    # execução: não precisa de `st.rerun()` (que, dentro de `@st.dialog`, fecha o pop-up —
    # bug real observado, ver docstring do módulo).
    geracao_key = f"reforco_geracao_{chave}_{processo}"
    geracao = st.session_state.setdefault(geracao_key, 0)
    editor_key = f"reforco_editor_{chave}_{processo}_{geracao}"

    delta = st.session_state.get(editor_key, {})
    houve_edicao_de_meses = False
    for posicao, mudancas in delta.get("edited_rows", {}).items():
        if "Meses a Empenhar" in mudancas:
            novo_meses = float(mudancas["Meses a Empenhar"])
            valor_mensal_linha = float(linhas.iloc[posicao]["valor_mensal"])
            valores.iat[posicao, valores.columns.get_loc("meses")] = novo_meses
            valores.iat[posicao, valores.columns.get_loc("empenhar")] = round(novo_meses * valor_mensal_linha, 2)
            houve_edicao_de_meses = True
        elif "Empenhar (R$)" in mudancas:
            valores.iat[posicao, valores.columns.get_loc("empenhar")] = float(mudancas["Empenhar (R$)"])

    st.session_state[estado_key] = valores

    if houve_edicao_de_meses:
        geracao += 1
        st.session_state[geracao_key] = geracao
        editor_key = f"reforco_editor_{chave}_{processo}_{geracao}"

    tabela_editor = pd.DataFrame(
        {
            "Item de Despesa": linhas["item_despesa"].to_numpy(),
            "Empenho": linhas["ne_curta"].to_numpy(),
            "Meses a Empenhar": valores["meses"].to_numpy(),
            "Empenhar (R$)": valores["empenhar"].to_numpy(),
        }
    )
    st.data_editor(
        tabela_editor,
        key=editor_key,
        disabled=["Item de Despesa", "Empenho"],
        column_config={
            "Meses a Empenhar": st.column_config.NumberColumn(step=0.01, min_value=0.0, format="%.2f"),
            "Empenhar (R$)": st.column_config.NumberColumn(step=0.01, min_value=0.0, format="R$ %.2f"),
        },
        hide_index=True,
        width="stretch",
    )

    # sempre a partir de `valores` (o estado que acabamos de reconciliar acima), nunca do
    # retorno cru do widget — ver docstring do módulo sobre o atraso de um clique na célula.
    linhas_finais = linhas.assign(
        meses=valores["meses"].to_numpy(),
        empenhar=valores["empenhar"].to_numpy(),
    )

    total = float(linhas_finais["empenhar"].sum())
    st.metric("Total a Empenhar", format_brl_full(total))

    linhas_para_pdf = excluir_linhas_zeradas(linhas_finais)

    # dois modelos em uso pela PROPLAD (ver docstring de src/relatorio_reforco_empenho.py) —
    # os dois precisam ser emitidos, não é escolha de um ou outro.
    nome_arquivo = processo.replace("/", "-")
    col_detalhado, col_resumido = st.columns(2)
    with col_detalhado:
        st.download_button(
            "Baixar PDF — Modelo Detalhado",
            data=gerar_pdf_detalhado(spec, processo, linhas_para_pdf),
            file_name=f"reforco_empenho_detalhado_{nome_arquivo}.pdf",
            mime="application/pdf",
            type="primary",
            width="stretch",
            key=f"reforco_download_detalhado_{chave}_{processo}",
        )
    with col_resumido:
        st.download_button(
            "Baixar PDF — Modelo Resumido",
            data=gerar_pdf_resumido(spec, processo, linhas_para_pdf),
            file_name=f"reforco_empenho_resumido_{nome_arquivo}.pdf",
            mime="application/pdf",
            width="stretch",
            key=f"reforco_download_resumido_{chave}_{processo}",
        )


def render_botao_relatorio(df: pd.DataFrame, spec: EspecificacaoRelatorio, chave: str) -> None:
    """Botão que abre o pop-up de emissão do relatório — chamar de dentro da página, com o
    DataFrame já lido por ela (não relê a planilha) e uma `chave` distinta por página
    (namespace de `st.session_state`, para as páginas conviverem sem colidir chaves de
    widget)."""

    if st.button("📄 Relatório de Reforço de Empenho", key=f"reforco_abrir_{chave}"):
        _abrir_relatorio(df, spec, chave)
