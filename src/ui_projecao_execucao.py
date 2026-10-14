"""
Edição da Projeção pela Execução de Contratos Contínuos (14/10/2026).

Camada de interface. A regra está em `src/relatorio_projecao_execucao.py` (`projetar_meses(ajustes=)`) e a gravação em
`src/projecao_ajustes.py`. Duas partes:

  * MATRIZ de leitura NE × 12 meses no estilo da conciliação por competência (HTML próprio, funções `html_*` puras,
    textos escapados): coluna do contrato com o NÚMERO em negrito e o fornecedor abaixo, células coloridas por situação
    (realizado, projetado, restante de mês em aberto) e `✎` no mês cujo esperado foi ajustado pelo usuário.
  * EDIÇÃO POR NE: um campo de texto por mês editável (esperado TOTAL do mês; o liquidado do mês continua descontado),
    "Gravar", "Refazer esta NE" e "Refazer todas do exercício" (com confirmação). Sem `st.data_editor` nem `st.dialog`
    (o editor quebra dentro de diálogos).
"""

from __future__ import annotations

import math
import re
from html import escape

import pandas as pd
import streamlit as st

from src.design_tokens import BORDER, SURFACE_ALT, TEXT_FAINT, TEXT_MUTED, WARNING
from src.projecao_ajustes import (
    ErroAjuste,
    ajustes_vigentes,
    refazer_ne,
    refazer_tudo,
    registrar_ajustes,
)
from src.relatorio_projecao_execucao import (
    MESES,
    TIPO_PROJETADO,
    TIPO_REALIZADO,
    TIPO_RESTANTE_ABERTO,
    RelatorioProjecaoExecucao,
    liquidado_abatido,
)
from src.ui_cadastro import formatar_brl

_MILHAR = re.compile(r"^\d{1,3}(\.\d{3})+$")
_TOLERANCIA = 0.005

CSS = f"""
<style>
.pe-m {{ border-collapse:collapse; font-size:12px; width:100%; }}
.pe-m th {{ font-size:11px; color:{TEXT_FAINT} !important; text-transform:uppercase; padding:4px 3px; text-align:right; }}
.pe-m th:first-child, .pe-m td:first-child {{ text-align:left; }}
.pe-m td {{ padding:4px 3px; text-align:right; font-variant-numeric:tabular-nums; border-top:1px solid {BORDER}; }}
.pe-m td.c {{ border-radius:4px; }}
.pe-m .k-real {{ background:{SURFACE_ALT} !important; }}
.pe-m .k-proj {{ background:rgba(9,105,218,.16) !important; }}
.pe-m .k-aberto {{ background:rgba(201,106,0,.20) !important; }}
.pe-m .k-edit {{ box-shadow:inset 0 0 0 2px #1d4ed8; }}
.pe-m .k-vazio {{ color:{TEXT_FAINT} !important; }}
.pe-m .t b {{ display:block; font-size:13px; }}
.pe-m .t small {{ color:{TEXT_MUTED} !important; font-size:11px; }}
.pe-m .t i {{ font-style:normal; color:{TEXT_FAINT} !important; font-size:11px; }}
.pe-m tr.tot td {{ font-weight:700; border-top:2px solid {BORDER}; }}
.pe-leg {{ font-size:12px; margin:4px 0 8px; }}
.pe-leg span {{ padding:1px 8px; border-radius:4px; margin-right:8px; }}
.pe-aviso {{ color:{WARNING} !important; font-size:12px; }}
</style>
"""


# ------------------------------------------------------------------ funções puras
def ler_valor_brl(texto: str | None) -> float | None:
    """Texto digitado → valor. Vazio → `None` (sem ajuste). Aceita `1.234,56`, `1234,56`, `1234.56`, `1.234` (milhar)
    e o prefixo `R$`. Negativo, `nan`, `inf` e texto não numérico levantam `ValueError`; zero é válido."""

    limpo = re.sub(r"(?i)r\$|\s", "", str(texto or ""))
    if not limpo:
        return None
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif _MILHAR.match(limpo):
        limpo = limpo.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d+)?", limpo):
        raise ValueError(f"Valor inválido: {texto!r} (use zero ou um número positivo, ex.: 1.234,56).")
    valor = float(limpo)
    if math.isnan(valor) or math.isinf(valor):
        raise ValueError(f"Valor inválido: {texto!r}.")
    return valor


