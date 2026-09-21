"""
Regra de projeção de Despesas de Pessoal — replica a metodologia identificada no
relatório-modelo da SPO/MEC ("Relatório Resumido das Despesas de Pessoal", UO 26248/
UFRPE), decidida e confirmada em conversa com o usuário (ver decisões abaixo) —
NENHUMA regra aqui foi presumida sem confirmação explícita.

Camada: regra de negócio pura (não lê arquivo, não importa Streamlit) — consome os
DataFrames já normalizados por `src.importacao_execucao.carregar_atual()` (Execução
Anual) e `src.importacao_execucao_mensal.carregar_atual()` (Execução Mensal, 2024 em
diante) — as duas bases têm importação versionada por manifesto (21/09/2026: a Mensal
ganhou o mesmo padrão da Anual). `grade_mensal`/`grade_mensal_beneficios` recebem o
`ano` como parâmetro explícito e filtram `mensal_df` por ele — a base mensal cobrir
vários exercícios não implica em somar/misturar anos aqui.

DECISÕES CONFIRMADAS PELO USUÁRIO (09-10/09/2026) — mudar exige nova confirmação,
nunca presumir:

  1. "Mês de referência" usa LIQUIDADA, não Empenhada. Pessoal é empenhado uma única
     vez (estimativo, no início do exercício) — a Empenhada mensal fica ~zero e não
     serve como referência de folha. Confirmado contra a base real: Empenhada de
     pessoal em 2026 ficou entre R$ 0 e ~R$ 20 mil/mês (ajustes pontuais); Liquidada
     ficou na faixa de R$ 31-44 mi/mês (Ativos), R$ 16-26 mi/mês (Inativos), R$ 7,7-
     8,5 mi/mês (RPPS) — só ela reflete o movimento real da folha.
  2. Escopo = as 3 ações "core" do relatório SPO (20TP Ativos, 0181 Inativos, 09HB
     RPPS) MAIS duas ações adicionais pedidas pelo usuário, fora do relatório
     original: 2004 (Assistência Médica/Odontológica) e 212B (Benefícios
     Obrigatórios — inclui Auxílio-Alimentação, Auxílio-Transporte etc.).
  3. ED_94 (Indenizações e Restituições Trabalhistas) e ED_96 (Ressarcimento de
     Despesa de Pessoal Requisitado) não têm execução observada na UFRPE em 2026,
     mas o usuário pediu para o código já estar preparado para contabilizá-los caso
     apareçam — incluídos na tabela com o grupo de multiplicador que o próprio
     briefing já indicava (94 no grupo ×12 "indenizações trabalhistas"; 96 no grupo
     ×13,3333 "ressarcimento de pessoal requisitado").
  4. Sentenças judiciais (elemento 91): a separação ativo × inativo usa a mesma Ação
     de Governo que já separa o resto da classificação (20TP=ativo → ×13,3333;
     0181=inativo → ×13) — não uma lista manual de naturezas detalhadas (a base real
     mistura as duas dentro da mesma natureza de despesa).
  5. Rubricas das ações 2004/212B fora da metodologia original do relatório SPO
     (auxílio-alimentação, auxílio-transporte, assistência médica/odontológica
     etc.): ×12 — mesma lógica do grupo "sem 13º/férias" já definido para
     vencimentos regulares.
  6. Grade MENSAL (pedido explícito, com o layout de referência de um relatório da
     SPO/MEC anexado pelo usuário): para o exercício CORRENTE, meses já presentes na
     base mensal usam o valor REAL (Liquidada); meses futuros usam a projeção da
     regra da rubrica. A parcela "extra" de um multiplicador acima de ×12 (a fração
     13º/férias embutida no ×13/×13,3333) e o próprio 13º salário são concentrados
     em DOIS meses — metade em junho (antecipação), metade em novembro (parcela
     final) — mesmo padrão real de pagamento do funcionalismo público, confirmado
     pelo usuário. Rubricas de "Benefício Especial" (Lei 12.618/2012) e
     "Precatórios/Sentenças de Pequeno Valor", citadas pelo usuário como ainda sem
     execução na UFRPE: a primeira já cai automaticamente no mecanismo de erro
     existente (é uma natureza dentro da Ação 0181, já rastreada — ver decisão 4); a
     segunda pertenceria a uma Ação de Governo INTEIRA ainda fora de `ACOES_ESCOPO` —
     sem o código dela, não há como detectá-la; bastaria somar a `ACOES_ESCOPO` e ao
     `_GRUPO_POR_ACAO` quando o código for conhecido.
  7. (18/09/2026) Auditoria externa comparou a metodologia deste módulo com a matriz de
     projeção 2023v3 (modelo original da SPO/MEC). Duas divergências resolvidas:
     - Abono pecuniário/constitucional/adiantamento de férias (item 3 acima, proporção
       histórica): CONFIRMADO manter como está — divergência deliberada e consciente em
       relação à matriz 2023v3, não um erro a corrigir.
     - ED_94 (Indenizações e Restituições Trabalhistas, item 3 acima): tinha um único
       multiplicador x12 para todos os grupos. A matriz 2023v3 pede x12 para Ativo mas
       x13 para Inativo. CORRIGIDO para multiplicador por grupo (Ativo -> x12, Inativo
       -> x13), alinhando ao modelo — sem efeito na projeção atual (base de inativos
       ainda é zero), mas evita divergência quando essa rubrica passar a ter execução.
  8. (21/09/2026) BUG CORRIGIDO — comparação direta contra a planilha oficial 26248 (não
     contra a matriz teórica) achou uma diferença real de ~R$44 milhões no total do
     exercício, concentrada quase inteira na regra REGRA_DECIMO_TERCEIRO: ela usava
     `valor_mes_referencia` da PRÓPRIA rubrica de 13º (ex.: natureza detalhada 31901143)
     no mês de referência escolhido — mas essa rubrica só tem valor real em junho
     (antecipação) e novembro (parcela final); em qualquer outro mês de referência (ex.:
     agosto), o valor é um resíduo quase nulo (confirmado: R$698,73 para o 13º do Ativo
     em ago/2026), fazendo a parcela projetada de novembro colapsar para perto de zero
     em vez do valor esperado (a planilha 26248 mostra ~R$16,6 milhões em novembro só
     para essa rubrica do Ativo). CORRIGIDO: `_valor_referencia_natureza_mae` busca o
     mês de referência da natureza de despesa "mãe" de cada rubrica de 13º (319011
     Vencimentos para o Ativo, 319001/319003 para Inativo, 319004 para temporários) —
     a mesma base que já alimenta a proporção histórica (item 3) — em vez do valor da
     própria rubrica de 13º. Sem mudança na distribuição temporal (ainda metade em
     junho/metade em novembro, decisão 6) nem nas demais regras.

Contrato público:
    classificar_grupo(acao_cod) -> str | None
    regra_para_natureza(natureza_despesa_cod, natureza_detalhada_cod) -> RegraRubrica | None
    multiplicador_efetivo(regra, grupo) -> float
    filtrar_escopo(df) -> pd.DataFrame
    valor_mes_referencia(mensal_df, ano_mes) -> pd.DataFrame
    ultimo_mes_fechado(mensal_df) -> int | None
    execucao_ano_anterior(anual_df, ano) -> pd.DataFrame
    projetar(mensal_df, anual_df, ano_mes_referencia, ano_projecao) -> ResultadoProjecao
    dotacao_atualizada_por_grupo(dotacao_df, ano) -> pd.Series
    comparar_com_dotacao(resultado, dotacao_df, ano_dotacao) -> pd.DataFrame
    grade_mensal(mensal_df, anual_df, ano, ano_mes_referencia) -> ResultadoGradeMensal
    aplicar_overrides(grade, overrides) -> ResultadoGradeMensal
    saldo_remanescente(grade, dotacao_por_grupo) -> pd.DataFrame
    consolidar_por_elemento(grade) -> ResultadoGradeMensal
    consolidar_relatorio_ativo(grade) -> ResultadoGradeMensal
    dotacao_atualizada_por_plano_orcamentario(dotacao_df, ano) -> pd.Series
    valor_mes_referencia_beneficios(mensal_df, ano_mes) -> pd.DataFrame
    execucao_ano_anterior_beneficios(anual_df, ano) -> pd.DataFrame
    grade_mensal_beneficios(mensal_df, anual_df, ano, ano_mes_referencia) -> ResultadoGradeMensal
    substituir_beneficios_por_plano_orcamentario(grade, mensal_df, anual_df) -> ResultadoGradeMensal
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# --------------------------------------------------------------------------------------
# 1. Classificação por Ação de Governo (decisão 2)
# --------------------------------------------------------------------------------------

ACAO_ATIVO = "20TP"
ACAO_INATIVO = "0181"
ACAO_RPPS = "09HB"
ACAO_ASSISTENCIA_MEDICA = "2004"
ACAO_BENEFICIOS_OBRIGATORIOS = "212B"

GRUPO_ATIVO = "ativo"
GRUPO_INATIVO = "inativo"
GRUPO_RPPS = "rpps"
#: grupo "guarda-chuva" para as 2 ações adicionais (decisão 2) — fora da metodologia
#: original do relatório SPO, tratadas à parte na interface (não como "Ativo"/
#: "Inativo"/"RPPS" do relatório-modelo).
GRUPO_OUTROS_BENEFICIOS = "outros_beneficios"

#: núcleo do relatório-modelo SPO/MEC — regras estritas (natureza sem regra mapeada
#: aqui é ERRO, não fica de fora silenciosamente).
_ACOES_NUCLEO_SPO = {ACAO_ATIVO, ACAO_INATIVO, ACAO_RPPS}
#: adicionadas pelo usuário, fora do relatório original — regras mais tolerantes
#: (natureza sem regra mapeada cai no padrão ×12 "outros benefícios", com ALERTA,
#: não erro — decisão 5).
_ACOES_EXTRAS_USUARIO = {ACAO_ASSISTENCIA_MEDICA, ACAO_BENEFICIOS_OBRIGATORIOS}

ACOES_ESCOPO = _ACOES_NUCLEO_SPO | _ACOES_EXTRAS_USUARIO

_GRUPO_POR_ACAO: dict[str, str] = {
    ACAO_ATIVO: GRUPO_ATIVO,
    ACAO_INATIVO: GRUPO_INATIVO,
    ACAO_RPPS: GRUPO_RPPS,
    ACAO_ASSISTENCIA_MEDICA: GRUPO_OUTROS_BENEFICIOS,
    ACAO_BENEFICIOS_OBRIGATORIOS: GRUPO_OUTROS_BENEFICIOS,
}


def classificar_grupo(acao_cod: object) -> str | None:
    """Ativo/Inativo/RPPS/Outros Benefícios a partir da Ação de Governo — `None` se
    `acao_cod` não pertence a nenhuma das 5 ações do escopo (linha fora deste
    módulo)."""

    return _GRUPO_POR_ACAO.get(str(acao_cod)) if pd.notna(acao_cod) else None


# --------------------------------------------------------------------------------------
# 2. Tabela de regras de projeção, por Natureza de Despesa (decisões 1, 3, 5)
# --------------------------------------------------------------------------------------

#: 12 meses + 13º + 1/3 de férias constitucional.
MULTIPLICADOR_13_3333 = 40 / 3
#: 12 meses + 13º, sem o terço de férias.
MULTIPLICADOR_13 = 13.0
#: sem 13º nem férias — são linhas/regras separadas.
MULTIPLICADOR_12 = 12.0

REGRA_MULTIPLICADOR = "multiplicador"
REGRA_SENTENCA_POR_GRUPO = "sentenca_por_grupo"
REGRA_INDENIZACAO_POR_GRUPO = "indenizacao_por_grupo"
REGRA_DECIMO_TERCEIRO = "decimo_terceiro"
REGRA_PROPORCAO_HISTORICA = "proporcao_historica"
REGRA_ZERO = "zero"


@dataclass(frozen=True)
class RegraRubrica:
    natureza_despesa_cod: str
    descricao: str
    tipo: str
    multiplicador: float | None = None
    #: só para `REGRA_SENTENCA_POR_GRUPO` — multiplicador depende do grupo (ativo/inativo).
    multiplicador_por_grupo: dict[str, float] | None = None
    #: origem da regra, para rastreabilidade (aparece nos relatórios/testes).
    origem: str = ""


def _regra(cod: str, desc: str, tipo: str, mult: float | None = None, origem: str = "") -> RegraRubrica:
    return RegraRubrica(natureza_despesa_cod=cod, descricao=desc, tipo=tipo, multiplicador=mult, origem=origem)


#: tabela indexada por `natureza_despesa_cod` (6 dígitos) — a granularidade que o
#: relatório-modelo SPO/MEC usa. Cobre as naturezas GND1 (319xxx) confirmadas na
#: execução real de 2026 das 3 ações núcleo, mais as variantes GND3 (339xxx) das
#: MESMAS rubricas que aparecem dentro da ação 212B (ex.: contratação temporária,
#: sentenças, exercícios anteriores classificados sob 212B em vez de sob a ação
#: núcleo correspondente — mesma regra da rubrica, independente de qual ação a
#: financia).
TABELA_REGRAS: dict[str, RegraRubrica] = {
    # --- grupo ×13,3333 (12 meses + 13º + 1/3 férias) ---
    "319004": _regra("319004", "Contratação por Tempo Determinado", REGRA_MULTIPLICADOR, MULTIPLICADOR_13_3333),
    "339004": _regra("339004", "Contratação por Tempo Determinado", REGRA_MULTIPLICADOR, MULTIPLICADOR_13_3333),
    "319104": _regra(
        "319104", "Contratação por Tempo Determinado (Operações Intra-Orçamentárias)", REGRA_MULTIPLICADOR, MULTIPLICADOR_13_3333,
        origem="NÃO confirmado explicitamente pelo usuário — inferido por analogia direta com o par 319013/319113 "
        "(RGPS/RPPS: mesma rubrica, variante intra-orçamentária, mesmo multiplicador). Achado ao validar contra "
        "dados reais de 2026 (natureza presente, sem regra até então). Revisar se questionado.",
    ),
    "319007": _regra("319007", "Contribuição a Entidade Fechada de Previdência", REGRA_MULTIPLICADOR, MULTIPLICADOR_13_3333),
    "319096": _regra(
        "319096", "Ressarcimento de Despesa de Pessoal Requisitado", REGRA_MULTIPLICADOR, MULTIPLICADOR_13_3333,
        origem="ED_96 do briefing — sem execução observada em 2026, incluída defensivamente (decisão 3).",
    ),
    # --- indenizações trabalhistas: multiplicador depende do grupo (decisão 7) ---
    "319094": _regra(
        "319094", "Indenizações e Restituições Trabalhistas", REGRA_INDENIZACAO_POR_GRUPO,
        origem="ED_94 do briefing — sem execução observada em 2026, incluída defensivamente (decisão 3). "
        "Multiplicador por grupo confirmado em 18/09/2026 (decisão 7): Ativo (20TP) -> x12; "
        "Inativo (0181) -> x13, alinhado ao relatório-modelo (antes x12 para todos).",
    ),
    # --- grupo ×13 (12 meses + 13º, sem 1/3 férias) ---
    "319013": _regra("319013", "Obrigações Patronais (RGPS)", REGRA_MULTIPLICADOR, MULTIPLICADOR_13),
    "319113": _regra("319113", "Obrigações Patronais — RPPS (Ação 09HB)", REGRA_MULTIPLICADOR, MULTIPLICADOR_13),
    # --- grupo ×12 (sem 13º nem férias — linhas separadas) ---
    "319001": _regra("319001", "Aposentadorias, Reserva Remunerada e Reformas (excl. 13º)", REGRA_MULTIPLICADOR, MULTIPLICADOR_12),
    "319003": _regra("319003", "Pensões (excl. 13º)", REGRA_MULTIPLICADOR, MULTIPLICADOR_12),
    "319011": _regra("319011", "Vencimentos e Vantagens Fixas — Pessoal Civil (excl. 13º/férias)", REGRA_MULTIPLICADOR, MULTIPLICADOR_12),
    "319016": _regra("319016", "Outras Despesas Variáveis — Pessoal Civil", REGRA_MULTIPLICADOR, MULTIPLICADOR_12),
    # --- sentenças judiciais: multiplicador depende do grupo (decisão 4) ---
    "319091": _regra(
        "319091", "Sentenças Judiciais", REGRA_SENTENCA_POR_GRUPO,
        origem="Ativo (20TP) -> x13,3333; Inativo (0181) -> x13 — via Ação de Governo (decisão 4).",
    ),
    "339091": _regra("339091", "Sentenças Judiciais", REGRA_SENTENCA_POR_GRUPO),
    # --- despesas de exercícios anteriores: projeção sempre zero ---
    "319092": _regra("319092", "Despesas de Exercícios Anteriores", REGRA_ZERO),
    "339092": _regra("339092", "Despesas de Exercícios Anteriores", REGRA_ZERO),
    "319192": _regra(
        "319192", "Despesas de Exercícios Anteriores (Operações Intra-Orçamentárias)", REGRA_ZERO,
        origem="Mesma regra de 319092 (a natureza da despesa, não a variante intra-orçamentária, é o que "
        "define a regra — despesa de exercício anterior projeta zero de qualquer forma). Achado ao validar "
        "contra dados reais de 2026.",
    ),
    # --- itens sem padrão mensal estável: mantêm a proporção histórica sobre vencimentos ---
    # (naturezas detalhadas específicas, ver `NATUREZAS_DETALHADAS_PROPORCAO_HISTORICA`
    # abaixo — a natureza de despesa 319011 "mãe" já está mapeada acima como x12; as duas
    # naturezas detalhadas abaixo SOBRESCREVEM essa regra por serem mais específicas.)
}

#: item 2 do briefing: 13º salário — mesmo valor do mês de referência da folha (x1,
#: não um multiplicador de meses). Códigos REAIS confirmados na execução 2026 (natureza
#: detalhada, não natureza de despesa — o 13º convive com a folha regular dentro da
#: MESMA natureza de despesa "mãe", ex. 319001/319011, por isso a exceção é por
#: natureza detalhada, mais fina que a tabela principal acima).
NATUREZAS_DETALHADAS_DECIMO_TERCEIRO: dict[str, str] = {
    "31901143": "13º SALARIO (Ativos)",
    "31900106": "13 SALARIO - PESSOAL CIVIL (Inativos/Aposentados)",
    "31900303": "13 SALARIO - PENSOES CIVIS",
    "31900413": "13º SALARIO - CONTRATO TEMPORARIO",
}

#: item 3 do briefing: sem padrão mensal estável — projeta mantendo a MESMA proporção
#: que o item representou sobre os Vencimentos (319011) na execução do ano anterior.
#: 31901145/31901146 confirmados na execução real 2026. 31901144 (Abono Pecuniário)
#: SEM execução observada em 2026 — incluído defensivamente (mesmo padrão do ED_94/
#: ED_96, decisão 3), a pedido do usuário ao restringir a aba Ativo ao layout do
#: relatório-modelo anexado (10/09/2026): fica pronto para quando a rubrica aparecer,
#: em vez de cair no x12 genérico do elemento 11/12.
NATUREZAS_DETALHADAS_PROPORCAO_HISTORICA: dict[str, str] = {
    "31901144": "ABONO PECUNIÁRIO (venda de férias)",
    "31901145": "FÉRIAS - 1/3 CONSTITUCIONAL (abono constitucional)",
    "31901146": "FÉRIAS - PAGAMENTO ANTECIPADO (adiantamento de férias)",
}

#: naturezas de despesa das 2 ações adicionais (decisão 2) que já têm rubrica própria
#: identificada na execução 2026 — mapeadas explicitamente para x12 (decisão 5), em vez
#: de cair só no padrão implícito, para ficarem auditáveis nesta tabela também.
_NATUREZAS_OUTROS_BENEFICIOS_CONHECIDAS = {
    "339046": "Auxílio-Alimentação",
    "339049": "Auxílio-Transporte",
    "339008": "Outros Benefícios Assistenciais do Servidor",
}
for _cod, _desc in _NATUREZAS_OUTROS_BENEFICIOS_CONHECIDAS.items():
    TABELA_REGRAS[_cod] = _regra(_cod, _desc, REGRA_MULTIPLICADOR, MULTIPLICADOR_12, origem="Decisão 5 (rubrica fora do relatório SPO original).")


def regra_para_natureza(natureza_despesa_cod: str, natureza_detalhada_cod: str | None = None) -> RegraRubrica | None:
    """Resolve a regra de projeção de uma linha — checa primeiro as exceções por
    Natureza Detalhada (13º salário, proporção histórica — mais específicas), depois
    a tabela principal por Natureza de Despesa. `None` se não há regra mapeada (ver
    `filtrar_escopo`/`projetar` para o que cada camada faz com isso: erro nas ações
    núcleo do relatório SPO, alerta+padrão x12 nas ações extras do usuário)."""

    if natureza_detalhada_cod in NATUREZAS_DETALHADAS_DECIMO_TERCEIRO:
        return _regra(
            natureza_despesa_cod, NATUREZAS_DETALHADAS_DECIMO_TERCEIRO[natureza_detalhada_cod],
            REGRA_DECIMO_TERCEIRO, origem="Item 2 do briefing (13º salário).",
        )
    if natureza_detalhada_cod in NATUREZAS_DETALHADAS_PROPORCAO_HISTORICA:
        return _regra(
            natureza_despesa_cod, NATUREZAS_DETALHADAS_PROPORCAO_HISTORICA[natureza_detalhada_cod],
            REGRA_PROPORCAO_HISTORICA, origem="Item 3 do briefing (proporção histórica).",
        )
    return TABELA_REGRAS.get(str(natureza_despesa_cod))


def multiplicador_efetivo(regra: RegraRubrica, grupo: str | None) -> float:
    """Resolve o multiplicador de fato para `REGRA_MULTIPLICADOR`/`REGRA_SENTENCA_POR_GRUPO`/
    `REGRA_INDENIZACAO_POR_GRUPO` — as únicas regras que usam um número direto (as
    outras três — 13º, proporção histórica, zero — não multiplicam o mês de referência
    por um fator fixo, ver `projetar`)."""

    if regra.tipo == REGRA_MULTIPLICADOR:
        assert regra.multiplicador is not None
        return regra.multiplicador
    if regra.tipo == REGRA_SENTENCA_POR_GRUPO:
        if grupo == GRUPO_ATIVO:
            return MULTIPLICADOR_13_3333
        if grupo == GRUPO_INATIVO:
            return MULTIPLICADOR_13
        # RPPS/outros_beneficios não têm sentença classificada no briefing — trata pela
        # regra mais conservadora (x13, sem o terço de férias) em vez de presumir x13,3333.
        return MULTIPLICADOR_13
    if regra.tipo == REGRA_INDENIZACAO_POR_GRUPO:
        if grupo == GRUPO_INATIVO:
            return MULTIPLICADOR_13
        # Ativo (decisão 3) e RPPS/outros_beneficios (sem indenização classificada no
        # briefing, tratado pelo mesmo padrão x12 da decisão 3/5) — decisão 7.
        return MULTIPLICADOR_12
    raise ValueError(f"multiplicador_efetivo: regra {regra.tipo!r} não usa multiplicador direto.")


# --------------------------------------------------------------------------------------
# 3. Filtragem por escopo (Execução Anual OU Mensal — mesmos nomes de coluna)
# --------------------------------------------------------------------------------------

def filtrar_escopo(df: pd.DataFrame) -> pd.DataFrame:
    """Linhas das 5 ações do escopo (decisão 2), com a coluna `grupo` (Ativo/Inativo/
    RPPS/Outros Benefícios) já anexada. Funciona tanto com o DataFrame da Execução
    Anual (`src.importacao_execucao.carregar_atual()`) quanto da Mensal
    (`src.tesouro_execucao_mensal.ler_execucao_mensal()`) — ambas têm `acao_cod`."""

    recorte = df.loc[df["acao_cod"].isin(ACOES_ESCOPO)].copy()
    recorte["grupo"] = recorte["acao_cod"].map(_GRUPO_POR_ACAO)
    return recorte


# --------------------------------------------------------------------------------------
# 4. Valor do mês de referência (decisão 1: Liquidada, base Mensal)
# --------------------------------------------------------------------------------------

def valor_mes_referencia(mensal_df: pd.DataFrame, ano_mes: int) -> pd.DataFrame:
    """Liquidada do mês `ano_mes`, por (grupo, natureza_despesa_cod,
    natureza_detalhada_cod), dentro do escopo de pessoal. Usa as linhas de tipo
    "item_execucao" (onde Liquidada/Paga são reais, não repetidas por item — ver
    docstring de `src.tesouro_execucao_mensal`), filtra pelo mês pedido antes de somar."""

    escopo = filtrar_escopo(mensal_df)
    do_mes = escopo.loc[(escopo["ano_mes"] == ano_mes) & (escopo["tipo_linha"] == "item_execucao")]
    agrupado = (
        do_mes.groupby(["grupo", "natureza_despesa_cod", "natureza_despesa_desc", "natureza_detalhada_cod", "natureza_detalhada_desc"], dropna=False)
        ["liquidada"].sum(min_count=1).reset_index()
    )
    return agrupado.rename(columns={"liquidada": "valor_mes_referencia"})


def ultimo_mes_fechado(mensal_df: pd.DataFrame) -> int | None:
    """`ano_mes` do último mês com Liquidada de pessoal (escopo do módulo) maior que
    zero — heurística de "mês fechado" pedida pelo briefing como valor padrão do
    parâmetro (o mês corrente costuma aparecer na extração já com algumas linhas, mas
    ainda incompleto/zerado; usar o último mês com movimento real evita escolher um
    mês em aberto). `None` se a base mensal não tiver nenhum mês com dado de pessoal."""

    escopo = filtrar_escopo(mensal_df)
    do_tipo_item = escopo.loc[escopo["tipo_linha"] == "item_execucao"]
    por_mes = do_tipo_item.groupby("ano_mes")["liquidada"].sum(min_count=1)
    com_movimento = por_mes[por_mes.fillna(0.0) > 0]
    if com_movimento.empty:
        return None
    return int(com_movimento.index.max())


# --------------------------------------------------------------------------------------
# 5. Execução do ano anterior (item 3: proporção histórica) — base Anual
# --------------------------------------------------------------------------------------

def execucao_ano_anterior(anual_df: pd.DataFrame, ano: int) -> pd.DataFrame:
    """Empenhado do ano `ano` (tipicamente o ano anterior ao da projeção), por (grupo,
    natureza_despesa_cod, natureza_detalhada_cod), dentro do escopo de pessoal — usa a
    Execução ANUAL (`carregar_atual()`), preservando nulo≠zero (`min_count=1`, mesmo
    padrão do resto do projeto)."""

    escopo = filtrar_escopo(anual_df)
    do_ano = escopo.loc[escopo["ano"] == ano]
    agrupado = (
        do_ano.groupby(["grupo", "natureza_despesa_cod", "natureza_despesa_desc", "natureza_detalhada_cod", "natureza_detalhada_desc"], dropna=False)
        ["empenhada"].sum(min_count=1).reset_index()
    )
    return agrupado.rename(columns={"empenhada": "execucao_ano_anterior"})


# --------------------------------------------------------------------------------------
# 6. Projeção
# --------------------------------------------------------------------------------------

@dataclass
class ResultadoProjecao:
    linhas: pd.DataFrame
    ano_mes_referencia: int
    ano_projecao: int
    erros: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.erros

    def total_por_grupo(self) -> pd.Series:
        return self.linhas.groupby("grupo")["projecao"].sum(min_count=1)


def projetar(mensal_df: pd.DataFrame, anual_df: pd.DataFrame, ano_mes_referencia: int, ano_projecao: int) -> ResultadoProjecao:
    """Monta a projeção completa: uma linha por (grupo, natureza de despesa, natureza
    detalhada) no escopo de pessoal, com o valor do mês de referência (Liquidada),
    execução do ano anterior (para a regra de proporção histórica) e a projeção final,
    conforme a regra de cada rubrica (`regra_para_natureza`).

    `ano_mes_referencia` no formato `AAAAMM` (ex. 202609); `ano_projecao` é o exercício
    sendo projetado (tipicamente o ano de `ano_mes_referencia // 100` + 1)."""

    ano_referencia = ano_mes_referencia // 100
    ano_anterior_ref = ano_referencia - 1

    valor_mes = valor_mes_referencia(mensal_df, ano_mes_referencia)
    exec_ano_anterior = execucao_ano_anterior(anual_df, ano_anterior_ref)

    linhas = valor_mes.merge(
        exec_ano_anterior[["grupo", "natureza_despesa_cod", "natureza_detalhada_cod", "execucao_ano_anterior"]],
        on=["grupo", "natureza_despesa_cod", "natureza_detalhada_cod"], how="outer",
    )

    # Execução do ano anterior de vencimentos REGULARES (319011, excl. 13º/férias) por
    # grupo — denominador da regra de proporção histórica (item 3 do briefing). Mesma
    # exclusão de `_projecao_vencimentos_do_grupo` (numerador e denominador da
    # proporção precisam usar a MESMA definição de "vencimentos regulares", senão a
    # proporção histórica calculada aqui não corresponde à que existiu de fato).
    _excecoes_venc = set(NATUREZAS_DETALHADAS_DECIMO_TERCEIRO) | set(NATUREZAS_DETALHADAS_PROPORCAO_HISTORICA)
    vencimentos_ano_anterior = (
        exec_ano_anterior.loc[
            (exec_ano_anterior["natureza_despesa_cod"] == "319011")
            & (~exec_ano_anterior["natureza_detalhada_cod"].isin(_excecoes_venc))
        ]
        .groupby("grupo")["execucao_ano_anterior"].sum(min_count=1)
    )

    erros: list[str] = []
    alertas: list[str] = []
    projecoes: list[float | None] = []
    regras_aplicadas: list[str] = []
    origem_regra: list[str] = []

    for linha in linhas.itertuples(index=False):
        regra = regra_para_natureza(linha.natureza_despesa_cod, linha.natureza_detalhada_cod)
        if regra is None:
            mensagem = (
                f"Sem regra de projeção para natureza {linha.natureza_despesa_cod} "
                f"({linha.natureza_despesa_desc}), detalhada {linha.natureza_detalhada_cod} "
                f"({linha.natureza_detalhada_desc}), grupo {linha.grupo}."
            )
            if linha.grupo in (GRUPO_ATIVO, GRUPO_INATIVO, GRUPO_RPPS):
                # núcleo do relatório SPO: regra ausente é ERRO — nada projetado
                # silenciosamente fora da metodologia confirmada (AGENTS.md: dados
                # financeiros não podem ser descartados/modificados sem sinalização).
                erros.append(mensagem)
                projecoes.append(None)
                regras_aplicadas.append("SEM_REGRA")
                origem_regra.append("")
                continue
            # ações extras do usuário: cai no padrão x12 (decisão 5), com ALERTA (não erro).
            alertas.append(mensagem + " Aplicado o padrão x12 da decisão 5.")
            regra = _regra(str(linha.natureza_despesa_cod), str(linha.natureza_despesa_desc), REGRA_MULTIPLICADOR, MULTIPLICADOR_12)

        valor_ref = linha.valor_mes_referencia
        if regra.tipo == REGRA_ZERO:
            projecoes.append(0.0)
        elif regra.tipo == REGRA_DECIMO_TERCEIRO:
            # NÃO usar `valor_ref` (o mês de referência da PRÓPRIA rubrica de 13º): ela só
            # tem valor real em junho/novembro, quando o 13º de fato é pago — em qualquer
            # outro mês de referência, `valor_ref` é resíduo quase nulo e projetaria a
            # parcela de novembro perto de zero (bug real, achado comparando com a
            # planilha oficial 26248, ver decisão 8). A base correta é o mês de referência
            # da natureza "mãe" (319011 Vencimentos, 319001 Aposentadorias, 319003
            # Pensões, 319004 Contratação Temporária — a mesma que já classifica esta
            # linha), não a da rubrica de 13º em si.
            projecoes.append(_valor_referencia_natureza_mae(linhas, linha.grupo, linha.natureza_despesa_cod))
        elif regra.tipo == REGRA_PROPORCAO_HISTORICA:
            base_ano_anterior = vencimentos_ano_anterior.get(linha.grupo)
            if pd.isna(linha.execucao_ano_anterior) or not base_ano_anterior or pd.isna(base_ano_anterior):
                alertas.append(
                    f"Proporção histórica indisponível para {linha.natureza_detalhada_desc} "
                    f"(grupo {linha.grupo}) — sem execução do ano anterior de referência; projeção zerada."
                )
                projecoes.append(0.0)
            else:
                # Projeta a NOVA base de vencimentos (mês de referência x12, grupo
                # correspondente), não a execução bruta do ano anterior — é isso que o
                # item 3 do briefing pede ("aplicada à nova projeção de vencimentos").
                vencimentos_projetados = _projecao_vencimentos_do_grupo(linhas, linha.grupo)
                proporcao = float(linha.execucao_ano_anterior) / float(base_ano_anterior)
                projecoes.append(proporcao * vencimentos_projetados if vencimentos_projetados is not None else None)
        else:  # REGRA_MULTIPLICADOR / REGRA_SENTENCA_POR_GRUPO / REGRA_INDENIZACAO_POR_GRUPO
            if pd.isna(valor_ref):
                projecoes.append(None)
            else:
                projecoes.append(float(valor_ref) * multiplicador_efetivo(regra, linha.grupo))
        regras_aplicadas.append(regra.tipo)
        origem_regra.append(regra.origem)

    linhas = linhas.assign(projecao=projecoes, regra_aplicada=regras_aplicadas, origem_regra=origem_regra)
    return ResultadoProjecao(linhas=linhas, ano_mes_referencia=ano_mes_referencia, ano_projecao=ano_projecao, erros=erros, alertas=alertas)


def _valor_referencia_natureza_mae(linhas: pd.DataFrame, grupo: str, natureza_despesa_cod: str) -> float | None:
    """Soma do `valor_mes_referencia` de UM mês, para a natureza de despesa "mãe" do
    grupo (319011 Vencimentos no Ativo, 319001 Aposentadorias/319003 Pensões no Inativo,
    319004 Contratação Temporária, conforme o caso) — excluindo as naturezas detalhadas
    que já têm regra própria (13º salário, proporção histórica de férias): são
    sub-rubricas da MESMA natureza "mãe", mas com projeção própria — somá-las aqui infla
    o valor com algo que já tem sua própria regra (13º entraria dobrado: uma vez aqui,
    outra como "13º x1").

    Base tanto da proporção histórica (item 3, via `_projecao_vencimentos_do_grupo`,
    x12) quanto do 13º salário (decisão 8: cada rubrica de 13º usa a sua PRÓPRIA
    natureza mãe, não o mês de referência da própria rubrica de 13º, que só é
    diferente de zero em junho/novembro)."""

    excecoes = set(NATUREZAS_DETALHADAS_DECIMO_TERCEIRO) | set(NATUREZAS_DETALHADAS_PROPORCAO_HISTORICA)
    base = linhas.loc[
        (linhas["grupo"] == grupo)
        & (linhas["natureza_despesa_cod"] == natureza_despesa_cod)
        & (~linhas["natureza_detalhada_cod"].isin(excecoes))
    ]
    if base.empty or base["valor_mes_referencia"].isna().all():
        return None
    return float(base["valor_mes_referencia"].sum(min_count=1))


def _projecao_vencimentos_do_grupo(linhas: pd.DataFrame, grupo: str) -> float | None:
    """Projeção anualizada (x12) de "Vencimentos e Vantagens Fixas" (319011) REGULARES
    do grupo — denominador vivo da regra de proporção histórica (item 3), calculado a
    partir do próprio mês de referência do grupo, não da execução bruta do ano
    anterior. Ver `_valor_referencia_natureza_mae` para a exclusão das naturezas
    detalhadas com regra própria."""

    valor_um_mes = _valor_referencia_natureza_mae(linhas, grupo, "319011")
    return None if valor_um_mes is None else valor_um_mes * MULTIPLICADOR_12


# --------------------------------------------------------------------------------------
# 7. Comparação com a Dotação — o objetivo central deste módulo (pedido explícito do
#    usuário: "o objeto principal é conferir se a dotação é suficiente ou não de acordo
#    com as projeções"). Base Dotação Anual (`src.importacao_dotacao.carregar_atual()`)
#    — MESMA origem BI CPOC, mas SEM a dimensão Natureza de Despesa (só Ação/PTRES/GND/
#    Fonte/Plano Orçamentário): a comparação por isso acontece no nível de GRUPO (Ativo/
#    Inativo/RPPS/Outros Benefícios), a granularidade mais fina que a Dotação sustenta —
#    não por natureza de despesa, como a projeção em si.
# --------------------------------------------------------------------------------------

#: nome do indicador usado pela Dotação Anual para "dotação atualizada" (após
#: suplementações/cancelamentos/remanejamentos) — ver `src.dotacao_anual_analysis.
#: KNOWN_ITEM_INDICATORS`. É o valor certo para "quanto está disponível hoje", em vez
#: de `dotacao_inicial` (não reflete ajustes já ocorridos no exercício).
_ITEM_DOTACAO_ATUALIZADA = "dotacao_atualizada"


def dotacao_atualizada_por_grupo(dotacao_df: pd.DataFrame, ano: int) -> pd.Series:
    """Dotação Atualizada do ano `ano`, somada por grupo (Ativo/Inativo/RPPS/Outros
    Benefícios) — usa `acao_codigo`/`ano_lancamento` (nomes de coluna da Dotação Anual,
    diferentes de `acao_cod`/`ano` da Execução) porque a Dotação vem de
    `src.importacao_dotacao.carregar_atual()`, um leitor com contrato próprio."""

    recorte = dotacao_df.loc[
        (dotacao_df["item_informacao_codigo"] == _ITEM_DOTACAO_ATUALIZADA)
        & (dotacao_df["ano_lancamento"] == ano)
        & (dotacao_df["acao_codigo"].isin(ACOES_ESCOPO))
    ].copy()
    recorte["grupo"] = recorte["acao_codigo"].map(_GRUPO_POR_ACAO)
    return recorte.groupby("grupo")["valor_movimento_liquido"].sum(min_count=1)


#: prefixo dos códigos de Plano Orçamentário "Regra de Ouro" (RO01/RO03/RO05/RO09...) —
#: mesmo Plano Orçamentário sob a ótica de controle constitucional da regra de ouro
#: (Art. 167, III, CF), não um valor ADICIONAL de dotação. Na base real conhecida
#: (10/09/2026) sempre vêm nulas (`sum(min_count=1)` já as ignora sozinho), mas excluídas
#: aqui por código mesmo assim — nunca somar às claras algo que pode ser o mesmo dinheiro
#: contado duas vezes, mesmo que hoje o risco seja só teórico.
_PREFIXO_PO_REGRA_DE_OURO = "RO"


def dotacao_atualizada_por_plano_orcamentario(dotacao_df: pd.DataFrame, ano: int) -> pd.Series:
    """Dotação Atualizada do ano `ano`, por (Ação, Plano Orçamentário) — só as 2 ações
    de Outros Benefícios (2004/212B, decisão 2). Pedido do usuário (10/09/2026): ao
    contrário de Natureza de Despesa, a Dotação Anual TEM a dimensão Plano Orçamentário
    (`plano_orcamentario_codigo`/`_descricao`) — dá pra comparar dotação × projeção no
    mesmo nível de detalhe de `grade_mensal_beneficios`, não só por grupo inteiro.
    Devolve uma `pd.Series` indexada por `(acao_codigo, plano_orcamentario_codigo)` —
    o código de PO sozinho NÃO é único entre as 2 ações (ex. "0001" é "Assistência
    Médica" em 2004 mas "Assistência Pré-Escolar" em 212B)."""

    recorte = dotacao_df.loc[
        (dotacao_df["item_informacao_codigo"] == _ITEM_DOTACAO_ATUALIZADA)
        & (dotacao_df["ano_lancamento"] == ano)
        & (dotacao_df["acao_codigo"].isin(_ACOES_EXTRAS_USUARIO))
        & (~dotacao_df["plano_orcamentario_codigo"].astype(str).str.startswith(_PREFIXO_PO_REGRA_DE_OURO))
    ]
    return recorte.groupby(["acao_codigo", "plano_orcamentario_codigo"])["valor_movimento_liquido"].sum(min_count=1)


def comparar_com_dotacao(resultado: ResultadoProjecao, dotacao_df: pd.DataFrame, ano_dotacao: int) -> pd.DataFrame:
    """Projeção x Dotação Atualizada, por grupo — responde diretamente "a dotação é
    suficiente para a despesa projetada?". `ano_dotacao` é parametrizável (pedido
    explícito, mesmo espírito do mês de referência): a Dotação Anual só tem dado até o
    exercício CORRENTE (não existe "dotação de 2027" antes de o exercício começar), então
    o padrão razoável é comparar contra a dotação do ano corrente — não presumido aqui,
    quem chama decide e passa explicitamente.

    Colunas do resultado: `grupo`, `projecao`, `dotacao_atualizada`, `diferenca`
    (dotação − projeção: positivo = sobra, negativo = falta), `suficiente` (bool)."""

    projetado = resultado.total_por_grupo().rename("projecao")
    dotacao = dotacao_atualizada_por_grupo(dotacao_df, ano_dotacao).rename("dotacao_atualizada")
    comparacao = pd.concat([projetado, dotacao], axis=1).reset_index(names="grupo")
    comparacao["diferenca"] = comparacao["dotacao_atualizada"] - comparacao["projecao"]
    comparacao["suficiente"] = comparacao["diferenca"] >= 0
    return comparacao


# --------------------------------------------------------------------------------------
# 8. Grade mensal (Jan-Dez) — pedido explícito do usuário, com layout de referência
#    (um mock de relatório da SPO/MEC anexado na conversa): mês já executado mostra o
#    valor REAL da base mensal; mês futuro mostra a projeção da regra da rubrica. O
#    objetivo é o mesmo do resto do módulo ("a dotação é suficiente?"), só que agora
#    mês a mês, via `saldo_remanescente` — não um total único do exercício.
# --------------------------------------------------------------------------------------

MESES_NOMES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
#: junho = antecipação, novembro = parcela final — mesmo padrão real de pagamento do
#: 13º salário do funcionalismo público federal (decisão 6, confirmada pelo usuário).
#: Números de 1-12 (não 0-11), convertidos para índice de lista onde usados.
MES_ANTECIPACAO_DECIMO_TERCEIRO = 6
MES_PARCELA_DECIMO_TERCEIRO = 11


@dataclass
class ResultadoGradeMensal:
    linhas: pd.DataFrame  # colunas: grupo, natureza_despesa_cod, natureza_detalhada_desc, meses (list[float|None], 12), regra_aplicada, ultimo_mes_real
    ano: int
    ano_mes_referencia: int
    erros: list[str] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.erros

    def total_por_grupo_por_mes(self) -> pd.DataFrame:
        """Uma linha por grupo, uma coluna por mês (1-12) — soma de todas as rubricas
        daquele grupo, preservando nulo (`None`) só quando TODAS as rubricas do grupo
        naquele mês são nulas (mesmo espírito de `sum(min_count=1)` do resto do
        projeto)."""

        por_grupo: dict[str, list[float | None]] = {}
        for grupo, grupo_df in self.linhas.groupby("grupo"):
            totais_mes: list[float | None] = []
            for indice_mes in range(12):
                valores = [linha[indice_mes] for linha in grupo_df["meses"] if linha[indice_mes] is not None]
                totais_mes.append(sum(valores) if valores else None)
            por_grupo[grupo] = totais_mes
        return pd.DataFrame(por_grupo, index=range(1, 13)).T


def _distribuir_mes_futuro(
    regra: RegraRubrica, grupo: str, valor_referencia: float | None, meses_a_projetar: list[int],
) -> dict[int, float | None]:
    """Valor projetado (não real) de UMA rubrica para cada mês em `meses_a_projetar`
    (1-12) — a contrapartida mensal de `multiplicador_efetivo`/`projetar`, só que
    distribuída no tempo em vez de somada num total único. Meses de 13º/parcela extra
    (jun/nov) só recebem o acréscimo se estiverem entre os meses a projetar — um
    exercício cujo mês de referência já passa de novembro não teria mês futuro
    nenhum para receber a parcela, e tudo bem: ela já teria sido paga (real)."""

    if regra.tipo == REGRA_ZERO:
        return {mes: 0.0 for mes in meses_a_projetar}
    if valor_referencia is None:
        return {mes: None for mes in meses_a_projetar}
    valor_referencia = float(valor_referencia)

    if regra.tipo == REGRA_DECIMO_TERCEIRO:
        metade = valor_referencia / 2
        return {
            mes: (metade if mes in (MES_ANTECIPACAO_DECIMO_TERCEIRO, MES_PARCELA_DECIMO_TERCEIRO) else 0.0)
            for mes in meses_a_projetar
        }
    if regra.tipo == REGRA_PROPORCAO_HISTORICA:
        # sem padrão temporal confirmado pelo usuário (diferente do 13º, decisão 6 só
        # cobriu 13º/parcela extra dos multiplicadores) — distribuído em partes iguais
        # pelos meses restantes como simplificação documentada, não presumida como
        # regra definitiva. Ver docstring do módulo.
        return {mes: valor_referencia for mes in meses_a_projetar}
    # REGRA_MULTIPLICADOR / REGRA_SENTENCA_POR_GRUPO / REGRA_INDENIZACAO_POR_GRUPO: valor cheio em todo mês futuro,
    # mais a fração "acima de 12" do multiplicador, metade em cada mês de 13º.
    multiplicador = multiplicador_efetivo(regra, grupo)
    extra_total = valor_referencia * (multiplicador - 12.0)
    metade_extra = extra_total / 2
    resultado: dict[int, float | None] = {}
    for mes in meses_a_projetar:
        valor = valor_referencia
        if mes in (MES_ANTECIPACAO_DECIMO_TERCEIRO, MES_PARCELA_DECIMO_TERCEIRO):
            valor += metade_extra
        resultado[mes] = valor
    return resultado


def grade_mensal(mensal_df: pd.DataFrame, anual_df: pd.DataFrame, ano: int, ano_mes_referencia: int) -> ResultadoGradeMensal:
    """Uma linha por (grupo, natureza de despesa, natureza detalhada) do escopo de
    pessoal, com uma lista de 12 valores (Jan-Dez de `ano`): mês já presente na base
    mensal usa o valor REAL (Liquidada); mês futuro usa a projeção da regra da rubrica
    (`_distribuir_mes_futuro`). `ano_mes_referencia` (formato AAAAMM) é o mês cujo valor
    alimenta a projeção dos meses futuros — mesmo parâmetro de `projetar`."""

    escopo_mensal = filtrar_escopo(mensal_df)
    do_ano = escopo_mensal.loc[
        (escopo_mensal["ano_mes"] // 100 == ano) & (escopo_mensal["tipo_linha"] == "item_execucao")
    ]
    # "Real" = até o mês de referência (inclusive), não "qualquer mês que apareça no
    # arquivo": a extração mensal pode já trazer o mês seguinte com todas as linhas
    # zeradas (folha ainda não fechada na data da extração — foi exatamente por isso
    # que `ultimo_mes_fechado` existe, para não escolher um mês incompleto como
    # referência). Amarrar aqui ao mês de referência escolhido evita o mesmo problema
    # nesta grade: sem isso, um mês "presente mas zerado" aparecia como executado
    # zero em vez de projetado — visualmente indistinguível de "não tivemos despesa
    # nenhuma naquele mês", o que é enganoso.
    meses_reais_presentes = list(range(1, (ano_mes_referencia % 100) + 1))

    colunas_chave = ["grupo", "natureza_despesa_cod", "natureza_despesa_desc", "natureza_detalhada_cod", "natureza_detalhada_desc"]
    reais_por_mes = do_ano.groupby([*colunas_chave, "ano_mes"])["liquidada"].sum(min_count=1).reset_index()

    valor_ref = valor_mes_referencia(mensal_df, ano_mes_referencia)

    chaves = pd.concat([reais_por_mes[colunas_chave], valor_ref[colunas_chave]], ignore_index=True).drop_duplicates()

    meses_futuros = [mes for mes in range(1, 13) if mes not in meses_reais_presentes]

    erros: list[str] = []
    alertas: list[str] = []
    linhas = []
    for chave in chaves.itertuples(index=False):
        regra = regra_para_natureza(chave.natureza_despesa_cod, chave.natureza_detalhada_cod)
        if regra is None:
            mensagem = (
                f"Sem regra de projeção para natureza {chave.natureza_despesa_cod} "
                f"({chave.natureza_despesa_desc}), detalhada {chave.natureza_detalhada_cod} "
                f"({chave.natureza_detalhada_desc}), grupo {chave.grupo}."
            )
            if chave.grupo in (GRUPO_ATIVO, GRUPO_INATIVO, GRUPO_RPPS):
                erros.append(mensagem)
                regra = None
            else:
                alertas.append(mensagem + " Aplicado o padrão x12 da decisão 5.")
                regra = _regra(str(chave.natureza_despesa_cod), str(chave.natureza_despesa_desc), REGRA_MULTIPLICADOR, MULTIPLICADOR_12)

        if regra is not None and regra.tipo == REGRA_DECIMO_TERCEIRO:
            # Ver decisão 8 / `_valor_referencia_natureza_mae`: nunca o mês de referência
            # da própria rubrica de 13º (só tem valor real em jun/nov).
            valor_referencia = _valor_referencia_natureza_mae(valor_ref, chave.grupo, chave.natureza_despesa_cod)
        else:
            linha_ref = valor_ref.loc[
                (valor_ref["grupo"] == chave.grupo)
                & (valor_ref["natureza_despesa_cod"] == chave.natureza_despesa_cod)
                & (valor_ref["natureza_detalhada_cod"] == chave.natureza_detalhada_cod)
            ]
            valor_referencia = float(linha_ref.iloc[0]["valor_mes_referencia"]) if len(linha_ref) and pd.notna(linha_ref.iloc[0]["valor_mes_referencia"]) else None

        projetados = _distribuir_mes_futuro(regra, chave.grupo, valor_referencia, meses_futuros) if regra is not None else {mes: None for mes in meses_futuros}

        reais_desta_linha_df = reais_por_mes.loc[
            (reais_por_mes["grupo"] == chave.grupo)
            & (reais_por_mes["natureza_despesa_cod"] == chave.natureza_despesa_cod)
            & (reais_por_mes["natureza_detalhada_cod"] == chave.natureza_detalhada_cod)
        ]
        reais_desta_linha = reais_desta_linha_df.set_index(reais_desta_linha_df["ano_mes"] % 100)["liquidada"]

        meses_valores: list[float | None] = []
        for mes in range(1, 13):
            if mes in meses_reais_presentes:
                valor = reais_desta_linha.get(mes)
                meses_valores.append(float(valor) if pd.notna(valor) else None)
            else:
                meses_valores.append(projetados.get(mes))

        linhas.append({
            "grupo": chave.grupo,
            "natureza_despesa_cod": chave.natureza_despesa_cod,
            "natureza_despesa_desc": chave.natureza_despesa_desc,
            "natureza_detalhada_cod": chave.natureza_detalhada_cod,
            "natureza_detalhada_desc": chave.natureza_detalhada_desc,
            "meses": meses_valores,
            "regra_aplicada": regra.tipo if regra is not None else "SEM_REGRA",
        })

    return ResultadoGradeMensal(
        linhas=pd.DataFrame(linhas), ano=ano, ano_mes_referencia=ano_mes_referencia, erros=erros, alertas=alertas,
    )


#: chave de uma rubrica dentro da grade — a mesma tripla usada em toda a grade mensal.
ChaveRubrica = tuple[str, str, str]  # (grupo, natureza_despesa_cod, natureza_detalhada_cod)


def aplicar_overrides(grade: ResultadoGradeMensal, overrides: dict[ChaveRubrica, dict[int, float]]) -> ResultadoGradeMensal:
    """Substitui, na grade, os valores projetados por edição manual do usuário (pedido
    explícito: "os meses que ainda virão é que devem poder ser editados").

    SÓ mexe em meses FUTUROS (`mes > grade.ano_mes_referencia % 100`) — um mês que já
    tem execução real na base mensal nunca é sobrescrito por aqui, mesmo que
    `overrides` contenha uma chave para ele: o dado real é sempre a fonte da verdade
    (mesmo princípio do resto do projeto, AGENTS.md — "dados financeiros não podem ser
    silenciosamente descartados"). Devolve uma NOVA `ResultadoGradeMensal` (não muda a
    original in-place), para o chamador poder comparar antes/depois se precisar."""

    ultimo_mes_real = grade.ano_mes_referencia % 100
    linhas = grade.linhas.copy()
    novas_listas_meses = []
    for _, linha in linhas.iterrows():
        chave = (linha["grupo"], linha["natureza_despesa_cod"], linha["natureza_detalhada_cod"])
        meses = list(linha["meses"])
        substituicoes = overrides.get(chave, {})
        for mes, valor in substituicoes.items():
            if mes > ultimo_mes_real:
                meses[mes - 1] = valor
        novas_listas_meses.append(meses)
    linhas["meses"] = novas_listas_meses
    return ResultadoGradeMensal(
        linhas=linhas, ano=grade.ano, ano_mes_referencia=grade.ano_mes_referencia,
        erros=grade.erros, alertas=grade.alertas,
    )


def saldo_remanescente(grade: ResultadoGradeMensal, dotacao_por_grupo: pd.Series) -> pd.DataFrame:
    """Saldo acumulado por grupo, mês a mês: Dotação Atualizada (fixa no ano) menos a
    soma acumulada (executado real + projetado) até aquele mês — decisão 6, confirmada
    pelo usuário ("Dotação Atualizada menos o acumulado até aquele mês"). Um saldo
    negativo num mês futuro sinaliza que a dotação se esgota antes do fim do exercício,
    NA DATA-BASE atual — o objetivo central deste módulo, aplicado mês a mês em vez de
    só ao total anual (ver `comparar_com_dotacao` para a versão agregada)."""

    totais = grade.total_por_grupo_por_mes()
    linhas = []
    for grupo in totais.index:
        dotacao = float(dotacao_por_grupo.get(grupo)) if grupo in dotacao_por_grupo.index and pd.notna(dotacao_por_grupo.get(grupo)) else None
        acumulado = 0.0
        saldos: list[float | None] = []
        for mes in range(1, 13):
            valor_mes = totais.loc[grupo, mes]
            if valor_mes is not None:
                acumulado += valor_mes
            saldos.append((dotacao - acumulado) if dotacao is not None else None)
        linhas.append({"grupo": grupo, "meses": saldos})
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------------------
# 9. Consolidação por elemento — pedido explícito do usuário: a grade "Rubrica × Mês"
#    da interface não deve descer até o nível de sub-detalhe (natureza detalhada) da
#    base bruta, e sim ficar no nível de ELEMENTO de despesa — o mesmo nível da
#    metodologia do briefing original (ED_04, ED_11/12 etc.) e da referência visual que
#    o usuário anexou. As únicas exceções são as rubricas com regra de projeção PRÓPRIA
#    (13º salário, proporção histórica): são conceitualmente diferentes do elemento
#    "mãe" — seguem uma regra diferente da dele, não uma variação dela — por isso
#    continuam em linha própria (mesmo padrão da referência visual: "SUB11/12_43 13º
#    SALARIO" aparece à parte de "ED_11/12 VENC E VANT FIXAS EXCL 13º/FÉRIAS").
# --------------------------------------------------------------------------------------

def _elemento_de_despesa(natureza_despesa_cod: str) -> str:
    """Os 2 últimos dígitos da natureza de despesa (6 dígitos: categoria+grupo+
    modalidade+elemento, ex. 319004 = 3-1-90-04) — o elemento de despesa "de verdade"
    do orçamento público, independente da modalidade de aplicação (90 = direta, 91 =
    intra-orçamentária). Ex.: 319004 e 319104 são o MESMO elemento (04), só a
    modalidade muda — devem consolidar na mesma linha, não em duas."""

    codigo = str(natureza_despesa_cod)
    return codigo[-2:] if len(codigo) >= 2 else codigo


def consolidar_por_elemento(grade: ResultadoGradeMensal) -> ResultadoGradeMensal:
    """Devolve uma NOVA `ResultadoGradeMensal` com uma linha por (grupo, elemento de
    despesa) em vez de uma linha por (grupo, natureza de despesa completa, sub-
    detalhe) — soma os meses das naturezas detalhadas que caem no mesmo ELEMENTO
    (`_elemento_de_despesa`, últimos 2 dígitos — funde modalidade direta/intra-
    orçamentária da mesma rubrica, ex. 319004+319104), preservando nulo≠zero (só vira
    `None` se TODAS as parcelas daquele mês forem nulas). O código/descrição
    representativos da linha consolidada são os da natureza de MENOR código dentro do
    elemento (a modalidade 90/direta, quando existe, por ordenação lexicográfica —
    '...004' < '...104'). Chamar logo após `grade_mensal()`, antes de
    `aplicar_overrides()` — os overrides passam a se referir à linha JÁ consolidada
    (mesma chave `(grupo, natureza_despesa_cod, natureza_detalhada_cod)`, só que aqui
    `natureza_detalhada_cod` é um valor-âncora igual ao próprio `natureza_despesa_cod`
    escolhido como representante, não necessariamente um código real da base)."""

    linhas = grade.linhas
    mascara_especiais = linhas["regra_aplicada"].isin([REGRA_DECIMO_TERCEIRO, REGRA_PROPORCAO_HISTORICA])
    especiais = linhas[mascara_especiais].copy()
    regulares = linhas[~mascara_especiais].copy()
    regulares["elemento"] = regulares["natureza_despesa_cod"].map(_elemento_de_despesa)

    consolidadas = []
    for (grupo, elemento), subgrupo in regulares.groupby(["grupo", "elemento"], dropna=False):
        meses_somados: list[float | None] = []
        for indice in range(12):
            valores = [linha[indice] for linha in subgrupo["meses"] if linha[indice] is not None]
            meses_somados.append(sum(valores) if valores else None)
        primeira = subgrupo.sort_values("natureza_despesa_cod").iloc[0]
        consolidadas.append({
            "grupo": grupo,
            "natureza_despesa_cod": primeira["natureza_despesa_cod"],
            "natureza_despesa_desc": primeira["natureza_despesa_desc"],
            "natureza_detalhada_cod": primeira["natureza_despesa_cod"],
            "natureza_detalhada_desc": primeira["natureza_despesa_desc"],
            "meses": meses_somados,
            "regra_aplicada": primeira["regra_aplicada"],
        })

    resultado = pd.concat([pd.DataFrame(consolidadas), especiais], ignore_index=True)
    return ResultadoGradeMensal(
        linhas=resultado, ano=grade.ano, ano_mes_referencia=grade.ano_mes_referencia,
        erros=grade.erros, alertas=grade.alertas,
    )


# --------------------------------------------------------------------------------------
# 10. Layout fixo da aba Ativo — pedido explícito do usuário (10/09/2026), reproduzindo
#     a lista de linhas de um relatório-modelo anexado: só ED_04/07/11-12/RGPS(13)/
#     16-17/91(Sentenças)/92/94/96 aparecem, com os elementos 11 e 12 fundidos numa
#     única linha "Vencimentos e Vantagens Fixas (excl. 13º/férias)" — dentro dela, só 4
#     sub-rubricas ganham linha própria (13º, Abono Pecuniário, Abono Constitucional,
#     Adiantamento de Férias — as 4 já tratadas como regra própria acima); qualquer
#     outra sub-rubrica de 11/12 (ex. adicional noturno, gratificações) soma dentro da
#     própria linha ED_11/12. Um elemento fora desta lista, se aparecer na execução
#     real, NUNCA some silenciosamente — vai para uma linha residual "Outros / Não
#     Classificado" com ALERTA (mesmo princípio do resto do módulo, decisão 3/5: dado
#     financeiro real não é descartado sem sinalização). Só afeta o grupo Ativo —
#     Inativo/RPPS/Outros Benefícios não usam este layout curado.
# --------------------------------------------------------------------------------------

#: (chave de exibição, elementos que ela agrega, descrição da linha).
_LINHAS_RELATORIO_ATIVO: list[tuple[str, tuple[str, ...], str]] = [
    ("04", ("04",), "Contratação por Tempo Determinado"),
    ("07", ("07",), "Contribuição a Entidade Fechada de Previdência"),
    ("11/12", ("11", "12"), "Vencimentos e Vantagens Fixas — Pessoal Civil (excl. 13º/férias)"),
    ("13", ("13",), "Obrigações Patronais (RGPS)"),
    ("16/17", ("16", "17"), "Outras Despesas Variáveis — Pessoal Civil"),
    ("91", ("91",), "Sentenças Judiciais"),
    ("92", ("92",), "Despesas de Exercícios Anteriores"),
    ("94", ("94",), "Indenizações e Restituições Trabalhistas"),
    ("96", ("96",), "Ressarcimento de Despesa de Pessoal Requisitado"),
]
_ELEMENTO_PARA_LINHA_ATIVO: dict[str, str] = {
    elemento: chave for chave, elementos, _ in _LINHAS_RELATORIO_ATIVO for elemento in elementos
}
_DESCRICAO_LINHA_ATIVO: dict[str, str] = {chave: desc for chave, _, desc in _LINHAS_RELATORIO_ATIVO}
#: linha residual para elemento fora da lista fixa acima (não deve ocorrer com a
#: execução real conhecida em 10/09/2026 — existe só para nunca esconder dinheiro).
_LINHA_ATIVO_OUTROS = "outros"


def consolidar_relatorio_ativo(grade: ResultadoGradeMensal) -> ResultadoGradeMensal:
    """Restringe e reagrupa SÓ o grupo Ativo ao layout fixo descrito acima — chamar
    depois de `consolidar_por_elemento()`. Linhas de outros grupos (Inativo/RPPS/
    Outros Benefícios) atravessam sem alteração."""

    linhas = grade.linhas
    fora_ativo = linhas[linhas["grupo"] != GRUPO_ATIVO]
    ativo = linhas[linhas["grupo"] == GRUPO_ATIVO].copy()
    if ativo.empty:
        return ResultadoGradeMensal(
            linhas=linhas.copy(), ano=grade.ano, ano_mes_referencia=grade.ano_mes_referencia,
            erros=grade.erros, alertas=grade.alertas,
        )

    ativo["elemento"] = ativo["natureza_despesa_cod"].map(_elemento_de_despesa)
    # só as 4 sub-rubricas de 11/12 com regra própria (13º/proporção histórica) ganham
    # linha separada — a mesma regra aplicada a outro elemento (ex. 13º do contrato
    # temporário, elemento 04) funde de volta na linha regular do elemento.
    mascara_subitem = (
        ativo["regra_aplicada"].isin([REGRA_DECIMO_TERCEIRO, REGRA_PROPORCAO_HISTORICA])
        & ativo["elemento"].isin(("11", "12"))
    )
    subitens = ativo[mascara_subitem].drop(columns="elemento")
    regulares = ativo[~mascara_subitem].copy()
    regulares["linha_relatorio"] = regulares["elemento"].map(_ELEMENTO_PARA_LINHA_ATIVO).fillna(_LINHA_ATIVO_OUTROS)

    alertas = list(grade.alertas)
    fora_da_lista = regulares.loc[regulares["linha_relatorio"] == _LINHA_ATIVO_OUTROS]
    if not fora_da_lista.empty:
        codigos = ", ".join(sorted(fora_da_lista["natureza_despesa_cod"].unique()))
        alertas.append(
            f"Ativo: natureza(s) {codigos} fora da lista fixa do relatório-modelo (ED_04/07/11-12/13/16-17/"
            "91/92/94/96) — somadas em \"Outros / Não Classificado\" para não descartar valor real."
        )

    consolidadas = []
    for linha_relatorio, subgrupo in regulares.groupby("linha_relatorio"):
        meses_somados: list[float | None] = []
        for indice in range(12):
            valores = [linha[indice] for linha in subgrupo["meses"] if linha[indice] is not None]
            meses_somados.append(sum(valores) if valores else None)
        desc = _DESCRICAO_LINHA_ATIVO.get(linha_relatorio, "Outros / Não Classificado")
        consolidadas.append({
            "grupo": GRUPO_ATIVO,
            "natureza_despesa_cod": linha_relatorio,
            "natureza_despesa_desc": desc,
            "natureza_detalhada_cod": linha_relatorio,
            "natureza_detalhada_desc": desc,
            "meses": meses_somados,
            "regra_aplicada": subgrupo.iloc[0]["regra_aplicada"],
        })

    resultado = pd.concat([fora_ativo, pd.DataFrame(consolidadas), subitens], ignore_index=True)
    return ResultadoGradeMensal(
        linhas=resultado, ano=grade.ano, ano_mes_referencia=grade.ano_mes_referencia,
        erros=grade.erros, alertas=alertas,
    )


# --------------------------------------------------------------------------------------
# 11. Outros Benefícios por PLANO ORÇAMENTÁRIO — pedido explícito do usuário (10/09/2026):
#     "não desejo ver por elemento de despesa [...] cada plano orçamentário dessas ações
#     se referem a um benefício específico [...] gostaria que a aba se concentrasse nesse
#     aspecto de evidenciação por plano orçamentário". Achado ao investigar a base real: um
#     único Plano Orçamentário mistura VÁRIAS naturezas de despesa com regras de projeção
#     DIFERENTES entre si (ex. PO "Assistência Pré-Escolar" combina 339004 ×13,3333, 339008
#     ×12 e 339092 zero) — e a MESMA natureza aparece em POs diferentes (ex. 339004 aparece
#     em "Assistência Pré-Escolar", "Auxílio-Transporte" E "Auxílio-Alimentação). Por isso a
#     regra ainda é resolvida por Natureza de Despesa (como no resto do módulo), mas a soma
#     mensal por PO acontece ANTES de virar uma linha — não é uma "natureza mãe com
#     sub-rubricas especiais" como o caso do elemento 11/12 em `consolidar_relatorio_ativo`:
#     aqui o PO de fato mistura naturezas heterogêneas por definição, não faz sentido
#     mostrar sub-linha nenhuma separada. Confirmado que a Dotação Anual tem a MESMA
#     dimensão (`plano_orcamentario_codigo`), permitindo comparar dotação × projeção no
#     nível de PO (`dotacao_atualizada_por_plano_orcamentario`, seção 7).
#
#     Reaproveita o schema de `ResultadoGradeMensal` (mesmo formato de `grade_mensal`) para
#     não exigir nenhuma mudança em `aplicar_overrides`/`saldo_remanescente`/
#     `total_por_grupo_por_mes` (todos genéricos, só enxergam uma chave `(grupo, dim1,
#     dim2)`) — `natureza_despesa_cod`/`_desc` guardam `acao_cod`/nome da Ação;
#     `natureza_detalhada_cod`/`_desc` guardam `po_cod`/`po_desc`.
# --------------------------------------------------------------------------------------

#: colunas usadas para resolver a REGRA de cada fatia (Ação, PO, Natureza) antes de somar
#: por PO — description columns (po_desc/acao_desc) ficam DE FORA de propósito: a mesma
#: dupla (acao_cod, po_cod) já apareceu com descrições ligeiramente diferentes entre
#: exercícios na base real (ex. "AUXILIO-TRANSPORTE DE CIVIS" vs "...CIVIS ATIVOS") —
#: incluir a descrição na chave fragmentaria um PO em 2 linhas por causa só do texto.
_COLUNAS_FINAS_BENEFICIOS = [
    "grupo", "acao_cod", "po_cod",
    "natureza_despesa_cod", "natureza_despesa_desc",
    "natureza_detalhada_cod", "natureza_detalhada_desc",
]


def _escopo_beneficios(df: pd.DataFrame) -> pd.DataFrame:
    return filtrar_escopo(df).loc[lambda d: d["grupo"] == GRUPO_OUTROS_BENEFICIOS]


def _rotulos_po(df: pd.DataFrame) -> dict[tuple[str, str], tuple[str, str]]:
    """`(acao_cod, po_cod) -> (acao_desc, po_desc)` — a primeira descrição não nula vista
    para cada dupla (ver nota acima sobre por que a descrição fica fora da chave)."""

    escopo = _escopo_beneficios(df)
    rotulos: dict[tuple[str, str], tuple[str, str]] = {}
    for linha in escopo[["acao_cod", "acao_desc", "po_cod", "po_desc"]].dropna(subset=["acao_cod", "po_cod"]).itertuples(index=False):
        chave = (linha.acao_cod, linha.po_cod)
        if chave not in rotulos:
            rotulos[chave] = (linha.acao_desc, linha.po_desc)
    return rotulos


def valor_mes_referencia_beneficios(mensal_df: pd.DataFrame, ano_mes: int) -> pd.DataFrame:
    """Como `valor_mes_referencia`, mas só Outros Benefícios e por (Ação, Plano
    Orçamentário) em vez de Natureza de Despesa — mesma granularidade de exibição de
    `grade_mensal_beneficios`, usada para a coluna "Base PLOA" dos filhos dessa aba."""

    escopo = _escopo_beneficios(mensal_df)
    do_mes = escopo.loc[(escopo["ano_mes"] == ano_mes) & (escopo["tipo_linha"] == "item_execucao")]
    por_natureza = do_mes.groupby(_COLUNAS_FINAS_BENEFICIOS, dropna=False)["liquidada"].sum(min_count=1)
    por_po = por_natureza.groupby(["grupo", "acao_cod", "po_cod"]).sum(min_count=1).reset_index()
    return por_po.rename(columns={
        "liquidada": "valor_mes_referencia", "acao_cod": "natureza_despesa_cod", "po_cod": "natureza_detalhada_cod",
    })


def execucao_ano_anterior_beneficios(anual_df: pd.DataFrame, ano: int) -> pd.DataFrame:
    """Como `execucao_ano_anterior`, mas só Outros Benefícios e por (Ação, Plano
    Orçamentário) — mesma granularidade de `grade_mensal_beneficios`, usada para a
    coluna "Execução Ano Anterior" dos filhos dessa aba."""

    escopo = _escopo_beneficios(anual_df)
    do_ano = escopo.loc[escopo["ano"] == ano]
    por_natureza = do_ano.groupby(_COLUNAS_FINAS_BENEFICIOS, dropna=False)["empenhada"].sum(min_count=1)
    por_po = por_natureza.groupby(["grupo", "acao_cod", "po_cod"]).sum(min_count=1).reset_index()
    return por_po.rename(columns={
        "empenhada": "execucao_ano_anterior", "acao_cod": "natureza_despesa_cod", "po_cod": "natureza_detalhada_cod",
    })


def grade_mensal_beneficios(mensal_df: pd.DataFrame, anual_df: pd.DataFrame, ano: int, ano_mes_referencia: int) -> ResultadoGradeMensal:
    """Grade mensal de Outros Benefícios por PLANO ORÇAMENTÁRIO — ver docstring da seção
    11 acima para o raciocínio completo. Regra ausente aqui nunca é erro (mesma
    tolerância da decisão 5 — ações fora do relatório-modelo original), só alerta com o
    padrão ×12."""

    escopo_mensal = _escopo_beneficios(mensal_df)
    do_ano = escopo_mensal.loc[
        (escopo_mensal["ano_mes"] // 100 == ano) & (escopo_mensal["tipo_linha"] == "item_execucao")
    ]
    meses_reais_presentes = list(range(1, (ano_mes_referencia % 100) + 1))

    reais_por_mes = do_ano.groupby([*_COLUNAS_FINAS_BENEFICIOS, "ano_mes"])["liquidada"].sum(min_count=1).reset_index()

    escopo_referencia = escopo_mensal.loc[
        (escopo_mensal["ano_mes"] == ano_mes_referencia) & (escopo_mensal["tipo_linha"] == "item_execucao")
    ]
    valor_ref = (
        escopo_referencia.groupby(_COLUNAS_FINAS_BENEFICIOS, dropna=False)["liquidada"].sum(min_count=1).reset_index()
        .rename(columns={"liquidada": "valor_mes_referencia"})
    )

    chaves = pd.concat(
        [reais_por_mes[_COLUNAS_FINAS_BENEFICIOS], valor_ref[_COLUNAS_FINAS_BENEFICIOS]], ignore_index=True,
    ).drop_duplicates()
    meses_futuros = [mes for mes in range(1, 13) if mes not in meses_reais_presentes]
    rotulos = _rotulos_po(mensal_df)

    alertas: list[str] = []
    #: acumula os meses de TODAS as naturezas do mesmo (acao_cod, po_cod) antes de virar
    #: uma linha — um Plano Orçamentário mistura naturezas de fato (ver docstring da
    #: seção), não é uma "mãe" com sub-rubricas especiais como o elemento 11/12 do Ativo.
    acumulado: dict[tuple[str, str], list[list[float | None]]] = {}

    for chave in chaves.itertuples(index=False):
        regra = regra_para_natureza(chave.natureza_despesa_cod, chave.natureza_detalhada_cod)
        if regra is None:
            alertas.append(
                f"Outros Benefícios (PO {chave.po_cod}): sem regra de projeção para natureza "
                f"{chave.natureza_despesa_cod} ({chave.natureza_despesa_desc}), detalhada "
                f"{chave.natureza_detalhada_cod} ({chave.natureza_detalhada_desc}). Aplicado o "
                "padrão x12 da decisão 5."
            )
            regra = _regra(str(chave.natureza_despesa_cod), str(chave.natureza_despesa_desc), REGRA_MULTIPLICADOR, MULTIPLICADOR_12)

        linha_ref = valor_ref.loc[
            (valor_ref["acao_cod"] == chave.acao_cod) & (valor_ref["po_cod"] == chave.po_cod)
            & (valor_ref["natureza_despesa_cod"] == chave.natureza_despesa_cod)
            & (valor_ref["natureza_detalhada_cod"] == chave.natureza_detalhada_cod)
        ]
        valor_referencia = float(linha_ref.iloc[0]["valor_mes_referencia"]) if len(linha_ref) and pd.notna(linha_ref.iloc[0]["valor_mes_referencia"]) else None

        projetados = _distribuir_mes_futuro(regra, GRUPO_OUTROS_BENEFICIOS, valor_referencia, meses_futuros)

        reais_desta_linha_df = reais_por_mes.loc[
            (reais_por_mes["acao_cod"] == chave.acao_cod) & (reais_por_mes["po_cod"] == chave.po_cod)
            & (reais_por_mes["natureza_despesa_cod"] == chave.natureza_despesa_cod)
            & (reais_por_mes["natureza_detalhada_cod"] == chave.natureza_detalhada_cod)
        ]
        reais_desta_linha = reais_desta_linha_df.set_index(reais_desta_linha_df["ano_mes"] % 100)["liquidada"]

        meses_valores: list[float | None] = []
        for mes in range(1, 13):
            if mes in meses_reais_presentes:
                valor = reais_desta_linha.get(mes)
                meses_valores.append(float(valor) if pd.notna(valor) else None)
            else:
                meses_valores.append(projetados.get(mes))

        chave_po = (chave.acao_cod, chave.po_cod)
        acumulado.setdefault(chave_po, []).append(meses_valores)

    linhas = []
    for (acao_cod, po_cod), listas_meses in acumulado.items():
        acao_desc, po_desc = rotulos.get((acao_cod, po_cod), (acao_cod, po_cod))
        meses_somados: list[float | None] = []
        for indice in range(12):
            valores = [m[indice] for m in listas_meses if m[indice] is not None]
            meses_somados.append(sum(valores) if valores else None)
        linhas.append({
            "grupo": GRUPO_OUTROS_BENEFICIOS,
            "natureza_despesa_cod": acao_cod,
            "natureza_despesa_desc": acao_desc,
            "natureza_detalhada_cod": po_cod,
            "natureza_detalhada_desc": po_desc,
            "meses": meses_somados,
            "regra_aplicada": "plano_orcamentario",
        })

    return ResultadoGradeMensal(
        linhas=pd.DataFrame(linhas), ano=ano, ano_mes_referencia=ano_mes_referencia, erros=[], alertas=alertas,
    )


def substituir_beneficios_por_plano_orcamentario(
    grade: ResultadoGradeMensal, mensal_df: pd.DataFrame, anual_df: pd.DataFrame,
) -> ResultadoGradeMensal:
    """Troca, dentro de `grade` (já passada por `consolidar_por_elemento`/
    `consolidar_relatorio_ativo`), as linhas do grupo Outros Benefícios — hoje por
    elemento de despesa — pelas linhas por Plano Orçamentário de
    `grade_mensal_beneficios` (ver seção 11). Ativo/Inativo/RPPS não são tocados.
    Chamar como último passo antes de `aplicar_overrides()`."""

    beneficios = grade_mensal_beneficios(mensal_df, anual_df, grade.ano, grade.ano_mes_referencia)
    linhas = pd.concat([
        grade.linhas.loc[grade.linhas["grupo"] != GRUPO_OUTROS_BENEFICIOS],
        beneficios.linhas,
    ], ignore_index=True)
    # Os alertas de "sem regra" por Natureza (gerados por `grade_mensal` sobre as linhas
    # que acabamos de descartar acima) ficariam redundantes com os, mais precisos, que
    # `grade_mensal_beneficios` já gera por PO (mesmo gap, mas apontando o Plano
    # Orçamentário em vez de só a natureza) — mantém só os de outros grupos.
    alertas_sem_duplicar = [a for a in grade.alertas if "grupo outros_beneficios" not in a]
    return ResultadoGradeMensal(
        linhas=linhas, ano=grade.ano, ano_mes_referencia=grade.ano_mes_referencia,
        erros=grade.erros + beneficios.erros, alertas=alertas_sem_duplicar + beneficios.alertas,
    )
