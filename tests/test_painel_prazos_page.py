"""Smoke test da página Gerenciamento de Prazos — bloco Google Agenda por situação de
conexão. A situação é simulada com `mock.patch` (nunca lê `data/google_agenda/` real)."""

import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PainelPrazosGoogleAgendaTests(unittest.TestCase):
    def _abrir(self, situacao: str) -> AppTest:
        with mock.patch("src.google_agenda.situacao_conexao", return_value=situacao):
            app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
            app.run(timeout=60)
            app.switch_page("app_pages/painel_prazos.py")
            app.run(timeout=60)
        return app

    def test_sem_credenciais_mostra_instrucao(self):
        app = self._abrir("sem_credenciais")
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("docs/google_agenda.md" in m.value for m in app.markdown))

    def test_desconectado_mostra_botao_conectar(self):
        app = self._abrir("desconectado")
        self.assertEqual(len(app.exception), 0)
        self.assertIn("Conectar ao Google Agenda", [b.label for b in app.button])

    def test_conectado_sincroniza_ao_abrir_e_mostra_botao(self):
        from src.prazos_sincronizacao import ResumoSincronizacao
        resumo = ResumoSincronizacao(executado_em="2026-09-27T12:00:00+00:00")
        with mock.patch("src.google_agenda.situacao_conexao", return_value="conectado"), \
             mock.patch("src.google_agenda.cliente", return_value=mock.Mock(listar_eventos=mock.Mock(return_value=[]))), \
             mock.patch("src.prazos_sincronizacao.sincronizar", return_value=resumo) as sync, \
             mock.patch("src.prazos_sincronizacao.salvar_resumo"), \
             mock.patch("src.prazos_sincronizacao.carregar_ultimo_resumo", return_value=None):
            app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
            app.run(timeout=60)
            app.switch_page("app_pages/painel_prazos.py")
            app.run(timeout=60)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(sync.call_count, 1)
        self.assertIn("Sincronizar agora", [b.label for b in app.button])

    def test_falha_na_sincronizacao_nao_repete_a_cada_interacao(self):
        from src.google_agenda import ErroGoogleAgenda
        with mock.patch("src.google_agenda.situacao_conexao", return_value="conectado"), \
             mock.patch("src.google_agenda.cliente", return_value=mock.Mock(listar_eventos=mock.Mock(return_value=[]))), \
             mock.patch("src.prazos_sincronizacao.sincronizar", side_effect=ErroGoogleAgenda("sem rede")) as sync, \
             mock.patch("src.prazos_sincronizacao.carregar_ultimo_resumo", return_value=None):
            app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
            app.run(timeout=60)
            app.switch_page("app_pages/painel_prazos.py")
            app.run(timeout=60)
            app.run(timeout=60)  # nova interação dentro dos 5 minutos
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(sync.call_count, 1)
        self.assertTrue(any("sem rede" in e.value for e in app.error))

    def test_titulo_de_reuniao_e_exibido_como_texto(self):
        # títulos de reunião são escritos por terceiros: nem markdown nem HTML podem passar
        import streamlit as st
        from datetime import date, time
        from src.prazos_sincronizacao import ResumoSincronizacao
        evento = {
            "id": "r1", "titulo": "**Reunião** <img src=x onerror=alert(1)>", "descricao": "",
            "data_inicio": date(2026, 10, 1), "hora_inicio": time(15, 0), "data_fim": date(2026, 10, 1),
            "hora_fim": time(16, 0), "cancelado": False, "atualizado_em": "", "prazo_id": None,
            "propriedades": {}, "organizador": "<b>org</b>@ufrpe.br", "minha_resposta": "needsAction", "link": "",
        }
        st.cache_data.clear()
        resumo = ResumoSincronizacao(executado_em="2026-09-27T12:00:00+00:00")
        with mock.patch("src.google_agenda.situacao_conexao", return_value="conectado"), \
             mock.patch("src.google_agenda.cliente", return_value=mock.Mock(listar_eventos=mock.Mock(return_value=[evento]))), \
             mock.patch("src.prazos_sincronizacao.sincronizar", return_value=resumo), \
             mock.patch("src.prazos_sincronizacao.salvar_resumo"), \
             mock.patch("src.prazos_sincronizacao.carregar_ultimo_resumo", return_value=None):
            app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
            app.run(timeout=60)
            app.switch_page("app_pages/painel_prazos.py")
            app.run(timeout=60)
        st.cache_data.clear()
        self.assertEqual(len(app.exception), 0)
        linha = next(m.value for m in app.markdown if "Reunião" in m.value)
        self.assertNotIn("<img", linha)
        self.assertIn("&lt;img src=x onerror=alert", linha)
        self.assertNotIn("<b>org</b>", linha)
        self.assertIn("\\*\\*Reunião\\*\\*", linha)

    def test_card_de_prazo_exibe_texto_sem_interpretar_html(self):
        # "Transformar em prazo" copia título/descrição de reuniões de terceiros para o prazo
        from datetime import date
        from src.prazos_orcamentarios import novo_prazo
        prazo = novo_prazo("<img src=x onerror=alert(1)>", date(2026, 12, 1),
                           descricao="<script>x</script>", responsavel="<b>eu</b>", categoria="<i>c</i>")
        with mock.patch("src.google_agenda.situacao_conexao", return_value="sem_credenciais"), \
             mock.patch("src.prazos_orcamentarios.carregar_prazos", return_value=[prazo]):
            app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
            app.run(timeout=60)
            app.switch_page("app_pages/painel_prazos.py")
            app.run(timeout=60)
        self.assertEqual(len(app.exception), 0)
        conteudo = "\n".join(m.value for m in app.markdown)
        for bruto in ("<img src=x", "<script>", "<b>eu</b>", "<i>c</i>"):
            self.assertNotIn(bruto, conteudo)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", conteudo)

    def test_desconectar_sem_revogacao_confirmada_avisa(self):
        from src.prazos_sincronizacao import ResumoSincronizacao
        resumo = ResumoSincronizacao(executado_em="2026-09-27T12:00:00+00:00")
        situacao = mock.Mock(return_value="conectado")

        def desconectar_sem_revogar(*_args, **_kwargs):
            situacao.return_value = "desconectado"
            return False

        with mock.patch("src.google_agenda.situacao_conexao", situacao), \
             mock.patch("src.google_agenda.cliente", return_value=mock.Mock(listar_eventos=mock.Mock(return_value=[]))), \
             mock.patch("src.google_agenda.desconectar", side_effect=desconectar_sem_revogar) as desconectar, \
             mock.patch("src.prazos_sincronizacao.sincronizar", return_value=resumo), \
             mock.patch("src.prazos_sincronizacao.salvar_resumo"), \
             mock.patch("src.prazos_sincronizacao.carregar_ultimo_resumo", return_value=None):
            app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
            app.run(timeout=60)
            app.switch_page("app_pages/painel_prazos.py")
            app.run(timeout=60)
            next(b for b in app.button if b.label == "Desconectar").click().run(timeout=60)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(desconectar.call_count, 1)
        self.assertTrue(any("myaccount.google.com/permissions" in w.value for w in app.warning))

    def test_pasta_de_prazos_ausente_vira_aviso(self):
        from src.prazos_sincronizacao import ErroSincronizacao
        with mock.patch("src.google_agenda.situacao_conexao", return_value="conectado"), \
             mock.patch("src.google_agenda.cliente", return_value=mock.Mock(listar_eventos=mock.Mock(return_value=[]))), \
             mock.patch("src.prazos_sincronizacao.sincronizar", side_effect=ErroSincronizacao("pasta ausente")), \
             mock.patch("src.prazos_sincronizacao.carregar_ultimo_resumo", return_value=None):
            app = AppTest.from_file(str(PROJECT_ROOT / "app.py"))
            app.run(timeout=60)
            app.switch_page("app_pages/painel_prazos.py")
            app.run(timeout=60)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("pasta ausente" in e.value for e in app.error))


if __name__ == "__main__":
    unittest.main()