def titulo_contrato(contrato_numero: object, fornecedor: object) -> str:
    """Título do contrato: número e fornecedor (como na conciliação por competência)."""

    numero = "" if contrato_numero is None or pd.isna(contrato_numero) else str(contrato_numero).strip()
    nome = "" if fornecedor is None or pd.isna(fornecedor) else str(fornecedor).strip()
    return f"Contrato {numero or '—'} — {nome or '(sem fornecedor)'}"


def meses_editaveis(relatorio: RelatorioProjecaoExecucao) -> list[int]:
    """Do primeiro mês em aberto a dezembro; vazio quando o exercício já foi encerrado."""

    if relatorio.mes_referencia >= 12:
        return []
    return list(range(max(relatorio.ultimo_fechado + 1, 1), 13))


def valores_para_gravar(
    digitado: dict[int, str], vigente: dict[int, float], metodologia: dict[int, float | None],
) -> dict[int, float | None]:
    """Só o que MUDA: campo vazio ou igual à metodologia remove o ajuste que havia (`None`) e nada faz se não havia;
    valor novo vira ajuste; igual ao vigente não grava. `ValueError` cita o mês do campo inválido."""

    saida: dict[int, float | None] = {}
    for mes, texto in digitado.items():
        try:
            valor = ler_valor_brl(texto)
        except ValueError as erro:
            raise ValueError(f"{MESES[mes - 1]}: {erro}") from erro
        metodo = metodologia.get(mes)
        igual_metodologia = valor is not None and metodo is not None and abs(valor - metodo) < _TOLERANCIA
        if valor is None or igual_metodologia:
            if mes in vigente:
                saida[mes] = None
        elif mes not in vigente or abs(valor - vigente[mes]) >= _TOLERANCIA:
            saida[mes] = valor
    return saida


def _mil(valor: float) -> str:
    return f"{valor / 1000:,.1f} mil".replace(",", "X").replace(".", ",").replace("X", ".")


def _celula(relatorio: RelatorioProjecaoExecucao, indice: int, mes: int) -> str:
    tipo = relatorio.mensal.at[indice, f"t{mes}"]
    realizado = relatorio.mensal.at[indice, f"r{mes}"]
    nome = MESES[mes - 1].lower()
    if tipo in (TIPO_PROJETADO, TIPO_RESTANTE_ABERTO):
        projetado = relatorio.mensal.at[indice, f"p{mes}"]
        esperado = relatorio.mensal.at[indice, f"e{mes}"]
        liquidado = 0.0 if pd.isna(realizado) else float(realizado)
        ajustado = bool(relatorio.mensal.at[indice, f"a{mes}"])
        classe = "k-aberto" if tipo == TIPO_RESTANTE_ABERTO else "k-proj"
        titulo = (
            f"{nome}: esperado {formatar_brl(float(esperado))} − liquidado {formatar_brl(liquidado)} = projetado "
            f"{formatar_brl(float(projetado))}" + (" (esperado ajustado por você)" if ajustado else "")
        )
        texto = _mil(float(projetado)) + ("*" if liquidado_abatido(relatorio, indice, mes) else "") + (" ✎" if ajustado else "")
        return f'<td class="c {classe}{" k-edit" if ajustado else ""}" title="{escape(titulo)}">{texto}</td>'
    if tipo == TIPO_REALIZADO and not pd.isna(realizado):
        return f'<td class="c k-real" title="{escape(f"{nome}: realizado {formatar_brl(float(realizado))}")}">{_mil(float(realizado))}</td>'
    return '<td class="k-vazio">—</td>'


def html_matriz(relatorio: RelatorioProjecaoExecucao) -> str:
    """Matriz NE × 12 meses; a última coluna e a linha final somam só o projetado (o realizado não entra)."""

    cabecalho = "".join(f"<th>{m.lower()}</th>" for m in MESES)
    corpo, totais = [], [0.0] * 12
    for indice, linha in relatorio.linhas.iterrows():
        celulas, soma = [], 0.0
        for mes in range(1, 13):
            celulas.append(_celula(relatorio, indice, mes))
            projetado = relatorio.mensal.at[indice, f"p{mes}"]
            if relatorio.mensal.at[indice, f"t{mes}"] in (TIPO_PROJETADO, TIPO_RESTANTE_ABERTO) and not pd.isna(projetado):
                soma += float(projetado)
                totais[mes - 1] += float(projetado)
        numero = escape("—" if pd.isna(linha["contrato_numero"]) or not str(linha["contrato_numero"]).strip() else str(linha["contrato_numero"]))
        fornecedor = escape("" if pd.isna(linha["fornecedor"]) else str(linha["fornecedor"]))
        corpo.append(
            f'<tr><td class="t"><b>{numero}</b><small>{fornecedor}</small> <i>{escape(str(linha["ne_curta"]))}</i></td>'
            f'{"".join(celulas)}<td><b>{_mil(soma)}</b></td></tr>'
        )
    total_geral = sum(totais)
    corpo.append(
        '<tr class="tot"><td>Total projetado</td>'
        + "".join(f"<td>{_mil(v) if v else '—'}</td>" for v in totais) + f"<td>{_mil(total_geral)}</td></tr>"
    )
    return (
        f'<table class="pe-m"><thead><tr><th>Contrato</th>{cabecalho}<th>Projetado até dez.</th></tr></thead>'
        f'<tbody>{"".join(corpo)}</tbody></table>'
    )


