"""Análise conjunta por recorte agregado de Dotação e Execução validadas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import pandas as pd

from src.dotacao_analysis import ValidatedDotacaoDataset
from src.execucao_analysis import ValidatedExecucaoDataset
from src.tesouro_dotacao import DOTACAO_OUTPUT_COLUMNS
from src.tesouro_execucao import EXECUCAO_OUTPUT_COLUMNS


# Compatibilidade confirmada pela mesma dimensão codificada nas duas assinaturas.
COMMON_DIMENSIONS = {
    "iduso": ("iduso_codigo", "iduso_codigo"),
    "resultado_primario": ("resultado_primario_codigo", "resultado_primario_codigo"),
    "acao_governo": ("acao_codigo", "acao_codigo"),
    "plano_orcamentario": ("plano_orcamentario_codigo", "plano_orcamentario_codigo"),
    "grupo_despesa": ("grupo_despesa_codigo", "grupo_despesa_codigo"),
    "fonte_recursos_detalhada": ("fonte_recursos_detalhada_codigo", "fonte_recursos_detalhada_codigo"),
    "ptres": ("ptres_codigo", "ptres_codigo"),
}

INDICATOR_DEFINITIONS = (
    ("dotacao_atualizada", "Dotação Atualizada", "dotacao", "dotacao_atualizada"),
    ("despesa_empenhada", "Empenhado", "execucao", "despesa_empenhada"),
    ("despesa_liquidada", "Liquidado", "execucao", "despesa_liquidada"),
    ("despesa_paga", "Pago", "execucao", "despesa_paga"),
)


@dataclass
class VisaoOrcamentariaResult:
    dotacao_filtrada: pd.DataFrame
    execucao_filtrada: pd.DataFrame
    indicadores: pd.DataFrame


def build_common_filter_options(dotacao: pd.DataFrame, execucao: pd.DataFrame) -> dict[str, list[object]]:
    """Retorna a união de códigos para que um filtro tenha efeito explícito em ambas."""

    _validate_inputs(dotacao, execucao)
    return {
        name: sorted(
            set(dotacao[dot_column].dropna().tolist()) | set(execucao[exec_column].dropna().tolist()),
            key=str,
        )
        for name, (dot_column, exec_column) in COMMON_DIMENSIONS.items()
    }


def apply_common_filters(dotacao: pd.DataFrame, execucao: pd.DataFrame, selections: Mapping[str, Sequence[object]] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filtra cada origem separadamente; não combina nem replica linhas."""

    _validate_inputs(dotacao, execucao)
    filtered_dotacao, filtered_execucao = dotacao.copy(deep=True), execucao.copy(deep=True)
    for name, selected in (selections or {}).items():
        if name not in COMMON_DIMENSIONS:
            raise ValueError(f"Filtro comum não suportado: {name}.")
        values = list(selected)
        if not values:
            continue
        dot_column, exec_column = COMMON_DIMENSIONS[name]
        filtered_dotacao = _filter_values(filtered_dotacao, dot_column, values)
        filtered_execucao = _filter_values(filtered_execucao, exec_column, values)
    return filtered_dotacao, filtered_execucao


def build_visao_orcamentaria(dotacao_dataset: ValidatedDotacaoDataset, execucao_dataset: ValidatedExecucaoDataset, selections: Mapping[str, Sequence[object]] | None = None) -> VisaoOrcamentariaResult:
    """Calcula indicadores diretamente das fontes validadas, em um recorte comum."""

    if dotacao_dataset.validation_status != "Aprovada" or execucao_dataset.validation_status != "Aprovada":
        raise ValueError("A Visão Orçamentária requer as duas bases validadas.")
    dotacao, execucao = apply_common_filters(dotacao_dataset.normalized_data, execucao_dataset.normalized_data, selections)
    records = []
    for code, label, source, selector in INDICATOR_DEFINITIONS:
        rows = dotacao[dotacao["item_informacao_codigo"] == selector] if source == "dotacao" else execucao[execucao["metrica_execucao_codigo"] == selector]
        records.append({"indicador_codigo": code, "indicador": label, "origem": source, **_summary(rows)})
    indicators = pd.DataFrame.from_records(records)
    indicators["valor_movimento_liquido"] = pd.array(indicators["valor_movimento_liquido"], dtype="Float64")
    return VisaoOrcamentariaResult(dotacao, execucao, indicators)


def build_memorias_por_origem(result: VisaoOrcamentariaResult) -> dict[str, pd.DataFrame]:
    """Expõe as linhas de cálculo sem perder a rastreabilidade própria de cada base."""

    dotacao = result.dotacao_filtrada[result.dotacao_filtrada["item_informacao_codigo"] == "dotacao_atualizada"].copy(deep=True)
    execucao = result.execucao_filtrada[result.execucao_filtrada["metrica_execucao_codigo"].isin(["despesa_empenhada", "despesa_liquidada", "despesa_paga"])].copy(deep=True)
    return {"dotacao": dotacao, "execucao": execucao}


def _summary(dataframe: pd.DataFrame) -> dict[str, object]:
    values = pd.Series(pd.array(pd.to_numeric(dataframe["valor_movimento_liquido"], errors="coerce"), dtype="Float64"))
    if (dataframe["valor_movimento_liquido"].notna() & values.isna()).any():
        raise ValueError("A base analítica contém valor monetário não numérico.")
    return {
        "quantidade_registros": len(values),
        "quantidade_nulos": int(values.isna().sum()),
        "quantidade_zeros": int(values.eq(0).fillna(False).sum()),
        "quantidade_negativos": int(values.lt(0).fillna(False).sum()),
        "valor_movimento_liquido": values.sum(min_count=1),
    }


def _filter_values(dataframe: pd.DataFrame, column: str, values: list[object]) -> pd.DataFrame:
    include_null = any(_is_null_scalar(value) for value in values)
    non_null = [value for value in values if not _is_null_scalar(value)]
    mask = dataframe[column].isin(non_null)
    if include_null:
        mask |= dataframe[column].isna()
    return dataframe.loc[mask].copy(deep=True)


def _validate_inputs(dotacao: pd.DataFrame, execucao: pd.DataFrame) -> None:
    missing_dotacao = sorted(set(DOTACAO_OUTPUT_COLUMNS).difference(dotacao.columns))
    missing_execucao = sorted(set(EXECUCAO_OUTPUT_COLUMNS).difference(execucao.columns))
    if missing_dotacao or missing_execucao:
        raise ValueError("As bases normalizadas não possuem o contrato necessário para a Visão Orçamentária.")


def _is_null_scalar(value: object) -> bool:
    result = pd.isna(value)
    try:
        return bool(result)
    except (TypeError, ValueError):
        return False
