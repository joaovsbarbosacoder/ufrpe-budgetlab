"""
Linha do tempo das vigências de UM contrato, desenhada dentro do cadastro do contrato (11/10/2026).

Camada de interface (HTML). A regra (segmentos, marcadores, situação) está em `src/linha_tempo_vigencias.py`. Usada
na janela de detalhe da página Contratos (Contratos.gov) e na seção "Contratos.gov" da janela "Editar contrato" de
Contratos Contínuos — pedido do usuário: dentro do cadastro de cada contrato, não numa seção separada. Somente
leitura. `html_*` são funções puras (texto), testáveis sem Streamlit.
"""

from __future__ import annotations

from datetime import date
from html import escape

import streamlit as st

from src.design_tokens import ACCENT, BORDER, NEGATIVE, POSITIVE, SURFACE_ALT, TEXT_FAINT, TEXT_MUTED, WARNING
from src.linha_tempo_vigencias import LinhaDoTempo, janela_do_contrato
from src.ui_cadastro import chip

_COR_TA = "#5B9BF0"
_COR_CADASTRO = "#A9B6CA"
_COR_ACRESCIMO = "#8A5CF6"
_COR_MARCA = {"R": POSITIVE, "A": _COR_ACRESCIMO, "P": TEXT_MUTED, "X": NEGATIVE}

CSS = f"""
<style>
.ltv-bloco {{ margin: 6px 0 12px; }}
.ltv-leg {{ display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:{TEXT_FAINT}; margin:2px 0 8px; }}
.ltv-leg i {{ display:inline-block; width:20px; height:8px; border-radius:3px; margin-right:5px; vertical-align:middle; }}
.ltv-leg b {{ display:inline-block; min-width:16px; text-align:center; color:#fff; border-radius:7px; font-size:10px;
    padding:0 3px; margin-right:4px; }}
.ltv-cab, .ltv-linha {{ display:grid; grid-template-columns:minmax(0,1fr) 190px; gap:14px; align-items:center; }}
.ltv-eixo {{ position:relative; height:16px; border-bottom:1px solid {BORDER}; }}
.ltv-ano {{ position:absolute; border-left:1px solid {BORDER}; padding-left:4px; font-size:11px; color:{TEXT_FAINT};
    height:16px; }}
.ltv-linha {{ padding:8px 0; }}
.ltv-trilho {{ position:relative; height:30px; background:{SURFACE_ALT}; border-radius:6px; }}
.ltv-seg {{ position:absolute; top:8px; height:14px; border-radius:3px; }}
.ltv-seg.contrato {{ background:{ACCENT}; }}
.ltv-seg.ta {{ background:{_COR_TA}; box-shadow:inset -2px 0 0 #fff; }}
.ltv-seg.cadastro {{ background:{_COR_CADASTRO}; }}
.ltv-seg.corte {{ border-top-left-radius:0; border-bottom-left-radius:0; }}
.ltv-hoje {{ position:absolute; top:0; bottom:0; width:2px; background:{NEGATIVE}; }}
.ltv-ev {{ position:absolute; top:0; transform:translateX(-50%); font-size:9px; font-weight:700; line-height:14px;
    min-width:14px; text-align:center; border-radius:7px; padding:0 3px; color:#fff; z-index:2; }}
.ltv-fim small {{ display:block; color:{TEXT_FAINT}; font-size:12px; margin-top:3px; }}
.ltv-div {{ color:{WARNING}; font-weight:600; }}
.ltv-lista {{ font-size:12.5px; color:{TEXT_MUTED}; margin:6px 0 0; padding-left:18px; }}
@media (max-width:700px) {{ .ltv-cab, .ltv-linha {{ grid-template-columns:1fr; }} }}
</style>
"""


def _posicao(dia: date, janela: tuple[date, date]) -> float:
    inicio, fim = janela
    total = max((fim - inicio).days, 1)
    return max(0.0, min(100.0, (dia - inicio).days / total * 100))


def html_eixo(janela: tuple[date, date]) -> str:
    return "".join(
        f'<div class="ltv-ano" style="left:{_posicao(date(ano, 1, 1), janela):.3f}%">{ano}</div>'
        for ano in range(janela[0].year, janela[1].year + 1)
    )


