"""Testes de `src/limite_empenho_remanejamentos.py` — remanejamento temporário de limite de
empenho entre IDUSOs (pedido explícito do usuário, 28/09/2026), com registro em disco e
possibilidade de desfazer."""

from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from src.limite_empenho_remanejamentos import (
    RemanejamentoInvalido,
    carregar_remanejamentos,
    desfazer_remanejamento,
    limite_por_iduso_com_remanejamentos,
    registrar_remanejamento,
    remanejamentos_ativos,
)


def _resultado(*linhas: tuple[str, float | None, float]) -> pd.DataFrame:
    """Linhas no formato de `saldo_disponivel_a_empenhar`: (iduso, limite_liberado, empenhada)."""

    registros = []
    for iduso, limite, empenhada in linhas:
        registros.append(
            {
                "iduso_cod": iduso,
                "iduso_desc": f"IDUSO {iduso}",
                "limite_liberado": limite,
                "empenhada": empenhada,
                "saldo_disponivel": None if limite is None else limite - empenhada,
            }
        )
    dataframe = pd.DataFrame(registros)
    for coluna in ("limite_liberado", "empenhada", "saldo_disponivel"):
        dataframe[coluna] = dataframe[coluna].astype("Float64")
    return dataframe


class PersistenciaRemanejamentosTests(unittest.TestCase):
    def setUp(self) -> None:
        self._diretorio = TemporaryDirectory()
        self.addCleanup(self._diretorio.cleanup)
        self.caminho = Path(self._diretorio.name) / "remanejamentos.json"

    def test_sem_arquivo_devolve_lista_vazia(self):
        self.assertEqual(carregar_remanejamentos(self.caminho), [])

    def test_registrar_grava_e_carrega_com_valor_exato(self):
        registro = registrar_remanejamento(2026, "0", "8", Decimal("1234.56"), "cobrir diárias", caminho=self.caminho)

        carregados = carregar_remanejamentos(self.caminho)
        self.assertEqual(len(carregados), 1)
        self.assertEqual(carregados[0], registro)
        self.assertEqual(carregados[0].valor, Decimal("1234.56"))
        self.assertEqual(carregados[0].iduso_origem, "0")
        self.assertEqual(carregados[0].iduso_destino, "8")
        self.assertIsNone(carregados[0].desfeito_em)

    def test_iduso_preserva_zeros_iniciais_como_identificador(self):
        registrar_remanejamento(2026, "08", "0", Decimal("10"), caminho=self.caminho)
        self.assertEqual(carregar_remanejamentos(self.caminho)[0].iduso_origem, "08")

    def test_rejeita_origem_igual_ao_destino(self):
        with self.assertRaises(RemanejamentoInvalido):
            registrar_remanejamento(2026, "0", "0", Decimal("10"), caminho=self.caminho)
        self.assertFalse(self.caminho.exists())

    def test_rejeita_valor_zero_ou_negativo(self):
        for valor in (Decimal("0"), Decimal("-5")):
            with self.assertRaises(RemanejamentoInvalido):
                registrar_remanejamento(2026, "0", "8", valor, caminho=self.caminho)
        self.assertFalse(self.caminho.exists())

    def test_rejeita_mais_de_duas_casas_decimais(self):
        with self.assertRaises(RemanejamentoInvalido):
            registrar_remanejamento(2026, "0", "8", Decimal("10.001"), caminho=self.caminho)

    def test_desfazer_marca_como_desfeito_sem_apagar_o_registro(self):
        # rastreabilidade: o historico continua no arquivo, so deixa de valer
        registro = registrar_remanejamento(2026, "0", "8", Decimal("100"), caminho=self.caminho)
        desfazer_remanejamento(registro.id, caminho=self.caminho)

        carregados = carregar_remanejamentos(self.caminho)
        self.assertEqual(len(carregados), 1)
        self.assertIsNotNone(carregados[0].desfeito_em)
        self.assertEqual(remanejamentos_ativos(carregados, 2026), [])

    def test_desfazer_id_inexistente_ou_ja_desfeito_lanca_erro(self):
        registro = registrar_remanejamento(2026, "0", "8", Decimal("100"), caminho=self.caminho)
        with self.assertRaises(RemanejamentoInvalido):
            desfazer_remanejamento("nao-existe", caminho=self.caminho)
        desfazer_remanejamento(registro.id, caminho=self.caminho)
        with self.assertRaises(RemanejamentoInvalido):
            desfazer_remanejamento(registro.id, caminho=self.caminho)

    def test_arquivo_corrompido_lanca_erro_em_vez_de_sumir_com_os_remanejamentos(self):
        # diferente da fracao liberada: aqui sao valores financeiros — cair em "lista vazia"
        # faria os limites voltarem ao original sem aviso nenhum.
        self.caminho.write_text("{ nao e json", encoding="utf-8")
        with self.assertRaises(ValueError):
            carregar_remanejamentos(self.caminho)

    def test_registrar_nao_deixa_arquivo_temporario_para_tras(self):
        registrar_remanejamento(2026, "0", "8", Decimal("1"), caminho=self.caminho)
        self.assertEqual(list(self.caminho.parent.iterdir()), [self.caminho])

    def test_valor_gravado_como_texto_no_json(self):
        registrar_remanejamento(2026, "0", "8", Decimal("0.10"), caminho=self.caminho)
        dado = json.loads(self.caminho.read_text(encoding="utf-8"))
        self.assertEqual(dado["remanejamentos"][0]["valor"], "0.10")

    def test_ativos_filtra_pelo_exercicio(self):
        registrar_remanejamento(2025, "0", "8", Decimal("1"), caminho=self.caminho)
        registrar_remanejamento(2026, "8", "0", Decimal("2"), caminho=self.caminho)
        ativos = remanejamentos_ativos(carregar_remanejamentos(self.caminho), 2026)
        self.assertEqual([r.valor for r in ativos], [Decimal("2")])


