"""TEDs — Importações. Quarta página do grupo "TEDs" (ver `app.py`).

Assistente de 4 passos (Arquivo → Mapeamento → Validação → Confirmação) sobre as funções já
existentes e testadas (`src/teds_importacao_simec.py`, `src/teds_lotes.py`) — nenhuma regra
nova, só uma prévia (dry-run: lê e valida sem gravar) antes da confirmação gravar de verdade.

"Mapeamento" mostra o `_MAPA_*` real de cada leitor (qual coluna da planilha casou com qual
campo esperado) — não é editável nesta versão: os leitores não expõem hoje uma forma de
sobrescrever o mapeamento detectado, isso seria escopo novo.

TESOURO GERENCIAL NÃO TEM UPLOAD AQUI (decisão de 22/09/2026, ver `docs/base_teds.md` seção 6): a
base do Tesouro Gerencial É a Execução Mensal já importada em "Atualizar Planilhas" — a seção
"Tesouro Gerencial — Execução Mensal" abaixo só a sincroniza para `execucao_tg` (botão
explícito, lote auditável em `import_batch`, idempotente pelo sha256 da extração).

"Rejeitados" no card de estatísticas do topo é sempre 0 fora do fluxo de importação corrente:
o banco não guarda historicamente quantas linhas foram rejeitadas em cada lote (só
`quantidade_registros`, as aceitas) — não é um dado fictício, é um dado que este schema não
persiste; a contagem real de rejeitadas só existe durante a própria validação/confirmação.
"""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from src import design_tokens
from src.teds_importacao_simec import (
    _MAPA_DOC_NC,
    _MAPA_DOC_NE,
    _MAPA_DOC_PF,
    _MAPA_EXECUCAO_ANUAL,
    ler_doc_ne_simec,
    ler_doc_nc_simec,
    ler_doc_pf_simec,
    ler_execucao_anual_simec,
)
from src.teds_alertas import TOLERANCIA_CONCILIACAO
from src.teds_celula_orcamentaria import (
    _MAPA_NC_TG_2026,
    _MAPA_NC_TG_HISTORICA,
    TIPO_NC_TG_2026,
    TIPO_NC_TG_HISTORICA,
    ler_nc_tg_2026,
    ler_nc_tg_historica,
)
from src.teds_lotes import (
    ExecucaoMensalNaoImportada,
    comparar_rodape,
    importar_doc_ne,
    importar_doc_nc,
    importar_doc_pf,
    importar_execucao_anual,
    importar_nc_tg_2026,
    importar_nc_tg_historica,
    reavaliar_alertas,
    sincronizar_execucao_tg_atual,
    status_sincronizacao_execucao_tg,
)
from src.teds_normalizacao import ColunaObrigatoriaAusente, mapear_colunas
from src.teds_reversao import ReversaoNaoPermitida, lotes_reversiveis, reverter_lote
from src.teds_ui import brl, conexao, formatar_historico_lotes, historico_importacoes, injetar_css, render_kpi_strip, rotulo_tipo_alerta
from src.ui_theme import render_page_header

injetar_css()
render_page_header("Importações", "Importe e processe arquivos de dados para atualização dos TEDs.", "TEDs")

conn = conexao()

_ROTULO_LOTE = {
    "simec_execucao_anual": "SIMEC — Execução", "simec_doc_nc": "SIMEC — DOC NC",
    "simec_doc_ne": "SIMEC — DOC NE", "simec_doc_pf": "SIMEC — DOC PF",
    "tesouro_gerencial_execucao": "Tesouro Gerencial — Execução",
    TIPO_NC_TG_HISTORICA: "Tesouro Gerencial — NC (Destaques)", TIPO_NC_TG_2026: "Tesouro Gerencial — NC 2026",
}

