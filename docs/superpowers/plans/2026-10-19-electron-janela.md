# Janela própria (Electron) do BudgetLab instalado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O sistema instalado abre em janela própria (Electron), sem navegador e sem janela preta, com o Streamlit escutando só em `127.0.0.1`.

**Architecture:** Runtime oficial do Electron (sem Node/npm) dentro do instalador Inno atual. Um `main.js` pequeno atualiza (opcional), sobe o Streamlit escondido, espera ficar pronto e abre a janela; a lógica testável fica em `electron/lib.js`, testada pelo próprio Electron em modo Node.

**Tech Stack:** Electron (win32-x64, versão fixada), JavaScript (`node:test`), Python 3.13/pytest, PowerShell, Inno Setup 6.

**Spec:** `docs/superpowers/specs/2026-10-19-electron-janela-design.md` (estende `2026-10-19-instalador-windows-design.md`).

## Global Constraints

- Streamlit sempre com `--server.address 127.0.0.1`; a janela carrega sempre `http://127.0.0.1:<porta>`, nunca `localhost`.
- `nodeIntegration: false`, `contextIsolation: true`, `sandbox: true`, sem `preload`.
- Navegação restrita à origem `http://127.0.0.1:<porta>`; URLs `http:`/`https:` externas abrem em `shell.openExternal`; qualquer outro esquema é bloqueado.
- Ao fechar a janela, encerrar o Streamlit e seus filhos (`taskkill /PID <pid> /T /F`); nenhum `python.exe` pode ficar vivo.
- Instância única (`requestSingleInstanceLock`); tempo limite de 60 s na atualização; espera de até 120 s pela saúde (`/_stcore/health`, a cada 500 ms); até 3 tentativas de porta.
- Log de início em `%LOCALAPPDATA%\UFRPE BudgetLab\log\inicio.txt`, regravado a cada abertura.
- Electron: `.zip` oficial win32-x64 com versão estável fixada em uma constante e **SHA-256 conferido** contra o `SHASUMS256.txt` da mesma versão; build aborta se divergir. Sem Node/npm.
- Nenhuma alteração em `src/`, `app_pages/`, `app.py`; dados em `dados\` nunca tocados (regras do instalador atual continuam).
- Testes: `python -m pytest tests/<arquivo> -v`; suíte completa ao final: `python -m pytest tests -n 8 --dist loadfile`.

## Review Focus

1. Caminho de instalação com espaço e acento (`C:\bl Ação\...`): `spawn` do Python/Streamlit deve receber o caminho como argumento único.
2. Streamlit cai antes de ficar pronto (porta ocupada, erro de import): a janela mostra o erro com as últimas linhas e o caminho do log, não fica em "Iniciando..." para sempre.
3. Usuário fecha a janela durante o carregamento ou durante a atualização: o processo da atualização e o do Streamlit também são encerrados.
4. Segunda abertura enquanto a primeira ainda está carregando: só foca/mostra a janela existente, sem iniciar outro servidor.
5. Link externo e `window.open` para outro host, `file:` e `javascript:`: nunca carregam dentro da janela.

---

### Task 1: Lado Python — `atualizar_cli.py` e `--server.address`

**Files:**
- Create: `scripts/instalador/atualizar_cli.py`
- Modify: `scripts/instalador/iniciar.py` (função `comando_streamlit`)
- Test: `tests/test_instalador_atualizar_cli.py`, `tests/test_instalador_iniciar.py`

**Interfaces:**
- Consumes: `atualizar(app: Path, python: Path, *, sha, baixar, pip) -> str` de `scripts/instalador/atualizar.py`.
- Produces: `atualizar_cli.main(argv: list[str] | None = None, atualizar_fn=atualizar) -> int` — `argv = [app, python]`; imprime exatamente `sem_novidade`, `atualizado` ou `falhou` (uma linha) e devolve sempre `0` (falha de atualização nunca impede abrir); sem argumentos devolve `2`. Executável por script (`python scripts\instalador\atualizar_cli.py <app> <python>`), com a raiz do app no `sys.path` como em `iniciar.py`.

- [ ] **Step 1: Escrever os testes (falhando)**
  - `test_atualizar_cli_imprime_resultado_e_sai_zero[sem_novidade|atualizado|falhou]` (`capsys`, `atualizar_fn` simulado): saída é o resultado e `main(["app","py"]) == 0`.
  - `test_atualizar_cli_sem_argumentos_devolve_2`.
  - `test_atualizar_cli_funciona_por_script_sem_cwd_no_sys_path`: `python -I scripts/instalador/atualizar_cli.py` sem argumentos devolve `2` (prova que a importação de `scripts.*` funciona como script).
  - em `test_instalador_iniciar.py`: `test_comando_streamlit_escuta_so_em_127_0_0_1` — `cmd[cmd.index("--server.address") + 1] == "127.0.0.1"`.

- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_instalador_atualizar_cli.py tests/test_instalador_iniciar.py -v` → FAIL (módulo inexistente / argumento ausente).

