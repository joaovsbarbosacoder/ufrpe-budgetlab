"""
Alertas do módulo de TEDs, um bloco por seção deste arquivo (lista completa e regras em
`docs/base_teds.md`, seção 8):

  * "empenho associado a mais de um TED" — o caso concreto documentado no briefing (NE
    2026NE000422 nos TEDs 17352 e 17454);
  * "NC sem UG emitente" (`status_relacionamento='PARCIAL'` — ver docstring de
    `ler_doc_nc_simec` em `src/teds_importacao_simec.py`): achado da extração real do SIMEC;
  * conciliação SIMEC analítica × consolidada;
  * validações cadastrais e de vigência;
  * execução por NE no Tesouro Gerencial.

Cada tipo tem duas camadas: funções puras (testáveis sem banco) e uma `sincronizar_alertas_*`
que lê do SQLite e grava alertas novos em `alerta` — sem duplicar um alerta já aberto para o
mesmo documento, e sem nunca fechar um alerta sozinha (resolução é sempre uma ação humana
registrada na Central de Alertas, fora do escopo desta fase).
"""

from __future__ import annotations

import calendar
import json
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from src.teds_auditoria import (
    ACAO_ALERTA_STATUS_ALTERADO,
    ACAO_VINCULO_NE_DECIDIDO,
    ENTIDADE_ALERTA,
    ENTIDADE_VINCULO_NE,
    registrar_auditoria,
)
from src.teds_normalizacao import texto_para_valor, valor_para_texto

TIPO_EMPENHO_MULTIPLOS_TEDS = "empenho_multiplos_teds"
TIPO_NC_UG_EMITENTE_AUSENTE = "nc_ug_emitente_ausente"
STATUS_PENDENTE = "pendente"
STATUS_DESCARTADO = "descartado"
STATUS_OK = "ok"
STATUS_RELACIONAMENTO_PARCIAL = "PARCIAL"


@dataclass(frozen=True)
class VinculoNE:
    chave_ted: str
    chave_empenho: str
    numero_ne: str
    valor_ne: Decimal


@dataclass(frozen=True)
class Alerta:
    tipo: str
    gravidade: str
    documento: str
    descricao: str
    chave_ted: str | None = None
    status: str = "aberto"


@dataclass(frozen=True)
class DecisaoVinculoNE:
    id: int
    chave_empenho: str
    chave_ted_escolhida: str
    teds_envolvidos: tuple[str, ...]
    decisao: str
    responsavel: str
    justificativa: str
    data_decisao: str
    alerta_id: int


def agrupar_por_empenho(vinculos: list[VinculoNE]) -> dict[str, list[VinculoNE]]:
    grupos: dict[str, list[VinculoNE]] = {}
    for vinculo in vinculos:
        grupos.setdefault(vinculo.chave_empenho, []).append(vinculo)
    return grupos


def detectar_ne_em_multiplos_teds(vinculos: list[VinculoNE]) -> dict[str, list[VinculoNE]]:
    """Chaves de empenho cujos vínculos apontam para mais de um TED distinto.

    Não decide qual TED está certo — só identifica o conflito (regra do briefing: "não
    excluir nem escolher automaticamente um dos vínculos").
    """

    pendentes = {}
    for chave_empenho, grupo in agrupar_por_empenho(vinculos).items():
        if len({v.chave_ted for v in grupo}) > 1:
            pendentes[chave_empenho] = grupo
    return pendentes


def total_empenhado_por_ted(
    vinculos: list[VinculoNE], pendentes: dict[str, list[VinculoNE]]
) -> dict[str, Decimal]:
    """Soma `valor_ne` por TED, excluindo vínculos pendentes de distribuição — impede que a
    execução de uma NE em conflito seja contabilizada integralmente nos dois TEDs enquanto
    a pendência não é resolvida."""

    totais: dict[str, Decimal] = {}
    for vinculo in vinculos:
        if vinculo.chave_empenho in pendentes:
            continue
        totais[vinculo.chave_ted] = totais.get(vinculo.chave_ted, Decimal("0")) + vinculo.valor_ne
    return totais


def gerar_alertas_ne_multiplos_teds(pendentes: dict[str, list[VinculoNE]]) -> list[Alerta]:
    alertas = []
    for chave_empenho, grupo in pendentes.items():
        teds = sorted({v.chave_ted for v in grupo})
        numero_ne = grupo[0].numero_ne
        descricao = (
            f"Empenho {numero_ne} (chave {chave_empenho}) está vinculado a {len(teds)} TEDs "
            f"diferentes: {', '.join(teds)}. Execução mantida fora dos totais consolidados "
            "de todos os TEDs envolvidos até a resolução do vínculo."
        )
        alertas.append(
            Alerta(
                tipo=TIPO_EMPENHO_MULTIPLOS_TEDS,
                gravidade="alta",
                documento=chave_empenho,
                descricao=descricao,
                chave_ted=None,
            )
        )
    return alertas


# --------------------------------------------------------------------------------------
# NC sem UG emitente (status_relacionamento='PARCIAL')
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DocumentoNC:
    chave_nc_documento: str
    numero_nc: str
    chave_ted: str | None
    status_relacionamento: str


def detectar_documentos_nc_parciais(documentos: list[DocumentoNC]) -> list[DocumentoNC]:
    """Documentos de NC com `status_relacionamento='PARCIAL'` — sem UG emitente em nenhuma
    das linhas do documento, o que impede a conciliação externa por UG (ver docstring de
    `ler_doc_nc_simec`). Não decide nada sobre o documento, só identifica a lacuna."""

    return [d for d in documentos if d.status_relacionamento == STATUS_RELACIONAMENTO_PARCIAL]


#: Rótulo do agrupamento das NCs sem UG que também não têm TED conhecido.
SEM_TED = "(sem TED)"


def gerar_alertas_nc_parcial(parciais: list[DocumentoNC]) -> list[Alerta]:
    """Um alerta por TED (documento `ted:<chave_ted>`, gravidade "baixa"), listando as NCs sem UG.

    Decisão de 08/10/2026 (spec `docs/superpowers/specs/2026-10-08-teds-alertas-e-controle-nc-design.md`,
    §3.3): era um alerta "media" por NC; a ausência de UG é falha sistemática do SIMEC (28% das NCs na
    extração real), e um alerta por NC (41) poluía a Central. NC sem `chave_ted` agrupa em
    `ted:(sem TED)`. TED sem NC nessa situação não gera alerta."""

    por_ted: dict[str | None, list[DocumentoNC]] = {}
    for documento in parciais:
        por_ted.setdefault(documento.chave_ted, []).append(documento)

    alertas = []
    for chave in sorted(por_ted, key=lambda c: (c is None, c or "")):
        documentos = sorted(por_ted[chave], key=lambda d: (d.numero_nc, d.chave_nc_documento))
        numeros = ", ".join(d.numero_nc for d in documentos)
        rotulo = f"TED {chave}" if chave else "NCs sem TED conhecido"
        alertas.append(
            Alerta(
                tipo=TIPO_NC_UG_EMITENTE_AUSENTE,
                gravidade="baixa",
                documento=f"ted:{chave or SEM_TED}",
                descricao=(
                    f"{rotulo}: {len(documentos)} NC(s) sem UG emitente em nenhuma linha da extração "
                    f"({numeros}) — conciliação externa por UG fica incompleta até a UG ser "
                    "identificada manualmente."
                ),
                chave_ted=chave,
            )
        )
    return alertas


def _carregar_documentos_nc(conn: sqlite3.Connection) -> list[DocumentoNC]:
    linhas = conn.execute(
        "SELECT chave_nc_documento, numero_nc, chave_ted, status_relacionamento FROM documento_nc"
    ).fetchall()
    return [
        DocumentoNC(
            chave_nc_documento=chave_nc_documento,
            numero_nc=numero_nc,
            chave_ted=chave_ted,
            status_relacionamento=status_relacionamento,
        )
        for chave_nc_documento, numero_nc, chave_ted, status_relacionamento in linhas
    ]


def sincronizar_alertas_nc_parcial(conn: sqlite3.Connection) -> list[Alerta]:
    """Garante um alerta aberto por TED com NC de `status_relacionamento='PARCIAL'` (um por TED desde
    08/10/2026, ver `gerar_alertas_nc_parcial`). Devolve só os alertas recém-criados nesta chamada (não
    os que já existiam) — mesma semântica de `sincronizar_alertas_multiplos_teds`. Nunca fecha alerta:
    os antigos, um por NC, continuam abertos até resolução (a reavaliação da spec, §4, cuida deles)."""

    parciais = detectar_documentos_nc_parciais(_carregar_documentos_nc(conn))
    return _gravar_alertas_novos(conn, gerar_alertas_nc_parcial(parciais))


# --------------------------------------------------------------------------------------
# Conciliação SIMEC: documentos analíticos (NC/PF) × totais consolidados (execucao_anual)
# --------------------------------------------------------------------------------------

TIPO_NC_DIVERGE_CONSOLIDADO = "nc_liquida_diverge_consolidado"
TIPO_PF_DIVERGE_CONSOLIDADO = "pf_liquida_diverge_consolidado"
TIPO_PF_MAIOR_QUE_NC = "pf_liquida_maior_que_nc"

#: Diferença máxima tolerada entre duas somas (briefing, seções 8.1/9.1: "maior que R$ 0,01").
TOLERANCIA_CONCILIACAO = Decimal("0.01")


