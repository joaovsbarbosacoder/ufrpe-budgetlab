"""Testes do leitor de vigência de Contratos (src/contratos_vigencia.py).

Usa uma fixture congelada em `tests/fixtures/` (não a planilha de trabalho em `data/raw/`,
que pode ser substituída em atualizações futuras) — pulado se o arquivo não existir. Todos
os números esperados abaixo foram conferidos contra a extração de 15/08/2026, com
`consolidar_por_contrato(..., hoje=date(2026, 8, 15))` fixo — sem isso, dias/criticidade
mudariam a cada dia que passa e o teste ficaria não determinístico.

IMPORTANTE: ao atualizar a planilha de trabalho em `data/raw/`, NÃO sobrescreva esta fixture
automaticamente — mesma regra das demais fixtures deste diretório (ver AGENTS.md).
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import openpyxl

from src.contratos_vigencia import (
    ErroLayoutBase,
    NOME_ABA,
    classificar_criticidade,
    consolidar_por_contrato,
    ler_contratos_vigencia,
    termos_do_contrato,
)

CAMINHO_BASE = Path("tests/fixtures/contratos_vigencia_2026-08-15.xlsx")
HOJE_FIXO = date(2026, 8, 15)


def _variante_com_coluna_renomeada(caminho: Path, tmp_dir: Path) -> Path:
    """Cópia da planilha real com o cabeçalho "GESTOR" renomeado — simula uma coluna
    esperada sumindo do layout, sem depender de um arquivo de outra base."""

    wb = openpyxl.load_workbook(caminho)
    aba = wb[NOME_ABA]
    for celula in aba[1]:
        if celula.value == "GESTOR":
            celula.value = "GESTOR RENOMEADO"
    destino = tmp_dir / caminho.name
    wb.save(destino)
    return destino


class TestClassificarCriticidade(unittest.TestCase):
    def test_sem_dias_e_indeterminado(self):
        self.assertEqual(classificar_criticidade(None), "Indeterminado")

    def test_dias_negativos_e_vencido(self):
        self.assertEqual(classificar_criticidade(-1), "Vencido")

    def test_ate_60_dias_e_critico(self):
        self.assertEqual(classificar_criticidade(0), "Crítico")
        self.assertEqual(classificar_criticidade(60), "Crítico")

    def test_61_a_120_dias_e_atencao(self):
        self.assertEqual(classificar_criticidade(61), "Atenção")
        self.assertEqual(classificar_criticidade(120), "Atenção")

    def test_acima_de_120_dias_e_no_prazo(self):
        self.assertEqual(classificar_criticidade(121), "No prazo")


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestLeituraContratosVigencia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.termos = ler_contratos_vigencia(CAMINHO_BASE)

    def test_le_uma_linha_por_termo(self):
        self.assertEqual(len(self.termos), 1314)
        for coluna in (
            "numero_contrato", "ano_contrato", "contratado", "cnpj_cpf", "objeto", "termo",
            "finalidade_termo", "data_assinatura", "termo_final", "valor_termo",
            "valor_mensal_planilha", "valor_anual_planilha", "gestor", "email_gestor",
            "garantia_status", "arquivo_pdf", "linha_origem",
        ):
            self.assertIn(coluna, self.termos.columns)

    def test_contratos_distintos(self):
        self.assertEqual(self.termos["numero_contrato"].nunique(), 438)

    def test_layout_diferente_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            variante = _variante_com_coluna_renomeada(CAMINHO_BASE, Path(tmp))
            with self.assertRaises(ErroLayoutBase):
                ler_contratos_vigencia(variante)

    def test_termos_do_contrato_devolve_so_o_historico_daquele_numero(self):
        grupo = termos_do_contrato(self.termos, "19/2005")
        self.assertEqual(len(grupo), 2)
        self.assertTrue((grupo["numero_contrato"] == "19/2005").all())


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestConsolidacaoPorContrato(unittest.TestCase):
    """Confere a consolidação por contrato contra a extração de 15/08/2026, com `hoje` fixo
    para dias/criticidade não mudarem a cada execução."""

    @classmethod
    def setUpClass(cls):
        termos = ler_contratos_vigencia(CAMINHO_BASE)
        cls.contratos = consolidar_por_contrato(termos, hoje=HOJE_FIXO)

    def _linha(self, numero: str):
        return self.contratos[self.contratos["numero_contrato"] == numero].iloc[0]

    def test_uma_linha_por_contrato(self):
        self.assertEqual(len(self.contratos), 438)

    def test_distribuicao_de_criticidade(self):
        contagem = self.contratos["criticidade"].value_counts()
        self.assertEqual(int(contagem.get("Vencido", 0)), 382)
        self.assertEqual(int(contagem.get("No prazo", 0)), 32)
        self.assertEqual(int(contagem.get("Crítico", 0)), 11)
        self.assertEqual(int(contagem.get("Atenção", 0)), 6)
        self.assertEqual(int(contagem.get("Indeterminado", 0)), 7)

    def test_quantidade_de_alertas_por_tipo(self):
        alertas = self.contratos["alertas"]
        self.assertEqual(int(alertas.apply(lambda a: "Sem termo final" in a).sum()), 7)
        self.assertEqual(int(alertas.apply(lambda a: "Sem gestor" in a).sum()), 335)
        self.assertEqual(int(alertas.apply(lambda a: "Sem documento" in a).sum()), 363)
        self.assertEqual(int(alertas.apply(lambda a: "CNPJ/CPF suspeito" in a).sum()), 18)
        self.assertEqual(int(alertas.apply(lambda a: "Sem valor mensal" in a).sum()), 388)
        self.assertEqual(int(alertas.apply(lambda a: "Garantia pendente" in a).sum()), 1)

    def test_contrato_com_varios_termos_usa_o_mais_recente_por_termo_final(self):
        linha = self._linha("19/2005")
        self.assertEqual(linha["qtd_termos"], 2)
        # U+00B0 (degree sign), not U+00BA (ordinal indicator) - source spreadsheet mixes
        # both for the same meaning across rows; this contract's row uses U+00B0 (checked
        # against the 2026-08-15 extract).
        self.assertEqual(linha["termo_atual"], "1\xb0 ADITIVO")
        self.assertEqual(linha["termo_final"], date(2015, 5, 31))
        self.assertEqual(linha["dias_para_vencer"], -4094)
        self.assertEqual(linha["criticidade"], "Vencido")
        self.assertIn("Sem gestor", linha["alertas"])
        self.assertIn("Sem documento", linha["alertas"])
        self.assertIn("Sem valor mensal", linha["alertas"])

    def test_valor_mensal_e_derivado_do_anual_quando_so_um_dos_dois_existe(self):
        comparaveis = self.contratos.dropna(subset=["valor_mensal", "valor_anual"])
        self.assertFalse(comparaveis.empty)
        diferenca = (comparaveis["valor_anual"] - comparaveis["valor_mensal"] * 12).abs()
        # tolerância maior que a usual: valor_mensal/valor_anual nem sempre vêm do mesmo termo
        # quando um dos dois está ausente em alguns termos do histórico (ver docstring do
        # módulo) — aqui só confere que a derivação (Ã·12/Ã—12) não diverge absurdamente.
        self.assertTrue((diferenca <= comparaveis["valor_anual"].abs() * 0.5 + 1).all())


if __name__ == "__main__":
    unittest.main()
