"""Validação de integridade da normalização de Dotação do Tesouro Gerencial."""

from __future__ import annotations

from dataclasses import dataclass
import numbers

import pandas as pd

from src.tesouro_dotacao import (
    VALUE_START_COLUMN,
    classify_dotacao_period,
    recognize_dotacao_base,
)


DEFAULT_TOLERANCE = 0.000001
NULL_GROUP_LABEL = "<NULO>"

INCONSISTENCY_COLUMNS = [
    "tipo",
    "periodo",
    "item_informacao",
    "linha_origem",
    "coluna_origem",
    "valor_matriz_original",
    "valor_base_normalizada",
    "diferenca",
    "mensagem",
]


@dataclass
class DotacaoNormalizationValidation:
    """Métricas e comparações de uma aba normalizada."""

    sheet_name: str
    tolerance: float
    raw_data_row_count: int
    monetary_column_count: int
    monetary_cell_count: int
    normalized_row_count: int
    raw_null_count: int
    normalized_null_count: int
    raw_zero_count: int
    normalized_zero_count: int
    raw_negative_count: int
    normalized_negative_count: int
    raw_sum: float
    normalized_sum: float
    difference: float
    period_comparison: pd.DataFrame
    item_comparison: pd.DataFrame
    period_item_comparison: pd.DataFrame
    inconsistencies: pd.DataFrame
    periods_found: list[str]
    periods_in_scope: list[str]
    periods_ignored: list[str]
    ignored_column_count: int
    ignored_monetary_cell_count: int
    ignored_value_sum: float

    @property
    def approved(self) -> bool:
        return self.inconsistencies.empty


@dataclass
class _PeriodScopeSummary:
    periods_found: list[str]
    periods_in_scope: list[str]
    periods_ignored: list[str]
    invalid_periods: list[str]
    included_column_indices: list[int]
    ignored_column_count: int
    ignored_monetary_cell_count: int
    ignored_value_sum: float


