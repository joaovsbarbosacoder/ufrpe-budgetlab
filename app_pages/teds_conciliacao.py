"""TEDs — Conciliação. Quinta página do grupo "TEDs" (ver `app.py`).

Compara, por TED, o valor/quantidade de NEs registrados no SIMEC (`vinculo_ne`, real) contra o
Tesouro Gerencial (`execucao_tg`, cruzado por `numero_completo_ne` — ver docstring de
`src/teds_importacao_tesouro_gerencial.py`). A comparação em si é real; o que normalmente
aparece é "Fonte ausente", porque o leitor do Tesouro Gerencial ainda não foi confirmado
contra uma extração real (não é fictício — é a extração que ainda não existe).

A situação "Conferência necessária" tanto pode vir de uma divergência de valor acima da
tolerância quanto do alerta já existente de NE-em-múltiplos-TEDs (`src/teds_alertas.py`) — as
duas fontes de divergência aparecem juntas nesta tela, sem inventar uma terceira regra.

Tolerância monetária é lida de `st.session_state["teds_tolerancia_monetaria"]` — configurável
na página Configurações; sem ela definida ainda nesta sessão, usa R$ 0,01 (mesmo valor do
mockup).
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from src.teds_normalizacao import texto_para_valor
from src.teds_ui import anos_disponiveis, badge, brl, carregar_teds, conexao, cor_situacao_conciliacao, filtrar_por_exercicio, injetar_css
from src.ui_theme import render_page_header

injetar_css()
render_page_header("Conciliação", "Compare informações entre as fontes e identifique divergências nos TEDs.", "TEDs")

conn = conexao()
teds_df = carregar_teds(conn)
if teds_df.empty:
    st.info('Nenhum TED importado ainda. Vá em "Importações".')
    st.stop()

tolerancia = st.session_state.get("teds_tolerancia_monetaria", Decimal("0.01"))

col_exercicio, col_ted, col_tipo, col_situacao = st.columns(4)
anos = anos_disponiveis(teds_df)
with col_exercicio:
    exercicio = st.selectbox("Exercício", ["Todos"] + [str(a) for a in anos], key="cc_exercicio")
with col_ted:
    ted_sel = st.selectbox("TED", ["Todos"] + sorted(teds_df["ted"].tolist()), key="cc_ted")
with col_tipo:
    tipo_sel = st.selectbox("Tipo de divergência", ["Todos", "Valor das NEs", "Quantidade de NEs"], key="cc_tipo")
with col_situacao:
    situacao_sel = st.selectbox("Situação", ["Todas", "Conciliado", "Conferência necessária", "Fonte ausente"], key="cc_situacao")

filtrado = teds_df
if exercicio != "Todos":
    filtrado = filtrar_por_exercicio(filtrado, int(exercicio))
if ted_sel != "Todos":
    filtrado = filtrado[filtrado["ted"] == ted_sel]


def _linhas_ne(chave_ted: str) -> list[tuple]:
    return conn.execute(
        "SELECT numero_ne, valor_ne, status_validacao FROM vinculo_ne WHERE chave_ted = ?", (chave_ted,)
    ).fetchall()


def _tg_por_numeros(numeros_ne: set[str]) -> list[tuple]:
    if not numeros_ne:
        return []
    marcadores = ",".join("?" * len(numeros_ne))
    return conn.execute(
        f"SELECT numero_completo_ne, empenhado FROM execucao_tg WHERE numero_completo_ne IN ({marcadores})",
        list(numeros_ne),
    ).fetchall()


linhas_comparacao = []
for _, ted_row in filtrado.iterrows():
    chave_ted = ted_row["chave_ted"]
    ne_linhas = _linhas_ne(chave_ted)
    numeros_ne = {n for n, _, _ in ne_linhas}
    tg_linhas = _tg_por_numeros(numeros_ne)
    tem_pendencia = any(status == "pendente" for _, _, status in ne_linhas)

    valor_simec = sum((texto_para_valor(v) for _, v, _ in ne_linhas), start=Decimal("0"))
    qtd_simec = len(ne_linhas)
    if tg_linhas:
        valor_tg = sum((texto_para_valor(v) for _, v in tg_linhas if v is not None), start=Decimal("0"))
        qtd_tg = len({n for n, _ in tg_linhas})
        fonte_ausente = False
    else:
        valor_tg, qtd_tg, fonte_ausente = None, None, True

    for metrica, valor_a, valor_b, ausente in (
        ("Valor das NEs", valor_simec, valor_tg, fonte_ausente),
        ("Quantidade de NEs", Decimal(qtd_simec), Decimal(qtd_tg) if qtd_tg is not None else None, fonte_ausente),
    ):
        if ausente:
            diferenca, situacao = None, "Fonte ausente"
        else:
            diferenca = valor_a - valor_b
            if tem_pendencia or abs(diferenca) > tolerancia:
                situacao = "Conferência necessária"
            else:
                situacao = "Conciliado"
        linhas_comparacao.append(
            {
                "chave_ted": chave_ted, "ted": ted_row["ted"], "siafi": ted_row["codigo_siafi"],
                "metrica": metrica, "simec": valor_a, "documentos": qtd_simec, "tg": valor_b,
                "diferenca": diferenca, "situacao": situacao,
            }
        )

comparacao = pd.DataFrame(linhas_comparacao)
if tipo_sel != "Todos":
    comparacao = comparacao[comparacao["metrica"] == tipo_sel]
if situacao_sel != "Todas":
    comparacao = comparacao[comparacao["situacao"] == situacao_sel]

kpi = st.columns(4)
kpi[0].container(border=True).metric("Conciliados", str((comparacao["situacao"] == "Conciliado").sum()))
kpi[1].container(border=True).metric("Conferência necessária", str((comparacao["situacao"] == "Conferência necessária").sum()))
kpi[2].container(border=True).metric("Fonte ausente", str((comparacao["situacao"] == "Fonte ausente").sum()))
diferenca_total = sum(
    (abs(d) for d in comparacao.loc[comparacao["metrica"] == "Valor das NEs", "diferenca"].dropna()), start=Decimal("0")
)
kpi[3].container(border=True).metric("Diferença total", brl(diferenca_total))

st.markdown("#### Comparação entre fontes")
if comparacao.empty:
    st.caption("Nenhum registro para os filtros selecionados.")
else:
    cabecalho = st.columns([0.8, 1, 1.6, 1.4, 1, 1.4, 1.2, 1.6, 0.8])
    for coluna, rotulo in zip(cabecalho, ["TED", "SIAFI", "Métrica", "SIMEC", "Documentos", "Tesouro Gerencial", "Diferença", "Situação", ""]):
        coluna.markdown(f"**{rotulo}**" if rotulo else "")
    for posicao, linha in comparacao.reset_index(drop=True).iterrows():
        c = st.columns([0.8, 1, 1.6, 1.4, 1, 1.4, 1.2, 1.6, 0.8])
        c[0].write(linha["ted"])
        c[1].write(linha["siafi"])
        c[2].write(linha["metrica"])
        c[3].write(brl(linha["simec"]) if linha["metrica"] == "Valor das NEs" else str(int(linha["simec"])))
        c[4].write(str(linha["documentos"]))
        if linha["situacao"] == "Fonte ausente":
            c[5].write("—")
            c[6].write("—")
        else:
            c[5].write(brl(linha["tg"]) if linha["metrica"] == "Valor das NEs" else str(int(linha["tg"])))
            c[6].write(brl(linha["diferenca"]) if linha["metrica"] == "Valor das NEs" else str(int(linha["diferenca"])))
        c[7].markdown(badge(linha["situacao"], cor_situacao_conciliacao(linha["situacao"])), unsafe_allow_html=True)
        if linha["situacao"] == "Conferência necessária":
            if c[8].button("Analisar", key=f"cc_analisar_{posicao}"):
                st.session_state["cc_evidencia"] = (linha["chave_ted"], linha["metrica"])
        else:
            c[8].write("")

evidencia = st.session_state.get("cc_evidencia")
if evidencia:
    chave_ted_ev, metrica_ev = evidencia
    ted_row = teds_df[teds_df["chave_ted"] == chave_ted_ev]
    if not ted_row.empty:
        ted_row = ted_row.iloc[0]
        with st.container(border=True):
            col_titulo, col_fechar = st.columns([5, 1])
            col_titulo.markdown(f"#### Evidências da divergência — TED {ted_row['ted']} · {metrica_ev}")
            if col_fechar.button("Fechar"):
                del st.session_state["cc_evidencia"]
                st.rerun()

            ne_linhas = _linhas_ne(chave_ted_ev)
            pendentes = [n for n, _, s in ne_linhas if s == "pendente"]
            if pendentes:
                st.warning(f"NE(s) com pendência de NE-em-múltiplos-TEDs neste TED: {', '.join(pendentes)}.")

            col_simec, col_tg = st.columns(2)
            with col_simec:
                st.markdown("**SIMEC**")
                st.dataframe(
                    pd.DataFrame(ne_linhas, columns=["Número da NE", "Valor", "Status"]).assign(Valor=lambda d: d["Valor"].map(brl)),
                    hide_index=True, width="stretch",
                )
            with col_tg:
                st.markdown("**Tesouro Gerencial**")
                tg_linhas = _tg_por_numeros({n for n, _, _ in ne_linhas})
                if not tg_linhas:
                    st.caption("Sem dado — nenhuma extração do Tesouro Gerencial importada para estas NEs.")
                else:
                    st.dataframe(
                        pd.DataFrame(tg_linhas, columns=["Número completo da NE", "Empenhado"]).assign(Empenhado=lambda d: d["Empenhado"].map(brl)),
                        hide_index=True, width="stretch",
                    )
