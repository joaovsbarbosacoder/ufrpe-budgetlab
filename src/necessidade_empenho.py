"""
Necessidade de empenho — regra de negócio compartilhada por Contratos Contínuos e Bolsas.

Camada: regra específica de negócio, não leitor, não interface. Depende só de pandas.

Contexto: as duas planilhas de origem têm uma coluna "MESES A EMPENHAR"/"EMPENHAR (R$)" que,
na prática, está vazia (Contratos Contínuos) ou preenchida à mão de forma inconsistente
(Bolsas) — não é uma fórmula confiável em nenhuma das duas. A fórmula real e validada contra
dado de verdade é a de "MESES DE SALDO" nas duas planilhas: `meses_empenhados - meses_liquidados`
(confirmado célula a célula nas duas bases — ver histórico da conversa). Este módulo recalcula
essa mesma conta como `meses_a_empenhar`, para não depender do campo manual da origem.
"""

from __future__ import annotations

import calendar
from datetime import date

import pandas as pd


def calcular_necessidade_empenho(
    meses_empenhados: pd.Series, meses_liquidados: pd.Series, valor_mensal: pd.Series
) -> tuple[pd.Series, pd.Series]:
    """meses_a_empenhar = meses_empenhados − meses_liquidados; valor_a_empenhar = valor_mensal × meses_a_empenhar.

    Mesma fórmula da coluna "MESES DE SALDO" já existente nas duas planilhas de origem
    (Contratos Contínuos e Bolsas), recalculada aqui para não depender do campo manual
    "MESES A EMPENHAR"/"EMPENHAR (R$)" de cada uma (vazio ou inconsistente na origem).
    """
    meses_a_empenhar = meses_empenhados - meses_liquidados
    valor_a_empenhar = valor_mensal * meses_a_empenhar
    return meses_a_empenhar, valor_a_empenhar


