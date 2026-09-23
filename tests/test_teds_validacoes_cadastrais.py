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
    PRAZO_SEM_MOVIMENTACAO_DIAS,
    TIPO_TED_SEM_MOVIMENTACAO,
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
#: As regras antigas são testadas com a regra de "sem movimentação" desligada (prazo enorme), para cada
#: teste continuar falando de uma regra só; a regra nova tem os testes próprios mais abaixo.
SEM_LIMITE = 10**6
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
    return [a.tipo for a in gerar_alertas_cadastrais(list(teds), list(documentos), HOJE, SEM_LIMITE)]


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
            [_ted(inicio_vigencia=date(2028, 1, 1), fim_vigencia=date(2027, 1, 1))], [], HOJE, SEM_LIMITE
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
        alertas = gerar_alertas_cadastrais([_ted(), outro], [], HOJE, SEM_LIMITE)
        self.assertEqual([a.tipo for a in alertas], [TIPO_SIAFI_EM_MULTIPLOS_TEDS])
        self.assertEqual(alertas[0].documento, "1ABDKU")
        self.assertIn("17352", alertas[0].descricao)
        self.assertIn("99999", alertas[0].descricao)

    def test_documento_antes_do_inicio_e_depois_do_fim(self):
        antes = _doc(date(2024, 12, 31), chave="A")
        depois = _doc(date(2028, 1, 1), chave="B")
        alertas = gerar_alertas_cadastrais([_ted()], [antes, depois], HOJE, SEM_LIMITE)
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
        self.assertEqual(sincronizar_alertas_cadastrais(self.conn, HOJE, SEM_LIMITE), [])

    def test_pf_fora_da_vigencia_gera_um_alerta_unico_e_o_documento_continua_no_banco(self):
        self._pf("PF1", "2019-05-10")
        self.assertEqual(len(sincronizar_alertas_cadastrais(self.conn, HOJE, SEM_LIMITE)), 1)
        self.assertEqual(sincronizar_alertas_cadastrais(self.conn, HOJE, SEM_LIMITE), [])
        self.assertEqual(self._abertos(), [TIPO_DOCUMENTO_FORA_DA_VIGENCIA])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documento_pf").fetchone()[0], 1)

    def test_nc_de_ted_desconhecido_ou_sem_ted_e_ignorada(self):
        self.conn.execute(
            """INSERT INTO documento_nc (chave_nc_documento, chave_ted, numero_nc, data_emissao, operacao,
                 valor_original_total, valor_assinado_total, quantidade_linhas, status_relacionamento, import_batch_id)
               VALUES ('orfa', NULL, 'NCX', '2001-01-01', '+', '1.00', '1.00', 1, 'OK', 1)"""
        )
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_cadastrais(self.conn, HOJE, SEM_LIMITE), [])

    def test_alerta_nao_fecha_sozinho_quando_o_problema_some(self):
        self.conn.execute("UPDATE ted SET fim_vigencia = '2026-01-01'")
        self.conn.commit()
        self.assertEqual(len(sincronizar_alertas_cadastrais(self.conn, HOJE, SEM_LIMITE)), 1)
        self.conn.execute("UPDATE ted SET fim_vigencia = '2027-12-31'")
        self.conn.commit()
        self.assertEqual(sincronizar_alertas_cadastrais(self.conn, HOJE, SEM_LIMITE), [])
        self.assertEqual(self._abertos(), [TIPO_TED_VENCIDO_EM_EXECUCAO])

    def test_data_invalida_no_banco_nao_quebra_a_sincronizacao(self):
        self._pf("PF1", "não é data")
        self.assertEqual(sincronizar_alertas_cadastrais(self.conn, HOJE, SEM_LIMITE), [])


