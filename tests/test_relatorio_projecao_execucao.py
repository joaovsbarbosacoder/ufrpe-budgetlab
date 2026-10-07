"""Testes do relatório separado "Projeção pela Execução" (`src/relatorio_projecao_execucao.py`).
Dados sintéticos; valores esperados calculados à mão em cada caso. O relatório só LÊ a saída de
`necessidade_por_ne` — nenhum outro relatório ou quadro da página muda (ver docstring do módulo)."""

from __future__ import annotations

import unittest
from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

from src.relatorio_necessidade_empenho import necessidade_por_ne
from src.relatorio_projecao_execucao import (
    ORIGEM_EXECUCAO,
    ORIGEM_HERDADO,
    ORIGEM_SEM_HISTORICO,
    TIPO_PROJETADO,
    TIPO_RESTANTE_ABERTO,
    ContextoProjecaoExecucao,
    FatorExecucao,
    fator_de_execucao,
    gerar_pdf,
    gerar_xlsx,
    herdar_fator,
    montar_relatorio,
    projetar_meses,
    ultimo_mes_fechado,
)

CUSTO_1000 = [1000.0] * 12


class TestFatorDeExecucao(unittest.TestCase):
    def test_ultimo_mes_fechado(self):
        self.assertEqual(ultimo_mes_fechado(10), 7)  # extração em outubro: fechados até julho

    def test_execucao_constante_peso_1(self):
        # 0,90 em todos os meses: variância 0 → peso 1, fator = execução observada
        fator = fator_de_execucao({m: 900.0 for m in range(1, 8)}, CUSTO_1000, 7)
        self.assertEqual(fator.origem, ORIGEM_EXECUCAO)
        self.assertEqual(fator.meses_usados, (2, 3, 4, 5, 6, 7))  # janela: últimos 6 fechados
        self.assertAlmostEqual(fator.peso, 1.0)
        self.assertAlmostEqual(fator.fator, 0.9)

    def test_peso_cai_com_a_oscilacao(self):
        # razões 0,6/1,0/0,8/1,0/0,6/0,8 → observada 4800/6000 = 0,8; média 0,8;
        # variância amostral = (0,04+0,04+0+0,04+0,04+0)/5 = 0,032; peso = 6·0,01/(0,06+0,032) = 0,652174;
        # fator = 1 − 0,2 × 0,652174 = 0,869565
        valores = {2: 600.0, 3: 1000.0, 4: 800.0, 5: 1000.0, 6: 600.0, 7: 800.0}
        fator = fator_de_execucao(valores, CUSTO_1000, 7)
        self.assertAlmostEqual(fator.execucao_observada, 0.8)
        self.assertAlmostEqual(fator.peso, 0.06 / 0.092, places=6)
        self.assertAlmostEqual(fator.fator, 1 - 0.2 * 0.06 / 0.092, places=6)

    def test_meses_abertos_e_custo_zero_nao_entram(self):
        # ago/set (abertos) e o mês sem custo ficam de fora; 2 meses fechados → sem histórico
        custo = [0.0] * 4 + [1000.0] * 8
        fator = fator_de_execucao({4: 500.0, 6: 900.0, 7: 900.0, 8: 100.0, 9: 100.0}, custo, 7)
        self.assertEqual(fator.origem, ORIGEM_SEM_HISTORICO)
        self.assertEqual(fator.fator, 1.0)
        self.assertEqual(fator.meses_usados, (6, 7))

    def test_estorno_entra_como_veio(self):
        fator = fator_de_execucao({5: 1000.0, 6: -200.0, 7: 1000.0}, CUSTO_1000, 7)
        self.assertAlmostEqual(fator.execucao_observada, 1800.0 / 3000.0)
        self.assertLess(fator.peso, 0.1)  # oscilação enorme → quase valor cheio

    def test_heranca(self):
        antecessor = FatorExecucao(0.94, 0.97, 0.937, (2, 3, 4, 5, 6, 7), ORIGEM_EXECUCAO)
        sem = FatorExecucao(1.0, 0.0, None, (6, 7), ORIGEM_SEM_HISTORICO)
        herdado = herdar_fator(sem, antecessor, "2026NE000095")
        self.assertEqual((herdado.origem, herdado.fator, herdado.ne_antecessora), (ORIGEM_HERDADO, 0.94, "2026NE000095"))
        proprio = FatorExecucao(0.8, 1.0, 0.8, (5, 6, 7), ORIGEM_EXECUCAO)
        self.assertIs(herdar_fator(proprio, antecessor, "X"), proprio)  # já tem histórico: não herda
        self.assertIs(herdar_fator(sem, sem, "X"), sem)  # antecessor sem histórico: não herda


