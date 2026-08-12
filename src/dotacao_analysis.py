"""Análises em memória sobre bases validadas de Dotação Orçamentária."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping, Sequence

import pandas as pd

from src.tesouro_dotacao import DOTACAO_OUTPUT_COLUMNS
from src.tesouro_dotacao_validation import DEFAULT_TOLERANCE
from src.tesouro_dotacao_workbook import DotacaoWorkbookResult


DOTACAO_ANALYSIS_SESSION_KEY = "dotacao_analysis_dataset"

FILTER_COLUMNS = {
    "exercicio": "ano_exercicio",
    "iduso": "iduso_codigo",
    "resultado_primario": "resultado_primario_codigo",
    "acao_governo": "acao_codigo",
    "ptres": "ptres_codigo",
    "plano_orcamentario": "plano_orcamentario_codigo",
    "grupo_despesa": "grupo_despesa_codigo",
    "fonte_recursos_detalhada": "fonte_recursos_detalhada_codigo",
    "periodo": "periodo_rotulo_origem",
    "item_informacao": "item_informacao_codigo",
}

KNOWN_ITEM_INDICATORS = {
    "projeto_inicial_loa_fixacao_despesa": "Projeto inicial / LOA",
    "dotacao_inicial": "Dotação inicial",
    "dotacao_suplementar": "Dotação suplementar",
    "dotacao_atualizada": "Dotação atualizada",
    "dotacao_cancelada_remanejada": "Dotação cancelada/remanejada",
    "creditos_adicionais_excesso_arrecadacao": (
        "Créditos adicionais — excesso de arrecadação"
    ),
    "creditos_adicionais_superavit_financeiro": (
        "Créditos adicionais — superávit financeiro"
    ),
}

TRACEABILITY_COLUMNS = [
    "arquivo_origem",
    "aba_origem",
    "linha_origem",
    "coluna_origem",
]

DETAIL_COLUMNS = [
    "arquivo_origem",
    "aba_origem",
    "linha_origem",
    "coluna_origem",
    "ano_exercicio",
    "periodo_rotulo_origem",
    "periodo_ordem",
    "periodo_tipo",
    "mes_numero",
    "iduso_codigo",
    "iduso_descricao",
    "resultado_primario_codigo",
    "resultado_primario_descricao",
    "acao_codigo",
    "acao_descricao",
    "ptres_codigo",
    "plano_orcamentario_codigo",
    "plano_orcamentario_descricao",
    "grupo_despesa_codigo",
    "grupo_despesa_descricao",
    "fonte_recursos_detalhada_codigo",
    "fonte_recursos_detalhada_descricao",
    "item_informacao_origem",
    "item_informacao_codigo",
    "metrica_origem",
    "valor_movimento_liquido",
]

INDICATOR_MEMORY_COLUMNS = [
    "item_informacao_origem",
    "item_informacao_codigo",
    "arquivo_origem",
    "aba_origem",
    "linha_origem",
    "coluna_origem",
    "valor_movimento_liquido",
]

PERIOD_GROUP_COLUMNS = [
    "ano_exercicio",
    "periodo_rotulo_origem",
    "periodo_ordem",
    "periodo_tipo",
    "mes_numero",
    "item_informacao_codigo",
]

# Contrato público consumido pela página Dotação Orçamentária.
# Cada dimensão é agregada diretamente, sem joins entre classificações.
MANAGEMENT_DIMENSION_COLUMNS: dict[str, tuple[str, ...]] = {
    "detalhada": (
        "resultado_primario_codigo",
        "resultado_primario_descricao",
        "iduso_codigo",
        "iduso_descricao",
        "acao_codigo",
        "acao_descricao",
        "ptres_codigo",
        "plano_orcamentario_codigo",
        "plano_orcamentario_descricao",
        "grupo_despesa_codigo",
        "grupo_despesa_descricao",
        "fonte_recursos_detalhada_codigo",
        "fonte_recursos_detalhada_descricao",
    ),
    "acao": ("acao_codigo", "acao_descricao"),
    "ptres": (
        "ptres_codigo",
        "acao_codigo",
        "acao_descricao",
        "plano_orcamentario_codigo",
        "plano_orcamentario_descricao",
    ),
    "grupo_despesa": (
        "grupo_despesa_codigo",
        "grupo_despesa_descricao",
    ),
    "plano_orcamentario": (
        "plano_orcamentario_codigo",
        "plano_orcamentario_descricao",
        "acao_codigo",
        "acao_descricao",
        "ptres_codigo",
    ),
    "fonte": (
        "fonte_recursos_detalhada_codigo",
        "fonte_recursos_detalhada_descricao",
    ),
}

MANAGEMENT_VALUE_COLUMNS = ["total_movimentos", *KNOWN_ITEM_INDICATORS]


@dataclass
class ValidatedDotacaoDataset:
    """Conjunto aprovado para análise, mantido apenas na sessão em memória."""

    filename: str
    source_sha256: str
    sheets: list[str]
    normalized_data: pd.DataFrame
    validation_status: str

    @property
    def row_count(self) -> int:
        return len(self.normalized_data)


@dataclass
class DotacaoIndicatorCalculationMemory:
    """Memória de cálculo de um indicador, reconciliada com suas linhas."""

    item_informacao_codigo: str
    indicador: str
    total_indicador: object
    total_linhas_exibidas: object
    diferenca: object
    quantidade_linhas: int
    quantidade_nulos: int
    quantidade_zeros: int
    quantidade_negativos: int
    linhas: pd.DataFrame

    @property
    def reconciled(self) -> bool:
        return _values_equal(
            self.total_indicador,
            self.total_linhas_exibidas,
        ) and not self.linhas.duplicated(subset=TRACEABILITY_COLUMNS).any()


def prepare_validated_dataset(
    workbook_result: DotacaoWorkbookResult,
    file_content: bytes,
    tolerance: float = DEFAULT_TOLERANCE,
) -> ValidatedDotacaoDataset:
    """Prepara uma cópia analítica somente quando toda a validação foi aprovada."""

    if not workbook_result.integrity_approved:
        raise ValueError(
            "Somente bases de Dotação com normalização aprovada podem ser analisadas."
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

    return ValidatedDotacaoDataset(
        filename=workbook_result.filename,
        source_sha256=sha256(file_content).hexdigest(),
        sheets=list(workbook_result.recognized_sheets),
        normalized_data=normalized,
        validation_status="Aprovada",
    )


def apply_dotacao_filters(
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


def build_indicator_calculation_memory(
    dataframe: pd.DataFrame,
    item_informacao_codigo: str,
) -> DotacaoIndicatorCalculationMemory:
    """Relaciona o total de um indicador às linhas filtradas que o compõem."""

    _validate_normalized_dataframe(dataframe)
    try:
        indicator_label = KNOWN_ITEM_INDICATORS[item_informacao_codigo]
    except KeyError as error:
        raise ValueError(
            "A memória de cálculo só pode ser criada para um indicador conhecido."
        ) from error

    indicators = build_item_indicators(dataframe).set_index(
        "item_informacao_codigo"
    )
    indicator = indicators.loc[item_informacao_codigo]
    lines = dataframe[
        dataframe["item_informacao_codigo"] == item_informacao_codigo
    ].loc[:, INDICATOR_MEMORY_COLUMNS].copy(deep=True)
    line_summary = _value_state_summary(lines["valor_movimento_liquido"])
    total_indicator = indicator["valor_movimento_liquido"]
    total_lines = line_summary["valor_movimento_liquido"]

    return DotacaoIndicatorCalculationMemory(
        item_informacao_codigo=item_informacao_codigo,
        indicador=indicator_label,
        total_indicador=total_indicator,
        total_linhas_exibidas=total_lines,
        diferenca=_numeric_difference(total_indicator, total_lines),
        quantidade_linhas=len(lines),
        quantidade_nulos=line_summary["quantidade_nulos"],
        quantidade_zeros=line_summary["quantidade_zeros"],
        quantidade_negativos=line_summary["quantidade_negativos"],
        linhas=lines,
    )


def build_unknown_item_summary(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Resume itens não mapeados sem removê-los da análise."""

    _validate_normalized_dataframe(dataframe)
    unknown = dataframe[
        ~dataframe["item_informacao_codigo"].isin(KNOWN_ITEM_INDICATORS)
    ].copy(deep=True)
    if unknown.empty:
        return pd.DataFrame(
            columns=[
                "item_informacao_codigo",
                "item_informacao_origem",
                "quantidade_registros",
                "quantidade_nulos",
                "quantidade_zeros",
                "quantidade_negativos",
                "valor_movimento_liquido",
            ]
        )

    records = []
    grouped = unknown.groupby(
        ["item_informacao_codigo", "item_informacao_origem"],
        dropna=False,
        sort=False,
    )
    for (item_code, item_source), group in grouped:
        summary = _value_state_summary(group["valor_movimento_liquido"])
        records.append(
            {
                "item_informacao_codigo": item_code,
                "item_informacao_origem": item_source,
                **summary,
            }
        )

    result = pd.DataFrame.from_records(records)
    result["valor_movimento_liquido"] = pd.array(
        result["valor_movimento_liquido"],
        dtype="Float64",
    )
    return result


