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
    TIPO_ANULACAO,
    TIPO_REFORCO,
    _agrupado_por_classificacao,
    excluir_linhas_zeradas,
    gerar_pdf_detalhado,
    gerar_pdf_resumido,
    linhas_para_processo,
    linhas_todos_os_empenhos,
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
    # 1 linha por CONTRATO/NE (não por item — ver docstring de
    # `src.contratos_continuos_cadastro`): "Tekis" tem 2 itens de licitação, cada um com seu
    # percentual do valor mensal total do contrato (`itens`); os demais têm 1 item só, 100%.
    return pd.DataFrame(
        {
            "processo_empenho": ["001370/2026-44", "001370/2026-44", "000214/2026-66", "001370/2026-44"],
            "fornecedor": [
                "Associação Paranaense de Cultura - APC", "Brascon Gestão Ambiental Ltda",
                "Companhia Energética de Pernambuco", "Tekis Tecnologias Avançadas Ltda",
            ],
            "unidade_cod": ["SEDE"] * 4,
            "acao_cod": ["20TP"] * 4,
            "ptres": ["169885", "169885", "169886", "169885"],
            "fonte_cod": ["1000"] * 4,
            "natureza_despesa_cod": ["339039"] * 4,
            "ugr_cod": ["157684"] * 4,
            "pi_cod": ["M20TPG01AXN", "M20TPG02AXN", "M20TPG03AXN", "M20TPG04AXN"],
            "ne_curta": ["2026NE000100", "2026NE000101", "2026NE000102", "2026NE000084"],
            "despesa_mensal": [3000.0, 2000.0, 5000.0, 10000.0],
            "meses_a_empenhar": [1.5, 0.0, 3.0, 0.000648],
            "itens": [
                [{"numero": 1, "percentual": 100.0}],
                [{"numero": 1, "percentual": 100.0}],
                [{"numero": 1, "percentual": 100.0}],
                [{"numero": 1, "percentual": 70.0}, {"numero": 2, "percentual": 30.0}],
            ],
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
        self.assertEqual(len(linhas), 4)
        self.assertIn("Brascon Gestão Ambiental Ltda", set(linhas["item_despesa"]))

    def test_contrato_de_1_item_nao_ganha_sufixo_de_item(self):
        linhas = linhas_para_processo(_continuos_sintetico(), CONTRATOS_CONTINUOS, "000214/2026-66")
        self.assertEqual(linhas.iloc[0]["item_despesa"], "Companhia Energética de Pernambuco")

    def test_valor_mensal_vem_de_despesa_mensal(self):
        linhas = linhas_para_processo(_continuos_sintetico(), CONTRATOS_CONTINUOS, "000214/2026-66")
        self.assertEqual(linhas.iloc[0]["valor_mensal"], 5000.0)

    def test_contrato_com_varios_itens_vira_uma_linha_por_item_com_valor_rateado(self):
        # pedido explícito: o item não é uma entidade própria no cadastro (1 registro por
        # contrato/NE) — só vira linha própria aqui, no relatório, ratreando "despesa_mensal"
        # do contrato pelo percentual de cada item (não colapsado, nem indistinguível).
        linhas = linhas_para_processo(_continuos_sintetico(), CONTRATOS_CONTINUOS, "001370/2026-44")
        itens_tekis = linhas[linhas["ne_curta"] == "2026NE000084"]
        self.assertEqual(len(itens_tekis), 2)
        valores = dict(zip(itens_tekis["item_despesa"], itens_tekis["valor_mensal"]))
        self.assertEqual(
            valores,
            {"Tekis Tecnologias Avançadas Ltda — Item 1": 7000.0, "Tekis Tecnologias Avançadas Ltda — Item 2": 3000.0},
        )
        # meses_sugeridos é sempre no nível da NE (liquidação não é dividida por item) —
        # idêntico nas duas linhas expandidas do mesmo contrato.
        self.assertEqual(itens_tekis["meses_sugeridos"].nunique(), 1)


class TestLinhasTodosOsEmpenhos(unittest.TestCase):
    """`linhas_todos_os_empenhos` — pedido explícito exclusivo da Anulação: mesmo esquema de
    `linhas_para_processo`, sem o filtro por um processo escolhido."""

    def test_reune_linhas_de_todos_os_processos_com_ne(self):
        # 3 linhas com NE reconhecível no total: 2 em "001167/2026-78", 1 em "002429/2026-11"
        # (ver _bolsas_sintetico) — "SEM NE AINDA"/"SEM NE" ficam de fora, mesmo critério de
        # linhas_para_processo/processos_disponiveis.
        linhas = linhas_todos_os_empenhos(_bolsas_sintetico(), BOLSAS_AUXILIOS)
        self.assertEqual(len(linhas), 3)
        self.assertEqual(set(linhas["processo"]), {"001167/2026-78", "002429/2026-11"})
        self.assertNotIn("SEM NE AINDA", set(linhas["item_despesa"]))
        self.assertNotIn("SEM NE", set(linhas["item_despesa"]))

    def test_expande_por_item_de_licitacao_entre_processos_diferentes(self):
        # Mesmo comportamento de linhas_para_processo para Contratos Contínuos (expansão por
        # item), só que abrangendo os dois processos da base sintética de uma vez.
        linhas = linhas_todos_os_empenhos(_continuos_sintetico(), CONTRATOS_CONTINUOS)
        self.assertEqual(len(linhas), 5)  # 3 contratos de 1 item + Tekis (2 itens) = 5
        self.assertEqual(set(linhas["processo"]), {"001370/2026-44", "000214/2026-66"})


class TestExcluirLinhasZeradas(unittest.TestCase):
    def _linhas(self, meses: list[float], empenhar: list[float]) -> pd.DataFrame:
        return pd.DataFrame({"item_despesa": [f"item{i}" for i in range(len(meses))], "meses": meses, "empenhar": empenhar})

    def test_remove_linha_com_meses_zero(self):
        resultado = excluir_linhas_zeradas(self._linhas([0.0, 1.5], [0.0, 3000.0]))
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]["item_despesa"], "item1")

    def test_remove_linha_com_empenhar_zero_mesmo_com_meses_nao_zero(self):
        # editado manualmente pra 0 direto na coluna Empenhar (R$), sem mexer em Meses.
        resultado = excluir_linhas_zeradas(self._linhas([2.0, 1.0], [0.0, 1500.0]))
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]["item_despesa"], "item1")

    def test_linha_com_meses_nulo_nao_e_removida(self):
        # NaN (dado incompleto) e zero (nada a reforçar) são coisas diferentes — só zero sai.
        resultado = excluir_linhas_zeradas(self._linhas([float("nan"), 1.0], [float("nan"), 1500.0]))
        self.assertEqual(len(resultado), 2)

    def test_todas_zeradas_devolve_vazio(self):
        resultado = excluir_linhas_zeradas(self._linhas([0.0, 0.0], [0.0, 0.0]))
        self.assertTrue(resultado.empty)


