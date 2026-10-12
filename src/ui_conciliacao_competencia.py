"""
Seção "Liquidação por competência × Contratos.gov" dentro do cadastro de cada contrato de Contínuos (11/10/2026).

Camada de interface. A regra está em `src/conciliacao_competencia_gov.py`. Seletor de EXERCÍCIO e, mês a mês, duas
linhas empilhadas: a liquidação do relatório de competência e, abaixo, as notas do Contratos.gov. Os dois valores quando
houver (com a diferença destacada), "sem registro" no que faltar; quando só há nota, o elemento de despesa do empenho.
Em cada mês, um FILTRO DE NEs (padrão: as da 20RK) define o que fica em evidência — nos dois lados; o que sai do filtro
aparece como "fora do filtro" (nada some em silêncio).
Somente leitura. HTML próprio (não `st.dataframe`, que aparece em branco dentro de janelas); `html_*` são puras.
"""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from src.conciliacao_competencia_gov import (
    CLASSES,
    CLASSES_OK,
    AjusteMes,
    Causa,
    Contexto,
    causas_do_mes,
    classificar_mes,
    construir_contexto,
    EmpenhoInfo,
    MesConciliado,
    conciliar_exercicio,
    empenhos_do_contrato,
    exercicios_disponiveis,
    filtrar_mes,
    itens_das_notas,
    nes_do_mes,
    ajustar_mes,
    padrao_do_mes,
    totais_por_ne,
)
from src.decisoes_conciliacao import (
    CLASSES_COM_SUGESTAO,
    ErroDecisao,
    aplicar_decisao,
    assinatura_mes,
    carregar_eventos,
    desfazer_decisao,
    reconstruir_decisoes,
    registrar_decisao,
)
from src.design_tokens import BORDER, NEGATIVE, POSITIVE, SURFACE_ALT, TEXT_FAINT, TEXT_MUTED, WARNING
from src.ui_cadastro import celula_principal, celula_suave, celula_valor, chip, formatar_brl, tabela_html

_MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

CSS = f"""
<style>
.cmp-mes {{ display:grid; grid-template-columns:70px minmax(0,1fr); gap:12px; padding:9px 0; border-bottom:1px solid {BORDER}; }}
.cmp-mes .cmp-rot {{ font-weight:700; font-size:13px; }}
.cmp-mes .cmp-rot small {{ display:block; color:{TEXT_FAINT} !important; font-weight:400; font-size:11px; }}
.cmp-linha {{ display:grid; grid-template-columns:190px 150px minmax(0,1fr); gap:10px; align-items:center; padding:2px 0; font-size:13px; }}
.cmp-linha .cmp-fonte {{ color:{TEXT_MUTED} !important; }}
.cmp-linha .cmp-valor {{ text-align:right; font-weight:700; font-variant-numeric:tabular-nums; }}
.cmp-linha .cmp-vazio {{ color:{TEXT_FAINT} !important; font-style:italic; font-weight:400; }}
.cmp-linha .cmp-nota {{ color:{TEXT_FAINT} !important; font-size:12px; }}
.cmp-detalhe {{ margin:2px 0 4px 200px; font-size:12px; color:{TEXT_FAINT} !important; }}
.cmp-detalhe div {{ padding:1px 0; }}
.cmp-fora {{ margin:3px 0 2px 200px; font-size:12px; color:{WARNING} !important; }}
.cmp-tag {{ border:1px solid {BORDER}; border-radius:6px; padding:0 6px; font-size:11px; color:{TEXT_MUTED} !important; }}
.cmp-painel {{ background:{SURFACE_ALT} !important; border-radius:8px; padding:8px 12px; margin:6px 0 8px; font-size:13px; }}
.cmp-nota-painel {{ color:{TEXT_FAINT} !important; }}
.cmp-cons {{ border-collapse:collapse; font-size:12px; width:100%; }}
.cmp-cons th {{ font-size:11px; color:{TEXT_FAINT} !important; text-transform:uppercase; padding:4px 3px; text-align:right; }}
.cmp-cons th:first-child, .cmp-cons td:first-child {{ text-align:left; }}
.cmp-cons td {{ padding:3px 3px; text-align:right; font-variant-numeric:tabular-nums; border-top:1px solid {BORDER}; }}
.cmp-cons td.c {{ border-radius:4px; }}
.cmp-cons .k-batem {{ background:rgba(10,143,61,.16) !important; }}
.cmp-cons .k-sem_registro {{ color:{TEXT_FAINT} !important; }}
.cmp-cons .k-deslocamento, .cmp-cons .k-cancelamento, .cmp-cons .k-nota_pendente {{ background:rgba(9,105,218,.16) !important; }}
.cmp-cons .k-ambiguo, .cmp-cons .k-sem_explicacao {{ background:rgba(210,10,22,.16) !important; }}
.cmp-cons .k-so_notas, .cmp-cons .k-so_relatorio {{ background:rgba(201,106,0,.20) !important; }}
.cmp-cons tr.tot td {{ font-weight:700; border-top:2px solid {BORDER}; }}
.cmp-risco {{ text-decoration:line-through; opacity:.75; }}
.cmp-alerta {{ background:{SURFACE_ALT} !important; border-radius:6px; padding:1px 7px; color:{WARNING} !important; font-weight:600; }}
.cmp-ok {{ color:{POSITIVE} !important; font-weight:600; }}
.cmp-credor {{ color:{TEXT_MUTED} !important; font-size:11px; font-weight:400; }}
.cmp-mes.cmp-conf {{ border-left:4px solid {POSITIVE}; padding-left:8px; background:rgba(10,143,61,.07) !important; }}
.cmp-mes.cmp-rej {{ border-left:4px solid {NEGATIVE}; padding-left:8px; }}
.cmp-decisao {{ margin:4px 0 2px 200px; font-size:12px; font-weight:600; }}
.cmp-decisao.conf {{ color:{POSITIVE} !important; }}
.cmp-decisao.rej {{ color:{NEGATIVE} !important; }}
.cmp-dif {{ color:{NEGATIVE} !important; font-weight:600; }}
@media (max-width:760px) {{ .cmp-mes {{ grid-template-columns:1fr; }} .cmp-linha {{ grid-template-columns:1fr; }} .cmp-detalhe, .cmp-fora, .cmp-decisao {{ margin-left:0; }} }}
</style>
"""


