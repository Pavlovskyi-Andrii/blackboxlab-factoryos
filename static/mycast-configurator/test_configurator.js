// #261 QA: deterministic tests for the MyCast configurator logic. Run: node static/mycast-configurator/test_configurator.js
'use strict';
const assert = require('assert');
const M = require('./configurator.js');

let passed = 0;
function test(name, fn) { fn(); passed += 1; console.log('ok -', name); }

const BOX = 'sports.boxing.ua_boxers', AI = 'tech.ai.claude', PY = 'tech.programming.python';
function ready() {
  let p = M.newProfile();
  p = M.setTopic(p, BOX, true, { kind: 'ukraine' });
  p = M.setTopic(p, AI, true);
  return p;
}

test('taxonomy ids are unique, labelled in three languages, and cover the owner categories', () => {
  const ids = Object.keys(M.INDEX);
  assert.strictEqual(new Set(ids).size, ids.length);
  for (const id of ids) for (const l of ['en', 'uk', 'ru']) assert.ok(M.topicLabel(id, l), id + ' ' + l);
  assert.deepStrictEqual(M.TAXONOMY.map(c => c.id), ['sports', 'tech', 'news', 'business', 'health', 'culture', 'travel', 'science', 'auto', 'hobbies']);
  assert.ok(ids.length >= 80, 'broad taxonomy: ' + ids.length);
});

test('topic selection needs at least two subtopics, across categories', () => {
  let p = M.setTopic(M.newProfile(), BOX, true);
  assert.deepStrictEqual(M.validate(p).map(e => e.code), ['min_topics']);
  p = M.setTopic(p, AI, true);
  assert.deepStrictEqual(M.validate(p), []);
  p = M.setTopic(p, AI, false);
  assert.deepStrictEqual(M.validate(p).map(e => e.code), ['min_topics']);
  assert.throws(() => M.setTopic(p, 'sports.boxing.nope', true));
});

test('geographic scope only where it applies; custom scope needs a place', () => {
  let p = ready();
  assert.deepStrictEqual(p.topics[BOX], { scope: { kind: 'ukraine' } });
  assert.deepStrictEqual(p.topics[AI], {});                       // AI has no geographic scope
  assert.throws(() => M.setScope(p, AI, 'world'));
  p = M.setScope(p, BOX, 'custom', '');
  assert.deepStrictEqual(M.validate(p).map(e => e.code), ['custom_place_required']);
  p = M.setScope(p, BOX, 'custom', 'Lviv <script>');
  assert.deepStrictEqual(p.topics[BOX].scope, { kind: 'custom', place: 'Lviv script' });
  assert.deepStrictEqual(M.validate(p), []);
});

test('time, timezone, frequency and duration are validated', () => {
  const p = ready();
  assert.strictEqual(p.schedule.timezone, 'Europe/Kyiv');
  const codes = patch => M.validate(M.update(p, { schedule: patch })).map(e => e.code);
  assert.deepStrictEqual(codes({ time: '24:00' }), ['bad_time']);
  assert.deepStrictEqual(codes({ time: '7:30' }), ['bad_time']);
  assert.deepStrictEqual(codes({ timezone: 'Mars/Olympus' }), ['bad_timezone']);
  assert.deepStrictEqual(codes({ timezone: 'America/New_York', time: '06:05' }), []);
  assert.deepStrictEqual(codes({ frequency: 'hourly' }), ['bad_frequency']);
  assert.deepStrictEqual(codes({ frequency: 'weekly' }), ['bad_frequency']);             // replaced by chosen days
  assert.deepStrictEqual(codes({ frequency: 'days', days: [] }), ['days_required']);
  assert.deepStrictEqual(codes({ frequency: 'days', days: ['funday'] }), ['days_required']);
  assert.deepStrictEqual(codes({ frequency: 'days', days: ['mon', 'fri'] }), []);
  assert.deepStrictEqual(M.toJSON(M.update(p, { schedule: { frequency: 'daily', days: ['mon'] } })).schedule.days, []);  // daily ignores days
  assert.deepStrictEqual(codes({ durationMin: 7 }), ['bad_duration']);
});

test('free text and custom sources are bounded and https-only', () => {
  const p = ready();
  assert.deepStrictEqual(M.validate(M.update(p, { freeText: 'x'.repeat(121) })).map(e => e.code), ['too_long']);
  assert.deepStrictEqual(M.validate(M.update(p, { customSources: ['http://example.com/rss'] })).map(e => e.code), ['bad_url']);
  assert.deepStrictEqual(M.validate(M.update(p, { customSources: ['https://example.com/rss.xml'] })), []);
});

test('no audio available: no preview, no fake state', () => {
  const out = M.makePreview(ready(), {});
  assert.strictEqual(out.ok, false);
  assert.strictEqual(out.reason, 'audio_unavailable');
  assert.strictEqual(out.profile.state, 'draft');
  assert.strictEqual(out.profile.preview, null);
});

