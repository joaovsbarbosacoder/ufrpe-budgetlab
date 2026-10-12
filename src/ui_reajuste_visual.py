"""
Componentes visuais da página "Reajuste estimado" (12/10/2026) — HTML puro, sem Streamlit.

Camada de apresentação: recebe valores JÁ estimados por `src/estimativa_reajuste.py` (via `src/ui_reajuste.py`) e só os
desenha — cartão de destaque, lista dos contratos que mais pesam, mapa de calor do ano, linha do tempo dos ciclos e
gráfico mensal de um contrato. Regras: nulo ≠ zero (traço, nunca R$ 0,00); o número do contrato vem acompanhado do nome do
credor; textos escapados; contrato sem estimativa continua visível, com o motivo. Maquete:
`docs/superpowers/specs/2026-10-12-estimativa-reajuste-repaginada-mockup.html`.

Contrato público:
    CSS
    html_destaque(ano, formalizado, projetado, anteriores, sem_estimativa) -> str
    html_ranking(itens, limite=None) -> str
    html_mapa(pivot, ano, bases_por_contrato) -> str
    html_ciclos(ciclos) -> str
    html_grafico_mensal(matriz, ano) -> str
"""

from __future__ import annotations

from xml.sax.saxutils import escape

import pandas as pd

from src.design_tokens import (
    ACCENT,
    ACCENT_SOFT,
    BORDER,
    NEGATIVE,
    NEGATIVE_SOFT,
    POSITIVE,
    POSITIVE_SOFT,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    TEXT_FAINT,
    TEXT_MUTED,
    WARNING,
    WARNING_SOFT,
)
from src.ui_cadastro import formatar_brl

_MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

