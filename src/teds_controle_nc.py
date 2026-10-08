"""
Leitura e conferência EM MEMÓRIA da planilha manual de controle de NCs (sem Streamlit).

Decisão (08/10/2026, spec `2026-10-08-teds-alertas-e-controle-nc-design.md`, §2 e §5): a planilha
"CONTROLE DESC.CREDITOS" é uma ferramenta de consulta para sanear dúvidas e pendências, NÃO uma
fonte contínua. Por isso nada daqui grava no banco (sem tabela, lote ou coluna): `ler_controle_nc`
só interpreta bytes e `conferir_controle` só LÊ `documento_nc`, `ted` e `execucao_anual`. O único
registro persistente possível é a resolução de um alerta feita pelo usuário na página, fora deste
módulo. A planilha também não alimenta as regras de alerta.

Nada é corrigido na leitura: códigos ficam como texto (zeros à esquerda preservados), "-" vira
nulo, e linha ou aba que não dá para interpretar é listada com o motivo em vez de sumir.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from openpyxl import Workbook, load_workbook

from src.teds_normalizacao import (
    normalizar_codigo,
    normalizar_espacos,
    normalizar_nome_coluna,
    parse_valor_brl,
    texto_para_valor,
)

_TOLERANCIA = Decimal("0.01")
_LINHAS_DE_CABECALHO = 6

SITUACAO_CONFERE = "confere"
SITUACAO_DIVERGE = "diverge"
SITUACAO_AMBIGUA = "ambigua"
SITUACAO_SEM_PLANILHA = "sem_planilha"

# Apelidos de coluna (já normalizados por `normalizar_nome_coluna`) -> campo interno. Os layouts
# mudam por ano; "ted n. transferencia" (2014-2017) é uma coluna só que alimenta os dois campos.
_APELIDOS: dict[str, str] = {
    "nc": "nc",
    "data": "data",
    "ug emitente": "ug_emitente",
    "nome orgao": "orgao",
    "unidade orcamentaria": "orgao",
    "oficio": "oficio",
    "fonte": "fonte",
    "ptres": "ptres",
    "nd": "natureza",
    "pi": "pi",
    "ted": "ted",
    "n. transferencia": "transferencia",
    "ted n. transferencia": "ted_transferencia",
    "valor": "valor",
    "valor recebido": "valor",
    "processo": "processo",
    "processo sipac": "processo",
    "observacao": "observacao",
}

_CAMPOS_CODIGO = ("nc", "ug_emitente", "fonte", "ptres", "natureza", "pi", "ted", "transferencia")
_CAMPOS_TEXTO = ("orgao", "oficio", "processo", "observacao")
# Campos que a linha de continuação (NC em branco) herda da linha de cima, na mesma aba.
_HERDADOS = ("nc", "data", "ug_emitente", "orgao", "oficio", "fonte", "ted", "transferencia",
             "processo")


# --------------------------------------------------------------------------------------
# Estruturas
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class LinhaControleNc:
    aba: str
    linha_origem: int
    nc: str | None
    data: date | None
    ug_emitente: str | None
    orgao: str | None
    oficio: str | None
    fonte: str | None
    ptres: str | None
    natureza: str | None
    pi: str | None
    ted: str | None
    transferencia: str | None
    valor: Decimal
    processo: str | None
    observacao: str | None


@dataclass
class ResultadoLeituraControleNc:
    linhas: list[LinhaControleNc] = field(default_factory=list)
    rejeitadas: list[tuple[str, int, str]] = field(default_factory=list)   # (aba, linha, motivo)
    abas_ignoradas: list[tuple[str, str]] = field(default_factory=list)    # (aba, motivo)


@dataclass(frozen=True)
class ConferenciaNc:
    chave_nc_documento: str
    chave_ted: str | None
    numero_nc: str
    situacao: str  # "confere" | "diverge" | "ambigua" | "sem_planilha"
    valor_simec: Decimal | None
    valor_planilha: Decimal | None
    ug_simec: str | None
    ug_planilha: str | None


@dataclass
class ConferenciaControle:
    por_nc: list[ConferenciaNc]
    nc_anterior_consolidado: dict[str, list[LinhaControleNc]]  # chave_ted -> linhas
    sem_ted: list[LinhaControleNc]
    leitura: ResultadoLeituraControleNc


# --------------------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------------------

def _vazio(valor: object) -> bool:
    texto = normalizar_espacos(valor)
    return texto in ("", "-")


def _texto(valor: object) -> str | None:
    return None if _vazio(valor) else normalizar_espacos(valor)


def _codigo(valor: object) -> str | None:
    return None if _vazio(valor) else (normalizar_codigo(valor) or None)


def _data(valor: object) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = normalizar_espacos(valor)
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _mapear_cabecalho(linha: tuple) -> dict[str, int]:
    colunas: dict[str, int] = {}
    for indice, celula in enumerate(linha):
        campo = _APELIDOS.get(normalizar_nome_coluna(celula))
        if campo and campo not in colunas:
            colunas[campo] = indice
    return colunas


def _achar_cabecalho(linhas: list[tuple]) -> tuple[int, dict[str, int]] | None:
    for posicao, linha in enumerate(linhas[:_LINHAS_DE_CABECALHO]):
        if any(normalizar_nome_coluna(c) == "nc" for c in linha):
            return posicao, _mapear_cabecalho(linha)
    return None


def _ler_aba(nome: str, linhas: list[tuple], resultado: ResultadoLeituraControleNc) -> None:
    achado = _achar_cabecalho(linhas)
    if achado is None:
        resultado.abas_ignoradas.append((nome, "cabeçalho com a coluna NC não encontrado"))
        return
    posicao, colunas = achado
    if "valor" not in colunas:
        resultado.abas_ignoradas.append((nome, "sem coluna de valor (VALOR / VALOR RECEBIDO)"))
        return

    def celula(linha: tuple, campo: str) -> object:
        indice = colunas.get(campo)
        return linha[indice] if indice is not None and indice < len(linha) else None

    anterior: dict[str, object] = {}
    for deslocamento, linha in enumerate(linhas[posicao + 1:], start=posicao + 2):
        # `deslocamento` é o número da linha na planilha (1-based).
        campos: dict[str, object] = {}
        for campo in ("nc", "data", "ug_emitente", "orgao", "oficio", "fonte", "ptres", "natureza",
                      "pi", "ted", "transferencia", "processo", "observacao"):
            campos[campo] = celula(linha, campo)
        combinado = celula(linha, "ted_transferencia")
        if "ted_transferencia" in colunas:
            campos["ted"] = combinado
            campos["transferencia"] = combinado
        if all(_vazio(v) for v in list(campos.values()) + [celula(linha, "valor")]):
            continue

        convertidos: dict[str, object] = {}
        for campo in _CAMPOS_CODIGO:
            convertidos[campo] = _codigo(campos[campo])
        for campo in _CAMPOS_TEXTO:
            convertidos[campo] = _texto(campos[campo])
        convertidos["data"] = _data(campos["data"])

        if convertidos["nc"] is None:
            if not anterior:
                resultado.rejeitadas.append(
                    (nome, deslocamento, "linha de continuação sem NC anterior na aba"))
                continue
            for campo in _HERDADOS:
                if convertidos[campo] is None:
                    convertidos[campo] = anterior[campo]
        else:
            anterior = {campo: convertidos[campo] for campo in _HERDADOS}

        try:
            valor = parse_valor_brl(celula(linha, "valor")) if not _vazio(celula(linha, "valor")) \
                else None
        except ValueError:
            valor = None
        if valor is None:
            resultado.rejeitadas.append((nome, deslocamento, "sem valor numérico"))
            continue

        resultado.linhas.append(LinhaControleNc(
            aba=nome, linha_origem=deslocamento, valor=valor,
            ptres=convertidos["ptres"], natureza=convertidos["natureza"], pi=convertidos["pi"],
            observacao=convertidos["observacao"],
            **{campo: convertidos[campo] for campo in _HERDADOS},
        ))


def ler_controle_nc(conteudo: bytes) -> ResultadoLeituraControleNc:
    """Lê todas as abas do `.xlsx` em memória (spec §5.1). Nunca toca o banco."""

    resultado = ResultadoLeituraControleNc()
    livro = load_workbook(io.BytesIO(conteudo), data_only=True)
    try:
        for planilha in livro.worksheets:
            linhas = [tuple(r) for r in planilha.iter_rows(values_only=True)]
            _ler_aba(planilha.title, linhas, resultado)
    finally:
        livro.close()
    return resultado


# --------------------------------------------------------------------------------------
# Conferência
# --------------------------------------------------------------------------------------

def _numero_do_ted(chave_ted: str | None) -> str | None:
    return chave_ted.split("|")[0] if chave_ted else None


def conferir_controle(conn, leitura: ResultadoLeituraControleNc) -> ConferenciaControle:
    """Confere a planilha com o banco (spec §5.2). SOMENTE LEITURA: só `SELECT` em
    `documento_nc` e `execucao_anual` (a ligação com o TED usa o número do TED da própria chave)."""

    por_chave: dict[tuple[str, str], list[LinhaControleNc]] = {}
    por_ted: dict[str, list[LinhaControleNc]] = {}
    sem_ted: list[LinhaControleNc] = []
    for linha in leitura.linhas:
        if linha.ted is None:
            sem_ted.append(linha)
            continue
        por_ted.setdefault(linha.ted, []).append(linha)
        if linha.nc:
            por_chave.setdefault((linha.nc, linha.ted), []).append(linha)

    documentos = conn.execute(
        "SELECT chave_nc_documento, chave_ted, ted, numero_nc, ug_emitente, valor_assinado_total "
        "FROM documento_nc ORDER BY chave_nc_documento"
    ).fetchall()
    repetidas: dict[tuple[str, str | None], int] = {}
    for _, chave_ted, ted, numero_nc, _, _ in documentos:
        chave = (normalizar_codigo(numero_nc), ted or _numero_do_ted(chave_ted))
        repetidas[chave] = repetidas.get(chave, 0) + 1

    por_nc: list[ConferenciaNc] = []
    for chave_doc, chave_ted, ted, numero_nc, ug_simec, assinado in documentos:
        numero = normalizar_codigo(numero_nc)
        ted_num = ted or _numero_do_ted(chave_ted)
        valor_simec = abs(texto_para_valor(assinado)) if assinado is not None else None
        ug_simec = normalizar_codigo(ug_simec) or None
        candidatas = [
            l for l in por_chave.get((numero, ted_num), [])
            if not (ug_simec and l.ug_emitente and l.ug_emitente != ug_simec)
        ] if ted_num else []

        def montar(situacao, valor_planilha=None, ug_planilha=None):
            return ConferenciaNc(chave_doc, chave_ted, numero, situacao, valor_simec,
                                 valor_planilha, ug_simec, ug_planilha)

        if not candidatas:
            por_nc.append(montar(SITUACAO_SEM_PLANILHA))
            continue
        ugs = {l.ug_emitente for l in candidatas if l.ug_emitente}
        if len(ugs) > 1 or repetidas[(numero, ted_num)] > 1:
            por_nc.append(montar(SITUACAO_AMBIGUA))
            continue
        total = sum((l.valor for l in candidatas), Decimal("0"))
        situacao = (SITUACAO_CONFERE if valor_simec is not None
                    and abs(total - valor_simec) <= _TOLERANCIA else SITUACAO_DIVERGE)
        por_nc.append(montar(situacao, total, next(iter(ugs), None)))

    # NC da planilha anterior ao primeiro ano do consolidado do TED (liga pelo número do TED).
    primeiro_ano: dict[str, int] = {}
    for chave_ted, ano in conn.execute(
        "SELECT chave_ted, MIN(ano_emissao) FROM execucao_anual GROUP BY chave_ted"
    ).fetchall():
        primeiro_ano[chave_ted] = ano
    anteriores: dict[str, list[LinhaControleNc]] = {}
    for chave_ted, ano in sorted(primeiro_ano.items()):
        corte = date(ano, 1, 1)
        achadas = [l for l in por_ted.get(_numero_do_ted(chave_ted), [])
                   if l.data is not None and l.data < corte]
        if achadas:
            anteriores[chave_ted] = achadas

    return ConferenciaControle(por_nc=por_nc, nc_anterior_consolidado=anteriores,
                               sem_ted=sem_ted, leitura=leitura)


# --------------------------------------------------------------------------------------
# Justificativa sugerida (spec §5.3)
# --------------------------------------------------------------------------------------

_TIPOS_COM_JUSTIFICATIVA = {
    "nc_ug_emitente_ausente",
    "pf_liquida_maior_que_nc",
    "pf_liquida_diverge_consolidado",
    "ted_credito_sem_empenho",
}
_MAX_NCS_NA_JUSTIFICATIVA = 8


def _brl(valor: Decimal) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def justificativa_sugerida(alerta_tipo: str, chave_ted: str,
                           conferencia: ConferenciaControle) -> str | None:
    """Texto editável para resolver um alerta com base na planilha, citando NC, data, valor e
    UG. `None` se o tipo não é de spec §5.3 ou a planilha não tem dado para o TED."""

    if alerta_tipo not in _TIPOS_COM_JUSTIFICATIVA:
        return None
    numero = _numero_do_ted(chave_ted)
    linhas = conferencia.nc_anterior_consolidado.get(chave_ted) \
        if alerta_tipo == "pf_liquida_maior_que_nc" else None
    anterior = bool(linhas)
    if not linhas:
        linhas = [l for l in conferencia.leitura.linhas if l.ted == numero and l.nc]
    if not linhas:
        return None

    agrupadas: dict[str, dict] = {}
    for l in linhas:
        g = agrupadas.setdefault(l.nc, {"valor": Decimal("0"), "data": None, "ug": None})
        g["valor"] += l.valor
        g["data"] = g["data"] or l.data
        g["ug"] = g["ug"] or l.ug_emitente
    itens = []
    for nc, g in list(agrupadas.items())[:_MAX_NCS_NA_JUSTIFICATIVA]:
        data = g["data"].strftime("%d/%m/%Y") if g["data"] else "sem data"
        ug = f" (UG {g['ug']})" if g["ug"] else ""
        itens.append(f"NC {nc} de {data}, {_brl(g['valor'])}{ug}")
    resto = len(agrupadas) - len(itens)
    texto = "; ".join(itens) + (f"; e mais {resto} NC(s)" if resto > 0 else "")
    prefixo = ("Planilha de controle (NC anterior ao consolidado): " if anterior
               else "Planilha de controle: ")
    return f"{prefixo}{texto}."


# --------------------------------------------------------------------------------------
# Exportação
# --------------------------------------------------------------------------------------

_CABECALHO_LINHA = ["Aba", "Linha", "NC", "Data", "UG emitente", "Órgão", "Ofício", "Fonte",
                    "PTRES", "ND", "PI", "TED", "Transferência", "Valor", "Processo", "Observação"]


def _linha_planilha(l: LinhaControleNc) -> list:
    return [l.aba, l.linha_origem, l.nc, l.data, l.ug_emitente, l.orgao, l.oficio, l.fonte,
            l.ptres, l.natureza, l.pi, l.ted, l.transferencia, float(l.valor), l.processo,
            l.observacao]


def gerar_xlsx_conferencia(conferencia: ConferenciaControle) -> bytes:
    """Excel do resultado, para download (spec §5.2). Gerado em memória."""

    livro = Workbook()
    ws = livro.active
    ws.title = "Conferência por NC"
    ws.append(["NC", "TED (chave)", "Situação", "Valor SIMEC", "Valor planilha", "UG SIMEC",
               "UG planilha (sugestão)"])
    for c in conferencia.por_nc:
        ws.append([c.numero_nc, c.chave_ted, c.situacao,
                   float(c.valor_simec) if c.valor_simec is not None else None,
                   float(c.valor_planilha) if c.valor_planilha is not None else None,
                   c.ug_simec, c.ug_planilha])

    ws = livro.create_sheet("NC anterior ao consolidado")
    ws.append(["TED (chave)", *_CABECALHO_LINHA])
    for chave_ted, linhas in conferencia.nc_anterior_consolidado.items():
        for l in linhas:
            ws.append([chave_ted, *_linha_planilha(l)])

    ws = livro.create_sheet("Sem TED")
    ws.append(_CABECALHO_LINHA)
    for l in conferencia.sem_ted:
        ws.append(_linha_planilha(l))

    ws = livro.create_sheet("Não lido")
    ws.append(["Tipo", "Aba", "Linha", "Motivo"])
    for aba, motivo in conferencia.leitura.abas_ignoradas:
        ws.append(["Aba não lida", aba, None, motivo])
    for aba, linha, motivo in conferencia.leitura.rejeitadas:
        ws.append(["Linha rejeitada", aba, linha, motivo])

    buf = io.BytesIO()
    livro.save(buf)
    return buf.getvalue()
