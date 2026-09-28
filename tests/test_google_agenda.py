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
    DIRETORIO_PADRAO,
    DIRETORIO_TOKEN,
    MARCADOR,
    URL_REVOGACAO,
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


_TOKEN_VALIDO = json.dumps({
    "client_id": "x", "client_secret": "y", "refresh_token": "z",
    "token": "t", "scopes": ["https://www.googleapis.com/auth/calendar.events"],
})


class _ComDiretorios(unittest.TestCase):
    """`diretorio` (credentials.json, pasta do projeto) e `token_dir` (token, fora do
    projeto) temporários e separados — nunca o %APPDATA% real."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._tmp_token = tempfile.TemporaryDirectory()
        self.diretorio = Path(self._tmp.name)
        self.token_dir = Path(self._tmp_token.name) / "UFRPE BudgetLab"  # ainda não existe

    def tearDown(self):
        self._tmp.cleanup()
        self._tmp_token.cleanup()

    def _credenciais(self):
        (self.diretorio / ARQUIVO_CREDENCIAIS).write_text("{}", encoding="utf-8")

    def _token(self, conteudo=_TOKEN_VALIDO, onde=None):
        onde = onde or self.token_dir
        onde.mkdir(parents=True, exist_ok=True)
        (onde / ARQUIVO_TOKEN).write_text(conteudo, encoding="utf-8")


class TestSituacaoConexao(_ComDiretorios):
    def test_sem_credenciais(self):
        self.assertEqual(situacao_conexao(self.diretorio, self.token_dir), "sem_credenciais")

    def test_diretorio_inexistente_e_sem_credenciais(self):
        self.assertEqual(situacao_conexao(self.diretorio / "nao_existe", self.token_dir), "sem_credenciais")

    def test_credenciais_sem_token_e_desconectado(self):
        self._credenciais()
        self.assertEqual(situacao_conexao(self.diretorio, self.token_dir), "desconectado")

    def test_token_com_refresh_token_e_conectado(self):
        self._credenciais()
        self._token()
        self.assertEqual(situacao_conexao(self.diretorio, self.token_dir), "conectado")

    def test_token_corrompido_e_desconectado(self):
        self._credenciais()
        self._token("não é json")
        self.assertEqual(situacao_conexao(self.diretorio, self.token_dir), "desconectado")

    def test_token_fica_fora_da_pasta_do_projeto_por_padrao(self):
        # a pasta do projeto é sincronizada com o Google Drive: o token não pode ir para lá
        self.assertNotEqual(DIRETORIO_TOKEN.resolve(), DIRETORIO_PADRAO.resolve())
        self.assertNotIn(Path.cwd().resolve(), DIRETORIO_TOKEN.resolve().parents)

    def test_token_antigo_na_pasta_do_projeto_e_migrado(self):
        self._credenciais()
        self._token(onde=self.diretorio)  # local antigo, anterior a esta mudança
        self.assertEqual(situacao_conexao(self.diretorio, self.token_dir), "conectado")
        self.assertFalse((self.diretorio / ARQUIVO_TOKEN).exists())
        self.assertEqual((self.token_dir / ARQUIVO_TOKEN).read_text(encoding="utf-8"), _TOKEN_VALIDO)

    def test_token_antigo_e_descartado_quando_ja_existe_o_novo(self):
        self._credenciais()
        self._token()
        self._token("antigo", onde=self.diretorio)
        self.assertEqual(situacao_conexao(self.diretorio, self.token_dir), "conectado")
        self.assertFalse((self.diretorio / ARQUIVO_TOKEN).exists())
        self.assertEqual((self.token_dir / ARQUIVO_TOKEN).read_text(encoding="utf-8"), _TOKEN_VALIDO)


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

    def test_erro_http_informa_o_motivo_dado_pelo_google(self):
        # sem o motivo, um 403 no resumo/histórico não diz se foi limite de uso ou permissão
        conteudo = b'{"error": {"code": 403, "message": "Rate Limit Exceeded", "errors": [{"reason": "rateLimitExceeded"}]}}'
        erro = HttpError(httplib2.Response({"status": 403}), conteudo)
        for chamada in (
            lambda c: c.criar_evento({"summary": "x"}),
            lambda c: c.excluir_evento("x"),
        ):
            cliente = ClienteGoogleAgenda(_ServicoFalso(_EventosFalsos(erro=erro)))
            with self.assertRaises(ErroGoogleAgenda) as contexto:
                chamada(cliente)
            self.assertIn("HTTP 403", str(contexto.exception))
            self.assertIn("Rate Limit Exceeded", str(contexto.exception))

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


class TestConectarDesconectar(_ComDiretorios):
    def setUp(self):
        super().setUp()
        self._credenciais()

    def _fluxo(self, **run_local_server):
        fluxo = mock.Mock()
        fluxo.run_local_server.configure_mock(**run_local_server)
        patcher = mock.patch("src.google_agenda.InstalledAppFlow")
        classe_fluxo = patcher.start()
        self.addCleanup(patcher.stop)
        classe_fluxo.from_client_secrets_file.return_value = fluxo
        return fluxo

    def test_conectar_grava_token_fora_da_pasta_do_projeto(self):
        credenciais = mock.Mock()
        credenciais.to_json.return_value = '{"refresh_token": "z"}'
        self._fluxo(return_value=credenciais)
        conectar(self.diretorio, self.token_dir)
        self.assertEqual(
            json.loads((self.token_dir / ARQUIVO_TOKEN).read_text(encoding="utf-8")),
            {"refresh_token": "z"},
        )
        self.assertFalse((self.diretorio / ARQUIVO_TOKEN).exists())

    def test_conectar_sem_credenciais_e_erro(self):
        (self.diretorio / ARQUIVO_CREDENCIAIS).unlink()
        with self.assertRaises(ErroGoogleAgenda):
            conectar(self.diretorio, self.token_dir)

    def test_autorizacao_negada_vira_erro_google_agenda(self):
        from oauthlib.oauth2.rfc6749.errors import AccessDeniedError
        self._fluxo(side_effect=AccessDeniedError("access_denied"))
        with self.assertRaises(ErroGoogleAgenda) as contexto:
            conectar(self.diretorio, self.token_dir)
        self.assertIn("não concluída", str(contexto.exception))
        self.assertFalse((self.token_dir / ARQUIVO_TOKEN).exists())

    def test_autorizacao_abandonada_vira_erro_google_agenda(self):
        # navegador fechado: após o tempo limite a biblioteca falha com AttributeError
        fluxo = self._fluxo(side_effect=AttributeError("'NoneType' object has no attribute 'replace'"))
        with self.assertRaises(ErroGoogleAgenda):
            conectar(self.diretorio, self.token_dir)
        self.assertIn("timeout_seconds", fluxo.run_local_server.call_args.kwargs)

    def _token_expirado(self):
        # sem "token": credencial inválida com refresh_token → cliente() tenta renovar
        self._token(json.dumps({
            "client_id": "x", "client_secret": "y", "refresh_token": "z",
            "scopes": ["https://www.googleapis.com/auth/calendar.events"],
        }))

    def test_renovar_token_sem_internet_vira_erro_e_mantem_token(self):
        self._token_expirado()
        with mock.patch("google.oauth2.credentials.Credentials.refresh",
                        side_effect=TransportError("sem rede")):
            with self.assertRaises(ErroGoogleAgenda):
                cliente(self.diretorio, self.token_dir)
        self.assertTrue((self.token_dir / ARQUIVO_TOKEN).exists())

    def test_renovar_token_revogado_desconecta_sem_tentar_revogar(self):
        self._token_expirado()
        with mock.patch("google.oauth2.credentials.Credentials.refresh",
                        side_effect=RefreshError("invalid_grant")), \
             mock.patch("src.google_agenda.requests.post") as post:
            with self.assertRaises(ErroGoogleAgenda):
                cliente(self.diretorio, self.token_dir)
        self.assertFalse((self.token_dir / ARQUIVO_TOKEN).exists())
        post.assert_not_called()  # o token já é inválido: revogar só custaria uma chamada de rede

    def test_desconectar_revoga_no_google_e_apaga_o_token(self):
        self._token()
        resposta = mock.Mock(status_code=200)
        with mock.patch("src.google_agenda.requests.post", return_value=resposta) as post:
            self.assertTrue(desconectar(self.diretorio, self.token_dir))
        self.assertEqual(post.call_args.args[0], URL_REVOGACAO)
        self.assertEqual(post.call_args.kwargs["data"], {"token": "z"})  # refresh token
        self.assertFalse((self.token_dir / ARQUIVO_TOKEN).exists())
        self.assertTrue((self.diretorio / ARQUIVO_CREDENCIAIS).exists())

    def test_desconectar_sem_internet_apaga_o_token_mesmo_assim(self):
        import requests
        self._token()
        with mock.patch("src.google_agenda.requests.post", side_effect=requests.ConnectionError("sem rede")):
            self.assertFalse(desconectar(self.diretorio, self.token_dir))
        self.assertFalse((self.token_dir / ARQUIVO_TOKEN).exists())

    def test_desconectar_com_recusa_do_google_apaga_o_token_e_informa(self):
        self._token()
        with mock.patch("src.google_agenda.requests.post", return_value=mock.Mock(status_code=503)):
            self.assertFalse(desconectar(self.diretorio, self.token_dir))
        self.assertFalse((self.token_dir / ARQUIVO_TOKEN).exists())

    def test_desconectar_token_ja_invalido_no_google_conta_como_revogado(self):
        self._token()
        with mock.patch("src.google_agenda.requests.post", return_value=mock.Mock(status_code=400)):
            self.assertTrue(desconectar(self.diretorio, self.token_dir))

    def test_desconectar_sem_token_e_idempotente(self):
        with mock.patch("src.google_agenda.requests.post") as post:
            self.assertTrue(desconectar(self.diretorio, self.token_dir))
        post.assert_not_called()

    def test_desconectar_apaga_tambem_token_no_local_antigo(self):
        self._token(onde=self.diretorio)
        with mock.patch("src.google_agenda.requests.post", return_value=mock.Mock(status_code=200)):
            desconectar(self.diretorio, self.token_dir)
        self.assertFalse((self.diretorio / ARQUIVO_TOKEN).exists())
        self.assertFalse((self.token_dir / ARQUIVO_TOKEN).exists())


if __name__ == "__main__":
    unittest.main()