CSS = f"""<style>
.rj-card {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:14px; padding:16px 20px; margin:0 0 14px; }}
.rj-hero {{ display:grid; grid-template-columns:1.2fr 2fr; gap:20px; align-items:center; }}
.rj-rot {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:{TEXT_MUTED} !important; }}
.rj-valor {{ font-size:32px; font-weight:700; color:{WARNING} !important; font-variant-numeric:tabular-nums; }}
.rj-sub {{ font-size:12px; color:{TEXT_FAINT} !important; }}
.rj-tiles {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }}
.rj-tile {{ background:{SURFACE_ALT}; border-radius:10px; padding:10px 12px; }}
.rj-tile .t {{ font-size:11px; color:{TEXT_MUTED} !important; text-transform:uppercase; letter-spacing:.04em; }}
.rj-tile .v {{ font-size:17px; font-weight:700; font-variant-numeric:tabular-nums; }}
.rj-tile .d {{ font-size:11px; color:{TEXT_FAINT} !important; }}
.rj-tile.alerta {{ background:{NEGATIVE_SOFT}; }} .rj-tile.alerta .v {{ color:{NEGATIVE} !important; }}
.rj-barra-total {{ display:flex; height:10px; border-radius:6px; overflow:hidden; margin-top:12px; background:{SURFACE_ALT}; }}
.rj-f {{ background:{ACCENT}; }} .rj-p {{ background:#8CC7FF; }}
.rj-leg {{ display:flex; gap:14px; flex-wrap:wrap; font-size:11px; color:{TEXT_MUTED} !important; margin-top:6px; }}
.rj-leg i {{ display:inline-block; width:9px; height:9px; border-radius:3px; margin-right:5px; }}
.rj-titulo {{ font-size:15px; font-weight:700; margin:0 0 2px; }} .rj-leg2 {{ font-size:12px; color:{TEXT_FAINT} !important; margin-bottom:10px; }}
.rj-linha {{ display:grid; grid-template-columns:2.2fr 1.1fr 1.6fr 1fr; gap:14px; align-items:center; padding:10px 0; border-top:1px solid {BORDER}; }}
.rj-linha.primeira {{ border-top:0; }}
.rj-nome span {{ color:{TEXT_MUTED} !important; font-size:12.5px; }}
.rj-pill {{ display:inline-block; border-radius:999px; padding:1px 9px; font-size:11px; font-weight:600; margin-right:4px; }}
.rj-pill.f {{ background:{ACCENT_SOFT}; color:{ACCENT} !important; }} .rj-pill.p {{ background:{WARNING_SOFT}; color:{WARNING} !important; }}
.rj-pill.r {{ background:{POSITIVE_SOFT}; color:{POSITIVE} !important; }} .rj-pill.n {{ background:{NEGATIVE_SOFT}; color:{NEGATIVE} !important; }}
.rj-base {{ font-size:12px; color:{TEXT_MUTED} !important; }} .rj-base b {{ color:{TEXT} !important; font-size:13px; }}
.rj-mini {{ display:flex; height:8px; border-radius:5px; overflow:hidden; background:{SURFACE_ALT}; margin-top:4px; }}
.rj-num {{ text-align:right; font-weight:700; font-variant-numeric:tabular-nums; }}
.rj-num small {{ display:block; font-weight:400; color:{TEXT_FAINT} !important; font-size:11px; }}
table.rj-heat {{ border-collapse:separate; border-spacing:3px; width:100%; font-size:11.5px; }}
.rj-heat th {{ color:{TEXT_FAINT} !important; font-weight:600; text-transform:uppercase; font-size:10.5px; text-align:center; }}
.rj-heat td {{ text-align:center; border-radius:5px; padding:5px 2px; font-variant-numeric:tabular-nums; }}
.rj-heat td.c {{ text-align:left; font-weight:600; font-size:12px; white-space:nowrap; }}
.rj-h0 {{ background:{SURFACE_ALT}; color:{TEXT_FAINT} !important; }} .rj-h1 {{ background:rgba(9,105,218,.12); }}
.rj-h2 {{ background:rgba(9,105,218,.24); }} .rj-h3 {{ background:rgba(9,105,218,.42); color:#fff !important; }}
.rj-heat td.rj-base {{ outline:2px solid {WARNING}; outline-offset:-2px; }}
.rj-tl {{ display:flex; margin:8px 0 14px; }}
.rj-no {{ flex:1; position:relative; text-align:center; padding-top:20px; font-size:12px; }}
.rj-no:before {{ content:""; position:absolute; top:6px; left:0; right:0; height:3px; background:{BORDER}; }}
.rj-no .pt {{ position:absolute; top:0; left:50%; margin-left:-7px; width:14px; height:14px; border-radius:50%; background:#fff; border:3px solid {WARNING}; }}
.rj-no.formalizado .pt {{ background:{ACCENT}; border-color:{ACCENT}; }}
.rj-no b {{ display:block; }} .rj-no span {{ color:{TEXT_MUTED} !important; }}
.rj-grafico {{ display:flex; align-items:flex-end; gap:6px; height:110px; margin:6px 0 4px; border-bottom:1px solid {BORDER}; }}
.rj-col {{ flex:1; display:flex; flex-direction:column; justify-content:flex-end; align-items:center; height:100%; }}
.rj-col .b {{ width:100%; background:{SURFACE_ALT}; border:1px solid {BORDER}; border-bottom:0; border-radius:4px 4px 0 0; }}
.rj-ac-f {{ width:100%; background:{ACCENT}; }} .rj-ac-p {{ width:100%; background:#8CC7FF; }}
.rj-meses {{ display:flex; gap:6px; font-size:10.5px; color:{TEXT_FAINT} !important; text-align:center; }} .rj-meses div {{ flex:1; }}
.rj-nota {{ font-size:12px; color:{TEXT_MUTED} !important; background:{SURFACE_ALT}; border-radius:8px; padding:8px 12px; margin-top:10px; }}
@media (max-width:820px) {{ .rj-hero {{ grid-template-columns:1fr; }} .rj-tiles {{ grid-template-columns:1fr 1fr; }}
  .rj-linha {{ grid-template-columns:1fr 1fr; }} }}
</style>"""


def _reais(valor: float | None) -> str:
    """"R$ 1.386.420" (sem centavos) para o destaque; nulo vira traço (nunca R$ 0)."""
    if valor is None or pd.isna(valor):
        return "—"
    return "R$ " + f"{valor:,.0f}".replace(",", ".")


