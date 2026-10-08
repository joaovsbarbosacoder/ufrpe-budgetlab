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


class JanelaComumESemBaseTests(unittest.TestCase):
    """Regras revistas em 08/10/2026 (spec `docs/superpowers/specs/2026-10-08-teds-alertas-e-controle-nc-design.md`,
    §3.1 e §3.2): a soma analítica só considera documentos com data nos anos do consolidado do TED; TED sem
    nenhum documento do tipo é "sem base"; PF > NC com vigência anterior ao consolidado é "sem base"."""

    def setUp(self):
        self.conn = conectar(":memory:")
        self.conn.execute(
            "INSERT INTO import_batch (id, tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, status) "
            "VALUES (1, 'teste', 'x.xlsx', 'hash', '2026-01-01T00:00:00', 'ok')"
        )

    def tearDown(self):
        self.conn.close()

    def _ted(self, ted, inicio):
        numero, siafi = ted.split("|")
        self.conn.execute(
            "INSERT INTO ted (chave_ted, ted, codigo_siafi, estado_atual, inicio_vigencia, fim_vigencia, "
            "ug_descentralizadora) VALUES (?, ?, ?, 'Termo em Execução', ?, '2030-12-31', '153165')",
            (ted, numero, siafi, inicio),
        )

    def _anual(self, ted, ano, nc, pf):
        self.conn.execute(
            "INSERT INTO execucao_anual VALUES (?, ?, ?, '0.00', ?, ?, '0.00', ?, 1, '{}')",
            (ted, ano, nc, nc, pf, pf),
        )

    def _pf(self, ted, numero, data, valor):
        self.conn.execute(
            """INSERT INTO documento_pf (chave_ted, ug_emitente, numero_pf, data_emissao, operacao,
                 valor_original, valor_assinado, import_batch_id, linha_origem)
               VALUES (?, '153165', ?, ?, '+', ?, ?, 1, '{}')""",
            (ted, numero, data, valor, valor),
        )

    def _consolidado_2023_2025(self):
        # Repassado 2023–2025 = 1.094.824,95 (NC igual, para não misturar com PF > NC).
        self._anual(TED_17352, 2023, "400000.00", "400000.00")
        self._anual(TED_17352, 2024, "394824.95", "394824.95")
        self._anual(TED_17352, 2025, "300000.00", "300000.00")

    def _pfs_2019_2022(self):
        # 2019–2022 somam 1.711.150,55 — fora da janela do consolidado.
        self._pf(TED_17352, "PF19", "2019-03-01", "500000.00")
        self._pf(TED_17352, "PF20", "2020-03-01", "600000.00")
        self._pf(TED_17352, "PF21", "2021-03-01", "411150.55")
        self._pf(TED_17352, "PF22", "2022-03-01", "200000.00")

    def _sincronizar(self):
        return [(a.tipo, a.documento, a.descricao) for a in sincronizar_alertas_conciliacao_simec(self.conn)]

    def test_janela_elimina_divergencia_de_periodo(self):
        self._consolidado_2023_2025()
        self._pfs_2019_2022()
        self._pf(TED_17352, "PF23", "2023-05-01", "400000.00")
        self._pf(TED_17352, "PF24", "2024-05-01", "394824.95")
        self._pf(TED_17352, "PF25", "2025-05-01", "300000.00")
        self.conn.commit()
        self.assertNotIn(TIPO_PF_DIVERGE_CONSOLIDADO, [t for t, _, _ in self._sincronizar()])

    def test_janela_parcial(self):
        self._consolidado_2023_2025()
        self._pfs_2019_2022()
        self._pf(TED_17352, "PF23", "2023-05-01", "400000.00")
        self._pf(TED_17352, "PF24", "2024-05-01", "300000.00")
        self._pf(TED_17352, "PF25", "2025-05-01", "300000.00")  # 2023–2025 = 1.000.000,00
        self.conn.commit()
        alertas = [a for a in self._sincronizar() if a[0] == TIPO_PF_DIVERGE_CONSOLIDADO]
        self.assertEqual(len(alertas), 1)
        self.assertIn("1.000.000,00", alertas[0][2])
        self.assertIn("1.711.150,55", alertas[0][2])  # valor fora da janela citado

    def _nc(self, ted, numero, data, valor):
        self.conn.execute(
            """INSERT INTO documento_nc (chave_nc_documento, chave_ted, numero_nc, data_emissao, operacao,
                 valor_original_total, valor_assinado_total, quantidade_linhas, status_relacionamento, import_batch_id)
               VALUES (?, ?, ?, ?, '+', ?, ?, 1, 'OK', 1)""",
            (f"{ted}|{numero}", ted, numero, data, valor, valor),
        )

    def test_documento_sem_data_que_explica_a_diferenca_e_inconclusivo(self):
        # Correção de 08/10/2026 (revisão com o banco real): PF sem data que completa o consolidado não pode
        # virar divergência — janela + sem data bate, então é inconclusivo (sem alerta).
        self._consolidado_2023_2025()
        self._pf(TED_17352, "PF23", "2023-05-01", "1000000.00")
        self._pf(TED_17352, "PFX", None, "94824.95")
        self.conn.commit()
        self.assertNotIn(TIPO_PF_DIVERGE_CONSOLIDADO, [t for t, _, _ in self._sincronizar()])

    def test_documento_sem_data_que_nao_explica_a_diferenca_gera_alerta(self):
        self._consolidado_2023_2025()
        self._pf(TED_17352, "PF23", "2023-05-01", "1000000.00")
        self._pf(TED_17352, "PFX", None, "50000.00")
        self.conn.commit()
        (alerta,) = [a for a in self._sincronizar() if a[0] == TIPO_PF_DIVERGE_CONSOLIDADO]
        self.assertIn("1.000.000,00", alerta[2])
        self.assertIn("1 PF sem data", alerta[2])
        self.assertIn("50.000,00", alerta[2])

    def test_nc_sem_data_igual_ao_consolidado_formato_14142_nao_gera_alerta(self):
        # Formato real do TED 14142|1AAVEH: duas NCs sem data (3.473.147,40 + 1.210.680,00) somam exatamente o
        # Total Descentralizado consolidado (4.683.827,40) e nenhuma NC datada cai na janela.
        self._anual(TED_17352, 2023, "4683827.40", "0.00")
        self._nc(TED_17352, "NC1", None, "3473147.40")
        self._nc(TED_17352, "NC2", None, "1210680.00")
        self.conn.commit()
        self.assertNotIn(TIPO_NC_DIVERGE_CONSOLIDADO, [t for t, _, _ in self._sincronizar()])

    def test_nc_diverge_com_e_sem_os_documentos_sem_data_gera_alerta(self):
        self._anual(TED_17352, 2023, "1000.00", "0.00")
        self._nc(TED_17352, "NC1", "2023-02-01", "600.00")
        self._nc(TED_17352, "NC2", None, "123.45")
        self._pf(TED_17352, "PFX", None, "77.77")  # PF sem data não pode aparecer no alerta de NC
        self.conn.commit()
        (alerta,) = [a for a in self._sincronizar() if a[0] == TIPO_NC_DIVERGE_CONSOLIDADO]
        self.assertIn("1 NC sem data", alerta[2])
        self.assertIn("123,45", alerta[2])
        self.assertNotIn("77,77", alerta[2])
        self.assertNotIn("PF sem data", alerta[2])

    def test_ted_sem_pf_no_extrato_e_sem_base(self):
        self._anual(TED_17352, 2025, "842294.76", "842294.76")
        self._anual(TED_17454, 2025, "10.00", "10.00")
        self._pf(TED_17454, "PFB", "2025-02-01", "10.00")  # há PF, mas de outro TED
        self.conn.commit()
        self.assertEqual(self._sincronizar(), [])

    def test_pf_maior_que_nc_vigencia_anterior_e_sem_base(self):
        self._ted(TED_17352, "2022-08-16")
        self._anual(TED_17352, 2023, "0.00", "637870.01")
        self.conn.commit()
        self.assertNotIn(TIPO_PF_MAIOR_QUE_NC, [t for t, _, _ in self._sincronizar()])

    def test_pf_maior_que_nc_real(self):
        self._ted(TED_17352, "2024-01-10")
        self._anual(TED_17352, 2024, "100.00", "200.00")
        self.conn.commit()
        self.assertEqual([t for t, _, _ in self._sincronizar()], [TIPO_PF_MAIOR_QUE_NC])


if __name__ == "__main__":
    unittest.main()
