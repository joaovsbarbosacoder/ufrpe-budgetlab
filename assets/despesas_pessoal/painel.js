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

  function chart() {
    const series = d.serieSaldo.filter(s => s.meses.some(ok));
    if (!series.length) return '<p class="ap-empty">Sem dotação para calcular o saldo.</p>';
    const W = 1000, H = 300, P = {l: 120, r: 24, t: 14, b: 30};
    const valores = series.flatMap(s => s.meses.filter(ok));
    const max = Math.max(0, ...valores), min = Math.min(0, ...valores);
    const passo = (() => { const bruto = (max - min) / 5 || 1; const p = 10 ** Math.floor(Math.log10(bruto)); return [1, 2, 5, 10].map(m => m * p).find(v => v >= bruto); })();
    const x = i => P.l + i * (W - P.l - P.r) / 11;
    const y = v => P.t + (max - v) * (H - P.t - P.b) / ((max - min) || 1);
    let s = `<svg class="ap-svg" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Saldo remanescente por grupo, de janeiro a dezembro">`;
    if (d.mes < 12) s += `<rect class="ap-svg-proj" x="${x(d.mes - 1)}" y="${P.t}" width="${x(11) - x(d.mes - 1)}" height="${H - P.t - P.b}"/><text class="ap-svg-proj-label" x="${x(d.mes - 1) + 6}" y="${P.t + 12}">projetado</text>`;
    for (let v = Math.ceil(min / passo) * passo; v <= max; v += passo) {
      s += `<line class="${v === 0 ? 'ap-svg-zero' : 'ap-svg-grid'}" x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}"/><text class="ap-svg-axis" x="${P.l - 8}" y="${y(v) + 4}" text-anchor="end">${esc(new Intl.NumberFormat('pt-BR').format(v))}</text>`;
    }
    months.forEach((m, i) => { s += `<text class="ap-svg-axis" x="${x(i)}" y="${H - 8}" text-anchor="middle">${m}</text>`; });
    series.forEach(sr => {
      const cor = groupColor[sr.key] || '#0969DA';
      const pts = sr.meses.map((v, i) => ok(v) ? `${x(i)},${y(v)}` : null);
      const real = pts.slice(0, d.mes).filter(Boolean), proj = pts.slice(d.mes - 1).filter(Boolean);
      if (real.length) s += `<polyline points="${real.join(' ')}" fill="none" stroke="${cor}" stroke-width="2.4"/>`;
      if (proj.length > 1) s += `<polyline points="${proj.join(' ')}" fill="none" stroke="${cor}" stroke-width="2.4" stroke-dasharray="6 5"/>`;
      const fim = sr.meses[11];
      if (ok(fim)) s += `<circle cx="${x(11)}" cy="${y(fim)}" r="${fim < 0 ? 5 : 3.5}" fill="${fim < 0 ? 'var(--red)' : cor}" stroke="#fff" stroke-width="1.5"/>`;
    });
    s += `<text class="ap-svg-axis" x="${P.l - 8}" y="${P.t - 2}" text-anchor="end">R$</text></svg>`;
    const legenda = series.map(sr => `<span><i style="background:${groupColor[sr.key] || '#0969DA'}"></i>${esc(sr.nome)} · dez <b class="${ok(sr.meses[11]) && sr.meses[11] < 0 ? 'ap-neg' : 'ap-pos'}">${signed(sr.meses[11])}</b></span>`).join('');
    return `<div class="ap-chart-legend">${legenda}<span><i class="ap-dash"></i>Projetado</span></div>${s}`;
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
      <section class="ap-block"><h2 class="ap-section-title">Saldo remanescente mês a mês</h2><p class="ap-section-sub">Dotação − (executado + projetado acumulado). Abaixo de zero = déficit.</p><div class="ap-chart">${chart()}</div></section>
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
