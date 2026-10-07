# Aditivos de Contratos Contínuos — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** contratos contínuos ganham uma lista de aditivos (valor, vigência, rateio, previsto/assinado) e todas as contas passam a usar, mês a mês, o valor em vigor.

**Architecture:** módulo puro novo `src/contratos_aditivos.py` (modelo do aditivo, validação, valor/rateio/vigência vigentes, série mensal por dia, custo do mês, retroativo). A janela de execução (início → vigência efetiva/véspera da suspensão) sai de `src/necessidade_empenho.py`, reaproveitada pela regra atual. Necessidade, projeção, Reforço e despesa anual passam a consumir a série; com valor constante as contas são matematicamente as de hoje, e um retrato de referência congelado prova isso.

**Tech Stack:** Python 3.13, pandas, Streamlit (`st.dialog`, `st.tabs`, fragmentos), openpyxl, reportlab, unittest/pytest (`.venv/Scripts/python.exe -m pytest`).

**Spec:** `docs/superpowers/specs/2026-10-06-aditivos-contratos-design.md`

## Global Constraints

- Contrato **sem aditivo**: necessidade, projeção, despesa anual, cobertura por PTRES e sugestão do Reforço idênticos aos atuais (Task 1 congela; toda task seguinte roda `tests/test_retrato_contratos.py`).
- Dado financeiro nunca descartado nem alterado em silêncio; nulo ≠ zero ≠ negativo (despesa mensal nula continua produzindo nulo onde produz hoje).
- `numero` do aditivo é texto (identificador), nunca número.
- Datas dentro de `aditivos` gravadas como texto `"AAAA-MM-DD"`; `despesa_mensal` e `vigencia_fim` do contrato nunca sobrescritos por aditivo.
- Tipos: `REAJUSTE`, `REPACTUACAO`, `PRORROGACAO`, `ACRESCIMO_SUPRESSAO`, `OUTRO`. Situações: `PREVISTO`, `ASSINADO`.
- Nada de `st.data_editor` dentro de `st.dialog` (quebra); grade com `st.columns` + widgets; recarga com `st.rerun(scope="fragment")`.
- Sem banco/persistência nova; Bolsas e Auxílios não muda.
- Testes: `.venv/Scripts/python.exe -m pytest -q -p no:warnings <arquivos>`; suíte completa (~11 min) ao fim das Tasks 6, 8 e 10.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; nunca incluir `README.md` inteiro com `git add` (há alteração local do usuário — seção "Atalho de inicialização"; adicionar só os próprios trechos) nem `data/manifestos/`, `Iniciar BudgetLab.bat`, `scripts/atualizar_e_iniciar.ps1`.

## Review Focus

1. **Despesa mensal negativa** (a base real já teve uma): hoje a necessidade dá 0; com `max(0, Σcusto − empenhado)` e empenhado negativo daria positivo — manter 0 sempre que `Σcusto ≤ 0` (teste na Task 6).
2. **Registro antigo** com `aditivos` ausente, `None` ou `[]`: lido como lista vazia, sem erro e sem mudar números (teste na Task 5).
3. **Duplicar exercício com aditivo `PREVISTO`**: copiado continuando `PREVISTO` (o usuário confirma depois); nunca promovido a assinado (teste na Task 5).
4. **Aditivo que começa depois da vigência original já vencida** (contrato ficou dias sem cobertura): a janela é contínua até a vigência efetiva — os dias do intervalo contam pelo valor anterior; aviso "renovação não cadastrada" não aparece porque há aditivo posterior (teste na Task 4).
5. **Valor mensal vigente zero/nulo no Reforço**: `meses_sugeridos` nulo (nunca divisão por zero nem infinito) (teste na Task 8).

---

### Task 1: Retrato de referência (antes de qualquer mudança de conta)

**Files:**
- Create: `tests/_retrato_contratos.py`
- Create: `tests/fixtures/retrato_contratos_sem_aditivo_2026-10-06.json` (gerado)
- Create: `tests/test_retrato_contratos.py`

