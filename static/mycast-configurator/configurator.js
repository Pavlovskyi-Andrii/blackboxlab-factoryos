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
  // Owner feedback 2026-11-06: "daily" needs no weekday; otherwise the listener ticks the days (dots).
  const FREQUENCIES = ['daily', 'days'];
  const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  const DURATIONS = [5, 10, 15];
  const LANGUAGES = ['uk', 'ru', 'en'];
  const VOICES = ['narrator', 'two_hosts'];
  // #281: the 30 prebuilt Gemini TTS voices [name, style, gender by ear]. Must match mycast_voices.VOICES (a test checks).
  const GEMINI_VOICES = [
    ['Zephyr', 'Bright', 'f'],
    ['Puck', 'Upbeat', 'm'],
    ['Charon', 'Informative', 'm'],
    ['Kore', 'Firm', 'f'],
    ['Fenrir', 'Excitable', 'm'],
    ['Leda', 'Youthful', 'f'],
    ['Orus', 'Firm', 'm'],
    ['Aoede', 'Breezy', 'f'],
    ['Callirrhoe', 'Easy-going', 'f'],
    ['Autonoe', 'Bright', 'f'],
    ['Enceladus', 'Breathy', 'm'],
    ['Iapetus', 'Clear', 'm'],
    ['Umbriel', 'Easy-going', 'm'],
    ['Algieba', 'Smooth', 'm'],
    ['Despina', 'Smooth', 'f'],
    ['Erinome', 'Clear', 'f'],
    ['Algenib', 'Gravelly', 'm'],
    ['Rasalgethi', 'Informative', 'm'],
    ['Laomedeia', 'Upbeat', 'f'],
    ['Achernar', 'Soft', 'f'],
    ['Alnilam', 'Firm', 'm'],
    ['Schedar', 'Even', 'm'],
    ['Gacrux', 'Mature', 'f'],
    ['Pulcherrima', 'Forward', 'f'],
    ['Achird', 'Friendly', 'm'],
    ['Zubenelgenubi', 'Casual', 'm'],
    ['Vindemiatrix', 'Gentle', 'f'],
    ['Sadachbia', 'Lively', 'm'],
    ['Sadaltager', 'Knowledgeable', 'm'],
    ['Sulafat', 'Warm', 'f']];
  const VOICE_GENDER = Object.fromEntries(GEMINI_VOICES.map(v => [v[0], v[2]]));
  const DEFAULT_VOICES = { narrator: ['Charon'], two_hosts: ['Charon', 'Kore'] };
  function validVoices(mode, voices) {
    if (!Array.isArray(voices) || voices.some(v => !VOICE_GENDER[v])) return false;
    if (mode === 'narrator') return voices.length === 1 && VOICE_GENDER[voices[0]] === 'm';
    return voices.length === 2 && voices[0] !== voices[1] && VOICE_GENDER[voices[0]] === 'm' && VOICE_GENDER[voices[1]] === 'f';
  }
  // Delivery honesty. Telegram is the preferred channel and can be chosen in a draft, but nothing is sent from here.
  // Download works only with a real local file. Viber, WhatsApp and email are planned and cannot be chosen.
  const CHANNELS = { telegram: 'primary_not_connected', download: 'requires_local_file', viber: 'planned', whatsapp: 'planned', email: 'planned' };
  // Social follows: a handle/name or a link on the platform's own domain.
  const PLATFORMS = {
    youtube: ['youtube.com', 'youtu.be'], x: ['x.com', 'twitter.com'], telegram: ['t.me', 'telegram.me'],
    instagram: ['instagram.com'], tiktok: ['tiktok.com'], facebook: ['facebook.com'], web: [] };
  // Quick picks: public figures' official X accounts. A shortcut, not an endorsement.
  const SUGGESTED_FOLLOWS = [
    { id: 'zelensky', platform: 'x', value: '@ZelenskyyUa', name: L('Volodymyr Zelensky', 'Володимир Зеленський', 'Владимир Зеленский') },
    { id: 'trump', platform: 'x', value: '@realDonaldTrump', name: L('Donald Trump', 'Дональд Трамп', 'Дональд Трамп') },
    { id: 'macron', platform: 'x', value: '@EmmanuelMacron', name: L('Emmanuel Macron', 'Емманюель Макрон', 'Эммануэль Макрон') },
    { id: 'musk', platform: 'x', value: '@elonmusk', name: L('Elon Musk', 'Ілон Маск', 'Илон Маск') },
    { id: 'gates', platform: 'x', value: '@BillGates', name: L('Bill Gates', 'Білл Гейтс', 'Билл Гейтс') }];
  const MIN_TOPICS = 2;
  const MAX_FREE_TEXT = 120;
  const MAX_CUSTOM_PER_GROUP = 5;
  const MAX_CUSTOM_LEN = 40;
  const MAX_FOLLOWS = 20;
  const MAX_FOLLOW_LEN = 120;
  const SHARE_VERSION = 1;

  const INDEX = {};
  const GROUPS = {};
  for (const cat of TAXONOMY) for (const group of cat.groups) {
    GROUPS[`${cat.id}.${group.id}`] = { category: cat.id, label: group.label, geo: group.geo };
    for (const [tid, label] of group.topics) INDEX[`${cat.id}.${group.id}.${tid}`] = { category: cat.id, group: group.id, label, geo: group.geo };
  }
  const TOPIC_IDS = Object.keys(INDEX);   // stable order: share links store positions in this list

  function topicLabel(id, lang) { const t = INDEX[id]; return t ? (t.label[lang] || t.label.en) : id; }

  function search(query, lang) {
    const q = String(query || '').trim().toLowerCase();
    if (!q) return TOPIC_IDS.slice();
    return TOPIC_IDS.filter(id => ['en', 'uk', 'ru'].some(l => topicLabel(id, l).toLowerCase().includes(q)) ||
      topicLabel(id, lang).toLowerCase().includes(q));
  }


  /* Owner request 2026-11-08: a search like "growth hacking" offers narrower sub-topics to add as the listener's own
     entries ("Growth hacking: ідеї для стартапів", "… для готового бізнесу", …). Offline templates, no AI call. */
  const NARROW = {
    uk: ['ідеї для стартапів', 'для готового бізнесу', 'для малого бізнесу', 'кейси компаній', 'інструменти', 'тренди', 'в Україні', 'для початківців', 'помилки й уроки'],
    ru: ['идеи для стартапов', 'для готового бизнеса', 'для малого бизнеса', 'кейсы компаний', 'инструменты', 'тренды', 'в Украине', 'для начинающих', 'ошибки и уроки'],
    en: ['ideas for startups', 'for established business', 'for small business', 'company case studies', 'tools', 'trends', 'in Ukraine', 'for beginners', 'mistakes and lessons'] };
  const GUESS = [
    [/growth|маркет|market|sales|продаж|brand|бренд|smm|seo|реклам|advert|startup|стартап|business|бізнес|бизнес|founder|ceo/i, 'business.entrepreneurship'],
    [/money|financ|фінанс|финанс|invest|інвест|инвест|crypto|крипт|bitcoin|stock|акці|акци/i, 'business.money'],
    [/(^|[\s,.])(ai|ші|ии)([\s,.]|$)|gpt|claude|gemini|llm|machine learning|нейро/i, 'tech.ai'],
    [/code|program|програм|python|javascript|dev|розроб|разраб/i, 'tech.programming'],
    [/secur|безпек|безопас|hack(?!ing\b)|кібер|кибер/i, 'tech.security'],
    [/health|здоров|sport|спорт|fitness|фітнес|фитнес|run|біг|бег/i, 'health.wellbeing'],
    [/travel|подорож|путеш|trip|туризм/i, 'travel.trips'],
    [/film|кіно|кино|music|музик|book|книг|art|мистец|искусств/i, 'culture.arts'],
    [/science|наук|space|космос|physics|фізик|физик/i, 'science.science_topics'],
    [/car|авто|tesla|ev\b|електромоб|электромоб/i, 'auto.cars'],
    [/food|їж|еда|cook|кулін|кулин|recipe|рецепт/i, 'hobbies.food']];

  /** The best taxonomy group for a free query: the group of a matching topic, else a keyword guess, else news. */
  function guessGroup(query, lang) {
    const q = String(query || '').trim();
    const hit = q ? search(q, lang || 'uk')[0] : null;
    if (hit) return hit.split('.').slice(0, 2).join('.');
    for (const [re, g] of GUESS) if (re.test(q) && GROUPS[g]) return g;
    return 'news.headlines';
  }

  /** Narrower sub-topics for a query, each at most MAX_CUSTOM_LEN characters; the query itself comes first. */
  function suggestSubtopics(query, lang) {
    const raw = clean(query, MAX_CUSTOM_LEN);
    if (raw.length < 2) return [];
    const q = raw.charAt(0).toUpperCase() + raw.slice(1);
    const out = [q];
    for (const facet of NARROW[lang] || NARROW.en) {
      const text = `${q}: ${facet}`;
      if (text.length <= MAX_CUSTOM_LEN) out.push(text);
    }
    return out;
  }

  function newProfile() {
    return { version: 1, topics: {}, custom: {}, freeText: '', customSources: [], follows: [],
      schedule: { timezone: 'Europe/Kyiv', time: '07:30', frequency: 'daily', days: [], durationMin: 10 },
      voice: { mode: 'two_hosts', language: 'uk', voices: DEFAULT_VOICES.two_hosts.slice() }, delivery: 'telegram', state: 'draft', preview: null, approvedAt: null,
      calendar: { birthdays: false, events: false }, plan: null };
  }

  /* Bring an older saved draft up to date: watch list -> follows (keywords), weekly/manual -> chosen days. */
  function migrate(saved) {
    const base = newProfile();
    if (!saved || typeof saved !== 'object') return base;
    const p = { ...base, ...saved, schedule: { ...base.schedule, ...(saved.schedule || {}) }, voice: { ...base.voice, ...(saved.voice || {}) } };
    p.topics = {}; for (const id of Object.keys(saved.topics || {})) if (INDEX[id]) p.topics[id] = saved.topics[id];
    p.calendar = { birthdays: !!(saved.calendar && saved.calendar.birthdays === true), events: !!(saved.calendar && saved.calendar.events === true) };
    p.custom = {}; for (const g of Object.keys(saved.custom || {})) if (GROUPS[g] && Array.isArray(saved.custom[g])) p.custom[g] = saved.custom[g].map(v => clean(v, MAX_CUSTOM_LEN)).filter(Boolean).slice(0, MAX_CUSTOM_PER_GROUP);
    p.follows = Array.isArray(saved.follows) ? saved.follows.filter(f => f && PLATFORMS[f.platform] !== undefined && f.value) : [];
    if (Array.isArray(saved.watchList)) for (const w of saved.watchList) if (w && w.value) p.follows.push({ platform: 'web', value: clean(w.value, MAX_FOLLOW_LEN) });
    delete p.watchList;
    const s = p.schedule;
    if (s.frequency === 'weekly') { s.frequency = 'days'; s.days = WEEKDAYS.includes(s.weekday) ? [s.weekday] : ['mon']; }
    if (!FREQUENCIES.includes(s.frequency)) s.frequency = 'daily';
    delete s.weekday;
    s.days = (Array.isArray(s.days) ? s.days : []).filter(d => WEEKDAYS.includes(d));
    if (!(p.delivery in CHANNELS) || CHANNELS[p.delivery] === 'planned') p.delivery = 'telegram';
    if (!validVoices(p.voice.mode, p.voice.voices)) p.voice = { ...p.voice, voices: (DEFAULT_VOICES[p.voice.mode] || DEFAULT_VOICES.two_hosts).slice() };
    p.plan = sanitizePlan(saved.plan);   // drafts saved before the timeline have no plan: it is derived from the picks
    return { ...p, state: 'draft', preview: null, approvedAt: null };
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

  /* "Your own" entry in a row: a club, a fighter, a league (e.g. Arsenal under football, Usyk under boxing). */
  function addCustom(profile, groupKey, value) {
    if (!GROUPS[groupKey]) throw new Error('unknown group ' + groupKey);
    const text = clean(value, MAX_CUSTOM_LEN);
    const list = (profile.custom || {})[groupKey] || [];
    if (!text || list.length >= MAX_CUSTOM_PER_GROUP || list.some(v => v.toLowerCase() === text.toLowerCase())) return profile;
    const next = invalidate(profile);
    return { ...next, custom: { ...(next.custom || {}), [groupKey]: [...list, text] } };
  }

  function removeCustom(profile, groupKey, index) {
    const list = ((profile.custom || {})[groupKey] || []);
    if (!(index >= 0 && index < list.length)) return profile;
    const next = invalidate(profile);
    const custom = { ...(next.custom || {}) };
    const left = list.filter((_, i) => i !== index);
    if (left.length) custom[groupKey] = left; else delete custom[groupKey];
    return { ...next, custom };
  }

  /* Normalise a follow: "@name", a plain name, or an https link on that platform's own domain. Returns null if unusable. */
  function normalizeFollow(platform, value) {
    if (!(platform in PLATFORMS)) return null;
    const raw = clean(value, MAX_FOLLOW_LEN);
    if (!raw) return null;
    if (/^[a-z]+:/i.test(raw)) {
      let url;
      try { url = new URL(raw); } catch (e) { return null; }
      if (url.protocol !== 'https:') return null;
      const host = url.hostname.toLowerCase().replace(/^(www|m|mobile)\./, '');
      const allowed = PLATFORMS[platform];
      if (allowed.length && !allowed.includes(host)) return null;
      return { platform, value: `https://${host}${url.pathname}`.replace(/\/+$/, '') };
    }
    if (/\s{2,}/.test(raw)) return null;
    return { platform, value: raw };
  }

  function addFollow(profile, platform, value) {
    const f = normalizeFollow(platform, value);
    if (!f) throw new Error('bad follow');
    const list = profile.follows || [];
    if (list.length >= MAX_FOLLOWS || list.some(x => x.platform === f.platform && x.value.toLowerCase() === f.value.toLowerCase())) return profile;
    const next = invalidate(profile);
    return { ...next, follows: [...list, f] };
  }

  function removeFollow(profile, index) {
    const list = profile.follows || [];
    if (!(index >= 0 && index < list.length)) return profile;
    const next = invalidate(profile);
    return { ...next, follows: list.filter((_, i) => i !== index) };
  }

  function toggleDay(profile, day) {
    if (!WEEKDAYS.includes(day)) throw new Error('bad day ' + day);
    const days = profile.schedule.days || [];
    const next = days.includes(day) ? days.filter(d => d !== day) : WEEKDAYS.filter(d => d === day || days.includes(d));
    return update(profile, { schedule: { days: next } });
  }

  function update(profile, patch) {
    const next = invalidate(profile);
    const voice = { ...next.voice, ...(patch.voice || {}) };
    // Switching one host <-> two hosts keeps a valid pick: fall back to the defaults when the old choice no longer fits.
    if (!validVoices(voice.mode, voice.voices)) voice.voices = (DEFAULT_VOICES[voice.mode] || DEFAULT_VOICES.two_hosts).slice();
    return { ...next, ...patch, schedule: { ...next.schedule, ...(patch.schedule || {}) }, voice };
  }

  /* Owner note 2026-11-08: an episode = world news + personal interests + friends' birthdays + today's calendar
     (Google Calendar). Only the wish is stored here; nothing is read from any calendar until the owner approves a
     read-only Google Calendar connection, so the status stays not_connected. */
  const CALENDAR_PARTS = ['birthdays', 'events'];
  function setCalendar(profile, part, on) {
    if (!CALENDAR_PARTS.includes(part)) throw new Error('bad calendar part ' + part);
    const next = invalidate(profile);
    return { ...next, calendar: { ...(next.calendar || { birthdays: false, events: false }), [part]: !!on } };
  }

  /* Owner request 2026-11-11: the episode timeline ("полоса"). The episode is a row of segments derived from the
     picks: a locked greeting first, one news block (topics and own entries under "News"), one personal-interests block
     (every other category plus the free-text topic), one block per followed channel, and the Google Calendar block
     (birthdays or meetings) at the end. profile.plan stores only the listener's edits as [{ id, sec, off }]:
     order, durations and removed blocks. Segments whose source is deselected are dropped when the plan is read;
     new segments are added before a trailing calendar block. Nothing here generates or schedules an episode. */
  const PLAN_MIN_SEC = 15, PLAN_MAX_SEC = 300, PLAN_STEP_SEC = 15, MAX_PLAN_ITEMS = 40;
  const PLAN_DEFAULT_SEC = { greet: 20, news: 120, interests: 120, follow: 120, cal: 30 };
  const PLAN_LABELS = { greet: L('Greeting', 'Привітання', 'Приветствие'), news: L('News', 'Новини', 'Новости'),
    interests: L('My interests', 'Мої інтереси', 'Мои интересы'), cal: L('Google Calendar', 'Google Календар', 'Google Календарь') };
  const PLATFORM_NAMES = { youtube: L('YouTube', 'YouTube', 'YouTube'), x: L('X', 'X', 'X'), telegram: L('Telegram', 'Telegram', 'Telegram'),
    instagram: L('Instagram', 'Instagram', 'Instagram'), tiktok: L('TikTok', 'TikTok', 'TikTok'), facebook: L('Facebook', 'Facebook', 'Facebook'), web: L('Web', 'Сайт', 'Сайт') };

  function followSegId(f) { return 'f:' + f.platform + ':' + String(f.value || '').toLowerCase(); }
  function clampSec(sec) { const n = Math.round(Number(sec)); return Number.isFinite(n) && n > 0 ? Math.min(PLAN_MAX_SEC, Math.max(PLAN_MIN_SEC, n)) : null; }
  function sanitizePlan(raw) {
    if (!Array.isArray(raw)) return null;
    const seen = new Set(), out = [];
    for (const r of raw) {
      if (out.length >= MAX_PLAN_ITEMS) break;
      if (!r || typeof r.id !== 'string' || !r.id || r.id.length > 200 || seen.has(r.id)) continue;
      seen.add(r.id);
      const item = { id: r.id }, sec = clampSec(r.sec);
      if (sec !== null) item.sec = sec;
      if (r.off === true && r.id !== 'greet') item.off = true;
      out.push(item);
    }
    return out;
  }
  function planSources(profile) {
    const out = [{ id: 'greet', kind: 'greet' }];
    const isNews = k => k.split('.')[0] === 'news';
    const topics = Object.keys(profile.topics || {}), groups = Object.keys(profile.custom || {}).filter(g => (profile.custom[g] || []).length);
    if (topics.some(isNews) || groups.some(isNews)) out.push({ id: 'news', kind: 'news' });
    if (topics.some(k => !isNews(k)) || groups.some(g => !isNews(g)) || clean(profile.freeText, MAX_FREE_TEXT)) out.push({ id: 'interests', kind: 'interests' });
    for (const f of profile.follows || []) {
      if (!f || !f.value) continue;
      const id = followSegId(f);
      if (!out.some(s => s.id === id)) out.push({ id, kind: 'follow', platform: f.platform, value: f.value });
    }
    const cal = profile.calendar || {};
    if (cal.birthdays || cal.events) out.push({ id: 'cal', kind: 'cal' });
    return out;
  }
  // Every segment in plan order, removed ones included (off: true) so a restore puts a block back where it was.
  function fullPlan(profile) {
    const sources = planSources(profile), byId = new Map(sources.map(s => [s.id, s]));
    const saved = sanitizePlan(profile.plan) || [];
    const make = (s, r) => ({ ...s, sec: (r && r.sec) || PLAN_DEFAULT_SEC[s.kind], off: s.kind !== 'greet' && !!(r && r.off), locked: s.kind === 'greet' });
    const list = saved.filter(r => r.id !== 'greet' && byId.has(r.id)).map(r => make(byId.get(r.id), r));
    for (const s of sources) {
      if (s.kind === 'greet' || list.some(x => x.id === s.id)) continue;
      const item = make(s, null), last = list[list.length - 1];
      if (s.kind !== 'cal' && last && last.id === 'cal') list.splice(list.length - 1, 0, item); else list.push(item);
    }
    return [make(byId.get('greet'), saved.find(r => r.id === 'greet')), ...list];
  }
  function planFromProfile(profile) { return fullPlan(profile).filter(x => !x.off); }
  function planRemoved(profile) { return fullPlan(profile).filter(x => x.off); }
  function planTotal(items) { return (items || []).reduce((n, i) => n + (i.off ? 0 : Number(i.sec) || 0), 0); }
  function planLimitSec(profile) { return Number((profile.schedule || {}).durationMin || 10) * 60; }
  function planLabel(item, lang) {
    if (item.kind === 'follow') {
      const name = PLATFORM_NAMES[item.platform] ? (PLATFORM_NAMES[item.platform][lang] || PLATFORM_NAMES[item.platform].en) : '';
      const v = String(item.value || '').replace(/^https:\/\/[^/]+\/?/, '');
      return (name ? name + ' ' : '') + (v || item.value || '');
    }
    const l = PLAN_LABELS[item.kind];
    return l ? (l[lang] || l.en) : item.id;
  }
  function withPlan(profile, full) {
    const next = invalidate(profile);
    return { ...next, plan: full.map(x => (x.off ? { id: x.id, sec: x.sec, off: true } : { id: x.id, sec: x.sec })) };
  }
  /** Move a segment to position toIndex among the active segments. The greeting stays first. */
  function movePlanItem(profile, id, toIndex) {
    const full = fullPlan(profile), item = full.find(x => x.id === id);
    if (!item || item.locked || item.off) return profile;
    const rest = full.filter(x => x.id !== id), active = rest.filter(x => !x.off);
    const to = Math.max(1, Math.min(active.length, Math.round(Number(toIndex)) || 0));
    rest.splice(to < active.length ? rest.indexOf(active[to]) : rest.length, 0, item);
    if (rest.every((x, i) => x.id === full[i].id)) return profile;
    return withPlan(profile, rest);
  }
  /** Set a segment's length in seconds, kept within 15 s … 5 min. */
  function setPlanDuration(profile, id, sec) {
    const full = fullPlan(profile), item = full.find(x => x.id === id), next = clampSec(sec);
    if (!item || next === null || next === item.sec) return profile;
    return withPlan(profile, full.map(x => (x.id === id ? { ...x, sec: next } : x)));
  }
  function removePlanItem(profile, id) {
    const full = fullPlan(profile), item = full.find(x => x.id === id);
    if (!item || item.locked || item.off) return profile;
    return withPlan(profile, full.map(x => (x.id === id ? { ...x, off: true } : x)));
  }
  function restorePlanItem(profile, id) {
    const full = fullPlan(profile), item = full.find(x => x.id === id);
    if (!item || !item.off) return profile;
    return withPlan(profile, full.map(x => (x.id === id ? { ...x, off: false } : x)));
  }

  /* Owner request 2026-11-11: sub-topics may also come from GET /api/mycast/subtopics. The answer is untrusted: keep
     plain strings only, cleaned like an own entry, without duplicates, at most 10. */
  function cleanSubtopics(list) {
    const out = [];
    for (const v of Array.isArray(list) ? list : []) {
      if (typeof v !== 'string') continue;
      const text = clean(v, MAX_CUSTOM_LEN);
      if (text.length >= 2 && !out.some(o => o.toLowerCase() === text.toLowerCase())) out.push(text);
      if (out.length >= 10) break;
    }
    return out;
  }

  /* #281: pick the Gemini voice for one slot (0 = host A / narrator, 1 = host B). Invalid picks are refused. */
  function setVoice(profile, slot, name) {
    const voices = (profile.voice.voices || []).slice();
    voices[slot] = name;
    if (!validVoices(profile.voice.mode, voices)) throw new Error('bad voice ' + name);
    return update(profile, { voice: { voices } });
  }

  // Any change to an approved/reviewed/previewed profile drops it back to draft: the old preview no longer matches.
  function invalidate(profile) {
    if (profile.state === 'draft') return profile;
    return { ...profile, state: 'draft', preview: null, approvedAt: null };
  }

  function validTimezone(tz) {
    try { new Intl.DateTimeFormat('en-US', { timeZone: tz }); return true; } catch (e) { return false; }
  }

  function selectionCount(profile) {
    const custom = Object.values(profile.custom || {}).reduce((n, list) => n + list.length, 0);
    return Object.keys(profile.topics || {}).length + custom;
  }

  function validate(profile) {
    const errors = [];
    const ids = Object.keys(profile.topics || {});
    if (selectionCount(profile) < MIN_TOPICS) errors.push({ field: 'topics', code: 'min_topics', min: MIN_TOPICS });
    for (const id of ids) {
      if (!INDEX[id]) errors.push({ field: 'topics', code: 'unknown_topic', id });
      const scope = (profile.topics[id] || {}).scope;
      if (scope && scope.kind === 'custom' && !scope.place) errors.push({ field: 'scope', code: 'custom_place_required', id });
    }
    for (const [g, list] of Object.entries(profile.custom || {})) {
      if (!GROUPS[g] || !Array.isArray(list) || list.length > MAX_CUSTOM_PER_GROUP || list.some(v => !v || String(v).length > MAX_CUSTOM_LEN)) errors.push({ field: 'custom', code: 'bad_custom', group: g });
    }
    const s = profile.schedule || {};
    if (!validTimezone(s.timezone)) errors.push({ field: 'timezone', code: 'bad_timezone' });
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(String(s.time || ''))) errors.push({ field: 'time', code: 'bad_time' });
    if (!FREQUENCIES.includes(s.frequency)) errors.push({ field: 'frequency', code: 'bad_frequency' });
    if (s.frequency === 'days' && !(Array.isArray(s.days) && s.days.length && s.days.every(d => WEEKDAYS.includes(d)))) errors.push({ field: 'days', code: 'days_required' });
    if (!DURATIONS.includes(Number(s.durationMin))) errors.push({ field: 'duration', code: 'bad_duration' });
    if (!LANGUAGES.includes((profile.voice || {}).language)) errors.push({ field: 'language', code: 'bad_language' });
    if (!VOICES.includes((profile.voice || {}).mode)) errors.push({ field: 'voice', code: 'bad_voice' });
    else if (!validVoices(profile.voice.mode, profile.voice.voices)) errors.push({ field: 'voice', code: 'bad_voices' });
    if (String(profile.freeText || '').length > MAX_FREE_TEXT) errors.push({ field: 'freeText', code: 'too_long', max: MAX_FREE_TEXT });
    for (const url of profile.customSources || []) {
      if (!/^https:\/\/[a-z0-9.-]+\.[a-z]{2,}(\/[^\s]*)?$/i.test(url)) errors.push({ field: 'customSources', code: 'bad_url', url });
    }
    const follows = profile.follows || [];
    if (follows.length > MAX_FOLLOWS) errors.push({ field: 'follows', code: 'too_many_follows', max: MAX_FOLLOWS });
    for (const f of follows) if (!f || !normalizeFollow(f.platform, f.value)) errors.push({ field: 'follows', code: 'bad_follow' });
    if (!(profile.delivery in CHANNELS)) errors.push({ field: 'delivery', code: 'bad_channel' });
    else if (!channelStatus(profile.delivery, profile.preview).selectable) errors.push({ field: 'delivery', code: 'channel_unavailable' });
    return errors;
  }

  // "usable": something can really be delivered now. "selectable": it may be saved as the preferred channel in a draft.
  function channelStatus(channel, preview) {
    const kind = CHANNELS[channel];
    if (!kind) return { usable: false, selectable: false, reason: 'unknown_channel' };
    if (kind === 'planned') return { usable: false, selectable: false, reason: 'planned' };
    if (kind === 'primary_not_connected') return { usable: false, selectable: true, reason: 'not_connected' };
    return preview && (preview.kind === 'local_file' || preview.kind === 'gemini_demo') && preview.url ? { usable: true, selectable: true, reason: '' }
      : { usable: false, selectable: true, reason: 'no_local_file' };
  }

  // A preview exists only when something real can play: a local audio file, or the browser's own speech engine
  // reading a clearly labelled demo script. Otherwise the state stays draft and the reason is shown.
  function makePreview(profile, env) {
    const errors = validate(profile);
    if (errors.length) return { ok: false, profile, reason: 'invalid', errors };
    if (env && env.demoAudioUrl) {   // a short sample voiced by Gemini on the server: real audio, still only a demo
      const lines = demoLines(profile);
      return { ok: true, profile: { ...profile, state: 'preview_ready',
        preview: { kind: 'gemini_demo', url: env.demoAudioUrl, script: lines.map(l => l.text).join(' '), lines, label: 'demo_not_episode' } } };
    }
    if (env && env.localAudioUrl) {
      return { ok: true, profile: { ...profile, state: 'preview_ready', preview: { kind: 'local_file', url: env.localAudioUrl } } };
    }
    if (env && env.speechSynthesis) {
      const lines = demoLines(profile);
      return { ok: true, profile: { ...profile, state: 'preview_ready',
        preview: { kind: 'browser_tts_demo', script: lines.map(l => l.text).join(' '), lines, label: 'demo_not_ai_episode' } } };
    }
    return { ok: false, profile: { ...profile, preview: null }, reason: 'audio_unavailable', errors: [] };
  }

  /* A short demo, about 15 s: host A greets and names the first picks; with two hosts, host B names the rest. */
  function demoLines(profile) {
    const lang = profile.voice.language;
    const names = demoNames(profile, lang);
    const T = {
      uk: { hi: 'Це демо MyCast, а не справжній випуск. Привіт! Це новини, які ти замовив.', a: 'Сьогодні в нас:', b: 'А ще:', bye: 'До зустрічі завтра!' },
      ru: { hi: 'Это демо MyCast, а не настоящий выпуск. Привет! Это новости, которые ты заказал.', a: 'Сегодня у нас:', b: 'А ещё:', bye: 'До встречи завтра!' },
      en: { hi: 'This is a MyCast demo, not a real episode. Hi! Here is the news you ordered.', a: 'Today we have:', b: 'And also:', bye: 'See you tomorrow!' } }[lang];
    if (profile.voice.mode !== 'two_hosts' || names.length < 2) {
      return [{ host: 'A', text: `${T.hi} ${T.a} ${names.slice(0, 5).join(', ')}. ${T.bye}` }];
    }
    const half = Math.ceil(Math.min(names.length, 6) / 2);
    return [{ host: 'A', text: `${T.hi} ${T.a} ${names.slice(0, half).join(', ')}.` },
            { host: 'B', text: `${T.b} ${names.slice(half, 6).join(', ')}. ${T.bye}` }];
  }
  /* The picks in episode order: news and personal interests follow their blocks in the timeline. A removed block's
     picks are left out, unless that would leave the demo with nothing to say. */
  function demoNames(profile, lang) {
    const news = [], other = [];
    for (const id of Object.keys(profile.topics || {})) (id.split('.')[0] === 'news' ? news : other).push(topicLabel(id, lang));
    for (const [g, list] of Object.entries(profile.custom || {})) (g.split('.')[0] === 'news' ? news : other).push(...list);
    const out = [];
    for (const item of planFromProfile(profile)) {
      if (item.kind === 'news') out.push(...news);
      if (item.kind === 'interests') out.push(...other);
    }
    return out.length ? out : [...news, ...other];
  }
  function demoScript(profile) { return demoLines(profile).map(l => l.text).join(' '); }

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
    const s = profile.schedule;
    return { version: 1, state: profile.state, approved_at: profile.approvedAt, active: false,
      topics: Object.keys(profile.topics).sort().map(id => ({ id, scope: (profile.topics[id] || {}).scope || null })),
      custom: Object.keys(profile.custom || {}).sort().map(g => ({ group: g, items: profile.custom[g].map(v => clean(v, MAX_CUSTOM_LEN)) })),
      free_text: clean(profile.freeText, MAX_FREE_TEXT), custom_sources: (profile.customSources || []).slice(0, 10),
      follows: (profile.follows || []).slice(0, MAX_FOLLOWS).map(f => normalizeFollow(f.platform, f.value)).filter(Boolean),
      schedule: { timezone: s.timezone, time: s.time, frequency: s.frequency, days: s.frequency === 'days' ? s.days.slice() : [],
        durationMin: Number(s.durationMin) },
      voice: { ...profile.voice },
      delivery: { channel: profile.delivery, status: channelStatus(profile.delivery, profile.preview).reason || 'ready' },
      preview: profile.preview ? { kind: profile.preview.kind } : null,
      calendar: { birthdays: !!(profile.calendar || {}).birthdays, events: !!(profile.calendar || {}).events, source: 'google_calendar', status: 'not_connected' },
      plan: planFromProfile(profile).map(i => ({ id: i.id, kind: i.kind, sec: i.sec })), plan_removed: planRemoved(profile).map(i => i.id),
      plan_total_sec: planTotal(planFromProfile(profile)) };
  }

  /* Share link: the listener's settings (never state, preview or approval) packed into a URL-safe string.
     Topics are stored as positions in TOPIC_IDS so a QR code stays small. Decoding validates everything again. */
  function b64urlEncode(str) {
    const bytes = typeof TextEncoder !== 'undefined' ? new TextEncoder().encode(str) : Buffer.from(str, 'utf8');
    let bin = ''; for (const b of bytes) bin += String.fromCharCode(b);
    const b64 = typeof btoa !== 'undefined' ? btoa(bin) : Buffer.from(bin, 'binary').toString('base64');
    return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function b64urlDecode(s) {
    const b64 = String(s).replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((String(s).length + 3) % 4);
    const bin = typeof atob !== 'undefined' ? atob(b64) : Buffer.from(b64, 'base64').toString('binary');
    const bytes = Uint8Array.from(bin, c => c.charCodeAt(0));
    return typeof TextDecoder !== 'undefined' ? new TextDecoder().decode(bytes) : Buffer.from(bytes).toString('utf8');
  }
  const SCOPE_CODE = { ukraine: 'u', world: 'w', custom: 'c' };
  function encodeShare(profile) {
    const t = Object.keys(profile.topics).filter(id => INDEX[id]).map(id => {
      const sc = (profile.topics[id] || {}).scope;
      const i = TOPIC_IDS.indexOf(id);
      return sc ? (sc.kind === 'custom' ? [i, 'c', clean(sc.place, 60)] : [i, SCOPE_CODE[sc.kind]]) : [i];
    });
    const s = profile.schedule;
    const data = { v: SHARE_VERSION, n: TOPIC_IDS.length, t, c: profile.custom || {}, f: (profile.follows || []).map(f => [f.platform, f.value]),
      s: [s.timezone, s.time, s.frequency, s.frequency === 'days' ? s.days : [], Number(s.durationMin)],
      o: [profile.voice.mode, profile.voice.language, profile.voice.voices], d: profile.delivery, x: clean(profile.freeText, MAX_FREE_TEXT),
      k: [(profile.calendar || {}).birthdays ? 1 : 0, (profile.calendar || {}).events ? 1 : 0] };
    // Timeline (2026-11-11): optional key "pl", only once the listener has edited the plan. Links made before it have
    // no "pl" and decode to the default plan; older pages ignore the key. Follow segments are stored by their position
    // in "f" so a long channel link is not repeated.
    if (Array.isArray(profile.plan)) {
      const fid = (profile.follows || []).map(followSegId);
      data.pl = sanitizePlan(profile.plan).map(r => {
        const id = r.id.startsWith('f:') ? (fid.indexOf(r.id) >= 0 ? 'f' + fid.indexOf(r.id) : null) : r.id;
        return id === null ? null : [id, r.sec || 0, r.off ? 1 : 0];
      }).filter(Boolean);
    }
    return b64urlEncode(JSON.stringify(data));
  }
  function decodeShare(code) {
    let data;
    try { data = JSON.parse(b64urlDecode(String(code || '').slice(0, 8000))); } catch (e) { throw new Error('bad share code'); }
    if (!data || data.v !== SHARE_VERSION || data.n !== TOPIC_IDS.length) throw new Error('bad share code');
    let p = newProfile();
    const back = { u: 'ukraine', w: 'world', c: 'custom' };
    for (const row of Array.isArray(data.t) ? data.t : []) {
      const id = TOPIC_IDS[row && row[0]];
      if (!id) continue;
      p = setTopic(p, id, true, row[1] ? { kind: back[row[1]] || 'world' } : undefined);
      if (row[1] === 'c' && INDEX[id].geo) p = setScope(p, id, 'custom', row[2]);
    }
    for (const [g, list] of Object.entries(data.c || {})) if (GROUPS[g] && Array.isArray(list)) for (const v of list) p = addCustom(p, g, v);
    for (const f of Array.isArray(data.f) ? data.f : []) { try { p = addFollow(p, f[0], f[1]); } catch (e) { /* drop unusable follows */ } }
    const s = Array.isArray(data.s) ? data.s : [];
    const freq = FREQUENCIES.includes(s[2]) ? s[2] : 'daily';
    p = update(p, { schedule: { timezone: validTimezone(s[0]) ? s[0] : 'Europe/Kyiv', time: /^([01]\d|2[0-3]):[0-5]\d$/.test(s[1]) ? s[1] : '07:30',
      frequency: freq, days: (Array.isArray(s[3]) ? s[3] : []).filter(d => WEEKDAYS.includes(d)), durationMin: DURATIONS.includes(Number(s[4])) ? Number(s[4]) : 10 } });
    const o = Array.isArray(data.o) ? data.o : [];
    const mode = VOICES.includes(o[0]) ? o[0] : 'two_hosts';
    p = update(p, { voice: { mode, language: LANGUAGES.includes(o[1]) ? o[1] : 'uk', voices: validVoices(mode, o[2]) ? o[2] : DEFAULT_VOICES[mode].slice() },
      delivery: CHANNELS[data.d] && CHANNELS[data.d] !== 'planned' ? data.d : 'telegram', freeText: clean(data.x, MAX_FREE_TEXT) });
    const k = Array.isArray(data.k) ? data.k : [];
    p = { ...p, calendar: { birthdays: k[0] === 1, events: k[1] === 1 } };
    if (Array.isArray(data.pl)) {
      const rawF = Array.isArray(data.f) ? data.f : [];
      p.plan = sanitizePlan(data.pl.map(row => {
        if (!Array.isArray(row) || typeof row[0] !== 'string') return null;
        let id = row[0];
        const m = /^f(\d+)$/.exec(id);
        if (m) { const f = rawF[Number(m[1])], n = Array.isArray(f) ? normalizeFollow(f[0], f[1]) : null; if (!n) return null; id = followSegId(n); }
        return { id, sec: row[1], off: row[2] === 1 };
      }));
    }
    return { ...p, state: 'draft', preview: null, approvedAt: null };
  }

  return { GEMINI_VOICES, VOICE_GENDER, DEFAULT_VOICES, validVoices, setVoice,
    TAXONOMY, INDEX, GROUPS, TOPIC_IDS, SCOPES, FREQUENCIES, WEEKDAYS, DURATIONS, LANGUAGES, VOICES, CHANNELS, PLATFORMS,
    SUGGESTED_FOLLOWS, MIN_TOPICS, MAX_FREE_TEXT, MAX_CUSTOM_PER_GROUP, MAX_FOLLOWS,
    CALENDAR_PARTS, setCalendar,
    topicLabel, search, guessGroup, suggestSubtopics, newProfile, migrate, setTopic, setScope, addCustom, removeCustom, normalizeFollow, addFollow, removeFollow,
    toggleDay, update, validate, selectionCount, channelStatus, makePreview, markReviewed, approve, toJSON, demoLines, demoScript,
    encodeShare, decodeShare,
    PLAN_MIN_SEC, PLAN_MAX_SEC, PLAN_STEP_SEC, PLAN_DEFAULT_SEC, planFromProfile, planRemoved, planTotal, planLimitSec, planLabel,
    movePlanItem, setPlanDuration, removePlanItem, restorePlanItem, cleanSubtopics };
});
