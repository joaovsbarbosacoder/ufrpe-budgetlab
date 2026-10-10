"""Testes do Relatório de Reforço de Empenho (src/relatorio_reforco_empenho.py).

Dados sintéticos — a lógica é pura reorganização de colunas já validadas em
`ler_bolsas_auxilios`/`ler_contratos_continuos`, não precisa de fixture de planilha real.
"""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.necessidade_empenho import descricao_vigencia
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


class TestCabecalhoDetalhado(unittest.TestCase):
    def test_cabecalho_segue_o_modelo_com_item_lic_e_sem_unidade(self):
        from src.relatorio_reforco_empenho import _cabecalho_detalhado

        self.assertEqual(
            _cabecalho_detalhado(TIPO_REFORCO),
            [
                "Nº CONTRATO", "Nº PROCESSO EMPENHO", "FORNECEDOR", "CNPJ/CPF FORNEC", "AÇÃO", "PTRES",
                "FONTE", "ND", "UGR", "PI", "EMPENHO", "ITEM LIC.", "EMPENHAR (R$)",
            ],
        )
        self.assertEqual(_cabecalho_detalhado(TIPO_ANULACAO)[-1], "ANULAR (R$)")

    def test_larguras_acompanham_as_colunas_e_cabem_na_pagina(self):
        from src.relatorio_reforco_empenho import _LARGURAS_COLUNA_DETALHADO, _cabecalho_detalhado

        self.assertEqual(len(_LARGURAS_COLUNA_DETALHADO), len(_cabecalho_detalhado(TIPO_REFORCO)))
        self.assertLessEqual(sum(_LARGURAS_COLUNA_DETALHADO), 756)

    def test_contratos_trazem_contrato_e_cnpj_nas_linhas(self):
        df = _continuos_sintetico().assign(
            contrato_numero=["23/2025", "29/2024", "05/2026", "29/2021"],
            fornecedor_cnpj_cpf=["76659820000151", "11863530000180", "12345678000100", "7674744000130"],
        )
        linhas = linhas_para_processo(df, CONTRATOS_CONTINUOS, "001370/2026-44", 2026)
        apc = linhas[linhas["item_despesa"].str.startswith("Associação")].iloc[0]
        self.assertEqual(apc["contrato"], "23/2025")
        self.assertEqual(apc["cnpj_cpf"], "76659820000151")
        # contrato com 2 itens de licitação: contrato e CNPJ repetidos nas duas linhas
        tekis = linhas[linhas["item_despesa"].str.startswith("Tekis")]
        self.assertEqual(len(tekis), 2)
        self.assertEqual(set(tekis["contrato"]), {"29/2021"})

    def test_bolsas_ficam_com_contrato_e_cnpj_vazios(self):
        linhas = linhas_para_processo(_bolsas_sintetico(), BOLSAS_AUXILIOS, "001167/2026-78", 2026)
        self.assertTrue(linhas[["contrato", "cnpj_cpf"]].isna().all().all())

    def test_cnpj_sem_zero_a_esquerda_e_completado_sem_mexer_em_cpf_ou_cnpj_completo(self):
        from src.relatorio_reforco_empenho import _formatar_cnpj_cpf

        self.assertEqual(_formatar_cnpj_cpf("7578965000105"), "07578965000105")
        self.assertEqual(_formatar_cnpj_cpf("76659820000151"), "76659820000151")
        self.assertEqual(_formatar_cnpj_cpf("12345678901"), "12345678901")
        self.assertEqual(_formatar_cnpj_cpf(None), "")

    def test_pdf_detalhado_de_contratos_com_contrato_e_cnpj_gera(self):
        df = _continuos_sintetico().assign(
            contrato_numero=["23/2025", "29/2024", "05/2026", "29/2021"],
            fornecedor_cnpj_cpf=["76659820000151", "11863530000180", "12345678000100", "7674744000130"],
        )
        linhas = linhas_para_processo(df, CONTRATOS_CONTINUOS, "001370/2026-44", 2026)
        linhas = linhas.assign(empenhar=1000.0)
        pdf = gerar_pdf_detalhado(CONTRATOS_CONTINUOS, TIPO_REFORCO, "001370/2026-44", linhas)
        self.assertTrue(pdf.startswith(b"%PDF"))


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


