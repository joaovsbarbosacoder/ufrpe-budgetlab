"""
Leitura e consolidação das abas mensais de pagamentos de contratos.

Camada: regra específica de base (não é leitor genérico, não é analítica, não é interface).
Depende só de pandas/openpyxl. Não importa Streamlit.

Origem: planilha "CONTRATOS - CONTROLE - 2020" (mantida manualmente) — cada mês do exercício
tem sua própria aba, nomeada "{Mês} - Planilha - {ano}" (ex.: "Janeiro - Planilha - 2026").

Escopo deliberado: só o exercício de 2026 (pedido explícito) — o layout de colunas muda entre
anos (2023-2025 usam "DH" onde 2026 usa "NP"/coluna sem nome; 2023 tem uma estrutura bem
diferente, sem "PROCESSO"); cobrir vários anos exigiria reconciliar esses layouts, fora de
escopo por ora. A planilha também tem dezenas de outras abas fora do padrão "{Mês} - Planilha
- {ano}" (ex. "HomeOffice", abas de fornecedor específico) — ignoradas por não terem esse
nome exato.

Campos como NP/NS/OB (números de nota de pagamento/nota de sistema/ordem bancária) ficam de
fora do esquema por pedido explícito ("desconsidere a necessidade dos documentos de OB e NP
ou congêneres... no máximo, se apegue ao número do empenho") — o único identificador de
documento mantido é `empenho`. `TED` (outro identificador de documento de pagamento) fica de
fora pelo mesmo motivo.

`CTO` (número do contrato) tem uma corrupção conhecida na origem: pelo menos 81 células nas 8
abas de 2026 (conferido na extração de 15/08/2026) têm um número de contrato no formato
"MM/AAAA" (ex. "10/2025") reinterpretado pelo Excel como data (`datetime(2025, 10, 1)`) — sempre
com dia = 1, o que torna a recuperação sem ambiguidade: `f"{mes}/{ano}"` reconstrói o número
original exatamente. Ver `_normalizar_contrato`.

Duplicidade: mesma combinação contrato + NF + valor lançada em mais de uma aba mensal é
tratada como duplicidade — a primeira ocorrência (na ordem dos meses) é a principal; as
demais ficam marcadas para auditoria e não somam nos totais.

`empenho` pode citar o ano do empenho no formato "XXXXNEYYYYYY" (ou "XXNEYYYYYY", 2 ou 4
dígitos — os dois convivem na base) — `anos_do_empenho`/a coluna `anos_empenho` extraem esse
ano para filtrar pagamentos por "ano de referência" na tela (pedido explícito: pagamentos
associados a empenho de anos anteriores ao corrente não interessam, mesmo aparecendo numa
aba mensal do ano corrente).

`nes_do_empenho`/a coluna `nes_empenho` extraem o(s) número(s) de NE completo(s) citado(s) em
`empenho`, normalizados para "AAAANEnnnnnn" — mesmo formato de `ne_curta` em
`src/contratos_continuos.py` — para casar pagamento com contrato contínuo por NE (pedido
explícito: restringir a apresentação de pagamentos aos empenhos já relacionados na aba de
Contratos Contínuos). Só tokens com "NE" explícito são reconhecidos; formas abreviadas que
citam só o número (ex. o "812" em "25NE000044/812") ficam de fora — casamento errado é pior do
que não casar.

Contrato público:
    ler_pagamentos(caminho, ano=2026) -> pd.DataFrame
    serie_por_contrato(pagamentos, contrato) -> tuple[pd.DataFrame, float]
    anos_do_empenho(valor) -> set[int]
    nes_do_empenho(valor) -> set[str]
    normalizar_numero_contrato(valor) -> str | None
    meses_pagos_por_contrato(pagamentos) -> pd.DataFrame
"""

from __future__ import annotations

import re
import unicodedata
import warnings
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from src.cache_bases import em_cache
from src.leitura_excel import motor_excel

MESES_ORDEM = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


class ErroLayoutBase(ValueError):
    """Cabeçalho da planilha sem as colunas esperadas — falhar cedo, nunca adivinhar."""


