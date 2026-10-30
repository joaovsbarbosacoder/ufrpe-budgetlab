"""HTML dos quadros do discricionário por Plano Orçamentário (pedido do usuário, 29/10/2026).

Protótipo aprovado: `docs/superpowers/specs/2026-10-29-resultado-orcamentario-acoes-discricionarias-mockup.html`. Um quadro por Plano
Orçamentário (PO), agrupados sob a sua Ação, no desenho dos quadros de Despesas de Pessoal: pílula de folga/déficit, executado,
projetado e dotação, barra (executado sólido, projetado hachurado, vermelho acima da dotação, traço da dotação) e, quando o plano tem
mais de uma fonte, o saldo de cada fonte.

Camada: apresentação pura — recebe `PlanosDiscricionarios` já calculado, não lê arquivo nem importa Streamlit. Nulo continua "—" e
sem barra, nunca R$ 0,00. A nota da arrecadação própria só aparece quando o valor informado ultrapassa a dotação da célula (a mesma
regra do detalhamento por GND e Ação).
"""

from __future__ import annotations

from src import design_tokens as dt
from src.resultado_orcamentario_planos import LinhaAvulsa, PlanosDiscricionarios, QuadroPlano, SaldoFonte
from src.ui_resultado_orcamentario import _txt, brl, percentual

_TOLERANCIA_EXCEDENTE = 0.004
#: cores dos quadros por Ação (a mesma cor para todos os planos da Ação)
_CORES = ("#0969DA", "#6F42C1", "#0F8B84", "#C96A00", "#0A8F3D", "#B83280", "#2F6FDE", "#8A5A00", "#1E7F6B", "#7A3FD1", "#C2410C", "#0E7490")

