"""Testes de src/prazos_sincronizacao.py — mapeamento prazo ↔ evento e conciliação com um
cliente falso em memória (nunca acessa a rede). Diretórios temporários a cada teste."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta, timezone

from src.google_agenda import MARCADOR
from src.prazos_orcamentarios import novo_prazo
from src.prazos_sincronizacao import (
    ErroSincronizacao,
    campos_do_evento,
    corpo_evento,
    sincronizacao_devida,
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


if __name__ == "__main__":
    unittest.main()
