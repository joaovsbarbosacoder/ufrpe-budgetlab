"""Testes de `reavaliar_alertas` (`src/teds_lotes.py`): roda as verificações de alerta sobre dados já
importados, sem reimportar. Só cria alertas ausentes, é idempotente, não altera dado importado e
deixa registro na trilha de auditoria. Banco em memória — nunca `data/teds/teds.db`.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from src.teds_alertas import (
    TIPO_NC_UG_EMITENTE_AUSENTE,
    TIPO_PF_DIVERGE_CONSOLIDADO,
    TIPO_TED_CREDITO_SEM_EMPENHO,
)
from src.teds_auditoria import (
    ACAO_ALERTA_STATUS_ALTERADO,
    ACAO_ALERTAS_REAVALIADOS,
    ENTIDADE_ALERTA,
    historico_auditoria,
)
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

    # --- Fechamento de alertas obsoletos dos tipos revistos (spec de 08/10/2026, §4) ---
    def _alerta(self, tipo, documento, status="aberto", chave=None):
        cursor = self.conn.execute(
            "INSERT INTO alerta (tipo, gravidade, chave_ted, documento, descricao, status, data_identificacao) "
            "VALUES (?, 'media', ?, ?, 'x', ?, '2026-01-01T00:00:00')",
            (tipo, chave, documento, status),
        )
        self.conn.commit()
        return cursor.lastrowid

    def _estado(self, alerta_id):
        return self.conn.execute(
            "SELECT status, responsavel, justificativa, data_resolucao FROM alerta WHERE id = ?", (alerta_id,)
        ).fetchone()

    def test_fecha_obsoleto_com_justificativa_e_auditoria(self):
        # TED_B não tem NC; um PF fora do consolidado deixa de ser divergência: tira os PF => "sem base".
        self.conn.execute("DELETE FROM documento_pf WHERE chave_ted = ?", (TED_B,))
        self.conn.commit()
        alerta_id = self._alerta(TIPO_PF_DIVERGE_CONSOLIDADO, TED_B, chave=TED_B)
        resultado = reavaliar_alertas(self.conn)
        status, responsavel, justificativa, data_resolucao = self._estado(alerta_id)
        self.assertEqual(status, "resolvido")
        self.assertEqual(responsavel, "sistema")
        self.assertTrue(justificativa.startswith("Regra revisada em 08/10/2026:"))
        self.assertTrue(data_resolucao)
        registros = [
            r for r in historico_auditoria(self.conn, ENTIDADE_ALERTA, alerta_id)
            if r.acao == ACAO_ALERTA_STATUS_ALTERADO
        ]
        self.assertEqual(len(registros), 1)
        self.assertEqual(registros[0].valor_anterior["status"], "aberto")
        self.assertEqual(registros[0].valor_novo["status"], "resolvido")
        self.assertEqual(registros[0].usuario, "sistema")
        self.assertEqual(resultado.fechados_por_tipo, {TIPO_PF_DIVERGE_CONSOLIDADO: 1})
        resumo = historico_auditoria(self.conn, ENTIDADE_ALERTA, "reavaliacao")[-1].valor_novo
        self.assertEqual(resumo["fechados"], 1)
        self.assertEqual(resumo["fechados_por_tipo"], {TIPO_PF_DIVERGE_CONSOLIDADO: 1})

    def test_fecha_alerta_antigo_de_ug_por_nc(self):
        self.conn.execute(
            "INSERT INTO documento_nc (chave_nc_documento, numero_nc, chave_ted, data_emissao, operacao, "
            "valor_original_total, valor_assinado_total, quantidade_linhas, status_relacionamento, import_batch_id) "
            "VALUES ('K1', '2024NC000001', ?, '2024-01-01', '+', '10.00', '10.00', 1, 'PARCIAL', 1)",
            (TED_A,),
        )
        self.conn.commit()
        antigo = self._alerta(TIPO_NC_UG_EMITENTE_AUSENTE, "K1", chave=TED_A)
        reavaliar_alertas(self.conn)
        self.assertEqual(self._estado(antigo)[0], "resolvido")
        self.assertIn(f"ted:{TED_A}", self._alertas(TIPO_NC_UG_EMITENTE_AUSENTE))
        novo = self.conn.execute(
            "SELECT status FROM alerta WHERE tipo = ? AND documento = ?",
            (TIPO_NC_UG_EMITENTE_AUSENTE, f"ted:{TED_A}"),
        ).fetchone()
        self.assertEqual(novo[0], "aberto")

    def test_mantem_alerta_ainda_valido(self):
        alerta_id = self._alerta(TIPO_PF_DIVERGE_CONSOLIDADO, TED_A, chave=TED_A)
        reavaliar_alertas(self.conn)
        self.assertEqual(self._estado(alerta_id)[0], "aberto")

    def test_nao_fecha_tipos_nao_revistos(self):
        alerta_id = self._alerta(TIPO_TED_CREDITO_SEM_EMPENHO, TED_B, chave=TED_B)
        resultado = reavaliar_alertas(self.conn)
        self.assertEqual(self._estado(alerta_id)[0], "aberto")
        self.assertNotIn(TIPO_TED_CREDITO_SEM_EMPENHO, resultado.fechados_por_tipo)

    def test_resolvido_manual_nao_reabre(self):
        alerta_id = self._alerta(TIPO_PF_DIVERGE_CONSOLIDADO, TED_A, status="resolvido", chave=TED_A)
        antes = self._estado(alerta_id)
        reavaliar_alertas(self.conn)
        # O resolvido fica intacto (não é reaberto). Pela deduplicação existente (só entre não resolvidos), a
        # condição ainda verdadeira gera UM alerta novo, e só um: a segunda execução não cria outro.
        self.assertEqual(self._estado(alerta_id), antes)
        self.assertEqual(self._alertas(TIPO_PF_DIVERGE_CONSOLIDADO), [TED_A, TED_A])
        reavaliar_alertas(self.conn)
        self.assertEqual(self._alertas(TIPO_PF_DIVERGE_CONSOLIDADO), [TED_A, TED_A])

    def test_reavaliacao_idempotente(self):
        self.conn.execute("DELETE FROM documento_pf WHERE chave_ted = ?", (TED_B,))
        self._alerta(TIPO_PF_DIVERGE_CONSOLIDADO, TED_B, chave=TED_B)
        primeira = reavaliar_alertas(self.conn)
        self.assertEqual(sum(primeira.fechados_por_tipo.values()), 1)
        total = self.conn.execute("SELECT COUNT(*) FROM alerta").fetchone()[0]
        segunda = reavaliar_alertas(self.conn)
        self.assertEqual(segunda.fechados_por_tipo, {})
        self.assertEqual(segunda.total, 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM alerta").fetchone()[0], total)


if __name__ == "__main__":
    unittest.main()
