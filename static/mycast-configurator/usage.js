/* T-633 consent-aware usage events for the pilot pages (#270, M5).
   <section id="usage" data-api="/api/…/usage" data-product="MyBrief" data-key="mybrief" data-used="#show" hidden>
   Nothing is sent, and no code is created, before the visitor presses "Allow". After that the browser keeps one random
   code in its own storage and tells the same site three things: opened (activated), did the main action (used — a
   click or submit on the data-used selector, or window.factoryUsage.used()), came back on a later day (returned).
   The visitor can see what is stored and delete it here. First-party only: no cookies, no third-party analytics.
   The consent texts below are version CONSENT_VERSION in mvp_usage.py: change them together. */
(function () {
  'use strict';
  var root = document.getElementById('usage');
  if (!root) return;
  var API = root.getAttribute('data-api') || '/api/mycast/usage';
  var PRODUCT = root.getAttribute('data-product') || 'MyCast';
  var KEY = (root.getAttribute('data-key') || 'mycast') + ':usage';
  var USED = root.getAttribute('data-used') || '';
  var USED_ON = root.getAttribute('data-used-on') || 'click';
  var UI = {
    uk: {h: 'Анонімний підрахунок використання', ask: 'Допоможіть покращити %P%: чи можна анонімно рахувати ваші візити? Ми зберігаємо лише три дати — день, коли ви вперше відкрили %P%, день першого використання і день, коли ви повернулися, — під випадковим кодом, який лежить у цьому браузері. Без імені, e-mail, IP-адреси чи вмісту сторінки; без сторонньої аналітики. Переглянути або видалити дані можна тут будь-коли.',
      allow: 'Дозволити', no: 'Ні, дякую', on: 'Анонімний підрахунок використання увімкнено.', show: 'Показати, що збережено', del: 'Видалити мої дані та зупинити', off: 'Анонімний підрахунок використання вимкнено.', turnOn: 'Увімкнути',
      deleted: 'Видалено. Про ваші візити нічого не зберігається.', err: 'Не вдалося звернутися до сервера. Спробуйте пізніше.', none: 'Про вас нічого не збережено.'},
    ru: {h: 'Анонимный подсчёт использования', ask: 'Помогите улучшить %P%: можно ли анонимно считать ваши визиты? Мы храним только три даты — день, когда вы впервые открыли %P%, день первого использования и день, когда вы вернулись, — под случайным кодом, который лежит в этом браузере. Без имени, e-mail, IP-адреса и содержимого страницы; без сторонней аналитики. Посмотреть или удалить данные можно здесь в любой момент.',
      allow: 'Разрешить', no: 'Нет, спасибо', on: 'Анонимный подсчёт использования включён.', show: 'Показать, что сохранено', del: 'Удалить мои данные и остановить', off: 'Анонимный подсчёт использования выключен.', turnOn: 'Включить',
      deleted: 'Удалено. О ваших визитах ничего не хранится.', err: 'Не удалось обратиться к серверу. Попробуйте позже.', none: 'О вас ничего не сохранено.'},
    en: {h: 'Anonymous usage counting', ask: 'Help improve %P%: may we count your visits anonymously? We keep only three dates — the day you first opened %P%, the day you first used it and the day you came back — under a random code that stays in this browser. No name, e-mail, IP address or page content; no third-party analytics. You can view or delete the data here at any time.',
      allow: 'Allow', no: 'No, thanks', on: 'Anonymous usage counting is on.', show: 'Show what is stored', del: 'Delete my data and stop', off: 'Anonymous usage counting is off.', turnOn: 'Turn on',
      deleted: 'Deleted. Nothing is stored about your visits.', err: 'Could not reach the server. Please try later.', none: 'Nothing is stored about you.'}
  };
  Object.keys(UI).forEach(function (l) { Object.keys(UI[l]).forEach(function (k) { UI[l][k] = UI[l][k].split('%P%').join(PRODUCT); }); });
  var css = '#usage{margin-top:18px;border:1px solid var(--edge2,#3a4470);border-radius:var(--r,18px);padding:14px 16px;display:grid;gap:10px;font-size:14px}#usage h2{margin:0;font:600 15px/1.3 var(--body,system-ui)}#usage p{margin:0}' +
    '#usage .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}#usage button{font:600 14px var(--body,system-ui);padding:9px 14px;border-radius:10px;border:1px solid var(--edge2,#3a4470);background:transparent;color:inherit;cursor:pointer;min-height:40px}' +
    '#usage button.yes{border:0;background:var(--cyan,#4fe3ff);color:#08101f}#usage button:focus-visible{outline:2px solid var(--cyan,#4fe3ff);outline-offset:2px}#usage pre{margin:0;white-space:pre-wrap;word-break:break-word;font-size:12px}';
  var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  var cfg = null, note = '', shown = '', usedSent = false;
  function lang() { var l = (document.documentElement.lang || 'uk').slice(0, 2); return UI[l] ? l : 'en'; }
  function u() { return UI[lang()]; }
  function mem(v) { try { if (v === undefined) return JSON.parse(localStorage.getItem(KEY) || '{}'); localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) { return {}; } }
  function el(tag, attrs, text) { var e = document.createElement(tag); for (var k in attrs || {}) { if (k === 'class') e.className = attrs[k]; else e.setAttribute(k, attrs[k]); } if (text != null) e.textContent = text; return e; }
  function consented() { var m = mem(); return !!(cfg && cfg.enabled && m.token && m.v === cfg.consent_version); }
  function newToken() { var a = new Uint8Array(24); crypto.getRandomValues(a); return Array.prototype.map.call(a, function (b) { return ('0' + b.toString(16)).slice(-2); }).join(''); }
  function post(body) {
    return fetch(API, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', Accept: 'application/json'}, body: JSON.stringify(body)})
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw new Error(j.detail || String(r.status)); return j; }); });
  }
  function send(event) {
    if (!consented()) return;
    var m = mem();
    post({action: 'event', event: event, consent: true, consent_version: m.v, participant: m.token}).catch(function () {});
  }
  function btn(text, cls, fn) { var b = el('button', {type: 'button', class: cls || ''}, text); b.addEventListener('click', fn); return b; }

  function render() {
    var x = u(), m = mem();
    root.textContent = '';
    if (!cfg || (!cfg.enabled && !m.token)) { root.hidden = true; return; }
    root.hidden = false;
    root.appendChild(el('h2', {id: 'usageTitle'}, x.h));
    var row = el('div', {class: 'row'});
    if (consented() || (m.token && !cfg.enabled)) {
      root.appendChild(el('p', null, cfg.enabled ? x.on : x.off));
      row.appendChild(btn(x.show, '', function () {
        post({action: 'export', participant: mem().token}).then(function (j) { shown = j.records && j.records.length ? JSON.stringify(j.records, null, 1) : u().none; note = ''; render(); })
          .catch(function () { note = u().err; render(); });
      }));
      row.appendChild(btn(x.del, '', function () {
        post({action: 'delete', participant: mem().token}).then(function () { mem({declined: true}); shown = ''; note = u().deleted; render(); })
          .catch(function () { note = u().err; render(); });
      }));
    } else if (m.declined && m.v !== 'ask') {
      root.appendChild(el('p', null, x.off));
      row.appendChild(btn(x.turnOn, '', function () { var k = mem(); k.v = 'ask'; mem(k); note = ''; render(); }));
    } else {
      root.appendChild(el('p', null, x.ask));
      row.appendChild(btn(x.allow, 'yes', function () {
        var k = mem(); mem({token: k.token || newToken(), v: cfg.consent_version}); note = ''; send('activated'); render();
      }));
      row.appendChild(btn(x.no, '', function () {
        var k = mem(); if (k.token) post({action: 'delete', participant: k.token}).catch(function () {});  // asked again and refused: drop the old record too
        mem({declined: true}); note = ''; render();
      }));
    }
    root.appendChild(row);
    if (shown) root.appendChild(el('pre', {tabindex: '0'}, shown));
    if (note) root.appendChild(el('p', {role: 'status'}, note));
  }

  function used() { if (usedSent || !consented()) return; usedSent = true; send('used'); }
  window.factoryUsage = {used: used};
  if (USED) document.addEventListener(USED_ON, function (e) { if (e.target && e.target.closest && e.target.closest(USED)) used(); }, true);

  root.setAttribute('aria-labelledby', 'usageTitle');
  root.hidden = true;
  fetch(API, {headers: {Accept: 'application/json'}, cache: 'no-store', credentials: 'same-origin'})
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (c) { cfg = c; render(); send('returned'); })
    .catch(function () { root.hidden = true; });
  new MutationObserver(render).observe(document.documentElement, {attributes: true, attributeFilter: ['lang']});
})();
