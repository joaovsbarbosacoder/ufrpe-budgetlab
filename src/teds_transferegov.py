"""
TEDs do TransfereGov — API de Dados Abertos (`https://api.transferegov.gestao.gov.br/ted/`).

POR QUE UMA ORIGEM SEPARADA (decisão de 08/10/2026)
---------------------------------------------------
Os TEDs do MEC (CAPES, SESu, FNDE…) tramitam no SIMEC e já entram no módulo pelos extratos do SIMEC. Os
TEDs de outros órgãos (MDA, INCRA, MPA, MDS…) tramitam no TransfereGov e hoje ficavam de fora. No
levantamento de 08/10/2026 os dois conjuntos não tinham nenhuma NC em comum. Por isso esta base grava em
tabelas próprias (`tg_*`, ver `src/teds_schema.py`) e não em `ted`/`documento_nc`/`documento_pf`: as
regras de conciliação e de alerta do SIMEC exigem SIAFI e Execução Anual, que estes TEDs não têm, e
acusariam divergências falsas.

O QUE NÃO É FEITO, DE PROPÓSITO
-------------------------------
* Nenhum total de NC ou PF é calculado. A API traz os eventos de NC (`cd_evento`: 300300, 300302,
  300306, 300309…) e a situação contábil da TRF (TRF003, TRF004, TRF027…) sem dizer o que significam, e
  só o 300302 aparece como "estorno" no texto das próprias NCs. Somar exigiria presumir o sinal de cada
  código (regra permanente: não presumir regra contábil). Os valores ficam guardados como vieram, sem
  sinal, e a tela mostra o código ao lado.
* Nenhum vínculo TED → NE é criado. A API não traz NE. `indicios_ne` cruza a CÉLULA dos eventos de NC
  (exercício, PTRES, fonte, natureza, PI) com as células das NEs da Execução Mensal (`ne_celula`) e
  devolve só um indício para conferência — mesma regra do módulo: coincidência de célula nunca cria
  vínculo.
* O valor do plano de ação (`vl_total_plano_acao`) é informativo: no levantamento ele não era teto das
  NCs (aditivos e valores por exercício), então não é comparado com nada.

IDEMPOTÊNCIA E RASTREABILIDADE
------------------------------
A resposta da API é serializada num JSON canônico (tabelas e linhas ordenadas) cujo SHA-256 é o
`hash_arquivo` do lote: consultar de novo sem mudança na API é um no-op. O JSON inteiro fica em
`tg_extracao_bruta` (append-only) e cada linha gravada leva a linha da API em `linha_origem`. Linhas
conhecidas são atualizadas no lugar (o gatilho de versões guarda a anterior, então o lote pode ser
revertido em Importações); linha que a API deixe de trazer permanece como estava — a sincronização nunca
apaga.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

import pandas as pd

from src.teds_lotes import ResultadoImportacaoLote, ResumoControle, _lote_ja_importado, _registrar_lote
from src.teds_normalizacao import texto_para_valor, valor_para_texto

URL_API = "https://api.transferegov.gestao.gov.br/ted"
TIPO_TRANSFEREGOV = "transferegov_ted"

#: Identificação da UFRPE na API: sigla da unidade executora no plano de ação e UG favorecida das NCs/PFs
#: (153165, a mesma das NEs da Execução Mensal, ex.: `153165152392024NE000001`).
SIGLA_UFRPE = "UFRPE"
UG_UFRPE = "153165"

TAMANHO_PAGINA = 1000  # limite de linhas por resposta da API (confirmado: 206 com content-range 0-999)
_IDS_POR_CONSULTA = 80  # ids por filtro `in.(...)`, para a URL não crescer demais

#: Ordenação estável por tabela: paginação por `offset` sem `order` pode repetir ou pular linhas.
_ORDEM = {
    "plano_acao": "id_plano_acao.asc",
    "programa": "id_programa.asc",
    "termo_execucao": "id_termo.asc",
    "nota_credito": "id_nota.asc",
    "evento": "id_nota.asc,cd_evento.asc,cd_ptres_evento.asc,cd_fonte_recurso_evento.asc,"
              "cd_plano_interno_evento.asc,codigo_natureza.asc,vl_evento.asc",
    "programacao_financeira": "id_programacao.asc",
    "trf": "id_programacao.asc,cd_vinculacao_trf.asc,cd_fonte_recurso_trf.asc,cd_categoria_gasto_trf.asc,"
           "cd_situacao_contabil_trf.asc,vl_valor_trf.asc",
}

#: (tabela, parâmetros da consulta) -> linhas de UMA página. Injetável para os testes não usarem rede.
BuscadorPagina = Callable[[str, dict[str, str]], list[dict[str, Any]]]


class ErroConsultaTransfereGov(RuntimeError):
    """A API não respondeu ou respondeu algo que não é a lista de linhas esperada."""


def buscar_pagina_http(tabela: str, parametros: dict[str, str], *, timeout: float = 120) -> list[dict[str, Any]]:
    url = f"{URL_API}/{tabela}?{urllib.parse.urlencode(parametros, safe='(),.')}"
    requisicao = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            dados = json.loads(resposta.read(), parse_float=Decimal)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as erro:
        raise ErroConsultaTransfereGov(f"Falha ao consultar {tabela} no TransfereGov: {erro}") from erro
    if not isinstance(dados, list):
        raise ErroConsultaTransfereGov(f"Resposta inesperada da API para {tabela}: {str(dados)[:200]}")
    return dados


def _buscar_tudo(buscar: BuscadorPagina, tabela: str, filtros: dict[str, str]) -> list[dict[str, Any]]:
    linhas: list[dict[str, Any]] = []
    deslocamento = 0
    while True:
        pagina = buscar(tabela, {**filtros, "order": _ORDEM[tabela], "limit": str(TAMANHO_PAGINA),
                                 "offset": str(deslocamento)})
        linhas.extend(pagina)
        if len(pagina) < TAMANHO_PAGINA:
            return linhas
        deslocamento += TAMANHO_PAGINA


def _buscar_por_ids(buscar: BuscadorPagina, tabela: str, campo: str, ids: set[Any]) -> list[dict[str, Any]]:
    ordenados = sorted({str(i) for i in ids if i is not None}, key=lambda v: (len(v), v))
    linhas: list[dict[str, Any]] = []
    for inicio in range(0, len(ordenados), _IDS_POR_CONSULTA):
        lote = ordenados[inicio:inicio + _IDS_POR_CONSULTA]
        linhas.extend(_buscar_tudo(buscar, tabela, {campo: f"in.({','.join(lote)})"}))
    return linhas


def _sem_repetidas(linhas: list[dict[str, Any]], campo_id: str) -> list[dict[str, Any]]:
    """A mesma NC/PF pode vir pelas duas consultas (plano da UFRPE e UG favorecida): fica uma vez."""

    vistas: dict[Any, dict[str, Any]] = {}
    sem_id = []
    for linha in linhas:
        chave = linha.get(campo_id)
        if chave is None:
            sem_id.append(linha)
        else:
            vistas.setdefault(chave, linha)
    return list(vistas.values()) + sem_id


@dataclass(frozen=True)
class ExtracaoTransfereGov:
    """Resposta da API já filtrada para a UFRPE: `tabelas[nome da tabela da API] = linhas`."""

    tabelas: dict[str, list[dict[str, Any]]]
    consultado_em: str


def baixar_extracao(buscar: BuscadorPagina | None = None) -> ExtracaoTransfereGov:
    """Consulta a API: planos de ação em que a UFRPE é executora e, a partir deles, programas, termos,
    NCs (do plano ou com a UFRPE como UG favorecida), eventos das NCs, PFs (idem) e linhas TRF."""

    buscar = buscar or buscar_pagina_http
    planos = _buscar_tudo(buscar, "plano_acao", {"sigla_unidade_responsavel_execucao": f"eq.{SIGLA_UFRPE}"})
    ids_plano = {p.get("id_plano_acao") for p in planos}
    programas = _buscar_por_ids(buscar, "programa", "id_programa", {p.get("id_programa") for p in planos})
    termos = _buscar_por_ids(buscar, "termo_execucao", "id_plano_acao", ids_plano)
    notas = _sem_repetidas(
        _buscar_por_ids(buscar, "nota_credito", "id_plano_acao", ids_plano)
        + _buscar_tudo(buscar, "nota_credito", {"cd_ug_favorecida_nota": f"eq.{UG_UFRPE}"}),
        "id_nota",
    )
    eventos = _buscar_por_ids(buscar, "evento", "id_nota", {n.get("id_nota") for n in notas})
    pfs = _sem_repetidas(
        _buscar_por_ids(buscar, "programacao_financeira", "id_plano_acao", ids_plano)
        + _buscar_tudo(buscar, "programacao_financeira", {"ug_favorecida_programacao": f"eq.{UG_UFRPE}"}),
        "id_programacao",
    )
    trfs = _buscar_por_ids(buscar, "trf", "id_programacao", {p.get("id_programacao") for p in pfs})
    return ExtracaoTransfereGov(
        tabelas={
            "plano_acao": planos, "programa": programas, "termo_execucao": termos, "nota_credito": notas,
            "evento": eventos, "programacao_financeira": pfs, "trf": trfs,
        },
        consultado_em=datetime.now(timezone.utc).isoformat(),
    )


def serializar_extracao(extracao: ExtracaoTransfereGov) -> str:
    """JSON canônico (tabelas e linhas ordenadas, chaves ordenadas): a mesma resposta da API dá sempre o
    mesmo texto, independentemente da ordem em que as linhas chegaram. `consultado_em` fica de fora — é
    a hora da consulta, não conteúdo da base."""

    def canonica(linha: dict[str, Any]) -> str:
        return json.dumps(linha, sort_keys=True, ensure_ascii=False, default=str)

    return json.dumps(
        {tabela: [json.loads(t) for t in sorted(canonica(l) for l in linhas)]
         for tabela, linhas in sorted(extracao.tabelas.items())},
        sort_keys=True, ensure_ascii=False, default=str,
    )


# --------------------------------------------------------------------------------------
# Normalização das linhas da API
# --------------------------------------------------------------------------------------

def _codigo(valor: Any) -> str | None:
    """Identificador como texto (zeros à esquerda preservados); vazio vira nulo, nunca zero."""

    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _valor(valor: Any) -> str | None:
    """Valor monetário como texto decimal exato; nulo continua nulo (nunca vira zero). Um valor com mais
    de duas casas é guardado inteiro, sem arredondar."""

    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    numero = Decimal(str(valor))
    duas_casas = numero.quantize(Decimal("0.01"))
    return valor_para_texto(numero) if duas_casas == numero else str(numero)


_DATA_ISO = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _data(valor: Any) -> str | None:
    """Parte da data (AAAA-MM-DD) de uma data ou data-hora ISO da API; o valor completo fica em
    `linha_origem`."""

    if valor is None:
        return None
    encontrado = _DATA_ISO.match(str(valor))
    return encontrado.group(1) if encontrado else None


def _json(conteudo: Any) -> str:
    return json.dumps(conteudo, sort_keys=True, ensure_ascii=False, default=str)


@dataclass(frozen=True)
class LinhaRejeitadaTG:
    tabela: str
    motivo: str
    linha: dict[str, Any]


@dataclass
class LeituraTransfereGov:
    teds: list[dict[str, Any]] = field(default_factory=list)
    notas: list[dict[str, Any]] = field(default_factory=list)
    eventos: list[dict[str, Any]] = field(default_factory=list)
    pfs: list[dict[str, Any]] = field(default_factory=list)
    trfs: list[dict[str, Any]] = field(default_factory=list)
    rejeitadas: list[LinhaRejeitadaTG] = field(default_factory=list)
    linhas_lidas: int = 0

    @property
    def total_registros(self) -> int:
        return len(self.teds) + len(self.notas) + len(self.eventos) + len(self.pfs) + len(self.trfs)


def _chave_por_conteudo(partes: list[str | None], ocorrencias: dict[str, int]) -> str:
    """Chave de uma linha sem identificador na API: o conteúdo + o número da ocorrência (`#1`, `#2`…)."""

    base = "|".join(p or "" for p in partes)
    ocorrencias[base] = ocorrencias.get(base, 0) + 1
    return f"{base}#{ocorrencias[base]}"


def montar_registros(extracao: ExtracaoTransfereGov) -> LeituraTransfereGov:
    """Converte a resposta da API nas linhas das tabelas `tg_*`. Pura (não grava nada)."""

    t = extracao.tabelas
    leitura = LeituraTransfereGov(linhas_lidas=sum(len(linhas) for linhas in t.values()))
    programas = {_codigo(p.get("id_programa")): p for p in t.get("programa", [])}
    # Normalmente um termo por plano. Se vierem mais, o de maior `id_termo` (o mais recente) alimenta as
    # colunas e todos ficam em `linha_origem` — nenhum é descartado em silêncio.
    termos_por_plano: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for termo in t.get("termo_execucao", []):
        termos_por_plano[_codigo(termo.get("id_plano_acao"))].append(termo)
    termos = {
        plano: max(lista, key=lambda x: (len(str(x.get("id_termo") or "")), str(x.get("id_termo") or "")))
        for plano, lista in termos_por_plano.items()
    }

    for plano in t.get("plano_acao", []):
        id_plano = _codigo(plano.get("id_plano_acao"))
        if id_plano is None:
            leitura.rejeitadas.append(LinhaRejeitadaTG("plano_acao", "plano de ação sem id_plano_acao", plano))
            continue
        programa = programas.get(_codigo(plano.get("id_programa"))) or {}
        termo = termos.get(id_plano) or {}
        sq, aa = _codigo(plano.get("sq_instrumento")), _codigo(plano.get("aa_instrumento"))
        leitura.teds.append({
            "id_plano_acao": id_plano,
            "instrumento": f"{sq}/{aa}" if sq and aa else sq,
            "sq_instrumento": sq,
            "aa_instrumento": aa,
            "id_programa": _codigo(plano.get("id_programa")),
            "codigo_programa": _codigo(programa.get("tx_codigo_programa")),
            "nome_programa": programa.get("tx_nome_programa"),
            "sigla_concedente": _codigo(programa.get("sigla_unidade_descentralizadora")),
            "concedente": programa.get("unidade_descentralizadora"),
            "sigla_executora": _codigo(plano.get("sigla_unidade_responsavel_execucao")),
            "executora": plano.get("unidade_responsavel_execucao"),
            "objeto": plano.get("tx_objeto_plano_acao"),
            "valor_plano": _valor(plano.get("vl_total_plano_acao")),
            "inicio_vigencia": _data(plano.get("dt_inicio_vigencia")),
            "fim_vigencia": _data(plano.get("dt_fim_vigencia")),
            "situacao_plano": _codigo(plano.get("tx_situacao_plano_acao")),
            "id_termo": _codigo(termo.get("id_termo")),
            "situacao_termo": _codigo(termo.get("tx_situacao_termo")),
            "processo_sei": _codigo(termo.get("tx_num_processo_sei")),
            "numero_ns": _codigo(termo.get("tx_numero_ns_termo")),
            "data_assinatura": _data(termo.get("dt_assinatura_termo")),
            "data_efetivacao": _data(termo.get("dt_efetivacao_termo")),
            "linha_origem": _json({
                "plano_acao": plano, "programa": programa or None,
                "termo_execucao": sorted(termos_por_plano.get(id_plano, []), key=_json) or None,
            }),
        })

    for nota in t.get("nota_credito", []):
        id_nota = _codigo(nota.get("id_nota"))
        if id_nota is None:
            leitura.rejeitadas.append(LinhaRejeitadaTG("nota_credito", "NC sem id_nota", nota))
            continue
        leitura.notas.append({
            "id_nota": id_nota,
            "id_plano_acao": _codigo(nota.get("id_plano_acao")),
            "numero_nc": _codigo(nota.get("tx_numero_nota")),
            "minuta": _codigo(nota.get("tx_minuta_nota")),
            "data_emissao": _data(nota.get("dt_emissao_nota")),
            "ug_emitente": _codigo(nota.get("cd_ug_emitente_nota")),
            "gestao_emitente": _codigo(nota.get("cd_gestao_emitente_nota")),
            "ug_favorecida": _codigo(nota.get("cd_ug_favorecida_nota")),
            "gestao_favorecida": _codigo(nota.get("cd_gestao_favorecida_nota")),
            "situacao": _codigo(nota.get("tx_situacao_nota")),
            "observacao": nota.get("tx_observacao_nota"),
            "linha_origem": _json(nota),
        })

    ocorrencias: dict[str, int] = {}
    for evento in sorted(t.get("evento", []), key=_json):
        id_nota = _codigo(evento.get("id_nota"))
        if id_nota is None:
            leitura.rejeitadas.append(LinhaRejeitadaTG("evento", "evento sem id_nota", evento))
            continue
        registro = {
            "id_nota": id_nota,
            "cd_evento": _codigo(evento.get("cd_evento")),
            "ptres": _codigo(evento.get("cd_ptres_evento")),
            "fonte_detalhada": _codigo(evento.get("cd_fonte_recurso_evento")),
            "pi": _codigo(evento.get("cd_plano_interno_evento")),
            "natureza": _codigo(evento.get("codigo_natureza")),
            "descricao_natureza": evento.get("descricao_natureza"),
            "ug_responsavel": _codigo(evento.get("cd_ug_responsavel_evento")),
            "esfera": evento.get("nome_esfera_orcamentaria"),
            "valor": _valor(evento.get("vl_evento")),
            "linha_origem": _json(evento),
        }
        registro["chave_evento"] = _chave_por_conteudo(
            [id_nota, registro["cd_evento"], registro["ptres"], registro["fonte_detalhada"], registro["pi"],
             registro["natureza"], registro["ug_responsavel"], registro["valor"]],
            ocorrencias,
        )
        leitura.eventos.append(registro)

    for pf in t.get("programacao_financeira", []):
        id_pf = _codigo(pf.get("id_programacao"))
        if id_pf is None:
            leitura.rejeitadas.append(LinhaRejeitadaTG("programacao_financeira", "PF sem id_programacao", pf))
            continue
        leitura.pfs.append({
            "id_programacao": id_pf,
            "id_plano_acao": _codigo(pf.get("id_plano_acao")),
            "tipo": _codigo(pf.get("tp_pf_tipo_programacao")),
            "numero_pf": _codigo(pf.get("tx_numero_programacao")),
            "minuta": _codigo(pf.get("tx_minuta_programacao")),
            "situacao": _codigo(pf.get("tx_situacao_programacao")),
            "ug_emitente": _codigo(pf.get("ug_emitente_programacao")),
            "ug_favorecida": _codigo(pf.get("ug_favorecida_programacao")),
            "data_recebimento": _data(pf.get("dh_recebimento_programacao")),
            "observacao": pf.get("tx_observacao_programacao"),
            "linha_origem": _json(pf),
        })

    ocorrencias = {}
    for trf in sorted(t.get("trf", []), key=_json):
        id_pf = _codigo(trf.get("id_programacao"))
        if id_pf is None:
            leitura.rejeitadas.append(LinhaRejeitadaTG("trf", "linha TRF sem id_programacao", trf))
            continue
        registro = {
            "id_programacao": id_pf,
            "vinculacao": _codigo(trf.get("cd_vinculacao_trf")),
            "fonte": _codigo(trf.get("cd_fonte_recurso_trf")),
            "categoria_gasto": _codigo(trf.get("cd_categoria_gasto_trf")),
            "situacao_contabil": _codigo(trf.get("cd_situacao_contabil_trf")),
            "valor": _valor(trf.get("vl_valor_trf")),
            "linha_origem": _json(trf),
        }
        registro["chave_trf"] = _chave_por_conteudo(
            [id_pf, registro["vinculacao"], registro["fonte"], registro["categoria_gasto"],
             registro["situacao_contabil"], registro["valor"]],
            ocorrencias,
        )
        leitura.trfs.append(registro)

    return leitura


# --------------------------------------------------------------------------------------
# Gravação
# --------------------------------------------------------------------------------------

_COLUNAS = {
    "tg_ted": ("id_plano_acao", "instrumento", "sq_instrumento", "aa_instrumento", "id_programa", "codigo_programa",
               "nome_programa", "sigla_concedente", "concedente", "sigla_executora", "executora", "objeto",
               "valor_plano", "inicio_vigencia", "fim_vigencia", "situacao_plano", "id_termo", "situacao_termo",
               "processo_sei", "numero_ns", "data_assinatura", "data_efetivacao", "linha_origem"),
    "tg_nota_credito": ("id_nota", "id_plano_acao", "numero_nc", "minuta", "data_emissao", "ug_emitente",
                        "gestao_emitente", "ug_favorecida", "gestao_favorecida", "situacao", "observacao",
                        "linha_origem"),
    "tg_nc_evento": ("chave_evento", "id_nota", "cd_evento", "ptres", "fonte_detalhada", "pi", "natureza",
                     "descricao_natureza", "ug_responsavel", "esfera", "valor", "linha_origem"),
    "tg_programacao_financeira": ("id_programacao", "id_plano_acao", "tipo", "numero_pf", "minuta", "situacao",
                                  "ug_emitente", "ug_favorecida", "data_recebimento", "observacao", "linha_origem"),
    "tg_pf_trf": ("chave_trf", "id_programacao", "vinculacao", "fonte", "categoria_gasto", "situacao_contabil",
                  "valor", "linha_origem"),
}


def _upsert(conn: sqlite3.Connection, tabela: str, registros: list[dict[str, Any]], batch_id: int) -> None:
    colunas = _COLUNAS[tabela] + ("import_batch_id",)
    chave = colunas[0]
    atualizar = ", ".join(f"{c} = excluded.{c}" for c in colunas[1:])
    conn.executemany(
        f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({', '.join('?' * len(colunas))}) "
        f"ON CONFLICT({chave}) DO UPDATE SET {atualizar}",
        [tuple(r[c] for c in colunas[:-1]) + (batch_id,) for r in registros],
    )


def sincronizar_transferegov(conn: sqlite3.Connection, extracao: ExtracaoTransfereGov) -> ResultadoImportacaoLote:
    """Grava a extração num lote `transferegov_ted` (idempotente pelo SHA-256 do JSON canônico). Tudo numa
    transação: ou o lote entra inteiro, ou nada muda. Não dispara alertas — nenhuma regra de alerta usa
    estas tabelas."""

    conteudo = serializar_extracao(extracao)
    hash_conteudo = hashlib.sha256(conteudo.encode("utf-8")).hexdigest()
    existente = _lote_ja_importado(conn, TIPO_TRANSFEREGOV, hash_conteudo)
    if existente is not None:
        return ResultadoImportacaoLote(existente, ja_importado=True, inseridos=0)

    leitura = montar_registros(extracao)
    resumo = ResumoControle(  # sem somas: o sinal dos eventos/TRF não é conhecido (docstring do módulo)
        quantidade_linhas_lidas=leitura.linhas_lidas, quantidade_rejeitadas=len(leitura.rejeitadas),
        quantidade_com_aviso=0,
    )
    try:
        batch_id = _registrar_lote(
            conn, TIPO_TRANSFEREGOV, f"API TransfereGov — TEDs da {SIGLA_UFRPE}", hash_conteudo,
            leitura.total_registros, resumo,
        )
        conn.execute(
            "INSERT INTO tg_extracao_bruta (import_batch_id, consultado_em, conteudo) VALUES (?, ?, ?)",
            (batch_id, extracao.consultado_em, conteudo),
        )
        _upsert(conn, "tg_ted", leitura.teds, batch_id)
        _upsert(conn, "tg_nota_credito", leitura.notas, batch_id)
        _upsert(conn, "tg_nc_evento", leitura.eventos, batch_id)
        _upsert(conn, "tg_programacao_financeira", leitura.pfs, batch_id)
        _upsert(conn, "tg_pf_trf", leitura.trfs, batch_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return ResultadoImportacaoLote(batch_id, False, leitura.total_registros, list(leitura.rejeitadas))


def ultimo_lote_transferegov(conn: sqlite3.Connection) -> tuple[int, str] | None:
    """(id, data da importação) do lote ativo mais recente, ou `None` se nunca sincronizou."""

    return conn.execute(
        "SELECT id, data_importacao FROM import_batch WHERE tipo_relatorio = ? AND status = 'ok' "
        "ORDER BY id DESC LIMIT 1",
        (TIPO_TRANSFEREGOV,),
    ).fetchone()


# --------------------------------------------------------------------------------------
# Consultas para as telas
# --------------------------------------------------------------------------------------

def carregar_teds_transferegov(conn: sqlite3.Connection) -> pd.DataFrame:
    """Uma linha por plano de ação, com a quantidade de NCs e PFs (contagem de documentos, não soma). Campo
    vazio fica `None` (não `NaN`), como no banco."""

    teds = pd.read_sql_query(
        """
        SELECT t.*,
               (SELECT COUNT(*) FROM tg_nota_credito n WHERE n.id_plano_acao = t.id_plano_acao) AS qtd_nc,
               (SELECT COUNT(*) FROM tg_programacao_financeira p WHERE p.id_plano_acao = t.id_plano_acao) AS qtd_pf
        FROM tg_ted t
        ORDER BY t.aa_instrumento IS NULL, t.aa_instrumento, t.sq_instrumento, CAST(t.id_plano_acao AS INTEGER)
        """,
        conn,
    )
    return teds.astype(object).where(teds.notna(), None)


def notas_do_plano(conn: sqlite3.Connection, id_plano_acao: str) -> list[dict[str, Any]]:
    """NCs do plano com os seus eventos (`eventos`: lista de dicionários, valor sem sinal)."""

    notas = [
        dict(zip(("id_nota", "numero_nc", "data_emissao", "ug_emitente", "ug_favorecida", "situacao", "observacao"), linha))
        for linha in conn.execute(
            "SELECT id_nota, numero_nc, data_emissao, ug_emitente, ug_favorecida, situacao, observacao "
            "FROM tg_nota_credito WHERE id_plano_acao = ? ORDER BY data_emissao, numero_nc",
            (id_plano_acao,),
        )
    ]
    for nota in notas:
        nota["eventos"] = [
            dict(zip(("cd_evento", "ptres", "fonte_detalhada", "natureza", "pi", "valor"), linha))
            for linha in conn.execute(
                "SELECT cd_evento, ptres, fonte_detalhada, natureza, pi, valor FROM tg_nc_evento "
                "WHERE id_nota = ? ORDER BY chave_evento",
                (nota["id_nota"],),
            )
        ]
    return notas


def pfs_do_plano(conn: sqlite3.Connection, id_plano_acao: str) -> list[dict[str, Any]]:
    """PFs do plano com as suas linhas TRF (`trfs`, valor sem sinal)."""

    pfs = [
        dict(zip(("id_programacao", "numero_pf", "data_recebimento", "ug_emitente", "ug_favorecida", "situacao", "observacao"), linha))
        for linha in conn.execute(
            "SELECT id_programacao, numero_pf, data_recebimento, ug_emitente, ug_favorecida, situacao, observacao "
            "FROM tg_programacao_financeira WHERE id_plano_acao = ? ORDER BY data_recebimento, numero_pf",
            (id_plano_acao,),
        )
    ]
    for pf in pfs:
        pf["trfs"] = [
            dict(zip(("situacao_contabil", "fonte", "vinculacao", "categoria_gasto", "valor"), linha))
            for linha in conn.execute(
                "SELECT situacao_contabil, fonte, vinculacao, categoria_gasto, valor FROM tg_pf_trf "
                "WHERE id_programacao = ? ORDER BY chave_trf",
                (pf["id_programacao"],),
            )
        ]
    return pfs


@dataclass(frozen=True)
class IndicioNE:
    """NE da Execução Mensal cuja célula coincide com a de um evento de NC do TransfereGov. Indício para
    conferência, NUNCA vínculo. `empenhado`/`liquidado`/`pago` são o acumulado da NE no Tesouro Gerencial
    (`None` = NE sem linha em `execucao_tg`, "sem dado", nunca zero); `teds_simec` lista os TEDs do SIMEC
    a que a NE já está vinculada."""

    numero_ne: str
    ids_plano_acao: tuple[str, ...]
    instrumentos: tuple[str, ...]
    numeros_nc: tuple[str, ...]
    ptres: str
    fonte_detalhada: str
    natureza: str
    pi: str
    empenhado: Decimal | None
    liquidado: Decimal | None
    pago: Decimal | None
    teds_simec: tuple[str, ...]


_ANO_NC = re.compile(r"^(\d{4})NC")


def _ano_da_nc(numero_nc: str | None, data_emissao: str | None) -> str | None:
    encontrado = _ANO_NC.match(numero_nc or "")
    if encontrado:
        return encontrado.group(1)
    return data_emissao[:4] if data_emissao else None


def indicios_ne(conn: sqlite3.Connection, id_plano_acao: str | None = None) -> list[IndicioNE]:
    """Cruza (exercício, PTRES, fonte detalhada, natureza, PI) dos eventos das NCs com a UFRPE como UG
    favorecida contra `ne_celula`. O exercício da NC é o do número (`2024NC…`) ou, sem ele, o da emissão; o
    da NE é o do número. Campos comparados como texto, sem espaços nas pontas. Filtra por plano quando
    `id_plano_acao` é dado."""

    celulas: dict[tuple[str, ...], dict[str, set[str]]] = defaultdict(lambda: {"planos": set(), "instrumentos": set(), "ncs": set()})
    consulta = (
        "SELECT n.id_plano_acao, t.instrumento, n.numero_nc, n.data_emissao, e.ptres, e.fonte_detalhada, e.natureza, e.pi "
        "FROM tg_nc_evento e JOIN tg_nota_credito n ON n.id_nota = e.id_nota "
        "LEFT JOIN tg_ted t ON t.id_plano_acao = n.id_plano_acao WHERE n.ug_favorecida = ?"
    )
    parametros: list[Any] = [UG_UFRPE]
    if id_plano_acao is not None:
        consulta += " AND n.id_plano_acao = ?"
        parametros.append(id_plano_acao)
    for plano, instrumento, numero_nc, data_emissao, ptres, fonte, natureza, pi in conn.execute(consulta, parametros):
        ano = _ano_da_nc(numero_nc, data_emissao)
        if ano is None or not all((ptres, fonte, natureza)):
            continue
        chave = (ano, ptres.strip(), fonte.strip(), natureza.strip(), (pi or "").strip())
        celulas[chave]["planos"].add(plano or "")
        celulas[chave]["instrumentos"].add(instrumento or f"plano {plano}")
        if numero_nc:
            celulas[chave]["ncs"].add(numero_nc)
    if not celulas:
        return []

    encontrados: list[tuple[str, tuple[str, ...]]] = []
    for numero_ne, ptres, fonte, natureza, pi in conn.execute(
        "SELECT numero_ne, ptres, fonte_detalhada, natureza, pi FROM ne_celula ORDER BY numero_ne"
    ):
        chave = (numero_ne[:4], (ptres or "").strip(), (fonte or "").strip(), (natureza or "").strip(), (pi or "").strip())
        if chave in celulas:
            encontrados.append((numero_ne, chave))
    if not encontrados:
        return []

    execucao: dict[str, list[Decimal | None]] = {}
    for numero_ne, empenhado, liquidado, pago in conn.execute(
        "SELECT numero_completo_ne, empenhado, liquidado, pago FROM execucao_tg"
    ):
        totais = execucao.setdefault(numero_ne, [None, None, None])
        for i, valor in enumerate((empenhado, liquidado, pago)):
            if valor is not None:
                totais[i] = (totais[i] or Decimal("0")) + texto_para_valor(valor)
    vinculos: dict[str, set[str]] = defaultdict(set)
    for numero_ne, chave_ted in conn.execute("SELECT numero_ne, chave_ted FROM vinculo_ne"):
        vinculos[numero_ne].add(chave_ted)

    indicios = []
    for numero_ne, chave in encontrados:
        info = celulas[chave]
        empenhado, liquidado, pago = execucao.get(numero_ne, [None, None, None])
        indicios.append(IndicioNE(
            numero_ne=numero_ne,
            ids_plano_acao=tuple(sorted(info["planos"])),
            instrumentos=tuple(sorted(info["instrumentos"])),
            numeros_nc=tuple(sorted(info["ncs"])),
            ptres=chave[1], fonte_detalhada=chave[2], natureza=chave[3], pi=chave[4],
            empenhado=empenhado, liquidado=liquidado, pago=pago,
            teds_simec=tuple(sorted(vinculos.get(numero_ne, ()))),
        ))
    return indicios
