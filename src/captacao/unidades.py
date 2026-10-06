"""Cadastro editável de unidades (UGR) da Captação.

O código da UGR é um IDENTIFICADOR (texto): zeros à esquerda e alfanuméricos são
preservados. Unidades nunca são excluídas, só desativadas (demandas, representantes e
prorrogações apontam para elas). Toda alteração exige responsável e vai ao histórico.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from src.captacao import auditoria
from src.captacao.auditoria import ErroCadastro

TABELA = "unidade"
CAMPOS = ("ugr_codigo", "nome", "sigla")


def _limpar(dados: dict[str, Any]) -> dict[str, str | None]:
    return {c: (str(dados.get(c) or "").strip() or None) for c in CAMPOS}


def _validar(conexao: sqlite3.Connection, valores: dict[str, str | None], ignorar_id: int | None) -> None:
    erros = []
    codigo = valores["ugr_codigo"]
    if not codigo:
        erros.append("Informe o código da UGR.")
    elif conexao.execute(
        "SELECT id FROM unidade WHERE ugr_codigo = ? AND id IS NOT ?", (codigo, ignorar_id)
    ).fetchone():
        erros.append(f"Já existe uma unidade com o código {codigo!r}.")
    if not valores["nome"]:
        erros.append("Informe o nome da unidade.")
    if erros:
        raise ErroCadastro(erros)


def criar_unidade(conexao: sqlite3.Connection, dados: dict[str, Any], usuario: str | None) -> int:
    usuario = auditoria.exigir_usuario(usuario)
    valores = _limpar(dados)
    _validar(conexao, valores, None)
    with conexao:
        cursor = conexao.execute(
            "INSERT INTO unidade (ugr_codigo, nome, sigla, ativa) VALUES (?, ?, ?, 1)",
            (valores["ugr_codigo"], valores["nome"], valores["sigla"]),
        )
        unidade_id = int(cursor.lastrowid)
        auditoria.registrar(conexao, TABELA, unidade_id, "CRIAR", "ugr_codigo", None, valores["ugr_codigo"], usuario)
    return unidade_id


def editar_unidade(
    conexao: sqlite3.Connection, unidade_id: int, dados: dict[str, Any], usuario: str | None
) -> list[str]:
    """Altera código, nome e sigla (o `id` não muda). Devolve os campos alterados."""

    usuario = auditoria.exigir_usuario(usuario)
    atual = conexao.execute("SELECT * FROM unidade WHERE id = ?", (unidade_id,)).fetchone()
    if atual is None:
        raise ErroCadastro([f"Unidade {unidade_id} não encontrada."])
    valores = _limpar(dados)
    _validar(conexao, valores, unidade_id)
    mudancas = [(c, atual[c], valores[c]) for c in CAMPOS if atual[c] != valores[c]]
    if not mudancas:
        return []
    with conexao:
        conexao.execute(
            f"UPDATE unidade SET {', '.join(f'{c} = ?' for c, _, _ in mudancas)} WHERE id = ?",
            (*[depois for _, _, depois in mudancas], unidade_id),
        )
        for campo, antes, depois in mudancas:
            auditoria.registrar(conexao, TABELA, unidade_id, "EDITAR", campo, antes, depois, usuario)
    return [campo for campo, _, _ in mudancas]


def alterar_ativa(conexao: sqlite3.Connection, unidade_id: int, ativa: bool, usuario: str | None) -> bool:
    """Ativa ou desativa (nunca exclui). Devolve se houve mudança."""

    usuario = auditoria.exigir_usuario(usuario)
    atual = conexao.execute("SELECT ativa FROM unidade WHERE id = ?", (unidade_id,)).fetchone()
    if atual is None:
        raise ErroCadastro([f"Unidade {unidade_id} não encontrada."])
    if bool(atual["ativa"]) == ativa:
        return False
    with conexao:
        conexao.execute("UPDATE unidade SET ativa = ? WHERE id = ?", (int(ativa), unidade_id))
        auditoria.registrar(
            conexao, TABELA, unidade_id, "ATIVAR" if ativa else "DESATIVAR",
            "ativa", str(int(not ativa)), str(int(ativa)), usuario,
        )
    return True


def listar_unidades(conexao: sqlite3.Connection, apenas_ativas: bool = False) -> list[sqlite3.Row]:
    consulta = "SELECT * FROM unidade" + (" WHERE ativa = 1" if apenas_ativas else "") + " ORDER BY nome, ugr_codigo"
    return conexao.execute(consulta).fetchall()
