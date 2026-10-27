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
    SEM_ACAO, TIPO_DDP, acoes_dos_quadros, conciliacao_por_acao, conciliacao_sem_ddp, conferencia, confronto_liquidado, ddp_por_natureza,
    ler_relatorio, plano_operacoes, quadro_reforco, quadro_sem_ddp, reforco_por_acao_po, reserva_projetada,
    separar_competencias, validar_conjunto, variacao_por_natureza,
)
from src.ddp_siape_arquivos import (
    ArquivoGuardadoInvalido, carregar as carregar_guardada, competencias_com_ddp, competencias_guardadas, guardar,
    historico, manifesto_atual,
)
from src.despesas_pessoal import ACOES_ESCOPO, GRUPO_RPPS, MESES_NOMES, dotacao_atualizada_por_acao_e_po
from src.ui_despesas_pessoal_abas import _md, brl


def _mes(ano_mes: int | None) -> str:
    return "—" if ano_mes is None else f"{MESES_NOMES[ano_mes % 100 - 1].lower()}/{ano_mes // 100}"


mes_ano = _mes


def aviso_ddp_aplicada(resultado, erro: str | None, ano_mes_referencia: int) -> tuple[str, str] | None:
    """(nível do `st.*`, texto) do aviso do painel sobre a DDP guardada; `None` se não há o que dizer."""
    if erro:
        return "error", f"A DDP guardada não pôde ser lida ({erro}) e não foi usada no painel."
    if resultado.competencia is None:
        return None
    mes = _mes(resultado.competencia)
    if not resultado.aplicada:
        return "info", f"DDP de {mes} guardada: {resultado.motivo}"
    if ano_mes_referencia != resultado.competencia:
        return None
    texto = (
        f"{mes} está com os valores da DDP do SIAPE ({brl(resultado.total_no_painel)}), ainda não liquidados; novembro "
        f"em diante é projetado a partir dela. Naturezas que a DDP não traz (RPPS patronal e outras) seguem pela "
        f"projeção. Assim que a liquidação de {mes} fechar na Execução Mensal, ela passa a valer no lugar da DDP."
    )
    if resultado.liquidado_parcial_substituido:
        texto += (f" Liquidação parcial já lançada no mês e substituída por esses valores: "
                  f"{brl(resultado.liquidado_parcial_substituido)}.")
    if resultado.sem_destino:
        texto += " Sem linha de empenho para distribuir, não entraram no painel: " + "; ".join(
            f"{n} ({brl(v)})" for n, v in resultado.sem_destino) + "."
        return "warning", _md(texto)
    return "info", _md(texto)


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


def render_rpps(itens: pd.DataFrame, por_empenho: pd.DataFrame, conciliacao: dict, competencia: int) -> None:
    """Contribuição patronal ao RPPS (27/10/2026): não está na DDP; o mês vem da projeção do painel."""
    st.markdown("**RPPS patronal — pela projeção do painel, sem DDP**")
    if itens.empty:
        st.info("A projeção do painel não tem o grupo RPPS neste exercício.")
        return
    colunas = st.columns(4)
    colunas[0].metric(f"Projeção de {_mes(competencia)}", brl(itens["ddp"].sum()))
    colunas[1].metric("Saldo a liquidar", brl(itens["saldo"].sum()))
    colunas[2].metric("Reforço do mês", brl(por_empenho["reforco_mes"].sum()))
    colunas[3].metric("Reforço até dezembro", brl(por_empenho["reforco_ate_dezembro"].sum()))
    st.dataframe(tabela_itens(itens).drop(columns=["Já liquidado no mês"]).rename(columns={"DDP do mês": "Projeção do mês"}),
                 hide_index=True, width="stretch", height="content")
    c = conciliacao
    if c["dotacao"] is not None:
        st.caption(_md(
            f"Fecha com o painel: reforço até dezembro {brl(c['reforco_ate_dezembro'])} = déficit de dotação do grupo "
            f"{brl(c['deficit_dotacao'])} (projetado no ano {brl(c['total_ano'])} − dotação {brl(c['dotacao'])}) + dotação "
            f"ainda não empenhada {brl(c['dotacao_nao_empenhada'])} + diferença entre o Liquidado da base e a grade nos "
            f"meses anteriores {brl(c['diferenca_meses_anteriores'])}."
        ))
    st.caption(
        "O valor do mês é a projeção do painel (fórmulas da sessão, sem as edições manuais), não um documento do "
        "SIAPE — não há o que conferir. A reserva inclui o 13º de novembro. Se o patronal de algum mês for liquidado "
        "em outro mês, a diferença aparece na conciliação acima; nenhuma regra é presumida."
    )


