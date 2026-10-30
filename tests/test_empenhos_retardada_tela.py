"""Testes de `src/empenhos_retardada_tela.py` — regras da tela de Empenhos com Execução Retardada,
sem Streamlit nem navegador.

Dois tipos de entrada:
  * DataFrames sintéticos montados à mão (cortes, nulos, cascata dos filtros), com valores
    esperados calculados à mão nos próprios testes;
  * a fixture congelada da Execução Mensal (`tests/fixtures/execucao_mensal_2026-09-22.xlsx`,
    a mesma da página) para conferir que os totais da tela reconciliam com a base.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from src.candidatos_anulacao import INDICACOES
from src.empenhos_retardada_tela import (
    AVISO_BUSCA_VAZIA,
    AVISO_FILTROS_VAZIOS,
    AVISO_NADA_PASSA,
    AVISO_SEM_CORTE,
    FAIXAS_IDADE,
    FAIXAS_SALDO,
    OPCOES_AGRUPAMENTO,
    ORDEM_DOS_GRUPOS,
    TAMANHO_PAGINA,
    aplicar_acao,
    calcular_destaque,
    com_faixas,
    com_idade,
    com_percentual,
    cortes_no_padrao,
    estado_inicial,
    formatar_brl,
    formatar_idade,
    formatar_pct,
    idade_por_ne,
    montar_tela,
    resolver_filtros,
    rotular_faixas,
)
from src.execucao_ne_utils import saldo_por_ne
from src.tesouro_execucao_mensal import agregar_por_ne, ler_execucao_mensal
from src.ui_filtros_execucao import CAMPOS_AVANCADOS_EXECUCAO, CAMPOS_RAPIDOS_EXECUCAO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMINHO_FIXTURE = PROJECT_ROOT / "tests/fixtures/execucao_mensal_2026-09-22.xlsx"
CAMPOS_AVANCADOS = CAMPOS_AVANCADOS_EXECUCAO + (
    ("ne_informacao_complementar", "NE - Informação Complementar", "ne_informacao_complementar", None),
    ("unidade_orcamentaria", "Unidade Orçamentária", "unidade_orcamentaria_cod", "unidade_orcamentaria_desc"),
)
NOMES = [c[0] for c in CAMPOS_RAPIDOS_EXECUCAO + CAMPOS_AVANCADOS]
ANO = 2026
MES = 9  # a fixture vai até 09/2026


class FormatacaoTests(unittest.TestCase):
    def test_nulo_zero_e_negativo_sao_distintos(self) -> None:
        self.assertEqual(formatar_brl(None), "—")
        self.assertEqual(formatar_brl(float("nan")), "—")
        self.assertEqual(formatar_brl(0.0), "R$ 0")
        self.assertEqual(formatar_brl(-1234.6), "−R$ 1.235")
        self.assertEqual(formatar_brl(1_234_567.0), "R$ 1.234.567")
        self.assertEqual(formatar_pct(None), "—")
        self.assertEqual(formatar_pct(16.94), "16,9%")


class AplicarAcaoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.estado = estado_inicial(ANO)

    def test_estado_inicial_pre_seleciona_exercicio_e_corte_em_reais(self) -> None:
        self.assertEqual(self.estado["filtros"], {"ano": ["2026"]})
        self.assertTrue(self.estado["usar_rs"])
        self.assertFalse(self.estado["usar_pct"])
        self.assertEqual((self.estado["ordem"], self.estado["sentido"], self.estado["modo"]), ("Saldo", "desc", "OU"))

    def test_nao_altera_o_estado_recebido(self) -> None:
        original = {**self.estado, "filtros": dict(self.estado["filtros"])}
        aplicar_acao(self.estado, {"tipo": "filtro", "nome": "acao", "valores": ["20RK"]}, NOMES)
        aplicar_acao(self.estado, {"tipo": "limpar"}, NOMES)
        self.assertEqual(self.estado, original)

    def test_filtro_define_e_lista_vazia_remove(self) -> None:
        novo = aplicar_acao(self.estado, {"tipo": "filtro", "nome": "acao", "valores": ["20RK — X", "4002 — Y"]}, NOMES)
        self.assertEqual(novo["filtros"]["acao"], ["20RK — X", "4002 — Y"])
        novo = aplicar_acao(novo, {"tipo": "filtro", "nome": "ano", "valores": []}, NOMES)
        self.assertNotIn("ano", novo["filtros"])

    def test_limpar_zera_busca_e_filtros_inclusive_exercicio(self) -> None:
        novo = aplicar_acao({**self.estado, "busca": "abc"}, {"tipo": "limpar"}, NOMES)
        self.assertEqual((novo["busca"], novo["filtros"]), ("", {}))

    def test_ordenar_mesma_coluna_inverte_e_outra_coluna_comeca_pelo_sentido_natural(self) -> None:
        novo = aplicar_acao(self.estado, {"tipo": "ordenar", "coluna": "Saldo"}, NOMES)
        self.assertEqual(novo["sentido"], "asc")
        novo = aplicar_acao(novo, {"tipo": "ordenar", "coluna": "Favorecido"}, NOMES)
        self.assertEqual((novo["ordem"], novo["sentido"]), ("Favorecido", "asc"))
        novo = aplicar_acao(novo, {"tipo": "ordenar", "coluna": "Empenhado"}, NOMES)
        self.assertEqual((novo["ordem"], novo["sentido"]), ("Empenhado", "desc"))

    def test_acoes_que_mudam_a_lista_voltam_para_a_pagina_1(self) -> None:
        na_pagina_3 = {**self.estado, "pagina": 3}
        for acao in (
            {"tipo": "ordenar", "coluna": "NE"},
            {"tipo": "agrupar", "valor": "Credor"},
            {"tipo": "visao", "valor": "Todos no escopo"},
            {"tipo": "corte_rs", "valor": 5000},
            {"tipo": "busca", "valor": "x"},
        ):
            self.assertEqual(aplicar_acao(na_pagina_3, acao, NOMES)["pagina"], 1, acao)
        self.assertEqual(aplicar_acao(na_pagina_3, {"tipo": "detalhe", "ne": "N"}, NOMES)["pagina"], 3)

    def test_acao_invalida_e_ignorada(self) -> None:
        for acao in (
            None, "texto", {"tipo": "desconhecida"}, {"tipo": "filtro", "nome": "inexistente", "valores": ["a"]},
            {"tipo": "corte_rs", "valor": -1}, {"tipo": "corte_rs", "valor": "abc"}, {"tipo": "corte_pct", "valor": 5000},
            {"tipo": "modo", "valor": "XOR"}, {"tipo": "ordenar", "coluna": "Outra"}, {"tipo": "agrupar", "valor": "Outro"},
        ):
            novo = aplicar_acao(self.estado, acao, NOMES)
            self.assertEqual(novo, self.estado, acao)

    def test_corte_zero_e_valido(self) -> None:
        self.assertEqual(aplicar_acao(self.estado, {"tipo": "corte_rs", "valor": 0}, NOMES)["corte_rs"], 0.0)


def _por_ne(saldos: list[float | None], empenhados: list[float | None]) -> pd.DataFrame:
    return pd.DataFrame({"ne_ccor": [f"NE{i}" for i in range(len(saldos))], "saldo": saldos, "empenhada": empenhados})


class CortesTests(unittest.TestCase):
    def setUp(self) -> None:
        # NE0: saldo 50 mil de 100 mil (50%); NE1: 5 mil de 5 mil (100%); NE2: 30 mil de 1 milhão (3%);
        # NE3: empenhado nulo; NE4: empenhado zero e saldo negativo.
        self.visivel = com_percentual(_por_ne([50_000.0, 5_000.0, 30_000.0, None, -200.0], [100_000.0, 5_000.0, 1_000_000.0, None, 0.0]))
        self.estado = {**estado_inicial(ANO), "corte_rs": 10_000.0, "corte_pct": 20.0}

    def test_percentual_nulo_quando_empenhado_nulo_ou_zero(self) -> None:
        self.assertEqual(self.visivel["percentual_saldo"].tolist()[:3], [50.0, 100.0, 3.0])
        self.assertTrue(self.visivel["percentual_saldo"].iloc[3:].isna().all())

    def test_so_corte_em_reais(self) -> None:
        mascara, descricao = calcular_destaque(self.visivel, self.estado)
        self.assertEqual(mascara.tolist(), [True, False, True, False, False])
        self.assertEqual(descricao, "saldo ≥ R$ 10.000")

    def test_dois_cortes_com_ou_e_com_e(self) -> None:
        estado = {**self.estado, "usar_pct": True}
        mascara, descricao = calcular_destaque(self.visivel, estado)
        self.assertEqual(mascara.tolist(), [True, True, True, False, False])
        self.assertIn(" ou ", descricao)
        mascara, descricao = calcular_destaque(self.visivel, {**estado, "modo": "E"})
        self.assertEqual(mascara.tolist(), [True, False, False, False, False])
        self.assertIn(" e ", descricao)

    def test_nenhum_corte_ligado(self) -> None:
        mascara, descricao = calcular_destaque(self.visivel, {**self.estado, "usar_rs": False})
        self.assertFalse(mascara.any())
        self.assertIsNone(descricao)


class IdadeDoSaldoTests(unittest.TestCase):
    """Regra definida pelo usuário (17/10/2026): idade = meses entre o primeiro mês com valor
    empenhado e o mês da extração; só para o exercício da extração. Referência: 09/2026."""

    def setUp(self) -> None:
        self.linhas = pd.DataFrame(
            [
                # NE A: empenhada em mar/2026, reforçada em jul -> conta o primeiro mês: 9 - 3 = 6
                ("A", 2026, 202603, 1_000.0), ("A", 2026, 202607, 500.0),
                # NE B: valor zero em jan não conta; primeiro empenho em mai -> 4
                ("B", 2026, 202601, 0.0), ("B", 2026, 202605, 800.0),
                # NE C: exercício anterior -> sem idade
                ("C", 2025, 202503, 900.0),
                # NE D: nenhum valor empenhado (só nulo) -> sem idade
                ("D", 2026, 202602, None),
                # NE E: empenhada no próprio mês da extração -> 0
                ("E", 2026, 202609, 300.0),
                # NE F: primeiro movimento é um estorno (negativo) em ago -> conta: 1
                ("F", 2026, 202608, -50.0), ("F", 2026, 202609, 400.0),
            ],
            columns=["ne_ccor", "ano", "ano_mes", "empenhada"],
        )

    def test_idade_em_meses_calculada_a_mao(self) -> None:
        idades = idade_por_ne(self.linhas, 2026, 9)
        self.assertEqual(idades.to_dict(), {"A": 6, "B": 4, "E": 0, "F": 1})
        self.assertNotIn("C", idades.index)  # exercício anterior
        self.assertNotIn("D", idades.index)  # sem valor empenhado

    def test_formatacao(self) -> None:
        self.assertEqual(formatar_idade(None), "—")
        self.assertEqual(formatar_idade(pd.NA), "—")
        self.assertEqual(formatar_idade(0), "0 meses")
        self.assertEqual(formatar_idade(1), "1 mês")
        self.assertEqual(formatar_idade(6), "6 meses")

    def test_corte_por_idade_exige_saldo_positivo_e_idade_conhecida(self) -> None:
        visivel = pd.DataFrame({
            "ne_ccor": ["A", "B", "C", "D", "E", "F"],
            "saldo": [500.0, 0.0, 900.0, 100.0, 300.0, -10.0],
            "empenhada": [1_500.0, 800.0, 900.0, 100.0, 300.0, 350.0],
        })
        visivel = com_idade(com_percentual(visivel), self.linhas, 2026, 9)
        estado = {**estado_inicial(2026), "usar_rs": False, "usar_idade": True, "corte_idade": 3}
        mascara, descricao = calcular_destaque(visivel, estado)
        # A: 6 meses, saldo 500 -> passa; B: 4 meses mas saldo zero -> não; C: sem idade -> não;
        # D: sem idade -> não; E: 0 meses -> não; F: idade 1 e saldo negativo -> não
        self.assertEqual(mascara.tolist(), [True, False, False, False, False, False])
        self.assertEqual(descricao, "empenho há 3 meses ou mais com saldo")

    def test_idade_combina_com_os_outros_cortes(self) -> None:
        visivel = pd.DataFrame({"ne_ccor": ["A", "E"], "saldo": [500.0, 20_000.0], "empenhada": [1_500.0, 30_000.0]})
        visivel = com_idade(com_percentual(visivel), self.linhas, 2026, 9)
        estado = {**estado_inicial(2026), "usar_idade": True, "corte_idade": 3}  # R$ 10 mil ligado
        self.assertEqual(calcular_destaque(visivel, estado)[0].tolist(), [True, True])  # OU
        self.assertEqual(calcular_destaque(visivel, {**estado, "modo": "E"})[0].tolist(), [False, False])

    def test_acao_de_corte_por_idade(self) -> None:
        estado = estado_inicial(2026)
        self.assertFalse(estado["usar_idade"])
        self.assertEqual(estado["corte_idade"], 3)
        self.assertTrue(aplicar_acao(estado, {"tipo": "usar_idade", "valor": True}, NOMES)["usar_idade"])
        self.assertEqual(aplicar_acao(estado, {"tipo": "corte_idade", "valor": 6}, NOMES)["corte_idade"], 6)
        for invalido in (2.5, -1, 121, "x"):
            self.assertEqual(aplicar_acao(estado, {"tipo": "corte_idade", "valor": invalido}, NOMES)["corte_idade"], 3)

    def test_dica_so_com_os_cortes_nos_valores_padrao(self) -> None:
        padrao = estado_inicial(ANO)
        self.assertTrue(cortes_no_padrao(padrao))
        for mudanca in (
            {"usar_rs": False}, {"corte_rs": 5_000.0}, {"usar_pct": True}, {"corte_pct": 30.0},
            {"usar_idade": True}, {"corte_idade": 6}, {"modo": "E"},
        ):
            self.assertFalse(cortes_no_padrao({**padrao, **mudanca}), mudanca)
        # filtros, busca, ordem e visão não contam como "ajustar os cortes"
        self.assertTrue(cortes_no_padrao({**padrao, "busca": "x", "ordem": "NE", "visao": "Todos no escopo"}))

    def test_estado_antigo_sem_campos_de_idade_continua_funcionando(self) -> None:
        base = ler_execucao_mensal(CAMINHO_FIXTURE)
        antigo = {k: v for k, v in estado_inicial(ANO).items() if k not in ("usar_idade", "corte_idade")}
        dados, estado, _lista = montar_tela(
            base, antigo, campos_rapidos=CAMPOS_RAPIDOS_EXECUCAO, campos_avancados=CAMPOS_AVANCADOS,
            ano_extracao=ANO, mes_extracao=MES,
        )
        self.assertFalse(estado["usar_idade"])
        self.assertIsNotNone(dados["lista"])


def _valores(serie: pd.Series) -> list:
    return [None if pd.isna(v) else v for v in serie]


class FaixasTests(unittest.TestCase):
    """Faixas de agrupamento (30/10/2026): nulo fica sem faixa; zero e negativo têm faixa própria,
    comparados no centavo; limites superiores inclusivos."""

    def test_saldo(self) -> None:
        saldos = pd.Series([None, -50.0, -1e-14, 0.0, 0.01, 1_000.0, 1_000.01, 10_000.0, 100_000.0, 100_000.01])
        self.assertEqual(
            _valores(rotular_faixas(saldos, FAIXAS_SALDO, com_sinal=True)),
            [None, "saldo negativo", "saldo zero", "saldo zero", "até R$ 1 mil", "até R$ 1 mil",
             "de R$ 1 mil a R$ 10 mil", "de R$ 1 mil a R$ 10 mil", "de R$ 10 mil a R$ 100 mil", "acima de R$ 100 mil"],
        )

    def test_idade(self) -> None:
        idades = pd.Series([None, 0, 2, 3, 5, 6, 8, 9], dtype="Int64")
        self.assertEqual(
            _valores(rotular_faixas(idades, FAIXAS_IDADE, com_sinal=False)),
            [None, "até 2 meses", "até 2 meses", "3 a 5 meses", "3 a 5 meses", "6 a 8 meses", "6 a 8 meses", "9 meses ou mais"],
        )

    def test_percentual_segue_o_sinal_do_saldo_e_situacao_no_corte(self) -> None:
        visivel = pd.DataFrame({
            "saldo": [0.004, 500.0, -10.0, 0.0],
            "percentual_saldo": [0.00004, 50.0, -1.0, None],
            "idade_meses": pd.Series([None, 1, 2, None], dtype="Int64"),
        })
        com = com_faixas(visivel, pd.Series([False, True, False, False]), cortes_ligados=True)
        self.assertEqual(_valores(com["faixa_pct_saldo"]), ["saldo zero", "de 25% a 50%", "saldo negativo", None])
        self.assertEqual(com["situacao_corte"].tolist(), ["Abaixo do corte", "Em destaque (passa do corte)", "Abaixo do corte", "Abaixo do corte"])
        sem_corte = com_faixas(visivel, pd.Series([False] * 4), cortes_ligados=False)
        self.assertTrue(sem_corte["situacao_corte"].isna().all())  # sem corte ligado: nem passa nem fica abaixo
        pd.testing.assert_series_equal(com["saldo"], visivel["saldo"])  # valores não mudam

    def test_acoes_dos_limites_de_anulacao(self) -> None:
        estado = estado_inicial(ANO)
        self.assertEqual(aplicar_acao(estado, {"tipo": "anul_nunca_meses", "valor": 6}, NOMES)["anul_nunca_meses"], 6)
        self.assertEqual(aplicar_acao(estado, {"tipo": "anul_residual_rs", "valor": 0}, NOMES)["anul_residual_rs"], 0.0)
        for tipo, invalido in (("anul_sem_liq_meses", 2.5), ("anul_residual_pct", 101), ("anul_residual_rs", -1)):
            self.assertEqual(aplicar_acao(estado, {"tipo": tipo, "valor": invalido}, NOMES)[tipo], estado[tipo])
        self.assertEqual(aplicar_acao(estado, {"tipo": "agrupar", "valor": "Fonte de recursos"}, NOMES)["grupo"], "Fonte de recursos")


class CascataFiltrosTests(unittest.TestCase):
    CAMPOS = (("cor", "Cor", "cor", None), ("tam", "Tamanho", "tam", "tam_desc"))

    def setUp(self) -> None:
        self.df = pd.DataFrame({
            "cor": ["azul", "azul", "verde"],
            "tam": ["01", "02", "02"],
            "tam_desc": ["P", "M", "M"],
        })

    def test_opcoes_de_cada_campo_respeitam_os_outros_campos_e_nao_a_si_mesmo(self) -> None:
        opcoes, codigos, limpos = resolver_filtros(self.df, self.CAMPOS, {"cor": ["verde"]})
        self.assertEqual(opcoes["tam"], ["02 — M"])  # só tamanho com registro verde
        self.assertEqual(opcoes["cor"], ["azul", "verde"])  # a cor não se restringe pela própria seleção
        self.assertEqual(codigos, {"cor": ["verde"]})
        self.assertEqual(limpos, {"cor": ["verde"]})

    def test_codigo_com_zero_a_esquerda_preservado(self) -> None:
        _opcoes, codigos, _limpos = resolver_filtros(self.df, self.CAMPOS, {"tam": ["01 — P"]})
        self.assertEqual(codigos, {"tam": ["01"]})

    def test_selecao_que_deixou_de_existir_e_descartada(self) -> None:
        _opcoes, codigos, limpos = resolver_filtros(self.df, self.CAMPOS, {"tam": ["inexistente"]})
        self.assertEqual((limpos, codigos), ({}, {}))

    def test_par_sem_registro_descarta_os_dois_como_o_multiselect_antigo(self) -> None:
        # verde + tamanho 01 não existe junto: cada campo é validado contra o que os OUTROS
        # selecionam (verde some das opções de cor com tam=01, e 01 some das de tamanho com
        # cor=verde) — mesmo resultado do multiselect de `src/ui_filtros_execucao.py`.
        _opcoes, codigos, limpos = resolver_filtros(self.df, self.CAMPOS, {"cor": ["verde"], "tam": ["01 — P"]})
        self.assertEqual((limpos, codigos), ({}, {}))


class MontarTelaFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = ler_execucao_mensal(CAMINHO_FIXTURE)

    def _tela(self, **mudancas):
        estado = {**estado_inicial(ANO), **mudancas}
        return montar_tela(
            self.base, estado, campos_rapidos=CAMPOS_RAPIDOS_EXECUCAO, campos_avancados=CAMPOS_AVANCADOS,
            ano_extracao=ANO, mes_extracao=MES,
        )

    def test_resumo_reconcilia_com_a_base(self) -> None:
        dados, _estado, _lista = self._tela()
        por_ne = saldo_por_ne(agregar_por_ne(self.base[self.base["ano"] == ANO]))
        self.assertEqual(dados["resumo"]["empenhos"], len(por_ne))
        self.assertEqual(dados["resumo"]["saldo"], formatar_brl(por_ne["saldo"].sum()))
        self.assertEqual(dados["resumo"]["empenhado"], formatar_brl(por_ne["empenhada"].sum(min_count=1)))
        self.assertIn("exercício em andamento", dados["aviso_exercicio"])

    def test_em_destaque_lista_so_quem_passa_e_resume_o_resto(self) -> None:
        dados, _estado, lista = self._tela()
        por_ne = saldo_por_ne(agregar_por_ne(self.base[self.base["ano"] == ANO]))
        passam = int((por_ne["saldo"] >= 10_000).sum())
        self.assertEqual(dados["lista"]["total"], passam)
        self.assertEqual(len(lista), passam)
        self.assertTrue(lista["passa_corte"].eq(True).all())
        self.assertIn(f"+ {len(por_ne) - passam} empenhos abaixo do corte", dados["lista"]["abaixo"])
        saldos = lista["saldo"].tolist()
        self.assertEqual(saldos, sorted(saldos, reverse=True))  # padrão: saldo, maior primeiro

    def test_todos_no_escopo_paginado(self) -> None:
        dados, estado, lista = self._tela(visao="Todos no escopo", pagina=2)
        self.assertEqual(dados["lista"]["total"], dados["resumo"]["empenhos"])
        self.assertEqual(dados["lista"]["pagina"], 2)
        self.assertEqual(dados["lista"]["inicio"], TAMANHO_PAGINA + 1)
        self.assertEqual(dados["lista"]["linhas"][0]["ne_ccor"], str(lista["ne_ccor"].iloc[TAMANHO_PAGINA]))

    def test_pagina_fora_do_intervalo_volta_para_a_ultima(self) -> None:
        dados, estado, _lista = self._tela(visao="Todos no escopo", pagina=999)
        self.assertEqual(estado["pagina"], dados["lista"]["total_paginas"])

    def test_agrupamento_soma_dos_grupos_igual_ao_total(self) -> None:
        dados, _estado, lista = self._tela(visao="Todos no escopo", grupo="Ação de governo")
        self.assertEqual(sum(s["n"] for s in dados["lista"]["subtotais"].values()), len(lista))
        grupos_na_ordem = list(dict.fromkeys(lista["grupo_lista"]))
        self.assertEqual(len(grupos_na_ordem), len(dados["lista"]["subtotais"]))  # cada grupo contíguo

    def test_sem_corte_avisa_e_nao_lista(self) -> None:
        dados, _estado, lista = self._tela(usar_rs=False)
        self.assertIn(AVISO_SEM_CORTE, dados["avisos_lista"])
        self.assertIsNone(lista)

    def test_corte_alto_demais_avisa_que_nada_passa(self) -> None:
        dados, _estado, lista = self._tela(corte_rs=1e15)
        self.assertIn(AVISO_NADA_PASSA, dados["avisos_lista"])
        self.assertIsNone(lista)

    def test_busca_sem_resultado(self) -> None:
        dados, _estado, lista = self._tela(busca="nao-existe-xyzxyz")
        self.assertEqual(dados["aviso"], AVISO_BUSCA_VAZIA)
        self.assertIsNone(lista)

    def test_combinacao_de_filtros_sem_registro(self) -> None:
        # filtro válido isolado, mas sem registro junto com o exercício: some na limpeza da cascata,
        # então forçamos um exercício sem dados na fixture via filtro de ano inexistente.
        dados, estado, lista = self._tela(filtros={"ano": ["1999"]})
        # ano inexistente é descartado (não é opção) — a tela volta a mostrar todos os exercícios
        self.assertEqual(estado["filtros"], {})
        self.assertIsNotNone(lista)
        self.assertNotEqual(dados.get("aviso"), AVISO_FILTROS_VAZIOS)

    def test_detalhe_da_ne_aberta_e_limpo_quando_ela_sai_da_lista(self) -> None:
        dados, _estado, lista = self._tela()
        ne = str(lista["ne_ccor"].iloc[0])
        dados, estado, _lista = self._tela(ne_aberta=ne)
        self.assertEqual(dados["detalhe"]["ne_ccor"], ne)
        self.assertGreater(len(dados["detalhe"]["origem"]), 0)
        dados, estado, _lista = self._tela(ne_aberta="NE-QUE-NAO-EXISTE")
        self.assertIsNone(dados["detalhe"])
        self.assertIsNone(estado["ne_aberta"])

    def test_idade_so_no_exercicio_da_extracao(self) -> None:
        dados, _estado, lista = self._tela(visao="Todos no escopo", filtros={})
        do_ano = lista[lista["ano"] == ANO]
        de_outros = lista[lista["ano"] != ANO]
        self.assertGreater(len(de_outros), 0)
        self.assertTrue(de_outros["idade_meses"].isna().all())
        self.assertTrue(do_ano["idade_meses"].dropna().between(0, MES - 1).all())

    def test_ligar_corte_por_idade_na_tela(self) -> None:
        dados, _estado, lista = self._tela(usar_rs=False, usar_idade=True, corte_idade=6)
        self.assertIn("empenho há 6 meses ou mais com saldo", dados["resultado_corte"])
        self.assertTrue((lista["idade_meses"] >= 6).all())
        self.assertTrue((lista["saldo"] > 0).all())

    def test_todos_os_agrupamentos_mantem_todos_os_empenhos_e_somam_o_saldo(self) -> None:
        _dados, _estado, sem = self._tela(visao="Todos no escopo", filtros={})
        for grupo in OPCOES_AGRUPAMENTO:
            if OPCOES_AGRUPAMENTO[grupo] is None:
                continue
            dados, _estado, lista = self._tela(visao="Todos no escopo", filtros={}, grupo=grupo)
            self.assertEqual(len(lista), len(sem), grupo)
            self.assertEqual(sorted(lista["ne_ccor"]), sorted(sem["ne_ccor"]), grupo)
            self.assertEqual(sum(s["n"] for s in dados["lista"]["subtotais"].values()), len(sem), grupo)
            self.assertAlmostEqual(lista["saldo"].sum(), sem["saldo"].sum(), places=2, msg=grupo)
            self.assertEqual(len(dict.fromkeys(lista["grupo_lista"])), len(dados["lista"]["subtotais"]), grupo)

    def test_faixas_seguem_a_ordem_natural(self) -> None:
        for grupo, ordem in ORDEM_DOS_GRUPOS.items():
            _dados, _estado, lista = self._tela(visao="Todos no escopo", filtros={}, grupo=grupo)
            presentes = [g for g in dict.fromkeys(lista["grupo_lista"]) if g != "—"]
            self.assertEqual(presentes, [g for g in ordem if g in presentes], grupo)

    def test_indicacoes_na_tela_e_no_detalhe(self) -> None:
        dados, _estado, lista = self._tela(visao="Todos no escopo", filtros={}, grupo="Indicação de anulação")
        self.assertEqual([c["nome"] for c in dados["anulacao"]["contagem"]], list(INDICACOES))
        com = lista[lista["indicacoes_anulacao"].notna()]
        self.assertGreater(len(com), 0)
        ne = str(com["ne_ccor"].iloc[0])
        dados, _estado, _lista = self._tela(visao="Todos no escopo", filtros={}, ne_aberta=ne)
        self.assertEqual(dados["detalhe"]["indicacoes"], str(com["indicacoes_anulacao"].iloc[0]).split("; "))

    def test_linhas_trazem_nulo_como_traco(self) -> None:
        dados, _estado, _lista = self._tela(visao="Todos no escopo", usar_rs=False)
        for linha in dados["lista"]["linhas"]:
            if linha["pct_valor"] is None:
                self.assertEqual(linha["pct"], "—")
            self.assertIsNone(linha["corte"])  # nenhum corte ligado: "—", não "abaixo"


if __name__ == "__main__":
    unittest.main()
