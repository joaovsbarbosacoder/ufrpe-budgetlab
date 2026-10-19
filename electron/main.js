// UFRPE BudgetLab — janela própria (Electron) sobre o Streamlit local.
// Fluxo: tela de carregamento → atualização opcional → Streamlit em 127.0.0.1 → janela.
// Ao fechar a janela, o Streamlit e seus filhos são encerrados. Ver
// docs/superpowers/specs/2026-10-19-electron-janela-design.md.
const { app, BrowserWindow, Menu, shell } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const lib = require("./lib");

const caminhos = lib.caminhos(process.resourcesPath);
const TEMPO_ATUALIZACAO_MS = 60_000;
const TENTATIVAS_PORTA = 3;

let janela = null;
let servidor = null;
let atualizacao = null;
let encerrando = false;
let porta = null;
let saida = "";

function registrar(texto) {
  saida += texto;
  try {
    fs.appendFileSync(caminhos.log, texto);
  } catch {
    // o log é só diagnóstico
  }
}

function matar(processo) {
  if (processo && processo.pid && processo.exitCode === null) {
    spawnSync("taskkill", ["/PID", String(processo.pid), "/T", "/F"], { windowsHide: true });
  }
}

function abrirExterno(url) {
  if (/^https?:\/\//i.test(url)) shell.openExternal(url);
}

function criarJanela() {
  janela = new BrowserWindow({
    width: 1366,
    height: 860,
    title: "UFRPE BudgetLab",
    backgroundColor: "#f4f7fb",
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true },
  });
  janela.webContents.on("will-navigate", (evento, url) => {
    if (!porta || !lib.urlPermitida(url, porta)) {
      evento.preventDefault();
      abrirExterno(url);
    }
  });
  janela.webContents.setWindowOpenHandler(({ url }) => {
    abrirExterno(url);
    return { action: "deny" };
  });
  // Sem menu, F5 e Ctrl+R não recarregam sozinhos: reativa o recarregamento.
  janela.webContents.on("before-input-event", (evento, entrada) => {
    const recarregar = entrada.key === "F5" || (entrada.control && entrada.key.toLowerCase() === "r");
    if (entrada.type === "keyDown" && recarregar) {
      evento.preventDefault();
      janela.webContents.reloadIgnoringCache();
    }
  });
  janela.on("closed", () => {
    janela = null;
  });
}

function mostrar() {
  if (!janela) return;
  if (janela.isMinimized()) janela.restore();
  janela.show();
  janela.focus();
}

function atualizar() {
  return new Promise((resolve) => {
    const script = path.win32.join(caminhos.app, "scripts", "instalador", "atualizar_cli.py");
    if (!fs.existsSync(caminhos.python) || !fs.existsSync(script)) return resolve();
    atualizacao = spawn(caminhos.python, [script, caminhos.app, caminhos.python], {
      cwd: caminhos.app,
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: "1" },
    });
    const limite = setTimeout(() => matar(atualizacao), TEMPO_ATUALIZACAO_MS);
    atualizacao.stdout.on("data", (d) => registrar(`[atualização] ${d}`));
    atualizacao.stderr.on("data", (d) => registrar(`[atualização] ${d}`));
    const fim = () => {
      clearTimeout(limite);
      resolve();
    };
    atualizacao.once("error", fim);
    atualizacao.once("close", fim);
  });
}

// Sobe o Streamlit e devolve true quando /_stcore/health responder, false se ele cair antes.
function subir(portaTentativa) {
  const { cmd, args } = lib.comandoStreamlit(caminhos.python, portaTentativa);
  registrar(`\n[servidor] porta ${portaTentativa}\n`);
  servidor = spawn(cmd, args, {
    cwd: caminhos.app,
    windowsHide: true,
    env: { ...process.env, PYTHONUTF8: "1" },
  });
  let caiu = false;
  servidor.stdout.on("data", (d) => registrar(String(d)));
  servidor.stderr.on("data", (d) => registrar(String(d)));
  const saiu = new Promise((resolve) => {
    const fim = () => {
      caiu = true;
      resolve(false);
    };
    servidor.once("exit", fim);
    servidor.once("error", (erro) => {
      registrar(`[servidor] erro: ${erro.message}\n`);
      fim();
    });
  });
  const pronto = lib.esperarSaude(portaTentativa, { parar: () => caiu || encerrando });
  return Promise.race([pronto, saiu]);
}

// Carrega o app e confere que ele renderizou (título deixa de ser "Streamlit"). Se a página
// ficar em branco, recarrega uma vez; se ainda assim não renderizar, mostra a página de erro.
async function abrirApp(portaApp) {
  const titulo = () => (janela ? janela.webContents.executeJavaScript("document.title") : "");
  for (let tentativa = 1; tentativa <= 2 && janela && !encerrando; tentativa++) {
    registrar(`[janela] carregando o app (tentativa ${tentativa})\n`);
    if (tentativa === 1) await janela.loadURL(lib.urlApp(portaApp));
    else janela.webContents.reloadIgnoringCache();
    registrar("[janela] página carregada; esperando renderizar\n");
    if (await lib.esperarRender(titulo, { tentativas: 40 })) return;
    registrar(`[janela] página sem renderizar (tentativa ${tentativa})\n`);
  }
  if (janela && !encerrando) {
    await janela.loadFile(path.join(__dirname, "erro.html"), {
      query: { log: caminhos.log, texto: "A página não terminou de carregar.\n" + lib.ultimasLinhas(saida, 20) },
    });
  }
}

async function iniciar() {
  Menu.setApplicationMenu(null);
  try {
    fs.mkdirSync(path.win32.dirname(caminhos.log), { recursive: true });
    fs.writeFileSync(caminhos.log, "");
  } catch {
    // sem log, segue
  }
  criarJanela();
  await janela.loadFile(path.join(__dirname, "carregando.html"));

  await atualizar();
  for (let tentativa = 1; tentativa <= TENTATIVAS_PORTA && !encerrando; tentativa++) {
    porta = await lib.escolherPorta();
    if (await subir(porta)) {
      if (janela) await abrirApp(porta);
      return;
    }
    matar(servidor);
  }
  if (janela && !encerrando) {
    await janela.loadFile(path.join(__dirname, "erro.html"), {
      query: { log: caminhos.log, texto: lib.ultimasLinhas(saida, 20) },
    });
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", mostrar);
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", () => {
    encerrando = true;
    matar(atualizacao);
    matar(servidor);
  });
  app.whenReady().then(iniciar);
}