def _brl(valor: float) -> str:
    return formatar_brl(valor).replace("$", "&#36;")


_SITUACAO_TOTAL = {
    "batem": ("Batem", "ok"), "diverge_relatorio": ("Relatório ≠ Execução", "warn"), "diverge_notas": ("Notas ≠ Execução", "warn"),
    "sem_execucao": ("Sem Execução Mensal", "neutro"),
}


def html_totais(linhas) -> str:
    """Quadro de totais por NE: notas × relatório de competência × Execução Mensal, com as diferenças."""

    corpo = []
    for l in linhas:
        rotulo, tom = _SITUACAO_TOTAL[l.situacao]
        acao = f"{l.empenho.acao}" + (f" · {l.empenho.elemento}" if l.empenho and l.empenho.elemento else "") if l.empenho else "—"
        corpo.append([
            celula_principal(l.ne, acao), celula_valor(l.notas, vazio="sem nota"), celula_valor(l.relatorio, vazio="sem relatório"),
            celula_valor(l.execucao, vazio="sem lançamento"), celula_valor(l.dif_relatorio, vazio="—"),
            celula_valor(l.dif_notas, vazio="—"), chip(rotulo, tom),
        ])
    return tabela_html(
        [("NE / ação", False), ("Notas", True), ("Relatório", True), ("Exec. Mensal", True), ("Relat. − Exec.", True),
         ("Notas − Exec.", True), ("Situação", False)],
        corpo, [1.5, 1, 1, 1, 1, 1, 1.3],
    )


def _compacto(valor: float | None) -> str:
    """Valor curto para a célula da matriz: "2,6 mil", "1,2 mi"; nulo vira "—" (o valor exato fica no título)."""
    if valor is None:
        return "—"
    absoluto = abs(valor)
    if absoluto >= 1_000_000:
        texto = f"{valor / 1_000_000:.1f} mi"
    elif absoluto >= 1_000:
        texto = f"{valor / 1_000:.1f} mil"
    else:
        texto = f"{valor:.0f}"
    return texto.replace(".", ",")


def _credor_html(linha: dict) -> str:
    """Nome do credor (do cadastro de Contínuos) logo abaixo do número do contrato; sem credor, nada."""

    credor = linha.get("credor")
    if credor is None or (isinstance(credor, float) and pd.isna(credor)) or not str(credor).strip():
        return ""
    return f'<br><span class="cmp-credor">{escape(str(credor).strip())}</span>'


