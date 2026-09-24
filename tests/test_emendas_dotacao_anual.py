"""Dotação Atualizada da Dotação Anual por (ano, RP, PTRES) ao lado da Dotação do relatório
ou cadastro de Emendas — regras 1-5 da proposta aprovada (ver
`docs/base_emendas_acompanhamento.md`, seção "Dotação Anual por PTRES").

Dados sintéticos: as regras são de cruzamento e não dependem de nenhuma extração real.
"""

from __future__ import annotations

import unittest

import pandas as pd

from src.emendas_parlamentares import (
    ErroVinculoEmenda,
    agregar_dotacao_por_ptres,
    divergencias_dotacao,
    vincular_execucao_emendas,
)


def _relatorio(linhas: list[dict]) -> pd.DataFrame:
    padrao = {
        "arquivo_origem": "relatorio.xlsx", "aba_origem": "Emendas", "linha_origem": 4,
        "resultado_primario_cod": "6", "ptres": "111111",
        "emenda_numero": "202600000001", "autor_emenda": "PARL / Emenda 1",
        "parlamentar": "PARL", "gnd_cod": "4", "ano": 2026,
        "dotacao_atualizada": 100.0,
        "empenhada_relatorio": pd.NA, "liquidada_relatorio": pd.NA, "paga_relatorio": pd.NA,
    }
    return pd.DataFrame([{**padrao, **linha} for linha in linhas])


def _execucao(linhas: list[dict] | None = None) -> pd.DataFrame:
    padrao = {"ano": 2026, "resultado_primario_cod": "6", "ptres": "111111",
              "empenhada": 10.0, "liquidada": 0.0, "paga": pd.NA}
    return pd.DataFrame([{**padrao, **linha} for linha in (linhas or [{}])])


def _dotacao(linhas: list[dict]) -> pd.DataFrame:
    padrao = {"ano_lancamento": 2026, "resultado_primario_codigo": "6",
              "ptres_codigo": "111111", "item_informacao_codigo": "dotacao_atualizada",
              "valor_movimento_liquido": 100.0}
    return pd.DataFrame([{**padrao, **linha} for linha in linhas])


class AgregarDotacaoPorPtresTests(unittest.TestCase):
    def test_soma_so_dotacao_atualizada_e_so_rps_de_emenda(self) -> None:
        agregado = agregar_dotacao_por_ptres(_dotacao([
            {"valor_movimento_liquido": 60.0},
            {"valor_movimento_liquido": 40.0},                                   # mesmo PTRES
            {"item_informacao_codigo": "dotacao_inicial", "valor_movimento_liquido": 999.0},
            {"resultado_primario_codigo": "2", "valor_movimento_liquido": 777.0},  # não é emenda
        ]))
        self.assertEqual(len(agregado), 1)
        self.assertEqual(float(agregado.loc[0, "dotacao_anual_ptres"]), 100.0)

    def test_nulo_nao_vira_zero_e_zero_nao_vira_nulo(self) -> None:
        agregado = agregar_dotacao_por_ptres(_dotacao([
            {"ptres_codigo": "000001", "valor_movimento_liquido": pd.NA},
            {"ptres_codigo": "000002", "valor_movimento_liquido": 0.0},
            {"ptres_codigo": "000003", "valor_movimento_liquido": -50.0},
        ])).set_index("ptres")["dotacao_anual_ptres"]
        self.assertTrue(pd.isna(agregado["000001"]))
        self.assertEqual(float(agregado["000002"]), 0.0)
        self.assertEqual(float(agregado["000003"]), -50.0)   # negativo preservado

    def test_ptres_preserva_zeros_a_esquerda(self) -> None:
        agregado = agregar_dotacao_por_ptres(_dotacao([{"ptres_codigo": "007890"}]))
        self.assertEqual(agregado.loc[0, "ptres"], "007890")

    def test_linha_sem_chave_nao_e_descartada_em_silencio(self) -> None:
        with self.assertRaises(ErroVinculoEmenda):
            agregar_dotacao_por_ptres(_dotacao([{"ptres_codigo": pd.NA}]))


