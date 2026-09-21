"""
Testes de `src/teds_alertas.py` com o caso real documentado no briefing: a NE
2026NE000422 (UG 153165, gestão 15239, R$ 388.300,00) cadastrada tanto no TED 17352
(SIAFI 1ABDKU) quanto no TED 17454 (SIAFI 1ABDKQ), que também tem a NE 2026NE000427
(R$ 154.496,00) sem conflito.
"""

from __future__ import annotations

import sqlite3
import unittest
from decimal import Decimal

from src.teds_alertas import (
    STATUS_DESCARTADO,
    TIPO_EMPENHO_MULTIPLOS_TEDS,
    TIPO_NC_UG_EMITENTE_AUSENTE,
    DocumentoNC,
    VinculoNE,
    detectar_documentos_nc_parciais,
    detectar_ne_em_multiplos_teds,
    gerar_alertas_nc_parcial,
    gerar_alertas_ne_multiplos_teds,
    carregar_decisoes_vinculo_ne,
    registrar_decisao_vinculo_ne,
    sincronizar_alertas_multiplos_teds,
    sincronizar_alertas_nc_parcial,
    total_empenhado_por_ted,
)
from src.teds_normalizacao import chave_empenho, chave_ted, valor_para_texto
from src.teds_schema import conectar

TED_17352 = chave_ted("17352", "1ABDKU")
TED_17454 = chave_ted("17454", "1ABDKQ")
NE_422 = chave_empenho("153165", "15239", "2026NE000422")
NE_427 = chave_empenho("153165", "15239", "2026NE000427")


def _vinculos_do_caso() -> list[VinculoNE]:
    return [
        VinculoNE(chave_ted=TED_17352, chave_empenho=NE_422, numero_ne="2026NE000422", valor_ne=Decimal("388300.00")),
        VinculoNE(chave_ted=TED_17454, chave_empenho=NE_427, numero_ne="2026NE000427", valor_ne=Decimal("154496.00")),
        VinculoNE(chave_ted=TED_17454, chave_empenho=NE_422, numero_ne="2026NE000422", valor_ne=Decimal("388300.00")),
    ]


class DeteccaoPuraTests(unittest.TestCase):
    def test_detecta_apenas_a_ne_duplicada(self):
        pendentes = detectar_ne_em_multiplos_teds(_vinculos_do_caso())
        self.assertEqual(set(pendentes.keys()), {NE_422})
        self.assertEqual(len(pendentes[NE_422]), 2)

    def test_total_empenhado_exclui_vinculo_pendente_dos_dois_teds(self):
        vinculos = _vinculos_do_caso()
        pendentes = detectar_ne_em_multiplos_teds(vinculos)
        totais = total_empenhado_por_ted(vinculos, pendentes)

        # TED 17454 mantém só a NE 427 (sem conflito); TED 17352 fica sem nenhum total
        # enquanto a NE 422 estiver pendente de distribuição — nunca os R$ 388.300,00
        # contados nos dois ao mesmo tempo.
        self.assertEqual(totais.get(TED_17454, Decimal("0")), Decimal("154496.00"))
        self.assertEqual(totais.get(TED_17352, Decimal("0")), Decimal("0"))
        soma_total = sum(totais.values(), Decimal("0"))
        self.assertEqual(soma_total, Decimal("154496.00"))

    def test_gera_um_alerta_de_gravidade_alta_para_o_par(self):
        pendentes = detectar_ne_em_multiplos_teds(_vinculos_do_caso())
        alertas = gerar_alertas_ne_multiplos_teds(pendentes)
        self.assertEqual(len(alertas), 1)
        alerta = alertas[0]
        self.assertEqual(alerta.tipo, TIPO_EMPENHO_MULTIPLOS_TEDS)
        self.assertEqual(alerta.gravidade, "alta")
        self.assertEqual(alerta.documento, NE_422)
        self.assertIn(TED_17352, alerta.descricao)
        self.assertIn(TED_17454, alerta.descricao)

    def test_sem_conflito_nao_gera_alerta(self):
        vinculos = [
            VinculoNE(chave_ted=TED_17454, chave_empenho=NE_427, numero_ne="2026NE000427", valor_ne=Decimal("154496.00")),
        ]
        pendentes = detectar_ne_em_multiplos_teds(vinculos)
        self.assertEqual(pendentes, {})
        self.assertEqual(gerar_alertas_ne_multiplos_teds(pendentes), [])


class SincronizacaoComBancoTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")
        for v in _vinculos_do_caso():
            self.conn.execute(
                """
                INSERT INTO vinculo_ne
                    (chave_ted, chave_empenho, ug_emitente, gestao_emitente, numero_ne, valor_ne,
                     import_batch_id, linha_origem)
                VALUES (?, ?, '153165', '15239', ?, ?, 1, '{}')
                """,
                (v.chave_ted, v.chave_empenho, v.numero_ne, valor_para_texto(v.valor_ne)),
            )
        self.conn.execute(
            "INSERT INTO import_batch (id, tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, status) "
            "VALUES (1, 'teste', 'x.xlsx', 'hash', '2026-01-01T00:00:00', 'ok')"
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_marca_status_validacao_pendente_so_na_ne_conflitante(self):
        sincronizar_alertas_multiplos_teds(self.conn)
        status = dict(
            self.conn.execute(
                "SELECT chave_empenho, status_validacao FROM vinculo_ne"
            ).fetchall()
        )
        # NE_422 aparece duas vezes (uma por TED) — todas as linhas dela ficam pendentes.
        linhas_422 = self.conn.execute(
            "SELECT status_validacao FROM vinculo_ne WHERE chave_empenho = ?", (NE_422,)
        ).fetchall()
        self.assertTrue(all(s == "pendente" for (s,) in linhas_422))
        self.assertEqual(status[NE_427], "ok")

    def test_cria_alerta_aberto_uma_unica_vez(self):
        novos_primeira = sincronizar_alertas_multiplos_teds(self.conn)
        self.assertEqual(len(novos_primeira), 1)

        novos_segunda = sincronizar_alertas_multiplos_teds(self.conn)
        self.assertEqual(novos_segunda, [])

        abertos = self.conn.execute(
            "SELECT COUNT(*) FROM alerta WHERE tipo = ? AND status = 'aberto'",
            (TIPO_EMPENHO_MULTIPLOS_TEDS,),
        ).fetchone()[0]
        self.assertEqual(abertos, 1)

    def test_alerta_em_analise_nao_e_duplicado_por_nova_sincronizacao(self):
        # Um alerta marcado "em análise" (workflow humano da Central de Alertas) não pode ser
        # tratado como resolvido pela sincronização automática — reimportar o arquivo (ou
        # rodar a sincronização de novo) não pode criar um segundo alerta pro mesmo empenho
        # só porque o status saiu de 'aberto'.
        sincronizar_alertas_multiplos_teds(self.conn)
        self.conn.execute("UPDATE alerta SET status = 'em_analise' WHERE tipo = ?", (TIPO_EMPENHO_MULTIPLOS_TEDS,))
        self.conn.commit()

        novos = sincronizar_alertas_multiplos_teds(self.conn)
        self.assertEqual(novos, [])

        total = self.conn.execute(
            "SELECT COUNT(*) FROM alerta WHERE tipo = ?", (TIPO_EMPENHO_MULTIPLOS_TEDS,)
        ).fetchone()[0]
        self.assertEqual(total, 1)

    def test_decisao_mantem_so_ted_escolhido_contabilizavel_e_preserva_historico(self):
        sincronizar_alertas_multiplos_teds(self.conn)
        alerta_id = self.conn.execute(
            "SELECT id FROM alerta WHERE tipo = ?", (TIPO_EMPENHO_MULTIPLOS_TEDS,)
        ).fetchone()[0]

        decisao = registrar_decisao_vinculo_ne(
            self.conn,
            alerta_id=alerta_id,
            chave_empenho=NE_422,
            chave_ted_escolhida=TED_17352,
            responsavel="Maria Silva",
            justificativa="A documentação de origem identifica o TED 17352.",
        )

        status = dict(
            self.conn.execute(
                "SELECT chave_ted, status_validacao FROM vinculo_ne WHERE chave_empenho = ?",
                (NE_422,),
            ).fetchall()
        )
        self.assertEqual(status[TED_17352], "ok")
        self.assertEqual(status[TED_17454], STATUS_DESCARTADO)
        self.assertEqual(decisao.chave_ted_escolhida, TED_17352)
        self.assertEqual(decisao.teds_envolvidos, (TED_17352, TED_17454))

        historico = carregar_decisoes_vinculo_ne(self.conn, NE_422)
        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0].responsavel, "Maria Silva")
        alerta = self.conn.execute(
            "SELECT status, responsavel, justificativa FROM alerta WHERE id = ?", (alerta_id,)
        ).fetchone()
        self.assertEqual(alerta, ("resolvido", "Maria Silva", "A documentação de origem identifica o TED 17352."))

    def test_sincronizacao_preserva_decisao_vigente_sem_reabrir_alerta(self):
        sincronizar_alertas_multiplos_teds(self.conn)
        alerta_id = self.conn.execute(
            "SELECT id FROM alerta WHERE tipo = ?", (TIPO_EMPENHO_MULTIPLOS_TEDS,)
        ).fetchone()[0]
        registrar_decisao_vinculo_ne(
            self.conn,
            alerta_id=alerta_id,
            chave_empenho=NE_422,
            chave_ted_escolhida=TED_17454,
            responsavel="João Souza",
            justificativa="Conferência efetuada no processo de origem.",
        )

        novos = sincronizar_alertas_multiplos_teds(self.conn)

        self.assertEqual(novos, [])
        status = dict(
            self.conn.execute(
                "SELECT chave_ted, status_validacao FROM vinculo_ne WHERE chave_empenho = ?",
                (NE_422,),
            ).fetchall()
        )
        self.assertEqual(status[TED_17454], "ok")
        self.assertEqual(status[TED_17352], STATUS_DESCARTADO)
        total_alertas = self.conn.execute(
            "SELECT COUNT(*) FROM alerta WHERE tipo = ?", (TIPO_EMPENHO_MULTIPLOS_TEDS,)
        ).fetchone()[0]
        self.assertEqual(total_alertas, 1)

    def test_decisao_exige_responsavel_e_justificativa(self):
        sincronizar_alertas_multiplos_teds(self.conn)
        alerta_id = self.conn.execute(
            "SELECT id FROM alerta WHERE tipo = ?", (TIPO_EMPENHO_MULTIPLOS_TEDS,)
        ).fetchone()[0]

        with self.assertRaisesRegex(ValueError, "responsável"):
            registrar_decisao_vinculo_ne(
                self.conn,
                alerta_id=alerta_id,
                chave_empenho=NE_422,
                chave_ted_escolhida=TED_17352,
                responsavel=" ",
                justificativa="Vínculo conferido.",
            )
        with self.assertRaisesRegex(ValueError, "justificativa"):
            registrar_decisao_vinculo_ne(
                self.conn,
                alerta_id=alerta_id,
                chave_empenho=NE_422,
                chave_ted_escolhida=TED_17352,
                responsavel="Maria Silva",
                justificativa=" ",
            )

    def test_novo_ted_invalida_decisao_anterior_e_reabre_conferencia(self):
        sincronizar_alertas_multiplos_teds(self.conn)
        alerta_id = self.conn.execute(
            "SELECT id FROM alerta WHERE tipo = ?", (TIPO_EMPENHO_MULTIPLOS_TEDS,)
        ).fetchone()[0]
        registrar_decisao_vinculo_ne(
            self.conn,
            alerta_id=alerta_id,
            chave_empenho=NE_422,
            chave_ted_escolhida=TED_17352,
            responsavel="Maria Silva",
            justificativa="Conferência baseada nos dois vínculos existentes.",
        )
        terceiro_ted = chave_ted("18000", "1NOVO1")
        self.conn.execute(
            """
            INSERT INTO vinculo_ne
                (chave_ted, chave_empenho, ug_emitente, gestao_emitente, numero_ne,
                 valor_ne, import_batch_id, linha_origem)
            VALUES (?, ?, '153165', '15239', '2026NE000422', '388300.00', 1, '{}')
            """,
            (terceiro_ted, NE_422),
        )
        self.conn.commit()

        novos = sincronizar_alertas_multiplos_teds(self.conn)

        self.assertEqual(len(novos), 1)
        status = self.conn.execute(
            "SELECT DISTINCT status_validacao FROM vinculo_ne WHERE chave_empenho = ?",
            (NE_422,),
        ).fetchall()
        self.assertEqual(status, [("pendente",)])
        abertos = self.conn.execute(
            "SELECT COUNT(*) FROM alerta WHERE documento = ? AND status = 'aberto'", (NE_422,)
        ).fetchone()[0]
        self.assertEqual(abertos, 1)


