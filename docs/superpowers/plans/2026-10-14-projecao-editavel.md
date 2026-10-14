# Projeção pela execução editável — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** permitir gravar o esperado de um mês por NE na Projeção pela execução de Contratos Contínuos, fazer relatório, Necessidade e Resultado Orçamentário usarem esse valor, e refazer pela metodologia por NE ou geral.

**Architecture:** log de eventos em JSON (um arquivo por evento) reconstruído em `{NE: {mês: esperado}}`; `projetar_meses` ganha o parâmetro `ajustes` que substitui o esperado (custo × fator, com teto) e `projecao_contratos` carrega e repassa; a tela é HTML puro (matriz) mais um formulário por NE.

**Tech Stack:** Python 3.13, pandas, Streamlit, reportlab, openpyxl, pytest (`python -m pytest <arquivos> -q -p no:cacheprovider`).

**Spec:** `docs/superpowers/specs/2026-10-14-projecao-editavel-design.md` (maquete: `…-mockup.html`). Trabalho no worktree `.claude/worktrees/projecao-editavel`, branch `feat/projecao-editavel`.

## Global Constraints

- Só Contratos Contínuos; Bolsas e Auxílios, Necessidade pelo valor contratual e a coluna "valor cheio" não mudam.
- Valor digitado = **esperado total do mês**; projetado = `max(0, esperado − liquidado do mês)`; o saldo do empenho nunca entra na grade.
- Meses editáveis: do primeiro mês em aberto (`ultimo_mes_fechado(mes_referencia) + 1`) a dezembro, inclusive os que a metodologia deixa vazios. Exercício encerrado (`mes_referencia >= 12`): nada edita nem projeta.
- Ajuste em mês já fechado: ignorado na conta, fica no log, aparece em aviso ("ajuste superado").
- Zero (0,00) é ajuste válido; campo vazio = sem ajuste; negativo e não numérico são recusados.
- `ne_curta` é texto (ex.: `2026NE000551`), nunca número. Log nunca é apagado nem sobrescrito; arquivo ilegível levanta `ErroAjuste`.
- Toda linha, seletor e aviso mostra o **número do contrato e o fornecedor** (título do contrato).
- Marca de ajuste: `✎` na tela; `†` no Excel e no PDF (Helvetica não tem `✎`).
- Pasta de dados: `data/projecao_execucao/<exercício>/`, fora do git: acrescentar `data/projecao_execucao/*` e `!data/projecao_execucao/.gitkeep` ao `.gitignore` (padrão das demais pastas de `data/`) e criar `data/projecao_execucao/.gitkeep`.
- Reiniciar o Streamlit para ver código novo (`fileWatcherType = "none"`).

## Review Focus

- Ajuste digitado num mês que uma nova extração fecha: tem de ser ignorado e avisado, não somado nem apagado (Task 2).
- Ajuste de NE que não existe mais no relatório ou contrato sem NE: ignorado sem erro (Task 2).
- Arquivo de evento corrompido: a página mostra o erro, usa a metodologia e não grava por cima (Tasks 1 e 5).
- Valor digitado em formatos `1.234,56`, `1234,56`, `1234.56`, vazio, `abc`, negativo (Task 4).
- Ajuste igual à metodologia ou "Gravar" sem mudança: não gera evento; voltar um mês à metodologia remove o ajuste (Tasks 1 e 4).

---

### Task 1: Persistência por eventos (`src/projecao_ajustes.py`)

**Files:**
- Create: `src/projecao_ajustes.py`, `data/projecao_execucao/.gitkeep`
- Modify: `.gitignore`
- Test: `tests/test_projecao_ajustes.py`