def html_legenda() -> str:
    itens = (
        ("k-real", "Realizado"), ("k-proj", "Projetado"), ("k-aberto", "Restante de mês em aberto"),
        ("k-proj k-edit", "Esperado ajustado por você ✎"),
    )
    spans = "".join(f'<span class="pe-m"><span class="c {c}" style="padding:1px 8px;border-radius:4px;margin-right:8px">{t}</span></span>' for c, t in itens)
    return (
        f'<div class="pe-leg">{spans}<span>* liquidado do mês já abatido (esperado − liquidado) · valores em mil</span></div>'
    )


# ------------------------------------------------------------------ tela
def _formatar_campo(valor: float) -> str:
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _ne_rotulo(linha: pd.Series) -> str:
    """Rótulo do seletor: `<NE> — <fornecedor> — Contrato <nº>`."""

    numero, fornecedor = titulo_contrato(linha["contrato_numero"], linha["fornecedor"]).split(" — ", 1)
    return f"{linha['ne_curta']} — {fornecedor} — {numero}"


def _limpar_campos(chave: str, ne: str | None) -> None:
    prefixo = f"{chave}_pe_campo_" + (f"{ne}_" if ne else "")
    for k in [k for k in list(st.session_state.keys()) if isinstance(k, str) and k.startswith(prefixo)]:
        del st.session_state[k]


def _cb_gravar(chave: str, exercicio: int, extracao: str, ne: str, meses: list[int], vigente: dict, metodologia: dict) -> None:
    digitado = {m: st.session_state.get(f"{chave}_pe_campo_{ne}_{m}", "") for m in meses}
    try:
        valores = valores_para_gravar(digitado, vigente, metodologia)
        if not valores:
            st.session_state[f"{chave}_pe_msg"] = ("info", "Nada mudou: nenhum ajuste gravado.")
            return
        registrar_ajustes(exercicio=exercicio, ne_curta=ne, valores=valores, extracao=extracao)
    except (ValueError, ErroAjuste) as erro:
        st.session_state[f"{chave}_pe_msg"] = ("erro", str(erro))
        return
    _limpar_campos(chave, ne)
    st.session_state[f"{chave}_pe_msg"] = ("ok", f"{len(valores)} mês(es) gravado(s) para {ne}. A projeção já usa os novos valores.")


def _cb_refazer_ne(chave: str, exercicio: int, extracao: str, ne: str) -> None:
    try:
        refazer_ne(exercicio=exercicio, ne_curta=ne, extracao=extracao)
    except ErroAjuste as erro:
        st.session_state[f"{chave}_pe_msg"] = ("erro", str(erro))
        return
    _limpar_campos(chave, ne)
    st.session_state[f"{chave}_pe_msg"] = ("ok", f"{ne} refeita pela metodologia (o histórico dos ajustes continua gravado).")


def _cb_refazer_tudo(chave: str, exercicio: int, extracao: str) -> None:
    try:
        refazer_tudo(exercicio=exercicio, extracao=extracao)
    except ErroAjuste as erro:
        st.session_state[f"{chave}_pe_msg"] = ("erro", str(erro))
        return
    _limpar_campos(chave, None)
    st.session_state[f"{chave}_pe_confirma_tudo"] = False
    st.session_state[f"{chave}_pe_msg"] = ("ok", "Todas as NEs do exercício refeitas pela metodologia.")


