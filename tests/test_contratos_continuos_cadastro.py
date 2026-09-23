"""Testes do cadastro nativo de Contratos Contínuos.

`meses_no_ano` (pedido explícito, mesmo campo/motivo de
`tests/test_bolsas_auxilios_cadastro.py`): total de meses que o contrato é pago no exercício —
corrige o mesmo bug real de Bolsas e Auxílios (`despesa_anual` sempre `× 12`, mesmo para um
contrato que só roda parte do ano). Único módulo deste par (Bolsas/Contratos Contínuos) sem
teste dedicado até agora — os demais campos do cadastro continuam cobertos só indiretamente
por `tests/test_relatorio_reforco_empenho.py`/`tests/test_ui_relatorio_reforco_empenho.py`.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import src.cadastro_por_exercicio as cadastro_por_exercicio
import src.contratos_continuos_cadastro as cadastro


class TestMesesNoAno(unittest.TestCase):
    def test_despesa_anual_usa_meses_no_ano(self) -> None:
        registro = cadastro.novo_contrato(despesa_mensal=1000.0, meses_no_ano=6)
        dataframe = cadastro.como_dataframe([registro])
        self.assertAlmostEqual(dataframe.loc[0, "despesa_anual"], 6000.0)

    def test_sem_meses_no_ano_cai_no_padrao_de_12(self) -> None:
        # registro anterior a esta correção (campo nunca preenchido, `novo_contrato` sem o
        # argumento) -- mesmo comportamento de antes, contrato "contínuo" o ano inteiro.
        registro = cadastro.novo_contrato(despesa_mensal=1000.0)
        self.assertIsNone(registro["meses_no_ano"])
        dataframe = cadastro.como_dataframe([registro])
        self.assertAlmostEqual(dataframe.loc[0, "despesa_anual"], 12000.0)

    def test_contrato_de_12_meses_explicito_bate_com_o_padrao_anterior(self) -> None:
        registro = cadastro.novo_contrato(despesa_mensal=2500.0, meses_no_ano=12)
        dataframe = cadastro.como_dataframe([registro])
        self.assertAlmostEqual(dataframe.loc[0, "despesa_anual"], 30000.0)

    def test_meses_no_ano_e_copiado_ao_duplicar_identidade(self) -> None:
        self.assertIn("meses_no_ano", cadastro.CAMPOS_IDENTIDADE)


class TestVigenciaFim(unittest.TestCase):
    """`vigencia_fim` agora é editável na tela (cartão e "+ Novo contrato"): a página grava
    ISO 8601 ou `None` — vazio nunca vira data presumida."""

    def test_data_informada_vira_timestamp_no_dataframe(self) -> None:
        registro = cadastro.novo_contrato(vigencia_fim="2027-03-31")
        dataframe = cadastro.como_dataframe([registro])
        self.assertEqual(dataframe.loc[0, "vigencia_fim"], pd.Timestamp("2027-03-31"))

    def test_sem_data_fica_nulo(self) -> None:
        registro = cadastro.novo_contrato(vigencia_fim=None)
        self.assertIsNone(registro["vigencia_fim"])
        dataframe = cadastro.como_dataframe([registro])
        self.assertTrue(pd.isna(dataframe.loc[0, "vigencia_fim"]))

    def test_grava_e_recarrega_a_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp)
            registro = cadastro.novo_contrato(vigencia_fim="2027-03-31")
            cadastro_por_exercicio.salvar(destino, 2026, registro)
            recarregado = cadastro_por_exercicio.carregar_registros(destino, 2026)
            self.assertEqual(recarregado[0]["vigencia_fim"], "2027-03-31")

            registro["vigencia_fim"] = pd.Timestamp("NaT")  # linha.to_dict() sem data
            cadastro_por_exercicio.atualizar(destino, 2026, registro)
            recarregado = cadastro_por_exercicio.carregar_registros(destino, 2026)
            self.assertIsNone(recarregado[0]["vigencia_fim"])


class TestSituacaoVigencia(unittest.TestCase):
    HOJE = date(2026, 9, 23)

    def _situacao(self, vigencia: object) -> tuple[str, int | None]:
        return cadastro.situacao_vigencia(vigencia, hoje=self.HOJE)

    def test_sem_data_nunca_e_presumida(self) -> None:
        for vazio in (None, pd.NaT, pd.NA, "", "texto invalido", float("nan")):
            self.assertEqual(self._situacao(vazio), ("sem_data", None))

    def test_expirada(self) -> None:
        self.assertEqual(self._situacao("2026-09-22"), ("expirada", -1))
        self.assertEqual(self._situacao(pd.Timestamp("2026-01-01")), ("expirada", -265))

    def test_vence_hoje_conta_como_a_vencer(self) -> None:
        self.assertEqual(self._situacao("2026-09-23T00:00:00"), ("a_vencer", 0))

    def test_limite_da_janela_de_alerta(self) -> None:
        limite = self.HOJE + timedelta(days=cadastro.DIAS_ALERTA_VIGENCIA)
        self.assertEqual(self._situacao(limite.isoformat())[0], "a_vencer")
        depois = limite + timedelta(days=1)
        self.assertEqual(self._situacao(depois.isoformat())[0], "vigente")

    def test_aceita_date_do_widget(self) -> None:
        self.assertEqual(self._situacao(date(2027, 12, 31))[0], "vigente")


class TestResumoVigencia(unittest.TestCase):
    HOJE = date(2026, 9, 23)

    def setUp(self) -> None:
        self.vigencias = pd.Series(
            [
                "2026-09-01",  # expirada
                "2026-01-01",  # expirada
                "2026-10-01",  # a vencer
                "2027-12-31",  # vigente
                None,          # sem data
                pd.NaT,        # sem data
            ],
            index=[10, 11, 12, 13, 14, 15],
        )

    def test_contagem_por_situacao(self) -> None:
        resumo = cadastro.resumo_vigencia(self.vigencias, self.HOJE)
        self.assertEqual(
            resumo, {"expirada": 2, "a_vencer": 1, "vigente": 1, "sem_data": 2, "total": 6}
        )

    def test_sem_data_nao_entra_nos_contadores_de_alerta(self) -> None:
        resumo = cadastro.resumo_vigencia(pd.Series([None, pd.NaT]), self.HOJE)
        self.assertEqual((resumo["expirada"], resumo["a_vencer"]), (0, 0))
        self.assertEqual(resumo["sem_data"], 2)

    def test_situacoes_preserva_indice_e_permite_filtrar(self) -> None:
        situacoes = cadastro.situacoes_vigencia(self.vigencias, self.HOJE)
        self.assertEqual(list(situacoes.index), [10, 11, 12, 13, 14, 15])
        alerta = self.vigencias[situacoes.isin(["expirada", "a_vencer"])]
        self.assertEqual(list(alerta.index), [10, 11, 12])

    def test_serie_vazia(self) -> None:
        resumo = cadastro.resumo_vigencia(pd.Series([], dtype="object"), self.HOJE)
        self.assertEqual(resumo["total"], 0)


class TestDuplicarExercicioEVigencia(unittest.TestCase):
    HOJE = date(2026, 9, 23)

    def _origem(self) -> list[dict]:
        return [
            cadastro.novo_contrato(fornecedor="Expirado", vigencia_fim="2026-08-01", despesa_mensal=100.0),
            cadastro.novo_contrato(fornecedor="A vencer", vigencia_fim="2026-10-10"),
            cadastro.novo_contrato(fornecedor="Vigente", vigencia_fim="2028-01-31"),
            cadastro.novo_contrato(fornecedor="Sem data"),
        ]

    def test_duplicar_copia_vigencia_sem_alterar_e_zera_execucao(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp)
            origem = self._origem()
            origem[0]["valor_empenhado"] = 999.0
            novos = cadastro_por_exercicio.duplicar_exercicio(
                destino, origem, 2027, cadastro.CAMPOS_IDENTIDADE, cadastro.CAMPOS_EXECUCAO_PADRAO
            )
            self.assertEqual(
                [n["vigencia_fim"] for n in novos],
                ["2026-08-01", "2026-10-10", "2028-01-31", None],
            )
            self.assertEqual(novos[0]["valor_empenhado"], 0.0)
            recarregados = cadastro_por_exercicio.carregar_registros(destino, 2027)
            self.assertEqual(len(recarregados), 4)
            self.assertEqual({r["vigencia_fim"] for r in recarregados}, {"2026-08-01", "2026-10-10", "2028-01-31", None})

    def test_aviso_conta_expiradas_a_vencer_e_sem_data(self) -> None:
        self.assertEqual(cadastro.aviso_vigencia_duplicacao(self._origem(), self.HOJE), (1, 1, 1))

    def test_aviso_sem_registros(self) -> None:
        self.assertEqual(cadastro.aviso_vigencia_duplicacao([], self.HOJE), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
