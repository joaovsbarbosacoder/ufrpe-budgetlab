"""Complementos manuais do cadastro de contratos (`src/contratos_complementos.py`)."""

from datetime import datetime
from decimal import Decimal

import pytest

from src.contratos_complementos import (
    carregar_complementos,
    complementos_ausentes,
    salvar_complemento,
)

AGORA = datetime(2026, 10, 8, 14, 30, 0)


def test_ida_e_volta(tmp_path):
    caminho = tmp_path / "complementos.json"
    salvar_complemento("18940", "862.858,76", "Repactuação", caminho=caminho, agora=AGORA)

    comp = carregar_complementos(caminho)["18940"]
    assert comp.contrato_id == "18940"
    assert comp.valor_mensal == Decimal("862858.76")
    assert comp.observacoes == "Repactuação"
    assert comp.alterado_em == AGORA.isoformat()


def test_aceita_valor_sem_separador_de_milhar(tmp_path):
    comp = salvar_complemento("1", "862858,76", "", caminho=tmp_path / "c.json", agora=AGORA)
    assert comp.valor_mensal == Decimal("862858.76")


def test_vazio_e_nulo_e_zero_e_zero(tmp_path):
    caminho = tmp_path / "c.json"
    assert salvar_complemento("1", "", "", caminho=caminho, agora=AGORA).valor_mensal is None
    zero = salvar_complemento("2", "0,00", "", caminho=caminho, agora=AGORA).valor_mensal
    assert zero == Decimal("0.00")
    recarregado = carregar_complementos(caminho)
    assert recarregado["1"].valor_mensal is None
    assert recarregado["2"].valor_mensal == Decimal("0.00")


@pytest.mark.parametrize("texto", ["1,234", "-5,00", "abc"])
def test_rejeita_invalidos(tmp_path, texto):
    caminho = tmp_path / "c.json"
    with pytest.raises(ValueError):
        salvar_complemento("1", texto, "", caminho=caminho, agora=AGORA)
    assert not caminho.exists()


def test_invalido_nao_altera_arquivo_existente(tmp_path):
    caminho = tmp_path / "c.json"
    salvar_complemento("1", "10,00", "", caminho=caminho, agora=AGORA)
    antes = caminho.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        salvar_complemento("1", "x", "", caminho=caminho, agora=AGORA)
    assert caminho.read_text(encoding="utf-8") == antes


def test_outro_contrato_preservado(tmp_path):
    caminho = tmp_path / "c.json"
    salvar_complemento("1", "10,00", "um", caminho=caminho, agora=AGORA)
    salvar_complemento("2", "20,00", "dois", caminho=caminho, agora=AGORA)
    segundo = carregar_complementos(caminho)["2"]

    salvar_complemento("1", "11,00", "um bis", caminho=caminho, agora=datetime(2026, 10, 9))
    final = carregar_complementos(caminho)
    assert final["2"] == segundo
    assert final["1"].valor_mensal == Decimal("11.00")


def test_arquivo_inexistente_e_vazio(tmp_path):
    assert carregar_complementos(tmp_path / "nao_existe.json") == {}


def test_arquivo_ilegivel_e_erro(tmp_path):
    caminho = tmp_path / "c.json"
    caminho.write_text("{quebrado", encoding="utf-8")
    with pytest.raises(ValueError, match="c.json"):
        carregar_complementos(caminho)
    with pytest.raises(ValueError):
        salvar_complemento("1", "1,00", "", caminho=caminho, agora=AGORA)
    assert caminho.read_text(encoding="utf-8") == "{quebrado"


def test_gravacao_atomica_nao_deixa_temporario(tmp_path):
    salvar_complemento("1", "10,00", "", caminho=tmp_path / "c.json", agora=AGORA)
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_complementos_ausentes(tmp_path):
    caminho = tmp_path / "c.json"
    salvar_complemento("1", "1,00", "", caminho=caminho, agora=AGORA)
    salvar_complemento("2", "2,00", "", caminho=caminho, agora=AGORA)
    ausentes = complementos_ausentes(carregar_complementos(caminho), {"1"})
    assert [c.contrato_id for c in ausentes] == ["2"]
