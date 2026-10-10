"""
Cliente HTTP somente leitura da API pública do Contratos.gov.br.

Camada de acesso à rede: único módulo do projeto que fala com
`https://contratos.comprasnet.gov.br`. Só faz requisições GET e devolve o JSON bruto,
sem conversão de valores nem regra de negócio — a normalização e a interpretação dos
campos vivem em outros módulos. Não importa Streamlit e não grava nada em disco.

Resiliência: erros transitórios (HTTP 5xx, timeout, falha de conexão) são repetidos até
`tentativas` vezes, com pausa exponencial `pausa_base * 2**(n-1)`. HTTP 429 respeita o
cabeçalho `Retry-After` numérico, finito e não negativo (limitado a 60 s); senão usa a pausa
exponencial. Timeout, falha de conexão e ChunkedEncodingError são transitórios; as demais
`requests.RequestException` abortam sem repetir (`status` None). Demais 4xx abortam sem repetir. Esgotadas
as tentativas, ou diante de JSON inválido, levanta `ErroApiContratosGov` — nunca devolve
dado parcial em silêncio. Entre chamadas consecutivas há uma pequena pausa de cortesia
(`pausa_entre_chamadas`). `dormir` é injetável para que os testes não esperem de verdade.

Prazos de espera: a lista de contratos ativos da UG (4,8 MB, ~1.800 itens) leva de 45 a 55 s
para o servidor começar a responder (medido em 09/10/2026; a conexão em si leva 0,1 s e a lista
de inativos, 0,6 s), então as duas listas usam `timeout_lista` (180 s). Os detalhes por contrato
respondem em ~0,4 s e seguem com `timeout` (30 s). Com 3 novas tentativas, uma lista que nunca
responda pode levar até ~12 min para falhar.
"""

from __future__ import annotations

import math
import time
from typing import Callable

import requests

URL_BASE = "https://contratos.comprasnet.gov.br"
LIMITE_RETRY_AFTER = 60.0  # segundos: teto da pausa pedida pelo servidor


class ErroApiContratosGov(RuntimeError):
    """Falha ao consultar a API; `status` é None quando não houve resposta HTTP."""

    def __init__(self, mensagem: str, url: str, status: int | None = None):
        super().__init__(mensagem)
        self.url = url
        self.status = status


class ClienteContratosGov:
    def __init__(
        self,
        sessao: requests.Session | None = None,
        *,
        timeout: float = 30,
        timeout_lista: float = 180,
        tentativas: int = 3,
        pausa_base: float = 2.0,
        pausa_entre_chamadas: float = 0.2,
        dormir: Callable[[float], None] = time.sleep,
    ):
        self._sessao = sessao if sessao is not None else requests.Session()
        self._timeout = timeout
        self._timeout_lista = timeout_lista
        self._tentativas = tentativas
        self._pausa_base = pausa_base
        self._pausa_entre_chamadas = pausa_entre_chamadas
        self._dormir = dormir
        #: total de requisições HTTP feitas (inclui novas tentativas).
        self.chamadas = 0

    def _requisitar(self, url: str, timeout: float):
        """Uma requisição, respeitando a pausa entre chamadas. Devolve resposta ou exceção."""
        if self.chamadas > 0 and self._pausa_entre_chamadas > 0:
            self._dormir(self._pausa_entre_chamadas)
        self.chamadas += 1
        return self._sessao.get(url, timeout=timeout)

    @staticmethod
    def _pausa_retry_after(resposta, padrao: float) -> float:
        """`Retry-After` numérico, finito e não negativo, limitado a `LIMITE_RETRY_AFTER`;
        qualquer outro valor (ausente, negativo, nan, inf, data) usa a pausa exponencial."""
        try:
            valor = float(resposta.headers.get("Retry-After"))
        except (TypeError, ValueError):
            return padrao
        if not math.isfinite(valor) or valor < 0:
            return padrao
        return min(valor, LIMITE_RETRY_AFTER)

    def get_json(self, caminho: str, *, timeout: float | None = None) -> list | dict:
        url = f"{URL_BASE}{caminho}"
        prazo = self._timeout if timeout is None else timeout
        for n in range(self._tentativas + 1):
            ultima = n == self._tentativas
            pausa = self._pausa_base * 2**n
            try:
                resposta = self._requisitar(url, prazo)
            except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as exc:
                if ultima:
                    raise ErroApiContratosGov(
                        f"Falha de conexão com {url}: {exc}", url
                    ) from exc
                self._dormir(pausa)
                continue
            except requests.RequestException as exc:  # demais falhas do requests: sem repetir
                raise ErroApiContratosGov(
                    f"Falha ao consultar {url}: {exc}", url
                ) from exc

            status = resposta.status_code
            if status == 429 or status >= 500:
                if ultima:
                    raise ErroApiContratosGov(
                        f"HTTP {status} ao consultar {url}", url, status
                    )
                if status == 429:
                    pausa = self._pausa_retry_after(resposta, pausa)
                self._dormir(pausa)
                continue
            if status >= 400:
                raise ErroApiContratosGov(f"HTTP {status} ao consultar {url}", url, status)
            try:
                return resposta.json()
            except ValueError as exc:
                raise ErroApiContratosGov(
                    f"Resposta não é JSON válido em {url}", url, status
                ) from exc
        raise AssertionError("inalcançável")  # pragma: no cover

    def contratos_ug(self, ug: str) -> list[dict]:
        return self.get_json(f"/api/contrato/ug/{ug}", timeout=self._timeout_lista)

    def contratos_inativos_ug(self, ug: str) -> list[dict]:
        return self.get_json(f"/api/contrato/inativo/ug/{ug}", timeout=self._timeout_lista)

    def historico(self, contrato_id: str) -> list[dict]:
        return self.get_json(f"/api/contrato/{contrato_id}/historico")

    def empenhos(self, contrato_id: str) -> list[dict]:
        return self.get_json(f"/api/contrato/{contrato_id}/empenhos")
