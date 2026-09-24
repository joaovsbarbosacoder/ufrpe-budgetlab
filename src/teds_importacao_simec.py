"""
Leitores das quatro extrações do SIMEC usadas pelo acompanhamento de TEDs:

  * Execução: Orçamentário e Financeiro -> `ler_execucao_anual_simec`
  * Documentos: DOC NE                  -> `ler_doc_ne_simec`
  * Documentos: DOC NC                  -> `ler_doc_nc_simec`
  * Documentos: DOC PF                  -> `ler_doc_pf_simec`

Cada função recebe o DataFrame já lido pelo `pandas.read_excel` (a leitura do arquivo em si
fica a cargo de `src/teds_lotes.py`, que também sabe calcular o hash do arquivo bruto) e
devolve um `ResultadoLeitura`: registros normalizados prontos para persistir, e linhas
rejeitadas com o motivo — nunca lança exceção por causa de uma linha ruim isolada (regra 4:
rodapés sem identificador documental são ignorados, não tratados como erro).

Revisado contra uma extração real do SIMEC (4 arquivos, exercício 2026): os `_MAPA_*` abaixo
trazem tanto os nomes de coluna confirmados na extração real quanto os nomes descritos no
briefing original (mantidos como alias, para não quebrar quem já dependia deles).
`normalizar_nome_coluna` cobre variação de acento/caixa/espaço e também o sufixo monetário
`(R$)` que a extração real usa em algumas colunas de valor (ex.: "Total Descentralizado
(R$)") — por isso a maioria dos campos de valor não precisou de um alias explícito para o
sufixo.

Achados da extração real que exigiram tratamento específico (não presumidos, confirmados
linha a linha contra os 4 arquivos):

  * TED, UG e Gestão Emitente costumam vir como `float` (ex.: `12112.0`) — `codigo_coluna`
    (via `normalizar_codigo`) remove o sufixo antes de virar texto; ver docstring de
    `codigo_coluna` em `src/teds_normalizacao.py`.
  * DOC NC: a coluna de UG emitente vem vazia em ~41% das linhas reais (86 de 179, no
    arquivo de referência) — não é rodapé, é uma lacuna legítima da extração. Essas linhas
    são importadas (não rejeitadas), com `ug_emitente=None`, aviso
    `UG_EMITENTE_NC_AUSENTE` e `status_relacionamento='PARCIAL'`. A UG emitente, quando
    ausente, NUNCA é preenchida com a UG Descentralizadora — são UGs diferentes em todas as
    linhas onde as duas colunas vêm preenchidas.
  * DOC NC: o mesmo documento (mesmo TED+SIAFI+número+operação+data) aparece em várias
    linhas da planilha (rateio por fonte/ação — 20 de 122 documentos no arquivo de
    referência, totalizando 179 linhas). `ler_doc_nc_simec` preserva cada linha em
    `registros` (nunca trata repetição como duplicidade) e devolve também `documentos`,
    agregado por `chave_nc_documento`.
  * NC usa `( + )`/`( - )` e PF usa `(+)`/`(-)` para a mesma operação — `normalizar_operacao`
    converte ambos para `+`/`-` antes de persistir o campo `operacao`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pandas as pd

from src.teds_normalizacao import (
    chave_empenho,
    chave_nc_documento,
    chave_nc_linha,
    chave_ted,
    codigo_coluna as _codigo,
    data_para_texto,
    linha_origem as _linha_origem,
    mapear_colunas as _mapear_colunas,
    normalizar_operacao,
    normalizar_nome_coluna,
    parse_data_br,
    parse_valor_brl,
    sinal_operacao,
    texto_coluna as _texto,
    validar_colunas_obrigatorias as _validar_colunas_obrigatorias,
)

AVISO_UG_EMITENTE_NC_AUSENTE = "UG_EMITENTE_NC_AUSENTE"
STATUS_RELACIONAMENTO_OK = "OK"
STATUS_RELACIONAMENTO_PARCIAL = "PARCIAL"


@dataclass
class LinhaRejeitada:
    indice: int
    motivo: str
    linha_origem: dict[str, Any]


@dataclass
class ResultadoLeitura:
    registros: list[dict[str, Any]] = field(default_factory=list)
    rejeitadas: list[LinhaRejeitada] = field(default_factory=list)
    #: total(is) impresso(s) no rodapé do relatório, por campo de valor; `None` se não há rodapé
    rodape: dict[str, Decimal] | None = None


def _celula_vazia(valor: Any) -> bool:
    return bool(pd.isna(valor)) or str(valor).strip() == ""


def _capturar_rodape(
    df: pd.DataFrame, colunas: dict[str, str], campos_valor: tuple[str, ...]
) -> dict[str, Decimal] | None:
    """Total impresso pelo SIMEC na ÚLTIMA linha da planilha.

    Formato confirmado nas 4 extrações reais (17/09/2026): a última linha vem sem nenhum
    identificador (TED, SIAFI, número do documento, datas...) e só com o(s) valor(es) somado(s).
    Só a última linha é examinada, e só é rodapé se TODAS as colunas fora dos campos de valor
    estiverem vazias — uma linha de dado nunca é tomada por rodapé. `None` se não há rodapé.

    Atenção: no DOC NC e no DOC PF o total do rodapé é a soma ABSOLUTA (positivas + negativas),
    não o líquido — quem compara deve usar a soma bruta."""

    if df.empty:
        return None
    colunas_valor = {colunas[c] for c in campos_valor if c in colunas}
    if not colunas_valor:
        return None
    ultima = df.iloc[-1]
    if any(not _celula_vazia(ultima[c]) for c in df.columns if c not in colunas_valor):
        return None
    rodape: dict[str, Decimal] = {}
    for campo in campos_valor:
        if campo in colunas and not _celula_vazia(ultima[colunas[campo]]):
            try:
                rodape[campo] = parse_valor_brl(ultima[colunas[campo]])
            except ValueError:
                return None
    return rodape or None


# --------------------------------------------------------------------------------------
# 1. Execução: Orçamentário e Financeiro
# --------------------------------------------------------------------------------------

_MAPA_EXECUCAO_ANUAL = {
    "ano_emissao": (normalizar_nome_coluna("Ano de emissão"),),
    "descricao": (normalizar_nome_coluna("Descrição do Termo"),),
    "estado_atual": (normalizar_nome_coluna("Estado Atual"),),
    "inicio_vigencia": (normalizar_nome_coluna("Início da Vigência"),),
    "fim_vigencia": (normalizar_nome_coluna("Fim da Vigência"),),
    "codigo_siafi": (normalizar_nome_coluna("SIAFI"),),
    "ted": (normalizar_nome_coluna("TED"),),
    "ug_descentralizadora": (normalizar_nome_coluna("UG Descentralizadora"),),
    "total_nc_descentralizacao": (normalizar_nome_coluna("Total NC Descentralização"),),
    "total_nc_devolucao": (normalizar_nome_coluna("Total NC Devolução"),),
    "total_descentralizado": (normalizar_nome_coluna("Total Descentralizado"),),
    "total_pf_repasse": (normalizar_nome_coluna("Total PF Repasse"),),
    "total_pf_devolucao": (normalizar_nome_coluna("Total PF Devolução"),),
    "total_repassado": (normalizar_nome_coluna("Total Repassado"),),
}

_CAMPOS_VALOR_EXECUCAO_ANUAL = (
    "total_nc_descentralizacao",
    "total_nc_devolucao",
    "total_descentralizado",
    "total_pf_repasse",
    "total_pf_devolucao",
    "total_repassado",
)

#: colunas sem as quais o arquivo não identifica o TED nem sustenta a conciliação (regra 6.1
#: do briefing) — os demais campos do `_MAPA_EXECUCAO_ANUAL` (descrição, estado, vigência, UG
#: descentralizadora) já são tratados como opcionais linha a linha no corpo da função.
_CAMPOS_OBRIGATORIOS_EXECUCAO_ANUAL = ("ted", "codigo_siafi", "ano_emissao") + _CAMPOS_VALOR_EXECUCAO_ANUAL


def ler_execucao_anual_simec(df: pd.DataFrame) -> ResultadoLeitura:
    colunas = _mapear_colunas(df.columns, _MAPA_EXECUCAO_ANUAL)
    _validar_colunas_obrigatorias(df.columns, colunas, _CAMPOS_OBRIGATORIOS_EXECUCAO_ANUAL)
    resultado = ResultadoLeitura()
    resultado.rodape = _capturar_rodape(df, colunas, _CAMPOS_VALOR_EXECUCAO_ANUAL)

    for indice, linha in df.iterrows():
        origem = _linha_origem(linha)
        ted = _codigo(linha, colunas, "ted")
        siafi = _codigo(linha, colunas, "codigo_siafi")
        if not ted or not siafi:
            resultado.rejeitadas.append(
                LinhaRejeitada(indice, "sem TED/SIAFI (possível linha de rodapé)", origem)
            )
            continue

        try:
            ano_emissao = int(float(linha[colunas["ano_emissao"]]))
            valores: dict[str, Decimal] = {
                campo: parse_valor_brl(linha[colunas[campo]])
                for campo in _CAMPOS_VALOR_EXECUCAO_ANUAL
            }
        except (KeyError, ValueError, TypeError) as exc:
            resultado.rejeitadas.append(LinhaRejeitada(indice, str(exc), origem))
            continue

        registro = {
            "chave_ted": chave_ted(ted, siafi),
            "ted": ted,
            "codigo_siafi": siafi,
            "descricao": _texto(linha, colunas, "descricao") or None,
            "estado_atual": _texto(linha, colunas, "estado_atual") or None,
            "inicio_vigencia": data_para_texto(
                parse_data_br(linha[colunas["inicio_vigencia"]]) if "inicio_vigencia" in colunas else None
            ),
            "fim_vigencia": data_para_texto(
                parse_data_br(linha[colunas["fim_vigencia"]]) if "fim_vigencia" in colunas else None
            ),
            "ug_descentralizadora": _codigo(linha, colunas, "ug_descentralizadora") or None,
            "ano_emissao": ano_emissao,
            "linha_origem": origem,
            **valores,
        }
        resultado.registros.append(registro)

    return resultado


# --------------------------------------------------------------------------------------
# 2. Documentos: DOC NE
# --------------------------------------------------------------------------------------

_MAPA_DOC_NE = {
    "gestao_emitente": (normalizar_nome_coluna("Gestão Emitente - NE"),),
    "numero_ne": (normalizar_nome_coluna("Número do Empenho"),),
    "ug_emitente": (normalizar_nome_coluna("UG Executora Emitente - NE"),),
    "descricao": (normalizar_nome_coluna("Descrição do Termo"),),
    "estado_atual": (normalizar_nome_coluna("Estado Atual"),),
    "inicio_vigencia": (normalizar_nome_coluna("Início da Vigência"),),
    "fim_vigencia": (normalizar_nome_coluna("Fim da Vigência"),),
    "codigo_siafi": (normalizar_nome_coluna("SIAFI"),),
    "ted": (normalizar_nome_coluna("TED"),),
    "ug_descentralizadora": (normalizar_nome_coluna("UG Descentralizadora"),),
    "valor_ne": (normalizar_nome_coluna("Valor da NE"),),
}

#: descrição/estado/vigência/UG descentralizadora ficam de fora (opcionais, tratados linha a
#: linha) — os demais formam a chave do TED e do empenho (regra 4.2 do briefing).
_CAMPOS_OBRIGATORIOS_DOC_NE = (
    "numero_ne", "ted", "codigo_siafi", "ug_emitente", "gestao_emitente", "valor_ne",
)


def ler_doc_ne_simec(df: pd.DataFrame) -> ResultadoLeitura:
    colunas = _mapear_colunas(df.columns, _MAPA_DOC_NE)
    _validar_colunas_obrigatorias(df.columns, colunas, _CAMPOS_OBRIGATORIOS_DOC_NE)
    resultado = ResultadoLeitura()
    resultado.rodape = _capturar_rodape(df, colunas, ("valor_ne",))

    for indice, linha in df.iterrows():
        origem = _linha_origem(linha)
        ted = _codigo(linha, colunas, "ted")
        siafi = _codigo(linha, colunas, "codigo_siafi")
        numero_ne = _codigo(linha, colunas, "numero_ne")
        ug_emitente = _codigo(linha, colunas, "ug_emitente")
        gestao_emitente = _codigo(linha, colunas, "gestao_emitente")

        if not numero_ne or not ted or not siafi:
            resultado.rejeitadas.append(
                LinhaRejeitada(indice, "sem NE/TED/SIAFI (possível linha de rodapé)", origem)
            )
            continue
        if not ug_emitente or not gestao_emitente:
            resultado.rejeitadas.append(
                LinhaRejeitada(indice, "NE sem UG ou gestão emitente", origem)
            )
            continue

        try:
            valor_ne = parse_valor_brl(linha[colunas["valor_ne"]])
        except (KeyError, ValueError, TypeError) as exc:
            resultado.rejeitadas.append(LinhaRejeitada(indice, str(exc), origem))
            continue

        registro = {
            "chave_ted": chave_ted(ted, siafi),
            "ted": ted,
            "codigo_siafi": siafi,
            "descricao_ted": _texto(linha, colunas, "descricao") or None,
            "estado_atual": _texto(linha, colunas, "estado_atual") or None,
            "inicio_vigencia": data_para_texto(
                parse_data_br(linha[colunas["inicio_vigencia"]]) if "inicio_vigencia" in colunas else None
            ),
            "fim_vigencia": data_para_texto(
                parse_data_br(linha[colunas["fim_vigencia"]]) if "fim_vigencia" in colunas else None
            ),
            "ug_descentralizadora": _codigo(linha, colunas, "ug_descentralizadora") or None,
            "ug_emitente": ug_emitente,
            "gestao_emitente": gestao_emitente,
            "numero_ne": numero_ne,
            "chave_empenho": chave_empenho(ug_emitente, gestao_emitente, numero_ne),
            "valor_ne": valor_ne,
            # Não confirmado: este relatório não lista uma coluna de descrição própria da NE
            # (só "Descrição do Termo", que é do TED) — ver docstring do módulo.
            "descricao_ne": None,
            "linha_origem": origem,
        }
        resultado.registros.append(registro)

    return resultado


# --------------------------------------------------------------------------------------
# 3. Documentos: DOC NC
# --------------------------------------------------------------------------------------

_MAPA_DOC_NC = {
    "operacao": (normalizar_nome_coluna("Operação"),),
    "ug_emitente": (
        normalizar_nome_coluna("UG Emitente - NC"),
        normalizar_nome_coluna("UG emitente da NC"),
    ),
    "numero_nc": (normalizar_nome_coluna("Número da NC"),),
    "codigo_siafi": (
        normalizar_nome_coluna("SIAFI"),
        normalizar_nome_coluna("Número da transferência SIAFI"),
    ),
    "valor_nc": (
        normalizar_nome_coluna("Valor Total NC"),
        normalizar_nome_coluna("Valor total da NC"),
    ),
    "data_emissao": (normalizar_nome_coluna("Data de Emissão da NC"),),
    "ted": (normalizar_nome_coluna("TED"),),
}

#: `ug_emitente` fica de fora de propósito — ausente em ~41% das linhas reais (ver docstring
#: do módulo), tratado como aviso/relacionamento parcial linha a linha, não como coluna
#: obrigatória do arquivo. `data_emissao` também é tolerada ausente (ver corpo do leitor).
_CAMPOS_OBRIGATORIOS_DOC_NC = ("numero_nc", "operacao", "valor_nc", "ted", "codigo_siafi")


@dataclass
class ResultadoLeituraNC:
    registros: list[dict[str, Any]] = field(default_factory=list)
    documentos: list[dict[str, Any]] = field(default_factory=list)
    rejeitadas: list[LinhaRejeitada] = field(default_factory=list)
    rodape: dict[str, Decimal] | None = None


def ler_doc_nc_simec(df: pd.DataFrame, identificador_lote: str = "") -> ResultadoLeituraNC:
    """Lê o relatório DOC NC.

    `identificador_lote` é opcional e identifica o lote de importação (ex.: hash do arquivo
    de origem, atribuído por `src/teds_lotes.py`) — usado só para compor `chave_nc_linha`
    (idempotência/rastreabilidade da linha). Sem ele, a chave de linha ainda é estável para
    reimportações do MESMO DataFrame (mesmo índice de linha), mas não distingue lotes.

    Cada linha da planilha é preservada em `registros` — a mesma NC pode aparecer em várias
    linhas (rateio por fonte/ação) e isso não é duplicidade. `documentos` traz o agregado por
    `chave_nc_documento` (TED+SIAFI+número+operação+data), com os valores somados.
    """

    colunas = _mapear_colunas(df.columns, _MAPA_DOC_NC)
    _validar_colunas_obrigatorias(df.columns, colunas, _CAMPOS_OBRIGATORIOS_DOC_NC)
    resultado = ResultadoLeituraNC()
    resultado.rodape = _capturar_rodape(df, colunas, ("valor_nc",))
    agregados: dict[str, dict[str, Any]] = {}

    for indice, linha in df.iterrows():
        origem = _linha_origem(linha)
        numero_nc = _codigo(linha, colunas, "numero_nc")

        if not numero_nc:
            resultado.rejeitadas.append(
                LinhaRejeitada(indice, "sem número da NC (possível linha de rodapé)", origem)
            )
            continue

        ug_emitente = _codigo(linha, colunas, "ug_emitente") or None
        ted = _codigo(linha, colunas, "ted")
        siafi = _codigo(linha, colunas, "codigo_siafi")

        try:
            operacao_normalizada = normalizar_operacao(linha[colunas["operacao"]])
            valor_original = parse_valor_brl(linha[colunas["valor_nc"]])
        except (KeyError, ValueError, TypeError) as exc:
            resultado.rejeitadas.append(LinhaRejeitada(indice, str(exc), origem))
            continue

        valor_assinado_calc = valor_original * sinal_operacao(linha[colunas["operacao"]])
        data_emissao = data_para_texto(
            parse_data_br(linha[colunas["data_emissao"]]) if "data_emissao" in colunas else None
        )

        avisos: list[str] = []
        if ug_emitente is None:
            avisos.append(AVISO_UG_EMITENTE_NC_AUSENTE)
        status_relacionamento = (
            STATUS_RELACIONAMENTO_PARCIAL if ug_emitente is None else STATUS_RELACIONAMENTO_OK
        )

        chave_documento = chave_nc_documento(ted, siafi, numero_nc, operacao_normalizada, data_emissao)
        chave_linha = chave_nc_linha(identificador_lote, indice)

        registro = {
            "chave_ted": chave_ted(ted, siafi) if ted and siafi else None,
            "chave_nc_documento": chave_documento,
            "chave_nc_linha": chave_linha,
            "ug_emitente": ug_emitente,
            "numero_nc": numero_nc,
            "codigo_siafi": siafi or None,
            "ted": ted or None,
            "data_emissao": data_emissao,
            "operacao": operacao_normalizada,
            "valor_original": valor_original,
            "valor_assinado": valor_assinado_calc,
            "status_relacionamento": status_relacionamento,
            "avisos": avisos,
            "linha_origem": origem,
        }
        resultado.registros.append(registro)

        documento = agregados.get(chave_documento)
        if documento is None:
            documento = {
                "chave_nc_documento": chave_documento,
                "chave_ted": registro["chave_ted"],
                "ted": registro["ted"],
                "codigo_siafi": registro["codigo_siafi"],
                "numero_nc": numero_nc,
                "operacao": operacao_normalizada,
                "data_emissao": data_emissao,
                "ug_emitente": ug_emitente,
                "valor_original_total": Decimal("0"),
                "valor_assinado_total": Decimal("0"),
                "quantidade_linhas": 0,
                "status_relacionamento": STATUS_RELACIONAMENTO_OK,
                "chaves_nc_linha": [],
            }
            agregados[chave_documento] = documento

        if documento["ug_emitente"] is None and ug_emitente is not None:
            documento["ug_emitente"] = ug_emitente
        if ug_emitente is None:
            documento["status_relacionamento"] = STATUS_RELACIONAMENTO_PARCIAL
        documento["valor_original_total"] += valor_original
        documento["valor_assinado_total"] += valor_assinado_calc
        documento["quantidade_linhas"] += 1
        documento["chaves_nc_linha"].append(chave_linha)

    resultado.documentos = list(agregados.values())
    return resultado


# --------------------------------------------------------------------------------------
# 4. Documentos: DOC PF
# --------------------------------------------------------------------------------------

_MAPA_DOC_PF = {
    "data_emissao": (normalizar_nome_coluna("Data de Emissão Doc. PF"),),
    "numero_pf": (normalizar_nome_coluna("Número Doc. PF"),),
    "operacao": (normalizar_nome_coluna("Operação"),),
    "ug_emitente": (normalizar_nome_coluna("UG Emitente - PF"),),
    "descricao": (normalizar_nome_coluna("Descrição do Termo"),),
    "estado_atual": (normalizar_nome_coluna("Estado Atual"),),
    "fim_vigencia": (normalizar_nome_coluna("Fim da Vigência"),),
    "inicio_vigencia": (normalizar_nome_coluna("Início da Vigência"),),
    "codigo_siafi": (normalizar_nome_coluna("SIAFI"),),
    "ted": (normalizar_nome_coluna("TED"),),
    "ug_descentralizadora": (normalizar_nome_coluna("UG Descentralizadora"),),
    "valor_pf": (normalizar_nome_coluna("Valor Doc. PF"),),
}

_CAMPOS_OBRIGATORIOS_DOC_PF = ("numero_pf", "ug_emitente", "operacao", "valor_pf", "ted", "codigo_siafi")


def ler_doc_pf_simec(df: pd.DataFrame) -> ResultadoLeitura:
    colunas = _mapear_colunas(df.columns, _MAPA_DOC_PF)
    _validar_colunas_obrigatorias(df.columns, colunas, _CAMPOS_OBRIGATORIOS_DOC_PF)
    resultado = ResultadoLeitura()
    resultado.rodape = _capturar_rodape(df, colunas, ("valor_pf",))

    for indice, linha in df.iterrows():
        origem = _linha_origem(linha)
        numero_pf = _codigo(linha, colunas, "numero_pf")
        ug_emitente = _codigo(linha, colunas, "ug_emitente")
        ted = _codigo(linha, colunas, "ted")
        siafi = _codigo(linha, colunas, "codigo_siafi")

        if not numero_pf or not ug_emitente:
            resultado.rejeitadas.append(
                LinhaRejeitada(indice, "sem número/UG emitente do Doc. PF (possível rodapé)", origem)
            )
            continue

        try:
            operacao_normalizada = normalizar_operacao(linha[colunas["operacao"]])
            valor_original = parse_valor_brl(linha[colunas["valor_pf"]])
        except (KeyError, ValueError, TypeError) as exc:
            resultado.rejeitadas.append(LinhaRejeitada(indice, str(exc), origem))
            continue

        valor_assinado_calc = valor_original * sinal_operacao(linha[colunas["operacao"]])

        registro = {
            "chave_ted": chave_ted(ted, siafi) if ted and siafi else None,
            "ug_emitente": ug_emitente,
            "numero_pf": numero_pf,
            "data_emissao": data_para_texto(
                parse_data_br(linha[colunas["data_emissao"]]) if "data_emissao" in colunas else None
            ),
            "operacao": operacao_normalizada,
            "valor_original": valor_original,
            "valor_assinado": valor_assinado_calc,
            "linha_origem": origem,
        }
        resultado.registros.append(registro)

    return resultado
