"""Testes da camada de interface da projeção editável (`src/ui_projecao_execucao.py`): funções puras."""

from __future__ import annotations

import unittest

import pandas as pd

from src.relatorio_necessidade_empenho import necessidade_por_ne
from src.relatorio_projecao_execucao import montar_relatorio
from src.ui_projecao_execucao import (
    html_legenda,
    html_matriz,
    ler_valor_brl,
    meses_editaveis,
    titulo_contrato,
    valores_para_gravar,
)

NE = "2026NE000001"


def _linha(**campos):
    base = {
        "ne_curta": NE, "fornecedor": "Estável & Cia <Ltda>", "contrato_numero": "10/2025", "despesa_mensal": 1000.0,
        "meses_no_ano": 12.0, "valor_empenhado": 0.0, "valor_empenhado_execucao": 9000.0,
        "valor_empenhado_planilha_total_ne": None, "valor_liquidado_execucao": 6300.0,
        "liquidado_via_competencia": True, "saldo_execucao": None, "saldo_colado_planilha": None,
        "status_contrato": "ATIVO", "vigencia_fim": pd.NaT,
    }
    base.update(campos)
    return base


def _relatorio(ajustes=None):
    por_ne, sem_ne = necessidade_por_ne(pd.DataFrame([_linha()]), None, 2026)
    liquidacao = pd.DataFrame({"ne_curta": [NE] * 7, "ano_mes": [202601 + i for i in range(7)], "valor": [900.0] * 7})
    return montar_relatorio(por_ne, sem_ne, liquidacao, 2026, 10, ajustes=ajustes)


class TestLerValorBrl(unittest.TestCase):
    def test_formatos_aceitos(self):
        for texto in ("1.234,56", "1234,56", "1234.56", " R$ 1.234,56 ", "1.234.567,89"):
            with self.subTest(texto=texto):
                esperado = 1234567.89 if texto.endswith("567,89") else 1234.56
                self.assertAlmostEqual(ler_valor_brl(texto), esperado)

    def test_ponto_de_milhar_sem_decimais(self):
        self.assertEqual(ler_valor_brl("1.234"), 1234.0)
        self.assertEqual(ler_valor_brl("12.345.678"), 12345678.0)

    def test_vazio_e_none_e_zero_e_zero(self):
        self.assertIsNone(ler_valor_brl(""))
        self.assertIsNone(ler_valor_brl("   "))
        self.assertEqual(ler_valor_brl("0"), 0.0)
        self.assertEqual(ler_valor_brl("0,00"), 0.0)

    def test_invalidos(self):
        for texto in ("abc", "-5", "-0,01", "nan", "inf", "1,2,3", "12a"):
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                ler_valor_brl(texto)


class TestTituloContrato(unittest.TestCase):
    def test_numero_e_fornecedor(self):
        self.assertEqual(titulo_contrato("10/2025", "Serval"), "Contrato 10/2025 — Serval")

    def test_faltando_dados(self):
        self.assertEqual(titulo_contrato(None, "Serval"), "Contrato — — Serval")
        self.assertEqual(titulo_contrato("10/2025", ""), "Contrato 10/2025 — (sem fornecedor)")


class TestValoresParaGravar(unittest.TestCase):
    METOD = {9: 900.0, 10: 900.0, 11: None}

    def test_sem_mudanca_nao_grava(self):
        self.assertEqual(valores_para_gravar({9: "", 10: ""}, {}, self.METOD), {})

    def test_igual_a_metodologia_sem_ajuste_previo_nao_grava(self):
        self.assertEqual(valores_para_gravar({9: "900,00"}, {}, self.METOD), {})

    def test_igual_a_metodologia_com_ajuste_previo_remove_o_ajuste(self):
        self.assertEqual(valores_para_gravar({9: "900,00"}, {9: 700.0}, self.METOD), {9: None})

    def test_campo_vazio_com_ajuste_previo_remove_o_ajuste(self):
        self.assertEqual(valores_para_gravar({9: ""}, {9: 700.0}, self.METOD), {9: None})

    def test_novo_valor_e_gravado_e_zero_tambem(self):
        self.assertEqual(valores_para_gravar({9: "1.000,50", 10: "0"}, {}, self.METOD), {9: 1000.5, 10: 0.0})

    def test_igual_ao_vigente_nao_grava(self):
        self.assertEqual(valores_para_gravar({9: "700,00"}, {9: 700.0}, self.METOD), {})

    def test_mes_vazio_da_metodologia_aceita_valor(self):
        self.assertEqual(valores_para_gravar({11: "300"}, {}, self.METOD), {11: 300.0})

    def test_texto_invalido_levanta_com_o_mes(self):
        with self.assertRaises(ValueError) as erro:
            valores_para_gravar({10: "abc"}, {}, self.METOD)
        self.assertIn("out", str(erro.exception).lower())


class TestMesesEditaveis(unittest.TestCase):
    def test_do_primeiro_mes_aberto_a_dezembro(self):
        self.assertEqual(meses_editaveis(_relatorio()), [8, 9, 10, 11, 12])

    def test_exercicio_encerrado_nao_edita(self):
        por_ne, sem_ne = necessidade_por_ne(pd.DataFrame([_linha()]), None, 2026)
        encerrado = montar_relatorio(por_ne, sem_ne, None, 2026, 12)
        self.assertEqual(meses_editaveis(encerrado), [])


class TestHtml(unittest.TestCase):
    def test_matriz_traz_titulo_do_contrato_marca_e_total(self):
        html = html_matriz(_relatorio({NE: {12: 5000.0}}))
        self.assertIn("<b>10/2025</b>", html)
        self.assertIn(NE, html)
        self.assertIn("✎", html)
        self.assertIn("Total", html)
        self.assertIn("k-aberto", html)  # ago/set em aberto
        self.assertIn("k-real", html)

    def test_matriz_sem_ajuste_nao_tem_marca(self):
        self.assertNotIn("✎", html_matriz(_relatorio()))

    def test_matriz_escapa_texto(self):
        html = html_matriz(_relatorio())
        self.assertIn("Estável &amp; Cia &lt;Ltda&gt;", html)
        self.assertNotIn("<Ltda>", html)

    def test_title_da_celula_mostra_esperado_liquidado_e_projetado(self):
        html = html_matriz(_relatorio({NE: {12: 5000.0}}))
        self.assertIn("esperado", html)
        self.assertIn("liquidado", html)
        self.assertIn("projetado", html)

    def test_legenda(self):
        legenda = html_legenda()
        for texto in ("Realizado", "Projetado", "em aberto", "✎", "*"):
            self.assertIn(texto, legenda)


if __name__ == "__main__":
    unittest.main()
