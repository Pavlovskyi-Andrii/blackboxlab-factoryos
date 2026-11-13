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
  assert.deepStrictEqual(codes({ durationMin: 31 }), ['bad_duration']);
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

test('a Gemini-voiced demo is real audio and downloadable, but still labelled a demo', () => {
  const out = M.makePreview(ready(), { demoAudioUrl: '/api/mycast/demo/j/audio', speechSynthesis: true });
  assert.deepStrictEqual([out.profile.preview.kind, out.profile.preview.label], ['gemini_demo', 'demo_not_episode']);
  assert.deepStrictEqual(M.channelStatus('download', out.profile.preview), { usable: true, selectable: true, reason: '' });
  assert.deepStrictEqual(M.toJSON(out.profile).preview, { kind: 'gemini_demo' });
});

test('#281 voices: male narrator, male+female pair, mode switch keeps a valid pick, edits reset approval, shared', () => {
  let p = ready();
  assert.deepStrictEqual(p.voice.voices, ['Charon', 'Kore']);
  p = M.setVoice(p, 0, 'Puck'); p = M.setVoice(p, 1, 'Leda');
  assert.deepStrictEqual(p.voice.voices, ['Puck', 'Leda']);
  assert.throws(() => M.setVoice(p, 0, 'Kore'));                                  // host A must be male by ear
  assert.throws(() => M.setVoice(p, 1, 'Puck'));                                  // host B female, and different
  assert.throws(() => M.setVoice(p, 1, 'Nobody'));
  const solo = M.update(p, { voice: { mode: 'narrator' } });
  assert.deepStrictEqual(solo.voice.voices, ['Charon']);                          // two picks do not fit one host
  assert.deepStrictEqual(M.validate(solo), []);
  const approved = M.approve(M.markReviewed(M.makePreview(p, { speechSynthesis: true }).profile), true, 't');
  assert.strictEqual(M.setVoice(approved, 0, 'Orus').state, 'draft');             // a new voice drops approval
  assert.deepStrictEqual(M.decodeShare(M.encodeShare(p)).voice.voices, ['Puck', 'Leda']);
  assert.deepStrictEqual(M.validate({ ...p, voice: { ...p.voice, voices: ['Kore', 'Puck'] } }).map(e => e.code), ['bad_voices']);
  assert.strictEqual(M.GEMINI_VOICES.length, 30);
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

test('a free search offers narrower sub-topics that become valid own entries (owner request 2026-11-08)', () => {
  const list = M.suggestSubtopics('growth hacking', 'uk');
  assert.strictEqual(list[0], 'Growth hacking');
  assert.ok(list.includes('Growth hacking: ідеї для стартапів') && list.includes('Growth hacking: для готового бізнесу'));
  assert.ok(list.every(v => v.length <= 40));
  assert.ok(M.suggestSubtopics('growth hacking', 'en').includes('Growth hacking: ideas for startups'));
  assert.deepStrictEqual(M.suggestSubtopics(' a ', 'uk'), []);
  assert.ok(M.suggestSubtopics('<b>x</b>yz', 'uk').every(v => !/[<>]/.test(v)));
  assert.strictEqual(M.guessGroup('growth hacking', 'uk'), 'business.entrepreneurship');
  assert.strictEqual(M.guessGroup('бокс', 'uk'), 'sports.boxing');           // a real topic match wins
  assert.strictEqual(M.guessGroup('інші новини', 'uk'), 'news.headlines');   // "ші" inside a word is not AI
  assert.strictEqual(M.guessGroup('AI agents', 'en'), 'tech.ai');
  let p = M.newProfile();
  for (const v of list.slice(1, 3)) p = M.addCustom(p, M.guessGroup('growth hacking', 'uk'), v);
  assert.deepStrictEqual(M.validate(p), []);                                 // two narrow topics are enough to start
  assert.strictEqual(M.decodeShare(M.encodeShare(p)).custom['business.entrepreneurship'].length, 2);
});

test('calendar wishes (birthdays, events) are stored, shared and never claimed as connected', () => {
  let p = M.newProfile();
  assert.deepStrictEqual(p.calendar, { birthdays: false, events: false });
  p = M.setCalendar(p, 'birthdays', true);
  assert.strictEqual(M.toJSON(p).calendar.status, 'not_connected');           // nothing reads a calendar yet
  assert.deepStrictEqual(M.decodeShare(M.encodeShare(p)).calendar, { birthdays: true, events: false });
  assert.deepStrictEqual(M.migrate({ version: 1 }).calendar, { birthdays: false, events: false });   // old drafts
  assert.deepStrictEqual(M.migrate({ version: 1, calendar: { birthdays: 'yes' } }).calendar.birthdays, false);
  assert.throws(() => M.setCalendar(p, 'emails', true));
});


/* Owner request 2026-11-11: the episode timeline. */
const NEWS = 'news.headlines.international';
function planned() {
  let p = M.setTopic(M.newProfile(), BOX, true);
  p = M.setTopic(p, AI, true);
  return p;
}
const ids = p => M.planFromProfile(p).map(i => i.id);

test('timeline: derived from picks, greeting locked first, calendar at the end, new segments before it', () => {
  assert.ok(M.INDEX[NEWS], 'news topic exists');
  let p = planned();
  assert.deepStrictEqual(ids(p), ['greet', 'interests']);
  p = M.setTopic(p, NEWS, true);
  p = M.addFollow(p, 'telegram', '@channel');
  p = M.setCalendar(p, 'birthdays', true);
  assert.deepStrictEqual(ids(p), ['greet', 'news', 'interests', 'f:telegram:@channel', 'cal']);
  const plan = M.planFromProfile(p);
  assert.deepStrictEqual(plan.map(i => i.sec), [20, 120, 120, 120, 30]);
  assert.strictEqual(M.planTotal(plan), 410);
  assert.strictEqual(M.planLimitSec(p), 600);
  assert.ok(plan[0].locked && !plan[1].locked);
  assert.strictEqual(M.planLabel(plan[3], 'uk'), 'Telegram @channel');
  assert.strictEqual(M.planLabel(plan[4], 'uk'), 'Google Календар');
  assert.strictEqual(M.planLabel(plan[1], 'ru'), 'Новости');
  // an edited plan keeps its order; a new follow goes in before the trailing calendar
  p = M.movePlanItem(p, 'interests', 1);
  p = M.addFollow(p, 'youtube', '@veritasium');
  assert.deepStrictEqual(ids(p), ['greet', 'interests', 'news', 'f:telegram:@channel', 'f:youtube:@veritasium', 'cal']);
  // events alone also make a calendar block; no calendar wish, no block
  assert.ok(ids(M.setCalendar(planned(), 'events', true)).includes('cal'));
  assert.ok(!ids(M.setCalendar(p, 'birthdays', false)).includes('cal'));
  // the free-text topic alone is a personal interest
  assert.deepStrictEqual(ids(M.update(M.newProfile(), { freeText: 'chess' })), ['greet', 'interests']);
});

test('timeline: the greeting cannot move or be removed; moves are clamped after it', () => {
  let p = M.setCalendar(M.addFollow(M.setTopic(planned(), NEWS, true), 'x', '@elonmusk'), 'events', true);
  assert.strictEqual(M.movePlanItem(p, 'greet', 3), p);
  assert.strictEqual(M.removePlanItem(p, 'greet'), p);
  p = M.movePlanItem(p, 'cal', 0);                                     // index 0 is the greeting's: lands at 1
  assert.deepStrictEqual(ids(p), ['greet', 'cal', 'news', 'interests', 'f:x:@elonmusk']);
  p = M.movePlanItem(p, 'cal', 99);
  assert.deepStrictEqual(ids(p), ['greet', 'news', 'interests', 'f:x:@elonmusk', 'cal']);
  p = M.movePlanItem(p, 'f:x:@elonmusk', 1);
  assert.deepStrictEqual(ids(p), ['greet', 'f:x:@elonmusk', 'news', 'interests', 'cal']);
  assert.strictEqual(M.movePlanItem(p, 'nope', 2), p);
  assert.strictEqual(M.movePlanItem(p, 'news', 2), p);                 // already there: unchanged
});

test('timeline: durations stay within 15 s and 5 min', () => {
  let p = planned();
  p = M.setPlanDuration(p, 'interests', 135);
  assert.strictEqual(M.planFromProfile(p)[1].sec, 135);
  assert.strictEqual(M.planFromProfile(M.setPlanDuration(p, 'interests', 1)).find(i => i.id === 'interests').sec, M.PLAN_MIN_SEC);
  assert.strictEqual(M.planFromProfile(M.setPlanDuration(p, 'interests', 9999)).find(i => i.id === 'interests').sec, M.PLAN_MAX_SEC);
  assert.strictEqual(M.setPlanDuration(p, 'interests', 'abc'), p);
  assert.strictEqual(M.setPlanDuration(p, 'missing', 60), p);
  assert.strictEqual(M.planFromProfile(M.setPlanDuration(p, 'greet', 45))[0].sec, 45);   // greeting: length only
  assert.deepStrictEqual([M.PLAN_MIN_SEC, M.PLAN_MAX_SEC, M.PLAN_STEP_SEC], [15, 300, 15]);
});

test('timeline: remove and restore a block; deselected sources drop out; edits reset approval', () => {
  let p = M.setCalendar(M.addFollow(M.setTopic(planned(), NEWS, true), 'telegram', '@a'), 'birthdays', true);
  p = M.removePlanItem(p, 'news');
  assert.deepStrictEqual(ids(p), ['greet', 'interests', 'f:telegram:@a', 'cal']);
  assert.deepStrictEqual(M.planRemoved(p).map(i => i.id), ['news']);
  assert.strictEqual(M.removePlanItem(p, 'news'), p);
  assert.strictEqual(M.planTotal(M.planFromProfile(p)), 20 + 120 + 120 + 30);
  p = M.restorePlanItem(p, 'news');
  assert.deepStrictEqual(ids(p), ['greet', 'news', 'interests', 'f:telegram:@a', 'cal']);   // back where it was
  assert.strictEqual(M.restorePlanItem(p, 'news'), p);
  p = M.removeFollow(p, 0);
  assert.deepStrictEqual(ids(p), ['greet', 'news', 'interests', 'cal']);
  p = M.setTopic(p, NEWS, false);
  assert.deepStrictEqual(ids(p), ['greet', 'interests', 'cal']);
  const approved = M.approve(M.markReviewed(M.makePreview(p, { speechSynthesis: true }).profile), true, 't');
  for (const edit of [x => M.movePlanItem(x, 'cal', 1), x => M.setPlanDuration(x, 'cal', 60), x => M.removePlanItem(x, 'cal')]) {
    assert.strictEqual(edit(approved).state, 'draft');
  }
});

test('timeline: drafts without a plan migrate; bad saved plans are cleaned', () => {
  const old = { version: 1, topics: { [BOX]: { scope: { kind: 'world' } }, [AI]: {} }, calendar: { birthdays: true } };
  const p = M.migrate(old);
  assert.strictEqual(p.plan, null);
  assert.deepStrictEqual(ids(p), ['greet', 'interests', 'cal']);
  const q = M.migrate({ ...old, plan: [{ id: 'cal', sec: 9999 }, { id: 'greet', off: true }, null, { id: 'interests', sec: 'x', off: true }, { id: 'cal', sec: 20 }, { id: 'ghost', sec: 60 }] });
  assert.deepStrictEqual(q.plan, [{ id: 'cal', sec: 300 }, { id: 'greet' }, { id: 'interests', off: true }, { id: 'ghost', sec: 60 }]);
  assert.deepStrictEqual(ids(q), ['greet', 'cal']);                    // unknown "ghost" is ignored, interests stays removed
  assert.deepStrictEqual(M.planRemoved(q).map(i => [i.id, i.sec]), [['interests', 120]]);
  assert.deepStrictEqual(M.validate(q), []);
  assert.strictEqual(M.migrate({ version: 1, plan: 'junk' }).plan, null);
});

test('timeline: share link and JSON carry the plan; links without a plan still decode', () => {
  let p = M.setCalendar(M.addFollow(M.setTopic(planned(), NEWS, true), 'youtube', 'https://www.youtube.com/@veritasium'), 'birthdays', true);
  const plainCode = M.encodeShare(p);                                  // no edits yet: no "pl" key, same as before
  assert.ok(!JSON.parse(Buffer.from(plainCode.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8')).pl);
  assert.strictEqual(M.decodeShare(plainCode).plan, null);
  p = M.movePlanItem(p, 'cal', 1);
  p = M.setPlanDuration(p, 'f:youtube:https://youtube.com/@veritasium', 75);
  p = M.removePlanItem(p, 'news');
  const back = M.decodeShare(M.encodeShare(p));
  assert.deepStrictEqual(M.planFromProfile(back), M.planFromProfile(p));
  assert.deepStrictEqual(M.planRemoved(back).map(i => i.id), ['news']);
  const a = M.toJSON(p), b = M.toJSON(back);
  for (const k of ['topics', 'custom', 'follows', 'schedule', 'voice', 'free_text', 'calendar', 'plan', 'plan_removed', 'plan_total_sec']) assert.deepStrictEqual(b[k], a[k], k);
  assert.deepStrictEqual(a.plan.map(i => i.id), ['greet', 'cal', 'interests', 'f:youtube:https://youtube.com/@veritasium']);
  assert.strictEqual(a.plan_total_sec, 20 + 30 + 120 + 75);
  // garbage in "pl" is ignored, never fatal
  const raw = JSON.parse(Buffer.from(M.encodeShare(p).replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8'));
  raw.pl = [['f9', 60, 0], 'x', [5], ['cal', -3, 0]];
  const odd = M.decodeShare(Buffer.from(JSON.stringify(raw), 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''));
  assert.deepStrictEqual(ids(odd), ['greet', 'news', 'interests', 'f:youtube:https://youtube.com/@veritasium', 'cal']);
  assert.strictEqual(M.planFromProfile(odd).find(i => i.id === 'cal').sec, 30);   // a bad length falls back to the default
});

test('timeline: the demo names news and interests in plan order', () => {
  let p = M.setTopic(planned(), NEWS, true);
  p = M.update(p, { voice: { language: 'en', mode: 'narrator' } });
  const first = () => M.demoLines(p)[0].text.split('Today we have: ')[1];
  assert.ok(first().startsWith(M.topicLabel(NEWS, 'en')));
  p = M.movePlanItem(p, 'interests', 1);
  assert.ok(!first().startsWith(M.topicLabel(NEWS, 'en')) && first().includes(M.topicLabel(NEWS, 'en')));
  p = M.removePlanItem(p, 'news');
  assert.ok(!first().includes(M.topicLabel(NEWS, 'en')));
  p = M.removePlanItem(p, 'interests');                                // nothing left: fall back to every pick
  assert.ok(first().includes(M.topicLabel(NEWS, 'en')));
});

test('server sub-topics are cleaned: strings only, no markup, no duplicates, at most 10', () => {
  assert.deepStrictEqual(M.cleanSubtopics(['AI agents', 'ai agents', '<b>Tools</b>', 7, null, 'x', 'A'.repeat(80)]), ['AI agents', 'bTools/b', 'A'.repeat(40)]);
  assert.deepStrictEqual(M.cleanSubtopics('nope'), []);
  assert.strictEqual(M.cleanSubtopics(Array.from({ length: 30 }, (_, i) => 'topic ' + i)).length, 10);
});

console.log(`MyCast configurator tests passed: ${passed}`);
