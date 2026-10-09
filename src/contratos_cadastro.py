"""
Tabelas derivadas do cadastro de contratos (fotografia do Contratos.gov.br -> DataFrames).

Camada: regra específica da base Contratos.gov.br (não é cliente HTTP, não é extração/gravação,
não é interface). Funções puras, sem I/O: recebem a fotografia já carregada (dict) e devolvem
DataFrames. Depende só de pandas/decimal. Não importa Streamlit.

Origem: fotografia JSON da spec §5 (`{"versao_formato": 1, "consultado_em", "ug", "lista_ativos",
"lista_inativos", "detalhes": {"<id>": {"historico", "empenhos", "consultado_em", "origem"}}}`),
com as respostas da API guardadas sem transformação por `src/contratosgov_extracao.py`.
Nada aqui altera a fotografia (as tabelas são estruturas derivadas, em memória).

Decisões:
- `situacao` da API NÃO é confiável (instrumentos "Ativo" com vigência vencida): é guardada
  como `situacao_api`; a situação real é calculada pelas datas e por uma data de referência
  passada como parâmetro (testes determinísticos).
- Nenhuma regra de derivação do valor mensal é presumida (`valor_parcela` vem como está).
- Códigos (id, número, UG, gestão, NE, fonte, natureza, CNPJ/CPF) são sempre texto, com zeros
  iniciais preservados; `fornecedor_documento` guarda só os dígitos.
- Valores monetários: texto brasileiro ("830.906,44") -> Decimal (colunas dtype object).
  Vazio/None -> nulo; zero e negativo preservados; formato fora do padrão -> erro.
- `qualificacao_termo` vem da API como lista de {codigo, descricao} (achado da fixture de
  08/10/2026, não previsto na spec): guardado como texto "descricao1; descricao2".
- `retroativo` vem da API como "Sim"/"Não" e é convertido em bool; qualquer outro texto é erro.
  `retroativo_periodo` ("MM/AAAA–MM/AAAA") só existe quando os quatro campos de referência
  estão presentes; período parcial fica nulo (o dado bruto permanece na fotografia).
- Erros de dado levantam `ErroDadoContratosGov` citando contrato_id, endpoint e campo.
  Campo obrigatório = chave presente (valor null é aceito e vira nulo): na lista `id, numero,
  tipo, fornecedor, vigencia_inicio, vigencia_fim, valor_global`; em /empenhos `numero,
  unidade_gestora, gestao`; em /historico `id, tipo, data_assinatura`.
- Mesmo `id` repetido nas listas (ou nas duas) é erro, não duplicata silenciosa.
- Ordem: contratos = ativos, depois inativos (ordem da API); termos por `data_assinatura` e
  `termo_id` numérico; empenhos na ordem da API dentro de cada contrato.

Contrato público:
    class ErroDadoContratosGov(ValueError)
    valor_brl(texto, *, contrato_id, endpoint, campo) -> Decimal | None
    data_iso(texto, *, contrato_id, endpoint, campo) -> date | None
    situacao_vigencia(inicio, fim, inativo, referencia) -> str  (ver SITUACOES)
    montar_contratos(fotografia, referencia) -> pd.DataFrame
    montar_termos(fotografia) -> pd.DataFrame
    montar_empenhos(fotografia) -> pd.DataFrame
    resumo(contratos) -> dict
    SITUACOES
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pandas as pd

SITUACOES = ("vigente", "a_iniciar", "encerrado", "inativo", "sem_vigencia")

_RE_VALOR = re.compile(r"^-?(\d{1,3}(\.\d{3})*|\d+),\d{2}$")
_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_NUMERO = re.compile(r"^\d{5}/(\d{4})$")

_OBRIGATORIOS_LISTA = ("id", "numero", "tipo", "fornecedor", "vigencia_inicio", "vigencia_fim", "valor_global")
_OBRIGATORIOS_EMPENHO = ("numero", "unidade_gestora", "gestao")
_OBRIGATORIOS_TERMO = ("id", "tipo", "data_assinatura")

COLUNAS_CONTRATOS = [
    "contrato_id", "numero", "ano_contrato", "fornecedor_tipo", "fornecedor_documento",
    "fornecedor_nome", "processo", "objeto", "categoria", "modalidade", "data_assinatura",
    "vigencia_inicio", "vigencia_fim", "valor_inicial", "valor_global", "num_parcelas",
    "valor_parcela", "valor_acumulado", "situacao_api", "inativo_api", "situacao_vigencia",
    "dias_para_vencer", "qtd_termos", "qtd_empenhos", "detalhe_consultado_em", "detalhe_origem",
]
COLUNAS_TERMOS = [
    "contrato_id", "termo_id", "tipo", "numero", "qualificacao_termo", "data_assinatura",
    "vigencia_inicio", "vigencia_fim", "valor_global", "novo_valor_global", "novo_num_parcelas",
    "novo_valor_parcela", "data_inicio_novo_valor", "retroativo", "retroativo_valor",
    "retroativo_periodo", "observacao",
]
COLUNAS_EMPENHOS = [
    "contrato_id", "empenho_id", "ne_ccor", "ne", "ug", "gestao", "data_emissao", "fonte_recurso",
    "plano_interno", "natureza_despesa", "empenhado", "a_liquidar", "liquidado", "pago",
    "rp_inscrito", "rp_a_liquidar", "rp_liquidado", "rp_pago",
]
_MONETARIAS_CONTRATOS = ("valor_inicial", "valor_global", "valor_parcela", "valor_acumulado")
_MONETARIAS_TERMOS = ("valor_global", "novo_valor_global", "novo_valor_parcela", "retroativo_valor")
_MONETARIAS_EMPENHOS = (
    "empenhado", "a_liquidar", "liquidado", "pago", "rp_inscrito", "rp_a_liquidar",
    "rp_liquidado", "rp_pago",
)


class ErroDadoContratosGov(ValueError):
    """Dado da fotografia fora do formato esperado (cita contrato, endpoint e campo)."""


def _erro(contrato_id, endpoint, campo, detalhe) -> ErroDadoContratosGov:
    return ErroDadoContratosGov(
        f"Contrato {contrato_id} ({endpoint}), campo '{campo}': {detalhe}"
    )


def valor_brl(texto, *, contrato_id: str, endpoint: str, campo: str) -> Decimal | None:
    """Converte "830.906,44" em Decimal. None/"" -> None; zero e negativo preservados."""
    if texto is None or texto == "":
        return None
    if not isinstance(texto, str) or not _RE_VALOR.match(texto):
        raise _erro(contrato_id, endpoint, campo, f"valor monetário inválido: {texto!r}")
    return Decimal(texto.replace(".", "").replace(",", "."))


def data_iso(texto, *, contrato_id: str, endpoint: str, campo: str) -> date | None:
    """Converte "AAAA-MM-DD" em date. None/"" -> None."""
    if texto is None or texto == "":
        return None
    if not isinstance(texto, str) or not _RE_DATA.match(texto):
        raise _erro(contrato_id, endpoint, campo, f"data inválida (esperado AAAA-MM-DD): {texto!r}")
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise _erro(contrato_id, endpoint, campo, f"data inválida: {texto!r}") from None


def situacao_vigencia(inicio: date | None, fim: date | None, inativo: bool, referencia: date) -> str:
    """Precedência: inativo > sem_vigencia > a_iniciar > encerrado > vigente."""
    if inativo:
        return "inativo"
    if inicio is None or fim is None:
        return "sem_vigencia"
    if referencia < inicio:
        return "a_iniciar"
    if fim < referencia:
        return "encerrado"
    return "vigente"


def _exigir(item, chaves, contrato_id, endpoint):
    if not isinstance(item, dict):
        raise _erro(contrato_id, endpoint, "(item)", "esperado objeto JSON")
    for chave in chaves:
        if chave not in item:
            raise _erro(contrato_id, endpoint, chave, "campo obrigatório ausente")


def _texto(valor, contrato_id, endpoint, campo) -> str | None:
    """Código/texto: None/"" -> None; números viram str (sem perder dígitos); demais tipos erro."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool) or not isinstance(valor, (str, int)):
        raise _erro(contrato_id, endpoint, campo, f"esperado texto, veio {valor!r}")
    return str(valor)


