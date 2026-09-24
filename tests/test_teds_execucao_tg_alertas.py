"""
Testes dos alertas de execução por NE no Tesouro Gerencial (`src/teds_alertas.py`, briefing
seções 8.2 e 10): liquidado > empenhado, pago > liquidado e valor da NE no SIMEC diferente do
empenhado do Tesouro.

Decisões: comparação do ACUMULADO da NE (soma de todos os meses sincronizados, estornos com
sinal) — nunca mês a mês, para a defasagem de lançamento não gerar alerta falso —, tolerância
R$ 0,01, e NE sem dado no Tesouro é "sem base", nunca zero.
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from src.teds_alertas import (
    TIPO_NE_LIQUIDADO_MAIOR_QUE_EMPENHADO,
    TIPO_NE_PAGO_MAIOR_QUE_LIQUIDADO,
    TIPO_NE_SIMEC_DIFERE_TESOURO,
    TotalTesouroNE,
    VinculoSimec,
    gerar_alertas_execucao_tg,
    sincronizar_alertas_execucao_tg,
)
from src.teds_lotes import importar_doc_ne, sincronizar_execucao_tg
from src.teds_normalizacao import chave_empenho, chave_ted
from src.teds_schema import conectar

D = Decimal
TED_A = chave_ted("17352", "1ABDKU")
TED_B = chave_ted("17454", "1ABDKQ")
NE = "2026NE000427"
CE = chave_empenho("153165", "15239", NE)


def _vinculo(valor="1000.00", ted=TED_A, numero=NE):
    return VinculoSimec(ted, chave_empenho("153165", "15239", numero), numero, D(valor))


def _total(emp="1000.00", liq="0", pago="0", numero=NE, original="=emp"):
    """`original="=emp"`: o original observado é igual ao acumulado (NE sem reforço nem anulação)."""

    valor_original = D(emp) if original == "=emp" else (None if original is None else D(original))
    return TotalTesouroNE(numero, D(emp), D(liq), D(pago), original=valor_original, mes_original=(2026, 1))


def _tipos(vinculos, totais):
    return [a.tipo for a in gerar_alertas_execucao_tg(vinculos, {t.numero_ne: t for t in totais})]


class RegrasPurasTests(unittest.TestCase):
    def test_execucao_regular_nao_gera_alerta(self):
        self.assertEqual(_tipos([_vinculo()], [_total(liq="800.00", pago="700.00")]), [])

    def test_liquidado_maior_que_empenhado(self):
        alertas = gerar_alertas_execucao_tg([_vinculo()], {NE: _total(liq="1000.02")})
        self.assertEqual([a.tipo for a in alertas], [TIPO_NE_LIQUIDADO_MAIOR_QUE_EMPENHADO])
        self.assertEqual(alertas[0].gravidade, "alta")
        self.assertEqual(alertas[0].documento, NE)
        self.assertEqual(alertas[0].chave_ted, TED_A)
        self.assertIn("R$ 0,02", alertas[0].descricao)

    def test_pago_maior_que_liquidado(self):
        self.assertEqual(
            _tipos([_vinculo()], [_total(liq="500.00", pago="600.00")]), [TIPO_NE_PAGO_MAIOR_QUE_LIQUIDADO]
        )

    def test_um_centavo_e_tolerado(self):
        self.assertEqual(_tipos([_vinculo()], [_total(liq="1000.01", pago="1000.02")]), [])

    def test_simec_que_nao_bate_nem_com_o_original_nem_com_o_liquido_gera_alerta(self):
        alertas = gerar_alertas_execucao_tg([_vinculo("388300.00")], {NE: _total("154496.00")})
        self.assertEqual([a.tipo for a in alertas], [TIPO_NE_SIMEC_DIFERE_TESOURO])
        self.assertEqual(alertas[0].documento, f"{TED_A}|{CE}")
        self.assertIn("valor original", alertas[0].descricao)
        self.assertIn("primeiro empenho em 01/2026", alertas[0].descricao)
        self.assertIn("líquido atual", alertas[0].descricao)

    def test_simec_igual_ao_original_com_reforco_posterior_no_tesouro_esta_explicado(self):
        # Original 1.000, reforço de 500 depois: Tesouro líquido 1.500; o SIMEC guarda o original.
        self.assertEqual(_tipos([_vinculo("1000.00")], [_total("1500.00", original="1000.00")]), [])

    def test_simec_igual_ao_original_com_anulacao_posterior_no_tesouro_esta_explicado(self):
        self.assertEqual(_tipos([_vinculo("1000.00")], [_total("244.10", original="1000.00")]), [])
        self.assertEqual(_tipos([_vinculo("30000.00")], [_total("0.00", original="30000.00")]), [])  # anulada em 100%

    def test_simec_ja_atualizado_igual_ao_liquido_atual_tambem_esta_explicado(self):
        self.assertEqual(_tipos([_vinculo("244.10")], [_total("244.10", original="10000.00")]), [])

    def test_um_centavo_de_diferenca_para_o_original_e_tolerado(self):
        self.assertEqual(_tipos([_vinculo("1000.01")], [_total("1500.00", original="1000.00")]), [])
        self.assertEqual(
            _tipos([_vinculo("1000.02")], [_total("1500.00", original="1000.00")]), [TIPO_NE_SIMEC_DIFERE_TESOURO]
        )

    def test_original_nao_observavel_e_sem_base_e_nao_gera_alerta(self):
        # NE anterior ao início da Execução Mensal: o primeiro movimento visível é um reforço.
        self.assertEqual(_tipos([_vinculo("999.00")], [_total("1500.00", original=None)]), [])

    def test_ne_sem_dado_no_tesouro_e_sem_base_e_nao_gera_alerta(self):
        self.assertEqual(_tipos([_vinculo("999.00")], []), [])

    def test_estorno_negativo_ja_entra_no_acumulado(self):
        # Empenhado 1.000 com anulação de 200 = 800 líquido; SIMEC já traz 800: sem divergência.
        self.assertEqual(_tipos([_vinculo("800.00")], [_total("800.00", liq="800.00")]), [])

    def test_ne_em_dois_teds_gera_alerta_de_execucao_uma_vez_e_sem_ted(self):
        vinculos = [_vinculo(ted=TED_A), _vinculo(ted=TED_B)]
        alertas = gerar_alertas_execucao_tg(vinculos, {NE: _total(liq="2000.00")})
        self.assertEqual([a.tipo for a in alertas], [TIPO_NE_LIQUIDADO_MAIOR_QUE_EMPENHADO])
        self.assertIsNone(alertas[0].chave_ted)

    def test_divergencia_simec_e_por_vinculo(self):
        vinculos = [_vinculo("500.00", ted=TED_A), _vinculo("1000.00", ted=TED_B)]
        alertas = gerar_alertas_execucao_tg(vinculos, {NE: _total("1000.00", original="1000.00")})
        self.assertEqual([(a.tipo, a.chave_ted) for a in alertas], [(TIPO_NE_SIMEC_DIFERE_TESOURO, TED_A)])


def _df_ne(valor: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "Gestão Emitente - NE": "15239", "UG Executora Emitente - NE": "153165",
        "Descrição do Termo": "Termo", "Estado Atual": "Termo em Execução",
        "Início da Vigência": "01/01/2026", "Fim da Vigência": "31/12/2027",
        "UG Descentralizadora": "154046", "Número do Empenho": NE,
        "SIAFI": "1ABDKU", "TED": "17352", "Valor da NE": valor,
    }])


class IntegracaoComBancoTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")

    def tearDown(self):
        self.conn.close()

    def _abertos(self):
        return sorted(t for (t,) in self.conn.execute("SELECT tipo FROM alerta WHERE status != 'resolvido'"))

    def test_sem_execucao_tg_nao_gera_alerta_de_execucao(self):
        importar_doc_ne(self.conn, _df_ne("1.000,00"), "ne.xlsx", b"ne")
        self.assertEqual(sincronizar_alertas_execucao_tg(self.conn), [])

    def test_gera_uma_vez_e_nao_fecha_sozinho(self):
        importar_doc_ne(self.conn, _df_ne("1.000,00"), "ne.xlsx", b"ne")
        self.conn.execute(
            "INSERT INTO import_batch (id, tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, status) "
            "VALUES (99, 'teste', 'x', 'h', '2026-01-01', 'ok')"
        )
        self.conn.execute(
            "INSERT INTO execucao_tg (numero_completo_ne, empenhado, liquidado, pago, ano_lancamento, "
            "mes_lancamento, import_batch_id, linha_origem) VALUES (?, '900.00', '0', '0', 2026, 1, 99, '{}')",
            (NE,),
        )
        self.conn.commit()
        self.assertEqual(len(sincronizar_alertas_execucao_tg(self.conn)), 1)
        self.assertEqual(sincronizar_alertas_execucao_tg(self.conn), [])
        # O Tesouro passa a bater com o SIMEC, mas o alerta só fecha por ação humana.
        self.conn.execute("UPDATE execucao_tg SET empenhado = '1000.00'")
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_execucao_tg(self.conn), [])
        self.assertEqual(self._abertos(), [TIPO_NE_SIMEC_DIFERE_TESOURO])

    def test_sincronizar_a_execucao_mensal_dispara_os_alertas(self):
        importar_doc_ne(self.conn, _df_ne("1.000,00"), "ne.xlsx", b"ne")
        registros = [
            {"numero_completo_ne": NE, "favorecido": "F", "descricao": "D", "empenhado": D(e),
             "liquidado": D(l), "pago": D(p), "ano_lancamento": 2026, "mes_lancamento": m, "linha_origem": {}}
            for m, e, l, p in ((1, "1000.00", "0", "0"), (2, "0", "600.00", "0"), (3, "0", "0", "700.00"))
        ]
        leitura = SimpleNamespace(registros=registros, rejeitadas=[])
        with mock.patch("src.teds_lotes.montar_execucao_tg", return_value=leitura):
            sincronizar_execucao_tg(self.conn, pd.DataFrame(), "sha-teste", "mensal.xlsx")
        self.assertEqual(self._abertos(), [TIPO_NE_PAGO_MAIOR_QUE_LIQUIDADO])  # 700 pagos > 600 liquidados

    def _linhas_tg(self, numero_ne, movimentos):
        self.conn.execute(
            "INSERT OR IGNORE INTO import_batch (id, tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, status) "
            "VALUES (99, 'teste', 'x', 'h', '2026-01-01', 'ok')"
        )
        for ano, mes, empenhado in movimentos:
            self.conn.execute(
                "INSERT INTO execucao_tg (numero_completo_ne, empenhado, liquidado, pago, ano_lancamento, "
                "mes_lancamento, import_batch_id, linha_origem) VALUES (?, ?, '0', '0', ?, ?, 99, '{}')",
                (numero_ne, empenhado, ano, mes),
            )

    def test_o_original_e_o_primeiro_movimento_e_o_reforco_posterior_nao_gera_alerta(self):
        importar_doc_ne(self.conn, _df_ne("1.000,00"), "ne.xlsx", b"ne")  # SIMEC: original R$ 1.000
        self._linhas_tg(NE, [(2026, 1, "1000.00"), (2026, 4, "500.00")])  # reforço em abril
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_execucao_tg(self.conn), [])

    def test_valor_do_simec_diferente_do_primeiro_movimento_e_do_liquido_gera_alerta(self):
        importar_doc_ne(self.conn, _df_ne("2.000,00"), "ne.xlsx", b"ne")
        self._linhas_tg(NE, [(2026, 1, "1000.00"), (2026, 4, "500.00")])
        self.conn.commit()
        (alerta,) = sincronizar_alertas_execucao_tg(self.conn)
        self.assertEqual(alerta.tipo, TIPO_NE_SIMEC_DIFERE_TESOURO)
        self.assertIn("primeiro empenho em 01/2026", alerta.descricao)

    def test_movimentos_zerados_no_inicio_sao_ignorados_ao_achar_o_original(self):
        importar_doc_ne(self.conn, _df_ne("1.000,00"), "ne.xlsx", b"ne")
        self._linhas_tg(NE, [(2026, 1, "0.00"), (2026, 2, "1000.00"), (2026, 5, "-200.00")])
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_execucao_tg(self.conn), [])

    def test_ne_anterior_ao_inicio_da_base_nao_tem_original_observavel(self):
        # A base começa em 2026 (há linhas de outra NE em 2026); esta NE é de 2025: sem base.
        importar_doc_ne(self.conn, _df_ne("1.000,00").assign(**{"Número do Empenho": "2025NE000900"}), "ne.xlsx", b"ne")
        self._linhas_tg("2025NE000900", [(2026, 3, "300.00")])  # só um reforço visível
        self._linhas_tg("2026NE000001", [(2026, 1, "50.00")])
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_execucao_tg(self.conn), [])

    def test_defasagem_de_lancamento_nao_gera_alerta(self):
        """Liquidado lançado num mês em que não há empenho: no acumulado, tudo bate."""

        importar_doc_ne(self.conn, _df_ne("1.000,00"), "ne.xlsx", b"ne")
        self.conn.execute(
            "INSERT INTO import_batch (id, tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, status) "
            "VALUES (99, 'teste', 'x', 'h', '2026-01-01', 'ok')"
        )
        for mes, emp, liq, pago in ((1, "1000.00", "0", "0"), (2, "0", "1000.00", "0"), (3, "0", "0", "1000.00")):
            self.conn.execute(
                "INSERT INTO execucao_tg (numero_completo_ne, empenhado, liquidado, pago, ano_lancamento, "
                "mes_lancamento, import_batch_id, linha_origem) VALUES (?, ?, ?, ?, 2026, ?, 99, '{}')",
                (NE, emp, liq, pago, mes),
            )
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_execucao_tg(self.conn), [])


if __name__ == "__main__":
    unittest.main()
