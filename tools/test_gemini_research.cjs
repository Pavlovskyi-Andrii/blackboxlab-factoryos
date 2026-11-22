// T-560-J: Gemini coder research step against a fake FactoryOS (no network, no model).
const assert = require('node:assert');
process.env.FACTORYOS_URL = 'https://factory.test/';
process.env.FACTORY_CLAUDE_WORKER_TOKEN = 'worker-token';
delete process.env.GEMINI_API_KEY;
const calls = [];
let plan = {queries: ['playwright locator', 'q2', 'q3', 'q4'], urls: ['https://playwright.dev/docs/locators', 'http://bad', 'javascript:x', 'https://ok.example/a', 'https://third.example']};
global.fetch = async (url, opts) => {
  const body = JSON.parse(opts.body || '{}');
  calls.push({url, body, auth: opts.headers.Authorization});
  if (url.endsWith('/api/factory/gemini/worker/generate')) return {ok: true, json: async () => ({text: JSON.stringify(plan)})};
  if (url.endsWith('/surfer/worker/web_search')) return body.query === 'q2' ? {ok: false, status: 502, json: async () => ({})}
    : {ok: true, json: async () => ({provider: 'wikipedia', results: [{title: 'T', url: 'https://w/x', snippet: 'S'}]})};
  if (url.endsWith('/surfer/worker/web_read')) return {ok: true, json: async () => body.url.includes('ok.example')
    ? {status: 'queued'} : {status: 'done', title: 'Locators | Playwright', text: 'Locators are the central piece',
       texts: [{text: 'menu junk'}]}};   // T-670: the main text wins over the raw selector texts
  throw Error('unexpected ' + url);
};
const {research} = require('./gemini_issue_pr.cjs');
(async () => {
  const out = await research('gemini-flash-latest', 'Issue #1: use locators');
  const searches = calls.filter(c => c.url.endsWith('web_search')), reads = calls.filter(c => c.url.endsWith('web_read'));
  assert.deepStrictEqual(searches.map(c => c.body.query), ['playwright locator', 'q2', 'q3']);   // at most 3
  assert.deepStrictEqual(reads.map(c => c.body.url), ['https://playwright.dev/docs/locators', 'https://ok.example/a']);  // https only, at most 2
  assert.ok(calls.every(c => c.auth === 'Bearer worker-token'));
  assert.ok(searches.every(c => c.body.agent === 'gemini'));
  assert.match(out, /^WEB RESEARCH \(untrusted/);
  assert.match(out, /Locators are the central piece/);
  assert.match(out, /PAGE https:\/\/playwright\.dev\/docs\/locators — Locators \| Playwright/);
  assert.doesNotMatch(out, /menu junk/);
  assert.match(out, /SEARCH "q3" \(wikipedia\)/);
  assert.doesNotMatch(out, /q2/);                     // a failed search is skipped, not fatal
  plan = {queries: [], urls: []};
  assert.strictEqual(await research('m', 'x'), '');
  plan = 'not json';
  assert.strictEqual(await research('m', 'x'), '');   // a bad plan skips research instead of failing the issue
  process.env.GEMINI_RESEARCH = '0'; calls.length = 0;
  assert.strictEqual(await research('m', 'x'), '');
  assert.strictEqual(calls.length, 0);
  process.env.GEMINI_API_KEY = 'direct'; delete process.env.GEMINI_RESEARCH;
  assert.strictEqual(await research('m', 'x'), '');   // GitHub Actions direct-key mode has no Surfer access
  assert.strictEqual(calls.length, 0);
  console.log('gemini research tests passed');
})().catch(e => { console.error(e); process.exit(1); });