test('browser speech gives a labelled demo, never an "AI episode"', () => {
  const out = M.makePreview(ready(), { speechSynthesis: true });
  assert.strictEqual(out.profile.state, 'preview_ready');
  assert.strictEqual(out.profile.preview.kind, 'browser_tts_demo');
  assert.strictEqual(out.profile.preview.label, 'demo_not_ai_episode');
  assert.ok(out.profile.preview.script.startsWith('Це демо MyCast, а не справжній випуск.'));
  assert.deepStrictEqual(out.profile.preview.lines.map(l => l.host), ['A', 'B']);          // two hosts take turns
  const solo = M.makePreview(M.update(ready(), { voice: { mode: 'narrator' } }), { speechSynthesis: true }).profile.preview;
  assert.deepStrictEqual(solo.lines.map(l => l.host), ['A']);
  const invalid = M.makePreview(M.newProfile(), { speechSynthesis: true });
  assert.strictEqual(invalid.ok, false);
  assert.strictEqual(invalid.reason, 'invalid');
});

test('download only with a real local file; Telegram is preferred but never shown as delivered', () => {
  const tts = M.makePreview(ready(), { speechSynthesis: true }).profile;
  assert.deepStrictEqual(M.channelStatus('download', tts.preview), { usable: false, selectable: true, reason: 'no_local_file' });
  const file = M.makePreview(ready(), { localAudioUrl: 'blob:demo' }).profile;
  assert.deepStrictEqual(M.channelStatus('download', file.preview), { usable: true, selectable: true, reason: '' });
  assert.deepStrictEqual(M.channelStatus('telegram', file.preview), { usable: false, selectable: true, reason: 'not_connected' });
  assert.strictEqual(M.newProfile().delivery, 'telegram');
});

test('Viber, WhatsApp and email are planned: visible, never selectable', () => {
  for (const ch of ['viber', 'whatsapp', 'email']) {
    assert.deepStrictEqual(M.channelStatus(ch, null), { usable: false, selectable: false, reason: 'planned' });
    assert.deepStrictEqual(M.validate(M.update(ready(), { delivery: ch })).map(e => e.code), ['channel_unavailable']);
  }
  assert.deepStrictEqual(M.validate(M.update(ready(), { delivery: 'pigeon' })).map(e => e.code), ['bad_channel']);
});

test('your own entry in each row counts as a pick, is cleaned, bounded and resets approval', () => {
  let p = M.addCustom(M.newProfile(), 'sports.football', '  Arsenal <b> ');
  assert.deepStrictEqual(p.custom, { 'sports.football': ['Arsenal b'] });
  assert.deepStrictEqual(M.validate(p).map(e => e.code), ['min_topics']);                 // one pick is not enough
  p = M.addCustom(p, 'sports.mma', 'Daniel Hutchins');
  assert.deepStrictEqual(M.validate(p), []);                                               // two custom entries are
  assert.strictEqual(M.addCustom(p, 'sports.football', 'arsenal b'), p);                   // duplicate ignored
  assert.throws(() => M.addCustom(p, 'sports.chess', 'x'));
  for (let i = 0; i < 9; i++) p = M.addCustom(p, 'news.local', 'k' + i);
  assert.strictEqual(p.custom['news.local'].length, M.MAX_CUSTOM_PER_GROUP);
  const approved = M.approve(M.markReviewed(M.makePreview(p, { speechSynthesis: true }).profile), true, 't');
  const edited = M.removeCustom(approved, 'sports.mma', 0);
  assert.strictEqual(edited.state, 'draft');
  assert.strictEqual(edited.custom['sports.mma'], undefined);
});

test('social follows: handle or link on the platform\'s own domain, https only, de-duplicated', () => {
  let p = M.addFollow(ready(), 'x', '@elonmusk');
  p = M.addFollow(p, 'youtube', 'https://www.youtube.com/@Veritasium/');
  assert.deepStrictEqual(p.follows, [{ platform: 'x', value: '@elonmusk' }, { platform: 'youtube', value: 'https://youtube.com/@Veritasium' }]);
  assert.strictEqual(M.addFollow(p, 'x', '@ElonMusk'), p);                                  // duplicate ignored
  for (const [pl, v] of [['youtube', 'https://evil.example/@x'], ['x', 'http://x.com/a'], ['telegram', 'javascript:alert(1)'], ['myspace', 'a'], ['x', '  ']]) {
    assert.throws(() => M.addFollow(p, pl, v), pl + ' ' + v);
  }
  assert.deepStrictEqual(M.normalizeFollow('telegram', 'https://t.me/s/kyivindependent'), { platform: 'telegram', value: 'https://t.me/s/kyivindependent' });
  assert.ok(M.SUGGESTED_FOLLOWS.every(f => M.normalizeFollow(f.platform, f.value)));
  assert.deepStrictEqual(M.toJSON(p).follows[0], { platform: 'x', value: '@elonmusk' });
});

