"""
Núcleo genérico de importação versionada — manifesto, delta entre extrações e política de
confirmação. Extraído de `importacao_execucao.py` (a implementação original, específica da
Execução Anual) para ser reutilizado por qualquer base que precise do mesmo padrão.

Camada: orquestração de importação (acima do leitor de cada base, abaixo da interface).
Não importa Streamlit. Não conhece nenhuma base específica — cada base fornece suas próprias
funções de leitura/reconciliação/validação e o conjunto de medidas que possui.

Política adotada (decisão do projeto, válida para qualquer base que use este núcleo):
  * COMPOSIÇÃO POR ANO — cada extração é a verdade completa PARA OS EXERCÍCIOS QUE ELA TRAZ.
    Um exercício ausente da extração mais recente não desaparece: continua disponível com o
    último dado importado para ele. Pedido explícito do usuário — os exercícios fechados não
    precisam ser reenviados a cada atualização, só o exercício corrente muda com frequência.
    Dentro de um mesmo exercício não há merge: se o ano X está na extração nova, ela vale
    inteira para o ano X (nunca soma/mescla linha a linha com a extração anterior desse ano).
    `manifestos_por_ano` resolve, pra cada ano já visto, qual foi o manifesto mais recente que
    o trouxe — é a partir dela que `carregar_atual` (`importacao_execucao.py`/
    `importacao_dotacao.py`) monta o DataFrame composto que as páginas de fato leem.
  * A data de referência da extração vem da data de modificação do arquivo (mtime) no momento
    em que ele é gravado em disco — que hoje, para bases importadas via upload de navegador,
    é o momento do upload (o navegador não preserva o mtime do arquivo original).

O que fica versionado não são os dados, e sim o MANIFESTO de cada importação: um JSON pequeno
com hash, data e totais por período. Ele é a âncora de rastreabilidade — permite responder
"esses números são de qual extração?" e mostrar o que mudou entre uma extração e a seguinte.

Compatibilidade — decisão explícita, não efeito colateral do refactor: `Manifesto` LÊ tanto o
formato novo (contagens agrupadas no campo `contagens`) quanto o formato antigo da Execução
Anual (contagens como campos soltos — `linhas`, `linhas_empenho`, `linhas_item_execucao`,
`notas_empenho_distintas`), tanto na construção direta em Python quanto ao carregar um
manifesto já gravado em disco. Isso existe para não invalidar manifestos e testes que já
constroem `Manifesto` no formato antigo.

Mas toda importação NOVA (via `gerar_manifesto`/`importar`) passa a ESCREVER só o formato
novo — `contagens` aninhado, nunca mais campos soltos no nível raiz. Isso é necessário para
que o núcleo seja de fato genérico: os nomes de contagem da Execução (`linhas_empenho`,
`notas_empenho_distintas`) não fazem sentido para a Dotação Anual, que terá as suas próprias
(`abas_reconhecidas`, `linhas_normalizadas`, etc.) — só um dicionário aberto acomoda as duas
sem um novo campo fixo por base. Consequência visível: a próxima vez que a Execução Anual for
reimportada de verdade (pela interface ou por `importar()`), `data/manifestos/
execucao_anual_atual.json` migra do formato antigo para o novo. O antigo continua legível
indefinidamente — só deixa de ser o formato que o código produz.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd

DIRETORIO_MANIFESTOS_PADRAO = Path("data/manifestos")
TOLERANCIA_PADRAO = 0.01

#: Contagens que a Execução Anual gravava como campos soltos, antes deste núcleo existir.
#: `Manifesto.__init__` aceita essas chaves como kwargs e as dobra para dentro de `contagens`.
_CAMPOS_CONTAGEM_LEGADOS = (
    "linhas",
    "linhas_empenho",
    "linhas_item_execucao",
    "notas_empenho_distintas",
)


def nome_ponteiro(base: str) -> str:
    """Nome do arquivo-ponteiro para a extração atual de uma base."""

    return f"{base}_atual.json"


# --------------------------------------------------------------------------------------
# Manifesto
# --------------------------------------------------------------------------------------

class Manifesto:
    """Identidade verificável de uma extração importada.

    Não é um `@dataclass` porque o construtor precisa aceitar, de forma tolerante, tanto o
    formato novo (`contagens={"linhas": ..., ...}`) quanto o formato antigo de campos soltos
    (`linhas=..., linhas_empenho=...`) — dataclasses geram o `__init__` a partir dos campos
    declarados e não comportam essa flexibilidade sem perder a validação de argumentos
    inesperados.
    """

    #: Subclasses de uma base específica podem fixar isto para que `Manifesto.atual()` funcione
    #: sem exigir o argumento `base` a cada chamada (ver `importacao_execucao.Manifesto`).
    BASE: str | None = None

    def __init__(
        self,
        *,
        base: str,
        arquivo: str,
        sha256: str,
        data_extracao: str,
        importado_em: str,
        anos: list[int],
        totais: dict[str, float],
        totais_por_ano: dict[str, dict[str, float | None]],
        contagens: dict[str, int] | None = None,
        **legado: int,
    ) -> None:
        self.base = base
        self.arquivo = arquivo
        self.sha256 = sha256
        self.data_extracao = data_extracao  # ISO, derivada do mtime do arquivo
        self.importado_em = importado_em  # ISO, momento da importação
        self.anos = anos
        self.totais = totais
        self.totais_por_ano = totais_por_ano

        contagens = dict(contagens) if contagens else {}
        for campo in _CAMPOS_CONTAGEM_LEGADOS:
            if campo in legado:
                contagens[campo] = legado.pop(campo)
        if legado:
            raise TypeError(f"Manifesto() recebeu argumentos inesperados: {sorted(legado)}")
        self.contagens = contagens

    # Compatibilidade com o formato antigo (Execução Anual, antes deste núcleo existir): os
    # quatro contadores eram campos soltos do manifesto. Continuam acessíveis como atributos,
    # só que lendo de `contagens` por baixo — o formato novo os grava lá, não mais soltos.
    @property
    def linhas(self) -> int | None:
        return self.contagens.get("linhas")

    @property
    def linhas_empenho(self) -> int | None:
        return self.contagens.get("linhas_empenho")

    @property
    def linhas_item_execucao(self) -> int | None:
        return self.contagens.get("linhas_item_execucao")

    @property
    def notas_empenho_distintas(self) -> int | None:
        return self.contagens.get("notas_empenho_distintas")

    def __repr__(self) -> str:
        return f"Manifesto(base={self.base!r}, sha256={self.sha256!r}, anos={self.anos!r})"

    @property
    def rotulo(self) -> str:
        return f"{self.data_extracao[:10]}_{self.sha256[:8]}"

    def to_dict(self) -> dict:
        return {
            "base": self.base,
            "arquivo": self.arquivo,
            "sha256": self.sha256,
            "data_extracao": self.data_extracao,
            "importado_em": self.importado_em,
            "anos": self.anos,
            "totais": self.totais,
            "totais_por_ano": self.totais_por_ano,
            "contagens": self.contagens,
        }

    def salvar(self, diretorio: Path) -> Path:
        diretorio = Path(diretorio)
        diretorio.mkdir(parents=True, exist_ok=True)
        caminho = diretorio / f"{self.base}_{self.rotulo}.json"
        conteudo = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        caminho.write_text(conteudo, encoding="utf-8")
        (diretorio / nome_ponteiro(self.base)).write_text(conteudo, encoding="utf-8")
        return caminho

    @classmethod
    def carregar(cls, caminho: Path) -> "Manifesto":
        return cls(**json.loads(Path(caminho).read_text(encoding="utf-8")))

    @classmethod
    def atual(
        cls,
        diretorio: Path = DIRETORIO_MANIFESTOS_PADRAO,
        base: str | None = None,
    ) -> "Manifesto | None":
        base = base or cls.BASE
        if base is None:
            raise ValueError(
                "Informe 'base' ou use uma subclasse com Manifesto.BASE definido "
                "(ver importacao_execucao.Manifesto)."
            )
        ponteiro = Path(diretorio) / nome_ponteiro(base)
        return cls.carregar(ponteiro) if ponteiro.exists() else None


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def destino_sem_sobrescrever(diretorio: str | Path, nome: str, sha256: str) -> tuple[Path, bool]:
    """Onde gravar em `diretorio` um arquivo de origem chamado `nome`, com conteúdo `sha256`,
    SEM nunca substituir outro arquivo de origem (regra do projeto: arquivos importados são
    imutáveis — cada manifesto aponta para o seu, e sobrescrever torna aquela extração
    irreproduzível). Devolve `(destino, ja_existe)`:

    - nome livre → o próprio nome;
    - mesmo nome e mesmo conteúdo → o arquivo existente é reaproveitado (`ja_existe=True`);
    - mesmo nome e conteúdo diferente → `<nome>__<8 primeiros do sha256><extensão>` (e, na
      colisão improvável também desse nome com outro conteúdo, o sha256 inteiro).

    Caso real (28/09/2026): o navegador reaproveitou "(8).xlsx" num download novo e a
    reimportação sobrescreveu o arquivo da extração de 22/09."""

    diretorio = Path(diretorio)
    base = Path(nome)
    for candidato in (nome, f"{base.stem}__{sha256[:8]}{base.suffix}", f"{base.stem}__{sha256}{base.suffix}"):
        destino = diretorio / candidato
        if not destino.exists():
            return destino, False
        if _sha256(destino) == sha256:
            return destino, True
    raise FileExistsError(f"Não há nome livre para gravar {nome} ({sha256}) em {diretorio}.")


def _data_extracao(caminho: Path) -> str:
    return datetime.fromtimestamp(caminho.stat().st_mtime).replace(microsecond=0).isoformat()


def gerar_manifesto(
    df: pd.DataFrame,
    caminho: Path,
    *,
    base: str,
    reconciliar: Callable[[pd.DataFrame], dict],
) -> Manifesto:
    """Reconcilia `df` e monta o manifesto da extração apontada por `caminho`.

    `reconciliar` é fornecido por cada base e deve devolver um dict com pelo menos `anos`,
    `totais` e `totais_por_ano`; qualquer outra chave é tratada como contagem estrutural
    (ex.: `linhas`, `notas_empenho_distintas` na Execução; `abas_reconhecidas` na Dotação).
    """

    caminho = Path(caminho)
    r = reconciliar(df)
    contagens = {k: v for k, v in r.items() if k not in ("anos", "totais", "totais_por_ano")}
    return Manifesto(
        base=base,
        arquivo=caminho.name,
        sha256=_sha256(caminho),
        data_extracao=_data_extracao(caminho),
        importado_em=datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat(),
        anos=r["anos"],
        totais=r["totais"],
        totais_por_ano={str(a): v for a, v in r["totais_por_ano"].items()},
        contagens=contagens,
    )


# --------------------------------------------------------------------------------------
# Comparação entre extrações
# --------------------------------------------------------------------------------------

@dataclass
class Delta:
    """O que mudou da extração anterior para a nova. Informativo, nunca bloqueante."""

    houve_anterior: bool
    mesma_extracao: bool = False
    anos_novos: list[int] = field(default_factory=list)
    #: Anos que a extração anterior tinha e esta não traz — INFORMATIVO, não é mais motivo de
    #: bloqueio (ver `exige_confirmacao`): sob composição por ano, esses exercícios continuam
    #: disponíveis com o último dado importado, não desaparecem do painel.
    anos_removidos: list[int] = field(default_factory=list)
    anos_alterados: dict[int, dict[str, dict[str, float | None]]] = field(default_factory=dict)
    #: Subconjunto de `anos_alterados` que já eram anteriores ao exercício mais recente da
    #: extração anterior — mudança retroativa (anulação/reprocessamento), não avanço normal.
    anos_retroativos: list[int] = field(default_factory=list)
    variacao_total: dict[str, float | None] = field(default_factory=dict)
    alertas: list[str] = field(default_factory=list)

    def resumo_texto(self) -> list[str]:
        if not self.houve_anterior:
            return ["Primeira importação desta base — não há extração anterior para comparar."]
        if self.mesma_extracao:
            return ["Arquivo idêntico ao da última importação (mesmo hash). Nada mudou."]
        linhas = []
        if self.anos_novos:
            linhas.append(f"Exercícios novos: {', '.join(map(str, self.anos_novos))}.")
        if self.anos_removidos:
            linhas.append(
                "Exercícios não incluídos nesta extração (mantêm o último dado importado): "
                + ", ".join(map(str, self.anos_removidos)) + "."
            )
        for ano, medidas in sorted(self.anos_alterados.items()):
            partes = [_formatar_mudanca(medida, valores) for medida, valores in medidas.items()]
            linhas.append(f"{ano}: " + "; ".join(partes))
        if not linhas:
            linhas.append("Exercícios e totais idênticos, apesar do arquivo ser diferente.")
        return linhas


def _formatar_mudanca(medida: str, valores: dict[str, float | None]) -> str:
    diferenca = valores["diferenca"]
    if diferenca is None:
        return f"{medida} {valores['antes']} → {valores['depois']}"
    return f"{medida} {diferenca:+,.2f}"


def _valores_diferem(antes: float | None, depois: float | None, tolerancia: float) -> bool:
    if antes is None or depois is None:
        return antes != depois
    return abs(float(depois) - float(antes)) > tolerancia


def _diferenca(antes: float | None, depois: float | None) -> float | None:
    if antes is None or depois is None:
        return None
    return round(float(depois) - float(antes), 2)


def comparar(
    anterior: Manifesto | None,
    novo: Manifesto,
    *,
    medidas: Sequence[str],
    tolerancia: float = TOLERANCIA_PADRAO,
) -> Delta:
    if anterior is None:
        return Delta(houve_anterior=False)
    if anterior.sha256 == novo.sha256:
        return Delta(houve_anterior=True, mesma_extracao=True)

    delta = Delta(houve_anterior=True)
    anos_ant, anos_novo = set(anterior.anos), set(novo.anos)
    delta.anos_novos = sorted(anos_novo - anos_ant)
    delta.anos_removidos = sorted(anos_ant - anos_novo)

    if delta.anos_removidos:
        delta.alertas.append(
            f"A nova extração não traz {', '.join(map(str, delta.anos_removidos))}. "
            "Sob composição por ano, esses exercícios continuam disponíveis no painel com o "
            "último dado importado para eles — não é preciso reenviá-los."
        )

    ano_mais_recente_ant = max(anos_ant) if anos_ant else None
    for ano in sorted(anos_ant & anos_novo):
        mudancas = {}
        for m in medidas:
            antes = anterior.totais_por_ano[str(ano)].get(m)
            depois = novo.totais_por_ano[str(ano)].get(m)
            if _valores_diferem(antes, depois, tolerancia):
                mudancas[m] = {"antes": antes, "depois": depois, "diferenca": _diferenca(antes, depois)}
        if mudancas:
            delta.anos_alterados[ano] = mudancas
            if ano_mais_recente_ant is not None and ano < ano_mais_recente_ant:
                delta.anos_retroativos.append(ano)
                delta.alertas.append(
                    f"{ano} mudou retroativamente — provável anulação ou reprocessamento. "
                    "Números já divulgados desse exercício precisam ser reconferidos."
                )

    delta.variacao_total = {
        m: _diferenca(anterior.totais.get(m), novo.totais.get(m)) for m in medidas
    }
    return delta


@dataclass
class MotivosGate:
    """Por que uma reimportação exige confirmação explícita antes de gravar."""

    anos_retroativos: list[int]


def exige_confirmacao(delta: Delta) -> MotivosGate | None:
    """Política do gate: só retroatividade exige confirmação explícita — mudar um valor já
    divulgado de um exercício fechado.

    Um exercício ausente da extração nova (`delta.anos_removidos`) NÃO gera gate desde que a
    política virou composição por ano (ver docstring do módulo): esse exercício não é perdido,
    só não é atualizado nesta rodada — é o caso normal e esperado de enviar só o exercício
    corrente. Continua aparecendo como informação (`delta.anos_removidos`,
    `Delta.resumo_texto()`), só deixou de bloquear.
    """

    if not delta.anos_retroativos:
        return None
    return MotivosGate(anos_retroativos=list(delta.anos_retroativos))


# --------------------------------------------------------------------------------------
# Importação
# --------------------------------------------------------------------------------------

@dataclass
class ResultadoImportacao:
    df: pd.DataFrame
    manifesto: Manifesto
    delta: Delta
    validacao: object            # RelatorioValidacao (contrato: .ok, .erros, .alertas)
    caminho_manifesto: Path | None

    @property
    def ok(self) -> bool:
        return bool(getattr(self.validacao, "ok", False))


def importar(
    caminho: str | Path,
    *,
    base: str,
    ler: Callable[[Path], pd.DataFrame],
    reconciliar: Callable[[pd.DataFrame], dict],
    validar: Callable[[pd.DataFrame], object],
    medidas: Sequence[str],
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
    registrar: bool = True,
) -> ResultadoImportacao:
    """
    Lê, valida, compara com a última extração e registra o manifesto.

    Substituição total: o DataFrame devolvido é a base inteira e deve substituir o que estiver
    em memória/persistência. O manifesto só é gravado se a validação não tiver erros —
    extração inválida não vira referência histórica.
    """
    caminho = Path(caminho)
    diretorio_manifestos = Path(diretorio_manifestos)

    df = ler(caminho)
    manifesto = gerar_manifesto(df, caminho, base=base, reconciliar=reconciliar)
    anterior = Manifesto.atual(diretorio_manifestos, base=base)
    delta = comparar(anterior, manifesto, medidas=medidas)

    relatorio = validar(df)

    caminho_manifesto = None
    if registrar and bool(getattr(relatorio, "ok", False)) and not delta.mesma_extracao:
        caminho_manifesto = manifesto.salvar(diretorio_manifestos)

    return ResultadoImportacao(
        df=df,
        manifesto=manifesto,
        delta=delta,
        validacao=relatorio,
        caminho_manifesto=caminho_manifesto,
    )


def historico(
    base: str,
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
) -> list[Manifesto]:
    """Manifestos de todas as importações já feitas desta base, do mais antigo ao mais recente."""
    diretorio = Path(diretorio_manifestos)
    if not diretorio.exists():
        return []
    ponteiro = nome_ponteiro(base)
    arquivos = [p for p in diretorio.glob(f"{base}_*.json") if p.name != ponteiro]
    return sorted((Manifesto.carregar(p) for p in arquivos), key=lambda m: m.data_extracao)


def manifestos_por_ano(
    base: str,
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
) -> dict[int, Manifesto]:
    """Para cada ano já visto por esta base, o manifesto mais recente (por `importado_em`) que
    o traz — a base para "composição por ano" (ver docstring do módulo).

    `historico()` já inclui a importação mais recente: `Manifesto.salvar` sempre grava, no
    mesmo carregamento, tanto o ponteiro (`{base}_atual.json`) quanto um arquivo próprio com
    `rotulo` (data + hash) — não precisa somar `Manifesto.atual()` separado.

    Quem consome isto (`carregar_atual` em `importacao_execucao.py`/`importacao_dotacao.py`)
    agrupa os anos por manifesto (via `sha256`) antes de ler qualquer arquivo, pra nunca ler o
    mesmo arquivo mais de uma vez nem duplicar linha de um ano que uma importação mais nova já
    assumiu.
    """
    resultado: dict[int, Manifesto] = {}
    for m in sorted(historico(base, diretorio_manifestos), key=lambda m: m.importado_em):
        for ano in m.anos:
            resultado[ano] = m
    return resultado


class ArquivoHistoricoAusente(FileNotFoundError):
    """O manifesto aponta para um arquivo de `data/raw/` que não existe mais."""


def agrupar_anos_por_arquivo(
    por_ano: dict[int, Manifesto],
) -> tuple[dict[str, list[int]], dict[str, Manifesto]]:
    """Agrupa os anos por `sha256` do manifesto dono — base de todo `carregar_atual`."""
    anos_por_sha: dict[str, list[int]] = {}
    manifesto_por_sha: dict[str, Manifesto] = {}
    for ano, manifesto in por_ano.items():
        anos_por_sha.setdefault(manifesto.sha256, []).append(ano)
        manifesto_por_sha[manifesto.sha256] = manifesto
    return anos_por_sha, manifesto_por_sha


def exigir_arquivos_historico(
    anos_por_sha: dict[str, list[int]],
    manifesto_por_sha: dict[str, Manifesto],
    diretorio_dados_brutos: str | Path,
) -> None:
    """Confere TODOS os arquivos antes de ler qualquer um: um ano histórico sem arquivo nunca
    pode sumir em silêncio do painel — falha cedo, nomeando ano(s) e arquivo."""
    diretorio_dados_brutos = Path(diretorio_dados_brutos)
    ausentes = [
        f"{', '.join(map(str, sorted(anos)))} → {manifesto_por_sha[sha].arquivo}"
        for sha, anos in anos_por_sha.items()
        if not (diretorio_dados_brutos / manifesto_por_sha[sha].arquivo).exists()
    ]
    if ausentes:
        raise ArquivoHistoricoAusente(
            f"Arquivo de origem ausente em {diretorio_dados_brutos} — exercício(s) sem dados: "
            + "; ".join(ausentes)
            + ". Restaure o arquivo (ele não é versionado no Git) ou reimporte esses exercícios."
        )


def situacao_historico(
    base: str,
    diretorio_dados_brutos: str | Path,
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
) -> pd.DataFrame:
    """Uma linha por exercício: de qual extração vem (a mesma que `carregar_atual` usa) e se o
    arquivo de origem existe. Somente leitura — não lê os xlsx nem grava nada."""
    diretorio_dados_brutos = Path(diretorio_dados_brutos)
    linhas = [
        {
            "exercicio": ano,
            "data_extracao": manifesto.data_extracao,
            "sha256_curto": manifesto.sha256[:8],
            "arquivo": manifesto.arquivo,
            "arquivo_presente": (diretorio_dados_brutos / manifesto.arquivo).exists(),
        }
        for ano, manifesto in sorted(manifestos_por_ano(base, diretorio_manifestos).items())
    ]
    return pd.DataFrame(
        linhas,
        columns=["exercicio", "data_extracao", "sha256_curto", "arquivo", "arquivo_presente"],
    )


def historico_como_tabela(
    base: str,
    medidas: Sequence[str],
    diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO,
    *,
    contagem_destaque: str | None = None,
) -> pd.DataFrame:
    """Uma linha por importação, com totais — pronto para exibir na aba.

    `contagem_destaque` inclui uma coluna extra lida de `Manifesto.contagens` sob o próprio
    nome (ex.: "linhas" na Execução) — cada base decide qual das suas contagens é a mais
    relevante para essa tabela-resumo; as demais continuam disponíveis em `m.contagens`.
    """
    registros = []
    for m in historico(base, diretorio_manifestos):
        registro = {
            "data_extracao": m.data_extracao,
            "importado_em": m.importado_em,
            "arquivo": m.arquivo,
            "sha256_curto": m.sha256[:8],
            "exercicios": ", ".join(map(str, m.anos)),
        }
        if contagem_destaque is not None:
            registro[contagem_destaque] = m.contagens.get(contagem_destaque)
        registro.update({medida: m.totais[medida] for medida in medidas})
        registros.append(registro)
    return pd.DataFrame(registros)
