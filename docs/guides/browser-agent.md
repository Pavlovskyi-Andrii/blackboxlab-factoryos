# Browser agent (T-560) — install on the EC2 worker

The dashboard card "Браузерний агент" queues read-only tasks (an https URL + up to 5 CSS selectors). The EC2 worker
(`factoryos-claude-worker`, user `ec2-user`) opens the page in an anonymous headless Chromium, returns the text it read
and one screenshot. No logins, forms, registration or purchases in this slice; submit stays disabled in the executor.

## One-time install (as root on EC2, Amazon Linux 2023)
```
dnf install -y nss atk at-spi2-atk cups-libs libdrm libxkbcommon libXcomposite libXdamage libXrandr mesa-libgbm pango alsa-lib
sudo -u ec2-user -H python3 -m pip install --user playwright
mkdir -p /home/ec2-user/pw-tmp && chown ec2-user /home/ec2-user/pw-tmp
sudo -u ec2-user -H env TMPDIR=/home/ec2-user/pw-tmp python3 -m playwright install --only-shell chromium
systemctl restart factoryos-claude-worker
```
Check: `journalctl -u factoryos-claude-worker --since "10 min ago" --no-pager | grep browser-tasks`. Without
Playwright the worker logs once "Playwright is not installed on this worker" and leaves tasks queued.

`ENOSPC: no space left on device` during the download (seen 2026-11-13): on Amazon Linux `/tmp` is a RAM-backed tmpfs,
too small on a 1 GB instance for the ~186 MB archive, so the commands above download into a folder on the disk
(`TMPDIR`) and fetch only the headless shell, which is all the worker uses. Check space first with `df -h / /tmp`;
if `/` itself is full, `dnf clean all` and `journalctl --vacuum-size=100M` free the usual suspects.

## Safety
- Only public https hosts. Every browser connection (page, sub-resource, redirect) goes through a local proxy that checks
  the resolved address at connection time and refuses private ones (EC2 metadata included, DNS rebinding included).
- Navigation stays on the task's origin; other sites may only serve page resources (GET); any POST/PUT is blocked.
- CAPTCHA / 2FA / security pages stop the run as "Потрібні ви" (waiting_human); nothing is bypassed.
- Screenshots live on the Render disk (≤ 2 MB each, last 50 tasks), owner-only.
