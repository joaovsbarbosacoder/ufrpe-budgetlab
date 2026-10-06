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
edição separadas): Item de Despesa / Empenho / Valor Mensal / Saldo (só leitura, as duas
últimas evidenciando o valor mensal da despesa e o saldo do empenho — pedido explícito,
válido para Reforço e Anulação) e Meses a Empenhar|Anular / Rótulo de valor (R$) (as duas
editáveis, pedido explícito — as duas são campos personalizáveis, não só "Meses"). GRADE FEITA
À MÃO (`st.columns` + `st.text_input` mascarado por linha, ver mais abaixo — uma linha do
`st.dialog` por vez) — NÃO `st.data_editor` (bug real visto em produção, corrigido: a grade
nativa ficava permanentemente em branco no navegador dentro deste `st.dialog`, sem exceção
nenhuma e com o dado certo confirmado chegando até o front-end — ver `_render_conteudo_relatorio`
para os detalhes). Mesmo padrão já usado em outras telas do projeto (ex. `despesas_pessoal`)
que evitam esse componente nativo por limitação semelhante.

Regra de prioridade entre as duas colunas editáveis (pedido explícito): editar a coluna de
meses SEMPRE recalcula a coluna de valor (= meses × valor mensal da linha), mesmo que a
célula já tivesse um valor digitado à mão antes — a edição de meses vence. Editar o valor
direto fica valendo como está (sem alterar a coluna de meses) até a próxima vez que a coluna
de meses for editada nessa mesma linha. Implementado com `on_change` no `st.text_input` de
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

PONTUAÇÃO PT-BR NAS DUAS COLUNAS EDITÁVEIS (pedido explícito, corrige limitação documentada
antes aqui): `st.number_input` não formata com separador de milhar de jeito nenhum (nem
"1,234.57" americano, nem "1.234,57" pt-BR — mesma limitação que o `st.data_editor` já tinha).
Por isso "Meses a Empenhar/Anular" e "Empenhar/Anular (R$)" viraram `st.text_input` com máscara
manual: a própria key do widget guarda o TEXTO já formatado ("1.234,57"), não o float — reformata
no `on_change` (`_recalcular_valor_por_meses`/`_reformatar_valor`), e o valor numérico só é
extraído de volta (`_parse_valor_brl`) na hora de usar (recálculo, soma do total, `linhas_finais`
pro PDF). Perde os botões de incremento (+/-) do `number_input`, aceito como troca pela
pontuação correta. `_parse_valor_brl` tolera tanto "94.500,00" (pt-BR) quanto "94500,00"/"94500"
quanto "94500.00" (americano, sem vírgula nenhuma) — sem vírgula, o ponto NUNCA é tratado como
milhar sozinho (evita multiplicar por 1000 sem querer); "94.500" digitado à mão SEM vírgula
(pt-BR "noventa e quatro mil" sem centavos) é a única ambiguidade genuína que sobra — vira 94,5,
não 94500 — mas ela nunca sobrevive a um primeiro `on_change` (a formatação de volta sempre
inclui vírgula), então só existe no instante entre digitar e sair do campo.

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

#: proporções das 6 colunas da grade feita à mão (`_render_conteudo_relatorio`) — Item de
#: Despesa ganha o espaço que sobra (nomes de fornecedor/programa variam bastante de tamanho);
#: Empenho (NE) e as quatro colunas numéricas ficam mais estreitas. Valor Mensal/Saldo (pedido
#: explícito: "evidenciar também" — só leitura, para quem emite decidir quanto reforçar/anular
#: com o dado à vista) ficam ANTES das duas editáveis (Meses/Valor), mesma ordem de leitura de
#: "quanto a bolsa/contrato custa por mês e quanto ainda tem de saldo" → "quanto empenhar/anular
#: agora".
_PROPORCOES_LINHA = [2.6, 1.2, 1.15, 1.15, 1.0, 1.3]


def _formatar_valor_brl(valor: float) -> str:
    """Pontuação pt-BR (milhar com ponto, decimal com vírgula) — mesmo formato de
    `src.relatorio_reforco_empenho._formatar_valor`, aplicado aqui às duas colunas editáveis
    (ver docstring do módulo). O texto formatado é o que fica guardado na própria key do
    widget — `_parse_valor_brl`, abaixo, é o inverso."""

    return f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _parse_valor_brl(texto: str) -> float:
    """Inverso de `_formatar_valor_brl` — ver docstring do módulo pra a ambiguidade genuína que
    sobra (milhar pt-BR sem vírgula). Texto vazio ou não numérico vira 0.0 (mesmo critério de
    zero explícito do resto do módulo — campo sem preenchimento não é "sem dado", é "nada a
    lançar aqui"). Nunca negativo (mesmo limite que o `min_value=0.0` do `number_input` aplicava
    antes)."""

    texto = (texto or "").strip()
    if not texto:
        return 0.0
    limpo = texto.replace(".", "").replace(",", ".") if "," in texto else texto
    try:
        valor = float(limpo)
    except ValueError:
        return 0.0
    return valor if valor > 0.0 else 0.0


