"""
Decisões sobre as sugestões de conciliação: confirmar ou rejeitar (11/10/2026).

Camada: regra pura + persistência por eventos. As sugestões da conciliação (deslocamento de competência, cancelamento
provável, ambíguo, nota ainda não liquidada) eram só visuais; aqui o usuário registra o que decidiu, com responsável e
justificativa. Padrão de `src/ajustes_dotacao_emendas.py`:

  * Um arquivo JSON por ação em `data/conciliacao_decisoes/` (PERSISTÊNCIA autorizada pelo usuário em 11/10/2026; fora do
    Git), gravação atômica (tmp + replace), `versao_schema` 1. Evento nunca é alterado nem apagado; desfazer ACRESCENTA
    um evento. Arquivo ilegível levanta `ErroDecisao` — nunca vira "sem decisões" em silêncio.
  * A decisão vale para (contrato, competência) e leva a ASSINATURA do que foi sugerido (`assinatura_mes`: classe, NEs,
    notas e valores). Se os dados mudam e a assinatura difere, a decisão fica OBSOLETA e é ignorada: o mês volta a
    aparecer como pendente.
  * Ambíguo pode ser CONFIRMADO desde que o usuário indique a(s) nota(s) cancelada(s) (`notas_desconsideradas`): a
    escolha é dele, registrada e desfazível; o sistema nunca desempata sozinho.
  * Confirmada = o mês deixa de ser pendência (classe "confirmada"); rejeitada = continua pendente (classe "rejeitada").
    Ambíguo só pode ser rejeitado: o sistema não escolhe qual nota (nem o usuário pode por aqui).

Contrato público:
    ErroDecisao
    DECISOES, CLASSES_COM_SUGESTAO
    assinatura_mes(classe, nes, notas, valor_notas, valor_relatorio) -> str
    registrar_decisao(*, contrato, ano_mes, classe, assinatura, decisao, justificativa, responsavel, diretorio=None,
                      notas_desconsideradas=None) -> dict
    desfazer_decisao(*, decisao_id, motivo, responsavel, diretorio=None) -> dict
    carregar_eventos(diretorio=None) -> list[dict]
    reconstruir_decisoes(eventos) -> {(contrato, ano_mes): Decisao}
    aplicar_decisao(classe, decisao, assinatura) -> classe
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DIRETORIO_DECISOES = Path("data/conciliacao_decisoes")
VERSAO_SCHEMA = 1
DECISOES = ("confirmada", "rejeitada")
#: classes que recebem decisão (as sugestões do sistema)
CLASSES_COM_SUGESTAO = ("deslocamento", "cancelamento", "ambiguo", "nota_pendente")
MIN_JUSTIFICATIVA = 10


class ErroDecisao(ValueError):
    """Decisão inválida, evento inexistente ou arquivo de decisões ilegível."""


@dataclass(frozen=True)
class Decisao:
    id: str
    contrato: str
    ano_mes: int
    classe: str
    assinatura: str
    decisao: str
    justificativa: str
    responsavel: str
    registrado_em: str
    #: só no ambíguo CONFIRMADO: as notas que o usuário indicou como canceladas, (nota, ne, valor) — o sistema não escolhe
    notas_desconsideradas: tuple = ()


def assinatura_mes(classe: str, nes, notas, valor_notas: float | None, valor_relatorio: float | None) -> str:
    """Identidade do que foi sugerido para o mês: muda se a classe, as NEs, as notas ou algum valor mudar (nulo ≠ valor)."""

    base = json.dumps(
        [classe, sorted(nes), sorted(notas), None if valor_notas is None else round(valor_notas, 2),
         None if valor_relatorio is None else round(valor_relatorio, 2)],
        ensure_ascii=False,
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _pasta(diretorio: Path | None) -> Path:
    return Path(diretorio if diretorio is not None else DIRETORIO_DECISOES)


def _gravar(evento: dict, diretorio: Path | None) -> None:
    pasta = _pasta(diretorio)
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = evento["registrado_em"].replace(":", "").replace("-", "").replace(".", "")
    caminho = pasta / f"{carimbo}_{evento['id'][:8]}.json"
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text(json.dumps(evento, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(temporario, caminho)


def _agora() -> str:
    """Com microssegundos: duas ações no mesmo segundo precisam manter a ordem (a mais recente vale)."""
    return datetime.now().isoformat()


def carregar_eventos(diretorio: Path | None = None) -> list[dict]:
    pasta = _pasta(diretorio)
    if not pasta.exists():
        return []
    eventos = []
    for caminho in sorted(pasta.glob("*.json")):
        try:
            evento = json.loads(caminho.read_text(encoding="utf-8"))
            if evento["versao_schema"] != VERSAO_SCHEMA or evento["tipo"] not in ("decisao", "desfazer"):
                raise KeyError("tipo/versão")
        except (OSError, ValueError, KeyError, TypeError) as erro:
            raise ErroDecisao(f"Não foi possível ler {caminho}: {erro}") from erro
        eventos.append(evento)
    return sorted(eventos, key=lambda e: (e["registrado_em"], e["id"]))


def registrar_decisao(
    *, contrato: str, ano_mes: int, classe: str, assinatura: str, decisao: str, justificativa: str, responsavel: str,
    diretorio: Path | None = None, notas_desconsideradas=None,
) -> dict:
    if classe not in CLASSES_COM_SUGESTAO:
        raise ErroDecisao(f"Só sugestões recebem decisão ({', '.join(CLASSES_COM_SUGESTAO)}); este mês é '{classe}'.")
    if decisao not in DECISOES:
        raise ErroDecisao(f"Decisão inválida: {decisao!r}. Use {' ou '.join(DECISOES)}.")
    notas = [(str(n), str(ne), round(float(v), 2)) for n, ne, v in (notas_desconsideradas or [])]
    if classe == "ambiguo" and decisao == "confirmada":
        if not notas:
            raise ErroDecisao(
                "Mês ambíguo: mais de uma nota fecha o valor e o sistema não escolhe qual. Para confirmar, indique a(s) "
                "nota(s) que você sabe estar(em) cancelada(s)/repetida(s)."
            )
    elif notas:
        raise ErroDecisao("A escolha de notas só vale ao confirmar um mês ambíguo.")
    if len(justificativa.strip()) < MIN_JUSTIFICATIVA:
        raise ErroDecisao(f"Informe a justificativa (mínimo de {MIN_JUSTIFICATIVA} caracteres).")
    if not responsavel.strip():
        raise ErroDecisao("Informe o responsável pela decisão.")
    evento = {
        "versao_schema": VERSAO_SCHEMA, "tipo": "decisao", "id": uuid.uuid4().hex, "contrato": str(contrato),
        "ano_mes": int(ano_mes), "classe": classe, "assinatura": assinatura, "decisao": decisao,
        "justificativa": justificativa.strip(), "responsavel": responsavel.strip(), "registrado_em": _agora(),
        "notas_desconsideradas": [list(n) for n in notas],
    }
    _gravar(evento, diretorio)
    return evento


def desfazer_decisao(*, decisao_id: str, motivo: str, responsavel: str, diretorio: Path | None = None) -> dict:
    ativas = {d.id for d in reconstruir_decisoes(carregar_eventos(diretorio)).values()}
    if decisao_id not in ativas:
        raise ErroDecisao("Esta decisão não existe ou já foi desfeita/substituída.")
    if len(motivo.strip()) < MIN_JUSTIFICATIVA:
        raise ErroDecisao(f"Informe o motivo (mínimo de {MIN_JUSTIFICATIVA} caracteres).")
    if not responsavel.strip():
        raise ErroDecisao("Informe o responsável.")
    evento = {
        "versao_schema": VERSAO_SCHEMA, "tipo": "desfazer", "id": uuid.uuid4().hex, "decisao_id": decisao_id,
        "motivo": motivo.strip(), "responsavel": responsavel.strip(), "registrado_em": _agora(),
    }
    _gravar(evento, diretorio)
    return evento


def reconstruir_decisoes(eventos: list[dict]) -> dict[tuple[str, int], Decisao]:
    """Decisões em vigor por (contrato, competência): a última de cada mês que não foi desfeita."""

    desfeitas = {e["decisao_id"] for e in eventos if e["tipo"] == "desfazer"}
    vigentes: dict[tuple[str, int], Decisao] = {}
    for e in eventos:  # em ordem: a mais recente de cada mês substitui a anterior
        if e["tipo"] != "decisao" or e["id"] in desfeitas:
            continue
        vigentes[(e["contrato"], int(e["ano_mes"]))] = Decisao(
            e["id"], e["contrato"], int(e["ano_mes"]), e["classe"], e["assinatura"], e["decisao"], e["justificativa"],
            e["responsavel"], e["registrado_em"],
            tuple((str(n), str(ne), float(v)) for n, ne, v in e.get("notas_desconsideradas", [])),
        )
    return vigentes


def aplicar_decisao(classe: str, decisao: Decisao | None, assinatura: str) -> str:
    """A classe do mês depois da decisão: "confirmada" ou "rejeitada" se há decisão ATIVA (mesma assinatura) para uma
    sugestão; senão a classe original (sem decisão, obsoleta ou classe que não é sugestão)."""

    if decisao is None or classe not in CLASSES_COM_SUGESTAO or decisao.assinatura != assinatura:
        return classe
    return decisao.decisao
