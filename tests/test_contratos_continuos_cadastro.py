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
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd

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


class TestVigenciaEStatusNoCadastro(unittest.TestCase):
    """`vigencia_fim` (data) e o status SUSPENSO precisam sobreviver à gravação e à leitura: a
    projeção do relatório de Necessidade de Empenho depende dos dois (02/10/2026)."""

    def test_ida_e_volta_preserva_data_e_status(self) -> None:
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(cadastro, "DIRETORIO_PADRAO", Path(pasta)):
            registro = cadastro.novo_contrato(
                contrato_numero="14/2022", status_contrato="SUSPENSO",
                vigencia_fim=pd.Timestamp("2026-11-15"), despesa_mensal=1000.0,
            )
            cadastro.salvar_contrato(2026, registro)
            lido = cadastro.como_dataframe(cadastro.carregar_contratos(2026))
        self.assertEqual(lido.loc[0, "status_contrato"], "SUSPENSO")
        self.assertEqual(lido.loc[0, "vigencia_fim"], pd.Timestamp("2026-11-15"))

    def test_data_removida_grava_nulo_nunca_presumido(self) -> None:
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(cadastro, "DIRETORIO_PADRAO", Path(pasta)):
            registro = cadastro.novo_contrato(contrato_numero="1/2026", vigencia_fim=pd.Timestamp("2026-11-15"))
            cadastro.salvar_contrato(2026, registro)
            registro["vigencia_fim"] = None
            cadastro.atualizar_contrato(2026, registro)
            lido = cadastro.como_dataframe(cadastro.carregar_contratos(2026))
        self.assertTrue(pd.isna(lido.loc[0, "vigencia_fim"]))

    def test_vigencia_e_copiada_ao_duplicar_identidade(self) -> None:
        self.assertIn("vigencia_fim", cadastro.CAMPOS_IDENTIDADE)


class TestInicioDaExecucaoNoCadastro(unittest.TestCase):
    """`inicio_execucao_data` (início por data, 02/10/2026) é dado de execução do exercício."""

    def test_ida_e_volta_preserva_a_data(self) -> None:
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(cadastro, "DIRETORIO_PADRAO", Path(pasta)):
            registro = cadastro.novo_contrato(contrato_numero="9/2026", inicio_execucao_data=pd.Timestamp("2026-07-16"))
            cadastro.salvar_contrato(2026, registro)
            lido = cadastro.como_dataframe(cadastro.carregar_contratos(2026))
        self.assertEqual(lido.loc[0, "inicio_execucao_data"], pd.Timestamp("2026-07-16"))

    def test_sem_data_fica_nulo_nunca_presumido(self) -> None:
        lido = cadastro.como_dataframe([cadastro.novo_contrato(contrato_numero="9/2026")])
        self.assertTrue(pd.isna(lido.loc[0, "inicio_execucao_data"]))

    def test_inicio_e_de_execucao_nao_de_identidade(self) -> None:
        # por exercício: em branco no exercício novo (como `inicio_execucao_mes`), não copiado ao duplicar
        self.assertIn("inicio_execucao_data", cadastro.CAMPOS_EXECUCAO_PADRAO)
        self.assertNotIn("inicio_execucao_data", cadastro.CAMPOS_IDENTIDADE)


class TestProcessosNoCadastro(unittest.TestCase):
    """Processo da contratação e processo de empenho, editáveis na janela desde 06/10/2026: são
    identificadores (texto, zeros à esquerda preservados), nunca presumidos um a partir do outro."""

    def test_ida_e_volta_preserva_os_dois_processos_como_texto(self) -> None:
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(cadastro, "DIRETORIO_PADRAO", Path(pasta)):
            registro = cadastro.novo_contrato(
                contrato_numero="14/2022", processo_contratacao="012543/2024-98", processo_empenho="001370/2026-44",
            )
            cadastro.salvar_contrato(2026, registro)
            lido = cadastro.como_dataframe(cadastro.carregar_contratos(2026))
        self.assertEqual(lido.loc[0, "processo_contratacao"], "012543/2024-98")
        self.assertEqual(lido.loc[0, "processo_empenho"], "001370/2026-44")

    def test_processo_nao_informado_fica_nulo(self) -> None:
        lido = cadastro.como_dataframe([cadastro.novo_contrato(contrato_numero="1/2026", processo_contratacao="000001/2026-01")])
        self.assertTrue(pd.isna(lido.loc[0, "processo_empenho"]))

    def test_processos_sao_copiados_ao_duplicar_identidade(self) -> None:
        self.assertIn("processo_contratacao", cadastro.CAMPOS_IDENTIDADE)
        self.assertIn("processo_empenho", cadastro.CAMPOS_IDENTIDADE)


