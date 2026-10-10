import asyncio, html, os, random, sqlite3, time, uuid, logging, json
from datetime import datetime, timezone, timedelta
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import (Message, CallbackQuery, LabeledPrice, PreCheckoutQuery, BotCommand, FSInputFile,
                           BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats)
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ⚠️ TOKEN KODGA YOZILMAYDI. Terminalda:  export BOT_TOKEN="123:ABC..."   yoki  token.txt fayliga yozing.
TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not TOKEN and os.path.exists("token.txt"):
    TOKEN = open("token.txt", encoding="utf-8").read().strip()
if not TOKEN:
    raise SystemExit("❌ BOT_TOKEN topilmadi: export BOT_TOKEN=\"123:ABC...\"  yoki token.txt fayliga yozing.")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_ID", "8495751297").split(",") if x.strip().isdigit()}
WEB_URL = os.getenv("WEB_URL", "http://127.0.0.1:8000").rstrip("/")   # ochiq https manzil (ngrok/cloudflared/domen)
WEB_PORT = int(os.getenv("PORT", "8000"))
NEWS = "https://t.me/NightMafiaNews"
NEWS_USER = "NightMafiaNews"
CARD_USER = "https://t.me/yldwv_fx"
SUF = "nightmafiauzbot"            # /gamenightmafiauzbot kabi qo'shimcha buyruqlar uchun
REG_SEC, NIGHT_SEC, DAY_SEC, VOTE_SEC, CONF_SEC, MINP, MINVS = 1800, 45, 40, 30, 20, 4, 2
CH_MAX = 50                        # /change max ishtirokchi
AMAX = 10                          # max faol rollar soni
TZ = timezone(timedelta(hours=5))

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
r = Router()
dp.include_router(r)
esc = html.escape
BOTNAME = ""
BG_TASKS = []


def dfmt(ts): return datetime.fromtimestamp(ts, TZ).strftime("%d.%m.%Y %H:%M")


def n_(x): return f"{int(x):,}"     # 999,997,650 — Telegram telefon raqam deb ko'k qilib yubormasligi uchun


