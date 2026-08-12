"""Testes da reimportação pela interface (aba Execução Orçamentária, seção
"Reimportar base").

Constrói variantes do arquivo de referência (um exercício fechado alterado,
um exercício removido, o exercício corrente avançando) para exercitar os
três caminhos do gate de confirmação. Como a reimportação grava de verdade
em `data/manifestos/` e `data/raw/`, cada teste faz backup do estado atual
antes de rodar e restaura tudo em `tearDown` — mesmo que a asserção falhe.
"""

from __future__ import annotations

import io
import shutil
import unittest
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.importacao_execucao import Manifesto

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIRETORIO_RAW = PROJECT_ROOT / "data/raw"
DIRETORIO_MANIFESTOS = PROJECT_ROOT / "data/manifestos"
MANIFESTO_ATUAL = DIRETORIO_MANIFESTOS / "execucao_anual_atual.json"

COL_ANO = 35        # posição 0-indexada da coluna "ano" no arquivo bruto
COL_EMPENHADA = 36  # posição 0-indexada da coluna "empenhada"

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _build_variant(
    caminho_base: Path,
    *,
    modificar_ano: int | None = None,
    delta: float | None = None,
    remover_ano: int | None = None,
) -> bytes:
    """Cópia do arquivo de referência com uma alteração pontual e controlada."""

    header = pd.read_excel(caminho_base, header=None, nrows=2, dtype=str)
    data = pd.read_excel(caminho_base, header=None, skiprows=2, dtype=str)

    if remover_ano is not None:
        data = data[data[COL_ANO] != str(remover_ano)].reset_index(drop=True)

    if modificar_ano is not None:
        indice = data.index[data[COL_ANO] == str(modificar_ano)][0]
        atual = float(data.at[indice, COL_EMPENHADA] or 0)
        data.at[indice, COL_EMPENHADA] = str(atual + delta)

    completo = pd.concat([header, data], ignore_index=True)
    buffer = io.BytesIO()
    completo.to_excel(buffer, header=False, index=False, engine="openpyxl")
    return buffer.getvalue()


