"""Regras de tela de Empenhos com Execução Retardada — sem Streamlit.

Camada: regra de apresentação. Recebe a base de Execução Mensal já lida e um ESTADO de tela
(dicionário simples guardado pela página em `st.session_state`) e devolve o pacote de dados que
o componente visual da página (`src/ui_empenhos_retardada_componente.py`) desenha. As ações do
usuário (filtrar, ordenar, ligar corte, abrir detalhe...) voltam do componente como dicionários e
são aplicadas por `aplicar_acao`, que só devolve um novo estado.

Por que existe (17/10/2026, pedido explícito: a página inteira com o layout do mockup aprovado):
a tela deixou de ser montada com widgets nativos do Streamlit; para a regra de negócio não ficar
presa ao HTML/JS do componente, tudo que decide O QUE aparece mora aqui e é testado sem navegador
(`tests/test_empenhos_retardada_tela.py`). As regras são as MESMAS já validadas na página
(docstring de `app_pages/empenhos_execucao_retardada.py`), só mudaram de lugar:

  * busca livre restringe as NEs (todas as linhas da NE) antes de calcular as opções dos filtros;
  * filtros por atributo combinados (vários valores = OU dentro do campo, E entre campos), com
    opções em cascata mútua — cada campo só oferece valores com registro dado o que está
    selecionado em TODOS os outros (mesma lógica de `src/ui_filtros_execucao.py`, reaproveitando
    `option_mapping`/`apply_filters` de lá);
  * seleção persistida que deixou de existir nas opções é descartada (como o multiselect fazia);
  * saldo por NE via `saldo_por_ne(agregar_por_ne(...))`; `percentual_saldo` nulo quando o
    empenhado é nulo ou zero (a NE continua na lista);
  * cortes em R$ e em %, independentes, combinados por OU (padrão) ou E; NE com saldo/percentual
    nulo nunca passa do corte; nenhum corte ligado é estado válido (aviso, sem lista em destaque);
  * lista da tela = lista do relatório (`montar_lista_relatorio`), paginada em `TAMANHO_PAGINA`;
  * (17/10/2026, regra definida pelo usuário) idade do saldo em meses e um terceiro corte,
    "empenho há N meses ou mais com saldo", desligado por padrão — ver `idade_por_ne`.

Valores nulos aparecem como "—", nunca como zero; negativos mantêm o sinal.
"""

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd

from src.execucao_ne_utils import detalhar_nota_empenho, ne_curta, saldo_por_ne
from src.relatorio_empenhos_retardada import COLUNA_GRUPO, COLUNA_PASSA_CORTE, montar_lista_relatorio
from src.tesouro_execucao_mensal import agregar_por_ne
from src.ui_filtros_execucao import CampoFiltro, apply_filters, option_mapping

CORTE_RS_PADRAO = 10_000.0
CORTE_PCT_PADRAO = 20.0  # %
CORTE_IDADE_PADRAO = 3  # meses
COLUNA_IDADE = "idade_meses"
TAMANHO_PAGINA = 100

VISAO_DESTAQUE = "Em destaque"
VISAO_TODOS = "Todos no escopo"
SENTIDO_DESC = "desc"
SENTIDO_ASC = "asc"

#: coluna da tabela -> coluna da lista por NE (ordem = ordem das colunas na tela)
COLUNAS_ORDENAVEIS: dict[str, str] = {
    "NE": "ne_ccor",
    "Favorecido": "ne_favorecido",
    "Empenhado": "empenhada",
    "Liquidado": "liquidada",
    "Saldo": "saldo",
    "% Saldo": "percentual_saldo",
    "Idade": COLUNA_IDADE,
}
ORDENACAO_PADRAO = "Saldo"
#: colunas de texto começam de A a Z; números começam do maior
_COLUNAS_TEXTO = ("NE", "Favorecido")