class TestGerarPdfDetalhado(unittest.TestCase):
    def test_pdf_valido_com_total_correto(self):
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78")
        linhas = linhas.assign(empenhar=linhas["meses_sugeridos"] * linhas["valor_mensal"])

        pdf_bytes = gerar_pdf_detalhado(BOLSAS_AUXILIOS, TIPO_REFORCO, "001167/2026-78", linhas)

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 500)

    def test_linha_com_empenhar_nulo_nao_quebra_o_pdf(self):
        # "Meses a Empenhar" sem preencher (dado incompleto na origem, ver
        # `meses_a_empenhar` em necessidade_empenho.py) não pode virar "nan" no PDF.
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78")
        linhas = linhas.assign(empenhar=[float("nan"), 5000.0])

        pdf_bytes = gerar_pdf_detalhado(BOLSAS_AUXILIOS, TIPO_REFORCO, "001167/2026-78", linhas)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_pdf_de_relatorio_vazio_nao_quebra(self):
        vazio = pd.DataFrame(
            columns=[
                "processo", "item_despesa", "unidade_cod", "acao_cod", "ptres", "fonte_cod",
                "natureza_despesa_cod", "ugr_cod", "pi_cod", "ne_curta", "empenhar",
            ]
        )
        pdf_bytes = gerar_pdf_detalhado(BOLSAS_AUXILIOS, TIPO_REFORCO, "000000/0000-00", vazio)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_pdf_de_anulacao_e_valido(self):
        # Mesmo modelo do Reforço, só que com TIPO_ANULACAO — pedido explícito de escopo
        # (relatório de Anulação de Saldo de Empenho, mesma mecânica/layout do Reforço).
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78")
        linhas = linhas.assign(empenhar=[3000.0, 0.0])

        pdf_bytes = gerar_pdf_detalhado(BOLSAS_AUXILIOS, TIPO_ANULACAO, "001167/2026-78", linhas)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_pdf_sem_processo_unico_e_valido(self):
        # Anulação sem seletor de Processo (pedido explícito: "apareça todos os empenhos") —
        # linhas de mais de um processo juntas, `processo=None` (omite a linha "Processo:" do
        # cabeçalho; cada linha já mostra o próprio processo na coluna "PROCESSO").
        linhas = linhas_todos_os_empenhos(_bolsas_sintetico(), BOLSAS_AUXILIOS)
        linhas = linhas.assign(empenhar=[3000.0, 0.0, 1000.0])

        pdf_bytes = gerar_pdf_detalhado(BOLSAS_AUXILIOS, TIPO_ANULACAO, None, linhas)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))