def _recalcular_valor_por_meses(meses_key: str, valor_key: str, valor_mensal: float) -> None:
    """`on_change` do campo de meses — recalcula e grava o valor em R$ ANTES do campo "Valor"
    ser desenhado nesta mesma execução (callbacks de `on_change` rodam antes do script
    recomeçar do topo — diferente de detectar a mudança só depois de já ter desenhado os dois
    widgets, o que deixaria "Valor" um rerun atrasado). Também reformata o próprio campo de
    meses (pontuação pt-BR, ver docstring do módulo). Editar "Valor" diretamente não passa por
    aqui — fica valendo como foi digitado até a próxima edição de "Meses" nessa mesma linha
    (pedido explícito, mesma regra de prioridade de antes)."""

    meses = _parse_valor_brl(st.session_state[meses_key])
    st.session_state[meses_key] = _formatar_valor_brl(meses)
    st.session_state[valor_key] = _formatar_valor_brl(round(meses * valor_mensal, 2))


def _reformatar_valor(valor_key: str) -> None:
    """`on_change` do campo "Valor" quando editado direto — só reaplica a pontuação pt-BR no
    que foi digitado (`_parse_valor_brl` → `_formatar_valor_brl`), nunca mexe em "Meses" (mesma
    regra de prioridade: editar valor direto não recalcula meses)."""

    st.session_state[valor_key] = _formatar_valor_brl(_parse_valor_brl(st.session_state[valor_key]))


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

    # Grade feita à mão (`st.columns` + `st.text_input` por linha, ver docstring do módulo pra
    # o porquê de `text_input` e não `number_input`) — NÃO `st.data_editor` (pedido explícito,
    # correção de um bug real visto em produção: o `st.data_editor` dentro deste `st.dialog`
    # ficava permanentemente em branco no navegador real — sem exceção nenhuma, com o dado certo
    # confirmado chegando até o front-end via inspeção direta do Arrow transmitido pelo servidor,
    # mas a grade nunca desenhava as células visualmente; aparenta ser um bug do próprio
    # componente nativo nesta versão do Streamlit dentro de um dialog, não reproduzível a partir
    # do servidor). Mesmo padrão já usado em outras telas do projeto (ex. `despesas_pessoal`) que
    # evitam esse componente por limitação semelhante — "nunca misturar grade HTML com widget
    # nativo tentando ocupar uma célula dela: ou tudo é `st.columns`/widgets nativos, ou tudo é
    # HTML" (mesma lição já documentada ali) — aqui é tudo `st.columns`.
    #
    # Cada célula editável é um widget PRÓPRIO (`st.text_input`, key fixa por linha/coluna —
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
    cabecalho[2].caption("Valor Mensal")
    cabecalho[3].caption("Saldo")
    cabecalho[4].caption(tipo.rotulo_coluna_meses)
    cabecalho[5].caption(tipo.rotulo_coluna_valor)

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
            st.session_state[meses_key] = _formatar_valor_brl(meses_inicial)
        if valor_key not in st.session_state:
            valor_inicial = _parse_valor_brl(st.session_state[meses_key]) * valor_mensal_linha
            st.session_state[valor_key] = _formatar_valor_brl(round(valor_inicial, 2))

        linha_cols = st.columns(_PROPORCOES_LINHA, vertical_alignment="center")
        linha_cols[0].write(linha.item_despesa)
        situacao_vigencia = getattr(linha, "situacao_vigencia", None)
        if situacao_vigencia is not None and pd.notna(situacao_vigencia):
            # status/vigência que limitou a sugestão inicial (Contratos Contínuos, 02/10/2026)
            linha_cols[0].caption(f"{situacao_vigencia} — sugestão ajustada por status, vigência ou início da execução")
        linha_cols[1].write(linha.ne_curta)
        # só leitura (pedido explícito: "evidenciar também" o valor mensal da despesa e o saldo
        # do empenho) — `format_brl_full` já distingue nulo de zero ("Valor nulo" vs "R$ 0,00",
        # mesma regra permanente do projeto), diferente de zero silencioso.
        linha_cols[2].write(format_brl_full(linha.valor_mensal))
        linha_cols[3].write(format_brl_full(getattr(linha, "saldo", None)))
        linha_cols[4].text_input(
            tipo.rotulo_coluna_meses, key=meses_key,
            label_visibility="collapsed", on_change=_recalcular_valor_por_meses,
            args=(meses_key, valor_key, valor_mensal_linha),
        )
        linha_cols[5].text_input(
            tipo.rotulo_coluna_valor, key=valor_key,
            label_visibility="collapsed", on_change=_reformatar_valor, args=(valor_key,),
        )

        meses_finais.append(_parse_valor_brl(st.session_state[meses_key]))
        valores_finais.append(_parse_valor_brl(st.session_state[valor_key]))

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
    `st.text_input` de cada linha, uma por célula editável — ver `_render_conteudo_relatorio`)
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
