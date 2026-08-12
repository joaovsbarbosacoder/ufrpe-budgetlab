"""
Importação versionada da base ANUAL de Execução da Despesa.

Camada: orquestração de importação (acima do leitor, abaixo da interface).
Não importa Streamlit.

Política adotada (decisão do projeto):
  * SUBSTITUIÇÃO TOTAL — a extração mais recente é a verdade completa. Não há merge de
    exercícios entre arquivos diferentes.
  * A data de referência da extração vem da data de modificação do arquivo (mtime).

O que fica versionado não são os dados, e sim o MANIFESTO de cada importação: um JSON pequeno
com hash, data e totais por exercício. Ele é a âncora de rastreabilidade — permite responder
"esses R$ X de 2026 são de qual foto?" e mostrar o que mudou entre uma extração e a seguinte,
inclusive em exercícios antigos (anulação e reprocessamento alteram o passado).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.execucao_anual import MEDIDAS, ler_execucao_anual, reconciliar, validar

DIRETORIO_MANIFESTOS_PADRAO = Path("data/manifestos")
NOME_PONTEIRO = "execucao_anual_atual.json"
TOLERANCIA = 0.01


# --------------------------------------------------------------------------------------
# Manifesto
# --------------------------------------------------------------------------------------

@dataclass
class Manifesto:
    """Identidade verificável de uma extração importada."""

    base: str
    arquivo: str
    sha256: str
    data_extracao: str        # ISO, derivada do mtime do arquivo
    importado_em: str         # ISO, momento da importação
    linhas: int
    linhas_empenho: int
    linhas_item_execucao: int
    notas_empenho_distintas: int
    anos: list[int]
    totais: dict[str, float]
    totais_por_ano: dict[str, dict[str, float]]

    @property
    def rotulo(self) -> str:
        return f"{self.data_extracao[:10]}_{self.sha256[:8]}"

    def salvar(self, diretorio: Path) -> Path:
        diretorio = Path(diretorio)
        diretorio.mkdir(parents=True, exist_ok=True)
        caminho = diretorio / f"{self.base}_{self.rotulo}.json"
        conteudo = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        caminho.write_text(conteudo, encoding="utf-8")
        (diretorio / NOME_PONTEIRO).write_text(conteudo, encoding="utf-8")
        return caminho

    @classmethod
    def carregar(cls, caminho: Path) -> "Manifesto":
        return cls(**json.loads(Path(caminho).read_text(encoding="utf-8")))

    @classmethod
    def atual(cls, diretorio: Path = DIRETORIO_MANIFESTOS_PADRAO) -> "Manifesto | None":
        ponteiro = Path(diretorio) / NOME_PONTEIRO
        return cls.carregar(ponteiro) if ponteiro.exists() else None


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _data_extracao(caminho: Path) -> str:
    return datetime.fromtimestamp(caminho.stat().st_mtime).replace(microsecond=0).isoformat()


def gerar_manifesto(df: pd.DataFrame, caminho: Path, base: str = "execucao_anual") -> Manifesto:
    caminho = Path(caminho)
    r = reconciliar(df)
    return Manifesto(
        base=base,
        arquivo=caminho.name,
        sha256=_sha256(caminho),
        data_extracao=_data_extracao(caminho),
        importado_em=datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat(),
        linhas=r["linhas"],
        linhas_empenho=r["linhas_empenho"],
        linhas_item_execucao=r["linhas_item_execucao"],
        notas_empenho_distintas=r["notas_empenho_distintas"],
        anos=r["anos"],
        totais=r["totais"],
        totais_por_ano={str(a): v for a, v in r["totais_por_ano"].items()},
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
    anos_removidos: list[int] = field(default_factory=list)
    anos_alterados: dict[int, dict[str, dict[str, float]]] = field(default_factory=dict)
    variacao_total: dict[str, float] = field(default_factory=dict)
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
            linhas.append(f"Exercícios que sumiram: {', '.join(map(str, self.anos_removidos))}.")
        for ano, medidas in sorted(self.anos_alterados.items()):
            partes = [f"{m} {v['diferenca']:+,.2f}" for m, v in medidas.items()]
            linhas.append(f"{ano}: " + "; ".join(partes))
        if not linhas:
            linhas.append("Exercícios e totais idênticos, apesar do arquivo ser diferente.")
        return linhas


def comparar(anterior: Manifesto | None, novo: Manifesto) -> Delta:
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
            "Como a política é de substituição total, esses exercícios deixarão de existir no painel."
        )

    ano_mais_recente_ant = max(anos_ant) if anos_ant else None
    for ano in sorted(anos_ant & anos_novo):
        mudancas = {}
        for m in MEDIDAS:
            antes = float(anterior.totais_por_ano[str(ano)][m])
            depois = float(novo.totais_por_ano[str(ano)][m])
            if abs(depois - antes) > TOLERANCIA:
                mudancas[m] = {"antes": antes, "depois": depois, "diferenca": round(depois - antes, 2)}
        if mudancas:
            delta.anos_alterados[ano] = mudancas
            if ano_mais_recente_ant is not None and ano < ano_mais_recente_ant:
                delta.alertas.append(
                    f"{ano} mudou retroativamente — provável anulação ou reprocessamento. "
                    "Números já divulgados desse exercício precisam ser reconferidos."
                )

    delta.variacao_total = {
        m: round(float(novo.totais[m]) - float(anterior.totais[m]), 2) for m in MEDIDAS
    }
    return delta


# --------------------------------------------------------------------------------------
# Importação
# --------------------------------------------------------------------------------------

@dataclass
class ResultadoImportacao:
    df: pd.DataFrame
    manifesto: Manifesto
    delta: Delta
    validacao: object            # RelatorioValidacao
    caminho_manifesto: Path | None

    @property
    def ok(self) -> bool:
        return bool(getattr(self.validacao, "ok", False))


def importar(
    caminho: str | Path,
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

    df = ler_execucao_anual(caminho)
    manifesto = gerar_manifesto(df, caminho)
    anterior = Manifesto.atual(diretorio_manifestos)
    delta = comparar(anterior, manifesto)

    esperado = None  # nada a conferir contra: a nova extração define os próprios totais
    relatorio = validar(df, esperado=esperado)

    caminho_manifesto = None
    if registrar and relatorio.ok and not delta.mesma_extracao:
        caminho_manifesto = manifesto.salvar(diretorio_manifestos)

    return ResultadoImportacao(
        df=df,
        manifesto=manifesto,
        delta=delta,
        validacao=relatorio,
        caminho_manifesto=caminho_manifesto,
    )


def historico(diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO) -> list[Manifesto]:
    """Manifestos de todas as importações já feitas, do mais antigo ao mais recente."""
    diretorio = Path(diretorio_manifestos)
    if not diretorio.exists():
        return []
    arquivos = [p for p in diretorio.glob("execucao_anual_*.json") if p.name != NOME_PONTEIRO]
    return sorted((Manifesto.carregar(p) for p in arquivos), key=lambda m: m.data_extracao)


def historico_como_tabela(diretorio_manifestos: str | Path = DIRETORIO_MANIFESTOS_PADRAO) -> pd.DataFrame:
    """Uma linha por importação, com totais — pronto para exibir na aba."""
    registros = []
    for m in historico(diretorio_manifestos):
        registros.append(
            {
                "data_extracao": m.data_extracao,
                "importado_em": m.importado_em,
                "arquivo": m.arquivo,
                "sha256_curto": m.sha256[:8],
                "linhas": m.linhas,
                "exercicios": ", ".join(map(str, m.anos)),
                **{m_: m.totais[m_] for m_ in MEDIDAS},
            }
        )
    return pd.DataFrame(registros)


if __name__ == "__main__":
    import sys

    resultado = importar(sys.argv[1], *(sys.argv[2:3] or []))
    print("Extração:", resultado.manifesto.data_extracao, "| hash", resultado.manifesto.sha256[:8])
    print("Linhas:", resultado.manifesto.linhas, "| exercícios:", resultado.manifesto.anos)
    print("Totais:", resultado.manifesto.totais)
    print("Validação OK:", resultado.ok, "| erros:", resultado.validacao.erros or "nenhum")
    print("Alertas:", resultado.validacao.alertas or "nenhum")
    print("--- mudanças desde a última importação ---")
    for linha in resultado.delta.resumo_texto():
        print(" ", linha)
    for alerta in resultado.delta.alertas:
        print("  ⚠", alerta)
