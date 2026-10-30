"""Indicações de empenhos candidatos a anulação — Empenhos com Execução Retardada (30/10/2026).

Camada: regra de negócio, sem Streamlit. Recebe a lista por NE já montada pela tela
(`src/empenhos_retardada_tela.py`: `saldo`, `liquidada`, `percentual_saldo`, `idade_meses`) e as
linhas já filtradas da Execução Mensal, e devolve colunas DERIVADAS. Não descarta nem altera
nenhuma linha ou valor.

INFORMATIVO: uma indicação aponta o que vale analisar; não é recomendação de anular nem decide
nada sozinha. Os limites são parâmetros da tela (propostos em 30/10/2026, a validar pelo usuário):

  * "Saldo negativo (conferir)": saldo < 0 — liquidado acima do empenhado. Não é candidato a
    anulação, é inconsistência a conferir; fica em primeiro na prioridade para não passar
    despercebida.
  * "Nunca liquidada": saldo > 0, liquidado nulo ou zero (nenhum item de execução com valor) e
    idade do saldo ≥ N meses. Idade só existe no exercício da extração (`idade_por_ne`), então a
    indicação também só vale nele.
  * "Sem liquidação recente": saldo > 0, já teve liquidação, e o último mês com liquidado não nulo
    e diferente de zero ficou há ≥ N meses do mês da extração. Só no exercício da extração, pelo
    mesmo motivo da idade (decisão de 17/10/2026): a base de anos anteriores para em dezembro, e o
    que foi liquidado depois como resto a pagar não aparece.
  * "Saldo residual": saldo > 0, liquidado > 0, e saldo ≤ R$ X OU saldo ≤ Y% do empenhado — o
    resto que sobra depois de o empenho ter sido quase todo executado. Vale para qualquer exercício.

Uma NE pode ter várias indicações (coluna `COLUNA_INDICACOES`, separadas por "; "); a principal
(`COLUNA_INDICACAO_PRINCIPAL`) é a primeira da ordem de `INDICACOES`, e "Sem indicação" quando não
há nenhuma — usada no agrupamento. Valor nulo nunca dispara indicação (não dá para afirmar).

Fora daqui, por enquanto: sobra pela projeção de Contratos Contínuos/Bolsas (`src/sobra_empenho.py`)
e saldo de exercícios anteriores.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

NUNCA_LIQUIDADA_MESES_PADRAO = 3
SEM_LIQUIDACAO_MESES_PADRAO = 3
RESIDUAL_RS_PADRAO = 1_000.0
RESIDUAL_PCT_PADRAO = 5.0  # %

SALDO_NEGATIVO = "Saldo negativo (conferir)"
NUNCA_LIQUIDADA = "Nunca liquidada"
SEM_LIQUIDACAO_RECENTE = "Sem liquidação recente"
SALDO_RESIDUAL = "Saldo residual"
SEM_INDICACAO = "Sem indicação"
#: ordem = prioridade da indicação principal
INDICACOES = (SALDO_NEGATIVO, NUNCA_LIQUIDADA, SEM_LIQUIDACAO_RECENTE, SALDO_RESIDUAL)

COLUNA_MESES_SEM_LIQUIDACAO = "meses_sem_liquidacao"
COLUNA_INDICACOES = "indicacoes_anulacao"
COLUNA_INDICACAO_PRINCIPAL = "indicacao_principal"


def parametros_padrao() -> dict[str, Any]:
    return {
        "anul_nunca_meses": NUNCA_LIQUIDADA_MESES_PADRAO,
        "anul_sem_liq_meses": SEM_LIQUIDACAO_MESES_PADRAO,
        "anul_residual_rs": RESIDUAL_RS_PADRAO,
        "anul_residual_pct": RESIDUAL_PCT_PADRAO,
    }


def descrever_parametros(parametros: dict[str, Any]) -> list[tuple[str, str]]:
    """(indicação, regra com os limites em uso) — legenda da tela e cabeçalho do relatório."""

    def meses(n: int) -> str:
        return f"{n} {'mês' if n == 1 else 'meses'}"

    rs = f"{float(parametros['anul_residual_rs']):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    pct = f"{float(parametros['anul_residual_pct']):g}".replace(".", ",")
    return [
        (SALDO_NEGATIVO, "liquidado acima do empenhado"),
        (NUNCA_LIQUIDADA, f"nada liquidado, empenho há {meses(int(parametros['anul_nunca_meses']))} ou mais (só exercício da extração)"),
        (SEM_LIQUIDACAO_RECENTE, f"última liquidação há {meses(int(parametros['anul_sem_liq_meses']))} ou mais (só exercício da extração)"),
        (SALDO_RESIDUAL, f"já liquidado e saldo até R$ {rs} ou até {pct}% do empenhado"),
    ]


def meses_sem_liquidacao_por_ne(filtrado: pd.DataFrame, ano_extracao: int, mes_extracao: int) -> pd.Series:
    """Meses entre o último mês com liquidado (não nulo, diferente de zero) e o mês da extração, por
    `ne_ccor`. Só NE do exercício da extração; NE sem nenhuma liquidação fica de fora (nula)."""

    colunas = {"ne_ccor", "ano", "ano_mes", "liquidada", "tipo_linha"}
    if filtrado.empty or not colunas <= set(filtrado.columns):
        return pd.Series(dtype="Int64", name=COLUNA_MESES_SEM_LIQUIDACAO)
    linhas = filtrado[
        (filtrado["tipo_linha"] == "item_execucao")
        & (filtrado["ano"].astype("Int64") == ano_extracao)
        & filtrado["liquidada"].notna()
        & (filtrado["liquidada"] != 0)
    ]
    if linhas.empty:
        return pd.Series(dtype="Int64", name=COLUNA_MESES_SEM_LIQUIDACAO)
    ultimo = pd.to_numeric(linhas["ano_mes"].astype(str), errors="coerce").groupby(linhas["ne_ccor"]).max().dropna()
    ano, mes = ultimo // 100, ultimo % 100
    return ((ano_extracao * 12 + mes_extracao) - (ano * 12 + mes)).astype("Int64").rename(COLUNA_MESES_SEM_LIQUIDACAO)


def com_indicacoes(
    visivel: pd.DataFrame,
    filtrado: pd.DataFrame,
    ano_extracao: int,
    mes_extracao: int,
    parametros: dict[str, Any],
) -> pd.DataFrame:
    """Cópia de `visivel` com `COLUNA_MESES_SEM_LIQUIDACAO`, `COLUNA_INDICACOES` (nula quando não há
    nenhuma) e `COLUNA_INDICACAO_PRINCIPAL`. Exige `idade_meses` e `percentual_saldo` já calculados."""

    meses = visivel["ne_ccor"].map(meses_sem_liquidacao_por_ne(filtrado, ano_extracao, mes_extracao)).astype("Int64")
    # comparação no centavo: empenhado − liquidado em ponto flutuante deixa resíduos como −1e-14,
    # que não são saldo negativo nem saldo a liquidar (o valor exibido não muda)
    saldo = pd.to_numeric(visivel["saldo"], errors="coerce").round(2)
    liquidada = pd.to_numeric(visivel["liquidada"], errors="coerce").round(2)
    com_saldo = (saldo > 0).fillna(False)
    ja_liquidou = (liquidada.notna() & (liquidada != 0)).fillna(False)
    idade = visivel["idade_meses"].astype("Int64")

    regras = {
        SALDO_NEGATIVO: (saldo < 0).fillna(False),
        NUNCA_LIQUIDADA: com_saldo & ~ja_liquidou & (idade >= int(parametros["anul_nunca_meses"])).fillna(False),
        SEM_LIQUIDACAO_RECENTE: com_saldo & ja_liquidou & (meses >= int(parametros["anul_sem_liq_meses"])).fillna(False),
        SALDO_RESIDUAL: com_saldo
        & (liquidada > 0).fillna(False)
        & (
            (saldo <= float(parametros["anul_residual_rs"])).fillna(False)
            | (visivel["percentual_saldo"] <= float(parametros["anul_residual_pct"])).fillna(False)
        ),
    }
    indicacoes = pd.Series("", index=visivel.index, dtype=object)
    principal = pd.Series(SEM_INDICACAO, index=visivel.index, dtype=object)
    for nome in reversed(INDICACOES):  # do fim para o começo: a de maior prioridade fica por último
        mascara = regras[nome].astype(bool)
        indicacoes = indicacoes.where(~mascara, nome + indicacoes.map(lambda t: f"; {t}" if t else ""))
        principal = principal.where(~mascara, nome)
    return visivel.assign(**{
        COLUNA_MESES_SEM_LIQUIDACAO: meses,
        COLUNA_INDICACOES: indicacoes.where(indicacoes != "", None),
        COLUNA_INDICACAO_PRINCIPAL: principal,
    })


def contagem_por_indicacao(lista: pd.DataFrame) -> list[dict[str, Any]]:
    """Quantas NEs e quanto saldo em cada indicação (uma NE conta em todas as que tiver)."""

    resultado = []
    textos = lista[COLUNA_INDICACOES].fillna("") if COLUNA_INDICACOES in lista.columns else pd.Series("", index=lista.index)
    for nome in INDICACOES:
        mascara = textos.str.split("; ").map(lambda partes: nome in partes)
        do_grupo = lista[mascara]
        resultado.append({"nome": nome, "n": int(len(do_grupo)), "saldo": do_grupo["saldo"].sum(min_count=1)})
    return resultado