**Interfaces:**
- Produces: `entradas_do_retrato(contratos: list[dict]) -> list[dict]` (só campos de cálculo: `id, ne_curta, contrato_numero, fornecedor, processo_empenho, status_contrato, vigencia_fim, inicio_execucao_data, inicio_execucao_mes, data_suspensao, meses_no_ano, despesa_mensal, valor_empenhado, saldo_colado_planilha, meses_empenhados, meses_liquidados, itens, unidade_cod, acao_cod, ptres, fonte_cod, natureza_despesa_cod, ugr_cod, pi_cod`; sem CNPJ) e `calcular_retrato(entradas: list[dict], exercicio: int = 2026) -> dict`.

- [ ] **Step 1:** `calcular_retrato` monta `como_dataframe(entradas)` e sintetiza a execução, deterministicamente: `valor_empenhado_execucao = valor_empenhado_planilha_total_ne = valor_empenhado_autoritativo = valor_empenhado`; `valor_liquidado_execucao = 0.5 × valor_empenhado`; `saldo_execucao = saldo_autoritativo = empenhado − liquidado`; `liquidado_via_competencia = False`; `inicio_execucao_efetivo = inicio_execucao_mes`; aplica `com_efeitos_da_suspensao`. Devolve `{"necessidade_por_ne": {ne: [necessidade, meses_restantes, meses_vigentes]}, "sem_ne": {contrato: [...]}, "projecao": {ne_ou_contrato: [p1..p12]}` (via `montar_relatorio(*necessidade_por_ne(df, None, 2026), None, 2026, 9)`), `"despesa_anual": {id: valor}`, `"reforco": {processo: [[ne, item, valor_mensal, meses_sugeridos], ...]}` (todo processo de `processos_disponiveis`, com `src.necessidade_empenho.date` substituída por subclasse cujo `today()` é `date(2026, 10, 6)`). NaN serializado como `null`.
- [ ] **Step 2:** gerar o fixture com o código ATUAL (`HEAD` = `ce6d83d`), a partir de `carregar_contratos(2026)`; gravar `{"entradas": ..., "esperado": ...}` em `tests/fixtures/retrato_contratos_sem_aditivo_2026-10-06.json`.
- [ ] **Step 3: teste** `TestRetratoSemAditivo.test_numeros_identicos_ao_retrato`: lê o fixture, recalcula, compara chave a chave com `math.isclose(rel_tol=1e-9, abs_tol=1e-6)`; `null` só casa com NaN/None.
- [ ] **Step 4:** rodar `tests/test_retrato_contratos.py` → PASS.
- [ ] **Step 5: Commit** `test: retrato de referencia dos contratos sem aditivo`.

### Task 2: Janela de execução em `necessidade_empenho`

**Files:**
- Modify: `src/necessidade_empenho.py` (`meses_vigentes_no_exercicio`, novo `janela_de_execucao`)
- Test: `tests/test_necessidade_empenho.py`

**Interfaces:**
- Produces: `janela_de_execucao(status, vigencia_fim, exercicio: int, inicio=None, data_suspensao=None) -> tuple[pd.Timestamp, pd.Timestamp] | None` — primeiro e último dia (inclusive) em execução no exercício; `None` = nenhum dia. Mesmas regras de hoje (SUSPENSO sem data/VENCIDO sem data → `None`; data manda sobre status; véspera da suspensão via `fim_ate_a_suspensao`).
- `meses_vigentes_no_exercicio` passa a derivar da janela, mantendo assinatura e a semântica exata do `None` atual: `None` só quando não há início informado depois de 1º/jan **nem** fim/véspera de suspensão **dentro** do exercício — fim em 31/12 do próprio exercício continua devolvendo `12.0`, não `None`.