@unittest.skipUnless(MANIFESTO_ATUAL.exists(), f"Manifesto ausente em {MANIFESTO_ATUAL}")
class ReimportacaoPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        manifesto_atual = Manifesto.atual()
        caminho_base = DIRETORIO_RAW / manifesto_atual.arquivo

        cls.variant_retroativo = _build_variant(caminho_base, modificar_ano=2023, delta=100_000.0)
        cls.variant_removido = _build_variant(caminho_base, remover_ano=2023)
        cls.variant_avanco = _build_variant(caminho_base, modificar_ano=2026, delta=100_000.0)

    def setUp(self) -> None:
        self._manifesto_backup = MANIFESTO_ATUAL.read_bytes()
        self._raw_antes = set(DIRETORIO_RAW.glob("*.xlsx"))
        self._manifestos_antes = set(DIRETORIO_MANIFESTOS.glob("execucao_anual_*.json"))

    def tearDown(self) -> None:
        MANIFESTO_ATUAL.write_bytes(self._manifesto_backup)
        for novo in set(DIRETORIO_RAW.glob("*.xlsx")) - self._raw_antes:
            novo.unlink(missing_ok=True)
        for novo in set(DIRETORIO_MANIFESTOS.glob("execucao_anual_*.json")) - self._manifestos_antes:
            novo.unlink(missing_ok=True)
        staging = DIRETORIO_RAW / "_staging"
        if staging.exists():
            shutil.rmtree(staging)

    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()
        app.switch_page("app_pages/execucao_orcamentaria.py")
        app.run(timeout=30)
        return app

    def _upload(self, app: AppTest, content: bytes, filename: str) -> None:
        app.file_uploader[0].set_value((filename, content, XLSX_MIME))
        app.run(timeout=60)

    def test_retroactive_change_shows_gate_and_blocks_commit_by_default(self) -> None:
        app = self._open_page()
        self._upload(app, self.variant_retroativo, "variant_retroativo.xlsx")

        self.assertEqual(len(app.exception), 0)
        textos = [item.value for item in app.markdown]
        self.assertTrue(any("Exercícios com valores alterados retroativamente" in t for t in textos))
        self.assertTrue(any("2023" in t and "→" in t for t in textos))

        confirmar = next(b for b in app.button if b.label == "Confirmar substituição")
        self.assertTrue(confirmar.disabled)
        self.assertFalse(any(b.label == "Confirmar importação" for b in app.button))

        checkbox = next(c for c in app.checkbox if "confirmo a substituição" in c.label)
        self.assertFalse(checkbox.value)

        # nada deve ter sido gravado só de mostrar a prévia
        self.assertEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_backup)

    def test_retroactive_change_commits_once_explicitly_confirmed(self) -> None:
        app = self._open_page()
        self._upload(app, self.variant_retroativo, "variant_retroativo.xlsx")

        checkbox = next(c for c in app.checkbox if "confirmo a substituição" in c.label)
        checkbox.check()
        app.run(timeout=30)

        confirmar = next(b for b in app.button if b.label == "Confirmar substituição")
        self.assertFalse(confirmar.disabled)
        confirmar.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertNotEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_backup)
        manifesto_novo = Manifesto.atual()
        self.assertEqual(manifesto_novo.totais_por_ano["2023"]["empenhada"], 762_555_916.88)
        self.assertTrue((DIRETORIO_RAW / manifesto_novo.arquivo).exists())

    def test_removed_exercise_shows_gate_and_blocks_commit_by_default(self) -> None:
        app = self._open_page()
        self._upload(app, self.variant_removido, "variant_removido.xlsx")

        self.assertEqual(len(app.exception), 0)
        textos = [item.value for item in app.markdown]
        self.assertTrue(any("Exercícios que somem do painel" in t and "2023" in t for t in textos))

        confirmar = next(b for b in app.button if b.label == "Confirmar substituição")
        self.assertTrue(confirmar.disabled)
        self.assertEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_backup)

    def test_ongoing_exercise_advance_commits_without_gate(self) -> None:
        app = self._open_page()
        self._upload(app, self.variant_avanco, "variant_avanco.xlsx")

        self.assertEqual(len(app.exception), 0)
        self.assertFalse(any(b.label == "Confirmar substituição" for b in app.button))
        confirmar = next(b for b in app.button if b.label == "Confirmar importação")
        self.assertFalse(confirmar.disabled)

        confirmar.click()
        app.run(timeout=60)

        self.assertEqual(len(app.exception), 0)
        self.assertNotEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_backup)
        manifesto_novo = Manifesto.atual()
        self.assertEqual(manifesto_novo.arquivo, "variant_avanco.xlsx")
        self.assertEqual(manifesto_novo.totais_por_ano["2026"]["empenhada"], 754_539_889.56)
        self.assertTrue((DIRETORIO_RAW / "variant_avanco.xlsx").exists())

    def test_uploading_identical_file_reports_nothing_to_save(self) -> None:
        manifesto_atual = Manifesto.atual()
        caminho_ativo = DIRETORIO_RAW / manifesto_atual.arquivo
        conteudo_identico = caminho_ativo.read_bytes()

        app = self._open_page()
        self._upload(app, conteudo_identico, manifesto_atual.arquivo)

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(
            any("Arquivo idêntico à extração atual" in item.value for item in app.info)
        )
        self.assertFalse(any(b.label in ("Confirmar importação", "Confirmar substituição") for b in app.button))
        self.assertEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_backup)

    def test_invalid_extraction_is_blocked_and_reports_errors(self) -> None:
        # Linha sem NE CCor -> erro estrutural determinístico em validar(),
        # independente de magnitudes financeiras.
        caminho_ativo = DIRETORIO_RAW / Manifesto.atual().arquivo
        header = pd.read_excel(caminho_ativo, header=None, nrows=2, dtype=str)
        data = pd.read_excel(caminho_ativo, header=None, skiprows=2, dtype=str)
        COL_NE_CCOR = 33
        data.at[0, COL_NE_CCOR] = ""
        completo = pd.concat([header, data], ignore_index=True)
        buffer = io.BytesIO()
        completo.to_excel(buffer, header=False, index=False, engine="openpyxl")

        app = self._open_page()
        self._upload(app, buffer.getvalue(), "variant_invalido.xlsx")

        self.assertEqual(len(app.exception), 0)
        textos_erro = [item.value for item in app.error]
        self.assertTrue(any("bloqueada" in t for t in textos_erro))
        self.assertFalse(any(b.label in ("Confirmar importação", "Confirmar substituição") for b in app.button))
        self.assertEqual(MANIFESTO_ATUAL.read_bytes(), self._manifesto_backup)


if __name__ == "__main__":
    unittest.main()
