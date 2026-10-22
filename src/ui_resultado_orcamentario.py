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
    executado: float | None, projetado: float | None,
    resultado: float | None, rodape_resultado: str,
    receitas: float | None = None,
) -> str:
    """Critério de 15/10/2026: `Resultado = Dotação − Executado − Projetado a realizar` (ver `src.resultado_orcamentario`).
    `receitas` (22/10/2026): receitas próprias informadas à mão, somadas à dotação; o cartão só aparece quando há valor."""

    classe, selo = situacao_resultado(resultado)
    cartoes = [
        ("Dotação Atualizada", dotacao, rodape_dotacao, ""),
        *([("(+) Receitas próprias", receitas, "Arrecadação informada à mão, de fonte fora das células", "")] if receitas else []),
        ("(−) Executado nas células", executado, "Contratos e Bolsas: liquidado · demais origens: empenhado", ""),
        ("(−) Projetado a realizar", projetado, "Contratos + Bolsas (o que falta da projeção) + outras previstas", ""),
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


# ------------------------------------------------------------------ detalhamento por GND e Ação
ESTILO_DETALHE = f"""
<style>
.ro-det{{background:{dt.SURFACE};border:1px solid {dt.BORDER};border-radius:{dt.RADIUS};overflow:hidden;
  font-family:{dt.FONT_BODY};color:{dt.TEXT};font-size:14px}}
.ro-det .lin{{display:grid;grid-template-columns:minmax(230px,2.6fr) repeat(4,minmax(110px,1fr)) 120px 92px;gap:10px;
  align-items:center;padding:9px 16px;border-bottom:1px solid #E7EEF6}}
.ro-det .cab{{background:{dt.SURFACE_ALT};color:{dt.TEXT_MUTED};font-weight:600;font-size:13px}}
.ro-det .num{{{dt.FONT_MONO_NUM}text-align:right;white-space:nowrap}}
.ro-det details>summary{{list-style:none;cursor:pointer;font-weight:600}}
.ro-det details>summary::-webkit-details-marker{{display:none}}
.ro-det details>summary:hover{{background:{dt.SURFACE_ALT}}}
.ro-det .chev{{display:inline-block;width:18px;color:{dt.TEXT_FAINT};transition:transform .15s}}
.ro-det details[open]>summary .chev{{transform:rotate(90deg)}}
.ro-det details>summary .lin{{background:#FAFCFE}}
.ro-det .mini{{display:inline-block;width:56px;height:6px;border-radius:3px;background:{dt.SURFACE_ALT};position:relative;
  overflow:hidden;vertical-align:middle;margin-right:8px}}
.ro-det .mini i{{position:absolute;left:0;top:0;bottom:0;background:{dt.ACCENT}}}
.ro-det .mini i.acima{{background:{dt.NEGATIVE}}}
.ro-det .cons{{white-space:nowrap;text-align:left}}
.ro-det .sub{{font-weight:400;font-size:13.5px;padding-left:46px}}
.ro-det .extra{{font-style:italic;color:{dt.TEXT_MUTED}}}
.ro-det .tot{{font-weight:700;border-top:2px solid {dt.BORDER};border-bottom:0}}
.ro-det .cod{{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:{dt.TEXT_MUTED};margin-right:8px}}
.ro-det .pos{{color:{dt.POSITIVE}}} .ro-det .neg{{color:{dt.NEGATIVE}}}
.ro-det .tag{{font-size:11.5px;font-weight:600;border-radius:6px;padding:1px 8px;text-align:center}}
.ro-det .tag.pos{{background:{dt.POSITIVE_SOFT}}} .ro-det .tag.neg{{background:{dt.NEGATIVE_SOFT}}}
.ro-det .tag.neu{{background:{dt.SURFACE_ALT};color:{dt.TEXT_MUTED}}}
.ro-det .vazio{{padding:12px 16px;color:{dt.TEXT_FAINT}}}
@media(max-width:820px){{.ro-det{{overflow-x:auto}}.ro-det .lin{{min-width:780px}}}}
</style>
"""

AGRUPAR_GND = "gnd"
AGRUPAR_ACAO = "acao"


def _soma(serie: pd.Series) -> float | None:
    """Soma que mantém nulo (nulo não vira zero); série vazia = 0."""

    valores = serie.astype("float64")
    return None if valores.isna().any() else float(valores.sum())


def _resultado_do(dotacao: float | None, executado: float | None, projetado: float | None) -> float | None:
    if dotacao is None or executado is None or projetado is None:
        return None
    return dotacao - executado - projetado


def _linha_detalhe(
    rotulo: str, dotacao: float | None, executado: float | None, projetado: float | None, resultado: float | None,
    classe: str = "", prefixo: str = "", cod: str = "",
) -> str:
    dotacao, executado, projetado, resultado = (
        None if v is None or pd.isna(v) else float(v) for v in (dotacao, executado, projetado, resultado)
    )
    sinal = "" if resultado is None or resultado == 0 else (" pos" if resultado > 0 else " neg")
    classe_sit, selo = situacao_resultado(resultado)
    consumo = percentual(
        None if executado is None or projetado is None else executado + projetado, dotacao
    )
    codigo = f'<span class="cod">{_txt(cod)}</span>' if cod else ""
    barra = ""
    if dotacao and executado is not None and projetado is not None and dotacao > 0:
        usado = (executado + projetado) / dotacao * 100
        barra = f'<span class="mini"><i class="{"acima" if usado > 100 else ""}" style="width:{min(usado, 100):.1f}%"></i></span>'
    return (
        f'<div class="lin {classe}"><span>{prefixo}{codigo}{_txt(rotulo)}</span>'
        f'<span class="num">{brl(dotacao)}</span><span class="num">{brl(executado)}</span>'
        f'<span class="num">{brl(projetado)}</span><span class="num{sinal}">{brl(resultado)}</span>'
        f'<span class="cons">{barra}{_txt(consumo)}</span><span class="tag {classe_sit}">{_txt(selo)}</span></div>'
    )


def _rotulos(registro: pd.Series, chave: str) -> tuple[str, str]:
    """`(código, descrição)` do GND ou da Ação do registro; descrição ausente fica em branco."""

    codigo, descricao = (
        (registro["gnd"], registro["gnd_descricao"]) if chave == AGRUPAR_GND else (registro["acao"], registro["acao_descricao"])
    )
    rotulo = "GND " + str(codigo) if chave == AGRUPAR_GND else str(codigo)
    return rotulo, "" if descricao is None or pd.isna(descricao) else f"— {descricao}"


def html_detalhe_gnd_acao(
    linhas: pd.DataFrame, total: tuple[float | None, float | None, float | None, float | None],
    agrupar: str = AGRUPAR_GND, rodape: str = "", rodape_classe: str = "info", abrir: bool | None = None,
) -> str:
    """Tabela do detalhamento (`DetalheGndAcao.linhas`): grupos que abrem para o outro eixo, linhas "Fora das células
    marcadas" e "Sem célula" quando existirem, e o total do bolsão. `total` = dotação, executado, projetado e resultado.
    `abrir`: `True` abre todos os grupos, `False` fecha todos, `None` (padrão) abre só o primeiro."""

    cabecalho = (
        '<div class="lin cab"><span>Grupo</span><span class="num">Dotação atualizada</span>'
        '<span class="num">Executado</span><span class="num">Projetado a realizar</span><span class="num">Resultado</span>'
        '<span class="num">Consumo</span><span>Situação</span></div>'
    )
    celulas = linhas.loc[linhas["tipo"] == "celula"]
    partes = [ESTILO_DETALHE, f'<div class="ro-det">{cabecalho}']
    if celulas.empty and not len(linhas):
        partes.append('<p class="vazio">Marque ao menos uma célula para ver o detalhamento.</p>')
    outro = AGRUPAR_ACAO if agrupar == AGRUPAR_GND else AGRUPAR_GND
    eixo = "gnd" if agrupar == AGRUPAR_GND else "acao"
    for posicao, (_, grupo) in enumerate(celulas.groupby(eixo, sort=True)):
        codigo, descricao = _rotulos(grupo.iloc[0], agrupar)
        dot, exe, prj = _soma(grupo["dotacao"]), _soma(grupo["executado"]), _soma(grupo["projetado"])
        topo = _linha_detalhe(
            descricao.removeprefix("— "), dot, exe, prj, _resultado_do(dot, exe, prj),
            prefixo='<span class="chev">▶</span>', cod=codigo,
        )
        internos = []
        for _, r in grupo.sort_values("acao" if outro == AGRUPAR_ACAO else "gnd").iterrows():
            cod_i, desc_i = _rotulos(r, outro)
            internos.append(_linha_detalhe(
                desc_i.removeprefix("— "), r["dotacao"], r["executado"], r["projetado"], r["resultado"], "sub", cod=cod_i,
            ))
        # <summary> precisa ser o primeiro filho: a linha do grupo vira o resumo
        aberto = " open" if (abrir is True or (abrir is None and posicao == 0)) else ""
        partes.append(f"<details{aberto}><summary>{topo}</summary>{''.join(internos)}</details>")
    for tipo, rotulo in (("fora_marcadas", "Fora das células marcadas (parte de NE em célula não marcada)"),
                         ("sem_celula", "Sem célula (outras despesas previstas, contratos ativos sem NE e receitas próprias sem GND/Ação)")):
        for _, r in linhas.loc[linhas["tipo"] == tipo].iterrows():
            partes.append(_linha_detalhe(rotulo, r["dotacao"], r["executado"], r["projetado"], r["resultado"], "extra"))
    partes.append(_linha_detalhe("Total do bolsão", *total, classe="tot"))
    if rodape:
        partes.append(f'<div class="ro-check {rodape_classe}" style="padding:8px 16px"><span>{_txt(rodape)}</span></div>')
    partes.append("</div>")
    return ESTILO + "".join(partes)