def tabela_acao_po(tabela: pd.DataFrame) -> pd.DataFrame:
    def situacao(v):
        if v is None or pd.isna(v):
            return "Sem dotação na base"
        return "Não cabe" if round(v, 2) < 0 else "Cabe"
    return pd.DataFrame({
        "Ação": tabela["acao_cod"], "PO": tabela["po_cod"].replace("", "—"),
        "Dotação atualizada": tabela["dotacao"].map(brl), "Empenhado": tabela["empenhado"].map(brl),
        "Disponível para empenhar": tabela["disponivel"].map(brl), "Reforço do mês": tabela["reforco_mes"].map(brl),
        "Reforço até dezembro": tabela["reforco_ate_dezembro"].map(brl),
        "Disponível − reforço": tabela["saldo_apos_reforco"].map(brl), "Situação": tabela["saldo_apos_reforco"].map(situacao),
        "Sobra nos empenhos do quadro": tabela["sobra_empenhos"].map(brl), "Empenhos com reforço": tabela["empenhos"],
    })


def render_acao_po(tabela: pd.DataFrame, ano_dotacao: int) -> None:
    """O reforço cabe na dotação de cada Ação/PO? (27/10/2026)"""
    st.markdown("**O reforço cabe na dotação?**")
    nao_cabe = tabela.loc[tabela["saldo_apos_reforco"].round(2) < 0]
    if not nao_cabe.empty:
        st.warning(_md("Reforço até dezembro maior que a dotação ainda não empenhada em: " + "; ".join(
            f"{r.acao_cod}/{r.po_cod} (falta {brl(-r.saldo_apos_reforco)})" for r in nao_cabe.itertuples()) + "."))
    st.dataframe(tabela_acao_po(tabela), hide_index=True, width="stretch", height="content")
    st.caption(_md(
        f"Disponível = Dotação Atualizada de {ano_dotacao} − tudo o que já foi empenhado na Ação/PO no exercício (todos "
        "os empenhos, inclusive os fora da folha). Entram só os reforços dos quadros desta aba (DDP e RPPS): outras "
        "despesas da mesma ação que ainda precisem de empenho não estão aqui, e por isso a conta pode diferir do saldo "
        "do painel. “Sobra nos empenhos do quadro” é o que ficaria em dezembro nos empenhos com folga e poderia ser "
        "anulado para liberar dotação na mesma Ação/PO. Nenhum remanejamento entre ações ou POs é presumido. "
        f"“{SEM_ACAO}”: empenho agrupado com Ação/PO diferentes, ou natureza sem empenho."
    ))


_NOMES_GRUPO = {"ativo": "Ativo", "inativo": "Inativo", "rpps": "RPPS", "outros_beneficios": "Outros Benefícios"}


def tabela_conciliacao(conc: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Ação": conc["acao_cod"], "Grupo": conc["grupo"].map(_NOMES_GRUPO),
        "Saldo no painel": conc["saldo_painel"].map(brl),
        "+ Projeção do painel fora do quadro": conc["projecao_fora"].map(brl),
        "+ Executado do painel fora dos empenhos do quadro": conc["executado_fora"].map(brl),
        "− Empenhado fora dos quadros": conc["empenhado_fora"].map(brl),
        "− Sobra nos empenhos do quadro": conc["sobras"].map(brl),
        "= Saldo no quadro (disponível − reforço)": conc["saldo_quadro"].map(brl),
        "Diferença não explicada": conc["diferenca"].map(brl),
    })


