"""Aba "Aditivos" da janela de edição de Contratos Contínuos (06/10/2026).

Camada: interface (Streamlit). Fica em módulo próprio, e não na página, para poder ser testada com o
`AppTest` fora do `st.dialog` (que só executa a abertura da janela). A regra de negócio mora em
`src/contratos_aditivos.py`; aqui só se monta o formulário e se devolve a lista de aditivos digitada.
"""

from __future__ import annotations

from datetime import date

import streamlit as st
from streamlit.errors import StreamlitAPIException

from src.contratos_aditivos import (
    ROTULO_SITUACAO,
    ROTULO_TIPO,
    SITUACOES,
    TIPOS,
    Aditivo,
    aditivo_para_registro,
    aditivos_do_registro,
)

def _data_do_cartao(valor: object) -> date | None:
    """Data guardada no cartão de aditivo (texto ISO, `date` ou nulo) -> `date` do `st.date_input`."""

    if valor is None or valor == "":
        return None
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])


def _recarregar() -> None:
    """Recarrega só o fragmento (a janela `st.dialog` é um fragmento: um `st.rerun()` completo a fecharia).
    Em rerun completo — o `AppTest` roda o script inteiro — `scope="fragment"` não é aceito; cai no rerun
    comum, que é inofensivo fora da janela."""

    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()


#: nome público de `_recarregar`, para o chamador de `acrescentar_aditivo` (a página).
recarregar_fragmento = _recarregar


def _iniciar_estado(k: str, aditivos: list[Aditivo]) -> str:
    """Cria, uma vez, a lista de cartões da aba em `st.session_state[f"{k}_aditivos"]` a partir do registro
    (cada cartão com `_uid` = posição; `..._prox` = próximo `_uid` livre). Devolve a chave da lista."""

    chave = f"{k}_aditivos"
    if chave not in st.session_state:
        st.session_state[chave] = [{**aditivo_para_registro(a), "_uid": posicao} for posicao, a in enumerate(aditivos)]
        st.session_state[f"{chave}_prox"] = len(st.session_state[chave])
    return chave


def acrescentar_aditivo(k: str, aditivos_atuais: list[Aditivo], novo: Aditivo) -> None:
    """Põe um aditivo (ex.: o sugerido a partir de um termo do Contratos.gov) na lista da aba Aditivos,
    depois dos que já estão lá. Só mexe em `st.session_state` — NADA é gravado: o aditivo só vira parte do
    cadastro quando o usuário clica "Salvar" na janela de edição, e continua editável até lá. Inicializa a
    lista a partir de `aditivos_atuais` se a aba ainda não foi aberta. O chamador recarrega o fragmento."""

    chave = _iniciar_estado(k, aditivos_atuais)
    uid = st.session_state[f"{chave}_prox"]
    st.session_state[chave].append({**aditivo_para_registro(novo), "_uid": uid})
    st.session_state[f"{chave}_prox"] = uid + 1


