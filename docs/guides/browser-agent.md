# Browser agent (T-560) — install on the EC2 worker

The dashboard card "Браузерний агент" queues read-only tasks (an https URL + up to 5 CSS selectors). The EC2 worker
(`factoryos-claude-worker`, user `ec2-user`) opens the page in an anonymous headless Chromium, returns the text it read
and one screenshot. No logins, forms, registration or purchases in this slice; submit stays disabled in the executor.

## One-time install (as root on EC2, Amazon Linux 2023)
```
dnf install -y nss atk at-spi2-atk cups-libs libdrm libxkbcommon libXcomposite libXdamage libXrandr mesa-libgbm pango alsa-lib
sudo -u ec2-user -H python3 -m pip install --user playwright
sudo -u ec2-user -H python3 -m playwright install chromium
systemctl restart factoryos-claude-worker
```
Check: `journalctl -u factoryos-claude-worker --since "10 min ago" --no-pager | grep browser-tasks`. Without
Playwright the worker logs once "Playwright is not installed on this worker" and leaves tasks queued.

## Safety
- Only public https hosts; the worker re-resolves the host and refuses private addresses (EC2 metadata included).
- Navigation stays on the task's origin; other sites may only serve page resources (GET); any POST/PUT is blocked.
- CAPTCHA / 2FA / security pages stop the run as "Потрібні ви" (waiting_human); nothing is bypassed.
- Screenshots live on the Render disk (≤ 2 MB each, last 50 tasks), owner-only.
