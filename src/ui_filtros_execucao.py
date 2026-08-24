"""Filtro reutilizável de dimensões da Execução Anual — busca + filtros rápidos + avançados,
aplicados linha a linha na base bruta (antes de agregar por NE).

Extraído de `app_pages/consulta_empenhos.py` (a implementação original, específica daquela
página) para ser reutilizado por qualquer outra página que precise do mesmo mecanismo de
filtro sobre `src/execucao_anual.py::ler_execucao_anual` — ex.
`app_pages/empenhos_execucao_retardada.py`. Parametrizado pela lista de campos e por um
prefixo de namespace de `st.session_state`, para duas páginas usarem o componente ao mesmo
tempo sem colidir chaves.

Camada: componente de interface (importa Streamlit) genérico o bastante para não conhecer o
CSS/layout de nenhuma página específica — cada página injeta seu próprio CSS e monta a barra
de filtros com as peças daqui.

Um campo de filtro é uma tupla `(nome, rótulo, coluna_código, coluna_descrição | None)` —
mesmo formato que `FILTER_FIELDS_RAPIDOS`/`FILTER_FIELDS_AVANCADOS` já tinham em
`consulta_empenhos.py`. `nome` vira parte da chave de `st.session_state`
(`f"{prefixo}_{nome}_{source_key}"`); `coluna_código`/`coluna_descrição` apontam para colunas
do DataFrame filtrado.

`CAMPOS_RAPIDOS_EXECUCAO`/`CAMPOS_AVANCADOS_EXECUCAO` são as 16 dimensões que Consulta de
Empenhos expunha originalmente — ficam aqui (não redeclaradas em cada página) para que uma
nova página com "o mesmo filtro completo" (ex. `empenhos_execucao_retardada.py`) importe o
MESMO conjunto, em vez de definir uma lista parecida-mas-diferente por engano.

FILTRO COMBINADO (pedido explícito, decidido para as duas páginas que usam este módulo — ver
histórico da conversa): cada campo é um `st.multiselect`, não mais um dropdown de valor único
com "Todos". Nenhum valor selecionado num campo equivale a "Todos" (sem filtro nesse campo,
mesmo efeito de antes); um ou mais valores selecionados filtra por `.isin(...)`, não por
igualdade. Essa mudança reverte a decisão anterior de Consulta de Empenhos de usar seleção
única "de propósito" — decisão nova, pedida explicitamente para as duas páginas.

Contrato público:
    CampoFiltro = tuple[str, str, str, str | None]
    CAMPOS_RAPIDOS_EXECUCAO: tuple[CampoFiltro, ...]
    CAMPOS_AVANCADOS_EXECUCAO: tuple[CampoFiltro, ...]
    CAMPOS_EXECUCAO: tuple[CampoFiltro, ...]  # rápidos + avançados
    option_mapping(dataframe, code_column, description_column) -> dict[str, object]
    selected_values(label, mapping, key) -> list[object]
    apply_filters(dataframe, campos_todos, selections) -> pd.DataFrame
    render_filtros_rapidos(dataframe, campos_rapidos, campos_todos, prefixo, source_key) -> dict[str, list[object]]
    render_filtros_avancados(dataframe, campos_avancados, campos_todos, prefixo, source_key, selections) -> None
    limpar_filtros(campos_todos, prefixo, source_key) -> None
"""

from __future__ import annotations

from typing import Sequence

import pandas as pd
import streamlit as st

#: (nome, rótulo, coluna_código, coluna_descrição | None)
CampoFiltro = tuple[str, str, str, str | None]

#: 4 filtros sempre visíveis — nome do filtro -> (rótulo, coluna código, coluna descrição | None).
CAMPOS_RAPIDOS_EXECUCAO: tuple[CampoFiltro, ...] = (
    ("ano", "Exercício", "ano", None),
    ("acao", "Ação de Governo", "acao_cod", "acao_desc"),
    ("ugr", "UGR - Gestão", "ugr_cod", "ugr_desc"),
    ("gnd", "Grupo de Despesa", "gnd_cod", "gnd_desc"),
)

#: 12 filtros recolhíveis — mesmo formato acima.
CAMPOS_AVANCADOS_EXECUCAO: tuple[CampoFiltro, ...] = (
    ("iduso", "Iduso", "iduso_cod", "iduso_desc"),
    ("resultado_primario", "Resultado Primário Lei", "resultado_primario_cod", "resultado_primario_desc"),
    ("categoria_economica", "Categoria Econômica", "categoria_economica_cod", "categoria_economica_desc"),
    ("elemento", "Elemento de Despesa", "elemento_cod", "elemento_desc"),
    ("fonte", "Fonte de Recursos", "fonte_cod", "fonte_desc"),
    ("natureza_despesa", "Natureza de Despesa", "natureza_despesa_cod", "natureza_despesa_desc"),
    ("natureza_detalhada", "Natureza de Despesa Detalhada", "natureza_detalhada_cod", "natureza_detalhada_desc"),
    ("subitem", "Subitem", "subitem_cod", "subitem_desc"),
    ("pi", "PI", "pi_cod", "pi_desc"),
    ("ptres", "PTRES", "ptres", None),
    ("ug_executora", "UG Executora", "ug_executora_cod", "ug_executora_desc"),
    ("ug_responsavel", "UG Responsável", "ug_responsavel_cod", "ug_responsavel_desc"),
    ("processo", "Número do Processo", "processo_ne", None),
)

CAMPOS_EXECUCAO: tuple[CampoFiltro, ...] = CAMPOS_RAPIDOS_EXECUCAO + CAMPOS_AVANCADOS_EXECUCAO


