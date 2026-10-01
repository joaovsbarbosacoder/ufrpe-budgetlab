"""Regras puras da Captação de Demandas (RN-01..RN-05, fases e transições)."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from src.captacao import regras

ABERTURA = date(2026, 9, 1)
ENCERRAMENTO = date(2026, 10, 31)
PRAZO_VALIDACAO = date(2026, 11, 7)


def _demanda_completa(**ajustes):
    demanda = {
        "tipo": "EQUIPAMENTO_PERMANENTE",
        "descricao": "Balança eletrônica",
        "quantidade": 2,
        "unidade_fornecimento": "Unidade",
        "valor_unitario": "24000.00",
        "prioridade": "ESSENCIAL",
        "objetivos_pdi": [1],
        "metas_pls": [1],
        "contribuicao": "Apoia a meta.",
        "justificativa": "x" * 200,
        "solicita_analise_vinculo": 0,
    }
    demanda.update(ajustes)
    return demanda


class ValorTotalTests(unittest.TestCase):
    def test_rn03_total_e_quantidade_vezes_valor_unitario(self):
        self.assertEqual(regras.calcular_valor_total(3, "10.10"), Decimal("30.30"))

    def test_rn03_nao_usa_float_e_arredonda_meio_para_cima(self):
        self.assertEqual(regras.calcular_valor_total(3, "0.335"), Decimal("1.01"))
        with self.assertRaises(TypeError):
            regras.calcular_valor_total(1, 0.1)

    def test_rn03_aceita_virgula_decimal(self):
        self.assertEqual(regras.calcular_valor_total(2, "1,50"), Decimal("3.00"))

    def test_ausente_zero_e_negativo_nunca_viram_total_zero(self):
        for quantidade, unitario in [(None, "1.00"), (1, None), (1, ""), (0, "1.00"), (1, "0"), (1, "-5"), (-1, "5"), (1, "abc")]:
            with self.subTest(quantidade=quantidade, unitario=unitario):
                self.assertIsNone(regras.calcular_valor_total(quantidade, unitario))

    def test_quantidade_nao_inteira_ou_booleana_e_recusada(self):
        self.assertIsNone(regras.calcular_valor_total(True, "1.00"))
        self.assertIsNone(regras.calcular_valor_total("2", "1.00"))


class NaturezaTests(unittest.TestCase):
    def test_rn04_natureza_sugerida_pelo_tipo(self):
        self.assertEqual(regras.natureza_sugerida("MATERIAL_CONSUMO"), "CUSTEIO")
        self.assertEqual(regras.natureza_sugerida("SERVICO"), "CUSTEIO")
        self.assertEqual(regras.natureza_sugerida("EQUIPAMENTO_PERMANENTE"), "CAPITAL")
        self.assertEqual(regras.natureza_sugerida("OBRA_REFORMA"), "CAPITAL")
        self.assertIsNone(regras.natureza_sugerida(None))
        self.assertIsNone(regras.natureza_sugerida("OUTRO"))

    def test_natureza_final_prevalece_e_vazia_vale_a_sugerida(self):
        self.assertEqual(regras.natureza_efetiva("CUSTEIO", "CAPITAL"), "CUSTEIO")
        self.assertEqual(regras.natureza_efetiva(None, "CAPITAL"), "CAPITAL")

    def test_rn04_alerta_de_classificacao_so_para_obra_reforma(self):
        self.assertTrue(regras.exige_alerta_classificacao("OBRA_REFORMA"))
        self.assertFalse(regras.exige_alerta_classificacao("SERVICO"))


class FaseEPrazoTests(unittest.TestCase):
    def test_agendado_abre_automaticamente_na_data_de_abertura(self):
        self.assertEqual(regras.fase_por_data("AGENDADO", ABERTURA, ENCERRAMENTO, date(2026, 8, 31)), "AGENDADO")
        self.assertEqual(regras.fase_por_data("AGENDADO", ABERTURA, ENCERRAMENTO, ABERTURA), "ABERTO")

    def test_aberto_encerra_depois_da_data_de_encerramento_inclusive_no_dia(self):
        self.assertEqual(regras.fase_por_data("ABERTO", ABERTURA, ENCERRAMENTO, ENCERRAMENTO), "ABERTO")
        self.assertEqual(regras.fase_por_data("ABERTO", ABERTURA, ENCERRAMENTO, date(2026, 11, 1)), "ENCERRADO")

    def test_agendado_pode_atravessar_direto_para_encerrado(self):
        self.assertEqual(regras.fase_por_data("AGENDADO", ABERTURA, ENCERRAMENTO, date(2026, 12, 1)), "ENCERRADO")

    def test_demais_fases_so_mudam_manualmente(self):
        for fase in ("RASCUNHO", "EM_ANALISE", "CONCLUIDO", "ENCERRADO"):
            self.assertEqual(regras.fase_por_data(fase, ABERTURA, ENCERRAMENTO, date(2030, 1, 1)), fase)

    def test_prazo_efetivo_prefere_a_prorrogacao(self):
        self.assertEqual(regras.prazo_efetivo(ENCERRAMENTO, None), ENCERRAMENTO)
        self.assertEqual(regras.prazo_efetivo(ENCERRAMENTO, date(2026, 11, 7)), date(2026, 11, 7))

    def test_rn05_registro_so_com_ciclo_aberto_e_dentro_do_prazo(self):
        def pode(fase, hoje, prorrogacao=None, antecipado=False):
            return regras.pode_registrar(fase, ABERTURA, ENCERRAMENTO, prorrogacao, hoje, antecipado)

        self.assertTrue(pode("ABERTO", date(2026, 10, 1)))
        self.assertTrue(pode("ABERTO", ENCERRAMENTO))
        self.assertFalse(pode("ABERTO", date(2026, 11, 1)))
        self.assertFalse(pode("ENCERRADO", date(2026, 10, 1)))
        self.assertFalse(pode("EM_ANALISE", date(2026, 10, 1)))
        self.assertFalse(pode("RASCUNHO", date(2026, 10, 1)))

    def test_rn05_prorrogacao_estende_so_a_unidade(self):
        prorrogada = date(2026, 11, 7)
        self.assertTrue(regras.pode_registrar("ABERTO", ABERTURA, ENCERRAMENTO, prorrogada, date(2026, 11, 5)))
        self.assertFalse(regras.pode_registrar("ABERTO", ABERTURA, ENCERRAMENTO, prorrogada, date(2026, 11, 8)))
        self.assertFalse(regras.pode_registrar("ABERTO", ABERTURA, ENCERRAMENTO, None, date(2026, 11, 5)))

    def test_rascunho_antecipado_depende_da_configuracao_do_ciclo(self):
        antes = date(2026, 8, 20)
        self.assertFalse(regras.pode_registrar("AGENDADO", ABERTURA, ENCERRAMENTO, None, antes, False))
        self.assertTrue(regras.pode_registrar("AGENDADO", ABERTURA, ENCERRAMENTO, None, antes, True))
        self.assertFalse(regras.pode_registrar("ABERTO", ABERTURA, ENCERRAMENTO, None, antes, True))

    def test_envio_antes_da_abertura_e_recusado_mesmo_com_rascunho_antecipado(self):
        self.assertFalse(regras.pode_enviar("AGENDADO", ABERTURA, ENCERRAMENTO, None, date(2026, 8, 20)))

    def test_rn06_devolvida_pode_ser_reenviada_ate_o_prazo_de_validacao(self):
        depois_do_encerramento = date(2026, 11, 3)
        self.assertFalse(regras.pode_enviar("ENCERRADO", ABERTURA, ENCERRAMENTO, None, depois_do_encerramento))
        self.assertTrue(
            regras.pode_enviar(
                "ENCERRADO", ABERTURA, ENCERRAMENTO, None, depois_do_encerramento,
                devolvida=True, prazo_validacao=PRAZO_VALIDACAO,
            )
        )
        self.assertFalse(
            regras.pode_enviar(
                "ENCERRADO", ABERTURA, ENCERRAMENTO, None, date(2026, 11, 8),
                devolvida=True, prazo_validacao=PRAZO_VALIDACAO,
            )
        )


class ValidarEnvioTests(unittest.TestCase):
    def test_demanda_completa_nao_tem_pendencias(self):
        self.assertEqual(regras.validar_envio(_demanda_completa()), [])

    def test_rn01_exige_objetivo_pdi_e_meta_pls(self):
        self.assertIn("Pelo menos um objetivo do PDI", regras.validar_envio(_demanda_completa(objetivos_pdi=[])))
        self.assertIn("Pelo menos uma meta do PLS", regras.validar_envio(_demanda_completa(metas_pls=[])))

    def test_rn01_excecao_libera_so_a_meta_pls_nunca_o_pdi(self):
        pedido = _demanda_completa(metas_pls=[], solicita_analise_vinculo=1)
        self.assertEqual(regras.validar_envio(pedido), [])
        self.assertEqual(
            regras.validar_envio(_demanda_completa(objetivos_pdi=[], metas_pls=[], solicita_analise_vinculo=1)),
            ["Pelo menos um objetivo do PDI"],
        )

    def test_rn01_excecao_pode_ser_desligada_por_ser_ponto_em_aberto(self):
        pedido = _demanda_completa(metas_pls=[], solicita_analise_vinculo=1)
        self.assertEqual(
            regras.validar_envio(pedido, permitir_excecao_vinculo_pls=False), ["Pelo menos uma meta do PLS"]
        )

    def test_rn02_justificativa_minima_de_200_caracteres(self):
        self.assertEqual(regras.validar_envio(_demanda_completa(justificativa="x" * 200)), [])
        self.assertEqual(
            regras.validar_envio(_demanda_completa(justificativa="x" * 199)),
            ["Justificativa com pelo menos 200 caracteres"],
        )
        # espaços nas pontas não contam: 150 caracteres úteis < 200
        self.assertEqual(
            regras.validar_envio(_demanda_completa(justificativa=" " * 100 + "x" * 150 + " " * 100)),
            ["Justificativa com pelo menos 200 caracteres"],
        )

    def test_rn02_contribuicao_obrigatoria(self):
        self.assertEqual(
            regras.validar_envio(_demanda_completa(contribuicao="  ")), ["Contribuição para as metas"]
        )

    def test_rn08_lista_todas_as_pendencias_de_uma_vez(self):
        pendencias = regras.validar_envio({})
        for esperado in (
            "Tipo da demanda", "Descrição do item", "Quantidade (inteiro maior que zero)",
            "Unidade de fornecimento", "Valor unitário (maior que zero)", "Prioridade",
            "Pelo menos um objetivo do PDI", "Pelo menos uma meta do PLS",
            "Contribuição para as metas", "Justificativa com pelo menos 200 caracteres",
        ):
            self.assertIn(esperado, pendencias)

    def test_quantidade_e_valor_zero_ou_negativo_sao_recusados(self):
        for ajuste in ({"quantidade": 0}, {"quantidade": -1}, {"valor_unitario": "0"}, {"valor_unitario": "-1"}):
            with self.subTest(ajuste=ajuste):
                self.assertNotEqual(regras.validar_envio(_demanda_completa(**ajuste)), [])


class TransicaoTests(unittest.TestCase):
    def test_transicoes_do_diagrama_de_situacoes(self):
        permitidas = [
            ("RASCUNHO", "ENVIADA"),
            ("ENVIADA", "VALIDADA_CHEFIA"),
            ("ENVIADA", "RASCUNHO"),
            ("VALIDADA_CHEFIA", "VALIDADA_PROPLAD"),
            ("VALIDADA_CHEFIA", "RASCUNHO"),
            ("VALIDADA_PROPLAD", "INCLUIDA_PROPOSTA"),
            ("VALIDADA_PROPLAD", "NAO_INCLUIDA"),
        ]
        for de, para in permitidas:
            self.assertTrue(regras.transicao_permitida(de, para), (de, para))

    def test_transicoes_fora_do_diagrama_sao_recusadas(self):
        for de, para in [
            ("RASCUNHO", "VALIDADA_CHEFIA"),
            ("ENVIADA", "VALIDADA_PROPLAD"),
            ("VALIDADA_PROPLAD", "RASCUNHO"),
            ("INCLUIDA_PROPOSTA", "NAO_INCLUIDA"),
            ("NAO_INCLUIDA", "RASCUNHO"),
            ("INEXISTENTE", "ENVIADA"),
        ]:
            self.assertFalse(regras.transicao_permitida(de, para), (de, para))


if __name__ == "__main__":
    unittest.main()
