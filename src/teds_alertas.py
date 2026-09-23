"""
Alertas do módulo de TEDs. Cinco tipos implementados (os três últimos, de conciliação SIMEC, estão
na seção própria mais abaixo):

  * "empenho associado a mais de um TED" (ver briefing, seção "Alertas do MVP") — o caso
    concreto documentado (NE 2026NE000422 nos TEDs 17352 e 17454);
  * "NC sem UG emitente" (`status_relacionamento='PARCIAL'` — ver docstring de
    `ler_doc_nc_simec` em `src/teds_importacao_simec.py`): achado da extração real do SIMEC,
    não do briefing original — ~41% das linhas reais de DOC NC não trazem essa coluna, o que
    limita a conciliação externa daquele documento (aprovado explicitamente para gerar alerta,
    ver conversa de alinhamento).

Os demais alertas do MVP (crédito sem empenho, vigência, etc.) ficam para uma
fase seguinte, fora do escopo aprovado agora.

Cada tipo tem duas camadas: funções puras (testáveis sem banco) e uma `sincronizar_alertas_*`
que lê do SQLite e grava alertas novos em `alerta` — sem duplicar um alerta já aberto para o
mesmo documento, e sem nunca fechar um alerta sozinha (resolução é sempre uma ação humana
registrada na Central de Alertas, fora do escopo desta fase).
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from src.teds_auditoria import (
    ACAO_ALERTA_STATUS_ALTERADO,
    ACAO_VINCULO_NE_DECIDIDO,
    ENTIDADE_ALERTA,
    ENTIDADE_VINCULO_NE,
    registrar_auditoria,
)
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
# Conciliação SIMEC: documentos analíticos (NC/PF) × totais consolidados (execucao_anual)
# --------------------------------------------------------------------------------------

TIPO_NC_DIVERGE_CONSOLIDADO = "nc_liquida_diverge_consolidado"
TIPO_PF_DIVERGE_CONSOLIDADO = "pf_liquida_diverge_consolidado"
TIPO_PF_MAIOR_QUE_NC = "pf_liquida_maior_que_nc"

#: Diferença máxima tolerada entre duas somas (briefing, seções 8.1/9.1: "maior que R$ 0,01").
TOLERANCIA_CONCILIACAO = Decimal("0.01")


@dataclass(frozen=True)
class ResumoConciliacaoSimec:
    """Uma linha por TED. `*_analitica` = soma dos documentos importados (`valor_assinado`,
    ou seja, já com o sinal da operação); `*_consolidada` = soma de `execucao_anual` sobre
    todos os exercícios importados (Total Descentralizado / Total Repassado).

    `nc_analitica`/`pf_analitica` ficam `None` quando a base analítica correspondente ainda não
    foi importada (nunca zero: "sem base" não pode virar "divergência de tudo")."""

    chave_ted: str
    nc_consolidada: Decimal
    pf_consolidada: Decimal
    nc_analitica: Decimal | None
    pf_analitica: Decimal | None


def _moeda(valor: Decimal) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_alertas_conciliacao_simec(
    resumos: list[ResumoConciliacaoSimec], tolerancia: Decimal = TOLERANCIA_CONCILIACAO
) -> list[Alerta]:
    """Três verificações, todas descritivas: só apontam a diferença e as causas possíveis, sem
    decidir qual fonte está certa e sem alterar nenhum dado.

      1. NC líquida analítica ≠ Total Descentralizado consolidado;
      2. PF líquido analítico ≠ Total Repassado consolidado;
      3. PF líquido consolidado > NC líquida consolidada (repasse sem crédito que o cubra).
    """

    alertas: list[Alerta] = []
    for r in sorted(resumos, key=lambda x: x.chave_ted):
        if r.nc_analitica is not None and abs(r.nc_analitica - r.nc_consolidada) > tolerancia:
            alertas.append(
                Alerta(
                    tipo=TIPO_NC_DIVERGE_CONSOLIDADO,
                    gravidade="alta",
                    documento=r.chave_ted,
                    chave_ted=r.chave_ted,
                    descricao=(
                        f"NC líquida dos documentos importados ({_moeda(r.nc_analitica)}) difere do "
                        f"Total Descentralizado consolidado ({_moeda(r.nc_consolidada)}) em "
                        f"{_moeda(r.nc_analitica - r.nc_consolidada)}. Possíveis causas: extração de "
                        "documentos incompleta ou de outro período, documento sem data/TED, ou "
                        "divergência real na origem — não decidido automaticamente."
                    ),
                )
            )
        if r.pf_analitica is not None and abs(r.pf_analitica - r.pf_consolidada) > tolerancia:
            alertas.append(
                Alerta(
                    tipo=TIPO_PF_DIVERGE_CONSOLIDADO,
                    gravidade="alta",
                    documento=r.chave_ted,
                    chave_ted=r.chave_ted,
                    descricao=(
                        f"PF líquido dos documentos importados ({_moeda(r.pf_analitica)}) difere do "
                        f"Total Repassado consolidado ({_moeda(r.pf_consolidada)}) em "
                        f"{_moeda(r.pf_analitica - r.pf_consolidada)}. Possíveis causas: extração de "
                        "documentos incompleta ou de outro período, ou divergência real na origem "
                        "— não decidido automaticamente."
                    ),
                )
            )
        if r.pf_consolidada - r.nc_consolidada > tolerancia:
            alertas.append(
                Alerta(
                    tipo=TIPO_PF_MAIOR_QUE_NC,
                    gravidade="alta",
                    documento=r.chave_ted,
                    chave_ted=r.chave_ted,
                    descricao=(
                        f"Repasse líquido consolidado ({_moeda(r.pf_consolidada)}) é maior que a NC "
                        f"líquida consolidada ({_moeda(r.nc_consolidada)}): excesso de "
                        f"{_moeda(r.pf_consolidada - r.nc_consolidada)}. Pode indicar crédito "
                        "descentralizado em exercício anterior ao período importado — conferir "
                        "antes de considerar o TED conciliado."
                    ),
                )
            )
    return alertas


def _carregar_resumos_conciliacao(conn: sqlite3.Connection) -> list[ResumoConciliacaoSimec]:
    consolidado: dict[str, list[Decimal]] = {}
    for chave_ted, total_descentralizado, total_repassado in conn.execute(
        "SELECT chave_ted, total_descentralizado, total_repassado FROM execucao_anual"
    ).fetchall():
        acumulado = consolidado.setdefault(chave_ted, [Decimal("0"), Decimal("0")])
        acumulado[0] += texto_para_valor(total_descentralizado)
        acumulado[1] += texto_para_valor(total_repassado)

    def _somar(sql: str) -> dict[str, Decimal] | None:
        linhas = conn.execute(sql).fetchall()
        if not linhas:
            return None
        somas: dict[str, Decimal] = {}
        for chave_ted, valor in linhas:
            if chave_ted:
                somas[chave_ted] = somas.get(chave_ted, Decimal("0")) + texto_para_valor(valor)
        return somas

    nc = _somar("SELECT chave_ted, valor_assinado_total FROM documento_nc")
    pf = _somar("SELECT chave_ted, valor_assinado FROM documento_pf")
    return [
        ResumoConciliacaoSimec(
            chave_ted=chave_ted,
            nc_consolidada=nc_cons,
            pf_consolidada=pf_cons,
            nc_analitica=None if nc is None else nc.get(chave_ted, Decimal("0")),
            pf_analitica=None if pf is None else pf.get(chave_ted, Decimal("0")),
        )
        for chave_ted, (nc_cons, pf_cons) in consolidado.items()
    ]


def _gravar_alertas_novos(conn: sqlite3.Connection, candidatos: list[Alerta]) -> list[Alerta]:
    """Grava os candidatos que ainda não têm alerta não resolvido para o mesmo (tipo, documento)
    e devolve só os recém-criados. Nunca fecha nem altera um alerta existente."""

    tipos = sorted({a.tipo for a in candidatos})
    ja_sinalizados: set[tuple[str, str]] = set()
    if tipos:
        ja_sinalizados = {
            (tipo, documento)
            for tipo, documento in conn.execute(
                "SELECT tipo, documento FROM alerta WHERE status != 'resolvido' AND tipo IN ({})".format(
                    ",".join("?" * len(tipos))
                ),
                tipos,
            ).fetchall()
        }
    novos: list[Alerta] = []
    for alerta in candidatos:
        if (alerta.tipo, alerta.documento) not in ja_sinalizados:
            novos.append(alerta)
            ja_sinalizados.add((alerta.tipo, alerta.documento))

    agora = datetime.now(timezone.utc).isoformat()
    for alerta in novos:
        conn.execute(
            """
            INSERT INTO alerta (tipo, gravidade, chave_ted, documento, descricao, status, data_identificacao)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (alerta.tipo, alerta.gravidade, alerta.chave_ted, alerta.documento,
             alerta.descricao, alerta.status, agora),
        )
    conn.commit()
    return novos


