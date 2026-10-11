"""
Linha do tempo das vigências por contrato — Contratos Contínuos × Contratos.gov (11/10/2026).

Camada: regra pura (pandas/datetime; sem Streamlit, sem leitura de arquivo). Somente LEITURA: monta, para cada
contrato do cadastro de Contínuos, os períodos de vigência (contrato original e termos aditivos de vigência do
Contratos.gov), os marcadores dos termos (reajuste, acréscimo/supressão, apostilamento, rescisão) e a situação da
vigência. Nada é gravado; a tela está em `src/ui_linha_tempo_vigencias.py`.

Regras:
  * Uma linha por `contrato_numero` (o cadastro pode ter uma linha por NE).
  * Segmentos: o termo "Contrato" do gov e cada Termo Aditivo cuja qualificação inclui VIGÊNCIA (acréscimo/supressão
    sozinho não muda a vigência). Contrato sem ligação ao gov: só a vigência do cadastro (sem início conhecido).
  * Marcadores: Termo Aditivo com REAJUSTE (R) e/ou ACRÉSCIMO/SUPRESSÃO (A), na data do novo valor (senão no início
    do termo, senão na assinatura); apostilamento (P) e rescisão (X) na assinatura.
  * Fim da vigência: o do gov quando ligado (senão o efetivo do cadastro); `diverge` quando os dois existem e diferem.
  * Situação: sem ligação ao gov (neutro), sem data de fim (aviso), encerrado (neutro — fim passado não é problema
    em si), vence em até `DIAS_ALERTA` dias (aviso) ou vigente (ok).

Contrato público:
    Segmento, Evento, LinhaDoTempo
    situacao_vigencia(ligado, fim, hoje, dias_alerta=DIAS_ALERTA) -> (rótulo, tom)
    linhas_do_tempo(cadastro, contratos_gov, termos_gov, hoje) -> list[LinhaDoTempo]
    contagens(linhas, hoje) -> dict[str, int]
    janela_padrao(linhas, hoje) -> (início, fim)
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

DIAS_ALERTA = 90


@dataclass(frozen=True)
class Segmento:
    inicio: date | None  # None = início desconhecido (só a vigência do cadastro)
    fim: date
    rotulo: str
    tipo: str  # contrato | ta | cadastro


@dataclass(frozen=True)
class Evento:
    data: date
    marca: str  # R (reajuste), A (acréscimo/supressão), RA, P (apostilamento), X (rescisão)
    rotulo: str


@dataclass(frozen=True)
class LinhaDoTempo:
    contrato: str
    fornecedor: str
    ligado: bool
    fim_gov: date | None
    fim_cadastro: date | None
    situacao: str
    tom: str
    segmentos: list[Segmento] = field(default_factory=list)
    eventos: list[Evento] = field(default_factory=list)

    @property
    def fim(self) -> date | None:
        return self.fim_gov or self.fim_cadastro

    @property
    def diverge(self) -> bool:
        return bool(self.ligado and self.fim_gov and self.fim_cadastro and self.fim_gov != self.fim_cadastro)


def _vazio(valor: object) -> bool:
    return valor is None or (not isinstance(valor, (list, dict)) and bool(pd.isna(valor)))


def _data(valor: object) -> date | None:
    if _vazio(valor):
        return None
    if isinstance(valor, (pd.Timestamp, datetime)):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def _sem_acento(texto: object) -> str:
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii").upper()


def _texto(valor: object) -> str:
    return "" if _vazio(valor) else str(valor)


def situacao_vigencia(ligado: bool, fim: date | None, hoje: date, dias_alerta: int = DIAS_ALERTA) -> tuple[str, str]:
    """Rótulo e tom (`ok`, `warn`, `neutro`) da situação da vigência."""

    if not ligado:
        return "Sem ligação ao gov", "neutro"
    if fim is None:
        return "Sem data de fim", "warn"
    if fim < hoje:
        return "Encerrado", "neutro"
    dias = (fim - hoje).days
    if dias <= dias_alerta:
        return f"Vence em {dias} dia(s)", "warn"
    return "Vigente", "ok"


def _termos_do_contrato(termos: pd.DataFrame, contrato_id: str) -> tuple[list[Segmento], list[Evento]]:
    segmentos: list[Segmento] = []
    eventos: list[Evento] = []
    for _, termo in termos[termos["contrato_id"].astype(str) == contrato_id].iterrows():
        tipo = _sem_acento(termo.get("tipo"))
        numero = _texto(termo.get("numero"))
        inicio, fim = _data(termo.get("vigencia_inicio")), _data(termo.get("vigencia_fim"))
        assinatura = _data(termo.get("data_assinatura"))
        qualificacao = _texto(termo.get("qualificacao_termo"))
        q = _sem_acento(qualificacao)
        if tipo == "CONTRATO":
            if inicio and fim:
                segmentos.append(Segmento(inicio, fim, f"Contrato {numero}", "contrato"))
        elif tipo == "TERMO ADITIVO":
            if "VIGENCIA" in q and inicio and fim:
                segmentos.append(Segmento(inicio, fim, f"TA {numero}", "ta"))
            marca = ("R" if "REAJUSTE" in q else "") + ("A" if "ACRESCIMO" in q else "")
            dia = _data(termo.get("data_inicio_novo_valor")) or inicio or assinatura
            if marca and dia:
                eventos.append(Evento(dia, marca, f"TA {numero}: {qualificacao}"))
        elif "APOSTILAMENTO" in tipo:
            if assinatura:
                eventos.append(Evento(assinatura, "P", f"Apostilamento {numero}"))
        elif "RESCIS" in tipo:
            dia = assinatura or inicio
            if dia:
                eventos.append(Evento(dia, "X", f"Rescisão {numero}"))
    segmentos.sort(key=lambda s: (s.inicio or date.min, s.fim))
    eventos.sort(key=lambda e: (e.data, e.marca))
    return segmentos, eventos


def linhas_do_tempo(
    cadastro: pd.DataFrame, contratos_gov: pd.DataFrame | None, termos_gov: pd.DataFrame | None, hoje: date,
) -> list[LinhaDoTempo]:
    """Uma linha por contrato do cadastro, ordenadas pelo fim da vigência (os que vencem primeiro no topo; sem data
    por último). Sem fotografia do gov (`contratos_gov` nulo), todos ficam "sem ligação"."""

    gov = None
    if contratos_gov is not None and not contratos_gov.empty:
        gov = contratos_gov.assign(contrato_id=contratos_gov["contrato_id"].astype(str)).set_index("contrato_id")
    linhas = []
    for numero, grupo in cadastro.groupby("contrato_numero", sort=False):
        linha = grupo.iloc[0]
        contrato_id = linha.get("contratosgov_id") if "contratosgov_id" in grupo.columns else None
        fim_cadastro = _data(linha.get("vigencia_fim_efetiva", linha.get("vigencia_fim")))
        ligado = gov is not None and not _vazio(contrato_id) and str(contrato_id) in gov.index
        if ligado:
            fim_gov = _data(gov.loc[str(contrato_id), "vigencia_fim"])
            segmentos, eventos = ([], []) if termos_gov is None else _termos_do_contrato(termos_gov, str(contrato_id))
        else:
            fim_gov = None
            segmentos = [Segmento(None, fim_cadastro, "Vigência do cadastro", "cadastro")] if fim_cadastro else []
            eventos = []
        situacao, tom = situacao_vigencia(ligado, fim_gov or fim_cadastro, hoje)
        linhas.append(LinhaDoTempo(
            contrato=str(numero), fornecedor=_texto(linha.get("fornecedor")), ligado=ligado, fim_gov=fim_gov,
            fim_cadastro=fim_cadastro, situacao=situacao, tom=tom, segmentos=segmentos, eventos=eventos,
        ))
    return sorted(linhas, key=lambda l: (l.fim is None, l.fim or date.max, l.contrato))


def contagens(linhas: list[LinhaDoTempo], hoje: date) -> dict[str, int]:
    return {
        "contratos": len(linhas),
        "vigentes": sum(l.tom == "ok" for l in linhas),
        "vencem_90_dias": sum(l.situacao.startswith("Vence") for l in linhas),
        "encerrados": sum(l.situacao == "Encerrado" for l in linhas),
        "sem_ligacao": sum(not l.ligado for l in linhas),
        "sem_data": sum(l.ligado and l.fim is None for l in linhas),
        "divergentes": sum(l.diverge for l in linhas),
    }


def janela_padrao(linhas: list[LinhaDoTempo], hoje: date) -> tuple[date, date]:
    """De janeiro de dois anos antes de `hoje` a dezembro do ano do último fim de vigência (no máximo 4 anos à frente)."""

    fins = [l.fim for l in linhas if l.fim is not None]
    ultimo = max([hoje.year, *(f.year for f in fins)])
    return date(hoje.year - 2, 1, 1), date(min(ultimo, hoje.year + 4), 12, 31)
