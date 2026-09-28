"""Testes do glossário: integridade dos dados e comportamento da página."""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests._apptest import TEMPO_LIMITE_APPTEST

from src.glossario import GLOSSARIO, SIGLAS_DA_INTERFACE, TEMAS, buscar, termos_por_tema

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GlossarioDadosTests(unittest.TestCase):
    def test_nenhum_termo_duplicado(self) -> None:
        nomes = [termo.termo for termo in GLOSSARIO]
        self.assertEqual(len(nomes), len(set(nomes)))

    def test_todos_os_campos_obrigatorios_preenchidos(self) -> None:
        for termo in GLOSSARIO:
            with self.subTest(termo=termo.termo):
                self.assertTrue(termo.termo.strip())
                self.assertTrue(termo.definicao.strip())
                self.assertTrue(termo.fonte.strip())
                self.assertIn(termo.tema, TEMAS)

    def test_ver_tambem_referencia_termos_existentes(self) -> None:
        nomes = {termo.termo for termo in GLOSSARIO}
        for termo in GLOSSARIO:
            for referencia in termo.ver_tambem:
                with self.subTest(termo=termo.termo, referencia=referencia):
                    self.assertIn(referencia, nomes)

    def test_termos_por_tema_preserva_todos_os_verbetes_sem_duplicar(self) -> None:
        agrupado = termos_por_tema()
        total = sum(len(itens) for itens in agrupado.values())
        self.assertEqual(total, len(GLOSSARIO))
        self.assertEqual(set(agrupado.keys()), set(TEMAS))

    def test_busca_vazia_devolve_tudo(self) -> None:
        self.assertEqual(buscar(""), GLOSSARIO)
        self.assertEqual(buscar("   "), GLOSSARIO)

    def test_busca_ignora_acentos_e_caixa(self) -> None:
        self.assertIn("Esfera Orçamentária", [t.termo for t in buscar("orcamento")])
        resultado_com_acento = {t.termo for t in buscar("descentralização")}
        resultado_sem_acento = {t.termo for t in buscar("descentralizacao")}
        self.assertEqual(resultado_com_acento, resultado_sem_acento)
        self.assertTrue(resultado_com_acento)

    def test_busca_por_sigla(self) -> None:
        termos = {t.termo for t in buscar("PTRES")}
        self.assertIn("Programa de Trabalho Resumido", termos)

    def test_siglas_exibidas_na_interface_estao_mapeadas(self) -> None:
        for sigla in SIGLAS_DA_INTERFACE:
            with self.subTest(sigla=sigla):
                correspondencias = buscar(sigla)
                self.assertTrue(correspondencias)
                self.assertTrue(
                    any(termo.sigla == sigla or sigla in termo.aliases for termo in correspondencias)
                )

    def test_busca_encontra_alias_operacional(self) -> None:
        termos = {t.termo for t in buscar("BI CPOC")}
        self.assertIn("Tesouro Gerencial", termos)

    def test_resumo_e_detalhes_separam_a_leitura_em_camadas(self) -> None:
        termo = next(t for t in GLOSSARIO if t.termo == "Empenho")
        self.assertTrue(termo.resumo.endswith("."))
        self.assertIsNotNone(termo.detalhes)
        self.assertLess(len(termo.resumo), len(termo.definicao))

    def test_busca_sem_resultado(self) -> None:
        self.assertEqual(buscar("termo-que-nao-existe-no-glossario"), ())


class GlossarioPageTests(unittest.TestCase):
    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=TEMPO_LIMITE_APPTEST)
        app.run()
        app.switch_page("app_pages/glossario.py")
        app.run()
        return app

    def test_renderiza_primeira_pagina_de_cartoes_sem_busca(self) -> None:
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Glossário")
        # Expanders com ícone são expostos como ``status`` no AppTest 1.61.
        # 10 cartões por página + o expander "Exportar e importar o glossário".
        self.assertEqual(len(app.get("status")), 11)
        self.assertEqual(len(app.text_input), 1)
        self.assertEqual(len(app.selectbox), 1)
        self.assertEqual(len(app.segmented_control), 1)

    def test_busca_filtra_os_cartoes(self) -> None:
        app = self._open_page()

        app.text_input[0].set_value("PTRES").run()

        self.assertEqual(len(app.exception), 0)
        self.assertGreaterEqual(len(app.get("status")), 1)
        headings = [m.value for m in app.markdown if m.value.startswith("####")]
        self.assertTrue(any("Programa de Trabalho Resumido" in h for h in headings))

    def test_busca_por_nova_sigla_operacional(self) -> None:
        app = self._open_page()

        app.text_input[0].set_value("PF").run()

        self.assertEqual(len(app.exception), 0)
        headings = [m.value for m in app.markdown if m.value.startswith("####")]
        self.assertTrue(any("Programação Financeira" in h for h in headings))

    def test_busca_sem_resultado_mostra_aviso(self) -> None:
        app = self._open_page()

        app.text_input[0].set_value("termo-que-nao-existe-no-glossario").run()

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(len(app.warning) >= 1)


if __name__ == "__main__":
    unittest.main()
