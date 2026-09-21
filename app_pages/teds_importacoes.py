"""TEDs — Importações. Quarta página do grupo "TEDs" (ver `app.py`).

Assistente de 4 passos (Arquivo → Mapeamento → Validação → Confirmação) sobre as funções já
existentes e testadas (`src/teds_importacao_simec.py`, `src/teds_lotes.py`) — nenhuma regra
nova, só uma prévia (dry-run: lê e valida sem gravar) antes da confirmação gravar de verdade.

"Mapeamento" mostra o `_MAPA_*` real de cada leitor (qual coluna da planilha casou com qual
campo esperado) — não é editável nesta versão: os leitores não expõem hoje uma forma de
sobrescrever o mapeamento detectado, isso seria escopo novo.

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
from src.teds_lotes import importar_doc_ne, importar_doc_nc, importar_doc_pf, importar_execucao_anual
from src.teds_normalizacao import ColunaObrigatoriaAusente, mapear_colunas
from src.teds_ui import brl, conexao, formatar_historico_lotes, historico_importacoes, injetar_css, render_kpi_strip
from src.ui_theme import render_page_header

injetar_css()
render_page_header("Importações", "Importe e processe arquivos de dados para atualização dos TEDs.", "TEDs")

conn = conexao()

_TIPOS = {
    "SIMEC — Execução: Orçamentário e Financeiro": ("simec_execucao_anual", _MAPA_EXECUCAO_ANUAL, ler_execucao_anual_simec, importar_execucao_anual),
    "SIMEC — DOC NC": ("simec_doc_nc", _MAPA_DOC_NC, ler_doc_nc_simec, importar_doc_nc),
    "SIMEC — DOC NE": ("simec_doc_ne", _MAPA_DOC_NE, ler_doc_ne_simec, importar_doc_ne),
    "SIMEC — DOC PF": ("simec_doc_pf", _MAPA_DOC_PF, ler_doc_pf_simec, importar_doc_pf),
}

historico = historico_importacoes(conn)
ultima = historico["data_importacao"].max() if not historico.empty else None
total_aceitos = int(historico["quantidade_registros"].sum()) if not historico.empty else 0

render_kpi_strip([
    {"label": "Última atualização", "value": pd.Timestamp(ultima).strftime("%d/%m/%Y %H:%M") if ultima else "—", "icon": "□", "tone": design_tokens.ACCENT},
    {"label": "Arquivos importados", "value": len(historico), "icon": "▤", "tone": design_tokens.POSITIVE},
    {"label": "Registros aceitos", "value": total_aceitos, "icon": "✓", "tone": design_tokens.ACCENT},
    {"label": "Com avisos", "value": st.session_state.get("imp_ultimo_avisos", "—"), "icon": "!", "tone": design_tokens.WARNING},
    {"label": "Rejeitados", "value": st.session_state.get("imp_ultimo_rejeitados", 0), "icon": "×", "tone": design_tokens.NEGATIVE},
])

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
        _, _, leitor, _ = _TIPOS[tipo_rotulo]
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
