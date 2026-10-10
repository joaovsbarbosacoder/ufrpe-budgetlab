"""Contratos — cadastro dos contratos da UG 153165 (UFRPE) a partir do Contratos.gov.br.

Camada: interface. Sem regra de negócio própria: lê a fotografia atual e o histórico com
`src/contratosgov_extracao.py`, monta as tabelas com `src/contratos_cadastro.py`, lê e grava os
complementos manuais com `src/contratos_complementos.py` e consulta a API (só quando o usuário pede)
com `src/contratosgov_api.py`. Layout aprovado em 08/10/2026 (spec
`docs/superpowers/specs/2026-10-08-contratosgov-cadastro-design.md` §4.0 e o protótipo
`...-mockup.html`), com os componentes de `src/ui_cadastro.py` das demais páginas de cadastro.

Três abas (`st.tabs`):
  * Cadastro — cartão-resumo (contratos, vigentes, vencem em 90 dias, valor global dos vigentes),
    abas de situação com contagem, busca livre, filtro de categoria, ordenação e o registro em
    linhas; o botão de cada linha abre o detalhe numa janela (`st.dialog`) com o complemento
    manual (widgets comuns — nunca `st.data_editor` dentro de `st.dialog`, quebra conhecida no
    projeto), a linha do tempo dos termos e as NEs com total.
  * Atualizar — "Consultar agora" ("Fazer primeira carga" sem fotografia) com opção de
    atualização completa e progresso; a fotografia nova e o delta ficam em `st.session_state` até
    gravar ou descartar. Remoção (contrato, termo ou NE) exige "Estou ciente da remoção". Falha da
    API mostra a URL e mantém a fotografia anterior.
  * Histórico de atualizações — um manifesto por linha, a atual marcada.

Nada é consultado na rede ao abrir a página. Os diretórios (`contratosgov_extracao.DIRETORIO_*`,
`contratos_complementos.CAMINHO_PADRAO`) e o cliente (`contratosgov_api.ClienteContratosGov`) são
lidos em tempo de execução, para os testes trocarem por `tmp_path`/um cliente falso.

Data de referência da vigência: `date.today()`, salvo quando `st.session_state` traz
`contratos_referencia` (gancho só para testes determinísticos — `tests/test_contratos_page.py`).

Valores: nulo aparece "—", zero "R$ 0,00" (`formatar_brl`). Valor mensal só vem do complemento
manual (a API não traz parcela confiável — nenhuma derivação é presumida), marcado "MANUAL".
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from html import escape

import pandas as pd
import streamlit as st

from src import contratos_complementos, contratosgov_api, contratosgov_extracao
from src.contratos_cadastro import (
    ErroDadoContratosGov,
    montar_contratos,
    montar_empenhos,
    montar_termos,
    resumo,
    valor_brl,
)
from src.design_tokens import (
    ACCENT,
    BORDER,
    BORDER_SOFT,
    NEGATIVE,
    NEGATIVE_SOFT,
    SURFACE,
    TEXT,
    TEXT_FAINT,
    TEXT_MUTED,
)
from src.ui_cadastro import (
    celula_categoria,
    celula_principal,
    celula_suave,
    celula_valor,
    chip,
    contagens_por_aba,
    formatar_brl,
    grade_indicadores,
    ordenar_por,
    tabela_html,
)
from src.ui_cadastro import cartao_resumo
from src.ui_cadastro import css as css_cadastro
from src.ui_theme import render_page_header

CHAVE_REFERENCIA = "contratos_referencia"
CHAVE_ABA = "ctg_aba"
CHAVE_CONSULTA = "ctg_consulta"
CHAVE_AVISO = "ctg_aviso"
QTD_INICIAL_REGISTRO = 15
ABAS = ["Cadastro", "Atualizar", "Histórico de atualizações"]

ROTULO_SITUACAO = {
    "vigente": ("Vigente", "ok"),
    "a_iniciar": ("A iniciar", "info"),
    "encerrado": ("Encerrado", "neutro"),
    "inativo": ("Inativo na API", "neutro"),
    "sem_vigencia": ("Sem vigência", "warn"),
}
ORDENACOES = {
    # Proximidade em módulo (|dias|): fora de Vigentes/A iniciar, o encerrado há mais tempo não vem primeiro.
    "Ordenar: vencimento mais próximo": ("_dias_abs_ordem", True),
    "Maior valor global": ("_valor_global_ordem", False),
    "Nº do contrato": ("_numero_ordem", False),
}
PROPORCOES_REGISTRO = [3.2, 1.2, 1.7, 1.3, 1.3, 0.6, 0.6, 0.55]
CABECALHOS_REGISTRO = [
    ("Contrato / fornecedor", False), ("Categoria", False), ("Vigência", False), ("Valor global", True),
    ("Valor mensal", True), ("Termos", True), ("NEs", True), ("", False),
]


# ----------------------------------------------------------------------------- formatação

def _legenda(texto: str) -> None:
    """Texto da API como legenda, escapado como HTML: `st.caption` o interpretaria como Markdown/LaTeX
    ("R$ 1,00 … R$ 2,00" virava fórmula; `*` e `_` viravam ênfase). Quebras viram espaço."""

    st.markdown(f'<div class="ctg-legenda">{escape(" ".join(texto.split()))}</div>', unsafe_allow_html=True)


def _nulo(valor: object) -> bool:
    return valor is None or bool(pd.isna(valor))


def _data(valor: object) -> str:
    if _nulo(valor):
        return "—"
    if isinstance(valor, str):
        try:
            valor = date.fromisoformat(valor[:10])
        except ValueError:
            return valor
    return valor.strftime("%d/%m/%Y")


def _data_hora(texto: object) -> str:
    if _nulo(texto) or not str(texto).strip():
        return "—"
    try:
        return datetime.fromisoformat(str(texto).replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return str(texto)


def _rotulo_documento(tipo: object) -> str:
    """Rótulo do documento do fornecedor conforme o tipo da API."""

    return {"JURIDICA": "CNPJ", "FISICA": "CPF"}.get(str(tipo), "Identificador")


def _documento(digitos: object) -> str:
    """CNPJ/CPF só com dígitos (texto) -> máscara de exibição; identificador com letras ou de outro
    tamanho fica como veio."""

    if _nulo(digitos):
        return ""
    d = str(digitos)
    if not d.isdigit():
        return d
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return d


def _valor_br_editavel(valor: Decimal | None) -> str:
    """Decimal -> "862.858,76" para o campo de edição; nulo -> vazio."""

    if valor is None:
        return ""
    return f"{valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _tom_dias(dias: int) -> str:
    """Chip de dias para vencer: verde > 90, laranja 31–90, vermelho ≤ 30 (spec §4.0)."""

    if dias > 90:
        return "ok"
    if dias > 30:
        return "warn"
    return "bad"


def _chip_situacao(linha) -> str:
    situacao = linha["situacao_vigencia"]
    if situacao == "vigente" and not _nulo(linha["dias_para_vencer"]):
        dias = int(linha["dias_para_vencer"])
        return chip(f"{dias} dia{'s' if abs(dias) != 1 else ''}", _tom_dias(dias))
    rotulo, tom = ROTULO_SITUACAO.get(situacao, (str(situacao), "neutro"))
    return chip(rotulo, tom)


def _soma(valores) -> Decimal | None:
    """Soma de Decimais ignorando nulos; tudo nulo -> None (nulo ≠ zero)."""

    presentes = [v for v in valores if not _nulo(v)]
    return sum(presentes, Decimal("0")) if presentes else None


def _valor_texto_api(texto: object) -> str:
    """Valor bruto da API ("830.906,44") formatado; formato inesperado aparece como veio."""

    try:
        return formatar_brl(valor_brl(texto, contrato_id="-", endpoint="-", campo="-"))
    except ErroDadoContratosGov:
        return str(texto)


def _css_pagina() -> str:
    return f"""
