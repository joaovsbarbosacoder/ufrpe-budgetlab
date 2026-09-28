import unittest

import pandas as pd

from src.despesas_pessoal import (
    ACAO_ATIVO,
    ACAO_ASSISTENCIA_MEDICA,
    ACAO_BENEFICIOS_OBRIGATORIOS,
    ACAO_INATIVO,
    ACAO_RPPS,
    GRUPO_ATIVO,
    GRUPO_INATIVO,
    GRUPO_OUTROS_BENEFICIOS,
    GRUPO_RPPS,
    MULTIPLICADOR_12,
    MULTIPLICADOR_13,
    MULTIPLICADOR_13_3333,
    REGRA_DECIMO_TERCEIRO,
    REGRA_INDENIZACAO_POR_GRUPO,
    REGRA_MULTIPLICADOR,
    REGRA_PROPORCAO_HISTORICA,
    REGRA_SENTENCA_POR_GRUPO,
    REGRA_ZERO,
    MES_ANTECIPACAO_DECIMO_TERCEIRO,
    MES_PARCELA_DECIMO_TERCEIRO,
    PARAMETROS_PADRAO,
    ParametrosProjecao,
    TABELA_REGRAS,
    diferencas_do_padrao,
    execucao_exercicio_por_grupo,
    execucao_exercicio_por_natureza,
    liquidada_mensal_por_grupo,
    aplicar_overrides,
    classificar_grupo,
    consolidar_por_elemento,
    consolidar_relatorio_ativo,
    comparar_com_dotacao,
    comparar_beneficios_por_plano_orcamentario,
    comparar_projecao_com_executado,
    SEM_PLANO_ORCAMENTARIO,
    desvio_por_mes_de_partida,
    resumo_projecao_com_executado,
    dotacao_atualizada_por_acao_beneficios,
    dotacao_atualizada_por_grupo,
    dotacao_atualizada_por_plano_orcamentario,
    execucao_ano_anterior,
    filtrar_escopo,
    grade_mensal,
    grade_mensal_beneficios,
    multiplicador_efetivo,
    projetar,
    regra_para_natureza,
    saldo_remanescente,
    saldo_remanescente_beneficios_por_acao,
    substituir_beneficios_por_plano_orcamentario,
    ultimo_mes_fechado,
    valor_mes_referencia,
)


class TestClassificarGrupo(unittest.TestCase):
    def test_mapeia_as_5_acoes_do_escopo(self):
        self.assertEqual(classificar_grupo(ACAO_ATIVO), GRUPO_ATIVO)
        self.assertEqual(classificar_grupo(ACAO_INATIVO), GRUPO_INATIVO)
        self.assertEqual(classificar_grupo(ACAO_RPPS), GRUPO_RPPS)
        self.assertEqual(classificar_grupo(ACAO_ASSISTENCIA_MEDICA), GRUPO_OUTROS_BENEFICIOS)
        self.assertEqual(classificar_grupo(ACAO_BENEFICIOS_OBRIGATORIOS), GRUPO_OUTROS_BENEFICIOS)

    def test_acao_fora_do_escopo_devolve_none(self):
        self.assertIsNone(classificar_grupo("20RK"))

    def test_nulo_devolve_none(self):
        self.assertIsNone(classificar_grupo(pd.NA))
        self.assertIsNone(classificar_grupo(None))


class TestRegraParaNatureza(unittest.TestCase):
    def test_contratacao_temporaria_e_13_3333(self):
        regra = regra_para_natureza("319004", "31900413")
        # 31900413 é o 13º da contratação temporária — a EXCEÇÃO (decimo_terceiro)
        # vence a regra "mãe" (x13,3333) da natureza 319004.
        self.assertEqual(regra.tipo, REGRA_DECIMO_TERCEIRO)

    def test_contratacao_temporaria_regular_e_13_3333(self):
        regra = regra_para_natureza("319004", "31900401")
        self.assertEqual(regra.tipo, REGRA_MULTIPLICADOR)
        self.assertEqual(regra.multiplicador, MULTIPLICADOR_13_3333)

    def test_obrigacoes_patronais_rgps_e_13(self):
        regra = regra_para_natureza("319013", "31901301")
        self.assertEqual(regra.multiplicador, MULTIPLICADOR_13)

    def test_obrigacoes_patronais_rpps_e_13(self):
        regra = regra_para_natureza("319113", "31911303")
        self.assertEqual(regra.multiplicador, MULTIPLICADOR_13)

    def test_vencimentos_regulares_e_12(self):
        regra = regra_para_natureza("319011", "31901101")
        self.assertEqual(regra.tipo, REGRA_MULTIPLICADOR)
        self.assertEqual(regra.multiplicador, MULTIPLICADOR_12)

    def test_13o_salario_de_ativos_vence_a_regra_mae_de_vencimentos(self):
        regra = regra_para_natureza("319011", "31901143")
        self.assertEqual(regra.tipo, REGRA_DECIMO_TERCEIRO)

    def test_ferias_constitucional_e_proporcao_historica(self):
        regra = regra_para_natureza("319011", "31901145")
        self.assertEqual(regra.tipo, REGRA_PROPORCAO_HISTORICA)

    def test_ferias_antecipada_e_proporcao_historica(self):
        regra = regra_para_natureza("319011", "31901146")
        self.assertEqual(regra.tipo, REGRA_PROPORCAO_HISTORICA)

    def test_exercicios_anteriores_e_zero(self):
        regra = regra_para_natureza("319092", "31909201")
        self.assertEqual(regra.tipo, REGRA_ZERO)

    def test_sentencas_judiciais_e_regra_por_grupo(self):
        regra = regra_para_natureza("319091", "31909101")
        self.assertEqual(regra.tipo, REGRA_SENTENCA_POR_GRUPO)

    def test_ed94_indenizacoes_trabalhistas_defensivo(self):
        regra = regra_para_natureza("319094", "31909401")
        self.assertEqual(regra.tipo, REGRA_INDENIZACAO_POR_GRUPO)

    def test_ed96_ressarcimento_defensivo(self):
        regra = regra_para_natureza("319096", "31909601")
        self.assertEqual(regra.multiplicador, MULTIPLICADOR_13_3333)

    def test_auxilio_alimentacao_e_12(self):
        regra = regra_para_natureza("339046", "33904601")
        self.assertEqual(regra.multiplicador, MULTIPLICADOR_12)

    def test_natureza_desconhecida_devolve_none(self):
        self.assertIsNone(regra_para_natureza("999999", "99999901"))


class TestMultiplicadorEfetivo(unittest.TestCase):
    def test_sentenca_ativo_e_13_3333(self):
        regra = regra_para_natureza("319091", "x")
        self.assertAlmostEqual(multiplicador_efetivo(regra, GRUPO_ATIVO), MULTIPLICADOR_13_3333)

    def test_sentenca_inativo_e_13(self):
        regra = regra_para_natureza("319091", "x")
        self.assertEqual(multiplicador_efetivo(regra, GRUPO_INATIVO), MULTIPLICADOR_13)

    def test_multiplicador_direto_ignora_grupo(self):
        regra = regra_para_natureza("319004", "x")
        self.assertEqual(multiplicador_efetivo(regra, GRUPO_RPPS), MULTIPLICADOR_13_3333)

    def test_indenizacao_ativo_e_12(self):
        regra = regra_para_natureza("319094", "x")
        self.assertEqual(multiplicador_efetivo(regra, GRUPO_ATIVO), MULTIPLICADOR_12)

    def test_indenizacao_inativo_e_13(self):
        regra = regra_para_natureza("319094", "x")
        self.assertEqual(multiplicador_efetivo(regra, GRUPO_INATIVO), MULTIPLICADOR_13)

    def test_indenizacao_outros_grupos_e_12(self):
        regra = regra_para_natureza("319094", "x")
        self.assertEqual(multiplicador_efetivo(regra, GRUPO_RPPS), MULTIPLICADOR_12)

    def test_regra_sem_multiplicador_direto_levanta_erro(self):
        regra = regra_para_natureza("319092", "x")
        with self.assertRaises(ValueError):
            multiplicador_efetivo(regra, GRUPO_ATIVO)


def _linha_execucao(acao_cod, natureza_despesa_cod, natureza_detalhada_cod, **extra):
    base = dict(
        acao_cod=acao_cod,
        acao_desc="",
        natureza_despesa_cod=natureza_despesa_cod,
        natureza_despesa_desc=f"NATUREZA {natureza_despesa_cod}",
        natureza_detalhada_cod=natureza_detalhada_cod,
        natureza_detalhada_desc=f"DETALHE {natureza_detalhada_cod}",
    )
    base.update(extra)
    return base


class TestFiltrarEscopo(unittest.TestCase):
    def test_mantem_so_as_5_acoes_e_anexa_grupo(self):
        df = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101"),
            _linha_execucao(ACAO_INATIVO, "319001", "31900101"),
            _linha_execucao("20RK", "339030", "33903001"),  # fora do escopo
        ])
        resultado = filtrar_escopo(df)
        self.assertEqual(len(resultado), 2)
        self.assertListEqual(sorted(resultado["grupo"].tolist()), [GRUPO_ATIVO, GRUPO_INATIVO])


class TestValorMesReferenciaEExecucaoAnoAnterior(unittest.TestCase):
    def _base_mensal(self):
        linhas = []
        for ano_mes in (202608, 202609):
            linhas.append(_linha_execucao(
                ACAO_ATIVO, "319011", "31901101",
                tipo_linha="item_execucao", ano_mes=ano_mes, liquidada=1000.0 + ano_mes, paga=0.0,
            ))
        # linha de tipo "empenho" não deve entrar na soma de Liquidada/Paga
        linhas.append(_linha_execucao(
            ACAO_ATIVO, "319011", "31901101",
            tipo_linha="empenho", ano_mes=202609, liquidada=pd.NA, paga=pd.NA,
        ))
        return pd.DataFrame(linhas)

    def test_valor_mes_referencia_usa_liquidada_do_mes_pedido(self):
        resultado = valor_mes_referencia(self._base_mensal(), 202609)
        self.assertEqual(len(resultado), 1)
        self.assertAlmostEqual(float(resultado.iloc[0]["valor_mes_referencia"]), 1000.0 + 202609)

    def test_execucao_ano_anterior_usa_empenhada_do_ano_pedido(self):
        df = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", ano=2025, empenhada=500000.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", ano=2026, empenhada=999999.0),
        ])
        resultado = execucao_ano_anterior(df, 2025)
        self.assertEqual(len(resultado), 1)
        self.assertAlmostEqual(float(resultado.iloc[0]["execucao_ano_anterior"]), 500000.0)


