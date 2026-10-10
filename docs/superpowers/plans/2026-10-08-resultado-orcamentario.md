# Resultado Orçamentário — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar a página "Resultado Orçamentário", que confronta a Dotação Atualizada das células escolhidas com o empenhado nessas células e com a necessidade de empenho (Contratos Contínuos, Bolsas e Auxílios e despesas manuais).

**Architecture:** Regra pura em `src/resultado_orcamentario.py` (DataFrames entram, dataclass sai). Persistência JSON em `src/resultado_orcamentario_cadastro.py`. A montagem das tabelas de Contratos e Bolsas que hoje vive nas páginas vai para `src/resultado_orcamentario_fontes.py`, e as duas páginas passam a chamá-la. A interface fica em `app_pages/resultado_orcamentario.py`.

**Tech Stack:** Python, pandas, Streamlit (`st.data_editor`, `st.expander`, `st.cache_data`), pytest (`-n auto`, `--testmon`), `streamlit.testing.v1.AppTest`.

**Spec:** `docs/superpowers/specs/2026-10-08-resultado-orcamentario-design.md` (e o protótipo `docs/superpowers/specs/2026-10-08-resultado-orcamentario-mockup.html`)

## Global Constraints

- Códigos orçamentários são texto (`string`), com zeros à esquerda preservados. Nunca converter para número.
- Nulo ≠ zero ≠ negativo em todas as somas. Use `sum(min_count=1)` onde a ausência importa e marque o resultado como `incompleto`, em vez de preencher com 0.
- Nenhuma conta existente muda: Necessidade, Projeção pela Execução, Limite de Empenho e os testes atuais das páginas de Contratos e Bolsas passam **sem alteração**.
- Persistência só em `data/resultado_orcamentario/<exercício>/`, git-ignorada, com gravação atômica (temporário + `Path.replace`).
- Necessidade de Contratos e Bolsas = `necessidade_execucao` do `RelatorioProjecaoExecucao`, **sem antecessor**.
- Contrato ou bolsa sem NE fica fora da conta e aparece só em aviso.
- Ordem de classificação do empenhado: Contratos → Bolsas → Outros. Cada NE é contada uma vez.
- Tolerância da conferência de fechamento: R$ 0,01.
- Comentários e docstrings em português, no estilo do repositório (decisão + data + motivo).
- Testes: `python -m pytest tests --testmon -n auto` nas rodadas intermediárias e `python -m pytest tests -n auto` ao final.

## Review Focus

1. **Liquidação por Competência ausente ou ilegível:** a necessidade de Contratos e Bolsas fica `None` (indisponível), o cartão mostra "—" e o resultado aparece como incompleto, nunca como zero. O teste fica na Task 4 (`test_necessidade_indisponivel_deixa_resultado_incompleto`).
2. **Nenhuma célula selecionada:** o resultado é `None`, com a mensagem "Nenhuma célula selecionada", e não um "déficit" igual à necessidade. Teste na Task 4 (`test_sem_selecao_resultado_none`).
3. **NE da Execução com Fonte Detalhada nula** (extrações antigas): ela não casa com nenhuma célula e entra no aviso "empenho sem fonte detalhada", com valor, sem sumir silenciosamente. Teste na Task 4 (`test_empenho_sem_fonte_detalhada_vira_aviso`).
4. **Exercício sem contratos ou bolsas cadastrados:** a necessidade é 0,0 (lista vazia legítima), diferente do `None` de "indisponível". Teste na Task 4 (`test_cadastro_vazio_necessidade_zero`).
5. **JSON de seleção com célula que sumiu da Dotação depois de uma reimportação:** a célula continua no arquivo, gera aviso e não quebra a tabela de seleção. Teste na Task 4 (`test_celula_selecionada_ausente`) e na Task 2 (ida e volta preserva).

---

### Task 1: Fonte Detalhada nas dimensões do bloco de empenho

**Files:**
- Modify: `src/tesouro_execucao_mensal.py` (`_DIMENSOES_EXTRA_BLOCO`, ~linha 343)
- Test: `tests/test_tesouro_execucao_mensal.py`

**Interfaces:**
- Produces: `valor_empenhado_por_bloco(df)` passa a devolver também as colunas `fonte_recursos_detalhada_cod` e `fonte_recursos_detalhada_desc`.