#: rótulo na tela -> coluna da lista por NE ("Credor" = favorecido da NE)
OPCOES_AGRUPAMENTO: dict[str, str | None] = {
    "Sem agrupamento": None,
    "Unidade orçamentária": "unidade_orcamentaria_desc",
    "Credor": "ne_favorecido",
    "Ação de governo": "acao_desc",
}

COLUNAS_BUSCA = [
    "ne_ccor", "ne_descricao", "ne_favorecido", "natureza_detalhada_label",
    "pi_cod", "ptres", "acao_desc", "fonte_desc", "processo_ne",
]

AVISO_BUSCA_VAZIA = "Nenhum empenho encontrado com os filtros informados."
AVISO_FILTROS_VAZIOS = "Nenhum registro corresponde à combinação de filtros selecionada."
AVISO_SEM_CORTE = f'Ligue pelo menos um dos dois cortes acima para ver os empenhos em destaque (ou escolha "{VISAO_TODOS}").'
AVISO_NADA_PASSA = "Nenhum empenho passa do(s) corte(s) ligado(s) acima."


# --------------------------------------------------------------------------- formatação
def formatar_brl(valor: object) -> str:
    """Reais inteiros, ponto de milhar (mesmo padrão já usado na página); nulo vira "—"."""

    if valor is None or pd.isna(valor):
        return "—"
    negativo = valor < 0
    texto = "R$ " + f"{abs(round(float(valor))):,.0f}".replace(",", ".")
    return ("−" if negativo else "") + texto


def formatar_brl_centavos(valor: object) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    texto = f"{abs(float(valor)):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return ("−" if float(valor) < 0 else "") + "R$ " + texto


def formatar_pct(valor: object) -> str:
    if valor is None or pd.isna(valor):
        return "—"
    return f"{float(valor):.1f}%".replace(".", ",")


_MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def formatar_idade(valor: object) -> str:
    """Idade do saldo em meses; nula (exercício anterior ou sem mês de empenho) vira "—"."""

    if valor is None or pd.isna(valor):
        return "—"
    n = int(valor)
    return f"{n} {'mês' if n == 1 else 'meses'}"


def _texto(valor: object) -> str:
    return "—" if valor is None or pd.isna(valor) else str(valor)


def _numero(valor: object) -> float | None:
    return None if valor is None or pd.isna(valor) else float(valor)


# --------------------------------------------------------------------------------- estado
def estado_inicial(ano_extracao: int) -> dict[str, Any]:
    """Estado da primeira renderização: exercício da extração pré-selecionado (só aqui — depois de
    "Limpar filtros" volta para todos, como antes), corte em R$ ligado, corte em % desligado."""

    return {
        "busca": "",
        "filtros": {"ano": [str(ano_extracao)]},
        "usar_rs": True,
        "corte_rs": CORTE_RS_PADRAO,
        "usar_pct": False,
        "corte_pct": CORTE_PCT_PADRAO,
        "usar_idade": False,
        "corte_idade": CORTE_IDADE_PADRAO,
        "modo": "OU",
        "visao": VISAO_DESTAQUE,
        "ordem": ORDENACAO_PADRAO,
        "sentido": SENTIDO_DESC,
        "grupo": "Sem agrupamento",
        "pagina": 1,
        "ne_aberta": None,
    }


def _numero_valido(valor: object, minimo: float, maximo: float | None = None) -> float | None:
    try:
        numero = float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if numero != numero or numero < minimo or (maximo is not None and numero > maximo):
        return None
    return numero