class TestProjetarMeses(unittest.TestCase):
    def test_mes_aberto_parcial_sem_registro_e_futuros(self):
        # extração em outubro; fator 0,9 → esperado 900/mês. Ago: 100 (< 450) → restante 800;
        # Set: sem registro → 900; Out: 200 já liquidado → 700; Nov/Dez 900. Total 4.200.
        # Valor cheio nos mesmos meses: 900 + 1000 + 800 + 1000 + 1000 = 4.700.
        realizado = {m: 900.0 for m in range(1, 8)} | {8: 100.0, 10: 200.0}
        projecao = projetar_meses(realizado, CUSTO_1000, 0.9, 10)
        self.assertEqual(projecao.projetado[:7], [None] * 7)
        self.assertAlmostEqual(projecao.projetado[7], 800.0)
        self.assertAlmostEqual(projecao.projetado[8], 900.0)
        self.assertAlmostEqual(projecao.projetado[9], 700.0)
        self.assertEqual(projecao.tipos[7], TIPO_RESTANTE_ABERTO)
        self.assertEqual(projecao.tipos[9], TIPO_PROJETADO)
        self.assertAlmostEqual(projecao.total_projetado, 4200.0)
        self.assertAlmostEqual(projecao.total_valor_cheio, 4700.0)
        self.assertEqual(projecao.restante_em_aberto(), [(8, 800.0), (9, 900.0)])

    def test_mes_aberto_com_metade_ou_mais_e_completo(self):
        projecao = projetar_meses({8: 450.0, 9: 900.0}, CUSTO_1000, 0.9, 10)
        self.assertIsNone(projecao.projetado[7])
        self.assertIsNone(projecao.projetado[8])
        self.assertEqual(projecao.tipos[7], "Realizado")

    def test_fora_da_execucao_e_custo_desconhecido_nao_projetam(self):
        custo = [1000.0] * 10 + [0.0, float("nan")]
        projecao = projetar_meses({}, custo, 1.0, 10)
        self.assertAlmostEqual(projecao.projetado[9], 1000.0)
        self.assertIsNone(projecao.projetado[10])
        self.assertIsNone(projecao.projetado[11])

    def test_exercicio_encerrado_nao_projeta(self):
        self.assertEqual(projetar_meses({}, CUSTO_1000, 1.0, 12).total_projetado, 0.0)


def _linha(**campos: object) -> dict:
    base = {
        "ne_curta": None, "fornecedor": "F", "contrato_numero": "1/2026", "despesa_mensal": 1000.0,
        "meses_no_ano": 12.0, "valor_empenhado": 0.0, "valor_empenhado_execucao": None,
        "valor_empenhado_planilha_total_ne": None, "valor_liquidado_execucao": None,
        "liquidado_via_competencia": True, "saldo_execucao": None, "saldo_colado_planilha": None,
        "status_contrato": "ATIVO", "vigencia_fim": pd.NaT,
    }
    base.update(campos)
    return base


NE_EST = "2026NE000001"  # estável a 0,90
NE_NOVA = "2026NE000002"  # sem histórico


def _filtrado() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # empenhado 9.000, liquidado 6.300 (jan–jul a 900) → saldo 2.700
            _linha(ne_curta=NE_EST, fornecedor="ESTAVEL", contrato_numero="10/2025",
                   valor_empenhado_execucao=9000.0, valor_liquidado_execucao=6300.0),
            # empenhado 2.000, nada liquidado → saldo 2.000; início 01/09
            _linha(ne_curta=NE_NOVA, fornecedor="NOVA", contrato_numero="20/2026",
                   valor_empenhado_execucao=2000.0, valor_liquidado_execucao=0.0,
                   inicio_execucao_data=pd.Timestamp("2026-09-01")),
            _linha(ne_curta=None, fornecedor="SEM NE", valor_empenhado=0.0),
        ]
    )


def _liquidacao() -> pd.DataFrame:
    return pd.DataFrame(
        {"ne_curta": [NE_EST] * 7, "ano_mes": [202601 + i for i in range(7)], "valor": [900.0] * 7}
    )


def _relatorio(antecessores=None):
    por_ne, sem_ne = necessidade_por_ne(_filtrado(), None, 2026)
    return montar_relatorio(por_ne, sem_ne, _liquidacao(), 2026, 10, antecessores)


