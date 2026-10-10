# TEDs — alertas sem falso positivo e conferência com a planilha de controle de NCs — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer os alertas de conciliação dos TEDs apontarem só divergência comprovável pelas fontes oficiais e oferecer uma conferência em memória com a planilha manual de controle de NCs, para sanear pendências caso a caso.

**Architecture:** Regras revistas em `src/teds_alertas.py`; reavaliação em `src/teds_lotes.py` fecha (com justificativa e auditoria) os alertas que as regras revistas não sustentam; leitor e conferência puros (sem Streamlit, sem gravação) em `src/teds_controle_nc.py`; seção nova na página Conciliação com upload, conferência, download e resolução manual de alerta pelo fluxo já existente.

**Tech Stack:** Python, pandas, openpyxl, SQLite (`sqlite3`), `Decimal`, Streamlit, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-teds-alertas-e-controle-nc-design.md`

## Global Constraints

- Todo valor monetário do módulo é `Decimal` (`teds_normalizacao.texto_para_valor`); nunca `float` no cálculo.
- Códigos (NC, UG, PTRES, natureza, fonte, PI, TED, transferência) são texto, zeros à esquerda preservados; `"-"`, vazio e `nan` viram `None`.
- **A planilha nunca é gravada:** nenhuma tabela, coluna, lote ou arquivo novo; a conferência roda em memória. O único efeito persistente permitido é a resolução de alerta que o usuário confirma, pelo fluxo existente `teds_ui.atualizar_status_alerta` (auditado).
- Tolerância monetária: `TOLERANCIA_CONCILIACAO = Decimal("0.01")` (já existe).
- "Sem base" (dado ausente) nunca vira zero e nunca gera alerta de divergência.
- Fechamento automático (opção A): status `resolvido`, `responsavel = "sistema"`, justificativa começando por `"Regra revisada em 08/10/2026: "`, registro `alerta_status_alterado` na `auditoria` na mesma transação; só para os 5 tipos revistos.
- Comentários e docstrings em português, no estilo do repositório (decisão + data + motivo).
- Testes usam SQLite temporário (`tmp_path`), nunca `data/teds/teds.db`. Rodar em série (`python -m pytest ... -q -p no:cacheprovider`), nunca `-n auto`.

## Review Focus

1. **Mesmo número de NC em UGs diferentes:** a conferência nunca escolhe uma por acaso; ambígua = sem UG sugerida e sem comparação de valor (Task 3, `test_nc_ambigua_nao_e_comparada`).
2. **TED com documentos em parte dentro e em parte fora da janela do consolidado:** só a parte dentro entra na comparação, a de fora aparece na descrição (Task 1, `test_janela_parcial`).
3. **Fechamento automático só nos tipos revistos:** `ted_credito_sem_empenho` aberto sem candidato atual nunca é fechado (Task 2, `test_nao_fecha_tipos_nao_revistos`).
4. **Alerta já resolvido manualmente** não é reaberto nem duplicado (Task 2, `test_resolvido_manual_nao_reabre`).
5. **Upload na Conciliação não grava nada:** contagens de todas as tabelas do banco iguais antes e depois da conferência (Task 4, `test_conferencia_nao_grava_no_banco`).

---

### Task 1: Regras revistas dos alertas

**Files:**
- Modify: `src/teds_alertas.py` (`ResumoConciliacaoSimec`, `_carregar_resumos_conciliacao`, `gerar_alertas_conciliacao_simec`, `gerar_alertas_nc_parcial`/`sincronizar_alertas_nc_parcial`, `gerar_alertas_cadastrais`/`_carregar_cadastro`/`sincronizar_alertas_cadastrais`, descrição em `gerar_alertas_execucao_do_ted`)
- Test: os arquivos de testes de alertas existentes (`tests/test_teds_alertas.py`, `tests/test_teds_conciliacao_simec.py`, `tests/test_teds_validacoes_cadastrais.py`, `tests/test_teds_execucao_do_ted.py` — use os que já cobrem cada regra)

**Interfaces:**
- Produces: `ResumoConciliacaoSimec` ganha `anos_consolidado: frozenset[int]`, `nc_fora_janela: Decimal`, `pf_fora_janela: Decimal`, `documentos_sem_data: int`, `inicio_vigencia: date | None`. `nc_analitica`/`pf_analitica` somam **só documentos com ano em `anos_consolidado`** e ficam `None` quando o TED não tem nenhum documento do tipo.
- `gerar_alertas_cadastrais` ganha parâmetro `ultima_execucao_tesouro: dict[str, date] | None = None` (chave_ted → último dia do mês mais recente com liquidado ou pago ≠ 0 em NE vinculada não descartada) e `movimento_consolidado_no_ano: set[str] | None = None` (chave_ted com NC ou PF ≠ 0 no ano de `hoje` em `execucao_anual`); `_carregar_cadastro`/`sincronizar_alertas_cadastrais` carregam os dois.
- `TIPO_NC_UG_EMITENTE_AUSENTE` passa a ser um por TED: documento `f"ted:{chave_ted}"`, gravidade `baixa`, descrição com a contagem e os números das NCs sem UG. NC sem `chave_ted` agrupa em `ted:(sem TED)`.

Regras: ver spec §3.1–§3.5 (texto da descrição do consolidado e do TED encerrado copiados de lá).

- [ ] **Step 1: Write the failing tests** (banco temporário com `ted`, `execucao_anual`, `documento_nc`/`documento_pf`, `vinculo_ne`, `execucao_tg` conforme o caso):
  - `test_janela_elimina_divergencia_de_periodo`: consolidado 2023–2025 repassado R$ 1.094.824,95; PFs 2019–2022 somando 1.711.150,55 e 2023–2025 somando 1.094.824,95 → sem `pf_liquida_diverge_consolidado`.
  - `test_janela_parcial`: mesma janela, PFs 2023–2025 somando 1.000.000,00 → alerta; descrição contém "1.711.150,55".
  - `test_ted_sem_pf_no_extrato_e_sem_base`: TED com repassado 842.294,76 e nenhum PF dele (há PF de outro TED) → sem alerta.
  - `test_pf_maior_que_nc_vigencia_anterior_e_sem_base`: vigência desde 2022-08-16, consolidado só 2023 com NC 0 / PF 637.870,01 → sem alerta.
  - `test_pf_maior_que_nc_real`: vigência desde 2024-01-10, consolidado 2024 NC 100,00 / PF 200,00 → alerta.
  - `test_nc_sem_ug_um_alerta_por_ted`: TED A com 3 NCs sem UG, TED B com 0 → um alerta `ted:A` citando as 3; nenhum para B.
  - `test_movimentacao_pelo_tesouro`: TED em execução, último PF há 200 dias, pagamento em NE vinculada no mês anterior a `hoje` → sem `ted_sem_movimentacao`.
  - `test_movimentacao_consolidado_sem_documento_na_descricao`: TED em execução sem documento, consolidado com PF no ano de `hoje` → alerta cuja descrição contém "o consolidado indica movimentação".
  - `test_credito_sem_empenho_ted_encerrado`: estado "Comprovado no SIAFI." → descrição termina com "pendência para a prestação de contas."
- [ ] **Step 2:** rodar os arquivos de teste → FAIL nos novos.
- [ ] **Step 3:** Implemente. Testes existentes que fixavam o comportamento antigo ("sem documento" comparado como R$ 0; um alerta de UG por NC) são **atualizados** para a regra nova, com comentário citando a spec; nenhum outro teste pode mudar.
- [ ] **Step 4:** `python -m pytest tests -k teds -q -p no:cacheprovider` → PASS.
- [ ] **Step 5: Commit** `fix: alertas de conciliacao dos TEDs pela janela comum, sem base e um alerta de UG por TED`

---

### Task 2: Reavaliação fecha alertas obsoletos dos tipos revistos

**Files:**
- Modify: `src/teds_lotes.py` (`reavaliar_alertas`, `ResultadoReavaliacaoAlertas`)
- Modify: `src/teds_alertas.py` (fechamento)
- Test: `tests/test_teds_reavaliacao_alertas.py`

**Interfaces:**
- Produces:
  - `TIPOS_REVISTOS_08_10_2026 = frozenset({TIPO_NC_DIVERGE_CONSOLIDADO, TIPO_PF_DIVERGE_CONSOLIDADO, TIPO_PF_MAIOR_QUE_NC, TIPO_NC_UG_EMITENTE_AUSENTE, TIPO_TED_SEM_MOVIMENTACAO})`
  - `candidatos_tipos_revistos(conn, hoje: date | None = None) -> set[tuple[str, str]]` — `(tipo, documento)` que as regras atuais produzem para os tipos revistos, sem gravar.
  - `fechar_alertas_obsoletos(conn, candidatos_atuais: set[tuple[str, str]]) -> dict[str, int]` — fecha (status `resolvido`, `responsavel="sistema"`, `justificativa="Regra revisada em 08/10/2026: " + motivo`, `data_resolucao` agora) cada alerta não resolvido de tipo revisto cujo `(tipo, documento)` não está em `candidatos_atuais`, gravando `registrar_auditoria(acao=ACAO_ALERTA_STATUS_ALTERADO, entidade=ENTIDADE_ALERTA, entidade_id=<id>, valor_anterior=..., valor_novo=..., usuario="sistema", motivo=...)` na mesma transação; devolve contagem por tipo.
  - Motivos: NC/PF diverge → "a comparação passou a usar só o período coberto pelo consolidado; TED sem documento no extrato é 'sem base'"; PF > NC → "TED com vigência anterior ao consolidado é 'sem base'"; NC sem UG → "o alerta passou a ser um por TED"; sem movimentação → "a movimentação passou a incluir liquidação e pagamento no Tesouro".
  - `reavaliar_alertas`: roda as verificações (como hoje), depois `fechar_alertas_obsoletos(conn, candidatos_tipos_revistos(conn))`; `valor_novo` da auditoria da reavaliação ganha `"fechados"` e `"fechados_por_tipo"`; `ResultadoReavaliacaoAlertas` ganha `fechados_por_tipo: dict[str, int]`. A página Importações passa a mostrar também os fechados (ajuste mínimo na mensagem existente).

- [ ] **Step 1: Write the failing tests:**
  - `test_fecha_obsoleto_com_justificativa_e_auditoria`: alerta aberto `pf_liquida_diverge_consolidado` de TED que agora é "sem base" → após `reavaliar_alertas`: `resolvido`, responsável "sistema", justificativa começa com "Regra revisada em 08/10/2026:", 1 registro `alerta_status_alterado` para o id.
  - `test_fecha_alerta_antigo_de_ug_por_nc`: alerta aberto `nc_ug_emitente_ausente` com documento de NC (formato antigo) → fechado; o novo `ted:<chave>` criado.
  - `test_mantem_alerta_ainda_valido`: divergência que continua → aberto.
  - `test_nao_fecha_tipos_nao_revistos`: `ted_credito_sem_empenho` aberto sem candidato → aberto.
  - `test_resolvido_manual_nao_reabre`: resolvido manualmente e regra ainda aponta → nem reabre nem duplica.
  - `test_reavaliacao_idempotente`: segunda execução fecha 0 e cria 0.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implemente.
- [ ] **Step 4:** `python -m pytest tests -k teds -q -p no:cacheprovider` → PASS.
- [ ] **Step 5: Commit** `feat: reavaliacao fecha alertas dos TEDs que as regras revistas nao sustentam`

---

### Task 3: Leitor e conferência da planilha de controle (em memória)

**Files:**
- Create: `src/teds_controle_nc.py`
- Test: `tests/test_teds_controle_nc.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class LinhaControleNc: aba: str; linha_origem: int; nc: str | None; data: date | None; ug_emitente: str | None; orgao: str | None; oficio: str | None; fonte: str | None; ptres: str | None; natureza: str | None; pi: str | None; ted: str | None; transferencia: str | None; valor: Decimal; processo: str | None; observacao: str | None`
  - `@dataclass class ResultadoLeituraControleNc: linhas: list[LinhaControleNc]; rejeitadas: list[tuple[str, int, str]]; abas_ignoradas: list[tuple[str, str]]`
  - `ler_controle_nc(conteudo: bytes) -> ResultadoLeituraControleNc`
  - `@dataclass(frozen=True) class ConferenciaNc: chave_nc_documento: str; chave_ted: str | None; numero_nc: str; situacao: str  # "confere"|"diverge"|"ambigua"|"sem_planilha"; valor_simec: Decimal | None; valor_planilha: Decimal | None; ug_simec: str | None; ug_planilha: str | None`
  - `@dataclass class ConferenciaControle: por_nc: list[ConferenciaNc]; nc_anterior_consolidado: dict[str, list[LinhaControleNc]]  # chave_ted → linhas; sem_ted: list[LinhaControleNc]; leitura: ResultadoLeituraControleNc`
  - `conferir_controle(conn, leitura: ResultadoLeituraControleNc) -> ConferenciaControle` — só lê o banco (`documento_nc`, `ted`, `execucao_anual`).
  - `justificativa_sugerida(alerta_tipo: str, chave_ted: str, conferencia: ConferenciaControle) -> str | None` — texto para os tipos de spec §5.3, citando NC, data, valor e UG da planilha; `None` quando a planilha não tem dado para o TED.
  - `gerar_xlsx_conferencia(conferencia: ConferenciaControle) -> bytes` — abas "Conferência por NC", "NC anterior ao consolidado", "Sem TED", "Não lido".

