"""Teste de fumaça da reimportação pela interface — página "Atualizar Planilhas", card
"Execução Mensal" (`src/reimportacao_especificacoes.py::ESPECIFICACAO_EXECUCAO_MENSAL`).

Só confirma a fiação ponta a ponta (o card renderiza, o upload sobe pela interface e grava o
manifesto) — a lógica de detecção de retroatividade/composição por ano já é testada a fundo em
`tests/test_importacao_execucao_mensal.py` (módulo) e `tests/test_importacao_versionada.py`
(núcleo genérico); a suíte equivalente da Execução Anual
(`tests/test_execucao_orcamentaria_reimportacao.py`) cobre os três caminhos do gate de
confirmação em detalhe — não duplicado aqui de propósito.

"Atualizar Planilhas" tem 3 `st.file_uploader` com o rótulo "Nova extração (.xlsx)" (Execução,
Dotação, Execução Mensal, nesta ordem de renderização — ver `app_pages/atualizar_planilhas.py`)
— o terceiro é o desta base.

`ESPECIFICACAO_EXECUCAO_MENSAL` é redirecionada para um diretório temporário por
`tests._reimportacao_isolamento` — nenhuma escrita em `data/raw/`/`data/manifestos/` reais.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests._apptest import TEMPO_LIMITE_APPTEST

from src.importacao_execucao_mensal import Manifesto
from tests._reimportacao_isolamento import IsolamentoReimportacaoMixin

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMINHO_FIXTURE = PROJECT_ROOT / "tests/fixtures/execucao_mensal_2026-09-22.xlsx"

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@unittest.skipUnless(CAMINHO_FIXTURE.exists(), f"Fixture ausente em {CAMINHO_FIXTURE}")
class ExecucaoMensalReimportacaoPageTests(IsolamentoReimportacaoMixin, unittest.TestCase):
    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=TEMPO_LIMITE_APPTEST)
        app.run()
        app.switch_page("app_pages/atualizar_planilhas.py")
        app.run()
        return app

    def test_card_execucao_mensal_aparece_na_pagina(self) -> None:
        app = self._open_page()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any(s.value == "Execução Mensal" for s in app.subheader))
        uploaders = [u for u in app.file_uploader if u.label == "Nova extração (.xlsx)"]
        self.assertEqual(len(uploaders), 3)

    def test_upload_da_extracao_grava_manifesto_e_confirma_na_interface(self) -> None:
        # Checa o manifesto gravado em disco, não o texto "Importação concluída" — esse
        # `st.success` é seguido de `st.rerun()` (`src/ui_reimportacao.py::
        # _efetivar_reimportacao`) e não sobrevive de forma confiável ao rerun dentro do
        # `AppTest` (mesmo padrão já usado por `tests/test_execucao_orcamentaria_reimportacao.py`,
        # que também confere o manifesto em vez da mensagem).
        app = self._open_page()
        uploader = [u for u in app.file_uploader if u.label == "Nova extração (.xlsx)"][2]
        uploader.set_value((CAMINHO_FIXTURE.name, CAMINHO_FIXTURE.read_bytes(), XLSX_MIME))
        app.run()

        self.assertEqual(len(app.exception), 0)
        confirmar = next(b for b in app.button if b.label == "Confirmar importação")
        confirmar.click()
        app.run()

        self.assertEqual(len(app.exception), 0)
        manifesto = Manifesto.atual(diretorio=self.tmp_manifestos)
        self.assertIsNotNone(manifesto)
        self.assertEqual(manifesto.anos, [2024, 2025, 2026])
        self.assertTrue((self.tmp_raw / CAMINHO_FIXTURE.name).exists())


if __name__ == "__main__":
    unittest.main()
