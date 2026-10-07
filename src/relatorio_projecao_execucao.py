"""Relatório "Projeção pela Execução" — Contratos Contínuos (tela, PDF e Excel).

Camada: regra de relatório. Não lê planilha nem importa Streamlit. Relatório SEPARADO (pedido
explícito, 06/10/2026): não altera a Necessidade de Empenho, o Registro de contratos nem o Relatório
de Reforço — só os LÊ. Recebe a saída de `relatorio_necessidade_empenho.necessidade_por_ne` (custo,
saldo e necessidade contratual por NE, a mesma conta do Resumo Consolidado) e a Liquidação por
Competência por (NE, mês); a regra do fator está na primeira seção deste arquivo (abaixo).

Por NE: fator de execução (origem, peso, meses usados), grade Jan–Dez com o realizado, o restante dos
meses em aberto e a despesa projetada até dezembro, e:
  * Despesa projetada pela execução (restante do exercício) e a mesma pelo valor contratado cheio
    (fator 1, mesmos meses) — a diferença é o efeito isolado do fator;
  * Necessidade pela execução = max(0, despesa projetada pela execução − saldo do empenho), ao lado
    da Necessidade até dezembro contratual (Resumo Consolidado), para comparação.
Contrato sem NE fica de fora (não há execução para medir) e é contado nos avisos.

Contrato antecessor (herança do fator para NE sem histórico): informado por quem emite, a cada
emissão (`antecessores`); não é gravado no cadastro.

Pedido (06/10/2026): projetar a despesa levando em conta o que foi de fato liquidado — grande parte
dos contratos liquida menos que o valor mensal. Decisão do usuário: a diferença é EXECUÇÃO ABAIXO DO
CONTRATADO (economia real), não valor retido a pagar depois — por isso o fator abaixo de 1 é usado
como está. Contrato novo repete o valor mensal (fator 1).

REGRA (calibrada no teste retroativo sobre os meses já realizados de 2026, ver histórico):
  * Razão de cada mês = liquidado por competência ÷ custo contratado do mês (`custo_mensal`: valor
    em vigor, aditivos e meses proporcionais já embutidos).
  * Só meses FECHADOS entram: até `ultimo_mes_fechado` (o relatório usa 3 meses antes do mês da
    extração — os dois meses anteriores à extração ainda recebem liquidação). Dos meses fechados com
    registro e custo > 0, os últimos `JANELA_MESES` (6): tira janeiro–março (recesso e pico de
    retroativo de abril) da conta na maior parte do ano.
  * Execução observada = soma do liquidado ÷ soma do custo nesses meses (acumulada: atraso
    compensado no mês seguinte se anula, ao contrário da mediana).
  * Peso da execução = n·τ² ÷ (n·τ² + σ²), com n meses e σ² a variância das razões mensais:
    cresce com o número de meses e cai quanto mais a execução oscila. τ² = `TAU2_PRUDENCIA_ALTA`
    (0,01 — a mais prudente das testadas; a calibrada pelos dados, ~0,046, projeta menos e erra mais
    para baixo). Razões todas iguais (σ² = 0): peso 1.
  * Fator = 1 + (execução observada − 1) × peso. Menos de `MIN_MESES` (3) meses: sem histórico,
    fator 1 (valor mensal cheio) — ou o fator do contrato ANTECESSOR, quando informado.
  * Mês em aberto (os dois anteriores ao da extração): registro abaixo de `LIMIAR_MES_ABERTO` (50%)
    do esperado (custo × fator), ou sem registro → projeta o restante (esperado − liquidado);
    com 50% ou mais, conta como completo. Do mês da extração em diante: esperado − o que já houver
    de liquidado no mês (nunca negativo).

Valores: nulo ≠ zero. Liquidação negativa (estorno) entra na conta como veio; custo nulo (valor
desconhecido) não projeta (nulo); custo zero (fora da execução) não projeta nem conta como mês.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from io import BytesIO
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.contratos_aditivos import aditivos_do_registro, custo_mensal

# ------------------------------------------------------------------ fator de execução (regra)
JANELA_MESES = 6
MIN_MESES = 3
TAU2_PRUDENCIA_ALTA = 0.01
LIMIAR_MES_ABERTO = 0.5
#: meses entre o último mês fechado e o mês da extração (extração em outubro → fechados até julho)
DEFASAGEM_MESES_ABERTOS = 2

ORIGEM_EXECUCAO = "Execução observada"
ORIGEM_HERDADO = "Herdado do antecessor"
ORIGEM_SEM_HISTORICO = "Sem histórico (valor cheio)"

TIPO_REALIZADO = "Realizado"
TIPO_RESTANTE_ABERTO = "Restante do mês em aberto"
TIPO_PROJETADO = "Projetado"


def _numero(valor: object) -> float | None:
    if valor is None:
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(numero) else numero


@dataclass(frozen=True)
class FatorExecucao:
    fator: float
    peso: float
    #: liquidado ÷ custo acumulado nos meses usados; nulo sem histórico
    execucao_observada: float | None
    meses_usados: tuple[int, ...]
    origem: str
    ne_antecessora: str | None = None


def ultimo_mes_fechado(mes_referencia: int) -> int:
    """Último mês fechado do exercício para o mês da extração (0 a 12): três meses antes dele."""

    return mes_referencia - DEFASAGEM_MESES_ABERTOS - 1


def fator_de_execucao(
    realizado: dict[int, float], custo: list[float], ultimo_fechado: int, tau2: float = TAU2_PRUDENCIA_ALTA,
) -> FatorExecucao:
    """Fator de execução de uma NE (ver docstring do módulo). `realizado`: mês (1-12) → liquidado por
    competência no exercício (só meses com registro). `custo`: 12 custos contratados do mês."""

    meses = [
        mes for mes in range(1, 13)
        if mes <= ultimo_fechado and _numero(realizado.get(mes)) is not None
        and (_numero(custo[mes - 1]) or 0.0) > 0
    ][-JANELA_MESES:]
    if len(meses) < MIN_MESES:
        return FatorExecucao(1.0, 0.0, None, tuple(meses), ORIGEM_SEM_HISTORICO)

    liquidados = [float(realizado[mes]) for mes in meses]
    custos = [float(custo[mes - 1]) for mes in meses]
    observada = sum(liquidados) / sum(custos)
    razoes = [l / c for l, c in zip(liquidados, custos)]
    media = sum(razoes) / len(razoes)
    variancia = sum((r - media) ** 2 for r in razoes) / (len(razoes) - 1)
    n = len(meses)
    peso = 1.0 if variancia <= 1e-12 else n * tau2 / (n * tau2 + variancia)
    return FatorExecucao(1.0 + (observada - 1.0) * peso, peso, observada, tuple(meses), ORIGEM_EXECUCAO)


def herdar_fator(proprio: FatorExecucao, antecessor: FatorExecucao | None, ne_antecessora: str | None) -> FatorExecucao:
    """O fator do antecessor substitui o próprio só quando a NE não tem histórico e o antecessor tem.
    Caso contrário devolve o próprio (sem alteração)."""

    if proprio.origem != ORIGEM_SEM_HISTORICO or antecessor is None or antecessor.origem != ORIGEM_EXECUCAO:
        return proprio
    return FatorExecucao(
        antecessor.fator, antecessor.peso, antecessor.execucao_observada, antecessor.meses_usados,
        ORIGEM_HERDADO, ne_antecessora,
    )


@dataclass(frozen=True)
class ProjecaoMensal:
    #: 12 valores: liquidado por competência do mês (nulo sem registro)
    realizado: list[float | None]
    #: 12 valores: despesa projetada pela execução (nulo quando o mês não é projetado)
    projetado: list[float | None]
    #: 12 valores: a mesma projeção pelo valor contratado cheio (fator 1), nos mesmos meses
    projetado_valor_cheio: list[float | None]
    #: 12 tipos (`TIPO_*`) ou nulo
    tipos: list[str | None]

    @property
    def total_projetado(self) -> float:
        return sum(v for v in self.projetado if v is not None)

    @property
    def total_valor_cheio(self) -> float:
        return sum(v for v in self.projetado_valor_cheio if v is not None)

    def restante_em_aberto(self) -> list[tuple[int, float]]:
        return [
            (mes, self.projetado[mes - 1]) for mes in range(1, 13)
            if self.tipos[mes - 1] == TIPO_RESTANTE_ABERTO and (self.projetado[mes - 1] or 0.0) > 0
        ]


def projetar_meses(
    realizado: dict[int, float], custo: list[float], fator: float, mes_referencia: int,
) -> ProjecaoMensal:
    """Grade Jan–Dez de uma NE (ver docstring do módulo). Exercício encerrado (`mes_referencia` ≥ 12,
    mesma regra do relatório de Necessidade): nada é projetado."""

    fechado = ultimo_mes_fechado(mes_referencia)
    abertos = {mes for mes in range(fechado + 1, mes_referencia) if 1 <= mes <= 12}
    realizado_lista: list[float | None] = [_numero(realizado.get(mes)) for mes in range(1, 13)]
    projetado: list[float | None] = [None] * 12
    cheio: list[float | None] = [None] * 12
    tipos: list[str | None] = ["Realizado" if v is not None else None for v in realizado_lista]
    if mes_referencia >= 12:
        return ProjecaoMensal(realizado_lista, projetado, cheio, tipos)

    for mes in range(max(fechado + 1, 1), 13):
        custo_mes = _numero(custo[mes - 1])
        if custo_mes is None or custo_mes <= 0:
            continue
        liquidado = realizado_lista[mes - 1]
        esperado = custo_mes * fator
        if mes in abertos:
            if liquidado is not None and liquidado >= LIMIAR_MES_ABERTO * esperado:
                continue  # mês em aberto que já recebeu a maior parte: completo
            tipo = TIPO_RESTANTE_ABERTO
        elif mes < mes_referencia:
            continue
        else:
            tipo = TIPO_PROJETADO
        ja = liquidado or 0.0
        projetado[mes - 1] = max(0.0, esperado - ja)
        cheio[mes - 1] = max(0.0, custo_mes - ja)
        tipos[mes - 1] = tipo
    return ProjecaoMensal(realizado_lista, projetado, cheio, tipos)


# ------------------------------------------------------------------ relatório
TITULO = "PROJEÇÃO DA DESPESA PELA EXECUÇÃO — CONTRATOS CONTÍNUOS"
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

#: fator abaixo disso: liquidação muito menor que o cadastrado — provável despesa mensal a revisar
LIMIAR_ABAIXO_DO_CADASTRO = 0.5
#: execução observada acima disso: liquida mais que o contratado — provável aditivo não cadastrado
LIMIAR_ACIMA_DO_CONTRATO = 1.03

NOTA_REGRA = (
    f"Fator de execução = 1 + (execução observada − 1) × peso. Execução observada = liquidado por "
    f"competência ÷ custo contratado, acumulados nos últimos {JANELA_MESES} meses fechados (os dois meses "
    f"anteriores ao da extração ainda estão em aberto). Peso = n·τ² ÷ (n·τ² + variância das razões "
    f"mensais), τ² = {TAU2_PRUDENCIA_ALTA} (prudência alta): cresce com o nº de meses e cai com a oscilação. "
    f"Menos de {MIN_MESES} meses: fator 1 (valor mensal cheio) ou o do antecessor informado. Mês em aberto "
    f"com menos de {int(LIMIAR_MES_ABERTO * 100)}% do esperado (ou sem registro): projeta o restante. Do mês "
    "da extração a dezembro: custo contratado do mês × fator. Necessidade pela execução = despesa projetada "
    "− saldo do empenho (nunca negativa). A diferença para o valor contratado é tratada como execução abaixo "
    "do contratado (decisão de 06/10/2026)."
)


@dataclass(frozen=True)
class ContextoProjecaoExecucao:
    exercicio: int
    data_extracao: str
    hash_manifesto: str
    data_emissao: str
    origem_competencia: str


@dataclass(frozen=True)
class RelatorioProjecaoExecucao:
    #: uma linha por NE, em ordem decrescente de necessidade pela execução
    linhas: pd.DataFrame
    #: mesmo índice: r1..r12 (realizado), p1..p12 (projetado pela execução), t1..t12 (tipo do mês)
    mensal: pd.DataFrame
    exercicio: int
    mes_referencia: int
    ultimo_fechado: int
    qtd_sem_ne: int
    avisos: list[str] = field(default_factory=list)

    def _soma(self, coluna: str) -> float:
        return float(self.linhas[coluna].sum(min_count=1)) if not self.linhas.empty else 0.0

    @property
    def total_projetado_execucao(self) -> float:
        return self._soma("projetado_execucao")

    @property
    def total_projetado_valor_cheio(self) -> float:
        return self._soma("projetado_valor_cheio")

    @property
    def total_restante_em_aberto(self) -> float:
        return self._soma("restante_em_aberto")

    @property
    def total_necessidade_execucao(self) -> float:
        return self._soma("necessidade_execucao")

    @property
    def total_necessidade_contratual(self) -> float:
        return self._soma("necessidade_contratual")

    @property
    def total_saldo(self) -> float:
        return self._soma("saldo")


def _realizado_por_ne(liquidacao_mensal: pd.DataFrame | None, exercicio: int) -> dict[str, dict[int, float]]:
    if liquidacao_mensal is None or liquidacao_mensal.empty:
        return {}
    ano_mes = liquidacao_mensal["ano_mes"].astype("int64")
    serie = liquidacao_mensal.assign(ano=ano_mes // 100, mes=ano_mes % 100)
    serie = serie[(serie["ano"] == exercicio) & serie["mes"].between(1, 12)]
    agrupado = serie.groupby(["ne_curta", "mes"])["valor"].sum(min_count=1)
    resultado: dict[str, dict[int, float]] = {}
    for (ne, mes), valor in agrupado.items():
        if not pd.isna(valor):
            resultado.setdefault(ne, {})[int(mes)] = float(valor)
    return resultado


def _custo_da_ne(linha: pd.Series, exercicio: int) -> list[float]:
    """Custo contratado mês a mês da NE — a MESMA chamada de `_aplicar_necessidade` (Resumo)."""

    return custo_mensal(
        linha["despesa_mensal"], aditivos_do_registro(linha["aditivos"]), exercicio,
        status=linha["status_contrato"], vigencia_fim=linha["vigencia_fim"],
        inicio=linha["inicio_execucao_considerado"], data_suspensao=linha["data_suspensao"],
        meses_no_ano=linha["meses_no_ano"],
    )


def fatores_por_ne(
    por_ne: pd.DataFrame, liquidacao_mensal: pd.DataFrame | None, exercicio: int, mes_referencia: int,
) -> dict[str, object]:
    """Fator próprio de cada NE (sem herança) — a tela usa para listar quem pode ser antecessor."""

    realizados = _realizado_por_ne(liquidacao_mensal, exercicio)
    fechado = ultimo_mes_fechado(mes_referencia)
    return {
        linha["ne_curta"]: fator_de_execucao(realizados.get(linha["ne_curta"], {}), _custo_da_ne(linha, exercicio), fechado)
        for _, linha in por_ne.iterrows()
    }


def montar_relatorio(
    por_ne: pd.DataFrame,
    sem_ne: pd.DataFrame,
    liquidacao_mensal: pd.DataFrame | None,
    exercicio: int,
    mes_referencia: int,
    antecessores: dict[str, str] | None = None,
) -> RelatorioProjecaoExecucao:
    """`por_ne`/`sem_ne`: saída de `necessidade_por_ne(..., exercicio)`. `liquidacao_mensal`:
    `ne_curta`, `ano_mes`, `valor` (Liquidação por Competência). `antecessores`: NE sem histórico →
    NE cujo fator ela herda. Não altera as entradas."""

    antecessores = antecessores or {}
    realizados = _realizado_por_ne(liquidacao_mensal, exercicio)
    fechado = ultimo_mes_fechado(mes_referencia)
    proprios = fatores_por_ne(por_ne, liquidacao_mensal, exercicio, mes_referencia)

    registros, mensais = [], []
    avisos_antecessor = []
    for _, linha in por_ne.iterrows():
        ne = linha["ne_curta"]
        custo = _custo_da_ne(linha, exercicio)
        fator = proprios[ne]
        ne_ant = antecessores.get(ne)
        if ne_ant:
            herdado = herdar_fator(fator, proprios.get(ne_ant), ne_ant)
            if herdado is fator:
                motivo = (
                    "ela já tem histórico próprio" if fator.origem != ORIGEM_SEM_HISTORICO
                    else f"{ne_ant} não tem histórico suficiente"
                )
                avisos_antecessor.append(f"{ne}: antecessor {ne_ant} ignorado — {motivo}.")
            fator = herdado
        projecao = projetar_meses(realizados.get(ne, {}), custo, fator.fator, mes_referencia)
        saldo = linha["saldo_para_necessidade"]
        saldo_num = 0.0 if pd.isna(saldo) else float(saldo)
        restante = sum(v for _, v in projecao.restante_em_aberto())
        registros.append(
            {
                "ne_curta": ne,
                "fornecedor": linha["fornecedor"],
                "contrato_numero": linha["contrato_numero"],
                "status_contrato": linha["status_contrato"],
                "vigencia_fim": linha["vigencia_fim"],
                "despesa_mensal": linha["despesa_mensal"],
                "valor_empenhado": linha["valor_empenhado_exibido"],
                "saldo": saldo,
                "origem_fator": fator.origem,
                "ne_antecessora": fator.ne_antecessora,
                "execucao_observada": fator.execucao_observada,
                "peso": fator.peso,
                "fator": fator.fator,
                "meses_usados": ", ".join(MESES[m - 1] for m in fator.meses_usados),
                "restante_em_aberto": restante,
                "projetado_execucao": projecao.total_projetado,
                "projetado_valor_cheio": projecao.total_valor_cheio,
                "necessidade_execucao": max(0.0, projecao.total_projetado - saldo_num),
                "necessidade_contratual": linha["necessidade"],
            }
        )
        mensais.append(
            {
                **{f"r{m}": projecao.realizado[m - 1] for m in range(1, 13)},
                **{f"p{m}": projecao.projetado[m - 1] for m in range(1, 13)},
                **{f"t{m}": projecao.tipos[m - 1] for m in range(1, 13)},
            }
        )

    colunas_mensal = [f"r{m}" for m in range(1, 13)] + [f"p{m}" for m in range(1, 13)] + [f"t{m}" for m in range(1, 13)]
    linhas = pd.DataFrame(registros)
    mensal = pd.DataFrame(mensais, columns=colunas_mensal)
    if not linhas.empty:
        ordem = linhas["necessidade_execucao"].sort_values(ascending=False, kind="stable").index
        linhas = linhas.loc[ordem].reset_index(drop=True)
        mensal = mensal.loc[ordem].reset_index(drop=True)
        for coluna in ("execucao_observada", "peso", "fator", "saldo", "necessidade_contratual", "valor_empenhado"):
            linhas[coluna] = pd.to_numeric(linhas[coluna], errors="coerce").astype("float64")

    relatorio = RelatorioProjecaoExecucao(
        linhas=linhas, mensal=mensal, exercicio=exercicio, mes_referencia=mes_referencia,
        ultimo_fechado=fechado, qtd_sem_ne=len(sem_ne),
    )
    relatorio.avisos.extend(_avisos(relatorio) + avisos_antecessor)
    return relatorio


def _rotulo_ne(linha: pd.Series) -> str:
    contrato = linha["contrato_numero"]
    return f"{linha['ne_curta']}" + (f" (contrato {contrato})" if pd.notna(contrato) else "")


def _avisos(relatorio: RelatorioProjecaoExecucao) -> list[str]:
    linhas = relatorio.linhas
    avisos = []
    if relatorio.mes_referencia >= 12:
        avisos.append("Extração em dezembro ou depois: exercício encerrado, nada é projetado.")
    if linhas.empty:
        return avisos
    abaixo = linhas[(linhas["origem_fator"] == ORIGEM_EXECUCAO) & (linhas["fator"] < LIMIAR_ABAIXO_DO_CADASTRO)]
    if not abaixo.empty:
        avisos.append(
            "Liquidação muito abaixo do cadastrado (fator < "
            f"{LIMIAR_ABAIXO_DO_CADASTRO:.2f}) — conferir a despesa mensal do cadastro: "
            + ", ".join(f"{_rotulo_ne(l)} fator {l['fator']:.2f}" for _, l in abaixo.iterrows()) + "."
        )
    acima = linhas[(linhas["origem_fator"] == ORIGEM_EXECUCAO) & (linhas["execucao_observada"] > LIMIAR_ACIMA_DO_CONTRATO)]
    if not acima.empty:
        avisos.append(
            "Liquida acima do contratado — provável reajuste/aditivo não cadastrado: "
            + ", ".join(f"{_rotulo_ne(l)} execução {l['execucao_observada']:.2f}" for _, l in acima.iterrows()) + "."
        )
    herdados = linhas[linhas["origem_fator"] == ORIGEM_HERDADO]
    if not herdados.empty:
        avisos.append(
            "Fator herdado do contrato antecessor informado: "
            + ", ".join(f"{_rotulo_ne(l)} ← {l['ne_antecessora']} ({l['fator']:.2f})" for _, l in herdados.iterrows()) + "."
        )
    sem_historico = linhas[(linhas["origem_fator"] == ORIGEM_SEM_HISTORICO) & (linhas["projetado_execucao"] > 0)]
    if not sem_historico.empty:
        avisos.append(
            f"Menos de {MIN_MESES} meses fechados de execução — projetado pelo valor mensal cheio: "
            + ", ".join(_rotulo_ne(l) for _, l in sem_historico.iterrows()) + "."
        )
    em_aberto = linhas[linhas["restante_em_aberto"] > 0].sort_values("restante_em_aberto", ascending=False)
    if not em_aberto.empty:
        maiores = ", ".join(
            f"{l['ne_curta']} R$ {_formatar_brl(l['restante_em_aberto'])}" for _, l in em_aberto.head(5).iterrows()
        )
        avisos.append(
            f"Meses em aberto (liquidação ainda incompleta ou sem registro): {len(em_aberto)} NE(s), restante "
            f"projetado R$ {_formatar_brl(em_aberto['restante_em_aberto'].sum())} — maiores: {maiores} "
            "(detalhe mês a mês na grade, em laranja)."
        )
    if relatorio.qtd_sem_ne:
        avisos.append(
            f"{relatorio.qtd_sem_ne} item(ns) de contrato sem NE fora deste relatório (sem execução para medir) — "
            "ver o relatório de Necessidade de Empenho."
        )
    return avisos


# ------------------------------------------------------------------------------ formatação
def _formatar_brl(valor: object) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    texto = f"{float(valor):,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _formatar_fator(valor: object) -> str:
    return "—" if valor is None or pd.isna(valor) else f"{float(valor):.2f}".replace(".", ",")


def _texto(valor: object) -> str:
    return "" if valor is None or pd.isna(valor) else str(valor)


def linhas_parametros(relatorio: RelatorioProjecaoExecucao, contexto: ContextoProjecaoExecucao) -> list[tuple[str, str]]:
    fechado = relatorio.ultimo_fechado
    return [
        ("Exercício", str(contexto.exercicio)),
        ("Extração da Execução Mensal", f"{contexto.data_extracao} (manifesto {contexto.hash_manifesto})"),
        ("Liquidação por Competência", contexto.origem_competencia),
        ("Meses fechados (base do fator)", f"até {MESES[fechado - 1]}" if 1 <= fechado <= 12 else "nenhum"),
        ("Emitido em", contexto.data_emissao),
        ("NEs no relatório", str(len(relatorio.linhas))),
        ("Saldo dos empenhos (R$)", _formatar_brl(relatorio.total_saldo)),
        ("Despesa projetada pela execução (R$)", _formatar_brl(relatorio.total_projetado_execucao)),
        ("  dos quais restante de meses em aberto (R$)", _formatar_brl(relatorio.total_restante_em_aberto)),
        ("Despesa projetada pelo valor contratado (R$)", _formatar_brl(relatorio.total_projetado_valor_cheio)),
        ("Necessidade pela execução (R$)", _formatar_brl(relatorio.total_necessidade_execucao)),
        ("Necessidade até dezembro — contratual (R$)", _formatar_brl(relatorio.total_necessidade_contratual)),
        ("Regra", NOTA_REGRA),
    ]


def _resumo(relatorio: RelatorioProjecaoExecucao) -> pd.DataFrame:
    linhas = relatorio.linhas
    return pd.DataFrame(
        {
            "NE": linhas["ne_curta"].map(_texto).astype(object),
            "Fornecedor": linhas["fornecedor"].map(_texto).astype(object),
            "Contrato": linhas["contrato_numero"].map(_texto).astype(object),
            "Status": linhas["status_contrato"].map(_texto).astype(object),
            "Despesa mensal": linhas["despesa_mensal"],
            "Empenhado": linhas["valor_empenhado"],
            "Saldo do empenho": linhas["saldo"],
            "Origem do fator": linhas["origem_fator"].astype(object),
            "NE antecessora": linhas["ne_antecessora"].map(_texto).replace("", None).astype(object),
            "Meses usados": linhas["meses_usados"].replace("", None).astype(object),
            "Execução observada": linhas["execucao_observada"],
            "Peso da execução": linhas["peso"],
            "Fator de execução": linhas["fator"],
            "Restante de meses em aberto": linhas["restante_em_aberto"],
            "Despesa projetada (execução)": linhas["projetado_execucao"],
            "Despesa projetada (valor contratado)": linhas["projetado_valor_cheio"],
            "Necessidade pela execução": linhas["necessidade_execucao"],
            "Necessidade até dezembro (contratual)": linhas["necessidade_contratual"],
        }
    )


_COLUNAS_FATOR_XLSX = {"Execução observada", "Peso da execução", "Fator de execução"}
_COLUNAS_TEXTO_XLSX = {"NE", "Fornecedor", "Contrato", "Status", "Origem do fator", "NE antecessora", "Meses usados", "Tipo"}
_PREENCHIMENTO_PROJETADO = "DCE6F2"
_PREENCHIMENTO_ABERTO = "FCE4C4"


def _formatar_aba(planilha, dados: pd.DataFrame) -> None:
    for indice, cabecalho in enumerate(dados.columns, start=1):
        letra = planilha.cell(row=1, column=indice).column_letter
        formato = "@" if cabecalho in _COLUNAS_TEXTO_XLSX else ("0.00" if cabecalho in _COLUNAS_FATOR_XLSX else "#,##0.00")
        for celula in planilha[letra][1:]:
            celula.number_format = formato
        planilha.column_dimensions[letra].width = 45 if cabecalho == "Fornecedor" else min(max(len(cabecalho), 12) + 2, 34)
    planilha.freeze_panes = "B2"


def gerar_xlsx(relatorio: RelatorioProjecaoExecucao, contexto: ContextoProjecaoExecucao) -> bytes:
    """Abas: "Resumo por NE", "Grade mensal" (Jan–Dez: realizado ou projetado; projetado sombreado,
    restante de mês em aberto em laranja), "Detalhe mensal" (formato longo com o tipo de cada mês) e
    "Parâmetros" (avisos, totais e regra). Nulo é célula vazia, nunca zero."""

    from openpyxl.styles import Font, PatternFill

    resumo = _resumo(relatorio)
    grade_linhas, marcas, detalhe = [], [], []
    for indice, linha in relatorio.linhas.iterrows():
        valores, tipos = {}, []
        for mes in range(1, 13):
            tipo = relatorio.mensal.at[indice, f"t{mes}"]
            projetado = relatorio.mensal.at[indice, f"p{mes}"]
            realizado = relatorio.mensal.at[indice, f"r{mes}"]
            if tipo in (TIPO_PROJETADO, TIPO_RESTANTE_ABERTO):
                valores[MESES[mes - 1]] = projetado
            else:
                valores[MESES[mes - 1]] = realizado
            tipos.append(tipo)
            if tipo is not None:
                detalhe.append(
                    {
                        "NE": linha["ne_curta"], "Fornecedor": _texto(linha["fornecedor"]), "Nº do mês": mes,
                        "Mês": MESES[mes - 1], "Tipo": tipo,
                        "Realizado": None if pd.isna(realizado) else realizado,
                        "Projetado": None if projetado is None or pd.isna(projetado) else projetado,
                    }
                )
        grade_linhas.append({"NE": linha["ne_curta"], "Fornecedor": _texto(linha["fornecedor"]), "Fator de execução": linha["fator"], **valores,
                             "Despesa projetada (execução)": linha["projetado_execucao"]})
        marcas.append(tipos)
    grade = pd.DataFrame(grade_linhas, columns=["NE", "Fornecedor", "Fator de execução", *MESES, "Despesa projetada (execução)"])
    detalhe_df = pd.DataFrame(detalhe, columns=["NE", "Fornecedor", "Nº do mês", "Mês", "Tipo", "Realizado", "Projetado"])
    parametros = [("Avisos", aviso) for aviso in relatorio.avisos] + linhas_parametros(relatorio, contexto)
    coluna_jan = list(grade.columns).index(MESES[0]) + 1

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        resumo.to_excel(writer, sheet_name="Resumo por NE", index=False)
        _formatar_aba(writer.sheets["Resumo por NE"], resumo)
        grade.to_excel(writer, sheet_name="Grade mensal", index=False)
        planilha = writer.sheets["Grade mensal"]
        _formatar_aba(planilha, grade)
        for numero_linha, tipos in enumerate(marcas, start=2):
            for mes, tipo in enumerate(tipos):
                if tipo in (TIPO_PROJETADO, TIPO_RESTANTE_ABERTO):
                    celula = planilha.cell(row=numero_linha, column=coluna_jan + mes)
                    cor = _PREENCHIMENTO_ABERTO if tipo == TIPO_RESTANTE_ABERTO else _PREENCHIMENTO_PROJETADO
                    celula.fill = PatternFill("solid", fgColor=cor)
                    celula.font = Font(italic=True)
        detalhe_df.to_excel(writer, sheet_name="Detalhe mensal", index=False)
        _formatar_aba(writer.sheets["Detalhe mensal"], detalhe_df)
        writer.sheets["Detalhe mensal"].column_dimensions["C"].width = 10
        for celula in writer.sheets["Detalhe mensal"]["C"][1:]:
            celula.number_format = "0"
        pd.DataFrame(parametros, columns=["Parâmetro", "Valor"]).to_excel(writer, sheet_name="Parâmetros", index=False)
        writer.sheets["Parâmetros"].column_dimensions["A"].width = 46
        writer.sheets["Parâmetros"].column_dimensions["B"].width = 120
    return buffer.getvalue()


# -------------------------------------------------------------------------------- PDF
_CABECALHO_GRADE_PDF = ["NE", "FATOR", *[m.upper() for m in MESES], "PROJETADO"]
_LARGURAS_GRADE_PDF = [62, 36] + [48] * 12 + [66]
_CABECALHO_RESUMO_PDF = [
    "NE", "FORNECEDOR / CONTRATO", "ORIGEM DO FATOR", "EXEC. OBS.", "PESO", "FATOR", "SALDO (R$)",
    "PROJ. EXECUÇÃO (R$)", "PROJ. CONTRATADO (R$)", "NEC. EXECUÇÃO (R$)", "NEC. CONTRATUAL (R$)",
]
_LARGURAS_RESUMO_PDF = [58, 170, 78, 38, 32, 34, 66, 72, 72, 72, 72]
_COR_TITULO_NE = colors.HexColor("#E8EEF7")
_COR_PROJETADO = colors.HexColor(f"#{_PREENCHIMENTO_PROJETADO}")
_COR_ABERTO = colors.HexColor(f"#{_PREENCHIMENTO_ABERTO}")


def _estilo_base() -> list[tuple]:
    return [
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDDDDD")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]


def gerar_pdf(relatorio: RelatorioProjecaoExecucao, contexto: ContextoProjecaoExecucao) -> bytes:
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
        title=f"{TITULO} — {contexto.exercicio}",
    )
    estilos = getSampleStyleSheet()
    estilo_parametro = estilos["Normal"].clone("parametro_projecao")
    estilo_parametro.fontSize = 8
    estilo_parametro.leading = 10
    estilo_aviso = estilo_parametro.clone("aviso_projecao")
    estilo_aviso.textColor = colors.HexColor("#8A4B00")
    estilo_celula = estilos["Normal"].clone("celula_projecao")
    estilo_celula.fontSize = 6.5
    estilo_celula.leading = 7.5
    estilo_secao = estilos["Heading4"]

    elementos: list = [Paragraph(escape(f"{TITULO} — EXERCÍCIO {contexto.exercicio}"), estilos["Heading3"])]
    for aviso in relatorio.avisos:
        elementos.append(Paragraph(f"<b>ATENÇÃO:</b> {escape(aviso)}", estilo_aviso))
    for rotulo, valor in linhas_parametros(relatorio, contexto):
        elementos.append(Paragraph(f"<b>{escape(rotulo.strip())}:</b> {escape(valor)}", estilo_parametro))
    elementos.append(Spacer(1, 8))

    # ---- resumo por NE
    dados = [_CABECALHO_RESUMO_PDF]
    for _, linha in relatorio.linhas.iterrows():
        origem = linha["origem_fator"] + (f" ({linha['ne_antecessora']})" if pd.notna(linha["ne_antecessora"]) and linha["ne_antecessora"] else "")
        dados.append(
            [
                linha["ne_curta"],
                Paragraph(f"{escape(_texto(linha['fornecedor']) or '(sem fornecedor)')}<br/>Contrato {escape(_texto(linha['contrato_numero']) or '—')}", estilo_celula),
                Paragraph(escape(origem), estilo_celula),
                _formatar_fator(linha["execucao_observada"]), _formatar_fator(linha["peso"]), _formatar_fator(linha["fator"]),
                _formatar_brl(linha["saldo"]), _formatar_brl(linha["projetado_execucao"]),
                _formatar_brl(linha["projetado_valor_cheio"]), _formatar_brl(linha["necessidade_execucao"]),
                _formatar_brl(linha["necessidade_contratual"]),
            ]
        )
    dados.append(
        [
            "TOTAL", "", "", "", "", "", _formatar_brl(relatorio.total_saldo),
            _formatar_brl(relatorio.total_projetado_execucao), _formatar_brl(relatorio.total_projetado_valor_cheio),
            _formatar_brl(relatorio.total_necessidade_execucao), _formatar_brl(relatorio.total_necessidade_contratual),
        ]
    )
    tabela = Table(dados, colWidths=_LARGURAS_RESUMO_PDF, repeatRows=1)
    tabela.setStyle(TableStyle(_estilo_base() + [
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F5F5F5")]),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    elementos.append(Paragraph("Resumo por NE — fator de execução, despesa projetada e necessidade", estilo_secao))
    elementos.append(tabela)
    elementos.append(Spacer(1, 10))

    # ---- grade mensal
    dados = [_CABECALHO_GRADE_PDF]
    comandos: list[tuple] = []
    for indice, linha in relatorio.linhas.iterrows():
        posicao = len(dados)
        titulo = (
            f"<b>{escape(linha['ne_curta'])}</b> — {escape(_texto(linha['fornecedor']) or '(sem fornecedor)')}"
            f" — Contrato {escape(_texto(linha['contrato_numero']) or '—')} — {escape(linha['origem_fator'])}"
            f" — Meses usados: {escape(_texto(linha['meses_usados']) or '—')}"
        )
        dados.append([Paragraph(titulo, estilo_celula)] + [""] * (len(_CABECALHO_GRADE_PDF) - 1))
        celulas = []
        for mes in range(1, 13):
            tipo = relatorio.mensal.at[indice, f"t{mes}"]
            if tipo in (TIPO_PROJETADO, TIPO_RESTANTE_ABERTO):
                celulas.append(_formatar_brl(relatorio.mensal.at[indice, f"p{mes}"]))
                cor = _COR_ABERTO if tipo == TIPO_RESTANTE_ABERTO else _COR_PROJETADO
                comandos += [
                    ("BACKGROUND", (mes + 1, posicao + 1), (mes + 1, posicao + 1), cor),
                    ("FONTNAME", (mes + 1, posicao + 1), (mes + 1, posicao + 1), "Helvetica-Oblique"),
                ]
            else:
                celulas.append(_formatar_brl(relatorio.mensal.at[indice, f"r{mes}"]))
        dados.append([linha["ne_curta"], _formatar_fator(linha["fator"]), *celulas, _formatar_brl(linha["projetado_execucao"])])
        comandos += [
            ("SPAN", (0, posicao), (-1, posicao)),
            ("BACKGROUND", (0, posicao), (-1, posicao), _COR_TITULO_NE),
            ("NOSPLIT", (0, posicao), (-1, posicao + 1)),
        ]
    tabela = Table(dados, colWidths=_LARGURAS_GRADE_PDF, repeatRows=1)
    tabela.setStyle(TableStyle(_estilo_base() + [("ALIGN", (1, 0), (-1, -1), "RIGHT")] + comandos))
    elementos.append(Paragraph(
        "Realizado × projeção mês a mês (projetado sombreado em azul; restante de mês em aberto em laranja)", estilo_secao
    ))
    elementos.append(tabela)
    documento.build(elementos)
    return buffer.getvalue()
