"""Testes da especificação de importação versionada da Dotação Anual
(src/importacao_dotacao.py).

Não repete a suíte de reconhecimento/normalização (`test_tesouro_dotacao_anual.py`) nem a de
agregação (`test_dotacao_anual_analysis.py`) — reaproveita as mesmas fixtures delas para
provar que a ADAPTAÇÃO ao núcleo genérico (leitura por caminho, reconciliação em dict,
validação em RelatorioValidacao, manifesto, delta) funciona de ponta a ponta, com os nomes de
medida REAIS da Dotação Anual (dotacao_inicial/suplementar/atualizada/cancelada_remanejada) —
nunca empenhada/liquidada/paga da Execução.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.importacao_dotacao import (
    MEDIDAS,
    Manifesto,
    historico,
    importar,
    ler_dotacao_anual,
    reconciliar_dotacao_anual,
    validar_dotacao_anual,
)
from tests.test_tesouro_dotacao_anual import (
    workbook_bytes,
    write_invalid_sheet,
    write_recognized_sheet,
    write_recognized_sheet_2025,
)


def _escrever_workbook(diretorio: Path, nome: str, builder) -> Path:
    caminho = diretorio / nome
    caminho.write_bytes(workbook_bytes(builder))
    return caminho


class MedidasReaisTests(unittest.TestCase):
    def test_medidas_sao_as_da_dotacao_nao_as_da_execucao(self) -> None:
        self.assertEqual(
            set(MEDIDAS),
            {
                "dotacao_inicial",
                "dotacao_suplementar",
                "dotacao_atualizada",
                "dotacao_cancelada_remanejada",
            },
        )
        self.assertFalse(set(MEDIDAS) & {"empenhada", "liquidada", "paga"})


class LerDotacaoAnualTests(unittest.TestCase):
    def test_le_arquivo_valido_do_caminho(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _escrever_workbook(Path(tmp), "dotacao.xlsx", write_recognized_sheet)
            leitura = ler_dotacao_anual(caminho)

            self.assertTrue(leitura.workbook.integrity_approved)
            self.assertEqual(leitura.workbook.recognized_sheets, ["Base"])
            self.assertEqual(len(leitura.conteudo), caminho.stat().st_size)


class ReconciliarDotacaoAnualTests(unittest.TestCase):
    def test_totais_e_totais_por_ano_com_nomes_reais_de_medida(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _escrever_workbook(Path(tmp), "dotacao.xlsx", write_recognized_sheet)
            leitura = ler_dotacao_anual(caminho)
            r = reconciliar_dotacao_anual(leitura)

            self.assertEqual(r["anos"], [2024])
            self.assertEqual(r["totais"]["dotacao_inicial"], 1000.0)
            self.assertEqual(r["totais"]["dotacao_atualizada"], 1200.0)
            self.assertIsNone(r["totais"]["dotacao_suplementar"])  # nunca apareceu na fixture
            self.assertIsNone(r["totais"]["dotacao_cancelada_remanejada"])

            self.assertEqual(r["totais_por_ano"][2024]["dotacao_inicial"], 1000.0)
            self.assertEqual(r["totais_por_ano"][2024]["dotacao_atualizada"], 1200.0)

            self.assertEqual(r["abas_reconhecidas"], 1)
            self.assertEqual(r["linhas_normalizadas"], 6)


class ValidarDotacaoAnualTests(unittest.TestCase):
    def test_aprova_arquivo_valido(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _escrever_workbook(Path(tmp), "dotacao.xlsx", write_recognized_sheet)
            leitura = ler_dotacao_anual(caminho)
            relatorio = validar_dotacao_anual(leitura)

            self.assertTrue(relatorio.ok, relatorio.erros)
            self.assertEqual(relatorio.erros, [])

    def test_bloqueia_arquivo_com_valor_nao_numerico(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _escrever_workbook(Path(tmp), "dotacao_invalida.xlsx", write_invalid_sheet)
            leitura = ler_dotacao_anual(caminho)
            relatorio = validar_dotacao_anual(leitura)

            self.assertFalse(relatorio.ok)
            self.assertTrue(relatorio.erros)


class ImportarDotacaoAnualTests(unittest.TestCase):
    def test_primeira_importacao_registra_manifesto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _escrever_workbook(Path(tmp), "dotacao.xlsx", write_recognized_sheet)
            res = importar(caminho, tmp)

            self.assertTrue(res.ok, res.validacao.erros)
            self.assertFalse(res.delta.houve_anterior)
            self.assertIsNotNone(res.caminho_manifesto)
            self.assertEqual(len(historico(tmp)), 1)
            self.assertEqual(Manifesto.atual(tmp).sha256, res.manifesto.sha256)
            self.assertEqual(res.manifesto.totais_por_ano["2024"]["dotacao_inicial"], 1000.0)

    def test_reimportar_o_mesmo_arquivo_e_idempotente(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _escrever_workbook(Path(tmp), "dotacao.xlsx", write_recognized_sheet)
            importar(caminho, tmp)
            segunda = importar(caminho, tmp)

            self.assertTrue(segunda.delta.mesma_extracao)
            self.assertIsNone(segunda.caminho_manifesto)
            self.assertEqual(len(historico(tmp)), 1)

    def test_ano_novo_e_avanco_sao_detectados_com_medidas_da_dotacao(self) -> None:
        # Prova o pipeline inteiro (importar -> gerar_manifesto -> comparar) com os nomes
        # reais da Dotação, não com medidas genéricas de teste.
        with tempfile.TemporaryDirectory() as tmp:
            caminho_2024 = _escrever_workbook(Path(tmp), "dotacao_2024.xlsx", write_recognized_sheet)
            importar(caminho_2024, tmp)

            caminho_2025 = _escrever_workbook(
                Path(tmp), "dotacao_2025.xlsx", write_recognized_sheet_2025
            )
            segunda = importar(caminho_2025, tmp)

            self.assertEqual(segunda.delta.anos_novos, [2025])
            self.assertEqual(segunda.delta.anos_removidos, [2024])  # substituição total
            self.assertEqual(
                segunda.manifesto.totais_por_ano["2025"]["dotacao_atualizada"], 5000.0
            )

    def test_extracao_invalida_nao_grava_manifesto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _escrever_workbook(Path(tmp), "dotacao_invalida.xlsx", write_invalid_sheet)
            res = importar(caminho, tmp)

            self.assertFalse(res.ok)
            self.assertIsNone(res.caminho_manifesto)
            self.assertIsNone(Manifesto.atual(tmp))


if __name__ == "__main__":
    unittest.main(verbosity=2)
