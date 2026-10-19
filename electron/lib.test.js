// Testes das funções puras do Electron. Executar com o próprio Electron em modo Node:
//   $env:ELECTRON_RUN_AS_NODE=1; & "build_instalador\electron-teste\UFRPE BudgetLab.exe" --test electron\lib.test.js
const test = require("node:test");
const assert = require("node:assert");
const net = require("node:net");
const lib = require("./lib");

test("comandoStreamlit: caminho com espaço e acento vai como um único argumento", () => {
  const py = "C:/Users/João Silva/UFRPE BudgetLab/python/python.exe";
  const { cmd, args } = lib.comandoStreamlit(py, 8503);
  assert.strictEqual(cmd, py);
  assert.deepStrictEqual(args.slice(0, 4), ["-m", "streamlit", "run", "app.py"]);
  assert.strictEqual(args[args.indexOf("--server.address") + 1], "127.0.0.1");
  assert.strictEqual(args[args.indexOf("--server.port") + 1], "8503");
  assert.strictEqual(args[args.indexOf("--browser.gatherUsageStats") + 1], "false");
  assert.strictEqual(args[args.indexOf("--server.headless") + 1], "true");
});

test("urlApp e urlSaude usam 127.0.0.1", () => {
  assert.strictEqual(lib.urlApp(8503), "http://127.0.0.1:8503");
  assert.strictEqual(lib.urlSaude(8503), "http://127.0.0.1:8503/_stcore/health");
});

test("urlPermitida aceita só a origem local da porta", () => {
  assert.strictEqual(lib.urlPermitida("http://127.0.0.1:8503/x?y=1", 8503), true);
  for (const ruim of [
    "http://localhost:8503", "http://127.0.0.1:8504", "https://127.0.0.1:8503",
    "https://exemplo.com", "file:///C:/x", "javascript:alert(1)", "não é url", "",
  ]) {
    assert.strictEqual(lib.urlPermitida(ruim, 8503), false, ruim);
  }
});

test("ultimasLinhas", () => {
  assert.strictEqual(lib.ultimasLinhas("a\nb\nc\nd", 2), "c\nd");
  assert.strictEqual(lib.ultimasLinhas("", 5), "");
  assert.strictEqual(lib.ultimasLinhas("a\nb", 10), "a\nb");
});

test("escolherPorta devolve uma porta livre", async () => {
  const porta = await lib.escolherPorta();
  assert.ok(Number.isInteger(porta) && porta >= 1024 && porta <= 65535);
  await new Promise((ok, falha) => {
    const s = net.createServer();
    s.once("error", falha);
    s.listen(porta, "127.0.0.1", () => s.close(ok));
  });
});

test("caminhos deriva a raiz de resourcesPath e aceita BUDGETLAB_RAIZ", () => {
  const c = lib.caminhos(String.raw`C:\x\UFRPE BudgetLab\electron\resources`, {});
  assert.ok(c.raiz.endsWith("UFRPE BudgetLab"));
  assert.ok(c.python.endsWith(String.raw`python\python.exe`));
  assert.ok(c.app.endsWith(String.raw`UFRPE BudgetLab\app`));
  assert.ok(c.log.endsWith(String.raw`log\inicio.txt`));
  assert.strictEqual(lib.caminhos("C:/x", { BUDGETLAB_RAIZ: String.raw`D:\dev` }).raiz, String.raw`D:\dev`);
});

test("esperarSaude: tenta de novo até responder", async () => {
  let n = 0;
  const buscar = async () => { n += 1; if (n < 3) throw new Error("recusado"); return { ok: true }; };
  assert.strictEqual(await lib.esperarSaude(8503, { tentativas: 5, intervaloMs: 1, buscar }), true);
});

test("esperarSaude: desiste depois das tentativas", async () => {
  const buscar = async () => { throw new Error("recusado"); };
  assert.strictEqual(await lib.esperarSaude(8503, { tentativas: 3, intervaloMs: 1, buscar }), false);
});

test("esperarSaude: para na hora quando parar() é verdadeiro (servidor caiu)", async () => {
  let chamadas = 0;
  const buscar = async () => { chamadas += 1; throw new Error("recusado"); };
  const r = await lib.esperarSaude(8503, { tentativas: 100, intervaloMs: 1, buscar, parar: () => chamadas >= 2 });
  assert.strictEqual(r, false);
  assert.ok(chamadas <= 3);
});

test("appRenderizado: título 'Streamlit' (esqueleto) ainda não é o app", () => {
  assert.strictEqual(lib.appRenderizado("Streamlit"), false);
  assert.strictEqual(lib.appRenderizado(""), false);
  assert.strictEqual(lib.appRenderizado(undefined), false);
  assert.strictEqual(lib.appRenderizado("UFRPE BudgetLab"), true);
});

test("esperarRender: devolve true quando o título muda e false se nunca mudar", async () => {
  let n = 0;
  const titulo = async () => (++n < 3 ? "Streamlit" : "UFRPE BudgetLab");
  assert.strictEqual(await lib.esperarRender(titulo, { tentativas: 10, intervaloMs: 1 }), true);
  assert.strictEqual(await lib.esperarRender(async () => "Streamlit", { tentativas: 3, intervaloMs: 1 }), false);
  assert.strictEqual(await lib.esperarRender(async () => { throw new Error("x"); }, { tentativas: 2, intervaloMs: 1 }), false);
});
