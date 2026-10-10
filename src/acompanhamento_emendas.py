"""Acompanhamento de emendas: tramitação (status + histórico), objeto e destinatário (10/2026).

Camada: regra específica da base de Emendas (sem Streamlit). Spec:
`docs/superpowers/specs/2026-10-10-emendas-acompanhamento-e-visual-design.md`.

Dados MANUAIS por emenda, guardados como eventos JSON IMUTÁVEIS em `data/emendas/acompanhamento/` (mesmo padrão de
`src/vinculos_emendas.py`): nada é editado nem apagado, o estado vigente é reconstruído pela sequência, e arquivo
ilegível ou histórico incoerente LEVANTA erro (nunca vira "sem histórico"). O relatório oficial importado não muda.

* Tramitação: cada registro leva status (lista sugerida ou "Outro" com texto), data do status (retroativa ok, futura
  não), observação opcional e responsável. O status atual é o registro não cancelado de maior data (desempate: o
  registrado por último). Corrigir um erro é CANCELAR o registro (com motivo): o original permanece no histórico.
* Complemento: objeto e destinatário (texto livre, vazio = não informado/nulo), sempre gravados juntos (retrato
  completo); o vigente é o último evento e o histórico mostra valor anterior → novo.

Chave da emenda: `(ano:int, resultado_primario_cod:str, emenda_numero:str)`. Vale para QUALQUER exercício (é
acompanhamento, não valor financeiro). O servidor valida que a chave existe (`chaves_validas`); evento de emenda que
deixou de existir é listado como órfão, nunca descartado. Não há regra de transição entre status (não definida).

Contrato público:
    ErroAcompanhamento, DIRETORIO_ACOMPANHAMENTO, STATUS_SUGERIDOS, STATUS_OUTRO
    registrar_status(...) / cancelar_status(...) / definir_complemento(...) -> dict
    carregar_eventos(diretorio) -> list[dict]
    reconstruir_tramitacao(eventos) -> DataFrame ; status_atual(tramitacao) -> DataFrame
    complemento_vigente(eventos) -> DataFrame ; historico_complemento(eventos, chave) -> DataFrame
    orfaos(eventos, chaves_validas) -> list[dict]
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from src.emendas_parlamentares import RPS_EMENDA

DIRETORIO_ACOMPANHAMENTO = Path("data/emendas/acompanhamento")
VERSAO_SCHEMA = 1
STATUS_OUTRO = "Outro"
#: lista sugerida (proposta do desenvolvimento — validar com a área antes do uso oficial). Registros antigos guardam
#: o TEXTO do status, então mudar a lista não altera o histórico.
STATUS_SUGERIDOS = (
    "Indicada",
    "Recebida pela UFRPE",
    "Em análise técnica",
    "Impedimento técnico",
    "Proposta aceita",
    "Empenhada",
    "Liquidada",
    "Paga",
    "Concluída",
    "Cancelada",
)
ACOES_EVENTO = {"registrar_status", "cancelar_status", "definir_complemento"}
MIN_STATUS_OUTRO, MAX_STATUS_OUTRO = 3, 80
MAX_OBSERVACAO, MAX_OBJETO, MAX_DESTINATARIO = 500, 500, 200
MIN_MOTIVO = 10

COLUNAS_TRAMITACAO = [
    "evento_id", "ano", "resultado_primario_cod", "emenda_numero", "status", "data_status", "observacao",
    "responsavel", "registrado_em", "cancelado", "cancelado_motivo", "cancelado_por", "cancelado_em",
]
COLUNAS_COMPLEMENTO = [
    "ano", "resultado_primario_cod", "emenda_numero", "objeto", "destinatario", "responsavel", "registrado_em",
]


class ErroAcompanhamento(ValueError):
    """Registro de acompanhamento inválido, ou log de eventos ilegível/incoerente."""


# ------------------------------------------------------------------------------------------ validações


def _texto_obrigatorio(valor: object, campo: str, minimo: int = 1) -> str:
    if not isinstance(valor, str) or len(valor.strip()) < minimo:
        detalhe = f" (mínimo de {minimo} caracteres)" if minimo > 1 else ""
        raise ErroAcompanhamento(f"{campo} é obrigatório{detalhe}.")
    return valor.strip()


def _texto_opcional(valor: object, campo: str, maximo: int) -> str | None:
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return None
    if not isinstance(valor, str):
        raise ErroAcompanhamento(f"{campo} deve ser texto.")
    texto = valor.strip()
    if not texto:
        return None
    if len(texto) > maximo:
        raise ErroAcompanhamento(f"{campo} excede {maximo} caracteres.")
    return texto


def _chave(ano: object, resultado_primario_cod: object, emenda_numero: object) -> tuple[int, str, str]:
    if isinstance(ano, bool):
        raise ErroAcompanhamento("Exercício inválido.")
    try:
        ano_inteiro = int(ano)  # type: ignore[arg-type]
        if float(ano) != ano_inteiro:  # type: ignore[arg-type]
            raise ValueError
    except (TypeError, ValueError) as erro:
        raise ErroAcompanhamento("Exercício inválido.") from erro
    rp = _texto_obrigatorio(resultado_primario_cod, "Resultado Primário").upper().removeprefix("RP").strip()
    if rp not in RPS_EMENDA:
        raise ErroAcompanhamento("O Resultado Primário deve ser 6, 7 ou 8.")
    return ano_inteiro, rp, _texto_obrigatorio(emenda_numero, "Número da emenda")


def _normalizar_validas(chaves_validas: object) -> set[tuple[int, str, str]]:
    return {_chave(*chave) for chave in chaves_validas}  # type: ignore[union-attr]


def _exigir_chave_existente(chave: tuple[int, str, str], chaves_validas: object) -> None:
    if chave not in _normalizar_validas(chaves_validas):
        raise ErroAcompanhamento("Emenda não encontrada nos dados atuais.")


def _status(status: object, status_outro: object) -> tuple[str, str | None]:
    if status == STATUS_OUTRO:
        texto = _texto_obrigatorio(status_outro, "Descrição do status", MIN_STATUS_OUTRO)
        if len(texto) > MAX_STATUS_OUTRO:
            raise ErroAcompanhamento(f"A descrição do status excede {MAX_STATUS_OUTRO} caracteres.")
        return STATUS_OUTRO, texto
    if status not in STATUS_SUGERIDOS:
        raise ErroAcompanhamento(f"Status inválido: {status!r}.")
    return str(status), None


def _data(valor: object, campo: str) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor.strip()):
        try:
            return date.fromisoformat(valor.strip())
        except ValueError:
            pass
    raise ErroAcompanhamento(f"{campo} inválida (esperado AAAA-MM-DD).")


def _id_valido(valor: object, nome: str) -> str:
    if not isinstance(valor, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", valor):
        raise ErroAcompanhamento(f"O identificador do {nome} é inválido.")
    return valor


def _validar_evento(evento: object) -> None:
    if not isinstance(evento, dict):
        raise ErroAcompanhamento("Evento de acompanhamento deve ser um objeto JSON.")
    if evento.get("versao_schema") != VERSAO_SCHEMA:
        raise ErroAcompanhamento("Versão de evento de acompanhamento não reconhecida.")
    acao = evento.get("acao")
    if acao not in ACOES_EVENTO:
        raise ErroAcompanhamento("Ação de evento de acompanhamento inválida.")
    _id_valido(evento.get("evento_id"), "evento")
    _texto_obrigatorio(evento.get("responsavel"), "Responsável")
    try:
        instante = datetime.fromisoformat(evento.get("registrado_em"))  # type: ignore[arg-type]
    except (TypeError, ValueError) as erro:
        raise ErroAcompanhamento("O evento não possui data de registro válida.") from erro
    if instante.tzinfo is None:
        raise ErroAcompanhamento("A data do evento deve informar o fuso horário.")
    if acao == "cancelar_status":
        _id_valido(evento.get("evento_alvo_id"), "evento cancelado")
        _texto_obrigatorio(evento.get("motivo"), "Motivo", MIN_MOTIVO)
        return
    _chave(evento.get("ano"), evento.get("resultado_primario_cod"), evento.get("emenda_numero"))
    if acao == "registrar_status":
        _status(evento.get("status"), evento.get("status_outro"))
        _data(evento.get("data_status"), "Data do status")
        _texto_opcional(evento.get("observacao"), "Observação", MAX_OBSERVACAO)
    else:
        _texto_opcional(evento.get("objeto"), "Objeto", MAX_OBJETO)
        _texto_opcional(evento.get("destinatario"), "Destinatário", MAX_DESTINATARIO)
        _texto_opcional(evento.get("motivo"), "Motivo", MAX_OBSERVACAO)


def _ordem(evento: dict) -> tuple[str, str]:
    return str(evento.get("registrado_em", "")), str(evento.get("evento_id", ""))


def _chave_do_evento(evento: dict) -> tuple[int, str, str]:
    return _chave(evento["ano"], evento["resultado_primario_cod"], evento["emenda_numero"])


# ------------------------------------------------------------------------------------ persistência


def _novo_evento(acao: str, responsavel: str, **campos: object) -> dict:
    return {
        "versao_schema": VERSAO_SCHEMA,
        "evento_id": str(uuid.uuid4()),
        "acao": acao,
        "registrado_em": datetime.now(timezone.utc).isoformat(),
        "responsavel": responsavel,
        **campos,
    }


def _salvar_evento(evento: dict, diretorio: str | Path) -> Path:
    _validar_evento(evento)
    pasta = Path(diretorio)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{evento['evento_id']}.json"
    if caminho.exists():
        raise FileExistsError(f"Já existe o evento {evento['evento_id']}.")
    temporario = pasta / f".{evento['evento_id']}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(json.dumps(evento, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()
    return caminho


def carregar_eventos(diretorio: str | Path = DIRETORIO_ACOMPANHAMENTO) -> list[dict]:
    """Lê e valida todo o log; evento inválido ou histórico incoerente nunca é ignorado."""

    pasta = Path(diretorio)
    if not pasta.exists():
        return []
    eventos: list[dict] = []
    for caminho in sorted(pasta.glob("*.json")):
        try:
            evento = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as erro:
            raise ErroAcompanhamento(f"Não foi possível ler o evento de acompanhamento {caminho}.") from erro
        try:
            _validar_evento(evento)
        except ErroAcompanhamento as erro:
            raise ErroAcompanhamento(f"Evento de acompanhamento inválido em {caminho}: {erro}") from erro
        evento = dict(evento)
        evento["_arquivo_evento"] = str(caminho)
        eventos.append(evento)
    eventos = sorted(eventos, key=_ordem)
    reconstruir_tramitacao(eventos)  # coerência dos cancelamentos
    return eventos


# --------------------------------------------------------------------------------------- operações


def registrar_status(
    *,
    chave: tuple,
    status: str,
    status_outro: str | None,
    data_status: object,
    observacao: str | None,
    responsavel: str,
    chaves_validas: object,
    hoje: date | None = None,
    diretorio: str | Path = DIRETORIO_ACOMPANHAMENTO,
) -> dict:
    """Valida e grava um registro de status na tramitação da emenda `chave`. `hoje` é parâmetro (testes
    determinísticos). Nada é gravado se alguma validação falhar."""

    responsavel = _texto_obrigatorio(responsavel, "Responsável")
    chave_normalizada = _chave(*chave)
    _exigir_chave_existente(chave_normalizada, chaves_validas)
    status_final, outro = _status(status, status_outro)
    dia = _data(data_status, "Data do status")
    if dia > (hoje or date.today()):
        raise ErroAcompanhamento("A data do status não pode ser futura.")
    evento = _novo_evento(
        "registrar_status", responsavel,
        ano=chave_normalizada[0], resultado_primario_cod=chave_normalizada[1], emenda_numero=chave_normalizada[2],
        status=status_final, status_outro=outro, data_status=dia.isoformat(),
        observacao=_texto_opcional(observacao, "Observação", MAX_OBSERVACAO),
    )
    _salvar_evento(evento, diretorio)
    return evento


def cancelar_status(
    *, evento_id: str, motivo: str, responsavel: str, diretorio: str | Path = DIRETORIO_ACOMPANHAMENTO
) -> dict:
    """Cancela um registro de status (corrige um erro): acrescenta um evento e mantém o original. Só registros de
    status ainda não cancelados; o motivo é obrigatório."""

    motivo = _texto_obrigatorio(motivo, "Motivo", MIN_MOTIVO)
    responsavel = _texto_obrigatorio(responsavel, "Responsável")
    eventos = carregar_eventos(diretorio)
    alvo = next((e for e in eventos if e["evento_id"] == evento_id), None)
    if alvo is None or alvo["acao"] != "registrar_status":
        raise ErroAcompanhamento("Registro de status não encontrado.")
    tramitacao = reconstruir_tramitacao(eventos)
    if bool(tramitacao.loc[tramitacao["evento_id"] == evento_id, "cancelado"].iloc[0]):
        raise ErroAcompanhamento("Este registro já foi cancelado.")
    evento = _novo_evento("cancelar_status", responsavel, evento_alvo_id=evento_id, motivo=motivo)
    _salvar_evento(evento, diretorio)
    return evento


def definir_complemento(
    *,
    chave: tuple,
    objeto: str | None,
    destinatario: str | None,
    responsavel: str,
    motivo: str | None,
    chaves_validas: object,
    diretorio: str | Path = DIRETORIO_ACOMPANHAMENTO,
) -> dict:
    """Define objeto e destinatário da emenda (retrato completo dos dois campos; vazio = nulo). Recusa o que não
    muda nada em relação ao vigente — inclusive tudo vazio sem nada anterior."""

    responsavel = _texto_obrigatorio(responsavel, "Responsável")
    chave_normalizada = _chave(*chave)
    _exigir_chave_existente(chave_normalizada, chaves_validas)
    objeto_final = _texto_opcional(objeto, "Objeto", MAX_OBJETO)
    destinatario_final = _texto_opcional(destinatario, "Destinatário", MAX_DESTINATARIO)
    vigente = complemento_vigente(carregar_eventos(diretorio))
    atual = vigente[
        (vigente["ano"] == chave_normalizada[0])
        & (vigente["resultado_primario_cod"] == chave_normalizada[1])
        & (vigente["emenda_numero"] == chave_normalizada[2])
    ]
    anteriores = (None, None) if atual.empty else tuple(
        None if pd.isna(valor) else valor for valor in atual.iloc[0][["objeto", "destinatario"]]
    )
    if (objeto_final, destinatario_final) == anteriores:
        raise ErroAcompanhamento("Nenhuma alteração: objeto e destinatário já estão assim.")
    evento = _novo_evento(
        "definir_complemento", responsavel,
        ano=chave_normalizada[0], resultado_primario_cod=chave_normalizada[1], emenda_numero=chave_normalizada[2],
        objeto=objeto_final, destinatario=destinatario_final, motivo=_texto_opcional(motivo, "Motivo", MAX_OBSERVACAO),
    )
    _salvar_evento(evento, diretorio)
    return evento


# ------------------------------------------------------------------------------------ reconstrução


def reconstruir_tramitacao(eventos: list[dict]) -> pd.DataFrame:
    """Histórico completo da tramitação, em ordem cronológica (`data_status`, depois registro), com `cancelado`
    e quem/quando/por quê cancelou. Levanta `ErroAcompanhamento` para cancelamento de registro inexistente ou
    cancelado duas vezes."""

    registros: dict[str, dict] = {}
    for evento in sorted(eventos, key=_ordem):
        if evento["acao"] == "registrar_status":
            chave = _chave_do_evento(evento)
            registros[evento["evento_id"]] = {
                "evento_id": evento["evento_id"],
                "ano": chave[0],
                "resultado_primario_cod": chave[1],
                "emenda_numero": chave[2],
                "status": evento["status_outro"] if evento["status"] == STATUS_OUTRO else evento["status"],
                "data_status": _data(evento["data_status"], "Data do status"),
                "observacao": evento.get("observacao"),
                "responsavel": evento["responsavel"].strip(),
                "registrado_em": evento["registrado_em"],
                "cancelado": False,
                "cancelado_motivo": None,
                "cancelado_por": None,
                "cancelado_em": None,
            }
        elif evento["acao"] == "cancelar_status":
            alvo = registros.get(evento["evento_alvo_id"])
            if alvo is None:
                raise ErroAcompanhamento("Histórico incoerente: cancelamento de um registro de status inexistente.")
            if alvo["cancelado"]:
                raise ErroAcompanhamento("Histórico incoerente: registro de status cancelado mais de uma vez.")
            alvo.update(
                cancelado=True, cancelado_motivo=evento["motivo"].strip(), cancelado_por=evento["responsavel"].strip(),
                cancelado_em=evento["registrado_em"],
            )
    tabela = pd.DataFrame(list(registros.values()), columns=COLUNAS_TRAMITACAO)
    tabela["cancelado"] = tabela["cancelado"].astype(bool)
    return tabela.sort_values(["data_status", "registrado_em"], kind="stable").reset_index(drop=True)


def status_atual(tramitacao: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por emenda: o registro NÃO cancelado de maior `data_status` (desempate: registrado por último)."""

    ativos = tramitacao[~tramitacao["cancelado"]]
    if ativos.empty:
        return tramitacao.iloc[0:0].copy()
    ordenados = ativos.sort_values(["data_status", "registrado_em"], kind="stable")
    ultimos = ordenados.groupby(["ano", "resultado_primario_cod", "emenda_numero"], sort=True).tail(1)
    return ultimos.sort_values(["ano", "resultado_primario_cod", "emenda_numero"]).reset_index(drop=True)


