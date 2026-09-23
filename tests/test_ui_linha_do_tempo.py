"""Testes de `src/ui_linha_do_tempo.py` — somatórios ao final da linha do tempo mensal."""

import pandas as pd

from src.ui_linha_do_tempo import totais_linha_do_tempo


def test_totais_somam_todos_os_meses():
    tempo = pd.DataFrame(
        {
            "ano_mes": [202601, 202602, 202603],
            "empenhada": [1000.0, 0.0, 500.5],
            "liquidada": [200.0, 300.0, 0.0],
            "paga": [100.0, 0.0, 50.25],
        }
    )
    assert totais_linha_do_tempo(tempo) == {"empenhada": 1500.5, "liquidada": 500.0, "paga": 150.25}


def test_totais_preservam_valor_negativo():
    tempo = pd.DataFrame(
        {"ano_mes": [202601, 202602], "empenhada": [100.0, -40.0], "liquidada": [0.0, 0.0], "paga": [0.0, 0.0]}
    )
    assert totais_linha_do_tempo(tempo)["empenhada"] == 60.0
