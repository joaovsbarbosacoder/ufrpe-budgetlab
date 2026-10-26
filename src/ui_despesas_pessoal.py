"""Adaptador de apresentação do HTML Acompanhamento de Pessoal.

Não altera projeções: prepara os resultados do módulo de pessoal para uma tabela
HTML única. As duas seções ainda sem mapeamento ficam explícitas, sem valores
fictícios. A dotação não é rateada por natureza (a base não tem essa dimensão).
"""
from __future__ import annotations

import calendar
import math
from pathlib import Path

import pandas as pd
from streamlit.components.v2 import component

from src import design_tokens as tokens
from src.despesas_pessoal import (
    ACAO_ASSISTENCIA_MEDICA, ACAO_BENEFICIOS_OBRIGATORIOS,
    GRUPO_ATIVO, GRUPO_INATIVO, GRUPO_RPPS, GRUPO_OUTROS_BENEFICIOS,
    REGRA_DECIMO_TERCEIRO, REGRA_PROPORCAO_HISTORICA,
    LINHA_TOTAL, ResultadoGradeMensal, execucao_ano_anterior, execucao_ano_anterior_beneficios, resumo_quadro_beneficios,
    valor_mes_referencia, valor_mes_referencia_beneficios,
    regra_para_natureza, saldo_remanescente, saldo_remanescente_beneficios_por_acao,
)
from src.ui_despesas_pessoal_abas import aviso_faixa_historica

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "despesas_pessoal"
_COMPONENTE_PESSOAL = component(
    "ufrpe_acompanhamento_pessoal",
    html='<div id="pessoal"></div>',
    css=(ASSETS / "painel.css").read_text(encoding="utf-8"),
    js=(ASSETS / "painel.js").read_text(encoding="utf-8"),
)
GRUPOS = {
    GRUPO_ATIVO: "ATIVO", GRUPO_INATIVO: "INATIVO",
    GRUPO_RPPS: "RPPS — AÇÃO 09HB", GRUPO_OUTROS_BENEFICIOS: "OUTROS BENEFÍCIOS",
}
ESPECIAIS = {REGRA_DECIMO_TERCEIRO, REGRA_PROPORCAO_HISTORICA}
#: decisão 12 (22/09/2026) — nomes das 2 ações que compõem Outros Benefícios, usados só
#: pra separar as linhas do Saldo Remanescente (o resto do painel continua agrupado).
_NOMES_ACAO_BENEFICIOS = {
    ACAO_ASSISTENCIA_MEDICA: "2004 — ASSISTÊNCIA MÉDICA/ODONTOLÓGICA",
    ACAO_BENEFICIOS_OBRIGATORIOS: "212B — BENEFÍCIOS OBRIGATÓRIOS",
}


def numero(valor):
    return None if valor is None or pd.isna(valor) else float(valor)


def soma(valores):
    conhecidos = [numero(v) for v in valores if numero(v) is not None]
    return sum(conhecidos) if conhecidos else None


def _contexto(df, medida):
    """Mesmas chaves da grade consolidada, sem misturar 13º/férias à rubrica mãe."""
    resultado = {}
    for r in df.itertuples(index=False):
        regra = regra_para_natureza(r.natureza_despesa_cod, r.natureza_detalhada_cod)
        especial = regra is not None and regra.tipo in ESPECIAIS
        detalhe = r.natureza_detalhada_cod if especial else r.natureza_despesa_cod
        chave = (r.grupo, r.natureza_despesa_cod, detalhe)
        resultado.setdefault(chave, []).append(getattr(r, medida))
    return {chave: soma(valores) for chave, valores in resultado.items()}


def _contexto_beneficios(df, medida):
    """Como `_contexto`, mas para `execucao_ano_anterior_beneficios`/
    `valor_mes_referencia_beneficios` — já vêm uma linha por (grupo, acao_cod, po_cod),
    sem a distinção "especial" (não existe sub-rubrica de 13º/proporção histórica no
    nível de Plano Orçamentário — ver seção 11 de `despesas_pessoal.py`)."""
    resultado = {}
    for r in df.itertuples(index=False):
        chave = (r.grupo, r.natureza_despesa_cod, r.natureza_detalhada_cod)
        resultado.setdefault(chave, []).append(getattr(r, medida))
    return {chave: soma(valores) for chave, valores in resultado.items()}


