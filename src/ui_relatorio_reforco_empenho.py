"""Pop-up "Relatórios" (Reforço de Empenho / Anulação de Saldo de Empenho) — botão
reutilizável em `app_pages/bolsas_auxilios.py` e `app_pages/contratos_continuos.py` (pedido
explícito: um botão em cada página, ao lado do botão de "+ Novo programa/contrato", não uma
página separada condensando as duas bases).

UM BOTÃO SÓ, DOIS RELATÓRIOS (pedido explícito posterior — antes só existia o Reforço): o
botão abre um pop-up que primeiro pergunta qual relatório emitir (`TIPO_REFORCO`/
`TIPO_ANULACAO`, `src/relatorio_reforco_empenho.py`) e, escolhido, renderiza o mesmo
conteúdo (seletor de processo + tabela editável + os dois PDFs) parametrizado por
`TipoRelatorio` — mesma mecânica, só rótulos/valor inicial diferentes entre os dois. Os dois
passos (escolha do tipo, depois o conteúdo) vivem dentro do MESMO `@st.dialog` — trocar de
tela NÃO chama `st.rerun()` (que, de dentro de um dialog já aberto, FECHA o pop-up inteiro —
ver mais abaixo); a escolha só grava `st.session_state` e deixa o rerun natural do clique do
botão levar adiante, com a variável local já atualizada no mesmo run (sem exigir um segundo
clique).

Uma tabela só por relatório (pedido explícito — nada de tabela de referência + tabela de
edição separadas): Item de Despesa / Empenho (só leitura) e Meses a Empenhar|Anular / Rótulo
de valor (R$) (as duas editáveis, pedido explícito — as duas são campos personalizáveis, não
só "Meses").

Regra de prioridade entre as duas colunas editáveis (pedido explícito): editar a coluna de
meses SEMPRE recalcula a coluna de valor (= meses × valor mensal da linha), mesmo que a
célula já tivesse um valor digitado à mão antes — a edição de meses vence. Editar o valor
direto fica valendo como está (sem alterar a coluna de meses) até a próxima vez que a coluna
de meses for editada nessa mesma linha.

Implementado com um contador de "geração" que troca a key do `st.data_editor` quando há
edição da coluna de meses — sem trocar a key, a célula de valor fica travada no valor com que
o widget nasceu, ignorando qualquer novo `tabela_editor` que passarmos depois. O delta da
edição é lido da key ATUAL logo no início desta função (resposta à interação que o usuário
acabou de commitar com Enter/Tab), e a troca de key acontece ANTES de desenhar o widget —
tudo dentro do MESMO rerun que o commit do usuário já disparou, sem precisar de `st.rerun()`
(que, chamado de dentro de `@st.dialog`, FECHA o pop-up inteiro em vez de só re-renderizar —
bug real observado antes desta versão).

Linha com meses OU valor igual a zero fica de fora do PDF (pedido explícito — não há o que
lançar), mas continua visível/editável na tela (não é escondida da edição, só do relatório
final).

VALOR INICIAL DIFERE ENTRE OS DOIS TIPOS (pedido explícito): Reforço sugere a partir de
`meses_sugeridos` (necessidade calculada — execução ou "por calendário", ver
`src/relatorio_reforco_empenho.py`); Anulação de Saldo de Empenho NÃO tem sugestão nenhuma —
toda linha começa em zero, quem emite decide quanto anular linha a linha (pedido explícito:
"sem sugestão automática — todas as linhas começam zeradas").

ESTADO NÃO SOBREVIVE A FECHAR O POP-UP (pedido explícito): tanto a escolha do tipo de
relatório quanto os valores editados só valem enquanto o mesmo pop-up continua aberto.
`render_botao_relatorio` apaga esse estado (`_limpar_estado_relatorio`) toda vez que o botão
que abre o pop-up é clicado — único jeito de "reabrir" (`st.dialog` não avisa quando foi
fechado), então limpar no clique do botão equivale a limpar no fechamento anterior; reabrir
sempre volta à tela de escolha do relatório.

PONTUAÇÃO DE MILHAR nas colunas editáveis (pedido explícito): `st.column_config.NumberColumn`
aceita `,` (sprintf-js) pra agrupar milhar, mas só no padrão americano ("1,234.57") — colunas
editáveis não aceitam HTML customizado (só leitura consegue o pt-BR completo de
`format_brl_full`, "1.234,57", usado no `st.metric` de total abaixo da grade).

Contrato público:
    render_botao_relatorio(df, spec, chave) -> None
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.relatorio_reforco_empenho import (
    TIPO_ANULACAO,
    TIPO_REFORCO,
    EspecificacaoRelatorio,
    TipoRelatorio,
    excluir_linhas_zeradas,
    gerar_pdf_detalhado,
    gerar_pdf_resumido,
    linhas_para_processo,
    processos_disponiveis,
)
from src.ui_theme import format_brl_full

_TIPOS = (TIPO_REFORCO, TIPO_ANULACAO)


@st.dialog("Relatórios", width="large")
def _abrir_relatorios(df: pd.DataFrame, spec: EspecificacaoRelatorio, chave: str) -> None:
    tipo_key = f"reforco_tipo_{chave}"
    tipo_id = st.session_state.get(tipo_key)

    if tipo_id is not None and st.button("← Voltar", key=f"reforco_voltar_{chave}"):
        _limpar_estado_relatorio(chave)
        tipo_id = None

    if tipo_id is None:
        # Escolha do relatório dentro do MESMO dialog (não um segundo `st.dialog` — Streamlit
        # proíbe dialog dentro de dialog, mesma restrição já contornada em
        # `app_pages/contratos_continuos.py::_abrir_resumo_completo`). Sem `st.rerun()` aqui de
        # propósito (fecharia o pop-up, ver docstring do módulo): a variável local `tipo_id` é
        # atualizada no próprio clique, então o conteúdo do relatório já aparece neste mesmo
        # run, sem exigir um segundo clique.
        st.caption("Escolha o relatório que deseja emitir.")
        for tipo in _TIPOS:
            if st.button(f"📄 {tipo.rotulo_escolha}", key=f"reforco_escolher_{chave}_{tipo.id}", width="stretch"):
                st.session_state[tipo_key] = tipo.id
                tipo_id = tipo.id
        if tipo_id is None:
            return

    tipo = TIPO_REFORCO if tipo_id == "reforco" else TIPO_ANULACAO
    st.divider()
    _render_conteudo_relatorio(df, spec, tipo, chave)


def _render_conteudo_relatorio(
    df: pd.DataFrame, spec: EspecificacaoRelatorio, tipo: TipoRelatorio, chave: str
) -> None:
    """Seletor de processo + tabela editável + os dois PDFs — conteúdo compartilhado entre
    Reforço e Anulação (`_abrir_relatorios`, acima), parametrizado por `tipo`. Toda key de
    `st.session_state`/widget inclui `tipo.id` para as duas telas nunca colidirem quando o
    mesmo processo é usado nos dois relatórios dentro da mesma sessão."""

    processos = processos_disponiveis(df, spec)
    if not processos:
        st.warning("Nenhum processo com empenho reconhecível nesta base.")
        return

    processo = st.selectbox("Processo", processos, key=f"reforco_processo_{chave}_{tipo.id}")

    linhas = linhas_para_processo(df, spec, processo)
    if linhas.empty:
        st.warning("Nenhuma linha de empenho para este processo.")
        return

    # `\$` escapado: dois "R$" no mesmo texto viravam um par de delimitadores de fórmula
    # (o Markdown do Streamlit trata "$...$" como LaTeX) — bug real observado (texto saía
    # em itálico, com espaços comidos, entre o primeiro e o segundo "R$").
    rotulo_valor_escapado = tipo.rotulo_coluna_valor.replace("$", "\\$")
    st.caption(
        f'Edite "{tipo.rotulo_coluna_meses}" (recalcula "{rotulo_valor_escapado}" automaticamente) OU digite '
        f'direto em "{rotulo_valor_escapado}" para um valor personalizado — editar "{tipo.rotulo_coluna_meses}" '
        "de novo sempre sobrescreve o valor digitado direto. Linha com meses ou valor igual a "
        "zero não entra no PDF."
    )

    # `valores` é o estado de verdade (meses/empenhar por linha), independente do que o
    # widget mostra — precisa sobreviver a reruns sem se perder (por isso mora aqui, não é
    # recriado do zero a cada execução do script, só na primeira vez que este processo é
    # aberto). Valor inicial difere por tipo (pedido explícito, ver docstring do módulo):
    # Reforço sugere a partir de `meses_sugeridos`; Anulação começa sempre zerada.
    estado_key = f"reforco_valores_{chave}_{tipo.id}_{processo}"
    if estado_key not in st.session_state:
        if tipo.id == "reforco":
            meses_iniciais = linhas["meses_sugeridos"].round(2)
        else:
            meses_iniciais = pd.Series(0.0, index=linhas.index)
        st.session_state[estado_key] = pd.DataFrame(
            {
                "meses": meses_iniciais,
                "empenhar": (meses_iniciais * linhas["valor_mensal"]).round(2),
            }
        )
    valores = st.session_state[estado_key]

    # `geração` troca a key do editor quando uma edição da coluna de meses pede um recálculo
    # visível na própria grade — sem trocar a key, a célula de valor fica travada no valor com
    # que o widget nasceu, ignorando qualquer novo `tabela_editor` que passarmos depois (o
    # `st.data_editor` só respeita o argumento inicial + o que o próprio usuário editou NAQUELA
    # key; um valor recalculado por nós não é "o que o usuário editou"). O delta é lido da key
    # ATUAL, ANTES de decidir a key desta renderização — é a resposta à interação que o usuário
    # acabou de commitar (Enter/Tab), já disponível nesta mesma execução: não precisa de
    # `st.rerun()` (que, dentro de `@st.dialog`, fecha o pop-up — bug real observado, ver
    # docstring do módulo).
    geracao_key = f"reforco_geracao_{chave}_{tipo.id}_{processo}"
    geracao = st.session_state.setdefault(geracao_key, 0)
    editor_key = f"reforco_editor_{chave}_{tipo.id}_{processo}_{geracao}"

    delta = st.session_state.get(editor_key, {})
    houve_edicao_de_meses = False
    for posicao, mudancas in delta.get("edited_rows", {}).items():
        if tipo.rotulo_coluna_meses in mudancas:
            novo_meses = float(mudancas[tipo.rotulo_coluna_meses])
            valor_mensal_linha = float(linhas.iloc[posicao]["valor_mensal"])
            valores.iat[posicao, valores.columns.get_loc("meses")] = novo_meses
            valores.iat[posicao, valores.columns.get_loc("empenhar")] = round(novo_meses * valor_mensal_linha, 2)
            houve_edicao_de_meses = True
        elif tipo.rotulo_coluna_valor in mudancas:
            valores.iat[posicao, valores.columns.get_loc("empenhar")] = float(mudancas[tipo.rotulo_coluna_valor])

    st.session_state[estado_key] = valores

    if houve_edicao_de_meses:
        geracao += 1
        st.session_state[geracao_key] = geracao
        editor_key = f"reforco_editor_{chave}_{tipo.id}_{processo}_{geracao}"

    tabela_editor = pd.DataFrame(
        {
            "Item de Despesa": linhas["item_despesa"].to_numpy(),
            "Empenho": linhas["ne_curta"].to_numpy(),
            tipo.rotulo_coluna_meses: valores["meses"].to_numpy(),
            tipo.rotulo_coluna_valor: valores["empenhar"].to_numpy(),
        }
    )
    st.data_editor(
        tabela_editor,
        key=editor_key,
        disabled=["Item de Despesa", "Empenho"],
        column_config={
            # `,` (sprintf-js, não C-printf) agrupa milhar — pedido explícito ("pontuação de
            # valores"). Só chega a americano (vírgula milhar, ponto decimal: "1,234.57"), não
            # o pt-BR completo do resto do app (`format_brl_full`, "1.234,57") — `NumberColumn`
            # de coluna EDITÁVEL não aceita formatação livre por HTML, só o subconjunto
            # sprintf-js que o Streamlit expõe (sem locale pt-BR nele). Ainda assim melhor que
            # antes (sem separador nenhum: "94500.00").
            tipo.rotulo_coluna_meses: st.column_config.NumberColumn(step=0.01, min_value=0.0, format="%,.2f"),
            tipo.rotulo_coluna_valor: st.column_config.NumberColumn(step=0.01, min_value=0.0, format="R$ %,.2f"),
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
    st.metric(tipo.rotulo_total, format_brl_full(total))

    linhas_para_pdf = excluir_linhas_zeradas(linhas_finais)

    # dois modelos em uso pela PROPLAD (ver docstring de src/relatorio_reforco_empenho.py) —
    # os dois precisam ser emitidos, não é escolha de um ou outro.
    nome_arquivo = processo.replace("/", "-")
    col_detalhado, col_resumido = st.columns(2)
    with col_detalhado:
        st.download_button(
            "Baixar PDF — Modelo Detalhado",
            data=gerar_pdf_detalhado(spec, tipo, processo, linhas_para_pdf),
            file_name=f"{tipo.prefixo_arquivo}_detalhado_{nome_arquivo}.pdf",
            mime="application/pdf",
            type="primary",
            width="stretch",
            key=f"reforco_download_detalhado_{chave}_{tipo.id}_{processo}",
        )
    with col_resumido:
        st.download_button(
            "Baixar PDF — Modelo Resumido",
            data=gerar_pdf_resumido(spec, tipo, processo, linhas_para_pdf),
            file_name=f"{tipo.prefixo_arquivo}_resumido_{nome_arquivo}.pdf",
            mime="application/pdf",
            width="stretch",
            key=f"reforco_download_resumido_{chave}_{tipo.id}_{processo}",
        )


def _limpar_estado_relatorio(chave: str) -> None:
    """Apaga todo o estado de edição do relatório (tipo escolhido, valores por processo,
    geração da grade do editor e as próprias keys do `st.data_editor`) — pedido explícito: o
    valor editado só vale enquanto o pop-up continua aberto. Ao fechar (X, Esc, clicar fora,
    ou "← Voltar") e reabrir, os valores voltam ao padrão de cada tipo e a tela de escolha
    reaparece — chamada sempre que o botão que abre o pop-up é clicado, já que essa é a única
    forma de "reabrir" (`st.dialog` não tem um gancho de fechamento próprio)."""

    prefixos = (f"reforco_valores_{chave}_", f"reforco_geracao_{chave}_", f"reforco_editor_{chave}_")
    for chave_sessao in list(st.session_state.keys()):
        if any(chave_sessao.startswith(prefixo) for prefixo in prefixos):
            del st.session_state[chave_sessao]
    st.session_state.pop(f"reforco_tipo_{chave}", None)


def render_botao_relatorio(df: pd.DataFrame, spec: EspecificacaoRelatorio, chave: str) -> None:
    """Botão que abre o pop-up de emissão de relatório — chamar de dentro da página, com o
    DataFrame já lido por ela (não relê a planilha) e uma `chave` distinta por página
    (namespace de `st.session_state`, para as páginas conviverem sem colidir chaves de
    widget). Um botão só para os dois relatórios (Reforço/Anulação, pedido explícito) — o
    pop-up pergunta qual emitir antes de mostrar a tabela (ver `_abrir_relatorios`)."""

    if st.button("📄 Relatórios", key=f"reforco_abrir_{chave}"):
        _limpar_estado_relatorio(chave)
        _abrir_relatorios(df, spec, chave)
