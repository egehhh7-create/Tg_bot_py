import os
import threading
from flask import Flask
import logging
import sqlite3
from datetime import datetime, timezone

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================
# FLASK WEB SERVER (Render)
# =========================
flask_app = Flask('')

@flask_app.route('/')
def home():
    return "Bot is alive and running 24/7!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

# =========================
# CONFIG
# =========================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8843032958:AAHncXJvH23jX98_jPHZQBUs5n4syAFLdhM")
ADMIN_ID = 8719367797

CHANNEL_1 = "@pement_proff"
CHANNEL_2 = "@CAPTCHA_BOT_LIVE_PAY1"

CHANNEL_1_URL = "https://t.me/pement_proff"
CHANNEL_2_URL = "https://t.me/CAPTCHA_BOT_LIVE_PAY1"

BKASH_NUMBER = "01952268398"
NAGAD_NUMBER = "01975776953"
SUPPORT_URL = "https://t.me/BD_INCOME_SUPPORT"

MIN_DEPOSIT = 200
MIN_WITHDRAW = 300
REFERRAL_BONUS = 100

PACKAGES = {
    1: {"deposit": 200, "bonus": 100, "total": 300},
    2: {"deposit": 400, "bonus": 230, "total": 630},
    3: {"deposit": 600, "bonus": 370, "total": 970},
    4: {"deposit": 1500, "bonus": 1780, "total": 3280},
    5: {"deposit": 2000, "bonus": 2320, "total": 4320},
    6: {"deposit": 2500, "bonus": 3000, "total": 5500},
}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# =========================
# DATABASE
# =========================

DB_PATH = os.environ.get("DB_PATH", "bot2.db")
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row


def db_execute(query, params=(), fetchone=False, fetchall=False, commit=False):
    cur = db.cursor()
    cur.execute(query, params)

    result = None

    if fetchone:
        result = cur.fetchone()
    elif fetchall:
        result = cur.fetchall()

    if commit:
        db.commit()

    return result


