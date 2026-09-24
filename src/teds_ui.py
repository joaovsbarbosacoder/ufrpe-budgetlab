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
import json
from html import escape

import pandas as pd
import streamlit as st

from src import design_tokens
from src.teds_alertas import (
    STATUS_OK,
    TIPO_EMPENHO_MULTIPLOS_TEDS,
    TIPO_NC_DIVERGE_CONSOLIDADO,
    TIPO_NC_UG_EMITENTE_AUSENTE,
    TIPO_NE_LIQUIDADO_MAIOR_QUE_EMPENHADO,
    TIPO_NE_PAGO_MAIOR_QUE_LIQUIDADO,
    TIPO_NE_SIMEC_DIFERE_TESOURO,
    TIPO_PF_DIVERGE_CONSOLIDADO,
    TIPO_PF_MAIOR_QUE_NC,
    TIPO_RODAPE_DIVERGENTE,
    TIPO_DOCUMENTO_FORA_DA_VIGENCIA,
    TIPO_SIAFI_EM_MULTIPLOS_TEDS,
    TIPO_TED_SEM_MOVIMENTACAO,
    TIPO_TED_SEM_SIAFI,
    TIPO_TED_SEM_UG_DESCENTRALIZADORA,
    TIPO_TED_VENCIDO_EM_EXECUCAO,
    TIPO_TED_VIGENCIA_INVERTIDA,
)
from src.teds_auditoria import (
    ACAO_ALERTA_STATUS_ALTERADO,
    ACAO_VINCULO_NE_DECIDIDO,
    ENTIDADE_ALERTA,
    registrar_auditoria,
)
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
    TIPO_NC_DIVERGE_CONSOLIDADO: "NC líquida difere do consolidado",
    TIPO_PF_DIVERGE_CONSOLIDADO: "PF líquido difere do consolidado",
    TIPO_PF_MAIOR_QUE_NC: "PF líquido maior que a NC líquida",
    TIPO_TED_VIGENCIA_INVERTIDA: "Vigência do TED invertida",
    TIPO_TED_SEM_UG_DESCENTRALIZADORA: "TED sem UG descentralizadora",
    TIPO_SIAFI_EM_MULTIPLOS_TEDS: "SIAFI associado a mais de um TED",
    TIPO_DOCUMENTO_FORA_DA_VIGENCIA: "Documento fora da vigência",
    TIPO_TED_VENCIDO_EM_EXECUCAO: "TED vencido ainda em execução",
    TIPO_TED_SEM_MOVIMENTACAO: "TED em execução sem movimentação",
    TIPO_NE_LIQUIDADO_MAIOR_QUE_EMPENHADO: "NE com liquidado maior que empenhado",
    TIPO_NE_PAGO_MAIOR_QUE_LIQUIDADO: "NE com pago maior que liquidado",
    TIPO_NE_SIMEC_DIFERE_TESOURO: "Valor da NE no SIMEC difere do Tesouro",
    TIPO_RODAPE_DIVERGENTE: "Rodapé do relatório difere da soma importada",
    TIPO_TED_SEM_SIAFI: "TED sem código SIAFI",
}

