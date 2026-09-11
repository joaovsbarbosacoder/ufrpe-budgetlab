export default function(component) {
  const {data: d, parentElement, setTriggerValue} = component;
  const root = parentElement.querySelector('#pessoal');
  // Estado visual local: expandir uma linha não recalcula nem recarrega a página.
  const collapsed = root._collapsed || (root._collapsed = {});
  const scrolls = [...root.querySelectorAll('.ap-wrap')].map(el => el.scrollLeft);
  const months = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const brl = v => v === null || v === undefined || !Number.isFinite(v) ? '—' :
    (v < 0 ? '−' : '') + 'R$ ' + new Intl.NumberFormat('pt-BR', {maximumFractionDigits: 0}).format(Math.abs(v));
  const cssVars = Object.entries(d.cores).map(([k,v]) => `--${k}:${v}`).join(';');
  const kpis = [
    [`Executado + projetado ${d.ano}`, d.total.total, 'var(--text)'],
    ['Dotação atual', d.total.dotacao, 'var(--strong)'],
    [`Execução ${d.ano - 1}`, d.total.execAnt, 'var(--muted)'],
    ['Saldo total em dezembro', d.saldoDezembro, d.saldoDezembro < 0 ? 'var(--red)' : 'var(--green)'],
  ];
  const monthHeaders = saldo => months.map((m,i) => `<th scope="col" class="${!saldo && i >= d.mes ? 'ap-proj' : ''}">${m}</th>`).join('');
  const contextCells = (g, tag) => `<${tag}>${brl(g.total)}</${tag}><${tag} title="${g.key instanceof Array ? 'Dotação disponível somente por grupo; sem rateio por rubrica.' : ''}">${brl(g.dotacao)}</${tag}><${tag}>${brl(g.execAnt)}</${tag}><${tag} class="ap-proj">${brl(g.basePloa)}</${tag}>`;
  function row(g, group, gi, ci) {
    const tag = group ? 'th' : 'td';
    const toggle = group && !g.subtotal;
    const name = toggle ? `<button class="ap-group-button" data-toggle="${esc(g.key)}" aria-expanded="${!collapsed[g.key]}"><span class="ap-arrow">${collapsed[g.key] ? '▸' : '▾'}</span> ${esc(g.nome)}</button>` : esc(g.nome);
    const cells = g.meses.map((v,i) => {
      const future = i >= d.mes;
      const edited = (g.editados || []).includes(i+1);
      const editable = !group && g.key && future;
      return `<${tag} class="${future ? 'ap-proj' : ''}">${editable ? `<button class="ap-cell-button ${edited ? 'ap-edited' : ''}" data-edit="${gi}:${ci}:${i+1}" aria-label="Editar ${esc(g.nome)}, ${months[i]}" title="${edited ? 'Ajuste manual. ' : ''}Editar projeção de ${months[i]}">${brl(v)}</button>` : brl(v)}</${tag}>`;
    }).join('');
    return `<tr class="${g.subtotal ? 'ap-total-row' : group ? 'ap-group-row' : 'ap-child-row'}" ${group ? '' : `data-parent="${esc(d.grupos[gi].key)}" ${collapsed[d.grupos[gi].key] ? 'hidden' : ''}`}><${tag} class="ap-sticky ${toggle ? 'ap-toggle' : ''}" ${group ? 'scope="row"' : ''}>${name}</${tag}>${cells}${contextCells(g,tag)}</tr>`;
  }
  const rows = d.grupos.map((g,gi) => row(g,true,gi) + (g.children || []).map((c,ci) => row(c,false,gi,ci)).join('')).join('');
  const saldoRows = d.saldos.map(s => `<tr class="${s.subtotal ? 'ap-total-row' : ''}"><th scope="row" class="ap-sticky">${esc(s.nome)}</th>${s.meses.map(v => `<td style="color:${v < 0 ? 'var(--red)' : s.subtotal || s.key === 'rpps' ? 'var(--green)' : 'var(--text)'}">${brl(v)}</td>`).join('')}</tr>`).join('');
  const executed = d.mes === 1 ? 'Jan' : `Jan–${months[d.mes-1]}`;
  const projected = d.mes === 12 ? 'nenhum mês' : d.mes === 11 ? 'Dez' : `${months[d.mes]}–Dez`;
  const statusColor = d.aviso.tipo === 'error' ? 'var(--red)' : d.aviso.tipo === 'success' ? 'var(--green)' : 'var(--accent)';
  const reconciliation = d.reconciliacao;
  root.innerHTML = `<section class="ap-page" style="${esc(cssVars)}" aria-label="Acompanhamento de Pessoal">
    <header class="ap-nav"><div class="ap-brand-wrap"><h1 class="ap-brand">Acompanhamento de Pessoal</h1><span class="ap-uo">UO 26248 — UFRPE</span></div><button class="ap-data-base" title="Alterar mês e dotação de referência" aria-label="Alterar data-base">Data-base: ${esc(d.dataBase)}</button></header>
    <div class="ap-kpis">${kpis.map(([label,value,color]) => `<div class="ap-kpi"><div class="ap-kpi-label">${esc(label)}</div><div class="ap-kpi-value" style="color:${color}">${brl(value)}</div></div>`).join('')}</div>
    <div class="ap-alert" role="status" style="--status:${statusColor}"><span class="ap-alert-label">${d.aviso.tipo === 'success' ? 'Situação' : 'Alerta'}</span><span>${esc(d.aviso.texto)}</span></div>
    <div class="ap-legend"><span><span class="ap-dot"></span>Executado (${executed})</span><span><span class="ap-dot ap-dot-proj"></span>Projetado (${projected})</span><span class="ap-reconciliation">Diferença Exec. Ano Anterior vs. base validada: ${brl(reconciliation.diferenca)} — ver nota</span></div>
    <div class="ap-wrap ap-main-wrap" tabindex="0" role="region" aria-label="Rubrica por mês, tabela com rolagem horizontal"><table class="ap-tbl" aria-label="Rubrica por mês"><thead><tr><th scope="col" class="ap-sticky">Rubrica</th>${monthHeaders(false)}<th scope="col">Total</th><th scope="col">Dotação Atual</th><th scope="col">Exec. Ano Anterior</th><th scope="col" class="ap-proj">Base PLOA ${d.ano + 1}</th></tr></thead><tbody>${rows}</tbody></table></div>
    <section class="ap-saldo"><h2 class="ap-section-title">Saldo remanescente por grupo (dotação − executado/projetado acumulado)</h2><div class="ap-wrap" tabindex="0" role="region" aria-label="Saldos por mês, tabela com rolagem horizontal"><table class="ap-tbl" aria-label="Saldo remanescente por grupo"><thead><tr><th scope="col" class="ap-sticky">Grupo</th>${monthHeaders(true)}</tr></thead><tbody>${saldoRows}</tbody></table></div></section>
    <footer class="ap-notes"><p>Estrutura reproduzida do HTML “Acompanhamento de Pessoal”, com os dados das bases locais. Data-base ${esc(d.dataBase)}; Dotação Atualizada de ${d.anoDotacao}. “Base PLOA ${d.ano+1}” apresenta o valor do mês de referência por rubrica, sem multiplicador; 13º e férias aparecem como “—” nessa coluna porque seguem regra própria. O total de grupo conserva a soma do mês de referência.</p>
    <p>“Exec. Ano Anterior”: soma das rubricas exibidas ${brl(reconciliation.rubricas)}; base anual no mesmo escopo ${brl(reconciliation.base)}; diferença ${brl(reconciliation.diferenca)}${reconciliation.diferenca !== null && Math.abs(reconciliation.diferenca) > .01 ? ' — inclui rubricas históricas sem correspondência na grade atual' : ''}. Dotação por rubrica não disponível: não é feito rateio. Benefício Especial e Precatórios aguardam mapeamento específico e não compõem subtotais separados. Outros Benefícios mantém as ações 2004/212B do painel.</p>
    <p>${esc(d.procedencia)}</p><p>Clique no nome do grupo para recolher/expandir. Clique em um valor projetado de rubrica para editar; meses executados ficam protegidos. Clique na data-base para alterar a referência.</p>
    ${d.temEdicoes ? '<p>Há projeções editadas nesta sessão, sublinhadas na tabela. <button class="ap-note-action" data-reset>Restaurar projeções calculadas</button></p>' : ''}
    ${d.erros.length || d.alertas.length ? `<details><summary>Notas da projeção (${d.erros.length} erros, ${d.alertas.length} alertas)</summary><ul>${[...d.erros,...d.alertas].map(a => `<li>${esc(a)}</li>`).join('')}</ul></details>` : ''}</footer>
    <dialog class="ap-dialog" id="ap-edit" aria-labelledby="ap-edit-title"><form><h2 id="ap-edit-title">Editar projeção</h2><p class="ap-dialog-description" id="ap-edit-description"></p><label for="ap-value">Novo valor (R$)</label><input id="ap-value" name="valor" type="number" step="0.01" required><div class="ap-dialog-actions"><button type="button" data-cancel>Cancelar</button><button type="submit">Aplicar</button></div></form></dialog>
    <dialog class="ap-dialog" id="ap-filters" aria-labelledby="ap-filters-title"><form><h2 id="ap-filters-title">Referência da comparação</h2><label for="ap-exercise">Exercício</label><select id="ap-exercise">${d.anosExecucao.map(v => `<option value="${v}" ${v===Math.floor(d.referencia/100) ? 'selected' : ''}>${v}</option>`).join('')}</select><label for="ap-reference">Mês de referência (data-base)</label><select id="ap-reference">${d.mesesDisponiveis.filter(v => Math.floor(v/100) === Math.floor(d.referencia/100)).map(v => `<option value="${v}" ${v===d.referencia ? 'selected' : ''}>${months[v%100-1]}/${Math.floor(v/100)}</option>`).join('')}</select><label for="ap-budget">Dotação de referência</label><select id="ap-budget">${d.anosDotacao.map(v => `<option value="${v}" ${v===d.anoDotacao ? 'selected' : ''}>${v}</option>`).join('')}</select><p class="ap-dialog-description">O exercício escolhido nunca mistura meses de anos diferentes na mesma referência. Meses até a data-base são executados; os seguintes são projetados. Os ajustes manuais ficam restritos à referência escolhida nesta sessão.</p><div class="ap-dialog-actions"><button type="button" data-cancel>Cancelar</button><button type="submit">Atualizar</button></div></form></dialog>
  </section>`;
  root.querySelectorAll('.ap-wrap').forEach((el,i) => { el.scrollLeft = scrolls[i] || 0; });
  root.querySelectorAll('[data-toggle]').forEach(button => {
    button.onclick = () => {
      const key = button.dataset.toggle;
      collapsed[key] = !collapsed[key];
      button.setAttribute('aria-expanded', String(!collapsed[key]));
      button.querySelector('.ap-arrow').textContent = collapsed[key] ? '▸' : '▾';
      root.querySelectorAll('[data-parent]').forEach(tr => { if(tr.dataset.parent === key) tr.hidden = collapsed[key]; });
    };
  });
  root.querySelectorAll('[data-cancel]').forEach(b => {b.onclick = () => b.closest('dialog').close();});
  const editDialog = root.querySelector('#ap-edit');
  let selected;
  root.querySelectorAll('[data-edit]').forEach(b => { b.onclick = () => {
    const [gi,ci,month] = b.dataset.edit.split(':').map(Number);
    selected = {row:d.grupos[gi].children[ci], month};
    root.querySelector('#ap-edit-description').textContent = `${selected.row.nome} — ${months[month-1]}/${d.ano}`;
    const input = root.querySelector('#ap-value');
    // Preserva o valor interno; formatação arredondada é só para leitura na tabela.
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
