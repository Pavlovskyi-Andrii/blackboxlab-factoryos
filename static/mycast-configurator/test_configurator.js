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
  assert.deepStrictEqual(codes({ frequency: 'weekly', weekday: 'funday' }), ['weekday_required']);
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
  assert.ok(out.profile.preview.script.startsWith('Це демо-озвучка'));
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

test('watch list: typed, cleaned, de-duplicated, bounded, and it invalidates approval', () => {
  let p = M.addWatch(ready(), 'athlete', '  Oleksandr Usyk <b> ');
  assert.deepStrictEqual(p.watchList, [{ kind: 'athlete', value: 'Oleksandr Usyk b' }]);
  assert.strictEqual(M.addWatch(p, 'athlete', 'oleksandr usyk b'), p);          // duplicate ignored
  assert.strictEqual(M.addWatch(p, 'team', '   '), p);                         // empty ignored
  assert.throws(() => M.addWatch(p, 'planet', 'Mars'));
  for (let i = 0; i < 30; i++) p = M.addWatch(p, 'keyword', 'k' + i);
  assert.strictEqual(p.watchList.length, M.MAX_WATCH);
  assert.deepStrictEqual(M.toJSON(p).watch_list[0], { kind: 'athlete', value: 'Oleksandr Usyk b' });
  const approved = M.approve(M.markReviewed(M.makePreview(ready(), { speechSynthesis: true }).profile), true, 't');
  const edited = M.addWatch(approved, 'team', 'Shakhtar');
  assert.strictEqual(edited.state, 'draft');
  assert.strictEqual(M.removeWatch(edited, 0).watchList.length, 0);
  assert.strictEqual(M.removeWatch(edited, 5), edited);
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
  assert.deepStrictEqual(json.watch_list, []);
  assert.strictEqual(json.state, 'draft');
});

console.log(`MyCast configurator tests passed: ${passed}`);