def _eventos_de_complemento(eventos: list[dict]) -> list[dict]:
    return [e for e in sorted(eventos, key=_ordem) if e["acao"] == "definir_complemento"]


def complemento_vigente(eventos: list[dict]) -> pd.DataFrame:
    """Objeto e destinatário vigentes por emenda (o último evento de cada uma); vazio = nulo."""

    ultimo: dict[tuple, dict] = {}
    for evento in _eventos_de_complemento(eventos):
        chave = _chave_do_evento(evento)
        ultimo[chave] = {
            "ano": chave[0], "resultado_primario_cod": chave[1], "emenda_numero": chave[2],
            "objeto": evento.get("objeto"), "destinatario": evento.get("destinatario"),
            "responsavel": evento["responsavel"].strip(), "registrado_em": evento["registrado_em"],
        }
    return pd.DataFrame(list(ultimo.values()), columns=COLUNAS_COMPLEMENTO)


def historico_complemento(eventos: list[dict], chave: tuple) -> pd.DataFrame:
    """Alterações de objeto/destinatário de uma emenda, em ordem, com o valor anterior → novo."""

    alvo = _chave(*chave)
    linhas, objeto_anterior, destinatario_anterior = [], None, None
    for evento in _eventos_de_complemento(eventos):
        if _chave_do_evento(evento) != alvo:
            continue
        linhas.append(
            {
                "registrado_em": evento["registrado_em"], "responsavel": evento["responsavel"].strip(),
                "motivo": evento.get("motivo"), "objeto_anterior": objeto_anterior, "objeto": evento.get("objeto"),
                "destinatario_anterior": destinatario_anterior, "destinatario": evento.get("destinatario"),
            }
        )
        objeto_anterior, destinatario_anterior = evento.get("objeto"), evento.get("destinatario")
    return pd.DataFrame(
        linhas,
        columns=["registrado_em", "responsavel", "motivo", "objeto_anterior", "objeto", "destinatario_anterior", "destinatario"],
    )


def orfaos(eventos: list[dict], chaves_validas: object) -> list[dict]:
    """Registros de status e de complemento de emendas que não existem mais nos dados atuais — permanecem
    registrados e são listados aqui, nunca descartados."""

    validas = _normalizar_validas(chaves_validas)
    resultado = []
    for evento in sorted(eventos, key=_ordem):
        if evento["acao"] == "cancelar_status":
            continue
        chave = _chave_do_evento(evento)
        if chave in validas:
            continue
        resumo = (
            evento["status_outro"] if evento["acao"] == "registrar_status" and evento["status"] == STATUS_OUTRO
            else evento.get("status") if evento["acao"] == "registrar_status"
            else f"objeto/destinatário: {evento.get('objeto') or '—'} / {evento.get('destinatario') or '—'}"
        )
        resultado.append(
            {
                "acao": evento["acao"], "evento_id": evento["evento_id"], "ano": chave[0],
                "resultado_primario_cod": chave[1], "emenda_numero": chave[2],
                "registrado_em": evento["registrado_em"], "responsavel": evento["responsavel"].strip(), "resumo": resumo,
            }
        )
    return resultado