**Interfaces:**
- Produces:
  - `class ErroAjuste(ValueError)`
  - `DIRETORIO_AJUSTES = Path("data/projecao_execucao")`, `VERSAO_SCHEMA = 1`
  - `registrar_ajustes(*, exercicio: int, ne_curta: str, valores: dict[int, float | None], extracao: str, diretorio: Path | None = None) -> dict` (grava 1 evento "ajustar")
  - `refazer_ne(*, exercicio: int, ne_curta: str, extracao: str, diretorio: Path | None = None) -> dict`
  - `refazer_tudo(*, exercicio: int, extracao: str, diretorio: Path | None = None) -> dict`
  - `carregar_eventos(exercicio: int, diretorio: Path | None = None) -> list[dict]` (ordenados por `registrado_em`, `id`)
  - `reconstruir(eventos: list[dict]) -> dict[str, dict[int, float]]`
  - `ajustes_vigentes(exercicio: int, diretorio: Path | None = None) -> dict[str, dict[int, float]]` (= `reconstruir(carregar_eventos(...))`)

- [ ] **Step 1: Write the failing tests** em `tests/test_projecao_ajustes.py`, usando `tempfile.TemporaryDirectory` como `diretorio`: `test_registrar_e_reconstruir` (ajusta `2026NE000001` mês 9 = 800.0 e 10 = 0.0 → `{"2026NE000001": {9: 800.0, 10: 0.0}}`); `test_ultimo_vence_e_none_remove` (9=800, depois 9=900 → 900; depois 9=None → mês some; NE sem meses some do dicionário); `test_refazer_ne_so_limpa_aquela`; `test_refazer_tudo_limpa_exercicio_mas_nao_outro_exercicio` (dois diretórios por exercício); `test_log_nao_e_apagado` (3 eventos → 3 arquivos `.json` na pasta); `test_validacoes` (negativo, `float("nan")`, `float("inf")`, mês 0 e 13, `ne_curta` vazia, `valores` vazio → `ErroAjuste`); `test_arquivo_corrompido_levanta_erro_e_nao_e_sobrescrito` (arquivo `.json` com `{` → `carregar_eventos` levanta `ErroAjuste` e o arquivo continua igual); `test_ne_curta_preserva_texto` (`"2026NE000551"`, não vira número); `test_zero_e_valido`.
- [ ] **Step 2: Run to verify they fail** — `python -m pytest tests/test_projecao_ajustes.py -q -p no:cacheprovider` → FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implement `src/projecao_ajustes.py`** espelhando `src/decisoes_conciliacao.py` (`_pasta`, `_gravar` com tmp + `os.replace`, `_agora()` com microssegundos, `carregar_eventos` que valida `versao_schema` e `tipo ∈ {"ajustar","refazer_ne","refazer_tudo"}`). Pasta de um exercício = `DIRETORIO_AJUSTES / str(exercicio)`. Valores arredondados com `round(float(v), 2)`.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** — `git add src/projecao_ajustes.py tests/test_projecao_ajustes.py .gitignore data/projecao_execucao/.gitkeep` e `git commit -m "feat: log de ajustes da projecao pela execucao"`.

### Task 2: Regra do ajuste e aviso (`src/relatorio_projecao_execucao.py`)

**Files:**
- Modify: `src/relatorio_projecao_execucao.py` (`ProjecaoMensal`, `projetar_meses`, `montar_relatorio`, `COLUNAS_LINHAS`, `_avisos`, `gerar_xlsx`, `gerar_pdf`, `LEGENDA_GRADE`, `NOTA_REGRA`)
- Test: `tests/test_relatorio_projecao_execucao.py`

**Interfaces:**
- Consumes: `ajustes: dict[str, dict[int, float]]` (saída de `projecao_ajustes.reconstruir`).
- Produces:
  - `ProjecaoMensal` ganha `ajustado: list[bool]` (12), `metodologia: list[float | None]` (12; esperado da metodologia, com teto, nos meses editáveis; `None` onde a metodologia não projeta ou o mês não é editável) e `superados: list[int]` (meses de ajuste ignorados por já estarem fechados).
  - `projetar_meses(realizado, custo, fator, mes_referencia, teto_mensal=None, ajustes: dict[int, float] | None = None) -> ProjecaoMensal`
  - `montar_relatorio(..., ajustes: dict[str, dict[int, float]] | None = None)`; `linhas` ganha `ajustada_manualmente: bool`; `mensal` ganha `a1..a12` (bool, mês ajustado e aplicado) e `m1..m12` (metodologia); `RelatorioProjecaoExecucao` ganha `superados: dict[str, list[int]]` e `ajustes_sem_ne: list[str]`.

