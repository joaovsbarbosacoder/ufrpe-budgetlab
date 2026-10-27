"""Aba "Folha (DDP)" da página Acompanhamento de Pessoal (27/10/2026).

O usuário envia os PDFs do SIAPE (DDP e Crédito Bancário, de servidor e de pensionista);
a aba mostra a conferência dos totais, o reforço por empenho e o confronto com a Liquidada
da base. Os PDFs ficam só na memória da sessão — nada é gravado (AGENTS.md). Nenhum
cálculo financeiro mora aqui: tudo vem de `src.ddp_siape`.
"""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from src.ddp_siape import (
    OPERACAO_REMANEJAR, SEM_ACAO, TIPO_DDP, acoes_dos_quadros, conciliacao_por_acao, conciliacao_sem_ddp, conferencia, confronto_liquidado, ddp_por_natureza,
    ler_relatorio, plano_operacoes, quadro_reforco, quadro_sem_ddp, reforco_por_acao_po, reserva_projetada,
    separar_competencias, validar_conjunto, variacao_por_natureza,
)
from src.ddp_siape import por_empenho_somente_reforco
from src import ui_cartoes as cd
from src.ddp_siape_relatorio import CRITERIOS, OPERACOES, DadosRelatorio, _nota_empenho, relatorio_excel
from src.ddp_siape_arquivos import (
    ArquivoGuardadoInvalido, carregar as carregar_guardada, competencias_com_ddp, competencias_guardadas, guardar,
    historico, manifesto_atual, remover, validar_troca,
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
        "Saldo do empenho (empenhado − liquidado)": por_empenho["saldo"].map(brl), "Folha do mês (DDP)": por_empenho["ddp"].map(brl),
        "Falta para pagar a folha do mês": por_empenho["falta"].map(brl), "Sobra que pode ser anulada": por_empenho["sobra_livre"].map(brl),
        "Coberto por remanejamento dentro do empenho": por_empenho["compensa"].map(brl), "Reforço necessário para o mês": por_empenho["reforco_mes"].map(brl),
        "Reforço necessário até dezembro": por_empenho["reforco_ate_dezembro"].map(brl),
    })


def tabela_itens(itens: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Empenho": itens["empenho"], "Natureza": itens["natureza_detalhada"], "Descrição": itens["descricao"].fillna("—"),
        "Saldo do empenho (empenhado − liquidado)": itens["saldo"].map(brl), "Folha do mês (DDP)": itens["ddp"].map(brl), "Falta para pagar a folha do mês": itens["falta"].map(brl),
        "Necessidade de nov e dez (projeção)": itens["reserva"].map(brl), "Sobra que pode ser anulada": itens["sobra_livre"].map(brl),
        "Sobra (+) ou falta (−) em dezembro": itens["saldo_apos_ano"].map(brl), "Como a folha foi atribuída ao empenho": itens["criterio"].map(lambda c: CRITERIOS.get(c, c)),
        "Base da necessidade de nov e dez": itens["tipo_reserva"], "Já liquidado no mês": itens["liquidado_no_mes"].map(brl),
    })


def tabela_confronto(confronto: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Natureza": confronto["natureza_detalhada"], "Descrição na DDP": confronto["descricao"],
        "DDP líquida": confronto["ddp"].map(brl), "Liquidado na base": confronto["liquidado_no_mes"].map(brl),
        "Diferença (liquidado − DDP)": confronto["diferenca"].map(brl),
    })


def tabela_plano(plano: pd.DataFrame, itens: pd.DataFrame) -> pd.DataFrame:
    descricao = itens.dropna(subset=["descricao"]).drop_duplicates("natureza_detalhada").set_index("natureza_detalhada")["descricao"]
    rotulo = lambda n: "—" if n is None or pd.isna(n) else f"{n} {descricao.get(n, '')}".strip()
    return pd.DataFrame({
        "Empenho": plano["empenho"], "Operação": plano["operacao"].map(OPERACOES),
        "Item que cede (anular)": plano["item_origem"].map(rotulo), "Item que recebe (reforçar)": plano["item_destino"].map(rotulo),
        "Valor": plano["valor"].map(brl),
    })


