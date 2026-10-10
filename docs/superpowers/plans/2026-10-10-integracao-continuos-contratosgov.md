# Integração Contratos Contínuos × Contratos.gov.br Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Conciliar vigência e aditivos do Contratos.gov.br com o cadastro nativo de Contratos Contínuos, permitir registrar aditivos do gov com um clique (só grava ao Salvar) e incluir contratos novos do gov no cadastro.

**Architecture:** Funções puras novas em `src/contratos_continuos.py` (ligação por NE, depois número+CNPJ; conciliação; aditivos pendentes; candidatos), consumindo as tabelas `contratos`/`termos`/`empenhos` de `src/contratos_cadastro.py` já montadas. A página `app_pages/contratos_continuos.py` as aplica depois de `tabela_contratos(...)`, em memória, sem nova persistência; gravações só pelos diálogos já existentes.

**Tech Stack:** Python 3.14, pandas, Streamlit (`AppTest`), pytest (`python -m pytest ... -n auto`, ver `AGENTS.md`).

**Spec:** `docs/superpowers/specs/2026-10-10-integracao-continuos-contratosgov-design.md`

## Global Constraints

- Repositório: `G:\Outros computadores\Meu PC\Downloads\ufrpe-budgetlab`; branch nova `feat/integracao-continuos-contratosgov` a partir de `feat/google-agenda` (decisão do usuário: editar a pasta do Drive; o usuário para de usar a pasta durante o trabalho e volta para `feat/google-agenda` depois).
- Nunca alterar a fotografia do gov (`data/raw/contratosgov/`), `tests/fixtures/*` nem planilhas; nada novo em `data/` (cadastro nativo já existente é a única persistência).
- NE, CNPJ/CPF, números de contrato e códigos sempre texto, zeros à esquerda preservados; nulo ≠ zero ≠ negativo (usar `pd.NA`/`None` para ausente).
- Divergência de valor fora de escopo: `valor_parcela_contratosgov` é só referência.
- Nada é gravado sem o usuário clicar em Salvar/"Adicionar contrato" nos diálogos existentes.
- Regra específica de base fora do importador genérico; funções em `src/contratos_continuos.py`; não mexer em `src/resultado_orcamentario_fontes.py`.
- Testes: referência do gov fixa em `date(2026, 10, 8)`, fixture `tests/fixtures/contratosgov_2026-10-08.json` (6 contratos); valores esperados abaixo foram calculados à mão. Testes de página usam `TEMPO_LIMITE_APPTEST` e `aquecer_pagina` de `tests/_apptest.py`.
- Rodadas intermediárias: `python -m pytest tests/<arquivo> -q`; ao final do plano a suíte completa `python -m pytest tests -n auto` (muda código compartilhado de página).
- Desvio da spec: `com_contratosgov` não recebe `hoje` — a situação de vigência do gov já vem de `montar_contratos(fotografia, referencia)`.

## Review Focus

- NE do cadastro com espaços/minúsculas ou nula: normalizar (`strip().upper()`) e nunca casar nulo com nulo.
- Um contrato do gov ligado por vários registros (uma NE cada): não duplica candidatos nem muda contagens do gov; `contratosgov_id` igual nos registros.
- Contrato do gov sem empenhos (`220038`) ou sem natureza/PI/fonte: "Incluir" funciona com NE e códigos nulos, sem exceção.
- CNPJ/CPF de pessoa física com zeros (`00000000191`) e com pontuação no cadastro (`000.000.001-91`): comparar só dígitos, gravar o texto como veio do gov.
- Fotografia ausente, ilegível ou vazia: a tela segue sem a integração, com aviso, sem exceção; termo sem `data_inicio_novo_valor` nem `data_assinatura`: sugestão chega com `data_inicio` nula (o usuário preenche; `validar_aditivos` recusa ao salvar).

---

### Task 0: Branch e documentos

**Files:**
- Add (commit): `docs/superpowers/specs/2026-10-10-integracao-continuos-contratosgov-design.md`, `docs/superpowers/plans/2026-10-10-integracao-continuos-contratosgov.md`

