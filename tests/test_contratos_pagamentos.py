"""Testes do leitor de pagamentos de contratos (src/contratos_pagamentos.py).

Usa uma fixture congelada em `tests/fixtures/` (não a planilha de trabalho em `data/raw/`,
que pode ser substituída em atualizações futuras) — pulado se o arquivo não existir. Todos
os números esperados abaixo foram conferidos contra a extração de 15/08/2026 (8 abas
mensais de 2026, Janeiro a Agosto).

A fixture só tem essas 8 abas — a planilha real de origem tem ~90 (a maioria fora do padrão
"<Mês> - Planilha - <ano>" ou de anos com layout diferente, ver docstring de
`src/contratos_pagamentos.py`), o que fazia a leitura levar dezenas de segundos por causa do
tamanho do arquivo (7,8 MB), não do volume de dado relevante. Reduzida às 8 abas realmente
lidas por `ler_pagamentos(..., ano=2026)`, a fixture cai para ~100 KB e a suíte deste arquivo
roda em segundos, não minutos — mesmos valores, testados e conferidos idênticos antes da
troca.

IMPORTANTE: ao atualizar a planilha de trabalho em `data/raw/`, NÃO sobrescreva esta fixture
automaticamente — mesma regra das demais fixtures deste diretório (ver AGENTS.md).
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import openpyxl

from src.contratos_pagamentos import (
    ErroLayoutBase,
    anos_do_empenho,
    ler_pagamentos,
    mes_competencia_de,
    meses_pagos_por_contrato,
    nes_do_empenho,
    normalizar_numero_contrato,
    serie_por_contrato,
    soma_por_ne,
)

CAMINHO_BASE = Path("tests/fixtures/contratos_pagamentos_2026-08-15.xlsx")


def _planilha_sintetica_sem_empenho(tmp_dir: Path) -> Path:
    """Workbook mínimo, construído do zero (não uma cópia da planilha real de 90 abas — lenta
    demais para carregar/regravar por inteiro, e desnecessária: só o layout de uma aba
    importa aqui) com uma aba "Janeiro - Planilha - 2026" sem a coluna EMPENHO, para
    exercitar a rejeição de layout e o caso de nenhuma aba do ano encontrada."""

    colunas = ["CTO", "COMPETÊNCIA", "EMISSÃO", "NF", "CNPJ", "EMPRESA", "VALOR", "UNIDADE", "PROCESSO"]
    wb = openpyxl.Workbook()
    aba = wb.active
    aba.title = "Janeiro - Planilha - 2026"
    aba.append(colunas)
    destino = tmp_dir / "planilha_sem_empenho.xlsx"
    wb.save(destino)
    return destino


#: lida uma única vez para toda a suíte deste arquivo — a planilha real tem ~90 abas e é
#: lenta para abrir (segundos por leitura); os testes compartilham este resultado em vez de
#: cada `setUpClass` reler o arquivo do zero.
_PAGAMENTOS_COMPARTILHADO: object = None


def _pagamentos_compartilhado():
    global _PAGAMENTOS_COMPARTILHADO
    if _PAGAMENTOS_COMPARTILHADO is None:
        _PAGAMENTOS_COMPARTILHADO = ler_pagamentos(CAMINHO_BASE, ano=2026)
    return _PAGAMENTOS_COMPARTILHADO


class TestNormalizarContrato(unittest.TestCase):
    def test_recupera_numero_a_partir_de_data_reinterpretada(self):
        from src.contratos_pagamentos import _normalizar_contrato

        self.assertEqual(_normalizar_contrato(datetime(2025, 10, 1)), "10/2025")
        self.assertEqual(_normalizar_contrato(datetime(2024, 3, 1)), "3/2024")

    def test_texto_normal_passa_direto(self):
        from src.contratos_pagamentos import _normalizar_contrato

        self.assertEqual(_normalizar_contrato("20/2019"), "20/2019")


class TestAnosDoEmpenho(unittest.TestCase):
    def test_prefixo_de_2_digitos_normaliza_para_4(self):
        self.assertEqual(anos_do_empenho("26NE000094"), {2026})
        self.assertEqual(anos_do_empenho("21NE000733"), {2021})

    def test_prefixo_de_4_digitos_passa_direto(self):
        self.assertEqual(anos_do_empenho("2026NE000130"), {2026})

    def test_celula_com_mais_de_um_empenho_devolve_todos_os_anos(self):
        self.assertEqual(anos_do_empenho("25NE000044/25NE000812"), {2025})
        self.assertEqual(anos_do_empenho("25NE000002 E 25NE000003"), {2025})
        self.assertEqual(anos_do_empenho("25NE000001/26NE000002"), {2025, 2026})

    def test_sem_padrao_ne_reconhecivel_devolve_vazio(self):
        self.assertEqual(anos_do_empenho(None), set())
        self.assertEqual(anos_do_empenho(""), set())
        self.assertEqual(anos_do_empenho("723"), set())


class TestNesDoEmpenho(unittest.TestCase):
    def test_prefixo_de_2_digitos_normaliza_para_4_e_numero_para_6(self):
        self.assertEqual(nes_do_empenho("26NE94"), {"2026NE000094"})
        self.assertEqual(nes_do_empenho("21NE000733"), {"2021NE000733"})

    def test_prefixo_de_4_digitos_passa_direto(self):
        self.assertEqual(nes_do_empenho("2026NE000130"), {"2026NE000130"})

    def test_celula_com_mais_de_um_ne_devolve_todos(self):
        self.assertEqual(
            nes_do_empenho("25NE000044/25NE000812"),
            {"2025NE000044", "2025NE000812"},
        )

    def test_forma_abreviada_sem_ne_explicito_nao_e_reconhecida(self):
        # "812" em "25NE000044/812" não tem "NE" explícito — casamento arriscado, não deve
        # aparecer no conjunto (ver docstring de nes_do_empenho).
        self.assertEqual(nes_do_empenho("25NE000044/812"), {"2025NE000044"})

    def test_sem_padrao_ne_reconhecivel_devolve_vazio(self):
        self.assertEqual(nes_do_empenho(None), set())
        self.assertEqual(nes_do_empenho(""), set())
        self.assertEqual(nes_do_empenho("723"), set())


class TestMesCompetenciaDe(unittest.TestCase):
    def test_nome_de_mes_isolado_usa_ano_do_exercicio(self):
        self.assertEqual(mes_competencia_de("JANEIRO", 2026), datetime(2026, 1, 1))
        self.assertEqual(mes_competencia_de("Março", 2026), datetime(2026, 3, 1))

    def test_data_unica_ja_reconvertida_pelo_excel(self):
        self.assertEqual(mes_competencia_de("2026-12-25 00:00:00", 2026), datetime(2026, 12, 1))

    def test_periodo_inteiro_dentro_de_um_mes(self):
        self.assertEqual(mes_competencia_de("01/02/2026 A 28/02/2026", 2026), datetime(2026, 2, 1))

    def test_periodo_fracionado_usa_o_mes_com_mais_dias(self):
        # 20/02 a 28/02 = 9 dias em fevereiro, 01/03 a 19/03 = 19 dias em março -> março.
        self.assertEqual(mes_competencia_de("20/02/2026 a 19/03/2026", 2026), datetime(2026, 3, 1))

    def test_periodo_com_lado_abreviado_so_o_dia(self):
        # "16 a 31/05/2026": o pandas por vezes lê essa string inteira como uma única
        # data/hora ("16" viraria hora) se checada antes do separador de período — regressão
        # coberta aqui.
        self.assertEqual(mes_competencia_de("16 a 31/05/2026", 2026), datetime(2026, 5, 1))
        self.assertEqual(mes_competencia_de("01 a 15/07/2026", 2026), datetime(2026, 7, 1))

    def test_periodo_sem_ano_em_nenhum_lado_usa_ano_do_exercicio(self):
        self.assertEqual(mes_competencia_de("12/06 A 07/07", 2026), datetime(2026, 6, 1))

    def test_periodo_com_ano_de_2_digitos(self):
        self.assertEqual(mes_competencia_de("01/01/26 A 31/01/26", 2026), datetime(2026, 1, 1))

    def test_sentinela_ou_vazio_devolve_none(self):
        self.assertIsNone(mes_competencia_de("-", 2026))
        self.assertIsNone(mes_competencia_de("", 2026))
        self.assertIsNone(mes_competencia_de(None, 2026))

    def test_texto_livre_demais_devolve_none(self):
        self.assertIsNone(mes_competencia_de("REPACTUAÇÃO JAN A MAI/25", 2026))
        self.assertIsNone(mes_competencia_de("DEA - Reajuste de jun a dez/2025", 2026))


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestLerPagamentos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = _pagamentos_compartilhado()

    def test_le_linhas_e_colunas_esperadas(self):
        self.assertEqual(len(self.df), 380)
        for coluna in (
            "contrato", "competencia_raw", "emissao", "nf", "cnpj", "fornecedor", "valor",
            "empenho", "unidade", "processo", "mes_planilha", "duplicado", "alertas", "status", "anos_empenho",
            "nes_empenho", "mes_pagamento", "mes_competencia",
        ):
            self.assertIn(coluna, self.df.columns)

    def test_np_ns_ted_nao_fazem_parte_do_esquema(self):
        # pedido explícito: "desconsidere a necessidade dos documentos de OB e NP ou
        # congêneres... no máximo, se apegue ao número do empenho".
        for coluna_ausente in ("np", "ns", "ted", "ob"):
            self.assertNotIn(coluna_ausente, self.df.columns)

    def test_oito_meses_de_2026_encontrados(self):
        self.assertEqual(
            sorted(self.df["mes_planilha"].unique(), key=lambda m: self.df[self.df["mes_planilha"] == m]["mes_ordem"].iloc[0]),
            ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto"],
        )

    def test_contratos_distintos(self):
        self.assertEqual(self.df["contrato"].nunique(), 38)

    def test_contrato_recuperado_de_data_corrompida_aparece_no_formato_esperado(self):
        # nenhum valor de contrato deve sobrar como objeto datetime — todos já normalizados
        # para texto "MM/AAAA" por _normalizar_contrato.
        self.assertTrue(self.df["contrato"].apply(lambda v: isinstance(v, str)).all())

    def test_duplicidade_contagem_bate_com_o_levantamento(self):
        self.assertEqual(int(self.df["duplicado"].sum()), 20)

    def test_distribuicao_de_status(self):
        contagem = self.df["status"].value_counts()
        self.assertEqual(int(contagem.get("Publicado", 0)), 357)
        self.assertEqual(int(contagem.get("Duplicado", 0)), 20)
        self.assertEqual(int(contagem.get("Bloqueado", 0)), 2)
        self.assertEqual(int(contagem.get("Alerta", 0)), 1)

    def test_valor_total_nao_duplicado(self):
        total = self.df[~self.df["duplicado"]]["valor"].sum()
        self.assertAlmostEqual(total, 35615409.27, places=1)

    def test_primeira_ocorrencia_de_um_grupo_duplicado_nao_e_marcada_como_duplicada(self):
        duplicados = self.df[self.df["duplicado"]]
        self.assertFalse(duplicados.empty)
        chave = duplicados.iloc[0]["chave_duplicidade"]
        grupo = self.df[self.df["chave_duplicidade"] == chave].sort_values("mes_ordem")
        self.assertFalse(bool(grupo.iloc[0]["duplicado"]))
        self.assertTrue(grupo.iloc[1:]["duplicado"].all())

    def test_layout_diferente_e_rejeitado(self):
        with tempfile.TemporaryDirectory() as tmp:
            variante = _planilha_sintetica_sem_empenho(Path(tmp))
            with self.assertRaises(ErroLayoutBase):
                ler_pagamentos(variante, ano=2026)

    def test_ano_sem_nenhuma_aba_correspondente_falha(self):
        # usa a planilha sintética (1 aba), não a real (90 abas) — mesmo caso de teste, sem
        # pagar o custo de abrir o arquivo grande de novo só pra não achar nada.
        with tempfile.TemporaryDirectory() as tmp:
            variante = _planilha_sintetica_sem_empenho(Path(tmp))
            with self.assertRaises(ErroLayoutBase):
                ler_pagamentos(variante, ano=1999)


class TestSomaPorNe(unittest.TestCase):
    def test_soma_valores_da_mesma_ne_inclusive_duplicados(self):
        import pandas as pd

        df = pd.DataFrame(
            {
                "valor": [100.0, 50.0, 30.0],
                "nes_empenho": [{"2026NE000001"}, {"2026NE000001"}, {"2026NE000002"}],
            }
        )
        resultado = soma_por_ne(df)
        self.assertAlmostEqual(resultado["2026NE000001"], 150.0)
        self.assertAlmostEqual(resultado["2026NE000002"], 30.0)

    def test_linha_com_mais_de_um_ne_fica_fora_da_soma(self):
        import pandas as pd

        df = pd.DataFrame(
            {
                "valor": [100.0, 50.0],
                "nes_empenho": [{"2026NE000001", "2026NE000002"}, {"2026NE000001"}],
            }
        )
        resultado = soma_por_ne(df)
        self.assertAlmostEqual(resultado["2026NE000001"], 50.0)
        self.assertNotIn("2026NE000002", resultado.index)

    def test_sem_nenhum_ne_reconhecido_devolve_serie_vazia(self):
        import pandas as pd

        df = pd.DataFrame({"valor": [100.0], "nes_empenho": [set()]})
        self.assertTrue(soma_por_ne(df).empty)


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestSeriePorContrato(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = _pagamentos_compartilhado()

    def test_serie_ignora_pagamentos_duplicados(self):
        contrato = self.df.dropna(subset=["contrato"])["contrato"].iloc[0]
        serie, media = serie_por_contrato(self.df, contrato)
        reais = self.df[(self.df["contrato"] == contrato) & (~self.df["duplicado"])]
        self.assertEqual(serie["pago"].sum(), reais["valor"].sum())

    def test_contrato_inexistente_devolve_serie_vazia(self):
        serie, media = serie_por_contrato(self.df, "000/0000")
        self.assertTrue(serie.empty)
        self.assertEqual(media, 0.0)


class TestNormalizarNumeroContrato(unittest.TestCase):
    """Casamento com o número de contrato de Contratos Contínuos (`contrato_numero`) — regras
    aprovadas antes da implementação (ver histórico da conversa)."""

    def test_remove_zero_a_esquerda(self):
        self.assertEqual(normalizar_numero_contrato("023/2025"), "23/2025")

    def test_expande_ano_de_2_digitos(self):
        self.assertEqual(normalizar_numero_contrato("01/26"), "1/2026")

    def test_ignora_sufixo_de_unidade(self):
        self.assertEqual(normalizar_numero_contrato("12/2025 - SEDE"), "12/2025")
        self.assertEqual(normalizar_numero_contrato("22/23 -UAST- DEA"), "22/2023")

    def test_sem_numero_fica_sn_maiusculo(self):
        self.assertEqual(normalizar_numero_contrato("sn/2026"), "SN/2026")

    def test_ja_normalizado_passa_sem_alteracao(self):
        self.assertEqual(normalizar_numero_contrato("10/2022"), "10/2022")

    def test_texto_sem_o_padrao_numero_barra_ano_devolve_none(self):
        self.assertIsNone(normalizar_numero_contrato("lixo"))
        self.assertIsNone(normalizar_numero_contrato(None))

    def test_dois_sufixos_diferentes_do_mesmo_numero_normalizam_igual(self):
        # mesmo contrato faturado por mais de uma unidade (pedido explícito: unir, não
        # fragmentar) — as duas formas vistas na origem colapsam na mesma chave.
        self.assertEqual(
            normalizar_numero_contrato("22/2023 - UAST"), normalizar_numero_contrato("22/23 -UAST- DEA")
        )


@unittest.skipUnless(CAMINHO_BASE.exists(), f"Planilha ausente em {CAMINHO_BASE}")
class TestMesesPagosPorContrato(unittest.TestCase):
    """Valores conferidos contra a fixture de 15/08/2026 (ver docstring do módulo)."""

    @classmethod
    def setUpClass(cls):
        cls.df = _pagamentos_compartilhado()
        cls.resultado = meses_pagos_por_contrato(cls.df)

    def test_colunas_esperadas(self):
        self.assertEqual(
            set(self.resultado.columns), {"contrato_normalizado", "meses_pagos", "ultimo_mes_pago"}
        )

    def test_uma_linha_por_contrato_normalizado(self):
        self.assertEqual(
            self.resultado["contrato_normalizado"].nunique(), len(self.resultado)
        )

    def test_contrato_21_2017_pago_nos_8_meses_da_fixture(self):
        linha = self.resultado.set_index("contrato_normalizado").loc["21/2017"]
        self.assertEqual(linha["meses_pagos"], 8)
        self.assertEqual(linha["ultimo_mes_pago"], datetime(2026, 8, 1))

    def test_contrato_20_2024_pago_em_1_mes_so(self):
        linha = self.resultado.set_index("contrato_normalizado").loc["20/2024"]
        self.assertEqual(linha["meses_pagos"], 1)
        self.assertEqual(linha["ultimo_mes_pago"], datetime(2026, 5, 1))

    def test_pagamento_duplicado_nao_conta_como_mes_novo(self):
        # o mesmo lançamento (contrato+NF+valor) repetido numa aba mensal diferente não deve
        # inflar a contagem de meses pagos — mesmo critério de `serie_por_contrato`.
        contrato = self.df[self.df["duplicado"]]["contrato"].iloc[0]
        normalizado = normalizar_numero_contrato(contrato)
        meses_sem_duplicados = self.df[
            (self.df["contrato"] == contrato) & (~self.df["duplicado"])
        ]["mes_pagamento"].nunique()
        linha = self.resultado.set_index("contrato_normalizado").loc[normalizado]
        self.assertEqual(linha["meses_pagos"], meses_sem_duplicados)

    def test_contrato_sem_numero_reconhecivel_fica_fora(self):
        # nenhum contrato_normalizado da fixture é None/NaN
        self.assertFalse(self.resultado["contrato_normalizado"].isna().any())


if __name__ == "__main__":
    unittest.main()