def validate_dotacao_normalization(
    raw_dataframe: pd.DataFrame,
    normalized_dataframe: pd.DataFrame,
    sheet_name: str,
    tolerance: float = DEFAULT_TOLERANCE,
) -> DotacaoNormalizationValidation:
    """Compara a matriz monetária bruta e sua representação em formato longo."""

    if tolerance < 0:
        raise ValueError("A tolerância não pode ser negativa.")

    raw = raw_dataframe.copy(deep=True)
    normalized = normalized_dataframe.copy(deep=True)

    recognition = recognize_dotacao_base(raw)
    if not recognition.matched:
        raise ValueError(
            "A validação só pode ser executada em uma aba reconhecida como "
            "Dotação do Tesouro Gerencial."
        )

    required_columns = {
        "aba_origem",
        "linha_origem",
        "coluna_origem",
        "periodo_rotulo_origem",
        "item_informacao_origem",
        "valor_movimento_liquido",
    }
    missing_columns = sorted(required_columns.difference(normalized.columns))
    if missing_columns:
        raise ValueError(
            "A base normalizada não contém as colunas necessárias: "
            + ", ".join(missing_columns)
        )

    normalized = normalized[normalized["aba_origem"] == sheet_name].copy(deep=True)
    period_scope = _summarize_period_scope(raw)
    raw_long = _build_raw_monetary_long(
        raw,
        period_scope.included_column_indices,
    )
    normalized_long = _build_normalized_monetary_long(normalized)

    raw_data_row_count = max(raw.shape[0] - 3, 0)
    monetary_column_count = len(period_scope.included_column_indices)
    monetary_cell_count = raw_data_row_count * monetary_column_count
    normalized_row_count = len(normalized_long)

    raw_values = raw_long["valor"]
    normalized_values = normalized_long["valor"]

    raw_null_count = int(raw_values.isna().sum())
    normalized_null_count = int(normalized_values.isna().sum())
    raw_zero_count = int(raw_values.eq(0).fillna(False).sum())
    normalized_zero_count = int(normalized_values.eq(0).fillna(False).sum())
    raw_negative_count = int(raw_values.lt(0).fillna(False).sum())
    normalized_negative_count = int(normalized_values.lt(0).fillna(False).sum())

    raw_sum = float(raw_values.sum(skipna=True))
    normalized_sum = float(normalized_values.sum(skipna=True))
    difference = normalized_sum - raw_sum

    period_comparison = _compare_aggregates(
        raw_long,
        normalized_long,
        ["periodo_rotulo_origem"],
        tolerance,
    )
    item_comparison = _compare_aggregates(
        raw_long,
        normalized_long,
        ["item_informacao_origem"],
        tolerance,
    )
    period_item_comparison = _compare_aggregates(
        raw_long,
        normalized_long,
        ["periodo_rotulo_origem", "item_informacao_origem"],
        tolerance,
    )

    inconsistency_records: list[dict[str, object]] = []
    for period in period_scope.invalid_periods:
        inconsistency_records.append(
            _inconsistency_record(
                inconsistency_type="periodo_fora_do_escopo",
                original_value=pd.NA,
                normalized_value=pd.NA,
                difference=pd.NA,
                message=f"Período não reconhecido para o escopo analítico: '{period}'.",
                period=period,
            )
        )
    _append_count_inconsistency(
        inconsistency_records,
        "quantidade_linhas_normalizadas",
        monetary_cell_count,
        normalized_row_count,
        "A quantidade de linhas normalizadas difere de linhas brutas × "
        "colunas monetárias.",
    )
    _append_count_inconsistency(
        inconsistency_records,
        "quantidade_nulos",
        raw_null_count,
        normalized_null_count,
        "A quantidade de valores nulos não foi preservada.",
    )
    _append_count_inconsistency(
        inconsistency_records,
        "quantidade_zeros",
        raw_zero_count,
        normalized_zero_count,
        "A quantidade de valores iguais a zero não foi preservada.",
    )
    _append_count_inconsistency(
        inconsistency_records,
        "quantidade_negativos",
        raw_negative_count,
        normalized_negative_count,
        "A quantidade de valores negativos não foi preservada.",
    )

    if not _values_equal(raw_sum, normalized_sum, tolerance):
        inconsistency_records.append(
            _inconsistency_record(
                inconsistency_type="soma_total",
                original_value=raw_sum,
                normalized_value=normalized_sum,
                difference=difference,
                message="A soma total difere acima da tolerância.",
            )
        )

    inconsistency_records.extend(
        _coordinate_inconsistencies(raw_long, normalized_long, tolerance)
    )
    inconsistency_records.extend(
        _aggregate_inconsistencies(period_comparison, "soma_por_periodo")
    )
    inconsistency_records.extend(
        _aggregate_inconsistencies(item_comparison, "soma_por_item")
    )
    inconsistency_records.extend(
        _aggregate_inconsistencies(
            period_item_comparison,
            "soma_por_periodo_item",
        )
    )

    inconsistencies = pd.DataFrame.from_records(
        inconsistency_records,
        columns=INCONSISTENCY_COLUMNS,
    )

    return DotacaoNormalizationValidation(
        sheet_name=sheet_name,
        tolerance=tolerance,
        raw_data_row_count=raw_data_row_count,
        monetary_column_count=monetary_column_count,
        monetary_cell_count=monetary_cell_count,
        normalized_row_count=normalized_row_count,
        raw_null_count=raw_null_count,
        normalized_null_count=normalized_null_count,
        raw_zero_count=raw_zero_count,
        normalized_zero_count=normalized_zero_count,
        raw_negative_count=raw_negative_count,
        normalized_negative_count=normalized_negative_count,
        raw_sum=raw_sum,
        normalized_sum=normalized_sum,
        difference=difference,
        period_comparison=period_comparison,
        item_comparison=item_comparison,
        period_item_comparison=period_item_comparison,
        inconsistencies=inconsistencies,
        periods_found=period_scope.periods_found,
        periods_in_scope=period_scope.periods_in_scope,
        periods_ignored=period_scope.periods_ignored,
        ignored_column_count=period_scope.ignored_column_count,
        ignored_monetary_cell_count=period_scope.ignored_monetary_cell_count,
        ignored_value_sum=period_scope.ignored_value_sum,
    )