- [ ] **Step 1:** Confirmar que o usuário parou de usar a pasta; `git status --short` deve listar só os 3 manifestos `data/manifestos/contratosgov_*` e os dois documentos (nada de `src/`/`app_pages/` modificado). Se houver outra alteração, parar e perguntar.
- [ ] **Step 2:** `git switch -c feat/integracao-continuos-contratosgov` (a partir da `feat/google-agenda` atual; não mexe nos arquivos). Rodar `python -m pytest tests/test_contratos_continuos.py tests/test_contratos_cadastro.py -q` e anotar a linha de resultado como baseline.
- [ ] **Step 3: Commit** apenas os dois documentos: `git add docs/superpowers/specs/2026-10-10-integracao-continuos-contratosgov-design.md docs/superpowers/plans/2026-10-10-integracao-continuos-contratosgov.md` e `git commit -m "docs: spec e plano da integracao Continuos x Contratos.gov"` (não adicionar os manifestos não rastreados).

### Task 1: `com_contratosgov` — ligação e conciliação de vigência

**Files:**
- Modify: `src/contratos_continuos.py` (nova seção após `com_meses_pagos`; atualizar a docstring "Contrato público" se o módulo a tiver)
- Test: `tests/test_contratos_continuos.py` (estilo do arquivo; classe `TestComContratosGov`)

**Interfaces:**
- Consumes: `normalizar_numero_contrato(valor) -> str | None` (já importada no módulo); `src.contratos_cadastro.montar_contratos/montar_termos/montar_empenhos` (nos testes); `src.contratos_continuos_cadastro.novo_contrato/como_dataframe` (nos testes); `src.contratos_aditivos.Aditivo`.
- Produces:
  - `SITUACOES_CONCILIACAO = ("conciliado", "divergente", "sem_par_no_contratosgov", "conflito", "sem_data_para_comparar")`
  - `com_contratosgov(df: pd.DataFrame, contratos: pd.DataFrame, termos: pd.DataFrame, empenhos: pd.DataFrame) -> pd.DataFrame` — cópia de `df` com as colunas: `contratosgov_id` (string), `ligacao_por` (`"ne"`/`"numero"`/nulo), `situacao_conciliacao`, `situacao_vigencia_gov`, `vigencia_fim_contratosgov` (`date`), `diverge_vigencia` (`boolean`), `qtd_termos`, `qtd_aditivos_gov` (`Int64`), `valor_parcela_contratosgov` (float, referência). Colunas do gov ficam nulas sem par/conflito.