ESTILO = f"""
<style>
.rp{{font-family:{dt.FONT_BODY};color:{dt.TEXT}}}
.rp .kpis{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:6px}}
.rp .kpi{{background:{dt.SURFACE};border:1px solid {dt.BORDER};border-radius:14px;padding:12px 16px;min-width:0}}
.rp .kpi .l{{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:{dt.TEXT_MUTED}}}
.rp .kpi .v{{font-size:19px;font-weight:650;margin-top:3px;font-variant-numeric:tabular-nums;white-space:nowrap}}
.rp .kpi .s{{font-size:12px;color:{dt.TEXT_MUTED};margin-top:2px}}
.rp .acao{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:20px 0 8px;padding-bottom:4px;
  border-bottom:1px solid {dt.BORDER}}}
.rp .acao h3{{margin:0;font-size:14.5px}} .rp .acao .cod{{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:{dt.ACCENT};margin-right:8px}}
.rp .acao .tot{{font-size:12px;color:{dt.TEXT_MUTED};white-space:nowrap}} .rp .acao .tot b{{color:{dt.TEXT}}}
.rp .cards{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
.rp .card{{background:{dt.SURFACE};border:1px solid {dt.BORDER};border-top:4px solid var(--c);border-radius:14px;padding:14px 18px;min-width:0}}
.rp .card header{{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}}
.rp .card h4{{margin:0;font-size:13.5px;line-height:1.35}}
.rp .card h4 .po{{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:var(--c);margin-right:8px;white-space:nowrap}}
.rp .pill{{font-size:12px;font-weight:650;padding:4px 10px;border-radius:999px;white-space:nowrap}}
.rp .pill.neg{{color:{dt.NEGATIVE};background:{dt.NEGATIVE_SOFT}}} .rp .pill.pos{{color:{dt.POSITIVE};background:{dt.POSITIVE_SOFT}}}
.rp .pill.neu{{color:{dt.TEXT_MUTED};background:{dt.SURFACE_ALT}}}
.rp .figs{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0 22px;font-size:11.5px;color:{dt.TEXT_MUTED}}}
.rp .figs b{{display:block;color:{dt.TEXT};font-size:14px;font-variant-numeric:tabular-nums;margin-top:2px;white-space:nowrap}}
.rp .bar{{position:relative;height:16px;border-radius:999px;background:{dt.SURFACE_ALT}}}
.rp .b-exec,.rp .b-proj,.rp .b-over{{position:absolute;top:0;bottom:0}}
.rp .b-exec{{left:0;background:var(--c);border-radius:999px 0 0 999px}}
.rp .b-proj{{background:repeating-linear-gradient(135deg,color-mix(in srgb,var(--c) 55%,white) 0 5px,color-mix(in srgb,var(--c) 28%,white) 5px 10px)}}
.rp .b-over{{min-width:6px;border-radius:0 999px 999px 0;
  background:repeating-linear-gradient(135deg,{dt.NEGATIVE} 0 4px,color-mix(in srgb,{dt.NEGATIVE} 40%,white) 4px 8px)}}
.rp .b-dot{{position:absolute;top:-5px;bottom:-5px;width:2px;background:{dt.TEXT}}}
.rp .b-dot::after{{content:"Dotação";position:absolute;top:-16px;left:50%;transform:translateX(-50%);font-size:10px;color:{dt.TEXT_MUTED};
  white-space:nowrap}}
.rp .foot{{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:11.5px;color:{dt.TEXT_MUTED};margin-top:10px}} .rp .foot b{{color:{dt.TEXT}}}
.rp .fontes{{margin-top:10px;border-top:1px dashed {dt.BORDER};padding-top:8px;display:grid;gap:4px}}
.rp .fontes div{{display:flex;justify-content:space-between;gap:10px;font-size:12.5px}} .rp .fontes span{{color:{dt.TEXT_MUTED}}}
.rp .fontes b{{white-space:nowrap}}
.rp .fontes .f1050{{color:{dt.ACCENT}}}
.rp .fontes small{{display:block;font-size:11px;color:{dt.ACCENT};line-height:1.3}}
.rp .neg{{color:{dt.NEGATIVE}}} .rp .pos{{color:{dt.POSITIVE}}}
.rp .avulsas{{margin-top:18px;display:grid;gap:6px}}
.rp .avulsa{{display:flex;justify-content:space-between;gap:12px;padding:8px 14px;border:1px dashed {dt.BORDER};border-radius:10px;
  font-size:12.5px;color:{dt.TEXT_MUTED};font-style:italic}}
.rp .avulsa b{{color:{dt.TEXT};font-style:normal}}
.rp .ok{{color:{dt.POSITIVE};font-size:12px;margin-top:10px}} .rp .erro{{color:{dt.NEGATIVE};font-size:12px;margin-top:10px}}
.rp .vazio{{color:{dt.TEXT_FAINT};padding:10px 0}}
.rp .filtro{{margin:8px 0 0;font-size:12px;color:{dt.ACCENT};background:{dt.ACCENT_SOFT};border-radius:10px;padding:7px 12px}}
@media(max-width:900px){{.rp .cards{{grid-template-columns:1fr}}.rp .kpis{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
@media(max-width:520px){{.rp .kpis{{grid-template-columns:1fr}}.rp .figs{{grid-template-columns:1fr 1fr}}}}
</style>
"""


def _classe_saldo(saldo: float | None) -> str:
    return "" if saldo is None or saldo == 0 else (" pos" if saldo > 0 else " neg")


def _sinal(v: float | None) -> str:
    if v is None:
        return "—"
    return ("+" if v >= 0 else "−") + brl(abs(v))


def _pilula(dotacao: float | None, saldo: float | None) -> str:
    if saldo is None:
        return '<span class="pill neu">Incompleto</span>' if dotacao is not None else '<span class="pill neu">Sem dotação</span>'
    if saldo < -_TOLERANCIA_EXCEDENTE:
        return f'<span class="pill neg">Déficit {brl(-saldo)}</span>'
    if abs(saldo) <= _TOLERANCIA_EXCEDENTE:
        return '<span class="pill neu">Dotação integral</span>'
    return f'<span class="pill pos">Folga {brl(saldo)}</span>'


