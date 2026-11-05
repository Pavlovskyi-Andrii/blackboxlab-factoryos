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

_BATTLE_TEXT = {
    "ru": {
        "publish_gate": "🔒 Публикация: только после ручного одобрения в очереди публикаций. Автопубликации нет; эти кнопки ничего не публикуют.",
        "status": {"planned": "🗓 запланирован", "running": "⏳ идёт", "completed": "✅ завершён"},
        "metrics": {
            "views": "просмотры", "reach": "охват", "likes": "лайки", "comments": "комментарии", "shares": "репосты",
            "saves": "сохранения", "conversions": "конверсии", "ctr_pct": "CTR %", "retention_pct": "удержание %",
            "completion_rate_pct": "досмотры %"
        },
        "no_data": "нет данных",
        "dec_none": "Решение владельца: нет",
        "dec_approve": "Решение владельца: ✅ одобрена {short_id} · {label} ({time})",
        "dec_reject": "Решение владельца: ❌ кандидаты отклонены ({time})",
        "list_title": "⚔️ Battle Runs (последние)",
        "list_empty": "⚔️ Battle Runs\n\nБаттлов пока нет.",
        "btn_refresh": "🔄 Обновить",
        "btn_chains": "🔗 Цепочки",
        "btn_metrics": "📊 Метрики",
        "btn_approve": "✅ Одобрить ",
        "btn_reject": "❌ Отклонить кандидатов",
        "btn_all": "⬅️ Все баттлы",
        "summary_type_status": "Тип: {kind} · статус: {status}",
        "summary_brief": "Бриф: ",
        "summary_chains_head": "Цепочки ({count}):",
        "summary_steps": "({done}/{total} шагов)",
        "judge_mismatch": " ⚠️ выбор не совпадает с баллами",
        "judge_selected": "Судья {operator}: выбрал {selected} ({totals}){flag}",
        "judge_none": "Судья: оценки нет",
        "chains_head": "🔗 Кандидаты · {battle_id}",
        "made_by": "сделал {operator} · {model} · {runtime}",
        "no_step_result": "результата нет",
        "final_result": "Итог: ",
        "link_only": "(только ссылка)",
        "link_ref": "\n  Ссылка: ",
        "metrics_head": "📊 Метрики · {battle_id}",
        "metrics_no_source": "Источник метрик не подключён; данных нет.",
        "metrics_ranking": "Рейтинг по просмотрам (среднее на измеренную публикацию)",
        "no_rank": "без ранга",
        "metrics_chain_row": "{rank} · {short_id} · {label} · публикаций: {published}, измерено: {measured}",
        "partial": " (частично)",
        "metrics_footer": "Только реальные снимки платформ. Нет данных — значит нет данных, не ноль.",
        "not_found": "Баттл не найден. Пример: /battle battle_0123456789abcdef",
        "refused": "Недоступно: из Telegram только просмотр и одобрение/отклонение. Публикация — через ручное одобрение.",
        "note_approved": "✅ Одобрено: ",
        "note_rejected": "❌ Кандидаты отклонены",
        "note_already": " (уже записано)",
        "note_suffix": ". Ничего не опубликовано.",
        "chains_label": "цепочек:",
    },
    "uk": {
        "publish_gate": "🔒 Публікація: тільки після ручного схвалення в черзі публікацій. Автопублікації немає; ці кнопки нічого не публікують.",
        "status": {"planned": "🗓 запланований", "running": "⏳ триває", "completed": "✅ завершений"},
        "metrics": {
            "views": "перегляди", "reach": "охоплення", "likes": "вподобайки", "comments": "коментарі", "shares": "репости",
            "saves": "збереження", "conversions": "конверсії", "ctr_pct": "CTR %", "retention_pct": "утримання %",
            "completion_rate_pct": "догляди %"
        },
        "no_data": "немає даних",
        "dec_none": "Рішення власника: немає",
        "dec_approve": "Рішення власника: ✅ схвалена {short_id} · {label} ({time})",
        "dec_reject": "Рішення власника: ❌ кандидати відхилені ({time})",
        "list_title": "⚔️ Battle Runs (останні)",
        "list_empty": "⚔️ Battle Runs\n\nБаттлів поки немає.",
        "btn_refresh": "🔄 Оновити",
        "btn_chains": "🔗 Ланцюжки",
        "btn_metrics": "📊 Метрики",
        "btn_approve": "✅ Схвалити ",
        "btn_reject": "❌ Відхилити кандидатів",
        "btn_all": "⬅️ Усі баттли",
        "summary_type_status": "Тип: {kind} · статус: {status}",
        "summary_brief": "Бриф: ",
        "summary_chains_head": "Ланцюжки ({count}):",
        "summary_steps": "({done}/{total} кроків)",
        "judge_mismatch": " ⚠️ вибір не збігається з балами",
        "judge_selected": "Суддя {operator}: вибрав {selected} ({totals}){flag}",
        "judge_none": "Суддя: оцінки немає",
        "chains_head": "🔗 Кандидати · {battle_id}",
        "made_by": "зробив {operator} · {model} · {runtime}",
        "no_step_result": "результату немає",
        "final_result": "Підсумок: ",
        "link_only": "(тільки посилання)",
        "link_ref": "\n  Посилання: ",
        "metrics_head": "📊 Метрики · {battle_id}",
        "metrics_no_source": "Джерело метрик не підключено; даних немає.",
        "metrics_ranking": "Рейтинг за переглядами (середнє на виміряну публікацію)",
        "no_rank": "без рангу",
        "metrics_chain_row": "{rank} · {short_id} · {label} · публікацій: {published}, виміряно: {measured}",
        "partial": " (частково)",
        "metrics_footer": "Тільки реальні знімки платформ. Немає даних — означає немає даних, не нуль.",
        "not_found": "Баттл не знайдено. Приклад: /battle battle_0123456789abcdef",
        "refused": "Недоступно: з Telegram тільки перегляд та схвалення/відхилення. Публікація — через ручне схвалення.",
        "note_approved": "✅ Схвалено: ",
        "note_rejected": "❌ Кандидати відхилені",
        "note_already": " (вже записано)",
        "note_suffix": ". Нічого не опубліковано.",
        "chains_label": "ланцюжків:",
    },
    "en": {
        "publish_gate": "🔒 Publishing: only after manual approval in the publishing queue. No automatic publishing; these buttons do not publish anything.",
        "status": {"planned": "🗓 planned", "running": "⏳ running", "completed": "✅ completed"},
        "metrics": {
            "views": "views", "reach": "reach", "likes": "likes", "comments": "comments", "shares": "shares",
            "saves": "saves", "conversions": "conversions", "ctr_pct": "CTR %", "retention_pct": "retention %",
            "completion_rate_pct": "completion %"
        },
        "no_data": "no data",
        "dec_none": "Owner decision: none",
        "dec_approve": "Owner decision: ✅ approved {short_id} · {label} ({time})",
        "dec_reject": "Owner decision: ❌ candidates rejected ({time})",
        "list_title": "⚔️ Battle Runs (recent)",
        "list_empty": "⚔️ Battle Runs\n\nNo battles yet.",
        "btn_refresh": "🔄 Refresh",
        "btn_chains": "🔗 Chains",
        "btn_metrics": "📊 Metrics",
        "btn_approve": "✅ Approve ",
        "btn_reject": "❌ Reject candidates",
        "btn_all": "⬅️ All battles",
        "summary_type_status": "Type: {kind} · status: {status}",
        "summary_brief": "Brief: ",
        "summary_chains_head": "Chains ({count}):",
        "summary_steps": "({done}/{total} steps)",
        "judge_mismatch": " ⚠️ selection does not match scores",
        "judge_selected": "Judge {operator}: selected {selected} ({totals}){flag}",
        "judge_none": "Judge: no rating",
        "chains_head": "🔗 Candidates · {battle_id}",
        "made_by": "done by {operator} · {model} · {runtime}",
        "no_step_result": "no result",
        "final_result": "Result: ",
        "link_only": "(link only)",
        "link_ref": "\n  Link: ",
        "metrics_head": "📊 Metrics · {battle_id}",
        "metrics_no_source": "Metrics source not connected; no data.",
        "metrics_ranking": "Ranking by views (average per measured publication)",
        "no_rank": "no rank",
        "metrics_chain_row": "{rank} · {short_id} · {label} · publications: {published}, measured: {measured}",
        "partial": " (partial)",
        "metrics_footer": "Real platform snapshots only. No data means no data, not zero.",
        "not_found": "Battle not found. Example: /battle battle_0123456789abcdef",
        "refused": "Unavailable: Telegram only supports viewing and approval/rejection. Publishing requires manual approval.",
        "note_approved": "✅ Approved: ",
        "note_rejected": "❌ Candidates rejected",
        "note_already": " (already recorded)",
        "note_suffix": ". Nothing published.",
        "chains_label": "chains:",
    },
}

