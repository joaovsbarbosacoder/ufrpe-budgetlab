"""Testes de `src/limite_empenho.py` — cota orçamentária discricionária liberada por período.

Usa DataFrames sintéticos mínimos (só as colunas que `saldo_disponivel_a_empenhar` de fato
lê), não a fixture completa de Dotação Anual/Execução Mensal — a função não valida a
integridade estrutural das bases (isso já é responsabilidade de quem monta
`carregar_atual()`), só agrega e cruza colunas já normalizadas.
"""

from __future__ import annotations

import unittest
from fractions import Fraction

import pandas as pd

from src.limite_empenho import (
    FONTE_LIVRE_UNIAO,
    GND_PESSOAL,
    RESULTADO_PRIMARIO_EMENDA,
    RESULTADO_PRIMARIO_OBRIGATORIO,
    saldo_disponivel_a_empenhar,
)

_DIMENSOES_DOTACAO_PADRAO = dict(
    # colunas de rastreabilidade exigidas por `_validate_normalized_dataframe`
    # (`src/dotacao_anual_analysis.py`) — usada internamente por
    # `build_dotacao_anual_subdivision_analysis`, agora reaproveitada por
    # `saldo_disponivel_a_empenhar` (ver docstring de `src/limite_empenho.py`).
    arquivo_origem="teste.xlsx", aba_origem="Base", linha_origem=1, coluna_origem="K",
    item_informacao_origem="Item Informação",
    iduso_codigo="0", iduso_descricao="RECURSOS NAO DESTINADOS",
    resultado_primario_codigo="2", resultado_primario_descricao="PRIMARIO DISCRICIONARIO",
    acao_codigo="20Y0", acao_descricao="ACAO TESTE",
    plano_orcamentario_codigo="0000", plano_orcamentario_descricao="PO TESTE",
    grupo_despesa_codigo="3", grupo_despesa_descricao="OUTRAS DESPESAS CORRENTES",
    fonte_recursos_detalhada_descricao="RECURSOS LIVRES DA UNIAO",
)


def _linha_dotacao(ptres: str, item: str, valor: float | None, **overrides) -> dict:
    linha = dict(
        _DIMENSOES_DOTACAO_PADRAO,
        ano_lancamento=2026,
        ptres_codigo=ptres,
        item_informacao_codigo=item,
        fonte_recursos_detalhada_codigo="1000000000",  # digito exercicio "1" + fonte "000"
        valor_movimento_liquido=valor,
    )
    linha.update(overrides)
    return linha


_DIMENSOES_EXECUCAO_PADRAO = dict(
    iduso_cod="0", iduso_desc="RECURSOS NAO DESTINADOS",
    resultado_primario_cod="2", resultado_primario_desc="PRIMARIO DISCRICIONARIO",
    acao_cod="20Y0", acao_desc="ACAO TESTE",
    po_cod="0000", po_desc="PO TESTE",
    gnd_cod="3", gnd_desc="OUTRAS DESPESAS CORRENTES",
    elemento_cod="39", elemento_desc="OUTROS SERVICOS", natureza_detalhada_desc="X",
    ugr_cod="15239", ugr_desc="UFRPE",
    fonte_cod="000", fonte_desc="RECURSOS LIVRES DA UNIAO",
    # incluídas em 08/10/2026: `valor_empenhado_por_bloco` passou a carregar a Fonte Detalhada
    # (ver src/tesouro_execucao_mensal.py); sem elas o bloco de empenho falha por coluna ausente.
    fonte_recursos_detalhada_cod="1000000000", fonte_recursos_detalhada_desc="RECURSOS LIVRES DA UNIAO",
)


def _linha_execucao(
    ne_ccor: str, ptres: str, ano_mes: int, empenhada: float, tipo_linha: str = "empenho", **overrides
) -> dict:
    linha = dict(
        _DIMENSOES_EXECUCAO_PADRAO,
        ano=ano_mes // 100,
        ano_mes=ano_mes,
        ne_ccor=ne_ccor,
        natureza_detalhada_cod="339039", subitem_cod="1",
        ne_item_cod=None,
        tipo_linha=tipo_linha,
        ptres=ptres,
        empenhada=empenhada,
    )
    linha.update(overrides)
    return linha