_TIPOS = {
    "SIMEC — Execução: Orçamentário e Financeiro": ("simec_execucao_anual", _MAPA_EXECUCAO_ANUAL, ler_execucao_anual_simec, importar_execucao_anual),
    "SIMEC — DOC NC": ("simec_doc_nc", _MAPA_DOC_NC, ler_doc_nc_simec, importar_doc_nc),
    "SIMEC — DOC NE": ("simec_doc_ne", _MAPA_DOC_NE, ler_doc_ne_simec, importar_doc_ne),
    "SIMEC — DOC PF": ("simec_doc_pf", _MAPA_DOC_PF, ler_doc_pf_simec, importar_doc_pf),
    "Tesouro Gerencial — NC até 2025 (Destaques Recebidos)": (
        TIPO_NC_TG_HISTORICA, _MAPA_NC_TG_HISTORICA, ler_nc_tg_historica, importar_nc_tg_historica
    ),
    "Tesouro Gerencial — NC 2026": (TIPO_NC_TG_2026, _MAPA_NC_TG_2026, ler_nc_tg_2026, importar_nc_tg_2026),
}

historico = historico_importacoes(conn)
# Lotes revertidos continuam no histórico, mas não contam como "importados" nem como aceitos.
ativos = historico[historico["status"] == "ok"]
ultima = ativos["data_importacao"].max() if not ativos.empty else None
total_aceitos = int(ativos["quantidade_registros"].sum()) if not ativos.empty else 0

render_kpi_strip([
    {"label": "Última atualização", "value": pd.Timestamp(ultima).strftime("%d/%m/%Y %H:%M") if ultima else "—", "icon": "□", "tone": design_tokens.ACCENT},
    {"label": "Arquivos importados", "value": len(ativos), "icon": "▤", "tone": design_tokens.POSITIVE},
    {"label": "Registros aceitos", "value": total_aceitos, "icon": "✓", "tone": design_tokens.ACCENT},
    {"label": "Com avisos", "value": st.session_state.get("imp_ultimo_avisos", "—"), "icon": "!", "tone": design_tokens.WARNING},
    {"label": "Rejeitados", "value": st.session_state.get("imp_ultimo_rejeitados", 0), "icon": "×", "tone": design_tokens.NEGATIVE},
])

st.markdown("#### Tesouro Gerencial — Execução Mensal")
manifesto_tg, lote_tg = status_sincronizacao_execucao_tg(conn)
if manifesto_tg is None:
    st.info(
        "Nenhuma extração da Execução Mensal importada ainda — importe em **Atualizar Planilhas** "
        "para poder sincronizá-la aqui."
    )
else:
    st.caption(
        f"Extração atual: `{manifesto_tg.arquivo}` · data da extração: "
        f"{pd.Timestamp(manifesto_tg.data_extracao).strftime('%d/%m/%Y')} · exercícios "
        f"{', '.join(map(str, manifesto_tg.anos))}"
    )
    if lote_tg is not None:
        st.success(f"Esta extração já está sincronizada (lote #{lote_tg}) — nada a fazer.")
    else:
        st.warning("Esta extração ainda não foi sincronizada com o módulo de TEDs.")
    if st.button("Sincronizar com a Execução Mensal", type="primary", disabled=lote_tg is not None):
        try:
            with st.spinner("Lendo a Execução Mensal e gravando em execucao_tg…"):
                resultado_tg = sincronizar_execucao_tg_atual(conn)
        except ExecucaoMensalNaoImportada as erro:
            st.error(str(erro))
        except Exception as erro:
            st.error(f"Falha ao sincronizar: {erro}")
        else:
            st.session_state["imp_ultimo_rejeitados"] = len(resultado_tg.rejeitadas)
            st.success(
                f"Sincronização concluída — {resultado_tg.inseridos} linha(s) NE × mês gravada(s), "
                f"{len(resultado_tg.rejeitadas)} rejeitada(s)."
            )
            for rejeitada in resultado_tg.rejeitadas[:10]:
                st.caption(f"Rejeitada: {rejeitada.motivo}")

