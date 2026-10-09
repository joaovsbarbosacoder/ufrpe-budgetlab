"""Testes do cliente HTTP do Contratos.gov.br (`src/contratosgov_api.py`).

Nenhum teste toca a rede: a sessão é um `Mock` e as pausas são registradas numa lista.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from src.contratosgov_api import URL_BASE, ClienteContratosGov, ErroApiContratosGov


def _resposta(status=200, dados=None, headers=None, json_erro=None):
    r = Mock()
    r.status_code = status
    r.headers = headers or {}
    if json_erro is not None:
        r.json.side_effect = json_erro
    else:
        r.json.return_value = dados if dados is not None else []
    return r


def _cliente(*respostas, **kw):
    sessao = Mock()
    sessao.get.side_effect = list(respostas)
    pausas: list[float] = []
    kw.setdefault("pausa_entre_chamadas", 0)
    cliente = ClienteContratosGov(sessao, dormir=pausas.append, **kw)
    return cliente, sessao, pausas


def test_get_json_monta_url_e_devolve_json():
    cliente, sessao, _ = _cliente(_resposta(dados=[{"id": 1}]))
    assert cliente.contratos_ug("153165") == [{"id": 1}]
    sessao.get.assert_called_once_with(
        "https://contratos.comprasnet.gov.br/api/contrato/ug/153165", timeout=180
    )
    assert URL_BASE == "https://contratos.comprasnet.gov.br"


def test_listas_usam_prazo_longo_e_detalhes_o_curto():
    """A lista de contratos ativos leva ~50 s para o servidor começar a responder (medido em
    09/10/2026, 4,8 MB); os detalhes por contrato respondem em ~0,4 s."""
    cliente, sessao, _ = _cliente(*[_resposta() for _ in range(4)])
    cliente.contratos_ug("153165")
    cliente.contratos_inativos_ug("153165")
    cliente.historico("1004328")
    cliente.empenhos("1004328")
    prazos = [c.kwargs["timeout"] for c in sessao.get.call_args_list]
    assert prazos == [180, 180, 30, 30]


def test_prazos_sao_configuraveis():
    cliente, sessao, _ = _cliente(_resposta(), _resposta(), timeout=7, timeout_lista=90)
    cliente.contratos_ug("153165")
    cliente.historico("1004328")
    assert [c.kwargs["timeout"] for c in sessao.get.call_args_list] == [90, 7]


def test_rotas_dos_quatro_metodos():
    cliente, sessao, _ = _cliente(*[_resposta() for _ in range(4)])
    cliente.contratos_ug("153165")
    cliente.contratos_inativos_ug("153165")
    cliente.historico("1004328")
    cliente.empenhos("1004328")
    urls = [c.args[0] for c in sessao.get.call_args_list]
    assert urls == [
        f"{URL_BASE}/api/contrato/ug/153165",
        f"{URL_BASE}/api/contrato/inativo/ug/153165",
        f"{URL_BASE}/api/contrato/1004328/historico",
        f"{URL_BASE}/api/contrato/1004328/empenhos",
    ]


def test_repete_em_5xx_e_depois_sucede():
    cliente, _, pausas = _cliente(_resposta(503), _resposta(503), _resposta(dados=[1]))
    assert cliente.contratos_ug("1") == [1]
    assert cliente.chamadas == 3
    assert pausas == [2.0, 4.0]


def test_aborta_apos_esgotar_tentativas():
    cliente, sessao, _ = _cliente(*[_resposta(500) for _ in range(4)])
    with pytest.raises(ErroApiContratosGov) as exc:
        cliente.contratos_ug("1")
    assert exc.value.status == 500
    assert "/api/contrato/ug/1" in str(exc.value)
    assert exc.value.url.endswith("/api/contrato/ug/1")
    assert sessao.get.call_count == 4


def test_429_respeita_retry_after():
    cliente, _, pausas = _cliente(
        _resposta(429, headers={"Retry-After": "7"}), _resposta(dados=[])
    )
    cliente.contratos_ug("1")
    assert pausas == [7.0]


def test_4xx_aborta_sem_repetir():
    cliente, sessao, _ = _cliente(_resposta(404))
    with pytest.raises(ErroApiContratosGov) as exc:
        cliente.historico("9")
    assert exc.value.status == 404
    assert sessao.get.call_count == 1


def test_timeout_e_erro_de_conexao_repetem():
    cliente, _, _ = _cliente(
        requests.Timeout(), requests.Timeout(), _resposta(dados=[{"a": 1}])
    )
    assert cliente.contratos_ug("1") == [{"a": 1}]

    cliente, _, _ = _cliente(*[requests.ConnectionError() for _ in range(4)])
    with pytest.raises(ErroApiContratosGov) as exc:
        cliente.contratos_ug("1")
    assert exc.value.status is None


def test_json_invalido_aborta():
    cliente, _, _ = _cliente(_resposta(json_erro=ValueError("x")))
    with pytest.raises(ErroApiContratosGov):
        cliente.contratos_ug("1")


def test_pausa_entre_chamadas_so_apos_a_primeira():
    cliente, _, pausas = _cliente(_resposta(), _resposta(), pausa_entre_chamadas=0.2)
    cliente.contratos_ug("1")
    assert pausas == []
    cliente.contratos_ug("2")
    assert pausas == [0.2]


def test_chunked_encoding_error_e_repetido():
    cliente, sessao, _ = _cliente(requests.exceptions.ChunkedEncodingError(), _resposta(dados=[1]))
    assert cliente.contratos_ug("1") == [1]
    assert sessao.get.call_count == 2


def test_outra_excecao_do_requests_vira_erro_sem_repetir():
    cliente, sessao, _ = _cliente(requests.exceptions.InvalidURL("url ruim"), _resposta(dados=[1]))
    with pytest.raises(ErroApiContratosGov) as exc:
        cliente.contratos_ug("1")
    assert exc.value.status is None
    assert exc.value.url.endswith("/api/contrato/ug/1")
    assert sessao.get.call_count == 1


@pytest.mark.parametrize("retry_after", ["-5", "nan", "inf", "-inf", "abc"])
def test_retry_after_invalido_cai_na_pausa_exponencial(retry_after):
    cliente, _, pausas = _cliente(_resposta(429, headers={"Retry-After": retry_after}), _resposta(dados=[]))
    cliente.contratos_ug("1")
    assert pausas == [2.0]


def test_retry_after_grande_e_limitado_a_60_segundos():
    cliente, _, pausas = _cliente(_resposta(429, headers={"Retry-After": "600"}), _resposta(dados=[]))
    cliente.contratos_ug("1")
    assert pausas == [60.0]