class TestUltimoMesFechado(unittest.TestCase):
    def test_ignora_mes_com_liquidada_zerada(self):
        df = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202608, liquidada=500.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202609, liquidada=0.0, paga=0.0),
        ])
        self.assertEqual(ultimo_mes_fechado(df), 202608)

    def test_sem_nenhum_mes_com_movimento_devolve_none(self):
        df = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202608, liquidada=0.0, paga=0.0),
        ])
        self.assertIsNone(ultimo_mes_fechado(df))

    def test_rola_para_o_exercicio_seguinte_quando_a_base_mensal_cruza_dois_anos(self):
        # Pedido do usuário (10/09/2026: "quero que o sistema perdure por mais anos... 2027,
        # 2028..."): se a mesma extração mensal passar a trazer o novo exercício junto com o
        # anterior (ex. DEZ/2026 + JAN/2027 no mesmo arquivo — ver docs/base_execucao_mensal.md,
        # pendência já documentada), o "último mês fechado" tem que rolar pro ano novo assim
        # que ele tiver movimento real, não travar no ano anterior.
        df = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202612, liquidada=500.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202701, liquidada=520.0, paga=0.0),
        ])
        self.assertEqual(ultimo_mes_fechado(df), 202701)

    def test_rejeita_mes_com_grupos_se_compensando(self):
        # Decisão 9 (22/09/2026) — achado real: set/2026 tinha Ativo quase zero mas
        # Inativo normal, então a SOMA do escopo inteiro ainda ficava > 0 (regra antiga
        # passava). Cada grupo precisa estar perto do seu próprio histórico — aqui Ativo
        # despenca em 202609 (10, vs. média de 1000 nos 2 meses anteriores) mesmo com a
        # soma total (10 + 600 = 610) positiva; deve rejeitar e cair para 202608.
        linhas = []
        for ano_mes in (202607, 202608):
            linhas.append(_linha_execucao(
                ACAO_ATIVO, "319011", "31901101",
                tipo_linha="item_execucao", ano_mes=ano_mes, liquidada=1000.0, paga=0.0,
            ))
            linhas.append(_linha_execucao(
                ACAO_INATIVO, "319001", "31900101",
                tipo_linha="item_execucao", ano_mes=ano_mes, liquidada=500.0, paga=0.0,
            ))
        linhas.append(_linha_execucao(
            ACAO_ATIVO, "319011", "31901101",
            tipo_linha="item_execucao", ano_mes=202609, liquidada=10.0, paga=0.0,
        ))
        linhas.append(_linha_execucao(
            ACAO_INATIVO, "319001", "31900101",
            tipo_linha="item_execucao", ano_mes=202609, liquidada=600.0, paga=0.0,
        ))
        df = pd.DataFrame(linhas)
        self.assertEqual(ultimo_mes_fechado(df), 202608)


class TestProjetar(unittest.TestCase):
    """Cenário sintético cobrindo as 5 regras + o caso "sem regra" nos dois níveis de
    rigor (núcleo SPO = erro; ações extras do usuário = alerta + padrão x12)."""

    def _mensal(self):
        linhas = [
            # Ativo: vencimentos regulares (x12) + 13º (x1) + férias constitucional (proporção histórica)
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202608, liquidada=100000.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901143", tipo_linha="item_execucao", ano_mes=202608, liquidada=8000.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901145", tipo_linha="item_execucao", ano_mes=202608, liquidada=3000.0, paga=0.0),
            # Ativo: sentença judicial (deve virar x13,3333, não x13)
            _linha_execucao(ACAO_ATIVO, "319091", "31909101", tipo_linha="item_execucao", ano_mes=202608, liquidada=2000.0, paga=0.0),
            # Inativo: sentença judicial (deve virar x13)
            _linha_execucao(ACAO_INATIVO, "319091", "31909101", tipo_linha="item_execucao", ano_mes=202608, liquidada=1500.0, paga=0.0),
            # Inativo: exercícios anteriores (projeção sempre zero, mesmo tendo valor no mês)
            _linha_execucao(ACAO_INATIVO, "319092", "31909201", tipo_linha="item_execucao", ano_mes=202608, liquidada=999.0, paga=0.0),
            # Extra do usuário (212B): rubrica não mapeada explicitamente -> alerta + padrão x12
            _linha_execucao(ACAO_BENEFICIOS_OBRIGATORIOS, "339999", "33999901", tipo_linha="item_execucao", ano_mes=202608, liquidada=4000.0, paga=0.0),
        ]
        return pd.DataFrame(linhas)

    def _anual(self):
        linhas = [
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", ano=2025, empenhada=1_100_000.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901145", ano=2025, empenhada=33_000.0),
        ]
        return pd.DataFrame(linhas)

    def test_multiplicador_simples_sentenca_ativo(self):
        resultado = projetar(self._mensal(), self._anual(), 202608, 2027)
        linha = resultado.linhas[
            (resultado.linhas["grupo"] == GRUPO_ATIVO) & (resultado.linhas["natureza_despesa_cod"] == "319091")
        ].iloc[0]
        self.assertAlmostEqual(float(linha["projecao"]), 2000.0 * MULTIPLICADOR_13_3333)

    def test_multiplicador_simples_sentenca_inativo(self):
        resultado = projetar(self._mensal(), self._anual(), 202608, 2027)
        linha = resultado.linhas[
            (resultado.linhas["grupo"] == GRUPO_INATIVO) & (resultado.linhas["natureza_despesa_cod"] == "319091")
        ].iloc[0]
        self.assertAlmostEqual(float(linha["projecao"]), 1500.0 * MULTIPLICADOR_13)

    def test_exercicios_anteriores_projeta_zero_mesmo_com_valor_no_mes(self):
        resultado = projetar(self._mensal(), self._anual(), 202608, 2027)
        linha = resultado.linhas[resultado.linhas["natureza_despesa_cod"] == "319092"].iloc[0]
        self.assertEqual(float(linha["projecao"]), 0.0)

    def test_decimo_terceiro_e_uma_vez_o_mes_de_referencia_da_natureza_mae(self):
        # Decisão 8 (bug corrigido): a base do 13º é o mês de referência da natureza
        # "mãe" (319011, aqui só a linha 31901101 = R$100.000 — excluindo as próprias
        # 31901143/31901145, que têm regra própria), NUNCA o mês de referência da
        # PRÓPRIA rubrica de 13º (31901143 = R$8.000 no fixture) — essa segunda leitura
        # só bate com a realidade em junho/novembro, quando o 13º é de fato pago; em
        # qualquer outro mês de referência ela é um resíduo que não representa "um mês
        # de folha".
        resultado = projetar(self._mensal(), self._anual(), 202608, 2027)
        linha = resultado.linhas[resultado.linhas["natureza_detalhada_cod"] == "31901143"].iloc[0]
        self.assertAlmostEqual(float(linha["projecao"]), 100_000.0)

    def test_proporcao_historica_aplica_proporcao_do_ano_anterior_sobre_vencimentos_projetados(self):
        resultado = projetar(self._mensal(), self._anual(), 202608, 2027)
        linha = resultado.linhas[resultado.linhas["natureza_detalhada_cod"] == "31901145"].iloc[0]
        # proporção 2025: 33.000 / 1.100.000 = 0,03
        # vencimentos projetados do grupo Ativo: 100.000 (mês ref, natureza 319011) x 12 = 1.200.000
        # projeção esperada: 0,03 x 1.200.000 = 36.000
        self.assertAlmostEqual(float(linha["projecao"]), 36_000.0, places=2)

    def test_rubrica_nao_mapeada_em_acao_extra_gera_alerta_e_aplica_x12(self):
        resultado = projetar(self._mensal(), self._anual(), 202608, 2027)
        linha = resultado.linhas[resultado.linhas["natureza_despesa_cod"] == "339999"].iloc[0]
        self.assertAlmostEqual(float(linha["projecao"]), 4000.0 * MULTIPLICADOR_12)
        self.assertTrue(any("339999" in alerta for alerta in resultado.alertas))
        self.assertTrue(resultado.ok)  # alerta não é erro

    def test_rubrica_nao_mapeada_no_nucleo_spo_gera_erro_e_nao_projeta(self):
        mensal = self._mensal()
        # injeta uma natureza desconhecida numa das 3 ações NÚCLEO (não extra)
        extra = _linha_execucao(ACAO_RPPS, "319999", "31999901", tipo_linha="item_execucao", ano_mes=202608, liquidada=777.0, paga=0.0)
        mensal = pd.concat([mensal, pd.DataFrame([extra])], ignore_index=True)
        resultado = projetar(mensal, self._anual(), 202608, 2027)
        self.assertFalse(resultado.ok)
        self.assertTrue(any("319999" in erro for erro in resultado.erros))
        linha = resultado.linhas[resultado.linhas["natureza_despesa_cod"] == "319999"].iloc[0]
        # `None` vira NaN ao entrar numa coluna numérica do DataFrame — comportamento
        # normal do pandas, não um bug: o teste confere "sem valor", não `is None`.
        self.assertTrue(pd.isna(linha["projecao"]))


def _linha_dotacao(acao_codigo, item_informacao_codigo, ano_lancamento, valor_movimento_liquido,
                    plano_orcamentario_codigo=None):
    return dict(
        acao_codigo=acao_codigo, item_informacao_codigo=item_informacao_codigo,
        ano_lancamento=ano_lancamento, valor_movimento_liquido=valor_movimento_liquido,
        plano_orcamentario_codigo=plano_orcamentario_codigo,
    )


class TestDotacaoAtualizadaPorGrupo(unittest.TestCase):
    def test_soma_so_dotacao_atualizada_do_ano_pedido_dentro_do_escopo(self):
        df = pd.DataFrame([
            _linha_dotacao(ACAO_ATIVO, "dotacao_atualizada", 2026, 400_000.0),
            _linha_dotacao(ACAO_ATIVO, "dotacao_inicial", 2026, 350_000.0),  # não é "atualizada" — ignorado
            _linha_dotacao(ACAO_ATIVO, "dotacao_atualizada", 2025, 999_999.0),  # ano errado — ignorado
            _linha_dotacao(ACAO_INATIVO, "dotacao_atualizada", 2026, 200_000.0),
            _linha_dotacao("20RK", "dotacao_atualizada", 2026, 111_111.0),  # fora do escopo — ignorado
        ])
        resultado = dotacao_atualizada_por_grupo(df, 2026)
        self.assertAlmostEqual(float(resultado[GRUPO_ATIVO]), 400_000.0)
        self.assertAlmostEqual(float(resultado[GRUPO_INATIVO]), 200_000.0)
        self.assertNotIn("fora_do_escopo", resultado.index)


