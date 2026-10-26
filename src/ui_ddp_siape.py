"""Aba "Folha (DDP)" da página Acompanhamento de Pessoal (27/10/2026).

O usuário envia os PDFs do SIAPE (DDP e Crédito Bancário, de servidor e de pensionista);
a aba mostra a conferência dos totais, o reforço por empenho e o confronto com a Liquidada
da base. Os PDFs ficam só na memória da sessão — nada é gravado (AGENTS.md). Nenhum
cálculo financeiro mora aqui: tudo vem de `src.ddp_siape`.
"""
from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from src.ddp_siape import (
    TIPO_DDP, conferencia, confronto_liquidado, ddp_por_natureza, ler_relatorio, plano_operacoes, quadro_reforco,
    reserva_projetada, separar_competencias, validar_conjunto, variacao_por_natureza,
)
from src.despesas_pessoal import MESES_NOMES
from src.ui_despesas_pessoal_abas import _md, brl


def _mes(ano_mes: int | None) -> str:
    return "—" if ano_mes is None else f"{MESES_NOMES[ano_mes % 100 - 1].lower()}/{ano_mes // 100}"


def _situacao(linha) -> str:
    diferencas = {
        "bruto − descontos ≠ líquido": linha["dif_bruto_menos_desconto"],
        "naturezas ≠ bruto": linha["dif_naturezas_bruto"],
        "seções (2) e (3) ≠ descontos": linha["dif_desconto"],
        "crédito bancário ≠ líquido": linha["dif_credito"],
    }
    problemas = [f"{nome}: {brl(valor)}" for nome, valor in diferencas.items()
                 if valor is not None and not pd.isna(valor) and abs(valor) >= 0.005]
    if problemas:
        return "Diferença — " + "; ".join(problemas)
    if linha["credito_bancario"] is None or pd.isna(linha["credito_bancario"]):
        return "Confere internamente (crédito bancário não enviado)"
    return "Confere"


def tabela_conferencia(conf: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{
        "Competência": _mes(linha["competencia"]), "Público": linha["publico"].title(), "Folha": linha["folha"].title(),
        "Bruto": brl(linha["bruto"]), "Descontos": brl(linha["desconto"]), "Líquido": brl(linha["liquido"]),
        "Crédito bancário": brl(linha["credito_bancario"]), "Situação": _situacao(linha),
    } for _, linha in conf.iterrows()])


def tabela_por_empenho(por_empenho: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Empenho": por_empenho["empenho"], "Ação": por_empenho["acao_cod"].fillna("—"),
        "Saldo a liquidar": por_empenho["saldo"].map(brl), "DDP do mês": por_empenho["ddp"].map(brl),
        "Falta nos itens": por_empenho["falta"].map(brl), "Sobra livre nos itens": por_empenho["sobra_livre"].map(brl),
        "Compensa na própria NE": por_empenho["compensa"].map(brl), "Reforço do mês": por_empenho["reforco_mes"].map(brl),
        "Reforço até dezembro": por_empenho["reforco_ate_dezembro"].map(brl),
    })


def tabela_itens(itens: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Empenho": itens["empenho"], "Natureza": itens["natureza_detalhada"], "Descrição": itens["descricao"].fillna("—"),
        "Saldo a liquidar": itens["saldo"].map(brl), "DDP do mês": itens["ddp"].map(brl), "Falta": itens["falta"].map(brl),
        "Reserva dos meses seguintes": itens["reserva"].map(brl), "Sobra livre": itens["sobra_livre"].map(brl),
        "Saldo depois de dezembro": itens["saldo_apos_ano"].map(brl), "Critério": itens["criterio"],
        "Reserva por": itens["tipo_reserva"], "Já liquidado no mês": itens["liquidado_no_mes"].map(brl),
    })


def tabela_confronto(confronto: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Natureza": confronto["natureza_detalhada"], "Descrição na DDP": confronto["descricao"],
        "DDP líquida": confronto["ddp"].map(brl), "Liquidada na base": confronto["liquidado_no_mes"].map(brl),
        "Diferença (base − DDP)": confronto["diferenca"].map(brl),
    })


def tabela_plano(plano: pd.DataFrame, itens: pd.DataFrame) -> pd.DataFrame:
    descricao = itens.dropna(subset=["descricao"]).drop_duplicates("natureza_detalhada").set_index("natureza_detalhada")["descricao"]
    rotulo = lambda n: "—" if n is None or pd.isna(n) else f"{n} {descricao.get(n, '')}".strip()
    return pd.DataFrame({
        "Empenho": plano["empenho"], "Operação": plano["operacao"].str.capitalize(),
        "Anular do item": plano["item_origem"].map(rotulo), "Reforçar o item": plano["item_destino"].map(rotulo),
        "Valor": plano["valor"].map(brl),
    })


_SITUACOES = {"nova": "Nova", "saiu": "Não veio neste mês", "alta": "Alta", "queda": "Queda", "sem variação": "Sem variação"}