def sincronizar_alertas_conciliacao_simec(conn: sqlite3.Connection) -> list[Alerta]:
    """Grava os alertas de conciliação que ainda não estão abertos para o mesmo TED. Devolve só
    os recém-criados. Nunca fecha um alerta — se a diferença deixar de existir numa
    importação futura, o alerta continua até tratamento humano (mesma regra dos demais)."""

    return _gravar_alertas_novos(
        conn, gerar_alertas_conciliacao_simec(_carregar_resumos_conciliacao(conn))
    )


# --------------------------------------------------------------------------------------
# Validações cadastrais e de vigência do TED (briefing, seção 7)
# --------------------------------------------------------------------------------------

TIPO_TED_VIGENCIA_INVERTIDA = "ted_vigencia_invertida"
TIPO_TED_SEM_UG_DESCENTRALIZADORA = "ted_sem_ug_descentralizadora"
TIPO_SIAFI_EM_MULTIPLOS_TEDS = "siafi_em_multiplos_teds"
TIPO_DOCUMENTO_FORA_DA_VIGENCIA = "documento_fora_da_vigencia"
TIPO_TED_VENCIDO_EM_EXECUCAO = "ted_vencido_em_execucao"
TIPO_TED_SEM_MOVIMENTACAO = "ted_sem_movimentacao"

