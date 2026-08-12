"""Análises em memória sobre bases validadas de Dotação Anual (BI CPOC - Por Ano)."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping, Sequence

import pandas as pd

from src.tesouro_dotacao_anual import DOTACAO_ANUAL_OUTPUT_COLUMNS
from src.tesouro_dotacao_anual_validation import DEFAULT_TOLERANCE
from src.tesouro_dotacao_anual_workbook import DotacaoAnualWorkbookResult


DOTACAO_ANUAL_ANALYSIS_SESSION_KEY = "dotacao_anual_analysis_dataset"

FILTER_COLUMNS = {
    "ano": "ano_lancamento",
    "iduso": "iduso_codigo",
    "resultado_primario": "resultado_primario_codigo",
    "acao_governo": "acao_codigo",
    "ptres": "ptres_codigo",
    "plano_orcamentario": "plano_orcamentario_codigo",
    "grupo_despesa": "grupo_despesa_codigo",
    "fonte_recursos_detalhada": "fonte_recursos_detalhada_codigo",
}

KNOWN_ITEM_INDICATORS = {
    "dotacao_inicial": "Dotação inicial",
    "dotacao_suplementar": "Dotação suplementar",
    "dotacao_atualizada": "Dotação atualizada",
    "dotacao_cancelada_remanejada": "Dotação cancelada/remanejada",
}

TRACEABILITY_COLUMNS = [
    "arquivo_origem",
    "aba_origem",
    "linha_origem",
    "coluna_origem",
]

YEAR_ANALYSIS_COLUMNS = ["ano_lancamento", *KNOWN_ITEM_INDICATORS]

# Ação primeiro (agrupador do painel de cartões), demais dimensões na
# hierarquia já usada no restante do projeto.
SUBDIVISION_DIMENSION_COLUMNS = (
    "acao_codigo",
    "acao_descricao",
    "ptres_codigo",
    "plano_orcamentario_codigo",
    "plano_orcamentario_descricao",
    "grupo_despesa_codigo",
    "grupo_despesa_descricao",
    "resultado_primario_codigo",
    "resultado_primario_descricao",
    "iduso_codigo",
    "iduso_descricao",
    "fonte_recursos_detalhada_codigo",
    "fonte_recursos_detalhada_descricao",
)

SUBDIVISION_ANALYSIS_COLUMNS = [*SUBDIVISION_DIMENSION_COLUMNS, *KNOWN_ITEM_INDICATORS]


@dataclass
class ValidatedDotacaoAnualDataset:
    """Conjunto aprovado para análise, mantido apenas na sessão em memória."""

    filename: str
    source_sha256: str
    sheets: list[str]
    normalized_data: pd.DataFrame
    validation_status: str

    @property
    def row_count(self) -> int:
        return len(self.normalized_data)


def prepare_validated_dotacao_anual_dataset(
    workbook_result: DotacaoAnualWorkbookResult,
    file_content: bytes,
    tolerance: float = DEFAULT_TOLERANCE,
) -> ValidatedDotacaoAnualDataset:
    """Prepara uma cópia analítica somente quando toda a validação foi aprovada."""

    if not workbook_result.integrity_approved:
        raise ValueError(
            "Somente bases de Dotação Anual com normalização aprovada podem ser "
            "analisadas."
        )

    normalized = workbook_result.consolidated_data.copy(deep=True)
    _validate_normalized_dataframe(normalized)
    if normalized.empty:
        raise ValueError("A base normalizada aprovada não possui registros.")

    if normalized.duplicated(subset=TRACEABILITY_COLUMNS).any():
        raise ValueError("A base analítica possui coordenadas de origem duplicadas.")

    if len(normalized) != workbook_result.normalized_row_count:
        raise ValueError(
            "A quantidade de registros analíticos difere da validação multiaba."
        )

    values = normalized["valor_movimento_liquido"]
    normalized_sum = float(values.sum(skipna=True))
    if abs(normalized_sum - workbook_result.normalized_sum) > tolerance:
        raise ValueError("A soma da base analítica difere da validação multiaba.")

    return ValidatedDotacaoAnualDataset(
        filename=workbook_result.filename,
        source_sha256=sha256(file_content).hexdigest(),
        sheets=list(workbook_result.recognized_sheets),
        normalized_data=normalized,
        validation_status="Aprovada",
    )


def apply_dotacao_anual_filters(
    dataframe: pd.DataFrame,
    selections: Mapping[str, Sequence[object]] | None = None,
) -> pd.DataFrame:
    """Aplica filtros inclusivos por dimensão sem agregar ou alterar valores."""

    _validate_normalized_dataframe(dataframe)
    filtered = dataframe.copy(deep=True)

    for filter_name, selected_values in (selections or {}).items():
        try:
            column = FILTER_COLUMNS[filter_name]
        except KeyError as error:
            raise ValueError(f"Filtro não suportado: {filter_name}.") from error

        values = list(selected_values)
        if not values:
            continue

        include_null = any(_is_null_scalar(value) for value in values)
        non_null_values = [value for value in values if not _is_null_scalar(value)]
        column_mask = filtered[column].isin(non_null_values)
        if include_null:
            column_mask = column_mask | filtered[column].isna()
        filtered = filtered.loc[column_mask].copy(deep=True)

    return filtered


def build_item_indicators(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Soma cada item conhecido isoladamente, sem criar identidades entre itens."""

    _validate_normalized_dataframe(dataframe)
    records = []
    for item_code, item_label in KNOWN_ITEM_INDICATORS.items():
        item_rows = dataframe[dataframe["item_informacao_codigo"] == item_code]
        records.append(_summary_record(item_rows, item_code, item_label))

    result = pd.DataFrame.from_records(records)
    result["valor_movimento_liquido"] = pd.array(
        result["valor_movimento_liquido"],
        dtype="Float64",
    )
    return result


