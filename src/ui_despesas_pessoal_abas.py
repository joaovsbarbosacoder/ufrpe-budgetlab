"""Abas auxiliares da página Acompanhamento de Pessoal (27/09/2026).

- "Fórmulas de projeção": expõe cada fórmula de `src.despesas_pessoal` com os valores
  em uso e deixa os números editáveis em campos. O resultado é um
  `ParametrosProjecao`; os campos vivem só no `st.session_state` (sem persistência —
  AGENTS.md) e partem sempre de `PARAMETROS_PADRAO` (as decisões confirmadas).
- "Exercícios anteriores": leitura da execução já realizada (Execução Anual e Mensal)
  de um exercício passado, sem projeção alguma.

Nenhum cálculo financeiro mora aqui — só coleta de parâmetros e formatação.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.despesas_pessoal import (
    GRUPO_ATIVO, GRUPO_INATIVO, GRUPO_OUTROS_BENEFICIOS, GRUPO_RPPS,
    MESES_NOMES, PARAMETROS_PADRAO, REGRA_MULTIPLICADOR, TABELA_REGRAS,
    ParametrosProjecao, comparar_beneficios_por_plano_orcamentario, comparar_projecao_com_executado, desvio_por_mes_de_partida, dotacao_atualizada_por_grupo, execucao_exercicio_por_grupo,
    execucao_exercicio_por_natureza, liquidada_mensal_por_grupo, resumo_projecao_com_executado,
)

PREFIXO = "dp_f_"
NOMES_GRUPOS = {
    GRUPO_ATIVO: "Ativo (20TP)", GRUPO_INATIVO: "Inativo (0181)",
    GRUPO_RPPS: "RPPS (09HB)", GRUPO_OUTROS_BENEFICIOS: "Outros Benefícios (2004/212B)",
}


def brl(valor) -> str:
    """R$ com centavos, padrão pt-BR; nulo vira "—" (nunca zero)."""
    if valor is None or pd.isna(valor):
        return "—"
    # arredonda antes do sinal: resíduo de ponto flutuante não vira "−R$ 0,00".
    centavos = round(float(valor), 2)
    texto = f"{abs(centavos):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if centavos < 0 else "") + "R$ " + texto


def _mult(valor: float) -> str:
    return f"×{valor:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def tabela_multiplicadores() -> pd.DataFrame:
    """Rubricas de multiplicador direto da `TABELA_REGRAS`, com os valores padrão."""
    linhas = [
        {"Natureza": cod, "Descrição": regra.descricao, "Multiplicador": float(regra.multiplicador),
         "Extra só na parcela final": regra.extra_concentrado_em_novembro}
        for cod, regra in sorted(TABELA_REGRAS.items()) if regra.tipo == REGRA_MULTIPLICADOR
    ]
    return pd.DataFrame(linhas)


def parametros_da_tabela(editada: pd.DataFrame, **demais) -> ParametrosProjecao:
    """Monta `ParametrosProjecao` só com o que difere da tabela padrão (código como
    texto, nunca número). Levanta `ValueError` com a mensagem de validação."""
    multiplicadores, extras = {}, {}
    for linha in editada.itertuples(index=False):
        cod = str(linha[0])
        padrao = TABELA_REGRAS[cod]
        mult, extra = linha[2], linha[3]
        if mult is None or pd.isna(mult):
            raise ValueError(f"Natureza {cod}: multiplicador em branco.")
        if float(mult) != padrao.multiplicador:
            multiplicadores[cod] = float(mult)
        if bool(extra) != padrao.extra_concentrado_em_novembro:
            extras[cod] = bool(extra)
    return ParametrosProjecao(multiplicadores_natureza=multiplicadores, extra_concentrado_natureza=extras, **demais)


def _restaurar() -> None:
    for chave in [k for k in st.session_state if str(k).startswith(PREFIXO)]:
        del st.session_state[chave]


def render_formulas() -> tuple[ParametrosProjecao, str | None]:
    """Campos editáveis das fórmulas. Devolve (parâmetros em uso, erro de validação).
    Com erro, devolve `PARAMETROS_PADRAO` — o erro é exibido, nunca ignorado."""
    p0 = PARAMETROS_PADRAO
    st.markdown("#### Fórmulas de projeção")
    st.caption(
        "Os valores iniciais são as regras confirmadas da metodologia (relatório SPO/MEC e decisões "
        "registradas em `src/despesas_pessoal.py`). Alterações valem só nesta sessão, recalculam o "
        "painel imediatamente e ficam declaradas na procedência. R = Liquidada da rubrica no mês de "
        "referência (data-base); m = multiplicador; f = fração paga na antecipação do 13º."
    )
    st.button("Restaurar fórmulas padrão", on_click=_restaurar, key=PREFIXO + "restaurar_botao")

    st.markdown("##### 1. Multiplicador por natureza de despesa")
    st.markdown(
        "Mês futuro = **R**. No mês da antecipação do 13º soma **f × (m − 12) × R** e no mês da "
        "parcela final **(1 − f) × (m − 12) × R**. Com *Extra só na parcela final* marcado "
        "(Obrigações Patronais), **(m − 12) × R** inteiro cai na parcela final. "
        "Total anual equivalente: **m × R**."
    )
    editada = st.data_editor(
        tabela_multiplicadores(), key=PREFIXO + "tabela", hide_index=True, width="stretch",
        disabled=["Natureza", "Descrição"], num_rows="fixed",
        column_config={
            "Natureza": st.column_config.TextColumn(width="small"),
            "Multiplicador": st.column_config.NumberColumn(min_value=12.0, step=0.0001, format="%.4f"),
            "Extra só na parcela final": st.column_config.CheckboxColumn(),
        },
    )

    st.markdown("##### 2. Multiplicador por grupo (sentenças, indenizações, rubrica sem regra)")
    c1, c2, c3 = st.columns(3)
    numero = dict(min_value=12.0, step=0.0001, format="%.4f")
    with c1:
        st.caption("Sentenças Judiciais (319091/339091)")
        sentenca_ativo = st.number_input("Ativo", value=p0.sentenca_ativo, key=PREFIXO + "sentenca_ativo", **numero)
        sentenca_inativo = st.number_input("Inativo", value=p0.sentenca_inativo, key=PREFIXO + "sentenca_inativo", **numero)
        sentenca_demais = st.number_input("Demais grupos", value=p0.sentenca_demais, key=PREFIXO + "sentenca_demais", **numero)
    with c2:
        st.caption("Indenizações Trabalhistas (319094)")
        indenizacao_inativo = st.number_input("Inativo", value=p0.indenizacao_inativo, key=PREFIXO + "indenizacao_inativo", **numero)
        indenizacao_demais = st.number_input("Ativo e demais grupos", value=p0.indenizacao_demais, key=PREFIXO + "indenizacao_demais", **numero)
    with c3:
        st.caption("Rubrica sem regra nas ações 2004/212B (gera alerta)")
        sem_regra = st.number_input("Multiplicador aplicado", value=p0.multiplicador_sem_regra_beneficios,
                                    key=PREFIXO + "sem_regra", **numero)
    st.caption("Ações 20TP/0181/09HB: rubrica sem regra continua sendo **erro** (não projetada), não editável.")

    st.markdown("##### 3. 13º salário e distribuição no tempo")
    st.markdown(
        "Rubricas de 13º (31901143, 31900106, 31900303, 31900413): antecipação = **f × R_mãe**, "
        "parcela final = **(1 − f) × R_mãe**, demais meses futuros = 0 — R_mãe é a Liquidada do mês "
        "de referência da natureza mãe (319011, 319001, 319003 ou 319004), sem as sub-rubricas com regra própria."
    )
    c1, c2, c3 = st.columns(3)
    meses = list(range(1, 13))
    formatar_mes = lambda m: MESES_NOMES[m - 1]  # noqa: E731
    with c1:
        mes_antecipacao = st.selectbox("Mês da antecipação", meses, index=p0.mes_antecipacao_13 - 1,
                                       format_func=formatar_mes, key=PREFIXO + "mes_antecipacao")
    with c2:
        mes_parcela = st.selectbox("Mês da parcela final", meses, index=p0.mes_parcela_13 - 1,
                                   format_func=formatar_mes, key=PREFIXO + "mes_parcela")
    with c3:
        fracao_antecipacao = st.number_input("f — fração na antecipação", min_value=0.0, max_value=1.0,
                                             value=p0.fracao_antecipacao_13, step=0.05, format="%.2f",
                                             key=PREFIXO + "fracao_antecipacao")
    dezembro = st.checkbox("Dezembro projetado do Ativo repete o valor de novembro (real ou projetado)",
                           value=p0.dezembro_ativo_repete_novembro, key=PREFIXO + "dezembro")

    st.markdown("##### 4. Mês fechado (data-base padrão)")
    st.markdown(
        "Um mês é *fechado* se, em cada grupo, a Liquidada for ≥ **fração mínima × média dos N meses "
        "anteriores** daquele grupo. O último mês fechado é a data-base inicial do painel."
    )
    c1, c2 = st.columns(2)
    with c1:
        janela = st.number_input("N — meses anteriores comparados", min_value=1, max_value=12,
                                 value=p0.janela_meses_fechamento, step=1, key=PREFIXO + "janela")
    with c2:
        fracao_fechamento = st.number_input("Fração mínima", min_value=0.0, max_value=1.0,
                                            value=p0.fracao_minima_fechamento, step=0.05, format="%.2f",
                                            key=PREFIXO + "fracao_fechamento")

    with st.expander("Fórmulas fixas (não editáveis)"):
        st.markdown(
            "- **Despesas de Exercícios Anteriores** (319092/339092/319192): meses futuros = 0.\n"
            "- **Abono pecuniário / 1/3 de férias / adiantamento de férias** (31901144/45/46): na grade "
            "mensal, cada mês futuro repete **R** da própria sub-rubrica. A proporção histórica sobre "
            "vencimentos do ano anterior só entra no cálculo anual consolidado (`projetar`), que este "
            "painel não exibe.\n"
            "- **Meses executados** (até a data-base): Liquidada real da Execução Mensal — nunca "
            "substituída por projeção nem por ajuste manual.\n"
            "- **Saldo remanescente**: Dotação Atualizada do exercício − acumulado (executado + projetado) até o mês.\n"
            "- **Base PLOA**: R por rubrica, sem multiplicador."
        )

    try:
        parametros = parametros_da_tabela(
            editada, sentenca_ativo=sentenca_ativo, sentenca_inativo=sentenca_inativo,
            sentenca_demais=sentenca_demais, indenizacao_inativo=indenizacao_inativo,
            indenizacao_demais=indenizacao_demais, multiplicador_sem_regra_beneficios=sem_regra,
            mes_antecipacao_13=int(mes_antecipacao), mes_parcela_13=int(mes_parcela),
            fracao_antecipacao_13=float(fracao_antecipacao), dezembro_ativo_repete_novembro=bool(dezembro),
            janela_meses_fechamento=int(janela), fracao_minima_fechamento=float(fracao_fechamento),
        )
    except ValueError as erro:
        st.error(f"Parâmetro inválido — o painel está usando as fórmulas padrão até a correção: {erro}")
        return PARAMETROS_PADRAO, str(erro)
    return parametros, None


def render_exercicios_anteriores(anual: pd.DataFrame, mensal: pd.DataFrame, dotacao: pd.DataFrame,
                                 ano_corrente: int, procedencia: str = "", *,
                                 parametros: ParametrosProjecao | None = None,
                                 mes_referencia_padrao: int | None = None,
                                 formulas_ajustadas: bool = False) -> None:
    """Execução realizada de um exercício anterior a `ano_corrente` e, quando a base
    mensal cobre o exercício, a projeção reconstruída com as fórmulas em uso × o
    executado (`render_projecao_com_executado`)."""
    st.markdown("#### Execução de exercícios anteriores")
    anos = sorted({int(a) for a in anual["ano"].dropna().unique() if int(a) < ano_corrente}, reverse=True)
    if not anos:
        st.info(f"A Execução Anual importada não tem exercício anterior a {ano_corrente}.")
        return
    ano = st.selectbox("Exercício", anos, index=0, key="dp_hist_ano")

    por_grupo = execucao_exercicio_por_grupo(anual, ano)
    if por_grupo.empty:
        st.info(f"Sem execução de pessoal nas ações acompanhadas em {ano}.")
        return
    dotacao_grupo = dotacao_atualizada_por_grupo(dotacao, ano)
    resumo = por_grupo.assign(dotacao=por_grupo["grupo"].map(dotacao_grupo))
    total = {"grupo": "total", **{c: resumo[c].sum(min_count=1) for c in ("dotacao", "empenhada", "liquidada", "paga")}}
    resumo = pd.concat([resumo, pd.DataFrame([total])], ignore_index=True)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Dotação Atualizada", brl(total["dotacao"]))
    k2.metric("Empenhada", brl(total["empenhada"]))
    k3.metric("Liquidada", brl(total["liquidada"]))
    k4.metric("Paga", brl(total["paga"]))

    st.markdown("##### Resumo por grupo (Execução Anual)")
    st.dataframe(pd.DataFrame({
        "Grupo": resumo["grupo"].map(lambda g: NOMES_GRUPOS.get(g, "TOTAL")),
        "Dotação Atualizada": resumo["dotacao"].map(brl),
        "Empenhada": resumo["empenhada"].map(brl),
        "Liquidada": resumo["liquidada"].map(brl),
        "Paga": resumo["paga"].map(brl),
    }), hide_index=True, width="stretch")

    st.markdown("##### Liquidada mês a mês (Execução Mensal)")
    mensal_ano = liquidada_mensal_por_grupo(mensal, ano)
    if mensal_ano.empty:
        anos_mensal = sorted({int(v) // 100 for v in mensal["ano_mes"].dropna().unique()})
        cobertura = f"de {anos_mensal[0]} a {anos_mensal[-1]}" if anos_mensal else "nenhum exercício"
        st.info(f"A Execução Mensal importada cobre {cobertura}; para {ano} há apenas o total anual acima.")
    else:
        tabela = pd.DataFrame({"Grupo": [NOMES_GRUPOS[g] for g in mensal_ano.index]})
        for mes in range(1, 13):
            tabela[MESES_NOMES[mes - 1]] = [brl(v) for v in mensal_ano[mes]]
        totais_grupo = mensal_ano.sum(axis=1, min_count=1)
        tabela["Total"] = [brl(v) for v in totais_grupo]
        st.dataframe(tabela, hide_index=True, width="stretch")
        soma_mensal = totais_grupo.sum(min_count=1)
        diferenca = None if pd.isna(soma_mensal) or pd.isna(total["liquidada"]) else float(total["liquidada"]) - float(soma_mensal)
        st.caption(
            f"Conciliação: Liquidada anual {brl(total['liquidada'])} − soma mensal {brl(soma_mensal)} = "
            f"{brl(diferenca)}. As duas bases têm extrações independentes."
        )
        render_projecao_com_executado(mensal, anual, ano, mensal_ano, parametros,
                                      mes_referencia_padrao, formulas_ajustadas)

    with st.expander("Detalhe por natureza de despesa"):
        detalhe = execucao_exercicio_por_natureza(anual, ano)
        st.dataframe(pd.DataFrame({
            "Grupo": detalhe["grupo"].map(NOMES_GRUPOS),
            "Natureza": detalhe["natureza_despesa_cod"].astype(str),
            "Descrição": detalhe["natureza_despesa_desc"],
            "Empenhada": detalhe["empenhada"].map(brl),
            "Liquidada": detalhe["liquidada"].map(brl),
            "Paga": detalhe["paga"].map(brl),
        }), hide_index=True, width="stretch")
    if procedencia:
        st.caption(procedencia)


def _pct(valor) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    # arredonda antes do sinal: −0,04% não vira "−0,0%".
    percentual = round(float(valor) * 100, 1) + 0.0
    return f"{percentual:+.1f}%".replace(".", ",").replace("-", "−")


def render_projecao_com_executado(mensal: pd.DataFrame, anual: pd.DataFrame, ano: int,
                                  mensal_ano: pd.DataFrame, parametros: ParametrosProjecao | None,
                                  mes_referencia_padrao: int | None, formulas_ajustadas: bool) -> None:
    """Projeção reconstruída × executado — só leitura; nada aqui altera o painel."""
    st.markdown("##### Projeção reconstruída × executado")
    meses_com_dado = [m for m in range(1, 12) if mensal_ano[m].notna().any()]
    if not meses_com_dado:
        st.info(f"Sem mês de {ano} com dado para servir de referência.")
        return
    padrao = mes_referencia_padrao if mes_referencia_padrao in meses_com_dado else meses_com_dado[-1]
    mes_ref = st.selectbox(
        "Projetar a partir de (mês de referência)", meses_com_dado, index=meses_com_dado.index(padrao),
        format_func=lambda m: f"{MESES_NOMES[m - 1]}/{ano}", key="dp_hist_mes_referencia",
    )
    st.caption(
        "Aplica as fórmulas " + ("**ajustadas nesta sessão** (aba Fórmulas de projeção)" if formulas_ajustadas
                                 else "padrão da metodologia")
        + f" como se a data-base fosse {MESES_NOMES[mes_ref - 1]}/{ano} e compara os meses seguintes com a "
        "Liquidada que de fato ocorreu. Ajustes manuais de meses do painel não entram. "
        "Diferença = executado − projetado (positivo: a projeção ficou abaixo do real)."
    )
    comparacao = comparar_projecao_com_executado(mensal, anual, ano, int(mes_ref), parametros)
    if comparacao.empty:
        st.info("Não há rubricas de pessoal para projetar nesta referência.")
        return
    resumo = resumo_projecao_com_executado(comparacao)
    st.dataframe(pd.DataFrame({
        "Grupo": resumo["grupo"].map(lambda g: NOMES_GRUPOS.get(g, "TOTAL")),
        "Meses comparados": resumo["meses"],
        "Projetado": resumo["projetado"].map(brl),
        "Executado": resumo["executado"].map(brl),
        "Diferença": resumo["diferenca"].map(brl),
        "Diferença %": resumo["diferenca_pct"].map(_pct),
    }), hide_index=True, width="stretch")
    with st.expander("Mês a mês por grupo"):
        st.dataframe(pd.DataFrame({
            "Grupo": comparacao["grupo"].map(NOMES_GRUPOS),
            "Mês": comparacao["mes"].map(lambda m: MESES_NOMES[m - 1]),
            "Projetado": comparacao["projetado"].map(brl),
            "Executado": comparacao["executado"].map(brl),
            "Diferença": comparacao["diferenca"].map(brl),
        }), hide_index=True, width="stretch")

    with st.expander("Outros Benefícios por Plano Orçamentário"):
        render_beneficios_por_plano(mensal, anual, ano, int(mes_ref), parametros,
                                    resumo.set_index("grupo")["projetado"].get(GRUPO_OUTROS_BENEFICIOS))

    # Recalcula a grade uma vez por mês de partida (~5 s na base real) — só sob demanda.
    if st.toggle("Comparar todos os meses de partida", key="dp_hist_todos_meses"):
        render_desvio_por_mes_de_partida(mensal, anual, ano, parametros)


def tabela_desvio_por_mes_de_partida(desvio: pd.DataFrame) -> pd.DataFrame:
    """Mês de partida × grupo, com a Diferença % de cada combinação (nulo = "—")."""
    grupos = [g for g in NOMES_GRUPOS if g in set(desvio["grupo"])] + ["total"]
    tabela = pd.DataFrame({"Mês de partida": [
        f"{MESES_NOMES[m - 1]}" for m in sorted(desvio["mes_referencia"].unique())
    ]})
    for grupo in grupos:
        valores = desvio.loc[desvio["grupo"] == grupo].set_index("mes_referencia")["diferenca_pct"]
        tabela[NOMES_GRUPOS.get(grupo, "TOTAL")] = [
            _pct(valores.get(m)) for m in sorted(desvio["mes_referencia"].unique())
        ]
    return tabela


def render_desvio_por_mes_de_partida(mensal: pd.DataFrame, anual: pd.DataFrame, ano: int,
                                     parametros: ParametrosProjecao | None) -> None:
    desvio = desvio_por_mes_de_partida(mensal, anual, ano, parametros)
    if desvio.empty:
        st.info(f"Sem mês de {ano} com dado para servir de partida.")
        return
    st.caption(
        "Cada linha repete a comparação acima partindo de um mês diferente: Diferença % = "
        "(executado − projetado) ÷ projetado, somando os meses seguintes que têm os dois lados. "
        "Sinal constante em várias linhas indica desvio sistemático da fórmula; um valor isolado "
        "muito alto costuma indicar um mês de partida atípico (a projeção repete aquele mês)."
    )
    st.dataframe(tabela_desvio_por_mes_de_partida(desvio), hide_index=True, width="stretch")


def render_beneficios_por_plano(mensal: pd.DataFrame, anual: pd.DataFrame, ano: int, mes_ref: int,
                                parametros: ParametrosProjecao | None, projetado_grupo) -> None:
    """Desvio de Outros Benefícios aberto por (Ação, Plano Orçamentário)."""
    comparacao = comparar_beneficios_por_plano_orcamentario(mensal, anual, ano, mes_ref, parametros)
    if comparacao.empty:
        st.info("Sem Plano Orçamentário de Outros Benefícios nesta referência.")
        return
    resumo = resumo_projecao_com_executado(comparacao, chave="plano")
    rotulos = comparacao.drop_duplicates("plano").set_index("plano")
    corpo = resumo[resumo["plano"] != "total"].copy()
    corpo["_ordem"] = corpo["diferenca"].abs()
    corpo = corpo.sort_values("_ordem", ascending=False, na_position="last")
    ordenado = pd.concat([corpo, resumo[resumo["plano"] == "total"]], ignore_index=True)
    st.caption(
        "Mesma referência e mesmas fórmulas da tabela acima, só para Outros Benefícios; ordenado pela "
        "maior diferença absoluta. Diferença % fica “—” quando o projetado é zero ou negativo."
    )
    st.dataframe(pd.DataFrame({
        "Ação": ordenado["plano"].map(lambda k: rotulos["acao_cod"].get(k, "TOTAL")),
        "PO": ordenado["plano"].map(lambda k: rotulos["po_cod"].get(k, "")),
        "Descrição": ordenado["plano"].map(lambda k: rotulos["po_desc"].get(k, "")),
        "Meses comparados": ordenado["meses"],
        "Projetado": ordenado["projetado"].map(brl),
        "Executado": ordenado["executado"].map(brl),
        "Diferença": ordenado["diferenca"].map(brl),
        "Diferença %": ordenado["diferenca_pct"].map(_pct),
    }), hide_index=True, width="stretch")
    total_po = resumo.set_index("plano").loc["total", "projetado"]
    if not (pd.isna(total_po) and pd.isna(projetado_grupo)) and (
        pd.isna(total_po) or pd.isna(projetado_grupo) or round(float(total_po), 2) != round(float(projetado_grupo), 2)
    ):
        st.warning(f"Soma dos Planos Orçamentários ({brl(total_po)}) difere da linha do grupo ({brl(projetado_grupo)}).")
