"""Blocos visuais da página Despesas de Pessoal sem cara de planilha (27/10/2026).

Funções puras que devolvem HTML (texto sempre escapado) e o CSS compartilhado, para `st.html`.
Cartões, indicadores, barras e listas no lugar de tabelas de linhas e colunas, na linguagem do
painel de Pessoal (`design_tokens`). Não calcula nada: recebe os valores já prontos.
Classes com prefixo `cd-`. `<details>` faz o recolher/expandir sem JavaScript.
"""
from __future__ import annotations

from html import escape

from src import design_tokens as t

TONS = {"azul": t.ACCENT, "verde": t.POSITIVE, "vermelho": t.NEGATIVE, "laranja": t.WARNING, "cinza": t.TEXT_FAINT}
FUNDOS = {"azul": t.ACCENT_SOFT, "verde": t.POSITIVE_SOFT, "vermelho": t.NEGATIVE_SOFT, "laranja": t.WARNING_SOFT,
          "cinza": "rgba(124,141,168,0.14)"}


def brl(valor) -> str:
    """R$ com centavos, padrão pt-BR; nulo vira "—" (nunca zero)."""
    if valor is None or valor != valor:
        return "—"
    centavos = round(float(valor), 2) + 0.0
    texto = f"{abs(centavos):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("−" if centavos < 0 else "") + "R$ " + texto


def _e(valor) -> str:
    return escape("" if valor is None else str(valor))


