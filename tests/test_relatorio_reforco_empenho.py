"""Testes do Relatório de Reforço de Empenho (src/relatorio_reforco_empenho.py).

Dados sintéticos — a lógica é pura reorganização de colunas já validadas em
`ler_bolsas_auxilios`/`ler_contratos_continuos`, não precisa de fixture de planilha real.
"""

from __future__ import annotations

import unittest
from datetime import date

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
    processos_disponiveis,
    texto_vigencia,
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
        self.linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78", 2026)

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
        linhas = linhas_para_processo(_continuos_sintetico(), CONTRATOS_CONTINUOS, "001370/2026-44", 2026)
        self.assertEqual(len(linhas), 4)
        self.assertIn("Brascon Gestão Ambiental Ltda", set(linhas["item_despesa"]))

    def test_contrato_de_1_item_nao_ganha_sufixo_de_item(self):
        linhas = linhas_para_processo(_continuos_sintetico(), CONTRATOS_CONTINUOS, "000214/2026-66", 2026)
        self.assertEqual(linhas.iloc[0]["item_despesa"], "Companhia Energética de Pernambuco")

    def test_valor_mensal_vem_de_despesa_mensal(self):
        linhas = linhas_para_processo(_continuos_sintetico(), CONTRATOS_CONTINUOS, "000214/2026-66", 2026)
        self.assertEqual(linhas.iloc[0]["valor_mensal"], 5000.0)

    def test_contrato_com_varios_itens_vira_uma_linha_por_item_com_valor_rateado(self):
        # pedido explícito: o item não é uma entidade própria no cadastro (1 registro por
        # contrato/NE) — só vira linha própria aqui, no relatório, ratreando "despesa_mensal"
        # do contrato pelo percentual de cada item (não colapsado, nem indistinguível).
        linhas = linhas_para_processo(_continuos_sintetico(), CONTRATOS_CONTINUOS, "001370/2026-44", 2026)
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


class TestVigenciaNoRelatorio(unittest.TestCase):
    """Vigência é só informativa: repassada às linhas de Contratos Contínuos, nunca altera
    valores e nunca aparece em Bolsas e Auxílios."""

    HOJE = date(2026, 9, 23)

    def _continuos_com_vigencia(self) -> pd.DataFrame:
        df = _continuos_sintetico()
        df["vigencia_fim"] = pd.to_datetime(
            ["2026-08-22", None, "2026-10-03", "2027-12-31"]
        )
        return df

    def test_vigencia_e_repassada_por_contrato_inclusive_nos_itens_expandidos(self):
        linhas = linhas_para_processo(self._continuos_com_vigencia(), CONTRATOS_CONTINUOS, "001370/2026-44", 2026)
        tekis = linhas[linhas["ne_curta"] == "2026NE000084"]
        self.assertEqual(len(tekis), 2)
        self.assertTrue((tekis["vigencia_fim"] == pd.Timestamp("2027-12-31")).all())
        brascon = linhas[linhas["ne_curta"] == "2026NE000101"].iloc[0]
        self.assertTrue(pd.isna(brascon["vigencia_fim"]))

    def test_vigencia_nao_altera_valores_do_relatorio(self):
        sem = linhas_para_processo(_continuos_sintetico(), CONTRATOS_CONTINUOS, "001370/2026-44", 2026)
        com = linhas_para_processo(self._continuos_com_vigencia(), CONTRATOS_CONTINUOS, "001370/2026-44", 2026)
        colunas = ["item_despesa", "ne_curta", "valor_mensal", "meses_sugeridos", "saldo"]
        pd.testing.assert_frame_equal(sem[colunas], com[colunas])
        self.assertTrue(sem["vigencia_fim"].isna().all())  # base sem a coluna: tudo nulo

    def test_bolsas_continuam_sem_vigencia(self):
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78", 2026)
        self.assertTrue(linhas["vigencia_fim"].isna().all())
        self.assertIsNone(BOLSAS_AUXILIOS.coluna_vigencia)

    def test_pdfs_nao_recebem_coluna_de_vigencia(self):
        linhas = linhas_para_processo(self._continuos_com_vigencia(), CONTRATOS_CONTINUOS, "001370/2026-44", 2026)
        linhas = linhas.assign(meses=1.0, empenhar=100.0)
        self.assertTrue(gerar_pdf_detalhado(CONTRATOS_CONTINUOS, TIPO_REFORCO, "001370/2026-44", linhas).startswith(b"%PDF"))
        self.assertTrue(gerar_pdf_resumido(CONTRATOS_CONTINUOS, TIPO_REFORCO, "001370/2026-44", linhas).startswith(b"%PDF"))

    def test_texto_vigencia(self):
        casos = {
            "2026-08-22": "Vigência até 22/08/2026 · expirada há 32 d",
            "2026-09-23": "Vigência até 23/09/2026 · vence hoje",
            "2026-10-03": "Vigência até 03/10/2026 · vence em 10 d",
            "2027-12-31": "Vigência até 31/12/2027",
        }
        for entrada, esperado in casos.items():
            self.assertEqual(texto_vigencia(entrada, self.HOJE), esperado)

    def test_sem_data_nao_gera_texto(self):
        for vazio in (None, pd.NaT, pd.NA, float("nan"), ""):
            self.assertEqual(texto_vigencia(vazio, self.HOJE), "")