- [ ] **Step 1: testes** `test_janela_de_execucao`: ATIVO sem datas → `(2026-01-01, 2026-12-31)`; início 16/07 + fim 15/11 → `(2026-07-16, 2026-11-15)`; SUSPENSO com data 01/10 → `(2026-01-01, 2026-09-30)`; SUSPENSO sem data → `None`; VENCIDO sem data → `None`; fim 2025-12-31 → `None`; início 2027-01-01 → `None`.
- [ ] **Step 2:** rodar → FAIL (`janela_de_execucao` não existe).
- [ ] **Step 3:** implementar; reescrever `meses_vigentes_no_exercicio` sobre a janela (`_posicao_em_meses`).
- [ ] **Step 4:** rodar `tests/test_necessidade_empenho.py tests/test_relatorio_necessidade_empenho.py tests/test_relatorio_reforco_empenho.py tests/test_retrato_contratos.py` → PASS.
- [ ] **Step 5: Commit** `refactor: janela de execucao do contrato no exercicio`.

### Task 3: Modelo, validação e vigentes (`src/contratos_aditivos.py`)

**Files:**
- Create: `src/contratos_aditivos.py`
- Test: `tests/test_contratos_aditivos.py`

**Interfaces:**
- Produces:
  - `TIPOS: tuple[str, ...]`, `SITUACOES = ("PREVISTO", "ASSINADO")`
  - `@dataclass(frozen=True) class Aditivo: numero: str; tipo: str; situacao: str; data_inicio: date; data_assinatura: date | None; valor_mensal: float | None; vigencia_fim: date | None; itens: list[dict] | None` + `@property previsto -> bool`
  - `aditivos_do_registro(bruto: object) -> list[Aditivo]` — `None`/NaN/`[]`/ausente → `[]`; datas ISO → `date`; ordenado por `data_inicio`.
  - `aditivo_para_registro(a: Aditivo) -> dict` — datas como `"AAAA-MM-DD"`, `numero` como `str`.
  - `validar_aditivos(aditivos: list[Aditivo]) -> list[str]` — mensagens prefixadas pelo `numero` (ou "Aditivo sem nº").
  - `valor_vigente_em(despesa_mensal: float | None, aditivos: list[Aditivo], dia: date) -> tuple[float | None, Aditivo | None]`
  - `rateio_vigente_em(itens_base: list[dict], aditivos: list[Aditivo], dia: date) -> list[dict]`
  - `vigencia_efetiva(vigencia_fim: object, aditivos: list[Aditivo]) -> tuple[pd.Timestamp, Aditivo | None]` (`NaT` quando nenhuma)

- [ ] **Step 1: testes** (`TestModelo`, `TestValidacao`, `TestVigentes`):
  - ida e volta `aditivo_para_registro` → `aditivos_do_registro` preserva tudo; `numero="002"` continua `"002"`.
  - `aditivos_do_registro(None) == aditivos_do_registro(float("nan")) == []`.
  - validação: sem `numero` → erro; sem nenhuma alteração → `"2º TA: informe ao menos novo valor, nova vigência ou novo rateio."`; `itens` somando 90 → erro; duas `data_inicio` iguais → erro citando os dois nº; `valor_mensal=-50.0` → **sem** erro.
  - `valor_vigente_em(10_000, [TA1(01/07/2025, 10_400), TA2(01/07/2026, 10_800)], date(2026, 6, 30)) == (10_400, TA1)`; em `date(2026, 7, 1)` → `(10_800, TA2)`; aditivo só de prorrogação (`valor_mensal=None`) não muda o valor.
  - `vigencia_efetiva("2025-06-30", [TA1(vig 2026-06-30), TA2(vig 2027-06-30)])` → `(2027-06-30, TA2)`; sem aditivo com vigência → a do contrato, `None`.
  - `rateio_vigente_em` com TA que muda itens para `[{1: 60}, {2: 40}]` a partir de 01/07/2026 → antes: base; depois: o novo.
- [ ] **Step 2:** rodar `tests/test_contratos_aditivos.py` → FAIL (módulo não existe).
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar → PASS.
- [ ] **Step 5: Commit** `feat: modelo e validacao de aditivos de contratos`.

### Task 4: Série mensal, custo, retroativo e previstos

**Files:**
- Modify: `src/contratos_aditivos.py`
- Test: `tests/test_contratos_aditivos.py`