CSS = f"""<style>
.cd-kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:14px; margin:6px 0 10px; }}
.cd-kpi {{ background:{t.SURFACE}; border:1px solid {t.BORDER}; border-top:4px solid var(--c,{t.ACCENT}); border-radius:{t.RADIUS}; padding:15px 18px; }}
.cd-kpi .rot {{ font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:{t.TEXT_MUTED}; }}
.cd-kpi .val {{ font-size:26px; font-weight:700; color:{t.TEXT}; margin-top:4px; font-variant-numeric:tabular-nums; line-height:1.15; }}
.cd-kpi .sub {{ font-size:12px; color:{t.TEXT_MUTED}; margin-top:3px; }}
.cd-secao {{ font-size:16px; font-weight:700; color:{t.TEXT}; margin:28px 0 2px; }}
.cd-sub {{ font-size:12.5px; color:{t.TEXT_MUTED}; margin:0 0 12px; max-width:980px; line-height:1.5; }}
.cd-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(440px,1fr)); gap:14px; }}
.cd-card {{ background:{t.SURFACE}; border:1px solid {t.BORDER}; border-left:5px solid var(--c,{t.ACCENT}); border-radius:{t.RADIUS}; padding:14px 18px; min-width:0; }}
.cd-top {{ display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }}
.cd-card h4 {{ margin:0; font-size:15px; font-weight:700; color:{t.TEXT}; }}
.cd-meta {{ font-size:11.5px; color:{t.TEXT_MUTED}; margin-top:2px; }}
.cd-pill {{ display:inline-block; font-size:11.5px; font-weight:600; padding:3px 10px; border-radius:999px; white-space:nowrap; color:var(--c); background:var(--f); }}
.cd-badge {{ display:inline-block; font-size:10.5px; font-weight:600; padding:1px 8px; border-radius:6px; margin-left:6px; color:{t.TEXT_MUTED}; background:{t.SURFACE_ALT}; vertical-align:middle; }}
.cd-bar {{ position:relative; height:10px; border-radius:999px; background:{t.SURFACE_ALT}; margin:12px 0 4px; overflow:hidden; }}
.cd-bar i {{ position:absolute; top:0; bottom:0; left:0; background:var(--c,{t.ACCENT}); }}
.cd-bar i.seg2 {{ background:var(--c2,{t.NEGATIVE}); }}
.cd-barlbl {{ font-size:11.5px; color:{t.TEXT_MUTED}; }}
.cd-figs {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px 16px; margin-top:12px; }}
.cd-figs div {{ font-size:11px; color:{t.TEXT_MUTED}; letter-spacing:.02em; }}
.cd-figs b {{ display:block; font-size:13.5px; color:{t.TEXT}; font-variant-numeric:tabular-nums; margin-top:1px; font-weight:600; }}
.cd-figs b.neg {{ color:{t.NEGATIVE}; }} .cd-figs b.pos {{ color:{t.POSITIVE}; }}
.cd-det {{ margin-top:12px; border-top:1px solid {t.BORDER}; padding-top:8px; }}
.cd-det summary {{ cursor:pointer; font-size:12px; color:{t.ACCENT}; list-style:none; }}
.cd-det summary::-webkit-details-marker {{ display:none; }}
.cd-det summary::before {{ content:"▸ "; }} .cd-det[open] summary::before {{ content:"▾ "; }}
.cd-itens {{ display:flex; flex-direction:column; gap:6px; margin-top:8px; }}
.cd-item {{ display:flex; justify-content:space-between; gap:12px; align-items:center; background:{t.SURFACE_ALT}; border-radius:{t.RADIUS_SM}; padding:7px 10px; }}
.cd-item .nome {{ font-size:12px; color:{t.TEXT}; min-width:0; }}
.cd-item .nome small {{ display:block; color:{t.TEXT_MUTED}; font-size:10.5px; }}
.cd-chips {{ display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; }}
.cd-chip {{ font-size:11px; padding:2px 8px; border-radius:999px; white-space:nowrap; font-variant-numeric:tabular-nums; color:var(--c); background:var(--f); }}
.cd-op {{ display:grid; grid-template-columns:minmax(0,1fr) 26px minmax(0,1fr) auto; gap:8px; align-items:center; padding:8px 0; border-top:1px solid {t.BORDER}; font-size:12px; }}
.cd-op:first-of-type {{ border-top:0; }}
.cd-op .lado small {{ display:block; color:{t.TEXT_MUTED}; font-size:10.5px; }}
.cd-op .seta {{ text-align:center; color:{t.TEXT_FAINT}; font-size:16px; }}
.cd-op .valor {{ font-weight:700; font-variant-numeric:tabular-nums; color:{t.TEXT}; white-space:nowrap; }}
.cd-passos {{ margin-top:10px; }}
.cd-passo {{ display:flex; justify-content:space-between; gap:12px; padding:5px 0; border-top:1px dashed {t.BORDER}; font-size:12px; color:{t.TEXT_MUTED}; }}
.cd-passo:first-child {{ border-top:0; }}
.cd-passo b {{ font-variant-numeric:tabular-nums; color:{t.TEXT}; font-weight:600; }}
.cd-passo.total {{ border-top:2px solid {t.BORDER}; color:{t.TEXT}; font-weight:600; }}
.cd-passo.total b {{ font-size:14px; }}
.cd-div {{ display:grid; grid-template-columns:minmax(150px,1.3fr) minmax(0,2fr) 130px; gap:10px; align-items:center; padding:5px 0; border-top:1px solid {t.BORDER}; font-size:12px; }}
.cd-div:first-of-type {{ border-top:0; }}
.cd-div .nome small {{ display:block; color:{t.TEXT_MUTED}; font-size:10.5px; }}
.cd-div .trilho {{ position:relative; height:10px; background:{t.SURFACE_ALT}; border-radius:999px; }}
.cd-div .trilho i {{ position:absolute; top:0; bottom:0; border-radius:999px; }}
.cd-div .trilho::after {{ content:""; position:absolute; left:50%; top:-2px; bottom:-2px; width:1px; background:{t.BORDER}; }}
.cd-div .valor {{ text-align:right; font-weight:600; font-variant-numeric:tabular-nums; }}
.cd-eq {{ display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:10px; font-variant-numeric:tabular-nums; }}
.cd-eq span {{ font-size:11px; color:{t.TEXT_MUTED}; display:block; }}
.cd-eq b {{ font-size:14px; color:{t.TEXT}; }}
.cd-eq .op {{ font-size:18px; color:{t.TEXT_FAINT}; }}
.cd-meses {{ display:grid; grid-template-columns:repeat(12,1fr); gap:5px; align-items:end; height:92px; margin-top:12px; }}
.cd-mes {{ display:flex; flex-direction:column; justify-content:flex-end; align-items:center; height:100%; }}
.cd-mes i {{ display:block; width:100%; border-radius:4px 4px 0 0; background:var(--c,{t.ACCENT}); min-height:2px; }}
.cd-mes.vazio i {{ background:{t.SURFACE_ALT}; height:2px !important; }}
.cd-mes span {{ font-size:9.5px; color:{t.TEXT_FAINT}; margin-top:3px; }}
.cd-vs {{ display:grid; grid-template-columns:78px minmax(0,1fr) 128px; gap:8px; align-items:center; margin-top:8px; font-size:12px; color:{t.TEXT_MUTED}; }}
.cd-vs .trilho {{ position:relative; height:10px; border-radius:999px; background:{t.SURFACE_ALT}; }}
.cd-vs .trilho i {{ position:absolute; left:0; top:0; bottom:0; border-radius:999px; }}
.cd-vs b {{ text-align:right; color:{t.TEXT}; font-variant-numeric:tabular-nums; font-weight:600; }}
.cd-faixa {{ position:relative; height:34px; margin:16px 4px 6px; }}
.cd-faixa .trilho {{ position:absolute; left:0; right:0; top:14px; height:6px; border-radius:999px; background:{t.SURFACE_ALT}; }}
.cd-faixa .banda {{ position:absolute; top:11px; height:12px; border-radius:6px; background:{t.WARNING_SOFT}; border:1px solid {t.WARNING}; }}
.cd-faixa .marca {{ position:absolute; top:4px; width:3px; height:26px; border-radius:2px; transform:translateX(-1px); }}
.cd-faixa .marca small {{ position:absolute; top:-14px; left:50%; transform:translateX(-50%); font-size:9.5px; white-space:nowrap; color:{t.TEXT_MUTED}; }}
.cd-hm {{ display:grid; gap:3px; margin-top:8px; font-size:12px; font-variant-numeric:tabular-nums; }}
.cd-hm-h {{ font-size:11px; color:{t.TEXT_MUTED}; text-align:center; padding:2px 0 4px; }}
.cd-hm-h:first-child {{ text-align:left; }}
.cd-hm-l {{ color:{t.TEXT}; display:flex; align-items:center; font-weight:600; }}
.cd-hm-c {{ text-align:center; padding:8px 4px; border-radius:{t.RADIUS_SM}; background:{t.SURFACE_ALT}; color:{t.TEXT}; }}
.cd-hm-c.vazio {{ color:{t.TEXT_FAINT}; background:transparent; border:1px dashed {t.BORDER}; }}
.cd-legenda {{ font-size:11px; color:{t.TEXT_MUTED}; display:flex; gap:14px; flex-wrap:wrap; margin-top:4px; }}
.cd-legenda i {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; vertical-align:-1px; }}
</style>"""