- [ ] **Step 1: Write the failing test** `test_valor_empenhado_por_bloco_inclui_fonte_detalhada`. Monte um DataFrame mínimo com 2 linhas `tipo_linha == "empenho"` da mesma NE e bloco, com `fonte_recursos_detalhada_cod = "1000000000"`. Asserts: a coluna existe; o valor é `"1000000000"` (string, zeros preservados); `len(resultado) == 1`; `empenhada` é igual ao valor da primeira linha.
- [ ] **Step 2:** `python -m pytest tests/test_tesouro_execucao_mensal.py -k fonte_detalhada -v`. Esperado: FAIL com KeyError.
- [ ] **Step 3:** Acrescente `"fonte_recursos_detalhada_cod"` e `"fonte_recursos_detalhada_desc"` a `_DIMENSOES_EXTRA_BLOCO`. A fonte é constante por NE, então `"first"` não mistura dado. Registre isso no comentário com a data.
- [ ] **Step 4:** `python -m pytest tests --testmon -n auto`. Esperado: tudo PASS. O Limite de Empenho e a Consulta de Empenhos continuam iguais.
- [ ] **Step 5: Commit** `feat: fonte detalhada nas dimensoes do bloco de empenho`

---

### Task 2: Persistência da seleção e das despesas manuais

**Files:**
- Create: `src/resultado_orcamentario_cadastro.py`
- Create: `data/resultado_orcamentario/.gitkeep`
- Modify: `.gitignore` (bloco `data/resultado_orcamentario/*` + `!data/resultado_orcamentario/.gitkeep`, no padrão de `data/demandas/`)
- Test: `tests/test_resultado_orcamentario_cadastro.py`

**Interfaces:**
- Produces:
  - `CHAVE_CELULA: tuple[str, ...] = ("iduso_codigo", "resultado_primario_codigo", "acao_codigo", "ptres_codigo", "plano_orcamentario_codigo", "grupo_despesa_codigo", "fonte_recursos_detalhada_codigo")`
  - `CelulaChave = tuple[str | None, ...]` (7 posições, na ordem de `CHAVE_CELULA`)
  - `DIRETORIO_PADRAO = Path("data/resultado_orcamentario")`
  - `class ArquivoCorrompido(ValueError)`
  - `@dataclass(frozen=True) class DespesaManual: id: str; descricao: str; valor: float; observacao: str | None; celula: CelulaChave | None; criado_em: str; atualizado_em: str`
  - `carregar_selecao(exercicio: int, diretorio: Path = DIRETORIO_PADRAO) -> list[CelulaChave]` (arquivo ausente → `[]`; JSON inválido → `ArquivoCorrompido`)
  - `salvar_selecao(exercicio: int, celulas: list[CelulaChave], diretorio: Path = DIRETORIO_PADRAO) -> None`
  - `carregar_despesas(exercicio: int, diretorio: Path = DIRETORIO_PADRAO) -> list[DespesaManual]`
  - `validar_despesa(descricao: str, valor: float | None) -> list[str]` (mensagens de erro; vazio = válido)
  - `incluir_despesa(exercicio, descricao, valor, observacao, celula, diretorio=DIRETORIO_PADRAO) -> DespesaManual`
  - `atualizar_despesa(exercicio, id_despesa, descricao, valor, observacao, celula, diretorio=DIRETORIO_PADRAO) -> DespesaManual`
  - `excluir_despesa(exercicio, id_despesa, diretorio=DIRETORIO_PADRAO) -> None`
- Arquivos: `<diretorio>/<exercicio>/celulas.json` = `{"celulas": [[7 códigos]], "atualizado_em": ISO}`; `<diretorio>/<exercicio>/despesas_manuais.json` = `{"despesas": [ {…campos de DespesaManual, celula como lista ou null} ]}`.

