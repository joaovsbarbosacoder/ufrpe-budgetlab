"""
Sincronização bidirecional entre o cadastro de Prazos Orçamentários e o Google Agenda.

Camada: regra de negócio da integração. Não acessa a rede diretamente — recebe um cliente com
a interface de `src.google_agenda.ClienteGoogleAgenda` (injeção), o que permite testar toda a
conciliação com um cliente falso. Não importa Streamlit.

Regras (decididas com o usuário em 27/09/2026 — ver
`docs/superpowers/specs/2026-09-27-google-agenda-design.md`):
- todo prazo vira um evento de DIA INTEIRO no calendário principal;
- só título, data e descrição são editáveis pelo Google; tipo, categoria, prioridade,
  responsável e antecedência viajam em `extendedProperties.private` e só se editam aqui;
- lembrete do Google limitado a 28 dias (limite da API); a criticidade "Vencendo" do
  BudgetLab continua usando `dias_antecedencia` integral;
- evento excluído no Google → prazo CONCLUÍDO (nunca excluído);
- prazo excluído no BudgetLab → evento excluído no Google;
- os dois lados alterados → vence o mais recente, sempre registrado no resumo com o valor
  descartado (rastreabilidade: nada é sobrescrito sem registro).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.google_agenda import DIRETORIO_PADRAO as DIRETORIO_AGENDA
from src.google_agenda import MARCADOR, MARCADOR_BUDGETLAB, ErroGoogleAgenda, _gravar_atomico
from src.prazos_orcamentarios import (
    DIAS_ANTECEDENCIA_PADRAO,
    DIRETORIO_PADRAO,
    PRIORIDADE_PADRAO,
    TIPO_PADRAO,
    atualizar,
    carregar_prazo,
    carregar_prazos,
    gravar_estado_sincronizacao,
)

ARQUIVO_RESUMO = "ultima_sincronizacao.json"
#: uma linha JSON por sincronização que alterou algo, teve conflito ou erro (só acrescenta).
ARQUIVO_HISTORICO = "historico_sincronizacao.jsonl"

#: limite da Calendar API para lembretes (40320 minutos = 4 semanas).
DIAS_MAXIMOS_LEMBRETE = 28
#: só visual: acrescentá-lo ou removê-lo no Google NÃO altera `concluido`.
PREFIXO_CONCLUIDO = "✓ "
INTERVALO_SINCRONIZACAO_AUTOMATICA = timedelta(minutes=5)


class ErroSincronizacao(ValueError):
    """Evento do Google que não pode ser aplicado ao prazo (ex.: título vazio)."""


def corpo_evento(prazo: dict) -> dict:
    data = date.fromisoformat(prazo["data_prazo"])
    # `or`: campo presente com null (cadastro legado/editado à mão) também usa o padrão
    dias_antecedencia = prazo.get("dias_antecedencia")
    dias_antecedencia = DIAS_ANTECEDENCIA_PADRAO if dias_antecedencia is None else int(dias_antecedencia)
    minutos = min(dias_antecedencia, DIAS_MAXIMOS_LEMBRETE) * 1440
    return {
        "summary": (PREFIXO_CONCLUIDO if prazo.get("concluido") else "") + prazo["titulo"],
        "description": prazo.get("descricao") or "",
        "start": {"date": data.isoformat()},
        "end": {"date": (data + timedelta(days=1)).isoformat()},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": minutos}]},
        "extendedProperties": {"private": {
            MARCADOR_BUDGETLAB: "1",
            MARCADOR: str(prazo["id"]),
            "tipo": str(prazo.get("tipo") or TIPO_PADRAO),
            "categoria": str(prazo.get("categoria") or ""),
            "prioridade": str(prazo.get("prioridade") or PRIORIDADE_PADRAO),
            "responsavel": str(prazo.get("responsavel") or ""),
            "dias_antecedencia": str(dias_antecedencia),
        }},
    }


def _corpo_atualizacao(prazo: dict) -> dict:
    """Corpo do `patch`: a API MESCLA objetos, então um evento que o usuário transformou em
    evento com horário manteria `dateTime` ao lado do `date` enviado (HTTP 400). Os nulos
    explícitos apagam o horário e o fuso, voltando o evento a dia inteiro."""

    corpo = corpo_evento(prazo)
    for parte in ("start", "end"):
        corpo[parte] = {**corpo[parte], "dateTime": None, "timeZone": None}
    return corpo


def campos_do_evento(evento: dict) -> dict:
    """Os 3 campos editáveis pelo Google, prontos para gravação. Rejeita evento sem título ou
    sem data (o prazo local fica intacto e o erro vai para o resumo)."""

    titulo = evento["titulo"].strip()
    if titulo.startswith(PREFIXO_CONCLUIDO.strip()):
        titulo = titulo[len(PREFIXO_CONCLUIDO.strip()):].strip()
    if not titulo:
        raise ErroSincronizacao("evento sem título no Google Agenda — alteração não aplicada.")
    if evento["data_inicio"] is None:
        raise ErroSincronizacao("evento sem data no Google Agenda — alteração não aplicada.")
    return {
        "titulo": titulo,
        "data_prazo": evento["data_inicio"].isoformat(),
        "descricao": evento["descricao"],
    }


def sincronizacao_devida(
    ultima: datetime | None, agora: datetime,
    intervalo: timedelta = INTERVALO_SINCRONIZACAO_AUTOMATICA,
) -> bool:
    """Controle da sincronização automática ao abrir a página (o Streamlit reexecuta o
    script a cada clique — sem este limite cada interação chamaria a API)."""

    return ultima is None or agora - ultima >= intervalo


@dataclass
class ResumoSincronizacao:
    executado_em: str
    criados: list[str] = field(default_factory=list)
    atualizados_no_google: list[str] = field(default_factory=list)
    atualizados_no_budgetlab: list[str] = field(default_factory=list)
    concluidos_por_exclusao: list[str] = field(default_factory=list)
    eventos_excluidos: list[str] = field(default_factory=list)
    conflitos: list[dict] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)

    def total_alteracoes(self) -> int:
        return sum(len(lista) for lista in (
            self.criados, self.atualizados_no_google, self.atualizados_no_budgetlab,
            self.concluidos_por_exclusao, self.eventos_excluidos,
        ))


def _momento(texto: str | None) -> datetime:
    if not texto:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(texto)


def _valores(origem: dict) -> dict:
    return {"titulo": origem["titulo"], "data_prazo": origem["data_prazo"], "descricao": origem.get("descricao", "")}


class _AlteradoDuranteSincronizacao(Exception):
    """O prazo foi editado (ex.: em outra aba) enquanto esta sincronização rodava."""


def _garantir_inalterado(prazo: dict, diretorio: Path) -> None:
    """Relê o registro antes de gravar: se ele mudou desde a leitura do início da
    sincronização, gravar o retrato antigo apagaria a edição sem registro. Nesse caso o
    prazo fica para a próxima sincronização (que adota o evento já criado, sem duplicar)."""

    atual = carregar_prazo(prazo["id"], diretorio)
    if atual.get("atualizado_em", atual.get("criado_em")) != prazo["atualizado_em"]:
        raise _AlteradoDuranteSincronizacao


def _vincular(prazo: dict, evento: dict, diretorio: Path) -> None:
    """Grava o estado "sincronizado" do prazo com este evento, sem carimbar alteração local."""

    _garantir_inalterado(prazo, diretorio)
    gravar_estado_sincronizacao({
        **prazo,
        "google_event_id": evento["id"],
        "sincronizado_em": prazo["atualizado_em"],
        "google_atualizado_em": evento["atualizado_em"],
    }, diretorio)


def _enviar(cliente, prazo: dict, evento: dict | None, diretorio: Path) -> None:
    """BudgetLab → Google: cria (sem evento) ou atualiza o evento e vincula."""

    if evento is None:
        novo = cliente.criar_evento(corpo_evento(prazo))
    else:
        novo = cliente.atualizar_evento(evento["id"], _corpo_atualizacao(prazo))
    _vincular(prazo, novo, diretorio)


def _receber(prazo: dict, evento: dict, diretorio: Path, agora: datetime) -> dict:
    """Google → BudgetLab: aplica os 3 campos editáveis e marca como sincronizado. Carimba
    `atualizado_em` (é uma alteração real do registro) e iguala `sincronizado_em` a ele."""

    campos = campos_do_evento(evento)
    carimbo = agora.isoformat()
    atualizado = {
        **prazo, **campos,
        "atualizado_em": carimbo,
        "sincronizado_em": carimbo,
        "google_event_id": evento["id"],
        "google_atualizado_em": evento["atualizado_em"],
    }
    _garantir_inalterado(prazo, diretorio)
    gravar_estado_sincronizacao(atualizado, diretorio)
    return atualizado


def sincronizar(cliente, diretorio: str | Path = DIRETORIO_PADRAO, agora: datetime | None = None) -> ResumoSincronizacao:
    """Concilia todos os prazos com os eventos marcados do calendário principal. Falha na
    listagem inicial propaga `ErroGoogleAgenda` sem alterar nada. Erro em um item vai para
    `resumo.erros` e não interrompe os demais (será tentado de novo na próxima vez).

    Pasta de prazos ausente (renomeada, drive indisponível) cancela tudo com
    `ErroSincronizacao`: sem ela, todos os eventos pareceriam de prazos excluídos."""

    diretorio = Path(diretorio)
    if not diretorio.exists():
        raise ErroSincronizacao(f"pasta de prazos '{diretorio}' não encontrada — sincronização cancelada.")
    agora = agora or datetime.now(timezone.utc)
    eventos = cliente.listar_eventos_de_prazos()  # pode lançar ErroGoogleAgenda: aborta aqui
    resumo = ResumoSincronizacao(executado_em=agora.isoformat())

    eventos_por_prazo: dict[str, list[dict]] = {}
    for evento in eventos:
        if evento["prazo_id"]:
            eventos_por_prazo.setdefault(evento["prazo_id"], []).append(evento)

    prazos = carregar_prazos(diretorio)
    for prazo in prazos:
        titulo = prazo.get("titulo") or prazo["id"]
        prazo.setdefault("atualizado_em", prazo.get("criado_em"))
        candidatos = eventos_por_prazo.get(prazo["id"], [])
        ativos = [e for e in candidatos if not e["cancelado"]]
        event_id = prazo.get("google_event_id")
        try:
            if event_id is None:
                if ativos:  # queda entre criar e gravar: adota em vez de duplicar
                    evento, duplicados = ativos[0], ativos[1:]
                    _enviar(cliente, prazo, evento, diretorio)
                    resumo.atualizados_no_google.append(titulo)
                elif prazo.get("removido_no_google"):
                    continue
                else:
                    duplicados = []
                    _enviar(cliente, prazo, None, diretorio)
                    resumo.criados.append(titulo)
            else:
                evento = next((e for e in ativos if e["id"] == event_id), None)
                duplicados = [e for e in ativos if e["id"] != event_id]
                if evento is None:
                    _garantir_inalterado(prazo, diretorio)
                    atualizar({**prazo, "concluido": True, "removido_no_google": True,
                               "google_event_id": None}, diretorio)
                    resumo.concluidos_por_exclusao.append(titulo)
                else:
                    mudou_local = prazo["atualizado_em"] != prazo.get("sincronizado_em")
                    mudou_google = evento["atualizado_em"] != prazo.get("google_atualizado_em")
                    if mudou_local and mudou_google:
                        google_vence = _momento(evento["atualizado_em"]) > _momento(prazo["atualizado_em"])
                        resumo.conflitos.append({
                            "titulo": titulo,
                            "vencedor": "Google" if google_vence else "BudgetLab",
                            "valor_budgetlab": _valores(prazo),
                            "valor_google": {
                                "titulo": evento["titulo"],
                                "data_prazo": evento["data_inicio"].isoformat() if evento["data_inicio"] else None,
                                "descricao": evento["descricao"],
                            },
                        })
                        if google_vence:
                            # os 3 campos vêm do Google; o resto (concluído, antecedência,
                            # tipo...) continua local e precisa chegar ao evento
                            recebido = _receber(prazo, evento, diretorio, agora)
                            _enviar(cliente, recebido, evento, diretorio)
                            titulo = recebido["titulo"]
                            resumo.atualizados_no_budgetlab.append(titulo)
                        else:
                            _enviar(cliente, prazo, evento, diretorio)
                            resumo.atualizados_no_google.append(titulo)
                    elif mudou_local:
                        _enviar(cliente, prazo, evento, diretorio)
                        resumo.atualizados_no_google.append(titulo)
                    elif mudou_google:
                        titulo = _receber(prazo, evento, diretorio, agora)["titulo"]
                        resumo.atualizados_no_budgetlab.append(titulo)
            for duplicado in duplicados:
                cliente.excluir_evento(duplicado["id"])
                resumo.eventos_excluidos.append(f"{titulo} (duplicado)")
        except _AlteradoDuranteSincronizacao:
            continue  # nada se perde: a próxima sincronização trata a versão nova
        except (ErroGoogleAgenda, ValueError, TypeError, KeyError, OSError) as erro:
            # ValueError cobre ErroSincronizacao/ErroPrazoOrcamentario e registro malformado
            # (ex.: data fora do formato ISO) — um registro ruim não interrompe os demais
            resumo.erros.append(f"{titulo}: {erro}")

    ids_locais = {prazo["id"] for prazo in prazos}
    orfaos = [
        evento
        for prazo_id, candidatos in eventos_por_prazo.items() if prazo_id not in ids_locais
        for evento in candidatos if not evento["cancelado"]
    ]
    if not prazos and len(orfaos) > 1:
        # pasta vazia com vários eventos marcados: mais provável ser pasta esvaziada/restaurada
        # do que o usuário ter excluído tudo — excluir em massa não é feito automaticamente
        resumo.erros.append(
            f"Nenhum prazo local, mas {len(orfaos)} eventos de prazos no Google: nada foi excluído "
            "por segurança. Se os prazos foram mesmo excluídos, apague os eventos no Google Agenda."
        )
        orfaos = []
    for evento in orfaos:
        try:
            cliente.excluir_evento(evento["id"])
            resumo.eventos_excluidos.append(evento["titulo"].removeprefix(PREFIXO_CONCLUIDO))
        except ErroGoogleAgenda as erro:
            resumo.erros.append(f"{evento['titulo']}: {erro}")

    return resumo


def salvar_resumo(resumo: ResumoSincronizacao, diretorio: str | Path = DIRETORIO_AGENDA) -> Path:
    """Grava a última sincronização (exibida na tela) e, se ela alterou algo, teve conflito
    ou erro, ACRESCENTA uma linha ao histórico — o resumo é substituído a cada 5 min, e o
    valor descartado num conflito não pode sumir com ele (rastreabilidade)."""

    diretorio = Path(diretorio)
    caminho = diretorio / ARQUIVO_RESUMO
    dados = asdict(resumo)
    _gravar_atomico(caminho, json.dumps(dados, ensure_ascii=False, indent=2))
    if resumo.total_alteracoes() or resumo.conflitos or resumo.erros:
        with (diretorio / ARQUIVO_HISTORICO).open("a", encoding="utf-8") as historico:
            historico.write(json.dumps(dados, ensure_ascii=False) + "\n")
    return caminho


def carregar_historico(diretorio: str | Path = DIRETORIO_AGENDA) -> list[dict]:
    caminho = Path(diretorio) / ARQUIVO_HISTORICO
    if not caminho.exists():
        return []
    return [json.loads(linha) for linha in caminho.read_text(encoding="utf-8").splitlines() if linha.strip()]


def carregar_ultimo_resumo(diretorio: str | Path = DIRETORIO_AGENDA) -> dict | None:
    caminho = Path(diretorio) / ARQUIVO_RESUMO
    if not caminho.exists():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))
