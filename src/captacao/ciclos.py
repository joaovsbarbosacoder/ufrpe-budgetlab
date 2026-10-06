"""Ciclo de captação: cadastro, edição, fases manuais e prorrogação por unidade (Etapa 4).

As regras de prazo (fase pela data, prazo efetivo, RN-05/RN-06) ficam em `regras.py`;
aqui só há persistência e as validações de cadastro. A fase ARMAZENADA muda só por ação
explícita (agendar, abrir, encerrar); a fase EFETIVA exibida combina a armazenada com a
data (`regras.fase_por_data`) — por isso não há rotina que grave transições automáticas.

Fora desta etapa (propostas posteriores): avançar para EM_ANALISE/CONCLUIDO (priorização)
e o envio dos avisos por e-mail (os interruptores só são guardados em `avisos_json`).

Toda alteração exige responsável e vai ao histórico (`auditoria.py`).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from src.captacao import auditoria, regras
from src.captacao.auditoria import ErroCadastro

CAMPOS_DATA = ("abertura", "encerramento", "prazo_validacao", "devolutiva_prevista")
CAMPOS_TEXTO = ("versao_pdi", "versao_pls", "mensagem_abertura")
CAMPOS_BOOL = ("permite_rascunho_antecipado", "somente_leitura_apos")
AVISOS = ("abertura", "sete_dias", "dois_dias", "aviso_chefia", "dia_encerramento")
CAMPOS_EDITAVEIS = (*CAMPOS_DATA, *CAMPOS_TEXTO, *CAMPOS_BOOL, "avisos_json")

_ROTULO_DATA = {
    "abertura": "abertura do registro",
    "encerramento": "encerramento do registro",
    "prazo_validacao": "prazo de validação pela chefia",
    "devolutiva_prevista": "devolutiva prevista",
}
#: fases efetivas em que cada campo deixa de poder ser alterado (RN-05: não mexer no prazo
#: já em curso; para estender só para uma unidade, use a prorrogação)
_BLOQUEIO_ABERTURA = ("ABERTO", "ENCERRADO", "EM_ANALISE", "CONCLUIDO")
_BLOQUEIO_ENCERRAMENTO = ("ENCERRADO", "EM_ANALISE", "CONCLUIDO")


def _data(valor: object, rotulo: str, erros: list[str]) -> str | None:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if isinstance(valor, date):
        return valor.isoformat()
    try:
        return date.fromisoformat(str(valor).strip()).isoformat()
    except ValueError:
        erros.append(f"Data inválida em {rotulo}: {valor!r}.")
        return None


def _para_date(texto: str | None) -> date | None:
    return date.fromisoformat(texto) if texto else None


def avisos_padrao() -> dict[str, bool]:
    """Todos desligados: nada é enviado sem o gestor ligar (e o envio ainda não existe)."""

    return {chave: False for chave in AVISOS}


def avisos_do_ciclo(ciclo: sqlite3.Row) -> dict[str, bool]:
    guardado = json.loads(ciclo["avisos_json"]) if ciclo["avisos_json"] else {}
    return {chave: bool(guardado.get(chave, False)) for chave in AVISOS}


def _normalizar(conexao: sqlite3.Connection, dados: dict[str, Any]) -> dict[str, Any]:
    """Valores prontos para gravar (datas ISO, 0/1, JSON); levanta `ErroCadastro` com todos
    os problemas de validação de uma vez."""

    erros: list[str] = []
    valores: dict[str, Any] = {c: _data(dados.get(c), _ROTULO_DATA[c], erros) for c in CAMPOS_DATA}

    sequencia = [(c, valores[c]) for c in CAMPOS_DATA if valores[c]]
    for (campo_a, a), (campo_b, b) in zip(sequencia, sequencia[1:]):
        if a > b:
            erros.append(f"A data de {_ROTULO_DATA[campo_a]} não pode ser depois de {_ROTULO_DATA[campo_b]}.")

    for campo, tabela, coluna in (("versao_pdi", "objetivo_pdi", "versao_pdi"), ("versao_pls", "meta_pls", "versao_pls")):
        texto = str(dados.get(campo) or "").strip() or None
        if texto and not conexao.execute(f"SELECT 1 FROM {tabela} WHERE {coluna} = ? LIMIT 1", (texto,)).fetchone():
            erros.append(f"A versão {texto!r} não está carregada em Planos de Referência.")
        valores[campo] = texto
    valores["mensagem_abertura"] = str(dados.get("mensagem_abertura") or "").strip() or None

    for campo in CAMPOS_BOOL:
        valores[campo] = int(bool(dados.get(campo, campo == "somente_leitura_apos")))

    avisos = dados.get("avisos") or avisos_padrao()
    valores["avisos_json"] = json.dumps({c: bool(avisos.get(c, False)) for c in AVISOS}, sort_keys=True)

    if erros:
        raise ErroCadastro(erros)
    return valores


def _ciclo(conexao: sqlite3.Connection, ciclo_id: int) -> sqlite3.Row:
    ciclo = conexao.execute("SELECT * FROM ciclo WHERE id = ?", (ciclo_id,)).fetchone()
    if ciclo is None:
        raise ErroCadastro([f"Ciclo {ciclo_id} não encontrado."])
    return ciclo


def fase_efetiva(ciclo: sqlite3.Row, hoje: date) -> str:
    return regras.fase_por_data(ciclo["fase"], _para_date(ciclo["abertura"]), _para_date(ciclo["encerramento"]), hoje)


def listar_ciclos(conexao: sqlite3.Connection) -> list[sqlite3.Row]:
    return conexao.execute("SELECT * FROM ciclo ORDER BY exercicio DESC").fetchall()


# --- Cadastro -----------------------------------------------------------------------


def criar_ciclo(conexao: sqlite3.Connection, exercicio: int, dados: dict[str, Any], usuario: str | None) -> int:
    """Cria o ciclo do exercício em fase RASCUNHO (em preparação). Um ciclo por exercício."""

    usuario = auditoria.exigir_usuario(usuario)
    if isinstance(exercicio, bool) or not isinstance(exercicio, int) or not 2000 <= exercicio <= 2100:
        raise ErroCadastro(["Informe o exercício (ano com 4 dígitos)."])
    if conexao.execute("SELECT 1 FROM ciclo WHERE exercicio = ?", (exercicio,)).fetchone():
        raise ErroCadastro([f"Já existe um ciclo para o exercício {exercicio}."])
    valores = _normalizar(conexao, dados)

    with conexao:
        colunas = ", ".join(("exercicio", *CAMPOS_EDITAVEIS, "fase", "criado_por", "criado_em"))
        marcas = ", ".join("?" * (len(CAMPOS_EDITAVEIS) + 4))
        cursor = conexao.execute(
            f"INSERT INTO ciclo ({colunas}) VALUES ({marcas})",
            (exercicio, *[valores[c] for c in CAMPOS_EDITAVEIS], "RASCUNHO", usuario, auditoria.agora()),
        )
        ciclo_id = int(cursor.lastrowid)
        auditoria.registrar(conexao, "ciclo", ciclo_id, "CRIAR", "exercicio", None, str(exercicio), usuario)
    return ciclo_id


def editar_ciclo(
    conexao: sqlite3.Connection, ciclo_id: int, dados: dict[str, Any], usuario: str | None, hoje: date
) -> list[str]:
    """Altera datas, versões dos planos, regras e avisos (o exercício nunca muda). Com o
    ciclo aberto a abertura fica travada; depois do encerramento também o encerramento —
    para estender o prazo de uma unidade, use a prorrogação. Devolve os campos alterados."""

    usuario = auditoria.exigir_usuario(usuario)
    atual = _ciclo(conexao, ciclo_id)
    valores = _normalizar(conexao, dados)
    efetiva = fase_efetiva(atual, hoje)

    travados = []
    if efetiva in _BLOQUEIO_ABERTURA and valores["abertura"] != atual["abertura"]:
        travados.append("abertura do registro")
    if efetiva in _BLOQUEIO_ENCERRAMENTO and valores["encerramento"] != atual["encerramento"]:
        travados.append("encerramento do registro")
    if travados:
        raise ErroCadastro(
            [f"Com o ciclo {efetiva.lower()}, não é possível alterar: {', '.join(travados)}. "
             "Para dar mais prazo a uma unidade, conceda uma prorrogação."]
        )

    mudancas = [(c, atual[c], valores[c]) for c in CAMPOS_EDITAVEIS if atual[c] != valores[c]]
    if not mudancas:
        return []
    with conexao:
        conexao.execute(
            f"UPDATE ciclo SET {', '.join(f'{c} = ?' for c, _, _ in mudancas)} WHERE id = ?",
            (*[depois for _, _, depois in mudancas], ciclo_id),
        )
        for campo, antes, depois in mudancas:
            auditoria.registrar(conexao, "ciclo", ciclo_id, "EDITAR", campo, antes, None if depois is None else str(depois), usuario)
    return [campo for campo, _, _ in mudancas]


# --- Fases manuais ------------------------------------------------------------------


def _gravar_fase(conexao: sqlite3.Connection, ciclo: sqlite3.Row, nova: str, usuario: str) -> None:
    conexao.execute("UPDATE ciclo SET fase = ? WHERE id = ?", (nova, ciclo["id"]))
    auditoria.registrar(conexao, "ciclo", ciclo["id"], "FASE", "fase", ciclo["fase"], nova, usuario)


def agendar_ciclo(conexao: sqlite3.Connection, ciclo_id: int, usuario: str | None) -> None:
    """RASCUNHO → AGENDADO. Exige abertura e encerramento (as regras de prazo dependem delas)."""

    usuario = auditoria.exigir_usuario(usuario)
    ciclo = _ciclo(conexao, ciclo_id)
    if ciclo["fase"] != "RASCUNHO":
        raise ErroCadastro([f"Só um ciclo em preparação pode ser agendado (fase atual: {ciclo['fase']})."])
    faltando = [_ROTULO_DATA[c] for c in ("abertura", "encerramento") if not ciclo[c]]
    if faltando:
        raise ErroCadastro([f"Informe antes: {', '.join(faltando)}."])
    with conexao:
        _gravar_fase(conexao, ciclo, "AGENDADO", usuario)


def abrir_agora(conexao: sqlite3.Connection, ciclo_id: int, usuario: str | None, hoje: date) -> None:
    """Abre o registro manualmente (RASCUNHO/AGENDADO → ABERTO). Se a abertura estava em data
    futura (ou vazia), ela passa a ser hoje — registrado no histórico — porque a regra
    RN-05 não deixa registrar antes da data de abertura."""

    usuario = auditoria.exigir_usuario(usuario)
    ciclo = _ciclo(conexao, ciclo_id)
    if ciclo["fase"] not in ("RASCUNHO", "AGENDADO"):
        raise ErroCadastro([f"O ciclo já foi aberto ou encerrado (fase atual: {ciclo['fase']})."])
    encerramento = _para_date(ciclo["encerramento"])
    if encerramento is None:
        raise ErroCadastro(["Informe a data de encerramento do registro antes de abrir."])
    if hoje > encerramento:
        raise ErroCadastro(["A data de encerramento já passou: ajuste-a antes de abrir."])
    abertura = _para_date(ciclo["abertura"])
    with conexao:
        if abertura is None or hoje < abertura:
            conexao.execute("UPDATE ciclo SET abertura = ? WHERE id = ?", (hoje.isoformat(), ciclo_id))
            auditoria.registrar(conexao, "ciclo", ciclo_id, "EDITAR", "abertura", ciclo["abertura"], hoje.isoformat(), usuario)
        _gravar_fase(conexao, ciclo, "ABERTO", usuario)


def encerrar_agora(conexao: sqlite3.Connection, ciclo_id: int, usuario: str | None, hoje: date) -> None:
    """Encerra o registro manualmente (ABERTO → ENCERRADO), mesmo antes da data. Vale também
    para o ciclo que a data já deixou aberto. Depois disso nem unidades prorrogadas registram."""

    usuario = auditoria.exigir_usuario(usuario)
    ciclo = _ciclo(conexao, ciclo_id)
    if ciclo["fase"] == "ENCERRADO":
        raise ErroCadastro(["O ciclo já está encerrado."])
    if ciclo["fase"] not in ("AGENDADO", "ABERTO") or fase_efetiva(ciclo, hoje) not in ("ABERTO", "ENCERRADO"):
        raise ErroCadastro([f"Só um ciclo aberto pode ser encerrado (fase atual: {fase_efetiva(ciclo, hoje)})."])
    with conexao:
        _gravar_fase(conexao, ciclo, "ENCERRADO", usuario)


# --- Prorrogação por unidade --------------------------------------------------------


def _validar_prorrogacao(
    conexao: sqlite3.Connection, ciclo: sqlite3.Row, novo_prazo: object, motivo: str | None
) -> tuple[str, str]:
    erros: list[str] = []
    prazo = _data(novo_prazo, "novo prazo", erros)
    if prazo is None and not erros:
        erros.append("Informe o novo prazo.")
    if prazo and ciclo["encerramento"] and prazo <= ciclo["encerramento"]:
        erros.append("O novo prazo precisa ser depois do encerramento do registro do ciclo.")
    motivo = (motivo or "").strip()
    if not motivo:
        erros.append("O motivo da prorrogação é obrigatório.")
    if ciclo["fase"] not in ("AGENDADO", "ABERTO"):
        erros.append(f"Só é possível prorrogar enquanto o registro não foi encerrado (fase atual: {ciclo['fase']}).")
    if erros:
        raise ErroCadastro(erros)
    return prazo, motivo


def conceder_prorrogacao(
    conexao: sqlite3.Connection, ciclo_id: int, unidade_id: int, novo_prazo: object, motivo: str | None, usuario: str | None
) -> int:
    """Novo prazo individual para uma unidade, com motivo obrigatório. Uma por unidade e
    ciclo; para mudar, use `alterar_prorrogacao`."""

    usuario = auditoria.exigir_usuario(usuario)
    ciclo = _ciclo(conexao, ciclo_id)
    unidade = conexao.execute("SELECT ativa FROM unidade WHERE id = ?", (unidade_id,)).fetchone()
    if unidade is None or not unidade["ativa"]:
        raise ErroCadastro(["Unidade não encontrada ou desativada."])
    if conexao.execute("SELECT 1 FROM prorrogacao WHERE ciclo_id = ? AND unidade_id = ?", (ciclo_id, unidade_id)).fetchone():
        raise ErroCadastro(["Esta unidade já tem prorrogação neste ciclo; altere a existente."])
    prazo, motivo = _validar_prorrogacao(conexao, ciclo, novo_prazo, motivo)
    with conexao:
        cursor = conexao.execute(
            "INSERT INTO prorrogacao (ciclo_id, unidade_id, novo_prazo, motivo, concedida_por, concedida_em)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (ciclo_id, unidade_id, prazo, motivo, usuario, auditoria.agora()),
        )
        prorrogacao_id = int(cursor.lastrowid)
        auditoria.registrar(conexao, "prorrogacao", prorrogacao_id, "PRORROGAR", "novo_prazo", None, prazo, usuario)
        auditoria.registrar(conexao, "prorrogacao", prorrogacao_id, "PRORROGAR", "motivo", None, motivo, usuario)
    return prorrogacao_id


def alterar_prorrogacao(
    conexao: sqlite3.Connection, prorrogacao_id: int, novo_prazo: object, motivo: str | None, usuario: str | None
) -> list[str]:
    """Muda prazo e/ou motivo de uma prorrogação existente (o valor anterior fica no histórico)."""

    usuario = auditoria.exigir_usuario(usuario)
    atual = conexao.execute("SELECT * FROM prorrogacao WHERE id = ?", (prorrogacao_id,)).fetchone()
    if atual is None:
        raise ErroCadastro([f"Prorrogação {prorrogacao_id} não encontrada."])
    prazo, motivo = _validar_prorrogacao(conexao, _ciclo(conexao, atual["ciclo_id"]), novo_prazo, motivo)
    mudancas = [(c, atual[c], v) for c, v in (("novo_prazo", prazo), ("motivo", motivo)) if atual[c] != v]
    if not mudancas:
        return []
    with conexao:
        conexao.execute(
            f"UPDATE prorrogacao SET {', '.join(f'{c} = ?' for c, _, _ in mudancas)} WHERE id = ?",
            (*[depois for _, _, depois in mudancas], prorrogacao_id),
        )
        for campo, antes, depois in mudancas:
            auditoria.registrar(conexao, "prorrogacao", prorrogacao_id, "PRORROGAR", campo, antes, depois, usuario)
    return [campo for campo, _, _ in mudancas]


def listar_prorrogacoes(conexao: sqlite3.Connection, ciclo_id: int) -> list[sqlite3.Row]:
    return conexao.execute(
        "SELECT p.*, u.ugr_codigo, u.nome AS unidade_nome FROM prorrogacao p"
        " JOIN unidade u ON u.id = p.unidade_id WHERE p.ciclo_id = ? ORDER BY u.nome",
        (ciclo_id,),
    ).fetchall()
