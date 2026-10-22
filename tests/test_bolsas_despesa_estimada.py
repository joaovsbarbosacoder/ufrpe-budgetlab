"""Testes de `src/bolsas_despesa_estimada.py` — despesa estimada por PTRES na cobertura de Bolsas (22/10/2026)."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.bolsas_despesa_estimada import despesa_estimada_por_ptres


def _cadastro(linhas: list[tuple]) -> pd.DataFrame:
    """Cada linha: (ptres, ne_curta, valor_anual)."""
    return pd.DataFrame(linhas, columns=["ptres", "ne_curta", "valor_anual"])


def _projecao(linhas: list[tuple]) -> pd.DataFrame:
    """Cada linha: (ne_curta, valor_empenhado, saldo, projetado_execucao)."""
    return pd.DataFrame(linhas, columns=["ne_curta", "valor_empenhado", "saldo", "projetado_execucao"])


def test_bolsa_com_ne_usa_executado_mais_projetado_e_nao_o_valor_anual_cheio():
    # PEC-G (Promisaes) com os números reais de 22/10/2026: cadastro 3.732 × 12; empenhado 26.124, saldo 1.244, projetado 11.196
    r = despesa_estimada_por_ptres(
        _cadastro([("230404", "2026NE000058", 44784.0)]), _projecao([("2026NE000058", 26124.0, 1244.0, 11196.0)])
    )
    assert r.despesa["230404"] == pytest.approx(24880.0 + 11196.0) == pytest.approx(36076.0)
    assert (r.pela_execucao, r.pelo_cadastro) == (1, 0)
    assert r.total_cadastro == pytest.approx(44784.0) and r.total_estimado == pytest.approx(36076.0)


def test_bolsa_sem_ne_ou_sem_linha_no_relatorio_segue_pelo_valor_anual():
    cadastro = _cadastro([("A", None, 1000.0), ("B", "NE_SEM_LINHA", 500.0), ("C", "NE1", 300.0)])
    r = despesa_estimada_por_ptres(cadastro, _projecao([("NE1", 400.0, 100.0, 50.0)]))
    assert r.despesa["A"] == 1000.0 and r.despesa["B"] == 500.0
    assert r.despesa["C"] == pytest.approx(350.0)  # (400 − 100) + 50
    assert (r.pela_execucao, r.pelo_cadastro) == (1, 2)


def test_valor_nulo_na_projecao_nao_vira_zero_e_cai_no_cadastro():
    r = despesa_estimada_por_ptres(
        _cadastro([("A", "NE1", 800.0), ("B", "NE2", 600.0)]),
        _projecao([("NE1", 400.0, 100.0, float("nan")), ("NE2", float("nan"), 0.0, 10.0)]),
    )
    assert r.despesa["A"] == 800.0 and r.despesa["B"] == 600.0
    assert r.pela_execucao == 0 and r.pelo_cadastro == 2


def test_projecao_indisponivel_mantem_o_valor_anual_cadastrado():
    cadastro = _cadastro([("A", "NE1", 800.0), ("A", "NE2", 200.0)])
    for linhas in (None, _projecao([])):
        r = despesa_estimada_por_ptres(cadastro, linhas)
        assert r.despesa["A"] == 1000.0 and r.pela_execucao == 0 and r.pelo_cadastro == 2


def test_ne_compartilhada_e_repartida_pelo_peso_do_valor_anual_sem_contar_duas_vezes():
    cadastro = _cadastro([("A", "NE1", 600.0), ("B", "NE1", 200.0)])
    r = despesa_estimada_por_ptres(cadastro, _projecao([("NE1", 1000.0, 200.0, 100.0)]))  # total da NE: 800 + 100 = 900
    assert r.despesa["A"] == pytest.approx(675.0) and r.despesa["B"] == pytest.approx(225.0)
    assert r.despesa.sum() == pytest.approx(900.0)


def test_ne_compartilhada_sem_peso_reparte_em_partes_iguais():
    cadastro = _cadastro([("A", "NE1", math.nan), ("B", "NE1", math.nan)])
    r = despesa_estimada_por_ptres(cadastro, _projecao([("NE1", 500.0, 100.0, 100.0)]))
    assert r.despesa["A"] == pytest.approx(250.0) and r.despesa["B"] == pytest.approx(250.0)


def test_varias_bolsas_no_mesmo_ptres_somam():
    cadastro = _cadastro([("A", "NE1", 100.0), ("A", "NE2", 200.0), ("B", None, 50.0)])
    r = despesa_estimada_por_ptres(cadastro, _projecao([("NE1", 80.0, 10.0, 20.0), ("NE2", 150.0, 0.0, 30.0)]))
    assert r.despesa["A"] == pytest.approx(90.0 + 180.0) and r.despesa["B"] == 50.0
    assert r.despesa.index.name == "ptres_codigo"
