"""
Leitura e normalização da base MENSAL de Execução da Despesa (BI CPOC / Tesouro Gerencial).

Camada: regra específica de base (não é leitor genérico, não é analítica, não é interface).
Depende apenas de pandas/openpyxl. Não importa Streamlit. Ver docs/base_execucao_mensal.md
para o contrato completo (layout, regra de deduplicação, reconciliação).

LAYOUT ATUAL (extração recebida em 21/09/2026, substitui o formato anterior de aba única —
ver docs/base_execucao_mensal.md, seção "Histórico de layout", para o formato antigo ainda
coberto pela fixture congelada `tests/fixtures/execucao_mensal_2026-09-03.xlsx`):
  * MÚLTIPLAS ABAS, uma por exercício (ex. "2026", "2025", "2024") — `ano` não é mais uma
    coluna de dado, é derivado do nome da aba (decisão explícita do usuário: a extração agora
    cobre 2024-2026, não só 2026+; ler todas as abas presentes, nunca uma lista fixa de anos).
  * 2 linhas de banner de relatório ("Páginas:", "Ano Lançamento: AAAA") + 1 linha em branco
    antes do cabeçalho de 3 linhas (que passou da linha 1 para a linha 4 da planilha).
  * Duas dimensões novas frente ao layout antigo: `Unidade Orçamentária` (par código/descrição,
    logo após PTRES) e `NE - Informação Complementar` (campo único, logo após `NE - Núm.
    Processo`) — nenhuma delas existia na base ANUAL nem no layout antigo desta base.
  * `NE Item` (código + descrição) continua existindo, só que deslocado para depois de `NE CCor
    - Favorecido` (mesma posição relativa ao layout antigo, mas os índices absolutos mudaram
    por causa das duas dimensões novas acima).
  * Além dos blocos mensais reais (`"JAN/2026"` etc.), os exercícios fechados trazem blocos de
    encerramento rotulados `"013/AAAA"`/`"014/AAAA"` no fim — decisão explícita do usuário:
    ignorados (não entram no resultado), tratados como blocos conhecidos-e-descartados, não
    como erro de layout.
  * Em vez de 1 bloco anual de Empenhada/Liquidada/Paga, há N blocos mensais (um por mês
    presente na extração) — detectados dinamicamente a partir do rótulo de cada bloco na
    primeira linha do cabeçalho, nunca um número fixo de meses hardcoded (a extração cresce
    um mês por vez ao longo do exercício).
  * (22/09/2026) `Fonte Recursos Detalhada` (par código/descrição) passou a vir logo após
    `Fonte Recursos` — pedido do usuário para viabilizar o cruzamento com a Dotação Anual no
    mesmo nível de detalhe da Fonte (`src.painel_acoes_empenho` documentava a colisão de
    granularidade entre as duas bases antes disso: Execução só tinha a Fonte de 3 dígitos,
    Dotação tinha os 10 dígitos). Confirmei comparando `BI CPOC - EXEC. DESPESAS - Por Ano
    (7).xlsx` (formato anterior, já importado) contra a `(8).xlsx` (nova extração) linha a
    linha: a ÚNICA diferença é este par de colunas inserido entre `Fonte Recursos` e `Grupo
    Despesa` — todo o resto do layout (árvore mensal, blocos, NE Item) é idêntico.

A REGRA QUE MUDA TUDO NESTA BASE: dentro de uma mesma NE, o valor "Empenhada" de um mês
aparece IDÊNTICO, repetido, em todas as linhas de `NE Item` que compartilham a mesma
`Natureza Despesa Detalhada`/`Subitem` — o valor é o total daquele (NE, Subitem, mês), não um
valor por item. Confirmado manualmente contra a extração de referência (ver
docs/base_execucao_mensal.md, seção de validação): somar direto por linha de item multiplica
o Empenhado pela quantidade de itens do subitem. A leitura aqui devolve a granularidade bruta
(uma linha por combinação original × mês, preservando `ne_item_cod`/`ne_item_desc` para busca
textual); `valor_empenhado_por_bloco` faz a deduplicação correta antes de somar.

Contrato público:
    ler_execucao_mensal(caminho) -> pd.DataFrame          (uma linha por linha bruta × mês)
    valor_empenhado_por_bloco(df) -> pd.DataFrame         (empenhada deduplicada por NE/bloco/mês)
    liquidado_por_ne_e_mes(df) -> pd.DataFrame            (liquidado por NE/mês de lançamento, sem preencher 0)
    reconciliar(df) -> dict
    validar(df, esperado=None) -> RelatorioValidacao
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.cache_bases import em_cache
from src.leitura_excel import motor_excel

# --------------------------------------------------------------------------------------
# 1. Contrato do arquivo de origem
# --------------------------------------------------------------------------------------

#: linhas de relatório antes do cabeçalho ("Páginas:", "Ano Lançamento: AAAA", em branco).
LINHAS_BANNER = 3
LINHAS_CABECALHO = 3
#: total de linhas puladas antes dos dados = banner + cabeçalho.
LINHAS_PULADAS = LINHAS_BANNER + LINHAS_CABECALHO
PRIMEIRA_LINHA_DADOS_PLANILHA = LINHAS_PULADAS + 1

#: colunas dimensionais (0-40) na ordem/posição da extração atual (21/09/2026). `ano` NÃO é
#: uma coluna aqui — é derivado do nome da aba (ver docstring do módulo) e acrescentado depois
#: da leitura bruta.
COLUNAS_DIMENSAO = [
    "iduso_cod", "iduso_desc",
    "resultado_primario_cod", "resultado_primario_desc",
    "categoria_economica_cod", "categoria_economica_desc",
    "acao_cod", "acao_desc",
    "elemento_cod", "elemento_desc",
    "fonte_cod", "fonte_desc",
    "fonte_recursos_detalhada_cod", "fonte_recursos_detalhada_desc",
    "gnd_cod", "gnd_desc",
    "natureza_despesa_cod", "natureza_despesa_desc",
    "natureza_detalhada_cod", "natureza_detalhada_desc",
    "subitem_cod", "subitem_desc",
    "pi_cod", "pi_desc",
    "po_acao_cod", "po_cod", "po_desc",
    "ptres",
    "unidade_orcamentaria_cod", "unidade_orcamentaria_desc",
    "ug_executora_cod", "ug_executora_desc",
    "ug_responsavel_cod", "ug_responsavel_desc",
    "ugr_cod", "ugr_desc",
    "processo_ne",
    "ne_informacao_complementar",
    "ne_descricao", "ne_ccor", "ne_favorecido",
    "ne_item_cod", "ne_item_desc",
]

#: posição (0-indexada) da primeira coluna do primeiro bloco mensal.
PRIMEIRA_COLUNA_MESES = len(COLUNAS_DIMENSAO)
#: posição da coluna `ne_item_cod` (as duas últimas colunas dimensionais são o par NE Item).
_COLUNA_NE_ITEM = PRIMEIRA_COLUNA_MESES - 2

MEDIDAS = ["empenhada", "liquidada", "paga"]

_SENTINELAS_PROCESSO = {"'-9", "'-8"}
MARCADOR_ITEM_EXECUCAO = "NAO SE APLICA"
_SENTINELA_SEM_ITEM = "-9"

#: mês abreviado (Tesouro Gerencial, PT-BR, maiúsculo) -> número do mês.
_MESES_PT = {
    "JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12,
}
_PADRAO_ROTULO_MES = re.compile(r"^([A-ZÇ]{3})/(\d{4})$")

#: blocos de encerramento de exercício ("013/2025", "014/2025", ...) — período numérico de 3
#: dígitos em vez de mês. Decisão explícita do usuário (21/09/2026): ignorar estes blocos, não
#: tratar como erro de layout (ver docstring do módulo).
_PADRAO_ROTULO_ENCERRAMENTO = re.compile(r"^0\d{2}/(\d{4})$")

#: âncoras de posição fixa (linha 1 do cabeçalho, já sem as linhas de banner, 0-indexada).
#: Posições deslocadas em +2 a partir de "Grupo Despesa" em 22/09/2026 — nova extração
#: passou a incluir "Fonte Recursos Detalhada" (par código/descrição, decisão do usuário)
#: logo após "Fonte Recursos" (posições 10-11), pedido pra viabilizar cruzamento com a
#: Dotação Anual sem a perda de granularidade documentada em `src.painel_acoes_empenho`.
_ANCORAS_LINHA1 = {
    0: "Iduso", 14: "Grupo Despesa", 27: "PTRES",
    28: "Unidade Or", 36: "NE - N",
}


class ErroLayoutBase(ValueError):
    """Layout do arquivo diferente do contrato — falhar cedo, nunca adivinhar."""


# --------------------------------------------------------------------------------------
# 2. Leitura
# --------------------------------------------------------------------------------------

def _rotulo_mes(texto: object) -> tuple[int, int] | None:
    """`"JAN/2026"` -> `(2026, 1)`. `None` se não casar o padrão (não é um rótulo de mês)."""

    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return None
    encontrado = _PADRAO_ROTULO_MES.match(str(texto).strip().upper())
    if not encontrado or encontrado.group(1) not in _MESES_PT:
        return None
    return int(encontrado.group(2)), _MESES_PT[encontrado.group(1)]


def _blocos_mensais(cabecalho_linha1: list) -> list[tuple[int, int, int]]:
    """A partir da linha 1 do cabeçalho (rótulos "JAN/2026" repetidos 3x por bloco), devolve
    uma lista `(coluna_empenhada, ano, mes)` por bloco encontrado — nunca um número de meses
    fixo: a extração ganha um bloco novo a cada mês que passa, e ler menos ou mais meses do
    que os presentes no arquivo não deve exigir alterar este módulo."""

    blocos: list[tuple[int, int, int]] = []
    coluna = PRIMEIRA_COLUNA_MESES
    total = len(cabecalho_linha1)
    while coluna < total:
        if coluna + 2 >= total:
            raise ErroLayoutBase(
                f"Bloco incompleto a partir da coluna {coluna + 1} — "
                "cada bloco precisa de 3 colunas (Empenhada, Liquidada, Paga)."
            )
        rotulo = _rotulo_mes(cabecalho_linha1[coluna])
        if rotulo is not None:
            ano, mes = rotulo
            blocos.append((coluna, ano, mes))
            coluna += 3
            continue
        texto = str(cabecalho_linha1[coluna] or "").strip()
        if _PADRAO_ROTULO_ENCERRAMENTO.match(texto):
            # Bloco de encerramento de exercício (ex. "013/2025") — conhecido e
            # deliberadamente descartado, não é um erro de layout (ver docstring do módulo).
            coluna += 3
            continue
        raise ErroLayoutBase(
            f"Coluna {coluna + 1}: esperado um rótulo de mês (ex. 'JAN/2026') ou de "
            f"encerramento (ex. '013/2025'), obtido {cabecalho_linha1[coluna]!r}."
        )
    if not blocos:
        raise ErroLayoutBase("Nenhum bloco mensal encontrado após as colunas dimensionais.")
    return blocos


#: 4 dígitos — nome de aba esperado (um exercício por aba, ver docstring do módulo).
_PADRAO_NOME_ABA_ANO = re.compile(r"^(\d{4})$")


def _validar_assinatura(xls: pd.ExcelFile, sheet_name: str) -> list[tuple[int, int, int]]:
    """Confere as âncoras fixas e devolve os blocos mensais detectados (ver `_blocos_mensais`)
    — a mesma leitura serve de validação e de mapa de colunas, para nunca divergir uma da
    outra. `sheet_name` é o exercício da aba (validado como o próprio ano de referência)."""

    if not _PADRAO_NOME_ABA_ANO.match(sheet_name):
        raise ErroLayoutBase(
            f"Nome de aba {sheet_name!r}: esperado um exercício de 4 dígitos (ex. '2026')."
        )

    cabecalho = pd.read_excel(
        xls, sheet_name=sheet_name, header=None, skiprows=LINHAS_BANNER, nrows=LINHAS_CABECALHO, dtype=str
    )
    linha1 = cabecalho.iloc[0].tolist()

    for pos, esperado in _ANCORAS_LINHA1.items():
        obtido = str(linha1[pos] or "")
        if not obtido.strip().upper().startswith(esperado.upper()):
            raise ErroLayoutBase(
                f"Aba {sheet_name!r}, coluna {pos + 1}: esperado cabeçalho iniciando por "
                f"{esperado!r}, obtido {obtido!r}."
            )

    # As 3 linhas do cabeçalho, sobrepostas na coluna `ne_item_cod` (a penúltima dimensional):
    # linha 1 = rótulo de grupo (irrelevante aqui, não validado), linha 2 = 'Item Informação',
    # linha 3 = 'NE Item' — mesmo espírito do deslocamento documentado para a base anual
    # (docs/base_execucao_anual.md), só que em 3 linhas de cabeçalho, não 2. Os blocos
    # mensais (e as colunas Empenhada/Liquidada/Paga da linha 2) só começam de fato em
    # PRIMEIRA_COLUNA_MESES.
    linha2 = cabecalho.iloc[1].tolist()
    if str(linha2[_COLUNA_NE_ITEM] or "").strip() != "Item Informação":
        raise ErroLayoutBase(
            f"Aba {sheet_name!r}, coluna {_COLUNA_NE_ITEM + 1} (linha 2): esperado "
            f"'Item Informação', obtido {linha2[_COLUNA_NE_ITEM]!r}."
        )
    for deslocamento, esperado in enumerate(("DESPESAS EMPENHADAS", "DESPESAS LIQUIDADAS", "DESPESAS PAGAS")):
        obtido = str(linha2[PRIMEIRA_COLUNA_MESES + deslocamento] or "")
        if not obtido.strip().upper().startswith(esperado):
            raise ErroLayoutBase(
                f"Aba {sheet_name!r}, coluna {PRIMEIRA_COLUNA_MESES + 1 + deslocamento} (linha 2): "
                f"esperado iniciando por {esperado!r}, obtido {obtido!r}."
            )

    linha3 = cabecalho.iloc[2].tolist()
    if str(linha3[_COLUNA_NE_ITEM] or "").strip() != "NE Item":
        raise ErroLayoutBase(
            f"Aba {sheet_name!r}, coluna {_COLUNA_NE_ITEM + 1} (linha 3): esperado 'NE Item', "
            f"obtido {linha3[_COLUNA_NE_ITEM]!r}."
        )

    return _blocos_mensais(linha1)


def _para_numero(serie: pd.Series) -> pd.Series:
    """Mesma conversão de `src.execucao_anual._para_numero` (texto monetário -> float,
    preservando NaN)."""

    limpo = (
        serie.astype("string")
        .str.strip()
        .str.replace(r"^R\$\s*", "", regex=True)
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    original = pd.to_numeric(serie.astype("string").str.strip(), errors="coerce")
    convertido = pd.to_numeric(limpo, errors="coerce")
    return original.where(original.notna(), convertido)


def _ler_aba(xls: pd.ExcelFile, nome_arquivo: str, sheet_name: str) -> pd.DataFrame:
    """Lê e normaliza uma única aba (um exercício) — ver `ler_execucao_mensal` para o
    contrato público, que concatena todas as abas da planilha."""

    blocos = _validar_assinatura(xls, sheet_name)
    ano_aba = int(sheet_name)

    bruto = pd.read_excel(xls, sheet_name=sheet_name, header=None, skiprows=LINHAS_PULADAS, dtype=str)

    dimensoes = bruto.iloc[:, :PRIMEIRA_COLUNA_MESES].copy()
    dimensoes.columns = COLUNAS_DIMENSAO
    for col in COLUNAS_DIMENSAO:
        dimensoes[col] = dimensoes[col].astype("string").str.strip()
    dimensoes["ano"] = pd.array([ano_aba] * len(dimensoes), dtype="int16")
    dimensoes["processo_ne"] = dimensoes["processo_ne"].mask(dimensoes["processo_ne"].isin(_SENTINELAS_PROCESSO))
    dimensoes.insert(0, "linha_origem", range(PRIMEIRA_LINHA_DADOS_PLANILHA, PRIMEIRA_LINHA_DADOS_PLANILHA + len(bruto)))
    dimensoes.insert(1, "arquivo_origem", nome_arquivo)
    dimensoes.insert(2, "aba_origem", sheet_name)

    eh_item = dimensoes["ne_descricao"].fillna("").str.upper().eq(MARCADOR_ITEM_EXECUCAO)
    dimensoes["tipo_linha"] = pd.Series("empenho", index=dimensoes.index, dtype="string").mask(eh_item, "item_execucao")
    dimensoes["ne_ano"] = dimensoes["ne_ccor"].str.slice(11, 15)
    dimensoes["ne_numero"] = dimensoes["ne_ccor"].str.slice(15)
    dimensoes["natureza_detalhada_label"] = dimensoes["natureza_detalhada_cod"] + " - " + dimensoes["natureza_detalhada_desc"]
    dimensoes["tem_item"] = dimensoes["ne_item_cod"].notna() & dimensoes["ne_item_cod"].ne(_SENTINELA_SEM_ITEM)

    partes = []
    for coluna_empenhada, ano_bloco, mes_bloco in blocos:
        parte = dimensoes.copy()
        parte["mes"] = mes_bloco
        parte["ano_mes"] = ano_bloco * 100 + mes_bloco
        parte["empenhada"] = _para_numero(bruto.iloc[:, coluna_empenhada])
        parte["liquidada"] = _para_numero(bruto.iloc[:, coluna_empenhada + 1])
        parte["paga"] = _para_numero(bruto.iloc[:, coluna_empenhada + 2])
        partes.append(parte)

    return pd.concat(partes, ignore_index=True)


@em_cache
def ler_execucao_mensal(caminho: str | Path) -> pd.DataFrame:
    """Lê a base bruta e devolve o DataFrame normalizado em formato longo — uma linha por
    (linha original da planilha × mês do bloco correspondente), com `mes`/`ano_mes` derivados
    do rótulo do próprio bloco. TODAS as abas presentes na planilha são lidas e concatenadas —
    uma por exercício, nunca uma lista fixa de anos (ver docstring do módulo). Sem agregar
    nada — para a soma financeira correta, ver `valor_empenhado_por_bloco`."""

    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(caminho)

    with pd.ExcelFile(caminho, engine=motor_excel()) as xls:
        abas = xls.sheet_names
        if not abas:
            raise ErroLayoutBase("Planilha sem nenhuma aba.")
        resultado = pd.concat((_ler_aba(xls, caminho.name, aba) for aba in abas), ignore_index=True)

    return resultado.sort_values(["ano", "linha_origem", "ano_mes"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# 3. A deduplicação que esta base exige (ver docstring do módulo)
# --------------------------------------------------------------------------------------

#: chave de um "bloco" dentro de uma NE: mesma NE, mesma classificação orçamentária
#: (Natureza Detalhada + Subitem — a granularidade real do valor empenhado) e mesmo mês. O
#: valor "Empenhada" é idêntico em toda linha de item que compartilha essa chave; somar sem
#: deduplicar primeiro multiplica o Empenhado pela quantidade de itens do bloco.
_CHAVE_BLOCO = ["ne_ccor", "natureza_detalhada_cod", "subitem_cod", "ano_mes"]


#: dimensões extra incluídas no resultado de `valor_empenhado_por_bloco`, além da chave do
#: bloco em si — todas constantes dentro de um bloco (mesma NE, mesma Natureza
#: Detalhada/Subitem, mesmo mês), então `"first"` nunca perde nem mistura dado; existem aqui
#: só para permitir composição por dimensão (ex.: Empenhado por GND) sem duplicar a conta.
_DIMENSOES_EXTRA_BLOCO = {
    "elemento_cod": "elemento_cod", "elemento_desc": "elemento_desc",
    "natureza_detalhada_desc": "natureza_detalhada_desc",
    "gnd_cod": "gnd_cod", "gnd_desc": "gnd_desc",
    "fonte_cod": "fonte_cod", "fonte_desc": "fonte_desc",
    "acao_cod": "acao_cod", "acao_desc": "acao_desc",
    "ugr_cod": "ugr_cod", "ugr_desc": "ugr_desc",
    "ptres": "ptres",
    "po_cod": "po_cod", "po_desc": "po_desc",
    "resultado_primario_cod": "resultado_primario_cod", "resultado_primario_desc": "resultado_primario_desc",
    "iduso_cod": "iduso_cod", "iduso_desc": "iduso_desc",
}


def valor_empenhado_por_bloco(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (NE, Natureza Detalhada, Subitem, mês) — o valor "Empenhada" correto
    desta base, sem a duplicação por item. Linhas de item de execução (`tipo_linha ==
    "item_execucao"`, sem `ne_item_cod` real) não têm empenhada própria e ficam de fora; usar
    `df` bruto para Liquidada/Paga, que vêm de lá (ver docs/base_execucao_mensal.md)."""

    linhas_empenho = df.loc[df["tipo_linha"] == "empenho"]
    agregacoes = {nome: (coluna, "first") for nome, coluna in _DIMENSOES_EXTRA_BLOCO.items()}
    agregacoes["empenhada"] = ("empenhada", "first")
    agregacoes["qtd_itens"] = ("ne_item_cod", "nunique")
    return linhas_empenho.groupby(_CHAVE_BLOCO, dropna=False).agg(**agregacoes).reset_index()


