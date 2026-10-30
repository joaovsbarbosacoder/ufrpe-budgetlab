"""Testes de `src/resultado_orcamentario_planos.py` — quadros do discricionário por Plano Orçamentário (29/10/2026).

Reaproveita os builders sintéticos de `tests/test_resultado_orcamentario.py`. Em todo cenário a soma dos quadros precisa fechar com o
`ResultadoOrcamentario` do discricionário (calculado com `selecao_discricionaria`).
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.resultado_orcamentario_cadastro import DespesaManual
from src.resultado_orcamentario_planos import planos_discricionarios, selecao_discricionaria
from tests.test_resultado_orcamentario import (
    R1050,
    _cad_bolsas,
    _cad_contratos,
    _calc,
    _empenhado,
    _nec,
    _receita,
)

# Ação 20Y0, dois planos (0001 e 0002) e uma célula de outra fonte no plano 0001; X é obrigatória (RP1), fora do discricionário
P1 = ("0", "2", "20Y0", "100001", "0001", "3", "1000000000")
P1B = ("0", "2", "20Y0", "100001", "0001", "3", "3050000000")
P2 = ("0", "2", "20Y0", "100002", "0002", "3", "1000000000")
Q = ("0", "2", "21AA", "100003", "0000", "4", "1000000000")
X = ("0", "1", "20Y0", "100009", "0001", "3", "1000000000")


def _celulas(dot_p1=1000.0, dot_p1b=200.0, dot_p2=500.0, dot_q=300.0, dot_x=9999.0, com_nomes=True) -> pd.DataFrame:
    chaves = [P1, P1B, P2, Q, X]
    df = pd.DataFrame({"chave": chaves, "dotacao_atualizada": pd.array([dot_p1, dot_p1b, dot_p2, dot_q, dot_x], dtype="Float64")})
    if com_nomes:
        df["acao_codigo"] = [c[2] for c in chaves]
        df["acao_descricao"] = ["ACAO 20Y0"] * 3 + ["ACAO 21AA", "ACAO 20Y0"]
        df["plano_orcamentario_codigo"] = [c[4] for c in chaves]
        df["plano_orcamentario_descricao"] = ["PLANO UM", "PLANO UM", "PLANO DOIS", "PLANO Q", "PLANO X"]
        df["fonte_recursos_detalhada_codigo"] = [c[6] for c in chaves]
        df["fonte_recursos_detalhada_descricao"] = ["TESOURO", "PROPRIOS", "TESOURO", "TESOURO", "TESOURO"]
    return df


def _gerar(celulas=None, empenhos=None, ativos_sem_ne=None, **kw):
    celulas = _celulas() if celulas is None else celulas
    selecao = selecao_discricionaria(celulas)
    if empenhos is None:
        empenhos = _empenhado([("N1", P1, 400.0), ("N2", P2, 200.0), ("N3", P1B, 50.0), ("N9", X, 90.0)])
    args = dict(
        celulas=celulas, empenhado=empenhos, selecao=selecao,
        cadastro_contratos=_cad_contratos(("N1", "N9")), cadastro_bolsas=_cad_bolsas(("N2",)),
        # N1 (P1): liquidado 300, projetado 120. N9 (célula X, fora do RP2): liquidado 30, projetado 10. N2 (bolsa, P2): 150 e 40.
        necessidade_contratos=_nec({"N1": (400.0, 100.0, 120.0), "N9": (90.0, 60.0, 10.0)}),
        necessidade_bolsas=_nec({"N2": (200.0, 50.0, 40.0)}),
        despesas_manuais=[],
    )
    args.update(kw)
    res = _calc(**args)
    return res, planos_discricionarios(res, celulas, args["empenhado"], args["despesas_manuais"], ativos_sem_ne)


def _quadro(r, acao, po):
    achados = [p for p in r.planos if p.acao == acao and p.po == po]
    assert len(achados) == 1, achados
    return achados[0]


def test_selecao_discricionaria_so_traz_o_resultado_primario_2():
    assert set(selecao_discricionaria(_celulas())) == {P1, P1B, P2, Q}


def test_um_quadro_por_plano_com_dotacao_executado_projetado_e_saldo():
    res, r = _gerar()
    assert r.fecha and r.dotacao == pytest.approx(res.dotacao) == pytest.approx(2000.0)
    plano1 = _quadro(r, "20Y0", "0001")
    assert plano1.dotacao == pytest.approx(1200.0)  # P1 1000 + P1B 200
    # N1 (contrato, P1): executado 300 / projetado 120; N3 (outros, P1B): empenhado 50
    assert plano1.executado == pytest.approx(350.0) and plano1.projetado == pytest.approx(120.0)
    assert plano1.saldo == pytest.approx(1200.0 - 350.0 - 120.0)
    plano2 = _quadro(r, "20Y0", "0002")
    assert plano2.dotacao == 500.0 and plano2.executado == pytest.approx(150.0) and plano2.projetado == pytest.approx(40.0)
    sem_movimento = _quadro(r, "21AA", "0000")
    assert sem_movimento.dotacao == 300.0 and sem_movimento.executado == 0.0 and sem_movimento.saldo == pytest.approx(300.0)
    assert r.saldo == pytest.approx(res.resultado)


def test_nomes_da_acao_e_do_plano_vem_da_dotacao_e_faltando_nome_nao_quebra():
    _, r = _gerar()
    plano = _quadro(r, "20Y0", "0001")
    assert plano.acao_descricao == "ACAO 20Y0" and plano.po_descricao == "PLANO UM"
    _, sem_nomes = _gerar(celulas=_celulas(com_nomes=False))
    assert _quadro(sem_nomes, "20Y0", "0001").po_descricao is None


def test_celula_fora_do_rp2_nao_vira_quadro_e_a_parte_de_ne_dela_nao_entra_nos_planos():
    res, r = _gerar()
    assert {(p.acao, p.po) for p in r.planos} == {("20Y0", "0001"), ("20Y0", "0002"), ("21AA", "0000")}
    assert sum(p.dotacao for p in r.planos) == pytest.approx(2000.0)  # a dotação 9999 de X não entra
    assert r.fecha and r.saldo == pytest.approx(res.resultado)


def test_um_plano_com_mais_de_uma_fonte_lista_as_fontes_e_a_soma_fecha_com_o_plano():
    _, r = _gerar()
    plano1 = _quadro(r, "20Y0", "0001")
    assert [f.fonte for f in plano1.fontes] == ["1000000000", "3050000000"]
    assert sum(f.dotacao for f in plano1.fontes) == pytest.approx(plano1.dotacao)
    assert sum(f.saldo for f in plano1.fontes) == pytest.approx(plano1.saldo)
    assert plano1.fontes[1].fonte_descricao == "PROPRIOS"


def test_despesa_manual_com_celula_vai_para_o_plano_e_sem_celula_para_a_linha_avulsa():
    com = DespesaManual("1", "Com célula", 25.0, None, P2, "2026-01-01", "2026-01-01", True)
    sem = DespesaManual("2", "Sem célula", 40.0, None, None, "2026-01-01", "2026-01-01", True)
    res, r = _gerar(despesas_manuais=[com, sem])
    assert _quadro(r, "20Y0", "0002").projetado == pytest.approx(40.0 + 25.0)
    assert r.sem_celula.projetado == pytest.approx(40.0) and r.sem_celula.executado == 0.0
    assert r.fecha and r.saldo == pytest.approx(res.resultado)


def test_despesa_desconsiderada_nao_entra():
    fora = DespesaManual("1", "Fora", 25.0, None, P2, "2026-01-01", "2026-01-01", False)
    _, r = _gerar(despesas_manuais=[fora])
    assert _quadro(r, "20Y0", "0002").projetado == pytest.approx(40.0)


def test_dotacao_nula_deixa_o_plano_e_o_total_sem_valor_e_nunca_zero():
    _, r = _gerar(celulas=_celulas(dot_p2=None))
    plano2 = _quadro(r, "20Y0", "0002")
    assert plano2.dotacao is None and plano2.saldo is None
    assert r.dotacao is None and r.saldo is None
    assert _quadro(r, "20Y0", "0001").saldo is not None


def test_projecao_indisponivel_deixa_executado_e_projetado_sem_valor():
    res, r = _gerar(necessidade_contratos=None)
    assert res.resultado is None
    plano1 = _quadro(r, "20Y0", "0001")
    assert plano1.executado is None and plano1.projetado is None and plano1.saldo is None and plano1.dotacao == 1200.0


def test_receita_na_celula_1050_da_20rk_limita_e_leva_o_excedente_na_fonte():
    extra = pd.DataFrame({
        "chave": [R1050], "dotacao_atualizada": pd.array([415401.8], dtype="Float64"),
        "acao_codigo": ["20RK"], "acao_descricao": ["FUNCIONAMENTO"], "plano_orcamentario_codigo": ["0000"],
        "plano_orcamentario_descricao": ["DESPESAS DIVERSAS"],
        "fonte_recursos_detalhada_codigo": ["1050000000"], "fonte_recursos_detalhada_descricao": ["PROPRIOS LIVRES"],
    })
    celulas = pd.concat([_celulas(), extra], ignore_index=True)
    res, r = _gerar(celulas=celulas, receitas_proprias=[_receita(447514.78)])
    plano = _quadro(r, "20RK", "0000")
    assert plano.dotacao == pytest.approx(415401.8)
    (fonte,) = plano.fontes
    assert fonte.receita_limite == pytest.approx(447514.78) and fonte.receita_excedente == pytest.approx(32112.98)
    assert r.fecha and r.dotacao == pytest.approx(res.dotacao)


def test_ordem_acoes_por_dotacao_e_planos_por_dotacao_dentro_da_acao():
    _, r = _gerar()
    assert [(p.acao, p.po) for p in r.planos] == [("20Y0", "0001"), ("20Y0", "0002"), ("21AA", "0000")]


# ------------------------------------------------------------------ filtros da página (30/10/2026)
from src.resultado_orcamentario_planos import (  # noqa: E402
    SITUACAO_DEFICIT,
    SITUACAO_FOLGA,
    SITUACAO_INTEGRAL,
    SITUACAO_SEM_SALDO,
    LinhaAvulsa,
    PlanosDiscricionarios,
    QuadroPlano,
    SaldoFonte,
    filtrar_planos,
    opcoes_filtros,
    situacao,
)


def _sf(fonte, dotacao, executado, projetado):
    saldo = None if None in (dotacao, executado, projetado) else dotacao - executado - projetado
    return SaldoFonte(fonte, f"DESC {fonte}", dotacao, executado, projetado, saldo)


def _qp(acao, po, *fontes):
    def soma(i):
        valores = [getattr(f, i) for f in fontes]
        return None if any(v is None for v in valores) else sum(valores)

    dot, exe, prj = soma("dotacao"), soma("executado"), soma("projetado")
    saldo = None if None in (dot, exe, prj) else dot - exe - prj
    return QuadroPlano(acao, f"ACAO {acao}", po, f"PLANO {po}", dot, exe, prj, saldo, tuple(fontes))


def _base_filtros():
    # 20RK/0000: duas fontes — 1000 folga 100, 1050 déficit 50 -> plano folga 50
    # 20RK/0002: fonte 1000, déficit 30
    # 4002/0000: fonte 1000, executado nulo -> sem saldo
    planos = [
        _qp("20RK", "0000", _sf("1000000000", 500.0, 300.0, 100.0), _sf("1050000000", 200.0, 150.0, 100.0)),
        _qp("20RK", "0002", _sf("1000000000", 100.0, 80.0, 50.0)),
        _qp("4002", "0000", _sf("1000000000", 300.0, None, 10.0)),
    ]
    return PlanosDiscricionarios(planos, LinhaAvulsa(5.0, 1.0), LinhaAvulsa(0.0, 0.0), 1100.0, None, 260.0, None, 0.0, ["aviso"])


def test_situacao_pela_mesma_tolerancia_da_pilula():
    assert situacao(None) == SITUACAO_SEM_SALDO
    assert situacao(-0.01) == SITUACAO_DEFICIT
    assert situacao(0.003) == situacao(-0.003) == SITUACAO_INTEGRAL
    assert situacao(0.01) == SITUACAO_FOLGA


def test_sem_filtro_devolve_o_resultado_como_esta():
    base = _base_filtros()
    assert filtrar_planos(base) is base
    assert filtrar_planos(base, acoes=[], planos=None) is base


def test_filtro_por_acao_e_plano_soma_so_os_visiveis_sem_avulsas():
    r = filtrar_planos(_base_filtros(), acoes=["20RK"])
    assert [(p.acao, p.po) for p in r.planos] == [("20RK", "0000"), ("20RK", "0002")]
    assert (r.dotacao, r.executado, r.projetado, r.saldo) == (800.0, 530.0, 250.0, 20.0)
    assert r.filtrado and r.planos_no_total == 3 and r.avisos == ["aviso"]
    assert r.fora == LinhaAvulsa(0.0, 0.0)
    so_um = filtrar_planos(_base_filtros(), planos=["4002|0000"])  # PO 0000 existe nas duas Ações: a chave leva a Ação
    assert [(p.acao, p.po) for p in so_um.planos] == [("4002", "0000")]
    assert so_um.executado is None and so_um.saldo is None  # nulo continua nulo, nunca zero


def test_filtro_por_fonte_refaz_o_plano_so_com_as_fontes_escolhidas():
    r = filtrar_planos(_base_filtros(), fontes=["1050000000"])
    assert len(r.planos) == 1  # só 20RK/0000 tem a 1050
    p = r.planos[0]
    assert (p.dotacao, p.executado, p.projetado, p.saldo) == (200.0, 150.0, 100.0, -50.0)
    assert [f.fonte for f in p.fontes] == ["1050000000"]
    assert (r.dotacao, r.saldo) == (200.0, -50.0)
    base = _base_filtros()
    filtrar_planos(base, fontes=["1050000000"])
    assert base.planos[0].dotacao == 700.0  # não altera o resultado recebido


def test_situacao_vale_sobre_o_saldo_ja_recortado_pela_fonte():
    # sem fonte, 20RK/0000 tem folga (50); só com a 1050, déficit (−50)
    assert [p.po for p in filtrar_planos(_base_filtros(), situacoes=[SITUACAO_DEFICIT]).planos] == ["0002"]
    r = filtrar_planos(_base_filtros(), fontes=["1050000000"], situacoes=[SITUACAO_DEFICIT])
    assert [(p.acao, p.po) for p in r.planos] == [("20RK", "0000")]
    assert [p.acao for p in filtrar_planos(_base_filtros(), situacoes=[SITUACAO_SEM_SALDO]).planos] == ["4002"]


def test_filtro_sem_nenhum_plano_tem_totais_zerados_e_marca_o_recorte():
    r = filtrar_planos(_base_filtros(), acoes=["4002"], situacoes=[SITUACAO_FOLGA])
    assert r.planos == [] and r.filtrado and (r.dotacao, r.saldo) == (0.0, 0.0)


def test_opcoes_dos_filtros_em_cascata():
    acoes, planos, fontes = opcoes_filtros(_base_filtros())
    assert acoes == {"20RK": "20RK — ACAO 20RK", "4002": "4002 — ACAO 4002"}
    assert list(planos) == ["20RK|0000", "20RK|0002", "4002|0000"]
    assert list(fontes) == ["1000000000", "1050000000"]
    _, planos, fontes = opcoes_filtros(_base_filtros(), ["4002"])
    assert list(planos) == ["4002|0000"] and list(fontes) == ["1000000000"]
    _, _, fontes = opcoes_filtros(_base_filtros(), None, ["20RK|0002"])
    assert list(fontes) == ["1000000000"]