#: Prazo padrão de "TED em execução sem movimentação" (briefing, seção 7, não define o prazo — este
#: valor é uma escolha inicial, ajustável por parâmetro). Movimentação = NC ou PF emitida; a NE não
#: entra porque `vinculo_ne` não guarda data de emissão.
PRAZO_SEM_MOVIMENTACAO_DIAS = 180

#: Único estado tratado como "em execução" (texto exato da extração real do SIMEC, comparado sem
#: acento e sem diferença de caixa). Os demais estados (prestação de contas, diligência,
#: comprovado etc.) NÃO são tratados como execução — regra confirmada apenas pelos valores vistos
#: na extração; um estado novo do SIMEC não gera alerta até ser classificado.
ESTADO_EM_EXECUCAO = "termo em execucao"


def _sem_acento_minusculo(texto: str | None) -> str:
    if not texto:
        return ""
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).strip().lower()


def estado_em_execucao(estado_atual: str | None) -> bool:
    return _sem_acento_minusculo(estado_atual) == ESTADO_EM_EXECUCAO


@dataclass(frozen=True)
class TedCadastro:
    chave_ted: str
    ted: str
    codigo_siafi: str
    estado_atual: str | None
    inicio_vigencia: date | None
    fim_vigencia: date | None
    ug_descentralizadora: str | None


@dataclass(frozen=True)
class DocumentoDatado:
    """NC ou PF já reduzido ao que a validação de vigência precisa."""

    tipo_documento: str  # "NC" | "PF"
    chave_documento: str
    numero: str
    chave_ted: str
    data_emissao: date | None


def _data_br(valor: date) -> str:
    return valor.strftime("%d/%m/%Y")