**Interfaces:**
- Consumes: Task 2 `janela_de_execucao`; Task 3.
- Produces:
  - `serie_valor_mensal(despesa_mensal, aditivos, exercicio: int, numero_item: int | None = None, itens_base: list[dict] | None = None) -> list[float]` — 12 médias por dia do valor em vigor (sem corte); com `numero_item`, o valor do item (valor × percentual vigente ÷ 100). `despesa_mensal` nula → 12 NaN.
  - `custo_mensal(despesa_mensal, aditivos, exercicio: int, *, status, vigencia_fim, inicio=None, data_suspensao=None, meses_no_ano=None, numero_item=None, itens_base=None) -> list[float]` — Σ, nos dias da janela (vigência = `vigencia_efetiva`), de `valor(d) ÷ dias_do_mês`; `meses_no_ano` (N) corta quando a soma das frações a partir do primeiro dia atinge N (`None` = sem teto). Janela `None` → 12 zeros; despesa nula → 12 NaN.
  - `retroativo_por_aditivo(despesa_mensal, aditivos, exercicio: int, meses_realizados: set[int]) -> list[tuple[Aditivo, float]]` — só `ASSINADO`, com `valor_mensal` e `data_assinatura > data_inicio`: Σ nos dias de `[data_inicio, data_assinatura)` em meses de `meses_realizados` de `(valor(d) − valor_sem_esse_aditivo(d)) ÷ dias_do_mês`.
  - `meses_com_previsto(aditivos, exercicio: int) -> set[int]` — meses cujo valor ou vigência vem de aditivo `PREVISTO`.

- [ ] **Step 1: testes** (valores à mão):
  - sem aditivo, R$ 1.000: `serie_valor_mensal == [1000.0] * 12`; `custo_mensal(... status="ATIVO", vigencia_fim=NaT)` soma 12.000.
  - reajuste 1.000 → 1.310 em 16/07/2026: julho = `1000 × 15/31 + 1310 × 16/31` (= 1.160,00); agosto–dez 1.310.
  - exemplo do spec (aniversário em junho): `sum(serie_valor_mensal(10_000, [TA1, TA2], 2026)) == 127_200.0`; em 2027 janeiro = 10.800.
  - janela com vigência efetiva 2026-06-30 e sem aditivo posterior → custo julho–dez = 0.
  - **Review Focus 4**: vigência original 30/06/2026, TA2 começa 15/07/2026 com vigência 30/06/2027 → custo de julho inclui os dias 1–14 pelo valor anterior.
  - `meses_no_ano=6`, início 01/03 → custo só mar–ago.
  - SUSPENSO com data 01/10 → custo out–dez = 0.
  - retroativo: TA2 (01/07/2026, +400/mês) assinado 15/09/2026, `meses_realizados={7, 8}` → `[(TA2, 800.0)]`; sem `data_assinatura` → `[]`; `PREVISTO` → `[]`.
  - `meses_com_previsto` com TA previsto em 01/07/2026 → `{7, …, 12}`.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar (iteração por dia do exercício; frações mensais acumuladas para o teto).
- [ ] **Step 4:** rodar `tests/test_contratos_aditivos.py` → PASS.
- [ ] **Step 5: Commit** `feat: serie mensal, custo e retroativo de aditivos`.

### Task 5: Cadastro e despesa anual

**Files:**
- Modify: `src/contratos_continuos_cadastro.py` (`CAMPOS_IDENTIDADE`, `como_dataframe`, `_COLUNAS_VAZIAS`)
- Test: `tests/test_contratos_continuos_cadastro.py`