Leitura: spec §5.1. Ligação planilha → SIMEC: número da NC igual e TED igual (o número do TED é a parte de `chave_ted` antes do `|`); quando ambas têm UG, a UG também precisa bater. Valor da planilha = soma das linhas da NC no mesmo TED; valor SIMEC = `abs(valor_assinado_total)`. Mais de um candidato com UGs diferentes, ou mais de uma NC no SIMEC com o mesmo número no mesmo TED → `ambigua`. "NC anterior ao consolidado": linhas da planilha do TED com `data` anterior a 1º de janeiro do menor `ano_emissao` do TED em `execucao_anual` (ligação planilha → TED pelo número do TED).

- [ ] **Step 1: Write the failing tests** (`.xlsx` mínimo criado em memória com openpyxl):
  - `test_layout_2016_com_continuacao`: cabeçalho `NC | DATA | UG EMITENTE | NOME ÓRGÃO | OFÍCIO | FONTE | PTRES | ND | TED  N.  TRANSFERENCIA | VALOR RECEBIDO | PROCESSO | OBSERVAÇÃO`; `2016NC700145` em 3 linhas (2ª e 3ª só PTRES/ND/valor) → 3 linhas com nc `2016NC700145`, ug `153173`, ted `688033`, valores `Decimal("2400000")`, `Decimal("200000")`, `Decimal("50000")`.
  - `test_layout_2023`: `NC | DATA | UG EMITENTE | OFÍCIO | TED | N.  TRANSFERENCIA | VALOR | PROCESSO | OBSERVAÇÃO`, TED `11926` numérico → `"11926"`, transferência `"1AALOH"`.
  - `test_layout_2026_zero_a_esquerda`: fonte `"1000000000"`, PTRES `"023541"` preservados.
  - `test_traco_vira_nulo`, `test_linha_sem_valor_rejeitada_com_motivo`, `test_aba_nao_reconhecida_listada`.
  - `test_confere_e_diverge`: SIMEC `2023NC000076` TED 11926 R$ 176.562,00 sem UG × planilha mesmo TED, UG 152734, 176562 → `confere`, `ug_planilha="152734"`; outra NC 46.097,73 × 102.600,50 → `diverge`.
  - `test_nc_ambigua_nao_e_comparada`: `2024NC000036` em duas linhas de UGs diferentes no mesmo TED → `ambigua`, sem `ug_planilha`.
  - `test_nc_anterior_ao_consolidado`: TED 11460 com consolidado 2023 e planilha com NC de 2022 de 800.000 → aparece em `nc_anterior_consolidado["11460|..."]`.
  - `test_justificativa_sugerida_pf_maior_que_nc`: contém "Planilha de controle", o número da NC, a data e "R$ 800.000,00".
  - `test_conferir_nao_grava`: contagem de linhas de todas as tabelas igual antes e depois de `conferir_controle`.
  - `test_xlsx_tem_as_abas`: `gerar_xlsx_conferencia` abre com as 4 abas.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implemente.
