"""Relatório de Necessidade de Empenho até o fim do exercício — Contratos Contínuos (PDF e Excel).

Camada: regra de relatório. Não lê planilha nem importa Streamlit; recebe o DataFrame de
contratos já enriquecido por `src.contratos_continuos.com_saldo_execucao` (o mesmo que alimenta o
"Resumo Consolidado" da página) e as colunas de meses liquidados por NE.

PEDIDO (01/10/2026): "implemente o mesmo modelo de exportação de relatórios que consta na
consulta de empenhos na aba de contratos contínuos [PDF e Excel], considerando a necessidade de
empenho até o fim do exercício". O relatório é a versão exportável do card "Necessidade de
Empenho por NE" da página — mesma regra, mesmas linhas, mesma ordem — e por isso a conta vive
aqui (`necessidade_por_ne`) e a página a CHAMA, em vez de duplicá-la: tela e arquivo não podem
divergir.

REGRA (já em uso na página, apenas movida para cá; nada foi acrescentado):
  * Uma linha por NE (itens de licitação da mesma NE são somados em `despesa_mensal`); contrato
    sem NE entra à parte, uma linha por item.
  * Saldo da NE: Empenhado − Liquidado por COMPETÊNCIA quando a NE tem competência apurada;
    senão `saldo_execucao` (Execução Mensal, por lançamento); senão o saldo colado na
    planilha; sem nenhum dos três, 0 (`base_saldo` registra qual fonte valeu — nunca mistura
    fontes dentro da mesma NE).
  * Meses já empenhados = Empenhado ÷ despesa mensal (0 se a despesa mensal é 0 ou nula).
  * Meses restantes = (`meses_no_ano`, 12 quando não cadastrado) − meses já empenhados, nunca
    negativo.
  * Necessidade até dezembro = despesa mensal × meses restantes, nunca negativa: o quanto falta
    EMPENHAR para cobrir os meses do exercício (custo do ano − já empenhado). CORREÇÃO
    (02/10/2026, "não foi intencional"): a regra anterior ainda subtraía o saldo (empenhado −
    liquidado) dessa conta, descontando-o duas vezes — ele já está dentro do empenhado. O saldo
    continua exibido (e abate a PROJEÇÃO mês a mês, que mede o gasto a partir do primeiro mês sem
    liquidação), mas não entra mais na necessidade do card.
  * VIGÊNCIA E STATUS NO CARD (pedido explícito, 02/10/2026 — o card deve concordar com o
    relatório): os "meses no ano" do contrato ficam limitados aos meses em que ele está vigente
    no exercício (`meses_vigentes_no_exercicio`: de janeiro até o fim da vigência do cadastro,
    mês final proporcional aos dias) — meses restantes = min(meses no ano, meses vigentes) −
    meses já empenhados. SUSPENSO sem data de suspensão e contrato cuja vigência acabou antes do
    exercício (ou VENCIDO sem data) ficam com 0 meses vigentes, logo sem necessidade; SUSPENSO com
    data de suspensão (06/10/2026) conta só até a véspera dela, como um fim de vigência; sem
    `vigencia_fim` e ATIVO nada muda. A data manda sobre o status, como na projeção do relatório. Só se aplica quando o
    exercício é informado (`necessidade_por_ne(..., exercicio)`).
  * INÍCIO DA EXECUÇÃO (pedido explícito, 02/10/2026): os meses anteriores ao início NÃO contam —
    meses vigentes = do início (data ou, se só o mês foi definido, o dia 1º dele) até o fim da
    vigência, o mês inicial e o final proporcionais aos dias. Vale só o início INFORMADO pelo
    usuário (campo "Início da execução (data)" ou o botão de mês); o mês detectado
    automaticamente pelo primeiro empenho NÃO corta nada (empenho tardio não prova que o contrato
    começou tarde) — NEs com início provável depois de janeiro e sem início definido são listadas
    nos avisos. A data manda sobre o mês.
  Esta regra é calendário-agnóstica (não usa a data de hoje): "até dezembro" é o total que
  falta para cobrir os meses ainda devidos do exercício. Ela NÃO é a sugestão "por calendário"
  do Relatório de Reforço (`necessidade_ate_mes_vigente`), que considera o mês vigente.

Valores: nulo ≠ zero. Contrato sem NE tem liquidado/saldo NULOS (exibidos "—"), não zero; NE sem
saldo em nenhuma fonte tem saldo 0 declarado em `base_saldo` ("Sem saldo (assumido 0)").

PROJEÇÃO MÊS A MÊS (pedidos explícitos posteriores, 01/10/2026: "o mesmo modelo [grade Jan–Dez da
Consulta de Empenhos] aproveitando a projeção de necessidade de empenho", "valor projetado
evidenciado mês a mês", despesa mensal fixa; e, depois de ver o primeiro PDF: dizer o saldo atual
do empenho, começar pelo primeiro mês sem liquidação, "em todos os meses apareçam dados", "subtrair
o saldo da necessidade mensal e colocar essa diferença no primeiro mês sem liquidação e partir
daí"):
uma linha por NE/item na grade Jan…Dez do exercício, onde TODO mês com dado mostra um valor:
  * Meses com Liquidação por Competência (qualquer registro do exercício, inclusive estorno ou
    zero — nada é descartado): valor REALIZADO (liquidado). Mês sem registro antes da projeção
    fica vazio ("—", nulo, não zero) — não há dado para inventar.
  * A projeção começa no PRIMEIRO MÊS SEM LIQUIDAÇÃO = mês seguinte ao último mês com registro
    de competência. NE sem nenhum registro de competência (ou base indisponível): começa no mês
    seguinte ao da extração da Execução Mensal (`mes_referencia_do_exercicio`), com aviso.
  * Meses PROJETADOS (sombreados): despesa mensal fixa por mês, abatido o saldo atual do empenho
    (`projetar_necessidade_mensal`) — o primeiro mês projeta (despesa mensal − saldo) e os
    seguintes a despesa mensal cheia; se o saldo for maior que a despesa mensal, o excesso é
    abatido nos meses seguintes (cada mês projeta só o que passa do saldo acumulado, nunca
    negativo). Saldo atual = o saldo do Resumo Consolidado (`saldo_para_necessidade`; item sem
    NE: nenhum saldo a abater).
  * Quantidade de meses projetados: do primeiro mês sem liquidação até dezembro, limitada pelos
    meses que o contrato é pago no exercício (`meses_no_ano`, 12 se não cadastrado) menos os meses
    já realizados — não projeta além da vida do contrato.
  * VIGÊNCIA E STATUS (pedido explícito, 02/10/2026 — "a priori, da data fim que deve mandar"):
    a projeção para no mês do FIM DA VIGÊNCIA do cadastro (`vigencia_fim`), e o mês final é
    PROPORCIONAL aos dias de vigência (fim em 15/11 → novembro projeta 15/30 da despesa mensal);
    nada é projetado depois do fim. Vigência já encerrada antes do primeiro mês a projetar: sem
    projeção. Status "SUSPENSO" sem data de suspensão não projeta nada, mesmo vigente, e manda
    sobre a data; com `data_suspensao` (06/10/2026) projeta até a véspera dela. Sem
    `vigencia_fim` informada, o status decide: "VENCIDO" não projeta; os demais projetam até
    dezembro (com aviso). Data e status que se contradizem (ATIVO com vigência encerrada,
    VENCIDO com vigência futura) seguem a DATA e são listados nos avisos. A coluna
    `observacao_projecao` de `mensal` registra o motivo em cada linha.
  Esta projeção NÃO reconcilia com a "Necessidade até Dezembro" do Resumo Consolidado, que conta
  os meses restantes pelo empenhado (empenhado ÷ despesa mensal), não pelo calendário; os dois
  valores aparecem no relatório (aba/coluna própria) e a diferença é avisada.

Contrato público:
    BASE_COMPETENCIA, BASE_LANCAMENTO, BASE_PLANILHA, BASE_SEM_SALDO, BASE_SEM_NE, MESES
    ContextoRelatorioNecessidade (dataclass)
    RelatorioNecessidade (dataclass: linhas, mensal, + totais)
    necessidade_por_ne(filtrado, meses_liquidados_por_ne, exercicio=None) -> (por_ne, sem_ne)
    meses_vigentes_no_exercicio(status, vigencia_fim, exercicio) -> float | None
    mes_referencia_do_exercicio(data_extracao, exercicio) -> int
    limite_de_projecao(status, vigencia_fim, exercicio) -> LimiteProjecao
    projetar_necessidade_mensal(despesa_mensal, saldo, primeiro_mes, qtd_meses, fracao_ultimo_mes=1.0)
        -> list[float] (12)
    montar_relatorio(por_ne, sem_ne, liquidacao_mensal, exercicio, mes_referencia) -> RelatorioNecessidade
    gerar_pdf(relatorio, contexto) -> bytes
    gerar_xlsx(relatorio, contexto) -> bytes
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, replace
from datetime import date, timedelta
from io import BytesIO
from xml.sax.saxutils import escape

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.contratos_aditivos import (
    aditivos_do_registro,
    custo_mensal,
    dia_de_referencia,
    meses_com_previsto,
    ROTULO_SITUACAO,
    ROTULO_TIPO,
    retroativo_por_aditivo,
    serie_valor_mensal,
    valor_vigente_em,
    vigencia_efetiva,
)
from src.necessidade_empenho import (  # noqa: F401  (reexportados: contrato público deste módulo)
    STATUS_ATIVO,
    STATUS_SUSPENSO,
    STATUS_VENCIDO,
    fim_ate_a_suspensao,
    meses_vigentes_no_exercicio,
)

TITULO = "NECESSIDADE DE EMPENHO ATÉ O FIM DO EXERCÍCIO — CONTRATOS CONTÍNUOS"

BASE_COMPETENCIA = "Competência"
BASE_LANCAMENTO = "Data de liquidação"
BASE_PLANILHA = "Saldo colado na planilha"
BASE_SEM_SALDO = "Sem saldo (assumido 0)"
BASE_SEM_NE = "Sem NE"

_COLUNAS_MESES_LIQUIDADOS = ["ne_curta", "meses_liquidados", "ultimo_mes_liquidado"]

MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
TIPO_REALIZADO = "Realizado"
TIPO_PROJETADO = "Projetado"
TIPO_PROJETADO_PREVISTO = "Projetado — aditivo previsto"

NOTA_REGRA = (
    "Necessidade = despesa mensal × meses restantes (nunca negativa) = o que falta empenhar. "
    "Meses restantes = meses no ano (12 quando não cadastrado) − empenhado ÷ despesa mensal (nunca "
    "negativo). Os meses no ano são limitados pelo período de execução (início informado e fim da "
    "vigência do cadastro, meses inicial e final proporcionais); o status SUSPENSO zera a "
    "necessidade a partir da data da suspensão (sem data, no exercício inteiro). O saldo não entra nesta conta (já está no empenhado). "
    "Saldo = Empenhado − Liquidado por competência quando a NE tem competência apurada; senão "
    "saldo da Execução Mensal (data de liquidação); senão saldo colado na planilha. Contrato sem "
    "NE: sem saldo a abater."
)


def _inicio_considerado(tabela: pd.DataFrame, exercicio: int | None) -> pd.Series:
    """Data de início da execução INFORMADA pelo usuário: `inicio_execucao_data` ou, na falta dela,
    o dia 1º do mês manual (`inicio_execucao_mes`, que precisa do `exercicio`). Nulo quando não
    informado — o mês detectado automaticamente não entra aqui."""

    inicios = []
    for data, mes in zip(tabela["inicio_execucao_data"], tabela["inicio_execucao_mes"]):
        if pd.notna(data):
            inicios.append(pd.Timestamp(data))
        elif exercicio is None:
            inicios.append(pd.NaT)  # o mês manual precisa do exercício para virar data
        elif pd.notna(mes):
            inicios.append(pd.Timestamp(year=exercicio, month=int(mes), day=1))
        else:
            inicios.append(pd.NaT)
    return pd.Series(inicios, index=tabela.index, dtype="datetime64[ns]")


def _meses_no_ano_efetivos(tabela: pd.DataFrame, exercicio: int | None) -> tuple[pd.Series, pd.Series]:
    """(`meses_no_ano` limitado pelo período de execução, `meses_vigentes`). Sem `exercicio`
    (chamador antigo) nada é limitado. `meses_vigentes` nulo = nada limita aquela linha."""

    base = tabela["meses_no_ano"].fillna(12).astype("float64")
    if exercicio is None:
        return base, pd.Series(float("nan"), index=tabela.index, dtype="float64")
    vigentes = pd.Series(
        [
            meses_vigentes_no_exercicio(status, vigencia_efetiva(fim, aditivos_do_registro(adit))[0], exercicio, inicio, suspensao)
            for status, fim, inicio, suspensao, adit in zip(
                tabela["status_contrato"], tabela["vigencia_fim"], tabela["inicio_execucao_considerado"],
                tabela["data_suspensao"], tabela["aditivos"],
            )
        ],
        index=tabela.index, dtype="float64",
    )
    return pd.concat([base, vigentes], axis=1).min(axis=1), vigentes


def _meses_cobertos(empenhado: float, serie: list[float]) -> float:
    """Meses (fração) que o `empenhado` cobre percorrendo a série mensal a partir de janeiro (depois de
    dezembro, pelo valor de dezembro). Valor mensal nulo ou ≤ 0 não cobre nada — o mesmo que dividir por
    zero/nulo e tratar como 0 na regra antiga. Com valor constante, é `empenhado ÷ valor`."""

    restante = 0.0 if pd.isna(empenhado) else float(empenhado)
    meses = 0.0
    for indice in range(12):
        valor = serie[indice]
        if pd.isna(valor) or valor <= 0:
            return meses
        if restante >= valor:
            restante -= valor
            meses += 1.0
        else:
            return meses + restante / valor
    final = serie[11]
    return meses if pd.isna(final) or final <= 0 else meses + restante / final


def _aplicar_necessidade(tabela: pd.DataFrame, exercicio: int | None) -> None:
    """Preenche `meses_ja_empenhados`, `meses_vigentes`, `meses_restantes`, `necessidade` e, com
    `exercicio`, `custo_exercicio`, `valor_mensal_vigente` e `inclui_previsto` (aditivos, 06/10/2026).
    Sem `exercicio` mantém a regra anterior (despesa mensal × meses restantes, sem vigência nem aditivos).

    Com `exercicio`: necessidade = max(0, custo do exercício − empenhado), em que o custo soma, mês a
    mês, o valor em vigor nos dias em execução (`custo_mensal`; a diferença retroativa dos reajustes
    entra sozinha). Custo ≤ 0 nunca gera necessidade (despesa negativa) e despesa nula continua nula.
    Empenhado nulo conta como nada empenhado. Com valor constante a conta é a de antes:
    `despesa × max(0, meses em execução − empenhado ÷ despesa)`."""

    empenhado = tabela["valor_empenhado_exibido"]
    if exercicio is None:
        tabela["meses_ja_empenhados"] = (empenhado / tabela["despesa_mensal"].replace(0.0, pd.NA)).fillna(0.0)
        meses_efetivos, tabela["meses_vigentes"] = _meses_no_ano_efetivos(tabela, exercicio)
        tabela["meses_restantes"] = (meses_efetivos - tabela["meses_ja_empenhados"]).clip(lower=0)
        tabela["necessidade"] = (tabela["despesa_mensal"] * tabela["meses_restantes"]).clip(lower=0)
        return

    aditivos = [aditivos_do_registro(valor) for valor in tabela["aditivos"]]
    custos, vigentes, previstos, ja_empenhados = [], [], [], []
    dia_ref = dia_de_referencia(exercicio)
    for posicao, adit in enumerate(aditivos):
        linha = tabela.iloc[posicao]
        custo = custo_mensal(
            linha["despesa_mensal"], adit, exercicio, status=linha["status_contrato"],
            vigencia_fim=linha["vigencia_fim"], inicio=linha["inicio_execucao_considerado"],
            data_suspensao=linha["data_suspensao"], meses_no_ano=linha["meses_no_ano"],
        )
        custos.append(float("nan") if any(pd.isna(v) for v in custo) else sum(custo))
        vigentes.append(valor_vigente_em(linha["despesa_mensal"], adit, dia_ref)[0])
        previstos.append(bool(meses_com_previsto(adit, exercicio, linha["vigencia_fim"])))
        ja_empenhados.append(_meses_cobertos(empenhado.iloc[posicao], serie_valor_mensal(linha["despesa_mensal"], adit, exercicio)))

    tabela["custo_exercicio"] = pd.Series(custos, index=tabela.index, dtype="float64")
    tabela["valor_mensal_vigente"] = pd.Series(vigentes, index=tabela.index, dtype="float64")
    tabela["inclui_previsto"] = pd.Series(previstos, index=tabela.index, dtype="bool")
    tabela["meses_ja_empenhados"] = pd.Series(ja_empenhados, index=tabela.index, dtype="float64")
    meses_efetivos, tabela["meses_vigentes"] = _meses_no_ano_efetivos(tabela, exercicio)
    tabela["meses_restantes"] = (meses_efetivos - tabela["meses_ja_empenhados"]).clip(lower=0)
    falta = (tabela["custo_exercicio"] - empenhado.fillna(0.0)).clip(lower=0)
    tabela["necessidade"] = falta.where(tabela["custo_exercicio"] > 0, 0.0).where(tabela["custo_exercicio"].notna())


def necessidade_por_ne(
    filtrado: pd.DataFrame, meses_liquidados_por_ne: pd.DataFrame | None, exercicio: int | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calcula a Necessidade de Empenho até Dezembro — a regra do card "Resumo Consolidado" da
    página de Contratos Contínuos (ver docstring do módulo). Devolve `(por_ne, sem_ne)`: uma
    linha por NE, e uma linha por item sem NE. Não altera `filtrado`.

    `filtrado` precisa de `ne_curta`, `fornecedor`, `contrato_numero`, `despesa_mensal`,
    `meses_no_ano`, `valor_empenhado`, `valor_empenhado_execucao`,
    `valor_empenhado_planilha_total_ne`, `valor_liquidado_execucao`, `liquidado_via_competencia`,
    `saldo_execucao`, `saldo_colado_planilha` (saída de `com_saldo_execucao`).
    `meses_liquidados_por_ne`: `ne_curta`, `meses_liquidados`, `ultimo_mes_liquidado` (ou
    `None`/vazio — toda NE fica sem esses dois campos). `exercicio`: quando informado, aplica a
    vigência (`vigencia_fim`) e o status SUSPENSO/VENCIDO aos meses no ano (ver docstring do
    módulo); `None` mantém a regra anterior, sem vigência."""

    if meses_liquidados_por_ne is None:
        meses_liquidados_por_ne = pd.DataFrame(columns=_COLUNAS_MESES_LIQUIDADOS)

    com_ne = filtrado.dropna(subset=["ne_curta"])
    sem_ne = filtrado[filtrado["ne_curta"].isna()].copy()

    # status e vigência (cadastro) só acompanham a NE para o relatório; ausentes na entrada
    # (chamadores antigos) ficam nulos — nunca inventados.
    colunas_cadastro = (
        "status_contrato", "vigencia_fim", "inicio_execucao_data", "inicio_execucao_mes", "inicio_execucao_efetivo",
        "data_suspensao", "aditivos",
    )
    extras = {coluna: (coluna, "first") for coluna in colunas_cadastro if coluna in filtrado.columns}
    por_ne = com_ne.groupby("ne_curta", sort=False).agg(
        **extras,
        qtd_linhas_na_ne=("ne_curta", "size"),
        fornecedor=("fornecedor", "first"),
        contrato_numero=("contrato_numero", "first"),
        despesa_mensal=("despesa_mensal", "sum"),
        meses_no_ano=("meses_no_ano", "first"),
        valor_empenhado_execucao=("valor_empenhado_execucao", "first"),
        valor_empenhado_planilha_total_ne=("valor_empenhado_planilha_total_ne", "first"),
        valor_liquidado_execucao=("valor_liquidado_execucao", "first"),
        liquidado_via_competencia=("liquidado_via_competencia", "first"),
        saldo_execucao=("saldo_execucao", "first"),
        saldo_colado_planilha=("saldo_colado_planilha", "first"),
    ).reset_index()
    for coluna in colunas_cadastro:
        for tabela in (por_ne, sem_ne):
            if coluna not in tabela.columns:
                tabela[coluna] = pd.NA
    for tabela in (por_ne, sem_ne):
        tabela["inicio_execucao_considerado"] = _inicio_considerado(tabela, exercicio)
    por_ne = por_ne.merge(meses_liquidados_por_ne, on="ne_curta", how="left")
    por_ne["valor_empenhado_exibido"] = por_ne["valor_empenhado_execucao"].fillna(
        por_ne["valor_empenhado_planilha_total_ne"]
    )

    usa_competencia = por_ne["liquidado_via_competencia"].fillna(False) & por_ne["valor_liquidado_execucao"].notna()
    saldo_competencia = por_ne["valor_empenhado_exibido"] - por_ne["valor_liquidado_execucao"]
    saldo_lancamento_fallback = por_ne["saldo_execucao"].fillna(por_ne["saldo_colado_planilha"]).fillna(0.0)
    por_ne["saldo_para_necessidade"] = saldo_competencia.where(usa_competencia, saldo_lancamento_fallback)
    por_ne["base_saldo"] = BASE_SEM_SALDO
    por_ne.loc[por_ne["saldo_colado_planilha"].notna(), "base_saldo"] = BASE_PLANILHA
    por_ne.loc[por_ne["saldo_execucao"].notna(), "base_saldo"] = BASE_LANCAMENTO
    por_ne.loc[usa_competencia, "base_saldo"] = BASE_COMPETENCIA

    # o saldo (empenhado − liquidado) já está dentro do empenhado: não é subtraído de novo aqui
    # (correção de 02/10/2026, ver docstring do módulo)
    _aplicar_necessidade(por_ne, exercicio)

    sem_ne["valor_empenhado_exibido"] = sem_ne["valor_empenhado"]
    _aplicar_necessidade(sem_ne, exercicio)
    sem_ne["base_saldo"] = BASE_SEM_NE

    return por_ne, sem_ne


