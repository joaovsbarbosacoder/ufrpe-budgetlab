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
.ro-cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;font-family:{dt.FONT_BODY}}}
.ro-card{{background:{dt.SURFACE};border:1px solid {dt.BORDER};border-radius:{dt.RADIUS};padding:16px 18px}}
.ro-card .lbl{{font-size:13px;color:{dt.TEXT_MUTED}}}
.ro-card .val{{font-size:22px;font-weight:600;color:{dt.TEXT};margin-top:6px;white-space:nowrap;{dt.FONT_MONO_NUM}}}
.ro-card .foot{{font-size:12px;color:{dt.TEXT_FAINT};margin-top:4px}}
.ro-card.res{{border-width:2px}}
.ro-card.res.pos{{border-color:{dt.POSITIVE};background:{dt.POSITIVE_SOFT}}}
.ro-card.res.neg{{border-color:{dt.NEGATIVE};background:{dt.NEGATIVE_SOFT}}}
.ro-card.res.neu{{border-color:{dt.WARNING};background:{dt.WARNING_SOFT}}}
.ro-card.res .val{{font-size:24px}}
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


# ------------------------------------------------------------------------------- células
# Seção "Células" no desenho do protótipo aprovado em 08/10/2026
# (`docs/superpowers/specs/2026-10-08-resultado-orcamentario-celulas-mockup.html`): células agrupadas
# por Ação, códigos em etiquetas, valores em pt-BR e barra do percentual empenhado. As caixas de marcar
# e os botões são widgets do Streamlit; aqui só o texto. `ESTILO_CELULAS` é entregue uma vez por página.
ESTILO_CELULAS = f"""
<style>
.ro-acao-tit{{font-family:{dt.FONT_BODY};font-weight:600;font-size:15px;color:{dt.TEXT}}}
.ro-acao-tit .cod{{color:{dt.ACCENT};margin-right:6px}}
.ro-acao-sub{{font-family:{dt.FONT_BODY};font-size:12px;color:{dt.TEXT_MUTED};margin-top:2px}}
.ro-pill{{display:inline-block;background:{dt.ACCENT_SOFT};color:{dt.ACCENT};border-radius:999px;padding:1px 8px;
  font-weight:600;margin-left:6px}}
.ro-acao-dot{{font-family:{dt.FONT_BODY};text-align:right}}
.ro-l{{font-size:11px;color:{dt.TEXT_FAINT};text-transform:uppercase;letter-spacing:.06em}}
.ro-v{{font-weight:600;color:{dt.TEXT};{dt.FONT_MONO_NUM}white-space:nowrap}}
.ro-v.zero{{color:{dt.TEXT_FAINT};font-weight:500}}
.ro-cel{{font-family:{dt.FONT_BODY}}}
.ro-chips{{display:flex;flex-wrap:wrap;gap:6px;font-size:12px}}
.ro-chip{{background:{dt.SURFACE_ALT};border:1px solid {dt.BORDER};border-radius:6px;padding:1px 7px;color:{dt.TEXT_MUTED}}}
.ro-chip b{{color:{dt.TEXT};font-weight:600}}
.ro-valores{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) 1.3fr;gap:16px;margin-top:8px;align-items:center}}
.ro-barra{{height:8px;background:{dt.SURFACE_ALT};border-radius:4px;overflow:hidden}}
.ro-barra>i{{display:block;height:100%;background:{dt.ACCENT}}}
.ro-barra.alto>i{{background:{dt.WARNING}}}
.ro-barra-l{{font-size:12px;color:{dt.TEXT_MUTED};margin-top:4px}}
.ro-rodape{{display:flex;gap:28px;flex-wrap:wrap;font-family:{dt.FONT_BODY}}}
[class*="st-key-ro_acao_"] [data-testid="stExpander"],
[class*="st-key-ro_acao_"] [data-testid="stExpander"] details{{border:none !important;background:transparent !important;
  box-shadow:none !important}}
[class*="st-key-ro_acao_"] [data-testid="stExpander"] summary{{padding-left:0;color:{dt.ACCENT};font-size:13px}}
@media (max-width:760px){{.ro-valores{{grid-template-columns:1fr 1fr}}}}
</style>
"""

LIMIAR_BARRA_ALTA = 90.0


def html_cabecalho_acao(acao: str, descricao: str, qtd: int, qtd_selecionadas: int) -> str:
    plural = "s" if qtd != 1 else ""
    selo = (
        f'<span class="ro-pill">{qtd_selecionadas} selecionada{"s" if qtd_selecionadas != 1 else ""}</span>'
        if qtd_selecionadas else ""
    )
    return (
        f'<div class="ro-acao-tit"><span class="cod">{_txt(acao)}</span>{_txt(descricao)}</div>'
        f'<div class="ro-acao-sub">{qtd} célula{plural}{selo}</div>'
    )


def html_dotacao_acao(dotacao: float | None) -> str:
    return f'<div class="ro-acao-dot"><div class="ro-l">Dotação da ação</div><div class="ro-v">{brl(dotacao)}</div></div>'


def html_celula(chave: tuple, dotacao: float | None, empenhado: float | None, saldo: float | None) -> str:
    """`chave` na ordem de `CHAVE_CELULA` (iduso, rp, ação, ptres, po, gnd, fonte). Barra = empenhado ÷
    dotação; dotação nula ou zero → "—" e barra vazia (nunca um percentual inventado)."""

    iduso, rp, _acao, ptres, po, gnd, fonte = (("—" if p is None else p) for p in chave)
    chips = "".join(
        f'<span class="ro-chip">{rotulo} <b>{_txt(valor)}</b></span>'
        for rotulo, valor in (("PTRES", ptres), ("PO", po), ("GND", gnd), ("Fonte", fonte), ("IDUSO", iduso), ("RP", rp))
    )
    largura = _largura(empenhado, dotacao)
    pct = percentual(empenhado, dotacao)
    alto = " alto" if largura >= LIMIAR_BARRA_ALTA else ""
    zero = " zero" if empenhado == 0 else ""
    return (
        f'<div class="ro-cel"><div class="ro-chips">{chips}</div><div class="ro-valores">'
        f'<div><div class="ro-l">Dotação</div><div class="ro-v">{brl(dotacao)}</div></div>'
        f'<div><div class="ro-l">Empenhado</div><div class="ro-v{zero}">{brl(empenhado)}</div></div>'
        f'<div><div class="ro-l">Saldo</div><div class="ro-v">{brl(saldo)}</div></div>'
        f'<div><div class="ro-barra{alto}"><i style="width:{largura:.1f}%"></i></div>'
        f'<div class="ro-barra-l">{_txt(pct)} empenhado</div></div>'
        "</div></div>"
    )


def html_rodape_totais(dotacao: float | None, empenhado: float | None, saldo: float | None) -> str:
    return (
        '<div class="ro-rodape">'
        f'<div><div class="ro-l">Dotação selecionada</div><div class="ro-v">{brl(dotacao)}</div></div>'
        f'<div><div class="ro-l">Empenhado</div><div class="ro-v">{brl(empenhado)}</div></div>'
        f'<div><div class="ro-l">Saldo</div><div class="ro-v">{brl(saldo)}</div></div>'
        "</div>"
    )


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