def _inteiro(valor, contrato_id, endpoint, campo) -> int | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        raise _erro(contrato_id, endpoint, campo, f"inteiro inválido: {valor!r}")
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str) and valor.strip().isdigit():
        return int(valor.strip())
    raise _erro(contrato_id, endpoint, campo, f"inteiro inválido: {valor!r}")


def _ids_dos_contratos(fotografia: dict) -> list[tuple[dict, bool, str]]:
    """(item, inativo_api, endpoint) na ordem ativos -> inativos; erro em id repetido."""
    ug = fotografia.get("ug")
    pares = [
        (fotografia.get("lista_ativos") or [], False, f"/api/contrato/ug/{ug}"),
        (fotografia.get("lista_inativos") or [], True, f"/api/contrato/inativo/ug/{ug}"),
    ]
    vistos: dict[str, str] = {}
    saida = []
    for itens, inativo, endpoint in pares:
        for item in itens:
            _exigir(item, ("id",), "?", endpoint)
            cid = str(item["id"])
            _exigir(item, _OBRIGATORIOS_LISTA, cid, endpoint)
            if cid in vistos:
                raise _erro(cid, endpoint, "id", f"id repetido (também em {vistos[cid]})")
            vistos[cid] = endpoint
            saida.append((item, inativo, endpoint))
    return saida


