"""Reconhecimento e normalização de bases de Dotação do Tesouro Gerencial."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import numbers
from pathlib import Path
import re
import unicodedata

import pandas as pd


DIMENSION_COLUMN_COUNT = 13
HIERARCHY_COLUMN_COUNT = 11
VALUE_START_COLUMN = 13

DOTACAO_OUTPUT_COLUMNS = [
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

CODE_COLUMNS = [
    "iduso_codigo",
    "resultado_primario_codigo",
    "acao_codigo",
    "ptres_codigo",
    "plano_orcamentario_codigo",
    "grupo_despesa_codigo",
    "fonte_recursos_detalhada_codigo",
    "item_informacao_codigo",
]

STRING_COLUMNS = [
    "arquivo_origem",
    "aba_origem",
    "coluna_origem",
    "periodo_rotulo_origem",
    "periodo_tipo",
    "iduso_descricao",
    "resultado_primario_descricao",
    "acao_descricao",
    "plano_orcamentario_descricao",
    "grupo_despesa_descricao",
    "fonte_recursos_detalhada_descricao",
    "item_informacao_origem",
    "metrica_origem",
    *CODE_COLUMNS,
]

HEADER_SIGNATURE = {
    "A1": (0, 0, "IDUSO"),
    "C1": (0, 2, "Resultado Primário Lei"),
    "E1": (0, 4, "Ação Governo"),
    "G1": (0, 6, "PTRES"),
    "H1": (0, 7, "Plano Orçamentário"),
    "J1": (0, 9, "Grupo Despesa"),
    "L1": (0, 11, "Mês Lançamento"),
    "L2": (1, 11, "Item Informação"),
    "L3": (2, 11, "Fonte Recursos Detalhada"),
}

HEADER_SIGNATURE_ALIASES = {
    # "Período" occurs in representative legacy exports; do not add fuzzy aliases.
    "L1": ("Período",),
}

MONTHS = {
    "JAN": 1,
    "FEV": 2,
    "MAR": 3,
    "ABR": 4,
    "MAI": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SET": 9,
    "OUT": 10,
    "NOV": 11,
    "DEZ": 12,
}

KNOWN_ITEM_CODES = {
    "projeto inicial loa fixacao despesa": "projeto_inicial_loa_fixacao_despesa",
    "projeto inicial da loa fixacao da despesa": (
        "projeto_inicial_loa_fixacao_despesa"
    ),
    "dotacao inicial": "dotacao_inicial",
    "dotacao suplementar": "dotacao_suplementar",
    "dotacao atualizada": "dotacao_atualizada",
    "dotacao cancelada remanejada": "dotacao_cancelada_remanejada",
    "creditos adicionais excesso arrecadacao": (
        "creditos_adicionais_excesso_arrecadacao"
    ),
    "creditos adicionais excesso de arrecadacao": (
        "creditos_adicionais_excesso_arrecadacao"
    ),
    "creditos adicionais superavit financeiro": (
        "creditos_adicionais_superavit_financeiro"
    ),
}


@dataclass
class DotacaoRecognition:
    """Resultado auditável do reconhecimento estrutural."""

    matched: bool
    validation_failures: list[str]


@dataclass
class DotacaoTransformResult:
    """Resultado da normalização de uma aba anual de Dotação."""

    recognized: bool
    normalized_data: pd.DataFrame
    raw_row_count: int
    normalized_row_count: int
    periods_found: list[str]
    items_found: list[str]
    warnings: list[str]
    validation_failures: list[str]
    periods_in_scope: list[str] = field(default_factory=list)
    periods_ignored: list[str] = field(default_factory=list)
    ignored_column_count: int = 0
    ignored_monetary_cell_count: int = 0
    ignored_value_sum: float = 0.0


def read_dotacao_sheet(
    file_content: bytes,
    filename: str,
    sheet_name: str,
) -> pd.DataFrame:
    """Lê uma aba com ``header=None`` a partir de uma cópia em memória."""

    extension = Path(filename).suffix.lower()
    engines = {".xlsx": "openpyxl", ".xls": "xlrd"}
    try:
        engine = engines[extension]
    except KeyError as error:
        raise ValueError(
            "Formato não suportado. Use um arquivo .xlsx ou .xls."
        ) from error

    return pd.read_excel(
        BytesIO(file_content),
        sheet_name=sheet_name,
        header=None,
        engine=engine,
    )


def recognize_dotacao_base(raw_dataframe: pd.DataFrame) -> DotacaoRecognition:
    """Reconhece a base pelas nove células estruturais confirmadas."""

    failures: list[str] = []

    if raw_dataframe.shape[0] < 3 or raw_dataframe.shape[1] < DIMENSION_COLUMN_COUNT:
        failures.append(
            "A planilha não possui as três linhas de cabeçalho e as colunas "
            "de dimensão esperadas até M."
        )

    for cell_name, (row_index, column_index, expected) in HEADER_SIGNATURE.items():
        observed = _safe_cell(raw_dataframe, row_index, column_index)
        if _normalize_label(observed) not in _signature_labels(cell_name, expected):
            observed_text = _clean_text(observed)
            failures.append(
                f"{cell_name}: esperado '{expected}', encontrado "
                f"'{observed_text if not pd.isna(observed_text) else 'vazio'}'."
            )

    return DotacaoRecognition(matched=not failures, validation_failures=failures)


def transform_dotacao_sheet(
    raw_dataframe: pd.DataFrame,
    filename: str,
    sheet_name: str,
) -> DotacaoTransformResult:
    """Converte uma aba reconhecida em uma linha por célula monetária."""

    recognition = recognize_dotacao_base(raw_dataframe)
    if not recognition.matched:
        return DotacaoTransformResult(
            recognized=False,
            normalized_data=_empty_output_dataframe(),
            raw_row_count=len(raw_dataframe),
            normalized_row_count=0,
            periods_found=[],
            items_found=[],
            warnings=[],
            validation_failures=recognition.validation_failures,
        )

    warnings: list[str] = []
    validation_failures: list[str] = []
    year = _extract_year(sheet_name)
    if year is None:
        validation_failures.append(
            "Não foi possível extrair o ano de exercício do nome da aba."
        )

    if raw_dataframe.shape[1] <= VALUE_START_COLUMN:
        validation_failures.append(
            "Nenhuma coluna monetária foi encontrada a partir da coluna N."
        )
        return DotacaoTransformResult(
            recognized=True,
            normalized_data=_empty_output_dataframe(),
            raw_row_count=len(raw_dataframe),
            normalized_row_count=0,
            periods_found=[],
            items_found=[],
            warnings=warnings,
            validation_failures=validation_failures,
        )

    data_rows = raw_dataframe.iloc[3:].copy(deep=True)
    data_rows.iloc[:, :HIERARCHY_COLUMN_COUNT] = data_rows.iloc[
        :, :HIERARCHY_COLUMN_COUNT
    ].ffill()

    value_column_indices = list(range(VALUE_START_COLUMN, raw_dataframe.shape[1]))
    period_headers = raw_dataframe.iloc[0, VALUE_START_COLUMN:].copy().ffill()

    periods_found: list[str] = []
    periods_in_scope: list[str] = []
    periods_ignored: list[str] = []
    items_found: list[str] = []
    records: list[dict[str, object]] = []
    ignored_column_count = 0
    ignored_monetary_cell_count = 0
    ignored_value_sum = 0.0

    for value_offset, column_index in enumerate(value_column_indices):
        period_source = _clean_period_label(period_headers.iloc[value_offset])
        item_source = _clean_text(raw_dataframe.iat[1, column_index])
        metric_source = _clean_text(raw_dataframe.iat[2, column_index])

        period_scope, period_order, period_type, month_number = classify_dotacao_period(
            period_source
        )
        if not pd.isna(period_source):
            _append_unique(periods_found, str(period_source))
        if pd.isna(period_source):
            _append_unique(
                validation_failures,
                f"{_excel_column_name(column_index)}1 não possui período.",
            )
        elif period_scope == "ignored":
            pass
        elif pd.isna(period_order):
            _append_unique(
                validation_failures,
                f"Período não reconhecido: '{period_source}'.",
            )
        else:
            _append_unique(periods_found, str(period_source))
            _append_unique(periods_in_scope, str(period_source))

        item_code, known_item = _normalize_item(item_source)
        if not pd.isna(item_source):
            _append_unique(items_found, str(item_source))
        if not known_item:
            _append_unique(
                warnings,
                "Item Informação não mapeado: "
                f"'{item_source if not pd.isna(item_source) else 'vazio'}' "
                f"→ '{item_code}'.",
            )

        normalized_metric = _normalize_label(metric_source)
        if period_scope != "ignored" and not (
            "movim liquido" in normalized_metric
            and "item informacao" in normalized_metric
        ):
            _append_unique(
                validation_failures,
                f"{_excel_column_name(column_index)}3 não contém a métrica "
                "'Movim. Líquido - R$ (Item Informação)'.",
            )

        if period_scope == "ignored":
            _append_unique(periods_ignored, str(period_source))
            ignored_column_count += 1
            ignored_monetary_cell_count += len(data_rows)
            ignored_values = pd.to_numeric(
                data_rows.iloc[:, column_index],
                errors="coerce",
            )
            ignored_value_sum += float(ignored_values.sum(skipna=True))
            continue

        for row_offset in range(len(data_rows)):
            source_row_index = row_offset + 3
            raw_value = data_rows.iat[row_offset, column_index]
            numeric_value = pd.to_numeric(raw_value, errors="coerce")
            if not pd.isna(raw_value) and pd.isna(numeric_value):
                _append_unique(
                    validation_failures,
                    "Valor não numérico em "
                    f"{_excel_column_name(column_index)}{source_row_index + 1}.",
                )

            records.append(
                {
                    "arquivo_origem": filename,
                    "aba_origem": sheet_name,
                    "linha_origem": source_row_index + 1,
                    "coluna_origem": _excel_column_name(column_index),
                    "ano_exercicio": year,
                    "periodo_rotulo_origem": period_source,
                    "periodo_ordem": period_order,
                    "periodo_tipo": period_type,
                    "mes_numero": month_number,
                    "iduso_codigo": _normalize_code(data_rows.iat[row_offset, 0]),
                    "iduso_descricao": _clean_text(data_rows.iat[row_offset, 1]),
                    "resultado_primario_codigo": _normalize_code(
                        data_rows.iat[row_offset, 2]
                    ),
                    "resultado_primario_descricao": _clean_text(
                        data_rows.iat[row_offset, 3]
                    ),
                    "acao_codigo": _normalize_code(data_rows.iat[row_offset, 4]),
                    "acao_descricao": _clean_text(data_rows.iat[row_offset, 5]),
                    "ptres_codigo": _normalize_code(data_rows.iat[row_offset, 6]),
                    "plano_orcamentario_codigo": _normalize_code(
                        data_rows.iat[row_offset, 7]
                    ),
                    "plano_orcamentario_descricao": _clean_text(
                        data_rows.iat[row_offset, 8]
                    ),
                    "grupo_despesa_codigo": _normalize_code(
                        data_rows.iat[row_offset, 9]
                    ),
                    "grupo_despesa_descricao": _clean_text(
                        data_rows.iat[row_offset, 10]
                    ),
                    "fonte_recursos_detalhada_codigo": _normalize_code(
                        data_rows.iat[row_offset, 11]
                    ),
                    "fonte_recursos_detalhada_descricao": _clean_text(
                        data_rows.iat[row_offset, 12]
                    ),
                    "item_informacao_origem": item_source,
                    "item_informacao_codigo": item_code,
                    "metrica_origem": metric_source,
                    "valor_movimento_liquido": numeric_value,
                }
            )

    normalized_data = _apply_output_dtypes(
        pd.DataFrame.from_records(records, columns=DOTACAO_OUTPUT_COLUMNS)
    )

    if normalized_data.duplicated(
        subset=["arquivo_origem", "aba_origem", "linha_origem", "coluna_origem"]
    ).any():
        validation_failures.append(
            "Foram produzidas coordenadas de origem duplicadas na normalização."
        )

    return DotacaoTransformResult(
        recognized=True,
        normalized_data=normalized_data,
        raw_row_count=len(raw_dataframe),
        normalized_row_count=len(normalized_data),
        periods_found=periods_found,
        items_found=items_found,
        warnings=warnings,
        validation_failures=validation_failures,
        periods_in_scope=periods_in_scope,
        periods_ignored=periods_ignored,
        ignored_column_count=ignored_column_count,
        ignored_monetary_cell_count=ignored_monetary_cell_count,
        ignored_value_sum=ignored_value_sum,
    )


def _empty_output_dataframe() -> pd.DataFrame:
    return _apply_output_dtypes(pd.DataFrame(columns=DOTACAO_OUTPUT_COLUMNS))


def _apply_output_dtypes(dataframe: pd.DataFrame) -> pd.DataFrame:
    typed = dataframe.copy(deep=True)
    for column in STRING_COLUMNS:
        typed[column] = pd.array(typed[column], dtype="string")
    for column in ["linha_origem", "ano_exercicio", "periodo_ordem", "mes_numero"]:
        typed[column] = pd.array(typed[column], dtype="Int64")
    typed["valor_movimento_liquido"] = pd.array(
        pd.to_numeric(typed["valor_movimento_liquido"], errors="coerce"),
        dtype="Float64",
    )
    return typed


def _normalize_item(value: object) -> tuple[str, bool]:
    normalized = _normalize_label(value)
    if normalized in KNOWN_ITEM_CODES:
        return KNOWN_ITEM_CODES[normalized], True

    if all(token in normalized for token in ["projeto", "loa", "fixacao", "despesa"]):
        return "projeto_inicial_loa_fixacao_despesa", True
    if "dotacao" in normalized and all(
        token in normalized for token in ["cancelada", "remanejada"]
    ):
        return "dotacao_cancelada_remanejada", True
    if "excesso" in normalized and "arrecadacao" in normalized:
        return "creditos_adicionais_excesso_arrecadacao", True
    if "superavit" in normalized and "financeiro" in normalized:
        return "creditos_adicionais_superavit_financeiro", True

    slug = normalized.replace(" ", "_") or "sem_rotulo"
    return f"item_nao_mapeado_{slug}", False


def classify_dotacao_period(value: object) -> tuple[str, object, object, object]:
    if pd.isna(value):
        return "invalid", pd.NA, pd.NA, pd.NA

    label = str(value).strip().upper()
    month_match = re.fullmatch(
        r"(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)/(19|20)\d{2}",
        label,
    )
    if month_match:
        month = MONTHS[month_match.group(1)]
        return "included", month, "mes_calendario", month

    ignored_match = re.fullmatch(r"0?(13|14)/(19|20)\d{2}", label)
    if ignored_match:
        return "ignored", pd.NA, pd.NA, pd.NA

    return "invalid", pd.NA, "periodo_desconhecido", pd.NA


def _normalize_code(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        numeric_value = float(value)
        if numeric_value.is_integer():
            return str(int(numeric_value))

    text = str(value).strip()
    numeric_with_decimal = re.fullmatch(r"([+-]?\d+)\.0+", text)
    if numeric_with_decimal:
        return numeric_with_decimal.group(1)
    return text or pd.NA


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
    text = str(value).strip()
    return text or pd.NA


def _normalize_label(value: object) -> str:
    cleaned = _clean_text(value)
    if pd.isna(cleaned):
        return ""
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", str(cleaned))
        if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", without_accents).lower().split())


def _signature_labels(cell_name: str, expected: str) -> set[str]:
    """Return the closed set of accepted normalized labels for a signature cell."""

    return {
        _normalize_label(label)
        for label in (expected, *HEADER_SIGNATURE_ALIASES.get(cell_name, ()))
    }


def _extract_year(sheet_name: str) -> int | None:
    match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", str(sheet_name))
    return int(match.group(1)) if match else None


def _safe_cell(dataframe: pd.DataFrame, row_index: int, column_index: int) -> object:
    if row_index >= dataframe.shape[0] or column_index >= dataframe.shape[1]:
        return pd.NA
    return dataframe.iat[row_index, column_index]


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