- [ ] **Step 1: Write the failing tests.** Helpers do módulo de teste: `_gov()` → `(contratos, termos, empenhos)` de `montar_*` sobre a fixture com `date(2026,10,8)`; `_cadastro(*registros)` → `como_dataframe([novo_contrato(**r) ...], 2026, hoje=date(2026,10,8))`. Testes (nome → asserções):
  - `test_liga_por_ne`: registro `contrato_numero="13/2026", ne_curta="2026NE000522", vigencia_fim=Timestamp("2027-09-10")` → `contratosgov_id == "1004328"`, `ligacao_por == "ne"`, `situacao_conciliacao == "conciliado"`, `diverge_vigencia` falso, `qtd_termos == 1`, `qtd_aditivos_gov == 0`, `situacao_vigencia_gov == "vigente"`, `vigencia_fim_contratosgov == date(2027,9,10)`.
  - `test_ne_com_espacos_e_minusculas_liga`: `ne_curta=" 2026ne000522 "` → mesmo `contratosgov_id`.
  - `test_liga_por_numero_e_cnpj_sem_ne`: `"29/2021"`, `fornecedor_cnpj_cpf="07.674.744/0001-30"`, `vigencia_fim=Timestamp("2026-10-17")` → `ligacao_por == "numero"`, id `"118872"`, `qtd_termos == 5`, `qtd_aditivos_gov == 4`, conciliado.
  - `test_numero_sem_cnpj_nao_liga`: `"29/2021"` sem CNPJ e sem NE → `sem_par_no_contratosgov`.
  - `test_divergente_e_aditivo_nativo_concilia`: `"29/2021"`, `ne_curta="2025NE000046"`, `vigencia_fim=Timestamp("2025-10-17")`, sem aditivos → `divergente` e `diverge_vigencia` verdadeiro (gov 2026-10-17); com um aditivo nativo `{"numero":"4","tipo":"PRORROGACAO","situacao":"ASSINADO","data_inicio":"2025-10-18","vigencia_fim":"2026-10-17"}` → `conciliado` (conferir contra `vigencia_efetiva` de `src/contratos_aditivos.py`).
  - `test_conflito_ne_e_numero`: `"13/2026"` + CNPJ `05340639000130` + `ne_curta="2025NE000046"` (NE do 118872) → `conflito`, `contratosgov_id` nulo, colunas do gov nulas.
  - `test_ne_em_dois_contratos_e_conflito`: `empenhos` sintético com a mesma `ne` em dois `contrato_id` → `conflito`.
  - `test_varios_registros_mesmo_contrato`: duas linhas, NEs `2026NE000522` e `2026NE000523` → ambas `contratosgov_id == "1004328"`.
  - `test_sem_par`: `"99/2026"`, `ne_curta="2026NE999999"` → `sem_par_no_contratosgov`, `diverge_vigencia` nulo; `ne_curta` nula em dois registros não casam entre si.
  - `test_vigencia_nula_nao_e_divergencia`: `vigencia_fim=None` ligado por NE → `sem_data_para_comparar`, `diverge_vigencia` nulo.
  - `test_contrato_encerrado_no_gov`: `ne_curta="2021NE000072"` (contrato `7925`, vigência gov 2025-05-31) → `situacao_vigencia_gov == "encerrado"`.
  - `test_nao_altera_linhas_nem_valores` (mesma quantidade de linhas e colunas originais idênticas) e `test_df_vazio_devolve_colunas_novas`.
- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_contratos_continuos.py -q -k ContratosGov`. Expected: erro de importação de `com_contratosgov`.
- [ ] **Step 3: Implement** `com_contratosgov` em `src/contratos_continuos.py`. Abordagem: índices `ne → {contrato_id}` (de `empenhos`, ne normalizada com `strip().upper()`) e `(número normalizado, CNPJ só dígitos) → {contrato_id}` (de `contratos.numero`/`fornecedor_documento`); por linha: candidatos por NE (só se `ne_curta` não nula) e por número+CNPJ (só se ambos presentes); NE com >1 contrato, número ambíguo, ou os dois conjuntos não vazios e diferentes → `conflito`; um só conjunto → liga (`ligacao_por`); nenhum → sem par. Comparar `vigencia_fim_efetiva` (Timestamp → `.date()`) com `contratos.vigencia_fim` (`date`); falta de data → `sem_data_para_comparar`. `qtd_aditivos_gov` = termos do contrato com `tipo == "Termo Aditivo"`. `valor_parcela_contratosgov` = `float(Decimal)` do contrato. Sem `Series.map` com merge que possa duplicar linhas.
- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_contratos_continuos.py -q`. Expected: tudo PASS (testes antigos inclusos).
- [ ] **Step 5: Commit**

```bash
git add src/contratos_continuos.py tests/test_contratos_continuos.py
git commit -m "feat: com_contratosgov liga Continuos ao Contratos.gov e concilia a vigencia"
```

### Task 2: Aditivos do gov sem registro

**Files:**
- Modify: `src/contratos_continuos.py`
- Test: `tests/test_contratos_continuos.py` (classe `TestAditivosDoGov`)

