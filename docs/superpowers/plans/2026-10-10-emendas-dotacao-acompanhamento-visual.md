# Emendas — decisão de dotação, acompanhamento e novo visual — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir sanear divergências de dotação com decisão registrada, registrar tramitação (status + histórico), objeto e destinatário de cada emenda, e apresentar tudo num registro compacto.

**Architecture:** Dois módulos novos de regra pura + persistência por eventos imutáveis (mesmo padrão de `src/vinculos_emendas.py`): `src/ajustes_dotacao_emendas.py` (etapa 1) e `src/acompanhamento_emendas.py` (etapa 2). A decisão de dotação entra em `vincular_execucao_emendas` por um parâmetro opcional; a página `app_pages/emendas_parlamentares.py` ganha janelas (`@st.dialog`) e, na etapa 3, o registro compacto. O relatório oficial nunca é alterado.

**Tech Stack:** Python 3.14, pandas, Streamlit (`AppTest`), pytest (`python -m pytest ... -p no:cacheprovider`; na pasta do Drive usar no máximo `-n 4`).

**Specs:** `docs/superpowers/specs/2026-10-10-emendas-ajuste-dotacao-design.md` (etapa 1) · `docs/superpowers/specs/2026-10-10-emendas-acompanhamento-e-visual-design.md` (etapas 2 e 3) · maquete `docs/superpowers/specs/2026-10-10-emendas-visual-mockup.html`.

## Global Constraints

