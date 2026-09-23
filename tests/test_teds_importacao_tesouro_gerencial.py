"""
Testes de `src/teds_importacao_tesouro_gerencial.py` — `execucao_tg` derivada da Execução
Mensal (decisão de 22/09/2026, ver `docs/base_teds.md` seção 6).

Duas camadas: dado sintético mínimo (regra por regra: formato da NE, movimentos do mês,
Decimal exato, rejeição, nulo/zero) e a fixture real congelada da Execução Mensal
(`tests/fixtures/execucao_mensal_2026-09-22.xlsx`), onde o teste que importa é a
RECONCILIAÇÃO: a soma do que vai para `execucao_tg` bate com os totais que a própria base
reconcilia (`src.tesouro_execucao_mensal.reconciliar`).
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.teds_importacao_tesouro_gerencial import montar_execucao_tg
from src.tesouro_execucao_mensal import _DIMENSOES_EXTRA_BLOCO, ler_execucao_mensal, reconciliar

CAMINHO_FIXTURE = Path("tests/fixtures/execucao_mensal_2026-09-22.xlsx")

# `ne_ccor` real: 11 dígitos de órgão/UG/gestão + "AAAANEnnnnnn".
NE_A = "158155152322026NE000422"
NE_B = "158155152322026NE000427"


def _linha_empenho(ne_ccor: str, ano_mes: int, empenhada: float, favorecido: str, descricao: str) -> dict:
    linha = {coluna: None for coluna in _DIMENSOES_EXTRA_BLOCO.values()}
    linha.update(
        ne_ccor=ne_ccor, ano_mes=ano_mes, tipo_linha="empenho", natureza_detalhada_cod="339039",
        subitem_cod="01", ne_item_cod="1", empenhada=empenhada, liquidada=None, paga=None,
        ne_favorecido=favorecido, ne_descricao=descricao,
    )
    return linha


def _linha_item_execucao(ne_ccor: str, ano_mes: int, liquidada: float, paga: float) -> dict:
    linha = {coluna: None for coluna in _DIMENSOES_EXTRA_BLOCO.values()}
    linha.update(
        ne_ccor=ne_ccor, ano_mes=ano_mes, tipo_linha="item_execucao", natureza_detalhada_cod="339039",
        subitem_cod="01", ne_item_cod=None, empenhada=None, liquidada=liquidada, paga=paga,
        ne_favorecido="sentinela", ne_descricao="ITEM EXECUCAO",
    )
    return linha


def _execucao_mensal_sintetica() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _linha_empenho(NE_A, 202608, 388_300.00, "Fornecedor X", "Serviço Y"),
            _linha_item_execucao(NE_A, 202608, 100_000.10, 90_000.00),
            _linha_item_execucao(NE_A, 202609, 50_000.20, 40_000.00),
            _linha_empenho(NE_B, 202609, 154_496.00, "Fornecedor Z", "Serviço W"),
        ]
    )


class MontarExecucaoTgSinteticoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resultado = montar_execucao_tg(_execucao_mensal_sintetica())
        self.por_chave = {
            (r["numero_completo_ne"], r["ano_lancamento"], r["mes_lancamento"]): r
            for r in self.resultado.registros
        }

    def test_uma_linha_por_ne_e_mes_com_numero_no_formato_curto(self) -> None:
        self.assertEqual(self.resultado.rejeitadas, [])
        self.assertEqual(
            set(self.por_chave),
            {("2026NE000422", 2026, 8), ("2026NE000422", 2026, 9), ("2026NE000427", 2026, 9)},
        )

    def test_movimentos_do_mes_ficam_no_proprio_mes_sem_acumular(self) -> None:
        agosto = self.por_chave[("2026NE000422", 2026, 8)]
        setembro = self.por_chave[("2026NE000422", 2026, 9)]
        self.assertEqual((agosto["empenhado"], agosto["liquidado"], agosto["pago"]),
                         (Decimal("388300.00"), Decimal("100000.10"), Decimal("90000.00")))
        # sem linha de empenho em setembro: movimento do mês é zero, não repete o de agosto.
        self.assertEqual((setembro["empenhado"], setembro["liquidado"], setembro["pago"]),
                         (Decimal("0.00"), Decimal("50000.20"), Decimal("40000.00")))

    def test_valores_sao_decimal_exato_em_centavos(self) -> None:
        for registro in self.resultado.registros:
            for campo in ("empenhado", "liquidado", "pago"):
                self.assertIsInstance(registro[campo], Decimal)
                self.assertEqual(registro[campo], registro[campo].quantize(Decimal("0.01")))

    def test_favorecido_e_descricao_vem_das_linhas_de_empenho(self) -> None:
        registro = self.por_chave[("2026NE000422", 2026, 9)]
        self.assertEqual(registro["favorecido"], "Fornecedor X")
        self.assertEqual(registro["descricao"], "Serviço Y")

    def test_linha_origem_preserva_chave_de_reconciliacao(self) -> None:
        origem = self.por_chave[("2026NE000427", 2026, 9)]["linha_origem"]
        self.assertEqual(origem["ne_ccor"], NE_B)
        self.assertEqual(origem["ano_mes"], 202609)

    def test_ne_fora_do_formato_e_rejeitada_nunca_gravada(self) -> None:
        df = _execucao_mensal_sintetica()
        df.loc[len(df)] = _linha_empenho("SEM-FORMATO", 202608, 10.0, "F", "D")

        resultado = montar_execucao_tg(df)

        self.assertEqual(len(resultado.rejeitadas), 1)
        self.assertIn("SEM-FORMATO", resultado.rejeitadas[0].motivo)
        self.assertEqual(len(resultado.registros), 3)

    def test_zero_negativo_de_ponto_flutuante_vira_zero(self) -> None:
        df = pd.DataFrame([_linha_empenho(NE_A, 202608, -0.0, "F", "D")])
        registro = montar_execucao_tg(df).registros[0]
        self.assertEqual(str(registro["empenhado"]), "0.00")

    def test_estorno_negativo_e_preservado_com_sinal(self) -> None:
        df = pd.DataFrame(
            [_linha_empenho(NE_A, 202608, 1000.0, "F", "D"), _linha_item_execucao(NE_A, 202608, -250.0, 0.0)]
        )
        registro = montar_execucao_tg(df).registros[0]
        self.assertEqual(registro["liquidado"], Decimal("-250.00"))

    def test_base_vazia_devolve_resultado_vazio(self) -> None:
        resultado = montar_execucao_tg(_execucao_mensal_sintetica().iloc[0:0])
        self.assertEqual((resultado.registros, resultado.rejeitadas), ([], []))


@unittest.skipUnless(CAMINHO_FIXTURE.exists(), f"Fixture ausente em {CAMINHO_FIXTURE}")
class MontarExecucaoTgReconciliaComAExecucaoMensalTests(unittest.TestCase):
    """O que vai para `execucao_tg` tem que somar exatamente o que a base reconcilia — nenhum
    valor criado, perdido ou duplicado na remontagem por NE × mês."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.base = ler_execucao_mensal(CAMINHO_FIXTURE)
        cls.resultado = montar_execucao_tg(cls.base)
        cls.totais = reconciliar(cls.base)["totais"]

    def test_nenhuma_ne_da_base_real_e_rejeitada(self) -> None:
        self.assertEqual(self.resultado.rejeitadas, [])

    def test_somas_batem_com_os_totais_reconciliados_da_base(self) -> None:
        for campo, medida in (("empenhado", "empenhada"), ("liquidado", "liquidada"), ("pago", "paga")):
            soma = sum((r[campo] for r in self.resultado.registros), start=Decimal("0"))
            self.assertAlmostEqual(float(soma), self.totais[medida], delta=0.05, msg=campo)

    def test_chave_natural_e_unica(self) -> None:
        chaves = [(r["numero_completo_ne"], r["ano_lancamento"], r["mes_lancamento"]) for r in self.resultado.registros]
        self.assertEqual(len(chaves), len(set(chaves)))

    def test_toda_ne_da_base_aparece(self) -> None:
        ne_da_base = set(self.base["ne_ccor"].unique())
        ne_montadas = {r["linha_origem"]["ne_ccor"] for r in self.resultado.registros}
        self.assertEqual(ne_da_base, ne_montadas)


if __name__ == "__main__":
    unittest.main()