- [ ] **Step 3: Implementar** `atualizar_cli.py` (sys.path na raiz no topo, `main` conforme Interfaces) e acrescentar `"--server.address", "127.0.0.1"` ao `comando_streamlit` de `iniciar.py`.

- [ ] **Step 4: Rodar e ver passar** — mesmo comando → PASS; suíte do instalador: `python -m pytest tests/test_instalador_atualizar.py tests/test_instalador_iniciar.py tests/test_instalador_atualizar_cli.py -q` → sem falhas.

- [ ] **Step 5: Commit** — `git add scripts/instalador tests && git commit -m "feat(instalador): atualizar_cli e Streamlit só em 127.0.0.1"`.

---

### Task 2: Runtime do Electron e `lib.js` (funções puras testadas)

**Files:**
- Create: `scripts/electron_runtime.ps1`, `electron/lib.js`, `electron/lib.test.js`, `electron/package.json`
- Modify: `.gitignore` (adicionar `build_instalador/` já existe; acrescentar `electron/node_modules/` por precaução)

**Interfaces:**
- Produces:
  - `scripts/electron_runtime.ps1`: constante `$ElectronVersao` (versão estável mais recente no momento da implementação, obtida em `https://api.github.com/repos/electron/electron/releases/latest`) e função `Obter-Electron -Destino <pasta>` que baixa `electron-v<versão>-win32-x64.zip` e `SHASUMS256.txt` da release oficial no GitHub, **confere o SHA-256**, aborta se divergir, extrai em `Destino` e renomeia `electron.exe` para `UFRPE BudgetLab.exe`. Cache do zip em `build_instalador\cache\`.
  - `electron/lib.js` (CommonJS, exporta): `comandoStreamlit(python: string, porta: number) -> { cmd: string, args: string[] }` com `args = ["-m","streamlit","run","app.py","--server.headless","true","--server.address","127.0.0.1","--server.port",String(porta),"--browser.gatherUsageStats","false"]`; `urlApp(porta) -> "http://127.0.0.1:<porta>"`; `urlSaude(porta) -> urlApp(porta)+"/_stcore/health"`; `urlPermitida(url: string, porta: number) -> boolean` (só origem `http://127.0.0.1:<porta>`); `ultimasLinhas(texto: string, n: number) -> string`; `escolherPorta() -> Promise<number>` (escuta em `127.0.0.1:0`, lê a porta, fecha); `caminhos(resourcesPath: string, env?: object) -> { raiz, python, app, log }` (raiz = dois níveis acima de `resourcesPath`, ou `env.BUDGETLAB_RAIZ` se definido; `python = raiz\python\python.exe`; `app = raiz\app`; `log = raiz\log\inicio.txt`); `esperarSaude(porta: number, { tentativas = 240, intervaloMs = 500, buscar = fetch }) -> Promise<boolean>`.
  - `electron/package.json`: `{ "name": "ufrpe-budgetlab", "version": "1.0.0", "main": "main.js" }`.

- [ ] **Step 1: Obter o runtime** — escrever `electron_runtime.ps1`, fixar `$ElectronVersao`, rodar `Obter-Electron -Destino build_instalador\electron-teste`. Expected: pasta com `UFRPE BudgetLab.exe`; rodar com SHA adulterado (variável de teste) aborta com mensagem. Confirmar `& "build_instalador\electron-teste\UFRPE BudgetLab.exe" --version` com `ELECTRON_RUN_AS_NODE=1` imprime a versão do Node embutido.