_SITUACOES = {"nova": "Nova", "saiu": "Não veio neste mês", "alta": "Alta", "queda": "Queda", "sem variação": "Sem variação"}


def tabela_variacao(variacao: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Natureza": variacao["natureza_detalhada"], "Descrição na DDP": variacao["descricao"].fillna("—"),
        "Mês anterior": variacao["anterior"].map(brl), "Mês atual": variacao["atual"].map(brl),
        "Variação": variacao["variacao"].map(brl), "Situação": variacao["situacao"].map(_SITUACOES),
    })


def cartoes_plano(plano: pd.DataFrame, itens: pd.DataFrame) -> list[str]:
    descricao = (itens.dropna(subset=["descricao"]).drop_duplicates("natureza_detalhada").set_index("natureza_detalhada")["descricao"].to_dict()
                 if len(itens) else {})
    notas = {e: _nota_empenho(n) for e, n in itens.groupby("empenho")["nes"].first().items()} if len(itens) else {}
    acoes = itens.groupby("empenho")["acao_cod"].first().to_dict() if len(itens) else {}
    cartoes = []
    for empenho, grupo in plano.groupby("empenho", sort=False):
        cartoes.append(cd.cartao_operacoes(notas.get(empenho, empenho), acoes.get(empenho) if isinstance(acoes.get(empenho), str) else None, [
            {"tipo": "remanejar" if o.operacao == OPERACAO_REMANEJAR else "reforco", "de": o.item_origem, "de_desc": descricao.get(o.item_origem),
             "para": o.item_destino, "para_desc": descricao.get(o.item_destino), "valor": o.valor} for o in grupo.itertuples()]))
    return cartoes


def cartoes_conferencia(conf: pd.DataFrame) -> list[str]:
    cartoes = []
    for _, linha in conf.iterrows():
        situacao = _situacao(linha)
        problemas = situacao.removeprefix("Diferença — ").split("; ") if situacao.startswith("Diferença") else []
        curto = ("Confere" if situacao == "Confere" else "Confere (crédito bancário não enviado)" if situacao.startswith("Confere")
                 else "Há diferença")
        cartoes.append(cd.cartao_conferencia(linha["publico"].title(), f"{_mes(linha['competencia'])} · {linha['folha'].title()}", linha["bruto"],
                                             linha["desconto"], linha["liquido"], linha["credito_bancario"], curto, problemas))
    return cartoes


def render_variacao(variacao: pd.DataFrame, anterior: int, atual: int) -> None:
    """O que mudou na DDP entre as duas competências enviadas (27/10/2026)."""
    total_anterior, total_atual = variacao["anterior"].sum(), variacao["atual"].sum()
    delta = total_atual - total_anterior
    st.html(cd.secao(f"O que mudou de {_mes(anterior)} para {_mes(atual)}", "Maiores variações da DDP líquida por natureza (servidor + pensionista). "
                     "Barra para a direita: a folha subiu; para a esquerda: caiu.") + cd.kpis([
        {"rotulo": f"DDP líquida de {_mes(anterior)}", "valor": brl(total_anterior), "tom": "cinza"},
        {"rotulo": f"DDP líquida de {_mes(atual)}", "valor": brl(total_atual)},
        {"rotulo": "Variação", "valor": brl(delta), "tom": "vermelho" if delta > 0 else "verde",
         "sub": f"{(total_atual / total_anterior - 1):+.1%}".replace(".", ",") if total_anterior else None},
    ]))
    novas = variacao.loc[variacao["situacao"] == "nova"]
    sairam = variacao.loc[variacao["situacao"] == "saiu"]
    if not novas.empty:
        st.caption(_md("Naturezas novas: " + "; ".join(f"{r.natureza_detalhada} {r.descricao} ({brl(r.atual)})" for r in novas.itertuples()) + "."))
    if not sairam.empty:
        st.caption(_md("Não vieram neste mês: " + "; ".join(
            f"{r.natureza_detalhada} {r.descricao} ({brl(r.anterior)} no anterior)" for r in sairam.itertuples()) + "."))
    mudaram = variacao.loc[variacao["variacao"] != 0].head(10)
    st.html('<div class="cd-card" style="--c:#0969DA">' + cd.barras_divergentes([
        {"nome": f"{r.natureza_detalhada} {r.descricao or ''}".strip(), "valor": r.variacao,
         "detalhe": f"{brl(r.anterior)} → {brl(r.atual)} · {_SITUACOES.get(r.situacao, r.situacao)}"} for r in mudaram.itertuples()
    ]) + "</div>")
    with st.expander(f"Todas as naturezas ({len(variacao)})"):
        st.dataframe(tabela_variacao(variacao), hide_index=True, width="stretch", height="content")


