"""Equivalência da montagem compartilhada de Contratos e Bolsas (`src/resultado_orcamentario_fontes.py`)
com o caminho que as páginas faziam antes de a montagem ser extraída (refatoração pura, 08/10/2026).
O caminho "antigo" abaixo é a cópia literal das chamadas que estavam em `app_pages/`; usa as fixtures
congeladas, não `data/raw/`."""

from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from src import bolsas_auxilios as bolsas_src
from src import contratos_continuos as contratos_src
from src.contratos_continuos_cadastro import como_dataframe
from src.execucao_ne_utils import ne_curta as _ne_curta_execucao
from src.execucao_ne_utils import saldo_por_ne
from src.liquidacao_competencia import ler_liquidacao_competencia, liquidado_por_ne, liquidado_por_ne_e_mes
from src.projecao_execucao_bolsas import entrada_relatorio as entrada_projecao_execucao
from src.relatorio_necessidade_empenho import necessidade_por_ne
from src.relatorio_projecao_execucao import BOLSAS_AUXILIOS
from src.relatorio_projecao_execucao import montar_relatorio as montar_relatorio_projecao_execucao
from src.resultado_orcamentario_fontes import projecao_bolsas, projecao_contratos, tabela_bolsas, tabela_contratos
from src.tesouro_execucao_mensal import (
    agregar_por_ne,
    ler_execucao_mensal,
    linha_do_tempo_por_ne,
    primeiro_mes_com_empenho_por_ne,
)

FIXTURES = Path(__file__).parent / "fixtures"
EXERCICIO = 2026
MES_REFERENCIA = 9  # extração da fixture de competência: 11/09/2026


def _cadastro_contratos() -> pd.DataFrame:
    """A planilha congelada passada pelo mesmo `como_dataframe` que a página usa sobre o cadastro nativo
    (traz `meses_no_ano`, `inicio_execucao_mes`, suspensão etc.)."""

    lido = contratos_src.ler_contratos_continuos(FIXTURES / "contratos_continuos_2026-08-13.xlsm")
    lido["id"] = [f"c{i}" for i in range(len(lido))]
    registros = [{k: (None if pd.isna(v) else v) for k, v in r.items()} for r in lido.to_dict("records")]
    return como_dataframe(registros, EXERCICIO)


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        execucao = ler_execucao_mensal(FIXTURES / "execucao_mensal_2026-09-22.xlsx")
        cls.por_ne_execucao = saldo_por_ne(agregar_por_ne(execucao))
        tempo = linha_do_tempo_por_ne(execucao)
        tempo["ne_curta"] = tempo["ne_ccor"].apply(_ne_curta_execucao)
        cls.sugestao = primeiro_mes_com_empenho_por_ne(tempo)
        competencia = ler_liquidacao_competencia(FIXTURES / "liquidacao_competencia_2026-09-11.xlsx")
        totais = liquidado_por_ne(competencia)
        cls.indice = pd.Series(totais.to_numpy(), index=[_ne_curta_execucao(ne) for ne in totais.index])
        cls.competencia = liquidado_por_ne_e_mes(competencia)
        cls.competencia["ne_curta"] = cls.competencia["ne_ccor"].apply(_ne_curta_execucao)