class TestDataDaSuspensaoNoCadastro(unittest.TestCase):
    """`data_suspensao` (06/10/2026): dado de execução do exercício, como o status."""

    def test_ida_e_volta_preserva_a_data(self):
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(cadastro, "DIRETORIO_PADRAO", Path(pasta)):
            registro = cadastro.novo_contrato(
                contrato_numero="9/2026", status_contrato="SUSPENSO", data_suspensao=pd.Timestamp("2026-08-01"),
            )
            cadastro.salvar_contrato(2026, registro)
            lido = cadastro.como_dataframe(cadastro.carregar_contratos(2026))
        self.assertEqual(lido.loc[0, "data_suspensao"], pd.Timestamp("2026-08-01"))

    def test_registro_anterior_sem_o_campo_fica_nulo(self):
        legado = cadastro.novo_contrato(contrato_numero="9/2026")
        legado.pop("data_suspensao")
        self.assertTrue(pd.isna(cadastro.como_dataframe([legado]).loc[0, "data_suspensao"]))

    def test_e_de_execucao_nao_de_identidade(self):
        self.assertIn("data_suspensao", cadastro.CAMPOS_EXECUCAO_PADRAO)
        self.assertNotIn("data_suspensao", cadastro.CAMPOS_IDENTIDADE)


