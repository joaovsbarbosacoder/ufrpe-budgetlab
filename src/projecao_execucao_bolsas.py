"""Entrada do relatório "Projeção pela Execução" para Bolsas e Auxílios.

Camada: regra da base. Não lê planilha nem importa Streamlit. Pedido de 07/10/2026: o mesmo relatório de
Contratos Contínuos (`src/relatorio_projecao_execucao.py`, regra do fator e da projeção inalterada) em
Bolsas e Auxílios. Bolsa não tem aditivo, vigência nem status de contrato, por isso o custo de cada mês
é calculado aqui, separado do relatório genérico:

  * Valor mensal = `valor_mensal` do cadastro (quantidade efetiva × valor unitário).
  * Meses da bolsa: `meses_no_ano` meses seguidos a partir do início da execução, até dezembro.
    `meses_no_ano` vazio = 12 (mesmo padrão de `src.necessidade_empenho.necessidade_ate_dezembro`). Fração
    de mês (ex.: 10,5) conta no último mês pela fração. Decisão do usuário (07/10/2026): situar os meses
    pelo início, não pelo mês corrente.
  * Início, nesta ordem (decisão de 07/10/2026): (1) o informado no cadastro (`inicio_execucao_mes`);
    (2) o primeiro mês do exercício com liquidação POSITIVA por competência da NE — o empenho costuma
    sair em janeiro, mas a bolsa pode só começar a pagar depois (caso real: 2026NE000022, 10 meses,
    empenho em jan e pagamento de fev a nov; pelo empenho, novembro saía da projeção); estorno ou zero
    não marcam início; (3) o mês do primeiro empenho (`inicio_execucao_efetivo`, sugestão da página);
    (4) janeiro. Só para este relatório — o Relatório de Reforço segue usando `inicio_execucao_efetivo`.

Valores: nulo ≠ zero. Valor mensal desconhecido → custo nulo nos 12 meses (não projeta); valor zero →
custo zero. Programa sem NE fica fora (contado nos avisos do relatório).

Comparações (as mesmas da página): saldo = `saldo_execucao` (Execução Mensal) com o valor colado na
planilha como reserva; empenhado = `valor_empenhado_execucao` com `valor_empenhado_tg` como reserva;
necessidade = a do Resumo Consolidado (`necessidade_ate_dezembro`).
"""

from __future__ import annotations

import math

import pandas as pd

from src.necessidade_empenho import necessidade_ate_dezembro

MESES_NO_ANO_PADRAO = 12


def _numero(valor: object) -> float | None:
    if valor is None or valor is pd.NA:
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(numero) else numero


def custo_mensal_bolsa(valor_mensal: object, meses_no_ano: object, inicio_mes: object) -> list[float]:
    """12 custos do exercício (Jan–Dez) de uma bolsa — ver docstring do módulo."""

    valor = _numero(valor_mensal)
    if valor is None:
        return [float("nan")] * 12
    meses = _numero(meses_no_ano)
    restante = MESES_NO_ANO_PADRAO if meses is None else max(meses, 0.0)
    inicio = _numero(inicio_mes)
    inicio = 1 if inicio is None else int(inicio)
    if not 1 <= inicio <= 12:
        raise ValueError(f"Início da execução fora de 1–12: {inicio_mes!r}")

    custo = [0.0] * 12
    for mes in range(inicio, 13):
        if restante <= 1e-9:
            break
        fracao = min(1.0, restante)
        custo[mes - 1] = valor * fracao
        restante -= fracao
    return custo


