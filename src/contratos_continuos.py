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
    com_contratosgov(df, contratos, termos, empenhos) -> pd.DataFrame   (ligação/conciliação com o gov)
    candidatos_novos(df, contratos, empenhos) -> (candidatos, em_duvida)   (contratos do gov ausentes)
    registro_novo_do_gov(candidato, ne=None) -> dict   (argumentos de `novo_contrato`)
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd

from src.cache_bases import em_cache
from src.leitura_excel import motor_excel

from src.contratos_aditivos import Aditivo
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


# ---------------------------------------------------------------------------------------------
# Integração com o Contratos.gov.br (10/2026): ligação por NE (depois número + CNPJ/CPF),
# conciliação de vigência e contagem de termos. Funções puras, em memória: recebem as tabelas
# derivadas de `src.contratos_cadastro` (`contratos`, `termos`, `empenhos`) e nunca alteram a
# fotografia do gov nem o cadastro.
# ---------------------------------------------------------------------------------------------

SITUACOES_CONCILIACAO = (
    "conciliado", "divergente", "sem_par_no_contratosgov", "conflito", "sem_data_para_comparar",
)

#: `tipo` do termo no Contratos.gov.br que conta como aditivo (apostilamento, rescisão etc. não).
TIPO_TERMO_ADITIVO = "Termo Aditivo"

_COLUNAS_CONTRATOSGOV = (
    "contratosgov_id", "ligacao_por", "situacao_conciliacao", "situacao_vigencia_gov",
    "vigencia_fim_contratosgov", "diverge_vigencia", "qtd_termos", "qtd_aditivos_gov",
    "qtd_aditivos_pendentes", "valor_parcela_contratosgov",
)


def _so_digitos(valor: object) -> str | None:
    """CNPJ/CPF só com dígitos (zeros à esquerda preservados), para comparar com o do gov; nulo ou
    sem dígito → `None`."""

    if valor is None or pd.isna(valor):
        return None
    digitos = re.sub(r"\D", "", str(valor))
    return digitos or None


def _ne_normalizada(valor: object) -> str | None:
    if valor is None or pd.isna(valor):
        return None
    texto = str(valor).strip().upper()
    return texto or None


def _resolver_ligacoes(df: pd.DataFrame, contratos: pd.DataFrame, empenhos: pd.DataFrame) -> pd.DataFrame:
    """Liga cada linha do cadastro a um contrato do gov. Ordem: (a) `ne_curta` ∈ `empenhos.ne`;
    (b) número normalizado (`normalizar_numero_contrato`) + CNPJ/CPF iguais (só dígitos). NE nula não
    casa com nada, e número sem CNPJ/CPF não liga (nunca presumir). Devolve, alinhado a `df.index`:
    `contratosgov_id` (`None` sem par ou em conflito), `ligacao_por` ("ne"/"numero"/`None`),
    `conflito` (bool) e `envolvidos` (conjunto de `contrato_id` do gov citados no conflito).
    Conflito: NE em mais de um contrato, número+CNPJ ambíguo no gov, ou NE e número apontando
    contratos diferentes — nada do gov é aplicado nesses casos."""

    por_ne: dict[str, set[str]] = {}
    for ne, contrato_id in zip(empenhos["ne"], empenhos["contrato_id"]):
        chave = _ne_normalizada(ne)
        if chave:
            por_ne.setdefault(chave, set()).add(str(contrato_id))

    por_numero: dict[tuple[str, str], set[str]] = {}
    for contrato_id, numero, documento in zip(
        contratos["contrato_id"], contratos["numero"], contratos["fornecedor_documento"]
    ):
        numero_norm, documento_norm = normalizar_numero_contrato(numero), _so_digitos(documento)
        if numero_norm and documento_norm:
            por_numero.setdefault((numero_norm, documento_norm), set()).add(str(contrato_id))

    linhas = []
    for ne_curta, numero, documento in zip(df["ne_curta"], df["contrato_numero"], df["fornecedor_cnpj_cpf"]):
        ne = _ne_normalizada(ne_curta)
        numero_norm, documento_norm = normalizar_numero_contrato(numero), _so_digitos(documento)
        cand_ne = por_ne.get(ne, set()) if ne else set()
        cand_numero = por_numero.get((numero_norm, documento_norm), set()) if numero_norm and documento_norm else set()

        contrato_id, ligacao, envolvidos = None, None, frozenset()
        if cand_ne:
            if len(cand_ne) > 1 or (cand_numero and cand_numero != cand_ne):
                envolvidos = frozenset(cand_ne | cand_numero)
            else:
                contrato_id, ligacao = next(iter(cand_ne)), "ne"
        elif cand_numero:
            if len(cand_numero) > 1:
                envolvidos = frozenset(cand_numero)
            else:
                contrato_id, ligacao = next(iter(cand_numero)), "numero"
        linhas.append(
            {"contratosgov_id": contrato_id, "ligacao_por": ligacao, "conflito": bool(envolvidos), "envolvidos": envolvidos}
        )
    return pd.DataFrame(linhas, index=df.index, columns=["contratosgov_id", "ligacao_por", "conflito", "envolvidos"])