class TestAditivosNoCadastro(unittest.TestCase):
    """Aditivos (06/10/2026, spec `2026-10-06-aditivos-contratos-design.md`): lista dentro do contrato,
    datas ISO, `numero` texto; `despesa_mensal` e `vigencia_fim` do contrato nunca sobrescritos."""

    TA1 = {
        "numero": "1º TA", "tipo": "REAJUSTE", "situacao": "ASSINADO", "data_inicio": "2025-07-01",
        "data_assinatura": None, "valor_mensal": 10_400.0, "vigencia_fim": "2026-06-30", "itens": None,
    }
    TA2 = {
        "numero": "002", "tipo": "REAJUSTE", "situacao": "ASSINADO", "data_inicio": "2026-07-01",
        "data_assinatura": "2026-07-05", "valor_mensal": 10_800.0, "vigencia_fim": "2027-06-30", "itens": None,
    }

    def _contrato(self, **campos):
        return cadastro.novo_contrato(
            contrato_numero="14/2022", despesa_mensal=10_000.0, vigencia_fim=pd.Timestamp("2025-06-30"), **campos,
        )

    def test_ida_e_volta_preserva_aditivos_datas_iso_e_numero_texto(self):
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(cadastro, "DIRETORIO_PADRAO", Path(pasta)):
            cadastro.salvar_contrato(2026, self._contrato(aditivos=[self.TA1, self.TA2]))
            registro = cadastro.carregar_contratos(2026)[0]
            lido = cadastro.como_dataframe([registro], 2026)
        self.assertEqual(registro["aditivos"], [self.TA1, self.TA2])  # gravado como veio (ISO, texto)
        self.assertEqual([a.numero for a in lido.loc[0, "aditivos"]], ["1º TA", "002"])
        self.assertEqual(lido.loc[0, "vigencia_fim"], pd.Timestamp("2025-06-30"))  # original intacta
        self.assertEqual(lido.loc[0, "despesa_mensal"], 10_000.0)  # original intacta

    def test_despesa_anual_do_exemplo_do_spec(self):
        lido = cadastro.como_dataframe([self._contrato(aditivos=[self.TA1, self.TA2])], 2026)
        self.assertAlmostEqual(lido.loc[0, "despesa_anual"], 127_200.0)

    def test_colunas_derivadas(self):
        lido = cadastro.como_dataframe([self._contrato(aditivos=[self.TA1, self.TA2])], 2026, hoje=date(2026, 8, 1))
        self.assertEqual(lido.loc[0, "vigencia_fim_efetiva"], pd.Timestamp("2027-06-30"))
        self.assertFalse(lido.loc[0, "tem_aditivo_previsto"])
        self.assertEqual(lido.loc[0, "valor_mensal_vigente"], 10_800.0)  # 2º TA já em vigor em 01/08/2026

    def test_valor_mensal_vigente_acompanha_hoje_limitado_ao_exercicio(self):
        contrato = self._contrato(aditivos=[self.TA1, self.TA2])
        vigente = lambda exercicio, hoje: cadastro.como_dataframe([contrato], exercicio, hoje=hoje).loc[0, "valor_mensal_vigente"]
        self.assertEqual(vigente(2026, date(2026, 3, 1)), 10_400.0)  # só o 1º TA até 30/06/2026
        self.assertEqual(vigente(2026, date(2026, 7, 1)), 10_800.0)
        self.assertEqual(vigente(2025, date(2026, 10, 6)), 10_400.0)  # exercício passado: 31/12/2025
        self.assertEqual(vigente(2099, date(2026, 10, 6)), 10_800.0)  # exercício futuro: 01/01/2099
        self.assertEqual(vigente(2025, date(2025, 3, 1)), 10_000.0)  # antes do 1º TA: o valor original

    def test_registro_sem_aditivos_igual_ao_de_antes_chave_ausente_none_e_lista_vazia(self):
        antes = cadastro.como_dataframe([cadastro.novo_contrato(despesa_mensal=1000.0, meses_no_ano=6)])
        for aditivos in ("ausente", None, []):
            registro = cadastro.novo_contrato(despesa_mensal=1000.0, meses_no_ano=6)
            if aditivos == "ausente":
                registro.pop("aditivos")
            else:
                registro["aditivos"] = aditivos
            lido = cadastro.como_dataframe([registro], 2026)
            self.assertEqual(lido.loc[0, "aditivos"], [], msg=str(aditivos))
            self.assertAlmostEqual(lido.loc[0, "despesa_anual"], antes.loc[0, "despesa_anual"])
            self.assertAlmostEqual(lido.loc[0, "despesa_anual"], 6_000.0)
            self.assertEqual(lido.loc[0, "valor_mensal_vigente"], 1000.0)
            self.assertTrue(pd.isna(lido.loc[0, "vigencia_fim_efetiva"]))

    def test_despesa_anual_nula_continua_nula(self):
        lido = cadastro.como_dataframe([cadastro.novo_contrato(contrato_numero="1/2026")], 2026)
        self.assertTrue(pd.isna(lido.loc[0, "despesa_anual"]))

    def test_sem_exercicio_mantem_a_conta_antiga(self):
        lido = cadastro.como_dataframe([self._contrato(aditivos=[self.TA1, self.TA2])])
        self.assertAlmostEqual(lido.loc[0, "despesa_anual"], 10_000.0 * 12)

    def test_aditivo_previsto_marca_a_coluna(self):
        previsto = {**self.TA2, "situacao": "PREVISTO"}
        lido = cadastro.como_dataframe([self._contrato(aditivos=[self.TA1, previsto])], 2026)
        self.assertTrue(lido.loc[0, "tem_aditivo_previsto"])

    def test_duplicar_exercicio_copia_os_aditivos_e_o_previsto_continua_previsto(self):
        previsto = {**self.TA2, "situacao": "PREVISTO"}
        self.assertIn("aditivos", cadastro.CAMPOS_IDENTIDADE)
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(cadastro, "DIRETORIO_PADRAO", Path(pasta)):
            cadastro.salvar_contrato(2026, self._contrato(aditivos=[self.TA1, previsto]))
            cadastro.duplicar_exercicio(2026, 2027)
            copiado = cadastro.carregar_contratos(2027)[0]
        self.assertEqual(copiado["aditivos"], [self.TA1, previsto])
        self.assertEqual(copiado["aditivos"][1]["situacao"], "PREVISTO")


if __name__ == "__main__":
    unittest.main()