def _normalizar(texto: object) -> str:
    if texto is None:
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sem_acento).strip().upper()


#: cabeçalho normalizado (sem acento, maiúsculo) da origem -> nome interno da coluna. NP/NS/TED
#: ficam de fora por pedido explícito (ver docstring do módulo).
COLUNAS_ORIGEM = {
    "CTO": "contrato_raw",
    "COMPETENCIA": "competencia_raw",
    "EMISSAO": "emissao_raw",
    "NF": "nf",
    "CNPJ": "cnpj_raw",
    "EMPRESA": "fornecedor",
    "VALOR": "valor",
    "EMPENHO": "empenho",
    "UNIDADE": "unidade",
    "PROCESSO": "processo",
}

_COLUNAS_TEXTO = {"nf", "fornecedor", "empenho", "unidade", "processo", "competencia_raw"}


def _normalizar_contrato(valor: object) -> object:
    """Recupera o número de contrato quando o Excel reinterpretou "MM/AAAA" como data (ver
    docstring do módulo) — sempre com dia 1 nos casos conferidos; texto normal passa direto."""

    if isinstance(valor, (datetime, date)):
        return f"{valor.month}/{valor.year}"
    return valor


#: prefixo numérico antes de "NE" — 2 dígitos ("26NE...") ou 4 ("2026NE...", conferido na
#: extração de 15/08/2026: os dois formatos convivem na mesma base).
_EMPENHO_ANO_RE = re.compile(r"(\d{2,4})NE", re.IGNORECASE)


def anos_do_empenho(valor: object) -> set[int]:
    """Anos de empenho citados no campo (o "XXXX" de "XXXXNEYYYYYY" — prefixo de 2 ou 4
    dígitos, normalizado para 4). Uma célula pode citar mais de um empenho (ex.:
    "25NE000044/25NE000812", "25NE000002 E 25NE000003") — devolve todos os anos encontrados,
    não só o primeiro, para o filtro de "ano de referência" não esconder um pagamento que
    também cita o ano corrente só porque cita outro ano antes. Conjunto vazio quando não dá
    para reconhecer nenhum ano (célula vazia, ou sem o padrão "NE") — não é erro, o
    pagamento fica visível independente do filtro nesse caso (ver `app_pages/
    contratos_pagamentos.py`)."""

    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return set()
    anos = set()
    for prefixo in _EMPENHO_ANO_RE.findall(str(valor).upper()):
        anos.add(int(prefixo) if len(prefixo) == 4 else 2000 + int(prefixo))
    return anos


#: token de NE completo — prefixo do ano (2 ou 4 dígitos) + "NE" + número. Só captura tokens
#: com o "NE" explícito: formas abreviadas que omitem o prefixo (ex. o "812" em
#: "25NE000044/812") não são reconhecidas com segurança e ficam de fora — arriscar um
#: casamento errado é pior do que não casar.
_NE_TOKEN_RE = re.compile(r"(\d{2,4})NE(\d+)", re.IGNORECASE)


def nes_do_empenho(valor: object) -> set[str]:
    """Números de NE completos citados no campo, normalizados para "AAAANEnnnnnn" (ano de 4
    dígitos, número com 6 dígitos) — mesmo formato de `ne_curta` em
    `src/contratos_continuos.py`, para permitir casar pagamento com contrato contínuo por NE.
    Conjunto vazio quando não há nenhum token "NE" reconhecível (célula vazia, ou só forma
    abreviada sem "NE" explícito)."""

    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return set()
    nes = set()
    for prefixo, numero in _NE_TOKEN_RE.findall(str(valor).upper()):
        ano = int(prefixo) if len(prefixo) == 4 else 2000 + int(prefixo)
        nes.add(f"{ano}NE{numero.zfill(6)}")
    return nes


#: nome normalizado (sem acento, maiúsculo) de mês -> número (1-12), a partir de MESES_ORDEM.
_MES_NOME_PARA_NUMERO = {_normalizar(nome): i + 1 for i, nome in enumerate(MESES_ORDEM)}

_SENTINELAS_SEM_COMPETENCIA = {"", "-"}

