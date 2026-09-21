"""
Alertas do módulo de TEDs. Dois tipos implementados:

  * "empenho associado a mais de um TED" (ver briefing, seção "Alertas do MVP") — o caso
    concreto documentado (NE 2026NE000422 nos TEDs 17352 e 17454);
  * "NC sem UG emitente" (`status_relacionamento='PARCIAL'` — ver docstring de
    `ler_doc_nc_simec` em `src/teds_importacao_simec.py`): achado da extração real do SIMEC,
    não do briefing original — ~41% das linhas reais de DOC NC não trazem essa coluna, o que
    limita a conciliação externa daquele documento (aprovado explicitamente para gerar alerta,
    ver conversa de alinhamento).

Os demais alertas do MVP (crédito sem empenho, PF maior que NC, vigência, etc.) ficam para uma
fase seguinte, fora do escopo aprovado agora.

Cada tipo tem duas camadas: funções puras (testáveis sem banco) e uma `sincronizar_alertas_*`
que lê do SQLite e grava alertas novos em `alerta` — sem duplicar um alerta já aberto para o
mesmo documento, e sem nunca fechar um alerta sozinha (resolução é sempre uma ação humana
registrada na Central de Alertas, fora do escopo desta fase).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from src.teds_normalizacao import texto_para_valor, valor_para_texto

TIPO_EMPENHO_MULTIPLOS_TEDS = "empenho_multiplos_teds"
TIPO_NC_UG_EMITENTE_AUSENTE = "nc_ug_emitente_ausente"
STATUS_PENDENTE = "pendente"
STATUS_DESCARTADO = "descartado"
STATUS_OK = "ok"
STATUS_RELACIONAMENTO_PARCIAL = "PARCIAL"


@dataclass(frozen=True)
class VinculoNE:
    chave_ted: str
    chave_empenho: str
    numero_ne: str
    valor_ne: Decimal


@dataclass(frozen=True)
class Alerta:
    tipo: str
    gravidade: str
    documento: str
    descricao: str
    chave_ted: str | None = None
    status: str = "aberto"


@dataclass(frozen=True)
class DecisaoVinculoNE:
    id: int
    chave_empenho: str
    chave_ted_escolhida: str
    teds_envolvidos: tuple[str, ...]
    decisao: str
    responsavel: str
    justificativa: str
    data_decisao: str
    alerta_id: int


def agrupar_por_empenho(vinculos: list[VinculoNE]) -> dict[str, list[VinculoNE]]:
    grupos: dict[str, list[VinculoNE]] = {}
    for vinculo in vinculos:
        grupos.setdefault(vinculo.chave_empenho, []).append(vinculo)
    return grupos


def detectar_ne_em_multiplos_teds(vinculos: list[VinculoNE]) -> dict[str, list[VinculoNE]]:
    """Chaves de empenho cujos vínculos apontam para mais de um TED distinto.

    Não decide qual TED está certo — só identifica o conflito (regra do briefing: "não
    excluir nem escolher automaticamente um dos vínculos").
    """

    pendentes = {}
    for chave_empenho, grupo in agrupar_por_empenho(vinculos).items():
        if len({v.chave_ted for v in grupo}) > 1:
            pendentes[chave_empenho] = grupo
    return pendentes


def total_empenhado_por_ted(
    vinculos: list[VinculoNE], pendentes: dict[str, list[VinculoNE]]
) -> dict[str, Decimal]:
    """Soma `valor_ne` por TED, excluindo vínculos pendentes de distribuição — impede que a
    execução de uma NE em conflito seja contabilizada integralmente nos dois TEDs enquanto
    a pendência não é resolvida."""

    totais: dict[str, Decimal] = {}
    for vinculo in vinculos:
        if vinculo.chave_empenho in pendentes:
            continue
        totais[vinculo.chave_ted] = totais.get(vinculo.chave_ted, Decimal("0")) + vinculo.valor_ne
    return totais


def gerar_alertas_ne_multiplos_teds(pendentes: dict[str, list[VinculoNE]]) -> list[Alerta]:
    alertas = []
    for chave_empenho, grupo in pendentes.items():
        teds = sorted({v.chave_ted for v in grupo})
        numero_ne = grupo[0].numero_ne
        descricao = (
            f"Empenho {numero_ne} (chave {chave_empenho}) está vinculado a {len(teds)} TEDs "
            f"diferentes: {', '.join(teds)}. Execução mantida fora dos totais consolidados "
            "de todos os TEDs envolvidos até a resolução do vínculo."
        )
        alertas.append(
            Alerta(
                tipo=TIPO_EMPENHO_MULTIPLOS_TEDS,
                gravidade="alta",
                documento=chave_empenho,
                descricao=descricao,
                chave_ted=None,
            )
        )
    return alertas


# --------------------------------------------------------------------------------------
# NC sem UG emitente (status_relacionamento='PARCIAL')
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DocumentoNC:
    chave_nc_documento: str
    numero_nc: str
    chave_ted: str | None
    status_relacionamento: str


def detectar_documentos_nc_parciais(documentos: list[DocumentoNC]) -> list[DocumentoNC]:
    """Documentos de NC com `status_relacionamento='PARCIAL'` — sem UG emitente em nenhuma
    das linhas do documento, o que impede a conciliação externa por UG (ver docstring de
    `ler_doc_nc_simec`). Não decide nada sobre o documento, só identifica a lacuna."""

    return [d for d in documentos if d.status_relacionamento == STATUS_RELACIONAMENTO_PARCIAL]


def gerar_alertas_nc_parcial(parciais: list[DocumentoNC]) -> list[Alerta]:
    alertas = []
    for documento in parciais:
        descricao = (
            f"NC {documento.numero_nc} (documento {documento.chave_nc_documento}) sem UG "
            "emitente em nenhuma linha da extração — conciliação externa por UG fica "
            "incompleta até a UG ser identificada manualmente."
        )
        alertas.append(
            Alerta(
                tipo=TIPO_NC_UG_EMITENTE_AUSENTE,
                gravidade="media",
                documento=documento.chave_nc_documento,
                descricao=descricao,
                chave_ted=documento.chave_ted,
            )
        )
    return alertas


def _carregar_documentos_nc(conn: sqlite3.Connection) -> list[DocumentoNC]:
    linhas = conn.execute(
        "SELECT chave_nc_documento, numero_nc, chave_ted, status_relacionamento FROM documento_nc"
    ).fetchall()
    return [
        DocumentoNC(
            chave_nc_documento=chave_nc_documento,
            numero_nc=numero_nc,
            chave_ted=chave_ted,
            status_relacionamento=status_relacionamento,
        )
        for chave_nc_documento, numero_nc, chave_ted, status_relacionamento in linhas
    ]


def sincronizar_alertas_nc_parcial(conn: sqlite3.Connection) -> list[Alerta]:
    """Garante um alerta aberto para cada documento de NC com `status_relacionamento='PARCIAL'`.
    Devolve só os alertas recém-criados nesta chamada (não os que já existiam) — mesma
    semântica de `sincronizar_alertas_multiplos_teds`."""

    documentos = _carregar_documentos_nc(conn)
    parciais = detectar_documentos_nc_parciais(documentos)

    ja_sinalizados = {
        documento
        for (documento,) in conn.execute(
            "SELECT documento FROM alerta WHERE tipo = ? AND status != 'resolvido'",
            (TIPO_NC_UG_EMITENTE_AUSENTE,),
        ).fetchall()
    }

    novos = [
        alerta for alerta in gerar_alertas_nc_parcial(parciais) if alerta.documento not in ja_sinalizados
    ]

    agora = datetime.now(timezone.utc).isoformat()
    for alerta in novos:
        conn.execute(
            """
            INSERT INTO alerta (tipo, gravidade, chave_ted, documento, descricao, status, data_identificacao)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alerta.tipo,
                alerta.gravidade,
                alerta.chave_ted,
                alerta.documento,
                alerta.descricao,
                alerta.status,
                agora,
            ),
        )
    conn.commit()
    return novos


