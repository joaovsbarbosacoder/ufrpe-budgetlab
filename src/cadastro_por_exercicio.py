"""
Motor genérico de cadastro nativo multi-exercício — persistência em disco (um arquivo JSON por
registro, gravação atômica via arquivo temporário + rename, mesmo padrão de
`src.prazos_orcamentarios`), com registros agrupados por exercício (ano) em subpastas
(`<diretorio_base>/<ano>/<id>.json`).

Usado por `src/bolsas_auxilios_cadastro.py` e `src/contratos_continuos_cadastro.py` para
desvincular essas duas páginas de reimportação manual de planilha (pedido explícito): o
cadastro passa a viver só no sistema, editável em tela, sem precisar de um novo arquivo Excel
para refletir mudanças.

Camada: infraestrutura de persistência genérica — não conhece o esquema de nenhuma feature
específica. Cada módulo que usa este motor define seus próprios campos de identidade
(copiados ao duplicar um exercício para o próximo, via `duplicar_exercicio`) e campos de
execução (zerados/em branco no exercício novo — o vínculo com a base oficial que autentica o
saldo/empenho se refaz depois, quando o usuário informar o novo número de empenho daquele
exercício).

Contrato público:
    caminho_exercicio(diretorio_base, ano) -> Path
    novo_registro(**campos) -> dict
    salvar(diretorio_base, ano, registro) -> Path
    atualizar(diretorio_base, ano, registro) -> Path
    excluir(diretorio_base, ano, identificador) -> None
    carregar_registros(diretorio_base, ano) -> list[dict]
    anos_disponiveis(diretorio_base) -> list[int]
    duplicar_exercicio(diretorio_base, registros_origem, ano_destino, campos_identidade, campos_execucao_padrao) -> list[dict]
"""

from __future__ import annotations

import json
import math
import re
import shutil
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


class ErroCadastro(ValueError):
    """Operação de cadastro inválida — nunca gravar/ler um registro incoerente."""


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def caminho_exercicio(diretorio_base: str | Path, ano: int) -> Path:
    return Path(diretorio_base) / str(int(ano))


def novo_registro(**campos: object) -> dict:
    """Monta um registro novo (ainda não gravado — ver `salvar`), com `id`/`criado_em`/
    `atualizado_em` preenchidos automaticamente. `campos` são os campos específicos da feature
    (identidade + execução); este módulo não conhece esquema, só armazena o que recebe."""

    agora = _agora_iso()
    return {"id": str(uuid.uuid4()), "criado_em": agora, "atualizado_em": agora, **campos}


def _caminho_registro(identificador: str, diretorio: Path) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(identificador)):
        raise ErroCadastro("Identificador de registro inválido.")
    return diretorio / f"{identificador}.json"


def _serializavel(valor: object) -> object:
    """Registros costumam ser montados a partir de uma linha de DataFrame (`linha.to_dict()`)
    em `app_pages/bolsas_auxilios.py`/`app_pages/contratos_continuos.py` — `pd.Timestamp`,
    `pd.NaT`, `pd.NA` e `float('nan')` (todos possíveis ali) não são serializáveis em JSON por
    padrão (`pd.NaT`/`pd.NA` levantam `TypeError` direto; `float('nan')` "funciona" mas grava
    JSON inválido, "NaN" sem aspas). Convertidos aqui para `None`/ISO 8601 antes de gravar, uma
    vez só, para nenhum módulo que usa este motor precisar lembrar de fazer isso na mão.
    Recursivo em listas/dicts — alguns registros trazem estrutura aninhada (ex.: `itens` em
    `src.contratos_continuos_cadastro`, uma lista de `{"numero", "percentual"}`)."""

    if isinstance(valor, dict):
        return {chave: _serializavel(sub_valor) for chave, sub_valor in valor.items()}
    if isinstance(valor, list):
        return [_serializavel(item) for item in valor]
    if isinstance(valor, pd.Timestamp):
        return None if pd.isna(valor) else valor.isoformat()
    if valor is pd.NA or valor is pd.NaT:
        return None
    if isinstance(valor, float) and math.isnan(valor):
        return None
    if hasattr(valor, "item"):
        return valor.item()
    return valor


def _gravar_atomico(registro: dict, caminho: Path) -> None:
    registro = {chave: _serializavel(valor) for chave, valor in registro.items()}
    temporario = caminho.parent / f".{registro['id']}.{uuid.uuid4().hex}.tmp"
    try:
        temporario.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(caminho)
    finally:
        if temporario.exists():
            temporario.unlink()


def salvar(diretorio_base: str | Path, ano: int, registro: dict) -> Path:
    """Grava um registro novo atomicamente, sem sobrescrever outro ID."""

    diretorio = caminho_exercicio(diretorio_base, ano)
    diretorio.mkdir(parents=True, exist_ok=True)
    caminho = _caminho_registro(str(registro["id"]), diretorio)
    if caminho.exists():
        raise FileExistsError(f"Já existe um registro com o ID {registro['id']} em {diretorio}.")
    _gravar_atomico(registro, caminho)
    return caminho


