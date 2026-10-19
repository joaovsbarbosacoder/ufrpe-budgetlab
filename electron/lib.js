// Funções puras do inicializador Electron (testadas em lib.test.js).
const net = require("node:net");
const path = require("node:path");

function comandoStreamlit(python, porta) {
  return {
    cmd: python,
    args: [
      "-m", "streamlit", "run", "app.py",
      "--server.headless", "true",
      "--server.address", "127.0.0.1",
      "--server.port", String(porta),
      "--browser.gatherUsageStats", "false",
    ],
  };
}

const urlApp = (porta) => `http://127.0.0.1:${porta}`;
const urlSaude = (porta) => `${urlApp(porta)}/_stcore/health`;

// Só a origem local do servidor: nunca localhost, outra porta, https, file: ou javascript:.
function urlPermitida(url, porta) {
  try {
    return new URL(url).origin === urlApp(porta);
  } catch {
    return false;
  }
}

function ultimasLinhas(texto, n) {
  if (!texto) return "";
  return texto.split(/\r?\n/).slice(-n).join("\n");
}

function escolherPorta() {
  return new Promise((ok, falha) => {
    const servidor = net.createServer();
    servidor.once("error", falha);
    servidor.listen(0, "127.0.0.1", () => {
      const { port } = servidor.address();
      servidor.close(() => ok(port));
    });
  });
}

// resourcesPath = <raiz>\electron\resources → a raiz da instalação fica dois níveis acima.
function caminhos(resourcesPath, env = process.env) {
  const raiz = env.BUDGETLAB_RAIZ || path.win32.resolve(resourcesPath, "..", "..");
  return {
    raiz,
    python: path.win32.join(raiz, "python", "python.exe"),
    app: path.win32.join(raiz, "app"),
    log: path.win32.join(raiz, "log", "inicio.txt"),
  };
}

const dormir = (ms) => new Promise((ok) => setTimeout(ok, ms));

async function esperarSaude(porta, { tentativas = 240, intervaloMs = 500, buscar = fetch } = {}) {
  for (let i = 0; i < tentativas; i++) {
    try {
      const resposta = await buscar(urlSaude(porta));
      if (resposta.ok) return true;
    } catch {
      // servidor ainda subindo
    }
    await dormir(intervaloMs);
  }
  return false;
}

module.exports = {
  comandoStreamlit, urlApp, urlSaude, urlPermitida, ultimasLinhas,
  escolherPorta, caminhos, esperarSaude,
};