def _continuos_com_calendario_sintetico() -> pd.DataFrame:
    """Mesmas colunas de `_continuos_sintetico()` + as usadas na sugestão "por calendário" (ver
    docstring de `_bolsas_com_calendario_sintetico`, abaixo) — pedido explícito posterior: a
    mesma correção de `meses_no_ano` aplicada a Bolsas vale também para Contratos Contínuos."""

    base = _continuos_sintetico()
    base["inicio_execucao_efetivo"] = [1, 1, 1, 1]
    base["valor_empenhado_autoritativo"] = [30_000.0, 2000.0, 5000.0, 10_000.0]
    base["meses_no_ano"] = [1, 12, 12, 12]
    return base


class TestSugestaoPorCalendarioRespeitaMesesNoAnoContinuos(unittest.TestCase):
    """Mesma correção de `TestSugestaoPorCalendarioRespeitaMesesNoAno` (Bolsas, mais abaixo),
    agora também para Contratos Contínuos (pedido explícito: "implemente essa mesma validação
    que aplicamos para bolsas")."""

    def test_contrato_com_meses_no_ano_1_ja_pago_nao_sugere_reforco(self) -> None:
        # "APC": despesa_mensal 3.000, mas já empenhado o equivalente a 10 meses (30.000) —
        # excede sozinho o teto de meses_no_ano=1, cravado em zero.
        linhas = linhas_para_processo(
            _continuos_com_calendario_sintetico(), CONTRATOS_CONTINUOS, "001370/2026-44", 2026
        )
        linha_apc = linhas[linhas["ne_curta"] == "2026NE000100"].iloc[0]
        self.assertEqual(linha_apc["meses_sugeridos"], 0.0)

    def test_contrato_de_12_meses_nao_e_afetado_pelo_teto(self) -> None:
        # "Brascon": meses_no_ano=12 (não é o fator limitante) — continua vindo do calendário
        # normalmente, mesmo comportamento de antes desta correção.
        linhas = linhas_para_processo(
            _continuos_com_calendario_sintetico(), CONTRATOS_CONTINUOS, "001370/2026-44", 2026
        )
        linha_brascon = linhas[linhas["ne_curta"] == "2026NE000101"].iloc[0]
        self.assertFalse(pd.isna(linha_brascon["meses_sugeridos"]))


def _bolsas_com_calendario_sintetico() -> pd.DataFrame:
    """Mesmas colunas de `_bolsas_sintetico()` + as usadas na sugestão "por calendário"
    (`inicio_execucao_efetivo`/`valor_empenhado_autoritativo`/`meses_no_ano`), que a página
    monta antes de chamar `render_botao_relatorio` (ver `app_pages/bolsas_auxilios.py`) — sem
    elas, `linhas_para_processo` cai de volta pra `meses_a_empenhar` puro (já coberto em
    `TestLinhasParaProcessoBolsas`)."""

    base = _bolsas_sintetico()
    base["inicio_execucao_efetivo"] = [3, 1, None, 6, None]
    base["valor_empenhado_autoritativo"] = [70_000.0, 7500.0, None, 1000.0, None]
    base["meses_no_ano"] = [1, 12, 1, 12, 12]
    return base


