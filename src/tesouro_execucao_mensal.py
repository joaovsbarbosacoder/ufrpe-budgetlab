"""
Leitura e normalização da base MENSAL de Execução da Despesa (BI CPOC / Tesouro Gerencial),
a partir do exercício 2026 — sucessora, só para 2026 em diante, da base ANUAL existente
(`src/execucao_anual.py`, que continua a fonte de 2023-2025 e não é substituída por esta).

Camada: regra específica de base (não é leitor genérico, não é analítica, não é interface).
Depende apenas de pandas/openpyxl. Não importa Streamlit. Ver docs/base_execucao_mensal.md
para o contrato completo (layout, regra de deduplicação, reconciliação).

Diferenças de layout frente à base anual (mesma origem BI CPOC, mesmas 38 colunas
dimensionais nas mesmas posições):
  * Cabeçalho ocupa 3 linhas (não 2) — uma linha a mais no topo com o rótulo do mês
    ("JAN/2026" etc.) por cima de cada bloco mensal.
  * Uma dimensão nova, `NE Item` (código + descrição), entre `NE CCor - Favorecido` e
    `Ano Lançamento` — descreve o item/produto/rubrica dentro do empenho (ex.: elemento 30,
    "Item compra: 00201 - PAPEL FILME...").
  * Em vez de 1 bloco anual de Empenhada/Liquidada/Paga, há N blocos mensais (um por mês
    presente na extração) — detectados dinamicamente a partir do rótulo de cada bloco na
    primeira linha do cabeçalho, nunca um número fixo de meses hardcoded (a extração cresce
    um mês por vez ao longo do exercício).

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
    reconciliar(df) -> dict
    validar(df, esperado=None) -> RelatorioValidacao
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------------------
# 1. Contrato do arquivo de origem
# --------------------------------------------------------------------------------------

LINHAS_CABECALHO = 3
PRIMEIRA_LINHA_DADOS_PLANILHA = 4

#: colunas dimensionais (0-37), mesma posição/ordem/nome que `src.execucao_anual.COLUNAS` —
#: reaproveitado de propósito (mesma origem BI CPOC) até a posição da "NE CCor - Favorecido".
COLUNAS_DIMENSAO = [
    "iduso_cod", "iduso_desc",
    "resultado_primario_cod", "resultado_primario_desc",
    "categoria_economica_cod", "categoria_economica_desc",
    "acao_cod", "acao_desc",
    "elemento_cod", "elemento_desc",
    "fonte_cod", "fonte_desc",
    "gnd_cod", "gnd_desc",
    "natureza_despesa_cod", "natureza_despesa_desc",
    "natureza_detalhada_cod", "natureza_detalhada_desc",
    "subitem_cod", "subitem_desc",
    "pi_cod", "pi_desc",
    "po_acao_cod", "po_cod", "po_desc",
    "ptres",
    "ug_executora_cod", "ug_executora_desc",
    "ug_responsavel_cod", "ug_responsavel_desc",
    "ugr_cod", "ugr_desc",
    "processo_ne",
    "ne_descricao", "ne_ccor", "ne_favorecido",
    "ne_item_cod", "ne_item_desc",
    "ano",
]

#: posição (0-indexada) da primeira coluna do primeiro bloco mensal — logo após `ano`.
PRIMEIRA_COLUNA_MESES = len(COLUNAS_DIMENSAO)

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

#: âncoras de posição fixa (linha 1 do cabeçalho, 0-indexada) — mesmo espírito de
#: `execucao_anual.ASSINATURA_CABECALHO`, adaptado às 3 linhas e à coluna NE Item nova.
_ANCORAS_LINHA1 = {0: "Iduso", 12: "Grupo Despesa", 25: "PTRES", 32: "NE - N", 36: "NE Item"}


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
        rotulo = _rotulo_mes(cabecalho_linha1[coluna])
        if rotulo is None:
            raise ErroLayoutBase(
                f"Coluna {coluna + 1}: esperado um rótulo de mês (ex. 'JAN/2026'), "
                f"obtido {cabecalho_linha1[coluna]!r}."
            )
        if coluna + 2 >= total:
            raise ErroLayoutBase(
                f"Bloco mensal incompleto a partir da coluna {coluna + 1} — "
                "cada mês precisa de 3 colunas (Empenhada, Liquidada, Paga)."
            )
        ano, mes = rotulo
        blocos.append((coluna, ano, mes))
        coluna += 3
    if not blocos:
        raise ErroLayoutBase("Nenhum bloco mensal encontrado após as colunas dimensionais.")
    return blocos


def _validar_assinatura(caminho: Path) -> list[tuple[int, int, int]]:
    """Confere as âncoras fixas e devolve os blocos mensais detectados (ver `_blocos_mensais`)
    — a mesma leitura serve de validação e de mapa de colunas, para nunca divergir uma da
    outra."""

    cabecalho = pd.read_excel(caminho, header=None, nrows=3, dtype=str)
    linha1 = cabecalho.iloc[0].tolist()

    for pos, esperado in _ANCORAS_LINHA1.items():
        obtido = str(linha1[pos] or "")
        if not obtido.strip().upper().startswith(esperado.upper()):
            raise ErroLayoutBase(
                f"Coluna {pos + 1}: esperado cabeçalho iniciando por {esperado!r}, obtido {obtido!r}."
            )

    # 'Item Informação'/'Ano Lançamento' ficam sobrepostos na própria coluna `ano` (a última
    # dimensional, índice PRIMEIRA_COLUNA_MESES - 1) — mesmo deslocamento já documentado para
    # a base anual (ver docs/base_execucao_anual.md, "o rótulo Item Informação da linha 1 está
    # deslocado sobre a coluna de ano"); só que aqui em duas linhas de cabeçalho diferentes,
    # não uma. Os meses (e as colunas Empenhada/Liquidada/Paga da linha 2) só começam de fato
    # em PRIMEIRA_COLUNA_MESES.
    coluna_ano = PRIMEIRA_COLUNA_MESES - 1
    linha2 = cabecalho.iloc[1].tolist()
    if str(linha2[coluna_ano] or "").strip() != "Item Informação":
        raise ErroLayoutBase(
            f"Coluna {coluna_ano + 1} (linha 2): esperado 'Item Informação', "
            f"obtido {linha2[coluna_ano]!r}."
        )
    for deslocamento, esperado in enumerate(("DESPESAS EMPENHADAS", "DESPESAS LIQUIDADAS", "DESPESAS PAGAS")):
        obtido = str(linha2[PRIMEIRA_COLUNA_MESES + deslocamento] or "")
        if not obtido.strip().upper().startswith(esperado):
            raise ErroLayoutBase(
                f"Coluna {PRIMEIRA_COLUNA_MESES + 1 + deslocamento} (linha 2): esperado "
                f"iniciando por {esperado!r}, obtido {obtido!r}."
            )

    linha3 = cabecalho.iloc[2].tolist()
    if str(linha3[coluna_ano] or "").strip() != "Ano Lançamento":
        raise ErroLayoutBase(
            f"Coluna {coluna_ano + 1} (linha 3): esperado 'Ano Lançamento', "
            f"obtido {linha3[coluna_ano]!r}."
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


def ler_execucao_mensal(caminho: str | Path) -> pd.DataFrame:
    """Lê a base bruta e devolve o DataFrame normalizado em formato longo — uma linha por
    (linha original da planilha × mês do bloco correspondente), com `mes`/`ano_mes` derivados
    do rótulo do próprio bloco (nunca de `ano`/`Ano Lançamento`, que é uma dimensão à parte,
    ver docstring do módulo). Sem agregar nada — para a soma financeira correta, ver
    `valor_empenhado_por_bloco`."""

    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(caminho)

    blocos = _validar_assinatura(caminho)

    bruto = pd.read_excel(caminho, header=None, skiprows=LINHAS_CABECALHO, dtype=str)

    dimensoes = bruto.iloc[:, :PRIMEIRA_COLUNA_MESES].copy()
    dimensoes.columns = COLUNAS_DIMENSAO
    for col in COLUNAS_DIMENSAO:
        if col != "ano":
            dimensoes[col] = dimensoes[col].astype("string").str.strip()
    dimensoes["ano"] = pd.to_numeric(dimensoes["ano"], errors="raise").astype("int16")
    dimensoes["processo_ne"] = dimensoes["processo_ne"].mask(dimensoes["processo_ne"].isin(_SENTINELAS_PROCESSO))
    dimensoes.insert(0, "linha_origem", range(PRIMEIRA_LINHA_DADOS_PLANILHA, PRIMEIRA_LINHA_DADOS_PLANILHA + len(bruto)))
    dimensoes.insert(1, "arquivo_origem", caminho.name)

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

    resultado = pd.concat(partes, ignore_index=True)
    return resultado.sort_values(["linha_origem", "ano_mes"]).reset_index(drop=True)


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
    aparecem nas linhas de item de execução, uma por NE×mês)."""

    empenhado_dedup = valor_empenhado_por_bloco(df)
    liquidado_pago = df.loc[df["tipo_linha"] == "item_execucao"]

    return {
        "linhas": int(len(df)),
        "linhas_originais": int(df["linha_origem"].nunique()),
        "meses": sorted(df["ano_mes"].unique().tolist()),
        "notas_empenho_distintas": int(df["ne_ccor"].nunique()),
        "totais": {
            "empenhada": round(float(empenhado_dedup["empenhada"].sum()), 2),
            "liquidada": round(float(liquidado_pago["liquidada"].sum(min_count=1) or 0.0), 2),
            "paga": round(float(liquidado_pago["paga"].sum(min_count=1) or 0.0), 2),
        },
        "totais_por_ano": {
            int(ano): round(float(grupo["empenhada"].sum()), 2)
            for ano, grupo in empenhado_dedup.assign(ano=empenhado_dedup["ano_mes"] // 100).groupby("ano")
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
    # longo do exercício, mesmo espírito da checagem anual de `execucao_anual.validar`.
    liquidado_pago = df.loc[df["tipo_linha"] == "item_execucao"]
    por_mes = liquidado_pago.groupby("ano_mes")[["liquidada", "paga"]].sum(min_count=1).fillna(0.0)
    acumulado = por_mes.sort_index().cumsum()
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
