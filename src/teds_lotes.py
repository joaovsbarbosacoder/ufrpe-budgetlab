"""
Orquestração de importação do módulo de TEDs: liga os leitores
(`src/teds_importacao_simec.py`; e, para o Tesouro Gerencial,
`src/teds_importacao_tesouro_gerencial.py`, que deriva da Execução Mensal em vez de ler arquivo) ao schema
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
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from src.importacao_execucao_mensal import (
    DIRETORIO_DADOS_BRUTOS_PADRAO,
    DIRETORIO_MANIFESTOS_PADRAO,
    Manifesto as ManifestoExecucaoMensal,
    carregar_atual as carregar_execucao_mensal_atual,
)
from src.teds_alertas import (
    registrar_alertas_ted_sem_siafi,
    sincronizar_alertas_rodape,
    sincronizar_alertas_execucao_tg,
    sincronizar_alertas_cadastrais,
    sincronizar_alertas_conciliacao_simec,
    sincronizar_alertas_multiplos_teds,
    sincronizar_alertas_nc_parcial,
)
from src.teds_importacao_simec import (
    LinhaRejeitada,
    ler_doc_ne_simec,
    ler_doc_nc_simec,
    ler_doc_pf_simec,
    ler_execucao_anual_simec,
)
from src.teds_importacao_tesouro_gerencial import montar_execucao_tg
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


@dataclass(frozen=True)
class ResumoControle:
    """Total de controle de um lote (regra 6.2 do briefing): quantidade de linhas lidas,
    rejeitadas e aceitas com aviso, mais a soma bruta/positiva/negativa/líquida quando o
    relatório tem um valor por linha com sinal bem definido.

    As somas ficam `None` para Execução Anual e Execução do Tesouro Gerencial: essas duas
    bases trazem várias colunas de valor por linha (ex.: os 6 totais por TED da Execução
    Anual, ou empenhado/liquidado/pago por NE × mês) sem uma leitura única de "valor da linha" — forçar uma soma ali exigiria escolher
    arbitrariamente qual coluna vale como "o" valor da linha, o que não está no briefing nem
    foi confirmado contra as extrações reais revisadas.

    O total do rodapé e a diferença contra ele (também parte da regra 6.2) não ficam aqui: são
    calculados por `comparar_rodape` e gravados por `_gravar_rodape` (colunas do lote).
    """

    quantidade_linhas_lidas: int
    quantidade_rejeitadas: int
    quantidade_com_aviso: int
    soma_bruta: Decimal | None = None
    soma_positiva: Decimal | None = None
    soma_negativa: Decimal | None = None
    soma_liquida: Decimal | None = None


def _resumo_controle(
    *,
    quantidade_linhas_lidas: int,
    registros: list[dict[str, Any]],
    rejeitadas: list[LinhaRejeitada],
    campo_valor: str | None,
    campo_operacao: str | None = None,
    campo_avisos: str | None = None,
) -> ResumoControle:
    """`campo_valor=None` quando o relatório não sustenta soma bruta/positiva/negativa/líquida
    (ver `ResumoControle`). `campo_operacao=None` trata todo registro como positivo (relatórios
    sem sinal de operação, ex.: DOC NE)."""

    quantidade_com_aviso = sum(1 for r in registros if r.get(campo_avisos)) if campo_avisos else 0
    if campo_valor is None:
        return ResumoControle(quantidade_linhas_lidas, len(rejeitadas), quantidade_com_aviso)

    bruta = Decimal("0")
    positiva = Decimal("0")
    negativa = Decimal("0")
    liquida = Decimal("0")
    for registro in registros:
        valor: Decimal = registro[campo_valor]
        sinal = 1 if campo_operacao is None or registro[campo_operacao] == "+" else -1
        bruta += valor
        liquida += valor * sinal
        if sinal > 0:
            positiva += valor
        else:
            negativa += valor

    return ResumoControle(
        quantidade_linhas_lidas, len(rejeitadas), quantidade_com_aviso, bruta, positiva, negativa, liquida
    )


@dataclass(frozen=True)
class ComparacaoRodape:
    """Um campo de valor: total impresso no rodapé × soma calculada das linhas aceitas."""

    campo: str
    rodape: Decimal
    calculado: Decimal

    @property
    def diferenca(self) -> Decimal:
        return self.rodape - self.calculado


#: relatório -> {campo do rodapé: campo do registro somado}. DOC NC e DOC PF comparam a soma
#: BRUTA (`valor_original`, sempre positivo), nunca a líquida: o rodapé do SIMEC é absoluto —
#: confirmado nas extrações reais de 17/09/2026 (NC: positivas + negativas = rodapé).
_CAMPOS_RODAPE_POR_RELATORIO: dict[str, dict[str, str]] = {
    TIPO_EXECUCAO_ANUAL: {
        "total_nc_descentralizacao": "total_nc_descentralizacao",
        "total_nc_devolucao": "total_nc_devolucao",
        "total_descentralizado": "total_descentralizado",
        "total_pf_repasse": "total_pf_repasse",
        "total_pf_devolucao": "total_pf_devolucao",
        "total_repassado": "total_repassado",
    },
    TIPO_DOC_NE: {"valor_ne": "valor_ne"},
    TIPO_DOC_NC: {"valor_nc": "valor_original"},
    TIPO_DOC_PF: {"valor_pf": "valor_original"},
}


def comparar_rodape(tipo_relatorio: str, leitura: Any) -> list[ComparacaoRodape] | None:
    """Compara o rodapé lido com a soma das linhas aceitas. `None` = o arquivo não trazia rodapé
    (não é erro: só não há o que conferir). Pura — a página de Importações a usa na validação,
    antes de gravar, e os importadores a usam ao registrar o lote."""

    rodape = getattr(leitura, "rodape", None)
    campos = _CAMPOS_RODAPE_POR_RELATORIO.get(tipo_relatorio)
    if not rodape or campos is None:
        return None
    return [
        ComparacaoRodape(
            campo,
            valor_rodape,
            sum((r[campos[campo]] for r in leitura.registros), start=Decimal("0")),
        )
        for campo, valor_rodape in rodape.items()
        if campo in campos
    ] or None


def _gravar_rodape(conn: sqlite3.Connection, batch_id: int, comparacoes: list[ComparacaoRodape] | None) -> None:
    """Guarda no lote o total do rodapé e a diferença (regra 6.2). Sem rodapé, fica NULL."""

    if not comparacoes:
        return
    maior = max((abs(c.diferenca) for c in comparacoes), default=Decimal("0"))
    total = valor_para_texto(comparacoes[0].rodape) if len(comparacoes) == 1 else None
    detalhe = [
        {
            "campo": c.campo,
            "rodape": valor_para_texto(c.rodape),
            "calculado": valor_para_texto(c.calculado),
            "diferenca": valor_para_texto(c.diferenca),
        }
        for c in comparacoes
    ]
    conn.execute(
        "UPDATE import_batch SET total_rodape = ?, diferenca_rodape = ?, detalhe_rodape = ? WHERE id = ?",
        (total, valor_para_texto(maior), json.dumps(detalhe, ensure_ascii=False), batch_id),
    )


def _registrar_lote(
    conn: sqlite3.Connection,
    tipo_relatorio: str,
    nome_arquivo: str,
    hash_arquivo: str,
    quantidade_registros: int,
    resumo: ResumoControle | None = None,
) -> int:
    resumo = resumo or ResumoControle(quantidade_linhas_lidas=quantidade_registros, quantidade_rejeitadas=0, quantidade_com_aviso=0)
    cursor = conn.execute(
        """
        INSERT INTO import_batch
            (tipo_relatorio, nome_arquivo, hash_arquivo, data_importacao, quantidade_registros, status,
             quantidade_linhas_lidas, quantidade_rejeitadas, quantidade_com_aviso,
             soma_bruta, soma_positiva, soma_negativa, soma_liquida, versionado)
        VALUES (?, ?, ?, ?, ?, 'ok', ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            tipo_relatorio,
            nome_arquivo,
            hash_arquivo,
            datetime.now(timezone.utc).isoformat(),
            quantidade_registros,
            resumo.quantidade_linhas_lidas,
            resumo.quantidade_rejeitadas,
            resumo.quantidade_com_aviso,
            valor_para_texto(resumo.soma_bruta) if resumo.soma_bruta is not None else None,
            valor_para_texto(resumo.soma_positiva) if resumo.soma_positiva is not None else None,
            valor_para_texto(resumo.soma_negativa) if resumo.soma_negativa is not None else None,
            valor_para_texto(resumo.soma_liquida) if resumo.soma_liquida is not None else None,
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
    resumo = _resumo_controle(
        quantidade_linhas_lidas=len(df), registros=leitura.registros, rejeitadas=leitura.rejeitadas,
        campo_valor=None,
    )
    batch_id = _registrar_lote(
        conn, TIPO_EXECUCAO_ANUAL, nome_arquivo, hash_arquivo, len(leitura.registros), resumo
    )
    _gravar_rodape(conn, batch_id, comparar_rodape(TIPO_EXECUCAO_ANUAL, leitura))

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
    registrar_alertas_ted_sem_siafi(conn, [(r.ted, r.motivo) for r in leitura.rejeitadas if r.ted])
    sincronizar_alertas_rodape(conn)
    sincronizar_alertas_conciliacao_simec(conn)
    sincronizar_alertas_cadastrais(conn)
    return ResultadoImportacaoLote(batch_id, False, len(leitura.registros), leitura.rejeitadas)


def importar_doc_ne(
    conn: sqlite3.Connection, df: pd.DataFrame, nome_arquivo: str, conteudo_bytes: bytes
) -> ResultadoImportacaoLote:
    hash_arquivo = _hash_bytes(conteudo_bytes)
    existente = _lote_ja_importado(conn, TIPO_DOC_NE, hash_arquivo)
    if existente is not None:
        return ResultadoImportacaoLote(existente, ja_importado=True, inseridos=0)

    leitura = ler_doc_ne_simec(df)
    resumo = _resumo_controle(
        quantidade_linhas_lidas=len(df), registros=leitura.registros, rejeitadas=leitura.rejeitadas,
        campo_valor="valor_ne",
    )
    batch_id = _registrar_lote(conn, TIPO_DOC_NE, nome_arquivo, hash_arquivo, len(leitura.registros), resumo)
    _gravar_rodape(conn, batch_id, comparar_rodape(TIPO_DOC_NE, leitura))

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
    sincronizar_alertas_rodape(conn)
    sincronizar_alertas_multiplos_teds(conn)
    sincronizar_alertas_execucao_tg(conn)
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
    resumo = _resumo_controle(
        quantidade_linhas_lidas=len(df), registros=leitura.registros, rejeitadas=leitura.rejeitadas,
        campo_valor="valor_original", campo_operacao="operacao", campo_avisos="avisos",
    )
    batch_id = _registrar_lote(conn, TIPO_DOC_NC, nome_arquivo, hash_arquivo, len(leitura.registros), resumo)
    _gravar_rodape(conn, batch_id, comparar_rodape(TIPO_DOC_NC, leitura))

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
    sincronizar_alertas_rodape(conn)
    sincronizar_alertas_nc_parcial(conn)
    sincronizar_alertas_conciliacao_simec(conn)
    sincronizar_alertas_cadastrais(conn)
    return ResultadoImportacaoLote(batch_id, False, len(leitura.registros), leitura.rejeitadas)


def importar_doc_pf(
    conn: sqlite3.Connection, df: pd.DataFrame, nome_arquivo: str, conteudo_bytes: bytes
) -> ResultadoImportacaoLote:
    hash_arquivo = _hash_bytes(conteudo_bytes)
    existente = _lote_ja_importado(conn, TIPO_DOC_PF, hash_arquivo)
    if existente is not None:
        return ResultadoImportacaoLote(existente, ja_importado=True, inseridos=0)

    leitura = ler_doc_pf_simec(df)
    resumo = _resumo_controle(
        quantidade_linhas_lidas=len(df), registros=leitura.registros, rejeitadas=leitura.rejeitadas,
        campo_valor="valor_original", campo_operacao="operacao",
    )
    batch_id = _registrar_lote(conn, TIPO_DOC_PF, nome_arquivo, hash_arquivo, len(leitura.registros), resumo)
    _gravar_rodape(conn, batch_id, comparar_rodape(TIPO_DOC_PF, leitura))

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
    sincronizar_alertas_rodape(conn)
    sincronizar_alertas_conciliacao_simec(conn)
    sincronizar_alertas_cadastrais(conn)
    return ResultadoImportacaoLote(batch_id, False, len(leitura.registros), leitura.rejeitadas)


def sincronizar_execucao_tg(
    conn: sqlite3.Connection, execucao_mensal: pd.DataFrame, sha256_manifesto: str, nome_arquivo: str
) -> ResultadoImportacaoLote:
    """Espelha a Execução Mensal em `execucao_tg` (uma linha por NE × mês de lançamento — ver
    `src/teds_importacao_tesouro_gerencial.py`). Diferente dos demais relatórios, NÃO há arquivo
    enviado por upload: a origem é a extração já importada e versionada da Execução Mensal, e o
    `sha256_manifesto` dela faz o papel de hash do arquivo na idempotência de arquivo idêntico
    (mesma extração já sincronizada -> no-op). Extração nova traz linhas conhecidas -> upsert
    pela chave natural (NE, ano, mês), atualizando valores e a rastreabilidade para o lote
    novo; linha que uma extração posterior deixe de trazer permanece como estava (esta função
    nunca apaga)."""

    existente = _lote_ja_importado(conn, TIPO_EXECUCAO_TG, sha256_manifesto)
    if existente is not None:
        return ResultadoImportacaoLote(existente, ja_importado=True, inseridos=0)

    leitura = montar_execucao_tg(execucao_mensal)
    resumo = _resumo_controle(
        quantidade_linhas_lidas=len(leitura.registros) + len(leitura.rejeitadas),
        registros=leitura.registros, rejeitadas=leitura.rejeitadas, campo_valor=None,
    )
    batch_id = _registrar_lote(
        conn, TIPO_EXECUCAO_TG, nome_arquivo, sha256_manifesto, len(leitura.registros), resumo
    )

    conn.executemany(
        """
        INSERT INTO execucao_tg
            (numero_completo_ne, favorecido, descricao, empenhado, liquidado, pago,
             ano_lancamento, mes_lancamento, import_batch_id, linha_origem)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(numero_completo_ne, ano_lancamento, mes_lancamento)
        DO UPDATE SET
            favorecido = excluded.favorecido,
            descricao = excluded.descricao,
            empenhado = excluded.empenhado,
            liquidado = excluded.liquidado,
            pago = excluded.pago,
            import_batch_id = excluded.import_batch_id,
            linha_origem = excluded.linha_origem
        """,
        [
            (
                r["numero_completo_ne"],
                r["favorecido"],
                r["descricao"],
                valor_para_texto(r["empenhado"]),
                valor_para_texto(r["liquidado"]),
                valor_para_texto(r["pago"]),
                r["ano_lancamento"],
                r["mes_lancamento"],
                batch_id,
                _json_linha_origem(r["linha_origem"]),
            )
            for r in leitura.registros
        ],
    )
    conn.commit()
    sincronizar_alertas_execucao_tg(conn)
    return ResultadoImportacaoLote(batch_id, False, len(leitura.registros), leitura.rejeitadas)


class ExecucaoMensalNaoImportada(RuntimeError):
    """Não há extração da Execução Mensal importada (`data/manifestos/execucao_mensal_atual.json`
    ausente) — nada a sincronizar; a importação é feita em "Atualizar Planilhas"."""


def status_sincronizacao_execucao_tg(
    conn: sqlite3.Connection, diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO
) -> tuple[ManifestoExecucaoMensal | None, int | None]:
    """(manifesto atual da Execução Mensal, id do lote que já a sincronizou ou `None`) —
    consulta barata (não lê a planilha), para a página mostrar o estado antes de qualquer ação."""

    manifesto = ManifestoExecucaoMensal.atual(Path(diretorio_manifestos))
    if manifesto is None:
        return None, None
    return manifesto, _lote_ja_importado(conn, TIPO_EXECUCAO_TG, manifesto.sha256)


def sincronizar_execucao_tg_atual(
    conn: sqlite3.Connection,
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
    diretorio_dados_brutos: str | Path = DIRETORIO_DADOS_BRUTOS_PADRAO,
) -> ResultadoImportacaoLote:
    """Sincroniza `execucao_tg` com a extração ATUAL da Execução Mensal (a composta por ano de
    `carregar_atual`, nunca lê um arquivo fora do manifesto). Confere a idempotência ANTES de
    ler a planilha grande: extração já sincronizada devolve o lote antigo sem tocar no arquivo.
    Levanta `ExecucaoMensalNaoImportada` se não há extração importada."""

    manifesto, lote_existente = status_sincronizacao_execucao_tg(conn, diretorio_manifestos)
    if manifesto is None:
        raise ExecucaoMensalNaoImportada("Nenhuma extração da Execução Mensal importada ainda.")
    if lote_existente is not None:
        return ResultadoImportacaoLote(lote_existente, ja_importado=True, inseridos=0)

    execucao_mensal = carregar_execucao_mensal_atual(diretorio_dados_brutos, diretorio_manifestos)
    if execucao_mensal is None:
        raise ExecucaoMensalNaoImportada("Manifesto da Execução Mensal sem dados carregáveis.")
    return sincronizar_execucao_tg(conn, execucao_mensal, manifesto.sha256, manifesto.arquivo)


# --------------------------------------------------------------------------------------
# Conveniência: importar direto de um arquivo em disco (nunca o modifica — só lê). Só os
# relatórios do SIMEC: a execução do Tesouro Gerencial não vem de arquivo próprio, ver
# `sincronizar_execucao_tg`.
# --------------------------------------------------------------------------------------

_IMPORTADORES_POR_TIPO = {
    TIPO_EXECUCAO_ANUAL: importar_execucao_anual,
    TIPO_DOC_NE: importar_doc_ne,
    TIPO_DOC_NC: importar_doc_nc,
    TIPO_DOC_PF: importar_doc_pf,
}


def importar_arquivo(conn: sqlite3.Connection, tipo_relatorio: str, caminho: str | Path) -> ResultadoImportacaoLote:
    importador = _IMPORTADORES_POR_TIPO.get(tipo_relatorio)
    if importador is None:
        raise ValueError(f"Tipo de relatório desconhecido: {tipo_relatorio!r}")

    caminho = Path(caminho)
    conteudo = caminho.read_bytes()
    df = pd.read_excel(caminho)
    return importador(conn, df, caminho.name, conteudo)
