/* MyCast configurator (#261): taxonomy, validation, profile JSON and the honest state machine.
   Pure logic, no DOM and no network: runs in the browser (window.MyCast) and in Node tests (module.exports).
   States: draft -> preview_ready (only with a real local preview) -> reviewed -> approved. Any edit after a preview
   returns to draft. Nothing here schedules, sends, publishes or generates an AI episode. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MyCast = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';
  // Stable ids; labels per language. geo: the subtopic takes a geographic scope.
  const L = (en, uk, ru) => ({ en, uk, ru });
  const TAXONOMY = [
    { id: 'sports', label: L('Sports', 'Спорт', 'Спорт'), groups: [
      { id: 'boxing', label: L('Boxing', 'Бокс', 'Бокс'), geo: true, topics: [
        ['pro', L('Professional boxing', 'Професійний бокс', 'Профессиональный бокс')],
        ['amateur', L('Amateur boxing', 'Аматорський бокс', 'Любительский бокс')],
        ['ua_boxers', L('Ukrainian boxers', 'Українські боксери', 'Украинские боксёры')],
        ['results', L('Bouts and results', 'Бої та результати', 'Бои и результаты')],
        ['rankings', L('Rankings', 'Рейтинги', 'Рейтинги')]] },
      { id: 'mma', label: L('MMA / UFC', 'ММА / UFC', 'ММА / UFC'), geo: false, topics: [
        ['ufc', L('UFC events', 'Турніри UFC', 'Турниры UFC')], ['fighters', L('Fighters', 'Бійці', 'Бойцы')]] },
      { id: 'football', label: L('Football', 'Футбол', 'Футбол'), geo: true, topics: [
        ['upl', L('Ukrainian Premier League', 'УПЛ', 'УПЛ')], ['ucl', L('Champions League', 'Ліга чемпіонів', 'Лига чемпионов')],
        ['epl', L('Premier League', 'АПЛ', 'АПЛ')], ['national', L('National teams', 'Збірні', 'Сборные')],
        ['transfers', L('Transfers', 'Трансфери', 'Трансферы')]] },
      { id: 'basketball', label: L('Basketball', 'Баскетбол', 'Баскетбол'), geo: true, topics: [
        ['nba', L('NBA', 'НБА', 'НБА')], ['euroleague', L('EuroLeague', 'Євроліга', 'Евролига')]] },
      { id: 'endurance', label: L('Endurance', 'Витривалість', 'Выносливость'), geo: true, topics: [
        ['triathlon', L('Triathlon', 'Тріатлон', 'Триатлон')], ['running', L('Running', 'Біг', 'Бег')],
        ['cycling', L('Cycling', 'Велоспорт', 'Велоспорт')], ['swimming', L('Swimming', 'Плавання', 'Плавание')]] },
      { id: 'other_sports', label: L('Other sports', 'Інший спорт', 'Другой спорт'), geo: true, topics: [
        ['tennis', L('Tennis', 'Теніс', 'Теннис')], ['f1', L('Formula 1', 'Формула 1', 'Формула 1')],
        ['olympics', L('Olympics', 'Олімпіада', 'Олимпиада')], ['fitness', L('Fitness', 'Фітнес', 'Фитнес')]] }] },
    { id: 'tech', label: L('IT & technology', 'IT та технології', 'IT и технологии'), groups: [
      { id: 'ai', label: L('AI', 'Штучний інтелект', 'Искусственный интеллект'), geo: false, topics: [
        ['llm_launches', L('Model launches', 'Нові моделі', 'Новые модели')], ['openai', L('OpenAI', 'OpenAI', 'OpenAI')],
        ['claude', L('Claude', 'Claude', 'Claude')], ['gemini', L('Gemini', 'Gemini', 'Gemini')],
        ['agents', L('AI agents', 'AI-агенти', 'AI-агенты')], ['workflows', L('Practical workflows', 'Практичні сценарії', 'Практические сценарии')]] },
      { id: 'programming', label: L('Programming', 'Програмування', 'Программирование'), geo: false, topics: [
        ['python', L('Python', 'Python', 'Python')], ['javascript', L('JavaScript', 'JavaScript', 'JavaScript')],
        ['web_mobile', L('Web and mobile', 'Веб і мобільні', 'Веб и мобильные')], ['open_source', L('Open source', 'Open source', 'Open source')]] },
      { id: 'devops', label: L('DevOps / cloud', 'DevOps / хмари', 'DevOps / облака'), geo: false, topics: [
        ['aws', L('AWS', 'AWS', 'AWS')], ['containers', L('Docker and Kubernetes', 'Docker і Kubernetes', 'Docker и Kubernetes')],
        ['linux', L('Linux', 'Linux', 'Linux')]] },
      { id: 'security', label: L('Cybersecurity', 'Кібербезпека', 'Кибербезопасность'), geo: false, topics: [
        ['vulns', L('Vulnerabilities', 'Вразливості', 'Уязвимости')], ['privacy', L('Privacy', 'Приватність', 'Приватность')]] },
      { id: 'hardware', label: L('Gadgets, robotics, drones', 'Гаджети, робототехніка, дрони', 'Гаджеты, робототехника, дроны'), geo: false, topics: [
        ['gadgets', L('Gadgets', 'Гаджети', 'Гаджеты')], ['robotics', L('Robotics', 'Робототехніка', 'Робототехника')],
        ['drones', L('Drones', 'Дрони', 'Дроны')]] },
      { id: 'startups', label: L('Startups', 'Стартапи', 'Стартапы'), geo: true, topics: [
        ['funding', L('Funding rounds', 'Раунди інвестицій', 'Раунды инвестиций')], ['launches', L('Launches', 'Запуски', 'Запуски')]] }] },
    { id: 'news', label: L('Ukraine, world and local news', 'Новини України, світу та міста', 'Новости Украины, мира и города'), groups: [
      { id: 'headlines', label: L('Headlines', 'Головне', 'Главное'), geo: true, topics: [
        ['top', L('Top stories', 'Головні новини', 'Главные новости')], ['politics', L('Politics', 'Політика', 'Политика')],
        ['international', L('International relations', 'Міжнародні відносини', 'Международные отношения')]] },
      { id: 'economy', label: L('Economy and law', 'Економіка та закони', 'Экономика и законы'), geo: true, topics: [
        ['economy', L('Economy', 'Економіка', 'Экономика')], ['legislation', L('Legislation', 'Законодавство', 'Законодательство')]] },
      { id: 'local', label: L('City and region', 'Місто та регіон', 'Город и регион'), geo: true, topics: [
        ['events', L('Local events', 'Події міста', 'События города')], ['transport', L('Transport', 'Транспорт', 'Транспорт')],
        ['weather', L('Weather', 'Погода', 'Погода')]] }] },
    { id: 'business', label: L('Business and personal finance', 'Бізнес та особисті фінанси', 'Бизнес и личные финансы'), groups: [
      { id: 'entrepreneurship', label: L('Entrepreneurship', 'Підприємництво', 'Предпринимательство'), geo: true, topics: [
        ['marketing', L('Marketing', 'Маркетинг', 'Маркетинг')], ['sales', L('Sales', 'Продажі', 'Продажи')]] },
      { id: 'money', label: L('Money', 'Гроші', 'Деньги'), geo: true, topics: [
        ['investing', L('Investing', 'Інвестиції', 'Инвестиции')], ['banks_taxes', L('Banks and taxes', 'Банки та податки', 'Банки и налоги')],
        ['real_estate', L('Real estate', 'Нерухомість', 'Недвижимость')], ['crypto_edu', L('Crypto basics', 'Основи крипти', 'Основы крипты')]] }] },
    { id: 'health', label: L('Health and lifestyle', "Здоров'я та стиль життя", 'Здоровье и образ жизни'), groups: [
      { id: 'wellbeing', label: L('Wellbeing', 'Самопочуття', 'Самочувствие'), geo: false, topics: [
        ['research', L('Medical research', 'Медичні дослідження', 'Медицинские исследования')], ['nutrition', L('Nutrition', 'Харчування', 'Питание')],
        ['sleep', L('Sleep', 'Сон', 'Сон')], ['mental', L('Mental health', "Ментальне здоров'я", 'Ментальное здоровье')],
        ['parenting', L('Parenting', 'Батьківство', 'Родительство')], ['training', L('Training', 'Тренування', 'Тренировки')]] }] },
    { id: 'culture', label: L('Culture and entertainment', 'Культура та розваги', 'Культура и развлечения'), groups: [
      { id: 'screen', label: L('Screen', 'Екран', 'Экран'), geo: false, topics: [
        ['movies', L('Movies', 'Кіно', 'Кино')], ['tv', L('TV series', 'Серіали', 'Сериалы')], ['youtube', L('YouTube', 'YouTube', 'YouTube')]] },
      { id: 'arts', label: L('Arts', 'Мистецтво', 'Искусство'), geo: true, topics: [
        ['music', L('Music', 'Музика', 'Музыка')], ['books', L('Books', 'Книги', 'Книги')],
        ['theatre', L('Theatre and exhibitions', 'Театр і виставки', 'Театр и выставки')], ['games', L('Games', 'Ігри', 'Игры')]] }] },
    { id: 'travel', label: L('Travel and city', 'Подорожі та місто', 'Путешествия и город'), groups: [
      { id: 'trips', label: L('Trips', 'Подорожі', 'Путешествия'), geo: true, topics: [
        ['destinations', L('Destinations', 'Напрямки', 'Направления')], ['budget', L('Budget trips', 'Бюджетні подорожі', 'Бюджетные поездки')],
        ['hotels', L('Hotels', 'Готелі', 'Отели')], ['restaurants', L('Local restaurants', 'Місцеві ресторани', 'Местные рестораны')]] }] },
    { id: 'science', label: L('Science and education', 'Наука та освіта', 'Наука и образование'), groups: [
      { id: 'science_topics', label: L('Science', 'Наука', 'Наука'), geo: false, topics: [
        ['space', L('Space', 'Космос', 'Космос')], ['physics', L('Physics', 'Фізика', 'Физика')], ['biology', L('Biology', 'Біологія', 'Биология')],
        ['history', L('History', 'Історія', 'История')], ['environment', L('Environment', 'Довкілля', 'Окружающая среда')]] },
      { id: 'learning', label: L('Learning and career', "Навчання та кар'єра", 'Обучение и карьера'), geo: false, topics: [
        ['languages', L('Languages', 'Мови', 'Языки')], ['courses', L('Courses', 'Курси', 'Курсы')], ['career', L('Career', "Кар'єра", 'Карьера')]] }] },
    { id: 'auto', label: L('Automotive and transport', 'Авто та транспорт', 'Авто и транспорт'), groups: [
      { id: 'cars', label: L('Cars', 'Автомобілі', 'Автомобили'), geo: true, topics: [
        ['ev', L('Electric vehicles', 'Електромобілі', 'Электромобили')], ['launches', L('New models', 'Нові моделі авто', 'Новые модели авто')],
        ['maintenance', L('Maintenance and repair', 'Обслуговування та ремонт', 'Обслуживание и ремонт')], ['motorsport', L('Motorsport', 'Автоспорт', 'Автоспорт')]] },
      { id: 'mobility', label: L('Getting around', 'Пересування містом', 'Передвижение по городу'), geo: true, topics: [
        ['public_transit', L('Public transport', 'Громадський транспорт', 'Общественный транспорт')], ['city_cycling', L('City cycling', 'Велосипед у місті', 'Велосипед в городе')]] }] },
    { id: 'hobbies', label: L('Food and hobbies', 'Їжа та хобі', 'Еда и хобби'), groups: [
      { id: 'food', label: L('Food', 'Їжа', 'Еда'), geo: true, topics: [
        ['recipes', L('Recipes and cooking', 'Рецепти та кулінарія', 'Рецепты и кулинария')], ['coffee', L('Coffee', 'Кава', 'Кофе')]] },
      { id: 'making', label: L('Making and caring', 'Творчість і турбота', 'Творчество и забота'), geo: false, topics: [
        ['photography', L('Photography', 'Фотографія', 'Фотография')], ['diy', L('DIY', 'Зроби сам', 'Сделай сам')],
        ['gardening', L('Gardening', 'Садівництво', 'Садоводство')], ['pets', L('Pets', 'Домашні тварини', 'Домашние животные')]] }] },
  ];

  const SCOPES = ['ukraine', 'world', 'custom'];
  const FREQUENCIES = ['daily', 'weekly', 'manual'];
  const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  const DURATIONS = [5, 10, 15];
  const LANGUAGES = ['uk', 'ru', 'en'];
  const VOICES = ['narrator', 'two_hosts'];
  // Delivery honesty. Telegram is the preferred channel and can be chosen in a draft, but nothing is sent from here.
  // Download works only with a real local file. Viber, WhatsApp and email are planned and cannot be chosen.
  const CHANNELS = { telegram: 'primary_not_connected', download: 'requires_local_file', viber: 'planned', whatsapp: 'planned', email: 'planned' };
  const WATCH_KINDS = ['athlete', 'team', 'channel', 'keyword'];
  const MAX_WATCH = 20;
  const MAX_WATCH_LEN = 60;
  const MIN_TOPICS = 2;
  const MAX_FREE_TEXT = 120;

  const INDEX = {};
  for (const cat of TAXONOMY) for (const group of cat.groups) for (const [tid, label] of group.topics) {
    INDEX[`${cat.id}.${group.id}.${tid}`] = { category: cat.id, group: group.id, label, geo: group.geo };
  }

  function topicLabel(id, lang) { const t = INDEX[id]; return t ? (t.label[lang] || t.label.en) : id; }

  function search(query, lang) {
    const q = String(query || '').trim().toLowerCase();
    if (!q) return Object.keys(INDEX);
    return Object.keys(INDEX).filter(id => ['en', 'uk', 'ru'].some(l => topicLabel(id, l).toLowerCase().includes(q)) ||
      topicLabel(id, lang).toLowerCase().includes(q));
  }

  function newProfile() {
    return { version: 1, topics: {}, freeText: '', customSources: [], schedule: { timezone: 'Europe/Kyiv', time: '07:30',
      frequency: 'daily', weekday: 'mon', durationMin: 10 }, voice: { mode: 'two_hosts', language: 'uk' },
      watchList: [], delivery: 'telegram', state: 'draft', preview: null, approvedAt: null };
  }

  function clean(text, max) { return String(text || '').replace(/[\u0000-\u001f<>]/g, '').trim().slice(0, max); }

  function setTopic(profile, id, on, scope) {
    if (!INDEX[id]) throw new Error('unknown topic ' + id);
    const next = invalidate(profile);
    const topics = { ...next.topics };
    if (on) topics[id] = INDEX[id].geo ? { scope: SCOPES.includes(scope && scope.kind) ? scope : { kind: 'world' } } : {};
    else delete topics[id];
    return { ...next, topics };
  }

  function setScope(profile, id, kind, place) {
    if (!profile.topics[id] || !INDEX[id] || !INDEX[id].geo) throw new Error('topic has no geographic scope: ' + id);
    if (!SCOPES.includes(kind)) throw new Error('bad scope ' + kind);
    const next = invalidate(profile);
    const scope = kind === 'custom' ? { kind, place: clean(place, 60) } : { kind };
    return { ...next, topics: { ...next.topics, [id]: { scope } } };
  }

  // Watch list: athletes, teams, channels or keywords to follow. Duplicates (any case) are ignored.
  function addWatch(profile, kind, value) {
    if (!WATCH_KINDS.includes(kind)) throw new Error('bad watch kind ' + kind);
    const text = clean(value, MAX_WATCH_LEN);
    const list = profile.watchList || [];
    if (!text || list.length >= MAX_WATCH || list.some(w => w.kind === kind && w.value.toLowerCase() === text.toLowerCase())) return profile;
    const next = invalidate(profile);
    return { ...next, watchList: [...list, { kind, value: text }] };
  }

  function removeWatch(profile, index) {
    const list = profile.watchList || [];
    if (!(index >= 0 && index < list.length)) return profile;
    const next = invalidate(profile);
    return { ...next, watchList: list.filter((_, i) => i !== index) };
  }

  function update(profile, patch) {
    const next = invalidate(profile);
    return { ...next, ...patch, schedule: { ...next.schedule, ...(patch.schedule || {}) }, voice: { ...next.voice, ...(patch.voice || {}) } };
  }

  // Any change to an approved/reviewed/previewed profile drops it back to draft: the old preview no longer matches.
  function invalidate(profile) {
    if (profile.state === 'draft') return profile;
    return { ...profile, state: 'draft', preview: null, approvedAt: null };
  }

  function validTimezone(tz) {
    try { new Intl.DateTimeFormat('en-US', { timeZone: tz }); return true; } catch (e) { return false; }
  }

  function validate(profile) {
    const errors = [];
    const ids = Object.keys(profile.topics || {});
    if (ids.length < MIN_TOPICS) errors.push({ field: 'topics', code: 'min_topics', min: MIN_TOPICS });
    for (const id of ids) {
      if (!INDEX[id]) errors.push({ field: 'topics', code: 'unknown_topic', id });
      const scope = (profile.topics[id] || {}).scope;
      if (scope && scope.kind === 'custom' && !scope.place) errors.push({ field: 'scope', code: 'custom_place_required', id });
    }
    const s = profile.schedule || {};
    if (!validTimezone(s.timezone)) errors.push({ field: 'timezone', code: 'bad_timezone' });
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(String(s.time || ''))) errors.push({ field: 'time', code: 'bad_time' });
    if (!FREQUENCIES.includes(s.frequency)) errors.push({ field: 'frequency', code: 'bad_frequency' });
    if (s.frequency === 'weekly' && !WEEKDAYS.includes(s.weekday)) errors.push({ field: 'weekday', code: 'weekday_required' });
    if (!DURATIONS.includes(Number(s.durationMin))) errors.push({ field: 'duration', code: 'bad_duration' });
    if (!LANGUAGES.includes((profile.voice || {}).language)) errors.push({ field: 'language', code: 'bad_language' });
    if (!VOICES.includes((profile.voice || {}).mode)) errors.push({ field: 'voice', code: 'bad_voice' });
    if (String(profile.freeText || '').length > MAX_FREE_TEXT) errors.push({ field: 'freeText', code: 'too_long', max: MAX_FREE_TEXT });
    for (const url of profile.customSources || []) {
      if (!/^https:\/\/[a-z0-9.-]+\.[a-z]{2,}(\/[^\s]*)?$/i.test(url)) errors.push({ field: 'customSources', code: 'bad_url', url });
    }
    const watch = profile.watchList || [];
    if (watch.length > MAX_WATCH) errors.push({ field: 'watchList', code: 'too_many_watch', max: MAX_WATCH });
    for (const w of watch) if (!WATCH_KINDS.includes(w && w.kind) || !w.value || String(w.value).length > MAX_WATCH_LEN) errors.push({ field: 'watchList', code: 'bad_watch' });
    if (!(profile.delivery in CHANNELS)) errors.push({ field: 'delivery', code: 'bad_channel' });
    else if (!channelStatus(profile.delivery, profile.preview).selectable) errors.push({ field: 'delivery', code: 'channel_unavailable' });
    return errors;
  }

  // Delivery honesty: a channel is usable only if it is really connected (none is, here) or, for download,
  // only when a real local audio file exists.
  // "usable": something can really be delivered now. "selectable": it may be saved as the preferred channel in a draft.
  function channelStatus(channel, preview) {
    const kind = CHANNELS[channel];
    if (!kind) return { usable: false, selectable: false, reason: 'unknown_channel' };
    if (kind === 'planned') return { usable: false, selectable: false, reason: 'planned' };
    if (kind === 'primary_not_connected') return { usable: false, selectable: true, reason: 'not_connected' };
    return preview && preview.kind === 'local_file' && preview.url ? { usable: true, selectable: true, reason: '' }
      : { usable: false, selectable: true, reason: 'no_local_file' };
  }

  // A preview exists only when something real can play: a local audio file, or the browser's own speech engine
  // reading a clearly labelled demo script. Otherwise the state stays draft and the reason is shown.
  function makePreview(profile, env) {
    const errors = validate(profile);
    if (errors.length) return { ok: false, profile, reason: 'invalid', errors };
    if (env && env.localAudioUrl) {
      return { ok: true, profile: { ...profile, state: 'preview_ready', preview: { kind: 'local_file', url: env.localAudioUrl } } };
    }
    if (env && env.speechSynthesis) {
      return { ok: true, profile: { ...profile, state: 'preview_ready',
        preview: { kind: 'browser_tts_demo', script: demoScript(profile), label: 'demo_not_ai_episode' } } };
    }
    return { ok: false, profile: { ...profile, preview: null }, reason: 'audio_unavailable', errors: [] };
  }

  function demoScript(profile) {
    const lang = profile.voice.language;
    const names = Object.keys(profile.topics).slice(0, 4).map(id => topicLabel(id, lang));
    const intro = { uk: 'Це демо-озвучка налаштувань, а не справжній випуск. Ваші теми:', ru: 'Это демо-озвучка настроек, а не настоящий выпуск. Ваши темы:',
      en: 'This is a demo reading of your settings, not a real episode. Your topics:' }[lang];
    return `${intro} ${names.join(', ')}.`;
  }

  function markReviewed(profile) {
    if (profile.state !== 'preview_ready') throw new Error('review needs a preview');
    return { ...profile, state: 'reviewed' };
  }

  function approve(profile, confirmed, now) {
    if (profile.state !== 'reviewed') throw new Error('approve needs a reviewed preview');
    if (confirmed !== true) throw new Error('explicit confirmation required');
    return { ...profile, state: 'approved', approvedAt: now || new Date().toISOString() };
  }

  // What the backend would receive. "active" stays false: there is no live scheduler or delivery in this prototype.
  function toJSON(profile) {
    return { version: 1, state: profile.state, approved_at: profile.approvedAt, active: false,
      topics: Object.keys(profile.topics).sort().map(id => ({ id, scope: (profile.topics[id] || {}).scope || null })),
      free_text: clean(profile.freeText, MAX_FREE_TEXT), custom_sources: (profile.customSources || []).slice(0, 10),
      watch_list: (profile.watchList || []).slice(0, MAX_WATCH).map(w => ({ kind: w.kind, value: clean(w.value, MAX_WATCH_LEN) })),
      schedule: { ...profile.schedule, durationMin: Number(profile.schedule.durationMin) }, voice: { ...profile.voice },
      delivery: { channel: profile.delivery, status: channelStatus(profile.delivery, profile.preview).reason || 'ready' },
      preview: profile.preview ? { kind: profile.preview.kind } : null };
  }

  return { TAXONOMY, INDEX, SCOPES, FREQUENCIES, WEEKDAYS, DURATIONS, LANGUAGES, VOICES, CHANNELS, WATCH_KINDS, MAX_WATCH,
    MIN_TOPICS, MAX_FREE_TEXT, topicLabel, search, newProfile, setTopic, setScope, addWatch, removeWatch, update, validate,
    channelStatus, makePreview, markReviewed, approve, toJSON, demoScript };
});
