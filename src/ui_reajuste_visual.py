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

ROTULO_ESTADO = {"formalizado": "Formalizado, a confirmar", "projetado": "Projetado"}
ROTULO_ORIGEM_BASE = {"liquidado": "Liquidado", "contratado": "Contratado (teto)", "sem_liquidado": "Sem liquidado apurado"}
ROTULO_ORIGEM_PERCENTUAL = {
    "manual": "Manual", "oficial": "Oficial (12 meses)", "oficial_ultimo": "Oficial (último disponível)",
    "sem_indice": "Sem índice",
}

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
.rj-heat td.c {{ text-align:left; font-weight:600; font-size:12px; max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.rj-credor {{ font-weight:400; color:{TEXT_MUTED} !important; margin-left:6px; }}
.rj-rolagem {{ overflow-x:auto; }} .rj-rolagem.alta {{ max-height:420px; overflow-y:auto; }}
table.rj-tab {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
.rj-tab th {{ position:sticky; top:0; background:{SURFACE}; z-index:1; text-align:left; font-size:10.5px; text-transform:uppercase;
  letter-spacing:.04em; color:{TEXT_FAINT} !important; padding:6px 8px; border-bottom:2px solid {BORDER}; white-space:nowrap; }}
.rj-tab td {{ padding:7px 8px; border-bottom:1px solid {BORDER}; vertical-align:top; }}
.rj-tab td.n, .rj-tab th.n {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
.rj-tab .peq {{ display:block; color:{TEXT_FAINT} !important; font-size:11px; }}
.rj-zero {{ color:{TEXT_FAINT} !important; }} .rj-nada {{ color:{TEXT_FAINT} !important; }}
.rj-tag {{ display:inline-block; border:1px solid {BORDER}; border-radius:6px; padding:0 6px; font-size:10.5px; color:{TEXT_MUTED} !important; margin-left:4px; }}
.rj-tab tr.rj-total td {{ font-weight:700; border-top:2px solid {BORDER}; border-bottom:0; background:{SURFACE_ALT}; }}
.rj-h0 {{ background:{SURFACE_ALT}; color:{TEXT_FAINT} !important; }} .rj-h1 {{ background:rgba(9,105,218,.12); }}
.rj-h2 {{ background:rgba(9,105,218,.24); }} .rj-h3 {{ background:rgba(9,105,218,.42); color:#fff !important; }}
.rj-heat td.rj-base {{ outline:2px solid {WARNING}; outline-offset:-2px; }}
.rj-tl {{ display:flex; margin:8px 0 14px; }}
.rj-no {{ flex:1; position:relative; text-align:center; padding-top:20px; font-size:12px; }}
.rj-no:before {{ content:""; position:absolute; top:6px; left:0; right:0; height:3px; background:{BORDER}; }}
.rj-no .pt {{ position:absolute; top:0; left:50%; margin-left:-7px; width:14px; height:14px; border-radius:50%; background:#fff; border:3px solid {WARNING}; }}
.rj-no.formalizado .pt {{ background:{ACCENT}; border-color:{ACCENT}; }}
.rj-no.registrado .pt {{ background:{POSITIVE}; border-color:{POSITIVE}; }}
.rj-no b {{ display:block; }} .rj-no span {{ color:{TEXT_MUTED} !important; }}
.rj-grafico {{ display:flex; align-items:flex-end; gap:6px; height:110px; margin:6px 0 4px; border-bottom:1px solid {BORDER}; }}
.rj-col {{ flex:1; display:flex; flex-direction:column; justify-content:flex-end; align-items:center; height:100%; }}
.rj-col .b {{ width:100%; background:#C5D4E6; border:1px solid #9FB4CE; border-bottom:0; border-radius:4px 4px 0 0; }}
.rj-col .b.teto {{ background:repeating-linear-gradient(45deg,#E6EDF6,#E6EDF6 4px,#CBD8E8 4px,#CBD8E8 8px); border-style:dashed; }}
.rj-v {{ font-size:9.5px; color:{TEXT_MUTED} !important; margin-bottom:2px; white-space:nowrap; }}
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


def html_mapa(
    pivot: pd.DataFrame, ano: int, bases_por_contrato: dict[str, set[int]], credores: dict[str, str] | None = None,
) -> str:
    """Mapa de calor contrato × mês do acréscimo estimado no exercício: quanto mais forte a cor, maior o valor; o mês da
    data-base fica contornado; nulo = traço (sem estimativa), zero conhecido = 0. `credores` (número do contrato → nome,
    do cadastro de Contínuos) acompanha o número do contrato em cada linha."""

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
        credor = (credores or {}).get(str(contrato))
        nome = f'<span class="rj-credor">{escape(str(credor))}</span>' if credor and str(credor).strip() else ""
        titulo_linha = escape(f"{contrato} — {credor}" if nome else str(contrato))
        corpo.append(f'<tr><td class="c" title="{titulo_linha}"><b>{escape(str(contrato))}</b>{nome}</td>{"".join(celulas)}</tr>')
    return (
        f'<div class="rj-card"><table class="rj-heat"><thead><tr><th></th>{cabecalho}</tr></thead>'
        f'<tbody>{"".join(corpo)}</tbody></table>'
        + (f'<div class="rj-leg2" style="margin:8px 0 0">{ocultos} contrato{"s" if ocultos != 1 else ""} sem acréscimo '
           "neste exercício não aparece(m) no mapa.</div>" if ocultos else "")
        + "</div>"
    )


def reajustes_registrados(aditivos) -> list:
    """Reajustes JÁ registrados no cadastro: aditivos de tipo REAJUSTE, assinados, com data e com o novo valor mensal
    informado (o assinado sem valor é "a confirmar", não registrado; o previsto ainda não é histórico), em ordem
    cronológica. É o que a linha do tempo mostra como "registrado" ao lado dos ciclos estimados."""

    return sorted(
        (
            a for a in (aditivos or [])
            if a.tipo == "REAJUSTE" and a.situacao == "ASSINADO" and a.data_inicio is not None and a.valor_mensal is not None
        ),
        key=lambda a: a.data_inicio,
    )


def html_ciclos(ciclos: list, registrados: list | None = None) -> str:
    """Linha do tempo do contrato: os reajustes já registrados no cadastro (`registrados`, de `reajustes_registrados`) e os
    ciclos estimados (data-base, percentual e estado), em ordem cronológica. Os ciclos nunca repetem um registrado (o
    cálculo já os exclui)."""

    nos = []
    for aditivo in registrados or []:
        nos.append((
            aditivo.data_inicio,
            f'<div class="rj-no registrado"><span class="pt"></span><b>{aditivo.data_inicio:%d/%m/%Y}</b>'
            f"<span>{formatar_brl(aditivo.valor_mensal)}/mês · registrado</span></div>",
        ))
    for ciclo in ciclos:
        pct = "sem percentual" if _nulo(ciclo.percentual) else f"{ciclo.percentual:.2f} %".replace(".", ",")
        nos.append((
            ciclo.data_base,
            f'<div class="rj-no {escape(ciclo.estado)}"><span class="pt"></span><b>{ciclo.data_base:%d/%m/%Y}</b>'
            f"<span>{pct} · {escape(ciclo.estado)}</span></div>",
        ))
    if not nos:
        return '<div class="rj-leg2">Nenhum ciclo de reajuste na vigência.</div>'
    return f'<div class="rj-tl">{"".join(html for _, html in sorted(nos, key=lambda n: n[0]))}</div>'


def html_grafico_mensal(matriz: pd.DataFrame, ano: int) -> str:
    """Barras do exercício: a base do mês (liquidado = barra cheia; valor contratado, o teto, = barra listrada) e, empilhado
    em cima dela, o acréscimo formalizado e o projetado, com o valor compacto sobre cada coluna. Mês sem base apurada não
    ganha barra nem valor (nulo, não zero). Sem nenhum acréscimo no exercício, avisa que o gráfico mostra só a base."""

    do_ano = matriz[matriz["ano"] == ano] if matriz is not None and not matriz.empty else pd.DataFrame()
    if do_ano.empty:
        return '<div class="rj-leg2">Sem estimativa mensal para mostrar.</div>'
    por_mes = do_ano.set_index("mes")

    def valor(coluna: str, mes: int):
        return por_mes[coluna].get(mes) if coluna in por_mes.columns and mes in por_mes.index else None

    topos = [
        (0.0 if _nulo(valor("base_valor", m)) else valor("base_valor", m)) + (0.0 if _nulo(valor("acrescimo", m)) else valor("acrescimo", m))
        for m in range(1, 13)
    ]
    escala = max(topos, default=0.0) or 1.0
    colunas = []
    tem_acrescimo = False
    for mes in range(1, 13):
        base, f, p = valor("base_valor", mes), valor("acrescimo_formalizado", mes), valor("acrescimo_projetado", mes)
        teto = valor("base_origem", mes) == "contratado"
        # de cima para baixo: valor, formalizado, projetado, base (o acréscimo fica EM CIMA da base)
        partes = []
        tem_base = not _nulo(base) and base > 0
        if tem_base:
            partes.append(f'<div class="rj-v">{_compacto(topos[mes - 1])}</div>')
        if not _nulo(f) and f > 0:
            tem_acrescimo = True
            partes.append(f'<div class="rj-ac-f" style="height:{f / escala * 100:.1f}%"></div>')
        if not _nulo(p) and p > 0:
            tem_acrescimo = True
            partes.append(f'<div class="rj-ac-p" style="height:{p / escala * 100:.1f}%"></div>')
        if tem_base:
            partes.append(f'<div class="b{" teto" if teto else ""}" style="height:{base / escala * 100:.1f}%"></div>')
        titulo = f"{_MESES[mes - 1]}/{ano}: base {formatar_brl(base)} · formalizado {formatar_brl(f)} · projetado {formatar_brl(p)}"
        colunas.append(f'<div class="rj-col" title="{escape(titulo)}">{"".join(partes)}</div>')
    meses = "".join(f"<div>{m}</div>" for m in _MESES)
    legenda = (
        '<div class="rj-leg"><span><i style="background:#C5D4E6;border:1px solid #9FB4CE"></i>base: liquidado</span>'
        '<span><i style="background:repeating-linear-gradient(45deg,#E6EDF6,#E6EDF6 2px,#CBD8E8 2px,#CBD8E8 4px);border:1px dashed #9FB4CE"></i>'
        "base: valor contratado (teto, mês ainda sem liquidado)</span>"
        '<span><i class="rj-f"></i>acréscimo formalizado</span><span><i class="rj-p"></i>acréscimo projetado</span>'
        "<span>mês sem barra = sem liquidado apurado</span></div>"
    )
    aviso = (
        "" if tem_acrescimo
        else '<div class="rj-nota">Sem acréscimo de reajuste neste exercício — o gráfico mostra só a base do mês.</div>'
    )
    return f'<div class="rj-grafico">{"".join(colunas)}</div><div class="rj-meses">{meses}</div>{legenda}{aviso}'


# ---------------------------------------------------------------- tabelas (12/10/2026)
def _valor_html(valor: object) -> str:
    """Moeda pt-BR: nulo = traço; zero conhecido = "R$ 0,00" esmaecido (nunca confundido com nulo)."""

    if _nulo(valor):
        return '<span class="rj-nada">—</span>'
    if valor == 0:
        return '<span class="rj-zero">R$ 0,00</span>'
    return formatar_brl(valor)


def _percentual_html(valor: object) -> str:
    return '<span class="rj-nada">—</span>' if _nulo(valor) else f"{float(valor):.2f} %".replace(".", ",")


def _soma(serie: pd.Series) -> float | None:
    total = serie.sum(skipna=True, min_count=1)
    return None if pd.isna(total) else float(total)


def _estado_pill(estado: object) -> str:
    texto = str(estado or "")
    if not texto:
        return ""
    formalizado = texto.lower().startswith("formalizado")
    return f'<span class="rj-pill {"f" if formalizado else "p"}">{"Formalizado" if formalizado else "Projetado"}</span>'


def _situacao_html(situacao: object) -> str:
    item = {"situacao": situacao}
    if str(situacao or "").startswith("Estimado"):
        return '<span class="rj-pill f">Estimado</span>'
    pills, motivo = _pills_e_motivo(item)
    return f'{pills}<span class="peq">{motivo}</span>' if motivo else pills


def html_tabela_resumo(resumo: pd.DataFrame, ano: int) -> str:
    """Tabela completa por contrato (substitui o `st.dataframe` de 15 colunas): contrato com o nome do credor, situação, próximo
    ciclo (data-base, estado, percentual e origem), os valores do exercício, exercícios anteriores, acréscimo na vigência e as
    observações (ciclos a confirmar, competências sem estimativa, retroativo do gov), mais a linha de totais."""

    col_f, col_p, col_a = f"Formalizado a confirmar {ano}", f"Projetado {ano}", f"Acréscimo {ano}"
    linhas = []
    for _, linha in resumo.iterrows():
        data_base = linha["Data-base"]
        if not _nulo(data_base):
            ciclo = (
                f'<b>{data_base:%d/%m/%Y}</b> {_estado_pill(linha["Estado do ciclo"])}'
                f'<span class="peq">{_percentual_html(linha["Percentual (%)"])} · {escape(str(linha["Origem do %"] or ""))}</span>'
            )
        else:
            ciclo = '<span class="rj-nada">—</span>'
        observacoes = []
        if not _nulo(linha["Ciclos a confirmar"]):
            observacoes.append(f"Ciclos a confirmar: {escape(str(linha['Ciclos a confirmar']))}")
        if not _nulo(linha["Competências sem estimativa"]) and int(linha["Competências sem estimativa"]) > 0:
            observacoes.append(f"{int(linha['Competências sem estimativa'])} competência(s) sem estimativa")
        if not _nulo(linha["Retroativo no gov (contrato inteiro)"]):
            observacoes.append(f"Retroativo no gov: {formatar_brl(linha['Retroativo no gov (contrato inteiro)'])} (contrato inteiro)")
        credor = linha["Fornecedor"]
        credor = escape(str(credor)) if not _nulo(credor) and str(credor).strip() else "sem credor no cadastro"
        linhas.append(
            f'<tr><td><b>{escape(str(linha["Contrato"]))}</b><span class="peq">{credor}</span></td>'
            f'<td>{_situacao_html(linha["Situação"])}</td><td>{ciclo}</td>'
            f'<td class="n">{_valor_html(linha[col_f])}</td><td class="n">{_valor_html(linha[col_p])}</td>'
            f'<td class="n"><b>{_valor_html(linha[col_a])}</b></td><td class="n">{_valor_html(linha["Exercícios anteriores"])}</td>'
            f'<td class="n">{_valor_html(linha["Acréscimo na vigência"])}</td>'
            f'<td>{"".join(f'<span class="peq">{o}</span>' for o in observacoes)}</td></tr>'
        )
    total = (
        '<tr class="rj-total"><td>Total</td><td></td><td></td>'
        + "".join(
            f'<td class="n">{_valor_html(_soma(resumo[c]))}</td>'
            for c in (col_f, col_p, col_a, "Exercícios anteriores", "Acréscimo na vigência")
        )
        + "<td></td></tr>"
    )
    cabecalho = (
        f'<tr><th>Contrato / credor</th><th>Situação</th><th>Próximo ciclo</th><th class="n">Formalizado a confirmar {ano}</th>'
        f'<th class="n">Projetado {ano}</th><th class="n">Acréscimo {ano}</th><th class="n">Exercícios anteriores</th>'
        '<th class="n">Acréscimo na vigência</th><th>Observações</th></tr>'
    )
    return f'<div class="rj-rolagem"><table class="rj-tab rj-resumo"><thead>{cabecalho}</thead><tbody>{"".join(linhas)}{total}</tbody></table></div>'


def html_tabela_competencias(matriz: pd.DataFrame) -> str:
    """Detalhe por competência de um contrato: base (valor e origem), ciclo (data-base e estado), percentual (e origem), os
    acréscimos formalizado/projetado/total e as marcas de exercício anterior e prorrogação prevista."""

    if matriz is None or matriz.empty:
        return '<div class="rj-leg2">Sem estimativa por competência para mostrar.</div>'
    linhas = []
    for _, linha in matriz.iterrows():
        marcas = ""
        if bool(linha.get("exercicio_anterior")):
            marcas += '<span class="rj-tag">exercício anterior</span>'
        if bool(linha.get("prorrogacao_prevista")):
            marcas += '<span class="rj-tag">prorrogação prevista</span>'
        origem_base = ROTULO_ORIGEM_BASE.get(linha.get("base_origem"), "")
        tem_ciclo = not _nulo(linha.get("data_base")) and not _nulo(linha.get("ciclo")) and int(linha["ciclo"]) > 0
        ciclo = (
            f'{linha["data_base"]:%d/%m/%Y} {_estado_pill(linha.get("estado_ciclo"))}' if tem_ciclo
            else '<span class="rj-nada">—</span>'
        )
        origem_pct = ROTULO_ORIGEM_PERCENTUAL.get(linha.get("percentual_origem"), "")
        linhas.append(
            f'<tr><td><b>{escape(str(linha["competencia"]))}</b>{marcas}</td>'
            f'<td class="n">{_valor_html(linha.get("base_valor"))}<span class="peq">{escape(origem_base)}</span></td>'
            f'<td>{ciclo}</td><td class="n">{_percentual_html(linha.get("percentual"))}<span class="peq">{escape(origem_pct)}</span></td>'
            f'<td class="n">{_valor_html(linha.get("acrescimo_formalizado"))}</td>'
            f'<td class="n">{_valor_html(linha.get("acrescimo_projetado"))}</td>'
            f'<td class="n"><b>{_valor_html(linha.get("acrescimo"))}</b></td></tr>'
        )
    cabecalho = (
        '<tr><th>Competência</th><th class="n">Base</th><th>Ciclo</th><th class="n">Percentual</th><th class="n">Formalizado</th>'
        '<th class="n">Projetado</th><th class="n">Acréscimo</th></tr>'
    )
    return f'<div class="rj-rolagem alta"><table class="rj-tab rj-comp"><thead>{cabecalho}</thead><tbody>{"".join(linhas)}</tbody></table></div>'


def _aviso_bloqueados(bloqueados: list[dict]) -> str:
    """Aviso dos reajustes formalizados que o quadro NÃO propõe porque já existe outro aditivo na mesma data."""

    if not bloqueados:
        return ""
    n = len(bloqueados)
    por_contrato = {b["contrato"]: b["acrescimo"] for b in bloqueados if not _nulo(b.get("acrescimo"))}
    soma = f" Formalizado a confirmar neles: {formatar_brl(sum(por_contrato.values()))}." if por_contrato else ""
    itens = "".join(
        f'<div class="rj-base"><b>{escape(str(b["contrato"]))}</b> — {escape(str(b.get("fornecedor") or "sem credor no cadastro"))} · '
        f'ciclo de {b["data"]:%d/%m/%Y} · já há o aditivo {escape(str(b["outro"]))} nesta data</div>'
        for b in sorted(bloqueados, key=lambda b: (str(b["contrato"]), b["data"]))
    )
    plural = "s" if n != 1 else ""
    return (
        f'<div class="rj-nota">{n} reajuste{plural} formalizado{plural} não aparecem acima: já existe outro aditivo na mesma '
        f"data (ex.: prorrogação), e o sistema não cria um segundo aditivo na data.{soma} Se o valor reajustado já consta "
        f"nesse aditivo, o cadastro do contrato é o lugar de ajustá-lo.{itens}</div>"
    )


def html_a_registrar(pendentes: list[dict], ano: int, bloqueados: list[dict] | None = None) -> str:
    """Quadro "A registrar": todos os reajustes FORMALIZADOS (assinados no gov, sem valor no cadastro) de todos os contratos,
    para registrar um a um. Cada item: `contrato`, `fornecedor`, `data` (data-base), `percentual`, `origem`,
    `valor_sugerido` (novo valor mensal sugerido; nulo = informe o do termo) e `acrescimo` (formalizado a confirmar do
    contrato no exercício; nulo não entra no total). Cabeçalho com a contagem e o total a confirmar. `bloqueados`: ciclos
    formalizados que NÃO podem ser registrados aqui porque já há outro aditivo (ex.: prorrogação) na mesma data — listados
    num aviso, com o formalizado a confirmar deles, para o total fechar com o cartão (`outro` = rótulo do aditivo)."""

    aviso = _aviso_bloqueados(bloqueados or [])
    if not pendentes:
        return f'<div class="rj-card"><div class="rj-leg2">Nenhum reajuste formalizado a registrar.</div>{aviso}</div>'
    ordenados = sorted(pendentes, key=lambda p: (str(p["contrato"]), p["data"]))
    n = len(ordenados)
    acrescimos = {p["contrato"]: p["acrescimo"] for p in ordenados if not _nulo(p.get("acrescimo"))}  # por contrato, sem repetir
    total = sum(acrescimos.values()) if acrescimos else None
    cabecalho = f'<div class="rj-titulo">{n} reajuste{"s" if n != 1 else ""} formalizado{"s" if n != 1 else ""} a registrar</div>'
    if total is not None:
        cabecalho += f'<div class="rj-leg2">Formalizado a confirmar em {ano}: {formatar_brl(total)}.</div>'
    linhas = []
    for posicao, p in enumerate(ordenados):
        pct = (
            f'<b>{_percentual_html(p.get("percentual"))}</b> · {escape(str(p.get("origem") or ""))}'
            if not _nulo(p.get("percentual")) else '<span class="rj-nada">sem percentual</span>'
        )
        if _nulo(p.get("valor_sugerido")):
            sugerido = '<span class="rj-nada">—</span><small>informe o valor do termo</small>'
        else:
            sugerido = f'{formatar_brl(p["valor_sugerido"])}<small>novo valor mensal sugerido</small>'
        classe = "rj-linha primeira" if posicao == 0 else "rj-linha"
        credor = escape(str(p.get("fornecedor") or "sem credor no cadastro"))
        linhas.append(
            f'<div class="{classe}"><div class="rj-nome"><b>{escape(str(p["contrato"]))}</b> <span>— {credor}</span></div>'
            f'<div class="rj-base">ciclo de <b>{p["data"]:%d/%m/%Y}</b></div><div class="rj-base">{pct}</div>'
            f'<div class="rj-num">{sugerido}</div></div>'
        )
    return f'<div class="rj-card">{cabecalho}{"".join(linhas)}{aviso}</div>'
