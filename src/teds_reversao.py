"""
Reversão de lote de importação do módulo de TEDs (briefing, seção 6.4): desfaz um lote
"integralmente, sem apagar o histórico da operação".

COMO FUNCIONA (ver `docs/base_teds.md`, seção 8.2)
--------------------------------------------------
As importações gravam por *upsert*: uma linha que o arquivo novo já conhecia é atualizada no
lugar. Para poder desfazer isso, um gatilho (`src/teds_schema.py::TABELAS_VERSIONADAS`) copia a
versão ANTERIOR da linha para `historico_linha` toda vez que um lote diferente a sobrescreve.
Reverter o lote B, para cada linha que hoje pertence a B:

  * se existia uma versão anterior válida (de um lote que NÃO foi revertido) → a linha volta a
    essa versão, com o `import_batch_id` original;
  * senão (B criou a linha) → a linha sai da tabela de trabalho.

Em ambos os casos a versão de B é gravada em `linha_revertida`: nada é descartado, só deixa de
contar nos totais. O lote fica com `status = 'revertido'`, com quem reverteu, quando e por quê,
e a ação entra na trilha de auditoria — tudo na MESMA transação: ou o lote é revertido por
inteiro, ou nada muda.

LIMITES (deliberados)
---------------------
  * Só lotes gravados depois do histórico de versões existir (`versionado = 1`): um lote
    anterior pode ter sobrescrito linhas sem deixar o valor antigo guardado, e revertê-lo
    apagaria dado que já existia. Esses lotes são recusados com mensagem explicando o motivo.
  * Reverter fora de ordem é permitido: o valor restaurado é sempre o da versão anterior mais
    recente que pertence a um lote ainda válido (pula versões de lotes já revertidos).
  * `vinculo_ne.status_validacao` (decisão humana sobre NE em mais de um TED) NÃO é revertido
    junto com o valor: ao restaurar um vínculo, o status atual é mantido.
  * Alertas já criados a partir de dados do lote revertido NÃO são fechados automaticamente
    (mesma regra dos demais alertas: só uma pessoa resolve). Os alertas dos dados que sobraram
    são recalculados ao final.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.teds_alertas import (
    sincronizar_alertas_cadastrais,
    sincronizar_alertas_conciliacao_simec,
    sincronizar_alertas_multiplos_teds,
    sincronizar_alertas_nc_parcial,
)
from src.teds_auditoria import ACAO_LOTE_REVERTIDO, ENTIDADE_IMPORT_BATCH, registrar_auditoria
from src.teds_schema import TABELAS_VERSIONADAS

STATUS_LOTE_OK = "ok"
STATUS_LOTE_REVERTIDO = "revertido"

ACAO_LINHA_REMOVIDA = "removida"
ACAO_LINHA_VOLTOU_A_VERSAO_ANTERIOR = "voltou_a_versao_anterior"

#: Colunas que uma restauração NÃO sobrescreve, por tabela: `id` é gerado pelo banco e
#: `status_validacao` guarda uma decisão humana que a importação nunca alterou.
_COLUNAS_PRESERVADAS = {"execucao_tg": {"id"}, "vinculo_ne": {"status_validacao"}}


class ReversaoNaoPermitida(ValueError):
    """O lote não pode ser revertido (não existe, já foi revertido ou é anterior ao histórico
    de versões) ou faltam responsável/motivo."""


@dataclass(frozen=True)
class ResultadoReversao:
    import_batch_id: int
    removidas: dict[str, int] = field(default_factory=dict)
    restauradas: dict[str, int] = field(default_factory=dict)

    @property
    def total_removidas(self) -> int:
        return sum(self.removidas.values())

    @property
    def total_restauradas(self) -> int:
        return sum(self.restauradas.values())


def lotes_reversiveis(conn: sqlite3.Connection) -> list[tuple[int, str, str, str, int]]:
    """(id, tipo_relatorio, nome_arquivo, data_importacao, quantidade_registros) dos lotes que
    ainda podem ser revertidos, do mais recente ao mais antigo."""

    return conn.execute(
        "SELECT id, tipo_relatorio, nome_arquivo, data_importacao, quantidade_registros "
        "FROM import_batch WHERE status = ? AND versionado = 1 ORDER BY id DESC",
        (STATUS_LOTE_OK,),
    ).fetchall()


def _motivo_de_recusa(conn: sqlite3.Connection, import_batch_id: int) -> str | None:
    lote = conn.execute(
        "SELECT status, versionado FROM import_batch WHERE id = ?", (import_batch_id,)
    ).fetchone()
    if lote is None:
        return "Lote não encontrado."
    status, versionado = lote
    if status == STATUS_LOTE_REVERTIDO:
        return "Este lote já foi revertido."
    if status != STATUS_LOTE_OK:
        return f"Só lotes com status \"{STATUS_LOTE_OK}\" podem ser revertidos (este está \"{status}\")."
    if versionado != 1:
        return (
            "Este lote é anterior ao histórico de versões: ele pode ter sobrescrito linhas sem "
            "guardar o valor antigo, então revertê-lo apagaria dado que já existia. Não é seguro reverter."
        )
    return None


def _chave_de(linha_json: str, colunas_chave: tuple[str, ...]) -> tuple:
    dados = json.loads(linha_json)
    return tuple(dados[c] for c in colunas_chave)


def _reverter_tabela(
    conn: sqlite3.Connection,
    tabela: str,
    import_batch_id: int,
    lotes_invalidos: set[int],
    agora: str,
) -> tuple[int, int]:
    """Devolve (linhas removidas, linhas restauradas) da tabela."""

    colunas_chave, colunas = TABELAS_VERSIONADAS[tabela]
    linhas = [
        dict(zip(colunas, valores))
        for valores in conn.execute(
            f"SELECT {', '.join(colunas)} FROM {tabela} WHERE import_batch_id = ?", (import_batch_id,)
        ).fetchall()
    ]
    if not linhas:
        return 0, 0

    cache: dict[int, dict[tuple, tuple[int | None, dict[str, Any]]]] = {}

    def versoes_substituidas_por(lote: int) -> dict[tuple, tuple[int | None, dict[str, Any]]]:
        if lote not in cache:
            versoes: dict[tuple, tuple[int | None, dict[str, Any]]] = {}
            for chave_json, origem, conteudo in conn.execute(
                "SELECT chave, import_batch_id_origem, conteudo FROM historico_linha "
                "WHERE tabela = ? AND import_batch_id_sobrescritor = ? ORDER BY id",
                (tabela, lote),
            ).fetchall():
                versoes[_chave_de(chave_json, colunas_chave)] = (origem, json.loads(conteudo))
            cache[lote] = versoes
        return cache[lote]

    def versao_anterior_valida(chave: tuple) -> dict[str, Any] | None:
        lote_atual, visitados = import_batch_id, set()
        while lote_atual not in visitados:
            visitados.add(lote_atual)
            encontrada = versoes_substituidas_por(lote_atual).get(chave)
            if encontrada is None:
                return None
            origem, conteudo = encontrada
            if origem is not None and origem in lotes_invalidos:
                lote_atual = origem  # essa versão também é de um lote revertido: volta mais um passo
                continue
            return conteudo
        return None

    restaurar = [c for c in colunas if c not in colunas_chave and c not in _COLUNAS_PRESERVADAS.get(tabela, set())]
    condicao_chave = " AND ".join(f"{c} = ?" for c in colunas_chave)
    removidas = restauradas = 0
    arquivadas = []
    for linha in linhas:
        chave = tuple(linha[c] for c in colunas_chave)
        anterior = versao_anterior_valida(chave)
        arquivadas.append((
            import_batch_id, tabela,
            json.dumps(dict(zip(colunas_chave, chave)), ensure_ascii=False, default=str),
            json.dumps(linha, ensure_ascii=False, default=str),
            ACAO_LINHA_VOLTOU_A_VERSAO_ANTERIOR if anterior is not None else ACAO_LINHA_REMOVIDA,
            agora,
        ))
        if anterior is None:
            conn.execute(f"DELETE FROM {tabela} WHERE {condicao_chave}", chave)
            removidas += 1
        else:
            conn.execute(
                f"UPDATE {tabela} SET {', '.join(f'{c} = ?' for c in restaurar)} WHERE {condicao_chave}",
                [anterior[c] for c in restaurar] + list(chave),
            )
            restauradas += 1

    conn.executemany(
        "INSERT INTO linha_revertida (import_batch_id, tabela, chave, conteudo, acao, data_hora) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        arquivadas,
    )
    return removidas, restauradas


def reverter_lote(
    conn: sqlite3.Connection,
    import_batch_id: int,
    *,
    responsavel: str,
    motivo: str,
    origem: str = "interface",
) -> ResultadoReversao:
    """Reverte o lote inteiro numa única transação (ver o docstring do módulo)."""

    responsavel = (responsavel or "").strip()
    motivo = (motivo or "").strip()
    if not responsavel:
        raise ReversaoNaoPermitida("Informe o responsável pela reversão.")
    if not motivo:
        raise ReversaoNaoPermitida("Informe o motivo da reversão.")
    recusa = _motivo_de_recusa(conn, import_batch_id)
    if recusa is not None:
        raise ReversaoNaoPermitida(recusa)

    agora = datetime.now(timezone.utc).isoformat()
    lotes_invalidos = {
        id_lote
        for (id_lote,) in conn.execute(
            "SELECT id FROM import_batch WHERE status = ?", (STATUS_LOTE_REVERTIDO,)
        ).fetchall()
    } | {import_batch_id}

    removidas: dict[str, int] = {}
    restauradas: dict[str, int] = {}
    try:
        conn.execute("UPDATE versionamento_controle SET pausado = 1 WHERE id = 1")
        for tabela in TABELAS_VERSIONADAS:
            n_removidas, n_restauradas = _reverter_tabela(conn, tabela, import_batch_id, lotes_invalidos, agora)
            if n_removidas:
                removidas[tabela] = n_removidas
            if n_restauradas:
                restauradas[tabela] = n_restauradas
        conn.execute("UPDATE versionamento_controle SET pausado = 0 WHERE id = 1")
        conn.execute(
            "UPDATE import_batch SET status = ?, revertido_em = ?, revertido_por = ?, motivo_reversao = ? "
            "WHERE id = ?",
            (STATUS_LOTE_REVERTIDO, agora, responsavel, motivo, import_batch_id),
        )
        registrar_auditoria(
            conn, acao=ACAO_LOTE_REVERTIDO, entidade=ENTIDADE_IMPORT_BATCH, entidade_id=import_batch_id,
            valor_anterior={"status": STATUS_LOTE_OK},
            valor_novo={
                "status": STATUS_LOTE_REVERTIDO,
                "linhas_removidas": removidas,
                "linhas_restauradas_para_versao_anterior": restauradas,
            },
            usuario=responsavel, motivo=motivo, origem=origem,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Depois de comitar: recalcula alertas sobre o que sobrou (só cria, nunca fecha).
    sincronizar_alertas_multiplos_teds(conn)
    sincronizar_alertas_nc_parcial(conn)
    sincronizar_alertas_conciliacao_simec(conn)
    sincronizar_alertas_cadastrais(conn)
    return ResultadoReversao(import_batch_id, removidas, restauradas)