def aplicar_acao(estado: dict[str, Any], acao: object, nomes_filtro: Sequence[str]) -> dict[str, Any]:
    """Aplica uma ação vinda do componente e devolve um NOVO estado (o recebido não muda).

    Ação desconhecida ou com valor inválido é ignorada (estado igual) — o componente é código da
    própria página, mas a entrada vem do navegador e não deve derrubar a tela. Qualquer ação que
    muda a lista (filtro, busca, corte, visão, ordem, agrupamento) volta para a página 1."""

    novo = {**estado, "filtros": dict(estado.get("filtros", {}))}
    if not isinstance(acao, dict):
        return novo
    tipo = acao.get("tipo")
    volta_pagina_1 = True

    if tipo == "busca":
        novo["busca"] = str(acao.get("valor") or "").strip()
    elif tipo == "filtro":
        nome = acao.get("nome")
        valores = acao.get("valores")
        if nome not in nomes_filtro or not isinstance(valores, list):
            return novo
        rotulos = [str(v) for v in valores]
        if rotulos:
            novo["filtros"][nome] = rotulos
        else:
            novo["filtros"].pop(nome, None)
    elif tipo == "limpar":
        novo["busca"] = ""
        novo["filtros"] = {}
    elif tipo in ("usar_rs", "usar_pct", "usar_idade"):
        novo[tipo] = bool(acao.get("valor"))
    elif tipo == "corte_idade":
        numero = _numero_valido(acao.get("valor"), 0.0, 120.0)
        if numero is None or numero != int(numero):
            return novo
        novo["corte_idade"] = int(numero)
    elif tipo == "corte_rs":
        numero = _numero_valido(acao.get("valor"), 0.0)
        if numero is None:
            return novo
        novo["corte_rs"] = numero
    elif tipo == "corte_pct":
        numero = _numero_valido(acao.get("valor"), 0.0, 1000.0)
        if numero is None:
            return novo
        novo["corte_pct"] = numero
    elif tipo == "modo":
        if acao.get("valor") not in ("E", "OU"):
            return novo
        novo["modo"] = acao["valor"]
    elif tipo == "visao":
        if acao.get("valor") not in (VISAO_DESTAQUE, VISAO_TODOS):
            return novo
        novo["visao"] = acao["valor"]
    elif tipo == "ordenar":
        coluna = acao.get("coluna")
        if coluna not in COLUNAS_ORDENAVEIS:
            return novo
        if novo.get("ordem") == coluna:
            novo["sentido"] = SENTIDO_ASC if novo.get("sentido") == SENTIDO_DESC else SENTIDO_DESC
        else:
            novo["ordem"] = coluna
            novo["sentido"] = SENTIDO_ASC if coluna in _COLUNAS_TEXTO else SENTIDO_DESC
    elif tipo == "agrupar":
        if acao.get("valor") not in OPCOES_AGRUPAMENTO:
            return novo
        novo["grupo"] = acao["valor"]
    elif tipo == "pagina":
        try:
            novo["pagina"] = max(1, int(acao.get("valor")))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return novo
        volta_pagina_1 = False
    elif tipo == "detalhe":
        novo["ne_aberta"] = str(acao.get("ne")) if acao.get("ne") else None
        volta_pagina_1 = False
    elif tipo == "fechar_detalhe":
        novo["ne_aberta"] = None
        volta_pagina_1 = False
    else:
        return novo

    if volta_pagina_1:
        novo["pagina"] = 1
    return novo


# -------------------------------------------------------------------------------- filtros
def restringir_a_busca(dataframe: pd.DataFrame, busca: str) -> pd.DataFrame:
    """Linhas (nível de execução) das NEs que batem com a busca livre — por `ne_ccor`, todas as
    linhas da NE, para não quebrar `agregar_por_ne` (mesma regra que já existia na página)."""

    if not busca:
        return dataframe
    alvo = busca.strip().lower()
    mascara = pd.Series(False, index=dataframe.index)
    for coluna in COLUNAS_BUSCA:
        if coluna in dataframe.columns:
            mascara = mascara | dataframe[coluna].astype("string").str.lower().str.contains(alvo, na=False, regex=False)
    return dataframe[dataframe["ne_ccor"].isin(set(dataframe.loc[mascara, "ne_ccor"]))]


def aplicar_busca_por_ne(por_ne: pd.DataFrame, busca: str) -> pd.DataFrame:
    """Rede de segurança idempotente sobre a lista já agregada (a restrição principal é
    `restringir_a_busca`, antes de agregar)."""

    if not busca:
        return por_ne
    alvo = busca.strip().lower()
    mascara = pd.Series(False, index=por_ne.index)
    for coluna in COLUNAS_BUSCA:
        if coluna in por_ne.columns:
            mascara = mascara | por_ne[coluna].astype("string").str.lower().str.contains(alvo, na=False, regex=False)
    return por_ne[mascara]