def build_dotacao_anual_year_analysis(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Agrega cada indicador conhecido por ano de lançamento, isoladamente."""

    _validate_normalized_dataframe(dataframe)
    if dataframe.empty:
        result = pd.DataFrame(columns=YEAR_ANALYSIS_COLUMNS)
        for value_column in KNOWN_ITEM_INDICATORS:
            result[value_column] = pd.Series(dtype="Float64")
        return result

    records = []
    grouped = dataframe.groupby("ano_lancamento", dropna=False, sort=False)
    for ano, group in grouped:
        record: dict[str, object] = {"ano_lancamento": ano}
        for item_code in KNOWN_ITEM_INDICATORS:
            item_values = group.loc[
                group["item_informacao_codigo"] == item_code,
                "valor_movimento_liquido",
            ]
            record[item_code] = _value_state_summary(item_values)["valor_movimento_liquido"]
        records.append(record)

    result = pd.DataFrame.from_records(records, columns=YEAR_ANALYSIS_COLUMNS)
    for value_column in KNOWN_ITEM_INDICATORS:
        result[value_column] = pd.array(result[value_column], dtype="Float64")
    return result.sort_values(
        "ano_lancamento", na_position="last", kind="stable"
    ).reset_index(drop=True)


def build_dotacao_anual_subdivision_analysis(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Agrega por Ação Governo e demais dimensões, uma linha por subdivisão.

    Cada indicador conhecido continua sendo somado isoladamente por
    subdivisão; não há identidade algébrica criada entre eles nem entre
    subdivisões de uma mesma Ação.
    """

    _validate_normalized_dataframe(dataframe)
    group_columns = list(SUBDIVISION_DIMENSION_COLUMNS)
    if dataframe.empty:
        result = pd.DataFrame(columns=SUBDIVISION_ANALYSIS_COLUMNS)
        for value_column in KNOWN_ITEM_INDICATORS:
            result[value_column] = pd.Series(dtype="Float64")
        return result

    records = []
    grouped = dataframe.groupby(group_columns, dropna=False, sort=False)
    for group_values, group in grouped:
        record: dict[str, object] = dict(zip(group_columns, group_values, strict=True))
        for item_code in KNOWN_ITEM_INDICATORS:
            item_values = group.loc[
                group["item_informacao_codigo"] == item_code,
                "valor_movimento_liquido",
            ]
            record[item_code] = _value_state_summary(item_values)["valor_movimento_liquido"]
        records.append(record)

    result = pd.DataFrame.from_records(records, columns=SUBDIVISION_ANALYSIS_COLUMNS)
    for value_column in KNOWN_ITEM_INDICATORS:
        result[value_column] = pd.array(result[value_column], dtype="Float64")
    return result.sort_values(
        group_columns, na_position="last", kind="stable"
    ).reset_index(drop=True)


def summarize_value_states(dataframe: pd.DataFrame) -> dict[str, object]:
    """Conta estados monetários sem confundir ausência, zero e negativo."""

    _validate_normalized_dataframe(dataframe)
    return _value_state_summary(dataframe["valor_movimento_liquido"])


def _summary_record(
    dataframe: pd.DataFrame,
    item_code: str,
    item_label: str,
) -> dict[str, object]:
    return {
        "item_informacao_codigo": item_code,
        "indicador": item_label,
        **_value_state_summary(dataframe["valor_movimento_liquido"]),
    }


def _value_state_summary(values: pd.Series) -> dict[str, object]:
    converted = pd.to_numeric(values, errors="coerce")
    invalid_values = values.notna() & converted.isna()
    if invalid_values.any():
        raise ValueError("A base analítica contém valor monetário não numérico.")
    numeric_values = pd.array(converted, dtype="Float64")
    value_series = pd.Series(numeric_values)
    total = value_series.sum(min_count=1)
    return {
        "quantidade_registros": len(value_series),
        "quantidade_nulos": int(value_series.isna().sum()),
        "quantidade_zeros": int(value_series.eq(0).fillna(False).sum()),
        "quantidade_negativos": int(value_series.lt(0).fillna(False).sum()),
        "valor_movimento_liquido": total,
    }


def _validate_normalized_dataframe(dataframe: pd.DataFrame) -> None:
    missing_columns = sorted(
        set(DOTACAO_ANUAL_OUTPUT_COLUMNS).difference(dataframe.columns)
    )
    if missing_columns:
        raise ValueError(
            "A base normalizada não contém as colunas necessárias: "
            + ", ".join(missing_columns)
        )


def _is_null_scalar(value: object) -> bool:
    result = pd.isna(value)
    try:
        return bool(result)
    except (TypeError, ValueError):
        return False