class TestDotacaoAtualizadaPorPlanoOrcamentario(unittest.TestCase):
    """Pedido do usuário (10/09/2026): a Dotação Anual TEM a dimensão Plano
    Orçamentário — dá pra comparar dotação x projeção nesse nível, só para as 2 ações
    de Outros Benefícios."""

    def test_mesmo_codigo_po_em_acoes_diferentes_nao_se_mistura(self):
        # "0001" é "Assistência Médica" em 2004 mas "Assistência Pré-Escolar" em
        # 212B — achado real na base (ver docstring de `dotacao_atualizada_por_plano_orcamentario`).
        df = pd.DataFrame([
            _linha_dotacao(ACAO_ASSISTENCIA_MEDICA, "dotacao_atualizada", 2026, 500_000.0, plano_orcamentario_codigo="0001"),
            _linha_dotacao(ACAO_BENEFICIOS_OBRIGATORIOS, "dotacao_atualizada", 2026, 300_000.0, plano_orcamentario_codigo="0001"),
        ])
        resultado = dotacao_atualizada_por_plano_orcamentario(df, 2026)
        self.assertAlmostEqual(float(resultado[(ACAO_ASSISTENCIA_MEDICA, "0001")]), 500_000.0)
        self.assertAlmostEqual(float(resultado[(ACAO_BENEFICIOS_OBRIGATORIOS, "0001")]), 300_000.0)

    def test_exclui_linhas_regra_de_ouro(self):
        df = pd.DataFrame([
            _linha_dotacao(ACAO_BENEFICIOS_OBRIGATORIOS, "dotacao_atualizada", 2026, 300_000.0, plano_orcamentario_codigo="0005"),
            _linha_dotacao(ACAO_BENEFICIOS_OBRIGATORIOS, "dotacao_atualizada", 2026, 999_999.0, plano_orcamentario_codigo="RO05"),
        ])
        resultado = dotacao_atualizada_por_plano_orcamentario(df, 2026)
        self.assertAlmostEqual(float(resultado[(ACAO_BENEFICIOS_OBRIGATORIOS, "0005")]), 300_000.0)
        self.assertNotIn((ACAO_BENEFICIOS_OBRIGATORIOS, "RO05"), resultado.index)

    def test_acoes_fora_de_outros_beneficios_sao_ignoradas(self):
        df = pd.DataFrame([
            _linha_dotacao(ACAO_ATIVO, "dotacao_atualizada", 2026, 1_000_000.0, plano_orcamentario_codigo="0001"),
        ])
        resultado = dotacao_atualizada_por_plano_orcamentario(df, 2026)
        self.assertTrue(resultado.empty)


class TestDotacaoAtualizadaPorAcaoBeneficios(unittest.TestCase):
    """Decisão 12 (22/09/2026): dotação de Outros Benefícios por AÇÃO (2004/212B), um
    nível acima de Plano Orçamentário — pedido do usuário pra separar o Saldo
    Remanescente entre as 2 ações."""

    def test_soma_todos_os_po_da_mesma_acao(self):
        df = pd.DataFrame([
            _linha_dotacao(ACAO_ASSISTENCIA_MEDICA, "dotacao_atualizada", 2026, 500_000.0, plano_orcamentario_codigo="0001"),
            _linha_dotacao(ACAO_ASSISTENCIA_MEDICA, "dotacao_atualizada", 2026, 100_000.0, plano_orcamentario_codigo="0002"),
            _linha_dotacao(ACAO_BENEFICIOS_OBRIGATORIOS, "dotacao_atualizada", 2026, 300_000.0, plano_orcamentario_codigo="0001"),
        ])
        resultado = dotacao_atualizada_por_acao_beneficios(df, 2026)
        self.assertAlmostEqual(float(resultado[ACAO_ASSISTENCIA_MEDICA]), 600_000.0)
        self.assertAlmostEqual(float(resultado[ACAO_BENEFICIOS_OBRIGATORIOS]), 300_000.0)

    def test_exclui_regra_de_ouro_e_acoes_fora_do_escopo(self):
        df = pd.DataFrame([
            _linha_dotacao(ACAO_BENEFICIOS_OBRIGATORIOS, "dotacao_atualizada", 2026, 300_000.0, plano_orcamentario_codigo="0005"),
            _linha_dotacao(ACAO_BENEFICIOS_OBRIGATORIOS, "dotacao_atualizada", 2026, 999_999.0, plano_orcamentario_codigo="RO05"),
            _linha_dotacao(ACAO_ATIVO, "dotacao_atualizada", 2026, 1_000_000.0, plano_orcamentario_codigo="0001"),
        ])
        resultado = dotacao_atualizada_por_acao_beneficios(df, 2026)
        self.assertAlmostEqual(float(resultado[ACAO_BENEFICIOS_OBRIGATORIOS]), 300_000.0)
        self.assertNotIn(ACAO_ATIVO, resultado.index)


class TestCompararComDotacao(unittest.TestCase):
    """Objetivo central do módulo (pedido explícito do usuário): dotação suficiente ou
    não, por grupo."""

    def _mensal_simples(self, valor_ativo=100_000.0, valor_inativo=100_000.0):
        return pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202608, liquidada=valor_ativo, paga=0.0),
            _linha_execucao(ACAO_INATIVO, "319001", "31900101", tipo_linha="item_execucao", ano_mes=202608, liquidada=valor_inativo, paga=0.0),
        ])

    def test_grupo_com_dotacao_maior_que_projecao_e_suficiente(self):
        mensal = self._mensal_simples(valor_ativo=10_000.0)  # projeção: 10.000 x 12 = 120.000
        dotacao = pd.DataFrame([
            _linha_dotacao(ACAO_ATIVO, "dotacao_atualizada", 2026, 200_000.0),  # > projeção
            _linha_dotacao(ACAO_INATIVO, "dotacao_atualizada", 2026, 5_000.0),  # < projeção (100.000 x 12)
        ])
        # sem naturezas de proporção histórica neste cenário — anual vazio (mas com as
        # colunas certas, senão `filtrar_escopo` levanta KeyError num DataFrame sem
        # nenhuma coluna) é suficiente pra `execucao_ano_anterior` não achar nada.
        anual_vazio = pd.DataFrame(columns=[
            "acao_cod", "ano", "natureza_despesa_cod", "natureza_despesa_desc",
            "natureza_detalhada_cod", "natureza_detalhada_desc", "empenhada",
        ])
        resultado = projetar(mensal, anual_vazio, 202608, 2027)
        comparacao = comparar_com_dotacao(resultado, dotacao, 2026)

        linha_ativo = comparacao[comparacao["grupo"] == GRUPO_ATIVO].iloc[0]
        self.assertTrue(bool(linha_ativo["suficiente"]))
        self.assertGreater(float(linha_ativo["diferenca"]), 0)

        linha_inativo = comparacao[comparacao["grupo"] == GRUPO_INATIVO].iloc[0]
        self.assertFalse(bool(linha_inativo["suficiente"]))
        self.assertLess(float(linha_inativo["diferenca"]), 0)