class LimitePorIdusoComRemanejamentosTests(unittest.TestCase):
    def setUp(self) -> None:
        self._diretorio = TemporaryDirectory()
        self.addCleanup(self._diretorio.cleanup)
        self.caminho = Path(self._diretorio.name) / "remanejamentos.json"

    def _ativos(self):
        return remanejamentos_ativos(carregar_remanejamentos(self.caminho), 2026)

    def test_sem_remanejamento_ajustado_igual_ao_original(self):
        resultado = _resultado(("0", 1000.0, 400.0), ("0", 500.0, 100.0), ("8", 300.0, 350.0))
        tabela = limite_por_iduso_com_remanejamentos(resultado, [])

        linha_0 = tabela.loc[tabela["iduso_cod"] == "0"].iloc[0]
        self.assertAlmostEqual(float(linha_0["limite_liberado"]), 1500.0)
        self.assertAlmostEqual(float(linha_0["remanejado_liquido"]), 0.0)
        self.assertAlmostEqual(float(linha_0["limite_ajustado"]), 1500.0)
        self.assertAlmostEqual(float(linha_0["saldo_ajustado"]), 1000.0)

    def test_remanejamento_move_limite_e_preserva_o_total(self):
        resultado = _resultado(("0", 1000.0, 400.0), ("8", 300.0, 350.0))
        registrar_remanejamento(2026, "0", "8", Decimal("200"), caminho=self.caminho)
        tabela = limite_por_iduso_com_remanejamentos(resultado, self._ativos()).set_index("iduso_cod")

        self.assertAlmostEqual(float(tabela.loc["0", "remanejado_liquido"]), -200.0)
        self.assertAlmostEqual(float(tabela.loc["0", "limite_ajustado"]), 800.0)
        self.assertAlmostEqual(float(tabela.loc["0", "saldo_ajustado"]), 400.0)
        self.assertAlmostEqual(float(tabela.loc["8", "remanejado_liquido"]), 200.0)
        self.assertAlmostEqual(float(tabela.loc["8", "limite_ajustado"]), 500.0)
        self.assertAlmostEqual(float(tabela.loc["8", "saldo_ajustado"]), 150.0)
        # valores originais continuam lado a lado (reconciliacao com a base)
        self.assertAlmostEqual(float(tabela.loc["0", "limite_liberado"]), 1000.0)
        self.assertAlmostEqual(float(tabela["limite_ajustado"].sum()), float(tabela["limite_liberado"].sum()))

    def test_desfazer_volta_ao_limite_original(self):
        resultado = _resultado(("0", 1000.0, 400.0), ("8", 300.0, 350.0))
        registro = registrar_remanejamento(2026, "0", "8", Decimal("200"), caminho=self.caminho)
        desfazer_remanejamento(registro.id, caminho=self.caminho)
        tabela = limite_por_iduso_com_remanejamentos(resultado, self._ativos()).set_index("iduso_cod")
        self.assertAlmostEqual(float(tabela.loc["0", "limite_ajustado"]), 1000.0)
        self.assertAlmostEqual(float(tabela.loc["8", "limite_ajustado"]), 300.0)

    def test_varios_remanejamentos_somam_liquido(self):
        resultado = _resultado(("0", 1000.0, 0.0), ("8", 1000.0, 0.0))
        registrar_remanejamento(2026, "0", "8", Decimal("300"), caminho=self.caminho)
        registrar_remanejamento(2026, "8", "0", Decimal("100"), caminho=self.caminho)
        tabela = limite_por_iduso_com_remanejamentos(resultado, self._ativos()).set_index("iduso_cod")
        self.assertAlmostEqual(float(tabela.loc["0", "remanejado_liquido"]), -200.0)
        self.assertAlmostEqual(float(tabela.loc["8", "remanejado_liquido"]), 200.0)

    def test_iduso_do_remanejamento_ausente_da_base_aparece_sinalizado(self):
        # nao descarta o remanejamento em silencio: o IDUSO aparece com limite base nulo
        resultado = _resultado(("0", 1000.0, 0.0))
        registrar_remanejamento(2026, "0", "9", Decimal("50"), caminho=self.caminho)
        tabela = limite_por_iduso_com_remanejamentos(resultado, self._ativos()).set_index("iduso_cod")

        self.assertIn("9", tabela.index)
        self.assertTrue(bool(tabela.loc["9", "ausente_da_base"]))
        self.assertTrue(pd.isna(tabela.loc["9", "limite_liberado"]))
        self.assertAlmostEqual(float(tabela.loc["9", "remanejado_liquido"]), 50.0)
        self.assertFalse(bool(tabela.loc["0", "ausente_da_base"]))

    def test_limite_base_nulo_mantem_ajustado_nulo(self):
        # nulo != zero: sem Dotacao Atualizada conhecida no grupo inteiro, nao se inventa limite
        resultado = _resultado(("0", None, 0.0), ("8", 100.0, 0.0))
        registrar_remanejamento(2026, "8", "0", Decimal("10"), caminho=self.caminho)
        tabela = limite_por_iduso_com_remanejamentos(resultado, self._ativos()).set_index("iduso_cod")
        self.assertTrue(pd.isna(tabela.loc["0", "limite_ajustado"]))
        self.assertTrue(pd.isna(tabela.loc["0", "saldo_ajustado"]))


if __name__ == "__main__":
    unittest.main()