class TestAgrupadoPorClassificacao(unittest.TestCase):
    def test_linhas_com_mesma_classificacao_somam_numa_so(self):
        # pedido explícito de correção: modelo resumido = "tabela dinâmica" agrupando por
        # Ação/PTRES/Fonte/ND/PI/UGR e somando "empenhar" — duas linhas de fornecedores/itens
        # diferentes, mesma classificação orçamentária, viram uma linha só somada.
        linhas = pd.DataFrame(
            {
                "acao_cod": ["20RK", "20RK", "20RK"],
                "ptres": ["230390", "230390", "230390"],
                "fonte_cod": ["1000", "1000", "1000"],
                "natureza_despesa_cod": ["339039", "339039", "339040"],
                "pi_cod": ["M20RKG01SCN", "M20RKG01SCN", "M20RKG35SCN"],
                "ugr_cod": ["157909", "157909", "157842"],
                "empenhar": [1000.0, 500.0, 300.0],
            }
        )
        agrupado = _agrupado_por_classificacao(linhas)
        self.assertEqual(len(agrupado), 2)
        linha_339039 = agrupado[agrupado["natureza_despesa_cod"] == "339039"].iloc[0]
        self.assertEqual(linha_339039["empenhar"], 1500.0)
        linha_339040 = agrupado[agrupado["natureza_despesa_cod"] == "339040"].iloc[0]
        self.assertEqual(linha_339040["empenhar"], 300.0)


class TestGerarPdfResumido(unittest.TestCase):
    def test_pdf_valido_com_total_correto(self):
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78")
        linhas = linhas.assign(empenhar=linhas["meses_sugeridos"] * linhas["valor_mensal"])

        pdf_bytes = gerar_pdf_resumido(BOLSAS_AUXILIOS, TIPO_REFORCO, "001167/2026-78", linhas)

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 500)

    def test_linha_com_empenhar_nulo_nao_quebra_o_pdf(self):
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78")
        linhas = linhas.assign(empenhar=[float("nan"), 5000.0])

        pdf_bytes = gerar_pdf_resumido(BOLSAS_AUXILIOS, TIPO_REFORCO, "001167/2026-78", linhas)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_pdf_de_relatorio_vazio_nao_quebra(self):
        vazio = pd.DataFrame(
            columns=[
                "processo", "item_despesa", "unidade_cod", "acao_cod", "ptres", "fonte_cod",
                "natureza_despesa_cod", "ugr_cod", "pi_cod", "ne_curta", "empenhar",
            ]
        )
        pdf_bytes = gerar_pdf_resumido(BOLSAS_AUXILIOS, TIPO_REFORCO, "000000/0000-00", vazio)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_pdf_de_anulacao_e_valido(self):
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78")
        linhas = linhas.assign(empenhar=[3000.0, 0.0])

        pdf_bytes = gerar_pdf_resumido(BOLSAS_AUXILIOS, TIPO_ANULACAO, "001167/2026-78", linhas)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_pdf_sem_processo_unico_e_valido(self):
        linhas = linhas_todos_os_empenhos(_bolsas_sintetico(), BOLSAS_AUXILIOS)
        linhas = linhas.assign(empenhar=[3000.0, 0.0, 1000.0])

        pdf_bytes = gerar_pdf_resumido(BOLSAS_AUXILIOS, TIPO_ANULACAO, None, linhas)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
