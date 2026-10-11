"""
Seção "Linha do tempo das vigências" de Contratos Contínuos (11/10/2026).

Camada de interface (Streamlit + HTML). A regra (segmentos, marcadores, situação) está em
`src/linha_tempo_vigencias.py`; aqui só se desenha: totais, busca, filtro de situação, legenda, eixo de anos com a
marca de hoje e uma linha por contrato — o mesmo modelo do relatório HTML de 11/10/2026, agora nativo. Somente
leitura: nada é gravado. As funções `html_*` são puras (devolvem texto) para serem testáveis sem Streamlit.
"""

from __future__ import annotations

from datetime import date
from html import escape

import pandas as pd
import streamlit as st

from src.design_tokens import ACCENT, BORDER, NEGATIVE, POSITIVE, SURFACE_ALT, TEXT_FAINT, TEXT_MUTED, WARNING
from src.linha_tempo_vigencias import LinhaDoTempo, contagens, janela_padrao, linhas_do_tempo
from src.ui_cadastro import chip, grade_indicadores

#: filtro de situação → predicado sobre a linha
FILTROS = {
    "Todas as situações": lambda l: True,
    "Vigentes": lambda l: l.tom == "ok",
    "Vencem em até 90 dias": lambda l: l.situacao.startswith("Vence"),
    "Encerrados": lambda l: l.situacao == "Encerrado",
    "Sem ligação ao gov ou sem data": lambda l: (not l.ligado) or l.fim is None,
    "Fim do gov ≠ cadastro": lambda l: l.diverge,
}

_COR_MARCA = {"R": POSITIVE, "A": "#8A5CF6", "P": TEXT_MUTED, "X": NEGATIVE}

