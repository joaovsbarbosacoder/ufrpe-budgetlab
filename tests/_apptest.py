"""Tempo limite único para os testes de página com `streamlit.testing.v1.AppTest`.

Todo `AppTest.from_file`/`from_function` dos testes recebe `default_timeout=TEMPO_LIMITE_APPTEST`,
e nenhum `.run()` passa `timeout` próprio: o limite vale para a primeira execução, para cada
interação (`button.click().run()`) e para a troca de página, e é ajustado só aqui.

Por que 60 s: o padrão do Streamlit (3 s) estourava neste ambiente — projeto numa pasta
sincronizada com o Google Drive, onde a primeira execução de `app.py` (imports + leitura de
dados) passa de 3 s — e fazia a suíte completa sempre terminar com erros de "timed out" que não
eram falha de lógica (ex.: `test_home_page`, `test_consulta_empenhos_page`, `test_glossario`).
O limite é finito de propósito: uma página que realmente trave ou fique muito lenta ainda falha.
"""

TEMPO_LIMITE_APPTEST = 60

#: Limite só do AQUECIMENTO de uma página (`aquecer_pagina`), nunca das interações do teste.
TEMPO_LIMITE_AQUECIMENTO_APPTEST = 300


def aquecer_pagina(caminho_da_pagina: str) -> None:
    """Executa a página uma vez, com `TEMPO_LIMITE_AQUECIMENTO_APPTEST`, para preencher os
    `st.cache_data` do processo antes do teste cronometrado.

    Por que existe: a primeira execução de uma página que lê as planilhas reais (Execução Mensal,
    Pagamentos, Liquidação por Competência) leva ~55 s neste ambiente — leitura de `.xlsx` numa
    pasta sincronizada com o Google Drive — e a segunda, ~1 s (cache em memória, compartilhado
    entre os `AppTest` do mesmo processo). Com `TEMPO_LIMITE_APPTEST` em 60 s, o primeiro teste a
    tocar a página passava ou estourava por poucos segundos, sem haver regressão. O aquecimento
    absorve esse custo único com um limite maior; o teste em si continua sob
    `TEMPO_LIMITE_APPTEST`, então uma página que fique lenta de verdade (renderização, não carga de
    dado) ainda falha."""

    from streamlit.testing.v1 import AppTest

    AppTest.from_file(str(caminho_da_pagina), default_timeout=TEMPO_LIMITE_AQUECIMENTO_APPTEST).run()