#: separador " A "/" a " (com espaço dos dois lados) usado nos períodos fracionados da
#: origem — não casa um "a" dentro de outra palavra.
_SEPARADOR_PERIODO_RE = re.compile(r"\s+a\s+", re.IGNORECASE)


def _parse_data_periodo(texto: str, ano_reserva: int, mes_reserva: int) -> pd.Timestamp | None:
    """Um dos dois lados de um período fracionado ("DD/MM/AAAA", "DD/MM/AA", "DD/MM" sem ano,
    ou só o dia) — dia/mês/ano ausentes são herdados de `mes_reserva`/`ano_reserva` (o lado
    completo do período, ou o ano do exercício quando nenhum dos dois lados tem ano)."""

    partes = texto.strip().split("/")
    try:
        if len(partes) == 1:
            dia, mes, ano = int(partes[0]), mes_reserva, ano_reserva
        elif len(partes) == 2:
            dia, mes, ano = int(partes[0]), int(partes[1]), ano_reserva
        else:
            dia, mes, ano = int(partes[0]), int(partes[1]), int(partes[2])
            ano = ano + 2000 if ano < 100 else ano
        dia = min(dia, 28)  # só o mês/ano importam para a decisão do mês de competência
        return pd.Timestamp(year=ano, month=mes, day=dia)
    except (ValueError, IndexError):
        return None


def _mes_de_periodo_fracionado(inicio: pd.Timestamp, fim: pd.Timestamp) -> pd.Timestamp:
    """O mês a que um período fracionado se refere (pedido explícito) — o mês com mais dias
    dentro do período `[inicio, fim]`; empate resolvido para o mês mais cedo."""

    if inicio > fim:
        inicio, fim = fim, inicio
    dias = pd.date_range(inicio, fim, freq="D").to_period("M")
    contagem = pd.Series(1, index=dias).groupby(level=0).sum().sort_index()
    escolhido = contagem.idxmax()
    return pd.Timestamp(year=escolhido.year, month=escolhido.month, day=1)


def mes_competencia_de(valor: object, ano_exercicio: int) -> pd.Timestamp | None:
    """O mês a que a competência do pagamento se refere (dia sempre 1º) — `None` quando o
    texto de origem não é reconhecível (célula vazia/"-", ou formato livre demais para
    interpretar com segurança: "fail loud" em `ler_pagamentos` não se aplica linha a linha,
    então aqui é melhor não adivinhar do que adivinhar errado).

    Três formas reconhecidas na origem:
      * nome do mês isolado ("JANEIRO") — assume o ano do exercício sendo lido, já que a
        planilha não guarda o ano nesse formato.
      * uma data única (a maioria já reconvertida para texto ISO pelo Excel, ex.
        "2026-12-25 00:00:00" — mesma corrupção MM/AAAA->data descrita para `CTO`, mas aqui a
        data em si já é a informação certa, não precisa de recuperação).
      * um período fracionado "DD/MM/AAAA A DD/MM/AAAA" (com variações: ano de 2 dígitos, sem
        ano num dos lados, só o dia num dos lados) — o mês escolhido é o que tem mais dias
        dentro do período (pedido explícito: "considere como o mês a que o período se
        refere"), não o mês de início nem o de fim automaticamente.
    """

    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    texto = str(valor).strip()
    if not texto or texto in _SENTINELAS_SEM_COMPETENCIA:
        return None

    # o separador de período é checado ANTES da tentativa de data única: o parser fuzzy do
    # pandas por vezes interpreta um lado abreviado de período (ex. "16 a 31/05/2026", só o
    # dia do lado esquerdo) como uma única data/hora válida (lê "16" como hora), atropelando
    # a lógica de período abaixo — verificado com `pd.to_datetime("16 a 31/05/2026")` ==
    # Timestamp("2026-05-31 16:00:00"). Textos com o separador nunca são uma data única de
    # verdade, então checar o separador primeiro elimina esse risco.
    partes = _SEPARADOR_PERIODO_RE.split(texto)
    if len(partes) == 2:
        fim = _parse_data_periodo(partes[1], ano_exercicio, 1)
        if fim is None:
            return None
        inicio = _parse_data_periodo(partes[0], fim.year, fim.month)
        if inicio is None:
            return None
        return _mes_de_periodo_fracionado(inicio, fim)

    # `dayfirst` não se aplica a strings ISO ("2026-12-25 00:00:00", geradas quando o Excel
    # reinterpretou a célula como data) — pandas emite um UserWarning cosmético nesse caso,
    # sem afetar o resultado; suprimido aqui para não poluir o log a cada linha.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        data_unica = pd.to_datetime(texto, errors="coerce", dayfirst=True)
    if not pd.isna(data_unica):
        return pd.Timestamp(year=data_unica.year, month=data_unica.month, day=1)

    numero_mes = _MES_NOME_PARA_NUMERO.get(_normalizar(texto))
    if numero_mes is not None:
        return pd.Timestamp(year=ano_exercicio, month=numero_mes, day=1)

    return None