def kpis(itens: list[dict]) -> str:
    """Indicadores: cada item = {"rotulo", "valor", "sub" (opcional), "tom" (opcional)}."""
    cartoes = "".join(
        f'<div class="cd-kpi" style="--c:{TONS.get(i.get("tom", "azul"), t.ACCENT)}"><div class="rot">{_e(i["rotulo"])}</div>'
        f'<div class="val">{_e(i["valor"])}</div>' + (f'<div class="sub">{_e(i["sub"])}</div>' if i.get("sub") else "") + "</div>"
        for i in itens)
    return f'<div class="cd-kpis">{cartoes}</div>'


def secao(titulo: str, explicacao: str | None = None) -> str:
    return f'<div class="cd-secao">{_e(titulo)}</div>' + (f'<p class="cd-sub">{_e(explicacao)}</p>' if explicacao else "")


def pill(texto: str, tom: str) -> str:
    return f'<span class="cd-pill" style="--c:{TONS[tom]};--f:{FUNDOS[tom]}">{_e(texto)}</span>'


def chip(texto: str, tom: str) -> str:
    return f'<span class="cd-chip" style="--c:{TONS[tom]};--f:{FUNDOS[tom]}">{_e(texto)}</span>'


def _fig(rotulo: str, valor, classe: str = "") -> str:
    return f'<div>{_e(rotulo)}<b class="{classe}">{_e(brl(valor))}</b></div>'