- Repositório `G:\Outros computadores\Meu PC\Downloads\ufrpe-budgetlab`, branch `feat/emendas-ajuste-dotacao` (já existe, com as specs). Commits terminam com `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Nada de push/PR/merge sem o usuário pedir.
- Relatório importado, Dotação Anual e execução nunca alterados; transformações em memória; eventos = um JSON imutável por ação, gravação atômica (temporário + `replace`), nunca sobrescreve; arquivo ilegível **levanta erro** (nunca vira "sem eventos").
- Chave do vínculo: `(ano:int, resultado_primario_cod:str, emenda_numero:str, ptres:str)`; chave da emenda: `(ano, resultado_primario_cod, emenda_numero)`. Códigos sempre texto.
- Nulo ≠ zero ≠ vazio: valor informado `0` é válido; vazio/`None` não; texto vazio é gravado como `null`.
- Decisão de dotação só para `ano >= ANO_INICIO_ATUALIZACAO` (2026). Acompanhamento vale para qualquer exercício.
- `responsavel` e `justificativa` obrigatórios onde a spec manda; mínimo de justificativa = 10 caracteres úteis (após `strip`).
- Datas e instantes: `registrado_em` em UTC ISO com fuso; `hoje` é parâmetro nas funções que validam data (testes determinísticos).
- Validação sempre no servidor (módulos `src/`), nunca só na interface.
- Testes de página (`AppTest`) executam só a **primeira** abertura de um `@st.dialog`; confira o conteúdo ao abrir, sem interagir dentro da janela. Páginas leem bases reais (manifestos atuais): seguir o padrão de `tests/test_emendas_parlamentares_page.py` (skip sem manifesto).
- Comunicação e comentários em português, no estilo do módulo.

## Review Focus

- Decisão obsoleta: relatório novo com valor diferente ⇒ decisão **não** aplicada, divergência volta com aviso.
- PTRES com mais de uma emenda no exercício/RP: `adotar_dotacao_anual` recusada no servidor (e não oferecida na janela).
- Evento corrompido (JSON inválido, campo faltando, versão desconhecida) em qualquer dos dois diretórios: erro explícito, não "sem decisões/sem histórico".
- Status atual: desempate por `registrado_em` quando a `data_status` empata; cancelar duas vezes recusado; `data_status` futura recusada, retroativa aceita.
- Complemento: vazio vira `null`; histórico mostra valor anterior → novo; chave de emenda inexistente recusada; evento de emenda que sumiu aparece como órfão.
- Visual: o registro compacto mostra as mesmas emendas e os mesmos totais do cartão atual (com o mesmo filtro); testes antigos presos ao HTML dos cartões são **atualizados**, não apagados.

---

## ETAPA 1 — Decisão registrada sobre divergência de dotação

### Task 1: Núcleo de eventos de decisão — `src/ajustes_dotacao_emendas.py`

**Files:**
- Create: `src/ajustes_dotacao_emendas.py`
- Test: `tests/test_ajustes_dotacao_emendas.py` (unittest, diretório temporário)

**Interfaces:**
- Consumes: `ANO_INICIO_ATUALIZACAO` de `src.emendas_parlamentares`; `vinculos` = `ResultadoVinculoEmendas.vinculos` (colunas `ano`, `resultado_primario_cod`, `emenda_numero`, `ptres`, `dotacao_atualizada`, `dotacao_anual_ptres`, e opcionalmente `dotacao_relatorio`).
- Produces:
  - `class ErroAjusteDotacao(ValueError)`; `DIRETORIO_AJUSTES = Path("data/emendas/ajustes_dotacao")`; `DECISOES = ("adotar_dotacao_anual", "manter_relatorio", "valor_informado")`
  - `registrar_decisao(*, vinculos, ano, resultado_primario_cod, emenda_numero, ptres, decisao, valor_informado, justificativa, responsavel, diretorio=DIRETORIO_AJUSTES) -> dict` (evento gravado, com `decisao_id`, `valor_relatorio`, `valor_dotacao_anual`, `valor_efetivo`)
  - `desfazer_decisao(*, decisao_id, justificativa, responsavel, diretorio=DIRETORIO_AJUSTES) -> dict`
  - `carregar_eventos(diretorio=DIRETORIO_AJUSTES) -> list[dict]`
  - `reconstruir_decisoes(eventos) -> list[dict]` (cada decisão com `desfeita: bool`, `desfeita_motivo`, `desfeita_por`, `desfeita_em`)
  - `ptres_com_uma_emenda(vinculos, ano, resultado_primario_cod, ptres) -> bool`

- [ ] **Step 1: Write the failing tests** (`TestRegistrarDecisao`, fixture `vinculos` sintética de 2 linhas: emenda `E1` PTRES `P1` dotação 300000.0 e anual 600000.0 em 2026; emenda `E2` PTRES `P2` 100000.0/100000.0 em 2026; `P3` compartilhado por `E3` e `E4`, anual 500000.0):
  - `test_adotar_dotacao_anual_grava_evento_com_valores_da_decisao`: `valor_relatorio == 300000.0`, `valor_dotacao_anual == 600000.0`, `valor_efetivo == 600000.0`, arquivo `<evento_id>.json` criado; `reconstruir_decisoes(carregar_eventos(...))` devolve 1 decisão ativa.
  - `test_manter_relatorio_tem_valor_efetivo_igual_ao_do_relatorio` (300000.0).
  - `test_valor_informado_aceita_zero_e_recusa_vazio_e_negativo`: `0.0` ok; `None` e `-1` levantam `ErroAjusteDotacao`.
  - `test_recusa_exercicio_anterior_a_2026`, `test_recusa_chave_inexistente`, `test_recusa_decisao_invalida`.
  - `test_adotar_recusada_quando_o_ptres_tem_mais_de_uma_emenda` (E3/P3) e `test_manter_e_valor_informado_continuam_permitidos_no_ptres_compartilhado`.
  - `test_recusa_justificativa_curta_e_responsavel_vazio` (justificativa `"curta"`, `"   "`; responsável `""`).
  - `test_uma_decisao_ativa_por_chave`: segunda decisão na mesma chave levanta erro pedindo para desfazer a anterior.
  - `test_desfazer_acrescenta_evento_e_nao_apaga_o_original`: 2 arquivos; decisão `desfeita is True` com motivo/por; desfazer de novo e de id inexistente levantam erro.
  - `test_arquivo_de_evento_ilegivel_ou_incompleto_levanta_erro`: JSON inválido, campo `decisao` fora de `DECISOES`, `versao_schema` desconhecida.
  - `test_ptres_com_uma_emenda`: `True` para P1, `False` para P3.
- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_ajustes_dotacao_emendas.py -q -p no:cacheprovider`. Expected: ImportError.
- [ ] **Step 3: Implement** o módulo seguindo `_novo_evento`/`_salvar_evento`/`carregar_eventos_vinculo` de `src/vinculos_emendas.py` (evento `versao_schema: 1`, `acao` ∈ {`decidir`,`desfazer`}). `registrar_decisao` localiza a linha em `vinculos` (valor original = `dotacao_relatorio` se a coluna existir, senão `dotacao_atualizada`); `adotar_dotacao_anual` exige `dotacao_anual_ptres` não nulo e `ptres_com_uma_emenda`; carrega eventos antes de gravar para checar "uma ativa por chave".
- [ ] **Step 4: Run to verify pass.** Expected: PASS.
- [ ] **Step 5: Commit** — `git add src/ajustes_dotacao_emendas.py tests/test_ajustes_dotacao_emendas.py` · `feat: eventos de decisao sobre divergencia de dotacao de Emendas`.