def html_trilho(linha: LinhaDoTempo, janela: tuple[date, date], hoje: date) -> str:
    partes = []
    for seg in linha.segmentos:
        if seg.fim < janela[0]:
            continue
        cortado = seg.inicio is None or seg.inicio < janela[0]
        esquerda = 0.0 if seg.inicio is None else _posicao(seg.inicio, janela)
        largura = max(_posicao(seg.fim, janela) - esquerda, 0.4)
        inicio_txt = "início desconhecido" if seg.inicio is None else f"{seg.inicio:%d/%m/%Y}"
        partes.append(
            f'<div class="ltv-seg {seg.tipo}{" corte" if cortado else ""}" style="left:{esquerda:.3f}%;'
            f'width:{largura:.3f}%" title="{escape(seg.rotulo)}: {inicio_txt} a {seg.fim:%d/%m/%Y}"></div>'
        )
    for ev in linha.eventos:
        if janela[0] <= ev.data <= janela[1]:
            partes.append(
                f'<div class="ltv-ev" style="left:{_posicao(ev.data, janela):.3f}%;background:{_COR_MARCA[ev.marca[0]]}" '
                f'title="{escape(ev.rotulo)} ({ev.data:%d/%m/%Y})">{escape(ev.marca)}</div>'
            )
    if janela[0] <= hoje <= janela[1]:
        partes.append(f'<div class="ltv-hoje" style="left:{_posicao(hoje, janela):.3f}%" title="Hoje"></div>')
    return f'<div class="ltv-trilho">{"".join(partes)}</div>'


def html_legenda() -> str:
    return (
        '<div class="ltv-leg">'
        f'<span><i style="background:{ACCENT}"></i>Contrato original</span>'
        f'<span><i style="background:{_COR_TA}"></i>Termo aditivo de vigência</span>'
        f'<span><i style="background:{_COR_CADASTRO}"></i>Vigência do cadastro</span>'
        f'<span><b style="background:{POSITIVE}">R</b>reajuste</span>'
        f'<span><b style="background:{_COR_ACRESCIMO}">A</b>acréscimo/supressão</span>'
        f'<span><b style="background:{TEXT_MUTED}">P</b>apostilamento</span>'
        f'<span><b style="background:{NEGATIVE}">X</b>rescisão</span>'
        f'<span><i style="background:{NEGATIVE};width:3px"></i>hoje</span>'
        "</div>"
    )


def html_bloco_contrato(linha: LinhaDoTempo, hoje: date) -> str:
    """Bloco completo de um contrato: legenda, eixo de anos, trilho e situação, mais a lista dos períodos de vigência
    (para quem não usa o mouse). Textos escapados."""

    janela = janela_do_contrato(linha, hoje)
    fim = f"fim {linha.fim:%d/%m/%Y}" if linha.fim else "sem data de fim"
    diverge = f' <span class="ltv-div">≠ cadastro {linha.fim_cadastro:%d/%m/%Y}</span>' if linha.diverge else ""
    periodos = "".join(
        f"<li>{escape(s.rotulo)}: {'—' if s.inicio is None else format(s.inicio, '%d/%m/%Y')} a {s.fim:%d/%m/%Y}</li>"
        for s in linha.segmentos
    )
    return (
        f'<div class="ltv-bloco">{html_legenda()}'
        f'<div class="ltv-cab"><div class="ltv-eixo">{html_eixo(janela)}</div><div></div></div>'
        f'<div class="ltv-linha">{html_trilho(linha, janela, hoje)}'
        f'<div class="ltv-fim">{chip(linha.situacao, linha.tom)}<small>{fim}{diverge}</small></div></div>'
        f'{f"<ul class=ltv-lista>{periodos}</ul>" if periodos else ""}</div>'
    )


def render_linha_tempo_do_contrato(linha: LinhaDoTempo, hoje: date) -> None:
    st.markdown(CSS + html_bloco_contrato(linha, hoje), unsafe_allow_html=True)
