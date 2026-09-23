"""
Schema SQLite do módulo de TEDs (Termos de Execução Descentralizada).

Decisão de arquitetura aprovada explicitamente para este módulo (ver conversa de
alinhamento): ao contrário das demais bases do projeto (manifesto versionado, sem banco —
`src/importacao_versionada.py`), o acompanhamento de TEDs precisa cruzar cinco fontes
diferentes (TED, NC, PF, NE-SIMEC, execução no Tesouro Gerencial) e manter uma fila de
decisões (vínculo de NE pendente, alerta com justificativa e histórico) que não cabe no
padrão de "recarregar tudo do Excel a cada acesso". O banco fica isolado em
`data/teds/teds.db`, sem afetar o padrão das outras bases.

Todo valor monetário é armazenado como TEXT (Decimal exato via
`src/teds_normalizacao.valor_para_texto`), nunca REAL — ver o motivo no docstring daquele
módulo.

`linha_origem` (TEXT, JSON) preserva a linha original da planilha para auditoria (regra 3 do
briefing) e `import_batch_id` referencia o lote que gravou/atualizou aquele registro pela
última vez — histórico de lotes é mantido inteiro em `import_batch`, nunca sobrescrito.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

CAMINHO_BANCO_PADRAO = Path("data/teds/teds.db")

#: Colunas de "total de controle" (regra 6.2 do briefing) adicionadas depois da criação
#: original de `import_batch` — migradas via `ALTER TABLE` em `conectar()` para não perder o
#: histórico já gravado em `data/teds/teds.db` (lotes antigos ficam com essas colunas NULL,
#: nunca com um total inventado). Somas ficam em TEXT/Decimal, nunca REAL (ver
#: `src/teds_normalizacao.py`). "Total do rodapé" e a diferença contra ele NÃO entraram nesta
#: rodada: as 4 extrações reais revisadas (ver docstring de `src/teds_importacao_simec.py`)
#: não tiveram uma linha de rodapé com total confirmada coluna a coluna — capturar isso exigiria
#: presumir um formato ainda não visto, o que o projeto evita fazer (ver AGENTS.md).
_COLUNAS_CONTROLE_IMPORT_BATCH: dict[str, str] = {
    "quantidade_linhas_lidas": "INTEGER",
    "quantidade_rejeitadas": "INTEGER",
    "quantidade_com_aviso": "INTEGER",
    "soma_bruta": "TEXT",
    "soma_positiva": "TEXT",
    "soma_negativa": "TEXT",
    "soma_liquida": "TEXT",
    # Reversão de lote (`src/teds_reversao.py`). `versionado` = 1 só nos lotes gravados quando
    # o histórico de versões já existia: um lote anterior a isso pode ter sobrescrito linhas sem
    # deixar o valor antigo guardado, então NÃO pode ser revertido com segurança.
    "versionado": "INTEGER",
    "revertido_em": "TEXT",
    "revertido_por": "TEXT",
    "motivo_reversao": "TEXT",
}

_DDL = """
CREATE TABLE IF NOT EXISTS import_batch (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_relatorio TEXT NOT NULL,
    nome_arquivo TEXT NOT NULL,
    hash_arquivo TEXT NOT NULL,
    data_importacao TEXT NOT NULL,
    quantidade_registros INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    mensagem_erro TEXT
);

CREATE INDEX IF NOT EXISTS ix_import_batch_tipo_hash
    ON import_batch (tipo_relatorio, hash_arquivo);

CREATE TABLE IF NOT EXISTS ted (
    chave_ted TEXT PRIMARY KEY,
    ted TEXT NOT NULL,
    codigo_siafi TEXT NOT NULL,
    descricao TEXT,
    estado_atual TEXT,
    inicio_vigencia TEXT,
    fim_vigencia TEXT,
    ug_descentralizadora TEXT,
    ug_descentralizada TEXT,
    import_batch_id INTEGER
);

CREATE TABLE IF NOT EXISTS execucao_anual (
    chave_ted TEXT NOT NULL,
    ano_emissao INTEGER NOT NULL,
    total_nc_descentralizacao TEXT NOT NULL,
    total_nc_devolucao TEXT NOT NULL,
    total_descentralizado TEXT NOT NULL,
    total_pf_repasse TEXT NOT NULL,
    total_pf_devolucao TEXT NOT NULL,
    total_repassado TEXT NOT NULL,
    import_batch_id INTEGER NOT NULL,
    linha_origem TEXT NOT NULL,
    PRIMARY KEY (chave_ted, ano_emissao)
);