### Task 2: Aplicar decisões na composição — `aplicar_decisoes` e `vincular_execucao_emendas`

**Files:**
- Modify: `src/ajustes_dotacao_emendas.py` (`aplicar_decisoes`), `src/emendas_parlamentares.py` (`vincular_execucao_emendas`, `divergencias_dotacao`, `_resumir_emendas_vinculadas`)
- Test: `tests/test_ajustes_dotacao_emendas.py` (classe `TestAplicarDecisoes`), `tests/test_emendas_parlamentares.py` (não regressão)

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `aplicar_decisoes(vinculos, decisoes) -> pd.DataFrame` — acrescenta `dotacao_relatorio` (Float64, original), `dotacao_decisao` (string), `dotacao_decisao_id` (string), `dotacao_decisao_estado` (`"ativa"`, `"obsoleta"`, `"sem_efeito"` ou nulo), `dotacao_divergencia_pendente` (bool); substitui `dotacao_atualizada` só nas decisões `ativa`; recalcula `diferenca_dotacao` e `dotacao_divergente` com a dotação efetiva. Regras: **obsoleta** = relatório atual ≠ `valor_relatorio` da decisão (±0,01) → não aplicada, divergência continua pendente; **sem_efeito** = não obsoleta e Dotação Anual igual ao relatório atual (divergência inexistente); **ativa** = demais (inclui `manter_relatorio`: valor não muda, `dotacao_divergencia_pendente = False`). Decisão `desfeita` é ignorada.
  - `vincular_execucao_emendas(relatorio, execucao, ano_inicio_atualizacao=..., dotacao=None, decisoes_dotacao=None)`; sem `decisoes_dotacao` o resultado é **idêntico** ao atual (inclui sem as colunas novas).
  - `divergencias_dotacao(vinculos)` devolve só as pendentes (e as obsoletas) com a coluna `dotacao_decisao_estado` quando existir.
  - `emendas` (resumo) ganha `dotacao_relatorio` (soma) e `dotacao_divergencia_pendente` (`any`) quando as colunas existirem.