def gerar_alertas_cadastrais(
    teds: list[TedCadastro],
    documentos: list[DocumentoDatado],
    hoje: date,
    prazo_sem_movimentacao_dias: int = PRAZO_SEM_MOVIMENTACAO_DIAS,
) -> list[Alerta]:
    """Todas as verificações são descritivas: apontam a inconsistência sem alterar, excluir ou
    deixar de importar nada. Documento fora da vigência pode ser legítimo (briefing, seção 7),
    por isso gera alerta com justificativa possível, nunca exclusão."""

    alertas: list[Alerta] = []
    por_chave = {t.chave_ted: t for t in teds}

    for t in sorted(teds, key=lambda x: x.chave_ted):
        rotulo = f"TED {t.ted} (SIAFI {t.codigo_siafi})"
        if t.inicio_vigencia and t.fim_vigencia and t.inicio_vigencia > t.fim_vigencia:
            alertas.append(Alerta(
                tipo=TIPO_TED_VIGENCIA_INVERTIDA, gravidade="alta", documento=t.chave_ted,
                chave_ted=t.chave_ted,
                descricao=(
                    f"{rotulo}: início da vigência ({_data_br(t.inicio_vigencia)}) é posterior ao "
                    f"fim ({_data_br(t.fim_vigencia)}). Cadastro inconsistente na origem."
                ),
            ))
        if not (t.ug_descentralizadora or "").strip():
            alertas.append(Alerta(
                tipo=TIPO_TED_SEM_UG_DESCENTRALIZADORA, gravidade="media", documento=t.chave_ted,
                chave_ted=t.chave_ted,
                descricao=f"{rotulo}: UG descentralizadora ausente no cadastro.",
            ))
        if (
            estado_em_execucao(t.estado_atual)
            and t.fim_vigencia is not None
            and hoje > t.fim_vigencia
        ):
            alertas.append(Alerta(
                tipo=TIPO_TED_VENCIDO_EM_EXECUCAO, gravidade="media", documento=t.chave_ted,
                chave_ted=t.chave_ted,
                descricao=(
                    f"{rotulo}: vigência encerrada em {_data_br(t.fim_vigencia)}, mas o estado "
                    f"atual ainda é \"{t.estado_atual}\". Conferir prorrogação ou encerramento."
                ),
            ))

    ultima_movimentacao: dict[str, date] = {}
    for d in documentos:
        if d.data_emissao is not None and d.data_emissao <= hoje:
            atual = ultima_movimentacao.get(d.chave_ted)
            if atual is None or d.data_emissao > atual:
                ultima_movimentacao[d.chave_ted] = d.data_emissao
    for t in sorted(teds, key=lambda x: x.chave_ted):
        if not estado_em_execucao(t.estado_atual):
            continue
        # Sem nenhum documento datado, a referência é o início da vigência: um TED recém-iniciado
        # ainda não é "sem movimentação". Sem documento e sem início, não há como datar: alerta.
        ultima = ultima_movimentacao.get(t.chave_ted)
        referencia = ultima or t.inicio_vigencia
        if referencia is not None and (hoje - referencia).days <= prazo_sem_movimentacao_dias:
            continue
        if ultima is not None:
            detalhe = f"última NC/PF emitida em {_data_br(ultima)}"
        elif referencia is not None:
            detalhe = f"nenhuma NC/PF emitida desde o início da vigência ({_data_br(referencia)})"
        else:
            detalhe = "nenhuma NC/PF emitida e sem data de início da vigência"
        alertas.append(Alerta(
            tipo=TIPO_TED_SEM_MOVIMENTACAO, gravidade="media", documento=t.chave_ted, chave_ted=t.chave_ted,
            descricao=(
                f"TED {t.ted} (SIAFI {t.codigo_siafi}) em execução sem movimentação há mais de "
                f"{prazo_sem_movimentacao_dias} dias: {detalhe}. Movimentação = NC ou PF emitida "
                "(a NE não tem data no banco)."
            ),
        ))

    teds_por_siafi: dict[str, set[str]] = {}
    for t in teds:
        teds_por_siafi.setdefault(t.codigo_siafi, set()).add(t.ted)
    for siafi, numeros in sorted(teds_por_siafi.items()):
        if len(numeros) > 1:
            alertas.append(Alerta(
                tipo=TIPO_SIAFI_EM_MULTIPLOS_TEDS, gravidade="alta", documento=siafi,
                descricao=(
                    f"Código SIAFI {siafi} associado a {len(numeros)} TEDs diferentes: "
                    f"{', '.join(sorted(numeros))}. Sem justificativa registrada."
                ),
            ))

    for d in sorted(documentos, key=lambda x: (x.tipo_documento, x.chave_documento)):
        t = por_chave.get(d.chave_ted)
        if t is None or d.data_emissao is None:
            continue
        if t.inicio_vigencia and d.data_emissao < t.inicio_vigencia:
            posicao, limite = "antes do início", t.inicio_vigencia
        elif t.fim_vigencia and d.data_emissao > t.fim_vigencia:
            posicao, limite = "depois do fim", t.fim_vigencia
        else:
            continue
        alertas.append(Alerta(
            tipo=TIPO_DOCUMENTO_FORA_DA_VIGENCIA, gravidade="media",
            documento=f"{d.tipo_documento}|{d.chave_documento}", chave_ted=d.chave_ted,
            descricao=(
                f"{d.tipo_documento} {d.numero} do TED {t.ted} emitida em {_data_br(d.data_emissao)}, "
                f"{posicao} da vigência ({_data_br(limite)}). Pode ser legítimo em casos "
                "específicos — registrar justificativa se for o caso."
            ),
        ))
    return alertas


