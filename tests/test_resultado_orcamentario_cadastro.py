"""Testes da persistência da seleção de células e das despesas manuais do Resultado Orçamentário."""

import pytest

from src.resultado_orcamentario_cadastro import (
    ArquivoCorrompido,
    atualizar_despesa,
    carregar_avisos_ok,
    carregar_despesas,
    carregar_selecao,
    definir_consideracao,
    excluir_despesa,
    incluir_despesa,
    salvar_avisos_ok,
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


def test_despesa_nova_vem_considerada_e_a_escolha_fica_gravada(tmp_path):
    a = incluir_despesa(2026, "Obra A", 100.0, None, None, tmp_path)
    b = incluir_despesa(2026, "Obra B", 200.0, None, None, tmp_path)
    assert a.considerada is True
    definir_consideracao(2026, a.id, False, tmp_path)
    por_id = {d.id: d for d in carregar_despesas(2026, tmp_path)}
    assert por_id[a.id].considerada is False and por_id[b.id].considerada is True
    definir_consideracao(2026, a.id, True, tmp_path)
    assert carregar_despesas(2026, tmp_path)[0].considerada is True


def test_definir_consideracao_nao_mexe_na_data_de_atualizacao_e_editar_preserva_a_escolha(tmp_path):
    a = incluir_despesa(2026, "Obra A", 100.0, None, None, tmp_path)
    definir_consideracao(2026, a.id, False, tmp_path)
    assert carregar_despesas(2026, tmp_path)[0].atualizado_em == a.atualizado_em
    atualizar_despesa(2026, a.id, "Obra A", 150.0, None, None, tmp_path)
    editada = carregar_despesas(2026, tmp_path)[0]
    assert editada.valor == 150.0 and editada.considerada is False


def test_arquivo_antigo_sem_o_campo_vale_como_considerada(tmp_path):
    pasta = tmp_path / "2026"
    pasta.mkdir()
    (pasta / "despesas_manuais.json").write_text(
        '{"despesas": [{"id": "x", "descricao": "Antiga", "valor": 10.0, "observacao": null, "celula": null, '
        '"criado_em": "2026-10-08T00:00:00+00:00", "atualizado_em": "2026-10-08T00:00:00+00:00"}]}', encoding="utf-8",
    )
    assert carregar_despesas(2026, tmp_path)[0].considerada is True


def test_definir_consideracao_de_despesa_inexistente_levanta(tmp_path):
    with pytest.raises(KeyError):
        definir_consideracao(2026, "nao-existe", False, tmp_path)


def test_avisos_ok_ida_e_volta_e_arquivo_ausente(tmp_path):
    assert carregar_avisos_ok(2026, tmp_path) == set()
    salvar_avisos_ok(2026, {"Aviso B", "Aviso A"}, tmp_path)
    assert carregar_avisos_ok(2026, tmp_path) == {"Aviso A", "Aviso B"}
    assert carregar_avisos_ok(2025, tmp_path) == set()  # por exercício


def test_avisos_ok_arquivo_corrompido_ou_em_formato_inesperado_levanta(tmp_path):
    (tmp_path / "2026").mkdir()
    arquivo = tmp_path / "2026" / "avisos_ok.json"
    arquivo.write_text("{não é json", encoding="utf-8")
    with pytest.raises(ArquivoCorrompido):
        carregar_avisos_ok(2026, tmp_path)
    arquivo.write_text('{"avisos": [1, 2]}', encoding="utf-8")
    with pytest.raises(ArquivoCorrompido):
        carregar_avisos_ok(2026, tmp_path)


def test_receitas_ida_e_volta_e_consideracao(tmp_path):
    from src.resultado_orcamentario_cadastro import (
        carregar_receitas, definir_consideracao_receita, excluir_receita, incluir_receita,
    )

    assert carregar_receitas(2026, tmp_path) == []
    nova = incluir_receita(2026, "  Fonte 050 ", 1234.5, "set/2026", tmp_path)
    (lida,) = carregar_receitas(2026, tmp_path)
    assert (lida.descricao, lida.valor, lida.observacao, lida.considerada) == ("Fonte 050", 1234.5, "set/2026", True)
    definir_consideracao_receita(2026, nova.id, False, tmp_path)
    assert carregar_receitas(2026, tmp_path)[0].considerada is False
    excluir_receita(2026, nova.id, tmp_path)
    assert carregar_receitas(2026, tmp_path) == []


@pytest.mark.parametrize("valor", [None, 0.0, -5.0])
def test_receita_valor_invalido_recusado(tmp_path, valor):
    from src.resultado_orcamentario_cadastro import carregar_receitas, incluir_receita, validar_receita

    assert validar_receita("x", valor)
    with pytest.raises(ValueError):
        incluir_receita(2026, "x", valor, None, tmp_path)
    assert carregar_receitas(2026, tmp_path) == []


def test_receitas_arquivo_corrompido_levanta(tmp_path):
    from src.resultado_orcamentario_cadastro import carregar_receitas

    (tmp_path / "2026").mkdir()
    (tmp_path / "2026" / "receitas_proprias.json").write_text("{nao é json", encoding="utf-8")
    with pytest.raises(ArquivoCorrompido):
        carregar_receitas(2026, tmp_path)


def test_receita_com_gnd_e_acao_ida_e_volta_e_exige_os_dois(tmp_path):
    from src.resultado_orcamentario_cadastro import carregar_receitas, incluir_receita, validar_receita

    incluir_receita(2026, "Fonte 050", 10.0, None, tmp_path, gnd="3", acao="20RK")
    incluir_receita(2026, "Sem destino", 5.0, None, tmp_path)
    com, sem = carregar_receitas(2026, tmp_path)
    assert (com.gnd, com.acao) == ("3", "20RK") and (sem.gnd, sem.acao) == (None, None)
    assert validar_receita("x", 1.0, "3", None) and validar_receita("x", 1.0, None, "20RK")
    assert validar_receita("x", 1.0, "3", "20RK") == [] and validar_receita("x", 1.0) == []
    with pytest.raises(ValueError):
        incluir_receita(2026, "x", 1.0, None, tmp_path, gnd="3")
    assert len(carregar_receitas(2026, tmp_path)) == 2
