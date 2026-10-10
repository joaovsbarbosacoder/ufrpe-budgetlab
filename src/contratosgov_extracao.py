"""
Extração incremental, delta e gravação versionada do cadastro de contratos (Contratos.gov.br).

Camada: orquestração da base Contratos.gov.br — acima do cliente HTTP (`contratosgov_api`) e das
tabelas derivadas (`contratos_cadastro`), abaixo da interface. Não importa Streamlit.

Fluxo (spec §5):
  1. `consultar` busca as listas ativa e inativa da UG, mantém só `tipo == "Contrato"` e monta a
     fotografia NOVA, sempre completa (todo contrato tem detalhe). O detalhe (`/historico` e
     `/empenhos`) é consultado quando: atualização completa; contrato ausente da fotografia
     anterior; vigente ou a iniciar pela vigência calculada (datas do item NOVO da lista,
     `inativo` = veio da lista de inativos); item da lista diferente do anterior (comparação
     sem a chave `links`, que só traz URLs); ou mudou de lista (ativo <-> inativo). Os demais
     copiam o detalhe da fotografia anterior com `origem = "reaproveitado:<sha12>"`, onde o sha12
     é o da fotografia em que o detalhe foi realmente consultado (origem já reaproveitada é
     mantida). Resposta fora do formato (lista que não é lista, item que não é objeto ou sem `id`) levanta
     `ErroDadoContratosGov`. Qualquer `ErroApiContratosGov` propaga: nada parcial é devolvido nem gravado.
  2. `calcular_delta` compara a anterior com a nova, por contrato. Termos e NEs são comparados só
     entre contratos presentes nas duas fotografias (contrato novo/ausente já é a mudança).
     Vigência e valor global comparam o texto bruto da API (`vigencia_fim`, `valor_global`).
  3. `gravar` (tudo ou nada): se houver remoção (contrato ausente, termo removido, NE
     desvinculada) e o usuário não declarou ciência, levanta `ConfirmacaoNecessaria` ANTES de
     escrever qualquer arquivo. Depois valida a fotografia montando as tabelas derivadas (erro de
     dado aborta sem gravar), grava o JSON canônico imutável em `DIRETORIO_FOTOGRAFIAS` (nunca
     sobrescreve: `destino_sem_sobrescrever`) e o manifesto em `DIRETORIO_MANIFESTOS`.

Nada é escrito fora de `DIRETORIO_FOTOGRAFIAS` e `DIRETORIO_MANIFESTOS` (atributos de módulo
lidos em tempo de chamada, para a página e os testes poderem trocá-los). A fotografia gravada
não carrega `_sha256`: essa chave é injetada só em memória por `carregar_atual`.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from src.contratos_cadastro import (
    ErroDadoContratosGov,
    data_iso,
    montar_contratos,
    montar_empenhos,
    montar_termos,
    resumo,
    situacao_vigencia,
)
from src.importacao_versionada import (
    DIRETORIO_MANIFESTOS_PADRAO,
    Manifesto,
    destino_sem_sobrescrever,
    historico,
)

BASE = "contratosgov"
UG_UFRPE = "153165"
DIRETORIO_FOTOGRAFIAS = Path("data/raw/contratosgov")
DIRETORIO_MANIFESTOS = DIRETORIO_MANIFESTOS_PADRAO

VERSAO_FORMATO = 1
TIPO_CONTRATO = "Contrato"
PREFIXO_REAPROVEITADO = "reaproveitado:"
CAMPOS_MOVIMENTO_NE = (
    "empenhado", "aliquidar", "liquidado", "pago", "rpinscrito", "rpaliquidar", "rpliquidado", "rppago",
)


class FotografiaAusente(FileNotFoundError):
    """O manifesto atual aponta para uma fotografia que não existe em disco."""


class ConfirmacaoNecessaria(RuntimeError):
    """A gravação removeria itens (contrato, termo ou NE) e o usuário não declarou ciência."""


def _dir_manifestos(d: Path | None) -> Path:
    return Path(d) if d is not None else Path(DIRETORIO_MANIFESTOS)


def _dir_fotografias(d: Path | None) -> Path:
    return Path(d) if d is not None else Path(DIRETORIO_FOTOGRAFIAS)


def _agora_iso(momento: datetime) -> str:
    return momento.replace(microsecond=0).isoformat()


def _sha256(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


# --------------------------------------------------------------------------------------
# Leitura da fotografia atual
# --------------------------------------------------------------------------------------

def carregar_atual(
    dir_manifestos: Path | None = None, dir_fotografias: Path | None = None
) -> tuple[dict | None, Manifesto | None]:
    """Fotografia e manifesto atuais, ou `(None, None)` se nunca houve gravação.

    A fotografia devolvida traz `_sha256` (do manifesto) injetado. Manifesto apontando arquivo
    inexistente -> `FotografiaAusente`; arquivo cujo conteúdo não confere com o sha256 do
    manifesto -> `ValueError` (a fotografia é imutável; alteração não pode passar em silêncio).
    """
    manifesto = Manifesto.atual(_dir_manifestos(dir_manifestos), base=BASE)
    if manifesto is None:
        return None, None
    caminho = _dir_fotografias(dir_fotografias) / manifesto.arquivo
    if not caminho.exists():
        raise FotografiaAusente(
            f"O manifesto atual do cadastro de contratos aponta para {manifesto.arquivo}, que não "
            f"existe em {caminho.parent}. Restaure o arquivo (ele não é versionado no Git) ou faça "
            "uma carga completa na aba Atualizar da página Contratos."
        )
    conteudo = caminho.read_bytes()
    sha = _sha256(conteudo)
    if sha != manifesto.sha256:
        raise ValueError(
            f"A fotografia {caminho} foi alterada depois de gravada: sha256 {sha[:12]} difere do "
            f"manifesto ({manifesto.sha256[:12]})."
        )
    fotografia = json.loads(conteudo.decode("utf-8"))
    fotografia["_sha256"] = manifesto.sha256
    return fotografia, manifesto


def historico_atualizacoes(dir_manifestos: Path | None = None) -> list[Manifesto]:
    """Manifestos de todas as gravações, mais recente primeiro."""
    return sorted(
        historico(BASE, _dir_manifestos(dir_manifestos)),
        key=lambda m: (m.data_extracao, m.importado_em),
        reverse=True,
    )


# --------------------------------------------------------------------------------------
# Consulta com política incremental
# --------------------------------------------------------------------------------------

def _itens(fotografia: dict | None) -> dict[str, tuple[dict, bool]]:
    """{contrato_id: (item da lista, inativo_api)}."""
    if not fotografia:
        return {}
    saida = {}
    for chave, inativo in (("lista_ativos", False), ("lista_inativos", True)):
        for item in fotografia.get(chave) or []:
            saida[str(item["id"])] = (item, inativo)
    return saida


def _sem_links(item: dict) -> dict:
    return {k: v for k, v in item.items() if k != "links"}


def _exigir_lista(resposta, endpoint: str) -> list:
    """Resposta de endpoint de lista precisa ser uma lista JSON (nunca vira lista vazia em silêncio)."""
    if not isinstance(resposta, list):
        raise ErroDadoContratosGov(
            f"Resposta de {endpoint} fora do formato: esperada lista JSON, veio {type(resposta).__name__}."
        )
    return resposta


def _so_contratos(resposta, endpoint: str) -> list[dict]:
    """Valida a lista (itens objeto) e mantém só `tipo == "Contrato"`; contrato sem `id` é erro."""
    contratos = []
    for posicao, item in enumerate(_exigir_lista(resposta, endpoint)):
        if not isinstance(item, dict):
            raise ErroDadoContratosGov(
                f"Item {posicao} de {endpoint} fora do formato: esperado objeto JSON, veio {type(item).__name__}."
            )
        if item.get("tipo") != TIPO_CONTRATO:
            continue
        if item.get("id") in (None, ""):
            raise ErroDadoContratosGov(
                f"Item {posicao} de {endpoint} (número {item.get('numero')!r}) sem o campo 'id'."
            )
        contratos.append(item)
    return contratos


def _precisa_detalhe(
    cid: str, item: dict, inativo: bool, ant_itens: dict, anterior: dict | None,
    referencia: date, endpoint: str,
) -> bool:
    if anterior is None or cid not in ant_itens or cid not in (anterior.get("detalhes") or {}):
        return True
    inicio = data_iso(item.get("vigencia_inicio"), contrato_id=cid, endpoint=endpoint, campo="vigencia_inicio")
    fim = data_iso(item.get("vigencia_fim"), contrato_id=cid, endpoint=endpoint, campo="vigencia_fim")
    if situacao_vigencia(inicio, fim, inativo, referencia) in ("vigente", "a_iniciar"):
        return True
    item_ant, inativo_ant = ant_itens[cid]
    return inativo_ant != inativo or _sem_links(item_ant) != _sem_links(item)


def consultar(
    cliente,
    anterior: dict | None,
    *,
    referencia: date,
    agora: datetime,
    completa: bool = False,
    progresso: Callable[[int, int], None] | None = None,
) -> dict:
    """Monta a fotografia nova (formato da spec §5). Erros da API propagam sem resultado parcial.

    `progresso(feito, total)` é chamado com `(0, total)` antes dos detalhes e após cada contrato
    reconsultado; `total` = contratos cujo detalhe será consultado.
    """
    consultado_em = _agora_iso(agora)
    ug = UG_UFRPE
    lista_ativos = _so_contratos(cliente.contratos_ug(ug), f"/api/contrato/ug/{ug}")
    lista_inativos = _so_contratos(cliente.contratos_inativos_ug(ug), f"/api/contrato/inativo/ug/{ug}")

    sha12 = None
    if anterior is not None and not completa:
        if "_sha256" not in anterior:
            raise ValueError("Fotografia anterior sem '_sha256' (use carregar_atual para lê-la).")
        sha12 = anterior["_sha256"][:12]
    ant_itens = _itens(anterior)

    alvos: list[str] = []
    for itens, inativo, endpoint in (
        (lista_ativos, False, f"/api/contrato/ug/{ug}"),
        (lista_inativos, True, f"/api/contrato/inativo/ug/{ug}"),
    ):
        for item in itens:
            cid = str(item["id"])
            if completa or _precisa_detalhe(cid, item, inativo, ant_itens, anterior, referencia, endpoint):
                alvos.append(cid)

    detalhes: dict[str, dict] = {}
    total = len(alvos)
    if progresso:
        progresso(0, total)
    for n, cid in enumerate(alvos, start=1):
        detalhes[cid] = {
            "historico": _exigir_lista(cliente.historico(cid), f"/api/contrato/{cid}/historico"),
            "empenhos": _exigir_lista(cliente.empenhos(cid), f"/api/contrato/{cid}/empenhos"),
            "consultado_em": consultado_em,
            "origem": "consulta",
        }
        if progresso:
            progresso(n, total)

    for cid in _itens({"lista_ativos": lista_ativos, "lista_inativos": lista_inativos}):
        if cid in detalhes:
            continue
        det = copy.deepcopy(anterior["detalhes"][cid])
        if not str(det.get("origem") or "").startswith(PREFIXO_REAPROVEITADO):
            det["origem"] = f"{PREFIXO_REAPROVEITADO}{sha12}"
        detalhes[cid] = det

    return {
        "versao_formato": VERSAO_FORMATO,
        "consultado_em": consultado_em,
        "ug": ug,
        "lista_ativos": lista_ativos,
        "lista_inativos": lista_inativos,
        "detalhes": detalhes,
    }


# --------------------------------------------------------------------------------------
# Delta
# --------------------------------------------------------------------------------------

@dataclass
class Delta:
    """Mudanças da fotografia anterior para a nova, por contrato (spec §5)."""

    contratos_novos: list[dict] = field(default_factory=list)
    contratos_ausentes: list[dict] = field(default_factory=list)
    termos_novos: list[dict] = field(default_factory=list)
    termos_removidos: list[dict] = field(default_factory=list)
    vigencia_alterada: list[dict] = field(default_factory=list)
    valor_global_alterado: list[dict] = field(default_factory=list)
    situacao_alterada: list[dict] = field(default_factory=list)
    nes_novas: list[dict] = field(default_factory=list)
    nes_removidas: list[dict] = field(default_factory=list)
    nes_movimentadas: int = 0

    def exige_confirmacao(self) -> bool:
        return bool(self.contratos_ausentes or self.termos_removidos or self.nes_removidas)

    def contagens(self) -> dict[str, int]:
        return {
            f"delta_{f.name}": (getattr(self, f.name) if f.name == "nes_movimentadas" else len(getattr(self, f.name)))
            for f in fields(self)
        }


def _termos(fotografia: dict, cid: str) -> dict[str, dict]:
    return {
        str(t.get("id")): t
        for t in ((fotografia.get("detalhes") or {}).get(cid, {}).get("historico") or [])
    }


def _nes(fotografia: dict, cid: str) -> dict[str, dict]:
    return {
        f"{e.get('unidade_gestora')}{e.get('gestao')}{e.get('numero')}": e
        for e in ((fotografia.get("detalhes") or {}).get(cid, {}).get("empenhos") or [])
    }


def calcular_delta(anterior: dict | None, nova: dict) -> Delta:
    delta = Delta()
    ant, nov = _itens(anterior), _itens(nova)

    def ident(cid, item):
        return {"contrato_id": cid, "numero": item.get("numero")}

    for cid, (item, _) in nov.items():
        if cid not in ant:
            delta.contratos_novos.append(ident(cid, item))
    for cid, (item, _) in ant.items():
        if cid not in nov:
            delta.contratos_ausentes.append(ident(cid, item))

    for cid, (item, inativo) in nov.items():
        if cid not in ant:
            continue
        item_ant, inativo_ant = ant[cid]
        base = ident(cid, item)
        for campo, destino in (("vigencia_fim", delta.vigencia_alterada), ("valor_global", delta.valor_global_alterado)):
            if item_ant.get(campo) != item.get(campo):
                destino.append({**base, "antes": item_ant.get(campo), "depois": item.get(campo)})
        if inativo_ant != inativo:
            delta.situacao_alterada.append({**base, "antes": inativo_ant, "depois": inativo})

        t_ant, t_nov = _termos(anterior, cid), _termos(nova, cid)
        for tid, termo in t_nov.items():
            if tid not in t_ant:
                delta.termos_novos.append({**base, "termo_id": tid, "tipo": termo.get("tipo"), "termo_numero": termo.get("numero")})
        for tid, termo in t_ant.items():
            if tid not in t_nov:
                delta.termos_removidos.append({**base, "termo_id": tid, "tipo": termo.get("tipo"), "termo_numero": termo.get("numero")})

        n_ant, n_nov = _nes(anterior, cid), _nes(nova, cid)
        for ne_ccor, ne in n_nov.items():
            if ne_ccor not in n_ant:
                delta.nes_novas.append({**base, "ne_ccor": ne_ccor, "ne": ne.get("numero")})
            elif any(n_ant[ne_ccor].get(c) != ne.get(c) for c in CAMPOS_MOVIMENTO_NE):
                delta.nes_movimentadas += 1
        for ne_ccor, ne in n_ant.items():
            if ne_ccor not in n_nov:
                delta.nes_removidas.append({**base, "ne_ccor": ne_ccor, "ne": ne.get("numero")})
    return delta


# --------------------------------------------------------------------------------------
# Gravação
# --------------------------------------------------------------------------------------

def gravar(
    nova: dict,
    delta: Delta,
    *,
    ciente_remocao: bool = False,
    importado_em: datetime,
    referencia: date,
    dir_manifestos: Path | None = None,
    dir_fotografias: Path | None = None,
) -> Manifesto:
    """Grava a fotografia (imutável) e o manifesto. Tudo ou nada."""
    if delta.exige_confirmacao() and not ciente_remocao:
        raise ConfirmacaoNecessaria(
            "A atualização remove itens da fotografia anterior "
            f"({len(delta.contratos_ausentes)} contrato(s) ausente(s), "
            f"{len(delta.termos_removidos)} termo(s) removido(s), "
            f"{len(delta.nes_removidas)} NE(s) desvinculada(s)). Confirme a ciência para gravar."
        )
    dir_m, dir_f = _dir_manifestos(dir_manifestos), _dir_fotografias(dir_fotografias)

    fotografia = {k: v for k, v in nova.items() if k != "_sha256"}
    # Validação antes de qualquer escrita: erro de dado aborta sem gravar.
    contratos = montar_contratos(fotografia, referencia)
    termos = montar_termos(fotografia)
    empenhos = montar_empenhos(fotografia)
    r = resumo(contratos)
    origens = [str(d.get("origem") or "") for d in fotografia["detalhes"].values()]

    conteudo = json.dumps(fotografia, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    sha = _sha256(conteudo)
    destino, ja_existe = destino_sem_sobrescrever(dir_f, f"{BASE}_{sha[:12]}.json", sha)

    manifesto = Manifesto(
        base=BASE,
        arquivo=destino.name,
        sha256=sha,
        data_extracao=fotografia["consultado_em"],
        importado_em=_agora_iso(importado_em),
        anos=[],
        totais={"valor_global_vigentes": float(r["valor_global_vigentes"])},
        totais_por_ano={},
        contagens={
            "contratos": r["total"],
            "vigentes": r["vigentes"],
            "termos": int(len(termos)),
            "empenhos": int(len(empenhos)),
            "reconsultados": sum(o == "consulta" for o in origens),
            "reaproveitados": sum(o.startswith(PREFIXO_REAPROVEITADO) for o in origens),
        } | delta.contagens(),
    )

    if not ja_existe:
        dir_f.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_name(destino.name + ".tmp")
        temporario.write_bytes(conteudo)
        temporario.replace(destino)
    manifesto.salvar(dir_m)
    return manifesto
