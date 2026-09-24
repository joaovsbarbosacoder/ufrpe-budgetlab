"""
Testes do rodapé dos relatórios do SIMEC (`src/teds_importacao_simec.py::_capturar_rodape`,
`src/teds_lotes.py::comparar_rodape`, briefing seção 6.2).

Formato confirmado nas 4 extrações reais de 17/09/2026: a ÚLTIMA linha vem sem nenhum
identificador e só com o(s) total(is). No DOC NC e no DOC PF o rodapé é a soma ABSOLUTA
(positivas + negativas), não o líquido. Os DataFrames abaixo reproduzem esses cabeçalhos e o
formato, com valores fictícios.
"""

from __future__ import annotations

import json
import unittest
from decimal import Decimal

import numpy as np
import pandas as pd

from src.teds_alertas import TIPO_RODAPE_DIVERGENTE
from src.teds_importacao_simec import (
    ler_doc_nc_simec,
    ler_doc_ne_simec,
    ler_doc_pf_simec,
    ler_execucao_anual_simec,
)
from src.teds_lotes import (
    TIPO_DOC_NC,
    TIPO_DOC_PF,
    comparar_rodape,
    importar_doc_nc,
    importar_doc_ne,
    importar_doc_pf,
    importar_execucao_anual,
)
from src.teds_schema import conectar

D = Decimal
NAN = np.nan


def _nc(linhas, rodape="auto"):
    """linhas = (numero, operacao, valor). `rodape`: 'auto' = soma bruta, None = sem rodapé."""

    base = {
        "Data de Emissão da NC": "10/02/2026", "UG Emitente - NC": "154046", "Descrição do Termo": "Termo",
        "Estado Atual": "Termo em Execução", "Fim da Vigência": "31/12/2027", "Início da Vigência": "01/01/2026",
        "SIAFI": "1ABDKU", "TED": "17352", "UG Descentralizadora": "153165",
    }
    dados = [{**base, "Número da NC": n, "Operação": op, "Valor Total NC": v} for n, op, v in linhas]
    df = pd.DataFrame(dados)
    if rodape is not None:
        total = sum(v for _, _, v in linhas) if rodape == "auto" else rodape
        df.loc[len(df)] = {c: NAN for c in df.columns} | {"Valor Total NC": total}
    return df


def _pf(linhas, rodape="auto"):
    base = {
        "Data de Emissão Doc. PF": "10/02/2026", "UG Emitente - PF": "154046", "Descrição do Termo": "Termo",
        "Estado Atual": "Termo em Execução", "Fim da Vigência": "31/12/2027", "Início da Vigência": "01/01/2026",
        "SIAFI": "1ABDKU", "TED": "17352", "UG Descentralizadora": "153165",
    }
    dados = [{**base, "Número Doc. PF": n, "Operação": op, "Valor Doc. PF (R$)": v} for n, op, v in linhas]
    df = pd.DataFrame(dados)
    if rodape is not None:
        total = sum(v for _, _, v in linhas) if rodape == "auto" else rodape
        df.loc[len(df)] = {c: NAN for c in df.columns} | {"Valor Doc. PF (R$)": total}
    return df


def _ne(linhas, rodape="auto"):
    base = {
        "Gestão Emitente - NE": "15239", "UG Executora Emitente - NE": "153165", "Descrição do Termo": "Termo",
        "Estado Atual": "Termo em Execução", "Fim da Vigência": "31/12/2027", "Início da Vigência": "01/01/2026",
        "SIAFI": "1ABDKU", "TED": "17352", "UG Descentralizadora": "154046",
    }
    dados = [{**base, "Número do Empenho": n, "Valor da NE": v} for n, v in linhas]
    df = pd.DataFrame(dados)
    if rodape is not None:
        total = sum(v for _, v in linhas) if rodape == "auto" else rodape
        df.loc[len(df)] = {c: NAN for c in df.columns} | {"Valor da NE": total}
    return df


_TOTAIS_EXECUCAO = [
    "Total NC Descentralização (R$)", "Total NC Devolução (R$)", "Total Descentralizado (R$)",
    "Total PF Repasse", "Total PF Devolução", "Total Repassado",
]


def _execucao(rodape="auto", ajuste=None):
    base = {
        "Ano de emissão": 2026.0, "Descrição do Termo": "Termo", "Estado Atual": "Termo em Execução",
        "Fim da Vigência": "31/12/2027", "Início da Vigência": "01/01/2026", "SIAFI": "1ABDKU", "TED": 17352.0,
        "UG Descentralizadora": 153165.0,
    }
    linhas = [
        {**base, **dict(zip(_TOTAIS_EXECUCAO, (1000.0, 100.0, 900.0, 800.0, 50.0, 750.0)))},
        {**base, "SIAFI": "1ABDKQ", "TED": 17454.0,
         **dict(zip(_TOTAIS_EXECUCAO, (500.0, 0.0, 500.0, 500.0, 0.0, 500.0)))},
    ]
    df = pd.DataFrame(linhas)
    if rodape is not None:
        somas = {c: float(df[c].sum()) for c in _TOTAIS_EXECUCAO}
        somas.update(ajuste or {})
        df.loc[len(df)] = {c: NAN for c in df.columns} | somas
    return df


