"""
Trilha de auditoria do módulo de TEDs (briefing, seção 16).

Registra QUEM fez o quê, QUANDO, com que valor anterior e novo e por qual motivo, para as ações
humanas sobre alertas e vínculos de NE. É append-only: a tabela `auditoria` tem gatilhos que
abortam qualquer `UPDATE` ou `DELETE` (ver `src/teds_schema.py`), então nem uma correção
posterior consegue reescrever a história — uma correção é um novo registro.

Não há conceito de usuário autenticado no projeto: `usuario` é o responsável informado na tela
(texto livre, o mesmo já gravado em `alerta.responsavel`), ou "não informado" quando a ação não
o trouxe. Não presume identidade além disso.

Camada: sem Streamlit e sem regra de negócio de alerta — só grava e lê. Quem chama decide o
momento do `commit` (por padrão NÃO comita, para a auditoria entrar na MESMA transação da
alteração que ela descreve: ou os dois persistem, ou nenhum).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

ACAO_ALERTA_STATUS_ALTERADO = "alerta_status_alterado"
ACAO_VINCULO_NE_DECIDIDO = "vinculo_ne_decidido"
ACAO_LOTE_REVERTIDO = "lote_revertido"
ACAO_ALERTAS_REAVALIADOS = "alertas_reavaliados"

ENTIDADE_ALERTA = "alerta"
ENTIDADE_VINCULO_NE = "vinculo_ne"
ENTIDADE_IMPORT_BATCH = "import_batch"

USUARIO_NAO_INFORMADO = "não informado"


@dataclass(frozen=True)
class RegistroAuditoria:
    id: int
    data_hora: str
    usuario: str
    acao: str
    entidade: str
    entidade_id: str
    valor_anterior: dict[str, Any] | None
    valor_novo: dict[str, Any] | None
    motivo: str | None
    origem: str


def _json(valor: dict[str, Any] | None) -> str | None:
    if valor is None:
        return None
    return json.dumps(valor, ensure_ascii=False, sort_keys=True)


def registrar_auditoria(
    conn: sqlite3.Connection,
    *,
    acao: str,
    entidade: str,
    entidade_id: str | int,
    valor_anterior: dict[str, Any] | None,
    valor_novo: dict[str, Any] | None,
    usuario: str | None = None,
    motivo: str | None = None,
    origem: str = "interface",
    commit: bool = False,
) -> int:
    """Insere um registro e devolve o id. `commit=False` (padrão) deixa a transação aberta para
    o chamador — use isso dentro da transação da alteração auditada."""

    cursor = conn.execute(
        """
        INSERT INTO auditoria
            (data_hora, usuario, acao, entidade, entidade_id, valor_anterior, valor_novo, motivo, origem)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            (usuario or "").strip() or USUARIO_NAO_INFORMADO,
            acao,
            entidade,
            str(entidade_id),
            _json(valor_anterior),
            _json(valor_novo),
            (motivo or "").strip() or None,
            origem,
        ),
    )
    if commit:
        conn.commit()
    return int(cursor.lastrowid)


def _desserializar(texto: str | None) -> dict[str, Any] | None:
    return None if texto is None else json.loads(texto)


def historico_auditoria(
    conn: sqlite3.Connection, entidade: str, entidade_id: str | int
) -> list[RegistroAuditoria]:
    """Registros de uma entidade, do mais antigo ao mais recente."""

    linhas = conn.execute(
        """
        SELECT id, data_hora, usuario, acao, entidade, entidade_id, valor_anterior, valor_novo,
               motivo, origem
        FROM auditoria WHERE entidade = ? AND entidade_id = ? ORDER BY id
        """,
        (entidade, str(entidade_id)),
    ).fetchall()
    return [
        RegistroAuditoria(
            id, data_hora, usuario, acao, ent, ent_id,
            _desserializar(anterior), _desserializar(novo), motivo, origem,
        )
        for id, data_hora, usuario, acao, ent, ent_id, anterior, novo, motivo, origem in linhas
    ]
