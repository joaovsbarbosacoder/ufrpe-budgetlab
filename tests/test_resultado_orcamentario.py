"""Testes de `src/resultado_orcamentario.py` — regra do Resultado Orçamentário (bolsão de células).

DataFrames sintéticos mínimos montados no próprio teste (08/10/2026).
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.resultado_orcamentario import (
    soma_ou_nulo,
    ORIGEM_BOLSAS,
    ORIGEM_CONTRATOS,
    ORIGEM_DEA,
    ORIGEM_MATERIAL_CONSUMO,
    ORIGEM_OUTROS,
    calcular_resultado,
    celulas_da_dotacao,
    empenhado_por_ne_e_celula,
)
from src.resultado_orcamentario_cadastro import CHAVE_CELULA, DespesaManual

A = ("0", "2", "20Y0", "100001", "0000", "3", "1000000000")
B = ("0", "2", "20Y0", "100002", "0000", "3", "1000000000")
C = ("0", "2", "20Y0", "100003", "0000", "3", "1000000000")
OUTRAS = "Outras despesas previstas"


def _celulas(dot_a=1000.0, dot_b=500.0, dot_c=300.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "chave": [A, B, C],
            "dotacao_atualizada": pd.array([dot_a, dot_b, dot_c], dtype="Float64"),
        }
    )


def _empenhado(linhas: list[tuple]) -> pd.DataFrame:
    """Cada linha: (ne, chave, valor) ou (ne, chave, valor, elemento)."""
    return pd.DataFrame(
        [
            {
                "ne_curta": linha[0],
                "chave": linha[1],
                "empenhada": linha[2],
                "elemento_cod": linha[3] if len(linha) > 3 else "39",
                "natureza_detalhada_desc": "NAT",
                "ne_favorecido": "FAV",
            }
            for linha in linhas
        ]
    )


def _empenhos_padrao() -> pd.DataFrame:
    return _empenhado([("N1", A, 400.0), ("N2", B, 200.0), ("N3", A, 100.0), ("N9", C, 50.0)])


def _cad_contratos(nes=("N1", "N9")) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ne_curta": list(nes),
            "contrato_numero": [f"C{i}" for i, _ in enumerate(nes)],
            "fornecedor": [f"F{i}" for i, _ in enumerate(nes)],
        }
    )


def _cad_bolsas(nes=("N2",)) -> pd.DataFrame:
    return pd.DataFrame({"ne_curta": list(nes), "programa_bolsa": [f"P{i}" for i, _ in enumerate(nes)]})


def _nec(valores: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame({"ne_curta": list(valores), "necessidade_execucao": list(valores.values())})


def _sem_ne_vazio() -> pd.DataFrame:
    return pd.DataFrame({"contrato_numero": [], "fornecedor": [], "necessidade": []})


def _manual(valor=40.0) -> DespesaManual:
    return DespesaManual("1", "Desp", valor, None, None, "2026-01-01", "2026-01-01")


def _calc(**kw):
    args = dict(
        celulas=_celulas(),
        empenhado=_empenhos_padrao(),
        selecao=[A, B],
        cadastro_contratos=_cad_contratos(),
        cadastro_bolsas=_cad_bolsas(),
        necessidade_contratos=_nec({"N1": 150.0, "N9": 80.0}),
        necessidade_bolsas=_nec({"N2": 60.0}),
        sem_ne_contratos=_sem_ne_vazio(),
        sem_ne_bolsas=pd.DataFrame({"programa_bolsa": [], "necessidade": []}),
        despesas_manuais=[_manual()],
    )
    args.update(kw)
    return calcular_resultado(**args)




def test_resultado_conta_a_mao():
    r = _calc()
    assert r.dotacao == 1500
    assert r.empenhado == {
        ORIGEM_CONTRATOS: 400, ORIGEM_BOLSAS: 200, ORIGEM_DEA: 0.0, ORIGEM_MATERIAL_CONSUMO: 0.0,
        ORIGEM_OUTROS: 100,
    }
    assert r.empenhado_total == 700
    assert r.necessidade == {ORIGEM_CONTRATOS: 230, ORIGEM_BOLSAS: 60, OUTRAS: 40}
    assert sum(r.necessidade.values()) == 330  # N9 (celula nao selecionada) entra
    assert r.resultado == 1500 - 700 - 330 == 470
    assert r.incompleto is False


def test_ne_em_celula_nao_selecionada_fora_do_empenhado_dentro_da_necessidade():
    r = _calc()
    por_ne = r.empenhado_por_ne
    assert "N9" not in set(por_ne.loc[por_ne["celula_selecionada"], "ne_curta"])
    assert r.necessidade[ORIGEM_CONTRATOS] == 150 + 80


def test_ne_nos_dois_cadastros_vai_para_contratos():
    r = _calc(cadastro_bolsas=_cad_bolsas(("N1", "N2")))
    linha = r.empenhado_por_ne.query("ne_curta == 'N1'").iloc[0]
    assert linha["origem"] == ORIGEM_CONTRATOS
    assert r.empenhado[ORIGEM_CONTRATOS] == 400
    assert any("N1" in a and "conferir" in a for a in r.avisos)


def test_ne_compartilhada_contada_uma_vez():
    cad = pd.DataFrame(
        {
            "ne_curta": ["N1", "N1", "N9"],
            "contrato_numero": ["C1", "C2", "C9"],
            "fornecedor": ["F1", "F2", "F9"],
        }
    )
    r = _calc(cadastro_contratos=cad)
    assert r.empenhado[ORIGEM_CONTRATOS] == 400
    assert len(r.empenhado_por_ne.query("ne_curta == 'N1'")) == 1
    assert any("compartilhada" in a and "N1" in a for a in r.avisos)


def test_conferencia_fecha():
    assert abs(_calc().diferenca_conferencia) < 0.01


def test_sem_ne_fora_da_conta_com_aviso():
    sem = pd.DataFrame({"contrato_numero": ["C77"], "fornecedor": ["F77"], "necessidade": [999.0]})
    r = _calc(sem_ne_contratos=sem)
    assert r.resultado == 470
    assert any("1 contrato" in a and "999" in a for a in r.avisos)


def test_celula_com_dotacao_nula_incompleto():
    r = _calc(celulas=_celulas(dot_b=pd.NA))
    assert r.incompleto is True
    assert r.resultado is None
    assert any("sem Dotação Atualizada" in a for a in r.avisos)


def test_necessidade_indisponivel_deixa_resultado_incompleto():
    r = _calc(necessidade_contratos=None)
    assert r.necessidade[ORIGEM_CONTRATOS] is None
    assert r.resultado is None
    assert r.incompleto is True


def test_necessidade_nula_de_uma_ne_deixa_resultado_incompleto():
    # NE sem valor mensal: o relatório de projeção traz necessidade nula — não pode virar zero aqui.
    nec = pd.DataFrame({"ne_curta": ["N1", "N9"], "necessidade_execucao": [150.0, float("nan")]})
    r = _calc(necessidade_contratos=nec)
    assert r.necessidade[ORIGEM_CONTRATOS] is None
    assert r.resultado is None
    assert r.incompleto is True
    assert any("N9" in a and "não calculada" in a for a in r.avisos)


def test_cadastro_vazio_necessidade_zero():
    r = _calc(necessidade_bolsas=pd.DataFrame({"ne_curta": [], "necessidade_execucao": []}))
    assert r.necessidade[ORIGEM_BOLSAS] == 0.0
    assert r.incompleto is False


def test_sem_selecao_resultado_none():
    r = _calc(selecao=[])
    assert r.resultado is None
    assert any("Nenhuma célula selecionada" in a for a in r.avisos)
    assert r.incompleto is False


def test_celula_selecionada_ausente():
    fantasma = ("9",) * 7
    r = _calc(selecao=[A, B, fantasma])
    assert any("ausente da base" in a for a in r.avisos)
    assert r.resultado == 470


def test_empenho_sem_fonte_detalhada_vira_aviso():
    sem_fonte = A[:-1] + (None,)
    emp = _empenhado([("N1", A, 400.0), ("N5", sem_fonte, 77.0)])
    r = _calc(empenhado=emp)
    assert r.empenhado_total == 400
    assert any("fonte" in a.lower() and "77" in a for a in r.avisos)


def _dot_linha(ptres, item, valor, ano=2026, po="0000"):
    return {
        "ano_lancamento": ano, "arquivo_origem": "t", "aba_origem": "b", "linha_origem": 1,
        "coluna_origem": "K", "item_informacao_origem": "i",
        "iduso_codigo": "0", "iduso_descricao": "x",
        "resultado_primario_codigo": "2", "resultado_primario_descricao": "x",
        "acao_codigo": "20Y0", "acao_descricao": "x", "ptres_codigo": ptres,
        "plano_orcamentario_codigo": po, "plano_orcamentario_descricao": "x",
        "grupo_despesa_codigo": "3", "grupo_despesa_descricao": "x",
        "fonte_recursos_detalhada_codigo": "1000000000",
        "fonte_recursos_detalhada_descricao": "x",
        "item_informacao_codigo": item, "valor_movimento_liquido": valor,
    }


def _exec_linha(ne_ccor, ptres, empenhada, ano=2026, fonte="1000000000", favorecido="FAV"):
    return {
        "ano": ano, "ano_mes": ano * 100 + 1, "ne_ccor": ne_ccor,
        "natureza_detalhada_cod": "339039", "subitem_cod": "1", "ne_item_cod": None,
        "tipo_linha": "empenho", "empenhada": empenhada, "ptres": ptres,
        "elemento_cod": "39", "elemento_desc": "x", "natureza_detalhada_desc": "SERV",
        "gnd_cod": "3", "gnd_desc": "x", "fonte_cod": "000", "fonte_desc": "x",
        "fonte_recursos_detalhada_cod": fonte, "fonte_recursos_detalhada_desc": "x",
        "acao_cod": "20Y0", "acao_desc": "x", "ugr_cod": "1", "ugr_desc": "x",
        "po_cod": "0000", "po_desc": "x", "resultado_primario_cod": "2",
        "resultado_primario_desc": "x", "iduso_cod": "0", "iduso_desc": "x",
        "ne_favorecido": favorecido,
    }


def test_zeros_a_esquerda_casam():
    # PO "0000" e fonte "1000000000" passam como texto pela Dotacao e pela Execucao.
    dot = pd.DataFrame([_dot_linha("100001", "dotacao_atualizada", 1000.0)])
    celulas = celulas_da_dotacao(dot, 2026)
    assert celulas.iloc[0]["chave"] == A
    exe = pd.DataFrame([_exec_linha("15225626000" + "2026NE000100", "100001", 400.0)])
    emp = empenhado_por_ne_e_celula(exe, 2026)
    assert emp.iloc[0]["chave"] == A
    r = _calc(celulas=celulas, selecao=[A], empenhado=emp, cadastro_contratos=_cad_contratos(("2026NE000100",)))
    assert r.dotacao == 1000
    assert r.empenhado[ORIGEM_CONTRATOS] == 400


def test_celulas_da_dotacao_e_empenhado_por_ne():
    dot = pd.DataFrame(
        [
            _dot_linha("100001", "dotacao_atualizada", 10.0),
            _dot_linha("100002", "dotacao_inicial", 5.0),  # atualizada nula, mas tem indicador
            _dot_linha("100003", "dotacao_atualizada", 9.0, ano=2025),  # outro exercicio
            _dot_linha("100004", "dotacao_atualizada", None),  # sem nenhum indicador
        ]
    )
    cel = celulas_da_dotacao(dot, 2026)
    assert len(cel) == 2
    assert str(cel["ptres_codigo"].dtype) == "string"
    assert str(cel["dotacao_atualizada"].dtype) == "Float64"
    assert list(CHAVE_CELULA) == [
        "iduso_codigo", "resultado_primario_codigo", "acao_codigo", "ptres_codigo",
        "plano_orcamentario_codigo", "grupo_despesa_codigo", "fonte_recursos_detalhada_codigo",
    ]
    assert cel.iloc[0]["chave"] == ("0", "2", "20Y0", "100001", "0000", "3", "1000000000")
    assert cel.iloc[0]["dotacao_atualizada"] == 10.0
    assert pd.isna(cel.iloc[1]["dotacao_atualizada"])

    exe = pd.DataFrame(
        [
            _exec_linha("15225626000" + "2026NE000100", "100001", 400.0),
            _exec_linha("15225626000" + "2025NE000007", "100001", 99.0, ano=2025),
        ]
    )
    emp = empenhado_por_ne_e_celula(exe, 2026)
    assert len(emp) == 1
    linha = emp.iloc[0]
    assert linha["ne_curta"] == "2026NE000100"
    assert linha["chave"] == ("0", "2", "20Y0", "100001", "0000", "3", "1000000000")
    assert linha["empenhada"] == 400.0
    assert linha["natureza_detalhada_desc"] == "SERV"
    assert linha["ne_favorecido"] == "FAV"


def test_empenhado_nulo_em_celula_marcada_incompleto():
    emp = _empenhado([("N1", A, 400.0), ("N3", A, None)])
    r = _calc(empenhado=emp)
    assert r.resultado is None
    assert r.incompleto is True
    assert any("nulo" in a and "N3" in a for a in r.avisos)
    # Correção (08/10/2026): totais exibidos de empenhado ficam None (a página mostra "—"), não ignoram o nulo.
    assert r.empenhado_total is None
    assert r.empenhado[ORIGEM_CONTRATOS] == 400.0
    assert any(v is None for v in r.empenhado.values())


def test_aviso_sem_ne_bolsas_usa_necessidade_renomeada():
    # Forma real vinda de `projecao_bolsas`: a coluna privada `_necessidade` já renomeada.
    sem = pd.DataFrame({"fornecedor": ["Programa X"], "_necessidade": [17500.0]}).rename(columns={"_necessidade": "necessidade"})
    r = _calc(sem_ne_bolsas=sem)
    assert any("1 bolsa" in a and "17.500,00" in a for a in r.avisos)


def test_aviso_sem_ne_com_valor_nulo_diz_nao_calculado():
    sem = pd.DataFrame({"programa_bolsa": ["A", "B"], "necessidade": [100.0, None]})
    r = _calc(sem_ne_bolsas=sem)
    assert any("2 bolsas" in a and "valor não calculado" in a for a in r.avisos)
    sem_coluna = pd.DataFrame({"programa_bolsa": ["A"]})
    assert any("valor não calculado" in a for a in _calc(sem_ne_bolsas=sem_coluna).avisos)


def test_soma_ou_nulo_nao_trata_nulo_como_zero():
    # revisão da Task 5: "Total selecionado" com uma célula de dotação nula não pode virar total definido
    assert soma_ou_nulo(pd.Series([100.0, None, 50.0], dtype="Float64")) is None
    assert soma_ou_nulo(pd.Series([100.0, float("nan")])) is None
    assert soma_ou_nulo(pd.Series([100.0, -30.0, 0.0], dtype="Float64")) == 70.0
    assert soma_ou_nulo(pd.Series([], dtype="Float64")) == 0.0


def test_outros_segmentado_por_elemento_92_e_30():
    # N3 (elemento 92), N4 (elemento 30) e N5 (39) não estão nos cadastros: saem de "Outros" por elemento.
    emp = _empenhado([
        ("N1", A, 400.0, "37"), ("N2", B, 200.0, "18"),
        ("N3", A, 70.0, "92"), ("N4", A, 20.0, "30"), ("N5", A, 10.0, "39"),
    ])
    r = _calc(empenhado=emp)
    assert r.empenhado[ORIGEM_DEA] == 70.0
    assert r.empenhado[ORIGEM_MATERIAL_CONSUMO] == 20.0
    assert r.empenhado[ORIGEM_OUTROS] == 10.0
    assert r.empenhado_total == 700.0
    assert abs(r.diferenca_conferencia) < 0.01
    origens = r.empenhado_por_ne.set_index("ne_curta")["origem"]
    assert origens["N3"] == ORIGEM_DEA and origens["N4"] == ORIGEM_MATERIAL_CONSUMO and origens["N5"] == ORIGEM_OUTROS


def test_contrato_e_bolsa_tem_prioridade_sobre_o_elemento():
    emp = _empenhado([("N1", A, 400.0, "30"), ("N2", B, 200.0, "92")])
    r = _calc(empenhado=emp)
    assert r.empenhado[ORIGEM_CONTRATOS] == 400.0 and r.empenhado[ORIGEM_BOLSAS] == 200.0
    assert r.empenhado[ORIGEM_DEA] == 0.0 and r.empenhado[ORIGEM_MATERIAL_CONSUMO] == 0.0


def test_ne_com_dois_elementos_divide_o_valor():
    emp = _empenhado([("N7", A, 50.0, "30"), ("N7", A, 30.0, "39")])
    r = _calc(empenhado=emp)
    assert r.empenhado[ORIGEM_MATERIAL_CONSUMO] == 50.0
    assert r.empenhado[ORIGEM_OUTROS] == 30.0


def test_sem_elemento_fica_em_outros():
    emp = _empenhado([("N8", A, 15.0, None)])
    r = _calc(empenhado=emp)
    assert r.empenhado[ORIGEM_OUTROS] == 15.0