def _data_ou_none(texto: str | None) -> date | None:
    if not texto:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def _carregar_cadastro(conn: sqlite3.Connection) -> tuple[list[TedCadastro], list[DocumentoDatado]]:
    teds = [
        TedCadastro(chave_ted, ted, siafi, estado, _data_ou_none(ini), _data_ou_none(fim), ug)
        for chave_ted, ted, siafi, estado, ini, fim, ug in conn.execute(
            "SELECT chave_ted, ted, codigo_siafi, estado_atual, inicio_vigencia, fim_vigencia, "
            "ug_descentralizadora FROM ted"
        ).fetchall()
    ]
    documentos = [
        DocumentoDatado("NC", chave, numero, chave_ted, _data_ou_none(data))
        for chave, numero, chave_ted, data in conn.execute(
            "SELECT chave_nc_documento, numero_nc, chave_ted, data_emissao FROM documento_nc "
            "WHERE chave_ted IS NOT NULL"
        ).fetchall()
    ] + [
        DocumentoDatado("PF", f"{chave_ted}|{ug}|{numero}", numero, chave_ted, _data_ou_none(data))
        for chave_ted, ug, numero, data in conn.execute(
            "SELECT chave_ted, ug_emitente, numero_pf, data_emissao FROM documento_pf"
        ).fetchall()
    ]
    return teds, documentos


def sincronizar_alertas_cadastrais(
    conn: sqlite3.Connection,
    hoje: date | None = None,
    prazo_sem_movimentacao_dias: int = PRAZO_SEM_MOVIMENTACAO_DIAS,
) -> list[Alerta]:
    """Grava as validações cadastrais/de vigência ainda não sinalizadas. `hoje` e o prazo são
    injetáveis para teste. Nunca fecha alerta existente."""

    teds, documentos = _carregar_cadastro(conn)
    return _gravar_alertas_novos(
        conn,
        gerar_alertas_cadastrais(teds, documentos, hoje or date.today(), prazo_sem_movimentacao_dias),
    )


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
    origem: str = "interface",
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
        status_vinculos_anteriores = dict(
            conn.execute(
                "SELECT chave_ted, status_validacao FROM vinculo_ne WHERE chave_empenho = ?",
                (chave_empenho,),
            ).fetchall()
        )
        alerta_anterior = conn.execute(
            "SELECT status, responsavel, justificativa FROM alerta WHERE id = ?", (alerta_id,)
        ).fetchone()
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
        # Auditoria na MESMA transação da decisão: ou as duas persistem, ou nenhuma.
        status_vinculos_novos = {
            ted: (STATUS_OK if ted == chave_ted_escolhida else STATUS_DESCARTADO) for ted in teds
        }
        registrar_auditoria(
            conn, acao=ACAO_VINCULO_NE_DECIDIDO, entidade=ENTIDADE_VINCULO_NE, entidade_id=chave_empenho,
            valor_anterior={"status_validacao_por_ted": status_vinculos_anteriores},
            valor_novo={"status_validacao_por_ted": status_vinculos_novos, "ted_escolhido": chave_ted_escolhida},
            usuario=responsavel, motivo=justificativa, origem=origem,
        )
        registrar_auditoria(
            conn, acao=ACAO_ALERTA_STATUS_ALTERADO, entidade=ENTIDADE_ALERTA, entidade_id=alerta_id,
            valor_anterior={
                "status": alerta_anterior[0], "responsavel": alerta_anterior[1],
                "justificativa": alerta_anterior[2],
            },
            valor_novo={"status": "resolvido", "responsavel": responsavel, "justificativa": justificativa},
            usuario=responsavel, motivo=justificativa, origem=origem,
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
