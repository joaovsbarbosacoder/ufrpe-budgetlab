"""
Leitura e normalização da planilha de Contratos Contínuos (PROAD).

Camada: regra específica de base (não é leitor genérico, não é analítica, não é interface).
Depende só de pandas/openpyxl. Não importa Streamlit.

Origem: planilha de trabalho mantida manualmente (`SERVIÇOS CONTÍNUOS - 2026 - AGO A DEZ.xlsm`),
não um export único e estável como o BI CPOC da Execução Mensal — por isso o casamento de
colunas é por NOME normalizado (sem acento, maiúsculo), não por posição: numa planilha editada
à mão a ordem das colunas muda com mais facilidade do que o texto do cabeçalho.

Aba lida: "Planilha atualizada". Granularidade: uma linha por contrato × item de
licitação/despesa dentro do empenho vigente — não uma linha por contrato, não por mês.

As colunas `MESES A EMPENHAR`/`EMPENHAR (R$)` da origem ficam de fora do esquema: estão
sempre vazias nesta planilha (conferido em 4 extrações diferentes) — a coluna real com a
mesma lógica de negócio é `MESES DE SALDO`, recalculada aqui como `meses_a_empenhar`/
`valor_a_empenhar` via `src/necessidade_empenho.py`, em vez de lida da origem.

`SALDO TOTAL TG` (o saldo colado manualmente na aba BASE_TG desta planilha, no nível da NE)
vira `saldo_colado_planilha` — não `SALDO TG ATUALIZADO`, que é o mesmo saldo rateado por
item de licitação quando o contrato tem mais de um (`% ITEM LIC.`); comparar essa fração
contra `saldo_execucao` (sempre no nível da NE inteira) geraria falsa divergência em todo
contrato com vários itens. Ver `com_saldo_execucao` para o saldo autoritativo, derivado da
Execução Mensal já validada do projeto.

Contrato público:
    ler_contratos_continuos(caminho) -> pd.DataFrame
    com_saldo_execucao(df, por_ne_execucao, indice_liquidado_competencia=None) -> pd.DataFrame
    com_meses_pagos(df, meses_pagos) -> pd.DataFrame
    com_efeitos_da_suspensao(df) -> pd.DataFrame
    situacao_contrato(status, vigencia_fim_efetiva, necessidade, hoje) -> (texto, tom)
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd

from src.cache_bases import em_cache
from src.leitura_excel import motor_excel

from src.contratos_pagamentos import normalizar_numero_contrato
from src.execucao_ne_utils import (
    indice_liquidado_por_ne_curta,
    indice_saldo_por_ne_curta,
    indice_valor_empenhado_por_ne_curta,
)
from src.necessidade_empenho import STATUS_SUSPENSO, STATUS_VENCIDO, calcular_necessidade_empenho

NOME_ABA = "Planilha atualizada"

#: sentinelas de "sem empenho" usadas nesta planilha na coluna EMPENHO.
_SENTINELAS_SEM_EMPENHO = {"", "-", "0"}


class ErroLayoutBase(ValueError):
    """Cabeçalho da planilha sem as colunas esperadas — falhar cedo, nunca adivinhar."""


def _normalizar(texto: object) -> str:
    if texto is None:
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sem_acento).strip().upper()


#: cabeçalho normalizado (sem acento, maiúsculo) da origem -> nome interno da coluna. Colunas
#: da origem que não aparecem aqui são descartadas na leitura: HOJE (data da fórmula, não
#: dado), NECESSIDADE DE EMPENHO/MÊS ATUAL (métrica prospectiva de calendário, fora de escopo
#: por ora), OBSERVAÇÃO (sempre vazia nesta extração), ANULAR (R$)/SALDO ANTERIOR (quase todo
#: nulo), STATUS ATUALIZAÇÃO (housekeeping da automação da planilha, não do dado),
#: MESES A EMPENHAR/EMPENHAR (R$) (ver docstring do módulo), e SALDO TG ATUALIZADO (saldo por
#: item rateado — ver nota sobre `SALDO TOTAL TG` acima).
COLUNAS_ORIGEM = {
    "ANO CONTRATO": "ano_contrato",
    "NO CONTRATO": "contrato_numero",
    "NO PROCESSO CONTRATACAO": "processo_contratacao",
    "NO PROCESSO EMPENHO": "processo_empenho",
    "FORNECEDOR": "fornecedor",
    "TIPO": "tipo_contrato",
    "TIPO DE DESPESA": "tipo_despesa",
    "CNPJ/CPF FORNEC": "fornecedor_cnpj_cpf",
    "DT VIGENCIA CONTRATO": "vigencia_fim",
    "STATUS": "status_contrato",
    "UNIDADE": "unidade_cod",
    "ACAO": "acao_cod",
    "PTRES": "ptres",
    "FONTE": "fonte_cod",
    "ND": "natureza_despesa_cod",
    "UGR": "ugr_cod",
    "PI": "pi_cod",
    "VARIOS ITENS LIC.": "tem_varios_itens",
    "EMPENHO": "ne_curta",
    "MESES DE SALDO": "meses_de_saldo",
    "MESES EMPENHADOS": "meses_empenhados",
    "MESES LIQUIDADOS": "meses_liquidados",
    "ITEM LIC.": "item_licitacao",
    "%": "item_percentual",
    "DESPESA MENSAL": "despesa_mensal",
    "DESPESA ANUAL": "despesa_anual",
    "VALOR EMPENHADO": "valor_empenhado",
    "SALDO TOTAL TG": "saldo_colado_planilha",
}

_COLUNAS_TEXTO = {
    "contrato_numero", "processo_contratacao", "processo_empenho", "fornecedor",
    "tipo_contrato", "tipo_despesa", "fornecedor_cnpj_cpf", "status_contrato",
    "unidade_cod", "acao_cod", "ptres", "fonte_cod", "natureza_despesa_cod",
    "ugr_cod", "pi_cod", "ne_curta",
}
_COLUNAS_NUMERICAS = {
    "ano_contrato", "meses_de_saldo", "meses_empenhados", "meses_liquidados",
    "item_licitacao", "item_percentual", "despesa_mensal", "despesa_anual",
    "valor_empenhado", "saldo_colado_planilha",
}


@em_cache
def ler_contratos_continuos(caminho: str | Path) -> pd.DataFrame:
    """Lê a aba "Planilha atualizada" e devolve o DataFrame normalizado, com as colunas
    derivadas `meses_a_empenhar`/`valor_a_empenhar` (ver docstring do módulo). Não liga com a
    Execução Mensal — para isso, `com_saldo_execucao`."""

    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(caminho)

    bruto = pd.read_excel(caminho, sheet_name=NOME_ABA, header=0, dtype=object, engine=motor_excel())

    normalizados = {coluna: _normalizar(coluna) for coluna in bruto.columns}
    faltando = set(COLUNAS_ORIGEM) - set(normalizados.values())
    if faltando:
        raise ErroLayoutBase(
            f"Colunas ausentes na aba {NOME_ABA!r} de {caminho.name}: {sorted(faltando)}. "
            "O layout da planilha mudou."
        )

    mapa = {origem: COLUNAS_ORIGEM[norm] for origem, norm in normalizados.items() if norm in COLUNAS_ORIGEM}
    df = bruto.rename(columns=mapa)[list(mapa.values())].copy()

    # linhas em branco no fim da planilha de trabalho e a linha de total (soma de todas as
    # colunas monetárias, sem FORNECEDOR nem nenhuma outra coluna identificadora — só
    # "STATUS ATUALIZAÇÃO" preenchido com um resumo textual como "52 atualizados") não são
    # linha de dado; um `dropna(how="all")` não pega a linha de total (ela tem várias colunas
    # com valor, só não as identificadoras), mesmo bug já resolvido para Bolsas e Auxílios via
    # `processo` (ver `ler_bolsas_auxilios`). FORNECEDOR nunca é nulo em nenhuma linha real
    # desta planilha (conferido na extração de 13/08/2026).
    df = df.dropna(subset=["fornecedor"]).reset_index(drop=True)

    for coluna in _COLUNAS_TEXTO:
        df[coluna] = df[coluna].astype("string").str.strip()

    for coluna in _COLUNAS_NUMERICAS:
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")

    df["vigencia_fim"] = pd.to_datetime(df["vigencia_fim"], errors="coerce")
    df["tem_varios_itens"] = df["tem_varios_itens"].str.upper().eq("SIM")
    df.loc[df["ne_curta"].isin(_SENTINELAS_SEM_EMPENHO), "ne_curta"] = pd.NA

    df["meses_a_empenhar"], df["valor_a_empenhar"] = calcular_necessidade_empenho(
        df["meses_empenhados"], df["meses_liquidados"], df["despesa_mensal"]
    )

    return df


def _diverge(execucao: pd.Series, planilha: pd.Series, tolerancia: float = 0.01) -> pd.Series:
    tem_os_dois = execucao.notna() & planilha.notna()
    diferenca = (execucao - planilha).abs()
    resultado = pd.Series(pd.NA, index=execucao.index, dtype="boolean")
    resultado.loc[tem_os_dois] = diferenca[tem_os_dois] > tolerancia
    return resultado


def com_saldo_execucao(
    df: pd.DataFrame,
    por_ne_execucao: pd.DataFrame,
    indice_liquidado_competencia: pd.Series | None = None,
) -> pd.DataFrame:
    """Acrescenta, via `ne_curta`, dois pares de campos buscados na Execução Mensal já
    validada do projeto: `saldo_execucao`/`diverge_saldo` (contra `saldo_colado_planilha`,
    sempre no nível da NE nos dois lados) e `valor_empenhado_execucao`/
    `diverge_valor_empenhado` (contra a soma de `valor_empenhado` por NE, não o valor da
    linha) — ambos com divergência True quando a diferença passa de R$ 0,01.
    `por_ne_execucao` é o resultado de
    `execucao_ne_utils.saldo_por_ne(tesouro_execucao_mensal.agregar_por_ne(...))`.

    `valor_empenhado` da planilha é rateado por item de licitação quando o contrato tem mais
    de um (mesmo problema de `SALDO TG ATUALIZADO` vs. `SALDO TOTAL TG`, ver docstring do
    módulo): comparar a Execução (sempre no nível da NE) contra o valor de um item isolado
    geraria falsa divergência em todo contrato com vários itens — soma-se por NE antes de
    comparar. `valor_empenhado_planilha_total_ne` (novo campo) é essa soma, repetida em todas
    as linhas da mesma NE; `valor_empenhado` da linha continua sendo o valor do item,
    inalterado.

    NE sem correspondência na Execução (ou linha sem `ne_curta`, contrato ainda sem empenho)
    fica com os campos de comparação nulos — não é erro, é ausência de dado para comparar.

    Também recalcula `meses_a_empenhar`/`valor_a_empenhar` (a "Necessidade de Empenho") a
    partir da Execução Mensal em vez das colunas manuais `meses_empenhados`/`meses_liquidados`
    da planilha, para todo contrato cuja NE já foi encontrada acima: `valor_liquidado_execucao`
    (novo campo) e `valor_empenhado_execucao` ÷ `despesa_mensal_total_ne` (despesa mensal
    somada por NE, mesmo motivo do rateio acima) viram
    `meses_liquidados_execucao`/`meses_empenhados_execucao` — fração exata, sem arredondar
    (decisão confirmada com o usuário). Assim a Necessidade de Empenho atualiza sozinha a cada
    reimportação de Execução Mensal, sem precisar tocar na planilha de Contratos Contínuos.
    Contrato sem NE, ou com NE ainda não encontrada na Execução carregada, mantém
    `meses_empenhados`/`meses_liquidados` da planilha (fallback inalterado) — `necessidade_via`
    (novo campo) marca "execucao" ou "planilha" conforme a fonte usada em cada linha, para a
    interface deixar isso visível.

    `indice_liquidado_competencia` (opcional, pedido explícito do usuário): quando informado
    (Série `ne_curta` -> total por Liquidação por Competência, ver
    `src.liquidacao_competencia.liquidado_por_ne` + `execucao_ne_utils.ne_curta`),
    `valor_liquidado_execucao` vem dele em vez da Execução Mensal (mês de LANÇAMENTO) — a
    Execução Mensal só sabe dizer quando a liquidação foi formalmente lançada, não a que mês a
    despesa se refere; a competência é a fonte mais correta para "quanto já foi de fato
    incorrido". NE sem nenhuma linha de competência fica nula em `valor_liquidado_execucao`
    (mesmo tratamento de "sem correspondência" de sempre — cai em `tem_base_para_calculo`
    abaixo, volta pros campos manuais da planilha, nunca usa o valor de lançamento como
    substituto silencioso) — EXCETO quando a Execução Mensal também não tem nenhuma liquidação
    para a NE (06/10/2026): aí as duas bases confirmam liquidado 0,00, gravado como zero e
    sinalizado em `sem_liquidacao_confirmada`. `None` (arquivo de competência indisponível) preserva o
    comportamento anterior a este pedido (Execução Mensal). `liquidado_via_competencia` (novo
    campo, booleano constante no resultado) sinaliza qual fonte foi usada, para a interface
    ajustar o rótulo mostrado.
    """
    resultado = df.copy()

    indice_saldo = indice_saldo_por_ne_curta(por_ne_execucao)
    resultado["saldo_execucao"] = resultado["ne_curta"].map(indice_saldo)
    resultado["diverge_saldo"] = _diverge(resultado["saldo_execucao"], resultado["saldo_colado_planilha"])

    indice_valor_empenhado = indice_valor_empenhado_por_ne_curta(por_ne_execucao)
    resultado["valor_empenhado_execucao"] = resultado["ne_curta"].map(indice_valor_empenhado)

    resultado["liquidado_via_competencia"] = indice_liquidado_competencia is not None
    indice_liquidado = indice_liquidado_por_ne_curta(por_ne_execucao)
    resultado["sem_liquidacao_confirmada"] = False
    if indice_liquidado_competencia is not None:
        resultado["valor_liquidado_execucao"] = resultado["ne_curta"].map(indice_liquidado_competencia)
        # NE na Execução sem NENHUMA liquidação lá (nula ou zero) e sem linha de competência: as duas
        # bases confirmam que nada foi liquidado — liquidado = 0,00 declarado (pedido de 06/10/2026: NE
        # recém-empenhada caía nos campos manuais e zerava a necessidade). Se a Execução tem liquidação e a
        # competência não, continua nulo (sem substituto silencioso pelo valor de lançamento).
        liquidado_lancamento = pd.to_numeric(resultado["ne_curta"].map(indice_liquidado), errors="coerce")
        sem_liquidacao = (
            resultado["valor_liquidado_execucao"].isna()
            & resultado["ne_curta"].map(indice_valor_empenhado).notna()
            & (liquidado_lancamento.isna() | (liquidado_lancamento.abs() < 0.005))
        )
        resultado.loc[sem_liquidacao, "valor_liquidado_execucao"] = 0.0
        resultado["sem_liquidacao_confirmada"] = sem_liquidacao.astype(bool)
    else:
        resultado["valor_liquidado_execucao"] = resultado["ne_curta"].map(indice_liquidado)

    soma_planilha_por_ne = resultado.dropna(subset=["ne_curta"]).groupby("ne_curta")["valor_empenhado"].sum()
    resultado["valor_empenhado_planilha_total_ne"] = resultado["ne_curta"].map(soma_planilha_por_ne)
    resultado["diverge_valor_empenhado"] = _diverge(
        resultado["valor_empenhado_execucao"], resultado["valor_empenhado_planilha_total_ne"]
    )

    soma_despesa_mensal_por_ne = resultado.dropna(subset=["ne_curta"]).groupby("ne_curta")["despesa_mensal"].sum()
    resultado["despesa_mensal_total_ne"] = resultado["ne_curta"].map(soma_despesa_mensal_por_ne)

    tem_base_para_calculo = (
        resultado["valor_empenhado_execucao"].notna()
        & resultado["valor_liquidado_execucao"].notna()
        & resultado["despesa_mensal_total_ne"].notna()
        & (resultado["despesa_mensal_total_ne"] != 0)
    )

    meses_empenhados_execucao = resultado["valor_empenhado_execucao"] / resultado["despesa_mensal_total_ne"]
    meses_liquidados_execucao = resultado["valor_liquidado_execucao"] / resultado["despesa_mensal_total_ne"]
    resultado["meses_empenhados_execucao"] = meses_empenhados_execucao.where(tem_base_para_calculo)
    resultado["meses_liquidados_execucao"] = meses_liquidados_execucao.where(tem_base_para_calculo)

    meses_a_empenhar_execucao, valor_a_empenhar_execucao = calcular_necessidade_empenho(
        meses_empenhados_execucao, meses_liquidados_execucao, resultado["despesa_mensal"]
    )
    resultado["meses_a_empenhar"] = resultado["meses_a_empenhar"].where(~tem_base_para_calculo, meses_a_empenhar_execucao)
    resultado["valor_a_empenhar"] = resultado["valor_a_empenhar"].where(~tem_base_para_calculo, valor_a_empenhar_execucao)
    resultado["necessidade_via"] = pd.Series("planilha", index=resultado.index).where(~tem_base_para_calculo, "execucao")

    return resultado


def com_meses_pagos(df: pd.DataFrame, meses_pagos: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta `meses_pagos`/`ultimo_mes_pago`, buscados na planilha de Pagamentos de
    Contratos (`src.contratos_pagamentos.meses_pagos_por_contrato`) via `contrato_numero`
    normalizado (`normalizar_numero_contrato`, aplicada aqui também para casar com o mesmo
    formato canônico) — indicador INDEPENDENTE de quantos meses tiveram pagamento
    efetivamente registrado e qual foi o mais recente, não uma correção de `meses_liquidados`
    (campo manual desta planilha): liquidação e pagamento são estágios orçamentários
    diferentes, este campo não substitui aquele.

    Contrato sem número reconhecível (`contrato_numero` vazio/fora do padrão "<número ou
    SN>/<ano>") ou sem correspondência na planilha de Pagamentos fica com os dois campos
    nulos — não é erro, é ausência de dado para comparar (mesmo critério de
    `com_saldo_execucao`).
    """
    resultado = df.copy()
    resultado["contrato_normalizado"] = resultado["contrato_numero"].apply(normalizar_numero_contrato)
    indexado = meses_pagos.set_index("contrato_normalizado")
    resultado["meses_pagos"] = resultado["contrato_normalizado"].map(indexado["meses_pagos"])
    resultado["ultimo_mes_pago"] = resultado["contrato_normalizado"].map(indexado["ultimo_mes_pago"])
    return resultado


