"""
Cadastro nativo, multi-exercício, de Contratos Contínuos — substitui a leitura de planilha
(`src.contratos_continuos.ler_contratos_continuos`) como fonte de dados de
`app_pages/contratos_continuos.py` (mesmo pedido explícito de desvinculação de planilha já
atendido para Bolsas e Auxílios, ver `src/bolsas_auxilios_cadastro.py`).

GRANULARIDADE (pedido explícito de correção, decisão de negócio confirmada com o usuário):
um registro é um CONTRATO/NE inteiro, não um item de licitação — diferente da planilha de
origem (uma linha por contrato × item) e diferente da primeira versão deste módulo. Motivo:
no SIAFI, o reforço de empenho é feito por item de licitação, mas a LIQUIDAÇÃO não é dividida
por item — ela acontece no nível da NE inteira. Saldo, status, liquidado são conceitos da NE,
não do item; manter um registro por item duplicava esses campos em vários "cartões" que
precisavam ser editados em sincronia (editar o saldo do Item 1 não atualizava o Item 2do mesmo
contrato — risco real de inconsistência). O item de licitação não é uma entidade própria: é só
a forma de ratear o valor mensal do contrato inteiro entre os itens, para saber quando o teto
de cada um se esgota e precisa de reforço — por isso mora dentro do cadastro do contrato como
uma lista de percentuais (`itens`), e só "aparece" (vira linha própria) na hora de montar o
Relatório de Reforço de Empenho (`src.relatorio_reforco_empenho.linhas_para_processo`), nunca
nas telas de cartão/Resumo Consolidado/Empenhado × Liquidado (que continuam 1 linha por
contrato).

Constrói em cima do motor genérico `src.cadastro_por_exercicio` (persistência em disco, um JSON
por registro, agrupado por exercício em `data/contratos_continuos/<ano>/`). `despesa_mensal`
agora é o valor mensal do CONTRATO INTEIRO (soma do que a planilha trazia por item) — os itens
(`itens`, lista de `{"numero": int, "percentual": float}`, os percentuais somando 100) ratream
esse total na hora do relatório: `valor_mensal_do_item = despesa_mensal × percentual ÷ 100`.
"Duplicar cadastro" copia o contrato inteiro, itens incluídos (identidade/classificação, não
execução).

`meses_no_ano` (pedido explícito, mesmo campo/motivo de `src.bolsas_auxilios_cadastro`): total
de meses que o contrato é pago no exercício — a maioria é 12 (contrato "contínuo" de verdade),
mas um contrato que só roda parte do ano (ex.: iniciado no meio do exercício, ou com vigência
menor que 12 meses) tem menos. Usado em `despesa_anual` (abaixo) e na sugestão "por calendário"
do Relatório de Reforço (`src.necessidade_empenho.necessidade_ate_mes_vigente`) — sem ele
(registro anterior a esta correção), cai no padrão de 12, idêntico ao comportamento de antes.

`meses_pagos`/`ultimo_mes_pago` (`src.contratos_pagamentos`) continuam vindo de uma planilha
separada, cruzada por número de contrato em tempo de render (`com_meses_pagos`) — fora do
escopo desta desvinculação.

`como_dataframe` devolve o mesmo esquema de colunas que
`src.contratos_continuos.ler_contratos_continuos` produzia (menos `meses_de_saldo`/
`item_licitacao`/`item_percentual`, substituídos por `itens`) — o resto do pipeline da página
(`com_saldo_execucao`, `com_meses_pagos`, Resumo Consolidado, Empenhado × Liquidado, Cobertura
Orçamentária) já operava por NE via `groupby` (um contrato podia ter várias linhas antes) —
com 1 linha por NE de cada vez, esse `groupby` vira um no-op inofensivo, nenhuma mudança
precisou ser feita ali.

Migração única (`migrar_de_planilha`): lê a planilha antiga (uma linha por item) e AGRUPA por
NE (ou por número de contrato, para contratos ainda sem NE) — `despesa_mensal`/`valor_empenhado`
somados entre os itens do grupo (cada item trazia sua própria fração), os demais campos de
identidade/execução (já repetidos idênticos em cada linha de item na origem) tirados do
primeiro item do grupo. `item_percentual` de cada item vira `itens`; quando ausente na origem,
recalculado a partir da fração de `despesa_mensal` de cada item sobre o total do grupo.

Contrato público:
    novo_contrato(**campos) -> dict
    salvar_contrato(ano, contrato) -> Path
    atualizar_contrato(ano, contrato) -> Path
    excluir_contrato(ano, id) -> None
    carregar_contratos(ano) -> list[dict]
    como_dataframe(contratos, exercicio=None, *, hoje=None) -> pd.DataFrame
    anos_disponiveis() -> list[int]
    duplicar_exercicio(ano_origem, ano_destino) -> list[dict]
    migrar_de_planilha(caminho, ano, *, diretorio_base=None) -> list[dict]
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.cadastro_por_exercicio import (
    anos_disponiveis as _anos_disponiveis,
    atualizar as _atualizar,
    carregar_registros,
    duplicar_exercicio as _duplicar_exercicio,
    excluir as _excluir,
    excluir_exercicio as _excluir_exercicio,
    novo_registro,
    salvar as _salvar,
)
from src.contratos_aditivos import (
    aditivos_do_registro,
    meses_com_previsto,
    serie_valor_mensal,
    valor_vigente_em,
    vigencia_efetiva,
)
from src.contratos_continuos import ler_contratos_continuos
from src.necessidade_empenho import calcular_necessidade_empenho

DIRETORIO_PADRAO = Path("data/contratos_continuos")

#: item padrão de um contrato novo — um item só, 100% do valor mensal.
ITEM_UNICO_PADRAO = [{"numero": 1, "percentual": 100.0}]

#: copiados ao duplicar um exercício — classificação/identidade do contrato, não execução
#: (`itens` inclusos: é composição do contrato, não dado de saldo/liquidação).
CAMPOS_IDENTIDADE = [
    "ano_contrato", "contrato_numero", "processo_contratacao", "processo_empenho", "fornecedor",
    "tipo_contrato", "tipo_despesa", "fornecedor_cnpj_cpf", "vigencia_fim", "unidade_cod",
    "acao_cod", "ptres", "fonte_cod", "natureza_despesa_cod", "ugr_cod", "pi_cod",
    "despesa_mensal", "meses_no_ano", "itens", "aditivos",
]

#: em branco/zerados no exercício novo — o vínculo com a Execução Anual se refaz quando o
#: usuário digitar o novo número de empenho (`ne_curta`) daquele exercício. `inicio_execucao_mes`
#: (1-12, opcional) é o mês do primeiro empenho daquela NE — auto-detectado a partir da base
#: mensal quando ausente (ver `src.tesouro_execucao_mensal.primeiro_mes_com_empenho_por_ne`),
#: editável pelo usuário se perceber um erro na detecção; usado só na sugestão inicial do
#: Relatório de Reforço (`src.necessidade_empenho.necessidade_ate_mes_vigente`).
CAMPOS_EXECUCAO_PADRAO = {
    "ne_curta": None,
    "valor_empenhado": 0.0,
    "saldo_colado_planilha": 0.0,
    "status_contrato": "ATIVO",
    "meses_empenhados": 0.0,
    "meses_liquidados": 0.0,
    "inicio_execucao_mes": None,
    #: início da execução por DATA (opcional, pedido explícito 02/10/2026): permite o primeiro mês
    #: proporcional na necessidade de empenho. Por exercício (execução), como `inicio_execucao_mes`;
    #: manda sobre o mês quando informada. Vazio = nulo, nunca presumido.
    "inicio_execucao_data": None,
    #: data da suspensão (opcional, pedido explícito 06/10/2026): com o status SUSPENSO, o contrato
    #: deixa de produzir efeito (necessidade, projeção, sugestão de reforço) a partir dela; sem ela,
    #: SUSPENSO vale para o exercício inteiro. Por exercício (execução), como o status. Vazio = nulo.
    "data_suspensao": None,
}

_COLUNAS_TEXTO = [
    "contrato_numero", "processo_contratacao", "processo_empenho", "fornecedor", "tipo_contrato",
    "tipo_despesa", "fornecedor_cnpj_cpf", "status_contrato", "unidade_cod", "acao_cod", "ptres",
    "fonte_cod", "natureza_despesa_cod", "ugr_cod", "pi_cod", "ne_curta",
]
_COLUNAS_NUMERICAS = [
    "ano_contrato", "despesa_mensal", "meses_no_ano", "valor_empenhado", "saldo_colado_planilha",
    "meses_empenhados", "meses_liquidados", "inicio_execucao_mes",
]
_COLUNAS_VAZIAS = [
    "id", *_COLUNAS_TEXTO, *_COLUNAS_NUMERICAS, "vigencia_fim", "inicio_execucao_data", "data_suspensao", "itens", "tem_varios_itens",
    "aditivos", "vigencia_fim_efetiva", "valor_mensal_vigente", "tem_aditivo_previsto",
    "despesa_anual", "meses_a_empenhar", "valor_a_empenhar",
]


def novo_contrato(**campos: object) -> dict:
    """Monta um registro novo (ainda não gravado — ver `salvar_contrato`). Campo de identidade
    não informado fica `None` (`itens` usa `ITEM_UNICO_PADRAO` — um item só, 100%); campo de
    execução não informado usa o padrão de exercício novo (`CAMPOS_EXECUCAO_PADRAO`, ex.:
    status "ATIVO")."""

    base = {chave: None for chave in CAMPOS_IDENTIDADE}
    base["itens"] = list(ITEM_UNICO_PADRAO)
    base.update(CAMPOS_EXECUCAO_PADRAO)
    base.update({chave: valor for chave, valor in campos.items() if chave in base})
    return novo_registro(**base)


def salvar_contrato(ano: int, contrato: dict) -> Path:
    return _salvar(DIRETORIO_PADRAO, ano, contrato)


def atualizar_contrato(ano: int, contrato: dict) -> Path:
    return _atualizar(DIRETORIO_PADRAO, ano, contrato)


def excluir_contrato(ano: int, identificador: str) -> None:
    _excluir(DIRETORIO_PADRAO, ano, identificador)


def carregar_contratos(ano: int) -> list[dict]:
    return carregar_registros(DIRETORIO_PADRAO, ano)


def anos_disponiveis() -> list[int]:
    return _anos_disponiveis(DIRETORIO_PADRAO)


def excluir_exercicio(ano: int) -> None:
    _excluir_exercicio(DIRETORIO_PADRAO, ano)


def _itens_validos(valor: object) -> list[dict]:
    if isinstance(valor, list) and valor:
        return valor
    return list(ITEM_UNICO_PADRAO)


def _dia_de_referencia(exercicio: int | None, hoje: date | None) -> date:
    """"Hoje" limitado ao exercício: hoje se está nele, 31/12 se o exercício já passou, 01/01 se ainda
    não começou. Sem exercício, hoje."""

    hoje = hoje or date.today()
    if exercicio is None:
        return hoje
    if hoje.year > exercicio:
        return date(exercicio, 12, 31)
    if hoje.year < exercicio:
        return date(exercicio, 1, 1)
    return hoje


def _despesa_anual(despesa_mensal: object, aditivos: list, exercicio: int, meses_no_ano: object) -> float:
    """Soma dos `meses_no_ano` primeiros meses (12 se vazio; fração no último, e meses além de 12 pelo valor
    de dezembro) da série mensal do exercício, sem corte de vigência/início — como a conta antiga. Despesa
    mensal nula continua nula."""

    serie = serie_valor_mensal(despesa_mensal, aditivos, exercicio)
    meses = 12.0 if pd.isna(meses_no_ano) else float(meses_no_ano)
    total = 0.0
    for indice in range(12):
        parte = min(1.0, max(0.0, meses - indice))
        if parte > 0:
            total += serie[indice] * parte
    if meses > 12:
        total += serie[11] * (meses - 12)
    return total


def como_dataframe(contratos: list[dict], exercicio: int | None = None, *, hoje: date | None = None) -> pd.DataFrame:
    """Mesmo esquema de colunas de `src.contratos_continuos.ler_contratos_continuos` (ver
    docstring do módulo, menos `item_licitacao`/`item_percentual`, substituídos por `itens`) —
    `despesa_anual`/`meses_a_empenhar`/`valor_a_empenhar` recalculados aqui (nunca gravados no
    registro: são sempre derivados de despesa mensal/meses)."""

    if not contratos:
        return pd.DataFrame(columns=_COLUNAS_VAZIAS)

    df = pd.DataFrame(contratos)
    df["id"] = df["id"].astype("string")
    for coluna in _COLUNAS_TEXTO:
        if coluna not in df.columns:
            df[coluna] = pd.NA
        df[coluna] = df[coluna].astype("string")
    for coluna in _COLUNAS_NUMERICAS:
        if coluna not in df.columns:
            df[coluna] = pd.NA
        df[coluna] = pd.to_numeric(df[coluna], errors="coerce")
    if "vigencia_fim" not in df.columns:
        df["vigencia_fim"] = pd.NA
    df["vigencia_fim"] = pd.to_datetime(df["vigencia_fim"], errors="coerce")
    if "inicio_execucao_data" not in df.columns:
        df["inicio_execucao_data"] = pd.NA
    df["inicio_execucao_data"] = pd.to_datetime(df["inicio_execucao_data"], errors="coerce")
    if "data_suspensao" not in df.columns:
        df["data_suspensao"] = pd.NA
    df["data_suspensao"] = pd.to_datetime(df["data_suspensao"], errors="coerce")
    if "itens" not in df.columns:
        df["itens"] = None
    df["itens"] = df["itens"].apply(_itens_validos)
    df["tem_varios_itens"] = df["itens"].apply(lambda itens: len(itens) > 1)

    # Aditivos (06/10/2026): `despesa_mensal` e `vigencia_fim` seguem os ORIGINAIS do contrato; o que vale
    # em cada data vem de `src.contratos_aditivos`. Registro anterior aos aditivos = lista vazia.
    df["aditivos"] = [aditivos_do_registro(valor) for valor in df.get("aditivos", pd.Series([None] * len(df)))]
    df["vigencia_fim_efetiva"] = pd.to_datetime(
        pd.Series([vigencia_efetiva(fim, adit)[0] for fim, adit in zip(df["vigencia_fim"], df["aditivos"])], index=df.index),
        errors="coerce",
    )
    dia_de_referencia = _dia_de_referencia(exercicio, hoje)
    df["valor_mensal_vigente"] = pd.Series(
        [valor_vigente_em(valor, adit, dia_de_referencia)[0] for valor, adit in zip(df["despesa_mensal"], df["aditivos"])],
        index=df.index, dtype="float64",
    )
    df["tem_aditivo_previsto"] = [
        any(a.previsto for a in adit) if exercicio is None else bool(meses_com_previsto(adit, exercicio))
        for adit in df["aditivos"]
    ]

    # meses_no_ano (pedido explícito, mesmo campo de src.bolsas_auxilios_cadastro): total de
    # meses que o contrato é pago no exercício — contrato sem esse campo ainda preenchido
    # (registro anterior a esta correção) cai no padrão de 12 (mesmo critério "contínuo" já
    # usado antes desta mudança, nenhum contrato existente muda de valor). Com `exercicio`, a
    # despesa anual é a soma da série mensal (valor em vigor mês a mês, spec §4.5); sem ele, a
    # conta antiga `despesa_mensal × meses`.
    if exercicio is None:
        df["despesa_anual"] = df["despesa_mensal"] * df["meses_no_ano"].fillna(12)
    else:
        df["despesa_anual"] = pd.Series(
            [
                _despesa_anual(valor, adit, exercicio, meses)
                for valor, adit, meses in zip(df["despesa_mensal"], df["aditivos"], df["meses_no_ano"])
            ],
            index=df.index, dtype="float64",
        )
    df["meses_a_empenhar"], df["valor_a_empenhar"] = calcular_necessidade_empenho(
        df["meses_empenhados"], df["meses_liquidados"], df["despesa_mensal"]
    )
    return df


def duplicar_exercicio(ano_origem: int, ano_destino: int) -> list[dict]:
    registros_origem = carregar_contratos(ano_origem)
    return _duplicar_exercicio(
        DIRETORIO_PADRAO, registros_origem, ano_destino, CAMPOS_IDENTIDADE, CAMPOS_EXECUCAO_PADRAO
    )


def _limpo(valor: object) -> object:
    if pd.isna(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.isoformat()
    if hasattr(valor, "item"):
        return valor.item()
    return valor


def _itens_do_grupo(grupo: pd.DataFrame, despesa_mensal_total: float) -> list[dict]:
    """Um `{"numero", "percentual"}` por linha (item) do grupo — usa `item_percentual` da
    origem quando presente; sem ele, deriva da fração de `despesa_mensal` do item sobre o
    total do grupo (mesma proporção, só calculada em vez de lida — ver docstring do módulo).

    `item_percentual` da planilha ("% ITEM LIC.") vem em FRAÇÃO (0-1: "0,7" = 70%), não em
    percentual (0-100) — conferido linha a linha contra a extração real (ex.: Tekis Item 1 =
    0.7, Item 2 = 0.3). Multiplicado por 100 aqui pra ficar na mesma escala usada em todo o
    resto do cadastro (`itens[].percentual` sempre 0-100, mesma escala do campo editável no
    cartão)."""

    itens = []
    for posicao, (_, linha_item) in enumerate(grupo.iterrows(), start=1):
        numero_bruto = linha_item.get("item_licitacao")
        numero = int(numero_bruto) if pd.notna(numero_bruto) else posicao

        percentual_bruto = linha_item.get("item_percentual")
        if pd.notna(percentual_bruto):
            percentual = round(float(percentual_bruto) * 100, 4)
        else:
            despesa_item = linha_item.get("despesa_mensal")
            if pd.notna(despesa_item) and despesa_mensal_total:
                percentual = round(float(despesa_item) / despesa_mensal_total * 100, 4)
            else:
                percentual = round(100 / len(grupo), 4)
        itens.append({"numero": numero, "percentual": percentual})
    return itens


def migrar_de_planilha(
    caminho: str | Path,
    ano: int,
    *,
    diretorio_base: str | Path | None = None,
) -> list[dict]:
    """Importação única: lê a planilha antiga (uma linha por contrato × item de licitação,
    `ler_contratos_continuos`) e AGRUPA por NE (ou por número de contrato, para contratos
    ainda sem NE atribuída) em um registro nativo por contrato — usada uma vez para migrar
    2026 (pedido explícito de desvinculação da planilha); não é chamada pela página em uso
    normal. Ver docstring do módulo para o critério de agrupamento e o que cada campo vira."""

    dataframe = ler_contratos_continuos(caminho)
    destino = DIRETORIO_PADRAO if diretorio_base is None else Path(diretorio_base)
    chave_agrupamento = dataframe["ne_curta"].fillna(dataframe["contrato_numero"])

    criados = []
    for _, grupo in dataframe.groupby(chave_agrupamento, sort=False):
        primeira = grupo.iloc[0]
        despesa_mensal_total = float(grupo["despesa_mensal"].sum(min_count=1) or 0.0)
        valor_empenhado_total = float(grupo["valor_empenhado"].sum(min_count=1) or 0.0)

        campos = {
            chave: _limpo(primeira.get(chave))
            for chave in CAMPOS_IDENTIDADE
            if chave not in ("despesa_mensal", "itens")
        }
        campos["despesa_mensal"] = despesa_mensal_total
        campos["itens"] = _itens_do_grupo(grupo, despesa_mensal_total)

        for chave_execucao in CAMPOS_EXECUCAO_PADRAO:
            campos[chave_execucao] = (
                valor_empenhado_total if chave_execucao == "valor_empenhado" else _limpo(primeira.get(chave_execucao))
            )

        registro = novo_registro(**campos)
        _salvar(destino, ano, registro)
        criados.append(registro)
    return criados
