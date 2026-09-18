"""
Orquestração de importação do módulo de TEDs: liga os leitores
(`src/teds_importacao_simec.py`, `src/teds_importacao_tesouro_gerencial.py`) ao schema
SQLite (`src/teds_schema.py`), registrando cada lote em `import_batch` e gravando as linhas
de forma idempotente (regra 10 do briefing).

Idempotência em duas camadas:
  * arquivo idêntico (mesmo hash SHA-256 já importado com sucesso para o mesmo tipo de
    relatório) -> importação inteira é um no-op, o lote antigo é reaproveitado;
  * linha a linha, via `INSERT ... ON CONFLICT ... DO UPDATE` pela chave natural de cada
    tabela -> reimportar um arquivo diferente que traga uma linha já conhecida atualiza
    aquela linha (e sua rastreabilidade para o lote mais recente) em vez de duplicá-la.

Nunca lê nem grava nada em `data/raw/`; o arquivo de origem permanece como o chamador
entregou (regra 1: nunca alterar arquivos importados).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.teds_alertas import sincronizar_alertas_multiplos_teds, sincronizar_alertas_nc_parcial
from src.teds_importacao_simec import (
    LinhaRejeitada,
    ler_doc_ne_simec,
    ler_doc_nc_simec,
    ler_doc_pf_simec,
    ler_execucao_anual_simec,
)
from src.teds_importacao_tesouro_gerencial import ler_execucao_tg
from src.teds_normalizacao import valor_para_texto

TIPO_EXECUCAO_ANUAL = "simec_execucao_anual"
TIPO_DOC_NE = "simec_doc_ne"
TIPO_DOC_NC = "simec_doc_nc"
TIPO_DOC_PF = "simec_doc_pf"
TIPO_EXECUCAO_TG = "tesouro_gerencial_execucao"


@dataclass
class ResultadoImportacaoLote:
    import_batch_id: int
    ja_importado: bool
    inseridos: int
    rejeitadas: list[LinhaRejeitada] = field(default_factory=list)


def _hash_bytes(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def _json_linha_origem(linha: dict[str, Any]) -> str:
    return json.dumps(linha, ensure_ascii=False, default=str)


def _lote_ja_importado(conn: sqlite3.Connection, tipo_relatorio: str, hash_arquivo: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM import_batch WHERE tipo_relatorio = ? AND hash_arquivo = ? AND status = 'ok'",
        (tipo_relatorio, hash_arquivo),
    ).fetchone()
    return row[0] if row else None


def _registrar_lote(
    conn: sqlite3.Connection,
    tipo_relatorio: str,
    nome_arquivo: str,
    hash_arquivo: str,
    quantidade_registros: int,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO import_batch
            (tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, quantidade_registros, status)
        VALUES (?, ?, ?, ?, ?, 'ok')
        """,
        (
            tipo_relatorio,
            nome_arquivo,
            hash_arquivo,
            datetime.now(timezone.utc).isoformat(),
            quantidade_registros,
        ),
    )
    return cursor.lastrowid


def _upsert_ted(conn: sqlite3.Connection, registro: dict[str, Any], batch_id: int) -> None:
    descricao = registro.get("descricao") or registro.get("descricao_ted")
    conn.execute(
        """
        INSERT INTO ted
            (chave_ted, ted, codigo_siafi, descricao, estado_atual, inicio_vigencia,
             fim_vigencia, ug_descentralizadora, import_batch_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chave_ted) DO UPDATE SET
            descricao = COALESCE(excluded.descricao, ted.descricao),
            estado_atual = COALESCE(excluded.estado_atual, ted.estado_atual),
            inicio_vigencia = COALESCE(excluded.inicio_vigencia, ted.inicio_vigencia),
            fim_vigencia = COALESCE(excluded.fim_vigencia, ted.fim_vigencia),
            ug_descentralizadora = COALESCE(excluded.ug_descentralizadora, ted.ug_descentralizadora),
            import_batch_id = excluded.import_batch_id
        """,
        (
            registro["chave_ted"],
            registro["ted"],
            registro["codigo_siafi"],
            descricao,
            registro.get("estado_atual"),
            registro.get("inicio_vigencia"),
            registro.get("fim_vigencia"),
            registro.get("ug_descentralizadora"),
            batch_id,
        ),
    )


