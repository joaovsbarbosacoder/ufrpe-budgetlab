"""
Instrumentos de cobrança (notas fiscais/faturas do Contratos.gov) dentro do cadastro de cada contrato (11/10/2026).

Camada de interface. A tabela vem de `src.contratos_cadastro.montar_faturas`; aqui só se resume e se mostra: totais,
alerta de erro no Siafi, a lista das notas e o DETALHAMENTO de uma nota escolhida (valores, datas, identificação,
empenhos, competências, itens faturados e informações complementares). Somente leitura.

Tudo em HTML próprio (`tabela_html`/`grade_indicadores`), não em `st.dataframe`: dentro de `st.dialog` a grade do
`st.dataframe` (desenhada em <canvas>) depende do tema do navegador e aparecia em branco para o usuário (11/10/2026).
As funções `html_*` e `resumo_faturas` são puras (testáveis sem Streamlit).

Valores do CONTRATO INTEIRO, como vêm da API. Em Contratos Contínuos (parcela da ação 20RK) a lista é filtrada,
por padrão, pelas NEs do cadastro — o usuário pode ver todas.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from html import escape

import pandas as pd
import streamlit as st

from src.ui_cadastro import celula_principal, celula_suave, celula_valor, chip, formatar_brl, grade_indicadores, tabela_html


def _vazio(valor: object) -> bool:
    return valor is None or (isinstance(valor, float) and pd.isna(valor))


def _soma(serie: pd.Series) -> Decimal | None:
    valores = [v for v in serie if not _vazio(v)]
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


def _t(valor: object) -> str:
    """Texto para exibição: nulo (None, NaN — o pandas troca None por NaN em coluna mista) ou vazio vira "—"."""
    return "—" if _vazio(valor) or str(valor).strip() == "" else str(valor)


def _data(valor: object) -> str:
    return valor.strftime("%d/%m/%Y") if isinstance(valor, date) else "—"


def _brl(valor: object) -> str:
    return "—" if _vazio(valor) else formatar_brl(valor)


def _sim_nao(valor: object) -> str:
    return {True: "Sim", False: "Não"}.get(valor, "—")


def _numero(valor: object) -> str:
    """Quantidade no formato brasileiro, sem zeros finais desnecessários ("1,00000" → "1"; "2,50" → "2,5")."""
    if _vazio(valor):
        return "—"
    texto = format(Decimal(valor).normalize(), "f")
    inteiro, _, fracao = texto.partition(".")
    inteiro = f"{int(inteiro):,}".replace(",", ".") if inteiro.lstrip("-").isdigit() else inteiro
    return f"{inteiro},{fracao}" if fracao else inteiro


def _chip_situacao(situacao: object) -> str:
    if _vazio(situacao):
        return chip("—", "neutro")
    texto = str(situacao)
    if _tem_erro(texto):
        return chip(texto, "bad")
    return chip(texto, "ok" if "apropriado" in texto.lower() else "warn")


def ordenar(faturas: pd.DataFrame) -> pd.DataFrame:
    """Da competência mais recente para a mais antiga (empate: emissão mais recente)."""
    if faturas.empty:
        return faturas
    return faturas.assign(
        _comp=faturas["referencias"].apply(_maior_competencia),
        _emissao=faturas["emissao"].apply(lambda d: d.isoformat() if isinstance(d, date) else ""),
    ).sort_values(["_comp", "_emissao"], ascending=False).drop(columns=["_comp", "_emissao"])


def html_lista(faturas: pd.DataFrame) -> str:
    """Lista das notas (já ordenadas), com rolagem."""

    linhas = []
    for _, nota in faturas.iterrows():
        linhas.append([
            celula_principal(_competencias(nota["referencias"]), f"Nº {_t(nota['numero'])} · {_t(nota['tipo_instrumento'])}"),
            celula_suave(_data(nota["emissao"])),
            celula_suave(_data(nota["vencimento"])),
            celula_valor(nota["valor"], vazio="—"),
            celula_valor(nota["glosa"], vazio="—"),
            celula_valor(nota["valor_liquido"], vazio="—"),
            celula_suave(_data(nota["data_liquidacao"])),
            celula_suave(", ".join(nota["nes"]) or "—"),
            _chip_situacao(nota["situacao"]),
        ])
    return tabela_html(
        [("Competência / nota", False), ("Emissão", False), ("Vencimento", False), ("Valor", True), ("Glosa", True),
         ("Líquido", True), ("Liquidação", False), ("NE(s)", False), ("Situação", False)],
        linhas, [1.6, 0.8, 0.8, 1, 0.7, 1, 0.8, 1.1, 1.2], rolagem=True,
    )


def rotulo_nota(nota: pd.Series) -> str:
    return f"Nº {_t(nota['numero'])} · competência {_competencias(nota['referencias'])} · {_brl(nota['valor'])}"


def html_detalhe(nota: pd.Series) -> str:
    """Tudo o que foi cadastrado na nota: valores, datas, identificação, empenhos, competências, itens faturados e
    informações complementares. Textos escapados."""

    valores = grade_indicadores([
        ("Valor", _brl(nota["valor"])), ("Juros", _brl(nota["juros"])), ("Multa", _brl(nota["multa"])),
        ("Glosa", _brl(nota["glosa"])), ("Valor líquido", _brl(nota["valor_liquido"])),
        ("Situação no Siafi", _t(nota["situacao"])),
    ])
    datas = grade_indicadores([
        ("Emissão", _data(nota["emissao"])), ("Protocolo", _data(nota["protocolo"])), ("Ateste", _data(nota["ateste"])),
        ("Prazo", _data(nota["prazo"])), ("Vencimento", _data(nota["vencimento"])),
        ("Liquidação", _data(nota["data_liquidacao"])),
    ])
    identificacao = tabela_html(
        [("Campo", False), ("Informação", False)],
        [[celula_suave(campo), celula_principal(valor)] for campo, valor in (
            ("Tipo de instrumento", _t(nota["tipo_instrumento"])),
            ("Tipo de lista", _t(nota["tipo_lista"])),
            ("Número / série", f"{_t(nota['numero'])} / {_t(nota['serie'])}"),
            ("Documento no SIAFI", _t(nota["documento_siafi"])),
            ("Processo", _t(nota["processo"])),
            ("Chave da NF-e", _t(nota["chave_nfe"])),
            ("Optante pelo Simples", _sim_nao(nota["optante_simples"])),
            ("Repactuação", _sim_nao(nota["repactuacao"])),
            ("Nota cancelada", _sim_nao(nota["cancelada"])),
            ("Justificativa", _t(nota["justificativa"])),
        )],
        [1, 3],
    )
    empenhos = tabela_html(
        [("NE", False), ("Subelemento", False), ("Valor", True)],
        [[celula_principal(_t(ne)), celula_suave(_t(sub)), celula_valor(valor, vazio="—")] for ne, sub, valor in nota["empenhos"]],
        [1.4, 1, 1],
    ) if nota["empenhos"] else '<div class="cad-sub">Sem empenho informado.</div>'
    competencias = tabela_html(
        [("Competência", False), ("Valor", True)],
        [[celula_principal(f"{mes:02d}/{ano}"), celula_valor(valor, vazio="—")] for ano, mes, valor in nota["referencias"]],
        [1, 1],
    ) if nota["referencias"] else '<div class="cad-sub">Sem competência informada.</div>'
    itens = tabela_html(
        [("Item do contrato", False), ("Quantidade", True), ("Valor unitário", True), ("Valor total", True)],
        [[celula_principal(f"Item {_t(item)}"), celula_suave(_numero(qtd)), celula_suave(_brl(unitario)),
          celula_valor(total, vazio="—")] for item, qtd, unitario, total in nota["itens"]],
        [1.2, 0.8, 1, 1],
    ) if nota["itens"] else '<div class="cad-sub">Sem itens faturados informados.</div>'
    complemento = escape(_t(nota["inf_complementar"]))

    def bloco(titulo: str, conteudo: str) -> str:
        return f'<div class="cad-secao-dialogo" style="margin-top:12px">{escape(titulo)}</div>{conteudo}'

    return (
        f"{valores}{bloco('Datas', datas)}{bloco('Identificação', identificacao)}"
        f"{bloco('Empenhos', empenhos)}{bloco('Competências', competencias)}{bloco('Itens faturados', itens)}"
        f"{bloco('Informações complementares', f'<div class=cad-sub style=white-space:pre-wrap>{complemento}</div>')}"
    )


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
        ("Valor bruto", _brl(total["valor"])),
        ("Glosas", _brl(total["glosa"])),
        ("Valor líquido", _brl(total["valor_liquido"])),
        ("Com erro no Siafi", str(total["erros_siafi"])),
        ("Canceladas", str(total["canceladas"])),
    ]), unsafe_allow_html=True)
    if total["erros_siafi"]:
        st.warning(f"{total['erros_siafi']} nota(s) com erro no Siafi — confira a apropriação.")

    # lista e detalhamento ficam OCULTOS por padrão (pedido do usuário, 11/10/2026): a janela de edição do contrato já é
    # longa; os totais e o alerta de erro no Siafi continuam visíveis acima
    ordenadas = ordenar(visiveis).reset_index(drop=True)
    with st.expander(f"Notas e detalhamento ({len(ordenadas)})", expanded=False):
        st.markdown(html_lista(ordenadas), unsafe_allow_html=True)
        rotulos = [rotulo_nota(nota) for _, nota in ordenadas.iterrows()]
        escolhida = st.selectbox(
            "Detalhar nota", range(len(rotulos)), format_func=lambda i: rotulos[i], key=f"{chave}_faturas_detalhe",
        )
        st.markdown(html_detalhe(ordenadas.iloc[escolhida]), unsafe_allow_html=True)