class CapturaDoRodapeTests(unittest.TestCase):
    def test_nc_rodape_e_a_soma_absoluta_das_positivas_e_negativas(self):
        df = _nc([("1", "( + )", 1000.0), ("2", "( - )", 200.0)])
        self.assertEqual(ler_doc_nc_simec(df).rodape, {"valor_nc": D("1200.00")})

    def test_pf_ne_e_execucao_anual(self):
        self.assertEqual(ler_doc_pf_simec(_pf([("1", "(+)", 10.0), ("2", "(-)", 4.0)])).rodape, {"valor_pf": D("14.00")})
        self.assertEqual(ler_doc_ne_simec(_ne([("2026NE000001", 5.0), ("2026NE000002", 7.5)])).rodape, {"valor_ne": D("12.50")})
        rodape = ler_execucao_anual_simec(_execucao()).rodape
        self.assertEqual(set(rodape), {
            "total_nc_descentralizacao", "total_nc_devolucao", "total_descentralizado",
            "total_pf_repasse", "total_pf_devolucao", "total_repassado",
        })
        self.assertEqual(rodape["total_repassado"], D("1250.00"))

    def test_arquivo_sem_rodape_devolve_none(self):
        self.assertIsNone(ler_doc_nc_simec(_nc([("1", "( + )", 10.0)], rodape=None)).rodape)
        self.assertIsNone(ler_execucao_anual_simec(_execucao(rodape=None)).rodape)

    def test_linha_de_dado_com_identificador_nunca_e_tomada_por_rodape(self):
        # última linha traz TED/SIAFI/número: é dado, não rodapé
        self.assertIsNone(ler_doc_nc_simec(_nc([("1", "( + )", 10.0), ("2", "( + )", 20.0)], rodape=None)).rodape)

    def test_rodape_com_um_identificador_solto_nao_e_rodape(self):
        df = _nc([("1", "( + )", 10.0)])
        df.loc[df.index[-1], "TED"] = "17352"  # sujeira numa coluna de identificação
        self.assertIsNone(ler_doc_nc_simec(df).rodape)

    def test_dataframe_vazio(self):
        self.assertIsNone(ler_doc_nc_simec(_nc([("1", "( + )", 1.0)]).iloc[0:0]).rodape)

    def test_a_linha_de_rodape_continua_rejeitada_como_linha_de_dado(self):
        leitura = ler_doc_nc_simec(_nc([("1", "( + )", 10.0)]))
        self.assertEqual(len(leitura.registros), 1)
        self.assertEqual(len(leitura.rejeitadas), 1)


class CompararRodapeTests(unittest.TestCase):
    def test_nc_compara_a_soma_bruta_e_nao_a_liquida(self):
        df = _nc([("1", "( + )", 1000.0), ("2", "( - )", 200.0)])
        (comp,) = comparar_rodape(TIPO_DOC_NC, ler_doc_nc_simec(df))
        self.assertEqual((comp.rodape, comp.calculado, comp.diferenca), (D("1200.00"), D("1200.00"), D("0.00")))

    def test_rodape_liquido_no_lugar_do_absoluto_diverge(self):
        df = _nc([("1", "( + )", 1000.0), ("2", "( - )", 200.0)], rodape=800.0)
        (comp,) = comparar_rodape(TIPO_DOC_NC, ler_doc_nc_simec(df))
        self.assertEqual(comp.diferenca, D("-400.00"))

    def test_pf_tambem_e_bruto(self):
        df = _pf([("1", "(+)", 10.0), ("2", "(-)", 4.0)])
        (comp,) = comparar_rodape(TIPO_DOC_PF, ler_doc_pf_simec(df))
        self.assertEqual(comp.diferenca, D("0.00"))

    def test_sem_rodape_devolve_none(self):
        self.assertIsNone(comparar_rodape(TIPO_DOC_NC, ler_doc_nc_simec(_nc([("1", "( + )", 1.0)], rodape=None))))

    def test_tipo_desconhecido_devolve_none(self):
        self.assertIsNone(comparar_rodape("outro", ler_doc_nc_simec(_nc([("1", "( + )", 1.0)]))))


