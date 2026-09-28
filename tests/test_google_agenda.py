"""Testes de src/google_agenda.py — normalização de eventos da API e situação da conexão.
Nenhum teste acessa a rede nem usa credencial real; diretórios são temporários.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path
from unittest import mock

import httplib2
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError

from src.google_agenda import (
    ARQUIVO_CREDENCIAIS,
    ARQUIVO_TOKEN,
    MARCADOR,
    ClienteGoogleAgenda,
    ErroGoogleAgenda,
    cliente,
    conectar,
    desconectar,
    normalizar_evento,
    situacao_conexao,
)


def _bruto(**extras) -> dict:
    base = {
        "id": "ev1", "status": "confirmed", "summary": "Reunião PROPLAD",
        "description": "Pauta", "updated": "2026-09-20T12:00:00.000Z",
        "htmlLink": "https://calendar.google.com/ev1",
        "organizer": {"email": "chefe@ufrpe.br"},
        "start": {"dateTime": "2026-10-01T14:00:00-03:00"},
        "end": {"dateTime": "2026-10-01T15:30:00-03:00"},
    }
    base.update(extras)
    return base


class TestNormalizarEvento(unittest.TestCase):
    def test_evento_com_horario(self):
        evento = normalizar_evento(_bruto())
        self.assertEqual(evento["id"], "ev1")
        self.assertEqual(evento["titulo"], "Reunião PROPLAD")
        self.assertEqual(evento["descricao"], "Pauta")
        self.assertEqual(evento["data_inicio"], date(2026, 10, 1))
        self.assertEqual(evento["hora_inicio"], time(14, 0))
        self.assertEqual(evento["data_fim"], date(2026, 10, 1))
        self.assertEqual(evento["hora_fim"], time(15, 30))
        self.assertFalse(evento["cancelado"])
        self.assertEqual(evento["atualizado_em"], "2026-09-20T12:00:00.000Z")
        self.assertIsNone(evento["prazo_id"])
        self.assertEqual(evento["propriedades"], {})
        self.assertEqual(evento["organizador"], "chefe@ufrpe.br")
        self.assertIsNone(evento["minha_resposta"])
        self.assertEqual(evento["link"], "https://calendar.google.com/ev1")

    def test_horario_em_utc_e_convertido_para_recife(self):
        evento = normalizar_evento(_bruto(start={"dateTime": "2026-10-02T01:30:00Z"}))
        # 01:30 UTC = 22:30 do dia anterior em Recife (UTC-3)
        self.assertEqual(evento["data_inicio"], date(2026, 10, 1))
        self.assertEqual(evento["hora_inicio"], time(22, 30))

    def test_evento_de_dia_inteiro(self):
        evento = normalizar_evento(_bruto(start={"date": "2026-12-01"}, end={"date": "2026-12-02"}))
        self.assertEqual(evento["data_inicio"], date(2026, 12, 1))
        self.assertIsNone(evento["hora_inicio"])
        self.assertEqual(evento["data_fim"], date(2026, 12, 2))
        self.assertIsNone(evento["hora_fim"])

    def test_evento_cancelado_sem_datas(self):
        evento = normalizar_evento({"id": "ev9", "status": "cancelled", "updated": "2026-09-21T00:00:00Z"})
        self.assertTrue(evento["cancelado"])
        self.assertIsNone(evento["data_inicio"])
        self.assertEqual(evento["titulo"], "")
        self.assertEqual(evento["descricao"], "")

    def test_marcador_de_prazo(self):
        evento = normalizar_evento(_bruto(extendedProperties={"private": {MARCADOR: "abc", "budgetlab": "1"}}))
        self.assertEqual(evento["prazo_id"], "abc")
        self.assertEqual(evento["propriedades"]["budgetlab"], "1")

    def test_minha_resposta_vem_do_attendee_self(self):
        evento = normalizar_evento(_bruto(attendees=[
            {"email": "outro@ufrpe.br", "responseStatus": "accepted"},
            {"email": "eu@gmail.com", "self": True, "responseStatus": "needsAction"},
        ]))
        self.assertEqual(evento["minha_resposta"], "needsAction")


class TestSituacaoConexao(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.diretorio = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_sem_credenciais(self):
        self.assertEqual(situacao_conexao(self.diretorio), "sem_credenciais")

    def test_diretorio_inexistente_e_sem_credenciais(self):
        self.assertEqual(situacao_conexao(self.diretorio / "nao_existe"), "sem_credenciais")

    def test_credenciais_sem_token_e_desconectado(self):
        (self.diretorio / ARQUIVO_CREDENCIAIS).write_text("{}", encoding="utf-8")
        self.assertEqual(situacao_conexao(self.diretorio), "desconectado")

    def test_token_com_refresh_token_e_conectado(self):
        (self.diretorio / ARQUIVO_CREDENCIAIS).write_text("{}", encoding="utf-8")
        (self.diretorio / ARQUIVO_TOKEN).write_text(json.dumps({
            "client_id": "x", "client_secret": "y", "refresh_token": "z",
            "token": "t", "scopes": ["https://www.googleapis.com/auth/calendar.events"],
        }), encoding="utf-8")
        self.assertEqual(situacao_conexao(self.diretorio), "conectado")

    def test_token_corrompido_e_desconectado(self):
        (self.diretorio / ARQUIVO_CREDENCIAIS).write_text("{}", encoding="utf-8")
        (self.diretorio / ARQUIVO_TOKEN).write_text("não é json", encoding="utf-8")
        self.assertEqual(situacao_conexao(self.diretorio), "desconectado")


class _Requisicao:
    def __init__(self, resposta=None, erro=None):
        self._resposta, self._erro = resposta, erro

    def execute(self):
        if self._erro is not None:
            raise self._erro
        return self._resposta


class _EventosFalsos:
    """Imita `servico.events()`: registra os parâmetros e devolve respostas enfileiradas."""

    def __init__(self, paginas=None, erro=None):
        self.paginas = list(paginas or [])
        self.erro = erro
        self.chamadas: list[tuple[str, dict]] = []

    def list(self, **params):
        self.chamadas.append(("list", params))
        return _Requisicao(self.paginas.pop(0) if self.paginas else {"items": []}, self.erro)

    def insert(self, **params):
        self.chamadas.append(("insert", params))
        return _Requisicao({"id": "novo", "updated": "2026-09-27T10:00:00Z", **params["body"]}, self.erro)

    def patch(self, **params):
        self.chamadas.append(("patch", params))
        return _Requisicao({"id": params["eventId"], "updated": "2026-09-27T11:00:00Z", **params["body"]}, self.erro)

    def delete(self, **params):
        self.chamadas.append(("delete", params))
        return _Requisicao("", self.erro)


class _ServicoFalso:
    def __init__(self, eventos: _EventosFalsos):
        self._eventos = eventos

    def events(self):
        return self._eventos


def _http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"erro")


class TestClienteGoogleAgenda(unittest.TestCase):
    def test_listagem_percorre_todas_as_paginas(self):
        eventos = _EventosFalsos(paginas=[
            {"items": [{"id": "a"}], "nextPageToken": "p2"},
            {"items": [{"id": "b"}]},
        ])
        resultado = ClienteGoogleAgenda(_ServicoFalso(eventos)).listar_eventos_de_prazos()
        self.assertEqual([e["id"] for e in resultado], ["a", "b"])
        self.assertEqual(eventos.chamadas[1][1]["pageToken"], "p2")

    def test_listar_eventos_de_prazos_filtra_marcador_e_inclui_excluidos(self):
        eventos = _EventosFalsos()
        ClienteGoogleAgenda(_ServicoFalso(eventos)).listar_eventos_de_prazos()
        params = eventos.chamadas[0][1]
        self.assertEqual(params["calendarId"], "primary")
        self.assertEqual(params["privateExtendedProperty"], "budgetlab=1")
        self.assertTrue(params["showDeleted"])

    def test_listar_eventos_usa_janela_e_expande_recorrentes(self):
        eventos = _EventosFalsos()
        inicio = datetime(2026, 9, 27, tzinfo=timezone.utc)
        fim = datetime(2026, 10, 27, tzinfo=timezone.utc)
        ClienteGoogleAgenda(_ServicoFalso(eventos)).listar_eventos(inicio, fim)
        params = eventos.chamadas[0][1]
        self.assertEqual(params["timeMin"], inicio.isoformat())
        self.assertEqual(params["timeMax"], fim.isoformat())
        self.assertTrue(params["singleEvents"])
        self.assertEqual(params["orderBy"], "startTime")

    def test_listar_eventos_exige_datetime_com_fuso(self):
        cliente = ClienteGoogleAgenda(_ServicoFalso(_EventosFalsos()))
        with self.assertRaises(ValueError):
            cliente.listar_eventos(datetime(2026, 9, 27), datetime(2026, 10, 27))

    def test_falha_na_listagem_vira_erro_google_agenda(self):
        cliente = ClienteGoogleAgenda(_ServicoFalso(_EventosFalsos(erro=_http_error(500))))
        with self.assertRaises(ErroGoogleAgenda):
            cliente.listar_eventos_de_prazos()

    def test_criar_e_atualizar_devolvem_evento_normalizado(self):
        eventos = _EventosFalsos()
        cliente = ClienteGoogleAgenda(_ServicoFalso(eventos))
        criado = cliente.criar_evento({"summary": "Prazo", "start": {"date": "2026-12-01"}, "end": {"date": "2026-12-02"}})
        self.assertEqual(criado["id"], "novo")
        self.assertEqual(criado["titulo"], "Prazo")
        atualizado = cliente.atualizar_evento("novo", {"summary": "Prazo 2"})
        self.assertEqual(atualizado["atualizado_em"], "2026-09-27T11:00:00Z")
        self.assertEqual(eventos.chamadas[1][0], "patch")

    def test_excluir_evento_ja_removido_nao_e_erro(self):
        for status in (404, 410):
            cliente = ClienteGoogleAgenda(_ServicoFalso(_EventosFalsos(erro=_http_error(status))))
            cliente.excluir_evento("x")  # não lança

    def test_sem_internet_na_listagem_vira_erro_google_agenda(self):
        # httplib2 converte a falha de DNS em ServerNotFoundError (não é OSError)
        erro = httplib2.ServerNotFoundError("Unable to find the server at www.googleapis.com")
        cliente = ClienteGoogleAgenda(_ServicoFalso(_EventosFalsos(erro=erro)))
        with self.assertRaises(ErroGoogleAgenda):
            cliente.listar_eventos_de_prazos()

    def test_token_revogado_durante_requisicao_vira_erro_google_agenda(self):
        cliente = ClienteGoogleAgenda(_ServicoFalso(_EventosFalsos(erro=RefreshError("invalid_grant"))))
        with self.assertRaises(ErroGoogleAgenda):
            cliente.criar_evento({"summary": "x"})

    def test_sem_internet_ao_excluir_vira_erro_google_agenda(self):
        erro = httplib2.ServerNotFoundError("sem rede")
        cliente = ClienteGoogleAgenda(_ServicoFalso(_EventosFalsos(erro=erro)))
        with self.assertRaises(ErroGoogleAgenda):
            cliente.excluir_evento("x")

    def test_excluir_com_outro_erro_vira_erro_google_agenda(self):
        cliente = ClienteGoogleAgenda(_ServicoFalso(_EventosFalsos(erro=_http_error(403))))
        with self.assertRaises(ErroGoogleAgenda):
            cliente.excluir_evento("x")


class TestConectarDesconectar(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.diretorio = Path(self._tmp.name)
        (self.diretorio / ARQUIVO_CREDENCIAIS).write_text("{}", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_conectar_grava_token(self):
        credenciais = mock.Mock()
        credenciais.to_json.return_value = '{"refresh_token": "z"}'
        fluxo = mock.Mock()
        fluxo.run_local_server.return_value = credenciais
        with mock.patch("src.google_agenda.InstalledAppFlow") as classe_fluxo:
            classe_fluxo.from_client_secrets_file.return_value = fluxo
            conectar(self.diretorio)
        self.assertEqual(
            json.loads((self.diretorio / ARQUIVO_TOKEN).read_text(encoding="utf-8")),
            {"refresh_token": "z"},
        )

    def test_conectar_sem_credenciais_e_erro(self):
        (self.diretorio / ARQUIVO_CREDENCIAIS).unlink()
        with self.assertRaises(ErroGoogleAgenda):
            conectar(self.diretorio)

    def _token_expirado(self):
        # sem "token": credencial inválida com refresh_token → cliente() tenta renovar
        (self.diretorio / ARQUIVO_TOKEN).write_text(json.dumps({
            "client_id": "x", "client_secret": "y", "refresh_token": "z",
            "scopes": ["https://www.googleapis.com/auth/calendar.events"],
        }), encoding="utf-8")

    def test_renovar_token_sem_internet_vira_erro_e_mantem_token(self):
        self._token_expirado()
        with mock.patch("google.oauth2.credentials.Credentials.refresh",
                        side_effect=TransportError("sem rede")):
            with self.assertRaises(ErroGoogleAgenda):
                cliente(self.diretorio)
        self.assertTrue((self.diretorio / ARQUIVO_TOKEN).exists())

    def test_renovar_token_revogado_desconecta(self):
        self._token_expirado()
        with mock.patch("google.oauth2.credentials.Credentials.refresh",
                        side_effect=RefreshError("invalid_grant")):
            with self.assertRaises(ErroGoogleAgenda):
                cliente(self.diretorio)
        self.assertFalse((self.diretorio / ARQUIVO_TOKEN).exists())

    def test_desconectar_apaga_so_o_token(self):
        (self.diretorio / ARQUIVO_TOKEN).write_text("{}", encoding="utf-8")
        desconectar(self.diretorio)
        self.assertFalse((self.diretorio / ARQUIVO_TOKEN).exists())
        self.assertTrue((self.diretorio / ARQUIVO_CREDENCIAIS).exists())
        desconectar(self.diretorio)  # idempotente


if __name__ == "__main__":
    unittest.main()
