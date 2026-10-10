"""Integração dos totais de TEDs com vínculos de empenho pendentes.

O conflito continua rastreável nas consultas e nos alertas, mas nenhuma medida financeira
pode contabilizar a mesma NE em mais de um TED enquanto o vínculo não for resolvido.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from src.teds_alertas import registrar_decisao_vinculo_ne, sincronizar_alertas_multiplos_teds
from src.teds_normalizacao import chave_empenho, chave_ted, valor_para_texto
from src.teds_schema import conectar
from src.teds_ui import (
    alertas_de_ne_para_ted,
    atualizar_status_alerta,
    calcular_cobertura_relacionamentos,
    carregar_teds,
    data_br,
    situacao_conciliacao,
    soma_tg_por_teds,
    vinculos_ne,
)

class DataBrTests(unittest.TestCase):
    def test_formata_data_e_data_hora_iso(self):
        self.assertEqual(data_br('2026-03-05'), '05/03/2026')
        self.assertEqual(data_br('2026-03-05T14:30:59+00:00', com_hora=True), '05/03/2026 14:30')
        self.assertEqual(data_br('2026-03-05T14:30:59'), '05/03/2026')

    def test_nulo_vazio_e_texto_nao_data(self):
        self.assertEqual(data_br(None), '—')
        self.assertEqual(data_br(''), '—')
        self.assertEqual(data_br('Em análise'), 'Em análise')
        self.assertEqual(data_br('05/03/2026'), '05/03/2026')


TED_17352 = chave_ted("17352", "1ABDKU")
TED_17454 = chave_ted("17454", "1ABDKQ")
NE_422 = chave_empenho("153165", "15239", "2026NE000422")
NE_427 = chave_empenho("153165", "15239", "2026NE000427")


class TotaisComVinculoPendenteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = conectar(":memory:")
        for chave, ted, siafi in (
            (TED_17352, "17352", "1ABDKU"),
            (TED_17454, "17454", "1ABDKQ"),
        ):
            self.conn.execute(
                "INSERT INTO ted (chave_ted, ted, codigo_siafi) VALUES (?, ?, ?)",
                (chave, ted, siafi),
            )

        for chave_ted_vinculo, chave_ne, numero_ne, valor in (
            (TED_17352, NE_422, "2026NE000422", Decimal("388300.00")),
            (TED_17454, NE_422, "2026NE000422", Decimal("388300.00")),
            (TED_17454, NE_427, "2026NE000427", Decimal("154496.00")),
        ):
            self.conn.execute(
                """
                INSERT INTO vinculo_ne
                    (chave_ted, chave_empenho, ug_emitente, gestao_emitente, numero_ne,
                     valor_ne, import_batch_id, linha_origem)
                VALUES (?, ?, '153165', '15239', ?, ?, 1, '{}')
                """,
                (chave_ted_vinculo, chave_ne, numero_ne, valor_para_texto(valor)),
            )

        for numero_ne, liquidado, pago in (
            ("2026NE000422", Decimal("100000.00"), Decimal("90000.00")),
            ("2026NE000427", Decimal("50000.00"), Decimal("40000.00")),
        ):
            self.conn.execute(
                """
                INSERT INTO execucao_tg
                    (numero_completo_ne, liquidado, pago, ano_lancamento, mes_lancamento,
                     import_batch_id, linha_origem)
                VALUES (?, ?, ?, 2026, 8, 1, '{}')
                """,
                (numero_ne, valor_para_texto(liquidado), valor_para_texto(pago)),
            )
        self.conn.commit()
        sincronizar_alertas_multiplos_teds(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_empenhado_pendente_fica_fora_dos_totais_por_ted(self) -> None:
        por_chave = carregar_teds(self.conn).set_index("chave_ted")

        self.assertEqual(por_chave.loc[TED_17352, "empenhado"], Decimal("0"))
        self.assertEqual(por_chave.loc[TED_17454, "empenhado"], Decimal("154496.00"))

    def test_execucao_tg_da_ne_pendente_fica_fora_dos_totais(self) -> None:
        liquidado, pago, tem_dado = soma_tg_por_teds(self.conn, {TED_17352, TED_17454})

        self.assertTrue(tem_dado)
        self.assertEqual(liquidado, Decimal("50000.00"))
        self.assertEqual(pago, Decimal("40000.00"))

    def test_ne_pendente_continua_visivel_com_alerta_nos_dois_teds(self) -> None:
        for chave in (TED_17352, TED_17454):
            numeros = {linha[0] for linha in vinculos_ne(self.conn, chave)}
            self.assertIn("2026NE000422", numeros)

            alertas = alertas_de_ne_para_ted(self.conn, chave)
            self.assertEqual(len(alertas), 1)
            self.assertEqual(alertas[0].gravidade, "alta")
            self.assertEqual(alertas[0].documento, NE_422)

    def test_pendencia_tem_prioridade_sobre_fonte_ausente_na_conciliacao(self) -> None:
        situacao = situacao_conciliacao(
            tem_pendencia=True,
            fonte_ausente=True,
            diferenca=None,
            tolerancia=Decimal("0.01"),
        )

        self.assertEqual(situacao, "Conferência necessária")

    def test_apos_decisao_so_ted_escolhido_recebe_empenhado_e_execucao_tg(self) -> None:
        alerta_id = self.conn.execute(
            "SELECT id FROM alerta WHERE documento = ?", (NE_422,)
        ).fetchone()[0]
        registrar_decisao_vinculo_ne(
            self.conn,
            alerta_id=alerta_id,
            chave_empenho=NE_422,
            chave_ted_escolhida=TED_17352,
            responsavel="Maria Silva",
            justificativa="Conferido no processo administrativo.",
        )

        por_chave = carregar_teds(self.conn).set_index("chave_ted")
        self.assertEqual(por_chave.loc[TED_17352, "empenhado"], Decimal("388300.00"))
        self.assertEqual(por_chave.loc[TED_17454, "empenhado"], Decimal("154496.00"))

        liquidado_17352, pago_17352, tem_17352 = soma_tg_por_teds(self.conn, {TED_17352})
        self.assertTrue(tem_17352)
        self.assertEqual(liquidado_17352, Decimal("100000.00"))
        self.assertEqual(pago_17352, Decimal("90000.00"))

        liquidado_17454, pago_17454, tem_17454 = soma_tg_por_teds(self.conn, {TED_17454})
        self.assertTrue(tem_17454)
        self.assertEqual(liquidado_17454, Decimal("50000.00"))
        self.assertEqual(pago_17454, Decimal("40000.00"))

    def test_alerta_resolvido_permanece_no_historico_dos_dois_teds(self) -> None:
        alerta_id = self.conn.execute(
            "SELECT id FROM alerta WHERE documento = ?", (NE_422,)
        ).fetchone()[0]
        registrar_decisao_vinculo_ne(
            self.conn,
            alerta_id=alerta_id,
            chave_empenho=NE_422,
            chave_ted_escolhida=TED_17352,
            responsavel="Maria Silva",
            justificativa="Conferido no processo administrativo.",
        )

        for chave in (TED_17352, TED_17454):
            alertas = alertas_de_ne_para_ted(self.conn, chave)
            self.assertEqual(len(alertas), 1)
            self.assertEqual(alertas[0].status, "resolvido")

    def test_alerta_de_vinculo_multiplo_nao_pode_ser_resolvido_sem_decisao(self) -> None:
        alerta_id = self.conn.execute(
            "SELECT id FROM alerta WHERE documento = ?", (NE_422,)
        ).fetchone()[0]

        with self.assertRaisesRegex(ValueError, "decisão explícita"):
            atualizar_status_alerta(
                self.conn,
                alerta_id,
                "resolvido",
                responsavel="Maria Silva",
                justificativa="Tentativa sem escolher um TED.",
            )

        status = self.conn.execute(
            "SELECT status FROM alerta WHERE id = ?", (alerta_id,)
        ).fetchone()[0]
        self.assertEqual(status, "aberto")


class CoberturaRelacionamentosTests(unittest.TestCase):
    """§13 do briefing — cobertura de relacionamentos, incluindo o valor financeiro dos
    documentos sem TED (não só a contagem de linhas)."""

    def setUp(self) -> None:
        self.conn = conectar(":memory:")

    def tearDown(self) -> None:
        self.conn.close()

    def _inserir_documento_nc(self, chave: str, chave_ted_valor, status_relacionamento, valor) -> None:
        self.conn.execute(
            """
            INSERT INTO documento_nc
                (chave_nc_documento, chave_ted, numero_nc, operacao, valor_original_total,
                 valor_assinado_total, quantidade_linhas, status_relacionamento, import_batch_id)
            VALUES (?, ?, ?, '+', ?, ?, 1, ?, 1)
            """,
            (chave, chave_ted_valor, chave, valor_para_texto(valor), valor_para_texto(valor), status_relacionamento),
        )

    def test_documento_nc_sem_ted_conta_como_nao_relacionado_com_valor(self) -> None:
        self._inserir_documento_nc("doc-1", TED_17352, "OK", Decimal("100.00"))
        self._inserir_documento_nc("doc-2", None, "OK", Decimal("50.00"))
        self.conn.commit()

        cobertura = calcular_cobertura_relacionamentos(self.conn)

        self.assertEqual(cobertura.pct_nc_relacionadas, 0.5)
        self.assertEqual(cobertura.qtd_documentos_nao_relacionados, 1)
        self.assertEqual(cobertura.valor_nao_relacionado, Decimal("50.00"))

    def test_documento_nc_parcial_e_contado_separado_de_nao_relacionado(self) -> None:
        # PARCIAL (UG emitente ausente) é uma lacuna diferente de "sem TED" — um documento pode
        # ter TED conhecido e ainda assim ser PARCIAL (ver regra 4.5 do briefing).
        self._inserir_documento_nc("doc-1", TED_17352, "PARCIAL", Decimal("100.00"))
        self.conn.commit()

        cobertura = calcular_cobertura_relacionamentos(self.conn)

        self.assertEqual(cobertura.qtd_documentos_parciais, 1)
        self.assertEqual(cobertura.qtd_documentos_nao_relacionados, 0)
        self.assertEqual(cobertura.valor_nao_relacionado, Decimal("0"))

    def test_percentuais_sao_none_quando_nao_ha_documento_nenhum(self) -> None:
        cobertura = calcular_cobertura_relacionamentos(self.conn)

        self.assertIsNone(cobertura.pct_nc_relacionadas)
        self.assertIsNone(cobertura.pct_pf_relacionadas)
        self.assertIsNone(cobertura.pct_ne_relacionadas)
        self.assertEqual(cobertura.valor_nao_relacionado, Decimal("0"))

    def test_ne_pendente_nao_conta_como_relacionada_ate_decisao(self) -> None:
        self.conn.execute(
            "INSERT INTO ted (chave_ted, ted, codigo_siafi) VALUES (?, '17352', '1ABDKU')", (TED_17352,)
        )
        self.conn.execute(
            "INSERT INTO ted (chave_ted, ted, codigo_siafi) VALUES (?, '17454', '1ABDKQ')", (TED_17454,)
        )
        for chave_ted_vinculo in (TED_17352, TED_17454):
            self.conn.execute(
                """
                INSERT INTO vinculo_ne
                    (chave_ted, chave_empenho, ug_emitente, gestao_emitente, numero_ne,
                     valor_ne, status_validacao, import_batch_id, linha_origem)
                VALUES (?, ?, '153165', '15239', '2026NE000422', ?, 'pendente', 1, '{}')
                """,
                (chave_ted_vinculo, NE_422, valor_para_texto(Decimal("388300.00"))),
            )
        self.conn.commit()

        cobertura = calcular_cobertura_relacionamentos(self.conn)

        self.assertEqual(cobertura.pct_ne_relacionadas, 0.0)

    def test_ne_relacionada_ao_tesouro_gerencial(self) -> None:
        self.conn.execute(
            "INSERT INTO ted (chave_ted, ted, codigo_siafi) VALUES (?, '17352', '1ABDKU')", (TED_17352,)
        )
        self.conn.execute(
            """
            INSERT INTO vinculo_ne
                (chave_ted, chave_empenho, ug_emitente, gestao_emitente, numero_ne,
                 valor_ne, status_validacao, import_batch_id, linha_origem)
            VALUES (?, ?, '153165', '15239', '2026NE000422', ?, 'ok', 1, '{}')
            """,
            (TED_17352, NE_422, valor_para_texto(Decimal("388300.00"))),
        )
        self.conn.execute(
            "INSERT INTO execucao_tg (numero_completo_ne, ano_lancamento, mes_lancamento, "
            "import_batch_id, linha_origem) VALUES ('2026NE000422', 2026, 8, 1, '{}')"
        )
        self.conn.commit()

        cobertura = calcular_cobertura_relacionamentos(self.conn)

        self.assertEqual(cobertura.pct_ne_relacionadas, 1.0)
        self.assertEqual(cobertura.pct_ne_no_tesouro_gerencial, 1.0)


if __name__ == "__main__":
    unittest.main()
