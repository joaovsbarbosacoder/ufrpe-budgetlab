"""Complementos manuais do cadastro de Contratos (valor mensal e observações).

Os complementos são digitados pelo usuário e ficam guardados por id de contrato, separados
dos dados vindos da API do Contratos.gov.br: uma atualização da API nunca os toca, e um
complemento cujo contrato sumiu da API é preservado (ver `complementos_ausentes`).

Regras:
  * Valor mensal em texto BR ("862.858,76" ou "862858,76"), com no máximo 2 casas, nunca
    negativo. Vazio = nulo (valor não informado); "0,00" = zero. São coisas diferentes.
  * Gravado como texto ("862858.76") e lido como `Decimal`, sem ponto flutuante.
  * Gravação atômica (temporário + `replace`). Arquivo ilegível LANÇA `ValueError` em vez de
    cair em "nenhum complemento": voltar em silêncio a vazio esconderia dados digitados, e a
    próxima gravação os sobrescreveria.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

CAMINHO_PADRAO = Path("data/contratos/complementos.json")
VERSAO_FORMATO = 1

# Milhar opcional com ponto, vírgula decimal opcional com 1 ou 2 casas.
_VALOR_BR = re.compile(r"^(\d{1,3}(\.\d{3})+|\d+)(,\d{1,2})?$")


@dataclass(frozen=True)
class Complemento:
    contrato_id: str
    valor_mensal: Decimal | None
    observacoes: str
    alterado_em: str


def _interpretar_valor(texto: str) -> Decimal | None:
    texto = (texto or "").strip()
    if not texto:
        return None
    if not _VALOR_BR.match(texto):
        raise ValueError(
            f"Valor mensal inválido: {texto!r}. Use o formato 862.858,76 "
            "(até 2 casas decimais, sem sinal)."
        )
    valor = Decimal(texto.replace(".", "").replace(",", "."))
    return valor.quantize(Decimal("0.01"))


def _de_json(contrato_id: str, dado: dict) -> Complemento:
    bruto = dado["valor_mensal"]
    return Complemento(
        contrato_id=str(contrato_id),
        valor_mensal=None if bruto is None else Decimal(str(bruto)),
        observacoes=str(dado.get("observacoes") or ""),
        alterado_em=str(dado["alterado_em"]),
    )


def _para_json(complemento: Complemento) -> dict:
    return {
        "valor_mensal": None if complemento.valor_mensal is None else str(complemento.valor_mensal),
        "observacoes": complemento.observacoes,
        "alterado_em": complemento.alterado_em,
    }


def carregar_complementos(caminho: str | Path | None = None) -> dict[str, Complemento]:
    """Complementos gravados, por id de contrato. Arquivo inexistente = `{}`; ilegível ou
    malformado lança `ValueError` com o caminho."""

    caminho = Path(CAMINHO_PADRAO if caminho is None else caminho)
    if not caminho.exists():
        return {}
    try:
        dado = json.loads(caminho.read_text(encoding="utf-8"))
        return {str(id_): _de_json(id_, item) for id_, item in dado["complementos"].items()}
    except (OSError, json.JSONDecodeError, KeyError, TypeError, AttributeError, ValueError, InvalidOperation) as error:
        raise ValueError(f"Arquivo de complementos ilegível ({caminho}): {error}") from error


def _gravar(complementos: dict[str, Complemento], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    dado = {
        "versao_formato": VERSAO_FORMATO,
        "complementos": {id_: _para_json(item) for id_, item in complementos.items()},
    }
    temporario = caminho.parent / f".{caminho.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(json.dumps(dado, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()


def salvar_complemento(
    contrato_id: str,
    valor_mensal: str,
    observacoes: str,
    *,
    caminho: str | Path | None = None,
    agora: datetime | None = None,
) -> Complemento:
    """Cria ou substitui o complemento de um contrato, preservando os demais. Valida antes de
    tocar no arquivo."""

    valor = _interpretar_valor(valor_mensal)
    caminho = Path(CAMINHO_PADRAO if caminho is None else caminho)
    existentes = carregar_complementos(caminho)
    novo = Complemento(
        contrato_id=str(contrato_id),
        valor_mensal=valor,
        observacoes=str(observacoes or ""),
        alterado_em=(agora or datetime.now()).isoformat(),
    )
    existentes[novo.contrato_id] = novo
    _gravar(existentes, caminho)
    return novo


def complementos_ausentes(
    complementos: dict[str, Complemento], ids_atuais: set[str]
) -> list[Complemento]:
    """Complementos de contratos que não estão mais na base atual da API (preservados)."""

    return [item for id_, item in complementos.items() if id_ not in ids_atuais]
