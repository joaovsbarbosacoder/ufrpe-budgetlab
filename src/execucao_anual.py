"""
Leitura e normalização da base ANUAL de Execução da Despesa (BI PROPLAD / Tesouro Gerencial).

Camada: regra específica de base (não é leitor genérico, não é analítica, não é interface).
Depende apenas de pandas/openpyxl. Não importa Streamlit.

Origem esperada: "BI CPOC - EXEC. DESPESAS - Por Ano.xlsx" (aba única, sucessora da extração
"BI PROPLAD" de mesmo layout, com a coluna "NE - Núm. Processo" adicionada na posição 33).
Layout: cabeçalho em 2 linhas + 40 colunas posicionais. Ver docs/base_execucao_anual.md.

Contrato público:
    ler_execucao_anual(caminho) -> pd.DataFrame  (normalizado, com rastreabilidade)
    reconciliar(df) -> dict                      (totais por ano e globais)
    validar(df, esperado=None) -> RelatorioValidacao
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pandas as pd

from src.cache_bases import em_cache
from src.leitura_excel import motor_excel

# --------------------------------------------------------------------------------------
# 1. Contrato do arquivo de origem
# --------------------------------------------------------------------------------------

#: Linha 1 = rótulos de grupo; linha 2 = subcabeçalho só das 4 últimas colunas.
#: Os dados começam na linha 3 da planilha (índice 0 do DataFrame após skiprows=2).
LINHAS_CABECALHO = 2
PRIMEIRA_LINHA_DADOS_PLANILHA = 3

#: Nomes internos, por POSIÇÃO. O arquivo não tem cabeçalho utilizável em uma única linha,
#: então a ordem das colunas é o contrato. Qualquer mudança de layout deve quebrar a leitura
#: em `_validar_assinatura`, nunca silenciosamente renomear dados.
COLUNAS = [
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
    "ano",
    "empenhada", "liquidada", "paga",
]

MEDIDAS = ["empenhada", "liquidada", "paga"]

#: Sentinelas do BI para "sem processo vinculado" na coluna "NE - Núm. Processo" — não um
#: número real, por isso viram nulo em vez de ficarem como texto na base normalizada.
_SENTINELAS_PROCESSO = {"'-9", "'-8"}

#: Assinatura mínima do cabeçalho (linha 1 da planilha) usada para detectar troca de layout.
ASSINATURA_CABECALHO = {
    0: "Iduso",
    12: "Grupo Despesa",
    25: "PTRES",
    32: "NE - N",
    37: "DESPESAS EMPENHADAS",
    38: "DESPESAS LIQUIDADAS",
    39: "DESPESAS PAGAS",
}

#: Marcador do Tesouro Gerencial para linhas que NÃO são a linha do empenho.
MARCADOR_ITEM_EXECUCAO = "NAO SE APLICA"


class ErroLayoutBase(ValueError):
    """Layout do arquivo diferente do contrato — falhar cedo, nunca adivinhar."""


# --------------------------------------------------------------------------------------
# 2. Leitura
# --------------------------------------------------------------------------------------

def _validar_assinatura(caminho: Path) -> None:
    cabecalho = pd.read_excel(caminho, header=None, nrows=1, dtype=str, engine=motor_excel()).iloc[0].tolist()
    if len(cabecalho) != len(COLUNAS):
        raise ErroLayoutBase(
            f"Esperadas {len(COLUNAS)} colunas, encontradas {len(cabecalho)}. "
            "A extração do Tesouro Gerencial mudou — revise docs/base_execucao_anual.md."
        )
    for pos, esperado in ASSINATURA_CABECALHO.items():
        obtido = str(cabecalho[pos] or "")
        if not obtido.strip().upper().startswith(esperado.upper()):
            raise ErroLayoutBase(
                f"Coluna {pos + 1}: esperado cabeçalho iniciando por {esperado!r}, obtido {obtido!r}."
            )


def _para_numero(serie: pd.Series) -> pd.Series:
    """Converte texto monetário em float preservando NaN (ausência ≠ zero)."""
    limpo = (
        serie.astype("string")
        .str.strip()
        .str.replace(r"^R\$\s*", "", regex=True)
        .str.replace(".", "", regex=False)   # separador de milhar, se houver
        .str.replace(",", ".", regex=False)  # decimal pt-BR, se houver
    )
    # Arquivos exportados com decimal em ponto já ficam corretos acima só se não houver
    # milhar; por isso reconverte quando a limpeza destruiu o decimal.
    original = pd.to_numeric(serie.astype("string").str.strip(), errors="coerce")
    convertido = pd.to_numeric(limpo, errors="coerce")
    return original.where(original.notna(), convertido)


@em_cache
def ler_execucao_anual(caminho: str | Path) -> pd.DataFrame:
    """Lê a base bruta e devolve o DataFrame normalizado, sem agregar nada."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(caminho)

    _validar_assinatura(caminho)

    df = pd.read_excel(caminho, header=None, skiprows=LINHAS_CABECALHO, dtype=str, engine=motor_excel())
    df.columns = COLUNAS

    # Rastreabilidade: linha exata na planilha de origem.
    df.insert(0, "linha_origem", range(PRIMEIRA_LINHA_DADOS_PLANILHA, PRIMEIRA_LINHA_DADOS_PLANILHA + len(df)))
    df.insert(1, "arquivo_origem", caminho.name)

    # Dimensões: texto limpo, códigos SEMPRE como string (zeros à esquerda são significativos).
    for col in COLUNAS:
        if col in MEDIDAS:
            continue
        df[col] = df[col].astype("string").str.strip()

    for col in MEDIDAS:
        df[col] = _para_numero(df[col])

    df["ano"] = pd.to_numeric(df["ano"], errors="raise").astype("int16")
    df["processo_ne"] = df["processo_ne"].mask(df["processo_ne"].isin(_SENTINELAS_PROCESSO))

    # Tipo de linha: a base mistura linha de EMPENHO com linha de ITEM DE EXECUÇÃO.
    eh_item = df["ne_descricao"].fillna("").str.upper().eq(MARCADOR_ITEM_EXECUCAO)
    df["tipo_linha"] = pd.Series("empenho", index=df.index, dtype="string").mask(eh_item, "item_execucao")

    # Chaves derivadas úteis e verificáveis contra a origem.
    df["ne_ano"] = df["ne_ccor"].str.slice(11, 15)
    df["ne_numero"] = df["ne_ccor"].str.slice(15)
    df["natureza_detalhada_label"] = df["natureza_detalhada_cod"] + " - " + df["natureza_detalhada_desc"]
    df["gnd_label"] = df["gnd_cod"] + " - " + df["gnd_desc"]
    df["fonte_label"] = df["fonte_cod"] + " - " + df["fonte_desc"]
    df["acao_label"] = df["acao_cod"] + " - " + df["acao_desc"]

    return df


