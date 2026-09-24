"""
Teste de página "Células NC × NE" (TEDs): mostra os indicadores por situação, a tabela rastreável e os filtros.
Usa um banco temporário — nunca `data/teds/teds.db`.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.teds_lotes import importar_doc_nc, importar_doc_ne, importar_nc_tg_historica, sincronizar_execucao_tg
from src.teds_schema import conectar
from tests.test_teds_celula_orcamentaria import (
    NC_A,
    _bruto_hist,
    _como_header0,
    _df_nc_simec,
    _df_ne_simec,
    _execucao_mensal,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGINA = "app_pages/teds_celulas.py"


class CelulasPageTests(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.caminho = Path(self.pasta.name) / "teds.db"
        self.conexoes = []
        self.conn = conectar(self.caminho)
        # O patch fica ativo durante o TESTE INTEIRO: todo `run()` do AppTest (inclusive os de depois de mexer
        # nos filtros) abre o banco temporário. Fora dele a página abriria o banco REAL, `data/teds/teds.db`.
        patcher = mock.patch("src.teds_ui.conexao", self._abrir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.conn.close()
        for conexao in self.conexoes:
            conexao.close()
        self.pasta.cleanup()

    def test_a_pagina_nunca_abre_o_banco_real(self):
        self._rodar()
        self.assertTrue(self.conexoes, "a página deveria ter aberto o banco temporário, não o real")

    def _abrir(self):
        conexao = sqlite3.connect(self.caminho, check_same_thread=False)  # o AppTest roda noutra thread
        self.conexoes.append(conexao)
        return conexao

    def _popular(self):
        importar_doc_ne(self.conn, _df_ne_simec(), "ne.xlsx", b"ne")
        importar_doc_nc(self.conn, _df_nc_simec(["2025NC000408"]), "nc.xlsx", b"nc")
        bruto = _bruto_hist([(NC_A, "1AAMVG", n, "230551", "MCC62G22EDN", "1000A00238", 10.0) for n in ("339014", "339030")])
        importar_nc_tg_historica(self.conn, _como_header0(bruto), "destaques.xlsx", b"destaques")
        vazio = SimpleNamespace(registros=[], rejeitadas=[])
        with mock.patch("src.teds_lotes.montar_execucao_tg", return_value=vazio):
            sincronizar_execucao_tg(self.conn, _execucao_mensal("339032"), "sha", "mensal.xlsx")

    def _rodar(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / PAGINA), default_timeout=60)
        app.run()
        return app

    def test_sem_nenhuma_ne_vinculada_avisa_e_para(self):
        app = self._rodar()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("Nenhuma NE vinculada" in i.value for i in app.info))

    def test_sem_bases_de_celula_mostra_os_avisos_e_a_ne_como_base_incompleta(self):
        importar_doc_ne(self.conn, _df_ne_simec(), "ne.xlsx", b"ne")
        app = self._rodar()
        self.assertEqual(len(app.exception), 0)
        avisos = " ".join(w.value for w in app.warning)
        self.assertIn("Nenhum relatório de NC do Tesouro Gerencial importado", avisos)
        self.assertIn("Sincronizar com a Execução Mensal", avisos)
        self.assertEqual(len(app.dataframe), 1)
        self.assertEqual(app.dataframe[0].value["Situação"].tolist(), ["NC não identificada ou base incompleta"])

    def test_mostra_a_divergencia_com_os_codigos_comparados_e_filtra_por_situacao(self):
        self._popular()
        app = self._rodar()
        self.assertEqual(len(app.exception), 0)
        tabela = app.dataframe[0].value
        self.assertEqual(len(tabela), 1)
        linha = tabela.iloc[0]
        self.assertEqual(linha["Situação"], "Divergência para conferência")
        self.assertEqual(linha["Célula da NE (PTRES | fonte | natureza | PI)"], "230551 | 1000A00238 | 339032 | MCC62G22EDN")
        self.assertEqual(linha["Campos divergentes"], "natureza da despesa")
        self.assertIn("339014", linha["Valores nas NCs para o campo divergente"])

        app.selectbox(key="cel_situacao").set_value("Correspondente").run()
        self.assertEqual(len(app.dataframe[0].value), 0)
        app.selectbox(key="cel_situacao").set_value("Divergência para conferência").run()
        self.assertEqual(len(app.dataframe[0].value), 1)

    def test_filtro_por_ne_e_por_nc(self):
        self._popular()
        app = self._rodar()
        app.text_input(key="cel_ne").set_value("2025NE000706").run()
        self.assertEqual(len(app.dataframe[0].value), 1)
        app.text_input(key="cel_ne").set_value("2099NE").run()
        self.assertEqual(len(app.dataframe[0].value), 0)
        app.text_input(key="cel_ne").set_value("").run()
        app.text_input(key="cel_nc").set_value("2025NC000408").run()
        self.assertEqual(len(app.dataframe[0].value), 1)


if __name__ == "__main__":
    unittest.main()