class SaldoDisponivelAEmpenharTests(unittest.TestCase):
    def test_linha_normal_bate_com_a_formula_da_planilha_de_referencia(self):
        dotacao = pd.DataFrame([_linha_dotacao("100001", "dotacao_atualizada", 846852.0)])
        execucao = pd.DataFrame([_linha_execucao("NE001", "100001", 202601, 279186.43)])

        resultado = saldo_disponivel_a_empenhar(dotacao, execucao, 2026, Fraction(9, 12))

        self.assertEqual(len(resultado), 1)
        linha = resultado.iloc[0]
        self.assertAlmostEqual(float(linha["dotacao_atualizada"]), 846852.0, places=2)
        self.assertAlmostEqual(float(linha["empenhada"]), 279186.43, places=2)
        # mesmos numeros da planilha de referencia real (COTA 2026, linha da acao 2994/230387)
        self.assertAlmostEqual(float(linha["limite_liberado"]), 635139.0, places=2)
        self.assertAlmostEqual(float(linha["saldo_disponivel"]), 355952.57, places=2)

    def test_combinacao_sem_nenhum_indicador_no_ano_pedido_fica_fora_da_tabela(self):
        # bug real relatado pelo usuario (22/09/2026, com prints do "Limite de Empenho"): a
        # combinacao de dimensoes so tem dado de "dotacao_atualizada" em 2025 (outro ano) —
        # para 2026 ela nao tem NENHUM dos 4 indicadores, so existe na base "de passagem".
        # Painel por Acao (`app_pages/painel_acoes.py`) ja omite isso; esta ferramenta precisa
        # do mesmo comportamento (ver "has_any_indicator" em `_dotacao_atualizada_no_escopo`).
        dotacao = pd.DataFrame(
            [
                _linha_dotacao("100010", "dotacao_atualizada", 5000.0, ano_lancamento=2025),
                _linha_dotacao("100010", "dotacao_atualizada", None, ano_lancamento=2026),
            ]
        )
        execucao = pd.DataFrame([_linha_execucao("NE010", "100010", 202601, 0.0)])

        resultado = saldo_disponivel_a_empenhar(dotacao, execucao, 2026, Fraction(9, 12))
        self.assertTrue(resultado.empty)

    def test_combinacao_com_outro_indicador_preenchido_continua_aparecendo(self):
        # mesma combinacao do teste acima, mas com "dotacao_inicial" preenchido em 2026 (só
        # "dotacao_atualizada" que é nula) — tem QUE aparecer, com dotacao_atualizada nula,
        # porque tem sim informação a mostrar no recorte pedido (mesmo criterio de
        # `has_any_indicator`, não é "só dotacao_atualizada" que conta).
        dotacao = pd.DataFrame(
            [
                _linha_dotacao("100011", "dotacao_inicial", 3000.0, ano_lancamento=2026),
                _linha_dotacao("100011", "dotacao_atualizada", None, ano_lancamento=2026),
            ]
        )
        execucao = pd.DataFrame([_linha_execucao("NE011", "100011", 202601, 0.0)])

        resultado = saldo_disponivel_a_empenhar(dotacao, execucao, 2026, Fraction(9, 12))
        self.assertEqual(len(resultado), 1)
        self.assertTrue(pd.isna(resultado.iloc[0]["dotacao_atualizada"]))

    def test_empenhado_sem_dotacao_fica_fora_da_tabela(self):
        # pedido explicito do usuario (22/09/2026): o universo desta tabela precisa ser o
        # mesmo de "Painel por Ação" (só Dotação) — uma combinação que só existe na Execução
        # não apareceria lá, então também não aparece aqui (a lacuna de carregamento de dado
        # continua sinalizada em Alertas Gerenciais, não é objetivo desta ferramenta repetir).
        dotacao = pd.DataFrame([_linha_dotacao("100001", "dotacao_atualizada", 1000.0)])
        execucao = pd.DataFrame([_linha_execucao("NE002", "200002", 202601, 5000.0)])

        resultado = saldo_disponivel_a_empenhar(dotacao, execucao, 2026, Fraction(9, 12))

        self.assertEqual(len(resultado), 1)
        self.assertNotIn("200002", resultado["ptres"].tolist())

    def test_dotacao_sem_nenhum_empenho_tem_empenhado_zero_nao_nulo(self):
        # aqui SIM zero e o valor certo: a NE simplesmente nao empenhou nada ainda nesse
        # PTRES, e' diferente de "nao sei quanto foi empenhado".
        dotacao = pd.DataFrame([_linha_dotacao("100003", "dotacao_atualizada", 2000.0)])
        execucao = pd.DataFrame([_linha_execucao("NE003", "999999", 202601, 10.0)])  # outro PTRES

        resultado = saldo_disponivel_a_empenhar(dotacao, execucao, 2026, Fraction(9, 12))

        linha = resultado.loc[resultado["ptres"] == "100003"].iloc[0]
        self.assertEqual(float(linha["empenhada"]), 0.0)
        self.assertAlmostEqual(float(linha["limite_liberado"]), 1500.0, places=2)
        self.assertAlmostEqual(float(linha["saldo_disponivel"]), 1500.0, places=2)

    def test_exclui_pessoal_gnd_1(self):
        dotacao = pd.DataFrame([_linha_dotacao("100004", "dotacao_atualizada", 1000.0, grupo_despesa_codigo=GND_PESSOAL)])
        execucao = pd.DataFrame([_linha_execucao("NE004", "100004", 202601, 500.0, gnd_cod=GND_PESSOAL)])

        resultado = saldo_disponivel_a_empenhar(dotacao, execucao, 2026, Fraction(9, 12))
        self.assertTrue(resultado.empty)

    def test_exclui_emenda_resultado_primario_6(self):
        dotacao = pd.DataFrame(
            [_linha_dotacao("100005", "dotacao_atualizada", 1000.0, resultado_primario_codigo=RESULTADO_PRIMARIO_EMENDA)]
        )
        execucao = pd.DataFrame(
            [_linha_execucao("NE005", "100005", 202601, 500.0, resultado_primario_cod=RESULTADO_PRIMARIO_EMENDA)]
        )

        resultado = saldo_disponivel_a_empenhar(dotacao, execucao, 2026, Fraction(9, 12))
        self.assertTrue(resultado.empty)

    def test_exclui_primario_obrigatorio_resultado_primario_1(self):
        # pedido explicito do usuario (22/09/2026), confirmado apos a extracao real revelar
        # linhas RP1 ("PRIMARIO OBRIGATORIO") nesta ferramenta "Discricionaria" — inconsistente
        # com o proprio escopo da pagina, ver docstring de src/limite_empenho.py.
        dotacao = pd.DataFrame(
            [_linha_dotacao("100012", "dotacao_atualizada", 1000.0, resultado_primario_codigo=RESULTADO_PRIMARIO_OBRIGATORIO)]
        )
        execucao = pd.DataFrame(
            [_linha_execucao("NE012", "100012", 202601, 500.0, resultado_primario_cod=RESULTADO_PRIMARIO_OBRIGATORIO)]
        )

        resultado = saldo_disponivel_a_empenhar(dotacao, execucao, 2026, Fraction(9, 12))
        self.assertTrue(resultado.empty)

    def test_exclui_fonte_diferente_de_recursos_livres_da_uniao(self):
        # fonte detalhada "1050000000" -> digitos 1:4 = "050", nao "000".
        dotacao = pd.DataFrame([_linha_dotacao("100006", "dotacao_atualizada", 1000.0, fonte_recursos_detalhada_codigo="1050000000")])
        execucao = pd.DataFrame([_linha_execucao("NE006", "100006", 202601, 500.0, fonte_cod="050")])

        resultado = saldo_disponivel_a_empenhar(dotacao, execucao, 2026, Fraction(9, 12))
        self.assertTrue(resultado.empty)

    def test_fonte_detalhada_com_digito_de_exercicio_diferente_ainda_bate_pelos_3_seguintes(self):
        # "3000000000" (exercicio anterior) tem os mesmos 3 digitos centrais "000" de
        # "1000000000" (exercicio corrente) -> mesmo escopo, confirmado pelo usuario
        # (22/09/2026): o 1o digito e' so indicador de exercicio, nao faz parte da fonte.
        dotacao = pd.DataFrame([_linha_dotacao("100007", "dotacao_atualizada", 1000.0, fonte_recursos_detalhada_codigo="3000000000")])
        execucao = pd.DataFrame([_linha_execucao("NE007", "100007", 202601, 100.0)])

        resultado = saldo_disponivel_a_empenhar(dotacao, execucao, 2026, Fraction(9, 12))
        self.assertEqual(len(resultado), 1)

    def test_item_execucao_nao_conta_como_empenhado(self):
        # linhas tipo_linha="item_execucao" nao tem Empenhada propria (ver
        # valor_empenhado_por_bloco) -- so linhas "empenho" contam.
        dotacao = pd.DataFrame([_linha_dotacao("100008", "dotacao_atualizada", 1000.0)])
        execucao = pd.DataFrame(
            [
                _linha_execucao("NE008", "100008", 202601, 500.0, tipo_linha="empenho"),
                _linha_execucao("NE008", "100008", 202601, 999999.0, tipo_linha="item_execucao"),
            ]
        )

        resultado = saldo_disponivel_a_empenhar(dotacao, execucao, 2026, Fraction(9, 12))
        self.assertEqual(len(resultado), 1)
        self.assertAlmostEqual(float(resultado.iloc[0]["empenhada"]), 500.0, places=2)

    def test_soma_dotacao_de_mais_de_um_ano_lancamento_so_conta_o_ano_pedido(self):
        dotacao = pd.DataFrame(
            [
                _linha_dotacao("100009", "dotacao_atualizada", 1000.0, ano_lancamento=2025),
                _linha_dotacao("100009", "dotacao_atualizada", 2000.0, ano_lancamento=2026),
            ]
        )
        execucao = pd.DataFrame([_linha_execucao("NE009", "100009", 202601, 0.0)])

        resultado = saldo_disponivel_a_empenhar(dotacao, execucao, 2026, Fraction(9, 12))
        self.assertEqual(len(resultado), 1)
        self.assertAlmostEqual(float(resultado.iloc[0]["dotacao_atualizada"]), 2000.0, places=2)

    def test_constantes_de_escopo(self):
        self.assertEqual(GND_PESSOAL, "1")
        self.assertEqual(RESULTADO_PRIMARIO_EMENDA, "6")
        self.assertEqual(RESULTADO_PRIMARIO_OBRIGATORIO, "1")
        self.assertEqual(FONTE_LIVRE_UNIAO, "000")


if __name__ == "__main__":
    unittest.main()