def _itens_do_cartao(itens: pd.DataFrame, empenho: str) -> list[dict]:
    do_empenho = itens.loc[itens["empenho"] == empenho]
    return [{"natureza": r.natureza_detalhada, "descricao": r.descricao, "folha": r.ddp, "falta": r.falta, "sobra": r.sobra_livre}
            for r in do_empenho.itertuples()]


def cartoes_empenhos(por_empenho: pd.DataFrame, itens: pd.DataFrame, mes: str, ano: int, origem: str | None = None) -> list[str]:
    """Um cartão por empenho, do que mais precisa de reforço para o que menos precisa."""
    notas = {e: _nota_empenho(n) for e, n in itens.groupby("empenho")["nes"].first().items()} if len(itens) else {}
    return [cd.cartao_empenho(notas.get(r.empenho, r.empenho), r.acao_cod if isinstance(r.acao_cod, str) else None, r.saldo, r.ddp,
                              r.falta, r.sobra_livre, r.compensa, r.reforco_mes, r.reforco_ate_dezembro,
                              _itens_do_cartao(itens, r.empenho), mes, ano, origem)
            for r in por_empenho.itertuples()]


def render_rpps(itens: pd.DataFrame, por_empenho: pd.DataFrame, conciliacao: dict, competencia: int) -> None:
    """Contribuição patronal ao RPPS (27/10/2026): não está na DDP; o mês vem da projeção do painel."""
    mes, ano = _mes(competencia), competencia // 100
    st.html(cd.secao("RPPS patronal — pela projeção do painel, sem DDP",
                     "A contribuição patronal não vem na DDP: o valor do mês e a necessidade de nov e dez são a projeção do painel "
                     "(acompanhando vencimentos + gratificação do Ativo), sem as edições manuais."))
    if itens.empty:
        st.info("A projeção do painel não tem o grupo RPPS neste exercício.")
        return
    st.html(cd.kpis([
        {"rotulo": f"Projeção de {mes}", "valor": brl(itens["ddp"].sum())}, {"rotulo": "Saldo do empenho", "valor": brl(itens["saldo"].sum()), "tom": "cinza"},
        {"rotulo": "Reforço necessário para o mês", "valor": brl(por_empenho["reforco_mes"].sum()), "tom": "laranja"},
        {"rotulo": "Reforço necessário até dezembro", "valor": brl(por_empenho["reforco_ate_dezembro"].sum()), "tom": "vermelho"},
    ]) + cd.grade(cartoes_empenhos(por_empenho, itens, mes, ano, f"RPPS patronal — folha de {mes} pela projeção")))
    c = conciliacao
    if c["dotacao"] is not None:
        st.caption(_md(
            f"Fecha com o painel: reforço até dezembro {brl(c['reforco_ate_dezembro'])} = déficit de dotação do grupo "
            f"{brl(c['deficit_dotacao'])} (projetado no ano {brl(c['total_ano'])} − dotação {brl(c['dotacao'])}) + dotação "
            f"ainda não empenhada {brl(c['dotacao_nao_empenhada'])} + diferença entre o liquidado da base e a grade nos "
            f"meses anteriores {brl(c['diferenca_meses_anteriores'])}."))