# --------------------------------------------------------------------------------------
# 3. Reconciliação e validação
# --------------------------------------------------------------------------------------

def reconciliar(df: pd.DataFrame) -> dict:
    """Totais que devem bater com a origem (Tesouro Gerencial / planilha)."""
    por_ano = df.groupby("ano")[MEDIDAS].sum().round(2)
    return {
        "linhas": int(len(df)),
        "linhas_empenho": int((df["tipo_linha"] == "empenho").sum()),
        "linhas_item_execucao": int((df["tipo_linha"] == "item_execucao").sum()),
        "anos": sorted(df["ano"].unique().tolist()),
        "notas_empenho_distintas": int(df["ne_ccor"].nunique()),
        "totais": {m: round(float(df[m].sum()), 2) for m in MEDIDAS},
        "totais_por_ano": {int(a): {m: round(float(v[m]), 2) for m in MEDIDAS} for a, v in por_ano.iterrows()},
    }


@dataclass
class RelatorioValidacao:
    ok: bool
    erros: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)
    resumo: dict = field(default_factory=dict)


def validar(df: pd.DataFrame, esperado: dict | None = None) -> RelatorioValidacao:
    """Validações financeiras e estruturais. `esperado` = dict no formato de `reconciliar`."""
    erros: list[str] = []
    alertas: list[str] = []
    resumo = reconciliar(df)

    # Estrutura
    if df["ano"].isna().any():
        erros.append("Há linhas sem Ano Lançamento.")
    if df["ne_ccor"].isna().any() or df["ne_ccor"].eq("").any():
        erros.append("Há linhas sem NE CCor.")
    if not df["ne_ano"].eq(df["ano"].astype(str)).all():
        alertas.append(
            "Existem linhas cujo ano da NE difere do Ano Lançamento — possível resto a pagar; "
            "a análise intra-exercício precisa ser revista."
        )
    if df.duplicated(subset=[c for c in COLUNAS if c not in MEDIDAS]).any():
        alertas.append("Há linhas duplicadas na chave dimensional completa.")
    ne_com_empenho = set(df.loc[df["tipo_linha"] == "empenho", "ne_ccor"])
    ne_sem_linha_empenho = set(df["ne_ccor"]) - ne_com_empenho
    if ne_sem_linha_empenho:
        alertas.append(
            f"{len(ne_sem_linha_empenho)} NE sem nenhuma linha do tipo 'empenho' — "
            "agregar_por_ne() deixará ne_descricao/processo_ne nulos para essas NEs."
        )

    # Regra específica desta base
    soma_emp_itens = float(df.loc[df["tipo_linha"] == "item_execucao", "empenhada"].sum())
    if abs(soma_emp_itens) > 0.01:
        alertas.append(
            f"Linhas de item de execução somam {soma_emp_itens:.2f} em DESPESAS EMPENHADAS "
            "(esperado ~0,00 por serem anulações que se cancelam)."
        )
    liq_fora = df.loc[df["tipo_linha"] == "empenho", ["liquidada", "paga"]].notna().sum().sum()
    if liq_fora:
        alertas.append(f"{int(liq_fora)} valores de liquidado/pago em linhas de empenho (layout mudou?).")

    # Coerência financeira por ano
    por_ano = df.groupby("ano")[MEDIDAS].sum()
    for ano, linha in por_ano.iterrows():
        if linha["liquidada"] - linha["empenhada"] > 0.01:
            erros.append(f"{ano}: liquidado maior que empenhado.")
        if linha["paga"] - linha["liquidada"] > 0.01:
            erros.append(f"{ano}: pago maior que liquidado.")

    # Conferência contra totais informados pela origem
    if esperado:
        for medida, valor in esperado.get("totais", {}).items():
            obtido = resumo["totais"][medida]
            if abs(obtido - valor) > 0.01:
                erros.append(f"Total de {medida}: esperado {valor:.2f}, obtido {obtido:.2f}.")
        if esperado.get("linhas") not in (None, resumo["linhas"]):
            erros.append(f"Linhas: esperado {esperado['linhas']}, obtido {resumo['linhas']}.")

    return RelatorioValidacao(ok=not erros, erros=erros, alertas=alertas, resumo=resumo)


