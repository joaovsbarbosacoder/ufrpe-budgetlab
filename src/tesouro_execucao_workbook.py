"""Orquestração em memória de abas de Execução da Despesa."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.excel_importer import list_excel_sheets
from src.tesouro_execucao import EXECUCAO_OUTPUT_COLUMNS, read_execucao_sheet, recognize_execucao_base, transform_execucao_sheet
from src.tesouro_execucao_validation import DEFAULT_TOLERANCE, INCONSISTENCY_COLUMNS, validate_execucao_normalization


TRACEABILITY_COLUMNS = ["arquivo_origem", "aba_origem", "linha_origem", "coluna_origem"]


@dataclass
class ExecucaoWorkbookSheetResult:
    sheet_name: str
    recognized: bool
    integrity_approved: bool | None = None
    raw_data_row_count: int = 0
    monetary_cell_count: int = 0
    normalized_row_count: int = 0
    null_count: int = 0
    zero_count: int = 0
    negative_count: int = 0
    raw_sum: float = 0.0
    normalized_sum: float = 0.0
    difference: float = 0.0
    years_found: list[int] = field(default_factory=list)
    structural_failures: list[str] = field(default_factory=list)
    validation_failures: list[str] = field(default_factory=list)
    processing_error: str | None = None
    inconsistencies: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=INCONSISTENCY_COLUMNS))


@dataclass
class ExecucaoWorkbookResult:
    filename: str
    sheet_results: list[ExecucaoWorkbookSheetResult]
    consolidated_data: pd.DataFrame
    consolidated_inconsistencies: pd.DataFrame

    @property
    def recognized_sheets(self) -> list[str]:
        return [item.sheet_name for item in self.sheet_results if item.recognized]

    @property
    def integrity_approved(self) -> bool:
        recognized = [item for item in self.sheet_results if item.recognized]
        return bool(recognized) and all(item.integrity_approved and not item.processing_error for item in recognized) and self.consolidated_inconsistencies.empty


def process_execucao_workbook(file_content: bytes, filename: str, tolerance: float = DEFAULT_TOLERANCE) -> ExecucaoWorkbookResult:
    """Reconhece, normaliza e valida cada aba sem escrever no disco."""

    results: list[ExecucaoWorkbookSheetResult] = []
    frames: list[pd.DataFrame] = []
    inconsistencies: list[pd.DataFrame] = []
    for sheet_name in list_excel_sheets(file_content, filename):
        try:
            raw = read_execucao_sheet(file_content, filename, sheet_name)
            recognition = recognize_execucao_base(raw)
            if not recognition.matched:
                results.append(ExecucaoWorkbookSheetResult(sheet_name, False, structural_failures=recognition.validation_failures))
                continue
            treatment = transform_execucao_sheet(raw, filename, sheet_name)
            validation = validate_execucao_normalization(raw, treatment.normalized_data, sheet_name, tolerance)
        except Exception as error:
            results.append(ExecucaoWorkbookSheetResult(sheet_name, False, processing_error=f"{type(error).__name__}: {error}"))
            continue
        frames.append(treatment.normalized_data)
        if not validation.inconsistencies.empty:
            frame = validation.inconsistencies.copy(deep=True)
            frame.insert(0, "aba_origem", sheet_name)
            inconsistencies.append(frame)
        results.append(ExecucaoWorkbookSheetResult(sheet_name, True, validation.approved and not treatment.validation_failures, validation.raw_data_row_count, validation.monetary_cell_count, validation.normalized_row_count, validation.normalized_null_count, validation.normalized_zero_count, validation.normalized_negative_count, validation.raw_sum, validation.normalized_sum, validation.difference, treatment.years_found, validation_failures=treatment.validation_failures, inconsistencies=validation.inconsistencies.copy(deep=True)))
    consolidated = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=EXECUCAO_OUTPUT_COLUMNS)
    consolidated_inconsistencies = pd.concat(inconsistencies, ignore_index=True) if inconsistencies else pd.DataFrame(columns=["aba_origem", *INCONSISTENCY_COLUMNS])
    if consolidated.duplicated(subset=TRACEABILITY_COLUMNS, keep=False).any():
        consolidated_inconsistencies = pd.concat([consolidated_inconsistencies, pd.DataFrame([{"aba_origem": pd.NA, "tipo": "coordenadas_duplicadas_consolidado", "mensagem": "O consolidado possui coordenadas de origem duplicadas."}])], ignore_index=True)
    return ExecucaoWorkbookResult(filename, results, consolidated, consolidated_inconsistencies)