def render_conciliacao(conc: pd.DataFrame) -> None:
    """Ponte entre o saldo do quadro por ação e o saldo do painel (27/10/2026)."""
    st.markdown("**Do saldo do painel ao saldo do quadro, por ação**")
    st.dataframe(tabela_conciliacao(conc), hide_index=True, width="stretch", height="content")
    fora = conc["diferenca"].dropna().abs().max() if conc["diferenca"].notna().any() else 0.0
    if fora >= 0.005:
        st.warning(f"Há diferença não explicada de até {brl(fora)} entre o painel e o quadro: confira antes de usar.")
    sem = conc.attrs.get("naturezas_sem_acao", 0)
    st.caption(_md(
        "Saldo do quadro = dotação − empenhado na ação − reforço até dezembro dos empenhos do quadro. Saldo do painel = "
        "dotação − total do ano projetado. A diferença entre os dois é a soma das parcelas: projeção do painel que o "
        "quadro não cobre (naturezas sem empenho de folha, diferença entre DDP e projeção), executado que não passou "
        "pelos empenhos do quadro, empenhado em outras notas da ação e sobra dos empenhos com folga. Outros Benefícios "
        "é aberto por ação (2004/212B) pela ação em que cada natureza é executada; projeção padrão, sem as edições "
        "manuais. Ação sem dotação na base fica em branco."
        + (f" {sem} linha(s) da projeção sem ação única ficaram fora." if sem else "")
    ))


def planilha_excel(competencia: int, conf: pd.DataFrame, plano: pd.DataFrame, por_empenho: pd.DataFrame,
                   itens: pd.DataFrame, itens_rpps: pd.DataFrame | None = None,
                   acao_po: pd.DataFrame | None = None, conciliacao: pd.DataFrame | None = None) -> bytes:
    """Planilha para download (gerada em memória, nada é gravado no servidor), com os valores numéricos."""
    arquivo = BytesIO()
    with pd.ExcelWriter(arquivo, engine="openpyxl") as escritor:
        plano.to_excel(escritor, sheet_name="Plano por item", index=False)
        por_empenho.to_excel(escritor, sheet_name="Por empenho", index=False)
        itens.drop(columns=["nes"]).to_excel(escritor, sheet_name="Itens", index=False)
        if itens_rpps is not None and not itens_rpps.empty:
            itens_rpps.drop(columns=["nes"]).rename(columns={"ddp": "projecao_mes"}).to_excel(
                escritor, sheet_name="RPPS (projeção)", index=False)
        if acao_po is not None and not acao_po.empty:
            acao_po.to_excel(escritor, sheet_name="Por ação e PO", index=False)
        if conciliacao is not None and not conciliacao.empty:
            conciliacao.to_excel(escritor, sheet_name="Painel × quadro", index=False)
        conf.to_excel(escritor, sheet_name="Conferência", index=False)
        pd.DataFrame({"competencia": [competencia]}).to_excel(escritor, sheet_name="Referência", index=False)
    return arquivo.getvalue()


def tabela_guardadas(competencias: list[int], diretorio_manifestos=None) -> pd.DataFrame:
    """Uma linha por PDF da versão atual de cada competência guardada, mais a contagem de versões."""
    linhas = []
    for c in reversed(competencias):
        manifesto = manifesto_atual(c, diretorio_manifestos)
        versoes = len(historico(c, diretorio_manifestos))
        for a in manifesto["arquivos"]:
            linhas.append({
                "Competência": _mes(c), "Tipo": a["tipo"], "Público": a["publico"].title(), "Gerado em": a["data_geracao"] or "—",
                "Arquivo enviado": a["nome_original"], "Hash": a["sha256"][:8], "Guardado em": manifesto["gravado_em"][:16].replace("T", " "),
                "Versões da competência": versoes,
            })
    return pd.DataFrame(linhas)


def render_guardadas(competencias: list[int]) -> None:
    with st.expander(f"DDPs guardadas ({', '.join(_mes(c) for c in reversed(competencias))})"):
        st.dataframe(tabela_guardadas(competencias), hide_index=True, width="stretch", height="content")
        st.caption(
            "Reenviar um PDF diferente para o mesmo tipo, público e competência cria uma versão nova; o PDF e o "
            "manifesto anteriores ficam preservados. Os arquivos estão em `data/raw/ddp_siape/` e os manifestos em "
            "`data/manifestos/`."
        )