def _cartoes(grupos, mes, saldos_por_grupo, saldos_beneficios_df, dotacao_por_acao_beneficios, faixa):
    """Cartão por grupo da visão geral (27/10/2026, novo visual aprovado): executado até a data-base, projetado
    depois dela, total, dotação, saldo e — com `faixa` (`faixa_historica_total_anual`) — mínimo/máximo históricos e
    o saldo no pior caso. Nulo continua nulo (sem dotação ou sem faixa, o campo derivado fica `None`, nunca zero)."""
    faixa = faixa.set_index("grupo") if faixa is not None and not faixa.empty else None
    cartoes = []
    for g in grupos:
        if g.get("pendente") or g.get("subtotal"):
            continue
        executado = soma(g["meses"][:mes])
        projetado = soma(g["meses"][mes:])
        faixa_min = faixa_max = None
        if faixa is not None and g["key"] in faixa.index:
            faixa_min, faixa_max = numero(faixa.loc[g["key"], "total_min"]), numero(faixa.loc[g["key"], "total_max"])
        dot = g["dotacao"]
        saldo_serie = saldos_por_grupo.get(g["key"]) or [None] * 12
        cartao = {
            "key": g["key"], "nome": g["nome"], "executado": executado, "projetado": projetado, "total": g["total"],
            "dotacao": dot, "saldo": saldo_serie[11], "faixaMin": faixa_min, "faixaMax": faixa_max,
            "pior": None if dot is None or faixa_max is None else dot - faixa_max, "acoes": [],
        }
        if g["key"] == GRUPO_OUTROS_BENEFICIOS and not saldos_beneficios_df.empty:
            for acao_cod, nome in _NOMES_ACAO_BENEFICIOS.items():
                registro = saldos_beneficios_df.loc[saldos_beneficios_df["acao_cod"] == acao_cod]
                cartao["acoes"].append({
                    "nome": nome, "dotacao": numero(dotacao_por_acao_beneficios.get(acao_cod)),
                    "saldo": numero(registro.iloc[0]["meses"][11]) if not registro.empty else None,
                })
        cartoes.append(cartao)
    return cartoes


_MEDIDAS_BENEFICIOS = ("dotacao", "empenhada", "executado", "projetado", "total", "saldo", "empenho_saldo",
                       "total_media", "saldo_media", "empenho_saldo_media")


def _beneficios_po(quadro):
    """Quadro de Outros Benefícios por Ação/PO/Iduso (`despesas_pessoal.quadro_beneficios_por_po_iduso`) em
    JSON, com subtotais por ação e por Iduso — `None` sem quadro (a seção não aparece)."""
    if quadro is None or quadro.empty:
        return None

    def registros(df, rotulo):
        return [{"rotulo": rotulo(r), **{m: numero(r[m]) for m in _MEDIDAS_BENEFICIOS}} for _, r in df.iterrows()]

    acoes = {**{a: n for a, n in _NOMES_ACAO_BENEFICIOS.items()}}
    linhas = [{
        "acao": r["acao"], "po": r["po"], "poDesc": None if pd.isna(r["po_desc"]) else str(r["po_desc"]),
        "iduso": r["iduso"], **{m: numero(r[m]) for m in _MEDIDAS_BENEFICIOS},
    } for _, r in quadro.iterrows()]
    idusos = {r["iduso"]: (None if pd.isna(r["iduso_desc"]) else str(r["iduso_desc"])) for _, r in quadro.iterrows()}
    por_acao = resumo_quadro_beneficios(quadro, "acao")
    por_iduso = resumo_quadro_beneficios(quadro, "iduso")
    return {
        "linhas": linhas,
        "porAcao": registros(por_acao.loc[por_acao["acao"] != LINHA_TOTAL], lambda r: acoes.get(r["acao"], r["acao"])),
        "porIduso": registros(por_iduso.loc[por_iduso["iduso"] != LINHA_TOTAL],
                              lambda r: f"Iduso {r['iduso']}" + (f" — {idusos[r['iduso']]}" if idusos.get(r["iduso"]) else "")),
        "total": registros(por_acao.loc[por_acao["acao"] == LINHA_TOTAL], lambda r: "Total")[0],
    }


