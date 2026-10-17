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

from src.empenhos_retardada_tela import (
    AVISO_BUSCA_VAZIA,
    AVISO_FILTROS_VAZIOS,
    AVISO_NADA_PASSA,
    AVISO_SEM_CORTE,
    TAMANHO_PAGINA,
    aplicar_acao,
    calcular_destaque,
    com_percentual,
    estado_inicial,
    formatar_brl,
    formatar_pct,
    montar_tela,
    resolver_filtros,
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
        return montar_tela(self.base, estado, campos_rapidos=CAMPOS_RAPIDOS_EXECUCAO, campos_avancados=CAMPOS_AVANCADOS, ano_extracao=ANO)

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

    def test_linhas_trazem_nulo_como_traco(self) -> None:
        dados, _estado, _lista = self._tela(visao="Todos no escopo", usar_rs=False)
        for linha in dados["lista"]["linhas"]:
            if linha["pct_valor"] is None:
                self.assertEqual(linha["pct"], "—")
            self.assertIsNone(linha["corte"])  # nenhum corte ligado: "—", não "abaixo"


if __name__ == "__main__":
    unittest.main()