#: Todos os tipos de alerta que as telas listam por padrão.
TIPOS_ALERTA = (
    TIPO_EMPENHO_MULTIPLOS_TEDS,
    TIPO_NC_UG_EMITENTE_AUSENTE,
    TIPO_NC_DIVERGE_CONSOLIDADO,
    TIPO_PF_DIVERGE_CONSOLIDADO,
    TIPO_PF_MAIOR_QUE_NC,
    TIPO_DOCUMENTO_FORA_DA_VIGENCIA,
    TIPO_SIAFI_EM_MULTIPLOS_TEDS,
    TIPO_TED_SEM_UG_DESCENTRALIZADORA,
    TIPO_TED_VENCIDO_EM_EXECUCAO,
    TIPO_TED_VIGENCIA_INVERTIDA,
    TIPO_TED_SEM_MOVIMENTACAO,
    TIPO_NE_LIQUIDADO_MAIOR_QUE_EMPENHADO,
    TIPO_NE_PAGO_MAIOR_QUE_LIQUIDADO,
    TIPO_NE_SIMEC_DIFERE_TESOURO,
    TIPO_RODAPE_DIVERGENTE,
    TIPO_TED_SEM_SIAFI,
)


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
    d = design_tokens
    st.markdown(
        f"""
        <style>
        .teds-badge {{
            font-family: {d.FONT_HEADING}; font-size: 11px; letter-spacing: 0.01em;
            padding: 4px 10px; border-radius: 999px; display: inline-block;
            background: color-mix(in srgb, currentColor 10%, transparent);
            white-space: normal; line-height: 1.35; font-weight: 700;
        }}
        .teds-card {{
            border: 1px solid {d.BORDER}; border-radius: {d.RADIUS}; padding: 14px 16px;
            background: {d.SURFACE}; box-shadow: 0 3px 12px rgba(11,53,87,.06);
        }}
        .teds-muted {{ color: {d.TEXT_MUTED}; font-size: 12.5px; }}
        .teds-fictício {{
            font-family: {d.FONT_HEADING}; font-size: 9.5px; letter-spacing: 0.06em;
            text-transform: uppercase; color: {d.WARNING};
        }}
        .teds-kpi-grid {{
            display:grid; grid-template-columns:repeat(var(--count),minmax(0,1fr)); gap:12px;
            margin:.2rem 0 1rem;
        }}
        .teds-kpi {{
            min-height:92px; display:flex; align-items:center; gap:14px;
            background:{d.SURFACE}; border:1px solid {d.BORDER}; border-radius:{d.RADIUS};
            padding:14px 16px; box-shadow:0 3px 12px rgba(11,53,87,.055);
        }}
        .teds-kpi-icon {{
            flex:0 0 52px; width:52px; height:52px; border-radius:50%; color:white;
            display:grid; place-items:center; font-size:24px; font-weight:800;
            background:var(--tone); box-shadow:inset 0 -8px 18px rgba(0,0,0,.08);
        }}
        .teds-kpi-label {{color:{d.TEXT_MUTED};font-size:13px;font-weight:650;line-height:1.25}}
        .teds-kpi-value {{color:var(--tone);font-size:24px;font-weight:800;line-height:1.2;
            letter-spacing:-.035em;font-variant-numeric:tabular-nums}}
        .teds-panel {{background:{d.SURFACE};border:1px solid {d.BORDER};border-radius:{d.RADIUS};
            padding:16px 18px;box-shadow:0 3px 12px rgba(11,53,87,.055);height:100%}}
        .teds-panel-head {{display:flex;align-items:center;justify-content:space-between;margin-bottom:15px}}
        .teds-panel-title {{font:700 18px {d.FONT_HEADING};color:{d.TEXT}}}
        .teds-panel-meta {{color:{d.TEXT_MUTED};font-size:12px}}
        .teds-progress-row {{display:grid;grid-template-columns:92px minmax(120px,1fr) 54px 145px;
            gap:12px;align-items:center;margin:14px 0;color:{d.TEXT};font-size:13px}}
        .teds-progress-track {{height:16px;border-radius:5px;background:{d.BORDER};overflow:hidden}}
        .teds-progress-fill {{height:100%;border-radius:5px;background:var(--tone);width:var(--width)}}
        .teds-progress-pct {{font-weight:700;font-variant-numeric:tabular-nums}}
        .teds-progress-value {{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}}
        .teds-difference {{display:flex;justify-content:space-between;border-top:1px solid {d.BORDER};
            margin-top:16px;padding-top:14px}}
        .teds-difference strong {{color:{d.WARNING};font-size:20px}}
        @media (max-width:1100px) {{.teds-kpi-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}
            .teds-progress-row{{grid-template-columns:84px 1fr 48px}}.teds-progress-value{{grid-column:2/4;text-align:left}}}}
        @media (max-width:700px) {{.teds-kpi-grid{{grid-template-columns:1fr}}
            .teds-progress-row{{grid-template-columns:78px 1fr}}.teds-progress-pct{{text-align:right}}
            .teds-progress-value{{grid-column:2}}}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_strip(metrics: list[dict[str, object]]) -> None:
    """Faixa de indicadores do módulo TED, fiel à densidade do handoff."""

    cards = []
    for metric in metrics:
        cards.append(
            "<div class='teds-kpi' style='--tone:{tone}'>"
            "<div class='teds-kpi-icon'>{icon}</div><div>"
            "<div class='teds-kpi-label'>{label}</div>"
            "<div class='teds-kpi-value'>{value}</div></div></div>".format(
                tone=escape(str(metric.get("tone", design_tokens.ACCENT))),
                icon=escape(str(metric.get("icon", "•"))),
                label=escape(str(metric["label"])),
                value=escape(str(metric["value"])),
            )
        )
    st.markdown(
        f"<div class='teds-kpi-grid' style='--count:{min(len(cards), 5)}'>" + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


def render_execution_panel(
    title: str,
    rows: list[dict[str, object]],
    *,
    difference: tuple[str, str] | None = None,
) -> None:
    """Painel compacto de execução com rótulo, barra, percentual e valor."""

    body = []
    for row in rows:
        width = max(0.0, min(float(row.get("fraction", 0.0)), 1.0)) * 100
        body.append(
            "<div class='teds-progress-row' style='--tone:{tone};--width:{width:.1f}%'>"
            "<span>{label}</span><div class='teds-progress-track'><div class='teds-progress-fill'></div></div>"
            "<span class='teds-progress-pct'>{percent}</span>"
            "<span class='teds-progress-value'>{value}</span></div>".format(
                tone=escape(str(row.get("tone", design_tokens.ACCENT))),
                width=width,
                label=escape(str(row["label"])),
                percent=escape(str(row["percent"])),
                value=escape(str(row["value"])),
            )
        )
    diff_html = ""
    if difference:
        diff_html = (
            "<div class='teds-difference'><span>" + escape(difference[0]) + "</span>"
            "<strong>" + escape(difference[1]) + "</strong></div>"
        )
    st.markdown(
        "<div class='teds-panel'><div class='teds-panel-head'>"
        f"<span class='teds-panel-title'>{escape(title)}</span>"
        "<span class='teds-panel-meta'>Valores em R$</span></div>"
        + "".join(body) + diff_html + "</div>",
        unsafe_allow_html=True,
    )


def cor_gravidade(gravidade: str) -> str:
    return {"alta": design_tokens.NEGATIVE, "media": design_tokens.WARNING, "baixa": design_tokens.TEXT_MUTED}.get(gravidade, design_tokens.TEXT_MUTED)


def rotulo_gravidade(gravidade: str) -> str:
    return {"alta": "Crítico", "media": "Atenção", "baixa": "Informativo"}.get(gravidade, gravidade)


def cor_status_alerta(status: str) -> str:
    return {STATUS_ABERTO: design_tokens.NEGATIVE, STATUS_EM_ANALISE: design_tokens.WARNING, STATUS_RESOLVIDO: design_tokens.POSITIVE}.get(status, design_tokens.TEXT_MUTED)


def rotulo_status_alerta(status: str) -> str:
    return _ROTULO_STATUS_ALERTA.get(status, status)


_ROTULO_ACAO_AUDITORIA = {
    ACAO_ALERTA_STATUS_ALTERADO: "Situação do alerta alterada",
    ACAO_VINCULO_NE_DECIDIDO: "Vínculo de NE decidido",
}


def rotulo_acao_auditoria(acao: str) -> str:
    return _ROTULO_ACAO_AUDITORIA.get(acao, acao)


def formatar_valor_auditoria(valor: dict | None) -> str:
    """Texto curto de um `valor_anterior`/`valor_novo` da trilha — `None` (registro que cria) e
    campo vazio aparecem como "—", nunca como a palavra "None"."""

    if not valor:
        return "—"
    return "; ".join(
        f"{campo}: {json.dumps(conteudo, ensure_ascii=False) if isinstance(conteudo, dict) else dash(conteudo)}"
        for campo, conteudo in valor.items()
    )


def rotulo_tipo_alerta(tipo: str) -> str:
    return _ROTULO_TIPO_ALERTA.get(tipo, tipo)


def cor_situacao_conciliacao(situacao: str) -> str:
    return {"Conciliado": design_tokens.POSITIVE, "Conferência necessária": design_tokens.NEGATIVE, "Fonte ausente": design_tokens.WARNING}.get(situacao, design_tokens.TEXT_MUTED)


def situacao_conciliacao(
    *,
    tem_pendencia: bool,
    fonte_ausente: bool,
    diferenca: Decimal | None,
    tolerancia: Decimal,
) -> str:
    """Classifica a comparação sem deixar uma fonte ausente ocultar um vínculo conflitante."""

    if tem_pendencia:
        return "Conferência necessária"
    if fonte_ausente:
        return "Fonte ausente"
    if diferenca is not None and abs(diferenca) > tolerancia:
        return "Conferência necessária"
    return "Conciliado"


def cor_estado_ted(estado_atual: str | None) -> str:
    texto = (estado_atual or "").lower()
    if "execu" in texto:
        return design_tokens.POSITIVE
    if "restri" in texto or "diligên" in texto:
        return design_tokens.NEGATIVE
    if "aguard" in texto or "cadastr" in texto:
        return design_tokens.TEXT_MUTED
    return design_tokens.WARNING


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
    """Soma somente vínculos liberados para contabilização.

    Uma NE ligada a mais de um TED permanece consultável em ``vinculo_ne``. Somente o vínculo
    com ``status_validacao='ok'`` compõe o total; pendentes e descartados ficam como evidência.
    """

    linhas = conn.execute(
        "SELECT valor_ne FROM vinculo_ne WHERE chave_ted = ? AND status_validacao = ?",
        (chave_ted, STATUS_OK),
    ).fetchall()
    total = Decimal("0")
    for (valor,) in linhas:
        total += texto_para_valor(valor)
    return total


def soma_tg_por_teds(conn: sqlite3.Connection, chaves_ted: set[str]) -> tuple[Decimal, Decimal, bool]:
    """`(liquidado, pago, tem_dado)` somados para o conjunto de TEDs, cruzando
    `vinculo_ne.numero_ne` (já no formato completo, ex. "2024NE000338") com
    `execucao_tg.numero_completo_ne`. Somente vínculos com `status_validacao='ok'` entram no
    cruzamento, pelo mesmo bloqueio aplicado ao total empenhado. `tem_dado=False` quando
    nenhuma linha do Tesouro Gerencial foi importada para as NEs contabilizáveis — nesse caso
    os dois valores vêm zerados, mas o chamador não deve exibi-los como "0,00" (é ausência de
    dado contabilizável, não um total real de zero)."""

    if not chaves_ted:
        return Decimal("0"), Decimal("0"), False
    marcadores = ",".join("?" * len(chaves_ted))
    numeros_ne = {
        numero_ne
        for (numero_ne,) in conn.execute(
            f"SELECT DISTINCT numero_ne FROM vinculo_ne "
            f"WHERE chave_ted IN ({marcadores}) AND status_validacao = ?",
            [*chaves_ted, STATUS_OK],
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
class CoberturaRelacionamentos:
    """Painel de qualidade do §13 do briefing — percentuais/contagens sobre o quanto dos
    documentos importados já está de fato ligado a um TED (ou ao Tesouro Gerencial), para o valor financeiro sem relacionamento nunca ficar escondido atrás de
    "só uma quantidade de linhas".

    Interpretação adotada onde o briefing não é literal quanto à direção da métrica (registrado
    aqui, não presumido em silêncio):

      * "percentual de NEs relacionadas a um TED" não pode ser medido contra `vinculo_ne` (toda
        linha ali JÁ nasce ligada a um TED — `ler_doc_ne_simec` rejeita a linha antes de
        persistir se faltar TED/SIAFI, ver `src/teds_importacao_simec.py`). Em vez disso, mede
        a fração de NEs com atribuição HOJE inequívoca a um único TED (`status_validacao='ok'`)
        sobre o total de NEs distintas conhecidas — uma NE presa em `pendente` (múltiplos TEDs,
        ver `src/teds_alertas.py`) conta como não coberta até a decisão humana.
      * "percentual de NEs relacionadas ao Tesouro Gerencial" cruza as NEs com
        `status_validacao='ok'` (as mesmas contabilizáveis nos totais financeiros, ver
        `soma_tg_por_teds`) contra `execucao_tg.numero_completo_ne`.

    "Liquidações com competência" (5º indicador de antes) saiu: `execucao_tg` agora espelha a
    Execução Mensal, cujo mês é o de LANÇAMENTO, não o de competência — todo registro teria
    "competência" por construção, indicador sem informação. Competência real depende de integrar
    a Liquidação por Competência (ver docs/base_teds.md seção 6), fora do escopo atual.
    """

    pct_nc_relacionadas: float | None
    pct_pf_relacionadas: float | None
    pct_ne_relacionadas: float | None
    pct_ne_no_tesouro_gerencial: float | None
    qtd_documentos_parciais: int
    qtd_documentos_nao_relacionados: int
    valor_nao_relacionado: Decimal


def _percentual(numerador: int, denominador: int) -> float | None:
    return None if denominador == 0 else numerador / denominador


def calcular_cobertura_relacionamentos(conn: sqlite3.Connection) -> CoberturaRelacionamentos:
    total_nc, relacionadas_nc, parciais_nc, nao_relacionadas_nc = conn.execute(
        """
        SELECT COUNT(*), SUM(chave_ted IS NOT NULL), SUM(status_relacionamento = 'PARCIAL'),
               SUM(chave_ted IS NULL)
        FROM documento_nc
        """
    ).fetchone()
    # Soma em Decimal (nunca `SUM`/`CAST AS REAL` do SQLite — ponto flutuante binário é
    # proibido para dinheiro neste módulo, ver docstring de `src/teds_normalizacao.py`).
    valores_nc_sem_ted = conn.execute(
        "SELECT valor_assinado_total FROM documento_nc WHERE chave_ted IS NULL"
    ).fetchall()

    total_pf, relacionadas_pf, nao_relacionadas_pf = conn.execute(
        "SELECT COUNT(*), SUM(chave_ted IS NOT NULL), SUM(chave_ted IS NULL) FROM documento_pf"
    ).fetchone()
    valores_pf_sem_ted = conn.execute(
        "SELECT valor_assinado FROM documento_pf WHERE chave_ted IS NULL"
    ).fetchall()

    valor_nao_relacionado = sum(
        (texto_para_valor(v) for (v,) in (*valores_nc_sem_ted, *valores_pf_sem_ted)),
        start=Decimal("0"),
    )

    total_ne, ne_ok = conn.execute(
        """
        SELECT COUNT(DISTINCT chave_empenho), COUNT(DISTINCT CASE WHEN status_validacao = 'ok' THEN chave_empenho END)
        FROM vinculo_ne
        """
    ).fetchone()

    ne_no_tg = conn.execute(
        """
        SELECT COUNT(DISTINCT v.chave_empenho) FROM vinculo_ne v
        WHERE v.status_validacao = 'ok'
          AND EXISTS (SELECT 1 FROM execucao_tg t WHERE t.numero_completo_ne = v.numero_ne)
        """
    ).fetchone()[0]

    return CoberturaRelacionamentos(
        pct_nc_relacionadas=_percentual(relacionadas_nc or 0, total_nc or 0),
        pct_pf_relacionadas=_percentual(relacionadas_pf or 0, total_pf or 0),
        pct_ne_relacionadas=_percentual(ne_ok or 0, total_ne or 0),
        pct_ne_no_tesouro_gerencial=_percentual(ne_no_tg or 0, ne_ok or 0),
        qtd_documentos_parciais=parciais_nc or 0,
        qtd_documentos_nao_relacionados=(nao_relacionadas_nc or 0) + (nao_relacionadas_pf or 0),
        valor_nao_relacionado=valor_nao_relacionado,
    )


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
    tipos: tuple[str, ...] = TIPOS_ALERTA,
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
    TED. Isso mantém o alerta resolvido acessível no histórico dos dois TEDs envolvidos."""

    chaves_empenho = {
        chave_empenho
        for (chave_empenho,) in conn.execute(
            "SELECT DISTINCT chave_empenho FROM vinculo_ne WHERE chave_ted = ?",
            (chave_ted,),
        ).fetchall()
    }
    if not chaves_empenho:
        return []
    todos = carregar_alertas(conn, tipos=(TIPO_EMPENHO_MULTIPLOS_TEDS,))
    return [a for a in todos if a.documento in chaves_empenho]


def atualizar_status_alerta(
    conn: sqlite3.Connection,
    alerta_id: int,
    novo_status: str,
    *,
    responsavel: str | None = None,
    justificativa: str | None = None,
    origem: str = "interface",
) -> None:
    from datetime import datetime, timezone

    if novo_status == STATUS_RESOLVIDO:
        linha = conn.execute("SELECT tipo FROM alerta WHERE id = ?", (alerta_id,)).fetchone()
        if linha is not None and linha[0] == TIPO_EMPENHO_MULTIPLOS_TEDS:
            raise ValueError(
                "Alertas de vínculo múltiplo devem ser resolvidos pela decisão explícita do TED."
            )

    def _estado() -> tuple:
        return conn.execute(
            "SELECT status, responsavel, justificativa FROM alerta WHERE id = ?", (alerta_id,)
        ).fetchone()

    anterior = _estado()
    data_resolucao = datetime.now(timezone.utc).isoformat() if novo_status == STATUS_RESOLVIDO else None
    try:
        conn.execute(
            """
            UPDATE alerta SET status = ?, responsavel = COALESCE(?, responsavel),
                   justificativa = COALESCE(?, justificativa), data_resolucao = COALESCE(?, data_resolucao)
            WHERE id = ?
            """,
            (novo_status, responsavel, justificativa, data_resolucao, alerta_id),
        )
        novo = _estado()
        if anterior is not None and novo is not None:
            # Na MESMA transação do UPDATE: ou o status e a trilha persistem juntos, ou nenhum.
            registrar_auditoria(
                conn, acao=ACAO_ALERTA_STATUS_ALTERADO, entidade=ENTIDADE_ALERTA, entidade_id=alerta_id,
                valor_anterior=dict(zip(("status", "responsavel", "justificativa"), anterior)),
                valor_novo=dict(zip(("status", "responsavel", "justificativa"), novo)),
                usuario=novo[1], motivo=justificativa, origem=origem,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def contar_alertas_por_status(conn: sqlite3.Connection) -> dict[str, int]:
    linhas = conn.execute(
        "SELECT status, COUNT(*) FROM alerta WHERE tipo IN ({}) GROUP BY status".format(
            ",".join("?" * len(TIPOS_ALERTA))
        ),
        TIPOS_ALERTA,
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
    "id": "Lote", "tipo_relatorio": "Tipo", "nome_arquivo": "Arquivo", "data_importacao": "Data e hora",
    "quantidade_registros": "Registros aceitos", "status": "Status", "revertido_em": "Revertido em",
    "revertido_por": "Revertido por", "motivo_reversao": "Motivo da reversão",
}


def formatar_historico_lotes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.rename(columns=_ROTULOS_COLUNA_LOTE)
    formatado = df.copy()
    formatado["tipo_relatorio"] = formatado["tipo_relatorio"].map(lambda t: _ROTULO_TIPO_RELATORIO.get(t, t))
    formatado["data_importacao"] = pd.to_datetime(formatado["data_importacao"]).dt.strftime("%d/%m/%Y %H:%M")
    if "revertido_em" in formatado:
        formatado["revertido_em"] = formatado["revertido_em"].map(
            lambda v: None if pd.isna(v) or not v else pd.Timestamp(v).strftime("%d/%m/%Y %H:%M")
        )
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
    colunas = [
        "id", "tipo_relatorio", "nome_arquivo", "data_importacao", "quantidade_registros", "status",
        "revertido_em", "revertido_por", "motivo_reversao",
    ]
    linhas = conn.execute(
        f"SELECT {', '.join(colunas)} FROM import_batch ORDER BY data_importacao DESC, id DESC"
    ).fetchall()
    return pd.DataFrame(linhas, columns=colunas)