# --------------------------------------------------------------------------------------
# Integração com o banco
# --------------------------------------------------------------------------------------

def _carregar_vinculos(conn: sqlite3.Connection) -> list[VinculoNE]:
    linhas = conn.execute(
        "SELECT chave_ted, chave_empenho, numero_ne, valor_ne FROM vinculo_ne"
    ).fetchall()
    return [
        VinculoNE(
            chave_ted=chave_ted,
            chave_empenho=chave_empenho,
            numero_ne=numero_ne,
            valor_ne=texto_para_valor(valor_ne),
        )
        for chave_ted, chave_empenho, numero_ne, valor_ne in linhas
    ]


def carregar_decisoes_vinculo_ne(
    conn: sqlite3.Connection, chave_empenho: str
) -> list[DecisaoVinculoNE]:
    """Histórico append-only das decisões para um empenho, da mais recente à mais antiga."""

    linhas = conn.execute(
        """
        SELECT id, chave_empenho, chave_ted_escolhida, teds_envolvidos, decisao,
               responsavel, justificativa, data_decisao, alerta_id
        FROM decisao_vinculo_ne
        WHERE chave_empenho = ?
        ORDER BY id DESC
        """,
        (chave_empenho,),
    ).fetchall()
    return [
        DecisaoVinculoNE(
            id=id_decisao,
            chave_empenho=chave,
            chave_ted_escolhida=escolhida,
            teds_envolvidos=tuple(json.loads(teds)),
            decisao=decisao,
            responsavel=responsavel,
            justificativa=justificativa,
            data_decisao=data_decisao,
            alerta_id=alerta_id,
        )
        for id_decisao, chave, escolhida, teds, decisao, responsavel, justificativa, data_decisao, alerta_id in linhas
    ]


