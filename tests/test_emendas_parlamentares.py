"""Testes da base de acompanhamento e do vínculo de Emendas por PTRES.

A fixture é uma cópia deliberadamente congelada do relatório recebido em
28/08/2026. Atualizações da planilha de trabalho não devem sobrescrevê-la:
uma nova referência exige outro nome, novos totais conferidos e revisão
explícita destes testes.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import openpyxl
import pandas as pd

from src.emendas_parlamentares import (
    ErroPoliticaImportacao,
    ErroVinculoEmenda,
    carregar_emendas_cadastradas,
    compor_relatorio_com_cadastros,
    nova_emenda,
    nova_emenda_acompanhamento,
    salvar,
    validar_anos_importaveis,
    vincular_execucao_emendas,
)
from src.tesouro_emendas_acompanhamento import (
    ErroDadosBase,
    ErroLayoutBase,
    ler_emendas_acompanhamento,
    ler_emendas_acompanhamento_bytes,
    reconciliar_emendas_acompanhamento,
)


CAMINHO_BASE = Path("tests/fixtures/emendas_acompanhamento_2026-08-28.xlsx")
HASH_FIXTURE = "5db888d2f8fa413257bd395caff2d14256360f026274970cff90b3a8d1959672"


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Fixture ausente em {CAMINHO_BASE}")
class TestLeituraEmendasAcompanhamento(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = ler_emendas_acompanhamento(CAMINHO_BASE)
        cls.reconciliacao = reconciliar_emendas_acompanhamento(cls.df)

    def test_fixture_tem_hash_congelado(self):
        hash_atual = hashlib.sha256(CAMINHO_BASE.read_bytes()).hexdigest()
        self.assertEqual(hash_atual, HASH_FIXTURE)

    def test_linhas_emendas_ptres_e_anos(self):
        self.assertEqual(self.reconciliacao["linhas"], 29)
        self.assertEqual(self.reconciliacao["emendas_distintas"], 25)
        self.assertEqual(self.reconciliacao["ptres_distintos"], 27)
        self.assertEqual(
            self.reconciliacao["anos"],
            [2016, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026],
        )

    def test_codigos_ficam_texto_e_linha_ano_ficam_inteiros_nulos(self):
        for coluna in (
            "resultado_primario_cod",
            "ptres",
            "emenda_numero",
            "gnd_cod",
        ):
            self.assertEqual(str(self.df[coluna].dtype), "string")
        self.assertEqual(str(self.df["ano"].dtype), "Int64")
        self.assertEqual(str(self.df["linha_origem"].dtype), "Int64")

    def test_resolve_apenas_mesclagens_reais_de_dados(self):
        linha_20 = self.df[self.df["linha_origem"].eq(20)].iloc[0]
        self.assertEqual(linha_20["ptres"], "217658")
        self.assertEqual(linha_20["emenda_numero"], "202338130007")
        self.assertEqual(linha_20["gnd_cod"], "3")
        self.assertEqual(linha_20["dotacao_atualizada"], 0)

        linha_24 = self.df[self.df["linha_origem"].eq(24)].iloc[0]
        self.assertEqual(linha_24["ptres"], "238855")
        self.assertEqual(linha_24["emenda_numero"], "202438130004")
        self.assertEqual(linha_24["gnd_cod"], "3")

    def test_uma_emenda_pode_ter_mais_de_um_ptres(self):
        emenda = self.df[
            self.df["emenda_numero"].eq("202632990006")
        ]
        self.assertEqual(set(emenda["ptres"]), {"261462", "269202"})

    def test_nulo_zero_e_negativo_permanecem_distintos(self):
        self.assertEqual(
            self.reconciliacao["zeros"],
            {
                "dotacao_atualizada": 4,
                "empenhada_relatorio": 0,
                "liquidada_relatorio": 0,
                "paga_relatorio": 0,
            },
        )
        self.assertEqual(
            self.reconciliacao["nulos"],
            {
                "dotacao_atualizada": 0,
                "empenhada_relatorio": 8,
                "liquidada_relatorio": 19,
                "paga_relatorio": 20,
            },
        )
        self.assertTrue(
            all(valor == 0 for valor in self.reconciliacao["negativos"].values())
        )

    def test_totais_reconciliam_com_a_referencia_manual(self):
        totais = self.reconciliacao["totais"]
        self.assertAlmostEqual(totais["dotacao_atualizada"], 10_525_108.00, places=2)
        self.assertAlmostEqual(totais["empenhada_relatorio"], 7_962_726.79, places=2)
        self.assertAlmostEqual(totais["liquidada_relatorio"], 1_800_329.44, places=2)
        self.assertAlmostEqual(totais["paga_relatorio"], 1_447_991.04, places=2)

    def test_leitura_em_memoria_tem_o_mesmo_resultado(self):
        em_memoria = ler_emendas_acompanhamento_bytes(
            CAMINHO_BASE.read_bytes(), CAMINHO_BASE.name
        )
        pd.testing.assert_frame_equal(self.df, em_memoria)

    def test_layout_alterado_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "layout_alterado.xlsx"
            workbook = openpyxl.load_workbook(CAMINHO_BASE)
            workbook.active["G2"] = "MEDIDA RENOMEADA"
            workbook.save(destino)
            with self.assertRaises(ErroLayoutBase):
                ler_emendas_acompanhamento(destino)

    def test_valor_financeiro_invalido_nao_vira_nulo(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "valor_invalido.xlsx"
            workbook = openpyxl.load_workbook(CAMINHO_BASE)
            workbook.active["G4"] = "VALOR INVÁLIDO"
            workbook.save(destino)
            with self.assertRaises(ErroDadosBase):
                ler_emendas_acompanhamento(destino)


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Fixture ausente em {CAMINHO_BASE}")
class TestPoliticaDeAtualizacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = ler_emendas_acompanhamento(CAMINHO_BASE)

    def test_relatorio_inicial_pode_conter_historico_mas_upload_nao(self):
        self.assertIn(2016, self.df["ano"].tolist())
        with self.assertRaisesRegex(ErroPoliticaImportacao, "2016"):
            validar_anos_importaveis(self.df)

    def test_upload_com_anos_a_partir_de_2026_e_aceito(self):
        validar_anos_importaveis(self.df[self.df["ano"].ge(2026)])

    def test_cadastro_manual_historico_e_bloqueado(self):
        argumentos = {
            "parlamentar": "Pessoa",
            "numero": "202500000001",
            "rp_codigo": "6",
            "rp_descricao": "Emenda Individual",
            "acao_codigo": "20RK",
            "acao_descricao": "Funcionamento",
            "po_codigo": "0000",
            "po_descricao": "PO",
            "objeto": "Objeto",
            "responsavel": "Responsável",
            "situacao": "Não iniciada",
            "proximo": "Empenho",
            "indicado": 0.0,
        }
        with self.assertRaises(ErroPoliticaImportacao):
            nova_emenda(**argumentos, exercicio=2025, ptres="001234")

        atual = nova_emenda(
            **{**argumentos, "numero": "202600000001"},
            exercicio=2026,
            ptres=["001234", "001234", "AB12"],
        )
        self.assertEqual(atual["exercicio"], 2026)
        self.assertEqual(atual["ptres"], ["001234", "AB12"])
        self.assertEqual(atual["indicado"], 0.0)

    def test_cadastro_manual_multi_ptres_preserva_codigos_e_nulo(self):
        cadastro = nova_emenda_acompanhamento(
            exercicio=2026,
            parlamentar="Pessoa",
            numero="00001234",
            rp_codigo="6",
            ptres=["001234", "AB12", "001234"],
            gnd_codigo="03",
            dotacao_atualizada=None,
        )
        self.assertEqual(cadastro["numero"], "00001234")
        self.assertEqual(cadastro["ptres"], ["001234", "AB12"])
        self.assertEqual(cadastro["gnd_codigo"], "03")
        self.assertIsNone(cadastro["dotacao_atualizada"])

    def test_persistencia_manual_e_atomica_e_nao_sobrescreve_id(self):
        cadastro = nova_emenda_acompanhamento(
            exercicio=2026,
            parlamentar="Pessoa",
            numero="202600000001",
            rp_codigo="6",
            ptres=["001234"],
            gnd_codigo="4",
            dotacao_atualizada=0.0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            caminho = salvar(cadastro, tmp)
            self.assertTrue(caminho.exists())
            self.assertEqual(carregar_emendas_cadastradas(tmp), [cadastro])
            with self.assertRaises(FileExistsError):
                salvar(cadastro, tmp)

    def test_relatorio_oficial_prevalece_sem_apagar_cadastro_sobreposto(self):
        cadastro = nova_emenda_acompanhamento(
            exercicio=2026,
            parlamentar="CARLOS EDUARDO GOMES DA SILVA",
            numero="202632990006",
            rp_codigo="6",
            ptres=["269202"],
            gnd_codigo="4",
            dotacao_atualizada=999.0,
        )
        composicao = compor_relatorio_com_cadastros(self.df, [cadastro])

        self.assertEqual(len(composicao.relatorio), len(self.df))
        self.assertEqual(len(composicao.sobreposicoes), 1)
        oficial = composicao.relatorio[
            composicao.relatorio["ptres"].eq("269202")
        ].iloc[0]
        self.assertEqual(oficial["origem_cadastro"], "relatorio")


def _relatorio_sintetico(linhas: list[dict]) -> pd.DataFrame:
    padrao = {
        "ano": 2026,
        "resultado_primario_cod": "6",
        "emenda_numero": "202600000001",
        "autor_emenda": "AUTOR / EMENDA 1",
        "parlamentar": "AUTOR",
        "ptres": "P1",
        "gnd_cod": "4",
        "linha_origem": 4,
        "dotacao_atualizada": 0.0,
        "empenhada_relatorio": pd.NA,
        "liquidada_relatorio": pd.NA,
        "paga_relatorio": pd.NA,
    }
    return pd.DataFrame([{**padrao, **linha} for linha in linhas])


def _execucao_sintetica(linhas: list[dict]) -> pd.DataFrame:
    padrao = {
        "ano": 2026,
        "resultado_primario_cod": "6",
        "ptres": "P1",
        "empenhada": pd.NA,
        "liquidada": pd.NA,
        "paga": pd.NA,
    }
    registros = [{**padrao, **linha} for linha in linhas]
    return pd.DataFrame(registros, columns=list(padrao))


class TestVinculoComExecucao(unittest.TestCase):
    def test_historico_fica_estatico_e_ano_atual_usa_execucao(self):
        relatorio = _relatorio_sintetico(
            [
                {
                    "ano": 2025,
                    "emenda_numero": "202500000001",
                    "ptres": "H1",
                    "empenhada_relatorio": 60.0,
                    "liquidada_relatorio": 50.0,
                    "paga_relatorio": 40.0,
                },
                {"ptres": "P1", "dotacao_atualizada": 100.0},
                {
                    "ptres": "P2",
                    "gnd_cod": "3",
                    "linha_origem": 5,
                    "dotacao_atualizada": 0.0,
                },
                {
                    "emenda_numero": "202600000002",
                    "autor_emenda": "OUTRO / EMENDA 2",
                    "parlamentar": "OUTRO",
                    "ptres": "P3",
                    "linha_origem": 6,
                    "dotacao_atualizada": 50.0,
                },
            ]
        )
        execucao = _execucao_sintetica(
            [
                {"ano": 2025, "ptres": "H1", "empenhada": 999.0},
                {"ano": 2025, "ptres": "H2", "empenhada": 321.0},
                {"ptres": "P1", "empenhada": 100.0},
                {"ptres": "P1", "liquidada": 80.0, "paga": 70.0},
                {"ptres": "U1", "empenhada": 209.0, "liquidada": 209.0, "paga": 209.0},
            ]
        )

        resultado = vincular_execucao_emendas(relatorio, execucao)

        historica = resultado.emendas[resultado.emendas["ano"].eq(2025)].iloc[0]
        self.assertEqual(historica["empenhada"], 60.0)
        self.assertEqual(historica["origem_valores"], "relatorio_estatico")

        atual = resultado.emendas[
            resultado.emendas["emenda_numero"].eq("202600000001")
        ].iloc[0]
        self.assertEqual(atual["ptres_total"], 2)
        self.assertEqual(atual["ptres_com_execucao"], 1)
        self.assertEqual(atual["empenhada"], 100.0)
        self.assertEqual(atual["liquidada"], 80.0)
        self.assertEqual(atual["paga"], 70.0)
        self.assertEqual(atual["origem_valores"], "execucao_anual_parcial")

        sem_execucao = resultado.ptres_sem_execucao
        self.assertEqual(set(sem_execucao["ptres"]), {"P2", "P3"})
        self.assertTrue(
            sem_execucao.loc[sem_execucao["ptres"].eq("P2"), "dotacao_atualizada"]
            .eq(0)
            .all()
        )
        self.assertEqual(set(resultado.execucao_sem_vinculo["ptres"]), {"U1"})

    def test_ptres_269202_vincula_e_267239_permanece_sem_emenda(self):
        relatorio = ler_emendas_acompanhamento(CAMINHO_BASE)
        execucao = _execucao_sintetica(
            [
                {"ptres": "269202", "empenhada": 1_000_000.0},
                {
                    "ptres": "267239",
                    "empenhada": 209_000.0,
                    "liquidada": 209_000.0,
                    "paga": 209_000.0,
                },
            ]
        )
        resultado = vincular_execucao_emendas(relatorio, execucao)

        emenda = resultado.emendas[
            resultado.emendas["emenda_numero"].eq("202632990006")
        ].iloc[0]
        self.assertEqual(emenda["empenhada"], 1_000_000.0)
        self.assertEqual(emenda["ptres_com_execucao"], 1)
        self.assertEqual(
            set(resultado.execucao_sem_vinculo["ptres"]), {"267239"}
        )

    def test_ptres_atribuido_a_duas_emendas_e_bloqueado(self):
        relatorio = _relatorio_sintetico(
            [
                {"ptres": "P1"},
                {
                    "emenda_numero": "202600000002",
                    "autor_emenda": "OUTRO / EMENDA 2",
                    "parlamentar": "OUTRO",
                    "ptres": "P1",
                    "linha_origem": 5,
                },
            ]
        )
        with self.assertRaisesRegex(ErroVinculoEmenda, "PTRES"):
            vincular_execucao_emendas(relatorio, _execucao_sintetica([]))


if __name__ == "__main__":
    unittest.main()
