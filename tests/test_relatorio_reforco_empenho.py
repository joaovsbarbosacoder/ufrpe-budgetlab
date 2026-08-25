"""Testes do Relatório de Reforço de Empenho (src/relatorio_reforco_empenho.py).

Dados sintéticos — a lógica é pura reorganização de colunas já validadas em
`ler_bolsas_auxilios`/`ler_contratos_continuos`, não precisa de fixture de planilha real.
"""

from __future__ import annotations

import unittest

import pandas as pd

from src.relatorio_reforco_empenho import (
    BOLSAS_AUXILIOS,
    CONTRATOS_CONTINUOS,
    gerar_pdf_detalhado,
    gerar_pdf_resumido,
    linhas_para_processo,
    processos_disponiveis,
)


def _bolsas_sintetico() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "processo": ["001167/2026-78", "001167/2026-78", "001167/2026-78", "002429/2026-11", "000668/2026-37"],
            "programa_bolsa": ["PADPG", "ESO", "SEM NE AINDA", "OUTRO PROGRAMA", "SEM NE"],
            "unidade_cod": ["PRPG", "PREG", "NEI", "PREG", "NACES"],
            "acao_cod": ["20GK", "20GK", "20GK", "20GK", "4002"],
            "ptres": ["230389", "230389", "230395", "230395", "230396"],
            "fonte_cod": ["1000", "1000", "1000", "1000", "1000"],
            "natureza_despesa_cod": ["339018", "339018", "339018", "339018", "339018"],
            "ugr_cod": ["151931", "157684", "157665", "157684", "157681"],
            "pi_cod": ["M20GKO94AXN", "M20GKG19AXN", "M20GKG20BSN", "M20GKG19AXN", "M4002G23BSE"],
            "ne_curta": ["2026NE000020", "2026NE000056", None, "2026NE000099", None],
            "valor_mensal": [15750.0, 7500.0, 900.0, 1000.0, 500.0],
            "meses_a_empenhar": [0.923810, 0.966197, 0.0, 2.0, 1.0],
        }
    )


def _continuos_sintetico() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "processo_empenho": ["001370/2026-44", "001370/2026-44", "000214/2026-66"],
            "fornecedor": ["Associação Paranaense de Cultura - APC", "Brascon Gestão Ambiental Ltda", "Companhia Energética de Pernambuco"],
            "unidade_cod": ["SEDE", "SEDE", "SEDE"],
            "acao_cod": ["20TP", "20TP", "20TP"],
            "ptres": ["169885", "169885", "169886"],
            "fonte_cod": ["1000", "1000", "1000"],
            "natureza_despesa_cod": ["339039", "339039", "339039"],
            "ugr_cod": ["157684", "157684", "157684"],
            "pi_cod": ["M20TPG01AXN", "M20TPG02AXN", "M20TPG03AXN"],
            "ne_curta": ["2026NE000100", "2026NE000101", "2026NE000102"],
            "despesa_mensal": [3000.0, 2000.0, 5000.0],
            "meses_a_empenhar": [1.5, 0.0, 3.0],
        }
    )


class TestProcessosDisponiveis(unittest.TestCase):
    def test_lista_processos_distintos_ordenados_por_frequencia(self):
        processos = processos_disponiveis(_bolsas_sintetico(), BOLSAS_AUXILIOS)
        self.assertEqual(processos[0], "001167/2026-78")
        self.assertIn("002429/2026-11", processos)

    def test_linha_sem_ne_nao_conta_para_processo_disponivel(self):
        # "000668/2026-37" só tem uma linha, e essa linha não tem NE (nada a reforçar).
        processos = processos_disponiveis(_bolsas_sintetico(), BOLSAS_AUXILIOS)
        self.assertNotIn("000668/2026-37", processos)


