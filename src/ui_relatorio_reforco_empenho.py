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
só "Meses"). GRADE FEITA À MÃO (`st.columns` + `st.number_input` por linha, uma linha do
`st.dialog` por vez) — NÃO `st.data_editor` (bug real visto em produção, corrigido: a grade
nativa ficava permanentemente em branco no navegador dentro deste `st.dialog`, sem exceção
nenhuma e com o dado certo confirmado chegando até o front-end — ver `_render_conteudo_relatorio`
para os detalhes). Mesmo padrão já usado em outras telas do projeto (ex. `despesas_pessoal`)
que evitam esse componente nativo por limitação semelhante.

Regra de prioridade entre as duas colunas editáveis (pedido explícito): editar a coluna de
meses SEMPRE recalcula a coluna de valor (= meses × valor mensal da linha), mesmo que a
célula já tivesse um valor digitado à mão antes — a edição de meses vence. Editar o valor
direto fica valendo como está (sem alterar a coluna de meses) até a próxima vez que a coluna
de meses for editada nessa mesma linha. Implementado com `on_change` no `st.number_input` de
meses (`_recalcular_valor_por_meses`) — roda ANTES do script recomeçar do topo, então o campo
de valor já nasce com o número recalculado na mesma execução (sem o atraso de um rerun que um
recálculo feito só depois de desenhar os dois widgets teria).

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

SEM PONTUAÇÃO DE MILHAR nas colunas editáveis (`st.number_input` não formata o valor exibido
com separador nenhum, "94500.00") — só leitura consegue o pt-BR completo de `format_brl_full`
("1.234,57"), usado no `st.metric` de total abaixo da grade. Mesma limitação que o
`st.data_editor` já tinha (nem "1,234.57" americano, nem "1.234,57" pt-BR, dentro da própria
célula editável).

Contrato público:
    render_botao_relatorio(df, spec, chave, ano_referencia) -> None
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

#: proporções das 4 colunas da grade feita à mão (`_render_conteudo_relatorio`) — Item de
#: Despesa ganha o espaço que sobra (nomes de fornecedor/programa variam bastante de tamanho),
#: Empenho (NE) e as duas colunas numéricas ficam mais estreitas.
_PROPORCOES_LINHA = [3.2, 1.6, 1.1, 1.4]


def _recalcular_valor_por_meses(meses_key: str, valor_key: str, valor_mensal: float) -> None:
    """`on_change` do `st.number_input` de meses — recalcula e grava o valor em R$ ANTES do
    campo "Valor" ser desenhado nesta mesma execução (callbacks de `on_change` rodam antes do
    script recomeçar do topo — diferente de detectar a mudança só depois de já ter desenhado
    os dois widgets, o que deixaria "Valor" um rerun atrasado). Editar "Valor" diretamente não
    passa por aqui — fica valendo como foi digitado até a próxima edição de "Meses" nessa
    mesma linha (pedido explícito, mesma regra de prioridade de antes)."""

    st.session_state[valor_key] = round(st.session_state[meses_key] * valor_mensal, 2)


@st.dialog("Relatórios", width="large")
def _abrir_relatorios(
    df: pd.DataFrame, spec: EspecificacaoRelatorio, chave: str, ano_referencia: int
) -> None:
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
        #
        # `st.empty()` (bug real observado em produção, print de tela: com um `st.caption` +
        # `st.button` soltos, direto no corpo da função, os dois botões de escolha continuavam
        # desenhados na tela ACIMA do conteúdo do relatório já escolhido, no MESMO run em que a
        # escolha acontece — Streamlit não tem como "apagar" um elemento já desenhado neste
        # run a não ser through um placeholder). Escrevendo a escolha dentro de
        # `picker_placeholder.container()` e chamando `picker_placeholder.empty()` assim que
        # uma escolha é feita, os dois botões somem do resultado final deste run antes dele
        # terminar — sem isso, o usuário via os dois relatórios "empilhados" e a grade do
        # relatório escolhido parecia vazia/perdida no meio do resto da tela.
        picker_placeholder = st.empty()
        with picker_placeholder.container():
            st.caption("Escolha o relatório que deseja emitir.")
            for tipo in _TIPOS:
                if st.button(f"📄 {tipo.rotulo_escolha}", key=f"reforco_escolher_{chave}_{tipo.id}", width="stretch"):
                    st.session_state[tipo_key] = tipo.id
                    tipo_id = tipo.id
        if tipo_id is None:
            return
        picker_placeholder.empty()

    tipo = TIPO_REFORCO if tipo_id == "reforco" else TIPO_ANULACAO
    st.divider()
    _render_conteudo_relatorio(df, spec, tipo, chave, ano_referencia)