- [ ] **Step 2: Escrever `electron/lib.test.js` (falhando)** com `node:test` e `assert`:
  - `comandoStreamlit("C:/Users/João Silva/UFRPE BudgetLab/python/python.exe", 8503)`: `cmd` igual ao caminho inteiro (um único elemento), `args` contém `--server.address` seguido de `127.0.0.1` e `--server.port` seguido de `"8503"`.
  - `urlPermitida("http://127.0.0.1:8503/x", 8503) === true`; `false` para `http://localhost:8503`, `http://127.0.0.1:8504`, `https://127.0.0.1:8503`, `https://exemplo.com`, `file:///C:/x`, `javascript:alert(1)`, string inválida.
  - `ultimasLinhas("a\nb\nc\nd", 2) === "c\nd"`; texto vazio → `""`.
  - `escolherPorta()` devolve inteiro entre 1024 e 65535 e a porta está livre em seguida.
  - `caminhos("C:/x/UFRPE BudgetLab/electron/resources", {})`: `raiz` termina em `UFRPE BudgetLab`, `python` termina em `python\python.exe`; com `{BUDGETLAB_RAIZ:"D:/dev"}` a raiz é `D:\dev`.
  - `esperarSaude` com `buscar` simulado que falha 2 vezes e depois responde `{ok:true}` → `true`; sempre falhando com `tentativas=3` → `false`.

- [ ] **Step 3: Rodar e ver falhar** — `$env:ELECTRON_RUN_AS_NODE=1; & "build_instalador\electron-teste\UFRPE BudgetLab.exe" --test electron\lib.test.js` → FAIL (módulo `./lib` inexistente).

- [ ] **Step 4: Implementar `electron/lib.js`** com as assinaturas acima (`net` para a porta, `URL` para `urlPermitida`, `path.win32` para `caminhos`).

- [ ] **Step 5: Rodar e ver passar** — mesmo comando → todos PASS.

- [ ] **Step 6: Commit** — `git add scripts/electron_runtime.ps1 electron .gitignore && git commit -m "feat(electron): runtime verificado por SHA-256 e lib.js testado"`.

---

### Task 3: `main.js`, tela de carregamento e página de erro

**Files:**
- Create: `electron/main.js`, `electron/carregando.html`, `electron/erro.html`