def com_contratosgov(
    df: pd.DataFrame, contratos: pd.DataFrame, termos: pd.DataFrame, empenhos: pd.DataFrame
) -> pd.DataFrame:
    """Acrescenta ao cadastro de Contínuos (`como_dataframe`) a ligação com o Contratos.gov.br e a
    conciliação de vigência — mesma granularidade e valores originais de `df`, nada é alterado.

    Ligação em `_resolver_ligacoes` (NE primeiro; vários registros — uma NE cada — podem ligar ao
    mesmo contrato do gov). Campos: `contratosgov_id`, `ligacao_por`, `situacao_vigencia_gov`
    (a do gov, calculada pelas datas — a `situacao` da API não é confiável), `vigencia_fim_contratosgov`
    (`date`), `qtd_termos`, `qtd_aditivos_gov` (só `tipo == "Termo Aditivo"`),
    `valor_parcela_contratosgov` (REFERÊNCIA: o gov traz o contrato inteiro, Contínuos traz a parcela da
    ação 20RK — nunca comparado) e `situacao_conciliacao` ∈ `SITUACOES_CONCILIACAO`.

    Vigência: `vigencia_fim_efetiva` do cadastro (já com os aditivos nativos) contra `vigencia_fim` do gov,
    igualdade exata de data em `diverge_vigencia` (`boolean`). Data nula em qualquer lado →
    "sem_data_para_comparar" e `diverge_vigencia` nulo — ausência de dado nunca vira divergência. Sem par
    ou em conflito, os campos do gov ficam nulos."""

    resultado = df.copy()
    ligacoes = _resolver_ligacoes(df, contratos, empenhos)

    gov = contratos.assign(contrato_id=contratos["contrato_id"].astype(str)).set_index("contrato_id")
    termos_por_contrato = termos.assign(contrato_id=termos["contrato_id"].astype(str)).groupby("contrato_id")
    qtd_termos = termos_por_contrato.size()
    qtd_aditivos = termos[termos["tipo"] == TIPO_TERMO_ADITIVO].assign(
        contrato_id=lambda t: t["contrato_id"].astype(str)
    ).groupby("contrato_id").size()

    vigencia_cadastro = pd.to_datetime(
        resultado["vigencia_fim_efetiva"] if "vigencia_fim_efetiva" in resultado.columns else resultado["vigencia_fim"],
        errors="coerce",
    )

    aditivos_nativos = resultado["aditivos"] if "aditivos" in resultado.columns else pd.Series([[]] * len(resultado), index=resultado.index)

    saidas: dict[str, list] = {coluna: [] for coluna in _COLUNAS_CONTRATOSGOV}
    for (_, ligacao), vigencia, aditivos in zip(ligacoes.iterrows(), vigencia_cadastro, aditivos_nativos):
        contrato_id = ligacao["contratosgov_id"]
        if contrato_id is None or pd.isna(contrato_id):  # `iterrows` troca None por NaN
            situacao = "conflito" if ligacao["conflito"] else "sem_par_no_contratosgov"
            valores = dict.fromkeys(_COLUNAS_CONTRATOSGOV, pd.NA)
            valores.update(situacao_conciliacao=situacao)
        else:
            contrato = gov.loc[contrato_id]
            fim_gov = contrato["vigencia_fim"]
            fim_gov = pd.NA if fim_gov is None or pd.isna(fim_gov) else fim_gov
            diverge = pd.NA
            if pd.isna(fim_gov) or pd.isna(vigencia):
                situacao = "sem_data_para_comparar"
            else:
                diverge = bool(vigencia.date() != fim_gov)
                situacao = "divergente" if diverge else "conciliado"
            parcela = contrato["valor_parcela"]
            valores = {
                "contratosgov_id": contrato_id,
                "ligacao_por": ligacao["ligacao_por"],
                "situacao_conciliacao": situacao,
                "situacao_vigencia_gov": contrato["situacao_vigencia"],
                "vigencia_fim_contratosgov": fim_gov,
                "diverge_vigencia": diverge,
                "qtd_termos": int(qtd_termos.get(contrato_id, 0)),
                "qtd_aditivos_gov": int(qtd_aditivos.get(contrato_id, 0)),
                "qtd_aditivos_pendentes": len(
                    aditivos_pendentes(aditivos, termos[termos["contrato_id"].astype(str) == contrato_id])
                ),
                "valor_parcela_contratosgov": pd.NA if parcela is None or pd.isna(parcela) else float(parcela),
            }
        for coluna in _COLUNAS_CONTRATOSGOV:
            saidas[coluna].append(valores[coluna])

    resultado["contratosgov_id"] = pd.array(saidas["contratosgov_id"], dtype="string")
    resultado["ligacao_por"] = pd.array(saidas["ligacao_por"], dtype="string")
    resultado["situacao_conciliacao"] = pd.array(saidas["situacao_conciliacao"], dtype="string")
    resultado["situacao_vigencia_gov"] = pd.array(saidas["situacao_vigencia_gov"], dtype="string")
    resultado["vigencia_fim_contratosgov"] = pd.Series(saidas["vigencia_fim_contratosgov"], index=resultado.index, dtype=object)
    resultado["diverge_vigencia"] = pd.array(saidas["diverge_vigencia"], dtype="boolean")
    resultado["qtd_termos"] = pd.array(saidas["qtd_termos"], dtype="Int64")
    resultado["qtd_aditivos_gov"] = pd.array(saidas["qtd_aditivos_gov"], dtype="Int64")
    resultado["qtd_aditivos_pendentes"] = pd.array(saidas["qtd_aditivos_pendentes"], dtype="Int64")
    resultado["valor_parcela_contratosgov"] = pd.array(saidas["valor_parcela_contratosgov"], dtype="Float64")
    return resultado


