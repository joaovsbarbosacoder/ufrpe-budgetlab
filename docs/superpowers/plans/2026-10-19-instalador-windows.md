# Instalador Windows do UFRPE BudgetLab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gerar dois instaladores Windows (`BudgetLab-Setup.exe` leve e `BudgetLab-Setup-Completo.exe` com `data/`) que instalam o sistema sem exigir Python, Git ou internet, com atualização opcional pelo GitHub.

**Architecture:** Python embeddable + dependências + código empacotados com Inno Setup, instalados por usuário em `%LOCALAPPDATA%\UFRPE BudgetLab\`. Dados ficam em `dados\`, ligados a `app\data` por junção de diretório, então nenhum módulo de `src/` muda. A lógica testável (atualização e inicialização) fica em Python puro em `scripts/instalador/`; empacotamento em PowerShell + Inno.

**Tech Stack:** Python 3.13 (stdlib: `urllib`, `zipfile`, `subprocess`, `hashlib`, `json`), pytest, PowerShell, Inno Setup 6.

**Spec:** `docs/superpowers/specs/2026-10-19-instalador-windows-design.md`

## Global Constraints

- Instalação por usuário, sem administrador, em `%LOCALAPPDATA%\UFRPE BudgetLab\` com `python\`, `app\`, `dados\` e junção `app\data → dados`.
- Nenhuma alteração em `src/`, `app_pages/`, `app.py` ou nas regras de negócio; nenhuma persistência nova além de `dados\` (a `data/` atual relocada) e `versao.txt`.
- Instalar, atualizar, reinstalar e desinstalar **nunca** substituem `dados\`; o instalador completo só copia o que não existe (`onlyifdoesntexist`); desinstalar pergunta antes de remover `dados\` (padrão: manter).
- Nunca `rmtree`/remoção recursiva em `app\` (a junção levaria `dados\` junto); o desinstalador remove a junção com `rmdir` antes de apagar `app\`.
- Atualização: repositório `joaovsbarbosacoder/ufrpe-budgetlab`, ramo `master`, API pública sem token; tudo ou nada; qualquer falha só avisa e abre a versão instalada; `versao.txt` é gravado por último.
- Streamlit: `--server.headless true --server.port 8501 --browser.gatherUsageStats false`, pasta de trabalho `app\`.
- `dist/` fica fora do Git. Arquivos originais importados nunca são alterados.
- Testes: `python -m pytest tests/<arquivo> -v` nas etapas de cada tarefa; suíte completa ao final com `python -m pytest tests -n 8 --dist loadfile`.

## Review Focus

1. Caminho com espaços e acentos (`CPOC - PROPLAD`, nome de usuário com acento): o comando do Streamlit e o atalho devem funcionar.
2. Porta 8501 ocupada por outro programa: o sistema deve subir em outra porta livre, não falhar mudo.
3. Zip com entrada maliciosa (`..\x`, caminho absoluto): a atualização deve recusar, sem escrever fora de `app\`.
4. Queda de energia/erro no meio da atualização: `versao.txt` não muda e a próxima tentativa recomeça limpa.
5. Instalador completo sobre `dados\` já existente com arquivos mais novos: nada é sobrescrito.

---

### Task 1: Atualizador (`atualizar.py`)

**Files:**
- Create: `scripts/instalador/__init__.py` (vazio)
- Create: `scripts/instalador/atualizar.py`
- Test: `tests/test_instalador_atualizar.py`

**Interfaces:**
- Produces:
  - `REPO = "joaovsbarbosacoder/ufrpe-budgetlab"`, `RAMO = "master"`
  - `ler_versao(app: Path) -> dict` — lê `app/versao.txt` (JSON `{"commit": str, "requirements_sha256": str, "arquivos": list[str]}`); ausente ou inválido → `{"commit": "", "requirements_sha256": "", "arquivos": []}`.
  - `sha_remoto(abrir=urllib.request.urlopen, timeout: float = 5) -> str` — SHA do `master` via `https://api.github.com/repos/{REPO}/commits/{RAMO}` (`Accept: application/vnd.github.sha`); levanta `ErroAtualizacao` em qualquer falha de rede/HTTP.
  - `class ErroAtualizacao(Exception)`
  - `extrair_zip(zip_path: Path, destino: Path) -> list[str]` — extrai para `destino` descartando o diretório raiz do zip do GitHub (`ufrpe-budgetlab-master/`); ignora tudo sob `data/`; recusa (`ErroAtualizacao`) entrada com `..` ou caminho absoluto; devolve a lista de caminhos relativos (com `/`) extraídos.
  - `aplicar(staging: Path, app: Path, versao_antiga: dict) -> list[str]` — copia arquivo a arquivo de `staging` para `app`; remove de `app` só os arquivos listados em `versao_antiga["arquivos"]` que não estão no novo conjunto (nunca algo sob `data`); devolve a lista de arquivos novos.
  - `atualizar(app: Path, python: Path, *, sha=sha_remoto, baixar=baixar_zip, pip=rodar_pip) -> str` — devolve `"sem_novidade"`, `"atualizado"` ou `"falhou"` (nunca levanta); fluxo: compara SHA com `versao.txt`; baixa o zip para pasta temporária; extrai em staging; se o `sha256` do `requirements.txt` novo difere do gravado, chama `pip(python, requirements)` e, se falhar, devolve `"falhou"` sem tocar em `app`; `aplicar`; grava `versao.txt` por último.
  - `baixar_zip(destino: Path, abrir=urllib.request.urlopen, timeout: float = 30) -> None` e `rodar_pip(python: Path, requirements: Path) -> bool` (`python -m pip install --disable-pip-version-check -r requirements`, `True` se código de saída 0).

