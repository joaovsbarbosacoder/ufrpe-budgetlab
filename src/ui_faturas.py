"""
Instrumentos de cobrança (notas fiscais/faturas do Contratos.gov) dentro do cadastro de cada contrato (11/10/2026).

Camada de interface. A tabela vem de `src.contratos_cadastro.montar_faturas`; aqui só se resume e se mostra: totais,
alertas (erro no Siafi, glosa, nota cancelada) e a lista por competência. Somente leitura. `resumo_faturas` e
`tabela_faturas` são puras (testáveis sem Streamlit).

Valores do CONTRATO INTEIRO, como vêm da API. Em Contratos Contínuos (parcela da ação 20RK) a lista é filtrada,
por padrão, pelas NEs do cadastro — o usuário pode ver todas.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from src.ui_cadastro import formatar_brl, grade_indicadores


def _soma(serie: pd.Series) -> Decimal | None:
    valores = [v for v in serie if v is not None and not (isinstance(v, float) and pd.isna(v))]
    return sum(valores, Decimal("0")) if valores else None


def _tem_erro(situacao: object) -> bool:
    return isinstance(situacao, str) and "erro" in situacao.lower()


def resumo_faturas(faturas: pd.DataFrame) -> dict:
    """Quantidade, valor bruto, glosas, valor líquido (nulos quando não há valor — nunca zero inventado), notas com
    erro no Siafi e canceladas."""

    return {
        "quantidade": int(len(faturas)),
        "valor": _soma(faturas["valor"]),
        "glosa": _soma(faturas["glosa"]),
        "valor_liquido": _soma(faturas["valor_liquido"]),
        "erros_siafi": int(faturas["situacao"].apply(_tem_erro).sum()),
        "canceladas": int(faturas["cancelada"].apply(lambda v: v is True).sum()),
    }


def _competencias(referencias: tuple) -> str:
    return ", ".join(f"{mes:02d}/{ano}" for ano, mes, _ in referencias) or "—"


def _maior_competencia(referencias: tuple) -> tuple[int, int]:
    return max(((ano, mes) for ano, mes, _ in referencias), default=(0, 0))


def tabela_faturas(faturas: pd.DataFrame) -> pd.DataFrame:
    """Tabela para exibição, da competência mais recente para a mais antiga."""

    if faturas.empty:
        return pd.DataFrame()
    ordem = faturas.assign(
        _comp=faturas["referencias"].apply(_maior_competencia),
        _emissao=faturas["emissao"].apply(lambda d: d.isoformat() if d else ""),
    ).sort_values(["_comp", "_emissao"], ascending=False)

    def numero(valor: object) -> float | None:
        return None if valor is None or (isinstance(valor, float) and pd.isna(valor)) else float(valor)

    def sim_nao(valor: object) -> str:
        return {True: "Sim", False: "Não"}.get(valor, "—")

    return pd.DataFrame({
        "Competência": ordem["referencias"].apply(_competencias),
        "Nº": ordem["numero"],
        "Tipo": ordem["tipo_instrumento"],
        "Emissão": ordem["emissao"],
        "Vencimento": ordem["vencimento"],
        "Valor": ordem["valor"].apply(numero),
        "Glosa": ordem["glosa"].apply(numero),
        "Líquido": ordem["valor_liquido"].apply(numero),
        "Liquidação": ordem["data_liquidacao"],
        "NE(s)": ordem["nes"].apply(lambda nes: ", ".join(nes) or "—"),
        "Situação": ordem["situacao"],
        "Cancelada": ordem["cancelada"].apply(sim_nao),
        "Repactuação": ordem["repactuacao"].apply(sim_nao),
    })


def render_faturas_do_contrato(
    faturas: pd.DataFrame | None, consultado: bool, chave: str, nes_do_cadastro: set[str] | None = None,
) -> None:
    """Seção dentro da janela do contrato. `consultado=False`: a fotografia é anterior ao endpoint (não confundir com
    "sem notas"). `nes_do_cadastro` (Contínuos): filtra pelas NEs da parcela, com opção de ver todas."""

    if not consultado or faturas is None:
        st.caption(
            "Instrumentos de cobrança ainda não consultados para este contrato — faça uma atualização na página "
            "Contratos (aba Atualizar; a completa traz todos os contratos)."
        )
        return
    if faturas.empty:
        st.caption("Nenhum instrumento de cobrança no Contratos.gov para este contrato.")
        return

    visiveis = faturas
    if nes_do_cadastro:
        todas = st.checkbox(
            "Mostrar notas de todas as NEs do contrato (o gov traz o contrato inteiro, de todas as ações)",
            key=f"{chave}_faturas_todas",
        )
        if not todas:
            visiveis = faturas[faturas["nes"].apply(lambda nes: bool(set(nes) & nes_do_cadastro))]
            st.caption(
                f"{len(visiveis)} de {len(faturas)} nota(s) — só as pagas pelas NEs deste cadastro "
                f"({', '.join(sorted(nes_do_cadastro))})."
            )
    if visiveis.empty:
        st.caption("Nenhuma nota paga pelas NEs deste cadastro.")
        return

    total = resumo_faturas(visiveis)
    st.markdown(grade_indicadores([
        ("Notas", str(total["quantidade"])),
        ("Valor bruto", formatar_brl(total["valor"]) if total["valor"] is not None else "—"),
        ("Glosas", formatar_brl(total["glosa"]) if total["glosa"] is not None else "—"),
        ("Valor líquido", formatar_brl(total["valor_liquido"]) if total["valor_liquido"] is not None else "—"),
        ("Com erro no Siafi", str(total["erros_siafi"])),
        ("Canceladas", str(total["canceladas"])),
    ]), unsafe_allow_html=True)
    if total["erros_siafi"]:
        st.warning(f"{total['erros_siafi']} nota(s) com erro no Siafi — confira a apropriação.")
    st.dataframe(
        tabela_faturas(visiveis), hide_index=True, width="stretch",
        column_config={
            "Emissão": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Vencimento": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Liquidação": st.column_config.DateColumn(format="DD/MM/YYYY"),
            **{c: st.column_config.NumberColumn(format="R$ %.2f") for c in ("Valor", "Glosa", "Líquido")},
        },
    )
