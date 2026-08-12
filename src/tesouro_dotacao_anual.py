"""Reconhecimento e normalização de bases de Dotação Anual (BI CPOC - Por Ano).

Esta base é organizada por ano (não por mês) e usa células mescladas de
verdade para representar a hierarquia de dimensões, em vez de repetir o
valor em cada linha. Por isso o reconhecimento e a normalização partem de
``openpyxl`` diretamente (para enxergar ``merged_cells``), e não do
``pandas.read_excel`` usado pelo importador genérico.

A detecção da estrutura é dinâmica: em vez de assumir letras de coluna fixas,
ela localiza a coluna-âncora rotulada "Item Informação" na linha 1 (que
sempre precede o par de colunas de Plano Orçamentário, logo antes da matriz
monetária) e interpreta os blocos dimensionais à esquerda dela pelas
mesclagens de cabeçalho de 3 linhas. Isso permite reconhecer variantes que
apenas inserem ou removem um bloco dimensional (ex.: uma exportação sem
Grupo de Despesa), sem exigir uma nova assinatura fixa para cada variante.

Blocos dimensionais desconhecidos não são presumidos: um nome de bloco fora
de ``KNOWN_BLOCK_COLUMNS`` reprova o reconhecimento em vez de ser ignorado.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import unicodedata

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet


HEADER_ROW_COUNT = 3
FIRST_DATA_ROW = HEADER_ROW_COUNT + 1

ANCHOR_LABEL = "item informacao"
PLANO_ORCAMENTARIO_LABEL = "plano orcamentario"

# Nome do bloco (slug) -> (coluna_codigo_saida, coluna_descricao_saida | None).
# Um bloco cujo nome não esteja aqui reprova o reconhecimento: ver docstring.
KNOWN_BLOCK_COLUMNS: dict[str, tuple[str, str | None]] = {
    "iduso": ("iduso_codigo", "iduso_descricao"),
    "resultado_primario_lei": (
        "resultado_primario_codigo",
        "resultado_primario_descricao",
    ),
    "grupo_despesa": ("grupo_despesa_codigo", "grupo_despesa_descricao"),
    "acao_governo": ("acao_codigo", "acao_descricao"),
    "ptres": ("ptres_codigo", None),
    "fonte_recursos_detalhada": (
        "fonte_recursos_detalhada_codigo",
        "fonte_recursos_detalhada_descricao",
    ),
}

KNOWN_ANNUAL_ITEM_CODES = {
    "dotacao inicial": "dotacao_inicial",
    "dotacao suplementar": "dotacao_suplementar",
    "dotacao atualizada": "dotacao_atualizada",
    "dotacao cancelada e remanejada": "dotacao_cancelada_remanejada",
}

DOTACAO_ANUAL_OUTPUT_COLUMNS = [
    "arquivo_origem",
    "aba_origem",
    "linha_origem",
    "coluna_origem",
    "ano_lancamento",
    "iduso_codigo",
    "iduso_descricao",
    "resultado_primario_codigo",
    "resultado_primario_descricao",
    "grupo_despesa_codigo",
    "grupo_despesa_descricao",
    "acao_codigo",
    "acao_descricao",
    "ptres_codigo",
    "fonte_recursos_detalhada_codigo",
    "fonte_recursos_detalhada_descricao",
    "plano_orcamentario_codigo",
    "plano_orcamentario_descricao",
    "item_informacao_origem",
    "item_informacao_codigo",
    "valor_movimento_liquido",
]

STRING_COLUMNS = [
    "arquivo_origem",
    "aba_origem",
    "coluna_origem",
    "iduso_codigo",
    "iduso_descricao",
    "resultado_primario_codigo",
    "resultado_primario_descricao",
    "grupo_despesa_codigo",
    "grupo_despesa_descricao",
    "acao_codigo",
    "acao_descricao",
    "ptres_codigo",
    "fonte_recursos_detalhada_codigo",
    "fonte_recursos_detalhada_descricao",
    "plano_orcamentario_codigo",
    "plano_orcamentario_descricao",
    "item_informacao_origem",
    "item_informacao_codigo",
]


@dataclass(frozen=True)
class DimensionBlock:
    name: str
    code_column: int
    description_column: int | None


@dataclass(frozen=True)
class MonetaryColumn:
    column_index: int
    column_letter: str
    item_label: str
    item_code: str
    year: int | None


@dataclass
class DotacaoAnualStructure:
    """Estrutura dinâmica detectada: consumida também pela validação."""

    blocks: list[DimensionBlock]
    plano_orcamentario: DimensionBlock
    monetary_columns: list[MonetaryColumn]
    warnings: list[str]


@dataclass
class DotacaoAnualRecognition:
    """Resultado auditável do reconhecimento estrutural dinâmico."""

    matched: bool
    validation_failures: list[str]


@dataclass
class DotacaoAnualTransformResult:
    """Resultado da normalização de uma aba de Dotação Anual."""

    recognized: bool
    normalized_data: pd.DataFrame
    raw_row_count: int
    normalized_row_count: int
    anos_encontrados: list[int]
    itens_encontrados: list[str]
    warnings: list[str]
    validation_failures: list[str]


def read_dotacao_anual_sheet(
    file_content: bytes,
    filename: str,
    sheet_name: str,
) -> Worksheet:
    """Abre a aba via ``openpyxl`` para preservar o mapa de células mescladas."""

    extension = Path(filename).suffix.lower()
    if extension != ".xlsx":
        raise ValueError(
            "A Dotação Anual requer um arquivo .xlsx: o reconhecimento depende "
            "de células mescladas, não suportadas na leitura de .xls."
        )

    workbook = load_workbook(BytesIO(file_content), data_only=True)
    try:
        return workbook[sheet_name]
    except KeyError as error:
        raise ValueError(f"Aba não encontrada: {sheet_name!r}.") from error


def recognize_dotacao_anual_base(worksheet: Worksheet) -> DotacaoAnualRecognition:
    """Reconhece a base pela âncora 'Item Informação' e pelos blocos que a precedem."""

    if worksheet.max_row < FIRST_DATA_ROW or worksheet.max_column < 1:
        return DotacaoAnualRecognition(
            matched=False,
            validation_failures=[
                "A planilha não possui as três linhas de cabeçalho esperadas."
            ],
        )

    structure, failures = detect_dotacao_anual_structure(worksheet)
    return DotacaoAnualRecognition(matched=structure is not None, validation_failures=failures)


def transform_dotacao_anual_sheet(
    worksheet: Worksheet,
    filename: str,
    sheet_name: str,
) -> DotacaoAnualTransformResult:
    """Converte uma aba reconhecida em uma linha por célula monetária."""

    raw_row_count = max(worksheet.max_row - HEADER_ROW_COUNT, 0)
    structure, failures = detect_dotacao_anual_structure(worksheet)
    if structure is None:
        return DotacaoAnualTransformResult(
            recognized=False,
            normalized_data=_empty_output_dataframe(),
            raw_row_count=raw_row_count,
            normalized_row_count=0,
            anos_encontrados=[],
            itens_encontrados=[],
            warnings=[],
            validation_failures=failures,
        )

    resolver = MergeResolver(worksheet)
    warnings = list(structure.warnings)
    validation_failures: list[str] = []
    records: list[dict[str, object]] = []

    anos_encontrados = sorted(
        {column.year for column in structure.monetary_columns if column.year is not None}
    )
    itens_encontrados: list[str] = []
    for column in structure.monetary_columns:
        if column.item_label not in itens_encontrados:
            itens_encontrados.append(column.item_label)

    blocks_by_name = {block.name: block for block in structure.blocks}

    for row in range(FIRST_DATA_ROW, worksheet.max_row + 1):
        row_dimensions: dict[str, object] = {}
        row_has_value = False

        for block_name, (code_field, description_field) in KNOWN_BLOCK_COLUMNS.items():
            block = blocks_by_name.get(block_name)
            if block is None:
                row_dimensions[code_field] = pd.NA
                if description_field:
                    row_dimensions[description_field] = pd.NA
                continue

            code_value = resolver.value(row, block.code_column)
            if code_value is not None:
                row_has_value = True
            row_dimensions[code_field] = _as_code(code_value)

            if description_field:
                description_value = resolver.value(row, block.description_column)
                if description_value is not None:
                    row_has_value = True
                row_dimensions[description_field] = _as_text(description_value)

        plano = structure.plano_orcamentario
        plano_codigo = resolver.value(row, plano.code_column)
        plano_descricao = resolver.value(row, plano.description_column)
        if plano_codigo is not None or plano_descricao is not None:
            row_has_value = True
        row_dimensions["plano_orcamentario_codigo"] = _as_code(plano_codigo)
        row_dimensions["plano_orcamentario_descricao"] = _as_text(plano_descricao)

        if not row_has_value:
            continue

        for monetary_column in structure.monetary_columns:
            raw_value = worksheet.cell(
                row=row, column=monetary_column.column_index
            ).value
            numeric_value = _as_number(raw_value)
            if raw_value is not None and numeric_value is None:
                validation_failures.append(
                    "Valor não numérico em "
                    f"{monetary_column.column_letter}{row}."
                )

            record = dict(row_dimensions)
            record.update(
                {
                    "arquivo_origem": filename,
                    "aba_origem": sheet_name,
                    "linha_origem": row,
                    "coluna_origem": monetary_column.column_letter,
                    "ano_lancamento": monetary_column.year,
                    "item_informacao_origem": monetary_column.item_label,
                    "item_informacao_codigo": monetary_column.item_code,
                    "valor_movimento_liquido": numeric_value,
                }
            )
            records.append(record)

    normalized_data = _apply_output_dtypes(
        pd.DataFrame.from_records(records, columns=DOTACAO_ANUAL_OUTPUT_COLUMNS)
    )
    if normalized_data.duplicated(
        subset=["arquivo_origem", "aba_origem", "linha_origem", "coluna_origem"]
    ).any():
        validation_failures.append(
            "Foram produzidas coordenadas de origem duplicadas na normalização."
        )

    return DotacaoAnualTransformResult(
        recognized=True,
        normalized_data=normalized_data,
        raw_row_count=raw_row_count,
        normalized_row_count=len(normalized_data),
        anos_encontrados=anos_encontrados,
        itens_encontrados=itens_encontrados,
        warnings=warnings,
        validation_failures=validation_failures,
    )


# =============================================================================
# DETECÇÃO DINÂMICA DA ESTRUTURA
# =============================================================================


class MergeResolver:
    """Devolve o valor efetivo de uma célula, resolvendo mesclagens reais."""

    def __init__(self, worksheet: Worksheet):
        self._anchor: dict[tuple[int, int], tuple[int, int]] = {}
        for merged_range in worksheet.merged_cells.ranges:
            top_left = (merged_range.min_row, merged_range.min_col)
            for row in range(merged_range.min_row, merged_range.max_row + 1):
                for column in range(merged_range.min_col, merged_range.max_col + 1):
                    self._anchor[(row, column)] = top_left
        self._worksheet = worksheet

    def value(self, row: int, column: int) -> object:
        anchor_row, anchor_column = self._anchor.get((row, column), (row, column))
        return self._worksheet.cell(row=anchor_row, column=anchor_column).value


def detect_dotacao_anual_structure(
    worksheet: Worksheet,
) -> tuple[DotacaoAnualStructure | None, list[str]]:
    """Detecta dinamicamente blocos dimensionais e matriz monetária.

    Compartilhado entre o reconhecimento/normalização e a validação
    independente, para que as duas etapas nunca discordem sobre quais
    colunas são monetárias.
    """

    failures: list[str] = []

    anchor_column = _locate_anchor_column(worksheet)
    if anchor_column is None:
        failures.append(
            "Não encontrei a coluna com o rótulo 'Item Informação' na linha 1 — "
            "a base não corresponde à assinatura estrutural da Dotação Anual."
        )
        return None, failures

    blocks, block_failures = _detect_dimension_blocks(worksheet, anchor_column)
    failures.extend(block_failures)
    if not blocks and not block_failures:
        failures.append("Nenhum bloco dimensional foi encontrado antes da matriz monetária.")

    plano, plano_failures = _detect_plano_orcamentario(worksheet, anchor_column)
    failures.extend(plano_failures)
    if plano is None or failures:
        return None, failures

    monetary_columns, warnings = _detect_monetary_columns(
        worksheet, plano.description_column + 1
    )
    if not monetary_columns:
        failures.append(
            "Nenhuma coluna monetária foi encontrada após o bloco de Plano "
            "Orçamentário."
        )
        return None, failures

    return DotacaoAnualStructure(blocks, plano, monetary_columns, warnings), failures


def _locate_anchor_column(worksheet: Worksheet) -> int | None:
    for column in range(1, worksheet.max_column + 1):
        value = worksheet.cell(row=1, column=column).value
        if value is not None and _normalize_label(value) == ANCHOR_LABEL:
            return column
    return None


def _full_header_merge(worksheet: Worksheet, column: int) -> tuple[int, int] | None:
    """(largura, coluna_final) da mesclagem de 3 linhas iniciada em `column`."""

    for merged_range in worksheet.merged_cells.ranges:
        if (
            merged_range.min_row == 1
            and merged_range.max_row == HEADER_ROW_COUNT
            and merged_range.min_col == column
        ):
            return merged_range.max_col - merged_range.min_col + 1, merged_range.max_col
    return None


def _detect_dimension_blocks(
    worksheet: Worksheet, anchor_column: int
) -> tuple[list[DimensionBlock], list[str]]:
    blocks: list[DimensionBlock] = []
    failures: list[str] = []
    column = 1
    while column < anchor_column:
        label = worksheet.cell(row=1, column=column).value
        merge = _full_header_merge(worksheet, column)
        if merge is None:
            failures.append(
                f"{get_column_letter(column)}1: bloco dimensional sem mesclagem de "
                "cabeçalho de 3 linhas reconhecível."
            )
            column += 1
            continue

        width, end_column = merge
        name = _slug(label)
        if name not in KNOWN_BLOCK_COLUMNS:
            failures.append(
                f"{get_column_letter(column)}1: bloco dimensional desconhecido "
                f"{label!r} — a base não corresponde à assinatura conhecida da "
                "Dotação Anual."
            )
            column = end_column + 1
            continue

        _, description_field = KNOWN_BLOCK_COLUMNS[name]
        expected_width = 2 if description_field else 1
        if width != expected_width:
            failures.append(
                f"{get_column_letter(column)}1: bloco '{label}' tem largura "
                f"{width}, esperado {expected_width}."
            )

        blocks.append(
            DimensionBlock(
                name=name,
                code_column=column,
                description_column=column + 1 if description_field else None,
            )
        )
        column = end_column + 1

    return blocks, failures


def _detect_plano_orcamentario(
    worksheet: Worksheet, anchor_column: int
) -> tuple[DimensionBlock | None, list[str]]:
    failures: list[str] = []
    plano_merge = next(
        (
            merged_range
            for merged_range in worksheet.merged_cells.ranges
            if merged_range.min_row == HEADER_ROW_COUNT
            and merged_range.max_row == HEADER_ROW_COUNT
            and merged_range.min_col == anchor_column
        ),
        None,
    )
    if plano_merge is None:
        failures.append(
            f"{get_column_letter(anchor_column)}{HEADER_ROW_COUNT}: não localizei "
            "o bloco de Plano Orçamentário imediatamente antes da matriz "
            "monetária."
        )
        return None, failures

    label = worksheet.cell(row=HEADER_ROW_COUNT, column=anchor_column).value
    if _normalize_label(label) != PLANO_ORCAMENTARIO_LABEL:
        failures.append(
            f"{get_column_letter(anchor_column)}{HEADER_ROW_COUNT}: esperado "
            f"'Plano Orçamentário', encontrado {label!r}."
        )

    end_column = plano_merge.max_col
    if end_column != anchor_column + 1:
        failures.append(
            "O bloco de Plano Orçamentário deve ter exatamente duas colunas "
            "(código e descrição)."
        )
        return None, failures

    return DimensionBlock("plano_orcamentario", anchor_column, anchor_column + 1), failures


def _detect_monetary_columns(
    worksheet: Worksheet, start_column: int
) -> tuple[list[MonetaryColumn], list[str]]:
    columns: list[MonetaryColumn] = []
    warnings: list[str] = []

    for column in range(start_column, worksheet.max_column + 1):
        item_label = worksheet.cell(row=1, column=column).value
        year_value = worksheet.cell(row=2, column=column).value
        metric_label = worksheet.cell(row=HEADER_ROW_COUNT, column=column).value

        if item_label is None:
            warnings.append(
                f"{get_column_letter(column)}1: coluna monetária sem rótulo de "
                "item — ignorada."
            )
            continue

        item_code = KNOWN_ANNUAL_ITEM_CODES.get(_normalize_label(item_label))
        if item_code is None:
            slug = _slug(item_label) or "sem_rotulo"
            item_code = f"item_nao_mapeado_{slug}"
            warnings.append(
                f"{get_column_letter(column)}1: item monetário não mapeado: "
                f"{item_label!r} → '{item_code}'."
            )

        year = _parse_year(year_value)
        if year is None:
            warnings.append(
                f"{get_column_letter(column)}2: ano de lançamento não "
                f"identificado ({year_value!r})."
            )

        if metric_label is not None and "movim" not in _normalize_label(metric_label):
            warnings.append(
                f"{get_column_letter(column)}{HEADER_ROW_COUNT}: métrica "
                f"inesperada {metric_label!r} nesta coluna."
            )

        columns.append(
            MonetaryColumn(
                column_index=column,
                column_letter=get_column_letter(column),
                item_label=str(item_label),
                item_code=item_code,
                year=year,
            )
        )

    return columns, warnings


# =============================================================================
# UTILITÁRIOS
# =============================================================================


def _apply_output_dtypes(dataframe: pd.DataFrame) -> pd.DataFrame:
    typed = dataframe.copy(deep=True)
    for column in STRING_COLUMNS:
        typed[column] = pd.array(typed[column], dtype="string")
    for column in ["linha_origem", "ano_lancamento"]:
        typed[column] = pd.array(typed[column], dtype="Int64")
    typed["valor_movimento_liquido"] = pd.array(
        pd.to_numeric(typed["valor_movimento_liquido"], errors="coerce"),
        dtype="Float64",
    )
    return typed


def _empty_output_dataframe() -> pd.DataFrame:
    return _apply_output_dtypes(pd.DataFrame(columns=DOTACAO_ANUAL_OUTPUT_COLUMNS))


def _as_code(value: object) -> object:
    if value is None:
        return pd.NA
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    text = str(value).strip()
    return text or pd.NA


def _as_text(value: object) -> object:
    if value is None:
        return pd.NA
    text = str(value).strip()
    return text or pd.NA


def _as_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _parse_year(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    return int(text) if text.isdigit() else None


def _normalize_label(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    without_accents = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    return " ".join(without_accents.lower().split())


def _slug(value: object) -> str:
    return "_".join(_normalize_label(value).split())