@dataclass(frozen=True)
class ResumoConciliacaoSimec:
    """Uma linha por TED. `*_analitica` = soma dos documentos importados (`valor_assinado`,
    ou seja, já com o sinal da operação); `*_consolidada` = soma de `execucao_anual` sobre
    todos os exercícios importados (Total Descentralizado / Total Repassado).

    Janela comum (decisão de 08/10/2026, spec `docs/superpowers/specs/2026-10-08-teds-alertas-e-controle-nc-design.md`,
    §3.1): `nc_analitica`/`pf_analitica` somam SÓ os documentos com data num ano de `anos_consolidado`
    (os anos de `execucao_anual` do TED) — a extração analítica cobre outro recorte (ex.: PF desde 2019 ×
    consolidado desde 2023), e comparar períodos diferentes gerava divergência falsa. O valor fora da
    janela fica em `nc_fora_janela`/`pf_fora_janela`; documento sem data fica fora da soma e é contado e
    somado À PARTE, por tipo (`nc_sem_data`/`nc_sem_data_valor`, `pf_sem_data`/`pf_sem_data_valor`).

    Documento sem data (correção de 08/10/2026, decisão do controlador após rodar as regras no banco real,
    onde NCs principais de vários TEDs vêm sem data — ex.: 14142|1AAVEH, duas NCs sem data somam exatamente
    o consolidado): sem data não dá para saber se está na janela, então só há divergência se ela persiste
    TANTO com a soma da janela QUANTO com janela + sem data; se uma das duas bate, é inconclusivo (sem
    alerta). Ver `_diverge`.

    `nc_analitica`/`pf_analitica` ficam `None` quando o TED não tem NENHUM documento do tipo no extrato
    ("sem base", nunca zero: não pode virar "divergência de tudo"). Antes de 08/10/2026 o "sem base" era
    só a tabela inteira vazia, e o TED sem documento era comparado como R$ 0.

    `inicio_vigencia` serve à regra de PF maior que a NC (§3.2). Os campos novos têm valor padrão para um
    resumo montado à mão continuar valendo como antes (sem janela, sem vigência)."""

    chave_ted: str
    nc_consolidada: Decimal
    pf_consolidada: Decimal
    nc_analitica: Decimal | None
    pf_analitica: Decimal | None
    anos_consolidado: frozenset[int] = frozenset()
    nc_fora_janela: Decimal = Decimal("0")
    pf_fora_janela: Decimal = Decimal("0")
    nc_sem_data: int = 0
    nc_sem_data_valor: Decimal = Decimal("0")
    pf_sem_data: int = 0
    pf_sem_data_valor: Decimal = Decimal("0")
    inicio_vigencia: date | None = None


def _moeda(valor: Decimal) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _anos_texto(anos: frozenset[int]) -> str:
    """"2023–2025" quando os anos são contínuos; senão a lista ("2019, 2023")."""

    ordenados = sorted(anos)
    if len(ordenados) > 1 and ordenados == list(range(ordenados[0], ordenados[-1] + 1)):
        return f"{ordenados[0]}–{ordenados[-1]}"
    return ", ".join(str(a) for a in ordenados)


def _diverge(
    janela: Decimal | None, sem_data_qtd: int, sem_data_valor: Decimal, consolidado: Decimal, tolerancia: Decimal
) -> bool:
    """Divergência comprovável (correção de 08/10/2026): `janela` `None` é "sem base" (nunca diverge). Com
    documentos sem data, a diferença tem de persistir com a janela sozinha E com janela + sem data — se
    qualquer uma das duas bate com o consolidado, é inconclusivo, não divergência."""

    if janela is None or abs(janela - consolidado) <= tolerancia:
        return False
    return sem_data_qtd == 0 or abs(janela + sem_data_valor - consolidado) > tolerancia


def _detalhe_janela(
    r: ResumoConciliacaoSimec, fora_janela: Decimal, tipo: str, sem_data_qtd: int, sem_data_valor: Decimal
) -> str:
    """Trecho da descrição com o que ficou fora da soma (spec de 08/10/2026, §3.1), só do tipo do alerta
    (`tipo` = "NC" ou "PF"). Vazio quando o resumo não traz os anos do consolidado (montado à mão)."""

    if not r.anos_consolidado:
        return ""
    texto = (
        f" Comparados só os documentos emitidos em {_anos_texto(r.anos_consolidado)} (anos do consolidado); "
        f"documentos de outros anos somam {_moeda(fora_janela)} e ficaram fora"
    )
    if sem_data_qtd:
        texto += (
            f"; {sem_data_qtd} {tipo} sem data ({_moeda(sem_data_valor)}) fora da soma — a diferença persiste "
            "também somando-as"
        )
    return texto + "."


def vigencia_anterior_ao_consolidado(r: ResumoConciliacaoSimec) -> bool:
    """Vigência iniciada antes de 1º de janeiro do primeiro ano do consolidado do TED: a NC daquele
    período não está nas fontes oficiais importadas, então PF > NC é "sem base" (decisão de 08/10/2026,
    spec, §3.2 — os 7 alertas abertos tinham vigência anterior a 2023). Sem início de vigência ou sem
    anos do consolidado não dá para afirmar: `False` (alerta como antes)."""

    return (
        r.inicio_vigencia is not None
        and bool(r.anos_consolidado)
        and r.inicio_vigencia < date(min(r.anos_consolidado), 1, 1)
    )


def gerar_alertas_conciliacao_simec(
    resumos: list[ResumoConciliacaoSimec], tolerancia: Decimal = TOLERANCIA_CONCILIACAO
) -> list[Alerta]:
    """Três verificações, todas descritivas: só apontam a diferença e as causas possíveis, sem
    decidir qual fonte está certa e sem alterar nenhum dado.

      1. NC líquida analítica ≠ Total Descentralizado consolidado;
      2. PF líquido analítico ≠ Total Repassado consolidado;
      3. PF líquido consolidado > NC líquida consolidada (repasse sem crédito que o cubra) — exceto
         quando a vigência começa antes do primeiro ano do consolidado ("sem base", spec de
         08/10/2026, §3.2).

    1 e 2 só avaliam o TED que tem documento do tipo (`*_analitica` não `None`) e, desde 08/10/2026,
    comparam o mesmo período (janela comum, §3.1; a soma já vem filtrada pelo carregador).
    """

    alertas: list[Alerta] = []
    for r in sorted(resumos, key=lambda x: x.chave_ted):
        if _diverge(r.nc_analitica, r.nc_sem_data, r.nc_sem_data_valor, r.nc_consolidada, tolerancia):
            alertas.append(
                Alerta(
                    tipo=TIPO_NC_DIVERGE_CONSOLIDADO,
                    gravidade="alta",
                    documento=r.chave_ted,
                    chave_ted=r.chave_ted,
                    descricao=(
                        f"NC líquida dos documentos importados ({_moeda(r.nc_analitica)}) difere do "
                        f"Total Descentralizado consolidado ({_moeda(r.nc_consolidada)}) em "
                        f"{_moeda(r.nc_analitica - r.nc_consolidada)}.{_detalhe_janela(r, r.nc_fora_janela, 'NC', r.nc_sem_data, r.nc_sem_data_valor)} "
                        "Possíveis causas: extração de documentos incompleta, documento sem data/TED, ou "
                        "divergência real na origem — não decidido automaticamente."
                    ),
                )
            )
        if _diverge(r.pf_analitica, r.pf_sem_data, r.pf_sem_data_valor, r.pf_consolidada, tolerancia):
            alertas.append(
                Alerta(
                    tipo=TIPO_PF_DIVERGE_CONSOLIDADO,
                    gravidade="alta",
                    documento=r.chave_ted,
                    chave_ted=r.chave_ted,
                    descricao=(
                        f"PF líquido dos documentos importados ({_moeda(r.pf_analitica)}) difere do "
                        f"Total Repassado consolidado ({_moeda(r.pf_consolidada)}) em "
                        f"{_moeda(r.pf_analitica - r.pf_consolidada)}.{_detalhe_janela(r, r.pf_fora_janela, 'PF', r.pf_sem_data, r.pf_sem_data_valor)} "
                        "Possíveis causas: extração de documentos incompleta, documento sem data, ou "
                        "divergência real na origem — não decidido automaticamente."
                    ),
                )
            )
        if r.pf_consolidada - r.nc_consolidada > tolerancia and not vigencia_anterior_ao_consolidado(r):
            alertas.append(
                Alerta(
                    tipo=TIPO_PF_MAIOR_QUE_NC,
                    gravidade="alta",
                    documento=r.chave_ted,
                    chave_ted=r.chave_ted,
                    descricao=(
                        f"Repasse líquido consolidado ({_moeda(r.pf_consolidada)}) é maior que a NC "
                        f"líquida consolidada ({_moeda(r.nc_consolidada)}): excesso de "
                        f"{_moeda(r.pf_consolidada - r.nc_consolidada)}. Pode indicar crédito "
                        "descentralizado em exercício anterior ao período importado — conferir "
                        "antes de considerar o TED conciliado."
                    ),
                )
            )
    return alertas