def init_db():
    # এর নিচের বাকি কোডগুলো আগের মতনই থাকবে...

    db_execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            balance REAL DEFAULT 0,
            referred_by INTEGER,
            referral_paid INTEGER DEFAULT 0,
            package_active INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """,
        commit=True,
    )

    db_execute(
        """
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            package_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            amount REAL NOT NULL,
            transaction_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
        """,
        commit=True,
    )

    db_execute(
        """
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            number TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
        """,
        commit=True,
    )


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_user(user_id):
    return db_execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,),
        fetchone=True,
    )


def ensure_user(user, referred_by=None):

    existing = get_user(user.id)

    if existing:

        db_execute(
            """
            UPDATE users
            SET username = ?, first_name = ?
            WHERE user_id = ?
            """,
            (
                user.username or "",
                user.first_name or "",
                user.id,
            ),
            commit=True,
        )

        return

    if referred_by == user.id:
        referred_by = None

    db_execute(
        """
        INSERT INTO users
        (
            user_id,
            username,
            first_name,
            balance,
            referred_by,
            referral_paid,
            package_active,
            created_at
        )
        VALUES (?, ?, ?, 0, ?, 0, 0, ?)
        """,
        (
            user.id,
            user.username or "",
            user.first_name or "",
            referred_by,
            now_iso(),
        ),
        commit=True,
    )


def get_balance(user_id):

    row = db_execute(
        "SELECT balance FROM users WHERE user_id = ?",
        (user_id,),
        fetchone=True,
    )

    if not row:
        return 0.0

    return float(row["balance"])


def change_balance(user_id, amount):

    db_execute(
        """
        UPDATE users
        SET balance = balance + ?
        WHERE user_id = ?
        """,
        (
            amount,
            user_id,
        ),
        commit=True,
    )


# =========================
# MAIN REPLY KEYBOARD
# =========================

def main_keyboard(user_id):

    rows = [
        ["📦 প্যাকেজ", "👤 মাই একাউন্ট"],
        ["💰 ডিপোজিট", "💸 উইথড্রো"],
        ["👥 রেফার আর্ন", "📞 সাপোর্ট"],
    ]

    if user_id == ADMIN_ID:

        rows.append(
            ["⚙️ এডমিন প্যানেল"]
        )

    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
    )


# =========================
# JOIN KEYBOARD
# =========================

def join_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 Channel 1",
                    url=CHANNEL_1_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    "📢 Channel 2",
                    url=CHANNEL_2_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ Join Complete",
                    callback_data="check_join",
                )
            ],
        ]
    )


# =========================
# MEMBERSHIP CHECK
# =========================

async def is_channel_member(
    bot,
    user_id,
    chat_id,
):

    try:

        member = await bot.get_chat_member(
            chat_id=chat_id,
            user_id=user_id,
        )

        return member.status in {
            "member",
            "administrator",
            "creator",
        }

    except Exception as exc:

        logger.warning(
            "Membership check failed for %s: %s",
            chat_id,
            exc,
        )

        return False


async def joined_required_channels(
    context,
    user_id,
):

    first = await is_channel_member(
        context.bot,
        user_id,
        CHANNEL_1,
    )

    second = await is_channel_member(
        context.bot,
        user_id,
        CHANNEL_2,
    )

    return first and second


# =========================
# START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    referred_by = None

    if context.args:

        try:

            candidate = int(
                context.args[0]
            )

            if (
                candidate != user.id
                and get_user(candidate)
            ):

                referred_by = candidate

        except (
            TypeError,
            ValueError,
        ):

            referred_by = None

    ensure_user(
        user,
        referred_by,
    )

    context.user_data.clear()

    joined = await joined_required_channels(
        context,
        user.id,
    )

    if not joined:

        await update.message.reply_text(
            "🔐 <b>বট ব্যবহার করার আগে নিচের ২টি Channel-এ Join করুন।</b>\n\n"
            "দুইটি Channel-এ Join করার পর "
            "<b>✅ Join Complete</b> বাটনে চাপুন।",
            parse_mode=ParseMode.HTML,
            reply_markup=join_keyboard(),
        )

        return

    await update.message.reply_text(
        "🎉 <b>স্বাগতম!</b>\n\n"
        "নিচের মেনু থেকে আপনার প্রয়োজনীয় অপশন নির্বাচন করুন।",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(user.id),
    )


# =========================
# PACKAGES
# =========================

async def packages_page(
    update,
    context,
):

    context.user_data.clear()

    buttons = []

    for package_id, item in PACKAGES.items():

        buttons.append(
            [
                InlineKeyboardButton(
                    f"📦 Package {package_id}: "
                    f"৳{item['deposit']} → "
                    f"৳{item['total']}",
                    callback_data=f"pkg_{package_id}",
                )
            ]
        )

    await update.message.reply_text(
        "📦 <b>প্যাকেজ লিস্ট</b>\n\n"
        "আপনার পছন্দের Package নির্বাচন করুন।",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


async def package_details(
    query,
    context,
    package_id,
):

    item = PACKAGES.get(
        package_id
    )

    if not item:

        await query.answer(
            "Package পাওয়া যায়নি।",
            show_alert=True,
        )

        return

    text = (
        f"📦 <b>Package {package_id}</b>\n\n"
        f"💳 Deposit: ৳{item['deposit']}\n"
        f"🎁 Bonus: ৳{item['bonus']}\n"
        f"💰 Total: ৳{item['total']}\n\n"
        "নিচের Deposit বাটনে চাপুন।"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💳 Deposit",
                    callback_data=f"buy_{package_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 প্যাকেজ লিস্ট",
                    callback_data="packages",
                )
            ],
        ]
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# =========================
# DEPOSIT
# =========================

async def deposit_method_page(
    query,
    context,
    package_id,
):

    item = PACKAGES.get(
        package_id
    )

    if not item:

        await query.answer(
            "Package পাওয়া যায়নি।",
            show_alert=True,
        )

        return

    context.user_data[
        "deposit_package"
    ] = package_id

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💚 bKash",
                    callback_data="dep_method_bkash",
                ),
                InlineKeyboardButton(
                    "🟢 Nagad",
                    callback_data="dep_method_nagad",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data=f"pkg_{package_id}",
                )
            ],
        ]
    )

    await query.edit_message_text(
        f"💳 <b>Deposit Method</b>\n\n"
        f"Package Amount: ৳{item['deposit']}\n\n"
        "একটি মাধ্যম নির্বাচন করুন।",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def choose_deposit_method(
    query,
    context,
    method,
):

    package_id = context.user_data.get(
        "deposit_package"
    )

    item = PACKAGES.get(
        package_id
    )

    if not item:

        await query.answer(
            "Deposit session পাওয়া যায়নি।",
            show_alert=True,
        )

        return

    context.user_data[
        "deposit_method"
    ] = method

    context.user_data[
        "state"
    ] = "deposit_amount"

    number = (
        BKASH_NUMBER
        if method == "bKash"
        else NAGAD_NUMBER
    )

    await query.edit_message_text(
        f"💳 <b>{method} Deposit</b>\n\n"
        f"📱 Number: <code>{number}</code>\n"
        f"💰 Package Amount: <b>৳{item['deposit']}</b>\n\n"
        f"উপরের নাম্বারে ৳{item['deposit']} টাকা পাঠিয়ে "
        "তারপর নিচে Amount লিখুন।",
        parse_mode=ParseMode.HTML,
    )


# =========================
# WITHDRAW
# =========================

async def withdraw_page(
    update,
    context,
):

    context.user_data.clear()

    user_id = update.effective_user.id

    balance = get_balance(
        user_id
    )

    if balance < MIN_WITHDRAW:

        await update.message.reply_text(
            f"💸 <b>উইথড্রো</b>\n\n"
            f"💰 আপনার Balance: ৳{balance:.2f}\n"
            f"⬇️ সর্বনিম্ন Withdraw: ৳{MIN_WITHDRAW}\n\n"
            "আপনার Balance এখনও Withdraw করার জন্য যথেষ্ট নয়।",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(
                user_id
            ),
        )

        return

    context.user_data[
        "state"
    ] = "withdraw_method"

    await update.message.reply_text(
        "💸 <b>উইথড্রো</b>\n\n"
        "bKash অথবা Nagad নির্বাচন করুন।",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💚 bKash",
                        callback_data="wd_method_bkash",
                    ),
                    InlineKeyboardButton(
                        "🟢 Nagad",
                        callback_data="wd_method_nagad",
                    ),
                ]
            ]
        ),
    )


async def choose_withdraw_method(
    query,
    context,
    method,
):

    context.user_data[
        "withdraw_method"
    ] = method

    context.user_data[
        "state"
    ] = "withdraw_number"

    await query.edit_message_text(
        f"💸 <b>{method} Withdraw</b>\n\n"
        f"আপনার {method} নাম্বার পাঠান।",
        parse_mode=ParseMode.HTML,
    )


# =========================
# ACCOUNT
# =========================

async def account_page(
    update,
    context,
):

    user_id = update.effective_user.id

    row = get_user(
        user_id
    )

    balance = get_balance(
        user_id
    )

    active = (
        bool(row["package_active"])
        if row
        else False
    )

    await update.message.reply_text(
        "👤 <b>মাই একাউন্ট</b>\n\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"💰 Balance: <b>৳{balance:.2f}</b>\n"
        f"📦 Account Active: "
        f"{'✅ হ্যাঁ' if active else '❌ না'}",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(
            user_id
        ),
    )


# =========================
# REFERRAL
# =========================

async def referral_page(
    update,
    context,
):

    user_id = update.effective_user.id

    me = await context.bot.get_me()

    link = (
        f"https://t.me/{me.username}"
        f"?start={user_id}"
    )

    row = db_execute(
        """
        SELECT COUNT(*) AS c
        FROM users
        WHERE referred_by = ?
        """,
        (user_id,),
        fetchone=True,
    )

    count = (
        int(row["c"])
        if row
        else 0
    )

    await update.message.reply_text(
        "👥 <b>রেফার আর্ন</b>\n\n"
        f"🔗 আপনার Referral Link:\n"
        f"<code>{link}</code>\n\n"
        f"👤 মোট Referral: {count}\n"
        f"🎁 Referral Bonus: ৳{REFERRAL_BONUS}\n\n"
        "আপনার লিংক দিয়ে কেউ Bot Start করে "
        "Package কিনে তার প্রথম Deposit সফলভাবে "
        "Approve করালে আপনি ৳100 Bonus পাবেন।",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(
            user_id
        ),
    )


# =========================
# SUPPORT
# =========================

async def support_page(
    update,
    context,
):

    await update.message.reply_text(
        "📞 <b>সাপোর্ট</b>\n\n"
        "যেকোনো সমস্যায় আমাদের Support-এ যোগাযোগ করুন।",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💬 Support",
                        url=SUPPORT_URL,
                    )
                ]
            ]
        ),
    )


# =========================
# ADMIN
# =========================

def admin_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💳 Pending Deposits",
                    callback_data="admin_deposits",
                )
            ],
            [
                InlineKeyboardButton(
                    "💸 Pending Withdrawals",
                    callback_data="admin_withdrawals",
                )
            ],
            [
                InlineKeyboardButton(
                    "➕ Balance Add",
                    callback_data="admin_add",
                )
            ],
            [
                InlineKeyboardButton(
                    "📢 Notice / Broadcast",
                    callback_data="admin_broadcast",
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Statistics",
                    callback_data="admin_stats",
                )
            ],
        ]
    )


async def admin_page(
    update,
    context,
):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "❌ এই অপশন শুধু Admin-এর জন্য।"
        )

        return

    context.user_data.clear()

    await update.message.reply_text(
        "⚙️ <b>এডমিন প্যানেল</b>\n\n"
        "নিচের অপশন থেকে কাজ নির্বাচন করুন।",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


# =========================
# ADMIN DEPOSITS
# =========================

async def admin_deposits_page(
    query,
):

    rows = db_execute(
        """
        SELECT
            id,
            user_id,
            package_id,
            method,
            amount
        FROM deposits
        WHERE status = 'pending'
        ORDER BY id DESC
        LIMIT 30
        """,
        fetchall=True,
    )

    buttons = []

    for row in rows:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"💰 #{row['id']} | "
                    f"User {row['user_id']} | "
                    f"৳{row['amount']:.0f}",
                    callback_data=f"depview_{row['id']}",
                )
            ]
        )

    if not buttons:

        text = (
            "💳 <b>Pending Deposits</b>\n\n"
            "কোনো pending deposit নেই।"
        )

    else:

        text = (
            "💳 <b>Pending Deposits</b>\n\n"
            "Request নির্বাচন করুন।"
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "🔙 Admin Panel",
                callback_data="admin",
            )
        ]
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


async def admin_deposit_view(
    query,
    deposit_id,
):

    row = db_execute(
        """
        SELECT
            d.*,
            u.username,
            u.first_name
        FROM deposits d
        LEFT JOIN users u
        ON u.user_id = d.user_id
        WHERE d.id = ?
        AND d.status = 'pending'
        """,
        (deposit_id,),
        fetchone=True,
    )

    if not row:

        await query.answer(
            "Request পাওয়া যায়নি।",
            show_alert=True,
        )

        return

    item = PACKAGES[
        row["package_id"]
    ]

    text = (
        "💳 <b>Deposit Request</b>\n\n"
        f"🆔 Request: #{row['id']}\n"
        f"👤 User ID: <code>{row['user_id']}</code>\n"
        f"👤 Name: {row['first_name'] or '-'}\n"
        f"📦 Package: {row['package_id']}\n"
        f"💳 Method: {row['method']}\n"
        f"💰 Deposit: ৳{row['amount']:.2f}\n"
        f"🎁 Bonus: ৳{item['bonus']}\n"
        f"💵 Total Add: ৳{item['total']}\n"
        f"🧾 Transaction ID: "
        f"<code>{row['transaction_id']}</code>"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=f"depapprove_{deposit_id}",
                ),
                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=f"depreject_{deposit_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="admin_deposits",
                )
            ],
        ]
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# =========================
# ADMIN WITHDRAWALS
# =========================

async def admin_withdrawals_page(
    query,
):

    rows = db_execute(
        """
        SELECT
            id,
            user_id,
            method,
            number,
            amount
        FROM withdrawals
        WHERE status = 'pending'
        ORDER BY id DESC
        LIMIT 30
        """,
        fetchall=True,
    )

    buttons = []

    for row in rows:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"💸 #{row['id']} | "
                    f"User {row['user_id']} | "
                    f"৳{row['amount']:.0f}",
                    callback_data=f"wdview_{row['id']}",
                )
            ]
        )

    if not buttons:

        text = (
            "💸 <b>Pending Withdrawals</b>\n\n"
            "কোনো pending withdrawal নেই।"
        )

    else:

        text = (
            "💸 <b>Pending Withdrawals</b>\n\n"
            "Request নির্বাচন করুন।"
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "🔙 Admin Panel",
                callback_data="admin",
            )
        ]
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
    )


async def admin_withdrawal_view(
    query,
    withdrawal_id,
):

    row = db_execute(
        """
        SELECT *
        FROM withdrawals
        WHERE id = ?
        AND status = 'pending'
        """,
        (withdrawal_id,),
        fetchone=True,
    )

    if not row:

        await query.answer(
            "Request পাওয়া যায়নি।",
            show_alert=True,
        )

        return

    text = (
        "💸 <b>Withdraw Request</b>\n\n"
        f"🆔 Request: #{row['id']}\n"
        f"👤 User ID: <code>{row['user_id']}</code>\n"
        f"💳 Method: {row['method']}\n"
        f"📱 Number: <code>{row['number']}</code>\n"
        f"💰 Amount: ৳{row['amount']:.2f}\n\n"
        "টাকা পাঠানোর পর Approve করুন।"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=f"wdapprove_{withdrawal_id}",
                ),
                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=f"wdreject_{withdrawal_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="admin_withdrawals",
                )
            ],
        ]
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# =========================
# CALLBACK HANDLER
# =========================

async def callback_handler(
    update,
    context,
):

    query = update.callback_query

    await query.answer()

    data = query.data

    user_id = query.from_user.id

    # JOIN CHECK
    if data == "check_join":

        if not await joined_required_channels(
            context,
            user_id,
        ):

            await query.answer(
                "❌ আগে দুইটি Channel-এ Join করুন।",
                show_alert=True,
            )

            return

        await query.edit_message_text(
            "✅ <b>Join Complete!</b>\n\n"
            "নিচের Keyboard থেকে অপশন নির্বাচন করুন।",
            parse_mode=ParseMode.HTML,
        )

        await context.bot.send_message(
            chat_id=user_id,
            text="🏠 Main Menu",
            reply_markup=main_keyboard(
                user_id
            ),
        )

        return

    # HOME
    if data == "home":

        await query.edit_message_text(
            "🏠 <b>Main Menu</b>\n\n"
            "নিচের Keyboard ব্যবহার করুন।",
            parse_mode=ParseMode.HTML,
        )

        return

    # PACKAGES
    if data == "packages":

        buttons = []

        for package_id, item in PACKAGES.items():

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"📦 Package {package_id}: "
                        f"৳{item['deposit']} → "
                        f"৳{item['total']}",
                        callback_data=f"pkg_{package_id}",
                    )
                ]
            )

        await query.edit_message_text(
            "📦 <b>প্যাকেজ লিস্ট</b>\n\n"
            "Package নির্বাচন করুন।",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                buttons
            ),
        )

        return

    # PACKAGE
    if data.startswith("pkg_"):

        package_id = int(
            data.split("_")[1]
        )

        await package_details(
            query,
            context,
            package_id,
        )

        return

    # BUY
    if data.startswith("buy_"):

        package_id = int(
            data.split("_")[1]
        )

        await deposit_method_page(
            query,
            context,
            package_id,
        )

        return

    # DEPOSIT BKASH
    if data == "dep_method_bkash":

        await choose_deposit_method(
            query,
            context,
            "bKash",
        )

        return

    # DEPOSIT NAGAD
    if data == "dep_method_nagad":

        await choose_deposit_method(
            query,
            context,
            "Nagad",
        )

        return

    # WITHDRAW BKASH
    if data == "wd_method_bkash":

        await choose_withdraw_method(
            query,
            context,
            "bKash",
        )

        return

    # WITHDRAW NAGAD
    if data == "wd_method_nagad":

        await choose_withdraw_method(
            query,
            context,
            "Nagad",
        )

        return

    # ADMIN
    if data == "admin":

        if user_id != ADMIN_ID:
            return

        await query.edit_message_text(
            "⚙️ <b>এডমিন প্যানেল</b>\n\n"
            "নিচের অপশন থেকে কাজ নির্বাচন করুন।",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard(),
        )

        return

    # ADMIN DEPOSITS
    if data == "admin_deposits":

        if user_id == ADMIN_ID:

            await admin_deposits_page(
                query
            )

        return

    # ADMIN WITHDRAWALS
    if data == "admin_withdrawals":

        if user_id == ADMIN_ID:

            await admin_withdrawals_page(
                query
            )

        return

    # DEPOSIT VIEW
    if data.startswith("depview_"):

        if user_id == ADMIN_ID:

            deposit_id = int(
                data.split("_")[1]
            )

            await admin_deposit_view(
                query,
                deposit_id,
            )

        return

    # WITHDRAW VIEW
    if data.startswith("wdview_"):

        if user_id == ADMIN_ID:

            withdrawal_id = int(
                data.split("_")[1]
            )

            await admin_withdrawal_view(
                query,
                withdrawal_id,
            )

        return

    # APPROVE DEPOSIT
    if data.startswith("depapprove_"):

        if user_id != ADMIN_ID:
            return

        deposit_id = int(
            data.split("_")[1]
        )

        row = db_execute(
            """
            SELECT *
            FROM deposits
            WHERE id = ?
            AND status = 'pending'
            """,
            (deposit_id,),
            fetchone=True,
        )

        if not row:

            await query.answer(
                "Request পাওয়া যায়নি।",
                show_alert=True,
            )

            return

        item = PACKAGES[
            row["package_id"]
        ]

        target = row["user_id"]

        db_execute(
            """
            UPDATE deposits
            SET status = 'approved'
            WHERE id = ?
            """,
            (deposit_id,),
            commit=True,
        )

        change_balance(
            target,
            item["total"],
        )

        db_execute(
            """
            UPDATE users
            SET package_active = 1
            WHERE user_id = ?
            """,
            (target,),
            commit=True,
        )

        # REFERRAL BONUS
        ref = db_execute(
            """
            SELECT referred_by, referral_paid
            FROM users
            WHERE user_id = ?
            """,
            (target,),
            fetchone=True,
        )

        if (
            ref
            and ref["referred_by"]
            and not ref["referral_paid"]
        ):

            referrer = ref[
                "referred_by"
            ]

            change_balance(
                referrer,
                REFERRAL_BONUS,
            )

            db_execute(
                """
                UPDATE users
                SET referral_paid = 1
                WHERE user_id = ?
                """,
                (target,),
                commit=True,
            )

            try:

                await context.bot.send_message(
                    referrer,
                    "🎉 <b>Referral Bonus</b>\n\n"
                    "আপনার Referral User Package কিনেছে।\n"
                    f"🎁 Bonus: ৳{REFERRAL_BONUS}\n"
                    f"💰 Balance: "
                    f"৳{get_balance(referrer):.2f}",
                    parse_mode=ParseMode.HTML,
                )

            except Exception:
                pass

        try:

            await context.bot.send_message(
                target,
                "✅ <b>Deposit Approved!</b>\n\n"
                f"💳 Deposit: ৳{item['deposit']}\n"
                f"🎁 Bonus: ৳{item['bonus']}\n"
                f"💰 Total Added: ৳{item['total']}\n"
                f"📊 Current Balance: "
                f"৳{get_balance(target):.2f}",
                parse_mode=ParseMode.HTML,
            )

        except Exception:
            pass

        await query.edit_message_text(
            "✅ <b>Deposit Approved</b>\n\n"
            f"User: {target}\n"
            f"Added: ৳{item['total']}",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard(),
        )

        return

    # REJECT DEPOSIT
    if data.startswith("depreject_"):

        if user_id != ADMIN_ID:
            return

        deposit_id = int(
            data.split("_")[1]
        )

        row = db_execute(
            """
            SELECT user_id
            FROM deposits
            WHERE id = ?
            AND status = 'pending'
            """,
            (deposit_id,),
            fetchone=True,
        )

        if not row:

            await query.answer(
                "Request পাওয়া যায়নি।",
                show_alert=True,
            )

            return

        target = row["user_id"]

        db_execute(
            """
            UPDATE deposits
            SET status = 'rejected'
            WHERE id = ?
            """,
            (deposit_id,),
            commit=True,
        )

        try:

            await context.bot.send_message(
                target,
                "❌ আপনার Deposit Request Reject করা হয়েছে।\n"
                "Transaction তথ্য যাচাই করা যায়নি।",
            )

        except Exception:
            pass

        await query.edit_message_text(
            f"❌ <b>Deposit Rejected</b>\n\n"
            f"User: {target}",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard(),
        )

        return

    # APPROVE WITHDRAW
    if data.startswith("wdapprove_"):

        if user_id != ADMIN_ID:
            return

        withdrawal_id = int(
            data.split("_")[1]
        )

        row = db_execute(
            """
            SELECT *
            FROM withdrawals
            WHERE id = ?
            AND status = 'pending'
            """,
            (withdrawal_id,),
            fetchone=True,
        )

        if not row:

            await query.answer(
                "Request পাওয়া যায়নি।",
                show_alert=True,
            )

            return

        db_execute(
            """
            UPDATE withdrawals
            SET status = 'approved'
            WHERE id = ?
            """,
            (withdrawal_id,),
            commit=True,
        )

        try:

            await context.bot.send_message(
                row["user_id"],
                "✅ <b>Withdraw Approved!</b>\n\n"
                f"💳 Method: {row['method']}\n"
                f"💰 Amount: ৳{row['amount']:.2f}\n"
                "Payment পাঠানো হয়েছে।",
                parse_mode=ParseMode.HTML,
            )

        except Exception:
            pass

        await query.edit_message_text(
            "✅ <b>Withdrawal Approved</b>\n\n"
            f"User: {row['user_id']}\n"
            f"Amount: ৳{row['amount']:.2f}",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard(),
        )

        return

    # REJECT WITHDRAW
    if data.startswith("wdreject_"):

        if user_id != ADMIN_ID:
            return

        withdrawal_id = int(
            data.split("_")[1]
        )

        row = db_execute(
            """
            SELECT *
            FROM withdrawals
            WHERE id = ?
            AND status = 'pending'
            """,
            (withdrawal_id,),
            fetchone=True,
        )

        if not row:

            await query.answer(
                "Request পাওয়া যায়নি।",
                show_alert=True,
            )

            return

        db_execute(
            """
            UPDATE withdrawals
            SET status = 'rejected'
            WHERE id = ?
            """,
            (withdrawal_id,),
            commit=True,
        )

        change_balance(
            row["user_id"],
            row["amount"],
        )

        try:

            await context.bot.send_message(
                row["user_id"],
                "❌ <b>Withdraw Rejected</b>\n\n"
                f"৳{row['amount']:.2f} "
                "আপনার Balance-এ ফেরত দেওয়া হয়েছে।",
                parse_mode=ParseMode.HTML,
            )

        except Exception:
            pass

        await query.edit_message_text(
            "❌ <b>Withdrawal Rejected</b>\n\n"
            f"User: {row['user_id']}\n"
            f"Amount ফেরত: "
            f"৳{row['amount']:.2f}",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard(),
        )

        return

    # ADMIN ADD BALANCE
    if data == "admin_add":

        if user_id != ADMIN_ID:
            return

        context.user_data[
            "state"
        ] = "admin_add"

        await query.edit_message_text(
            "➕ <b>Balance Add</b>\n\n"
            "এই format-এ পাঠান:\n\n"
            "<code>USER_ID AMOUNT</code>\n\n"
            "উদাহরণ:\n"
            "<code>123456789 500</code>",
            parse_mode=ParseMode.HTML,
        )

        return

    # ADMIN BROADCAST
    if data == "admin_broadcast":

        if user_id != ADMIN_ID:
            return

        context.user_data[
            "state"
        ] = "admin_broadcast"

        await query.edit_message_text(
            "📢 <b>Broadcast Notice</b>\n\n"
            "যে Notice সবাইকে পাঠাতে চান, "
            "এখন সেটি লিখে পাঠান।",
            parse_mode=ParseMode.HTML,
        )

        return

    # ADMIN STATISTICS
    if data == "admin_stats":

        if user_id != ADMIN_ID:
            return

        users = db_execute(
            "SELECT COUNT(*) AS c FROM users",
            fetchone=True,
        )["c"]

        pending_dep = db_execute(
            """
            SELECT COUNT(*) AS c
            FROM deposits
            WHERE status = 'pending'
            """,
            fetchone=True,
        )["c"]

        pending_wd = db_execute(
            """
            SELECT COUNT(*) AS c
            FROM withdrawals
            WHERE status = 'pending'
            """,
            fetchone=True,
        )["c"]

        total_balance = db_execute(
            """
            SELECT COALESCE(
                SUM(balance),
                0
            ) AS s
            FROM users
            """,
            fetchone=True,
        )["s"]

        await query.edit_message_text(
            "📊 <b>Statistics</b>\n\n"
            f"👥 Users: {users}\n"
            f"💳 Pending Deposits: {pending_dep}\n"
            f"💸 Pending Withdrawals: {pending_wd}\n"
            f"💰 Total Balance: "
            f"৳{float(total_balance):.2f}",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard(),
        )

        return


# =========================
# TEXT HANDLER
# =========================

async def text_handler(
    update,
    context,
):

    user = update.effective_user

    text = update.message.text.strip()

    state = context.user_data.get(
        "state"
    )

    ensure_user(user)

    # MAIN MENU

    if text == "📦 প্যাকেজ":

        await packages_page(
            update,
            context,
        )

        return

    if text == "👤 মাই একাউন্ট":

        await account_page(
            update,
            context,
        )

        return

    if text == "💰 ডিপোজিট":

        await packages_page(
            update,
            context,
        )

        return

    if text == "💸 উইথড্রো":

        await withdraw_page(
            update,
            context,
        )

        return

    if text == "👥 রেফার আর্ন":

        await referral_page(
            update,
            context,
        )

        return

    if text == "📞 সাপোর্ট":

        await support_page(
            update,
            context,
        )

        return

    if text == "⚙️ এডমিন প্যানেল":

        await admin_page(
            update,
            context,
        )

        return

    # =====================
    # DEPOSIT AMOUNT
    # =====================

    if state == "deposit_amount":

        package_id = context.user_data.get(
            "deposit_package"
        )

        method = context.user_data.get(
            "deposit_method"
        )

        item = PACKAGES.get(
            package_id
        )

        if not item or not method:

            context.user_data.clear()

            await update.message.reply_text(
                "❌ Deposit session শেষ হয়েছে। "
                "আবার Deposit থেকে শুরু করুন।",
                reply_markup=main_keyboard(
                    user.id
                ),
            )

            return

        try:

            amount = float(
                text.replace(",", "")
            )

        except ValueError:

            await update.message.reply_text(
                "❌ শুধু সঠিক সংখ্যায় Amount লিখুন।"
            )

            return

        if amount != item["deposit"]:

            await update.message.reply_text(
                f"❌ এই Package-এর সঠিক "
                f"Deposit Amount হলো "
                f"৳{item['deposit']}।"
            )

            return

        context.user_data[
            "deposit_amount"
        ] = amount

        context.user_data[
            "state"
        ] = "deposit_txid"

        await update.message.reply_text(
            "🧾 এখন আপনার "
            "<b>Transaction ID</b> পাঠান।",
            parse_mode=ParseMode.HTML,
        )

        return

    # =====================
    # DEPOSIT TXID
    # =====================

    if state == "deposit_txid":

        package_id = context.user_data.get(
            "deposit_package"
        )

        method = context.user_data.get(
            "deposit_method"
        )

        amount = context.user_data.get(
            "deposit_amount"
        )

        item = PACKAGES.get(
            package_id
        )

        if (
            not item
            or not method
            or amount is None
        ):

            context.user_data.clear()

            await update.message.reply_text(
                "❌ Deposit session শেষ হয়েছে। "
                "আবার চেষ্টা করুন।",
                reply_markup=main_keyboard(
                    user.id
                ),
            )

            return

        duplicate = db_execute(
            """
            SELECT id
            FROM deposits
            WHERE transaction_id = ?
            AND status IN (
                'pending',
                'approved'
            )
            """,
            (text,),
            fetchone=True,
        )

        if duplicate:

            await update.message.reply_text(
                "❌ এই Transaction ID "
                "আগে ব্যবহার করা হয়েছে।"
            )

            return

        db_execute(
            """
            INSERT INTO deposits
            (
                user_id,
                package_id,
                method,
                amount,
                transaction_id,
                status,
                created_at
            )
            VALUES (
                ?, ?, ?, ?, ?, 'pending', ?
            )
            """,
            (
                user.id,
                package_id,
                method,
                amount,
                text,
                now_iso(),
            ),
            commit=True,
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ <b>Deposit Request গ্রহণ করা হয়েছে।</b>\n\n"
            "⏳ দয়া করে <b>৫–১০ মিনিট</b> অপেক্ষা করুন।\n"
            "Admin Transaction চেক করে সঠিক হলে "
            "আপনার Deposit + Bonus Balance-এ যোগ করে দেবেন।",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(
                user.id
            ),
        )

        try:

            await context.bot.send_message(
                ADMIN_ID,
                "🔔 <b>New Deposit Request</b>\n\n"
                f"👤 User: <code>{user.id}</code>\n"
                f"📦 Package: {package_id}\n"
                f"💳 Method: {method}\n"
                f"💰 Amount: ৳{amount:.2f}\n"
                f"🧾 TXID: <code>{text}</code>",
                parse_mode=ParseMode.HTML,
            )

        except Exception as exc:

            logger.warning(
                "Admin deposit notification failed: %s",
                exc,
            )

        return

    # =====================
    # WITHDRAW NUMBER
    # =====================

    if state == "withdraw_number":

        method = context.user_data.get(
            "withdraw_method"
        )

        if not method:

            context.user_data.clear()

            await update.message.reply_text(
                "❌ Withdraw session শেষ হয়েছে।",
                reply_markup=main_keyboard(
                    user.id
                ),
            )

            return

        if (
            not text.isdigit()
            or len(text) < 10
        ):

            await update.message.reply_text(
                "❌ সঠিক bKash/Nagad Number দিন।"
            )

            return

        context.user_data[
            "withdraw_number"
        ] = text

        context.user_data[
            "state"
        ] = "withdraw_amount"

        await update.message.reply_text(
            f"💰 কত টাকা Withdraw করবেন?\n"
            f"সর্বনিম্ন: ৳{MIN_WITHDRAW}"
        )

        return

    # =====================
    # WITHDRAW AMOUNT
    # =====================

    if state == "withdraw_amount":

        try:

            amount = float(
                text.replace(",", "")
            )

        except ValueError:

            await update.message.reply_text(
                "❌ সঠিক Amount লিখুন।"
            )

            return

        if amount < MIN_WITHDRAW:

            await update.message.reply_text(
                f"❌ সর্বনিম্ন Withdraw "
                f"৳{MIN_WITHDRAW}।"
            )

            return

        balance = get_balance(
            user.id
        )

        if amount > balance:

            await update.message.reply_text(
                f"❌ আপনার Balance "
                f"৳{balance:.2f}। "
                "এর বেশি Withdraw করা যাবে না।"
            )

            return

        method = context.user_data.get(
            "withdraw_method"
        )

        number = context.user_data.get(
            "withdraw_number"
        )

        # Balance reserve
        change_balance(
            user.id,
            -amount,
        )

        db_execute(
            """
            INSERT INTO withdrawals
            (
                user_id,
                method,
                number,
                amount,
                status,
                created_at
            )
            VALUES (
                ?, ?, ?, ?, 'pending', ?
            )
            """,
            (
                user.id,
                method,
                number,
                amount,
                now_iso(),
            ),
            commit=True,
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ <b>Withdraw Request গ্রহণ করা হয়েছে।</b>\n\n"
            f"💳 Method: {method}\n"
            f"📱 Number: <code>{number}</code>\n"
            f"💰 Amount: ৳{amount:.2f}\n\n"
            "⏳ আপনার Request Pending আছে।\n"
            "দয়া করে সর্বোচ্চ <b>১০ মিনিট</b> অপেক্ষা করুন।",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(
                user.id
            ),
        )

        try:

            await context.bot.send_message(
                ADMIN_ID,
                "🔔 <b>New Withdrawal Request</b>\n\n"
                f"👤 User: <code>{user.id}</code>\n"
                f"💳 Method: {method}\n"
                f"📱 Number: <code>{number}</code>\n"
                f"💰 Amount: ৳{amount:.2f}",
                parse_mode=ParseMode.HTML,
            )

        except Exception as exc:

            logger.warning(
                "Admin withdrawal notification failed: %s",
                exc,
            )

        return

    # =====================
    # ADMIN ADD BALANCE
    # =====================

    if (
        user.id == ADMIN_ID
        and state == "admin_add"
    ):

        parts = text.split()

        if len(parts) != 2:

            await update.message.reply_text(
                "Format:\n"
                "USER_ID AMOUNT\n\n"
                "উদাহরণ:\n"
                "123456789 500"
            )

            return

        try:

            target = int(
                parts[0]
            )

            amount = float(
                parts[1]
            )

        except ValueError:

            await update.message.reply_text(
                "❌ সঠিক format দিন।"
            )

            return

        if amount <= 0:

            await update.message.reply_text(
                "❌ Amount 0-এর বেশি হতে হবে।"
            )

            return

        if not get_user(target):

            await update.message.reply_text(
                "❌ User পাওয়া যায়নি।"
            )

            return

        change_balance(
            target,
            amount,
        )

        context.user_data.clear()

        await update.message.reply_text(
            f"✅ Balance Add হয়েছে।\n\n"
            f"User: {target}\n"
            f"Amount: ৳{amount:.2f}",
            reply_markup=main_keyboard(
                user.id
            ),
        )

        try:

            await context.bot.send_message(
                target,
                f"💰 Admin আপনার Balance-এ "
                f"৳{amount:.2f} যোগ করেছেন।\n"
                f"Current Balance: "
                f"৳{get_balance(target):.2f}",
            )

        except Exception:
            pass

        return

    # =====================
    # ADMIN BROADCAST
    # =====================

    if (
        user.id == ADMIN_ID
        and state == "admin_broadcast"
    ):

        rows = db_execute(
            "SELECT user_id FROM users",
            fetchall=True,
        )

        sent = 0
        failed = 0

        for row in rows:

            try:

                await context.bot.send_message(
                    row["user_id"],
                    "📢 <b>Admin Notice</b>\n\n"
                    + text,
                    parse_mode=ParseMode.HTML,
                )

                sent += 1

            except Exception:

                failed += 1

        context.user_data.clear()

        await update.message.reply_text(
            f"✅ Broadcast সম্পন্ন।\n\n"
            f"📨 Sent: {sent}\n"
            f"⚠️ Failed: {failed}",
            reply_markup=main_keyboard(
                user.id
            ),
        )

        return

    await update.message.reply_text(
        "নিচের মেনু থেকে একটি অপশন নির্বাচন করুন।",
        reply_markup=main_keyboard(
            user.id
        ),
    )


# =========================
# ERROR HANDLER
# =========================

async def error_handler(
    update,
    context,
):

    logger.exception(
        "Unhandled error:",
        exc_info=context.error,
    )


# =========================
# SET TELEGRAM MENU
# =========================

async def post_init(
    application,
):

    await application.bot.set_my_commands(
        [
            (
                "start",
                "Start the bot",
            )
        ]
    )


# =========================
# MAIN
# =========================

def main():
    init_db()

    # Render-এ ২৪/৭ সচল রাখার জন্য Flask ওয়েব সার্ভার চালু করা হচ্ছে
    threading.Thread(target=run_web_server, daemon=True).start()

    if (
        BOT_TOKEN
        == "PUT_YOUR_NEW_BOT_TOKEN_HERE"
    ):

        raise RuntimeError(
            "BOT_TOKEN বসানো হয়নি। "
            "কোডের BOT_TOKEN লাইনে "
            "নতুন Bot Token দিন।"
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            text_handler,
        )
    )

    app.add_error_handler(
        error_handler
    )

    print(
        "Bot and Web Server are running..."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