- [ ] **Step 1: Write the failing tests** (todos com `tmp_path` como diretório):
  - `test_selecao_ida_e_volta_preserva_zeros`: salvar `[("0","2","20RK","230987","0000","3","1000000000")]` e recarregar dá a mesma tupla, com `"0000"` intacto.
  - `test_selecao_arquivo_ausente_lista_vazia` → `[]`.
  - `test_selecao_arquivo_corrompido_levanta`: escreva `"{"` em `celulas.json` → `pytest.raises(ArquivoCorrompido)`.
  - `test_selecao_mantem_celula_desconhecida`: uma tupla qualquer (inexistente em base) sobrevive à ida e volta.
  - `test_gravacao_atomica_nao_deixa_temporario`: depois de `salvar_selecao`, a pasta do exercício contém só `celulas.json`.
  - `test_validar_despesa`: `("", 10.0)` → erro de descrição; `("X", None)` → erro de valor; `("X", 0.0)` e `("X", -5.0)` → erro "maior que zero"; `("X", 1.0)` → `[]`.
  - `test_incluir_atualizar_excluir_despesa`: incluir 2, atualizar o valor da 1ª para 620000.0, excluir a 2ª; recarregar dá 1 despesa com valor 620000.0 e `atualizado_em >= criado_em`.
  - `test_incluir_despesa_invalida_levanta_value_error`.
  - `test_exercicios_isolados`: a seleção de 2026 não aparece em 2025.
- [ ] **Step 2:** `python -m pytest tests/test_resultado_orcamentario_cadastro.py -v`. Esperado: FAIL (módulo inexistente).
- [ ] **Step 3:** Implemente seguindo o padrão de gravação atômica de `src/limite_empenho_preferencias.py`. A docstring do módulo deve registrar a aprovação da persistência (08/10/2026, exigência do AGENTS.md). `incluir_despesa`/`atualizar_despesa` chamam `validar_despesa` e levantam `ValueError("; ".join(erros))`.
- [ ] **Step 4:** `python -m pytest tests/test_resultado_orcamentario_cadastro.py -v`. Esperado: PASS.
- [ ] **Step 5: Commit** `feat: persistencia da selecao de celulas e despesas manuais do resultado orcamentario`

---

### Task 3: Montagem compartilhada de Contratos e Bolsas (extraída das páginas)

**Files:**
- Create: `src/resultado_orcamentario_fontes.py`
- Modify: `app_pages/contratos_continuos.py` (bloco das colunas derivadas, ~linhas 1726–1747, e `_render_relatorio_projecao_execucao`, ~1343–1374)
- Modify: `app_pages/bolsas_auxilios.py` (bloco das colunas derivadas, ~linhas 1043–1059, e `_render_relatorio_projecao_execucao`, ~824–831)
- Test: `tests/test_resultado_orcamentario_fontes.py`

**Interfaces:**
- Consumes: funções já existentes, sem mudança: `contratos_continuos.com_saldo_execucao`, `com_efeitos_da_suspensao`; `bolsas_auxilios.com_saldo_execucao`; `relatorio_necessidade_empenho.necessidade_por_ne`; `projecao_execucao_bolsas.entrada_relatorio`; `relatorio_projecao_execucao.montar_relatorio`, `BOLSAS_AUXILIOS`.
- Produces:
  - `tabela_contratos(cadastro: pd.DataFrame, por_ne_execucao: pd.DataFrame, indice_liquidado_competencia: pd.Series | None, sugestao_inicio_por_ne: pd.Series) -> pd.DataFrame`: exatamente o que a página faz hoje, ou seja, `com_saldo_execucao` → `valor_empenhado_autoritativo`, `saldo_autoritativo`, `inicio_execucao_efetivo` → `com_efeitos_da_suspensao`. **Não** inclui `com_meses_pagos`, que é só de exibição e continua na página, aplicado antes.
  - `tabela_bolsas(cadastro: pd.DataFrame, por_ne_execucao: pd.DataFrame, sugestao_inicio_por_ne: pd.Series) -> pd.DataFrame`: o mesmo para Bolsas (`valor_empenhado_tg` como reserva).
  - `projecao_contratos(tabela: pd.DataFrame, competencia: pd.DataFrame, exercicio: int, mes_referencia: int, antecessores: dict[str, str] | None = None) -> tuple[RelatorioProjecaoExecucao, pd.DataFrame]`: devolve `(relatorio, sem_ne)`, com `sem_ne` vindo de `necessidade_por_ne(tabela, None, exercicio)`.
  - `projecao_bolsas(tabela: pd.DataFrame, competencia: pd.DataFrame, exercicio: int, mes_referencia: int) -> tuple[RelatorioProjecaoExecucao, pd.DataFrame]`.

