"""Regra do Resultado Orçamentário: dotação das células marcadas menos o empenhado e a necessidade.

Decisão (08/10/2026): o usuário marca um "bolsão" de células orçamentárias (IDUSO, resultado
primário, ação, PTRES, plano orçamentário, grupo de despesa e fonte detalhada) e a página mostra
`Resultado = Dotação das células − Empenhado das células − Necessidade de empenho`.
Motivo: no bolsão, a necessidade de Contratos e Bolsas precisa ser coberta pelos recursos
escolhidos, mesmo quando a NE está em célula não marcada; já o empenhado só conta o que foi de
fato empenhado nas células marcadas. Este módulo é regra pura: não importa Streamlit e não lê
arquivo. Especificação: docs/superpowers/specs/2026-10-08-resultado-orcamentario-design.md.

Códigos são sempre texto (zeros à esquerda preservados). Nulo, zero e negativo são estados
distintos: dotação nula não vira zero (o resultado fica incompleto); estorno líquido (empenhado
negativo) entra como está.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.dotacao_anual_analysis import (
    KNOWN_ITEM_INDICATORS,
    SUBDIVISION_DIMENSION_COLUMNS,
    build_dotacao_anual_subdivision_analysis,
)
from src.execucao_ne_utils import ne_curta
from src.resultado_orcamentario_cadastro import CHAVE_CELULA, CelulaChave, DespesaManual
from src.tesouro_execucao_mensal import valor_empenhado_por_bloco

ORIGEM_CONTRATOS = "Contratos Contínuos"
ORIGEM_BOLSAS = "Bolsas e Auxílios"
ORIGEM_OUTROS = "Outros empenhos"
OUTRAS_DESPESAS = "Outras despesas previstas"

TOLERANCIA_CONFERENCIA = 0.01

#: colunas da Execução Mensal (`valor_empenhado_por_bloco`) que formam a chave da célula, na
#: mesma ordem de `CHAVE_CELULA`.
_COLUNAS_CHAVE_EXECUCAO: tuple[str, ...] = (
    "iduso_cod",
    "resultado_primario_cod",
    "acao_cod",
    "ptres",
    "po_cod",
    "gnd_cod",
    "fonte_recursos_detalhada_cod",
)

_COLUNAS_EMPENHADO_POR_NE = [
    "ne_curta", "origem", "empenhada", "contrato_numero", "fornecedor", "programa_bolsa",
    "natureza_detalhada_desc", "ne_favorecido", "celula_selecionada",
]


@dataclass
class ResultadoOrcamentario:
    dotacao: float | None
    empenhado: dict[str, float]
    empenhado_total: float
    diferenca_conferencia: float
    necessidade: dict[str, float | None]
    resultado: float | None
    incompleto: bool
    empenhado_por_ne: pd.DataFrame
    avisos: list[str] = field(default_factory=list)


def _texto_ou_none(valor) -> str | None:
    return None if pd.isna(valor) else str(valor)


def _brl(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def soma_ou_nulo(valores: pd.Series) -> float | None:
    """Soma para exibição: `None` se QUALQUER valor for nulo (nulo não vira zero na soma, spec §5);
    série vazia (nada selecionado) = 0,0.

    Correção (08/10/2026, revisão da Task 5): o "Total selecionado" da tabela de células somava com
    `min_count=1` e tratava a dotação nula de uma célula como zero, mostrando um total definido enquanto
    o cartão mostrava "—"."""

    if valores.isna().any():
        return None
    return float(valores.sum()) if len(valores) else 0.0


def celulas_da_dotacao(dotacao: pd.DataFrame, exercicio: int) -> pd.DataFrame:
    """Uma linha por célula do exercício, a partir da Dotação Anual normalizada.

    Decisão (08/10/2026): mesmo filtro de `limite_empenho._dotacao_atualizada_no_escopo`
    (subdivisão com ao menos um dos indicadores conhecidos no exercício, para não listar
    combinações que só existem "de passagem" por dado de outro ano), mas SEM o filtro
    discricionário: o bolsão pode incluir qualquer fonte, resultado primário ou GND. Motivo:
    o usuário escolhe livremente as células que compõem o bolsão.
    """

    do_ano = dotacao.loc[dotacao["ano_lancamento"] == exercicio]
    subdivisoes = build_dotacao_anual_subdivision_analysis(do_ano)
    tem_algum_indicador = subdivisoes[list(KNOWN_ITEM_INDICATORS)].notna().any(axis=1)
    celulas = subdivisoes.loc[tem_algum_indicador, [*SUBDIVISION_DIMENSION_COLUMNS, "dotacao_atualizada"]].copy()

    for coluna in SUBDIVISION_DIMENSION_COLUMNS:
        celulas[coluna] = celulas[coluna].astype("string")
    celulas["dotacao_atualizada"] = celulas["dotacao_atualizada"].astype("Float64")
    celulas = celulas.reset_index(drop=True)
    celulas["chave"] = [
        tuple(_texto_ou_none(valor) for valor in linha)
        for linha in celulas[list(CHAVE_CELULA)].itertuples(index=False, name=None)
    ]
    return celulas


def empenhado_por_ne_e_celula(execucao_mensal: pd.DataFrame, exercicio: int) -> pd.DataFrame:
    """Empenhado (deduplicado por bloco) por NE curta e célula, no exercício.

    Decisão (08/10/2026): `ne_favorecido` vem da Execução Mensal bruta (primeiro valor não nulo
    por `ne_ccor`), porque `valor_empenhado_por_bloco` não o carrega. A soma usa `min_count=1`:
    NE sem nenhum valor informado fica nula, não zero.
    """

    bruto = execucao_mensal.loc[execucao_mensal["ano"] == exercicio]
    blocos = valor_empenhado_por_bloco(bruto)
    colunas = ["ne_curta", "chave", "empenhada", "natureza_detalhada_desc", "ne_favorecido"]
    if blocos.empty:
        return pd.DataFrame(columns=colunas)

    if "ne_favorecido" in bruto.columns:
        favorecidos = bruto.dropna(subset=["ne_favorecido"]).groupby("ne_ccor")["ne_favorecido"].first()
    else:
        favorecidos = pd.Series(dtype="object")

    blocos = blocos.copy()
    blocos["ne_curta"] = blocos["ne_ccor"].astype(str).map(ne_curta)
    for coluna in _COLUNAS_CHAVE_EXECUCAO:
        blocos[coluna] = blocos[coluna].astype("string")
    blocos["ne_favorecido"] = blocos["ne_ccor"].map(favorecidos)

    agrupado = (
        blocos.groupby(["ne_curta", *_COLUNAS_CHAVE_EXECUCAO], dropna=False)
        .agg(
            empenhada=("empenhada", lambda s: s.sum(min_count=1)),
            natureza_detalhada_desc=(
                "natureza_detalhada_desc",
                lambda s: "; ".join(dict.fromkeys(s.dropna().astype(str))) or None,
            ),
            ne_favorecido=("ne_favorecido", lambda s: next((v for v in s if pd.notna(v)), None)),
        )
        .reset_index()
    )
    agrupado["chave"] = [
        tuple(_texto_ou_none(valor) for valor in linha)
        for linha in agrupado[list(_COLUNAS_CHAVE_EXECUCAO)].itertuples(index=False, name=None)
    ]
    return agrupado[colunas].reset_index(drop=True)


def _soma_necessidade(relatorio: pd.DataFrame | None) -> float | None:
    """`None` = relatório indisponível (não é zero). DataFrame vazio = zero."""

    if relatorio is None:
        return None
    if relatorio.empty:
        return 0.0
    return float(pd.to_numeric(relatorio["necessidade_execucao"], errors="coerce").sum())


def _por_ne(cadastro: pd.DataFrame, colunas: list[str]) -> dict[str, dict]:
    """Para cada `ne_curta` do cadastro, os valores distintos (em ordem) de cada coluna."""

    resultado: dict[str, dict] = {}
    if cadastro is None or cadastro.empty or "ne_curta" not in cadastro.columns:
        return resultado
    for ne, grupo in cadastro.groupby("ne_curta", dropna=True):
        info = {}
        for coluna in colunas:
            if coluna in grupo.columns:
                info[coluna] = list(dict.fromkeys(grupo[coluna].dropna().astype(str)))
            else:
                info[coluna] = []
        resultado[str(ne)] = info
    return resultado


def _aviso_sem_ne(sem_ne: pd.DataFrame, singular: str, plural: str) -> str | None:
    if sem_ne is None or sem_ne.empty:
        return None
    quantidade = len(sem_ne)
    soma = float(pd.to_numeric(sem_ne["necessidade"], errors="coerce").sum()) if "necessidade" in sem_ne else 0.0
    nome = singular if quantidade == 1 else plural
    return (
        f"{quantidade} {nome} sem NE vinculada: necessidade de {_brl(soma)} informativa, "
        "fora da conta do resultado."
    )


def calcular_resultado(
    celulas: pd.DataFrame,
    empenhado: pd.DataFrame,
    selecao: list[CelulaChave],
    cadastro_contratos: pd.DataFrame,
    cadastro_bolsas: pd.DataFrame,
    necessidade_contratos: pd.DataFrame | None,
    necessidade_bolsas: pd.DataFrame | None,
    sem_ne_contratos: pd.DataFrame,
    sem_ne_bolsas: pd.DataFrame,
    despesas_manuais: list[DespesaManual],
) -> ResultadoOrcamentario:
    """Resultado = Dotação − Empenhado total − Σ necessidade (ver §3 a §5 da especificação).

    Decisões (08/10/2026):
    - `resultado` é `None` com seleção vazia, dotação indeterminada ou alguma necessidade
      indisponível. Com seleção vazia há aviso próprio e `incompleto=False`; nos demais casos
      `incompleto=True`. Motivo: nulo não pode virar zero na soma.
    - Dotação é `None` se alguma célula marcada presente na base não tem Dotação Atualizada.
    - A necessidade de Contratos e Bolsas soma TODAS as NEs do relatório, inclusive as de células
      não marcadas; o empenhado só conta as células marcadas.
    - NE nos dois cadastros vai para Contratos (com aviso); NE ligada a mais de um contrato é
      contada uma vez (com aviso de NE compartilhada).
    """

    avisos: list[str] = []
    selecionadas = list(dict.fromkeys(tuple(c) for c in selecao))
    conjunto_selecao = set(selecionadas)

    # --- Dotação das células marcadas -------------------------------------------------------
    chaves_na_base = set(celulas["chave"]) if len(celulas) else set()
    ausentes = [c for c in selecionadas if c not in chaves_na_base]
    for chave in ausentes:
        avisos.append(f"Célula selecionada ausente da base de Dotação: {' / '.join(str(p) for p in chave)}.")

    presentes = celulas.loc[celulas["chave"].isin(conjunto_selecao)] if len(celulas) else celulas
    dotacao: float | None
    if not selecionadas:
        avisos.append("Nenhuma célula selecionada: marque ao menos uma célula para calcular o resultado.")
        dotacao = None
    elif presentes.empty:
        dotacao = None
    else:
        nulas = presentes.loc[presentes["dotacao_atualizada"].isna()]
        for chave in nulas["chave"]:
            avisos.append(f"Célula sem Dotação Atualizada: {' / '.join(str(p) for p in chave)}.")
        if len(nulas):
            dotacao = None
        else:
            dotacao = float(presentes["dotacao_atualizada"].astype("Float64").sum())

    # --- Empenhado e origem -----------------------------------------------------------------
    emp = empenhado.copy() if empenhado is not None else pd.DataFrame()
    for coluna in ("ne_curta", "chave", "empenhada", "natureza_detalhada_desc", "ne_favorecido"):
        if coluna not in emp.columns:
            emp[coluna] = pd.Series(dtype="object")
    emp["empenhada"] = pd.to_numeric(emp["empenhada"], errors="coerce")

    sem_fonte = emp["chave"].map(lambda c: c[-1] is None)
    if sem_fonte.any():
        total_sem_fonte = float(emp.loc[sem_fonte, "empenhada"].sum())
        avisos.append(
            f"{int(sem_fonte.sum())} empenho(s) sem Fonte de Recursos Detalhada ({_brl(total_sem_fonte)}) "
            "não entram em nenhuma célula."
        )
    emp["celula_selecionada"] = emp["chave"].map(lambda c: c in conjunto_selecao) & ~sem_fonte

    info_contratos = _por_ne(cadastro_contratos, ["contrato_numero", "fornecedor"])
    info_bolsas = _por_ne(cadastro_bolsas, ["programa_bolsa"])

    def _origem(ne: str) -> str:
        if ne in info_contratos:
            return ORIGEM_CONTRATOS
        if ne in info_bolsas:
            return ORIGEM_BOLSAS
        return ORIGEM_OUTROS

    por_ne = (
        emp.groupby(["ne_curta", "celula_selecionada"], dropna=False)
        .agg(
            empenhada=("empenhada", lambda s: s.sum(min_count=1)),
            natureza_detalhada_desc=("natureza_detalhada_desc", "first"),
            ne_favorecido=("ne_favorecido", lambda s: next((v for v in s if pd.notna(v)), None)),
        )
        .reset_index()
        if len(emp)
        else pd.DataFrame(columns=["ne_curta", "celula_selecionada", "empenhada", "natureza_detalhada_desc", "ne_favorecido"])
    )
    por_ne["ne_curta"] = por_ne["ne_curta"].astype(str)
    por_ne["origem"] = por_ne["ne_curta"].map(_origem)
    por_ne["contrato_numero"] = por_ne["ne_curta"].map(lambda n: "; ".join(info_contratos.get(n, {}).get("contrato_numero", [])) or None)
    por_ne["fornecedor"] = por_ne["ne_curta"].map(lambda n: "; ".join(info_contratos.get(n, {}).get("fornecedor", [])) or None)
    por_ne["programa_bolsa"] = por_ne["ne_curta"].map(lambda n: "; ".join(info_bolsas.get(n, {}).get("programa_bolsa", [])) or None)
    por_ne = por_ne[_COLUNAS_EMPENHADO_POR_NE].reset_index(drop=True)

    nes_selecionadas = por_ne.loc[por_ne["celula_selecionada"], "ne_curta"].tolist()
    for ne in nes_selecionadas:
        if ne in info_contratos and ne in info_bolsas:
            avisos.append(f"NE {ne} em Contratos e em Bolsas — conferir.")
        if len(info_contratos.get(ne, {}).get("contrato_numero", [])) > 1:
            avisos.append(f"NE {ne} compartilhada por mais de um contrato; empenho contado uma única vez.")

    selecionados = por_ne.loc[por_ne["celula_selecionada"]]
    # Correção (08/10/2026, revisão da Task 4): empenhado nulo em célula marcada não pode virar
    # zero na soma. Avisa, nomeando as NEs, e deixa o resultado incompleto.
    nes_empenho_nulo = selecionados.loc[selecionados["empenhada"].isna(), "ne_curta"].tolist()
    if nes_empenho_nulo:
        avisos.append(
            "Empenhado nulo (não informado) em célula marcada para a(s) NE: "
            + ", ".join(nes_empenho_nulo)
            + ". Resultado incompleto."
        )
    empenhado_por_origem = {
        origem: float(selecionados.loc[selecionados["origem"] == origem, "empenhada"].sum())
        for origem in (ORIGEM_CONTRATOS, ORIGEM_BOLSAS, ORIGEM_OUTROS)
    }
    # Conferência independente da classificação: soma direta das linhas das células marcadas.
    empenhado_total = float(emp.loc[emp["celula_selecionada"], "empenhada"].sum())
    diferenca = empenhado_total - sum(empenhado_por_origem.values())
    if abs(diferenca) >= TOLERANCIA_CONFERENCIA:
        avisos.append(f"Conferência do empenhado não fecha: diferença de {_brl(diferenca)}.")

    # --- Necessidade ------------------------------------------------------------------------
    necessidade: dict[str, float | None] = {
        ORIGEM_CONTRATOS: _soma_necessidade(necessidade_contratos),
        ORIGEM_BOLSAS: _soma_necessidade(necessidade_bolsas),
        OUTRAS_DESPESAS: float(sum(d.valor for d in despesas_manuais)),
    }
    for origem in (ORIGEM_CONTRATOS, ORIGEM_BOLSAS):
        if necessidade[origem] is None:
            avisos.append(f"Necessidade de {origem} indisponível: resultado incompleto.")

    for aviso in (
        _aviso_sem_ne(sem_ne_contratos, "contrato", "contratos"),
        _aviso_sem_ne(sem_ne_bolsas, "bolsa", "bolsas"),
    ):
        if aviso:
            avisos.append(aviso)

    # --- Resultado --------------------------------------------------------------------------
    resultado: float | None = None
    if dotacao is not None and not nes_empenho_nulo and all(v is not None for v in necessidade.values()):
        resultado = dotacao - empenhado_total - float(sum(necessidade.values()))
    incompleto = bool(selecionadas) and resultado is None

    return ResultadoOrcamentario(
        dotacao=dotacao,
        empenhado=empenhado_por_origem,
        empenhado_total=empenhado_total,
        diferenca_conferencia=diferenca,
        necessidade=necessidade,
        resultado=resultado,
        incompleto=incompleto,
        empenhado_por_ne=por_ne,
        avisos=avisos,
    )
