# Cadastro de Contratos (Contratos.gov.br) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Página nova "Contratos" com um cadastro dos contratos da UG 153165 alimentado pela API pública do Contratos.gov.br — fotografia versionada, atualização incremental com prévia/delta, complementos manuais.

**Architecture:** Cliente HTTP isolado → extração monta uma fotografia JSON completa (respostas cruas da API) e o delta contra a anterior → gravação imutável com `Manifesto` de `importacao_versionada` → funções puras derivam as tabelas `contratos`/`termos`/`empenhos` em memória → página Streamlit. Complementos manuais num JSON próprio, nunca tocado pela atualização.

**Tech Stack:** Python, pandas, requests (já em `requirements.txt`), Streamlit, pytest (+xdist/testmon), `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-10-08-contratosgov-cadastro-design.md` (layout: `...-contratosgov-cadastro-mockup.html`). Leia os dois antes de começar.

## Global Constraints

- Somente leitura na API: GET em `https://contratos.comprasnet.gov.br/api/contrato/ug/{ug}`, `/api/contrato/inativo/ug/{ug}`, `/api/contrato/{id}/historico`, `/api/contrato/{id}/empenhos`. Nenhuma rota `/api/v1`.
- UG fixa `"153165"`; só itens com `tipo == "Contrato"`.
- Códigos (id, número, UG, gestão, NE, CNPJ/CPF, fonte, natureza, PI) sempre `str`; zeros iniciais preservados.
- Valores monetários → `Decimal`; `None`/`""` → nulo (nunca zero); texto não conversível → `ErroDadoContratosGov` citando `contrato_id`, endpoint e campo.
- Vigência calculada pelas datas, com data de referência como parâmetro; `situacao` da API guardada como veio.
- Nenhum arquivo escrito fora de `data/raw/contratosgov/`, `data/manifestos/` e `data/contratos/`. Não importar nem alterar `contratos_continuos*`, `contratos_vigencia`, `necessidade_empenho`, `relatorio_reforco_empenho`.
- Nenhum teste acessa a rede.
- Nunca `st.data_editor` dentro de `st.dialog`.
- Testes: rodadas intermediárias `python -m pytest tests --testmon -n auto`; ao final `python -m pytest tests -n auto` (uma suíte por vez — ver `tests/conftest.py`).
- `app.py` e `README.md` têm alterações não commitadas de outro trabalho. Antes de editá-los (Tasks 5 e 6), rode `git diff --stat app.py README.md`; se houver alteração alheia, **pare e pergunte ao usuário** como proceder — nunca inclua mudanças alheias num commit.
- Commits só com os arquivos da task (`git add <arquivos>`), mensagem em português, terminando com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Mesmo `id` nas listas de ativos e de inativos** — esperado: `ErroDadoContratosGov` explícito, não duplicar nem escolher em silêncio (teste na Task 2).
2. **Contrato que sai da lista ativa e entra na de inativos entre duas consultas** — esperado: aparece no delta como alterado (situação), não como "ausente" + "novo" (teste na Task 4).
3. **Valor com sinal negativo ou sem milhar (`"-1.234,56"`, `"500,00"`) e valor `"0,00"`** — esperado: `Decimal("-1234.56")`, `Decimal("500.00")`, `Decimal("0.00")` ≠ nulo (teste na Task 2).
4. **Falha de rede no meio dos detalhes (ex.: 30º contrato)** — esperado: nenhuma fotografia/manifesto gravado, a anterior continua atual (teste na Task 4).
5. **Complementos de um contrato que deixou de existir na API** — esperado: preservados e listados como "ausente na última consulta" (teste na Task 3; exibição na Task 5).

---

### Task 1: Cliente HTTP do Contratos.gov.br

**Files:**
- Create: `src/contratosgov_api.py`
- Test: `tests/test_contratosgov_api.py`