def primeiro_mes_liquidado_por_ne(competencia: pd.DataFrame | None, exercicio: int) -> pd.Series:
    """Primeiro mês (1-12) do `exercicio` com liquidação positiva por competência, por `ne_curta`.
    `competencia`: `ne_curta`, `ano_mes`, `valor`. Sem base: série vazia."""

    if competencia is None or competencia.empty:
        return pd.Series(dtype="int64")
    ano_mes = competencia["ano_mes"].astype("int64")
    positivos = competencia[(ano_mes // 100 == exercicio) & (competencia["valor"] > 0)]
    return (positivos["ano_mes"].astype("int64") % 100).groupby(positivos["ne_curta"]).min()


def _primeiro_valor(serie: pd.Series) -> object:
    """Primeiro valor não nulo — valor de execução por NE vem repetido em cada programa da mesma NE."""

    validos = serie.dropna()
    return validos.iloc[0] if not validos.empty else None


def _unir_textos(serie: pd.Series) -> object:
    textos = [str(v) for v in serie.dropna().unique() if str(v).strip()]
    return "; ".join(textos) if textos else None


def entrada_relatorio(
    filtrado: pd.DataFrame, competencia: pd.DataFrame | None = None, exercicio: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, list[float]]]:
    """`(por_ne, sem_ne, custos)` para `relatorio_projecao_execucao.montar_relatorio(..., custos=custos,
    rotulos=BOLSAS_AUXILIOS)`. `por_ne` usa as colunas do relatório genérico (programa em `fornecedor`,
    processo em `contrato_numero`, situação em `status_contrato`); uma linha por NE — programas que
    dividem a mesma NE somam valor mensal, custo e necessidade, e os valores de execução da NE (saldo,
    empenhado) entram uma vez só. Não altera `filtrado`.

    `competencia`/`exercicio`: Liquidação por Competência (`ne_curta`, `ano_mes`, `valor`) para o início
    automático (ver docstring do módulo); sem ela, o início é o do cadastro ou o do primeiro empenho.

    `filtrado` precisa de `ne_curta`, `programa_bolsa`, `processo`, `situacao_tg`, `valor_mensal`,
    `meses_no_ano`, `inicio_execucao_mes`, `inicio_execucao_efetivo`, `valor_empenhado_execucao`, `valor_empenhado_tg`,
    `saldo_execucao` e `saldo_colado_planilha`."""

    dados = filtrado.copy()
    primeiro_liquidado = (
        primeiro_mes_liquidado_por_ne(competencia, exercicio) if exercicio is not None else pd.Series(dtype="int64")
    )
    inicio = (
        pd.to_numeric(dados["inicio_execucao_mes"], errors="coerce")
        .fillna(dados["ne_curta"].map(primeiro_liquidado))
        .fillna(pd.to_numeric(dados["inicio_execucao_efetivo"], errors="coerce"))
    )
    empenhado = dados["valor_empenhado_execucao"].fillna(dados["valor_empenhado_tg"])
    _, necessidade = necessidade_ate_dezembro(dados["valor_mensal"].fillna(0.0), empenhado, dados["meses_no_ano"])
    dados = dados.assign(
        _empenhado=empenhado,
        _saldo=dados["saldo_execucao"].fillna(dados["saldo_colado_planilha"]),
        _necessidade=necessidade,
        _inicio=inicio,
    )

    tem_ne = dados["ne_curta"].notna() & dados["ne_curta"].astype("string").str.strip().ne("")
    sem_ne = dados[~tem_ne].reset_index(drop=True)
    com_ne = dados[tem_ne]

    linhas, custos = [], {}
    for ne, grupo in com_ne.groupby("ne_curta", sort=True):
        custos_programas = [
            custo_mensal_bolsa(v, m, i)
            for v, m, i in zip(grupo["valor_mensal"], grupo["meses_no_ano"], grupo["_inicio"])
        ]
        custos[ne] = [sum(c[mes] for c in custos_programas) for mes in range(12)]  # NaN propaga: nulo continua nulo
        linhas.append(
            {
                "ne_curta": ne,
                "fornecedor": _unir_textos(grupo["programa_bolsa"]),
                "contrato_numero": _unir_textos(grupo["processo"]),
                "status_contrato": _unir_textos(grupo["situacao_tg"]),
                "vigencia_fim": None,
                "despesa_mensal": grupo["valor_mensal"].sum(min_count=1),
                "valor_empenhado_exibido": _primeiro_valor(grupo["_empenhado"]),
                "saldo_para_necessidade": _primeiro_valor(grupo["_saldo"]),
                "necessidade": grupo["_necessidade"].sum(min_count=1),
            }
        )
    por_ne = pd.DataFrame(
        linhas,
        columns=[
            "ne_curta", "fornecedor", "contrato_numero", "status_contrato", "vigencia_fim", "despesa_mensal",
            "valor_empenhado_exibido", "saldo_para_necessidade", "necessidade",
        ],
    )
    return por_ne, sem_ne, custos
