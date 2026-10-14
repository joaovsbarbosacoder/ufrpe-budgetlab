"""
Ajustes manuais da Projeção pela Execução de Contratos Contínuos (14/10/2026).

Camada: regra pura + persistência por eventos. O usuário grava o ESPERADO TOTAL de um mês de uma NE; a projeção usa
esse valor no lugar de "custo × fator" (ver `relatorio_projecao_execucao.projetar_meses`) e continua descontando o
liquidado do mês. Padrão de `src/decisoes_conciliacao.py`:

  * Uma pasta por exercício em `data/projecao_execucao/<exercício>/` (PERSISTÊNCIA aprovada pelo usuário em
    14/10/2026; fora do Git), um arquivo JSON por evento, gravação atômica (tmp + replace), `versao_schema` 1.
    Evento nunca é alterado nem apagado; refazer ACRESCENTA um evento. Pasta com arquivo ilegível levanta
    `ErroAjuste` — nunca vira "sem ajustes" em silêncio e nada é gravado por cima.
  * Eventos: "ajustar" (`valores`: mês 1-12 → esperado, ou `None` para voltar o mês à metodologia), "refazer_ne" e
    "refazer_tudo". O estado vigente é reconstruído em ordem: o último evento de cada mês vence.
  * Zero (0,00) é ajuste válido; negativo, nan e infinito são recusados. `ne_curta` é texto, nunca número.

Contrato público:
    ErroAjuste
    registrar_ajustes(*, exercicio, ne_curta, valores, extracao, diretorio=None) -> dict
    refazer_ne(*, exercicio, ne_curta, extracao, diretorio=None) -> dict
    refazer_tudo(*, exercicio, extracao, diretorio=None) -> dict
    carregar_eventos(exercicio, diretorio=None) -> list[dict]
    reconstruir(eventos) -> {ne_curta: {mês: esperado}}
    ajustes_vigentes(exercicio, diretorio=None) -> {ne_curta: {mês: esperado}}
"""

from __future__ import annotations

import json
import math
import os
import uuid
from datetime import datetime
from pathlib import Path

DIRETORIO_AJUSTES = Path("data/projecao_execucao")
VERSAO_SCHEMA = 1
TIPOS = ("ajustar", "refazer_ne", "refazer_tudo")


class ErroAjuste(ValueError):
    """Ajuste inválido ou pasta de ajustes ilegível."""


def _pasta(exercicio: int, diretorio: Path | None) -> Path:
    return Path(diretorio if diretorio is not None else DIRETORIO_AJUSTES) / str(int(exercicio))


def _agora() -> str:
    """Com microssegundos: duas ações no mesmo segundo precisam manter a ordem (a mais recente vale)."""
    return datetime.now().isoformat()


