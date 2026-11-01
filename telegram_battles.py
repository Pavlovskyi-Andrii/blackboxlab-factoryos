"""T-587 Telegram Battle controls for the paired owner bridge.

The owner can list Battle Runs, open one battle (summary + judge pick + owner decision), compare its candidate
chains (per-step provenance and final output excerpt) and see factual outcome metrics from the T-583 leaderboard.
The only actions are the two safe owner decisions from `battle_runs.OWNER_ACTIONS`: approve one completed chain as
the winner, or reject the candidates. Neither publishes, runs a provider, creates a job or edits a candidate;
publication still goes through the normal human approval gate. Any other `battle:*` callback is refused.

Callback data (all under Telegram's 64-byte limit):
  battle:list · battle:view:<id> · battle:chains:<id> · battle:metrics:<id> · battle:approve:<id>:c<n> · battle:reject:<id>
"""
import re
from typing import Callable, Optional

from battle_runs import OUTCOME_METRICS, BattleError

BATTLE_ID = r"battle_[0-9a-f]{16}"
LIST_LIMIT = 8
TEXT_LIMIT = 3900
PUBLISH_GATE = "🔒 Публикация: только после ручного одобрения в очереди публикаций. Автопубликации нет; эти кнопки ничего не публикуют."
STATUS_TEXT = {"planned": "🗓 запланирован", "running": "⏳ идёт", "completed": "✅ завершён"}
METRIC_LABELS = {"views": "просмотры", "reach": "охват", "likes": "лайки", "comments": "комментарии", "shares": "репосты",
                 "saves": "сохранения", "conversions": "конверсии", "ctr_pct": "CTR %", "retention_pct": "удержание %",
                 "completion_rate_pct": "досмотры %"}


def _short(chain_id: str) -> str:
    return chain_id.rsplit(".", 1)[-1]


def _steps_line(chain: dict) -> str:
    return " ▸ ".join(f"{s['role']}→{s['operator']}" for s in chain.get("steps") or [])


def _num(value) -> str:
    if value is None:
        return "нет данных"
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