PUBLISH_GATE = _BATTLE_TEXT["ru"]["publish_gate"]
STATUS_TEXT = _BATTLE_TEXT["ru"]["status"]
METRIC_LABELS = _BATTLE_TEXT["ru"]["metrics"]


def _t(lang: str = "ru") -> dict:
    return _BATTLE_TEXT.get(lang) or _BATTLE_TEXT["ru"]


def _short(chain_id: str) -> str:
    return chain_id.rsplit(".", 1)[-1]


def _steps_line(chain: dict) -> str:
    return " ▸ ".join(f"{s['role']}→{s['operator']}" for s in chain.get("steps") or [])


def _num(value, lang: str = "ru") -> str:
    if value is None:
        return _t(lang)["no_data"]
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


class BattleTelegram:
    """Battle view + safe owner decisions over Telegram. `latest_snapshot(publish_id)` feeds the factual metrics."""

    def __init__(self, store, latest_snapshot: Optional[Callable[[str], Optional[dict]]] = None, decided_by: str = "telegram-owner"):
        self.store = store
        self.latest_snapshot = latest_snapshot
        self.decided_by = decided_by

    # ---- rendering -------------------------------------------------------------------------------------------
    def _decision_line(self, battle: dict, lang: str = "ru") -> str:
        t = _t(lang)
        decisions = self.store.owner_decisions(battle["battle_id"])
        if not decisions:
            return t["dec_none"]
        d = decisions[-1]
        if d["action"] == "approve":
            label = next((c["label"] for c in battle["chains"] if c["chain_id"] == d["chain_id"]), d["chain_id"])
            return t["dec_approve"].format(short_id=_short(d["chain_id"]), label=label, time=d["decided_at"][:16])
        return t["dec_reject"].format(time=d["decided_at"][:16])

    def list_text(self, lang: str = "ru") -> tuple:
        t = _t(lang)
        battles = self.store.list(limit=LIST_LIMIT)
        if not battles:
            return t["list_empty"], {"inline_keyboard": [[{"text": t["btn_refresh"], "callback_data": "battle:list"}]]}
        lines, rows = [t["list_title"]], []
        for b in battles:
            st = t["status"].get(b["status"], b["status"])
            lines.append(f"• {b['battle_id']} · {st} · {t['chains_label']} {len(b['chains'])}"
                         f"\n  {b['brief'][:90]}")
            rows.append([{"text": "⚔️ " + b["battle_id"][7:15] + " · " + b["brief"][:24], "callback_data": "battle:view:" + b["battle_id"]}])
        return "\n".join(lines)[:TEXT_LIMIT], {"inline_keyboard": rows}

    def _keyboard(self, battle: dict, lang: str = "ru") -> dict:
        t = _t(lang)
        bid = battle["battle_id"]
        rows = [[{"text": t["btn_chains"], "callback_data": "battle:chains:" + bid},
                 {"text": t["btn_metrics"], "callback_data": "battle:metrics:" + bid}]]
        approve = [{"text": t["btn_approve"] + _short(c["chain_id"]), "callback_data": f"battle:approve:{bid}:{_short(c['chain_id'])}"}
                   for c in battle["chains"] if c["status"] == "completed"]
        for i in range(0, len(approve), 3):
            rows.append(approve[i:i + 3])
        rows.append([{"text": t["btn_reject"], "callback_data": "battle:reject:" + bid},
                     {"text": t["btn_all"], "callback_data": "battle:list"}])
        return {"inline_keyboard": rows}

    def summary_text(self, battle: dict, lang: str = "ru") -> str:
        t = _t(lang)
        st = t["status"].get(battle["status"], battle["status"])
        lines = [f"⚔️ Battle {battle['battle_id']}",
                 t["summary_type_status"].format(kind=battle["kind"], status=st),
                 t["summary_brief"] + battle["brief"][:300], "",
                 t["summary_chains_head"].format(count=len(battle["chains"]))]
        for c in battle["chains"]:
            done = sum(1 for s in c["steps"] if s["status"] == "completed")
            c_st = t["status"].get(c["status"], c["status"])
            steps_str = t["summary_steps"].format(done=done, total=len(c["steps"]))
            lines.append(f"• {_short(c['chain_id'])} · {c['label']} · {c_st} {steps_str}"
                         f"\n  {_steps_line(c)}")
        reviews = self.store.reviews(battle["battle_id"])
        lines.append("")
        if reviews:
            for r in reviews:
                totals = " · ".join(f"{_short(k)} {v}" for k, v in r["totals"].items())
                flag = "" if r["selection_matches_scores"] else t["judge_mismatch"]
                lines.append(t["judge_selected"].format(operator=r["judge"]["operator"], selected=_short(r["selected_chain_id"]), totals=totals, flag=flag))
        else:
            lines.append(t["judge_none"])
        lines.extend([self._decision_line(battle, lang=lang), "", t["publish_gate"]])
        return "\n".join(lines)[:TEXT_LIMIT]

    def chains_text(self, battle: dict, lang: str = "ru") -> str:
        t = _t(lang)
        lines = [t["chains_head"].format(battle_id=battle["battle_id"])]
        for c in battle["chains"]:
            st = t["status"].get(c["status"], c["status"])
            lines.extend(["", f"{_short(c['chain_id'])} · {c['label']} · {st}"])
            for s in c["steps"]:
                res = s.get("result") or {}
                made = t["made_by"].format(operator=res["operator"], model=res["model"], runtime=res["runtime"]) if res else t["no_step_result"]
                lines.append(f"  {s['index'] + 1}. {s['role']} → {s['operator']} ({made})")
            final = c["steps"][-1].get("result") if c["steps"] else None
            if final:
                excerpt = " ".join(str(final.get("output_excerpt") or "").split())[:300]
                ref = final.get("output_ref") or ""
                lines.append("  " + t["final_result"] + (excerpt or t["link_only"]) + (f"{t['link_ref']}{ref}" if ref else ""))
                if final.get("output_hash"):
                    lines.append("  sha256: " + final["output_hash"][:16])
        return "\n".join(lines)[:TEXT_LIMIT]

    def metrics_text(self, battle: dict, lang: str = "ru") -> str:
        t = _t(lang)
        lines = [t["metrics_head"].format(battle_id=battle["battle_id"])]
        if self.latest_snapshot is None:
            return "\n".join(lines + ["", t["metrics_no_source"]])
        board = self.store.leaderboard(battle["battle_id"], self.latest_snapshot, "views")
        lines.append(t["metrics_ranking"])
        for row in board["chains"]:
            rank = f"#{row['rank']}" if row["rank"] else t["no_rank"]
            lines.extend(["", t["metrics_chain_row"].format(rank=rank, short_id=_short(row["chain_id"]), label=row["label"], published=row["published_items"], measured=row["measured_items"])
                        ])
            shown = [f"{t['metrics'][m]}: {_num(row['metrics'][m]['total'] if row['metrics'][m]['total'] is not None else row['metrics'][m]['value'], lang=lang)}"
                     + (t["partial"] if row["metrics"][m]["status"] == "partial" else "")
                     for m, _ in OUTCOME_METRICS if row["metrics"][m]["status"] != "unavailable"]
            lines.append("  " + (" · ".join(shown) if shown else t["no_data"]))
        lines.extend(["", t["metrics_footer"]])
        return "\n".join(lines)[:TEXT_LIMIT]

    # ---- Telegram entry points ------------------------------------------------------------------------------
    def _send_battle(self, api, chat_id, battle, text, lang: str = "ru"):
        api("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": self._keyboard(battle, lang=lang)})

    def command(self, command: str, text: str, chat_id: str, api, lang: str = "ru") -> dict:
        t = _t(lang)
        parts = text.split(maxsplit=1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""
        if command == "/battle" and arg:
            try:
                battle = self.store.get(arg)
            except BattleError:
                api("sendMessage", {"chat_id": chat_id, "text": t["not_found"]})
                return {"handled": True}
            self._send_battle(api, chat_id, battle, self.summary_text(battle, lang=lang), lang=lang)
            return {"handled": True, "action": "battle", "battle_id": battle["battle_id"]}
        value, keyboard = self.list_text(lang=lang)
        api("sendMessage", {"chat_id": chat_id, "text": value, "reply_markup": keyboard})
        return {"handled": True, "action": "battles"}

    def callback(self, data: str, chat_id: str, callback_id: str, api, lang: str = "ru") -> dict:
        t = _t(lang)
        if data == "battle:list":
            api("answerCallbackQuery", {"callback_query_id": callback_id})
            value, keyboard = self.list_text(lang=lang)
            api("sendMessage", {"chat_id": chat_id, "text": value, "reply_markup": keyboard})
            return {"handled": True, "action": "battles"}
        m = re.fullmatch(rf"battle:(view|chains|metrics|reject):({BATTLE_ID})", data) \
            or re.fullmatch(rf"battle:(approve):({BATTLE_ID}):(c\d)", data)
        if not m:
            # Publish, run, rerun or anything else is not a Telegram battle action.
            api("answerCallbackQuery", {"callback_query_id": callback_id, "text": t["refused"]})
            return {"handled": True, "action": "battle_refused"}
        action, bid = m.group(1), m.group(2)
        try:
            battle = self.store.get(bid)
            if action in ("approve", "reject"):
                chain_id = f"{bid}.{m.group(3)}" if action == "approve" else ""
                decision, created = self.store.record_owner_decision(bid, action, chain_id, self.decided_by, "telegram")
                battle = self.store.get(bid)
                note = (t["note_approved"] + _short(chain_id) if action == "approve" else t["note_rejected"])
                note += ("" if created else t["note_already"]) + t["note_suffix"]
                api("answerCallbackQuery", {"callback_query_id": callback_id, "text": note[:190]})
                self._send_battle(api, chat_id, battle, note + "\n\n" + self.summary_text(battle, lang=lang), lang=lang)
                return {"handled": True, "action": "battle_" + action, "battle_id": bid, "chain_id": chain_id, "created": created}
            fn = {"view": self.summary_text, "chains": self.chains_text, "metrics": self.metrics_text}[action]
            text = fn(battle, lang=lang)
        except BattleError as exc:
            api("answerCallbackQuery", {"callback_query_id": callback_id, "text": str(exc.detail)[:190]})
            return {"handled": True, "action": "battle_error", "status_code": exc.status_code}
        api("answerCallbackQuery", {"callback_query_id": callback_id})
        self._send_battle(api, chat_id, battle, text, lang=lang)
        return {"handled": True, "action": "battle_" + action, "battle_id": bid}