# --------------------------------------------------------------------------------------
# 4. Agregações de apoio (ainda camada de dados; gráficos/cards ficam na interface)
# --------------------------------------------------------------------------------------

DIMENSOES_ANALITICAS = {
    "GND": ["gnd_cod", "gnd_desc"],
    "Fonte de Recursos": ["fonte_cod", "fonte_desc"],
    "Ação de Governo": ["acao_cod", "acao_desc"],
    "Natureza de Despesa Detalhada": ["natureza_detalhada_cod", "natureza_detalhada_desc"],
    "Resultado Primário": ["resultado_primario_cod", "resultado_primario_desc"],
    "UG Responsável": ["ug_responsavel_cod", "ug_responsavel_desc"],
    "UGR": ["ugr_cod", "ugr_desc"],
    "PI": ["pi_cod", "pi_desc"],
    "PTRES": ["ptres"],
    "Plano Orçamentário": ["po_acao_cod", "po_cod", "po_desc"],
    "Favorecido": ["ne_favorecido"],
}


def agregar(df: pd.DataFrame, por: Iterable[str], incluir_ano: bool = True) -> pd.DataFrame:
    """Agrega as três medidas por dimensões arbitrárias, sem perder linhas por NaN."""
    chaves = list(por)
    if incluir_ano:
        chaves = ["ano", *chaves]
    fora = [c for c in chaves if c not in df.columns]
    if fora:
        raise KeyError(f"Colunas inexistentes: {fora}")
    out = df.groupby(chaves, dropna=False)[MEDIDAS].sum(min_count=1).fillna(0.0).reset_index()
    out["execucao_liquidada_pct"] = (out["liquidada"] / out["empenhada"]).where(out["empenhada"] != 0)
    out["pagamento_pct"] = (out["paga"] / out["liquidada"]).where(out["liquidada"] != 0)
    return out.sort_values([*chaves]).reset_index(drop=True)