def _compacto(valor: float | None) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    absoluto = abs(valor)
    if absoluto >= 1_000_000:
        texto = f"{valor / 1_000_000:.1f} mi"
    elif absoluto >= 10_000:
        texto = f"{valor / 1_000:.0f} mil"
    elif absoluto >= 1_000:
        texto = f"{valor / 1_000:.1f} mil"
    else:
        texto = f"{valor:.0f}"
    return texto.replace(".", ",")


def _nulo(valor: object) -> bool:
    return valor is None or bool(pd.isna(valor))


def html_destaque(
    ano: int, formalizado: float | None, projetado: float | None, anteriores: float | None, sem_estimativa: int,
) -> str:
    """Cartão do topo: o total estimado do exercício (formalizado + projetado), os quatro indicadores e a barra da divisão
    formalizado × projetado. Sem nenhum valor, o total é traço (nunca R$ 0)."""

    total = None if _nulo(formalizado) and _nulo(projetado) else (0.0 if _nulo(formalizado) else formalizado) + (0.0 if _nulo(projetado) else projetado)
    barra = ""
    if total:
        f = 0.0 if _nulo(formalizado) else formalizado
        pct_f = round(f / total * 100)
        barra = (
            f'<div class="rj-barra-total"><div class="rj-f" style="width:{pct_f}%"></div><div class="rj-p" style="width:{100 - pct_f}%"></div></div>'
            f'<div class="rj-leg"><span><i class="rj-f"></i>Formalizado {pct_f}%</span><span><i class="rj-p"></i>Projetado {100 - pct_f}%</span></div>'
        )
    contratos = f"{sem_estimativa} contrato" + ("" if sem_estimativa == 1 else "s")
    return (
        '<div class="rj-card rj-hero"><div>'
        f'<div class="rj-rot">Reajuste estimado em {ano}</div><div class="rj-valor">{_reais(total)}</div>'
        f'<div class="rj-sub">se confirmados todos os ciclos previstos na vigência dos contratos de {ano}</div></div><div>'
        '<div class="rj-tiles">'
        f'<div class="rj-tile"><div class="t">Formalizado a confirmar</div><div class="v">{_reais(formalizado)}</div>'
        '<div class="d">assinado no gov, ainda sem valor no cadastro</div></div>'
        f'<div class="rj-tile"><div class="t">Projetado</div><div class="v">{_reais(projetado)}</div><div class="d">próximos aniversários</div></div>'
        f'<div class="rj-tile"><div class="t">Exercícios anteriores</div><div class="v">{_reais(anteriores)}</div>'
        '<div class="d">retroativo, fora do total</div></div>'
        f'<div class="rj-tile alerta"><div class="t">Sem estimativa</div><div class="v">{contratos}</div>'
        '<div class="d">falta índice, data-base ou fim de vigência</div></div>'
        f'</div>{barra}</div></div>'
    )


def _pills_e_motivo(item: dict) -> tuple[str, str]:
    situacao = str(item.get("situacao") or "")
    if situacao.startswith("Estimado"):
        estado = str(item.get("estado") or "")
        positivo = lambda chave: not _nulo(item.get(chave)) and item[chave] > 0  # noqa: E731
        pills = ""
        if positivo("formalizado"):
            pills += '<span class="rj-pill f">Formalizado</span>'
        if positivo("projetado"):
            pills += '<span class="rj-pill p">Projetado</span>'
        if not pills:  # sem valor positivo: o estado do próximo ciclo
            formalizado = estado.startswith("Formalizado")
            pills = f'<span class="rj-pill {"f" if formalizado else "p"}">{"Formalizado" if formalizado else "Projetado"}</span>'
        return pills, ""
    if situacao.startswith("Sem reajuste previsto"):
        return '<span class="rj-pill r">Sem reajuste previsto</span>', "nenhum aniversário dentro da vigência"
    motivo = (
        "falta a data-base do contrato" if situacao.startswith("Sem data-base")
        else "falta o percentual (índice indisponível)" if situacao.startswith("Sem percentual")
        else "falta o fim da vigência" if situacao.startswith("Sem fim")
        else escape(situacao)
    )
    return '<span class="rj-pill n">Sem estimativa</span>', motivo