def tabela_acao_po(tabela: pd.DataFrame) -> pd.DataFrame:
    def situacao(v):
        if v is None or pd.isna(v):
            return "Sem dotação na base"
        return "Não cabe" if round(v, 2) < 0 else "Cabe"
    return pd.DataFrame({
        "Ação": tabela["acao_cod"], "PO": tabela["po_cod"].replace("", "—"),
        "Dotação atualizada": tabela["dotacao"].map(brl), "Empenhado": tabela["empenhado"].map(brl),
        "Dotação ainda não empenhada": tabela["disponivel"].map(brl), "Reforço necessário para o mês": tabela["reforco_mes"].map(brl),
        "Reforço necessário até dezembro": tabela["reforco_ate_dezembro"].map(brl),
        "Sobra (+) ou falta (−) de dotação após o reforço": tabela["saldo_apos_reforco"].map(brl), "Situação": tabela["saldo_apos_reforco"].map(situacao),
        "Sobra prevista em dezembro nos empenhos": tabela["sobra_empenhos"].map(brl), "Notas de empenho que precisam de reforço": tabela["empenhos"],
    })


def render_acao_po(tabela: pd.DataFrame, ano_dotacao: int) -> None:
    """O reforço cabe na dotação de cada Ação/PO? (27/10/2026)"""
    st.html(cd.secao("O reforço cabe na dotação?", f"Dotação Atualizada de {ano_dotacao} menos tudo o que já foi empenhado na Ação/PO no exercício "
                     "(inclusive empenhos fora da folha). Entram só os reforços desta aba (DDP e RPPS). Nenhum remanejamento entre ações ou "
                     f"POs é presumido. “{SEM_ACAO}”: empenho agrupado com Ação/PO diferentes, ou natureza sem empenho."))
    nao_cabe = tabela.loc[tabela["saldo_apos_reforco"].round(2) < 0]
    if not nao_cabe.empty:
        st.warning(_md("Reforço até dezembro maior que a dotação ainda não empenhada em: " + "; ".join(
            f"{r.acao_cod}/{r.po_cod} (falta {brl(-r.saldo_apos_reforco)})" for r in nao_cabe.itertuples()) + "."))
    st.html(cd.grade([cd.cartao_dotacao(r.acao_cod, r.po_cod, r.dotacao, r.empenhado, r.disponivel, r.reforco_mes, r.reforco_ate_dezembro,
                                        r.saldo_apos_reforco, r.sobra_empenhos, r.empenhos) for r in tabela.itertuples()]))


_NOMES_GRUPO = {"ativo": "Ativo", "inativo": "Inativo", "rpps": "RPPS", "outros_beneficios": "Outros Benefícios"}


def tabela_conciliacao(conc: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Ação": conc["acao_cod"], "Grupo": conc["grupo"].map(_NOMES_GRUPO),
        "Saldo da dotação pela projeção do painel": conc["saldo_painel"].map(brl),
        "+ Despesa projetada fora dos empenhos da folha": conc["projecao_fora"].map(brl),
        "+ Já liquidado por outras notas da ação": conc["executado_fora"].map(brl),
        "− Empenhado em outras notas da ação": conc["empenhado_fora"].map(brl),
        "− Sobra prevista nos empenhos da folha": conc["sobras"].map(brl),
        "= Saldo da dotação após os reforços": conc["saldo_quadro"].map(brl),
        "Diferença (deve ser zero)": conc["diferenca"].map(brl),
    })