def grade(cartoes: list[str]) -> str:
    return f'<div class="cd-grid">{"".join(cartoes)}</div>' if cartoes else ""


def cartao_empenho(nota: str, acao: str | None, saldo: float, folha: float, falta: float, sobra: float, coberto: float,
                   reforco_mes: float, reforco_dez: float, itens: list[dict], mes: str, ano: int, origem: str | None = None) -> str:
    """Um empenho: situação em destaque, barra do saldo × folha do mês, números e os itens (recolhidos).
    `itens` = [{"natureza", "descricao", "folha", "falta", "sobra"}]."""
    if reforco_dez > 0.004:
        tom = "vermelho" if reforco_mes > 0.004 else "laranja"
        situacao = pill(f"Reforço até dez: {brl(reforco_dez)}", tom)
    else:
        tom, situacao = "verde", pill("Sem reforço", "verde")
    cobertura = 1.0 if folha <= 0 else max(0.0, min(1.0, saldo / folha))
    barra = (f'<div class="cd-bar" style="--c:{t.POSITIVE};--c2:{t.NEGATIVE}"><i style="width:{cobertura * 100:.1f}%"></i>'
             f'<i class="seg2" style="left:{cobertura * 100:.1f}%;width:{(1 - cobertura) * 100:.1f}%"></i></div>')
    rotulo = (f'<div class="cd-barlbl">O saldo do empenho cobre {cobertura:.0%} da folha de {_e(mes)}'
              + (f" — falta {_e(brl(falta))}" if falta > 0.004 else "") + "</div>")
    figuras = "".join([
        _fig("Saldo do empenho", saldo), _fig(f"Folha de {mes}", folha), _fig("Falta para pagar a folha", falta, "neg" if falta > 0.004 else ""),
        _fig("Sobra que pode ser anulada", sobra, "pos" if sobra > 0.004 else ""), _fig("Coberto por remanejamento", coberto),
        _fig(f"Reforço para {mes}", reforco_mes, "neg" if reforco_mes > 0.004 else ""),
    ])
    linhas = ""
    for i in itens:
        chips = chip(f"folha {brl(i['folha'])}", "cinza")
        if i.get("falta", 0) > 0.004:
            chips += chip(f"falta {brl(i['falta'])}", "vermelho")
        if i.get("sobra", 0) > 0.004:
            chips += chip(f"sobra {brl(i['sobra'])}", "verde")
        linhas += (f'<div class="cd-item"><div class="nome">{_e(i["natureza"])} {_e(i.get("descricao") or "")}</div>'
                   f'<div class="cd-chips">{chips}</div></div>')
    detalhe = (f'<details class="cd-det"><summary>Itens do empenho ({len(itens)})</summary><div class="cd-itens">{linhas}</div></details>'
               if itens else "")
    badge = f'<span class="cd-badge">{_e(acao)}</span>' if acao else ""
    meta = f'<div class="cd-meta">{_e(origem)}</div>' if origem else ""
    return (f'<div class="cd-card" style="--c:{TONS[tom]}"><div class="cd-top"><div><h4>{_e(nota)}{badge}</h4>{meta}</div>{situacao}</div>'
            f'{barra}{rotulo}<div class="cd-figs">{figuras}</div>'
            f'<div class="cd-figs" style="grid-template-columns:1fr;margin-top:8px"><div>Reforço necessário até dez/{ano}'
            f'<b class="{"neg" if reforco_dez > 0.004 else ""}">{_e(brl(reforco_dez))}</b></div></div>{detalhe}</div>')