- [ ] **Step 1: Write the failing tests** com as fixtures congeladas (`tests/fixtures/contratos_continuos_2026-08-13.xlsm`, `bolsas_auxilios_2026-08-13.xlsx`, `execucao_mensal_2026-09-22.xlsx`, `liquidacao_competencia_2026-09-11.xlsx`), no mesmo carregamento que `tests/test_relatorio_projecao_execucao.py` e `tests/test_projecao_execucao_bolsas.py` já usam:
  - `test_projecao_contratos_igual_ao_caminho_da_pagina`: monte a tabela pelo caminho antigo (as chamadas copiadas literalmente da página) e por `tabela_contratos` + `projecao_contratos`. Asserts: `pd.testing.assert_frame_equal` nas `linhas` dos dois relatórios e `total_necessidade_execucao` igual.
  - `test_projecao_bolsas_igual_ao_caminho_da_pagina`: o mesmo para Bolsas.
  - `test_sem_ne_devolvido`: `len(sem_ne) == relatorio.qtd_sem_ne`.
- [ ] **Step 2:** `python -m pytest tests/test_resultado_orcamentario_fontes.py -v`. Esperado: FAIL (módulo inexistente).
- [ ] **Step 3:** Mova as linhas das páginas para as quatro funções sem alterar a lógica. As páginas passam a chamá-las. Os comentários de decisão que estavam na página vão junto para o `src/`.
- [ ] **Step 4:** `python -m pytest tests/test_resultado_orcamentario_fontes.py tests/test_relatorio_projecao_execucao.py tests/test_projecao_execucao_bolsas.py tests/test_contratos_continuos.py tests/test_bolsas_auxilios.py -n auto`. Depois rode `python -m pytest tests -k "page or contratos or bolsas" -n auto`. Esperado: tudo PASS, sem tocar em nenhum teste existente.
- [ ] **Step 5: Commit** `refactor: montagem de contratos e bolsas para a projecao em src, compartilhada`

---

### Task 4: Regra do Resultado Orçamentário

**Files:**
- Create: `src/resultado_orcamentario.py`
- Test: `tests/test_resultado_orcamentario.py`

**Interfaces:**
- Consumes: `CHAVE_CELULA`, `CelulaChave`, `DespesaManual` (Task 2); `valor_empenhado_por_bloco` com fonte detalhada (Task 1); `execucao_ne_utils.ne_curta`; `dotacao_anual_analysis.build_dotacao_anual_subdivision_analysis`, `KNOWN_ITEM_INDICATORS`.
- Produces:
  - `ORIGEM_CONTRATOS = "Contratos Contínuos"`, `ORIGEM_BOLSAS = "Bolsas e Auxílios"`, `ORIGEM_OUTROS = "Outros empenhos"`
  - `celulas_da_dotacao(dotacao: pd.DataFrame, exercicio: int) -> pd.DataFrame`: uma linha por célula do exercício (subdivisões com algum indicador, mesmo filtro de `limite_empenho._dotacao_atualizada_no_escopo`, **sem** o filtro discricionário). Colunas: `SUBDIVISION_DIMENSION_COLUMNS` + `dotacao_atualizada` (Float64) + `chave` (tupla `CelulaChave`).
  - `empenhado_por_ne_e_celula(execucao_mensal: pd.DataFrame, exercicio: int) -> pd.DataFrame`: colunas `ne_curta`, `chave`, `empenhada` (soma `min_count=1`), `natureza_detalhada_desc`, `ne_favorecido` (primeira não nula).
  - `@dataclass class ResultadoOrcamentario`: `dotacao: float | None`; `empenhado: dict[str, float]` (chaves = as 3 origens); `empenhado_total: float`; `diferenca_conferencia: float`; `necessidade: dict[str, float | None]` (chaves `ORIGEM_CONTRATOS`, `ORIGEM_BOLSAS`, `"Outras despesas previstas"`); `resultado: float | None`; `incompleto: bool`; `empenhado_por_ne: pd.DataFrame` (colunas `ne_curta`, `origem`, `empenhada`, `contrato_numero`, `fornecedor`, `programa_bolsa`, `natureza_detalhada_desc`, `ne_favorecido`, `celula_selecionada: bool`); `avisos: list[str]`.
  - `calcular_resultado(celulas: pd.DataFrame, empenhado: pd.DataFrame, selecao: list[CelulaChave], cadastro_contratos: pd.DataFrame, cadastro_bolsas: pd.DataFrame, necessidade_contratos: pd.DataFrame | None, necessidade_bolsas: pd.DataFrame | None, sem_ne_contratos: pd.DataFrame, sem_ne_bolsas: pd.DataFrame, despesas_manuais: list[DespesaManual]) -> ResultadoOrcamentario`
    - `cadastro_*`: precisam de `ne_curta`, mais `contrato_numero`/`fornecedor` ou `programa_bolsa`.
    - `necessidade_*`: `linhas` do relatório (`ne_curta`, `necessidade_execucao`); `None` = indisponível.
    - `resultado = dotacao − empenhado_total − Σ necessidade`. É `None` se `selecao` estiver vazia, se `dotacao` for `None` ou se alguma necessidade for `None`. Nesses casos, `incompleto=True`, exceto com seleção vazia, que gera o aviso próprio.

