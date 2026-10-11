"""Testes de `src/linha_tempo_vigencias.py` — linha do tempo das vigências por contrato (Contratos.gov × Contínuos).

Somente leitura: a regra só monta segmentos, marcadores e situação a partir dos dados recebidos.
"""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from src.linha_tempo_vigencias import (
    Evento,
    Segmento,
    contagens,
    janela_padrao,
    linhas_do_tempo,
    situacao_vigencia,
)

HOJE = date(2026, 10, 11)


def _cadastro() -> pd.DataFrame:
    return pd.DataFrame({
        "contrato_numero": ["35/2024", "35/2024", "99/2026", "13/2026"],
        "fornecedor": ["Serval", "Serval", "Sem Par", "Prime"],
        "contratosgov_id": ["1", "1", pd.NA, "2"],
        "vigencia_fim_efetiva": [pd.Timestamp("2026-06-16"), pd.Timestamp("2026-06-16"), pd.Timestamp("2027-01-31"), pd.Timestamp("2027-09-10")],
    })


def _contratos_gov() -> pd.DataFrame:
    return pd.DataFrame({
        "contrato_id": ["1", "2"],
        "vigencia_inicio": [date(2024, 10, 16), date(2026, 9, 10)],
        "vigencia_fim": [date(2026, 6, 16), date(2027, 3, 1)],
    })


def _termos_gov() -> pd.DataFrame:
    return pd.DataFrame({
        "contrato_id": ["1", "1", "1", "1", "1", "2"],
        "tipo": ["Contrato", "Termo Aditivo", "Termo Aditivo", "Termo de Apostilamento", "Termo de Rescisão", "Contrato"],
        "numero": ["00035/2024", "00003/2025", "00001/2024", "00002/2026", "00009/2026", "00013/2026"],
        "qualificacao_termo": [None, "VIGÊNCIA; REAJUSTE", "ACRÉSCIMO / SUPRESSÃO; REAJUSTE", None, None, None],
        "vigencia_inicio": [date(2024, 10, 16), date(2025, 10, 17), date(2024, 12, 2), date(2024, 10, 16), date(2026, 6, 1), date(2026, 9, 10)],
        "vigencia_fim": [date(2025, 10, 16), date(2026, 2, 16), date(2025, 10, 16), date(2026, 2, 16), None, date(2027, 3, 1)],
        "data_assinatura": [date(2024, 10, 1), date(2025, 10, 15), date(2024, 12, 2), date(2026, 2, 3), date(2026, 6, 1), date(2026, 9, 1)],
        "data_inicio_novo_valor": [None, date(2025, 10, 17), date(2024, 12, 2), date(2026, 2, 3), None, None],
    })


def _por_numero():
    return {l.contrato: l for l in linhas_do_tempo(_cadastro(), _contratos_gov(), _termos_gov(), HOJE)}


class SituacaoTests(unittest.TestCase):
    def test_situacoes(self) -> None:
        self.assertEqual(situacao_vigencia(False, date(2027, 1, 1), HOJE), ("Sem ligação ao gov", "neutro"))
        self.assertEqual(situacao_vigencia(True, None, HOJE), ("Sem data de fim", "warn"))
        self.assertEqual(situacao_vigencia(True, date(2026, 6, 16), HOJE), ("Encerrado", "neutro"))
        self.assertEqual(situacao_vigencia(True, date(2026, 10, 17), HOJE), ("Vence em 6 dia(s)", "warn"))
        self.assertEqual(situacao_vigencia(True, date(2026, 10, 11), HOJE), ("Vence em 0 dia(s)", "warn"))
        self.assertEqual(situacao_vigencia(True, date(2027, 9, 10), HOJE), ("Vigente", "ok"))


class LinhasTests(unittest.TestCase):
    def test_uma_linha_por_contrato_ordenada_pelo_fim(self) -> None:
        linhas = linhas_do_tempo(_cadastro(), _contratos_gov(), _termos_gov(), HOJE)
        self.assertEqual([l.contrato for l in linhas], ["35/2024", "99/2026", "13/2026"])  # 16/06/26, 31/01/27, 01/03/27

    def test_segmentos_sao_o_contrato_e_os_termos_de_vigencia(self) -> None:
        linha = _por_numero()["35/2024"]
        self.assertEqual(linha.segmentos, [
            Segmento(date(2024, 10, 16), date(2025, 10, 16), "Contrato 00035/2024", "contrato"),
            Segmento(date(2025, 10, 17), date(2026, 2, 16), "TA 00003/2025", "ta"),
        ])  # o TA 00001/2024 (acréscimo + reajuste, sem VIGÊNCIA) não é segmento

    def test_marcadores_de_reajuste_acrescimo_apostilamento_e_rescisao(self) -> None:
        eventos = _por_numero()["35/2024"].eventos
        self.assertIn(Evento(date(2024, 12, 2), "RA", "TA 00001/2024: ACRÉSCIMO / SUPRESSÃO; REAJUSTE"), eventos)
        self.assertIn(Evento(date(2025, 10, 17), "R", "TA 00003/2025: VIGÊNCIA; REAJUSTE"), eventos)
        self.assertIn(Evento(date(2026, 2, 3), "P", "Apostilamento 00002/2026"), eventos)
        self.assertIn(Evento(date(2026, 6, 1), "X", "Rescisão 00009/2026"), eventos)
        self.assertEqual(eventos, sorted(eventos, key=lambda e: e.data))

    def test_situacao_e_divergencia_com_o_cadastro(self) -> None:
        linhas = _por_numero()
        self.assertEqual((linhas["35/2024"].situacao, linhas["35/2024"].tom), ("Encerrado", "neutro"))
        self.assertFalse(linhas["35/2024"].diverge)
        prime = linhas["13/2026"]
        self.assertEqual(prime.fim, date(2027, 3, 1))  # o fim do gov manda
        self.assertTrue(prime.diverge)  # cadastro diz 10/09/2027
        self.assertEqual(prime.situacao, "Vigente")

    def test_contrato_sem_ligacao_usa_a_vigencia_do_cadastro(self) -> None:
        linha = _por_numero()["99/2026"]
        self.assertFalse(linha.ligado)
        self.assertEqual(linha.segmentos, [Segmento(None, date(2027, 1, 31), "Vigência do cadastro", "cadastro")])
        self.assertEqual(linha.situacao, "Sem ligação ao gov")

    def test_sem_fotografia_do_gov_todos_ficam_sem_ligacao(self) -> None:
        linhas = linhas_do_tempo(_cadastro(), None, None, HOJE)
        self.assertEqual(len(linhas), 3)
        self.assertTrue(all(not l.ligado for l in linhas))


class AuxiliaresTests(unittest.TestCase):
    def test_contagens(self) -> None:
        linhas = linhas_do_tempo(_cadastro(), _contratos_gov(), _termos_gov(), HOJE)
        self.assertEqual(contagens(linhas, HOJE), {
            "contratos": 3, "vigentes": 1, "vencem_90_dias": 0, "encerrados": 1, "sem_ligacao": 1, "sem_data": 0, "divergentes": 1,
        })

    def test_janela_vai_de_dois_anos_antes_ao_ultimo_fim(self) -> None:
        linhas = linhas_do_tempo(_cadastro(), _contratos_gov(), _termos_gov(), HOJE)
        self.assertEqual(janela_padrao(linhas, HOJE), (date(2024, 1, 1), date(2027, 12, 31)))


if __name__ == "__main__":
    unittest.main()