def tipo_aditivo_por_qualificacao(qualificacao: object) -> str:
    """Tipo do aditivo nativo (`src.contratos_aditivos.TIPOS`) sugerido pela `qualificacao_termo` do gov
    ("VIGÊNCIA; REAJUSTE"): REAJUSTE se houver reajuste (muda o valor); senão PRORROGACAO se houver
    vigência; senão ACRESCIMO_SUPRESSAO; senão OUTRO (inclui só "INFORMATIVO" e vazio). Um termo com
    várias qualificações vira UM aditivo — é só sugestão, o usuário ajusta antes de salvar."""

    texto = _normalizar(qualificacao)
    if "REAJUSTE" in texto:
        return "REAJUSTE"
    if "VIGENCIA" in texto:
        return "PRORROGACAO"
    if "ACRESCIMO" in texto:
        return "ACRESCIMO_SUPRESSAO"
    return "OUTRO"


def _data_ou_none(valor: object) -> date | None:
    if valor is None or pd.isna(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.date()
    return valor


def _chave_numero_termo(numero: object) -> str:
    """Forma comparável do número de um termo/aditivo: `normalizar_numero_contrato` quando o texto segue
    "<número>/<ano>" ("00001/2022" == "1/2022"); senão o texto aparado em maiúsculas (o número do
    aditivo nativo é texto livre)."""

    normalizado = normalizar_numero_contrato(numero)
    if normalizado:
        return normalizado
    return "" if numero is None or pd.isna(numero) else str(numero).strip().upper()


def aditivos_pendentes(aditivos: list[Aditivo], termos_do_contrato: pd.DataFrame) -> pd.DataFrame:
    """Termos aditivos do gov (só `tipo == "Termo Aditivo"` — apostilamento, rescisão e o próprio
    contrato nunca contam) que não têm aditivo nativo correspondente. Um termo está REGISTRADO se algum
    aditivo nativo tem o mesmo número (`_chave_numero_termo`) ou a mesma `data_assinatura`. O casamento é
    heurístico (número nativo é texto livre): serve para SUGERIR o registro, nunca para gravar sozinho."""

    do_gov = termos_do_contrato[termos_do_contrato["tipo"] == TIPO_TERMO_ADITIVO]
    numeros = {_chave_numero_termo(a.numero) for a in aditivos}
    datas = {a.data_assinatura for a in aditivos if a.data_assinatura is not None}
    registrado = [
        _chave_numero_termo(numero) in numeros or _data_ou_none(assinatura) in datas
        for numero, assinatura in zip(do_gov["numero"], do_gov["data_assinatura"])
    ]
    return do_gov[[not r for r in registrado]]


def aditivo_sugerido(termo: pd.Series) -> Aditivo:
    """Aditivo nativo sugerido a partir de um termo aditivo do gov: `tipo` por qualificação, situação
    ASSINADO, `data_inicio` = `data_inicio_novo_valor` (senão `data_assinatura`; nula se nenhuma das duas —
    `validar_aditivos` recusa ao salvar, o usuário preenche), `vigencia_fim` do termo. `valor_mensal`
    SEMPRE nulo: a parcela do gov é do contrato inteiro, Contínuos traz só a parcela da ação 20RK."""

    assinatura = _data_ou_none(termo["data_assinatura"])
    inicio = _data_ou_none(termo["data_inicio_novo_valor"]) or assinatura
    return Aditivo(
        numero=str(termo["numero"]),
        tipo=tipo_aditivo_por_qualificacao(termo["qualificacao_termo"]),
        situacao="ASSINADO",
        data_inicio=inicio,
        data_assinatura=assinatura,
        valor_mensal=None,
        vigencia_fim=_data_ou_none(termo["vigencia_fim"]),
        itens=None,
    )


def numero_no_formato_continuos(numero_gov: object) -> str | None:
    """Número do contrato do gov ("00013/2026") no formato usado no cadastro de Contínuos ("13/2026"; ao
    menos 2 dígitos no número: "00002/2026" → "02/2026"). Texto fora do padrão "<número>/<ano>" volta como
    veio, aparado; nulo → `None`. É só uma convenção de apresentação: o usuário edita na janela."""

    if numero_gov is None or pd.isna(numero_gov):
        return None
    normalizado = normalizar_numero_contrato(numero_gov)
    if normalizado is None:
        return str(numero_gov).strip() or None
    parte_numero, _, parte_ano = normalizado.partition("/")
    return f"{parte_numero.zfill(2) if parte_numero.isdigit() else parte_numero}/{parte_ano}"


_COLUNAS_CANDIDATO = (
    "contrato_id", "numero", "ano_contrato", "fornecedor_nome", "fornecedor_documento", "objeto", "categoria",
    "vigencia_fim", "situacao_vigencia", "valor_parcela", "nes", "motivo",
)


def candidatos_novos(
    df: pd.DataFrame, contratos: pd.DataFrame, empenhos: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Contratos do Contratos.gov.br ainda sem registro no cadastro de Contínuos em tela (mesma ligação de
    `com_contratosgov`; um contrato ligado por qualquer registro — inclusive vários, uma NE cada — não
    aparece). Devolve `(candidatos, em_duvida)`:

    * candidato: `situacao_vigencia` "vigente" ou "a_iniciar" (decisão do usuário: todos os vigentes ausentes
      — o gov não tem o campo "contínuo");
    * em dúvida: "sem_vigencia" (sem datas) e todo contrato citado num conflito de ligação (NE e número
      apontando contratos diferentes etc.) — sem botão de inclusão, com o `motivo`.

    Encerrados e inativos ficam de fora. Ordenado por `vigencia_fim` crescente. `nes` traz, por contrato, a
    lista de `{"ne", "natureza_despesa", "plano_interno", "fonte_recurso"}` com os textos do gov. O
    `valor_parcela` é só referência (contrato inteiro; Contínuos traz a parcela da ação 20RK)."""

    ligacoes = _resolver_ligacoes(df, contratos, empenhos)
    ligados = {str(i) for i in ligacoes["contratosgov_id"].dropna()}
    em_conflito = set().union(*ligacoes["envolvidos"]) if len(ligacoes) else set()

    nes_por_contrato: dict[str, list[dict]] = {}
    for registro in empenhos.to_dict("records"):
        nes_por_contrato.setdefault(str(registro["contrato_id"]), []).append(
            {chave: registro[chave] for chave in ("ne", "natureza_despesa", "plano_interno", "fonte_recurso")}
        )

    candidatos, em_duvida = [], []
    for contrato in contratos.to_dict("records"):
        contrato_id = str(contrato["contrato_id"])
        if contrato_id in ligados:
            continue
        situacao = contrato["situacao_vigencia"]
        if contrato_id in em_conflito:
            motivo, destino = "conflito de ligação: NE e número/CNPJ apontam contratos diferentes", em_duvida
        elif situacao == "sem_vigencia":
            motivo, destino = "sem vigência no Contratos.gov", em_duvida
        elif situacao in ("vigente", "a_iniciar"):
            motivo = f"{'vigente' if situacao == 'vigente' else 'a iniciar'} no Contratos.gov, ausente do cadastro"
            destino = candidatos
        else:
            continue
        fim = contrato["vigencia_fim"]
        destino.append(
            {
                "contrato_id": contrato_id,
                "numero": contrato["numero"],
                "ano_contrato": contrato["ano_contrato"],
                "fornecedor_nome": contrato["fornecedor_nome"],
                "fornecedor_documento": contrato["fornecedor_documento"],
                "objeto": contrato["objeto"],
                "categoria": contrato["categoria"],
                "vigencia_fim": None if fim is None or pd.isna(fim) else fim,
                "situacao_vigencia": situacao,
                "valor_parcela": contrato["valor_parcela"],
                "nes": nes_por_contrato.get(contrato_id, []),
                "motivo": motivo,
            }
        )

    def _montar(linhas: list[dict]) -> pd.DataFrame:
        linhas = sorted(linhas, key=lambda l: (l["vigencia_fim"] is None, l["vigencia_fim"] or date.max))
        return pd.DataFrame(linhas, columns=list(_COLUNAS_CANDIDATO)).reset_index(drop=True)

    return _montar(candidatos), _montar(em_duvida)


def _codigo_antes_do_hifen(texto: object) -> str | None:
    """Código de "339039 - OUTROS SERVICOS..." / "M20RKG01SCN - GESTAO..." (texto antes de " - ");
    sem hífen, o texto inteiro ("1000000000"). Sempre texto, zeros preservados; nulo/vazio → `None`."""

    if texto is None or pd.isna(texto):
        return None
    codigo = str(texto).split(" - ", 1)[0].strip()
    return codigo or None


def registro_novo_do_gov(candidato: pd.Series, ne: str | None = None) -> dict:
    """Argumentos de `src.contratos_continuos_cadastro.novo_contrato` para incluir um candidato de
    `candidatos_novos`, só com o que o Contratos.gov tem: número (`numero_no_formato_continuos`), ano,
    fornecedor, CNPJ/CPF (texto, como veio), `vigencia_fim`, status ATIVO e — se `ne` for informada —
    NE, natureza de despesa, plano interno e fonte dessa NE. Ação, PTRES, UGR, despesa mensal e meses não
    existem no gov: ficam fora (nulos, nunca zero). NE que não pertence ao contrato levanta `ValueError`."""

    selecionada = None
    if ne is not None:
        chave = _ne_normalizada(ne)
        selecionada = next((n for n in candidato["nes"] if _ne_normalizada(n["ne"]) == chave), None)
        if selecionada is None:
            raise ValueError(f"A NE {ne!r} não pertence ao contrato {candidato['numero']} do Contratos.gov.")

    fim = candidato["vigencia_fim"]
    ano = candidato["ano_contrato"]
    return {
        "contrato_numero": numero_no_formato_continuos(candidato["numero"]),
        "ano_contrato": None if ano is None or pd.isna(ano) else int(ano),
        "fornecedor": candidato["fornecedor_nome"],
        "fornecedor_cnpj_cpf": candidato["fornecedor_documento"],
        "vigencia_fim": None if fim is None or pd.isna(fim) else pd.Timestamp(fim),
        "status_contrato": "ATIVO",
        "ne_curta": None if selecionada is None else selecionada["ne"],
        "natureza_despesa_cod": None if selecionada is None else _codigo_antes_do_hifen(selecionada["natureza_despesa"]),
        "pi_cod": None if selecionada is None else _codigo_antes_do_hifen(selecionada["plano_interno"]),
        "fonte_cod": None if selecionada is None else _codigo_antes_do_hifen(selecionada["fonte_recurso"]),
    }