def _ler_aba(workbook: pd.ExcelFile, mes: str, ano: int) -> pd.DataFrame | None:
    """Uma aba/mês, a partir de um `pd.ExcelFile` já aberto — None se a aba não existir (mês
    do exercício ainda não chegou, ou fora do padrão de nome esperado), não é erro.

    Recebe o workbook já aberto (não o caminho) de propósito: a planilha de origem tem ~90
    abas e 7-8 MB — abrir um `pd.ExcelFile`/`pd.read_excel` por mês (8 vezes) reprocessa o
    arquivo inteiro do zero a cada chamada; abrir uma vez e usar `.parse()` por aba é ~6x mais
    rápido (65s -> 10s, conferido na extração de 15/08/2026)."""

    nome_aba = f"{mes} - Planilha - {ano}"
    if nome_aba not in workbook.sheet_names:
        return None
    bruto = workbook.parse(sheet_name=nome_aba, header=0, dtype=object)

    normalizados = {coluna: _normalizar(coluna) for coluna in bruto.columns}
    faltando = set(COLUNAS_ORIGEM) - set(normalizados.values())
    if faltando:
        raise ErroLayoutBase(
            f"Colunas ausentes na aba {nome_aba!r}: {sorted(faltando)}. O layout da planilha mudou."
        )

    mapa = {origem: COLUNAS_ORIGEM[norm] for origem, norm in normalizados.items() if norm in COLUNAS_ORIGEM}
    df = bruto.rename(columns=mapa)[list(mapa.values())].copy()
    df["mes_planilha"] = mes
    df["mes_ordem"] = MESES_ORDEM.index(mes)
    df["linha_origem"] = df.index + 2
    return df


