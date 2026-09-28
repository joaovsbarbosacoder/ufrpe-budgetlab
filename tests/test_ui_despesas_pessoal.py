"""Contrato de apresentação: dados reais, contexto e eventos do componente."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.despesas_pessoal import MESES_NOMES, grade_mensal, consolidar_por_elemento
from src.ui_despesas_pessoal import montar_painel, validar_edicao


def bases():
    def linha(cod, valor, **extras):
        return dict(acao_cod="20TP", acao_desc="PESSOAL ATIVO", natureza_despesa_cod="319011",
                    natureza_despesa_desc="VENCIMENTOS", natureza_detalhada_cod=cod,
                    natureza_detalhada_desc=cod, po_cod="0000", po_desc="",
                    liquidada=valor, tipo_linha="item_execucao",
                    ano_mes=202608, **extras)
    mensal = pd.DataFrame([linha("31901101", 100), linha("31901131", -10),
                          linha("31901143", 0), linha("31901145", 5)])
    anual = pd.DataFrame([linha("31901101", 0, ano=2025, empenhada=1000),
                         linha("31901131", 0, ano=2025, empenhada=-100),
                         linha("31901143", 0, ano=2025, empenhada=80),
                         linha("31901145", 0, ano=2025, empenhada=50)])
    return mensal, anual


class TestPainelPessoal(unittest.TestCase):
    def setUp(self):
        self.mensal, self.anual = bases()
        self.grade = consolidar_por_elemento(grade_mensal(self.mensal, self.anual, 2026, 202608))

    def painel(self, dotacao=None):
        return montar_painel(self.grade, self.mensal, self.anual,
                             pd.Series({"ativo": 5000}) if dotacao is None else dotacao, 2026,
                             meses_disponiveis=[202608], anos_dotacao=[2026])

    def test_serializa_nulos_sem_nan_e_preserva_zero_e_negativo(self):
        d = self.painel()
        json.dumps(d, allow_nan=False)
        ativo = d["grupos"][0]
        self.assertEqual(ativo["children"][0]["meses"][7], 90)
        self.assertIsNone(ativo["children"][0]["meses"][0])
        self.assertEqual(ativo["children"][1]["meses"][7], 0)

    def test_contexto_historico_consolida_sem_duplicar_especiais(self):
        d = self.painel()
        filhos = d["grupos"][0]["children"]
        self.assertEqual([f["execAnt"] for f in filhos], [900, 80, 50])
        self.assertEqual(d["reconciliacao"]["diferenca"], 0)

    def test_base_ploa_especial_e_nula_mas_zero_regular_e_zero(self):
        self.mensal.loc[self.mensal.natureza_detalhada_cod.eq("31901101"), "liquidada"] = 10
        d = self.painel()
        self.assertEqual(d["grupos"][0]["children"][0]["basePloa"], 0)
        self.assertIsNone(d["grupos"][0]["children"][1]["basePloa"])
        self.assertIsNone(d["grupos"][0]["children"][2]["basePloa"])

    def test_dotacao_nao_e_inventada_por_rubrica(self):
        d = self.painel()
        self.assertEqual(d["grupos"][0]["dotacao"], 5000)
        self.assertTrue(all(f["dotacao"] is None for f in d["grupos"][0]["children"]))

    def test_secoes_referencia_sem_mapeamento_nao_inventam_zeros(self):
        d = self.painel()
        for g in d["grupos"]:
            if g.get("pendente"):
                self.assertEqual(g["meses"], [None] * 12)
                self.assertIsNone(g["dotacao"])
        self.assertEqual(d["total"]["total"], sum(self.grade.total_por_grupo_por_mes().loc["ativo"].dropna()))

    def test_sem_dotacao_nao_anuncia_suficiencia(self):
        self.assertEqual(self.painel(pd.Series(dtype=float))["aviso"]["tipo"], "warning")

    def test_ano_e_data_base_dinamicos_sem_data_do_exemplo(self):
        d = self.painel()
        self.assertEqual(d["dataBase"], "31/08/2026")
        self.assertEqual(d["referencia"], 202608)

    def test_anos_execucao_deriva_dos_meses_disponiveis(self):
        # Pedido do usuário (10/09/2026): seletor de Exercício explícito no componente —
        # `anosExecucao` é a lista de anos que alimenta esse seletor, derivada de
        # `mesesDisponiveis` (não presumida/fixa), pronta pra quando mais de um exercício
        # tiver dado real na mesma base.
        d = montar_painel(self.grade, self.mensal, self.anual, pd.Series({"ativo": 5000}), 2026,
                          meses_disponiveis=[202608], anos_dotacao=[2026])
        self.assertEqual(d["anosExecucao"], [2026])

    def test_anos_execucao_com_dois_exercicios_na_base(self):
        d = montar_painel(self.grade, self.mensal, self.anual, pd.Series({"ativo": 5000}), 2026,
                          meses_disponiveis=[202608, 202701], anos_dotacao=[2026])
        self.assertEqual(d["anosExecucao"], [2026, 2027])

    def test_cores_de_status_reproduzem_handoff(self):
        cores = self.painel()["cores"]
        self.assertEqual(cores["red"], "#F85149")
        self.assertEqual(cores["green"], "#3FB950")

    def test_edicao_preserva_centavos_negativos_e_zero(self):
        for valor in (-10.27, 0, 5.125):
            evento = dict(chave=["ativo", "319011", "319011"], mes=9, valor=valor, referencia=202608)
            self.assertEqual(validar_edicao(evento, self.grade)[2], valor)

    def test_recusa_edicoes_de_reais_inexistentes_e_nao_finitos(self):
        valido = dict(chave=["ativo", "319011", "319011"], mes=9, valor=100, referencia=202608)
        for ajuste in ({"mes": 8}, {"mes": 13}, {"mes": 0}, {"valor": float("nan")},
                       {"valor": float("inf")}, {"valor": None}, {"valor": True},
                       {"chave": ["ativo", "999999", "999999"]}, {"referencia": 202708}):
            with self.subTest(ajuste=ajuste), self.assertRaises(ValueError):
                validar_edicao({**valido, **ajuste}, self.grade)

    def test_pagina_conecta_componente_e_aplica_edicao_sem_mutar_base(self):
        manifesto = SimpleNamespace(data_extracao="2026-09-03T00:00:00", sha256="abc12345")
        dotacao = pd.DataFrame([dict(acao_codigo="20TP", item_informacao_codigo="dotacao_atualizada",
                                      ano_lancamento=2026, valor_movimento_liquido=5000,
                                      plano_orcamentario_codigo="0000")])
        montagens = []
        # A página aplica `consolidar_relatorio_ativo` por cima de `consolidar_por_elemento`
        # — no grupo Ativo, o elemento 319011 (11) vira a linha de relatório "11/12"
        # (ver TestConsolidarRelatorioAtivo).
        evento = dict(chave=["ativo", "11/12", "11/12"], mes=9, valor=-123.45, referencia=202608)
        def render(d):
            montagens.append(d)
            return SimpleNamespace(edicao=evento if len(montagens) == 1 else None, filtros=None, restaurar=None)
        stat_original = Path.stat
        exists_original = Path.exists
        def caminho_base(p):
            return p.name in {
                "execucao_anual_atual.json", "dotacao_anual_atual.json", "execucao_mensal_atual.json",
            }
        def stat_base(p, *args, **kwargs):
            return stat_original(Path(__file__)) if caminho_base(p) else stat_original(p, *args, **kwargs)
        with patch("src.importacao_execucao.Manifesto.atual", return_value=manifesto), \
             patch("src.importacao_dotacao.Manifesto.atual", return_value=manifesto), \
             patch("src.importacao_execucao_mensal.Manifesto.atual", return_value=manifesto), \
             patch("src.importacao_execucao.carregar_atual", return_value=self.anual), \
             patch("src.importacao_dotacao.carregar_atual", return_value=dotacao), \
             patch("src.importacao_execucao_mensal.carregar_atual", return_value=self.mensal), \
             patch("src.ui_despesas_pessoal.render_painel", side_effect=render), \
             patch("pathlib.Path.exists", lambda p: True if caminho_base(p) else exists_original(p)), \
             patch("pathlib.Path.stat", stat_base):
            at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app_pages/despesas_pessoal.py"), default_timeout=15).run()
        self.assertEqual(len(at.exception), 0)
        self.assertGreaterEqual(len(montagens), 2)
        self.assertEqual(montagens[-1]["grupos"][0]["children"][0]["meses"][8], -123.45)
        self.assertTrue(montagens[-1]["temEdicoes"])
        self.assertEqual(self.mensal.iloc[0].liquidada, 100)


class TestContratoVisualDoHandoff(unittest.TestCase):
    """Trava a estrutura observável do HTML recebido, sem congelar os dados do exemplo."""

    @classmethod
    def setUpClass(cls):
        raiz = Path(__file__).resolve().parents[1]
        cls.referencia = (raiz / "design_handoff_streamlit/acompanhamento-pessoal.dc.html").read_text(encoding="utf-8")
        cls.css = (raiz / "assets/despesas_pessoal/painel.css").read_text(encoding="utf-8")
        cls.js = (raiz / "assets/despesas_pessoal/painel.js").read_text(encoding="utf-8")

    def test_preserva_ordem_das_secoes_principais(self):
        referencia = ['class="nav"', 'list="{{ kpis }}"', '>Alerta</span>', "Executado (Jan–Abr)",
                      '<div class="ap-wrap"', "Saldo remanescente", "Estrutura e valores"]
        implementacao = ['<header class="ap-nav"', '<div class="ap-kpis"', '<div class="ap-alert"',
                         '<div class="ap-legend"', '<div class="ap-wrap ap-main-wrap"',
                         '<section class="ap-saldo"', '<footer class="ap-notes"']
        self.assertEqual(sorted(self.referencia.find(v) for v in referencia), [self.referencia.find(v) for v in referencia])
        self.assertEqual(sorted(self.js.find(v) for v in implementacao), [self.js.find(v) for v in implementacao])

    def test_medidas_e_comportamentos_centrais_sao_os_do_handoff(self):
        for trecho in (
            "padding: 18px 32px", "font-size: 21px", "letter-spacing: .06em",
            "padding: 7px 10px", "font-size: 12px", "position: sticky",
            "left: 0", "overflow-x: auto", "padding: 26px 32px 0",
        ):
            with self.subTest(trecho=trecho):
                self.assertIn(trecho, self.css)

    def test_tabelas_tem_17_e_13_colunas_e_grupos_expandem_inline(self):
        self.assertIn("monthHeaders(false)", self.js)
        self.assertIn("contextCells(g,tag)", self.js)
        self.assertIn("monthHeaders(true)", self.js)
        self.assertIn('data-parent="${esc(d.grupos[gi].key)}"', self.js)
        self.assertIn("collapsed[key] = !collapsed[key]", self.js)

    def test_componente_usa_somente_api_v2_e_escopo_parent_element(self):
        self.assertIn("export default function(component)", self.js)
        self.assertIn("parentElement", self.js)
        for proibido in ("components.v1", "Streamlit.setComponentValue", "window.Streamlit", "window.parent.postMessage"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, self.js)


class TestAbasFormulasEHistorico(unittest.TestCase):
    """27/09/2026 — aba de fórmulas editáveis e aba de exercícios anteriores."""

    def setUp(self):
        import streamlit as st
        st.cache_data.clear()  # a página guarda as bases em cache entre execuções do AppTest
        self.mensal, self.anual = bases()
        self.anual["tipo_linha"] = "empenho"
        self.anual["paga"] = 0.0

    def _rodar(self, acao=None):
        manifesto = SimpleNamespace(data_extracao="2026-09-03T00:00:00", sha256="abc12345")
        dotacao = pd.DataFrame([dict(acao_codigo="20TP", item_informacao_codigo="dotacao_atualizada",
                                      ano_lancamento=2025, valor_movimento_liquido=7000,
                                      plano_orcamentario_codigo="0000")])
        montagens = []
        def render(d):
            montagens.append(d)
            return SimpleNamespace(edicao=None, filtros=None, restaurar=None)
        stat_original, exists_original = Path.stat, Path.exists
        nomes = {"execucao_anual_atual.json", "dotacao_anual_atual.json", "execucao_mensal_atual.json"}
        with patch("src.importacao_execucao.Manifesto.atual", return_value=manifesto), \
             patch("src.importacao_dotacao.Manifesto.atual", return_value=manifesto), \
             patch("src.importacao_execucao_mensal.Manifesto.atual", return_value=manifesto), \
             patch("src.importacao_execucao.carregar_atual", return_value=self.anual), \
             patch("src.importacao_dotacao.carregar_atual", return_value=dotacao), \
             patch("src.importacao_execucao_mensal.carregar_atual", return_value=self.mensal), \
             patch("src.ui_despesas_pessoal.render_painel", side_effect=render), \
             patch("pathlib.Path.exists", lambda p: True if p.name in nomes else exists_original(p)), \
             patch("pathlib.Path.stat", lambda p, *a, **k: stat_original(Path(__file__)) if p.name in nomes else stat_original(p, *a, **k)):
            at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app_pages/despesas_pessoal.py"), default_timeout=15)
            at.run()
            if acao:
                acao(at)
                at.run()
        return at, montagens

    @staticmethod
    def _decimo_terceiro(dados):
        ativo = dados["grupos"][0]
        return next(f for f in ativo["children"] if f["key"][2] == "31901143")

    def test_padrao_declara_procedencia_e_mostra_tres_abas(self):
        at, montagens = self._rodar()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual([t.label for t in at.tabs], ["Acompanhamento", "Fórmulas de projeção", "Exercícios anteriores"])
        self.assertIn("Fórmulas de projeção: padrão da metodologia.", montagens[-1]["procedencia"])
        # R_mãe = 100 − 10 (31901101 + 31901131); metade na parcela final de novembro.
        self.assertEqual(self._decimo_terceiro(montagens[-1])["meses"][10], 45)

    def test_campo_editado_recalcula_o_painel_e_fica_declarado(self):
        at, montagens = self._rodar(lambda at: at.number_input(key="dp_f_fracao_antecipacao").set_value(0.0))
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(self._decimo_terceiro(montagens[-1])["meses"][10], 90)
        self.assertIn("Fórmulas ajustadas nesta sessão: fração na antecipação do 13º: 0%", montagens[-1]["procedencia"])
        self.assertEqual(len(at.warning), 1)

    def test_parametro_invalido_mostra_erro_e_usa_padrao(self):
        at, montagens = self._rodar(lambda at: at.selectbox(key="dp_f_mes_parcela").set_value(6))
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(any("meses diferentes" in e.value for e in at.error))
        self.assertEqual(self._decimo_terceiro(montagens[-1])["meses"][10], 45)

    def test_aba_exercicios_anteriores_lista_so_anos_passados(self):
        at, _ = self._rodar()
        seletor = at.selectbox(key="dp_hist_ano")
        self.assertEqual(seletor.options, ["2025"])
        textos = " ".join(m.value for m in at.metric)
        self.assertIn("R$ 7.000,00", textos)  # dotação 2025
        self.assertIn("R$ 1.030,00", textos)  # empenhada 2025 (1000 − 100 + 80 + 50)
        self.assertTrue(any("cobre de 2026 a 2026" in i.value for i in at.info))

    def test_brl_preserva_nulo_zero_e_negativo(self):
        from src.ui_despesas_pessoal_abas import brl
        self.assertEqual(brl(None), "\u2014")
        self.assertEqual(brl(0), "R$ 0,00")
        self.assertEqual(brl(-1e-9), "R$ 0,00")
        self.assertEqual(brl(-1234.5), "\u2212R$ 1.234,50")

    def test_projecao_reconstruida_do_exercicio_anterior(self):
        # 2025 na base mensal: 31901101 = 100 em Jan-Ago e 110 em Set-Dez. Data-base do
        # painel = Ago/2026, então a comparação parte de Ago/2025: projetado 4 × 100 = 400,
        # executado 4 × 110 = 440, diferença 40 (+10,0%).
        linhas = [dict(self.mensal.iloc[0]) | dict(ano_mes=202500 + m, liquidada=100.0 if m <= 8 else 110.0)
                  for m in range(1, 13)]
        self.mensal = pd.concat([self.mensal, pd.DataFrame(linhas)], ignore_index=True)
        at, _ = self._rodar()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(at.selectbox(key="dp_hist_mes_referencia").value, 8)
        tabela = next(t.value for t in at.dataframe if "Meses comparados" in t.value.columns)
        total = tabela.set_index("Grupo").loc["TOTAL"]
        self.assertEqual(total["Projetado"], "R$ 400,00")
        self.assertEqual(total["Executado"], "R$ 440,00")
        self.assertEqual(total["Diferença"], "R$ 40,00")
        self.assertEqual(total["Diferença %"], "+10,0%")

    def test_todos_os_meses_de_partida_sob_demanda(self):
        # 2025: 31901101 = 100 em Jan-Ago e 110 em Set-Dez.
        # Partida Jan: projeta 100 × 11 = 1.100; executado 7 × 100 + 4 × 110 = 1.140 → +3,6%.
        # Partida Ago: 400 × 440 → +10,0%. Partida Set: 3 × 110 = 330 = executado → +0,0%.
        linhas = [dict(self.mensal.iloc[0]) | dict(ano_mes=202500 + m, liquidada=100.0 if m <= 8 else 110.0)
                  for m in range(1, 13)]
        self.mensal = pd.concat([self.mensal, pd.DataFrame(linhas)], ignore_index=True)
        at, _ = self._rodar()
        self.assertFalse(any("Mês de partida" in t.value.columns for t in at.dataframe))  # desligado
        at, _ = self._rodar(lambda at: at.toggle(key="dp_hist_todos_meses").set_value(True))
        self.assertEqual(len(at.exception), 0)
        tabela = next(t.value for t in at.dataframe if "Mês de partida" in t.value.columns).set_index("Mês de partida")
        self.assertEqual(list(tabela.index), MESES_NOMES[:11])
        self.assertEqual(tabela.loc["Jan", "TOTAL"], "+3,6%")
        self.assertEqual(tabela.loc["Ago", "TOTAL"], "+10,0%")
        self.assertEqual(tabela.loc["Set", "TOTAL"], "+0,0%")

    def test_pct_sem_sinal_negativo_em_zero(self):
        from src.ui_despesas_pessoal_abas import _pct
        self.assertEqual(_pct(-0.0004), "+0,0%")
        self.assertEqual(_pct(-0.123), "\u221212,3%")
        self.assertEqual(_pct(None), "\u2014")

    def test_outros_beneficios_por_plano_orcamentario(self):
        # 2025, 212B/0005 (339046, x12): 100 em Jan-Ago, 110 em Set-Dez. Partida Ago:
        # projetado 400, executado 440 → +R$ 40,00 (+10,0%), igual à linha do grupo.
        linhas = [dict(self.mensal.iloc[0]) | dict(
            acao_cod="212B", acao_desc="BENEFICIOS", natureza_despesa_cod="339046",
            natureza_despesa_desc="AUXILIO-ALIMENTACAO", natureza_detalhada_cod="33904601",
            po_cod="0005", po_desc="AUXILIO-ALIMENTACAO DE CIVIS ATIVOS",
            ano_mes=202500 + m, liquidada=100.0 if m <= 8 else 110.0,
        ) for m in range(1, 13)]
        self.mensal = pd.concat([self.mensal, pd.DataFrame(linhas)], ignore_index=True)
        # partida explícita: com Ago/2026 sem Outros Benefícios, a data-base padrão da
        # página deixa de ser Ago (critério de mês fechado) — não é o que se testa aqui.
        at, _ = self._rodar(lambda at: at.selectbox(key="dp_hist_mes_referencia").set_value(8))
        self.assertEqual(len(at.exception), 0)
        tabela = next(t.value for t in at.dataframe if "PO" in t.value.columns)
        linha = tabela.iloc[0]
        self.assertEqual((linha["Ação"], linha["PO"]), ("212B", "0005"))
        self.assertEqual(linha["Descrição"], "AUXILIO-ALIMENTACAO DE CIVIS ATIVOS")
        self.assertEqual(linha["Diferença"], "R$ 40,00")
        self.assertEqual(linha["Diferença %"], "+10,0%")
        self.assertEqual(tabela.iloc[-1]["Ação"], "TOTAL")
        self.assertFalse(any("difere da linha do grupo" in w.value for w in at.warning))