#: origem da `despesa_anual` de cada linha depois de `com_efeitos_da_suspensao`.
DESPESA_CONTRATUAL = "Contratual (despesa mensal × meses no ano)"
DESPESA_EMPENHADO_SUSPENSO = "Empenhado (contrato suspenso)"


def com_efeitos_da_suspensao(df: pd.DataFrame) -> pd.DataFrame:
    """Contrato SUSPENSO só produz efeito pelo que já foi empenhado e liquidado (pedido explícito,
    06/10/2026: "os contratos suspensos parem de fazer efeito após a suspensão. Só devem fazer efeito
    os valores de empenho e liquidação já computados"). Para essas linhas:

      * `despesa_anual` (Despesa anual e Cobertura Orçamentária por PTRES) passa a ser o valor JÁ
        EMPENHADO — o da Execução Mensal (`valor_empenhado_execucao`) quando a NE foi encontrada nela,
        senão o `valor_empenhado` do cadastro (decisão do usuário, 06/10/2026). NE compartilhada por
        mais de uma linha usa o valor do cadastro, para não contar o empenho da NE inteira em cada
        linha (nenhum rateio é presumido). Empenhado nulo continua nulo, nunca vira zero.
      * `meses_a_empenhar`/`valor_a_empenhar` ("Saldo a liquidar (execução)" no cartão-resumo) viram zero declarado: não se
        pede reforço para contrato parado. Saldo, empenhado e liquidado não mudam.

    A despesa contratual original fica em `despesa_anual_contratual` e a origem do valor em
    `despesa_anual_base`, para reconciliação. Precisa de `com_saldo_execucao` antes (usa
    `valor_empenhado_execucao`); sem essa coluna, usa só o cadastro. Não altera a entrada."""

    resultado = df.copy()
    status = resultado["status_contrato"].astype("string").str.strip().str.upper()
    suspenso = status.eq(STATUS_SUSPENSO).fillna(False).astype(bool)

    ne = resultado["ne_curta"]
    compartilhada = (ne.notna() & ne.duplicated(keep=False)).astype(bool)
    if "valor_empenhado_execucao" in resultado.columns:
        execucao = pd.to_numeric(resultado["valor_empenhado_execucao"], errors="coerce").where(~compartilhada)
    else:
        execucao = pd.Series(float("nan"), index=resultado.index)
    empenhado = execucao.fillna(pd.to_numeric(resultado["valor_empenhado"], errors="coerce"))

    resultado["despesa_anual_contratual"] = resultado["despesa_anual"]
    resultado["despesa_anual"] = resultado["despesa_anual"].where(~suspenso, empenhado)
    resultado["despesa_anual_base"] = pd.Series(DESPESA_CONTRATUAL, index=resultado.index).where(
        ~suspenso, DESPESA_EMPENHADO_SUSPENSO
    )
    resultado["meses_a_empenhar"] = resultado["meses_a_empenhar"].where(~suspenso, 0.0)
    resultado["valor_a_empenhar"] = resultado["valor_a_empenhar"].where(~suspenso, 0.0)
    return resultado