**Interfaces:**
- Consumes: `electron/lib.js` (Task 2), `atualizar_cli.py` (Task 1).
- Produces: aplicativo Electron executável com `BUDGETLAB_RAIZ` apontando para uma raiz com `python\` e `app\` (instalação ou, em desenvolvimento, uma pasta de teste).

- [ ] **Step 1: Implementar `main.js`** conforme a spec (seção "Comportamento do `main.js`"): instância única (segunda abertura chama `mostrar()`/`focus()` na janela existente); `BrowserWindow` com `webPreferences: { nodeIntegration:false, contextIsolation:true, sandbox:true }`, `carregando.html` imediato; atualização via `spawn(python, [app\scripts\instalador\atualizar_cli.py, app, python])` com `timeout` de 60 s e `windowsHide`; `escolherPorta` + `spawn(comandoStreamlit(...))` com `cwd: app`, `windowsHide: true`, saída acumulada em memória e gravada em `caminhos().log`; `esperarSaude` e então `loadURL(urlApp(porta))`; `will-navigate`/`setWindowOpenHandler` usando `urlPermitida` e `shell.openExternal` só para `http:`/`https:`; `will-download` com o diálogo padrão de salvar; ao `close`/`window-all-closed`/`before-quit` matar a atualização e o Streamlit com `taskkill /PID <pid> /T /F` e `app.quit()`; se o Streamlit sair antes de ficar pronto ou a espera esgotar, carregar `erro.html` com `ultimasLinhas(saida, 20)` e o caminho do log (até 3 tentativas com porta nova antes de mostrar o erro).
  - `carregando.html`: texto "Iniciando o UFRPE BudgetLab..." sem scripts externos; `erro.html`: título "Não foi possível iniciar", área `<pre>` preenchida via `executeJavaScript`/query string codificada e o caminho do log.

- [ ] **Step 2: Fumaça em desenvolvimento** — com `build_instalador\electron-teste` (Task 2) e uma raiz de teste contendo `python\` (o Python embutido gerado pelo build atual) e `app\` (cópia do repositório com `data\` apontando para dados de teste): `$env:BUDGETLAB_RAIZ="<raiz>"; & "build_instalador\electron-teste\UFRPE BudgetLab.exe" electron`. Expected: janela própria abre no "Início" do sistema, sem janela preta e sem navegador; `Get-NetTCPConnection -State Listen` mostra o Streamlit só em `127.0.0.1`; ao fechar a janela, nenhum `python.exe` da raiz de teste continua vivo (`Get-CimInstance Win32_Process`).

- [ ] **Step 3: Cenários do Review Focus** (manuais, na mesma raiz de teste): (a) quebrar `app.py` de propósito → a janela mostra a página de erro com as últimas linhas e o caminho do log; (b) abrir uma segunda vez durante o carregamento → só uma janela, um servidor; (c) fechar a janela enquanto carrega → nenhum processo órfão; (d) clicar num link externo → abre no navegador padrão e a janela não navega; restaurar o `app.py`.

- [ ] **Step 4: Commit** — `git add electron && git commit -m "feat(electron): janela própria com Streamlit local e encerramento limpo"`.

---

### Task 4: Build e instalador Inno com o Electron

**Files:**
- Modify: `scripts/build_instalador.ps1`, `installer/budgetlab.iss`

**Interfaces:**
- Consumes: `Obter-Electron` (Task 2), `electron/*` (Task 3).
- Produces: `dist\BudgetLab-Setup.exe` e `dist\BudgetLab-Setup-Completo.exe` cujos atalhos abrem `{app}\electron\UFRPE BudgetLab.exe`.

- [ ] **Step 1: `build_instalador.ps1`** — importar `scripts\electron_runtime.ps1`; após montar `python\` e `app\`, chamar `Obter-Electron -Destino build_instalador\electron`, copiar `electron\{package.json,main.js,lib.js,carregando.html,erro.html}` para `build_instalador\electron\resources\app\` (sem `lib.test.js`) e remover `resources\default_app.asar` se existir.

- [ ] **Step 2: `budgetlab.iss`** — `[Files]`: `Source: "{#Build}\electron\*"; DestDir: "{app}\electron"` (mesmas flags de `python\*`); `[Dirs]`: `{app}\log`; `[Icons]` (menu Iniciar e área de trabalho) e `[Run]` "Abrir agora": `Filename: "{app}\electron\UFRPE BudgetLab.exe"` sem parâmetros, `WorkingDir: "{app}"`; `[UninstallRun]`: antes do `rmdir` da junção, `taskkill /IM "UFRPE BudgetLab.exe" /T /F` (`runhidden`, ignorando erro se não estiver aberto); `[UninstallDelete]`: acrescentar `{app}\electron` e `{app}\log`.

- [ ] **Step 3: Compilar** — `powershell -File scripts\build_instalador.ps1` e depois `-ComDados`. Expected: os dois `.exe` em `dist\`, tamanhos reportados (leve ≈ 150–190 MB).

- [ ] **Step 4: Commit** — `git add scripts/build_instalador.ps1 installer/budgetlab.iss && git commit -m "feat(instalador): Electron dentro do instalador Inno"`.

---

### Task 5: Verificação ponta a ponta e documentação

**Files:**
- Modify: `README.md` (seção "Instalador Windows": janela própria, como fechar, manutenção da versão do Electron, plano B)

- [ ] **Step 1: Instalar o leve** em pasta nova com espaço e acento (`/DIR="C:\bl Ação"`, `/VERYSILENT /NOICONS`) e abrir `C:\bl Ação\electron\UFRPE BudgetLab.exe`. Expected: janela própria no "Início"; `Get-NetTCPConnection` confirma escuta só em `127.0.0.1`; log em `C:\bl Ação\log\inicio.txt`.
- [ ] **Step 2: Uso real** — navegar por duas páginas, gerar e baixar um relatório (PDF ou Excel): o diálogo de salvar aparece e o arquivo é gravado onde o usuário escolher.
- [ ] **Step 3: Fechar** — fechar a janela: `Get-Process` mostra nenhum `UFRPE BudgetLab.exe` nem `python.exe` da pasta de teste.
- [ ] **Step 4: Instalar o completo por cima** com um arquivo do usuário já em `dados\` e desinstalar mantendo `dados\` (regras do instalador atual continuam valendo: arquivos preservados, junção removida, só `dados\` sobra).
- [ ] **Step 5: README** — atualizar a seção conforme o escopo acima.
- [ ] **Step 6: Suíte completa** — `python -m pytest tests -n 8 --dist loadfile` → sem regressões; testes JS: `ELECTRON_RUN_AS_NODE=1 ... --test electron\lib.test.js` → PASS.
- [ ] **Step 7: Commit** — `git add README.md && git commit -m "docs: janela própria (Electron) no instalador Windows"`.
