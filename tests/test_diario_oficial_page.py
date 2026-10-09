"""Smoke test da página Diário Oficial (DOU). Nunca acessa a rede nem `data/raw/dou/` real:
`DIRETORIO_PADRAO` aponta para uma pasta temporária com a fixture sintética
(`tests/fixtures/dou_inlabs_sintetico.xml`) e as credenciais são simuladas."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from src import dou_inlabs
from tests._apptest import TEMPO_LIMITE_APPTEST

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "dou_inlabs_sintetico.xml"
PAGINA = "app_pages/diario_oficial.py"
SENHA = "segredo-123"


def _preparar_dia(raiz: Path, dia: date = date(2026, 10, 8)) -> None:
    pasta = raiz / dia.isoformat()
    pasta.mkdir(parents=True)
    nome = f"{dia.isoformat()}-DO3.zip"
    with zipfile.ZipFile(pasta / nome, "w") as arquivo:
        arquivo.writestr("sintetico.xml", FIXTURE.read_bytes())
    sha = hashlib.sha256((pasta / nome).read_bytes()).hexdigest()
    (pasta / dou_inlabs.ARQUIVO_MANIFESTO).write_text(json.dumps({
        "data_publicacao": dia.isoformat(),
        "verificado_em": "2026-10-08T09:30:00",
        "arquivos": [{"arquivo": nome, "secao": "DO3", "sha256": sha, "bytes": 1, "baixado_em": "2026-10-08T09:30:00"}],
    }), encoding="utf-8")


class DiarioOficialPageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name) / "raw_dou"
        self.raiz.mkdir()
        self.pasta_termos = Path(self._tmp.name) / "dou"
        self.addCleanup(self._tmp.cleanup)

    def _abrir(self, credenciais: bool = True) -> AppTest:
        ambiente = {dou_inlabs.VARIAVEL_EMAIL: "a@b.br", dou_inlabs.VARIAVEL_SENHA: SENHA} if credenciais else {}
        patches = [
            mock.patch.object(dou_inlabs, "DIRETORIO_PADRAO", self.raiz),
            mock.patch.object(dou_inlabs, "DIRETORIO_TERMOS", self.pasta_termos),
            mock.patch.dict("os.environ", ambiente, clear=False),
        ]
        if not credenciais:
            patches.append(mock.patch.object(
                dou_inlabs, "credenciais_do_ambiente", side_effect=dou_inlabs.ErroInlabs("ausentes"),
            ))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=TEMPO_LIMITE_APPTEST)
        app.run()
        app.switch_page(PAGINA)
        app.run()
        return app

    def _nova_sessao(self) -> AppTest:
        """Outra sessão do navegador (mesmos patches): lê os termos de novo do disco."""
        app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=TEMPO_LIMITE_APPTEST)
        app.run()
        app.switch_page(PAGINA)
        app.run()
        return app

    def _botao(self, app: AppTest):
        return next(b for b in app.button if b.label == "Baixar atualizações do DOU")

    def _textos(self, app: AppTest) -> str:
        partes = [m.value for m in app.markdown] + [s.value for s in app.subheader]
        partes += [e.value for e in (*app.warning, *app.error, *app.success, *app.info)]
        return "\n".join(str(p) for p in partes)

    def test_sem_credenciais_desabilita_botao_e_orienta(self):
        app = self._abrir(credenciais=False)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(self._botao(app).disabled)
        self.assertIn("docs/dou_inlabs.md", self._textos(app))
        self.assertIn("Nenhum dia baixado ainda.", self._textos(app))

    def test_lista_materias_baixadas_com_termos_padrao(self):
        _preparar_dia(self.raiz)
        app = self._abrir()
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(self._botao(app).disabled)
        self.assertIn("2 matéria(s) encontrada(s)", self._textos(app))
        tabela = app.dataframe[0].value
        self.assertEqual(set(tabela["Identificação"]), {
            "EXTRATO DE CONTRATO Nº 12/2026 - UASG 153165",
            "PORTARIA SOF Nº 99, DE 7 DE OUTUBRO DE 2026",
        })
        self.assertNotIn(SENHA, self._textos(app))

    def test_termo_novo_alcanca_dias_ja_baixados(self):
        _preparar_dia(self.raiz)
        app = self._abrir()
        app.multiselect(key="dou_termos").set_value(["licitação"]).run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("1 matéria(s) encontrada(s)", self._textos(app))
        self.assertEqual(list(app.dataframe[0].value["Termos"]), ["licitação"])

    def test_filtro_de_secao(self):
        _preparar_dia(self.raiz)
        app = self._abrir()
        app.multiselect(key="dou_secoes").set_value(["DO1"]).run()
        self.assertIn("1 matéria(s) encontrada(s)", self._textos(app))

    def test_botao_baixa_e_mostra_resumo(self):
        resumo = dou_inlabs.ResumoAtualizacao(
            dias_consultados=[date(2026, 10, 7), date(2026, 10, 8)],
            dias_sem_publicacao=[date(2026, 10, 7)],
            arquivos=[Path("x.zip")],
        )
        app = self._abrir()
        with mock.patch.object(dou_inlabs.ClienteInlabs, "autenticar") as autenticar, \
             mock.patch.object(dou_inlabs, "atualizar", return_value=resumo) as atualizar:
            self._botao(app).click().run()
        self.assertEqual(len(app.exception), 0)
        autenticar.assert_called_once_with("a@b.br", SENHA)
        self.assertEqual(atualizar.call_args.args[2], self.raiz)
        texto = self._textos(app)
        self.assertIn("2 dia(s) consultado(s), 1 arquivo(s) baixado(s)", texto)
        self.assertIn("sem publicação em 07/10", texto)
        self.assertNotIn(SENHA, texto)

    def test_login_recusado_mostra_erro_sem_quebrar(self):
        app = self._abrir()
        with mock.patch.object(dou_inlabs.ClienteInlabs, "autenticar",
                               side_effect=dou_inlabs.ErroInlabs("Login no INLABS recusado: confira e-mail e senha.")), \
             mock.patch.object(dou_inlabs, "atualizar") as atualizar:
            self._botao(app).click().run()
        self.assertEqual(len(app.exception), 0)
        atualizar.assert_not_called()
        self.assertIn("Login no INLABS recusado", self._textos(app))


    def test_refinar_restringe_a_busca(self):
        _preparar_dia(self.raiz)
        app = self._abrir()
        app.multiselect(key="dou_refinar").set_value(["limpeza"]).run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("1 matéria(s) encontrada(s)", self._textos(app))
        self.assertIn("limpeza", app.dataframe[0].value["Termos"].iloc[0])

    def test_termos_salvos_valem_na_proxima_sessao(self):
        _preparar_dia(self.raiz)
        app = self._abrir()
        app.multiselect(key="dou_termos").set_value(["UFRPE", "limpeza"]).run()
        app.multiselect(key="dou_refinar").set_value(["contínuos"]).run()
        salvo = json.loads((self.pasta_termos / dou_inlabs.ARQUIVO_TERMOS).read_text(encoding="utf-8"))
        self.assertEqual((salvo["termos"], salvo["refinar"]), (["UFRPE", "limpeza"], ["contínuos"]))

        outra = self._nova_sessao()
        self.assertEqual(len(outra.exception), 0)
        self.assertEqual(outra.multiselect(key="dou_termos").value, ["UFRPE", "limpeza"])
        self.assertEqual(outra.multiselect(key="dou_refinar").value, ["contínuos"])
        self.assertIn("1 matéria(s) encontrada(s)", self._textos(outra))

    def test_restaurar_termos_padrao(self):
        _preparar_dia(self.raiz)
        dou_inlabs.salvar_termos(["licitação"], ["pregão"], self.pasta_termos)
        app = self._abrir()
        self.assertEqual(app.multiselect(key="dou_termos").value, ["licitação"])
        next(b for b in app.button if b.label == "Restaurar termos padrão").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.multiselect(key="dou_termos").value, list(dou_inlabs.TERMOS_UFRPE_PADRAO))
        self.assertEqual(app.multiselect(key="dou_refinar").value, [])
        self.assertEqual(dou_inlabs.carregar_termos(self.pasta_termos).termos, dou_inlabs.TERMOS_UFRPE_PADRAO)
        self.assertIn("2 matéria(s) encontrada(s)", self._textos(app))

    def test_arquivo_de_termos_invalido_avisa_sem_quebrar(self):
        _preparar_dia(self.raiz)
        self.pasta_termos.mkdir()
        (self.pasta_termos / dou_inlabs.ARQUIVO_TERMOS).write_text("{quebrado", encoding="utf-8")
        app = self._abrir()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("usando os padrões", self._textos(app))
        self.assertIn("2 matéria(s) encontrada(s)", self._textos(app))


if __name__ == "__main__":
    unittest.main()
