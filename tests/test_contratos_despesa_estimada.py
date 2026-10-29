"""Testes de `src/contratos_despesa_estimada.py` — despesa estimada por PTRES na cobertura de Contratos (29/10/2026)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.contratos_continuos import DESPESA_CONTRATUAL, DESPESA_EMPENHADO_SUSPENSO
from src.contratos_despesa_estimada import despesa_estimada_por_ptres


def _contratos(linhas: list[tuple]) -> pd.DataFrame:
    """Cada linha: (ptres, ne_curta, despesa_anual[, despesa_anual_base[, tem_aditivo_previsto]])."""
    registros = []
    for linha in linhas:
        ptres, ne, despesa = linha[:3]
        registros.append({
            "ptres": ptres, "ne_curta": ne, "despesa_anual": despesa,
            "despesa_anual_base": linha[3] if len(linha) > 3 else DESPESA_CONTRATUAL,
            "tem_aditivo_previsto": linha[4] if len(linha) > 4 else False,
        })
    return pd.DataFrame(registros)


def _projecao(linhas: list[tuple]) -> pd.DataFrame:
    """Cada linha: (ne_curta, valor_empenhado, saldo, projetado_execucao)."""
    return pd.DataFrame(linhas, columns=["ne_curta", "valor_empenhado", "saldo", "projetado_execucao"])


def test_contrato_com_ne_usa_liquidado_mais_projetado_e_nao_a_despesa_anual_contratual():
    r = despesa_estimada_por_ptres(_contratos([("230390", "NE1", 1200.0)]), _projecao([("NE1", 900.0, 200.0, 300.0)]))
    assert r.despesa["230390"] == pytest.approx(700.0 + 300.0)  # (900 − 200) + 300
    assert (r.pela_execucao, r.pelo_cadastro) == (1, 0)
    assert r.total_cadastro == pytest.approx(1200.0) and r.total_estimado == pytest.approx(1000.0)


def test_base_contratual_ou_projecao_indisponivel_mantem_a_despesa_anual():
    contratos = _contratos([("A", "NE1", 1200.0), ("A", "NE2", 800.0)])
    for linhas in (None, _projecao([])):
        r = despesa_estimada_por_ptres(contratos, linhas)
        assert r.despesa["A"] == 2000.0 and (r.pela_execucao, r.pelo_cadastro) == (0, 2)


def test_contrato_suspenso_segue_pelo_empenhado_que_a_pagina_ja_usa():
    contratos = _contratos([("A", "NE1", 500.0, DESPESA_EMPENHADO_SUSPENSO)])
    r = despesa_estimada_por_ptres(contratos, _projecao([("NE1", 900.0, 200.0, 300.0)]))
    assert r.despesa["A"] == 500.0 and r.pela_execucao == 0


def test_contrato_com_aditivo_previsto_segue_pela_despesa_anual_para_nao_perder_o_aditivo():
    contratos = _contratos([("A", "NE1", 1500.0, DESPESA_CONTRATUAL, True)])
    r = despesa_estimada_por_ptres(contratos, _projecao([("NE1", 900.0, 200.0, 300.0)]))
    assert r.despesa["A"] == 1500.0 and (r.pela_execucao, r.pelo_cadastro) == (0, 1)


def test_ne_compartilhada_nao_e_ratada_e_a_busca_nao_a_transforma_em_ne_unica():
    completa = _contratos([("A", "NE1", 600.0), ("A", "NE1", 400.0), ("A", "NE2", 100.0)])
    filtrada = completa.iloc[[0, 2]]  # a busca escondeu a segunda linha da NE1
    projecao = _projecao([("NE1", 1000.0, 0.0, 0.0), ("NE2", 80.0, 0.0, 10.0)])
    r = despesa_estimada_por_ptres(filtrada, projecao, tabela_completa=completa)
    assert r.despesa["A"] == pytest.approx(600.0 + 90.0)  # NE1 fica contratual; só NE2 vai pela execução
    assert (r.pela_execucao, r.pelo_cadastro) == (1, 1)
    # sem a tabela completa, a filtrada enganaria: a NE1 pareceria única
    enganada = despesa_estimada_por_ptres(filtrada, projecao)
    assert enganada.pela_execucao == 2


def test_sem_ne_sem_linha_ou_valor_nulo_seguem_pela_despesa_anual_e_nulo_nao_vira_zero():
    contratos = _contratos([("A", None, 100.0), ("B", "NE_SEM_LINHA", 200.0), ("C", "NE3", 300.0), ("D", "NE4", 400.0)])
    projecao = _projecao([("NE3", 50.0, 0.0, float("nan")), ("NE4", float("nan"), 0.0, 10.0)])
    r = despesa_estimada_por_ptres(contratos, projecao)
    assert [r.despesa[p] for p in "ABCD"] == [100.0, 200.0, 300.0, 400.0]
    assert r.pela_execucao == 0 and r.pelo_cadastro == 4


def test_varios_contratos_no_mesmo_ptres_somam_e_o_indice_tem_o_nome_esperado():
    contratos = _contratos([("A", "NE1", 1000.0), ("A", "NE2", 500.0), ("B", None, 70.0)])
    r = despesa_estimada_por_ptres(contratos, _projecao([("NE1", 800.0, 100.0, 50.0), ("NE2", 300.0, 0.0, 20.0)]))
    assert r.despesa["A"] == pytest.approx(750.0 + 320.0) and r.despesa["B"] == 70.0
    assert r.despesa.index.name == "ptres_codigo"