def render_conciliacao(conc: pd.DataFrame) -> None:
    """Ponte entre o saldo do relatório por ação e o saldo do painel (27/10/2026)."""
    st.html(cd.secao("Conciliação com o painel, por ação",
                     "Por que o saldo deste relatório (dotação − empenhado − reforço) difere do saldo do painel (dotação − despesa projetada "
                     "no ano): a soma das parcelas explica a diferença, que deve ser zero. Outros Benefícios é aberto por ação (2004/212B); "
                     "projeção padrão, sem as edições manuais."))
    fora = conc["diferenca"].dropna().abs().max() if conc["diferenca"].notna().any() else 0.0
    if fora >= 0.005:
        st.warning(f"Há diferença não explicada de até {brl(fora)} entre o painel e o relatório: confira antes de usar.")
    st.html(cd.grade([cd.cartao_conciliacao(r.acao_cod, _NOMES_GRUPO.get(r.grupo, r.grupo), [
        ("Saldo da dotação pela projeção do painel", r.saldo_painel, "normal"),
        ("+ Despesa projetada fora dos empenhos da folha", r.projecao_fora, "normal"),
        ("+ Já liquidado por outras notas da ação", r.executado_fora, "normal"),
        ("− Empenhado em outras notas da ação", r.empenhado_fora, "normal"),
        ("− Sobra prevista nos empenhos da folha", r.sobras, "normal"),
        ("= Saldo da dotação após os reforços", r.saldo_quadro, "total"),
    ], r.diferenca) for r in conc.itertuples()]))
    sem = conc.attrs.get("naturezas_sem_acao", 0)
    if sem:
        st.caption(f"{sem} linha(s) da projeção sem ação única ficaram fora.")


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
        render_troca(competencias)