test('share link round-trips the settings, never the state, and rejects garbage', () => {
  let p = M.setTopic(M.newProfile(), BOX, true, { kind: 'ukraine' });
  p = M.setTopic(p, 'news.local.events', true); p = M.setScope(p, 'news.local.events', 'custom', 'Lviv');
  p = M.addCustom(p, 'sports.football', 'Arsenal'); p = M.addFollow(p, 'x', '@ZelenskyyUa');
  p = M.update(p, { schedule: { frequency: 'days', days: ['mon', 'fri'], time: '06:45' }, voice: { language: 'en' }, freeText: 'chess' });
  const approved = M.approve(M.markReviewed(M.makePreview(p, { speechSynthesis: true }).profile), true, 't');
  const code = M.encodeShare(approved);
  assert.ok(/^[A-Za-z0-9_-]+$/.test(code) && code.length < 600, code.length);
  const back = M.decodeShare(code);
  assert.strictEqual(back.state, 'draft');
  assert.strictEqual(back.preview, null);
  const a = M.toJSON(approved), b = M.toJSON(back);
  for (const k of ['topics', 'custom', 'follows', 'schedule', 'voice', 'free_text']) assert.deepStrictEqual(b[k], a[k], k);
  assert.throws(() => M.decodeShare('not-a-code'));
  assert.throws(() => M.decodeShare(''));
});

test('old saved drafts migrate: watch list -> follows, weekly -> chosen days, planned channel -> Telegram', () => {
  const old = { version: 1, topics: { [BOX]: { scope: { kind: 'world' } }, 'gone.topic.x': {} }, watchList: [{ kind: 'athlete', value: 'Usyk' }],
    schedule: { timezone: 'Europe/Kyiv', time: '07:30', frequency: 'weekly', weekday: 'wed', durationMin: 10 }, delivery: 'viber', state: 'approved' };
  const p = M.migrate(old);
  assert.deepStrictEqual(Object.keys(p.topics), [BOX]);
  assert.deepStrictEqual(p.follows, [{ platform: 'web', value: 'Usyk' }]);
  assert.deepStrictEqual([p.schedule.frequency, p.schedule.days, p.schedule.weekday], ['days', ['wed'], undefined]);
  assert.deepStrictEqual([p.delivery, p.state], ['telegram', 'draft']);
});

test('new categories: automotive and food/hobbies, with scope only where it applies', () => {
  assert.ok(M.INDEX['auto.cars.ev'].geo);
  assert.strictEqual(M.INDEX['hobbies.making.pets'].geo, false);
  assert.ok(M.search('кава', 'uk').includes('hobbies.food.coffee'));
});

test('approval needs preview, review and explicit confirmation', () => {
  let p = ready();
  assert.throws(() => M.markReviewed(p));
  p = M.makePreview(p, { speechSynthesis: true }).profile;
  assert.throws(() => M.approve(p, true));                        // not reviewed yet
  p = M.markReviewed(p);
  assert.throws(() => M.approve(p, false));                       // no explicit confirmation
  p = M.approve(p, true, '2026-11-05T22:00:00Z');
  assert.strictEqual(p.state, 'approved');
  assert.strictEqual(M.toJSON(p).active, false);                  // approval never activates delivery here
});

test('any edit after preview or approval invalidates it', () => {
  let p = M.approve(M.markReviewed(M.makePreview(ready(), { speechSynthesis: true }).profile), true, 't');
  for (const edit of [x => M.setTopic(x, PY, true), x => M.setScope(x, BOX, 'world'),
    x => M.update(x, { voice: { language: 'en' } }), x => M.update(x, { schedule: { time: '08:00' } })]) {
    const after = edit(p);
    assert.strictEqual(after.state, 'draft');
    assert.strictEqual(after.preview, null);
    assert.strictEqual(after.approvedAt, null);
  }
});

test('search finds topics in any language; profile JSON uses stable ids', () => {
  assert.ok(M.search('бокс', 'uk').includes('sports.boxing.pro'));
  assert.ok(M.search('triathlon', 'uk').includes('sports.endurance.triathlon'));
  assert.ok(M.search('', 'uk').length === Object.keys(M.INDEX).length);
  const json = M.toJSON(ready());
  assert.deepStrictEqual(json.topics.map(t => t.id), [BOX, AI].sort());
  assert.strictEqual(json.delivery.channel, 'telegram');
  assert.strictEqual(json.delivery.status, 'not_connected');
  assert.deepStrictEqual([json.follows, json.custom], [[], []]);
  assert.strictEqual(json.state, 'draft');
});

console.log(`MyCast configurator tests passed: ${passed}`);
