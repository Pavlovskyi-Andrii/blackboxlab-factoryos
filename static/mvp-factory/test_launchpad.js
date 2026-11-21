// T-704: runtime test of launchpad.html without a browser. The page's own script runs against a small DOM stand-in.
// Run: node static/mvp-factory/test_launchpad.js
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const html = fs.readFileSync(path.join(__dirname, 'launchpad.html'), 'utf8');
const script = html.slice(html.lastIndexOf('<script>') + 8, html.lastIndexOf('</script>'));

function open(search, respond, stored) {
  const nodes = {}, buttons = ['uk', 'ru', 'en'].map(l => ({dataset: {lang: l}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener(_, fn) { this.click = fn; }}));
  const node = id => nodes[id] || (nodes[id] = {textContent: '', innerHTML: ''});
  const calls = [];
  const ctx = {
    document: {querySelector: s => node(s), querySelectorAll: () => buttons, documentElement: {lang: ''}, title: ''},
    location: {search}, URLSearchParams, encodeURIComponent, Math, JSON, String, Array, Object, Error,
    localStorage: {getItem: () => stored || null, setItem() {}},
    fetch: async (url, opts) => { calls.push({url, opts}); return respond(url); },
  };
  vm.runInNewContext(script, ctx);
  return {ctx, calls, board: () => node('#board').innerHTML, buttons, node};
}
const tick = () => new Promise(r => setTimeout(r, 5));
const check = (id, over) => Object.assign({id, phase: 'battle', types: [], target: {min: 5, max: null}, actual: 'unknown', honest_zero: false,
  levels: {}, excluded: {}, target_met: 'unknown', gate_after: null, loop: []}, over);
const gates = ['G1', 'G2', 'G3', 'G4', 'G5'].map(g => ({gate: g, who_decides: g > 'G2' ? 'owner' : 'judge_or_owner', state: 'pending', proposals: [], decision: null}));
const ok = body => ({ok: true, status: 200, json: async () => body});

(async () => {
  // 1. The project comes from the link; the default is MyCast; only the board is fetched, and only read.
  let p = open('?project=faceless-creator', () => ok({checks: [], gates, funnels: {}, needs_you: [], learn: {}}));
  await tick();
  assert.deepStrictEqual(p.calls.map(c => c.url), ['/api/mvp-factory/faceless-creator/launchpad']);
  assert.strictEqual(p.calls[0].opts.method, undefined);
  p = open('', () => ok({checks: [], gates, funnels: {}, needs_you: [], learn: {}}));
  await tick();
  assert.strictEqual(p.calls[0].url, '/api/mvp-factory/mycast/launchpad');
  p = open('?project=../../admin%3Fx%3D1', () => ok({checks: [], gates, funnels: {}, needs_you: [], learn: {}}));
  await tick();
  assert.strictEqual(p.calls[0].url, '/api/mvp-factory/adminx1/launchpad');     // nothing but [a-z0-9-] reaches the URL

  // 2. An honest zero is "0", missing data is "unknown": never the same thing on screen.
  const data = {checks: [check('D1', {actual: 0, honest_zero: true, target_met: false, excluded: {test: 0, synthetic: 6}}),
                         check('D2', {actual: 'unknown'}), check('D3', {actual: 7, target_met: false, levels: {linked: 7}})],
                gates, needs_you: [{kind: 'gate', gate: 'G1', state: 'pending'}],
                funnels: {communities: {stages: {reach: 0, clicks: 'unknown', leads: 0, main_scenario_done: 'unknown', payments: 0},
                                        largest_drop: null, blockers: [], demand_reading: 'honest_zero', entries: 1}},
                learn: {verdict: 'unknown', main_channel: 'unknown', main_metric: 'unknown', price_covers_direct_cost: 'unknown'}, artifact_count: 13};
  p = open('?project=mycast', () => ok(data), 'en');
  await tick();
  const cards = p.board().split('<div class="card">');
  const d1 = cards.find(c => c.includes('D1 ·')), d2 = cards.find(c => c.includes('D2 ·')), d3 = cards.find(c => c.includes('D3 ·'));
  assert.ok(d1.includes('<div class="big">0</div>') && d1.includes('Honest zero') && d1.includes('6 synthetic'));
  assert.ok(d2.includes('<div class="big">unknown</div>') && !d2.includes('Honest zero'));
  assert.ok(d3.includes('<div class="big">7</div>') && d3.includes('has links · 7') && d3.includes('below the target'));
  const funnel = cards.find(c => c.includes('<h3>Communities</h3>'));
  assert.ok(funnel.includes('honest zero: no leads, no payments'));
  assert.ok(/Leads<\/td><td><b>0<\/b>/.test(funnel) && /Clicks<\/td><td><b>unknown<\/b>/.test(funnel));
  assert.ok(p.board().includes('A decision is waiting') && p.board().includes('G1 ·'));

  // 3. Languages switch without another request; every visible key resolves.
  p.buttons[0].click();
  assert.ok(p.board().includes('Чесний нуль') && p.board().includes('невідомо'));
  p.buttons[1].click();
  assert.ok(p.board().includes('Честный ноль') && p.board().includes('неизвестно'));
  assert.strictEqual(p.calls.length, 1);
  assert.ok(!/>(c_|g_|ch_|st_|dr_|f_|n_|level_|phase_)[A-Za-z_0-9]+</.test(p.board()), 'a raw translation key is on screen');

  // 4. Text from the board is escaped.
  const evil = JSON.parse(JSON.stringify(data));
  evil.gates[0].state = 'decided';
  evil.gates[0].decision = {chosen: ['<img src=x onerror=alert(1)>'], rationale: '<script>alert(2)</script>', decided_by: '"><b>x'};
  p = open('?project=mycast', () => ok(evil), 'en');
  await tick();
  assert.ok(!p.board().includes('<img src=x') && !p.board().includes('<script>alert(2)') && p.board().includes('&lt;img src=x'));

  // 5. A refused or failed request shows the error state and no board.
  for (const respond of [() => ({ok: false, status: 401, json: async () => ({detail: 'authentication required'})}),
                         () => { throw new Error('offline'); }]) {
    p = open('?project=mycast', respond, 'en');
    assert.ok(p.board().includes('Loading the board'));
    await tick();
    assert.ok(p.board().includes('Could not load the board') && !p.board().includes('class="grid"'));
  }
  console.log('launchpad page tests passed');
})().catch(e => { console.error(e); process.exit(1); });
