"""Isolamento de diretórios para os testes de reimportação via `AppTest` — ver
`tests/test_execucao_orcamentaria_reimportacao.py` e
`tests/test_dotacao_orcamentaria_reimportacao.py`.

Espelha o padrão já usado por `tests/test_atualizar_planilhas.py` (constrói a própria
`EspecificacaoBase` apontando pra um diretório temporário, nunca pra `data/raw/` real — ver
AGENTS.md, "Fixtures de teste vs. dados de trabalho"), adaptado para
`EspecificacaoReimportacao`: as duas instâncias de produção (`ESPECIFICACAO_EXECUCAO_ANUAL`/
`ESPECIFICACAO_DOTACAO_ANUAL`, em `src/reimportacao_especificacoes.py`) são singletons
construídos uma vez, sem ponto de injeção próprio.

Como as páginas testadas rodam via `AppTest.from_file("app.py")` (reexecuta o script inteiro a
cada `app.run()`, no mesmo processo, mesmo `sys.modules`), o ponto de injeção é fazer
monkeypatch desses dois atributos de módulo antes de abrir a página — a reexecução de
`from src.reimportacao_especificacoes import ESPECIFICACAO_...` a cada rerun sempre lê o valor
atual do atributo do módulo, então o patch é visto pela página sem precisar reimplementar a
navegação.
"""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path
from unittest import mock

from src import reimportacao_especificacoes
from src.importacao_dotacao import ResultadoImportacao as ResultadoImportacaoDotacao
from src.importacao_dotacao import importar as importar_dotacao
from src.importacao_execucao import ResultadoImportacao as ResultadoImportacaoExecucao
from src.importacao_execucao import importar as importar_execucao


class IsolamentoReimportacaoMixin:
    """Mixin — combinar com `unittest.TestCase` (usa `self.addCleanup`). `setUp`/`tearDown`
    (via `addCleanup`) que redirecionam `ESPECIFICACAO_EXECUCAO_ANUAL` e
    `ESPECIFICACAO_DOTACAO_ANUAL` para um diretório temporário — nenhuma escrita em
    `data/raw/`/`data/manifestos/` reais durante o teste. As duas specs compartilham o mesmo
    `raw/` (a pasta `_entrada` é compartilhada entre bases, ver `src/ui_reimportacao.py`) e o
    mesmo `manifestos/` (como em produção: um diretório só, arquivos namespaced por base).
    """

    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        raiz = Path(self._tmpdir.name)
        self.tmp_raw = raiz / "raw"
        self.tmp_manifestos = raiz / "manifestos"
        self.tmp_raw.mkdir()
        self.tmp_manifestos.mkdir()

        self._patch_spec("ESPECIFICACAO_EXECUCAO_ANUAL")
        self._patch_spec("ESPECIFICACAO_DOTACAO_ANUAL")

    def _patch_spec(self, nome_atributo: str) -> None:
        original = getattr(reimportacao_especificacoes, nome_atributo)
        redirecionada = dataclasses.replace(
            original,
            diretorio_dados_brutos=self.tmp_raw,
            diretorio_manifestos=self.tmp_manifestos,
        )
        patcher = mock.patch.object(reimportacao_especificacoes, nome_atributo, redirecionada)
        patcher.start()
        self.addCleanup(patcher.stop)

    def importar_baseline_execucao(self, caminho_fixture: Path) -> ResultadoImportacaoExecucao:
        caminho = self.tmp_raw / caminho_fixture.name
        caminho.write_bytes(caminho_fixture.read_bytes())
        resultado = importar_execucao(caminho, diretorio_manifestos=self.tmp_manifestos)
        assert resultado.ok, resultado.validacao.erros
        return resultado

    def importar_baseline_dotacao(self, conteudo: bytes, nome_arquivo: str) -> ResultadoImportacaoDotacao:
        caminho = self.tmp_raw / nome_arquivo
        caminho.write_bytes(conteudo)
        resultado = importar_dotacao(caminho, diretorio_manifestos=self.tmp_manifestos)
        assert resultado.ok, resultado.validacao.erros
        return resultado
