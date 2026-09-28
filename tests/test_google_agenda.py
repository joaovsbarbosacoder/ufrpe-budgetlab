"""Testes de src/google_agenda.py — normalização de eventos da API e situação da conexão.
Nenhum teste acessa a rede nem usa credencial real; diretórios são temporários.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, time
from pathlib import Path

from src.google_agenda import (
    ARQUIVO_CREDENCIAIS,
    ARQUIVO_TOKEN,
    MARCADOR,
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


if __name__ == "__main__":
    unittest.main()
