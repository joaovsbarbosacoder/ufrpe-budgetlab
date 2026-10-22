"""Testes de `src/resultado_orcamentario_detalhe.py` — detalhamento por GND e Ação (20/10/2026).

Reaproveita os builders sintéticos de `tests/test_resultado_orcamentario.py`. Em todo cenário o detalhamento
precisa fechar com o `ResultadoOrcamentario` (cartões): dotação, executado, projetado e resultado.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.resultado_orcamentario_cadastro import DespesaManual
from src.resultado_orcamentario_detalhe import (
    TIPO_CELULA,
    TIPO_FORA,
    TIPO_SEM_CELULA,
    detalhar_por_gnd_acao,
)
from tests.test_resultado_orcamentario import (
    A,
    C,
    _cad_bolsas,
    _cad_contratos,
    _calc,
    _celulas,
    _empenhado,
    _empenhos_padrao,
    _manual,
    _nec,
)

# outro GND (4) e outra ação (20Z1)
D = ("0", "2", "20Z1", "100004", "0000", "4", "1000000000")
B = ("0", "2", "20Y0", "100002", "0000", "3", "1000000000")


def _celulas_com_d(dot_d=200.0) -> pd.DataFrame:
    extra = pd.DataFrame({"chave": [D], "dotacao_atualizada": pd.array([dot_d], dtype="Float64")})
    return pd.concat([_celulas(), extra], ignore_index=True)


def _linha(det, tipo, gnd=None, acao=None) -> pd.Series:
    linhas = det.linhas
    achadas = linhas.loc[
        (linhas["tipo"] == tipo)
        & ((linhas["gnd"] == gnd) if gnd is not None else True)
        & ((linhas["acao"] == acao) if acao is not None else True)
    ]
    assert len(achadas) == 1, achadas
    return achadas.iloc[0]


def test_cenario_padrao_fecha_com_os_cartoes():
    despesas = [_manual()]
    res = _calc(despesas_manuais=despesas)
    det = detalhar_por_gnd_acao(res, _celulas(), _empenhos_padrao(), [A, B], despesas)

    assert det.fecha and det.diferenca_conferencia == pytest.approx(0.0)
    assert det.dotacao == pytest.approx(res.dotacao)
    assert det.executado == pytest.approx(res.executado_total)
    assert det.projetado == pytest.approx(res.projetado_total)
    assert det.resultado == pytest.approx(res.resultado)

    grupo = _linha(det, TIPO_CELULA, "3", "20Y0")
    # dotação A + B; executado N1 300 + N2 150 + N3 100 (outros); projetado N1 120 + N2 40
    assert grupo["dotacao"] == pytest.approx(1500.0)
    assert grupo["executado"] == pytest.approx(550.0)
    assert grupo["projetado"] == pytest.approx(160.0)
    assert grupo["resultado"] == pytest.approx(790.0)
    # despesa manual sem célula: linha própria, com dotação zero
    sem = _linha(det, TIPO_SEM_CELULA)
    assert sem["projetado"] == pytest.approx(40.0) and sem["dotacao"] == pytest.approx(0.0)
    assert sem["resultado"] == pytest.approx(-40.0)


def test_separa_por_gnd_e_acao():
    emp = _empenhado([("N1", A, 400.0), ("N4", D, 80.0), ("N3", A, 100.0)])
    res = _calc(
        celulas=_celulas_com_d(), empenhado=emp, selecao=[A, D],
        cadastro_contratos=_cad_contratos(("N1",)), cadastro_bolsas=_cad_bolsas(("N4",)),
        necessidade_contratos=_nec({"N1": (400.0, 100.0, 120.0)}),
        necessidade_bolsas=_nec({"N4": (80.0, 30.0, 20.0)}), despesas_manuais=[],
    )
    det = detalhar_por_gnd_acao(res, _celulas_com_d(), emp, [A, D], [])

    assert det.fecha
    g3 = _linha(det, TIPO_CELULA, "3", "20Y0")
    g4 = _linha(det, TIPO_CELULA, "4", "20Z1")
    assert (g3["dotacao"], g3["executado"], g3["projetado"]) == (1000.0, 400.0, 120.0)  # N1 300 + N3 100
    assert (g4["dotacao"], g4["executado"], g4["projetado"]) == (200.0, 50.0, 20.0)  # bolsa N4: 80 − 30
    assert not (det.linhas["tipo"] == TIPO_SEM_CELULA).any()  # sem despesa sem célula, a linha não aparece
    assert not (det.linhas["tipo"] == TIPO_FORA).any()


def test_ne_em_duas_celulas_e_rateada_pelo_empenhado():
    emp = _empenhado([("N1", A, 300.0), ("N1", D, 100.0)])
    res = _calc(
        celulas=_celulas_com_d(), empenhado=emp, selecao=[A, D],
        cadastro_contratos=_cad_contratos(("N1",)), cadastro_bolsas=_cad_bolsas(()),
        necessidade_contratos=_nec({"N1": (400.0, 100.0, 80.0)}), necessidade_bolsas=_nec({}),
        despesas_manuais=[],
    )
    det = detalhar_por_gnd_acao(res, _celulas_com_d(), emp, [A, D], [])

    assert det.fecha
    g3, g4 = _linha(det, TIPO_CELULA, "3", "20Y0"), _linha(det, TIPO_CELULA, "4", "20Z1")
    # executado 300 e projetado 80, 75% / 25%
    assert (g3["executado"], g3["projetado"]) == (pytest.approx(225.0), pytest.approx(60.0))
    assert (g4["executado"], g4["projetado"]) == (pytest.approx(75.0), pytest.approx(20.0))
    assert any("rateados" in aviso and "N1" in aviso for aviso in det.avisos)


def test_parte_da_ne_em_celula_nao_marcada_vai_para_fora_das_marcadas():
    emp = _empenhado([("N1", A, 300.0), ("N1", C, 100.0)])
    res = _calc(
        empenhado=emp, selecao=[A],
        cadastro_contratos=_cad_contratos(("N1",)), cadastro_bolsas=_cad_bolsas(()),
        necessidade_contratos=_nec({"N1": (400.0, 100.0, 80.0)}), necessidade_bolsas=_nec({}),
        despesas_manuais=[],
    )
    det = detalhar_por_gnd_acao(res, _celulas(), emp, [A], [])

    assert det.fecha  # a NE entra inteira na conta: 300 de executado e 80 de projetado
    assert _linha(det, TIPO_CELULA, "3", "20Y0")["executado"] == pytest.approx(225.0)
    fora = _linha(det, TIPO_FORA)
    assert (fora["executado"], fora["projetado"]) == (pytest.approx(75.0), pytest.approx(20.0))
    assert fora["dotacao"] == pytest.approx(0.0)


def test_ne_com_empenho_nulo_em_celula_vai_para_sem_celula_com_aviso():
    emp = _empenhado([("N1", A, 300.0), ("N1", D, None)])
    res = _calc(
        celulas=_celulas_com_d(), empenhado=emp, selecao=[A, D],
        cadastro_contratos=_cad_contratos(("N1",)), cadastro_bolsas=_cad_bolsas(()),
        necessidade_contratos=_nec({"N1": (300.0, 100.0, 80.0)}), necessidade_bolsas=_nec({}),
        despesas_manuais=[],
    )
    det = detalhar_por_gnd_acao(res, _celulas_com_d(), emp, [A, D], [])

    # o empenho nulo impede o rateio, mas os totais continuam fechando com os cartões
    assert det.fecha and det.resultado == pytest.approx(res.resultado)
    assert _linha(det, TIPO_SEM_CELULA)["projetado"] == pytest.approx(80.0)
    assert any("Sem célula" in aviso and "N1" in aviso for aviso in det.avisos)


def test_despesa_manual_com_celula_marcada_ou_nao():
    despesas = [
        DespesaManual("1", "Na marcada", 30.0, None, D, "2026-01-01", "2026-01-01", True),
        DespesaManual("2", "Em não marcada", 20.0, None, C, "2026-01-01", "2026-01-01", True),
        DespesaManual("3", "Desconsiderada", 999.0, None, D, "2026-01-01", "2026-01-01", False),
    ]
    res = _calc(celulas=_celulas_com_d(), selecao=[A, D], despesas_manuais=despesas)
    det = detalhar_por_gnd_acao(res, _celulas_com_d(), _empenhos_padrao(), [A, D], despesas)

    assert det.fecha
    assert _linha(det, TIPO_CELULA, "4", "20Z1")["projetado"] == pytest.approx(30.0)
    assert _linha(det, TIPO_FORA)["projetado"] == pytest.approx(20.0)  # despesa em célula não marcada


def test_contrato_ativo_sem_ne_entra_em_sem_celula():
    ativos = pd.DataFrame(
        {"contrato_numero": ["X1"], "fornecedor": ["F"], "necessidade": [70.0], "status_contrato": ["ATIVO"]}
    )
    res = _calc(sem_ne_contratos=ativos, despesas_manuais=[])
    det = detalhar_por_gnd_acao(res, _celulas(), _empenhos_padrao(), [A, B], [], ativos)

    assert det.fecha
    assert _linha(det, TIPO_SEM_CELULA)["projetado"] == pytest.approx(70.0)


def test_projecao_indisponivel_deixa_executado_e_projetado_nulos_nunca_zero():
    res = _calc(necessidade_bolsas=None, despesas_manuais=[])
    det = detalhar_por_gnd_acao(res, _celulas(), _empenhos_padrao(), [A, B], [])

    grupo = _linha(det, TIPO_CELULA, "3", "20Y0")
    assert grupo["dotacao"] == pytest.approx(1500.0)
    assert pd.isna(grupo["executado"]) and pd.isna(grupo["projetado"]) and pd.isna(grupo["resultado"])
    assert det.executado is None and det.projetado is None and det.resultado is None
    assert res.resultado is None and det.fecha
    assert any("indisponível" in aviso for aviso in det.avisos)


def test_dotacao_nula_da_celula_deixa_o_grupo_sem_resultado():
    celulas = _celulas(dot_a=None)
    res = _calc(celulas=celulas, despesas_manuais=[])
    det = detalhar_por_gnd_acao(res, celulas, _empenhos_padrao(), [A, B], [])

    grupo = _linha(det, TIPO_CELULA, "3", "20Y0")
    assert pd.isna(grupo["dotacao"]) and pd.isna(grupo["resultado"])
    assert grupo["executado"] == pytest.approx(550.0)
    assert det.dotacao is None and det.resultado is None


def test_selecao_vazia_nao_gera_linhas():
    res = _calc(selecao=[], despesas_manuais=[])
    det = detalhar_por_gnd_acao(res, _celulas(), _empenhos_padrao(), [], [])

    assert det.linhas.empty and det.fecha


def _com_1050(dot=1000.0) -> pd.DataFrame:
    from tests.test_resultado_orcamentario import R1050

    extra = pd.DataFrame({"chave": [R1050], "dotacao_atualizada": pd.array([dot], dtype="Float64")})
    return pd.concat([_celulas(), extra], ignore_index=True)


def _receita(valor, id_="r1"):
    from src.resultado_orcamentario_cadastro import ReceitaPropria

    return ReceitaPropria(id_, "Arrecadação", valor, None, "2026-10-22", "2026-10-22", True)


def test_celula_1050_limitada_pela_receita_aparece_no_grupo_e_fecha_com_os_cartoes():
    from tests.test_resultado_orcamentario import R1050

    receitas = [_receita(300.0)]
    res = _calc(celulas=_com_1050(), selecao=[A, B, R1050], receitas_proprias=receitas)
    det = detalhar_por_gnd_acao(res, _com_1050(), _empenhos_padrao(), [A, B, R1050], [_manual()])

    assert det.fecha and det.dotacao == pytest.approx(res.dotacao) == pytest.approx(1800.0)
    assert det.resultado == pytest.approx(res.resultado)
    grupo = _linha(det, TIPO_CELULA, "3", "20RK")
    assert grupo["dotacao"] == pytest.approx(300.0) and grupo["receitas"] == pytest.approx(300.0)
    assert _linha(det, TIPO_CELULA, "3", "20Y0")["receitas"] == 0.0


def test_sem_limite_a_celula_1050_entra_inteira_no_detalhe_e_sem_nota():
    from tests.test_resultado_orcamentario import R1050

    res = _calc(celulas=_com_1050(), selecao=[A, B, R1050])
    det = detalhar_por_gnd_acao(res, _com_1050(), _empenhos_padrao(), [A, B, R1050], [_manual()])
    assert det.fecha and _linha(det, TIPO_CELULA, "3", "20RK")["dotacao"] == pytest.approx(1000.0)
    assert det.linhas["receitas"].sum() == 0.0