- [ ] **Step 1: Write the failing tests:**
  - `test_adotar_muda_dotacao_atualizada_e_preserva_o_original`: caso do usuário (E1: 300000 × 600000, `adotar`) ⇒ `dotacao_atualizada == 600000.0`, `dotacao_relatorio == 300000.0`, `dotacao_decisao_estado == "ativa"`, `dotacao_divergencia_pendente` falso, `diferenca_dotacao == 0.0`; resumo por emenda com dotação 600000.0.
  - `test_manter_nao_muda_valor_mas_encerra_o_alerta`: dotação 300000.0, `dotacao_divergente` verdadeiro, `dotacao_divergencia_pendente` falso, `divergencias_dotacao(...)` vazio.
  - `test_valor_informado_zero_vira_dotacao_zero_e_nao_nula`.
  - `test_decisao_obsoleta_nao_e_aplicada_quando_o_relatorio_muda`: decisão gravada com relatório 300000; relatório novo 450000 ⇒ estado `obsoleta`, dotação 450000.0, divergência pendente e listada em `divergencias_dotacao` com o estado.
  - `test_sem_efeito_quando_o_relatorio_passa_a_igualar_a_dotacao_anual` (relatório novo 600000).
  - `test_decisao_desfeita_e_ignorada`.
  - `test_sem_decisoes_o_resultado_e_identico_ao_atual`: `vincular_execucao_emendas(..., decisoes_dotacao=None)` e `=[]` iguais ao chamado sem o parâmetro (`pd.testing.assert_frame_equal` em `emendas` e `vinculos`), sem colunas novas.
  - Em `tests/test_emendas_parlamentares.py`: o teste existente de divergência continua passando sem alteração.
- [ ] **Step 2: Run to verify failure.** Expected: FAIL/ImportError.
- [ ] **Step 3: Implement.** Em `vincular_execucao_emendas`, chamar `aplicar_decisoes` logo depois de `_acrescentar_dotacao_anual` e antes do cálculo das medidas executadas; `_resumir_emendas_vinculadas` só agrega as colunas novas quando presentes (mesmo padrão do bloco de `dotacao_anual_ptres`). Nulo nunca vira zero na comparação (`tem_ambos`).
- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_ajustes_dotacao_emendas.py tests/test_emendas_parlamentares.py tests/test_vinculos_emendas.py -q -p no:cacheprovider`. Expected: PASS.
- [ ] **Step 5: Commit** — `feat: decisoes de dotacao aplicadas na composicao de Emendas`.

### Task 3: Tela — "Resolver", janela e "Decisões de dotação"

**Files:**
- Modify: `app_pages/emendas_parlamentares.py` (carregar eventos e decisões; passar `decisoes_dotacao`; quadro de divergências com "Resolver"; `_dialogo_resolver_divergencia`; seção "Decisões de dotação"; marca no cartão)
- Test: `tests/test_emendas_parlamentares_page.py`

**Interfaces:**
- Consumes: `carregar_eventos`, `reconstruir_decisoes`, `registrar_decisao`, `desfazer_decisao`, `ptres_com_uma_emenda`, `ErroAjusteDotacao`.
- Produces: `_dialogo_resolver_divergencia(linha_divergencia: pd.Series, vinculos: pd.DataFrame) -> None`; botões com `key` `em_resolver_<ano>_<rp>_<emenda>_<ptres>`; seção com botões `em_desfazer_<decisao_id>`.

- [ ] **Step 1: Write the failing tests** (substituir/atualizar `test_divergencia_de_dotacao_e_listada_com_os_dois_valores_sem_apontar_o_correto`, mantendo a verificação dos dois valores; `ajustes_dotacao_emendas.DIRETORIO_AJUSTES` trocado por diretório temporário via `patch`):
  - quadro mostra os dois valores **e** um botão "Resolver" por divergência pendente;
  - abrir "Resolver" mostra relatório, Dotação Anual, diferença, as três opções (a de adotar só quando o PTRES não é compartilhado), campos de justificativa e responsável, e **não grava** nada (diretório continua vazio);
  - com uma decisão já gravada (evento criado por `registrar_decisao` no diretório temporário): o quadro de pendentes some para essa emenda, o cartão mostra "dotação decidida" e o valor original do relatório, a seção "Decisões de dotação" lista a decisão com responsável/justificativa/data e traz "Desfazer"; o total "Dotação atualizada" reflete o valor decidido;
  - evento corrompido no diretório ⇒ a página mostra erro explícito (`st.error`) e não quebra com exceção.
- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_emendas_parlamentares_page.py -q -p no:cacheprovider`. Expected: FAIL.
- [ ] **Step 3: Implement.** Carregar eventos dentro do mesmo `try` da composição (acrescentar `ErroAjusteDotacao` ao `except`); "Resolver" abre `@st.dialog`; confirmar chama `registrar_decisao` (e, para "alterar", `desfazer_decisao` + `registrar_decisao`), mostra `st.toast` e `st.rerun()`. A janela não oferece `adotar` quando `ptres_com_uma_emenda` é falso e exibe o motivo.
- [ ] **Step 4: Run to verify pass.** Conferir a tela real com `preview_start` (porta livre): caso da emenda `202642780018` (300 mil × 600 mil), **sem clicar em registrar** na base real.
- [ ] **Step 5: Commit** — `feat: tela de Emendas resolve divergencia de dotacao com decisao registrada`.

