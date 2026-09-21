"""Testes de `src/teds_normalizacao.py` — conversão de valor/data/código e chaves naturais."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

import pandas as pd

from src.teds_normalizacao import (
    chave_empenho,
    chave_nc,
    chave_nc_documento,
    chave_nc_linha,
    chave_pf,
    chave_ted,
    codigo_coluna,
    data_para_texto,
    decompor_numero_ne,
    normalizar_codigo,
    normalizar_nome_coluna,
    normalizar_operacao,
    parse_data_br,
    parse_valor_brl,
    sinal_operacao,
    texto_para_valor,
    valor_assinado,
    valor_para_texto,
)


class ParseValorBrlTests(unittest.TestCase):
    def test_milhar_e_decimal_brasileiros(self):
        self.assertEqual(parse_valor_brl("5.076.636,25"), Decimal("5076636.25"))
        self.assertEqual(parse_valor_brl("R$ 2.748.263,99"), Decimal("2748263.99"))

    def test_negativo_com_sinal(self):
        self.assertEqual(parse_valor_brl("-19.902,91"), Decimal("-19902.91"))

    def test_numero_ja_convertido_passa_direto(self):
        self.assertEqual(parse_valor_brl(388300), Decimal("388300.00"))
        self.assertEqual(parse_valor_brl(388300.5), Decimal("388300.50"))
        self.assertEqual(parse_valor_brl(Decimal("1.50")), Decimal("1.50"))

    def test_vazio_e_invalido(self):
        with self.assertRaises(ValueError):
            parse_valor_brl("")
        with self.assertRaises(ValueError):
            parse_valor_brl("abc")

    def test_roundtrip_texto_persistencia(self):
        valor = Decimal("388300.00")
        self.assertEqual(texto_para_valor(valor_para_texto(valor)), valor)


class SinalOperacaoTests(unittest.TestCase):
    def test_positivo(self):
        self.assertEqual(sinal_operacao("(+)"), 1)
        self.assertEqual(sinal_operacao("+"), 1)

    def test_negativo(self):
        self.assertEqual(sinal_operacao("(-)"), -1)
        self.assertEqual(sinal_operacao(" - "), -1)

    def test_operacao_ausente_ou_desconhecida(self):
        with self.assertRaises(ValueError):
            sinal_operacao("")
        with self.assertRaises(ValueError):
            sinal_operacao("outra coisa")

    def test_valor_assinado_aplica_sinal(self):
        self.assertEqual(valor_assinado(Decimal("19902.91"), "(-)"), Decimal("-19902.91"))
        self.assertEqual(valor_assinado(Decimal("388300.00"), "(+)"), Decimal("388300.00"))


class ParseDataBrTests(unittest.TestCase):
    def test_data_valida(self):
        self.assertEqual(parse_data_br("31/08/2026"), date(2026, 8, 31))

    def test_vazio_vira_none(self):
        self.assertIsNone(parse_data_br(""))
        self.assertIsNone(parse_data_br(None))

    def test_formato_invalido_levanta_erro(self):
        with self.assertRaises(ValueError):
            parse_data_br("2026-08-31")

    def test_data_para_texto(self):
        self.assertEqual(data_para_texto(date(2026, 8, 31)), "2026-08-31")
        self.assertIsNone(data_para_texto(None))


class NormalizarCodigoTests(unittest.TestCase):
    def test_float_integral_vira_inteiro_em_texto(self):
        self.assertEqual(normalizar_codigo(153165.0), "153165")

    def test_preserva_zeros_a_esquerda_quando_ja_texto(self):
        self.assertEqual(normalizar_codigo("015239"), "015239")

    def test_none_vira_vazio(self):
        self.assertEqual(normalizar_codigo(None), "")

    def test_codigo_alfanumerico_vira_maiusculo(self):
        # regra 3.1 do briefing: "1abdku" -> "1ABDKU".
        self.assertEqual(normalizar_codigo("1abdku"), "1ABDKU")
        self.assertEqual(normalizar_codigo("2026ne000422"), "2026NE000422")

    def test_codigo_ja_maiusculo_nao_muda(self):
        self.assertEqual(normalizar_codigo("2026NE000422"), "2026NE000422")


class NormalizarNomeColunaTests(unittest.TestCase):
    def test_variacoes_de_acento_espaco_e_caixa_sao_equivalentes(self):
        self.assertEqual(
            normalizar_nome_coluna("Início da Vigência"),
            normalizar_nome_coluna("inicio   da vigencia"),
        )

    def test_tolera_sufixo_monetario_r_cifrao(self):
        # A extração real do SIMEC usa "(R$)" em algumas colunas de valor e não em outras
        # para o mesmo tipo de campo — a coluna com sufixo tem que casar com o alias sem ele.
        self.assertEqual(
            normalizar_nome_coluna("Total Descentralizado (R$)"),
            normalizar_nome_coluna("Total Descentralizado"),
        )
        self.assertEqual(
            normalizar_nome_coluna("Valor Doc. PF (R$)"),
            normalizar_nome_coluna("Valor Doc. PF"),
        )

    def test_sufixo_monetario_so_e_removido_no_final(self):
        # "(R$)" no meio do nome não deveria ser tratado como o sufixo monetário.
        self.assertNotEqual(
            normalizar_nome_coluna("Total (R$) Descentralizado"),
            normalizar_nome_coluna("Total Descentralizado"),
        )


class CodigoColunaTests(unittest.TestCase):
    def _linha(self, valor):
        return pd.Series({"TED": valor})

    def test_float_integral_sem_sufixo_ponto_zero(self):
        # Bug real: o Excel/pandas costuma entregar TED/UG/Gestão como float (12112.0) quando
        # a coluna é puramente numérica — a chave não pode carregar o ".0".
        colunas = {"ted": "TED"}
        self.assertEqual(codigo_coluna(self._linha(12112.0), colunas, "ted"), "12112")
        self.assertEqual(codigo_coluna(self._linha(153165.0), colunas, "ted"), "153165")
        self.assertEqual(codigo_coluna(self._linha(15239.0), colunas, "ted"), "15239")

    def test_alfanumerico_preservado(self):
        colunas = {"ted": "TED"}
        self.assertEqual(codigo_coluna(self._linha("1AAMVG"), colunas, "ted"), "1AAMVG")

    def test_zeros_a_esquerda_preservados_quando_ja_texto(self):
        colunas = {"ted": "TED"}
        self.assertEqual(codigo_coluna(self._linha("015239"), colunas, "ted"), "015239")

    def test_coluna_nao_mapeada_vira_vazio(self):
        self.assertEqual(codigo_coluna(self._linha(1), {}, "ted"), "")


class NormalizarOperacaoTests(unittest.TestCase):
    def test_formatos_com_e_sem_espaco_internos(self):
        # DOC NC usa "( + )"/"( - )"; DOC PF usa "(+)"/"(-)" — ambos têm que convergir.
        self.assertEqual(normalizar_operacao("( + )"), "+")
        self.assertEqual(normalizar_operacao("(+)"), "+")
        self.assertEqual(normalizar_operacao("( - )"), "-")
        self.assertEqual(normalizar_operacao("(-)"), "-")


class ChavesNaturaisTests(unittest.TestCase):
    def test_chave_ted(self):
        self.assertEqual(chave_ted("17352", "1ABDKU"), "17352|1ABDKU")

    def test_chave_ted_normaliza_codigo_numerico(self):
        self.assertEqual(chave_ted(17352, "1ABDKU"), "17352|1ABDKU")

    def test_chave_empenho(self):
        self.assertEqual(
            chave_empenho(153165, 15239, "2026NE000422"),
            "153165|15239|2026NE000422",
        )

    def test_chave_nc_e_chave_pf(self):
        self.assertEqual(chave_nc(153165, "2026NC000010"), "153165|2026NC000010")
        self.assertEqual(chave_pf("153165", "2024PF000016"), "153165|2024PF000016")

    def test_chave_nc_documento_agrupa_linhas_do_mesmo_documento(self):
        # Mesmo TED/SIAFI/número/operação/data -> mesma chave de documento, independente da
        # UG emitente (que pode faltar em parte das linhas reais).
        chave_a = chave_nc_documento("17352", "1ABDKU", "2026NC000101", "+", "2026-02-10")
        chave_b = chave_nc_documento(17352.0, "1ABDKU", "2026NC000101", "+", "2026-02-10")
        self.assertEqual(chave_a, chave_b)

    def test_chave_nc_documento_muda_com_numero_diferente(self):
        chave_a = chave_nc_documento("17352", "1ABDKU", "2026NC000101", "+", "2026-02-10")
        chave_b = chave_nc_documento("17352", "1ABDKU", "2026NC000102", "+", "2026-02-10")
        self.assertNotEqual(chave_a, chave_b)

    def test_chave_nc_linha_combina_lote_e_indice(self):
        self.assertEqual(chave_nc_linha("lote-1", 3), "lote-1|3")
        self.assertNotEqual(chave_nc_linha("lote-1", 3), chave_nc_linha("lote-2", 3))

    def test_descricao_nunca_entra_na_chave(self):
        # A chave não deve mudar mesmo que a descrição textual do termo mude — a função nem
        # aceita esse parâmetro, o que é a garantia (regra 9 do briefing).
        self.assertEqual(chave_ted.__code__.co_varnames[: chave_ted.__code__.co_argcount], ("ted", "codigo_siafi"))


class DecomporNumeroNeTests(unittest.TestCase):
    def test_formato_reconhecido(self):
        self.assertEqual(decompor_numero_ne("2026NE000422"), ("2026", "NE", "000422"))

    def test_formato_nao_reconhecido_devolve_none(self):
        self.assertIsNone(decompor_numero_ne("algo-diferente"))


if __name__ == "__main__":
    unittest.main()