# ───────────────────────── DB ─────────────────────────
db = sqlite3.connect("mafia", check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, lang TEXT DEFAULT 'uz',
 web TEXT, money INT DEFAULT 0, diamonds INT DEFAULT 0, ncoin INT DEFAULT 0, himoya INT DEFAULT 0,
 hujjat INT DEFAULT 0, osish INT DEFAULT 0, geroyd INT DEFAULT 0, wins INT DEFAULT 0, games INT DEFAULT 0,
 arole TEXT DEFAULT '', vip INT DEFAULT 0, vip_until INT DEFAULT 0, t_h INT DEFAULT 1, t_d INT DEFAULT 1,
 t_o INT DEFAULT 1, t_g INT DEFAULT 1, blocked INT DEFAULT 0, pair INT DEFAULT 0, has_hero INT DEFAULT 0,
 hname TEXT DEFAULT '', points INT DEFAULT 0, hprot INT DEFAULT 0, charge INT DEFAULT 0, boosts INT DEFAULT 0)""")
db.execute("""CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY, bal INT DEFAULT 0, sub_until INT DEFAULT 0,
 notified INT DEFAULT 1, mode TEXT DEFAULT 'night', off TEXT DEFAULT '')""")
db.execute("CREATE TABLE IF NOT EXISTS pts_log(uid INT, ball INT, ts INT)")
db.execute("CREATE INDEX IF NOT EXISTS i_pts ON pts_log(ts)")
db.execute("CREATE TABLE IF NOT EXISTS pairs(a INT, b INT, PRIMARY KEY(a,b))")
db.execute("""CREATE TABLE IF NOT EXISTS heroes(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INT, name TEXT DEFAULT '',
 points INT DEFAULT 0, hprot INT DEFAULT 0, charge INT DEFAULT 10)""")
db.execute("CREATE TABLE IF NOT EXISTS tx(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INT, src INT, dst INT, kind TEXT, amount INT)")
db.execute("CREATE TABLE IF NOT EXISTS bans(id INTEGER PRIMARY KEY, snap TEXT)")


def addcol(tbl, col, ddl):
    if col not in [x["name"] for x in db.execute(f"PRAGMA table_info({tbl})")]:
        db.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {ddl}")


addcol("users", "boosts", "INT DEFAULT 0")
addcol("groups", "sub_until", "INT DEFAULT 0")
addcol("groups", "notified", "INT DEFAULT 1")
addcol("groups", "mode", "TEXT DEFAULT 'night'")
addcol("groups", "off", "TEXT DEFAULT ''")
for _x in db.execute("SELECT id,pair FROM users WHERE pair>0").fetchall():      # eski para ma'lumotlarini ko'chirish
    _a, _b = sorted((_x["id"], _x["pair"]))
    db.execute("INSERT OR IGNORE INTO pairs(a,b) VALUES(?,?)", (_a, _b))
    db.execute("UPDATE users SET pair=0 WHERE id=?", (_x["id"],))
db.commit()
COLS = ["money", "diamonds", "ncoin", "himoya", "hujjat", "osish", "geroyd", "wins", "games", "arole", "vip",
        "vip_until", "has_hero", "hname", "points", "hprot", "charge", "boosts"]


def U(uid, name=None):
    row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        db.execute("INSERT INTO users(id,name,web) VALUES(?,?,?)", (uid, name or str(uid), uuid.uuid4().hex))
        db.commit()
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    elif name and row["name"] != name:
        db.execute("UPDATE users SET name=? WHERE id=?", (name, uid)); db.commit()
        row = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return row


def S(uid, **kw):
    U(uid)
    db.execute(f"UPDATE users SET {','.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), uid)); db.commit()


def A(uid, f, n):
    U(uid)
    db.execute(f"UPDATE users SET {f}={f}+? WHERE id=?", (n, uid)); db.commit()


def is_admin(uid): return uid in ADMIN_IDS


def vlevel(u): return u["vip"] if u["vip_until"] > time.time() else 0


def txlog(src, dst, kind, amount):
    db.execute("INSERT INTO tx(ts,src,dst,kind,amount) VALUES(?,?,?,?,?)", (int(time.time()), src, dst, kind, amount)); db.commit()


# ---- guruh sozlamalari / obuna ----
def Gr(chat):
    db.execute("INSERT OR IGNORE INTO groups(id) VALUES(?)", (chat,)); db.commit()
    return db.execute("SELECT * FROM groups WHERE id=?", (chat,)).fetchone()


def gset(chat, **kw):
    Gr(chat)
    db.execute(f"UPDATE groups SET {','.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), chat)); db.commit()


def goff(chat): return {x for x in Gr(chat)["off"].split(",") if x}


def sub_active(chat): return Gr(chat)["sub_until"] > time.time()


def sub_add(chat, days):
    g = Gr(chat); new = int(max(g["sub_until"], time.time()) + days * 86400)
    db.execute("UPDATE groups SET sub_until=?, notified=0 WHERE id=?", (new, chat)); db.commit()
    return new


def sub_link(chat): return f"https://t.me/{BOTNAME}?start=sub{abs(chat)}"


# ---- para / geroy ----
PLIM = {0: 1, 1: 1, 2: 2, 3: 4, 4: 6}
HLIM = {0: 1, 1: 1, 2: 2, 3: 4, 4: 6}


def pairs_of(uid):
    return [x["b"] if x["a"] == uid else x["a"] for x in db.execute("SELECT a,b FROM pairs WHERE a=? OR b=?", (uid, uid))]


def padd(a, b):
    a, b = sorted((a, b)); db.execute("INSERT OR IGNORE INTO pairs(a,b) VALUES(?,?)", (a, b)); db.commit()


def pdel(a, b):
    a, b = sorted((a, b)); db.execute("DELETE FROM pairs WHERE a=? AND b=?", (a, b)); db.commit()


def plim(uid): return PLIM[vlevel(U(uid))]


def hlim(uid): return HLIM[vlevel(U(uid))]


def hcount(uid):
    return (1 if U(uid)["has_hero"] else 0) + db.execute("SELECT COUNT(*) c FROM heroes WHERE uid=?", (uid,)).fetchone()["c"]


def add_hero(uid, name="", points=None, hprot=0, charge=10):
    if not U(uid)["has_hero"]:
        kw = dict(has_hero=1, hname=name, hprot=hprot, charge=charge)
        if points is not None: kw["points"] = points
        S(uid, **kw)
    else:
        db.execute("INSERT INTO heroes(uid,name,points,hprot,charge) VALUES(?,?,?,?,?)", (uid, name, points or 0, hprot, charge)); db.commit()


def hero_remove_active(uid):
    row = db.execute("SELECT * FROM heroes WHERE uid=? ORDER BY id LIMIT 1", (uid,)).fetchone()
    if row:
        S(uid, has_hero=1, hname=row["name"], points=row["points"], hprot=row["hprot"], charge=row["charge"])
        db.execute("DELETE FROM heroes WHERE id=?", (row["id"],)); db.commit()
    else:
        S(uid, has_hero=0, hname="", points=0, hprot=0, charge=0)


def hero_swap(uid, hid):
    u = U(uid); row = db.execute("SELECT * FROM heroes WHERE id=? AND uid=?", (hid, uid)).fetchone()
    if not row: return
    cur = (u["hname"], u["points"], u["hprot"], u["charge"])
    S(uid, hname=row["name"], points=row["points"], hprot=row["hprot"], charge=row["charge"], has_hero=1)
    db.execute("UPDATE heroes SET name=?,points=?,hprot=?,charge=? WHERE id=?", (*cur, hid)); db.commit()


def aroles(u): return [x for x in (u["arole"] or "").split(",") if x]


VIPS = {1: ("➕ VIP Plus", 30), 2: ("🌟 VIP Pro", 60), 3: ("👨‍🍳 VIP Ultra", 90), 4: ("👑 VIP Ultra Promax", 150)}


def vemoji(uid):
    lv = vlevel(U(uid)); return VIPS[lv][0].split()[0] + " " if lv else ""


# ───────────────────────── Tillar (uz / ru / en) ─────────────────────────
LANGS = ("uz", "ru", "en"); IDX = {"uz": 0, "ru": 1, "en": 2}
GAP = "\n\u2800\n\u2800\n\u2800\n"
LT = {
    "start": ("Salom\nMen mafiya botiman. Doʻstlar bilan mafiya oʻynash uchun meni guruhingizga qoʻshing va 30 kishilik o'yindan zavqlaning" + GAP +
              "Meni admin qilib qoʻyganingizdan soʻng, oʻyinni boshlashingiz mumkin..",
              "Привет\nЯ бот для игры в мафию. Добавьте меня в свою группу, чтобы играть с друзьями — до 30 игроков!" + GAP +
              "Когда вы сделаете меня администратором, можно начинать игру..",
              "Hello\nI'm a mafia bot. Add me to your group to play mafia with friends and enjoy games of up to 30 players!" + GAP +
              "Once you make me an admin, you can start the game.."),
    "btn_GAP": ("Guruhga qo‘shish", "Добавить в группу", "Add to group"),
    "btn_news": ("Yangiliklar", "Новости", "News"),
    "btn_lang": ("Til / Язык", "Til / Язык", "Til / Язык"),
    "btn_ask": ("Savollar uchun", "Вопросы", "Questions"),
    "langtitle": ("🌐 Shaxsiy chat tili", "🌐 Язык личного чата", "🌐 Personal chat language"),
    "roles_hdr": ("Rollar ro'yxati:", "Список ролей:", "Roles list:"),
    "back": ("⬅️ Orqaga", "⬅️ Назад", "⬅️ Back"),
    "none": ("Yo'q", "Нет", "None"),
    "prof": ("👤 {name}{vip}\n\n💶 Dollar: {money}\n💎 Olmos: {dia}\n💠 NightCoin: {nc}\n\n🛡 Himoya: {h}\n📁 Hujjat: {d}\n⚖️ Osishdan himoya: {o}\n🔰 Geroydan himoya: {g}\n\n🎯 G'alaba: {w}\n🎲 Barcha o'yinlar: {gm}\n\n🃏 Faol rollar:{ar}",
             "👤 {name}{vip}\n\n💶 Доллары: {money}\n💎 Алмазы: {dia}\n💠 NightCoin: {nc}\n\n🛡 Защита: {h}\n📁 Документ: {d}\n⚖️ Защита от повешения: {o}\n🔰 Защита от героя: {g}\n\n🎯 Победы: {w}\n🎲 Всего игр: {gm}\n\n🃏 Активные роли:{ar}",
             "👤 {name}{vip}\n\n💶 Dollars: {money}\n💎 Diamonds: {dia}\n💠 NightCoin: {nc}\n\n🛡 Shield: {h}\n📁 Document: {d}\n⚖️ Hanging protection: {o}\n🔰 Hero protection: {g}\n\n🎯 Wins: {w}\n🎲 Total games: {gm}\n\n🃏 Active roles:{ar}"),
    "p_shop": ("Do'kon", "Магазин", "Shop"),
    "p_buyd": ("Xarid qilish 💎", "Купить 💎", "Buy 💎"),
    "p_buym": ("Xarid qilish 💵", "Купить 💵", "Buy 💵"),
    "p_hero": ("🥷 Mening geroyim", "🥷 Мой герой", "🥷 My hero"),
    "p_tr": ("🔄 Profil almashish", "🔄 Перенос профиля", "🔄 Switch profile"),
    "p_web": ("🌐 Web profil", "🌐 Веб-профиль", "🌐 Web profile"),
    "shop_title": ("🛒 <b>Do'kon</b>", "🛒 <b>Магазин</b>", "🛒 <b>Shop</b>"),
    "price": ("Narxi", "Цена", "Price"),
    "sh_hero": ("🥷 Geroy — 90 💎", "🥷 Герой — 90 💎", "🥷 Hero — 90 💎"),
    "sh_hero_s": ("🥷 Geroy — 300 ⭐️", "🥷 Герой — 300 ⭐️", "🥷 Hero — 300 ⭐️"),
    "sh_vip": ("⭐️ VIP", "⭐️ VIP", "⭐️ VIP"),
    "sh_ar": ("🎭 Faol rol", "🎭 Активная роль", "🎭 Active role"),
    "it_himoya": ("🛡 Himoya", "🛡 Защита", "🛡 Shield"),
    "itd_himoya": ("Bir marta hayotingizni saqlab qoladi.", "Один раз спасёт вам жизнь.", "Saves your life once."),
    "it_hujjat": ("📁 Hujjat", "📁 Документ", "📁 Document"),
    "itd_hujjat": ("Kimdir rolingizni tekshirsa, soxta hujjat yordam beradi.", "Если проверят вашу роль, поддельный документ поможет.", "A fake document helps if someone checks your role."),
    "it_osish": ("⚖️ Ovozdan himoya", "⚖️ Защита от повешения", "⚖️ Vote protection"),
    "itd_osish": ("Osishga hukm qilishsa, bir marta qutqaradi.", "Спасёт один раз, если приговорят к повешению.", "Saves you once if you're sentenced to hang."),
    "it_geroyd": ("🔰 Geroydan himoya", "🔰 Защита от героя", "🔰 Hero protection"),
    "itd_geroyd": ("Geroydan bo'lgan hujumdan omon qolish.", "Позволяет пережить атаку героя.", "Survive a hero attack."),
    "it_ncoin": ("💠 NightCoin", "💠 NightCoin", "💠 NightCoin"),
    "itd_ncoin": ("Tez orada ishga tushadigan marketdagi valyuta.", "Валюта будущего маркета.", "Currency of the upcoming market."),
    "no_dia": ("Olmos yetarli emas!", "Недостаточно алмазов!", "Not enough diamonds!"),
    "no_money": ("Pul yetarli emas!", "Недостаточно денег!", "Not enough money!"),
    "no_bal": ("Balans yetarli emas!", "Недостаточный баланс!", "Insufficient balance!"),
    "bought": ("✅ {n} sotib olindi!", "✅ {n} куплено!", "✅ {n} purchased!"),
    "hero_full": ("Geroy sloti to'lgan! (limit: {n}). VIP orqali limitni oshiring.", "Слоты героев заполнены! (лимит: {n}). Повысьте лимит через VIP.", "Hero slots are full! (limit: {n}). Raise it with VIP."),
    "hero_bought": ("🥷 Geroy sotib olindi! «Mening geroyim» bo'limiga o'ting.", "🥷 Герой куплен! Откройте раздел «Мой герой».", "🥷 Hero purchased! Open the “My hero” section."),
    "hero_none": ("Sizda geroy yo'q. Do'kondan sotib oling.", "У вас нет героя. Купите его в магазине.", "You have no hero. Buy one in the shop."),
    "hb_buy_d": ("🥷 Geroy sotib olish — 90 💎", "🥷 Купить героя — 90 💎", "🥷 Buy hero — 90 💎"),
    "hb_buy_s": ("🥷 Geroy — 300 ⭐️", "🥷 Герой — 300 ⭐️", "🥷 Hero — 300 ⭐️"),
    "hero_fmt": ("🥷 Geroy: {name}\n\n⭐️ Daraja: {L}\n👊 Kuch: {pow}\n🖤 Himoya: {hp}\n♥️ Max himoya: {mh}\n🩸 Zaryad miqdori: {ch}\n☑️ Jami ballari: {pts} ball\n🔰 Geroydan himoya: {gd}{nxt}",
                 "🥷 Герой: {name}\n\n⭐️ Уровень: {L}\n👊 Сила: {pow}\n🖤 Защита: {hp}\n♥️ Макс. защита: {mh}\n🩸 Заряд: {ch}\n☑️ Всего очков: {pts}\n🔰 Защита от героя: {gd}{nxt}",
                 "🥷 Hero: {name}\n\n⭐️ Level: {L}\n👊 Power: {pow}\n🖤 Protection: {hp}\n♥️ Max protection: {mh}\n🩸 Charge: {ch}\n☑️ Total points: {pts}\n🔰 Hero protection: {gd}{nxt}"),
    "hero_shop": ("🛒 Xaridlar uchun:\n➕ 1000 Ball qo'shish = 💎 50\n🛡 Himoyani yangilash = 💶 300\n🩸 Qurolni zaryadlash = 💶 200\n🖋 Geroy nomini o'zgertirish 💶 800",
                  "🛒 Покупки:\n➕ 1000 очков = 💎 50\n🛡 Обновить защиту = 💶 300\n🩸 Зарядить оружие = 💶 200\n🖋 Сменить имя героя = 💶 800",
                  "🛒 Purchases:\n➕ 1000 points = 💎 50\n🛡 Renew protection = 💶 300\n🩸 Recharge weapon = 💶 200\n🖋 Rename hero = 💶 800"),
    "hero_next": ("\n\n⏫ Keyingi daraja = {n} => {p} ball", "\n\n⏫ Следующий уровень = {n} => {p} очков", "\n\n⏫ Next level = {n} => {p} points"),
    "pow_range": ("{a}-{b} oralig'ida", "в пределах {a}-{b}", "between {a}-{b}"),
    "pow_max": ("maksimal uradi", "максимальный урон", "maximum damage"),
    "noname": ("nomsiz", "без имени", "unnamed"),
    "hb_ball": ("➕ 1000 Ball", "➕ 1000 очков", "➕ 1000 Points"),
    "hb_prot": ("🛡 Himoyani yangilash", "🛡 Обновить защиту", "🛡 Renew protection"),
    "hb_charge": ("🩸 Qurolni o'qlash", "🩸 Зарядить оружие", "🩸 Recharge weapon"),
    "hb_name": ("🖋 Geroy nomini o'zgertirish", "🖋 Сменить имя героя", "🖋 Rename hero"),
    "hb_lvls": ("⭐️ Darajalar haqida", "⭐️ Об уровнях", "⭐️ About levels"),
    "hb_status": ("🎭 Status", "🎭 Статус", "🎭 Status"),
    "hb_list": ("🔁 Geroylarim ({n}/{lim})", "🔁 Мои герои ({n}/{lim})", "🔁 My heroes ({n}/{lim})"),
    "h_ball_ok": ("1000 bal qo'shildi!", "Добавлено 1000 очков!", "1000 points added!"),
    "h_prot_ok": ("Himoya yangilandi!", "Защита обновлена!", "Protection renewed!"),
    "h_charge_ok": ("Qurol o'qlandi! (max 10 marta)", "Оружие заряжено! (макс. 10)", "Weapon recharged! (max 10)"),
    "h_name_ask": ("🖋 Geroyingiz uchun yangi nom yuboring:", "🖋 Отправьте новое имя для героя:", "🖋 Send a new name for your hero:"),
    "h_status_ask": ("🎭 Status uchun premium emoji/matn yuboring:", "🎭 Отправьте премиум-эмодзи/текст для статуса:", "🎭 Send a premium emoji/text for your status:"),
    "h_no800": ("Pul yetarli emas (800 💶)", "Недостаточно денег (800 💶)", "Not enough money (800 💶)"),
    "h_name_ok": ("✅ Geroy nomi o'zgardi.", "✅ Имя героя изменено.", "✅ Hero name changed."),
    "h_status_ok": ("✅ Status o'rnatildi.", "✅ Статус установлен.", "✅ Status set."),
    "h_list": ("🥷 Geroylaringiz ({n}/{lim}). Faol qilish uchun tanlang:", "🥷 Ваши герои ({n}/{lim}). Выберите активного:", "🥷 Your heroes ({n}/{lim}). Pick the active one:"),
    "lvl_fmt": ("⭐️ {i}-daraja:\n☑️ O'tish balli: {pts} ball\n👊 Kuch: {pow}\n♥️ Max Himoya: {mh}.0",
                "⭐️ Уровень {i}:\n☑️ Нужно очков: {pts}\n👊 Сила: {pow}\n♥️ Макс. защита: {mh}.0",
                "⭐️ Level {i}:\n☑️ Points needed: {pts}\n👊 Power: {pow}\n♥️ Max protection: {mh}.0"),
    "lvl_yours": ("Sizning darajangiz: {n}-daraja", "Ваш уровень: {n}", "Your level: {n}"),
    "vip_txt": ("⭐️ <b>VIP Obunalar</b>\n\n➕ VIP Plus — 30 💎 / 30 kun\n• Komissiyasiz o'tkazmalar\n• VIP status emoji\n• Kechqurun yoza olish\n• 1 para, 1 geroy\n\n🌟 VIP Pro — 60 💎 / 30 kun\n• Plus imkoniyatlari\n• 2× guruh limitlari\n• 2 para, 2 geroy\n\n👨‍🍳 VIP Ultra — 90 💎 / 30 kun\n• Pro imkoniyatlari\n• 4× guruh limitlari\n• 4 para, 4 geroy\n• /boost — guruhga 1 oylik premium obuna\n\n👑 VIP Ultra Promax — 150 💎 / 30 kun\n• Ultra imkoniyatlari\n• 6× guruh limitlari\n• 6 para, 6 geroy\n• /boost — guruhga 2 oylik premium obuna\n• Guruh obunasi arzon: 5 💎 / oy, 60 💎 / yil\n• Web profil: paralar, rollar va o'tkazmalar",
                "⭐️ <b>VIP-подписки</b>\n\n➕ VIP Plus — 30 💎 / 30 дней\n• Переводы без комиссии\n• VIP-эмодзи\n• Писать ночью\n• 1 пара, 1 герой\n\n🌟 VIP Pro — 60 💎 / 30 дней\n• Всё из Plus\n• 2× лимиты группы\n• 2 пары, 2 героя\n\n👨‍🍳 VIP Ultra — 90 💎 / 30 дней\n• Всё из Pro\n• 4× лимиты группы\n• 4 пары, 4 героя\n• /boost — 1 месяц премиум-подписки для группы\n\n👑 VIP Ultra Promax — 150 💎 / 30 дней\n• Всё из Ultra\n• 6× лимиты группы\n• 6 пар, 6 героев\n• /boost — 2 месяца подписки для группы\n• Подписка группы дешевле: 5 💎 / мес, 60 💎 / год\n• Веб-профиль: пары, роли и переводы",
                "⭐️ <b>VIP Subscriptions</b>\n\n➕ VIP Plus — 30 💎 / 30 days\n• Commission-free transfers\n• VIP status emoji\n• Write at night\n• 1 pair, 1 hero\n\n🌟 VIP Pro — 60 💎 / 30 days\n• Plus perks\n• 2× group limits\n• 2 pairs, 2 heroes\n\n👨‍🍳 VIP Ultra — 90 💎 / 30 days\n• Pro perks\n• 4× group limits\n• 4 pairs, 4 heroes\n• /boost — 1 month premium for a group\n\n👑 VIP Ultra Promax — 150 💎 / 30 days\n• Ultra perks\n• 6× group limits\n• 6 pairs, 6 heroes\n• /boost — 2 months for a group\n• Cheaper group plan: 5 💎 / month, 60 💎 / year\n• Web profile: pairs, roles and transfers"),
    "vip_bought": ("✅ {n} sotib olindi (30 kun)!", "✅ {n} куплен (30 дней)!", "✅ {n} purchased (30 days)!"),
    "buyd_title": ("💎 Olmos xarid qilish usulini tanlang:", "💎 Выберите способ покупки алмазов:", "💎 Choose how to buy diamonds:"),
    "buyd_stars": ("⭐️ Stars orqali", "⭐️ Через Stars", "⭐️ With Stars"),
    "buyd_card": ("💳 Karta orqali", "💳 Картой", "💳 By card"),
    "stars_title": ("💎 Qancha olmos olmoqchisiz?\n\n⭐️ Star orqali olmos xarid qiling!", "💎 Сколько алмазов хотите?\n\n⭐️ Покупайте алмазы за Stars!", "💎 How many diamonds do you want?\n\n⭐️ Buy diamonds with Stars!"),
    "buym_title": ("💵 Dollar xarid qilish (olmosga):", "💵 Покупка долларов (за алмазы):", "💵 Buy dollars (with diamonds):"),
    "paid": ("✅ To'lov qabul qilindi! +{d} 💎", "✅ Оплата принята! +{d} 💎", "✅ Payment received! +{d} 💎"),
    "ar_title": ("Sizga aktiv rol kerakmi?\n\nKerak bo'lsa, ro'yxatdan tanlab xarid qiling (maksimal {n} ta).\nO'yin boshlanganda birinchi sotib olingan rol 100% tushadi va faol roldan o'chadi — xohlasangiz qayta sotib olasiz.",
                 "Нужна активная роль?\n\nВыберите из списка и купите (максимум {n}).\nПри старте игры первая купленная роль выпадает на 100% и снимается — можно купить снова.",
                 "Need an active role?\n\nPick one from the list and buy it (max {n}).\nAt game start your first purchased role is assigned 100% and then removed — you can buy it again."),
    "ar_del": ("❌ Faol rollarni o'chirish — 100 💶", "❌ Удалить активные роли — 100 💶", "❌ Remove active roles — 100 💶"),
    "ar_none": ("Sizda faol rol yo'q.", "У вас нет активных ролей.", "You have no active roles."),
    "ar_max": ("Faol rollar limiti to'lgan (max {n}).", "Лимит активных ролей достигнут (макс. {n}).", "Active role limit reached (max {n})."),
    "ar_ok": ("✅ Faol rol sotib olindi: {role}. Keyingi o'yinda shu rol 100% tushadi.", "✅ Активная роль куплена: {role}. В следующей игре она выпадет на 100%.", "✅ Active role purchased: {role}. You'll get it 100% next game."),
    "ar_deleted": ("✅ Faol rollar o'chirildi.", "✅ Активные роли удалены.", "✅ Active roles removed."),
    "sub_txt": ("💎 <b>Guruh obunasi</b>\n\nGuruh: <b><i>{title}</i></b>\n📅 Obuna tugashi: {until}\n💎 Sizning balansingiz: {bal}\n\nTarifni tanlang. To'lov shaxsiy olmos balansingizdan olinadi.\nFaol obuna muddati ustiga yangi muddat qo'shiladi.",
                "💎 <b>Подписка группы</b>\n\nГруппа: <b><i>{title}</i></b>\n📅 Подписка до: {until}\n💎 Ваш баланс: {bal}\n\nВыберите тариф. Оплата списывается с вашего личного баланса алмазов.\nНовый срок добавляется к действующей подписке.",
                "💎 <b>Group subscription</b>\n\nGroup: <b><i>{title}</i></b>\n📅 Expires: {until}\n💎 Your balance: {bal}\n\nChoose a plan. Payment is taken from your personal diamond balance.\nThe new period is added on top of an active subscription."),
    "sub_m": ("1 oy (30 kun)", "1 месяц (30 дней)", "1 month (30 days)"),
    "sub_y": ("1 yil (365 kun)", "1 год (365 дней)", "1 year (365 days)"),
    "sub_none": ("Faol emas", "Не активна", "Inactive"),
    "sub_nodia": ("Olmos yetarli emas. Shaxsiy balansingizni to‘ldiring.", "Недостаточно алмазов. Пополните личный баланс.", "Not enough diamonds. Top up your personal balance."),
    "sub_ok_m": ("✅ Sotib olindi! Bot aktiv holatda (1-oy)", "✅ Куплено! Бот активен (1 месяц)", "✅ Purchased! Bot is active (1 month)"),
    "sub_ok_y": ("✅ Sotib olindi! Bot aktiv holatda: 1 yil (365 kun)", "✅ Куплено! Бот активен: 1 год (365 дней)", "✅ Purchased! Bot is active: 1 year (365 days)"),
    "tr_ask": ("🔄 Profil almashish\n\nO'tkazmoqchi bo'layotgan odamingizni telegram id raqamini yuboring.\nProfilni almashish narxi: 5 💎",
               "🔄 Перенос профиля\n\nОтправьте Telegram ID человека, которому хотите передать профиль.\nСтоимость переноса: 5 💎",
               "🔄 Switch profile\n\nSend the Telegram ID of the person you want to transfer to.\nTransfer cost: 5 💎"),
    "tr_conf": ("❓ Hamma narsa (geroy, pul, olmos va h.k.) shu akkauntga o'tkazilsinmi?\n\n🆔 ID: <code>{id}</code>\n👤 Ism: {name}\n💎 Narxi: 5",
                "❓ Передать всё (героя, деньги, алмазы и т.д.) на этот аккаунт?\n\n🆔 ID: <code>{id}</code>\n👤 Имя: {name}\n💎 Стоимость: 5",
                "❓ Transfer everything (hero, money, diamonds, etc.) to this account?\n\n🆔 ID: <code>{id}</code>\n👤 Name: {name}\n💎 Cost: 5"),
    "tr_yes": ("✅ Ha", "✅ Да", "✅ Yes"), "tr_no": ("❌ Yo'q", "❌ Нет", "❌ No"),
    "tr_done": ("✅ Profil o'tkazildi.", "✅ Профиль передан.", "✅ Profile transferred."),
    "tr_got": ("🔄 Sizga profil o'tkazildi!", "🔄 Вам передан профиль!", "🔄 A profile was transferred to you!"),
    "tr_nostart": ("⚠️ Qabul qiluvchi hali botdan /start bosmagan. U botga /start bosishi kerak, shundan keyin qayta urinib ko'ring.",
                   "⚠️ Получатель ещё не нажал /start в боте. Пусть сделает это и попробуйте снова.",
                   "⚠️ The receiver hasn't pressed /start in the bot yet. Ask them to, then try again."),
    "tr_new": ("Qabul qiluvchi akkaunti yangi (0 o'yin) bo'lishi kerak.", "Аккаунт получателя должен быть новым (0 игр).", "The receiver's account must be new (0 games)."),
    "tr_5": ("5 💎 kerak.", "Нужно 5 💎.", "You need 5 💎."),
    "tr_digits": ("Faqat raqam yuboring.", "Отправьте только цифры.", "Send digits only."),
    "tr_self": ("O'zingizga o'tkaza olmaysiz.", "Нельзя передать самому себе.", "You can't transfer to yourself."),
    "night_pick": ("🌃 Tunda kimni tanlaysiz?", "🌃 Кого выберете этой ночью?", "🌃 Whom do you pick tonight?"),
    "hm_prompt": ("Harakat turini tanlang.", "Выберите действие.", "Choose an action."),
    "hm_attack": ("🥷 Hujum qilish", "🥷 Атаковать", "🥷 Attack"),
    "hm_shield": ("⚜️ Himoyalanish", "⚜️ Защититься", "⚜️ Defend"),
    "hm_skip": ("🚷 O'tkazib yuborish", "🚷 Пропустить", "🚷 Skip"),
    "you_are": ("Siz - {role}!", "Вы — {role}!", "You are {role}!"),
    "mates": ("Sheriklaringizni eslab qoling!", "Запомните своих сообщников!", "Remember your partners!"),
    "set_title": ("⚙️ <b>Sozlamalar</b>\nGuruh: <b>{title}</b>\nRejim: <b>{mode}</b>", "⚙️ <b>Настройки</b>\nГруппа: <b>{title}</b>\nРежим: <b>{mode}</b>", "⚙️ <b>Settings</b>\nGroup: <b>{title}</b>\nMode: <b>{mode}</b>"),
    "set_mode": ("🎮 O'yin rejimi", "🎮 Режим игры", "🎮 Game mode"),
    "set_roles": ("🎭 Rollarni boshqarish", "🎭 Управление ролями", "🎭 Manage roles"),
    "set_sub": ("📅 Guruh obunasi", "📅 Подписка группы", "📅 Group subscription"),
    "set_modes_title": ("🎮 O'yin rejimini tanlang:", "🎮 Выберите режим игры:", "🎮 Choose the game mode:"),
    "set_roles_title": ("🎭 Rollarni yoqish/o'chirish (barcha rejimlarda ishlaydi).\n✅ — yoqilgan, ❌ — o'chirilgan.", "🎭 Включение/выключение ролей (во всех режимах).\n✅ — включена, ❌ — выключена.", "🎭 Enable/disable roles (works in every mode).\n✅ — on, ❌ — off."),
    "set_on_all": ("✅ Hammasini yoqish", "✅ Включить все", "✅ Enable all"),
    "set_off_all": ("🚫 Hammasini o'chirish", "🚫 Выключить все", "🚫 Disable all"),
    "seller_offer": ("🎁 Sotuvchi sizga bugun yarim narxdagi mahsulotlarni taklif qilmoqda:", "🎁 Продавец предлагает вам сегодня товары за полцены:", "🎁 The Seller offers you half-price items today:"),
}


def tt(uid, key, **kw):
    lg = U(uid)["lang"] if uid else "uz"
    s = LT[key][IDX.get(lg, 0)]
    return s.format(**kw) if kw else s


# ───────────────────────── Rollar ─────────────────────────
RL = [
    ("tinch", "🧑🏼", "Tinch axoli", "Sizning vazifangiz mafiani topish va ovoz berish jarayonida ularni osish"),
    ("don", "🤵🏻", "Don", "Bu tunda kim o'lishini siz hal qilasiz. Siz mafialar sardorisiz."),
    ("mafia", "🤵🏼", "Mafia", "Siz Mafiasiz, Donga boysunasiz va sizga qarshilik qilganlarni o'ldirasiz. Don o'lsa yangi Don bo'lishingiz mumkin."),
    ("manyak", "🔪", "Manyak", "Shahardagi hamma o'lishi kerak, sizdan tashqari albatta :)"),
    ("komissar", "🕵🏻‍♂️", "Komissar", "Shaharning asosiy himoyachisi va mafia qushandasi. Tunda tekshirasiz yoki otasiz."),
    ("doktor", "👨🏼‍⚕️", "Doktor", "Tunda kimnidir qutqarib qolishingiz mumkin..."),
    ("serjant", "👮🏻‍♂️", "Serjant", "Komissar katanining yordamchisi. Komissar o'lsa uning o'rnini egallaysiz."),
    ("daydi", "🧙‍♂️", "Daydi", "Xohlagan odamning uyiga ichkilik butilka olish uchun borib, qotilikning guvohi bo'lib qolishingiz mumkin."),
    ("mashuqa", "💃🏻", "Mashuqa", "Mehmonga borgan odamingizga uyqu dori berasiz va u bir kun uxlaydi (harakat qila olmaydi)."),
    ("advokat", "👨🏼‍💼", "Advokat", "Tunda kimni himoya qilishni tanlaysiz. Mafiani tanlasangiz, Komissar uni tinch aholi deb ko'radi. Siz mafia tarafdorisiz."),
    ("suidsid", "🤦🏼", "Suidsid", "Seni osib o'ldirishsa sen yutasan :)"),
    ("ubiytsa", "🥷", "Убийца", "Mafialar tarafda o'ynaysiz! Har tun kimnidir yashirincha ovlaydi, ammo komissarni nishonga olsa, komissar sizni o'ldiradi."),
    ("kamikaze", "💣", "Kamikaze", "Kechasi o'ldirilsangiz, o'ldirgan ham o'ladi. Kunlik ovozda o'ldirilsangiz, bir o'yinchini o'zingiz bilan olib ketasiz."),
    ("aferist", "🤹🏻", "Aferist", "Erkin rol. Kechasi birovga tashrif buyurib, uning ismini aldab qo'yadi. Maqsad — tirik qolish!"),
    ("minior", "☠️", "Minior", "Siz erkinsiz. Tunda tanlagan odamingiz eshigi oldiga mina qo'yasiz."),
    ("donxotin", "👩🏻‍💼", "Donning xotini", "Siz mafialar tarafdasiz. Tunda bir o'yinchining rolini bilib, mafialarga oshkor qilasiz."),
    ("zombi", "🧟‍♂️", "Zombi", "Vazifangiz hammani zombiga aylantirish."),
    ("kimyogar", "👨🏼‍🔬", "Kimyogar", "Siz mafialar tarafdasiz! Mafia a'zosini tanlasangiz himoya qilasiz, boshqalarni o'ldirasiz."),
    ("tentak", "👨🏻‍🦲", "Tentak", "Tunda bir o'yinchini tanlaysiz. Tinch taraf bo'lsa, uni o'sha kuni hech kim osa olmaydi, bo'lmasa o'ldirasiz."),
    ("buqalamun", "🦎", "Buqalamun", "Tun payti bir marta kimnidir tanlab, uning tarafida o'yinni davom ettirasiz."),
    ("sotuvchi", "🎁", "Sotuvchi", "Tunda kimnidir tanlab, ertasi kuni bot mahsulotlarini yarim narxda taklif qilasiz, sotib olsa 10% ishlaysiz."),
    ("muxlis", "🔮", "Muxlis", "Har kuni kimgadir muxlislik qilasiz. Uni o'ldirishsa, qotilga (manyakka) aylanib qasos olasiz."),
    ("omadli", "🤞🏼", "Omadli", "Omadi kulsa, suiqasddan omon qolishi mumkin bo'lgan tinch aholi."),
    ("rais", "💰", "Rais", "Tunda kimnidir tanlab, unga 50-250 dollar sovg'a berasiz."),
    ("sehrgar", "🧙‍♀️", "Sehrgar", "Sizni o'ldirishga urinsa, uni kechirish yoki kechirmaslik tanlovi beriladi."),
    ("mergan", "🎯", "Mergan", "Yakkalar ichida eng kuchlisi. Yakkalar uni o'ldira olmaydi."),
    ("janob", "🎖", "Janob", "Kunduzgi ovozda ovozingiz ikkitaga teng, shaxsingiz oshkor bo'lmaydi."),
    ("qoy", "🐑", "Qo'y", "Ovoz berishda suidsidni osishda qatnashsangiz, rolingiz qo'yga aylanadi."),
    ("jurnalist", "📰", "Jurnalist", "Tunda bir o'yinchini tekshirib, u qaysi tomonda ekanini (tinch / mafia / yakka) bilib olasiz."),
    ("qoriqchi", "💂🏻‍♂️", "Qo'riqchi", "Tunda bir o'yinchini qo'riqlaysiz: unga hujum bo'lsa, uning o'rniga siz o'lasiz."),
    ("hamshira", "👩🏻‍⚕️", "Hamshira", "Doktor o'lsa, uning o'rnini egallab Doktorga aylanasiz."),
    ("ovchi", "🏹", "Ovchi", "Sizni o'ldirishsa yoki osishsa, tasodifiy bitta mafia yoki yakka o'yinchini o'zingiz bilan olib ketasiz."),
]
RD = {k: (e, n, d) for k, e, n, d in RL}
RD["jangchi"] = ("⚔️", "Jangchi", "VS mode: har tun raqib jamoadan bitta o'yinchini nishonga olasiz. Jamoangiz nishonga eng ko'p olingan dushmanni yo'q qiladi.")
RT = {  # (ru nom, en nom, ru tavsif, en tavsif)
    "tinch": ("Мирный житель", "Civilian", "Найдите мафию и казните её на голосовании.", "Find the mafia and hang them in the vote."),
    "don": ("Дон", "Don", "Вы решаете, кто умрёт этой ночью. Вы глава мафии.", "You decide who dies tonight. You are the mafia boss."),
    "mafia": ("Мафия", "Mafia", "Вы подчиняетесь Дону и убиваете неугодных. Если Дон погибнет, можете стать новым Доном.", "You obey the Don and kill anyone in the way. If the Don dies you may become the new Don."),
    "manyak": ("Маньяк", "Maniac", "Все в городе должны умереть, кроме вас :)", "Everyone in town must die, except you :)"),
    "komissar": ("Комиссар", "Commissioner", "Главный защитник города. Ночью проверяете или стреляете.", "The city's main defender. At night you check or shoot."),
    "doktor": ("Доктор", "Doctor", "Ночью вы можете кого-то спасти...", "At night you can save someone..."),
    "serjant": ("Сержант", "Sergeant", "Помощник Комиссара. Если он погибнет — вы займёте его место.", "Commissioner's deputy. If he dies you take his place."),
    "daydi": ("Бродяга", "Tramp", "Ночью идёте к кому-то за бутылкой и можете стать свидетелем убийства.", "At night you visit someone for a bottle and may witness a murder."),
    "mashuqa": ("Любовница", "Mistress", "Усыпляете гостя — он не может действовать этой ночью.", "You put your guest to sleep — they can't act tonight."),
    "advokat": ("Адвокат", "Lawyer", "Выбираете, кого защитить. Комиссар увидит мафиози мирным. Вы на стороне мафии.", "You pick who to defend. The Commissioner sees a mafioso as civilian. You side with the mafia."),
    "suidsid": ("Суицидник", "Suicide", "Если вас повесят — вы побеждаете :)", "If they hang you, you win :)"),
    "ubiytsa": ("Убийца", "Assassin", "Играете за мафию! Каждую ночь тайно охотитесь, но если выберете комиссара — он убьёт вас.", "You play for the mafia! You hunt secretly each night, but if you target the Commissioner he kills you."),
    "kamikaze": ("Камикадзе", "Kamikaze", "Если вас убьют ночью, убийца умрёт тоже. Если повесят — заберёте одного с собой.", "If killed at night, your killer dies too. If hanged, you take one player with you."),
    "aferist": ("Аферист", "Swindler", "Свободная роль. Ночью обманывает проверки. Цель — выжить!", "Free role. At night you fool investigations. Goal — survive!"),
    "minior": ("Минёр", "Miner", "Свободная роль. Ночью ставите мину у двери выбранного игрока.", "Free role. At night you plant a mine at a chosen player's door."),
    "donxotin": ("Жена Дона", "Don's Wife", "На стороне мафии. Ночью узнаёте роль игрока и сообщаете мафии.", "Mafia side. At night you learn a player's role and tell the mafia."),
    "zombi": ("Зомби", "Zombie", "Ваша цель — превратить всех в зомби.", "Your goal is to turn everyone into zombies."),
    "kimyogar": ("Химик", "Chemist", "На стороне мафии! Члена мафии защищаете, остальных убиваете.", "Mafia side! You protect a mafia member and kill everyone else."),
    "tentak": ("Дурак", "Fool", "Ночью выбираете игрока. Если он мирный — днём его не повесят, иначе вы его убьёте.", "At night you pick a player. If peaceful, nobody can hang them that day; otherwise you kill them."),
    "buqalamun": ("Хамелеон", "Chameleon", "Один раз выбираете игрока и переходите на его сторону.", "Once you pick a player and join their side."),
    "sotuvchi": ("Продавец", "Seller", "Выбираете игрока: на следующий день он получит товары бота за полцены, вы заработаете 10%.", "Pick a player: next day they get bot items at half price and you earn 10%."),
    "muxlis": ("Фанат", "Fan", "Выбираете кумира. Если его убьют — вы становитесь маньяком и мстите.", "You pick an idol. If they're killed you become a maniac and take revenge."),
    "omadli": ("Везунчик", "Lucky", "Мирный житель, которому может повезти пережить покушение.", "A civilian who may luckily survive an assassination attempt."),
    "rais": ("Босс", "Boss", "Ночью дарите выбранному игроку 50–250 долларов.", "At night you gift a chosen player $50–250."),
    "sehrgar": ("Волшебник", "Wizard", "Если вас пытаются убить, вам дают выбор — простить или нет.", "If someone tries to kill you, you choose to forgive or not."),
    "mergan": ("Снайпер", "Sniper", "Сильнейший среди одиночек. Одиночки не могут его убить.", "The strongest among solos. Solo killers can't kill you."),
    "janob": ("Господин", "Gentleman", "Ваш голос днём равен двум, личность скрыта.", "Your daytime vote counts double and your identity stays hidden."),
    "qoy": ("Овца", "Sheep", "Если участвуете в повешении суицидника, ваша роль станет овцой.", "If you take part in hanging the suicide, you turn into a sheep."),
    "jurnalist": ("Журналист", "Journalist", "Ночью проверяете игрока и узнаёте, на чьей он стороне.", "At night you check a player and learn which side they're on."),
    "qoriqchi": ("Телохранитель", "Bodyguard", "Ночью охраняете игрока: если на него нападут, вы умрёте вместо него.", "At night you guard a player: if attacked, you die in their place."),
    "hamshira": ("Медсестра", "Nurse", "Если Доктор погибнет, вы займёте его место.", "If the Doctor dies, you take his place."),
    "ovchi": ("Охотник", "Hunter", "Если вас убьют или повесят, вы заберёте с собой случайного мафиози или одиночку.", "If you're killed or hanged, you take a random mafioso or solo player with you."),
    "jangchi": ("Боец", "Fighter", "VS режим: каждую ночь целитесь в игрока команды соперников.", "VS mode: each night you target a player of the enemy team."),
}


def rname(k, uid=None):
    e, n, d = RD[k]
    if uid and k in RT:
        lg = U(uid)["lang"]
        if lg in ("ru", "en"): n = RT[k][0 if lg == "ru" else 1]
    return f"{e} {n}"


def rdesc(k, uid=None):
    d = RD[k][2]
    if uid and k in RT:
        lg = U(uid)["lang"]
        if lg in ("ru", "en"): d = RT[k][2 if lg == "ru" else 3]
    return d


MAF = {"don", "mafia", "advokat", "ubiytsa", "donxotin", "kimyogar"}
SOLO = {"manyak", "suidsid", "aferist", "minior", "zombi"}
# Faol rol narxlari: ("d" = 💎, "m" = 💶)
ARP = {"ubiytsa": ("d", 5), "mergan": ("d", 2), "minior": ("d", 1), "suidsid": ("d", 5), "komissar": ("d", 3),
       "don": ("d", 2), "manyak": ("d", 2), "kimyogar": ("d", 3), "tentak": ("d", 1), "mafia": ("d", 1),
       "serjant": ("d", 1), "aferist": ("d", 2), "buqalamun": ("d", 1), "muxlis": ("d", 1), "sehrgar": ("d", 1), "ovchi": ("d", 2),
       "doktor": ("m", 600), "rais": ("m", 500), "mashuqa": ("m", 500), "advokat": ("m", 300),
       "kamikaze": ("m", 700), "daydi": ("m", 500), "donxotin": ("m", 500), "tinch": ("m", 200),
       "sotuvchi": ("m", 400), "omadli": ("m", 300), "janob": ("m", 600), "jurnalist": ("m", 500),
       "qoriqchi": ("m", 500), "hamshira": ("m", 400)}
ACT = {"don": [("k", "🔪")], "mafia": [("k", "🔪")], "ubiytsa": [("k", "🥷")], "manyak": [("k", "🔪")],
       "komissar": [("c", "🔍"), ("s", "🔫")], "doktor": [("h", "💉")], "mashuqa": [("b", "💃")], "advokat": [("a", "⚖️")],
       "daydi": [("d", "🍾")], "aferist": [("x", "🤹")], "minior": [("m", "💣")], "donxotin": [("w", "👁")],
       "kimyogar": [("e", "⚗️")], "tentak": [("t", "🎲")], "buqalamun": [("y", "🦎")], "sotuvchi": [("v", "🎁")],
       "muxlis": [("f", "⭐️")], "rais": [("g", "💰")], "zombi": [("z", "🧟")], "jurnalist": [("j", "📰")],
       "qoriqchi": [("q", "🛡")]}
ACT_VS = {"jangchi": [("k", "🎯")], "doktor": [("h", "💉")]}
FLAV = {"mergan": "🎯 Mergan tepkini bosdi", "buqalamun": "🦎 Buqalamun o'z tomonini tanladi",
        "manyak": "🔪 Manyak butalar orasiga yashirinib pichoqni qinidan chiqardi", "aferist": "🤹🏻 Aferist o'ljasini tanladi",
        "muxlis": "🔮 Muxlis dasht olishga ketdi", "komissar": "🕵🏻‍♂️ Komissar yozuvlarni tekshirishga ketdi",
        "mashuqa": "💃🏻 Mashuqa kimnikigadir mehmonga ketdi", "daydi": "🧙‍♂️ Daydi kimnikigadir shisha olish uchun ketdi",
        "zombi": "🧟‍♂️ Zombi ovga chiqdi"}
HOW = {"mafia": "mafialar", "manyak": "manyak", "ubiytsa": "qotil", "komissar": "komissar", "hero": "geroy",
       "kamikaze": "kamikaze portlashi", "vs": "dushman jamoa", "mine": "minior minasi", "kimyogar": "kimyogar",
       "tentak": "tentak", "sehrgar": "sehrgar", "ovchi": "ovchi o'qi"}
TEAM = {"r": "🔴 Qizil", "b": "🔵 Ko'k"}


def roles_kb():
    b = InlineKeyboardBuilder()
    for k, e, n, d in RL: b.button(text=f"{e} {n}", callback_data=f"ri:{k}")
    b.adjust(2); return b.as_markup()


def roles_kb_u(uid):
    b = InlineKeyboardBuilder()
    for k, e, n, d in RL: b.button(text=rname(k, uid), callback_data=f"ri:{k}")
    b.adjust(2); return b.as_markup()


def C(*names):
    """/game va /gamenightmafiauzbot (qo'shimcha nom) ikkalasini ham qabul qiladi."""
    return Command(*names, *[n + SUF for n in names])


@r.message(C("roles"))
async def cmd_roles(m: Message):
    await m.answer(tt(m.from_user.id, "roles_hdr"), reply_markup=roles_kb_u(m.from_user.id))


@r.callback_query(F.data.startswith("ri:"))
async def cb_role(c: CallbackQuery):
    k = c.data[3:]; uid = c.from_user.id
    await c.answer(f"{tt(uid, 'you_are', role=rname(k, uid))}\n\n{rdesc(k, uid)}"[:200], show_alert=True)


# ───────────────────────── Middleware (blok) ─────────────────────────
class Block(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u and not is_admin(u.id) and U(u.id, u.full_name)["blocked"]: return
        return await handler(event, data)


dp.update.outer_middleware(Block())


# ───────────────────────── /start, til ─────────────────────────
def start_kb(uid):
    b = InlineKeyboardBuilder()
    b.button(text="➕ " + tt(uid, "btn_gap"), url=f"https://t.me/{BOTNAME}?startgroup=true")
    b.button(text="🎄 " + tt(uid, "btn_news"), url=NEWS)
    b.button(text="🌐 " + tt(uid, "btn_lang"), callback_data="m:lang")
    b.button(text=tt(uid, "btn_ask"), url=CARD_USER)
    b.adjust(1, 2, 1); return b.as_markup()


def lang_kb(uid):
    cur = U(uid)["lang"]; b = InlineKeyboardBuilder()
    for code, label in (("uz", "🇺🇿 O'zbekcha"), ("ru", "🇷🇺 Русский"), ("en", "🇬🇧 English")):
        b.button(text=label + (" ◾" if code == cur else ""), callback_data=f"l:{code}")
    b.adjust(1); return b.as_markup()


@r.message(CommandStart(deep_link=True), F.chat.type == "private")
async def start_dl(m: Message, command: CommandObject):
    U(m.from_user.id, m.from_user.full_name)
    a = command.args or ""
    try:
        if a.startswith("sub"): return await sub_page(m, -int(a[3:]))
        if a.startswith("vs"):
            ch, tm = a[2:].rsplit("_", 1); return await vs_join_pm(m, int(ch), tm)
        if a.startswith("j"): return await join_game(m, int(a[1:]))
    except ValueError: pass
    await start_pm(m)


@r.message(CommandStart(), F.chat.type == "private")
async def start_pm(m: Message):
    U(m.from_user.id, m.from_user.full_name)
    await m.answer(tt(m.from_user.id, "start"), reply_markup=start_kb(m.from_user.id))


@r.message(Command("language"), F.chat.type == "private")
async def cmd_language(m: Message):
    uid = m.from_user.id; await m.answer(tt(uid, "langtitle"), reply_markup=lang_kb(uid))


@r.callback_query(F.data == "m:lang")
async def m_lang(c: CallbackQuery):
    uid = c.from_user.id; await c.message.answer(tt(uid, "langtitle"), reply_markup=lang_kb(uid)); await c.answer()


@r.callback_query(F.data == "m:start")
async def m_start(c: CallbackQuery):
    uid = c.from_user.id; await c.message.edit_text(tt(uid, "start"), reply_markup=start_kb(uid)); await c.answer()


@r.callback_query(F.data.startswith("l:"))
async def set_lang(c: CallbackQuery):
    uid = c.from_user.id; S(uid, lang=c.data[2:])
    try: await c.message.edit_text(tt(uid, "langtitle"), reply_markup=lang_kb(uid))
    except Exception: pass
    await c.answer()


# ───────────────────────── Profil ─────────────────────────
def onoff(v): return "🟢 ON" if v else "🔴 OFF"


def prof(uid):
    u = U(uid); lv = vlevel(u); ar = aroles(u)
    arl = "".join(f"\n{rname(x, uid)}" for x in ar if x in RD) if ar else f" <i>{tt(uid, 'none')}</i>"
    vip = f"\n{VIPS[lv][0]}" if lv else ""
    txt = tt(uid, "prof", name=esc(u["name"] or str(uid)), vip=vip, money=n_(u["money"]), dia=n_(u["diamonds"]), nc=n_(u["ncoin"]),
             h=n_(u["himoya"]), d=n_(u["hujjat"]), o=n_(u["osish"]), g=n_(u["geroyd"]), w=n_(u["wins"]), gm=n_(u["games"]), ar=arl)
    b = InlineKeyboardBuilder()
    b.button(text=f"🛡 - {onoff(u['t_h'])}", callback_data="tg:t_h")
    b.button(text=f"📁 - {onoff(u['t_d'])}", callback_data="tg:t_d")
    b.button(text=f"⚖️ - {onoff(u['t_o'])}", callback_data="tg:t_o")
    b.button(text=f"🔰 - {onoff(u['t_g'])}", callback_data="tg:t_g")
    b.button(text=tt(uid, "p_shop"), callback_data="m:shop")
    b.button(text=tt(uid, "p_buyd"), callback_data="m:buyd")
    b.button(text=tt(uid, "p_buym"), callback_data="m:buym")
    b.button(text=tt(uid, "p_hero"), callback_data="m:hero")
    b.button(text=tt(uid, "p_tr"), callback_data="m:transfer")
    if "127.0.0.1" not in WEB_URL and "localhost" not in WEB_URL:      # Telegram localhost havolani qabul qilmaydi
        b.button(text=tt(uid, "p_web"), url=f"{WEB_URL}/profile/{u['web']}/")
    b.adjust(2, 2, 1, 2, 1, 1, 1)
    return txt, b.as_markup()


@r.message(Command("profile"))
async def cmd_profile(m: Message):
    if m.chat.type != "private": return await m.reply("Profilni shaxsiy chatda ko'ring.")
    U(m.from_user.id, m.from_user.full_name); t_, k = prof(m.from_user.id); await m.answer(t_, reply_markup=k)


@r.callback_query(F.data == "m:profile")
async def m_prof(c: CallbackQuery):
    U(c.from_user.id, c.from_user.full_name); t_, k = prof(c.from_user.id)
    await c.message.edit_text(t_, reply_markup=k); await c.answer()


@r.callback_query(F.data.startswith("tg:"))
async def toggle(c: CallbackQuery):
    f = c.data[3:]; u = U(c.from_user.id); S(c.from_user.id, **{f: 0 if u[f] else 1})
    t_, k = prof(c.from_user.id); await c.message.edit_text(t_, reply_markup=k); await c.answer()


# ───────────────────────── Do'kon ─────────────────────────
ITEMS = {"himoya": ("money", 300), "hujjat": ("money", 200), "osish": ("diamonds", 1), "geroyd": ("diamonds", 3), "ncoin": ("diamonds", 100)}
CUR = {"money": "💶", "diamonds": "💎"}


def back(uid, to="m:profile"):
    b = InlineKeyboardBuilder(); b.button(text=tt(uid, "back"), callback_data=to); return b


@r.callback_query(F.data == "m:shop")
async def m_shop(c: CallbackQuery):
    uid = c.from_user.id; b = InlineKeyboardBuilder()
    for k, (cur, p) in ITEMS.items(): b.button(text=f"{tt(uid, 'it_' + k)} — {p} {CUR[cur]}", callback_data=f"b:{k}")
    b.button(text=tt(uid, "sh_hero"), callback_data="b:hero")
    b.button(text=tt(uid, "sh_hero_s"), callback_data="sh")
    b.button(text=tt(uid, "sh_vip"), callback_data="m:vip")
    b.button(text=tt(uid, "sh_ar"), callback_data="m:arole")
    b.button(text=tt(uid, "back"), callback_data="m:profile"); b.adjust(1)
    txt = tt(uid, "shop_title") + "\n\n" + "\n\n".join(
        f"{tt(uid, 'it_' + k)}\n{tt(uid, 'itd_' + k)}\n{tt(uid, 'price')}: {p} {CUR[cur]}" for k, (cur, p) in ITEMS.items())
    await c.message.edit_text(txt, reply_markup=b.as_markup()); await c.answer()


@r.callback_query(F.data.startswith("b:"))
async def buy(c: CallbackQuery):
    k = c.data[2:]; uid = c.from_user.id; u = U(uid)
    if k == "hero":
        lim = hlim(uid)
        if hcount(uid) >= lim: return await c.answer(tt(uid, "hero_full", n=lim), show_alert=True)
        if u["diamonds"] < 90: return await c.answer(tt(uid, "no_dia"), show_alert=True)
        A(uid, "diamonds", -90); add_hero(uid)
        return await c.answer(tt(uid, "hero_bought"), show_alert=True)
    cur, p = ITEMS[k]
    if u[cur] < p: return await c.answer(tt(uid, "no_dia" if cur == "diamonds" else "no_money"), show_alert=True)
    A(uid, cur, -p); A(uid, k, 1)
    await c.answer(tt(uid, "bought", n=tt(uid, "it_" + k)), show_alert=True)


@r.callback_query(F.data == "sh")
async def stars_hero(c: CallbackQuery):
    uid = c.from_user.id; lim = hlim(uid)
    if hcount(uid) >= lim: return await c.answer(tt(uid, "hero_full", n=lim), show_alert=True)
    await bot.send_invoice(uid, "🥷 Geroy", "1-daraja geroy", "hero", "XTR", [LabeledPrice(label="Geroy", amount=300)])
    await c.answer()


@r.callback_query(F.data == "m:vip")
async def m_vip(c: CallbackQuery):
    uid = c.from_user.id; b = InlineKeyboardBuilder()
    for k, (n, p) in VIPS.items(): b.button(text=f"{n} — {p} 💎", callback_data=f"v:{k}")
    b.button(text=tt(uid, "back"), callback_data="m:shop"); b.adjust(1)
    await c.message.edit_text(tt(uid, "vip_txt"), reply_markup=b.as_markup()); await c.answer()


@r.callback_query(F.data.startswith("v:"))
async def buy_vip(c: CallbackQuery):
    k = int(c.data[2:]); uid = c.from_user.id; u = U(uid); n, p = VIPS[k]
    if u["diamonds"] < p: return await c.answer(tt(uid, "no_dia"), show_alert=True)
    base = max(u["vip_until"], time.time()) if vlevel(u) == k else time.time()
    A(uid, "diamonds", -p); S(uid, vip=k, vip_until=int(base + 30 * 86400))
    if k >= 3: A(uid, "boosts", 1)             # Ultra / Promax: har sotib olishda 1 ta /boost
    await c.answer(tt(uid, "vip_bought", n=n), show_alert=True)


@r.callback_query(F.data == "m:arole")
async def m_arole(c: CallbackQuery):
    uid = c.from_user.id; b = InlineKeyboardBuilder()
    for k, (cur, p) in ARP.items():
        b.button(text=f"{rname(k, uid)} — {p} {'💎' if cur == 'd' else '💶'}", callback_data=f"ar:{k}")
    b.button(text=tt(uid, "ar_del"), callback_data="ar:del")
    b.button(text=tt(uid, "back"), callback_data="m:shop"); b.adjust(2)
    await c.message.edit_text(tt(uid, "ar_title", n=AMAX), reply_markup=b.as_markup()); await c.answer()


@r.callback_query(F.data.startswith("ar:"))
async def buy_arole(c: CallbackQuery):
    k = c.data[3:]; uid = c.from_user.id; u = U(uid); lst = aroles(u)
    if k == "del":
        if not lst: return await c.answer(tt(uid, "ar_none"), show_alert=True)
        if u["money"] < 100: return await c.answer(tt(uid, "no_money"), show_alert=True)
        A(uid, "money", -100); S(uid, arole=""); return await c.answer(tt(uid, "ar_deleted"), show_alert=True)
    if k not in ARP: return await c.answer()
    if len(lst) >= AMAX: return await c.answer(tt(uid, "ar_max", n=AMAX), show_alert=True)
    cur, p = ARP[k]; f = "diamonds" if cur == "d" else "money"
    if u[f] < p: return await c.answer(tt(uid, "no_bal"), show_alert=True)
    A(uid, f, -p); S(uid, arole=",".join(lst + [k]))
    await c.answer(tt(uid, "ar_ok", role=rname(k, uid)), show_alert=True)


# ───────────────────────── Olmos / dollar xaridi ─────────────────────────
STARS = {1: 5, 10: 50, 40: 200, 100: 500, 200: 1000, 1000: 5000}
DOLLAR = {1: 150, 5: 750, 10: 1500}


@r.callback_query(F.data == "m:buyd")
async def m_buyd(c: CallbackQuery):
    uid = c.from_user.id; b = InlineKeyboardBuilder()
    b.button(text=tt(uid, "buyd_stars"), callback_data="sd"); b.button(text=tt(uid, "buyd_card"), url=CARD_USER)
    b.button(text=tt(uid, "back"), callback_data="m:profile"); b.adjust(1)
    await c.message.edit_text(tt(uid, "buyd_title"), reply_markup=b.as_markup()); await c.answer()


@r.callback_query(F.data == "sd")
async def stars_menu(c: CallbackQuery):
    uid = c.from_user.id; b = InlineKeyboardBuilder()
    for d, s in STARS.items(): b.button(text=f"{d} 💎 = {s} ⭐️", callback_data=f"st:{d}")
    b.button(text=tt(uid, "back"), callback_data="m:buyd"); b.adjust(2)
    await c.message.edit_text(tt(uid, "stars_title"), reply_markup=b.as_markup()); await c.answer()


@r.callback_query(F.data.startswith("st:"))
async def stars_invoice(c: CallbackQuery):
    d = int(c.data[3:])
    await bot.send_invoice(c.from_user.id, f"{d} 💎 olmos", "Olmos xaridi", f"dia:{d}", "XTR", [LabeledPrice(label=f"{d} olmos", amount=STARS[d])])
    await c.answer()


@r.pre_checkout_query()
async def pre(q: PreCheckoutQuery): await q.answer(True)


@r.message(F.successful_payment)
async def paid(m: Message):
    uid = m.from_user.id; pl = m.successful_payment.invoice_payload
    if pl == "hero":
        if hcount(uid) < hlim(uid): add_hero(uid); return await m.answer(tt(uid, "hero_bought"))
        A(uid, "diamonds", 90); return await m.answer("🥷 Geroy sloti to'lgan — 90 💎 hisobingizga qaytarildi.")
    d = int(pl.split(":")[1]); A(uid, "diamonds", d)
    await m.answer(tt(uid, "paid", d=d))


@r.callback_query(F.data == "m:buym")
async def m_buym(c: CallbackQuery):
    uid = c.from_user.id; b = InlineKeyboardBuilder()
    for d, p in DOLLAR.items(): b.button(text=f"{d} 💎 → {p} 💶", callback_data=f"dm:{d}")
    b.button(text=tt(uid, "back"), callback_data="m:profile"); b.adjust(1)
    await c.message.edit_text(tt(uid, "buym_title"), reply_markup=b.as_markup()); await c.answer()


@r.callback_query(F.data.startswith("dm:"))
async def buy_dollar(c: CallbackQuery):
    d = int(c.data[3:]); uid = c.from_user.id
    if U(uid)["diamonds"] < d: return await c.answer(tt(uid, "no_dia"), show_alert=True)
    A(uid, "diamonds", -d); A(uid, "money", DOLLAR[d]); await c.answer(f"✅ +{DOLLAR[d]} 💶", show_alert=True)


# ───────────────────────── Geroy ─────────────────────────
MAXH = [0, 0, 10, 20, 30, 40, 50, 50, 60, 70, 80, 90, 100, 100, 110, 120, 130, 140, 150, 150, 160, 170, 180, 190,
        200, 200, 210, 220, 230, 240, 250, 250, 260, 270, 280, 290, 300, 300]
WAIT = {}
PEND = {}


def lvl(p): return min(38, p // 1100 + 1)


def lvl_list(uid):
    out = []
    for i in range(38):
        pw = tt(uid, "pow_range", a=40 + 7 * i, b=47 + 7 * i) if i < 37 else tt(uid, "pow_max")
        out.append(tt(uid, "lvl_fmt", i=i + 1, pts=i * 1100, pow=pw, mh=MAXH[i]))
    return out


def hero_dmg(uid):
    L_ = lvl(U(uid)["points"])
    return min(100, random.randint(40 + 7 * (L_ - 1), 47 + 7 * (L_ - 1)))


def hero_txt(u, uid, short=False):
    L_ = lvl(u["points"])
    pw = tt(uid, "pow_range", a=40 + 7 * (L_ - 1), b=47 + 7 * (L_ - 1)) if L_ < 38 else tt(uid, "pow_max")
    nxt = tt(uid, "hero_next", n=L_ + 1, p=L_ * 1100) if L_ < 38 else ""
    s = tt(uid, "hero_fmt", name=esc(u["hname"]) or tt(uid, "noname"), L=L_, pow=pw, hp=u["hprot"], mh=MAXH[L_ - 1],
           ch=u["charge"], pts=u["points"], gd=u["geroyd"], nxt=nxt)
    return s if short else s + "\n\n" + tt(uid, "hero_shop")


@r.callback_query(F.data == "m:hero")
async def m_hero(c: CallbackQuery):
    uid = c.from_user.id; u = U(uid); lim = hlim(uid); cnt = hcount(uid); b = InlineKeyboardBuilder()
    if not u["has_hero"]:
        b.button(text=tt(uid, "hb_buy_d"), callback_data="b:hero"); b.button(text=tt(uid, "hb_buy_s"), callback_data="sh")
        b.button(text=tt(uid, "back"), callback_data="m:profile"); b.adjust(1)
        return await c.message.edit_text(tt(uid, "hero_none"), reply_markup=b.as_markup())
    for t_, d in [(tt(uid, "hb_ball"), "h:ball"), (tt(uid, "hb_prot"), "h:prot"), (tt(uid, "hb_charge"), "h:charge"),
                  (tt(uid, "hb_name"), "h:name"), (tt(uid, "hb_lvls"), "h:lvls"), (tt(uid, "hb_status"), "h:status")]:
        b.button(text=t_, callback_data=d)
    if cnt > 1: b.button(text=tt(uid, "hb_list", n=cnt, lim=lim), callback_data="h:list")
    if cnt < lim: b.button(text=tt(uid, "hb_buy_d"), callback_data="b:hero"); b.button(text=tt(uid, "hb_buy_s"), callback_data="sh")
    b.button(text=tt(uid, "back"), callback_data="m:profile"); b.adjust(1)
    try: await c.message.edit_text(hero_txt(u, uid), reply_markup=b.as_markup())
    except Exception: pass
    try: await c.answer()
    except Exception: pass


@r.callback_query(F.data.startswith("hs:"))
async def hero_select(c: CallbackQuery):
    uid = c.from_user.id; hid = int(c.data[3:])
    if hid: hero_swap(uid, hid)
    await m_hero(c)


@r.callback_query(F.data.startswith("h:"))
async def hero_act(c: CallbackQuery):
    a = c.data[2:]; uid = c.from_user.id; u = U(uid)
    if not u["has_hero"]: return await c.answer("Geroy yo'q", show_alert=True)
    if a == "lvls":
        ls = lvl_list(uid)
        await c.message.answer("\n\n".join(ls[:19]))
        await c.message.answer("\n\n".join(ls[19:]) + "\n\n" + tt(uid, "lvl_yours", n=lvl(u["points"])))
        return await c.answer()
    if a == "list":
        b = InlineKeyboardBuilder()
        b.button(text=f"✅ {u['hname'] or tt(uid, 'noname')} — {lvl(u['points'])}", callback_data="hs:0")
        for x in db.execute("SELECT * FROM heroes WHERE uid=? ORDER BY id", (uid,)):
            b.button(text=f"🥷 {x['name'] or tt(uid, 'noname')} — {lvl(x['points'])}", callback_data=f"hs:{x['id']}")
        b.button(text=tt(uid, "back"), callback_data="m:hero"); b.adjust(1)
        await c.message.edit_text(tt(uid, "h_list", n=hcount(uid), lim=hlim(uid)), reply_markup=b.as_markup()); return await c.answer()
    if a == "status":
        WAIT[uid] = "status"; await c.message.answer(tt(uid, "h_status_ask")); return await c.answer()
    if a == "name":
        if u["money"] < 800: return await c.answer(tt(uid, "h_no800"), show_alert=True)
        WAIT[uid] = "hname"; await c.message.answer(tt(uid, "h_name_ask")); return await c.answer()
    cost = {"ball": ("diamonds", 50), "prot": ("money", 300), "charge": ("money", 200)}[a]
    if u[cost[0]] < cost[1]: return await c.answer(tt(uid, "no_bal"), show_alert=True)
    A(uid, cost[0], -cost[1])
    if a == "ball": A(uid, "points", 1000); await c.answer(tt(uid, "h_ball_ok"), show_alert=True)
    if a == "prot": S(uid, hprot=MAXH[lvl(u["points"]) - 1]); await c.answer(tt(uid, "h_prot_ok"), show_alert=True)
    if a == "charge": S(uid, charge=10); await c.answer(tt(uid, "h_charge_ok"), show_alert=True)
    await m_hero(c)


@r.message(Command("geroyinfo"))
async def geroyinfo(m: Message):
    tg = m.reply_to_message.from_user if m.reply_to_message else m.from_user; u = U(tg.id, tg.full_name)
    await m.reply(hero_txt(u, m.from_user.id, True) if u["has_hero"] else "Bu foydalanuvchida geroy yo'q.")


@r.message(C("gtop"))
async def gtop(m: Message):
    rows = db.execute("SELECT * FROM users WHERE has_hero=1 ORDER BY points DESC LIMIT 10").fetchall()
    await m.answer("🏆 <b>Geroylar reytingi</b>\n\n" + ("\n".join(
        f"{i}. {esc(x['hname'] or 'nomsiz')} ({esc(x['name'])}) — {lvl(x['points'])}-daraja, {x['points']} ball"
        for i, x in enumerate(rows, 1)) or "Hozircha yo'q"))


@r.message(Command("tgeroy"))
async def tgeroy(m: Message):
    if not m.reply_to_message: return await m.reply("Geroyni sotish uchun xaridorga reply qiling.")
    s, tg = m.from_user, m.reply_to_message.from_user; u = U(s.id); ub = U(tg.id, tg.full_name)
    if not u["has_hero"] or hcount(tg.id) >= HLIM[vlevel(ub)]: return await m.reply("Sizda geroy yo'q yoki xaridorda geroy sloti to'lgan.")
    price = lvl(u["points"]) * 10
    b = InlineKeyboardBuilder(); b.button(text=f"✅ Sotib olish ({price} 💎)", callback_data=f"tb:{s.id}:{tg.id}:{price}")
    b.button(text="❌ Rad etish", callback_data=f"tb:{s.id}:{tg.id}:0")
    await m.answer(f"{esc(tg.full_name)}, {esc(s.full_name)} geroyini ({lvl(u['points'])}-daraja) {price} 💎 ga sotmoqda.", reply_markup=b.as_markup())


@r.callback_query(F.data.startswith("tb:"))
async def tgeroy_buy(c: CallbackQuery):
    _, s, tg, p = c.data.split(":"); s, tg, p = int(s), int(tg), int(p)
    if c.from_user.id != tg: return await c.answer("Bu siz uchun emas", show_alert=True)
    if p == 0: return await c.message.edit_text("❌ Rad etildi.")
    us, ut = U(s), U(tg)
    if not us["has_hero"] or hcount(tg) >= HLIM[vlevel(ut)] or ut["diamonds"] < p:
        return await c.answer("Shartlar bajarilmadi (olmos/geroy).", show_alert=True)
    A(tg, "diamonds", -p); A(s, "diamonds", p)
    add_hero(tg, us["hname"], us["points"], us["hprot"], us["charge"]); hero_remove_active(s)
    await c.message.edit_text("✅ Geroy sotildi!")


# ───────────────────────── Profil almashish ─────────────────────────
@r.callback_query(F.data == "m:transfer")
async def m_transfer(c: CallbackQuery):
    uid = c.from_user.id; WAIT[uid] = "transfer"
    await c.message.answer(tt(uid, "tr_ask")); await c.answer()


@r.callback_query(F.data.in_({"pt:y", "pt:n"}))
async def cb_pt(c: CallbackQuery):
    uid = c.from_user.id; tid = PEND.pop(uid, None)
    if c.data == "pt:n" or not tid:
        t_, k = prof(uid); await c.message.edit_text(t_, reply_markup=k); return await c.answer()
    tu = db.execute("SELECT * FROM users WHERE id=?", (tid,)).fetchone()
    if not tu or tu["games"] > 0: return await c.answer(tt(uid, "tr_new"), show_alert=True)
    if U(uid)["diamonds"] < 5: return await c.answer(tt(uid, "tr_5"), show_alert=True)
    A(uid, "diamonds", -5); u = U(uid)                   # -5 💎 komissiya bilan o'tadi
    S(tid, **{c_: u[c_] for c_ in COLS})
    S(uid, **{c_: ("" if isinstance(u[c_], str) else 0) for c_ in COLS})
    db.execute("UPDATE heroes SET uid=? WHERE uid=?", (tid, uid)); db.commit()
    txlog(uid, tid, "account", 0)
    await c.message.edit_text(tt(uid, "tr_done")); await pm(tid, tt(tid, "tr_got")); await c.answer()


# ───────────────────────── Para ─────────────────────────
@r.message(C("para"))
async def para(m: Message):
    if not m.reply_to_message: return await m.reply("Para qo'shish uchun odamga reply qiling.")
    a, tg = m.from_user, m.reply_to_message.from_user
    if a.id == tg.id or tg.is_bot: return
    U(a.id, a.full_name); U(tg.id, tg.full_name)
    if tg.id in pairs_of(a.id): return await m.reply("Siz allaqachon para bo'lgansiz.")
    if len(pairs_of(a.id)) >= plim(a.id) or len(pairs_of(tg.id)) >= plim(tg.id):
        return await m.reply("Sizda yoki unda para limiti to'lgan (VIP bilan oshadi).")
    b = InlineKeyboardBuilder(); b.button(text="💕 Qabul", callback_data=f"pa:{a.id}:{tg.id}:1"); b.button(text="💔 Rad", callback_data=f"pa:{a.id}:{tg.id}:0")
    await m.answer(f"💌 {esc(tg.full_name)}, {esc(a.full_name)} sizga para bo'lishni taklif qilmoqda!", reply_markup=b.as_markup())


@r.callback_query(F.data.startswith("pa:"))
async def para_ans(c: CallbackQuery):
    _, a, tg, y = c.data.split(":"); a, tg = int(a), int(tg)
    if c.from_user.id != tg: return await c.answer("Bu siz uchun emas", show_alert=True)
    if y == "1":
        if len(pairs_of(a)) >= plim(a) or len(pairs_of(tg)) >= plim(tg): return await c.message.edit_text("Para limiti to'lgan.")
        padd(a, tg); await c.message.edit_text("💞 Yangi para tuzildi!")
    else: await c.message.edit_text("💔 Rad etildi.")


@r.message(C("mypara"))
async def mypara(m: Message):
    uid = m.from_user.id; U(uid, m.from_user.full_name); ps = pairs_of(uid); lim = plim(uid)
    if not ps: return await m.answer("👫 <b>Paralarim</b>\n\nSizda para yo'q. /para orqali para qo'shing.")
    txt = f"👫 Sizning asosiy parangiz : <b>{esc(U(ps[0])['name'])}</b> {lim}/{len(ps)}"
    if len(ps) > 1: txt += "\n\nBoshqa paralar: " + ", ".join(esc(U(x)["name"]) for x in ps[1:])
    await m.answer(txt)


@r.message(C("dpara"))
async def dpara(m: Message):
    uid = m.from_user.id; ps = pairs_of(uid)
    if not ps: return await m.reply("Sizda para yo'q.")
    if m.reply_to_message and m.reply_to_message.from_user.id in ps:
        pdel(uid, m.reply_to_message.from_user.id); return await m.reply("💔 Para uzildi.")
    if len(ps) == 1: pdel(uid, ps[0]); return await m.reply("💔 Para uzildi.")
    b = InlineKeyboardBuilder()
    for x in ps: b.button(text=f"💔 {U(x)['name']}", callback_data=f"dp:{uid}:{x}")
    b.adjust(1); await m.reply("Qaysi parani uzmoqchisiz?", reply_markup=b.as_markup())


@r.callback_query(F.data.startswith("dp:"))
async def dpara_cb(c: CallbackQuery):
    _, a, x = c.data.split(":")
    if c.from_user.id != int(a): return await c.answer("Bu siz uchun emas", show_alert=True)
    pdel(int(a), int(x)); await c.message.edit_text("💔 Para uzildi."); await c.answer()


# ───────────────────────── O'tkazmalar / giveaway ─────────────────────────
def num(m: Message):
    p = (m.text or "").split()
    return int(p[-1]) if len(p) > 1 and p[-1].isdigit() else 0


async def transfer(m: Message, f, name):
    if not m.reply_to_message: return await m.reply("Odamga reply qiling.")
    n = num(m); s, tg = m.from_user, m.reply_to_message.from_user
    if n < 1 or s.id == tg.id or tg.is_bot: return await m.reply(f"Foydalanish: reply + /{'give' if f == 'diamonds' else 'money'} miqdor")
    u = U(s.id, s.full_name); U(tg.id, tg.full_name); vip = vlevel(u) > 0
    if f == "money":
        fee = 0 if vip else 100                       # VIP — komissiyasiz; VIP bo'lmasa har o'tkazmaga 100 💶
        if u["money"] < n + fee: return await m.reply(f"{name} yetarli emas (o'tkazma + komissiya {fee})." if fee else f"{name} yetarli emas.")
        A(s.id, f, -(n + fee)); A(tg.id, f, n); got = n
        txt = f"✅ {n} {name} o'tkazildi." + ("" if vip else f" Komissiya: {fee} 💶 (VIP'larda komissiya yo'q)")
    else:
        if u[f] < n: return await m.reply(f"{name} yetarli emas.")
        got = n if vip else int(n * 0.9)
        A(s.id, f, -n); A(tg.id, f, got)
        txt = f"✅ {n} {name} o'tkazildi. Qabul qildi: {got}" + ("" if vip else " (10% komissiya, VIP komissiyasiz)")
    txlog(s.id, tg.id, f, got); await m.reply(txt)


@r.message(C("give"))
async def cmd_give(m: Message): await transfer(m, "diamonds", "💎")


@r.message(C("money"))
async def cmd_money(m: Message): await transfer(m, "money", "💶")


GV = {}


async def make_gv(m: Message, kind, restricted=False):
    n = num(m) if kind != "himoya" else 1; uid = m.from_user.id; u = U(uid, m.from_user.full_name)
    f = "himoya" if kind == "himoya" else "diamonds"
    if m.chat.type == "private": return await m.reply("Faqat guruhda.")
    if n < 1 or u[f] < n: return await m.reply("Balans yetarli emas yoki miqdor noto'g'ri.")
    A(uid, f, -n)
    b = InlineKeyboardBuilder(); b.button(text="🎁 Olish", callback_data="gv")
    msg = await m.answer(f"🎁 {esc(m.from_user.full_name)} {n} {'🛡 himoya' if kind == 'himoya' else '💎 olmos'} giveaway qildi!"
                         + (" (faqat o'yin qatnashchilari)" if restricted else ""), reply_markup=b.as_markup())
    GV[(m.chat.id, msg.message_id)] = dict(kind=kind, n=n, f=f, owner=uid, r=restricted)


@r.message(C("send"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_send(m: Message): await make_gv(m, "send")


@r.message(C("gsend"))
async def cmd_gsend(m: Message): await make_gv(m, "send", True)


@r.message(C("giveaway"))
async def cmd_gw(m: Message): await make_gv(m, "himoya")


@r.callback_query(F.data == "gv")
async def gv_claim(c: CallbackQuery):
    k = (c.message.chat.id, c.message.message_id); d = GV.get(k); uid = c.from_user.id
    if not d: return await c.answer("Tugagan", show_alert=True)
    U(uid, c.from_user.full_name)
    if d["r"]:
        g = games.get(c.message.chat.id)
        if not g or uid not in g.p: return await c.answer("Faqat o'yin qatnashchilari uchun!", show_alert=True)
    GV.pop(k); A(uid, d["f"], d["n"])
    await c.message.edit_text(f"🎉 {esc(c.from_user.full_name)} {d['n']} {'🛡' if d['f'] == 'himoya' else '💎'} oldi!"); await c.answer()


# ---- /change: ishtirokchilar ro'yxati (max 50), egasi To'xtatadi ----
CH = {}


def ch_text(d):
    names = "\n".join(f"{i}) <a href='tg://user?id={u}'>{esc(nm)}</a>" for i, (u, nm) in enumerate(d["join"].items(), 1)) or "—"
    return (f"<a href='tg://user?id={d['owner']}'>{esc(d['oname'])}</a> kimgadir {d['n']} ta 💎 sovg'a qilmoqchi!\n\n"
            f"Ishtirokchilar:\n{names}\n\nIshtirokchilar soni: {len(d['join'])}/{CH_MAX}")


def ch_kb():
    b = InlineKeyboardBuilder(); b.button(text="Qo'shilish", callback_data="chj"); b.button(text="To'xtatish", callback_data="chs")
    return b.as_markup()


@r.message(C("change"), GAP)
async def cmd_change(m: Message):
    n = num(m); uid = m.from_user.id; u = U(uid, m.from_user.full_name)
    if n < 1 or u["diamonds"] < n: return await m.reply("Foydalanish: /change miqdor (olmosingiz yetarli bo'lishi kerak).")
    A(uid, "diamonds", -n)
    d = dict(n=n, owner=uid, oname=m.from_user.full_name, join={}, chat=m.chat.id)
    msg = await m.answer(ch_text(d), reply_markup=ch_kb()); d["mid"] = msg.message_id
    CH[(m.chat.id, msg.message_id)] = d
    try: await bot.pin_chat_message(m.chat.id, msg.message_id, disable_notification=False)
    except Exception: pass
    asyncio.create_task(ch_timer(m.chat.id, msg.message_id))


async def ch_timer(chat, mid):
    await asyncio.sleep(900)
    await ch_finish(chat, mid)


async def ch_finish(chat, mid):
    d = CH.pop((chat, mid), None)
    if not d: return
    if d["join"]:
        w = random.choice(list(d["join"])); A(w, "diamonds", d["n"])
        txt = ch_text(d) + f"\n\n🏆 G'olib: <a href='tg://user?id={w}'>{esc(d['join'][w])}</a> — {d['n']} 💎"
    else:
        A(d["owner"], "diamonds", d["n"]); txt = ch_text(d) + "\n\nHech kim qo'shilmadi, olmos qaytarildi."
    try: await bot.edit_message_text(txt, chat_id=chat, message_id=mid, reply_markup=None)
    except Exception: pass
    try: await bot.unpin_chat_message(chat, mid)
    except Exception: pass


@r.callback_query(F.data == "chj")
async def ch_join(c: CallbackQuery):
    k = (c.message.chat.id, c.message.message_id); d = CH.get(k); uid = c.from_user.id
    if not d: return await c.answer("Tugagan", show_alert=True)
    if uid == d["owner"]: return await c.answer("Siz egasiz, qatnasha olmaysiz!", show_alert=True)
    if uid in d["join"]: return await c.answer("Siz allaqachon qo'shilgansiz!", show_alert=True)
    U(uid, c.from_user.full_name); d["join"][uid] = c.from_user.full_name
    await c.answer("✅ Qo'shildingiz!")
    if len(d["join"]) >= CH_MAX: return await ch_finish(*k)
    try: await c.message.edit_text(ch_text(d), reply_markup=ch_kb())
    except Exception: pass


@r.callback_query(F.data == "chs")
async def ch_stop(c: CallbackQuery):
    k = (c.message.chat.id, c.message.message_id); d = CH.get(k)
    if not d: return await c.answer("Tugagan", show_alert=True)
    if c.from_user.id != d["owner"] and not is_admin(c.from_user.id): return await c.answer("Faqat egasi to'xtata oladi!", show_alert=True)
    await c.answer(); await ch_finish(*k)


# ---- /psend: guruh obunasi ----
async def sub_view(uid, chat):
    try: title = (await bot.get_chat(chat)).title or str(chat)
    except Exception: title = str(chat)
    g = Gr(chat); mp, yp = sub_prices(uid)
    until = dfmt(g["sub_until"]) if g["sub_until"] > time.time() else tt(uid, "sub_none")
    txt = tt(uid, "sub_txt", title=esc(title), until=until, bal=U(uid)["diamonds"])
    b = InlineKeyboardBuilder()
    b.button(text=f"📅 {tt(uid, 'sub_m')} — {mp} 💎", callback_data=f"sb:{chat}:m")
    b.button(text=f"🗓 {tt(uid, 'sub_y')} — {yp} 💎", callback_data=f"sb:{chat}:y")
    b.button(text=tt(uid, "back"), callback_data="m:start"); b.adjust(1)
    return txt, b.as_markup()


def sub_prices(uid): return (5, 60) if vlevel(U(uid)) == 4 else (10, 70)      # Promax uchun arzon


async def sub_page(m: Message, chat):
    txt, kb = await sub_view(m.from_user.id, chat); await m.answer(txt, reply_markup=kb)


@r.callback_query(F.data.startswith("sb:"))
async def sub_buy(c: CallbackQuery):
    _, ch, k = c.data.split(":"); chat = int(ch); uid = c.from_user.id; u = U(uid)
    mp, yp = sub_prices(uid); price, days = (mp, 30) if k == "m" else (yp, 365)
    if u["diamonds"] < price: return await c.answer(tt(uid, "sub_nodia"), show_alert=True)
    A(uid, "diamonds", -price); new = sub_add(chat, days)
    await c.answer(tt(uid, "sub_ok_m" if k == "m" else "sub_ok_y"), show_alert=True)
    txt, kb = await sub_view(uid, chat)
    try: await c.message.edit_text(txt, reply_markup=kb)
    except Exception: pass
    await say(chat, f"✅ {esc(c.from_user.full_name)} guruh obunasini faollashtirdi ({'1 oy' if k == 'm' else '1 yil'}).\n📅 Obuna tugashi: {dfmt(new)}")


async def need_sub(m: Message):
    if sub_active(m.chat.id): return False
    b = InlineKeyboardBuilder(); b.button(text="📅 Guruh obunasi", url=sub_link(m.chat.id))
    await m.reply("⛔️ Bu guruhda obuna faol emas. Botdan foydalanish uchun guruh obunasini faollashtiring (1 oy — 10 💎, 1 yil — 70 💎).",
                  reply_markup=b.as_markup())
    return True


@r.message(C("psend"))
async def psend(m: Message):
    uid = m.from_user.id; U(uid, m.from_user.full_name)
    if m.chat.type == "private": return await m.reply("Bu buyruq guruhda ishlaydi: /psend")
    n = num(m); mp, yp = sub_prices(uid)
    if n == 0:
        b = InlineKeyboardBuilder(); b.button(text="📅 Guruh obunasi", url=sub_link(m.chat.id))
        return await m.reply("Obunani shaxsiy chatda boshqaring.", reply_markup=b.as_markup())
    if n not in (mp, yp): return await m.reply(f"Noto'g'ri miqdor. 1 oy — /psend {mp}, 1 yil — /psend {yp}")
    if U(uid)["diamonds"] < n: return await m.reply("Olmos yetarli emas. Shaxsiy balansingizni to‘ldiring.")
    A(uid, "diamonds", -n); days = 30 if n == mp else 365; new = sub_add(m.chat.id, days)
    await m.reply(f"✅ Sotib olindi! Bot aktiv holatda ({'1-oy' if days == 30 else '1 yil (365 kun)'}).\n📅 Obuna tugashi: {dfmt(new)}\n💎 Sizning balansingiz: {U(uid)['diamonds']}")


@r.message(C("ginfo"))
async def ginfo(m: Message):
    g = Gr(m.chat.id)
    await m.reply(f"🏦 Guruh obunasi: {('✅ faol, tugashi ' + dfmt(g['sub_until'])) if g['sub_until'] > time.time() else '❌ faol emas'}")


@r.message(C("boost"), GAP)
async def cmd_boost(m: Message):
    u = U(m.from_user.id, m.from_user.full_name); lv = vlevel(u)
    if lv < 3: return await m.reply("🚀 /boost faqat VIP Ultra va VIP Ultra Promax uchun.")
    if u["boosts"] < 1: return await m.reply("Boost qolmagan. VIP ni qayta sotib oling — har sotib olishda yangi boost beriladi.")
    A(m.from_user.id, "boosts", -1); days = 60 if lv == 4 else 30; new = sub_add(m.chat.id, days)
    await m.reply(f"🚀 Guruhga {'2 oylik' if lv == 4 else '1 oylik'} bepul obuna berildi!\n📅 Obuna tugashi: {dfmt(new)}")


async def say(chat, text, **kw):
    try: return await bot.send_message(chat, text, **kw)
    except Exception: return None


async def sub_watch():
    while True:
        try:
            for x in db.execute("SELECT id FROM groups WHERE sub_until>0 AND sub_until<=? AND notified=0", (int(time.time()),)).fetchall():
                db.execute("UPDATE groups SET notified=1 WHERE id=?", (x["id"],)); db.commit()
                b = InlineKeyboardBuilder(); b.button(text="🔄 Qayta sotib olish", url=sub_link(x["id"]))
                await say(x["id"], "⌛️ Sizning 1 oylik yoki 1 yillik obunangiz tugadi.\nQayta sotib olish uchun pastdagi tugmani bosing.", reply_markup=b.as_markup())
        except Exception:
            logging.exception("sub_watch")
        await asyncio.sleep(60)


# ───────────────────────── NEWS KANAL: /send ─────────────────────────
def is_news(m: Message):
    return (m.chat.username or "").lower() == NEWS_USER.lower()


NG = {}


def ng_text(d, final=False):
    head = f"🎁 <b>Obunachilarimizga {d['n']} ta 💎 sovg'a ajratildi!</b>"
    if not d["got"]: return head + "\n\nOlish uchun pastdagi tugmani bosing!"
    lines = "\n".join(f"{i}) {esc(nm)} 1💎" for i, nm in enumerate(d["got"], 1))
    return head + f"\n\n<b>Olganlar:</b>\n{lines}" + ("" if final else f"\n\nQolgan: {d['left']} 💎")


@r.channel_post(Command("send"), is_news)
async def news_send(m: Message):
    n = num(m)
    if n < 1: return
    b = InlineKeyboardBuilder(); b.button(text="🎁 Olish", callback_data="ng")
    d = dict(n=n, left=n, got=[], users=set())
    msg = await m.answer(ng_text(d), reply_markup=b.as_markup())
    NG[(msg.chat.id, msg.message_id)] = d
    try: await m.delete()
    except Exception: pass


@r.callback_query(F.data == "ng")
async def news_claim(c: CallbackQuery):
    k = (c.message.chat.id, c.message.message_id); d = NG.get(k); uid = c.from_user.id
    if not d: return await c.answer("Giveaway tugagan!", show_alert=True)
    if uid in d["users"]: return await c.answer("Siz allaqachon olgansiz!", show_alert=True)
    U(uid, c.from_user.full_name)
    d["users"].add(uid); d["left"] -= 1; d["got"].append(c.from_user.full_name); A(uid, "diamonds", 1)
    await c.answer("🎉 Sizga 1 💎 berildi!")
    fin = d["left"] <= 0
    if fin: NG.pop(k, None)
    b = InlineKeyboardBuilder(); b.button(text="🎁 Olish", callback_data="ng")
    try: await c.message.edit_text(ng_text(d, fin), reply_markup=None if fin else b.as_markup())
    except Exception: pass


# ---- /top1 /top7 /top30 (guruhda ham, kanalda ham) ----
TOPS = {1: "📆 Kunlik eng yaxshi o'yinchilar", 7: "📆 Haftalik eng yaxshi o'yinchilar",
        30: "📆 Oylik eng yaxshi o'yinchilar", 0: "🏆 Barcha vaqtdagi eng yaxshi o'yinchilar"}
TOPCMDS = ("top", "top1", "top7", "top30", "topall")


def topdays(cmd):
    cmd = cmd.lower()
    if cmd.endswith(SUF): cmd = cmd[:-len(SUF)]
    return {"top1": 1, "top7": 7, "top30": 30, "top": 30, "topall": 0}.get(cmd, 30)


async def send_top(m: Message, days):
    since = int(time.time() - days * 86400) if days else 0
    rows = db.execute("""SELECT u.name nm, SUM(l.ball) s FROM pts_log l JOIN users u ON u.id=l.uid
                         WHERE l.ts>=? GROUP BY l.uid HAVING s>0 ORDER BY s DESC LIMIT 30""", (since,)).fetchall()
    body = "\n".join(f"{i}. {esc(x['nm'])} – {x['s']} ball" for i, x in enumerate(rows, 1)) or "Hozircha ma'lumot yo'q."
    await m.answer(f"<b>{TOPS[days]}</b>\n\n{body}")


@r.message(C(*TOPCMDS))
async def top_msg(m: Message, command: CommandObject): await send_top(m, topdays(command.command))


@r.channel_post(C(*TOPCMDS), is_news)
async def news_top(m: Message, command: CommandObject): await send_top(m, topdays(command.command))


# ───────────────────────── O'YIN ─────────────────────────
games = {}
MODES = {"classic": ("Classik", 20), "night": ("Night", 30), "zombie": ("Zombie", 30), "mega": ("Mega Night", 30), "vs": ("VS mode", 30)}
MC = {}
# rejimlarda chiqmaydigan rollar
EXCL = {"classic": {"suidsid", "aferist", "zombi", "ubiytsa", "muxlis"},
        "night": {"janob", "zombi", "ubiytsa", "aferist", "kimyogar", "muxlis", "mergan"},
        "mega": {"zombi"}}
CORE = {"tinch", "don", "mafia", "komissar", "doktor", "manyak", "qoy", "zombi", "jangchi"}
SAFE = ["omadli", "janob", "daydi", "serjant", "mashuqa"]
ZPOOL = ["serjant", "omadli", "janob", "mergan", "daydi", "jurnalist", "qoriqchi", "hamshira", "ovchi", "kamikaze"]
SELL = {"himoya": ("🛡", 150), "hujjat": ("📁", 100), "osish": ("⚖️", 700), "geroyd": ("🔰", 1500)}


def newp(name, team=None):
    return dict(n=name, r=None, a=True, idle=0, act=False, r0=None, hp=100, shield=False, t=team, osh=False)


class G:
    def __init__(s, chat, owner, vs=False):
        s.chat, s.owner, s.p, s.state, s.round = chat, owner, {}, "reg", 0
        s.night, s.hero, s.votes, s.start_ev, s.task, s.regmsg = {}, {}, {}, asyncio.Event(), None, None
        s.vs = vs
        s.mode = "vs" if vs else Gr(chat)["mode"]
        s.url, s.t0, s.suid = None, time.time(), None
        s.need, s.night_ev, s.idx = set(), asyncio.Event(), {}
        s.yn, s.cand = {}, None
        s.immune, s.seller, s.offers, s.fans, s.wit = set(), {}, {}, {}, []

    def alive(s): return [u for u, d in s.p.items() if d["a"]]

    def plist(s):
        tag = {"r": "🔴 ", "b": "🔵 "}
        return "\n".join(f"{i}. {tag.get(s.p[u]['t'], '') if s.vs else ''}{vemoji(u)}<a href='tg://user?id={u}'>{esc(s.p[u]['n'])}</a>"
                         for i, u in enumerate(s.alive(), 1))


async def pm(uid, text, **kw):
    try: return await bot.send_message(uid, text, **kw)
    except Exception: return None


async def gm(g, text, **kw):
    try: return await bot.send_message(g.chat, text, **kw)
    except Exception: return None


async def pm_g(g, uid, text):
    kb = None
    if g.url:
        b = InlineKeyboardBuilder(); b.button(text="Guruhga o'tish", url=g.url); kb = b.as_markup()
    return await pm(uid, text, reply_markup=kb)


def link_kb(label="Botga o'tish"):
    b = InlineKeyboardBuilder(); b.button(text=label, url=f"https://t.me/{BOTNAME}"); return b.as_markup()


async def group_url(chat_id):
    try:
        c = await bot.get_chat(chat_id)
        if c.username: return f"https://t.me/{c.username}"
        if c.invite_link: return c.invite_link
        try: return await bot.export_chat_invite_link(chat_id)
        except Exception: pass
    except Exception: pass
    return f"https://t.me/c/{str(chat_id)[4:]}" if str(chat_id).startswith("-100") else None


async def gmedia(g, key, caption, kb=None):
    """media/night.mp4|gif|jpg|png va media/day.* fayllari yoki NIGHT_MEDIA / DAY_MEDIA (URL). Topilmasa — matn."""
    try:
        if key in MC: kind, src = MC[key]
        else:
            src, kind = None, None
            for ext, kd in (("mp4", "a"), ("gif", "a"), ("jpg", "p"), ("jpeg", "p"), ("png", "p")):
                pth = f"media/{key}.{ext}"
                if os.path.exists(pth): src, kind = FSInputFile(pth), kd; break
            if not src:
                url = os.getenv(f"{key.upper()}_MEDIA", "")
                if url: src, kind = url, ("a" if url.lower().endswith(("mp4", "gif")) else "p")
            if not src: return await gm(g, caption, reply_markup=kb)
        if kind == "a": msg = await bot.send_animation(g.chat, src, caption=caption, reply_markup=kb)
        else: msg = await bot.send_photo(g.chat, src, caption=caption, reply_markup=kb)
        MC[key] = (kind, msg.animation.file_id if kind == "a" and msg.animation else (msg.photo[-1].file_id if msg.photo else src))
        return msg
    except Exception:
        logging.exception("media xato")
        return await gm(g, caption, reply_markup=kb)


async def chat_admin(chat, uid):
    if is_admin(uid): return True
    try: return (await bot.get_chat_member(chat, uid)).status in ("administrator", "creator")
    except Exception: return False


async def is_gadmin(m: Message): return await chat_admin(m.chat.id, m.from_user.id)


GAP = F.chat.type.in_({"group", "supergroup"})


@r.message(C("game"), GAP)
async def cmd_game(m: Message):
    if m.chat.id in games: return await m.reply("O'yin allaqachon boshlangan.")
    if await need_sub(m): return
    g = G(m.chat.id, m.from_user.id); games[m.chat.id] = g
    g.task = asyncio.create_task(run_game(g))


@r.message(C("vsgame"), GAP)
async def cmd_vsgame(m: Message):
    if m.chat.id in games: return await m.reply("O'yin allaqachon boshlangan.")
    if await need_sub(m): return
    g = G(m.chat.id, m.from_user.id, vs=True); games[m.chat.id] = g
    g.task = asyncio.create_task(run_game(g))


def enough(g):
    if g.vs:
        rc = sum(1 for d in g.p.values() if d["t"] == "r"); bc = len(g.p) - rc
        return rc >= MINVS and bc >= MINVS
    return len(g.p) >= MINP


@r.message(C("start"), GAP)
async def cmd_gstart(m: Message):
    g = games.get(m.chat.id)
    if not g or g.state != "reg": return await m.reply("Avval /game orqali o'yin yarating.")
    if not enough(g):
        return await m.reply(f"Har bir jamoada kamida {MINVS} ta o'yinchi kerak." if g.vs else f"Kamida {MINP} ta o'yinchi kerak.")
    g.start_ev.set()


@r.message(C("stop"), GAP)
async def cmd_stop(m: Message):
    g = games.get(m.chat.id)
    if not g or not await is_gadmin(m): return
    if g.task: g.task.cancel()
    await m.answer("🛑 O'yin to'xtatildi. Qaytadan boshlash uchun /game")


@r.message(C("leave"), GAP)
async def cmd_leave(m: Message):
    g = games.get(m.chat.id)
    if g and g.state == "reg" and m.from_user.id in g.p: g.p.pop(m.from_user.id); await upd_reg(g); await m.reply("Siz o'yindan chiqdingiz.")


# ---- Sozlamalar: shaxsiy chatga yuboriladi ----
async def set_view(uid, chat, page):
    try: title = (await bot.get_chat(chat)).title or str(chat)
    except Exception: title = str(chat)
    g = Gr(chat); off = goff(chat); b = InlineKeyboardBuilder()
    if page == "m":
        for k, (n, mx) in MODES.items():
            if k != "vs": b.button(text=("✅ " if g["mode"] == k else "") + f"{n} ({mx})", callback_data=f"cm:{chat}:{k}")
        b.button(text=tt(uid, "back"), callback_data=f"cs:{chat}:b"); b.adjust(2, 2, 1)
        return tt(uid, "set_modes_title"), b.as_markup()
    if page == "r":
        ks = [k for k, _, _, _ in RL if k != "qoy"]
        for k in ks: b.button(text=("❌ " if k in off else "✅ ") + rname(k, uid), callback_data=f"cr:{chat}:{k}")
        b.button(text=tt(uid, "set_on_all"), callback_data=f"ca:{chat}:1")
        b.button(text=tt(uid, "set_off_all"), callback_data=f"ca:{chat}:0")
        b.button(text=tt(uid, "back"), callback_data=f"cs:{chat}:b")
        b.adjust(*([2] * (len(ks) // 2) + ([1] if len(ks) % 2 else []) + [1]))
        return tt(uid, "set_roles_title"), b.as_markup()
    b.button(text=f"{tt(uid, 'set_mode')}: {MODES[g['mode']][0]}", callback_data=f"cs:{chat}:m")
    b.button(text=tt(uid, "set_roles"), callback_data=f"cs:{chat}:r")
    b.button(text=tt(uid, "set_sub"), url=sub_link(chat)); b.adjust(1)
    return tt(uid, "set_title", title=esc(title), mode=MODES[g["mode"]][0]), b.as_markup()


@r.message(C("sozlamalar"), GAP)
async def cmd_settings(m: Message):
    if not await is_gadmin(m): return
    uid = m.from_user.id; txt, kb = await set_view(uid, m.chat.id, "b")
    if await pm(uid, txt, reply_markup=kb): await m.reply("⚙️ Sozlamalar shaxsiy chatga yuborildi.")
    else: await m.reply("⚠️ Sozlamalarni yuborib bo'lmadi. Avval botga o'tib /start bosing.", reply_markup=link_kb())


@r.callback_query(F.data.startswith(("cs:", "cm:", "cr:", "ca:")))
async def cb_cfg(c: CallbackQuery):
    p, ch, a = c.data.split(":"); chat = int(ch); uid = c.from_user.id
    if not await chat_admin(chat, uid): return await c.answer("Faqat adminlar", show_alert=True)
    page = "b"
    if p == "cs": page = a
    elif p == "cm": gset(chat, mode=a); page = "m"
    elif p == "cr":
        off = goff(chat); off.symmetric_difference_update({a}); gset(chat, off=",".join(sorted(off))); page = "r"
    elif p == "ca":
        gset(chat, off="" if a == "1" else ",".join(k for k, _, _, _ in RL if k != "qoy")); page = "r"
    txt, kb = await set_view(uid, chat, page)
    try: await c.message.edit_text(txt, reply_markup=kb)
    except Exception: pass
    await c.answer()


@r.message(C("tep"), GAP)
async def cmd_tep(m: Message):
    g = games.get(m.chat.id)
    if not g or g.state == "reg" or not await is_gadmin(m): return
    n = num(m); al = g.alive()
    if 1 <= n <= len(al):
        u = al[n - 1]; g.p[u]["a"] = False
        await m.answer(f"{esc(g.p[u]['n'])} o'yin admin tomonidan chiqarildi. U edi {rname(g.p[u]['r'])}")


def reg_text(g):
    if g.vs:
        def tm(t_):
            ns = [esc(d["n"]) for d in g.p.values() if d["t"] == t_]
            return ", ".join(ns) or "—", len(ns)
        (rn, rc), (bn, bc) = tm("r"), tm("b")
        return (f"<b>⚔️ VS mode — ro'yxatdan o'tish davom etmoqda!</b>\n\n🔴 Qizil jamoa ({rc}): {rn}\n\n"
                f"🔵 Ko'k jamoa ({bc}): {bn}\n\nJami: {len(g.p)} ta\nJamoani tanlash uchun pastdagi tugmalarni bosing.")
    names = ", ".join(esc(d["n"]) for d in g.p.values()) or "—"
    return f"<b>Ro'yxatdan o'tish davom etmoqda!</b>\nRejim: {MODES[g.mode][0]}\nRo'yxatdan o'tganlar: {names}\n\nJami: {len(g.p)} ta"


async def upd_reg(g):
    if not g.regmsg: return
    b = InlineKeyboardBuilder()
    if g.vs:
        rc = sum(1 for d in g.p.values() if d["t"] == "r"); bc = len(g.p) - rc
        b.button(text=f"🔴 Qizil ({rc})", url=f"https://t.me/{BOTNAME}?start=vs{g.chat}_r")      # botga o'tadi
        b.button(text=f"🔵 Ko'k ({bc})", url=f"https://t.me/{BOTNAME}?start=vs{g.chat}_b")
    else:
        b.button(text="💡 Qo'shilish", url=f"https://t.me/{BOTNAME}?start=j{g.chat}")
    try: await g.regmsg.edit_text(reg_text(g), reply_markup=b.as_markup())
    except Exception: pass


def to_group_kb(g):
    if not g.url: return None
    b = InlineKeyboardBuilder(); b.button(text="Guruhga qaytish", url=g.url); return b.as_markup()


async def vs_join_pm(m: Message, chat, tm):
    g = games.get(chat); uid = m.from_user.id
    if not g or not g.vs or g.state != "reg" or tm not in ("r", "b"):
        return await m.answer("Kechirasiz, bu o'yinga qo'shilib bo'lmaydi!")
    kb = to_group_kb(g)
    if uid in g.p:
        if g.p[uid]["t"] == tm: return await m.answer("Siz o'yinga qo'shilib bo'ldingiz.", reply_markup=kb)
        g.p[uid]["t"] = tm
        await m.answer(f"🔄 Jamoa almashtirdingiz! ({TEAM[tm]})", reply_markup=kb); return await upd_reg(g)
    if len(g.p) >= MODES["vs"][1]: return await m.answer("O'yin to'lgan!")
    g.p[uid] = newp(m.from_user.full_name, tm)
    await m.answer(f"✅ Siz o'yinga qo'shildingiz! ({TEAM[tm]} jamoa)", reply_markup=kb)
    await upd_reg(g)


async def join_game(m: Message, chat):
    g = games.get(chat); uid = m.from_user.id
    if not g or g.state != "reg" or g.vs or len(g.p) >= MODES[g.mode][1]:
        return await m.answer("Kechirasiz, bu o'yinga qo'shilib bo'lmaydi!")
    if uid in g.p: return await m.answer("Siz o'yinga qo'shilib bo'ldingiz.", reply_markup=to_group_kb(g))
    g.p[uid] = newp(m.from_user.full_name)
    await m.answer("✅ Siz o'yinga qo'shildingiz!", reply_markup=to_group_kb(g))
    await upd_reg(g)


def assign(g):
    ids = list(g.p); random.shuffle(ids); n = len(ids); mode = g.mode; off = goff(g.chat)
    ok = lambda k: k not in off
    safe = [k for k in SAFE if ok(k)]

    def filler(): return "tinch" if ok("tinch") else (random.choice(safe) if safe else "tinch")

    roles = []
    if mode == "zombie":
        roles = ["zombi"]
        if n >= 5 and ok("komissar"): roles.append("komissar")
        if n >= 6 and ok("doktor"): roles.append("doktor")
        pool = [k for k in ZPOOL if ok(k)]; random.shuffle(pool)
        while len(roles) < n: roles.append(pool.pop() if pool and random.random() < .5 else filler())
    else:
        nm = max(1, n // 4)
        roles += [k for k in (["don"] + ["mafia"] * (nm - 1)) if ok(k)]
        if n >= 5 and ok("komissar"): roles.append("komissar")
        if n >= 6 and ok("doktor"): roles.append("doktor")
        if n >= 7 and ok("manyak"): roles.append("manyak")
        ex = EXCL.get(mode, set())
        pool = [k for k, _, _, _ in RL if k not in CORE and k not in ex and ok(k)]; random.shuffle(pool)
        while len(roles) < n:
            if pool and (mode == "mega" or random.random() < .5): roles.append(pool.pop())
            elif mode == "mega": roles.append(random.choice(safe) if safe else "tinch")
            else: roles.append(filler())
    roles = roles[:n]; random.shuffle(roles)
    for u, rl in zip(ids, roles): g.p[u]["r"] = rl
    if mode != "zombie":                       # faol rollar 100% tushadi va ro'yxatdan o'chadi
        for u in ids:
            lst = aroles(U(u)); pick = next((x for x in lst if x in RD and x not in off and x != "zombi"), None)
            if pick: g.p[u]["r"] = pick; lst.remove(pick); S(u, arole=",".join(lst))
    for d in g.p.values(): d["r0"] = d["r"]


def assign_vs(g):
    for tm in "rb":
        ids = [u for u, d in g.p.items() if d["t"] == tm]; random.shuffle(ids)
        for i, u in enumerate(ids): g.p[u]["r"] = "doktor" if i == 0 and len(ids) >= 3 else "jangchi"
    for d in g.p.values(): d["r0"] = d["r"]


async def send_roles(g):
    bad = []
    for u, d in g.p.items():
        rl = d["r"]; txt = f"{tt(u, 'you_are', role=rname(rl, u))}\n\n{rdesc(rl, u)}"
        mates = []
        if g.vs:
            txt = f"{TEAM[d['t']]}\n\n" + txt
            mates = [(x, y) for x, y in g.p.items() if y["t"] == d["t"] and x != u]
        elif rl in MAF:
            mates = [(x, y) for x, y in g.p.items() if y["r"] in MAF and x != u]
        elif rl in ("komissar", "serjant"):
            mates = [(x, y) for x, y in g.p.items() if y["r"] in ("komissar", "serjant") and x != u]
        if mates:
            txt += f"\n\n<b>{tt(u, 'mates')}</b>\n" + "\n".join(f"{esc(y['n'])} - {rname(y['r'], u)}" for x, y in mates)
        if not await pm(u, txt): bad.append(esc(d["n"]))
    if bad: await gm(g, "⚠️ Quyidagi o'yinchilarga xabar yuborib bo'lmadi (botga /start bosing): " + ", ".join(bad))


async def run_game(g):
    try:
        g.url = await group_url(g.chat)
        g.regmsg = await gm(g, reg_text(g)); await upd_reg(g)
        if g.regmsg:
            try: await bot.pin_chat_message(g.chat, g.regmsg.message_id, disable_notification=False)
            except Exception: pass
        try: await asyncio.wait_for(g.start_ev.wait(), REG_SEC)
        except asyncio.TimeoutError: pass
        if not enough(g):
            await gm(g, "O'yin bekor qilindi: o'yinchilar yetarli emas.")
            return
        g.state = "start"
        if g.regmsg:
            try: await g.regmsg.edit_reply_markup(reply_markup=None)
            except Exception: pass
        assign_vs(g) if g.vs else assign(g)
        if not g.vs and not any(d["r"] in MAF or d["r"] in ("manyak", "zombi") for d in g.p.values()):
            await gm(g, "⚠️ Mafia / yakka rollari sozlamalarda o'chirilgan — o'yin bekor qilindi. /sozlamalar orqali rollarni yoqing.")
            return
        g.t0 = time.time()
        await gm(g, f"🎮 <b>O'yin boshlandi!</b>\nMode: <b>{MODES[g.mode][0]}</b>")
        await send_roles(g)
        await asyncio.sleep(3)
        w = None
        while True:
            g.round += 1
            await night(g)
            rep = await (resolve_vs(g) if g.vs else resolve(g))
            await day_intro(g)
            await gm(g, rep)
            if (w := win(g)): break
            if g.vs: await idle_check(g)
            else:
                await seller_offers(g)
                await day(g)
                if (w := win(g)): break
                await idle_check(g)
                if (w := win(g)): break
            if g.vs and (w := win(g)): break
        await finish(g, w)
    except asyncio.CancelledError:
        pass
    except Exception:
        logging.exception("O'yin xatosi")
        await gm(g, "⚠️ O'yinda xatolik yuz berdi, o'yin to'xtatildi.")
    finally:
        games.pop(g.chat, None)
        if g.regmsg:
            try: await bot.unpin_chat_message(g.chat, g.regmsg.message_id)
            except Exception: pass


# ───────────────────────── Tun ─────────────────────────
def kb_targets(g, kinds, tgts):
    b = InlineKeyboardBuilder()
    for k, em in kinds:
        for t_ in tgts: b.button(text=f"{em} {g.idx[t_]}. {g.p[t_]['n']}", callback_data=f"na:{g.chat}:{t_}:{k}")
    b.adjust(1); return b.as_markup()


def targets(g, u, rl):
    al = g.alive(); d = g.p[u]
    if g.vs:
        return [x for x in al if g.p[x]["t"] == d["t"]] if rl == "doktor" else [x for x in al if g.p[x]["t"] != d["t"]]
    if rl == "doktor": return al
    if rl in ("don", "mafia"): return [x for x in al if g.p[x]["r"] not in ("don", "mafia")]
    if rl == "zombi": return [x for x in al if g.p[x]["r"] != "zombi"]
    return [x for x in al if x != u]


def hero_targets(g, u):
    al = g.alive()
    if g.vs: return [x for x in al if g.p[x]["t"] != g.p[u]["t"]]
    return [x for x in al if x != u]


def hero_menu(g, u):
    b = InlineKeyboardBuilder()
    if U(u)["charge"] > 0: b.button(text=tt(u, "hm_attack"), callback_data=f"hm:{g.chat}:a")
    b.button(text=tt(u, "hm_shield"), callback_data=f"hm:{g.chat}:s")
    b.button(text=tt(u, "hm_skip"), callback_data=f"hm:{g.chat}:n")
    b.adjust(1); return b.as_markup()


def done(g, uid, key):
    g.need.discard((uid, key))
    if not g.need: g.night_ev.set()


async def night(g):
    g.state = "night"; g.night = {}; g.hero = {}; g.need = set(); g.night_ev = asyncio.Event(); g.offers = {}; g.seller = {}
    for d in g.p.values(): d["act"] = False; d["shield"] = False
    al = g.alive(); g.idx = {u: i for i, u in enumerate(al, 1)}
    await gmedia(g, "night", "🌃 <b>Tun</b>\nKo'chaga faqat jasur va qo'rqmas odamlar chiqishdi. Ertalab tirik qolganlarni sanaymiz...", link_kb())
    if not g.vs:
        fl = "\n".join(FLAV[g.p[u]["r"]] for u in al if g.p[u]["r"] in FLAV)
        if fl: await gm(g, fl)
    await gm(g, f"<b>Tirik o'yinchilar:</b>\n{g.plist()}\n\nTonggacha ⏳ {NIGHT_SEC} sekund qoldi", reply_markup=link_kb())
    for u in al:
        rl = g.p[u]["r"]; acts = (ACT_VS if g.vs else ACT).get(rl)
        if acts:
            tg = targets(g, u, rl)
            if tg and await pm(u, tt(u, "night_pick"), reply_markup=kb_targets(g, acts, tg)): g.need.add((u, "r"))
        if U(u)["has_hero"]:
            if await pm(u, tt(u, "hm_prompt"), reply_markup=hero_menu(g, u)): g.need.add((u, "h"))
    try: await asyncio.wait_for(g.night_ev.wait(), NIGHT_SEC)
    except asyncio.TimeoutError: pass
    g.state = "resolving"


@r.callback_query(F.data.startswith("na:"))
async def cb_night(c: CallbackQuery):
    _, ch, tg, k = c.data.split(":"); g = games.get(int(ch)); uid, tg = c.from_user.id, int(tg)
    if not g or g.state != "night" or uid not in g.p or not g.p[uid]["a"]: return await c.answer("Kech qoldingiz!", show_alert=True)
    g.night[uid] = (k, tg); g.p[uid]["act"] = True
    await c.message.edit_text(f"✅ {esc(g.p[tg]['n'])}"); await c.answer()
    done(g, uid, "r")


@r.callback_query(F.data.startswith("hm:"))
async def cb_hero_menu(c: CallbackQuery):
    _, ch, a = c.data.split(":"); g = games.get(int(ch)); uid = c.from_user.id
    if not g or g.state != "night" or uid not in g.p or not g.p[uid]["a"]: return await c.answer("Kech qoldingiz!", show_alert=True)
    if a == "back":
        await c.message.edit_text(tt(uid, "hm_prompt"), reply_markup=hero_menu(g, uid)); return await c.answer()
    if a == "a":
        if U(uid)["charge"] <= 0: return await c.answer("Qurolda zaryad yo'q!", show_alert=True)
        b = InlineKeyboardBuilder()
        for x in hero_targets(g, uid): b.button(text=f"{g.idx[x]}. {g.p[x]['n']}", callback_data=f"hg:{g.chat}:{x}")
        b.button(text=tt(uid, "back"), callback_data=f"hm:{g.chat}:back"); b.adjust(1)
        await c.message.edit_text("🥷 →", reply_markup=b.as_markup()); return await c.answer()
    if a == "s":
        g.p[uid]["shield"] = True; g.p[uid]["act"] = True
        text = f"⚜️ Geroy himoyasi: {U(uid)['hprot']}"
    else: text = "🚷"
    await c.message.edit_text(text); await c.answer(); done(g, uid, "h")


@r.callback_query(F.data.startswith("hg:"))
async def cb_hero_hit(c: CallbackQuery):
    _, ch, tg = c.data.split(":"); g = games.get(int(ch)); uid, tg = c.from_user.id, int(tg)
    if not g or g.state != "night" or uid not in g.p or not g.p[uid]["a"] or tg not in g.p: return await c.answer("Kech qoldingiz!", show_alert=True)
    g.hero[uid] = tg; g.p[uid]["act"] = True
    await c.message.edit_text(f"🥷 → {esc(g.p[tg]['n'])}"); await c.answer(); done(g, uid, "h")


async def hero_phase(g, blocked, dead):
    P = g.p; lines = []
    for u, tg in g.hero.items():
        if u in blocked or not P[u]["a"] or not P[tg]["a"] or any(d == tg for d, _, _ in dead): continue
        ud = U(u)
        if ud["charge"] <= 0: continue
        S(u, charge=ud["charge"] - 1)
        atk = rname(P[u]["r"]); tn = esc(P[tg]["n"]); tu = U(tg)
        if tu["geroyd"] > 0 and tu["t_g"]:
            A(tg, "geroyd", -1)
            lines.append(f"🔰 {tn}, siz geroydan saqlandingiz! {atk} geroyining hujumi qaytarildi.")
            await pm_g(g, tg, "🔰 Sizga geroy bilan hujum bo'ldi, ammo geroydan himoya sizni qutqardi!")
            continue
        dmg = hero_dmg(u)
        if P[tg]["shield"] and tu["hprot"] > 0:
            ab = min(dmg, tu["hprot"]); S(tg, hprot=tu["hprot"] - ab); dmg -= ab
            if dmg <= 0:
                lines.append(f"⚜️ {tn} geroy himoyasi bilan {atk} geroyining hujumini qaytardi!"); continue
        P[tg]["hp"] = max(0, P[tg]["hp"] - dmg)
        if P[tg]["hp"] <= 0:
            dead.append((tg, "hero", u))
        else:
            lines.append(f"{tn}ga {atk} geroyi bilan hujum qildi va {dmg}% jonini oldi. Hozirda uni {P[tg]['hp']}% joni bor.")
            await pm_g(g, tg, f"🥷 Sizga geroy bilan hujum qilindi! Joningiz: {P[tg]['hp']}%")
    return lines


def death_text(g, dead):
    P = g.p; txt = ""
    for tg, how, _ in dead:
        P[tg]["a"] = False
        txt += (f"\n💀 <b>{esc(P[tg]['n'])}</b> — {rname(P[tg]['r'])} vahshiylarcha o'ldirildi. "
                f"Aytishlaricha, uni {HOW.get(how, how)} tomonidan o'ldirishgan.")
    return txt


async def last_words(g, dead):
    for tg, _, _ in dead:
        await pm(tg, "Sizni shavqatsizlarcha o'ldirishdi! So'nggi so'zingizni aytish uchun sizda 45 soniya vaqt bor.")


async def resolve(g):
    P = g.p; N = g.night
    blocked = {x for u, (k, x) in N.items() if k == "b" and P[u]["a"]}
    heal = {x for u, (k, x) in N.items() if k == "h" and u not in blocked}
    hide = {x for u, (k, x) in N.items() if k == "a" and u not in blocked}
    guard = {x: u for u, (k, x) in N.items() if k == "q" and u not in blocked}
    mines = {x: u for u, (k, x) in N.items() if k == "m" and u not in blocked}
    fooled = {x for u, (k, x) in N.items() if k == "x" and u not in blocked}
    g.immune = set(); g.wit = []
    kills, bites = [], []
    mv = [(u, x) for u, (k, x) in N.items() if k == "k" and P[u]["r"] in ("don", "mafia") and u not in blocked]
    if mv:
        pick = next((y for y in mv if P[y[0]]["r"] == "don"), random.choice(mv)); kills.append((pick[0], pick[1], "mafia"))
    for u, (k, x) in N.items():
        if u in blocked or not P[u]["a"] or x not in P: continue
        rl = P[u]["r"]
        if k == "k" and rl in ("manyak", "ubiytsa"): kills.append((u, x, rl))
        elif k == "s" and rl == "komissar": kills.append((u, x, "komissar"))
        elif k == "e":
            if P[x]["r"] in MAF: heal.add(x)
            else: kills.append((u, x, "kimyogar"))
        elif k == "t":
            if P[x]["r"] in MAF or P[x]["r"] in SOLO: kills.append((u, x, "tentak"))
            else: g.immune.add(x)
        elif k == "c":
            tr = P[x]["r"]; ud = U(x)
            if x in hide and tr in MAF: tr = "tinch"
            elif ud["hujjat"] > 0 and ud["t_d"] and tr != "tinch": A(x, "hujjat", -1); tr = "tinch"
            if x in fooled: tr = P[random.choice(g.alive())]["r"]
            await pm(u, f"🔍 {esc(P[x]['n'])} — {rname(tr, u)}")
        elif k == "j":
            tr = P[x]["r"]; side = "🤵 Mafia" if tr in MAF else ("🎭 Yakka" if tr in SOLO else "🧑🏼 Tinch")
            await pm(u, f"📰 {esc(P[x]['n'])} — {side}")
        elif k == "w":
            tr = P[x]["r"]; msg = f"👁 Donning xotini aniqladi: {esc(P[x]['n'])} — {rname(tr)}"
            for z, d in P.items():
                if d["a"] and (d["r"] in MAF): await pm(z, msg)
        elif k == "d": g.wit.append((u, x))
        elif k == "g":
            amt = random.randint(50, 250); A(x, "money", amt)
            await pm(x, f"💰 Rais sizga {amt} 💶 sovg'a qildi!"); await pm(u, f"💰 Siz {esc(P[x]['n'])} ga {amt} 💶 sovg'a qildingiz.")
        elif k == "v": g.seller[x] = u
        elif k == "f": g.fans[u] = x
        elif k == "y":
            tr = P[x]["r"]; P[u]["r"] = tr if tr in MAF else "tinch"
            await pm(u, f"🦎 Siz endi {rname(P[u]['r'], u)}!")
        elif k == "z": bites.append((u, x))
    for u, x in g.wit:
        ks = [esc(P[kl]["n"]) for kl, kt, _ in kills if kt == x]
        await pm(u, f"🍾 Siz {esc(P[x]['n'])} uyiga bordingiz va {'qotilni ko`rdingiz: ' + ', '.join(ks) if ks else 'hech narsa ko`rmadingiz'}")
    dead = []
    dead_ids = lambda: {d for d, _, _ in dead}
    for killer, tg, how in kills:
        if not P[tg]["a"] or tg in dead_ids(): continue
        tr = P[tg]["r"]; ud = U(tg)
        if tg in mines and killer not in dead_ids():
            dead.append((killer, "mine", mines[tg])); await pm_g(g, tg, "💣 Eshigingiz oldidagi minada hujumchi portladi!"); continue
        gd = guard.get(tg)
        if gd and P[gd]["a"] and gd not in dead_ids() and gd != killer:
            dead.append((gd, how, killer)); await pm_g(g, tg, "💂 Sizga hujum bo'ldi, ammo Qo'riqchi o'zini qurbon qildi!"); continue
        if tg in heal: await pm_g(g, tg, "💉 Sizga hujum bo'ldi, ammo siz qutqarildingiz!"); continue
        if tr == "omadli" and random.random() < .35: await pm_g(g, tg, "🍀 Sizga hujum bo'ldi, ammo omadingiz kuldi!"); continue
        if ud["himoya"] > 0 and ud["t_h"]: A(tg, "himoya", -1); await pm_g(g, tg, "🛡 Sizga hujum bo'ldi, ammo himoya qutqardi!"); continue
        if tr == "mergan" and how == "manyak": await pm_g(g, tg, "🎯 Manyak sizni o'ldira olmadi!"); continue
        if tr == "sehrgar":
            if random.random() < .5: await pm_g(g, tg, "🧙‍♀️ Siz hujumchini kechirdingiz va omon qoldingiz."); continue
            if P[killer]["a"] and killer not in dead_ids(): dead.append((killer, "sehrgar", tg))
        dead.append((tg, how, killer))
        if tr == "kamikaze" and P[killer]["a"] and killer not in dead_ids(): dead.append((killer, "kamikaze", tg))
        if tr == "ovchi":
            cand = [y for y in g.alive() if (P[y]["r"] in MAF or P[y]["r"] in SOLO) and y not in dead_ids() and y != tg]
            if cand: dead.append((random.choice(cand), "ovchi", tg))
    conv = []
    for u, x in bites:                                        # zombi tishlashi
        if not P[x]["a"] or P[x]["r"] == "zombi" or x in dead_ids() or x in conv: continue
        if x in heal: await pm_g(g, x, "💉 Zombi sizga hujum qildi, ammo siz qutqarildingiz!"); continue
        if U(x)["himoya"] > 0 and U(x)["t_h"]: A(x, "himoya", -1); await pm_g(g, x, "🛡 Zombi sizni tishlamoqchi bo'ldi, himoya qutqardi!"); continue
        conv.append(x)
    for x in conv:
        P[x]["r"] = "zombi"; await pm_g(g, x, "🧟 Sizni zombi tishladi va siz zombiga aylandingiz!")
    hl = await hero_phase(g, blocked, dead)
    txt = ""
    if hl: txt += "\n".join(hl) + "\n"
    if conv: txt += f"\n🧟 Zombilar ko'payib bormoqda! Bu tun {len(conv)} kishi zombiga aylandi."
    if not dead and not conv: txt += "\nBu tun hech kim o'lmadi."
    txt += death_text(g, dead)
    await last_words(g, dead)
    for u, x in list(g.fans.items()):                         # muxlis: kumiri o'lsa — manyak
        if P[u]["a"] and P[u]["r"] == "muxlis" and not P[x]["a"]:
            P[u]["r"] = "manyak"; await pm(u, "🔪 Kumiringiz o'ldirildi! Siz endi Manyaksiz va qasos olasiz."); g.fans.pop(u, None)
    if not any(d["a"] and d["r"] == "komissar" for d in P.values()):
        for u, d in P.items():
            if d["a"] and d["r"] == "serjant": d["r"] = "komissar"; await pm(u, "🕵🏻‍♂️ Siz endi Komissarsiz!"); break
    if not any(d["a"] and d["r"] == "doktor" for d in P.values()):
        for u, d in P.items():
            if d["a"] and d["r"] == "hamshira": d["r"] = "doktor"; await pm(u, "👨🏼‍⚕️ Siz endi Doktorsiz!"); break
    g.state = "talk"
    return txt.strip()


async def resolve_vs(g):
    P = g.p; N = g.night
    heal = {"r": set(), "b": set()}
    for u, (k, x) in N.items():
        if k == "h" and P[u]["a"]: heal[P[u]["t"]].add(x)
    shots = {"r": {}, "b": {}}
    for u, (k, x) in N.items():
        if k == "k" and P[u]["a"]: shots[P[u]["t"]][x] = shots[P[u]["t"]].get(x, 0) + 1
    dead = []
    for tm, sh in shots.items():
        if not sh: continue
        mx = max(sh.values()); x = random.choice([y for y, v in sh.items() if v == mx])
        if not P[x]["a"]: continue
        ud = U(x)
        if x in heal[P[x]["t"]]: await pm_g(g, x, "💉 Sizga hujum bo'ldi, ammo Doktor sizni qutqardi!"); continue
        if ud["himoya"] > 0 and ud["t_h"]: A(x, "himoya", -1); await pm_g(g, x, "🛡 Sizga hujum bo'ldi, ammo himoya qutqardi!"); continue
        dead.append((x, "vs", 0))
    hl = await hero_phase(g, set(), dead)
    txt = ""
    if hl: txt += "\n".join(hl) + "\n"
    if not dead: txt += "\nBu tun hech kim o'lmadi."
    txt += death_text(g, dead)
    await last_words(g, dead)
    g.state = "talk"
    return txt.strip()


async def day_intro(g):
    await gmedia(g, "day", f"🏙 <b>{g.round}-kun</b>\nQuyosh chiqdi, ammo tun orqasida nima bo'lganini faqat bir necha kishi biladi...", link_kb())


# ---- Sotuvchi: yarim narxdagi mahsulotlar, 10% sotuvchiga ----
async def seller_offers(g):
    for x, s_ in g.seller.items():
        if not g.p[x]["a"]: continue
        b = InlineKeyboardBuilder()
        for k, (em, p) in SELL.items(): b.button(text=f"{tt(x, 'it_' + k)} — {p} 💶", callback_data=f"sv:{g.chat}:{k}")
        b.adjust(1); g.offers[x] = s_
        await pm_g(g, x, tt(x, "seller_offer"))
        await pm(x, "👇", reply_markup=b.as_markup())


@r.callback_query(F.data.startswith("sv:"))
async def cb_seller(c: CallbackQuery):
    _, ch, k = c.data.split(":"); g = games.get(int(ch)); uid = c.from_user.id
    if not g or uid not in g.offers or g.state in ("night", "resolving"): return await c.answer("⌛️ Taklif tugagan.", show_alert=True)
    em, p = SELL[k]
    if U(uid)["money"] < p: return await c.answer(tt(uid, "no_money"), show_alert=True)
    s_ = g.offers[uid]; A(uid, "money", -p); A(uid, k, 1); A(s_, "money", p // 10)
    await pm(s_, f"🎁 {esc(c.from_user.full_name)} {tt(s_, 'it_' + k)} sotib oldi — siz {p // 10} 💶 ishladingiz!")
    await c.answer(tt(uid, "bought", n=tt(uid, "it_" + k)), show_alert=True)


# ───────────────────────── Kun / ovoz berish ─────────────────────────
def yn_kb(chat, y=0, n=0):
    b = InlineKeyboardBuilder(); b.button(text=f"👍 {y}", callback_data=f"yn:{chat}:1"); b.button(text=f"👎 {n}", callback_data=f"yn:{chat}:0")
    return b.as_markup()


async def day(g):
    al = g.alive()
    await gm(g, f"<b>Tirik o'yinchilar:</b>\n{g.plist()}\n\n💬 Muhokama vaqti ⏳ {DAY_SEC} sekund", reply_markup=link_kb())
    await asyncio.sleep(DAY_SEC)
    g.state = "vote"; g.votes = {}
    await gm(g, f"⚖️ Aybdorlarni aniqlash vaqti keldi.\nOvoz berish uchun {VOTE_SEC} sekund vaqt.", reply_markup=link_kb("🗳 Ovoz berish"))
    for u in al:
        b = InlineKeyboardBuilder()
        for x in al:
            if x != u: b.button(text=g.p[x]["n"], callback_data=f"vt:{g.chat}:{x}")
        b.button(text="⏭ O'tkazib yuborish", callback_data=f"vt:{g.chat}:0"); b.adjust(2)
        await pm(u, "Kimni osamiz?", reply_markup=b.as_markup())
    await asyncio.sleep(VOTE_SEC)
    tally = {}
    for u, x in g.votes.items():
        if x: tally[x] = tally.get(x, 0) + (2 if g.p[u]["r"] == "janob" else 1)
    if not tally:
        g.state = "post"; return await gm(g, "Hech kim ovoz bermadi. Hech kim osilmadi, arqon osilib qoldi.")
    mx = max(tally.values()); top = [x for x, v in tally.items() if v == mx]
    if len(top) > 1:
        g.state = "post"; return await gm(g, "Bahslar tugadi, arqon osilib qoldi. Hech kim osilmadi.")
    tg = top[0]; g.cand = tg; g.yn = {}; g.state = "confirm"
    await gm(g, f"⚖️ <b>{esc(g.p[tg]['n'])}</b>ni osishga rozimisiz?\nOvoz berish uchun {CONF_SEC} sekund.", reply_markup=yn_kb(g.chat))
    await asyncio.sleep(CONF_SEC)
    g.state = "post"
    y = sum(1 for v in g.yn.values() if v == 1); n = sum(1 for v in g.yn.values() if v == 0)
    head = f"<b>Ovoz berish natijalari:</b>\n{y}👍 | {n}👎\n\n"
    ud = U(tg)
    if y <= n:
        return await gm(g, head + f"Aholi fikri bo'linib, <b>{esc(g.p[tg]['n'])}</b> osilmadi.")
    if tg in g.immune:
        return await gm(g, head + f"🎲 {esc(g.p[tg]['n'])} bugun osilmaydi (Tentak himoyasi).")
    if ud["osish"] > 0 and ud["t_o"] and not g.p[tg]["osh"]:     # osishdan himoya: bir o'yinda 1 marta
        A(tg, "osish", -1); g.p[tg]["osh"] = True
        return await gm(g, head + f"⚖️ {esc(g.p[tg]['n'])} osishdan himoya tufayli qutqarildi!")
    g.p[tg]["a"] = False
    await gm(g, head + f"🪢 <b>{esc(g.p[tg]['n'])}</b> kunduzgi yig'ilishda osildi!\nU edi {rname(g.p[tg]['r'])}.")
    await pm(tg, "Sizni osib o'ldirishdi! So'nggi so'zingizni aytish uchun sizda 45 soniya vaqt bor.")
    if g.p[tg]["r"] == "suidsid": g.suid = tg
    if g.p[tg]["r"] == "kamikaze":
        vs_ = [u for u, v in g.votes.items() if v == tg and g.p[u]["a"]]
        if vs_:
            k = random.choice(vs_); g.p[k]["a"] = False
            await gm(g, f"💣 Kamikaze {esc(g.p[k]['n'])} ({rname(g.p[k]['r'])}) ni o'zi bilan olib ketdi!")
    if g.p[tg]["r"] == "ovchi":
        cand = [y for y in g.alive() if g.p[y]["r"] in MAF or g.p[y]["r"] in SOLO]
        if cand:
            k = random.choice(cand); g.p[k]["a"] = False
            await gm(g, f"🏹 Ovchi {esc(g.p[k]['n'])} ({rname(g.p[k]['r'])}) ni o'zi bilan olib ketdi!")


async def idle_check(g):
    for u, d in g.p.items():
        if not d["a"]: continue
        d["idle"] = 0 if d["act"] else d["idle"] + 1
        if d["idle"] >= 2:
            d["a"] = False
            await gm(g, f"⌛️ {esc(d['n'])} 2 kun hech narsa qilmadi va o'yindan chetlatildi! U edi {rname(d['r'])}")
            await pm(u, "⌛️ Siz 2 kun hech narsa qilmadingiz va o'yindan chetlatildingiz!")


@r.callback_query(F.data.startswith("vt:"))
async def cb_vote(c: CallbackQuery):
    _, ch, tg = c.data.split(":"); g = games.get(int(ch)); uid = c.from_user.id
    if not g or g.state != "vote" or uid not in g.p or not g.p[uid]["a"]: return await c.answer("Kech qoldingiz!", show_alert=True)
    g.votes[uid] = int(tg); g.p[uid]["act"] = True
    await c.message.edit_text("Siz ovoz berdingiz: " + (esc(g.p[int(tg)]["n"]) if int(tg) else "o'tkazib yuborildi"))
    await gm(g, f"🗳 {esc(g.p[uid]['n'])} ovoz berdi" + (f": {esc(g.p[int(tg)]['n'])}" if int(tg) else "")); await c.answer()


@r.callback_query(F.data.startswith("yn:"))
async def cb_yn(c: CallbackQuery):
    _, ch, v = c.data.split(":"); g = games.get(int(ch)); uid = c.from_user.id
    if not g or g.state != "confirm" or uid not in g.p or not g.p[uid]["a"] or uid == g.cand:
        return await c.answer("Siz ovoz bera olmaysiz!", show_alert=True)
    g.yn[uid] = int(v); g.p[uid]["act"] = True
    y = sum(1 for x in g.yn.values() if x == 1); n = sum(1 for x in g.yn.values() if x == 0)
    try: await c.message.edit_reply_markup(reply_markup=yn_kb(g.chat, y, n))
    except Exception: pass
    await c.answer("Ovozingiz qabul qilindi")


# ───────────────────────── G'alaba / yakun ─────────────────────────
def win(g):
    P = g.p; al = [d for d in P.values() if d["a"]]
    if g.vs:
        rc = sum(1 for d in al if d["t"] == "r"); bc = sum(1 for d in al if d["t"] == "b")
        if rc == 0 and bc == 0: return "draw"
        if bc == 0: return "r"
        if rc == 0: return "b"
        if g.round >= 15: return "r" if rc > bc else ("b" if bc > rc else "draw")
        return None
    if g.mode == "zombie":
        z = sum(d["r"] == "zombi" for d in al)
        if z == 0: return "tinch"
        if z >= len(al) - z: return "zombi"
        return None
    if getattr(g, "suid", None): return "suidsid"
    mf = sum(d["r"] in MAF for d in al); mn = sum(d["r"] == "manyak" for d in al)
    if mf == 0 and mn == 0: return "tinch"
    if mf == 0 and mn and len(al) <= 2: return "manyak"
    if mf and mf >= len(al) - mf: return "mafia"
    return None


async def finish(g, w):
    mins = max(1, round((time.time() - g.t0) / 60))

    def won(d):
        rl = d["r"]
        if g.vs: return w == d["t"]
        if g.mode == "zombie": return (w == "zombi" and rl == "zombi") or (w == "tinch" and rl != "zombi")
        return (w == "mafia" and rl in MAF) or (w == "manyak" and rl == "manyak") or \
               (w == "tinch" and rl not in MAF and rl not in SOLO) or (w == "suidsid" and rl == "suidsid")

    tag = {"r": "🔴 ", "b": "🔵 "}

    def fmt(d):
        s = f"{tag.get(d['t'], '') if g.vs else ''}{esc(d['n'])} — {rname(d['r0'])}"
        return s + (f" ➜ {rname(d['r'])}" if d["r"] != d["r0"] else "")

    win_l = [fmt(d) for d in g.p.values() if won(d)]
    oth_l = [fmt(d) for d in g.p.values() if not won(d)]
    txt = "<b>O'yin tugadi!</b>\n\n"
    if g.vs and w == "draw": txt += "🤝 Durang!\n\n"
    if win_l: txt += "<b>G'olib bo'lgan o'yinchilar:</b>\n" + "\n".join(win_l) + "\n\n"
    if oth_l: txt += "<b>Qolgan o'yinchilar ro'yhati:</b>\n" + "\n".join(oth_l) + "\n\n"
    txt += f"O'yin vaqti: {mins} minut"
    await gm(g, txt)
    now = int(time.time())
    for u, d in g.p.items():
        wn = won(d)
        ball = random.randint(50, 150) if wn else -random.randint(10, 50)
        A(u, "games", 1); A(u, "money", 130 if wn else 40)
        if wn: A(u, "wins", 1)
        S(u, points=max(0, U(u)["points"] + ball))
        db.execute("INSERT INTO pts_log(uid,ball,ts) VALUES(?,?,?)", (u, ball, now)); db.commit()
        await pm(u, f"🏁 O'yin tugadi.\nSizga 💶 {130 if wn else 40}, {abs(ball)} ball {'🎯 berildi!' if wn else '🎯 ayirildi!'}")


# ───────────────────────── Admin panel (faqat ADMIN_ID) ─────────────────────────
BIG = 10 ** 9


def admin_kb():
    b = InlineKeyboardBuilder()
    for t_, d in [("💶 Cheksiz pul", "ad:money"), ("💎 Cheksiz olmos", "ad:dia"), ("💠 Cheksiz NightCoin", "ad:nc"),
                  ("🛡 Barcha buyumlar +99", "ad:items"), ("🥷 Geroy + 38-daraja", "ad:hero"), ("👑 VIP Promax (365 kun)", "ad:vip"),
                  ("📊 Statistika", "ad:stat")]: b.button(text=t_, callback_data=d)
    b.adjust(2); return b.as_markup()


@r.message(Command("admin"))
async def cmd_admin(m: Message):
    if not is_admin(m.from_user.id): return
    await m.answer("🛠 <b>Admin panelingiz</b>\n\nBuyruqlar:\n<code>/addmoney [id] miqdor</code>\n<code>/adddiamond [id] miqdor</code>\n"
                   "<code>/addncoin [id] miqdor</code>\n<code>/blok id</code> / <code>/unblok id</code>\n<code>/broadcast matn</code>\n"
                   "(id yozilmasa — o'zingizga)", reply_markup=admin_kb())


@r.callback_query(F.data.startswith("ad:"))
async def cb_admin(c: CallbackQuery):
    if not is_admin(c.from_user.id): return await c.answer("Ruxsat yo'q", show_alert=True)
    a, uid = c.data[3:], c.from_user.id
    if a == "money": S(uid, money=BIG)
    if a == "dia": S(uid, diamonds=BIG)
    if a == "nc": S(uid, ncoin=BIG)
    if a == "items": S(uid, himoya=99, hujjat=99, osish=99, geroyd=99)
    if a == "hero": S(uid, has_hero=1, points=40700, hprot=300, charge=10)
    if a == "vip": S(uid, vip=4, vip_until=int(time.time() + 365 * 86400)); A(uid, "boosts", 1)
    if a == "stat":
        n = db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        return await c.answer(f"Foydalanuvchilar: {n}\nAktiv o'yinlar: {len(games)}", show_alert=True)
    await c.answer("✅ Bajarildi", show_alert=True)


async def admin_add(m: Message, f):
    if not is_admin(m.from_user.id): return
    p = (m.text or "").split()[1:]
    if not p or not p[-1].lstrip("-").isdigit(): return await m.reply("Foydalanish: /buyruq [id] miqdor")
    tid = int(p[0]) if len(p) > 1 else m.from_user.id
    A(tid, f, int(p[-1])); await m.reply(f"✅ {tid}: {f} {int(p[-1]):+d}")


@r.message(Command("addmoney"))
async def a1(m: Message): await admin_add(m, "money")


@r.message(Command("adddiamond"))
async def a2(m: Message): await admin_add(m, "diamonds")


@r.message(Command("addncoin"))
async def a3(m: Message): await admin_add(m, "ncoin")


@r.message(Command("blok"))
async def blok(m: Message):
    if not is_admin(m.from_user.id): return
    p = (m.text or "").split()
    tid = int(p[1]) if len(p) > 1 and p[1].isdigit() else (m.reply_to_message.from_user.id if m.reply_to_message else 0)
    if not tid or tid in ADMIN_IDS: return await m.reply("Foydalanish: /blok id")
    u = U(tid)
    if u["blocked"]: return await m.reply("Bu foydalanuvchi allaqachon bloklangan.")
    snap = {c_: u[c_] for c_ in COLS}
    snap["heroes"] = [dict(x) for x in db.execute("SELECT name,points,hprot,charge FROM heroes WHERE uid=?", (tid,))]
    db.execute("INSERT OR REPLACE INTO bans(id,snap) VALUES(?,?)", (tid, json.dumps(snap)))
    db.execute("DELETE FROM heroes WHERE uid=?", (tid,)); db.commit()
    S(tid, blocked=1, **{c_: ("" if isinstance(u[c_], str) else 0) for c_ in COLS})
    await m.reply(f"🚫 {esc(u['name'])} ({tid}) botdan ban qilindi. Akkaunti 0 qilindi (/unblok bilan tiklanadi).")


@r.message(Command("unblok"))
async def unblok(m: Message):
    if not is_admin(m.from_user.id): return
    p = (m.text or "").split()
    tid = int(p[1]) if len(p) > 1 and p[1].isdigit() else (m.reply_to_message.from_user.id if m.reply_to_message else 0)
    if not tid: return await m.reply("Foydalanish: /unblok id")
    row = db.execute("SELECT snap FROM bans WHERE id=?", (tid,)).fetchone()
    S(tid, blocked=0)
    if row:
        snap = json.loads(row["snap"]); hs = snap.pop("heroes", [])
        S(tid, **{k: v for k, v in snap.items() if k in COLS})
        for h in hs: db.execute("INSERT INTO heroes(uid,name,points,hprot,charge) VALUES(?,?,?,?,?)", (tid, h["name"], h["points"], h["hprot"], h["charge"]))
        db.execute("DELETE FROM bans WHERE id=?", (tid,)); db.commit()
    await m.reply(f"✅ {esc(U(tid)['name'])} ({tid}) blokdan chiqarildi, akkaunt asl holatiga qaytarildi.")


@r.message(Command("broadcast"))
async def broadcast(m: Message):
    if not is_admin(m.from_user.id): return
    txt = (m.text or "").partition(" ")[2]; ok_ = 0
    for row in db.execute("SELECT id FROM users").fetchall():
        if await pm(row["id"], txt): ok_ += 1
        await asyncio.sleep(.05)
    await m.reply(f"Yuborildi: {ok_}")


# ───────────────────────── Matnli javoblar (nom, status, profil almashish) ─────────────────────────
@r.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def private_text(m: Message):
    uid = m.from_user.id; w = WAIT.pop(uid, None); u = U(uid)
    if w == "hname":
        if u["money"] < 800: return await m.answer(tt(uid, "h_no800"))
        A(uid, "money", -800); S(uid, hname=m.text[:24]); await m.answer(tt(uid, "h_name_ok"))
    elif w == "status":
        S(uid, name=m.text[:40]); await m.answer(tt(uid, "h_status_ok"))
    elif w == "transfer":
        if not m.text.strip().isdigit(): return await m.answer(tt(uid, "tr_digits"))
        tid = int(m.text.strip())
        if tid == uid: return await m.answer(tt(uid, "tr_self"))
        tu = db.execute("SELECT * FROM users WHERE id=?", (tid,)).fetchone()
        if not tu: return await m.answer(tt(uid, "tr_nostart"))
        if tu["games"] > 0: return await m.answer(tt(uid, "tr_new"))
        if u["diamonds"] < 5: return await m.answer(tt(uid, "tr_5"))
        PEND[uid] = tid
        b = InlineKeyboardBuilder(); b.button(text=tt(uid, "tr_yes"), callback_data="pt:y"); b.button(text=tt(uid, "tr_no"), callback_data="pt:n")
        await m.answer(tt(uid, "tr_conf", id=tid, name=esc(tu["name"] or str(tid))), reply_markup=b.as_markup())


# ───────────────────────── Web profil ─────────────────────────
WCSS = ("body{margin:0;background:#0f1722;color:#e6edf3;font-family:system-ui,Segoe UI,Arial,sans-serif}.w{max-width:760px;margin:0 auto;padding:18px}"
        "h1{font-size:24px;margin:6px 0}h2{font-size:16px;margin:22px 0 8px;color:#7fb2ff}.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}"
        ".c{background:#18222f;border-radius:12px;padding:12px;display:flex;justify-content:space-between;gap:8px}.c span{color:#9fb0c3}"
        ".l div{background:#18222f;border-radius:10px;padding:10px;margin-bottom:6px}.m{color:#9fb0c3;font-size:12px}.up{color:#6adf8a}.dn{color:#ff7b7b}")


def web_html(u):
    uid = u["id"]; lv = vlevel(u)
    card = lambda a, b: f"<div class='c'><span>{a}</span><b>{b}</b></div>"
    bal = "".join([card("💶 Dollar", n_(u["money"])), card("💎 Olmos", n_(u["diamonds"])), card("💠 NightCoin", n_(u["ncoin"]))])
    items = "".join([card("🛡 Himoya", u["himoya"]), card("📁 Hujjat", u["hujjat"]), card("⚖️ Osishdan himoya", u["osish"]), card("🔰 Geroydan himoya", u["geroyd"])])
    stat = "".join([card("🎯 G'alaba", u["wins"]), card("🎲 O'yinlar", u["games"]), card("🚀 Boost", u["boosts"])])
    ar = "".join(f"<div>{esc(rname(x))}</div>" for x in aroles(u) if x in RD) or "<div class='m'>Faol rol yo'q</div>"
    ps = pairs_of(uid)
    pr = "".join(f"<div>💞 {esc(U(x)['name'])}</div>" for x in ps) or "<div class='m'>Para yo'q</div>"
    hs = []
    if u["has_hero"]: hs.append(f"<div>🥷 {esc(u['hname'] or 'nomsiz')} — {lvl(u['points'])}-daraja, {u['points']} ball <b>(faol)</b></div>")
    for x in db.execute("SELECT * FROM heroes WHERE uid=?", (uid,)): hs.append(f"<div>🥷 {esc(x['name'] or 'nomsiz')} — {lvl(x['points'])}-daraja, {x['points']} ball</div>")
    rows = []
    for x in db.execute("SELECT * FROM tx WHERE src=? OR dst=? ORDER BY id DESC LIMIT 40", (uid, uid)):
        out = x["src"] == uid; other = x["dst"] if out else x["src"]
        icon = {"money": "💶", "diamonds": "💎"}.get(x["kind"], "🔄")
        nm = esc(U(other)["name"] or str(other)) if db.execute("SELECT 1 FROM users WHERE id=?", (other,)).fetchone() else str(other)
        amt = f"{x['amount']}" if x["kind"] != "account" else "profil"
        rows.append(f"<div><span class='{'dn' if out else 'up'}'>{'➡️ yubordi' if out else '⬅️ oldi'}</span> {icon} <b>{amt}</b> — {nm}<div class='m'>{dfmt(x['ts'])}</div></div>")
    vip = f"<div class='m'>{esc(VIPS[lv][0])}</div>" if lv else ""
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(u['name'] or '')} — Night Mafia</title><style>{WCSS}</style></head><body><div class='w'>"
            f"<h1>👤 {esc(u['name'] or str(uid))}</h1>{vip}<h2>Balans</h2><div class='g'>{bal}</div><h2>Buyumlar</h2><div class='g'>{items}</div>"
            f"<h2>Statistika</h2><div class='g'>{stat}</div><h2>🃏 Faol rollar</h2><div class='l'>{ar}</div>"
            f"<h2>👫 Paralar ({len(ps)}/{PLIM[lv]})</h2><div class='l'>{pr}</div><h2>🥷 Geroylar ({len(hs)}/{HLIM[lv]})</h2><div class='l'>{''.join(hs) or '<div class=m>Geroy yo`q</div>'}</div>"
            f"<h2>🔁 O'tkazmalar</h2><div class='l'>{''.join(rows) or '<div class=m>O`tkazmalar yo`q</div>'}</div></div></body></html>")


async def web_profile(req):
    u = db.execute("SELECT * FROM users WHERE web=?", (req.match_info["tok"],)).fetchone()
    if not u: return web.Response(text="Profil topilmadi", status=404)
    return web.Response(text=web_html(u), content_type="text/html", charset="utf-8")


async def web_root(req): return web.Response(text="Night Mafia ✅")


async def start_web():
    app = web.Application()
    app.router.add_get("/", web_root)
    app.router.add_get("/profile/{tok}/", web_profile)
    app.router.add_get("/profile/{tok}", web_profile)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
    logging.info("Web profil: %s", WEB_URL)


# ───────────────────────── Ishga tushirish ─────────────────────────
async def main():
    global BOTNAME
    logging.basicConfig(level=logging.INFO)
    os.makedirs("media", exist_ok=True)
    BOTNAME = (await bot.get_me()).username
    await start_web()
    BG_TASKS.append(asyncio.create_task(sub_watch()))
    gap = [("startnightmafiauzbot", "O'yinni boshlash"), ("gamenightmafiauzbot", "O'yin yaratish"),
           ("vsgamenightmafiauzbot", "Jamoaviy o'yin (VS)"), ("rolesnightmafiauzbot", "O'yin rollarini ko'rish"),
           ("leave", "O'yindan chiqish"), ("sozlamalar", "Sozlamalarni ochish"), ("stop", "O'yinni to'xtatish"),
           ("gtop", "Geroy va geroychalar reytingi"), ("top1", "Kunlik top"), ("top7", "Haftalik top"), ("top30", "Oylik top"),
           ("psend", "Guruh obunasi"), ("boost", "Guruhga premium obuna (VIP)")]
    prv = [("start", "O'yinni boshlash"), ("profile", "Profilingizni ko'rish (Shaxsiy chatda)"),
           ("roles", "O'yin rollarini ko'rish"), ("gtop", "Geroy va geroychalar reytingi"), ("language", "Tilni tanlash")]
    await bot.set_my_commands([BotCommand(command=c_, description=d) for c_, d in gap], scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands([BotCommand(command=c_, description=d) for c_, d in prv], scope=BotCommandScopeAllPrivateChats())
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())