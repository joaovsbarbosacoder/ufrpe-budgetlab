"""Extração incremental, delta e gravação versionada do cadastro de contratos
(`src/contratosgov_extracao.py`).

Nenhum teste acessa a rede: `ClienteFalso` serve as listas e os detalhes a partir de uma
fotografia (dict no formato da spec §5) e registra as chamadas. A fotografia anterior é a
fixture congelada `tests/fixtures/contratosgov_2026-10-08.json` (fatos conferidos à mão na
docstring de `tests/test_contratos_cadastro.py`), com `_sha256` injetado como faria
`carregar_atual`. Tudo o que é gravado vai para `tmp_path`.

Com a referência 08/10/2026, os vigentes da fixture são 1004328, 18940, 118872 e 220038; 7925
está encerrado e 71912 vem da lista de inativos. Os testes da política derivam esse conjunto
com `situacao_vigencia` (não o fixam à mão).
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from src import contratosgov_extracao as ext
from src.contratos_cadastro import data_iso, montar_contratos, resumo, situacao_vigencia
from src.contratosgov_api import ErroApiContratosGov
from src.contratosgov_extracao import (
    ConfirmacaoNecessaria,
    Delta,
    FotografiaAusente,
    calcular_delta,
    carregar_atual,
    consultar,
    gravar,
    historico_atualizacoes,
)

FIXTURE = Path(__file__).parent / "fixtures" / "contratosgov_2026-10-08.json"
REF = date(2026, 10, 8)
AGORA = datetime(2026, 10, 9, 10, 15, 30)
SHA_ANTERIOR = "ab" * 32  # sha256 fictício da fotografia anterior
SHA12 = SHA_ANTERIOR[:12]
TODOS = {"1004328", "18940", "118872", "220038", "7925", "71912"}


def fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def anterior() -> dict:
    foto = fixture()
    foto["_sha256"] = SHA_ANTERIOR
    return foto


def vigentes_ou_a_iniciar(foto: dict) -> set[str]:
    """Ids que a política reconsulta sempre, calculados pelas datas da lista (ref. REF)."""
    ids = set()
    for chave, inativo in (("lista_ativos", False), ("lista_inativos", True)):
        for item in foto[chave]:
            cid = str(item["id"])
            sit = situacao_vigencia(
                data_iso(item["vigencia_inicio"], contrato_id=cid, endpoint="t", campo="i"),
                data_iso(item["vigencia_fim"], contrato_id=cid, endpoint="t", campo="f"),
                inativo,
                REF,
            )
            if sit in ("vigente", "a_iniciar"):
                ids.add(cid)
    return ids


class ClienteFalso:
    """Serve a API a partir de uma fotografia; acrescenta um instrumento tipo "Empenho" à lista
    ativa (a API real traz 1.577 deles) para provar que a extração o descarta."""

    def __init__(self, foto: dict, *, falhar_no_detalhe: int | None = None):
        self.foto = copy.deepcopy(foto)
        self.falhar_no_detalhe = falhar_no_detalhe
        self.registro: list[tuple[str, str]] = []
        self._detalhes_servidos = 0

    def contratos_ug(self, ug):
        self.registro.append(("contratos_ug", ug))
        empenho = copy.deepcopy(self.foto["lista_ativos"][0])
        empenho.update({"id": 555, "tipo": "Empenho", "numero": "2026NE000001"})
        return copy.deepcopy(self.foto["lista_ativos"]) + [empenho]

    def contratos_inativos_ug(self, ug):
        self.registro.append(("contratos_inativos_ug", ug))
        return copy.deepcopy(self.foto["lista_inativos"])

    def _detalhe(self, cid, campo):
        self._detalhes_servidos += 1
        if self.falhar_no_detalhe and self._detalhes_servidos == self.falhar_no_detalhe:
            url = f"https://x/api/contrato/{cid}/{campo}"
            raise ErroApiContratosGov(f"HTTP 503 ao consultar {url}", url, 503)
        return copy.deepcopy(self.foto["detalhes"][str(cid)][campo])

    def historico(self, contrato_id):
        self.registro.append(("historico", str(contrato_id)))
        return self._detalhe(contrato_id, "historico")

    def empenhos(self, contrato_id):
        self.registro.append(("empenhos", str(contrato_id)))
        return self._detalhe(contrato_id, "empenhos")

    def detalhados(self) -> set[str]:
        return {cid for metodo, cid in self.registro if metodo == "historico"}


def _consultar(foto_api, ant, **kw):
    cliente = ClienteFalso(foto_api)
    nova = consultar(cliente, ant, referencia=REF, agora=AGORA, **kw)
    return cliente, nova


def _gravar(nova, delta, tmp_path, **kw):
    return gravar(
        nova, delta, importado_em=AGORA, referencia=REF,
        dir_manifestos=tmp_path / "manifestos", dir_fotografias=tmp_path / "raw", **kw,
    )


# --------------------------------------------------------------------------------------
# Política incremental
# --------------------------------------------------------------------------------------

def test_primeira_carga_consulta_todos():
    cliente, nova = _consultar(fixture(), None)

    assert cliente.detalhados() == TODOS
    assert set(nova["detalhes"]) == TODOS
    assert {d["origem"] for d in nova["detalhes"].values()} == {"consulta"}
    assert {d["consultado_em"] for d in nova["detalhes"].values()} == {"2026-10-09T10:15:30"}
    assert nova["versao_formato"] == 1
    assert nova["ug"] == "153165"
    assert nova["consultado_em"] == "2026-10-09T10:15:30"
    # só "Contrato": o instrumento tipo "Empenho" da lista é descartado
    assert [i["id"] for i in nova["lista_ativos"]] == [i["id"] for i in fixture()["lista_ativos"]]
    assert nova["lista_inativos"] == fixture()["lista_inativos"]
    # respostas guardadas sem transformação
    assert nova["detalhes"]["18940"]["historico"] == fixture()["detalhes"]["18940"]["historico"]
    assert "_sha256" not in nova


def test_incremental_reconsulta_so_vigentes_novos_e_alterados():
    esperado = vigentes_ou_a_iniciar(fixture())
    assert esperado and esperado < TODOS  # a fixture tem vigentes e não vigentes

    cliente, nova = _consultar(fixture(), anterior())

    assert cliente.detalhados() == esperado
    for cid in TODOS - esperado:  # encerrado (7925) e inativo (71912)
        assert nova["detalhes"][cid]["origem"] == f"reaproveitado:{SHA12}"
        assert nova["detalhes"][cid]["historico"] == fixture()["detalhes"][cid]["historico"]
        assert nova["detalhes"][cid]["consultado_em"] == fixture()["detalhes"][cid]["consultado_em"]
    for cid in esperado:
        assert nova["detalhes"][cid]["origem"] == "consulta"
    assert set(nova["detalhes"]) == TODOS


def test_reaproveitado_mantem_origem_original():
    ant = anterior()
    ant["detalhes"]["7925"]["origem"] = "reaproveitado:111111111111"
    _, nova = _consultar(fixture(), ant)
    assert nova["detalhes"]["7925"]["origem"] == "reaproveitado:111111111111"
    assert nova["detalhes"]["71912"]["origem"] == f"reaproveitado:{SHA12}"


def test_mudanca_so_em_links_nao_forca_reconsulta():
    api = fixture()
    api["lista_ativos"][0]["links"]["historico"] = "https://outro/endereco"  # 7925
    cliente, _ = _consultar(api, anterior())
    assert "7925" not in cliente.detalhados()


def test_encerrado_com_lista_alterada_e_reconsultado():
    api = fixture()
    encerrado = next(i for i in api["lista_ativos"] if i["id"] == 7925)
    encerrado["valor_global"] = "50.000,00"

    cliente, nova = _consultar(api, anterior())

    assert "7925" in cliente.detalhados()
    assert nova["detalhes"]["7925"]["origem"] == "consulta"
    assert "71912" not in cliente.detalhados()


def test_contrato_novo_e_mudanca_de_lista_sao_reconsultados():
    api = fixture()
    ant = anterior()
    # 71912 (inativo) passa a vir na lista de ativos; 7925 some da anterior (vira "novo")
    api["lista_ativos"].append(api["lista_inativos"].pop())
    ant["lista_ativos"] = [i for i in ant["lista_ativos"] if i["id"] != 7925]
    del ant["detalhes"]["7925"]

    cliente, _ = _consultar(api, ant)

    assert {"7925", "71912"} <= cliente.detalhados()


def test_completa_reconsulta_todos():
    cliente, nova = _consultar(fixture(), anterior(), completa=True)
    assert cliente.detalhados() == TODOS
    assert {d["origem"] for d in nova["detalhes"].values()} == {"consulta"}


def test_progresso_informado():
    chamadas = []
    _consultar(fixture(), anterior(), progresso=lambda feito, total: chamadas.append((feito, total)))
    n = len(vigentes_ou_a_iniciar(fixture()))
    assert chamadas[0] == (0, n)
    assert chamadas[-1] == (n, n)


def test_falha_no_meio_propaga_e_nao_grava(tmp_path):
    cliente = ClienteFalso(fixture(), falhar_no_detalhe=3)
    dir_m, dir_f = tmp_path / "manifestos", tmp_path / "raw"

    with pytest.raises(ErroApiContratosGov):
        consultar(cliente, None, referencia=REF, agora=AGORA)

    assert not dir_m.exists() and not dir_f.exists()
    assert list(tmp_path.iterdir()) == []
    assert carregar_atual(dir_m, dir_f) == (None, None)


# --------------------------------------------------------------------------------------
# Delta
# --------------------------------------------------------------------------------------

def _nova_com_todas_as_categorias() -> dict:
    nova = fixture()
    # contrato novo (sem termos nem NEs próprios: termos/NEs são comparados só entre
    # contratos presentes nas duas fotografias)
    novo = copy.deepcopy(nova["lista_ativos"][-1])
    novo.update({"id": 999999, "numero": "00099/2026"})
    nova["lista_ativos"].append(novo)
    nova["detalhes"]["999999"] = {
        "historico": [], "empenhos": [], "consultado_em": "2026-10-09T10:15:30", "origem": "consulta",
    }
    # termo novo no 18940
    termo = copy.deepcopy(nova["detalhes"]["18940"]["historico"][0])
    termo.update({"id": 9999999, "numero": "00005/2026"})
    nova["detalhes"]["18940"]["historico"].append(termo)
    # vigência do 118872 prorrogada
    next(i for i in nova["lista_ativos"] if i["id"] == 118872)["vigencia_fim"] = "2027-10-17"
    # valor global do 7925 alterado
    next(i for i in nova["lista_ativos"] if i["id"] == 7925)["valor_global"] = "50.000,00"
    # NE nova no 1004328
    ne = copy.deepcopy(nova["detalhes"]["1004328"]["empenhos"][0])
    ne.update({"id": 1, "numero": "2026NE999999"})
    nova["detalhes"]["1004328"]["empenhos"].append(ne)
    # NE do 7925 com pagamento novo
    nova["detalhes"]["7925"]["empenhos"][0]["pago"] = "30.000,00"
    return nova


def test_delta_categorias():
    delta = calcular_delta(anterior(), _nova_com_todas_as_categorias())

    assert delta.contratos_novos == [{"contrato_id": "999999", "numero": "00099/2026"}]
    assert delta.contratos_ausentes == []
    assert len(delta.termos_novos) == 1
    assert delta.termos_novos[0]["contrato_id"] == "18940"
    assert delta.termos_novos[0]["termo_id"] == "9999999"
    assert delta.termos_removidos == []
    assert delta.vigencia_alterada == [
        {"contrato_id": "118872", "numero": "00029/2021", "antes": "2026-10-17", "depois": "2027-10-17"}
    ]
    assert delta.valor_global_alterado == [
        {"contrato_id": "7925", "numero": "00018/2014", "antes": "42.822,36", "depois": "50.000,00"}
    ]
    assert delta.situacao_alterada == []
    assert len(delta.nes_novas) == 1
    assert delta.nes_novas[0]["contrato_id"] == "1004328"
    assert delta.nes_novas[0]["ne_ccor"] == "153165152392026NE999999"
    assert delta.nes_removidas == []
    assert delta.nes_movimentadas == 1
    assert delta.exige_confirmacao() is False
    assert delta.contagens() == {
        "delta_contratos_novos": 1, "delta_contratos_ausentes": 0,
        "delta_termos_novos": 1, "delta_termos_removidos": 0,
        "delta_vigencia_alterada": 1, "delta_valor_global_alterado": 1,
        "delta_situacao_alterada": 0, "delta_nes_novas": 1, "delta_nes_removidas": 0,
        "delta_nes_movimentadas": 1,
    }


def test_delta_sem_mudancas_e_vazio():
    delta = calcular_delta(anterior(), fixture())
    assert set(delta.contagens().values()) == {0}
    assert delta.exige_confirmacao() is False


def test_delta_primeira_carga():
    delta = calcular_delta(None, fixture())
    assert {c["contrato_id"] for c in delta.contratos_novos} == TODOS
    assert delta.termos_novos == [] and delta.nes_novas == []
    assert delta.exige_confirmacao() is False


def test_contrato_ausente_e_termo_removido_exigem_confirmacao():
    nova = fixture()
    nova["lista_inativos"] = []
    del nova["detalhes"]["71912"]
    removido = nova["detalhes"]["18940"]["historico"].pop()

    delta = calcular_delta(anterior(), nova)

    assert delta.contratos_ausentes == [{"contrato_id": "71912", "numero": "00011/2017"}]
    assert [t["termo_id"] for t in delta.termos_removidos] == [str(removido["id"])]
    assert delta.exige_confirmacao() is True


def test_remocoes_exigem_confirmacao(tmp_path):
    nova = fixture()
    removida = nova["detalhes"]["7925"]["empenhos"].pop(0)
    delta = calcular_delta(anterior(), nova)

    ne_ccor = f"{removida['unidade_gestora']}{removida['gestao']}{removida['numero']}"
    assert [n["ne_ccor"] for n in delta.nes_removidas] == [ne_ccor]
    assert delta.exige_confirmacao() is True

    with pytest.raises(ConfirmacaoNecessaria):
        _gravar(nova, delta, tmp_path)
    assert list(tmp_path.iterdir()) == []

    manifesto = _gravar(nova, delta, tmp_path, ciente_remocao=True)
    assert manifesto.contagens["delta_nes_removidas"] == 1
    assert (tmp_path / "raw" / manifesto.arquivo).exists()


def test_ativo_que_vira_inativo_e_situacao_alterada():
    nova = fixture()
    item = next(i for i in nova["lista_ativos"] if i["id"] == 7925)
    nova["lista_ativos"].remove(item)
    nova["lista_inativos"].append(item)

    delta = calcular_delta(anterior(), nova)

    assert delta.situacao_alterada == [
        {"contrato_id": "7925", "numero": "00018/2014", "antes": False, "depois": True}
    ]
    assert delta.contratos_ausentes == [] and delta.contratos_novos == []
    assert delta.exige_confirmacao() is False


# --------------------------------------------------------------------------------------
# Gravação e leitura
# --------------------------------------------------------------------------------------

def test_gravar_e_carregar_atual(tmp_path):
    _, nova = _consultar(fixture(), anterior())
    delta = calcular_delta(anterior(), nova)

    manifesto = _gravar(nova, delta, tmp_path)
    foto, atual = carregar_atual(tmp_path / "manifestos", tmp_path / "raw")

    assert foto.pop("_sha256") == manifesto.sha256
    assert foto == nova
    assert atual.base == "contratosgov"
    assert atual.sha256 == manifesto.sha256
    assert atual.arquivo == f"contratosgov_{manifesto.sha256[:12]}.json"
    assert atual.data_extracao == "2026-10-09T10:15:30"
    assert atual.importado_em == "2026-10-09T10:15:30"
    r = resumo(montar_contratos(nova, REF))
    n_vig = len(vigentes_ou_a_iniciar(fixture()))
    assert atual.contagens == {
        "contratos": r["total"], "vigentes": r["vigentes"], "termos": 28, "empenhos": 34,
        "reconsultados": n_vig, "reaproveitados": 6 - n_vig,
        **delta.contagens(),
    }
    assert atual.contagens["contratos"] == 6 and atual.contagens["vigentes"] == 4
    assert atual.totais == {"valor_global_vigentes": float(r["valor_global_vigentes"])}
    assert atual.totais["valor_global_vigentes"] == pytest.approx(11278519.41)
    assert atual.anos == [] and atual.totais_por_ano == {}


def test_fotografia_gravada_e_o_json_canonico(tmp_path):
    import hashlib

    nova = fixture()
    manifesto = _gravar(nova, calcular_delta(None, nova), tmp_path)
    conteudo = (tmp_path / "raw" / manifesto.arquivo).read_bytes()
    esperado = json.dumps(nova, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    assert conteudo == esperado
    assert manifesto.sha256 == hashlib.sha256(esperado).hexdigest()


def test_gravar_remove_sha_injetado(tmp_path):
    foto = anterior()  # tem _sha256, como vem de carregar_atual
    manifesto = _gravar(foto, calcular_delta(None, foto), tmp_path)
    gravada = json.loads((tmp_path / "raw" / manifesto.arquivo).read_text(encoding="utf-8"))
    assert "_sha256" not in gravada
    assert "_sha256" in foto  # o dict recebido não é modificado


def test_gravar_duas_vezes_nao_sobrescreve(tmp_path):
    primeira = fixture()
    m1 = _gravar(primeira, calcular_delta(None, primeira), tmp_path)
    ant, _ = carregar_atual(tmp_path / "manifestos", tmp_path / "raw")

    segunda = _nova_com_todas_as_categorias()
    segunda["consultado_em"] = "2026-10-10T08:00:00"
    m2 = gravar(
        segunda, calcular_delta(ant, segunda), importado_em=datetime(2026, 10, 10, 8, 5),
        referencia=REF, dir_manifestos=tmp_path / "manifestos", dir_fotografias=tmp_path / "raw",
    )

    assert m1.arquivo != m2.arquivo
    assert sorted(p.name for p in (tmp_path / "raw").iterdir()) == sorted([m1.arquivo, m2.arquivo])
    hist = historico_atualizacoes(tmp_path / "manifestos")
    assert [m.sha256 for m in hist] == [m2.sha256, m1.sha256]
    assert carregar_atual(tmp_path / "manifestos", tmp_path / "raw")[1].sha256 == m2.sha256


def test_historico_vazio(tmp_path):
    assert historico_atualizacoes(tmp_path / "manifestos") == []


def test_manifesto_aponta_arquivo_inexistente(tmp_path):
    nova = fixture()
    manifesto = _gravar(nova, calcular_delta(None, nova), tmp_path)
    (tmp_path / "raw" / manifesto.arquivo).unlink()

    with pytest.raises(FotografiaAusente, match=manifesto.arquivo):
        carregar_atual(tmp_path / "manifestos", tmp_path / "raw")


def test_fotografia_alterada_depois_de_gravada_e_erro(tmp_path):
    nova = fixture()
    manifesto = _gravar(nova, calcular_delta(None, nova), tmp_path)
    caminho = tmp_path / "raw" / manifesto.arquivo
    caminho.write_bytes(caminho.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="sha256"):
        carregar_atual(tmp_path / "manifestos", tmp_path / "raw")


def test_so_escreve_nos_diretorios_previstos(tmp_path):
    (tmp_path / "outro").mkdir()
    (tmp_path / "outro" / "intocado.txt").write_text("x", encoding="utf-8")
    antes = {p for p in tmp_path.rglob("*") if p.is_file()}

    _, nova = _consultar(fixture(), None)
    _gravar(nova, calcular_delta(None, nova), tmp_path)

    novos = {p for p in tmp_path.rglob("*") if p.is_file()} - antes
    assert novos
    for p in novos:
        assert p.parent in (tmp_path / "manifestos", tmp_path / "raw"), p
    assert {p.parent for p in novos} == {tmp_path / "manifestos", tmp_path / "raw"}


def test_diretorios_padrao_lidos_em_tempo_de_chamada(tmp_path, monkeypatch):
    monkeypatch.setattr(ext, "DIRETORIO_MANIFESTOS", tmp_path / "m")
    monkeypatch.setattr(ext, "DIRETORIO_FOTOGRAFIAS", tmp_path / "f")
    nova = fixture()
    gravar(nova, calcular_delta(None, nova), importado_em=AGORA, referencia=REF)
    foto, manifesto = carregar_atual()
    assert manifesto is not None and foto["ug"] == "153165"
    assert len(historico_atualizacoes()) == 1


def test_constantes_do_modulo():
    assert ext.BASE == "contratosgov"
    assert ext.UG_UFRPE == "153165"
    assert ext.DIRETORIO_FOTOGRAFIAS == Path("data/raw/contratosgov")
    assert ext.DIRETORIO_MANIFESTOS == Path("data/manifestos")
    assert isinstance(Delta(), Delta)
