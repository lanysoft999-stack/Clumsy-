# hosting_bot.py - Хостинг бот v16.7 (Render Disk - постоянное хранение)
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, BotCommand, MenuButtonCommands, MessageEntity
import os, sys, sqlite3, threading, time, uuid, shutil, zipfile, subprocess, signal, requests, json, logging, tempfile
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict, OrderedDict
from functools import lru_cache
import atexit

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('hosting_bot')

class MemoryCache:
    def __init__(self, max_size=500):
        self.cache = OrderedDict(); self.ttl = {}; self.max_size = max_size; self.lock = threading.Lock()
    def get(self, key):
        with self.lock:
            if key in self.cache:
                if self.ttl.get(key, 0) > time.time(): self.cache.move_to_end(key); return self.cache[key]
                else: del self.cache[key]; del self.ttl[key]
            return None
    def set(self, key, value, ttl=300):
        with self.lock:
            while len(self.cache) >= self.max_size: self.cache.popitem(last=False)
            self.cache[key] = value; self.ttl[key] = time.time() + ttl
    def delete(self, key):
        with self.lock:
            if key in self.cache: del self.cache[key]
            if key in self.ttl: del self.ttl[key]

cache = MemoryCache(max_size=500)

TOKEN = "8964647336:AAHs5cGpAuSGaXbDBeG-lmS6z0fgXIEM2rs"
VERSION = "16.7.0"
ADMIN_IDS = [314148464]
CRYPTO_TOKEN = "593773:AA2SggSE9MiTxJ6jdir8g7ufY2Cd2Pchvhu"
CRYPTO_API = "https://pay.crypt.bot/api"
SUPPORT_USERNAME = "hesers"
SUPPORT_URL = "https://t.me/hesers"

# Пути для Render с постоянным диском
BASE_DIR = "/data" if os.path.exists("/data") else os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
TEMP_DIR = os.path.join(BASE_DIR, "temp")
DATABASE_PATH = os.path.join(BASE_DIR, "bot_database.db")
CHANNEL_FILE = os.path.join(BASE_DIR, "required_channel.json")
PHOTOS_FILE = os.path.join(BASE_DIR, "category_photos.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "bot_settings.json")
for d in [SCRIPTS_DIR, LOGS_DIR, TEMP_DIR]: os.makedirs(d, exist_ok=True)

LOCATIONS = {"de": {"name": "Германия", "flag": "🇩🇪", "max_tiers": 3}, "us": {"name": "США", "flag": "🇺🇸", "max_tiers": 2}, "fi": {"name": "Финляндия", "flag": "🇫🇮", "max_tiers": 5}}

TIER_INFO = {
    "1": {"name": "Tier 1", "price_7d": 65, "cpu": "1 vCPU", "ram": "512 MB", "scripts": 3, "speed": "⚡ Базовый"},
    "2": {"name": "Tier 2", "price_7d": 100, "cpu": "2 vCPU", "ram": "1 GB", "scripts": 5, "speed": "⚡⚡ Оптимальный"},
    "3": {"name": "Tier 3", "price_7d": 140, "cpu": "3 vCPU", "ram": "2 GB", "scripts": 10, "speed": "⚡⚡⚡ Быстрый"},
    "4": {"name": "Tier 4", "price_7d": 220, "cpu": "4 vCPU", "ram": "4 GB", "scripts": 20, "speed": "🔥 Турбо"},
    "5": {"name": "Tier 5", "price_7d": 300, "cpu": "5 vCPU", "ram": "8 GB", "scripts": 999, "speed": "👑 Максимальный"},
}
DAYS_MULTIPLIER = {"7": 1, "30": 4, "90": 10}
DAYS_NAMES = {"7": "7 дней", "30": "30 дней", "90": "90 дней"}
def calc_price(tier, days): return TIER_INFO.get(tier, {}).get("price_7d", 0) * DAYS_MULTIPLIER.get(days, 1)

FREE_MAX_SCRIPTS, FREE_MAX_SIZE_MB = 3, 5
BASIC_MAX_SCRIPTS, BASIC_MAX_SIZE_MB = 3, 10
PRO_MAX_SCRIPTS, PRO_MAX_SIZE_MB = 10, 50
EXPERT_MAX_SCRIPTS, EXPERT_MAX_SIZE_MB = 999, 1024

bot_status = "running"
pending_payments, crypto_invoices, broadcast_state, upload_states, user_config_state, gift_tariff_state, chat_state = {}, {}, {}, {}, {}, {}, {}
executor = ThreadPoolExecutor(max_workers=5)
CATEGORY_PHOTOS = {"main": None, "shop": None, "hosts": None, "deposit": None, "profile": None, "support": None}
DEFAULT_SETTINGS = {"welcome_text": "🚀 <b>Добро пожаловать в Hosting Bot!</b>", "welcome_photo": None}
notified_users = {}

def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE): return json.load(open(SETTINGS_FILE, 'r', encoding='utf-8'))
    except: pass
    return DEFAULT_SETTINGS.copy()