class TestGradeMensal(unittest.TestCase):
    """Grade Jan-Dez: mês já na base mensal usa o valor real; mês futuro usa a
    projeção, com a parcela de 13º/multiplicador extra concentrada em jun/nov
    (decisão 6, confirmada pelo usuário)."""

    def _mensal(self):
        # Ativo, vencimentos regulares (x12): só Jan-Ago têm dado real; Set-Dez são
        # futuros e devem repetir o valor de referência (Ago = 202608 = 50.000,00).
        linhas = [
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202601 + i, liquidada=50_000.0 + i, paga=0.0)
            for i in range(8)  # 202601..202608
        ]
        # Ativo, contratação temporária (x13,3333) — mesmo recorte, só p/ conferir a
        # parcela extra concentrada em jun/nov nos meses futuros.
        linhas.append(_linha_execucao(ACAO_ATIVO, "319004", "31900401", tipo_linha="item_execucao", ano_mes=202608, liquidada=9_000.0, paga=0.0))
        return pd.DataFrame(linhas)

    def _anual_vazio(self):
        return pd.DataFrame(columns=[
            "acao_cod", "ano", "natureza_despesa_cod", "natureza_despesa_desc",
            "natureza_detalhada_cod", "natureza_detalhada_desc", "empenhada",
        ])

    def test_mes_ja_executado_usa_valor_real_nao_projecao(self):
        resultado = grade_mensal(self._mensal(), self._anual_vazio(), 2026, 202608)
        linha = resultado.linhas[resultado.linhas["natureza_despesa_cod"] == "319011"].iloc[0]
        # Jan (índice 0) = 50.000,00 real, não repetição do mês de referência (Ago).
        self.assertAlmostEqual(linha["meses"][0], 50_000.0)
        self.assertAlmostEqual(linha["meses"][7], 50_007.0)  # Ago real = 50.000+7

    def test_mes_futuro_de_rubrica_x12_repete_valor_de_referencia_sem_bump(self):
        resultado = grade_mensal(self._mensal(), self._anual_vazio(), 2026, 202608)
        linha = resultado.linhas[resultado.linhas["natureza_despesa_cod"] == "319011"].iloc[0]
        valor_ref = 50_007.0  # Ago (mês de referência)
        # Set (índice 8) é futuro e não é mês de 13º/parcela extra — repete liso.
        self.assertAlmostEqual(linha["meses"][8], valor_ref)

    def test_mes_futuro_x13_3333_concentra_extra_em_novembro_e_dezembro_repete_no_ativo(self):
        resultado = grade_mensal(self._mensal(), self._anual_vazio(), 2026, 202608)
        linha = resultado.linhas[resultado.linhas["natureza_despesa_cod"] == "319004"].iloc[0]
        valor_ref = 9_000.0
        extra_total = valor_ref * (MULTIPLICADOR_13_3333 - 12.0)
        metade_extra = extra_total / 2
        # jun já passou (mês de referência é agosto) — este cenário não tem mês futuro
        # de junho pra testar o bump diretamente aqui; novembro é o único mês de
        # parcela ainda futuro, recebendo o extra.
        self.assertAlmostEqual(linha["meses"][MES_PARCELA_DECIMO_TERCEIRO - 1], valor_ref + metade_extra)

    def test_obrigacoes_patronais_concentram_extra_inteiro_em_novembro(self):
        # Decisão 11 (22/09/2026): a antecipação de junho do 13º não gera desconto
        # previdenciário — Obrigações Patronais (319013/319113) não levam bônus em
        # junho, e o extra inteiro (não a metade) cai em novembro. Mês de referência
        # bem cedo no ano (fevereiro) pra jun/nov ainda serem futuros.
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_RPPS, "319113", "31911301", tipo_linha="item_execucao", ano_mes=202601, liquidada=10_000.0, paga=0.0),
        ])
        resultado = grade_mensal(mensal, self._anual_vazio(), 2026, 202601)
        linha = resultado.linhas[resultado.linhas["natureza_despesa_cod"] == "319113"].iloc[0]
        valor_ref = 10_000.0
        extra_total = valor_ref * (MULTIPLICADOR_13 - 12.0)
        self.assertAlmostEqual(linha["meses"][MES_ANTECIPACAO_DECIMO_TERCEIRO - 1], valor_ref)  # Jun: sem bônus
        self.assertAlmostEqual(linha["meses"][MES_PARCELA_DECIMO_TERCEIRO - 1], valor_ref + extra_total)  # Nov: extra inteiro (dobro)

    def test_decimo_terceiro_futuro_concentrado_meio_a_meio_em_junho_e_novembro(self):
        # mês de referência bem cedo no ano (fevereiro) pra jun/nov ainda serem futuros.
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202601, liquidada=100.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901143", tipo_linha="item_execucao", ano_mes=202601, liquidada=100.0, paga=0.0),  # 13º, Jan real
        ])
        resultado = grade_mensal(mensal, self._anual_vazio(), 2026, 202601)
        linha13 = resultado.linhas[resultado.linhas["natureza_detalhada_cod"] == "31901143"].iloc[0]
        self.assertAlmostEqual(linha13["meses"][MES_ANTECIPACAO_DECIMO_TERCEIRO - 1], 50.0)
        self.assertAlmostEqual(linha13["meses"][MES_PARCELA_DECIMO_TERCEIRO - 1], 50.0)
        # meses futuros que não são jun/nov ficam em zero (não é um valor recorrente
        # todo mês, só nos dois meses de pagamento).
        self.assertAlmostEqual(linha13["meses"][2], 0.0)  # Março

    def test_dezembro_repete_novembro_real_quando_novembro_ja_fechou(self):
        # Decisão 10: quando o mês de referência já passa de novembro, novembro é
        # REAL (não projetado) — dezembro (ainda futuro) deve copiar esse valor real,
        # não recalcular a partir de agosto.
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202601 + i, liquidada=50_000.0 + i, paga=0.0)
            for i in range(11)  # 202601..202611, incluindo novembro real
        ])
        resultado = grade_mensal(mensal, self._anual_vazio(), 2026, 202611)
        linha = resultado.linhas[resultado.linhas["natureza_despesa_cod"] == "319011"].iloc[0]
        self.assertAlmostEqual(linha["meses"][10], 50_010.0)  # Nov: real
        self.assertAlmostEqual(linha["meses"][11], 50_010.0)  # Dez: repete o real de nov

    def test_dezembro_nao_repete_novembro_fora_do_ativo(self):
        # Decisão 10 é exclusiva do grupo Ativo — Inativo/RPPS/Outros Benefícios
        # continuam com o valor liso mesmo em novembro/dezembro. Usa sentença judicial
        # (x13 no Inativo) justamente porque ELA tem bump em novembro — se a cópia de
        # dezembro estivesse vazando pra fora do Ativo, este teste pegaria (Dez
        # ficaria igual ao Nov com bump, em vez de continuar liso).
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_INATIVO, "319091", "31909101", tipo_linha="item_execucao", ano_mes=202608, liquidada=10_000.0, paga=0.0),
        ])
        resultado = grade_mensal(mensal, self._anual_vazio(), 2026, 202608)
        linha = resultado.linhas[resultado.linhas["natureza_despesa_cod"] == "319091"].iloc[0]
        self.assertAlmostEqual(linha["meses"][10], 15_000.0)  # Nov: liso + metade do extra (x13)
        self.assertAlmostEqual(linha["meses"][11], 10_000.0)  # Dez: continua liso, sem repetir nov

    def test_regra_zero_fica_zero_em_todos_os_meses_futuros(self):
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_INATIVO, "319092", "31909201", tipo_linha="item_execucao", ano_mes=202601, liquidada=999.0, paga=0.0),
        ])
        resultado = grade_mensal(mensal, self._anual_vazio(), 2026, 202601)
        linha = resultado.linhas[resultado.linhas["natureza_despesa_cod"] == "319092"].iloc[0]
        self.assertAlmostEqual(linha["meses"][0], 999.0)  # Jan: real
        self.assertAlmostEqual(linha["meses"][5], 0.0)  # Jun: projetado, regra zero

    def test_dois_exercicios_na_mesma_base_mensal_nao_vazam_um_no_outro(self):
        # Pedido do usuário (10/09/2026: "quero que o sistema perdure por mais anos... 2027,
        # 2028..."): se a extração mensal um dia trouxer DEZ/2026 e JAN/2027 juntas no mesmo
        # arquivo (cenário já documentado como pendência em docs/base_execucao_mensal.md),
        # pedir a grade de 2026 não pode incluir nada de 2027, e vice-versa.
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202612, liquidada=10_000.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202701, liquidada=99_999.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202702, liquidada=99_999.0, paga=0.0),
        ])
        grade_2026 = grade_mensal(mensal, self._anual_vazio(), 2026, 202612)
        linha_2026 = grade_2026.linhas[grade_2026.linhas["natureza_despesa_cod"] == "319011"].iloc[0]
        self.assertAlmostEqual(linha_2026["meses"][11], 10_000.0)  # dezembro de 2026: real
        self.assertTrue(all(v is None for v in linha_2026["meses"][:11]))  # nada de 2027 aqui

        grade_2027 = grade_mensal(mensal, self._anual_vazio(), 2027, 202702)
        linha_2027 = grade_2027.linhas[grade_2027.linhas["natureza_despesa_cod"] == "319011"].iloc[0]
        self.assertAlmostEqual(linha_2027["meses"][0], 99_999.0)  # janeiro de 2027: real
        self.assertAlmostEqual(linha_2027["meses"][1], 99_999.0)  # fevereiro de 2027: real
        self.assertNotAlmostEqual(linha_2027["meses"][0], 10_000.0)  # não herdou o valor de dez/2026


class TestAplicarOverrides(unittest.TestCase):
    def _grade_simples(self):
        # mês de referência = fevereiro (202602): Jan/Fev são reais, Mar em diante são
        # futuros e portanto editáveis.
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202601, liquidada=100.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202602, liquidada=110.0, paga=0.0),
        ])
        anual_vazio = pd.DataFrame(columns=[
            "acao_cod", "ano", "natureza_despesa_cod", "natureza_despesa_desc",
            "natureza_detalhada_cod", "natureza_detalhada_desc", "empenhada",
        ])
        return grade_mensal(mensal, anual_vazio, 2026, 202602)

    def test_override_em_mes_futuro_substitui_o_valor_projetado(self):
        grade = self._grade_simples()
        chave = (GRUPO_ATIVO, "319011", "31901101")
        resultado = aplicar_overrides(grade, {chave: {5: 999_999.0}})  # Maio, futuro
        linha = resultado.linhas[resultado.linhas["natureza_detalhada_cod"] == "31901101"].iloc[0]
        self.assertAlmostEqual(linha["meses"][4], 999_999.0)

    def test_override_em_mes_ja_real_e_ignorado(self):
        grade = self._grade_simples()
        chave = (GRUPO_ATIVO, "319011", "31901101")
        # Fevereiro (índice 1) já é real (110.0) — override não deve valer.
        resultado = aplicar_overrides(grade, {chave: {2: -1.0}})
        linha = resultado.linhas[resultado.linhas["natureza_detalhada_cod"] == "31901101"].iloc[0]
        self.assertAlmostEqual(linha["meses"][1], 110.0)

    def test_grade_original_nao_e_alterada_in_place(self):
        grade = self._grade_simples()
        valor_original_maio = grade.linhas.iloc[0]["meses"][4]
        chave = (GRUPO_ATIVO, "319011", "31901101")
        aplicar_overrides(grade, {chave: {5: 12345.0}})
        self.assertEqual(grade.linhas.iloc[0]["meses"][4], valor_original_maio)


class TestConsolidarPorElemento(unittest.TestCase):
    """Pedido explícito do usuário: "Rubrica × Mês" não deve descer até o nível de
    sub-detalhe (natureza detalhada) — só até ELEMENTO, exceto 13º/proporção
    histórica, que continuam em linha própria (mesma referência visual anexada)."""

    def _grade_com_varios_sub_detalhes(self):
        # 3 naturezas detalhadas DIFERENTES dentro do MESMO elemento (319011,
        # vencimentos regulares — regra x12) + 1 linha de 13º (regra própria).
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202601, liquidada=100.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901131", tipo_linha="item_execucao", ano_mes=202601, liquidada=50.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901109", tipo_linha="item_execucao", ano_mes=202601, liquidada=20.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901143", tipo_linha="item_execucao", ano_mes=202601, liquidada=8.0, paga=0.0),  # 13º
        ])
        anual_vazio = pd.DataFrame(columns=[
            "acao_cod", "ano", "natureza_despesa_cod", "natureza_despesa_desc",
            "natureza_detalhada_cod", "natureza_detalhada_desc", "empenhada",
        ])
        return grade_mensal(mensal, anual_vazio, 2026, 202601)

    def test_naturezas_regulares_do_mesmo_elemento_viram_uma_so_linha(self):
        grade = self._grade_com_varios_sub_detalhes()
        consolidada = consolidar_por_elemento(grade)
        linhas_319011 = consolidada.linhas[consolidada.linhas["natureza_despesa_cod"] == "319011"]
        # as 3 naturezas "regulares" (31901101/31901131/31901109) viram 1 linha; o 13º
        # (31901143) continua separado -> total de 2 linhas para a natureza 319011.
        self.assertEqual(len(linhas_319011), 2)

    def test_soma_das_naturezas_regulares_bate_com_a_soma_original(self):
        grade = self._grade_com_varios_sub_detalhes()
        consolidada = consolidar_por_elemento(grade)
        linha_regular = consolidada.linhas[
            (consolidada.linhas["natureza_despesa_cod"] == "319011") & (consolidada.linhas["regra_aplicada"] == REGRA_MULTIPLICADOR)
        ].iloc[0]
        self.assertAlmostEqual(linha_regular["meses"][0], 100.0 + 50.0 + 20.0)

    def test_linha_de_13o_continua_separada_e_intacta(self):
        grade = self._grade_com_varios_sub_detalhes()
        consolidada = consolidar_por_elemento(grade)
        linha_13 = consolidada.linhas[consolidada.linhas["regra_aplicada"] == REGRA_DECIMO_TERCEIRO]
        self.assertEqual(len(linha_13), 1)
        self.assertAlmostEqual(linha_13.iloc[0]["meses"][0], 8.0)

    def test_totais_por_grupo_nao_mudam_com_a_consolidacao(self):
        grade = self._grade_com_varios_sub_detalhes()
        consolidada = consolidar_por_elemento(grade)
        total_original = grade.total_por_grupo_por_mes().loc[GRUPO_ATIVO, 1]
        total_consolidado = consolidada.total_por_grupo_por_mes().loc[GRUPO_ATIVO, 1]
        self.assertAlmostEqual(total_original, total_consolidado)

    def test_modalidade_direta_e_intra_orcamentaria_do_mesmo_elemento_viram_uma_linha(self):
        # 319004 (direta) e 319104 (intra-orçamentária) são o MESMO elemento (04) —
        # só o dígito de modalidade muda (3-1-90-04 vs 3-1-91-04). Achado ao restringir
        # a aba Ativo ao layout do relatório-modelo (10/09/2026): antes desta correção,
        # apareciam como 2 linhas "ED_04" diferentes.
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319004", "319004", tipo_linha="item_execucao", ano_mes=202601, liquidada=100.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319104", "319104", tipo_linha="item_execucao", ano_mes=202601, liquidada=30.0, paga=0.0),
        ])
        anual_vazio = pd.DataFrame(columns=[
            "acao_cod", "ano", "natureza_despesa_cod", "natureza_despesa_desc",
            "natureza_detalhada_cod", "natureza_detalhada_desc", "empenhada",
        ])
        grade = grade_mensal(mensal, anual_vazio, 2026, 202601)
        consolidada = consolidar_por_elemento(grade)
        self.assertEqual(len(consolidada.linhas), 1)
        linha = consolidada.linhas.iloc[0]
        self.assertEqual(linha["natureza_despesa_cod"], "319004")  # modalidade direta é a representante
        self.assertAlmostEqual(linha["meses"][0], 130.0)