**Interfaces:**
- Consumes: Tasks 3–4.
- Produces (colunas novas de `como_dataframe`): `aditivos` (`list[Aditivo]`, `[]` quando ausente), `vigencia_fim_efetiva` (Timestamp/NaT), `valor_mensal_vigente` (float, na data de hoje limitada ao exercício: hoje se no exercício, 31/12 se passado, 01/01 se futuro), `tem_aditivo_previsto` (bool). `despesa_anual` = soma dos N primeiros meses de `serie_valor_mensal` a partir de janeiro (N = `meses_no_ano` ou 12; fração no último mês se N não inteiro). `como_dataframe(contratos, exercicio: int | None = None)` — `exercicio` necessário para a série; `None` mantém a conta antiga (`despesa_mensal × N`) para chamadores sem exercício.
- `aditivos` em `CAMPOS_IDENTIDADE` (copiado ao duplicar).

- [ ] **Step 1: testes:** ida e volta com dois aditivos (datas ISO no JSON, `numero` texto); **Review Focus 2**: registro sem chave, com `None` e com `[]` → `aditivos == []` e `despesa_anual` igual à de antes; duplicação copia `aditivos`; **Review Focus 3**: aditivo `PREVISTO` duplicado continua `PREVISTO`; `despesa_anual` do exemplo do spec = 127.200; `vigencia_fim` original intacta no registro gravado.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar; atualizar chamadas de `como_dataframe` em `app_pages/contratos_continuos.py` e em `tests/_retrato_contratos.py` para passar o exercício.
- [ ] **Step 4:** rodar `tests/test_contratos_continuos_cadastro.py tests/test_retrato_contratos.py` → PASS.
- [ ] **Step 5: Commit** `feat: aditivos no cadastro de contratos e despesa anual pela serie`.

### Task 6: Necessidade até dezembro pela série

**Files:**
- Modify: `src/relatorio_necessidade_empenho.py` (`necessidade_por_ne`, `_meses_no_ano_efetivos`)
- Test: `tests/test_relatorio_necessidade_empenho.py`

**Interfaces:**
- Consumes: `custo_mensal` (Task 4), colunas da Task 5. `necessidade_por_ne` aceita entrada sem `aditivos`/`vigencia_fim_efetiva` (chamadores antigos e fixtures): trata como `[]`/`vigencia_fim`.
- Produces: colunas novas em `por_ne`/`sem_ne`: `custo_exercicio` (float), `valor_mensal_vigente`, `inclui_previsto` (bool). Com `exercicio=None`, regra antiga intacta.

- [ ] **Step 1: testes:** exemplo do spec com empenhado 60.000 → `necessidade == 67_200.0`, `custo_exercicio == 127_200.0`; **Review Focus 1**: despesa −100, empenhado −2.000 → `necessidade == 0.0`; despesa nula → `necessidade` NaN como hoje; `meses_ja_empenhados` com série 10.400×6 + 10.800×6 e empenhado 67.200 → `6 + 4800/10800`.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar: `necessidade = max(0, Σcusto − empenhado)` se `Σcusto > 0` senão 0 (NaN preservado); `meses_ja_empenhados` percorrendo `custo` mês a mês; `meses_restantes = Σ frações em execução − meses_ja_empenhados` (≥ 0); vigência = `vigencia_fim_efetiva`.
- [ ] **Step 4:** rodar o arquivo + `tests/test_retrato_contratos.py` → PASS; depois a **suíte completa** → sem falhas.
- [ ] **Step 5: Commit** `feat: necessidade de empenho pela serie mensal dos aditivos`.

### Task 7: Projeção mensal, retroativo e previstos no relatório

**Files:**
- Modify: `src/relatorio_necessidade_empenho.py` (`projetar_necessidade_mensal`, `montar_relatorio`, `RelatorioNecessidade.valor_do_mes`)
- Test: `tests/test_relatorio_necessidade_empenho.py`

**Interfaces:**
- `projetar_necessidade_mensal(..., custos: list[float] | None = None) -> list[float]` — com `custos`, o acréscimo do mês `m` é `custos[m-1]` (frações já embutidas); sem, comportamento atual.
- `montar_relatorio` passa `custo_mensal(..., meses_no_ano=None)` (o teto continua sendo a `vida` atual) e acrescenta em `mensal`: `retroativo` (float, no primeiro mês projetado), `meses_previstos` (set[int] → texto "7,8,…" para Excel). Colunas novas de `linhas`: `custo_exercicio`, `valor_mensal_vigente`, `retroativo`.
- `valor_do_mes(indice, mes) -> tuple[float | None, bool]` inalterado; novo `tipo_do_mes(indice, mes) -> str | None` com `"Realizado"`, `"Projetado"`, `"Projetado — aditivo previsto"`.