def _selecoes_em_codigos(
    dataframe: pd.DataFrame, campos: Sequence[CampoFiltro], filtros: dict[str, list[str]]
) -> dict[str, list[object]]:
    """Rótulos "código — descrição" selecionados -> códigos brutos, traduzidos contra a base
    inteira (já restrita à busca) — o texto de um código não muda com o recorte."""

    resolvido: dict[str, list[object]] = {}
    for nome, _rotulo, coluna_cod, coluna_desc in campos:
        rotulos = filtros.get(nome) or []
        if not rotulos:
            continue
        mapeamento = option_mapping(dataframe, coluna_cod, coluna_desc)
        valores = [mapeamento[r] for r in rotulos if r in mapeamento]
        if valores:
            resolvido[nome] = valores
    return resolvido


def resolver_filtros(
    dataframe: pd.DataFrame, campos: Sequence[CampoFiltro], filtros: dict[str, list[str]]
) -> tuple[dict[str, list[str]], dict[str, list[object]], dict[str, list[str]]]:
    """Devolve (opções por campo, seleção em códigos, seleção em rótulos já limpa).

    Opções de cada campo = valores com registro dado o que está selecionado em TODOS os outros
    campos (cascata mútua, independente da ordem dos campos). Rótulo selecionado que não está
    mais entre as opções do seu campo é descartado — mesmo efeito do multiselect antigo."""

    todas = _selecoes_em_codigos(dataframe, campos, filtros)
    opcoes: dict[str, list[str]] = {}
    mapeamentos: dict[str, dict[str, object]] = {}
    for nome, _rotulo, coluna_cod, coluna_desc in campos:
        outras = {n: v for n, v in todas.items() if n != nome}
        disponivel = apply_filters(dataframe, campos, outras)
        mapeamento = option_mapping(disponivel, coluna_cod, coluna_desc)
        mapeamentos[nome] = mapeamento
        opcoes[nome] = list(mapeamento)

    limpos: dict[str, list[str]] = {}
    codigos: dict[str, list[object]] = {}
    for nome, _rotulo, _cod, _desc in campos:
        validos = [r for r in (filtros.get(nome) or []) if r in mapeamentos[nome]]
        if validos:
            limpos[nome] = validos
            codigos[nome] = [mapeamentos[nome][r] for r in validos]
    return opcoes, codigos, limpos


# --------------------------------------------------------------------------------- cortes
def com_percentual(visivel: pd.DataFrame) -> pd.DataFrame:
    """`percentual_saldo` = saldo / empenhado × 100; empenhado nulo ou zero -> nulo (não inf)."""

    empenhado_valido = visivel["empenhada"].where(visivel["empenhada"].fillna(0) != 0)
    return visivel.assign(percentual_saldo=(visivel["saldo"] / empenhado_valido) * 100)


def cortes_no_padrao(estado: dict[str, Any]) -> bool:
    """Verdadeiro quando os cortes estão exatamente como no estado inicial (R$ ligado em 10 mil,
    % desligado em 20, idade desligada em 3 meses, combinação OU). A tela usa isso só para exibir
    uma dica sobre o corte por idade; não altera lista, destaque nem relatório."""

    padrao = estado_inicial(0)
    return all(estado.get(k, padrao[k]) == padrao[k] for k in (
        "usar_rs", "corte_rs", "usar_pct", "corte_pct", "usar_idade", "corte_idade", "modo",
    ))


