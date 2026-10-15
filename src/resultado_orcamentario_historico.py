"""Histórico do Resultado Orçamentário: uma fotografia do resultado por dia e a variação entre elas.

Decisão (13/10/2026, aprovada pelo usuário): o resultado é recalculado a cada abertura da página e
não fica guardado em lugar nenhum; para mostrar "o saldo no dia e o que levou à alteração" é preciso
gravar fotografias. Persistência em arquivo aprovada explicitamente nesta data, conforme o AGENTS.md:
um JSON por dia em `data/resultado_orcamentario/<exercício>/historico/AAAA-MM-DD.json`, fora do git,
gravação atômica (mesmo padrão de `src.resultado_orcamentario_cadastro`). A fotografia do dia é
substituída quando o resultado muda no mesmo dia (vale a última do dia); dias sem abertura da
página não têm fotografia — o passado anterior a esta função não é reconstruível.

"O que levou à alteração" = variação por COMPONENTE da fórmula
`Resultado = Dotação − Empenhado − Necessidade`, entre duas fotografias consecutivas. Nulo não é
zero: componente nulo (indisponível) em qualquer das duas pontas gera variação nula, nunca 0,00.
Este módulo é regra pura + arquivos: não importa Streamlit.

CRITÉRIO (15/10/2026): a fórmula mudou para `Dotação − Executado − Projetado a realizar` (Contratos e Bolsas pelo que a NE já
liquidou e pelo que falta da projeção, não mais pelo empenhado e pela necessidade de empenho). As fotografias antigas não são
reescritas: cada uma leva o seu `criterio` (`None` = o critério antigo, empenhado + necessidade + anulação). Na fotografia
nova, `empenhado`/`empenhado_total` guardam o executado de Contratos e Bolsas (as demais origens seguem pelo empenhado) e
`necessidade` guarda o projetado. Comparar duas fotografias de critérios diferentes é sinalizado em `Mudanca`.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from src.resultado_orcamentario_cadastro import ArquivoCorrompido, DIRETORIO_PADRAO

NOME_PASTA = "historico"
VERSAO = 1
#: tolerância para considerar dois valores iguais (centavo): evita regravar por ruído de ponto flutuante.
TOLERANCIA = 0.005

#: sinal do efeito de cada grupo de componentes no resultado (Resultado = Dotação − Empenhado − Necessidade).
SINAL_DOTACAO = 1
SINAL_DESPESA = -1
#: anulação sugerida de empenho (15/10/2026): receita que soma ao resultado
SINAL_RECEITA = 1

#: critério de 15/10/2026 (ver o docstring do módulo); `None` na fotografia = critério anterior
CRITERIO_EXECUTADO_PROJETADO = "executado_projetado"


@dataclass(frozen=True)
class Fotografia:
    data: str  # AAAA-MM-DD
    exercicio: int
    resultado: float | None
    incompleto: bool
    dotacao: float | None
    empenhado: dict[str, float | None]
    empenhado_total: float | None
    necessidade: dict[str, float | None]
    celulas_marcadas: int
    dotacao_extracao: str | None = None
    dotacao_sha: str | None = None
    execucao_extracao: str | None = None
    execucao_sha: str | None = None
    #: Dotação Atualizada de cada célula MARCADA (chave = `chave_celula`). `None` = fotografia sem o detalhe
    #: (anterior a 13/10/2026 ou gravada sem ele); valor `None` dentro do dicionário = célula com dotação nula.
    dotacao_por_celula: dict[str, float | None] | None = None
    #: anulação sugerida por origem (15/10/2026). `None` = fotografia anterior ao registro: o resultado dela não incluía
    #: anulação (equivale a zero a somar). Vale também para origem ausente do dicionário.
    anulacao: dict[str, float | None] | None = None
    #: as "Outras despesas previstas" estavam na conta? (15/10/2026: o usuário pode desconsiderá-las). `None` = fotografia
    #: anterior ao registro, quando elas sempre entravam: vale como "consideradas".
    outras_despesas_consideradas: bool | None = None
    #: critério da fórmula (ver `CRITERIO_EXECUTADO_PROJETADO`); `None` = fotografia anterior a 15/10/2026
    criterio: str | None = None
    registrado_em: str = field(default="", compare=False)


@dataclass(frozen=True)
class Variacao:
    """Um componente entre duas fotografias. `efeito` é o quanto a variação moveu o resultado (já com o sinal da
    fórmula); `None` quando alguma ponta é nula."""

    grupo: str  # "Dotação" | "Empenhado" | "Necessidade" | "Anulação sugerida"
    componente: str
    anterior: float | None
    atual: float | None
    variacao: float | None
    efeito: float | None


@dataclass(frozen=True)
class VariacaoCelula:
    """Uma célula marcada entre duas fotografias. `antes`/`depois` nulos = célula FORA da seleção naquela ponta (ou
    dotação nula, ver `motivo`). `efeito` é o quanto moveu a dotação total: célula marcada/desmarcada move o valor
    inteiro; dotação nula em alguma ponta não é calculável (`None`)."""

    chave: str
    antes: float | None
    depois: float | None
    efeito: float | None
    motivo: str  # "dotação alterada" | "célula marcada" | "célula desmarcada" | "dotação nula"


@dataclass(frozen=True)
class Mudanca:
    """Entre a fotografia `anterior` e a `atual`: o que variou, em ordem da fórmula."""

    anterior: Fotografia
    atual: Fotografia
    variacoes: list[Variacao]
    variacao_resultado: float | None
    #: variação da dotação por célula; `None` quando alguma das fotografias não tem o detalhe
    celulas: list[VariacaoCelula] | None = None
    #: "consideradas → desconsideradas" (ou o inverso) quando a escolha sobre as outras despesas mudou entre as duas
    #: fotografias: parte da variação da necessidade vem dessa escolha, não de mudança nas despesas. `None` sem mudança.
    escolha_outras_despesas: str | None = None
    #: as duas fotografias usam critérios diferentes (empenhado+necessidade × executado+projetado): a variação dos
    #: componentes de Contratos e Bolsas mistura a mudança de critério com a mudança real. `None` = mesmo critério.
    mudanca_de_criterio: str | None = None


def _consideradas(foto: Fotografia) -> bool:
    """Outras despesas na conta da fotografia; ausente (fotografia antiga) vale como consideradas."""

    return foto.outras_despesas_consideradas is not False


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pasta(exercicio: int, diretorio: Path) -> Path:
    return Path(diretorio) / str(int(exercicio)) / NOME_PASTA


def _caminho(exercicio: int, dia: str, diretorio: Path) -> Path:
    return _pasta(exercicio, diretorio) / f"{dia}.json"


def _gravar_atomico(caminho: Path, dado: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.parent / f".{caminho.name}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(json.dumps(dado, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()


def _para_json(foto: Fotografia) -> dict:
    return {
        "versao": VERSAO,
        "data": foto.data,
        "registrado_em": foto.registrado_em,
        "exercicio": foto.exercicio,
        "resultado": foto.resultado,
        "incompleto": foto.incompleto,
        "dotacao": foto.dotacao,
        "empenhado": foto.empenhado,
        "empenhado_total": foto.empenhado_total,
        "necessidade": foto.necessidade,
        "celulas_marcadas": foto.celulas_marcadas,
        "dotacao_extracao": foto.dotacao_extracao,
        "dotacao_sha": foto.dotacao_sha,
        "execucao_extracao": foto.execucao_extracao,
        "execucao_sha": foto.execucao_sha,
        "dotacao_por_celula": foto.dotacao_por_celula,
        "anulacao": foto.anulacao,
        "outras_despesas_consideradas": foto.outras_despesas_consideradas,
        "criterio": foto.criterio,
    }


def _numero(valor: object) -> float | None:
    return None if valor is None else float(valor)


def _de_json(dado: dict, caminho: Path) -> Fotografia:
    try:
        return Fotografia(
            data=str(dado["data"]),
            exercicio=int(dado["exercicio"]),
            resultado=_numero(dado["resultado"]),
            incompleto=bool(dado["incompleto"]),
            dotacao=_numero(dado["dotacao"]),
            empenhado={str(k): _numero(v) for k, v in dado["empenhado"].items()},
            empenhado_total=_numero(dado["empenhado_total"]),
            necessidade={str(k): _numero(v) for k, v in dado["necessidade"].items()},
            celulas_marcadas=int(dado["celulas_marcadas"]),
            dotacao_extracao=dado.get("dotacao_extracao"),
            dotacao_sha=dado.get("dotacao_sha"),
            execucao_extracao=dado.get("execucao_extracao"),
            execucao_sha=dado.get("execucao_sha"),
            dotacao_por_celula=(
                None if dado.get("dotacao_por_celula") is None
                else {str(k): _numero(v) for k, v in dado["dotacao_por_celula"].items()}
            ),
            anulacao=(
                None if dado.get("anulacao") is None else {str(k): _numero(v) for k, v in dado["anulacao"].items()}
            ),
            outras_despesas_consideradas=(
                None if dado.get("outras_despesas_consideradas") is None else bool(dado["outras_despesas_consideradas"])
            ),
            criterio=None if dado.get("criterio") is None else str(dado["criterio"]),
            registrado_em=str(dado.get("registrado_em", "")),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as erro:
        raise ArquivoCorrompido(f"Formato inesperado: {caminho}") from erro


def _ler(caminho: Path) -> Fotografia:
    try:
        dado = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as erro:
        raise ArquivoCorrompido(f"Arquivo ilegível: {caminho}") from erro
    if not isinstance(dado, dict):
        raise ArquivoCorrompido(f"Formato inesperado: {caminho}")
    return _de_json(dado, caminho)


def carregar_historico(exercicio: int, diretorio: Path = DIRETORIO_PADRAO) -> list[Fotografia]:
    """Fotografias do exercício em ordem cronológica. Pasta ausente = histórico vazio; arquivo ilegível levanta
    `ArquivoCorrompido` (a página avisa e não grava por cima)."""

    pasta = _pasta(exercicio, diretorio)
    if not pasta.exists():
        return []
    return [_ler(c) for c in sorted(pasta.glob("????-??-??.json"))]


def _igual(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= TOLERANCIA


def _dicts_iguais(x: dict, y: dict) -> bool:
    return set(x) == set(y) and all(_igual(x[k], y[k]) for k in x)


def _anulacao_ou_zero(foto: Fotografia) -> dict[str, float | None]:
    """Anulação da fotografia para comparar; ausente (fotografia antiga) vale zero em Contratos e em Bolsas."""

    base = {"Contratos Contínuos": 0.0, "Bolsas e Auxílios": 0.0}
    base.update(foto.anulacao or {})
    return base


def _mesmo_conteudo(a: Fotografia, b: Fotografia) -> bool:
    return (
        a.exercicio == b.exercicio
        and a.incompleto == b.incompleto
        and a.celulas_marcadas == b.celulas_marcadas
        and _igual(a.resultado, b.resultado)
        and _igual(a.dotacao, b.dotacao)
        and _igual(a.empenhado_total, b.empenhado_total)
        and _dicts_iguais(a.empenhado, b.empenhado)
        and _dicts_iguais(a.necessidade, b.necessidade)
        and _dicts_iguais(_anulacao_ou_zero(a), _anulacao_ou_zero(b))
        and _consideradas(a) == _consideradas(b)
        and a.criterio == b.criterio
        and (a.dotacao_sha, a.execucao_sha) == (b.dotacao_sha, b.execucao_sha)
        and (
            (a.dotacao_por_celula is None and b.dotacao_por_celula is None)
            or (
                a.dotacao_por_celula is not None and b.dotacao_por_celula is not None
                and _dicts_iguais(a.dotacao_por_celula, b.dotacao_por_celula)
            )
        )
    )


def registrar(foto: Fotografia, diretorio: Path = DIRETORIO_PADRAO) -> bool:
    """Grava a fotografia do dia (`foto.data`), substituindo a anterior do mesmo dia. Só escreve se o conteúdo mudou
    (abrir a página várias vezes sem mudança não reescreve o arquivo). Devolve `True` se gravou."""

    caminho = _caminho(foto.exercicio, foto.data, diretorio)
    if caminho.exists():
        existente = _ler(caminho)  # ilegível: levanta e nada é sobrescrito
        if _mesmo_conteudo(existente, foto):
            return False
    gravada = Fotografia(**{**foto.__dict__, "registrado_em": _agora()})
    _gravar_atomico(caminho, _para_json(gravada))
    return True


def fotografar(
    resultado,
    exercicio: int,
    celulas_marcadas: int,
    hoje: date | None = None,
    dotacao_extracao: str | None = None,
    dotacao_sha: str | None = None,
    execucao_extracao: str | None = None,
    execucao_sha: str | None = None,
    dotacao_por_celula: dict[str, float | None] | None = None,
    outras_despesas_consideradas: bool = True,
) -> Fotografia:
    """Fotografia a partir de um `ResultadoOrcamentario` (qualquer objeto com os mesmos atributos).
    `outras_despesas_consideradas`: se as outras despesas previstas entraram na conta do resultado fotografado."""

    if hasattr(resultado, "executado_total"):  # critério de 15/10/2026: executado + projetado
        empenhado = {**resultado.empenhado, **resultado.executado}
        empenhado_total, necessidade, anulacao = resultado.executado_total, dict(resultado.projetado), {}
        criterio = CRITERIO_EXECUTADO_PROJETADO
    else:
        empenhado, empenhado_total = dict(resultado.empenhado), resultado.empenhado_total
        necessidade, anulacao, criterio = dict(resultado.necessidade), dict(getattr(resultado, "anulacao", None) or {}), None
    return Fotografia(
        data=(hoje or date.today()).isoformat(),
        exercicio=int(exercicio),
        resultado=resultado.resultado,
        incompleto=bool(resultado.incompleto),
        dotacao=resultado.dotacao,
        empenhado=empenhado,
        empenhado_total=empenhado_total,
        necessidade=necessidade,
        celulas_marcadas=int(celulas_marcadas),
        dotacao_extracao=dotacao_extracao,
        dotacao_sha=dotacao_sha,
        execucao_extracao=execucao_extracao,
        execucao_sha=execucao_sha,
        dotacao_por_celula=None if dotacao_por_celula is None else dict(dotacao_por_celula),
        anulacao=anulacao,
        outras_despesas_consideradas=bool(outras_despesas_consideradas),
        criterio=criterio,
    )


SEPARADOR_CHAVE = "|"


def chave_celula(chave: tuple) -> str:
    """Chave textual estável de uma célula (7 códigos; nulo vira vazio). Códigos são texto: zeros à esquerda ficam."""

    return SEPARADOR_CHAVE.join("" if parte is None else str(parte) for parte in chave)


def rotulo_celula(chave: str) -> str:
    return " / ".join(parte or "—" for parte in chave.split(SEPARADOR_CHAVE))


def _variacao(grupo: str, componente: str, sinal: int, anterior: float | None, atual: float | None) -> Variacao:
    if anterior is None or atual is None:
        return Variacao(grupo, componente, anterior, atual, None, None)
    delta = atual - anterior
    return Variacao(grupo, componente, anterior, atual, delta, sinal * delta)


def comparar(anterior: Fotografia, atual: Fotografia) -> Mudanca:
    """Variação componente a componente, na ordem da fórmula (Dotação, Empenhado por origem, Necessidade por
    origem). Componente que só existe em uma das fotografias entra como nulo na outra (não como zero)."""

    novo = atual.criterio == CRITERIO_EXECUTADO_PROJETADO
    grupo_consumo, grupo_futuro = ("Executado", "Projetado a realizar") if novo else ("Empenhado", "Necessidade")
    variacoes = [_variacao("Dotação", "Dotação atualizada", SINAL_DOTACAO, anterior.dotacao, atual.dotacao)]
    for origem in dict.fromkeys([*atual.empenhado, *anterior.empenhado]):
        variacoes.append(_variacao(
            grupo_consumo, origem, SINAL_DESPESA, anterior.empenhado.get(origem), atual.empenhado.get(origem)
        ))
    for origem in dict.fromkeys([*atual.necessidade, *anterior.necessidade]):
        variacoes.append(_variacao(
            grupo_futuro, origem, SINAL_DESPESA, anterior.necessidade.get(origem), atual.necessidade.get(origem)
        ))
    anul_antes, anul_depois = _anulacao_ou_zero(anterior), _anulacao_ou_zero(atual)
    for origem in dict.fromkeys([*anul_depois, *anul_antes]):
        variacoes.append(_variacao(
            "Anulação sugerida", origem, SINAL_RECEITA, anul_antes.get(origem, 0.0), anul_depois.get(origem, 0.0)
        ))
    delta = None if anterior.resultado is None or atual.resultado is None else atual.resultado - anterior.resultado
    escolha = None
    if _consideradas(anterior) != _consideradas(atual):
        nome = {True: "consideradas", False: "desconsideradas"}
        escolha = f"{nome[_consideradas(anterior)]} → {nome[_consideradas(atual)]}"
    criterio = None
    if anterior.criterio != atual.criterio:
        criterio = "empenhado + necessidade → executado + projetado" if novo else "executado + projetado → empenhado + necessidade"
    return Mudanca(anterior, atual, variacoes, delta, _variacao_celulas(anterior, atual), escolha, criterio)


def _variacao_celulas(anterior: Fotografia, atual: Fotografia) -> list[VariacaoCelula] | None:
    """Células que moveram a dotação, da maior variação absoluta para a menor. `None` se alguma ponta não tem o
    detalhe por célula. Célula presente só em uma ponta foi marcada/desmarcada (move o valor inteiro; na exibição a
    ponta ausente fica nula, não zero); dotação nula em alguma ponta não é calculável."""

    if anterior.dotacao_por_celula is None or atual.dotacao_por_celula is None:
        return None
    antes, depois = anterior.dotacao_por_celula, atual.dotacao_por_celula
    itens: list[VariacaoCelula] = []
    for chave in dict.fromkeys([*depois, *antes]):
        no_antes, no_depois = chave in antes, chave in depois
        a, d = antes.get(chave), depois.get(chave)
        if no_antes and no_depois:
            if a is None or d is None:
                if a is None and d is None:
                    continue  # nula nas duas pontas: nada mudou
                itens.append(VariacaoCelula(chave, a, d, None, "dotação nula"))
            elif abs(d - a) > TOLERANCIA:
                itens.append(VariacaoCelula(chave, a, d, d - a, "dotação alterada"))
        elif no_depois:
            itens.append(VariacaoCelula(chave, None, d, d, "célula marcada"))
        else:
            itens.append(VariacaoCelula(chave, a, None, None if a is None else -a, "célula desmarcada"))
    itens.sort(key=lambda v: (v.efeito is None, -abs(v.efeito or 0.0), v.chave))
    return itens


def mudancas(historico: list[Fotografia]) -> list[Mudanca]:
    """Comparações entre fotografias consecutivas, da mais recente para a mais antiga."""

    ordenado = sorted(historico, key=lambda f: f.data)
    return [comparar(a, b) for a, b in zip(ordenado, ordenado[1:])][::-1]


def mudou(variacao: Variacao) -> bool:
    """Componente que variou (ou passou a/deixou de ser nulo)."""

    if variacao.variacao is None:
        return not _igual(variacao.anterior, variacao.atual)
    return abs(variacao.variacao) > TOLERANCIA


def _situacao(resultado: float | None) -> str:
    """Mesmos rótulos dos cartões da página (nulo, zero e negativo são estados distintos)."""

    if resultado is None:
        return "Incompleto"
    if resultado > 0:
        return "Superávit"
    if resultado < 0:
        return "Déficit"
    return "Equilíbrio"


def virada_de_situacao(anterior: Fotografia | None, atual: Fotografia) -> str | None:
    """"Superávit → Déficit" quando a situação do dia difere da da fotografia anterior; `None` na primeira fotografia ou
    quando não mudou. Qualquer mudança conta, inclusive de/para "Equilíbrio" e "Incompleto" (resultado indisponível):
    nulo, zero e negativo são estados distintos neste projeto, então nenhum é tratado como outro."""

    if anterior is None:
        return None
    antes, depois = _situacao(anterior.resultado), _situacao(atual.resultado)
    return None if antes == depois else f"{antes} → {depois}"


def tabela_historico(historico: list[Fotografia]) -> pd.DataFrame:
    """Uma linha por dia, do mais recente para o mais antigo: resultado do dia, variação em relação à fotografia
    anterior (nula na primeira ou quando uma das pontas é nula) e as datas das extrações usadas."""

    ordenado = sorted(historico, key=lambda f: f.data)
    linhas = []
    anterior: Fotografia | None = None
    for foto in ordenado:
        delta = None
        if anterior is not None and anterior.resultado is not None and foto.resultado is not None:
            delta = foto.resultado - anterior.resultado
        situacao = _situacao(foto.resultado)
        linhas.append({
            "Dia": foto.data,
            "Resultado": foto.resultado,
            "Variação": delta,
            "Situação": situacao,
            "Mudança de situação": virada_de_situacao(anterior, foto),
            "Células marcadas": foto.celulas_marcadas,
            "Outras despesas": "Consideradas" if _consideradas(foto) else "Desconsideradas",
            "Critério": "Executado + projetado" if foto.criterio == CRITERIO_EXECUTADO_PROJETADO else "Empenhado + necessidade",
            "Dotação (extração)": foto.dotacao_extracao,
            "Execução Mensal (extração)": foto.execucao_extracao,
        })
        anterior = foto
    colunas = ["Dia", "Resultado", "Variação", "Situação", "Mudança de situação", "Células marcadas", "Outras despesas",
               "Critério", "Dotação (extração)", "Execução Mensal (extração)"]
    return pd.DataFrame(linhas[::-1], columns=colunas)


def tabela_mudanca(mudanca: Mudanca, apenas_que_mudaram: bool = True) -> pd.DataFrame:
    """Componentes da fórmula entre duas fotografias, com a variação e o efeito no resultado."""

    itens = [v for v in mudanca.variacoes if mudou(v)] if apenas_que_mudaram else list(mudanca.variacoes)
    return pd.DataFrame(
        [
            {
                "Grupo": v.grupo, "Componente": v.componente, "Antes": v.anterior, "Depois": v.atual,
                "Variação": v.variacao, "Efeito no resultado": v.efeito,
            }
            for v in itens
        ],
        columns=["Grupo", "Componente", "Antes", "Depois", "Variação", "Efeito no resultado"],
    )


def tabela_celulas(mudanca: Mudanca) -> pd.DataFrame | None:
    """Células que moveram a dotação entre as duas fotografias; `None` quando falta o detalhe em alguma delas."""

    if mudanca.celulas is None:
        return None
    return pd.DataFrame(
        [
            {
                "Célula": rotulo_celula(v.chave), "Motivo": v.motivo, "Antes": v.antes, "Depois": v.depois,
                "Efeito na dotação": v.efeito,
            }
            for v in mudanca.celulas
        ],
        columns=["Célula", "Motivo", "Antes", "Depois", "Efeito na dotação"],
    )
