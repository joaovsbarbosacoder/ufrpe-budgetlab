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

CREATE INDEX IF NOT EXISTS ix_alerta_status ON alerta (status);
CREATE INDEX IF NOT EXISTS ix_vinculo_ne_chave_empenho ON vinculo_ne (chave_empenho);
CREATE INDEX IF NOT EXISTS ix_decisao_vinculo_ne_empenho
    ON decisao_vinculo_ne (chave_empenho, id);
"""


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
