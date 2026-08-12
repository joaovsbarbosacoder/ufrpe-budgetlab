"""Leitura e diagnóstico estrutural de arquivos Excel."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re

import pandas as pd


EXCEL_ENGINES = {
    ".xlsx": "openpyxl",
    ".xls": "xlrd",
}


@dataclass(frozen=True)
class ExcelDiagnostics:
    """Resumo estrutural de uma aba, sem interpretação orçamentária."""

    unnamed_columns: list[str]
    fully_empty_columns: list[str]
    empty_cells_by_column: dict[str, int]
    possible_duplicate_columns: list[str]
    data_types_by_column: dict[str, str]


def _excel_engine(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    try:
        return EXCEL_ENGINES[extension]
    except KeyError as error:
        raise ValueError("Formato não suportado. Use um arquivo .xlsx ou .xls.") from error


def list_excel_sheets(file_content: bytes, filename: str) -> list[str]:
    """Retorna os nomes das abas sem alterar o conteúdo recebido."""

    with pd.ExcelFile(
        BytesIO(file_content),
        engine=_excel_engine(filename),
    ) as workbook:
        return list(workbook.sheet_names)


def read_excel_sheet(
    file_content: bytes,
    filename: str,
    sheet_name: str,
) -> pd.DataFrame:
    """Lê uma aba específica a partir de uma cópia em memória do arquivo."""

    return pd.read_excel(
        BytesIO(file_content),
        sheet_name=sheet_name,
        engine=_excel_engine(filename),
    )


def diagnose_dataframe(dataframe: pd.DataFrame) -> ExcelDiagnostics:
    """Calcula indicadores de qualidade estrutural de uma tabela."""

    column_names = [str(column) for column in dataframe.columns]
    empty_counts = {
        column_name: int(dataframe.iloc[:, index].isna().sum())
        for index, column_name in enumerate(column_names)
    }
    fully_empty_columns = [
        column_name
        for index, column_name in enumerate(column_names)
        if dataframe.iloc[:, index].isna().all()
    ]
    data_types = {
        column_name: str(dataframe.iloc[:, index].dtype)
        for index, column_name in enumerate(column_names)
    }

    return ExcelDiagnostics(
        unnamed_columns=[
            column_name
            for column_name in column_names
            if column_name.startswith("Unnamed:")
        ],
        fully_empty_columns=fully_empty_columns,
        empty_cells_by_column=empty_counts,
        possible_duplicate_columns=_find_possible_duplicate_columns(column_names),
        data_types_by_column=data_types,
    )


def _find_possible_duplicate_columns(column_names: list[str]) -> list[str]:
    """Localiza duplicatas exatas e sufixos criados pelo leitor do Excel."""

    counts = Counter(column_names)
    duplicate_families = {
        name for name, count in counts.items() if count > 1
    }

    for name in column_names:
        match = re.fullmatch(r"(.+)\.\d+", name)
        if match and match.group(1) in counts:
            duplicate_families.add(match.group(1))

    possible_duplicates = []
    for name in column_names:
        match = re.fullmatch(r"(.+)\.\d+", name)
        base_name = match.group(1) if match else name
        if base_name in duplicate_families and name not in possible_duplicates:
            possible_duplicates.append(name)

    return possible_duplicates
