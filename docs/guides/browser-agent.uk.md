# Браузерний агент (T-560) — встановлення на EC2-воркер

Картка «Браузерний агент» на дашборді ставить у чергу завдання лише на читання (https-адреса і до 5 CSS-селекторів). EC2-воркер
(`factoryos-claude-worker`, користувач `ec2-user`) відкриває сторінку в анонімному headless Chromium і повертає прочитаний текст
та один скриншот. У цій версії немає входу в акаунти, форм, реєстрації та покупок; надсилання форм у виконавці й далі вимкнене.

## Одноразове встановлення (під root на EC2, Amazon Linux 2023)
```
dnf install -y nss atk at-spi2-atk cups-libs libdrm libxkbcommon libXcomposite libXdamage libXrandr mesa-libgbm pango alsa-lib
sudo -u ec2-user -H python3 -m pip install --user playwright
mkdir -p /home/ec2-user/pw-tmp && chown ec2-user /home/ec2-user/pw-tmp
sudo -u ec2-user -H env TMPDIR=/home/ec2-user/pw-tmp python3 -m playwright install --only-shell chromium
systemctl restart factoryos-claude-worker
```
Перевірка: `journalctl -u factoryos-claude-worker --since "10 min ago" --no-pager | grep browser-tasks`. Якщо Playwright
не встановлено, воркер один раз пише в журнал "Playwright is not installed on this worker" і залишає завдання в черзі.

Помилка `ENOSPC: no space left on device` під час завантаження (траплялася 2026-11-13): в Amazon Linux тека `/tmp` — це tmpfs в оперативній пам'яті,
і на машині з 1 ГБ вона замала для архіву розміром близько 186 МБ. Тому команди вище завантажують файли в теку на диску
(`TMPDIR`) і беруть лише headless shell — більше воркеру нічого не потрібно. Спершу перевірте вільне місце командою `df -h / /tmp`;
якщо заповнений сам `/`, зазвичай допомагають `dnf clean all` і `journalctl --vacuum-size=100M`.

## Безпека
- Лише публічні https-сайти. Кожне з'єднання браузера (сторінка, вкладений ресурс, переспрямування) йде через локальний проксі,
  який у момент підключення перевіряє кінцеву адресу й відхиляє приватні адреси (зокрема метадані EC2 і підміну DNS — DNS rebinding).
- Переходи залишаються в межах вихідного сайту завдання; інші сайти можуть лише віддавати ресурси сторінки (GET); будь-які POST/PUT блокуються.
- CAPTCHA, 2FA і сторінки перевірки безпеки зупиняють запуск зі статусом «Потрібні ви» (waiting_human); нічого не обходиться.
- Скриншоти зберігаються на диску Render (не більше 2 МБ кожен, останні 50 завдань), доступ — лише у власника.
