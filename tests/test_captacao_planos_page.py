"""Página "Planos de Referência" (consulta por código/palavra-chave sobre o banco)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.captacao import planos, schema
from tests._apptest import TEMPO_LIMITE_APPTEST

PAGINA = str(Path(__file__).resolve().parents[1] / "app_pages" / "captacao_planos.py")
CAB_PDI = ("Código do objetivo", "Dimensão / eixo do PDI", "Descrição do objetivo")
CAB_PLS = ("Eixo temático", "Objetivo", "Código da meta", "Descrição da meta")


def _abrir(caminho: Path) -> AppTest:
    with patch("src.captacao.schema.conectar.__defaults__", (caminho,)):
        app = AppTest.from_file(PAGINA, default_timeout=TEMPO_LIMITE_APPTEST)
        app.run()
        return app


class PlanosPageTests(unittest.TestCase):
    def test_banco_vazio_orienta_a_carregar_as_listas(self):
        with tempfile.TemporaryDirectory() as pasta:
            app = _abrir(Path(pasta) / "captacao.db")
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Planos de Referência")
        mensagens = [i.value for i in app.info]
        self.assertTrue(any("objetivo do PDI" in m for m in mensagens))
        self.assertTrue(any("meta do PLS" in m for m in mensagens))

    def test_lista_itens_carregados_e_busca_filtra(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "captacao.db"
            conexao = schema.conectar(caminho)
            planos.carregar_pdi(
                conexao,
                planos.validar_linhas_pdi([CAB_PDI, ("007", "Ensino", "Permanência"), ("O2", "Pesquisa", "Ciência")]),
                "PDI 2025",
            )
            planos.carregar_pls(
                conexao,
                planos.validar_linhas_pls([CAB_PLS, ("Energia", "Efic", "1.1", "Reduzir energia")]),
                "PLS 2025",
            )
            conexao.close()

            app = _abrir(caminho)
            self.assertEqual(len(app.exception), 0)
            # duas tabelas de consulta (PDI e PLS); a terceira é o histórico do item em edição
            consulta = [d for d in app.dataframe if "Código" in d.value.columns]
            self.assertEqual(len(consulta), 2)
            tabela_pdi = app.dataframe[0].value
            self.assertEqual(list(tabela_pdi["Código"]), ["007", "O2"])  # zero à esquerda preservado

            with patch("src.captacao.schema.conectar.__defaults__", (caminho,)):
                app.text_input(key="captacao_planos_busca").set_value("ciencia").run()
            self.assertEqual(list(app.dataframe[0].value["Código"]), ["O2"])



class PlanosPageEdicaoTests(unittest.TestCase):
    def _banco(self, pasta: str) -> Path:
        caminho = Path(pasta) / "captacao.db"
        conexao = schema.conectar(caminho)
        planos.carregar_pdi(
            conexao, planos.validar_linhas_pdi([CAB_PDI, ("OE-01", "Sociedade", "Texto um"), ("OE-02", "Sociedade", "Texto dois")]), "PDI 2021-2030"
        )
        conexao.close()
        return caminho

    def _rodar(self, app: AppTest, caminho: Path) -> AppTest:
        with patch("src.captacao.schema.conectar.__defaults__", (caminho,)):
            return app.run()

    def _descricao(self, caminho: Path, codigo: str) -> str:
        conexao = schema.conectar(caminho)
        try:
            return conexao.execute("SELECT descricao FROM objetivo_pdi WHERE codigo = ?", (codigo,)).fetchone()[0]
        finally:
            conexao.close()

    def test_sem_responsavel_o_salvar_fica_desabilitado(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = self._banco(pasta)
            app = _abrir(caminho)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("responsável" in i.value.lower() for i in app.info))
        salvar = [b for b in app.button if b.label == "Salvar alterações"]
        self.assertEqual(len(salvar), 1)
        self.assertTrue(salvar[0].disabled)

    def test_edita_descricao_pela_pagina_e_grava_no_banco(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = self._banco(pasta)
            app = _abrir(caminho)
            app.text_input(key="captacao_planos_responsavel").set_value("Maria")
            app = self._rodar(app, caminho)
            app.text_area[0].set_value("Texto um reescrito")
            [b for b in app.button if b.label == "Salvar alterações"][0].click()
            app = self._rodar(app, caminho)
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any("descricao" in s.value for s in app.success))
            self.assertEqual(self._descricao(caminho, "OE-01"), "Texto um reescrito")
            conexao = schema.conectar(caminho)
            historico = conexao.execute("SELECT acao, campo, antes, depois, usuario FROM historico_plano WHERE acao = 'EDITAR'").fetchall()
            conexao.close()
            self.assertEqual([tuple(h) for h in historico], [("EDITAR", "descricao", "Texto um", "Texto um reescrito", "Maria")])

    def test_codigo_repetido_mostra_erro_e_nao_grava(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = self._banco(pasta)
            app = _abrir(caminho)
            app.text_input(key="captacao_planos_responsavel").set_value("Maria")
            app = self._rodar(app, caminho)
            [t for t in app.text_input if t.label == "Código"][0].set_value("OE-02")
            [b for b in app.button if b.label == "Salvar alterações"][0].click()
            app = self._rodar(app, caminho)
            self.assertTrue(any("Já existe o código" in e.value for e in app.error))
            conexao = schema.conectar(caminho)
            codigos = [r[0] for r in conexao.execute("SELECT codigo FROM objetivo_pdi ORDER BY id")]
            conexao.close()
            self.assertEqual(codigos, ["OE-01", "OE-02"])

    def test_desativar_item_pela_pagina(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = self._banco(pasta)
            app = _abrir(caminho)
            app.text_input(key="captacao_planos_responsavel").set_value("Maria")
            app = self._rodar(app, caminho)
            [b for b in app.button if b.label == "Desativar item"][0].click()
            app = self._rodar(app, caminho)
            self.assertEqual(len(app.exception), 0)
            conexao = schema.conectar(caminho)
            ativo = conexao.execute("SELECT ativo FROM objetivo_pdi WHERE codigo = 'OE-01'").fetchone()[0]
            conexao.close()
            self.assertEqual(ativo, 0)
            self.assertTrue(any(b.label == "Reativar item" for b in app.button))


if __name__ == "__main__":
    unittest.main()