def option_mapping(dataframe: pd.DataFrame, code_column: str, description_column: str | None) -> dict[str, object]:
    """"Código — descrição" -> valor bruto da coluna código, para popular um filtro a partir
    dos valores realmente presentes no recorte atual (cascata: combinações sem registro não
    aparecem)."""

    columns = [code_column] + ([description_column] if description_column else [])
    options = dataframe.loc[:, columns].drop_duplicates()
    options = options.sort_values(code_column, na_position="last", kind="stable")

    mapping: dict[str, object] = {}
    for _, row in options.iterrows():
        code = row[code_column]
        if pd.isna(code):
            continue
        label = str(code)
        if description_column:
            description = row.get(description_column, pd.NA)
            if pd.notna(description) and str(description) != label:
                label = f"{label} — {description}"
        mapping[label] = code
    return mapping


def selected_values(label: str, mapping: dict[str, object], key: str) -> list[object]:
    """Multiseleção (filtro combinado, pedido explícito) — zero valores selecionados equivale
    a "Todos" (sem filtro nesse campo); um ou mais aplica `.isin(...)` em `apply_filters`.

    Remove do `st.session_state` persistido qualquer rótulo que não exista mais em `mapping`
    (a cascata de opções muda a cada rerun conforme outros filtros mudam) — sem isso,
    `st.multiselect` levanta erro ao encontrar um valor persistido fora da lista de opções
    atual."""

    options = list(mapping)
    persistido = st.session_state.get(key, [])
    valido = [rotulo for rotulo in persistido if rotulo in options]
    if valido != persistido:
        st.session_state[key] = valido
    rotulos = st.multiselect(
        label, options=options, key=key,
        help="Selecione um ou mais valores. Nenhum selecionado equivale a 'Todos'.",
    )
    return [mapping[rotulo] for rotulo in rotulos]


def apply_filters(dataframe: pd.DataFrame, campos_todos: Sequence[CampoFiltro], selections: dict[str, list[object]]) -> pd.DataFrame:
    """Recorta `dataframe` linha a linha pelas seleções já feitas — antes de agregar por NE,
    já que Natureza Detalhada/Subitem (e outras dimensões) podem variar dentro da mesma NE.

    Cada campo selecionado filtra por `.isin(valores)` (filtro combinado: um OU outro valor
    do mesmo campo) — campos diferentes continuam combinando em E entre si (contrato original
    preservado, só a comparação por campo mudou de `==` para `.isin`)."""

    filtered = dataframe
    for filter_name, _, column, _desc in campos_todos:
        valores = selections.get(filter_name)
        if not valores:
            continue
        filtered = filtered[filtered[column].isin(valores)]
    return filtered


def render_filtros_rapidos(
    dataframe: pd.DataFrame,
    campos_rapidos: Sequence[CampoFiltro],
    campos_todos: Sequence[CampoFiltro],
    prefixo: str,
    source_key: str,
) -> dict[str, list[object]]:
    """Desenha os filtros rápidos (sempre visíveis, um `st.multiselect` por coluna) — cada
    campo recalcula suas opções disponíveis com base nas seleções já feitas nos campos
    anteriores do mesmo bloco (cascata). `campos_todos` (não só `campos_rapidos`) é usado para
    recortar `dataframe` a cada passo, para casar exatamente com o comportamento original: uma
    seleção de um filtro avançado feita numa rodada anterior também restringe as opções aqui."""

    selections: dict[str, list[object]] = {}
    columns = st.columns(len(campos_rapidos))
    for column, (filter_name, label, code_column, description_column) in zip(
        columns, campos_rapidos, strict=True
    ):
        available = apply_filters(dataframe, campos_todos, selections)
        mapping = option_mapping(available, code_column, description_column)
        key = f"{prefixo}_{filter_name}_{source_key}"
        with column:
            valores = selected_values(label, mapping, key)
        if valores:
            selections[filter_name] = valores
    return selections


def render_filtros_avancados(
    dataframe: pd.DataFrame,
    campos_avancados: Sequence[CampoFiltro],
    campos_todos: Sequence[CampoFiltro],
    prefixo: str,
    source_key: str,
    selections: dict[str, list[object]],
) -> None:
    """Desenha os filtros avançados (normalmente dentro de um `st.expander` recolhível,
    decisão de cada página) em 3 colunas — mesma cascata de `render_filtros_rapidos`, sobre as
    seleções já acumuladas (inclusive as dos filtros rápidos)."""

    columns = st.columns(3)
    for index, (filter_name, label, code_column, description_column) in enumerate(campos_avancados):
        available = apply_filters(dataframe, campos_todos, selections)
        mapping = option_mapping(available, code_column, description_column)
        key = f"{prefixo}_{filter_name}_{source_key}"
        with columns[index % 3]:
            valores = selected_values(label, mapping, key)
        if valores:
            selections[filter_name] = valores


def limpar_filtros(campos_todos: Sequence[CampoFiltro], prefixo: str, source_key: str) -> None:
    """Apaga do `st.session_state` as chaves de todos os campos de filtro, mais a busca livre
    — convenção do chamador ter uma chave `f"{prefixo}_busca_{source_key}"` para o
    `st.text_input` de busca, mesmo padrão já usado em `consulta_empenhos.py`."""

    for filter_name, _, _, _ in campos_todos:
        st.session_state.pop(f"{prefixo}_{filter_name}_{source_key}", None)
    st.session_state.pop(f"{prefixo}_busca_{source_key}", None)
