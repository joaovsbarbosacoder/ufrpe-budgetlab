"""Liquidação por Competência × Execução Mensal (SIAFI), por NE: avisos de divergência (03/11/2026).

Pedido do usuário (03/11/2026, caso 2026NE000551 — Minha Biblioteca): o executado e o saldo de Contratos Contínuos e de
Bolsas e Auxílios vêm da competência (empenhado − liquidado por competência). O relatório de competência de 03/11 trouxe
a mesma apropriação em dois NS e o executado da NE passou do empenho sem nenhum aviso. Este módulo só AVISA: nenhum
valor da conta muda, porque a regra de qual base prevalece quando as duas divergem não está definida.

  * Acima do empenhado: liquidado por competência − empenhado (Execução Mensal) > R$ 0,01 — saldo negativo, o executado
    passa do empenho.
  * Acima do SIAFI: liquidado por competência − liquidado (Execução Mensal) > R$ 0,01, sem passar do empenhado — pode ser
    competência apurada antes do lançamento (normal) ou documento em duplicidade; por isso é aviso à parte, mais brando.
  * Só diferenças para MAIS (competência abaixo do SIAFI é o atraso comum da apropriação, fora deste pedido).
  * Nulo não vira zero: NE sem competência não é comparada; sem empenhado (ou sem liquidado) na Execução Mensal, a
    comparação correspondente não é feita.
  * Documentos repetidos (`liquidacao_competencia.documentos_repetidos`) da NE avisada entram no texto, para conferência.

Camada analítica: não importa Streamlit.
"""

from __future__ import annotations

import pandas as pd

from src.execucao_ne_utils import indice_liquidado_por_ne_curta, indice_valor_empenhado_por_ne_curta, ne_curta

#: diferença mínima (R$) para avisar — a mesma tolerância de centavo das demais divergências de saldo do projeto
TOLERANCIA = 0.01

COLUNAS = [
    "ne_curta", "empenhado", "liquidado_siafi", "liquidado_competencia", "diferenca_siafi", "acima_do_empenho",
    "documentos_repetidos",
]


def _brl(valor: float | None) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _documento_curto(codigo: str) -> str:
    """NP/NS sem o prefixo de UG + gestão (11 dígitos), como a NE curta: "153165152392026NP001010" → "2026NP001010".
    Código fora desse formato volta como veio."""

    codigo = str(codigo).strip()
    return codigo[11:] if len(codigo) > 11 and codigo[:11].isdigit() and codigo[11:15].isdigit() else codigo


def _numero(valor: object) -> float | None:
    numero = pd.to_numeric(valor, errors="coerce")
    return None if pd.isna(numero) else float(numero)


def divergencias_por_ne(
    nes: list[str] | pd.Series | set[str],
    indice_competencia: pd.Series | None,
    por_ne_execucao: pd.DataFrame,
    repetidos: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Uma linha por NE de `nes` (forma curta) cuja competência passa do empenhado ou do liquidado no SIAFI.

    `indice_competencia`: `ne_curta` → total liquidado por competência (`liquidado_por_ne` com a NE curta).
    `por_ne_execucao`: `saldo_por_ne(agregar_por_ne(...))` da Execução Mensal. `repetidos`: saída de
    `documentos_repetidos` (opcional). Competência indisponível (`None`): nada a comparar, DataFrame vazio."""

    if indice_competencia is None or len(indice_competencia) == 0:
        return pd.DataFrame(columns=COLUNAS)
    # NE curta repetida (mesma NE em prefixos de UG diferentes): soma, sem perder o nulo (min_count=1)
    indice_competencia = indice_competencia.groupby(level=0).sum(min_count=1)
    empenhado = indice_valor_empenhado_por_ne_curta(por_ne_execucao).groupby(level=0).sum(min_count=1)
    liquidado = indice_liquidado_por_ne_curta(por_ne_execucao).groupby(level=0).sum(min_count=1)
    textos_repetidos: dict[str, list[str]] = {}
    if repetidos is not None:
        for _, r in repetidos.iterrows():
            textos_repetidos.setdefault(ne_curta(str(r["ne_ccor"])), []).append(
                f"{_documento_curto(r['documento_habil'])} com "
                + " e ".join(_documento_curto(d) for d in str(r["docs_contabeis"]).split(", "))
                + f" repetindo {int(r['meses'])} mês(es) "
                f"({_brl(r['valor_por_documento'])} cada)"
            )

    linhas = []
    for ne in dict.fromkeys(str(n) for n in nes if pd.notna(n)):
        competencia = _numero(indice_competencia.get(ne))
        if competencia is None:
            continue
        emp = _numero(empenhado.get(ne))
        liq = _numero(liquidado.get(ne))
        acima_empenho = emp is not None and competencia - emp > TOLERANCIA
        acima_siafi = liq is not None and competencia - liq > TOLERANCIA
        if not (acima_empenho or acima_siafi):
            continue
        linhas.append({
            "ne_curta": ne, "empenhado": emp, "liquidado_siafi": liq, "liquidado_competencia": competencia,
            "diferenca_siafi": None if liq is None else round(competencia - liq, 2),
            "acima_do_empenho": acima_empenho,
            "documentos_repetidos": "; ".join(textos_repetidos[ne]) if ne in textos_repetidos else None,
        })
    return pd.DataFrame(linhas, columns=COLUNAS)


def avisos_divergencia(divergencias: pd.DataFrame, origem: str) -> list[str]:
    """Até dois avisos (acima do empenhado; acima só do SIAFI) com os valores das duas bases por NE."""

    def _detalhe(l: pd.Series, com_empenho: bool) -> str:
        texto = l["ne_curta"] + " — " + (f"empenhado {_brl(l['empenhado'])}, " if com_empenho else "")
        texto += f"liquidado no SIAFI {_brl(l['liquidado_siafi'])}, por competência {_brl(l['liquidado_competencia'])}"
        if l["diferenca_siafi"] is not None and pd.notna(l["diferenca_siafi"]):
            texto += f" (+{_brl(l['diferenca_siafi'])} sobre o SIAFI)"
        if isinstance(l["documentos_repetidos"], str):
            texto += f"; documento {l['documentos_repetidos']}"
        return texto

    avisos = []
    if divergencias.empty:
        return avisos
    acima = divergencias[divergencias["acima_do_empenho"].astype(bool)]
    if not acima.empty:
        avisos.append(
            f"{origem}: liquidação por competência acima do empenhado (saldo negativo: o executado passa do empenho) — "
            "conferir no SIAFI; nenhum valor foi alterado: "
            + "; ".join(_detalhe(l, True) for _, l in acima.iterrows()) + "."
        )
    so_siafi = divergencias[~divergencias["acima_do_empenho"].astype(bool)]
    if not so_siafi.empty:
        avisos.append(
            f"{origem}: liquidação por competência acima do liquidado no SIAFI (competência apurada antes do lançamento, "
            "ou documento em duplicidade — conferir): "
            + "; ".join(_detalhe(l, False) for _, l in so_siafi.iterrows()) + "."
        )
    return avisos