def _detalhe(fotografia: dict, cid: str) -> dict:
    detalhes = fotografia.get("detalhes") or {}
    if cid not in detalhes:
        raise _erro(cid, "detalhes", "detalhes", "contrato sem detalhe na fotografia")
    return detalhes[cid]


def _df(linhas, colunas, monetarias) -> pd.DataFrame:
    df = pd.DataFrame(linhas, columns=colunas)
    for col in monetarias:
        df[col] = df[col].astype(object)
    return df


def montar_contratos(fotografia: dict, referencia: date) -> pd.DataFrame:
    linhas = []
    for item, inativo, endpoint in _ids_dos_contratos(fotografia):
        cid = str(item["id"])
        det = _detalhe(fotografia, cid)

        def d(campo):
            return data_iso(item.get(campo), contrato_id=cid, endpoint=endpoint, campo=campo)

        def v(campo):
            return valor_brl(item.get(campo), contrato_id=cid, endpoint=endpoint, campo=campo)

        def t(campo):
            return _texto(item.get(campo), cid, endpoint, campo)

        forn = item["fornecedor"]
        if forn is not None and not isinstance(forn, dict):
            raise _erro(cid, endpoint, "fornecedor", "esperado objeto JSON")
        forn = forn or {}
        doc = _texto(forn.get("cnpj_cpf_idgener"), cid, endpoint, "fornecedor.cnpj_cpf_idgener")
        doc = re.sub(r"\D", "", doc) if doc else None
        numero = _texto(item["numero"], cid, endpoint, "numero")
        m = _RE_NUMERO.match(numero or "")
        ini, fim = d("vigencia_inicio"), d("vigencia_fim")
        linhas.append({
            "contrato_id": cid,
            "numero": numero,
            "ano_contrato": int(m.group(1)) if m else None,
            "fornecedor_tipo": _texto(forn.get("tipo"), cid, endpoint, "fornecedor.tipo"),
            "fornecedor_documento": doc or None,
            "fornecedor_nome": _texto(forn.get("nome"), cid, endpoint, "fornecedor.nome"),
            "processo": t("processo"),
            "objeto": t("objeto"),
            "categoria": t("categoria"),
            "modalidade": t("modalidade"),
            "data_assinatura": d("data_assinatura"),
            "vigencia_inicio": ini,
            "vigencia_fim": fim,
            "valor_inicial": v("valor_inicial"),
            "valor_global": v("valor_global"),
            "num_parcelas": _inteiro(item.get("num_parcelas"), cid, endpoint, "num_parcelas"),
            "valor_parcela": v("valor_parcela"),
            "valor_acumulado": v("valor_acumulado"),
            "situacao_api": t("situacao"),
            "inativo_api": inativo,
            "situacao_vigencia": situacao_vigencia(ini, fim, inativo, referencia),
            "dias_para_vencer": (fim - referencia).days if fim is not None else None,
            "qtd_termos": len(det.get("historico") or []),
            "qtd_empenhos": len(det.get("empenhos") or []),
            "detalhe_consultado_em": det.get("consultado_em"),
            "detalhe_origem": det.get("origem"),
        })
    df = _df(linhas, COLUNAS_CONTRATOS, _MONETARIAS_CONTRATOS)
    for col in ("ano_contrato", "num_parcelas", "dias_para_vencer"):
        df[col] = df[col].astype("Int64")
    df["inativo_api"] = df["inativo_api"].astype(object)  # bool nativo do Python
    return df