class TestLinhasParaProcessoBolsas(unittest.TestCase):
    def setUp(self):
        self.linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78")

    def test_so_linhas_do_processo_escolhido(self):
        self.assertEqual(len(self.linhas), 2)
        self.assertTrue((self.linhas["processo"] == "001167/2026-78").all())

    def test_item_despesa_vem_do_programa_bolsa(self):
        self.assertEqual(set(self.linhas["item_despesa"]), {"PADPG", "ESO"})

    def test_meses_sugeridos_vem_de_meses_a_empenhar(self):
        linha = self.linhas[self.linhas["ne_curta"] == "2026NE000020"].iloc[0]
        self.assertAlmostEqual(linha["meses_sugeridos"], 0.923810, places=5)

    def test_linha_sem_ne_do_mesmo_processo_fica_de_fora(self):
        # "SEM NE AINDA" é do processo "001167/2026-78" mas não tem NE — não há empenho
        # para reforçar, não deve aparecer no relatório.
        self.assertNotIn("SEM NE AINDA", set(self.linhas["item_despesa"]))


class TestLinhasParaProcessoContinuos(unittest.TestCase):
    def test_item_despesa_vem_do_fornecedor(self):
        linhas = linhas_para_processo(_continuos_sintetico(), CONTRATOS_CONTINUOS, "001370/2026-44")
        self.assertEqual(len(linhas), 2)
        self.assertIn("Brascon Gestão Ambiental Ltda", set(linhas["item_despesa"]))

    def test_valor_mensal_vem_de_despesa_mensal(self):
        linhas = linhas_para_processo(_continuos_sintetico(), CONTRATOS_CONTINUOS, "000214/2026-66")
        self.assertEqual(linhas.iloc[0]["valor_mensal"], 5000.0)


class TestGerarPdfDetalhado(unittest.TestCase):
    def test_pdf_valido_com_total_correto(self):
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78")
        linhas = linhas.assign(empenhar=linhas["meses_sugeridos"] * linhas["valor_mensal"])

        pdf_bytes = gerar_pdf_detalhado(BOLSAS_AUXILIOS, "001167/2026-78", linhas)

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 500)

    def test_linha_com_empenhar_nulo_nao_quebra_o_pdf(self):
        # "Meses a Empenhar" sem preencher (dado incompleto na origem, ver
        # `meses_a_empenhar` em necessidade_empenho.py) não pode virar "nan" no PDF.
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78")
        linhas = linhas.assign(empenhar=[float("nan"), 5000.0])

        pdf_bytes = gerar_pdf_detalhado(BOLSAS_AUXILIOS, "001167/2026-78", linhas)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_pdf_de_relatorio_vazio_nao_quebra(self):
        vazio = pd.DataFrame(
            columns=[
                "processo", "item_despesa", "unidade_cod", "acao_cod", "ptres", "fonte_cod",
                "natureza_despesa_cod", "ugr_cod", "pi_cod", "ne_curta", "empenhar",
            ]
        )
        pdf_bytes = gerar_pdf_detalhado(BOLSAS_AUXILIOS, "000000/0000-00", vazio)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))


class TestGerarPdfResumido(unittest.TestCase):
    def test_pdf_valido_com_total_correto(self):
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78")
        linhas = linhas.assign(empenhar=linhas["meses_sugeridos"] * linhas["valor_mensal"])

        pdf_bytes = gerar_pdf_resumido(BOLSAS_AUXILIOS, "001167/2026-78", linhas)

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 500)

    def test_linha_com_empenhar_nulo_nao_quebra_o_pdf(self):
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78")
        linhas = linhas.assign(empenhar=[float("nan"), 5000.0])

        pdf_bytes = gerar_pdf_resumido(BOLSAS_AUXILIOS, "001167/2026-78", linhas)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_pdf_de_relatorio_vazio_nao_quebra(self):
        vazio = pd.DataFrame(
            columns=[
                "processo", "item_despesa", "unidade_cod", "acao_cod", "ptres", "fonte_cod",
                "natureza_despesa_cod", "ugr_cod", "pi_cod", "ne_curta", "empenhar",
            ]
        )
        pdf_bytes = gerar_pdf_resumido(BOLSAS_AUXILIOS, "000000/0000-00", vazio)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