def montar_painel(grade: ResultadoGradeMensal, mensal, anual, dotacao, ano_dotacao,
                  *, meses_disponiveis, anos_dotacao, procedencia="", editados=None,
                  dotacao_por_plano_orcamentario=None, dotacao_por_acao_beneficios=None, faixa=None,
                  quadro_beneficios=None):
    """Dados JSON da interface; todos os valores vêm das bases/processamento atual.

    `dotacao_por_plano_orcamentario` (opcional): `pd.Series` indexada por
    `(acao_cod, po_cod)` — pedido do usuário (10/09/2026): a Dotação Anual TEM a
    dimensão Plano Orçamentário, então os filhos de Outros Benefícios (que `grade` já
    traz por PO, ver `despesas_pessoal.grade_mensal_beneficios`) mostram dotação
    própria, diferente dos outros 3 grupos (Ativo/Inativo/RPPS ficam sem essa
    dimensão na base, `dotacao` continua `None` por rubrica para eles).

    `dotacao_por_acao_beneficios` (opcional): `pd.Series` indexada por `acao_codigo`
    (`despesas_pessoal.dotacao_atualizada_por_acao_beneficios`) — decisão 12
    (22/09/2026): separa o Saldo Remanescente de Outros Benefícios em 2 linhas (2004/
    212B) em vez de uma só. Não afeta os cartões por grupo, só a seção de saldo.

    `faixa` (opcional): `despesas_pessoal.faixa_historica_total_anual` já calculada — alimenta a faixa e o pior caso
    de cada cartão e o aviso "Cenário histórico" (`avisoFaixa`), ambos dentro do componente desde o novo visual
    (27/10/2026).

    `quadro_beneficios` (opcional): `despesas_pessoal.quadro_beneficios_por_po_iduso` — vira `beneficiosPo`, o
    quadro de Outros Benefícios por Ação, PO e Iduso da visão geral (27/10/2026)."""
    historico = execucao_ano_anterior(anual, grade.ano - 1)
    referencia = valor_mes_referencia(mensal, grade.ano_mes_referencia)
    exec_por_chave = _contexto(historico, "execucao_ano_anterior")
    ref_por_chave = _contexto(referencia, "valor_mes_referencia")
    # Outros Benefícios: `grade` já veio por Plano Orçamentário (não por Natureza), então
    # o histórico/referência por rubrica também precisa ser por PO — senão as chaves não
    # batem e execAnt/basePloa ficam vazios pra esse grupo inteiro.
    exec_por_chave.update(_contexto_beneficios(execucao_ano_anterior_beneficios(anual, grade.ano - 1), "execucao_ano_anterior"))
    ref_por_chave.update(_contexto_beneficios(valor_mes_referencia_beneficios(mensal, grade.ano_mes_referencia), "valor_mes_referencia"))
    exec_grupo = historico.groupby("grupo")["execucao_ano_anterior"].sum(min_count=1)
    ref_grupo = referencia.groupby("grupo")["valor_mes_referencia"].sum(min_count=1)
    totais = grade.total_por_grupo_por_mes()
    editados = editados or {}
    dotacao_por_plano_orcamentario = dotacao_por_plano_orcamentario if dotacao_por_plano_orcamentario is not None else pd.Series(dtype=float)
    grupos = []
    for chave, nome in GRUPOS.items():
        filhos = []
        linhas = grade.linhas.loc[grade.linhas["grupo"] == chave]
        for r in linhas.sort_values(["natureza_despesa_cod", "natureza_detalhada_cod"]).itertuples(index=False):
            id_rubrica = (chave, r.natureza_despesa_cod, r.natureza_detalhada_cod)
            especial = r.regra_aplicada in ESPECIAIS
            # Outros Benefícios: sem sub-rubrica "especial" (13º/proporção histórica não
            # existe no nível de PO) — sempre mostra o código do PO, não o da Ação (a
            # Ação já está implícita no grupo/aba).
            codigo = r.natureza_detalhada_cod if (especial or chave == GRUPO_OUTROS_BENEFICIOS) else r.natureza_despesa_cod
            dotacao_rubrica = (
                numero(dotacao_por_plano_orcamentario.get((r.natureza_despesa_cod, r.natureza_detalhada_cod)))
                if chave == GRUPO_OUTROS_BENEFICIOS else None
            )
            filhos.append({
                "key": list(id_rubrica), "nome": f"{r.natureza_detalhada_desc} · {codigo}", "regra": r.regra_aplicada,
                "meses": [numero(v) for v in r.meses], "total": soma(r.meses),
                "dotacao": dotacao_rubrica, "execAnt": exec_por_chave.get(id_rubrica),
                "basePloa": None if especial else ref_por_chave.get(id_rubrica),
                "editados": list(editados.get(id_rubrica, {})),
            })
        meses = [numero(v) for v in totais.loc[chave]] if chave in totais.index else [None] * 12
        grupos.append({"key": chave, "nome": nome, "meses": meses, "total": soma(meses),
                       "dotacao": numero(dotacao.get(chave)), "execAnt": numero(exec_grupo.get(chave)),
                       "basePloa": numero(ref_grupo.get(chave)), "children": filhos})

    def subtotal(chave, nome, membros):
        gs = [g for g in grupos if g["key"] in membros]
        meses = [soma(g["meses"][m] for g in gs) for m in range(12)]
        return {"key": chave, "nome": nome, "meses": meses, "total": soma(meses),
                **{col: soma(g[col] for g in gs) for col in ("dotacao", "execAnt", "basePloa")},
                "subtotal": True}

    # Estrutura da referência; sem códigos definidos não se presume zero nem
    # se extrai Benefício Especial do grupo Inativo por descrição heurística.
    def pendente(chave, nome, filho):
        return {"key": chave, "nome": nome, "meses": [None] * 12, "total": None,
                "dotacao": None, "execAnt": None, "basePloa": None, "pendente": True,
                "children": [{"nome": filho + " · mapeamento pendente", "meses": [None] * 12,
                              "total": None, "dotacao": None, "execAnt": None, "basePloa": None}]}

    total = subtotal("total", "TOTAL", list(GRUPOS))
    ordem = [grupos[0], grupos[1],
             pendente("beneficioEspecial", "BENEFÍCIO ESPECIAL", "BENEFÍCIO ESPECIAL LEI 12.618/2012 — INATIVO"),
             pendente("precat", "PRECAT E SENT EMP PUBLICA", "DESP. PRIMÁRIAS"),
             subtotal("primarias", "SUBTOTAL DESP PRIMÁRIAS", [GRUPO_ATIVO, GRUPO_INATIVO]),
             grupos[2], subtotal("financeiras", "SUBTOTAL DESP FINANCEIRAS", [GRUPO_RPPS]),
             grupos[3], total]
    saldos_df = saldo_remanescente(grade, dotacao)
    dotacao_por_acao_beneficios = (
        dotacao_por_acao_beneficios if dotacao_por_acao_beneficios is not None else pd.Series(dtype=float)
    )
    saldos_beneficios_df = saldo_remanescente_beneficios_por_acao(grade, dotacao_por_acao_beneficios)
    saldos = []
    chaves_beneficios_por_acao = []
    for grupo in ordem:
        if grupo.get("subtotal"):
            continue
        if grupo["key"] == GRUPO_OUTROS_BENEFICIOS:
            # Decisão 12: Outros Benefícios vira 2 linhas de saldo (2004/212B) em vez
            # de uma só — o cartão do grupo em si (acima) continua junto.
            for acao_cod, nome in _NOMES_ACAO_BENEFICIOS.items():
                registro = saldos_beneficios_df.loc[saldos_beneficios_df["acao_cod"] == acao_cod] if not saldos_beneficios_df.empty else pd.DataFrame()
                valores = [numero(v) for v in registro.iloc[0]["meses"]] if not registro.empty else [None] * 12
                chave = f"beneficios_{acao_cod}"
                chaves_beneficios_por_acao.append(chave)
                saldos.append({"key": chave, "nome": "Saldo " + nome, "meses": valores})
            continue
        registro = saldos_df.loc[saldos_df["grupo"] == grupo["key"]] if not saldos_df.empty else pd.DataFrame()
        valores = [numero(v) for v in registro.iloc[0]["meses"]] if not registro.empty else [None] * 12
        saldos.append({"key": grupo["key"], "nome": "Saldo " + grupo["nome"], "meses": valores})
    saldos_reais = [s for s in saldos if s["key"] in GRUPOS or s["key"] in chaves_beneficios_por_acao]
    saldo_total = [soma(s["meses"][m] for s in saldos_reais) for m in range(12)]
    saldos.append({"key": "total", "nome": "Saldo Total", "meses": saldo_total, "subtotal": True})
    deficits = [s for s in saldos_reais if any(v is not None and v < 0 for v in s["meses"])]
    if grade.erros:
        aviso = {"tipo": "error", "texto": "Grade incompleta: há rubricas sem regra de projeção. Consulte as notas."}
    elif deficits:
        nomes = "; ".join(s["nome"] for s in deficits)
        aviso = {"tipo": "error", "texto": f"{nomes}: saldo projeta déficit até dezembro/{grade.ano}."}
    elif any(g["dotacao"] is None or g["total"] is None for g in grupos):
        aviso = {"tipo": "warning", "texto": "Comparação incompleta: há grupos sem dotação ou execução disponível."}
    else:
        aviso = {"tipo": "success", "texto": f"Dotação suficiente nos grupos calculados até dezembro/{grade.ano}, na projeção atual."}

    saldos_por_grupo = {
        r.grupo: [numero(v) for v in r.meses] for r in saldos_df.itertuples(index=False)
    } if not saldos_df.empty else {}
    cartoes = _cartoes(grupos, grade.ano_mes_referencia % 100, saldos_por_grupo, saldos_beneficios_df,
                       dotacao_por_acao_beneficios, faixa)
    serie_saldo = [{"key": c["key"], "nome": c["nome"], "meses": saldos_por_grupo.get(c["key"], [None] * 12)} for c in cartoes]
    aviso_faixa = aviso_faixa_historica(faixa, dotacao, grade.ano) if faixa is not None else None

    reconciliado = soma(f["execAnt"] for g in grupos for f in g["children"])
    validado = soma(exec_grupo)
    diferenca = None if reconciliado is None or validado is None else reconciliado - validado
    mes = grade.ano_mes_referencia % 100
    return {
        "ano": grade.ano, "mes": mes, "referencia": grade.ano_mes_referencia, "anoDotacao": int(ano_dotacao),
        "dataBase": f"{calendar.monthrange(grade.ano, mes)[1]:02d}/{mes:02d}/{grade.ano}",
        "mesesDisponiveis": [int(v) for v in meses_disponiveis], "anosDotacao": [int(v) for v in anos_dotacao],
        # Seletor de Exercício (pedido do usuário, 10/09/2026 — "não quero que atravesse
        # exercícios, queria um botão para selecionar o exercício"): anos com pelo menos um
        # mês de execução real na base — a lista de "mês de referência" no componente é
        # sempre filtrada por um exercício escolhido explicitamente, nunca mistura anos.
        "anosExecucao": sorted({int(v) // 100 for v in meses_disponiveis}),
        "grupos": ordem, "saldos": saldos, "total": total, "saldoDezembro": saldo_total[11],
        "cartoes": cartoes, "serieSaldo": serie_saldo, "avisoFaixa": aviso_faixa,
        "beneficiosPo": _beneficios_po(quadro_beneficios),
        "aviso": aviso, "erros": grade.erros, "alertas": grade.alertas,
        "reconciliacao": {"rubricas": reconciliado, "base": validado, "diferenca": diferenca},
        "procedencia": procedencia, "temEdicoes": bool(editados),
        "cores": {"bg": tokens.BG, "text": tokens.TEXT, "divider": tokens.BORDER,
                  "surface": tokens.SURFACE, "muted": tokens.TEXT_MUTED,
                  "accent": tokens.ACCENT, "strong": tokens.ACCENT_STRONG,
                  # `getattr` mantém compatibilidade com um processo Streamlit que
                  # ainda tenha a versão anterior do módulo em memória; após a
                  # recarga, usa exatamente as cores do HTML de referência.
                  "red": getattr(tokens, "PESSOAL_NEGATIVE", tokens.NEGATIVE),
                  "green": getattr(tokens, "PESSOAL_POSITIVE", tokens.POSITIVE)},
    }


def validar_edicao(evento, grade):
    """Aceita só chaves existentes e meses futuros finitos; valida também no servidor."""
    if not isinstance(evento, dict) or evento.get("referencia") != grade.ano_mes_referencia:
        raise ValueError("A data-base da edição não corresponde à grade atual.")
    chave = evento.get("chave")
    if not isinstance(chave, list) or len(chave) != 3 or not all(isinstance(v, str) for v in chave):
        raise ValueError("Rubrica inválida.")
    chave = tuple(chave)
    chaves = set(grade.linhas[["grupo", "natureza_despesa_cod", "natureza_detalhada_cod"]].itertuples(index=False, name=None))
    if chave not in chaves:
        raise ValueError("Rubrica não encontrada na grade atual.")
    mes = evento.get("mes")
    if type(mes) is not int or not grade.ano_mes_referencia % 100 < mes <= 12:
        raise ValueError("Somente meses projetados podem ser editados.")
    valor = evento.get("valor")
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ValueError("Informe um valor numérico finito.")
    return chave, mes, float(valor)


def render_painel(dados):
    """Monta a instância CCv2 já registrada no carregamento do módulo."""
    return _COMPONENTE_PESSOAL(
        data=dados,
        key="dp_painel",
        on_edicao_change=lambda: None,
        on_filtros_change=lambda: None,
        on_restaurar_change=lambda: None,
    )