def idade_por_ne(filtrado: pd.DataFrame, ano_extracao: int, mes_extracao: int) -> pd.Series:
    """Idade do saldo, em meses, por `ne_ccor` (regra definida pelo usuário em 17/10/2026).

    Idade = mês da extração − primeiro mês (`ano_mes`) em que a NE tem valor empenhado não nulo e
    diferente de zero, entre as linhas já filtradas. A base só tem o MÊS do movimento (sem dia),
    então a idade é em meses inteiros: empenho no próprio mês da extração tem idade 0.

    Só para NE do exercício da extração (decisão do usuário: a base de exercícios anteriores
    registra a execução só até dezembro daquele ano — o que foi liquidado depois como resto a
    pagar não aparece, e contar a idade até hoje marcaria como atrasado o que pode já ter sido
    pago). NE de outro exercício, ou sem mês de empenho identificável, fica com idade nula."""

    if filtrado.empty or "ano_mes" not in filtrado.columns:
        return pd.Series(dtype="Int64", name=COLUNA_IDADE)
    linhas = filtrado[
        (filtrado["ano"].astype("Int64") == ano_extracao)
        & filtrado["empenhada"].notna()
        & (filtrado["empenhada"] != 0)
    ]
    if linhas.empty:
        return pd.Series(dtype="Int64", name=COLUNA_IDADE)
    primeiro = pd.to_numeric(linhas["ano_mes"].astype(str), errors="coerce").groupby(linhas["ne_ccor"]).min().dropna()
    ano, mes = primeiro // 100, primeiro % 100
    idade = (ano_extracao * 12 + mes_extracao) - (ano * 12 + mes)
    return idade.astype("Int64").rename(COLUNA_IDADE)


def com_idade(visivel: pd.DataFrame, filtrado: pd.DataFrame, ano_extracao: int, mes_extracao: int) -> pd.DataFrame:
    idades = idade_por_ne(filtrado, ano_extracao, mes_extracao)
    return visivel.assign(**{COLUNA_IDADE: visivel["ne_ccor"].map(idades).astype("Int64")})


def calcular_destaque(visivel: pd.DataFrame, estado: dict[str, Any]) -> tuple[pd.Series, str | None]:
    """(máscara de quem passa do corte, descrição do corte) — `None` quando nenhum corte está
    ligado. Nulo nunca passa (não dá para afirmar que passa sem saber o valor)."""

    passa_rs = (visivel["saldo"] >= estado["corte_rs"]).fillna(False)
    passa_pct = (visivel["percentual_saldo"] >= estado["corte_pct"]).fillna(False)
    partes: list[pd.Series] = []
    descricoes: list[str] = []
    if estado["usar_rs"]:
        partes.append(passa_rs)
        descricoes.append(f"saldo ≥ {formatar_brl(estado['corte_rs'])}")
    if estado["usar_pct"]:
        partes.append(passa_pct)
        descricoes.append(f"saldo ≥ {estado['corte_pct']:.0f}% do valor empenhado")
    if estado.get("usar_idade"):
        # idade só conta com saldo a liquidar (> 0); idade nula nunca passa
        idade = visivel[COLUNA_IDADE] if COLUNA_IDADE in visivel.columns else pd.Series(pd.NA, index=visivel.index, dtype="Int64")
        passa_idade = ((idade >= int(estado["corte_idade"])) & (visivel["saldo"] > 0)).fillna(False).astype(bool)
        partes.append(passa_idade)
        n = int(estado["corte_idade"])
        descricoes.append(f"empenho há {n} {'mês' if n == 1 else 'meses'} ou mais com saldo")

    if not partes:
        return pd.Series(False, index=visivel.index), None
    mascara = partes[0]
    usar_e = len(partes) >= 2 and estado.get("modo") == "E"
    for parte in partes[1:]:
        mascara = (mascara & parte) if usar_e else (mascara | parte)
    return mascara.astype(bool), (" e " if usar_e else " ou ").join(descricoes)