class SemMovimentacaoTests(unittest.TestCase):
    """TED em execução sem NC/PF emitida dentro do prazo (padrão 180 dias)."""

    def _alertas(self, teds, documentos=(), **kw):
        alertas = gerar_alertas_cadastrais(list(teds), list(documentos), HOJE, **kw)
        return [a for a in alertas if a.tipo == TIPO_TED_SEM_MOVIMENTACAO]

    def test_prazo_padrao_e_180_dias(self):
        self.assertEqual(PRAZO_SEM_MOVIMENTACAO_DIAS, 180)

    def test_ultima_movimentacao_recente_nao_gera_alerta(self):
        self.assertEqual(self._alertas([_ted()], [_doc(date(2026, 8, 1))]), [])

    def test_exatamente_no_limite_ainda_nao_gera_e_um_dia_depois_gera(self):
        limite = date(2026, 3, 27)  # 180 dias antes de 23/09/2026
        self.assertEqual((HOJE - limite).days, 180)
        self.assertEqual(self._alertas([_ted()], [_doc(limite)]), [])
        (alerta,) = self._alertas([_ted()], [_doc(date(2026, 3, 26))])
        self.assertEqual(alerta.gravidade, "media")
        self.assertEqual(alerta.documento, CH)
        self.assertIn("26/03/2026", alerta.descricao)

    def test_conta_a_movimentacao_mais_recente_entre_nc_e_pf(self):
        documentos = [_doc(date(2024, 1, 1), tipo="NC", chave="A"), _doc(date(2026, 9, 1), tipo="PF", chave="B")]
        self.assertEqual(self._alertas([_ted()], documentos), [])

    def test_so_ted_em_execucao_e_avaliado(self):
        ted = _ted(estado_atual="Termo Finalizado")
        self.assertEqual(self._alertas([ted], [_doc(date(2020, 1, 1))]), [])

    def test_sem_documento_usa_o_inicio_da_vigencia_como_referencia(self):
        recente = _ted(inicio_vigencia=date(2026, 8, 1))
        self.assertEqual(self._alertas([recente]), [])  # recém-iniciado: ainda não é "sem movimentação"
        (alerta,) = self._alertas([_ted(inicio_vigencia=date(2025, 1, 1))])
        self.assertIn("nenhuma NC/PF emitida desde o início da vigência (01/01/2025)", alerta.descricao)

    def test_sem_documento_e_sem_inicio_da_vigencia_gera_alerta(self):
        (alerta,) = self._alertas([_ted(inicio_vigencia=None)])
        self.assertIn("sem data de início da vigência", alerta.descricao)

    def test_documento_sem_data_ou_de_data_futura_nao_conta_como_movimentacao(self):
        documentos = [_doc(None, chave="A"), _doc(date(2027, 1, 1), chave="B")]
        self.assertEqual(len(self._alertas([_ted(inicio_vigencia=date(2025, 1, 1))], documentos)), 1)

    def test_prazo_e_parametrizavel(self):
        documentos = [_doc(date(2026, 8, 1))]
        self.assertEqual(len(self._alertas([_ted()], documentos, prazo_sem_movimentacao_dias=30)), 1)
        self.assertEqual(self._alertas([_ted()], documentos, prazo_sem_movimentacao_dias=90), [])

    def test_sincronizacao_gera_um_alerta_unico_sem_fechar_sozinho(self):
        conn = conectar(":memory:")
        try:
            conn.execute(
                "INSERT INTO ted (chave_ted, ted, codigo_siafi, estado_atual, inicio_vigencia, fim_vigencia, "
                "ug_descentralizadora) VALUES (?, '17352', '1ABDKU', 'Termo em Execução', '2025-01-01', '2027-12-31', '153165')",
                (CH,),
            )
            conn.commit()
            self.assertEqual(len(sincronizar_alertas_cadastrais(conn, HOJE)), 1)
            self.assertEqual(sincronizar_alertas_cadastrais(conn, HOJE), [])
            # Movimentação nova chega, mas o alerta só fecha por ação humana.
            conn.execute(
                """INSERT INTO documento_pf (chave_ted, ug_emitente, numero_pf, data_emissao, operacao,
                     valor_original, valor_assinado, import_batch_id, linha_origem)
                   VALUES (?, '153165', 'PF9', '2026-09-01', '+', '1.00', '1.00', 1, '{}')""",
                (CH,),
            )
            conn.commit()
            self.assertEqual(sincronizar_alertas_cadastrais(conn, HOJE), [])
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM alerta WHERE tipo = ? AND status != 'resolvido'", (TIPO_TED_SEM_MOVIMENTACAO,)).fetchone()[0],
                1,
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
