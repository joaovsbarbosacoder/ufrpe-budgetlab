"""Testes da camada de interface da projeção editável (`src/ui_projecao_execucao.py`): funções puras."""

from __future__ import annotations

import unittest

import pandas as pd

from src.relatorio_necessidade_empenho import necessidade_por_ne
from src.relatorio_projecao_execucao import montar_relatorio
from src.relatorio_projecao_execucao import BOLSAS_AUXILIOS, CONTRATOS
from src.ui_projecao_execucao import (
    CSS,
    formatar_quantidade,
    html_legenda,
    html_matriz,
    ler_valor_brl,
    meses_editaveis,
    quantidade_de_valor,
    quantidade_inteira,
    titulo_contrato,
    titulo_documento,
    valor_de_quantidade,
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

    def test_formato_ingles_com_virgula_de_milhar_e_recusado(self):
        for texto in ("1,234.56", "12,345,678.90", "1,234.5"):
            with self.subTest(texto=texto), self.assertRaises(ValueError):
                ler_valor_brl(texto)

    def test_zero_a_esquerda_e_decimal_e_nao_milhar(self):
        self.assertEqual(ler_valor_brl("0.500"), 0.5)
        self.assertEqual(ler_valor_brl("0.125"), 0.125)
        self.assertEqual(ler_valor_brl("1.500"), 1500.0)

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


class TestBolsasQuantidadeEValor(unittest.TestCase):
    """15/10/2026: em Bolsas e Auxílios o valor (R$) e a quantidade de bolsas se vinculam pelo valor de UMA bolsa."""

    def test_quantidade_de_valor(self):
        self.assertEqual(quantidade_de_valor(1200.0, 400.0), 3.0)
        self.assertEqual(quantidade_de_valor(1000.0, 400.0), 2.5)
        self.assertEqual(quantidade_de_valor(0.0, 400.0), 0.0)  # zero é valor, não ausência
        self.assertAlmostEqual(quantidade_de_valor(100.0, 300.0), 0.3333)  # 4 casas

    def test_sem_unidade_valida_nao_ha_quantidade(self):
        for unidade in (None, 0.0, -5.0):
            with self.subTest(unidade=unidade):
                self.assertIsNone(quantidade_de_valor(1200.0, unidade))
                self.assertIsNone(valor_de_quantidade(3.0, unidade))
        self.assertIsNone(quantidade_de_valor(None, 400.0))
        self.assertIsNone(valor_de_quantidade(None, 400.0))

    def test_valor_de_quantidade(self):
        self.assertEqual(valor_de_quantidade(3.0, 400.0), 1200.0)
        self.assertEqual(valor_de_quantidade(2.5, 400.0), 1000.0)
        self.assertEqual(valor_de_quantidade(0.0, 400.0), 0.0)
        self.assertEqual(valor_de_quantidade(3.0, 333.33), 999.99)  # centavos

    def test_ida_e_volta_nao_perde_centavos_em_bolsa_inteira(self):
        for qtd in (1.0, 7.0, 130.0):
            self.assertEqual(quantidade_de_valor(valor_de_quantidade(qtd, 1400.0), 1400.0), qtd)

    def test_formatar_quantidade_com_menos_casas(self):
        self.assertEqual(formatar_quantidade(3.3333, casas=2), "3,33")
        self.assertEqual(formatar_quantidade(0.7305, casas=2), "0,73")
        self.assertEqual(formatar_quantidade(213.5, casas=2), "213,5")
        self.assertEqual(formatar_quantidade(12.0, casas=2), "12")
        self.assertEqual(formatar_quantidade(0.001, casas=2), "0")  # arredonda para zero sem sobrar "0,00"

    def test_formatar_quantidade(self):
        self.assertEqual(formatar_quantidade(12.0), "12")
        self.assertEqual(formatar_quantidade(12.5), "12,5")
        self.assertEqual(formatar_quantidade(0.3333), "0,3333")
        self.assertEqual(formatar_quantidade(0.0), "0")

    def test_quantidade_inteira_com_tolerancia(self):
        self.assertTrue(quantidade_inteira(12.0))
        self.assertTrue(quantidade_inteira(12.004))
        self.assertFalse(quantidade_inteira(12.5))
        self.assertFalse(quantidade_inteira(0.3333))

    def test_titulo_documento_usa_os_rotulos_da_base(self):
        self.assertEqual(titulo_documento(CONTRATOS, "10/2025", "Serval"), "Contrato 10/2025 — Serval")
        self.assertEqual(titulo_documento(BOLSAS_AUXILIOS, "23096/2026", "Residência"), "Processo 23096/2026 — Residência")
        self.assertEqual(titulo_documento(BOLSAS_AUXILIOS, None, ""), "Processo — — (sem programa)")

    def test_matriz_mostra_bolsas_quando_ha_valor_de_bolsa(self):
        html = html_matriz(_relatorio({NE: {12: 5000.0}}), unidades={NE: 100.0})
        self.assertIn("bolsas", html)  # title da célula com a quantidade
        self.assertIn('<span class="q">50 bolsas</span>', html)  # 5.000 ÷ 100 no mês ajustado

    def test_celula_de_bolsas_tem_duas_linhas_fixas_valor_e_quantidade(self):
        html = html_matriz(_relatorio({NE: {12: 5000.0}}), unidades={NE: 100.0})
        self.assertRegex(html, r'<span class="v">5,0 mil[^<]*</span><span class="q">50 bolsas</span>')
        self.assertNotIn(" · 50 b<", html)  # sem o formato corrido em uma linha só, que quebrava no meio

    def test_quantidade_na_matriz_tem_no_maximo_duas_casas_e_a_dica_a_precisao_total(self):
        # 1.000 ÷ 300 = 3,3333 bolsas: a matriz mostra 3,33 e a dica (title) guarda as 4 casas
        html = html_matriz(_relatorio({NE: {12: 1000.0}}), unidades={NE: 300.0})
        self.assertIn('<span class="q">3,33 bolsas</span>', html)
        self.assertIn("3,3333 bolsas", html)

    def test_total_da_linha_mostra_a_quantidade_de_bolsas(self):
        html = html_matriz(_relatorio({NE: {12: 5000.0}}), unidades={NE: 100.0})
        total = html.split("</td></tr>")[0].rsplit('<td class="tt">', 1)[1]  # total da linha da NE
        self.assertIn('<span class="q">', total)
        self.assertIn("bolsas", total)

    def test_coluna_executado_mais_projetado_soma_o_liquidado_ao_projetado(self):
        # 7 meses liquidados de 900 = 6,3 mil; projetado até dez. = 4,5 mil -> 10,8 mil
        html = html_matriz(_relatorio())
        self.assertIn("<th>Executado + projetado</th>", html)
        linha_total = html.split('<tr class="tot">')[1]
        self.assertTrue(linha_total.endswith("<td>4,5 mil</td><td>10,8 mil</td></tr></tbody></table></div>"))
        linha_ne = html.split("</td></tr>")[0].rsplit('<td class="tt">', 1)[1]
        self.assertIn("10,8 mil", linha_ne)

    def test_celulas_nao_quebram_no_meio(self):
        self.assertIn("white-space:nowrap", CSS)

    def test_nome_longo_fica_em_duas_linhas_e_a_dica_traz_o_texto_completo(self):
        self.assertIn("-webkit-line-clamp:2", CSS)
        html = html_matriz(_relatorio())
        # a dica (title) da primeira coluna traz o título completo, já escapado
        self.assertIn('<td class="t" title="10/2025 — Estável &amp; Cia &lt;Ltda&gt; — 2026NE000001">', html)

    def test_tabela_fica_num_conteiner_com_rolagem_horizontal(self):
        # com 12 meses + total a tabela pode passar da largura da página: rola em vez de ser cortada
        html = html_matriz(_relatorio(), unidades={NE: 100.0})
        self.assertTrue(html.startswith('<div class="pe-rolagem"><table class="pe-m">'))
        self.assertTrue(html.endswith("</table></div>"))
        self.assertIn("overflow-x:auto", CSS)

    def test_matriz_sem_unidade_nao_mostra_bolsas(self):
        self.assertNotIn("bolsas", html_matriz(_relatorio({NE: {12: 5000.0}})))


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

    def test_com_ne_inclui_meses_fechados_sem_execucao(self):
        # 16/10/2026: jun sem registro e jul zerado (meses fechados sem execução) passam a ser editáveis; os demais
        # meses fechados têm liquidação e continuam fora
        relatorio = _relatorio()
        indice = relatorio.linhas.index[0]
        relatorio.mensal.at[indice, "r6"] = float("nan")
        relatorio.mensal.at[indice, "r7"] = 0.0
        self.assertEqual(meses_editaveis(relatorio, indice), [6, 7, 8, 9, 10, 11, 12])
        self.assertEqual(meses_editaveis(relatorio), [8, 9, 10, 11, 12])  # sem NE: só os abertos

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
