# Janela própria (Electron) para o BudgetLab instalado — design

Data: 19/10/2026 · Status: aguardando revisão do usuário.
Estende `2026-10-19-instalador-windows-design.md` (instalador Inno Setup).

## Objetivo

O sistema instalado deixa de abrir em aba do navegador e passa a abrir em uma
**janela própria** (sem barra de endereço nem abas, ícone na barra de tarefas), sem
a janela preta do inicializador. Por trás continua o Streamlit local, agora
escutando **somente em `127.0.0.1`**.

Decisões do usuário (19/10/2026): empacotar em Electron; **somente** a janela
(login/senha do INLABS dentro do sistema fica para outro subprojeto); Electron
**dentro do instalador Inno atual** (não trocar para electron-builder/NSIS).

Fora do escopo: credenciais do INLABS no sistema, assinatura digital do `.exe`,
mudanças em `src/`, `app_pages/` e `app.py`, instalador para outros sistemas,
bandeja do sistema/execução em segundo plano.

## Estrutura instalada (acréscimo)

```
%LOCALAPPDATA%\UFRPE BudgetLab\
  electron\                 runtime oficial do Electron (win32-x64), exe renomeado
    UFRPE BudgetLab.exe
    resources\app\          package.json, main.js, lib.js, carregando.html
  python\  app\  dados\     (inalterados; app\data → dados continua)
```

Os atalhos (menu Iniciar e área de trabalho) e a opção "Abrir agora" do
instalador passam a abrir `electron\UFRPE BudgetLab.exe`. `iniciar.py` e
`Iniciar BudgetLab.bat` permanecem para uso pelo repositório.

## Comportamento do `main.js`

1. **Instância única:** `app.requestSingleInstanceLock()`; uma segunda abertura só
   foca a janela existente.
2. **Janela imediata:** mostra `carregando.html` ("Iniciando o UFRPE BudgetLab...")
   logo ao abrir, sem tela em branco.
3. **Atualização opcional:** executa
   `python\python.exe scripts\instalador\atualizar_cli.py` (novo, fino, sobre
   `atualizar.atualizar`; imprime `sem_novidade|atualizado|falhou` e sai com 0),
   com tempo limite de 60 s; qualquer falha ou tempo esgotado só segue adiante.
4. **Servidor:** escolhe porta livre (escuta em `127.0.0.1:0`, lê a porta e
   fecha) e inicia `python\python.exe -m streamlit run app.py --server.headless
   true --server.address 127.0.0.1 --server.port <porta> --browser.gatherUsageStats
   false`, com `cwd` em `app\` e `windowsHide: true`.
5. **Pronto:** consulta `http://127.0.0.1:<porta>/_stcore/health` a cada 500 ms (até
   120 s) e então carrega `http://127.0.0.1:<porta>` na janela (sempre
   `127.0.0.1`, nunca `localhost`).
6. **Encerrar:** ao fechar a janela (ou `window-all-closed`), encerra o Streamlit
   **e seus filhos** (`taskkill /PID <pid> /T /F`) e sai. Nenhum `python.exe` deve
   ficar vivo.
7. **Falha:** se o Streamlit sair antes de ficar pronto ou o tempo esgotar, a
   janela mostra uma página de erro com as últimas linhas da saída do servidor e o
   caminho do arquivo de log (`%LOCALAPPDATA%\UFRPE BudgetLab\log\inicio.txt`,
   regravado a cada abertura, sem dados do sistema).

## Segurança

- `nodeIntegration: false`, `contextIsolation: true`, `sandbox: true`, sem
  `preload`: a página não acessa Node nem o computador.
- Navegação restrita à origem `http://127.0.0.1:<porta>`; qualquer outra URL é
  bloqueada na janela e aberta no navegador padrão (`shell.openExternal`, só para
  `https:`/`http:`). `window.open` segue a mesma regra.
- Streamlit só em `127.0.0.1` (corrige a escuta em todas as interfaces vista com
  `Network URL`/`External URL`). `iniciar.py` recebe o mesmo
  `--server.address 127.0.0.1`.
- Downloads (PDF/Excel dos relatórios) usam o diálogo de salvar do Electron
  (`will-download`); nenhum arquivo é salvo sem escolha do usuário.

## Build

`scripts/build_instalador.ps1` passa a: (a) baixar o `.zip` oficial do Electron
(versão estável fixada em uma constante do script, escolhida na implementação) e
**conferir o SHA-256** contra o `SHASUMS256.txt` publicado na mesma versão,
abortando se divergir; (b) extrair em `build_instalador\electron\`, renomear
`electron.exe` para `UFRPE BudgetLab.exe` e copiar `electron\app\*` (fonte no
repositório: `electron/`) para `resources\app\`; (c) o `budgetlab.iss` inclui
`electron\*` (`Excludes: "__pycache__"` já existente) e aponta atalhos e "Abrir
agora" para ele. Sem Node/npm: só o runtime pronto e o código JS do projeto.
A atualização opcional (`atualizar.py`) continua atualizando `app\`; os arquivos
do Electron só mudam com um novo instalador.

## Riscos e mitigações

1. **Tamanho:** o instalador cresce ~70–100 MB. Aceito.
2. **`.exe` sem assinatura:** SmartScreen/antivírus podem alertar; plano B é o
   `iniciar.py` pelo atalho antigo (mantido).
3. **Processos órfãos** (`python.exe` vivo após fechar): coberto por `taskkill /T`
   e por teste manual obrigatório; o desinstalador já é executado com o app fechado.
4. **Porta ocupada entre escolher e iniciar:** nova tentativa com outra porta (até
   3 vezes) antes de mostrar erro.
5. **Versão do Electron desatualizada** ao longo do tempo: documentada no README
   como manutenção do build.

## Testes

- `electron/lib.js` (funções puras: `comandoStreamlit(python, porta)`,
  `urlSaude(porta)`, `urlPermitida(url, porta)`, `escolherPorta()`,
  `ultimasLinhas(texto, n)`) com `electron/lib.test.js` (`node:test`), executado por
  `UFRPE BudgetLab.exe`/`electron.exe` com `ELECTRON_RUN_AS_NODE=1`; casos:
  comando inclui `--server.address 127.0.0.1` e caminhos com espaço/acento como
  argumento único; `urlPermitida` aceita só `127.0.0.1:<porta>` (rejeita
  `localhost`, outras portas, `file:`, `javascript:`).
- `tests/test_instalador_atualizar_cli.py` (pytest): a saída e o código de saída do
  `atualizar_cli.py` para os três resultados, com `atualizar` simulado.
- `tests/test_instalador_iniciar.py`: o comando de `iniciar.py` inclui
  `--server.address 127.0.0.1`.
- Verificação manual de ponta a ponta: instalar (leve e completo), abrir (janela
  própria, sem janela preta, sem navegador), usar uma página, baixar um relatório,
  clicar num link externo (abre o navegador padrão), tentar a segunda instância,
  fechar e confirmar que nenhum `python.exe`/Electron fica vivo, confirmar que o
  Streamlit **não** escuta fora de `127.0.0.1` (`Get-NetTCPConnection`), reinstalar
  e desinstalar mantendo `dados\`.
- A suíte atual (`python -m pytest tests -n 8 --dist loadfile`) deve continuar
  passando.

## Documentação

README: seção do instalador atualizada (janela própria, como fechar, manutenção da
versão do Electron e plano B).
