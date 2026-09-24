"""
Testes de "crédito sem empenho" e "repasse sem execução financeira" (`src/teds_alertas.py`, briefing
seções 8.2 e 9.3). Decisões do usuário (24/09/2026): TED com crédito e SEM NE merece alerta (pode ser NE
não lançada no SIMEC); "execução financeira" é o PAGO no Tesouro Gerencial; prazo de 90 dias.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from src.teds_alertas import (
    PRAZO_SEM_EXECUCAO_DIAS,
    TIPO_TED_CREDITO_SEM_EMPENHO,
    TIPO_TED_PF_SEM_EXECUCAO_FINANCEIRA,
    ExecucaoDoTed,
    gerar_alertas_execucao_do_ted,
    sincronizar_alertas_execucao_do_ted,
)
from src.teds_normalizacao import chave_empenho, chave_ted
from src.teds_schema import conectar

D = Decimal
HOJE = date(2026, 9, 24)
CH = chave_ted("17352", "1ABDKU")


def _ted(**mudancas):
    base = dict(
        chave_ted=CH, ted="17352", codigo_siafi="1ABDKU", estado_atual="Termo em Execução",
        inicio_vigencia=date(2025, 1, 1), nc_liquida=D("1000.00"), pf_liquida=D("1000.00"),
        ultima_nc_descentralizacao=date(2026, 1, 10), ultimo_pf_repasse=date(2026, 1, 10),
        qtd_nes_ativas=1, pago_tesouro=D("500.00"),
    )
    base.update(mudancas)
    return ExecucaoDoTed(**base)


def _tipos(*teds, **kw):
    return [a.tipo for a in gerar_alertas_execucao_do_ted(list(teds), HOJE, **kw)]


class CreditoSemEmpenhoTests(unittest.TestCase):
    def test_prazo_padrao_e_90_dias(self):
        self.assertEqual(PRAZO_SEM_EXECUCAO_DIAS, 90)

    def test_credito_sem_nenhuma_ne_apos_o_prazo_gera_alerta_alto(self):
        (alerta,) = gerar_alertas_execucao_do_ted([_ted(qtd_nes_ativas=0)], HOJE)
        self.assertEqual(alerta.tipo, TIPO_TED_CREDITO_SEM_EMPENHO)
        self.assertEqual((alerta.gravidade, alerta.documento, alerta.chave_ted), ("alta", CH, CH))
        self.assertIn("nenhuma NE vinculada", alerta.descricao)
        self.assertIn("NE não lançada no SIMEC", alerta.descricao)
        self.assertIn("10/01/2026", alerta.descricao)

    def test_com_ne_ativa_nao_gera(self):
        self.assertEqual(_tipos(_ted(qtd_nes_ativas=1, pago_tesouro=None)), [])

    def test_dentro_do_prazo_nao_gera_e_um_dia_depois_gera(self):
        limite = date(2026, 6, 26)
        self.assertEqual((HOJE - limite).days, 90)
        self.assertEqual(_tipos(_ted(qtd_nes_ativas=0, ultima_nc_descentralizacao=limite)), [])
        self.assertEqual(
            _tipos(_ted(qtd_nes_ativas=0, ultima_nc_descentralizacao=date(2026, 6, 25))), [TIPO_TED_CREDITO_SEM_EMPENHO]
        )

    def test_vale_para_qualquer_estado_do_ted(self):
        for estado in ("Comprovado no SIAFI.", "Termo Finalizado", None):
            self.assertEqual(_tipos(_ted(qtd_nes_ativas=0, estado_atual=estado)), [TIPO_TED_CREDITO_SEM_EMPENHO], estado)

    def test_sem_credito_liquido_positivo_nao_gera(self):
        self.assertEqual(_tipos(_ted(qtd_nes_ativas=0, nc_liquida=D("0.00"))), [])
        self.assertEqual(_tipos(_ted(qtd_nes_ativas=0, nc_liquida=D("-5.00"))), [])
        self.assertEqual(_tipos(_ted(qtd_nes_ativas=0, nc_liquida=D("0.01"))), [])  # dentro da tolerância

    def test_sem_nc_datada_usa_o_inicio_da_vigencia(self):
        (alerta,) = gerar_alertas_execucao_do_ted([_ted(qtd_nes_ativas=0, ultima_nc_descentralizacao=None)], HOJE)
        self.assertIn("início da vigência em 01/01/2025", alerta.descricao)
        recente = _ted(qtd_nes_ativas=0, ultima_nc_descentralizacao=None, inicio_vigencia=date(2026, 9, 1))
        self.assertEqual(_tipos(recente), [])

    def test_sem_nenhuma_data_gera_alerta(self):
        self.assertEqual(
            _tipos(_ted(qtd_nes_ativas=0, ultima_nc_descentralizacao=None, inicio_vigencia=None)),
            [TIPO_TED_CREDITO_SEM_EMPENHO],
        )

    def test_prazo_e_parametrizavel(self):
        ted = _ted(qtd_nes_ativas=0, ultima_nc_descentralizacao=date(2026, 8, 1))
        self.assertEqual(_tipos(ted), [])
        self.assertEqual(_tipos(ted, prazo_dias=30), [TIPO_TED_CREDITO_SEM_EMPENHO])


class RepasseSemExecucaoFinanceiraTests(unittest.TestCase):
    def _pf_parado(self, **mudancas):
        return _ted(pago_tesouro=D("0.00"), **mudancas)

    def test_pf_repassado_sem_pago_no_tesouro_apos_o_prazo_gera_alerta_medio(self):
        (alerta,) = gerar_alertas_execucao_do_ted([self._pf_parado()], HOJE)
        self.assertEqual(alerta.tipo, TIPO_TED_PF_SEM_EXECUCAO_FINANCEIRA)
        self.assertEqual(alerta.gravidade, "media")
        self.assertIn("nenhum pagamento no Tesouro", alerta.descricao)
        self.assertIn("último PF de repasse em 10/01/2026", alerta.descricao)

    def test_com_pago_no_tesouro_nao_gera(self):
        self.assertEqual(_tipos(_ted(pago_tesouro=D("0.02"))), [])

    def test_um_centavo_de_pago_conta_como_zero(self):
        self.assertEqual(_tipos(_ted(pago_tesouro=D("0.01"))), [TIPO_TED_PF_SEM_EXECUCAO_FINANCEIRA])

    def test_sem_dado_no_tesouro_e_sem_base_e_nao_gera(self):
        self.assertEqual(_tipos(_ted(pago_tesouro=None)), [])

    def test_so_ted_em_execucao(self):
        for estado in ("Termo Finalizado", "Comprovado no SIAFI.", None):
            self.assertEqual(_tipos(self._pf_parado(estado_atual=estado)), [], estado)

    def test_sem_ne_ativa_fica_com_a_regra_de_credito_e_nao_com_esta(self):
        self.assertEqual(_tipos(self._pf_parado(qtd_nes_ativas=0)), [TIPO_TED_CREDITO_SEM_EMPENHO])

    def test_sem_pf_liquido_positivo_nao_gera(self):
        self.assertEqual(_tipos(self._pf_parado(pf_liquida=D("0.00"))), [])
        self.assertEqual(_tipos(self._pf_parado(pf_liquida=D("-1.00"))), [])

    def test_dentro_do_prazo_nao_gera_e_um_dia_depois_gera(self):
        self.assertEqual(_tipos(self._pf_parado(ultimo_pf_repasse=date(2026, 6, 26))), [])
        self.assertEqual(
            _tipos(self._pf_parado(ultimo_pf_repasse=date(2026, 6, 25))), [TIPO_TED_PF_SEM_EXECUCAO_FINANCEIRA]
        )

    def test_as_duas_regras_independentes_no_mesmo_lote(self):
        outro = _ted(chave_ted=chave_ted("99999", "1ZZZZZ"), ted="99999", qtd_nes_ativas=0)
        alertas = gerar_alertas_execucao_do_ted([self._pf_parado(), outro], HOJE)
        self.assertEqual(
            sorted((a.tipo, a.chave_ted) for a in alertas),
            sorted([(TIPO_TED_PF_SEM_EXECUCAO_FINANCEIRA, CH), (TIPO_TED_CREDITO_SEM_EMPENHO, outro.chave_ted)]),
        )


class IntegracaoComBancoTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")
        self.conn.execute(
            "INSERT INTO import_batch (id, tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, status) "
            "VALUES (1, 'teste', 'x', 'h', '2026-01-01', 'ok')"
        )
        self.conn.execute(
            "INSERT INTO ted (chave_ted, ted, codigo_siafi, estado_atual, inicio_vigencia, fim_vigencia, "
            "ug_descentralizadora) VALUES (?, '17352', '1ABDKU', 'Termo em Execução', '2025-01-01', '2027-12-31', '153165')",
            (CH,),
        )
        self.conn.execute(
            "INSERT INTO execucao_anual VALUES (?, 2026, '1000.00', '0.00', '1000.00', '800.00', '0.00', '800.00', 1, '{}')",
            (CH,),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _nc(self, numero, data, operacao="+"):
        self.conn.execute(
            """INSERT INTO documento_nc (chave_nc_documento, chave_ted, numero_nc, data_emissao, operacao,
                 valor_original_total, valor_assinado_total, quantidade_linhas, status_relacionamento, import_batch_id)
               VALUES (?, ?, ?, ?, ?, '1.00', '1.00', 1, 'OK', 1)""",
            (f"{CH}|{numero}", CH, numero, data, operacao),
        )

    def _pf(self, numero, data, operacao="+"):
        self.conn.execute(
            """INSERT INTO documento_pf (chave_ted, ug_emitente, numero_pf, data_emissao, operacao,
                 valor_original, valor_assinado, import_batch_id, linha_origem)
               VALUES (?, '153165', ?, ?, ?, '1.00', '1.00', 1, '{}')""",
            (CH, numero, data, operacao),
        )

    def _ne(self, numero_ne, status="ok"):
        self.conn.execute(
            "INSERT INTO vinculo_ne (chave_ted, chave_empenho, ug_emitente, gestao_emitente, numero_ne, valor_ne, "
            "status_validacao, import_batch_id, linha_origem) VALUES (?, ?, '153165', '15239', ?, '1000.00', ?, 1, '{}')",
            (CH, chave_empenho("153165", "15239", numero_ne), numero_ne, status),
        )

    def _tg(self, numero_ne, pago):
        self.conn.execute(
            "INSERT INTO execucao_tg (numero_completo_ne, empenhado, liquidado, pago, ano_lancamento, mes_lancamento, "
            "import_batch_id, linha_origem) VALUES (?, '0', '0', ?, 2026, 1, 1, '{}')",
            (numero_ne, pago),
        )

    def _abertos(self):
        return sorted(t for (t,) in self.conn.execute("SELECT tipo FROM alerta WHERE status != 'resolvido'"))

    def test_ted_com_credito_e_sem_ne_gera_o_alerta_uma_vez_e_nao_fecha_sozinho(self):
        self._nc("NC1", "2026-01-10")
        self.conn.commit()
        self.assertEqual(len(sincronizar_alertas_execucao_do_ted(self.conn, HOJE)), 1)
        self.assertEqual(sincronizar_alertas_execucao_do_ted(self.conn, HOJE), [])
        self._ne("2026NE000001")  # a NE aparece depois...
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_execucao_do_ted(self.conn, HOJE), [])
        self.assertEqual(self._abertos(), [TIPO_TED_CREDITO_SEM_EMPENHO])  # ...mas só uma pessoa fecha

    def test_a_data_da_nc_de_devolucao_nao_conta_como_descentralizacao(self):
        self._nc("NC1", "2026-01-10", "+")
        self._nc("NC2", "2026-09-20", "-")  # devolução recente: não renova o prazo
        self.conn.commit()
        (alerta,) = sincronizar_alertas_execucao_do_ted(self.conn, HOJE)
        self.assertIn("10/01/2026", alerta.descricao)

    def test_ne_descartada_por_decisao_humana_nao_conta_como_vinculo(self):
        self._nc("NC1", "2026-01-10")
        self._ne("2026NE000001", status="descartado")
        self.conn.commit()
        self.assertEqual(self._tipos_novos(), [TIPO_TED_CREDITO_SEM_EMPENHO])

    def _tipos_novos(self):
        return [a.tipo for a in sincronizar_alertas_execucao_do_ted(self.conn, HOJE)]

    def test_ne_pendente_conta_como_vinculo(self):
        self._nc("NC1", "2026-01-10")
        self._ne("2026NE000001", status="pendente")
        self.conn.commit()
        self.assertEqual(self._tipos_novos(), [])

    def test_pf_sem_pago_no_tesouro(self):
        self._nc("NC1", "2026-01-10")
        self._pf("PF1", "2026-01-10")
        self._ne("2026NE000001")
        self._tg("2026NE000001", "0")
        self.conn.commit()
        self.assertEqual(self._tipos_novos(), [TIPO_TED_PF_SEM_EXECUCAO_FINANCEIRA])

    def test_sem_execucao_tg_e_sem_base(self):
        self._nc("NC1", "2026-01-10")
        self._pf("PF1", "2026-01-10")
        self._ne("2026NE000001")
        self.conn.commit()
        self.assertEqual(self._tipos_novos(), [])

    def test_pago_em_qualquer_mes_da_ne_evita_o_alerta(self):
        self._nc("NC1", "2026-01-10")
        self._pf("PF1", "2026-01-10")
        self._ne("2026NE000001")
        self._tg("2026NE000001", "0")
        self.conn.execute(
            "INSERT INTO execucao_tg (numero_completo_ne, empenhado, liquidado, pago, ano_lancamento, mes_lancamento, "
            "import_batch_id, linha_origem) VALUES ('2026NE000001', '0', '0', '300.00', 2026, 5, 1, '{}')"
        )
        self.conn.commit()
        self.assertEqual(self._tipos_novos(), [])


if __name__ == "__main__":
    unittest.main()
