"""
Teste de página da Central de Alertas (TEDs): a trilha de auditoria aparece no detalhe do alerta
e a ação "Marcar em análise" grava um registro de auditoria. Usa um banco temporário — nunca
`data/teds/teds.db`.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from tests._apptest import TEMPO_LIMITE_APPTEST

from src.teds_auditoria import ENTIDADE_ALERTA, historico_auditoria
from src.teds_schema import conectar

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGINA = "app_pages/teds_central_alertas.py"


class CentralAlertasPageTests(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.conexoes = []
        self.caminho = Path(self.pasta.name) / "teds.db"
        conn = conectar(self.caminho)
        conn.execute(
            "INSERT INTO alerta (id, tipo, gravidade, documento, descricao, data_identificacao) "
            "VALUES (1, 'ted_vencido_em_execucao', 'media', 'TED|1', 'Vigência encerrada.', '2026-09-23')"
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        # A página não fecha a conexão que abre; no Windows o arquivo só é apagado depois disso.
        for conexao in self.conexoes:
            conexao.close()
        self.pasta.cleanup()

    def _abrir(self):
        # O AppTest roda o script noutra thread; o esquema já foi aplicado em `setUp`.
        conexao = sqlite3.connect(self.caminho, check_same_thread=False)
        self.conexoes.append(conexao)
        return conexao

    def _rodar(self) -> AppTest:
        with mock.patch("src.teds_ui.conexao", self._abrir):
            app = AppTest.from_file(str(PROJECT_ROOT / PAGINA), default_timeout=TEMPO_LIMITE_APPTEST)
            app.run()
        return app

    def _textos(self, app: AppTest) -> str:
        return " ".join(str(e.value) for e in list(app.markdown) + list(app.caption))

    def test_alerta_sem_acao_mostra_trilha_vazia_e_regra_do_tipo_novo(self):
        app = self._rodar()
        self.assertEqual(len(app.exception), 0)
        texto = self._textos(app)
        self.assertIn("Trilha de auditoria", texto)
        self.assertIn("Nenhuma ação humana registrada para este alerta.", texto)
        self.assertIn("Termo em Execução", texto)  # regra de negócio do tipo, não "—"

    def test_marcar_em_analise_grava_auditoria_e_a_tela_passa_a_exibi_la(self):
        with mock.patch("src.teds_ui.conexao", self._abrir):
            app = AppTest.from_file(str(PROJECT_ROOT / PAGINA), default_timeout=TEMPO_LIMITE_APPTEST)
            app.run()
            app.text_input(key="ca_resp_txt_1").set_value("Ana").run()
            botao = next(b for b in app.button if b.label == "Marcar em análise")
            botao.click().run()

        self.assertEqual(len(app.exception), 0)
        conn = conectar(self.caminho)
        try:
            (registro,) = historico_auditoria(conn, ENTIDADE_ALERTA, 1)
        finally:
            conn.close()
        self.assertEqual(registro.usuario, "Ana")
        self.assertEqual(registro.valor_anterior["status"], "aberto")
        self.assertEqual(registro.valor_novo["status"], "em_analise")
        texto = self._textos(app)
        self.assertIn("Situação do alerta alterada", texto)
        self.assertIn("Ana", texto)


if __name__ == "__main__":
    unittest.main()
