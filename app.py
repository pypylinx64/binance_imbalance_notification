import os
import asyncio
import ccxt
import numpy as np
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


# ------------ OTHER ------------
def load_env_file(path=".env"):
    try:
        with open(path) as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k, v)

    except FileNotFoundError:
        pass

# ------------ CONFIG ------------
load_env_file()
TOKEN = os.environ["TELEGRAM_TOKEN"]

INTERVAL = 0.5
LEVELS = 10

exchange = ccxt.binance({"enableRateLimit": True})
watcher_started = False

# ------------ UTILS ------------
def normalize_symbol(user_symbol):
    base = user_symbol.strip().upper()

    if not base.isalpha():
        raise ValueError("Error: Symbol must contain letters only (e.g. BTC)")

    return base + "/USDT"

def calc_imbalance(order_book, depth=LEVELS):
    bids_list = order_book.get("bids", [])[:depth]
    asks_list = order_book.get("asks", [])[:depth]

    if bids_list:

        # [price, amount]
        bids = np.array(bids_list, dtype=float)  
        bid_vol = bids[:, 1].sum()

    else:
        bid_vol = 0.0

    if asks_list:
        asks = np.array(asks_list, dtype=float)
        ask_vol = asks[:, 1].sum()

    else:
        ask_vol = 0.0

    denom = bid_vol + ask_vol

    # bacause / 0 not imposible
    if denom == 0:
        return 0.0

    return float((bid_vol - ask_vol) / denom)


# ------------ TELEGRAM API ------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global watcher_started

    if not watcher_started:
        watcher_started = True
        asyncio.create_task(watcher_loop(context.application))

    text = f"""\
    This bot watches the Binance order book.
    It compares how much traders want to BUY with how much they want to SELL near the current price.
    When buying pressure becomes much stronger than selling pressure, you get an alert.

    Command: /set BTC 0.3

    X controls sensitivity: higher X = only very strong buyer pressure will trigger a notification.
    """

    await update.message.reply_text(text)

async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # chat_id = update.effective_chat.id

    if len(context.args) != 2:
        await update.message.reply_text("Usage: /set SYMBOL X")
        return

    symbol_text = context.args[0]
    x_text = context.args[1]

    try:
        symbol = normalize_symbol(symbol_text)

    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    try:
        x = float(x_text)

    except ValueError:
        await update.message.reply_text("Error: X must be a number")
        return

    try:
        exchange.load_markets()
        if symbol not in exchange.markets:
            await update.message.reply_text("Symbol not found on Binance")
            return
        
    except Exception:
        pass

    chats = context.application.chats
    chats[update.effective_chat.id] = {
        "symbol": symbol,
        "x": x,
        "last_alert": None,
    }

    await update.message.reply_text(f"Set {symbol} X={x}")

# ------------ WATCHER ------------
async def watcher_loop(app):
    chats = app.chats

    while True:
        if not chats:
            await asyncio.sleep(0.5)
            continue

        # iterate over all chats
        for chat_id, cfg in list(chats.items()):
            symbol = cfg["symbol"]
            x = cfg["x"]
            # last_alert = cfg["last_alert"]

            try:
                ob = exchange.fetch_order_book(symbol, limit=LEVELS)
                imbalance = calc_imbalance(ob, depth=LEVELS)

            except Exception:
                continue

            if imbalance > x:
                cfg["last_alert"] = imbalance

                text = f"""\
                ⚠ {symbol} imbalance alert ⚠
                Imbalance: {imbalance:.3f} (X = {x:.3f}).
                Buyers are stronger than sellers.
                """

                try:
                    await app.bot.send_message(chat_id=chat_id, text=text)

                except Exception:
                    pass

        await asyncio.sleep(INTERVAL)


# ------------ MAIN ------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # chat_id : "symbol": "BTC/USDT", "x": 0.3, "last_alert": None
    app.chats = {}

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("set", cmd_set))

    app.run_polling()


if __name__ == "__main__":
    main()