def atualizar(diretorio_base: str | Path, ano: int, registro: dict) -> Path:
    """Sobrescreve um registro já existente — só aceita ID já gravado, para este caminho nunca
    criar um registro novo por engano."""

    diretorio = caminho_exercicio(diretorio_base, ano)
    caminho = _caminho_registro(str(registro["id"]), diretorio)
    if not caminho.exists():
        raise FileNotFoundError(f"Nenhum registro com o ID {registro['id']} em {diretorio}.")
    registro = {**registro, "atualizado_em": _agora_iso()}
    _gravar_atomico(registro, caminho)
    return caminho


def excluir(diretorio_base: str | Path, ano: int, identificador: str) -> None:
    """Remove o registro em definitivo — sem lixeira nem histórico, mesmo critério de
    `src.prazos_orcamentarios.excluir`."""

    _caminho_registro(identificador, caminho_exercicio(diretorio_base, ano)).unlink(missing_ok=True)


def _liberar_e_repetir(func, caminho: str, exc_info) -> None:
    """Callback de `shutil.rmtree` (Windows): um arquivo/pasta recém-gravado às vezes fica com
    um lock passageiro — sincronização de nuvem (OneDrive), antivírus, indexador — que derruba
    a exclusão com `PermissionError: [WinError 5] Acesso negado` mesmo sem problema real de
    permissão (visto na prática: `data/bolsas_auxilios/<ano>/` recém-duplicado). Tira o
    atributo só-leitura e tenta a mesma operação de novo antes de desistir; se ainda assim
    falhar, deixa o erro subir — não esconde uma falha de permissão de verdade."""

    try:
        Path(caminho).chmod(stat.S_IWRITE)
    except OSError:
        pass
    func(caminho)


def excluir_exercicio(diretorio_base: str | Path, ano: int) -> None:
    """Apaga o exercício inteiro (todos os registros daquele ano) em definitivo — usado para
    remover uma duplicação/geração de exercício que deixou de fazer sentido. Sem lixeira nem
    histórico, mesmo critério de `excluir`. Quem decide se é seguro apagar (ex.: nunca deixar
    apagar o exercício mais antigo, o migrado da planilha original) é a interface, não este
    motor.

    Repete a exclusão algumas vezes com um pequeno intervalo (`_liberar_e_repetir` já tenta
    uma vez por dentro do próprio `rmtree`; este laço cobre o caso do lock ainda não ter sido
    liberado nem depois disso) — locks passageiros de sincronização/antivírus no Windows
    costumam se resolver sozinhos em menos de um segundo."""

    diretorio = caminho_exercicio(diretorio_base, ano)
    if not diretorio.exists():
        return

    ultimo_erro: PermissionError | None = None
    for tentativa in range(5):
        try:
            shutil.rmtree(diretorio, onexc=_liberar_e_repetir)
            return
        except PermissionError as erro:
            ultimo_erro = erro
            time.sleep(0.3 * (tentativa + 1))
    raise ultimo_erro


def carregar_registros(diretorio_base: str | Path, ano: int) -> list[dict]:
    diretorio = caminho_exercicio(diretorio_base, ano)
    if not diretorio.exists():
        return []
    return [
        json.loads(caminho.read_text(encoding="utf-8"))
        for caminho in sorted(diretorio.glob("*.json"))
    ]


def anos_disponiveis(diretorio_base: str | Path) -> list[int]:
    """Exercícios com pelo menos uma subpasta criada (mesmo que hoje vazia) — inclui todo ano
    que já teve `salvar`/`duplicar_exercicio` chamado alguma vez, mesmo que os registros
    tenham sido depois todos excluídos (o exercício continua navegável como histórico)."""

    diretorio_base = Path(diretorio_base)
    if not diretorio_base.exists():
        return []
    return sorted(
        int(item.name) for item in diretorio_base.iterdir()
        if item.is_dir() and re.fullmatch(r"\d{4}", item.name)
    )


def duplicar_exercicio(
    diretorio_base: str | Path,
    registros_origem: list[dict],
    ano_destino: int,
    campos_identidade: list[str],
    campos_execucao_padrao: dict,
) -> list[dict]:
    """Cria, em `ano_destino`, um registro novo para cada registro de `registros_origem` —
    copiando só `campos_identidade` (classificação: processo, ação, PTRES, etc.) e preenchendo
    o resto com `campos_execucao_padrao` (empenho/saldo/situação em branco: "gerar próximo
    exercício" começa sem execução, pedido explícito — o vínculo com a base de execução se
    refaz quando o usuário digitar o novo número de empenho daquele exercício).

    Não verifica se `ano_destino` já tem registros — quem decide se é seguro duplicar (ex.: não
    duplicar em cima de um exercício que o usuário já preencheu manualmente) é a interface, não
    este motor."""

    novos = []
    for origem in registros_origem:
        campos = {campo: origem.get(campo) for campo in campos_identidade}
        campos.update(campos_execucao_padrao)
        registro = novo_registro(**campos)
        salvar(diretorio_base, ano_destino, registro)
        novos.append(registro)
    return novos