def render_troca(competencias: list[int]) -> None:
    """Troca explícita de um PDF guardado por outro da mesma competência, tipo, público e folha."""
    st.markdown("**Trocar um arquivo guardado**")
    opcoes = [(c, a) for c in reversed(competencias) for a in manifesto_atual(c)["arquivos"]]
    rotulo = lambda par: (f"{_mes(par[0])} · {par[1]['tipo']} · {par[1]['publico'].title()} · {par[1]['folha'].title()}"
                          f" — {par[1]['nome_original']}")
    escolha = st.selectbox("Arquivo a trocar", opcoes, format_func=rotulo, key="dp_ddp_troca_alvo")
    # chave com contador: após a troca o envio volta vazio (um widget não pode ser limpo por código)
    if escolha is not None:
        with st.expander("Apagar este arquivo"):
            st.caption(
                "O arquivo deixa de valer para o painel e para a aba. Por rastreabilidade, o PDF e o manifesto "
                "anteriores continuam em `data/raw/ddp_siape/` e `data/manifestos/` (a versão anterior fica no histórico)."
            )
            if st.checkbox("Confirmo que quero apagar este arquivo", key=f"dp_ddp_apagar_ok_{st.session_state.get('dp_ddp_troca_n', 0)}"):
                if st.button("Apagar", key="dp_ddp_apagar"):
                    c, a = escolha
                    remover(c, a["tipo"], a["publico"], a["folha"])
                    st.session_state["dp_ddp_troca_n"] = st.session_state.get("dp_ddp_troca_n", 0) + 1
                    st.session_state["dp_ddp_msg"] = f"Arquivo apagado de {_mes(c)}: {a['nome_original']}. O painel deixa de usá-lo."
                    st.rerun()
    novo = st.file_uploader("PDF substituto", type="pdf", key=f"dp_ddp_troca_pdf_{st.session_state.get('dp_ddp_troca_n', 0)}")
    if not novo or escolha is None:
        return
    competencia, entrada = escolha
    conteudo = novo.getvalue()
    try:
        relatorio = ler_relatorio(conteudo, novo.name)
    except ValueError as erro:
        st.error(str(erro))
        return
    erros = validar_troca(entrada, relatorio, conteudo)
    for erro in erros:
        st.error(erro)
    if erros:
        return
    st.info(f"Será trocado: **{entrada['nome_original']}** (hash {entrada['sha256'][:8]}, gerado em {entrada['data_geracao'] or '—'}) "
            f"por **{novo.name}** (hash {hashlib.sha256(conteudo).hexdigest()[:8]}, gerado em "
            f"{relatorio.data_geracao.isoformat() if relatorio.data_geracao else '—'}). O PDF e o manifesto atuais ficam preservados.")
    if st.button("Confirmar troca", type="primary", key="dp_ddp_troca_confirmar"):
        guardar([(relatorio, conteudo)])
        st.session_state["dp_ddp_msg"] = f"Arquivo trocado em {_mes(competencia)}. O painel já usa o novo."
        st.session_state["dp_ddp_troca_n"] = st.session_state.get("dp_ddp_troca_n", 0) + 1
        st.rerun()


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
    st.html(cd.CSS + cd.secao(f"Folha de {_mes(competencia)}",
                              f"Paga em {_mes(ddp.mes_pagamento)}; relatórios gerados em "
                              f"{', '.join(sorted({r.data_geracao.strftime('%d/%m/%Y') for r in atuais if r.data_geracao}))}. "
                              f"DDP de {' e '.join(publicos)}."
                              + (f" Os PDFs de {_mes(anteriores[0].competencia)} entram só na comparação." if anteriores else "")))
    if len(publicos) < 2:
        st.warning("Só foi enviada a DDP de " + publicos[0] + ": o reforço abaixo não inclui a outra folha.")

    conf = conferencia(relatorios)
    st.html(cd.secao("Conferência dos totais", "Bruto − descontos = líquido = crédito bancário.")
            + cd.grade(cartoes_conferencia(conf)))

    natureza = ddp_por_natureza(atuais)
    variacao = None
    if anteriores:
        variacao = variacao_por_natureza(natureza, ddp_por_natureza(anteriores))
        render_variacao(variacao, anteriores[0].competencia, competencia)
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
    total_ddp = float(natureza["despesa"].sum())  # bruto: as despesas a anular não entram na necessidade de reforço
    ja_liquidado = float(confronto["liquidado_no_mes"].sum())
    if ja_liquidado > 0.004:
        st.warning(_md(
            f"A base já tem {brl(ja_liquidado)} liquidados em {_mes(competencia)} nas naturezas da DDP "
            f"({ja_liquidado / total_ddp:.0%} da DDP). O saldo abaixo já desconta esse valor: se for a própria "
            f"folha, o reforço a conta duas vezes — confira em “DDP × Liquidada no mês”."
        ))

    plano = plano_operacoes(itens)
    mes, ano = _mes(competencia), competencia // 100
    st.html(cd.kpis([
        {"rotulo": f"DDP bruta de {mes}", "valor": brl(total_ddp), "sub": "servidor + pensionista, sem abater as despesas a anular", "tom": "cinza"},
        {"rotulo": "Falta para pagar a folha do mês", "valor": brl(por_empenho["falta"].sum()), "sub": "soma dos itens com falta"},
        {"rotulo": f"Reforço necessário para {mes}", "valor": brl(por_empenho["reforco_mes"].sum()), "tom": "laranja",
         "sub": f"depois de remanejar {brl(por_empenho['compensa'].sum())} entre itens do mesmo empenho"},
        {"rotulo": f"Reforço necessário até dez/{ano}", "valor": brl(por_empenho["reforco_ate_dezembro"].sum()), "tom": "vermelho",
         "sub": "folha do mês + necessidade de nov e dez − saldo"},
    ]))

    cartoes = cartoes_empenhos(por_empenho, itens, mes, ano)
    st.html(cd.secao("Reforço por empenho", "Cada nota de empenho da folha, dos que mais precisam de reforço para os que menos precisam. A barra mostra "
                     "quanto da folha do mês o saldo do empenho cobre (verde) e o que falta (vermelho). Abra “Itens do empenho” para ver o detalhe."))
    st.html(cd.grade(cartoes[:12]))
    if len(cartoes) > 12:
        with st.expander(f"Demais empenhos ({len(cartoes) - 12})"):
            st.html(cd.grade(cartoes[12:]))

    st.html(cd.secao("Anulação + reforço, item a item", "Em cada empenho, o item com maior falta recebe primeiro, do item com maior sobra; o que a sobra não "
                     "cobre é reforço novo. Nenhum item cede mais que a sobra livre, então todos mantêm a necessidade de nov e dez. "
                     "Em empenhos agrupados (ex.: “NE000040 + NE000166”), escolha em qual deles reforçar."))
    if plano.empty:
        st.info("Nenhum item precisa de anulação ou reforço para esta folha.")
    else:
        st.html(cd.grade(cartoes_plano(plano, itens)))

    itens_rpps, por_empenho_rpps = quadro_sem_ddp(mensal, competencia, grade_linhas, GRUPO_RPPS)
    dotacao_rpps = None if dotacao_grupo is None else dotacao_grupo.get(GRUPO_RPPS)
    render_rpps(itens_rpps, por_empenho_rpps,
                conciliacao_sem_ddp(itens_rpps, grade_linhas, GRUPO_RPPS, competencia, dotacao_rpps), competencia)

    acao_po = acao_po_somente = conciliacao = None
    if dotacao_df is not None and ano_dotacao is not None:
        quadros = [(itens, por_empenho), (itens_rpps, por_empenho_rpps)]
        acoes = acoes_dos_quadros(quadros, mensal, competencia // 100) | set(ACOES_ESCOPO)
        dotacao_acao_po = dotacao_atualizada_por_acao_e_po(dotacao_df, ano_dotacao, acoes)
        acao_po = reforco_por_acao_po(quadros, mensal, competencia // 100, dotacao_acao_po)
        # cenário sem anulação agora (relatório em Excel): a sobra dos itens com folga continua empenhada
        acao_po_somente = reforco_por_acao_po(
            [(itens, por_empenho_somente_reforco(itens)), (itens_rpps, por_empenho_somente_reforco(itens_rpps))],
            mensal, competencia // 100, dotacao_acao_po)
        render_acao_po(acao_po, ano_dotacao)
        conciliacao = conciliacao_por_acao(quadros, mensal, competencia, grade_linhas, dotacao_acao_po)
        render_conciliacao(conciliacao)

    dados_relatorio = DadosRelatorio(
        competencia=competencia, procedencia=procedencia, conferencia=conf, natureza=natureza, por_empenho=por_empenho,
        itens=itens, plano=plano, confronto=confronto, rpps_itens=itens_rpps, rpps_por_empenho=por_empenho_rpps,
        acao_po=acao_po, acao_po_somente_reforco=acao_po_somente, conciliacao=conciliacao, ano_dotacao=ano_dotacao,
        variacao=variacao,
        competencia_anterior=anteriores[0].competencia if anteriores else None,
    )
    st.download_button(
        "Baixar relatório em Excel",
        relatorio_excel(dados_relatorio),
        file_name=f"reforco_folha_{competencia}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dp_ddp_excel",
    )
    with st.expander("Tabelas completas para análise (Excel e conferência linha a linha)"):
        st.markdown("**Reforço por empenho**")
        st.dataframe(tabela_por_empenho(por_empenho), hide_index=True, width="stretch", height="content")
        st.markdown("**Detalhe por item (nota de empenho × natureza)**")
        st.dataframe(tabela_itens(itens), hide_index=True, width="stretch", height="content")
        st.markdown(f"**DDP × liquidado na base em {_mes(competencia)}**")
        st.caption("Com a folha já liquidada, a diferença é o que a liquidação não reproduziu (em set/2026: reposição ao erário nas pensões, "
                   "cota-parte na creche e diferenças ainda sem explicação). Antes da liquidação, a coluna da base mostra só o que já entrou.")
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