class TestSugestaoRespeitaVigenciaEStatusContinuos(unittest.TestCase):
    """Pedido explícito (02/10/2026): contrato SUSPENSO, vencido ou com vigência encerrada começa
    com sugestão zerada; a vigência limita os meses sugeridos (mês final proporcional). Usa
    `meses_a_empenhar` como sugestão base (sem mês de início, o calendário não entra) para os
    valores serem determinísticos. Só a sugestão inicial muda."""

    PROCESSO_APC = "001370/2026-44"  # APC (3,0 mil/mês, sug. 1,5), Brascon (2,0 mil, 0,0), Tekis (2 itens)
    PROCESSO_CELPE = "000214/2026-66"  # CELPE (5,0 mil/mês, sug. 3,0)

    @staticmethod
    def _df(ajustes: dict[str, dict] | None = None) -> pd.DataFrame:
        df = _continuos_sintetico()
        df["status_contrato"] = "ATIVO"
        df["vigencia_fim"] = pd.NaT
        for ne, campos in (ajustes or {}).items():
            for campo, valor in campos.items():
                df.loc[df["ne_curta"] == ne, campo] = valor
        return df

    def _linhas(self, processo: str, ajustes: dict[str, dict] | None = None):
        return linhas_para_processo(self._df(ajustes), CONTRATOS_CONTINUOS, processo, 2026)

    def test_sem_restricao_nada_muda_e_nao_ha_situacao(self):
        linhas = self._linhas(self.PROCESSO_APC)
        apc = linhas[linhas["ne_curta"] == "2026NE000100"].iloc[0]
        self.assertEqual(apc["meses_sugeridos"], 1.5)
        self.assertTrue(linhas["situacao_vigencia"].isna().all())

    def test_suspenso_zera_a_sugestao(self):
        linhas = self._linhas(self.PROCESSO_APC, {"2026NE000100": {"status_contrato": "SUSPENSO"}})
        apc = linhas[linhas["ne_curta"] == "2026NE000100"].iloc[0]
        self.assertEqual(apc["meses_sugeridos"], 0.0)  # era 1,5
        self.assertEqual(apc["situacao_vigencia"], "Suspenso")
        tekis = linhas[linhas["ne_curta"] == "2026NE000084"]
        self.assertTrue((tekis["meses_sugeridos"] == 0.000648).all())  # os outros contratos não mudam

    def test_suspenso_com_varios_itens_zera_todas_as_linhas_do_contrato(self):
        linhas = self._linhas(self.PROCESSO_APC, {"2026NE000084": {"status_contrato": "SUSPENSO"}})
        tekis = linhas[linhas["ne_curta"] == "2026NE000084"]
        self.assertEqual(len(tekis), 2)
        self.assertTrue((tekis["meses_sugeridos"] == 0.0).all())

    def test_vencido_sem_data_zera(self):
        linhas = self._linhas(self.PROCESSO_CELPE, {"2026NE000102": {"status_contrato": "VENCIDO"}})
        self.assertEqual(linhas.iloc[0]["meses_sugeridos"], 0.0)  # era 3,0
        self.assertEqual(linhas.iloc[0]["situacao_vigencia"], "Vencido, sem data de vigência")

    def test_vencido_com_vigencia_futura_segue_a_data(self):
        linhas = self._linhas(
            self.PROCESSO_CELPE,
            {"2026NE000102": {"status_contrato": "VENCIDO", "vigencia_fim": pd.Timestamp("2027-03-01")}},
        )
        self.assertEqual(linhas.iloc[0]["meses_sugeridos"], 3.0)  # a data manda: inalterado
        self.assertTrue(pd.isna(linhas.iloc[0]["situacao_vigencia"]))

    def test_vigencia_encerrada_antes_do_exercicio_zera(self):
        linhas = self._linhas(self.PROCESSO_CELPE, {"2026NE000102": {"vigencia_fim": pd.Timestamp("2025-12-31")}})
        self.assertEqual(linhas.iloc[0]["meses_sugeridos"], 0.0)
        self.assertEqual(linhas.iloc[0]["situacao_vigencia"], "Vigência encerrada em 31/12/2025")

    def test_vigencia_no_exercicio_limita_os_meses_com_mes_final_proporcional(self):
        # fim 15/03: vigente 2 + 15/31 = 2,48 meses; sem empenho considerado, teto 2,48 < 3,0.
        linhas = self._linhas(self.PROCESSO_CELPE, {"2026NE000102": {"vigencia_fim": pd.Timestamp("2026-03-15")}})
        self.assertAlmostEqual(linhas.iloc[0]["meses_sugeridos"], 2 + 15 / 31)
        self.assertEqual(linhas.iloc[0]["situacao_vigencia"], "Vigência até 15/03/2026")

    def test_sugestao_menor_que_o_teto_nao_e_aumentada(self):
        # fim 30/06 (6 meses vigentes) > sugestão 3,0: o teto nunca puxa a sugestão para cima.
        linhas = self._linhas(self.PROCESSO_CELPE, {"2026NE000102": {"vigencia_fim": pd.Timestamp("2026-06-30")}})
        self.assertEqual(linhas.iloc[0]["meses_sugeridos"], 3.0)

    def test_teto_desconta_o_que_ja_foi_empenhado(self):
        # CELPE já empenhou 10.000 (2 meses de 5.000); vigência até 15/03 (2 + 15/31 meses, março
        # tem 31 dias) => teto = 15/31.
        df = self._df({"2026NE000102": {"vigencia_fim": pd.Timestamp("2026-03-15")}})
        df["valor_empenhado_autoritativo"] = [3000.0, 2000.0, 10_000.0, 10_000.0]
        linhas = linhas_para_processo(df, CONTRATOS_CONTINUOS, self.PROCESSO_CELPE, 2026)
        self.assertAlmostEqual(linhas.iloc[0]["meses_sugeridos"], 15 / 31)

    def test_vigencia_ja_coberta_pelo_empenho_zera_o_teto(self):
        # vigência até 28/02 (2 meses) e 2 meses já empenhados => nada a sugerir (zero, não nulo).
        df = self._df({"2026NE000102": {"vigencia_fim": pd.Timestamp("2026-02-28")}})
        df["valor_empenhado_autoritativo"] = [3000.0, 2000.0, 10_000.0, 10_000.0]
        linhas = linhas_para_processo(df, CONTRATOS_CONTINUOS, self.PROCESSO_CELPE, 2026)
        self.assertEqual(linhas.iloc[0]["meses_sugeridos"], 0.0)

    def test_sugestao_nula_continua_nula_salvo_contrato_nao_vigente(self):
        df = self._df({"2026NE000102": {"vigencia_fim": pd.Timestamp("2026-06-30")}})
        df.loc[df["ne_curta"] == "2026NE000102", "meses_a_empenhar"] = float("nan")
        linhas = linhas_para_processo(df, CONTRATOS_CONTINUOS, self.PROCESSO_CELPE, 2026)
        self.assertTrue(pd.isna(linhas.iloc[0]["meses_sugeridos"]))
        df.loc[df["ne_curta"] == "2026NE000102", "status_contrato"] = "SUSPENSO"
        linhas = linhas_para_processo(df, CONTRATOS_CONTINUOS, self.PROCESSO_CELPE, 2026)
        self.assertEqual(linhas.iloc[0]["meses_sugeridos"], 0.0)

    def test_suspenso_com_data_limita_ate_a_vespera_da_suspensao(self):
        # 06/10/2026: suspensão em 16/03 → véspera 15/03 → teto 2 + 15/31 meses (< sugestão 3,0)
        ne = "2026NE000102"
        linhas = self._linhas(
            self.PROCESSO_CELPE, {ne: {"status_contrato": "SUSPENSO", "data_suspensao": pd.Timestamp("2026-03-16")}}
        )
        self.assertAlmostEqual(linhas.iloc[0]["meses_sugeridos"], 2 + 15 / 31)
        self.assertEqual(linhas.iloc[0]["situacao_vigencia"], "Suspenso em 16/03/2026")

    def test_suspenso_com_data_nunca_aumenta_a_sugestao(self):
        # suspensão em 01/07 (6 meses vigentes) > sugestão 3,0: inalterada
        linhas = self._linhas(
            self.PROCESSO_CELPE,
            {"2026NE000102": {"status_contrato": "SUSPENSO", "data_suspensao": pd.Timestamp("2026-07-01")}},
        )
        self.assertEqual(linhas.iloc[0]["meses_sugeridos"], 3.0)

    def test_data_da_suspensao_sem_status_suspenso_nao_tem_efeito(self):
        linhas = self._linhas(self.PROCESSO_CELPE, {"2026NE000102": {"data_suspensao": pd.Timestamp("2026-01-01")}})
        self.assertEqual(linhas.iloc[0]["meses_sugeridos"], 3.0)
        self.assertTrue(pd.isna(linhas.iloc[0]["situacao_vigencia"]))

    def test_base_sem_colunas_de_vigencia_nao_muda(self):
        linhas = linhas_para_processo(_continuos_sintetico(), CONTRATOS_CONTINUOS, self.PROCESSO_APC, 2026)
        apc = linhas[linhas["ne_curta"] == "2026NE000100"].iloc[0]
        self.assertEqual(apc["meses_sugeridos"], 1.5)
        self.assertTrue(linhas["situacao_vigencia"].isna().all())

    def test_bolsas_nao_sao_afetadas(self):
        bolsas = _bolsas_sintetico()
        processo = bolsas["processo"].iloc[0]
        linhas = linhas_para_processo(bolsas, BOLSAS_AUXILIOS, processo, 2026)
        self.assertTrue(linhas["situacao_vigencia"].isna().all())
        self.assertFalse(linhas.columns.str.startswith("_").any())  # intermediárias nunca vazam