_ANUAL_VAZIO = pd.DataFrame(columns=[
    "acao_cod", "ano", "natureza_despesa_cod", "natureza_despesa_desc",
    "natureza_detalhada_cod", "natureza_detalhada_desc", "empenhada",
])


class TestConsolidarRelatorioAtivo(unittest.TestCase):
    """Layout fixo pedido pelo usuário (10/09/2026, foto do relatório-modelo anexada):
    só a aba Ativo é restrita a ED_04/07/11-12/13(RGPS)/16-17/91/92/94/96, com 11 e 12
    fundidos numa única linha e só 4 sub-rubricas (13º/Abono Pecuniário/Abono
    Constitucional/Adiantamento de Férias) soltas dentro dela."""

    def _grade(self, linhas_mensal, ano_mes=202601):
        mensal = pd.DataFrame(linhas_mensal)
        grade = grade_mensal(mensal, _ANUAL_VAZIO, ano_mes // 100, ano_mes)
        return consolidar_relatorio_ativo(consolidar_por_elemento(grade))

    def test_elementos_11_e_12_viram_uma_linha_11_12(self):
        resultado = self._grade([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202601, liquidada=100.0, paga=0.0),
        ])
        linha = resultado.linhas[resultado.linhas["grupo"] == GRUPO_ATIVO]
        self.assertEqual(list(linha["natureza_despesa_cod"]), ["11/12"])
        self.assertAlmostEqual(linha.iloc[0]["meses"][0], 100.0)

    def test_subitens_43_44_45_46_continuam_separados_dentro_de_11_12(self):
        resultado = self._grade([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202601, liquidada=100.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901143", tipo_linha="item_execucao", ano_mes=202601, liquidada=8.0, paga=0.0),  # 13º
            _linha_execucao(ACAO_ATIVO, "319011", "31901144", tipo_linha="item_execucao", ano_mes=202601, liquidada=3.0, paga=0.0),  # abono pecuniário
            _linha_execucao(ACAO_ATIVO, "319011", "31901145", tipo_linha="item_execucao", ano_mes=202601, liquidada=2.0, paga=0.0),  # abono constitucional
            _linha_execucao(ACAO_ATIVO, "319011", "31901146", tipo_linha="item_execucao", ano_mes=202601, liquidada=1.0, paga=0.0),  # adiantamento férias
        ])
        linhas = resultado.linhas[resultado.linhas["grupo"] == GRUPO_ATIVO]
        # 1 linha "11/12" (só o regular) + 4 sub-rubricas soltas = 5 linhas no total.
        self.assertEqual(len(linhas), 5)
        codigos_detalhados = set(linhas["natureza_detalhada_cod"])
        self.assertEqual(codigos_detalhados, {"11/12", "31901143", "31901144", "31901145", "31901146"})
        linha_11_12 = linhas[linhas["natureza_despesa_cod"] == "11/12"].iloc[0]
        self.assertAlmostEqual(linha_11_12["meses"][0], 100.0)  # só o regular, sub-rubricas não entram aqui

    def test_13o_de_contrato_temporario_funde_de_volta_em_ed_04(self):
        resultado = self._grade([
            _linha_execucao(ACAO_ATIVO, "319004", "319004", tipo_linha="item_execucao", ano_mes=202601, liquidada=100.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319004", "31900413", tipo_linha="item_execucao", ano_mes=202601, liquidada=8.0, paga=0.0),  # 13º contrato temp.
        ])
        linhas = resultado.linhas[resultado.linhas["grupo"] == GRUPO_ATIVO]
        # nenhuma linha própria para o 13º do contrato temporário — soma dentro de ED_04.
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas.iloc[0]["natureza_despesa_cod"], "04")
        self.assertAlmostEqual(linhas.iloc[0]["meses"][0], 108.0)

    def test_elemento_fora_da_lista_fixa_vai_para_outros_com_alerta(self):
        # 319001 tem regra própria (x12), mas o elemento 01 não está na lista fixa do
        # relatório-modelo para a aba Ativo — não pode sumir, tem que aparecer em
        # "Outros / Não Classificado" com um alerta visível.
        resultado = self._grade([
            _linha_execucao(ACAO_ATIVO, "319001", "319001", tipo_linha="item_execucao", ano_mes=202601, liquidada=42.0, paga=0.0),
        ])
        linhas = resultado.linhas[resultado.linhas["grupo"] == GRUPO_ATIVO]
        self.assertEqual(list(linhas["natureza_despesa_cod"]), ["outros"])
        self.assertAlmostEqual(linhas.iloc[0]["meses"][0], 42.0)
        self.assertTrue(any("outros" in a.lower() or "Outros" in a for a in resultado.alertas))

    def test_grupos_fora_de_ativo_nao_sao_alterados(self):
        resultado = self._grade([
            _linha_execucao(ACAO_INATIVO, "319001", "319001", tipo_linha="item_execucao", ano_mes=202601, liquidada=77.0, paga=0.0),
        ])
        linhas = resultado.linhas[resultado.linhas["grupo"] == GRUPO_INATIVO]
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas.iloc[0]["natureza_despesa_cod"], "319001")  # não passa pela curadoria de Ativo