def _retroativo(valor, cid, endpoint) -> bool | None:
    if valor is None or valor == "":
        return None
    if valor == "Sim":
        return True
    if valor == "Não":
        return False
    raise _erro(cid, endpoint, "retroativo", f"esperado 'Sim' ou 'Não', veio {valor!r}")


def _qualificacao(valor, cid, endpoint) -> str | None:
    """A API devolve uma lista de {codigo, descricao}; vira texto "desc1; desc2" (ordem da API)."""
    if valor is None or valor == "" or valor == []:
        return None
    if isinstance(valor, str):
        return valor
    if isinstance(valor, list):
        descricoes = []
        for q in valor:
            if not isinstance(q, dict) or not isinstance(q.get("descricao"), str):
                raise _erro(cid, endpoint, "qualificacao_termo", f"item sem 'descricao': {q!r}")
            descricoes.append(q["descricao"])
        return "; ".join(descricoes)
    raise _erro(cid, endpoint, "qualificacao_termo", f"formato inesperado: {valor!r}")


def _periodo(h, cid, endpoint) -> str | None:
    partes = [
        _texto(h.get(c), cid, endpoint, c)
        for c in ("retroativo_mesref_de", "retroativo_anoref_de", "retroativo_mesref_ate", "retroativo_anoref_ate")
    ]
    if any(p is None for p in partes):
        return None
    mes_de, ano_de, mes_ate, ano_ate = partes
    return f"{mes_de}/{ano_de}–{mes_ate}/{ano_ate}"


def montar_termos(fotografia: dict) -> pd.DataFrame:
    linhas = []
    for item, _, _ in _ids_dos_contratos(fotografia):
        cid = str(item["id"])
        endpoint = f"/api/contrato/{cid}/historico"
        for h in _detalhe(fotografia, cid).get("historico") or []:
            _exigir(h, _OBRIGATORIOS_TERMO, cid, endpoint)

            def d(campo):
                return data_iso(h.get(campo), contrato_id=cid, endpoint=endpoint, campo=campo)

            def v(campo):
                return valor_brl(h.get(campo), contrato_id=cid, endpoint=endpoint, campo=campo)

            linhas.append({
                "contrato_id": cid,
                "termo_id": _texto(h["id"], cid, endpoint, "id"),
                "tipo": _texto(h["tipo"], cid, endpoint, "tipo"),
                "numero": _texto(h.get("numero"), cid, endpoint, "numero"),
                "qualificacao_termo": _qualificacao(h.get("qualificacao_termo"), cid, endpoint),
                "data_assinatura": d("data_assinatura"),
                "vigencia_inicio": d("vigencia_inicio"),
                "vigencia_fim": d("vigencia_fim"),
                "valor_global": v("valor_global"),
                "novo_valor_global": v("novo_valor_global"),
                "novo_num_parcelas": _inteiro(h.get("novo_num_parcelas"), cid, endpoint, "novo_num_parcelas"),
                "novo_valor_parcela": v("novo_valor_parcela"),
                "data_inicio_novo_valor": d("data_inicio_novo_valor"),
                "retroativo": _retroativo(h.get("retroativo"), cid, endpoint),
                "retroativo_valor": v("retroativo_valor"),
                "retroativo_periodo": _periodo(h, cid, endpoint),
                "observacao": _texto(h.get("observacao"), cid, endpoint, "observacao"),
            })
    df = _df(linhas, COLUNAS_TERMOS, _MONETARIAS_TERMOS)
    df["novo_num_parcelas"] = df["novo_num_parcelas"].astype("Int64")
    df["retroativo"] = df["retroativo"].astype(object)  # True/False/None nativos
    df["_id_num"] = pd.to_numeric(df["termo_id"], errors="coerce")
    df = df.sort_values(["contrato_id", "data_assinatura", "_id_num"], kind="stable", na_position="last")
    return df.drop(columns="_id_num").reset_index(drop=True)


