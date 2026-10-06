"""Trilha de auditoria compartilhada de unidades, ciclos e prorrogações.

Cada alteração grava uma linha em `historico_cadastro` com o valor antes e depois, o
responsável e o instante (UTC). O BudgetLab não tem login: o responsável é o nome
informado na interface e é OBRIGATÓRIO para qualquer alteração.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


class ErroCadastro(Exception):
    """Violação de regra de cadastro; `erros` lista cada motivo. Nada foi gravado."""

    def __init__(self, erros: list[str]):
        self.erros = list(erros)
        super().__init__("; ".join(self.erros))


def agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def exigir_usuario(usuario: str | None) -> str:
    usuario = (usuario or "").strip()
    if not usuario:
        raise ErroCadastro(["Informe quem está fazendo a alteração (fica no histórico)."])
    return usuario


def registrar(
    conexao: sqlite3.Connection,
    tabela: str,
    item_id: int,
    acao: str,
    campo: str | None,
    antes: object,
    depois: object,
    usuario: str | None,
) -> None:
    """Uma linha de histórico. Não faz commit: quem chama controla a transação."""

    conexao.execute(
        "INSERT INTO historico_cadastro (tabela, item_id, acao, campo, antes, depois, usuario, criado_em)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (tabela, item_id, acao, campo, antes, depois, usuario, agora()),
    )


def historico(conexao: sqlite3.Connection, tabela: str, item_id: int) -> list[sqlite3.Row]:
    """Histórico do item, do mais antigo ao mais recente."""

    return conexao.execute(
        "SELECT * FROM historico_cadastro WHERE tabela = ? AND item_id = ? ORDER BY id", (tabela, item_id)
    ).fetchall()