def render_ddp(mensal: pd.DataFrame, grade_linhas: pd.DataFrame, ano_grade: int, procedencia: str,
               dotacao_grupo: pd.Series | None = None, dotacao_df: pd.DataFrame | None = None,
               ano_dotacao: int | None = None) -> None:
    """`grade_linhas`: `grade_mensal(...).linhas` do painel (projeção por natureza
    detalhada, com as fórmulas da sessão), usada para a reserva dos meses seguintes e para o
    mês do RPPS patronal. `dotacao_grupo`: dotação por grupo, para fechar o RPPS com o painel.
    `dotacao_df`/`ano_dotacao`: Dotação Anual e exercício do painel, para o quadro por Ação/PO."""
    st.markdown(
        "Envie os PDFs do SIAPE do mês: **DDP** e **Crédito Bancário**, de servidor e de pensionista. Eles ficam "
        "**guardados** (cópia sem alteração em `data/raw/ddp_siape/`, fora do git, com manifesto versionado): não é "
        "preciso enviar de novo. O painel usa a DDP do mês até a liquidação aparecer na Execução Mensal; a aba confere "
        "os totais e calcula, por empenho, quanto falta para liquidar a folha."
    )
    arquivos = st.file_uploader("PDFs do SIAPE", type="pdf", accept_multiple_files=True, key="dp_ddp_pdfs",
                                label_visibility="collapsed")
    if arquivos:
        recebidos = []
        for arquivo in arquivos:
            conteudo = arquivo.getvalue()
            try:
                recebidos.append((ler_relatorio(conteudo, arquivo.name), conteudo))
            except ValueError as erro:
                st.error(str(erro))
        erros = validar_conjunto([r for r, _ in recebidos], competencias_com_ddp=competencias_com_ddp()) if recebidos else []
        for erro in erros:
            st.error(erro)
        if recebidos and not erros:
            guarda = guardar(recebidos)
            if guarda.versoes_novas:
                st.session_state["dp_ddp_msg"] = ("Guardado: " + ", ".join(_mes(c) for c in guarda.versoes_novas)
                                                  + ". O painel já usa a DDP guardada.")
                st.rerun()  # o painel (montado antes desta aba) precisa reler a DDP guardada
            elif guarda.sem_mudanca:
                st.caption("Estes PDFs já estavam guardados, sem alteração: " + ", ".join(_mes(c) for c in guarda.sem_mudanca) + ".")
    mensagem = st.session_state.pop("dp_ddp_msg", None)
    if mensagem:
        st.success(mensagem)

    guardadas = competencias_guardadas()
    if not guardadas:
        st.info("Nenhuma DDP guardada ainda. Envie os PDFs acima.")
        return
    render_guardadas(guardadas)
    escolhida = guardadas[-1] if len(guardadas) == 1 else st.selectbox(
        "Competência analisada", list(reversed(guardadas)), format_func=_mes, key="dp_ddp_competencia")
    anterior_guardada = max((c for c in guardadas if c < escolhida), default=None)
    try:
        relatorios = carregar_guardada(escolhida) + (carregar_guardada(anterior_guardada) if anterior_guardada else [])
    except ArquivoGuardadoInvalido as erro:
        st.error(f"Não foi possível ler a DDP guardada: {erro}")
        return

    atuais, anteriores = separar_competencias(relatorios)
    ddp = next((r for r in atuais if r.tipo == TIPO_DDP), None)
    if ddp is None:
        st.warning(f"A competência {_mes(escolhida)} tem só o Crédito Bancário guardado; envie a DDP para analisar.")
        return
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

    itens_rpps, por_empenho_rpps = quadro_sem_ddp(mensal, competencia, grade_linhas, GRUPO_RPPS)
    dotacao_rpps = None if dotacao_grupo is None else dotacao_grupo.get(GRUPO_RPPS)
    render_rpps(itens_rpps, por_empenho_rpps,
                conciliacao_sem_ddp(itens_rpps, grade_linhas, GRUPO_RPPS, competencia, dotacao_rpps), competencia)

    acao_po = conciliacao = None
    if dotacao_df is not None and ano_dotacao is not None:
        quadros = [(itens, por_empenho), (itens_rpps, por_empenho_rpps)]
        acoes = acoes_dos_quadros(quadros, mensal, competencia // 100) | set(ACOES_ESCOPO)
        dotacao_acao_po = dotacao_atualizada_por_acao_e_po(dotacao_df, ano_dotacao, acoes)
        acao_po = reforco_por_acao_po(quadros, mensal, competencia // 100, dotacao_acao_po)
        render_acao_po(acao_po, ano_dotacao)
        conciliacao = conciliacao_por_acao(quadros, mensal, competencia, grade_linhas, dotacao_acao_po)
        render_conciliacao(conciliacao)

    st.download_button(
        "Baixar em Excel (plano, por empenho, itens, RPPS, ação/PO, painel × quadro e conferência)",
        planilha_excel(competencia, conf, plano, por_empenho, itens, itens_rpps, acao_po, conciliacao),
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
        "patronal ao RPPS não está na DDP: tem quadro próprio, pela projeção, fora dos totais da DDP. " + procedencia
    ))
