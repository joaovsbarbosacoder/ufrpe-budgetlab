"""Testes da persistência da seleção de células e das despesas manuais do Resultado Orçamentário."""

import pytest

from src.resultado_orcamentario_cadastro import (
    ArquivoCorrompido,
    atualizar_despesa,
    carregar_despesas,
    carregar_selecao,
    excluir_despesa,
    incluir_despesa,
    salvar_selecao,
    validar_despesa,
)

CELULA = ("0", "2", "20RK", "230987", "0000", "3", "1000000000")


def test_selecao_ida_e_volta_preserva_zeros(tmp_path):
    salvar_selecao(2026, [CELULA], tmp_path)
    recarregada = carregar_selecao(2026, tmp_path)
    assert recarregada == [CELULA]
    assert recarregada[0][4] == "0000"


def test_selecao_arquivo_ausente_lista_vazia(tmp_path):
    assert carregar_selecao(2026, tmp_path) == []


def test_selecao_arquivo_corrompido_levanta(tmp_path):
    pasta = tmp_path / "2026"
    pasta.mkdir()
    (pasta / "celulas.json").write_text("{", encoding="utf-8")
    with pytest.raises(ArquivoCorrompido):
        carregar_selecao(2026, tmp_path)


def test_selecao_mantem_celula_desconhecida(tmp_path):
    desconhecida = ("9", None, "ZZZZ", "999999", "ABCD", "9", "0000000000")
    salvar_selecao(2026, [CELULA, desconhecida], tmp_path)
    assert carregar_selecao(2026, tmp_path) == [CELULA, desconhecida]


def test_gravacao_atomica_nao_deixa_temporario(tmp_path):
    salvar_selecao(2026, [CELULA], tmp_path)
    assert [p.name for p in (tmp_path / "2026").iterdir()] == ["celulas.json"]


def test_validar_despesa():
    assert any("descri" in e.lower() for e in validar_despesa("", 10.0))
    assert any("valor" in e.lower() for e in validar_despesa("X", None))
    assert any("maior que zero" in e for e in validar_despesa("X", 0.0))
    assert any("maior que zero" in e for e in validar_despesa("X", -5.0))
    assert validar_despesa("X", 1.0) == []


def test_incluir_atualizar_excluir_despesa(tmp_path):
    a = incluir_despesa(2026, "Obra A", 100.0, None, CELULA, tmp_path)
    b = incluir_despesa(2026, "Obra B", 200.0, "obs", None, tmp_path)
    atualizar_despesa(2026, a.id, "Obra A", 620000.0, None, CELULA, tmp_path)
    excluir_despesa(2026, b.id, tmp_path)
    despesas = carregar_despesas(2026, tmp_path)
    assert len(despesas) == 1
    assert despesas[0].valor == 620000.0
    assert despesas[0].celula == CELULA
    assert despesas[0].atualizado_em >= despesas[0].criado_em


def test_incluir_despesa_invalida_levanta_value_error(tmp_path):
    with pytest.raises(ValueError):
        incluir_despesa(2026, "", 10.0, None, None, tmp_path)


def test_exercicios_isolados(tmp_path):
    salvar_selecao(2026, [CELULA], tmp_path)
    assert carregar_selecao(2025, tmp_path) == []


def test_preferencia_so_selecionadas_ida_e_volta(tmp_path):
    from src.resultado_orcamentario_cadastro import carregar_so_selecionadas, salvar_so_selecionadas

    assert carregar_so_selecionadas(tmp_path) is False  # arquivo ausente: desmarcada
    salvar_so_selecionadas(True, tmp_path)
    assert carregar_so_selecionadas(tmp_path) is True
    salvar_so_selecionadas(False, tmp_path)
    assert carregar_so_selecionadas(tmp_path) is False


def test_preferencia_ilegivel_volta_desmarcada(tmp_path):
    from src.resultado_orcamentario_cadastro import carregar_so_selecionadas

    (tmp_path / "preferencias.json").write_text("{", encoding="utf-8")
    assert carregar_so_selecionadas(tmp_path) is False