class BattleTelegram:
    """Battle view + safe owner decisions over Telegram. `latest_snapshot(publish_id)` feeds the factual metrics."""

    def __init__(self, store, latest_snapshot: Optional[Callable[[str], Optional[dict]]] = None, decided_by: str = "telegram-owner"):
        self.store = store
        self.latest_snapshot = latest_snapshot
        self.decided_by = decided_by

    # ---- rendering -------------------------------------------------------------------------------------------
    def _decision_line(self, battle: dict) -> str:
        decisions = self.store.owner_decisions(battle["battle_id"])
        if not decisions:
            return "Решение владельца: нет"
        d = decisions[-1]
        if d["action"] == "approve":
            label = next((c["label"] for c in battle["chains"] if c["chain_id"] == d["chain_id"]), d["chain_id"])
            return f"Решение владельца: ✅ одобрена {_short(d['chain_id'])} · {label} ({d['decided_at'][:16]})"
        return f"Решение владельца: ❌ кандидаты отклонены ({d['decided_at'][:16]})"

    def list_text(self) -> tuple:
        battles = self.store.list(limit=LIST_LIMIT)
        if not battles:
            return "⚔️ Battle Runs\n\nБаттлов пока нет.", {"inline_keyboard": [[{"text": "🔄 Обновить", "callback_data": "battle:list"}]]}
        lines, rows = ["⚔️ Battle Runs (последние)"], []
        for b in battles:
            lines.append(f"• {b['battle_id']} · {STATUS_TEXT.get(b['status'], b['status'])} · цепочек: {len(b['chains'])}"
                         f"\n  {b['brief'][:90]}")
            rows.append([{"text": "⚔️ " + b["battle_id"][7:15] + " · " + b["brief"][:24], "callback_data": "battle:view:" + b["battle_id"]}])
        return "\n".join(lines)[:TEXT_LIMIT], {"inline_keyboard": rows}

    def _keyboard(self, battle: dict) -> dict:
        bid = battle["battle_id"]
        rows = [[{"text": "🔗 Цепочки", "callback_data": "battle:chains:" + bid},
                 {"text": "📊 Метрики", "callback_data": "battle:metrics:" + bid}]]
        approve = [{"text": "✅ Одобрить " + _short(c["chain_id"]), "callback_data": f"battle:approve:{bid}:{_short(c['chain_id'])}"}
                   for c in battle["chains"] if c["status"] == "completed"]
        for i in range(0, len(approve), 3):
            rows.append(approve[i:i + 3])
        rows.append([{"text": "❌ Отклонить кандидатов", "callback_data": "battle:reject:" + bid},
                     {"text": "⬅️ Все баттлы", "callback_data": "battle:list"}])
        return {"inline_keyboard": rows}

    def summary_text(self, battle: dict) -> str:
        lines = [f"⚔️ Battle {battle['battle_id']}",
                 f"Тип: {battle['kind']} · статус: {STATUS_TEXT.get(battle['status'], battle['status'])}",
                 "Бриф: " + battle["brief"][:300], "", f"Цепочки ({len(battle['chains'])}):"]
        for c in battle["chains"]:
            done = sum(1 for s in c["steps"] if s["status"] == "completed")
            lines.append(f"• {_short(c['chain_id'])} · {c['label']} · {STATUS_TEXT.get(c['status'], c['status'])} "
                         f"({done}/{len(c['steps'])} шагов)\n  {_steps_line(c)}")
        reviews = self.store.reviews(battle["battle_id"])
        lines.append("")
        if reviews:
            for r in reviews:
                totals = " · ".join(f"{_short(k)} {v}" for k, v in r["totals"].items())
                flag = "" if r["selection_matches_scores"] else " ⚠️ выбор не совпадает с баллами"
                lines.append(f"Судья {r['judge']['operator']}: выбрал {_short(r['selected_chain_id'])} ({totals}){flag}")
        else:
            lines.append("Судья: оценки нет")
        lines.extend([self._decision_line(battle), "", PUBLISH_GATE])
        return "\n".join(lines)[:TEXT_LIMIT]

    def chains_text(self, battle: dict) -> str:
        lines = [f"🔗 Кандидаты · {battle['battle_id']}"]
        for c in battle["chains"]:
            lines.extend(["", f"{_short(c['chain_id'])} · {c['label']} · {STATUS_TEXT.get(c['status'], c['status'])}"])
            for s in c["steps"]:
                res = s.get("result") or {}
                made = f"сделал {res['operator']} · {res['model']} · {res['runtime']}" if res else "результата нет"
                lines.append(f"  {s['index'] + 1}. {s['role']} → {s['operator']} ({made})")
            final = c["steps"][-1].get("result") if c["steps"] else None
            if final:
                excerpt = " ".join(str(final.get("output_excerpt") or "").split())[:300]
                ref = final.get("output_ref") or ""
                lines.append("  Итог: " + (excerpt or "(только ссылка)") + (f"\n  Ссылка: {ref}" if ref else ""))
                if final.get("output_hash"):
                    lines.append("  sha256: " + final["output_hash"][:16])
        return "\n".join(lines)[:TEXT_LIMIT]

    def metrics_text(self, battle: dict) -> str:
        lines = [f"📊 Метрики · {battle['battle_id']}"]
        if self.latest_snapshot is None:
            return "\n".join(lines + ["", "Источник метрик не подключён; данных нет."])
        board = self.store.leaderboard(battle["battle_id"], self.latest_snapshot, "views")
        lines.append("Рейтинг по просмотрам (среднее на измеренную публикацию)")
        for row in board["chains"]:
            rank = f"#{row['rank']}" if row["rank"] else "без ранга"
            lines.extend(["", f"{rank} · {_short(row['chain_id'])} · {row['label']} · публикаций: {row['published_items']}, "
                              f"измерено: {row['measured_items']}"])
            shown = [f"{METRIC_LABELS[m]}: {_num(row['metrics'][m]['total'] if row['metrics'][m]['total'] is not None else row['metrics'][m]['value'])}"
                     + (" (частично)" if row["metrics"][m]["status"] == "partial" else "")
                     for m, _ in OUTCOME_METRICS if row["metrics"][m]["status"] != "unavailable"]
            lines.append("  " + (" · ".join(shown) if shown else "нет данных"))
        lines.extend(["", "Только реальные снимки платформ. Нет данных — значит нет данных, не ноль."])
        return "\n".join(lines)[:TEXT_LIMIT]

    # ---- Telegram entry points ------------------------------------------------------------------------------
    def _send_battle(self, api, chat_id, battle, text):
        api("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": self._keyboard(battle)})

    def command(self, command: str, text: str, chat_id: str, api) -> dict:
        parts = text.split(maxsplit=1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""
        if command == "/battle" and arg:
            try:
                battle = self.store.get(arg)
            except BattleError:
                api("sendMessage", {"chat_id": chat_id, "text": "Баттл не найден. Пример: /battle battle_0123456789abcdef"})
                return {"handled": True}
            self._send_battle(api, chat_id, battle, self.summary_text(battle))
            return {"handled": True, "action": "battle", "battle_id": battle["battle_id"]}
        value, keyboard = self.list_text()
        api("sendMessage", {"chat_id": chat_id, "text": value, "reply_markup": keyboard})
        return {"handled": True, "action": "battles"}

    def callback(self, data: str, chat_id: str, callback_id: str, api) -> dict:
        if data == "battle:list":
            api("answerCallbackQuery", {"callback_query_id": callback_id})
            value, keyboard = self.list_text()
            api("sendMessage", {"chat_id": chat_id, "text": value, "reply_markup": keyboard})
            return {"handled": True, "action": "battles"}
        m = re.fullmatch(rf"battle:(view|chains|metrics|reject):({BATTLE_ID})", data) \
            or re.fullmatch(rf"battle:(approve):({BATTLE_ID}):(c\d)", data)
        if not m:
            # Publish, run, rerun or anything else is not a Telegram battle action.
            api("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Недоступно: из Telegram только просмотр и одобрение/отклонение. Публикация — через ручное одобрение."})
            return {"handled": True, "action": "battle_refused"}
        action, bid = m.group(1), m.group(2)
        try:
            battle = self.store.get(bid)
            if action in ("approve", "reject"):
                chain_id = f"{bid}.{m.group(3)}" if action == "approve" else ""
                decision, created = self.store.record_owner_decision(bid, action, chain_id, self.decided_by, "telegram")
                battle = self.store.get(bid)
                note = ("✅ Одобрено: " + _short(chain_id) if action == "approve" else "❌ Кандидаты отклонены") \
                    + ("" if created else " (уже записано)") + ". Ничего не опубликовано."
                api("answerCallbackQuery", {"callback_query_id": callback_id, "text": note[:190]})
                self._send_battle(api, chat_id, battle, note + "\n\n" + self.summary_text(battle))
                return {"handled": True, "action": "battle_" + action, "battle_id": bid, "chain_id": chain_id, "created": created}
            text = {"view": self.summary_text, "chains": self.chains_text, "metrics": self.metrics_text}[action](battle)
        except BattleError as exc:
            api("answerCallbackQuery", {"callback_query_id": callback_id, "text": str(exc.detail)[:190]})
            return {"handled": True, "action": "battle_error", "status_code": exc.status_code}
        api("answerCallbackQuery", {"callback_query_id": callback_id})
        self._send_battle(api, chat_id, battle, text)
        return {"handled": True, "action": "battle_" + action, "battle_id": bid}