def importar_execucao_anual(
    conn: sqlite3.Connection, df: pd.DataFrame, nome_arquivo: str, conteudo_bytes: bytes
) -> ResultadoImportacaoLote:
    hash_arquivo = _hash_bytes(conteudo_bytes)
    existente = _lote_ja_importado(conn, TIPO_EXECUCAO_ANUAL, hash_arquivo)
    if existente is not None:
        return ResultadoImportacaoLote(existente, ja_importado=True, inseridos=0)

    leitura = ler_execucao_anual_simec(df)
    batch_id = _registrar_lote(conn, TIPO_EXECUCAO_ANUAL, nome_arquivo, hash_arquivo, len(leitura.registros))

    for r in leitura.registros:
        _upsert_ted(conn, r, batch_id)
        conn.execute(
            """
            INSERT INTO execucao_anual
                (chave_ted, ano_emissao, total_nc_descentralizacao, total_nc_devolucao,
                 total_descentralizado, total_pf_repasse, total_pf_devolucao, total_repassado,
                 import_batch_id, linha_origem)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chave_ted, ano_emissao) DO UPDATE SET
                total_nc_descentralizacao = excluded.total_nc_descentralizacao,
                total_nc_devolucao = excluded.total_nc_devolucao,
                total_descentralizado = excluded.total_descentralizado,
                total_pf_repasse = excluded.total_pf_repasse,
                total_pf_devolucao = excluded.total_pf_devolucao,
                total_repassado = excluded.total_repassado,
                import_batch_id = excluded.import_batch_id,
                linha_origem = excluded.linha_origem
            """,
            (
                r["chave_ted"],
                r["ano_emissao"],
                valor_para_texto(r["total_nc_descentralizacao"]),
                valor_para_texto(r["total_nc_devolucao"]),
                valor_para_texto(r["total_descentralizado"]),
                valor_para_texto(r["total_pf_repasse"]),
                valor_para_texto(r["total_pf_devolucao"]),
                valor_para_texto(r["total_repassado"]),
                batch_id,
                _json_linha_origem(r["linha_origem"]),
            ),
        )
    conn.commit()
    return ResultadoImportacaoLote(batch_id, False, len(leitura.registros), leitura.rejeitadas)


def importar_doc_ne(
    conn: sqlite3.Connection, df: pd.DataFrame, nome_arquivo: str, conteudo_bytes: bytes
) -> ResultadoImportacaoLote:
    hash_arquivo = _hash_bytes(conteudo_bytes)
    existente = _lote_ja_importado(conn, TIPO_DOC_NE, hash_arquivo)
    if existente is not None:
        return ResultadoImportacaoLote(existente, ja_importado=True, inseridos=0)

    leitura = ler_doc_ne_simec(df)
    batch_id = _registrar_lote(conn, TIPO_DOC_NE, nome_arquivo, hash_arquivo, len(leitura.registros))

    for r in leitura.registros:
        _upsert_ted(conn, r, batch_id)
        conn.execute(
            """
            INSERT INTO vinculo_ne
                (chave_ted, chave_empenho, ug_emitente, gestao_emitente, numero_ne, valor_ne,
                 descricao_ne, status_validacao, import_batch_id, linha_origem)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'ok', ?, ?)
            ON CONFLICT(chave_ted, chave_empenho) DO UPDATE SET
                valor_ne = excluded.valor_ne,
                descricao_ne = excluded.descricao_ne,
                import_batch_id = excluded.import_batch_id,
                linha_origem = excluded.linha_origem
            """,
            (
                r["chave_ted"],
                r["chave_empenho"],
                r["ug_emitente"],
                r["gestao_emitente"],
                r["numero_ne"],
                valor_para_texto(r["valor_ne"]),
                r["descricao_ne"],
                batch_id,
                _json_linha_origem(r["linha_origem"]),
            ),
        )
    conn.commit()
    sincronizar_alertas_multiplos_teds(conn)
    return ResultadoImportacaoLote(batch_id, False, len(leitura.registros), leitura.rejeitadas)