def _barra(p: QuadroPlano) -> str:
    dot, exe, prj = p.dotacao, p.executado, p.projetado
    if dot is None or exe is None or prj is None:
        return '<div class="bar" role="img" aria-label="sem barra: valor indisponível"></div>'
    total = exe + prj
    escala = max(dot, total, 1.0) * 1.04
    pct = lambda v: f"{max(0.0, v / escala * 100):.3f}%"  # noqa: E731
    ate = min(total, dot)
    acima = max(0.0, total - dot)
    sobra = f'<div class="b-over" style="left:{pct(dot)};width:{pct(acima)}"></div>' if acima > _TOLERANCIA_EXCEDENTE else ""
    return (
        f'<div class="bar" role="img" aria-label="{_txt(p.po)}: {_txt(brl(total))} de {_txt(brl(dot))} de dotação">'
        f'<div class="b-exec" style="width:{pct(min(exe, ate))}"></div>'
        f'<div class="b-proj" style="left:{pct(min(exe, ate))};width:{pct(max(0.0, ate - exe))}"></div>{sobra}'
        f'<div class="b-dot" style="left:{pct(dot)}"></div></div>'
    )


def _linha_fonte(f: SaldoFonte) -> str:
    e1050 = f.fonte is not None and str(f.fonte).startswith("1050")
    rotulo = f"Fonte {f.fonte}" + (f" · {f.fonte_descricao}" if e1050 and f.fonte_descricao else "")
    nota = ""
    if f.receita_limite is not None and f.receita_excedente > _TOLERANCIA_EXCEDENTE:
        nota = (
            f"<small>limitada pela arrecadação própria: informado {brl(f.receita_limite)} · "
            f"{brl(f.receita_excedente)} acima da dotação ficam fora</small>"
        )
    return (
        f'<div><span class="{"f1050" if e1050 else ""}">{_txt(rotulo)}{nota}</span>'
        f'<b class="{_classe_saldo(f.saldo).strip()}">{_sinal(f.saldo)}</b></div>'
    )


def _cartao(p: QuadroPlano, cor: str) -> str:
    total = None if p.executado is None or p.projetado is None else p.executado + p.projetado
    consumo = percentual(total, p.dotacao) if p.dotacao else "—"
    mostrar_fontes = len(p.fontes) > 1 or any(f.receita_limite is not None for f in p.fontes)
    fontes = f'<div class="fontes">{"".join(_linha_fonte(f) for f in p.fontes)}</div>' if mostrar_fontes else ""
    po_desc = f"{_txt(p.po_descricao)}" if p.po_descricao else "sem descrição"
    return (
        f'<article class="card" style="--c:{cor}"><header><h4><span class="po">PO {_txt(p.po)}</span>{po_desc}</h4>'
        f"{_pilula(p.dotacao, p.saldo)}</header>"
        f'<div class="figs"><div>Executado<b>{brl(p.executado)}</b></div><div>Projetado até dez<b>{brl(p.projetado)}</b></div>'
        f"<div>Dotação<b>{brl(p.dotacao)}</b></div></div>{_barra(p)}"
        f'<div class="foot"><span>Total do ano <b>{brl(total)}</b></span><span>Consumo da dotação <b>{_txt(consumo)}</b></span></div>'
        f"{fontes}</article>"
    )


def _avulsa(rotulo: str, linha: LinhaAvulsa) -> str:
    if linha.vazia:
        return ""
    return (
        f'<div class="avulsa"><span>{_txt(rotulo)}</span>'
        f"<span>Executado <b>{brl(linha.executado)}</b> · Projetado <b>{brl(linha.projetado)}</b></span></div>"
    )