def render_aba_aditivos(k: str, aditivos: list[Aditivo], itens_base: object) -> list[Aditivo]:
    """Aba "Aditivos" da janela de edição (06/10/2026): um cartão por aditivo (nº, tipo, situação, início,
    assinatura, novo valor mensal, nova vigência e, opcionalmente, novo rateio dos itens), em ordem de
    cadastro. A lista vive em `st.session_state[f"{k}_aditivos"]` (cada cartão com um `_uid` estável,
    chave dos widgets — assim remover um cartão não desloca o estado dos outros), inicializada uma vez a
    partir do registro e só gravada ao clicar "Salvar". Campo vazio = "mantém o anterior" (nulo, nunca
    zero). Devolve os aditivos conforme digitados, para os indicadores ao vivo e a validação ao salvar.
    Sem `st.data_editor` (quebra dentro de `st.dialog`); adicionar/remover recarrega só o fragmento."""

    chave = _iniciar_estado(k, aditivos)
    cartoes = st.session_state[chave]
    itens_base = itens_base if isinstance(itens_base, list) and itens_base else [{"numero": 1, "percentual": 100.0}]

    if not cartoes:
        st.caption("Nenhum aditivo cadastrado. Cada aditivo vale a partir da data de início; campo vazio mantém o valor anterior.")
    for cartao in list(cartoes):
        kk = f"{chave}_{cartao['_uid']}"
        with st.container(border=True):
            c_num, c_tipo, c_sit, c_ini, c_ass = st.columns([1, 1.3, 1.1, 1.2, 1.2])
            cartao["numero"] = c_num.text_input("Nº do termo", value=cartao.get("numero") or "", key=f"{kk}_numero")
            cartao["tipo"] = c_tipo.selectbox(
                "Tipo", list(TIPOS), index=TIPOS.index(cartao["tipo"]) if cartao.get("tipo") in TIPOS else 0,
                format_func=ROTULO_TIPO.get, key=f"{kk}_tipo",
            )
            cartao["situacao"] = c_sit.selectbox(
                "Situação", list(SITUACOES), index=SITUACOES.index(cartao["situacao"]) if cartao.get("situacao") in SITUACOES else 0,
                format_func=ROTULO_SITUACAO.get, key=f"{kk}_situacao",
                help="Previsto = valor estimado, ainda não assinado: entra nas contas, destacado nos relatórios.",
            )
            cartao["data_inicio"] = c_ini.date_input(
                "Início", value=_data_do_cartao(cartao.get("data_inicio")), format="DD/MM/YYYY",
                min_value=date(2000, 1, 1), max_value=date(2100, 12, 31), key=f"{kk}_inicio",
                help="A partir de quando o aditivo vale. Pode ser uma data passada (retroativo).",
            )
            cartao["data_assinatura"] = c_ass.date_input(
                "Assinatura", value=_data_do_cartao(cartao.get("data_assinatura")), format="DD/MM/YYYY",
                min_value=date(2000, 1, 1), max_value=date(2100, 12, 31), key=f"{kk}_assinatura",
                help="Opcional. Define o retroativo: reajuste assinado depois do início gera diferença nos meses já realizados.",
            )
            c_val, c_vig, c_rat = st.columns([1.2, 1.2, 1.6], vertical_alignment="bottom")
            cartao["valor_mensal"] = c_val.number_input(
                "Novo valor mensal (R$)", value=cartao.get("valor_mensal"), step=100.0, format="%.2f", key=f"{kk}_valor",
                placeholder="mantém o anterior",
            )
            if cartao["valor_mensal"] is not None and cartao["valor_mensal"] < 0:
                c_val.caption(":red[valor negativo]")
            cartao["vigencia_fim"] = c_vig.date_input(
                "Nova vigência (fim)", value=_data_do_cartao(cartao.get("vigencia_fim")), format="DD/MM/YYYY",
                min_value=date(2000, 1, 1), max_value=date(2100, 12, 31), key=f"{kk}_vigencia",
            )
            altera_rateio = c_rat.checkbox("Alterar rateio dos itens", value=cartao.get("itens") is not None, key=f"{kk}_altera_rateio")
            if altera_rateio:
                atuais = {int(i["numero"]): float(i["percentual"]) for i in (cartao.get("itens") or itens_base)}
                colunas_itens = st.columns(max(len(itens_base), 1))
                novos_itens = []
                for coluna, item in zip(colunas_itens, itens_base):
                    numero_item = int(item["numero"])
                    percentual = coluna.number_input(
                        f"Item {numero_item} (%)", value=atuais.get(numero_item, float(item["percentual"])),
                        min_value=0.0, max_value=100.0, step=1.0, key=f"{kk}_rateio_{numero_item}",
                    )
                    novos_itens.append({"numero": numero_item, "percentual": float(percentual)})
                cartao["itens"] = novos_itens
            else:
                cartao["itens"] = None
            if st.button("Remover aditivo", key=f"{kk}_rem", icon=":material/close:"):
                cartoes.remove(cartao)
                _recarregar()
    if st.button("Adicionar aditivo", key=f"{k}_adt_add", icon=":material/add:"):
        cartoes.append({
            "_uid": st.session_state[f"{chave}_prox"], "numero": "", "tipo": "REAJUSTE", "situacao": "ASSINADO",
            "data_inicio": None, "data_assinatura": None, "valor_mensal": None, "vigencia_fim": None, "itens": None,
        })
        st.session_state[f"{chave}_prox"] += 1
        _recarregar()
    return aditivos_do_registro([{chave_: valor for chave_, valor in cartao.items() if chave_ != "_uid"} for cartao in cartoes])
