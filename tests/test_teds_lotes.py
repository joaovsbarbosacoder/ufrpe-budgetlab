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
import unittest
from decimal import Decimal

import pandas as pd

from src.teds_alertas import TIPO_EMPENHO_MULTIPLOS_TEDS
from src.teds_importacao_simec import AVISO_UG_EMITENTE_NC_AUSENTE, STATUS_RELACIONAMENTO_PARCIAL
from src.teds_lotes import importar_doc_nc, importar_doc_ne, importar_execucao_anual
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


if __name__ == "__main__":
    unittest.main()
