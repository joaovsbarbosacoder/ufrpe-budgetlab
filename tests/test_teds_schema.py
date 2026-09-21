"""Teste mínimo do schema SQLite: todas as tabelas do modelo existem e aceitam PRAGMA."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.teds_schema import conectar

TABELAS_ESPERADAS = {
    "import_batch",
    "ted",
    "execucao_anual",
    "documento_nc",
    "documento_nc_linha",
    "documento_pf",
    "vinculo_ne",
    "execucao_tg",
    "alerta",
    "decisao_vinculo_ne",
}


class SchemaTests(unittest.TestCase):
    def test_todas_as_tabelas_do_modelo_sao_criadas(self):
        conn = conectar(":memory:")
        try:
            nomes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            self.assertTrue(TABELAS_ESPERADAS.issubset(nomes))
        finally:
            conn.close()

    def test_conectar_e_idempotente(self):
        conn = conectar(":memory:")
        conn2 = conectar(":memory:")
        try:
            self.assertIsNotNone(conn)
            self.assertIsNotNone(conn2)
        finally:
            conn.close()
            conn2.close()

    def test_banco_novo_ja_tem_colunas_de_total_de_controle(self):
        # Regra 6.2 do briefing: as colunas de total de controle existem mesmo num banco criado
        # do zero (não só como resultado da migração de um banco antigo).
        conn = conectar(":memory:")
        try:
            colunas = {row[1] for row in conn.execute("PRAGMA table_info(import_batch)").fetchall()}
            self.assertTrue(
                {
                    "quantidade_linhas_lidas", "quantidade_rejeitadas", "quantidade_com_aviso",
                    "soma_bruta", "soma_positiva", "soma_negativa", "soma_liquida",
                }.issubset(colunas)
            )
        finally:
            conn.close()

    def test_migracao_preserva_lotes_gravados_antes_das_colunas_de_controle(self):
        # Simula um `data/teds/teds.db` gravado antes desta rodada (schema antigo de
        # `import_batch`, sem as colunas de total de controle) — `conectar()` precisa migrar
        # via `ALTER TABLE` sem apagar o lote já existente.
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "teds_antigo.db"
            conexao_antiga = sqlite3.connect(caminho)
            conexao_antiga.execute(
                """
                CREATE TABLE import_batch (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo_relatorio TEXT NOT NULL,
                    nome_arquivo TEXT NOT NULL,
                    hash_arquivo TEXT NOT NULL,
                    data_importacao TEXT NOT NULL,
                    quantidade_registros INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    mensagem_erro TEXT
                )
                """
            )
            conexao_antiga.execute(
                "INSERT INTO import_batch (tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, "
                "quantidade_registros, status) VALUES ('simec_doc_nc', 'extrato (1).xlsx', 'abc123', "
                "'2026-01-01T00:00:00+00:00', 179, 'ok')"
            )
            conexao_antiga.commit()
            conexao_antiga.close()

            conn = conectar(caminho)
            try:
                lote = conn.execute(
                    "SELECT nome_arquivo, quantidade_registros, quantidade_linhas_lidas, soma_liquida "
                    "FROM import_batch"
                ).fetchone()
                self.assertEqual(lote[0], "extrato (1).xlsx")
                self.assertEqual(lote[1], 179)
                self.assertIsNone(lote[2])
                self.assertIsNone(lote[3])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