def cartao_operacoes(nota: str, acao: str | None, operacoes: list[dict]) -> str:
    """Plano de um empenho. `operacoes` = [{"tipo": "remanejar"|"reforco", "de", "de_desc", "para", "para_desc", "valor"}]."""
    linhas, total = "", 0.0
    for o in operacoes:
        total += o["valor"]
        origem = (f'<div class="lado">Cede<br><b>{_e(o["de"])}</b><small>{_e(o.get("de_desc") or "")}</small></div>'
                  if o["tipo"] == "remanejar" else '<div class="lado">Valor novo<small>reforço do empenho</small></div>')
        linhas += (f'<div class="cd-op">{origem}<div class="seta">➜</div>'
                   f'<div class="lado">Recebe<br><b>{_e(o["para"])}</b><small>{_e(o.get("para_desc") or "")}</small></div>'
                   f'<div class="valor">{_e(brl(o["valor"]))}</div></div>')
    badge = f'<span class="cd-badge">{_e(acao)}</span>' if acao else ""
    return (f'<div class="cd-card" style="--c:{t.ACCENT}"><div class="cd-top"><div><h4>{_e(nota)}{badge}</h4>'
            f'<div class="cd-meta">{len(operacoes)} operação(ões)</div></div>{pill(brl(total), "azul")}</div>{linhas}</div>')


def cartao_dotacao(acao: str, po: str, dotacao, empenhado, disponivel, reforco_mes, reforco_dez, saldo, sobra, empenhos: str) -> str:
    """Ação/PO: o reforço cabe na dotação ainda não empenhada?"""
    if saldo is None or saldo != saldo:
        tom, situacao = "cinza", pill("Sem dotação na base", "cinza")
    elif round(saldo, 2) < 0:
        tom, situacao = "vermelho", pill(f"Falta {brl(-saldo)}", "vermelho")
    else:
        tom, situacao = "verde", pill("Cabe na dotação", "verde")
    barra = ""
    if dotacao and dotacao == dotacao and dotacao > 0:
        usado = max(0.0, min(1.0, (empenhado or 0) / dotacao))
        extra = max(0.0, min(1.0 - usado, (reforco_dez or 0) / dotacao))
        barra = (f'<div class="cd-bar" style="--c:{t.ACCENT};--c2:{t.NEGATIVE if tom == "vermelho" else t.WARNING}"><i style="width:{usado * 100:.1f}%"></i>'
                 f'<i class="seg2" style="left:{usado * 100:.1f}%;width:{extra * 100:.1f}%"></i></div>'
                 f'<div class="cd-barlbl">Azul: já empenhado ({usado:.0%} da dotação). Em cor: reforço necessário até dezembro.</div>')
    figuras = "".join([
        _fig("Dotação atualizada", dotacao), _fig("Já empenhado", empenhado), _fig("Dotação ainda não empenhada", disponivel),
        _fig("Reforço para o mês", reforco_mes), _fig("Reforço até dezembro", reforco_dez, "neg" if (reforco_dez or 0) > 0.004 else ""),
        _fig("Sobra prevista nos empenhos", sobra, "pos" if (sobra or 0) > 0.004 else ""),
    ])
    rodape = f'<div class="cd-meta" style="margin-top:10px">Notas que precisam de reforço: {_e(empenhos)}</div>' if empenhos else ""
    return (f'<div class="cd-card" style="--c:{TONS[tom]}"><div class="cd-top"><div><h4>{_e(acao)}<span class="cd-badge">PO {_e(po or "—")}</span></h4></div>'
            f'{situacao}</div>{barra}<div class="cd-figs">{figuras}</div>{rodape}</div>')


