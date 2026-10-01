"""Página "Ciclo de Captação" (Etapa 0, somente leitura)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.captacao import schema
from tests._apptest import TEMPO_LIMITE_APPTEST

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGINA = str(PROJECT_ROOT / "app_pages" / "captacao_ciclo.py")


def _abrir() -> AppTest:
    app = AppTest.from_file(PAGINA, default_timeout=TEMPO_LIMITE_APPTEST)
    app.run()
    return app


class CicloPageTests(unittest.TestCase):
    def test_sem_banco_informa_que_nao_ha_ciclo_sem_falhar(self):
        with tempfile.TemporaryDirectory() as pasta:
            inexistente = Path(pasta) / "captacao.db"
            with patch.object(schema, "CAMINHO_BANCO_PADRAO", inexistente), patch(
                "src.captacao.schema.CAMINHO_BANCO_PADRAO", inexistente
            ):
                app = _abrir()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Captação de Demandas — Ciclo")
        self.assertTrue(any("nenhum ciclo" in info.value.lower() for info in app.info))

    def test_com_ciclo_mostra_datas_e_contagens_por_situacao(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "captacao.db"
            conexao = schema.conectar(caminho)
            conexao.execute("INSERT INTO unidade (id, ugr_codigo, nome) VALUES (1, '158001', 'Depto. A')")
            conexao.execute(
                "INSERT INTO ciclo (id, exercicio, fase, abertura, encerramento, criado_em)"
                " VALUES (1, 2027, 'ABERTO', '2026-09-01', '2026-10-31', 'x')"
            )
            conexao.execute(
                "INSERT INTO demanda (ciclo_id, unidade_id, situacao, criada_em, atualizada_em)"
                " VALUES (1, 1, 'RASCUNHO', 'x', 'x')"
            )
            conexao.commit()
            conexao.close()
            with patch("src.captacao.schema.CAMINHO_BANCO_PADRAO", caminho), patch(
                "src.captacao.schema.conectar.__defaults__", (caminho,)
            ):
                app = _abrir()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("2027" in subheader.value for subheader in app.subheader))
        valores = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(valores["Abertura do registro"], "01/09/2026")
        self.assertEqual(valores["Encerramento do registro"], "31/10/2026")
        self.assertEqual(valores["Rascunho"], "1")
        self.assertEqual(valores["Enviada"], "0")


if __name__ == "__main__":
    unittest.main()