class TestGradeMensalBeneficios(unittest.TestCase):
    """Pedido do usuário (10/09/2026): evidenciar Outros Benefícios por PLANO
    ORÇAMENTÁRIO, não por elemento de despesa — achado real na base: um PO mistura
    naturezas com regras de projeção diferentes entre si, e a MESMA natureza aparece
    em POs diferentes (ex. 339004 em "Assistência Pré-Escolar" e em "Auxílio-
    Transporte")."""

    def _grade(self, linhas_mensal, ano_mes=202601):
        mensal = pd.DataFrame(linhas_mensal)
        return grade_mensal_beneficios(mensal, _ANUAL_VAZIO, ano_mes // 100, ano_mes)

    def test_po_soma_naturezas_com_regras_diferentes(self):
        # 339004 (x13,3333) + 339008 (x12) no MESMO PO "0001" — devem virar 1 linha só.
        resultado = self._grade([
            _linha_execucao(ACAO_BENEFICIOS_OBRIGATORIOS, "339004", "339004",
                             tipo_linha="item_execucao", ano_mes=202601, liquidada=120.0, paga=0.0,
                             po_cod="0001", po_desc="ASSISTENCIA PRE-ESCOLAR", acao_desc="BENEFICIOS OBRIGATORIOS"),
            _linha_execucao(ACAO_BENEFICIOS_OBRIGATORIOS, "339008", "339008",
                             tipo_linha="item_execucao", ano_mes=202601, liquidada=50.0, paga=0.0,
                             po_cod="0001", po_desc="ASSISTENCIA PRE-ESCOLAR", acao_desc="BENEFICIOS OBRIGATORIOS"),
        ])
        linhas = resultado.linhas
        self.assertEqual(len(linhas), 1)
        linha = linhas.iloc[0]
        self.assertEqual(linha["natureza_despesa_cod"], ACAO_BENEFICIOS_OBRIGATORIOS)
        self.assertEqual(linha["natureza_detalhada_cod"], "0001")
        self.assertEqual(linha["natureza_detalhada_desc"], "ASSISTENCIA PRE-ESCOLAR")
        self.assertAlmostEqual(linha["meses"][0], 170.0)

    def test_mesma_natureza_em_pos_diferentes_nao_se_mistura(self):
        resultado = self._grade([
            _linha_execucao(ACAO_BENEFICIOS_OBRIGATORIOS, "339004", "339004",
                             tipo_linha="item_execucao", ano_mes=202601, liquidada=120.0, paga=0.0,
                             po_cod="0001", po_desc="ASSISTENCIA PRE-ESCOLAR", acao_desc=""),
            _linha_execucao(ACAO_BENEFICIOS_OBRIGATORIOS, "339004", "339004",
                             tipo_linha="item_execucao", ano_mes=202601, liquidada=80.0, paga=0.0,
                             po_cod="0003", po_desc="AUXILIO-TRANSPORTE", acao_desc=""),
        ])
        linhas = resultado.linhas.set_index("natureza_detalhada_cod")
        self.assertEqual(len(linhas), 2)
        self.assertAlmostEqual(linhas.loc["0001", "meses"][0], 120.0)
        self.assertAlmostEqual(linhas.loc["0003", "meses"][0], 80.0)

    def test_natureza_sem_regra_gera_alerta_por_po_nao_erro(self):
        resultado = self._grade([
            _linha_execucao(ACAO_ASSISTENCIA_MEDICA, "339093", "33909308",
                             tipo_linha="item_execucao", ano_mes=202601, liquidada=100.0, paga=0.0,
                             po_cod="0001", po_desc="ASSISTENCIA MEDICA", acao_desc=""),
        ])
        self.assertEqual(resultado.erros, [])
        self.assertEqual(len(resultado.alertas), 1)
        self.assertIn("PO 0001", resultado.alertas[0])
        self.assertAlmostEqual(resultado.linhas.iloc[0]["meses"][0], 100.0)

    def test_mes_futuro_projeta_por_natureza_antes_de_somar_por_po(self):
        # referência = jan/202601; fev é mês futuro sem bump de 13º (só jun/nov) — cada
        # natureza projeta pela própria regra e só DEPOIS soma por PO.
        resultado = self._grade([
            _linha_execucao(ACAO_BENEFICIOS_OBRIGATORIOS, "339004", "339004",
                             tipo_linha="item_execucao", ano_mes=202601, liquidada=120.0, paga=0.0,
                             po_cod="0001", po_desc="X", acao_desc=""),
            _linha_execucao(ACAO_BENEFICIOS_OBRIGATORIOS, "339008", "339008",
                             tipo_linha="item_execucao", ano_mes=202601, liquidada=50.0, paga=0.0,
                             po_cod="0001", po_desc="X", acao_desc=""),
        ])
        linha = resultado.linhas.iloc[0]
        self.assertAlmostEqual(linha["meses"][1], 170.0)


class TestSubstituirBeneficiosPorPlanoOrcamentario(unittest.TestCase):
    def test_troca_beneficios_mantem_ativo_intacto(self):
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "319011", tipo_linha="item_execucao", ano_mes=202601, liquidada=1000.0, paga=0.0),
            _linha_execucao(ACAO_BENEFICIOS_OBRIGATORIOS, "339046", "339046", tipo_linha="item_execucao", ano_mes=202601, liquidada=200.0, paga=0.0,
                             po_cod="0005", po_desc="AUXILIO-ALIMENTACAO", acao_desc=""),
        ])
        grade = consolidar_relatorio_ativo(consolidar_por_elemento(grade_mensal(mensal, _ANUAL_VAZIO, 2026, 202601)))
        resultado = substituir_beneficios_por_plano_orcamentario(grade, mensal, _ANUAL_VAZIO)

        ativo = resultado.linhas[resultado.linhas["grupo"] == GRUPO_ATIVO]
        self.assertEqual(len(ativo), 1)
        self.assertEqual(ativo.iloc[0]["natureza_despesa_cod"], "11/12")  # curadoria do Ativo intacta

        beneficios = resultado.linhas[resultado.linhas["grupo"] == GRUPO_OUTROS_BENEFICIOS]
        self.assertEqual(len(beneficios), 1)
        self.assertEqual(beneficios.iloc[0]["natureza_detalhada_cod"], "0005")  # por PO, não mais por elemento (339046)

    def test_total_de_beneficios_preservado_na_troca(self):
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_BENEFICIOS_OBRIGATORIOS, "339046", "339046", tipo_linha="item_execucao", ano_mes=202601, liquidada=200.0, paga=0.0,
                             po_cod="0005", po_desc="X", acao_desc=""),
            _linha_execucao(ACAO_BENEFICIOS_OBRIGATORIOS, "339049", "339049", tipo_linha="item_execucao", ano_mes=202601, liquidada=30.0, paga=0.0,
                             po_cod="0003", po_desc="Y", acao_desc=""),
        ])
        grade = consolidar_relatorio_ativo(consolidar_por_elemento(grade_mensal(mensal, _ANUAL_VAZIO, 2026, 202601)))
        total_antes = grade.total_por_grupo_por_mes().loc[GRUPO_OUTROS_BENEFICIOS, 1]
        resultado = substituir_beneficios_por_plano_orcamentario(grade, mensal, _ANUAL_VAZIO)
        total_depois = resultado.total_por_grupo_por_mes().loc[GRUPO_OUTROS_BENEFICIOS, 1]
        self.assertAlmostEqual(total_antes, total_depois)

    def test_alerta_antigo_por_natureza_e_substituido_pelo_de_po(self):
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ASSISTENCIA_MEDICA, "339093", "33909308", tipo_linha="item_execucao", ano_mes=202601, liquidada=10.0, paga=0.0,
                             po_cod="0001", po_desc="X", acao_desc=""),
        ])
        grade = consolidar_relatorio_ativo(consolidar_por_elemento(grade_mensal(mensal, _ANUAL_VAZIO, 2026, 202601)))
        self.assertTrue(any("grupo outros_beneficios" in a for a in grade.alertas))
        resultado = substituir_beneficios_por_plano_orcamentario(grade, mensal, _ANUAL_VAZIO)
        self.assertFalse(any("grupo outros_beneficios" in a for a in resultado.alertas))
        self.assertTrue(any("PO 0001" in a for a in resultado.alertas))


class TestSaldoRemanescente(unittest.TestCase):
    def test_saldo_acumula_mes_a_mes_e_pode_ficar_negativo(self):
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202601, liquidada=40_000.0, paga=0.0),
        ])
        anual_vazio = pd.DataFrame(columns=[
            "acao_cod", "ano", "natureza_despesa_cod", "natureza_despesa_desc",
            "natureza_detalhada_cod", "natureza_detalhada_desc", "empenhada",
        ])
        grade = grade_mensal(mensal, anual_vazio, 2026, 202601)
        # dotação pequena o bastante pra estourar antes do fim do ano (12 x 40.000 = 480.000).
        dotacao = pd.Series({GRUPO_ATIVO: 100_000.0})
        saldo = saldo_remanescente(grade, dotacao)
        linha = saldo[saldo["grupo"] == GRUPO_ATIVO].iloc[0]
        self.assertAlmostEqual(linha["meses"][0], 100_000.0 - 40_000.0)  # após Jan
        self.assertAlmostEqual(linha["meses"][1], 100_000.0 - 80_000.0)  # após Fev
        self.assertLess(linha["meses"][11], 0)  # estoura antes de dezembro


class TestSaldoRemanescenteBeneficiosPorAcao(unittest.TestCase):
    """Decisão 12 (22/09/2026): separar o Saldo Remanescente de Outros Benefícios entre
    2004 (Assistência Médica) e 212B (Benefícios Obrigatórios) — pedido do usuário pra
    não mascarar déficit de UMA ação com a folga da outra."""

    def test_deficit_de_uma_acao_nao_e_mascarado_pela_folga_da_outra(self):
        # Ambas x12 (sem 13º) pra manter a conta simples e previsível: 2004 projeta
        # 10.000 x 12 = 120.000 (> 100.000 de dotação, estoura); 212B projeta
        # 1.000 x 12 = 12.000 (<< 100.000 de dotação, sobra folgada).
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ASSISTENCIA_MEDICA, "339008", "339008", tipo_linha="item_execucao", ano_mes=202601, liquidada=10_000.0, paga=0.0,
                             po_cod="0001", po_desc="X", acao_desc=""),
            _linha_execucao(ACAO_BENEFICIOS_OBRIGATORIOS, "339046", "339046", tipo_linha="item_execucao", ano_mes=202601, liquidada=1_000.0, paga=0.0,
                             po_cod="0005", po_desc="Y", acao_desc=""),
        ])
        grade = consolidar_relatorio_ativo(consolidar_por_elemento(grade_mensal(mensal, _ANUAL_VAZIO, 2026, 202601)))
        grade = substituir_beneficios_por_plano_orcamentario(grade, mensal, _ANUAL_VAZIO)
        # 2004 tem dotação apertada (estoura); 212B tem dotação folgada — juntas (nível
        # de grupo) ainda sobra saldo, escondendo o déficit específico de 2004.
        dotacao_por_acao = pd.Series({ACAO_ASSISTENCIA_MEDICA: 100_000.0, ACAO_BENEFICIOS_OBRIGATORIOS: 100_000.0})
        saldo = saldo_remanescente_beneficios_por_acao(grade, dotacao_por_acao)

        linha_2004 = saldo[saldo["acao_cod"] == ACAO_ASSISTENCIA_MEDICA].iloc[0]
        linha_212b = saldo[saldo["acao_cod"] == ACAO_BENEFICIOS_OBRIGATORIOS].iloc[0]
        self.assertLess(linha_2004["meses"][11], 0)  # 2004 estoura sozinha
        self.assertGreater(linha_212b["meses"][11], 0)  # 212B sobra sozinha

        dotacao_grupo = pd.Series({GRUPO_OUTROS_BENEFICIOS: 200_000.0})
        saldo_grupo = saldo_remanescente(grade, dotacao_grupo)
        linha_grupo = saldo_grupo[saldo_grupo["grupo"] == GRUPO_OUTROS_BENEFICIOS].iloc[0]
        self.assertGreater(linha_grupo["meses"][11], 0)  # nível de grupo esconde o déficit


if __name__ == "__main__":
    unittest.main()


