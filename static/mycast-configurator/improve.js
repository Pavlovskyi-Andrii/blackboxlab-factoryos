/* T-634 "Help us improve MyCast": an optional quiz at the bottom of the page (#270).
   Answers are sent only after the consent box is ticked. Nothing is promised that the server does not say is on:
   the gift line appears only when /api/mycast/quiz reports rewards_enabled. A small nudge appears on a repeat visit
   (or after a minute on the page), can be closed for good, and respects reduced motion. */
(function () {
  'use strict';
  var root = document.getElementById('improve');
  if (!root) return;
  var KEY = 'mycast:improve';
  var UI = {
    uk: {h: 'Допоможіть покращити MyCast', lead: 'Хвилинний квіз: що додати, що прибрати, що змінити. Необов’язково — лише якщо маєте бажання.', start: 'Пройти квіз (1 хв)', next: 'Далі', back: 'Назад', skip: 'Пропустити', send: 'Надіслати', yes: 'Так', no: 'Ні', upTo: 'до двох варіантів',
      consent: 'Погоджуюсь, щоб мої відповіді зберегли для покращення MyCast', email: 'E-mail (необов’язково) — щоб сказати, коли ваше побажання з’явиться', contact: 'Можна написати мені на цей e-mail про MyCast', free: 'Ваші слова (необов’язково)',
      thanks: 'Дякуємо! Ваші відповіді вже в роботі.', gift: 'Вам нараховано {n} днів у подарунок.', signin: 'Увійдіть у MyCast, щоб отримати подарунок за квіз.', giftNote: 'Подарунок за квіз: +{n} днів MyCast для тих, хто увійшов.',
      done: 'Ви вже пройшли цей квіз — дякуємо!', err: 'Не вдалося надіслати. Спробуйте пізніше.', limit: 'Забагато відповідей сьогодні. Спробуйте завтра.', nudge: 'Допоможіть покращити MyCast · 1 хв', close: 'Закрити', step: 'Крок {a} з {b}', changed: 'Квіз оновився — відкрийте його ще раз.'},
    ru: {h: 'Помогите улучшить MyCast', lead: 'Минутный квиз: что добавить, что убрать, что изменить. Необязательно — только если есть желание.', start: 'Пройти квиз (1 мин)', next: 'Далее', back: 'Назад', skip: 'Пропустить', send: 'Отправить', yes: 'Да', no: 'Нет', upTo: 'до двух вариантов',
      consent: 'Согласен(на), чтобы мои ответы сохранили для улучшения MyCast', email: 'E-mail (необязательно) — чтобы сообщить, когда ваше пожелание появится', contact: 'Можно написать мне на этот e-mail о MyCast', free: 'Ваши слова (необязательно)',
      thanks: 'Спасибо! Ваши ответы уже в работе.', gift: 'Вам начислено {n} дней в подарок.', signin: 'Войдите в MyCast, чтобы получить подарок за квиз.', giftNote: 'Подарок за квиз: +{n} дней MyCast для вошедших.',
      done: 'Вы уже прошли этот квиз — спасибо!', err: 'Не удалось отправить. Попробуйте позже.', limit: 'Слишком много ответов сегодня. Попробуйте завтра.', nudge: 'Помогите улучшить MyCast · 1 мин', close: 'Закрыть', step: 'Шаг {a} из {b}', changed: 'Квиз обновился — откройте его ещё раз.'},
    en: {h: 'Help us improve MyCast', lead: 'A one-minute quiz: what to add, remove or change. Optional — only if you feel like it.', start: 'Take the quiz (1 min)', next: 'Next', back: 'Back', skip: 'Skip', send: 'Send', yes: 'Yes', no: 'No', upTo: 'up to two',
      consent: 'I agree that my answers are kept to improve MyCast', email: 'E-mail (optional) — so we can tell you when your wish ships', contact: 'You may e-mail me about MyCast at this address', free: 'In your own words (optional)',
      thanks: 'Thank you! Your answers are already in the queue.', gift: '{n} free days were added to your account.', signin: 'Sign in to MyCast to get the quiz gift.', giftNote: 'Quiz gift: +{n} MyCast days for signed-in listeners.',
      done: 'You have already taken this quiz — thank you!', err: 'Could not send. Please try later.', limit: 'Too many answers today. Please try tomorrow.', nudge: 'Help improve MyCast · 1 min', close: 'Close', step: 'Step {a} of {b}', changed: 'The quiz changed — please open it again.'}
  };
  var css = '#improve{display:grid;gap:12px}#improve .iq{border:1px solid var(--edge2,#3a4470);border-radius:var(--r,18px);background:var(--glass,rgba(20,27,54,.58));padding:18px;display:grid;gap:12px}' +
    '#improve .iq h3{margin:0;font:600 18px/1.3 var(--body,system-ui)}#improve .opts{display:grid;gap:8px}#improve .opt{display:flex;gap:10px;align-items:center;text-align:left;width:100%;padding:12px 14px;border-radius:12px;border:1px solid var(--edge,#2a3360);background:transparent;color:var(--ink,#eef1ff);font:inherit;cursor:pointer}' +
    '#improve .opt[aria-pressed="true"]{border-color:var(--cyan,#4fe3ff);background:rgba(79,227,255,.08)}#improve .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;justify-content:space-between}' +
    '#improve .lnk{background:none;border:0;color:var(--mute,#a3abc9);text-decoration:underline;cursor:pointer;font:inherit;padding:8px}#improve .meta{color:var(--mute,#a3abc9);font-size:13px}#improve label{display:flex;gap:8px;align-items:flex-start;font-size:14px}' +
    '#improve input[type=email],#improve textarea{width:100%;box-sizing:border-box;border-radius:10px;border:1px solid var(--edge2,#3a4470);background:rgba(7,10,22,.6);color:var(--ink,#eef1ff);padding:10px;font:inherit}#improve textarea{min-height:70px}' +
    '#improve :focus-visible,.iqNudge :focus-visible{outline:2px solid var(--cyan,#4fe3ff);outline-offset:2px}#improve .ok{color:var(--ok,#79e8b0)}#improve .bad{color:var(--bad,#ff8f86)}' +
    '.iqNudge{position:fixed;left:16px;bottom:16px;z-index:40;display:flex;gap:6px;align-items:center;max-width:calc(100vw - 32px);padding:8px 8px 8px 14px;border-radius:999px;border:1px solid var(--edge2,#3a4470);background:var(--glass2,rgba(28,37,72,.92));color:var(--ink,#eef1ff);box-shadow:0 10px 30px -12px rgba(0,0,0,.7);animation:iqIn .4s ease-out}' +
    '.iqNudge button{background:none;border:0;color:inherit;font:600 14px/1.2 var(--body,system-ui);cursor:pointer;padding:6px}.iqNudge .x{color:var(--mute,#a3abc9);font-size:18px;padding:4px 8px}' +
    '@keyframes iqIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}@media(max-width:760px){.iqNudge{bottom:calc(84px + env(safe-area-inset-bottom))}}@media(prefers-reduced-motion:reduce){.iqNudge{animation:none}}';
  var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  var quiz = null, step = -1, answers = {}, validateAnswer = '', state = 'intro', note = '', reward = null;
  function lang() { var l = (document.documentElement.lang || 'uk').slice(0, 2); return UI[l] ? l : 'en'; }
  function u() { return UI[lang()]; }
  function tr(obj) { return (obj && (obj[lang()] || obj.en)) || ''; }
  function fmt(s, v) { return String(s).replace(/\{(\w+)\}/g, function (_, k) { return v[k]; }); }
  function mem(v) { try { if (v === undefined) return JSON.parse(localStorage.getItem(KEY) || '{}'); localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) { return {}; } }
  function el(tag, attrs, text) { var e = document.createElement(tag); for (var k in attrs || {}) { if (k === 'class') e.className = attrs[k]; else e.setAttribute(k, attrs[k]); } if (text != null) e.textContent = text; return e; }
  function steps() { var s = quiz.questions.slice(); if (quiz.validate) s.push({id: '__validate', kind: 'yesno', text: quiz.validate.text}); s.push({id: '__final', kind: 'final'}); return s; }

  function render() {
    var x = u(); root.textContent = '';
    var head = el('div', {class: 'sectionHead'}); head.appendChild(el('h2', {id: 'improveTitle'}, x.h)); root.appendChild(head);
    var box = el('div', {class: 'iq'}); root.appendChild(box);
    if (state === 'done') {
      box.appendChild(el('p', {class: 'ok', role: 'status'}, note || x.thanks));
      if (reward && reward.status === 'granted') box.appendChild(el('p', null, fmt(x.gift, {n: reward.days})));
      else if (reward && reward.status === 'none' && quiz && quiz.rewards_enabled) box.appendChild(el('p', {class: 'meta'}, x.signin));
      return;
    }
    if (state === 'intro' || !quiz) {
      box.appendChild(el('p', {class: 'meta'}, x.lead));
      if (quiz && quiz.rewards_enabled) box.appendChild(el('p', {class: 'meta'}, fmt(x.giftNote, {n: quiz.reward_days})));
      var go = el('button', {type: 'button', class: 'cta'}, x.start); go.disabled = !quiz;
      go.addEventListener('click', function () { state = 'quiz'; step = 0; render(); focusFirst(); }); box.appendChild(go);
      if (note) box.appendChild(el('p', {class: 'bad', role: 'status'}, note));
      return;
    }
    var all = steps(), q = all[step];
    box.appendChild(el('p', {class: 'meta'}, fmt(x.step, {a: step + 1, b: all.length})));
    if (q.kind === 'final') return renderFinal(box);
    var h = el('h3', {id: 'iqQ'}, tr(q.text) + (q.kind === 'multi' ? ' · ' + x.upTo : '')); box.appendChild(h);
    var opts = el('div', {class: 'opts', role: 'group', 'aria-labelledby': 'iqQ'}); box.appendChild(opts);
    var list = q.kind === 'yesno' ? [{id: 'yes', text: {uk: x.yes, ru: x.yes, en: x.yes}}, {id: 'no', text: {uk: x.no, ru: x.no, en: x.no}}] : q.options;
    list.forEach(function (o) {
      var cur = q.kind === 'yesno' ? validateAnswer : answers[q.id];
      var on = Array.isArray(cur) ? cur.indexOf(o.id) >= 0 : cur === o.id;
      var b = el('button', {type: 'button', class: 'opt', 'aria-pressed': String(!!on)}, tr(o.text));
      b.addEventListener('click', function () {
        if (q.kind === 'multi') {
          var arr = (answers[q.id] || []).slice(), i = arr.indexOf(o.id);
          if (i >= 0) arr.splice(i, 1); else if (arr.length < (q.max || 2)) arr.push(o.id);
          answers[q.id] = arr; render(); focusFirst(o.id);
        } else { if (q.kind === 'yesno') validateAnswer = o.id; else answers[q.id] = o.id; step++; render(); focusFirst(); }
      });
      b.dataset.id = o.id; opts.appendChild(b);
    });
    var row = el('div', {class: 'row'}); box.appendChild(row);
    var back = el('button', {type: 'button', class: 'lnk'}, x.back); back.disabled = step === 0;
    back.addEventListener('click', function () { step = Math.max(0, step - 1); render(); focusFirst(); }); row.appendChild(back);
    var fwd = el('button', {type: 'button', class: q.kind === 'multi' ? 'cta' : 'lnk'}, q.kind === 'multi' ? x.next : x.skip);
    fwd.addEventListener('click', function () { step++; render(); focusFirst(); }); row.appendChild(fwd);
  }

  function renderFinal(box) {
    var x = u();
    var lf = el('label', null); var ta = el('textarea', {maxlength: '500', 'aria-label': x.free, placeholder: tr(quiz.free_text)}); lf.style.display = 'grid'; lf.appendChild(el('span', null, x.free)); lf.appendChild(ta); box.appendChild(lf);
    var lc = el('label', null); var cb = el('input', {type: 'checkbox', required: 'required'}); lc.appendChild(cb); lc.appendChild(el('span', null, x.consent)); box.appendChild(lc);
    var le = el('label', null); le.style.display = 'grid'; var em = el('input', {type: 'email', autocomplete: 'email', maxlength: '254'}); le.appendChild(el('span', null, x.email)); le.appendChild(em); box.appendChild(le);
    var lk = el('label', null); var ck = el('input', {type: 'checkbox'}); lk.appendChild(ck); lk.appendChild(el('span', null, x.contact)); box.appendChild(lk);
    var row = el('div', {class: 'row'}); box.appendChild(row);
    var back = el('button', {type: 'button', class: 'lnk'}, x.back); back.addEventListener('click', function () { step--; render(); focusFirst(); }); row.appendChild(back);
    var send = el('button', {type: 'button', class: 'cta'}, x.send); send.disabled = true; row.appendChild(send);
    var msg = el('p', {class: 'bad', role: 'status', 'aria-live': 'polite'}); box.appendChild(msg);
    cb.addEventListener('change', function () { send.disabled = !cb.checked; });
    send.addEventListener('click', function () {
      send.disabled = true;
      var body = {version: quiz.version, consent: cb.checked, answers: answers, free_text: ta.value.trim()};
      if (quiz.validate && validateAnswer) body.validate = {theme: quiz.validate.theme, answer: validateAnswer};
      if (em.value.trim()) { body.email = em.value.trim(); body.contact_consent = ck.checked; }
      fetch('/api/mycast/quiz', {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', Accept: 'application/json'}, body: JSON.stringify(body)})
        .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return {ok: r.ok, status: r.status, j: j}; }); })
        .then(function (res) {
          if (res.ok || res.j.detail === 'already_answered') {
            reward = res.ok ? res.j.reward : null; note = res.ok ? '' : u().done; state = 'done';
            mem({done: quiz.version, closed: true}); hideNudge(); render(); return;
          }
          if (res.j.detail === 'quiz_changed') { state = 'intro'; note = u().changed; load(); return; }
          msg.textContent = res.status === 429 ? u().limit : (res.j.detail === 'contact_consent_required' || res.j.detail === 'bad_email' ? x.contact : u().err);
          send.disabled = !cb.checked;
        })
        .catch(function () { msg.textContent = u().err; send.disabled = !cb.checked; });
    });
    cb.focus();
  }

  function focusFirst(id) {
    var b = id ? root.querySelector('.opt[data-id="' + id + '"]') : root.querySelector('.opt');
    if (b) b.focus();
  }

  var nudge = null;
  function hideNudge() { if (nudge) { nudge.remove(); nudge = null; } }
  function showNudge() {
    var m = mem(); if (nudge || m.closed || m.done === (quiz && quiz.version) || state !== 'intro') return;
    nudge = el('div', {class: 'iqNudge', role: 'complementary', 'aria-label': u().h});
    var go = el('button', {type: 'button'}, '💬 ' + u().nudge);
    go.addEventListener('click', function () { hideNudge(); root.scrollIntoView({behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start'}); state = 'quiz'; step = 0; render(); setTimeout(focusFirst, 300); });
    var x = el('button', {type: 'button', class: 'x', 'aria-label': u().close}, '×');
    x.addEventListener('click', function () { var m2 = mem(); m2.closed = true; mem(m2); hideNudge(); });
    nudge.appendChild(go); nudge.appendChild(x); document.body.appendChild(nudge);
  }

  function load() {
    fetch('/api/mycast/quiz', {headers: {Accept: 'application/json'}, cache: 'no-store'})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (q) {
        quiz = q; if (!q) { root.hidden = true; return; }
        root.hidden = false;
        if (mem().done === q.version) { state = 'done'; note = u().done; }
        render();
        var m = mem(); m.visits = (m.visits || 0) + 1; mem(m);
        if (state === 'intro') { if (m.visits >= 2) setTimeout(showNudge, 8000); else setTimeout(showNudge, 60000); }
      })
      .catch(function () { root.hidden = true; });
  }

  new MutationObserver(function () { render(); if (nudge) { hideNudge(); showNudge(); } }).observe(document.documentElement, {attributes: true, attributeFilter: ['lang']});
  root.hidden = true;
  load();
})();