class VincularComDotacaoTests(unittest.TestCase):
    def test_sem_dotacao_nenhuma_coluna_nova_e_criada(self) -> None:
        resultado = vincular_execucao_emendas(_relatorio([{}]), _execucao())
        self.assertNotIn("dotacao_anual_ptres", resultado.vinculos.columns)
        self.assertNotIn("dotacao_anual_ptres", resultado.emendas.columns)

    def test_ptres_do_cadastro_recebe_a_dotacao_anual_sem_digitar_e_sem_substituir(self) -> None:
        resultado = vincular_execucao_emendas(
            _relatorio([{"dotacao_atualizada": 100.0}]), _execucao(),
            dotacao=_dotacao([{"valor_movimento_liquido": 250.0}]),
        )
        vinculo = resultado.vinculos.iloc[0]
        self.assertEqual(float(vinculo["dotacao_anual_ptres"]), 250.0)
        self.assertEqual(float(vinculo["dotacao_atualizada"]), 100.0)   # informado, intacto
        self.assertEqual(float(resultado.emendas.iloc[0]["dotacao_anual_ptres"]), 250.0)

    def test_cadastro_sem_dotacao_informada_continua_nulo_e_recebe_a_da_dotacao_anual(self) -> None:
        resultado = vincular_execucao_emendas(
            _relatorio([{"dotacao_atualizada": pd.NA}]), _execucao(),
            dotacao=_dotacao([{"valor_movimento_liquido": 250.0}]),
        )
        vinculo = resultado.vinculos.iloc[0]
        self.assertTrue(pd.isna(vinculo["dotacao_atualizada"]))
        self.assertEqual(float(vinculo["dotacao_anual_ptres"]), 250.0)
        self.assertTrue(pd.isna(vinculo["diferenca_dotacao"]))
        self.assertFalse(bool(vinculo["dotacao_divergente"]))   # só um lado: nada a comparar

    def test_ptres_sem_dotacao_correspondente_fica_nulo_nunca_zero(self) -> None:
        resultado = vincular_execucao_emendas(
            _relatorio([{}]), _execucao(),
            dotacao=_dotacao([{"ptres_codigo": "999999"}]),
        )
        vinculo = resultado.vinculos.iloc[0]
        self.assertTrue(pd.isna(vinculo["dotacao_anual_ptres"]))
        self.assertEqual(int(resultado.emendas.iloc[0]["ptres_com_dotacao_anual"]), 0)

    def test_divergencia_e_sinalizada_sem_alterar_nenhum_valor(self) -> None:
        resultado = vincular_execucao_emendas(
            _relatorio([{"dotacao_atualizada": 100.0}]), _execucao(),
            dotacao=_dotacao([{"valor_movimento_liquido": 250.0}]),
        )
        vinculo = resultado.vinculos.iloc[0]
        self.assertTrue(bool(vinculo["dotacao_divergente"]))
        self.assertEqual(float(vinculo["diferenca_dotacao"]), 150.0)
        self.assertTrue(bool(resultado.emendas.iloc[0]["dotacao_divergente"]))

    def test_diferenca_dentro_da_tolerancia_nao_e_divergencia(self) -> None:
        resultado = vincular_execucao_emendas(
            _relatorio([{"dotacao_atualizada": 100.0}]), _execucao(),
            dotacao=_dotacao([{"valor_movimento_liquido": 100.01}]),
        )
        self.assertFalse(bool(resultado.vinculos.iloc[0]["dotacao_divergente"]))

    def test_exercicio_historico_nao_recebe_dotacao_anual(self) -> None:
        resultado = vincular_execucao_emendas(
            _relatorio([{"ano": 2025}]), _execucao([{"ano": 2025}]),
            dotacao=_dotacao([{"ano_lancamento": 2025, "valor_movimento_liquido": 250.0}]),
        )
        vinculo = resultado.vinculos.iloc[0]
        self.assertTrue(pd.isna(vinculo["dotacao_anual_ptres"]))
        self.assertFalse(bool(vinculo["dotacao_divergente"]))
        self.assertEqual(float(vinculo["dotacao_atualizada"]), 100.0)

    def test_ptres_compartilhado_por_duas_emendas_continua_barrado_sem_dividir_valor(self) -> None:
        relatorio = _relatorio([
            {"emenda_numero": "202600000001", "autor_emenda": "A / 1", "linha_origem": 4},
            {"emenda_numero": "202600000002", "autor_emenda": "B / 2", "linha_origem": 5,
             "parlamentar": "B"},
        ])
        with self.assertRaises(ErroVinculoEmenda):
            vincular_execucao_emendas(
                relatorio, _execucao(), dotacao=_dotacao([{"valor_movimento_liquido": 250.0}])
            )

    def test_execucao_e_demais_colunas_nao_mudam_ao_passar_dotacao(self) -> None:
        relatorio, execucao = _relatorio([{}]), _execucao()
        sem = vincular_execucao_emendas(relatorio, execucao).vinculos
        com = vincular_execucao_emendas(
            relatorio, execucao, dotacao=_dotacao([{"valor_movimento_liquido": 250.0}])
        ).vinculos
        pd.testing.assert_frame_equal(com[list(sem.columns)], sem)