- [ ] **Step 1: Write the failing tests** com DataFrames montados no próprio teste: 3 células (A e B selecionadas, C não), contratos com NEs `N1` (em A) e `N9` (em C), bolsa `N2` (em B) e NE avulsa `N3` (em A).
  - `test_resultado_conta_a_mao`: dotação A=1000, B=500, C=300; empenhado N1=400, N2=200, N3=100, N9=50; necessidade contratos N1=150, N9=80; bolsas N2=60; manual 40. Asserts: `dotacao == 1500`; `empenhado == {Contratos: 400, Bolsas: 200, Outros: 100}`; `empenhado_total == 700`; necessidade total `330` (N9 entra); `resultado == 1500 − 700 − 330 == 470`; `incompleto is False`.
  - `test_ne_em_celula_nao_selecionada_fora_do_empenhado_dentro_da_necessidade`: N9 não está em `empenhado_por_ne` com `celula_selecionada=True`, e os 80 estão na necessidade.
  - `test_ne_nos_dois_cadastros_vai_para_contratos`: N1 também na bolsa → origem Contratos e um aviso contendo `"N1"` e `"conferir"`.
  - `test_ne_compartilhada_contada_uma_vez`: N1 em 2 contratos → empenhado de Contratos continua 400, e aviso de NE compartilhada.
  - `test_conferencia_fecha`: `abs(diferenca_conferencia) < 0.01`.
  - `test_sem_ne_fora_da_conta_com_aviso`: `sem_ne_contratos` com 1 linha (necessidade 999) → resultado igual ao do primeiro teste, e o aviso cita "1 contrato" e "999".
  - `test_celula_com_dotacao_nula_incompleto`: dotação de B = `pd.NA` → `incompleto is True`, `resultado is None`, aviso "sem Dotação Atualizada".
  - `test_necessidade_indisponivel_deixa_resultado_incompleto`: `necessidade_contratos=None` → `necessidade[Contratos] is None`, `resultado is None`, `incompleto is True`.
  - `test_cadastro_vazio_necessidade_zero`: necessidade de bolsas com DataFrame vazio → `0.0`, `incompleto is False`.
  - `test_sem_selecao_resultado_none`: `selecao=[]` → `resultado is None`, aviso "Nenhuma célula selecionada".
  - `test_celula_selecionada_ausente`: seleção com uma tupla que não está em `celulas` → aviso "ausente da base", e o resultado das demais é calculado.
  - `test_empenho_sem_fonte_detalhada_vira_aviso`: linha de empenho com fonte `None` na chave → não entra em célula e gera aviso com o valor.
  - `test_zeros_a_esquerda_casam`: PO `"0000"` e fonte `"1000000000"` na Dotação e na Execução casam como texto.
  - `test_celulas_da_dotacao_e_empenhado_por_ne`: unitários das duas funções de entrada (filtro de exercício, tipo `string` dos códigos, `chave` montada na ordem de `CHAVE_CELULA`).
