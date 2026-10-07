"""Schema SQLite da Captação de Demandas (MVP da seção 10 do projeto de origem).

Persistência própria e isolada, aprovada explicitamente para este módulo (substitui o
antigo `src/demandas_orcamentarias.py`, que gravava um JSON por demanda). Mesmo padrão
de `src/teds_schema.py`: `conectar(":memory:")` nos testes, nunca tocando o arquivo real.

Decisões:

- Valores monetários ficam em TEXT com decimal exato (`"1234.50"`), nunca REAL — mesma
  decisão deliberada do módulo de TEDs; as regras convertem para `Decimal`.
- Datas são TEXT ISO (`YYYY-MM-DD`; instantes em ISO 8601 com fuso).
- Não há tabela de usuários/papéis: o BudgetLab não tem login. `usuario` é um rótulo
  livre (quem registrou/validou), até haver autenticação (ponto em aberto 6 do projeto).
- Excluir uma demanda nunca é físico: `excluida_em` (só em RASCUNHO, regra do serviço).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

CAMINHO_BANCO_PADRAO = Path("data/captacao/captacao.db")

_DDL = """
CREATE TABLE IF NOT EXISTS unidade (
    id          INTEGER PRIMARY KEY,
    ugr_codigo  TEXT NOT NULL UNIQUE,
    nome        TEXT NOT NULL,
    sigla       TEXT,
    ativa       INTEGER NOT NULL DEFAULT 1 CHECK (ativa IN (0, 1))
);

CREATE TABLE IF NOT EXISTS objetivo_pdi (
    id          INTEGER PRIMARY KEY,
    codigo      TEXT NOT NULL,
    dimensao    TEXT,
    descricao   TEXT NOT NULL,
    versao_pdi  TEXT NOT NULL,
    ativo       INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    UNIQUE (versao_pdi, codigo)
);

CREATE TABLE IF NOT EXISTS meta_pls (
    id          INTEGER PRIMARY KEY,
    eixo        TEXT,
    objetivo    TEXT,
    codigo      TEXT NOT NULL,
    descricao   TEXT NOT NULL,
    versao_pls  TEXT NOT NULL,
    ativo       INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    UNIQUE (versao_pls, codigo)
);