- [ ] **Step 1: Write the failing tests** em `tests/test_relatorio_projecao_execucao.py` (classe `TestAjustes`, `CUSTO_1000`, `projetar_meses({}, CUSTO_1000, 0.9, 10, ajustes=...)`): `test_ajuste_substitui_esperado_e_teto` (ajuste `{11: 700.0}` com teto 600 → `esperado[10] == 700.0`, `projetado[10] == 700.0`, marcado em `ajustado[10]`); `test_ajuste_abate_liquidado` (`realizado={10: 400.0}`, `ajustes={10: 900.0}` → `projetado[9] == 500.0` e `liquidado_abatido`); `test_ajuste_zero` (`{11: 0.0}` → `projetado[10] == 0.0`, `ajustado[10]` verdadeiro); `test_mes_vazio_da_metodologia_e_editavel` (custo `[0.0]*12`, `{11: 300.0}` → `projetado[10] == 300.0`); `test_mes_fechado_superado` (`mes_referencia=10`, `{5: 123.0}` → mês 5 sem efeito, `superados == [5]`); `test_exercicio_encerrado_ignora_ajustes` (`mes_referencia=12`); `test_metodologia_guardada` (sem ajuste `metodologia[10] == 900.0`; com ajuste continua 900.0); `test_cheio_nao_leva_ajuste`. Em `montar_relatorio` (reuse `_filtrado()`/`_liquidacao()`): `test_relatorio_com_ajuste_muda_necessidade` (NE estável, ajuste de dez = 5000 → `necessidade_execucao` sobe e `ajustada_manualmente`), `test_ajuste_de_ne_inexistente_e_ignorado_e_avisado` (NE `2026NE999999` → sem exceção, `ajustes_sem_ne == ["2026NE999999"]`, aviso presente), `test_aviso_de_ajustadas_traz_numero_do_contrato_e_fornecedor`, `test_excel_traz_coluna_ajustado_e_formato` (formato com `†`), `test_legenda_cita_ajuste`.
- [ ] **Step 2: Run to verify they fail** — `python -m pytest tests/test_relatorio_projecao_execucao.py -q -p no:cacheprovider -k "Ajustes or ajuste"` → FAIL.
- [ ] **Step 3: Implement in `projetar_meses`:** mês editável = `mes >= max(fechado + 1, 1)` e `mes_referencia < 12`; para esse mês, `metodologia[mes-1]` recebe o esperado atual (custo × fator com teto; `None` se custo nulo ou ≤ 0); se existir `ajustes[mes]`, o esperado passa a ser ele (**mesmo com custo nulo ou zero**, mesma regra de mês aberto: completo com ≥ 50% do esperado, tipo `Restante do mês em aberto` ou `Projetado`) e `ajustado[mes-1] = True`; ajuste de mês fechado (`mes <= fechado`) vai para `superados`. `cheio` continua só com custo.
- [ ] **Step 4: Implement in `montar_relatorio`:** passar `ajustes.get(ne, {})` a `projetar_meses`; NE de `ajustes` ausente em `por_ne` → `ajustes_sem_ne`; colunas novas em `COLUNAS_LINHAS`/`mensal`; `_avisos` ganha (a) "Projeção ajustada manualmente:" listando NE + `Contrato <nº> — <fornecedor>` + meses, (b) "Ajuste superado:" com NE, título e mês, (c) "Ajuste sem NE correspondente:". `gerar_xlsx`: coluna "Ajustado manualmente" (Sim/Não) no Resumo e na aba Detalhe mensal "Ajustado" por mês, formato de célula `'#,##0.00"†"'` (combinado com o asterisco: `'#,##0.00"*†"'`); `gerar_pdf`: `†` no valor; `LEGENDA_GRADE` ganha a linha de `†` e `NOTA_REGRA` a frase do ajuste.
- [ ] **Step 5: Run the whole file** — `python -m pytest tests/test_relatorio_projecao_execucao.py tests/test_liquidacao_consumo.py -q -p no:cacheprovider` → PASS (testes antigos intactos).
- [ ] **Step 6: Commit** — `git commit -m "feat: ajuste manual do esperado na projecao pela execucao"`.

