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
.cmp-risco {{ text-decoration:line-through; opacity:.75; }}
.cmp-alerta {{ background:{SURFACE_ALT} !important; border-radius:6px; padding:1px 7px; color:{WARNING} !important; font-weight:600; }}
.cmp-ok {{ color:{POSITIVE} !important; font-weight:600; }}
.cmp-dif {{ color:{NEGATIVE} !important; font-weight:600; }}
@media (max-width:760px) {{ .cmp-mes {{ grid-template-columns:1fr; }} .cmp-linha {{ grid-template-columns:1fr; }} .cmp-detalhe, .cmp-fora {{ margin-left:0; }} }}
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
    causas: list[Causa] | None = None,
) -> str:
    """O bloco de um mês: relatório e notas empilhados, com o detalhe por NE e o aviso do que ficou fora do filtro.
    `empenhos` (opcional) acrescenta a ação de cada NE que não é da 20RK. Textos escapados."""

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
        for indice, item in enumerate(mes.itens):
            sufixos = []
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
            if indice in retiradas:
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
    return f'<div class="cmp-mes">{rotulo}<div>{linha_rel}{linha_notas}{detalhe}{fora}</div></div>'


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
    # 1ª passada: seleção de NEs de cada mês (a do usuário, se já mexeu; senão o padrão), causa e classe
    analise = []
    for completo in meses:
        opcoes = nes_do_mes(completo)
        escolhidas = st.session_state.get(f"{chave}_cmp_{completo.ano}_{completo.mes}", padrao_do_mes(completo, empenhos))
        visto = filtrar_mes(completo, escolhidas) if opcoes else completo
        causas = causas_do_mes(contexto, completo.ano, completo.mes, escolhidas) if opcoes else []
        explicadas = {c.ne for c in causas if c.tipo == "deslocamento"}  # duas pontas confirmam: vale mais que o cancelamento
        ajuste = ajustar_mes(visto, explicadas) if opcoes else None
        analise.append((completo, opcoes, visto, causas, ajuste, classificar_mes(visto, ajuste, causas)))

    # painel de pendências do exercício + filtro "só os divergentes"
    contagem = {}
    for *_, classe in analise:
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

    for completo, opcoes, visto, causas, ajuste, classe in analise:
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
        bloco.markdown(html_mes(visto, empenhos, ajuste, causas), unsafe_allow_html=True)