- [ ] **Step 4:** `python -m pytest tests/test_teds_controle_nc.py -q -p no:cacheprovider` → PASS.
- [ ] **Step 5: Commit** `feat: conferencia em memoria com a planilha de controle de NCs`

---

### Task 4: Seção "Conferir com a planilha de controle" na Conciliação

**Files:**
- Modify: `app_pages/teds_conciliacao.py`
- Test: teste de página da Conciliação existente (ou `tests/test_teds_conciliacao_page.py` novo, no padrão dos testes de página do módulo, com banco temporário)

**Interfaces:**
- Consumes: Task 3 (`ler_controle_nc`, `conferir_controle`, `justificativa_sugerida`, `gerar_xlsx_conferencia`); `teds_ui.atualizar_status_alerta` (existente).

Conteúdo da seção (spec §5): `st.file_uploader` (`.xlsx`); resumo da leitura (linhas, rejeitadas, abas não lidas); contagem por situação e tabela das NCs `diverge`/`ambigua` e das com UG sugerida; tabela "NC anterior ao consolidado" por TED; tabela "Sem TED"; botão de download do Excel; lista dos alertas abertos dos tipos de spec §5.3 com sugestão (`justificativa_sugerida` não nula), cada um com justificativa editável, responsável e botão **Resolver** que chama `atualizar_status_alerta(..., status="resolvido", ...)`. Texto fixo: "A planilha é lida só nesta tela e não é gravada no banco."