- [ ] **Step 1: testes:** NE com TA (01/11/2026, 1.000 → 1.200, `ASSINADO`, assinatura 01/11) e referência setembro: out 500 (1.000 − saldo 500), nov 1.200, dez 1.200; com assinatura em 15/12 e `meses_realizados` vazio → `retroativo == 0.0`; caso do spec com realizado jul–ago e assinatura 15/09 → primeiro mês projetado inclui 800; aditivo `PREVISTO` em 01/11 → `tipo_do_mes(i, 11) == "Projetado — aditivo previsto"`.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar o arquivo + `tests/test_retrato_contratos.py` → PASS.
- [ ] **Step 5: Commit** `feat: projecao mensal com aditivos, retroativo e previstos`.

### Task 8: Reforço com valor e rateio vigentes

**Files:**
- Modify: `src/necessidade_empenho.py` (`necessidade_ate_mes_vigente`), `src/relatorio_reforco_empenho.py` (`_linhas_expandidas_por_item`, `_com_sugestao_por_calendario`, `_com_limite_de_vigencia`, `EspecificacaoRelatorio`)
- Test: `tests/test_relatorio_reforco_empenho.py`, `tests/test_necessidade_empenho.py`

**Interfaces:**
- `necessidade_ate_mes_vigente(..., pesos_mensais: pd.Series | None = None)` — cada elemento é uma lista de 12 pesos `valor_item(m) ÷ valor_item_vigente`; meses decorridos = Σ dos pesos do início ao mês vigente (fração do primeiro mês aplicada ao seu peso). `None` = pesos 1 (atual).
- `EspecificacaoRelatorio.coluna_aditivos: str | None = None` (`CONTRATOS_CONTINUOS`: `"aditivos"`); `coluna_vigencia_fim` de Contratos passa a `"vigencia_fim_efetiva"`.
- Linhas expandidas: `valor_mensal` = valor vigente do item (rateio vigente); `_pesos` (intermediária); teto de vigência em meses equivalentes `(Σ custo_item − empenhado_item) ÷ valor_vigente_item`; `situacao_vigencia` acrescenta `"2º TA desde 01/07/2026"` e `"(previsto)"`.

- [ ] **Step 1: testes:** contrato com TA em 01/07/2026 (3.000 → 3.300), início janeiro, empenhado 18.000, hoje 06/10/2026 → alvo = 6×3.000 + 4×3.300 = 31.200; `meses_sugeridos == (31_200 − 18_000) / 3_300` (= 4,0); rateio do TA `[60, 40]` → `valor_mensal` dos itens 1.980 e 1.320; **Review Focus 5**: valor vigente 0 → `meses_sugeridos` NaN; contratos sem aditivo e Bolsas inalterados; PDFs gerados sem erro.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar `tests/test_relatorio_reforco_empenho.py tests/test_ui_relatorio_reforco_empenho.py tests/test_necessidade_empenho.py tests/test_retrato_contratos.py` → PASS; **suíte completa** → sem falhas.
- [ ] **Step 5: Commit** `feat: sugestao do reforco com valor e rateio vigentes`.

### Task 9: Tela — abas Período/Aditivos e registro

**Files:**
- Modify: `app_pages/contratos_continuos.py` (`_dialogo_editar_contrato`, Registro de contratos, chamada de `como_dataframe`)
- Test: `tests/test_cadastros_layout_page.py`

**Interfaces:**
- Consumes: Tasks 3, 5. Estado da lista em `st.session_state[f"{k}_aditivos"]` (lista de dicts no formato de `aditivo_para_registro`), inicializado do registro, limpo em Salvar/Cancelar (como `itens_key`).
- Chaves de widget: `f"{k}_adt_{posicao}_{campo}"` (`numero`, `tipo`, `situacao`, `inicio`, `assinatura`, `valor`, `vigencia`, `altera_rateio`, `rem`), botão `f"{k}_adt_add"`.