# ------------------------------------------------------------------------------- detalhe
def montar_detalhe(filtrado: pd.DataFrame, linha: pd.Series) -> dict[str, Any]:
    """Mesmo conjunto de informações do antigo pop-up de detalhe, mais as linhas de origem
    (rastreabilidade até a planilha importada)."""

    def par(rotulo: str, cod: str, desc: str | None = None) -> list[str]:
        valor = _texto(linha.get(cod))
        if desc:
            valor = f"{valor} — {_texto(linha.get(desc))}"
        return [rotulo, valor]

    origem = detalhar_nota_empenho(filtrado, linha["ne_ccor"])
    linhas_origem = [
        {
            "linha": _texto(o.get("linha_origem")),
            "tipo": _texto(o.get("tipo_linha")),
            "ano": "—" if pd.isna(o.get("ano")) else str(int(o.get("ano"))),
            "empenhada": formatar_brl_centavos(o.get("empenhada")),
            "liquidada": formatar_brl_centavos(o.get("liquidada")),
            "paga": formatar_brl_centavos(o.get("paga")),
        }
        for _, o in origem.iterrows()
    ]
    return {
        "ne": ne_curta(str(linha["ne_ccor"])),
        "ne_ccor": str(linha["ne_ccor"]),
        "favorecido": _texto(linha.get("ne_favorecido")),
        "descricao": None if pd.isna(linha.get("ne_descricao")) else str(linha.get("ne_descricao")),
        "metricas": [
            ["Empenhado", formatar_brl(linha["empenhada"])],
            ["Liquidado", formatar_brl(linha["liquidada"])],
            ["Saldo", formatar_brl(linha["saldo"])],
            ["% do empenhado", formatar_pct(linha["percentual_saldo"])],
            ["Idade do saldo", formatar_idade(linha.get(COLUNA_IDADE))],
        ],
        "saldo_negativo": bool(_numero(linha["saldo"]) is not None and linha["saldo"] < 0),
        "secoes": [
            ["Classificação da despesa", [
                par("Categoria Econômica", "categoria_economica_cod", "categoria_economica_desc"),
                par("Grupo de Despesa", "gnd_cod", "gnd_desc"),
                par("Natureza de Despesa", "natureza_despesa_cod", "natureza_despesa_desc"),
                par("Natureza Detalhada", "natureza_detalhada_label"),
                par("Subitem", "subitem_resumo"),
                par("Elemento de Despesa", "elemento_cod", "elemento_desc"),
            ]],
            ["Programação orçamentária", [
                par("Nº do Processo", "processo_ne"),
                par("Ação de Governo", "acao_cod", "acao_desc"),
                par("Fonte de Recursos", "fonte_cod", "fonte_desc"),
                par("Resultado Primário Lei", "resultado_primario_cod", "resultado_primario_desc"),
                par("Iduso", "iduso_cod", "iduso_desc"),
                par("PI", "pi_cod", "pi_desc"),
                par("PTRES", "ptres"),
            ]],
            ["Unidades", [
                par("Unidade Orçamentária", "unidade_orcamentaria_cod", "unidade_orcamentaria_desc"),
                par("UG Executora", "ug_executora_cod", "ug_executora_desc"),
                par("UG Responsável", "ug_responsavel_cod", "ug_responsavel_desc"),
                par("UGR - Gestão", "ugr_cod", "ugr_desc"),
            ]],
        ],
        "origem": linhas_origem,
    }