---

## ETAPA 2 — Acompanhamento (tramitação, objeto, destinatário)

### Task 4: Núcleo — `src/acompanhamento_emendas.py`

**Files:**
- Create: `src/acompanhamento_emendas.py`
- Test: `tests/test_acompanhamento_emendas.py` (unittest, diretório temporário)

**Interfaces:**
- Produces:
  - `class ErroAcompanhamento(ValueError)`; `DIRETORIO_ACOMPANHAMENTO = Path("data/emendas/acompanhamento")`
  - `STATUS_SUGERIDOS = ("Indicada", "Recebida pela UFRPE", "Em análise técnica", "Impedimento técnico", "Proposta aceita", "Empenhada", "Liquidada", "Paga", "Concluída", "Cancelada")`; `STATUS_OUTRO = "Outro"`
  - `registrar_status(*, chave, status, status_outro, data_status, observacao, responsavel, chaves_validas, hoje=None, diretorio=DIRETORIO_ACOMPANHAMENTO) -> dict` — `chave = (ano:int, rp:str, emenda_numero:str)`; `chaves_validas: set[tuple]`
  - `cancelar_status(*, evento_id, motivo, responsavel, diretorio=...) -> dict`
  - `definir_complemento(*, chave, objeto, destinatario, responsavel, motivo, chaves_validas, diretorio=...) -> dict` (objeto ≤ 500 e destinatário ≤ 200 caracteres; vazio/espaços → `None`)
  - `carregar_eventos(diretorio=...) -> list[dict]`
  - `reconstruir_tramitacao(eventos) -> pd.DataFrame` (colunas `evento_id`, `ano`, `resultado_primario_cod`, `emenda_numero`, `status` (texto final: `status_outro` quando "Outro"), `data_status`, `observacao`, `responsavel`, `registrado_em`, `cancelado`, `cancelado_motivo`, `cancelado_por`) em ordem cronológica
  - `status_atual(tramitacao) -> pd.DataFrame` (uma linha por chave; registros cancelados ignorados)
  - `complemento_vigente(eventos) -> pd.DataFrame` (`ano`, `resultado_primario_cod`, `emenda_numero`, `objeto`, `destinatario`, `responsavel`, `registrado_em`); `historico_complemento(eventos, chave) -> pd.DataFrame` (valor anterior → novo)
  - `orfaos(eventos, chaves_validas) -> list[dict]`

- [ ] **Step 1: Write the failing tests:**
  - `test_status_da_lista_e_outro_com_texto`: "Em análise técnica" ok; "Outro" sem `status_outro` ou com 2 caracteres levanta; `status_outro` ignorado quando o status não é "Outro"; status fora da lista (sem ser "Outro") levanta.
  - `test_data_futura_recusada_e_retroativa_aceita` (`hoje=date(2026,10,10)`: `2026-10-11` recusada; `2026-08-12` aceita).
  - `test_responsavel_obrigatorio_e_observacao_limitada_a_500`.
  - `test_chave_inexistente_recusada`.
  - `test_status_atual_e_o_de_maior_data_e_desempata_por_registro`: "Em análise técnica" (12/08/2026) depois "Proposta aceita" (01/09/2026) ⇒ atual "Proposta aceita", histórico com os dois em ordem; dois com a mesma `data_status` ⇒ vale o registrado por último.
  - `test_cancelar_mantem_original_e_remove_do_status_atual`: arquivo original intacto (conteúdo igual), `cancelado is True`, status atual volta ao anterior; cancelar de novo e id inexistente levantam; motivo obrigatório.
  - `test_complemento_define_atualiza_e_registra_historico`: objeto/destinatário gravados; segundo evento troca só o objeto (destinatário preservado no retrato); histórico lista anterior → novo; texto vazio vira `None`; mais de 500/200 caracteres levanta.
  - `test_orfaos_listados_quando_a_chave_some`.
  - `test_arquivo_ilegivel_ou_incompleto_levanta_erro`.
