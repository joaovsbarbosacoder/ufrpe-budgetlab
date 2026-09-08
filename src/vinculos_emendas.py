"""Vínculos manuais, auditáveis e reversíveis entre execução e emendas.

Os arquivos importados permanecem imutáveis. Cada vinculação ou desfazimento
gera um novo evento JSON em ``data/emendas/vinculos``; o estado vigente é
reconstruído pelo histórico. Quando um relatório posterior passa a trazer o
mesmo vínculo, o evento manual fica registrado, mas deixa de gerar uma linha
adicional e, portanto, não duplica valores.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.emendas_parlamentares import (
    ANO_INICIO_ATUALIZACAO,
    ErroPoliticaImportacao,
    ErroVinculoEmenda,
    RPS_EMENDA,
    salvar,
)
from src.tesouro_emendas_acompanhamento import COLUNAS_SAIDA


DIRETORIO_VINCULOS = Path("data/emendas/vinculos")
ACOES_EVENTO = {"vincular", "desfazer"}
_CHAVE_PTRES = ["ano", "resultado_primario_cod", "ptres"]
_COLUNAS_STATUS = [
    "vinculo_id",
    "ano",
    "resultado_primario_cod",
    "ptres",
    "emenda_numero",
    "registrado_em",
    "observacao",
    "evento_id",
    "arquivo_evento",
    "status",
    "detalhe",
]


@dataclass
class ResultadoComposicaoVinculos:
    """Relatório com vínculos efetivos e seus estados de reconciliação."""

    relatorio: pd.DataFrame
    ativos: pd.DataFrame
    absorvidos: pd.DataFrame
    conflitos: pd.DataFrame
    orfaos: pd.DataFrame


def criar_id_vinculo() -> str:
    """Gera um identificador opaco seguro para arquivo e referência cruzada."""

    return str(uuid.uuid4())


def preparar_emenda_gerenciada(emenda: dict, vinculo_id: str) -> dict:
    """Marca uma nova identidade manual para que só o evento controle seu PTRES."""

    _validar_id(vinculo_id, "vínculo")
    preparada = dict(emenda)
    preparada["gerenciada_por_vinculo_id"] = vinculo_id
    return preparada


def carregar_eventos_vinculo(
    diretorio: str | Path = DIRETORIO_VINCULOS,
) -> list[dict]:
    """Lê e valida todo o log; um evento inválido nunca é ignorado."""

    pasta = Path(diretorio)
    if not pasta.exists():
        return []
    eventos: list[dict] = []
    for caminho in sorted(pasta.glob("*.json")):
        try:
            evento = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ErroVinculoEmenda(
                f"Não foi possível ler o evento de vínculo {caminho}."
            ) from error
        _validar_evento(evento)
        evento = dict(evento)
        evento["_arquivo_evento"] = str(caminho)
        eventos.append(evento)
    reconstruir_vinculos_ativos(eventos)
    return sorted(eventos, key=_ordem_evento)


def reconstruir_vinculos_ativos(eventos: list[dict]) -> list[dict]:
    """Reconstrói vínculos ativos e rejeita duplicidade ou histórico incoerente."""

    por_id: dict[str, dict] = {}
    id_por_chave: dict[tuple[int, str, str], str] = {}
    eventos_vistos: set[str] = set()
    vinculos_criados: set[str] = set()
    for evento in sorted(eventos, key=_ordem_evento):
        _validar_evento(evento)
        evento_id = evento["evento_id"]
        if evento_id in eventos_vistos:
            raise ErroVinculoEmenda(f"Evento de vínculo repetido: {evento_id}.")
        eventos_vistos.add(evento_id)
        vinculo_id = evento["vinculo_id"]
        chave = _chave_evento(evento)
        if evento["acao"] == "vincular":
            if vinculo_id in vinculos_criados:
                raise ErroVinculoEmenda(
                    f"O vínculo {vinculo_id} possui mais de um evento de criação."
                )
            outro = id_por_chave.get(chave)
            if outro is not None:
                raise ErroVinculoEmenda(
                    "O mesmo (ano, RP, PTRES) possui dois vínculos manuais "
                    f"ativos: {outro} e {vinculo_id}."
                )
            por_id[vinculo_id] = dict(evento)
            id_por_chave[chave] = vinculo_id
            vinculos_criados.add(vinculo_id)
            continue

        ativo = por_id.get(vinculo_id)
        if ativo is None:
            raise ErroVinculoEmenda(
                f"O evento {evento_id} desfaz um vínculo inexistente ou já desfeito."
            )
        if _chave_evento(ativo) != chave or (
            ativo["emenda_numero"] != evento["emenda_numero"]
        ):
            raise ErroVinculoEmenda(
                f"O desfazimento {evento_id} não corresponde ao vínculo original."
            )
        del por_id[vinculo_id]
        del id_por_chave[chave]
    return sorted(por_id.values(), key=_ordem_evento)


def registrar_vinculo_manual(
    *,
    ano: int,
    resultado_primario_cod: str,
    ptres: str,
    emenda_numero: str,
    pendencias: pd.DataFrame,
    relatorio: pd.DataFrame,
    cadastros: list[dict],
    observacao: str = "",
    vinculo_id: str | None = None,
    diretorio: str | Path = DIRETORIO_VINCULOS,
) -> dict:
    """Valida a fila e a identidade escolhida antes de persistir a vinculação."""

    chave = _normalizar_chave(ano, resultado_primario_cod, ptres)
    numero = _identificador(emenda_numero, "número da emenda")
    _validar_chave_pendente(chave, pendencias)
    identidades = _identidades_disponiveis(relatorio, cadastros)
    if (*chave[:2], numero) not in identidades:
        raise ErroVinculoEmenda(
            "A emenda escolhida não existe no mesmo exercício e Resultado Primário."
        )

    eventos = carregar_eventos_vinculo(diretorio)
    if any(
        _chave_evento(evento) == chave
        for evento in reconstruir_vinculos_ativos(eventos)
    ):
        raise ErroVinculoEmenda(
            "Esse (ano, RP, PTRES) já possui um vínculo manual ativo."
        )
    evento = _novo_evento(
        acao="vincular",
        vinculo_id=vinculo_id or criar_id_vinculo(),
        ano=chave[0],
        resultado_primario_cod=chave[1],
        ptres=chave[2],
        emenda_numero=numero,
        observacao=observacao,
    )
    _salvar_evento(evento, diretorio)
    return evento


def registrar_nova_emenda_vinculada(
    *,
    emenda: dict,
    pendencias: pd.DataFrame,
    relatorio: pd.DataFrame,
    cadastros: list[dict],
    diretorio_emendas: str | Path,
    diretorio_vinculos: str | Path = DIRETORIO_VINCULOS,
    observacao: str = "",
) -> tuple[dict, dict]:
    """Persiste uma nova identidade manual e o evento que controla seu PTRES."""

    vinculo_id = criar_id_vinculo()
    gerenciada = preparar_emenda_gerenciada(emenda, vinculo_id)
    ptres = gerenciada.get("ptres") or []
    if len(ptres) != 1:
        raise ErroVinculoEmenda(
            "Uma nova emenda criada a partir da pendência deve ter exatamente um PTRES."
        )
    cadastros_com_nova = [*cadastros, gerenciada]
    chave = _normalizar_chave(
        gerenciada.get("exercicio"),
        gerenciada.get("rp"),
        ptres[0],
    )
    _validar_chave_pendente(chave, pendencias)
    # Todas as validações do evento são feitas antes de qualquer gravação.
    numero = _identificador(gerenciada.get("numero"), "número da emenda")
    identidades_anteriores = _identidades_disponiveis(relatorio, cadastros)
    if (*chave[:2], numero) in identidades_anteriores:
        raise ErroVinculoEmenda(
            "Essa emenda já existe no exercício e RP informados; "
            "use a opção de vínculo com emenda existente."
        )
    identidades = _identidades_disponiveis(relatorio, cadastros_com_nova)
    if (*chave[:2], numero) not in identidades:
        raise ErroVinculoEmenda("A nova emenda não pôde ser validada.")
    eventos = carregar_eventos_vinculo(diretorio_vinculos)
    if any(
        _chave_evento(evento) == chave
        for evento in reconstruir_vinculos_ativos(eventos)
    ):
        raise ErroVinculoEmenda(
            "Esse (ano, RP, PTRES) já possui um vínculo manual ativo."
        )

    salvar(gerenciada, diretorio_emendas)
    evento = _novo_evento(
        acao="vincular",
        vinculo_id=vinculo_id,
        ano=chave[0],
        resultado_primario_cod=chave[1],
        ptres=chave[2],
        emenda_numero=numero,
        observacao=observacao,
    )
    _salvar_evento(evento, diretorio_vinculos)
    return gerenciada, evento


def desfazer_vinculo_manual(
    vinculo_id: str,
    *,
    observacao: str = "",
    diretorio: str | Path = DIRETORIO_VINCULOS,
) -> dict:
    """Acrescenta um evento de desfazimento sem apagar a criação original."""

    _validar_id(vinculo_id, "vínculo")
    eventos = carregar_eventos_vinculo(diretorio)
    ativos = {
        evento["vinculo_id"]: evento
        for evento in reconstruir_vinculos_ativos(eventos)
    }
    original = ativos.get(vinculo_id)
    if original is None:
        raise ErroVinculoEmenda(f"O vínculo {vinculo_id} não está ativo.")
    evento = _novo_evento(
        acao="desfazer",
        vinculo_id=vinculo_id,
        ano=original["ano"],
        resultado_primario_cod=original["resultado_primario_cod"],
        ptres=original["ptres"],
        emenda_numero=original["emenda_numero"],
        observacao=observacao,
    )
    _salvar_evento(evento, diretorio)
    return evento


def compor_relatorio_com_vinculos(
    relatorio: pd.DataFrame,
    cadastros: list[dict],
    eventos: list[dict],
) -> ResultadoComposicaoVinculos:
    """Aplica vínculos ativos sem duplicar chaves já entregues pelo relatório."""

    faltando = [coluna for coluna in COLUNAS_SAIDA if coluna not in relatorio.columns]
    if faltando:
        raise ErroVinculoEmenda(
            f"Relatório de Emendas sem as colunas obrigatórias: {faltando}."
        )
    base = relatorio.copy(deep=True)
    ativos = reconstruir_vinculos_ativos(eventos)
    identidades = _identidades_disponiveis(base, cadastros)
    chaves_relatorio: dict[tuple[int, str, str], set[str]] = {}
    for row in base.itertuples(index=False):
        ano_row = _ano_sem_politica(getattr(row, "ano"))
        if ano_row < ANO_INICIO_ATUALIZACAO:
            continue
        chave = _normalizar_chave(
            ano_row,
            getattr(row, "resultado_primario_cod"),
            getattr(row, "ptres"),
        )
        chaves_relatorio.setdefault(chave, set()).add(
            _identificador(getattr(row, "emenda_numero"), "número da emenda")
        )

    linhas_novas: list[dict] = []
    status: list[dict] = []
    for evento in ativos:
        chave = _chave_evento(evento)
        alvo = (*chave[:2], evento["emenda_numero"])
        presentes = chaves_relatorio.get(chave, set())
        if evento["emenda_numero"] in presentes:
            status.append(
                _linha_status(
                    evento,
                    "absorvido_relatorio",
                    "O relatório já contém o vínculo.",
                )
            )
            continue
        if presentes:
            numeros = ", ".join(sorted(presentes))
            status.append(
                _linha_status(
                    evento,
                    "conflito",
                    f"O relatório atribui o PTRES a outra emenda: {numeros}.",
                )
            )
            continue
        identidade = identidades.get(alvo)
        if identidade is None:
            status.append(
                _linha_status(
                    evento,
                    "orfa",
                    "A identidade da emenda não está mais disponível.",
                )
            )
            continue
        gnd = identidade.get("gnd_cod", pd.NA)
        linhas_novas.append(
            {
                "arquivo_origem": evento.get(
                    "_arquivo_evento",
                    f"data/emendas/vinculos/{evento['evento_id']}.json",
                ),
                "aba_origem": pd.NA,
                "linha_origem": pd.NA,
                "resultado_primario_cod": chave[1],
                "ptres": chave[2],
                "emenda_numero": evento["emenda_numero"],
                "autor_emenda": identidade["autor_emenda"],
                "parlamentar": identidade["parlamentar"],
                "gnd_cod": gnd,
                "ano": chave[0],
                "dotacao_atualizada": pd.NA,
                "empenhada_relatorio": pd.NA,
                "liquidada_relatorio": pd.NA,
                "paga_relatorio": pd.NA,
                "origem_cadastro": "vinculo_manual",
                "id_cadastro_manual": identidade.get("id_cadastro_manual", pd.NA),
            }
        )
        status.append(_linha_status(evento, "ativo", "Vínculo manual aplicado."))

    combinado = base
    if linhas_novas:
        combinado = pd.concat(
            [base, pd.DataFrame.from_records(linhas_novas)],
            ignore_index=True,
            sort=False,
        )
    tabela_status = pd.DataFrame.from_records(status, columns=_COLUNAS_STATUS)
    return ResultadoComposicaoVinculos(
        relatorio=combinado,
        ativos=tabela_status,
        absorvidos=tabela_status[
            tabela_status["status"].eq("absorvido_relatorio")
        ].reset_index(drop=True),
        conflitos=tabela_status[
            tabela_status["status"].eq("conflito")
        ].reset_index(drop=True),
        orfaos=tabela_status[
            tabela_status["status"].eq("orfa")
        ].reset_index(drop=True),
    )


def historico_eventos_dataframe(eventos: list[dict]) -> pd.DataFrame:
    """Expõe o log completo em formato tabular para auditoria na interface."""

    linhas = []
    for evento in sorted(eventos, key=_ordem_evento, reverse=True):
        linhas.append(
            {
                "evento_id": evento["evento_id"],
                "acao": evento["acao"],
                "vinculo_id": evento["vinculo_id"],
                "ano": evento["ano"],
                "resultado_primario_cod": evento["resultado_primario_cod"],
                "ptres": evento["ptres"],
                "emenda_numero": evento["emenda_numero"],
                "registrado_em": evento["registrado_em"],
                "observacao": evento["observacao"],
                "arquivo_evento": evento.get("_arquivo_evento", pd.NA),
            }
        )
    return pd.DataFrame.from_records(linhas)


def _identidades_disponiveis(
    relatorio: pd.DataFrame,
    cadastros: list[dict],
) -> dict[tuple[int, str, str], dict]:
    identidades: dict[tuple[int, str, str], dict] = {}
    if not relatorio.empty:
        obrigatorias = [
            "ano",
            "resultado_primario_cod",
            "emenda_numero",
            "autor_emenda",
            "parlamentar",
        ]
        faltando = [
            coluna for coluna in obrigatorias if coluna not in relatorio.columns
        ]
        if faltando:
            raise ErroVinculoEmenda(
                f"Relatório sem colunas para identificar emendas: {faltando}."
            )
        for row in relatorio.itertuples(index=False):
            ano_row = _ano_sem_politica(getattr(row, "ano"))
            if ano_row < ANO_INICIO_ATUALIZACAO:
                continue
            ano, rp, _ = _normalizar_chave(
                ano_row,
                getattr(row, "resultado_primario_cod"),
                getattr(row, "ptres"),
            )
            numero = _identificador(
                getattr(row, "emenda_numero"), "número da emenda"
            )
            chave = (ano, rp, numero)
            identidade = {
                "autor_emenda": _identificador(getattr(row, "autor_emenda"), "autor"),
                "parlamentar": _identificador(getattr(row, "parlamentar"), "parlamentar"),
                "gnd_cod": pd.NA,
                "id_cadastro_manual": pd.NA,
            }
            existente = identidades.get(chave)
            if existente is not None and (
                existente["autor_emenda"] != identidade["autor_emenda"]
                or existente["parlamentar"] != identidade["parlamentar"]
            ):
                raise ErroVinculoEmenda(
                    f"A emenda {numero} possui identidades divergentes no relatório."
                )
            identidades[chave] = identidade

    for cadastro in cadastros:
        if not cadastro.get("gerenciada_por_vinculo_id"):
            continue
        ano, rp, _ = _normalizar_chave(
            cadastro.get("exercicio"),
            cadastro.get("rp"),
            (cadastro.get("ptres") or [None])[0],
        )
        numero = _identificador(cadastro.get("numero"), "número da emenda")
        chave = (ano, rp, numero)
        if chave in identidades:
            continue
        gnd = cadastro.get("gnd_codigo")
        identidades[chave] = {
            "autor_emenda": _identificador(
                cadastro.get("autor_emenda") or cadastro.get("parlamentar"), "autor"
            ),
            "parlamentar": _identificador(
                cadastro.get("parlamentar"), "parlamentar"
            ),
            "gnd_cod": pd.NA if gnd is None or not str(gnd).strip() else str(gnd).strip(),
            "id_cadastro_manual": cadastro.get("id", pd.NA),
        }
    return identidades


def _validar_chave_pendente(chave: tuple[int, str, str], pendencias: pd.DataFrame) -> None:
    faltando = [
        coluna for coluna in _CHAVE_PTRES if coluna not in pendencias.columns
    ]
    if faltando:
        raise ErroVinculoEmenda(f"Fila de pendências sem colunas obrigatórias: {faltando}.")
    chaves = {
        _normalizar_chave(row.ano, row.resultado_primario_cod, row.ptres)
        for row in pendencias[_CHAVE_PTRES].itertuples(index=False)
    }
    if chave not in chaves:
        raise ErroVinculoEmenda(
            "O PTRES não consta mais na fila de execução sem emenda; recarregue o painel."
        )


def _novo_evento(
    *,
    acao: str,
    vinculo_id: str,
    ano: int,
    resultado_primario_cod: str,
    ptres: str,
    emenda_numero: str,
    observacao: str,
) -> dict:
    evento = {
        "versao_schema": 1,
        "evento_id": str(uuid.uuid4()),
        "acao": acao,
        "vinculo_id": vinculo_id,
        "ano": ano,
        "resultado_primario_cod": resultado_primario_cod,
        "ptres": ptres,
        "emenda_numero": emenda_numero,
        "registrado_em": datetime.now(timezone.utc).isoformat(),
        "observacao": str(observacao or "").strip(),
    }
    _validar_evento(evento)
    return evento


def _salvar_evento(evento: dict, diretorio: str | Path) -> Path:
    _validar_evento(evento)
    pasta = Path(diretorio)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{evento['evento_id']}.json"
    if caminho.exists():
        raise FileExistsError(f"Já existe o evento {evento['evento_id']}.")
    temporario = pasta / f".{evento['evento_id']}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(
            json.dumps(evento, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()
    return caminho


def _validar_evento(evento: dict) -> None:
    if not isinstance(evento, dict):
        raise ErroVinculoEmenda("Evento de vínculo deve ser um objeto JSON.")
    if evento.get("versao_schema") != 1:
        raise ErroVinculoEmenda("Versão de evento de vínculo não reconhecida.")
    if evento.get("acao") not in ACOES_EVENTO:
        raise ErroVinculoEmenda("Ação de evento de vínculo inválida.")
    _validar_id(evento.get("evento_id"), "evento")
    _validar_id(evento.get("vinculo_id"), "vínculo")
    _normalizar_chave(
        evento.get("ano"), evento.get("resultado_primario_cod"), evento.get("ptres")
    )
    _identificador(evento.get("emenda_numero"), "número da emenda")
    if not isinstance(evento.get("observacao"), str):
        raise ErroVinculoEmenda("A observação do evento deve ser textual.")
    registrado_em = evento.get("registrado_em")
    if not isinstance(registrado_em, str):
        raise ErroVinculoEmenda("O evento não possui data de registro válida.")
    try:
        instante = datetime.fromisoformat(registrado_em)
    except ValueError as error:
        raise ErroVinculoEmenda("O evento não possui data de registro válida.") from error
    if instante.tzinfo is None:
        raise ErroVinculoEmenda("A data do evento deve informar o fuso horário.")


def _normalizar_chave(
    ano: object, resultado_primario_cod: object, ptres: object
) -> tuple[int, str, str]:
    ano_inteiro = _ano_sem_politica(ano)
    if ano_inteiro < ANO_INICIO_ATUALIZACAO:
        raise ErroPoliticaImportacao(
            f"Vínculos manuais só podem alterar exercícios a partir de {ANO_INICIO_ATUALIZACAO}."
        )
    rp = _identificador(resultado_primario_cod, "Resultado Primário").upper()
    rp = rp.removeprefix("RP").strip()
    if rp not in RPS_EMENDA:
        raise ErroVinculoEmenda("O Resultado Primário deve ser 6, 7 ou 8.")
    return ano_inteiro, rp, _identificador(ptres, "PTRES")


def _ano_sem_politica(ano: object) -> int:
    """Valida o tipo do exercício sem rejeitar o histórico estático."""

    if isinstance(ano, bool):
        raise ErroVinculoEmenda("Exercício inválido no relatório de Emendas.")
    try:
        ano_inteiro = int(ano)
    except (TypeError, ValueError) as error:
        raise ErroVinculoEmenda("Exercício inválido no relatório de Emendas.") from error
    try:
        if float(ano) != ano_inteiro:
            raise ErroVinculoEmenda("Exercício não inteiro no relatório de Emendas.")
    except (TypeError, ValueError) as error:
        raise ErroVinculoEmenda("Exercício inválido no relatório de Emendas.") from error
    return ano_inteiro


def _identificador(valor: object, campo: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ErroVinculoEmenda(
            f"{campo} deve ser informado como texto para preservar o identificador."
        )
    return valor.strip()


def _validar_id(valor: object, nome: str) -> None:
    if not isinstance(valor, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", valor):
        raise ErroVinculoEmenda(f"O identificador do {nome} é inválido.")


def _chave_evento(evento: dict) -> tuple[int, str, str]:
    return _normalizar_chave(
        evento["ano"], evento["resultado_primario_cod"], evento["ptres"]
    )


def _ordem_evento(evento: dict) -> tuple[str, str]:
    return str(evento.get("registrado_em", "")), str(evento.get("evento_id", ""))


def _linha_status(evento: dict, status: str, detalhe: str) -> dict:
    return {
        "vinculo_id": evento["vinculo_id"],
        "ano": evento["ano"],
        "resultado_primario_cod": evento["resultado_primario_cod"],
        "ptres": evento["ptres"],
        "emenda_numero": evento["emenda_numero"],
        "registrado_em": evento["registrado_em"],
        "observacao": evento["observacao"],
        "evento_id": evento["evento_id"],
        "arquivo_evento": evento.get("_arquivo_evento", pd.NA),
        "status": status,
        "detalhe": detalhe,
    }