-- DOC NC é modelado em dois níveis (ver docstring de `ler_doc_nc_simec` em
-- src/teds_importacao_simec.py): a extração real repete o mesmo documento em várias linhas
-- (rateio por fonte/ação) e ~41% das linhas legítimas não trazem UG emitente — por isso
-- `ug_emitente` é opcional aqui (nunca preenchida com `ug_descentralizadora` como substituto)
-- e a chave de deduplicação não pode ser (ug_emitente, numero_nc) como nas demais bases.
--
-- Nível de LINHA da planilha: chave `chave_nc_linha` (lote de importação + índice de origem)
-- garante idempotência linha a linha e rastreabilidade — nunca usada para agrupar.
CREATE TABLE IF NOT EXISTS documento_nc_linha (
    chave_nc_linha TEXT PRIMARY KEY,
    chave_nc_documento TEXT NOT NULL,
    chave_ted TEXT,
    ted TEXT,
    codigo_siafi TEXT,
    numero_nc TEXT NOT NULL,
    ug_emitente TEXT,
    data_emissao TEXT,
    operacao TEXT NOT NULL,
    valor_original TEXT NOT NULL,
    valor_assinado TEXT NOT NULL,
    status_relacionamento TEXT NOT NULL,
    avisos TEXT NOT NULL DEFAULT '[]',
    import_batch_id INTEGER NOT NULL,
    linha_origem TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_documento_nc_linha_documento
    ON documento_nc_linha (chave_nc_documento);

-- Nível de DOCUMENTO (agregado): chave `chave_nc_documento` (TED+SIAFI+número+operação+data,
-- sem a UG emitente — ela não identifica o documento e vem ausente em boa parte das linhas).
-- Os totais somam TODAS as linhas de `documento_nc_linha` daquela chave a cada reimportação
-- do arquivo completo (nunca um incremento) — mesmo padrão de "última extração vence" já
-- usado em `execucao_anual`/`vinculo_ne` nesta tabela.
CREATE TABLE IF NOT EXISTS documento_nc (
    chave_nc_documento TEXT PRIMARY KEY,
    chave_ted TEXT,
    ted TEXT,
    codigo_siafi TEXT,
    numero_nc TEXT NOT NULL,
    ug_emitente TEXT,
    data_emissao TEXT,
    operacao TEXT NOT NULL,
    valor_original_total TEXT NOT NULL,
    valor_assinado_total TEXT NOT NULL,
    quantidade_linhas INTEGER NOT NULL,
    status_relacionamento TEXT NOT NULL,
    import_batch_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS documento_pf (
    chave_ted TEXT NOT NULL,
    ug_emitente TEXT NOT NULL,
    numero_pf TEXT NOT NULL,
    data_emissao TEXT,
    operacao TEXT NOT NULL,
    valor_original TEXT NOT NULL,
    valor_assinado TEXT NOT NULL,
    import_batch_id INTEGER NOT NULL,
    linha_origem TEXT NOT NULL,
    PRIMARY KEY (ug_emitente, numero_pf)
);

-- Uma linha por par (TED, empenho): é isso que permite a mesma NE aparecer sob dois TEDs
-- diferentes sem uma sobrescrever a outra — ver src/teds_alertas.py.
CREATE TABLE IF NOT EXISTS vinculo_ne (
    chave_ted TEXT NOT NULL,
    chave_empenho TEXT NOT NULL,
    ug_emitente TEXT NOT NULL,
    gestao_emitente TEXT NOT NULL,
    numero_ne TEXT NOT NULL,
    valor_ne TEXT NOT NULL,
    descricao_ne TEXT,
    status_validacao TEXT NOT NULL DEFAULT 'ok',
    import_batch_id INTEGER NOT NULL,
    linha_origem TEXT NOT NULL,
    PRIMARY KEY (chave_ted, chave_empenho)
);

-- Espelho da Execução Mensal (Tesouro Gerencial), sincronizado por
-- `src/teds_lotes.py::sincronizar_execucao_tg` — uma linha por NE × mês de LANÇAMENTO (não
-- competência: ver docs/base_teds.md seção 6). Empenhado/liquidado/pago são movimentos do
-- mês, não acumulados — somar por NE dá o total. Nomes `ano_lancamento`/`mes_lancamento`
-- (antes `ano_competencia`/`mes_competencia`) evitam rotular lançamento como competência.
CREATE TABLE IF NOT EXISTS execucao_tg (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_completo_ne TEXT NOT NULL,
    favorecido TEXT,
    descricao TEXT,
    empenhado TEXT,
    liquidado TEXT,
    pago TEXT,
    ano_lancamento INTEGER NOT NULL,
    mes_lancamento INTEGER NOT NULL,
    import_batch_id INTEGER NOT NULL,
    linha_origem TEXT NOT NULL,
    UNIQUE (numero_completo_ne, ano_lancamento, mes_lancamento)
);

CREATE TABLE IF NOT EXISTS alerta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    gravidade TEXT NOT NULL,
    chave_ted TEXT,
    documento TEXT,
    descricao TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'aberto',
    data_identificacao TEXT NOT NULL,
    responsavel TEXT,
    justificativa TEXT,
    data_resolucao TEXT
);

-- Registro append-only da decisão humana para uma NE associada a múltiplos TEDs.
-- Os vínculos originais não são apagados: apenas um fica contabilizável, e a fotografia dos
-- TEDs envolvidos permite invalidar a decisão se uma importação futura mudar o conflito.
CREATE TABLE IF NOT EXISTS decisao_vinculo_ne (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chave_empenho TEXT NOT NULL,
    chave_ted_escolhida TEXT NOT NULL,
    teds_envolvidos TEXT NOT NULL,
    decisao TEXT NOT NULL,
    responsavel TEXT NOT NULL,
    justificativa TEXT NOT NULL,
    data_decisao TEXT NOT NULL,
    alerta_id INTEGER NOT NULL
);

-- Trilha de auditoria (`src/teds_auditoria.py`): append-only. Os gatilhos abaixo abortam
-- UPDATE e DELETE, então nem uma correção posterior reescreve a história — corrigir é inserir
-- um novo registro. `valor_anterior`/`valor_novo` são JSON dos campos que mudaram.
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora TEXT NOT NULL,
    usuario TEXT NOT NULL,
    acao TEXT NOT NULL,
    entidade TEXT NOT NULL,
    entidade_id TEXT NOT NULL,
    valor_anterior TEXT,
    valor_novo TEXT,
    motivo TEXT,
    origem TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_auditoria_entidade ON auditoria (entidade, entidade_id, id);

CREATE TRIGGER IF NOT EXISTS trg_auditoria_sem_update
BEFORE UPDATE ON auditoria
BEGIN
    SELECT RAISE(ABORT, 'auditoria é append-only: não pode ser alterada');
END;

CREATE TRIGGER IF NOT EXISTS trg_auditoria_sem_delete
BEFORE DELETE ON auditoria
BEGIN
    SELECT RAISE(ABORT, 'auditoria é append-only: não pode ser apagada');
END;

CREATE INDEX IF NOT EXISTS ix_alerta_status ON alerta (status);
CREATE INDEX IF NOT EXISTS ix_vinculo_ne_chave_empenho ON vinculo_ne (chave_empenho);
CREATE INDEX IF NOT EXISTS ix_decisao_vinculo_ne_empenho
    ON decisao_vinculo_ne (chave_empenho, id);
"""


# --------------------------------------------------------------------------------------
# Histórico de versões e reversão de lote (`src/teds_reversao.py`, briefing seção 6.4)
# --------------------------------------------------------------------------------------

#: Tabelas cujas linhas carregam `import_batch_id` e podem ser sobrescritas por um lote novo
#: (`INSERT ... ON CONFLICT DO UPDATE`). Para cada uma: (colunas da chave natural, todas as
#: colunas). Um gatilho `BEFORE UPDATE` copia a versão ANTERIOR para `historico_linha` toda vez
#: que um lote diferente sobrescreve a linha — é isso que permite reverter um lote de verdade.
#: `tests/test_teds_reversao.py` confere que estas listas batem com o esquema real (uma coluna
#: nova esquecida aqui deixaria de ser preservada no histórico).
TABELAS_VERSIONADAS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "ted": (
        ("chave_ted",),
        ("chave_ted", "ted", "codigo_siafi", "descricao", "estado_atual", "inicio_vigencia",
         "fim_vigencia", "ug_descentralizadora", "ug_descentralizada", "import_batch_id"),
    ),
    "execucao_anual": (
        ("chave_ted", "ano_emissao"),
        ("chave_ted", "ano_emissao", "total_nc_descentralizacao", "total_nc_devolucao",
         "total_descentralizado", "total_pf_repasse", "total_pf_devolucao", "total_repassado",
         "import_batch_id", "linha_origem"),
    ),
    "vinculo_ne": (
        ("chave_ted", "chave_empenho"),
        ("chave_ted", "chave_empenho", "ug_emitente", "gestao_emitente", "numero_ne", "valor_ne",
         "descricao_ne", "status_validacao", "import_batch_id", "linha_origem"),
    ),
    "documento_nc_linha": (
        ("chave_nc_linha",),
        ("chave_nc_linha", "chave_nc_documento", "chave_ted", "ted", "codigo_siafi", "numero_nc",
         "ug_emitente", "data_emissao", "operacao", "valor_original", "valor_assinado",
         "status_relacionamento", "avisos", "import_batch_id", "linha_origem"),
    ),
    "documento_nc": (
        ("chave_nc_documento",),
        ("chave_nc_documento", "chave_ted", "ted", "codigo_siafi", "numero_nc", "ug_emitente",
         "data_emissao", "operacao", "valor_original_total", "valor_assinado_total",
         "quantidade_linhas", "status_relacionamento", "import_batch_id"),
    ),
    "documento_pf": (
        ("ug_emitente", "numero_pf"),
        ("chave_ted", "ug_emitente", "numero_pf", "data_emissao", "operacao", "valor_original",
         "valor_assinado", "import_batch_id", "linha_origem"),
    ),
    "execucao_tg": (
        ("numero_completo_ne", "ano_lancamento", "mes_lancamento"),
        ("id", "numero_completo_ne", "favorecido", "descricao", "empenhado", "liquidado", "pago",
         "ano_lancamento", "mes_lancamento", "import_batch_id", "linha_origem"),
    ),
}


def _json_object_sql(prefixo: str, colunas: tuple[str, ...]) -> str:
    return "json_object(" + ", ".join(f"'{c}', {prefixo}.{c}" for c in colunas) + ")"


def _gerar_ddl_versionamento() -> str:
    partes = [
        """
-- Versão ANTERIOR de uma linha, copiada por gatilho quando um lote diferente a sobrescreve.
-- `import_batch_id_origem` é o lote que escreveu a versão guardada; `..._sobrescritor`, o lote
-- que a substituiu. Append-only, como a auditoria.
CREATE TABLE IF NOT EXISTS historico_linha (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tabela TEXT NOT NULL,
    chave TEXT NOT NULL,
    import_batch_id_origem INTEGER,
    import_batch_id_sobrescritor INTEGER,
    conteudo TEXT NOT NULL,
    data_hora TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_historico_linha_sobrescritor
    ON historico_linha (tabela, import_batch_id_sobrescritor);

-- Linhas que uma reversão de lote retirou das tabelas de trabalho (a linha do lote revertido,
-- inteira, em JSON). Nada é descartado: sai dos totais mas continua consultável aqui.
CREATE TABLE IF NOT EXISTS linha_revertida (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_batch_id INTEGER NOT NULL,
    tabela TEXT NOT NULL,
    chave TEXT NOT NULL,
    conteudo TEXT NOT NULL,
    acao TEXT NOT NULL,
    data_hora TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_linha_revertida_lote ON linha_revertida (import_batch_id);

-- Interruptor de uma linha só: a reversão o liga para restaurar linhas sem que o gatilho
-- registre a própria restauração como se fosse uma nova sobrescrita.
CREATE TABLE IF NOT EXISTS versionamento_controle (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pausado INTEGER NOT NULL DEFAULT 0
);
INSERT INTO versionamento_controle (id, pausado) VALUES (1, 0) ON CONFLICT (id) DO NOTHING;
"""
    ]
    for tabela in ("historico_linha", "linha_revertida"):
        for operacao in ("UPDATE", "DELETE"):
            partes.append(
                f"""
CREATE TRIGGER IF NOT EXISTS trg_{tabela}_sem_{operacao.lower()}
BEFORE {operacao} ON {tabela}
BEGIN
    SELECT RAISE(ABORT, '{tabela} é append-only: não pode ser alterada nem apagada');
END;
"""
            )
    for tabela, (chave, colunas) in TABELAS_VERSIONADAS.items():
        partes.append(
            f"""
CREATE TRIGGER IF NOT EXISTS trg_versao_{tabela}
BEFORE UPDATE ON {tabela}
WHEN OLD.import_batch_id IS NOT NEW.import_batch_id
     AND (SELECT pausado FROM versionamento_controle WHERE id = 1) = 0
BEGIN
    INSERT INTO historico_linha
        (tabela, chave, import_batch_id_origem, import_batch_id_sobrescritor, conteudo, data_hora)
    VALUES
        ('{tabela}', {_json_object_sql("OLD", chave)}, OLD.import_batch_id, NEW.import_batch_id,
         {_json_object_sql("OLD", colunas)}, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
END;
"""
        )
    return "".join(partes)


_DDL += _gerar_ddl_versionamento()


def _migrar_colunas_controle_import_batch(conexao: sqlite3.Connection) -> None:
    """`ALTER TABLE ... ADD COLUMN` idempotente para quem já tinha `data/teds/teds.db` gravado
    antes das colunas de "total de controle" existirem — nunca recria a tabela nem apaga
    lotes já importados; colunas novas ficam NULL nas linhas antigas (nunca um total
    inventado para um lote que já rodou sem essa contabilidade)."""

    existentes = {linha[1] for linha in conexao.execute("PRAGMA table_info(import_batch)").fetchall()}
    for coluna, tipo_sql in _COLUNAS_CONTROLE_IMPORT_BATCH.items():
        if coluna not in existentes:
            conexao.execute(f"ALTER TABLE import_batch ADD COLUMN {coluna} {tipo_sql}")


def _migrar_execucao_tg_para_lancamento(conexao: sqlite3.Connection) -> None:
    """Troca o `execucao_tg` do layout antigo (uma linha por NE/documento hábil/documento
    contábil/competência, lido de arquivo próprio — nunca confirmado contra uma extração real)
    pelo layout atual (NE × mês de lançamento, sincronizado da Execução Mensal). Roda ANTES do
    `_DDL`, que só cria a tabela nova se ela não existir.

    Nunca descarta dado financeiro em silêncio: tabela antiga vazia é simplesmente removida;
    com linhas, é PRESERVADA renomeada para `execucao_tg_legado` (sufixo numérico se esse nome
    já existir) — o novo layout não tem para onde mapear documento hábil/contábil nem
    competência, então essas linhas não são convertidas, só guardadas."""

    colunas = {linha[1] for linha in conexao.execute("PRAGMA table_info(execucao_tg)").fetchall()}
    if not colunas or "documento_habil" not in colunas:
        return

    (linhas,) = conexao.execute("SELECT COUNT(*) FROM execucao_tg").fetchone()
    if linhas == 0:
        conexao.execute("DROP TABLE execucao_tg")
        return

    existentes = {linha[0] for linha in conexao.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    destino, sufixo = "execucao_tg_legado", 1
    while destino in existentes:
        sufixo += 1
        destino = f"execucao_tg_legado_{sufixo}"
    conexao.execute(f"ALTER TABLE execucao_tg RENAME TO {destino}")


def conectar(caminho: str | Path = CAMINHO_BANCO_PADRAO) -> sqlite3.Connection:
    """Abre (criando se necessário) o banco de TEDs, com o schema já aplicado.

    `caminho=":memory:"` é o padrão usado pelos testes — banco isolado por conexão, nunca
    tocando `data/teds/teds.db`.
    """

    if caminho != ":memory:":
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)

    conexao = sqlite3.connect(caminho)
    conexao.execute("PRAGMA foreign_keys = ON")
    _migrar_execucao_tg_para_lancamento(conexao)
    conexao.executescript(_DDL)
    _migrar_colunas_controle_import_batch(conexao)
    conexao.commit()
    return conexao
