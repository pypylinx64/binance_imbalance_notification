import os
import asyncio
from datetime import datetime
import ccxt
import numpy as np
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


# ------------ ENV ------------
def load_env_file(path=".env"):
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()

                if not line or line.startswith("#"):
                    continue

                if "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    except FileNotFoundError:
        pass


# ------------ CONFIG ------------
load_env_file()
TOKEN = os.environ["TELEGRAM_TOKEN"]

INTERVAL = 60.0
LEVELS = 10

exchange = ccxt.binance({"enableRateLimit": True})
watcher_started = False


# ------------ UTILS ------------
def normalize_symbol(user_symbol):
    base = user_symbol.strip().upper()
    if not base.isalpha():
        raise ValueError("Symbol must contain letters only (e.g. BTC)")
    return base + "/USDT"


def calc_imbalance(order_book, depth=LEVELS):
    bids_list = order_book.get("bids", [])[:depth]
    asks_list = order_book.get("asks", [])[:depth]

    if bids_list:
        bids = np.array(bids_list, dtype=float)
        bid_vol = float(bids[:, 1].sum())
    else:
        bid_vol = 0.0

    if asks_list:
        asks = np.array(asks_list, dtype=float)
        ask_vol = float(asks[:, 1].sum())
    else:
        ask_vol = 0.0

    denom = bid_vol + ask_vol
    if denom == 0:
        return 0.0

    return float((bid_vol - ask_vol) / denom)


# ------------ WATCHER ------------
async def watcher_loop(app):
    while True:
        if not app.chat_data:
            await asyncio.sleep(0.5)
            continue

        for chat_id, cfg in list(app.chat_data.items()):
            symbol = cfg.get("symbol")
            x = cfg.get("x")

            if not symbol or x is None:
                continue

            try:
                ob = await asyncio.to_thread(exchange.fetch_order_book, symbol, LEVELS)
                imbalance = calc_imbalance(ob, depth=LEVELS)

            except Exception:
                continue

            # Only alert when crossing above threshold (not already alerted)
            last_alert = cfg.get("last_alert")

            if imbalance > x and (last_alert is None or last_alert <= x):
                # Crossing above threshold - send alert
                cfg["last_alert"] = imbalance

                text = f"""\
⚠ {symbol} imbalance alert ⚠
-----------------------------
Current imbalance: {imbalance:.3f}
Alert imbalance (X): {x:.3f}
Current datetime: {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}
---------------------------------
Buyers are stronger than sellers.
"""
                try:
                    await app.bot.send_message(chat_id=chat_id, text=text)
                except Exception:
                    pass
            elif imbalance <= x:
                # Reset alert state when imbalance drops below threshold
                cfg["last_alert"] = imbalance

        await asyncio.sleep(INTERVAL)


# ------------ TELEGRAM API ------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    global watcher_started

    if not watcher_started:
        watcher_started = True
        asyncio.create_task(watcher_loop(context.application))

    text = f"""\
This bot watches the Binance order book.

When buying pressure becomes much stronger
than selling pressure, you get an alert.

Commands:
/start  – show this message
/set BTC 0.3  – set or replace alert
/del    – disable alerts

X controls sensitivity:
higher X = stronger buyer pressure
required for a notification.

Time update: {INTERVAL / 60} min; 
TOP ask/bids: {LEVELS};
"""

    await update.message.reply_text(text)


async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /set SYMBOL X")
        return

    try:
        symbol = normalize_symbol(context.args[0])
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    try:
        x = float(context.args[1])
    except ValueError:
        await update.message.reply_text("X must be a number")
        return

    # Market validation
    try:
        exchange.load_markets()
        if symbol not in exchange.markets:
            await update.message.reply_text("Pair not found on Binance")
            return
        
    except Exception:
        pass

    context.chat_data["symbol"] = symbol
    context.chat_data["x"] = x
    context.chat_data["last_alert"] = None

    await update.message.reply_text(f"Set {symbol} X={x}")

async def cmd_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.chat_data:
        await update.message.reply_text("Nothing to delete")
        return

    context.chat_data.clear()
    await update.message.reply_text("Alerts disabled")

# ------------ MAIN ------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("set", cmd_set))
    app.add_handler(CommandHandler("del", cmd_del))

    app.run_polling()


if __name__ == "__main__":
    main()
