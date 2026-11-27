# MyCast privacy page: proposed addition for the visit counter (T-743) — DRAFT for the owner

Status: **not published**. `static/mycast-configurator/privacy.html` is unchanged. The counter stays off
(`FACTORY_MYCAST_VISITS_ENABLED` unset) until the owner approves this text. Once approved, the text goes into the
privacy page in the same PR that the owner's flag change follows.

What the counter really does (code: `mycast_visits.py`, `static/mycast-configurator/v.js`):
- one record per page view of the MyCast site, profile page or episode page: date and time, page type, landing variant
  and channel from the link (for example `?v=b&ch=tg`), and the category of the site you came from (Telegram,
  LinkedIn, search…; the site address itself is dropped);
- a daily code made from the IP address and browser name with a key that changes every day; yesterday's key is
  deleted, so visits cannot be linked across days. The IP address and browser name are not stored. The code only
  estimates how many different visitors came on a day: people on one network with the same browser can count as one,
  and one person who changes network or browser can count as two. Every page view is counted as a view;
- no cookies, no browser storage, no third-party scripts; nothing is counted with Do Not Track or Global Privacy
  Control switched on; bots and test visits are not counted;
- the records are kept for 120 days, then only daily totals remain;
- when you sign up, the account keeps the variant and channel of the link you came from; it is deleted with the account.

Also covered (T-746, owner statistics, already on): the account counts how many times its episodes were started
on the MyCast site (own replays, and plays of a shared episode or profile player) — a number only, deleted with the
account. When an account is deleted, only an anonymous total remains: how many accounts were deleted and after how
many days, with no name or id.

## Text to add — Ukrainian (after «Чого ми не зберігаємо»)

**Статистика відвідувань.** Щоб зрозуміти, яка сторінка і який канал приводять людей, ми рахуємо перегляди сторінок
MyCast. Для кожного перегляду зберігаються дата й час, тип сторінки, варіант сторінки та канал із посилання (наприклад,
Telegram) і категорія сайту, з якого ви прийшли — без його адреси. Щоб приблизно оцінити, скільки різних людей зайшло за
день, ми робимо одноразовий код з IP-адреси та назви браузера ключем, який змінюється щодня; учорашній ключ видаляється,
тому відвідини різних днів пов’язати неможливо. Оцінка приблизна: люди з однієї мережі з однаковим браузером можуть
порахуватися як одна людина. Саму IP-адресу та назву браузера ми не зберігаємо. Ми не використовуємо cookies і
сторонні сервіси аналітики. Якщо у браузері ввімкнено Do Not Track або Global Privacy Control, перегляд не
рахується. Записи зберігаються 120 днів, потім лишаються тільки підсумки за день. Під час реєстрації в обліковому
записі зберігаються варіант сторінки й канал посилання, з якого ви прийшли; вони видаляються разом з обліковим записом.
Також в обліковому записі рахується, скільки разів ваші випуски запускали на сайті MyCast (лише число). Після видалення
облікового запису лишається тільки загальний лічильник видалених акаунтів, без жодних даних про вас.

## Text to add — English (in the English part, after "Not stored")

**Visit statistics.** To learn which page and which channel bring people, we count views of MyCast pages. For each
view we keep the date and time, the page type, the page variant and channel from the link (for example Telegram), and
the category of the site you came from, without its address. To estimate how many different people visited on a
day, we make a one-time code from your IP address and browser name with a key that changes every day; yesterday's key
is deleted, so visits on different days cannot be linked. The estimate is approximate: people on one network with the
same browser can count as one person. We do not store the IP address or the browser name. We use no
cookies and no third-party analytics. Nothing is counted when your browser sends Do Not Track or Global Privacy
Control. Records are kept for 120 days; after that only daily totals remain. When you sign up, your account keeps the
page variant and channel of the link you came from; they are deleted with your account. Your account also counts how
many times your episodes were started on the MyCast site (a number only). After an account is deleted, only an
anonymous count of deleted accounts remains, with nothing about you.

## Для владельца — то же по-русски (для проверки, на странице не публикуется)

**Статистика посещений.** Чтобы понять, какая страница и какой канал приводят людей, мы считаем просмотры страниц
MyCast. Для каждого просмотра хранятся дата и время, тип страницы, вариант страницы и канал из ссылки (например,
Telegram) и категория сайта, с которого вы пришли, — без его адреса. Чтобы примерно оценить, сколько разных людей
зашло за день, мы делаем одноразовый код из IP-адреса и названия браузера ключом, который меняется каждый день;
вчерашний ключ удаляется, поэтому посещения разных дней связать нельзя. Оценка приблизительная: люди из одной сети с
одинаковым браузером могут посчитаться как один человек. Сам IP-адрес и название браузера мы не храним. Cookies и
сторонние сервисы аналитики не используются. Если в браузере включены Do Not Track или Global Privacy Control,
просмотр не считается. Записи хранятся 120 дней, потом остаются только итоги за день. При регистрации в аккаунте
сохраняются вариант страницы и канал ссылки, по которой вы пришли; они удаляются вместе с аккаунтом. Также в аккаунте
считается, сколько раз ваши выпуски запускали на сайте MyCast (только число). После удаления аккаунта остаётся только
общий счётчик удалённых аккаунтов, без данных о вас.

Not legal advice: whether this is enough for GDPR in the EU depends on the owner's legal setup; the design avoids
cookies and stored identifiers to keep the risk low.