### Task 3: Ligação com Necessidade e Resultado Orçamentário

**Files:**
- Modify: `src/resultado_orcamentario_fontes.py` (`projecao_contratos`), `app_pages/resultado_orcamentario.py` (`_necessidade`), `app_pages/contratos_continuos.py` (`_necessidade_pela_execucao`, `_render_relatorio_projecao_execucao`)
- Test: `tests/test_resultado_orcamentario_fontes.py`

**Interfaces:**
- Consumes: `projecao_ajustes.ajustes_vigentes(exercicio)`; `montar_relatorio(..., ajustes=)` (Task 2).
- Produces: `projecao_contratos(tabela, competencia, exercicio, mes_referencia, antecessores=None, nes_pelo_lancamento=None, ajustes: dict[str, dict[int, float]] | None = None) -> tuple[RelatorioProjecaoExecucao, pd.DataFrame]`.

- [ ] **Step 1: Write the failing tests** (`TestContratos`): `test_projecao_contratos_repassa_ajustes` (mesma tabela do teste `igual_ao_caminho_da_pagina`, `ajustes={ne: {12: 99999.0}}` → `novo.total_necessidade_execucao` difere do sem ajuste e `novo.linhas` marca `ajustada_manualmente` só nessa NE); `test_sem_ajustes_continua_igual` (resultado idêntico ao atual).
- [ ] **Step 2: Run to verify they fail**.
- [ ] **Step 3: Implement** o parâmetro `ajustes` repassado a `montar_relatorio`. Nas páginas, ler `ajustes_vigentes(ano)` num `try/except ErroAjuste`: em erro, `st.warning` (Contratos) / `avisos_extras` (Resultado Orçamentário) com o texto do erro, usar `{}` e **nunca gravar**; passar `ajustes=` nas três chamadas de `projecao_contratos` (Contratos ×2, Resultado Orçamentário ×1). Bolsas não recebe.
- [ ] **Step 4: Run** `python -m pytest tests/test_resultado_orcamentario_fontes.py tests/test_resultado_orcamentario_page.py -q -p no:cacheprovider` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: projecao de contratos le os ajustes gravados"`.

### Task 4: Matriz e formulário por NE (`src/ui_projecao_execucao.py`)

**Files:**
- Create: `src/ui_projecao_execucao.py`
- Test: `tests/test_ui_projecao_execucao.py`

**Interfaces:**
- Consumes: `RelatorioProjecaoExecucao` (Task 2), `projecao_ajustes` (Task 1), `src.ui_cadastro.formatar_brl`.
- Produces:
  - `ler_valor_brl(texto: str) -> float | None` (vazio/espaços → `None`; aceita `1.234,56`, `1234,56`, `1234.56`; negativo, `nan`, `inf`, texto → `ValueError`)
  - `titulo_contrato(contrato_numero, fornecedor) -> str` (ex.: `"Contrato 10/2026 — Serval …"`, com `—` quando faltar)
  - `html_matriz(relatorio: RelatorioProjecaoExecucao) -> str` (tabela `cmp-cons`-like: coluna do contrato com número em negrito + fornecedor + NE; células com classes `k-real|k-proj|k-aberto`, ✎ e `*`; `title` com esperado, liquidado e projetado; linha de total; textos escapados)
  - `html_legenda() -> str`
  - `valores_para_gravar(digitado: dict[int, str], vigente: dict[int, float], metodologia: dict[int, float | None]) -> dict[int, float | None]` (só meses que mudam: texto vazio ou igual à metodologia → `None` se havia ajuste, senão omitido; igual ao vigente → omitido)
  - `render_edicao_projecao(relatorio, exercicio: int, extracao: str, chave: str) -> None` (expander "Editar a projeção pela execução": matriz, seletor `"<NE> — <fornecedor> — Contrato <nº>"`, uma `st.text_input` por mês editável com placeholder da metodologia, "Gravar", "Refazer esta NE" e "Refazer todas do exercício" com `st.checkbox` de confirmação; após gravar/refazer, `st.rerun()` e mensagem; `ErroAjuste` vira `st.error`)