- [ ] **Step 1: Write the failing tests:**
  - `test_conferencia_nao_grava_no_banco`: com o upload simulado (estado do widget ou chamando a função de render com bytes de fixture), contagens de todas as tabelas iguais antes e depois.
  - `test_resolver_pela_planilha_grava_status_e_auditoria`: com alerta `pf_liquida_maior_que_nc` aberto e planilha com NC anterior, clicar **Resolver** → alerta `resolvido` com a justificativa sugerida e 1 registro de auditoria.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** Implemente, seguindo o layout das seções existentes da página.
- [ ] **Step 4:** `python -m pytest tests -k teds -q -p no:cacheprovider` → PASS.
- [ ] **Step 5: Commit** `feat: conferencia com a planilha de controle na Conciliacao dos TEDs`

---

### Task 5: Documentação, validação com dados reais e suíte completa

**Files:**
- Modify: `docs/base_teds.md` (regras revistas, fechamento automático, conferência em memória), `README.md` (seção TEDs)

- [ ] **Step 1:** Atualize a documentação.
- [ ] **Step 2:** Validação numa **cópia** de `data/teds/teds.db` (em pasta temporária; o banco real não é tocado): rodar `reavaliar_alertas` e `conferir_controle` com `C:\Users\CPOC - PROPLAD\Downloads\CONTROLE DESC.CREDITOS ATUALIZADA.xlsx`; registrar no relatório: abertos antes/depois por tipo, fechados por tipo, e a conferência por situação. Conferir contra os critérios de sucesso (spec §1).
- [ ] **Step 3:** `python -m pytest tests -q -p no:cacheprovider` (suíte completa, em série).
- [ ] **Step 4: Commit** `docs: TEDs com regras revistas e conferencia com a planilha de controle`
