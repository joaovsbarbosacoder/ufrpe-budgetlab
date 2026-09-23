"""
Testes da conciliação SIMEC analítica × consolidada (`src/teds_alertas.py`): NC líquida e PF
líquido dos documentos importados contra Total Descentralizado / Total Repassado de
`execucao_anual`, mais o alerta de PF líquido maior que a NC líquida.

Regras do briefing (seções 8.1, 9.1 e 9.2): diferença acima de R$ 0,01 gera alerta; o alerta
só descreve — não decide qual fonte está certa, e nunca fecha sozinho.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from src.teds_alertas import (
    TIPO_NC_DIVERGE_CONSOLIDADO,
    TIPO_PF_DIVERGE_CONSOLIDADO,
    TIPO_PF_MAIOR_QUE_NC,
    ResumoConciliacaoSimec,
    gerar_alertas_conciliacao_simec,
    sincronizar_alertas_conciliacao_simec,
)
from src.teds_normalizacao import chave_ted
from src.teds_schema import conectar

D = Decimal
TED_17352 = chave_ted("17352", "1ABDKU")
TED_17454 = chave_ted("17454", "1ABDKQ")


def _resumo(nc_an, pf_an, nc_cons="388300.00", pf_cons="388300.00", ted=TED_17352):
    def conv(valor):
        return None if valor is None else D(valor)

    return ResumoConciliacaoSimec(ted, D(nc_cons), D(pf_cons), conv(nc_an), conv(pf_an))


class RegrasPurasTests(unittest.TestCase):
    def _tipos(self, *resumos):
        return [a.tipo for a in gerar_alertas_conciliacao_simec(list(resumos))]

    def test_ted_que_bate_exatamente_nao_gera_alerta(self):
        self.assertEqual(self._tipos(_resumo("388300.00", "388300.00")), [])

    def test_um_centavo_e_tolerado_mas_dois_centavos_nao(self):
        self.assertEqual(self._tipos(_resumo("388300.01", "388299.99")), [])
        self.assertEqual(self._tipos(_resumo("388300.02", "388300.00")), [TIPO_NC_DIVERGE_CONSOLIDADO])

    def test_nc_e_pf_divergentes_geram_um_alerta_cada(self):
        self.assertEqual(
            self._tipos(_resumo("300000.00", "100000.00")),
            [TIPO_NC_DIVERGE_CONSOLIDADO, TIPO_PF_DIVERGE_CONSOLIDADO],
        )

    def test_base_analitica_ausente_nao_vira_divergencia(self):
        # None = documentos ainda não importados; nunca tratado como zero.
        self.assertEqual(self._tipos(_resumo(None, None)), [])

    def test_analitico_zero_com_consolidado_positivo_e_divergencia(self):
        self.assertEqual(self._tipos(_resumo("0", "388300.00")), [TIPO_NC_DIVERGE_CONSOLIDADO])

    def test_devolucao_negativa_entra_com_sinal_e_liquido_bate(self):
        # 388.300,00 descentralizados - 44.076,20 devolvidos = 344.223,80 líquidos.
        self.assertEqual(self._tipos(_resumo("344223.80", "344223.80", "344223.80", "344223.80")), [])

    def test_pf_maior_que_nc_consolidados(self):
        alertas = gerar_alertas_conciliacao_simec([_resumo(None, None, "0.00", "637870.01")])
        self.assertEqual([a.tipo for a in alertas], [TIPO_PF_MAIOR_QUE_NC])
        self.assertEqual(alertas[0].gravidade, "alta")
        self.assertEqual(alertas[0].documento, TED_17352)
        self.assertIn("637.870,01", alertas[0].descricao)

    def test_pf_igual_menor_ou_negativo_nao_gera_pf_maior_que_nc(self):
        self.assertEqual(self._tipos(_resumo(None, None, "100.00", "100.00")), [])
        self.assertEqual(self._tipos(_resumo(None, None, "100.00", "-5.00")), [])


class SincronizacaoComBancoTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")
        self.conn.execute(
            "INSERT INTO import_batch (id, tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, status) "
            "VALUES (1, 'teste', 'x.xlsx', 'hash', '2026-01-01T00:00:00', 'ok')"
        )

    def tearDown(self):
        self.conn.close()

    def _execucao_anual(self, ted, ano, desc, dev, repasse, pf_dev):
        self.conn.execute(
            "INSERT INTO execucao_anual VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, '{}')",
            (ted, ano, desc, dev, str(D(desc) - D(dev)), repasse, pf_dev, str(D(repasse) - D(pf_dev))),
        )

    def _nc(self, ted, numero, valor_assinado):
        self.conn.execute(
            """INSERT INTO documento_nc (chave_nc_documento, chave_ted, ted, codigo_siafi, numero_nc,
                 data_emissao, operacao, valor_original_total, valor_assinado_total,
                 quantidade_linhas, status_relacionamento, import_batch_id)
               VALUES (?, ?, 'x', 'y', ?, '2026-01-01', '+', ?, ?, 1, 'OK', 1)""",
            (f"{ted}|{numero}", ted, numero, valor_assinado, valor_assinado),
        )

    def _pf(self, ted, numero, valor_assinado):
        self.conn.execute(
            """INSERT INTO documento_pf (chave_ted, ug_emitente, numero_pf, data_emissao, operacao,
                 valor_original, valor_assinado, import_batch_id, linha_origem)
               VALUES (?, '153165', ?, '2026-01-01', '+', ?, ?, 1, '{}')""",
            (ted, numero, valor_assinado, valor_assinado),
        )

    def _tipos_abertos(self):
        return sorted(t for (t,) in self.conn.execute("SELECT tipo FROM alerta WHERE status != 'resolvido'"))

    def test_sem_documentos_analiticos_so_o_pf_maior_que_nc_e_avaliado(self):
        self._execucao_anual(TED_17352, 2026, "388300.00", "0.00", "388300.00", "0.00")
        self._execucao_anual(TED_17454, 2026, "0.00", "0.00", "50.00", "0.00")
        self.conn.commit()
        novos = sincronizar_alertas_conciliacao_simec(self.conn)
        self.assertEqual([(a.tipo, a.documento) for a in novos], [(TIPO_PF_MAIOR_QUE_NC, TED_17454)])

    def test_soma_varios_exercicios_no_consolidado_e_varias_linhas_no_analitico(self):
        self._execucao_anual(TED_17352, 2025, "100000.00", "0.00", "100000.00", "0.00")
        self._execucao_anual(TED_17352, 2026, "288300.00", "0.00", "288300.00", "0.00")
        self._nc(TED_17352, "NC1", "250000.00")
        self._nc(TED_17352, "NC2", "138300.00")
        self._pf(TED_17352, "PF1", "388300.00")
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_conciliacao_simec(self.conn), [])

    def test_divergencia_gera_alerta_uma_unica_vez_e_nunca_fecha_sozinha(self):
        self._execucao_anual(TED_17352, 2026, "388300.00", "0.00", "388300.00", "0.00")
        self._nc(TED_17352, "NC1", "300000.00")
        self._pf(TED_17352, "PF1", "388300.00")
        self.conn.commit()
        self.assertEqual(len(sincronizar_alertas_conciliacao_simec(self.conn)), 1)
        self.assertEqual(sincronizar_alertas_conciliacao_simec(self.conn), [])
        self.assertEqual(self._tipos_abertos(), [TIPO_NC_DIVERGE_CONSOLIDADO])

        # A diferença some (NC completada), mas o alerta segue aberto até tratamento humano.
        self._nc(TED_17352, "NC2", "88300.00")
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_conciliacao_simec(self.conn), [])
        self.assertEqual(self._tipos_abertos(), [TIPO_NC_DIVERGE_CONSOLIDADO])

    def test_alerta_resolvido_permite_novo_alerta_se_a_divergencia_persistir(self):
        self._execucao_anual(TED_17352, 2026, "388300.00", "0.00", "388300.00", "0.00")
        self._nc(TED_17352, "NC1", "300000.00")
        self.conn.commit()
        sincronizar_alertas_conciliacao_simec(self.conn)
        self.conn.execute("UPDATE alerta SET status = 'resolvido'")
        self.conn.commit()
        self.assertEqual(len(sincronizar_alertas_conciliacao_simec(self.conn)), 1)

    def test_documento_sem_ted_conhecido_e_ignorado(self):
        self._execucao_anual(TED_17352, 2026, "388300.00", "0.00", "388300.00", "0.00")
        self._nc(TED_17352, "NC1", "388300.00")
        self.conn.execute(
            """INSERT INTO documento_nc (chave_nc_documento, chave_ted, numero_nc, operacao,
                 valor_original_total, valor_assinado_total, quantidade_linhas,
                 status_relacionamento, import_batch_id)
               VALUES ('orfa', NULL, 'NCX', '+', '9.99', '9.99', 1, 'OK', 1)"""
        )
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_conciliacao_simec(self.conn), [])


if __name__ == "__main__":
    unittest.main()