CREATE TABLE IF NOT EXISTS ciclo (
    id                          INTEGER PRIMARY KEY,
    exercicio                   INTEGER NOT NULL UNIQUE,
    fase                        TEXT NOT NULL DEFAULT 'RASCUNHO'
        CHECK (fase IN ('RASCUNHO', 'AGENDADO', 'ABERTO', 'ENCERRADO', 'EM_ANALISE', 'CONCLUIDO')),
    abertura                    TEXT,
    encerramento                TEXT,
    prazo_validacao             TEXT,
    devolutiva_prevista         TEXT,
    versao_pdi                  TEXT,
    versao_pls                  TEXT,
    permite_rascunho_antecipado INTEGER NOT NULL DEFAULT 0 CHECK (permite_rascunho_antecipado IN (0, 1)),
    somente_leitura_apos        INTEGER NOT NULL DEFAULT 1 CHECK (somente_leitura_apos IN (0, 1)),
    mensagem_abertura           TEXT,
    avisos_json                 TEXT,
    criado_por                  TEXT,
    criado_em                   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prorrogacao (
    id           INTEGER PRIMARY KEY,
    ciclo_id     INTEGER NOT NULL REFERENCES ciclo (id),
    unidade_id   INTEGER NOT NULL REFERENCES unidade (id),
    novo_prazo   TEXT NOT NULL,
    motivo       TEXT NOT NULL CHECK (length(trim(motivo)) > 0),
    concedida_por TEXT,
    concedida_em TEXT NOT NULL,
    UNIQUE (ciclo_id, unidade_id)
);

CREATE TABLE IF NOT EXISTS importacao_planilha (
    id           INTEGER PRIMARY KEY,
    ciclo_id     INTEGER NOT NULL REFERENCES ciclo (id),
    unidade_id   INTEGER NOT NULL REFERENCES unidade (id),
    usuario      TEXT,
    arquivo      TEXT NOT NULL,
    criada_em    TEXT NOT NULL,
    situacao     TEXT NOT NULL DEFAULT 'EM_REVISAO'
        CHECK (situacao IN ('EM_REVISAO', 'CONCLUIDA', 'CANCELADA')),
    total_linhas INTEGER NOT NULL DEFAULT 0,
    prontas      INTEGER NOT NULL DEFAULT 0,
    alertas      INTEGER NOT NULL DEFAULT 0,
    erros        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS demanda (
    id                       INTEGER PRIMARY KEY,
    ciclo_id                 INTEGER NOT NULL REFERENCES ciclo (id),
    unidade_id               INTEGER NOT NULL REFERENCES unidade (id),
    criada_por               TEXT,
    tipo                     TEXT,
    descricao                TEXT,
    codigo_catalogo          TEXT,
    quantidade               INTEGER,
    unidade_fornecimento     TEXT,
    valor_unitario           TEXT,
    valor_total              TEXT,
    natureza_sugerida        TEXT CHECK (natureza_sugerida IN ('CUSTEIO', 'CAPITAL')),
    natureza_final           TEXT CHECK (natureza_final IN ('CUSTEIO', 'CAPITAL')),
    prioridade               TEXT CHECK (prioridade IN ('ESSENCIAL', 'IMPORTANTE', 'DESEJAVEL')),
    risco                    TEXT,
    justificativa            TEXT,
    contribuicao             TEXT,
    depende_licitacao        INTEGER CHECK (depende_licitacao IN (0, 1)),
    existe_arp               INTEGER CHECK (existe_arp IN (0, 1)),
    recorrente               INTEGER CHECK (recorrente IN (0, 1)),
    solicita_analise_vinculo INTEGER NOT NULL DEFAULT 0 CHECK (solicita_analise_vinculo IN (0, 1)),
    origem                   TEXT NOT NULL DEFAULT 'MANUAL'
        CHECK (origem IN ('MANUAL', 'IMPORTACAO', 'CONTRATO')),
    linha_origem             INTEGER,
    importacao_id            INTEGER REFERENCES importacao_planilha (id),
    situacao                 TEXT NOT NULL DEFAULT 'RASCUNHO'
        CHECK (situacao IN ('RASCUNHO', 'ENVIADA', 'VALIDADA_CHEFIA', 'VALIDADA_PROPLAD',
                            'INCLUIDA_PROPOSTA', 'NAO_INCLUIDA')),
    devolvida                INTEGER NOT NULL DEFAULT 0 CHECK (devolvida IN (0, 1)),
    enviada_em               TEXT,
    excluida_em              TEXT,
    criada_em                TEXT NOT NULL,
    atualizada_em            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_demanda_ciclo_unidade_situacao ON demanda (ciclo_id, unidade_id, situacao);
CREATE INDEX IF NOT EXISTS ix_demanda_ciclo_situacao ON demanda (ciclo_id, situacao);

CREATE TABLE IF NOT EXISTS demanda_objetivo_pdi (
    demanda_id  INTEGER NOT NULL REFERENCES demanda (id),
    objetivo_id INTEGER NOT NULL REFERENCES objetivo_pdi (id),
    PRIMARY KEY (demanda_id, objetivo_id)
);

CREATE TABLE IF NOT EXISTS demanda_meta_pls (
    demanda_id INTEGER NOT NULL REFERENCES demanda (id),
    meta_id    INTEGER NOT NULL REFERENCES meta_pls (id),
    PRIMARY KEY (demanda_id, meta_id)
);

CREATE TABLE IF NOT EXISTS anexo (
    id            INTEGER PRIMARY KEY,
    demanda_id    INTEGER NOT NULL REFERENCES demanda (id),
    arquivo       TEXT NOT NULL,
    nome_original TEXT NOT NULL,
    tipo          TEXT NOT NULL DEFAULT 'OUTRO' CHECK (tipo IN ('ORCAMENTO', 'FOTO', 'ETP', 'OUTRO')),
    tamanho       INTEGER,
    enviado_por   TEXT,
    enviado_em    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS historico_situacao (
    id         INTEGER PRIMARY KEY,
    demanda_id INTEGER NOT NULL REFERENCES demanda (id),
    de         TEXT,
    para       TEXT NOT NULL,
    usuario    TEXT,
    comentario TEXT,
    criado_em  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_historico_demanda ON historico_situacao (demanda_id, criado_em);

CREATE TABLE IF NOT EXISTS importacao_linha (
    id            INTEGER PRIMARY KEY,
    importacao_id INTEGER NOT NULL REFERENCES importacao_planilha (id),
    numero_linha  INTEGER NOT NULL,
    dados_json    TEXT NOT NULL,
    situacao      TEXT NOT NULL CHECK (situacao IN ('OK', 'ALERTA', 'ERRO')),
    mensagens_json TEXT,
    demanda_id    INTEGER REFERENCES demanda (id)
);

CREATE TABLE IF NOT EXISTS criterio (
    id       INTEGER PRIMARY KEY,
    ciclo_id INTEGER NOT NULL REFERENCES ciclo (id),
    nome     TEXT NOT NULL,
    peso     TEXT NOT NULL,
    ordem    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS avaliacao (
    id           INTEGER PRIMARY KEY,
    demanda_id   INTEGER NOT NULL REFERENCES demanda (id),
    criterio_id  INTEGER NOT NULL REFERENCES criterio (id),
    nota         TEXT NOT NULL,
    avaliado_por TEXT,
    avaliado_em  TEXT NOT NULL,
    UNIQUE (demanda_id, criterio_id)
);

-- Trilha de auditoria dos planos de referência (src/captacao/planos.py): uma linha por
-- campo alterado, com o valor antes e depois. `item_id` aponta para a tabela indicada em
-- `tabela` (sem FK, pois há duas tabelas de destino).
CREATE TABLE IF NOT EXISTS historico_plano (
    id        INTEGER PRIMARY KEY,
    tabela    TEXT NOT NULL CHECK (tabela IN ('objetivo_pdi', 'meta_pls')),
    item_id   INTEGER NOT NULL,
    acao      TEXT NOT NULL CHECK (acao IN ('CRIAR', 'EDITAR', 'DESATIVAR', 'REATIVAR', 'CARGA')),
    campo     TEXT,
    antes     TEXT,
    depois    TEXT,
    usuario   TEXT,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_historico_plano_item ON historico_plano (tabela, item_id, criado_em);

-- Trilha de auditoria de unidades, ciclos e prorrogações (src/captacao/auditoria.py): uma
-- linha por campo alterado ou evento (mudança de fase, prorrogação).
CREATE TABLE IF NOT EXISTS historico_cadastro (
    id        INTEGER PRIMARY KEY,
    tabela    TEXT NOT NULL CHECK (tabela IN ('unidade', 'ciclo', 'prorrogacao')),
    item_id   INTEGER NOT NULL,
    acao      TEXT NOT NULL CHECK (acao IN ('CRIAR', 'EDITAR', 'ATIVAR', 'DESATIVAR', 'FASE', 'PRORROGAR')),
    campo     TEXT,
    antes     TEXT,
    depois    TEXT,
    usuario   TEXT,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_historico_cadastro_item ON historico_cadastro (tabela, item_id, criado_em);

CREATE TABLE IF NOT EXISTS cenario (
    id             INTEGER PRIMARY KEY,
    ciclo_id       INTEGER NOT NULL REFERENCES ciclo (id),
    nome           TEXT NOT NULL,
    limite_total   TEXT NOT NULL,
    limite_custeio TEXT,
    limite_capital TEXT,
    escolhido      INTEGER NOT NULL DEFAULT 0 CHECK (escolhido IN (0, 1))
);
"""

TABELAS = (
    "unidade",
    "objetivo_pdi",
    "meta_pls",
    "ciclo",
    "prorrogacao",
    "importacao_planilha",
    "demanda",
    "demanda_objetivo_pdi",
    "demanda_meta_pls",
    "anexo",
    "historico_situacao",
    "importacao_linha",
    "criterio",
    "avaliacao",
    "cenario",
    "historico_plano",
    "historico_cadastro",
)


def conectar(caminho: str | Path = CAMINHO_BANCO_PADRAO) -> sqlite3.Connection:
    """Abre (criando se necessário) o banco da Captação, com o schema já aplicado.

    `caminho=":memory:"` é o padrão dos testes — banco isolado por conexão, nunca tocando
    `data/captacao/captacao.db`.
    """

    if str(caminho) != ":memory:":
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)

    conexao = sqlite3.connect(caminho)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    conexao.executescript(_DDL)
    conexao.commit()
    return conexao
