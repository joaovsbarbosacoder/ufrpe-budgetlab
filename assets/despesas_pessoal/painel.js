export default function(component) {
  const {data: d, parentElement, setTriggerValue} = component;
  const root = parentElement.querySelector('#pessoal');
  // Estado visual local: expandir uma linha ou trocar de visão não recalcula nem recarrega a página.
  const collapsed = root._collapsed || (root._collapsed = {});
  const view = root._view || (root._view = 'geral');
  const scrolls = [...root.querySelectorAll('.ap-wrap')].map(el => el.scrollLeft);
  const months = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  // Novo visual (27/10/2026): valores exatos, com centavos — nada é arredondado para milhões nem para reais inteiros.
  const fmt = new Intl.NumberFormat('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const ok = v => v !== null && v !== undefined && Number.isFinite(v);
  const brl = v => !ok(v) ? '—' : (v < 0 ? '−' : '') + 'R$ ' + fmt.format(Math.abs(v));
  const signed = v => !ok(v) ? '—' : (v < 0 ? '−' : '+') + 'R$ ' + fmt.format(Math.abs(v));
  const cssVars = Object.entries(d.cores).map(([k,v]) => `--${k}:${v}`).join(';');
  const groupColor = {ativo: '#0969DA', inativo: '#6E40C9', rpps: '#0E8A8A', outros_beneficios: '#C96A00'};
  const ruleLabel = {
    multiplicador: ['Multiplicador', 'ap-r-mult'], decimo_terceiro: ['13º', 'ap-r-13'],
    proporcao_historica: ['Proporção histórica', 'ap-r-hist'], zero: ['Zero', 'ap-r-zero'],
    sentenca_por_grupo: ['Sentença', 'ap-r-sent'], indenizacao_por_grupo: ['Indenização', 'ap-r-sent'],
    plano_orcamentario: ['Por PO', 'ap-r-po'],
  };

  // ------------------------------------------------------------------ visão geral
  const execAnt = d.total.execAnt;
  const variacao = ok(execAnt) && execAnt > 0 && ok(d.total.total) ? (d.total.total / execAnt - 1) * 100 : null;
  const emDeficit = d.cartoes.filter(c => ok(c.saldo) && c.saldo < 0);
  const kpis = [
    [`Executado + projetado ${d.ano}`, brl(d.total.total), '', 'Executado até a data-base + projetado até dezembro', 'ap-kpi-hero'],
    ['Dotação atual', brl(d.total.dotacao), '', `Dotação Atualizada ${d.anoDotacao}`, ''],
    ['Saldo total em dezembro', signed(d.saldoDezembro), !ok(d.saldoDezembro) ? '' : d.saldoDezembro < 0 ? 'ap-neg' : 'ap-pos',
      ok(d.saldoDezembro) && d.saldoDezembro >= 0 && emDeficit.length ? `Positivo no total, mas ${emDeficit.length} grupo(s) em déficit` : 'Soma dos grupos e ações', ''],
    [`Execução ${d.ano - 1} (empenhada)`, brl(execAnt), '', variacao === null ? '' : `${d.ano} projetado: ${variacao >= 0 ? '+' : '−'}${fmt.format(Math.abs(variacao))}% sobre ${d.ano - 1}`, ''],
  ];
  const statusClass = d.aviso.tipo === 'error' ? 'ap-alert-neg' : d.aviso.tipo === 'success' ? 'ap-alert-pos' : 'ap-alert-info';
  const alerts = `<div class="ap-alert ${statusClass}" role="status"><span class="ap-alert-label">Projeção</span><span>${esc(d.aviso.texto)}</span></div>`
    + (d.avisoFaixa ? `<div class="ap-alert ap-alert-warn" role="status"><span class="ap-alert-label">Cenário histórico</span><span>${esc(d.avisoFaixa)}</span></div>` : '');

  function card(c) {
    const dot = ok(c.dotacao) ? c.dotacao : null;
    const escala = Math.max(dot || 0, c.faixaMax || 0, c.total || 0, 1) * 1.04;
    const pct = v => `${Math.max(0, v / escala * 100).toFixed(3)}%`;
    const exec = c.executado || 0, total = c.total || 0;
    const ate = dot === null ? total : Math.min(total, dot);
    const over = dot === null ? 0 : Math.max(0, total - dot);
    const estado = !ok(c.saldo) ? 'ap-pill-info' : c.saldo < 0 ? 'ap-pill-neg' : ok(c.pior) && c.pior < 0 ? 'ap-pill-warn' : 'ap-pill-pos';
    const pill = !ok(c.saldo) ? 'Sem dotação' : c.saldo < 0 ? `Déficit ${brl(-c.saldo)}` : `Folga ${brl(c.saldo)}`;
    const faixa = ok(c.faixaMin) && ok(c.faixaMax)
      ? `<div class="ap-range"><div class="ap-range-bar" style="left:${pct(c.faixaMin)};width:${pct(c.faixaMax - c.faixaMin)}" title="Faixa histórica ${esc(brl(c.faixaMin))} a ${esc(brl(c.faixaMax))}"></div></div>` : '';
    const acoes = c.acoes.length ? `<div class="ap-card-sub">${c.acoes.map(a => `<div><span>${esc(a.nome)}</span><b class="${ok(a.saldo) && a.saldo < 0 ? 'ap-neg' : 'ap-pos'}">${signed(a.saldo)}</b></div>`).join('')}</div>` : '';
    return `<article class="ap-card" style="--c:${groupColor[c.key] || 'var(--accent)'}">
      <header><h3>${esc(c.nome)}</h3><span class="ap-pill ${estado}">${esc(pill)}</span></header>
      <div class="ap-figs"><div>Executado ${d.mes === 1 ? 'jan' : 'jan–' + months[d.mes-1].toLowerCase()}<b>${brl(c.executado)}</b></div><div>Projetado até dez<b>${brl(c.projetado)}</b></div><div>Dotação<b>${brl(c.dotacao)}</b></div></div>
      <div class="ap-bar" role="img" aria-label="${esc(c.nome)}: ${esc(brl(c.total))} de ${esc(brl(c.dotacao))} de dotação">
        <div class="ap-bar-exec" style="width:${pct(Math.min(exec, ate))}"></div>
        <div class="ap-bar-proj" style="left:${pct(Math.min(exec, ate))};width:${pct(Math.max(0, ate - exec))}"></div>
        ${over ? `<div class="ap-bar-over" style="left:${pct(dot)};width:${pct(over)}"></div>` : ''}
        ${dot !== null ? `<div class="ap-bar-dot" style="left:${pct(dot)}"></div>` : ''}
      </div>${faixa}
      <div class="ap-card-foot"><span>Total do ano <b>${brl(c.total)}</b></span>${ok(c.faixaMin) ? `<span>Faixa histórica ${brl(c.faixaMin)} a ${brl(c.faixaMax)}</span><span class="${ok(c.pior) && c.pior < 0 ? 'ap-neg' : ''}">Pior caso: ${signed(c.pior)}</span>` : '<span>Sem faixa histórica (nenhum exercício anterior completo)</span>'}</div>
      ${acoes}
    </article>`;
  }

  // Saldo remanescente (27/10/2026): um painel por grupo, cada um na sua escala — no gráfico único o Ativo
  // achatava os demais. Linha cheia = executado, tracejada = projetado; faixa vermelha = abaixo de zero (déficit),
  // com o primeiro mês negativo marcado. Os rótulos do eixo são abreviados; o valor exato aparece ao passar o mouse.
  const compacto = v => {
    const a = Math.abs(v), f = (n, u) => (v < 0 ? '−' : '') + 'R$ ' + new Intl.NumberFormat('pt-BR', {maximumFractionDigits: 1}).format(n) + u;
    return a >= 1e9 ? f(a / 1e9, ' bi') : a >= 1e6 ? f(a / 1e6, ' mi') : a >= 1e3 ? f(a / 1e3, ' mil') : f(a, '');
  };
  const primeiroNegativo = sr => sr.meses.findIndex(v => ok(v) && v < 0);
  const CH = {W: 460, H: 190, l: 78, r: 14, t: 14, b: 24};
  const chX = i => CH.l + i * (CH.W - CH.l - CH.r) / 11;

  function miniChart(sr, k) {
    const cor = groupColor[sr.key] || '#0969DA';
    const valores = sr.meses.filter(ok);
    const neg = primeiroNegativo(sr), fim = sr.meses[11];
    const estado = !valores.length ? ['Sem dotação', ''] : neg >= 0
      ? [`Negativo a partir de ${months[neg].toLowerCase()} (${signed(sr.meses[neg])})`, 'ap-neg'] : ['Positivo até dezembro', 'ap-pos'];
    const cabeca = `<header><h3><i class="ap-swatch" style="background:${cor}"></i>${esc(sr.nome)}</h3><span>Dez <b class="${ok(fim) ? (fim < 0 ? 'ap-neg' : 'ap-pos') : ''}">${signed(fim)}</b></span></header><p class="ap-mini-status ${estado[1]}">${esc(estado[0])}</p>`;
    if (!valores.length) return `<div class="ap-mini">${cabeca}</div>`;
    let max = Math.max(0, ...valores), min = Math.min(0, ...valores);
    const bruto = (max - min) / 3 || 1, pot = 10 ** Math.floor(Math.log10(bruto));
    const passo = [1, 2, 2.5, 5, 10].map(m => m * pot).find(v => v >= bruto);
    // o déficit não é arredondado para baixo até o próximo passo (achataria a linha); só uma folga mínima visível
    max = Math.ceil(max / passo) * passo; min = min < 0 ? Math.min(min * 1.1, -max * 0.05) : 0;
    const {W, H, l, r, t, b} = CH;
    const y = v => t + (max - v) * (H - t - b) / ((max - min) || 1);
    const ticks = [];
    for (let v = 0; v <= max + passo / 2; v += passo) ticks.push(v);
    for (let v = -passo; v >= min; v -= passo) ticks.push(v);
    let s = `<svg class="ap-svg" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(sr.nome)}: saldo remanescente de janeiro a dezembro; ${esc(estado[0])}">`;
    if (d.mes < 12) s += `<rect class="ap-svg-proj" x="${chX(d.mes - 1)}" y="${t}" width="${chX(11) - chX(d.mes - 1)}" height="${H - t - b}"/>`;
    if (min < 0) s += `<rect class="ap-svg-neg" x="${l}" y="${y(0)}" width="${W - l - r}" height="${y(min) - y(0)}"/>`;
    ticks.forEach(v => {
      s += `<line class="${v === 0 ? 'ap-svg-zero' : 'ap-svg-grid'}" x1="${l}" x2="${W - r}" y1="${y(v)}" y2="${y(v)}"/><text class="ap-svg-axis" x="${l - 8}" y="${y(v) + 4}" text-anchor="end">${esc(v === 0 ? 'R$ 0' : compacto(v))}</text>`;
    });
    months.forEach((m, i) => { s += `<text class="ap-svg-axis" x="${chX(i)}" y="${H - 6}" text-anchor="middle">${m}</text>`; });
    const pts = sr.meses.map((v, i) => ok(v) ? `${chX(i)},${y(v)}` : null);
    const real = pts.slice(0, d.mes).filter(Boolean), proj = pts.slice(d.mes - 1).filter(Boolean);
    if (real.length) s += `<polyline points="${real.join(' ')}" fill="none" stroke="${cor}" stroke-width="2" stroke-linejoin="round"/>`;
    if (proj.length > 1) s += `<polyline points="${proj.join(' ')}" fill="none" stroke="${cor}" stroke-width="2" stroke-dasharray="6 4" stroke-linejoin="round"/>`;
    if (neg >= 0) s += `<circle class="ap-svg-ring" cx="${chX(neg)}" cy="${y(sr.meses[neg])}" r="5" fill="var(--red)"/>`;
    // camada de hover: guia vertical + ponto; colunas invisíveis maiores que a marca
    s += `<line class="ap-svg-cross" x1="0" x2="0" y1="${t}" y2="${H - b}" visibility="hidden"/><circle class="ap-svg-ring ap-svg-dot" r="4.5" fill="${cor}" visibility="hidden"/>`;
    const largura = (W - l - r) / 11;
    sr.meses.forEach((v, i) => { if (ok(v)) s += `<rect class="ap-svg-hit" data-k="${k}" data-i="${i}" data-y="${y(v)}" x="${chX(i) - largura / 2}" y="${t}" width="${largura}" height="${H - t - b}"/>`; });
    return `<div class="ap-mini">${cabeca}<div class="ap-mini-plot">${s}</svg><div class="ap-tip" role="tooltip" hidden></div></div></div>`;
  }

  function chart() {
    const series = d.serieSaldo;
    if (!series.some(s => s.meses.some(ok))) return '<p class="ap-empty">Sem dotação para calcular o saldo.</p>';
    return `<div class="ap-chart-legend"><span><i style="background:var(--muted)"></i>Executado</span><span><i class="ap-dash"></i>Projetado</span><span><i class="ap-neg-key"></i>Abaixo de zero: déficit</span><span>Cada grupo na sua escala; passe o mouse para ver o valor exato.</span></div><div class="ap-minis">${series.map(miniChart).join('')}</div>`;
  }

  // Outros Benefícios por Ação, PO e Iduso (27/10/2026): dotação, empenhado, executado, projetado, saldo e empenho
  // a reforçar; o cenário pela média é só comparação (não muda a projeção).
  function beneficiosPo() {
    const q = d.beneficiosPo;
    if (!q) return '';
    const cls = v => ok(v) ? (v < 0 ? 'ap-neg' : 'ap-pos') : '';
    const cells = r => `<td>${brl(r.dotacao)}</td><td>${brl(r.empenhada)}</td><td>${brl(r.executado)}</td><td class="ap-proj">${brl(r.projetado)}</td><td class="ap-col-total">${brl(r.total)}</td><td class="${cls(r.saldo)}">${signed(r.saldo)}</td><td class="${cls(r.empenho_saldo)}">${signed(r.empenho_saldo)}</td><td class="ap-cenario">${brl(r.total_media)}</td><td class="ap-cenario ${cls(r.saldo_media)}">${signed(r.saldo_media)}</td>`;
    const linhas = q.linhas.map(r => `<tr class="ap-child-row"><th scope="row" class="ap-sticky"><span class="ap-cod">${esc(r.acao)}/${esc(r.po)}</span> ${esc(r.poDesc || '')}</th><td class="ap-center">${esc(r.iduso)}</td>${cells(r)}</tr>`).join('');
    const sub = (titulo, rs) => `<tr class="ap-sub-title"><th scope="rowgroup" class="ap-sticky" colspan="11">${titulo}</th></tr>` + rs.map(r => `<tr class="ap-group-row"><th scope="row" class="ap-sticky">${esc(r.rotulo)}</th><td></td>${cells(r)}</tr>`).join('');
    return `<section class="ap-block"><h2 class="ap-section-title">Outros Benefícios por Ação, PO e Iduso</h2>
      <p class="ap-section-sub">Projetado pela mesma regra do painel (inclui os ajustes manuais da sessão). Saldo = dotação − total. Empenho: empenhado − total (negativo = empenho a reforçar). “Cenário pela média”: média mensal de jan até a data-base nos meses restantes (mês sem liquidação conta como zero; mês já liquidado após a data-base usa o maior valor) — só comparação, útil em PO esporádico.</p>
      <div class="ap-wrap" tabindex="0" role="region" aria-label="Outros Benefícios por Ação, PO e Iduso, tabela com rolagem horizontal"><table class="ap-tbl ap-tbl-po" aria-label="Outros Benefícios por Ação, PO e Iduso"><thead>
        <tr class="ap-band"><th class="ap-sticky"></th><th></th><th colspan="7"></th><th colspan="2" class="ap-cenario">Cenário pela média</th></tr>
        <tr><th scope="col" class="ap-sticky">Ação/PO</th><th scope="col">Iduso</th><th scope="col">Dotação</th><th scope="col">Empenhado</th><th scope="col">Executado ${d.mes === 1 ? 'jan' : 'jan–' + months[d.mes-1].toLowerCase()}</th><th scope="col" class="ap-proj">Projetado até dez</th><th scope="col">Total</th><th scope="col">Saldo da dotação</th><th scope="col">Empenho a reforçar (−) / sobra (+)</th><th scope="col" class="ap-cenario">Total</th><th scope="col" class="ap-cenario">Saldo</th></tr></thead>
        <tbody>${linhas}${sub('Por ação', q.porAcao)}${sub('Por Iduso', q.porIduso)}<tr class="ap-total-row"><th scope="row" class="ap-sticky">Total</th><td></td>${cells(q.total)}</tr></tbody></table></div></section>`;
  }

  const monthHeaders = saldo => months.map((m,i) => `<th scope="col" class="${!saldo && i >= d.mes ? 'ap-proj' : ''}">${m}</th>`).join('');
  const reais = d.grupos.filter(g => !g.pendente && !g.subtotal);
  const groupMonthRows = [...reais, d.total].map(g => {
    const saldo = ok(g.dotacao) && ok(g.total) ? g.dotacao - g.total : null;
    const total = g.key === 'total';
    return `<tr class="${total ? 'ap-total-row' : 'ap-group-row'}"><th scope="row" class="ap-sticky">${total ? '' : `<i class="ap-swatch" style="background:${groupColor[g.key] || 'var(--accent)'}"></i>`}${esc(total ? 'Total' : g.nome)}</th>${g.meses.map((v,i) => `<td class="${i >= d.mes ? 'ap-proj' : ''}">${brl(v)}</td>`).join('')}<td class="ap-col-total">${brl(g.total)}</td><td>${brl(g.dotacao)}</td><td class="${ok(saldo) ? (saldo < 0 ? 'ap-neg' : 'ap-pos') : ''}">${signed(saldo)}</td></tr>`;
  }).join('');
  const saldoRows = d.saldos.map(s => `<tr class="${s.subtotal ? 'ap-total-row' : ''}"><th scope="row" class="ap-sticky">${esc(s.nome)}</th>${s.meses.map(v => `<td class="${ok(v) && v < 0 ? 'ap-neg' : ''}">${brl(v)}</td>`).join('')}</tr>`).join('');

  // ------------------------------------------------------------------ rubrica × mês (tabela completa, editável)
  const contextCells = (g, tag) => `<${tag} class="ap-col-total">${brl(g.total)}</${tag}><${tag} title="${g.key instanceof Array ? 'Dotação disponível somente por grupo; sem rateio por rubrica.' : ''}">${brl(g.dotacao)}</${tag}><${tag}>${brl(g.execAnt)}</${tag}><${tag} class="ap-proj">${brl(g.basePloa)}</${tag}>`;
  function row(g, group, gi, ci) {
    const tag = group ? 'th' : 'td';
    const toggle = group && !g.subtotal;
    const regra = !group && g.regra && ruleLabel[g.regra] ? `<span class="ap-rule ${ruleLabel[g.regra][1]}">${ruleLabel[g.regra][0]}</span>` : '';
    const name = toggle ? `<button class="ap-group-button" data-toggle="${esc(g.key)}" aria-expanded="${!collapsed[g.key]}"><span class="ap-arrow">${collapsed[g.key] ? '▸' : '▾'}</span> <i class="ap-swatch" style="background:${groupColor[g.key] || 'var(--muted)'}"></i>${esc(g.nome)}</button>` : esc(g.nome) + regra;
    const cells = g.meses.map((v,i) => {
      const future = i >= d.mes;
      const edited = (g.editados || []).includes(i+1);
      const editable = !group && g.key && future;
      return `<${tag} class="${future ? 'ap-proj' : ''}">${editable ? `<button class="ap-cell-button ${edited ? 'ap-edited' : ''}" data-edit="${gi}:${ci}:${i+1}" aria-label="Editar ${esc(g.nome)}, ${months[i]}" title="${edited ? 'Ajuste manual. ' : ''}Editar projeção de ${months[i]}">${brl(v)}</button>` : brl(v)}</${tag}>`;
    }).join('');
    return `<tr class="${g.subtotal ? 'ap-total-row' : group ? 'ap-group-row' : 'ap-child-row'}" ${group ? '' : `data-parent="${esc(d.grupos[gi].key)}" ${collapsed[d.grupos[gi].key] ? 'hidden' : ''}`}><${tag} class="ap-sticky ${toggle ? 'ap-toggle' : ''}" ${group ? 'scope="row"' : ''}>${name}</${tag}>${cells}${contextCells(g,tag)}</tr>`;
  }
  const rows = d.grupos.map((g,gi) => row(g,true,gi) + (g.children || []).map((c,ci) => row(c,false,gi,ci)).join('')).join('');
  const executed = d.mes === 1 ? 'Jan' : `Jan–${months[d.mes-1]}`;
  const projected = d.mes === 12 ? 'nenhum mês' : d.mes === 11 ? 'Dez' : `${months[d.mes]}–Dez`;
  const reconciliation = d.reconciliacao;
  const hiddenUnless = v => view === v ? '' : 'hidden';

  root.innerHTML = `<section class="ap-page" style="${esc(cssVars)}" aria-label="Acompanhamento de Pessoal">
    <header class="ap-nav"><div class="ap-brand-wrap"><h1 class="ap-brand">Acompanhamento de Pessoal ${d.ano}</h1><span class="ap-uo">UO 26248 — UFRPE</span></div><button class="ap-data-base" title="Alterar mês e dotação de referência" aria-label="Alterar data-base">Data-base: ${esc(d.dataBase)} · Dotação ${d.anoDotacao} ▾</button></header>
    <div class="ap-views" role="tablist" aria-label="Visões do painel"><button role="tab" data-view="geral" aria-selected="${view === 'geral'}">Visão geral</button><button role="tab" data-view="rubricas" aria-selected="${view === 'rubricas'}">Rubrica × mês</button></div>
    <div class="ap-view" data-panel="geral" ${hiddenUnless('geral')}>
      <div class="ap-kpis">${kpis.map(([label,value,cls,sub,extra]) => `<div class="ap-kpi ${extra}"><div class="ap-kpi-label">${esc(label)}</div><div class="ap-kpi-value ${cls}">${esc(value)}</div><div class="ap-kpi-sub">${esc(sub)}</div></div>`).join('')}</div>
      <div class="ap-alerts">${alerts}</div>
      <section class="ap-block"><h2 class="ap-section-title">Por grupo</h2><p class="ap-section-sub">Barra = dotação consumida (executado sólido, projetado hachurado, vermelho acima da dotação); traço laranja = faixa histórica do total do ano.</p><div class="ap-cards">${d.cartoes.map(card).join('')}</div></section>
      ${beneficiosPo()}
      <section class="ap-block"><h2 class="ap-section-title">Saldo remanescente mês a mês</h2><p class="ap-section-sub">Dotação − (executado + projetado acumulado), por grupo. Os valores exatos estão na tabela “Saldo remanescente por grupo e ação”, abaixo.</p><div class="ap-chart">${chart()}</div></section>
      <section class="ap-block"><h2 class="ap-section-title">Grupo × mês</h2><p class="ap-section-sub">Valores exatos em reais. <button class="ap-link" data-goto="rubricas">Abrir o detalhamento mês a mês de cada rubrica →</button></p><div class="ap-wrap" tabindex="0" role="region" aria-label="Grupo por mês, tabela com rolagem horizontal"><table class="ap-tbl" aria-label="Grupo por mês"><thead><tr><th scope="col" class="ap-sticky">Grupo</th>${monthHeaders(false)}<th scope="col">Total</th><th scope="col">Dotação</th><th scope="col">Saldo</th></tr></thead><tbody>${groupMonthRows}</tbody></table></div></section>
      <section class="ap-saldo"><h2 class="ap-section-title">Saldo remanescente por grupo e ação (dotação − executado/projetado acumulado)</h2><div class="ap-wrap" tabindex="0" role="region" aria-label="Saldos por mês, tabela com rolagem horizontal"><table class="ap-tbl" aria-label="Saldo remanescente por grupo"><thead><tr><th scope="col" class="ap-sticky">Grupo</th>${monthHeaders(true)}</tr></thead><tbody>${saldoRows}</tbody></table></div></section>
    </div>
    <div class="ap-view" data-panel="rubricas" ${hiddenUnless('rubricas')}>
      <div class="ap-legend"><span><span class="ap-dot"></span>Executado (${executed})</span><span><span class="ap-dot ap-dot-proj"></span>Projetado (${projected})</span><button class="ap-link" data-expand="1">Expandir todos</button><button class="ap-link" data-expand="0">Recolher todos</button><span class="ap-reconciliation">Diferença Exec. Ano Anterior vs. base validada: ${brl(reconciliation.diferenca)} — ver nota</span></div>
      <div class="ap-wrap ap-main-wrap" tabindex="0" role="region" aria-label="Rubrica por mês, tabela com rolagem horizontal"><table class="ap-tbl" aria-label="Rubrica por mês"><thead><tr><th scope="col" class="ap-sticky">Rubrica</th>${monthHeaders(false)}<th scope="col">Total</th><th scope="col">Dotação Atual</th><th scope="col">Exec. Ano Anterior</th><th scope="col" class="ap-proj">Base PLOA ${d.ano + 1}</th></tr></thead><tbody>${rows}</tbody></table></div>
    </div>
    <footer class="ap-notes"><p>Data-base ${esc(d.dataBase)}; Dotação Atualizada de ${d.anoDotacao}. Valores exatos, com centavos. “Base PLOA ${d.ano+1}” apresenta o valor do mês de referência por rubrica, sem multiplicador; 13º e férias aparecem como “—” nessa coluna porque seguem regra própria. O total de grupo conserva a soma do mês de referência.</p>
    <p>“Exec. Ano Anterior”: soma das rubricas exibidas ${brl(reconciliation.rubricas)}; base anual no mesmo escopo ${brl(reconciliation.base)}; diferença ${brl(reconciliation.diferenca)}${reconciliation.diferenca !== null && Math.abs(reconciliation.diferenca) > .01 ? ' — inclui rubricas históricas sem correspondência na grade atual' : ''}. Dotação por rubrica não disponível: não é feito rateio. Benefício Especial e Precatórios aguardam mapeamento específico e não compõem subtotais separados. Outros Benefícios mantém as ações 2004/212B do painel.</p>
    <p>${esc(d.procedencia)}</p><p>Em “Rubrica × mês”, clique no nome do grupo para recolher/expandir e em um valor projetado de rubrica para editar; meses executados ficam protegidos. Clique na data-base para alterar a referência.</p>
    ${d.temEdicoes ? '<p>Há projeções editadas nesta sessão, sublinhadas na tabela. <button class="ap-note-action" data-reset>Restaurar projeções calculadas</button></p>' : ''}
    ${d.erros.length || d.alertas.length ? `<details><summary>Notas da projeção (${d.erros.length} erros, ${d.alertas.length} alertas)</summary><ul>${[...d.erros,...d.alertas].map(a => `<li>${esc(a)}</li>`).join('')}</ul></details>` : ''}</footer>
    <dialog class="ap-dialog" id="ap-edit" aria-labelledby="ap-edit-title"><form><h2 id="ap-edit-title">Editar projeção</h2><p class="ap-dialog-description" id="ap-edit-description"></p><label for="ap-value">Novo valor (R$)</label><input id="ap-value" name="valor" type="number" step="0.01" required><div class="ap-dialog-actions"><button type="button" data-cancel>Cancelar</button><button type="submit">Aplicar</button></div></form></dialog>
    <dialog class="ap-dialog" id="ap-filters" aria-labelledby="ap-filters-title"><form><h2 id="ap-filters-title">Referência da comparação</h2><label for="ap-exercise">Exercício</label><select id="ap-exercise">${d.anosExecucao.map(v => `<option value="${v}" ${v===Math.floor(d.referencia/100) ? 'selected' : ''}>${v}</option>`).join('')}</select><label for="ap-reference">Mês de referência (data-base)</label><select id="ap-reference">${d.mesesDisponiveis.filter(v => Math.floor(v/100) === Math.floor(d.referencia/100)).map(v => `<option value="${v}" ${v===d.referencia ? 'selected' : ''}>${months[v%100-1]}/${Math.floor(v/100)}</option>`).join('')}</select><label for="ap-budget">Dotação de referência</label><select id="ap-budget">${d.anosDotacao.map(v => `<option value="${v}" ${v===d.anoDotacao ? 'selected' : ''}>${v}</option>`).join('')}</select><p class="ap-dialog-description">O exercício escolhido nunca mistura meses de anos diferentes na mesma referência. Meses até a data-base são executados; os seguintes são projetados. Os ajustes manuais ficam restritos à referência escolhida nesta sessão.</p><div class="ap-dialog-actions"><button type="button" data-cancel>Cancelar</button><button type="submit">Atualizar</button></div></form></dialog>
  </section>`;
  root.querySelectorAll('.ap-wrap').forEach((el,i) => { el.scrollLeft = scrolls[i] || 0; });

  // Hover do saldo remanescente: guia vertical, ponto e dica com o valor exato do mês.
  root.querySelectorAll('.ap-mini-plot').forEach(plot => {
    const cross = plot.querySelector('.ap-svg-cross'), dot = plot.querySelector('.ap-svg-dot'), tip = plot.querySelector('.ap-tip');
    plot.querySelectorAll('.ap-svg-hit').forEach(hit => {
      hit.onmouseenter = () => {
        const sr = d.serieSaldo[+hit.dataset.k], i = +hit.dataset.i, cx = chX(i), cy = +hit.dataset.y, v = sr.meses[i];
        cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.setAttribute('visibility', 'visible');
        dot.setAttribute('cx', cx); dot.setAttribute('cy', cy); dot.setAttribute('visibility', 'visible');
        tip.innerHTML = `<b>${months[i]}/${d.ano}</b> · ${i < d.mes ? 'executado' : 'projetado'}<br>Saldo <span class="${v < 0 ? 'ap-neg' : ''}">${esc(signed(v))}</span>`;
        tip.style.left = `${cx / CH.W * 100}%`; tip.style.top = `${cy / CH.H * 100}%`;
        tip.classList.toggle('ap-tip-left', i > 6);
        tip.hidden = false;
      };
    });
    plot.onmouseleave = () => { cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); tip.hidden = true; };
  });

  const showView = v => {
    root._view = v;
    root.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.view === v)));
    root.querySelectorAll('[data-panel]').forEach(p => { p.hidden = p.dataset.panel !== v; });
  };
  root.querySelectorAll('[data-view]').forEach(b => { b.onclick = () => showView(b.dataset.view); });
  root.querySelectorAll('[data-goto]').forEach(b => { b.onclick = () => { showView(b.dataset.goto); root.scrollIntoView({block: 'start'}); }; });

  const setCollapsed = (key, value) => {
    collapsed[key] = value;
    const button = root.querySelector(`[data-toggle="${CSS.escape(key)}"]`);
    if (button) {
      button.setAttribute('aria-expanded', String(!value));
      button.querySelector('.ap-arrow').textContent = value ? '▸' : '▾';
    }
    root.querySelectorAll('[data-parent]').forEach(tr => { if(tr.dataset.parent === key) tr.hidden = value; });
  };
  root.querySelectorAll('[data-toggle]').forEach(button => {
    button.onclick = () => {
      const key = button.dataset.toggle;
      collapsed[key] = !collapsed[key];
      setCollapsed(key, collapsed[key]);
    };
  });
  root.querySelectorAll('[data-expand]').forEach(b => { b.onclick = () => {
    root.querySelectorAll('[data-toggle]').forEach(t => setCollapsed(t.dataset.toggle, b.dataset.expand === '0'));
  }; });

  root.querySelectorAll('[data-cancel]').forEach(b => {b.onclick = () => b.closest('dialog').close();});
  const editDialog = root.querySelector('#ap-edit');
  let selected;
  root.querySelectorAll('[data-edit]').forEach(b => { b.onclick = () => {
    const [gi,ci,month] = b.dataset.edit.split(':').map(Number);
    selected = {row:d.grupos[gi].children[ci], month};
    root.querySelector('#ap-edit-description').textContent = `${selected.row.nome} — ${months[month-1]}/${d.ano}`;
    const input = root.querySelector('#ap-value');
    // Preserva o valor interno; a formatação com centavos é só para leitura na tabela.
    input.step = 'any';
    input.value = selected.row.meses[month-1] === null ? '' : selected.row.meses[month-1];
    editDialog.showModal(); input.focus(); input.select();
  }; });
  editDialog.querySelector('form').onsubmit = e => {
    e.preventDefault();
    const input = root.querySelector('#ap-value');
    if(!input.reportValidity() || !Number.isFinite(input.valueAsNumber)) return;
    setTriggerValue('edicao', {chave:selected.row.key, mes:selected.month, valor:input.valueAsNumber, referencia:d.referencia});
    editDialog.close();
  };
  const filters = root.querySelector('#ap-filters');
  root.querySelector('.ap-data-base').onclick = () => filters.showModal();
  const exerciseSelect = root.querySelector('#ap-exercise');
  const referenceSelect = root.querySelector('#ap-reference');
  // Exercício e "mês de referência" nunca ficam dessincronizados (pedido explícito: não
  // misturar anos numa mesma referência) — trocar o exercício repopula as opções de mês
  // na hora, sem round-trip com o servidor; o mês escolhido é sempre o mais recente
  // daquele exercício (mesmo espírito do "último mês fechado" que o Python usa como
  // padrão inicial).
  exerciseSelect.onchange = () => {
    const ano = Number(exerciseSelect.value);
    const opcoes = d.mesesDisponiveis.filter(v => Math.floor(v/100) === ano);
    referenceSelect.innerHTML = opcoes.map(v => `<option value="${v}">${months[v%100-1]}/${Math.floor(v/100)}</option>`).join('');
    if(opcoes.length) referenceSelect.value = String(opcoes[opcoes.length-1]);
  };
  filters.querySelector('form').onsubmit = e => {
    e.preventDefault();
    setTriggerValue('filtros', {referencia:Number(referenceSelect.value), anoDotacao:Number(root.querySelector('#ap-budget').value)});
    filters.close();
  };
  const reset = root.querySelector('[data-reset]');
  if(reset) reset.onclick = () => setTriggerValue('restaurar', {referencia:d.referencia});
}