**Interfaces:**
- Consumes: `Aditivo`, `aditivos_do_registro` de `src.contratos_aditivos`; `normalizar_numero_contrato`; `termos` do gov (`tipo`, `numero`, `qualificacao_termo`, `data_assinatura`, `vigencia_fim`, `data_inicio_novo_valor`).
- Produces:
  - `tipo_aditivo_por_qualificacao(qualificacao: object) -> str` (um de `TIPOS` de `src.contratos_aditivos`)
  - `aditivos_pendentes(aditivos: list[Aditivo], termos_do_contrato: pd.DataFrame) -> pd.DataFrame` — linhas de `termos_do_contrato` (só `tipo == "Termo Aditivo"`) sem aditivo nativo correspondente
  - `aditivo_sugerido(termo: pd.Series) -> Aditivo`
  - `com_contratosgov` ganha a coluna `qtd_aditivos_pendentes` (`Int64`, nula sem par/conflito)

- [ ] **Step 1: Write the failing tests:**
  - `test_tipo_por_qualificacao`: `"VIGÊNCIA; REAJUSTE"`→`REAJUSTE`; `"VIGÊNCIA"`→`PRORROGACAO`; `"ACRÉSCIMO / SUPRESSÃO"`→`ACRESCIMO_SUPRESSAO`; `"INFORMATIVO; ACRÉSCIMO / SUPRESSÃO; VIGÊNCIA"`→`PRORROGACAO`; `"INFORMATIVO"`, `""`, `None`, `pd.NA`→`OUTRO`.
  - `test_pendentes_do_118872_sem_aditivos_nativos`: números pendentes `["00001/2022","00002/2023","00003/2024","00004/2025"]`.
  - `test_registrado_por_numero_normalizado`: aditivo nativo `numero="1/2022"` → restam 3 (`00002/2023`, `00003/2024`, `00004/2025`).
  - `test_registrado_por_data_de_assinatura`: aditivo nativo com `numero="TA"` e `data_assinatura=date(2023,10,17)` → `00002/2023` deixa de ser pendente.
  - `test_apostilamento_e_contrato_nao_sao_aditivos`: contrato `18940` sem nativos → pendentes `["00001/2019","00002/2021","00003/2022","00004/2024"]` (o `00004/2026` apostilamento e o termo "Contrato" ficam fora).
  - `test_aditivo_sugerido_reajuste`: termo `00004/2025` do 118872 → `Aditivo(numero="00004/2025", tipo="REAJUSTE", situacao="ASSINADO", data_inicio=date(2025,10,18), data_assinatura=date(2025,9,16), valor_mensal=None, vigencia_fim=date(2026,10,17), itens=None)`.
  - `test_aditivo_sugerido_sem_data_inicio_usa_assinatura`: termo `00001/2019` do 18940 → `tipo="PRORROGACAO"`, `data_inicio=date(2019,11,28)`; termo sintético sem `data_inicio_novo_valor` nem `data_assinatura` → `data_inicio is None`.
  - `test_com_contratosgov_conta_pendentes`: registro ligado ao 118872 sem aditivos nativos → `qtd_aditivos_pendentes == 4`; sem par → nulo.
- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_contratos_continuos.py -q -k "AditivosDoGov or pendentes"`. Expected: ImportError/FAIL.
- [ ] **Step 3: Implement** as três funções e a coluna. Regras: tipo = `REAJUSTE` se a qualificação contém "REAJUSTE"; senão `PRORROGACAO` se contém "VIGÊNCIA" (comparação sem acento e em maiúsculas via `_normalizar`); senão `ACRESCIMO_SUPRESSAO` se contém "ACRESCIMO"; senão `OUTRO`. "Registrado" = algum aditivo nativo com mesmo número normalizado (`normalizar_numero_contrato` quando reconhecível, senão `strip().upper()`) **ou** mesma `data_assinatura`. `valor_mensal` sempre `None`.
- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_contratos_continuos.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**

```bash
git add src/contratos_continuos.py tests/test_contratos_continuos.py
git commit -m "feat: aditivos do Contratos.gov pendentes de registro e aditivo sugerido"
```

### Task 3: Contratos novos do gov (`candidatos_novos`, `registro_novo_do_gov`)

**Files:**
- Modify: `src/contratos_continuos.py`
- Test: `tests/test_contratos_continuos.py` (classe `TestCandidatosNovos`)

**Interfaces:**
- Consumes: ligação da Task 1 (reutilizar o mesmo código interno de resolução, sem duplicar a regra); `src.contratos_continuos_cadastro.novo_contrato` (só nos testes).
- Produces:
  - `numero_no_formato_continuos(numero_gov: object) -> str | None` (`"00013/2026"`→`"13/2026"`, `"00002/2026"`→`"02/2026"` — ao menos 2 dígitos —, `"00018/2014"`→`"18/2014"`; texto fora do padrão devolve o original aparado; nulo → `None`)
  - `candidatos_novos(df: pd.DataFrame, contratos: pd.DataFrame, empenhos: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]` → `(candidatos, em_duvida)`, colunas: `contrato_id`, `numero`, `ano_contrato`, `fornecedor_nome`, `fornecedor_documento`, `objeto`, `categoria`, `vigencia_fim`, `situacao_vigencia`, `valor_parcela`, `nes` (lista de dicts `{"ne","natureza_despesa","plano_interno","fonte_recurso"}` com os textos do gov), `motivo`; ordenado por `vigencia_fim` crescente.
  - `registro_novo_do_gov(candidato: pd.Series, ne: str | None = None) -> dict` — argumentos de `novo_contrato(...)`: `contrato_numero`, `ano_contrato`, `fornecedor`, `fornecedor_cnpj_cpf`, `vigencia_fim` (`Timestamp`), `status_contrato="ATIVO"`, e, se `ne` informada e presente em `nes`: `ne_curta`, `natureza_despesa_cod`, `pi_cod`, `fonte_cod` (código = texto antes de `" - "`). Sem `ne`, essas chaves são `None`. Nunca traz `acao_cod`, `ptres`, `ugr_cod`, `despesa_mensal` nem meses.

- [ ] **Step 1: Write the failing tests** (ref. 2026-10-08):
  - `test_candidatos_com_um_registro_ligado`: cadastro com registro `ne_curta="2026NE000522"` → candidatos `contrato_id` `["118872","18940","220038"]` (nessa ordem: vigências 2026-10-17, 2027-05-28, 2027-10-03); `em_duvida` vazio; `71912` (inativo) e `7925` (encerrado) ausentes.
  - `test_cadastro_vazio_lista_os_quatro_vigentes`: ids `{"1004328","118872","18940","220038"}`.
  - `test_conflito_vai_para_duvida`: registro `"13/2026"` + CNPJ `05340639000130` + `ne_curta="2025NE000046"` → `em_duvida` = `{1004328, 118872}` com `motivo` contendo "conflito"; candidatos `{18940, 220038}`.
  - `test_sem_vigencia_vai_para_duvida`: `contratos` sintético com `situacao_vigencia="sem_vigencia"` → em dúvida, `motivo` contendo "sem vigência".
  - `test_varios_registros_do_mesmo_contrato_nao_duplicam`: dois registros (NEs 522 e 523) → o `1004328` não aparece e nenhum id repete.
  - `test_documento_preserva_zeros`: candidato `220038` → `fornecedor_documento == "00000000191"` (string).
  - `test_numero_no_formato_continuos`: os quatro casos acima + `None` + `"SN/2026"`.
  - `test_registro_novo_do_gov_com_ne`: candidato `1004328`, `ne="2026NE000522"` → `contrato_numero="13/2026"`, `ano_contrato=2026`, `fornecedor` e `fornecedor_cnpj_cpf="05340639000130"` do gov, `vigencia_fim=Timestamp("2027-09-10")`, `ne_curta="2026NE000522"`, `natureza_despesa_cod="339039"`, `pi_cod="M20RKG01SCN"`, `fonte_cod="1000000000"`, `status_contrato="ATIVO"`; `"acao_cod"`, `"ptres"`, `"ugr_cod"`, `"despesa_mensal"` ausentes do dict.
  - `test_registro_novo_do_gov_sem_ne_e_contrato_sem_empenhos`: `220038` sem `ne` → `ne_curta`, `natureza_despesa_cod`, `pi_cod`, `fonte_cod` `None`; sem exceção.
  - `test_registro_aceito_por_novo_contrato`: `novo_contrato(**registro_novo_do_gov(...))` não levanta.
- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_contratos_continuos.py -q -k CandidatosNovos`. Expected: ImportError.
- [ ] **Step 3: Implement.** Candidato = contrato com `situacao_vigencia` ∈ {`vigente`, `a_iniciar`} e nenhum registro ligado (mesma resolução da Task 1); em dúvida = `sem_vigencia` e todo contrato citado em conflito (união dos conjuntos NE/número) — cada um com `motivo`. Extrair de `com_contratosgov` uma função interna `_resolver_ligacoes(df, contratos, empenhos)` e usá-la nas duas.
- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_contratos_continuos.py -q`. Expected: PASS.
- [ ] **Step 5: Commit**

```bash
git add src/contratos_continuos.py tests/test_contratos_continuos.py
git commit -m "feat: candidatos novos do Contratos.gov e registro pre-preenchido para Continuos"
```

### Task 4: Tela — conciliação e "Registrar aditivo do gov"

**Files:**
- Modify: `src/ui_aditivos.py` (nova função), `app_pages/contratos_continuos.py` (carga do gov, `com_contratosgov` após `tabela_contratos(...)`, subtítulo da linha, seção na janela de edição)
- Test: `tests/test_ui_aditivos.py` (se não existir, criar; teste de `acrescentar_aditivo`), `tests/test_contratos_continuos_gov_page.py` (novo)

**Interfaces:**
- Consumes: `com_contratosgov`, `aditivos_pendentes`, `aditivo_sugerido` (Tasks 1–2); `src.contratosgov_extracao.carregar_atual() -> (fotografia | None, manifesto | None)` e `FotografiaAusente`; `montar_contratos(fotografia, referencia)`, `montar_termos(fotografia)`, `montar_empenhos(fotografia)`; `aditivo_para_registro`.
- Produces: `acrescentar_aditivo(k: str, aditivos_atuais: list[Aditivo], novo: Aditivo) -> None` em `src/ui_aditivos.py` — se `st.session_state[f"{k}_aditivos"]` não existe, inicializa como `render_aba_aditivos` (cada registro com `_uid` = posição, `f"{k}_aditivos_prox"` = tamanho); depois acrescenta `{**aditivo_para_registro(novo), "_uid": prox}` e incrementa `prox`. Na página: `_carregar_gov(referencia: date) -> tuple[DataFrame, DataFrame, DataFrame] | None` (aviso `st.warning` em fotografia ausente/ilegível, nunca exceção; referência vinda de `st.session_state.get("contratos_referencia", date.today())`, gancho de teste igual ao de `app_pages/contratos.py`).

- [ ] **Step 1: Write the failing tests.**
  - `test_acrescentar_aditivo_inicializa_e_acrescenta` (via `AppTest.from_function`): sem estado, com 1 aditivo atual e 1 novo → lista com 2 itens, `_uid` `[0, 1]`, `_prox == 2`; com estado já existente (`_uid` 0..2, `_prox` 3) → novo recebe `_uid == 3`.
  - Página (`tests/test_contratos_continuos_gov_page.py`, estilo de `tests/test_contratos_page.py`: `monkeypatch` de `contratosgov_extracao.DIRETORIO_MANIFESTOS/FOTOGRAFIAS` com `gravar(...)` da fixture, e de `src.contratos_continuos_cadastro.DIRETORIO_PADRAO` para `tmp_path` com `salvar_contrato(2026, novo_contrato(...))`; `skipUnless` do manifesto `data/manifestos/execucao_mensal_atual.json`; `aquecer_pagina` no setup): cadastro de teste com três registros — `13/2026` (NE 2026NE000522, vigência 2027-09-10), `29/2021` (NE 2025NE000046, vigência original 2025-10-17, sem aditivos) e `99/2026` (NE 2026NE999999).
    - `test_linhas_mostram_conciliacao`: sem exceção; HTML contém a vigência confere para o `13/2026`, "vigência diverge" para o `29/2021`, "sem par no Contratos.gov" para o `99/2026`, e "4 aditivos pendentes" no `29/2021`.
    - `test_janela_de_edicao_lista_aditivos_do_gov_sem_gravar`: clicar `cc_editar_*` do `29/2021` → a janela mostra a seção "Contratos.gov", os quatro botões "Registrar aditivo do gov" (um por número `00001/2022`…`00004/2025`) e o texto "nada é gravado até Salvar"; o cadastro em `tmp_path` não muda (mesmos arquivos e conteúdo).
    - `test_sem_fotografia_segue_com_aviso`: sem fotografia gravada → sem exceção, `st.warning`/`st.info` mencionando "Contratos.gov", e as linhas do registro continuam sem chip de conciliação.
- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_ui_aditivos.py tests/test_contratos_continuos_gov_page.py -q`. Expected: FAIL (função/chips ausentes).
- [ ] **Step 3: Implement** `acrescentar_aditivo`; `_carregar_gov`; chamada `com_contratosgov(dataframe, contratos, termos, empenhos)` logo após `tabela_contratos(...)` (só quando a carga deu certo); o subtítulo da linha ganha um trecho curto (ex.: "Gov: vigência confere", "Gov: vigência diverge", "sem par no Contratos.gov", "N aditivo(s) pendente(s)") sem alterar as colunas de `_PROPORCOES_REGISTRO`; a janela `_dialogo_editar_contrato` ganha, antes das abas Período/Aditivos, a seção "Contratos.gov" (vigência do cadastro × do gov, termo atual, histórico de termos em `st.dataframe`, valor da parcela rotulado "referência"), e para cada pendente um botão "Registrar aditivo do gov (<número do termo>)" que chama `acrescentar_aditivo(k, linha["aditivos"], aditivo_sugerido(termo))` seguido de `st.rerun(scope="fragment")`. Texto fixo na seção: "Nada é gravado até clicar em Salvar; revise os campos na aba Aditivos."
- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_ui_aditivos.py tests/test_contratos_continuos_gov_page.py tests/test_cadastros_layout_page.py tests/test_contratos_continuos.py -q`. Expected: PASS (a layout page não regride). Conferir a tela real com `preview_start` (porta livre) abrindo um registro ligado.
- [ ] **Step 5: Commit**

```bash
git add src/ui_aditivos.py app_pages/contratos_continuos.py tests/test_ui_aditivos.py tests/test_contratos_continuos_gov_page.py
git commit -m "feat: tela de Continuos concilia vigencia e permite registrar aditivos do Contratos.gov"
```

### Task 5: Tela — bloco "Novos no Contratos.gov" e inclusão

**Files:**
- Modify: `app_pages/contratos_continuos.py` (`_dialogo_novo_contrato` aceita valores iniciais; novo `_render_novos_contratosgov`)
- Test: `tests/test_contratos_continuos_gov_page.py`

**Interfaces:**
- Consumes: `candidatos_novos`, `registro_novo_do_gov` (Task 3); `_dialogo_novo_contrato`, `novo_contrato`, `salvar_contrato`.
- Produces: `_dialogo_novo_contrato(ano_exercicio: int, source_key: str, valores: dict | None = None) -> None` (cada widget usa `valores.get(...)` como valor inicial; sem `valores` o comportamento atual não muda) e `_render_novos_contratosgov(candidatos, em_duvida, ano_exercicio, source_key) -> None`.

- [ ] **Step 1: Write the failing tests** (mesmo cenário da Task 4, cadastro com `13/2026`, `29/2021`, `99/2026`):
  - `test_bloco_lista_candidatos_e_duvidas`: existe expander "Novos no Contratos.gov"; lista `00021/2017` e `00021/2023` (o `118872` está ligado ao `29/2021`, o `1004328` ao `13/2026`); `em_duvida` vazio; contratos inativo/encerrado ausentes.
  - `test_incluir_abre_janela_pre_preenchida_sem_gravar`: clicar "Incluir" do `00021/2017` → janela "Novo contrato" com `Nº do contrato == "21/2017"`, `Fornecedor == "RIO AVE IMOVEIS LTDA"`, `Ano == 2017`, `CNPJ/CPF == "10729661000106"`, vigência 28/05/2027; `Ação`, `PTRES`, `UGR` e `Despesa mensal` em branco/zero-padrão do formulário; cadastro em `tmp_path` sem arquivo novo.
  - `test_contrato_com_varias_nes_exige_escolha`: para o `00021/2017` (14 NEs) o bloco oferece um `selectbox` de NE; sem escolha, `ne_curta`/ND/PI/fonte da janela vêm vazios; escolhida `2026NE000203`, vêm preenchidos com os códigos do gov dessa NE.
  - `test_contrato_sem_empenhos_pode_ser_incluido`: `00021/2023` → janela abre com `NE` vazia, sem exceção.
- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_contratos_continuos_gov_page.py -q -k Novos`. Expected: FAIL.
- [ ] **Step 3: Implement.** Bloco em `st.expander` fechado, antes do "Registro de contratos", com contagem no rótulo; cada candidato numa linha compacta (número, fornecedor, vigência, valor da parcela rotulado "referência") + `selectbox` de NE quando houver mais de uma (opção "—" = nenhuma) + botão "Incluir" que chama `_dialogo_novo_contrato(ano, source_key, registro_novo_do_gov(candidato, ne))`. Em dúvida: lista só com o motivo, sem botão. A janela só grava no clique do botão do próprio formulário, como hoje.
- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_contratos_continuos_gov_page.py tests/test_cadastros_layout_page.py -q`. Expected: PASS. Conferir a tela real com `preview_start`.
- [ ] **Step 5: Commit**

```bash
git add app_pages/contratos_continuos.py tests/test_contratos_continuos_gov_page.py
git commit -m "feat: inclusao de contratos novos do Contratos.gov no cadastro de Continuos"
```

### Task 6: Documentação e suíte completa

**Files:**
- Modify: `README.md` (seção de Contratos Contínuos/Contratos.gov: ligação por NE, conciliação, aditivos sob demanda, candidatos, limites e dúvidas)

- [ ] **Step 1:** Atualizar o README no estilo da seção existente; incluir as dúvidas: casamento de aditivo "registrado" é heurístico (número/data), tipo do aditivo por qualificação é sugestão editável, valor mensal do gov não é importado (parcela 20RK × contrato inteiro), candidatos = todos os vigentes ausentes do exercício em tela.
- [ ] **Step 2: Run full suite** — `python -m pytest tests -n auto`. Expected: tudo PASS; registrar totais. Qualquer falha (mesmo anterior) é listada por nome no relatório.
- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: integracao Continuos x Contratos.gov"
```