def _carregar_resumos_conciliacao(conn: sqlite3.Connection) -> list[ResumoConciliacaoSimec]:
    consolidado: dict[str, list[Decimal]] = {}
    anos: dict[str, set[int]] = {}
    for chave_ted, ano, total_descentralizado, total_repassado in conn.execute(
        "SELECT chave_ted, ano_emissao, total_descentralizado, total_repassado FROM execucao_anual"
    ).fetchall():
        acumulado = consolidado.setdefault(chave_ted, [Decimal("0"), Decimal("0")])
        acumulado[0] += texto_para_valor(total_descentralizado)
        acumulado[1] += texto_para_valor(total_repassado)
        anos.setdefault(chave_ted, set()).add(int(ano))

    inicio_por_ted = {
        chave: _data_ou_none(inicio)
        for chave, inicio in conn.execute("SELECT chave_ted, inicio_vigencia FROM ted").fetchall()
    }

    def _somar(sql: str) -> dict[str, tuple[Decimal, Decimal, int, Decimal]]:
        """chave_ted → (soma na janela do consolidado, soma fora dela, qtd. sem data, soma sem data). TED
        fora do dicionário = nenhum documento do tipo ("sem base", spec de 08/10/2026, §3.1)."""

        somas: dict[str, list] = {}
        for chave_ted, data_emissao, valor in conn.execute(sql).fetchall():
            if not chave_ted:
                continue  # documento sem TED conhecido: aparece na cobertura de relacionamentos
            acumulado = somas.setdefault(chave_ted, [Decimal("0"), Decimal("0"), 0, Decimal("0")])
            data = _data_ou_none(data_emissao)
            if data is None:
                acumulado[2] += 1
                acumulado[3] += texto_para_valor(valor)
            elif data.year in anos.get(chave_ted, ()):
                acumulado[0] += texto_para_valor(valor)
            else:
                acumulado[1] += texto_para_valor(valor)
        return {chave: (v[0], v[1], v[2], v[3]) for chave, v in somas.items()}

    nc = _somar("SELECT chave_ted, data_emissao, valor_assinado_total FROM documento_nc")
    pf = _somar("SELECT chave_ted, data_emissao, valor_assinado FROM documento_pf")
    sem_base = (None, Decimal("0"), 0, Decimal("0"))
    resumos = []
    for chave_ted, (nc_cons, pf_cons) in consolidado.items():
        nc_janela, nc_fora, nc_sem_data, nc_sem_data_valor = nc.get(chave_ted, sem_base)
        pf_janela, pf_fora, pf_sem_data, pf_sem_data_valor = pf.get(chave_ted, sem_base)
        resumos.append(ResumoConciliacaoSimec(
            chave_ted=chave_ted,
            nc_consolidada=nc_cons,
            pf_consolidada=pf_cons,
            nc_analitica=nc_janela,
            pf_analitica=pf_janela,
            anos_consolidado=frozenset(anos[chave_ted]),
            nc_fora_janela=nc_fora,
            pf_fora_janela=pf_fora,
            nc_sem_data=nc_sem_data,
            nc_sem_data_valor=nc_sem_data_valor,
            pf_sem_data=pf_sem_data,
            pf_sem_data_valor=pf_sem_data_valor,
            inicio_vigencia=inicio_por_ted.get(chave_ted),
        ))
    return resumos


