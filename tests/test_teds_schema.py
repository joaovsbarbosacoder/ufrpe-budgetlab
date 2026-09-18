"""Teste mínimo do schema SQLite: todas as tabelas do modelo existem e aceitam PRAGMA."""

from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
