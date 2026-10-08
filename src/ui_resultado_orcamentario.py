"""HTML dos cartões e da Composição da página Resultado Orçamentário.

Pedido do usuário (08/10/2026): a página tinha saído diferente do protótipo aprovado
(`docs/superpowers/specs/2026-10-08-resultado-orcamentario-mockup.html`). Cartão do Resultado com
borda e fundo pela situação (superávit/déficit) e selo; Composição em linhas compactas com valor e %
à direita, barra de proporção e o detalhe por NE ao abrir a linha. `st.metric`/`st.expander` não
permitem esse desenho, por isso o HTML é montado aqui (como em `src/ui_despesas_pessoal.py`) e a
página só o entrega com `st.html`.

Camada: apresentação pura — recebe valores já calculados, não lê arquivo nem importa Streamlit.
Nulo continua "—" (via `formatar_brl`), nunca R$ 0,00. O "$" de "R$" vira `&#36;` para nenhum
renderizador de Markdown/LaTeX engolir o cifrão.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

import pandas as pd

from src import design_tokens as dt
from src.ui_cadastro import formatar_brl

ESTILO = f"""
<style>
.ro-cards{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;font-family:{dt.FONT_BODY}}}
.ro-card{{background:{dt.SURFACE};border:1px solid {dt.BORDER};border-radius:{dt.RADIUS};padding:16px 18px}}
.ro-card .lbl{{font-size:13px;color:{dt.TEXT_MUTED}}}
.ro-card .val{{font-size:24px;font-weight:600;color:{dt.TEXT};margin-top:6px;{dt.FONT_MONO_NUM}}}
.ro-card .foot{{font-size:12px;color:{dt.TEXT_FAINT};margin-top:4px}}
.ro-card.res{{border-width:2px}}
.ro-card.res.pos{{border-color:{dt.POSITIVE};background:{dt.POSITIVE_SOFT}}}
.ro-card.res.neg{{border-color:{dt.NEGATIVE};background:{dt.NEGATIVE_SOFT}}}
.ro-card.res.neu{{border-color:{dt.WARNING};background:{dt.WARNING_SOFT}}}
.ro-card.res .val{{font-size:26px}}
.ro-card.res.pos .val{{color:{dt.POSITIVE}}} .ro-card.res.neg .val{{color:{dt.NEGATIVE}}}
.ro-badge{{display:inline-block;font-size:12px;font-weight:600;border-radius:6px;padding:2px 8px;margin-left:6px;
  color:#fff;vertical-align:middle}}
.ro-badge.pos{{background:{dt.POSITIVE}}} .ro-badge.neg{{background:{dt.NEGATIVE}}} .ro-badge.neu{{background:{dt.WARNING}}}
.ro-box{{background:{dt.SURFACE};border:1px solid {dt.BORDER};border-radius:{dt.RADIUS};padding:6px 0 4px;
  overflow:hidden;font-family:{dt.FONT_BODY};color:{dt.TEXT}}}
.ro-box h3{{font-size:15px;margin:10px 18px 8px;font-weight:600}}
.ro-box details{{border-top:1px solid {dt.BORDER}}}
.ro-box summary{{list-style:none;cursor:pointer;display:grid;grid-template-columns:18px 1fr auto auto;gap:10px;
  align-items:center;padding:10px 18px;font-size:14px}}
.ro-box summary::-webkit-details-marker{{display:none}}
.ro-box summary:hover{{background:{dt.SURFACE_ALT}}}
.ro-box .chev{{color:{dt.TEXT_FAINT};transition:transform .15s}}
.ro-box details[open] .chev{{transform:rotate(90deg)}}
.ro-box .share{{font-size:12px;color:{dt.TEXT_FAINT};width:44px;text-align:right}}
.ro-box .num{{{dt.FONT_MONO_NUM}text-align:right;white-space:nowrap}}
.ro-bar{{height:4px;background:{dt.SURFACE_ALT};margin:0 18px 0 46px;border-radius:2px;overflow:hidden}}
.ro-bar>i{{display:block;height:100%;background:{dt.ACCENT}}}
.ro-inner{{padding:4px 18px 14px 46px;max-height:420px;overflow:auto}}
.ro-inner table{{width:100%;border-collapse:collapse;font-size:13px}}
.ro-inner th{{font-weight:600;color:{dt.TEXT_MUTED};text-align:left;border-bottom:1px solid {dt.BORDER};padding:6px 8px;
  background:{dt.SURFACE_ALT};position:sticky;top:0}}
.ro-inner td{{border-bottom:1px solid #E7EEF6;padding:6px 8px}}
.ro-inner .vazio{{color:{dt.TEXT_FAINT};font-size:13px;margin:6px 0 0}}
.ro-total{{display:flex;justify-content:space-between;padding:10px 18px;border-top:2px solid {dt.BORDER};font-weight:600}}
.ro-check{{display:flex;justify-content:space-between;gap:12px;padding:6px 18px 10px;font-size:12px}}
.ro-check.ok{{color:{dt.POSITIVE}}} .ro-check.erro{{color:{dt.NEGATIVE}}} .ro-check.info{{color:{dt.TEXT_FAINT}}}
@media (max-width: 900px){{.ro-cards{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
</style>
"""


def _txt(valor: object) -> str:
    """Texto seguro para HTML, com o "$" protegido."""

    return escape("" if valor is None else str(valor)).replace("$", "&#36;")


def brl(valor: object) -> str:
    return _txt(formatar_brl(valor))


def percentual(parte: float | None, total: float | None) -> str:
    if parte is None or total is None or pd.isna(parte) or pd.isna(total) or not total:
        return "—"
    return f"{parte / total * 100:.0f}%"


def _largura(parte: float | None, total: float | None) -> float:
    if parte is None or total is None or pd.isna(parte) or pd.isna(total) or not total or parte <= 0:
        return 0.0
    return max(0.0, min(100.0, parte / total * 100))


# ------------------------------------------------------------------------------- cartões
def situacao_resultado(resultado: float | None) -> tuple[str, str]:
    """`(classe, selo)`: pos/Superávit, neg/Déficit, neu/Equilíbrio; nulo → neu/Incompleto."""

    if resultado is None:
        return "neu", "Incompleto"
    if resultado > 0:
        return "pos", "Superávit"
    if resultado < 0:
        return "neg", "Déficit"
    return "neu", "Equilíbrio"


def html_cartoes(
    dotacao: float | None, rodape_dotacao: str,
    empenhado: float | None, necessidade: float | None,
    resultado: float | None, rodape_resultado: str,
) -> str:
    classe, selo = situacao_resultado(resultado)
    cartoes = [
        ("Dotação Atualizada", dotacao, rodape_dotacao, ""),
        ("(−) Empenhado nas células", empenhado, "Execução Mensal, todo empenho das células", ""),
        ("(−) Necessidade até dezembro", necessidade, "Contratos + Bolsas + outras previstas", ""),
    ]
    partes = [
        f'<div class="ro-card"><div class="lbl">{_txt(r)}</div><div class="val">{brl(v)}</div>'
        f'<div class="foot">{_txt(f)}</div></div>'
        for r, v, f, _ in cartoes
    ]
    partes.append(
        f'<div class="ro-card res {classe}"><div class="lbl">Resultado <span class="ro-badge {classe}">{_txt(selo)}'
        f'</span></div><div class="val">{brl(resultado)}</div><div class="foot">{_txt(rodape_resultado)}</div></div>'
    )
    return ESTILO + '<div class="ro-cards">' + "".join(partes) + "</div>"


# ----------------------------------------------------------------------------- composição
@dataclass(frozen=True)
class LinhaComposicao:
    """Uma linha do bloco: rótulo, valor (nulo = "—") e o detalhe que abre ao clicar.

    `detalhe`: tabela (colunas de moeda em `colunas_moeda`) ou `None`; `vazio`: texto quando não há
    tabela ou ela está vazia."""

    rotulo: str
    valor: float | None
    detalhe: pd.DataFrame | None = None
    colunas_moeda: tuple[str, ...] = ()
    vazio: str = "Nada a detalhar."


def _tabela_html(tabela: pd.DataFrame, colunas_moeda: tuple[str, ...]) -> str:
    cab = "".join(
        f'<th{" class=\"num\"" if c in colunas_moeda else ""}>{_txt(c)}</th>' for c in tabela.columns
    )
    linhas = []
    for registro in tabela.itertuples(index=False, name=None):
        celulas = []
        for coluna, valor in zip(tabela.columns, registro):
            if coluna in colunas_moeda:
                celulas.append(f'<td class="num">{brl(valor)}</td>')
            elif isinstance(valor, float) and not pd.isna(valor):
                celulas.append(f'<td class="num">{_txt(f"{valor:.2f}".replace(".", ","))}</td>')
            else:
                celulas.append(f"<td>{_txt('—' if valor is None or (not isinstance(valor, str) and pd.isna(valor)) else valor)}</td>")
        linhas.append("<tr>" + "".join(celulas) + "</tr>")
    return f"<table><thead><tr>{cab}</tr></thead><tbody>{''.join(linhas)}</tbody></table>"


def html_bloco(
    titulo: str, linhas: list[LinhaComposicao], total: float | None, rotulo_total: str,
    rodape: str = "", rodape_classe: str = "info",
) -> str:
    """Bloco da Composição. % e barra só quando o total é conhecido (nulo → "—", sem barra)."""

    partes = [f'<div class="ro-box"><h3>{_txt(titulo)}</h3>']
    for linha in linhas:
        if linha.detalhe is not None and not linha.detalhe.empty:
            interno = _tabela_html(linha.detalhe, linha.colunas_moeda)
        else:
            interno = f'<p class="vazio">{_txt(linha.vazio)}</p>'
        partes.append(
            "<details><summary>"
            f'<span class="chev">▶</span><span>{_txt(linha.rotulo)}</span>'
            f'<span class="share">{_txt(percentual(linha.valor, total))}</span>'
            f'<span class="num">{brl(linha.valor)}</span>'
            f'</summary><div class="ro-inner">{interno}</div></details>'
            f'<div class="ro-bar"><i style="width:{_largura(linha.valor, total):.1f}%"></i></div>'
        )
    partes.append(f'<div class="ro-total"><span>{_txt(rotulo_total)}</span><span class="num">{brl(total)}</span></div>')
    if rodape:
        partes.append(f'<div class="ro-check {rodape_classe}"><span>{_txt(rodape)}</span></div>')
    partes.append("</div>")
    return ESTILO + "".join(partes)