def importar_doc_nc(
    conn: sqlite3.Connection, df: pd.DataFrame, nome_arquivo: str, conteudo_bytes: bytes
) -> ResultadoImportacaoLote:
    """DOC NC é gravado em dois níveis (ver docstring de `ler_doc_nc_simec` e do DDL de
    `documento_nc`/`documento_nc_linha` em `src/teds_schema.py`): `documento_nc_linha`
    preserva cada linha da planilha (idempotente pela chave `chave_nc_linha`, que usa o hash
    do próprio arquivo como identificador de lote — reimportar o mesmo arquivo produz as
    mesmas chaves de linha) e `documento_nc` guarda o agregado por documento, recalculado do
    zero a cada importação a partir de TODAS as linhas do arquivo (a extração é sempre
    completa, nunca incremental)."""

    hash_arquivo = _hash_bytes(conteudo_bytes)
    existente = _lote_ja_importado(conn, TIPO_DOC_NC, hash_arquivo)
    if existente is not None:
        return ResultadoImportacaoLote(existente, ja_importado=True, inseridos=0)

    leitura = ler_doc_nc_simec(df, identificador_lote=hash_arquivo)
    batch_id = _registrar_lote(conn, TIPO_DOC_NC, nome_arquivo, hash_arquivo, len(leitura.registros))

    for r in leitura.registros:
        conn.execute(
            """
            INSERT INTO documento_nc_linha
                (chave_nc_linha, chave_nc_documento, chave_ted, ted, codigo_siafi, numero_nc,
                 ug_emitente, data_emissao, operacao, valor_original, valor_assinado,
                 status_relacionamento, avisos, import_batch_id, linha_origem)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chave_nc_linha) DO UPDATE SET
                chave_nc_documento = excluded.chave_nc_documento,
                chave_ted = excluded.chave_ted,
                ted = excluded.ted,
                codigo_siafi = excluded.codigo_siafi,
                numero_nc = excluded.numero_nc,
                ug_emitente = excluded.ug_emitente,
                data_emissao = excluded.data_emissao,
                operacao = excluded.operacao,
                valor_original = excluded.valor_original,
                valor_assinado = excluded.valor_assinado,
                status_relacionamento = excluded.status_relacionamento,
                avisos = excluded.avisos,
                import_batch_id = excluded.import_batch_id,
                linha_origem = excluded.linha_origem
            """,
            (
                r["chave_nc_linha"],
                r["chave_nc_documento"],
                r["chave_ted"],
                r["ted"],
                r["codigo_siafi"],
                r["numero_nc"],
                r["ug_emitente"],
                r["data_emissao"],
                r["operacao"],
                valor_para_texto(r["valor_original"]),
                valor_para_texto(r["valor_assinado"]),
                r["status_relacionamento"],
                json.dumps(r["avisos"], ensure_ascii=False),
                batch_id,
                _json_linha_origem(r["linha_origem"]),
            ),
        )

    for d in leitura.documentos:
        conn.execute(
            """
            INSERT INTO documento_nc
                (chave_nc_documento, chave_ted, ted, codigo_siafi, numero_nc, ug_emitente,
                 data_emissao, operacao, valor_original_total, valor_assinado_total,
                 quantidade_linhas, status_relacionamento, import_batch_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chave_nc_documento) DO UPDATE SET
                chave_ted = excluded.chave_ted,
                ted = excluded.ted,
                codigo_siafi = excluded.codigo_siafi,
                numero_nc = excluded.numero_nc,
                ug_emitente = excluded.ug_emitente,
                data_emissao = excluded.data_emissao,
                operacao = excluded.operacao,
                valor_original_total = excluded.valor_original_total,
                valor_assinado_total = excluded.valor_assinado_total,
                quantidade_linhas = excluded.quantidade_linhas,
                status_relacionamento = excluded.status_relacionamento,
                import_batch_id = excluded.import_batch_id
            """,
            (
                d["chave_nc_documento"],
                d["chave_ted"],
                d["ted"],
                d["codigo_siafi"],
                d["numero_nc"],
                d["ug_emitente"],
                d["data_emissao"],
                d["operacao"],
                valor_para_texto(d["valor_original_total"]),
                valor_para_texto(d["valor_assinado_total"]),
                d["quantidade_linhas"],
                d["status_relacionamento"],
                batch_id,
            ),
        )
    conn.commit()
    sincronizar_alertas_nc_parcial(conn)
    return ResultadoImportacaoLote(batch_id, False, len(leitura.registros), leitura.rejeitadas)


