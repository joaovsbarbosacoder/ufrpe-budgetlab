"""
Normalização compartilhada do módulo de TEDs (Termos de Execução Descentralizada).

Funções puras de conversão (valor BR -> Decimal, data BR -> ISO, código -> texto) e de
construção das chaves naturais usadas em todo o módulo. Não conhece SQLite nem nenhum
relatório específico — é a camada mais baixa, reaproveitada pelos leitores de cada base
(`src/teds_importacao_simec.py`, `src/teds_importacao_tesouro_gerencial.py`) e pela geração
de alertas (`src/teds_alertas.py`).

Decisão de projeto: valores monetários trafegam como `Decimal` em todo o módulo de TEDs (nunca
`float`), e são persistidos como texto decimal exato no SQLite — ver `valor_para_texto`/
`texto_para_valor`. Isso é diferente do padrão das demais bases do projeto (que usam
`float64`/pandas com tolerância de centavos), decisão deliberada para este módulo porque ele
faz comparações e somas entre fontes distintas (SIMEC x Tesouro Gerencial) onde arredondamento
acumulado poderia mascarar ou criar divergências.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

_DUAS_CASAS = Decimal("0.01")


# --------------------------------------------------------------------------------------
# Texto e códigos
# --------------------------------------------------------------------------------------

def normalizar_espacos(texto: object) -> str:
    """Remove espaços duplicados e nas pontas. `None`/NaN vira string vazia."""

    if texto is None:
        return ""
    if isinstance(texto, float) and math.isnan(texto):
        return ""
    return re.sub(r"\s+", " ", str(texto)).strip()


_SUFIXO_MONETARIO = re.compile(r"\(?\s*r\$\s*\)?\s*$")


def normalizar_nome_coluna(texto: object) -> str:
    """Forma canônica de um cabeçalho de coluna, para casar variantes com problema de
    acentuação (ver regra 12 do briefing), espaçamento irregular ou o sufixo monetário
    `(R$)` que algumas extrações do SIMEC acrescentam a colunas de valor (ex.: "Total
    Descentralizado (R$)" deve casar com "Total Descentralizado"). Usada só para reconhecer
    QUAL coluna é qual — nunca para transformar o conteúdo/identificadores."""

    texto_normalizado = normalizar_espacos(texto).casefold()
    sem_acento = unicodedata.normalize("NFKD", texto_normalizado)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    sem_sufixo_monetario = _SUFIXO_MONETARIO.sub("", sem_acento)
    return re.sub(r"\s+", " ", sem_sufixo_monetario).strip()


def normalizar_codigo(valor: object) -> str:
    """Converte um identificador (TED, SIAFI, UG, gestão, número de NC/PF/NE) para texto,
    preservando zeros à esquerda quando já vem como string. Excel/pandas costuma entregar
    códigos puramente numéricos como `float` (ex.: 153165.0) — nesse caso, a parte decimal
    é descartada por não carregar informação (não existe código com fração)."""

    if valor is None:
        return ""
    if isinstance(valor, float):
        if math.isnan(valor):
            return ""
        if valor.is_integer():
            return str(int(valor))
        return repr(valor)
    if isinstance(valor, int):
        return str(valor)
    return normalizar_espacos(valor)


# --------------------------------------------------------------------------------------
# Valores monetários
# --------------------------------------------------------------------------------------

def parse_valor_brl(texto: object) -> Decimal:
    """Converte um valor no formato brasileiro (ponto de milhar, vírgula decimal) para
    `Decimal`. Aceita também `float`/`int` (ex.: célula já lida como número pelo pandas)."""

    if isinstance(texto, Decimal):
        return texto.quantize(_DUAS_CASAS)
    if isinstance(texto, (int, float)):
        if isinstance(texto, float) and math.isnan(texto):
            raise ValueError("Valor monetário ausente (NaN)")
        return Decimal(str(texto)).quantize(_DUAS_CASAS)

    bruto = normalizar_espacos(texto)
    if not bruto:
        raise ValueError("Valor monetário vazio")

    bruto = bruto.replace("R$", "").strip()
    negativo = bruto.startswith("-") or (bruto.startswith("(") and bruto.endswith(")"))
    bruto = bruto.strip("()").lstrip("-").strip()

    bruto = bruto.replace(".", "").replace(",", ".")
    try:
        numero = Decimal(bruto)
    except InvalidOperation as exc:
        raise ValueError(f"Valor monetário inválido: {texto!r}") from exc

    if negativo:
        numero = -numero
    return numero.quantize(_DUAS_CASAS)


def valor_para_texto(valor: Decimal) -> str:
    """Forma canônica de persistência de um `Decimal` monetário no SQLite (texto, não
    ponto flutuante)."""

    return str(valor.quantize(_DUAS_CASAS))


def texto_para_valor(texto: str) -> Decimal:
    return Decimal(texto).quantize(_DUAS_CASAS)


def normalizar_operacao(operacao: object) -> str:
    """Operação normalizada para `+`/`-`, tolerando os formatos que os diferentes relatórios
    do SIMEC usam para o mesmo sinal (DOC NC: `( + )`/`( - )`; DOC PF: `(+)`/`(-)`). Reaproveita
    a validação de `sinal_operacao` — o texto retornado é sempre um dos dois caracteres, nunca
    o texto bruto da planilha."""

    return "+" if sinal_operacao(operacao) == 1 else "-"


def sinal_operacao(operacao: object) -> int:
    """`+1` para operações de descentralização/repasse, `-1` para devolução.

    A planilha registra a operação como `(+)`/`(-)` (ou variações de espaçamento); a regra
    olha apenas a presença do sinal de menos, não o formato exato do texto.
    """

    texto = normalizar_espacos(operacao)
    if not texto:
        raise ValueError("Operação (+/-) ausente")
    if "-" in texto:
        return -1
    if "+" in texto:
        return 1
    raise ValueError(f"Operação não reconhecida: {operacao!r}")


def valor_assinado(valor_original: Decimal, operacao: object) -> Decimal:
    return valor_original * sinal_operacao(operacao)


# --------------------------------------------------------------------------------------
# Datas
# --------------------------------------------------------------------------------------

_PADRAO_DATA_BR = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def parse_data_br(texto: object) -> date | None:
    """Converte `dd/mm/aaaa` para `date`. Célula vazia/ausente vira `None` (dado incompleto
    é sinalizado pelo chamador, nunca vira uma data inventada)."""

    if texto is None:
        return None
    if hasattr(texto, "date") and callable(texto.date):
        # já é datetime/Timestamp (pandas costuma entregar assim quando a coluna é reconhecida
        # como data pelo Excel).
        return texto.date()
    if isinstance(texto, date):
        return texto

    bruto = normalizar_espacos(texto)
    if not bruto:
        return None

    m = _PADRAO_DATA_BR.match(bruto)
    if not m:
        raise ValueError(f"Data fora do formato dd/mm/aaaa: {texto!r}")
    dia, mes, ano = (int(g) for g in m.groups())
    return date(ano, mes, dia)


def data_para_texto(valor: date | None) -> str | None:
    return valor.isoformat() if valor is not None else None


# --------------------------------------------------------------------------------------
# Chaves naturais — ver "Identificadores e relacionamentos" no briefing.
# Nunca usar descrição/nome como chave.
# --------------------------------------------------------------------------------------

def chave_ted(ted: object, codigo_siafi: object) -> str:
    return f"{normalizar_codigo(ted)}|{normalizar_codigo(codigo_siafi)}"


def chave_empenho(ug_emitente: object, gestao_emitente: object, numero_ne: object) -> str:
    return (
        f"{normalizar_codigo(ug_emitente)}|"
        f"{normalizar_codigo(gestao_emitente)}|"
        f"{normalizar_codigo(numero_ne)}"
    )


def chave_nc(ug_emitente: object, numero_nc: object) -> str:
    return f"{normalizar_codigo(ug_emitente)}|{normalizar_codigo(numero_nc)}"


def chave_pf(ug_emitente: object, numero_pf: object) -> str:
    return f"{normalizar_codigo(ug_emitente)}|{normalizar_codigo(numero_pf)}"


def chave_nc_documento(
    ted: object,
    codigo_siafi: object,
    numero_nc: object,
    operacao_normalizada: str,
    data_emissao: object,
) -> str:
    """Identifica o DOCUMENTO da NC (TED + SIAFI + número + operação + data de emissão),
    não a linha da planilha. A extração real do SIMEC repete a mesma NC em várias linhas
    (rateio por fonte/ação, por exemplo) — todas as linhas de um mesmo documento compartilham
    essa chave, e é nela que os valores devem ser agregados. Deliberadamente NÃO inclui a UG
    emitente: ela vem ausente em boa parte das linhas reais e não é o que identifica o
    documento (ver `AVISO_UG_EMITENTE_NC_AUSENTE` em `src/teds_importacao_simec.py`)."""

    return (
        f"{normalizar_codigo(ted)}|{normalizar_codigo(codigo_siafi)}|{normalizar_codigo(numero_nc)}|"
        f"{operacao_normalizada}|{normalizar_espacos(data_emissao)}"
    )


def chave_nc_linha(identificador_lote: object, numero_linha_origem: object) -> str:
    """Identifica a LINHA de origem de uma NC dentro de um lote de importação — usada para
    idempotência/rastreabilidade (reimportar o mesmo arquivo deve produzir a mesma chave de
    linha), nunca para agrupamento (isso é papel de `chave_nc_documento`)."""

    return f"{normalizar_espacos(identificador_lote)}|{normalizar_espacos(numero_linha_origem)}"


_PADRAO_NE_COMPLETA = re.compile(r"^(\d{4})([A-Z]{2})(\d+)$")


def decompor_numero_ne(numero_ne: object) -> tuple[str, str, str] | None:
    """Quebra um número de empenho no formato `2026NE000422` em (ano, tipo, número).

    Usado só quando a base precisar do ano isolado (ex.: cruzar com uma extração do Tesouro
    Gerencial que traga o ano separado do número). Retorna `None` se o formato não bater —
    o chamador decide se isso é um erro ou um formato ainda não mapeado (não confirmado com
    dado real do Tesouro Gerencial).
    """

    m = _PADRAO_NE_COMPLETA.match(normalizar_codigo(numero_ne))
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


# --------------------------------------------------------------------------------------
# Leitura de planilhas — compartilhado pelos leitores SIMEC e Tesouro Gerencial.
# --------------------------------------------------------------------------------------

def mapear_colunas(colunas: pd.Index, mapa_esperado: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """Casa cada nome canônico com a coluna real do DataFrame, tolerando variações de
    acento/caixa/espaço. Colunas ausentes simplesmente não entram no dicionário devolvido —
    cabe a quem chama decidir se a ausência é obrigatória ou opcional."""

    normalizadas = {normalizar_nome_coluna(c): c for c in colunas}
    encontrado: dict[str, str] = {}
    for canonico, variantes in mapa_esperado.items():
        for variante in variantes:
            if variante in normalizadas:
                encontrado[canonico] = normalizadas[variante]
                break
    return encontrado


def linha_origem(linha: pd.Series) -> dict[str, Any]:
    """Cópia da linha bruta como dict serializável, para preservar em `linha_origem`
    (auditoria) — `NaN` vira `None` para não gravar `nan` literal no JSON."""

    return {str(k): (None if pd.isna(v) else v) for k, v in linha.items()}


def texto_coluna(linha: pd.Series, colunas: dict[str, str], campo: str) -> str:
    """Texto normalizado de `campo` na linha, ou string vazia se a coluna não foi mapeada."""

    coluna = colunas.get(campo)
    if coluna is None:
        return ""
    return normalizar_espacos(linha[coluna])


def codigo_coluna(linha: pd.Series, colunas: dict[str, str], campo: str) -> str:
    """Como `texto_coluna`, mas para colunas que guardam identificador (TED, UG, gestão,
    número de NC/NE/PF): aplica `normalizar_codigo` direto sobre o valor BRUTO da célula, em
    vez de `normalizar_espacos`. Isso importa porque o pandas costuma ler um código puramente
    numérico como `float` (ex.: TED 12112 vira 12112.0); se o valor passar primeiro por
    `normalizar_espacos` (que faz `str(valor)`), o `.0` fica preso no texto e não há mais
    como `normalizar_codigo` reconhecer que era um float para descartá-lo — por isso os dois
    passos precisam ser um só, nesta ordem."""

    coluna = colunas.get(campo)
    if coluna is None:
        return ""
    return normalizar_codigo(linha[coluna])