class TestMontarRelatorio(unittest.TestCase):
    def test_estavel(self):
        # fator 0,9; ago e set sem registro → 900 cada (restante em aberto 1.800); out–dez 2.700.
        # projetado 4.500; valor cheio 5.000; necessidade = 4.500 − 2.700 = 1.800.
        # contratual (Resumo) = 12.000 − 9.000 = 3.000.
        relatorio = _relatorio()
        linha = relatorio.linhas.set_index("ne_curta").loc[NE_EST]
        self.assertAlmostEqual(linha["fator"], 0.9)
        self.assertAlmostEqual(linha["restante_em_aberto"], 1800.0)
        self.assertAlmostEqual(linha["projetado_execucao"], 4500.0)
        self.assertAlmostEqual(linha["projetado_valor_cheio"], 5000.0)
        self.assertAlmostEqual(linha["necessidade_execucao"], 1800.0)
        self.assertAlmostEqual(linha["necessidade_contratual"], 3000.0)
        self.assertEqual(relatorio.qtd_sem_ne, 1)

    def test_nova_valor_cheio_e_com_antecessor(self):
        # sem histórico: set (aberto, sem registro) 1.000 + out–dez 3.000 = 4.000; necessidade 4.000 − 2.000
        linha = _relatorio().linhas.set_index("ne_curta").loc[NE_NOVA]
        self.assertEqual(linha["origem_fator"], ORIGEM_SEM_HISTORICO)
        self.assertAlmostEqual(linha["projetado_execucao"], 4000.0)
        self.assertAlmostEqual(linha["necessidade_execucao"], 2000.0)
        # herdando 0,9 do antecessor: 3.600; necessidade 1.600
        herdada = _relatorio({NE_NOVA: NE_EST}).linhas.set_index("ne_curta").loc[NE_NOVA]
        self.assertEqual(herdada["origem_fator"], ORIGEM_HERDADO)
        self.assertEqual(herdada["ne_antecessora"], NE_EST)
        self.assertAlmostEqual(herdada["projetado_execucao"], 3600.0)
        self.assertAlmostEqual(herdada["necessidade_execucao"], 1600.0)

    def test_antecessor_invalido_e_avisado(self):
        relatorio = _relatorio({NE_EST: NE_NOVA})  # NE_EST já tem histórico
        self.assertEqual(relatorio.linhas.set_index("ne_curta").loc[NE_EST, "origem_fator"], ORIGEM_EXECUCAO)
        self.assertTrue(any("antecessor" in a and "ignorado" in a for a in relatorio.avisos))

    def test_ordem_totais_e_avisos(self):
        relatorio = _relatorio()
        self.assertEqual(relatorio.linhas["ne_curta"].tolist(), [NE_NOVA, NE_EST])  # necessidade decrescente
        self.assertAlmostEqual(relatorio.total_necessidade_execucao, 3800.0)
        self.assertAlmostEqual(relatorio.total_saldo, 4700.0)
        self.assertTrue(any("Meses em aberto" in a for a in relatorio.avisos))
        self.assertTrue(any("sem NE" in a for a in relatorio.avisos))
        self.assertTrue(any("valor mensal cheio" in a and NE_NOVA in a for a in relatorio.avisos))

    def test_aviso_abaixo_e_acima_do_cadastro(self):
        filtrado = pd.DataFrame([
            _linha(ne_curta=NE_EST, valor_empenhado_execucao=1000.0, valor_liquidado_execucao=700.0),
            _linha(ne_curta=NE_NOVA, valor_empenhado_execucao=1000.0, valor_liquidado_execucao=700.0),
        ])
        liquidacao = pd.DataFrame({
            "ne_curta": [NE_EST] * 7 + [NE_NOVA] * 7,
            "ano_mes": [202601 + i for i in range(7)] * 2,
            "valor": [100.0] * 7 + [1100.0] * 7,
        })
        por_ne, sem_ne = necessidade_por_ne(filtrado, None, 2026)
        avisos = montar_relatorio(por_ne, sem_ne, liquidacao, 2026, 10).avisos
        self.assertTrue(any("muito abaixo do cadastrado" in a and NE_EST in a for a in avisos))
        self.assertTrue(any("acima do contratado" in a and NE_NOVA in a for a in avisos))


class TestArquivos(unittest.TestCase):
    def setUp(self):
        self.relatorio = _relatorio()
        self.contexto = ContextoProjecaoExecucao(2026, "06/10/2026", "abcd1234", "06/10/2026 12:00", "Liquidação por Competência.xlsx")

    def test_pdf(self):
        self.assertTrue(gerar_pdf(self.relatorio, self.contexto).startswith(b"%PDF"))

    def test_xlsx(self):
        livro = load_workbook(BytesIO(gerar_xlsx(self.relatorio, self.contexto)))
        self.assertEqual(livro.sheetnames, ["Resumo por NE", "Grade mensal", "Detalhe mensal", "Parâmetros"])
        resumo = livro["Resumo por NE"]
        cabecalho = [c.value for c in resumo[1]]
        linha_est = next(r for r in resumo.iter_rows(min_row=2, values_only=True) if r[0] == NE_EST)
        self.assertAlmostEqual(linha_est[cabecalho.index("Necessidade pela execução")], 1800.0)
        self.assertAlmostEqual(linha_est[cabecalho.index("Fator de execução")], 0.9)
        grade = livro["Grade mensal"]
        cab_grade = [c.value for c in grade[1]]
        linha_grade = next(r for r in grade.iter_rows(min_row=2, values_only=True) if r[0] == NE_EST)
        self.assertEqual(linha_grade[cab_grade.index("Jan")], 900.0)  # realizado
        self.assertAlmostEqual(linha_grade[cab_grade.index("Ago")], 900.0)  # restante em aberto
        self.assertAlmostEqual(linha_grade[cab_grade.index("Out")], 900.0)  # projetado


if __name__ == "__main__":
    unittest.main()
