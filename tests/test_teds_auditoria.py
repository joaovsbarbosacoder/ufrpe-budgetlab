"""
Testes da trilha de auditoria (`src/teds_auditoria.py`, briefing seção 16): registro append-only,
gravado na MESMA transação da alteração auditada, com valor anterior, valor novo, usuário,
motivo e origem.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.teds_alertas import registrar_decisao_vinculo_ne
from src.teds_auditoria import (
    ACAO_ALERTA_STATUS_ALTERADO,
    ACAO_VINCULO_NE_DECIDIDO,
    ENTIDADE_ALERTA,
    ENTIDADE_VINCULO_NE,
    USUARIO_NAO_INFORMADO,
    historico_auditoria,
    registrar_auditoria,
)
from src.teds_normalizacao import chave_empenho, chave_ted
from src.teds_schema import conectar
from src.teds_ui import STATUS_EM_ANALISE, STATUS_RESOLVIDO, atualizar_status_alerta

TED_A = chave_ted("17352", "1ABDKU")
TED_B = chave_ted("17454", "1ABDKQ")
NE_422 = chave_empenho("153165", "15239", "2026NE000422")


class RegistroTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_registra_e_le_de_volta_com_json(self):
        registrar_auditoria(
            self.conn, acao="x", entidade="alerta", entidade_id=7,
            valor_anterior={"status": "aberto"}, valor_novo={"status": "resolvido", "responsavel": "Ana"},
            usuario="Ana", motivo="  conferido  ", origem="teste", commit=True,
        )
        (registro,) = historico_auditoria(self.conn, "alerta", 7)
        self.assertEqual(registro.usuario, "Ana")
        self.assertEqual(registro.motivo, "conferido")
        self.assertEqual(registro.origem, "teste")
        self.assertEqual(registro.valor_anterior, {"status": "aberto"})
        self.assertEqual(registro.valor_novo["responsavel"], "Ana")
        self.assertTrue(registro.data_hora)

    def test_usuario_ausente_vira_nao_informado_e_motivo_vazio_vira_none(self):
        registrar_auditoria(
            self.conn, acao="x", entidade="alerta", entidade_id=1,
            valor_anterior=None, valor_novo=None, usuario="  ", motivo="", commit=True,
        )
        (registro,) = historico_auditoria(self.conn, "alerta", 1)
        self.assertEqual(registro.usuario, USUARIO_NAO_INFORMADO)
        self.assertIsNone(registro.motivo)
        self.assertIsNone(registro.valor_anterior)

    def test_historico_e_por_entidade_e_em_ordem_cronologica(self):
        for entidade_id, acao in ((1, "a"), (2, "b"), (1, "c")):
            registrar_auditoria(
                self.conn, acao=acao, entidade="alerta", entidade_id=entidade_id,
                valor_anterior=None, valor_novo=None, commit=True,
            )
        self.assertEqual([r.acao for r in historico_auditoria(self.conn, "alerta", 1)], ["a", "c"])
        self.assertEqual(historico_auditoria(self.conn, "vinculo_ne", 1), [])

    def test_sem_commit_a_auditoria_acompanha_o_rollback(self):
        registrar_auditoria(
            self.conn, acao="x", entidade="alerta", entidade_id=1, valor_anterior=None, valor_novo=None
        )
        self.conn.rollback()
        self.assertEqual(historico_auditoria(self.conn, "alerta", 1), [])


class ImutabilidadeTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")
        registrar_auditoria(
            self.conn, acao="x", entidade="alerta", entidade_id=1, valor_anterior=None, valor_novo=None, commit=True
        )

    def tearDown(self):
        self.conn.close()

    def test_update_e_bloqueado(self):
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE auditoria SET usuario = 'outra pessoa'")
        self.assertEqual(historico_auditoria(self.conn, "alerta", 1)[0].usuario, USUARIO_NAO_INFORMADO)

    def test_delete_e_bloqueado(self):
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("DELETE FROM auditoria")
        self.assertEqual(len(historico_auditoria(self.conn, "alerta", 1)), 1)


class MigracaoTests(unittest.TestCase):
    def test_banco_antigo_sem_auditoria_ganha_a_tabela_sem_perder_alertas(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "teds.db"
            antigo = sqlite3.connect(caminho)
            antigo.executescript(
                """
                CREATE TABLE alerta (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, gravidade TEXT NOT NULL,
                    chave_ted TEXT, documento TEXT, descricao TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'aberto',
                    data_identificacao TEXT NOT NULL, responsavel TEXT, justificativa TEXT, data_resolucao TEXT
                );
                INSERT INTO alerta (tipo, gravidade, documento, descricao, data_identificacao)
                VALUES ('nc_ug_emitente_ausente', 'media', 'doc', 'desc', '2026-01-01');
                """
            )
            antigo.commit()
            antigo.close()

            conn = conectar(caminho)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM alerta").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0], 0)
                conectar(caminho).close()  # idempotente: reabrir não recria nem falha
            finally:
                conn.close()


class StatusDoAlertaTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")
        self.conn.execute(
            "INSERT INTO alerta (id, tipo, gravidade, documento, descricao, data_identificacao) "
            "VALUES (1, 'nc_ug_emitente_ausente', 'media', 'doc', 'desc', '2026-01-01')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_mudanca_de_status_grava_valor_anterior_e_novo(self):
        atualizar_status_alerta(self.conn, 1, STATUS_EM_ANALISE, responsavel="Ana")
        (registro,) = historico_auditoria(self.conn, ENTIDADE_ALERTA, 1)
        self.assertEqual(registro.acao, ACAO_ALERTA_STATUS_ALTERADO)
        self.assertEqual(registro.usuario, "Ana")
        self.assertEqual(registro.valor_anterior["status"], "aberto")
        self.assertIsNone(registro.valor_anterior["responsavel"])
        self.assertEqual(registro.valor_novo["status"], "em_analise")
        self.assertEqual(registro.valor_novo["responsavel"], "Ana")

    def test_resolver_registra_justificativa_como_motivo_e_preserva_a_historia(self):
        atualizar_status_alerta(self.conn, 1, STATUS_EM_ANALISE, responsavel="Ana")
        atualizar_status_alerta(self.conn, 1, STATUS_RESOLVIDO, responsavel="Bia", justificativa="Conferido na origem")
        historico = historico_auditoria(self.conn, ENTIDADE_ALERTA, 1)
        self.assertEqual([r.valor_novo["status"] for r in historico], ["em_analise", "resolvido"])
        self.assertEqual(historico[1].motivo, "Conferido na origem")
        self.assertEqual(historico[1].valor_anterior["responsavel"], "Ana")
        self.assertEqual(historico[1].valor_novo["responsavel"], "Bia")
        # A justificativa encerra o alerta, mas o alerta continua existindo (não é apagado).
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM alerta").fetchone()[0], 1)

    def test_status_sem_responsavel_e_registrado_como_nao_informado(self):
        atualizar_status_alerta(self.conn, 1, STATUS_EM_ANALISE)
        self.assertEqual(historico_auditoria(self.conn, ENTIDADE_ALERTA, 1)[0].usuario, USUARIO_NAO_INFORMADO)

    def test_alerta_inexistente_nao_grava_auditoria(self):
        atualizar_status_alerta(self.conn, 999, STATUS_EM_ANALISE)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0], 0)

    def test_regra_de_vinculo_multiplo_nao_pode_ser_resolvida_sem_decisao_e_nao_audita(self):
        self.conn.execute("UPDATE alerta SET tipo = 'empenho_multiplos_teds' WHERE id = 1")
        self.conn.commit()
        with self.assertRaises(ValueError):
            atualizar_status_alerta(self.conn, 1, STATUS_RESOLVIDO, justificativa="x")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0], 0)


class DecisaoDeVinculoTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")
        self.conn.execute(
            "INSERT INTO import_batch (id, tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, status) "
            "VALUES (1, 'teste', 'x.xlsx', 'hash', '2026-01-01T00:00:00', 'ok')"
        )
        for ted in (TED_A, TED_B):
            self.conn.execute(
                "INSERT INTO vinculo_ne (chave_ted, chave_empenho, ug_emitente, gestao_emitente, numero_ne, "
                "valor_ne, status_validacao, import_batch_id, linha_origem) "
                "VALUES (?, ?, '153165', '15239', '2026NE000422', '388300.00', 'pendente', 1, '{}')",
                (ted, NE_422),
            )
        self.conn.execute(
            "INSERT INTO alerta (id, tipo, gravidade, documento, descricao, data_identificacao) "
            "VALUES (1, 'empenho_multiplos_teds', 'alta', ?, 'desc', '2026-01-01')",
            (NE_422,),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _decidir(self, **extra):
        return registrar_decisao_vinculo_ne(
            self.conn, alerta_id=1, chave_empenho=NE_422, chave_ted_escolhida=TED_A,
            responsavel="Ana", justificativa="Descrição da NE cita o TED 17352", **extra,
        )

    def test_decisao_gera_auditoria_do_vinculo_e_do_alerta(self):
        self._decidir(origem="teste")
        (vinculo,) = historico_auditoria(self.conn, ENTIDADE_VINCULO_NE, NE_422)
        self.assertEqual(vinculo.acao, ACAO_VINCULO_NE_DECIDIDO)
        self.assertEqual(vinculo.usuario, "Ana")
        self.assertEqual(vinculo.origem, "teste")
        self.assertEqual(vinculo.motivo, "Descrição da NE cita o TED 17352")
        self.assertEqual(
            vinculo.valor_anterior["status_validacao_por_ted"], {TED_A: "pendente", TED_B: "pendente"}
        )
        self.assertEqual(vinculo.valor_novo["status_validacao_por_ted"], {TED_A: "ok", TED_B: "descartado"})
        self.assertEqual(vinculo.valor_novo["ted_escolhido"], TED_A)

        (alerta,) = historico_auditoria(self.conn, ENTIDADE_ALERTA, 1)
        self.assertEqual(alerta.valor_anterior["status"], "aberto")
        self.assertEqual(alerta.valor_novo["status"], "resolvido")

    def test_decisao_recusada_nao_deixa_auditoria(self):
        with self.assertRaises(ValueError):
            registrar_decisao_vinculo_ne(
                self.conn, alerta_id=1, chave_empenho=NE_422, chave_ted_escolhida=TED_A,
                responsavel="", justificativa="x",
            )
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0], 0)

    def test_falha_no_meio_da_decisao_desfaz_tambem_a_auditoria(self):
        # Sabota a gravação da auditoria: a decisão inteira (vínculos + alerta) deve reverter.
        self.conn.execute("DROP TRIGGER trg_auditoria_sem_update")
        self.conn.execute("ALTER TABLE auditoria RENAME TO auditoria_quebrada")
        self.conn.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self._decidir()
        status = dict(self.conn.execute("SELECT chave_ted, status_validacao FROM vinculo_ne").fetchall())
        self.assertEqual(status, {TED_A: "pendente", TED_B: "pendente"})
        self.assertEqual(self.conn.execute("SELECT status FROM alerta WHERE id = 1").fetchone()[0], "aberto")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM decisao_vinculo_ne").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