def _gravar_alertas_novos(conn: sqlite3.Connection, candidatos: list[Alerta]) -> list[Alerta]:
    """Grava os candidatos que ainda não têm alerta não resolvido para o mesmo (tipo, documento)
    e devolve só os recém-criados. Nunca fecha nem altera um alerta existente."""

    tipos = sorted({a.tipo for a in candidatos})
    ja_sinalizados: set[tuple[str, str]] = set()
    if tipos:
        ja_sinalizados = {
            (tipo, documento)
            for tipo, documento in conn.execute(
                "SELECT tipo, documento FROM alerta WHERE status != 'resolvido' AND tipo IN ({})".format(
                    ",".join("?" * len(tipos))
                ),
                tipos,
            ).fetchall()
        }
    novos: list[Alerta] = []
    for alerta in candidatos:
        if (alerta.tipo, alerta.documento) not in ja_sinalizados:
            novos.append(alerta)
            ja_sinalizados.add((alerta.tipo, alerta.documento))

    agora = datetime.now(timezone.utc).isoformat()
    for alerta in novos:
        conn.execute(
            """
            INSERT INTO alerta (tipo, gravidade, chave_ted, documento, descricao, status, data_identificacao)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (alerta.tipo, alerta.gravidade, alerta.chave_ted, alerta.documento,
             alerta.descricao, alerta.status, agora),
        )
    conn.commit()
    return novos


def sincronizar_alertas_conciliacao_simec(conn: sqlite3.Connection) -> list[Alerta]:
    """Grava os alertas de conciliação que ainda não estão abertos para o mesmo TED. Devolve só
    os recém-criados. Nunca fecha um alerta — se a diferença deixar de existir numa
    importação futura, o alerta continua até tratamento humano (mesma regra dos demais)."""

    return _gravar_alertas_novos(
        conn, gerar_alertas_conciliacao_simec(_carregar_resumos_conciliacao(conn))
    )


# --------------------------------------------------------------------------------------
# Validações cadastrais e de vigência do TED (briefing, seção 7)
# --------------------------------------------------------------------------------------

TIPO_TED_VIGENCIA_INVERTIDA = "ted_vigencia_invertida"
TIPO_TED_SEM_UG_DESCENTRALIZADORA = "ted_sem_ug_descentralizadora"
TIPO_SIAFI_EM_MULTIPLOS_TEDS = "siafi_em_multiplos_teds"
TIPO_DOCUMENTO_FORA_DA_VIGENCIA = "documento_fora_da_vigencia"
TIPO_TED_VENCIDO_EM_EXECUCAO = "ted_vencido_em_execucao"
TIPO_TED_SEM_MOVIMENTACAO = "ted_sem_movimentacao"
TIPO_TED_SEM_SIAFI = "ted_sem_siafi"

#: Prazo padrão de "TED em execução sem movimentação" (briefing, seção 7, não define o prazo — 90 dias
#: definidos com o usuário em 24/09/2026, ajustável por parâmetro; era 180 por escolha inicial). Movimentação = NC ou PF emitida
#: e, desde 08/10/2026, liquidação/pagamento no Tesouro em NE vinculada (a NE em si não entra porque
#: `vinculo_ne` não guarda data de emissão).
PRAZO_SEM_MOVIMENTACAO_DIAS = 90

#: Único estado tratado como "em execução" (texto exato da extração real do SIMEC, comparado sem
#: acento e sem diferença de caixa). Os demais estados (prestação de contas, diligência,
#: comprovado etc.) NÃO são tratados como execução — regra confirmada apenas pelos valores vistos
#: na extração; um estado novo do SIMEC não gera alerta até ser classificado.
ESTADO_EM_EXECUCAO = "termo em execucao"


def _sem_acento_minusculo(texto: str | None) -> str:
    if not texto:
        return ""
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).strip().lower()


def estado_em_execucao(estado_atual: str | None) -> bool:
    return _sem_acento_minusculo(estado_atual) == ESTADO_EM_EXECUCAO


#: Trechos (sem acento, minúsculos) que marcam um TED encerrado — comprovado, finalizado, em prestação de
#: contas ou relatório de cumprimento (spec de 08/10/2026, §3.5). Só muda a DESCRIÇÃO do crédito sem
#: empenho; nenhuma regra deixa de valer por causa disso.
TRECHOS_ESTADO_ENCERRADO = ("comprovado", "finalizado", "prestacao de contas", "relatorio de cumprimento")


def ted_encerrado(estado_atual: str | None) -> bool:
    estado = _sem_acento_minusculo(estado_atual)
    return any(trecho in estado for trecho in TRECHOS_ESTADO_ENCERRADO)


@dataclass(frozen=True)
class TedCadastro:
    chave_ted: str
    ted: str
    codigo_siafi: str
    estado_atual: str | None
    inicio_vigencia: date | None
    fim_vigencia: date | None
    ug_descentralizadora: str | None


@dataclass(frozen=True)
class DocumentoDatado:
    """NC ou PF já reduzido ao que a validação de vigência precisa."""

    tipo_documento: str  # "NC" | "PF"
    chave_documento: str
    numero: str
    chave_ted: str
    data_emissao: date | None


def _data_br(valor: date) -> str:
    return valor.strftime("%d/%m/%Y")


def gerar_alertas_cadastrais(
    teds: list[TedCadastro],
    documentos: list[DocumentoDatado],
    hoje: date,
    prazo_sem_movimentacao_dias: int = PRAZO_SEM_MOVIMENTACAO_DIAS,
    ultima_execucao_tesouro: dict[str, date] | None = None,
    movimento_consolidado_no_ano: set[str] | None = None,
) -> list[Alerta]:
    """Todas as verificações são descritivas: apontam a inconsistência sem alterar, excluir ou
    deixar de importar nada. Documento fora da vigência pode ser legítimo (briefing, seção 7),
    por isso gera alerta com justificativa possível, nunca exclusão.

    Sem movimentação (regra revista em 08/10/2026, spec
    `docs/superpowers/specs/2026-10-08-teds-alertas-e-controle-nc-design.md`, §3.4):
      * `ultima_execucao_tesouro` — chave_ted → último dia do mês mais recente com liquidado ou pago ≠ 0
        no Tesouro em NE vinculada não descartada; conta como movimentação junto com NC/PF emitida (o
        TED 10782 aparecia "sem movimento desde 2021" com execução no Tesouro). Data além de `hoje`
        (mês corrente) conta como `hoje`;
      * `movimento_consolidado_no_ano` — chave_ted com NC ou PF ≠ 0 no ano de `hoje` em `execucao_anual`;
        sem documento datado nesse ano, a descrição avisa e o alerta continua."""

    alertas: list[Alerta] = []
    por_chave = {t.chave_ted: t for t in teds}

    for t in sorted(teds, key=lambda x: x.chave_ted):
        rotulo = f"TED {t.ted} (SIAFI {t.codigo_siafi})"
        if t.inicio_vigencia and t.fim_vigencia and t.inicio_vigencia > t.fim_vigencia:
            alertas.append(Alerta(
                tipo=TIPO_TED_VIGENCIA_INVERTIDA, gravidade="alta", documento=t.chave_ted,
                chave_ted=t.chave_ted,
                descricao=(
                    f"{rotulo}: início da vigência ({_data_br(t.inicio_vigencia)}) é posterior ao "
                    f"fim ({_data_br(t.fim_vigencia)}). Cadastro inconsistente na origem."
                ),
            ))
        if not (t.ug_descentralizadora or "").strip():
            alertas.append(Alerta(
                tipo=TIPO_TED_SEM_UG_DESCENTRALIZADORA, gravidade="media", documento=t.chave_ted,
                chave_ted=t.chave_ted,
                descricao=f"{rotulo}: UG descentralizadora ausente no cadastro.",
            ))
        if (
            estado_em_execucao(t.estado_atual)
            and t.fim_vigencia is not None
            and hoje > t.fim_vigencia
        ):
            alertas.append(Alerta(
                tipo=TIPO_TED_VENCIDO_EM_EXECUCAO, gravidade="media", documento=t.chave_ted,
                chave_ted=t.chave_ted,
                descricao=(
                    f"{rotulo}: vigência encerrada em {_data_br(t.fim_vigencia)}, mas o estado "
                    f"atual ainda é \"{t.estado_atual}\". Conferir prorrogação ou encerramento."
                ),
            ))

    ultima_movimentacao: dict[str, date] = {}
    teds_com_documento_no_ano: set[str] = set()
    for d in documentos:
        if d.data_emissao is not None and d.data_emissao <= hoje:
            atual = ultima_movimentacao.get(d.chave_ted)
            if atual is None or d.data_emissao > atual:
                ultima_movimentacao[d.chave_ted] = d.data_emissao
        if d.data_emissao is not None and d.data_emissao.year == hoje.year:
            teds_com_documento_no_ano.add(d.chave_ted)
    ultimo_tesouro = {
        chave: min(data, hoje) for chave, data in (ultima_execucao_tesouro or {}).items()
    }
    for t in sorted(teds, key=lambda x: x.chave_ted):
        if not estado_em_execucao(t.estado_atual):
            continue
        # Sem nenhum documento datado, a referência é o início da vigência: um TED recém-iniciado
        # ainda não é "sem movimentação". Sem documento e sem início, não há como datar: alerta.
        ultima = ultima_movimentacao.get(t.chave_ted)
        tesouro = ultimo_tesouro.get(t.chave_ted)
        mais_recente = max((d for d in (ultima, tesouro) if d is not None), default=None)
        referencia = mais_recente or t.inicio_vigencia
        if referencia is not None and (hoje - referencia).days <= prazo_sem_movimentacao_dias:
            continue
        if ultima is not None:
            detalhe = f"última NC/PF emitida em {_data_br(ultima)}"
        elif t.inicio_vigencia is not None:
            detalhe = f"nenhuma NC/PF emitida desde o início da vigência ({_data_br(t.inicio_vigencia)})"
        else:
            detalhe = "nenhuma NC/PF emitida e sem data de início da vigência"
        if tesouro is not None:
            detalhe += f"; última liquidação/pagamento no Tesouro em NE vinculada em {_data_br(tesouro)}"
        aviso = ""
        if (
            t.chave_ted in (movimento_consolidado_no_ano or set())
            and t.chave_ted not in teds_com_documento_no_ano
        ):
            aviso = (
                f" Atenção: o consolidado indica movimentação em {hoje.year} que não está nos "
                "documentos importados."
            )
        alertas.append(Alerta(
            tipo=TIPO_TED_SEM_MOVIMENTACAO, gravidade="media", documento=t.chave_ted, chave_ted=t.chave_ted,
            descricao=(
                f"TED {t.ted} (SIAFI {t.codigo_siafi}) em execução sem movimentação há mais de "
                f"{prazo_sem_movimentacao_dias} dias: {detalhe}. Movimentação = NC ou PF emitida, ou "
                "liquidação/pagamento no Tesouro em NE vinculada (último dia do mês de lançamento)."
                f"{aviso}"
            ),
        ))

    teds_por_siafi: dict[str, set[str]] = {}
    for t in teds:
        teds_por_siafi.setdefault(t.codigo_siafi, set()).add(t.ted)
    for siafi, numeros in sorted(teds_por_siafi.items()):
        if len(numeros) > 1:
            alertas.append(Alerta(
                tipo=TIPO_SIAFI_EM_MULTIPLOS_TEDS, gravidade="alta", documento=siafi,
                descricao=(
                    f"Código SIAFI {siafi} associado a {len(numeros)} TEDs diferentes: "
                    f"{', '.join(sorted(numeros))}. Sem justificativa registrada."
                ),
            ))

    for d in sorted(documentos, key=lambda x: (x.tipo_documento, x.chave_documento)):
        t = por_chave.get(d.chave_ted)
        if t is None or d.data_emissao is None:
            continue
        if t.inicio_vigencia and d.data_emissao < t.inicio_vigencia:
            posicao, limite = "antes do início", t.inicio_vigencia
        elif t.fim_vigencia and d.data_emissao > t.fim_vigencia:
            posicao, limite = "depois do fim", t.fim_vigencia
        else:
            continue
        alertas.append(Alerta(
            tipo=TIPO_DOCUMENTO_FORA_DA_VIGENCIA, gravidade="media",
            documento=f"{d.tipo_documento}|{d.chave_documento}", chave_ted=d.chave_ted,
            descricao=(
                f"{d.tipo_documento} {d.numero} do TED {t.ted} emitida em {_data_br(d.data_emissao)}, "
                f"{posicao} da vigência ({_data_br(limite)}). Pode ser legítimo em casos "
                "específicos — registrar justificativa se for o caso."
            ),
        ))
    return alertas


def gerar_alertas_ted_sem_siafi(linhas: list[tuple[str, str]]) -> list[Alerta]:
    """`linhas` = (número do TED, motivo da rejeição) das linhas de TED SEM código SIAFI lidas da
    Execução Anual. O SIAFI compõe a chave do TED (`chave_ted`), então a linha não é gravada e o
    TED fica fora de todos os totais até uma extração trazer o SIAFI — o alerta torna isso visível
    em vez de deixar só uma linha rejeitada num resultado de importação."""

    return [
        Alerta(
            tipo=TIPO_TED_SEM_SIAFI, gravidade="media", documento=f"ted:{ted}", chave_ted=None,
            descricao=(
                f"{motivo}. A linha NÃO foi importada: o SIAFI faz parte da chave do TED, então ele fica "
                "fora de todos os totais até uma extração trazer o código."
            ),
        )
        for ted, motivo in sorted(set(linhas))
    ]


def registrar_alertas_ted_sem_siafi(conn: sqlite3.Connection, linhas: list[tuple[str, str]]) -> list[Alerta]:
    """Grava os alertas de TED sem SIAFI ainda não sinalizados. Nunca fecha alerta existente."""

    return _gravar_alertas_novos(conn, gerar_alertas_ted_sem_siafi(linhas))


def _data_ou_none(texto: str | None) -> date | None:
    if not texto:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def _carregar_ultima_execucao_tesouro(conn: sqlite3.Connection) -> dict[str, date]:
    """chave_ted → último dia do mês mais recente com liquidado ou pago ≠ 0 em `execucao_tg`, numa NE
    vinculada ao TED e não descartada (spec de 08/10/2026, §3.4). A comparação com zero é feita em
    `Decimal` (o banco guarda texto); valor nulo não conta como movimento."""

    nes_por_ted: dict[str, set[str]] = {}
    for chave, numero_ne in conn.execute(
        "SELECT chave_ted, numero_ne FROM vinculo_ne WHERE status_validacao != ?", (STATUS_DESCARTADO,)
    ).fetchall():
        nes_por_ted.setdefault(chave, set()).add(numero_ne)

    ultimo_mes_por_ne: dict[str, tuple[int, int]] = {}
    for numero_ne, liquidado, pago, ano, mes in conn.execute(
        "SELECT numero_completo_ne, liquidado, pago, ano_lancamento, mes_lancamento FROM execucao_tg"
    ).fetchall():
        if not any(v is not None and texto_para_valor(v) != 0 for v in (liquidado, pago)):
            continue
        atual = ultimo_mes_por_ne.get(numero_ne)
        if atual is None or (ano, mes) > atual:
            ultimo_mes_por_ne[numero_ne] = (ano, mes)

    resultado: dict[str, date] = {}
    for chave, nes in nes_por_ted.items():
        meses = [ultimo_mes_por_ne[ne] for ne in nes if ne in ultimo_mes_por_ne]
        if meses:
            ano, mes = max(meses)
            resultado[chave] = date(ano, mes, calendar.monthrange(ano, mes)[1])
    return resultado


def _carregar_movimento_consolidado_no_ano(conn: sqlite3.Connection, ano: int) -> set[str]:
    """chave_ted com NC ou PF ≠ 0 em `execucao_anual` no ano dado (qualquer das quatro colunas brutas:
    descentralização, devolução de NC, repasse, devolução de PF — devolução também é movimento)."""

    resultado: set[str] = set()
    for chave, *valores in conn.execute(
        "SELECT chave_ted, total_nc_descentralizacao, total_nc_devolucao, total_pf_repasse, "
        "total_pf_devolucao FROM execucao_anual WHERE ano_emissao = ?",
        (ano,),
    ).fetchall():
        if any(v is not None and texto_para_valor(v) != 0 for v in valores):
            resultado.add(chave)
    return resultado


def _carregar_cadastro(
    conn: sqlite3.Connection, hoje: date | None = None
) -> tuple[list[TedCadastro], list[DocumentoDatado], dict[str, date], set[str]]:
    """Cadastro, documentos datados e — desde 08/10/2026 (spec, §3.4) — a última execução no Tesouro por
    TED e os TEDs com movimento no consolidado no ano de `hoje`."""

    hoje = hoje or date.today()
    teds = [
        TedCadastro(chave_ted, ted, siafi, estado, _data_ou_none(ini), _data_ou_none(fim), ug)
        for chave_ted, ted, siafi, estado, ini, fim, ug in conn.execute(
            "SELECT chave_ted, ted, codigo_siafi, estado_atual, inicio_vigencia, fim_vigencia, "
            "ug_descentralizadora FROM ted"
        ).fetchall()
    ]
    documentos = [
        DocumentoDatado("NC", chave, numero, chave_ted, _data_ou_none(data))
        for chave, numero, chave_ted, data in conn.execute(
            "SELECT chave_nc_documento, numero_nc, chave_ted, data_emissao FROM documento_nc "
            "WHERE chave_ted IS NOT NULL"
        ).fetchall()
    ] + [
        DocumentoDatado("PF", f"{chave_ted}|{ug}|{numero}", numero, chave_ted, _data_ou_none(data))
        for chave_ted, ug, numero, data in conn.execute(
            "SELECT chave_ted, ug_emitente, numero_pf, data_emissao FROM documento_pf"
        ).fetchall()
    ]
    return (
        teds,
        documentos,
        _carregar_ultima_execucao_tesouro(conn),
        _carregar_movimento_consolidado_no_ano(conn, hoje.year),
    )


def sincronizar_alertas_cadastrais(
    conn: sqlite3.Connection,
    hoje: date | None = None,
    prazo_sem_movimentacao_dias: int = PRAZO_SEM_MOVIMENTACAO_DIAS,
) -> list[Alerta]:
    """Grava as validações cadastrais/de vigência ainda não sinalizadas. `hoje` e o prazo são
    injetáveis para teste. Nunca fecha alerta existente."""

    hoje = hoje or date.today()
    teds, documentos, ultima_execucao_tesouro, movimento_no_ano = _carregar_cadastro(conn, hoje)
    return _gravar_alertas_novos(
        conn,
        gerar_alertas_cadastrais(
            teds, documentos, hoje, prazo_sem_movimentacao_dias,
            ultima_execucao_tesouro=ultima_execucao_tesouro,
            movimento_consolidado_no_ano=movimento_no_ano,
        ),
    )


# --------------------------------------------------------------------------------------
# Fechamento de alertas obsoletos dos tipos revistos (spec de 08/10/2026, §4)
# --------------------------------------------------------------------------------------
#: Tipos cujas regras foram revistas em 08/10/2026 (conciliação pela janela comum e "sem base", um alerta de
#: UG por TED, movimentação com Tesouro). Só estes podem ser fechados pela reavaliação; os demais nunca.
TIPOS_REVISTOS_08_10_2026 = frozenset({
    TIPO_NC_DIVERGE_CONSOLIDADO,
    TIPO_PF_DIVERGE_CONSOLIDADO,
    TIPO_PF_MAIOR_QUE_NC,
    TIPO_NC_UG_EMITENTE_AUSENTE,
    TIPO_TED_SEM_MOVIMENTACAO,
})

_MOTIVO_COMPARACAO = (
    "a comparação passou a usar só o período coberto pelo consolidado; TED sem documento no extrato é 'sem base'"
)
_MOTIVOS_FECHAMENTO = {
    TIPO_NC_DIVERGE_CONSOLIDADO: _MOTIVO_COMPARACAO,
    TIPO_PF_DIVERGE_CONSOLIDADO: _MOTIVO_COMPARACAO,
    TIPO_PF_MAIOR_QUE_NC: "TED com vigência anterior ao consolidado é 'sem base'",
    TIPO_NC_UG_EMITENTE_AUSENTE: "o alerta passou a ser um por TED",
    TIPO_TED_SEM_MOVIMENTACAO: "a movimentação passou a incluir liquidação e pagamento no Tesouro",
}


def candidatos_tipos_revistos(conn: sqlite3.Connection, hoje: date | None = None) -> set[tuple[str, str]]:
    """`(tipo, documento)` que as regras ATUAIS produzem para os tipos revistos, sem gravar nada — a base
    para decidir quais alertas abertos desses tipos ficaram obsoletos."""

    hoje = hoje or date.today()
    candidatos = list(gerar_alertas_conciliacao_simec(_carregar_resumos_conciliacao(conn)))
    candidatos += gerar_alertas_nc_parcial(detectar_documentos_nc_parciais(_carregar_documentos_nc(conn)))
    teds, documentos, ultima_execucao_tesouro, movimento_no_ano = _carregar_cadastro(conn, hoje)
    candidatos += gerar_alertas_cadastrais(
        teds, documentos, hoje,
        ultima_execucao_tesouro=ultima_execucao_tesouro,
        movimento_consolidado_no_ano=movimento_no_ano,
    )
    return {(a.tipo, a.documento) for a in candidatos if a.tipo in TIPOS_REVISTOS_08_10_2026}


def fechar_alertas_obsoletos(
    conn: sqlite3.Connection, candidatos_atuais: set[tuple[str, str]]
) -> dict[str, int]:
    """Fecha (`resolvido`, responsável "sistema") cada alerta NÃO resolvido de tipo revisto cujo
    `(tipo, documento)` não está em `candidatos_atuais`. Decisão de 08/10/2026 (spec §4): as regras foram
    revistas e os alertas gerados pelas regras antigas não se sustentam; deixar para análise manual
    arrastaria falsos positivos. Cada fechamento grava `alerta_status_alterado` na MESMA transação
    (ou status e trilha persistem juntos, ou nenhum). Alertas `em_analise` dos tipos revistos também são fechados. Resolvido manualmente nunca é tocado; tipo não
    revisto nunca é fechado. Devolve a contagem por tipo."""

    tipos = sorted(TIPOS_REVISTOS_08_10_2026)
    abertos = conn.execute(
        "SELECT id, tipo, documento, status, responsavel, justificativa FROM alerta "
        "WHERE status != 'resolvido' AND tipo IN ({}) ORDER BY id".format(",".join("?" * len(tipos))),
        tipos,
    ).fetchall()
    fechados: dict[str, int] = {}
    agora = datetime.now(timezone.utc).isoformat()
    try:
        for alerta_id, tipo, documento, status, responsavel, justificativa in abertos:
            if (tipo, documento) in candidatos_atuais:
                continue
            motivo = _MOTIVOS_FECHAMENTO[tipo]
            nova_justificativa = "Regra revisada em 08/10/2026: " + motivo
            conn.execute(
                "UPDATE alerta SET status = 'resolvido', responsavel = 'sistema', justificativa = ?, "
                "data_resolucao = ? WHERE id = ?",
                (nova_justificativa, agora, alerta_id),
            )
            registrar_auditoria(
                conn, acao=ACAO_ALERTA_STATUS_ALTERADO, entidade=ENTIDADE_ALERTA, entidade_id=alerta_id,
                valor_anterior={"status": status, "responsavel": responsavel, "justificativa": justificativa},
                valor_novo={"status": "resolvido", "responsavel": "sistema", "justificativa": nova_justificativa},
                usuario="sistema", motivo=motivo, origem="reavaliacao",
            )
            fechados[tipo] = fechados.get(tipo, 0) + 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return dict(sorted(fechados.items()))


# --------------------------------------------------------------------------------------
# Execução no Tesouro Gerencial por NE (briefing, seções 8.2 e 10)
# --------------------------------------------------------------------------------------

TIPO_NE_LIQUIDADO_MAIOR_QUE_EMPENHADO = "ne_liquidado_maior_que_empenhado"
TIPO_NE_PAGO_MAIOR_QUE_LIQUIDADO = "ne_pago_maior_que_liquidado"
TIPO_NE_SIMEC_DIFERE_TESOURO = "ne_simec_difere_tesouro"


@dataclass(frozen=True)
class TotalTesouroNE:
    """Soma de TODOS os meses sincronizados de uma NE em `execucao_tg` (movimentos mensais,
    estornos com sinal). Comparar o acumulado — e não mês a mês — evita alerta falso quando a
    liquidação ou o pagamento é lançado num mês diferente do empenho."""

    numero_ne: str
    empenhado: Decimal
    liquidado: Decimal
    pago: Decimal
    #: valor ORIGINAL da NE no Tesouro = primeiro movimento de empenho não nulo (os meses seguintes são
    #: reforços e anulações). `None` quando não dá para observar: NE de exercício anterior ao início da
    #: Execução Mensal, cujo primeiro movimento visível já seria um reforço (ver `_carregar_execucao_tg`).
    original: Decimal | None = None
    mes_original: tuple[int, int] | None = None


@dataclass(frozen=True)
class VinculoSimec:
    chave_ted: str
    chave_empenho: str
    numero_ne: str
    valor_ne: Decimal


def gerar_alertas_execucao_tg(
    vinculos: list[VinculoSimec],
    totais: dict[str, TotalTesouroNE],
    tolerancia: Decimal = TOLERANCIA_CONCILIACAO,
) -> list[Alerta]:
    """Só NEs vinculadas a algum TED e com dado no Tesouro Gerencial; NE sem linha em
    `execucao_tg` (ex.: exercício anterior à Execução Mensal) é "sem base", nunca zero.

    O "Valor da NE" do SIMEC é o valor ORIGINAL da NE (confirmado pelo usuário em 24/09/2026), então não
    deve ser comparado só com o empenhado ACUMULADO do Tesouro (original + reforços − anulações). O valor
    do SIMEC está EXPLICADO se bate com o original OU com o líquido atual (na extração real há NEs cujo
    SIMEC já foi atualizado). O alerta `ne_simec_difere_tesouro` só sai quando não bate com nenhum dos dois
    — e só se o original é observável (`original is not None`)."""

    alertas: list[Alerta] = []
    teds_por_ne: dict[str, set[str]] = {}
    for v in vinculos:
        teds_por_ne.setdefault(v.numero_ne, set()).add(v.chave_ted)

    for numero_ne in sorted(teds_por_ne):
        total = totais.get(numero_ne)
        if total is None:
            continue
        teds = teds_por_ne[numero_ne]
        chave_ted = next(iter(teds)) if len(teds) == 1 else None
        if total.liquidado - total.empenhado > tolerancia:
            alertas.append(Alerta(
                tipo=TIPO_NE_LIQUIDADO_MAIOR_QUE_EMPENHADO, gravidade="alta", documento=numero_ne,
                chave_ted=chave_ted,
                descricao=(
                    f"NE {numero_ne}: liquidado acumulado ({_moeda(total.liquidado)}) maior que o empenhado "
                    f"acumulado ({_moeda(total.empenhado)}) no Tesouro Gerencial, excesso de "
                    f"{_moeda(total.liquidado - total.empenhado)}."
                ),
            ))
        if total.pago - total.liquidado > tolerancia:
            alertas.append(Alerta(
                tipo=TIPO_NE_PAGO_MAIOR_QUE_LIQUIDADO, gravidade="alta", documento=numero_ne,
                chave_ted=chave_ted,
                descricao=(
                    f"NE {numero_ne}: pago acumulado ({_moeda(total.pago)}) maior que o liquidado "
                    f"acumulado ({_moeda(total.liquidado)}) no Tesouro Gerencial, excesso de "
                    f"{_moeda(total.pago - total.liquidado)}."
                ),
            ))

    for v in sorted(vinculos, key=lambda x: (x.numero_ne, x.chave_ted)):
        total = totais.get(v.numero_ne)
        if total is None or total.original is None:
            continue  # sem base: o valor original não é observável
        if abs(v.valor_ne - total.original) <= tolerancia or abs(v.valor_ne - total.empenhado) <= tolerancia:
            continue  # explicado: bate com o original ou com o líquido atual
        mes = f"{total.mes_original[1]:02d}/{total.mes_original[0]}" if total.mes_original else "—"
        alertas.append(Alerta(
            tipo=TIPO_NE_SIMEC_DIFERE_TESOURO, gravidade="alta",
            documento=f"{v.chave_ted}|{v.chave_empenho}", chave_ted=v.chave_ted,
            descricao=(
                f"NE {v.numero_ne} no TED {v.chave_ted}: o valor no SIMEC ({_moeda(v.valor_ne)}) não bate nem "
                f"com o valor original no Tesouro Gerencial ({_moeda(total.original)}, primeiro empenho em "
                f"{mes}) nem com o líquido atual ({_moeda(total.empenhado)}, após reforços e anulações). "
                f"Diferença para o original: {_moeda(v.valor_ne - total.original)}. Possíveis causas: valor "
                "digitado errado no SIMEC, NE de outro processo ou extrações de datas diferentes — não "
                "decidido automaticamente."
            ),
        ))
    return alertas


def _carregar_execucao_tg(conn: sqlite3.Connection) -> tuple[list[VinculoSimec], dict[str, TotalTesouroNE]]:
    vinculos = [
        VinculoSimec(chave_ted, chave_empenho, numero_ne, texto_para_valor(valor_ne))
        for chave_ted, chave_empenho, numero_ne, valor_ne in conn.execute(
            "SELECT chave_ted, chave_empenho, numero_ne, valor_ne FROM vinculo_ne WHERE status_validacao != ?",
            (STATUS_DESCARTADO,),
        ).fetchall()
    ]
    somas: dict[str, list[Decimal]] = {}
    primeiro: dict[str, tuple[int, int, Decimal]] = {}
    ano_inicial_da_base: int | None = None
    for numero_ne, empenhado, liquidado, pago, ano, mes in conn.execute(
        "SELECT numero_completo_ne, empenhado, liquidado, pago, ano_lancamento, mes_lancamento "
        "FROM execucao_tg ORDER BY ano_lancamento, mes_lancamento"
    ).fetchall():
        ano_inicial_da_base = ano if ano_inicial_da_base is None else min(ano_inicial_da_base, ano)
        acumulado = somas.setdefault(numero_ne, [Decimal("0"), Decimal("0"), Decimal("0")])
        for i, valor in enumerate((empenhado, liquidado, pago)):
            if valor is not None:
                acumulado[i] += texto_para_valor(valor)
        if numero_ne not in primeiro and empenhado is not None and texto_para_valor(empenhado) != 0:
            primeiro[numero_ne] = (ano, mes, texto_para_valor(empenhado))

    totais: dict[str, TotalTesouroNE] = {}
    for ne, valores in somas.items():
        # O "original" só é observável se a NE é do primeiro ano da base em diante: NE mais antiga tem o
        # empenho inicial fora da Execução Mensal, e o primeiro movimento visível seria um reforço.
        try:
            ano_da_ne = int(ne[:4])
        except ValueError:
            ano_da_ne = None
        observavel = ano_da_ne is not None and ano_inicial_da_base is not None and ano_da_ne >= ano_inicial_da_base
        if not observavel:
            original, mes_original = None, None
        elif ne in primeiro:
            original, mes_original = primeiro[ne][2], primeiro[ne][:2]
        else:
            original, mes_original = Decimal("0"), None  # base cobre a NE e ela nunca teve empenho
        totais[ne] = TotalTesouroNE(ne, *valores, original=original, mes_original=mes_original)
    return vinculos, totais


def sincronizar_alertas_execucao_tg(conn: sqlite3.Connection) -> list[Alerta]:
    """Grava os alertas de execução por NE ainda não sinalizados. Nunca fecha alerta existente."""

    vinculos, totais = _carregar_execucao_tg(conn)
    return _gravar_alertas_novos(conn, gerar_alertas_execucao_tg(vinculos, totais))


# --------------------------------------------------------------------------------------
# Crédito sem empenho e repasse sem execução financeira (briefing, seções 8.2 e 9.3)
# --------------------------------------------------------------------------------------

TIPO_TED_CREDITO_SEM_EMPENHO = "ted_credito_sem_empenho"
TIPO_TED_PF_SEM_EXECUCAO_FINANCEIRA = "ted_pf_sem_execucao_financeira"

#: Prazo padrão das duas regras abaixo (o briefing manda "prazo configurável" e não o define; 90 dias
#: definido com o usuário em 24/09/2026, ajustável por parâmetro).
PRAZO_SEM_EXECUCAO_DIAS = 90


@dataclass(frozen=True)
class ExecucaoDoTed:
    """Tudo que as duas regras precisam de um TED, já reduzido.

    `nc_liquida`/`pf_liquida` vêm do consolidado (`execucao_anual`, todos os exercícios).
    `qtd_nes_ativas` conta NEs vinculadas que NÃO foram descartadas por decisão humana.
    `pago_tesouro` é o pago acumulado, no Tesouro Gerencial, das NEs ativas que têm dado lá;
    `None` = nenhuma delas tem dado no Tesouro ("sem base", nunca zero)."""

    chave_ted: str
    ted: str
    codigo_siafi: str
    estado_atual: str | None
    inicio_vigencia: date | None
    nc_liquida: Decimal
    pf_liquida: Decimal
    ultima_nc_descentralizacao: date | None
    ultimo_pf_repasse: date | None
    qtd_nes_ativas: int
    pago_tesouro: Decimal | None


def _dias_desde(referencia: date | None, hoje: date) -> int | None:
    return None if referencia is None else (hoje - referencia).days


def gerar_alertas_execucao_do_ted(
    teds: list[ExecucaoDoTed],
    hoje: date,
    prazo_dias: int = PRAZO_SEM_EXECUCAO_DIAS,
    tolerancia: Decimal = TOLERANCIA_CONCILIACAO,
) -> list[Alerta]:
    """Duas verificações, ambas descritivas (não decidem nada, não excluem nada).

    1. CRÉDITO SEM EMPENHO — NC líquida positiva e NENHUMA NE ativa vinculada ao TED, passado o prazo
       desde a última NC de descentralização (sem NC datada, desde o início da vigência). Vale para
       qualquer estado do TED: NE ausente pode ser erro de inserção no SIMEC (a NE não foi lançada).
       A NE não tem data no banco, então o prazo conta a partir da NC.
    2. REPASSE SEM EXECUÇÃO FINANCEIRA — TED EM EXECUÇÃO com PF líquido positivo, NEs ativas com dado no
       Tesouro Gerencial e pago acumulado zero nelas, passado o prazo desde o último PF de repasse.
       "Execução financeira" = pago no Tesouro (definido com o usuário)."""

    alertas: list[Alerta] = []
    for t in sorted(teds, key=lambda x: x.chave_ted):
        rotulo = f"TED {t.ted} (SIAFI {t.codigo_siafi})"

        if t.nc_liquida > tolerancia and t.qtd_nes_ativas == 0:
            referencia = t.ultima_nc_descentralizacao or t.inicio_vigencia
            dias = _dias_desde(referencia, hoje)
            if dias is None or dias > prazo_dias:
                origem = (
                    f"última NC de descentralização em {_data_br(t.ultima_nc_descentralizacao)}"
                    if t.ultima_nc_descentralizacao
                    else (
                        f"sem NC datada; início da vigência em {_data_br(t.inicio_vigencia)}"
                        if t.inicio_vigencia else "sem NC datada e sem início da vigência"
                    )
                )
                base = (
                    f"{rotulo}: NC líquida de {_moeda(t.nc_liquida)} e nenhuma NE vinculada há mais de "
                    f"{prazo_dias} dias ({origem})."
                )
                if ted_encerrado(t.estado_atual):
                    # Descrição separada para TED encerrado (decisão de 08/10/2026, spec, §3.5): a regra é
                    # a mesma, mas o que o usuário faz com o alerta é diferente.
                    descricao = (
                        f"{base} Estado atual: {t.estado_atual}. NE não registrada no SIMEC — pendência "
                        "para a prestação de contas."
                    )
                else:
                    descricao = (
                        f"{base} Pode ser NE não lançada no SIMEC — conferir na origem. "
                        f"Estado atual: {t.estado_atual or '—'}."
                    )
                alertas.append(Alerta(
                    tipo=TIPO_TED_CREDITO_SEM_EMPENHO, gravidade="alta", documento=t.chave_ted,
                    chave_ted=t.chave_ted, descricao=descricao,
                ))

        if (
            estado_em_execucao(t.estado_atual)
            and t.pf_liquida > tolerancia
            and t.qtd_nes_ativas > 0
            and t.pago_tesouro is not None
            and t.pago_tesouro <= tolerancia
        ):
            referencia = t.ultimo_pf_repasse or t.inicio_vigencia
            dias = _dias_desde(referencia, hoje)
            if dias is None or dias > prazo_dias:
                origem = (
                    f"último PF de repasse em {_data_br(t.ultimo_pf_repasse)}"
                    if t.ultimo_pf_repasse
                    else (f"sem PF datado; início da vigência em {_data_br(t.inicio_vigencia)}"
                          if t.inicio_vigencia else "sem PF datado e sem início da vigência")
                )
                alertas.append(Alerta(
                    tipo=TIPO_TED_PF_SEM_EXECUCAO_FINANCEIRA, gravidade="media", documento=t.chave_ted,
                    chave_ted=t.chave_ted,
                    descricao=(
                        f"{rotulo}: PF líquido de {_moeda(t.pf_liquida)} repassado e nenhum pagamento no "
                        f"Tesouro Gerencial nas NEs vinculadas há mais de {prazo_dias} dias ({origem})."
                    ),
                ))
    return alertas


def _carregar_execucao_do_ted(conn: sqlite3.Connection) -> list[ExecucaoDoTed]:
    def _datas(sql: str) -> dict[str, date | None]:
        return {chave: _data_ou_none(dt) for chave, dt in conn.execute(sql).fetchall() if chave}

    consolidado: dict[str, list[Decimal]] = {}
    for chave, descentralizado, repassado in conn.execute(
        "SELECT chave_ted, total_descentralizado, total_repassado FROM execucao_anual"
    ).fetchall():
        acumulado = consolidado.setdefault(chave, [Decimal("0"), Decimal("0")])
        acumulado[0] += texto_para_valor(descentralizado)
        acumulado[1] += texto_para_valor(repassado)

    ultima_nc = _datas(
        "SELECT chave_ted, MAX(data_emissao) FROM documento_nc WHERE operacao = '+' AND data_emissao IS NOT NULL GROUP BY chave_ted"
    )
    ultimo_pf = _datas(
        "SELECT chave_ted, MAX(data_emissao) FROM documento_pf WHERE operacao = '+' AND data_emissao IS NOT NULL GROUP BY chave_ted"
    )

    nes_por_ted: dict[str, set[str]] = {}
    for chave, numero_ne in conn.execute(
        "SELECT chave_ted, numero_ne FROM vinculo_ne WHERE status_validacao != ?", (STATUS_DESCARTADO,)
    ).fetchall():
        nes_por_ted.setdefault(chave, set()).add(numero_ne)

    pago_por_ne: dict[str, Decimal] = {}
    for numero_ne, pago in conn.execute("SELECT numero_completo_ne, pago FROM execucao_tg").fetchall():
        pago_por_ne[numero_ne] = pago_por_ne.get(numero_ne, Decimal("0")) + (
            texto_para_valor(pago) if pago is not None else Decimal("0")
        )

    resultado = []
    for chave, ted, siafi, estado, inicio in conn.execute(
        "SELECT chave_ted, ted, codigo_siafi, estado_atual, inicio_vigencia FROM ted"
    ).fetchall():
        nes = nes_por_ted.get(chave, set())
        com_dado = [ne for ne in nes if ne in pago_por_ne]
        nc_liq, pf_liq = consolidado.get(chave, [Decimal("0"), Decimal("0")])
        resultado.append(ExecucaoDoTed(
            chave_ted=chave, ted=ted, codigo_siafi=siafi, estado_atual=estado,
            inicio_vigencia=_data_ou_none(inicio), nc_liquida=nc_liq, pf_liquida=pf_liq,
            ultima_nc_descentralizacao=ultima_nc.get(chave), ultimo_pf_repasse=ultimo_pf.get(chave),
            qtd_nes_ativas=len(nes),
            pago_tesouro=sum((pago_por_ne[ne] for ne in com_dado), start=Decimal("0")) if com_dado else None,
        ))
    return resultado


def sincronizar_alertas_execucao_do_ted(
    conn: sqlite3.Connection, hoje: date | None = None, prazo_dias: int = PRAZO_SEM_EXECUCAO_DIAS
) -> list[Alerta]:
    """Grava os alertas de crédito sem empenho e de repasse sem execução financeira ainda não
    sinalizados. Nunca fecha alerta existente."""

    return _gravar_alertas_novos(
        conn, gerar_alertas_execucao_do_ted(_carregar_execucao_do_ted(conn), hoje or date.today(), prazo_dias)
    )


# --------------------------------------------------------------------------------------
# Rodapé do relatório × soma calculada (briefing, seção 6.2)
# --------------------------------------------------------------------------------------

TIPO_RODAPE_DIVERGENTE = "importacao_rodape_divergente"


def sincronizar_alertas_rodape(conn: sqlite3.Connection) -> list[Alerta]:
    """Um alerta crítico ("alta") por lote cujo total de rodapé difere da soma calculada em mais
    de R$ 0,01. Só lotes ativos (`status = 'ok'`); lote revertido não gera alerta novo. O lote
    continua importado — o alerta só sinaliza a divergência, quem decide é uma pessoa."""

    candidatos: list[Alerta] = []
    for id_lote, tipo_relatorio, nome_arquivo, diferenca, detalhe in conn.execute(
        "SELECT id, tipo_relatorio, nome_arquivo, diferenca_rodape, detalhe_rodape FROM import_batch "
        "WHERE status = 'ok' AND diferenca_rodape IS NOT NULL ORDER BY id"
    ).fetchall():
        if texto_para_valor(diferenca) <= TOLERANCIA_CONCILIACAO:
            continue
        divergentes = [
            item for item in json.loads(detalhe or "[]")
            if abs(texto_para_valor(item["diferenca"])) > TOLERANCIA_CONCILIACAO
        ]
        campos = "; ".join(
            f"{i['campo']}: rodapé {_moeda(texto_para_valor(i['rodape']))} × calculado "
            f"{_moeda(texto_para_valor(i['calculado']))} (diferença {_moeda(texto_para_valor(i['diferenca']))})"
            for i in divergentes
        )
        candidatos.append(Alerta(
            tipo=TIPO_RODAPE_DIVERGENTE, gravidade="alta", documento=f"lote:{id_lote}",
            descricao=(
                f"Lote #{id_lote} ({tipo_relatorio}, arquivo {nome_arquivo}): o total do rodapé difere da "
                f"soma das linhas importadas em mais de R$ 0,01 — {campos}. Possíveis causas: linha "
                "rejeitada na leitura, arquivo cortado ou rodapé de outra extração. O lote continua "
                "importado; conferir antes de usar os totais."
            ),
        ))
    return _gravar_alertas_novos(conn, candidatos)


# --------------------------------------------------------------------------------------
# Integração com o banco
# --------------------------------------------------------------------------------------

def _carregar_vinculos(conn: sqlite3.Connection) -> list[VinculoNE]:
    linhas = conn.execute(
        "SELECT chave_ted, chave_empenho, numero_ne, valor_ne FROM vinculo_ne"
    ).fetchall()
    return [
        VinculoNE(
            chave_ted=chave_ted,
            chave_empenho=chave_empenho,
            numero_ne=numero_ne,
            valor_ne=texto_para_valor(valor_ne),
        )
        for chave_ted, chave_empenho, numero_ne, valor_ne in linhas
    ]


def carregar_decisoes_vinculo_ne(
    conn: sqlite3.Connection, chave_empenho: str
) -> list[DecisaoVinculoNE]:
    """Histórico append-only das decisões para um empenho, da mais recente à mais antiga."""

    linhas = conn.execute(
        """
        SELECT id, chave_empenho, chave_ted_escolhida, teds_envolvidos, decisao,
               responsavel, justificativa, data_decisao, alerta_id
        FROM decisao_vinculo_ne
        WHERE chave_empenho = ?
        ORDER BY id DESC
        """,
        (chave_empenho,),
    ).fetchall()
    return [
        DecisaoVinculoNE(
            id=id_decisao,
            chave_empenho=chave,
            chave_ted_escolhida=escolhida,
            teds_envolvidos=tuple(json.loads(teds)),
            decisao=decisao,
            responsavel=responsavel,
            justificativa=justificativa,
            data_decisao=data_decisao,
            alerta_id=alerta_id,
        )
        for id_decisao, chave, escolhida, teds, decisao, responsavel, justificativa, data_decisao, alerta_id in linhas
    ]


def teds_vinculados_ao_empenho(conn: sqlite3.Connection, chave_empenho: str) -> list[str]:
    return [
        chave_ted
        for (chave_ted,) in conn.execute(
            "SELECT DISTINCT chave_ted FROM vinculo_ne WHERE chave_empenho = ? ORDER BY chave_ted",
            (chave_empenho,),
        ).fetchall()
    ]


def registrar_decisao_vinculo_ne(
    conn: sqlite3.Connection,
    *,
    alerta_id: int,
    chave_empenho: str,
    chave_ted_escolhida: str,
    responsavel: str,
    justificativa: str,
    origem: str = "interface",
) -> DecisaoVinculoNE:
    """Resolve explicitamente um vínculo múltiplo sem apagar qualquer linha importada."""

    responsavel = responsavel.strip()
    justificativa = justificativa.strip()
    if not responsavel:
        raise ValueError("Informe o responsável pela decisão.")
    if not justificativa:
        raise ValueError("Informe a justificativa da decisão.")

    alerta = conn.execute(
        "SELECT tipo, documento, status FROM alerta WHERE id = ?", (alerta_id,)
    ).fetchone()
    if alerta is None:
        raise ValueError("Alerta não encontrado.")
    tipo, documento, status = alerta
    if tipo != TIPO_EMPENHO_MULTIPLOS_TEDS or documento != chave_empenho:
        raise ValueError("O alerta não corresponde ao vínculo múltiplo informado.")
    if status == "resolvido":
        raise ValueError("Este alerta já foi resolvido.")

    teds = teds_vinculados_ao_empenho(conn, chave_empenho)
    if len(teds) < 2:
        raise ValueError("O empenho não está vinculado a mais de um TED.")
    if chave_ted_escolhida not in teds:
        raise ValueError("O TED escolhido não está entre os vínculos do empenho.")

    agora = datetime.now(timezone.utc).isoformat()
    try:
        status_vinculos_anteriores = dict(
            conn.execute(
                "SELECT chave_ted, status_validacao FROM vinculo_ne WHERE chave_empenho = ?",
                (chave_empenho,),
            ).fetchall()
        )
        alerta_anterior = conn.execute(
            "SELECT status, responsavel, justificativa FROM alerta WHERE id = ?", (alerta_id,)
        ).fetchone()
        conn.execute(
            "UPDATE vinculo_ne SET status_validacao = ? WHERE chave_empenho = ?",
            (STATUS_DESCARTADO, chave_empenho),
        )
        conn.execute(
            """
            UPDATE vinculo_ne SET status_validacao = ?
            WHERE chave_empenho = ? AND chave_ted = ?
            """,
            (STATUS_OK, chave_empenho, chave_ted_escolhida),
        )
        cursor = conn.execute(
            """
            INSERT INTO decisao_vinculo_ne
                (chave_empenho, chave_ted_escolhida, teds_envolvidos, decisao,
                 responsavel, justificativa, data_decisao, alerta_id)
            VALUES (?, ?, ?, 'atribuir_ted', ?, ?, ?, ?)
            """,
            (
                chave_empenho,
                chave_ted_escolhida,
                json.dumps(teds, ensure_ascii=False),
                responsavel,
                justificativa,
                agora,
                alerta_id,
            ),
        )
        conn.execute(
            """
            UPDATE alerta
            SET status = 'resolvido', responsavel = ?, justificativa = ?, data_resolucao = ?
            WHERE id = ?
            """,
            (responsavel, justificativa, agora, alerta_id),
        )
        # Auditoria na MESMA transação da decisão: ou as duas persistem, ou nenhuma.
        status_vinculos_novos = {
            ted: (STATUS_OK if ted == chave_ted_escolhida else STATUS_DESCARTADO) for ted in teds
        }
        registrar_auditoria(
            conn, acao=ACAO_VINCULO_NE_DECIDIDO, entidade=ENTIDADE_VINCULO_NE, entidade_id=chave_empenho,
            valor_anterior={"status_validacao_por_ted": status_vinculos_anteriores},
            valor_novo={"status_validacao_por_ted": status_vinculos_novos, "ted_escolhido": chave_ted_escolhida},
            usuario=responsavel, motivo=justificativa, origem=origem,
        )
        registrar_auditoria(
            conn, acao=ACAO_ALERTA_STATUS_ALTERADO, entidade=ENTIDADE_ALERTA, entidade_id=alerta_id,
            valor_anterior={
                "status": alerta_anterior[0], "responsavel": alerta_anterior[1],
                "justificativa": alerta_anterior[2],
            },
            valor_novo={"status": "resolvido", "responsavel": responsavel, "justificativa": justificativa},
            usuario=responsavel, motivo=justificativa, origem=origem,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return DecisaoVinculoNE(
        id=int(cursor.lastrowid),
        chave_empenho=chave_empenho,
        chave_ted_escolhida=chave_ted_escolhida,
        teds_envolvidos=tuple(teds),
        decisao="atribuir_ted",
        responsavel=responsavel,
        justificativa=justificativa,
        data_decisao=agora,
        alerta_id=alerta_id,
    )


def _decisoes_vigentes(conn: sqlite3.Connection) -> dict[str, DecisaoVinculoNE]:
    chaves = {
        chave
        for (chave,) in conn.execute(
            "SELECT DISTINCT chave_empenho FROM decisao_vinculo_ne"
        ).fetchall()
    }
    return {
        chave: carregar_decisoes_vinculo_ne(conn, chave)[0]
        for chave in chaves
    }


def sincronizar_alertas_multiplos_teds(conn: sqlite3.Connection) -> list[Alerta]:
    """Recalcula `status_validacao` de todos os vínculos e garante um alerta aberto para
    cada empenho pendente. Devolve os alertas recém-criados nesta chamada (não os que já
    existiam)."""

    vinculos = _carregar_vinculos(conn)
    conflitos = detectar_ne_em_multiplos_teds(vinculos)
    decisoes = _decisoes_vigentes(conn)
    pendentes: dict[str, list[VinculoNE]] = {}

    conn.execute(
        "UPDATE vinculo_ne SET status_validacao = ? WHERE status_validacao != ?",
        (STATUS_OK, STATUS_OK),
    )
    for chave_empenho, grupo in conflitos.items():
        teds_atuais = {v.chave_ted for v in grupo}
        decisao = decisoes.get(chave_empenho)
        if (
            decisao is not None
            and set(decisao.teds_envolvidos) == teds_atuais
            and decisao.chave_ted_escolhida in teds_atuais
        ):
            conn.execute(
                "UPDATE vinculo_ne SET status_validacao = ? WHERE chave_empenho = ?",
                (STATUS_DESCARTADO, chave_empenho),
            )
            conn.execute(
                """
                UPDATE vinculo_ne SET status_validacao = ?
                WHERE chave_empenho = ? AND chave_ted = ?
                """,
                (STATUS_OK, chave_empenho, decisao.chave_ted_escolhida),
            )
        else:
            pendentes[chave_empenho] = grupo
            conn.execute(
                "UPDATE vinculo_ne SET status_validacao = ? WHERE chave_empenho = ?",
                (STATUS_PENDENTE, chave_empenho),
            )

    ja_sinalizados = {
        documento
        for (documento,) in conn.execute(
            "SELECT documento FROM alerta WHERE tipo = ? AND status != 'resolvido'",
            (TIPO_EMPENHO_MULTIPLOS_TEDS,),
        ).fetchall()
    }

    novos = [
        alerta
        for alerta in gerar_alertas_ne_multiplos_teds(pendentes)
        if alerta.documento not in ja_sinalizados
    ]

    agora = datetime.now(timezone.utc).isoformat()
    for alerta in novos:
        conn.execute(
            """
            INSERT INTO alerta (tipo, gravidade, chave_ted, documento, descricao, status, data_identificacao)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alerta.tipo,
                alerta.gravidade,
                alerta.chave_ted,
                alerta.documento,
                alerta.descricao,
                alerta.status,
                agora,
            ),
        )
    conn.commit()
    return novos
