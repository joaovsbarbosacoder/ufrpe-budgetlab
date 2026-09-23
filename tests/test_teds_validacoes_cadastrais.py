"""
Testes das validações cadastrais e de vigência do TED (`src/teds_alertas.py`, briefing seção 7):
vigência invertida, UG descentralizadora ausente, SIAFI em mais de um TED, documento emitido
fora da vigência e TED vencido ainda em execução.

Todas descritivas: só geram alerta; nunca excluem documento, nunca fecham alerta sozinhas.
"""

from __future__ import annotations

import unittest
from datetime import date

from src.teds_alertas import (
    TIPO_DOCUMENTO_FORA_DA_VIGENCIA,
    TIPO_SIAFI_EM_MULTIPLOS_TEDS,
    TIPO_TED_SEM_UG_DESCENTRALIZADORA,
    TIPO_TED_VENCIDO_EM_EXECUCAO,
    TIPO_TED_VIGENCIA_INVERTIDA,
    DocumentoDatado,
    TedCadastro,
    estado_em_execucao,
    gerar_alertas_cadastrais,
    sincronizar_alertas_cadastrais,
)
from src.teds_normalizacao import chave_ted
from src.teds_schema import conectar

HOJE = date(2026, 9, 23)
CH = chave_ted("17352", "1ABDKU")


def _ted(**mudancas):
    base = dict(
        chave_ted=CH, ted="17352", codigo_siafi="1ABDKU", estado_atual="Termo em Execução",
        inicio_vigencia=date(2025, 1, 1), fim_vigencia=date(2027, 12, 31), ug_descentralizadora="153165",
    )
    base.update(mudancas)
    return TedCadastro(**base)


def _doc(data, tipo="PF", chave="PF1", ted=CH):
    return DocumentoDatado(tipo, chave, "0001", ted, data)


def _tipos(teds, documentos=()):
    return [a.tipo for a in gerar_alertas_cadastrais(list(teds), list(documentos), HOJE)]


class EstadoEmExecucaoTests(unittest.TestCase):
    def test_reconhece_sem_diferenca_de_acento_ou_caixa(self):
        self.assertTrue(estado_em_execucao("Termo em Execução"))
        self.assertTrue(estado_em_execucao("  TERMO EM EXECUCAO "))

    def test_outros_estados_nao_sao_execucao(self):
        for estado in ("Termo Finalizado", "Comprovado no SIAFI.", "Em Diligência", None, ""):
            self.assertFalse(estado_em_execucao(estado), estado)


class RegrasPurasTests(unittest.TestCase):
    def test_ted_regular_nao_gera_alerta(self):
        self.assertEqual(_tipos([_ted()], [_doc(date(2026, 3, 1))]), [])

    def test_vigencia_invertida(self):
        alertas = gerar_alertas_cadastrais(
            [_ted(inicio_vigencia=date(2028, 1, 1), fim_vigencia=date(2027, 1, 1))], [], HOJE
        )
        self.assertEqual([a.tipo for a in alertas], [TIPO_TED_VIGENCIA_INVERTIDA])
        self.assertEqual(alertas[0].gravidade, "alta")
        self.assertIn("01/01/2028", alertas[0].descricao)

    def test_inicio_igual_ao_fim_nao_e_invertida(self):
        self.assertEqual(
            _tipos([_ted(estado_atual="Termo Finalizado", inicio_vigencia=date(2026, 5, 5), fim_vigencia=date(2026, 5, 5))]), []
        )

    def test_vigencia_sem_data_nao_gera_alerta_de_vigencia(self):
        self.assertEqual(_tipos([_ted(inicio_vigencia=None, fim_vigencia=None)], [_doc(date(2020, 1, 1))]), [])

    def test_ug_descentralizadora_ausente_ou_vazia(self):
        self.assertEqual(_tipos([_ted(ug_descentralizadora=None)]), [TIPO_TED_SEM_UG_DESCENTRALIZADORA])
        self.assertEqual(_tipos([_ted(ug_descentralizadora="  ")]), [TIPO_TED_SEM_UG_DESCENTRALIZADORA])

    def test_ted_vencido_em_execucao(self):
        teds = [_ted(fim_vigencia=date(2026, 9, 22))]
        self.assertEqual(_tipos(teds), [TIPO_TED_VENCIDO_EM_EXECUCAO])

    def test_ultimo_dia_de_vigencia_ainda_nao_esta_vencido(self):
        self.assertEqual(_tipos([_ted(fim_vigencia=HOJE)]), [])

    def test_ted_vencido_mas_finalizado_ou_comprovado_nao_gera_alerta(self):
        for estado in ("Termo Finalizado", "Comprovado no SIAFI."):
            teds = [_ted(estado_atual=estado, inicio_vigencia=date(2022, 1, 1), fim_vigencia=date(2024, 1, 1))]
            self.assertEqual(_tipos(teds), [], estado)

    def test_siafi_em_dois_teds(self):
        outro = _ted(chave_ted=chave_ted("99999", "1ABDKU"), ted="99999")
        alertas = gerar_alertas_cadastrais([_ted(), outro], [], HOJE)
        self.assertEqual([a.tipo for a in alertas], [TIPO_SIAFI_EM_MULTIPLOS_TEDS])
        self.assertEqual(alertas[0].documento, "1ABDKU")
        self.assertIn("17352", alertas[0].descricao)
        self.assertIn("99999", alertas[0].descricao)

    def test_documento_antes_do_inicio_e_depois_do_fim(self):
        antes = _doc(date(2024, 12, 31), chave="A")
        depois = _doc(date(2028, 1, 1), chave="B")
        alertas = gerar_alertas_cadastrais([_ted()], [antes, depois], HOJE)
        self.assertEqual([a.tipo for a in alertas], [TIPO_DOCUMENTO_FORA_DA_VIGENCIA] * 2)
        self.assertIn("antes do início", alertas[0].descricao)
        self.assertIn("depois do fim", alertas[1].descricao)

    def test_documento_nos_limites_da_vigencia_esta_dentro(self):
        self.assertEqual(_tipos([_ted()], [_doc(date(2025, 1, 1), chave="A"), _doc(date(2027, 12, 31), chave="B")]), [])

    def test_documento_sem_data_ou_de_ted_desconhecido_e_ignorado(self):
        self.assertEqual(_tipos([_ted()], [_doc(None), _doc(date(2000, 1, 1), ted="outro")]), [])


class SincronizacaoComBancoTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")
        self.conn.execute(
            "INSERT INTO import_batch (id, tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, status) "
            "VALUES (1, 'teste', 'x.xlsx', 'hash', '2026-01-01T00:00:00', 'ok')"
        )
        self.conn.execute(
            "INSERT INTO ted (chave_ted, ted, codigo_siafi, estado_atual, inicio_vigencia, fim_vigencia, "
            "ug_descentralizadora) VALUES (?, '17352', '1ABDKU', 'Termo em Execução', '2025-01-01', '2027-12-31', '153165')",
            (CH,),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _pf(self, numero, data):
        self.conn.execute(
            """INSERT INTO documento_pf (chave_ted, ug_emitente, numero_pf, data_emissao, operacao,
                 valor_original, valor_assinado, import_batch_id, linha_origem)
               VALUES (?, '153165', ?, ?, '+', '10.00', '10.00', 1, '{}')""",
            (CH, numero, data),
        )
        self.conn.commit()

    def _abertos(self):
        return [t for (t,) in self.conn.execute("SELECT tipo FROM alerta WHERE status != 'resolvido'")]

    def test_banco_regular_nao_gera_alerta(self):
        self._pf("PF1", "2026-02-01")
        self.assertEqual(sincronizar_alertas_cadastrais(self.conn, HOJE), [])

    def test_pf_fora_da_vigencia_gera_um_alerta_unico_e_o_documento_continua_no_banco(self):
        self._pf("PF1", "2019-05-10")
        self.assertEqual(len(sincronizar_alertas_cadastrais(self.conn, HOJE)), 1)
        self.assertEqual(sincronizar_alertas_cadastrais(self.conn, HOJE), [])
        self.assertEqual(self._abertos(), [TIPO_DOCUMENTO_FORA_DA_VIGENCIA])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documento_pf").fetchone()[0], 1)

    def test_nc_de_ted_desconhecido_ou_sem_ted_e_ignorada(self):
        self.conn.execute(
            """INSERT INTO documento_nc (chave_nc_documento, chave_ted, numero_nc, data_emissao, operacao,
                 valor_original_total, valor_assinado_total, quantidade_linhas, status_relacionamento, import_batch_id)
               VALUES ('orfa', NULL, 'NCX', '2001-01-01', '+', '1.00', '1.00', 1, 'OK', 1)"""
        )
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_cadastrais(self.conn, HOJE), [])

    def test_alerta_nao_fecha_sozinho_quando_o_problema_some(self):
        self.conn.execute("UPDATE ted SET fim_vigencia = '2026-01-01'")
        self.conn.commit()
        self.assertEqual(len(sincronizar_alertas_cadastrais(self.conn, HOJE)), 1)
        self.conn.execute("UPDATE ted SET fim_vigencia = '2027-12-31'")
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_cadastrais(self.conn, HOJE), [])
        self.assertEqual(self._abertos(), [TIPO_TED_VENCIDO_EM_EXECUCAO])

    def test_data_invalida_no_banco_nao_quebra_a_sincronizacao(self):
        self._pf("PF1", "não é data")
        self.assertEqual(sincronizar_alertas_cadastrais(self.conn, HOJE), [])


if __name__ == "__main__":
    unittest.main()
