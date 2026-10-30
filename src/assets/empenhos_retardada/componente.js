// Empenhos com Execução Retardada — componente da página (layout do mockup aprovado em 17/10/2026).
//
// Só DESENHA o que recebe em `data` (montado em Python por src/empenhos_retardada_tela.py) e devolve
// as ações do usuário como o gatilho "acao" ({tipo, ...}). Nenhuma regra de negócio aqui: filtro,
// corte, ordenação, agrupamento e paginação são calculados no Python a cada ação.
// Estado só de interface (filtro aberto, rascunho da seleção, filtros por atributo visíveis) fica em
// `UI`, por instância, e sobrevive às novas renderizações.

const UI = new WeakMap();
const MAX_OPCOES = 300;

const esc = (valor) =>
  String(valor ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const ICONE_BUSCA =
  '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></svg>';

function textoSelecao(campo) {
  const n = campo.selecionados.length;
  if (n === 0) return "Todos";
  if (n === 1) return campo.selecionados[0];
  return `${n} selecionados`;
}

function htmlCampo(campo, ui, direita) {
  const ativo = campo.selecionados.length > 0;
  const aberto = ui.aberto === campo.nome;
  let pop = "";
  if (aberto) {
    pop = `<div class="ms-pop${direita ? " direita" : ""}" role="dialog" aria-label="${esc(campo.rotulo)}">
      <input class="ms-filtro" type="search" placeholder="Filtrar opções…" value="${esc(ui.filtroOpcoes)}" aria-label="Filtrar opções de ${esc(campo.rotulo)}">
      <div class="ms-lista">${htmlOpcoes(campo, ui)}</div>
      <div class="ms-rodape">
        <button type="button" class="link" data-acao="ms-limpar">Limpar seleção</button>
        <button type="button" class="btn primario peq" data-acao="ms-aplicar">Aplicar</button>
      </div>
    </div>`;
  }
  return `<div class="campo" data-campo="${esc(campo.nome)}">
    <span class="rot">${esc(campo.rotulo)}</span>
    <button type="button" class="ms-btn${ativo ? " ativo" : ""}" data-acao="ms-abrir" data-nome="${esc(campo.nome)}" aria-expanded="${aberto}" title="${esc(campo.selecionados.join("; "))}">
      <span class="ms-val">${esc(textoSelecao(campo))}</span><span class="ms-seta">▾</span>
    </button>${pop}
  </div>`;
}

function htmlOpcoes(campo, ui) {
  const alvo = (ui.filtroOpcoes || "").toLowerCase();
  // selecionados primeiro, para não "sumirem" numa lista longa
  const ordem = [...campo.opcoes].sort((a, b) => (ui.rascunho.has(b) ? 1 : 0) - (ui.rascunho.has(a) ? 1 : 0));
  const filtradas = alvo ? ordem.filter((o) => o.toLowerCase().includes(alvo)) : ordem;
  if (!filtradas.length) return '<div class="ms-vazio">Nenhuma opção com esse texto.</div>';
  const visiveis = filtradas.slice(0, MAX_OPCOES);
  const itens = visiveis
    .map(
      (o) => `<label class="ms-opcao"><input type="checkbox" data-opcao="${esc(o)}"${ui.rascunho.has(o) ? " checked" : ""}><span>${esc(o)}</span></label>`
    )
    .join("");
  const mais = filtradas.length > MAX_OPCOES
    ? `<div class="ms-mais">Mostrando ${MAX_OPCOES} de ${filtradas.length} opções. Digite para encontrar as demais.</div>`
    : "";
  return itens + mais;
}

function htmlFiltros(d, ui) {
  const rapidos = d.filtros_rapidos.map((c, i) => htmlCampo(c, ui, i >= d.filtros_rapidos.length - 1)).join("");
  const nAv = d.filtros_avancados.length;
  const ativos = d.n_filtros_ativos || 0;
  const avancados = ui.avancados
    ? `<div class="avancados">
        <p class="nota-av">${nAv} atributos cruzados; combinações sem registro não aparecem nas listas.</p>
        ${d.filtros_avancados.map((c, i) => htmlCampo(c, ui, i % 3 === 2)).join("")}
      </div>`
    : "";
  return `<section class="card filtros" aria-label="Filtros">
    <div class="linha-filtros">
      <div class="campo">
        <span class="rot">Busca livre</span>
        <label class="busca">${ICONE_BUSCA}<input id="er-busca" type="search" placeholder="NE, favorecido, ação, PI, processo…" value="${esc(d.busca)}" aria-label="Busca livre">${d.busca ? '<button type="button" class="limpa" data-acao="busca-limpar" aria-label="Limpar busca">×</button>' : ""}</label>
      </div>
      ${rapidos}
    </div>
    <div class="linha-acoes">
      <button type="button" class="btn" data-acao="avancados" aria-expanded="${ui.avancados}">${ui.avancados ? "Ocultar" : "Mostrar"} filtros por atributo (${nAv})${ativos ? `<span class="selo">${ativos}</span>` : ""}</button>
      <button type="button" class="link" data-acao="limpar">Limpar filtros</button>
    </div>
    ${avancados}
  </section>`;
}

function htmlResumo(r) {
  if (!r) return "";
  const pct = r.pct_liquidado;
  const barra = pct === null || pct === undefined
    ? ""
    : `<div class="fluxo-barra" role="img" aria-label="${pct.toFixed(1).replace(".", ",")}% liquidado e ${(100 - pct).toFixed(1).replace(".", ",")}% em saldo a liquidar"><div class="liq" style="width:${pct.toFixed(2)}%"></div><div class="sal" style="width:${(100 - pct).toFixed(2)}%"></div></div>`;
  const p = (v) => (pct === null || pct === undefined ? "" : `${v.toFixed(1).replace(".", ",")}% do empenhado`);
  return `<section class="card resumo" aria-label="Resumo do escopo">
    <div class="contagem"><div class="grande num">${esc(r.empenhos)}</div><div class="leg">empenhos no escopo</div></div>
    <div class="fluxo">
      ${barra}
      <div class="legenda">
        <div><div class="k rot">Empenhado</div><div class="v num">${esc(r.empenhado)}</div><div class="p">${pct === null || pct === undefined ? "" : "100%"}</div></div>
        <div><div class="k rot"><span class="ponto" style="background:var(--pos)"></span>Liquidado</div><div class="v num">${esc(r.liquidado)}</div><div class="p">${p(pct ?? 0)}</div></div>
        <div><div class="k rot"><span class="ponto" style="background:var(--warn)"></span>Saldo a liquidar</div><div class="v num">${esc(r.saldo)}</div><div class="p">${p(100 - (pct ?? 0))}</div></div>
      </div>
    </div>
  </section>`;
}

function htmlCortes(d) {
  const c = d.cortes;
  const fmt = (v) => (Number.isInteger(v) ? String(v) : String(v));
  const ligados = [c.usar_rs, c.usar_pct, c.usar_idade].filter(Boolean).length;
  const modo = ligados >= 2
    ? `<div class="seg" role="group" aria-label="Combinação dos cortes" title="OU: passa quem atende qualquer corte ligado. E: só quem atende todos.">
        ${["E", "OU"].map((m) => `<button type="button" data-acao="modo" data-valor="${m}" aria-pressed="${c.modo === m}">${m}</button>`).join("")}
      </div>`
    : "";
  return `<section class="card cortes" aria-label="Cortes de destaque">
    <span class="titulo">Destacar empenhos com</span>
    <label class="corte${c.usar_rs ? "" : " desligado"}"><span class="chave"><input type="checkbox" data-acao="usar_rs"${c.usar_rs ? " checked" : ""} aria-label="Usar corte em reais"><span></span></span>saldo de pelo menos R$ <input type="number" data-corte="corte_rs" value="${fmt(c.corte_rs)}" min="0" step="1000" aria-label="Saldo mínimo em reais"></label>
    ${modo}
    <label class="corte${c.usar_pct ? "" : " desligado"}"><span class="chave"><input type="checkbox" data-acao="usar_pct"${c.usar_pct ? " checked" : ""} aria-label="Usar corte em porcentagem"><span></span></span>saldo de pelo menos <input type="number" data-corte="corte_pct" value="${fmt(c.corte_pct)}" min="0" max="1000" step="5" aria-label="Saldo mínimo em porcentagem do empenhado"> % do empenhado</label>
    <label class="corte${c.usar_idade ? "" : " desligado"}" title="Meses entre o primeiro empenho da NE e ${esc(d.mes_referencia)} (mês da extração). Só para o exercício da extração; anos anteriores aparecem como —."><span class="chave"><input type="checkbox" data-acao="usar_idade"${c.usar_idade ? " checked" : ""} aria-label="Usar corte por idade do saldo"><span></span></span>empenho há pelo menos <input type="number" data-corte="corte_idade" value="${c.corte_idade}" min="0" max="120" step="1" aria-label="Idade mínima do saldo em meses"> meses, com saldo</label>
    <span class="resultado">${esc(d.resultado_corte || "")}</span>
    ${d.cortes_padrao
      ? `<p class="dica">Os cortes estão nos valores padrão. Quer destacar também os empenhos parados há mais tempo? <button type="button" class="link" data-acao="ligar-idade">Ligar corte por idade do saldo</button></p>`
      : ""}
  </section>`;
}

// Indicações de candidatos a anulação (src/candidatos_anulacao.py): legenda com contagem no escopo e
// limites ajustáveis. Informativo — não muda o destaque nem a lista.
function htmlAnulacao(d) {
  const a = d.anulacao;
  if (!a) return "";
  const p = a.parametros;
  const contagem = Object.fromEntries((a.contagem || []).map((c) => [c.nome, c]));
  const regras = a.regras
    .map(([nome, regra]) => {
      const c = contagem[nome] || { n: 0, saldo: "—" };
      const qtd = c.n ? `${c.n} ${c.n === 1 ? "empenho" : "empenhos"} · ${esc(c.saldo)}` : "nenhum empenho";
      return `<li><span class="pilula ind">${esc(nome)}</span><span class="regra">${esc(regra)}</span><span class="qtd num">${qtd}</span></li>`;
    })
    .join("");
  const num = (chave, valor, rotulo, attrs) =>
    `<label class="param">${rotulo} <input type="number" data-anul="${chave}" value="${esc(valor)}" ${attrs} aria-label="${esc(rotulo)}"></label>`;
  return `<section class="card anulacao" aria-label="Candidatos a anulação">
    <div class="topo-anul">
      <span class="titulo">Indicações para análise de anulação</span>
      <span class="aviso-anul">Informativo: aponta o que vale analisar, não é recomendação de anular.</span>
      ${d.grupo === "Indicação de anulação" ? "" : '<button type="button" class="link" data-acao="agrupar-indicacao">Agrupar por indicação</button>'}
    </div>
    <ul class="regras">${regras}</ul>
    <div class="params">
      ${num("anul_nunca_meses", p.anul_nunca_meses, "Nunca liquidada: meses", 'min="0" max="120" step="1"')}
      ${num("anul_sem_liq_meses", p.anul_sem_liq_meses, "Sem liquidação: meses", 'min="0" max="120" step="1"')}
      ${num("anul_residual_rs", p.anul_residual_rs, "Residual: até R$", 'min="0" step="100"')}
      ${num("anul_residual_pct", p.anul_residual_pct, "ou até %", 'min="0" max="100" step="1"')}
    </div>
  </section>`;
}

function htmlIndicacoes(lista) {
  return (lista || []).map((i) => `<span class="pilula ind">${esc(i)}</span>`).join(" ");
}

function htmlPaginacao(l) {
  if (!l || l.total_paginas <= 1) return "";
  return `<div class="paginacao">
    <button type="button" class="btn peq" data-acao="pagina" data-valor="${l.pagina - 1}"${l.pagina <= 1 ? " disabled" : ""} aria-label="Página anterior">‹</button>
    <span>Página ${l.pagina} de ${l.total_paginas}</span>
    <button type="button" class="btn peq" data-acao="pagina" data-valor="${l.pagina + 1}"${l.pagina >= l.total_paginas ? " disabled" : ""} aria-label="Próxima página">›</button>
  </div>`;
}

function htmlTabela(d) {
  const l = d.lista;
  if (!l) {
    const msgs = d.avisos_lista.length ? d.avisos_lista : ["Nenhum empenho para exibir."];
    return `<div class="card tabela"><div class="vazio">${msgs.map(esc).join("<br>")}</div></div>`;
  }
  const numericas = new Set(["Empenhado", "Liquidado", "Saldo", "% Saldo", "Idade"]);
  const cab = d.colunas
    .map((col) => {
      const ativa = d.ordem === col;
      const seta = ativa ? (d.sentido === "asc" ? "▲" : "▼") : "";
      const sort = ativa ? (d.sentido === "asc" ? "ascending" : "descending") : "none";
      return `<th class="${numericas.has(col) ? "dir" : ""}${ativa ? " ativa" : ""}" aria-sort="${sort}"><button type="button" data-acao="ordenar" data-coluna="${esc(col)}" title="Ordenar por ${esc(col)}">${esc(col)} ${seta}</button></th>`;
    })
    .join("");
  const colunas = d.colunas.length + (l.mostra_corte ? 1 : 0) + 2;
  let grupoAtual = null;
  const corpo = l.linhas
    .map((r) => {
      let g = "";
      if (r.grupo !== null && r.grupo !== grupoAtual) {
        grupoAtual = r.grupo;
        const s = l.subtotais[r.grupo] || { n: 0, saldo: "—" };
        g = `<tr class="grupo"><td colspan="${colunas}">${esc(r.grupo)}<span>${s.n} empenhos · saldo ${esc(s.saldo)}</span></td></tr>`;
      }
      const barra = r.pct_valor === null ? "" : `<div class="mini" aria-hidden="true"><i style="width:${Math.max(0, Math.min(100, r.pct_valor)).toFixed(1)}%"></i></div>`;
      const corte = !l.mostra_corte
        ? ""
        : `<td>${r.corte === null ? '<span class="pilula nao">—</span>' : r.corte ? '<span class="pilula ok">Destaque</span>' : '<span class="pilula nao">Abaixo</span>'}</td>`;
      return `${g}<tr class="linha">
        <td class="ne">${esc(r.ne)}<small title="${esc(r.acao)}">${esc(r.acao)}</small></td>
        <td class="fav" title="${esc(r.favorecido)}">${esc(r.favorecido)}</td>
        <td class="dir num">${esc(r.empenhado)}</td>
        <td class="dir num">${esc(r.liquidado)}</td>
        <td class="dir num"><div class="saldo"><span class="${r.saldo_negativo ? "neg" : ""}">${esc(r.saldo)}</span>${barra}</div></td>
        <td class="dir num">${esc(r.pct)}</td>
        <td class="dir num">${esc(r.idade)}</td>
        <td class="ind">${htmlIndicacoes(r.indicacoes)}</td>
        ${corte}
        <td class="dir"><button type="button" class="btn peq" data-acao="detalhe" data-ne="${esc(r.ne_ccor)}">Ver</button></td>
      </tr>`;
    })
    .join("");
  const thCorte = l.mostra_corte ? '<th><span class="th">Corte</span></th>' : "";
  return `<div class="card tabela">
    <div class="rolagem"><table>
      <thead><tr>${cab}<th><span class="th">Indicação</span></th>${thCorte}<th><span class="th"></span></th></tr></thead>
      <tbody>${corpo}</tbody>
    </table></div>
    <div class="rodape"><span>Exibindo ${l.inicio}–${l.fim} de ${l.total} empenhos.</span><span>${esc(l.abaixo || "")}</span>${htmlPaginacao(l)}</div>
  </div>`;
}

function htmlLista(d) {
  const grupos = d.grupos.map((g) => `<option value="${esc(g)}"${g === d.grupo ? " selected" : ""}>${esc(g)}</option>`).join("");
  return `<section aria-label="Empenhos" class="er">
    <div class="barra-lista">
      <div class="lado">
        <h3>Empenhos</h3>
        <div class="seg" role="group" aria-label="Exibir">
          ${d.visoes.map((v) => `<button type="button" data-acao="visao" data-valor="${esc(v)}" aria-pressed="${d.visao === v}">${esc(v)}</button>`).join("")}
        </div>
        <label class="sel">Agrupar por <select data-acao="agrupar" aria-label="Agrupar por">${grupos}</select></label>
      </div>
      <div class="lado">${htmlPaginacao(d.lista)}</div>
    </div>
    ${d.lista && d.avisos_lista.length ? `<div class="alerta">${d.avisos_lista.map(esc).join("<br>")}</div>` : ""}
    ${htmlTabela(d)}
  </section>`;
}

function htmlDetalhe(det) {
  if (!det) return "";
  const metricas = det.metricas
    .map(([k, v], i) => `<div><div class="rot">${esc(k)}</div><div class="v num${i === 2 && det.saldo_negativo ? " neg" : ""}">${esc(v)}</div></div>`)
    .join("");
  const secoes = det.secoes
    .map(([titulo, pares]) => `<div class="secao"><h4>${esc(titulo)}</h4><dl>${pares.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>`)
    .join("");
  const origem = det.origem
    .map((o) => `<tr><td>${esc(o.linha)}</td><td>${esc(o.tipo)}</td><td>${esc(o.ano)}</td><td class="dir num">${esc(o.empenhada)}</td><td class="dir num">${esc(o.liquidada)}</td><td class="dir num">${esc(o.paga)}</td></tr>`)
    .join("");
  return `<div class="fundo" data-acao="fechar"></div>
  <aside class="painel" role="dialog" aria-modal="true" aria-label="Detalhe do empenho ${esc(det.ne)}">
    <div class="topo">
      <div><p class="kicker">Detalhe do empenho</p><h2>${esc(det.ne)}</h2><p class="desc">${esc(det.favorecido)}</p></div>
      <button type="button" class="btn" data-acao="fechar">Fechar</button>
    </div>
    ${det.descricao ? `<p class="desc">${esc(det.descricao)}</p>` : ""}
    <div class="metricas">${metricas}</div>
    ${det.indicacoes && det.indicacoes.length ? `<p class="desc">Indicação para análise: ${htmlIndicacoes(det.indicacoes)}</p>` : ""}
    ${secoes}
    <div class="secao"><h4>Linhas de origem (rastreabilidade)</h4>
      <div class="origem"><table><thead><tr><th>Linha</th><th>Tipo</th><th>Ano</th><th class="dir">Empenhada</th><th class="dir">Liquidada</th><th class="dir">Paga</th></tr></thead><tbody>${origem}</tbody></table></div>
      <p class="desc">NE completa: ${esc(det.ne_ccor)}</p>
    </div>
  </aside>`;
}

function desenhar(raiz, d, ui) {
  const partes = [htmlFiltros(d, ui)];
  if (d.aviso_exercicio) partes.push(`<p class="nota">⚠ ${esc(d.aviso_exercicio)}</p>`);
  if (d.aviso) {
    partes.push(`<div class="alerta">${esc(d.aviso)}</div>`);
  } else {
    partes.push(htmlResumo(d.resumo), htmlCortes(d), htmlAnulacao(d), htmlLista(d));
  }
  if (d.detalhe && !ui.detalheFechado) partes.push(htmlDetalhe(d.detalhe));
  raiz.innerHTML = partes.join("");
  if (ui.aberto) {
    const filtro = raiz.querySelector(".ms-filtro");
    if (filtro) {
      filtro.focus();
      filtro.setSelectionRange(filtro.value.length, filtro.value.length);
    }
  }
}

function campoPorNome(d, nome) {
  return [...(d.filtros_rapidos || []), ...(d.filtros_avancados || [])].find((c) => c.nome === nome);
}

// Fecha o filtro aberto; devolve true quando enviou a nova seleção (a tela será redesenhada).
function fecharFiltro(ui, aplicar) {
  if (!ui.aberto) return false;
  const campo = campoPorNome(ui.dados, ui.aberto);
  const nome = ui.aberto;
  ui.aberto = null;
  ui.filtroOpcoes = "";
  if (aplicar && campo) {
    const atual = [...campo.selecionados].sort().join("\u0000");
    // mantém a ordem das opções (mesma ordem do multiselect antigo)
    const novo = campo.opcoes.filter((o) => ui.rascunho.has(o));
    if (novo.slice().sort().join("\u0000") !== atual) {
      ui.enviar({ tipo: "filtro", nome, valores: novo });
      return true;
    }
  }
  desenhar(ui.raiz, ui.dados, ui);
  return false;
}

function ligarEventos(raiz, ui) {
  raiz.addEventListener("click", (ev) => {
    const alvo = ev.target.closest("[data-acao]");
    if (!alvo || !raiz.contains(alvo)) return;
    const acao = alvo.dataset.acao;
    const d = ui.dados;
    if (acao === "ms-abrir") {
      const nome = alvo.dataset.nome;
      if (ui.aberto === nome) return fecharFiltro(ui, true);
      if (fecharFiltro(ui, true)) return; // outro filtro estava aberto e mudou: a tela vai ser redesenhada
      const campo = campoPorNome(d, nome);
      ui.aberto = nome;
      ui.rascunho = new Set(campo ? campo.selecionados : []);
      ui.filtroOpcoes = "";
      return desenhar(raiz, d, ui);
    }
    if (acao === "ms-aplicar") return fecharFiltro(ui, true);
    if (acao === "ms-limpar") {
      ui.rascunho = new Set();
      raiz.querySelectorAll(".ms-lista input[type=checkbox]").forEach((c) => (c.checked = false));
      return;
    }
    if (acao === "avancados") {
      ui.avancados = !ui.avancados;
      return desenhar(raiz, d, ui);
    }
    if (acao === "limpar") return ui.enviar({ tipo: "limpar" });
    if (acao === "ligar-idade") return ui.enviar({ tipo: "usar_idade", valor: true });
    if (acao === "agrupar-indicacao") return ui.enviar({ tipo: "agrupar", valor: "Indicação de anulação" });
    if (acao === "busca-limpar") return ui.enviar({ tipo: "busca", valor: "" });
    if (acao === "modo" || acao === "visao") return ui.enviar({ tipo: acao, valor: alvo.dataset.valor });
    if (acao === "ordenar") return ui.enviar({ tipo: "ordenar", coluna: alvo.dataset.coluna });
    if (acao === "pagina") return ui.enviar({ tipo: "pagina", valor: Number(alvo.dataset.valor) });
    if (acao === "detalhe") {
      ui.detalheFechado = false;
      return ui.enviar({ tipo: "detalhe", ne: alvo.dataset.ne });
    }
    if (acao === "fechar") return fecharDetalhe(ui);
  });

  raiz.addEventListener("change", (ev) => {
    const alvo = ev.target;
    if (alvo.matches(".ms-lista input[type=checkbox]")) {
      const opcao = alvo.dataset.opcao;
      if (alvo.checked) ui.rascunho.add(opcao);
      else ui.rascunho.delete(opcao);
      return;
    }
    if (alvo.matches("input[data-acao=usar_rs], input[data-acao=usar_pct], input[data-acao=usar_idade]")) {
      return ui.enviar({ tipo: alvo.dataset.acao, valor: alvo.checked });
    }
    if (alvo.matches("input[data-corte]")) {
      if (alvo.value === "" || Number.isNaN(Number(alvo.value))) return;
      return ui.enviar({ tipo: alvo.dataset.corte, valor: Number(alvo.value) });
    }
    if (alvo.matches("input[data-anul]")) {
      if (alvo.value === "" || Number.isNaN(Number(alvo.value))) return;
      return ui.enviar({ tipo: alvo.dataset.anul, valor: Number(alvo.value) });
    }
    if (alvo.matches("select[data-acao=agrupar]")) return ui.enviar({ tipo: "agrupar", valor: alvo.value });
  });

  raiz.addEventListener("input", (ev) => {
    if (ev.target.matches(".ms-filtro")) {
      ui.filtroOpcoes = ev.target.value;
      const lista = raiz.querySelector(".ms-lista");
      const campo = campoPorNome(ui.dados, ui.aberto);
      if (lista && campo) lista.innerHTML = htmlOpcoes(campo, ui);
    }
  });

  raiz.addEventListener("keydown", (ev) => {
    if (ev.target.id === "er-busca" && ev.key === "Enter") {
      ev.preventDefault();
      if (ev.target.value.trim() !== (ui.dados.busca || "")) ui.enviar({ tipo: "busca", valor: ev.target.value });
    }
    if (ev.key === "Escape") {
      if (ui.aberto) fecharFiltro(ui, false);
      else if (ui.dados.detalhe && !ui.detalheFechado) fecharDetalhe(ui);
    }
  });

  raiz.addEventListener("focusout", (ev) => {
    if (ev.target.id === "er-busca" && ev.target.value.trim() !== (ui.dados.busca || "")) {
      ui.enviar({ tipo: "busca", valor: ev.target.value });
    }
  });
}

function fecharDetalhe(ui) {
  ui.detalheFechado = true;
  ui.raiz.querySelectorAll(".fundo, .painel").forEach((el) => el.remove());
  ui.enviar({ tipo: "fechar_detalhe" });
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  let ui = UI.get(parentElement);
  if (!ui) {
    const raiz = document.createElement("div");
    raiz.className = "er";
    parentElement.appendChild(raiz);
    ui = { raiz, aberto: null, rascunho: new Set(), filtroOpcoes: "", avancados: false, detalheFechado: false };
    UI.set(parentElement, ui);
    ligarEventos(raiz, ui);
  }
  let seq = 0;
  ui.enviar = (acao) => setTriggerValue("acao", { ...acao, seq: `${Date.now()}-${seq++}` });
  ui.dados = data || {};
  if (!ui.dados.detalhe) ui.detalheFechado = false;
  ui.aberto = null; // dados novos: a seleção aplicada já veio do Python
  if (ui.dados.filtros_rapidos) desenhar(ui.raiz, ui.dados, ui);

  // clique fora do filtro aberto aplica a seleção (como fechar um multiselect)
  const fora = (ev) => {
    if (!ui.aberto) return;
    const caminho = ev.composedPath();
    const pop = ui.raiz.querySelector(".ms-pop");
    const botao = ui.raiz.querySelector(`.ms-btn[data-nome="${CSS.escape(ui.aberto)}"]`);
    if ((pop && caminho.includes(pop)) || (botao && caminho.includes(botao))) return;
    fecharFiltro(ui, true);
  };
  document.addEventListener("mousedown", fora, true);
  return () => document.removeEventListener("mousedown", fora, true);
}