- [ ] **Step 1: Escrever os testes (falhando)** em `tests/test_instalador_atualizar.py`, com `tmp_path`, zips montados na hora e dependências injetadas (sem rede):
  - `test_sem_novidade_quando_sha_igual`: `versao.txt` com `commit="abc"`, `sha` devolve `"abc"` → `"sem_novidade"`, `baixar` não chamado.
  - `test_atualiza_codigo_e_grava_versao_por_ultimo`: zip com `ufrpe-budgetlab-master/app.py` novo → `app/app.py` atualizado, `versao.txt["commit"]` igual ao novo SHA.
  - `test_data_nunca_extraida_nem_alterada`: `app/data` como junção (via `cmd /c mklink /J`; `pytest.mark.skipif(sys.platform != "win32")`) para `dados/` com `dados/x.json`; zip contém `data/.gitkeep` e `data/x.json` diferente → `dados/x.json` intacto e `.gitkeep` ausente.
  - `test_remove_arquivo_que_sumiu_so_do_codigo`: `versao_antiga["arquivos"]=["old.py"]`, `old.py` existe em `app`, novo zip sem ele → removido; um `app/data/y.json` permanece.
  - `test_zip_malicioso_recusado`: entrada `ufrpe-budgetlab-master/../fora.txt` → `extrair_zip` levanta `ErroAtualizacao`; `atualizar` devolve `"falhou"` e nada fora de `app` é criado.
  - `test_falha_no_pip_mantem_versao_anterior`: `requirements.txt` novo com hash diferente, `pip` devolve `False` → `"falhou"`, `app/app.py` e `versao.txt` inalterados.
  - `test_pip_so_quando_requirements_muda`: hash igual → `pip` não chamado.
  - `test_falha_de_rede_devolve_falhou`: `sha` levanta `ErroAtualizacao` → `"falhou"`.
  - `test_interrupcao_no_meio_nao_grava_versao`: `aplicar` levanta `OSError` no 2º arquivo (monkeypatch de cópia) → `"falhou"`, `versao.txt` original; chamada seguinte com cópia normal → `"atualizado"`.

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_instalador_atualizar.py -v` → falha de importação (`scripts.instalador.atualizar`).

- [ ] **Step 3: Implementar** `scripts/instalador/atualizar.py` com as assinaturas acima. Cópia com `shutil.copy2` arquivo a arquivo; remoção com `Path.unlink` e `rmdir` de pastas vazias, **nunca `shutil.rmtree`**; validar entradas do zip resolvendo cada destino e checando que fica dentro de `destino`.

- [ ] **Step 4: Rodar e ver passar** — `python -m pytest tests/test_instalador_atualizar.py -v` → todos PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/instalador tests/test_instalador_atualizar.py
git commit -m "feat(instalador): atualizador opcional pelo GitHub (tudo ou nada, sem tocar em dados)"
```