CSS = f"""
<style>
.ltv-leg {{ display:flex; gap:16px; flex-wrap:wrap; font-size:12.5px; color:{TEXT_FAINT}; margin:4px 0 10px; }}
.ltv-leg i {{ display:inline-block; width:22px; height:9px; border-radius:3px; margin-right:5px; vertical-align:middle; }}
.ltv-leg b {{ display:inline-block; min-width:16px; text-align:center; color:#fff; border-radius:7px; font-size:10px;
    padding:0 3px; margin-right:4px; }}
.ltv-cab, .ltv-linha {{ display:grid; grid-template-columns:240px minmax(0,1fr) 200px; gap:14px; align-items:center; }}
.ltv-cab {{ font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:{TEXT_FAINT};
    border-bottom:1px solid {BORDER}; padding-bottom:6px; }}
.ltv-eixo {{ position:relative; height:16px; }}
.ltv-ano {{ position:absolute; border-left:1px solid {BORDER}; padding-left:4px; font-size:11px; height:16px; }}
.ltv-linha {{ padding:8px 0; border-bottom:1px solid {BORDER}; }}
.ltv-id b {{ display:block; font-size:14px; }} .ltv-id span {{ color:{TEXT_FAINT}; font-size:12px; }}
.ltv-trilho {{ position:relative; height:28px; background:{SURFACE_ALT}; border-radius:6px; }}
.ltv-seg {{ position:absolute; top:7px; height:14px; border-radius:3px; }}
.ltv-seg.contrato {{ background:{ACCENT}; }}
.ltv-seg.ta {{ background:#5B9BF0; box-shadow:inset -2px 0 0 #fff; }}
.ltv-seg.cadastro {{ background:#A9B6CA; }}
.ltv-seg.corte {{ border-top-left-radius:0; border-bottom-left-radius:0; }}
.ltv-hoje {{ position:absolute; top:0; bottom:0; width:2px; background:{NEGATIVE}; }}
.ltv-ev {{ position:absolute; top:0; transform:translateX(-50%); font-size:9px; font-weight:700; line-height:14px;
    min-width:14px; text-align:center; border-radius:7px; padding:0 3px; color:#fff; z-index:2; }}
.ltv-fim small {{ display:block; color:{TEXT_FAINT}; font-size:12px; margin-top:3px; }}
.ltv-div {{ color:{WARNING}; font-weight:600; }}
@media (max-width:900px) {{ .ltv-cab {{ display:none; }} .ltv-linha {{ grid-template-columns:1fr; }} }}
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


def html_linha(linha: LinhaDoTempo, janela: tuple[date, date], hoje: date) -> str:
    """Uma linha: identificação, trilho (segmentos, marcadores, hoje) e situação. Textos escapados."""

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

    fim = f"fim {linha.fim:%d/%m/%Y}" if linha.fim else "sem data de fim"
    diverge = (
        f' <span class="ltv-div">≠ cadastro {linha.fim_cadastro:%d/%m/%Y}</span>' if linha.diverge else ""
    )
    return (
        f'<div class="ltv-linha"><div class="ltv-id"><b>{escape(linha.contrato)}</b>'
        f'<span>{escape(linha.fornecedor[:48])}</span></div>'
        f'<div class="ltv-trilho">{"".join(partes)}</div>'
        f'<div class="ltv-fim">{chip(linha.situacao, linha.tom)}<small>{fim}{diverge}</small></div></div>'
    )


def html_legenda() -> str:
    return (
        '<div class="ltv-leg">'
        f'<span><i style="background:{ACCENT}"></i>Contrato original</span>'
        '<span><i style="background:#5B9BF0"></i>Termo aditivo de vigência</span>'
        '<span><i style="background:#A9B6CA"></i>Vigência do cadastro (sem ligação ao gov)</span>'
        f'<span><b style="background:{POSITIVE}">R</b>reajuste</span>'
        '<span><b style="background:#8A5CF6">A</b>acréscimo/supressão</span>'
        f'<span><b style="background:{TEXT_MUTED}">P</b>apostilamento</span>'
        f'<span><b style="background:{NEGATIVE}">X</b>rescisão</span>'
        f'<span><i style="background:{NEGATIVE};width:3px"></i>hoje</span>'
        "</div>"
    )


def render_linha_tempo_vigencias(
    dataframe: pd.DataFrame, contratos_gov: pd.DataFrame | None, termos_gov: pd.DataFrame | None,
    hoje: date, source_key: str,
) -> None:
    """Seção completa, dentro de um expander fechado. `dataframe` é o cadastro do exercício já com a ligação ao gov
    (`com_contratosgov`); sem fotografia do gov, os contratos aparecem só com a vigência do cadastro."""

    with st.expander("Linha do tempo das vigências (Contratos.gov)", expanded=False):
        st.markdown(CSS, unsafe_allow_html=True)
        if contratos_gov is None:
            st.info("Sem fotografia do Contratos.gov.br: os contratos aparecem só com o fim de vigência do cadastro.")
        linhas = linhas_do_tempo(dataframe, contratos_gov, termos_gov, hoje)
        if not linhas:
            st.info("Nenhum contrato no exercício.")
            return

        total = contagens(linhas, hoje)
        st.markdown(grade_indicadores([
            ("Contratos", str(total["contratos"])),
            ("Vigentes", str(total["vigentes"])),
            ("Vencem em até 90 dias", str(total["vencem_90_dias"])),
            ("Encerrados", str(total["encerrados"])),
            ("Fim do gov ≠ cadastro", str(total["divergentes"])),
            ("Sem ligação ao gov / sem data", str(total["sem_ligacao"] + total["sem_data"])),
        ]), unsafe_allow_html=True)

        coluna_busca, coluna_filtro = st.columns([2, 1])
        busca = coluna_busca.text_input(
            "Buscar contrato ou fornecedor", key=f"ltv_{source_key}_busca", placeholder="Número ou fornecedor…"
        ).strip().lower()
        filtro = coluna_filtro.selectbox("Situação", list(FILTROS), key=f"ltv_{source_key}_situacao")
        visiveis = [
            l for l in linhas
            if FILTROS[filtro](l) and (not busca or busca in f"{l.contrato} {l.fornecedor}".lower())
        ]
        st.caption(
            f"{len(visiveis)} de {len(linhas)} contrato(s). Ordenados pelo fim da vigência (os que vencem primeiro no "
            "topo). Passe o mouse sobre barras e marcadores para ver datas e termos. Barras cortadas à esquerda "
            "começam antes da janela exibida."
        )
        if not visiveis:
            st.info("Nenhum contrato corresponde à busca/filtro.")
            return

        janela = janela_padrao(linhas, hoje)
        corpo = "".join(html_linha(l, janela, hoje) for l in visiveis)
        st.markdown(
            f"{html_legenda()}"
            f'<div class="ltv-cab"><div>Contrato / fornecedor</div><div class="ltv-eixo">{html_eixo(janela)}</div>'
            f"<div>Situação</div></div>{corpo}",
            unsafe_allow_html=True,
        )