def cartao_conciliacao(acao: str, grupo: str, passos: list[tuple[str, float, str]], diferenca) -> str:
    """Ponte painel → relatório. `passos` = [(rótulo, valor, "normal"|"total")]."""
    zero = diferenca is not None and diferenca == diferenca and abs(diferenca) < 0.005
    linhas = "".join(f'<div class="cd-passo {"total" if tipo == "total" else ""}"><span>{_e(r)}</span><b>{_e(brl(v))}</b></div>' for r, v, tipo in passos)
    selo = pill("Fecha: diferença R$ 0,00", "verde") if zero else (pill("Sem dotação na base", "cinza") if diferenca is None or diferenca != diferenca
                                                                    else pill(f"Diferença {brl(diferenca)}", "vermelho"))
    return (f'<div class="cd-card" style="--c:{t.ACCENT}"><div class="cd-top"><div><h4>{_e(acao)}<span class="cd-badge">{_e(grupo)}</span></h4></div>{selo}</div>'
            f'<div class="cd-passos">{linhas}</div></div>')


def cartao_conferencia(publico: str, competencia: str, bruto, descontos, liquido, credito, situacao: str, problemas: list[str]) -> str:
    """Conferência dos totais de um público (servidor / pensionista)."""
    confere = situacao == "Confere" or situacao.startswith("Confere")
    tom = "verde" if confere and not problemas else ("laranja" if confere else "vermelho")
    equacao = (f'<div class="cd-eq"><div><span>Bruto</span><b>{_e(brl(bruto))}</b></div><div class="op">−</div>'
               f'<div><span>Descontos</span><b>{_e(brl(descontos))}</b></div><div class="op">=</div>'
               f'<div><span>Líquido</span><b>{_e(brl(liquido))}</b></div><div class="op">=</div>'
               f'<div><span>Crédito bancário</span><b>{_e(brl(credito))}</b></div></div>')
    extra = f'<div class="cd-meta" style="margin-top:8px">{_e("; ".join(problemas))}</div>' if problemas else ""
    return (f'<div class="cd-card" style="--c:{TONS[tom]}"><div class="cd-top"><div><h4>{_e(publico)}</h4><div class="cd-meta">{_e(competencia)}</div></div>'
            f'{pill(("✓ " if confere else "✗ ") + situacao, tom)}</div>{equacao}{extra}</div>')


def barras_divergentes(linhas: list[dict], titulo_valor: str = "Variação") -> str:
    """Lista com barras para a esquerda (queda, verde) e direita (alta, vermelha), proporcionais ao maior valor.
    `linhas` = [{"nome", "detalhe", "valor", "tom" (opcional)}]."""
    if not linhas:
        return ""
    maior = max(abs(l["valor"]) for l in linhas) or 1.0
    saida = ""
    for l in linhas:
        v = l["valor"]
        largura = abs(v) / maior * 50
        cor = t.NEGATIVE if v > 0 else t.POSITIVE
        pos = f"left:50%;width:{largura:.1f}%" if v > 0 else f"left:{50 - largura:.1f}%;width:{largura:.1f}%"
        saida += (f'<div class="cd-div"><div class="nome">{_e(l["nome"])}<small>{_e(l.get("detalhe") or "")}</small></div>'
                  f'<div class="trilho"><i style="{pos};background:{cor}"></i></div>'
                  f'<div class="valor" style="color:{cor}">{_e(("+" if v > 0 else "") + brl(v))}</div></div>')
    return saida


