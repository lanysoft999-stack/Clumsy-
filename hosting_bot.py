cat > hosting_bot.py << 'EOF'
# hosting_bot.py - Python Hosting Bot для Render
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import os
import sqlite3
import threading
import time
import uuid
import shutil
import zipfile
import subprocess
import signal
from requests.exceptions import ReadTimeout

TOKEN = "8993679520:AAGLgewBaKXkNBjliut7B3t09ydPFu-YwB8"
VERSION = "3.2.0"
ADMIN_IDS = [314148464]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
TEMP_DIR = os.path.join(BASE_DIR, "temp")
DATABASE_PATH = os.path.join(BASE_DIR, "bot_database.db")

FREE_MAX_SCRIPTS = 10
FREE_MAX_SIZE_MB = 10
PREMIUM_MAX_SIZE_MB = 1024
PREMIUM_STARS_PRICE = 100
MONITOR_INTERVAL = 10

os.makedirs(SCRIPTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

bot_status = "running"

def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, subscription TEXT DEFAULT 'free', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS scripts (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL, pid INTEGER, status TEXT DEFAULT 'stopped', size INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users(user_id))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS promocodes (code TEXT PRIMARY KEY, max_uses INTEGER DEFAULT 1, used_count INTEGER DEFAULT 0)''')
        conn.execute('''INSERT OR IGNORE INTO promocodes (code, max_uses) VALUES ('PREMIUM2024', 100), ('HOSTINGFREE', 50)''')
        conn.commit()

def get_user(user_id):
    with get_db() as conn:
        cur = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = cur.fetchone()
        user = dict(row) if row else None
    if user and user_id in ADMIN_IDS:
        user['subscription'] = 'premium'
    return user

def create_user(user_id, username):
    with get_db() as conn:
        try:
            conn.execute('INSERT INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
            conn.commit()
        except: pass

def activate_premium(user_id):
    with get_db() as conn:
        conn.execute('UPDATE users SET subscription = ? WHERE user_id = ?', ('premium', user_id))
        conn.commit()

def activate_promo(user_id, code):
    with get_db() as conn:
        cur = conn.execute('SELECT * FROM promocodes WHERE code = ?', (code,))
        promo = cur.fetchone()
        if not promo: return False, "Промокод не найден"
        promo = dict(promo)
        if promo['used_count'] >= promo['max_uses']: return False, "Промокод закончился"
        conn.execute('UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?', (code,))
        conn.execute('UPDATE users SET subscription = ? WHERE user_id = ?', ('premium', user_id))
        conn.commit()
        return True, "Премиум активирован!"

def add_script(script_id, user_id, name, path, size):
    with get_db() as conn:
        conn.execute('INSERT INTO scripts (id, user_id, name, path, size) VALUES (?, ?, ?, ?, ?)', (script_id, user_id, name, path, size))
        conn.commit()

def get_user_scripts(user_id):
    with get_db() as conn:
        cur = conn.execute('SELECT * FROM scripts WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
        return [dict(row) for row in cur.fetchall()]

def get_script(script_id):
    with get_db() as conn:
        cur = conn.execute('SELECT * FROM scripts WHERE id = ?', (script_id,))
        row = cur.fetchone()
        return dict(row) if row else None

def get_all_scripts():
    with get_db() as conn:
        cur = conn.execute('SELECT * FROM scripts ORDER BY created_at DESC')
        return [dict(row) for row in cur.fetchall()]

def update_script_status(script_id, status, pid=None):
    with get_db() as conn:
        if pid is not None:
            conn.execute('UPDATE scripts SET status = ?, pid = ? WHERE id = ?', (status, pid, script_id))
        else:
            conn.execute('UPDATE scripts SET status = ? WHERE id = ?', (status, script_id))
        conn.commit()

def get_all_running_scripts():
    with get_db() as conn:
        cur = conn.execute("SELECT * FROM scripts WHERE status = 'running'")
        return [dict(row) for row in cur.fetchall()]

def count_user_scripts(user_id):
    with get_db() as conn:
        cur = conn.execute('SELECT COUNT(*) as cnt FROM scripts WHERE user_id = ?', (user_id,))
        row = cur.fetchone()
        return row['cnt'] if row else 0

def delete_script(script_id, user_id):
    with get_db() as conn:
        conn.execute('DELETE FROM scripts WHERE id = ? AND user_id = ?', (script_id, user_id))
        conn.commit()

def get_all_users():
    with get_db() as conn:
        cur = conn.execute('SELECT * FROM users ORDER BY created_at DESC')
        return [dict(row) for row in cur.fetchall()]

def stop_all_scripts():
    for script in get_all_running_scripts():
        try: os.killpg(os.getpgid(script['pid']), signal.SIGTERM)
        except:
            try: os.kill(script['pid'], signal.SIGTERM)
            except: pass
        update_script_status(script['id'], 'stopped')

def check_user_limits(user_id):
    if user_id in ADMIN_IDS: return True
    user = get_user(user_id)
    if not user: return False
    if user['subscription'] == 'premium': return True
    return count_user_scripts(user_id) < FREE_MAX_SCRIPTS

def cleanup_temp(user_id):
    temp_dir = os.path.join(TEMP_DIR, str(user_id))
    if os.path.exists(temp_dir):
        try: shutil.rmtree(temp_dir)
        except: pass

def extract_zip(zip_path, extract_to):
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        return True, None
    except Exception as e:
        return False, str(e)

def find_py_files(folder):
    py_files = []
    for root, dirs, files in os.walk(folder):
        for file in files:
            if file.endswith('.py'):
                py_files.append(os.path.join(root, file))
    return py_files

def run_script(script_id, script_path):
    log_path = os.path.join(LOGS_DIR, f"{script_id}.log")
    try:
        with open(log_path, 'ab') as log_file:
            process = subprocess.Popen(['python', script_path], stdout=log_file, stderr=subprocess.STDOUT, cwd=os.path.dirname(script_path), preexec_fn=os.setsid)
        return process.pid, None
    except Exception as e:
        return None, str(e)

def stop_script(pid):
    try:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            time.sleep(0.5)
            if is_process_alive(pid): os.killpg(os.getpgid(pid), signal.SIGKILL)
        except:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
            if is_process_alive(pid): os.kill(pid, signal.SIGKILL)
        return True, None
    except ProcessLookupError: return False, "Процесс не найден"
    except Exception as e: return False, str(e)

def is_process_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except: return False

bot = telebot.TeleBot(TOKEN)
upload_states = {}

def auth_required(message):
    user_id = message.from_user.id
    if not get_user(user_id):
        create_user(user_id, message.from_user.username)
    return True

def get_main_menu(user_id):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("📦 Запустить скрипт", callback_data="menu_upload"), InlineKeyboardButton("📋 Мои скрипты", callback_data="menu_list"), InlineKeyboardButton("💎 Премиум", callback_data="menu_premium"), InlineKeyboardButton("🎁 Промокод", callback_data="menu_promo"))
    if user_id in ADMIN_IDS:
        if bot_status == "running": markup.add(InlineKeyboardButton("⏹ ОСТАНОВИТЬ БОТА", callback_data="admin_stop_bot"))
        else: markup.add(InlineKeyboardButton("▶️ ЗАПУСТИТЬ БОТА", callback_data="admin_start_bot"))
        markup.add(InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"), InlineKeyboardButton("👥 Пользователи", callback_data="admin_users_list"), InlineKeyboardButton("📋 Все скрипты", callback_data="admin_all_scripts"), InlineKeyboardButton("🛑 Остановить всё", callback_data="admin_stop_all"))
    markup.add(InlineKeyboardButton("ℹ️ Помощь", callback_data="menu_help"))
    return markup

@bot.message_handler(commands=['start'])
def cmd_start(message):
    auth_required(message)
    user = get_user(message.from_user.id)
    user_id = message.from_user.id
    if user_id in ADMIN_IDS: status = "👑 Админ"
    elif user['subscription'] == 'premium': status = "💎 Премиум"
    else: status = "🆓 Бесплатный"
    if bot_status == "stopped" and user_id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "🔴 Бот остановлен", parse_mode='HTML')
        return
    max_scripts = "∞" if (user_id in ADMIN_IDS or user['subscription'] == 'premium') else FREE_MAX_SCRIPTS
    text = f"🚀 <b>Python Hosting Bot v{VERSION}</b>\n\nСтатус: {status}\nБот: {'🟢' if bot_status=='running' else '🔴'}\nСкриптов: {count_user_scripts(user_id)}/{max_scripts}\n\nОтправьте .py или .zip файл!"
    bot.send_message(message.chat.id, text, reply_markup=get_main_menu(user_id), parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == "admin_stop_bot")
def admin_stop_bot(call):
    if call.from_user.id not in ADMIN_IDS: bot.answer_callback_query(call.id, "❌ Нет доступа!"); return
    global bot_status
    bot_status = "stopped"
    stop_all_scripts()
    bot.answer_callback_query(call.id, "🔴 Остановлен!"); cmd_start(call.message)

@bot.callback_query_handler(func=lambda call: call.data == "admin_start_bot")
def admin_start_bot(call):
    if call.from_user.id not in ADMIN_IDS: bot.answer_callback_query(call.id, "❌ Нет доступа!"); return
    global bot_status
    bot_status = "running"
    bot.answer_callback_query(call.id, "🟢 Запущен!"); cmd_start(call.message)

@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
def admin_stats(call):
    if call.from_user.id not in ADMIN_IDS: bot.answer_callback_query(call.id, "❌ Нет доступа!"); return
    users = get_all_users()
    all_scripts = get_all_scripts()
    running = len(get_all_running_scripts())
    premium_count = sum(1 for u in users if u['subscription'] == 'premium')
    text = f"📊 <b>Статистика</b>\n\n👥 Пользователей: {len(users)}\n💎 Премиум: {premium_count}\n📦 Скриптов: {len(all_scripts)}\n🟢 Запущено: {running}"
    bot.send_message(call.message.chat.id, text, parse_mode='HTML')
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "admin_users_list")
def admin_users_list(call):
    if call.from_user.id not in ADMIN_IDS: bot.answer_callback_query(call.id, "❌ Нет доступа!"); return
    users = get_all_users()
    if not users: bot.send_message(call.message.chat.id, "👥 Нет пользователей"); bot.answer_callback_query(call.id); return
    text = f"👥 <b>Пользователи ({len(users)}):</b>\n\n"
    markup = InlineKeyboardMarkup(row_width=1)
    for u in users[:20]:
        status_icon = "💎" if u['subscription'] == 'premium' else "🆓"
        username = u.get('username', 'Нет')
        text += f"{status_icon} ID: {u['user_id']} | @{username}\n"
        markup.add(InlineKeyboardButton(f"📋 Скрипты {u['user_id']}", callback_data=f"admin_user_scripts:{u['user_id']}"))
    markup.add(InlineKeyboardButton("« Назад", callback_data="back_main"))
    bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "back_main")
def callback_back(call):
    cmd_start(call.message)

@bot.callback_query_handler(func=lambda call: call.data == "menu_upload")
def menu_upload(call):
    if bot_status == "stopped" and call.from_user.id not in ADMIN_IDS: bot.answer_callback_query(call.id, "🔴 Бот остановлен!"); return
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "📦 Отправьте .py файл или ZIP-архив")

@bot.callback_query_handler(func=lambda call: call.data == "menu_list")
def menu_list(call):
    bot.answer_callback_query(call.id)
    show_scripts(call.message)

@bot.callback_query_handler(func=lambda call: call.data == "menu_premium")
def menu_premium(call):
    bot.answer_callback_query(call.id)
    if call.from_user.id in ADMIN_IDS: bot.send_message(call.message.chat.id, "👑 У вас вечный премиум!"); return
    bot.send_invoice(chat_id=call.message.chat.id, title="💎 Премиум", description="Безлимит скриптов, до 1 ГБ", payload="premium_sub", provider_token="", currency="XTR", prices=[{"label": "Премиум", "amount": PREMIUM_STARS_PRICE}])

@bot.callback_query_handler(func=lambda call: call.data == "menu_promo")
def menu_promo(call):
    bot.answer_callback_query(call.id)
    if call.from_user.id in ADMIN_IDS: bot.send_message(call.message.chat.id, "👑 Админам не нужны!"); return
    msg = bot.send_message(call.message.chat.id, "🎁 Введите промокод:")
    bot.register_next_step_handler(msg, process_promo)

@bot.callback_query_handler(func=lambda call: call.data == "menu_help")
def menu_help(call):
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "📚 Помощь\n\n📦 Запустить скрипт\n📋 Мои скрипты\n💎 Премиум\n🎁 Промокод\n\nПромокоды: PREMIUM2024, HOSTINGFREE", parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('script:'))
def script_action(call):
    action, script_id = call.data.split(':')[1:]
    if action == "stop":
        script = get_script(script_id)
        if script and script['status'] == 'running':
            ok, msg = stop_script(script['pid'])
            if ok: update_script_status(script_id, 'stopped'); bot.answer_callback_query(call.id, "✅ Остановлен!")
            else: bot.answer_callback_query(call.id, f"❌ {msg}")
        else: bot.answer_callback_query(call.id, "Уже остановлен")
    elif action == "logs":
        log_path = os.path.join(LOGS_DIR, f"{script_id}.log")
        if os.path.exists(log_path):
            with open(log_path, 'rb') as f: bot.send_document(call.message.chat.id, f, caption=f"📄 Логи {script_id}")
            bot.answer_callback_query(call.id, "✅ Отправлены!")
        else: bot.answer_callback_query(call.id, "Логов нет")
    elif action == "delete":
        delete_script(script_id, call.from_user.id)
        script_dir = os.path.join(SCRIPTS_DIR, str(call.from_user.id), script_id)
        if os.path.exists(script_dir): shutil.rmtree(script_dir)
        bot.answer_callback_query(call.id, "✅ Удалён!")
    show_scripts(call.message, edit=True)

def show_scripts(message, edit=False):
    user_id = message.chat.id
    scripts = get_user_scripts(user_id)
    if not scripts:
        text = "📭 Нет скриптов"
        if edit: bot.edit_message_text(text, message.chat.id, message.message_id)
        else: bot.send_message(message.chat.id, text)
        return
    text = f"📋 <b>Ваши скрипты ({len(scripts)}):</b>\n\n"
    markup = InlineKeyboardMarkup(row_width=2)
    for s in scripts:
        status_icon = "🟢" if s['status'] == 'running' else "🔴"
        text += f"{status_icon} <b>{s['name']}</b>\nID: {s['id']}\nPID: {s['pid'] or '-'}\n\n"
        markup.add(InlineKeyboardButton(f"⏹ Стоп {s['id']}", callback_data=f"script:stop:{s['id']}"), InlineKeyboardButton(f"📄 Логи {s['id']}", callback_data=f"script:logs:{s['id']}"), InlineKeyboardButton(f"🗑 Удалить {s['id']}", callback_data=f"script:delete:{s['id']}"))
    if edit: bot.edit_message_text(text, message.chat.id, message.message_id, reply_markup=markup, parse_mode='HTML')
    else: bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='HTML')

def process_promo(message):
    code = message.text.strip().upper()
    success, msg = activate_promo(message.from_user.id, code)
    bot.send_message(message.chat.id, f"{'✅' if success else '❌'} {msg}")

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if bot_status == "stopped" and message.from_user.id not in ADMIN_IDS: bot.reply_to(message, "🔴 Бот остановлен"); return
    user_id = message.from_user.id
    auth_required(message)
    if not check_user_limits(user_id): bot.reply_to(message, "❌ Лимит скриптов"); return
    file_info = bot.get_file(message.document.file_id)
    file_name = message.document.file_name
    file_size = message.document.file_size
    user = get_user(user_id)
    max_size = PREMIUM_MAX_SIZE_MB if user['subscription'] == 'premium' else FREE_MAX_SIZE_MB
    if file_size > max_size * 1024 * 1024: bot.reply_to(message, f"❌ Максимум {max_size} МБ"); return
    temp_dir = os.path.join(TEMP_DIR, str(user_id))
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, file_name)
    try:
        downloaded = bot.download_file(file_info.file_path)
        with open(temp_path, 'wb') as f: f.write(downloaded)
    except Exception as e: bot.reply_to(message, f"❌ Ошибка: {e}"); return
    script_id = str(uuid.uuid4())[:8]
    upload_states[user_id] = {'script_id': script_id, 'temp_path': temp_path, 'file_name': file_name, 'file_size': file_size}
    if file_name.endswith('.zip'):
        extract_to = os.path.join(TEMP_DIR, str(user_id), script_id)
        os.makedirs(extract_to, exist_ok=True)
        ok, msg = extract_zip(temp_path, extract_to)
        if not ok: bot.reply_to(message, f"❌ Ошибка архива: {msg}"); cleanup_temp(user_id); return
        py_files = find_py_files(extract_to)
        if not py_files: bot.reply_to(message, "❌ Нет .py файлов"); cleanup_temp(user_id); return
        upload_states[user_id].update({'extract_to': extract_to, 'py_files': py_files})
        markup = InlineKeyboardMarkup(row_width=1)
        for pf in py_files:
            rel = os.path.relpath(pf, extract_to)
            markup.add(InlineKeyboardButton(rel, callback_data=f"sel:{rel}"))
        bot.send_message(user_id, "📁 Выберите главный файл:", reply_markup=markup)
    else: finish_script(user_id, temp_path, file_name)

@bot.callback_query_handler(func=lambda call: call.data.startswith('sel:'))
def select_callback(call):
    user_id = call.from_user.id
    if user_id not in upload_states: bot.answer_callback_query(call.id, "Устарело"); return
    rel_path = call.data.split(':', 1)[1]
    state = upload_states[user_id]
    extract_to = state.get('extract_to')
    full_path = os.path.join(extract_to, rel_path)
    state['selected_main'] = rel_path
    bot.edit_message_text(f"✅ {rel_path}\nЗапускаю...", user_id, call.message.message_id)
    bot.answer_callback_query(call.id)
    finish_script(user_id, full_path, state['file_name'])

def finish_script(user_id, script_path, original_filename):
    state = upload_states.get(user_id)
    script_id = state['script_id'] if state else str(uuid.uuid4())[:8]
    file_size = state['file_size'] if state else os.path.getsize(script_path)
    user_dir = os.path.join(SCRIPTS_DIR, str(user_id), script_id)
    os.makedirs(user_dir, exist_ok=True)
    if state and 'extract_to' in state:
        for item in os.listdir(state['extract_to']):
            s = os.path.join(state['extract_to'], item)
            d = os.path.join(user_dir, item)
            if os.path.isdir(s): shutil.copytree(s, d, dirs_exist_ok=True)
            else: shutil.copy2(s, d)
        main_rel = state.get('selected_main')
        main_file = os.path.join(user_dir, main_rel) if main_rel else script_path
    else:
        dest = os.path.join(user_dir, original_filename)
        shutil.move(script_path, dest)
        main_file = dest
    add_script(script_id, user_id, original_filename, user_dir, file_size)
    pid, error = run_script(script_id, main_file)
    if error: bot.send_message(user_id, f"❌ Ошибка: {error}"); return
    update_script_status(script_id, 'running', pid)
    bot.send_message(user_id, f"✅ <b>Запущен!</b>\nID: {script_id}\nPID: {pid}", parse_mode='HTML')
    cleanup_temp(user_id)

@bot.pre_checkout_query_handler(func=lambda query: True)
def pre_checkout(query): bot.answer_pre_checkout_query(query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def payment_success(message):
    activate_premium(message.from_user.id)
    bot.send_message(message.chat.id, "🌟 Премиум активирован!", parse_mode='HTML')

def monitor():
    while True:
        try:
            for script in get_all_running_scripts():
                if not is_process_alive(script['pid']): update_script_status(script['id'], 'stopped')
        except: pass
        time.sleep(MONITOR_INTERVAL)

if __name__ == '__main__':
    print(f"🤖 Python Hosting Bot v{VERSION}")
    init_db()
    threading.Thread(target=monitor, daemon=True).start()
    print("✅ Бот запущен!")
    while True:
        try: bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except ReadTimeout: print("⚠️ Таймаут..."); time.sleep(5); continue
        except Exception as e: print(f"❌ Ошибка: {e}"); time.sleep(5); continue
EOF