class TestSugestaoPorCalendarioRespeitaMesesNoAno(unittest.TestCase):
    """Reproduz o bug real reportado: bolsa "parcela única" (AUXÍLIO BEXT, `meses_no_ano=1`)
    continuava sugerindo reforço pelos meses decorridos do calendário mesmo já paga por
    completo — ver `tests/test_necessidade_empenho.py` para a cobertura na função pura; aqui
    end-to-end via `linhas_para_processo`, com a base já como a página monta (`ano_referencia`
    2026, "hoje" real do teste vem de `date.today()` dentro de `necessidade_ate_mes_vigente` —
    por isso o cenário usa uma bolsa JÁ TOTALMENTE PAGA, cujo resultado zero independe de qual
    mês é hoje)."""

    def setUp(self):
        self.linhas = linhas_para_processo(
            _bolsas_com_calendario_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78", 2026
        )

    def test_parcela_unica_ja_paga_por_completo_nao_sugere_reforco(self):
        # "PADPG": valor_mensal 15.750, mas valor_empenhado_autoritativo/meses_no_ano simulam
        # uma bolsa de 70.000/mês já paga (1 mês, igual ao caso real da BEXT) — sem o teto de
        # meses_no_ano, o calendário (início em março) sugeriria vários meses a mais.
        linha = self.linhas[self.linhas["ne_curta"] == "2026NE000020"].iloc[0]
        self.assertEqual(linha["valor_mensal"], 15_750.0)
        # meses_empenhados_equivalente = 70.000 / 15.750 já excede o teto de 1 mês sozinho —
        # cravado em zero, nunca negativo.
        self.assertEqual(linha["meses_sugeridos"], 0.0)

    def test_bolsa_de_12_meses_nao_e_afetada_pelo_teto(self):
        # "ESO": meses_no_ano=12 (não é o fator limitante) -- continua vindo do calendário
        # normalmente, mesmo comportamento de antes desta correção.
        linha = self.linhas[self.linhas["ne_curta"] == "2026NE000056"].iloc[0]
        self.assertFalse(pd.isna(linha["meses_sugeridos"]))


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
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78", 2026)
        linhas = linhas.assign(empenhar=linhas["meses_sugeridos"] * linhas["valor_mensal"])

        pdf_bytes = gerar_pdf_detalhado(BOLSAS_AUXILIOS, TIPO_REFORCO, "001167/2026-78", linhas)

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 500)

    def test_linha_com_empenhar_nulo_nao_quebra_o_pdf(self):
        # "Meses a Empenhar" sem preencher (dado incompleto na origem, ver
        # `meses_a_empenhar` em necessidade_empenho.py) não pode virar "nan" no PDF.
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78", 2026)
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
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78", 2026)
        linhas = linhas.assign(empenhar=[3000.0, 0.0])

        pdf_bytes = gerar_pdf_detalhado(BOLSAS_AUXILIOS, TIPO_ANULACAO, "001167/2026-78", linhas)
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
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78", 2026)
        linhas = linhas.assign(empenhar=linhas["meses_sugeridos"] * linhas["valor_mensal"])

        pdf_bytes = gerar_pdf_resumido(BOLSAS_AUXILIOS, TIPO_REFORCO, "001167/2026-78", linhas)

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 500)

    def test_linha_com_empenhar_nulo_nao_quebra_o_pdf(self):
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78", 2026)
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
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78", 2026)
        linhas = linhas.assign(empenhar=[3000.0, 0.0])

        pdf_bytes = gerar_pdf_resumido(BOLSAS_AUXILIOS, TIPO_ANULACAO, "001167/2026-78", linhas)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