st.markdown("#### Alertas")
st.caption(
    "Cada importação só gera os alertas que existiam quando ela rodou. Reavaliar aplica todas as verificações aos "
    "dados já importados, sem reimportar nada: só cria alertas que faltam — não fecha nem altera os existentes "
    "nem os dados importados."
)
if st.button("Reavaliar alertas", key="imp_reavaliar_alertas"):
    try:
        with st.spinner("Reavaliando alertas sobre os dados importados…"):
            resultado_alertas = reavaliar_alertas(conn)
    except Exception as erro:
        st.error(f"Falha ao reavaliar alertas: {erro}")
    else:
        if resultado_alertas.total == 0 and resultado_alertas.total_fechados == 0:
            st.success("Reavaliação concluída — nenhum alerta novo; os existentes continuam como estão.")
        else:
            st.success(
                f"Reavaliação concluída — {resultado_alertas.total} alerta(s) novo(s) criado(s) e "
                f"{resultado_alertas.total_fechados} obsoleto(s) fechado(s)."
            )
            for tipo, quantidade in resultado_alertas.criados_por_tipo.items():
                st.caption(f"{rotulo_tipo_alerta(tipo)}: {quantidade} criado(s)")
            for tipo, quantidade in resultado_alertas.fechados_por_tipo.items():
                st.caption(f"{rotulo_tipo_alerta(tipo)}: {quantidade} fechado(s) pela regra revista")

st.session_state.setdefault("imp_step", 1)

col_wizard, col_preview = st.columns([1.1, 1.4])

