"""Validação independente da normalização de Execução da Despesa."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.tesouro_execucao import METRICS, VALUE_COLUMN_INDICES, recognize_execucao_base


DEFAULT_TOLERANCE = 0.000001
INCONSISTENCY_COLUMNS = ["tipo", "metrica_execucao_codigo", "ano_lancamento", "linha_origem", "coluna_origem", "valor_origem", "valor_normalizado", "diferenca", "mensagem"]


@dataclass
class ExecucaoNormalizationValidation:
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
    metric_comparison: pd.DataFrame
    year_comparison: pd.DataFrame
    metric_year_comparison: pd.DataFrame
    inconsistencies: pd.DataFrame

    @property
    def approved(self) -> bool:
        return self.inconsistencies.empty


def validate_execucao_normalization(raw_dataframe: pd.DataFrame, normalized_dataframe: pd.DataFrame, sheet_name: str, tolerance: float = DEFAULT_TOLERANCE) -> ExecucaoNormalizationValidation:
    """Compara a origem AJ:AL à saída longa, sem criar regras entre métricas."""

    if tolerance < 0:
        raise ValueError("A tolerância não pode ser negativa.")
    raw = raw_dataframe.copy(deep=True)
    normalized = normalized_dataframe.copy(deep=True)
    if not recognize_execucao_base(raw).matched:
        raise ValueError("A validação só pode ser executada em uma aba reconhecida como Execução da Despesa.")
    required = {"aba_origem", "linha_origem", "coluna_origem", "ano_lancamento", "metrica_execucao_codigo", "valor_movimento_liquido"}
    missing = sorted(required.difference(normalized.columns))
    if missing:
        raise ValueError("A base normalizada não contém as colunas necessárias: " + ", ".join(missing))

    raw_long = _build_raw_long(raw)
    normalized_long = _build_normalized_long(normalized[normalized["aba_origem"] == sheet_name].copy(deep=True))
    raw_values, normalized_values = raw_long["valor"], normalized_long["valor"]
    counts = lambda values: (int(values.isna().sum()), int(values.eq(0).fillna(False).sum()), int(values.lt(0).fillna(False).sum()))
    raw_null, raw_zero, raw_negative = counts(raw_values)
    norm_null, norm_zero, norm_negative = counts(normalized_values)
    raw_sum, normalized_sum = float(raw_values.sum(skipna=True)), float(normalized_values.sum(skipna=True))
    metric_comparison = _compare_aggregates(raw_long, normalized_long, ["metrica_execucao_codigo"], tolerance)
    year_comparison = _compare_aggregates(raw_long, normalized_long, ["ano_lancamento"], tolerance)
    metric_year_comparison = _compare_aggregates(raw_long, normalized_long, ["metrica_execucao_codigo", "ano_lancamento"], tolerance)

    records: list[dict[str, object]] = []
    expected_cells = len(raw_long)
    for kind, expected, observed, message in [
        ("quantidade_linhas_normalizadas", expected_cells, len(normalized_long), "A quantidade de linhas normalizadas difere de linhas brutas × medidas."),
        ("quantidade_nulos", raw_null, norm_null, "A quantidade de valores nulos não foi preservada."),
        ("quantidade_zeros", raw_zero, norm_zero, "A quantidade de valores iguais a zero não foi preservada."),
        ("quantidade_negativos", raw_negative, norm_negative, "A quantidade de valores negativos não foi preservada."),
    ]:
        if expected != observed:
            records.append(_record(kind, expected, observed, observed - expected, message))
    if not _values_equal(raw_sum, normalized_sum, tolerance):
        records.append(_record("soma_total", raw_sum, normalized_sum, normalized_sum - raw_sum, "A soma total difere acima da tolerância."))
    records.extend(_coordinate_inconsistencies(raw_long, normalized_long, tolerance))
    for comparison, kind in [(metric_comparison, "soma_por_medida"), (year_comparison, "soma_por_ano"), (metric_year_comparison, "soma_por_medida_ano")]:
        for _, row in comparison[~comparison["consistente"]].iterrows():
            records.append(_record(kind, row["soma_origem"], row["soma_normalizada"], row["diferenca"], "A soma agregada difere acima da tolerância.", row.get("metrica_execucao_codigo", pd.NA), row.get("ano_lancamento", pd.NA)))
    inconsistencies = pd.DataFrame.from_records(records, columns=INCONSISTENCY_COLUMNS)
    return ExecucaoNormalizationValidation(sheet_name, tolerance, len(raw) - 2, 3, expected_cells, len(normalized_long), raw_null, norm_null, raw_zero, norm_zero, raw_negative, norm_negative, raw_sum, normalized_sum, normalized_sum - raw_sum, metric_comparison, year_comparison, metric_year_comparison, inconsistencies)


def _build_raw_long(raw: pd.DataFrame) -> pd.DataFrame:
    records = []
    for row_index in range(2, len(raw)):
        year = _year(raw.iat[row_index, 34])
        for column_index in VALUE_COLUMN_INDICES:
            records.append({"linha_origem": row_index + 1, "coluna_origem": _column_name(column_index), "metrica_execucao_codigo": METRICS[column_index], "ano_lancamento": year, "valor": pd.to_numeric(raw.iat[row_index, column_index], errors="coerce")})
    dataframe = pd.DataFrame.from_records(records)
    dataframe["ano_lancamento"] = pd.array(dataframe["ano_lancamento"], dtype="Int64")
    dataframe["valor"] = pd.array(dataframe["valor"], dtype="Float64")
    return dataframe


def _build_normalized_long(normalized: pd.DataFrame) -> pd.DataFrame:
    dataframe = normalized[["linha_origem", "coluna_origem", "metrica_execucao_codigo", "ano_lancamento", "valor_movimento_liquido"]].copy(deep=True)
    dataframe["valor"] = pd.array(pd.to_numeric(dataframe.pop("valor_movimento_liquido"), errors="coerce"), dtype="Float64")
    return dataframe


def _compare_aggregates(raw: pd.DataFrame, normalized: pd.DataFrame, columns: list[str], tolerance: float) -> pd.DataFrame:
    original = raw.groupby(columns, dropna=False, sort=False)["valor"].sum(min_count=1).reset_index(name="soma_origem")
    transformed = normalized.groupby(columns, dropna=False, sort=False)["valor"].sum(min_count=1).reset_index(name="soma_normalizada")
    comparison = original.merge(transformed, on=columns, how="outer", indicator=True)
    comparison["diferenca"] = pd.array([_difference(row["soma_origem"], row["soma_normalizada"]) for _, row in comparison.iterrows()], dtype="Float64")
    comparison["consistente"] = [row["_merge"] == "both" and _values_equal(row["soma_origem"], row["soma_normalizada"], tolerance) for _, row in comparison.iterrows()]
    return comparison.drop(columns="_merge")


def _coordinate_inconsistencies(raw: pd.DataFrame, normalized: pd.DataFrame, tolerance: float) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    coordinates = ["linha_origem", "coluna_origem"]
    duplicate_count = int(normalized.duplicated(subset=coordinates, keep=False).sum())
    if duplicate_count:
        records.append(_record("coordenadas_duplicadas", 0, duplicate_count, duplicate_count, "A base normalizada possui coordenadas de origem duplicadas."))
    comparison = raw.merge(normalized.drop_duplicates(subset=coordinates, keep="first"), on=coordinates, how="outer", suffixes=("_origem", "_normalizada"), indicator=True)
    for _, row in comparison.iterrows():
        original, transformed = row.get("valor_origem", pd.NA), row.get("valor_normalizada", pd.NA)
        if row["_merge"] == "both" and _values_equal(original, transformed, tolerance):
            continue
        records.append(_record("valor_por_coordenada", original, transformed, _difference(original, transformed), "O valor monetário difere na coordenada de origem.", row.get("metrica_execucao_codigo_origem", pd.NA), row.get("ano_lancamento_origem", pd.NA), row.get("linha_origem", pd.NA), row.get("coluna_origem", pd.NA)))
    return records


def _record(kind: str, original: object, transformed: object, difference: object, message: str, metric: object = pd.NA, year: object = pd.NA, row: object = pd.NA, column: object = pd.NA) -> dict[str, object]:
    return {"tipo": kind, "metrica_execucao_codigo": metric, "ano_lancamento": year, "linha_origem": row, "coluna_origem": column, "valor_origem": original, "valor_normalizado": transformed, "diferenca": difference, "mensagem": message}


def _values_equal(first: object, second: object, tolerance: float) -> bool:
    if pd.isna(first) and pd.isna(second): return True
    if pd.isna(first) or pd.isna(second): return False
    return abs(float(second) - float(first)) <= tolerance


def _difference(first: object, second: object) -> object:
    if pd.isna(first) and pd.isna(second): return 0.0
    if pd.isna(first) or pd.isna(second): return pd.NA
    return float(second) - float(first)


def _year(value: object) -> object:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric) or float(numeric) % 1: return pd.NA
    return int(numeric)


def _column_name(index: int) -> str:
    number, letters = index + 1, ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