def _build_raw_monetary_long(
    raw: pd.DataFrame,
    included_column_indices: list[int],
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    if not included_column_indices:
        return pd.DataFrame(
            columns=[
                "linha_origem",
                "coluna_origem",
                "periodo_rotulo_origem",
                "item_informacao_origem",
                "valor",
            ]
        )

    period_headers = raw.iloc[0, VALUE_START_COLUMN:].copy().ffill()
    for column_index in included_column_indices:
        period = _clean_period_label(
            period_headers.iloc[column_index - VALUE_START_COLUMN]
        )
        item = _clean_text(raw.iat[1, column_index])
        for row_index in range(3, raw.shape[0]):
            records.append(
                {
                    "linha_origem": row_index + 1,
                    "coluna_origem": _excel_column_name(column_index),
                    "periodo_rotulo_origem": _group_key(period),
                    "item_informacao_origem": _group_key(item),
                    "valor": pd.to_numeric(raw.iat[row_index, column_index], errors="coerce"),
                }
            )

    dataframe = pd.DataFrame.from_records(
        records,
        columns=[
            "linha_origem",
            "coluna_origem",
            "periodo_rotulo_origem",
            "item_informacao_origem",
            "valor",
        ],
    )
    dataframe["valor"] = pd.array(dataframe["valor"], dtype="Float64")
    return dataframe


def _summarize_period_scope(raw: pd.DataFrame) -> _PeriodScopeSummary:
    periods_found: list[str] = []
    periods_in_scope: list[str] = []
    periods_ignored: list[str] = []
    invalid_periods: list[str] = []
    included_column_indices: list[int] = []
    ignored_column_count = 0
    ignored_value_sum = 0.0
    raw_data_row_count = max(raw.shape[0] - 3, 0)

    if raw.shape[1] <= VALUE_START_COLUMN:
        return _PeriodScopeSummary(
            periods_found=periods_found,
            periods_in_scope=periods_in_scope,
            periods_ignored=periods_ignored,
            invalid_periods=invalid_periods,
            included_column_indices=included_column_indices,
            ignored_column_count=ignored_column_count,
            ignored_monetary_cell_count=0,
            ignored_value_sum=ignored_value_sum,
        )

    period_headers = raw.iloc[0, VALUE_START_COLUMN:].copy().ffill()
    for offset, column_index in enumerate(
        range(VALUE_START_COLUMN, raw.shape[1])
    ):
        period = _clean_period_label(period_headers.iloc[offset])
        if not pd.isna(period):
            _append_unique(periods_found, str(period))
        scope, _, _, _ = classify_dotacao_period(period)
        if scope == "included":
            included_column_indices.append(column_index)
            _append_unique(periods_in_scope, str(period))
        elif scope == "ignored":
            ignored_column_count += 1
            _append_unique(periods_ignored, str(period))
            ignored_values = pd.to_numeric(
                raw.iloc[3:, column_index],
                errors="coerce",
            )
            ignored_value_sum += float(ignored_values.sum(skipna=True))
        else:
            _append_unique(
                invalid_periods,
                str(period) if not pd.isna(period) else "vazio",
            )

    return _PeriodScopeSummary(
        periods_found=periods_found,
        periods_in_scope=periods_in_scope,
        periods_ignored=periods_ignored,
        invalid_periods=invalid_periods,
        included_column_indices=included_column_indices,
        ignored_column_count=ignored_column_count,
        ignored_monetary_cell_count=raw_data_row_count * ignored_column_count,
        ignored_value_sum=ignored_value_sum,
    )


def _build_normalized_monetary_long(normalized: pd.DataFrame) -> pd.DataFrame:
    dataframe = normalized[
        [
            "linha_origem",
            "coluna_origem",
            "periodo_rotulo_origem",
            "item_informacao_origem",
            "valor_movimento_liquido",
        ]
    ].copy(deep=True)
    dataframe["periodo_rotulo_origem"] = dataframe[
        "periodo_rotulo_origem"
    ].map(_group_key)
    dataframe["item_informacao_origem"] = dataframe[
        "item_informacao_origem"
    ].map(_group_key)
    dataframe["valor"] = pd.array(
        pd.to_numeric(dataframe.pop("valor_movimento_liquido"), errors="coerce"),
        dtype="Float64",
    )
    return dataframe


def _compare_aggregates(
    raw_long: pd.DataFrame,
    normalized_long: pd.DataFrame,
    group_columns: list[str],
    tolerance: float,
) -> pd.DataFrame:
    raw_grouped = (
        raw_long.groupby(group_columns, dropna=False, sort=False)["valor"]
        .sum(min_count=1)
        .reset_index(name="soma_matriz_original")
    )
    normalized_grouped = (
        normalized_long.groupby(group_columns, dropna=False, sort=False)["valor"]
        .sum(min_count=1)
        .reset_index(name="soma_base_normalizada")
    )
    comparison = raw_grouped.merge(
        normalized_grouped,
        on=group_columns,
        how="outer",
        indicator=True,
    )

    differences: list[object] = []
    consistent_values: list[bool] = []
    for _, row in comparison.iterrows():
        original_value = row["soma_matriz_original"]
        normalized_value = row["soma_base_normalizada"]
        both_present = row["_merge"] == "both"
        consistent = both_present and _values_equal(
            original_value,
            normalized_value,
            tolerance,
        )
        consistent_values.append(consistent)
        differences.append(_numeric_difference(original_value, normalized_value))

    comparison["diferenca"] = pd.array(differences, dtype="Float64")
    comparison["consistente"] = consistent_values
    comparison = comparison.drop(columns="_merge")
    for column in group_columns:
        comparison[column] = comparison[column].replace(NULL_GROUP_LABEL, pd.NA)
    return comparison


def _coordinate_inconsistencies(
    raw_long: pd.DataFrame,
    normalized_long: pd.DataFrame,
    tolerance: float,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    coordinate_columns = ["linha_origem", "coluna_origem"]

    duplicate_coordinates = normalized_long.duplicated(
        subset=coordinate_columns,
        keep=False,
    )
    if duplicate_coordinates.any():
        records.append(
            _inconsistency_record(
                inconsistency_type="coordenadas_duplicadas",
                original_value=0,
                normalized_value=int(duplicate_coordinates.sum()),
                difference=int(duplicate_coordinates.sum()),
                message="A base normalizada possui coordenadas de origem duplicadas.",
            )
        )

    normalized_unique = normalized_long.drop_duplicates(
        subset=coordinate_columns,
        keep="first",
    )
    comparison = raw_long.merge(
        normalized_unique,
        on=coordinate_columns,
        how="outer",
        suffixes=("_original", "_normalizada"),
        indicator=True,
    )
    for _, row in comparison.iterrows():
        original_value = row.get("valor_original", pd.NA)
        normalized_value = row.get("valor_normalizada", pd.NA)
        if row["_merge"] == "both" and _values_equal(
            original_value,
            normalized_value,
            tolerance,
        ):
            continue

        period = row.get("periodo_rotulo_origem_original", pd.NA)
        item = row.get("item_informacao_origem_original", pd.NA)
        records.append(
            _inconsistency_record(
                inconsistency_type="valor_por_coordenada",
                period=_display_group_value(period),
                item=_display_group_value(item),
                source_row=row.get("linha_origem", pd.NA),
                source_column=row.get("coluna_origem", pd.NA),
                original_value=original_value,
                normalized_value=normalized_value,
                difference=_numeric_difference(original_value, normalized_value),
                message="O valor monetário difere na coordenada de origem.",
            )
        )
    return records


def _aggregate_inconsistencies(
    comparison: pd.DataFrame,
    inconsistency_type: str,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for _, row in comparison[~comparison["consistente"]].iterrows():
        records.append(
            _inconsistency_record(
                inconsistency_type=inconsistency_type,
                period=row.get("periodo_rotulo_origem", pd.NA),
                item=row.get("item_informacao_origem", pd.NA),
                original_value=row["soma_matriz_original"],
                normalized_value=row["soma_base_normalizada"],
                difference=row["diferenca"],
                message="A soma agregada difere acima da tolerância.",
            )
        )
    return records


def _append_count_inconsistency(
    records: list[dict[str, object]],
    inconsistency_type: str,
    expected: int,
    observed: int,
    message: str,
) -> None:
    if expected == observed:
        return
    records.append(
        _inconsistency_record(
            inconsistency_type=inconsistency_type,
            original_value=expected,
            normalized_value=observed,
            difference=observed - expected,
            message=message,
        )
    )


def _inconsistency_record(
    inconsistency_type: str,
    original_value: object,
    normalized_value: object,
    difference: object,
    message: str,
    period: object = pd.NA,
    item: object = pd.NA,
    source_row: object = pd.NA,
    source_column: object = pd.NA,
) -> dict[str, object]:
    return {
        "tipo": inconsistency_type,
        "periodo": period,
        "item_informacao": item,
        "linha_origem": source_row,
        "coluna_origem": source_column,
        "valor_matriz_original": original_value,
        "valor_base_normalizada": normalized_value,
        "diferenca": difference,
        "mensagem": message,
    }


def _values_equal(first: object, second: object, tolerance: float) -> bool:
    first_is_null = pd.isna(first)
    second_is_null = pd.isna(second)
    if first_is_null and second_is_null:
        return True
    if first_is_null or second_is_null:
        return False
    return abs(float(second) - float(first)) <= tolerance


def _numeric_difference(original: object, normalized: object) -> object:
    if pd.isna(original) and pd.isna(normalized):
        return 0.0
    if pd.isna(original) or pd.isna(normalized):
        return pd.NA
    return float(normalized) - float(original)


def _group_key(value: object) -> str:
    if pd.isna(value):
        return NULL_GROUP_LABEL
    text = str(value).strip()
    return text if text else NULL_GROUP_LABEL


def _display_group_value(value: object) -> object:
    if pd.isna(value) or value == NULL_GROUP_LABEL:
        return pd.NA
    return value


def _clean_text(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    text = str(value).strip()
    return text or pd.NA


def _clean_period_label(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        numeric_value = float(value)
        if numeric_value.is_integer():
            return str(int(numeric_value))
    return _clean_text(value)


def _excel_column_name(zero_based_index: int) -> str:
    column_number = zero_based_index + 1
    letters = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
