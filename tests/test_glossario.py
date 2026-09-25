"""Testes do glossário: integridade dos dados e comportamento da página."""

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.glossario import GLOSSARIO, TEMAS, buscar, termos_por_tema

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

    def test_busca_sem_resultado(self) -> None:
        self.assertEqual(buscar("termo-que-nao-existe-no-glossario"), ())


class GlossarioPageTests(unittest.TestCase):
    def _open_page(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()
        app.switch_page("app_pages/glossario.py")
        app.run(timeout=30)
        return app

    def test_renderiza_um_expander_por_tema_sem_busca(self) -> None:
        app = self._open_page()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.title[0].value, "Glossário")
        self.assertEqual(len(app.get("expander")), len(TEMAS))

    def test_busca_filtra_e_nao_mostra_expanders(self) -> None:
        app = self._open_page()

        app.text_input[0].set_value("PTRES").run(timeout=30)

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.get("expander")), 0)
        headings = [m.value for m in app.markdown if m.value.startswith("#####")]
        self.assertTrue(any("Programa de Trabalho Resumido" in h for h in headings))

    def test_busca_sem_resultado_mostra_aviso(self) -> None:
        app = self._open_page()

        app.text_input[0].set_value("termo-que-nao-existe-no-glossario").run(timeout=30)

        self.assertEqual(len(app.exception), 0)
        self.assertTrue(len(app.warning) >= 1)


if __name__ == "__main__":
    unittest.main()
