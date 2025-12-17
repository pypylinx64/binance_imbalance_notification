import os
import asyncio
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


load_env_file()
TOKEN = os.environ["TELEGRAM_TOKEN"]


# ------------ CONFIG ------------
INTERVAL = 1.0
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

    bid_vol = float(np.array(bids_list, dtype=float)[:, 1].sum()) if bids_list else 0.0
    ask_vol = float(np.array(asks_list, dtype=float)[:, 1].sum()) if asks_list else 0.0

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
            last_alert = cfg.get("last_alert")

            if not symbol or x is None:
                continue

            try:
                ob = exchange.fetch_order_book(symbol, limit=LEVELS)
                imbalance = calc_imbalance(ob, depth=LEVELS)
            except Exception:
                continue

            if imbalance > x:
                if last_alert is not None and abs(imbalance - last_alert) < 0.02:
                    continue

                cfg["last_alert"] = imbalance

                text = f"""\
{symbol} imbalance alert

Current imbalance: {imbalance:.3f}
Alert threshold (X): {x:.3f}

Buying pressure is stronger than selling pressure.
"""
                try:
                    await app.bot.send_message(chat_id=chat_id, text=text)
                except Exception:
                    pass

        await asyncio.sleep(INTERVAL)


# ------------ TELEGRAM API ------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global watcher_started
    if not watcher_started:
        watcher_started = True
        asyncio.create_task(watcher_loop(context.application))

    text = f"""\
This bot watches the Binance order book.

It compares how much traders want to BUY
with how much they want to SELL near the current price.

When buying pressure becomes much stronger
than selling pressure, you get an alert.

Command:
  /set BTC 0.3

X controls sensitivity:
higher X = only very strong buyer pressure
will trigger a notification.
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

    # Optional market validation
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


# ------------ MAIN ------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("set", cmd_set))

    app.run_polling()


if __name__ == "__main__":
    main()