def linha_do_tempo_por_ne(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por (NE, mês): Empenhado (já deduplicado por bloco — soma correta entre
    Naturezas Detalhadas/Subitens diferentes da MESMA NE, sem duplicar dentro de cada um),
    Liquidado e Pago — para mostrar a evolução mensal de uma NE específica (ex.: painel de
    detalhe de `app_pages/consulta_empenhos.py`). Todas as NEs do recorte, não só uma: filtre
    o resultado por `ne_ccor` depois de chamar."""

    dedup = valor_empenhado_por_bloco(df)
    empenhada = dedup.groupby(["ne_ccor", "ano_mes"])["empenhada"].sum()

    liquidado_pago = df.loc[df["tipo_linha"] == "item_execucao"]
    liquidada_paga = liquidado_pago.groupby(["ne_ccor", "ano_mes"])[["liquidada", "paga"]].sum(min_count=1)

    resultado = pd.DataFrame({"empenhada": empenhada}).join(liquidada_paga, how="outer").fillna(0.0)
    return resultado.reset_index().sort_values(["ne_ccor", "ano_mes"]).reset_index(drop=True)


def liquidado_por_ne_e_mes(df: pd.DataFrame) -> pd.DataFrame:
    """Liquidado por (NE, mês de LANÇAMENTO) — colunas `ne_ccor`, `ano_mes`, `valor`, mesmo
    formato de `src.liquidacao_competencia.liquidado_por_ne_e_mes` (que é por mês de
    competência). Ao contrário de `linha_do_tempo_por_ne`, NÃO preenche com 0: só entram os
    (NE, mês) com ao menos uma linha de item de execução com Liquidado informado
    (`min_count=1` — mês só com nulos fica fora, zero real fica como 0). Sinal preservado."""

    itens = df.loc[df["tipo_linha"] == "item_execucao"]
    return (
        itens.groupby(["ne_ccor", "ano_mes"])["liquidada"]
        .sum(min_count=1)
        .dropna()
        .reset_index()
        .rename(columns={"liquidada": "valor"})
        .sort_values(["ne_ccor", "ano_mes"])
        .reset_index(drop=True)
    )


#: dimensões constantes dentro de uma NE (mesmo espírito de
#: `src.execucao_anual._DIMENSOES_CONSTANTES_POR_NE`, verificado contra a extração de
#: referência: nenhuma das 2.567 NEs tem mais de um valor distinto em nenhum destes campos —
#: ver commit que introduziu esta função). `natureza_detalhada`/`subitem` ficam de fora de
#: propósito — mesma exceção da Base Anual, uma NE pode ter mais de uma classificação.
_DIMENSOES_CONSTANTES_POR_NE = [
    "ano",
    "iduso_cod", "iduso_desc",
    "resultado_primario_cod", "resultado_primario_desc",
    "categoria_economica_cod", "categoria_economica_desc",
    "acao_cod", "acao_desc",
    "elemento_cod", "elemento_desc",
    "fonte_cod", "fonte_desc",
    "gnd_cod", "gnd_desc",
    "natureza_despesa_cod", "natureza_despesa_desc",
    "pi_cod", "pi_desc",
    "po_acao_cod", "po_cod", "po_desc",
    "ptres",
    "unidade_orcamentaria_cod", "unidade_orcamentaria_desc",
    "ug_executora_cod", "ug_executora_desc",
    "ug_responsavel_cod", "ug_responsavel_desc",
    "ugr_cod", "ugr_desc",
    "ne_informacao_complementar",
    "ne_favorecido",
]


def _resumo_classificacao(valores: pd.Series) -> str:
    """Valor único se a NE tem só uma classificação; contagem, caso contrário. Mesma função
    de `src.execucao_anual._resumo_classificacao`, duplicada aqui de propósito — os dois
    módulos não se importam entre si (bases independentes, ver docstring do módulo)."""

    unicos = valores.dropna().unique()
    if len(unicos) == 0:
        return "—"
    if len(unicos) == 1:
        return str(unicos[0])
    return f"{len(unicos)} classificações"


def agregar_por_ne(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por NE — para consulta/navegação, não para reconciliação financeira (para
    isso, `valor_empenhado_por_bloco`/`reconciliar`, que nunca perdem granularidade). Mesmo
    contrato de `src.execucao_anual.agregar_por_ne`, adaptado à granularidade extra desta
    base (mês + Natureza Detalhada/Subitem por bloco):

      * `empenhada` soma `valor_empenhado_por_bloco` (já deduplicada) por NE, entre todos os
        blocos E todos os meses — o total empenhado da NE até agora, não um valor mensal.
      * `liquidada`/`paga` somam direto as linhas de item de execução da NE (não duplicam por
        item nem por bloco, só por mês — soma entre meses é a correta).
      * `ne_descricao`/`processo_ne` vêm só das linhas de tipo "empenho" (mesma razão da Base
        Anual: linhas de item de execução trazem sentinela, não o dado real).
      * Natureza Detalhada/Subitem resumidos como "N classificações" quando a NE tem mais de
        uma (mesma exceção da Base Anual).
    """

    dedup_bloco = valor_empenhado_por_bloco(df)
    empenhada_por_ne = dedup_bloco.groupby("ne_ccor")["empenhada"].sum(min_count=1)

    liquidado_pago = df.loc[df["tipo_linha"] == "item_execucao"]
    liquidada_paga_por_ne = liquidado_pago.groupby("ne_ccor")[["liquidada", "paga"]].sum(min_count=1)

    agregacoes: dict[str, object] = {coluna: "first" for coluna in _DIMENSOES_CONSTANTES_POR_NE}
    agregacoes["natureza_detalhada_label"] = _resumo_classificacao
    agregacoes["subitem_cod"] = _resumo_classificacao
    resultado = df.groupby("ne_ccor", dropna=False).agg(agregacoes)

    resultado["empenhada"] = empenhada_por_ne
    resultado[["liquidada", "paga"]] = liquidada_paga_por_ne

    so_empenho = df.loc[df["tipo_linha"] == "empenho"].groupby("ne_ccor")
    resultado["ne_descricao"] = so_empenho["ne_descricao"].first()
    resultado["processo_ne"] = so_empenho["processo_ne"].first()

    resultado = resultado.reset_index().rename(columns={"subitem_cod": "subitem_resumo"})
    return resultado.sort_values("ne_ccor").reset_index(drop=True)


def primeiro_mes_com_empenho_por_ne(tempo_com_ne_curta: pd.DataFrame) -> pd.Series:
    """Mês (1-12) do primeiro `ano_mes` em que cada NE teve Empenhado > 0 — usado como
    referência automática de "quando a execução daquela NE começou" (pedido explícito:
    "o sistema faz essa análise e usa a data do primeiro empenho como referencial", ver
    `src.necessidade_empenho.necessidade_ate_mes_vigente`), para quando o cadastro não tem um
    mês de início informado manualmente. Recebe o resultado de `linha_do_tempo_por_ne` já com
    uma coluna `ne_curta` acrescentada (mesmo padrão de
    `app_pages/bolsas_auxilios.py`/`app_pages/contratos_continuos.py::_cached_linha_do_tempo`
    — esta função não sabe converter `ne_ccor` pra `ne_curta` sozinha). Devolve uma Series
    indexada por `ne_curta`; NE sem nenhum mês com empenho > 0 não aparece no resultado."""

    com_empenho = tempo_com_ne_curta[tempo_com_ne_curta["empenhada"] > 0]
    primeiro_ano_mes = com_empenho.groupby("ne_curta")["ano_mes"].min()
    return (primeiro_ano_mes % 100).astype(int)


# --------------------------------------------------------------------------------------
# 4. Reconciliação e validação
# --------------------------------------------------------------------------------------

def reconciliar(df: pd.DataFrame) -> dict:
    """Totais que devem bater com a origem — Empenhado já deduplicado por bloco (ver
    `valor_empenhado_por_bloco`); Liquidado/Pago somados direto (não duplicam por item: só
    aparecem nas linhas de item de execução, uma por NE×mês).

    `anos`/`totais_por_ano` (uma medida por ano, as 3) seguem o mesmo contrato de
    `src.execucao_anual.reconciliar` — exigido por `src.importacao_versionada.gerar_manifesto`/
    `comparar` (ver `src/importacao_execucao_mensal.py`, que amarra esta base a esse núcleo
    genérico)."""

    empenhado_dedup = valor_empenhado_por_bloco(df)
    liquidado_pago = df.loc[df["tipo_linha"] == "item_execucao"]

    emp_por_ano = empenhado_dedup.assign(ano=empenhado_dedup["ano_mes"] // 100).groupby("ano")["empenhada"].sum()
    lp_por_ano = liquidado_pago.groupby("ano")[["liquidada", "paga"]].sum(min_count=1)
    anos = sorted(set(df["ano"].unique().tolist()))

    return {
        "linhas": int(len(df)),
        "linhas_originais": int(df["linha_origem"].nunique()),
        "meses": sorted(df["ano_mes"].unique().tolist()),
        "anos": anos,
        "notas_empenho_distintas": int(df["ne_ccor"].nunique()),
        "totais": {
            "empenhada": round(float(empenhado_dedup["empenhada"].sum()), 2),
            "liquidada": round(float(liquidado_pago["liquidada"].sum(min_count=1) or 0.0), 2),
            "paga": round(float(liquidado_pago["paga"].sum(min_count=1) or 0.0), 2),
        },
        "totais_por_ano": {
            int(ano): {
                "empenhada": round(float(emp_por_ano.get(ano, 0.0)), 2),
                "liquidada": round(float(lp_por_ano.loc[ano, "liquidada"]), 2) if ano in lp_por_ano.index and pd.notna(lp_por_ano.loc[ano, "liquidada"]) else None,
                "paga": round(float(lp_por_ano.loc[ano, "paga"]), 2) if ano in lp_por_ano.index and pd.notna(lp_por_ano.loc[ano, "paga"]) else None,
            }
            for ano in anos
        },
    }


@dataclass
class RelatorioValidacao:
    ok: bool
    erros: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)
    resumo: dict = field(default_factory=dict)


def validar(df: pd.DataFrame, esperado: dict | None = None) -> RelatorioValidacao:
    """Validações estruturais e de coerência. `esperado` no formato de `reconciliar`."""

    erros: list[str] = []
    alertas: list[str] = []
    resumo = reconciliar(df)

    if df["ano"].isna().any():
        erros.append("Há linhas sem Ano Lançamento.")
    if df["ne_ccor"].isna().any() or df["ne_ccor"].eq("").any():
        erros.append("Há linhas sem NE CCor.")
    if not df["ne_ano"].eq(df["ano"].astype(str)).all():
        alertas.append(
            "Existem linhas cujo ano da NE difere do Ano Lançamento — possível resto a pagar; "
            "a leitura por mês assume que isso não acontece (confirmado pelo usuário para esta base)."
        )
    if not df["ano_mes"].astype(str).str.slice(0, 4).eq(df["ano"].astype(str)).all():
        alertas.append("Existe bloco mensal com ano diferente do Ano Lançamento da própria linha.")

    empenhado_dedup = valor_empenhado_por_bloco(df)
    if (empenhado_dedup["qtd_itens"] < 1).any():
        erros.append("Há bloco (NE, Natureza Detalhada, Subitem, mês) sem nenhum item associado.")

    # Liquidada/Paga são movimentos INCREMENTAIS de cada mês (não saldo acumulado) — um
    # pagamento registrado em maio pode ser referente a uma liquidação de abril, então
    # comparar mês a mês isoladamente é o teste errado (gera falso "pago > liquidado" sempre
    # que o pagamento atrasa um mês em relação à liquidação). A coerência real é ACUMULADA ao
    # longo do exercício, mesmo espírito da checagem anual de `execucao_anual.validar` — mas
    # reiniciada a cada exercício (a base agora cobre vários anos por aba, ver docstring do
    # módulo): acumular de dezembro de um ano para janeiro do seguinte seria incoerente.
    liquidado_pago = df.loc[df["tipo_linha"] == "item_execucao"]
    por_mes = liquidado_pago.groupby("ano_mes")[["liquidada", "paga"]].sum(min_count=1).fillna(0.0).sort_index()
    acumulado = por_mes.groupby(por_mes.index // 100).cumsum()
    excede = acumulado[acumulado["paga"] - acumulado["liquidada"] > 0.01]
    for ano_mes in excede.index:
        erros.append(f"Acumulado até {ano_mes}: pago maior que liquidado.")

    if esperado:
        for medida, valor in esperado.get("totais", {}).items():
            obtido = resumo["totais"][medida]
            if abs(obtido - valor) > 0.01:
                erros.append(f"Total de {medida}: esperado {valor:.2f}, obtido {obtido:.2f}.")

    return RelatorioValidacao(ok=not erros, erros=erros, alertas=alertas, resumo=resumo)


if __name__ == "__main__":  # inspeção rápida
    import sys

    dados = ler_execucao_mensal(sys.argv[1])
    rel = validar(dados)
    print(rel.resumo)
    print("ERROS:", rel.erros or "nenhum")
    print("ALERTAS:", rel.alertas or "nenhum")
