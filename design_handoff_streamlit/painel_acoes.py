"""Painel Orçamentário — um card por Ação de Governo, subdivisões dentro do card.

Sem percentuais e sem gráficos: apenas valores tabulares.
Os cards são HTML injetado (st.markdown) porque nenhum componente nativo do
Streamlit entrega a grade de 10 colunas com hierarquia código/nome por célula.
Os controles (filtros e o botão de expandir) são nativos.
"""
from __future__ import annotations

import streamlit as st

from src.data_loader import YEARS, carregar_base
from src.design_tokens import (
    ACCENT, ACCENT_LINE, ACCENT_SOFT, ACCENT_STRONG, BORDER, BORDER_SOFT,
    CARD_PAD, FONT_BODY, FONT_HEADING, RADIUS, SIZE, SPACE, SUBDIV_COLUMNS,
    SUBDIV_GAP, SURFACE, TABLE_MIN_WIDTH, TEXT, TEXT_FAINT, TEXT_MUTED, TRACK,
)

CAMINHO_BASE = "data/BI CPOC - DOTACAO - Por Ano.xlsx"
LINHAS_VISIVEIS = 6

# campo -> rótulo do filtro (a ordem é a ordem dos selects)
CAMPOS = {
    "iduso": "Iduso",
    "rp": "Res. prim. lei",
    "gnd": "Grupo de despesa",
    "acao": "Ação de governo",
    "ptres": "PTRES",
    "fonte": "Fonte detalhada",
    "po": "Plano orçamentário",
}


# ---------------------------------------------------------------- formatação
def brl(v: float) -> str:
    return "R$ " + f"{round(v):,}".replace(",", ".")


def num(v: float) -> str:
    if not v:
        return "—"
    return f"{round(v):,}".replace(",", ".")


def rotulo_opcao(df, campo: str, cod: str) -> str:
    if campo == "ptres":
        return cod
    nome = df.loc[df[f"{campo}_cod"] == cod, f"{campo}_nome"].iloc[0]
    return f"{cod} — {nome}" if nome else cod