- [ ] **Step 1: Write the failing tests:** `test_ler_valor_brl` (`"1.234,56"`, `"1234,56"`, `"1234.56"` → `1234.56`; `""` e `"  "` → `None`; `"0"` → `0.0`; `"abc"`, `"-5"`, `"nan"` → `ValueError`); `test_titulo_contrato` ; `test_html_matriz_tem_titulo_do_contrato_marca_e_total` (relatório sintético: número em `<b>`, fornecedor escapado `&amp;`, `✎` na célula ajustada, linha `Total`); `test_html_matriz_escapa_texto`; `test_valores_para_gravar` (igual à metodologia sem ajuste prévio → vazio; igual à metodologia com ajuste prévio → `{mes: None}`; novo valor → `{mes: valor}`; valor igual ao vigente → vazio; `"0"` → `{mes: 0.0}`).
- [ ] **Step 2: Run to verify they fail**.
- [ ] **Step 3: Implement** as funções puras e `render_edicao_projecao` (Streamlit sem `st.data_editor` nem `st.dialog`; chaves `f"{chave}_pe_*"`; cada widget com `key`; gravar chama `registrar_ajustes(..., extracao=extracao)` só se `valores_para_gravar` não for vazio).
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: matriz e edicao por NE da projecao pela execucao"`.

### Task 5: Integração na página, documentação e verificação

**Files:**
- Modify: `app_pages/contratos_continuos.py`, `README.md`
- Test: `tests/test_contratos_continuos_projecao_editavel_page.py` (AppTest, no padrão de `tests/test_resultado_orcamentario_page.py`)

**Interfaces:**
- Consumes: `render_edicao_projecao` (Task 4); `competencia_consumo.nes_trocadas`; `tempo`/`manifesto_execucao_mensal.sha256[:8]` como `extracao`.

- [ ] **Step 1: Write the failing page tests** (AppTest com a base de fixtures, como os testes de página existentes): `test_bloco_aparece_so_no_modo_projecao_pela_execucao`; `test_gravar_ajuste_muda_a_matriz` (digita o esperado de um mês, clica "Gravar", a célula ganha `✎`, existe 1 arquivo de evento na pasta temporária); `test_refazer_ne_e_geral` (a marca some, log continua com os eventos); `test_arquivo_corrompido_mostra_erro_e_nao_sobrescreve`; `test_titulo_do_contrato_no_seletor`. Use `monkeypatch`/patch de `DIRETORIO_AJUSTES` para pasta temporária.
- [ ] **Step 2: Run to verify they fail**.
- [ ] **Step 3: Implement:** chamar `render_edicao_projecao(...)` logo abaixo do relatório de projeção no `if _modo_execucao:`; documentar no README a regra (esperado total do mês, ajuste superado, onde ficam os arquivos, `†`/`✎`).
- [ ] **Step 4: Full verification:** `python -m pytest tests -n auto -q -p no:cacheprovider` → tudo verde (as falhas que dependem de manifestos locais, se aparecerem no worktree, devem ser as mesmas do `master` limpo). Reiniciar o Streamlit e conferir no navegador: editar um mês, gravar, ver Excel e PDF.
- [ ] **Step 5: Commit** — `git commit -m "feat: edicao da projecao pela execucao na pagina de Contratos Continuos"`; depois PR (descrição sem nomes de fornecedor, NE ou valores).