def html_consolidada(linhas: list[dict]) -> str:
    """Matriz contratos × 12 meses: o valor do relatório (ou, se só há nota, o da nota, em itálico) com a cor da classe do
    mês; o título de cada célula traz os valores exatos e a causa. Linha final com os totais por mês. Textos escapados."""

    cabecalho = "".join(f"<th>{_MESES[m]}</th>" for m in range(12))
    corpo, tot_rel, tot_notas = [], [None] * 12, [None] * 12
    for linha in linhas:
        celulas = []
        for i, mes in enumerate(linha["meses"]):
            rel, bruto, classe = mes["relatorio"], mes["notas"], mes["classe"]
            ajustado = mes.get("notas_ajustadas")
            notas = ajustado if ajustado is not None else bruto  # decisão confirmada: sem as notas indicadas como canceladas
            if rel is not None:
                tot_rel[i] = (tot_rel[i] or 0.0) + rel
            if notas is not None:
                tot_notas[i] = (tot_notas[i] or 0.0) + notas
            texto = _compacto(rel) if rel is not None else (f"<i>{_compacto(notas)}</i>" if notas is not None else "—")
            titulo = (
                f"{_MESES[i]}/{linha.get('ano', '')}: {CLASSES[classe]} · relatório "
                f"{'sem registro' if rel is None else formatar_brl(rel)} · notas {'sem registro' if bruto is None else formatar_brl(bruto)}"
                + (f" (ajustado por decisão: {formatar_brl(ajustado)})" if ajustado is not None else "")
            )
            if ajustado is not None:
                texto += "*"
            celulas.append(f'<td class="c k-{classe}" title="{escape(titulo)}">{texto}</td>')
        corpo.append(
            f"<tr><td><b>{escape(linha['contrato'])}</b>{_credor_html(linha)}</td>{''.join(celulas)}"
            f"<td><b>{_compacto(linha['total_relatorio'])}</b></td>"
            f"<td>{_compacto(linha.get('total_notas_ajustado', linha['total_notas']))}</td></tr>"
        )
    totais = "".join(f"<td>{_compacto(v)}</td>" for v in tot_rel)
    soma_rel = sum(v for v in tot_rel if v is not None) if any(v is not None for v in tot_rel) else None
    soma_notas = sum(v for v in tot_notas if v is not None) if any(v is not None for v in tot_notas) else None
    corpo.append(f'<tr class="tot"><td>Total (relatório)</td>{totais}<td>{_compacto(soma_rel)}</td><td>{_compacto(soma_notas)}</td></tr>')
    return (
        f'<table class="cmp-cons"><thead><tr><th>Contrato</th>{cabecalho}<th>Total relat.</th><th>Total notas</th></tr></thead>'
        f'<tbody>{"".join(corpo)}</tbody></table>'
    )


def html_legenda_consolidada() -> str:
    cores = {
        "batem": "Batem", "deslocamento": "Deslocamento / cancelamento / nota pendente",
        "sem_explicacao": "Ambíguo / sem explicação", "so_notas": "Só uma das fontes", "sem_registro": "Sem registro",
    }
    itens = "".join(
        f'<span class="k-{c}" style="padding:1px 8px;border-radius:4px;margin-right:8px">{escape(t)}</span>' for c, t in cores.items()
    )
    return (
        f'<div class="cmp-cons"><div style="font-size:12px;margin:4px 0 8px">{itens}'
        '<span>* valor das notas ajustado por decisão (nota indicada como cancelada)</span></div></div>'
    )