def html_ranking(itens: list[dict], limite: int | None = None) -> str:
    """Contratos ordenados pelo acréscimo estimado no exercício (nulos por último). Cada item: `contrato`, `fornecedor`,
    `situacao`, `estado`, `data_base`, `percentual`, `origem`, `formalizado`, `projetado`, `acrescimo`."""

    ordenados = sorted(itens, key=lambda i: (_nulo(i.get("acrescimo")), -(0.0 if _nulo(i.get("acrescimo")) else i["acrescimo"])))
    if limite is not None:
        ordenados = ordenados[:limite]
    maximo = max((i["acrescimo"] for i in ordenados if not _nulo(i.get("acrescimo")) and i["acrescimo"] > 0), default=0.0)
    linhas = []
    for posicao, item in enumerate(ordenados):
        pills, motivo = _pills_e_motivo(item)
        data_base = item.get("data_base")
        base = f'data-base <b>{data_base:%d/%m/%Y}</b>' if not _nulo(data_base) else (motivo or "sem data-base")
        if not _nulo(item.get("percentual")):
            pct = f'<b>{item["percentual"]:.2f} %</b>'.replace(".", ",") + f' · {escape(str(item.get("origem") or ""))}'
        else:
            pct = motivo or "sem percentual"
        barra = ""
        if maximo:
            f = 0.0 if _nulo(item.get("formalizado")) else max(item["formalizado"], 0.0)
            p = 0.0 if _nulo(item.get("projetado")) else max(item["projetado"], 0.0)
            barra = (
                f'<div class="rj-mini"><div class="rj-f" style="width:{f / maximo * 100:.1f}%"></div>'
                f'<div class="rj-p" style="width:{p / maximo * 100:.1f}%"></div></div>'
            )
        rotulo_valor = "acréscimo no exercício" if not _nulo(item.get("acrescimo")) else "sem estimativa"
        classe = "rj-linha primeira" if posicao == 0 else "rj-linha"
        linhas.append(
            f'<div class="{classe}"><div class="rj-nome"><b>{escape(str(item["contrato"]))}</b> '
            f'<span>— {escape(str(item.get("fornecedor") or "sem credor no cadastro"))}</span></div>'
            f'<div>{pills}<div class="rj-base">{base}</div></div>'
            f'<div class="rj-base">{pct}{barra}</div>'
            f'<div class="rj-num">{formatar_brl(item.get("acrescimo"))}<small>{rotulo_valor}</small></div></div>'
        )
    return f'<div class="rj-card">{"".join(linhas) or "<div class=rj-leg2>Nenhum contrato.</div>"}</div>'


def html_mapa(pivot: pd.DataFrame, ano: int, bases_por_contrato: dict[str, set[int]]) -> str:
    """Mapa de calor contrato × mês do acréscimo estimado no exercício: quanto mais forte a cor, maior o valor; o mês da
    data-base fica contornado; nulo = traço (sem estimativa), zero conhecido = 0."""

    if pivot is None or pivot.empty:
        return '<div class="rj-card"><div class="rj-leg2">Sem estimativa mensal para mostrar.</div></div>'
    totais = pivot.sum(axis=1, skipna=True, min_count=1)
    com_acrescimo = [c for c in totais.sort_values(ascending=False).index if not _nulo(totais[c]) and totais[c] > 0]
    ocultos = len(pivot) - len(com_acrescimo)
    if not com_acrescimo:
        return '<div class="rj-card"><div class="rj-leg2">Nenhum acréscimo estimado neste exercício.</div></div>'
    pivot = pivot.loc[com_acrescimo]
    positivos = [v for v in pivot.to_numpy().ravel() if not _nulo(v) and v > 0]
    maximo = max(positivos, default=0.0)
    cabecalho = "".join(f"<th>{m.capitalize()}</th>" for m in _MESES)
    corpo = []
    for contrato, linha in pivot.iterrows():
        celulas = []
        for mes in range(1, 13):
            valor = linha.get(mes)
            if _nulo(valor):
                nivel, texto = "rj-h0", "—"
            elif valor <= 0 or not maximo:
                nivel, texto = "rj-h0", _compacto(valor)
            else:
                razao = valor / maximo
                nivel, texto = ("rj-h1" if razao <= 0.25 else "rj-h2" if razao <= 0.6 else "rj-h3"), _compacto(valor)
            if mes in bases_por_contrato.get(str(contrato), set()):
                nivel += " rj-base"
            titulo = f"{_MESES[mes - 1]}/{ano}: {formatar_brl(valor)}"
            celulas.append(f'<td class="{nivel}" title="{escape(titulo)}">{texto}</td>')
        corpo.append(f'<tr><td class="c">{escape(str(contrato))}</td>{"".join(celulas)}</tr>')
    return (
        f'<div class="rj-card"><table class="rj-heat"><thead><tr><th></th>{cabecalho}</tr></thead>'
        f'<tbody>{"".join(corpo)}</tbody></table>'
        + (f'<div class="rj-leg2" style="margin:8px 0 0">{ocultos} contrato{"s" if ocultos != 1 else ""} sem acréscimo '
           "neste exercício não aparece(m) no mapa.</div>" if ocultos else "")
        + "</div>"
    )