def mes_referencia_do_exercicio(data_extracao: date, exercicio: int) -> int:
    """Último mês (1-12) do `exercicio` já coberto pela extração da Execução Mensal — o mês da
    extração, inclusive (pode estar parcial; o relatório avisa a data). Extração em ano anterior
    ao exercício: 0; em ano posterior: 12 (exercício encerrado). Usado só para NE sem nenhum
    registro de competência (ver docstring do módulo)."""

    if data_extracao.year > exercicio:
        return 12
    if data_extracao.year < exercicio:
        return 0
    return data_extracao.month




@dataclass(frozen=True)
class LimiteProjecao:
    """Até onde a vigência/status do contrato permite projetar (ver `limite_de_projecao`).

    `ultimo_mes`: último mês (1-12) projetável; 0 = nada a projetar. `fracao_ultimo_mes`: parte
    (0-1] da despesa mensal no último mês — 1.0 salvo quando a vigência termina no meio do mês.
    `mes_do_fim`: o mês (1-12) do fim da vigência quando ele limita a projeção (a fração só vale
    se o último mês projetado for esse), senão `None`. `motivo`: texto para a coluna
    `observacao_projecao`; `aviso`: categoria para a lista de avisos (ou `None`)."""

    ultimo_mes: int
    fracao_ultimo_mes: float
    mes_do_fim: int | None
    motivo: str
    aviso: str | None = None
    #: primeiro mês projetável (1 salvo início da execução informado dentro do exercício), a
    #: fração (0-1] da despesa mensal nesse mês e o mês do início quando ele limita (a fração só
    #: vale se o primeiro mês projetado for esse).
    primeiro_mes_permitido: int = 1
    fracao_primeiro_mes: float = 1.0
    mes_do_inicio: int | None = None