- [ ] **Step 1: testes:** `test_janela_tem_abas_periodo_e_aditivos` (ao abrir Editar: `[t.label for t in app.tabs]` contém `"Período"` e `"Aditivos"`; botão com chave terminando em `_adt_add`; sem exceção); `test_registro_mostra_vigencia_efetiva` (linha do registro renderiza sem exceção com contrato real).
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar conforme spec §5: abas; cartões (linha 1: nº, tipo, situação, início, assinatura; linha 2: valor, vigência, "Alterar rateio dos itens" com percentuais); "Remover aditivo"/"Adicionar aditivo" com `st.rerun(scope="fragment")`; valor mensal negativo destacado no cartão (`st.caption` em vermelho "valor negativo"), sem bloquear; Salvar chama `validar_aditivos` e grava `[aditivo_para_registro(a) …]` só sem erros (erros via `st.error` com o nº); indicadores do topo "Valor mensal vigente" (TA + "previsto"), "Vigência efetiva", "Despesa anual"; registro: vigência efetiva com marca "TA"/"previsto" e "N aditivo(s)" no subtítulo; `"aditivos"` fora da lista de chaves descartadas e as colunas derivadas (`vigencia_fim_efetiva`, `valor_mensal_vigente`, `tem_aditivo_previsto`) dentro dela.
- [ ] **Step 4:** rodar `tests/test_cadastros_layout_page.py` → PASS.
- [ ] **Step 5: Commit** `feat: aba de aditivos na janela de contratos`.

### Task 10: Relatórios, avisos, card, cobertura e README

**Files:**
- Modify: `src/relatorio_necessidade_empenho.py` (`_avisos`, `_aba_detalhe_mensal`, `gerar_xlsx`, `gerar_pdf`, resumo por NE), `app_pages/contratos_continuos.py` (card/faixa, cobertura por PTRES), `README.md` (só trechos próprios)
- Test: `tests/test_relatorio_necessidade_empenho.py`, `tests/test_cadastros_layout_page.py`

**Interfaces:**
- Consumes: Tasks 6–7 (`custo_exercicio`, `valor_mensal_vigente`, `retroativo`, `tipo_do_mes`, `inclui_previsto`).
- Produces: aba Excel `"Aditivos"` com colunas exatamente `["Contrato", "NE", "Nº do termo", "Tipo", "Situação", "Início", "Assinatura", "Valor anterior", "Valor novo", "Nova vigência", "Retroativo"]`; colunas novas no Resumo por NE `"Valor mensal vigente"`, `"Custo do exercício"`, `"Retroativo"`; avisos que começam com `"Renovação não cadastrada"`, `"Aditivos previstos (valores estimados)"`, `"Aditivo com valor mensal negativo"`.

- [ ] **Step 1: testes:** Excel tem a aba e as colunas acima, com uma linha por aditivo; "Detalhe mensal" traz o tipo `"Projetado — aditivo previsto"`; os três avisos aparecem nos casos certos e não aparecem em contrato sem aditivo (vigência efetiva após 31/12 → sem "Renovação não cadastrada"); PDF gerado (`startswith(b"%PDF")`) com aditivo previsto e retroativo; página: faixa do topo mostra `"estimados em aditivos previstos"` só quando há previsto.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar (PDF: marca e legenda "valor estimado (aditivo previsto)", nota "inclui R$ X de retroativo (nº TA)"; cobertura: "inclui aditivos previstos"); README: parágrafo "Aditivos" na seção de Contratos Contínuos.
- [ ] **Step 4:** rodar os dois arquivos + `tests/test_retrato_contratos.py` → PASS; **suíte completa** → sem falhas.
- [ ] **Step 5: Commit** `feat: aditivos nos relatorios, avisos e cobertura` (README só com os próprios trechos).