def save_settings(s):
    try: json.dump(s, open(SETTINGS_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2); return True
    except: return False
bot_settings = load_settings()

def load_photos():
    try:
        if os.path.exists(PHOTOS_FILE): return json.load(open(PHOTOS_FILE))
    except: pass
    return CATEGORY_PHOTOS.copy()
def save_photos(d):
    try: json.dump(d, open(PHOTOS_FILE, 'w'), ensure_ascii=False, indent=2)
    except: pass
def get_photo(cat): return load_photos().get(cat)

def get_db():
    conn = sqlite3.connect(DATABASE_PATH, timeout=10); conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0.0, subscription TEXT DEFAULT 'free', subscription_expiry TIMESTAMP, free_used INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, current_tier TEXT, current_location TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS scripts (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL, container_id TEXT, status TEXT DEFAULT 'stopped', size INTEGER, docker_config TEXT DEFAULT 'free', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, type TEXT DEFAULT 'pro', days INTEGER DEFAULT 30, max_uses INTEGER DEFAULT 1, used_count INTEGER DEFAULT 0)''')
        conn.commit()

@lru_cache(maxsize=128)
def get_cached_user(uid):
    with get_db() as conn:
        row = conn.execute('SELECT * FROM users WHERE user_id=?', (uid,)).fetchone()
        if not row: return None
        user = dict(row)
    if uid in ADMIN_IDS: user['subscription'] = 'expert'; user['current_tier'] = '5'
    return user
def get_user(uid):
    cached = cache.get(f"user:{uid}")
    if cached: return cached
    user = get_cached_user(uid)
    if user: cache.set(f"user:{uid}", user, 60)
    return user
def create_user(uid, username):
    with get_db() as conn: conn.execute('INSERT OR IGNORE INTO users (user_id, username, free_used) VALUES (?,?,0)', (uid, username)); conn.commit()
    cache.delete(f"user:{uid}"); get_cached_user.cache_clear()

def check_subscription(uid):
    user = get_user(uid)
    if not user: return False
    if uid in ADMIN_IDS: return True
    if user.get('subscription_expiry'):
        try:
            if datetime.now() < datetime.fromisoformat(user['subscription_expiry']): return True
            with get_db() as conn: conn.execute('UPDATE users SET subscription=?, subscription_expiry=NULL, free_used=1, current_tier=NULL, current_location=NULL WHERE user_id=?', ('free', uid)); conn.commit()
            cache.delete(f"user:{uid}"); get_cached_user.cache_clear()
        except: pass
    return False

def get_subscription_info(uid):
    user = get_user(uid)
    if not user: return "Нет", 0, "free"
    if uid in ADMIN_IDS: return "👑 Админ", 999, "expert"
    sub = user.get('subscription', 'free')
    if user.get('subscription_expiry'):
        try:
            delta = datetime.fromisoformat(user['subscription_expiry']) - datetime.now()
            d = delta.days; h = int(delta.seconds/3600)
            if d > 0: return sub.upper(), d, sub
            if h > 0: return sub.upper(), f"{h}ч", sub
            return "Истекла", 0, 'free'
        except: pass
    if sub == 'free' and user.get('free_used',0)==0: return "Не активирован", 0, 'free'
    return "Не активна", 0, 'free'

def set_subscription(uid, plan, days=0, tier=None, location=None):
    with get_db() as conn:
        if days > 0:
            expiry = (datetime.now() + timedelta(days=days)).isoformat()
            conn.execute('UPDATE users SET subscription=?, subscription_expiry=?, free_used=1, current_tier=?, current_location=? WHERE user_id=?', (plan, expiry, tier, location, uid))
        else: conn.execute('UPDATE users SET subscription=?, subscription_expiry=NULL, free_used=1 WHERE user_id=?', ('free', uid))
        conn.commit()
    cache.delete(f"user:{uid}"); get_cached_user.cache_clear()
    notified_users.pop(uid, None)

def get_user_limits(uid):
    user = get_user(uid)
    if not user: return FREE_MAX_SCRIPTS, FREE_MAX_SIZE_MB
    if uid in ADMIN_IDS: return EXPERT_MAX_SCRIPTS, EXPERT_MAX_SIZE_MB
    tier = user.get('current_tier')
    if tier and tier in TIER_INFO: return TIER_INFO[tier]['scripts'], PRO_MAX_SIZE_MB if tier in ['3','4','5'] else BASIC_MAX_SIZE_MB
    return FREE_MAX_SCRIPTS, FREE_MAX_SIZE_MB

def count_user_scripts(uid):
    with get_db() as conn: return conn.execute('SELECT COUNT(*) FROM scripts WHERE user_id=?', (uid,)).fetchone()[0]
def get_user_scripts(uid):
    with get_db() as conn: return [dict(r) for r in conn.execute('SELECT * FROM scripts WHERE user_id=? ORDER BY created_at DESC', (uid,)).fetchall()]
def get_all_scripts():
    with get_db() as conn: return [dict(r) for r in conn.execute('SELECT * FROM scripts ORDER BY created_at DESC').fetchall()]
def get_script(sid):
    with get_db() as conn:
        row = conn.execute('SELECT * FROM scripts WHERE id=?', (sid,)).fetchone()
        return dict(row) if row else None
def add_script(sid, uid, name, path, size, dc='free'):
    with get_db() as conn: conn.execute('INSERT INTO scripts VALUES (?,?,?,?,?,?,?,?)', (sid, uid, name, path, None, 'stopped', size, dc)); conn.commit()
def update_script_status(sid, status, cid=None):
    with get_db() as conn:
        if cid: conn.execute('UPDATE scripts SET status=?, container_id=? WHERE id=?', (status, cid, sid))
        else: conn.execute('UPDATE scripts SET status=? WHERE id=?', (status, sid))
        conn.commit()
def delete_script(sid, uid=None):
    with get_db() as conn:
        if uid: conn.execute('DELETE FROM scripts WHERE id=? AND user_id=?', (sid, uid))
        else: conn.execute('DELETE FROM scripts WHERE id=?', (sid,))
        conn.commit()
def get_all_users():
    with get_db() as conn: return [dict(r) for r in conn.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()]
def check_user_limits(uid): mx, _ = get_user_limits(uid); return True if mx == 999 else count_user_scripts(uid) < mx

def activate_promo(uid, code):
    with get_db() as conn:
        p = conn.execute('SELECT * FROM promocodes WHERE code=?', (code,)).fetchone()
        if not p: return False, "Промокод не найден"
        if p['used_count'] >= p['max_uses']: return False, "Закончился"
        conn.execute('UPDATE promocodes SET used_count=used_count+1 WHERE code=?', (code,))
        conn.execute('UPDATE users SET subscription=?, subscription_expiry=?, free_used=1 WHERE user_id=?', (p['type'], (datetime.now()+timedelta(days=p['days'])).isoformat(), uid))
        conn.commit()
    cache.delete(f"user:{uid}"); get_cached_user.cache_clear()
    return True, f"{p['type'].upper()} на {p['days']} дн!"

def is_bot_blocked(uid): return False if uid in ADMIN_IDS else bot_status == "stopped"

def run_fallback(sid, path):
    for f in os.listdir(path) if os.path.isdir(path) else []:
        if f.endswith('.py'):
            try:
                p = subprocess.Popen(['python', os.path.join(path, f)], stdout=open(os.path.join(LOGS_DIR, f"{sid}.log"), 'ab'), stderr=subprocess.STDOUT, cwd=path)
                return str(p.pid), None
            except Exception as e: return None, str(e)
    return None, "Нет .py"

def stop_all():
    for s in get_all_scripts():
        if s['status'] == 'running': update_script_status(s['id'], 'stopped')

def find_py_files(d):
    py_files = []
    for r, _, fs in os.walk(d):
        for f in fs:
            if f.endswith('.py'): py_files.append(os.path.join(r, f))
    return py_files
def extract_zip(zp, et):
    try:
        with zipfile.ZipFile(zp) as z: z.extractall(et)
        return True, None
    except Exception as e: return False, str(e)
def cleanup(uid):
    d = os.path.join(TEMP_DIR, str(uid))
    if os.path.exists(d): shutil.rmtree(d, ignore_errors=True)
def get_user_stats(uid):
    scripts = get_user_scripts(uid); total = len(scripts)
    running = len([s for s in scripts if s['status']=='running']); stopped = total-running
    uptime = 100.0 if total==0 else round((running/total)*100,1)
    return {'total':total,'running':running,'stopped':stopped,'uptime':uptime}
def get_all_stats():
    scripts = get_all_scripts(); running = len([s for s in scripts if s['status']=='running']); users = get_all_users()
    return {'total_scripts':len(scripts),'running':running,'stopped':len(scripts)-running,'total_users':len(users)}

def load_channels():
    try:
        if os.path.exists(CHANNEL_FILE): return json.load(open(CHANNEL_FILE))
    except: pass
    return {"channels":[],"welcome_text":"🔒 Подпишитесь на канал!","welcome_photo":None}
def save_channels(d):
    try: json.dump(d, open(CHANNEL_FILE,'w',encoding='utf-8'), ensure_ascii=False, indent=2); return True
    except: return False
def check_subscribed(uid):
    data = load_channels(); channels = data.get("channels",[])
    if not channels or uid in ADMIN_IDS: return True
    for ch in channels:
        try:
            if bot.get_chat_member(ch['id'], uid).status in ["left","kicked"]: return False
        except: return False
    return True
def channel_keyboard():
    data = load_channels(); channels = data.get("channels",[])
    if not channels: return InlineKeyboardMarkup()
    mk = InlineKeyboardMarkup(row_width=1)
    for ch in channels: mk.add(InlineKeyboardButton(f"📢 {ch['name']}", url=ch['url']))
    mk.add(InlineKeyboardButton("✅ Я подписался", callback_data="check_sub"))
    return mk

def create_invoice(amt, desc, payload):
    try:
        r = requests.post(f"{CRYPTO_API}/createInvoice", json={"asset":"USDT","amount":str(amt),"description":desc,"payload":payload}, headers={"Crypto-Pay-API-Token":CRYPTO_TOKEN}, timeout=10).json()
        if r.get('ok'): return {'success':True,'id':r['result']['invoice_id'],'url':r['result']['bot_invoice_url']}
    except: pass
    return {'success':False}
def check_invoice(iid):
    try:
        r = requests.get(f"{CRYPTO_API}/getInvoices", params={"invoice_ids":iid}, headers={"Crypto-Pay-API-Token":CRYPTO_TOKEN}, timeout=10).json()
        if r.get('ok') and r['result']['items']: return r['result']['items'][0]['status'] == 'paid'
    except: pass
    return False

bot = telebot.TeleBot(TOKEN, parse_mode='HTML')

def setup_menu():
    try: bot.set_my_commands([BotCommand("start","🚀 Главное меню")]); bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except: pass

def user_keyboard():
    mk = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    mk.add(KeyboardButton("🛒 Магазин"), KeyboardButton("💻 Мои хосты"))
    mk.add(KeyboardButton("💳 Пополнить"), KeyboardButton("👤 Профиль"))
    mk.add(KeyboardButton("🆘 Поддержка"))
    return mk

def admin_keyboard():
    mk = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    mk.add(KeyboardButton("📊 Статистика"), KeyboardButton("👥 Пользователи"))
    mk.add(KeyboardButton("📦 Хосты"), KeyboardButton("📢 Каналы"))
    mk.add(KeyboardButton("📨 Рассылка"), KeyboardButton("🎫 Промокоды"))
    mk.add(KeyboardButton("⚙️ Настройки"))
    mk.add(KeyboardButton("🛑 СТОП" if bot_status=="running" else "🟢 СТАРТ"))
    mk.add(KeyboardButton("⏹ Всё стоп"), KeyboardButton("▶️ Всё старт"))
    return mk

def send_with_photo(uid, cat, text, markup=None, welcome_photo_id=None):
    if cat=="main" and welcome_photo_id:
        try: bot.send_photo(uid, welcome_photo_id, caption=text, reply_markup=markup); return True
        except: pass
    photo = get_photo(cat)
    if photo:
        try: bot.send_photo(uid, photo, caption=text, reply_markup=markup); return True
        except: pass
    bot.send_message(uid, text, reply_markup=markup)
    return False

def configurator_keyboard(uid):
    state = user_config_state.get(uid, {"location":None,"tier":None,"days":None})
    location, tier, days = state.get("location"), state.get("tier"), state.get("days")
    gift_mode = state.get("gift_mode", False)
    max_tier = LOCATIONS[location]['max_tiers'] if location else 5
    kb = InlineKeyboardMarkup(row_width=3)
    loc_buttons = []
    for loc_id, loc_data in LOCATIONS.items():
        prefix = "✅ " if location==loc_id else ""
        loc_buttons.append(InlineKeyboardButton(f"{prefix}{loc_data['flag']} {loc_data['name']}", callback_data=f"cfg_loc:{loc_id}"))
    kb.add(*loc_buttons)
    tier_buttons_row1, tier_buttons_row2 = [], []
    for t_id in ["1","2","3"]:
        if int(t_id) <= max_tier:
            t_data = TIER_INFO[t_id]; prefix = "✅ " if tier==t_id else ""
            tier_buttons_row1.append(InlineKeyboardButton(f"{prefix}{t_data['name']} ({t_data['price_7d']}₽)", callback_data=f"cfg_tier:{t_id}"))
    for t_id in ["4","5"]:
        if int(t_id) <= max_tier:
            t_data = TIER_INFO[t_id]; prefix = "✅ " if tier==t_id else ""
            tier_buttons_row2.append(InlineKeyboardButton(f"{prefix}{t_data['name']} ({t_data['price_7d']}₽)", callback_data=f"cfg_tier:{t_id}"))
    if tier_buttons_row1: kb.add(*tier_buttons_row1)
    if tier_buttons_row2: kb.add(*tier_buttons_row2)
    if tier:
        days_buttons = []
        for d_id, d_name in DAYS_NAMES.items():
            prefix = "✅ " if days==d_id else ""
            days_buttons.append(InlineKeyboardButton(f"{prefix}{d_name} ({calc_price(tier,d_id)}₽)", callback_data=f"cfg_days:{d_id}"))
        kb.add(*days_buttons)
    if location and tier and days:
        total = calc_price(tier, days)
        kb.add(InlineKeyboardButton(f"🎁 Подарить — {total}₽" if gift_mode else f"💰 Оплатить — {total}₽", callback_data="gift_pay" if gift_mode else "cfg_pay"))
    kb.add(InlineKeyboardButton("❌ Отмена" if gift_mode else "« В магазин", callback_data="gift_cancel" if gift_mode else "cfg_back"))
    return kb, state

def get_config_description(state):
    location, tier, days = state.get("location"), state.get("tier"), state.get("days")
    text = "📦 <b>ХОСТ-СЕРВИС</b>\n\n📍 <b>Локация:</b> "
    text += f"{LOCATIONS[location]['flag']} {LOCATIONS[location]['name']}" if location else "❌ Не выбрана"
    text += "\n━━━━━━━━━━━━━━━━━━━━━━\n⚙️ <b>Тариф:</b> "
    if tier:
        t = TIER_INFO[tier]; scripts = "∞" if t['scripts']==999 else str(t['scripts'])
        text += f"\n📦 {t['name']}: {t['ram']} RAM, {t['cpu']}\n📜 Скриптов: {scripts}\n🚀 {t['speed']}"
    else:
        text += "❌ Не выбран"
        if location: text += f"\n<i>Доступно Tier 1-{LOCATIONS[location]['max_tiers']}</i>"
    text += "\n━━━━━━━━━━━━━━━━━━━━━━\n⏳ <b>Срок:</b> "
    if tier and days: text += f"{DAYS_NAMES[days]} — {calc_price(tier,days)}₽"
    else: text += "❌ Не выбран"
    if location and tier and days: text += f"\n━━━━━━━━━━━━━━━━━━━━━━\n💰 <b>ИТОГО: {calc_price(tier,days)}₽</b>"
    text += "\n\n👇 <i>Выберите параметры:</i>"
    return text

# ========== ВСЕ ОБРАБОТЧИКИ ==========
@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.from_user.id
    if not get_user(uid): create_user(uid, message.from_user.username)
    user_config_state.pop(uid,None); gift_tariff_state.pop(uid,None)
    if not check_subscribed(uid):
        data = load_channels(); wp = data.get('welcome_photo'); wt = data.get('welcome_text','🔒 Подпишитесь на канал!')
        if wp:
            try: bot.send_photo(uid, wp, caption=wt, reply_markup=channel_keyboard())
            except: bot.send_message(uid, wt, reply_markup=channel_keyboard())
        else: bot.send_message(uid, wt, reply_markup=channel_keyboard())
        return
    settings = load_settings(); welcome_photo = settings.get('welcome_photo')
    if uid in ADMIN_IDS:
        s = get_all_stats()
        bot.send_message(uid, f"👑 <b>АДМИН</b>\n\n👥 {s['total_users']}\n📦 {s['total_scripts']} (🟢{s['running']})\n\n👇 Действие:", reply_markup=admin_keyboard())
        return
    if bot_status=="stopped": bot.send_message(uid, "🔴 Бот остановлен!"); return
    if not check_subscription(uid):
        mk = InlineKeyboardMarkup(); mk.add(InlineKeyboardButton("🛒 В магазин", callback_data="shop_configurator"))
        bot.send_message(uid, "🚀 <b>Hosting Bot</b>\n\n⚠️ Активируйте тариф!\n\n🇩🇪 Tier 1-3 | 🇺🇸 Tier 1-2 | 🇫🇮 Tier 1-5", reply_markup=mk)
        return
    stats = get_user_stats(uid)
    txt = f"📊 <b>СТАТИСТИКА:</b>\n✅ Аптайм: {stats['uptime']}%\n🟢 Запущено: {stats['running']}\n🔴 Упало: {stats['stopped']}\n\n👇 <b>Действие:</b>"
    if welcome_photo:
        try: bot.send_photo(uid, welcome_photo, caption=txt, reply_markup=user_keyboard())
        except: bot.send_message(uid, txt, reply_markup=user_keyboard())
    else: send_with_photo(uid, "main", txt, user_keyboard(), welcome_photo)

@bot.message_handler(func=lambda m: m.text == "🛒 Магазин")
def shop_menu(message):
    uid = message.from_user.id
    if is_bot_blocked(uid): bot.send_message(uid, "🔴"); return
    user_config_state.pop(uid,None)
    mk = InlineKeyboardMarkup(row_width=1); mk.add(InlineKeyboardButton("🖥 Хост-сервис", callback_data="shop_configurator"))
    send_with_photo(uid, "shop", "🛒 <b>МАГАЗИН</b>\n\n📦 <b>Хост-сервис</b> — тарифы\n\n👇 Нажмите:", mk)

@bot.callback_query_handler(func=lambda c: c.data == "shop_configurator")
def open_configurator(call):
    uid = call.from_user.id
    if is_bot_blocked(uid): bot.answer_callback_query(call.id,"🔴",show_alert=True); return
    user_config_state[uid] = {"location":None,"tier":None,"days":None,"gift_mode":False}
    kb, state = configurator_keyboard(uid)
    bot.answer_callback_query(call.id)
    try: bot.edit_message_text(get_config_description(state), call.message.chat.id, call.message.message_id, reply_markup=kb)
    except: bot.send_message(call.message.chat.id, get_config_description(state), reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cfg_loc:"))
def config_select_location(call):
    uid = call.from_user.id
    if is_bot_blocked(uid): bot.answer_callback_query(call.id,"🔴",show_alert=True); return
    loc = call.data.split(":")[1]
    if uid not in user_config_state: user_config_state[uid] = {"location":None,"tier":None,"days":None}
    user_config_state[uid]["location"] = loc; user_config_state[uid]["tier"] = None; user_config_state[uid]["days"] = None
    kb, state = configurator_keyboard(uid)
    bot.answer_callback_query(call.id); bot.edit_message_text(get_config_description(state), call.message.chat.id, call.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cfg_tier:"))
def config_select_tier(call):
    uid = call.from_user.id
    if is_bot_blocked(uid): bot.answer_callback_query(call.id,"🔴",show_alert=True); return
    tier = call.data.split(":")[1]
    if uid not in user_config_state: user_config_state[uid] = {"location":None,"tier":None,"days":None}
    user_config_state[uid]["tier"] = tier; user_config_state[uid]["days"] = None
    kb, state = configurator_keyboard(uid)
    bot.answer_callback_query(call.id); bot.edit_message_text(get_config_description(state), call.message.chat.id, call.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cfg_days:"))
def config_select_days(call):
    uid = call.from_user.id
    if is_bot_blocked(uid): bot.answer_callback_query(call.id,"🔴",show_alert=True); return
    days = call.data.split(":")[1]
    if uid not in user_config_state: user_config_state[uid] = {"location":None,"tier":None,"days":None}
    user_config_state[uid]["days"] = days
    kb, state = configurator_keyboard(uid)
    bot.answer_callback_query(call.id); bot.edit_message_text(get_config_description(state), call.message.chat.id, call.message.message_id, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "cfg_pay")
def config_pay(call):
    uid = call.from_user.id
    if is_bot_blocked(uid): bot.answer_callback_query(call.id,"🔴",show_alert=True); return
    state = user_config_state.get(uid)
    if not state or not state['location'] or not state['tier'] or not state['days']: bot.answer_callback_query(call.id,"❌ Выберите все!"); return
    tier, days, location = state['tier'], state['days'], state['location']
    total = calc_price(tier, days)
    user = get_user(uid); balance = user.get('balance',0) if user else 0
    mk = InlineKeyboardMarkup(row_width=1)
    if balance >= total: mk.add(InlineKeyboardButton(f"💳 Оплатить с баланса ({balance}₽)", callback_data=f"cfg_dopay:balance"))
    else: mk.add(InlineKeyboardButton(f"💳 Недостаточно ({balance}₽/{total}₽)", callback_data="noop"))
    mk.add(InlineKeyboardButton("« Назад", callback_data="shop_configurator"))
    bot.answer_callback_query(call.id)
    bot.edit_message_text(f"🧾 <b>ПОДТВЕРЖДЕНИЕ</b>\n\n📍 {LOCATIONS[location]['name']}\n📦 {TIER_INFO[tier]['name']}\n📅 {DAYS_NAMES[days]}\n💰 {total}₽\n💳 Баланс: {balance}₽\n\n👇 Оплата:", call.message.chat.id, call.message.message_id, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cfg_dopay:"))
def config_do_payment(call):
    uid = call.from_user.id
    if is_bot_blocked(uid): bot.answer_callback_query(call.id,"🔴",show_alert=True); return
    state = user_config_state.get(uid,{}); tier = state.get('tier','1'); days = state.get('days','7'); location = state.get('location','de')
    total = calc_price(tier, days); bot.answer_callback_query(call.id)
    user = get_user(uid); balance = user.get('balance',0) if user else 0
    if balance < total: bot.send_message(uid, f"❌ Баланс: {balance}₽"); return
    with get_db() as conn: conn.execute('UPDATE users SET balance=balance-? WHERE user_id=?', (total, uid)); conn.commit()
    cache.delete(f"user:{uid}"); get_cached_user.cache_clear()
    days_int = 7 if days=='7' else 30 if days=='30' else 90
    sub_type = 'basic' if tier in ['1','2'] else 'pro' if tier in ['3','4'] else 'expert'
    set_subscription(uid, sub_type, days_int, tier, location)
    bot.send_message(uid, f"✅ <b>Оплачено!</b>\n\n📦 {TIER_INFO[tier]['name']}\n📅 {DAYS_NAMES[days]}\n💰 {total}₽\n\nТариф активирован!", reply_markup=user_keyboard())

@bot.callback_query_handler(func=lambda c: c.data == "cfg_back")
def config_back(call): shop_menu(call.message); bot.answer_callback_query(call.id)

# ========== ПОДАРОК ТАРИФА ==========
@bot.callback_query_handler(func=lambda c: c.data == "gift_tariff")
def gift_tariff_start(call):
    uid = call.from_user.id
    if is_bot_blocked(uid): bot.answer_callback_query(call.id,"🔴",show_alert=True); return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(uid, "🎁 <b>ПОДАРОК ДРУГУ</b>\n\nОтправьте @username:\nПример: <code>@friend</code>\n\n❌ /cancel")
    gift_tariff_state[uid] = {"step":"waiting_username"}
    bot.register_next_step_handler(msg, process_gift_username)

def process_gift_username(message):
    uid = message.from_user.id
    if not message.text or message.text=='/cancel': gift_tariff_state.pop(uid,None); bot.send_message(uid,"❌"); return
    username = message.text.strip().replace("@","")
    with get_db() as conn: user = conn.execute('SELECT user_id FROM users WHERE username=?', (username,)).fetchone()
    if not user: bot.send_message(uid,"❌ Не найден!"); return
    to_uid = user['user_id']
    if to_uid==uid: bot.send_message(uid,"❌ Нельзя себе!"); return
    gift_tariff_state[uid] = {"step":"choose_tariff","to_uid":to_uid,"to_username":username}
    user_config_state[uid] = {"location":None,"tier":None,"days":None,"gift_mode":True}
    kb, state = configurator_keyboard(uid)
    bot.send_message(uid, f"🎁 <b>ПОДАРОК ДЛЯ @{username}</b>\n\nВыберите тариф:\n\n👇 Нажмите:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data == "gift_cancel")
def gift_cancel(call):
    uid = call.from_user.id; gift_tariff_state.pop(uid,None); user_config_state.pop(uid,None)
    bot.answer_callback_query(call.id,"❌"); bot.edit_message_text("❌ Отменён", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data == "gift_pay")
def gift_pay(call):
    uid = call.from_user.id
    if is_bot_blocked(uid): bot.answer_callback_query(call.id,"🔴",show_alert=True); return
    state = user_config_state.get(uid); gift_info = gift_tariff_state.get(uid)
    if not state or not gift_info: bot.answer_callback_query(call.id,"❌ Сессия устарела!"); return
    tier = state.get('tier'); days = state.get('days'); location = state.get('location')
    total = calc_price(tier, days)
    user = get_user(uid); balance = user.get('balance',0) if user else 0
    if balance < total: bot.answer_callback_query(call.id,f"❌ Баланс: {balance}₽",show_alert=True); return
    to_uid = gift_info['to_uid']; to_username = gift_info['to_username']
    with get_db() as conn: conn.execute('UPDATE users SET balance=balance-? WHERE user_id=?', (total, uid)); conn.commit()
    days_int = 7 if days=='7' else 30 if days=='30' else 90
    sub_type = 'basic' if tier in ['1','2'] else 'pro' if tier in ['3','4'] else 'expert'
    set_subscription(to_uid, sub_type, days_int, tier, location)
    cache.delete(f"user:{uid}"); cache.delete(f"user:{to_uid}"); get_cached_user.cache_clear()
    gift_tariff_state.pop(uid,None); user_config_state.pop(uid,None)
    bot.answer_callback_query(call.id,"✅")
    bot.send_message(uid, f"🎁 <b>Подарок отправлен!</b>\n\n👤 @{to_username}\n📍 {LOCATIONS[location]['name']}\n📦 {TIER_INFO[tier]['name']}\n📅 {DAYS_NAMES[days]}\n💰 {total}₽", reply_markup=user_keyboard())
    try: bot.send_message(to_uid, f"🎁 <b>Вам подарили тариф!</b>\n\n📍 {LOCATIONS[location]['name']}\n📦 {TIER_INFO[tier]['name']}\n📅 {DAYS_NAMES[days]}\n\nТариф активен! /start", reply_markup=user_keyboard())
    except: pass

# ========== ПРОФИЛЬ ==========
@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def btn_profile(m):
    uid = m.from_user.id
    if is_bot_blocked(uid): bot.send_message(uid,"🔴"); return
    user = get_user(uid)
    if not user: bot.send_message(uid,"❌ /start"); return
    sub, dl, _ = get_subscription_info(uid)
    active = "✅" if check_subscription(uid) else "❌"
    ref = f"https://t.me/{bot.get_me().username}?start=ref{uid}"
    tier_info = ""; ut = user.get('current_tier')
    if ut and ut in TIER_INFO: tier_info = f"\n📦 {TIER_INFO[ut]['name']}: {TIER_INFO[ut]['ram']} | {TIER_INFO[ut]['cpu']}"
    loc_info = ""; ul = user.get('current_location')
    if ul and ul in LOCATIONS: loc_info = f"\n📍 {LOCATIONS[ul]['flag']} {LOCATIONS[ul]['name']}"
    expiry_info = ""
    if user.get('subscription_expiry'):
        try:
            delta = datetime.fromisoformat(user['subscription_expiry']) - datetime.now()
            d = delta.days; h = int(delta.seconds/3600)
            if d>0: expiry_info = f"\n⏳ {d} дн."
            elif h>0: expiry_info = f"\n⏳ {h} ч."
        except: pass
    text = f"👤 <b>ЛИЧНЫЙ КАБИНЕТ</b>\n\n🆔 <code>{uid}</code>\n💰 {user.get('balance',0)} ₽\n━━━━━━━━━━━━━━━━━━━━━━\n📋 <b>ПОДПИСКА</b>\n📊 {active} {sub}{tier_info}{loc_info}{expiry_info}\n━━━━━━━━━━━━━━━━━━━━━━\n🔗 <code>{ref}</code>"
    mk = InlineKeyboardMarkup(row_width=1)
    mk.add(InlineKeyboardButton("🎁 Подарить тариф другу", callback_data="gift_tariff"), InlineKeyboardButton("🎁 Промокод", callback_data="profile_promo"))
    send_with_photo(uid, "profile", text, mk)

@bot.callback_query_handler(func=lambda c: c.data == "profile_promo")
def profile_promo(call):
    uid = call.from_user.id
    if is_bot_blocked(uid): bot.answer_callback_query(call.id,"🔴"); return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(uid, "🎁 Введите промокод:\n❌ /cancel")
    bot.register_next_step_handler(msg, process_promo_code)

def process_promo_code(message):
    uid = message.from_user.id
    if not message.text or message.text=='/cancel': bot.send_message(uid,"❌"); return
    success, msg = activate_promo(uid, message.text.strip().upper())
    bot.send_message(uid, f"{'✅' if success else '❌'} {msg}")

# ========== ХОСТЫ ==========
@bot.message_handler(func=lambda m: m.text == "💻 Мои хосты")
def btn_hosts(m):
    uid = m.from_user.id
    if is_bot_blocked(uid) or not check_subscription(uid): bot.send_message(uid,"❌"); return
    scripts = get_user_scripts(uid)
    if not scripts: bot.send_message(uid,"😔 Нет хостов."); return
    text = f"💻 <b>Хосты ({len(scripts)})</b>\n\n"
    mk = InlineKeyboardMarkup(row_width=3)
    for i, s in enumerate(scripts,1):
        st = "🟢" if s['status']=='running' else "🔴"; sz = s['size']/(1024*1024) if s['size'] else 0
        text += f"{i}. {st} {s['name']} ({sz:.1f}МБ)\n"
        mk.add(InlineKeyboardButton("⏹", callback_data=f"sc:stop:{s['id']}"), InlineKeyboardButton("📄", callback_data=f"sc:log:{s['id']}"), InlineKeyboardButton("🗑", callback_data=f"sc:del:{s['id']}"))
    send_with_photo(uid, "hosts", text, mk)

# ========== ПОПОЛНЕНИЕ ==========
@bot.message_handler(func=lambda m: m.text == "💳 Пополнить")
def btn_deposit(m):
    uid = m.from_user.id
    if is_bot_blocked(uid): bot.send_message(uid,"🔴"); return
    mk = InlineKeyboardMarkup(row_width=1)
    mk.add(InlineKeyboardButton("💰 СБП", callback_data="dep_rub"), InlineKeyboardButton("💎 Crypto", callback_data="dep_crypto"), InlineKeyboardButton("⭐ Stars", callback_data="dep_stars"))
    send_with_photo(uid, "deposit", "💳 <b>ПОПОЛНЕНИЕ</b>\n\n👇 Выберите:", mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dep_"))
def deposit_method(call):
    uid = call.from_user.id
    if is_bot_blocked(uid): bot.answer_callback_query(call.id,"🔴"); return
    method = call.data.replace("dep_",""); bot.answer_callback_query(call.id)
    if method=="rub": msg = bot.send_message(uid,"💰 Сумма (мин 50₽):"); bot.register_next_step_handler(msg, process_deposit_rub)
    elif method=="crypto": msg = bot.send_message(uid,"💎 Сумма (мин $1):"); bot.register_next_step_handler(msg, process_deposit_crypto)
    elif method=="stars": msg = bot.send_message(uid,"⭐ Сумма (мин 50⭐):"); bot.register_next_step_handler(msg, process_deposit_stars)

def process_deposit_rub(message):
    uid = message.from_user.id
    try: amount = int(message.text)
    except: bot.send_message(uid,"❌"); return
    if amount<50: bot.send_message(uid,"❌ Мин 50₽"); return
    pending_payments[uid] = {'type':'balance','amount':amount}
    mk = InlineKeyboardMarkup().add(InlineKeyboardButton("✅ Я оплатил", callback_data="confirm_sbp"))
    bot.send_message(uid, f"💰 СБП\n💳 <code>2202206714879132</code>\n🏦 СБЕР\n💰 {amount}₽\n📸 Скриншот:", reply_markup=mk)

def process_deposit_crypto(message):
    uid = message.from_user.id
    try: amount = float(message.text.replace(',','.'))
    except: bot.send_message(uid,"❌"); return
    if amount<1: bot.send_message(uid,"❌ Мин $1"); return
    r = create_invoice(amount, "Пополнение", f"bal_{uid}_{amount}")
    if r['success']: crypto_invoices[r['id']] = {'uid':uid,'type':'balance','amount':amount}; mk = InlineKeyboardMarkup().add(InlineKeyboardButton("💎 Оплатить", url=r['url'])); bot.send_message(uid, f"💎 ${amount:.2f}", reply_markup=mk)
    else: bot.send_message(uid,"❌ Ошибка")

def process_deposit_stars(message):
    uid = message.from_user.id
    if not message.text.isdigit() or int(message.text)<50: bot.send_message(uid,"❌ Мин 50⭐"); return
    amount = int(message.text)
    bot.send_invoice(uid, "Пополнение", f"+{amount}⭐", f"bal_stars_{amount}", "", "XTR", [{"label":f"+{amount}⭐","amount":amount}])

@bot.callback_query_handler(func=lambda c: c.data == "confirm_sbp")
def confirm_sbp(call):
    if call.from_user.id not in pending_payments: bot.answer_callback_query(call.id,"❌"); return
    bot.answer_callback_query(call.id); bot.send_message(call.message.chat.id, "📸 Скриншот:")

# ========== ПОДДЕРЖКА С ЧАТОМ ==========
@bot.message_handler(func=lambda m: m.text == "🆘 Поддержка")
def btn_support(m):
    uid = m.from_user.id
    if is_bot_blocked(uid): bot.send_message(uid,"🔴"); return
    text = "🆘 <b>ПОДДЕРЖКА</b>\n\nВы можете написать администратору прямо здесь.\nОтправьте текст, фото, стикер или документ — админ вам ответит.\n\n📌 <i>Опишите вашу проблему или вопрос:</i>"
    mk = InlineKeyboardMarkup(row_width=1)
    mk.add(InlineKeyboardButton("💬 Написать админу", callback_data="chat_to_admin"), InlineKeyboardButton("📞 Telegram", url=SUPPORT_URL))
    send_with_photo(uid, "support", text, mk)

@bot.callback_query_handler(func=lambda c: c.data == "chat_to_admin")
def chat_to_admin(call):
    uid = call.from_user.id
    if is_bot_blocked(uid): bot.answer_callback_query(call.id,"🔴",show_alert=True); return
    chat_state[uid] = True
    bot.answer_callback_query(call.id, "✏️ Отправьте сообщение (текст/фото/стикер):")
    msg = bot.send_message(uid, "💬 <b>ЧАТ С АДМИНОМ</b>\n\nОтправьте ваше сообщение.\nМожно отправить текст, фото, стикер или документ.\n\n❌ /cancel для отмены")
    bot.register_next_step_handler(msg, process_chat_message)

def process_chat_message(message):
    uid = message.from_user.id
    if message.text and message.text == '/cancel': chat_state.pop(uid, None); bot.send_message(uid, "❌ Чат закрыт", reply_markup=user_keyboard()); return
    if not message.text and not message.photo and not message.sticker and not message.document: bot.send_message(uid, "❌ Отправьте текст, фото, стикер или документ!"); bot.register_next_step_handler(message, process_chat_message); return
    user = get_user(uid); username = f"@{user.get('username', uid)}" if user else f"#{uid}"
    for aid in ADMIN_IDS:
        try:
            mk = InlineKeyboardMarkup(row_width=1); mk.add(InlineKeyboardButton(f"✉️ Ответить {username}", callback_data=f"reply_to:{uid}"))
            if message.text: bot.send_message(aid, f"📩 <b>СООБЩЕНИЕ</b>\n\n👤 {username}\n🆔 <code>{uid}</code>\n📋 {get_subscription_info(uid)[0]}\n\n💬 {message.text}", reply_markup=mk)
            elif message.photo: bot.send_photo(aid, message.photo[-1].file_id, caption=f"📩 <b>ФОТО</b>\n👤 {username}\n🆔 <code>{uid}</code>\n💬 {message.caption or ''}", reply_markup=mk)
            elif message.sticker: bot.send_sticker(aid, message.sticker.file_id); bot.send_message(aid, f"📩 <b>СТИКЕР</b>\n👤 {username}\n🆔 <code>{uid}</code>", reply_markup=mk)
            elif message.document: bot.send_document(aid, message.document.file_id, caption=f"📩 <b>ДОКУМЕНТ</b>\n👤 {username}\n🆔 <code>{uid}</code>\n💬 {message.caption or ''}", reply_markup=mk)
        except Exception as e: logger.error(f"Chat error: {e}")
    chat_state.pop(uid, None)
    bot.send_message(uid, "✅ <b>Отправлено!</b>\nАдминистратор ответит вам в ближайшее время.", reply_markup=user_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("reply_to:"))
def reply_to_user(call):
    if call.from_user.id not in ADMIN_IDS: return
    to_uid = int(call.data.split(":")[1]); bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"✉️ <b>ОТВЕТ #{to_uid}</b>\n\nОтправьте ответ (текст/фото/стикер):\n❌ /cancel")
    bot.register_next_step_handler(msg, lambda m: send_reply(m, to_uid))

def send_reply(message, to_uid):
    if message.text and message.text == '/cancel': bot.send_message(message.chat.id, "❌ Отменено"); return
    if not message.text and not message.photo and not message.sticker and not message.document: bot.send_message(message.chat.id, "❌ Отправьте текст, фото, стикер или документ!"); bot.register_next_step_handler(message, lambda m: send_reply(m, to_uid)); return
    try:
        header = "📩 <b>ОТВЕТ АДМИНИСТРАТОРА</b>\n\n"; footer = "\n\n💬 <i>Нужна помощь? Напишите снова через «🆘 Поддержка»</i>"
        if message.text: bot.send_message(to_uid, f"{header}{message.text}{footer}", reply_markup=user_keyboard())
        elif message.photo: bot.send_photo(to_uid, message.photo[-1].file_id, caption=f"{header}{message.caption or ''}{footer}", reply_markup=user_keyboard())
        elif message.sticker: bot.send_sticker(to_uid, message.sticker.file_id); bot.send_message(to_uid, f"{header}Стикер от администратора{footer}", reply_markup=user_keyboard())
        elif message.document: bot.send_document(to_uid, message.document.file_id, caption=f"{header}{message.caption or ''}{footer}", reply_markup=user_keyboard())
        bot.send_message(message.chat.id, f"✅ Ответ отправлен #{to_uid}!")
    except Exception as e: bot.send_message(message.chat.id, f"❌ {e}")

# ========== АДМИН-ПАНЕЛЬ ==========
@bot.message_handler(func=lambda m: m.text == "📊 Статистика" and m.from_user.id in ADMIN_IDS)
def admin_btn_stats(m):
    u = get_all_users(); s = get_all_scripts(); r = len([x for x in s if x['status']=='running'])
    bot.send_message(m.chat.id, f"📊 <b>СТАТИСТИКА</b>\n\n👥 {len(u)}\n📦 {len(s)} (🟢{r} 🔴{len(s)-r})\n🆓 {sum(1 for x in u if x['subscription']=='free')} | 🔷 {sum(1 for x in u if x['subscription']=='basic')} | 💎 {sum(1 for x in u if x['subscription']=='pro')} | 👑 {sum(1 for x in u if x['subscription']=='expert')}")

@bot.message_handler(func=lambda m: m.text == "👥 Пользователи" and m.from_user.id in ADMIN_IDS)
def admin_btn_users(m):
    u = get_all_users()
    if not u: bot.send_message(m.chat.id,"👥 Нет"); return
    text = f"👥 <b>ПОЛЬЗОВАТЕЛИ ({len(u)})</b>\n\n"
    for i, x in enumerate(u[:10],1): text += f"{i}. <code>{x['user_id']}</code> @{x.get('username','?')}\n   💰{x.get('balance',0)}₽ | {get_subscription_info(x['user_id'])[0]}\n\n"
    mk = InlineKeyboardMarkup(row_width=1); mk.add(InlineKeyboardButton("🔍 Поиск по ID", callback_data="admin_search_user"))
    bot.send_message(m.chat.id, text, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "admin_search_user")
def admin_search_user(call):
    if call.from_user.id not in ADMIN_IDS: return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "🔍 ID пользователя:")
    bot.register_next_step_handler(msg, lambda m: search_user_by_id(m))

def search_user_by_id(message):
    if message.from_user.id not in ADMIN_IDS: return
    try:
        uid = int(message.text); user = get_user(uid)
        if not user: bot.send_message(message.chat.id,"❌ Не найден!"); return
        scripts = get_user_scripts(uid); sub, _, _ = get_subscription_info(uid)
        text = f"👤 <b>#{uid}</b> @{user.get('username','?')}\n💰 {user.get('balance',0)}₽ | 📋 {sub}\n📦 Tier: {user.get('current_tier','Нет')}\n💻 Скриптов: {len(scripts)}"
        mk = InlineKeyboardMarkup(row_width=2)
        if scripts:
            text += "\n<b>📄 Скрипты:</b>"
            for s in scripts:
                st = "🟢" if s['status']=='running' else "🔴"; sz = s['size']/(1024*1024) if s['size'] else 0
                text += f"\n{st} {s['name']} ({sz:.1f}МБ)"
                mk.add(InlineKeyboardButton(f"📥 {s['name'][:12]}", callback_data=f"adm_dl:{s['id']}"), InlineKeyboardButton(f"🗑 {s['id'][:6]}", callback_data=f"sc:del:{s['id']}"))
        mk.add(InlineKeyboardButton("📥 Скачать все", callback_data=f"adm_dl_all:{uid}"), InlineKeyboardButton("🗑 Удалить все", callback_data=f"adm_del_all:{uid}"))
        mk.add(InlineKeyboardButton("🔄 Сбросить подписку", callback_data=f"adm_reset:{uid}"))
        bot.send_message(message.chat.id, text, reply_markup=mk)
    except: bot.send_message(message.chat.id, "❌ Ошибка")

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_dl:"))
def adm_download_script(call):
    if call.from_user.id not in ADMIN_IDS: return
    sid = call.data.split(":")[1]; s = get_script(sid)
    if not s or not os.path.isdir(s['path']): bot.answer_callback_query(call.id,"❌",show_alert=True); return
    tmp_zip = os.path.join(tempfile.gettempdir(), f"{sid}.zip")
    shutil.make_archive(tmp_zip.replace('.zip',''), 'zip', s['path'])
    try:
        with open(tmp_zip,'rb') as f: bot.send_document(call.message.chat.id, f, caption=f"📦 {s['name']}\n🆔 {sid}")
        bot.answer_callback_query(call.id,"✅"); os.remove(tmp_zip)
    except: bot.answer_callback_query(call.id,"❌",show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_dl_all:"))
def adm_download_all_scripts(call):
    if call.from_user.id not in ADMIN_IDS: return
    uid = int(call.data.split(":")[1]); scripts = get_user_scripts(uid)
    if not scripts: bot.answer_callback_query(call.id,"❌",show_alert=True); return
    bot.answer_callback_query(call.id,"⏳")
    tmp_dir = tempfile.mkdtemp(); user_dir = os.path.join(tmp_dir, f"user_{uid}"); os.makedirs(user_dir, exist_ok=True)
    info_text = f"📦 <b>Скрипты #{uid}</b>\n\n"; copied = 0
    for s in scripts:
        if os.path.exists(s['path']) and os.path.isdir(s['path']):
            shutil.copytree(s['path'], os.path.join(user_dir, s['id']), dirs_exist_ok=True)
            sz = s['size']/(1024*1024) if s['size'] else 0
            info_text += f"{'🟢' if s['status']=='running' else '🔴'} {s['name']} ({sz:.1f}МБ) — {s['id']}\n"; copied += 1
    if copied==0: bot.send_message(call.message.chat.id,"❌"); shutil.rmtree(tmp_dir,ignore_errors=True); return
    zip_path = os.path.join(tempfile.gettempdir(), f"scripts_user_{uid}.zip")
    shutil.make_archive(zip_path.replace('.zip',''), 'zip', tmp_dir)
    try:
        with open(zip_path,'rb') as f: bot.send_document(call.message.chat.id, f, caption=info_text)
    except: pass
    shutil.rmtree(tmp_dir, ignore_errors=True)
    if os.path.exists(zip_path): os.remove(zip_path)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_del_all:"))
def adm_delete_all_scripts(call):
    if call.from_user.id not in ADMIN_IDS: return
    uid = int(call.data.split(":")[1]); scripts = get_user_scripts(uid)
    if not scripts: bot.answer_callback_query(call.id,"❌",show_alert=True); return
    mk = InlineKeyboardMarkup(row_width=2)
    mk.add(InlineKeyboardButton("✅ Да, удалить все", callback_data=f"adm_del_all_confirm:{uid}"), InlineKeyboardButton("❌ Отмена", callback_data="adm_cancel"))
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, f"⚠️ Удалить ВСЕ скрипты #{uid}?\n{len(scripts)} шт.\nНеобратимо!", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_del_all_confirm:"))
def adm_delete_all_confirm(call):
    if call.from_user.id not in ADMIN_IDS: return
    uid = int(call.data.split(":")[1]); scripts = get_user_scripts(uid)
    deleted = 0
    for s in scripts:
        try:
            delete_script(s['id'], uid)
            d = os.path.join(SCRIPTS_DIR, str(uid), s['id'])
            if os.path.exists(d): shutil.rmtree(d, ignore_errors=True)
            deleted += 1
        except: pass
    bot.answer_callback_query(call.id, f"✅ {deleted}/{len(scripts)}")

@bot.callback_query_handler(func=lambda c: c.data == "adm_cancel")
def adm_cancel(call): bot.answer_callback_query(call.id,"❌"); bot.delete_message(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("adm_reset:"))
def adm_reset(call):
    if call.from_user.id not in ADMIN_IDS: return
    set_subscription(int(call.data.split(":")[1]), 'free', 0)
    bot.answer_callback_query(call.id, "✅ Сброшен!")

@bot.message_handler(func=lambda m: m.text == "📦 Хосты" and m.from_user.id in ADMIN_IDS)
def admin_btn_hosts(m):
    ss = get_all_scripts()
    if not ss: bot.send_message(m.chat.id,"📭"); return
    mk = InlineKeyboardMarkup(row_width=2)
    for s in ss[:10]: mk.add(InlineKeyboardButton(f"🗑 {s['id'][:8]}", callback_data=f"sc:del:{s['id']}"))
    bot.send_message(m.chat.id, f"📦 <b>ХОСТЫ ({len(ss)})</b>", reply_markup=mk)

@bot.message_handler(func=lambda m: m.text == "📢 Каналы" and m.from_user.id in ADMIN_IDS)
def admin_btn_channel(m):
    channels = load_channels().get("channels",[])
    text = "📢 <b>КАНАЛЫ</b>\n\n" + ("\n".join([f"{i}. {ch['name']} ({ch['id']})" for i,ch in enumerate(channels,1)]) if channels else "❌ Нет")
    text += "\n\nОтправьте @username"
    mk = InlineKeyboardMarkup().add(InlineKeyboardButton("🗑 Удалить все", callback_data="admin_del_channels"))
    bot.send_message(m.chat.id, text, reply_markup=mk)
    bot.register_next_step_handler(m, add_channel_admin)

@bot.callback_query_handler(func=lambda c: c.data == "admin_del_channels")
def admin_del_channels(call):
    if call.from_user.id not in ADMIN_IDS: return
    save_channels({"channels":[],"welcome_text":"🔒 Подпишитесь!","welcome_photo":None})
    bot.answer_callback_query(call.id,"✅")

def add_channel_admin(message):
    if message.from_user.id not in ADMIN_IDS: return
    ch = message.text.strip()
    if not ch.startswith("@"): ch = "@"+ch
    try:
        chat = bot.get_chat(ch)
        data = load_channels()
        if "channels" not in data: data["channels"] = []
        data["channels"].append({"id":ch,"name":chat.title,"url":f"https://t.me/{ch[1:]}"})
        save_channels(data); bot.send_message(message.chat.id, f"✅ {chat.title}")
    except: bot.send_message(message.chat.id, "❌ Ошибка")

@bot.message_handler(func=lambda m: m.text == "📨 Рассылка" and m.from_user.id in ADMIN_IDS)
def admin_btn_spam(m):
    broadcast_state[m.from_user.id] = {"step":"choose_type"}
    mk = InlineKeyboardMarkup(row_width=1)
    mk.add(InlineKeyboardButton("📝 Текст", callback_data="bcast_text"), InlineKeyboardButton("🖼 Фото", callback_data="bcast_photo"), InlineKeyboardButton("« Отмена", callback_data="admin_cancel"))
    bot.send_message(m.chat.id, "📨 <b>РАССЫЛКА</b>\nТип:", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "admin_cancel")
def admin_cancel(call): broadcast_state.pop(call.from_user.id,None); bot.edit_message_text("❌", call.message.chat.id, call.message.message_id); bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("bcast_"))
def bcast_type(call):
    if call.from_user.id not in ADMIN_IDS: return
    t = call.data.replace("bcast_",""); broadcast_state[call.from_user.id] = {"step":"waiting","type":t}
    bot.edit_message_text("📝:" if t=="text" else "🖼:", call.message.chat.id, call.message.message_id); bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.from_user.id in ADMIN_IDS and broadcast_state.get(m.from_user.id,{}).get("step")=="waiting")
def bcast_send(message):
    uid = message.from_user.id; state = broadcast_state.pop(uid); users = get_all_users(); success = 0
    if state['type']=='text':
        for u in users:
            try: bot.send_message(u['user_id'], message.text); success += 1
            except: pass
            time.sleep(0.05)
    elif state['type']=='photo' and message.photo:
        for u in users:
            try: bot.send_photo(u['user_id'], message.photo[-1].file_id, caption=message.caption); success += 1
            except: pass
            time.sleep(0.05)
    bot.send_message(message.chat.id, f"📨 ✅ {success}/{len(users)}")

@bot.message_handler(func=lambda m: m.text == "🎫 Промокоды" and m.from_user.id in ADMIN_IDS)
def admin_btn_promos(m):
    with get_db() as conn: promos = conn.execute('SELECT * FROM promocodes').fetchall()
    text = "🎫 <b>ПРОМОКОДЫ</b>\n\n"
    if promos: text += "\n".join([f"• <code>{p['code']}</code> — {p['type']} {p['days']}дн ({p['used_count']}/{p['max_uses']})" for p in promos])
    else: text += "❌ Нет"
    text += "\n\n<code>КОД ТИП ДНИ ИСП</code>"
    mk = InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Удалить все", callback_data="del_all_promos"))
    bot.send_message(m.chat.id, text, reply_markup=mk)
    bot.register_next_step_handler(m, create_promo_admin)

def create_promo_admin(message):
    parts = message.text.strip().split()
    if len(parts)<4: bot.send_message(message.chat.id,"❌"); return
    with get_db() as conn: conn.execute('INSERT OR IGNORE INTO promocodes VALUES (?,?,?,?,0)', (parts[0].upper(), parts[1].lower(), int(parts[2]), int(parts[3]))); conn.commit()
    bot.send_message(message.chat.id, f"✅ {parts[0].upper()}")

@bot.callback_query_handler(func=lambda c: c.data == "del_all_promos")
def delete_all_promos(call):
    if call.from_user.id not in ADMIN_IDS: return
    with get_db() as conn: conn.execute('DELETE FROM promocodes'); conn.commit()
    bot.answer_callback_query(call.id,"✅")

@bot.message_handler(func=lambda m: m.text == "⚙️ Настройки" and m.from_user.id in ADMIN_IDS)
def admin_btn_settings(m):
    photos = load_photos(); settings = load_settings(); data = load_channels()
    text = f"⚙️ <b>НАСТРОЙКИ</b>\n\n🖼 Приветствие: {'✅' if settings.get('welcome_photo') else '❌'}\n🖼 ХС: {'✅' if photos.get('shop') else '❌'}\n🔒 Подписка: {'✅' if data.get('welcome_photo') else '❌'}\n📢 Каналов: {len(data.get('channels',[]))}"
    mk = InlineKeyboardMarkup(row_width=2)
    mk.add(InlineKeyboardButton("🖼 Приветствие", callback_data="set_welcome_photo"), InlineKeyboardButton("📝 Текст", callback_data="set_welcome_text"))
    mk.add(InlineKeyboardButton("🖼 Фото ХС", callback_data="setphoto_hs"), InlineKeyboardButton("🔒 Подписка", callback_data="admin_sub_settings"))
    mk.add(InlineKeyboardButton("🖼 Все фото", callback_data="admin_all_photos"))
    bot.send_message(m.chat.id, text, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "admin_sub_settings")
def admin_sub_settings(call):
    if call.from_user.id not in ADMIN_IDS: return
    bot.answer_callback_query(call.id)
    mk = InlineKeyboardMarkup(row_width=1)
    mk.add(InlineKeyboardButton("🖼 Фото", callback_data="set_sub_photo"), InlineKeyboardButton("📝 Текст", callback_data="set_sub_text"), InlineKeyboardButton("🗑", callback_data="del_sub_photo"))
    bot.send_message(call.message.chat.id, f"🔒 Подписка\n🖼 {'✅' if load_channels().get('welcome_photo') else '❌'}", reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "admin_all_photos")
def admin_all_photos(call):
    if call.from_user.id not in ADMIN_IDS: return
    bot.answer_callback_query(call.id)
    photos = load_photos()
    text = "🖼 <b>ВСЕ ФОТО</b>\n\n"
    cats = {"main":"🏠 Главное","shop":"🛒 Магазин","hosts":"💻 Хосты","deposit":"💳 Пополнение","profile":"👤 Профиль","support":"🆘 Поддержка"}
    for cat, desc in cats.items(): text += f"{'✅' if photos.get(cat) else '❌'} {desc}\n"
    mk = InlineKeyboardMarkup(row_width=2)
    for cat in cats: mk.add(InlineKeyboardButton(cat, callback_data=f"setphoto:{cat}"))
    bot.send_message(call.message.chat.id, text, reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data == "set_welcome_photo")
def set_welcome_photo(call):
    if call.from_user.id not in ADMIN_IDS: return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "🖼 Фото приветствия:\n❌ /skip")
    bot.register_next_step_handler(msg, lambda m: (settings:=load_settings(), settings.update({'welcome_photo':m.photo[-1].file_id}), save_settings(settings), bot.send_message(m.chat.id,"✅")) if m.photo else None)

@bot.callback_query_handler(func=lambda c: c.data == "set_welcome_text")
def set_welcome_text(call):
    if call.from_user.id not in ADMIN_IDS: return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "📝 Текст:\n❌ /skip")
    bot.register_next_step_handler(msg, lambda m: (settings:=load_settings(), settings.update({'welcome_text':m.text or ""}), save_settings(settings), bot.send_message(m.chat.id,"✅")) if m.text else None)

@bot.callback_query_handler(func=lambda c: c.data == "setphoto_hs")
def set_photo_hs(call):
    if call.from_user.id not in ADMIN_IDS: return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "🖼 Фото ХС:\n❌ /skip")
    bot.register_next_step_handler(msg, lambda m: (photos:=load_photos(), photos.update({'shop':m.photo[-1].file_id}), save_photos(photos), bot.send_message(m.chat.id,"✅")) if m.photo else None)

@bot.callback_query_handler(func=lambda c: c.data.startswith("setphoto:"))
def set_photo_category(call):
    if call.from_user.id not in ADMIN_IDS: return
    cat = call.data.split(":")[1]; bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"📸 {cat}:\n❌ /skip")
    bot.register_next_step_handler(msg, lambda m, c=cat: (photos:=load_photos(), photos.update({c:m.photo[-1].file_id}), save_photos(photos), bot.send_message(m.chat.id,f"✅ {c}")) if m.photo else None)

@bot.callback_query_handler(func=lambda c: c.data == "set_sub_photo")
def set_sub_photo(call):
    if call.from_user.id not in ADMIN_IDS: return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "🖼 Фото подписки:\n❌ /skip")
    bot.register_next_step_handler(msg, lambda m: (data:=load_channels(), data.update({'welcome_photo':m.photo[-1].file_id}), save_channels(data), bot.send_message(m.chat.id,"✅")) if m.photo else None)

@bot.callback_query_handler(func=lambda c: c.data == "set_sub_text")
def set_sub_text(call):
    if call.from_user.id not in ADMIN_IDS: return
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "📝 Текст подписки:\n❌ /skip")
    bot.register_next_step_handler(msg, lambda m: (data:=load_channels(), data.update({'welcome_text':m.text}), save_channels(data), bot.send_message(m.chat.id,"✅")) if m.text else None)

@bot.callback_query_handler(func=lambda c: c.data == "del_sub_photo")
def del_sub_photo(call):
    if call.from_user.id not in ADMIN_IDS: return
    data = load_channels(); data['welcome_photo'] = None; save_channels(data)
    bot.edit_message_text("🗑", call.message.chat.id, call.message.message_id); bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data == "delphoto_hs")
def del_photo_hs(call):
    if call.from_user.id not in ADMIN_IDS: return
    photos = load_photos(); photos['shop'] = None; save_photos(photos)
    bot.edit_message_text("🗑", call.message.chat.id, call.message.message_id); bot.answer_callback_query(call.id)

@bot.message_handler(func=lambda m: m.text in ["🛑 СТОП","🟢 СТАРТ"] and m.from_user.id in ADMIN_IDS)
def admin_btn_toggle(m):
    global bot_status
    if m.text=="🛑 СТОП": bot_status = "stopped"; stop_all(); bot.send_message(m.chat.id, "🔴 Бот остановлен!", reply_markup=admin_keyboard())
    else: bot_status = "running"; bot.send_message(m.chat.id, "🟢 Бот запущен!", reply_markup=admin_keyboard())

@bot.message_handler(func=lambda m: m.text == "⏹ Всё стоп" and m.from_user.id in ADMIN_IDS)
def admin_btn_stop_all(m): stop_all(); bot.send_message(m.chat.id,"🛑")
@bot.message_handler(func=lambda m: m.text == "▶️ Всё старт" and m.from_user.id in ADMIN_IDS)
def admin_btn_start_all(m): bot.send_message(m.chat.id,"▶️ Готово")

# ========== ОБРАБОТКА ОПЛАТЫ ==========
@bot.message_handler(content_types=['photo'])
def screenshot(message):
    uid = message.from_user.id
    if uid not in pending_payments: return
    pi = pending_payments.pop(uid)
    if pi.get('type')=='balance':
        for aid in ADMIN_IDS:
            mk = InlineKeyboardMarkup(row_width=2)
            mk.add(InlineKeyboardButton("✅ Подтвердить", callback_data=f"app_bal|{uid}|{pi['amount']}"), InlineKeyboardButton("❌ Отклонить", callback_data=f"rej|{uid}"))
            try: bot.send_photo(aid, message.photo[-1].file_id, caption=f"💰 +{pi['amount']}₽\n👤 {uid}", reply_markup=mk)
            except: pass
        bot.send_message(uid, "✅ Чек отправлен!")

@bot.callback_query_handler(func=lambda c: c.data.startswith("app_bal|"))
def approve_balance(call):
    if call.from_user.id not in ADMIN_IDS: return
    try:
        _, uid, amount = call.data.split("|"); uid = int(uid); amount = float(amount)
        with get_db() as conn: conn.execute('UPDATE users SET balance=balance+? WHERE user_id=?', (amount, uid)); conn.commit()
        cache.delete(f"user:{uid}"); get_cached_user.cache_clear()
        try: bot.send_message(uid, f"✅ Баланс +{amount}₽")
        except: pass
        bot.answer_callback_query(call.id,"✅")
    except: bot.answer_callback_query(call.id,"❌")

@bot.callback_query_handler(func=lambda c: c.data.startswith("rej|"))
def reject(call):
    if call.from_user.id not in ADMIN_IDS: return
    try: uid = int(call.data.replace("rej|","")); bot.send_message(uid,"❌ Отклонено"); bot.answer_callback_query(call.id,"❌")
    except: pass

@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def check_sub(call):
    user_id = call.from_user.id
    channels = load_channels().get("channels",[])
    if not channels: bot.answer_callback_query(call.id,"✅"); cmd_start(call.message); return
    not_subscribed = [ch['name'] for ch in channels if bot.get_chat_member(ch['id'], user_id).status in ["left","kicked"]]
    if not not_subscribed: bot.answer_callback_query(call.id,"✅"); cmd_start(call.message)
    else: bot.answer_callback_query(call.id, f"❌ {', '.join(not_subscribed)}", show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sc:"))
def script_action(call):
    if is_bot_blocked(call.from_user.id): bot.answer_callback_query(call.id,"🔴"); return
    try:
        _, a, sid = call.data.split(":")
        if a=="stop": s = get_script(sid); s and s['status']=='running' and update_script_status(sid,'stopped'); bot.answer_callback_query(call.id,"✅")
        elif a=="log":
            lp = os.path.join(LOGS_DIR, f"{sid}.log")
            os.path.exists(lp) and bot.send_document(call.message.chat.id, open(lp,'rb'), caption=f"📄 {sid}")
            bot.answer_callback_query(call.id,"✅")
        elif a=="del":
            s = get_script(sid); delete_script(sid, call.from_user.id)
            d = os.path.join(SCRIPTS_DIR, str(call.from_user.id), sid)
            os.path.exists(d) and shutil.rmtree(d, ignore_errors=True)
            lp = os.path.join(LOGS_DIR, f"{sid}.log")
            os.path.exists(lp) and os.remove(lp)
            bot.answer_callback_query(call.id,"✅")
    except: bot.answer_callback_query(call.id,"❌")

@bot.pre_checkout_query_handler(func=lambda q: True)
def pre_checkout(q): bot.answer_pre_checkout_query(q.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def pay_ok(message):
    p = message.successful_payment.invoice_payload
    if p.startswith("bal_stars_"):
        amount = int(p.replace("bal_stars_",""))
        with get_db() as conn: conn.execute('UPDATE users SET balance=balance+? WHERE user_id=?', (amount, message.from_user.id)); conn.commit()
        cache.delete(f"user:{message.from_user.id}"); get_cached_user.cache_clear()
        bot.send_message(message.chat.id, f"⭐ +{amount}₽")

@bot.message_handler(content_types=['document'])
def handle_doc(message):
    uid = message.from_user.id
    if is_bot_blocked(uid) or not get_user(uid) or not check_subscription(uid) or not check_user_limits(uid): bot.reply_to(message,"❌"); return
    fi = bot.get_file(message.document.file_id); fn, fs = message.document.file_name, message.document.file_size
    _, mx = get_user_limits(uid)
    if fs > mx*1024*1024: bot.reply_to(message, f"❌ Макс {mx}МБ"); return
    if not (fn.endswith('.py') or fn.endswith('.zip')): bot.reply_to(message,"❌ .py/.zip"); return
    td = os.path.join(TEMP_DIR, str(uid)); os.makedirs(td, exist_ok=True)
    tp = os.path.join(td, fn)
    with open(tp,'wb') as f: f.write(bot.download_file(fi.file_path))
    sid = str(uuid.uuid4())[:8]; upload_states[uid] = {'sid':sid,'tp':tp,'fn':fn,'fs':fs}
    if fn.endswith('.zip'):
        et = os.path.join(td, sid); os.makedirs(et, exist_ok=True)
        ok, msg = extract_zip(tp, et)
        if not ok: bot.reply_to(message, f"❌ {msg}"); cleanup(uid); return
        pf = find_py_files(et)
        if not pf: bot.reply_to(message,"❌ Нет .py"); cleanup(uid); return
        upload_states[uid].update({'et':et,'pf':pf})
        mk = InlineKeyboardMarkup(row_width=1)
        for f in pf: mk.add(InlineKeyboardButton(f"📄 {os.path.relpath(f,et)}", callback_data=f"sel:{os.path.relpath(f,et)}"))
        bot.send_message(uid, "📁 Главный файл:", reply_markup=mk)
    else: finish(uid, tp, fn)

@bot.callback_query_handler(func=lambda c: c.data.startswith("sel:"))
def select_file(call):
    uid = call.from_user.id
    if uid not in upload_states: bot.answer_callback_query(call.id,"❌"); return
    rel = call.data.split(":",1)[1]; state = upload_states[uid]; state['main'] = rel
    bot.edit_message_text(f"✅ {rel}", uid, call.message.message_id); bot.answer_callback_query(call.id)
    finish(uid, os.path.join(state['et'], rel), state['fn'])

def finish(uid, sp, ofn):
    state = upload_states.pop(uid, {})
    sid = state.get('sid', str(uuid.uuid4())[:8]); fs = state.get('fs', os.path.getsize(sp))
    ud = os.path.join(SCRIPTS_DIR, str(uid), sid); os.makedirs(ud, exist_ok=True)
    if 'et' in state:
        for item in os.listdir(state['et']):
            s = os.path.join(state['et'], item); d = os.path.join(ud, item)
            os.path.isdir(s) and shutil.copytree(s, d, dirs_exist_ok=True) or shutil.copy2(s, d)
        mf = os.path.join(ud, state.get('main',''))
    else: shutil.move(sp, os.path.join(ud, ofn)); mf = os.path.join(ud, ofn)
    cid, err = run_fallback(sid, ud)
    if err: bot.send_message(uid, f"❌ {err}"); return
    add_script(sid, uid, ofn, ud, fs, 'free'); update_script_status(sid, 'running', cid)
    bot.send_message(uid, f"✅ Хост запущен!\n📄 {ofn}\n🆔 <code>{sid}</code>")
    cleanup(uid)

# ========== МОНИТОРИНГ С УВЕДОМЛЕНИЯМИ ==========
def monitor():
    last_admin_notify = None
    while True:
        try:
            users = get_all_users()
            now = datetime.now()
            
            if now.hour == 10 and last_admin_notify != now.date():
                last_admin_notify = now.date()
                expiring_soon = []
                for user in users:
                    expiry = user.get('subscription_expiry')
                    if expiry:
                        try:
                            days = (datetime.fromisoformat(expiry) - now).days
                            if 0 <= days <= 3:
                                expiring_soon.append((user['user_id'], user.get('username'), days))
                        except: pass
                
                if expiring_soon:
                    text = "📊 <b>Истекающие подписки:</b>\n\n"
                    for uid, username, days in expiring_soon[:10]:
                        text += f"• <code>{uid}</code> @{username or '?'} — {days} дн.\n"
                    for aid in ADMIN_IDS:
                        try: bot.send_message(aid, text)
                        except: pass
            
            for user in users:
                uid = user['user_id']
                expiry = user.get('subscription_expiry')
                if not expiry: continue
                
                try:
                    expiry_date = datetime.fromisoformat(expiry)
                    delta = expiry_date - now
                    days_left = delta.days
                    
                    if uid not in notified_users:
                        notified_users[uid] = {}
                    
                    if days_left == 3:
                        if not notified_users[uid].get('3d'):
                            try:
                                bot.send_message(uid, f"⚠️ <b>Подписка истекает через 3 дня!</b>\n\n📋 Тариф: {get_subscription_info(uid)[0]}\n📅 Истекает: {expiry_date.strftime('%d.%m.%Y')}\n\nПродлите подписку в магазине!", reply_markup=user_keyboard())
                                notified_users[uid]['3d'] = True
                            except: pass
                    
                    if days_left == 1:
                        if not notified_users[uid].get('1d'):
                            try:
                                bot.send_message(uid, f"🔴 <b>Подписка истекает завтра!</b>\n\n📋 Тариф: {get_subscription_info(uid)[0]}\n📅 Истекает: {expiry_date.strftime('%d.%m.%Y')}\n\nСрочно продлите! Хосты будут остановлены.", reply_markup=user_keyboard())
                                notified_users[uid]['1d'] = True
                            except: pass
                    
                    if delta.total_seconds() <= 0:
                        try:
                            for script in get_user_scripts(uid):
                                if script['status'] == 'running':
                                    update_script_status(script['id'], 'stopped')
                            
                            with get_db() as conn:
                                conn.execute('UPDATE users SET subscription=?, subscription_expiry=NULL, free_used=1, current_tier=NULL, current_location=NULL WHERE user_id=?', ('free', uid))
                                conn.commit()
                            cache.delete(f"user:{uid}")
                            get_cached_user.cache_clear()
                            notified_users.pop(uid, None)
                            
                            bot.send_message(uid, f"🔴 <b>Подписка истекла!</b>\n\nВсе ваши хосты остановлены.\nКупите новую подписку в магазине.", reply_markup=user_keyboard())
                        except Exception as e:
                            logger.error(f"Expiry error for {uid}: {e}")
                            
                except Exception as e:
                    logger.error(f"Monitor error for user {uid}: {e}")
            
            time.sleep(3600)
            
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            time.sleep(3600)

def crypto_check():
    while True:
        try:
            for iid, info in list(crypto_invoices.items()):
                if check_invoice(iid):
                    if info.get('type')=='balance':
                        rub_amount = info['amount'] * 95
                        with get_db() as conn: conn.execute('UPDATE users SET balance=balance+? WHERE user_id=?', (rub_amount, info['uid'])); conn.commit()
                        cache.delete(f"user:{info['uid']}"); get_cached_user.cache_clear()
                        try: bot.send_message(info['uid'], f"💎 +{rub_amount}₽")
                        except: pass
                    del crypto_invoices[iid]
            time.sleep(15)
        except: time.sleep(30)

def cleanup_resources():
    try: stop_all(); executor.shutdown(wait=True)
    except: pass
atexit.register(cleanup_resources)
signal.signal(signal.SIGTERM, lambda s,f: sys.exit(0))
signal.signal(signal.SIGINT, lambda s,f: sys.exit(0))

# ========== АНТИ-СОН ==========
def keep_alive():
    while True:
        time.sleep(300)
        try:
            requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
        except:
            pass

threading.Thread(target=keep_alive, daemon=True).start()

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    print(f"🚀 Hosting Bot v{VERSION}")
    init_db()
    os.path.exists(SETTINGS_FILE) or save_settings(DEFAULT_SETTINGS)
    os.path.exists(PHOTOS_FILE) or save_photos(CATEGORY_PHOTOS)
    os.path.exists(CHANNEL_FILE) or save_channels({"channels":[],"welcome_text":"🔒 Подпишитесь на канал!","welcome_photo":None})
    setup_menu()
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=crypto_check, daemon=True).start()
    print("✅ Бот запущен")
    bot.infinity_polling()
