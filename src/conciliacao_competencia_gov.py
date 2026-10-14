"""
Linha do tempo por competência de um contrato: Liquidação por Competência (relatório do Tesouro) × instrumentos de
cobrança do Contratos.gov (11/10/2026).

Camada: regra pura (pandas/datetime; sem Streamlit, sem I/O). Somente LEITURA. Pedido do usuário: dentro do cadastro
de cada contrato de Contínuos, seletor de exercício e, mês a mês, a liquidação do relatório e, abaixo, as notas do
gov — os dois quando houver, "sem registro" no que faltar; quando só houver nota, o elemento de despesa do empenho
(o relatório não traz competência dos empenhos de DEA, elemento 92).

Regras (decisões do usuário, 11/10/2026):
  * Todas as NEs do contrato (as do Contratos.gov e a do cadastro) entram no cálculo; a escolha de quais ficam em
    evidência é um FILTRO POR MÊS (`filtrar_mes`), com padrão nas NEs da 20RK (`padrao_do_mes`). O que fica fora do
    filtro é mostrado como valor "fora do filtro" — nada some em silêncio.
  * Notas: só as liquidadas (com data de liquidação); valor por NE (`empenhos`); competência por `referencias`.
    1 competência → o valor de cada NE; 1 NE → o valor de cada competência; várias × várias → rateio proporcional
    (marcado). Nota com mesmo número, valor e NEs de outra do contrato = duplicada: sinalizada e contada uma vez.
  * Relatório e notas NUNCA são somados entre si: aparecem lado a lado, com a diferença.
  * CONCILIAÇÃO DE DUPLICIDADES (`ajustar_mes`, decisão do usuário 11/10/2026): as diferenças costumam ser notas
    canceladas/substituídas cujo cancelamento não foi informado no Contratos.gov. Por NE, quando as notas somam MAIS que
    o relatório, procura-se a MENOR combinação de notas cuja retirada fecha o relatório (tolerância R$ 1): combinação
    única = "provável cancelamento não informado" (retirada só na SUGESTÃO, em memória); mais de uma = ambíguo (as
    alternativas são mostradas, nunca se desempata); nenhuma = sem conclusão. Notas a MENOS que o relatório não são
    cancelamento e nada se infere. Nada é gravado nem alterado no dado do gov.
  * CAUSAS (`causas_do_mes`, ordem de evidência): (1) NOTA NÃO LIQUIDADA — o que falta nas notas é exatamente o valor de
    notas ainda sem liquidação (pendente/erro no Siafi); (2) DESLOCAMENTO DE COMPETÊNCIA — o excesso (ou a falta) da NE
    num mês é exatamente a falta (ou o excesso) da mesma NE num mês vizinho (±1, depois ±2, inclusive na virada de
    ano): a nota e o relatório registraram a mesma despesa em competências diferentes — duas pontas confirmam, por
    isso tem PRIORIDADE sobre o cancelamento (só uma ponta); (3) cancelamento provável (`ajustar_mes`). NE sem
    nenhuma linha no relatório (DEA) não tem com o que comparar e fica de fora.

Contrato público:
    ItemNota, MesConciliado, EmpenhoInfo, AjusteMes, Causa, Contexto
    ajustar_mes(mes, ignorar=()) -> AjusteMes
    construir_contexto(relatorio, itens, pendentes, naturezas) -> Contexto
    classificar_mes(mes, ajuste, causas) -> str   # uma das CLASSES
    totais_por_ne(relatorio, itens, execucao, empenhos) -> list[TotalNE]   # confronto de totais com a Execução Mensal
    causas_do_mes(contexto, ano, mes, nes) -> list[Causa]
    empenhos_do_contrato(empenhos_gov, contrato_id, ne_cadastro=None, natureza_cadastro=None) -> dict[ne, EmpenhoInfo]
    nes_do_mes(mes) -> list[str]
    padrao_do_mes(mes, empenhos) -> list[str]
    filtrar_mes(mes, selecionadas) -> MesConciliado
    naturezas_20rk(empenhos_gov, contrato_id, ne_cadastro=None, natureza_cadastro=None) -> dict[ne, natureza | None]
    itens_das_notas(faturas, naturezas) -> (DataFrame, fora_do_recorte: int)
    conciliar_exercicio(ano, relatorio, itens, naturezas) -> list[MesConciliado]
    exercicios_disponiveis(relatorio, itens, naturezas) -> list[int]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from itertools import combinations

import pandas as pd

TOLERANCIA = 1.0  # R$: diferença até este valor = "batem"

COLUNAS_ITENS = ["ne", "ano", "mes", "valor", "nota", "fatura_id", "rateada", "duplicada"]


@dataclass(frozen=True)
class EmpenhoInfo:
    natureza: str | None  # "339092 - DESPESAS ..."; None = não identificada
    plano_interno: str | None  # "M20RKG01SCN - GESTAO ..."; None = sem plano interno
    da_20rk: bool = False  # plano interno com "20RK", ou a NE do próprio cadastro de Contínuos

    @property
    def acao(self) -> str:
        """"20RK" quando é; senão o código do plano interno (ex.: "L20RLP01SCN"); "—" sem plano interno."""
        if self.da_20rk:
            return "20RK"
        return (self.plano_interno or "—").split(" - ")[0].strip() or "—"

    @property
    def elemento(self) -> str | None:
        codigo = (self.natureza or "")[:6]
        return codigo[4:6] if len(codigo) == 6 and codigo.isdigit() else None


@dataclass(frozen=True)
class ItemNota:
    ne: str
    valor: float
    nota: str
    rateada: bool
    duplicada: bool
    natureza: str | None  # ex.: "339092 - DESPESAS DE EXERCICIOS ANTERIORES"; None = não identificado

    @property
    def elemento(self) -> str | None:
        codigo = (self.natureza or "")[:6]
        return codigo[4:6] if len(codigo) == 6 and codigo.isdigit() else None


@dataclass(frozen=True)
class MesConciliado:
    ano: int
    mes: int
    relatorio: float | None  # None = sem registro no relatório
    relatorio_por_ne: dict[str, float] = field(default_factory=dict)
    notas: float | None = None  # None = sem registro de nota (duplicadas não somam)
    itens: list[ItemNota] = field(default_factory=list)
    #: valor (relatório + notas) das NEs desmarcadas no filtro do mês; `None` = nenhuma NE fora
    fora_do_filtro_relatorio: float | None = None
    fora_do_filtro_notas: float | None = None
    nes_fora: tuple[str, ...] = ()

    @property
    def situacao(self) -> str:
        if self.relatorio is None and self.notas is None:
            return "sem_registro"
        if self.notas is None:
            return "so_relatorio"
        if self.relatorio is None:
            return "so_notas"
        return "batem" if abs(self.relatorio - self.notas) <= TOLERANCIA else "divergem"

    @property
    def diferenca(self) -> float | None:
        if self.relatorio is None or self.notas is None:
            return None
        return self.notas - self.relatorio


MAX_NOTAS_BUSCA = 16  # acima disso a busca de combinações não é feita (sem conclusão)
MAX_RETIRADAS = 6


@dataclass(frozen=True)
class AjusteMes:
    """Resultado da conciliação de duplicidades de um mês. Índices referem-se a `MesConciliado.itens`."""

    #: notas sugeridas como canceladas (combinação ÚNICA por NE)
    retiradas: tuple[int, ...] = ()
    #: por NE ambígua: as combinações possíveis
    alternativas: tuple[tuple[str, tuple[tuple[int, ...], ...]], ...] = ()
    #: soma das notas válidas sem as retiradas (None = sem nota)
    notas_ajustadas: float | None = None
    situacao: str = "sem_ajuste"  # sem_ajuste | batem_ajustado | ambiguo


def _melhores_combinacoes(valores: list[float], alvo: float) -> list[tuple[int, ...]]:
    """As combinações de MENOR tamanho cuja soma é `alvo` (±TOLERANCIA); vazio se não houver (ou muitas notas)."""
    if len(valores) > MAX_NOTAS_BUSCA:
        return []
    for k in range(1, min(len(valores), MAX_RETIRADAS) + 1):
        achadas = [c for c in combinations(range(len(valores)), k) if abs(sum(valores[i] for i in c) - alvo) <= TOLERANCIA]
        if achadas:
            return achadas
    return []


def ajustar_mes(mes: "MesConciliado", ignorar=()) -> AjusteMes:
    """Conciliação de duplicidades do mês (já filtrado): ver docstring do módulo. `ignorar`: NEs já explicadas por outra
    causa de mais evidência (deslocamento de competência) — não recebem sugestão de cancelamento."""

    retiradas: list[int] = []
    alternativas: list[tuple[str, tuple[tuple[int, ...], ...]]] = []
    for ne, rel in mes.relatorio_por_ne.items():
        if ne in set(ignorar):
            continue
        indices = [i for i, item in enumerate(mes.itens) if item.ne == ne and not item.duplicada]
        total = sum(mes.itens[i].valor for i in indices)
        if not indices or total - rel <= TOLERANCIA:
            continue  # sem nota, ou notas já batem / a menos: nada a inferir
        combos = _melhores_combinacoes([mes.itens[i].valor for i in indices], total - rel)
        if len(combos) == 1:
            retiradas += [indices[j] for j in combos[0]]
        elif len(combos) > 1:
            alternativas.append((ne, tuple(tuple(indices[j] for j in c) for c in combos)))
    if not retiradas and not alternativas:
        return AjusteMes(notas_ajustadas=mes.notas)
    validos = [item.valor for i, item in enumerate(mes.itens) if not item.duplicada and i not in set(retiradas)]
    ajustadas = sum(validos) if validos else None
    if alternativas:
        situacao = "ambiguo"
    elif mes.relatorio is not None and ajustadas is not None and abs(ajustadas - mes.relatorio) <= TOLERANCIA:
        situacao = "batem_ajustado"
    else:
        situacao = "sem_ajuste"
    return AjusteMes(tuple(sorted(retiradas)), tuple(alternativas), ajustadas, situacao)


#: classe única de cada mês (já filtrado), do mais ao menos conciliado, com o rótulo do painel de pendências
CLASSES = {
    "batem": "Batem",
    "sem_registro": "Sem registro",
    "deslocamento": "Deslocamento de competência",
    "nota_pendente": "Nota ainda não liquidada",
    "cancelamento": "Cancelamento provável",
    "ambiguo": "Ambíguo",
    "so_notas": "Só nota (sem relatório)",
    "so_relatorio": "Só relatório (sem nota)",
    "sem_explicacao": "Diferença sem explicação",
    "confirmada": "Sugestão confirmada",
    "rejeitada": "Sugestão rejeitada",
}
#: classes que NÃO são pendência: nada a fazer ("confirmada" = o usuário confirmou a sugestão; "rejeitada" continua pendente)
CLASSES_OK = ("batem", "sem_registro", "confirmada")


@dataclass(frozen=True)
class TotalNE:
    """Totais de uma NE em três fontes (todas as competências/lançamentos disponíveis). A Execução Mensal é por mês de
    LANÇAMENTO, não por competência: só o total é comparável (e ela só cobre 2024 em diante)."""

    ne: str
    notas: float | None  # liquidado nas notas (válidas, sem duplicadas); None = nenhuma nota
    relatorio: float | None  # Liquidação por Competência; None = NE sem linha no relatório (ex.: DEA)
    execucao: float | None  # Execução Mensal (liquidada); None = NE sem lançamento na Execução Mensal
    empenho: EmpenhoInfo | None = None
    #: Ação e PTRES que o relatório de competência associa à NE (valores distintos, " / "); None = relatório sem a dimensão
    acoes_relatorio: str | None = None
    ptres_relatorio: str | None = None

    @property
    def acao_confere(self) -> bool | None:
        """A Ação do relatório de competência bate com a do cadastro/gov (`empenho`)? `None` = não comparável (relatório sem
        Ação, como no layout antigo, ou empenho sem plano interno); só informativo — não muda nenhum total nem a situação."""
        return acao_confere(self.empenho, self.acoes_relatorio)

    @property
    def dif_relatorio(self) -> float | None:
        return None if self.relatorio is None or self.execucao is None else round(self.relatorio - self.execucao, 2)

    @property
    def dif_notas(self) -> float | None:
        return None if self.notas is None or self.execucao is None else round(self.notas - self.execucao, 2)

    @property
    def situacao(self) -> str:
        """sem_execucao | batem (as fontes presentes batem com a Execução) | diverge_relatorio | diverge_notas"""
        if self.execucao is None:
            return "sem_execucao"
        if self.dif_relatorio is not None and abs(self.dif_relatorio) > TOLERANCIA:
            return "diverge_relatorio"
        if self.dif_notas is not None and abs(self.dif_notas) > TOLERANCIA:
            return "diverge_notas"
        return "batem"


def acao_confere(empenho: EmpenhoInfo | None, acoes_relatorio: str | None) -> bool | None:
    """Compara a Ação do relatório (código da Ação de Governo, ex. "20RK"; várias separadas por " / ") com o empenho do
    contrato. DÚVIDA REGISTRADA (13/10/2026): o empenho só traz o PLANO INTERNO (ex. "M20RKG01SCN"), que embute o código da
    Ação — mesma leitura que `da_20rk` já faz ("20RK" dentro do plano interno). Por isso "confere" = algum código de Ação do
    relatório aparece no plano interno; a regra contábil exata de correspondência Ação × PI não está definida e não é
    presumida além disso. NE com várias Ações no relatório confere se QUALQUER uma bate (nunca escolhe uma)."""

    acoes = {parte.strip() for parte in (acoes_relatorio or "").split("/") if parte.strip()}
    if empenho is None or not acoes:
        return None
    if empenho.da_20rk:
        return "20RK" in acoes
    plano = (empenho.plano_interno or "").split(" - ")[0].strip()
    if not plano:
        return None
    return any(acao in plano for acao in acoes)


def totais_por_ne(
    relatorio: pd.DataFrame | None, itens: pd.DataFrame, execucao: pd.DataFrame | None, empenhos: dict[str, EmpenhoInfo],
) -> list[TotalNE]:
    """Uma linha por NE do contrato com dado em alguma fonte: total das notas, do relatório e da Execução Mensal
    (`execucao` com `ne_curta` e `liquidada`). Ausência de fonte = None (nunca zero)."""

    rel = _relatorio_do_contrato(relatorio, set(empenhos))
    por_rel = {str(ne): float(v) for ne, v in rel.groupby("ne_curta")["valor"].sum().items()}
    validos = itens[~itens["duplicada"]] if not itens.empty else itens
    por_notas = {str(ne): float(v) for ne, v in validos.groupby("ne")["valor"].sum().items()} if not validos.empty else {}
    por_exec: dict[str, float] = {}
    if execucao is not None and not execucao.empty:
        recorte = execucao[execucao["ne_curta"].isin(set(empenhos))]
        por_exec = {str(ne): float(v) for ne, v in recorte.groupby("ne_curta")["liquidada"].sum().items()}
    nes = sorted(set(por_rel) | set(por_notas) | set(por_exec))
    acoes, ptres = _dimensoes_do_relatorio(rel)
    return [
        TotalNE(
            ne, round(por_notas[ne], 2) if ne in por_notas else None, round(por_rel[ne], 2) if ne in por_rel else None,
            round(por_exec[ne], 2) if ne in por_exec else None, empenhos.get(ne), acoes.get(ne), ptres.get(ne),
        )
        for ne in nes
    ]


def _dimensoes_do_relatorio(rel: pd.DataFrame) -> tuple[dict[str, str], dict[str, str]]:
    """Ação e PTRES por `ne_curta`, a partir das colunas opcionais `acoes`/`ptres` do relatório (só existem quando o
    layout do relatório as traz). Sem a coluna ou sem valor, a NE simplesmente não entra no dicionário."""

    def _por_ne(coluna: str) -> dict[str, str]:
        if coluna not in rel.columns or rel.empty:
            return {}
        recorte = rel[["ne_curta", coluna]].dropna(subset=[coluna]).drop_duplicates()
        return {str(ne): str(v) for ne, v in zip(recorte["ne_curta"], recorte[coluna])}

    return _por_ne("acoes"), _por_ne("ptres")


@dataclass(frozen=True)
class Causa:
    ne: str
    tipo: str  # nota_pendente | deslocamento
    valor: float
    #: deslocamento: AAAAMM do mês vizinho que tem o par; None para nota_pendente
    par: int | None = None
    #: deslocamento: "notas_aqui" (as notas estão neste mês, o relatório registrou no par) ou "relatorio_aqui"
    sentido: str | None = None
    #: nota_pendente: números das notas ainda sem liquidação
    notas: tuple[str, ...] = ()


@dataclass(frozen=True)
class Contexto:
    notas: dict  # (ne, AAAAMM) -> valor das notas liquidadas válidas
    relatorio: dict  # (ne, AAAAMM) -> valor do relatório
    pendentes: dict  # (ne, AAAAMM) -> [(nota, valor)] das notas ainda não liquidadas
    nes_com_relatorio: frozenset  # NEs que têm alguma linha no relatório (as demais — ex.: DEA — não se comparam)


def construir_contexto(
    relatorio: pd.DataFrame | None, itens: pd.DataFrame, pendentes: pd.DataFrame | None, naturezas: dict[str, str | None],
) -> Contexto:
    """Soma por (NE, mês) das duas fontes e das notas pendentes, de TODOS os meses (a vizinhança atravessa exercícios)."""

    rel = _relatorio_do_contrato(relatorio, set(naturezas))
    por_rel = {(str(ne), int(am)): round(float(v), 2) for (ne, am), v in rel.groupby(["ne_curta", "ano_mes"])["valor"].sum().items()}
    por_notas: dict = {}
    for r in itens[~itens["duplicada"]].itertuples() if not itens.empty else []:
        chave = (str(r.ne), int(r.ano) * 100 + int(r.mes))
        por_notas[chave] = round(por_notas.get(chave, 0.0) + float(r.valor), 2)
    por_pend: dict = {}
    for r in pendentes.itertuples() if pendentes is not None and not pendentes.empty else []:
        por_pend.setdefault((str(r.ne), int(r.ano) * 100 + int(r.mes)), []).append((str(r.nota), float(r.valor)))
    return Contexto(por_notas, por_rel, por_pend, frozenset(ne for ne, _ in por_rel))


def _vizinho(ano_mes: int, delta: int) -> int:
    ano, mes = divmod(ano_mes, 100)
    indice = ano * 12 + (mes - 1) + delta
    return (indice // 12) * 100 + indice % 12 + 1


def causas_do_mes(contexto: Contexto, ano: int, mes: int, nes) -> list[Causa]:
    """A causa de cada divergência das `nes` no mês (só as que têm causa identificada): ver docstring do módulo."""

    am = ano * 100 + mes
    causas = []
    for ne in sorted(nes):
        if ne not in contexto.nes_com_relatorio:
            continue  # sem relatório da NE em nenhum mês (DEA): nada a comparar
        dif = round(contexto.notas.get((ne, am), 0.0) - contexto.relatorio.get((ne, am), 0.0), 2)
        if abs(dif) <= TOLERANCIA:
            continue
        if dif < 0:  # relatório a mais que as notas
            falta = -dif
            pend = contexto.pendentes.get((ne, am), [])
            if pend and abs(sum(v for _, v in pend) - falta) <= TOLERANCIA:
                causas.append(Causa(ne, "nota_pendente", falta, None, None, tuple(n for n, _ in pend)))
                continue
        for delta in (-1, 1, -2, 2):  # o vizinho mais próximo primeiro
            vz = _vizinho(am, delta)
            dif_vz = round(contexto.notas.get((ne, vz), 0.0) - contexto.relatorio.get((ne, vz), 0.0), 2)
            if abs(dif_vz + dif) <= TOLERANCIA:  # excesso aqui = falta lá (ou o contrário)
                causas.append(Causa(ne, "deslocamento", abs(dif), vz, "notas_aqui" if dif > 0 else "relatorio_aqui"))
                break
    return causas


def classificar_mes(mes: "MesConciliado", ajuste: "AjusteMes | None", causas: "list[Causa] | None") -> str:
    """A classe do mês (ver `CLASSES`), na ordem de evidência: causa identificada (nota pendente, deslocamento) >
    cancelamento provável / ambíguo > situação simples das duas fontes."""

    if mes.situacao in ("sem_registro", "batem"):
        return mes.situacao
    tipos = [c.tipo for c in causas or []]
    if "nota_pendente" in tipos:
        return "nota_pendente"
    if "deslocamento" in tipos:
        return "deslocamento"
    if ajuste is not None and ajuste.situacao in ("batem_ajustado", "ambiguo"):
        return "cancelamento" if ajuste.situacao == "batem_ajustado" else "ambiguo"
    return {"so_notas": "so_notas", "so_relatorio": "so_relatorio", "divergem": "sem_explicacao"}[mes.situacao]


def _vazio(valor: object) -> bool:
    return valor is None or (isinstance(valor, float) and pd.isna(valor))


def empenhos_do_contrato(
    empenhos_gov: pd.DataFrame | None, contrato_id: object, ne_cadastro: object = None, natureza_cadastro: object = None,
) -> dict[str, EmpenhoInfo]:
    """TODAS as NEs do contrato no Contratos.gov (com natureza e plano interno) e a NE do cadastro de Contínuos (que é da
    20RK por definição, mesmo sem par no gov)."""

    resultado: dict[str, EmpenhoInfo] = {}
    if empenhos_gov is not None and not empenhos_gov.empty and not _vazio(contrato_id):
        recorte = empenhos_gov[empenhos_gov["contrato_id"].astype(str) == str(contrato_id)]
        for _, empenho in recorte.iterrows():
            if _vazio(empenho.get("ne")):
                continue
            natureza, pi = empenho.get("natureza_despesa"), empenho.get("plano_interno")
            resultado[str(empenho["ne"])] = EmpenhoInfo(
                None if _vazio(natureza) else str(natureza), None if _vazio(pi) else str(pi), "20RK" in str(pi or ""),
            )
    if not _vazio(ne_cadastro) and str(ne_cadastro).strip():
        ne = str(ne_cadastro).strip()
        atual = resultado.get(ne)
        natureza = atual.natureza if atual and atual.natureza else (None if _vazio(natureza_cadastro) else str(natureza_cadastro))
        resultado[ne] = EmpenhoInfo(natureza, atual.plano_interno if atual else None, True)
    return resultado


def nes_do_mes(mes: "MesConciliado") -> list[str]:
    """NEs que aparecem no mês em qualquer das fontes (relatório ou notas), em ordem."""
    return sorted(set(mes.relatorio_por_ne) | {item.ne for item in mes.itens})


def padrao_do_mes(mes: "MesConciliado", empenhos: dict[str, EmpenhoInfo]) -> list[str]:
    """Seleção inicial do filtro do mês: as NEs da 20RK que aparecem nele; se não houver nenhuma, todas."""
    presentes = nes_do_mes(mes)
    da_20rk = [ne for ne in presentes if empenhos.get(ne) is not None and empenhos[ne].da_20rk]
    return da_20rk or presentes


def filtrar_mes(mes: "MesConciliado", selecionadas) -> "MesConciliado":
    """O mês só com as NEs `selecionadas`: relatório e notas recalculados (as duplicadas não somam); o valor das NEs
    desmarcadas fica em `fora_do_filtro_*`. Seleção vazia = tudo fora."""

    escolhidas = set(selecionadas)
    rel = {ne: v for ne, v in mes.relatorio_por_ne.items() if ne in escolhidas}
    itens = [item for item in mes.itens if item.ne in escolhidas]
    fora_rel = [v for ne, v in mes.relatorio_por_ne.items() if ne not in escolhidas]
    fora_itens = [item for item in mes.itens if item.ne not in escolhidas and not item.duplicada]
    validas = [item.valor for item in itens if not item.duplicada]
    nes_fora = sorted((set(mes.relatorio_por_ne) | {i.ne for i in mes.itens}) - escolhidas)
    return MesConciliado(
        ano=mes.ano, mes=mes.mes, relatorio=sum(rel.values()) if rel else None, relatorio_por_ne=rel,
        notas=sum(validas) if validas else None, itens=itens,
        fora_do_filtro_relatorio=sum(fora_rel) if fora_rel else None,
        fora_do_filtro_notas=sum(i.valor for i in fora_itens) if fora_itens else None,
        nes_fora=tuple(nes_fora),
    )


def naturezas_20rk(
    empenhos_gov: pd.DataFrame | None, contrato_id: object, ne_cadastro: object = None, natureza_cadastro: object = None,
) -> dict[str, str | None]:
    """NEs da 20RK do contrato → natureza de despesa (texto do gov, ex. "339092 - DESPESAS ..."). A NE do cadastro de
    Contínuos (parcela 20RK por definição) entra mesmo sem par no gov, com a natureza do cadastro (ou nula)."""

    resultado: dict[str, str | None] = {}
    if empenhos_gov is not None and not empenhos_gov.empty and not _vazio(contrato_id):
        recorte = empenhos_gov[empenhos_gov["contrato_id"].astype(str) == str(contrato_id)]
        for _, empenho in recorte.iterrows():
            if "20RK" in str(empenho.get("plano_interno") or "") and not _vazio(empenho.get("ne")):
                natureza = empenho.get("natureza_despesa")
                resultado[str(empenho["ne"])] = None if _vazio(natureza) else str(natureza)
    if not _vazio(ne_cadastro) and str(ne_cadastro).strip():
        ne = str(ne_cadastro).strip()
        if resultado.get(ne) is None:
            resultado[ne] = None if _vazio(natureza_cadastro) else str(natureza_cadastro)
    return resultado


def itens_das_notas(
    faturas: pd.DataFrame | None, naturezas: dict[str, str | None], liquidadas: bool = True,
) -> tuple[pd.DataFrame, int]:
    """Uma linha por (NE do recorte, competência, nota) das notas liquidadas (ou, com `liquidadas=False`, das AINDA NÃO
    liquidadas: sem data de liquidação — pendentes ou com erro no Siafi), e quantas dessas notas ficaram fora do
    recorte (nenhuma NE do contrato)."""

    if faturas is None or faturas.empty:
        return pd.DataFrame(columns=COLUNAS_ITENS), 0
    tem_data = faturas["data_liquidacao"].apply(lambda d: isinstance(d, date))
    liquidadas = faturas[tem_data if liquidadas else ~tem_data]
    linhas, fora, vistas = [], 0, set()
    for _, nota in liquidadas.sort_values("fatura_id").iterrows():
        empenhos = [(ne, float(v)) for ne, _, v in nota["empenhos"] if ne and not _vazio(v)]
        referencias = [(a, m, float(v)) for a, m, v in nota["referencias"] if not _vazio(v)]
        if not any(ne in naturezas for ne, _ in empenhos):
            fora += 1
            continue
        if not referencias:
            continue
        assinatura = (nota["numero"], nota["valor"], tuple(sorted(ne for ne, _ in empenhos)))
        duplicada = assinatura in vistas
        vistas.add(assinatura)
        rateada = len(empenhos) > 1 and len(referencias) > 1
        total_refs = sum(v for _, _, v in referencias)
        for ne, valor_ne in empenhos:
            if ne not in naturezas:
                continue
            for ano, mes, valor_ref in referencias:
                if len(referencias) == 1:
                    parte = valor_ne
                elif len(empenhos) == 1:
                    parte = valor_ref
                else:
                    parte = valor_ne * valor_ref / total_refs if total_refs else 0.0
                linhas.append({
                    "ne": ne, "ano": int(ano), "mes": int(mes), "valor": parte, "nota": str(nota["numero"] or "—"),
                    "fatura_id": str(nota["fatura_id"]), "rateada": rateada, "duplicada": duplicada,
                })
    return pd.DataFrame(linhas, columns=COLUNAS_ITENS), fora


def _relatorio_do_contrato(relatorio: pd.DataFrame | None, nes: set[str]) -> pd.DataFrame:
    """`relatorio` = Liquidação por Competência por (NE, mês) com `ne_curta`, `ano_mes` (AAAAMM) e `valor`."""
    if relatorio is None or relatorio.empty or not nes:
        return pd.DataFrame(columns=["ne_curta", "ano_mes", "valor"])
    return relatorio[relatorio["ne_curta"].isin(nes)]


def conciliar_exercicio(
    ano: int, relatorio: pd.DataFrame | None, itens: pd.DataFrame, naturezas: dict[str, str | None],
) -> list[MesConciliado]:
    """Os 12 meses do exercício: relatório (soma das NEs do recorte) e notas (sem as duplicadas), com o detalhe por NE."""

    rel = _relatorio_do_contrato(relatorio, set(naturezas))
    meses = []
    for mes in range(1, 13):
        rel_mes = rel[rel["ano_mes"].astype(int) == ano * 100 + mes]
        por_ne = {str(ne): float(v) for ne, v in rel_mes.groupby("ne_curta")["valor"].sum().items()}
        notas_mes = itens[(itens["ano"] == ano) & (itens["mes"] == mes)] if not itens.empty else itens
        lista = [
            ItemNota(str(r.ne), float(r.valor), str(r.nota), bool(r.rateada), bool(r.duplicada), naturezas.get(str(r.ne)))
            for r in notas_mes.itertuples()
        ]
        validas = [i.valor for i in lista if not i.duplicada]
        meses.append(MesConciliado(
            ano=ano, mes=mes, relatorio=sum(por_ne.values()) if por_ne else None, relatorio_por_ne=por_ne,
            notas=sum(validas) if validas else None, itens=lista,
        ))
    return meses


def exercicios_disponiveis(relatorio: pd.DataFrame | None, itens: pd.DataFrame, naturezas: dict[str, str | None]) -> list[int]:
    """Anos com dado em alguma das fontes, do mais recente ao mais antigo."""
    anos = {int(a) // 100 for a in _relatorio_do_contrato(relatorio, set(naturezas))["ano_mes"]}
    if not itens.empty:
        anos |= {int(a) for a in itens["ano"]}
    return sorted(anos, reverse=True)