def build_period_analysis(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Agrega movimentos por mês e item no escopo analítico."""

    _validate_normalized_dataframe(dataframe)
    if dataframe.empty:
        return pd.DataFrame(
            columns=[
                *PERIOD_GROUP_COLUMNS,
                "item_informacao_origem",
                "periodo_eixo",
                "quantidade_registros",
                "quantidade_nulos",
                "quantidade_zeros",
                "quantidade_negativos",
                "valor_movimento_liquido",
            ]
        )

    records = []
    grouped = dataframe.groupby(PERIOD_GROUP_COLUMNS, dropna=False, sort=False)
    for group_values, group in grouped:
        record = dict(zip(PERIOD_GROUP_COLUMNS, group_values, strict=True))
        item_sources = [
            str(value)
            for value in group["item_informacao_origem"].dropna().unique()
        ]
        record["item_informacao_origem"] = (
            " | ".join(item_sources) if item_sources else pd.NA
        )
        record.update(_value_state_summary(group["valor_movimento_liquido"]))
        record["periodo_eixo"] = _period_axis_label(record)
        records.append(record)

    result = pd.DataFrame.from_records(records)
    result["valor_movimento_liquido"] = pd.array(
        result["valor_movimento_liquido"],
        dtype="Float64",
    )
    return result.sort_values(
        ["ano_exercicio", "periodo_ordem", "item_informacao_codigo"],
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)


def build_dotacao_dimension_analysis(
    dataframe: pd.DataFrame,
    dimension: str,
) -> pd.DataFrame:
    """Agrega a base filtrada por dimensão, sem joins ou identidades entre itens."""

    _validate_normalized_dataframe(dataframe)
    try:
        group_columns = list(MANAGEMENT_DIMENSION_COLUMNS[dimension])
    except KeyError as error:
        raise ValueError(f"Dimensão gerencial não suportada: {dimension}.") from error

    output_columns = [*group_columns, *MANAGEMENT_VALUE_COLUMNS]
    if dataframe.empty:
        result = pd.DataFrame(columns=output_columns)
        for value_column in MANAGEMENT_VALUE_COLUMNS:
            result[value_column] = pd.Series(dtype="Float64")
        return result

    records = []
    grouped = dataframe.groupby(group_columns, dropna=False, sort=False)
    for group_values, group in grouped:
        record = dict(zip(group_columns, group_values, strict=True))
        record["total_movimentos"] = _value_state_summary(
            group["valor_movimento_liquido"]
        )["valor_movimento_liquido"]
        for item_code in KNOWN_ITEM_INDICATORS:
            item_values = group.loc[
                group["item_informacao_codigo"] == item_code,
                "valor_movimento_liquido",
            ]
            record[item_code] = _value_state_summary(item_values)[
                "valor_movimento_liquido"
            ]
        records.append(record)

    result = pd.DataFrame.from_records(records, columns=output_columns)
    for value_column in MANAGEMENT_VALUE_COLUMNS:
        result[value_column] = pd.array(result[value_column], dtype="Float64")
    return result.sort_values(
        group_columns,
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)


def build_detail_view(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Retorna uma linha por movimento com classificações e rastreabilidade."""

    _validate_normalized_dataframe(dataframe)
    return dataframe.loc[:, DETAIL_COLUMNS].copy(deep=True)


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


def _period_axis_label(record: Mapping[str, object]) -> str:
    year = record["ano_exercicio"]
    order = record["periodo_ordem"]
    label = record["periodo_rotulo_origem"]
    year_text = "Sem exercício" if pd.isna(year) else str(int(year))
    order_text = "--" if pd.isna(order) else f"{int(order):02d}"
    label_text = "Sem período" if pd.isna(label) else str(label)
    return f"{year_text} · {order_text} · {label_text}"


def _validate_normalized_dataframe(dataframe: pd.DataFrame) -> None:
    missing_columns = sorted(set(DOTACAO_OUTPUT_COLUMNS).difference(dataframe.columns))
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


def _values_equal(first: object, second: object) -> bool:
    if pd.isna(first) and pd.isna(second):
        return True
    if pd.isna(first) or pd.isna(second):
        return False
    return float(first) == float(second)


def _numeric_difference(first: object, second: object) -> object:
    if pd.isna(first) and pd.isna(second):
        return 0.0
    if pd.isna(first) or pd.isna(second):
        return pd.NA
    return float(second) - float(first)
