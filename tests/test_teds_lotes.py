"""
Testes de `src/teds_lotes.py`: orquestração de importação sobre o SQLite. Cobre os critérios
de aceitação do briefing diretamente ligados à Fase 1:

  * reimportar o mesmo arquivo não duplica registros (idempotência por hash);
  * reimportar um arquivo diferente com a mesma linha atualiza em vez de duplicar
    (idempotência pela chave natural);
  * a NE 2026NE000422 é identificada automaticamente em dois TEDs (17352 e 17454) e sua
    execução não é somada duas vezes nos totais consolidados;
  * o TED 17454 preserva a NE 2026NE000427, sem conflito.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.teds_alertas import TIPO_EMPENHO_MULTIPLOS_TEDS
from src.teds_importacao_simec import AVISO_UG_EMITENTE_NC_AUSENTE, STATUS_RELACIONAMENTO_PARCIAL
from src.importacao_execucao_mensal import importar as importar_execucao_mensal
from src.teds_lotes import (
    ExecucaoMensalNaoImportada,
    importar_doc_nc,
    importar_doc_ne,
    importar_execucao_anual,
    sincronizar_execucao_tg,
    sincronizar_execucao_tg_atual,
    status_sincronizacao_execucao_tg,
)
from src.teds_normalizacao import chave_empenho, chave_ted, texto_para_valor
from src.teds_schema import conectar

TED_17352 = chave_ted("17352", "1ABDKU")
TED_17454 = chave_ted("17454", "1ABDKQ")
NE_422 = chave_empenho("153165", "15239", "2026NE000422")
NE_427 = chave_empenho("153165", "15239", "2026NE000427")

_LINHA_BASE_DOC_NE = {
    "Gestão Emitente - NE": "15239",
    "UG Executora Emitente - NE": "153165",
    "Descrição do Termo": "Termo de Execução Descentralizada",
    "Estado Atual": "Em execução",
    "Início da Vigência": "01/01/2026",
    "Fim da Vigência": "31/12/2027",
    "UG Descentralizadora": "154046",
}


def _df_doc_ne_caso_real() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {**_LINHA_BASE_DOC_NE, "Número do Empenho": "2026NE000422", "SIAFI": "1ABDKU", "TED": "17352", "Valor da NE": "388.300,00"},
            {**_LINHA_BASE_DOC_NE, "Número do Empenho": "2026NE000427", "SIAFI": "1ABDKQ", "TED": "17454", "Valor da NE": "154.496,00"},
            {**_LINHA_BASE_DOC_NE, "Número do Empenho": "2026NE000422", "SIAFI": "1ABDKQ", "TED": "17454", "Valor da NE": "388.300,00"},
        ]
    )


class ImportarDocNeCasoRealTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_identifica_ne_422_em_dois_teds_e_nao_soma_em_dobro(self):
        resultado = importar_doc_ne(self.conn, _df_doc_ne_caso_real(), "doc_ne.xlsx", b"conteudo-v1")
        self.assertFalse(resultado.ja_importado)
        self.assertEqual(resultado.inseridos, 3)

        linhas = self.conn.execute(
            "SELECT chave_ted, chave_empenho, status_validacao FROM vinculo_ne"
        ).fetchall()
        self.assertEqual(len(linhas), 3)

        status_por_par = {(ct, ce): sv for ct, ce, sv in linhas}
        self.assertEqual(status_por_par[(TED_17352, NE_422)], "pendente")
        self.assertEqual(status_por_par[(TED_17454, NE_422)], "pendente")
        self.assertEqual(status_por_par[(TED_17454, NE_427)], "ok")

        alerta = self.conn.execute(
            "SELECT gravidade, documento, status FROM alerta WHERE tipo = ?",
            (TIPO_EMPENHO_MULTIPLOS_TEDS,),
        ).fetchone()
        self.assertIsNotNone(alerta)
        gravidade, documento, status = alerta
        self.assertEqual(gravidade, "alta")
        self.assertEqual(documento, NE_422)
        self.assertEqual(status, "aberto")

    def test_reimportar_arquivo_identico_nao_duplica_nada(self):
        df = _df_doc_ne_caso_real()
        importar_doc_ne(self.conn, df, "doc_ne.xlsx", b"conteudo-v1")
        resultado_2 = importar_doc_ne(self.conn, df, "doc_ne.xlsx", b"conteudo-v1")

        self.assertTrue(resultado_2.ja_importado)
        total_vinculos = self.conn.execute("SELECT COUNT(*) FROM vinculo_ne").fetchone()[0]
        self.assertEqual(total_vinculos, 3)
        total_lotes = self.conn.execute(
            "SELECT COUNT(*) FROM import_batch WHERE tipo_relatorio = 'simec_doc_ne'"
        ).fetchone()[0]
        self.assertEqual(total_lotes, 1)
        total_alertas = self.conn.execute(
            "SELECT COUNT(*) FROM alerta WHERE tipo = ?", (TIPO_EMPENHO_MULTIPLOS_TEDS,)
        ).fetchone()[0]
        self.assertEqual(total_alertas, 1)

    def test_reimportar_arquivo_diferente_atualiza_em_vez_de_duplicar(self):
        importar_doc_ne(self.conn, _df_doc_ne_caso_real(), "doc_ne_v1.xlsx", b"conteudo-v1")

        df_corrigido = _df_doc_ne_caso_real()
        # Segunda extração já corrige o valor da NE 427 (ex.: reforço de empenho registrado).
        df_corrigido.loc[df_corrigido["Número do Empenho"] == "2026NE000427", "Valor da NE"] = "160.000,00"
        importar_doc_ne(self.conn, df_corrigido, "doc_ne_v2.xlsx", b"conteudo-v2")

        total_vinculos = self.conn.execute("SELECT COUNT(*) FROM vinculo_ne").fetchone()[0]
        self.assertEqual(total_vinculos, 3)  # atualizou, não duplicou

        valor = self.conn.execute(
            "SELECT valor_ne FROM vinculo_ne WHERE chave_ted = ? AND chave_empenho = ?",
            (TED_17454, NE_427),
        ).fetchone()[0]
        self.assertEqual(texto_para_valor(valor), Decimal("160000.00"))

        total_lotes = self.conn.execute(
            "SELECT COUNT(*) FROM import_batch WHERE tipo_relatorio = 'simec_doc_ne'"
        ).fetchone()[0]
        self.assertEqual(total_lotes, 2)  # histórico de lotes preservado (regra 11)


class ImportarExecucaoAnualTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_ted_17352_e_rodape_ignorado(self):
        df = pd.DataFrame(
            [
                {
                    "Ano de emissão": 2026,
                    "Descrição do Termo": "TED 17352",
                    "Estado Atual": "Em execução",
                    "Início da Vigência": "01/01/2026",
                    "Fim da Vigência": "31/12/2027",
                    "SIAFI": "1ABDKU",
                    "TED": "17352",
                    "UG Descentralizadora": "154046",
                    "Total NC Descentralização": "388.300,00",
                    "Total NC Devolução": "0,00",
                    "Total Descentralizado": "388.300,00",
                    "Total PF Repasse": "388.300,00",
                    "Total PF Devolução": "0,00",
                    "Total Repassado": "388.300,00",
                },
                {
                    "Ano de emissão": None,
                    "Descrição do Termo": "Total geral",
                    "SIAFI": None,
                    "TED": None,
                    "Total NC Descentralização": "388.300,00",
                    "Total NC Devolução": "0,00",
                    "Total Descentralizado": "388.300,00",
                    "Total PF Repasse": "388.300,00",
                    "Total PF Devolução": "0,00",
                    "Total Repassado": "388.300,00",
                },
            ]
        )
        resultado = importar_execucao_anual(self.conn, df, "execucao_anual.xlsx", b"conteudo")
        self.assertEqual(resultado.inseridos, 1)
        self.assertEqual(len(resultado.rejeitadas), 1)

        total = self.conn.execute(
            "SELECT total_descentralizado FROM execucao_anual WHERE chave_ted = ?",
            (TED_17352,),
        ).fetchone()[0]
        self.assertEqual(texto_para_valor(total), Decimal("388300.00"))

        ted_row = self.conn.execute(
            "SELECT descricao, ug_descentralizadora FROM ted WHERE chave_ted = ?", (TED_17352,)
        ).fetchone()
        self.assertEqual(ted_row, ("TED 17352", "154046"))


def _linha_doc_nc(**overrides):
    linha = {
        "Data de Emissão da NC": "02/07/2025",
        "Número da NC": "2025NC000265",
        "Operação": "( + )",
        "UG Emitente - NC": None,
        "Descrição do Termo": "Concessão PROAP 2023.",
        "Estado Atual": "Termo em Execução",
        "Fim da Vigência": "30/06/2027",
        "Início da Vigência": "29/05/2023",
        "SIAFI": "1AAMPD",
        "TED": 12172.0,
        "UG Descentralizadora": 150300.0,
        "Valor Total NC": 559338.0,
    }
    linha.update(overrides)
    return linha


class ImportarDocNcTests(unittest.TestCase):
    """Cobre o modelo de dois níveis de `documento_nc`/`documento_nc_linha` (ver docstring de
    `importar_doc_nc` em src/teds_lotes.py): linha sem UG emitente é importada com aviso, e o
    mesmo documento em várias linhas é preservado no detalhe e agregado corretamente."""

    def setUp(self):
        self.conn = conectar(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_nc_sem_ug_emitente_e_gravada_com_aviso_e_status_parcial(self):
        df = pd.DataFrame([_linha_doc_nc()])
        resultado = importar_doc_nc(self.conn, df, "doc_nc.xlsx", b"conteudo-v1")
        self.assertEqual(resultado.inseridos, 1)
        self.assertEqual(len(resultado.rejeitadas), 0)

        linha = self.conn.execute(
            "SELECT ug_emitente, status_relacionamento, avisos FROM documento_nc_linha"
        ).fetchone()
        ug_emitente, status_relacionamento, avisos = linha
        self.assertIsNone(ug_emitente)
        self.assertEqual(status_relacionamento, STATUS_RELACIONAMENTO_PARCIAL)
        self.assertIn(AVISO_UG_EMITENTE_NC_AUSENTE, json.loads(avisos))

        documento = self.conn.execute(
            "SELECT ug_emitente, status_relacionamento, quantidade_linhas FROM documento_nc"
        ).fetchone()
        self.assertEqual(documento, (None, STATUS_RELACIONAMENTO_PARCIAL, 1))

    def test_documento_com_varias_linhas_preserva_detalhe_e_agrega_no_banco(self):
        df = pd.DataFrame(
            [
                _linha_doc_nc(**{"UG Emitente - NC": 152734.0, "Valor Total NC": 559338.0}),
                _linha_doc_nc(**{"UG Emitente - NC": None, "Valor Total NC": 170000.0}),
                _linha_doc_nc(**{"UG Emitente - NC": None, "Valor Total NC": 140000.0}),
            ]
        )
        resultado = importar_doc_nc(self.conn, df, "doc_nc.xlsx", b"conteudo-v1")
        self.assertEqual(resultado.inseridos, 3)

        total_linhas = self.conn.execute("SELECT COUNT(*) FROM documento_nc_linha").fetchone()[0]
        self.assertEqual(total_linhas, 3)  # nenhuma linha foi descartada/mesclada

        total_documentos = self.conn.execute("SELECT COUNT(*) FROM documento_nc").fetchone()[0]
        self.assertEqual(total_documentos, 1)  # mas é um único documento agregado

        valor_total, ug_emitente, quantidade = self.conn.execute(
            "SELECT valor_assinado_total, ug_emitente, quantidade_linhas FROM documento_nc"
        ).fetchone()
        self.assertEqual(texto_para_valor(valor_total), Decimal("869338.00"))
        self.assertEqual(ug_emitente, "152734")  # veio da única linha que a trouxe
        self.assertEqual(quantidade, 3)

    def test_reimportar_arquivo_identico_nao_duplica_linha_nem_documento(self):
        df = pd.DataFrame([_linha_doc_nc(**{"UG Emitente - NC": 152734.0})])
        importar_doc_nc(self.conn, df, "doc_nc.xlsx", b"conteudo-v1")
        resultado_2 = importar_doc_nc(self.conn, df, "doc_nc.xlsx", b"conteudo-v1")

        self.assertTrue(resultado_2.ja_importado)
        total_linhas = self.conn.execute("SELECT COUNT(*) FROM documento_nc_linha").fetchone()[0]
        self.assertEqual(total_linhas, 1)
        total_documentos = self.conn.execute("SELECT COUNT(*) FROM documento_nc").fetchone()[0]
        self.assertEqual(total_documentos, 1)

    def test_nc_parcial_gera_alerta_automaticamente(self):
        df = pd.DataFrame([_linha_doc_nc()])  # UG Emitente - NC ausente -> PARCIAL
        importar_doc_nc(self.conn, df, "doc_nc.xlsx", b"conteudo-v1")

        alerta = self.conn.execute(
            "SELECT tipo, gravidade, status FROM alerta WHERE tipo = 'nc_ug_emitente_ausente'"
        ).fetchone()
        self.assertIsNotNone(alerta)
        tipo, gravidade, status = alerta
        self.assertEqual(gravidade, "media")
        self.assertEqual(status, "aberto")

    def test_reimportar_arquivo_diferente_atualiza_em_vez_de_duplicar(self):
        df_v1 = pd.DataFrame([_linha_doc_nc(**{"UG Emitente - NC": 152734.0, "Valor Total NC": 559338.0})])
        importar_doc_nc(self.conn, df_v1, "doc_nc_v1.xlsx", b"conteudo-v1")

        # Segunda extração do mesmo documento chega com valor corrigido.
        df_v2 = pd.DataFrame([_linha_doc_nc(**{"UG Emitente - NC": 152734.0, "Valor Total NC": 560000.0})])
        importar_doc_nc(self.conn, df_v2, "doc_nc_v2.xlsx", b"conteudo-v2")

        total_documentos = self.conn.execute("SELECT COUNT(*) FROM documento_nc").fetchone()[0]
        self.assertEqual(total_documentos, 1)  # atualizou, não duplicou

        valor_total = self.conn.execute("SELECT valor_assinado_total FROM documento_nc").fetchone()[0]
        self.assertEqual(texto_para_valor(valor_total), Decimal("560000.00"))

        total_lotes = self.conn.execute(
            "SELECT COUNT(*) FROM import_batch WHERE tipo_relatorio = 'simec_doc_nc'"
        ).fetchone()[0]
        self.assertEqual(total_lotes, 2)  # histórico de lotes preservado


class TotalDeControleTests(unittest.TestCase):
    """Regra 6.2 do briefing: cada lote grava quantidade de linhas lidas/rejeitadas/com aviso
    e a soma bruta/positiva/negativa/líquida, quando o relatório sustenta essa soma."""

    def setUp(self):
        self.conn = conectar(":memory:")

    def tearDown(self):
        self.conn.close()

    def _lote(self, tipo: str) -> tuple:
        return self.conn.execute(
            "SELECT quantidade_linhas_lidas, quantidade_rejeitadas, quantidade_com_aviso, "
            "soma_bruta, soma_positiva, soma_negativa, soma_liquida "
            "FROM import_batch WHERE tipo_relatorio = ?",
            (tipo,),
        ).fetchone()

    def test_doc_nc_com_operacoes_mistas_e_linha_de_rodape_ignorada(self):
        df = pd.DataFrame(
            [
                _linha_doc_nc(**{"UG Emitente - NC": 152734.0, "Operação": "( + )", "Valor Total NC": 600.0}),
                _linha_doc_nc(**{
                    "Número da NC": "2025NC000266", "UG Emitente - NC": 152734.0,
                    "Operação": "( - )", "Valor Total NC": 100.0,
                }),
                {"Número da NC": None, "Valor Total NC": 500.0},  # rodapé, sem identificador
            ]
        )
        importar_doc_nc(self.conn, df, "doc_nc.xlsx", b"conteudo")

        lidas, rejeitadas, com_aviso, bruta, positiva, negativa, liquida = self._lote("simec_doc_nc")
        self.assertEqual(lidas, 3)
        self.assertEqual(rejeitadas, 1)
        self.assertEqual(com_aviso, 0)
        self.assertEqual(texto_para_valor(bruta), Decimal("700.00"))
        self.assertEqual(texto_para_valor(positiva), Decimal("600.00"))
        self.assertEqual(texto_para_valor(negativa), Decimal("100.00"))
        self.assertEqual(texto_para_valor(liquida), Decimal("500.00"))

    def test_doc_nc_conta_linhas_com_aviso_de_ug_ausente(self):
        df = pd.DataFrame([_linha_doc_nc(**{"UG Emitente - NC": None, "Valor Total NC": 100.0})])
        importar_doc_nc(self.conn, df, "doc_nc.xlsx", b"conteudo")

        _, _, com_aviso, *_ = self._lote("simec_doc_nc")
        self.assertEqual(com_aviso, 1)

    def test_doc_ne_soma_como_sempre_positivo_sem_conceito_de_operacao(self):
        importar_doc_ne(self.conn, _df_doc_ne_caso_real(), "doc_ne.xlsx", b"conteudo")

        lidas, rejeitadas, com_aviso, bruta, positiva, negativa, liquida = self._lote("simec_doc_ne")
        self.assertEqual(lidas, 3)
        self.assertEqual(rejeitadas, 0)
        soma_esperada = Decimal("388300.00") + Decimal("154496.00") + Decimal("388300.00")
        self.assertEqual(texto_para_valor(bruta), soma_esperada)
        self.assertEqual(texto_para_valor(positiva), soma_esperada)
        self.assertEqual(texto_para_valor(negativa), Decimal("0"))
        self.assertEqual(texto_para_valor(liquida), soma_esperada)

    def test_execucao_anual_nao_calcula_soma_unica_de_linha(self):
        # Execução Anual tem 6 colunas de valor por linha — não sustenta uma única soma bruta/
        # positiva/negativa/líquida coerente (ver docstring de `ResumoControle`).
        df = pd.DataFrame(
            [
                {
                    "Ano de emissão": 2026, "SIAFI": "1ABDKU", "TED": "17352",
                    "Total NC Descentralização": "100,00", "Total NC Devolução": "0,00",
                    "Total Descentralizado": "100,00", "Total PF Repasse": "100,00",
                    "Total PF Devolução": "0,00", "Total Repassado": "100,00",
                }
            ]
        )
        importar_execucao_anual(self.conn, df, "execucao_anual.xlsx", b"conteudo")

        lidas, rejeitadas, com_aviso, bruta, positiva, negativa, liquida = self._lote("simec_execucao_anual")
        self.assertEqual(lidas, 1)
        self.assertEqual(rejeitadas, 0)
        self.assertIsNone(bruta)
        self.assertIsNone(positiva)
        self.assertIsNone(negativa)
        self.assertIsNone(liquida)


class SincronizarExecucaoTgTests(unittest.TestCase):
    """`execucao_tg` espelha a Execução Mensal (decisão de 22/09/2026): sem upload, idempotente
    pelo sha256 da extração, upsert pela chave (NE, ano, mês)."""

    def setUp(self):
        from tests.test_teds_importacao_tesouro_gerencial import _execucao_mensal_sintetica

        self.conn = conectar(":memory:")
        self.base = _execucao_mensal_sintetica()

    def tearDown(self):
        self.conn.close()

    def _linhas(self):
        return self.conn.execute(
            "SELECT numero_completo_ne, ano_lancamento, mes_lancamento, empenhado, liquidado, pago, "
            "import_batch_id FROM execucao_tg ORDER BY 1, 2, 3"
        ).fetchall()

    def test_grava_uma_linha_por_ne_e_mes_com_valores_em_texto_decimal(self):
        resultado = sincronizar_execucao_tg(self.conn, self.base, "sha-1", "extracao.xlsx")

        self.assertFalse(resultado.ja_importado)
        self.assertEqual(resultado.inseridos, 3)
        self.assertEqual(
            [linha[:6] for linha in self._linhas()],
            [
                ("2026NE000422", 2026, 8, "388300.00", "100000.10", "90000.00"),
                ("2026NE000422", 2026, 9, "0.00", "50000.20", "40000.00"),
                ("2026NE000427", 2026, 9, "154496.00", "0.00", "0.00"),
            ],
        )

    def test_mesma_extracao_e_no_op(self):
        sincronizar_execucao_tg(self.conn, self.base, "sha-1", "extracao.xlsx")
        segunda = sincronizar_execucao_tg(self.conn, self.base, "sha-1", "extracao.xlsx")

        self.assertTrue(segunda.ja_importado)
        self.assertEqual(segunda.inseridos, 0)
        self.assertEqual(len(self._linhas()), 3)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM import_batch").fetchone()[0], 1)

    def test_extracao_nova_atualiza_sem_duplicar_e_preserva_historico_de_lotes(self):
        primeira = sincronizar_execucao_tg(self.conn, self.base, "sha-1", "v1.xlsx")
        corrigida = self.base.copy()
        corrigida.loc[corrigida["tipo_linha"] == "item_execucao", "liquidada"] += 1.0

        segunda = sincronizar_execucao_tg(self.conn, corrigida, "sha-2", "v2.xlsx")

        self.assertFalse(segunda.ja_importado)
        linhas = self._linhas()
        self.assertEqual(len(linhas), 3)
        self.assertEqual(linhas[0][4], "100001.10")
        self.assertTrue(all(linha[6] == segunda.import_batch_id for linha in linhas))
        self.assertNotEqual(primeira.import_batch_id, segunda.import_batch_id)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM import_batch").fetchone()[0], 2)

    def test_linha_que_a_extracao_nova_deixa_de_trazer_nao_e_apagada(self):
        sincronizar_execucao_tg(self.conn, self.base, "sha-1", "v1.xlsx")
        so_a_ne_b = self.base[self.base["ne_ccor"].str.endswith("000427")]

        sincronizar_execucao_tg(self.conn, so_a_ne_b, "sha-2", "v2.xlsx")

        self.assertEqual(len(self._linhas()), 3)

    def test_rejeitada_entra_no_total_de_controle_do_lote(self):
        from tests.test_teds_importacao_tesouro_gerencial import _linha_empenho

        base = self.base.copy()
        base.loc[len(base)] = _linha_empenho("SEM-FORMATO", 202608, 10.0, "F", "D")

        resultado = sincronizar_execucao_tg(self.conn, base, "sha-1", "extracao.xlsx")

        self.assertEqual(len(resultado.rejeitadas), 1)
        lidas, rejeitadas, aceitas = self.conn.execute(
            "SELECT quantidade_linhas_lidas, quantidade_rejeitadas, quantidade_registros FROM import_batch"
        ).fetchone()
        self.assertEqual((lidas, rejeitadas, aceitas), (4, 1, 3))


_FIXTURE_EXECUCAO_MENSAL = Path("tests/fixtures/execucao_mensal_2026-09-22.xlsx")


@unittest.skipUnless(_FIXTURE_EXECUCAO_MENSAL.exists(), f"Fixture ausente em {_FIXTURE_EXECUCAO_MENSAL}")
class SincronizarExecucaoTgAtualTests(unittest.TestCase):
    """Ponta a ponta com o manifesto versionado da Execução Mensal (diretórios temporários —
    nunca toca `data/manifestos/` nem `data/raw/`)."""

    def setUp(self):
        self.conn = conectar(":memory:")
        self._tmp = tempfile.TemporaryDirectory()
        self.manifestos = Path(self._tmp.name) / "manifestos"
        self.raw = Path(self._tmp.name) / "raw"
        self.raw.mkdir()

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def _importar_fixture(self):
        shutil.copy(_FIXTURE_EXECUCAO_MENSAL, self.raw / _FIXTURE_EXECUCAO_MENSAL.name)
        importar_execucao_mensal(_FIXTURE_EXECUCAO_MENSAL, diretorio_manifestos=self.manifestos)

    def test_sem_extracao_importada_levanta_erro_explicito(self):
        manifesto, lote = status_sincronizacao_execucao_tg(self.conn, self.manifestos)
        self.assertEqual((manifesto, lote), (None, None))
        with self.assertRaises(ExecucaoMensalNaoImportada):
            sincronizar_execucao_tg_atual(self.conn, self.manifestos, self.raw)

    def test_sincroniza_a_extracao_atual_e_a_segunda_vez_e_no_op(self):
        self._importar_fixture()
        manifesto, lote_antes = status_sincronizacao_execucao_tg(self.conn, self.manifestos)
        self.assertIsNotNone(manifesto)
        self.assertIsNone(lote_antes)

        primeira = sincronizar_execucao_tg_atual(self.conn, self.manifestos, self.raw)

        self.assertFalse(primeira.ja_importado)
        self.assertGreater(primeira.inseridos, 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM execucao_tg").fetchone()[0], primeira.inseridos)
        nome, hash_lote = self.conn.execute("SELECT nome_arquivo, hash_arquivo FROM import_batch").fetchone()
        self.assertEqual((nome, hash_lote), (manifesto.arquivo, manifesto.sha256))
        self.assertEqual(status_sincronizacao_execucao_tg(self.conn, self.manifestos)[1], primeira.import_batch_id)

        segunda = sincronizar_execucao_tg_atual(self.conn, self.manifestos, self.raw)

        self.assertTrue(segunda.ja_importado)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM import_batch").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
