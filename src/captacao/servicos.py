"""Serviços transacionais da Captação de Demandas.

Toda mudança de situação passa por `_mudar_situacao`, que valida a transição
(`regras.TRANSICOES`) e grava `historico_situacao` na mesma transação da alteração da
demanda (AGENTS.md do projeto de origem). As regras de prazo e validação vêm de `regras.py`;
aqui só há acesso a banco.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from src.captacao import regras
from src.captacao.regras import ErroRegra

_CAMPOS_EDITAVEIS = (
    "tipo", "descricao", "codigo_catalogo", "quantidade", "unidade_fornecimento",
    "valor_unitario", "prioridade", "risco", "justificativa", "contribuicao",
    "depende_licitacao", "existe_arp", "recorrente", "solicita_analise_vinculo",
)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data(texto: str | None) -> date | None:
    return date.fromisoformat(texto) if texto else None


def _ciclo(conexao: sqlite3.Connection, ciclo_id: int) -> sqlite3.Row:
    ciclo = conexao.execute("SELECT * FROM ciclo WHERE id = ?", (ciclo_id,)).fetchone()
    if ciclo is None:
        raise ErroRegra([f"Ciclo {ciclo_id} não encontrado"])
    return ciclo


def _prorrogacao(conexao: sqlite3.Connection, ciclo_id: int, unidade_id: int) -> date | None:
    linha = conexao.execute(
        "SELECT novo_prazo FROM prorrogacao WHERE ciclo_id = ? AND unidade_id = ?",
        (ciclo_id, unidade_id),
    ).fetchone()
    return _data(linha["novo_prazo"]) if linha else None


def _gravar_vinculos(conexao: sqlite3.Connection, demanda_id: int, objetivos: list[int], metas: list[int]) -> None:
    conexao.execute("DELETE FROM demanda_objetivo_pdi WHERE demanda_id = ?", (demanda_id,))
    conexao.execute("DELETE FROM demanda_meta_pls WHERE demanda_id = ?", (demanda_id,))
    conexao.executemany(
        "INSERT INTO demanda_objetivo_pdi (demanda_id, objetivo_id) VALUES (?, ?)",
        [(demanda_id, objetivo) for objetivo in dict.fromkeys(objetivos)],
    )
    conexao.executemany(
        "INSERT INTO demanda_meta_pls (demanda_id, meta_id) VALUES (?, ?)",
        [(demanda_id, meta) for meta in dict.fromkeys(metas)],
    )


def _mudar_situacao(
    conexao: sqlite3.Connection,
    demanda_id: int,
    para: str,
    usuario: str | None,
    comentario: str | None = None,
    devolvida: bool | None = None,
) -> None:
    """Única porta de mudança de situação: valida a transição e grava o histórico. Não faz
    commit — quem chama controla a transação."""

    atual = conexao.execute("SELECT situacao FROM demanda WHERE id = ?", (demanda_id,)).fetchone()
    if atual is None:
        raise ErroRegra([f"Demanda {demanda_id} não encontrada"])
    de = atual["situacao"]
    if not regras.transicao_permitida(de, para):
        raise ErroRegra([f"Transição não permitida: {de} → {para}"])

    agora = _agora()
    colunas = "situacao = ?, atualizada_em = ?"
    parametros: list[Any] = [para, agora]
    if devolvida is not None:
        colunas += ", devolvida = ?"
        parametros.append(int(devolvida))
    conexao.execute(f"UPDATE demanda SET {colunas} WHERE id = ?", (*parametros, demanda_id))
    conexao.execute(
        "INSERT INTO historico_situacao (demanda_id, de, para, usuario, comentario, criado_em)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (demanda_id, de, para, usuario, comentario, agora),
    )


def criar_rascunho(
    conexao: sqlite3.Connection,
    ciclo_id: int,
    unidade_id: int,
    usuario: str | None,
    dados: dict[str, Any],
    hoje: date,
    origem: str = "MANUAL",
) -> int:
    """Cria uma demanda em RASCUNHO (pode estar incompleta — RN-02). Valida RN-05 (ciclo e
    prazo da unidade) e recalcula no servidor o valor total (RN-03) e a natureza sugerida
    (RN-04); valor total ou natureza vindos em `dados` são ignorados."""

    ciclo = _ciclo(conexao, ciclo_id)
    if not regras.pode_registrar(
        ciclo["fase"], _data(ciclo["abertura"]), _data(ciclo["encerramento"]),
        _prorrogacao(conexao, ciclo_id, unidade_id), hoje, bool(ciclo["permite_rascunho_antecipado"]),
    ):
        raise ErroRegra(["Fora do período de registro do ciclo para esta unidade"])

    valores = {campo: dados.get(campo) for campo in _CAMPOS_EDITAVEIS}
    # NOT NULL com padrão 0: ausente significa "não pediu análise" (os demais flags
    # Sim/Não aceitam NULL = não informado).
    valores["solicita_analise_vinculo"] = int(bool(valores["solicita_analise_vinculo"]))
    unitario = regras.para_decimal(valores["valor_unitario"])
    valores["valor_unitario"] = None if unitario is None else str(unitario)
    total = regras.calcular_valor_total(valores["quantidade"], unitario)
    agora = _agora()

    with conexao:
        cursor = conexao.execute(
            f"INSERT INTO demanda (ciclo_id, unidade_id, criada_por, {', '.join(_CAMPOS_EDITAVEIS)},"
            " valor_total, natureza_sugerida, origem, situacao, devolvida, criada_em, atualizada_em)"
            f" VALUES (?, ?, ?, {', '.join('?' * len(_CAMPOS_EDITAVEIS))}, ?, ?, ?, 'RASCUNHO', 0, ?, ?)",
            (
                ciclo_id, unidade_id, usuario, *[valores[c] for c in _CAMPOS_EDITAVEIS],
                None if total is None else str(total), regras.natureza_sugerida(valores["tipo"]),
                origem, agora, agora,
            ),
        )
        demanda_id = int(cursor.lastrowid)
        _gravar_vinculos(conexao, demanda_id, dados.get("objetivos_pdi") or [], dados.get("metas_pls") or [])
        conexao.execute(
            "INSERT INTO historico_situacao (demanda_id, de, para, usuario, comentario, criado_em)"
            " VALUES (?, NULL, 'RASCUNHO', ?, NULL, ?)",
            (demanda_id, usuario, agora),
        )
    return demanda_id


def enviar_demanda(conexao: sqlite3.Connection, demanda_id: int, usuario: str | None, hoje: date) -> None:
    """RASCUNHO → ENVIADA. Aplica RN-05/RN-06 (prazo) e RN-01/RN-02/RN-08 (pendências, nada
    parcial) e grava o histórico na mesma transação; se algo falhar, nada é gravado."""

    demanda = conexao.execute(
        "SELECT * FROM demanda WHERE id = ? AND excluida_em IS NULL", (demanda_id,)
    ).fetchone()
    if demanda is None:
        raise ErroRegra([f"Demanda {demanda_id} não encontrada"])
    if demanda["situacao"] != regras.SITUACAO_RASCUNHO:
        raise ErroRegra(["Só demandas em rascunho podem ser enviadas"])

    ciclo = _ciclo(conexao, demanda["ciclo_id"])
    if not regras.pode_enviar(
        ciclo["fase"], _data(ciclo["abertura"]), _data(ciclo["encerramento"]),
        _prorrogacao(conexao, demanda["ciclo_id"], demanda["unidade_id"]), hoje,
        devolvida=bool(demanda["devolvida"]), prazo_validacao=_data(ciclo["prazo_validacao"]),
    ):
        raise ErroRegra(["Fora do período de envio do ciclo para esta unidade"])

    completa = dict(demanda)
    completa["objetivos_pdi"] = [
        linha["objetivo_id"]
        for linha in conexao.execute("SELECT objetivo_id FROM demanda_objetivo_pdi WHERE demanda_id = ?", (demanda_id,))
    ]
    completa["metas_pls"] = [
        linha["meta_id"]
        for linha in conexao.execute("SELECT meta_id FROM demanda_meta_pls WHERE demanda_id = ?", (demanda_id,))
    ]
    pendencias = regras.validar_envio(completa)
    if pendencias:
        raise ErroRegra(pendencias)

    with conexao:
        # RN-03: o total é recalculado no envio, a partir de quantidade × valor unitário.
        total = regras.calcular_valor_total(demanda["quantidade"], demanda["valor_unitario"])
        conexao.execute(
            "UPDATE demanda SET valor_total = ?, natureza_sugerida = ?, enviada_em = ? WHERE id = ?",
            (str(total), regras.natureza_sugerida(demanda["tipo"]), _agora(), demanda_id),
        )
        _mudar_situacao(conexao, demanda_id, regras.SITUACAO_ENVIADA, usuario)