class DetectaDocumentosNcParciaisTests(unittest.TestCase):
    def _documentos(self):
        return [
            DocumentoNC(
                chave_nc_documento="12172|1AAMPD|2025NC000265|+|2025-07-02",
                numero_nc="2025NC000265",
                chave_ted=TED_17352,
                status_relacionamento="PARCIAL",
            ),
            DocumentoNC(
                chave_nc_documento="17454|1ABDKQ|2026NC000101|+|2026-02-10",
                numero_nc="2026NC000101",
                chave_ted=TED_17454,
                status_relacionamento="OK",
            ),
        ]

    def test_detecta_so_os_parciais(self):
        parciais = detectar_documentos_nc_parciais(self._documentos())
        self.assertEqual(len(parciais), 1)
        self.assertEqual(parciais[0].numero_nc, "2025NC000265")

    def test_gera_um_alerta_de_gravidade_media_por_documento_parcial(self):
        parciais = detectar_documentos_nc_parciais(self._documentos())
        alertas = gerar_alertas_nc_parcial(parciais)
        self.assertEqual(len(alertas), 1)
        alerta = alertas[0]
        self.assertEqual(alerta.tipo, TIPO_NC_UG_EMITENTE_AUSENTE)
        self.assertEqual(alerta.gravidade, "media")
        self.assertEqual(alerta.documento, "12172|1AAMPD|2025NC000265|+|2025-07-02")
        self.assertIn("2025NC000265", alerta.descricao)

    def test_sem_documento_parcial_nao_gera_alerta(self):
        documentos = [self._documentos()[1]]  # só o OK
        parciais = detectar_documentos_nc_parciais(documentos)
        self.assertEqual(gerar_alertas_nc_parcial(parciais), [])


class SincronizacaoNcParcialComBancoTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")
        self.conn.execute(
            "INSERT INTO import_batch (id, tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, status) "
            "VALUES (1, 'teste', 'x.xlsx', 'hash', '2026-01-01T00:00:00', 'ok')"
        )
        self.conn.execute(
            """
            INSERT INTO documento_nc
                (chave_nc_documento, chave_ted, ted, codigo_siafi, numero_nc, ug_emitente,
                 data_emissao, operacao, valor_original_total, valor_assinado_total,
                 quantidade_linhas, status_relacionamento, import_batch_id)
            VALUES (?, ?, '12172', '1AAMPD', ?, NULL, '2025-07-02', '+', '559338.00', '559338.00', 1, 'PARCIAL', 1)
            """,
            ("12172|1AAMPD|2025NC000265|+|2025-07-02", TED_17352, "2025NC000265"),
        )
        self.conn.execute(
            """
            INSERT INTO documento_nc
                (chave_nc_documento, chave_ted, ted, codigo_siafi, numero_nc, ug_emitente,
                 data_emissao, operacao, valor_original_total, valor_assinado_total,
                 quantidade_linhas, status_relacionamento, import_batch_id)
            VALUES (?, ?, '17454', '1ABDKQ', ?, '154046', '2026-02-10', '+', '35300.00', '35300.00', 1, 'OK', 1)
            """,
            ("17454|1ABDKQ|2026NC000101|+|2026-02-10", TED_17454, "2026NC000101"),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_cria_alerta_aberto_uma_unica_vez(self):
        novos_primeira = sincronizar_alertas_nc_parcial(self.conn)
        self.assertEqual(len(novos_primeira), 1)

        novos_segunda = sincronizar_alertas_nc_parcial(self.conn)
        self.assertEqual(novos_segunda, [])

        abertos = self.conn.execute(
            "SELECT COUNT(*) FROM alerta WHERE tipo = ? AND status = 'aberto'",
            (TIPO_NC_UG_EMITENTE_AUSENTE,),
        ).fetchone()[0]
        self.assertEqual(abertos, 1)

    def test_documento_ok_nao_gera_alerta(self):
        sincronizar_alertas_nc_parcial(self.conn)
        documento = self.conn.execute(
            "SELECT documento FROM alerta WHERE tipo = ?", (TIPO_NC_UG_EMITENTE_AUSENTE,)
        ).fetchone()[0]
        self.assertEqual(documento, "12172|1AAMPD|2025NC000265|+|2025-07-02")


if __name__ == "__main__":
    unittest.main()
