"""Contratos — vigência, efeitos financeiros e reforço de empenho.

Adaptação do handoff de design (`painel_vigencia.py`: uma linha por contrato, histórico de
atos no detalhe) para o leitor e os tokens reais deste projeto — não
`data_loader_vigencia.py`/`design_tokens.py` do pacote de handoff. As abas de conciliação
financeira e qualidade de dados do handoff foram removidas (ver "Diferenças deliberadas").

Fonte: aba "BASE_CONTRATOS" da planilha "CONTRATOS UFRPE (planilhas Google)" (mantida
manualmente, exportação do Google Sheets) — `src/contratos_vigencia.py`, validado contra a
extração de 15/08/2026 (1314 termos, 438 contratos distintos, 1 célula de data corrompida na
origem já tratada). Não tem relação com `src/contratos_continuos.py` (planilha "SERVIÇOS
CONTÍNUOS", cruzada com a Execução Anual): esta tela trata de vigência/prazo contratual, não
de saldo de empenho — são bases e perguntas diferentes sobre os mesmos contratos.

Diferenças deliberadas em relação ao handoff:
  * Leitor real e testado (`src/contratos_vigencia.py`, com fixture congelada em
    `tests/fixtures/contratos_vigencia_2026-08-15.xlsx`) — o `data_loader_vigencia.py` do
    handoff nunca foi validado contra a planilha real (colunas certas por sorte, mas cabeçalho
    casado por texto exato, não normalizado; `pd.NA` de coluna "string" quebra `valor or ""`
    em vários pontos — ambos corrigidos aqui).
  * Os tokens de cor/tipografia são os reais do projeto (`src/design_tokens.py`), não os do
    pacote de handoff — inclui `WARNING` (a "Atenção" do handoff usava `ACCENT_STRONG`, cor de
    acento, não de alerta; aqui usa `WARNING`, semanticamente mais correto).
  * Banner de defasagem calculado a partir do `mtime` real do arquivo, não um texto fixo de
    exemplo ("não atualizados há 2 dias") — mostrar uma data fabricada seria pior que não
    mostrar nada.
  * "Atualizar dados" limpa o cache de leitura e reroda — no handoff era um botão decorativo
    sem ação.
  * Sem `st.set_page_config`/`main()`: como as demais páginas deste app, é um script direto
    executado por `st.navigation` (`app.py` já chama `st.set_page_config` uma única vez).
  * A aba "Empenhos" (dentro do detalhe do contrato) mantém o aviso do handoff (este leitor
    não segrega empenho por contrato) — cruzar com `src/contratos_continuos.py` por número de
    contrato é possível, mas é uma integração nova, fora do escopo de "implemente esse
    design".
  * As abas "Conciliação financeira" e "Qualidade dos dados" do handoff foram removidas por
    pedido explícito ("não retornam nada" — os botões de aprovar/ajustar/rejeitar nunca
    persistiam nada, então a aba de conciliação não levava a lugar nenhum). A coluna que
    antes se chamava "Conciliação" (valores "Bloqueado"/"Não calculado", nomes vindos do
    fluxo de aprovação removido) virou "Pendências" — mostra a contagem de alertas de
    qualidade de cada contrato ("N pendência(s)"/"Sem pendências"), com a lista completa dos
    alertas visível na aba "Visão geral" do detalhe do contrato (antes só aparecia na aba de
    conciliação removida).
  * Sem "Ordenar" por cabeçalho de coluna nem `st.dataframe`: um filtro dedicado por campo
    (Contrato, Contratado, Término, Dias, Criticidade, Mensal vigente, Pendências — pedido
    explícito), acima da lista, junto do "Ordenar" já existente (mesmo padrão de
    `app_pages/consulta_empenhos.py`, "Empenhos no escopo").
  * A lista mostra só contratos vigentes por padrão (pedido explícito) — uma caixa de
    seleção "Mostrar todos os contratos" volta a incluir encerrados/sem termo final. Os
    filtros de Término/Dias/Criticidade/etc. continuam calculados sobre todos os 438
    contratos (não só os vigentes), para os limites de intervalo não mudarem cada vez que a
    caixa é marcada/desmarcada.
  * A lista mostra no máximo `QTD_INICIAL_LISTA` (20) contratos por vez, com um botão "Ver
    mais" para revelar mais `QTD_INCREMENTO_LISTA` (20) — mesmo padrão de "Ver mais" de
    `app_pages/consulta_empenhos.py`.
  * Prioridade de exibição (pedido explícito, sempre a chave de ordenação primária, antes do
    "Ordenar" escolhido): 1º os contratos que também aparecem em Contratos Contínuos
    (`src/contratos_continuos.py`, cruzado por número de contrato — 31 dos 32 contratos
    daquela base batem por número; "SN/2026" é um placeholder sem correspondência real), 2º
    os demais, por último os vencidos (mesmo que também estejam em Contratos Contínuos). Sem
    a planilha de Contratos Contínuos disponível, essa priorização vira só "vencidos por
    último" — sem o primeiro grupo.
  * As "principais informações" do contrato (pedido explícito) viraram campos editáveis
    dentro do diálogo de detalhe (aba "Visão geral": contratado, CNPJ/CPF, classificação,
    tipo de despesa, objeto, término, unidade gestora, valor mensal/anual; aba "Documentos e
    responsáveis": gestor, e-mail, garantia) — mesmo padrão de edição só-nesta-sessão de
    `bolsas_auxilios.py`/`contratos_continuos.py`. `_aplicar_edicoes_da_sessao` sobrepõe essas
    edições no DataFrame ANTES de calcular KPIs/filtros/lista e recalcula
    criticidade/situação/pendências a partir delas — sem isso, uma edição só apareceria
    dentro do próprio diálogo (mesmo bug já corrigido antes em `bolsas_auxilios.py`).
  * Novo quadro "Vigência × Contratos Contínuos" (pedido explícito, para achar incoerências):
    cruza, por número de contrato, o valor mensal/anual desta base contra o de Contratos
    Contínuos (despesa somada por contrato quando há mais de um item de licitação — mesmo
    motivo de `_render_quadro_dotacao` daquela página, que soma por PTRES). Mesmo padrão
    visual (grade `.ct-*`) do resto desta página, não os cartões `.cc-dotacao-*`/
    `.bls-dotacao-*` de outras páginas.
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.contratos_continuos import ler_contratos_continuos
from src.contratos_vigencia import classificar_criticidade, consolidar_por_contrato, ler_contratos_vigencia, termos_do_contrato
from src.design_tokens import ACCENT_STRONG, BORDER, FONT_HEADING, NEGATIVE, POSITIVE, SURFACE, TEXT_MUTED, WARNING
from src.ui_theme import render_page_header

DIRETORIO_DADOS_BRUTOS = Path("data/raw")
CAMINHO_BASE = DIRETORIO_DADOS_BRUTOS / "CONTRATOS UFRPE - BASE_CONTRATOS.xlsx"
#: para priorizar, na lista, os contratos que também aparecem em Contratos Contínuos (ver
#: `_numeros_em_contratos_continuos`) — mesmo arquivo usado por app_pages/contratos_continuos.py.
CAMINHO_CONTRATOS_CONTINUOS = DIRETORIO_DADOS_BRUTOS / "SERVIÇOS CONTÍNUOS - 2026 - AGO A DEZ.xlsm"

CRITICIDADE_COR = {
    "Vencido": NEGATIVE, "Crítico": NEGATIVE, "Atenção": WARNING,
    "No prazo": POSITIVE, "Indeterminado": TEXT_MUTED,
}

#: mesmo padrão de "Ver mais" de app_pages/consulta_empenhos.py ("Empenhos no escopo").
QTD_INICIAL_LISTA = 20
QTD_INCREMENTO_LISTA = 20

#: mesmo padrão de "Ordenar" de app_pages/consulta_empenhos.py ("Empenhos no escopo") — um
#: seletor ao lado do título da lista, não cabeçalho de coluna clicável nem st.dataframe.
ORDENS_CONTRATOS = [
    "Contrato", "Contratado", "Término mais próximo", "Mais dias até vencer",
    "Criticidade (mais crítico primeiro)", "Maior valor mensal", "Pendências (mais primeiro)",
]
_ORDEM_CRITICIDADE = {"Vencido": 0, "Crítico": 1, "Atenção": 2, "No prazo": 3, "Indeterminado": 4}


@st.cache_data(show_spinner="Lendo a base de vigência de contratos...")
def _cached_leitura(caminho: str, mtime: float) -> pd.DataFrame:
    """`mtime` só participa da chave de cache — força reler se o arquivo mudar."""

    return ler_contratos_vigencia(caminho)


@st.cache_data(show_spinner=False)
def _cached_numeros_contratos_continuos(caminho: str, mtime: float) -> set[str]:
    """Números de contrato (`23/2025`, etc.) que aparecem na base de Contratos Contínuos —
    para priorizar esses na lista desta página (pedido explícito). `mtime` só participa da
    chave de cache."""

    return set(ler_contratos_continuos(caminho)["contrato_numero"].dropna().unique())


@st.cache_data(show_spinner="Lendo a base de Contratos Contínuos...")
def _cached_valores_contratos_continuos(caminho: str, mtime: float) -> pd.DataFrame:
    """Despesa mensal/anual por número de contrato, somada por contrato (um contrato pode ter
    vários itens de licitação — mesmo motivo de `app_pages/contratos_continuos.py::
    _render_quadro_dotacao`, que já soma por PTRES pela mesma razão). `mtime` só participa da
    chave de cache."""

    bruto = ler_contratos_continuos(caminho)
    return bruto.groupby("contrato_numero").agg(
        despesa_mensal_continuos=("despesa_mensal", "sum"),
        despesa_anual_continuos=("despesa_anual", "sum"),
    )


def _brl(v: object) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "Não calculado"
    negativo = v < 0
    texto = "R$ " + f"{abs(round(v)):,.0f}".replace(",", ".")
    return ("−" if negativo else "") + texto


def _fmt_data(d: object) -> str:
    if d is None or (isinstance(d, float) and pd.isna(d)):
        return "Sem termo final"
    return d.strftime("%d/%m/%Y")


def _ou_vazio(valor: object) -> str:
    return "" if pd.isna(valor) else str(valor)


def _ou_zero(valor: object) -> float:
    return 0.0 if pd.isna(valor) else float(valor)


def _normalizar(texto: object) -> str:
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return sem_acento.strip().upper()


def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .ct-kicker {{ font-family: {FONT_HEADING}; font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: {TEXT_MUTED}; }}
        .ct-label {{ font-family: {FONT_HEADING}; font-size: 9px; letter-spacing: .08em; text-transform: uppercase; color: {TEXT_MUTED}; }}
        .ct-badge {{ display: inline-block; font-family: {FONT_HEADING}; font-size: 9.5px; letter-spacing: .04em;
          text-transform: uppercase; padding: 2px 7px; border-radius: 3px; margin: 0 4px 4px 0; }}
        .ct-banner {{ padding: 9px 14px; border: 1px solid {WARNING}; background: {WARNING}1A; color: {WARNING}; font-size: 12.5px; border-radius: 4px; }}
        .st-key-cv_tabela div[data-testid="stVerticalBlockBorderWrapper"] {{ border: 1px solid {BORDER} !important; border-radius: 4px; background: {SURFACE}; }}
        .st-key-cv_comparacao div[data-testid="stVerticalBlockBorderWrapper"] {{ border: 1px solid {BORDER} !important; border-radius: 4px; background: {SURFACE}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _badge(texto: str, cor: str) -> str:
    return f"<span class='ct-badge' style='background:{cor}22;color:{cor}'>{texto}</span>"


def _situacao_de(row: pd.Series) -> str:
    if pd.isna(row["termo_final"]):
        return "Sem termo final"
    return "Encerrado" if row["criticidade"] == "Vencido" else "Vigente"


#: sufixo da key do widget editável (ver `_abrir_detalhe`) -> coluna do DataFrame que ele edita.
_CAMPOS_EDITAVEIS_TEXTO = {
    "contratado": "contratado", "cnpj_cpf": "cnpj_cpf", "classificacao_objeto": "classificacao_objeto",
    "tipo_despesa": "tipo_despesa", "objeto": "objeto", "unidade_gestora": "unidade_gestora",
    "gestor": "gestor", "email_gestor": "email_gestor", "garantia_status": "garantia_status",
}
_CAMPOS_EDITAVEIS_NUMERICOS = {"valor_mensal": "valor_mensal", "valor_anual": "valor_anual"}


def _recalcular_alertas(row: pd.Series) -> list[str]:
    """Mesmas regras de `src.contratos_vigencia.consolidar_por_contrato` — duplicadas aqui
    (não importadas, a função de origem é privada ao módulo) para recalcular depois de uma
    edição na sessão."""

    alertas = []
    if pd.isna(row["termo_final"]):
        alertas.append("Sem termo final")
    if not _ou_vazio(row.get("gestor")).strip():
        alertas.append("Sem gestor")
    if not _ou_vazio(row.get("arquivo_pdf")).strip():
        alertas.append("Sem documento")
    cnpj_cpf = row.get("cnpj_cpf")
    if pd.notna(cnpj_cpf) and len(str(cnpj_cpf)) not in (11, 14):
        alertas.append("CNPJ/CPF suspeito")
    if pd.isna(row.get("valor_mensal")):
        alertas.append("Sem valor mensal")
    if _normalizar(row.get("garantia_status")) in ("PENDENTE", "NAO REGULARIZADA"):
        alertas.append("Garantia pendente")
    return alertas


def _aplicar_edicoes_da_sessao(contratos: pd.DataFrame) -> pd.DataFrame:
    """Sobrepõe, por contrato, os valores já editados no diálogo de detalhe (persistidos em
    `st.session_state` pela key do widget, ver `_abrir_detalhe`) e recalcula os campos
    derivados a partir deles — mesmo padrão (e mesmo motivo) de
    `app_pages/bolsas_auxilios.py::_aplicar_edicoes_da_sessao`: sem isso, uma edição só
    aparecia dentro do próprio diálogo, nunca nos KPIs/filtros/lista, que são calculados a
    partir do DataFrame antes de `_abrir_detalhe` desenhar os widgets."""

    resultado = contratos.copy()
    for indice, numero in resultado["numero_contrato"].items():
        k = f"cv_edit_{numero}"
        for sufixo, coluna in _CAMPOS_EDITAVEIS_TEXTO.items():
            valor = st.session_state.get(f"{k}_{sufixo}")
            if valor is not None:
                resultado.at[indice, coluna] = valor if valor != "" else pd.NA
        for sufixo, coluna in _CAMPOS_EDITAVEIS_NUMERICOS.items():
            valor = st.session_state.get(f"{k}_{sufixo}")
            if valor is not None:
                resultado.at[indice, coluna] = valor
        termo_final_editado = st.session_state.get(f"{k}_termo_final")
        if termo_final_editado is not None:
            resultado.at[indice, "termo_final"] = termo_final_editado

    hoje = date.today()
    resultado["dias_para_vencer"] = resultado["termo_final"].apply(
        lambda t: (t - hoje).days if pd.notna(t) else None
    )
    resultado["criticidade"] = resultado["dias_para_vencer"].apply(classificar_criticidade)
    resultado["situacao"] = resultado.apply(_situacao_de, axis=1)
    resultado["alertas"] = resultado.apply(_recalcular_alertas, axis=1)
    resultado["pendencias_qtd"] = resultado["alertas"].apply(len)
    resultado["conciliacao_status"] = resultado["pendencias_qtd"].apply(lambda n: "Com pendências" if n else "Sem pendências")
    return resultado


@st.dialog("Detalhe do contrato", width="large")
def _abrir_detalhe(numero: str, contratos: pd.DataFrame, termos: pd.DataFrame) -> None:
    row = contratos[contratos["numero_contrato"] == numero].iloc[0]
    cor = CRITICIDADE_COR.get(row["criticidade"], TEXT_MUTED)
    st.markdown(f"### Contrato {row['numero_contrato']}")
    st.caption(_ou_vazio(row["contratado"]) or "—")
    cor_pendencias = NEGATIVE if row["pendencias_qtd"] else POSITIVE
    st.markdown(
        _badge(_situacao_de(row), TEXT_MUTED) + _badge(row["criticidade"], cor)
        + _badge(row.get("conciliacao_status", "Sem pendências"), cor_pendencias),
        unsafe_allow_html=True,
    )
    objeto = _ou_vazio(row.get("objeto"))
    if objeto:
        st.markdown(f"<div style='font-size:12.5px;color:{TEXT_MUTED}'>{objeto[:280]}</div>", unsafe_allow_html=True)

    k = st.columns(4)
    k[0].metric("Mensal vigente", _brl(row["valor_mensal"]))
    k[1].metric("Anual contratual", _brl(row["valor_anual"]))
    k[2].metric("Projeção exercício", _brl(row["valor_anual"]))
    k[3].metric("Necessidade de reforço", "Não calculado")

    aba_geral, aba_linha, aba_fin, aba_emp, aba_doc, aba_aud = st.tabs(
        ["Visão geral", "Linha do tempo", "Financeiro", "Empenhos", "Documentos e responsáveis", "Auditoria"]
    )

    grupo = termos_do_contrato(termos, numero)

    with aba_geral:
        st.caption(
            "Campos editáveis — as alterações valem só nesta sessão (não são gravadas na "
            "planilha de origem) e já se refletem nos filtros, KPIs e na lista assim que o "
            "diálogo é fechado."
        )
        k_edit = f"cv_edit_{numero}"
        st.markdown("**Identificação**")
        c1, c2 = st.columns(2)
        c1.text_input("Contratado", value=_ou_vazio(row["contratado"]), key=f"{k_edit}_contratado")
        c2.text_input("CNPJ/CPF", value=_ou_vazio(row["cnpj_cpf"]), key=f"{k_edit}_cnpj_cpf")
        c3, c4 = st.columns(2)
        c3.text_input("Classificação do objeto", value=_ou_vazio(row["classificacao_objeto"]), key=f"{k_edit}_classificacao_objeto")
        c4.text_input("Tipo de despesa", value=_ou_vazio(row["tipo_despesa"]), key=f"{k_edit}_tipo_despesa")
        st.text_area("Objeto", value=_ou_vazio(row["objeto"]), key=f"{k_edit}_objeto")

        st.markdown("**Vigência e valores**")
        c5, c6 = st.columns(2)
        c5.date_input(
            "Término", value=row["termo_final"] if pd.notna(row["termo_final"]) else None, key=f"{k_edit}_termo_final"
        )
        c6.text_input("Unidade gestora", value=_ou_vazio(row["unidade_gestora"]), key=f"{k_edit}_unidade_gestora")
        c7, c8 = st.columns(2)
        c7.number_input(
            "Valor mensal (R$)", value=_ou_zero(row["valor_mensal"]), step=100.0, key=f"{k_edit}_valor_mensal"
        )
        c8.number_input(
            "Valor anual (R$)", value=_ou_zero(row["valor_anual"]), step=1000.0, key=f"{k_edit}_valor_anual"
        )
        st.caption(f"Termo atual (histórico, não editável): {_ou_vazio(row['termo_atual']) or '—'}")

        st.markdown("**Pendências**")
        if row["alertas"]:
            st.write(", ".join(row["alertas"]))
        else:
            st.write("Nenhuma pendência encontrada no cadastro deste contrato.")

    with aba_linha:
        for _, t in grupo.sort_values("data_assinatura", ascending=False).iterrows():
            com_impacto = pd.notna(t["valor_termo"]) and t["valor_termo"] != 0
            st.markdown(
                f"**{_fmt_data(t['data_assinatura'])} · {_ou_vazio(t['termo']) or '—'} · {_ou_vazio(t.get('finalidade_termo')) or '—'}** "
                + _badge(
                    "Com impacto financeiro" if com_impacto else "Sem impacto financeiro",
                    ACCENT_STRONG if com_impacto else TEXT_MUTED,
                ),
                unsafe_allow_html=True,
            )
            if com_impacto:
                st.write(f"Valor do termo: {_brl(t['valor_termo'])} · Vigência até {_fmt_data(t['termo_final'])}")
            st.markdown("<hr style='margin:6px 0'>", unsafe_allow_html=True)

    with aba_fin:
        tabela = grupo[["termo", "data_assinatura", "termo_final", "valor_termo", "finalidade_termo"]].copy()
        tabela.columns = ["Ato", "Data assinatura", "Termo final", "Valor do termo (R$)", "Finalidade"]
        st.dataframe(tabela, hide_index=True, width="stretch")
        if len(grupo) < 2:
            st.caption("Histórico insuficiente para gráfico de evolução do valor mensal.")

    with aba_emp:
        st.info(
            "Este leitor não segrega empenhos por contrato — cruzar com a base de Contratos "
            "Contínuos (src/contratos_continuos.py, por número de contrato) detalharia "
            "rateio, saldo e necessidade de reforço por número de empenho, mas é uma "
            "integração nova, ainda não implementada nesta tela."
        )

    with aba_doc:
        st.markdown("**Documento**")
        st.write(_ou_vazio(row.get("arquivo_pdf")) or "Não informado")
        st.markdown("**Gestor**")
        c9, c10 = st.columns(2)
        c9.text_input("Gestor", value=_ou_vazio(row.get("gestor")), key=f"{k_edit}_gestor", label_visibility="collapsed")
        c10.text_input("E-mail do gestor", value=_ou_vazio(row.get("email_gestor")), key=f"{k_edit}_email_gestor", label_visibility="collapsed")
        st.markdown("**Garantia**")
        st.text_input("Situação da garantia", value=_ou_vazio(row.get("garantia_status")), key=f"{k_edit}_garantia_status", label_visibility="collapsed")

    with aba_aud:
        st.write(f"Linha de origem: {row.get('linha_origem_atual', '—')}")
        st.write("Importação a partir da planilha BASE_CONTRATOS (CONTRATOS UFRPE).")


def _render_comparacao_continuos(contratos: pd.DataFrame) -> None:
    """Quadro cruzando, por número de contrato, o valor mensal/anual desta base (Contratos —
    Vigência) contra o de Contratos Contínuos (`src/contratos_continuos.py`, despesa somada
    por contrato quando há mais de um item de licitação) — pedido explícito, para achar
    incoerências entre as duas planilhas mantidas manualmente e de forma independente.

    Explicação confirmada pelo usuário para a maior parte das divergências (não todas — ver
    nota abaixo): muitos contratos são suportados por mais de uma unidade da UFRPE, mas
    Contratos Contínuos só traz a parcela suportada pela Ação 20RK, não o valor contratual
    inteiro (que é o que aparece em Contratos — Vigência). Consistente com os dados: na
    extração de 15/08/2026, das 22 divergências mensais, 17 têm Vigência > Contínuos (a
    direção esperada quando Contínuos só cobre uma fatia) — as outras 5 vão na direção oposta
    e continuam sem explicação conhecida, por isso a divergência continua sinalizada para
    todo mundo, não só descartada como "esperada".
    """

    if not CAMINHO_CONTRATOS_CONTINUOS.exists():
        st.info(
            "A planilha de Contratos Contínuos não foi encontrada — a comparação de valores "
            "mensais/anuais depende dela."
        )
        return

    valores_continuos = _cached_valores_contratos_continuos(
        str(CAMINHO_CONTRATOS_CONTINUOS), CAMINHO_CONTRATOS_CONTINUOS.stat().st_mtime
    )
    cruzado = contratos.set_index("numero_contrato")[["contratado", "valor_mensal", "valor_anual"]].join(
        valores_continuos, how="inner"
    ).reset_index()
    if cruzado.empty:
        st.info("Nenhum número de contrato em comum entre as duas bases.")
        return

    cruzado["dif_mensal"] = cruzado["valor_mensal"] - cruzado["despesa_mensal_continuos"]
    cruzado["dif_anual"] = cruzado["valor_anual"] - cruzado["despesa_anual_continuos"]
    cruzado["_diverge"] = (cruzado["dif_mensal"].abs() > 0.01) | (cruzado["dif_anual"].abs() > 0.01)
    cruzado["_dif_anual_abs"] = cruzado["dif_anual"].abs()
    cruzado = cruzado.sort_values(["_diverge", "_dif_anual_abs"], ascending=[False, False])

    divergentes = int(cruzado["_diverge"].sum())
    maior_na_vigencia = int((cruzado["dif_mensal"] > 0.01).sum())
    st.caption(
        f"{len(cruzado)} contratos em comum entre as duas bases · {divergentes} com valor "
        "mensal e/ou anual divergente (diferença maior que R$ 0,01)"
    )
    st.caption(
        f"Motivo mais comum: contratos suportados por mais de uma unidade da UFRPE, onde "
        "Contratos Contínuos só traz a parcela da Ação 20RK, não o valor contratual inteiro "
        f"— {maior_na_vigencia} das {divergentes} divergências têm Vigência maior que "
        "Contínuos, consistente com essa explicação. As demais não têm explicação conhecida "
        "ainda."
    )

    larguras = [0.8, 1.6, 1, 1, 0.85, 1, 1, 0.85]
    with st.container(key="cv_comparacao"):
        header = st.columns(larguras)
        for col, label in zip(
            header,
            ["Contrato", "Contratado", "Mensal (Vigência)", "Mensal (Contínuos)", "Dif. mensal",
             "Anual (Vigência)", "Anual (Contínuos)", "Dif. anual"],
        ):
            col.markdown(f"<span class='ct-label'>{label}</span>", unsafe_allow_html=True)
        for _, linha in cruzado.iterrows():
            c = st.columns(larguras)
            c[0].markdown(f"**{linha['numero_contrato']}**")
            c[1].write(_ou_vazio(linha["contratado"]) or "—")
            c[2].write(_brl(linha["valor_mensal"]))
            c[3].write(_brl(linha["despesa_mensal_continuos"]))
            cor_mensal = NEGATIVE if abs(linha["dif_mensal"]) > 0.01 else POSITIVE
            c[4].markdown(_badge(_brl(linha["dif_mensal"]), cor_mensal), unsafe_allow_html=True)
            c[5].write(_brl(linha["valor_anual"]))
            c[6].write(_brl(linha["despesa_anual_continuos"]))
            cor_anual = NEGATIVE if abs(linha["dif_anual"]) > 0.01 else POSITIVE
            c[7].markdown(_badge(_brl(linha["dif_anual"]), cor_anual), unsafe_allow_html=True)


# ---------------------------------------------------------------------- página
render_page_header(
    "Contratos — Vigência",
    "Gestão de vigência, efeitos financeiros e reforço de empenho",
    "Contratos",
)
_inject_css()

if not CAMINHO_BASE.exists():
    st.info(
        f"A planilha de vigência de contratos não foi encontrada em '{CAMINHO_BASE}'. "
        "Copie a extração atual (aba BASE_CONTRATOS) para essa pasta antes de usar esta página."
    )
    st.stop()

mtime = CAMINHO_BASE.stat().st_mtime

col_titulo, col_status = st.columns([3, 1])
with col_status:
    idade_dias = (datetime.now() - datetime.fromtimestamp(mtime)).days
    st.markdown(
        f"<div style='text-align:right' class='ct-kicker'>Atualizado em "
        f"{datetime.fromtimestamp(mtime).strftime('%d/%m/%Y às %H:%M')}</div>",
        unsafe_allow_html=True,
    )
    if st.button("Atualizar dados", use_container_width=True):
        _cached_leitura.clear()
        st.rerun()

try:
    termos = _cached_leitura(str(CAMINHO_BASE), mtime)
except Exception as error:
    st.error(f"Não foi possível ler os dados: {error}")
    st.stop()

contratos = consolidar_por_contrato(termos)
# `_aplicar_edicoes_da_sessao` já calcula situacao/pendencias/conciliacao_status (usando o
# valor original quando não há edição na sessão, ou o valor editado quando há) — não precisa
# de um cálculo "inicial" separado antes dela.
contratos = _aplicar_edicoes_da_sessao(contratos)

# Prioridade de exibição pedida explicitamente: contratos que também aparecem em Contratos
# Contínuos primeiro, depois os demais, com os vencidos sempre por último — regardless de
# terem correspondência em Contratos Contínuos ou não. Opcional: sem a planilha de Contratos
# Contínuos, todo mundo cai no nível 1 (nem prioridade nem penalidade), só os vencidos
# continuam por último.
if CAMINHO_CONTRATOS_CONTINUOS.exists():
    numeros_continuos = _cached_numeros_contratos_continuos(
        str(CAMINHO_CONTRATOS_CONTINUOS), CAMINHO_CONTRATOS_CONTINUOS.stat().st_mtime
    )
else:
    numeros_continuos = set()
contratos["_prioridade_exibicao"] = 1
contratos.loc[contratos["numero_contrato"].isin(numeros_continuos), "_prioridade_exibicao"] = 0
contratos.loc[contratos["criticidade"] == "Vencido", "_prioridade_exibicao"] = 2

if idade_dias >= 2:
    st.markdown(
        f"<div class='ct-banner'>Os dados não são atualizados há {idade_dias} dias. "
        "Indicadores financeiros podem estar defasados.</div>",
        unsafe_allow_html=True,
    )

mostrar_todos = st.checkbox("Mostrar todos os contratos (incluindo encerrados e sem termo final)", key="cv_mostrar_todos")
contratos_base = contratos if mostrar_todos else contratos[contratos["situacao"] == "Vigente"]

st.markdown("#### Filtros")
fr1 = st.columns(4)
contrato_filtro = fr1[0].text_input("Contrato", key="cv_f_contrato", placeholder="Nº do contrato")
contratado_filtro = fr1[1].text_input("Contratado", key="cv_f_contratado", placeholder="Nome do contratado")

datas_validas = contratos["termo_final"].dropna()
if len(datas_validas):
    termino_min, termino_max = datas_validas.min(), datas_validas.max()
    termino_filtro = fr1[2].date_input(
        "Término", value=(), min_value=termino_min, max_value=termino_max, key="cv_f_termino", format="DD/MM/YYYY"
    )
else:
    termino_filtro = ()

dias_validos = contratos["dias_para_vencer"].dropna()
if len(dias_validos):
    dias_min, dias_max = int(dias_validos.min()), int(dias_validos.max())
    dias_filtro = fr1[3].slider("Dias", min_value=dias_min, max_value=dias_max, value=(dias_min, dias_max), key="cv_f_dias")
else:
    dias_filtro = (0, 0)

fr2 = st.columns(3)
_opcoes_criticidade = sorted(contratos["criticidade"].unique().tolist(), key=lambda c: _ORDEM_CRITICIDADE.get(c, 99))
criticidade_filtro = fr2[0].multiselect(
    "Criticidade",
    options=_opcoes_criticidade,
    key="cv_f_criticidade",
    placeholder="Todas",
)
valores_validos = contratos["valor_mensal"].dropna()
if len(valores_validos):
    valor_min, valor_max = float(valores_validos.min()), float(valores_validos.max())
    mensal_filtro = fr2[1].slider(
        "Mensal vigente", min_value=valor_min, max_value=valor_max, value=(valor_min, valor_max),
        format="R$ %.0f", key="cv_f_mensal",
    )
else:
    mensal_filtro = (0.0, 0.0)
conciliacao_filtro = fr2[2].selectbox("Pendências", ["Todas", "Com pendências", "Sem pendências"], key="cv_f_conciliacao")

filtrado = contratos_base
if contrato_filtro:
    filtrado = filtrado[filtrado["numero_contrato"].astype("string").str.contains(contrato_filtro, case=False, na=False)]
if contratado_filtro:
    filtrado = filtrado[filtrado["contratado"].astype("string").str.contains(contratado_filtro, case=False, na=False)]
if len(termino_filtro) == 2:
    inicio, fim = termino_filtro
    filtrado = filtrado[filtrado["termo_final"].between(inicio, fim) | filtrado["termo_final"].isna()]
filtrado = filtrado[filtrado["dias_para_vencer"].between(*dias_filtro) | filtrado["dias_para_vencer"].isna()]
if criticidade_filtro:
    filtrado = filtrado[filtrado["criticidade"].isin(criticidade_filtro)]
filtrado = filtrado[filtrado["valor_mensal"].between(*mensal_filtro) | filtrado["valor_mensal"].isna()]
if conciliacao_filtro != "Todas":
    filtrado = filtrado[filtrado["conciliacao_status"] == conciliacao_filtro]

k = st.columns(6)
k[0].metric("Contratos vigentes", int((contratos["situacao"] == "Vigente").sum()), f"de {len(contratos)} contratos")
k[1].metric("Vencem em até 30 dias", int(contratos["dias_para_vencer"].between(0, 30).sum()))
k[2].metric("Vencem em 31–120 dias", int(contratos["dias_para_vencer"].between(31, 120).sum()))
k[3].metric("Sem termo final", int((contratos["situacao"] == "Sem termo final").sum()))
projecao = contratos["valor_anual"].dropna().sum()
k[4].metric(f"Projeção do exercício · {date.today().year}", _brl(projecao), "Provisório")
k[5].metric("Com pendências", int((contratos["conciliacao_status"] == "Com pendências").sum()))

st.markdown("#### Vencimentos por faixa")
faixas = [
    ("Vencido", contratos["dias_para_vencer"] < 0, NEGATIVE),
    ("0–30 dias", contratos["dias_para_vencer"].between(0, 30), NEGATIVE),
    ("31–60 dias", contratos["dias_para_vencer"].between(31, 60), WARNING),
    ("61–120 dias", contratos["dias_para_vencer"].between(61, 120), WARNING),
    ("121–180 dias", contratos["dias_para_vencer"].between(121, 180), POSITIVE),
    ("Acima de 180 dias", contratos["dias_para_vencer"] > 180, POSITIVE),
    ("Sem termo final", contratos["termo_final"].isna(), TEXT_MUTED),
]
maxq = max(1, *[int(m.sum()) for _, m, _ in faixas])
for rotulo, mask, cor in faixas:
    qtd = int(mask.sum())
    cols = st.columns([2, 6, 1])
    cols[0].markdown(f"<span style='font-size:12px'>{rotulo}</span>", unsafe_allow_html=True)
    cols[1].progress(qtd / maxq if maxq else 0)
    cols[2].markdown(f"<span style='font-size:12px'>{qtd}</span>", unsafe_allow_html=True)

st.markdown("#### Contratos")
col_titulo_tabela, col_ordem = st.columns([3, 1])
with col_titulo_tabela:
    escopo = "todos os contratos" if mostrar_todos else "contratos vigentes"
    st.caption(f"{len(filtrado)} de {len(contratos_base)} {escopo} ({len(contratos)} no total)")
with col_ordem:
    ordem = st.selectbox("Ordenar", ORDENS_CONTRATOS, key="cv_ordem", label_visibility="collapsed")

#: `_prioridade_exibicao` (0 = também em Contratos Contínuos, 1 = demais, 2 = vencidos) é
#: sempre a chave de ordenação primária (pedido explícito) — o "Ordenar" escolhido só decide
#: a ordem dentro de cada um desses três grupos.
if ordem == "Contrato":
    ordenado = filtrado.sort_values(["_prioridade_exibicao", "numero_contrato"])
elif ordem == "Contratado":
    ordenado = filtrado.sort_values(["_prioridade_exibicao", "contratado"], na_position="last")
elif ordem == "Término mais próximo":
    ordenado = filtrado.sort_values(["_prioridade_exibicao", "termo_final"], na_position="last")
elif ordem == "Mais dias até vencer":
    ordenado = filtrado.sort_values(
        ["_prioridade_exibicao", "dias_para_vencer"], ascending=[True, False], na_position="last"
    )
elif ordem == "Criticidade (mais crítico primeiro)":
    ordenado = filtrado.assign(
        _ordem_criticidade=filtrado["criticidade"].map(_ORDEM_CRITICIDADE)
    ).sort_values(["_prioridade_exibicao", "_ordem_criticidade"])
elif ordem == "Maior valor mensal":
    ordenado = filtrado.sort_values(
        ["_prioridade_exibicao", "valor_mensal"], ascending=[True, False], na_position="last"
    )
else:
    ordenado = filtrado.sort_values(["_prioridade_exibicao", "pendencias_qtd"], ascending=[True, False])
ordenado = ordenado.reset_index(drop=True)

mostrar_qtd = st.session_state.get("cv_mostrar_qtd", QTD_INICIAL_LISTA)
if not isinstance(mostrar_qtd, int) or mostrar_qtd < QTD_INICIAL_LISTA:
    mostrar_qtd = QTD_INICIAL_LISTA
mostrar_qtd = min(mostrar_qtd, len(ordenado)) if len(ordenado) else QTD_INICIAL_LISTA
st.session_state["cv_mostrar_qtd"] = mostrar_qtd
visiveis = ordenado.iloc[:mostrar_qtd]

with st.container(key="cv_tabela"):
    header = st.columns([1.4, 2, 1.2, 1, 1, 1.2, 1.3, 0.6])
    for col, label in zip(header, ["Contrato", "Contratado", "Término", "Dias", "Criticidade", "Mensal vigente", "Pendências", ""]):
        col.markdown(f"<span class='ct-label'>{label}</span>", unsafe_allow_html=True)
    for _, row in visiveis.iterrows():
        cor = CRITICIDADE_COR.get(row["criticidade"], TEXT_MUTED)
        c = st.columns([1.4, 2, 1.2, 1, 1, 1.2, 1.3, 0.6])
        c[0].markdown(f"**{row['numero_contrato']}**")
        c[1].write(_ou_vazio(row["contratado"]) or "—")
        c[2].write(_fmt_data(row["termo_final"]))
        dias = row["dias_para_vencer"]
        c[3].write("—" if pd.isna(dias) else (f"Vencido há {abs(int(dias))}d" if dias < 0 else str(int(dias))))
        c[4].markdown(_badge(row["criticidade"], cor), unsafe_allow_html=True)
        c[5].write(_brl(row["valor_mensal"]))
        texto_pendencias = f"{row['pendencias_qtd']} pendência(s)" if row["pendencias_qtd"] else "Sem pendências"
        c[6].markdown(
            _badge(texto_pendencias, NEGATIVE if row["pendencias_qtd"] else POSITIVE),
            unsafe_allow_html=True,
        )
        if c[7].button("Ver", key=f"cv_det_{row['numero_contrato']}"):
            _abrir_detalhe(row["numero_contrato"], contratos, termos)
    if ordenado.empty:
        st.markdown("<div class='ct-kicker'>Nenhum contrato corresponde aos filtros selecionados.</div>", unsafe_allow_html=True)

if mostrar_qtd < len(ordenado):
    st.caption(f"Mostrando {mostrar_qtd} de {len(ordenado)} contratos")
    if st.button("Ver mais", key="cv_ver_mais"):
        st.session_state["cv_mostrar_qtd"] = min(mostrar_qtd + QTD_INCREMENTO_LISTA, len(ordenado))
        st.rerun()
elif len(ordenado):
    st.caption(f"Mostrando todos os {len(ordenado)} contratos")

st.markdown("#### Vigência × Contratos Contínuos")
_render_comparacao_continuos(contratos)
