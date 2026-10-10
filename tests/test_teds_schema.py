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

    def test_conexao_espera_o_bloqueio_do_banco_por_30_segundos(self):
        # Vários servidores Streamlit compartilham o arquivo; o padrão de 5 s gerava "database is locked".
        conn = conectar(":memory:")
        try:
            self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 30000)
        finally:
            conn.close()

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


_DDL_EXECUCAO_TG_ANTIGO = """
CREATE TABLE execucao_tg (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_completo_ne TEXT NOT NULL,
    favorecido TEXT,
    descricao TEXT,
    empenhado TEXT,
    liquidado TEXT,
    pago TEXT,
    documento_habil TEXT,
    documento_contabil TEXT,
    ano_competencia INTEGER,
    mes_competencia INTEGER,
    valor_competencia TEXT,
    import_batch_id INTEGER NOT NULL,
    linha_origem TEXT NOT NULL,
    UNIQUE (numero_completo_ne, documento_habil, documento_contabil, ano_competencia, mes_competencia)
)
"""


def _colunas(conn: sqlite3.Connection, tabela: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({tabela})").fetchall()}


class MigracaoExecucaoTgTests(unittest.TestCase):
    """`execucao_tg` do layout antigo (documento hábil/contábil/competência) -> layout atual (NE x
    mês de lançamento). Nunca descarta dado financeiro em silêncio."""

    def test_banco_novo_ja_nasce_no_layout_de_lancamento(self):
        conn = conectar(":memory:")
        try:
            colunas = _colunas(conn, "execucao_tg")
            self.assertTrue({"ano_lancamento", "mes_lancamento"}.issubset(colunas))
            self.assertTrue({"documento_habil", "documento_contabil", "ano_competencia",
                             "mes_competencia", "valor_competencia"}.isdisjoint(colunas))
        finally:
            conn.close()

    def _banco_antigo(self, tmp: str, linhas: int) -> Path:
        caminho = Path(tmp) / "teds_antigo.db"
        antigo = sqlite3.connect(caminho)
        antigo.execute(_DDL_EXECUCAO_TG_ANTIGO)
        for i in range(linhas):
            antigo.execute(
                "INSERT INTO execucao_tg (numero_completo_ne, empenhado, documento_habil, "
                "ano_competencia, mes_competencia, import_batch_id, linha_origem) "
                "VALUES (?, '100.00', 'DH1', 2026, 8, 1, '{}')", (f"2026NE00000{i}",),
            )
        antigo.commit()
        antigo.close()
        return caminho

    def test_tabela_antiga_vazia_e_recriada_no_layout_novo(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = conectar(self._banco_antigo(tmp, linhas=0))
            try:
                self.assertIn("ano_lancamento", _colunas(conn, "execucao_tg"))
                self.assertNotIn("documento_habil", _colunas(conn, "execucao_tg"))
                nomes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertNotIn("execucao_tg_legado", nomes)
            finally:
                conn.close()

    def test_tabela_antiga_com_linhas_e_preservada_como_legado(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = conectar(self._banco_antigo(tmp, linhas=2))
            try:
                self.assertIn("ano_lancamento", _colunas(conn, "execucao_tg"))
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM execucao_tg").fetchone()[0], 0)
                legado = conn.execute(
                    "SELECT numero_completo_ne, empenhado, documento_habil FROM execucao_tg_legado ORDER BY 1"
                ).fetchall()
                self.assertEqual(legado, [("2026NE000000", "100.00", "DH1"), ("2026NE000001", "100.00", "DH1")])
            finally:
                conn.close()

    def test_migracao_e_idempotente_e_nao_repete_o_legado(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = self._banco_antigo(tmp, linhas=1)
            conectar(caminho).close()
            conn = conectar(caminho)
            try:
                nomes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("execucao_tg_legado", nomes)
                self.assertNotIn("execucao_tg_legado_2", nomes)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM execucao_tg_legado").fetchone()[0], 1)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