- [ ] **Step 2: Run to verify failure.** Expected: ImportError.
- [ ] **Step 3: Implement** no padrão de eventos imutáveis (ações `registrar_status`, `cancelar_status`, `definir_complemento`; `versao_schema: 1`; gravação atômica; `data_status` em ISO `AAAA-MM-DD`).
- [ ] **Step 4: Run to verify pass.** Expected: PASS.
- [ ] **Step 5: Commit** — `feat: acompanhamento de emendas (tramitacao, objeto e destinatario) por eventos`.

### Task 5: Tela — seção "Acompanhamento"

**Files:**
- Modify: `app_pages/emendas_parlamentares.py` (carga dos eventos; seção no cartão; `_dialogo_registrar_status`, `_dialogo_cancelar_status`, `_dialogo_editar_complemento`; órfãos; campos opcionais objeto/destinatário em `_dialog_cadastro_manual`)
- Test: `tests/test_emendas_parlamentares_page.py`

**Interfaces:**
- Consumes: Task 4; chaves válidas = `{(ano, rp, emenda_numero)}` de `resultado.emendas`.
- Produces: botões `em_status_<ano>_<rp>_<emenda>`, `em_complemento_<ano>_<rp>_<emenda>`, `em_cancelar_status_<evento_id>`.

- [ ] **Step 1: Write the failing tests** (diretório de acompanhamento temporário; eventos criados com `registrar_status`/`definir_complemento`):
  - cartão mostra o status atual e a data; histórico lista os registros em ordem, com o cancelado riscado;
  - objeto e destinatário aparecem; emenda sem complemento mostra "não informado";
  - as janelas "Registrar status" e "Editar objeto/destinatário" abrem com os campos esperados (lista de status + "Outro", data, observação, responsável) sem gravar;
  - evento órfão aparece em "Registros sem emenda correspondente";
  - evento corrompido ⇒ erro explícito sem exceção;
  - `_dialog_cadastro_manual` tem os campos opcionais de objeto e destinatário.