class TestParametrosProjecao(unittest.TestCase):
    """27/09/2026 — fórmulas editáveis: o padrão reproduz as decisões confirmadas e
    cada campo ajustado muda só a parte da fórmula que ele representa."""

    _mensal = TestGradeMensal._mensal
    _anual_vazio = TestGradeMensal._anual_vazio

    def test_padrao_nao_altera_a_grade(self):
        sem = grade_mensal(self._mensal(), self._anual_vazio(), 2026, 202608)
        com = grade_mensal(self._mensal(), self._anual_vazio(), 2026, 202608, PARAMETROS_PADRAO)
        self.assertEqual(sem.linhas["meses"].tolist(), com.linhas["meses"].tolist())
        self.assertEqual(diferencas_do_padrao(PARAMETROS_PADRAO), [])
        self.assertEqual(diferencas_do_padrao(None), [])

    def test_multiplicador_por_natureza_muda_so_a_rubrica(self):
        parametros = ParametrosProjecao(multiplicadores_natureza={"319004": 14.0})
        self.assertEqual(regra_para_natureza("319004", "31900401", parametros).multiplicador, 14.0)
        self.assertEqual(regra_para_natureza("319004", "31900401").multiplicador, MULTIPLICADOR_13_3333)
        # a tabela global nunca é modificada
        self.assertEqual(TABELA_REGRAS["319004"].multiplicador, MULTIPLICADOR_13_3333)
        resultado = grade_mensal(self._mensal(), self._anual_vazio(), 2026, 202608, parametros)
        linha = resultado.linhas[resultado.linhas["natureza_despesa_cod"] == "319004"].iloc[0]
        # Nov = R + metade de (14 − 12) × R
        self.assertAlmostEqual(linha["meses"][MES_PARCELA_DECIMO_TERCEIRO - 1], 9_000.0 + 9_000.0)
        self.assertEqual(diferencas_do_padrao(parametros), ["natureza 319004: x13,3333 → x14"])

    def test_multiplicador_por_grupo_de_sentenca_e_indenizacao(self):
        parametros = ParametrosProjecao(sentenca_inativo=14.0, indenizacao_demais=13.0)
        self.assertEqual(multiplicador_efetivo(regra_para_natureza("319091", "x"), GRUPO_INATIVO, parametros), 14.0)
        self.assertAlmostEqual(multiplicador_efetivo(regra_para_natureza("319091", "x"), GRUPO_ATIVO, parametros), MULTIPLICADOR_13_3333)
        self.assertEqual(multiplicador_efetivo(regra_para_natureza("319094", "x"), GRUPO_ATIVO, parametros), 13.0)

    def test_meses_e_fracao_do_decimo_terceiro(self):
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202601, liquidada=100.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901143", tipo_linha="item_execucao", ano_mes=202601, liquidada=100.0, paga=0.0),
        ])
        parametros = ParametrosProjecao(mes_antecipacao_13=7, mes_parcela_13=12, fracao_antecipacao_13=0.4,
                                        dezembro_ativo_repete_novembro=False)
        resultado = grade_mensal(mensal, self._anual_vazio(), 2026, 202601, parametros)
        linha13 = resultado.linhas[resultado.linhas["natureza_detalhada_cod"] == "31901143"].iloc[0]
        self.assertAlmostEqual(linha13["meses"][6], 40.0)   # Jul: antecipação (40%)
        self.assertAlmostEqual(linha13["meses"][11], 60.0)  # Dez: parcela final (60%)
        self.assertAlmostEqual(linha13["meses"][5], 0.0)    # Jun deixa de receber
        self.assertAlmostEqual(linha13["meses"][10], 0.0)   # Nov deixa de receber

    def test_dezembro_do_ativo_pode_deixar_de_repetir_novembro(self):
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319004", "31900401", tipo_linha="item_execucao", ano_mes=202608, liquidada=9_000.0, paga=0.0),
        ])
        padrao = grade_mensal(mensal, self._anual_vazio(), 2026, 202608).linhas.iloc[0]["meses"]
        self.assertAlmostEqual(padrao[11], padrao[10])
        ajustada = grade_mensal(mensal, self._anual_vazio(), 2026, 202608,
                                ParametrosProjecao(dezembro_ativo_repete_novembro=False)).linhas.iloc[0]["meses"]
        self.assertAlmostEqual(ajustada[11], 9_000.0)

    def test_extra_da_patronal_pode_voltar_a_ser_dividido(self):
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_RPPS, "319113", "31911301", tipo_linha="item_execucao", ano_mes=202601, liquidada=10_000.0, paga=0.0),
        ])
        parametros = ParametrosProjecao(extra_concentrado_natureza={"319113": False})
        linha = grade_mensal(mensal, self._anual_vazio(), 2026, 202601, parametros).linhas.iloc[0]
        self.assertAlmostEqual(linha["meses"][5], 15_000.0)
        self.assertAlmostEqual(linha["meses"][10], 15_000.0)

    def test_sem_regra_beneficios_usa_multiplicador_ajustado_e_avisa(self):
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_BENEFICIOS_OBRIGATORIOS, "339039", "33903901", tipo_linha="item_execucao",
                            ano_mes=202601, liquidada=100.0, paga=0.0),
        ])
        parametros = ParametrosProjecao(multiplicador_sem_regra_beneficios=14.0)
        resultado = grade_mensal(mensal, self._anual_vazio(), 2026, 202601, parametros)
        self.assertAlmostEqual(resultado.linhas.iloc[0]["meses"][10], 200.0)  # R + metade de 2 × R
        self.assertTrue(any("x14 da decisão 5" in a for a in resultado.alertas))

    def test_criterio_de_mes_fechado_editavel(self):
        df = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=m, liquidada=v, paga=0.0)
            for m, v in ((202606, 1000.0), (202607, 1000.0), (202608, 600.0))
        ])
        self.assertEqual(ultimo_mes_fechado(df), 202608)  # 600 >= 50% de 1000
        self.assertEqual(ultimo_mes_fechado(df, ParametrosProjecao(fracao_minima_fechamento=0.8)), 202607)

    def test_validacao_recusa_valores_sem_regra_definida(self):
        for ajuste in (
            {"sentenca_ativo": 11.9}, {"sentenca_ativo": float("nan")}, {"indenizacao_demais": True},
            {"multiplicadores_natureza": {"319011": 10.0}}, {"multiplicadores_natureza": {"319091": 13.0}},
            {"multiplicadores_natureza": {"999999": 13.0}}, {"extra_concentrado_natureza": {"319092": True}},
            {"mes_antecipacao_13": 0}, {"mes_parcela_13": 13}, {"mes_antecipacao_13": 11},
            {"fracao_antecipacao_13": 1.5}, {"fracao_minima_fechamento": -0.1}, {"janela_meses_fechamento": 0},
        ):
            with self.subTest(ajuste=ajuste), self.assertRaises(ValueError):
                ParametrosProjecao(**ajuste)


class TestExecucaoExerciciosAnteriores(unittest.TestCase):
    def _anual(self):
        return pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", ano=2025, tipo_linha="empenho", empenhada=1000.0, liquidada=0.0, paga=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", ano=2025, tipo_linha="item_execucao", empenhada=0.0, liquidada=900.0, paga=-5.0),
            _linha_execucao(ACAO_INATIVO, "319001", "31900101", ano=2025, tipo_linha="empenho", empenhada=300.0, liquidada=None, paga=None),
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", ano=2026, tipo_linha="empenho", empenhada=9999.0, liquidada=0.0, paga=0.0),
            _linha_execucao("20RK", "339030", "33903001", ano=2025, tipo_linha="empenho", empenhada=77.0, liquidada=0.0, paga=0.0),
        ])

    def test_por_grupo_so_do_exercicio_preserva_nulo_e_negativo(self):
        resultado = execucao_exercicio_por_grupo(self._anual(), 2025).set_index("grupo")
        self.assertEqual(list(resultado.index), [GRUPO_ATIVO, GRUPO_INATIVO])
        self.assertEqual(resultado.loc[GRUPO_ATIVO, "empenhada"], 1000.0)
        self.assertEqual(resultado.loc[GRUPO_ATIVO, "liquidada"], 900.0)
        self.assertEqual(resultado.loc[GRUPO_ATIVO, "paga"], -5.0)
        self.assertTrue(pd.isna(resultado.loc[GRUPO_INATIVO, "liquidada"]))

    def test_por_natureza_mantem_codigo_como_texto(self):
        resultado = execucao_exercicio_por_natureza(self._anual(), 2025)
        self.assertEqual(resultado["natureza_despesa_cod"].tolist(), ["319011", "319001"])
        self.assertEqual(resultado.iloc[0]["natureza_despesa_desc"], "NATUREZA 319011")

    def test_medida_ausente_vira_nulo(self):
        anual = self._anual().drop(columns="paga")
        self.assertTrue(execucao_exercicio_por_grupo(anual, 2025)["paga"].isna().all())

    def test_liquidada_mensal_nulo_em_mes_sem_dado(self):
        mensal = pd.DataFrame([
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202501, liquidada=10.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202503, liquidada=0.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="empenho", ano_mes=202503, liquidada=999.0),
            _linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao", ano_mes=202601, liquidada=50.0),
        ])
        resultado = liquidada_mensal_por_grupo(mensal, 2025)
        self.assertEqual(resultado.loc[GRUPO_ATIVO, 1], 10.0)
        self.assertTrue(pd.isna(resultado.loc[GRUPO_ATIVO, 2]))
        self.assertEqual(resultado.loc[GRUPO_ATIVO, 3], 0.0)
        self.assertTrue(liquidada_mensal_por_grupo(mensal, 2024).empty)


class TestProjecaoReconstruidaComExecutado(unittest.TestCase):
    """27/09/2026 — projeção de um exercício passado × Liquidada real. Valores
    esperados calculados à mão nos comentários."""

    def _mensal(self):
        linhas = []
        # Ativo 319011 (x12): Jan-Ago = 100; real Set-Dez = 110, 120, 130, 140.
        for mes, valor in [*((m, 100.0) for m in range(1, 9)), (9, 110.0), (10, 120.0), (11, 130.0), (12, 140.0)]:
            linhas.append(_linha_execucao(ACAO_ATIVO, "319011", "31901101", tipo_linha="item_execucao",
                                          ano_mes=202500 + mes, liquidada=valor, paga=0.0, po_cod="0000", po_desc=""))
        # Inativo 319001 (x12): Jan-Set = 50; Out-Dez sem linha na base (nulo, não zero).
        for mes in range(1, 10):
            linhas.append(_linha_execucao(ACAO_INATIVO, "319001", "31900101", tipo_linha="item_execucao",
                                          ano_mes=202500 + mes, liquidada=50.0, paga=0.0, po_cod="0000", po_desc=""))
        return pd.DataFrame(linhas)

    def _anual_vazio(self):
        return TestGradeMensal._anual_vazio(self)

    def test_mes_a_mes_compara_projecao_com_liquidada(self):
        comparacao = comparar_projecao_com_executado(self._mensal(), self._anual_vazio(), 2025, 8)
        ativo = comparacao[comparacao["grupo"] == GRUPO_ATIVO]
        # projeção a partir de Ago = 100 em Set-Dez (Dez repete Nov = 100).
        self.assertEqual(ativo["mes"].tolist(), [9, 10, 11, 12])
        self.assertEqual(ativo["projetado"].tolist(), [100.0] * 4)
        self.assertEqual(ativo["executado"].tolist(), [110.0, 120.0, 130.0, 140.0])
        self.assertEqual(ativo["diferenca"].tolist(), [10.0, 20.0, 30.0, 40.0])
        inativo = comparacao[comparacao["grupo"] == GRUPO_INATIVO]
        self.assertEqual(inativo["executado"].iloc[0], 50.0)
        self.assertEqual(inativo["diferenca"].iloc[0], 0.0)
        self.assertTrue(inativo["executado"].iloc[1:].isna().all())
        self.assertTrue(inativo["diferenca"].iloc[1:].isna().all())

    def test_resumo_so_soma_meses_com_os_dois_lados(self):
        resumo = resumo_projecao_com_executado(
            comparar_projecao_com_executado(self._mensal(), self._anual_vazio(), 2025, 8)
        ).set_index("grupo")
        self.assertEqual(resumo.loc[GRUPO_ATIVO, "meses"], 4)
        self.assertEqual(resumo.loc[GRUPO_ATIVO, "projetado"], 400.0)
        self.assertEqual(resumo.loc[GRUPO_ATIVO, "executado"], 500.0)
        self.assertEqual(resumo.loc[GRUPO_ATIVO, "diferenca"], 100.0)
        self.assertAlmostEqual(resumo.loc[GRUPO_ATIVO, "diferenca_pct"], 0.25)
        # Inativo: só Set tem executado — Out-Dez projetados (150) ficam fora da soma.
        self.assertEqual(resumo.loc[GRUPO_INATIVO, "meses"], 1)
        self.assertEqual(resumo.loc[GRUPO_INATIVO, "projetado"], 50.0)
        self.assertEqual(resumo.loc[GRUPO_INATIVO, "diferenca_pct"], 0.0)
        self.assertEqual(resumo.loc["total", "meses"], 4)
        self.assertEqual(resumo.loc["total", "projetado"], 450.0)
        self.assertEqual(resumo.loc["total", "executado"], 550.0)
        self.assertAlmostEqual(resumo.loc["total", "diferenca_pct"], 100.0 / 450.0)

    def test_usa_os_parametros_em_uso(self):
        # Sem repetir Nov em Dez, o Ativo continua liso (100) — mesmo resultado aqui;
        # com parcela final em Dez e 319011 x13, Dez recebe metade do extra: 100 + 50.
        parametros = ParametrosProjecao(multiplicadores_natureza={"319011": 13.0}, mes_parcela_13=12,
                                        dezembro_ativo_repete_novembro=False)
        comparacao = comparar_projecao_com_executado(self._mensal(), self._anual_vazio(), 2025, 8, parametros)
        ativo = comparacao[comparacao["grupo"] == GRUPO_ATIVO].set_index("mes")
        self.assertEqual(ativo.loc[12, "projetado"], 150.0)
        self.assertEqual(ativo.loc[12, "diferenca"], -10.0)

    def test_mes_de_referencia_sem_mes_a_projetar_e_recusado(self):
        for mes in (0, 12):
            with self.subTest(mes=mes), self.assertRaises(ValueError):
                comparar_projecao_com_executado(self._mensal(), self._anual_vazio(), 2025, mes)


