"""Blocos visuais da página inicial (28/10/2026).

Funções puras que devolvem HTML (texto sempre escapado) e o CSS da página, para `st.html`. Não calcula
nada: recebe estados já observados (disponibilidade das bases, prazos cadastrados). Classes com prefixo
`hm-`, na linguagem visual de `design_tokens`.
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape

from src import design_tokens as t

TONS = {"azul": t.ACCENT, "verde": t.POSITIVE, "vermelho": t.NEGATIVE, "laranja": t.WARNING, "cinza": t.TEXT_FAINT}
FUNDOS = {"azul": t.ACCENT_SOFT, "verde": t.POSITIVE_SOFT, "vermelho": t.NEGATIVE_SOFT, "laranja": t.WARNING_SOFT,
          "cinza": "rgba(124,141,168,0.14)"}

CSS = f"""<style>
.hm-faixa {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:2px 0 14px; }}
.hm-chip {{ display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:600; padding:5px 12px; border-radius:999px;
  color:var(--c); background:var(--f); }}
.hm-chip i {{ width:8px; height:8px; border-radius:50%; background:var(--c); display:inline-block; }}
.hm-kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; margin:4px 0 22px; }}
.hm-kpi {{ position:relative; background:{t.SURFACE}; border:1px solid {t.BORDER}; border-radius:{t.RADIUS}; padding:18px 20px 16px; overflow:hidden; }}
.hm-kpi::before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:5px; background:var(--c); }}
.hm-kpi .rot {{ font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:{t.TEXT_MUTED}; font-weight:600; }}
.hm-kpi .val {{ font-size:34px; font-weight:700; color:{t.TEXT}; margin-top:6px; line-height:1.05; font-variant-numeric:tabular-nums; }}
.hm-kpi .val small {{ font-size:15px; color:{t.TEXT_MUTED}; font-weight:600; margin-left:6px; }}
.hm-kpi .sub {{ font-size:12px; color:{t.TEXT_MUTED}; margin-top:6px; line-height:1.4; }}
.hm-par {{ display:grid; grid-template-columns:minmax(0,1.25fr) minmax(0,1fr); gap:16px; margin-bottom:8px; }}
@media (max-width: 1100px) {{ .hm-par {{ grid-template-columns:1fr; }} }}
.hm-painel {{ background:{t.SURFACE}; border:1px solid {t.BORDER}; border-radius:{t.RADIUS}; padding:18px 20px; min-width:0; }}
.hm-painel h3 {{ margin:0; font-size:16px; font-weight:700; color:{t.TEXT}; }}
.hm-painel .leg {{ font-size:12px; color:{t.TEXT_MUTED}; margin:2px 0 10px; }}
.hm-linha {{ display:flex; align-items:center; gap:12px; padding:10px 0; border-top:1px solid {t.BORDER}; }}
.hm-linha:first-of-type {{ border-top:0; }}
.hm-linha .corpo {{ flex:1; min-width:0; }}
.hm-linha .tit {{ font-size:13.5px; font-weight:600; color:{t.TEXT}; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.hm-linha .meta {{ font-size:11.5px; color:{t.TEXT_MUTED}; margin-top:1px; }}
.hm-linha .data {{ text-align:right; font-size:12px; color:{t.TEXT_MUTED}; white-space:nowrap; font-variant-numeric:tabular-nums; }}
.hm-linha .data b {{ display:block; font-size:13px; color:{t.TEXT}; }}
.hm-ponto {{ width:10px; height:10px; border-radius:50%; background:var(--c); flex:none; box-shadow:0 0 0 4px var(--f); }}
.hm-vazio {{ font-size:13px; color:{t.TEXT_MUTED}; padding:14px 0 4px; }}
.hm-secao {{ font-size:18px; font-weight:700; color:{t.TEXT}; margin:26px 0 2px; }}
.hm-secao-sub {{ font-size:12.5px; color:{t.TEXT_MUTED}; margin:0 0 12px; }}
.hm-grupo {{ display:flex; align-items:center; gap:10px; margin-bottom:2px; }}
.hm-grupo .ico {{ width:34px; height:34px; border-radius:10px; display:flex; align-items:center; justify-content:center; font-size:17px;
  background:var(--f); color:var(--c); flex:none; }}
.hm-grupo h4 {{ margin:0; font-size:15px; font-weight:700; color:{t.TEXT}; }}
.hm-grupo p {{ margin:0; font-size:11.5px; color:{t.TEXT_MUTED}; }}
</style>"""


def _e(valor) -> str:
    return escape("" if valor is None else str(valor))


def chip(texto: str, tom: str) -> str:
    return f'<span class="hm-chip" style="--c:{TONS[tom]};--f:{FUNDOS[tom]}"><i></i>{_e(texto)}</span>'


def faixa(chips: list[str]) -> str:
    """Faixa de estado logo abaixo do título (chips já montados por `chip`)."""
    return f'<div class="hm-faixa">{"".join(chips)}</div>'


def kpis(itens: list[dict]) -> str:
    """Indicadores: cada item = {"rotulo", "valor", "complemento" (opcional, ex. "de 7"), "sub", "tom"}."""
    cartoes = "".join(
        f'<div class="hm-kpi" style="--c:{TONS[i.get("tom", "azul")]}"><div class="rot">{_e(i["rotulo"])}</div>'
        f'<div class="val">{_e(i["valor"])}' + (f'<small>{_e(i["complemento"])}</small>' if i.get("complemento") else "") + "</div>"
        + (f'<div class="sub">{_e(i["sub"])}</div>' if i.get("sub") else "") + "</div>"
        for i in itens)
    return f'<div class="hm-kpis">{cartoes}</div>'


def _tempo(dias: int) -> str:
    if dias < 0:
        return f"atrasado há {-dias} dia{'s' if dias != -1 else ''}"
    if dias == 0:
        return "vence hoje"
    return f"em {dias} dia{'s' if dias != 1 else ''}"


_TOM_CRITICIDADE = {"Atrasado": "vermelho", "Vencendo": "laranja", "Em dia": "verde"}


def painel_prazos(prazos: list[dict], total_pendentes: int) -> str:
    """Próximos prazos pendentes (cada item: titulo, data_prazo (date), dias_para_vencer, criticidade, categoria, responsavel)."""
    if prazos:
        linhas = "".join(
            f'<div class="hm-linha"><span class="hm-ponto" style="--c:{TONS[_TOM_CRITICIDADE.get(p["criticidade"], "cinza")]};'
            f'--f:{FUNDOS[_TOM_CRITICIDADE.get(p["criticidade"], "cinza")]}"></span>'
            f'<div class="corpo"><div class="tit">{_e(p["titulo"])}</div>'
            f'<div class="meta">{_e(" · ".join(x for x in (p.get("categoria"), p.get("responsavel")) if x) or "sem categoria")}</div></div>'
            f'<div class="data"><b>{p["data_prazo"]:%d/%m/%Y}</b>{_e(_tempo(int(p["dias_para_vencer"])))}</div>'
            f'{chip(p["criticidade"], _TOM_CRITICIDADE.get(p["criticidade"], "cinza"))}</div>'
            for p in prazos)
        legenda = (f"{len(prazos)} de {total_pendentes} prazo(s) pendente(s), do mais urgente para o menos urgente."
                   if total_pendentes > len(prazos) else f"{total_pendentes} prazo(s) pendente(s), do mais urgente para o menos urgente.")
    else:
        linhas = '<div class="hm-vazio">Nenhum prazo orçamentário pendente cadastrado.</div>'
        legenda = "Cadastre os prazos em Gerenciamento de Prazos."
    return f'<div class="hm-painel"><h3>Prazos que pedem atenção</h3><div class="leg">{_e(legenda)}</div>{linhas}</div>'


def painel_bases(bases: list[tuple[str, bool, datetime | None]]) -> str:
    """Estado de cada base cadastrada: (nome, disponível, última atualização)."""
    linhas = "".join(
        f'<div class="hm-linha"><span class="hm-ponto" style="--c:{TONS["verde" if ok else "vermelho"]};--f:{FUNDOS["verde" if ok else "vermelho"]}"></span>'
        f'<div class="corpo"><div class="tit">{_e(nome)}</div>'
        f'<div class="meta">{_e("disponível localmente" if ok else "não encontrada")}</div></div>'
        f'<div class="data">{"<b>" + atualizado_em.strftime("%d/%m/%Y") + "</b>" + atualizado_em.strftime("%H:%M") if (ok and atualizado_em) else "—"}</div></div>'
        for nome, ok, atualizado_em in bases)
    return (f'<div class="hm-painel"><h3>Bases de dados</h3>'
            f'<div class="leg">Disponibilidade e data da última atualização de cada base cadastrada.</div>{linhas}</div>')


def paineis(prazos_html: str, bases_html: str) -> str:
    return f'<div class="hm-par">{prazos_html}{bases_html}</div>'


def secao(titulo: str, explicacao: str | None = None) -> str:
    return f'<div class="hm-secao">{_e(titulo)}</div>' + (f'<p class="hm-secao-sub">{_e(explicacao)}</p>' if explicacao else "")


def cabecalho_grupo(icone: str, titulo: str, descricao: str, tom: str = "azul") -> str:
    return (f'<div class="hm-grupo" style="--c:{TONS[tom]};--f:{FUNDOS[tom]}"><div class="ico">{_e(icone)}</div>'
            f'<div><h4>{_e(titulo)}</h4><p>{_e(descricao)}</p></div></div>')


def dias_ate(data: date, hoje: date) -> int:
    return (data - hoje).days
