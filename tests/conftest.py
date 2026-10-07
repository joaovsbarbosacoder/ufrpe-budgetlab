"""Configuração comum da suíte.

Os testes de página executam o `app.py`, que liga o cache das bases (`src/cache_bases.py`) na pasta
real `data/processed/cache_bases/`. Com esta variável, o `ativar_no_app()` não liga nada: a suíte lê
sempre a planilha e não grava nem reaproveita cópias fora dos testes do próprio cache (que ligam com
`ativar(diretorio)` numa pasta temporária). Definida no carregamento, vale também para os processos
do pytest-xdist.
"""

import os

from src.cache_bases import VARIAVEL_AMBIENTE

os.environ[VARIAVEL_AMBIENTE] = "desligado"