@em_cache
def ler_pagamentos(caminho: str | Path, ano: int = 2026) -> pd.DataFrame:
    """Lê todas as abas "{Mês} - Planilha - {ano}" encontradas (meses futuros do exercício
    corrente legitimamente não existem ainda — não é erro) e consolida numa única tabela, uma
    linha por lançamento de pagamento, com duplicidade e alertas marcados."""

    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(caminho)

    # `with` fecha o handle do arquivo explicitamente — sem isso, o Windows mantém o arquivo
    # travado depois da leitura (percebido nos testes: um arquivo temporário não conseguia
    # ser apagado logo em seguida por "já estar sendo usado por outro processo").
    with pd.ExcelFile(caminho, engine=motor_excel()) as workbook:
        partes = [parte for mes in MESES_ORDEM if (parte := _ler_aba(workbook, mes, ano)) is not None]
    if not partes:
        raise ErroLayoutBase(f"Nenhuma aba '<Mês> - Planilha - {ano}' encontrada em {caminho.name}.")

    df = pd.concat(partes, ignore_index=True)
    df["contrato"] = df["contrato_raw"].apply(_normalizar_contrato)
    df = df[df["contrato"].notna() & (df["contrato"].astype(str).str.strip() != "")]
    df["contrato"] = df["contrato"].astype(str).str.strip()

    for coluna in _COLUNAS_TEXTO:
        df[coluna] = df[coluna].astype("string").str.strip()

    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["cnpj"] = df["cnpj_raw"].astype("string").str.replace(r"\D", "", regex=True)
    df["emissao"] = pd.to_datetime(df["emissao_raw"], errors="coerce")
    df["anos_empenho"] = df["empenho"].apply(anos_do_empenho)
    df["nes_empenho"] = df["empenho"].apply(nes_do_empenho)

    # mês de pagamento: a própria aba mensal em que o lançamento está — é literalmente o mês
    # em que o pagamento foi registrado na planilha de origem (uma aba por mês de pagamento).
    df["mes_pagamento"] = pd.to_datetime(dict(year=ano, month=df["mes_ordem"] + 1, day=1))
    # mês de competência: a que período/serviço o pagamento se refere — parseado do texto
    # livre de COMPETENCIA (ver mes_competencia_de); período fracionado usa o mês com mais
    # dias dentro do intervalo, não o mês de início.
    df["mes_competencia"] = df["competencia_raw"].apply(lambda v: mes_competencia_de(v, ano))

    df = df.reset_index(drop=True)

    # duplicidade: mesma combinação contrato+NF+valor lançada em mais de uma aba mensal — a
    # primeira ocorrência (ordem dos meses) é a principal, as demais ficam para auditoria.
    df["chave_duplicidade"] = df["contrato"] + "|" + df["nf"].fillna("").astype(str) + "|" + df["valor"].astype(str)
    df = df.sort_values(["chave_duplicidade", "mes_ordem", "linha_origem"]).reset_index(drop=True)
    df["ocorrencia"] = df.groupby("chave_duplicidade").cumcount()
    df["duplicado"] = df["ocorrencia"] > 0

    def _alertas_de(linha: pd.Series) -> list[str]:
        alertas = []
        if pd.isna(linha["valor"]):
            alertas.append("Valor ausente ou inválido")
        if pd.isna(linha["processo"]) or not str(linha["processo"]).strip():
            alertas.append("Processo ausente")
        if pd.isna(linha["emissao"]):
            alertas.append("Emissão não reconhecida como data")
        return alertas

    df["alertas"] = df.apply(_alertas_de, axis=1)

    def _status_de(linha: pd.Series) -> str:
        if linha["duplicado"]:
            return "Duplicado"
        if any("ausente" in a or "inválid" in a for a in linha["alertas"]):
            return "Bloqueado"
        if linha["alertas"]:
            return "Alerta"
        return "Publicado"

    df["status"] = df.apply(_status_de, axis=1)
    return df


def serie_por_contrato(pagamentos: pd.DataFrame, contrato: str) -> tuple[pd.DataFrame, float]:
    """(linhas por mês, média mensal) dos pagamentos não duplicados de um contrato."""

    reais = pagamentos[(pagamentos["contrato"] == contrato) & (~pagamentos["duplicado"])]
    por_mes = (
        reais.groupby("mes_planilha", sort=False)["valor"]
        .sum()
        .reindex(sorted(reais["mes_planilha"].unique(), key=lambda m: MESES_ORDEM.index(m)))
    )
    media = float(por_mes.mean()) if len(por_mes) else 0.0
    return por_mes.reset_index(name="pago"), media


#: número (dígitos ou "SN" de "sem número") + separador "/" + ano (2 ou 4 dígitos) — o que
#: vem depois (sufixo de unidade, ex. " - SEDE", " -UAST- DEA") é ignorado de propósito: serve
#: só para casar com o número de contrato de Contratos Contínuos (`contrato_numero`, que não
#: carrega esse sufixo), não para preservar o texto original (ver `normalizar_numero_contrato`
#: e a decisão de tratar contratos com o mesmo número base + sufixos diferentes como o MESMO
#: contrato, aprovada antes desta implementação — casa com o padrão já conhecido de contrato
#: faturado por mais de uma unidade, ver `docs`/histórico da conversa).
_CONTRATO_NORMALIZADO_RE = re.compile(r"^\s*(\d+|SN)\s*/\s*(\d{4}|\d{2})\b", re.IGNORECASE)