# ------------------------------------------------------------------- estilos
def injetar_css() -> None:
    st.markdown(
        f"""
        <style>
        .po-card {{
            border: 1px solid {BORDER}; border-radius: {RADIUS};
            background: {SURFACE}; padding: {CARD_PAD};
            margin-bottom: {SPACE['xl']};
        }}
        .po-card-head {{
            display: grid; grid-template-columns: minmax(0,1fr) auto;
            gap: 24px; align-items: start; margin-bottom: {SPACE['md']};
        }}
        .po-kicker {{
            font-family: {FONT_HEADING}; font-size: {SIZE['value']};
            letter-spacing: {TRACK['kicker']}; color: {ACCENT}; text-transform: uppercase;
        }}
        .po-title {{
            margin: 3px 0 8px; font-family: {FONT_HEADING}; font-weight: 600;
            font-size: {SIZE['card_title']}; line-height: 1.12; color: {TEXT};
            text-transform: uppercase; text-wrap: pretty;
        }}
        .po-tags {{ display: flex; flex-wrap: wrap; gap: {SPACE['xs']}; }}
        .po-tag {{
            font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
            border: 1px solid {ACCENT_LINE}; border-radius: {RADIUS};
            padding: 2px 7px; background: {ACCENT_SOFT};
        }}
        .po-metric-label {{
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: {TRACK['label']}; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .po-metric {{
            font-family: {FONT_HEADING}; font-size: {SIZE['metric']}; line-height: 1.1;
            color: {ACCENT_STRONG}; font-variant-numeric: tabular-nums;
        }}
        .po-scroll {{ overflow-x: auto; padding-bottom: 2px; }}
        .po-row, .po-head, .po-foot {{
            display: grid; grid-template-columns: {SUBDIV_COLUMNS};
            gap: {SUBDIV_GAP}; min-width: {TABLE_MIN_WIDTH};
        }}
        .po-head {{
            padding-bottom: {SPACE['xs']}; border-bottom: 1px solid {BORDER};
            font-family: {FONT_HEADING}; font-size: {SIZE['micro']};
            letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .po-row {{
            padding: 9px 0; border-bottom: 1px solid {BORDER_SOFT}; align-items: baseline;
        }}
        .po-foot {{ padding-top: 9px; font-family: {FONT_HEADING}; align-items: baseline; }}
        .po-name {{ font-family: {FONT_BODY}; font-size: {SIZE['body']}; line-height: 1.25; color: {TEXT}; }}
        .po-name-sm {{ font-family: {FONT_BODY}; font-size: {SIZE['small']}; line-height: 1.25; color: {TEXT}; }}
        .po-code {{
            font-family: {FONT_HEADING}; font-size: {SIZE['code']};
            letter-spacing: {TRACK['label']}; color: {TEXT_MUTED};
        }}
        .po-flat {{
            font-family: {FONT_HEADING}; font-size: {SIZE['small']};
            letter-spacing: 0.08em; color: {TEXT_MUTED};
        }}
        .po-val {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value']};
            font-variant-numeric: tabular-nums; color: {TEXT_MUTED};
        }}
        .po-val-strong {{
            text-align: right; font-family: {FONT_BODY}; font-size: {SIZE['value_strong']};
            font-weight: 600; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG};
        }}
        .po-foot-label {{
            grid-column: span 6; font-size: {SIZE['label']};
            letter-spacing: {TRACK['label']}; text-transform: uppercase; color: {TEXT_MUTED};
        }}
        .po-foot-val {{ text-align: right; font-size: {SIZE['body']}; font-variant-numeric: tabular-nums; color: {TEXT}; }}
        .po-foot-total {{ text-align: right; font-size: 15px; font-variant-numeric: tabular-nums; color: {ACCENT_STRONG}; }}
        .po-empty {{
            font-family: {FONT_HEADING}; font-size: 16px; letter-spacing: 0.1em;
            text-transform: uppercase; color: {TEXT_MUTED}; padding: 40px 0;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


CABECALHO = [
    ("Plano orçamentário", ""), ("Fonte de recursos detalhada", ""),
    ("Grupo de despesa", ""), ("Res. prim. lei", ""), ("Iduso", ""), ("PTRES", ""),
    ("Inicial", "right"), ("Suplem.", "right"),
    ("Canc./remanej.", "right"), ("Atualizada", "right"),
]


def html_cabecalho() -> str:
    celulas = "".join(
        f'<span style="text-align:{al or "left"}">{t}</span>' for t, al in CABECALHO
    )
    return f'<div class="po-head">{celulas}</div>'


def html_linha(r) -> str:
    def par(nome, cod, prefixo="", classe="po-name-sm"):
        return (
            f'<div><div class="{classe}">{nome or "(não informado)"}</div>'
            f'<div class="po-code">{prefixo}{cod or "—"}</div></div>'
        )

    return (
        '<div class="po-row">'
        + par(r.po_nome, r.po_cod, "PO ", "po-name")
        + par(r.fonte_nome, r.fonte_cod)
        + par(r.gnd_nome, r.gnd_cod, "GND ")
        + par(r.rp_nome, r.rp_cod, "RP ")
        + f'<span class="po-flat">{r.iduso_cod or "—"}</span>'
        + f'<span class="po-flat">{r.ptres_cod or "—"}</span>'
        + f'<span class="po-val">{num(r.ini)}</span>'
        + f'<span class="po-val">{num(r.sup)}</span>'
        + f'<span class="po-val">{num(r.can)}</span>'
        + f'<span class="po-val-strong">{num(r.atu)}</span>'
        + "</div>"
    )


def resumo_atributo(valores) -> str:
    unicos = sorted({v for v in valores if v})
    return unicos[0] if len(unicos) == 1 else f"{len(unicos)} valores"


def render_card(codigo: str, nome: str, grupo, aberto: bool) -> None:
    tags = [
        ("PTRES", resumo_atributo(grupo["ptres_cod"])),
        ("Iduso", resumo_atributo(grupo["iduso_cod"])),
        ("RP", resumo_atributo(grupo["rp_cod"])),
        ("GND", resumo_atributo(grupo["gnd_cod"])),
        ("Fontes", resumo_atributo(grupo["fonte_cod"])),
        ("PO", resumo_atributo(grupo["po_cod"])),
    ]
    tags_html = "".join(f'<span class="po-tag">{k} {v}</span>' for k, v in tags)
    total = float(grupo["atu"].sum())
    n = len(grupo)
    ordenado = grupo.sort_values("atu", ascending=False)
    visiveis = ordenado if aberto else ordenado.head(LINHAS_VISIVEIS)
    linhas = "".join(html_linha(r) for r in visiveis.itertuples())
    somas = {m: float(grupo[m].sum()) for m in ("ini", "sup", "can", "atu")}

    st.markdown(
        f"""
        <div class="po-card">
          <div class="po-card-head">
            <div style="min-width:0">
              <div class="po-kicker">AÇÃO DE GOVERNO {codigo}</div>
              <div class="po-title">{nome}</div>
              <div class="po-tags">{tags_html}</div>
            </div>
            <div style="text-align:right">
              <div class="po-metric-label">Dotação atualizada</div>
              <div class="po-metric">{brl(total)}</div>
              <div class="po-metric-label" style="margin-top:4px">
                {n} {"subdivisão" if n == 1 else "subdivisões"}
              </div>
            </div>
          </div>
          <div class="po-scroll">
            {html_cabecalho()}
            {linhas}
            <div class="po-foot">
              <span class="po-foot-label">Total da ação</span>
              <span class="po-foot-val">{num(somas['ini'])}</span>
              <span class="po-foot-val">{num(somas['sup'])}</span>
              <span class="po-foot-val">{num(somas['can'])}</span>
              <span class="po-foot-total">{num(somas['atu'])}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if n > LINHAS_VISIVEIS:
        st.toggle(
            f"Ver todas as {n} subdivisões",
            key=f"expandir_{codigo}",
            help="Mostra todas as subdivisões desta ação",
        )


# ---------------------------------------------------------------------- página
def main() -> None:
    st.set_page_config(page_title="Painel Orçamentário", layout="wide")
    injetar_css()

    df = carregar_base(CAMINHO_BASE)

    st.markdown("### Painel Orçamentário")
    st.caption("Dotação por ação de governo e subdivisões")

    # --- refino: ano + os sete atributos, em uma linha ---------------------
    colunas = st.columns([0.8] + [1] * len(CAMPOS))
    with colunas[0]:
        ano = st.selectbox("Ano", YEARS, index=len(YEARS) - 1, key="f_ano")

    no_ano = df[df["ano"] == ano]
    escolhas: dict[str, str] = {}

    def passa(frame, ignorar=None):
        mask = frame.index == frame.index          # tudo True
        for campo, valor in escolhas.items():
            if campo == ignorar or not valor:
                continue
            mask &= frame[f"{campo}_cod"] == valor
        return frame[mask]

    # primeira passada só para ter as chaves; os selects usam opções cruzadas
    for campo in CAMPOS:
        escolhas.setdefault(campo, st.session_state.get(f"f_{campo}_cod", ""))

    for i, (campo, rotulo) in enumerate(CAMPOS.items(), start=1):
        base = passa(no_ano, ignorar=campo)
        codigos = sorted({c for c in base[f"{campo}_cod"] if c})
        opcoes = [""] + codigos
        atual = escolhas.get(campo, "")
        indice = opcoes.index(atual) if atual in opcoes else 0
        with colunas[i]:
            escolha = st.selectbox(
                rotulo, opcoes, index=indice, key=f"f_{campo}",
                format_func=lambda c, campo=campo: "Todos" if not c else rotulo_opcao(no_ano, campo, c),
            )
        escolhas[campo] = escolha
        st.session_state[f"f_{campo}_cod"] = escolha

    filtrados = passa(no_ano)

    # --- totais consolidados ---------------------------------------------
    m = st.columns(4)
    for col, (rotulo, campo) in zip(
        m,
        [("Dotação inicial", "ini"), ("Suplementar", "sup"),
         ("Cancelada / remanejada", "can"), ("Dotação atualizada", "atu")],
    ):
        col.metric(rotulo, brl(float(filtrados[campo].sum())))

    ativos = [f"{CAMPOS[c]} {v}" for c, v in escolhas.items() if v]
    acoes = filtrados.groupby(["acao_cod", "acao_nome"], sort=False)
    st.caption(
        f"{acoes.ngroups} ações · {len(filtrados)} lançamentos · "
        + (" · ".join(ativos) if ativos else "sem filtros aplicados")
    )

    if acoes.ngroups == 0:
        st.markdown('<div class="po-empty">Nenhuma ação com dotação para os filtros selecionados.</div>',
                    unsafe_allow_html=True)
        return

    # --- cards, maior dotação primeiro ------------------------------------
    ordem = (
        filtrados.groupby(["acao_cod", "acao_nome"])["atu"].sum()
        .sort_values(ascending=False).index
    )
    for codigo, nome in ordem:
        grupo = filtrados[filtrados["acao_cod"] == codigo]
        render_card(codigo, nome, grupo, aberto=bool(st.session_state.get(f"expandir_{codigo}")))


if __name__ == "__main__":
    main()