<style>
.st-key-ctg_resumo .cad-tiles {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
@media (max-width: 900px) {{ .st-key-ctg_resumo .cad-tiles {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
.ctg-manual {{ display: inline-block; margin-left: 6px; font-size: 10px; font-weight: 700; letter-spacing: 0.06em;
    color: {ACCENT}; border: 1px solid {ACCENT}; border-radius: 6px; padding: 0 4px; vertical-align: middle; }}
.ctg-vig {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 14px; color: {TEXT_MUTED}; }}
.ctg-num {{ text-align: right; font-size: 15px; color: {TEXT}; font-variant-numeric: tabular-nums; }}
.ctg-fonte {{ text-align: right; font-size: 13px; color: {TEXT_FAINT}; padding-top: 18px; }}
.ctg-legenda {{ font-size: 13.5px; color: {TEXT_FAINT}; margin: 2px 0 8px; overflow-wrap: anywhere; }}
.ctg-fonte code, .ctg-hash {{ font-size: 12.5px; }}
.ctg-timeline {{ border-left: 2px solid {BORDER}; margin: 6px 0 0 6px; padding-left: 16px; }}
.ctg-ev {{ position: relative; padding: 0 0 14px; }}
.ctg-ev::before {{ content: ""; position: absolute; left: -22px; top: 5px; width: 10px; height: 10px; border-radius: 50%;
    background: {ACCENT}; border: 2px solid {SURFACE}; }}
.ctg-ev.ini::before {{ background: {TEXT_FAINT}; }}
.ctg-ev .l1 {{ display: flex; justify-content: space-between; gap: 12px; color: {TEXT}; font-size: 14.5px; }}
.ctg-ev .l1 span {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
.ctg-ev .l2 {{ font-size: 13px; color: {TEXT_FAINT}; }}
.ctg-alerta {{ background: {NEGATIVE_SOFT}; border: 1px solid rgba(210,10,22,0.30); border-radius: 14px; color: {NEGATIVE};
    padding: 14px 18px; margin: 12px 0 6px; font-size: 14px; }}
.ctg-passos {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 10px 0 14px; }}
.ctg-passo {{ border: 1px solid {BORDER_SOFT}; border-radius: 14px; padding: 12px 14px; background: {SURFACE};
    font-size: 13.5px; color: {TEXT_MUTED}; }}
.ctg-passo b {{ display: block; color: {TEXT}; margin-bottom: 2px; }}
@media (max-width: 760px) {{ .ctg-passos {{ grid-template-columns: 1fr; }} }}
.ctg-antes {{ color: {TEXT_FAINT}; text-decoration: line-through; }}
</style>
"""


# ----------------------------------------------------------------------------- dados

def _referencia() -> date:
    valor = st.session_state.get(CHAVE_REFERENCIA)
    return valor if isinstance(valor, date) else date.today()


def _carregar(referencia: date):
    """(fotografia, manifesto, contratos, termos, empenhos, erro) da fotografia atual — tudo None
    sem fotografia. Erro de leitura ou de dado NÃO derruba a página: mostra a mensagem (nunca "sem
    dados"), não exibe o Cadastro e deixa a aba Atualizar tratar a anterior como ausente
    (`fotografia=None`, carga completa), para o usuário conseguir se recuperar."""

    try:
        fotografia, manifesto = contratosgov_extracao.carregar_atual()
        if fotografia is None:
            return None, None, None, None, None, None
        return (
            fotografia, manifesto, montar_contratos(fotografia, referencia),
            montar_termos(fotografia), montar_empenhos(fotografia), None,
        )
    except (contratosgov_extracao.FotografiaAusente, ValueError) as erro:
        st.error(
            f"Não foi possível ler a fotografia atual do Contratos.gov.br: {erro} "
            "O Cadastro fica oculto até uma nova carga completa: use a aba **Atualizar**."
        )
        return None, None, None, None, None, erro


def _carregar_complementos():
    """(complementos, legível). Arquivo ilegível: erro explícito e edição bloqueada (a gravação
    sobrescreveria o que foi digitado)."""

    try:
        return contratos_complementos.carregar_complementos(), True
    except ValueError as erro:
        st.error(f"{erro} — corrija o arquivo; a edição de complementos fica bloqueada até lá.")
        return {}, False


# ----------------------------------------------------------------------------- detalhe

def _detalhe_contrato(linha, termos, empenhos, complemento, editavel: bool, sha12: str) -> None:
    cid = linha["contrato_id"]
    rotulo, tom = ROTULO_SITUACAO.get(linha["situacao_vigencia"], ("", "neutro"))
    dias = linha["dias_para_vencer"]
    if linha["situacao_vigencia"] == "vigente" and not _nulo(dias):
        situacao_html = chip(f"{rotulo} · {int(dias)} dias", _tom_dias(int(dias)))
    else:
        situacao_html = chip(rotulo, tom)
    st.markdown(
        f'<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">{situacao_html}'
        f'{celula_categoria(linha["categoria"])}</div>',
        unsafe_allow_html=True,
    )
    doc = _documento(linha["fornecedor_documento"])
    partes = [p for p in (
        linha["fornecedor_nome"] if not _nulo(linha["fornecedor_nome"]) else None,
        f"{_rotulo_documento(linha['fornecedor_tipo'])} {doc}" if doc else None,
        f"Processo {linha['processo']}" if not _nulo(linha["processo"]) else None,
    ) if p]
    _legenda(" · ".join(partes))
    st.markdown(
        grade_indicadores([
            ("Vigência atual", f"{_data(linha['vigencia_inicio'])} – {_data(linha['vigencia_fim'])}"),
            ("Valor inicial", formatar_brl(linha["valor_inicial"])),
            ("Valor global atual", formatar_brl(linha["valor_global"])),
            ("Modalidade", "—" if _nulo(linha["modalidade"]) else str(linha["modalidade"])),
            ("Assinatura", _data(linha["data_assinatura"])),
            ("Situação na API (como veio)", "—" if _nulo(linha["situacao_api"]) else str(linha["situacao_api"])),
        ]),
        unsafe_allow_html=True,
    )
    if not _nulo(linha["objeto"]):
        _legenda(f"Objeto: {linha['objeto']}")

    st.markdown(
        '<div class="cad-secao-dialogo">Complemento manual · não vem da API · nunca é alterado pela atualização</div>',
        unsafe_allow_html=True,
    )
    c_valor, c_obs = st.columns([1, 2])
    valor_digitado = c_valor.text_input(
        "Valor mensal (R$)", value=_valor_br_editavel(complemento.valor_mensal if complemento else None),
        key=f"ctg_compl_valor_{cid}", placeholder="ex.: 862.858,76", disabled=not editavel,
    )
    obs_digitada = c_obs.text_area(
        "Observações", value=complemento.observacoes if complemento else "",
        key=f"ctg_compl_obs_{cid}", height=90, disabled=not editavel,
    )
    c_info, c_salvar = st.columns([3, 1], vertical_alignment="center")
    c_info.caption(f"Alterado em {_data_hora(complemento.alterado_em)}" if complemento else "Sem complemento gravado.")
    if c_salvar.button("Salvar complemento", key=f"ctg_compl_salvar_{cid}", type="primary", disabled=not editavel):
        try:
            contratos_complementos.salvar_complemento(cid, valor_digitado, obs_digitada)
        except ValueError as erro:
            st.error(str(erro))
        else:
            st.session_state[CHAVE_AVISO] = f"Complemento do contrato {linha['numero']} gravado."
            st.rerun()

    st.markdown(f'<div class="cad-secao-dialogo">Termos · {len(termos)} · do /historico</div>', unsafe_allow_html=True)
    if termos.empty:
        st.caption("Nenhum termo no /historico.")
    else:
        eventos = []
        ordenados = termos.iloc[::-1]  # montar_termos ordena por assinatura crescente: mais recente primeiro
        for posicao, (_, termo) in enumerate(ordenados.iterrows()):
            titulo = " ".join(str(p) for p in (termo["tipo"], termo["numero"]) if not _nulo(p))
            # Regra (decisão do controlador, a confirmar com o usuário): "novo valor global" nulo ou
            # 0,00 é lido como "este termo não define novo valor" — mostra-se então o valor global
            # do termo, rotulado como tal. O dado bruto permanece intacto na fotografia/tabela.
            valor = (
                f"novo valor global {formatar_brl(termo['novo_valor_global'])}"
                if not _nulo(termo["novo_valor_global"]) and termo["novo_valor_global"] != 0
                else f"valor global do termo {formatar_brl(termo['valor_global'])}"
            )
            detalhes = [f"Assinado {_data(termo['data_assinatura'])}"]
            if not _nulo(termo["vigencia_inicio"]) or not _nulo(termo["vigencia_fim"]):
                detalhes.append(f"vigência {_data(termo['vigencia_inicio'])} – {_data(termo['vigencia_fim'])}")
            if not _nulo(termo["data_inicio_novo_valor"]):
                detalhes.append(f"novo valor a partir de {_data(termo['data_inicio_novo_valor'])}")
            if termo["retroativo"] is True:
                periodo = "" if _nulo(termo["retroativo_periodo"]) else f" {termo['retroativo_periodo']}"
                detalhes.append(f"retroativo{periodo}: {formatar_brl(termo['retroativo_valor'])}")
            classe = "ctg-ev ini" if posicao == len(ordenados) - 1 else "ctg-ev"
            eventos.append(
                f'<div class="{classe}"><div class="l1"><b>{escape(titulo)}</b><span>{escape(valor)}</span></div>'
                f'<div class="l2">{escape(" · ".join(detalhes))}</div></div>'
            )
        st.markdown(f'<div class="ctg-timeline">{"".join(eventos)}</div>', unsafe_allow_html=True)

    st.markdown(
        f'<div class="cad-secao-dialogo">Notas de empenho · {len(empenhos)} · do /empenhos · valores do SIAFI '
        "informados pelo Contratos.gov.br</div>",
        unsafe_allow_html=True,
    )
    if empenhos.empty:
        st.caption("Nenhuma NE vinculada no /empenhos.")
    else:
        linhas = [
            [
                celula_principal(e["ne"], e["ne_ccor"]),
                celula_suave(_data(e["data_emissao"])),
                celula_principal(e["natureza_despesa"], e["plano_interno"]),
                celula_valor(e["empenhado"]), celula_valor(e["liquidado"]),
                celula_valor(e["pago"]), celula_valor(e["rp_pago"]),
            ]
            for _, e in empenhos.iterrows()
        ]
        rodape = [
            '<div class="cad-total-rotulo">Total</div>', "", "",
            *(celula_valor(_soma(empenhos[c])) for c in ("empenhado", "liquidado", "pago", "rp_pago")),
        ]
        st.markdown(
            tabela_html(
                [("NE", False), ("Emissão", False), ("Natureza / PI", False), ("Empenhado", True),
                 ("Liquidado", True), ("Pago", True), ("RP pago", True)],
                linhas, [1.7, 0.9, 2.0, 1.2, 1.2, 1.2, 1.1], rodape, rolagem=len(linhas) > 8,
            ),
            unsafe_allow_html=True,
        )

    origem = "" if _nulo(linha["detalhe_origem"]) else f" ({linha['detalhe_origem']})"
    st.caption(
        f"Detalhe consultado em {_data_hora(linha['detalhe_consultado_em'])}{origem} · fotografia {sha12} · "
        f"id no Contratos.gov.br: {cid}"
    )


def _abrir_detalhe(linha, termos, empenhos, complemento, editavel, sha12) -> None:
    st.dialog(f"Contrato {linha['numero']}", width="large")(_detalhe_contrato)(
        linha, termos, empenhos, complemento, editavel, sha12
    )


# ----------------------------------------------------------------------------- aba Cadastro

def _render_cadastro(contratos, termos, empenhos, manifesto, complementos, complementos_ok, referencia) -> None:
    r = resumo(contratos)
    ate = referencia + timedelta(days=90)
    with st.container(key="ctg_resumo"):
        st.markdown(
            cartao_resumo(
                "Contratos da UFRPE no Contratos.gov.br",
                f"{r['ativos_api']} ativo(s) + {r['inativos_api']} inativo(s) na API · tipo \"Contrato\", todos os anos.",
                {
                    "rotulo": "Vigentes em " + referencia.strftime("%d/%m/%Y"),
                    "valor": f"{r['vigentes']} de {r['total']} contratos",
                    "detalhe": "Vigência calculada pelas datas — não pelo campo \"situação\" da API",
                    "tom": "info",
                },
                [
                    ("Contratos", str(r["total"])),
                    ("Vigentes", str(r["vigentes"])),
                    ("Vencem em 90 dias", str(r["vencem_90"])),
                    ("Valor global vigentes", formatar_brl(r["valor_global_vigentes"])),
                ],
            ),
            unsafe_allow_html=True,
        )
    st.caption(f"Vencem em 90 dias: vigentes com fim da vigência até {ate.strftime('%d/%m/%Y')}.")

    situacao = contratos["situacao_vigencia"]
    mascaras = {
        "Vigentes": situacao.eq("vigente"),
        "A iniciar": situacao.eq("a_iniciar"),
        "Encerrados": situacao.eq("encerrado"),
        "Inativos": situacao.eq("inativo"),
    }
    if situacao.eq("sem_vigencia").any():
        mascaras["Sem vigência"] = situacao.eq("sem_vigencia")
    mascaras["Todos"] = pd.Series(True, index=contratos.index)
    contagens = contagens_por_aba(mascaras)

    dados = contratos.assign(
        _valor_global_ordem=contratos["valor_global"].map(lambda v: float("nan") if _nulo(v) else float(v)),
        _dias_abs_ordem=contratos["dias_para_vencer"].map(lambda d: float("nan") if _nulo(d) else float(abs(int(d)))),
        _numero_ordem=pd.to_numeric(contratos["ano_contrato"], errors="coerce") * 100000
        + pd.to_numeric(contratos["numero"].str.extract(r"^(\d{5})/", expand=False), errors="coerce"),
    )

    with st.container(border=True, key="cad_registro"):
        aba = st.segmented_control(
            "Situação", list(mascaras), default="Vigentes", key="cad_abas_ctg",
            format_func=lambda rotulo: f"{rotulo} ({contagens[rotulo]})", label_visibility="collapsed",
        ) or "Vigentes"
        c_busca, c_cat, c_ordem = st.columns([3, 1.3, 1.5], vertical_alignment="center")
        busca = c_busca.text_input(
            "Buscar", key="ctg_busca", label_visibility="collapsed",
            placeholder="Buscar por nº do contrato, fornecedor, CNPJ/CPF, processo ou objeto",
        )
        categorias = sorted(contratos["categoria"].dropna().astype(str).unique(), key=str.casefold)
        categoria = c_cat.selectbox(
            "Categoria", ["Todas as categorias", *categorias], key="ctg_categoria", label_visibility="collapsed",
        )
        ordem = c_ordem.selectbox("Ordenar", list(ORDENACOES), key="ctg_ordem", label_visibility="collapsed")

        registro = dados[mascaras[aba]]
        if categoria != "Todas as categorias":
            registro = registro[registro["categoria"].astype("string") == categoria]
        termo_busca = busca.strip().casefold()
        if termo_busca:
            # Dígitos casam com o documento do fornecedor só em busca numérica (sem letras, >= 4 dígitos):
            # "ltda 2" não pode casar com todo CNPJ que contenha "2".
            digitos = "".join(ch for ch in termo_busca if ch.isdigit())
            if len(digitos) < 4 or any(ch.isalpha() for ch in termo_busca):
                digitos = ""
            texto = registro[["numero", "fornecedor_nome", "processo", "objeto"]].fillna("").astype(str).agg("\n".join, axis=1)  # "\n": a busca não atravessa campos
            achou = texto.str.casefold().str.contains(termo_busca, regex=False)
            if digitos:
                achou |= registro["fornecedor_documento"].fillna("").astype(str).str.contains(digitos, regex=False)
            registro = registro[achou]
        coluna, crescente = ORDENACOES[ordem]
        registro = ordenar_por(registro, coluna, crescente)

        st.markdown(
            f'<div class="cad-contagem">{len(registro)} contrato(s) · '
            f'{formatar_brl(_soma(registro["valor_global"]))} de valor global</div>',
            unsafe_allow_html=True,
        )

        mostrar_todos = st.session_state.get("ctg_mostrar_todos", False)
        visiveis = registro if mostrar_todos else registro.iloc[:QTD_INICIAL_REGISTRO]
        if registro.empty:
            st.markdown('<div class="cad-vazio">Nenhum contrato nesta situação/busca.</div>', unsafe_allow_html=True)
        else:
            cab = st.columns(PROPORCOES_REGISTRO)
            for col, (rotulo, direita) in zip(cab, CABECALHOS_REGISTRO):
                col.markdown(f'<div class="cad-cabecalho{" direita" if direita else ""}">{escape(rotulo)}</div>', unsafe_allow_html=True)

        sha12 = manifesto.sha256[:12]
        for _, linha in visiveis.iterrows():
            cid = linha["contrato_id"]
            complemento = complementos.get(cid)
            with st.container(key=f"cad_linha_ctg_{cid}"):
                cel = st.columns(PROPORCOES_REGISTRO, vertical_alignment="center")
                doc = _documento(linha["fornecedor_documento"])
                nome = "" if _nulo(linha["fornecedor_nome"]) else str(linha["fornecedor_nome"])
                cel[0].markdown(celula_principal(linha["numero"], " · ".join(p for p in (nome, doc) if p)), unsafe_allow_html=True)
                cel[1].markdown(celula_categoria(linha["categoria"]), unsafe_allow_html=True)
                cel[2].markdown(
                    f'<div class="ctg-vig">até {_data(linha["vigencia_fim"])} {_chip_situacao(linha)}</div>',
                    unsafe_allow_html=True,
                )
                cel[3].markdown(celula_valor(linha["valor_global"]), unsafe_allow_html=True)
                if complemento is not None and complemento.valor_mensal is not None:
                    cel[4].markdown(
                        f'<div class="cad-valor">{escape(formatar_brl(complemento.valor_mensal))}'
                        '<span class="ctg-manual">MANUAL</span></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    cel[4].markdown(celula_valor(None, vazio="—"), unsafe_allow_html=True)
                cel[5].markdown(f'<div class="ctg-num">{int(linha["qtd_termos"])}</div>', unsafe_allow_html=True)
                cel[6].markdown(f'<div class="ctg-num">{int(linha["qtd_empenhos"])}</div>', unsafe_allow_html=True)
                with cel[7]:
                    with st.container(key=f"cad_acoes_ctg_{cid}"):
                        if st.button("", icon=":material/open_in_full:", key=f"ctg_detalhe_{cid}",
                                     help="Ver o detalhe do contrato", use_container_width=True):
                            _abrir_detalhe(
                                linha,
                                termos[termos["contrato_id"] == cid],
                                empenhos[empenhos["contrato_id"] == cid],
                                complemento, complementos_ok, sha12,
                            )

        if len(registro) > QTD_INICIAL_REGISTRO:
            c_mais, c_texto = st.columns([1, 3], vertical_alignment="center")
            if not mostrar_todos:
                c_texto.caption(f"Mostrando {QTD_INICIAL_REGISTRO} de {len(registro)} contratos")
                if c_mais.button("Ver mais", key="ctg_mais"):
                    st.session_state["ctg_mostrar_todos"] = True
                    st.rerun()
            elif c_mais.button("Ver menos", key="ctg_menos"):
                st.session_state["ctg_mostrar_todos"] = False
                st.rerun()

    st.caption(
        "Clique no ícone da linha para ver o detalhe. Valor mensal: só complemento manual "
        "(a API não traz parcela confiável)."
    )

    ausentes = contratos_complementos.complementos_ausentes(complementos, set(contratos["contrato_id"]))
    if ausentes:
        with st.expander("Complementos de contratos ausentes na última consulta"):
            st.caption("Preservados: o contrato não veio na fotografia atual, mas o complemento digitado não é apagado.")
            st.markdown(
                tabela_html(
                    [("Id no Contratos.gov.br", False), ("Valor mensal", True), ("Observações", False), ("Alterado em", False)],
                    [
                        [celula_suave(c.contrato_id), celula_valor(c.valor_mensal), celula_suave(c.observacoes or "—"),
                         celula_suave(_data_hora(c.alterado_em))]
                        for c in ausentes
                    ],
                    [1.2, 1.2, 3.0, 1.3],
                ),
                unsafe_allow_html=True,
            )


# ----------------------------------------------------------------------------- aba Atualizar

def _consultar(fotografia, completa: bool, referencia: date) -> None:
    """Consulta a API e guarda fotografia nova + delta na sessão. Nada é gravado aqui."""

    st.session_state.pop(CHAVE_CONSULTA, None)  # prévia antiga não sobrevive a uma nova consulta (nem falha)
    cliente = contratosgov_api.ClienteContratosGov()
    barra = st.progress(0.0, text="Consultando as listas de contratos… (a lista de ativos pode levar cerca de 1 minuto)")

    def progresso(feito: int, total: int) -> None:
        barra.progress(feito / total if total else 1.0, text=f"Detalhe (termos e NEs): {feito} de {total} contratos")

    inicio = time.monotonic()
    try:
        nova = contratosgov_extracao.consultar(
            cliente, fotografia, referencia=referencia, agora=datetime.now(), completa=completa, progresso=progresso,
        )
        delta = contratosgov_extracao.calcular_delta(fotografia, nova)
        contratos_novos = montar_contratos(nova, referencia)  # valida antes da prévia
    except contratosgov_api.ErroApiContratosGov as erro:
        barra.empty()
        status = f" (HTTP {erro.status})" if erro.status is not None else ""
        st.error(f"Falha ao consultar {erro.url}{status}: {erro}. A fotografia anterior continua valendo.")
        return
    except ErroDadoContratosGov as erro:
        barra.empty()
        st.error(f"A API devolveu um dado fora do formato esperado: {erro}. A fotografia anterior continua valendo.")
        return
    barra.progress(1.0, text="Consulta concluída")
    origens = [str(d.get("origem") or "") for d in nova["detalhes"].values()]
    st.session_state[CHAVE_CONSULTA] = {
        "nova": nova,
        "delta": delta,
        "contratos": contratos_novos,
        "anterior_em": None if fotografia is None else fotografia.get("consultado_em"),
        "chamadas": getattr(cliente, "chamadas", None),
        "segundos": time.monotonic() - inicio,
        "reconsultados": sum(o == "consulta" for o in origens),
        "reaproveitados": len(origens) - sum(o == "consulta" for o in origens),
    }


def _lista_delta(titulo: str, itens: list, linhas: list[list[str]], proporcoes: list[float], aberto=False) -> None:
    if not itens:
        return
    with st.expander(f"{titulo} ({len(itens)})", expanded=aberto):
        colunas = [("", False)] * len(proporcoes)
        st.markdown(tabela_html(colunas, linhas, proporcoes, rolagem=len(linhas) > 10), unsafe_allow_html=True)


def _render_previa(consulta: dict, referencia: date) -> None:
    delta = consulta["delta"]
    novos = consulta["contratos"].set_index("contrato_id")
    with st.container(border=True, key="cad_secao_ctg_previa"):
        tempo = consulta["segundos"]
        chamadas = "" if consulta["chamadas"] is None else f"{consulta['chamadas']} chamadas · "
        st.markdown(
            f"**Consulta concluída** — {chamadas}{int(tempo // 60)} min {int(tempo % 60)} s · "
            f"detalhe reconsultado: {consulta['reconsultados']} · reaproveitado: {consulta['reaproveitados']}"
        )
        base = (
            f"em relação a {_data_hora(consulta['anterior_em'])}" if consulta["anterior_em"] else "primeira carga"
        )
        st.markdown(f'<div class="cad-secao-dialogo">Prévia — o que muda ({base})</div>', unsafe_allow_html=True)
        removidos = len(delta.contratos_ausentes) + len(delta.termos_removidos) + len(delta.nes_removidas)
        st.markdown(
            grade_indicadores([
                ("Contratos novos", str(len(delta.contratos_novos))),
                ("Termos novos (aditivos / apostilamentos)", str(len(delta.termos_novos))),
                ("Vigência alterada", str(len(delta.vigencia_alterada))),
                ("Valor global alterado", str(len(delta.valor_global_alterado))),
                ("NEs novas · NEs com valores movimentados", f"{len(delta.nes_novas)} · {delta.nes_movimentadas}"),
                ("Removidos (contrato, termo ou NE)", str(removidos)),
            ]),
            unsafe_allow_html=True,
        )

        def info(cid):
            return novos.loc[cid] if cid in novos.index else None

        linhas_novos = []
        for item in delta.contratos_novos:
            c = info(item["contrato_id"])
            nome = "" if c is None or _nulo(c["fornecedor_nome"]) else str(c["fornecedor_nome"])
            vig = "—" if c is None else f"{_data(c['vigencia_inicio'])} – {_data(c['vigencia_fim'])}"
            linhas_novos.append([
                celula_principal(item["numero"], nome), celula_suave(vig),
                celula_valor(None if c is None else c["valor_global"]),
            ])
        _lista_delta("Contratos novos", delta.contratos_novos, linhas_novos, [3, 1.6, 1.3], aberto=True)
        _lista_delta(
            "Termos novos", delta.termos_novos,
            [[celula_principal(t["numero"], " ".join(str(p) for p in (t["tipo"], t["termo_numero"]) if p))]
             for t in delta.termos_novos],
            [1],
        )
        alteracoes = [
            [celula_suave(a["numero"]), celula_suave("Fim da vigência"),
             f'<div class="cad-suave"><span class="ctg-antes">{escape(_data(a["antes"]))}</span> → {escape(_data(a["depois"]))}</div>']
            for a in delta.vigencia_alterada
        ] + [
            [celula_suave(a["numero"]), celula_suave("Valor global"),
             f'<div class="cad-suave"><span class="ctg-antes">{escape(_valor_texto_api(a["antes"]))}</span> → '
             f'{escape(_valor_texto_api(a["depois"]))}</div>']
            for a in delta.valor_global_alterado
        ] + [
            [celula_suave(a["numero"]), celula_suave("Lista na API"),
             f'<div class="cad-suave"><span class="ctg-antes">{"inativo" if a["antes"] else "ativo"}</span> → '
             f'{"inativo" if a["depois"] else "ativo"}</div>']
            for a in delta.situacao_alterada
        ]
        _lista_delta("Vigência, valor e situação alterados", alteracoes, alteracoes, [1, 1.2, 2.5])
        _lista_delta(
            "NEs novas", delta.nes_novas,
            [[celula_principal(n["ne"], f"{n['ne_ccor']} · contrato {n['numero']}")] for n in delta.nes_novas], [1],
        )

        aceito = True
        if delta.exige_confirmacao():
            itens = (
                [f"Contrato {a['numero']}: não veio mais na API." for a in delta.contratos_ausentes]
                + [f"Contrato {t['numero']}: o termo {t['tipo'] or ''} {t['termo_numero'] or ''} não está mais no /historico."
                   for t in delta.termos_removidos]
                + [f"Contrato {n['numero']}: a NE {n['ne_ccor']} não está mais vinculada a ele." for n in delta.nes_removidas]
            )
            lista = "".join(f"<li>{escape(i)}</li>" for i in itens)
            st.markdown(
                f'<div class="ctg-alerta"><b>{removidos} item(ns) deixou(aram) de aparecer na API.</b>'
                f'<ul style="margin:6px 0">{lista}</ul>Eles continuam registrados nas fotografias anteriores — nada é apagado.</div>',
                unsafe_allow_html=True,
            )
            aceito = st.checkbox("Estou ciente da remoção", key=f"ctg_ciente_{consulta['nova']['consultado_em']}")
        elif not any(delta.contagens().values()):
            st.info("Nenhuma mudança em relação à fotografia anterior. Gravar registra a consulta no histórico.")

        c_descartar, c_gravar, _ = st.columns([1, 1.3, 3])
        if c_descartar.button("Descartar", key="ctg_descartar"):
            st.session_state.pop(CHAVE_CONSULTA, None)
            st.session_state[CHAVE_AVISO] = "Consulta descartada; nada foi gravado."
            st.rerun()
        if c_gravar.button("Gravar fotografia", key="ctg_gravar", type="primary", disabled=not aceito):
            try:
                manifesto = contratosgov_extracao.gravar(
                    consulta["nova"], delta, ciente_remocao=aceito, importado_em=datetime.now(), referencia=referencia,
                )
            except (contratosgov_extracao.ConfirmacaoNecessaria, ErroDadoContratosGov, ValueError, OSError) as erro:
                st.error(f"A fotografia não foi gravada: {erro}")
            else:
                st.session_state.pop(CHAVE_CONSULTA, None)
                st.session_state[CHAVE_AVISO] = f"Fotografia {manifesto.sha256[:12]} gravada."
                st.rerun()


def _render_atualizar(fotografia, contratos, referencia, erro_carga=None) -> None:
    st.markdown('<div class="cad-secao-titulo">Atualizar do Contratos.gov.br</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="cad-secao-desc">Consulta só de leitura. Nada é gravado antes de você confirmar; '
        "a fotografia anterior continua valendo se algo falhar.</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="ctg-passos">'
        f'<div class="ctg-passo"><b>1 · Lista</b>Contratos ativos e inativos da UG {contratosgov_extracao.UG_UFRPE} (2 chamadas).</div>'
        '<div class="ctg-passo"><b>2 · Detalhe</b>Termos e NEs dos vigentes, a iniciar, novos e alterados; '
        "os demais reaproveitam a fotografia anterior.</div>"
        '<div class="ctg-passo"><b>3 · Prévia</b>O que mudou desde a última fotografia. Confirme para gravar.</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    if fotografia is None:
        if erro_carga is not None:
            st.info(
                "A fotografia atual não pôde ser lida (veja o erro no topo): a carga abaixo é completa e, "
                "ao gravar, vira a nova fotografia atual. As anteriores continuam no histórico."
            )
        else:
            st.info(
                "Ainda não há dados do Contratos.gov.br. Faça a primeira carga "
                "(cerca de 2 chamadas por contrato, alguns minutos)."
            )
        if st.button("Fazer primeira carga", key="ctg_primeira_carga", type="primary"):
            _consultar(None, True, referencia)
    else:
        total = len(contratos)
        c_botao, c_opcao = st.columns([1, 3], vertical_alignment="center")
        completa = c_opcao.checkbox(
            f"Atualização completa (reconsultar todos os {total} — ~{2 * total + 2} chamadas)", key="ctg_completa",
        )
        if c_botao.button("Consultar agora", key="ctg_consultar", type="primary"):
            _consultar(fotografia, completa, referencia)

    consulta = st.session_state.get(CHAVE_CONSULTA)
    if consulta is not None:
        _render_previa(consulta, referencia)


# ----------------------------------------------------------------------------- aba Histórico

def _mudancas(contagens: dict) -> str:
    rotulos = [
        ("delta_contratos_novos", "novo(s)"), ("delta_contratos_ausentes", "ausente(s)"),
        ("delta_termos_novos", "termo(s) novo(s)"), ("delta_termos_removidos", "termo(s) removido(s)"),
        ("delta_vigencia_alterada", "vigência(s) alterada(s)"), ("delta_valor_global_alterado", "valor(es) alterado(s)"),
        ("delta_situacao_alterada", "situação(ões) alterada(s)"), ("delta_nes_novas", "NE(s) nova(s)"),
        ("delta_nes_removidas", "NE(s) desvinculada(s)"), ("delta_nes_movimentadas", "NE(s) movimentada(s)"),
    ]
    partes = [f"{contagens[c]} {r}" for c, r in rotulos if contagens.get(c)]
    return " · ".join(partes) if partes else "sem mudanças"


def _render_historico(manifesto_atual) -> None:
    st.markdown('<div class="cad-secao-titulo">Histórico de atualizações</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="cad-secao-desc">Cada linha é uma fotografia gravada (manifesto em <code>data/manifestos/</code>). '
        "As anteriores nunca são sobrescritas.</div>",
        unsafe_allow_html=True,
    )
    manifestos = contratosgov_extracao.historico_atualizacoes()
    if not manifestos:
        st.info("Nenhuma atualização gravada ainda.")
        return
    linhas = []
    for posicao, m in enumerate(manifestos):
        c = m.contagens
        atual = manifesto_atual is not None and m.sha256 == manifesto_atual.sha256
        consulta = escape(_data_hora(m.data_extracao)) + (f" {chip('atual', 'info')}" if atual else "")
        mudancas = "primeira carga" if posicao == len(manifestos) - 1 else _mudancas(c)

        def n(chave):
            return f'<div class="ctg-num">{escape(str(c.get(chave, "—")))}</div>'

        linhas.append([
            f'<div class="cad-suave">{consulta}</div>', f'<code class="ctg-hash">{escape(m.sha256[:12])}</code>',
            n("contratos"), n("vigentes"), n("termos"), n("empenhos"), n("reconsultados"), celula_suave(mudancas),
        ])
    st.markdown(
        tabela_html(
            [("Consulta", False), ("Fotografia", False), ("Contratos", True), ("Vigentes", True), ("Termos", True),
             ("NEs", True), ("Reconsultados", True), ("Mudanças", False)],
            linhas, [1.6, 1.2, 0.8, 0.8, 0.7, 0.7, 1.0, 2.6],
        ),
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------------------------- página

def _ir_para_atualizar() -> None:
    st.session_state[CHAVE_ABA] = "Atualizar"


st.markdown(css_cadastro(), unsafe_allow_html=True)
st.markdown(_css_pagina(), unsafe_allow_html=True)

referencia = _referencia()
fotografia, manifesto, contratos, termos, empenhos, erro_carga = _carregar(referencia)

c_titulo, c_acao = st.columns([3, 1.3])
with c_titulo:
    render_page_header("Contratos", "Cadastro da UG 153165 — UFRPE, a partir do Contratos.gov.br.", "Contratos")
with c_acao:
    st.write("")
    st.button("Atualizar do Contratos.gov.br", key="ctg_ir_atualizar", type="primary",
              on_click=_ir_para_atualizar, use_container_width=True)
    if manifesto is not None:
        st.markdown(
            f'<div class="ctg-fonte">Fotografia atual: {escape(_data_hora(manifesto.data_extracao))} · '
            f"<code>{escape(manifesto.sha256[:12])}</code></div>",
            unsafe_allow_html=True,
        )

aviso = st.session_state.pop(CHAVE_AVISO, None)
if aviso:
    st.success(aviso)

aba_cadastro, aba_atualizar, aba_historico = st.tabs(ABAS, key=CHAVE_ABA, on_change="rerun")

with aba_cadastro:
    if erro_carga is not None:
        st.warning("Cadastro indisponível: a fotografia atual não pôde ser lida (veja o erro acima).")
    elif contratos is None:
        st.info("Ainda não há dados do Contratos.gov.br. Faça a primeira carga na aba **Atualizar**.")
    else:
        complementos, complementos_ok = _carregar_complementos()
        _render_cadastro(contratos, termos, empenhos, manifesto, complementos, complementos_ok, referencia)

with aba_atualizar:
    _render_atualizar(fotografia, contratos, referencia, erro_carga)

with aba_historico:
    _render_historico(manifesto)