def cartao_grupo_execucao(nome: str, dotacao, empenhada, liquidada, paga, cor: str = "azul") -> str:
    """Execução de um exercício por grupo: quanto da dotação foi liquidado."""
    barra = ""
    if dotacao and dotacao == dotacao and dotacao > 0 and liquidada == liquidada:
        proporcao = max(0.0, min(1.0, liquidada / dotacao))
        barra = (f'<div class="cd-bar" style="--c:{TONS[cor]}"><i style="width:{proporcao * 100:.1f}%"></i></div>'
                 f'<div class="cd-barlbl">Liquidada = {proporcao:.1%} da dotação atualizada</div>')
    figuras = "".join([_fig("Dotação atualizada", dotacao), _fig("Empenhada", empenhada), _fig("Liquidada", liquidada), _fig("Paga", paga)])
    return (f'<div class="cd-card" style="--c:{TONS[cor]}"><div class="cd-top"><h4>{_e(nome)}</h4></div>{barra}'
            f'<div class="cd-figs" style="grid-template-columns:repeat(2,minmax(0,1fr))">{figuras}</div></div>')


def cartao_serie_mensal(nome: str, meses: list, total, rotulos: list[str], cor: str = "azul") -> str:
    """Doze colunas (uma por mês) com a Liquidada do grupo; mês sem dado fica vazio (não é zero)."""
    valores = [v if v is not None and v == v else None for v in meses]
    maior = max((abs(v) for v in valores if v is not None), default=0.0) or 1.0
    colunas = "".join(
        (f'<div class="cd-mes" title="{_e(r)}: {_e(brl(v))}"><i style="height:{max(2.0, abs(v) / maior * 70):.0f}px"></i><span>{_e(r[:1])}</span></div>'
         if v is not None else f'<div class="cd-mes vazio" title="{_e(r)}: sem dado"><i style="height:2px"></i><span>{_e(r[:1])}</span></div>')
        for v, r in zip(valores, rotulos))
    return (f'<div class="cd-card" style="--c:{TONS[cor]}"><div class="cd-top"><h4>{_e(nome)}</h4>{pill("Total " + brl(total), cor)}</div>'
            f'<div class="cd-meses">{colunas}</div></div>')


def _pct(valor) -> str:
    if valor is None or valor != valor:
        return "—"
    p = round(float(valor) * 100, 1) + 0.0
    return f"{p:+.1f}%".replace(".", ",").replace("-", "−")


def mapa_calor(linhas: list[str], colunas: list[str], valores: list[list], titulo_linha: str = "") -> str:
    """Mapa de calor de percentuais (fração: 0,05 = 5%): linhas × colunas. Intensidade proporcional ao maior
    módulo da própria coluna; positivo laranja, negativo verde, zero neutro e nulo "—" cinza (nunca zero)."""
    maximos = []
    for j in range(len(colunas)):
        mods = [abs(v[j]) for v in valores if v[j] is not None and v[j] == v[j]]
        maximos.append(max(mods) if mods else 0.0)
    cab = f'<div class="cd-hm-h">{_e(titulo_linha)}</div>' + "".join(f'<div class="cd-hm-h">{_e(c)}</div>' for c in colunas)
    corpo = ""
    for nome, linha in zip(linhas, valores):
        corpo += f'<div class="cd-hm-l">{_e(nome)}</div>'
        for j, v in enumerate(linha):
            if v is None or v != v:
                corpo += '<div class="cd-hm-c vazio">—</div>'
                continue
            forca = abs(v) / maximos[j] * 55 if maximos[j] else 0.0
            cor = t.WARNING if v > 0 else t.POSITIVE
            estilo = f' style="background:color-mix(in srgb,{cor} {forca:.0f}%,transparent)"' if v != 0 else ""
            corpo += f'<div class="cd-hm-c"{estilo}>{_e(_pct(v))}</div>'
    return (f'<div class="cd-hm" style="grid-template-columns:minmax(90px,1fr) repeat({len(colunas)},minmax(0,1fr))">{cab}{corpo}</div>'
            f'<div class="cd-legenda"><span><i style="background:{t.WARNING}"></i>executado acima do projetado</span>'
            f'<span><i style="background:{t.POSITIVE}"></i>executado abaixo do projetado</span>'
            f'<span>cor mais forte = maior desvio da coluna; “—” = sem comparação</span></div>')


