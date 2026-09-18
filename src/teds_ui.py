"""Camada compartilhada das 6 páginas de TEDs (`app_pages/teds_*.py`) — consultas ao SQLite,
formatação e CSS comuns. Não é chamada por nenhum leitor/importador (`src/teds_*.py`
existentes) nem por testes: é só a camada de apresentação.

Convenção "real vs. fictício" seguida nas páginas (mesma já usada em
`app_pages/alertas_gerenciais.py`/`app_pages/emendas_parlamentares.py`, adaptação de um
handoff de design): todo dado que já existe no schema (TED, execução anual, documentos NC/NE/PF,
alertas de NE-em-múltiplos-TEDs e NC-sem-UG-emitente, lotes de importação) é real, consultado
direto do banco. O que o mockup mostra mas ainda não tem regra de negócio aprovada (alertas de
vigência por prazo, parâmetros globais persistidos entre sessões, restauração de backup) fica
marcado como fictício/placeholder na tela — nunca escondido, nunca apresentado como se fosse
dado de verdade.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd
import streamlit as st

from src.design_tokens import BORDER, FONT_HEADING, NEGATIVE, POSITIVE, SURFACE_ALT, TEXT_MUTED, WARNING
from src.teds_alertas import TIPO_EMPENHO_MULTIPLOS_TEDS, TIPO_NC_UG_EMITENTE_AUSENTE
from src.teds_normalizacao import texto_para_valor
from src.teds_schema import conectar

STATUS_ABERTO = "aberto"
STATUS_EM_ANALISE = "em_analise"
STATUS_RESOLVIDO = "resolvido"

_ROTULO_STATUS_ALERTA = {
    STATUS_ABERTO: "Aberto",
    STATUS_EM_ANALISE: "Em análise",
    STATUS_RESOLVIDO: "Resolvido",
}

_ROTULO_TIPO_ALERTA = {
    TIPO_EMPENHO_MULTIPLOS_TEDS: "NE vinculada a mais de um TED",
    TIPO_NC_UG_EMITENTE_AUSENTE: "UG emitente da NC ausente",
}


def conexao() -> sqlite3.Connection:
    """Uma conexão nova por execução de script — ver docstring de
    `app_pages/teds_visao_geral.py` (mesmo raciocínio vale para as 6 páginas)."""

    return conectar()


# --------------------------------------------------------------------------------------
# Formatação
# --------------------------------------------------------------------------------------

def brl(texto_decimal: str | Decimal | None) -> str:
    if texto_decimal is None:
        return "—"
    valor = texto_decimal if isinstance(texto_decimal, Decimal) else texto_para_valor(texto_decimal)
    negativo = valor < 0
    texto = "R$ " + f"{abs(valor):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return ("−" if negativo else "") + texto


def dash(valor: object) -> str:
    if valor is None:
        return "—"
    if isinstance(valor, float) and pd.isna(valor):
        return "—"
    return str(valor)


def pct(numerador: Decimal, denominador: Decimal) -> tuple[float, str]:
    """`(fração 0-1 para a barra, texto "NN%" ou "—")`."""

    if denominador == 0:
        return 0.0, "—"
    fracao = float(numerador / denominador)
    fracao_exibicao = max(0.0, min(fracao, 1.0))
    return fracao_exibicao, f"{fracao * 100:.1f}%".replace(".", ",")


# --------------------------------------------------------------------------------------
# CSS compartilhado — cartões de estatística e badges de status/gravidade.
# --------------------------------------------------------------------------------------

def injetar_css() -> None:
    st.markdown(
        f"""
        <style>
        .teds-badge {{
            font-family: {FONT_HEADING}; font-size: 11px; letter-spacing: 0.02em;
            padding: 3px 10px; border-radius: 8px; display: inline-block;
            border: 1px solid currentColor; white-space: normal; line-height: 1.35;
        }}
        .teds-card {{
            border: 1px solid {BORDER}; border-radius: 12px; padding: 14px 16px;
            background: {SURFACE_ALT};
        }}
        .teds-muted {{ color: {TEXT_MUTED}; font-size: 12.5px; }}
        .teds-fictício {{
            font-family: {FONT_HEADING}; font-size: 9.5px; letter-spacing: 0.06em;
            text-transform: uppercase; color: {WARNING};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def cor_gravidade(gravidade: str) -> str:
    return {"alta": NEGATIVE, "media": WARNING, "baixa": TEXT_MUTED}.get(gravidade, TEXT_MUTED)


def rotulo_gravidade(gravidade: str) -> str:
    return {"alta": "Crítico", "media": "Atenção", "baixa": "Informativo"}.get(gravidade, gravidade)


def cor_status_alerta(status: str) -> str:
    return {STATUS_ABERTO: NEGATIVE, STATUS_EM_ANALISE: WARNING, STATUS_RESOLVIDO: POSITIVE}.get(status, TEXT_MUTED)


def rotulo_status_alerta(status: str) -> str:
    return _ROTULO_STATUS_ALERTA.get(status, status)


def rotulo_tipo_alerta(tipo: str) -> str:
    return _ROTULO_TIPO_ALERTA.get(tipo, tipo)


def cor_situacao_conciliacao(situacao: str) -> str:
    return {"Conciliado": POSITIVE, "Conferência necessária": NEGATIVE, "Fonte ausente": WARNING}.get(situacao, TEXT_MUTED)


def cor_estado_ted(estado_atual: str | None) -> str:
    texto = (estado_atual or "").lower()
    if "execu" in texto:
        return POSITIVE
    if "restri" in texto or "diligên" in texto:
        return NEGATIVE
    if "aguard" in texto or "cadastr" in texto:
        return TEXT_MUTED
    return WARNING


def badge(texto: str, cor: str) -> str:
    return f"<span class='teds-badge' style='color:{cor}'>{texto}</span>"


# --------------------------------------------------------------------------------------
# Consultas
# --------------------------------------------------------------------------------------

_CAMPOS_VALOR_EXECUCAO = (
    "total_nc_descentralizacao", "total_nc_devolucao", "total_descentralizado",
    "total_pf_repasse", "total_pf_devolucao", "total_repassado",
)


def carregar_teds(conn: sqlite3.Connection) -> pd.DataFrame:
    """Uma linha por TED (nunca por par TED+exercício). `execucao_anual` tem `PRIMARY KEY
    (chave_ted, ano_emissao)` de propósito — um TED plurianual aparece em mais de uma linha
    ali, cada uma com a fração daquele exercício (a soma delas bate com o total do TED, não
    é um valor repetido). Por isso a agregação por TED é feita em Python somando essas
    frações (nunca um JOIN linha-a-linha: isso duplicaria o TED por exercício e infla contagens
    e somas que são por-TED, como "empenhado" — bug real encontrado ao testar contra a
    extração real de 2026, corrigido aqui). `anos_emissao` guarda o conjunto de exercícios em
    que o TED teve movimento, para os filtros de "Exercício" testarem pertencimento, não
    igualdade com um único ano."""

    teds = conn.execute(
        "SELECT chave_ted, ted, codigo_siafi, descricao, estado_atual, inicio_vigencia, "
        "fim_vigencia, ug_descentralizadora FROM ted ORDER BY ted"
    ).fetchall()
    if not teds:
        return pd.DataFrame(
            columns=[
                "chave_ted", "ted", "codigo_siafi", "descricao", "estado_atual",
                "inicio_vigencia", "fim_vigencia", "ug_descentralizadora", "anos_emissao",
                *_CAMPOS_VALOR_EXECUCAO, "empenhado",
            ]
        )

    execucoes = conn.execute(
        f"SELECT chave_ted, ano_emissao, {', '.join(_CAMPOS_VALOR_EXECUCAO)} FROM execucao_anual"
    ).fetchall()
    agregados: dict[str, dict[str, Decimal]] = {}
    anos_por_ted: dict[str, set[int]] = {}
    for linha in execucoes:
        chave_ted, ano_emissao, *valores = linha
        acumulado = agregados.setdefault(chave_ted, {campo: Decimal("0") for campo in _CAMPOS_VALOR_EXECUCAO})
        for campo, valor in zip(_CAMPOS_VALOR_EXECUCAO, valores):
            acumulado[campo] += texto_para_valor(valor)
        anos_por_ted.setdefault(chave_ted, set()).add(int(ano_emissao))

    linhas_finais = []
    for chave_ted, ted, siafi, descricao, estado, inicio, fim, ug in teds:
        valores = agregados.get(chave_ted)
        linhas_finais.append(
            {
                "chave_ted": chave_ted, "ted": ted, "codigo_siafi": siafi, "descricao": descricao,
                "estado_atual": estado, "inicio_vigencia": inicio, "fim_vigencia": fim,
                "ug_descentralizadora": ug, "anos_emissao": frozenset(anos_por_ted.get(chave_ted, set())),
                **{campo: (str(valores[campo]) if valores else None) for campo in _CAMPOS_VALOR_EXECUCAO},
                "empenhado": _soma_empenhado_por_ted(conn, chave_ted),
            }
        )
    return pd.DataFrame(linhas_finais)


def anos_disponiveis(teds_df: pd.DataFrame) -> list[int]:
    """Anos de emissão distintos em todo o recorte — um TED plurianual conta em cada ano em
    que teve movimento (ver docstring de `carregar_teds`)."""

    todos: set[int] = set()
    for anos in teds_df["anos_emissao"]:
        todos |= anos
    return sorted(todos, reverse=True)


def filtrar_por_exercicio(teds_df: pd.DataFrame, ano: int) -> pd.DataFrame:
    return teds_df[teds_df["anos_emissao"].apply(lambda anos: ano in anos)]


def _soma_empenhado_por_ted(conn: sqlite3.Connection, chave_ted: str) -> Decimal:
    linhas = conn.execute("SELECT valor_ne FROM vinculo_ne WHERE chave_ted = ?", (chave_ted,)).fetchall()
    total = Decimal("0")
    for (valor,) in linhas:
        total += texto_para_valor(valor)
    return total


def soma_tg_por_teds(conn: sqlite3.Connection, chaves_ted: set[str]) -> tuple[Decimal, Decimal, bool]:
    """`(liquidado, pago, tem_dado)` somados para o conjunto de TEDs, cruzando
    `vinculo_ne.numero_ne` (já no formato completo, ex. "2024NE000338") com
    `execucao_tg.numero_completo_ne`. `tem_dado=False` quando nenhuma linha do Tesouro
    Gerencial foi importada ainda para nenhuma dessas NEs — nesse caso os dois valores vêm
    zerados, mas o chamador não deve exibi-los como "0,00" (é ausência de dado, não um total
    real de zero)."""

    if not chaves_ted:
        return Decimal("0"), Decimal("0"), False
    marcadores = ",".join("?" * len(chaves_ted))
    numeros_ne = {
        numero_ne
        for (numero_ne,) in conn.execute(
            f"SELECT DISTINCT numero_ne FROM vinculo_ne WHERE chave_ted IN ({marcadores})",
            list(chaves_ted),
        ).fetchall()
    }
    if not numeros_ne:
        return Decimal("0"), Decimal("0"), False
    marcadores_ne = ",".join("?" * len(numeros_ne))
    linhas = conn.execute(
        f"SELECT liquidado, pago FROM execucao_tg WHERE numero_completo_ne IN ({marcadores_ne})",
        list(numeros_ne),
    ).fetchall()
    if not linhas:
        return Decimal("0"), Decimal("0"), False
    liquidado = sum((texto_para_valor(v) for v, _ in linhas if v is not None), start=Decimal("0"))
    pago = sum((texto_para_valor(v) for _, v in linhas if v is not None), start=Decimal("0"))
    return liquidado, pago, True


@dataclass(frozen=True)
class AlertaLinha:
    id: int
    tipo: str
    gravidade: str
    chave_ted: str | None
    documento: str
    descricao: str
    status: str
    data_identificacao: str
    responsavel: str | None
    justificativa: str | None
    data_resolucao: str | None


def carregar_alertas(
    conn: sqlite3.Connection,
    *,
    tipos: tuple[str, ...] = (TIPO_EMPENHO_MULTIPLOS_TEDS, TIPO_NC_UG_EMITENTE_AUSENTE),
    status: str | None = None,
    chave_ted: str | None = None,
) -> list[AlertaLinha]:
    clausulas = ["tipo IN ({})".format(",".join("?" * len(tipos)))]
    parametros: list[object] = list(tipos)
    if status is not None:
        clausulas.append("status = ?")
        parametros.append(status)
    if chave_ted is not None:
        clausulas.append("chave_ted = ?")
        parametros.append(chave_ted)
    linhas = conn.execute(
        f"""
        SELECT id, tipo, gravidade, chave_ted, documento, descricao, status,
               data_identificacao, responsavel, justificativa, data_resolucao
        FROM alerta WHERE {' AND '.join(clausulas)}
        ORDER BY CASE gravidade WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END, data_identificacao DESC
        """,
        parametros,
    ).fetchall()
    return [AlertaLinha(*linha) for linha in linhas]


def alertas_de_ne_para_ted(conn: sqlite3.Connection, chave_ted: str) -> list[AlertaLinha]:
    """Alertas de NE-em-múltiplos-TEDs relacionados a este TED — não usam `chave_ted` na
    própria linha do alerta (uma NE pendente não pertence a um único TED, ver docstring de
    `gerar_alertas_ne_multiplos_teds`), então o cruzamento é por `chave_empenho` das NEs deste
    TED que estão com `status_validacao='pendente'`."""

    chaves_empenho_pendentes = {
        chave_empenho
        for (chave_empenho,) in conn.execute(
            "SELECT DISTINCT chave_empenho FROM vinculo_ne WHERE chave_ted = ? AND status_validacao = 'pendente'",
            (chave_ted,),
        ).fetchall()
    }
    if not chaves_empenho_pendentes:
        return []
    todos = carregar_alertas(conn, tipos=(TIPO_EMPENHO_MULTIPLOS_TEDS,))
    return [a for a in todos if a.documento in chaves_empenho_pendentes]


def atualizar_status_alerta(
    conn: sqlite3.Connection,
    alerta_id: int,
    novo_status: str,
    *,
    responsavel: str | None = None,
    justificativa: str | None = None,
) -> None:
    from datetime import datetime, timezone

    data_resolucao = datetime.now(timezone.utc).isoformat() if novo_status == STATUS_RESOLVIDO else None
    conn.execute(
        """
        UPDATE alerta SET status = ?, responsavel = COALESCE(?, responsavel),
               justificativa = COALESCE(?, justificativa), data_resolucao = COALESCE(?, data_resolucao)
        WHERE id = ?
        """,
        (novo_status, responsavel, justificativa, data_resolucao, alerta_id),
    )
    conn.commit()


def contar_alertas_por_status(conn: sqlite3.Connection) -> dict[str, int]:
    linhas = conn.execute(
        "SELECT status, COUNT(*) FROM alerta WHERE tipo IN (?, ?) GROUP BY status",
        (TIPO_EMPENHO_MULTIPLOS_TEDS, TIPO_NC_UG_EMITENTE_AUSENTE),
    ).fetchall()
    return dict(linhas)


def documentos_nc(conn: sqlite3.Connection, chave_ted: str) -> list[tuple]:
    return conn.execute(
        "SELECT numero_nc, ug_emitente, operacao, data_emissao, valor_assinado_total, "
        "quantidade_linhas, status_relacionamento FROM documento_nc WHERE chave_ted = ? "
        "ORDER BY data_emissao",
        (chave_ted,),
    ).fetchall()


def documentos_pf(conn: sqlite3.Connection, chave_ted: str) -> list[tuple]:
    return conn.execute(
        "SELECT numero_pf, ug_emitente, operacao, data_emissao, valor_assinado "
        "FROM documento_pf WHERE chave_ted = ? ORDER BY data_emissao",
        (chave_ted,),
    ).fetchall()


def vinculos_ne(conn: sqlite3.Connection, chave_ted: str) -> list[tuple]:
    return conn.execute(
        "SELECT numero_ne, ug_emitente, gestao_emitente, valor_ne, status_validacao, chave_empenho "
        "FROM vinculo_ne WHERE chave_ted = ? ORDER BY numero_ne",
        (chave_ted,),
    ).fetchall()


_ROTULO_TIPO_RELATORIO = {
    "simec_execucao_anual": "SIMEC — Execução Orç./Financeiro",
    "simec_doc_nc": "SIMEC — DOC NC",
    "simec_doc_ne": "SIMEC — DOC NE",
    "simec_doc_pf": "SIMEC — DOC PF",
    "tesouro_gerencial_execucao": "Tesouro Gerencial — Execução",
}

_ROTULOS_COLUNA_LOTE = {
    "tipo_relatorio": "Tipo", "nome_arquivo": "Arquivo", "data_importacao": "Data e hora",
    "quantidade_registros": "Registros aceitos", "status": "Status",
}


def formatar_historico_lotes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.rename(columns=_ROTULOS_COLUNA_LOTE)
    formatado = df.copy()
    formatado["tipo_relatorio"] = formatado["tipo_relatorio"].map(lambda t: _ROTULO_TIPO_RELATORIO.get(t, t))
    formatado["data_importacao"] = pd.to_datetime(formatado["data_importacao"]).dt.strftime("%d/%m/%Y %H:%M")
    return formatado.rename(columns=_ROTULOS_COLUNA_LOTE)


def historico_lotes_do_ted(conn: sqlite3.Connection, chave_ted: str) -> pd.DataFrame:
    """Lotes de importação que gravaram/atualizaram algo deste TED — junta os
    `import_batch_id` das quatro tabelas de origem (execução anual, NC, NE, PF)."""

    ids: set[int] = set()
    for tabela, filtro in (
        ("execucao_anual", "chave_ted = ?"),
        ("documento_nc", "chave_ted = ?"),
        ("vinculo_ne", "chave_ted = ?"),
        ("documento_pf", "chave_ted = ?"),
    ):
        ids.update(
            id_lote
            for (id_lote,) in conn.execute(
                f"SELECT DISTINCT import_batch_id FROM {tabela} WHERE {filtro}", (chave_ted,)
            ).fetchall()
        )
    colunas = ["tipo_relatorio", "nome_arquivo", "data_importacao", "quantidade_registros"]
    if not ids:
        return formatar_historico_lotes(pd.DataFrame(columns=colunas))
    marcadores = ",".join("?" * len(ids))
    linhas = conn.execute(
        f"SELECT tipo_relatorio, nome_arquivo, data_importacao, quantidade_registros FROM import_batch "
        f"WHERE id IN ({marcadores}) ORDER BY data_importacao DESC",
        list(ids),
    ).fetchall()
    return formatar_historico_lotes(pd.DataFrame(linhas, columns=colunas))


def historico_importacoes(conn: sqlite3.Connection) -> pd.DataFrame:
    linhas = conn.execute(
        "SELECT tipo_relatorio, nome_arquivo, data_importacao, quantidade_registros, status "
        "FROM import_batch ORDER BY data_importacao DESC"
    ).fetchall()
    return pd.DataFrame(
        linhas, columns=["tipo_relatorio", "nome_arquivo", "data_importacao", "quantidade_registros", "status"]
    )