def limite_de_projecao(
    status: object, vigencia_fim: object, exercicio: int, inicio: object = None, data_suspensao: object = None,
) -> LimiteProjecao:
    """Regra de vigência/status e início da execução da projeção: `_limite_por_status_e_fim` (abaixo)
    + o início informado, que impede a projeção antes dele (primeiro mês proporcional aos dias) —
    início em ano posterior ao exercício: nada a projetar; em ano anterior: não limita."""

    base = _limite_por_status_e_fim(status, vigencia_fim, exercicio, data_suspensao)
    if inicio is None or pd.isna(inicio) or base.ultimo_mes == 0:
        return base
    data_inicio = pd.Timestamp(inicio)
    texto = data_inicio.strftime("%d/%m/%Y")
    if data_inicio.year > exercicio:
        return replace(base, ultimo_mes=0, motivo=f"Início da execução em {texto} — sem projeção no exercício")
    if data_inicio.year < exercicio:
        return base
    dias_do_mes = calendar.monthrange(data_inicio.year, data_inicio.month)[1]
    dias_no_mes = dias_do_mes - data_inicio.day + 1
    proporcional = "" if dias_no_mes == dias_do_mes else f" (mês inicial proporcional: {dias_no_mes}/{dias_do_mes} dias)"
    return replace(
        base,
        primeiro_mes_permitido=data_inicio.month,
        fracao_primeiro_mes=dias_no_mes / dias_do_mes,
        mes_do_inicio=data_inicio.month,
        motivo=f"{base.motivo} · início da execução em {texto}{proporcional}",
    )


def _limite_por_status_e_fim(
    status: object, vigencia_fim: object, exercicio: int, data_suspensao: object = None,
) -> LimiteProjecao:
    """Regra de vigência/status da projeção (docstring do módulo): SUSPENSO sem data de suspensão não
    projeta; SUSPENSO com data projeta até a véspera da suspensão, como um fim de vigência
    (`fim_ate_a_suspensao`, 06/10/2026); com `vigencia_fim` a DATA manda (até o mês do fim, o último
    proporcional aos dias; encerrada antes do exercício, nada); sem data, VENCIDO não projeta e os
    demais projetam até dezembro. Avisos: `suspenso`, `vigencia_encerrada` (data passada),
    `vencido_sem_data`, `sem_data`, `vencido_com_vigencia` (status VENCIDO com vigência que ainda
    alcança o exercício), `ativo_com_vigencia_encerrada` (status diferente de VENCIDO com vigência
    encerrada)."""

    status_texto = None if status is None or pd.isna(status) else str(status).strip().upper()
    if status_texto == STATUS_SUSPENSO:
        if data_suspensao is None or pd.isna(data_suspensao):
            return LimiteProjecao(0, 1.0, None, "Suspenso — sem projeção", "suspenso")
        fim = fim_ate_a_suspensao(vigencia_fim, data_suspensao)
        base = _limite_por_status_e_fim(None, fim, exercicio)
        texto = f"Suspenso em {pd.Timestamp(data_suspensao):%d/%m/%Y}"
        if fim.year < exercicio:
            return replace(base, motivo=f"{texto} — sem projeção", aviso="suspenso")
        return replace(base, motivo=f"{texto} — {base.motivo}", aviso="suspenso")

    tem_data = vigencia_fim is not None and not pd.isna(vigencia_fim)
    if not tem_data:
        if status_texto == STATUS_VENCIDO:
            return LimiteProjecao(0, 1.0, None, "Vencido, sem data de vigência — sem projeção", "vencido_sem_data")
        return LimiteProjecao(12, 1.0, None, "Sem data de vigência — projetado até dezembro", "sem_data")

    fim = pd.Timestamp(vigencia_fim)
    texto_fim = fim.strftime("%d/%m/%Y")
    if fim.year < exercicio:
        aviso = "ativo_com_vigencia_encerrada" if status_texto != STATUS_VENCIDO else None
        return LimiteProjecao(0, 1.0, None, f"Vigência encerrada em {texto_fim} — sem projeção", aviso)
    if fim.year > exercicio:
        aviso = "vencido_com_vigencia" if status_texto == STATUS_VENCIDO else None
        return LimiteProjecao(12, 1.0, None, f"Vigência até {texto_fim} — projetado até dezembro", aviso)

    dias_do_mes = calendar.monthrange(fim.year, fim.month)[1]
    fracao = fim.day / dias_do_mes
    proporcional = "" if fracao >= 1.0 else f" (mês final proporcional: {fim.day}/{dias_do_mes} dias)"
    aviso = "vencido_com_vigencia" if status_texto == STATUS_VENCIDO else None
    return LimiteProjecao(fim.month, fracao, fim.month, f"Vigência até {texto_fim}{proporcional}", aviso)


def projetar_necessidade_mensal(
    despesa_mensal: float, saldo: float, primeiro_mes: int, qtd_meses: int, fracao_ultimo_mes: float = 1.0,
    fracao_primeiro_mes: float = 1.0, custos: list[float] | None = None,
) -> list[float]:
    """Necessidade de empenho projetada por mês (lista de 12; NaN fora dos `qtd_meses` meses a
    partir de `primeiro_mes`, 1-based).

    Despesa mensal fixa abatida do saldo atual: o gasto acumulado cresce uma `despesa_mensal` por
    mês e cada mês projeta o quanto esse acumulado passa a exceder `saldo` — o primeiro mês
    projeta `despesa_mensal − saldo` (a regra pedida pelo usuário) e os seguintes a despesa mensal
    cheia; saldo maior que a despesa mensal é abatido ao longo dos meses (mês coberto projeta
    0,00, nunca negativo); saldo negativo cai todo no primeiro mês. O ÚLTIMO mês projetado gasta
    só `fracao_ultimo_mes` da despesa mensal (vigência que termina no meio do mês) e o PRIMEIRO só
    `fracao_primeiro_mes` (execução que começa no meio do mês); com um único mês projetado, as duas
    frações se combinam. Entrada nula (despesa mensal ou saldo) devolve tudo NaN — não vira zero.

    `custos` (aditivos, 06/10/2026): custo de cada mês (12 valores, de `custo_mensal`) no lugar de
    `despesa_mensal × fração` — o valor em vigor naquele mês, com as frações de início/fim de execução
    já embutidas (`fracao_*` são ignoradas). Custo nulo no mês interrompe a projeção (restante NaN);
    sem `custos` nada muda."""

    mensal = [float("nan")] * 12
    if pd.isna(saldo) or (custos is None and pd.isna(despesa_mensal)):
        return mensal
    acumulado = 0.0
    excesso_anterior = 0.0
    primeiro = max(primeiro_mes, 1)
    ultimo_mes = min(primeiro_mes + qtd_meses - 1, 12)
    for mes in range(primeiro, ultimo_mes + 1):
        if primeiro == ultimo_mes:
            fracao = max(0.0, fracao_ultimo_mes - (1.0 - fracao_primeiro_mes))
        elif mes == primeiro:
            fracao = fracao_primeiro_mes
        elif mes == ultimo_mes:
            fracao = fracao_ultimo_mes
        else:
            fracao = 1.0
        if custos is not None:
            if pd.isna(custos[mes - 1]):
                break
            acumulado += custos[mes - 1]
        else:
            acumulado += despesa_mensal * fracao
        excesso = max(0.0, acumulado - saldo)
        mensal[mes - 1] = excesso - excesso_anterior
        excesso_anterior = excesso
    return mensal