def necessidade_ate_mes_vigente(
    valor_mensal: pd.Series, valor_empenhado: pd.Series, inicio_execucao_mes: pd.Series,
    ano_referencia: int,
    hoje: date | None = None,
    meses_no_ano: pd.Series | None = None,
    fracao_primeiro_mes: pd.Series | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Quanto falta empenhar para acompanhar o calendário até o mês vigente — métrica
    diferente de `calcular_necessidade_empenho` (que compara empenhado × liquidado, execução
    real). Pedido explícito: "parametrize o sistema para que ele fique pronto para empenhar o
    que falta para o mês vigente" (ex.: despesa anual R$ 120 mil, já empenhado R$ 70 mil,
    estamos em outubro → deveria estar empenhado R$ 100 mil → sugestão R$ 30 mil).

    `inicio_execucao_mes` é o mês (1-12) em que a NE recebeu o primeiro empenho DENTRO do
    exercício `ano_referencia` — auto-detectado a partir da base mensal (`src.
    tesouro_execucao_mensal.primeiro_mes_com_empenho_por_ne`) ou informado manualmente no
    cadastro, quando o usuário perceber um erro na detecção (ver
    `app_pages/bolsas_auxilios.py`/`app_pages/contratos_continuos.py::_render_card`). Meses
    decorridos contados de forma inclusiva a partir desse mês (mês de início conta como 1º
    mês) — mesmo critério de calendário (ano civil, não vigência do contrato) já usado em
    "Necessidade até Dezembro" no Resumo Consolidado.

    `ano_referencia` é o exercício do cadastro sendo calculado (não necessariamente o ano
    corrente) — corrige um bug real na virada de exercício: sem ele, um cadastro de 2026 ainda
    não duplicado para 2027 (`src.cadastro_por_exercicio`, duplicação é manual) calculava
    `hoje.month - inicio_execucao_mes + 1` misturando o mês real de HOJE (já em 2027) com um
    `inicio_execucao_mes` de 2026 — para uma NE iniciada em outubro, isso dava `1 - 10 + 1 =
    -8`, sempre limitado (`clip`) a zero, subestimando a sugestão silenciosamente, sem nenhum
    aviso na tela. Regra: `hoje.year` só entra na conta quando bate com `ano_referencia`
    (exercício em andamento, comportamento de sempre); se `hoje` já passou do exercício
    (`ano_referencia` encerrado), o exercício inteiro já decorreu — usa dezembro (12) como mês
    vigente, não o mês real de hoje, que pertence a outro exercício.

    Nunca fica negativo: já ter empenhado mais do que o alvo do mês vigente não sugere
    "desempenhar", vira zero (mesmo critério de "Necessidade até Dezembro"). Usada só na
    sugestão inicial do Relatório de Reforço de Empenho (pedido explícito de escopo) — o
    "Meses de Saldo"/"Empenhar" de cada cartão continua vindo de
    `calcular_necessidade_empenho`, inalterado.

    `meses_no_ano` (opcional — Contratos Contínuos não tem esse conceito, sempre `None` pra
    essa base) é o total de meses que o item é pago no exercício, vindo do cadastro (ex.: bolsa
    "parcela única" tem `meses_no_ano=1`) — teto de `meses_decorridos`: sem ele, uma bolsa já
    paga por completo (ex. parcela única já empenhada e liquidada) continuava sugerindo mais
    meses só porque o calendário já passou vários meses desde o início da execução, mesmo sem
    nenhum pagamento programado pra eles (bug real reportado pelo usuário, caso concreto:
    AUXÍLIO BEXT — Parcela Única, `meses_no_ano=1`, sugeria 6 meses de reforço já tendo pago o
    único mês devido).

    `fracao_primeiro_mes` (opcional, pedido explícito 02/10/2026 — início da execução por DATA):
    fração (0-1] do primeiro mês efetivamente em execução (dias de execução ÷ dias do mês). O
    mês de início deixa de contar inteiro: desconta-se `1 − fração` dos meses decorridos (só
    quando já decorreu ao menos um mês). Sem ela (`None`) o mês de início conta cheio, como
    sempre.
    """
    hoje = hoje or date.today()
    mes_vigente = 12 if hoje.year > ano_referencia else max(0, min(hoje.month, 12))
    if hoje.year < ano_referencia:
        mes_vigente = 0
    meses_decorridos = (mes_vigente - inicio_execucao_mes + 1).clip(lower=0)
    if fracao_primeiro_mes is not None:
        meses_decorridos = (meses_decorridos - (1 - fracao_primeiro_mes)).where(meses_decorridos > 0, 0).clip(lower=0)
    if meses_no_ano is not None:
        meses_decorridos = meses_decorridos.clip(upper=meses_no_ano)
    meses_empenhados_equivalente = valor_empenhado / valor_mensal.replace(0, pd.NA)
    meses_sugeridos = (meses_decorridos - meses_empenhados_equivalente).clip(lower=0)
    valor_sugerido = meses_sugeridos * valor_mensal
    return meses_sugeridos, valor_sugerido


STATUS_ATIVO = "ATIVO"
STATUS_VENCIDO = "VENCIDO"
STATUS_SUSPENSO = "SUSPENSO"


def _status_normalizado(status: object) -> str | None:
    return None if status is None or pd.isna(status) else str(status).strip().upper()


def _posicao_em_meses(data: pd.Timestamp, fim_do_dia: bool) -> float:
    """Posição da data dentro do ano, em meses (0 a 12): o mês é proporcional aos dias. Início do
    dia para a data de INÍCIO (dia 1 → mês cheio), fim do dia para a de FIM (último dia → mês
    cheio)."""

    dias_do_mes = calendar.monthrange(data.year, data.month)[1]
    dias_decorridos = data.day if fim_do_dia else data.day - 1
    return (data.month - 1) + dias_decorridos / dias_do_mes


def meses_vigentes_no_exercicio(
    status: object, vigencia_fim: object, exercicio: int, inicio: object = None
) -> float | None:
    """Quantos meses do `exercicio` o contrato está em execução (fração; do início da execução —
    janeiro se não informado — até o fim da vigência — dezembro se não informado —, o mês inicial
    e o final proporcionais aos dias) — `None` quando nada limita (sem data de fim dentro do
    exercício e sem início depois de 1º de janeiro). SUSPENSO: 0. VENCIDO sem data de fim: 0. Fim
    em ano anterior ao exercício, ou início em ano posterior: 0. A data manda sobre o status
    (VENCIDO com vigência futura segue a data). `inicio` é a data de início da execução
    informada pelo usuário (nunca presumida). Pedido explícito, 02/10/2026 — usada pela
    Necessidade de Empenho (Resumo Consolidado/relatório) e pela sugestão do Relatório de
    Reforço de Contratos Contínuos."""

    status_texto = _status_normalizado(status)
    if status_texto == STATUS_SUSPENSO:
        return 0.0
    tem_fim = vigencia_fim is not None and not pd.isna(vigencia_fim)
    if not tem_fim and status_texto == STATUS_VENCIDO:
        return 0.0

    posicao_inicio = 0.0
    if inicio is not None and not pd.isna(inicio):
        data_inicio = pd.Timestamp(inicio)
        if data_inicio.year > exercicio:
            return 0.0
        if data_inicio.year == exercicio:
            posicao_inicio = _posicao_em_meses(data_inicio, fim_do_dia=False)

    posicao_fim = 12.0
    fim_no_exercicio = False
    if tem_fim:
        data_fim = pd.Timestamp(vigencia_fim)
        if data_fim.year < exercicio:
            return 0.0
        if data_fim.year == exercicio:
            fim_no_exercicio = True
            posicao_fim = _posicao_em_meses(data_fim, fim_do_dia=True)

    if posicao_inicio == 0.0 and not fim_no_exercicio:
        return None  # nada limita: o contrato cobre o exercício inteiro
    return max(0.0, posicao_fim - posicao_inicio)


def descricao_vigencia(status: object, vigencia_fim: object, exercicio: int, inicio: object = None) -> str | None:
    """Texto curto do que a vigência/status e o início da execução fazem com o contrato no
    `exercicio` (para a tela do Relatório de Reforço) — `None` quando nada limita (mesmo critério
    de `meses_vigentes_no_exercicio`)."""

    status_texto = _status_normalizado(status)
    if status_texto == STATUS_SUSPENSO:
        return "Suspenso"
    partes = []
    if inicio is not None and not pd.isna(inicio):
        data_inicio = pd.Timestamp(inicio)
        if data_inicio.year >= exercicio:
            partes.append(f"Início da execução em {data_inicio:%d/%m/%Y}")
    if vigencia_fim is None or pd.isna(vigencia_fim):
        if status_texto == STATUS_VENCIDO:
            partes.append("Vencido, sem data de vigência")
    else:
        fim = pd.Timestamp(vigencia_fim)
        if fim.year < exercicio:
            partes.append(f"Vigência encerrada em {fim:%d/%m/%Y}")
        elif fim.year == exercicio:
            partes.append(f"Vigência até {fim:%d/%m/%Y}")
    return " · ".join(partes) if partes else None


def necessidade_ate_dezembro(
    valor_mensal: pd.Series, valor_empenhado: pd.Series, meses_no_ano: pd.Series
) -> tuple[pd.Series, pd.Series]:
    """Necessidade de Empenho até Dezembro de cada programa/bolsa: o que falta EMPENHAR para cobrir os
    meses do exercício, `valor_mensal × meses restantes`, nunca negativa. Meses restantes =
    `meses_no_ano` (12 se não cadastrado) − `valor_empenhado ÷ valor_mensal` (0 se o valor mensal é 0;
    empenhado nulo conta como nada empenhado), nunca negativo. Devolve `(meses_restantes, necessidade)`.

    O saldo (empenhado − liquidado) NÃO entra nesta conta: ele já está dentro do empenhado, e subtraí-lo
    de novo descontava o mesmo valor duas vezes (correção de 05/10/2026 em Bolsas e Auxílios, igual à
    feita em Contratos Contínuos em 02/10/2026 — ver `src/relatorio_necessidade_empenho.py`). Não altera
    as entradas."""

    meses_ja_empenhados = (valor_empenhado / valor_mensal.replace(0.0, pd.NA)).fillna(0.0)
    meses_restantes = (meses_no_ano.fillna(12) - meses_ja_empenhados).clip(lower=0)
    necessidade = (valor_mensal * meses_restantes).clip(lower=0)
    return meses_restantes, necessidade