def html_ciclos(ciclos: list) -> str:
    """Linha do tempo dos ciclos de reajuste do contrato (data-base, percentual e estado)."""

    if not ciclos:
        return '<div class="rj-leg2">Nenhum ciclo de reajuste na vigência.</div>'
    nos = []
    for ciclo in ciclos:
        pct = "sem percentual" if _nulo(ciclo.percentual) else f"{ciclo.percentual:.2f} %".replace(".", ",")
        nos.append(
            f'<div class="rj-no {escape(ciclo.estado)}"><span class="pt"></span><b>{ciclo.data_base:%d/%m/%Y}</b>'
            f'<span>{pct} · {escape(ciclo.estado)}</span></div>'
        )
    return f'<div class="rj-tl">{"".join(nos)}</div>'


def html_grafico_mensal(matriz: pd.DataFrame, ano: int) -> str:
    """Barras do exercício: base do mês (liquidado, ou contratado como teto) e, empilhado, o acréscimo formalizado e o
    projetado. Mês sem base e sem acréscimo fica vazio (nulo, não zero)."""

    do_ano = matriz[matriz["ano"] == ano] if matriz is not None and not matriz.empty else pd.DataFrame()
    if do_ano.empty:
        return '<div class="rj-leg2">Sem estimativa mensal para mostrar.</div>'
    por_mes = do_ano.set_index("mes")
    topos = [
        (0.0 if _nulo(por_mes["base_valor"].get(m)) else por_mes["base_valor"].get(m))
        + (0.0 if _nulo(por_mes["acrescimo"].get(m)) else por_mes["acrescimo"].get(m))
        for m in range(1, 13)
    ]
    escala = max(topos, default=0.0) or 1.0
    colunas = []
    for mes in range(1, 13):
        base = por_mes["base_valor"].get(mes) if mes in por_mes.index else None
        f = por_mes["acrescimo_formalizado"].get(mes) if mes in por_mes.index else None
        p = por_mes["acrescimo_projetado"].get(mes) if mes in por_mes.index else None
        partes = []
        if not _nulo(base) and base > 0:
            partes.append(f'<div class="b" style="height:{base / escala * 100:.1f}%"></div>')
        if not _nulo(p) and p > 0:
            partes.append(f'<div class="rj-ac-p" style="height:{p / escala * 100:.1f}%"></div>')
        if not _nulo(f) and f > 0:
            partes.append(f'<div class="rj-ac-f" style="height:{f / escala * 100:.1f}%"></div>')
        titulo = f"{_MESES[mes - 1]}/{ano}: base {formatar_brl(base)} · formalizado {formatar_brl(f)} · projetado {formatar_brl(p)}"
        colunas.append(f'<div class="rj-col" title="{escape(titulo)}">{"".join(partes)}</div>')
    meses = "".join(f"<div>{m}</div>" for m in _MESES)
    legenda = (
        '<div class="rj-leg"><span><i style="background:%s;border:1px solid %s"></i>base do mês (liquidado; futuro = teto contratado)</span>'
        '<span><i class="rj-f"></i>acréscimo formalizado</span><span><i class="rj-p"></i>acréscimo projetado</span></div>'
    ) % (SURFACE_ALT, BORDER)
    return f'<div class="rj-grafico">{"".join(colunas)}</div><div class="rj-meses">{meses}</div>{legenda}'
