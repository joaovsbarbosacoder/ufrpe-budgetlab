"""
Motor de leitura de Excel usado pelos leitores de base que passam por `pandas.read_excel`.

Pedido de 07/10/2026 (desempenho): o `python-calamine` (leitor em Rust, suportado pelo pandas como
`engine="calamine"`) lê as planilhas do projeto de 4 a 6 vezes mais rápido que o padrão (openpyxl) —
medido com a Execução Mensal (2,37 s → 0,62 s) e a Liquidação por Competência (1,41 s → 0,23 s).

Sem o pacote instalado, cai no motor padrão do pandas (`engine=None`: openpyxl para .xlsx/.xlsm,
xlrd para .xls) — o sistema continua funcionando igual, só mais devagar. A variável de ambiente
`BUDGETLAB_MOTOR_EXCEL=padrao` força o motor padrão (usada no teste de paridade entre os dois).

A paridade (mesmo DataFrame, mesmos tipos, nulos e textos, zeros à esquerda preservados) é verificada
para cada leitor sobre as fixtures em `tests/test_leitura_excel.py`. Leitores que usam recursos
próprios do openpyxl (célula a célula, `data_only`, estilos — Dotação Anual, Emendas, Captação)
continuam no openpyxl e não passam por aqui.
"""

from __future__ import annotations

import importlib.util
import os

MOTOR_RAPIDO = "calamine"
VARIAVEL_AMBIENTE = "BUDGETLAB_MOTOR_EXCEL"


def motor_excel() -> str | None:
    """`"calamine"` quando o pacote está instalado e não foi forçado o padrão; senão `None` (motor
    padrão do pandas). Avaliado a cada chamada, para a variável de ambiente valer na hora."""

    if os.environ.get(VARIAVEL_AMBIENTE, "").strip().lower() == "padrao":
        return None
    return MOTOR_RAPIDO if importlib.util.find_spec("python_calamine") is not None else None