def normalizar_numero_contrato(valor: object) -> str | None:
    """Número de contrato numa forma canônica para casar Pagamentos com Contratos Contínuos
    (`contrato_numero`) — mesma função aplicada aos dois lados do casamento, para não
    depender de qual base "já está no formato certo". `None` quando o texto não segue o
    padrão "<número ou SN>/<ano>" reconhecível (não é erro: contrato sem esse padrão fica sem
    correspondência, mais seguro que casar errado).

    Regras (aprovadas antes da implementação, ver histórico da conversa):
      * zero à esquerda no número removido ("023" -> "23"; "SN" não é numérico, fica "SN").
      * ano de 2 dígitos expandido para 4 assumindo o século 2000 (só há contratos entre 2017
        e 2026 nos dados conferidos — sem ambiguidade de século nesse intervalo).
      * qualquer texto depois do ano (sufixo de unidade, ex. " - SEDE") é descartado — contratos
        com o mesmo número base e sufixos diferentes viram o MESMO contrato normalizado
        (pedido explícito: são o mesmo contrato faturado por mais de uma unidade).
    """
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    encontrado = _CONTRATO_NORMALIZADO_RE.match(str(valor))
    if not encontrado:
        return None
    numero_texto, ano_texto = encontrado.groups()
    numero = "SN" if numero_texto.upper() == "SN" else str(int(numero_texto))
    ano = int(ano_texto)
    if ano < 100:
        ano += 2000
    return f"{numero}/{ano}"


def meses_pagos_por_contrato(pagamentos: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por número de contrato NORMALIZADO (`normalizar_numero_contrato`), com a
    quantidade de meses distintos em que houve pagamento (`meses_pagos`, a partir de
    `mes_pagamento` — o mês da ABA em que o lançamento está, não `mes_competencia`: é o dado
    mais seguro de "quando o pagamento foi feito", sem depender do texto livre de COMPETENCIA,
    que pode ficar em branco/não reconhecível) e o mês do pagamento mais recente
    (`ultimo_mes_pago`).

    Contratos com o mesmo número normalizado mas sufixos de unidade diferentes na origem (ex.
    "22/2023 - UAST" e outra ocorrência de "22/2023") ficam automaticamente unidos aqui, pois
    `normalizar_numero_contrato` já descarta o sufixo (pedido explícito — mesmo contrato,
    faturado por mais de uma unidade).

    Lançamentos marcados `duplicado` (ver `ler_pagamentos`) ficam de fora, mesmo critério de
    `serie_por_contrato` — uma duplicidade não é um mês novo de pagamento, é o mesmo
    lançamento repetido.
    """
    reais = pagamentos[~pagamentos["duplicado"]].copy()
    reais["contrato_normalizado"] = reais["contrato"].apply(normalizar_numero_contrato)
    reais = reais[reais["contrato_normalizado"].notna()]
    if reais.empty:
        return pd.DataFrame(columns=["contrato_normalizado", "meses_pagos", "ultimo_mes_pago"])

    agregado = reais.groupby("contrato_normalizado")["mes_pagamento"].agg(
        meses_pagos="nunique", ultimo_mes_pago="max"
    )
    return agregado.reset_index()


def soma_por_ne(pagamentos: pd.DataFrame) -> pd.Series:
    """Soma de `valor` por NE (todas as linhas, inclusive as marcadas `duplicado` — a
    reconciliação quer o total que a planilha registra para a NE, para comparar contra o
    valor oficial pago na Execução Anual; ver `app_pages/contratos_pagamentos.py`), indexada
    pela NE completa (mesmo formato de `ne_curta`/`nes_empenho`).

    Só entram pagamentos com exatamente um NE reconhecido no campo `empenho` — quando a
    célula cita mais de um (ex. "25NE000044/25NE000812"), não dá pra saber quanto do valor
    pertence a cada NE, então essas linhas ficam fora da soma (continuam visíveis na tela,
    só não entram nesta reconciliação por NE)."""

    linhas = pagamentos[pagamentos["nes_empenho"].apply(len) == 1]
    if linhas.empty:
        return pd.Series(dtype=float)
    nes = linhas["nes_empenho"].apply(lambda s: next(iter(s)))
    return linhas.groupby(nes)["valor"].sum()