- [ ] **Step 2:** `python -m pytest tests/test_resultado_orcamentario.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente. A chave da Execução é montada de `iduso_cod`, `resultado_primario_cod`, `acao_cod`, `ptres`, `po_cod`, `gnd_cod`, `fonte_recursos_detalhada_cod`, na mesma ordem de `CHAVE_CELULA`. O módulo não importa Streamlit nem lê arquivo.
- [ ] **Step 4:** `python -m pytest tests/test_resultado_orcamentario.py -v`. Esperado: PASS.
- [ ] **Step 5: Commit** `feat: regra do resultado orcamentario (bolsao de celulas)`

---

### Task 5: Página, menu e teste de página

**Files:**
- Create: `app_pages/resultado_orcamentario.py`
- Modify: `app.py` (novo `st.Page("app_pages/resultado_orcamentario.py", title="Resultado Orçamentário", icon=...)` logo depois de "Limite de Empenho")
- Test: `tests/test_resultado_orcamentario_page.py`

**Interfaces:**
- Consumes: Tasks 2, 3 e 4; `importacao_dotacao.carregar_atual`/`Manifesto`; `importacao_execucao_mensal.carregar_atual`/`Manifesto`; `relatorio_necessidade_empenho.mes_referencia_do_exercicio`; leitura e cache da Liquidação por Competência igual a `app_pages/bolsas_auxilios.py::_cached_liquidacao_competencia_por_mes`; `CAMINHO_LIQUIDACAO_COMPETENCIA = Path("data/raw") / "Liquidação por Competência.xlsx"`.

Layout = protótipo, nesta ordem: exercício e datas das extrações; 4 cartões (`cartao_resumo` de `src/ui_cadastro.py` ou o padrão das páginas vizinhas); "Composição" em `st.columns(2)` com `st.expander` por origem; "Células" em `st.data_editor` com coluna de seleção + botão "Salvar seleção"; "Outras despesas previstas" com lista, `st.form` de inclusão e diálogos de editar/excluir; "Avisos". A nota sobre o antecessor fica sob a Necessidade de Contratos. Sem Dotação ou sem Execução Mensal: `st.info` + `st.stop()`, como nas outras páginas. `ArquivoCorrompido`: `st.error` e o botão de salvar fica desabilitado.

- [ ] **Step 1: Write the failing tests** (`AppTest.from_file(..., default_timeout=TEMPO_LIMITE_APPTEST)`, `aquecer_pagina` no setup, diretório de persistência apontado para `tmp_path` via monkeypatch de `DIRETORIO_PADRAO`):
  - `test_pagina_abre_sem_excecao`: `not at.exception`; há título "Resultado Orçamentário".
  - `test_sem_selecao_mostra_mensagem`: aparece o texto "Nenhuma célula selecionada".
  - `test_salvar_selecao_grava_arquivo`: marque a 1ª linha do `data_editor`, clique em "Salvar seleção" → `celulas.json` existe com 1 célula.
  - `test_incluir_despesa_manual`: preencha o formulário (descrição "Teste", valor 100) e envie → `despesas_manuais.json` tem 1 despesa e a linha aparece na tabela.
  - `test_menu_tem_pagina`: `app.py` registra o título "Resultado Orçamentário" (mesmo padrão de `tests/test_home_page.py`).
- [ ] **Step 2:** `python -m pytest tests/test_resultado_orcamentario_page.py -v`. Esperado: FAIL.
- [ ] **Step 3:** Implemente a página e a entrada no menu. Faça cache das leituras pesadas (`st.cache_data` com a chave caminho+mtime, no padrão das páginas vizinhas) e chame `gc.collect()` ao final, como nas páginas de base grande (commit `2a02dcb`).
- [ ] **Step 4:** `python -m pytest tests/test_resultado_orcamentario_page.py -v`. Esperado: PASS. Depois, abra o app (`streamlit run app.py`) e confira visualmente contra o protótipo.
- [ ] **Step 5: Commit** `feat: pagina Resultado Orcamentario`

---

### Task 6: Documentação e suíte completa

**Files:**
- Modify: `README.md` (nova seção "### Resultado Orçamentário", depois de "Limite de Empenho" ou de "Painel por Ação de Governo", com fórmula, bolsão, origens do empenhado, sem NE fora, despesas manuais, persistência e a nota do antecessor)

- [ ] **Step 1:** Escreva a seção do README.
- [ ] **Step 2:** `python -m pytest tests -n auto`. Esperado: suíte inteira PASS.
- [ ] **Step 3: Commit** `docs: Resultado Orcamentario no README`