**Interfaces:**
- Produces:
  - `URL_BASE = "https://contratos.comprasnet.gov.br"`
  - `class ErroApiContratosGov(RuntimeError)` com atributos `url: str`, `status: int | None`
  - `class ClienteContratosGov(sessao: requests.Session | None = None, *, timeout: float = 30, tentativas: int = 3, pausa_base: float = 2.0, pausa_entre_chamadas: float = 0.2, dormir: Callable[[float], None] = time.sleep)`
    - `get_json(caminho: str) -> list | dict`
    - `contratos_ug(ug: str) -> list[dict]`, `contratos_inativos_ug(ug: str) -> list[dict]`, `historico(contrato_id: str) -> list[dict]`, `empenhos(contrato_id: str) -> list[dict]`
    - `chamadas: int` (contador, usado no progresso/relatório)

- [ ] **Step 1: Escrever os testes que falham** (sessão falsa via `unittest.mock.Mock` com `.get` devolvendo respostas com `status_code`, `json()`, `headers`; `dormir` registra as pausas numa lista):
  - `test_get_json_monta_url_e_devolve_json`: `contratos_ug("153165")` chama `GET https://contratos.comprasnet.gov.br/api/contrato/ug/153165` com `timeout=30` e devolve a lista.
  - `test_rotas_dos_quatro_metodos`: inativos → `/api/contrato/inativo/ug/153165`; `historico("1004328")` → `/api/contrato/1004328/historico`; `empenhos` análogo.
  - `test_repete_em_5xx_e_depois_sucede`: 503, 503, 200 → devolve o JSON; `chamadas == 3`; pausas crescentes `[2.0, 4.0]` (além das pausas entre chamadas, que o teste filtra ou zera com `pausa_entre_chamadas=0`).
  - `test_aborta_apos_esgotar_tentativas`: 4 × 500 → `ErroApiContratosGov` com `status == 500` e a URL na mensagem; exatamente 4 chamadas (1 + 3 novas tentativas).
  - `test_429_respeita_retry_after`: 429 com `Retry-After: 7`, depois 200 → pausa de 7.0 registrada.
  - `test_4xx_aborta_sem_repetir`: 404 → `ErroApiContratosGov(status=404)` após 1 chamada.
  - `test_timeout_e_erro_de_conexao_repetem`: `requests.Timeout` duas vezes, depois 200 → sucesso; quatro `requests.ConnectionError` → `ErroApiContratosGov(status=None)`.
  - `test_json_invalido_aborta`: 200 com `json()` levantando `ValueError` → `ErroApiContratosGov`.

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_contratosgov_api.py -v` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar `src/contratosgov_api.py`** — docstring de módulo no estilo do projeto (camada, origem, decisões). Pausa de nova tentativa = `pausa_base * 2**(n-1)`; em 429 usa `Retry-After` numérico se houver. `pausa_entre_chamadas` antes de cada chamada após a primeira. Sem regra de negócio, sem conversão de valores.

- [ ] **Step 4: Rodar e ver passar** — mesmo comando → PASS.

- [ ] **Step 5: Commit** — `git add src/contratosgov_api.py tests/test_contratosgov_api.py` · `feat: cliente HTTP somente leitura do Contratos.gov.br`.

---

### Task 2: Fixture congelada e tabelas derivadas (`contratos_cadastro`)

**Files:**
- Create: `tests/fixtures/contratosgov_2026-10-08.json`
- Create: `src/contratos_cadastro.py`
- Test: `tests/test_contratos_cadastro.py`

**Interfaces:**
- Consumes: `ClienteContratosGov` (Task 1), só para gerar a fixture (script descartável no scratchpad, não versionado).
- Produces:
  - Formato da fotografia (spec §5): `{"versao_formato": 1, "consultado_em": str ISO, "ug": "153165", "lista_ativos": [...], "lista_inativos": [...], "detalhes": {"<id>": {"historico": [...], "empenhos": [...], "consultado_em": str, "origem": "consulta" | "reaproveitado:<sha256[:12]>"}}}` — `lista_*` já filtradas a `tipo == "Contrato"`.
  - `class ErroDadoContratosGov(ValueError)`
  - `valor_brl(texto: str | None, *, contrato_id: str, endpoint: str, campo: str) -> Decimal | None`
  - `data_iso(texto: str | None, *, contrato_id: str, endpoint: str, campo: str) -> date | None`
  - `situacao_vigencia(inicio: date | None, fim: date | None, inativo: bool, referencia: date) -> str` — `"inativo"` | `"sem_vigencia"` | `"a_iniciar"` | `"vigente"` | `"encerrado"` (nessa precedência)
  - `montar_contratos(fotografia: dict, referencia: date) -> pd.DataFrame` — colunas da spec §4.1
  - `montar_termos(fotografia: dict) -> pd.DataFrame`, `montar_empenhos(fotografia: dict) -> pd.DataFrame`
  - `resumo(contratos: pd.DataFrame) -> dict` com chaves `total`, `ativos_api`, `inativos_api`, `vigentes`, `vencem_90` (vigentes com `dias_para_vencer <= 90`), `valor_global_vigentes: Decimal`
  - `SITUACOES = ("vigente", "a_iniciar", "encerrado", "inativo", "sem_vigencia")`

- [ ] **Step 1: Gerar a fixture.** Script em scratchpad usando `ClienteContratosGov`: baixar as duas listas da UG 153165, escolher **6 contratos** — `id 1004328` (00013/2026, vigente, 2 NEs), o contrato `00021/2017` (6 termos, apostilamento com novo valor global `"10.354.305,17"`), um encerrado com NE, um da lista de inativos, um vigente sem NE e um de pessoa física — e montar a fotografia no formato acima com `consultado_em = "2026-10-08T09:42:00"` e `origem = "consulta"`. **Substituir todo CPF de pessoa física** (`cnpj_cpf_idgener`, e o CPF dentro de `credor`/`credor_obj`/`usuario` se houver) por `"000.000.001-91"`; nomes de PF por `"PESSOA FÍSICA FICTÍCIA"`. Gravar com `json.dump(..., ensure_ascii=False, indent=1, sort_keys=True)`. Conferir à mão e anotar no docstring de `tests/test_contratos_cadastro.py`: ids escolhidos, quantos termos/NEs cada um tem, valor global de cada um, situação esperada com referência `date(2026, 10, 8)` e o total `valor_global_vigentes`.

- [ ] **Step 2: Escrever os testes que falham** (`REF = date(2026, 10, 8)`; fixture carregada com `json.load`):
  - `test_valor_brl`: `"830.906,44"→Decimal("830906.44")`, `"500,00"→Decimal("500.00")`, `"-1.234,56"→Decimal("-1234.56")`, `"0,00"→Decimal("0.00")` (e `is not None`), `None→None`, `""→None`; `"1.2x3,00"` e `"1234.56"` → `ErroDadoContratosGov` cuja mensagem contém o `contrato_id` e o `campo`.
  - `test_data_iso`: `"2026-09-10"→date(2026,9,10)`, `None`/`""→None`, `"10/09/2026"` → erro.
  - `test_situacao_vigencia`: um caso por saída, incluindo `inicio == referencia` e `fim == referencia` → `"vigente"`, e inativo com datas vigentes → `"inativo"`.
  - `test_contrato_vigente_00013_2026`: linha com `contrato_id == "1004328"`: `numero == "00013/2026"`, `ano_contrato == 2026`, `fornecedor_documento == "05340639000130"`, `valor_global == Decimal("830906.44")`, `situacao_vigencia == "vigente"`, `dias_para_vencer == 337`, `qtd_empenhos == 2`, `inativo_api is False`.
  - `test_empenhos_reconstroem_ne_completa`: para `1004328` existe `ne_ccor == "153165152392026NE000522"` com `ne == "2026NE000522"`, `ug == "153165"`, `gestao == "15239"`.
  - `test_termos_do_00021_2017`: 6 termos ordenados por `data_assinatura`; o primeiro é `tipo == "Contrato"`; o apostilamento tem `novo_valor_global == Decimal("10354305.17")`.
  - `test_inativo_e_pessoa_fisica`: o contrato da lista de inativos tem `situacao_vigencia == "inativo"`; o de PF tem `fornecedor_documento == "00000000191"`.
  - `test_resumo_confere_com_anotacao_manual`: valores do docstring.
  - `test_mesmo_id_em_ativos_e_inativos_e_erro`: fotografia mínima montada no teste com o mesmo `id` nas duas listas → `ErroDadoContratosGov`.
  - `test_campo_obrigatorio_ausente_e_erro`: item sem `vigencia_fim` **key** → erro citando o campo (valor `null` é aceito e vira nulo/`sem_vigencia`).
  - `test_numero_fora_do_padrao_tem_ano_nulo`: `numero = "ABC-12"` → `ano_contrato` nulo, `numero` preservado.

- [ ] **Step 3: Rodar e ver falhar** — `python -m pytest tests/test_contratos_cadastro.py -v` → FAIL.

- [ ] **Step 4: Implementar `src/contratos_cadastro.py`** — funções puras, sem I/O. `valor_brl` aceita só `^-?\d{1,3}(\.\d{3})*,\d{2}$` ou `^-?\d+,\d{2}$`. Campos obrigatórios na lista: `id, numero, tipo, fornecedor, vigencia_inicio, vigencia_fim, valor_global` (chave presente); nos detalhes: `numero, unidade_gestora, gestao` (empenhos) e `id, tipo, data_assinatura` (historico). `retroativo_periodo` = `"MM/AAAA–MM/AAAA"` a partir de `retroativo_mesref_de/anoref_de/mesref_ate/anoref_ate` quando todos presentes. Colunas monetárias com dtype `object` (Decimal).

- [ ] **Step 5: Rodar e ver passar** — mesmo comando → PASS.

- [ ] **Step 6: Commit** — `git add src/contratos_cadastro.py tests/test_contratos_cadastro.py tests/fixtures/contratosgov_2026-10-08.json` · `feat: tabelas do cadastro de contratos a partir da fotografia do Contratos.gov.br`.

---

### Task 3: Complementos manuais

**Files:**
- Create: `src/contratos_complementos.py`
- Create: `data/contratos/.gitkeep`
- Modify: `.gitignore` (acrescentar `data/contratos/*` e `!data/contratos/.gitkeep`, junto do bloco de `data/contratos_continuos/`)
- Test: `tests/test_contratos_complementos.py`

**Interfaces:**
- Produces:
  - `CAMINHO_PADRAO = Path("data/contratos/complementos.json")`
  - `@dataclass(frozen=True) class Complemento: contrato_id: str; valor_mensal: Decimal | None; observacoes: str; alterado_em: str`
  - `carregar_complementos(caminho: str | Path | None = None) -> dict[str, Complemento]` — arquivo inexistente → `{}`; ilegível/malformado → `ValueError` com o caminho.
  - `salvar_complemento(contrato_id: str, valor_mensal: str, observacoes: str, *, caminho: str | Path | None = None, agora: datetime | None = None) -> Complemento` — `valor_mensal` em texto BR (`"862.858,76"`, `"862858,76"`) ou vazio (→ nulo); mais de 2 casas, negativo ou texto inválido → `ValueError`. Gravação atômica (temporário + `replace`, como `src/limite_empenho_remanejamentos.py:_gravar`). Formato: `{"versao_formato": 1, "complementos": {"<id>": {"valor_mensal": "862858.76" | null, "observacoes": str, "alterado_em": ISO}}}`.
  - `complementos_ausentes(complementos: dict[str, Complemento], ids_atuais: set[str]) -> list[Complemento]`

- [ ] **Step 1: Testes que falham** (`tmp_path`):
  - `test_ida_e_volta`: salvar `("18940", "862.858,76", "Repactuação")` e recarregar → `Decimal("862858.76")`, mesmas observações, `alterado_em` = `agora.isoformat()`.
  - `test_vazio_e_nulo_e_zero_e_zero`: `""` → `None`; `"0,00"` → `Decimal("0.00")`.
  - `test_rejeita_invalidos`: `"1,234"`, `"-5,00"`, `"abc"` → `ValueError`; arquivo não é criado/alterado.
  - `test_outro_contrato_preservado`: salvar dois ids; regravar o primeiro não altera o segundo.
  - `test_arquivo_ilegivel_e_erro`: arquivo com `"{quebrado"` → `ValueError` contendo o caminho.
  - `test_gravacao_atomica_nao_deixa_temporario`: após salvar, nenhum `*.tmp` no diretório.
  - `test_complementos_ausentes`: ids `{"1","2"}` salvos, atuais `{"1"}` → devolve só o `"2"`.

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_contratos_complementos.py -v` → FAIL.

- [ ] **Step 3: Implementar** o módulo, o `.gitkeep` e o `.gitignore`.

- [ ] **Step 4: Rodar e ver passar**; conferir `git check-ignore data/contratos/complementos.json` → listado.

- [ ] **Step 5: Commit** — `git add src/contratos_complementos.py tests/test_contratos_complementos.py data/contratos/.gitkeep .gitignore` · `feat: complementos manuais do cadastro de contratos`.

---

### Task 4: Extração, delta e gravação versionada

**Files:**
- Create: `src/contratosgov_extracao.py`
- Test: `tests/test_contratosgov_extracao.py`

**Interfaces:**
- Consumes: `ClienteContratosGov` (Task 1); `situacao_vigencia`, `data_iso`, `valor_brl`, `montar_contratos`, `montar_termos`, `montar_empenhos`, `resumo` (Task 2); `Manifesto`, `destino_sem_sobrescrever`, `historico`, `DIRETORIO_MANIFESTOS_PADRAO` de `src/importacao_versionada.py`.
- Produces:
  - `BASE = "contratosgov"`, `UG_UFRPE = "153165"`, `DIRETORIO_FOTOGRAFIAS = Path("data/raw/contratosgov")`, `DIRETORIO_MANIFESTOS = DIRETORIO_MANIFESTOS_PADRAO` (atributos de módulo lidos em tempo de chamada, para a página e os testes poderem trocá-los)
  - `class FotografiaAusente(FileNotFoundError)`, `class ConfirmacaoNecessaria(RuntimeError)`
  - `carregar_atual(dir_manifestos: Path | None = None, dir_fotografias: Path | None = None) -> tuple[dict | None, Manifesto | None]`
  - `consultar(cliente, anterior: dict | None, *, referencia: date, agora: datetime, completa: bool = False, progresso: Callable[[int, int], None] | None = None) -> dict` — devolve a fotografia nova (formato da Task 2); qualquer `ErroApiContratosGov` propaga (nada parcial é devolvido).
  - `@dataclass class Delta` com listas de dicts: `contratos_novos`, `contratos_ausentes`, `termos_novos`, `termos_removidos`, `vigencia_alterada` (`contrato_id, numero, antes, depois`), `valor_global_alterado` (idem), `situacao_alterada` (idem; `inativo_api`), `nes_novas`, `nes_removidas`; `nes_movimentadas: int`; métodos `exige_confirmacao() -> bool` (há qualquer item em `contratos_ausentes`, `termos_removidos` ou `nes_removidas`) e `contagens() -> dict[str, int]` (chaves `delta_<campo>`)
  - `calcular_delta(anterior: dict | None, nova: dict) -> Delta`
  - `gravar(nova: dict, delta: Delta, *, ciente_remocao: bool = False, importado_em: datetime, referencia: date, dir_manifestos: Path | None = None, dir_fotografias: Path | None = None) -> Manifesto`
  - `historico_atualizacoes(dir_manifestos: Path | None = None) -> list[Manifesto]` (mais recente primeiro)

Política de `consultar` (spec §5): para cada item das listas novas, consultar detalhe se `completa`, ou se `id` não está em `anterior`, ou se `situacao_vigencia(...)` com `referencia` é `"vigente"`/`"a_iniciar"`, ou se o item da lista difere do item anterior (comparação de dicts **sem** a chave `links`) ou mudou de lista (ativo↔inativo). Senão copiar `anterior["detalhes"][id]` trocando `origem` para `"reaproveitado:<sha12 da anterior>"` (manter a origem existente se já era reaproveitado — a origem aponta para a fotografia onde o detalhe foi realmente consultado). O sha12 da anterior vem de `anterior["_sha256"][:12]`, chave que `carregar_atual` injeta ao ler (e que `gravar` remove antes de serializar).

Gravação: `conteudo = json.dumps(nova, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")`; `sha256` do conteúdo; nome `f"contratosgov_{sha[:12]}.json"`; `destino_sem_sobrescrever`; `Manifesto(base=BASE, arquivo=<nome final>, sha256, data_extracao=nova["consultado_em"], importado_em=..., anos=[], totais={"valor_global_vigentes": float(...)}, totais_por_ano={}, contagens={contratos, vigentes, termos, empenhos, reconsultados, reaproveitados} | delta.contagens())`; `manifesto.salvar(dir_manifestos)`. Se `delta.exige_confirmacao()` e não `ciente_remocao` → `ConfirmacaoNecessaria` **antes** de escrever qualquer arquivo.

- [ ] **Step 1: Testes que falham** — cliente falso (classe no teste) que serve listas/detalhes a partir de um dict de fotografia e registra as chamadas; `anterior` = fixture da Task 2 com `_sha256` injetado; `REF = date(2026, 10, 8)`.
  - `test_primeira_carga_consulta_todos`: `anterior=None` → detalhe consultado para os 6; todas as origens `"consulta"`.
  - `test_incremental_reconsulta_so_vigentes_novos_e_alterados`: sem mudanças na API → só os vigentes/a iniciar da fixture são reconsultados; encerrado e inativo com origem `"reaproveitado:<sha12>"`.
  - `test_encerrado_com_lista_alterada_e_reconsultado`: mudar `valor_global` do encerrado na API → reconsultado.
  - `test_completa_reconsulta_todos`.
  - `test_falha_no_meio_propaga_e_nao_grava`: cliente falha no 3º detalhe → `ErroApiContratosGov`; `tmp_path` sem fotografia nem manifesto.
  - `test_delta_categorias`: a partir da fixture, construir `nova` com 1 contrato novo, 1 termo novo, vigência alterada, valor global alterado, 1 NE nova, 1 NE com `pago` diferente → cada lista com 1 item e `nes_movimentadas == 1`; `exige_confirmacao() is False`.
  - `test_remocoes_exigem_confirmacao`: remover 1 NE de um contrato → `nes_removidas` com o `ne_ccor`; `gravar(...)` sem `ciente_remocao` → `ConfirmacaoNecessaria` e nada escrito; com `ciente_remocao=True` → grava.
  - `test_ativo_que_vira_inativo_e_situacao_alterada`: mover um item da lista ativa para a inativa → em `situacao_alterada`, não em `contratos_ausentes`/`contratos_novos`.
  - `test_gravar_e_carregar_atual`: grava; `carregar_atual` devolve fotografia igual à gravada (fora `_sha256`) e o manifesto com `base == "contratosgov"`, contagens e `totais["valor_global_vigentes"]` conferindo com `resumo`.
  - `test_gravar_duas_vezes_nao_sobrescreve`: duas fotografias diferentes → dois arquivos; `historico_atualizacoes` com 2 itens, mais recente primeiro.
  - `test_manifesto_aponta_arquivo_inexistente`: apagar a fotografia → `carregar_atual` levanta `FotografiaAusente`.
  - `test_so_escreve_nos_diretorios_previstos`: após `gravar` com `dir_*` em `tmp_path`, os únicos arquivos novos em `tmp_path` estão nesses dois diretórios.

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_contratosgov_extracao.py -v` → FAIL.

- [ ] **Step 3: Implementar `src/contratosgov_extracao.py`.** Delta por chaves: contratos por `id`; termos por `(contrato_id, termo_id)`; NEs por `(contrato_id, ne_ccor)`; "movimentada" = algum de `empenhado, aliquidar, liquidado, pago, rpinscrito, rpaliquidar, rpliquidado, rppago` diferente.

- [ ] **Step 4: Rodar e ver passar**; depois `python -m pytest tests --testmon -n auto`.

- [ ] **Step 5: Commit** — `git add src/contratosgov_extracao.py tests/test_contratosgov_extracao.py` · `feat: atualização incremental e versionada do cadastro de contratos`.

---

### Task 5: Página "Contratos"

**Files:**
- Create: `app_pages/contratos.py`
- Modify: `app.py` (grupo `"Contratos"`, primeiro item: `st.Page("app_pages/contratos.py", title="Contratos", icon="📑")`) — ver restrição global sobre alterações alheias.
- Test: `tests/test_contratos_page.py`

**Interfaces:**
- Consumes: Tasks 1–4. Lê `contratosgov_extracao.DIRETORIO_*` e `contratos_complementos.CAMINHO_PADRAO` em tempo de execução (os testes trocam esses atributos com `monkeypatch`).

Layout conforme spec §4.0 e o protótipo. Reaproveitar `src/ui_cadastro.py` (`cartao_resumo`, `chip`, `celula_principal`, `celula_categoria`, `celula_valor`, `formatar_brl`, `tabela_html`) e `src/ui_theme.py` como as páginas de cadastro existentes. Abas com `st.tabs(["Cadastro", "Atualizar", "Histórico de atualizações"])`. Detalhe em `st.dialog` com `st.text_input`/`st.text_area` + botão "Salvar complemento" (erro de validação mostrado com `st.error`, sem gravar). Atualizar: botão "Consultar agora" (ou "Fazer primeira carga" sem fotografia) + `st.checkbox("Atualização completa…")`; fotografia nova e delta em `st.session_state` até gravar/descartar; `st.progress` via `progresso`; alerta de remoção com `st.checkbox("Estou ciente da remoção")` habilitando "Gravar fotografia"; `ErroApiContratosGov` → `st.error` com a URL e a frase "A fotografia anterior continua valendo." Chips de dias: verde > 90, laranja 31–90, vermelho ≤ 30. Complementos ausentes listados num `st.expander("Complementos de contratos ausentes na última consulta")`.

- [ ] **Step 1: Testes que falham** (`AppTest.from_file("app_pages/contratos.py", default_timeout=TEMPO_LIMITE_APPTEST)`, `gc` já tratado no `conftest`):
  - `test_sem_fotografia_mostra_primeira_carga`: diretórios vazios em `tmp_path` → existe botão "Fazer primeira carga"; nenhuma exceção.
  - `test_com_fotografia_mostra_resumo_e_lista`: gravar a fixture via `gravar(...)` em `tmp_path` → a página contém `"00013/2026"` e o número de vigentes anotado na Task 2; nenhuma exceção.
  - `test_historico_lista_manifesto`: a aba de histórico mostra o hash curto da fotografia gravada.
  - `test_nao_chama_a_rede_ao_abrir`: `monkeypatch` de `requests.Session.get` para levantar `AssertionError` → a página abre sem exceção.

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_contratos_page.py -v` → FAIL.

- [ ] **Step 3: Implementar a página e registrar em `app.py`.**

- [ ] **Step 4: Rodar e ver passar**; abrir o app e conferir visualmente contra o protótipo (com a fixture copiada para um diretório temporário — **não** gravar em `data/` real sem o usuário pedir a primeira carga).

- [ ] **Step 5: Commit** — `git add app_pages/contratos.py tests/test_contratos_page.py app.py` · `feat: página Contratos com cadastro do Contratos.gov.br`.

---

### Task 6: Documentação e suíte completa

**Files:**
- Modify: `README.md` (seção "Contratos (Contratos.gov.br)": fonte, recorte, atualização incremental, complementos, arquivos gravados) — ver restrição global.
- Create: `docs/contratosgov.md` (endpoints usados, formato da fotografia, política incremental, regras de conversão, como atualizar a fixture deliberadamente — mesmo texto-guia do `AGENTS.md` para fixtures)

- [ ] **Step 1: Escrever a documentação.**
- [ ] **Step 2: Suíte completa** — `python -m pytest tests -n auto` → todos passam (sem outra suíte rodando em paralelo). Em especial, nenhum teste de `contratos_continuos`, `necessidade_empenho`, `relatorio_reforco_empenho` ou `contratos_vigencia` muda de resultado.
- [ ] **Step 3: Commit** — `git add README.md docs/contratosgov.md` · `docs: cadastro de contratos do Contratos.gov.br`.