def montar_empenhos(fotografia: dict) -> pd.DataFrame:
    linhas = []
    for item, _, _ in _ids_dos_contratos(fotografia):
        cid = str(item["id"])
        endpoint = f"/api/contrato/{cid}/empenhos"
        for e in _detalhe(fotografia, cid).get("empenhos") or []:
            _exigir(e, _OBRIGATORIOS_EMPENHO, cid, endpoint)
            ne = _texto(e["numero"], cid, endpoint, "numero")
            ug = _texto(e["unidade_gestora"], cid, endpoint, "unidade_gestora")
            gestao = _texto(e["gestao"], cid, endpoint, "gestao")
            for campo, valor in (("numero", ne), ("unidade_gestora", ug), ("gestao", gestao)):
                if valor is None:
                    raise _erro(cid, endpoint, campo, "valor obrigatório vazio")

            def v(campo):
                return valor_brl(e.get(campo), contrato_id=cid, endpoint=endpoint, campo=campo)

            linhas.append({
                "contrato_id": cid,
                "empenho_id": _texto(e.get("id"), cid, endpoint, "id"),
                "ne_ccor": f"{ug}{gestao}{ne}",
                "ne": ne,
                "ug": ug,
                "gestao": gestao,
                "data_emissao": data_iso(e.get("data_emissao"), contrato_id=cid, endpoint=endpoint, campo="data_emissao"),
                "fonte_recurso": _texto(e.get("fonte_recurso"), cid, endpoint, "fonte_recurso"),
                "plano_interno": _texto(e.get("planointerno"), cid, endpoint, "planointerno"),
                "natureza_despesa": _texto(e.get("naturezadespesa"), cid, endpoint, "naturezadespesa"),
                "empenhado": v("empenhado"),
                "a_liquidar": v("aliquidar"),
                "liquidado": v("liquidado"),
                "pago": v("pago"),
                "rp_inscrito": v("rpinscrito"),
                "rp_a_liquidar": v("rpaliquidar"),
                "rp_liquidado": v("rpliquidado"),
                "rp_pago": v("rppago"),
            })
    return _df(linhas, COLUNAS_EMPENHOS, _MONETARIAS_EMPENHOS)


def resumo(contratos: pd.DataFrame) -> dict:
    """Indicadores do cartão-resumo (spec §4.0). `vencem_90`: vigentes com dias_para_vencer <= 90."""
    vigentes = contratos[contratos["situacao_vigencia"] == "vigente"]
    dias = vigentes["dias_para_vencer"]
    total = Decimal("0")
    for valor in vigentes["valor_global"]:
        if valor is not None and not pd.isna(valor):
            total += valor
    inativos = int(contratos["inativo_api"].astype(bool).sum())
    return {
        "total": int(len(contratos)),
        "ativos_api": int(len(contratos)) - inativos,
        "inativos_api": inativos,
        "vigentes": int(len(vigentes)),
        "vencem_90": int((dias.notna() & (dias <= 90)).sum()),
        "valor_global_vigentes": total,
    }
