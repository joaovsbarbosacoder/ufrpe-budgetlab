"""Testes dos componentes de layout do módulo de TEDs (`src/teds_ui.py`): marcos da linha do tempo,
soma de documentos (nulo != zero), cobertura do Tesouro Gerencial e o HTML das linhas-cartão.

Só apresentação: nenhum cálculo de negócio novo. Usa banco temporário, nunca `data/teds/teds.db`.
"""

from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from src.teds_schema import conectar
from src.teds_ui import (
    cobertura_tg,
    html_linha,
    marcos_do_ted,
    paginar,
    somar_valores,
    texto_cobertura_tg,
)


class MarcosDoTedTests(unittest.TestCase):
    def test_ordena_cronologicamente_e_resume_primeira_e_ultima(self):
        marcos = marcos_do_ted("2020-12-08", "2024-12-31", ["2023-12-12"], ["2022-01-10", "2021-12-20", None])
        self.assertEqual(
            [(d, r) for d, r, _ in marcos],
            [
                ("2020-12-08", "Início da vigência"),
                ("2021-12-20", "Primeira PF (de 2)"),
                ("2022-01-10", "Última PF"),
                ("2023-12-12", "NC emitida"),
                ("2024-12-31", "Fim da vigência"),
            ],
        )

    def test_documento_sem_data_nao_e_datado_por_inferencia(self):
        self.assertEqual(marcos_do_ted(None, None, [None], [None]), [])


class SomarValoresTests(unittest.TestCase):
    def test_nulo_nao_vira_zero_e_e_contado_a_parte(self):
        soma, sem_valor = somar_valores(["10.50", None, "-0.50", "0"])
        self.assertEqual(soma, Decimal("10.00"))
        self.assertEqual(sem_valor, 1)

    def test_zero_e_negativo_entram_na_soma(self):
        self.assertEqual(somar_valores(["0.00", "-5.00"]), (Decimal("-5.00"), 0))


class CoberturaTgTests(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.conn = conectar(Path(self.pasta.name) / "teds.db")
        self.addCleanup(self.conn.close)

    def _ne(self, chave_ted: str, numero: str, status: str = "ok"):
        self.conn.execute(
            "INSERT INTO vinculo_ne (chave_ted, chave_empenho, ug_emitente, gestao_emitente, numero_ne, valor_ne, "
            "status_validacao, import_batch_id, linha_origem) VALUES (?, ?, '153165', '15239', ?, '100.00', ?, 1, '1')",
            (chave_ted, f"153165|15239|{numero}", numero, status),
        )

    def _tg(self, numero: str):
        self.conn.execute(
            "INSERT INTO execucao_tg (numero_completo_ne, empenhado, liquidado, pago, ano_lancamento, mes_lancamento, "
            "import_batch_id, linha_origem) VALUES (?, '100.00', '50.00', '25.00', 2024, 1, 1, '1')",
            (numero,),
        )

    def test_sem_extracao_sincronizada(self):
        self._ne("1|A", "2023NE000001")
        anos, numeros, sem_linha = cobertura_tg(self.conn, "1|A")
        self.assertIn("Nenhuma extração", texto_cobertura_tg(anos, numeros, sem_linha))

    def test_ne_de_ano_fora_da_cobertura_e_explicada(self):
        self._ne("1|A", "2023NE000001")
        self._tg("2024NE000009")
        self._tg("2026NE000009")
        mensagem = texto_cobertura_tg(*cobertura_tg(self.conn, "1|A"))
        self.assertIn("2024 a 2026", mensagem)
        self.assertIn("2023", mensagem)

    def test_cobertura_parcial_avisa_que_totais_consideram_so_parte_das_nes(self):
        self._ne("1|A", "2024NE000001")
        self._ne("1|A", "2023NE000002")
        self._tg("2024NE000001")
        mensagem = texto_cobertura_tg(*cobertura_tg(self.conn, "1|A"))
        self.assertIn("1 de 2", mensagem)

    def test_cobertura_completa_nao_gera_aviso(self):
        self._ne("1|A", "2024NE000001")
        self._tg("2024NE000001")
        self.assertIsNone(texto_cobertura_tg(*cobertura_tg(self.conn, "1|A")))

    def test_ted_sem_ne_contabilizavel(self):
        self._ne("1|A", "2024NE000001", status="pendente")
        self._tg("2024NE000001")
        self.assertIn("não tem NE contabilizável", texto_cobertura_tg(*cobertura_tg(self.conn, "1|A")))


class PaginarTests(unittest.TestCase):
    def test_fatia_da_pagina_e_total(self):
        self.assertEqual(paginar(89, 25, 1), (1, 4, 0, 25))
        self.assertEqual(paginar(89, 25, 4), (4, 4, 75, 89))

    def test_pagina_fora_do_intervalo_e_corrigida(self):
        self.assertEqual(paginar(10, 25, 7), (1, 1, 0, 10))
        self.assertEqual(paginar(89, 25, 0)[0], 1)

    def test_sem_registros_nao_quebra(self):
        self.assertEqual(paginar(0, 25, 1), (1, 1, 0, 0))


class HtmlLinhaTests(unittest.TestCase):
    def test_escapa_texto_livre_e_omite_metricas_vazias(self):
        html = html_linha("<b>TED</b>", "desc & mais", [], [])
        self.assertIn("&lt;b&gt;TED&lt;/b&gt;", html)
        self.assertIn("desc &amp; mais", html)
        self.assertNotIn("teds-hero", html)

    def test_metricas_aparecem_rotuladas(self):
        html = html_linha("TED 1", None, [], [("NC líquida", "R$ 1,00")])
        self.assertIn("NC líquida", html)
        self.assertIn("R$ 1,00", html)


if __name__ == "__main__":
    unittest.main()
