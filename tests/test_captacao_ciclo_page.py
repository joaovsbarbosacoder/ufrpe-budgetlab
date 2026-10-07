"""Páginas "Ciclo de Captação" e "Unidades da Captação" (Etapa 4)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.captacao import ciclos, schema, unidades
from tests._apptest import TEMPO_LIMITE_APPTEST

RAIZ = Path(__file__).resolve().parents[1]
PAGINA_CICLO = str(RAIZ / "app_pages" / "captacao_ciclo.py")
PAGINA_UNIDADES = str(RAIZ / "app_pages" / "captacao_unidades.py")
HOJE = date.today()


def _abrir(pagina: str, caminho: Path) -> AppTest:
    app = AppTest.from_file(pagina, default_timeout=TEMPO_LIMITE_APPTEST)
    return _rodar(app, caminho)


def _rodar(app: AppTest, caminho: Path) -> AppTest:
    with patch("src.captacao.schema.conectar.__defaults__", (caminho,)):
        return app.run()


def _datas_ciclo(**ajustes):
    dados = {
        "abertura": HOJE - timedelta(days=10),
        "encerramento": HOJE + timedelta(days=20),
        "prazo_validacao": HOJE + timedelta(days=30),
        "devolutiva_prevista": HOJE + timedelta(days=40),
    }
    dados.update(ajustes)
    return dados


def _botao(app: AppTest, rotulo: str):
    return [b for b in app.button if b.label == rotulo][0]


class CicloPageTests(unittest.TestCase):
    def test_sem_ciclo_orienta_a_criar_o_primeiro_sem_falhar(self):
        with tempfile.TemporaryDirectory() as pasta:
            app = _abrir(PAGINA_CICLO, Path(pasta) / "captacao.db")
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Captação de Demandas — Ciclo")
        self.assertTrue(any("Nenhum ciclo" in info.value for info in app.info))

    def test_sem_responsavel_os_botoes_de_gravar_ficam_desabilitados(self):
        with tempfile.TemporaryDirectory() as pasta:
            app = _abrir(PAGINA_CICLO, Path(pasta) / "captacao.db")
        self.assertTrue(_botao(app, "Criar ciclo").disabled)
        self.assertTrue(any("responsável" in info.value.lower() for info in app.info))

    def test_cria_ciclo_pela_pagina_e_grava_no_banco_e_no_historico(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "captacao.db"
            app = _abrir(PAGINA_CICLO, caminho)
            app.text_input(key="captacao_ciclo_responsavel").set_value("Maria")
            app.number_input(key="captacao_ciclo_novo_exercicio").set_value(2027)
            app.date_input(key="captacao_ciclo_novo_abertura").set_value(date(2026, 9, 1))
            app.date_input(key="captacao_ciclo_novo_encerramento").set_value(date(2026, 10, 31))
            app = _rodar(app, caminho)
            _botao(app, "Criar ciclo").click()
            app = _rodar(app, caminho)
            self.assertEqual(len(app.exception), 0)
            conexao = schema.conectar(caminho)
            linha = conexao.execute("SELECT * FROM ciclo").fetchone()
            historico = conexao.execute("SELECT acao, usuario FROM historico_cadastro").fetchall()
            conexao.close()
            self.assertEqual((linha["exercicio"], linha["fase"], linha["abertura"], linha["encerramento"]), (2027, "RASCUNHO", "2026-09-01", "2026-10-31"))
            self.assertEqual([tuple(h) for h in historico], [("CRIAR", "Maria")])

    def test_datas_fora_de_ordem_mostram_erro_e_nao_gravam(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "captacao.db"
            app = _abrir(PAGINA_CICLO, caminho)
            app.text_input(key="captacao_ciclo_responsavel").set_value("Maria")
            app.date_input(key="captacao_ciclo_novo_abertura").set_value(date(2026, 11, 1))
            app.date_input(key="captacao_ciclo_novo_encerramento").set_value(date(2026, 10, 1))
            app = _rodar(app, caminho)
            _botao(app, "Criar ciclo").click()
            app = _rodar(app, caminho)
            self.assertTrue(any("não pode ser depois" in e.value for e in app.error))
            conexao = schema.conectar(caminho)
            total = conexao.execute("SELECT COUNT(*) FROM ciclo").fetchone()[0]
            conexao.close()
            self.assertEqual(total, 0)

    def test_mostra_datas_e_contagens_do_ciclo_existente(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "captacao.db"
            conexao = schema.conectar(caminho)
            unidades.criar_unidade(conexao, {"ugr_codigo": "A1", "nome": "Depto. A"}, "Maria")
            ciclo_id = ciclos.criar_ciclo(conexao, 2027, _datas_ciclo(abertura=date(2026, 9, 1), encerramento=date(2026, 10, 31), prazo_validacao=date(2026, 11, 7), devolutiva_prevista=date(2026, 12, 15)), "Maria")
            conexao.execute(
                "INSERT INTO demanda (ciclo_id, unidade_id, situacao, criada_em, atualizada_em) VALUES (?, 1, 'RASCUNHO', 'x', 'x')", (ciclo_id,)
            )
            conexao.commit()
            conexao.close()
            app = _abrir(PAGINA_CICLO, caminho)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("2027" in s.value for s in app.subheader))
        valores = {m.label: m.value for m in app.metric}
        self.assertEqual(valores["Abertura do registro"], "01/09/2026")
        self.assertEqual(valores["Encerramento do registro"], "31/10/2026")
        self.assertEqual(valores["Devolutiva prevista"], "15/12/2026")
        self.assertEqual((valores["Rascunho"], valores["Enviada"]), ("1", "0"))

    def test_agenda_o_ciclo_pelo_botao(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "captacao.db"
            conexao = schema.conectar(caminho)
            ciclos.criar_ciclo(conexao, 2027, _datas_ciclo(), "Maria")
            conexao.close()
            app = _abrir(PAGINA_CICLO, caminho)
            app.text_input(key="captacao_ciclo_responsavel").set_value("Maria")
            app = _rodar(app, caminho)
            _botao(app, "Agendar ciclo").click()
            app = _rodar(app, caminho)
            self.assertEqual(len(app.exception), 0)
            conexao = schema.conectar(caminho)
            fase = conexao.execute("SELECT fase FROM ciclo").fetchone()[0]
            conexao.close()
            self.assertEqual(fase, "AGENDADO")

    def test_encerrar_agora_so_fica_habilitado_com_ciclo_aberto(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "captacao.db"
            conexao = schema.conectar(caminho)
            ciclos.criar_ciclo(conexao, 2027, _datas_ciclo(), "Maria")
            conexao.close()
            app = _abrir(PAGINA_CICLO, caminho)
            app.text_input(key="captacao_ciclo_responsavel").set_value("Maria")
            app = _rodar(app, caminho)
            self.assertTrue(_botao(app, "Encerrar registro agora").disabled)  # em preparação
            self.assertFalse(_botao(app, "Abrir registro agora").disabled)

    def test_concede_prorrogacao_pela_pagina(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "captacao.db"
            conexao = schema.conectar(caminho)
            unidades.criar_unidade(conexao, {"ugr_codigo": "A1", "nome": "Depto. A"}, "Maria")
            ciclo_id = ciclos.criar_ciclo(conexao, 2027, _datas_ciclo(), "Maria")
            ciclos.agendar_ciclo(conexao, ciclo_id, "Maria")
            conexao.close()
            app = _abrir(PAGINA_CICLO, caminho)
            app.text_input(key="captacao_ciclo_responsavel").set_value("Gestor")
            app = _rodar(app, caminho)
            prazo = HOJE + timedelta(days=25)
            app.date_input[-1].set_value(prazo)  # "Novo prazo" do formulário de prorrogação
            [t for t in app.text_input if t.label == "Motivo"][0].set_value("Troca de chefia")
            app = _rodar(app, caminho)
            _botao(app, "Conceder prorrogação").click()
            app = _rodar(app, caminho)
            self.assertEqual(len(app.exception), 0)
            conexao = schema.conectar(caminho)
            linha = conexao.execute("SELECT novo_prazo, motivo, concedida_por FROM prorrogacao").fetchone()
            conexao.close()
            self.assertEqual((linha["novo_prazo"], linha["motivo"], linha["concedida_por"]), (prazo.isoformat(), "Troca de chefia", "Gestor"))

    def test_prorrogacao_sem_motivo_mostra_erro(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "captacao.db"
            conexao = schema.conectar(caminho)
            unidades.criar_unidade(conexao, {"ugr_codigo": "A1", "nome": "Depto. A"}, "Maria")
            ciclo_id = ciclos.criar_ciclo(conexao, 2027, _datas_ciclo(), "Maria")
            ciclos.agendar_ciclo(conexao, ciclo_id, "Maria")
            conexao.close()
            app = _abrir(PAGINA_CICLO, caminho)
            app.text_input(key="captacao_ciclo_responsavel").set_value("Gestor")
            app = _rodar(app, caminho)
            app.date_input[-1].set_value(HOJE + timedelta(days=25))
            app = _rodar(app, caminho)
            _botao(app, "Conceder prorrogação").click()
            app = _rodar(app, caminho)
            self.assertTrue(any("motivo" in e.value.lower() for e in app.error))
            conexao = schema.conectar(caminho)
            total = conexao.execute("SELECT COUNT(*) FROM prorrogacao").fetchone()[0]
            conexao.close()
            self.assertEqual(total, 0)


class UnidadesPageTests(unittest.TestCase):
    def test_sem_unidades_orienta_a_incluir(self):
        with tempfile.TemporaryDirectory() as pasta:
            app = _abrir(PAGINA_UNIDADES, Path(pasta) / "captacao.db")
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Unidades da Captação")
        self.assertTrue(any("Nenhuma unidade" in info.value for info in app.info))
        self.assertTrue(_botao(app, "Incluir").disabled)

    def test_inclui_unidade_preservando_zero_a_esquerda(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "captacao.db"
            app = _abrir(PAGINA_UNIDADES, caminho)
            app.text_input(key="captacao_unidades_responsavel").set_value("Maria")
            app = _rodar(app, caminho)
            [t for t in app.text_input if t.label == "Código da UGR"][0].set_value("0158001")
            [t for t in app.text_input if t.label == "Nome"][0].set_value("Departamento de Agronomia")
            app = _rodar(app, caminho)
            _botao(app, "Incluir").click()
            app = _rodar(app, caminho)
            self.assertEqual(len(app.exception), 0)
            conexao = schema.conectar(caminho)
            linha = conexao.execute("SELECT ugr_codigo, nome, ativa FROM unidade").fetchone()
            conexao.close()
            self.assertEqual(tuple(linha), ("0158001", "Departamento de Agronomia", 1))

    def test_edita_e_desativa_pela_pagina(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "captacao.db"
            conexao = schema.conectar(caminho)
            unidades.criar_unidade(conexao, {"ugr_codigo": "A1", "nome": "Antigo"}, "Maria")
            conexao.close()
            app = _abrir(PAGINA_UNIDADES, caminho)
            app.text_input(key="captacao_unidades_responsavel").set_value("Maria")
            app = _rodar(app, caminho)
            [t for t in app.text_input if t.label == "Nome" and t.value == "Antigo"][0].set_value("Novo nome")
            app = _rodar(app, caminho)
            _botao(app, "Salvar alterações").click()
            app = _rodar(app, caminho)
            self.assertTrue(any("nome" in s.value for s in app.success))
            _botao(app, "Desativar unidade").click()
            app = _rodar(app, caminho)
            self.assertEqual(len(app.exception), 0)
            conexao = schema.conectar(caminho)
            linha = conexao.execute("SELECT nome, ativa FROM unidade").fetchone()
            conexao.close()
            self.assertEqual(tuple(linha), ("Novo nome", 0))

    def test_codigo_duplicado_mostra_erro(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "captacao.db"
            conexao = schema.conectar(caminho)
            unidades.criar_unidade(conexao, {"ugr_codigo": "A1", "nome": "Uma"}, "Maria")
            conexao.close()
            app = _abrir(PAGINA_UNIDADES, caminho)
            app.text_input(key="captacao_unidades_responsavel").set_value("Maria")
            app = _rodar(app, caminho)
            [t for t in app.text_input if t.label == "Código da UGR" and t.value == ""][0].set_value("A1")
            [t for t in app.text_input if t.label == "Nome" and t.value == ""][0].set_value("Outra")
            app = _rodar(app, caminho)
            _botao(app, "Incluir").click()
            app = _rodar(app, caminho)
            self.assertTrue(any("Já existe" in e.value for e in app.error))


if __name__ == "__main__":
    unittest.main()