@dataclass(frozen=True)
class ContextoRelatorioNecessidade:
    """Procedência impressa no cabeçalho do PDF e na aba "Parâmetros" do Excel."""

    exercicio: int
    data_extracao: str
    hash_manifesto: str
    data_emissao: str
    #: descrição da base de competência usada (arquivo + data de modificação), ou `None` quando
    #: indisponível (toda NE então usa o saldo por lançamento).
    origem_competencia: str | None
    #: texto digitado no campo "Buscar" da página (o relatório respeita o mesmo recorte do
    #: Resumo Consolidado), ou vazio.
    busca: str = ""


_COLUNAS_REALIZADO = [f"r{mes}" for mes in range(1, 13)]
_COLUNAS_PROJETADO = [f"p{mes}" for mes in range(1, 13)]


@dataclass(frozen=True)
class RelatorioNecessidade:
    #: uma linha por NE e uma por item sem NE, na ordem do Resumo Consolidado (necessidade
    #: decrescente, NEs primeiro). Colunas: ne_curta, fornecedor, contrato_numero,
    #: valor_empenhado, valor_liquidado, saldo, despesa_mensal, meses_no_ano, meses_ja_empenhados,
    #: meses_restantes, necessidade, base_saldo, meses_liquidados, ultimo_mes_liquidado.
    #: `necessidade` é a do Resumo Consolidado (meses restantes pelo empenhado).
    linhas: pd.DataFrame
    #: mesmo índice de `linhas`: r1..r12 (realizado — liquidado por competência), p1..p12
    #: (projetado — necessidade de empenho prevista; mutuamente exclusivos com r no mesmo mês),
    #: `primeiro_mes_projecao` (1-12, nulo se nada a projetar), `meses_projetados`,
    #: `observacao_projecao` (motivo/limite pela vigência e status) e `aviso_vigencia` (categoria
    #: de `limite_de_projecao`, nulo quando não há o que avisar).
    mensal: pd.DataFrame
    exercicio: int
    #: último mês coberto pela extração (0 a 12) — ver `mes_referencia_do_exercicio`.
    mes_referencia: int

    @property
    def total_necessidade(self) -> float:
        """Necessidade até Dezembro do Resumo Consolidado (não a projetada da grade)."""

        return float(self.linhas["necessidade"].sum())

    @property
    def total_projetado(self) -> float:
        """Soma da necessidade projetada na grade (todos os meses projetados de todas as linhas)."""

        return float(self.mensal[_COLUNAS_PROJETADO].sum().sum())

    def projetado_da_linha(self, indice: int) -> float | None:
        """Necessidade projetada da linha (soma dos meses projetados); nulo se nada projetado."""

        total = self.mensal.loc[indice, _COLUNAS_PROJETADO].sum(min_count=1)
        return None if pd.isna(total) else float(total)

    def realizado_da_linha(self, indice: int) -> float | None:
        total = self.mensal.loc[indice, _COLUNAS_REALIZADO].sum(min_count=1)
        return None if pd.isna(total) else float(total)

    @property
    def total_empenhado(self) -> float | None:
        total = self.linhas["valor_empenhado"].sum(min_count=1)
        return None if pd.isna(total) else float(total)

    @property
    def total_saldo(self) -> float | None:
        total = self.linhas["saldo"].sum(min_count=1)
        return None if pd.isna(total) else float(total)

    @property
    def total_mensal_realizado(self) -> list[float | None]:
        """Soma por mês (Jan…Dez) de todas as linhas; mês sem nenhum valor fica nulo."""

        return [None if pd.isna(v) else float(v) for v in self.mensal[_COLUNAS_REALIZADO].sum(min_count=1)]

    @property
    def total_mensal_projetado(self) -> list[float | None]:
        return [None if pd.isna(v) else float(v) for v in self.mensal[_COLUNAS_PROJETADO].sum(min_count=1)]

    @property
    def qtd_sem_ne(self) -> int:
        return int((self.linhas["base_saldo"] == BASE_SEM_NE).sum())

    @property
    def qtd_ne(self) -> int:
        return len(self.linhas) - self.qtd_sem_ne

    @property
    def nes_sem_realizado(self) -> list[str]:
        """NEs sem nenhum registro de competência no exercício (a projeção começa no mês
        seguinte ao da extração e os meses anteriores ficam "—")."""

        vazio = self.mensal[_COLUNAS_REALIZADO].isna().all(axis=1) & self.linhas["ne_curta"].notna()
        return self.linhas.loc[vazio, "ne_curta"].tolist()

    def tipo_do_mes(self, indice: int, mes: int) -> str | None:
        """Tipo do mês (1-12) da linha: "Realizado", "Projetado", "Projetado — aditivo previsto" (valor
        estimado por aditivo ainda não assinado) ou `None` quando não há dado."""

        valor, projetado = self.valor_do_mes(indice, mes)
        if valor is None:
            return None
        if not projetado:
            return TIPO_REALIZADO
        previstos = str(self.mensal.at[indice, "meses_previstos"])
        if str(mes) in previstos.split(","):
            return TIPO_PROJETADO_PREVISTO
        return TIPO_PROJETADO

    def valor_do_mes(self, indice: int, mes: int) -> tuple[float | None, bool]:
        """(valor, projetado) do mês (1-12) da linha: o realizado se houver, senão o projetado;
        `(None, False)` quando não há dado."""

        realizado = self.mensal.at[indice, f"r{mes}"]
        if not pd.isna(realizado):
            return float(realizado), False
        projetado = self.mensal.at[indice, f"p{mes}"]
        if not pd.isna(projetado):
            return float(projetado), True
        return None, False


