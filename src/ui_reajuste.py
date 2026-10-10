"""
Seção "Estimativa de reajuste" de Contratos Contínuos (11/10/2026).

Camada de interface (Streamlit). O cálculo está em `src/estimativa_reajuste.py` e os índices oficiais em
`src/indices_economicos.py`; aqui só se monta a tela: resumo por contrato, matriz mensal por competência,
configuração do contrato (índice, percentual e data-base manuais), promoção a aditivo PREVISTO e exportação.

É um CENÁRIO SEPARADO: nada aqui altera os totais, as projeções nem o cadastro, exceto por ação explícita do
usuário (salvar a configuração ou registrar o aditivo previsto). Spec:
`docs/superpowers/specs/2026-10-11-estimativa-reajuste-contratos-design.md`.
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from src.contratos_aditivos import aditivo_para_registro, aditivos_do_registro, validar_aditivos
from src.contratos_continuos_cadastro import atualizar_contrato
from src.estimativa_reajuste import (
    ParametrosReajuste,
    aditivo_previsto_do_ciclo,
    estimar_contrato,
    liquidado_do_contrato,
    nes_em_conflito,
    ultimo_mes_coberto,
)
from src.indices_economicos import INDICES, ErroIndiceEconomico, variacoes_bcb
from src.ui_cadastro import formatar_brl

ROTULO_SITUACAO = {
    "estimado": "Estimado",
    "sem_indice": "Sem percentual (índice indisponível)",
    "sem_data_base": "Sem data-base (informe o início ou a data)",
    "sem_vigencia_fim": "Sem fim de vigência",
    "sem_reajuste_na_vigencia": "Sem reajuste previsto na vigência",
}
ROTULO_ORIGEM_BASE = {"liquidado": "Liquidado", "contratado": "Contratado (teto)", "sem_liquidado": "Sem liquidado apurado"}
ROTULO_ORIGEM_PERCENTUAL = {
    "manual": "Manual", "oficial": "Oficial (12 meses)", "oficial_ultimo": "Oficial (último disponível)",
    "sem_indice": "Sem índice",
}
_NENHUM = "(nenhum)"


def _md(texto: str) -> str:
    return texto.replace("$", r"\$")


@st.cache_data(ttl=6 * 3600, show_spinner="Consultando o índice no Banco Central...")
def _variacoes_oficiais(indice: str, ano_inicial: int, hoje_iso: str) -> dict | str:
    """Variações mensais do índice desde janeiro de `ano_inicial`, ou o texto do erro (a página segue só
    com o percentual manual). `hoje_iso` só participa da chave de cache."""

    try:
        return variacoes_bcb(indice, date(ano_inicial, 1, 1), date.fromisoformat(hoje_iso))
    except ErroIndiceEconomico as erro:
        return str(erro)


def _parametros(linha: pd.Series) -> ParametrosReajuste:
    def valor(campo: str) -> object:
        bruto = linha.get(campo)
        return None if bruto is None or bool(pd.isna(bruto)) else bruto

    indice = valor("reajuste_indice")
    percentual = valor("reajuste_percentual_manual")
    data_base = valor("reajuste_data_base_manual")
    return ParametrosReajuste(
        indice=None if indice is None else str(indice).upper(),
        percentual_manual=None if percentual is None else float(percentual),
        data_base_manual=None if data_base is None else date.fromisoformat(str(data_base)[:10]),
    )


def _inicio_da_vigencia(linha: pd.Series, inicio_por_gov: dict[str, object]) -> date | None:
    gov = linha.get("contratosgov_id")
    if gov is None or bool(pd.isna(gov)):
        return None
    inicio = inicio_por_gov.get(str(gov))
    if inicio is None or bool(pd.isna(inicio)):
        return None
    return inicio.date() if isinstance(inicio, (pd.Timestamp, datetime)) else inicio


def _estimativas(
    dataframe: pd.DataFrame, todos_registros: list[dict], liquidacao_por_mes: pd.DataFrame | None,
    inicio_por_gov: dict[str, object], ano: int, hoje: date,
) -> tuple[list[dict], list[str]]:
    """Uma estimativa por contrato (a primeira linha de cada `contrato_numero` no exercício) e os avisos de
    NE em conflito. O liquidado soma as NEs do contrato em todos os exercícios, menos as NEs em conflito."""

    conflitos = nes_em_conflito(todos_registros)
    nes_por_contrato: dict[str, set[str]] = {}
    for registro in todos_registros:
        ne, contrato = registro.get("ne_curta"), registro.get("contrato_numero")
        if ne and contrato and str(ne).strip() not in conflitos:
            nes_por_contrato.setdefault(str(contrato).strip(), set()).add(str(ne).strip())

    cobertura = ultimo_mes_coberto(liquidacao_por_mes, hoje)
    variacoes_por_indice: dict[str, dict | None] = {}
    avisos = [
        f"NE {ne} está ligada a mais de um contrato ({', '.join(sorted(contratos))}) — o liquidado dela ficou "
        "fora da base até a correção do cadastro."
        for ne, contratos in sorted(conflitos.items())
    ]
    hoje_iso = hoje.isoformat()

    resultados = []
    vistos: set[str] = set()
    for _, linha in dataframe.iterrows():
        numero = str(linha.get("contrato_numero") or "").strip()
        if not numero or numero in vistos:
            continue
        vistos.add(numero)
        parametros = _parametros(linha)
        indice = parametros.indice if parametros.indice in INDICES else None
        if indice and indice not in variacoes_por_indice:
            retorno = _variacoes_oficiais(indice, ano - 3, hoje_iso)
            if isinstance(retorno, str):
                avisos.append(retorno)
                variacoes_por_indice[indice] = None
            else:
                variacoes_por_indice[indice] = retorno
        estimativa = estimar_contrato(
            contrato=numero, despesa_mensal=linha.get("despesa_mensal"), aditivos=list(linha.get("aditivos") or []),
            vigencia_inicio=_inicio_da_vigencia(linha, inicio_por_gov), vigencia_fim=linha.get("vigencia_fim"),
            parametros=parametros, exercicio_inicial=ano, variacoes=variacoes_por_indice.get(indice) if indice else None,
            liquidado=liquidado_do_contrato(nes_por_contrato.get(numero, set()), liquidacao_por_mes),
            ultimo_mes_coberto=cobertura,
        )
        resultados.append({"linha": linha, "estimativa": estimativa, "parametros": parametros})
    return resultados, avisos


def _soma_ou_nulo(serie: pd.Series) -> float | None:
    total = serie.sum(skipna=True, min_count=1)
    return None if pd.isna(total) else float(total)


def _resumo(resultados: list[dict], ano: int, hoje: date) -> pd.DataFrame:
    linhas = []
    for item in resultados:
        linha, estimativa = item["linha"], item["estimativa"]
        matriz = estimativa.matriz
        do_ano = matriz[matriz["ano"] == ano] if not matriz.empty else matriz
        proxima = next((c for c in estimativa.ciclos if c["data_base"] >= hoje), None)
        ciclo = proxima or (estimativa.ciclos[-1] if estimativa.ciclos else None)
        linhas.append({
            "Contrato": linha.get("contrato_numero"),
            "Fornecedor": linha.get("fornecedor"),
            "Situação": ROTULO_SITUACAO.get(estimativa.situacao, estimativa.situacao),
            "Data-base": None if ciclo is None else ciclo["data_base"],
            "Percentual (%)": None if ciclo is None or ciclo["percentual"] is None else round(ciclo["percentual"], 4),
            "Origem do %": None if ciclo is None else ROTULO_ORIGEM_PERCENTUAL.get(ciclo["origem"], ciclo["origem"]),
            # `min_count=1`: só NaN = sem estimativa (nulo), nunca R$ 0,00
            f"Acréscimo {ano}": None if do_ano.empty else _soma_ou_nulo(do_ano["acrescimo"]),
            "Acréscimo na vigência": None if matriz.empty else _soma_ou_nulo(matriz["acrescimo"]),
            "Competências sem estimativa": 0 if matriz.empty else int(matriz["acrescimo"].isna().sum()),
        })
    return pd.DataFrame(linhas)


def _matriz_longa(resultados: list[dict]) -> pd.DataFrame:
    matrizes = [item["estimativa"].matriz for item in resultados if not item["estimativa"].matriz.empty]
    if not matrizes:
        return pd.DataFrame()
    return pd.concat(matrizes, ignore_index=True)


def _excel(resumo: pd.DataFrame, matriz: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as escritor:
        resumo.to_excel(escritor, sheet_name="Resumo", index=False)
        legivel = matriz.copy()
        if not legivel.empty:
            legivel["base_origem"] = legivel["base_origem"].map(ROTULO_ORIGEM_BASE)
            legivel["percentual_origem"] = legivel["percentual_origem"].map(ROTULO_ORIGEM_PERCENTUAL)
        legivel.to_excel(escritor, sheet_name="Por competência", index=False)
    return buffer.getvalue()


@st.dialog("Configurar reajuste")
def _dialogo_configurar(registro: dict, ano: int, chave: str) -> None:
    st.caption(_md(
        "Índice oficial (IPCA, INPC ou IGP-M) sugere o percentual; o percentual manual, se informado, "
        "sobrescreve. A data-base manual substitui a calculada pela vigência."
    ))
    atual_indice = str(registro.get("reajuste_indice") or "").upper()
    opcoes = [_NENHUM, *INDICES]
    indice = st.selectbox(
        "Índice", opcoes, index=opcoes.index(atual_indice) if atual_indice in opcoes else 0, key=f"{chave}_indice"
    )
    atual_percentual = registro.get("reajuste_percentual_manual")
    usar_percentual = st.checkbox("Informar percentual manual", value=atual_percentual is not None, key=f"{chave}_usar_p")
    percentual = st.number_input(
        "Percentual manual (%)", value=float(atual_percentual) if atual_percentual is not None else 0.0,
        step=0.01, format="%.4f", disabled=not usar_percentual, key=f"{chave}_percentual",
    )
    atual_data = registro.get("reajuste_data_base_manual")
    usar_data = st.checkbox("Informar data-base manual", value=atual_data is not None, key=f"{chave}_usar_d")
    data_base = st.date_input(
        "Próxima data-base", value=date.fromisoformat(str(atual_data)[:10]) if atual_data else date.today(),
        format="DD/MM/YYYY", disabled=not usar_data, key=f"{chave}_data",
    )
    if st.button("Salvar configuração", type="primary", key=f"{chave}_salvar"):
        novo = dict(registro)
        novo["reajuste_indice"] = None if indice == _NENHUM else indice
        novo["reajuste_percentual_manual"] = float(percentual) if usar_percentual else None
        novo["reajuste_data_base_manual"] = data_base.isoformat() if usar_data else None
        atualizar_contrato(ano, novo)
        st.rerun()


def render_estimativa_reajuste(
    dataframe: pd.DataFrame, registros: list[dict], todos_registros: list[dict], ano: int,
    liquidacao_por_mes: pd.DataFrame | None, inicio_por_gov: dict[str, object], source_key: str,
    hoje: date | None = None,
) -> None:
    """Seção completa. `registros` são os do exercício `ano` (o que se grava); `todos_registros` são os de todos
    os exercícios (liquidado e conflito de NE); `inicio_por_gov` mapeia `contratosgov_id` → início da vigência;
    `hoje` é a data de referência (padrão: hoje) — define o último mês de liquidação considerado apurado."""

    hoje = hoje or date.today()

    with st.expander("Estimativa de reajuste (cenário por competência)", expanded=False):
        st.caption(_md(
            "Cenário separado: não altera Necessidade de Empenho, Projeção nem aditivos. O reajuste incide sobre o "
            "valor LIQUIDADO por competência; onde ainda não há liquidado apurado (meses futuros) a base é o valor "
            "contratado, marcado como teto. Competência já apurada sem lançamento fica vazia, nunca zero."
        ))
        resultados, avisos = _estimativas(dataframe, todos_registros, liquidacao_por_mes, inicio_por_gov, ano, hoje)
        for aviso in avisos:
            st.warning(_md(aviso))
        if not resultados:
            st.info("Nenhum contrato no exercício para estimar.")
            return

        resumo = _resumo(resultados, ano, hoje)
        matriz = _matriz_longa(resultados)
        coluna_ano = f"Acréscimo {ano}"
        a, b, c = st.columns(3)
        a.metric(f"Acréscimo estimado em {ano}", _md(formatar_brl(resumo[coluna_ano].sum(skipna=True))))
        b.metric("Acréscimo na vigência", _md(formatar_brl(resumo["Acréscimo na vigência"].sum(skipna=True))))
        c.metric("Contratos sem estimativa", str(int((resumo["Situação"] != ROTULO_SITUACAO["estimado"]).sum())))

        st.dataframe(
            resumo, hide_index=True, use_container_width=True,
            column_config={
                "Data-base": st.column_config.DateColumn(format="DD/MM/YYYY"),
                coluna_ano: st.column_config.NumberColumn(format="R$ %.2f"),
                "Acréscimo na vigência": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )

        if not matriz.empty:
            anos = sorted(matriz["ano"].unique())
            escolhido = st.selectbox(
                "Exercício da matriz mensal", anos, index=anos.index(ano) if ano in anos else 0, key=f"rj_{source_key}_ano"
            )
            do_ano = matriz[matriz["ano"] == escolhido]
            pivot = do_ano.pivot_table(index="contrato", columns="mes", values="acrescimo", aggfunc="sum", dropna=False)
            pivot.columns = [f"{mes:02d}/{escolhido}" for mes in pivot.columns]
            st.caption(f"Acréscimo estimado por competência em {escolhido} (vazio = sem estimativa).")
            st.dataframe(
                pivot, use_container_width=True,
                column_config={coluna: st.column_config.NumberColumn(format="R$ %.2f") for coluna in pivot.columns},
            )

        numeros = [item["linha"]["contrato_numero"] for item in resultados]
        escolhido_contrato = st.selectbox("Detalhar contrato", numeros, key=f"rj_{source_key}_contrato")
        item = next(i for i in resultados if i["linha"]["contrato_numero"] == escolhido_contrato)
        estimativa = item["estimativa"]
        st.caption(_md(f"Situação: {ROTULO_SITUACAO.get(estimativa.situacao, estimativa.situacao)}."))
        if not estimativa.matriz.empty:
            detalhe = estimativa.matriz[[
                "competencia", "base_valor", "base_origem", "ciclo", "percentual", "percentual_origem", "acrescimo",
                "prorrogacao_prevista",
            ]].rename(columns={
                "competencia": "Competência", "base_valor": "Base", "base_origem": "Origem da base", "ciclo": "Ciclo",
                "percentual": "Percentual (%)", "percentual_origem": "Origem do %", "acrescimo": "Acréscimo",
                "prorrogacao_prevista": "Prorrogação prevista",
            })
            detalhe["Origem da base"] = detalhe["Origem da base"].map(ROTULO_ORIGEM_BASE)
            detalhe["Origem do %"] = detalhe["Origem do %"].map(ROTULO_ORIGEM_PERCENTUAL)
            st.dataframe(
                detalhe, hide_index=True, use_container_width=True,
                column_config={
                    "Base": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Acréscimo": st.column_config.NumberColumn(format="R$ %.2f"),
                },
            )

        registro = next((r for r in registros if str(r.get("id")) == str(item["linha"].get("id"))), None)
        acoes = st.columns(2)
        if registro is not None and acoes[0].button("Configurar reajuste", key=f"rj_{source_key}_config"):
            _dialogo_configurar(registro, ano, f"rj_{source_key}_dlg")
        aditivos = list(item["linha"].get("aditivos") or [])
        proposto = aditivo_previsto_do_ciclo(estimativa, aditivos, item["linha"].get("despesa_mensal"))
        if registro is not None and proposto is not None and acoes[1].button(
            f"Registrar aditivo previsto ({proposto.data_inicio:%d/%m/%Y})", key=f"rj_{source_key}_promover"
        ):
            novos = [*aditivos, proposto]
            erros = validar_aditivos(aditivos_do_registro([aditivo_para_registro(a) for a in novos]))
            if erros:
                st.error(_md(" ".join(erros)))
            else:
                atualizado = dict(registro)
                atualizado["aditivos"] = [aditivo_para_registro(a) for a in novos]
                atualizar_contrato(ano, atualizado)
                st.rerun()

        st.download_button(
            "Baixar estimativa (Excel)", _excel(resumo, matriz), file_name=f"estimativa_reajuste_{ano}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"rj_{source_key}_excel",
        )
