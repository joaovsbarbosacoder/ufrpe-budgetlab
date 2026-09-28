"""Testes de src/prazos_sincronizacao.py — mapeamento prazo ↔ evento e conciliação com um
cliente falso em memória (nunca acessa a rede). Diretórios temporários a cada teste."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from src.google_agenda import MARCADOR, ErroGoogleAgenda
from src.prazos_orcamentarios import (
    atualizar,
    carregar_prazo,
    excluir,
    gravar_estado_sincronizacao,
    novo_prazo,
    salvar,
)
from src.prazos_sincronizacao import (
    ErroSincronizacao,
    campos_do_evento,
    carregar_ultimo_resumo,
    corpo_evento,
    salvar_resumo,
    sincronizacao_devida,
    sincronizar,
)


def _evento(**extras) -> dict:
    base = {
        "id": "ev1", "titulo": "Prazo A", "descricao": "", "data_inicio": date(2026, 12, 1),
        "hora_inicio": None, "data_fim": date(2026, 12, 2), "hora_fim": None,
        "cancelado": False, "atualizado_em": "2026-09-27T10:00:00Z", "prazo_id": None,
        "propriedades": {}, "organizador": "", "minha_resposta": None, "link": "",
    }
    base.update(extras)
    return base


class TestCorpoEvento(unittest.TestCase):
    def test_evento_de_dia_inteiro_com_marcadores(self):
        prazo = novo_prazo("Prestação de contas", date(2026, 12, 1), "Obs", "Fulano", 10,
                           "Calendário anual", "SIAFI", "Essencial")
        corpo = corpo_evento(prazo)
        self.assertEqual(corpo["summary"], "Prestação de contas")
        self.assertEqual(corpo["description"], "Obs")
        self.assertEqual(corpo["start"], {"date": "2026-12-01"})
        self.assertEqual(corpo["end"], {"date": "2026-12-02"})
        privadas = corpo["extendedProperties"]["private"]
        self.assertEqual(privadas["budgetlab"], "1")
        self.assertEqual(privadas[MARCADOR], prazo["id"])
        self.assertEqual(privadas["tipo"], "Calendário anual")
        self.assertEqual(privadas["categoria"], "SIAFI")
        self.assertEqual(privadas["prioridade"], "Essencial")
        self.assertEqual(privadas["responsavel"], "Fulano")
        self.assertEqual(privadas["dias_antecedencia"], "10")
        self.assertTrue(all(isinstance(v, str) for v in privadas.values()))

    def test_lembrete_em_minutos(self):
        corpo = corpo_evento(novo_prazo("A", date(2026, 12, 1), dias_antecedencia=10))
        self.assertEqual(corpo["reminders"], {"useDefault": False, "overrides": [{"method": "popup", "minutes": 14400}]})

    def test_lembrete_limitado_a_28_dias(self):
        corpo = corpo_evento(novo_prazo("A", date(2026, 12, 1), dias_antecedencia=60))
        self.assertEqual(corpo["reminders"]["overrides"][0]["minutes"], 28 * 1440)

    def test_concluido_prefixa_titulo(self):
        prazo = {**novo_prazo("A", date(2026, 12, 1)), "concluido": True}
        self.assertEqual(corpo_evento(prazo)["summary"], "✓ A")

    def test_prazo_legado_sem_campos_opcionais(self):
        prazo = novo_prazo("A", date(2026, 12, 1))
        for campo in ("dias_antecedencia", "tipo", "categoria", "prioridade"):
            prazo.pop(campo)
        corpo = corpo_evento(prazo)
        self.assertEqual(corpo["reminders"]["overrides"][0]["minutes"], 28 * 1440)  # padrão 30 → 28
        self.assertEqual(corpo["extendedProperties"]["private"]["tipo"], "Solicitação")


class TestCamposDoEvento(unittest.TestCase):
    def test_mapeia_titulo_data_descricao(self):
        self.assertEqual(
            campos_do_evento(_evento(titulo="Novo", descricao="D", data_inicio=date(2026, 12, 3))),
            {"titulo": "Novo", "data_prazo": "2026-12-03", "descricao": "D"},
        )

    def test_prefixo_de_concluido_e_removido(self):
        self.assertEqual(campos_do_evento(_evento(titulo="✓ Prazo A"))["titulo"], "Prazo A")
        self.assertEqual(campos_do_evento(_evento(titulo="✓Prazo A"))["titulo"], "Prazo A")

    def test_prefixo_nao_devolve_concluido(self):
        self.assertNotIn("concluido", campos_do_evento(_evento(titulo="✓ Prazo A")))

    def test_evento_com_horario_usa_data_de_inicio(self):
        campos = campos_do_evento(_evento(data_inicio=date(2026, 12, 4), hora_inicio=time(9, 0)))
        self.assertEqual(campos["data_prazo"], "2026-12-04")

    def test_titulo_vazio_e_rejeitado(self):
        for titulo in ("", "   ", "✓ "):
            with self.assertRaises(ErroSincronizacao):
                campos_do_evento(_evento(titulo=titulo))

    def test_evento_sem_data_e_rejeitado(self):
        with self.assertRaises(ErroSincronizacao):
            campos_do_evento(_evento(data_inicio=None))


class TestSincronizacaoDevida(unittest.TestCase):
    agora = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)

    def test_nunca_sincronizou(self):
        self.assertTrue(sincronizacao_devida(None, self.agora))

    def test_dentro_do_intervalo(self):
        self.assertFalse(sincronizacao_devida(self.agora - timedelta(minutes=4), self.agora))

    def test_intervalo_vencido(self):
        self.assertTrue(sincronizacao_devida(self.agora - timedelta(minutes=5), self.agora))


class ClienteFalso:
    """Calendário em memória com a interface de ClienteGoogleAgenda. `updated` avança a cada
    escrita; `falhar_em` faz uma operação específica lançar ErroGoogleAgenda."""

    def __init__(self):
        self.eventos: dict[str, dict] = {}
        self._seq = 0
        # relógio no passado: toda alteração local real (agora) é posterior a ele
        self._relogio = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.falhar_listagem = False
        self.falhar_em: set[tuple[str, str]] = set()  # (operação, prazo_id)
        self.excluidos: list[str] = []
        self.corpos_atualizados: list[dict] = []
        self.ao_criar = None  # simula algo acontecendo durante a chamada (ex.: edição em outra aba)

    def _carimbo(self) -> str:
        self._relogio += timedelta(seconds=1)
        return self._relogio.isoformat().replace("+00:00", "Z")

    def _normalizar(self, event_id: str, corpo: dict, cancelado=False) -> dict:
        privadas = corpo["extendedProperties"]["private"]
        return _evento(
            id=event_id, titulo=corpo["summary"], descricao=corpo["description"],
            data_inicio=date.fromisoformat(corpo["start"]["date"]),
            cancelado=cancelado, atualizado_em=self._carimbo(),
            prazo_id=privadas[MARCADOR], propriedades=dict(privadas),
        ) | {"_corpo": corpo}

    def listar_eventos_de_prazos(self):
        if self.falhar_listagem:
            raise ErroGoogleAgenda("falha simulada")
        return [dict(e) for e in self.eventos.values()]

    def criar_evento(self, corpo):
        if ("criar", corpo["extendedProperties"]["private"][MARCADOR]) in self.falhar_em:
            raise ErroGoogleAgenda("falha simulada")
        if self.ao_criar is not None:
            self.ao_criar()
        self._seq += 1
        event_id = f"ev{self._seq}"
        self.eventos[event_id] = self._normalizar(event_id, corpo)
        return dict(self.eventos[event_id])

    def atualizar_evento(self, event_id, corpo):
        self.corpos_atualizados.append(corpo)
        corpo_total = {**self.eventos[event_id]["_corpo"], **corpo}
        self.eventos[event_id] = self._normalizar(event_id, corpo_total)
        return dict(self.eventos[event_id])

    def excluir_evento(self, event_id):
        self.excluidos.append(event_id)
        self.eventos.pop(event_id, None)

    # --- ações "do usuário no Google" ---
    def editar_no_google(self, event_id, **campos):
        evento = self.eventos[event_id]
        evento.update(campos)
        evento["atualizado_em"] = self._carimbo()

    def cancelar_no_google(self, event_id):
        self.eventos[event_id].update(cancelado=True, atualizado_em=self._carimbo())


class TestSincronizar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.diretorio = Path(self._tmp.name)
        self.cliente = ClienteFalso()

    def tearDown(self):
        self._tmp.cleanup()

    def _prazo(self, titulo="Prazo A", **extras) -> dict:
        prazo = {**novo_prazo(titulo, date(2026, 12, 1)), **extras}
        salvar(prazo, self.diretorio)
        return prazo

    def _sync(self):
        return sincronizar(self.cliente, self.diretorio)

    def _recarregar(self, prazo) -> dict:
        return carregar_prazo(prazo["id"], self.diretorio)

    def test_prazo_novo_cria_evento_e_grava_estado(self):
        prazo = self._prazo()
        resumo = self._sync()
        self.assertEqual(resumo.criados, ["Prazo A"])
        gravado = self._recarregar(prazo)
        evento = self.cliente.eventos[gravado["google_event_id"]]
        self.assertEqual(evento["prazo_id"], prazo["id"])
        self.assertEqual(gravado["sincronizado_em"], gravado["atualizado_em"])
        self.assertEqual(gravado["google_atualizado_em"], evento["atualizado_em"])
        self.assertEqual(gravado["atualizado_em"], prazo["atualizado_em"])  # não virou "alteração local"

    def test_segunda_sincronizacao_sem_mudancas_nao_faz_nada(self):
        self._prazo()
        self._sync()
        resumo = self._sync()
        self.assertEqual(resumo.total_alteracoes(), 0)
        self.assertEqual(len(self.cliente.eventos), 1)

    def test_alteracao_local_atualiza_evento(self):
        prazo = self._prazo()
        self._sync()
        atualizar({**self._recarregar(prazo), "titulo": "Prazo B"}, self.diretorio)
        resumo = self._sync()
        self.assertEqual(resumo.atualizados_no_google, ["Prazo B"])
        evento = next(iter(self.cliente.eventos.values()))
        self.assertEqual(evento["titulo"], "Prazo B")
        self.assertEqual(self._sync().total_alteracoes(), 0)

    def test_alteracao_no_google_atualiza_prazo(self):
        prazo = self._prazo()
        self._sync()
        event_id = self._recarregar(prazo)["google_event_id"]
        self.cliente.editar_no_google(event_id, titulo="Renomeado", descricao="Nova",
                                      data_inicio=date(2026, 12, 10))
        resumo = self._sync()
        self.assertEqual(resumo.atualizados_no_budgetlab, ["Renomeado"])
        gravado = self._recarregar(prazo)
        self.assertEqual((gravado["titulo"], gravado["descricao"], gravado["data_prazo"]),
                         ("Renomeado", "Nova", "2026-12-10"))
        self.assertEqual(gravado["tipo"], prazo["tipo"])
        self.assertEqual(self._sync().total_alteracoes(), 0)

    def test_conflito_vence_o_mais_recente_e_fica_registrado(self):
        prazo = self._prazo()
        self._sync()
        event_id = self._recarregar(prazo)["google_event_id"]
        self.cliente.editar_no_google(event_id, titulo="Do Google")  # relógio falso: 01/01/2000
        atualizar({**self._recarregar(prazo), "titulo": "Do BudgetLab"}, self.diretorio)  # agora real, posterior
        resumo = self._sync()
        self.assertEqual(len(resumo.conflitos), 1)
        conflito = resumo.conflitos[0]
        self.assertEqual(conflito["vencedor"], "BudgetLab")
        self.assertEqual(conflito["valor_google"]["titulo"], "Do Google")
        self.assertEqual(conflito["valor_budgetlab"]["titulo"], "Do BudgetLab")
        self.assertEqual(self.cliente.eventos[event_id]["titulo"], "Do BudgetLab")

    def test_conflito_vencido_pelo_google(self):
        prazo = self._prazo()
        self._sync()
        gravado = self._recarregar(prazo)
        # alteração local antiga (carimbo manual) x alteração no Google posterior
        gravado.update(titulo="Do BudgetLab", atualizado_em="1999-01-01T00:00:00+00:00")
        gravar_estado_sincronizacao(gravado, self.diretorio)
        self.cliente.editar_no_google(gravado["google_event_id"], titulo="Do Google")
        resumo = self._sync()
        self.assertEqual(resumo.conflitos[0]["vencedor"], "Google")
        self.assertEqual(self._recarregar(prazo)["titulo"], "Do Google")

    def test_evento_excluido_no_google_conclui_o_prazo(self):
        prazo = self._prazo()
        self._sync()
        self.cliente.cancelar_no_google(self._recarregar(prazo)["google_event_id"])
        resumo = self._sync()
        self.assertEqual(resumo.concluidos_por_exclusao, ["Prazo A"])
        gravado = self._recarregar(prazo)
        self.assertTrue(gravado["concluido"])
        self.assertTrue(gravado["removido_no_google"])
        self.assertIsNone(gravado["google_event_id"])
        # não recria na próxima sincronização
        self.assertEqual(self._sync().total_alteracoes(), 0)

    def test_evento_ausente_da_listagem_conclui_o_prazo(self):
        prazo = self._prazo()
        self._sync()
        self.cliente.eventos.clear()
        self._sync()
        self.assertTrue(self._recarregar(prazo)["concluido"])

    def test_reabrir_prazo_removido_no_google_recria_evento(self):
        prazo = self._prazo()
        self._sync()
        self.cliente.cancelar_no_google(self._recarregar(prazo)["google_event_id"])
        self._sync()
        atualizar({**self._recarregar(prazo), "concluido": False}, self.diretorio)
        resumo = self._sync()
        self.assertEqual(resumo.criados, ["Prazo A"])
        self.assertIsNotNone(self._recarregar(prazo)["google_event_id"])

    def test_concluir_localmente_prefixa_evento(self):
        prazo = self._prazo()
        self._sync()
        atualizar({**self._recarregar(prazo), "concluido": True}, self.diretorio)
        self._sync()
        evento = self.cliente.eventos[self._recarregar(prazo)["google_event_id"]]
        self.assertEqual(evento["titulo"], "✓ Prazo A")

    def test_prefixo_editado_no_google_nao_altera_concluido(self):
        prazo = self._prazo()
        self._sync()
        self.cliente.editar_no_google(self._recarregar(prazo)["google_event_id"], titulo="✓ Prazo A")
        self._sync()
        gravado = self._recarregar(prazo)
        self.assertFalse(gravado["concluido"])
        self.assertEqual(gravado["titulo"], "Prazo A")

    def test_prazo_excluido_localmente_exclui_evento(self):
        prazo = self._prazo()
        self._sync()
        event_id = self._recarregar(prazo)["google_event_id"]
        excluir(prazo["id"], self.diretorio)
        resumo = self._sync()
        self.assertEqual(self.cliente.excluidos, [event_id])
        self.assertEqual(resumo.eventos_excluidos, ["Prazo A"])

    def test_falha_na_listagem_nao_altera_nada(self):
        prazo = self._prazo()
        self._sync()
        antes = self._recarregar(prazo)
        self.cliente.falhar_listagem = True
        with self.assertRaises(ErroGoogleAgenda):
            self._sync()
        self.assertEqual(self._recarregar(prazo), antes)

    def test_erro_em_um_item_nao_interrompe_os_demais(self):
        a = self._prazo("Prazo A")
        b = self._prazo("Prazo B")
        self.cliente.falhar_em.add(("criar", a["id"]))
        resumo = self._sync()
        self.assertEqual(resumo.criados, ["Prazo B"])
        self.assertEqual(len(resumo.erros), 1)
        self.assertIn("Prazo A", resumo.erros[0])
        self.assertIsNone(self._recarregar(a)["google_event_id"])
        self.assertIsNotNone(self._recarregar(b)["google_event_id"])

    def test_titulo_vazio_no_google_nao_e_aplicado(self):
        prazo = self._prazo()
        self._sync()
        self.cliente.editar_no_google(self._recarregar(prazo)["google_event_id"], titulo="  ")
        resumo = self._sync()
        self.assertEqual(len(resumo.erros), 1)
        self.assertEqual(self._recarregar(prazo)["titulo"], "Prazo A")

    def test_adota_evento_existente_sem_duplicar(self):
        prazo = self._prazo()
        self._sync()
        # simula queda depois de criar o evento e antes de gravar o estado
        gravado = self._recarregar(prazo)
        gravado.update(google_event_id=None, sincronizado_em=None, google_atualizado_em=None)
        gravar_estado_sincronizacao(gravado, self.diretorio)
        self._sync()
        self.assertEqual(len(self.cliente.eventos), 1)
        self.assertIsNotNone(self._recarregar(prazo)["google_event_id"])

    def test_exclui_evento_duplicado_do_mesmo_prazo(self):
        prazo = self._prazo()
        self._sync()
        vinculado = self._recarregar(prazo)["google_event_id"]
        duplicado = self.cliente.criar_evento(corpo_evento(self._recarregar(prazo)))["id"]
        resumo = self._sync()
        self.assertIn(vinculado, self.cliente.eventos)
        self.assertNotIn(duplicado, self.cliente.eventos)
        self.assertEqual(resumo.eventos_excluidos, ["Prazo A (duplicado)"])

    def test_edicao_local_durante_a_sincronizacao_nao_e_sobrescrita(self):
        prazo = self._prazo()

        def editar_em_outra_aba():
            atualizar({**self._recarregar(prazo), "titulo": "Editado em outra aba"}, self.diretorio)

        self.cliente.ao_criar = editar_em_outra_aba
        self._sync()
        self.cliente.ao_criar = None
        self.assertEqual(self._recarregar(prazo)["titulo"], "Editado em outra aba")
        self._sync()  # próxima sincronização adota o evento criado e envia a edição
        self.assertEqual(len(self.cliente.eventos), 1)
        self.assertEqual(next(iter(self.cliente.eventos.values()))["titulo"], "Editado em outra aba")
        self.assertEqual(self._recarregar(prazo)["titulo"], "Editado em outra aba")

    def test_pasta_de_prazos_ausente_cancela_sem_excluir_eventos(self):
        self._prazo("Prazo A")
        self._prazo("Prazo B")
        self._sync()
        with self.assertRaises(ErroSincronizacao):
            sincronizar(self.cliente, self.diretorio / "nao_existe")
        self.assertEqual(len(self.cliente.eventos), 2)
        self.assertEqual(self.cliente.excluidos, [])

    def test_pasta_vazia_nao_exclui_todos_os_eventos(self):
        a = self._prazo("Prazo A")
        b = self._prazo("Prazo B")
        self._sync()
        excluir(a["id"], self.diretorio)
        excluir(b["id"], self.diretorio)
        resumo = self._sync()
        self.assertEqual(len(self.cliente.eventos), 2)
        self.assertEqual(resumo.eventos_excluidos, [])
        self.assertEqual(len(resumo.erros), 1)

    def test_conflito_vencido_pelo_google_ainda_envia_campos_locais(self):
        prazo = self._prazo()
        self._sync()
        gravado = self._recarregar(prazo)
        gravado.update(concluido=True, dias_antecedencia=5, atualizado_em="1999-01-01T00:00:00+00:00")
        gravar_estado_sincronizacao(gravado, self.diretorio)
        self.cliente.editar_no_google(gravado["google_event_id"], titulo="Do Google")
        self._sync()
        evento = self.cliente.eventos[gravado["google_event_id"]]
        self.assertEqual(evento["titulo"], "✓ Do Google")
        self.assertEqual(evento["propriedades"]["dias_antecedencia"], "5")
        local = self._recarregar(prazo)
        self.assertTrue(local["concluido"])
        self.assertEqual(local["titulo"], "Do Google")
        self.assertEqual(self._sync().total_alteracoes(), 0)

    def test_atualizacao_limpa_horario_do_evento(self):
        # o patch mescla objetos: sem dateTime/timeZone nulos, um evento que o usuário
        # transformou em evento com horário ficaria com date + dateTime (HTTP 400)
        prazo = self._prazo()
        self._sync()
        atualizar({**self._recarregar(prazo), "titulo": "Prazo B"}, self.diretorio)
        self._sync()
        corpo = self.cliente.corpos_atualizados[-1]
        for parte in ("start", "end"):
            self.assertIn("date", corpo[parte])
            self.assertIsNone(corpo[parte]["dateTime"])
            self.assertIsNone(corpo[parte]["timeZone"])

    def test_registro_malformado_nao_interrompe_os_demais(self):
        import json as _json
        ruim = {**novo_prazo("Ruim", date(2026, 12, 1)), "data_prazo": "31/12/2026"}
        (self.diretorio / f"{ruim['id']}.json").write_text(_json.dumps(ruim), encoding="utf-8")
        self._prazo("Bom")
        resumo = self._sync()
        self.assertEqual(resumo.criados, ["Bom"])
        self.assertEqual(len(resumo.erros), 1)
        self.assertIn("Ruim", resumo.erros[0])

    def test_antecedencia_nula_usa_padrao(self):
        self._prazo(dias_antecedencia=None)
        resumo = self._sync()
        self.assertEqual(resumo.erros, [])
        corpo = next(iter(self.cliente.eventos.values()))["_corpo"]
        self.assertEqual(corpo["reminders"]["overrides"][0]["minutes"], 28 * 1440)

    def test_prazo_legado_sem_campos_de_sincronizacao(self):
        prazo = novo_prazo("Legado", date(2026, 12, 1))
        for campo in ("google_event_id", "sincronizado_em", "google_atualizado_em", "removido_no_google"):
            prazo.pop(campo)
        salvar(prazo, self.diretorio)
        resumo = self._sync()
        self.assertEqual(resumo.criados, ["Legado"])


class TestResumoPersistido(unittest.TestCase):
    def test_salvar_e_carregar_ultimo_resumo(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            self.assertIsNone(carregar_ultimo_resumo(diretorio))
            dados = tempfile.TemporaryDirectory()
            try:
                prazos = Path(dados.name)
                salvar(novo_prazo("A", date(2026, 12, 1)), prazos)
                resumo = sincronizar(ClienteFalso(), prazos)
            finally:
                dados.cleanup()
            salvar_resumo(resumo, diretorio)
            carregado = carregar_ultimo_resumo(diretorio)
            self.assertEqual(carregado["criados"], ["A"])
            self.assertEqual(carregado["executado_em"], resumo.executado_em)

    def test_historico_guarda_conflitos_de_sincronizacoes_anteriores(self):
        from src.prazos_sincronizacao import ResumoSincronizacao, carregar_historico
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            com_conflito = ResumoSincronizacao(executado_em="2026-09-27T12:00:00+00:00", conflitos=[{
                "titulo": "A", "vencedor": "Google",
                "valor_budgetlab": {"titulo": "Descartado"}, "valor_google": {"titulo": "A"},
            }])
            salvar_resumo(com_conflito, diretorio)
            salvar_resumo(ResumoSincronizacao(executado_em="2026-09-27T12:05:00+00:00"), diretorio)
            self.assertEqual(carregar_ultimo_resumo(diretorio)["conflitos"], [])
            historico = carregar_historico(diretorio)
            self.assertEqual(len(historico), 1)  # sincronização sem nada a registrar não entra
            self.assertEqual(historico[0]["conflitos"][0]["valor_budgetlab"]["titulo"], "Descartado")


if __name__ == "__main__":
    unittest.main()