---

### Task 2: Inicializador (`iniciar.py`)

**Files:**
- Create: `scripts/instalador/iniciar.py`
- Test: `tests/test_instalador_iniciar.py`

**Interfaces:**
- Consumes: `atualizar(app, python) -> str` da Task 1.
- Produces:
  - `sistema_aberto(porta: int, abrir=urllib.request.urlopen) -> bool` — `True` se `http://localhost:{porta}/_stcore/health` responde 200 em até 2 s.
  - `porta_livre(inicio: int = 8501, fim: int = 8510) -> int` — primeira porta sem listener (`socket.connect_ex != 0`); levanta `RuntimeError` se nenhuma.
  - `comando_streamlit(python: Path, porta: int) -> list[str]` — `[str(python), "-m", "streamlit", "run", "app.py", "--server.headless", "true", "--server.port", str(porta), "--browser.gatherUsageStats", "false"]`.
  - `main() -> int` — raiz = pasta do script subindo 2 níveis (`app\`), `python` = `<raiz>\..\python\python.exe`; chama `atualizar` (mensagem curta do resultado); se `sistema_aberto(8501)` só abre o navegador; senão `porta_livre`, abre o navegador quando a saúde responder (até 90 s, em thread) e executa `comando_streamlit` com `cwd=raiz`; devolve o código de saída.

- [ ] **Step 1: Escrever os testes (falhando)** em `tests/test_instalador_iniciar.py`:
  - `test_sistema_aberto_true_com_200` / `test_sistema_aberto_false_com_erro` (abrir injetado).
  - `test_porta_livre_pula_ocupada`: abrir um socket em 8501 (ou porta efêmera passada como `inicio`) → devolve a seguinte.
  - `test_comando_streamlit_com_caminho_com_espacos_e_acentos`: `python=Path("C:/Users/João Silva/UFRPE BudgetLab/python/python.exe")` → o primeiro item é esse caminho como um único elemento e `--browser.gatherUsageStats` vem seguido de `false`.

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_instalador_iniciar.py -v` → falha de importação.

- [ ] **Step 3: Implementar** `scripts/instalador/iniciar.py`; a lista de argumentos passa direto a `subprocess.run` (sem `shell=True`) para tolerar espaços/acentos.

- [ ] **Step 4: Rodar e ver passar** — `python -m pytest tests/test_instalador_iniciar.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/instalador/iniciar.py tests/test_instalador_iniciar.py
git commit -m "feat(instalador): inicializador com porta livre e abertura do navegador"
```

---

### Task 3: Build e script do Inno Setup

**Files:**
- Create: `scripts/build_instalador.ps1`
- Create: `installer/budgetlab.iss`
- Modify: `.gitignore` (adicionar `dist/` e `build_instalador/`)

**Interfaces:**
- Consumes: `scripts/instalador/iniciar.py` e `atualizar.py` (Tasks 1–2) copiados para `app\scripts\instalador\`.
- Produces: `dist\BudgetLab-Setup.exe` e, com `-ComDados`, `dist\BudgetLab-Setup-Completo.exe`.

- [ ] **Step 1: Pré-requisito** — instalar o Inno Setup 6 na máquina de build (`winget install JRSoftware.InnoSetup`, mediante autorização do usuário) e confirmar `iscc` (`C:\Program Files (x86)\Inno Setup 6\ISCC.exe`).

- [ ] **Step 2: `scripts/build_instalador.ps1 [-ComDados]`** — em `build_instalador\` (limpa a cada execução): (a) baixa o Python embeddable da mesma versão do ambiente de dev (`python -c "import sys"` → `3.13.x`) de python.org, extrai em `python\`, descomenta `import site` em `python313._pth`, instala o pip (`get-pip.py`) e roda `pip install -r requirements.txt`; (b) copia o código de `git ls-files` exceto `data/` e `tests/` para `app\`; (c) grava `app\versao.txt` (JSON: `commit` = `git rev-parse HEAD`, `requirements_sha256`, `arquivos` = lista copiada); (d) chama `ISCC.exe /DComDados=0|1 installer\budgetlab.iss`. O script aborta com mensagem se faltar Inno, internet ou árvore Git.

- [ ] **Step 3: `installer/budgetlab.iss`** — `PrivilegesRequired=lowest`, `DefaultDirName={localappdata}\UFRPE BudgetLab`, `OutputBaseFilename` conforme `ComDados`; `[Files]`: `python\*` e `app\*` (recursivo); com `ComDados`, `data\*` → `{app}\dados` com `Flags: onlyifdoesntexist recursesubdirs createallsubdirs`; `[Dirs]`: `{app}\dados` (e as subpastas de `data/` da variante leve, via lista gerada pelo build); `[Run]` pós-instalação: `cmd /c rmdir "{app}\app\data"` (só se for pasta vazia) seguido de `cmd /c mklink /J "{app}\app\data" "{app}\dados"`; `[Icons]` (menu Iniciar e área de trabalho): `{app}\python\python.exe` com argumentos `-m scripts.instalador.iniciar`, `WorkingDir={app}\app`; `[UninstallRun]`: `cmd /c rmdir "{app}\app\data"` (remove a junção sem seguir) **antes** da remoção de arquivos; `[Code]`: no desinstalador, perguntar se remove `dados\` (padrão Não) e só então apagar.

- [ ] **Step 4: Rodar o build** — `powershell -File scripts/build_instalador.ps1` e depois `-ComDados`. Esperado: `dist\BudgetLab-Setup.exe` e `dist\BudgetLab-Setup-Completo.exe` criados; tamanhos reportados.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_instalador.ps1 installer/budgetlab.iss .gitignore
git commit -m "feat(instalador): build e script Inno Setup (leve e completo)"
```

---

### Task 4: Verificação ponta a ponta e documentação

**Files:**
- Modify: `README.md` (nova seção "Instalação por instalador Windows", ao lado da seção do `Iniciar BudgetLab.bat`)

**Interfaces:**
- Consumes: os dois `.exe` da Task 3.

- [ ] **Step 1: Instalar o leve em pasta limpa** (`/DIR=` de teste ou usuário sem instalação) — o sistema abre, mostra "Início" e a pasta `dados\` existe vazia; `app\data` é junção (`dir /AL`).

- [ ] **Step 2: Cenário 5 do Review Focus** — criar `dados\marcador.txt` com conteúdo novo, instalar o **completo** por cima: `marcador.txt` intacto e os dados do pacote presentes onde não existiam.

- [ ] **Step 3: Atualização** — alterar o `versao.txt` de teste para um `commit` antigo e abrir pelo atalho com internet: mensagem de atualização, sistema abre e `dados\` intacto; repetir sem internet (rede desligada): aviso e abre normalmente.

- [ ] **Step 4: Desinstalar** — manter `dados\` (padrão) e confirmar que sobrou só `dados\`; reinstalar e repetir removendo `dados\`.

- [ ] **Step 5: README** — documentar como gerar (`build_instalador.ps1 [-ComDados]`), o que cada instalador contém, como atualizar/desinstalar e o plano B (zip portátil) como nota de risco.

- [ ] **Step 6: Suíte completa** — `python -m pytest tests -n 8 --dist loadfile` → sem regressões.

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs: instalação por instalador Windows"
```
