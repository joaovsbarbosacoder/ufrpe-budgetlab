"""Alertas Gerenciais — categorias calculáveis de verdade a partir de Dotação/Execução.

Só duas das 8 categorias da página têm dado real disponível hoje (as outras dependem de
Contratos/Bolsas/critérios ainda não definidos com a PROPLAD — ver docstring da página):

- **Ações com déficit projetado**: Ação de Governo onde o Empenhado (UGR Gestão UFRPE, ver
  `UGR_UFRPE` — mesmo filtro e mesmo motivo de `app_pages/dotacao_orcamentaria.py`, que exclui
  orçamento descentralizado de outras UGRs) já supera a Dotação Atualizada do exercício.
- **Recursos de emendas parlamentares não executados**: saldo a empenhar (Dotação Atualizada −
  Empenhado) do Resultado Primário 6 — o único RP de emenda que a Dotação Anual desta
  extração realmente tem (RP 7/8 só existem na Execução, sem dotação correspondente ainda;
  por isso não entram aqui, pra não inventar um "saldo" sem contrapartida orçamentária real).

Ambas comparam Dotação x Execução no exercício em andamento (`ano_extracao`, derivado da data
de extração do manifesto de Execução Anual — mesmo padrão de
`app_pages/dotacao_orcamentaria.py`).
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

#: UGR da própria UFRPE na Execução Anual — ver `app_pages/dotacao_orcamentaria.py::UGR_UFRPE`
#: para o achado completo (sem este filtro, Empenhado inclui orçamento descentralizado de
#: outras UGRs e fica sistematicamente maior que a Dotação Atualizada da UFRPE).
UGR_UFRPE = "15239"

#: Resultado Primário de emenda parlamentar que a Dotação Anual desta extração realmente tem
#: (achado real — ver docstring do módulo).
RP_EMENDA_COM_DOTACAO = "6"


def ano_extracao_execucao(manifesto_execucao) -> int:
    return datetime.fromisoformat(manifesto_execucao.data_extracao).year


def acoes_com_deficit(dotacao: pd.DataFrame, execucao: pd.DataFrame, ano: int) -> list[dict]:
    """Só ações com Dotação Atualizada > 0 E Empenhado acima dela — déficit de verdade, não
    "sem dotação lançada ainda" (algumas ações têm Empenhado no exercício em andamento sem
    nenhuma linha de Dotação Atualizada correspondente nesta extração; isso é uma lacuna de
    carregamento de dado, não um déficit, e contá-la aqui inflaria a categoria com um alerta
    que não existe de verdade — confirmado nos dados: em 2026 nenhuma ação tem déficit real,
    só ações sem dotação lançada)."""

    atualizada_por_acao = (
        dotacao[(dotacao["ano_lancamento"] == ano) & (dotacao["item_informacao_codigo"] == "dotacao_atualizada")]
        .groupby("acao_codigo")["valor_movimento_liquido"]
        .sum(min_count=1)
    )
    empenhado_por_acao = (
        execucao[(execucao["ano"] == ano) & (execucao["ugr_cod"] == UGR_UFRPE)]
        .groupby("acao_cod")["empenhada"]
        .sum(min_count=1)
    )
    descricoes = dict(
        dotacao[["acao_codigo", "acao_descricao"]].dropna().drop_duplicates().itertuples(index=False, name=None)
    )

    itens = []
    for codigo, atualizada in atualizada_por_acao.items():
        atualizada = float(atualizada) if pd.notna(atualizada) else 0.0
        if not atualizada:
            continue
        empenhado = empenhado_por_acao.get(codigo, 0.0) or 0.0
        deficit = float(empenhado) - atualizada
        if deficit <= 0:
            continue
        descricao = descricoes.get(codigo, "(sem descrição na Dotação Anual)")
        percentual = f"{deficit / atualizada * 100:,.0f}%".replace(",", ".")
        detalhe = f"Empenhado (UGR Gestão UFRPE) supera a Dotação Atualizada de {ano} em {percentual}"
        itens.append({"nome": f"{codigo} — {descricao}", "detalhe": detalhe, "valor": deficit})
    return sorted(itens, key=lambda item: item["valor"], reverse=True)


def emendas_rp6_nao_executadas(dotacao: pd.DataFrame, execucao: pd.DataFrame, ano: int) -> list[dict]:
    atualizada_rp6 = (
        dotacao[
            (dotacao["ano_lancamento"] == ano)
            & (dotacao["item_informacao_codigo"] == "dotacao_atualizada")
            & (dotacao["resultado_primario_codigo"] == RP_EMENDA_COM_DOTACAO)
        ]["valor_movimento_liquido"].sum(min_count=1)
    )
    empenhado_rp6 = (
        execucao[
            (execucao["ano"] == ano)
            & (execucao["ugr_cod"] == UGR_UFRPE)
            & (execucao["resultado_primario_cod"] == RP_EMENDA_COM_DOTACAO)
        ]["empenhada"].sum(min_count=1)
    )
    atualizada_rp6 = float(atualizada_rp6) if pd.notna(atualizada_rp6) else 0.0
    empenhado_rp6 = float(empenhado_rp6) if pd.notna(empenhado_rp6) else 0.0
    saldo = atualizada_rp6 - empenhado_rp6
    if saldo <= 0 or not atualizada_rp6:
        return []
    percentual = f"{saldo / atualizada_rp6 * 100:,.0f}%".replace(",", ".")
    return [
        {
            "nome": f"RP6 — Emenda Individual ({ano})",
            "detalhe": f"Saldo a empenhar de {percentual} da Dotação Atualizada de emenda individual (UGR Gestão UFRPE)",
            "valor": saldo,
        }
    ]