def _gravar(evento: dict, exercicio: int, diretorio: Path | None) -> None:
    # Não grava por cima de um log que não dá para ler: o erro aparece antes de qualquer escrita.
    carregar_eventos(exercicio, diretorio)
    pasta = _pasta(exercicio, diretorio)
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = evento["registrado_em"].replace(":", "").replace("-", "").replace(".", "")
    caminho = pasta / f"{carimbo}_{evento['id'][:8]}.json"
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text(json.dumps(evento, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temporario, caminho)


def _validar_evento(evento: dict) -> None:
    """Estrutura mínima de um evento lido do disco; qualquer falha vira `ErroAjuste` em `carregar_eventos`. Uma página
    nunca deve cair por causa de um arquivo editado à mão ou de schema futuro."""

    if not isinstance(evento["registrado_em"], str) or not isinstance(evento["id"], str):
        raise TypeError("registrado_em/id")
    if evento["tipo"] == "refazer_tudo":
        return
    if not isinstance(evento["ne_curta"], str) or not evento["ne_curta"].strip():
        raise ValueError("ne_curta")
    if evento["tipo"] == "refazer_ne":
        return
    valores = evento["valores"]
    if not isinstance(valores, dict) or not valores:
        raise TypeError("valores")
    for mes, valor in valores.items():
        if not 1 <= int(mes) <= 12:
            raise ValueError(f"mês {mes}")
        if valor is None:
            continue
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor < 0:
            raise ValueError(f"valor {valor!r}")


def carregar_eventos(exercicio: int, diretorio: Path | None = None) -> list[dict]:
    pasta = _pasta(exercicio, diretorio)
    if not pasta.exists():
        return []
    eventos = []
    for caminho in sorted(pasta.glob("*.json")):
        try:
            evento = json.loads(caminho.read_text(encoding="utf-8"))
            if evento["versao_schema"] != VERSAO_SCHEMA or evento["tipo"] not in TIPOS:
                raise KeyError("tipo/versão")
            _validar_evento(evento)
        except (OSError, ValueError, KeyError, TypeError) as erro:
            raise ErroAjuste(f"Não foi possível ler {caminho}: {erro}") from erro
        eventos.append(evento)
    return sorted(eventos, key=lambda e: (e["registrado_em"], e["id"]))


def _ne(ne_curta: str) -> str:
    ne = str(ne_curta or "").strip()
    if not ne:
        raise ErroAjuste("Informe a NE.")
    return ne


def _evento(tipo: str, extracao: str, **campos) -> dict:
    return {
        "versao_schema": VERSAO_SCHEMA, "tipo": tipo, "id": uuid.uuid4().hex, "registrado_em": _agora(),
        "extracao": str(extracao), **campos,
    }


def registrar_ajustes(
    *, exercicio: int, ne_curta: str, valores: dict[int, float | None], extracao: str, diretorio: Path | None = None,
) -> dict:
    ne = _ne(ne_curta)
    if not valores:
        raise ErroAjuste("Nenhum mês informado.")
    limpos: dict[str, float | None] = {}
    for mes, valor in valores.items():
        if not 1 <= int(mes) <= 12:
            raise ErroAjuste(f"Mês inválido: {mes!r} (use 1 a 12).")
        if valor is None:
            limpos[str(int(mes))] = None
            continue
        numero = float(valor)
        if math.isnan(numero) or math.isinf(numero) or numero < 0:
            raise ErroAjuste(f"Valor inválido para o mês {mes}: {valor!r} (use zero ou um número positivo).")
        limpos[str(int(mes))] = round(numero, 2)
    evento = _evento("ajustar", extracao, ne_curta=ne, valores=limpos)
    _gravar(evento, exercicio, diretorio)
    return evento


def refazer_ne(*, exercicio: int, ne_curta: str, extracao: str, diretorio: Path | None = None) -> dict:
    evento = _evento("refazer_ne", extracao, ne_curta=_ne(ne_curta))
    _gravar(evento, exercicio, diretorio)
    return evento


def refazer_tudo(*, exercicio: int, extracao: str, diretorio: Path | None = None) -> dict:
    evento = _evento("refazer_tudo", extracao)
    _gravar(evento, exercicio, diretorio)
    return evento


def reconstruir(eventos: list[dict]) -> dict[str, dict[int, float]]:
    """Ajustes em vigor por NE e mês, aplicando os eventos na ordem recebida."""

    vigentes: dict[str, dict[int, float]] = {}
    for e in eventos:
        if e["tipo"] == "refazer_tudo":
            vigentes.clear()
        elif e["tipo"] == "refazer_ne":
            vigentes.pop(e["ne_curta"], None)
        else:
            meses = vigentes.setdefault(e["ne_curta"], {})
            for mes, valor in e["valores"].items():
                if valor is None:
                    meses.pop(int(mes), None)
                else:
                    meses[int(mes)] = float(valor)
            if not meses:
                vigentes.pop(e["ne_curta"], None)
    return vigentes


def ajustes_vigentes(exercicio: int, diretorio: Path | None = None) -> dict[str, dict[int, float]]:
    return reconstruir(carregar_eventos(exercicio, diretorio))
