# Браузерный агент (T-560) — установка на EC2-воркер

Карточка «Браузерный агент» на дашборде ставит в очередь задачи только на чтение (https-адрес и до 5 CSS-селекторов). EC2-воркер
(`factoryos-claude-worker`, пользователь `ec2-user`) открывает страницу в анонимном headless Chromium и возвращает прочитанный текст
и один скриншот. В этой версии нет входа в аккаунты, форм, регистрации и покупок; отправка форм в исполнителе по-прежнему отключена.

## Разовая установка (под root на EC2, Amazon Linux 2023)
```
dnf install -y nss atk at-spi2-atk cups-libs libdrm libxkbcommon libXcomposite libXdamage libXrandr mesa-libgbm pango alsa-lib
sudo -u ec2-user -H python3 -m pip install --user playwright
mkdir -p /home/ec2-user/pw-tmp && chown ec2-user /home/ec2-user/pw-tmp
sudo -u ec2-user -H env TMPDIR=/home/ec2-user/pw-tmp python3 -m playwright install --only-shell chromium
systemctl restart factoryos-claude-worker
```
Проверка: `journalctl -u factoryos-claude-worker --since "10 min ago" --no-pager | grep browser-tasks`. Если Playwright
не установлен, воркер один раз пишет в журнал "Playwright is not installed on this worker" и оставляет задачи в очереди.

Ошибка `ENOSPC: no space left on device` во время загрузки (встречалась 2026-11-13): в Amazon Linux папка `/tmp` — это tmpfs в оперативной памяти,
и на машине с 1 ГБ она слишком мала для архива размером около 186 МБ. Поэтому команды выше скачивают файлы в папку на диске
(`TMPDIR`) и берут только headless shell — больше воркеру ничего не нужно. Сначала проверьте свободное место командой `df -h / /tmp`;
если заполнен сам `/`, обычно помогают `dnf clean all` и `journalctl --vacuum-size=100M`.

## Безопасность
- Только публичные https-сайты. Каждое соединение браузера (страница, вложенный ресурс, перенаправление) идёт через локальный прокси,
  который в момент подключения проверяет итоговый адрес и отклоняет частные адреса (включая метаданные EC2 и подмену DNS — DNS rebinding).
- Переходы остаются в пределах исходного сайта задачи; другие сайты могут только отдавать ресурсы страницы (GET); любые POST/PUT блокируются.
- CAPTCHA, 2FA и страницы проверки безопасности останавливают запуск со статусом «Нужны вы» (waiting_human); ничего не обходится.
- Скриншоты хранятся на диске Render (не больше 2 МБ каждый, последние 50 задач), доступ — только у владельца.