with col_wizard:
    st.markdown("#### Nova importação")
    passos = ["Arquivo", "Mapeamento", "Validação", "Confirmação"]
    st.caption(" → ".join(f"**{i}. {p}**" if i == st.session_state["imp_step"] else f"{i}. {p}" for i, p in enumerate(passos, start=1)))

    if st.session_state["imp_step"] == 1:
        tipo_rotulo = st.selectbox("Tipo de arquivo", list(_TIPOS.keys()), key="imp_tipo_rotulo")
        arquivo = st.file_uploader("Planilha (.xlsx)", type=["xlsx"], key="imp_arquivo_upload")
        if arquivo is not None and st.button("Avançar para mapeamento", type="primary"):
            st.session_state["imp_conteudo"] = arquivo.getvalue()
            st.session_state["imp_nome_arquivo"] = arquivo.name
            st.session_state["imp_tipo_rotulo_confirmado"] = tipo_rotulo
            st.session_state["imp_step"] = 2
            st.rerun()

    elif st.session_state["imp_step"] == 2:
        tipo_rotulo = st.session_state["imp_tipo_rotulo_confirmado"]
        _, mapa_esperado, leitor, _ = _TIPOS[tipo_rotulo]
        try:
            df = pd.read_excel(io.BytesIO(st.session_state["imp_conteudo"]))
        except Exception as erro:
            st.error(f"Não foi possível ler a planilha: {erro}")
            df = None
        if df is not None:
            st.session_state["imp_df"] = df
            colunas_encontradas = mapear_colunas(df.columns, mapa_esperado)
            linhas_mapa = [
                {"Campo esperado": campo, "Coluna encontrada na planilha": colunas_encontradas.get(campo, "— não encontrada —")}
                for campo in mapa_esperado
            ]
            st.dataframe(pd.DataFrame(linhas_mapa), hide_index=True, width="stretch")
            faltando = [m["Campo esperado"] for m in linhas_mapa if m["Coluna encontrada na planilha"].startswith("—")]

            # Regra 6.1 do briefing: coluna OBRIGATÓRIA ausente rejeita o arquivo inteiro — não
            # basta um aviso ignorável. O leitor de cada relatório já sabe quais dos campos de
            # `mapa_esperado` são obrigatórios (`_CAMPOS_OBRIGATORIOS_*`); reaproveita essa
            # validação aqui (dry-run, sem persistir nada) em vez de duplicar a lista de campos
            # obrigatórios nesta página.
            bloqueado = False
            if faltando:
                try:
                    leitor(df)
                except ColunaObrigatoriaAusente as exc:
                    st.error(str(exc))
                    bloqueado = True
                else:
                    st.warning(
                        f"Campos não encontrados no cabeçalho: {', '.join(faltando)} — opcionais "
                        "para este relatório, a importação pode continuar."
                    )

            col_voltar, col_avancar = st.columns(2)
            if col_voltar.button("Voltar"):
                st.session_state["imp_step"] = 1
                st.rerun()
            if col_avancar.button("Avançar para validação", type="primary", disabled=bloqueado):
                st.session_state["imp_step"] = 3
                st.rerun()

    elif st.session_state["imp_step"] == 3:
        tipo_rotulo = st.session_state["imp_tipo_rotulo_confirmado"]
        chave_tipo, _, leitor, _ = _TIPOS[tipo_rotulo]
        df = st.session_state["imp_df"]
        try:
            leitura = leitor(df)
        except Exception as erro:
            st.error(f"Falha ao validar a planilha: {erro}")
            leitura = None
        if leitura is not None:
            avisos_total = sum(len(r.get("avisos") or []) for r in leitura.registros)
            st.session_state["imp_ultimo_avisos"] = avisos_total
            st.session_state["imp_ultimo_rejeitados"] = len(leitura.rejeitadas)
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Linhas lidas", str(len(df)))
            c2.metric("Válidas", str(len(leitura.registros)))
            c3.metric("Aceitas com aviso", str(sum(1 for r in leitura.registros if r.get("avisos"))))
            c4.metric("Rejeitadas", str(len(leitura.rejeitadas)))
            c5.metric("Rodapé ignorado", str(sum(1 for x in leitura.rejeitadas if "rodapé" in x.motivo)))
            if avisos_total:
                st.warning(f"{avisos_total} linha(s) com aviso — serão importadas com relacionamento parcial.")
            # Regra 6.2 do briefing: o total impresso no rodapé do SIMEC deve bater com a soma das
            # linhas. Só informa — quem decide importar é a pessoa; a divergência vira alerta crítico.
            comparacoes = comparar_rodape(chave_tipo, leitura)
            if comparacoes is None:
                st.caption("O arquivo não traz linha de rodapé com total — não há o que conferir.")
            else:
                divergentes = [c for c in comparacoes if abs(c.diferenca) > TOLERANCIA_CONCILIACAO]
                if divergentes:
                    st.error(
                        "O total do rodapé **não** confere com a soma das linhas lidas: "
                        + "; ".join(f"{c.campo}: rodapé {brl(c.rodape)} × calculado {brl(c.calculado)}" for c in divergentes)
                        + ". A importação ainda pode ser feita e gerará um alerta crítico."
                    )
                else:
                    st.success(f"Total do rodapé confere com a soma das linhas ({len(comparacoes)} campo(s)).")
            st.session_state["imp_leitura_ok"] = True
            col_voltar, col_avancar = st.columns(2)
            if col_voltar.button("Voltar", key="v3"):
                st.session_state["imp_step"] = 2
                st.rerun()
            if col_avancar.button("Confirmar importação", type="primary"):
                st.session_state["imp_step"] = 4
                st.rerun()

    elif st.session_state["imp_step"] == 4:
        tipo_rotulo = st.session_state["imp_tipo_rotulo_confirmado"]
        chave_tipo, _, _, importador = _TIPOS[tipo_rotulo]
        df = st.session_state["imp_df"]
        conteudo = st.session_state["imp_conteudo"]
        nome_arquivo = st.session_state["imp_nome_arquivo"]
        try:
            resultado = importador(conn, df, nome_arquivo, conteudo)
        except Exception as erro:
            st.error(f"Falha ao importar: {erro}")
        else:
            if resultado.ja_importado:
                st.info("Este arquivo já tinha sido importado — nada mudou.")
            else:
                st.success(f"Importação concluída — {resultado.inseridos} linha(s) gravada(s), {len(resultado.rejeitadas)} rejeitada(s).")

            # Total de controle do lote (regra 6.2 do briefing) — mesmo depois de "já
            # importado", já que o lote antigo continua consultável por `import_batch_id`.
            lote = conn.execute(
                "SELECT quantidade_linhas_lidas, quantidade_rejeitadas, quantidade_com_aviso, "
                "soma_bruta, soma_positiva, soma_negativa, soma_liquida FROM import_batch WHERE id = ?",
                (resultado.import_batch_id,),
            ).fetchone()
            if lote is not None:
                lidas, rejeitadas_lote, com_aviso, bruta, positiva, negativa, liquida = lote
                st.markdown("###### Total de controle do lote")
                c1, c2, c3 = st.columns(3)
                c1.metric("Linhas lidas", lidas if lidas is not None else "—")
                c2.metric("Rejeitadas", rejeitadas_lote if rejeitadas_lote is not None else "—")
                c3.metric("Com aviso", com_aviso if com_aviso is not None else "—")
                if bruta is not None:
                    c4, c5, c6 = st.columns(3)
                    c4.metric("Soma bruta", brl(bruta))
                    c5.metric("Soma líquida (positiva − negativa)", brl(liquida))
                    c6.metric("Soma negativa", brl(negativa))
                else:
                    st.caption(
                        "Este relatório não sustenta uma soma bruta/positiva/negativa/líquida "
                        "única por linha (várias colunas de valor por registro)."
                    )

            rodape_lote = conn.execute(
                "SELECT total_rodape, diferenca_rodape FROM import_batch WHERE id = ?", (resultado.import_batch_id,)
            ).fetchone()
            if rodape_lote is not None and rodape_lote[1] is not None:
                total_rodape, diferenca_rodape = rodape_lote
                st.caption(
                    "Rodapé do relatório: "
                    + (f"total {brl(total_rodape)} · " if total_rodape is not None else "")
                    + f"maior diferença contra a soma das linhas: {brl(diferenca_rodape)}."
                )

            if st.button("Nova importação"):
                for chave in ("imp_conteudo", "imp_nome_arquivo", "imp_tipo_rotulo_confirmado", "imp_df", "imp_leitura_ok"):
                    st.session_state.pop(chave, None)
                st.session_state["imp_step"] = 1
                st.rerun()