def render_visao_consolidada(
    ligados: list, faturas: pd.DataFrame | None, empenhos_gov: pd.DataFrame | None, relatorio: pd.DataFrame | None, chave: str,
    credores: dict | None = None,
) -> None:
    """Expansor "todos os contratos": seletor de exercício e matriz calculada sob demanda (leva alguns segundos), com o
    credor de cada contrato (`credores`: número do contrato → nome, do cadastro de Contínuos) e a exportação em PDF/Excel."""

    from datetime import datetime

    from src.pendencias_conciliacao import consolidar_exercicio
    from src.relatorio_conciliacao_consolidada import gerar_pdf, gerar_xlsx

    with st.expander("Conciliação por competência — todos os contratos", expanded=False):
        if relatorio is None or relatorio.empty:
            st.caption("Sem a base de Liquidação por Competência, não há o que mostrar.")
            return
        anos = sorted({int(a) // 100 for a in relatorio["ano_mes"]}, reverse=True)
        ano = st.selectbox("Exercício", anos, key=f"{chave}_cons_ano")
        estado = f"{chave}_cons_dados"
        assinatura = (int(ano), len(ligados), len(relatorio), 0 if faturas is None else len(faturas))
        st.caption(
            "Valor LIQUIDADO por competência de cada contrato (relatório do Tesouro; em itálico, quando só há nota do gov), "
            "com a cor da situação do mês. Só as NEs da 20RK; passe o mouse sobre a célula para ver os valores exatos."
        )
        if st.button("Calcular a visão consolidada", key=f"{chave}_cons_calcular"):
            with st.spinner("Conciliando todos os contratos…"):
                linhas = consolidar_exercicio(ligados, faturas, empenhos_gov, relatorio, int(ano))
            for linha in linhas:
                linha["ano"] = int(ano)
                linha["credor"] = (credores or {}).get(linha["contrato"])
            st.session_state[estado] = (assinatura, linhas, datetime.now().strftime("%d/%m/%Y %H:%M"))
        guardado = st.session_state.get(estado)
        if guardado and guardado[0] == assinatura:
            st.markdown(CSS, unsafe_allow_html=True)
            st.markdown(html_legenda_consolidada() + html_consolidada(guardado[1]), unsafe_allow_html=True)
            nome = f"conciliacao_competencia_{int(ano)}_{guardado[2][:10].replace('/', '-')}"
            c_pdf, c_xlsx = st.columns(2)
            c_pdf.download_button(
                "Baixar PDF", data=lambda: gerar_pdf(guardado[1], int(ano), guardado[2]), file_name=f"{nome}.pdf",
                mime="application/pdf", key=f"{chave}_cons_pdf", use_container_width=True,
            )
            c_xlsx.download_button(
                "Baixar Excel", data=lambda: gerar_xlsx(guardado[1], int(ano), guardado[2]), file_name=f"{nome}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"{chave}_cons_xlsx",
                use_container_width=True,
            )


def _cb_registrar(
    prefixo: str, contrato: str, ano_mes: int, classe: str, assinatura: str, decisao: str, alternativas=(),
) -> None:
    """`on_click` do botão Confirmar/Rejeitar: grava o evento antes do redesenho (a janela do contrato não fecha).
    `alternativas` (mês ambíguo): por NE, as combinações possíveis de notas [(nota, ne, valor), ...]; a escolhida em cada
    seletor vira `notas_desconsideradas` — só ao CONFIRMAR."""

    try:
        escolhidas = None
        if decisao == "confirmada" and alternativas:
            escolhidas = []
            for k, combos in enumerate(alternativas):
                escolhidas.extend(combos[st.session_state.get(f"{prefixo}_alt_{k}", 0)])
        registrar_decisao(
            contrato=contrato, ano_mes=ano_mes, classe=classe, assinatura=assinatura, decisao=decisao,
            justificativa=st.session_state.get(f"{prefixo}_just", ""), responsavel=st.session_state.get(f"{prefixo}_resp", ""),
            notas_desconsideradas=escolhidas,
        )
        st.session_state[f"{prefixo}_msg"] = ""
    except ErroDecisao as erro:
        st.session_state[f"{prefixo}_msg"] = str(erro)


def _cb_desfazer(prefixo: str, decisao_id: str) -> None:
    try:
        desfazer_decisao(
            decisao_id=decisao_id, motivo=st.session_state.get(f"{prefixo}_mot", ""),
            responsavel=st.session_state.get(f"{prefixo}_resp", ""),
        )
        st.session_state[f"{prefixo}_msg"] = ""
    except ErroDecisao as erro:
        st.session_state[f"{prefixo}_msg"] = str(erro)


def _alternativas_do_mes(visto: MesConciliado, ajuste: AjusteMes | None) -> list[tuple[str, list[tuple]]]:
    """Mês ambíguo: por NE, as combinações de notas candidatas a canceladas, como [(nota, ne, valor), ...]."""

    if ajuste is None:
        return []
    return [
        (ne, [tuple((visto.itens[i].nota, visto.itens[i].ne, round(visto.itens[i].valor, 2)) for i in combo) for combo in combos])
        for ne, combos in ajuste.alternativas
    ]


def _render_decisao(
    contrato: str, completo: MesConciliado, classe_original: str, assinatura: str, decisao, chave: str, alternativas=(),
) -> None:
    """Formulário do mês: decisão ativa (com desfazer) ou Confirmar/Rejeitar a sugestão. Grava por callback."""

    ativa = decisao is not None and decisao.assinatura == assinatura and classe_original in CLASSES_COM_SUGESTAO
    rotulo = f"{_MESES[completo.mes - 1]}/{completo.ano}"
    prefixo = f"{chave}_dec_{completo.ano}_{completo.mes}"
    titulo = f"Decisão — {rotulo}" + (f" ({decisao.decisao})" if ativa else "")
    with st.expander(titulo, expanded=False):
        if decisao is not None and not ativa:
            st.caption("Havia uma decisão para este mês, mas os dados mudaram desde então: ela ficou obsoleta e foi ignorada.")
        if ativa:
            st.caption(
                f"Sugestão {decisao.decisao} por {decisao.responsavel} em {decisao.registrado_em[:19].replace('T', ' ')}: "
                f"{decisao.justificativa}"
            )
            if decisao.notas_desconsideradas:
                st.caption(
                    "Notas indicadas como canceladas: "
                    + "; ".join(f"nota {n} ({_brl(v)}, NE {ne})" for n, ne, v in decisao.notas_desconsideradas)
                )
            st.text_input("Motivo para desfazer", key=f"{prefixo}_mot")
            st.text_input("Responsável", key=f"{prefixo}_resp")
            st.button("Desfazer decisão", key=f"{prefixo}_desfazer", on_click=_cb_desfazer, args=(prefixo, decisao.id))
        else:
            st.caption(
                f"Sugestão do sistema para {rotulo}: {CLASSES[classe_original].lower()}. Confirmar tira o mês das pendências; "
                "rejeitar mantém a pendência. A decisão é gravada com responsável e justificativa e pode ser desfeita."
            )
            if classe_original == "ambiguo":
                st.caption(
                    "Mais de uma nota fecha o valor e o sistema não escolhe. Se você sabe qual está cancelada ou repetida, "
                    "indique-a abaixo e confirme; a escolha fica registrada e pode ser desfeita. Sem saber, rejeite."
                )
                for k, (ne, combos) in enumerate(alternativas):
                    st.selectbox(
                        f"Nota cancelada/repetida — NE {ne}", range(len(combos)), key=f"{prefixo}_alt_{k}",
                        format_func=lambda i, combos=combos: " + ".join(f"nota {n} ({_brl(v)})" for n, _ne, v in combos[i]),
                    )
            st.text_input("Responsável", key=f"{prefixo}_resp")
            st.text_area("Justificativa (mínimo de 10 caracteres)", key=f"{prefixo}_just", height=70)
            c1, c2 = st.columns(2)
            c1.button(
                "Confirmar sugestão", key=f"{prefixo}_confirmar", disabled=classe_original == "ambiguo" and not alternativas,
                help="Mês ambíguo: a nota cancelada é a que você escolheu acima.",
                on_click=_cb_registrar,
                args=(prefixo, contrato, completo.ano * 100 + completo.mes, classe_original, assinatura, "confirmada",
                      [c for _ne, c in alternativas]),
            )
            c2.button(
                "Rejeitar sugestão", key=f"{prefixo}_rejeitar", on_click=_cb_registrar,
                args=(prefixo, contrato, completo.ano * 100 + completo.mes, classe_original, assinatura, "rejeitada"),
            )
        if st.session_state.get(f"{prefixo}_msg"):
            st.error(st.session_state[f"{prefixo}_msg"])


def _rotulo_ne(ne: str, empenhos: dict[str, EmpenhoInfo]) -> str:
    info = empenhos.get(ne)
    if info is None:
        return f"{ne} · ação não identificada"
    elemento = f" · {info.elemento}" if info.elemento else ""
    return f"{ne} · {info.acao}{elemento}{' DEA' if info.elemento == '92' else ''}"


def _tag_elemento(item) -> str:
    if item.natureza is None:
        return '<span class="cmp-alerta">elemento não identificado</span>'
    rotulo = f"elemento {item.elemento} · {escape(item.natureza)}" if item.elemento else escape(item.natureza)
    return f'<span class="cmp-alerta">{rotulo}</span>' if item.elemento == "92" else f"<span>{rotulo}</span>"


def _mes_ano(ano_mes: int) -> str:
    return f"{_MESES[ano_mes % 100 - 1]}/{ano_mes // 100}"


def html_causa(mes: MesConciliado, causa: Causa) -> str:
    """Uma linha explicando a divergência de uma NE (nota pendente ou deslocamento de competência)."""

    ne = escape(causa.ne)
    if causa.tipo == "nota_pendente":
        notas = ", ".join(escape(n) for n in causa.notas)
        return (
            f'<div><span class="cmp-alerta">nota ainda não liquidada</span> NE {ne}: faltam {_brl(causa.valor)} nas notas — '
            f"é a nota {notas}, sem liquidação no Siafi (pendente ou com erro).</div>"
        )
    par = _mes_ano(causa.par)
    aqui = f"{_MESES[mes.mes - 1]}/{mes.ano}"
    if causa.sentido == "notas_aqui":
        texto = f"as notas põem {_brl(causa.valor)} em {aqui}, mas o relatório registrou esse valor em {par}"
    else:
        texto = f"o relatório registra {_brl(causa.valor)} em {aqui}, mas as notas puseram esse valor em {par}"
    return f'<div><span class="cmp-alerta">deslocamento de competência</span> NE {ne}: {texto} (par exato).</div>'


def html_mes(
    mes: MesConciliado, empenhos: dict[str, EmpenhoInfo] | None = None, ajuste: AjusteMes | None = None,
    causas: list[Causa] | None = None, decisao=None,
) -> str:
    """O bloco de um mês: relatório e notas empilhados, com o detalhe por NE e o aviso do que ficou fora do filtro.
    `empenhos` (opcional) acrescenta a ação de cada NE que não é da 20RK. `decisao` (a decisão ATIVA do mês, se houver)
    troca a marca de diferença por "conciliado por decisão" (confirmada) ou mantém a diferença avisando que a sugestão foi
    rejeitada, e mostra quem decidiu e por quê. Textos escapados."""

    rel_vazio = '<span class="cmp-valor cmp-vazio">sem registro</span>'
    if mes.relatorio is None:
        linha_rel = f'<div class="cmp-linha"><span class="cmp-fonte">Liquidação por competência</span>{rel_vazio}<span></span></div>'
    else:
        por_ne = " · ".join(f"{escape(ne)}: {_brl(v)}" for ne, v in sorted(mes.relatorio_por_ne.items()))
        linha_rel = (
            f'<div class="cmp-linha"><span class="cmp-fonte">Liquidação por competência</span>'
            f'<span class="cmp-valor">{_brl(mes.relatorio)}</span><span class="cmp-nota">{por_ne}</span></div>'
        )
    if mes.notas is None and not mes.itens:
        linha_notas = f'<div class="cmp-linha"><span class="cmp-fonte">Contratos.gov (notas)</span>{rel_vazio}<span></span></div>'
    else:
        valor = _brl(mes.notas) if mes.notas is not None else rel_vazio.replace("sem registro", "—")
        if ajuste is not None and ajuste.situacao == "batem_ajustado":
            marca = (
                f'<span class="cmp-ok">✓ batem, desconsiderando {len(ajuste.retiradas)} nota(s) '
                f'(ajustado: {_brl(ajuste.notas_ajustadas)})</span> '
                '<span class="cmp-alerta">provável cancelamento não informado no Contratos.gov</span>'
            )
        elif ajuste is not None and ajuste.situacao == "ambiguo":
            marca = f'<span class="cmp-dif">≠ diferença {_brl(mes.diferenca)}</span> <span class="cmp-alerta">ambíguo: ver alternativas</span>'
        elif mes.situacao == "batem":
            marca = '<span class="cmp-ok">✓ batem</span>'
        elif mes.situacao == "divergem":
            marca = f'<span class="cmp-dif">≠ diferença {_brl(mes.diferenca)}</span>'
        elif mes.situacao == "so_notas":
            marca = '<span class="cmp-alerta">sem registro no relatório de competência</span>'
        else:
            marca = ""
        escolhidas = list(getattr(decisao, "notas_desconsideradas", ()) or ()) if decisao is not None else []
        if decisao is not None and decisao.decisao == "confirmada" and escolhidas:
            marca = (
                f'<span class="cmp-ok">✓ batem, desconsiderando {len(escolhidas)} nota(s) por decisão</span> '
                '<span class="cmp-alerta">cancelamento indicado pelo usuário</span>'
            )
        elif decisao is not None and decisao.decisao == "confirmada":
            aceita = f" (diferença de {_brl(mes.diferenca)} aceita)" if mes.diferenca is not None else ""
            marca = f'<span class="cmp-ok">✓ conciliado por decisão{aceita}</span>'
        linha_notas = (
            f'<div class="cmp-linha"><span class="cmp-fonte">Contratos.gov (notas)</span>'
            f'<span class="cmp-valor">{valor}</span><span>{marca}</span></div>'
        )
    detalhe = ""
    if mes.itens or causas:
        # o elemento de despesa só é "evidenciado" quando o relatório não tem o mês (o caso do DEA)
        mostrar_elemento = mes.relatorio is None
        linhas = []
        retiradas = set(ajuste.retiradas) if ajuste is not None else set()
        # notas que o usuário indicou como canceladas: uma por escolha (nota, ne, valor), a primeira que casar
        pendentes_escolha = [tuple(n) for n in (getattr(decisao, "notas_desconsideradas", ()) or ())] if decisao is not None else []
        for indice, item in enumerate(mes.itens):
            sufixos = []
            chave_item = (item.nota, item.ne, round(item.valor, 2))
            escolhida = chave_item in pendentes_escolha
            if escolhida:
                pendentes_escolha.remove(chave_item)
                sufixos.append('<span class="cmp-alerta">desconsiderada por decisão</span>')
            if indice in retiradas:
                sufixos.append('<span class="cmp-alerta">sugerida como cancelada (não somada no ajuste)</span>')
            if item.duplicada:
                sufixos.append('<span class="cmp-alerta">possível duplicidade (não somada)</span>')
            if item.rateada:
                sufixos.append("rateio estimado")
            info = (empenhos or {}).get(item.ne)
            if info is not None and not info.da_20rk:
                sufixos.append(f'<span class="cmp-tag">{escape(info.acao)}</span>')
            if mostrar_elemento or item.elemento == "92":
                sufixos.append(_tag_elemento(item))
            texto = f"Nota {escape(item.nota)} · NE {escape(item.ne)} · {_brl(item.valor)}"
            if indice in retiradas or escolhida:
                texto = f'<span class="cmp-risco">{texto}</span>'
            linhas.append(f"<div>{texto}{' · ' + ' · '.join(sufixos) if sufixos else ''}</div>")
        for causa in causas or []:
            linhas.append(html_causa(mes, causa))
        if ajuste is not None:
            for ne, combos in ajuste.alternativas:
                opcoes = " ou ".join(
                    "+".join(f"nota {escape(mes.itens[i].nota)} ({_brl(mes.itens[i].valor)})" for i in c) for c in combos
                )
                linhas.append(
                    f'<div><span class="cmp-alerta">ambíguo</span> NE {escape(ne)}: o cancelamento poderia ser {opcoes}. '
                    "O sistema não escolhe.</div>"
                )
        detalhe = f'<div class="cmp-detalhe">{"".join(linhas)}</div>'
    fora = ""
    if mes.nes_fora:
        partes = []
        if mes.fora_do_filtro_relatorio is not None:
            partes.append(f"relatório {_brl(mes.fora_do_filtro_relatorio)}")
        if mes.fora_do_filtro_notas is not None:
            partes.append(f"notas {_brl(mes.fora_do_filtro_notas)}")
        valores = (": " + " · ".join(partes)) if partes else ""
        fora = (
            f'<div class="cmp-fora">{len(mes.nes_fora)} NE(s) fora do filtro{valores} '
            f"({escape(', '.join(mes.nes_fora))})</div>"
        )
    rotulo = f'<div class="cmp-rot">{_MESES[mes.mes - 1]}/{mes.ano}</div>'
    decidido, classe_css = "", ""
    if decisao is not None:
        conf = decisao.decisao == "confirmada"
        classe_css = " cmp-conf" if conf else " cmp-rej"
        verbo = "Sugestão confirmada" if conf else "Sugestão rejeitada (a pendência continua)"
        decidido = (
            f'<div class="cmp-decisao {"conf" if conf else "rej"}">{verbo} por {escape(decisao.responsavel)} em '
            f'{escape(decisao.registrado_em[:16].replace("T", " "))}: {escape(decisao.justificativa)}</div>'
        )
    return f'<div class="cmp-mes{classe_css}">{rotulo}<div>{linha_rel}{linha_notas}{detalhe}{decidido}{fora}</div></div>'


def render_conciliacao_competencia(
    linha: pd.Series, faturas_gov: tuple | None, empenhos_gov: pd.DataFrame | None,
    relatorio_por_mes: pd.DataFrame | None, chave: str, execucao_mensal: pd.DataFrame | None = None,
) -> None:
    """Seção na janela "Editar contrato". `faturas_gov` = (tabela, contratos consultados); `relatorio_por_mes` = Liquidação
    por Competência por (NE, mês) com `ne_curta`."""

    st.markdown("**Liquidação por competência × Contratos.gov (ação 20RK)**")
    if pd.isna(linha.get("contratosgov_id")):
        st.caption("Contrato sem par no Contratos.gov: não há notas para confrontar com o relatório de competência.")
        return
    cid = str(linha["contratosgov_id"])
    faturas, consultados = faturas_gov if faturas_gov is not None else (None, set())
    tabela = None if faturas is None or cid not in consultados else faturas[faturas["contrato_id"] == cid]
    ne_cadastro = linha.get("ne_curta") if pd.notna(linha.get("ne_curta")) else None
    empenhos = empenhos_do_contrato(empenhos_gov, cid, ne_cadastro)
    naturezas = {ne: info.natureza for ne, info in empenhos.items()}
    itens, fora = itens_das_notas(tabela, naturezas)
    pendentes, _ = itens_das_notas(tabela, naturezas, liquidadas=False)
    contexto = construir_contexto(relatorio_por_mes, itens, pendentes, naturezas)
    anos = exercicios_disponiveis(relatorio_por_mes, itens, naturezas)
    if tabela is None:
        st.caption("Instrumentos de cobrança ainda não consultados para este contrato — atualize na página Contratos.")
    if not anos:
        st.caption("Sem liquidação por competência nem notas da ação 20RK para este contrato.")
        return
    ano = st.selectbox("Exercício", anos, key=f"{chave}_cmp_ano")
    st.markdown(CSS, unsafe_allow_html=True)
    meses = conciliar_exercicio(int(ano), relatorio_por_mes, itens, naturezas)
    # confronto de totais por NE com a Execução Mensal (11/10/2026): só o total é comparável (lançamento ≠ competência)
    totais = totais_por_ne(relatorio_por_mes, itens, execucao_mensal, empenhos)
    if totais:
        with st.expander(f"Totais por NE × Execução Mensal ({len(totais)} NE(s))", expanded=False):
            st.caption(
                "Total de cada NE em todas as competências: liquidado nas notas, no relatório de competência e na "
                "Execução Mensal. A Execução Mensal é por mês de LANÇAMENTO (não por competência) e só cobre 2024 em "
                "diante; notas de 2024 para trás são incompletas no gov. Compare só o total."
            )
            st.markdown(html_totais(totais), unsafe_allow_html=True)
    st.caption(
        "Em cada mês, escolha quais NEs ficam em evidência (padrão: as da ação 20RK). Relatório e notas usam sempre a "
        "mesma seleção e não são somados. Quando as notas somam mais que o relatório, o sistema procura as notas cuja "
        "retirada fecha o valor (provável cancelamento não informado no gov) — é só uma sugestão, nada é gravado."
        + (f" {fora} nota(s) liquidada(s) não têm nenhuma NE deste contrato e ficaram fora." if fora else "")
    )
    contrato = str(linha["contrato_numero"])
    try:
        decisoes = reconstruir_decisoes(carregar_eventos())
    except ErroDecisao as erro:
        st.error(f"Decisões de conciliação ilegíveis: {erro}")
        decisoes = {}
    # 1ª passada: seleção de NEs de cada mês (a do usuário, se já mexeu; senão o padrão), causa e classe
    analise = []
    for completo in meses:
        opcoes = nes_do_mes(completo)
        escolhidas = st.session_state.get(f"{chave}_cmp_{completo.ano}_{completo.mes}", padrao_do_mes(completo, empenhos))
        visto = filtrar_mes(completo, escolhidas) if opcoes else completo
        causas = causas_do_mes(contexto, completo.ano, completo.mes, escolhidas) if opcoes else []
        explicadas = {c.ne for c in causas if c.tipo == "deslocamento"}  # duas pontas confirmam: vale mais que o cancelamento
        ajuste = ajustar_mes(visto, explicadas) if opcoes else None
        original = classificar_mes(visto, ajuste, causas)
        assinatura = assinatura_mes(
            original, escolhidas if opcoes else [], [i.nota for i in visto.itens], visto.notas, visto.relatorio
        )
        decisao = decisoes.get((contrato, completo.ano * 100 + completo.mes))
        analise.append((completo, opcoes, visto, causas, ajuste, aplicar_decisao(original, decisao, assinatura), original, assinatura, decisao))

    # painel de pendências do exercício + filtro "só os divergentes"
    contagem = {}
    for *_, classe, _original, _assinatura, _decisao in analise:
        contagem[classe] = contagem.get(classe, 0) + 1
    pendencias = sum(n for c, n in contagem.items() if c not in CLASSES_OK)
    st.markdown(
        '<div class="cmp-painel"><b>Pendências do exercício:</b> '
        + (" · ".join(f"{contagem[c]} {escape(CLASSES[c].lower())}" for c in CLASSES if contagem.get(c) and c not in CLASSES_OK)
           or "nenhuma")
        + f' <span class="cmp-nota-painel">({contagem.get("batem", 0)} mês(es) batem, {contagem.get("sem_registro", 0)} sem registro)</span></div>',
        unsafe_allow_html=True,
    )
    so_divergentes = st.checkbox(
        f"Mostrar só os meses com pendência ({pendencias})", key=f"{chave}_cmp_so_divergentes",
    )

    for completo, opcoes, visto, causas, ajuste, classe, original, assinatura, decisao in analise:
        if so_divergentes and classe in CLASSES_OK:
            continue
        bloco, filtro = st.container(), st.container()
        if not opcoes:
            bloco.markdown(html_mes(completo), unsafe_allow_html=True)
            continue
        rotulo = f"{_MESES[completo.mes - 1]}/{completo.ano}"
        with filtro:
            st.multiselect(
                f"NEs em evidência — {rotulo}", opcoes, default=padrao_do_mes(completo, empenhos),
                key=f"{chave}_cmp_{completo.ano}_{completo.mes}",
                format_func=lambda ne: _rotulo_ne(ne, empenhos),
            )
        bloco.markdown(
            html_mes(visto, empenhos, ajuste, causas, decisao if classe in ("confirmada", "rejeitada") else None),
            unsafe_allow_html=True,
        )
        if original in CLASSES_COM_SUGESTAO or decisao is not None:
            with bloco:
                _render_decisao(contrato, completo, original, assinatura, decisao, chave, _alternativas_do_mes(visto, ajuste))
