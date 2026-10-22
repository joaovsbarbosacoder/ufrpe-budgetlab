"""Regra do Resultado Orçamentário: dotação das células marcadas menos o executado, o empenhado e o projetado.

Decisão (08/10/2026): o usuário marca um "bolsão" de células orçamentárias (IDUSO, resultado
primário, ação, PTRES, plano orçamentário, grupo de despesa e fonte detalhada) e a página mostra
`Resultado = Dotação das células − Empenhado das células − Necessidade de empenho` (fórmula original; a de
Contratos e Bolsas mudou em 15/10/2026, ver abaixo). Este módulo é regra pura: não importa Streamlit e não lê
arquivo. Especificação: docs/superpowers/specs/2026-10-08-resultado-orcamentario-design.md.

EXECUTADO + PROJETADO (15/10/2026, pedido do usuário): para Contratos e Bolsas o resultado deixa de usar o empenhado e a
necessidade de empenho e passa a medir o CONSUMO do orçamento: `Resultado = Dotação (limitada pela arrecadação própria) − Executado − Projetado a realizar`,
onde executado = o que a NE já liquidou (valor empenhado − saldo) e projetado = o que falta da projeção pela execução até
dezembro (`projetado_execucao`). Como só se soma o que de fato será consumido, a sobra de empenho (saldo que a projeção não
vai liquidar) não pesa na conta e a antiga "anulação sugerida" como receita deixou de existir aqui (o relatório de Anulação
de Saldo de Empenho segue à parte). As demais origens (DEA, material de consumo, outros) continuam pelo empenhado.
Só entram as NEs com empenho nas células MARCADAS (decisão do usuário, 15/10/2026): o consumo de NE em célula não marcada
fica fora da conta e é listado em aviso, com o valor — nada some em silêncio. NE com empenho dentro e fora da seleção entra
inteira (a projeção é por NE, não por célula) e é sinalizada. A necessidade de empenho segue nas páginas de Contratos e Bolsas.

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
from src.resultado_orcamentario_cadastro import CHAVE_CELULA, CelulaChave, DespesaManual, ReceitaPropria
from src.tesouro_execucao_mensal import valor_empenhado_por_bloco

ORIGEM_CONTRATOS = "Contratos Contínuos"
ORIGEM_BOLSAS = "Bolsas e Auxílios"
ORIGEM_DEA = "Despesas de Exercícios Anteriores (elemento 92)"
ORIGEM_MATERIAL_CONSUMO = "Material de Consumo (elemento 30)"
ORIGEM_OUTROS = "Outros empenhos"
#: Ordem de exibição do empenhado. Pedido do usuário (08/10/2026): o que não é Contrato nem Bolsa
#: é segmentado pelo elemento de despesa — 92 e 30 em linhas próprias, o restante em "Outros".
#: Contrato e Bolsa têm prioridade: NE cadastrada fica na sua origem qualquer que seja o elemento.
ORIGENS_EMPENHADO = (ORIGEM_CONTRATOS, ORIGEM_BOLSAS, ORIGEM_DEA, ORIGEM_MATERIAL_CONSUMO, ORIGEM_OUTROS)
_ORIGEM_POR_ELEMENTO = {"92": ORIGEM_DEA, "30": ORIGEM_MATERIAL_CONSUMO}
OUTRAS_DESPESAS = "Outras despesas previstas"

TOLERANCIA_CONFERENCIA = 0.01

#: Receita própria (22/10/2026, regra do usuário): a dotação da fonte 1050 é estimativa da arrecadação do exercício e só
#: pode ser usada até o que foi arrecadado. O valor informado à mão é o LIMITE de uso da célula da ação 20RK, GND 3, fonte
#: detalhada 1050000000: ela conta `menor entre a dotação atualizada e a arrecadação informada`. A arrecadação não soma
#: dotação por fora. A fonte 1050000390 (parte já em execução) não entra no limite.
RECEITA_ACAO = "20RK"
RECEITA_GND = "3"
RECEITA_FONTE = "1050000000"
_IDX_CHAVE_ACAO = CHAVE_CELULA.index("acao_codigo")
_IDX_CHAVE_GND = CHAVE_CELULA.index("grupo_despesa_codigo")
_IDX_CHAVE_FONTE = CHAVE_CELULA.index("fonte_recursos_detalhada_codigo")
ROTULO_CELULA_RECEITA = f"ação {RECEITA_ACAO}, GND {RECEITA_GND}, fonte {RECEITA_FONTE}"


def e_celula_da_receita(chave: CelulaChave) -> bool:
    """A célula é aquela cuja dotação a arrecadação própria limita (ação 20RK, GND 3, fonte 1050000000)."""

    return (
        chave[_IDX_CHAVE_ACAO] == RECEITA_ACAO and chave[_IDX_CHAVE_GND] == RECEITA_GND
        and chave[_IDX_CHAVE_FONTE] == RECEITA_FONTE
    )


def dotacao_pela_receita(chave: CelulaChave, dotacao: float | None, limite: float | None) -> float | None:
    """Dotação com que a célula conta: o menor entre ela e a arrecadação informada, se for a célula da receita e houver limite.
    Dotação nula continua nula (nulo não vira zero)."""

    if limite is None or dotacao is None or not e_celula_da_receita(chave):
        return dotacao
    return min(float(dotacao), float(limite))

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
    "ne_curta", "origem", "elemento_cod", "empenhada", "contrato_numero", "fornecedor", "programa_bolsa",
    "natureza_detalhada_desc", "ne_favorecido", "celula_selecionada",
]


#: Contratos e Bolsas: uma linha por NE da projeção que está nas células marcadas
COLUNAS_CONSUMO_POR_NE = ["ne_curta", "origem", "executado", "projetado"]
ORIGENS_CONSUMO = (ORIGEM_CONTRATOS, ORIGEM_BOLSAS)


@dataclass
class ResultadoOrcamentario:
    dotacao: float | None
    #: empenhado nas células marcadas por origem (todas as 5) — base da conferência com a Execução Mensal
    empenhado: dict[str, float | None]
    empenhado_total: float | None
    diferenca_conferencia: float
    #: executado (liquidado) das NEs de Contratos e Bolsas nas células marcadas; `None` = projeção indisponível
    executado: dict[str, float | None]
    #: projetado a realizar até dezembro: Contratos, Bolsas e "Outras despesas previstas"
    projetado: dict[str, float | None]
    #: o que abate a dotação já consumido: executado de Contratos e Bolsas + empenhado das demais origens
    executado_total: float | None
    resultado: float | None
    incompleto: bool
    empenhado_por_ne: pd.DataFrame
    avisos: list[str] = field(default_factory=list)
    #: uma linha por NE de Contratos/Bolsas contada na conta: `ne_curta`, `origem`, `executado`, `projetado`
    consumo_por_ne: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=COLUNAS_CONSUMO_POR_NE))
    #: outras despesas previstas desmarcadas (fora da conta): quantidade e valor somado (15/10/2026)
    outras_desconsideradas_qtd: int = 0
    outras_desconsideradas_valor: float = 0.0
    #: arrecadação própria informada e considerada (soma dos lançamentos); `None` = nenhuma considerada, sem limite
    receita_limite: float | None = None
    #: dotação com que a célula da receita contou (menor entre a dotação e o limite); 0,0 se desmarcada ou sem limite
    receita_aplicada: float = 0.0
    #: parte da arrecadação informada que passa da dotação da célula (fica fora, em aviso); 0,0 se não passa
    receita_excedente: float = 0.0
    #: dotação das células marcadas SEM o limite (a do cartão é a limitada); igual a `dotacao` quando não há limite
    dotacao_integral: float | None = None
    receitas_desconsideradas_qtd: int = 0
    receitas_desconsideradas_valor: float = 0.0

    @property
    def projetado_total(self) -> float | None:
        return None if any(v is None for v in self.projetado.values()) else float(sum(self.projetado.values()))


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
    colunas = ["ne_curta", "chave", "elemento_cod", "empenhada", "natureza_detalhada_desc", "ne_favorecido"]
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
    # elemento por linha (08/10/2026): uma NE com mais de um elemento se divide entre as linhas do empenhado
    blocos["elemento_cod"] = blocos["elemento_cod"].astype("string") if "elemento_cod" in blocos else pd.NA

    agrupado = (
        blocos.groupby(["ne_curta", *_COLUNAS_CHAVE_EXECUCAO, "elemento_cod"], dropna=False)
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


def _consumo_da_origem(
    linhas: pd.DataFrame | None, origem: str, nes_marcadas: set[str], excluir: set[str],
    avisos: list[str],
) -> tuple[float | None, float | None, pd.DataFrame]:
    """`(executado, projetado, detalhe por NE)` das NEs de `origem` com empenho nas células marcadas, a partir do relatório de
    projeção (`valor_empenhado`, `saldo`, `projetado_execucao`). `linhas=None` = relatório indisponível: tudo `None` (nunca
    zero). Valor nulo em NE contada deixa o total da origem `None`, com aviso. NEs de células não marcadas ficam fora e são
    listadas em aviso com o valor. `excluir`: NEs que pertencem a outra origem (NE nos dois cadastros vai para Contratos)."""

    vazio = pd.DataFrame(columns=COLUNAS_CONSUMO_POR_NE)
    if linhas is None:
        return None, None, vazio
    if linhas.empty:
        return 0.0, 0.0, vazio
    base = linhas.copy()
    base = base.loc[base["ne_curta"].notna()]
    base["ne_curta"] = base["ne_curta"].astype(str)
    base = base.loc[~base["ne_curta"].isin(excluir)].drop_duplicates("ne_curta")
    for coluna in ("valor_empenhado", "saldo", "projetado_execucao"):
        base[coluna] = pd.to_numeric(base[coluna], errors="coerce") if coluna in base else float("nan")
    base["executado"] = base["valor_empenhado"] - base["saldo"]
    base["projetado"] = base["projetado_execucao"]
    dentro = base["ne_curta"].isin(nes_marcadas)
    contadas, fora = base.loc[dentro], base.loc[~dentro]
    detalhe = contadas.assign(origem=origem)[COLUNAS_CONSUMO_POR_NE].reset_index(drop=True)

    sem_executado = list(contadas.loc[contadas["executado"].isna(), "ne_curta"])
    if sem_executado:
        avisos.append(
            f"Executado de {origem} não calculado (empenho ou saldo ausente) para a(s) NE: " + ", ".join(sem_executado) + "."
        )
    sem_projecao = list(contadas.loc[contadas["projetado"].isna(), "ne_curta"])
    if sem_projecao:
        avisos.append(
            f"Projetado de {origem} não calculado para NE sem valor mensal cadastrado: " + ", ".join(sem_projecao) + "."
        )
    if len(fora):
        executado_fora, projetado_fora = fora["executado"].sum(), fora["projetado"].sum()
        avisos.append(
            f"{len(fora)} NE(s) de {origem} sem empenho nas células marcadas ficam fora da conta (executado "
            f"{_brl(float(executado_fora))} + projetado {_brl(float(projetado_fora))} = {_brl(float(executado_fora + projetado_fora))}): "
            + ", ".join(fora["ne_curta"]) + "."
        )
    return soma_ou_nulo(contadas["executado"]), soma_ou_nulo(contadas["projetado"]), detalhe


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
    # Correção (08/10/2026, revisão final): coluna ausente ou qualquer valor nulo = "valor não calculado";
    # antes a coluna ausente virava R$ 0,00 e o nulo era somado como zero (null != zero).
    soma = soma_ou_nulo(pd.to_numeric(sem_ne["necessidade"], errors="coerce")) if "necessidade" in sem_ne else None
    valor = "valor não calculado" if soma is None else _brl(soma)
    nome = singular if quantidade == 1 else plural
    return (
        f"{quantidade} {nome} sem NE vinculada: necessidade de {valor} informativa, "
        "fora da conta do resultado."
    )


STATUS_ATIVO = "ATIVO"


def separar_ativos_sem_ne(sem_ne: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`(ativos, demais)` entre os contratos sem NE, pelo `status_contrato` (sem diferenciar maiúsculas
    nem espaços). Sem a coluna de status, nenhum é ativo."""

    if sem_ne is None or sem_ne.empty or "status_contrato" not in sem_ne:
        vazio = sem_ne.iloc[0:0] if sem_ne is not None else pd.DataFrame()
        return vazio, sem_ne if sem_ne is not None else pd.DataFrame()
    ativo = sem_ne["status_contrato"].astype("string").str.strip().str.upper().eq(STATUS_ATIVO).fillna(False)
    return sem_ne.loc[ativo], sem_ne.loc[~ativo]


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
    receitas_proprias: list[ReceitaPropria] | None = None,
) -> ResultadoOrcamentario:
    """Resultado = Dotação (a da fonte 1050/20RK limitada pela arrecadação própria informada à mão) − Executado (Contratos e Bolsas) − Empenhado (demais origens) − Projetado a realizar (Contratos,
    Bolsas e outras despesas previstas); ver a docstring do módulo. `necessidade_contratos`/`necessidade_bolsas` são os
    `linhas` do relatório de Projeção pela Execução (nome mantido; trazem `valor_empenhado`, `saldo` e `projetado_execucao`).

    Decisões (08/10/2026):
    - `resultado` é `None` com seleção vazia, dotação indeterminada ou alguma necessidade
      indisponível. Com seleção vazia há aviso próprio e `incompleto=False`; nos demais casos
      `incompleto=True`. Motivo: nulo não pode virar zero na soma.
    - Dotação é `None` se alguma célula marcada presente na base não tem Dotação Atualizada.
    - (15/10/2026) Contratos e Bolsas só contam as NEs com empenho nas células marcadas; as demais ficam fora, em aviso.
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

    # Receitas próprias (22/10/2026): o total considerado é o LIMITE da dotação da célula da receita (ver o topo do módulo).
    # Lançamento desmarcado ("Considerar") fica fora, em aviso; sem nenhum considerado, não há limite e a dotação conta inteira.
    receitas = receitas_proprias or []
    receitas_fora = [r for r in receitas if not r.considerada]
    if receitas_fora:
        avisos.append(
            f"{len(receitas_fora)} de {len(receitas)} receitas próprias desconsideradas "
            f"({_brl(float(sum(r.valor for r in receitas_fora)))}): fora da conta do resultado."
        )
    receita_limite = float(sum(r.valor for r in receitas if r.considerada)) if len(receitas) > len(receitas_fora) else None

    presentes = celulas.loc[celulas["chave"].isin(conjunto_selecao)] if len(celulas) else celulas
    dotacao: float | None
    dotacao_integral: float | None = None
    receita_aplicada = receita_excedente = 0.0
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
            dotacao_integral = float(presentes["dotacao_atualizada"].astype("Float64").sum())
            dotacao = dotacao_integral
            alvo = presentes.loc[presentes["chave"].map(e_celula_da_receita)]
            if len(alvo) and receita_limite is None:
                avisos.append(
                    f"A célula da {ROTULO_CELULA_RECEITA} conta pela dotação estimada integral "
                    f"({_brl(float(alvo['dotacao_atualizada'].astype('Float64').sum()))}): informe a arrecadação própria para limitá-la."
                )
            elif len(alvo):
                dotacao_alvo = float(alvo["dotacao_atualizada"].astype("Float64").sum())
                receita_aplicada = min(dotacao_alvo, receita_limite)
                receita_excedente = max(receita_limite - dotacao_alvo, 0.0)
                dotacao = dotacao_integral - dotacao_alvo + receita_aplicada
                if receita_excedente:
                    avisos.append(
                        f"Arrecadação própria informada ({_brl(receita_limite)}) passa da dotação da célula da "
                        f"{ROTULO_CELULA_RECEITA} ({_brl(dotacao_alvo)}): {_brl(receita_excedente)} ficam fora."
                    )
                elif receita_aplicada < dotacao_alvo:
                    avisos.append(
                        f"Dotação da célula da {ROTULO_CELULA_RECEITA} limitada pela arrecadação própria: "
                        f"{_brl(dotacao_alvo)} → {_brl(receita_aplicada)}."
                    )
            elif receita_limite is not None:
                avisos.append(
                    f"Arrecadação própria informada ({_brl(receita_limite)}) sem efeito: a célula da "
                    f"{ROTULO_CELULA_RECEITA} não está marcada."
                )

    # --- Empenhado e origem -----------------------------------------------------------------
    emp = empenhado.copy() if empenhado is not None else pd.DataFrame()
    for coluna in ("ne_curta", "chave", "elemento_cod", "empenhada", "natureza_detalhada_desc", "ne_favorecido"):
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

    def _origem(ne: str, elemento: object) -> str:
        if ne in info_contratos:
            return ORIGEM_CONTRATOS
        if ne in info_bolsas:
            return ORIGEM_BOLSAS
        return _ORIGEM_POR_ELEMENTO.get(None if pd.isna(elemento) else str(elemento), ORIGEM_OUTROS)

    por_ne = (
        emp.groupby(["ne_curta", "celula_selecionada", "elemento_cod"], dropna=False)
        .agg(
            empenhada=("empenhada", lambda s: s.sum(min_count=1)),
            natureza_detalhada_desc=("natureza_detalhada_desc", "first"),
            ne_favorecido=("ne_favorecido", lambda s: next((v for v in s if pd.notna(v)), None)),
        )
        .reset_index()
        if len(emp)
        else pd.DataFrame(
            columns=["ne_curta", "celula_selecionada", "elemento_cod", "empenhada", "natureza_detalhada_desc", "ne_favorecido"]
        )
    )
    por_ne["ne_curta"] = por_ne["ne_curta"].astype(str)
    por_ne["origem"] = [_origem(ne, el) for ne, el in zip(por_ne["ne_curta"], por_ne["elemento_cod"])]
    por_ne["contrato_numero"] = por_ne["ne_curta"].map(lambda n: "; ".join(info_contratos.get(n, {}).get("contrato_numero", [])) or None)
    por_ne["fornecedor"] = por_ne["ne_curta"].map(lambda n: "; ".join(info_contratos.get(n, {}).get("fornecedor", [])) or None)
    por_ne["programa_bolsa"] = por_ne["ne_curta"].map(lambda n: "; ".join(info_bolsas.get(n, {}).get("programa_bolsa", [])) or None)
    por_ne = por_ne[_COLUNAS_EMPENHADO_POR_NE].reset_index(drop=True)

    # uma NE pode ter várias linhas (uma por elemento): avisa uma vez só
    nes_selecionadas = list(dict.fromkeys(por_ne.loc[por_ne["celula_selecionada"], "ne_curta"]))
    for ne in nes_selecionadas:
        if ne in info_contratos and ne in info_bolsas:
            avisos.append(f"NE {ne} em Contratos e em Bolsas — conferir.")
        if len(info_contratos.get(ne, {}).get("contrato_numero", [])) > 1:
            avisos.append(f"NE {ne} compartilhada por mais de um contrato; empenho contado uma única vez.")

    selecionados = por_ne.loc[por_ne["celula_selecionada"]]
    # Correção (08/10/2026, revisão da Task 4): empenhado nulo em célula marcada não pode virar
    # zero na soma. Avisa, nomeando as NEs, e deixa o resultado incompleto.
    nes_empenho_nulo = list(dict.fromkeys(selecionados.loc[selecionados["empenhada"].isna(), "ne_curta"]))
    if nes_empenho_nulo:
        avisos.append(
            "Empenhado nulo (não informado) em célula marcada para a(s) NE: "
            + ", ".join(nes_empenho_nulo)
            + ". Resultado incompleto."
        )
    # Correção (08/10/2026, revisão final): os totais exibidos de empenhado (por origem e geral) ficam
    # None quando alguma linha selecionada é nula (soma_ou_nulo), em vez de ignorar o nulo (null != zero).
    empenhado_por_origem = {
        origem: soma_ou_nulo(selecionados.loc[selecionados["origem"] == origem, "empenhada"])
        for origem in ORIGENS_EMPENHADO
    }
    # Conferência independente da classificação: soma direta das linhas das células marcadas.
    empenhado_total = soma_ou_nulo(emp.loc[emp["celula_selecionada"], "empenhada"])
    # A diferença da conferência usa somas que ignoram nulos (nulo contribui igualmente aos dois lados).
    diferenca = float(emp.loc[emp["celula_selecionada"], "empenhada"].sum()) - float(
        sum(selecionados.loc[selecionados["origem"] == o, "empenhada"].sum()
            for o in ORIGENS_EMPENHADO)
    )
    if abs(diferenca) >= TOLERANCIA_CONFERENCIA:
        avisos.append(f"Conferência do empenhado não fecha: diferença de {_brl(diferenca)}.")

    # --- Executado e projetado (Contratos e Bolsas) --------------------------------------------------
    # Contrato sem NE e ATIVO entra no projetado (pedido de 08/10/2026): sem execução para medir, vale a necessidade
    # contratual (Resumo Consolidado). Os demais sem NE (suspenso, vencido, previsto…) ficam fora e só no aviso.
    # Status ausente não é tratado como ATIVO.
    ativos_sem_ne, sem_ne_fora = separar_ativos_sem_ne(sem_ne_contratos)
    nes_marcadas = set(selecionados["ne_curta"].astype(str))
    # NE parcialmente fora da seleção: a projeção é por NE, então ela entra inteira (sinalizado)
    parciais = sorted(
        set(por_ne.loc[por_ne["celula_selecionada"], "ne_curta"]) & set(por_ne.loc[~por_ne["celula_selecionada"], "ne_curta"])
    )
    if parciais:
        avisos.append(
            "NE com empenho dentro e fora das células marcadas entra inteira no executado e no projetado (a projeção é "
            "por NE): " + ", ".join(parciais) + "."
        )
    executado: dict[str, float | None] = {}
    projetado: dict[str, float | None] = {}
    detalhes = []
    for origem, linhas, excluir in (
        (ORIGEM_CONTRATOS, necessidade_contratos, set()),
        (ORIGEM_BOLSAS, necessidade_bolsas, set(info_contratos)),
    ):
        executado[origem], projetado[origem], detalhe = _consumo_da_origem(linhas, origem, nes_marcadas, excluir, avisos)
        detalhes.append(detalhe)
        if linhas is None:
            avisos.append(f"Projeção de {origem} indisponível: resultado incompleto.")
    if projetado[ORIGEM_CONTRATOS] is not None and len(ativos_sem_ne):
        ativos_valor = (
            soma_ou_nulo(pd.to_numeric(ativos_sem_ne["necessidade"], errors="coerce"))
            if "necessidade" in ativos_sem_ne else None
        )
        projetado[ORIGEM_CONTRATOS] = None if ativos_valor is None else projetado[ORIGEM_CONTRATOS] + ativos_valor
        rotulos = ", ".join(
            str(c) for c in (ativos_sem_ne["contrato_numero"] if "contrato_numero" in ativos_sem_ne else [])
        )
        avisos.append(
            f"{len(ativos_sem_ne)} contrato(s) ATIVO(s) sem NE incluído(s) no projetado de Contratos pela "
            f"necessidade contratual ({'valor não calculado' if ativos_valor is None else _brl(ativos_valor)})"
            + (f": {rotulos}." if rotulos else ".")
        )
    # cada despesa tem a sua marca "considerada" (escolha item a item, 15/10/2026); as desmarcadas ficam fora, em aviso
    projetado[OUTRAS_DESPESAS] = float(sum(d.valor for d in despesas_manuais if d.considerada))
    desconsideradas = [d for d in despesas_manuais if not d.considerada]
    if desconsideradas:
        avisos.append(
            f"{len(desconsideradas)} de {len(despesas_manuais)} outras despesas previstas desconsideradas "
            f"({_brl(float(sum(d.valor for d in desconsideradas)))}): fora da conta do resultado."
        )
    consumo_por_ne = pd.concat(detalhes, ignore_index=True) if detalhes else pd.DataFrame(columns=COLUNAS_CONSUMO_POR_NE)

    # o que abate a dotação já consumido: executado de Contratos e Bolsas + empenhado das demais origens
    demais = [o for o in ORIGENS_EMPENHADO if o not in ORIGENS_CONSUMO]
    partes_executado = [executado[o] for o in ORIGENS_CONSUMO] + [empenhado_por_origem[o] for o in demais]
    executado_total = None if any(v is None for v in partes_executado) else float(sum(partes_executado))

    for aviso in (
        _aviso_sem_ne(sem_ne_fora, "contrato", "contratos"),
        _aviso_sem_ne(sem_ne_bolsas, "bolsa", "bolsas"),
    ):
        if aviso:
            avisos.append(aviso)

    # --- Resultado --------------------------------------------------------------------------
    resultado: float | None = None
    if (
        dotacao is not None and executado_total is not None and not nes_empenho_nulo
        and all(v is not None for v in projetado.values())
    ):
        resultado = dotacao - executado_total - float(sum(projetado.values()))
    incompleto = bool(selecionadas) and resultado is None

    return ResultadoOrcamentario(
        dotacao=dotacao,
        empenhado=empenhado_por_origem,
        empenhado_total=empenhado_total,
        diferenca_conferencia=diferenca,
        executado=executado,
        projetado=projetado,
        executado_total=executado_total,
        resultado=resultado,
        incompleto=incompleto,
        empenhado_por_ne=por_ne,
        avisos=avisos,
        consumo_por_ne=consumo_por_ne,
        outras_desconsideradas_qtd=len(desconsideradas),
        outras_desconsideradas_valor=float(sum(d.valor for d in desconsideradas)),
        receita_limite=receita_limite,
        receita_aplicada=receita_aplicada,
        receita_excedente=receita_excedente,
        dotacao_integral=dotacao_integral,
        receitas_desconsideradas_qtd=len(receitas_fora),
        receitas_desconsideradas_valor=float(sum(r.valor for r in receitas_fora)),
    )