class TestDescricaoVigencia(unittest.TestCase):
    def test_descricoes(self):
        self.assertEqual(descricao_vigencia("SUSPENSO", pd.NaT, 2026), "Suspenso")
        self.assertEqual(
            descricao_vigencia("SUSPENSO", pd.Timestamp("2026-11-30"), 2026, None, pd.Timestamp("2026-08-01")),
            "Suspenso em 01/08/2026 · Vigência até 30/11/2026",
        )
        self.assertEqual(descricao_vigencia("VENCIDO", pd.NaT, 2026), "Vencido, sem data de vigência")
        self.assertEqual(descricao_vigencia("ATIVO", pd.Timestamp("2026-03-15"), 2026), "Vigência até 15/03/2026")
        self.assertEqual(descricao_vigencia("ATIVO", pd.Timestamp("2025-12-31"), 2026), "Vigência encerrada em 31/12/2025")
        self.assertIsNone(descricao_vigencia("ATIVO", pd.NaT, 2026))
        self.assertIsNone(descricao_vigencia("ATIVO", pd.Timestamp("2027-06-01"), 2026))


class TestInicioDaExecucaoPorDataNoReforco(unittest.TestCase):
    """Início por data (02/10/2026) na sugestão "por calendário" de Contratos Contínuos. Exercício
    de 2020 (passado): o mês vigente é sempre dezembro, então não depende da data de hoje. CELPE:
    despesa 5.000, empenhado 5.000 (1 mês), 12 meses no ano."""

    PROCESSO_CELPE = "000214/2026-66"
    ANO = 2020

    def _celpe(self, **campos):
        df = _continuos_com_calendario_sintetico()
        df["inicio_execucao_data"] = pd.NaT
        for campo, valor in campos.items():
            df.loc[df["ne_curta"] == "2026NE000102", campo] = valor
        linhas = linhas_para_processo(df, CONTRATOS_CONTINUOS, self.PROCESSO_CELPE, self.ANO)
        return linhas.iloc[0]

    def test_sem_data_nada_muda(self):
        # início em janeiro (mês 1): 12 meses decorridos − 1 empenhado = 11
        self.assertAlmostEqual(self._celpe()["meses_sugeridos"], 11.0)

    def test_data_no_exercicio_proporcionaliza_o_primeiro_mes(self):
        # 16/07/2020: jul–dez = 6 meses, menos 15/31 do mês não executado, menos 1 empenhado
        linha = self._celpe(inicio_execucao_data=pd.Timestamp("2020-07-16"))
        self.assertAlmostEqual(linha["meses_sugeridos"], 5 - 15 / 31)
        self.assertEqual(linha["situacao_vigencia"], "Início da execução em 16/07/2020")

    def test_data_manda_sobre_o_mes_de_inicio(self):
        # mês de início 3 (auto/manual), mas a data diz julho: vale a data
        linha = self._celpe(inicio_execucao_efetivo=3, inicio_execucao_data=pd.Timestamp("2020-07-16"))
        self.assertAlmostEqual(linha["meses_sugeridos"], 5 - 15 / 31)

    def test_data_em_ano_anterior_equivale_a_janeiro_cheio(self):
        linha = self._celpe(inicio_execucao_data=pd.Timestamp("2019-05-10"))
        self.assertAlmostEqual(linha["meses_sugeridos"], 11.0)
        self.assertTrue(pd.isna(linha["situacao_vigencia"]))  # início anterior ao exercício não limita

    def test_data_em_ano_posterior_nao_sugere_nada(self):
        linha = self._celpe(inicio_execucao_data=pd.Timestamp("2021-02-01"))
        self.assertEqual(linha["meses_sugeridos"], 0.0)
        self.assertEqual(linha["situacao_vigencia"], "Início da execução em 01/02/2021")

    def test_contrato_sem_data_no_mesmo_relatorio_nao_e_afetado(self):
        df = _continuos_com_calendario_sintetico()
        df["inicio_execucao_data"] = pd.NaT
        df.loc[df["ne_curta"] == "2026NE000102", "inicio_execucao_data"] = pd.Timestamp("2020-07-16")
        linhas = linhas_para_processo(df, CONTRATOS_CONTINUOS, "001370/2026-44", self.ANO)
        brascon = linhas[linhas["ne_curta"] == "2026NE000101"].iloc[0]
        self.assertAlmostEqual(brascon["meses_sugeridos"], 11.0)  # 12 meses − 1 empenhado, como sempre

    def test_bolsas_ignoram_o_campo(self):
        bolsas = _bolsas_com_calendario_sintetico()
        processo = bolsas["processo"].iloc[0]
        sem = linhas_para_processo(bolsas, BOLSAS_AUXILIOS, processo, 2020)["meses_sugeridos"].tolist()
        bolsas["inicio_execucao_data"] = pd.Timestamp("2020-07-16")
        com = linhas_para_processo(bolsas, BOLSAS_AUXILIOS, processo, 2020)["meses_sugeridos"].tolist()
        self.assertEqual(sem, com)  # Bolsas não tem `coluna_inicio_data`: nada muda