def tabela_variacao(variacao: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Natureza": variacao["natureza_detalhada"], "Descrição na DDP": variacao["descricao"].fillna("—"),
        "Mês anterior": variacao["anterior"].map(brl), "Mês atual": variacao["atual"].map(brl),
        "Variação": variacao["variacao"].map(brl), "Situação": variacao["situacao"].map(_SITUACOES),
    })


def render_variacao(variacao: pd.DataFrame, anterior: int, atual: int) -> None:
    """O que mudou na DDP entre as duas competências enviadas (27/10/2026)."""
    st.markdown(f"**O que mudou de {_mes(anterior)} para {_mes(atual)}**")
    total_anterior, total_atual = variacao["anterior"].sum(), variacao["atual"].sum()
    colunas = st.columns(3)
    colunas[0].metric(f"DDP líquida de {_mes(anterior)}", brl(total_anterior))
    colunas[1].metric(f"DDP líquida de {_mes(atual)}", brl(total_atual))
    colunas[2].metric("Variação", brl(total_atual - total_anterior),
                      f"{(total_atual / total_anterior - 1):+.1%}".replace(".", ",") if total_anterior else None,
                      delta_color="off")
    novas = variacao.loc[variacao["situacao"] == "nova"]
    sairam = variacao.loc[variacao["situacao"] == "saiu"]
    if not novas.empty:
        st.caption(_md("Naturezas novas: " + "; ".join(
            f"{r.natureza_detalhada} {r.descricao} ({brl(r.atual)})" for r in novas.itertuples()) + "."))
    if not sairam.empty:
        st.caption(_md("Não vieram neste mês: " + "; ".join(
            f"{r.natureza_detalhada} {r.descricao} ({brl(r.anterior)} no anterior)" for r in sairam.itertuples()) + "."))
    mudaram = variacao.loc[variacao["variacao"] != 0]
    st.dataframe(tabela_variacao(mudaram.head(10)), hide_index=True, width="stretch", height="content")
    with st.expander(f"Todas as naturezas ({len(variacao)})"):
        st.dataframe(tabela_variacao(variacao), hide_index=True, width="stretch", height="content")


def planilha_excel(competencia: int, conf: pd.DataFrame, plano: pd.DataFrame, por_empenho: pd.DataFrame,
                   itens: pd.DataFrame) -> bytes:
    """Planilha para download (gerada em memória, nada é gravado no servidor), com os valores numéricos."""
    arquivo = BytesIO()
    with pd.ExcelWriter(arquivo, engine="openpyxl") as escritor:
        plano.to_excel(escritor, sheet_name="Plano por item", index=False)
        por_empenho.to_excel(escritor, sheet_name="Por empenho", index=False)
        itens.drop(columns=["nes"]).to_excel(escritor, sheet_name="Itens", index=False)
        conf.to_excel(escritor, sheet_name="Conferência", index=False)
        pd.DataFrame({"competencia": [competencia]}).to_excel(escritor, sheet_name="Referência", index=False)
    return arquivo.getvalue()


