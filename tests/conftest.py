"""Configuração comum da suíte.

Cache das bases: os testes de página executam o `app.py`, que liga o cache das bases
(`src/cache_bases.py`) na pasta real `data/processed/cache_bases/`. Com esta variável, o
`ativar_no_app()` não liga nada: a suíte lê sempre a planilha e não grava nem reaproveita cópias fora
dos testes do próprio cache (que ligam com `ativar(diretorio)` numa pasta temporária). Definida no
carregamento, vale também para os processos do pytest-xdist.

Memória dos testes de página (07/10/2026): cada execução do `AppTest` deixa para trás objetos com
referências circulares que seguram DataFrames inteiros (cópias devolvidas pelo `st.cache_data`). O
coletor de lixo do Python dispara pela QUANTIDADE de objetos, não pelo tamanho deles — poucos objetos
grandes quase não o acionam —, então a memória subia ~0,5 GB por teste: `test_consulta_empenhos_page.py`
chegava a ~8 GB num processo, e com `-n auto` a soma passava de 29 GB numa máquina de 15 GB (processos
caíam com "node down"/MemoryError). Um `gc.collect()` ao fim de cada teste de página (~0,1 s) mantém o
processo estável em ~1,5 GB.
"""

import gc
import os
from pathlib import Path

import pytest

from src.cache_bases import VARIAVEL_AMBIENTE

os.environ[VARIAVEL_AMBIENTE] = "desligado"

_USA_APPTEST: dict[Path, bool] = {}


def _arquivo_de_pagina(caminho: Path) -> bool:
    if caminho not in _USA_APPTEST:
        try:
            _USA_APPTEST[caminho] = "AppTest" in caminho.read_text(encoding="utf-8")
        except OSError:
            _USA_APPTEST[caminho] = False
    return _USA_APPTEST[caminho]


@pytest.fixture(autouse=True)
def _coletar_lixo_apos_teste_de_pagina(request):
    yield
    if _arquivo_de_pagina(Path(str(request.node.path))):
        gc.collect()