class TestDesvioPorMesDePartida(unittest.TestCase):
    """Mesmo cenário de `TestProjecaoReconstruidaComExecutado`: Ativo 100 em Jan-Ago e
    110/120/130/140 em Set-Dez; Inativo 50 em Jan-Set e sem linha em Out-Dez."""

    _mensal = TestProjecaoReconstruidaComExecutado._mensal
    _anual_vazio = TestProjecaoReconstruidaComExecutado._anual_vazio

    def test_uma_linha_por_mes_de_partida_com_dado_e_valores_a_mao(self):
        desvio = desvio_por_mes_de_partida(self._mensal(), self._anual_vazio(), 2025)
        self.assertEqual(sorted(desvio["mes_referencia"].unique()), list(range(1, 12)))
        por = desvio.set_index(["mes_referencia", "grupo"])
        # Partida Out: Ativo projeta 120 em Nov e Dez; executado 130 + 140 → diferença 30 / 240.
        self.assertEqual(por.loc[(10, GRUPO_ATIVO), "projetado"], 240.0)
        self.assertEqual(por.loc[(10, GRUPO_ATIVO), "diferenca"], 30.0)
        self.assertAlmostEqual(por.loc[(10, GRUPO_ATIVO), "diferenca_pct"], 0.125)
        # Inativo sem Liquidada em Out: não há projeção nem executado comparáveis (nulo, não 0).
        self.assertEqual(por.loc[(10, GRUPO_INATIVO), "meses"], 0)
        self.assertTrue(pd.isna(por.loc[(10, GRUPO_INATIVO), "diferenca_pct"]))
        self.assertAlmostEqual(por.loc[(10, "total"), "diferenca_pct"], 0.125)
        # Partida Set: Ativo projeta 110 × 3 = 330; executado 120 + 130 + 140 = 390.
        self.assertAlmostEqual(por.loc[(9, GRUPO_ATIVO), "diferenca_pct"], 60.0 / 330.0)

    def test_bate_com_a_comparacao_individual_de_cada_mes(self):
        desvio = desvio_por_mes_de_partida(self._mensal(), self._anual_vazio(), 2025)
        for mes in range(1, 12):
            with self.subTest(mes=mes):
                individual = resumo_projecao_com_executado(
                    comparar_projecao_com_executado(self._mensal(), self._anual_vazio(), 2025, mes)
                )
                do_mes = desvio.loc[desvio["mes_referencia"] == mes].drop(columns="mes_referencia")
                pd.testing.assert_frame_equal(do_mes.reset_index(drop=True), individual.reset_index(drop=True),
                                              check_dtype=False)

    def test_mes_sem_liquidada_nao_vira_linha(self):
        mensal = self._mensal()
        mensal = mensal[mensal["ano_mes"] != 202503]
        desvio = desvio_por_mes_de_partida(mensal, self._anual_vazio(), 2025)
        self.assertNotIn(3, set(desvio["mes_referencia"]))
        self.assertTrue(desvio_por_mes_de_partida(mensal, self._anual_vazio(), 2024).empty)


class TestBeneficiosPorPlanoOrcamentario(unittest.TestCase):
    """Outros Benefícios por (Ação, PO), 2025, partida Ago. Todas x12, sem repetição
    de dezembro (exclusiva do Ativo): cada mês futuro projeta o valor de Ago.
      212B/0005 Alimentação  100 em Jan-Ago, 110 em Set-Dez → +40 (+10%)
      212B/0003 Transporte    50 em Jan-Ago,  40 em Set-Dez → −40 (−20%)
      2004/0001 Assist. Méd.  20 o ano todo                 →   0
      212B/0001 Pré-Escolar   30 o ano todo                 →   0 (mesmo código de PO de 2004)
    Total: projetado 4 × 200 = 800, executado 800."""

    _anual_vazio = TestProjecaoReconstruidaComExecutado._anual_vazio

    def _mensal(self):
        planos = [
            (ACAO_BENEFICIOS_OBRIGATORIOS, "0005", "339046", "ALIMENTACAO", 100.0, 110.0),
            (ACAO_BENEFICIOS_OBRIGATORIOS, "0003", "339049", "TRANSPORTE", 50.0, 40.0),
            (ACAO_ASSISTENCIA_MEDICA, "0001", "339008", "ASSISTENCIA MEDICA", 20.0, 20.0),
            (ACAO_BENEFICIOS_OBRIGATORIOS, "0001", "339008", "PRE-ESCOLAR", 30.0, 30.0),
        ]
        linhas = []
        for acao, po, natureza, desc, ate_ago, depois in planos:
            for mes in range(1, 13):
                linhas.append(_linha_execucao(
                    acao, natureza, natureza + "01", tipo_linha="item_execucao", ano_mes=202500 + mes,
                    liquidada=ate_ago if mes <= 8 else depois, paga=0.0, po_cod=po, po_desc=desc,
                ))
        return pd.DataFrame(linhas)

    def test_desvio_por_plano_com_valores_a_mao(self):
        comparacao = comparar_beneficios_por_plano_orcamentario(self._mensal(), self._anual_vazio(), 2025, 8)
        resumo = resumo_projecao_com_executado(comparacao, chave="plano").set_index("plano")
        self.assertEqual(list(resumo.index), ["2004/0001", "212B/0001", "212B/0003", "212B/0005", "total"])
        self.assertEqual(resumo.loc["212B/0005", "diferenca"], 40.0)
        self.assertAlmostEqual(resumo.loc["212B/0005", "diferenca_pct"], 0.10)
        self.assertEqual(resumo.loc["212B/0003", "diferenca"], -40.0)
        self.assertAlmostEqual(resumo.loc["212B/0003", "diferenca_pct"], -0.20)
        # mesmo código "0001" nas duas ações: linhas separadas, cada uma com o seu valor.
        self.assertEqual(resumo.loc["2004/0001", "projetado"], 80.0)
        self.assertEqual(resumo.loc["212B/0001", "projetado"], 120.0)
        self.assertEqual(resumo.loc["total", "projetado"], 800.0)
        self.assertEqual(resumo.loc["total", "executado"], 800.0)
        rotulos = comparacao.drop_duplicates("plano").set_index("plano")
        self.assertEqual(rotulos.loc["212B/0001", "po_desc"], "PRE-ESCOLAR")
        self.assertEqual(rotulos.loc["212B/0001", "po_cod"], "0001")  # zero à esquerda preservado

    def test_soma_dos_planos_fecha_com_a_linha_do_grupo(self):
        for mes in (1, 5, 8, 11):
            with self.subTest(mes=mes):
                por_plano = resumo_projecao_com_executado(
                    comparar_beneficios_por_plano_orcamentario(self._mensal(), self._anual_vazio(), 2025, mes), chave="plano",
                ).set_index("plano").loc["total"]
                grupo = resumo_projecao_com_executado(
                    comparar_projecao_com_executado(self._mensal(), self._anual_vazio(), 2025, mes)
                ).set_index("grupo").loc[GRUPO_OUTROS_BENEFICIOS]
                self.assertAlmostEqual(por_plano["projetado"], grupo["projetado"])
                self.assertAlmostEqual(por_plano["executado"], grupo["executado"])

    def test_percentual_nulo_sobre_projetado_zero_ou_negativo(self):
        comparacao = pd.DataFrame([
            {"plano": "A", "mes": 9, "projetado": -100.0, "executado": 50.0, "diferenca": 150.0},
            {"plano": "B", "mes": 9, "projetado": 0.0, "executado": 5.0, "diferenca": 5.0},
        ])
        resumo = resumo_projecao_com_executado(comparacao, chave="plano").set_index("plano")
        self.assertTrue(pd.isna(resumo.loc["A", "diferenca_pct"]))
        self.assertTrue(pd.isna(resumo.loc["B", "diferenca_pct"]))
        self.assertEqual(resumo.loc["A", "diferenca"], 150.0)  # a diferença em R$ continua lá

    def test_executado_sem_po_aparece_explicito(self):
        mensal = self._mensal()
        mensal.loc[mensal["po_desc"] == "TRANSPORTE", "po_cod"] = None
        comparacao = comparar_beneficios_por_plano_orcamentario(mensal, self._anual_vazio(), 2025, 8)
        self.assertIn(f"{ACAO_BENEFICIOS_OBRIGATORIOS}/{SEM_PLANO_ORCAMENTARIO}", set(comparacao["plano"]))
        sem_po = comparacao[comparacao["po_cod"] == SEM_PLANO_ORCAMENTARIO]
        self.assertEqual(sem_po["executado"].tolist(), [40.0] * 4)
