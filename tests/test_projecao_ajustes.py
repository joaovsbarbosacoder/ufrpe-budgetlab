"""Testes do log de ajustes da Projeção pela Execução (`src/projecao_ajustes.py`).
Cada teste usa uma pasta temporária; nada toca `data/`."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.projecao_ajustes import (
    ErroAjuste,
    ajustes_vigentes,
    carregar_eventos,
    reconstruir,
    refazer_ne,
    refazer_tudo,
    registrar_ajustes,
)

NE = "2026NE000001"
OUTRA = "2026NE000002"


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pasta = Path(self._tmp.name)

    def ajustar(self, valores, ne=NE, exercicio=2026):
        return registrar_ajustes(exercicio=exercicio, ne_curta=ne, valores=valores, extracao="abcd1234", diretorio=self.pasta)

    def vigentes(self, exercicio=2026):
        return ajustes_vigentes(exercicio, self.pasta)


class TestReconstruir(_Base):
    def test_registrar_e_reconstruir(self):
        self.ajustar({9: 800.0, 10: 0.0})
        self.assertEqual(self.vigentes(), {NE: {9: 800.0, 10: 0.0}})

    def test_zero_e_valido(self):
        self.ajustar({11: 0.0})
        self.assertEqual(self.vigentes()[NE][11], 0.0)

    def test_ultimo_vence_e_none_remove(self):
        self.ajustar({9: 800.0})
        self.ajustar({9: 900.0})
        self.assertEqual(self.vigentes(), {NE: {9: 900.0}})
        self.ajustar({9: None})
        self.assertEqual(self.vigentes(), {})  # NE sem meses some do dicionário

    def test_ajustes_de_meses_diferentes_se_acumulam(self):
        self.ajustar({9: 800.0})
        self.ajustar({10: 700.0})
        self.assertEqual(self.vigentes(), {NE: {9: 800.0, 10: 700.0}})

    def test_refazer_ne_so_limpa_aquela(self):
        self.ajustar({9: 800.0})
        self.ajustar({9: 500.0}, ne=OUTRA)
        refazer_ne(exercicio=2026, ne_curta=NE, extracao="abcd1234", diretorio=self.pasta)
        self.assertEqual(self.vigentes(), {OUTRA: {9: 500.0}})

    def test_ajuste_depois_do_refazer_vale(self):
        self.ajustar({9: 800.0})
        refazer_ne(exercicio=2026, ne_curta=NE, extracao="abcd1234", diretorio=self.pasta)
        self.ajustar({9: 600.0})
        self.assertEqual(self.vigentes(), {NE: {9: 600.0}})

    def test_refazer_tudo_limpa_o_exercicio_mas_nao_outro_exercicio(self):
        self.ajustar({9: 800.0})
        self.ajustar({9: 100.0}, exercicio=2027)
        refazer_tudo(exercicio=2026, extracao="abcd1234", diretorio=self.pasta)
        self.assertEqual(self.vigentes(2026), {})
        self.assertEqual(self.vigentes(2027), {NE: {9: 100.0}})

    def test_sem_pasta_nao_ha_ajustes(self):
        self.assertEqual(ajustes_vigentes(2026, self.pasta / "nao_existe"), {})

    def test_ne_curta_preserva_texto(self):
        self.ajustar({9: 1.0}, ne="2026NE000551")
        self.assertIn("2026NE000551", self.vigentes())

    def test_reconstruir_puro_respeita_a_ordem_dos_eventos(self):
        eventos = [
            {"tipo": "ajustar", "ne_curta": NE, "valores": {"9": 10.0}},
            {"tipo": "refazer_ne", "ne_curta": NE},
            {"tipo": "ajustar", "ne_curta": NE, "valores": {"9": 20.0}},
        ]
        self.assertEqual(reconstruir(eventos), {NE: {9: 20.0}})


class TestLog(_Base):
    def test_log_nao_e_apagado(self):
        self.ajustar({9: 1.0})
        self.ajustar({9: 2.0})
        refazer_ne(exercicio=2026, ne_curta=NE, extracao="abcd1234", diretorio=self.pasta)
        self.assertEqual(len(list((self.pasta / "2026").glob("*.json"))), 3)
        self.assertEqual([e["tipo"] for e in carregar_eventos(2026, self.pasta)], ["ajustar", "ajustar", "refazer_ne"])

    def test_evento_guarda_extracao_e_data(self):
        evento = self.ajustar({9: 1.0})
        self.assertEqual(evento["extracao"], "abcd1234")
        self.assertTrue(evento["registrado_em"])

    def test_arquivo_corrompido_levanta_erro_e_nao_e_sobrescrito(self):
        self.ajustar({9: 1.0})
        ruim = (self.pasta / "2026" / "0000_corrompido.json")
        ruim.write_text("{", encoding="utf-8")
        with self.assertRaises(ErroAjuste):
            carregar_eventos(2026, self.pasta)
        with self.assertRaises(ErroAjuste):
            self.ajustar({9: 2.0})  # não grava por cima de um log ilegível
        self.assertEqual(ruim.read_text(encoding="utf-8"), "{")
        self.assertEqual(len(list((self.pasta / "2026").glob("*.json"))), 2)


class TestEventoValidoPorFora(_Base):
    """Evento JSON válido mas incompleto/estranho não pode derrubar quem lê: vira `ErroAjuste`."""

    def _escrever(self, evento: dict, nome="0001_evento.json"):
        import json
        pasta = self.pasta / "2026"
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / nome).write_text(json.dumps(evento), encoding="utf-8")

    def _base(self, **mudancas):
        evento = {"versao_schema": 1, "tipo": "ajustar", "id": "abc", "registrado_em": "2026-10-14T10:00:00",
                  "extracao": "x", "ne_curta": NE, "valores": {"9": 100.0}}
        evento.update(mudancas)
        return evento

    def test_eventos_incompletos_ou_invalidos_levantam_erro_ajuste(self):
        casos = {
            "sem_ne": {k: v for k, v in self._base().items() if k != "ne_curta"},
            "ne_vazia": self._base(ne_curta="  "),
            "valores_nao_dict": self._base(valores=[1, 2]),
            "valor_texto": self._base(valores={"9": "abc"}),
            "valor_negativo": self._base(valores={"9": -5}),
            "mes_fora": self._base(valores={"13": 1.0}),
            "mes_texto": self._base(valores={"x": 1.0}),
            "refazer_ne_sem_ne": {"versao_schema": 1, "tipo": "refazer_ne", "id": "b", "registrado_em": "2026-10-14T10:00:01"},
        }
        for nome, evento in casos.items():
            with self.subTest(caso=nome):
                for arquivo in (self.pasta / "2026").glob("*.json") if (self.pasta / "2026").exists() else []:
                    arquivo.unlink()
                self._escrever(evento)
                with self.assertRaises(ErroAjuste):
                    ajustes_vigentes(2026, self.pasta)

    def test_evento_valido_continua_lendo(self):
        self._escrever(self._base())
        self.assertEqual(ajustes_vigentes(2026, self.pasta), {NE: {9: 100.0}})


class TestValidacao(_Base):
    def test_valores_invalidos(self):
        casos = [{9: -1.0}, {9: float("nan")}, {9: float("inf")}, {0: 1.0}, {13: 1.0}, {}]
        for valores in casos:
            with self.subTest(valores=valores), self.assertRaises(ErroAjuste):
                self.ajustar(valores)

    def test_ne_vazia_e_recusada(self):
        for ne in ("", "   "):
            with self.subTest(ne=ne), self.assertRaises(ErroAjuste):
                self.ajustar({9: 1.0}, ne=ne)

    def test_nada_foi_gravado_quando_invalido(self):
        with self.assertRaises(ErroAjuste):
            self.ajustar({9: -1.0})
        self.assertEqual(self.vigentes(), {})


if __name__ == "__main__":
    unittest.main()