def montar_relatorio(
    por_ne: pd.DataFrame,
    sem_ne: pd.DataFrame,
    liquidacao_mensal: pd.DataFrame | None,
    exercicio: int,
    mes_referencia: int,
) -> RelatorioNecessidade:
    """Junta as duas saídas de `necessidade_por_ne` na ordem da tela (necessidade decrescente
    dentro de cada grupo, NEs antes dos itens sem NE) e monta a grade mensal (ver docstring do
    módulo). `liquidacao_mensal`: `ne_curta`, `ano_mes` (AAAAMM), `valor` — Liquidação por
    Competência (`liquidacao_competencia.liquidado_por_ne_e_mes`), ou `None` quando a base está
    indisponível (nenhum realizado). Todo registro do `exercicio` entra como realizado. Não
    altera as entradas."""

    colunas = [
        "ne_curta", "fornecedor", "contrato_numero", "valor_empenhado", "valor_liquidado", "saldo",
        "despesa_mensal", "meses_no_ano", "meses_ja_empenhados", "meses_restantes", "necessidade",
        "base_saldo", "meses_liquidados", "ultimo_mes_liquidado", "status_contrato", "vigencia_fim",
        "meses_vigentes", "inicio_execucao_considerado", "inicio_execucao_efetivo", "inicio_execucao_mes",
        "data_suspensao", "aditivos", "custo_exercicio", "valor_mensal_vigente", "inclui_previsto",
        "qtd_linhas_na_ne",
    ]
    com_ne = por_ne.sort_values("necessidade", ascending=False).rename(
        columns={
            "valor_empenhado_exibido": "valor_empenhado",
            "saldo_para_necessidade": "saldo",
        }
    )
    # Liquidado exibido = `valor_liquidado_execucao` de `com_saldo_execucao` (competência quando
    # a base está disponível, senão lançamento); nulo quando a NE não tem liquidado apurado —
    # nunca derivado nem convertido em zero. `base_saldo` diz de onde veio o saldo.
    com_ne = com_ne.assign(valor_liquidado=com_ne["valor_liquidado_execucao"])
    # `valor_empenhado_exibido` do item sem NE é o próprio `valor_empenhado` (ver
    # `necessidade_por_ne`); descarta o original para o rename não duplicar a coluna.
    itens_sem_ne = (
        sem_ne.drop(columns="valor_empenhado")
        .sort_values("necessidade", ascending=False)
        .rename(columns={"valor_empenhado_exibido": "valor_empenhado"})
    )
    itens_sem_ne = itens_sem_ne.assign(
        saldo=pd.NA, valor_liquidado=pd.NA, meses_liquidados=pd.NA, ultimo_mes_liquidado=pd.NaT,
    )
    linhas = pd.concat(
        [com_ne.reindex(columns=colunas), itens_sem_ne.reindex(columns=colunas)], ignore_index=True
    )
    linhas["meses_no_ano"] = linhas["meses_no_ano"].fillna(12).astype("float64")
    for coluna in ("valor_empenhado", "valor_liquidado", "saldo", "despesa_mensal",
                   "meses_ja_empenhados", "meses_restantes", "necessidade", "meses_liquidados", "meses_vigentes"):
        linhas[coluna] = pd.to_numeric(linhas[coluna], errors="coerce").astype("float64")
    linhas["ultimo_mes_liquidado"] = pd.to_datetime(linhas["ultimo_mes_liquidado"], errors="coerce")
    linhas["vigencia_fim"] = pd.to_datetime(linhas["vigencia_fim"], errors="coerce")
    linhas["data_suspensao"] = pd.to_datetime(linhas["data_suspensao"], errors="coerce")
    linhas["inicio_execucao_considerado"] = pd.to_datetime(linhas["inicio_execucao_considerado"], errors="coerce")
    linhas["status_contrato"] = linhas["status_contrato"].astype("object").where(linhas["status_contrato"].notna(), None)

    # ---- realizado: todo registro de Liquidação por Competência do exercício
    realizado = pd.DataFrame(float("nan"), index=linhas.index, columns=_COLUNAS_REALIZADO)
    if liquidacao_mensal is not None and not liquidacao_mensal.empty:
        ano_mes = liquidacao_mensal["ano_mes"].astype("int64")
        serie = liquidacao_mensal.assign(ano=ano_mes // 100, mes=ano_mes % 100)
        serie = serie[(serie["ano"] == exercicio) & serie["mes"].between(1, 12)]
        por_ne_mes = serie.groupby(["ne_curta", "mes"])["valor"].sum(min_count=1)
        for indice, ne in linhas["ne_curta"].items():
            if pd.isna(ne):
                continue
            for mes in range(1, 13):
                valor = por_ne_mes.get((ne, mes))
                if valor is not None and not pd.isna(valor):
                    realizado.at[indice, f"r{mes}"] = float(valor)

    # ---- projetado: do primeiro mês sem liquidação até dezembro (despesa mensal − saldo atual)
    projetado = pd.DataFrame(float("nan"), index=linhas.index, columns=_COLUNAS_PROJETADO)
    primeiro_mes = pd.Series(pd.NA, index=linhas.index, dtype="Int64", name="primeiro_mes_projecao")
    meses_projetados = pd.Series(0, index=linhas.index, dtype="Int64", name="meses_projetados")
    observacao = pd.Series("", index=linhas.index, dtype="object", name="observacao_projecao")
    aviso_vigencia = pd.Series(None, index=linhas.index, dtype="object", name="aviso_vigencia")
    retroativo = pd.Series(0.0, index=linhas.index, dtype="float64", name="retroativo")
    meses_previstos = pd.Series("", index=linhas.index, dtype="object", name="meses_previstos")
    retroativo_termos = pd.Series("", index=linhas.index, dtype="object", name="retroativo_termos")
    for indice, linha in linhas.iterrows():
        adit = aditivos_do_registro(linha["aditivos"])
        vigencia_ef = vigencia_efetiva(linha["vigencia_fim"], adit)[0]
        meses_com_registro = [m for m in range(1, 13) if not pd.isna(realizado.at[indice, f"r{m}"])]
        inicio = (max(meses_com_registro) + 1) if meses_com_registro else mes_referencia + 1
        inicio = max(inicio, 1)
        ate_dezembro = max(0, 12 - inicio + 1)
        # não projeta além da vida do contrato: meses pagos no exercício − meses já realizados
        vida = max(0, math.floor(linha["meses_no_ano"] - len(meses_com_registro) + 1e-9))
        # vigência/status: até onde o contrato permite projetar (a data manda; SUSPENSO não projeta)
        limite = limite_de_projecao(
            linha["status_contrato"], vigencia_ef, exercicio, linha["inicio_execucao_considerado"],
            linha["data_suspensao"],
        )
        inicio = max(inicio, limite.primeiro_mes_permitido)  # início da execução informado: nada antes dele
        ate_dezembro = max(0, 12 - inicio + 1)
        ate_limite = max(0, limite.ultimo_mes - inicio + 1)
        qtd = min(ate_dezembro, vida, ate_limite)
        if mes_referencia >= 12:  # exercício encerrado (extração de dezembro em diante): nada a projetar
            qtd = 0
        ultimo_projetado = inicio + qtd - 1
        # mês final proporcional só quando é justamente o mês do fim da vigência que fecha a projeção
        fracao = limite.fracao_ultimo_mes if limite.mes_do_fim is not None and ultimo_projetado == limite.mes_do_fim else 1.0
        fracao_inicial = limite.fracao_primeiro_mes if limite.mes_do_inicio is not None and inicio == limite.mes_do_inicio else 1.0
        saldo = 0.0 if linha["base_saldo"] == BASE_SEM_NE else linha["saldo"]
        custos = custo_mensal(
            linha["despesa_mensal"], adit, exercicio, status=linha["status_contrato"],
            vigencia_fim=linha["vigencia_fim"], inicio=linha["inicio_execucao_considerado"],
            data_suspensao=linha["data_suspensao"],
        )
        # retroativo dos reajustes assinados depois do início de vigência (só nos meses já realizados): é custo
        # do primeiro mês projetado — abatido pelo saldo como qualquer outro (revisão final, 06/10/2026) — e
        # fica também em coluna própria (spec §4.3)
        realizados = {m for m in range(1, 13) if not pd.isna(realizado.at[indice, f"r{m}"])}
        retros = retroativo_por_aditivo(linha["despesa_mensal"], adit, exercicio, realizados)
        total_retroativo = sum(v for _, v in retros)
        aplica_retroativo = bool(total_retroativo) and qtd > 0 and inicio <= 12 and not pd.isna(custos[inicio - 1])
        if aplica_retroativo:
            custos = [valor + total_retroativo if mes == inicio else valor for mes, valor in enumerate(custos, start=1)]
        projetado.loc[indice] = projetar_necessidade_mensal(
            linha["despesa_mensal"], saldo, inicio, qtd, fracao, fracao_inicial, custos=custos
        )
        meses_previstos.at[indice] = ",".join(
            str(m) for m in sorted(meses_com_previsto(adit, exercicio, linha["vigencia_fim"]))
        )
        if qtd > 0 and not projetado.loc[indice].isna().all():
            primeiro_mes.at[indice] = inicio
            meses_projetados.at[indice] = qtd
            if aplica_retroativo:
                retroativo.at[indice] = total_retroativo
                retroativo_termos.at[indice] = ", ".join(a.numero for a, v in retros if v)
        motivo, aviso = limite.motivo, limite.aviso
        if limite.mes_do_fim is not None and ate_limite == 0 and limite.aviso == "suspenso":
            # suspenso com data: a suspensão chega antes do primeiro mês sem liquidação
            motivo = f"Suspenso em {pd.Timestamp(linha['data_suspensao']).strftime('%d/%m/%Y')} — sem projeção"
        elif limite.mes_do_fim is not None and ate_limite == 0:
            # a vigência acaba antes do primeiro mês sem liquidação: nada a projetar
            motivo = f"Vigência encerrada em {pd.Timestamp(vigencia_ef).strftime('%d/%m/%Y')} — sem projeção"
            aviso = None if str(linha["status_contrato"]).strip().upper() == STATUS_VENCIDO else "ativo_com_vigencia_encerrada"
        observacao.at[indice] = motivo
        aviso_vigencia.at[indice] = aviso

    linhas["retroativo"] = retroativo
    linhas["inclui_previsto"] = linhas["inclui_previsto"].fillna(False).astype(bool)
    mensal = pd.concat(
        [realizado, projetado, primeiro_mes, meses_projetados, observacao, aviso_vigencia, retroativo, meses_previstos, retroativo_termos],
        axis=1,
    )
    return RelatorioNecessidade(
        linhas=linhas, mensal=mensal, exercicio=exercicio, mes_referencia=mes_referencia
    )


# ------------------------------------------------------------------------------ comum
def _formatar_brl(valor: object) -> str:
    """Pontuação pt-BR com centavos; nulo vira "—" (distinto de "0,00")."""

    if valor is None or pd.isna(valor):
        return "—"
    return f"{float(valor):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _formatar_meses(valor: object) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    return f"{float(valor):.2f}".replace(".", ",")


def _texto_ou_traco(valor: object) -> str:
    return "—" if valor is None or pd.isna(valor) else str(valor)


def _texto(valor: object) -> str | None:
    return None if valor is None or pd.isna(valor) else str(valor)


def _mes_ano(valor: object) -> str:
    return "—" if valor is None or pd.isna(valor) else pd.Timestamp(valor).strftime("%m/%Y")


def _mes_ano_dia(valor: object) -> str:
    return "—" if valor is None or pd.isna(valor) else pd.Timestamp(valor).strftime("%d/%m/%Y")


def _nome_mes(mes: object) -> str | None:
    return None if mes is None or pd.isna(mes) else MESES[int(mes) - 1]


def _mes_referencia_texto(relatorio: RelatorioNecessidade, contexto: ContextoRelatorioNecessidade) -> str:
    ref = relatorio.mes_referencia
    if ref <= 0:
        return f"nenhum mês de {relatorio.exercicio} coberto pela extração de {contexto.data_extracao}"
    if ref >= 12:
        return f"{relatorio.exercicio} encerrado (extração de {contexto.data_extracao})"
    return f"{MESES[ref - 1]}/{relatorio.exercicio} (extração de {contexto.data_extracao}; o mês pode estar parcial)"


def _avisos(relatorio: RelatorioNecessidade, contexto: ContextoRelatorioNecessidade) -> list[str]:
    avisos = []
    if contexto.origem_competencia is None:
        avisos.append(
            "A base de Liquidação por Competência não está disponível: não há Realizado em nenhuma "
            "NE (a projeção começa no mês seguinte ao da extração) e o saldo vem da Execução "
            "Mensal (data de liquidação), não da competência."
        )
    else:
        sem_realizado = relatorio.nes_sem_realizado
        if sem_realizado:
            avisos.append(
                f"NEs sem nenhuma liquidação por competência em {relatorio.exercicio} (meses anteriores "
                "ficam em '—', não zero; a projeção começa no mês seguinte ao da extração): "
                + ", ".join(sem_realizado) + "."
            )
    por_base = relatorio.linhas.groupby("base_saldo")["contrato_numero"].count()
    sem_ne = int(por_base.get(BASE_SEM_NE, 0))
    if sem_ne:
        avisos.append(
            f"{sem_ne} item(ns) de contrato sem NE: projeção sem saldo a abater (despesa mensal cheia "
            "desde o mês seguinte ao da extração); Realizado, liquidado e saldo ficam em branco (—)."
        )
    sem_saldo = relatorio.linhas.loc[relatorio.linhas["base_saldo"] == BASE_SEM_SALDO, "ne_curta"].tolist()
    if sem_saldo:
        avisos.append(
            "NEs sem saldo em nenhuma fonte (saldo assumido em 0, a projeção pode estar "
            "superestimada): " + ", ".join(sem_saldo) + "."
        )
    planilha = relatorio.linhas.loc[relatorio.linhas["base_saldo"] == BASE_PLANILHA, "ne_curta"].tolist()
    if planilha:
        avisos.append(
            "NEs sem saldo na Execução Mensal — usado o saldo colado na planilha (reserva): "
            + ", ".join(planilha) + "."
        )
    rotulo = lambda i: _texto_ou_traco(relatorio.linhas.at[i, "ne_curta"]) + (  # noqa: E731
        f" (contrato {relatorio.linhas.at[i, 'contrato_numero']})" if pd.notna(relatorio.linhas.at[i, "contrato_numero"]) else ""
    )
    por_categoria = {
        categoria: [rotulo(i) for i in relatorio.mensal.index[relatorio.mensal["aviso_vigencia"] == categoria]]
        for categoria in (
            "suspenso", "ativo_com_vigencia_encerrada", "vencido_com_vigencia", "vencido_sem_data", "sem_data",
        )
    }
    if por_categoria["suspenso"]:
        avisos.append(
            "Contratos SUSPENSOS — sem projeção a partir da data da suspensão (sem data informada, nenhuma "
            "projeção no exercício), mesmo vigentes: " + "; ".join(por_categoria["suspenso"]) + "."
        )
    if por_categoria["ativo_com_vigencia_encerrada"]:
        avisos.append(
            "Status diferente de VENCIDO, mas a data de vigência já encerrou — a data manda, sem projeção "
            "(se o contrato foi prorrogado, atualize a vigência no cadastro): "
            + "; ".join(por_categoria["ativo_com_vigencia_encerrada"]) + "."
        )
    if por_categoria["vencido_com_vigencia"]:
        avisos.append(
            "Status VENCIDO, mas a data de vigência ainda alcança o exercício — a data manda e a projeção "
            "vai até o fim dela (confira o status): " + "; ".join(por_categoria["vencido_com_vigencia"]) + "."
        )
    if por_categoria["vencido_sem_data"]:
        avisos.append(
            "Contratos VENCIDOS sem data de vigência — sem projeção: " + "; ".join(por_categoria["vencido_sem_data"]) + "."
        )
    if por_categoria["sem_data"]:
        avisos.append(
            "Contratos sem data de vigência no cadastro — projetados até dezembro: "
            + "; ".join(por_categoria["sem_data"]) + "."
        )
    primeiro_empenho = pd.to_numeric(relatorio.linhas["inicio_execucao_efetivo"], errors="coerce")
    sem_inicio = (
        relatorio.linhas["inicio_execucao_considerado"].isna() & primeiro_empenho.gt(1) & relatorio.linhas["ne_curta"].notna()
    )
    if sem_inicio.any():
        itens = [
            f"{relatorio.linhas.at[i, 'ne_curta']} (1º empenho em {MESES[int(primeiro_empenho.at[i]) - 1]})"
            for i in relatorio.linhas.index[sem_inicio]
        ]
        avisos.append(
            "NEs cujo primeiro empenho foi depois de janeiro e sem início da execução definido — a necessidade "
            "conta desde janeiro; se o contrato começou depois, defina o início da execução no card (data ou "
            "mês): " + "; ".join(itens) + "."
        )
    if abs(relatorio.total_projetado - relatorio.total_necessidade) > 0.005:
        avisos.append(
            f"A necessidade projetada na grade (R$ {_formatar_brl(relatorio.total_projetado)}) difere da "
            f"Necessidade até Dezembro do Resumo Consolidado (R$ {_formatar_brl(relatorio.total_necessidade)}): "
            "a grade projeta do primeiro mês sem liquidação até dezembro, pelo calendário; o Resumo "
            "conta os meses restantes pelo empenhado (empenhado ÷ despesa mensal). Os dois estão no "
            "Resumo por NE."
        )
    avisos += _avisos_de_aditivos(relatorio, rotulo)
    return avisos


def _avisos_de_aditivos(relatorio: RelatorioNecessidade, rotulo) -> list[str]:
    """Avisos dos aditivos (06/10/2026): renovação não cadastrada, aditivos previstos e valor negativo."""

    sem_renovacao, previstos, negativos, compartilhadas = [], [], [], []
    ultimo_dia = pd.Timestamp(year=relatorio.exercicio, month=12, day=31)
    for indice, linha in relatorio.linhas.iterrows():
        aditivos = aditivos_do_registro(linha["aditivos"])
        status = str(linha["status_contrato"]).strip().upper()
        vigencia = vigencia_efetiva(linha["vigencia_fim"], aditivos)[0]
        if (
            status not in (STATUS_SUSPENSO, STATUS_VENCIDO) and pd.notna(vigencia)
            and vigencia.year == relatorio.exercicio and vigencia < ultimo_dia
        ):
            sem_renovacao.append(f"{rotulo(indice)} (vigência até {vigencia:%d/%m/%Y})")
        if aditivos and pd.notna(linha["qtd_linhas_na_ne"]) and linha["qtd_linhas_na_ne"] > 1:
            compartilhadas.append(rotulo(indice))
        if linha["inclui_previsto"]:
            termos = ", ".join(a.numero for a in aditivos if a.previsto)
            previstos.append(f"{rotulo(indice)} ({termos})")
        termos_negativos = [a.numero for a in aditivos if a.valor_mensal is not None and a.valor_mensal < 0]
        if termos_negativos:
            negativos.append(f"{rotulo(indice)} ({', '.join(termos_negativos)})")
    avisos = []
    if sem_renovacao:
        avisos.append(
            "Renovação não cadastrada — a vigência efetiva acaba no exercício e não há aditivo (nem previsto) "
            "depois dela; a projeção e a necessidade param no vencimento (cadastre o aditivo, mesmo como "
            "previsto, para estimar a renovação): " + "; ".join(sem_renovacao) + "."
        )
    if previstos:
        avisos.append(
            "Aditivos previstos (valores estimados): ainda não assinados, entram na necessidade e na projeção: "
            + "; ".join(previstos) + "."
        )
    if negativos:
        avisos.append("Aditivo com valor mensal negativo (confira o termo): " + "; ".join(negativos) + ".")
    if compartilhadas:
        avisos.append(
            "NE compartilhada por mais de um contrato com aditivos — a necessidade usa os aditivos e a vigência do "
            "primeiro contrato da NE para todos (confira cada contrato): " + "; ".join(compartilhadas) + "."
        )
    return avisos


def notas_de_aditivos(relatorio: RelatorioNecessidade) -> list[str]:
    """Notas do PDF sobre aditivos (06/10/2026): a legenda dos meses de aditivo previsto e, por NE, o
    retroativo incluído no primeiro mês projetado. Sem aditivos, lista vazia."""

    notas = []
    if any(str(texto) for texto in relatorio.mensal["meses_previstos"]):
        notas.append("Meses em laranja: valor estimado (aditivo previsto), ainda não assinado.")
    for indice, linha in relatorio.linhas.iterrows():
        retroativo = float(relatorio.mensal.at[indice, "retroativo"])
        if retroativo:
            termos = relatorio.mensal.at[indice, "retroativo_termos"]
            notas.append(
                f"{_texto_ou_traco(linha['ne_curta'])} inclui R$ {_formatar_brl(retroativo)} de retroativo ({termos})."
            )
    return notas


def valor_estimado_em_previstos(
    filtrado: pd.DataFrame, meses_liquidados_por_ne: pd.DataFrame | None, exercicio: int
) -> float:
    """Quanto da Necessidade de Empenho até Dezembro vem de aditivos PREVISTO (valores estimados): a
    necessidade com eles menos a necessidade sem eles. 0,0 quando não há aditivo previsto."""

    if "aditivos" not in filtrado.columns:
        return 0.0
    listas = [aditivos_do_registro(valor) for valor in filtrado["aditivos"]]
    if not any(a.previsto for lista in listas for a in lista):
        return 0.0
    sem_previstos = filtrado.copy()
    sem_previstos["aditivos"] = pd.Series([[a for a in lista if not a.previsto] for lista in listas], index=filtrado.index, dtype=object)

    def total(tabela: pd.DataFrame) -> float:
        por_ne, sem_ne = necessidade_por_ne(tabela, meses_liquidados_por_ne, exercicio)
        return float(por_ne["necessidade"].sum() + sem_ne["necessidade"].sum())

    return total(filtrado) - total(sem_previstos)


NOTA_PROJECAO = (
    "Meses com liquidação por competência = Realizado. A projeção (meses sombreados) começa no "
    "primeiro mês sem liquidação e vai até dezembro: o primeiro mês projeta despesa mensal − saldo "
    "atual do empenho e os seguintes a despesa mensal cheia (saldo maior que a despesa mensal é "
    "abatido nos meses seguintes). Limitada aos meses que o contrato é pago no exercício menos os "
    "já realizados e pela vigência: a data de fim da vigência do cadastro manda (a projeção para "
    "no mês do fim, que é proporcional aos dias) e o status SUSPENSO não projeta a partir da data da "
    "suspensão (sem data, nada). Nenhuma média "
    "nem tendência — só a despesa mensal cadastrada."
)


def _linhas_parametros(relatorio: RelatorioNecessidade, contexto: ContextoRelatorioNecessidade) -> list[tuple[str, str]]:
    return [
        ("Exercício", str(contexto.exercicio)),
        ("Recorte", f"busca: {contexto.busca!r}" if contexto.busca else "todos os contratos do exercício"),
        ("NEs", str(relatorio.qtd_ne)),
        ("Itens sem NE", str(relatorio.qtd_sem_ne)),
        ("Necessidade projetada na grade (R$)", _formatar_brl(relatorio.total_projetado)),
        ("Necessidade até Dezembro — Resumo Consolidado (R$)", _formatar_brl(relatorio.total_necessidade)),
        ("Empenhado total (R$)", _formatar_brl(relatorio.total_empenhado)),
        ("Saldo atual total das NEs (R$)", _formatar_brl(relatorio.total_saldo)),
        ("Última extração da Execução Mensal", _mes_referencia_texto(relatorio, contexto)),
        ("Projeção", NOTA_PROJECAO),
        ("Regra do Resumo Consolidado", NOTA_REGRA),
        ("Execução Mensal", f"extração de {contexto.data_extracao} · hash {contexto.hash_manifesto}"),
        ("Liquidação por Competência", contexto.origem_competencia or "indisponível"),
        ("Emitido em", contexto.data_emissao),
    ]


# ------------------------------------------------------------------------------ Excel
_COLUNAS_VALOR_XLSX = {
    "Empenhado", "Liquidado", "Saldo atual do empenho", "Despesa mensal", "Necessidade até dezembro (Resumo)",
    "Necessidade projetada (grade)", "Total realizado", "Total projetado", "Total", "Valor", *MESES,
    # aditivos (06/10/2026)
    "Valor mensal vigente", "Custo do exercício", "Retroativo", "Valor anterior", "Valor novo",
}
_COLUNAS_DATA_XLSX = ("Vigência (fim)", "Início da execução", "Início", "Assinatura", "Nova vigência")
_COLUNAS_NUMERO_XLSX = {
    "Meses no ano", "Meses já empenhados", "Meses restantes", "Meses liquidados (competência)",
    "Meses vigentes no exercício",
}
_PREENCHIMENTO_PROJETADO = "FFF2CC"
#: mês projetado por aditivo PREVISTO (valor estimado, ainda não assinado)
_PREENCHIMENTO_PREVISTO = "F8CBAD"


def _soma(valores: list[float | None]) -> float | None:
    soma = pd.Series(valores, dtype="float64").sum(min_count=1)
    return None if pd.isna(soma) else float(soma)


def _aba_projecao_mensal(relatorio: RelatorioNecessidade) -> tuple[pd.DataFrame, list[list[bool]]]:
    """Uma linha por NE/item, colunas Jan…Dez: o valor de cada mês (realizado ou projetado).
    Devolve também, por linha, quais meses são projetados (para o destaque)."""

    registros = []
    projetados = []
    for indice, linha in relatorio.linhas.iterrows():
        valores = [relatorio.valor_do_mes(indice, m) for m in range(1, 13)]
        projetados.append([projetado for _, projetado in valores])
        registros.append(
            {
                "NE": _texto(linha["ne_curta"]),
                "Fornecedor": _texto(linha["fornecedor"]),
                "Contrato": _texto(linha["contrato_numero"]),
                "Status": _texto(linha["status_contrato"]),
                "Vigência (fim)": None if pd.isna(linha["vigencia_fim"]) else pd.Timestamp(linha["vigencia_fim"]).date(),
                "Início da execução": (
                    None if pd.isna(linha["inicio_execucao_considerado"])
                    else pd.Timestamp(linha["inicio_execucao_considerado"]).date()
                ),
                "Saldo atual do empenho": linha["saldo"],
                "Primeiro mês projetado": _nome_mes(relatorio.mensal.at[indice, "primeiro_mes_projecao"]),
                "Observação da projeção": _texto(relatorio.mensal.at[indice, "observacao_projecao"]) or None,
                **{nome: valor for nome, (valor, _) in zip(MESES, valores)},
                "Total realizado": relatorio.realizado_da_linha(indice),
                "Total projetado": relatorio.projetado_da_linha(indice),
            }
        )
    colunas = ["NE", "Fornecedor", "Contrato", "Status", "Vigência (fim)", "Início da execução", "Saldo atual do empenho",
               "Primeiro mês projetado", *MESES, "Total realizado", "Total projetado", "Observação da projeção"]
    aba = pd.DataFrame(registros, columns=colunas)
    for coluna in ("Saldo atual do empenho", *MESES, "Total realizado", "Total projetado"):
        aba[coluna] = aba[coluna].astype("float64")
    return aba, projetados


def _aba_detalhe_mensal(relatorio: RelatorioNecessidade) -> pd.DataFrame:
    """Formato longo (NE × mês) com o Tipo (Realizado/Projetado) — filtrável; só meses com dado."""

    registros = []
    for indice, linha in relatorio.linhas.iterrows():
        for mes in range(1, 13):
            valor, projetado = relatorio.valor_do_mes(indice, mes)
            if valor is None:
                continue
            # o retroativo dos reajustes entra no primeiro mês projetado (spec §4.3)
            retroativo = float(relatorio.mensal.at[indice, "retroativo"])
            retroativo_do_mes = retroativo if retroativo and mes == relatorio.mensal.at[indice, "primeiro_mes_projecao"] else None
            registros.append(
                {
                    "NE": _texto(linha["ne_curta"]), "Fornecedor": _texto(linha["fornecedor"]),
                    "Contrato": _texto(linha["contrato_numero"]), "Nº do mês": mes, "Mês": MESES[mes - 1],
                    "Tipo": relatorio.tipo_do_mes(indice, mes), "Valor": valor,
                    "Retroativo": retroativo_do_mes,
                }
            )
    aba = pd.DataFrame(
        registros, columns=["NE", "Fornecedor", "Contrato", "Nº do mês", "Mês", "Tipo", "Valor", "Retroativo"]
    )
    aba["Valor"] = aba["Valor"].astype("float64")
    aba["Retroativo"] = aba["Retroativo"].astype("float64")
    return aba


COLUNAS_ABA_ADITIVOS = [
    "Contrato", "NE", "Nº do termo", "Tipo", "Situação", "Início", "Assinatura", "Valor anterior",
    "Valor novo", "Nova vigência", "Retroativo",
]


def _aba_aditivos(relatorio: RelatorioNecessidade) -> pd.DataFrame:
    """Uma linha por aditivo dos contratos do relatório (06/10/2026), para conferir cada número com o termo:
    valor anterior → novo, datas e retroativo calculado. Vazio = "mantém o anterior" (nulo, nunca zero);
    `Retroativo` só existe para aditivo assinado com valor novo e assinatura posterior ao início."""

    registros = []
    for indice, linha in relatorio.linhas.iterrows():
        aditivos = aditivos_do_registro(linha["aditivos"])
        realizados = {m for m in range(1, 13) if not pd.isna(relatorio.mensal.at[indice, f"r{m}"])}
        retroativos = {id(a): v for a, v in retroativo_por_aditivo(linha["despesa_mensal"], aditivos, relatorio.exercicio, realizados)}
        for aditivo in aditivos:
            anterior = (
                None if aditivo.data_inicio is None
                else valor_vigente_em(linha["despesa_mensal"], aditivos, aditivo.data_inicio - timedelta(days=1))[0]
            )
            registros.append(
                {
                    "Contrato": _texto(linha["contrato_numero"]), "NE": _texto(linha["ne_curta"]),
                    "Nº do termo": aditivo.numero, "Tipo": ROTULO_TIPO.get(aditivo.tipo, aditivo.tipo),
                    "Situação": ROTULO_SITUACAO.get(aditivo.situacao, aditivo.situacao),
                    "Início": aditivo.data_inicio, "Assinatura": aditivo.data_assinatura,
                    "Valor anterior": anterior, "Valor novo": aditivo.valor_mensal,
                    "Nova vigência": aditivo.vigencia_fim, "Retroativo": retroativos.get(id(aditivo)),
                }
            )
    aba = pd.DataFrame(registros, columns=COLUNAS_ABA_ADITIVOS)
    for coluna in ("Valor anterior", "Valor novo", "Retroativo"):
        aba[coluna] = aba[coluna].astype("float64")
    return aba


def _aba_total_mensal(relatorio: RelatorioNecessidade) -> pd.DataFrame:
    realizado = relatorio.total_mensal_realizado
    projetado = relatorio.total_mensal_projetado
    aba = pd.DataFrame(
        [
            {"Tipo": TIPO_REALIZADO, **dict(zip(MESES, realizado)), "Total": _soma(realizado)},
            {"Tipo": TIPO_PROJETADO, **dict(zip(MESES, projetado)), "Total": _soma(projetado)},
        ]
    )
    for coluna in (*MESES, "Total"):
        aba[coluna] = aba[coluna].astype("float64")
    return aba


def _formatar_aba(planilha, dados: pd.DataFrame) -> None:
    """Formatos numéricos e larguras; congela a primeira coluna e o cabeçalho."""

    for indice, cabecalho in enumerate(dados.columns, start=1):
        letra = planilha.cell(row=1, column=indice).column_letter
        if cabecalho in _COLUNAS_VALOR_XLSX:
            formato = "#,##0.00"
        elif cabecalho in _COLUNAS_DATA_XLSX:
            formato = "dd/mm/yyyy"
        elif cabecalho in _COLUNAS_NUMERO_XLSX or cabecalho == "Nº do mês":
            formato = "0.00" if cabecalho in _COLUNAS_NUMERO_XLSX else "0"
        else:
            formato = "@"
        for celula in planilha[letra][1:]:
            celula.number_format = formato
        planilha.column_dimensions[letra].width = (
            45 if cabecalho in ("Fornecedor", "Observação da projeção") else min(max(len(cabecalho), 12) + 2, 32)
        )
    planilha.freeze_panes = "B2"


def gerar_xlsx(relatorio: RelatorioNecessidade, contexto: ContextoRelatorioNecessidade) -> bytes:
    """Abas: "Projeção mensal" (uma linha por NE, Jan…Dez; meses projetados sombreados e em
    itálico; mês de aditivo previsto em laranja), "Detalhe mensal" (formato longo com o Tipo de cada mês e o
    retroativo), "Total mensal", "Resumo por NE", "Aditivos" (um aditivo por linha) e "Parâmetros" (totais, regra e avisos). Nenhuma linha de total no meio das abas de dados.
    Nulo é célula vazia, nunca zero."""

    from openpyxl.styles import Font, PatternFill

    linhas = relatorio.linhas
    resumo = pd.DataFrame(
        {
            "NE": linhas["ne_curta"].map(_texto).astype(object),
            "Fornecedor": linhas["fornecedor"].map(_texto).astype(object),
            "Contrato": linhas["contrato_numero"].map(_texto).astype(object),
            "Empenhado": linhas["valor_empenhado"],
            "Liquidado": linhas["valor_liquidado"],
            "Saldo atual do empenho": linhas["saldo"],
            "Despesa mensal": linhas["despesa_mensal"],
            "Valor mensal vigente": linhas["valor_mensal_vigente"],
            "Custo do exercício": linhas["custo_exercicio"],
            "Retroativo": linhas["retroativo"],
            "Meses no ano": linhas["meses_no_ano"],
            "Meses já empenhados": linhas["meses_ja_empenhados"],
            "Meses vigentes no exercício": linhas["meses_vigentes"],
            "Meses restantes": linhas["meses_restantes"],
            "Necessidade até dezembro (Resumo)": linhas["necessidade"],
            "Necessidade projetada (grade)": [relatorio.projetado_da_linha(i) for i in linhas.index],
            "Status": linhas["status_contrato"].map(_texto).astype(object),
            "Vigência (fim)": [None if pd.isna(v) else pd.Timestamp(v).date() for v in linhas["vigencia_fim"]],
            "Início da execução": [
                None if pd.isna(v) else pd.Timestamp(v).date() for v in linhas["inicio_execucao_considerado"]
            ],
            "Primeiro mês projetado": [_nome_mes(relatorio.mensal.at[i, "primeiro_mes_projecao"]) for i in linhas.index],
            "Observação da projeção": [_texto(relatorio.mensal.at[i, "observacao_projecao"]) or None for i in linhas.index],
            "Base do saldo": linhas["base_saldo"].map(_texto).astype(object),
            "Meses liquidados (competência)": linhas["meses_liquidados"],
            "Último mês liquidado": linhas["ultimo_mes_liquidado"].map(_mes_ano).replace("—", None).astype(object),
        }
    )
    resumo["Necessidade projetada (grade)"] = resumo["Necessidade projetada (grade)"].astype("float64")

    projecao, projetados = _aba_projecao_mensal(relatorio)
    detalhe = _aba_detalhe_mensal(relatorio)
    total_mensal = _aba_total_mensal(relatorio)
    aditivos = _aba_aditivos(relatorio)
    parametros = [("Avisos", aviso) for aviso in _avisos(relatorio, contexto)] + _linhas_parametros(relatorio, contexto)
    coluna_jan = list(projecao.columns).index(MESES[0]) + 1

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        projecao.to_excel(writer, sheet_name="Projeção mensal", index=False)
        planilha = writer.sheets["Projeção mensal"]
        _formatar_aba(planilha, projecao)
        for (numero_linha, meses_projetados), indice in zip(enumerate(projetados, start=2), relatorio.linhas.index):
            for mes, projetado in enumerate(meses_projetados):
                if projetado:
                    celula = planilha.cell(row=numero_linha, column=coluna_jan + mes)
                    previsto = relatorio.tipo_do_mes(indice, mes + 1) == TIPO_PROJETADO_PREVISTO
                    celula.fill = PatternFill("solid", fgColor=_PREENCHIMENTO_PREVISTO if previsto else _PREENCHIMENTO_PROJETADO)
                    celula.font = Font(italic=True)
        detalhe.to_excel(writer, sheet_name="Detalhe mensal", index=False)
        _formatar_aba(writer.sheets["Detalhe mensal"], detalhe)
        total_mensal.to_excel(writer, sheet_name="Total mensal", index=False)
        _formatar_aba(writer.sheets["Total mensal"], total_mensal)
        resumo.to_excel(writer, sheet_name="Resumo por NE", index=False)
        _formatar_aba(writer.sheets["Resumo por NE"], resumo)
        aditivos.to_excel(writer, sheet_name="Aditivos", index=False)
        _formatar_aba(writer.sheets["Aditivos"], aditivos)
        pd.DataFrame(parametros, columns=["Parâmetro", "Valor"]).to_excel(writer, sheet_name="Parâmetros", index=False)
        writer.sheets["Parâmetros"].column_dimensions["A"].width = 46
        writer.sheets["Parâmetros"].column_dimensions["B"].width = 120
    return buffer.getvalue()


# -------------------------------------------------------------------------------- PDF
_CABECALHO_MENSAL_PDF = ["NE", "SALDO ATUAL", *[m.upper() for m in MESES], "REALIZADO", "PROJETADO"]
#: landscape(A4) com 10mm de margem (~785pt úteis).
_LARGURAS_MENSAL_PDF = [52, 60] + [46] * 12 + [58, 58]
_CABECALHO_TOTAL_PDF = ["TOTAL", "", *[m.upper() for m in MESES], "REALIZADO", "PROJETADO"]
_CABECALHO_RESUMO_PDF = [
    "NE", "FORNECEDOR / CONTRATO", "EMPENHADO (R$)", "SALDO ATUAL (R$)", "DESP. MENSAL (R$)",
    "NECESSIDADE RESUMO (R$)", "NECESSIDADE PROJETADA (R$)", "1º MÊS PROJ.", "BASE DO SALDO",
]
_LARGURAS_RESUMO_PDF = [62, 195, 72, 72, 66, 76, 76, 40, 126]
_COR_TITULO_NE = colors.HexColor("#E8EEF7")
_COR_PROJETADO = colors.HexColor(f"#{_PREENCHIMENTO_PROJETADO}")
_COR_PREVISTO = colors.HexColor(f"#{_PREENCHIMENTO_PREVISTO}")


def _estilo_base() -> list[tuple]:
    return [
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDDDDD")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]


def gerar_pdf(relatorio: RelatorioNecessidade, contexto: ContextoRelatorioNecessidade) -> bytes:
    buffer = BytesIO()
    documento = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
        title=f"{TITULO} — {contexto.exercicio}",
    )
    estilos = getSampleStyleSheet()
    estilo_parametro = estilos["Normal"].clone("parametro_necessidade")
    estilo_parametro.fontSize = 8
    estilo_parametro.leading = 10
    estilo_aviso = estilo_parametro.clone("aviso_necessidade")
    estilo_aviso.textColor = colors.HexColor("#8A4B00")
    estilo_celula = estilos["Normal"].clone("celula_necessidade")
    estilo_celula.fontSize = 6.5
    estilo_celula.leading = 7.5
    estilo_titulo_ne = estilo_celula.clone("titulo_ne_necessidade")
    estilo_titulo_ne.fontSize = 7
    estilo_titulo_ne.leading = 8.5

    elementos: list = [Paragraph(escape(f"{TITULO} — EXERCÍCIO {contexto.exercicio}"), estilos["Heading3"])]
    for aviso in _avisos(relatorio, contexto):
        elementos.append(Paragraph(f"<b>ATENÇÃO:</b> {escape(aviso)}", estilo_aviso))
    for rotulo, valor in _linhas_parametros(relatorio, contexto):
        elementos.append(Paragraph(f"<b>{escape(rotulo)}:</b> {escape(valor)}", estilo_parametro))
    elementos.append(Spacer(1, 8))

    # ---- grade mensal: uma faixa de título por NE e UMA linha de valores — cada mês mostra o
    # realizado ou, sombreado e em itálico, o projetado; a quebra de página só acontece ENTRE NEs.
    dados: list[list[object]] = [_CABECALHO_MENSAL_PDF]
    comandos: list[tuple] = []
    for indice, linha in relatorio.linhas.iterrows():
        inicio_proj = relatorio.mensal.at[indice, "primeiro_mes_projecao"]
        titulo = (
            f"<b>{escape(_texto_ou_traco(linha['ne_curta']) if pd.notna(linha['ne_curta']) else '(sem NE)')}</b>"
            f" — {escape(_texto(linha['fornecedor']) or '(sem fornecedor)')}"
            f" — Contrato {escape(_texto_ou_traco(linha['contrato_numero']))}"
            f" — Status {escape(_texto_ou_traco(linha['status_contrato']))}"
            f" — Vigência até {escape(_mes_ano_dia(linha['vigencia_fim']))}"
            f"{escape(' — Início da execução ' + _mes_ano_dia(linha['inicio_execucao_considerado'])) if pd.notna(linha['inicio_execucao_considerado']) else ''}"
            f" — Saldo atual do empenho R$ {escape(_formatar_brl(linha['saldo']))}"
            f" — Projeção a partir de {escape(_nome_mes(inicio_proj) or '—')}"
            f" — Necessidade projetada R$ {escape(_formatar_brl(relatorio.projetado_da_linha(indice)))}"
            f"<br/><i>{escape(_texto(relatorio.mensal.at[indice, 'observacao_projecao']) or '')}</i>"
        )
        posicao = len(dados)
        dados.append([Paragraph(titulo, estilo_titulo_ne)] + [""] * (len(_CABECALHO_MENSAL_PDF) - 1))
        valores = [relatorio.valor_do_mes(indice, m) for m in range(1, 13)]
        dados.append(
            [
                _texto_ou_traco(linha["ne_curta"]), _formatar_brl(linha["saldo"]),
                *[_formatar_brl(valor) for valor, _ in valores],
                _formatar_brl(relatorio.realizado_da_linha(indice)),
                _formatar_brl(relatorio.projetado_da_linha(indice)),
            ]
        )
        comandos += [
            ("SPAN", (0, posicao), (-1, posicao)),
            ("BACKGROUND", (0, posicao), (-1, posicao), _COR_TITULO_NE),
            ("NOSPLIT", (0, posicao), (-1, posicao + 1)),
        ]
        for mes, (_, projetado) in enumerate(valores, start=1):
            if projetado:
                previsto = relatorio.tipo_do_mes(indice, mes) == TIPO_PROJETADO_PREVISTO
                comandos += [
                    ("BACKGROUND", (mes + 1, posicao + 1), (mes + 1, posicao + 1), _COR_PREVISTO if previsto else _COR_PROJETADO),
                    ("FONTNAME", (mes + 1, posicao + 1), (mes + 1, posicao + 1), "Helvetica-Oblique"),
                ]
    tabela = Table(dados, colWidths=_LARGURAS_MENSAL_PDF, repeatRows=1)
    tabela.setStyle(TableStyle(_estilo_base() + [("ALIGN", (1, 0), (-1, -1), "RIGHT")] + comandos))
    estilo_secao = estilos["Heading4"]
    elementos.append(Paragraph("Realizado × projeção mês a mês (meses projetados sombreados, em itálico)", estilo_secao))
    elementos.append(tabela)
    for nota in notas_de_aditivos(relatorio):
        elementos.append(Paragraph(escape(nota), estilo_parametro))
    elementos.append(Spacer(1, 10))

    # ---- total mensal de todas as linhas, separando realizado e projetado
    realizado_total = relatorio.total_mensal_realizado
    projetado_total = relatorio.total_mensal_projetado
    dados_total = [
        ["Realizado", "", *[_formatar_brl(v) for v in realizado_total], _formatar_brl(_soma(realizado_total)), ""],
        ["Projetado", "", *[_formatar_brl(v) for v in projetado_total], "", _formatar_brl(_soma(projetado_total))],
    ]
    tabela_total = Table([_CABECALHO_TOTAL_PDF, *dados_total], colWidths=_LARGURAS_MENSAL_PDF)
    tabela_total.setStyle(
        TableStyle(
            _estilo_base()
            + [
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                ("BACKGROUND", (2, 2), (13, 2), _COR_PROJETADO),
                ("FONTNAME", (2, 2), (13, 2), "Helvetica-Oblique"),
            ]
        )
    )
    elementos.append(Paragraph("Total mensal (todas as NEs e itens do relatório)", estilo_secao))
    elementos.append(tabela_total)
    elementos.append(Spacer(1, 10))

    # ---- resumo por NE (empenhado, saldo, as duas necessidades)
    dados_resumo: list[list[object]] = [_CABECALHO_RESUMO_PDF]
    for indice, linha in relatorio.linhas.iterrows():
        identificacao = (
            f"{escape(_texto(linha['fornecedor']) or '(sem fornecedor)')}"
            f"<br/>Contrato {escape(_texto_ou_traco(linha['contrato_numero']))}"
        )
        dados_resumo.append(
            [
                _texto_ou_traco(linha["ne_curta"]),
                Paragraph(identificacao, estilo_celula),
                _formatar_brl(linha["valor_empenhado"]),
                _formatar_brl(linha["saldo"]),
                _formatar_brl(linha["despesa_mensal"]),
                _formatar_brl(linha["necessidade"]),
                _formatar_brl(relatorio.projetado_da_linha(indice)),
                _nome_mes(relatorio.mensal.at[indice, "primeiro_mes_projecao"]) or "—",
                Paragraph(escape(str(linha["base_saldo"])), estilo_celula),
            ]
        )
    dados_resumo.append(
        [
            "TOTAL", "", _formatar_brl(relatorio.total_empenhado), _formatar_brl(relatorio.total_saldo), "",
            _formatar_brl(relatorio.total_necessidade), _formatar_brl(relatorio.total_projetado), "", "",
        ]
    )
    tabela_resumo = Table(dados_resumo, colWidths=_LARGURAS_RESUMO_PDF, repeatRows=1)
    tabela_resumo.setStyle(
        TableStyle(
            _estilo_base()
            + [
                ("ALIGN", (2, 0), (6, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F5F5F5")]),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ]
        )
    )
    elementos.append(Paragraph("Resumo por NE — Necessidade de Empenho até Dezembro", estilo_secao))
    elementos.append(tabela_resumo)
    documento.build(elementos)
    return buffer.getvalue()
