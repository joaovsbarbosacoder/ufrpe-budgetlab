"""
Teste de página: seção "Conferir com a planilha de controle" na Conciliação dos TEDs.
A planilha é lida só em memória (nada é gravado) e a resolução de um alerta sugerida por ela passa
pelo fluxo existente (status + auditoria). Banco temporário — nunca `data/teds/teds.db`.
"""

from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from openpyxl import Workbook
from streamlit.testing.v1 import AppTest

from src.teds_auditoria import ENTIDADE_ALERTA, historico_auditoria
from src.teds_schema import conectar
from tests._apptest import TEMPO_LIMITE_APPTEST

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGINA = "app_pages/teds_conciliacao.py"
CHAVE_TED = "11926|1AALOH"
CAB = ["NC", "DATA", "UG EMITENTE", "OFÍCIO", "TED", "N.  TRANSFERENCIA", "VALOR", "PROCESSO",
       "OBSERVAÇÃO"]


def _planilha() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "2022"
    ws.append(CAB)
    ws.append(["2022NC001794", datetime(2022, 8, 3), 152734, "x", 11926, "1AALOH", 2246361.47,
               None, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class ConciliacaoControlePageTests(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.conexoes = []
        self.caminho = Path(self.pasta.name) / "teds.db"
        conn = conectar(self.caminho)
        conn.execute(
            "INSERT INTO import_batch (id, tipo_relatorio, nome_arquivo, hash_arquivo, "
            "data_importacao, status) VALUES (1, 'teste', 'x.xlsx', 'h', '2026-01-01T00:00:00', 'ok')"
        )
        conn.execute("INSERT INTO ted (chave_ted, ted, codigo_siafi) VALUES (?, '11926', '1AALOH')",
                     (CHAVE_TED,))
        zero = "0.00"
        conn.execute(
            "INSERT INTO execucao_anual (chave_ted, ano_emissao, total_nc_descentralizacao, "
            "total_nc_devolucao, total_descentralizado, total_pf_repasse, total_pf_devolucao, "
            "total_repassado, import_batch_id, linha_origem) VALUES (?, 2023, ?, ?, ?, ?, ?, ?, 1, '{}')",
            (CHAVE_TED, zero, zero, zero, zero, zero, zero),
        )
        conn.execute(
            "INSERT INTO alerta (id, tipo, gravidade, chave_ted, documento, descricao, "
            "data_identificacao) VALUES (1, 'pf_liquida_maior_que_nc', 'alta', ?, ?, "
            "'PF líquida maior que a NC.', '2026-10-01')", (CHAVE_TED, CHAVE_TED),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        for conexao in self.conexoes:
            conexao.close()
        self.pasta.cleanup()

    def _abrir(self):
        conexao = sqlite3.connect(self.caminho, check_same_thread=False)
        self.conexoes.append(conexao)
        return conexao

    def _contagens(self) -> dict[str, int]:
        conn = sqlite3.connect(self.caminho)
        try:
            tabelas = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tabelas}
        finally:
            conn.close()

    def _app(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / PAGINA), default_timeout=TEMPO_LIMITE_APPTEST)
        app.run()
        return app

    def test_conferencia_nao_grava_no_banco(self):
        antes = self._contagens()
        with mock.patch("src.teds_ui.conexao", self._abrir):
            app = self._app()
            app.file_uploader(key="cc_controle_upload").upload("controle.xlsx", _planilha()).run()
        self.assertEqual(len(app.exception), 0)
        texto = " ".join(str(e.value) for e in list(app.markdown) + list(app.caption))
        self.assertIn("A planilha é lida só nesta tela e não é gravada no banco.", texto)
        self.assertIn("NC anterior ao consolidado", texto)
        self.assertEqual(self._contagens(), antes)

    def test_resolver_pela_planilha_grava_status_e_auditoria(self):
        with mock.patch("src.teds_ui.conexao", self._abrir):
            app = self._app()
            app.file_uploader(key="cc_controle_upload").upload("controle.xlsx", _planilha()).run()
            sugestao = app.text_area(key="cc_controle_just_1").value
            self.assertIn("2022NC001794", sugestao)
            app.text_input(key="cc_controle_resp_1").set_value("Ana").run()
            next(b for b in app.button if b.label == "Resolver").click().run()
        self.assertEqual(len(app.exception), 0)
        conn = conectar(self.caminho)
        try:
            status, resp, just = conn.execute(
                "SELECT status, responsavel, justificativa FROM alerta WHERE id = 1").fetchone()
            registros = historico_auditoria(conn, ENTIDADE_ALERTA, 1)
        finally:
            conn.close()
        self.assertEqual(status, "resolvido")
        self.assertEqual(resp, "Ana")
        self.assertEqual(just, sugestao)
        self.assertEqual(len(registros), 1)


if __name__ == "__main__":
    unittest.main()