def _ta_reforco(numero, inicio, valor, itens=None, situacao="ASSINADO"):
    return {
        "numero": numero, "tipo": "REAJUSTE", "situacao": situacao, "data_inicio": inicio, "data_assinatura": None,
        "valor_mensal": valor, "vigencia_fim": None, "itens": itens,
    }


class TestReforcoComAditivos(unittest.TestCase):
    """Sugestão "por calendário" e valor/rateio vigentes com aditivos (06/10/2026). "Hoje" = 06/10/2026:
    janeiro a outubro decorridos. Valores à mão."""

    HOJE = date(2026, 10, 6)
    PROCESSO_APC = "001370/2026-44"  # APC (3.000/mês, NE ...100), Brascon, Tekis (10.000/mês, itens 70/30)

    @staticmethod
    def _df(aditivos_por_ne: dict | None = None, empenhado: dict | None = None) -> pd.DataFrame:
        df = _continuos_sintetico()
        df["status_contrato"] = "ATIVO"
        df["vigencia_fim"] = pd.NaT
        df["inicio_execucao_efetivo"] = 1
        df["valor_empenhado_autoritativo"] = 0.0
        df["aditivos"] = None
        df["aditivos"] = df["aditivos"].astype(object)
        for ne, aditivos in (aditivos_por_ne or {}).items():
            df.at[df.index[df["ne_curta"] == ne][0], "aditivos"] = aditivos
        for ne, valor in (empenhado or {}).items():
            df.loc[df["ne_curta"] == ne, "valor_empenhado_autoritativo"] = valor
        return df

    def _linhas(self, df, processo=None):
        return linhas_para_processo(df, CONTRATOS_CONTINUOS, processo or self.PROCESSO_APC, 2026, hoje=self.HOJE)

    def test_sugestao_percorre_o_custo_ate_o_mes_vigente(self):
        # APC: 3.000 até junho e 3.300 a partir de 01/07; alvo jan–out = 6×3.000 + 4×3.300 = 31.200;
        # empenhado 18.000 → faltam 13.200 = 4,0 meses do valor vigente (3.300)
        df = self._df({"2026NE000100": [_ta_reforco("1º TA", "2026-07-01", 3_300.0)]}, {"2026NE000100": 18_000.0})
        apc = self._linhas(df).query("ne_curta == '2026NE000100'").iloc[0]
        self.assertEqual(apc["valor_mensal"], 3_300.0)
        self.assertAlmostEqual(apc["meses_sugeridos"], 4.0)
        self.assertEqual(apc["situacao_vigencia"], "1º TA desde 01/07/2026")

    def test_rateio_vigente_define_os_itens_e_seus_valores(self):
        # Tekis: 10.000 → 11.000 e rateio 70/30 → 60/40 em 01/07: itens a 6.600 e 4.400
        ta = _ta_reforco(
            "1º TA", "2026-07-01", 11_000.0, itens=[{"numero": 1, "percentual": 60.0}, {"numero": 2, "percentual": 40.0}]
        )
        tekis = self._linhas(self._df({"2026NE000084": [ta]})).query("ne_curta == '2026NE000084'")
        self.assertEqual(sorted(tekis["valor_mensal"]), [4_400.0, 6_600.0])
        self.assertEqual(list(tekis["item_licitacao"]), [1, 2])

    def test_valor_vigente_zero_nao_gera_sugestao(self):
        # Review Focus 5: valor vigente 0 → sem divisão por zero, sugestão nula
        df = self._df({"2026NE000100": [_ta_reforco("1º TA", "2026-07-01", 0.0)]}, {"2026NE000100": 1_000.0})
        df.loc[df["ne_curta"] == "2026NE000100", "meses_a_empenhar"] = float("nan")  # sem reserva por execução
        apc = self._linhas(df).query("ne_curta == '2026NE000100'").iloc[0]
        self.assertEqual(apc["valor_mensal"], 0.0)
        self.assertTrue(pd.isna(apc["meses_sugeridos"]))

    def test_aditivo_previsto_aparece_na_situacao(self):
        df = self._df({"2026NE000100": [_ta_reforco("2º TA", "2026-07-01", 3_300.0, situacao="PREVISTO")]})
        apc = self._linhas(df).query("ne_curta == '2026NE000100'").iloc[0]
        self.assertEqual(apc["situacao_vigencia"], "2º TA desde 01/07/2026 (previsto)")

    def test_sem_aditivo_a_linha_e_igual_a_de_sempre(self):
        base = self._df()
        sem_coluna = base.drop(columns=["aditivos"])
        pd.testing.assert_frame_equal(self._linhas(base), self._linhas(sem_coluna))
        vazio = self._df({"2026NE000100": []})
        pd.testing.assert_frame_equal(self._linhas(base), self._linhas(vazio))
        apc = self._linhas(base).query("ne_curta == '2026NE000100'").iloc[0]
        self.assertAlmostEqual(apc["meses_sugeridos"], 10.0)  # jan–out a 3.000, nada empenhado

    def test_pdfs_saem_com_aditivos(self):
        df = self._df({"2026NE000100": [_ta_reforco("1º TA", "2026-07-01", 3_300.0)]}, {"2026NE000100": 18_000.0})
        linhas = self._linhas(df)
        linhas = linhas.assign(empenhar=linhas["meses_sugeridos"] * linhas["valor_mensal"])
        self.assertTrue(gerar_pdf_detalhado(CONTRATOS_CONTINUOS, TIPO_REFORCO, self.PROCESSO_APC, linhas).startswith(b"%PDF"))
        self.assertTrue(gerar_pdf_resumido(CONTRATOS_CONTINUOS, TIPO_REFORCO, self.PROCESSO_APC, linhas).startswith(b"%PDF"))

    def test_vigencia_efetiva_do_aditivo_limita_os_meses(self):
        # vigência original 2025-12-31 (encerrada); o TA prorroga até 31/03/2026 e reajusta para 3.300 em 01/01:
        # teto = (3 × 3.300 − 0) ÷ 3.300 = 3 meses
        ta = {**_ta_reforco("1º TA", "2026-01-01", 3_300.0), "vigencia_fim": "2026-03-31"}
        df = self._df({"2026NE000100": [ta]})
        df.loc[df["ne_curta"] == "2026NE000100", "vigencia_fim"] = pd.Timestamp("2025-12-31")
        apc = self._linhas(df).query("ne_curta == '2026NE000100'").iloc[0]
        self.assertAlmostEqual(apc["meses_sugeridos"], 3.0)


if __name__ == "__main__":
    unittest.main()
