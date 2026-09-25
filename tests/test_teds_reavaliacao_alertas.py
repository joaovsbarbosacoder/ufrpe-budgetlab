"""Testes de `reavaliar_alertas` (`src/teds_lotes.py`): roda as verificações de alerta sobre dados já
importados, sem reimportar. Só cria alertas ausentes, é idempotente, não altera dado importado e
deixa registro na trilha de auditoria. Banco em memória — nunca `data/teds/teds.db`.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from src.teds_alertas import TIPO_PF_DIVERGE_CONSOLIDADO
from src.teds_auditoria import ACAO_ALERTAS_REAVALIADOS, ENTIDADE_ALERTA, historico_auditoria
from src.teds_lotes import reavaliar_alertas
from src.teds_normalizacao import chave_ted
from src.teds_schema import conectar

TED_A = chave_ted("10010", "1AACUL")
TED_B = chave_ted("10328", "1AAEZQ")
_TABELAS_IMPORTADAS = ("ted", "execucao_anual", "documento_pf", "documento_nc", "vinculo_ne", "execucao_tg")


class ReavaliarAlertasTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")
        self.conn.execute(
            "INSERT INTO import_batch (id, tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, status) "
            "VALUES (1, 'teste', 'x.xlsx', 'hash', '2026-01-01T00:00:00', 'ok')"
        )
        for ted, ano, repasse in ((TED_A, 2024, "1000.00"), (TED_B, 2024, "500.00")):
            self.conn.execute(
                "INSERT INTO ted (chave_ted, ted, codigo_siafi, estado_atual, fim_vigencia, ug_descentralizadora, import_batch_id) "
                "VALUES (?, ?, 'x', 'Termo em Execução', '2099-12-31', '150011', 1)",
                (ted, ted.split("|")[0]),
            )
            self.conn.execute(
                "INSERT INTO execucao_anual VALUES (?, ?, '0.00', '0.00', '0.00', ?, '0.00', ?, 1, '{}')",
                (ted, ano, repasse, repasse),
            )
        # TED_A: documentos PF somam mais que o consolidado (divergência). TED_B: bate.
        self._pf(TED_A, "PF1", "2500.00")
        self._pf(TED_B, "PF2", "500.00")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _pf(self, ted, numero, valor):
        self.conn.execute(
            "INSERT INTO documento_pf (chave_ted, ug_emitente, numero_pf, data_emissao, operacao, valor_original, "
            "valor_assinado, import_batch_id, linha_origem) VALUES (?, '153165', ?, '2024-01-01', '+', ?, ?, 1, '{}')",
            (ted, numero, valor, valor),
        )

    def _fotografia(self):
        return {t: self.conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in _TABELAS_IMPORTADAS}

    def _alertas(self, tipo):
        return [d for (d,) in self.conn.execute("SELECT documento FROM alerta WHERE tipo = ?", (tipo,))]

    def test_cria_o_alerta_de_conciliacao_que_a_importacao_antiga_nao_gerou(self):
        self.assertEqual(self._alertas(TIPO_PF_DIVERGE_CONSOLIDADO), [])
        resultado = reavaliar_alertas(self.conn)
        self.assertEqual(self._alertas(TIPO_PF_DIVERGE_CONSOLIDADO), [TED_A])
        self.assertEqual(resultado.criados_por_tipo[TIPO_PF_DIVERGE_CONSOLIDADO], 1)
        self.assertEqual(resultado.total, sum(resultado.criados_por_tipo.values()))

    def test_e_idempotente(self):
        reavaliar_alertas(self.conn)
        total_antes = self.conn.execute("SELECT COUNT(*) FROM alerta").fetchone()[0]
        segunda = reavaliar_alertas(self.conn)
        self.assertEqual(segunda.total, 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM alerta").fetchone()[0], total_antes)

    def test_nao_altera_nenhum_dado_importado(self):
        antes = self._fotografia()
        reavaliar_alertas(self.conn)
        self.assertEqual(self._fotografia(), antes)

    def test_nao_fecha_nem_reabre_alerta_existente(self):
        reavaliar_alertas(self.conn)
        self.conn.execute("UPDATE alerta SET status = 'resolvido', justificativa = 'ok'")
        self.conn.commit()
        # Divergência persiste e o alerta foi resolvido por uma pessoa: pode existir um novo (regra das importações),
        # mas o resolvido nunca é alterado.
        reavaliar_alertas(self.conn)
        resolvidos = self.conn.execute("SELECT COUNT(*) FROM alerta WHERE status = 'resolvido' AND justificativa = 'ok'").fetchone()[0]
        self.assertGreaterEqual(resolvidos, 1)

    def test_registra_auditoria_mesmo_quando_nada_e_criado(self):
        reavaliar_alertas(self.conn, usuario="Fulana")
        reavaliar_alertas(self.conn)
        registros = [r for r in historico_auditoria(self.conn, ENTIDADE_ALERTA, "reavaliacao")]
        self.assertEqual([r.acao for r in registros], [ACAO_ALERTAS_REAVALIADOS, ACAO_ALERTAS_REAVALIADOS])
        self.assertEqual(registros[0].usuario, "Fulana")
        self.assertGreaterEqual(registros[0].valor_novo["criados"], 1)
        self.assertEqual(registros[1].valor_novo["criados"], 0)

    def test_valores_monetarios_nao_sao_alterados_pela_reavaliacao(self):
        reavaliar_alertas(self.conn)
        soma = sum(
            (Decimal(v) for (v,) in self.conn.execute("SELECT valor_assinado FROM documento_pf")), start=Decimal("0")
        )
        self.assertEqual(soma, Decimal("3000.00"))


if __name__ == "__main__":
    unittest.main()