def render_ddp(mensal: pd.DataFrame, grade_linhas: pd.DataFrame, ano_grade: int, procedencia: str) -> None:
    """`grade_linhas`: `grade_mensal(...).linhas` do painel (projeção por natureza
    detalhada, com as fórmulas da sessão), usada só para a reserva dos meses seguintes."""
    st.markdown(
        "Envie os PDFs do SIAPE do mês: **DDP** e **Crédito Bancário**, de servidor e de pensionista. "
        "A aba confere os totais e calcula, por empenho, quanto falta para liquidar a folha. Os arquivos "
        "ficam só nesta sessão e não são gravados."
    )
    arquivos = st.file_uploader("PDFs do SIAPE", type="pdf", accept_multiple_files=True, key="dp_ddp_pdfs",
                                label_visibility="collapsed")
    if not arquivos:
        return
    relatorios = []
    for arquivo in arquivos:
        try:
            relatorios.append(ler_relatorio(arquivo.getvalue(), arquivo.name))
        except ValueError as erro:
            st.error(str(erro))
    if not relatorios:
        return
    erros = validar_conjunto(relatorios)
    for erro in erros:
        st.error(erro)
    if erros:
        return

    atuais, anteriores = separar_competencias(relatorios)
    ddp = next(r for r in atuais if r.tipo == TIPO_DDP)
    competencia = ddp.competencia
    publicos = sorted({r.publico.lower() for r in atuais if r.tipo == TIPO_DDP})
    st.subheader(f"Folha de {_mes(competencia)}")
    st.caption(
        f"Paga em {_mes(ddp.mes_pagamento)}; relatórios gerados em "
        f"{', '.join(sorted({r.data_geracao.strftime('%d/%m/%Y') for r in atuais if r.data_geracao}))}. "
        f"DDP de {' e '.join(publicos)}."
        + (f" Os PDFs de {_mes(anteriores[0].competencia)} entram só na comparação." if anteriores else "")
    )
    if len(publicos) < 2:
        st.warning("Só foi enviada a DDP de " + publicos[0] + ": o reforço abaixo não inclui a outra folha.")

    st.markdown("**Conferência dos totais**")
    conf = conferencia(relatorios)
    st.dataframe(tabela_conferencia(conf), hide_index=True, width="stretch", height="content")

    natureza = ddp_por_natureza(atuais)
    if anteriores:
        render_variacao(variacao_por_natureza(natureza, ddp_por_natureza(anteriores)),
                        anteriores[0].competencia, competencia)
    confronto = confronto_liquidado(natureza, mensal, competencia)
    if competencia // 100 != ano_grade:
        st.warning(
            f"A DDP é de {competencia // 100} e a projeção do painel está em {ano_grade}: o reforço precisa da "
            f"projeção do mesmo exercício (escolha a referência na aba Acompanhamento). Abaixo, só o confronto "
            f"com a Liquidada."
        )
        st.dataframe(tabela_confronto(confronto), hide_index=True, width="stretch", height="content")
        return

    itens, por_empenho = quadro_reforco(natureza, mensal, competencia, reserva_projetada(grade_linhas, competencia % 100))
    total_ddp = float(natureza["liquido"].sum())
    ja_liquidado = float(confronto["liquidado_no_mes"].sum())
    if ja_liquidado > 0.004:
        st.warning(_md(
            f"A base já tem {brl(ja_liquidado)} liquidados em {_mes(competencia)} nas naturezas da DDP "
            f"({ja_liquidado / total_ddp:.0%} da DDP). O saldo abaixo já desconta esse valor: se for a própria "
            f"folha, o reforço a conta duas vezes — confira em “DDP × Liquidada no mês”."
        ))

    colunas = st.columns(4)
    colunas[0].metric(f"DDP líquida de {_mes(competencia)}", brl(total_ddp))
    colunas[1].metric("Falta nos itens", brl(por_empenho["falta"].sum()))
    colunas[2].metric("Reforço do mês", brl(por_empenho["reforco_mes"].sum()),
                      help="Falta nos itens menos o que dá para cobrir anulando a sobra livre de outros itens da mesma NE.")
    colunas[3].metric("Reforço até dezembro", brl(por_empenho["reforco_ate_dezembro"].sum()),
                      help="Por empenho: DDP do mês + projeção dos meses seguintes − saldo a liquidar, quando positivo.")

    st.markdown("**Reforço por empenho**")
    st.dataframe(tabela_por_empenho(por_empenho), hide_index=True, width="stretch", height="content")

    plano = plano_operacoes(itens)
    st.markdown("**Plano de anulação e reforço por item**")
    st.caption(
        "Em cada empenho, o item com maior falta recebe primeiro, da maior sobra livre; o que a sobra não cobre é "
        "reforço novo. Nenhum item cede mais que a sobra livre, então todos mantêm a reserva dos meses seguintes. "
        "Em linhas com dois empenhos (ex.: “NE000040 + NE000166”), escolha em qual deles reforçar."
    )
    if plano.empty:
        st.info("Nenhum item precisa de anulação ou reforço para esta folha.")
    else:
        st.dataframe(tabela_plano(plano, itens), hide_index=True, width="stretch", height="content")
    st.download_button(
        "Baixar em Excel (plano, por empenho, itens e conferência)",
        planilha_excel(competencia, conf, plano, por_empenho, itens),
        file_name=f"reforco_folha_{competencia}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dp_ddp_excel",
    )
    with st.expander("Detalhe por item (NE × natureza detalhada)"):
        st.dataframe(tabela_itens(itens), hide_index=True, width="stretch", height="content")
    with st.expander(f"DDP × Liquidada no mês ({_mes(competencia)})"):
        st.markdown(
            "Com a folha já liquidada, a diferença é o que a liquidação não reproduziu (em set/2026: reposição ao "
            "erário nas pensões, cota-parte na creche, e diferenças ainda sem explicação em vencimentos, "
            "gratificação e auxílio-alimentação). Antes da liquidação, a coluna da base mostra só o que já entrou."
        )
        st.dataframe(tabela_confronto(confronto), hide_index=True, width="stretch", height="content")

    st.caption(_md(
        "Como o reforço é calculado: saldo a liquidar = Empenhado − Liquidado do exercício, por item (NE × natureza "
        "detalhada), só nos empenhos cujo favorecido é a própria UG (os pagamentos diretos a operadoras ficam de fora). "
        "Falta = DDP − saldo. Sobra livre = saldo − DDP − reserva dos meses seguintes (projeção do painel com as "
        "fórmulas da sessão, sem as edições manuais; se a natureza também tem empenhos fora da folha, DDP × meses "
        "restantes). A falta de um item é compensada pela sobra livre de outro item da mesma NE — prática informada, "
        "não confirmada no SIAFI. Natureza em mais de um empenho: repartida pelo Liquidado do mês anterior; sem ele, "
        "os empenhos são somados. A DDP de servidor não separa ativo × aposentado no per capita. A contribuição "
        "patronal ao RPPS não está na DDP. " + procedencia
    ))