def html_planos_discricionarios(r: PlanosDiscricionarios) -> str:
    """Resumo do discricionário, um quadro por Plano Orçamentário (agrupados por Ação), as linhas avulsas e a conferência com o
    resultado."""

    if not r.planos:
        if r.filtrado:
            return ESTILO + '<div class="rp"><p class="vazio">Nenhum Plano Orçamentário atende aos filtros escolhidos.</p></div>'
        return ESTILO + '<div class="rp"><p class="vazio">Nenhuma célula do discricionário (Resultado Primário 2) neste exercício.</p></div>'

    em_deficit = sum(1 for p in r.planos if p.saldo is not None and p.saldo < -_TOLERANCIA_EXCEDENTE)
    consumo = percentual(
        None if r.executado is None or r.projetado is None else r.executado + r.projetado, r.dotacao
    )
    nota_filtro = (
        f'<p class="filtro">Filtrado: {len(r.planos)} de {r.planos_no_total} Planos. Os totais acima somam só os Planos '
        "exibidos; a conferência com o resultado do discricionário vale para a página sem filtros.</p>"
        if r.filtrado else ""
    )
    kpis = (
        '<div class="kpis">'
        f'<div class="kpi"><div class="l">Dotação discricionária</div><div class="v">{brl(r.dotacao)}</div>'
        f'<div class="s">{len({p.acao for p in r.planos})} Ações · {len(r.planos)} Planos</div></div>'
        f'<div class="kpi"><div class="l">Executado</div><div class="v">{brl(r.executado)}</div>'
        f'<div class="s">{_txt(percentual(r.executado, r.dotacao))} da dotação</div></div>'
        f'<div class="kpi"><div class="l">Projetado até dez</div><div class="v">{brl(r.projetado)}</div>'
        f'<div class="s">{_txt(percentual(r.projetado, r.dotacao))} da dotação</div></div>'
        f'<div class="kpi"><div class="l">Saldo</div><div class="v{_classe_saldo(r.saldo)}">{_sinal(r.saldo)}</div>'
        f'<div class="s">{em_deficit} Plano(s) em déficit · consumo {_txt(consumo)}</div></div></div>'
    )

    blocos: list[str] = []
    acoes: dict[str, list[QuadroPlano]] = {}
    for p in r.planos:
        acoes.setdefault(p.acao, []).append(p)
    for indice, (acao, planos) in enumerate(acoes.items()):
        cor = _CORES[indice % len(_CORES)]
        dot = None if any(p.dotacao is None for p in planos) else sum(p.dotacao for p in planos)
        saldo = None if any(p.saldo is None for p in planos) else sum(p.saldo for p in planos)
        descricao = next((p.acao_descricao for p in planos if p.acao_descricao), None)
        blocos.append(
            f'<div class="acao"><h3><span class="cod">{_txt(acao)}</span>{_txt(descricao or "sem descrição")}</h3>'
            f'<span class="tot">Dotação <b>{brl(dot)}</b> · Saldo <b class="{_classe_saldo(saldo).strip()}">{_sinal(saldo)}</b></span></div>'
            f'<div class="cards">{"".join(_cartao(p, cor) for p in planos)}</div>'
        )

    if r.filtrado:  # recorte: linhas avulsas e conferência só valem para o total
        return ESTILO + '<div class="rp">' + kpis + nota_filtro + "".join(blocos) + "</div>"
    avulsas = _avulsa("Fora do discricionário (parte de NE com empenho em célula que não é RP2)", r.fora) + _avulsa(
        "Sem célula (outras despesas previstas e contratos ativos sem NE)", r.sem_celula
    )
    conferencia = (
        f'<div class="ok">✓ A soma dos quadros confere com o resultado do discricionário · diferença '
        f"{brl(round(r.diferenca_conferencia, 2) + 0.0)}</div>"
        if r.fecha else
        f'<div class="erro">✗ A soma dos quadros não fecha com o resultado do discricionário · diferença '
        f"{brl(round(r.diferenca_conferencia, 2) + 0.0)}</div>"
    )
    return (
        ESTILO + '<div class="rp">' + kpis + "".join(blocos)
        + (f'<div class="avulsas">{avulsas}</div>' if avulsas else "") + conferencia + "</div>"
    )