SITUACAO_VENCIDO = "Vencido"
SITUACAO_SUSPENSO = "Suspenso"
SITUACAO_VIGENCIA_ENCERRADA = "Vigência encerrada"
SITUACAO_NECESSITA_REFORCO = "Necessita reforço"
SITUACAO_ATIVO = "Ativo"


def situacao_contrato(status: object, vigencia_fim_efetiva: object, necessidade: object, hoje: date) -> tuple[str, str]:
    """(texto, tom) da situação no Registro de contratos (06/10/2026), nesta ordem: status VENCIDO ou
    SUSPENSO do cadastro; vigência efetiva (com aditivos) já encerrada em `hoje` com outro status →
    "Vigência encerrada" (a data é do próprio cadastro; o status não é alterado); Necessidade até
    dezembro (`necessidade_por_linha`) > 0 → "Necessita reforço"; senão "Ativo". Antes o reforço era
    lido do saldo (empenhado − liquidado), o que marcava contrato com saldo e escondia o sem saldo.
    Status fora da lista conta como ATIVO; necessidade nula não pede reforço (sem dado)."""

    status_texto = None if status is None or pd.isna(status) else str(status).strip().upper()
    if status_texto == STATUS_VENCIDO:
        return SITUACAO_VENCIDO, "bad"
    if status_texto == STATUS_SUSPENSO:
        return SITUACAO_SUSPENSO, "neutro"
    if vigencia_fim_efetiva is not None and not pd.isna(vigencia_fim_efetiva):
        if pd.Timestamp(vigencia_fim_efetiva).date() < hoje:
            return SITUACAO_VIGENCIA_ENCERRADA, "bad"
    if necessidade is not None and not pd.isna(necessidade) and float(necessidade) > 0.005:
        return SITUACAO_NECESSITA_REFORCO, "warn"
    return SITUACAO_ATIVO, "ok"