# --------------------------------------------------------------------------------- tela
def montar_tela(
    dataframe: pd.DataFrame,
    estado: dict[str, Any],
    *,
    campos_rapidos: Sequence[CampoFiltro],
    campos_avancados: Sequence[CampoFiltro],
    ano_extracao: int,
    mes_extracao: int,
) -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame | None]:
    """Calcula tudo que a tela mostra.

    Devolve (dados para o componente, estado ajustado, lista do relatório ou None). O estado
    ajustado só difere do recebido por limpeza (filtro que deixou de existir, página fora do
    intervalo, detalhe de NE que saiu da lista) — a página grava de volta."""

    campos = tuple(campos_rapidos) + tuple(campos_avancados)
    estado = {**estado_inicial(ano_extracao), **estado, "filtros": dict(estado.get("filtros", {}))}  # estado salvo antes de um campo novo
    busca = estado.get("busca", "")

    def campo_dados(campo: CampoFiltro, opcoes: dict[str, list[str]]) -> dict[str, Any]:
        nome, rotulo, _cod, _desc = campo
        return {"nome": nome, "rotulo": rotulo, "opcoes": opcoes.get(nome, []), "selecionados": estado["filtros"].get(nome, [])}

    dados: dict[str, Any] = {
        "busca": busca,
        "cortes": {k: estado[k] for k in ("usar_rs", "corte_rs", "usar_pct", "corte_pct", "usar_idade", "corte_idade", "modo")},
        "cortes_padrao": cortes_no_padrao(estado),
        "mes_referencia": f"{_MESES[mes_extracao - 1]}/{ano_extracao}",
        "visao": estado["visao"],
        "visoes": [VISAO_DESTAQUE, VISAO_TODOS],
        "grupo": estado["grupo"],
        "grupos": list(OPCOES_AGRUPAMENTO),
        "ordem": estado["ordem"],
        "sentido": estado["sentido"],
        "colunas": list(COLUNAS_ORDENAVEIS),
        "aviso": None,
        "avisos_lista": [],
        "resumo": None,
        "lista": None,
        "detalhe": None,
    }

    buscado = restringir_a_busca(dataframe, busca)
    if busca and buscado.empty:
        opcoes, _codigos, limpos = resolver_filtros(dataframe.iloc[0:0], campos, estado["filtros"])
        dados["filtros_rapidos"] = [campo_dados(c, opcoes) for c in campos_rapidos]
        dados["filtros_avancados"] = [campo_dados(c, opcoes) for c in campos_avancados]
        dados["aviso"] = AVISO_BUSCA_VAZIA
        estado["ne_aberta"] = None
        return dados, estado, None

    opcoes, codigos, limpos = resolver_filtros(buscado, campos, estado["filtros"])
    estado["filtros"] = limpos
    dados["filtros_rapidos"] = [campo_dados(c, opcoes) for c in campos_rapidos]
    dados["filtros_avancados"] = [campo_dados(c, opcoes) for c in campos_avancados]
    dados["n_filtros_ativos"] = sum(1 for c in campos_avancados if limpos.get(c[0]))

    filtrado = apply_filters(buscado, campos, codigos)
    if filtrado.empty:
        dados["aviso"] = AVISO_FILTROS_VAZIOS
        estado["ne_aberta"] = None
        return dados, estado, None

    visivel = aplicar_busca_por_ne(saldo_por_ne(agregar_por_ne(filtrado)), busca)
    if visivel.empty:
        dados["aviso"] = AVISO_BUSCA_VAZIA
        estado["ne_aberta"] = None
        return dados, estado, None
    visivel = com_idade(com_percentual(visivel), filtrado, ano_extracao, mes_extracao)

    anos = visivel["ano"].dropna().astype(int).unique()
    if ano_extracao in anos:
        dados["aviso_exercicio"] = (
            f"O recorte inclui {ano_extracao}, exercício em andamento na data da extração — saldo desse "
            "exercício ainda pode estar em movimento normal, não é necessariamente atraso."
        )

    tem_empenhada = bool(visivel["empenhada"].notna().any())
    tem_liquidada = bool(visivel["liquidada"].notna().any())
    empenhado_total = visivel["empenhada"].sum(min_count=1) if tem_empenhada else None
    liquidado_total = visivel["liquidada"].sum(min_count=1) if tem_liquidada else None
    saldo_total = visivel["saldo"].sum()
    pct_liquidado = None
    if (
        empenhado_total is not None and not pd.isna(empenhado_total) and empenhado_total > 0
        and 0 <= (liquidado_total or 0) <= empenhado_total
    ):
        pct_liquidado = float((liquidado_total or 0) / empenhado_total * 100)
    dados["resumo"] = {
        "empenhos": int(len(visivel)),
        "empenhado": formatar_brl(empenhado_total) if tem_empenhada else "Sem registros",
        "liquidado": formatar_brl(liquidado_total) if tem_liquidada else "Sem registros",
        "saldo": formatar_brl(saldo_total),
        "pct_liquidado": pct_liquidado,
    }

    mascara, descricao_corte = calcular_destaque(visivel, estado)
    em_destaque = visivel[mascara]
    abaixo = visivel[~mascara]
    todos = estado["visao"] == VISAO_TODOS
    if descricao_corte is None:
        dados["resultado_corte"] = "Nenhum corte ligado"
        if not todos:
            dados["avisos_lista"].append(AVISO_SEM_CORTE)
    else:
        dados["resultado_corte"] = f"{len(em_destaque)} de {len(visivel)} empenhos com {descricao_corte}."

    coluna_grupo = OPCOES_AGRUPAMENTO.get(estado["grupo"])
    lista = montar_lista_relatorio(
        visivel,
        mascara,
        cortes_ligados=descricao_corte is not None,
        todos=todos,
        ordenar_por=COLUNAS_ORDENAVEIS.get(estado["ordem"], "saldo"),
        ascendente=estado["sentido"] == SENTIDO_ASC,
        agrupar_por=coluna_grupo,
    )
    dados["descricao_corte"] = descricao_corte

    if lista.empty:
        if descricao_corte is not None and not todos:
            dados["avisos_lista"].append(AVISO_NADA_PASSA)
        estado["ne_aberta"] = None
        return dados, estado, None

    total_paginas = max(1, -(-len(lista) // TAMANHO_PAGINA))
    pagina = min(max(1, int(estado.get("pagina", 1))), total_paginas)
    estado["pagina"] = pagina
    inicio = (pagina - 1) * TAMANHO_PAGINA
    trecho = lista.iloc[inicio : inicio + TAMANHO_PAGINA]

    subtotais: dict[str, dict[str, Any]] = {}
    if coluna_grupo:
        for nome_grupo, do_grupo in lista.groupby(COLUNA_GRUPO, sort=False):
            subtotais[str(nome_grupo)] = {"n": int(len(do_grupo)), "saldo": formatar_brl(do_grupo["saldo"].sum(min_count=1))}

    linhas = []
    for _, linha in trecho.iterrows():
        passa = linha[COLUNA_PASSA_CORTE]
        linhas.append({
            "ne": ne_curta(str(linha["ne_ccor"])),
            "ne_ccor": str(linha["ne_ccor"]),
            "favorecido": _texto(linha.get("ne_favorecido")),
            "acao": _texto(linha.get("acao_desc")),
            "uo": _texto(linha.get("unidade_orcamentaria_desc")),
            "empenhado": formatar_brl(linha["empenhada"]),
            "liquidado": formatar_brl(linha["liquidada"]),
            "saldo": formatar_brl(linha["saldo"]),
            "saldo_negativo": bool(_numero(linha["saldo"]) is not None and linha["saldo"] < 0),
            "pct": formatar_pct(linha["percentual_saldo"]),
            "pct_valor": _numero(linha["percentual_saldo"]),
            "idade": formatar_idade(linha.get(COLUNA_IDADE)),
            "corte": None if pd.isna(passa) else bool(passa),
            "grupo": str(linha[COLUNA_GRUPO]) if coluna_grupo else None,
        })

    dados["lista"] = {
        "linhas": linhas,
        "total": int(len(lista)),
        "pagina": pagina,
        "total_paginas": total_paginas,
        "inicio": inicio + 1,
        "fim": inicio + len(trecho),
        "mostra_corte": todos,
        "subtotais": subtotais,
        "abaixo": (
            f"+ {len(abaixo)} empenhos abaixo do corte, somando {formatar_brl(abaixo['saldo'].sum())} de saldo."
            if not todos and descricao_corte is not None and not abaixo.empty else None
        ),
    }

    if estado.get("ne_aberta"):
        alvo = lista[lista["ne_ccor"].astype(str) == estado["ne_aberta"]]
        if alvo.empty:
            estado["ne_aberta"] = None
        else:
            dados["detalhe"] = montar_detalhe(filtrado, alvo.iloc[0])
    return dados, estado, lista
