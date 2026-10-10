"""Testes da página Empenhos com Execução Retardada, com fixture congelada da Execução Mensal.

Migrada em 22/09/2026 (pedido explícito: "os filtros da seção consulta de empenho sejam
replicados na seção execução retardada") junto com a própria página — de leitura direta do
manifesto real da Execução Anual para o mesmo padrão de mock já usado em
`test_consulta_empenhos_page.py`: a página lê `Manifesto.atual()`/`carregar_atual()` de
`src.importacao_execucao_mensal`, a suíte mocka essas duas funções (não a página em si, ver
docstring de `test_consulta_empenhos_page.py` para o motivo) contra a MESMA fixture congelada
(`tests/fixtures/execucao_mensal_2026-09-21.xlsx`) que aquela página já usa — não depende de
nenhum manifesto real em `data/manifestos/`, nem de a extração real estar disponível/atualizada
no ambiente de teste.

Cobre as regras descritas na docstring de `app_pages/empenhos_execucao_retardada.py`: exercício
vigente pré-selecionado, os dois cortes de destaque (R$ e %, independentes, com um seletor E/OU
que só aparece quando os dois estão ligados — padrão OU), aviso quando nenhum corte está
ligado, busca livre, e os 2 filtros avançados que só existem na Execução Mensal (paridade com
Consulta de Empenhos).
"""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from io import BytesIO

import pandas as pd
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest

from tests._apptest import TEMPO_LIMITE_APPTEST

from src.importacao_execucao_mensal import gerar_manifesto
from src.relatorio_empenhos_retardada import ContextoRelatorio, gerar_xlsx
from src.tesouro_execucao_mensal import ler_execucao_mensal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMINHO_FIXTURE = PROJECT_ROOT / "tests/fixtures/execucao_mensal_2026-09-22.xlsx"


class EmpenhosExecucaoRetardadaPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataframe = ler_execucao_mensal(CAMINHO_FIXTURE)
        cls.manifesto = gerar_manifesto(cls.dataframe, CAMINHO_FIXTURE)

    def setUp(self) -> None:
        self._patch_manifesto = patch(
            "src.importacao_execucao_mensal.Manifesto.atual", return_value=self.manifesto
        )
        self._patch_carregar = patch(
            "src.importacao_execucao_mensal.carregar_atual", return_value=self.dataframe.copy()
        )
        self._patch_manifesto.start()
        self._patch_carregar.start()

    def tearDown(self) -> None:
        self._patch_carregar.stop()
        self._patch_manifesto.stop()

    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=TEMPO_LIMITE_APPTEST)
        app.run()
        app.switch_page("app_pages/empenhos_execucao_retardada.py")
        app.run()
        return app

    def test_renders_page_from_current_manifest(self) -> None:
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Empenhos com Execução Retardada")
        labels = [metric.label for metric in app.metric]
        self.assertEqual(labels, ["Empenhos no escopo", "Empenhado", "Liquidado", "Saldo total (empenhado − liquidado)"])

    def test_coleta_lixo_no_inicio_e_no_fim_da_pagina(self) -> None:
        # cópias da base devolvidas pelo st.cache_data ficavam presas em ciclos (~0,3 GB por interação)
        with patch("gc.collect", return_value=0) as coleta:
            app = self._open_page()
            antes = coleta.call_count
            app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(coleta.call_count - antes, 2)

    def test_shows_procedencia_footer_with_manifest_hash(self) -> None:
        app = self._open_page()

        self.assertTrue(any(f"hash {self.manifesto.sha256[:8]}" in item.value for item in app.caption))

    def test_exercicio_vigente_pre_selecionado(self) -> None:
        app = self._open_page()
        ano_extracao = datetime.fromisoformat(self.manifesto.data_extracao).year

        filtro_ano = next(m for m in app.multiselect if m.label == "Exercício")
        self.assertEqual(filtro_ano.value, [str(ano_extracao)])

    def test_corte_rs_ligado_por_padrao_pct_desligado(self) -> None:
        app = self._open_page()

        usar_rs = next(t for t in app.toggle if t.key and "usar_rs" in t.key)
        usar_pct = next(t for t in app.toggle if t.key and "usar_pct" in t.key)
        self.assertTrue(usar_rs.value)
        self.assertFalse(usar_pct.value)
        self.assertTrue(any("saldo ≥" in item.value for item in app.caption))

    def test_desligar_os_dois_cortes_mostra_aviso_sem_tabela(self) -> None:
        app = self._open_page()

        usar_rs = next(t for t in app.toggle if t.key and "usar_rs" in t.key)
        usar_rs.set_value(False)
        app.run()

        self.assertTrue(
            any("Ligue pelo menos um dos dois cortes" in item.value for item in app.warning)
        )

    def test_ligar_os_dois_cortes_combina_com_ou(self) -> None:
        app = self._open_page()

        usar_pct = next(t for t in app.toggle if t.key and "usar_pct" in t.key)
        usar_pct.set_value(True)
        app.run()

        self.assertTrue(
            any("saldo ≥" in item.value and " ou " in item.value for item in app.caption)
        )

    def test_selecionar_e_com_os_dois_cortes_combina_com_e(self) -> None:
        # pedido explicito do usuario (22/09/2026): antes o combinador era fixo em OU; agora
        # da pra escolher "E" (interseccao) quando os dois cortes estao ligados.
        app = self._open_page()

        usar_pct = next(t for t in app.toggle if t.key and "usar_pct" in t.key)
        usar_pct.set_value(True)
        app.run()

        seletor = next(s for s in app.segmented_control if s.key and "modo_combinacao" in s.key)
        self.assertEqual(seletor.value, "OU")  # padrao preserva o comportamento ja validado

        seletor.set_value("E")
        app.run()

        self.assertTrue(
            any("saldo ≥" in item.value and " e " in item.value for item in app.caption)
        )

    def test_seletor_e_ou_so_aparece_com_os_dois_cortes_ligados(self) -> None:
        app = self._open_page()  # padrao: so usar_rs ligado

        self.assertFalse(
            any(s.key and "modo_combinacao" in s.key for s in app.segmented_control)
        )

    def test_busca_livre_narrows_scope(self) -> None:
        app = self._open_page()

        empenhos_no_escopo_antes = next(m for m in app.metric if m.label == "Empenhos no escopo").value

        busca = next(t for t in app.text_input if t.label == "Busca livre")
        busca.set_value("termo-que-nao-deve-existir-em-nenhuma-ne-xyzxyz")
        app.run()

        self.assertTrue(any("Nenhum empenho encontrado" in item.value for item in app.warning))
        self.assertNotEqual(empenhos_no_escopo_antes, "0")

    def test_busca_livre_restringe_opcoes_dos_filtros_rapidos(self) -> None:
        # mesmo bug relatado e corrigido em consulta_empenhos.py (mesmo mecanismo de filtro
        # aqui, ver src/ui_filtros_execucao.py) — os filtros ofereciam atributos de NEs fora
        # da busca. "informatica", dentro do exercício vigente pré-selecionado (2026, ver
        # `ano_extracao`), bate numa única "Ação de Governo" nesta fixture:
        # "FUNCIONAMENTO DE INSTITUICOES FEDERAIS DE ENSINO SUPERIOR".
        app = self._open_page()
        busca = next(t for t in app.text_input if t.label == "Busca livre")
        busca.set_value("informatica")
        app.run()

        self.assertEqual(len(app.exception), 0)
        acao_filter = next(m for m in app.multiselect if m.label == "Ação de Governo")
        self.assertEqual(len(acao_filter.options), 1)
        self.assertTrue(any("FUNCIONAMENTO DE INSTITUICOES FEDERAIS DE ENSINO SUPERIOR" in o for o in acao_filter.options))

    def test_visualizacao_padrao_em_destaque(self) -> None:
        app = self._open_page()

        seletor = next(s for s in app.segmented_control if s.key and "visualizacao" in s.key)
        self.assertEqual(seletor.value, "Em destaque")
        self.assertTrue(any("empenhos abaixo do corte" in item.value for item in app.caption))

    def test_visualizacao_todos_lista_todo_o_escopo_paginado(self) -> None:
        # pedido explicito (28/09/2026): a pagina nao mostrava todas as NEs do escopo.
        app = self._open_page()
        no_escopo = int(next(m for m in app.metric if m.label == "Empenhos no escopo").value)

        seletor = next(s for s in app.segmented_control if s.key and "visualizacao" in s.key)
        seletor.set_value("Todos no escopo")
        app.run()

        self.assertEqual(len(app.exception), 0)
        self.assertGreater(no_escopo, 100)  # a fixture exige mais de uma pagina
        self.assertTrue(any(f"de {no_escopo} empenhos." in item.value and "Exibindo 1–100" in item.value for item in app.caption))
        self.assertFalse(any("empenhos abaixo do corte" in item.value for item in app.caption))
        botoes_ver = [b for b in app.button if b.label == "Ver"]
        self.assertEqual(len(botoes_ver), 100)
        self.assertTrue(any(f"{no_escopo} empenhos — mesma lista" in item.value for item in app.caption))

    def test_visualizacao_todos_funciona_com_cortes_desligados(self) -> None:
        app = self._open_page()
        next(t for t in app.toggle if t.key and "usar_rs" in t.key).set_value(False)
        next(s for s in app.segmented_control if s.key and "visualizacao" in s.key).set_value("Todos no escopo")
        app.run()

        self.assertEqual(len(app.exception), 0)
        self.assertFalse(any("Ligue pelo menos um dos dois cortes" in item.value for item in app.warning))
        self.assertTrue(any(b.label == "Ver" for b in app.button))

    # --- relatório = o que está na tela (pedido explícito, 28/09/2026) ------------------------
    # A geração do PDF/Excel só roda no clique do download (callable), que o AppTest não
    # dispara. Por isso os testes abaixo capturam a lista que a página montou via
    # `montar_lista_relatorio` (a MESMA usada para desenhar a tabela e para os downloads),
    # comparam com o que a tela mostra, e passam essa lista pelo gerador de Excel.
    def _abrir_capturando_lista(self, visualizacao: str | None = None) -> tuple[AppTest, list[pd.DataFrame]]:
        import src.relatorio_empenhos_retardada as modulo

        capturadas: list[pd.DataFrame] = []
        original = modulo.montar_lista_relatorio

        def _espia(*args, **kwargs):
            resultado = original(*args, **kwargs)
            capturadas.append(resultado)
            return resultado

        patcher = patch("src.relatorio_empenhos_retardada.montar_lista_relatorio", side_effect=_espia)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = self._open_page()
        if visualizacao is not None:
            next(s for s in app.segmented_control if s.key and "visualizacao" in s.key).set_value(visualizacao)
            capturadas.clear()
            app.run()
        return app, capturadas

    def _linhas_e_saldo_do_xlsx(self, lista: pd.DataFrame) -> tuple[int, float]:
        contexto = ContextoRelatorio("x", None, "22/09/2026", "hash", "29/09/2026 10:00")
        planilha = load_workbook(BytesIO(gerar_xlsx(lista, contexto)))["Empenhos"]
        cabecalho = [c.value for c in planilha[1]]
        coluna_saldo = cabecalho.index("Saldo")
        valores = [linha[coluna_saldo].value for linha in planilha.iter_rows(min_row=2)]
        return len(valores), sum(v for v in valores if v is not None)

    def test_relatorio_em_destaque_bate_com_a_tela(self) -> None:
        app, capturadas = self._abrir_capturando_lista()

        self.assertEqual(len(app.exception), 0)
        lista = capturadas[-1]
        legenda = next(c.value for c in app.caption if " empenhos com saldo ≥" in c.value)
        em_destaque = int(legenda.split(" de ")[0])
        self.assertEqual(len(lista), em_destaque)
        self.assertTrue(lista["passa_corte"].eq(True).all())
        self.assertTrue(any(f"{em_destaque} empenhos — mesma lista" in c.value for c in app.caption))
        self.assertEqual({b.label for b in app.get("download_button")}, {"Baixar PDF", "Baixar Excel"})

        linhas_xlsx, saldo_xlsx = self._linhas_e_saldo_do_xlsx(lista)
        self.assertEqual(linhas_xlsx, em_destaque)
        self.assertAlmostEqual(saldo_xlsx, float(lista["saldo"].sum()), places=2)

    def test_relatorio_todos_no_escopo_bate_com_a_tela(self) -> None:
        app, capturadas = self._abrir_capturando_lista("Todos no escopo")

        self.assertEqual(len(app.exception), 0)
        lista = capturadas[-1]
        no_escopo = int(next(m for m in app.metric if m.label == "Empenhos no escopo").value)
        saldo_tela = next(m for m in app.metric if m.label.startswith("Saldo total")).value
        self.assertEqual(len(lista), no_escopo)
        # mesmo formato do KPI (reais inteiros, ponto de milhar) — o total do relatório é o do topo.
        self.assertEqual("R$ " + f"{abs(round(lista['saldo'].sum())):,.0f}".replace(",", "."), saldo_tela.lstrip("−"))
        # primeira linha exibida na tela = primeira linha do relatório (mesma ordenação).
        primeira_ne = next(m.value for m in app.markdown if m.value.startswith(str(lista["ano"].iloc[0])) and "NE" in m.value)
        self.assertTrue(str(lista["ne_ccor"].iloc[0]).endswith(primeira_ne))

        linhas_xlsx, saldo_xlsx = self._linhas_e_saldo_do_xlsx(lista)
        self.assertEqual(linhas_xlsx, no_escopo)
        self.assertAlmostEqual(saldo_xlsx, float(lista["saldo"].sum()), places=2)

    def test_filtros_avancados_incluem_as_2_dimensoes_exclusivas_da_execucao_mensal(self) -> None:
        # Paridade com Consulta de Empenhos (pedido explícito, 22/09/2026): os 13 avançados
        # compartilhados (`src/ui_filtros_execucao.py`) mais estas 2, exclusivas desta base —
        # ver `_CAMPO_NE_INFORMACAO_COMPLEMENTAR`/`_CAMPO_UNIDADE_ORCAMENTARIA` na página.
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        rotulos = {m.label for m in app.multiselect}
        self.assertIn("NE - Informação Complementar", rotulos)
        self.assertIn("Unidade Orçamentária", rotulos)
        self.assertTrue(any("15 atributos cruzados" in item.value for item in app.caption))


if __name__ == "__main__":
    unittest.main()