with col_preview:
    st.markdown("#### Prévia dos registros")
    df_preview = st.session_state.get("imp_df")
    if df_preview is None:
        st.caption("Envie um arquivo para ver a prévia.")
    else:
        st.caption(f"Exibição das primeiras linhas do arquivo para conferência. Total de linhas: {len(df_preview)}")
        st.dataframe(df_preview.head(15), hide_index=True, width="stretch")

st.markdown("#### Histórico de importações")
if historico.empty:
    st.caption("Nenhuma importação registrada ainda.")
else:
    st.dataframe(formatar_historico_lotes(historico), hide_index=True, width="stretch")

st.markdown("#### Reverter lote")
mensagem_reversao = st.session_state.pop("imp_rev_msg", None)
if mensagem_reversao:
    st.success(mensagem_reversao)
st.caption(
    "Desfaz uma importação inteira: as linhas que o lote criou saem dos totais e as que ele "
    "sobrescreveu voltam ao valor anterior. Nada é apagado — as linhas retiradas ficam guardadas e a "
    "ação entra na trilha de auditoria. Alertas já criados não são fechados automaticamente."
)
reversiveis = lotes_reversiveis(conn)
if not reversiveis:
    st.info(
        "Nenhum lote pode ser revertido. Só lotes importados depois do histórico de versões podem ser "
        "revertidos com segurança; lotes anteriores e lotes já revertidos não aparecem aqui."
    )
else:
    opcoes = {
        f"#{id_lote} — {_ROTULO_LOTE.get(tipo, tipo)} — {arquivo} — "
        f"{pd.Timestamp(data).strftime('%d/%m/%Y %H:%M')} — {registros} registro(s)": id_lote
        for id_lote, tipo, arquivo, data, registros in reversiveis
    }
    with st.form("imp_reverter_lote", border=False):
        rotulo_lote = st.selectbox("Lote", list(opcoes), key="imp_rev_lote")
        responsavel_rev = st.text_input("Responsável pela reversão", key="imp_rev_resp")
        motivo_rev = st.text_area("Motivo da reversão", key="imp_rev_motivo", placeholder="Por que este lote deve ser desfeito?")
        confirmou = st.checkbox("Entendo que o lote sairá dos totais e que os alertas dele continuam abertos.", key="imp_rev_confirma")
        enviar = st.form_submit_button("Reverter lote", type="primary", disabled=False)
    if enviar:
        if not confirmou:
            st.error("Marque a confirmação antes de reverter.")
        else:
            try:
                resultado_rev = reverter_lote(
                    conn, opcoes[rotulo_lote], responsavel=responsavel_rev, motivo=motivo_rev,
                    origem="tela:importacoes",
                )
            except ReversaoNaoPermitida as erro:
                st.error(str(erro))
            else:
                st.session_state["imp_rev_msg"] = (
                    f"Lote #{resultado_rev.import_batch_id} revertido — {resultado_rev.total_removidas} linha(s) "
                    f"retirada(s) dos totais e {resultado_rev.total_restauradas} restaurada(s) ao valor anterior."
                )
                st.rerun()