def cartao_comparacao(nome: str, meses: int, projetado, executado, diferenca, pct: str, cor: str = "azul", detalhe: str | None = None) -> str:
    """Projeção reconstruída × executado de um grupo (diferença = executado − projetado)."""
    maior = max(abs(projetado or 0), abs(executado or 0)) or 1.0
    linha = lambda rot, v, tom: (f'<div class="cd-vs"><span>{rot}</span><div class="trilho"><i style="width:{max(0.0, abs(v or 0) / maior * 100):.1f}%;'
                                 f'background:{tom}"></i></div><b>{_e(brl(v))}</b></div>')
    if diferenca is None or diferenca != diferenca:
        selo = pill("Sem comparação", "cinza")
    else:
        selo = pill(f"{'+' if diferenca > 0 else ''}{brl(diferenca)} ({pct})", "laranja" if diferenca > 0 else "verde")
    return (f'<div class="cd-card" style="--c:{TONS[cor]}"><div class="cd-top"><div><h4>{_e(nome)}</h4>'
            f'<div class="cd-meta">{meses} mês(es) comparado(s)' + (f' · {_e(detalhe)}' if detalhe else "") + f'</div></div>{selo}</div>'
            f'{linha("Projetado", projetado, t.ACCENT)}{linha("Executado", executado, t.TEXT_FAINT)}</div>')


def cartao_faixa(nome: str, projetado, minimo, maximo, dotacao, saldo_pior, saldo_melhor, posicao: str, fatores: str) -> str:
    """Faixa histórica do total anual: banda mínimo–máximo, com o projetado e a dotação marcados."""
    pontos = [v for v in (projetado, minimo, maximo, dotacao) if v is not None and v == v]
    sem_faixa = minimo is None or minimo != minimo
    marcas = ""
    if pontos:
        baixo, alto = min(pontos), max(pontos)
        folga = (alto - baixo) * 0.08 or 1.0
        baixo, alto = baixo - folga, alto + folga
        pos = lambda v: (v - baixo) / (alto - baixo) * 100
        if not sem_faixa:
            marcas += f'<div class="banda" style="left:{pos(minimo):.1f}%;width:{max(pos(maximo) - pos(minimo), 0.8):.1f}%"></div>'
        if projetado is not None and projetado == projetado:
            marcas += f'<div class="marca" style="left:{pos(projetado):.1f}%;background:{t.ACCENT}"><small>projetado</small></div>'
        if dotacao is not None and dotacao == dotacao:
            marcas += f'<div class="marca" style="left:{pos(dotacao):.1f}%;background:{t.NEGATIVE}"><small>dotação</small></div>'
    tom = "cinza" if sem_faixa else ("verde" if (saldo_pior is not None and saldo_pior == saldo_pior and saldo_pior >= 0) else "vermelho")
    selo = pill(posicao if posicao != "—" else "Sem faixa histórica", {"Dentro da faixa": "verde", "Acima da faixa": "vermelho",
                                                                      "Abaixo da faixa": "laranja"}.get(posicao, "cinza"))
    figuras = "".join([_fig("Projetado no painel", projetado), _fig("Faixa: mínimo", minimo), _fig("Faixa: máximo", maximo),
                       _fig("Dotação atualizada", dotacao), _fig("Saldo no pior caso", saldo_pior, "neg" if (saldo_pior or 0) < 0 else ""),
                       _fig("Saldo no melhor caso", saldo_melhor, "neg" if (saldo_melhor or 0) < 0 else "")])
    return (f'<div class="cd-card" style="--c:{TONS[tom]}"><div class="cd-top"><div><h4>{_e(nome)}</h4>'
            f'<div class="cd-meta">Fator por exercício: {_e(fatores)}</div></div>{selo}</div>'
            f'<div class="cd-faixa"><div class="trilho"></div>{marcas}</div>'
            f'<div class="cd-legenda"><span><i style="background:{t.WARNING_SOFT};border:1px solid {t.WARNING}"></i>faixa histórica</span></div>'
            f'<div class="cd-figs">{figuras}</div></div>')