def teds_vinculados_ao_empenho(conn: sqlite3.Connection, chave_empenho: str) -> list[str]:
    return [
        chave_ted
        for (chave_ted,) in conn.execute(
            "SELECT DISTINCT chave_ted FROM vinculo_ne WHERE chave_empenho = ? ORDER BY chave_ted",
            (chave_empenho,),
        ).fetchall()
    ]


def registrar_decisao_vinculo_ne(
    conn: sqlite3.Connection,
    *,
    alerta_id: int,
    chave_empenho: str,
    chave_ted_escolhida: str,
    responsavel: str,
    justificativa: str,
) -> DecisaoVinculoNE:
    """Resolve explicitamente um vínculo múltiplo sem apagar qualquer linha importada."""

    responsavel = responsavel.strip()
    justificativa = justificativa.strip()
    if not responsavel:
        raise ValueError("Informe o responsável pela decisão.")
    if not justificativa:
        raise ValueError("Informe a justificativa da decisão.")

    alerta = conn.execute(
        "SELECT tipo, documento, status FROM alerta WHERE id = ?", (alerta_id,)
    ).fetchone()
    if alerta is None:
        raise ValueError("Alerta não encontrado.")
    tipo, documento, status = alerta
    if tipo != TIPO_EMPENHO_MULTIPLOS_TEDS or documento != chave_empenho:
        raise ValueError("O alerta não corresponde ao vínculo múltiplo informado.")
    if status == "resolvido":
        raise ValueError("Este alerta já foi resolvido.")

    teds = teds_vinculados_ao_empenho(conn, chave_empenho)
    if len(teds) < 2:
        raise ValueError("O empenho não está vinculado a mais de um TED.")
    if chave_ted_escolhida not in teds:
        raise ValueError("O TED escolhido não está entre os vínculos do empenho.")

    agora = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "UPDATE vinculo_ne SET status_validacao = ? WHERE chave_empenho = ?",
            (STATUS_DESCARTADO, chave_empenho),
        )
        conn.execute(
            """
            UPDATE vinculo_ne SET status_validacao = ?
            WHERE chave_empenho = ? AND chave_ted = ?
            """,
            (STATUS_OK, chave_empenho, chave_ted_escolhida),
        )
        cursor = conn.execute(
            """
            INSERT INTO decisao_vinculo_ne
                (chave_empenho, chave_ted_escolhida, teds_envolvidos, decisao,
                 responsavel, justificativa, data_decisao, alerta_id)
            VALUES (?, ?, ?, 'atribuir_ted', ?, ?, ?, ?)
            """,
            (
                chave_empenho,
                chave_ted_escolhida,
                json.dumps(teds, ensure_ascii=False),
                responsavel,
                justificativa,
                agora,
                alerta_id,
            ),
        )
        conn.execute(
            """
            UPDATE alerta
            SET status = 'resolvido', responsavel = ?, justificativa = ?, data_resolucao = ?
            WHERE id = ?
            """,
            (responsavel, justificativa, agora, alerta_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return DecisaoVinculoNE(
        id=int(cursor.lastrowid),
        chave_empenho=chave_empenho,
        chave_ted_escolhida=chave_ted_escolhida,
        teds_envolvidos=tuple(teds),
        decisao="atribuir_ted",
        responsavel=responsavel,
        justificativa=justificativa,
        data_decisao=agora,
        alerta_id=alerta_id,
    )


def _decisoes_vigentes(conn: sqlite3.Connection) -> dict[str, DecisaoVinculoNE]:
    chaves = {
        chave
        for (chave,) in conn.execute(
            "SELECT DISTINCT chave_empenho FROM decisao_vinculo_ne"
        ).fetchall()
    }
    return {
        chave: carregar_decisoes_vinculo_ne(conn, chave)[0]
        for chave in chaves
    }


def sincronizar_alertas_multiplos_teds(conn: sqlite3.Connection) -> list[Alerta]:
    """Recalcula `status_validacao` de todos os vínculos e garante um alerta aberto para
    cada empenho pendente. Devolve os alertas recém-criados nesta chamada (não os que já
    existiam)."""

    vinculos = _carregar_vinculos(conn)
    conflitos = detectar_ne_em_multiplos_teds(vinculos)
    decisoes = _decisoes_vigentes(conn)
    pendentes: dict[str, list[VinculoNE]] = {}

    conn.execute(
        "UPDATE vinculo_ne SET status_validacao = ? WHERE status_validacao != ?",
        (STATUS_OK, STATUS_OK),
    )
    for chave_empenho, grupo in conflitos.items():
        teds_atuais = {v.chave_ted for v in grupo}
        decisao = decisoes.get(chave_empenho)
        if (
            decisao is not None
            and set(decisao.teds_envolvidos) == teds_atuais
            and decisao.chave_ted_escolhida in teds_atuais
        ):
            conn.execute(
                "UPDATE vinculo_ne SET status_validacao = ? WHERE chave_empenho = ?",
                (STATUS_DESCARTADO, chave_empenho),
            )
            conn.execute(
                """
                UPDATE vinculo_ne SET status_validacao = ?
                WHERE chave_empenho = ? AND chave_ted = ?
                """,
                (STATUS_OK, chave_empenho, decisao.chave_ted_escolhida),
            )
        else:
            pendentes[chave_empenho] = grupo
            conn.execute(
                "UPDATE vinculo_ne SET status_validacao = ? WHERE chave_empenho = ?",
                (STATUS_PENDENTE, chave_empenho),
            )

    ja_sinalizados = {
        documento
        for (documento,) in conn.execute(
            "SELECT documento FROM alerta WHERE tipo = ? AND status != 'resolvido'",
            (TIPO_EMPENHO_MULTIPLOS_TEDS,),
        ).fetchall()
    }

    novos = [
        alerta
        for alerta in gerar_alertas_ne_multiplos_teds(pendentes)
        if alerta.documento not in ja_sinalizados
    ]

    agora = datetime.now(timezone.utc).isoformat()
    for alerta in novos:
        conn.execute(
            """
            INSERT INTO alerta (tipo, gravidade, chave_ted, documento, descricao, status, data_identificacao)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alerta.tipo,
                alerta.gravidade,
                alerta.chave_ted,
                alerta.documento,
                alerta.descricao,
                alerta.status,
                agora,
            ),
        )
    conn.commit()
    return novos