def _render_conteudo_relatorio(
    df: pd.DataFrame, spec: EspecificacaoRelatorio, tipo: TipoRelatorio, chave: str, ano_referencia: int
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

    linhas = linhas_para_processo(df, spec, processo, ano_referencia)
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

    # Grade feita à mão (`st.columns` + `st.number_input` por linha) — NÃO `st.data_editor`
    # (pedido explícito, correção de um bug real visto em produção: o `st.data_editor` dentro
    # deste `st.dialog` ficava permanentemente em branco no navegador real — sem exceção
    # nenhuma, com o dado certo confirmado chegando até o front-end via inspeção direta do
    # Arrow transmitido pelo servidor, mas a grade nunca desenhava as células visualmente;
    # aparenta ser um bug do próprio componente nativo nesta versão do Streamlit dentro de um
    # dialog, não reproduzível a partir do servidor). Mesmo padrão já usado em outras telas do
    # projeto (ex. `despesas_pessoal`) que evitam esse componente por limitação semelhante —
    # "nunca misturar grade HTML com widget nativo tentando ocupar uma célula dela: ou tudo é
    # `st.columns`/widgets nativos, ou tudo é HTML" (mesma lição já documentada ali) — aqui é
    # tudo `st.columns`.
    #
    # Cada célula editável é um widget PRÓPRIO (`st.number_input`, key fixa por linha/coluna —
    # `f"{prefixo_linha}_meses_{i}"`/`f"{prefixo_linha}_valor_{i}"`), não uma grade única — isso
    # elimina de vez o truque de "geração" que o `st.data_editor` exigia: um widget comum já
    # respeita um novo valor colocado em `st.session_state[sua_key]` ANTES dele ser instanciado
    # na mesma execução (diferente do `data_editor`, que ignorava um `tabela_editor` novo
    # enquanto a key não mudasse). "Meses" usa `on_change` (`_recalcular_valor_por_meses`) pra
    # recalcular e já deixar "Valor" com o número certo ANTES dele ser desenhado nesta mesma
    # execução — sem isso, o valor recalculado só apareceria visível um rerun depois.
    prefixo_linha = f"reforco_linha_{chave}_{tipo.id}_{processo}"
    linhas_indexadas = linhas.reset_index(drop=True)

    cabecalho = st.columns(_PROPORCOES_LINHA)
    cabecalho[0].caption("Item de Despesa")
    cabecalho[1].caption("Empenho")
    cabecalho[2].caption(tipo.rotulo_coluna_meses)
    cabecalho[3].caption(tipo.rotulo_coluna_valor)

    meses_finais = []
    valores_finais = []
    for i, linha in enumerate(linhas_indexadas.itertuples()):
        meses_key = f"{prefixo_linha}_meses_{i}"
        valor_key = f"{prefixo_linha}_valor_{i}"
        valor_mensal_linha = float(linha.valor_mensal) if pd.notna(linha.valor_mensal) else 0.0

        # Semente inicial (só na primeira execução deste processo/tipo — depois, o próprio
        # `st.session_state` do widget é quem manda). Difere por tipo (pedido explícito, ver
        # docstring do módulo): Reforço sugere a partir de `meses_sugeridos`; Anulação começa
        # sempre zerada.
        if meses_key not in st.session_state:
            meses_inicial = round(float(linha.meses_sugeridos), 2) if tipo.id == "reforco" else 0.0
            st.session_state[meses_key] = meses_inicial
        if valor_key not in st.session_state:
            st.session_state[valor_key] = round(st.session_state[meses_key] * valor_mensal_linha, 2)

        linha_cols = st.columns(_PROPORCOES_LINHA, vertical_alignment="center")
        linha_cols[0].write(linha.item_despesa)
        linha_cols[1].write(linha.ne_curta)
        linha_cols[2].number_input(
            tipo.rotulo_coluna_meses, key=meses_key, min_value=0.0, step=0.01, format="%.2f",
            label_visibility="collapsed", on_change=_recalcular_valor_por_meses,
            args=(meses_key, valor_key, valor_mensal_linha),
        )
        linha_cols[3].number_input(
            tipo.rotulo_coluna_valor, key=valor_key, min_value=0.0, step=0.01, format="%.2f",
            label_visibility="collapsed",
        )

        meses_finais.append(st.session_state[meses_key])
        valores_finais.append(st.session_state[valor_key])

    linhas_finais = linhas_indexadas.assign(meses=meses_finais, empenhar=valores_finais)

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
    """Apaga todo o estado de edição do relatório (tipo escolhido + as keys de cada
    `st.number_input` de cada linha, uma por célula editável — ver `_render_conteudo_relatorio`)
    — pedido explícito: o valor editado só vale enquanto o pop-up continua aberto. Ao fechar
    (X, Esc, clicar fora, ou "← Voltar") e reabrir, os valores voltam ao padrão de cada tipo e
    a tela de escolha reaparece — chamada sempre que o botão que abre o pop-up é clicado, já
    que essa é a única forma de "reabrir" (`st.dialog` não tem um gancho de fechamento
    próprio)."""

    prefixo = f"reforco_linha_{chave}_"
    for chave_sessao in list(st.session_state.keys()):
        if chave_sessao.startswith(prefixo):
            del st.session_state[chave_sessao]
    st.session_state.pop(f"reforco_tipo_{chave}", None)


def render_botao_relatorio(
    df: pd.DataFrame, spec: EspecificacaoRelatorio, chave: str, ano_referencia: int
) -> None:
    """Botão que abre o pop-up de emissão de relatório — chamar de dentro da página, com o
    DataFrame já lido por ela (não relê a planilha) e uma `chave` distinta por página
    (namespace de `st.session_state`, para as páginas conviverem sem colidir chaves de
    widget). Um botão só para os dois relatórios (Reforço/Anulação, pedido explícito) — o
    pop-up pergunta qual emitir antes de mostrar a tabela (ver `_abrir_relatorios`).

    `ano_referencia` é o exercício do cadastro em tela (`ano_selecionado` na página chamadora)
    — nunca inferido daqui, repassado até `necessidade_ate_mes_vigente` para a sugestão "por
    calendário" não misturar o mês real de hoje com um exercício diferente do que está sendo
    exibido (ex.: cadastro do ano anterior ainda não duplicado para o novo exercício)."""

    if st.button("📄 Relatórios", key=f"reforco_abrir_{chave}"):
        _limpar_estado_relatorio(chave)
        _abrir_relatorios(df, spec, chave, ano_referencia)