class TestContratos(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cadastro = _cadastro_contratos()
        normalizados = cls.cadastro["contrato_numero"].map(contratos_src.normalizar_numero_contrato).dropna().unique()[:5]
        cls.meses_pagos = pd.DataFrame(
            {
                "contrato_normalizado": normalizados,
                "meses_pagos": list(range(3, 3 + len(normalizados))),
                "ultimo_mes_pago": ["2026-06"] * len(normalizados),
            }
        )

    def _tabela_antiga(self, com_pagos: bool) -> pd.DataFrame:
        dataframe = contratos_src.com_saldo_execucao(self.cadastro, self.por_ne_execucao, self.indice)
        if com_pagos:
            dataframe = contratos_src.com_meses_pagos(dataframe, self.meses_pagos)
        dataframe["valor_empenhado_autoritativo"] = dataframe["valor_empenhado_execucao"].fillna(dataframe["valor_empenhado"])
        dataframe["saldo_autoritativo"] = dataframe["saldo_execucao"].fillna(dataframe["saldo_colado_planilha"])
        dataframe["inicio_execucao_efetivo"] = dataframe["inicio_execucao_mes"].fillna(
            dataframe["ne_curta"].map(self.sugestao)
        )
        return contratos_src.com_efeitos_da_suspensao(dataframe)

    def test_tabela_contratos_igual_ao_caminho_da_pagina(self):
        antiga = self._tabela_antiga(com_pagos=False)
        nova = tabela_contratos(self.cadastro, self.por_ne_execucao, self.indice, self.sugestao)
        pd.testing.assert_frame_equal(nova, antiga)

    def test_tabela_contratos_com_meses_pagos_igual_ao_caminho_da_pagina(self):
        antiga = self._tabela_antiga(com_pagos=True)
        nova = tabela_contratos(
            self.cadastro, self.por_ne_execucao, self.indice, self.sugestao, meses_pagos=self.meses_pagos
        )
        pd.testing.assert_frame_equal(nova, antiga)

    def test_projecao_contratos_igual_ao_caminho_da_pagina(self):
        tabela = self._tabela_antiga(com_pagos=False)
        por_ne, sem_ne_antigo = necessidade_por_ne(tabela, None, EXERCICIO)
        antigo = montar_relatorio_projecao_execucao(
            por_ne, sem_ne_antigo, self.competencia, EXERCICIO, MES_REFERENCIA, {}
        )
        novo, sem_ne = projecao_contratos(tabela, self.competencia, EXERCICIO, MES_REFERENCIA)
        pd.testing.assert_frame_equal(novo.linhas, antigo.linhas)
        pd.testing.assert_frame_equal(novo.mensal, antigo.mensal)
        self.assertEqual(novo.total_necessidade_execucao, antigo.total_necessidade_execucao)
        self.assertFalse(antigo.linhas.empty)
        pd.testing.assert_frame_equal(sem_ne, sem_ne_antigo)

    def test_sem_ne_devolvido(self):
        tabela = self._tabela_antiga(com_pagos=False)
        relatorio, sem_ne = projecao_contratos(tabela, self.competencia, EXERCICIO, MES_REFERENCIA)
        self.assertEqual(len(sem_ne), relatorio.qtd_sem_ne)

    def test_antecessores_sao_repassados(self):
        tabela = self._tabela_antiga(com_pagos=False)
        por_ne, sem_ne = necessidade_por_ne(tabela, None, EXERCICIO)
        nes = por_ne["ne_curta"].tolist()
        antecessores = {nes[0]: nes[1]}
        antigo = montar_relatorio_projecao_execucao(
            por_ne, sem_ne, self.competencia, EXERCICIO, MES_REFERENCIA, antecessores
        )
        novo, _ = projecao_contratos(tabela, self.competencia, EXERCICIO, MES_REFERENCIA, antecessores)
        pd.testing.assert_frame_equal(novo.linhas, antigo.linhas)


class TestBolsas(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cadastro = bolsas_src.ler_bolsas_auxilios(FIXTURES / "bolsas_auxilios_2026-08-13.xlsx")
        if "inicio_execucao_mes" not in cadastro.columns:
            cadastro["inicio_execucao_mes"] = pd.NA
        cadastro["inicio_execucao_mes"] = pd.to_numeric(cadastro["inicio_execucao_mes"], errors="coerce")
        cls.cadastro = cadastro

    def _tabela_antiga(self) -> pd.DataFrame:
        dataframe = bolsas_src.com_saldo_execucao(self.cadastro, self.por_ne_execucao)
        dataframe["valor_empenhado_autoritativo"] = dataframe["valor_empenhado_execucao"].fillna(dataframe["valor_empenhado_tg"])
        dataframe["saldo_autoritativo"] = dataframe["saldo_execucao"].fillna(dataframe["saldo_colado_planilha"])
        dataframe["inicio_execucao_efetivo"] = dataframe["inicio_execucao_mes"].fillna(
            dataframe["ne_curta"].map(self.sugestao)
        )
        return dataframe

    def test_tabela_bolsas_igual_ao_caminho_da_pagina(self):
        pd.testing.assert_frame_equal(
            tabela_bolsas(self.cadastro, self.por_ne_execucao, self.sugestao), self._tabela_antiga()
        )

    def test_projecao_bolsas_igual_ao_caminho_da_pagina(self):
        tabela = self._tabela_antiga()
        por_ne, sem_ne_antigo, custos = entrada_projecao_execucao(tabela, self.competencia, EXERCICIO)
        antigo = montar_relatorio_projecao_execucao(
            por_ne, sem_ne_antigo, self.competencia, EXERCICIO, MES_REFERENCIA, custos=custos, rotulos=BOLSAS_AUXILIOS,
        )
        novo, sem_ne = projecao_bolsas(tabela, self.competencia, EXERCICIO, MES_REFERENCIA)
        pd.testing.assert_frame_equal(novo.linhas, antigo.linhas)
        pd.testing.assert_frame_equal(novo.mensal, antigo.mensal)
        self.assertEqual(novo.total_necessidade_execucao, antigo.total_necessidade_execucao)
        self.assertFalse(antigo.linhas.empty)
        # Correção (08/10/2026): a coluna privada `_necessidade` sai renomeada como `necessidade`.
        pd.testing.assert_frame_equal(sem_ne, sem_ne_antigo.rename(columns={"_necessidade": "necessidade"}))
        self.assertIn("necessidade", sem_ne.columns)
        self.assertNotIn("_necessidade", sem_ne.columns)

    def test_sem_ne_devolvido(self):
        relatorio, sem_ne = projecao_bolsas(self._tabela_antiga(), self.competencia, EXERCICIO, MES_REFERENCIA)
        self.assertEqual(len(sem_ne), relatorio.qtd_sem_ne)


if __name__ == "__main__":
    unittest.main()
