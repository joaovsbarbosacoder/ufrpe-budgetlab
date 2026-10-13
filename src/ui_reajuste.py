"""
Página "Reajuste estimado" (11/10/2026; repaginada e movida para página própria em 12/10/2026).

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
from xml.sax.saxutils import escape

import pandas as pd
import streamlit as st

from src.contratos_aditivos import ROTULO_TIPO, Aditivo, aditivo_para_registro, aditivos_do_registro, validar_aditivos
from src.contratos_continuos_cadastro import atualizar_contrato
from src.estimativa_reajuste import (
    ParametrosReajuste,
    aditivo_previsto_do_ciclo,
    aditivos_sugeridos_dos_ciclos_formalizados,
    estimar_contrato,
    liquidado_do_contrato,
    nes_do_gov,
    nes_em_conflito,
    ultimo_mes_coberto,
)
from src.indices_economicos import INDICE_PADRAO, INDICES, ErroIndiceEconomico, variacoes_bcb
from src.ui_cadastro import formatar_brl
from src.ui_reajuste_visual import (
    CSS,
    ROTULO_ESTADO,
    ROTULO_ORIGEM_BASE,
    ROTULO_ORIGEM_PERCENTUAL,
    html_ciclos,
    html_a_registrar,
    html_destaque,
    html_grafico_mensal,
    html_mapa,
    html_ranking,
    html_tabela_competencias,
    html_tabela_resumo,
    reajustes_registrados,
)

ROTULO_SITUACAO = {
    "estimado": "Estimado",
    "sem_indice": "Sem percentual (índice indisponível)",
    "sem_data_base": "Sem data-base (informe o início ou a data)",
    "sem_vigencia_fim": "Sem fim de vigência",
    "sem_reajuste_na_vigencia": "Sem reajuste previsto na vigência",
}
_PADRAO = f"Padrão ({INDICE_PADRAO})"


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
        indice=INDICE_PADRAO if indice is None else str(indice).upper(),  # sem índice no cadastro: IPCA
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
    inicio_por_gov: dict[str, object], ano: int, hoje: date, vigencias_por_gov: dict[str, list] | None = None,
    empenhos_gov: pd.DataFrame | None = None,
) -> tuple[list[dict], list[str]]:
    """Uma estimativa por contrato (a primeira linha de cada `contrato_numero` no exercício) e os avisos de
    NE em conflito. O liquidado soma as NEs do contrato em todos os exercícios — as do cadastro e, do
    Contratos.gov, as de plano interno igual ao do cadastro (`nes_do_gov`) —, menos as NEs em conflito."""

    conflitos = nes_em_conflito(todos_registros)
    nes_por_contrato: dict[str, set[str]] = {}
    pis_por_contrato: dict[str, set[str]] = {}
    for registro in todos_registros:
        ne, contrato, pi = registro.get("ne_curta"), registro.get("contrato_numero"), registro.get("pi_cod")
        if not contrato:
            continue
        if ne and str(ne).strip() not in conflitos:
            nes_por_contrato.setdefault(str(contrato).strip(), set()).add(str(ne).strip())
        if pi and str(pi).strip():
            pis_por_contrato.setdefault(str(contrato).strip(), set()).add(str(pi).strip())

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
            retorno = _variacoes_oficiais(indice, ano - 5, hoje_iso)  # janelas de ciclos retroativos vão longe
            if isinstance(retorno, str):
                avisos.append(retorno)
                variacoes_por_indice[indice] = None
            else:
                variacoes_por_indice[indice] = retorno
        termos_gov = (vigencias_por_gov or {}).get(str(linha.get("contratosgov_id")), {})
        nes = nes_por_contrato.get(numero, set()) | {
            ne for ne in nes_do_gov(empenhos_gov, linha.get("contratosgov_id"), pis_por_contrato.get(numero, set()))
            if ne not in conflitos
        }
        estimativa = estimar_contrato(
            contrato=numero, despesa_mensal=linha.get("despesa_mensal"), aditivos=list(linha.get("aditivos") or []),
            vigencia_inicio=_inicio_da_vigencia(linha, inicio_por_gov), vigencia_fim=linha.get("vigencia_fim"),
            parametros=parametros, exercicio_inicial=ano, variacoes=variacoes_por_indice.get(indice) if indice else None,
            liquidado=liquidado_do_contrato(nes, liquidacao_por_mes),
            ultimo_mes_coberto=cobertura,
            reajustes_gov=termos_gov.get("reajustes"), retroativos=termos_gov.get("retroativos"),
            apostilamentos=termos_gov.get("apostilamentos"),
        )
        resultados.append({"linha": linha, "estimativa": estimativa, "parametros": parametros})
    return resultados, avisos


def _soma_ou_nulo(serie: pd.Series) -> float | None:
    total = serie.sum(skipna=True, min_count=1)
    return None if pd.isna(total) else float(total)


def _total_ou_traco(serie: pd.Series) -> str:
    """Total em R$; "—" quando nenhum contrato tem valor (nulo, nunca R$ 0,00)."""

    return _md(formatar_brl(serie.sum())) if serie.notna().any() else "—"


def _resumo(resultados: list[dict], ano: int, hoje: date) -> pd.DataFrame:
    linhas = []
    for item in resultados:
        linha, estimativa = item["linha"], item["estimativa"]
        matriz = estimativa.matriz
        vazio = matriz.empty
        do_ano = matriz if vazio else matriz[matriz["ano"] == ano]
        anteriores = matriz if vazio else matriz[matriz["exercicio_anterior"]]
        proxima = next((c for c in estimativa.ciclos if c.data_base >= hoje), None)
        ciclo = proxima or (estimativa.ciclos[-1] if estimativa.ciclos else None)
        a_confirmar = [c.data_base for c in estimativa.ciclos if c.estado == "formalizado"]
        retroativo_gov = [r.valor for r in estimativa.retroativos_exercicio if r.valor is not None]
        linhas.append({
            "Contrato": linha.get("contrato_numero"),
            "Fornecedor": linha.get("fornecedor"),
            "Situação": ROTULO_SITUACAO.get(estimativa.situacao, estimativa.situacao),
            "Data-base": None if ciclo is None else ciclo.data_base,
            "Estado do ciclo": None if ciclo is None else ROTULO_ESTADO.get(ciclo.estado, ciclo.estado),
            "Percentual (%)": None if ciclo is None or ciclo.percentual is None else round(ciclo.percentual, 4),
            "Origem do %": None if ciclo is None else ROTULO_ORIGEM_PERCENTUAL.get(ciclo.origem, ciclo.origem),
            # `min_count=1`: só NaN = sem estimativa (nulo), nunca R$ 0,00
            f"Formalizado a confirmar {ano}": None if do_ano.empty else _soma_ou_nulo(do_ano["acrescimo_formalizado"]),
            f"Projetado {ano}": None if do_ano.empty else _soma_ou_nulo(do_ano["acrescimo_projetado"]),
            f"Acréscimo {ano}": None if do_ano.empty else _soma_ou_nulo(do_ano["acrescimo"]),
            "Exercícios anteriores": None if anteriores.empty else _soma_ou_nulo(anteriores["acrescimo"]),
            "Acréscimo na vigência": None if vazio else _soma_ou_nulo(matriz["acrescimo"]),
            "Competências sem estimativa": 0 if vazio else int(matriz["acrescimo"].isna().sum()),
            "Ciclos a confirmar": ", ".join(f"{d:%d/%m/%Y}" for d in a_confirmar) or None,
            "Retroativo no gov (contrato inteiro)": sum(retroativo_gov) if retroativo_gov else None,
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
        "O índice oficial (padrão IPCA; também INPC ou IGP-M) sugere o percentual; o percentual manual, se "
        "informado, sobrescreve. A data-base manual substitui a calculada pelas últimas vigências."
    ))
    atual_indice = str(registro.get("reajuste_indice") or "").upper()
    opcoes = [_PADRAO, *INDICES]
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
        novo["reajuste_indice"] = None if indice == _PADRAO else indice
        novo["reajuste_percentual_manual"] = float(percentual) if usar_percentual else None
        novo["reajuste_data_base_manual"] = data_base.isoformat() if usar_data else None
        atualizar_contrato(ano, novo)
        st.rerun()


def _itens_do_ranking(resumo: pd.DataFrame, ano: int) -> list[dict]:
    """Uma linha do resumo por contrato, no formato de `html_ranking`."""

    itens = []
    for _, linha in resumo.iterrows():
        itens.append({
            "contrato": linha["Contrato"], "fornecedor": linha["Fornecedor"], "situacao": linha["Situação"],
            "estado": linha["Estado do ciclo"], "data_base": linha["Data-base"], "percentual": linha["Percentual (%)"],
            "origem": linha["Origem do %"], "formalizado": linha[f"Formalizado a confirmar {ano}"],
            "projetado": linha[f"Projetado {ano}"], "acrescimo": linha[f"Acréscimo {ano}"],
        })
    return itens


def _gravar_reajuste_formalizado(
    registro: dict, aditivos: list[Aditivo], sugerido: Aditivo, numero: str, valor: float | None, ano: int,
) -> str | None:
    """Grava o aditivo de Reajuste ASSINADO do ciclo `sugerido` com o `valor` informado e devolve `None`; ou devolve a
    mensagem de recusa (nada é gravado): valor vazio, outro aditivo na mesma data ou aditivos inválidos. O aditivo de
    Reajuste assinado SEM valor que já está na data é COMPLETADO (sem duplicar). Regra única dos dois formulários."""

    if valor is None:
        return "Informe o novo valor mensal do termo."
    existentes = [a for a in aditivos if a.data_inicio == sugerido.data_inicio]
    completavel = next(
        (a for a in existentes if a.tipo == "REAJUSTE" and a.situacao == "ASSINADO" and a.valor_mensal is None), None
    )
    if existentes and completavel is None:
        return "Já existe um aditivo com esta data de início: nada foi gravado."
    novo = Aditivo(
        numero=numero.strip(), tipo="REAJUSTE", situacao="ASSINADO", data_inicio=sugerido.data_inicio, valor_mensal=float(valor),
    )
    novos = [novo if a is completavel else a for a in aditivos] if completavel is not None else [*aditivos, novo]
    erros = validar_aditivos(aditivos_do_registro([aditivo_para_registro(a) for a in novos]))
    if erros:
        return _md(" ".join(erros))
    atualizado = dict(registro)
    atualizado["aditivos"] = [aditivo_para_registro(a) for a in novos]
    atualizar_contrato(ano, atualizado)
    return None


def _render_registro_formalizado(
    registro: dict, aditivos: list[Aditivo], sugeridos: list[Aditivo], ano: int, source_key: str,
) -> None:
    """Formulário "Registrar reajuste formalizado" do contrato aberto: para um ciclo assinado no gov que ainda não está no
    cadastro, grava o aditivo de Reajuste ASSINADO com o novo valor mensal. O valor vem SUGERIDO (valor em vigor × (1 +
    percentual)), mas só é gravado depois de conferido/editado e confirmado pelo botão."""

    base = f"rj_{source_key}_{registro.get('id')}_reg"
    st.markdown(
        '<div class="rj-titulo">Registrar reajuste formalizado</div><div class="rj-leg2">Reajuste já assinado no Contratos.gov '
        "e ainda sem valor no cadastro. Confira o valor sugerido (pelo índice) e ajuste ao do termo antes de registrar; só é "
        "gravado ao confirmar.</div>",
        unsafe_allow_html=True,
    )
    por_data = {sugerido.data_inicio.isoformat(): sugerido for sugerido in sugeridos}
    escolhida = st.selectbox(
        "Ciclo a registrar", list(por_data), format_func=lambda dia: f"{por_data[dia].data_inicio:%d/%m/%Y}", key=f"{base}_ciclo"
    )
    sugerido = por_data[escolhida]
    chave = f"{base}_{escolhida}"
    colunas = st.columns(2)
    numero = colunas[0].text_input("Nº do termo", value=sugerido.numero, key=f"{chave}_numero")
    valor = colunas[1].number_input(
        "Novo valor mensal (R$)", value=sugerido.valor_mensal, step=0.01, format="%.2f", key=f"{chave}_valor",
        help="Sugestão: valor em vigor × (1 + percentual do ciclo). Sem percentual ou sem valor em vigor, informe o do termo.",
    )
    if st.button("Registrar reajuste", key=f"{chave}_registrar"):
        erro = _gravar_reajuste_formalizado(registro, aditivos, sugerido, numero, valor, ano)
        if erro:
            st.error(erro)
        else:
            st.rerun()


def _bloqueados_por_outro_aditivo(resultados: list[dict], resumo: pd.DataFrame, ano: int) -> list[dict]:
    """Ciclos FORMALIZADOS cuja data já tem outro aditivo (que não é o Reajuste assinado sem valor — esse é completado): não
    se cria um segundo aditivo na mesma data. Entram no aviso do quadro com o formalizado a confirmar do contrato."""

    formalizado_por_contrato = dict(zip(resumo["Contrato"].astype(str), resumo[f"Formalizado a confirmar {ano}"]))
    bloqueados = []
    for item in resultados:
        linha, estimativa = item["linha"], item["estimativa"]
        aditivos = list(linha.get("aditivos") or [])
        propostas = {a.data_inicio for a in aditivos_sugeridos_dos_ciclos_formalizados(estimativa, aditivos, linha.get("despesa_mensal"))}
        for ciclo in estimativa.ciclos:
            if ciclo.estado != "formalizado" or ciclo.data_base in propostas:
                continue
            outro = next((a for a in aditivos if a.data_inicio == ciclo.data_base), None)
            if outro is None:
                continue
            bloqueados.append({
                "contrato": str(linha["contrato_numero"]), "fornecedor": linha.get("fornecedor"), "data": ciclo.data_base,
                "outro": f"{outro.numero} ({ROTULO_TIPO.get(outro.tipo, outro.tipo)})",
                "acrescimo": formalizado_por_contrato.get(str(linha["contrato_numero"])),
            })
    return bloqueados


def _pendentes_a_registrar(resultados: list[dict], registros: list[dict], resumo: pd.DataFrame, ano: int) -> list[dict]:
    """Os reajustes formalizados a registrar de TODOS os contratos do exercício (um item por ciclo), com o registro do
    cadastro, os aditivos atuais e o aditivo sugerido, prontos para o quadro e o formulário. Contrato sem registro no
    exercício (ou sem id) não entra: não há onde gravar."""

    formalizado_por_contrato = dict(zip(resumo["Contrato"].astype(str), resumo[f"Formalizado a confirmar {ano}"]))
    pendentes = []
    for item in resultados:
        linha, estimativa = item["linha"], item["estimativa"]
        registro = next((r for r in registros if str(r.get("id")) == str(linha.get("id"))), None)
        if registro is None:
            continue
        aditivos = list(linha.get("aditivos") or [])
        for sugerido in aditivos_sugeridos_dos_ciclos_formalizados(estimativa, aditivos, linha.get("despesa_mensal")):
            ciclo = next((c for c in estimativa.ciclos if c.data_base == sugerido.data_inicio), None)
            pendentes.append({
                "contrato": str(linha["contrato_numero"]), "fornecedor": linha.get("fornecedor"), "data": sugerido.data_inicio,
                "percentual": None if ciclo is None else ciclo.percentual,
                "origem": None if ciclo is None else ROTULO_ORIGEM_PERCENTUAL.get(ciclo.origem, ciclo.origem),
                "valor_sugerido": sugerido.valor_mensal, "acrescimo": formalizado_por_contrato.get(str(linha["contrato_numero"])),
                "registro": registro, "aditivos": aditivos, "sugerido": sugerido,
            })
    return pendentes


def _render_a_registrar(pendentes: list[dict], bloqueados: list[dict], ano: int, source_key: str) -> None:
    """Quadro "A registrar" + formulário para registrar um reajuste por vez (sem "registrar todos": cada valor é conferido)."""

    st.markdown(html_a_registrar(pendentes, ano, bloqueados), unsafe_allow_html=True)
    if not pendentes:
        return
    base = f"rj_{source_key}_lote"
    por_chave = {f"{p['contrato']}|{p['data'].isoformat()}": p for p in sorted(pendentes, key=lambda p: (p["contrato"], p["data"]))}
    escolhida = st.selectbox(
        "Reajuste a registrar", list(por_chave),
        format_func=lambda chave: f"{por_chave[chave]['contrato']} — {por_chave[chave]['data']:%d/%m/%Y}", key=f"{base}_item",
    )
    pendente = por_chave[escolhida]
    colunas = st.columns(2)
    numero = colunas[0].text_input("Nº do termo do reajuste", value=pendente["sugerido"].numero, key=f"{base}_{escolhida}_numero")
    valor = colunas[1].number_input(
        "Novo valor mensal do termo (R$)", value=pendente["valor_sugerido"], step=0.01, format="%.2f",
        key=f"{base}_{escolhida}_valor",
        help="Sugestão: valor em vigor × (1 + percentual do ciclo). Confira com o termo antes de registrar.",
    )
    if st.button("Registrar reajuste selecionado", key=f"{base}_{escolhida}_registrar"):
        erro = _gravar_reajuste_formalizado(
            pendente["registro"], pendente["aditivos"], pendente["sugerido"], numero, valor, ano
        )
        if erro:
            st.error(erro)
        else:
            st.rerun()


def _alternar_mais(chave: str) -> None:
    st.session_state[chave] = not st.session_state.get(chave, False)


LIMITE_RANKING = 8


def render_estimativa_reajuste(
    dataframe: pd.DataFrame, registros: list[dict], todos_registros: list[dict], ano: int,
    liquidacao_por_mes: pd.DataFrame | None, inicio_por_gov: dict[str, object], source_key: str,
    hoje: date | None = None, vigencias_por_gov: dict[str, list] | None = None,
    empenhos_gov: pd.DataFrame | None = None,
) -> None:
    """Conteúdo da página "Reajuste estimado" (repaginada em 12/10/2026): cartão de destaque, os contratos que mais pesam,
    mapa do ano e detalhe de um contrato — tudo calculado como antes (`_estimativas`), só a apresentação mudou.
    `registros` são os do exercício `ano` (o que se grava); `todos_registros` são os de todos os exercícios (liquidado e
    conflito de NE); `inicio_por_gov` mapeia `contratosgov_id` → início da vigência; `hoje` é a data de referência (padrão:
    hoje) — define o último mês de liquidação considerado apurado."""

    hoje = hoje or date.today()
    st.markdown(CSS, unsafe_allow_html=True)
    st.caption(_md(
        "Cenário separado: não altera Necessidade de Empenho, Projeção nem aditivos. O reajuste incide sobre o "
        "valor LIQUIDADO por competência; onde ainda não há liquidado apurado (meses futuros) a base é o valor "
        "contratado, marcado como teto. Competência já apurada sem lançamento fica vazia, nunca zero."
    ))
    resultados, avisos = _estimativas(
        dataframe, todos_registros, liquidacao_por_mes, inicio_por_gov, ano, hoje, vigencias_por_gov, empenhos_gov
    )
    for aviso in avisos:
        st.warning(_md(aviso))
    if not resultados:
        st.info("Nenhum contrato no exercício para estimar.")
        return

    resumo = _resumo(resultados, ano, hoje)
    matriz = _matriz_longa(resultados)
    # "sem estimativa" = situação desconhecida (falta índice, data-base ou fim de vigência); "sem reajuste previsto na
    # vigência" é uma resposta conhecida, não falta de dado
    desconhecidas = {ROTULO_SITUACAO[s] for s in ("sem_indice", "sem_data_base", "sem_vigencia_fim")}
    st.markdown(
        html_destaque(
            ano, _soma_ou_nulo(resumo[f"Formalizado a confirmar {ano}"]), _soma_ou_nulo(resumo[f"Projetado {ano}"]),
            _soma_ou_nulo(resumo["Exercícios anteriores"]), int(resumo["Situação"].isin(desconhecidas).sum()),
        ),
        unsafe_allow_html=True,
    )
    st.caption(_md(
        "Formalizado a confirmar = reajuste já assinado no Contratos.gov (ou aditivo sem valor) cujo valor ainda "
        "não está no cadastro: estimado pelo índice até você registrar o aditivo de Reajuste com o valor (aí sai "
        "daqui). Projetado = próximos aniversários. Exercícios anteriores = competências de anos passados "
        "alcançadas por reajuste formalizado com retroativo assinado neste exercício (fora do total do exercício). "
        "O retroativo do gov é do contrato inteiro: só referência, não comparável à parcela da 20RK."
    ))

    # ---- quem mais pesa
    itens = _itens_do_ranking(resumo, ano)
    chave_mais = f"rj_{source_key}_mais"
    mostrar_todos = st.session_state.get(chave_mais, False)
    st.markdown(
        f'<div class="rj-titulo">Quem mais pesa em {ano}</div>'
        '<div class="rj-leg2">Contratos ordenados pelo acréscimo estimado no exercício.</div>',
        unsafe_allow_html=True,
    )
    st.markdown(html_ranking(itens, None if mostrar_todos else LIMITE_RANKING), unsafe_allow_html=True)
    if len(itens) > LIMITE_RANKING:
        st.button(
            "Ver menos" if mostrar_todos else f"Ver mais ({len(itens)})", key=f"rj_{source_key}_btn_mais",
            on_click=_alternar_mais, args=(chave_mais,),
        )

    # ---- a registrar (reajustes formalizados de todos os contratos)
    _render_a_registrar(
        _pendentes_a_registrar(resultados, registros, resumo, ano),
        _bloqueados_por_outro_aditivo(resultados, resumo, ano), ano, source_key,
    )

    # ---- mapa do ano
    estimativas_por_contrato = {str(i["linha"]["contrato_numero"]): i["estimativa"] for i in resultados}
    escolhido = ano
    if not matriz.empty:
        anos = sorted(matriz["ano"].unique())
        escolhido = st.selectbox(
            "Exercício do mapa e do gráfico", anos, index=anos.index(ano) if ano in anos else 0, key=f"rj_{source_key}_ano"
        )
        pivot = matriz[matriz["ano"] == escolhido].pivot_table(
            index="contrato", columns="mes", values="acrescimo", aggfunc="sum", dropna=False
        )
        bases = {
            numero: {c.data_base.month for c in est.ciclos if c.data_base.year == escolhido}
            for numero, est in estimativas_por_contrato.items()
        }
    else:
        pivot, bases = pd.DataFrame(), {}
    st.markdown(
        f'<div class="rj-titulo">Mapa de {escolhido}</div><div class="rj-leg2">Acréscimo estimado por competência. Quanto mais '
        "forte a cor, maior o valor; o contorno laranja marca o mês da data-base; traço = sem estimativa.</div>",
        unsafe_allow_html=True,
    )
    credores = {str(i["linha"]["contrato_numero"]): i["linha"].get("fornecedor") for i in resultados}
    st.markdown(html_mapa(pivot, escolhido, bases, credores), unsafe_allow_html=True)

    # ---- detalhe de um contrato
    rotulos = {
        str(i["linha"]["contrato_numero"]): f"{i['linha']['contrato_numero']} — {i['linha'].get('fornecedor') or 'sem credor'}"
        for i in resultados
    }
    escolhido_contrato = st.selectbox(
        "Detalhar contrato", list(rotulos), format_func=lambda numero: rotulos[numero], key=f"rj_{source_key}_contrato"
    )
    item = next(i for i in resultados if str(i["linha"]["contrato_numero"]) == escolhido_contrato)
    estimativa = item["estimativa"]
    st.markdown(
        f'<div class="rj-titulo">{escape(rotulos[escolhido_contrato])}</div>'
        f'<div class="rj-leg2">{escape(ROTULO_SITUACAO.get(estimativa.situacao, estimativa.situacao))}. Ciclos de reajuste e o '
        "efeito mês a mês: a base é o liquidado por competência; nos meses futuros, o valor contratado (teto).</div>"
        + html_ciclos(estimativa.ciclos, reajustes_registrados(list(item["linha"].get("aditivos") or [])))
        + html_grafico_mensal(estimativa.matriz, escolhido),
        unsafe_allow_html=True,
    )
    retroativo = resumo.set_index("Contrato").loc[item["linha"]["contrato_numero"], "Retroativo no gov (contrato inteiro)"]
    if not pd.isna(retroativo):
        st.markdown(
            f'<div class="rj-nota">Retroativo no gov (contrato inteiro): {formatar_brl(retroativo)} — só referência, não '
            "comparável à parcela da 20RK.</div>",
            unsafe_allow_html=True,
        )
    if not estimativa.matriz.empty:
        with st.expander("Ver tabela detalhada das competências", expanded=False):
            st.markdown(html_tabela_competencias(estimativa.matriz), unsafe_allow_html=True)

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

    sugeridos = aditivos_sugeridos_dos_ciclos_formalizados(estimativa, aditivos, item["linha"].get("despesa_mensal"))
    if registro is not None and sugeridos:
        _render_registro_formalizado(registro, aditivos, sugeridos, ano, source_key)

    # ---- tabela completa (todas as colunas, para conferir os números)
    with st.expander("Tabela completa por contrato", expanded=False):
        st.markdown(html_tabela_resumo(resumo, ano), unsafe_allow_html=True)
    st.download_button(
        "Baixar estimativa (Excel)", _excel(resumo, matriz), file_name=f"estimativa_reajuste_{ano}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"rj_{source_key}_excel",
    )