def render_edicao_projecao(relatorio: RelatorioProjecaoExecucao, exercicio: int, extracao: str, chave: str) -> None:
    """Expansor "Editar a projeção pela execução": matriz de leitura e edição por NE. `extracao` é o hash curto da Execução
    Mensal vigente (guardado em cada evento). Log de ajustes ilegível: erro visível e nada é gravado."""

    with st.expander("Editar a projeção pela execução", expanded=False):
        if relatorio.linhas.empty:
            st.caption("Sem NE no relatório: não há o que editar.")
            return
        try:
            vigentes = ajustes_vigentes(exercicio)
        except ErroAjuste as erro:
            st.error(f"Não foi possível ler os ajustes gravados: {erro}")
            return
        meses = meses_editaveis(relatorio)
        st.markdown(CSS, unsafe_allow_html=True)
        st.caption(
            "O número que você grava é o ESPERADO TOTAL do mês: o sistema continua descontando o liquidado do mês. Vale "
            "no relatório, na Necessidade (modo projeção pela execução) e no Resultado Orçamentário. Quando o mês fechar, "
            "vale o realizado."
        )
        st.markdown(html_legenda() + html_matriz(relatorio), unsafe_allow_html=True)
        for tipo, texto in ([st.session_state.pop(f"{chave}_pe_msg")] if f"{chave}_pe_msg" in st.session_state else []):
            {"ok": st.success, "erro": st.error, "info": st.info}[tipo](texto)
        if not meses:
            st.caption("Exercício encerrado: a projeção não é editada.")
            return

        linhas = relatorio.linhas.reset_index(drop=True)
        rotulos = {linha["ne_curta"]: _ne_rotulo(linha) for _, linha in linhas.iterrows()}
        ne = st.selectbox("NE", list(rotulos), format_func=rotulos.get, key=f"{chave}_pe_ne")
        indice = relatorio.linhas.index[relatorio.linhas["ne_curta"] == ne][0]
        linha = relatorio.linhas.loc[indice]
        st.markdown(f"**{titulo_contrato(linha['contrato_numero'], linha['fornecedor'])}** · NE {ne}")
        vigente = vigentes.get(ne, {})
        metodologia = {m: (None if pd.isna(relatorio.mensal.at[indice, f"m{m}"]) else float(relatorio.mensal.at[indice, f"m{m}"])) for m in meses}
        superados = relatorio.superados.get(ne, [])
        if superados:
            st.markdown(
                f'<div class="pe-aviso">Ajuste superado (mês já fechado; vale o realizado): '
                f'{", ".join(MESES[m - 1] for m in superados if 1 <= m <= 12)}.</div>', unsafe_allow_html=True,
            )
        colunas = st.columns([1, 2, 2, 2, 2])
        for rotulo, coluna in zip(("Mês", "Metodologia (esperado)", "Seu ajuste (esperado)", "Liquidado no mês", "Projetado"), colunas):
            coluna.markdown(f"**{rotulo}**")
        for mes in meses:
            c_mes, c_met, c_aj, c_liq, c_proj = st.columns([1, 2, 2, 2, 2])
            realizado = relatorio.mensal.at[indice, f"r{mes}"]
            projetado = relatorio.mensal.at[indice, f"p{mes}"]
            metodo = metodologia[mes]
            c_mes.markdown(f"**{MESES[mes - 1]}/{exercicio}**")
            c_met.write(formatar_brl(metodo) if metodo is not None else "metodologia não projeta")
            c_aj.text_input(
                f"Esperado de {MESES[mes - 1]}", value=_formatar_campo(vigente[mes]) if mes in vigente else "",
                placeholder="sem ajuste" if metodo is not None else "informar esperado",
                key=f"{chave}_pe_campo_{ne}_{mes}", label_visibility="collapsed",
            )
            c_liq.write(formatar_brl(float(realizado)) if not pd.isna(realizado) else "sem registro")
            c_proj.write(formatar_brl(float(projetado)) if not pd.isna(projetado) else "realizado / —")
        st.button(
            "Gravar ajustes desta NE", key=f"{chave}_pe_gravar", type="primary", on_click=_cb_gravar,
            args=(chave, exercicio, extracao, ne, meses, vigente, metodologia),
        )
        st.button(
            "Refazer esta NE pela metodologia", key=f"{chave}_pe_refazer_ne", on_click=_cb_refazer_ne,
            args=(chave, exercicio, extracao, ne), disabled=not vigente,
        )
        confirma = st.checkbox("Confirmo refazer TODAS as NEs do exercício pela metodologia", key=f"{chave}_pe_confirma_tudo")
        st.button(
            "Refazer todas do exercício", key=f"{chave}_pe_refazer_tudo", on_click=_cb_refazer_tudo,
            args=(chave, exercicio, extracao), disabled=not (confirma and vigentes),
        )
