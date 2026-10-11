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

#: Dentro de `st.dialog`, o tema (`src/ui_theme.py`) força `background` e `color` com `!important` em todo `div`/`*`
#: da janela — por isso as cores aqui são por CLASSE (estilo inline não vence `!important`) e cada regra é prefixada
#: por `.ltv-bloco` (especificidade maior) com `!important`.
CSS = f"""
<style>
.ltv-bloco {{ margin: 6px 0 12px; }}
.ltv-bloco .ltv-leg {{ display:flex; gap:14px; flex-wrap:wrap; font-size:12px; margin:2px 0 8px; }}
.ltv-bloco .ltv-leg span {{ color:{TEXT_FAINT} !important; }}
.ltv-bloco .ltv-leg i {{ display:inline-block; width:20px; height:8px; border-radius:3px; margin-right:5px; vertical-align:middle; }}
.ltv-bloco .ltv-leg i.hoje {{ width:3px; }}
.ltv-bloco .ltv-leg b {{ display:inline-block; min-width:16px; text-align:center; border-radius:7px; font-size:10px;
    padding:0 3px; margin-right:4px; color:#fff !important; }}
.ltv-bloco .ltv-cab, .ltv-bloco .ltv-linha {{ display:grid; grid-template-columns:minmax(0,1fr) 190px; gap:14px; align-items:center; }}
.ltv-bloco .ltv-eixo {{ position:relative; height:16px; border-bottom:1px solid {BORDER}; }}
.ltv-bloco .ltv-ano {{ position:absolute; border-left:1px solid {BORDER}; padding-left:4px; font-size:11px;
    color:{TEXT_FAINT} !important; height:16px; background:transparent !important; }}
.ltv-bloco .ltv-linha {{ padding:8px 0; }}
.ltv-bloco .ltv-trilho {{ position:relative; height:30px; background:{SURFACE_ALT} !important; border-radius:6px; }}
.ltv-bloco .ltv-seg {{ position:absolute; top:8px; height:14px; border-radius:3px; }}
.ltv-bloco .c-contrato {{ background:{ACCENT} !important; }}
.ltv-bloco .c-ta {{ background:{_COR_TA} !important; }}
.ltv-bloco .ltv-seg.c-ta {{ box-shadow:inset -2px 0 0 #fff; }}
.ltv-bloco .c-cadastro {{ background:{_COR_CADASTRO} !important; }}
.ltv-bloco .ltv-seg.corte {{ border-top-left-radius:0; border-bottom-left-radius:0; }}
.ltv-bloco .c-hoje {{ background:{NEGATIVE} !important; }}
.ltv-bloco .ltv-hoje {{ position:absolute; top:0; bottom:0; width:2px; }}
.ltv-bloco .ltv-ev {{ position:absolute; top:0; transform:translateX(-50%); font-size:9px; font-weight:700; line-height:14px;
    min-width:14px; text-align:center; border-radius:7px; padding:0 3px; z-index:2; color:#fff !important; }}
.ltv-bloco .m-R {{ background:{POSITIVE} !important; }}
.ltv-bloco .m-A {{ background:{_COR_ACRESCIMO} !important; }}
.ltv-bloco .m-P {{ background:{TEXT_MUTED} !important; }}
.ltv-bloco .m-X {{ background:{NEGATIVE} !important; }}
.ltv-bloco .ltv-fim small {{ display:block; color:{TEXT_FAINT} !important; font-size:12px; margin-top:3px; }}
.ltv-bloco .ltv-div {{ color:{WARNING} !important; font-weight:600; }}
.ltv-bloco .ltv-lista {{ font-size:12.5px; margin:6px 0 0; padding-left:18px; }}
.ltv-bloco .ltv-lista li {{ color:{TEXT_MUTED} !important; }}
@media (max-width:700px) {{ .ltv-bloco .ltv-cab, .ltv-bloco .ltv-linha {{ grid-template-columns:1fr; }} }}
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
            f'<div class="ltv-seg c-{seg.tipo}{" corte" if cortado else ""}" style="left:{esquerda:.3f}%;'
            f'width:{largura:.3f}%" title="{escape(seg.rotulo)}: {inicio_txt} a {seg.fim:%d/%m/%Y}"></div>'
        )
    for ev in linha.eventos:
        if janela[0] <= ev.data <= janela[1]:
            partes.append(
                f'<div class="ltv-ev m-{ev.marca[0]}" style="left:{_posicao(ev.data, janela):.3f}%" '
                f'title="{escape(ev.rotulo)} ({ev.data:%d/%m/%Y})">{escape(ev.marca)}</div>'
            )
    if janela[0] <= hoje <= janela[1]:
        partes.append(f'<div class="ltv-hoje c-hoje" style="left:{_posicao(hoje, janela):.3f}%" title="Hoje"></div>')
    return f'<div class="ltv-trilho">{"".join(partes)}</div>'


def html_legenda() -> str:
    return (
        '<div class="ltv-leg">'
        '<span><i class="c-contrato"></i>Contrato original</span>'
        '<span><i class="c-ta"></i>Termo aditivo de vigência</span>'
        '<span><i class="c-cadastro"></i>Vigência do cadastro</span>'
        '<span><b class="m-R">R</b>reajuste</span>'
        '<span><b class="m-A">A</b>acréscimo/supressão</span>'
        '<span><b class="m-P">P</b>apostilamento</span>'
        '<span><b class="m-X">X</b>rescisão</span>'
        '<span><i class="c-hoje hoje"></i>hoje</span>'
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
    # o <style> vai num markdown só dele: junto do HTML no mesmo bloco, o Streamlit não o aplica
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(html_bloco_contrato(linha, hoje), unsafe_allow_html=True)
