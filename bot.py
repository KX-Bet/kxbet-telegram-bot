import os
import json
import asyncio
from datetime import datetime, timezone
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
FD_TOKEN = os.environ["FOOTBALL_DATA_TOKEN"]

FD_BASE = "https://api.football-data.org/v4"
STORE_PATH = "subscriptions.json"

TOP_COMPS = {
    "PL": "Premier League",
    "PD": "La Liga",
    "SA": "Serie A",
    "BL1": "Bundesliga",
    "FL1": "Ligue 1",
    "CL": "Champions League",
}

ALERT_TYPES = ["START", "HT", "GOAL", "FT"]

def load_store():
    if not os.path.exists(STORE_PATH):
        return {"users": {}, "matches": {}}
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_store(store):
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)

def fd_get(path, params=None):
    headers = {"X-Auth-Token": FD_TOKEN}
    r = requests.get(FD_BASE + path, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def today_iso():
    return datetime.now(timezone.utc).date().isoformat()

def match_label(m):
    home = m["homeTeam"].get("shortName") or m["homeTeam"]["name"]
    away = m["awayTeam"].get("shortName") or m["awayTeam"]["name"]
    status = m.get("status", "")
    utc_dt = m.get("utcDate", "")
    try:
        t = datetime.fromisoformat(utc_dt.replace("Z", "+00:00")).strftime("%H:%M")
    except Exception:
        t = "??:??"
    ft = m.get("score", {}).get("fullTime", {})
    hs, aas = ft.get("home"), ft.get("away")
    s = f"{hs}-{aas}" if hs is not None and aas is not None else "vs"
    return f"{t} • {home} {s} {away} • {status}"

def get_score_fulltime(m):
    ft = m.get("score", {}).get("fullTime", {})
    return (ft.get("home"), ft.get("away"))

def get_score_halftime(m):
    ht = m.get("score", {}).get("halfTime", {})
    return (ht.get("home"), ht.get("away"))

def ensure_user(store, user_id):
    if user_id not in store["users"]:
        store["users"][user_id] = {"match_ids": [], "alerts": ALERT_TYPES}

def ensure_match_state(store, match_id):
    if match_id not in store["matches"]:
        store["matches"][match_id] = {
            "last_status": None,
            "last_ft": [None, None],
            "sent": {"START": False, "HT": False, "FT": False},
        }

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ KXBet — alertes football\n\n"
        "➡️ /today : choisir les matchs du jour\n"
        "➡️ /my : tes matchs suivis"
    )

async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(name, callback_data=f"comp:{code}")]
                for code, name in TOP_COMPS.items()]
    await update.message.reply_text("Choisis une compétition :", reply_markup=InlineKeyboardMarkup(keyboard))

async def back_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    keyboard = [[InlineKeyboardButton(name, callback_data=f"comp:{code}")]
                for code, name in TOP_COMPS.items()]
    await q.edit_message_text("Choisis une compétition :", reply_markup=InlineKeyboardMarkup(keyboard))

async def comp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    comp_code = q.data.split(":", 1)[1]
    date = today_iso()

    data = fd_get(f"/competitions/{comp_code}/matches", params={"dateFrom": date, "dateTo": date})
    matches = data.get("matches", [])
    if not matches:
        await q.edit_message_text(f"Aucun match aujourd’hui pour {TOP_COMPS.get(comp_code, comp_code)}.")
        return

    store = load_store()
    user_id = str(q.from_user.id)
    subs = store.get("users", {}).get(user_id, {}).get("match_ids", [])

    buttons = []
    lines = [f"📅 {TOP_COMPS.get(comp_code, comp_code)} — {date}",
             "Clique sur un match pour suivre/désuivre :\n"]

    for m in matches[:20]:
        mid = str(m["id"])
        label = match_label(m)
        is_on = mid in subs
        buttons.append([InlineKeyboardButton(("✅ " if is_on else "🔔 ") + label[:55], callback_data=f"tog:{mid}")])
        lines.append(("✅ " if is_on else "🔔 ") + label)

    buttons.append([InlineKeyboardButton("↩️ Retour", callback_data="back:today")])

    await q.edit_message_text("\n".join(lines[:50]), reply_markup=InlineKeyboardMarkup(buttons))

async def toggle_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    match_id = q.data.split(":", 1)[1]

    store = load_store()
    user_id = str(q.from_user.id)
    ensure_user(store, user_id)
    ensure_match_state(store, match_id)

    subs = store["users"][user_id]["match_ids"]
    if match_id in subs:
        subs.remove(match_id)
        await q.answer("Désuivi 🛑", show_alert=False)
    else:
        subs.append(match_id)
        await q.answer("Suivi ✅", show_alert=False)

    save_store(store)

async def my_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store = load_store()
    user_id = str(update.effective_user.id)
    subs = store.get("users", {}).get(user_id, {}).get("match_ids", [])
    if not subs:
        await update.message.reply_text("Tu ne suis aucun match. Utilise /today.")
        return
    await update.message.reply_text("🎯 Matchs suivis (IDs) :\n" + "\n".join(f"- {m}" for m in subs[:30]))

async def notify_subscribers(app: Application, store, match_id: str, text: str):
    for uid, udata in store.get("users", {}).items():
        if match_id in udata.get("match_ids", []):
            try:
                await app.bot.send_message(chat_id=int(uid), text=text)
            except Exception:
                pass

async def poll_and_notify(app: Application):
    while True:
        store = load_store()

        tracked = set()
        for u in store.get("users", {}).values():
            tracked.update(u.get("match_ids", []))

        if not tracked:
            await asyncio.sleep(10)
            continue

        for mid in list(tracked):
            try:
                m = fd_get(f"/matches/{mid}").get("match")
                if not m:
                    continue

                ensure_match_state(store, mid)
                st = store["matches"][mid]

                status = m.get("status")
                ft = list(get_score_fulltime(m))
                ht = list(get_score_halftime(m))

                if status == "IN_PLAY" and not st["sent"]["START"]:
                    await notify_subscribers(app, store, mid, f"🟢 Début du match !\n{match_label(m)}")
                    st["sent"]["START"] = True

                if status == "PAUSED" and not st["sent"]["HT"]:
                    await notify_subscribers(app, store, mid, f"⏸️ Mi-temps : {ht[0]}-{ht[1]}\n{match_label(m)}")
                    st["sent"]["HT"] = True

                prev_ft = st.get("last_ft", [None, None])
                if ft[0] is not None and ft[1] is not None and prev_ft != ft:
                    if prev_ft != [None, None]:
                        await notify_subscribers(app, store, mid, f"⚽ BUT ! Score: {ft[0]}-{ft[1]}\n{match_label(m)}")
                    st["last_ft"] = ft

                if status == "FINISHED" and not st["sent"]["FT"]:
                    await notify_subscribers(app, store, mid, f"🏁 Fin : {ft[0]}-{ft[1]}\n{match_label(m)}")
                    st["sent"]["FT"] = True

                st["last_status"] = status
                store["matches"][mid] = st
                save_store(store)

            except Exception:
                pass

            await asyncio.sleep(7)

async def post_init(app: Application):
    app.create_task(poll_and_notify(app))

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("my", my_cmd))
    app.add_handler(CallbackQueryHandler(comp_callback, pattern=r"^comp:"))
    app.add_handler(CallbackQueryHandler(toggle_match, pattern=r"^tog:"))
    app.add_handler(CallbackQueryHandler(back_today, pattern=r"^back:today$"))
    app.post_init = post_init
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