---

## Self-Review

- **Cobertura da spec:** ligação/conciliação (T1), aditivos pendentes/sugeridos (T2), candidatos e pré-preenchimento (T3), cartão/janela/registrar sem gravar (T4), bloco de novos e Incluir (T5), docs/suíte (T6), branch/commit dos documentos (T0). Critérios de aceitação 1–5 mapeados em T1, T4–T5 (testes "sem gravar"), T4, T3/T5, T6.
- **Desvios da spec (ledger):** `com_contratosgov` sem `hoje`; subtítulo da linha em vez de nova coluna da tabela (colunas compartilhadas); `numero_no_formato_continuos` (mín. 2 dígitos) como convenção observada no cadastro (`02/2026`, `07/2026`) — editável pelo usuário.
- **Consistência de tipos:** `contrato_id` sempre string; `vigencia_fim` do gov é `date`, `vigencia_fim_efetiva` é `Timestamp` (comparar com `.date()`); `Aditivo` nunca recebe `valor_mensal` do gov.
- **Riscos abertos:** testes de página dependem de `data/manifestos/execucao_mensal_atual.json` e do cache aquecido (pulados sem ele); `AppTest` só executa a primeira invocação de um `@st.dialog` — por isso os testes de janela verificam o conteúdo ao abrir, não interações dentro dela.