class DivergenciasDotacaoTests(unittest.TestCase):
    def test_lista_so_os_ptres_divergentes_com_os_dois_valores_e_a_diferenca(self) -> None:
        relatorio = _relatorio([
            {"ptres": "111111", "dotacao_atualizada": 100.0, "linha_origem": 4},
            {"ptres": "222222", "dotacao_atualizada": 50.0, "linha_origem": 5},
        ])
        dotacao = _dotacao([
            {"ptres_codigo": "111111", "valor_movimento_liquido": 250.0},   # diverge
            {"ptres_codigo": "222222", "valor_movimento_liquido": 50.0},    # confere
        ])
        execucao = _execucao([{"ptres": "111111"}, {"ptres": "222222"}])
        divergencias = divergencias_dotacao(
            vincular_execucao_emendas(relatorio, execucao, dotacao=dotacao).vinculos
        )
        self.assertEqual(divergencias["ptres"].tolist(), ["111111"])
        self.assertEqual(float(divergencias.loc[0, "dotacao_atualizada"]), 100.0)
        self.assertEqual(float(divergencias.loc[0, "dotacao_anual_ptres"]), 250.0)
        self.assertEqual(float(divergencias.loc[0, "diferenca_dotacao"]), 150.0)

    def test_sem_divergencia_ou_sem_dotacao_ligada_devolve_vazio(self) -> None:
        confere = vincular_execucao_emendas(
            _relatorio([{"dotacao_atualizada": 100.0}]), _execucao(),
            dotacao=_dotacao([{"valor_movimento_liquido": 100.0}]),
        ).vinculos
        self.assertTrue(divergencias_dotacao(confere).empty)
        sem_dotacao = vincular_execucao_emendas(_relatorio([{}]), _execucao()).vinculos
        self.assertTrue(divergencias_dotacao(sem_dotacao).empty)

    def test_nao_altera_o_dataframe_de_entrada(self) -> None:
        vinculos = vincular_execucao_emendas(
            _relatorio([{"dotacao_atualizada": 100.0}]), _execucao(),
            dotacao=_dotacao([{"valor_movimento_liquido": 250.0}]),
        ).vinculos
        antes = vinculos.copy(deep=True)
        divergencias_dotacao(vinculos)
        pd.testing.assert_frame_equal(vinculos, antes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