def importar_doc_pf(
    conn: sqlite3.Connection, df: pd.DataFrame, nome_arquivo: str, conteudo_bytes: bytes
) -> ResultadoImportacaoLote:
    hash_arquivo = _hash_bytes(conteudo_bytes)
    existente = _lote_ja_importado(conn, TIPO_DOC_PF, hash_arquivo)
    if existente is not None:
        return ResultadoImportacaoLote(existente, ja_importado=True, inseridos=0)

    leitura = ler_doc_pf_simec(df)
    batch_id = _registrar_lote(conn, TIPO_DOC_PF, nome_arquivo, hash_arquivo, len(leitura.registros))

    for r in leitura.registros:
        conn.execute(
            """
            INSERT INTO documento_pf
                (chave_ted, ug_emitente, numero_pf, data_emissao, operacao, valor_original,
                 valor_assinado, import_batch_id, linha_origem)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ug_emitente, numero_pf) DO UPDATE SET
                chave_ted = excluded.chave_ted,
                data_emissao = excluded.data_emissao,
                operacao = excluded.operacao,
                valor_original = excluded.valor_original,
                valor_assinado = excluded.valor_assinado,
                import_batch_id = excluded.import_batch_id,
                linha_origem = excluded.linha_origem
            """,
            (
                r["chave_ted"],
                r["ug_emitente"],
                r["numero_pf"],
                r["data_emissao"],
                r["operacao"],
                valor_para_texto(r["valor_original"]),
                valor_para_texto(r["valor_assinado"]),
                batch_id,
                _json_linha_origem(r["linha_origem"]),
            ),
        )
    conn.commit()
    return ResultadoImportacaoLote(batch_id, False, len(leitura.registros), leitura.rejeitadas)


def importar_execucao_tg(
    conn: sqlite3.Connection, df: pd.DataFrame, nome_arquivo: str, conteudo_bytes: bytes
) -> ResultadoImportacaoLote:
    hash_arquivo = _hash_bytes(conteudo_bytes)
    existente = _lote_ja_importado(conn, TIPO_EXECUCAO_TG, hash_arquivo)
    if existente is not None:
        return ResultadoImportacaoLote(existente, ja_importado=True, inseridos=0)

    leitura = ler_execucao_tg(df)
    batch_id = _registrar_lote(conn, TIPO_EXECUCAO_TG, nome_arquivo, hash_arquivo, len(leitura.registros))

    for r in leitura.registros:
        conn.execute(
            """
            INSERT INTO execucao_tg
                (numero_completo_ne, favorecido, descricao, empenhado, liquidado, pago,
                 documento_habil, documento_contabil, ano_competencia, mes_competencia,
                 valor_competencia, import_batch_id, linha_origem)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(numero_completo_ne, documento_habil, documento_contabil, ano_competencia, mes_competencia)
            DO UPDATE SET
                favorecido = excluded.favorecido,
                descricao = excluded.descricao,
                empenhado = excluded.empenhado,
                liquidado = excluded.liquidado,
                pago = excluded.pago,
                valor_competencia = excluded.valor_competencia,
                import_batch_id = excluded.import_batch_id,
                linha_origem = excluded.linha_origem
            """,
            (
                r["numero_completo_ne"],
                r["favorecido"],
                r["descricao"],
                valor_para_texto(r["empenhado"]) if r["empenhado"] is not None else None,
                valor_para_texto(r["liquidado"]) if r["liquidado"] is not None else None,
                valor_para_texto(r["pago"]) if r["pago"] is not None else None,
                r["documento_habil"],
                r["documento_contabil"],
                r["ano_competencia"],
                r["mes_competencia"],
                valor_para_texto(r["valor_competencia"]) if r["valor_competencia"] is not None else None,
                batch_id,
                _json_linha_origem(r["linha_origem"]),
            ),
        )
    conn.commit()
    return ResultadoImportacaoLote(batch_id, False, len(leitura.registros), leitura.rejeitadas)


# --------------------------------------------------------------------------------------
# Conveniência: importar direto de um arquivo em disco (nunca o modifica — só lê).
# --------------------------------------------------------------------------------------

_IMPORTADORES_POR_TIPO = {
    TIPO_EXECUCAO_ANUAL: importar_execucao_anual,
    TIPO_DOC_NE: importar_doc_ne,
    TIPO_DOC_NC: importar_doc_nc,
    TIPO_DOC_PF: importar_doc_pf,
    TIPO_EXECUCAO_TG: importar_execucao_tg,
}


def importar_arquivo(conn: sqlite3.Connection, tipo_relatorio: str, caminho: str | Path) -> ResultadoImportacaoLote:
    importador = _IMPORTADORES_POR_TIPO.get(tipo_relatorio)
    if importador is None:
        raise ValueError(f"Tipo de relatório desconhecido: {tipo_relatorio!r}")

    caminho = Path(caminho)
    conteudo = caminho.read_bytes()
    df = pd.read_excel(caminho)
    return importador(conn, df, caminho.name, conteudo)
