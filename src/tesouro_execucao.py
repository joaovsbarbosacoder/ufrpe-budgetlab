"""Reconhecimento e normalização de Execução da Despesa do Tesouro Gerencial."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import numbers
from pathlib import Path
import re
import unicodedata

import pandas as pd


HEADER_ROW_COUNT = 2
DIMENSION_COLUMN_COUNT = 35  # A:AI
VALUE_COLUMN_INDICES = (35, 36, 37)  # AJ:AL, em índices iniciados em zero.

EXECUCAO_OUTPUT_COLUMNS = [
    "arquivo_origem", "aba_origem", "linha_origem", "coluna_origem",
    "iduso_codigo", "iduso_descricao",
    "resultado_primario_codigo", "resultado_primario_descricao",
    "categoria_economica_codigo", "categoria_economica_descricao",
    "acao_codigo", "acao_descricao",
    "elemento_despesa_codigo", "elemento_despesa_descricao",
    "fonte_recursos_detalhada_codigo", "fonte_recursos_detalhada_descricao",
    "grupo_despesa_codigo", "grupo_despesa_descricao",
    "natureza_despesa_codigo", "natureza_despesa_descricao",
    "natureza_despesa_detalhada_codigo", "natureza_despesa_detalhada_descricao",
    "subitem_codigo", "subitem_descricao", "pi_codigo", "pi_descricao",
    "plano_orcamentario_nivel1_origem", "plano_orcamentario_codigo",
    "plano_orcamentario_descricao", "ptres_codigo",
    "ug_executora_codigo", "ug_executora_descricao",
    "ug_responsavel_codigo", "ug_responsavel_descricao",
    "ugr_gestao_codigo", "ugr_gestao_descricao",
    "ne_ccor_codigo", "ne_ccor_favorecido_nome", "ano_lancamento",
    "metrica_execucao_origem", "metrica_execucao_codigo",
    "valor_movimento_liquido",
]

CODE_COLUMNS = [
    "iduso_codigo", "resultado_primario_codigo", "categoria_economica_codigo",
    "acao_codigo", "elemento_despesa_codigo",
    "fonte_recursos_detalhada_codigo", "grupo_despesa_codigo",
    "natureza_despesa_codigo", "natureza_despesa_detalhada_codigo",
    "subitem_codigo", "pi_codigo", "plano_orcamentario_nivel1_origem",
    "plano_orcamentario_codigo", "ptres_codigo", "ug_executora_codigo",
    "ug_responsavel_codigo", "ugr_gestao_codigo", "ne_ccor_codigo",
    "metrica_execucao_codigo",
]

STRING_COLUMNS = [
    "arquivo_origem", "aba_origem", "coluna_origem", *CODE_COLUMNS,
    "iduso_descricao", "resultado_primario_descricao",
    "categoria_economica_descricao", "acao_descricao",
    "elemento_despesa_descricao", "fonte_recursos_detalhada_descricao",
    "grupo_despesa_descricao", "natureza_despesa_descricao",
    "natureza_despesa_detalhada_descricao", "subitem_descricao", "pi_descricao",
    "plano_orcamentario_descricao", "ug_executora_descricao",
    "ug_responsavel_descricao", "ugr_gestao_descricao",
    "ne_ccor_favorecido_nome", "metrica_execucao_origem",
]

# A assinatura é propositalmente específica. Alterações futuras, como a descrição
# do empenho, precisam ser analisadas antes de passarem a ser aceitas.
HEADER_SIGNATURE = {
    "A1": (0, 0, "Iduso"),
    "C1": (0, 2, "Resultado Primário Lei"),
    "E1": (0, 4, "Categoria Econômica Despesa"),
    "G1": (0, 6, "Ação Governo"),
    "I1": (0, 8, "Elemento Despesa"),
    "K1": (0, 10, "Fonte Recursos Detalhada"),
    "M1": (0, 12, "Grupo Despesa"),
    "O1": (0, 14, "Natureza Despesa"),
    "Q1": (0, 16, "Natureza Despesa Detalhada"),
    "S1": (0, 18, "Subitem"),
    "U1": (0, 20, "PI"),
    "W1": (0, 22, "Plano Orçamentário"),
    "Z1": (0, 25, "PTRES"),
    "AA1": (0, 26, "UG Executora"),
    "AC1": (0, 28, "UG Responsável"),
    "AE1": (0, 30, "UGR - Gestão"),
    "AG1": (0, 32, "NE CCor"),
    "AH1": (0, 33, "NE CCor - Favorecido"),
    "AI1": (0, 34, "Item Informação"),
    "AI2": (1, 34, "Ano Lançamento"),
    "AJ1": (0, 35, "DESPESAS EMPENHADAS (CONTROLE EMPENHO)"),
    "AK1": (0, 36, "DESPESAS LIQUIDADAS (CONTROLE EMPENHO)"),
    "AL1": (0, 37, "DESPESAS PAGAS (CONTROLE EMPENHO)"),
    "AJ2": (1, 35, "Movim. Líquido - R$ (Item Informação)"),
    "AK2": (1, 36, "Movim. Líquido - R$ (Item Informação)"),
    "AL2": (1, 37, "Movim. Líquido - R$ (Item Informação)"),
}

METRICS = {
    35: "despesa_empenhada",
    36: "despesa_liquidada",
    37: "despesa_paga",
}

DIMENSION_MAPPINGS = (
    (0, "iduso_codigo", True), (1, "iduso_descricao", False),
    (2, "resultado_primario_codigo", True), (3, "resultado_primario_descricao", False),
    (4, "categoria_economica_codigo", True), (5, "categoria_economica_descricao", False),
    (6, "acao_codigo", True), (7, "acao_descricao", False),
    (8, "elemento_despesa_codigo", True), (9, "elemento_despesa_descricao", False),
    (10, "fonte_recursos_detalhada_codigo", True), (11, "fonte_recursos_detalhada_descricao", False),
    (12, "grupo_despesa_codigo", True), (13, "grupo_despesa_descricao", False),
    (14, "natureza_despesa_codigo", True), (15, "natureza_despesa_descricao", False),
    (16, "natureza_despesa_detalhada_codigo", True), (17, "natureza_despesa_detalhada_descricao", False),
    (18, "subitem_codigo", True), (19, "subitem_descricao", False),
    (20, "pi_codigo", True), (21, "pi_descricao", False),
    # A semântica do primeiro componente W ainda não foi confirmada.
    (22, "plano_orcamentario_nivel1_origem", True),
    (23, "plano_orcamentario_codigo", True),
    (24, "plano_orcamentario_descricao", False),
    (25, "ptres_codigo", True),
    (26, "ug_executora_codigo", True), (27, "ug_executora_descricao", False),
    (28, "ug_responsavel_codigo", True), (29, "ug_responsavel_descricao", False),
    (30, "ugr_gestao_codigo", True), (31, "ugr_gestao_descricao", False),
    (32, "ne_ccor_codigo", True), (33, "ne_ccor_favorecido_nome", False),
)


@dataclass(frozen=True)
class ExecucaoRecognition:
    matched: bool
    validation_failures: list[str]


@dataclass
class ExecucaoTransformResult:
    recognized: bool
    normalized_data: pd.DataFrame
    raw_row_count: int
    normalized_row_count: int
    years_found: list[int] = field(default_factory=list)
    validation_failures: list[str] = field(default_factory=list)


def read_execucao_sheet(file_content: bytes, filename: str, sheet_name: str) -> pd.DataFrame:
    """Lê a aba bruta exclusivamente a partir dos bytes recebidos."""

    extension = Path(filename).suffix.lower()
    engines = {".xlsx": "openpyxl", ".xls": "xlrd"}
    try:
        engine = engines[extension]
    except KeyError as error:
        raise ValueError("Formato não suportado. Use um arquivo .xlsx ou .xls.") from error
    return pd.read_excel(BytesIO(file_content), sheet_name=sheet_name, header=None, engine=engine)


def recognize_execucao_base(raw_dataframe: pd.DataFrame) -> ExecucaoRecognition:
    """Reconhece apenas a assinatura confirmada da exportação de Execução."""

    failures: list[str] = []
    if raw_dataframe.shape[0] < 3 or raw_dataframe.shape[1] != 38:
        failures.append("A planilha deve possuir duas linhas de cabeçalho, dados e exatamente as colunas A:AL.")
    for cell_name, (row_index, column_index, expected) in HEADER_SIGNATURE.items():
        observed = _safe_cell(raw_dataframe, row_index, column_index)
        if _normalize_label(observed) != _normalize_label(expected):
            failures.append(f"{cell_name}: esperado '{expected}', encontrado '{_display(observed)}'.")
    return ExecucaoRecognition(matched=not failures, validation_failures=failures)


def transform_execucao_sheet(raw_dataframe: pd.DataFrame, filename: str, sheet_name: str) -> ExecucaoTransformResult:
    """Produz uma linha por célula AJ, AK ou AL, preservando valores nulos."""

    recognition = recognize_execucao_base(raw_dataframe)
    if not recognition.matched:
        return ExecucaoTransformResult(False, _empty_output_dataframe(), len(raw_dataframe), 0, validation_failures=recognition.validation_failures)

    failures: list[str] = []
    records: list[dict[str, object]] = []
    years_found: list[int] = []
    for raw_row_index in range(HEADER_ROW_COUNT, len(raw_dataframe)):
        source_row = raw_row_index + 1
        dimensions: dict[str, object] = {}
        for column_index, field_name, is_code in DIMENSION_MAPPINGS:
            value = raw_dataframe.iat[raw_row_index, column_index]
            dimensions[field_name] = _normalize_code(value) if is_code else _clean_text(value)
        year = _normalize_year(raw_dataframe.iat[raw_row_index, 34])
        if pd.isna(year) and not pd.isna(raw_dataframe.iat[raw_row_index, 34]):
            _append_unique(failures, f"AI{source_row} não contém um ano de lançamento inteiro válido.")
        elif not pd.isna(year) and int(year) not in years_found:
            years_found.append(int(year))

        for column_index in VALUE_COLUMN_INDICES:
            raw_value = raw_dataframe.iat[raw_row_index, column_index]
            numeric_value = pd.to_numeric(raw_value, errors="coerce")
            if not pd.isna(raw_value) and pd.isna(numeric_value):
                _append_unique(failures, f"Valor não numérico em {_excel_column_name(column_index)}{source_row}.")
            records.append({
                "arquivo_origem": filename, "aba_origem": sheet_name,
                "linha_origem": source_row, "coluna_origem": _excel_column_name(column_index),
                **dimensions, "ano_lancamento": year,
                "metrica_execucao_origem": _clean_text(raw_dataframe.iat[0, column_index]),
                "metrica_execucao_codigo": METRICS[column_index],
                "valor_movimento_liquido": numeric_value,
            })

    normalized = _apply_output_dtypes(pd.DataFrame.from_records(records, columns=EXECUCAO_OUTPUT_COLUMNS))
    if normalized.duplicated(subset=["arquivo_origem", "aba_origem", "linha_origem", "coluna_origem"]).any():
        failures.append("Foram produzidas coordenadas de origem duplicadas na normalização.")
    return ExecucaoTransformResult(True, normalized, len(raw_dataframe), len(normalized), years_found, failures)


def _empty_output_dataframe() -> pd.DataFrame:
    return _apply_output_dtypes(pd.DataFrame(columns=EXECUCAO_OUTPUT_COLUMNS))


def _apply_output_dtypes(dataframe: pd.DataFrame) -> pd.DataFrame:
    typed = dataframe.copy(deep=True)
    for column in STRING_COLUMNS:
        typed[column] = pd.array(typed[column], dtype="string")
    typed["linha_origem"] = pd.array(typed["linha_origem"], dtype="Int64")
    typed["ano_lancamento"] = pd.array(typed["ano_lancamento"], dtype="Int64")
    typed["valor_movimento_liquido"] = pd.array(pd.to_numeric(typed["valor_movimento_liquido"], errors="coerce"), dtype="Float64")
    return typed


def _normalize_code(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        if float(value).is_integer():
            return str(int(value))
    text = str(value).strip()
    match = re.fullmatch(r"([+-]?\d+)\.0+", text)
    return match.group(1) if match else (text or pd.NA)


def _normalize_year(value: object) -> object:
    code = _normalize_code(value)
    if pd.isna(code) or not re.fullmatch(r"\d{4}", str(code)):
        return pd.NA
    return int(str(code))


def _clean_text(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    text = str(value).strip()
    return text or pd.NA


def _safe_cell(dataframe: pd.DataFrame, row_index: int, column_index: int) -> object:
    if row_index >= dataframe.shape[0] or column_index >= dataframe.shape[1]:
        return pd.NA
    return dataframe.iat[row_index, column_index]


def _normalize_label(value: object) -> str:
    if pd.isna(value):
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value).strip())
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).casefold().split())


def _display(value: object) -> str:
    return "vazio" if pd.isna(value) else str(value).strip()


def _excel_column_name(zero_based_index: int) -> str:
    number = zero_based_index + 1
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