- [ ] **Step 2: Run to verify failure.** Expected: FAIL.
- [ ] **Step 3: Implement.** Seção "Acompanhamento" dentro do cartão atual (será reaproveitada no detalhe do registro na Task 6); confirmação chama as funções da Task 4 e `st.rerun()`.
- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_emendas_parlamentares_page.py tests/test_acompanhamento_emendas.py -q -p no:cacheprovider`; conferir na tela real **sem registrar nada**.
- [ ] **Step 5: Commit** — `feat: tela de Emendas registra tramitacao, objeto e destinatario`.

---

## ETAPA 3 — Novo visual

### Task 6: Registro compacto, filtros e painel de pendências

**Files:**
- Modify: `app_pages/emendas_parlamentares.py` (registro compacto; filtro de exercício com padrão 2026+; filtro e coluna de tramitação; painel de pendências no topo; cores; tabela por PTRES só quando >1); reaproveitar `src/ui_cadastro.py` (padrão de Contratos Contínuos) e `src/design_tokens.py`
- Test: `tests/test_emendas_parlamentares_page.py`

**Interfaces:**
- Consumes: Tasks 3 e 5; `resultado.emendas`, `resultado.vinculos`, `status_atual`, `complemento_vigente`.
- Produces: registro com linhas de chave `em_linha_<ano>_<rp>_<emenda>`; expansão por emenda com PTRES, acompanhamento e decisão; filtro `emendas_filtro_status`.

- [ ] **Step 1: Write the failing tests** (atualizar os testes presos ao HTML dos cartões, sem apagar o que verificam):
  - **mesmos dados**: com o filtro "Todos", o registro compacto lista as mesmas emendas e os mesmos totais (dotação, empenhado, liquidado, pago) que o cartão antigo mostrava (valores esperados lidos da base de teste/manifesto, não digitados);
  - abre filtrado em 2026+ e o rótulo/legenda informa quantas emendas do histórico estão ocultas; "Todos" e "Histórico" funcionam;
  - totais do topo respeitam o filtro;
  - painel de pendências no topo com "Resolver" (decisão de dotação) e órfãos quando houver;
  - "Aguardando execução" sem a classe de erro; classe de erro só para problema real (divergência pendente, órfão);
  - coluna e filtro de Tramitação (status atual); emenda sem status mostra "—";
  - emenda com um PTRES não mostra a tabela interna repetida; com vários, mostra;
  - expansão mostra PTRES, acompanhamento e decisão.
- [ ] **Step 2: Run to verify failure.** Expected: FAIL.
- [ ] **Step 3: Implement.** Sem mudança de regra de negócio: mesma composição, só apresentação. Conferir visualmente com `preview_start` (largura de desktop) e comparar com a maquete.
- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_emendas_parlamentares_page.py tests/test_cadastros_layout_page.py -q -p no:cacheprovider`.
- [ ] **Step 5: Commit** — `feat: novo visual de Emendas (registro compacto, exercicio 2026+ por padrao, pendencias)`.

### Task 7: Documentação e suíte completa

**Files:**
- Modify: `README.md` (seção Emendas Parlamentares: decisão de dotação, acompanhamento, novo visual, limites e dúvidas), `docs/base_emendas_acompanhamento.md` (acrescentar §9 "Decisão de dotação e acompanhamento manual": diretórios de eventos, regras, estados da decisão)

- [ ] **Step 1:** Atualizar README e `docs/base_emendas_acompanhamento.md` (incluir as dúvidas: sem ordem entre status, responsável sem login, lista de status a validar com a área, PTRES compartilhado).
- [ ] **Step 2: Run full suite** — `python -m pytest tests -n 4 -q -p no:cacheprovider`. Expected: tudo PASS; registrar totais.
- [ ] **Step 3: Commit** — `docs: decisao de dotacao, acompanhamento e novo visual de Emendas`.

---

## Self-Review

- **Cobertura:** etapa 1 = Tasks 1–3 (spec de dotação: três decisões, justificativa/responsável, evento imutável, uma ativa por chave, obsolescência, PTRES compartilhado, aplicação nas contas, quadro/janela/seção/marca); etapa 2 = Tasks 4–5 (status com lista + "Outro", data, histórico, cancelamento, objeto/destinatário com histórico, órfãos, cadastro manual com campos opcionais); etapa 3 = Task 6 (registro compacto, 2026+ por padrão, pendências, cores, tramitação, PTRES único); documentação/suíte = Task 7.
- **Tipos:** chave de emenda `(int, str, str)` nos dois módulos e na página; `valor_*` em float/`Float64`; decisões e eventos como `dict`/`DataFrame` conforme os Interfaces; nomes `dotacao_decisao_estado` e `dotacao_divergencia_pendente` iguais nas Tasks 2, 3 e 6.
- **Riscos abertos:** os testes de página existentes estão presos ao HTML dos cartões (Task 6 os atualiza); a comparação por emenda contra a Dotação Anual do PTRES inteiro continua podendo dar falsa divergência com PTRES compartilhado (fora de escopo); `AppTest` só alcança a primeira abertura dos diálogos, então confirmar/desfazer é coberto nos módulos (Tasks 1 e 4) e conferido à mão na tela real, sem gravar na base real.