class GravacaoNoLoteEAlertaTests(unittest.TestCase):
    def setUp(self):
        self.conn = conectar(":memory:")

    def tearDown(self):
        self.conn.close()

    def _lote(self, id_lote):
        return self.conn.execute(
            "SELECT total_rodape, diferenca_rodape, detalhe_rodape FROM import_batch WHERE id = ?", (id_lote,)
        ).fetchone()

    def _alertas(self):
        return self.conn.execute(
            "SELECT gravidade, documento, descricao, status FROM alerta WHERE tipo = ?", (TIPO_RODAPE_DIVERGENTE,)
        ).fetchall()

    def test_rodape_conferido_grava_o_total_e_nao_gera_alerta(self):
        df = _nc([("1", "( + )", 1000.0), ("2", "( - )", 200.0)])
        lote = importar_doc_nc(self.conn, df, "nc.xlsx", b"nc").import_batch_id
        total, diferenca, detalhe = self._lote(lote)
        self.assertEqual((total, diferenca), ("1200.00", "0.00"))
        self.assertEqual(json.loads(detalhe)[0]["campo"], "valor_nc")
        self.assertEqual(self._alertas(), [])

    def test_rodape_divergente_gera_um_alerta_critico_e_o_lote_continua_importado(self):
        df = _nc([("1", "( + )", 1000.0)], rodape=1500.0)
        resultado = importar_doc_nc(self.conn, df, "nc.xlsx", b"nc")
        (gravidade, documento, descricao, status) = self._alertas()[0]
        self.assertEqual((gravidade, documento, status), ("alta", f"lote:{resultado.import_batch_id}", "aberto"))
        self.assertIn("valor_nc", descricao)
        self.assertIn("R$ 1.500,00", descricao)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documento_nc").fetchone()[0], 1)  # importou
        self.assertEqual(self._lote(resultado.import_batch_id)[1], "500.00")

    def test_um_centavo_de_diferenca_e_tolerado_e_dois_nao(self):
        importar_doc_nc(self.conn, _nc([("1", "( + )", 1000.0)], rodape=1000.01), "a.xlsx", b"a")
        self.assertEqual(self._alertas(), [])
        importar_doc_nc(self.conn, _nc([("1", "( + )", 1000.0)], rodape=1000.02), "b.xlsx", b"b")
        self.assertEqual(len(self._alertas()), 1)

    def test_arquivo_sem_rodape_fica_null_e_sem_alerta(self):
        lote = importar_doc_nc(self.conn, _nc([("1", "( + )", 10.0)], rodape=None), "nc.xlsx", b"nc").import_batch_id
        self.assertEqual(self._lote(lote), (None, None, None))
        self.assertEqual(self._alertas(), [])

    def test_reimportar_o_mesmo_arquivo_nao_duplica_o_alerta(self):
        df = _nc([("1", "( + )", 1000.0)], rodape=1500.0)
        importar_doc_nc(self.conn, df, "nc.xlsx", b"nc")
        importar_doc_nc(self.conn, df, "nc.xlsx", b"nc")
        self.assertEqual(len(self._alertas()), 1)

    def test_execucao_anual_confere_os_seis_campos_e_aponta_so_o_que_diverge(self):
        lote = importar_execucao_anual(self.conn, _execucao(), "ea.xlsx", b"ea").import_batch_id
        total, diferenca, detalhe = self._lote(lote)
        self.assertIsNone(total)  # vários campos: sem total único
        self.assertEqual(diferenca, "0.00")
        self.assertEqual(len(json.loads(detalhe)), 6)
        self.assertEqual(self._alertas(), [])

        lote2 = importar_execucao_anual(
            self.conn, _execucao(ajuste={"Total Repassado": 9999.0}), "ea2.xlsx", b"ea2"
        ).import_batch_id
        self.assertEqual(len(self._alertas()), 1)
        descricao = self._alertas()[0][2]
        self.assertIn("total_repassado", descricao)
        self.assertNotIn("total_nc_devolucao", descricao)  # só os campos que divergem entram no texto
        self.assertEqual(self._lote(lote2)[1], "8749.00")

    def test_doc_ne_e_doc_pf_gravam_o_rodape(self):
        lote_ne = importar_doc_ne(self.conn, _ne([("2026NE000001", 5.0), ("2026NE000002", 7.5)]), "ne.xlsx", b"ne").import_batch_id
        lote_pf = importar_doc_pf(self.conn, _pf([("1", "(+)", 10.0), ("2", "(-)", 4.0)]), "pf.xlsx", b"pf").import_batch_id
        self.assertEqual(self._lote(lote_ne)[:2], ("12.50", "0.00"))
        self.assertEqual(self._lote(lote_pf)[:2], ("14.00", "0.00"))

    def test_lote_revertido_nao_gera_alerta_novo(self):
        df = _nc([("1", "( + )", 1000.0)], rodape=1500.0)
        lote = importar_doc_nc(self.conn, df, "nc.xlsx", b"nc").import_batch_id
        self.conn.execute("UPDATE alerta SET status = 'resolvido'")
        self.conn.execute("UPDATE import_batch SET status = 'revertido' WHERE id = ?", (lote,))
        self.conn.commit()
        importar_doc_nc(self.conn, _nc([("9", "( + )", 1.0)]), "outro.xlsx", b"outro")  # dispara a sincronização
        self.assertEqual([a for a in self._alertas() if a[3] != "resolvido"], [])

    def test_banco_novo_tem_as_colunas_do_rodape(self):
        colunas = {linha[1] for linha in self.conn.execute("PRAGMA table_info(import_batch)")}
        self.assertTrue({"total_rodape", "diferenca_rodape", "detalhe_rodape"} <= colunas)


if __name__ == "__main__":
    unittest.main()
