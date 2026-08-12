"""Estado analítico em memória para bases validadas de Execução."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

import pandas as pd

from src.tesouro_execucao import EXECUCAO_OUTPUT_COLUMNS
from src.tesouro_execucao_validation import DEFAULT_TOLERANCE
from src.tesouro_execucao_workbook import ExecucaoWorkbookResult


EXECUCAO_ANALYSIS_SESSION_KEY = "execucao_analysis_dataset"
TRACEABILITY_COLUMNS = ["arquivo_origem", "aba_origem", "linha_origem", "coluna_origem"]


@dataclass
class ValidatedExecucaoDataset:
    filename: str
    source_sha256: str
    sheets: list[str]
    normalized_data: pd.DataFrame
    validation_status: str

    @property
    def row_count(self) -> int:
        return len(self.normalized_data)


def prepare_validated_execucao_dataset(
    workbook_result: ExecucaoWorkbookResult,
    file_content: bytes,
    tolerance: float = DEFAULT_TOLERANCE,
) -> ValidatedExecucaoDataset:
    """Disponibiliza somente uma Execução integralmente validada."""

    if not workbook_result.integrity_approved:
        raise ValueError("Somente bases de Execução com normalização aprovada podem ser analisadas.")
    normalized = workbook_result.consolidated_data.copy(deep=True)
    missing = sorted(set(EXECUCAO_OUTPUT_COLUMNS).difference(normalized.columns))
    if missing:
        raise ValueError("A base normalizada não contém as colunas necessárias: " + ", ".join(missing))
    if normalized.empty:
        raise ValueError("A base normalizada aprovada não possui registros.")
    if normalized.duplicated(subset=TRACEABILITY_COLUMNS).any():
        raise ValueError("A base analítica possui coordenadas de origem duplicadas.")
    expected_rows = sum(item.normalized_row_count for item in workbook_result.sheet_results if item.recognized)
    if len(normalized) != expected_rows:
        raise ValueError("A quantidade de registros analíticos difere da validação multiaba.")
    expected_sum = sum(item.normalized_sum for item in workbook_result.sheet_results if item.recognized)
    actual_sum = float(normalized["valor_movimento_liquido"].sum(skipna=True))
    if abs(actual_sum - expected_sum) > tolerance:
        raise ValueError("A soma da base analítica difere da validação multiaba.")
    return ValidatedExecucaoDataset(workbook_result.filename, sha256(file_content).hexdigest(), list(workbook_result.recognized_sheets), normalized, "Aprovada")
