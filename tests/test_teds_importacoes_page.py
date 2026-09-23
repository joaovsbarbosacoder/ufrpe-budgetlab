"""
Teste de página de Importações (TEDs): a seção "Reverter lote" lista só lotes reversíveis, recusa
sem confirmação/responsável/motivo e, com tudo preenchido, reverte o lote e mostra o resultado.
Usa um banco temporário — nunca `data/teds/teds.db`.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.teds_lotes import importar_doc_ne
from src.teds_normalizacao import texto_para_valor
from src.teds_schema import conectar

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGINA = "app_pages/teds_importacoes.py"


def _df_ne(valor: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "Gestão Emitente - NE": "15239", "UG Executora Emitente - NE": "153165",
        "Descrição do Termo": "Termo", "Estado Atual": "Termo em Execução",
        "Início da Vigência": "01/01/2026", "Fim da Vigência": "31/12/2027",
        "UG Descentralizadora": "154046", "Número do Empenho": "2026NE000427",
        "SIAFI": "1ABDKQ", "TED": "17454", "Valor da NE": valor,
    }])


class ImportacoesPageTests(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.caminho = Path(self.pasta.name) / "teds.db"
        self.conexoes = []
        conn = conectar(self.caminho)
        self.lote1 = importar_doc_ne(conn, _df_ne("100,00"), "v1.xlsx", b"v1").import_batch_id
        self.lote2 = importar_doc_ne(conn, _df_ne("160,00"), "v2.xlsx", b"v2").import_batch_id
        conn.close()

    def tearDown(self):
        for conexao in self.conexoes:
            conexao.close()
        self.pasta.cleanup()

    def _abrir(self):
        conexao = sqlite3.connect(self.caminho, check_same_thread=False)  # o AppTest roda noutra thread
        self.conexoes.append(conexao)
        return conexao

    def _app(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / PAGINA), default_timeout=60)
        return app

    def _valor(self) -> Decimal:
        conn = sqlite3.connect(self.caminho)
        try:
            (texto,) = conn.execute("SELECT valor_ne FROM vinculo_ne").fetchone()
        finally:
            conn.close()
        return texto_para_valor(texto)

    def _status(self, lote: int) -> str:
        conn = sqlite3.connect(self.caminho)
        try:
            return conn.execute("SELECT status FROM import_batch WHERE id = ?", (lote,)).fetchone()[0]
        finally:
            conn.close()

    def test_lista_os_lotes_reversiveis_e_recusa_sem_confirmar(self):
        with mock.patch("src.teds_ui.conexao", self._abrir):
            app = self._app()
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.selectbox(key="imp_rev_lote").options), 2)

            app.text_input(key="imp_rev_resp").set_value("Ana")
            app.text_area(key="imp_rev_motivo").set_value("arquivo errado")
            next(b for b in app.button if b.label == "Reverter lote").click().run()

        self.assertTrue(any("confirmação" in e.value for e in app.error))
        self.assertEqual(self._status(self.lote2), "ok")
        self.assertEqual(self._valor(), Decimal("160.00"))

    def test_reverte_o_lote_escolhido_e_mostra_o_resultado(self):
        with mock.patch("src.teds_ui.conexao", self._abrir):
            app = self._app()
            app.run()
            app.text_input(key="imp_rev_resp").set_value("Ana")
            app.text_area(key="imp_rev_motivo").set_value("arquivo errado")
            app.checkbox(key="imp_rev_confirma").check()
            next(b for b in app.button if b.label == "Reverter lote").click().run()

            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("revertido" in e.value and f"#{self.lote2}" in e.value for e in app.success))

        self.assertEqual(self._status(self.lote2), "revertido")
        self.assertEqual(self._valor(), Decimal("100.00"))  # voltou ao valor do lote 1

    def test_responsavel_em_branco_e_recusado_pela_regra_de_negocio(self):
        with mock.patch("src.teds_ui.conexao", self._abrir):
            app = self._app()
            app.run()
            app.text_area(key="imp_rev_motivo").set_value("x")
            app.checkbox(key="imp_rev_confirma").check()
            next(b for b in app.button if b.label == "Reverter lote").click().run()

        self.assertTrue(any("responsável" in e.value for e in app.error))
        self.assertEqual(self._status(self.lote2), "ok")


if __name__ == "__main__":
    unittest.main()
