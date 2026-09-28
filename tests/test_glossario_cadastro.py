"""Testes do cadastro editável do Glossário (inclusão, edição, exclusão)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from src import glossario_cadastro
from src.glossario import GLOSSARIO, TEMAS, buscar
from src.glossario_cadastro import (
    ErroGlossario,
    analisar_importacao,
    aplicar_importacao,
    atualizar,
    carregar,
    exportar,
    excluir,
    incluir,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

NOVO = {
    "termo": "Termo de Teste",
    "definicao": "Primeira frase. Segunda frase com detalhes.",
    "fonte": "Contexto do sistema (teste)",
    "tema": TEMAS[0],
    "sigla": "TT",
    "aliases": ["Teste"],
}


class CadastroBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.caminho = Path(self._tmp.name) / "glossario" / "cadastro.json"


class LeituraTests(CadastroBase):
    def test_sem_arquivo_devolve_a_base_fixa_sem_gravar(self) -> None:
        self.assertEqual(carregar(self.caminho), GLOSSARIO)
        self.assertFalse(self.caminho.exists())

    def test_arquivo_ilegivel_levanta_erro_e_nao_e_alterado(self) -> None:
        self.caminho.parent.mkdir(parents=True)
        self.caminho.write_text("{ isto nao e json", encoding="utf-8")
        with self.assertRaises(ErroGlossario):
            carregar(self.caminho)
        with self.assertRaises(ErroGlossario):
            incluir(NOVO, self.caminho)
        self.assertEqual(self.caminho.read_text(encoding="utf-8"), "{ isto nao e json")

    def test_caminho_padrao_e_resolvido_na_chamada(self) -> None:
        with mock.patch.object(glossario_cadastro, "CAMINHO_PADRAO", self.caminho):
            incluir(NOVO)
        self.assertTrue(self.caminho.exists())


class InclusaoTests(CadastroBase):
    def test_incluir_materializa_base_mais_o_novo_marcado_personalizado(self) -> None:
        novo = incluir(NOVO, self.caminho)

        self.assertTrue(novo.personalizado)
        termos = carregar(self.caminho)
        self.assertEqual(len(termos), len(GLOSSARIO) + 1)
        self.assertEqual(termos[: len(GLOSSARIO)], GLOSSARIO)
        self.assertEqual(termos[-1].sigla, "TT")
        self.assertEqual(termos[-1].aliases, ("Teste",))
        self.assertTrue(all(not termo.personalizado for termo in termos[:-1]))

    def test_termo_novo_e_encontrado_pela_busca(self) -> None:
        incluir(NOVO, self.caminho)
        encontrados = buscar("TT", carregar(self.caminho))
        self.assertIn("Termo de Teste", [termo.termo for termo in encontrados])

    def test_campos_obrigatorios(self) -> None:
        for campo in ("termo", "definicao", "fonte"):
            with self.subTest(campo=campo), self.assertRaises(ErroGlossario):
                incluir({**NOVO, campo: "   "}, self.caminho)
        with self.assertRaises(ErroGlossario):
            incluir({**NOVO, "tema": "Tema inexistente"}, self.caminho)
        self.assertFalse(self.caminho.exists())

    def test_termo_duplicado_sem_distinguir_caixa_e_acento(self) -> None:
        with self.assertRaises(ErroGlossario):
            incluir({**NOVO, "termo": "empenho"}, self.caminho)
        incluir(NOVO, self.caminho)
        with self.assertRaises(ErroGlossario):
            incluir({**NOVO, "termo": "TERMO DE TÉSTE".replace("É", "E")}, self.caminho)

    def test_ver_tambem_deve_apontar_para_termo_existente(self) -> None:
        with self.assertRaises(ErroGlossario):
            incluir({**NOVO, "ver_tambem": ["Inexistente"]}, self.caminho)
        incluir({**NOVO, "ver_tambem": ["Empenho"]}, self.caminho)
        self.assertEqual(carregar(self.caminho)[-1].ver_tambem, ("Empenho",))

    def test_texto_e_preservado_sem_alterar_conteudo(self) -> None:
        incluir({**NOVO, "definicao": "  Valor 0,00 e código 001234.  "}, self.caminho)
        self.assertEqual(carregar(self.caminho)[-1].definicao, "Valor 0,00 e código 001234.")


class EdicaoTests(CadastroBase):
    def test_editar_termo_da_base_grava_e_marca_como_nao_personalizado(self) -> None:
        original = next(t for t in GLOSSARIO if t.termo == "Empenho")
        dados = {
            "termo": original.termo,
            "definicao": "Nova definição. Detalhe.",
            "fonte": original.fonte,
            "tema": original.tema,
        }
        atualizar("Empenho", dados, self.caminho)

        editado = next(t for t in carregar(self.caminho) if t.termo == "Empenho")
        self.assertEqual(editado.definicao, "Nova definição. Detalhe.")
        self.assertFalse(editado.personalizado)
        self.assertEqual(len(carregar(self.caminho)), len(GLOSSARIO))
        # A base fixa do código nunca é alterada.
        self.assertNotEqual(next(t for t in GLOSSARIO if t.termo == "Empenho").definicao, editado.definicao)

    def test_renomear_atualiza_referencias_e_informa_quem_mudou(self) -> None:
        incluir({**NOVO, "ver_tambem": ["Empenho"]}, self.caminho)
        original = next(t for t in GLOSSARIO if t.termo == "Empenho")
        ajustados = atualizar(
            "Empenho",
            {
                "termo": "Empenho da Despesa",
                "definicao": original.definicao,
                "fonte": original.fonte,
                "tema": original.tema,
                "sigla": original.sigla,
            },
            self.caminho,
        )

        termos = carregar(self.caminho)
        self.assertIn("Termo de Teste", ajustados)
        self.assertEqual(termos[-1].ver_tambem, ("Empenho da Despesa",))
        nomes = {t.termo for t in termos}
        for termo in termos:
            self.assertTrue(set(termo.ver_tambem) <= nomes)

    def test_renomear_para_nome_de_outro_verbete_e_recusado(self) -> None:
        original = next(t for t in GLOSSARIO if t.termo == "Empenho")
        with self.assertRaises(ErroGlossario):
            atualizar(
                "Empenho",
                {"termo": "Liquidação", "definicao": "x.", "fonte": "y", "tema": original.tema},
                self.caminho,
            )
        self.assertFalse(self.caminho.exists())

    def test_editar_verbete_inexistente(self) -> None:
        with self.assertRaises(ErroGlossario):
            atualizar("Nao existe", NOVO, self.caminho)


class ExclusaoTests(CadastroBase):
    def test_excluir_termo_personalizado(self) -> None:
        incluir(NOVO, self.caminho)
        excluir("Termo de Teste", self.caminho)
        self.assertEqual(carregar(self.caminho), GLOSSARIO)

    def test_excluir_termo_da_base_nao_altera_o_codigo(self) -> None:
        incluir(NOVO, self.caminho)
        excluir("Termo de Teste", self.caminho)
        # "Restos a Pagar" pode ser referenciado; use um termo sem referência.
        livre = next(
            t.termo
            for t in GLOSSARIO
            if not any(t.termo in outro.ver_tambem for outro in GLOSSARIO)
        )
        excluir(livre, self.caminho)
        self.assertEqual(len(carregar(self.caminho)), len(GLOSSARIO) - 1)
        self.assertIn(livre, [t.termo for t in GLOSSARIO])

    def test_excluir_termo_referenciado_e_recusado(self) -> None:
        referenciado = next(
            t for t in GLOSSARIO if any(t.termo in outro.ver_tambem for outro in GLOSSARIO)
        )
        with self.assertRaises(ErroGlossario) as contexto:
            excluir(referenciado.termo, self.caminho)
        self.assertIn("Ver também", str(contexto.exception))
        self.assertFalse(self.caminho.exists())

    def test_excluir_inexistente(self) -> None:
        with self.assertRaises(ErroGlossario):
            excluir("Nao existe", self.caminho)


class ExportacaoImportacaoTests(CadastroBase):
    def setUp(self) -> None:
        super().setUp()
        self.origem = Path(self._tmp.name) / "outra_maquina.json"

    def _exportar_de_outra_maquina(self, **edicao) -> str:
        incluir(NOVO, self.origem)
        if edicao:
            atualizar("Empenho", edicao, self.origem)
        return exportar(self.origem)

    def test_exportar_sem_cadastro_devolve_a_base(self) -> None:
        conteudo = exportar(self.caminho)
        self.assertEqual(len(json.loads(conteudo)["termos"]), len(GLOSSARIO))
        self.assertFalse(self.caminho.exists())

    def test_analise_nao_grava_e_classifica(self) -> None:
        original = next(t for t in GLOSSARIO if t.termo == "Empenho")
        conteudo = self._exportar_de_outra_maquina(
            termo="Empenho", definicao="Outra. Definição.", fonte=original.fonte, tema=original.tema
        )
        plano = analisar_importacao(conteudo, self.caminho)

        self.assertEqual([t.termo for t in plano.novos], ["Termo de Teste"])
        self.assertEqual([atual.termo for atual, _ in plano.conflitos], ["Empenho"])
        self.assertEqual(len(plano.iguais), len(GLOSSARIO) - 1)
        self.assertFalse(self.caminho.exists())

    def test_importar_acrescenta_novos_e_preserva_conflitos_por_padrao(self) -> None:
        original = next(t for t in GLOSSARIO if t.termo == "Empenho")
        conteudo = self._exportar_de_outra_maquina(
            termo="Empenho", definicao="Outra. Definição.", fonte=original.fonte, tema=original.tema
        )
        aplicar_importacao(conteudo, False, self.caminho)

        termos = {t.termo: t for t in carregar(self.caminho)}
        self.assertIn("Termo de Teste", termos)
        self.assertTrue(termos["Termo de Teste"].personalizado)
        self.assertEqual(termos["Empenho"].definicao, original.definicao)

    def test_importar_substituindo_conflitos_so_com_pedido_explicito(self) -> None:
        original = next(t for t in GLOSSARIO if t.termo == "Empenho")
        conteudo = self._exportar_de_outra_maquina(
            termo="Empenho", definicao="Outra. Definição.", fonte=original.fonte, tema=original.tema
        )
        aplicar_importacao(conteudo, True, self.caminho)

        termos = {t.termo: t for t in carregar(self.caminho)}
        self.assertEqual(termos["Empenho"].definicao, "Outra. Definição.")

    def test_importar_nunca_remove_verbete_ausente_do_arquivo(self) -> None:
        incluir({**NOVO, "termo": "Local"}, self.caminho)
        aplicar_importacao(self._exportar_de_outra_maquina(), False, self.caminho)
        nomes = {t.termo for t in carregar(self.caminho)}
        self.assertTrue({"Local", "Termo de Teste"} <= nomes)

    def test_importar_arquivo_invalido_nao_grava(self) -> None:
        for conteudo in ("nao e json", "{}", json.dumps({"termos": [{"termo": "x"}]})):
            with self.subTest(conteudo=conteudo), self.assertRaises(ErroGlossario):
                aplicar_importacao(conteudo, True, self.caminho)
        self.assertFalse(self.caminho.exists())

    def test_importar_referencia_quebrada_e_recusado(self) -> None:
        carga = json.loads(exportar(self.caminho))
        carga["termos"][0]["ver_tambem"] = ["Inexistente"]
        with self.assertRaises(ErroGlossario):
            aplicar_importacao(json.dumps(carga), True, self.caminho)
        self.assertFalse(self.caminho.exists())

    def test_importar_arquivo_identico_nao_grava(self) -> None:
        aplicar_importacao(exportar(self.caminho), True, self.caminho)
        self.assertFalse(self.caminho.exists())

    def test_aceita_arquivo_em_bytes_com_bom(self) -> None:
        conteudo = ("﻿" + self._exportar_de_outra_maquina()).encode("utf-8")
        self.assertEqual(len(analisar_importacao(conteudo, self.caminho).novos), 1)


class DataDeAlteracaoTests(CadastroBase):
    def _com_data(self, dia: str):
        return mock.patch.object(glossario_cadastro, "_hoje", return_value=dia)

    def test_base_fixa_e_verbetes_nao_alterados_ficam_sem_data(self) -> None:
        with self._com_data("2026-09-25"):
            incluir(NOVO, self.caminho)
        termos = carregar(self.caminho)
        self.assertEqual(termos[-1].atualizado_em, "2026-09-25")
        self.assertTrue(all(t.atualizado_em is None for t in termos[:-1]))

    def test_editar_grava_a_data_do_dia_da_edicao(self) -> None:
        with self._com_data("2026-09-25"):
            incluir(NOVO, self.caminho)
        with self._com_data("2026-10-01"):
            atualizar("Termo de Teste", {**NOVO, "definicao": "Mudou. Sim."}, self.caminho)
        self.assertEqual(carregar(self.caminho)[-1].atualizado_em, "2026-10-01")

    def test_renomeio_data_tambem_quem_teve_a_referencia_ajustada(self) -> None:
        with self._com_data("2026-09-25"):
            incluir({**NOVO, "ver_tambem": ["Empenho"]}, self.caminho)
        original = next(t for t in GLOSSARIO if t.termo == "Empenho")
        with self._com_data("2026-10-01"):
            atualizar(
                "Empenho",
                {"termo": "Empenho X", "definicao": original.definicao, "fonte": original.fonte, "tema": original.tema},
                self.caminho,
            )
        termos = {t.termo: t for t in carregar(self.caminho)}
        self.assertEqual(termos["Termo de Teste"].atualizado_em, "2026-10-01")
        self.assertEqual(termos["Empenho X"].atualizado_em, "2026-10-01")

    def test_cadastro_antigo_sem_o_campo_continua_legivel(self) -> None:
        with self._com_data("2026-09-25"):
            incluir(NOVO, self.caminho)
        carga = json.loads(self.caminho.read_text(encoding="utf-8"))
        for item in carga["termos"]:
            item.pop("atualizado_em")
        self.caminho.write_text(json.dumps(carga), encoding="utf-8")
        self.assertTrue(all(t.atualizado_em is None for t in carregar(self.caminho)))

    def test_data_invalida_no_arquivo_e_recusada(self) -> None:
        carga = json.loads(exportar(self.caminho))
        carga["termos"][0]["atualizado_em"] = "25/09/2026"
        with self.assertRaises(ErroGlossario):
            analisar_importacao(json.dumps(carga), self.caminho)

    def test_data_nao_conta_para_decidir_se_verbetes_sao_identicos(self) -> None:
        with self._com_data("2026-09-25"):
            incluir(NOVO, self.caminho)
        with self._com_data("2026-10-01"):
            plano = analisar_importacao(exportar(self.caminho), self.caminho)
        self.assertEqual(plano.conflitos, ())
        outro = Path(self._tmp.name) / "outro.json"
        with self._com_data("2027-01-01"):
            incluir(NOVO, outro)
        self.assertEqual(analisar_importacao(exportar(outro), self.caminho).conflitos, ())


class PersistenciaTests(CadastroBase):
    def test_arquivo_gravado_e_json_valido_sem_temporarios(self) -> None:
        incluir(NOVO, self.caminho)
        carga = json.loads(self.caminho.read_text(encoding="utf-8"))
        self.assertEqual(len(carga["termos"]), len(GLOSSARIO) + 1)
        self.assertEqual([p.name for p in self.caminho.parent.iterdir()], ["cadastro.json"])


class PaginaCadastroTests(CadastroBase):
    def _abrir(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
        app.run()
        app.switch_page("app_pages/glossario.py")
        app.run(timeout=30)
        return app

    def test_pagina_reflete_termo_incluido_no_cadastro(self) -> None:
        with mock.patch.object(glossario_cadastro, "CAMINHO_PADRAO", self.caminho):
            incluir(NOVO)
            app = self._abrir()
            app.text_input[0].set_value("Termo de Teste").run(timeout=30)

        self.assertEqual(len(app.exception), 0)
        titulos = [m.value for m in app.markdown if m.value.startswith("####")]
        self.assertTrue(any("Termo de Teste" in t for t in titulos))

    def test_importacao_pela_pagina_acrescenta_verbete_novo(self) -> None:
        origem = Path(self._tmp.name) / "origem.json"
        incluir(NOVO, origem)
        conteudo = origem.read_bytes()
        with mock.patch.object(glossario_cadastro, "CAMINHO_PADRAO", self.caminho):
            plano = glossario_cadastro.analisar_importacao(conteudo)
            self.assertEqual(len(plano.novos), 1)
            glossario_cadastro.aplicar_importacao(conteudo, False)
            app = self._abrir()

        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.metric[0].value, str(len(GLOSSARIO) + 1))

    def test_cadastro_corrompido_mostra_erro_sem_quebrar(self) -> None:
        self.caminho.parent.mkdir(parents=True)
        self.caminho.write_text("nao e json", encoding="utf-8")
        with mock.patch.object(glossario_cadastro, "CAMINHO_PADRAO", self.caminho):
            app = self._abrir()

        self.assertEqual(len(app.exception), 0)
        self.assertGreaterEqual(len(app.error), 1)


if __name__ == "__main__":
    unittest.main()