def serie_anual(df: pd.DataFrame) -> pd.DataFrame:
    """Série Empenhado × Liquidado × Pago por exercício."""
    return agregar(df, por=[], incluir_ano=True)


#: `detalhar_nota_empenho` mudou para `src.execucao_ne_utils` em 22/09/2026 — mesmo motivo
#: das outras funções de ligação por NE (ver seção 5 abaixo): não depende de nada específico
#: desta base.


#: Dimensões confirmadas constantes dentro de uma mesma NE na base real (nenhuma delas varia
#: entre a linha de empenho e as linhas de item de execução, nem entre linhas de empenho quando
#: há mais de uma). `natureza_detalhada`/`subitem` ficam de fora de propósito — são as duas
#: exceções: uma NE pode ser lançada em mais de uma classificação orçamentária.
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
    "ug_executora_cod", "ug_executora_desc",
    "ug_responsavel_cod", "ug_responsavel_desc",
    "ugr_cod", "ugr_desc",
    "ne_favorecido",
]


def _resumo_classificacao(valores: pd.Series) -> str:
    """Valor único se a NE tem só uma classificação; contagem, caso contrário."""
    unicos = valores.dropna().unique()
    if len(unicos) == 0:
        return "—"
    if len(unicos) == 1:
        return str(unicos[0])
    return f"{len(unicos)} classificações"


def _soma_preservando_nulo(valores: pd.Series) -> float:
    return valores.sum(min_count=1)


def agregar_por_ne(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por NE (nota de empenho) — para consulta/navegação, não para reconciliação
    financeira (para isso, `agregar()`, que nunca perde a granularidade por linha).

    `ne_descricao` e `processo_ne` vêm só das linhas de tipo "empenho": linhas de item de
    execução sempre trazem o marcador "NAO SE APLICA"/uma sentinela de "sem processo" no
    lugar do valor real (ver `_SENTINELAS_PROCESSO`), não o dado verdadeiro da NE. As demais
    dimensões são constantes por NE, exceto Natureza Detalhada e Subitem (ver
    `_DIMENSOES_CONSTANTES_POR_NE`), resumidas como "N classificações" quando a NE tem mais
    de uma.
    """
    agregacoes: dict[str, object] = {coluna: "first" for coluna in _DIMENSOES_CONSTANTES_POR_NE}
    agregacoes["natureza_detalhada_label"] = _resumo_classificacao
    agregacoes["subitem_cod"] = _resumo_classificacao
    for medida in MEDIDAS:
        agregacoes[medida] = _soma_preservando_nulo

    resultado = df.groupby("ne_ccor", dropna=False).agg(agregacoes)
    so_empenho = df.loc[df["tipo_linha"] == "empenho"].groupby("ne_ccor")
    resultado["ne_descricao"] = so_empenho["ne_descricao"].first()
    resultado["processo_ne"] = so_empenho["processo_ne"].first()
    resultado = resultado.reset_index().rename(columns={"subitem_cod": "subitem_resumo"})
    return resultado.sort_values("ne_ccor").reset_index(drop=True)


# --------------------------------------------------------------------------------------
# 5. Ligação com outras bases que citam a NE sem o prefixo de órgão/UG
# --------------------------------------------------------------------------------------
#
# `ne_curta`/`saldo_por_ne`/`indice_*_por_ne_curta`/`detalhar_nota_empenho` moravam aqui —
# mudaram para `src/execucao_ne_utils.py` em 22/09/2026 (pré-requisito da migração de
# Bolsas/Contratos Contínuos/Contratos Pagamentos para a Execução Mensal, pedida pelo
# usuário): nunca dependeram de nada específico desta base, só de colunas presentes nas duas
# (`ne_ccor`/`empenhada`/`liquidada`/`paga`/`linha_origem`) — ver docstring de lá.


if __name__ == "__main__":  # inspeção rápida
    import sys

    dados = ler_execucao_anual(sys.argv[1])
    rel = validar(dados)
    print(rel.resumo)
    print("ERROS:", rel.erros or "nenhum")
    print("ALERTAS:", rel.alertas or "nenhum")
