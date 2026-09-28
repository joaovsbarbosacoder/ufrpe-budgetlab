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
