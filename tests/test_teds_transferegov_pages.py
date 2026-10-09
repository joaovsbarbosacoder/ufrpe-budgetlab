"""
Páginas dos TEDs com a origem TransfereGov: Lista (seletor de origem, lista e detalhe), Visão geral (resumo
sem valores) e Importações (botão de sincronização, sem rede). Banco temporário — nunca `data/teds/teds.db`.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from src import teds_transferegov as tg
from src.teds_schema import conectar
from src.ui_teds_transferegov import CHAVE_SELECIONADO, ORIGEM_TRANSFEREGOV
from tests._apptest import TEMPO_LIMITE_APPTEST
from tests.test_teds_transferegov import _extracao

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PaginasTransfereGovTests(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.caminho = Path(self.pasta.name) / "teds.db"
        self.conexoes = []
        conectar(self.caminho).close()

    def tearDown(self):
        for conexao in self.conexoes:
            conexao.close()
        self.pasta.cleanup()

    def _abrir(self):
        conexao = sqlite3.connect(self.caminho, check_same_thread=False)  # o AppTest roda noutra thread
        self.conexoes.append(conexao)
        return conexao

    def _sincronizar(self):
        conn = conectar(self.caminho)
        try:
            tg.sincronizar_transferegov(conn, _extracao())
        finally:
            conn.close()

    def _app(self, pagina: str) -> AppTest:
        return AppTest.from_file(str(PROJECT_ROOT / pagina), default_timeout=TEMPO_LIMITE_APPTEST)

    def _textos(self, app: AppTest) -> str:
        return " ".join(m.value for m in app.markdown) + " " + " ".join(c.value for c in app.caption)

    def test_lista_na_origem_transferegov_mostra_os_planos_e_abre_o_detalhe(self):
        self._sincronizar()
        with mock.patch("src.teds_ui.conexao", self._abrir):
            app = self._app("app_pages/teds_lista.py")
            app.session_state["lst_origem"] = ORIGEM_TRANSFEREGOV
            app.run()
            self.assertFalse(app.exception)
            textos = self._textos(app)
            self.assertIn("TED 975286/2025", textos)
            self.assertIn("Plano de ação 1445 (sem termo)", textos)

            app.button(key="tg_abrir_0").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state[CHAVE_SELECIONADO], "4180")
            textos = self._textos(app)
            self.assertIn("NC 2025NC800002", textos)
            self.assertIn("Evento 300302", textos)
            self.assertIn("nenhum total é calculado", textos)

    def test_lista_simec_vazia_continua_avisando(self):
        with mock.patch("src.teds_ui.conexao", self._abrir):
            app = self._app("app_pages/teds_lista.py")
            app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Nenhum TED importado" in i.value for i in app.info))

    def test_visao_geral_sem_simec_mostra_o_resumo_do_transferegov(self):
        self._sincronizar()
        with mock.patch("src.teds_ui.conexao", self._abrir):
            app = self._app("app_pages/teds_visao_geral.py")
            app.run()
        self.assertFalse(app.exception)
        self.assertIn("TEDs de outros órgãos (TransfereGov)", self._textos(app))
        self.assertIn("Planos de ação", self._textos(app))

    def test_importacoes_sincroniza_sem_rede_e_depois_e_no_op(self):
        extracao = _extracao()  # montada antes do patch: `_extracao` usa o próprio `baixar_extracao`
        with mock.patch("src.teds_ui.conexao", self._abrir), \
             mock.patch("src.teds_transferegov.baixar_extracao", lambda: extracao):
            app = self._app("app_pages/teds_importacoes.py")
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any("ainda não foi sincronizado" in w.value for w in app.warning))

            app.button(key="imp_sincronizar_transferegov").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Sincronização concluída" in s.value for s in app.success))

            app.button(key="imp_sincronizar_transferegov").click().run()
            self.assertTrue(any("A API não mudou" in s.value for s in app.success))

    def test_importacoes_erro_da_api_nao_grava_nada(self):
        def falha():
            raise tg.ErroConsultaTransfereGov("API fora do ar")

        with mock.patch("src.teds_ui.conexao", self._abrir), \
             mock.patch("src.teds_transferegov.baixar_extracao", falha):
            app = self._app("app_pages/teds_importacoes.py")
            app.run()
            app.button(key="imp_sincronizar_transferegov").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("API fora do ar" in e.value for e in app.error))
        conn = sqlite3.connect(self.caminho)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM import_batch").fetchone()[0], 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
