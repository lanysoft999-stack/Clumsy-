import asyncio
import logging
import json
import os
import random
import string
import datetime
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ⚙️ НАСТРОЙКИ
BOT_TOKEN = os.getenv("BOT_TOKEN", "8786847551:AAHghZ-NupfSk7cB7srYDdsiz5X3tmHqNZk")
ADMIN_IDS = [314148464]
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN", "593773:AAOki3WcSohzfdDIuSnQEPxMpWmvfD64E7Y")

DATA_FILE = "bot_data.json"
CHANNEL_FILE = "channel.json"

PRIVATE_CHANNEL_ID = -1004433873754
PRIVATE_CHANNEL_LINK = "https://t.me/+piQe0bSRCxZiMWU0"
USD_RATE = 98.5

HWID_RESET_LIMIT = 2
HWID_RESET_WINDOW_DAYS = 7
NOTIFY_DAYS = 3

PAYMENT_DETAILS = {"sbp": "💳 СБП: 2202206714879132\nБанк: Сбер\nПолучатель: Иван И."}
SECTION_PHOTOS = {"main": None, "profile": None, "shop": None, "support": None}

class States(StatesGroup):
    waiting_crypto_amount = State()
    waiting_sbp_amount = State()
    waiting_broadcast = State()
    waiting_photo_section = State()
    waiting_gift_username = State()

async def replace_message(callback: CallbackQuery, text: str, markup=None, section: str = None):
    try:
        if section:
            data = await load_data()
            photo_id = data.get("section_photos", SECTION_PHOTOS).get(section)
            if photo_id:
                try:
                    await callback.message.edit_media(types.InputMediaPhoto(media=photo_id, caption=text, parse_mode="HTML"), reply_markup=markup)
                    return
                except:
                    try: await callback.message.delete()
                    except: pass
                    await bot.send_photo(callback.from_user.id, photo_id, caption=text, reply_markup=markup, parse_mode="HTML")
                    return
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except:
        try: await callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except:
            try: await callback.message.delete()
            except: pass
            await bot.send_message(callback.from_user.id, text, reply_markup=markup, parse_mode="HTML")

async def send_with_photo(chat_id, text, markup=None, section=None):
    if section:
        data = await load_data()
        photo_id = data.get("section_photos", SECTION_PHOTOS).get(section)
        if photo_id:
            try: await bot.send_photo(chat_id, photo_id, caption=text, reply_markup=markup, parse_mode="HTML"); return
            except: pass
    await bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

async def load_data():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for k in ["pending_deposits", "crypto_invoices", "notified_users"]: data.setdefault(k, {} if k != "notified_users" else [])
            data.setdefault("section_photos", SECTION_PHOTOS.copy())
            for uid in data.get("users", {}):
                data["users"][uid].setdefault("hwid_resets", [])
                data["users"][uid].setdefault("banned", False)
                for lic in data["users"][uid].get("licenses", []):
                    if "expiration_date" not in lic and "purchase_date" in lic:
                        lic["expiration_date"] = (parse_date(lic["purchase_date"]) + datetime.timedelta(days=lic.get("duration_days", 7))).strftime("%d.%m.%Y %H:%M")
                    for f in ["gifted_by", "gifted_to"]: lic.setdefault(f, None)
            return data
    except: return {"users": {}, "pending_deposits": {}, "crypto_invoices": {}, "section_photos": SECTION_PHOTOS.copy(), "notified_users": []}

async def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)

def load_channel():
    try:
        with open(CHANNEL_FILE, 'r') as f: return json.load(f).get("channel")
    except: return None

def save_channel(ch): 
    with open(CHANNEL_FILE, 'w') as f: json.dump({"channel": ch}, f)

def generate_license_key(existing_keys):
    chars = string.ascii_uppercase + string.digits
    while True:
        key = "Clamcy-" + '-'.join([''.join(random.choices(chars, k=4)) for _ in range(3)])
        if key not in existing_keys: return key

def parse_date(s):
    if not s: return datetime.datetime.now()
    for fmt in ["%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"]:
        try: return datetime.datetime.strptime(s, fmt)
        except: continue
    try: return datetime.datetime.fromisoformat(s)
    except: return datetime.datetime.now()

def get_hwid_resets_left(user):
    now = datetime.datetime.now()
    recent = [r for r in user.get("hwid_resets", []) if parse_date(r) > now - datetime.timedelta(days=HWID_RESET_WINDOW_DAYS)]
    left = max(0, HWID_RESET_LIMIT - len(recent))
    if left == 0 and recent: return 0, min(parse_date(r) for r in recent) + datetime.timedelta(days=HWID_RESET_WINDOW_DAYS)
    return left, now

async def ban_user_from_channel(uid):
    try: await bot.ban_chat_member(PRIVATE_CHANNEL_ID, uid); return True
    except: return False

async def unban_user_from_channel(uid):
    try: await bot.unban_chat_member(PRIVATE_CHANNEL_ID, uid); return True
    except: return False

def main_menu():
    b = InlineKeyboardBuilder()
    b.button(text="👤 Профиль", callback_data="profile")
    b.button(text="🛒 Магазин", callback_data="shop")
    b.button(text="📞 Поддержка", callback_data="support")
    b.adjust(2, 1)
    return b.as_markup()

def admin_menu():
    b = InlineKeyboardBuilder()
    for t, c in [("📊 Статистика","admin_stats"),("👥 Пользователи","admin_users"),("📢 Рассылка","admin_broadcast"),
                 ("💳 СБП","admin_payments"),("⏳ Заявки СБП","admin_deposits"),("🖼 Фото","admin_photos"),("📢 Канал","admin_channel")]:
        b.button(text=t, callback_data=c)
    b.adjust(2)
    return b.as_markup()

def back_btn(cb, text="‹ Назад"):
    b = InlineKeyboardBuilder(); b.button(text=text, callback_data=cb); return b.as_markup()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== CRYPTO BOT ==========
async def create_crypto_invoice(usdt, uid):
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
    data = {"asset":"USDT","amount":str(usdt),"description":f"Clamcy {usdt} USDT","payload":json.dumps({"user_id":uid,"amount_rub":round(usdt*USD_RATE,2)}),"allow_comments":False,"allow_anonymous":False}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://pay.crypt.bot/api/createInvoice", headers=headers, json=data) as r:
                res = await r.json()
                return res["result"] if res.get("ok") else None
    except: return None

async def check_crypto_invoice(inv_id):
    headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://pay.crypt.bot/api/getInvoices", headers=headers, json={"invoice_ids":str(inv_id)}) as r:
                res = await r.json()
                return res["result"]["items"][0] if res.get("ok") and res["result"]["items"] else None
    except: return None

async def check_licenses_and_notify():
    while True:
        try:
            data = await load_data()
            changed, notified, now = False, data.get("notified_users", []), datetime.datetime.now()
            for uid, u in data.get("users", {}).items():
                expired, forever = True, False
                for lic in u.get("licenses", []):
                    if lic.get("duration_days", 0) >= 99999: forever = True; expired = False; continue
                    try: exp = parse_date(lic["expiration_date"])
                    except: continue
                    nk = f"{uid}_{lic['key']}"
                    if 0 < (exp - now).days <= NOTIFY_DAYS and nk not in notified:
                        try: await bot.send_message(int(uid), f"⚠️ Лицензия истекает!\n🔑 <code>{lic['key']}</code>\n⏳ {(exp-now).days} дн.\n🛒 Продлите!", parse_mode="HTML"); notified.append(nk); changed = True
                        except: pass
                    if now < exp: expired = False
                if forever: continue
                if (not u.get("licenses") or expired) and not u.get("banned"):
                    if await ban_user_from_channel(int(uid)):
                        u["banned"], u["in_channel"], changed = True, False, True
                        notified = [n for n in notified if not n.startswith(f"{uid}_")]
                        try: await bot.send_message(int(uid), "🔨 Лицензия истекла! Вы забанены.\n🛒 Купите новую!", parse_mode="HTML")
                        except: pass
            if changed: data["notified_users"] = notified; await save_data(data)
            await asyncio.sleep(300)
        except: await asyncio.sleep(300)

# ========== API ДЛЯ ПРИЛОЖЕНИЯ ==========
async def handle_api(request):
    try:
        body = await request.json()
        action = body.get("action")
        data = await load_data()
        
        if action == "check_license":
            key = body.get("key", "").strip()
            hwid = body.get("hwid", "")
            found = None
            for uid, u in data.get("users", {}).items():
                for lic in u.get("licenses", []):
                    if lic["key"] == key: found = lic; break
                if found: break
            
            if not found: return web.json_response({"valid": False, "error": "Ключ не найден"})
            
            exp = parse_date(found.get("expiration_date", ""))
            now = datetime.datetime.now()
            
            if found.get("duration_days", 0) < 99999 and now > exp:
                return web.json_response({"valid": False, "error": "Срок истёк"})
            if found.get("status") == "banned":
                return web.json_response({"valid": False, "error": "Заблокирована"})
            if not found.get("hwid") and hwid:
                found["hwid"] = hwid; found["last_use"] = now.strftime("%d.%m.%Y %H:%M"); await save_data(data)
            if found.get("hwid") and found["hwid"] != hwid and hwid:
                return web.json_response({"valid": False, "error": "Привязан к другому устройству"})
            
            remaining = max(0, (exp - now).days)
            return web.json_response({"valid": True, "key": key, "product": found.get("product", "Clamcy"),
                "duration_days": found.get("duration_days", 0), "remaining_days": remaining if found.get("duration_days", 0) < 99999 else 99999,
                "expiration_date": found.get("expiration_date", ""), "hwid": found.get("hwid", "")})
        
        elif action == "bind_hwid":
            key, hwid = body.get("key", "").strip(), body.get("hwid", "")
            for uid, u in data.get("users", {}).items():
                for lic in u.get("licenses", []):
                    if lic["key"] == key:
                        if lic.get("hwid") and lic["hwid"] != hwid: return web.json_response({"success": False, "error": "Уже привязан"})
                        lic["hwid"] = hwid; lic["last_use"] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M"); await save_data(data)
                        return web.json_response({"success": True})
            return web.json_response({"success": False, "error": "Ключ не найден"})
        
        return web.json_response({"valid": False, "error": "Неизвестное действие"})
    except Exception as e:
        logging.error(f"API: {e}")
        return web.json_response({"valid": False, "error": str(e)})

# ========== СТАРТ ==========
@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    await state.clear()
    uid = str(message.from_user.id)
    data = await load_data()
    ref = message.text.split("ref_")[1] if message.text and "ref_" in message.text else None
    
    if uid not in data["users"]:
        data["users"][uid] = {"first_name": message.from_user.first_name or "Пользователь","username": message.from_user.username or "","balance_rub": 0,"referrals": 0,
            "ref_link": f"t.me/{(await bot.get_me()).username}?start=ref_{uid}","licenses": [],"in_channel": False,"banned": False,"hwid_resets": [],"joined": datetime.datetime.now().strftime("%d.%m.%Y %H:%M")}
        if ref and ref in data["users"]: data["users"][ref]["referrals"] += 1; data["users"][ref]["balance_rub"] += 50
        await save_data(data)
    
    if message.from_user.id in ADMIN_IDS:
        await send_with_photo(message.chat.id, "👑 <b>Админ-панель Clamcy</b>", admin_menu(), "main"); return
    
    ch = load_channel()
    if ch:
        try:
            m = await bot.get_chat_member(ch, message.from_user.id)
            if m.status in ["left", "kicked"]:
                b = InlineKeyboardBuilder(); b.button(text="🔗 Подписаться", url=f"https://t.me/{ch.replace('@','')}"); b.button(text="✅ Проверить", callback_data="check_sub")
                await message.answer(f"🔒 Подпишитесь на {ch}", reply_markup=b.as_markup()); return
        except: pass
    
    await send_with_photo(message.chat.id, f"🎮 <b>Clamcy License Shop</b>\n\nДобро пожаловать, {data['users'][uid]['first_name']}!\nВыберите действие 👇", main_menu(), "main")

@dp.callback_query(F.data == "check_sub")
async def check_sub(callback: CallbackQuery):
    ch = load_channel()
    if ch:
        try:
            if (await bot.get_chat_member(ch, callback.from_user.id)).status not in ["left", "kicked"]:
                await replace_message(callback, "✅ Доступ открыт!", main_menu()); return
        except: pass
    await callback.answer("❌ Не подписались!", show_alert=True)

# ========== ПРОФИЛЬ ==========
@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    u = (await load_data())["users"].get(uid, {})
    left, _ = get_hwid_resets_left(u)
    text = f"👤 <b>{u.get('first_name','Пользователь')}</b>\n\n💰 Баланс: <b>{u.get('balance_rub',0):.2f} ₽</b>\n🔑 Лицензий: <b>{len(u.get('licenses',[]))}</b>\n👥 Рефералов: <b>{u.get('referrals',0)}</b>\n🔄 HWID: <b>{left}/{HWID_RESET_LIMIT}</b>\n🔨 Забанен: {'🔨 Да' if u.get('banned') else '✅ Нет'}\n\n🆔 <code>{uid}</code>"
    b = InlineKeyboardBuilder()
    for t, c in [("🗃 Мои лицензии","my_licenses"),("💸 Пополнить","top_up"),("📇 Рефералы","referral"),("‹ Назад","back_main")]: b.button(text=t, callback_data=c)
    b.adjust(1)
    await replace_message(callback, text, b.as_markup(), "profile")
    await callback.answer()

# ========== ПОПОЛНЕНИЕ ==========
@dp.callback_query(F.data == "top_up")
async def top_up(callback: CallbackQuery):
    b = InlineKeyboardBuilder(); b.button(text="₿ Крипта (USDT)", callback_data="crypto_start"); b.button(text="💳 СБП (RUB)", callback_data="sbp_start"); b.button(text="‹ Назад", callback_data="profile"); b.adjust(1)
    await replace_message(callback, "💳 <b>Выберите способ:</b>\n\n₿ Крипта — авто\n💳 СБП — перевод", b.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "crypto_start")
async def crypto_start(callback: CallbackQuery, state: FSMContext):
    await replace_message(callback, f"₿ Введите сумму в USDT (0.1-1000)\n📊 1 USDT ≈ {USD_RATE} ₽", back_btn("top_up"))
    await state.set_state(States.waiting_crypto_amount); await callback.answer()

@dp.message(States.waiting_crypto_amount)
async def crypto_amount(message: Message, state: FSMContext):
    try:
        usdt = float(message.text)
        if usdt < 0.1 or usdt > 1000: await message.answer("❌ 0.1-1000!"); return
    except: await message.answer("❌ Число!"); return
    await state.clear()
    inv = await create_crypto_invoice(usdt, str(message.from_user.id))
    if not inv: await message.answer("❌ Ошибка!"); return
    data = await load_data(); data["crypto_invoices"][str(inv["invoice_id"])] = {"user_id": str(message.from_user.id), "amount_rub": round(usdt*USD_RATE,2)}; await save_data(data)
    b = InlineKeyboardBuilder(); b.button(text="₿ Оплатить", url=inv["pay_url"]); b.button(text="✅ Я оплатил", callback_data=f"check_crypto_{inv['invoice_id']}"); b.button(text="‹ Назад", callback_data="top_up"); b.adjust(1)
    await message.answer(f"₿ Счёт создан!\n💵 {usdt} USDT\n💰 {round(usdt*USD_RATE,2)} ₽\nКурс: {USD_RATE}\n\n1. Оплатите\n2. «Я оплатил»\n⚡ Автозачисление!", reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto(callback: CallbackQuery):
    inv = await check_crypto_invoice(int(callback.data.replace("check_crypto_", "")))
    if not inv: await callback.answer("❌ Не найден!", show_alert=True); return
    if inv["status"] == "paid":
        data = await load_data(); info = data["crypto_invoices"].get(str(inv["invoice_id"]), {})
        uid, amt = info.get("user_id"), info.get("amount_rub", 0)
        if uid and uid in data["users"]:
            data["users"][uid]["balance_rub"] += amt; del data["crypto_invoices"][str(inv["invoice_id"])]; await save_data(data)
            await replace_message(callback, f"✅ +{amt:.2f} ₽\nБаланс: <b>{data['users'][uid]['balance_rub']:.2f} ₽</b>", main_menu())
        else: await callback.answer("✅ Начислено!", show_alert=True)
    else: await callback.answer("❌ Не оплачено!", show_alert=True)

@dp.callback_query(F.data == "sbp_start")
async def sbp_start(callback: CallbackQuery, state: FSMContext):
    await replace_message(callback, "💳 <b>СБП</b>\n\n📥 Введите сумму (10-100000 ₽):", back_btn("top_up"))
    await state.set_state(States.waiting_sbp_amount); await callback.answer()

@dp.message(States.waiting_sbp_amount)
async def sbp_amount(message: Message, state: FSMContext):
    try:
        amt = float(message.text)
        if amt < 10 or amt > 100000: await message.answer("❌ 10-100000!"); return
    except: await message.answer("❌ Число!"); return
    await state.clear()
    await message.answer(f"💳 <b>СБП Перевод</b>\n\n💰 {amt:.2f} ₽\n\n📝 {PAYMENT_DETAILS['sbp']}\n\n📸 Отправьте скриншот!", reply_markup=back_btn("profile"))
    if not hasattr(dp, "pending_sbp"): dp.pending_sbp = {}
    dp.pending_sbp[message.from_user.id] = {"amount": amt}

@dp.message(F.photo, States.waiting_photo_section)
async def photo_for_section(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS: return
    sec = (await state.get_data()).get("photo_section")
    if not sec: await state.clear(); return
    data = await load_data(); data.setdefault("section_photos", SECTION_PHOTOS.copy()); data["section_photos"][sec] = message.photo[-1].file_id; await save_data(data)
    await message.answer(f"✅ Фото для {sec} установлено!"); await message.answer_photo(message.photo[-1].file_id, caption="📸 Превью")
    await state.clear()

@dp.message(F.photo)
async def receive_sbp_check(message: Message):
    if not hasattr(dp, "pending_sbp"): dp.pending_sbp = {}
    if message.from_user.id not in dp.pending_sbp: return
    info = dp.pending_sbp.pop(message.from_user.id)
    data = await load_data(); data.setdefault("pending_deposits", {})
    did = str(len(data["pending_deposits"]) + 1)
    data["pending_deposits"][did] = {"user_id": str(message.from_user.id), "amount": info["amount"], "photo_id": message.photo[-1].file_id, "status": "pending", "date": datetime.datetime.now().strftime("%d.%m.%Y %H:%M")}
    await save_data(data)
    await message.answer(f"✅ Чек получен!\n💰 {info['amount']:.2f} ₽", reply_markup=main_menu())
    b = InlineKeyboardBuilder(); b.button(text="✅ Подтвердить", callback_data=f"dep_approve_{did}"); b.button(text="❌ Отклонить", callback_data=f"dep_reject_{did}"); b.adjust(2)
    for aid in ADMIN_IDS:
        try: await bot.send_photo(aid, message.photo[-1].file_id, caption=f"💰 СБП #{did}\n👤 {message.from_user.id}\n💰 {info['amount']:.2f} ₽", reply_markup=b.as_markup())
        except: pass

@dp.callback_query(F.data.startswith("dep_approve_"))
async def approve_deposit(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    did = callback.data.replace("dep_approve_", "")
    data = await load_data(); dep = data.get("pending_deposits", {}).get(did)
    if not dep or dep["status"] != "pending": await callback.answer("⏳ Обработано!"); return
    if dep["user_id"] not in data["users"]: await callback.answer("❌ Нет пользователя!"); return
    data["users"][dep["user_id"]]["balance_rub"] += dep["amount"]; data["pending_deposits"][did]["status"] = "approved"; await save_data(data)
    try: await bot.send_message(int(dep["user_id"]), f"✅ +{dep['amount']:.2f} ₽")
    except: pass
    await callback.message.edit_caption(callback.message.caption + f"\n\n✅ +{dep['amount']:.2f} ₽")
    await callback.answer("✅")

@dp.callback_query(F.data.startswith("dep_reject_"))
async def reject_deposit(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    did = callback.data.replace("dep_reject_", "")
    data = await load_data(); dep = data.get("pending_deposits", {}).get(did)
    if not dep or dep["status"] != "pending": await callback.answer("⏳ Обработано!"); return
    data["pending_deposits"][did]["status"] = "rejected"; await save_data(data)
    try: await bot.send_message(int(dep["user_id"]), "❌ Отклонено. @hesers")
    except: pass
    await callback.message.edit_caption(callback.message.caption + "\n\n❌ ОТКЛОНЕНО")
    await callback.answer("❌")

@dp.callback_query(F.data == "admin_deposits")
async def admin_deposits(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    pending = {k: v for k, v in (await load_data()).get("pending_deposits", {}).items() if v["status"] == "pending"}
    if not pending: await replace_message(callback, "⏳ Нет заявок.", back_btn("back_admin")); return
    text = "⏳ <b>Заявки СБП:</b>\n\n" + "\n".join([f"#{did} | {d.get('first_name','?')}\n💰 {d['amount']:.2f} ₽\n" for did, d in list(pending.items())[:10]])
    await replace_message(callback, text, back_btn("back_admin"))
    await callback.answer()

# ========== ЛИЦЕНЗИИ ==========
@dp.callback_query(F.data == "my_licenses")
async def my_licenses(callback: CallbackQuery):
    uid = str(callback.from_user.id)
    u = (await load_data()).get("users", {}).get(uid)
    if not u: await callback.answer("Не найден!", show_alert=True); return
    lic = u.get("licenses", [])
    if not lic: await replace_message(callback, "📂 Нет лицензий.\n🛒 Купите в магазине!", back_btn("profile")); await callback.answer(); return
    lic = lic[-1]
    exp = parse_date(lic.get("expiration_date", "")); now = datetime.datetime.now(); rem = max(0, (exp - now).days)
    dur, hwid, st = lic.get("duration_days", 0), lic.get("hwid"), lic.get("status", "active")
    if st == "banned": status, rem_text = "🚫 Заблокирована", "Заблокирована"
    elif dur >= 99999: status, rem_text = "🟢 Навсегда", "Неограниченно"
    elif exp > now: status, rem_text = "🟢 Активна", f"{rem} дн."
    else: status, rem_text = "🔴 Истекла", "Истекла"
    left, nr = get_hwid_resets_left(u)
    hw_info = f"🔄 HWID: <b>{left}/{HWID_RESET_LIMIT}</b>" if left > 0 else f"🔄 Новые: <b>{nr.strftime('%d.%m.%Y %H:%M')}</b>"
    gift = ""; 
    if lic.get("gifted_by"): gift = f"🎁 От: {(await load_data())['users'].get(lic['gifted_by'],{}).get('first_name','?')}\n"
    text = f"📜 <b>{lic.get('product','Clamcy')}</b>\n\n🔑 <code>{lic['key']}</code>\n📊 {status}\n🖥 {'✅ Привязано' if hwid else '❌ Не привязано'}\n⏳ {rem_text}\n{gift}🕐 {lic.get('last_use','?')}\n\n{hw_info}"
    kb = InlineKeyboardBuilder(); kb.button(text="⚜ Скачать", url=lic.get("invite_link", PRIVATE_CHANNEL_LINK)); kb.button(text="♻️ Сбросить HWID", callback_data=f"reset_hwid_{lic['key']}")
    if not lic.get("gifted_to") and status == "🟢 Активна": kb.button(text="🎁 Подарить", callback_data=f"gift_select_{lic['key']}")
    kb.button(text="‹ Назад", callback_data="profile"); kb.adjust(1)
    await replace_message(callback, text, kb.as_markup()); await callback.answer()

@dp.callback_query(F.data.startswith("gift_select_"))
async def gift_select(callback: CallbackQuery, state: FSMContext):
    await state.update_data(gift_key=callback.data.replace("gift_select_", "")); await state.set_state(States.waiting_gift_username)
    await replace_message(callback, "🎁 Введите @username или ID:", back_btn("my_licenses")); await callback.answer()

@dp.message(States.waiting_gift_username)
async def gift_username(message: Message, state: FSMContext):
    target = message.text.strip().replace("@", ""); data = await load_data(); tid = None
    if target.isdigit(): tid = target
    else:
        for uid, u in data["users"].items():
            if u.get("username", "").lower() == target.lower(): tid = uid; break
    if not tid: await message.answer("❌ Не найден!"); await state.clear(); return
    if tid not in data["users"]: data["users"][tid] = {"first_name": target, "username": target, "balance_rub": 0, "referrals": 0, "licenses": [], "in_channel": False, "banned": False, "hwid_resets": []}
    key = (await state.get_data())["gift_key"]; uid = str(message.from_user.id); found = False
    for lic in data["users"][uid].get("licenses", []):
        if lic["key"] == key and not lic.get("gifted_to"):
            lic["gifted_to"], lic["gifted_by"] = tid, uid
            nl = lic.copy(); nl["gifted_to"], nl["gifted_by"] = None, uid; nl["purchase_date"] = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
            data["users"][tid]["licenses"].append(nl); data["users"][uid]["licenses"].remove(lic); found = True; break
    if found:
        await unban_user_from_channel(int(tid)); data["users"][tid]["banned"] = False; await save_data(data)
        await message.answer(f"✅ Подарено!\n👤 {data['users'][tid]['first_name']}", reply_markup=back_btn("profile"))
        try: await bot.send_message(int(tid), f"🎁 Вам подарили ключ!\n🔑 <code>{key}</code>", parse_mode="HTML")
        except: pass
    else: await message.answer("❌ Ошибка!")
    await state.clear()

@dp.callback_query(F.data.startswith("reset_hwid_"))
async def reset_hwid(callback: CallbackQuery):
    uid = str(callback.from_user.id); key = callback.data.replace("reset_hwid_", ""); data = await load_data()
    u = data["users"].get(uid, {})
    if not u: await callback.answer("❌ Не найден!", show_alert=True); return
    left, nr = get_hwid_resets_left(u)
    if left == 0: await callback.answer(f"❌ Лимит! Новые: {nr.strftime('%d.%m.%Y %H:%M')}", show_alert=True); return
    for lic in u.get("licenses", []):
        if lic["key"] == key: lic["hwid"], lic["last_use"] = None, datetime.datetime.now().strftime("%d.%m.%Y %H:%M"); u.setdefault("hwid_resets", []).append(datetime.datetime.now().isoformat()); await save_data(data); await callback.answer(f"✅ HWID сброшен! Осталось: {left-1}/{HWID_RESET_LIMIT}", show_alert=True); await my_licenses(callback); return
    await callback.answer("❌ Не ваша!", show_alert=True)

@dp.callback_query(F.data == "referral")
async def referral(callback: CallbackQuery):
    u = (await load_data())["users"].get(str(callback.from_user.id), {})
    await replace_message(callback, f"📇 <b>Рефералы</b>\n\n👥 {u.get('referrals',0)}\n💰 Бонус: 50 ₽\n\n🔗 <code>{u.get('ref_link','')}</code>", back_btn("profile"))
    await callback.answer()

# ========== МАГАЗИН ==========
@dp.callback_query(F.data == "shop")
async def shop(callback: CallbackQuery):
    b = InlineKeyboardBuilder()
    for t, c in [("⚡ 7 дней • 149₽","clamcy_7"),("🔥 30 дней • 449₽","clamcy_30"),("💎 60 дней • 899₽","clamcy_60"),("👑 140 дней • 1499₽","clamcy_140")]: b.button(text=t, callback_data=f"buy_{c}")
    b.button(text="‹ Назад", callback_data="back_main"); b.adjust(1)
    await replace_message(callback, "🛒 <b>Магазин Clamcy</b>\n\nВыберите тариф:", b.as_markup(), "shop")
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def buy_license(callback: CallbackQuery):
    pk = callback.data.replace("buy_", "")
    products = {"clamcy_7": ("⚡ 7 дней", 7, 149), "clamcy_30": ("🔥 30 дней", 30, 449), "clamcy_60": ("💎 60 дней", 60, 899), "clamcy_140": ("👑 140 дней", 140, 1499)}
    if pk not in products: await callback.answer("❌ Не найден!"); return
    name, days, price = products[pk]
    uid = str(callback.from_user.id); u = (await load_data())["users"].get(uid, {})
    if any(parse_date(l["expiration_date"]) > datetime.datetime.now() for l in u.get("licenses", []) if l["key"].startswith("Clamcy") and l.get("duration_days", 0) < 99999):
        b = InlineKeyboardBuilder(); b.button(text="🗃 Лицензии", callback_data="my_licenses"); b.button(text="‹ Назад", callback_data="shop")
        await replace_message(callback, "❗️ Уже есть активная!", b.as_markup()); await callback.answer(); return
    bal = u.get("balance_rub", 0)
    b = InlineKeyboardBuilder(); b.button(text=f"💳 Купить ({price}₽)", callback_data=f"confirm_{pk}"); b.button(text="💸 Пополнить", callback_data="top_up"); b.button(text="‹ Назад", callback_data="shop"); b.adjust(1)
    text = f"📦 <b>{name}</b>\n\n⏱ {days} дн.\n💰 <b>{price} ₽</b>\n\nБаланс: <b>{bal:.2f} ₽</b>\n" + ("✅ Хватает!" if bal >= price else f"❌ Не хватает: <b>{price - bal:.2f} ₽</b>")
    await replace_message(callback, text, b.as_markup()); await callback.answer()

@dp.callback_query(F.data.startswith("confirm_"))
async def confirm_purchase(callback: CallbackQuery):
    pk = callback.data.replace("confirm_", "")
    products = {"clamcy_7": ("⚡ 7 дней", 7, 149), "clamcy_30": ("🔥 30 дней", 30, 449), "clamcy_60": ("💎 60 дней", 60, 899), "clamcy_140": ("👑 140 дней", 140, 1499)}
    if pk not in products: await callback.answer("❌ Ошибка!"); return
    name, days, price = products[pk]
    uid = str(callback.from_user.id); data = await load_data(); u = data["users"].get(uid, {})
    if u.get("balance_rub", 0) < price: await callback.answer("❌ Мало средств!", show_alert=True); return
    data["users"][uid]["balance_rub"] -= price
    key = generate_license_key([l["key"] for uu in data["users"].values() for l in uu.get("licenses", [])])
    link = PRIVATE_CHANNEL_LINK
    try: link = (await bot.create_chat_invite_link(PRIVATE_CHANNEL_ID, member_limit=1, name=f"Clamcy_{key[:8]}")).invite_link
    except: pass
    now = datetime.datetime.now(); exp = now + datetime.timedelta(days=days)
    data["users"][uid]["licenses"].append({"key": key, "purchase_date": now.strftime("%d.%m.%Y %H:%M"), "duration_days": days, "expiration_date": exp.strftime("%d.%m.%Y %H:%M"), "product": name, "hwid": None, "last_use": now.strftime("%d.%m.%Y %H:%M"), "invite_link": link, "status": "active", "gifted_by": None, "gifted_to": None})
    unban_msg = ""
    if u.get("banned"): await unban_user_from_channel(int(uid)); data["users"][uid]["banned"] = False; unban_msg = "\n\n🔓 Вы разбанены!"
    data["users"][uid]["in_channel"] = False; await save_data(data)
    b = InlineKeyboardBuilder(); b.button(text="⚜ Вступить", url=link); b.button(text="🗃 Лицензии", callback_data="my_licenses"); b.button(text="‹ Назад", callback_data="shop"); b.adjust(1)
    await replace_message(callback, f"✅ <b>Покупка!</b>\n\n📦 {name}\n⏱ {days} дн.\n🔑 <code>{key}</code>\n\n💰 Списано: <b>{price} ₽</b>\nОстаток: <b>{data['users'][uid]['balance_rub']:.2f} ₽</b>{unban_msg}\n\n⚜ Нажмите чтобы вступить!", b.as_markup())
    await callback.answer("✅")

# ========== ПОДДЕРЖКА ==========
@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    b = InlineKeyboardBuilder(); b.button(text="💬 Написать в поддержку", callback_data="start_chat"); b.button(text="‹ Назад", callback_data="back_main"); b.adjust(1)
    await replace_message(callback, "📞 <b>Поддержка Clamcy</b>\n\nЕсть вопросы? Напишите нам!\n\n🕐 Ответ: до 24ч\n👨‍💻 Админ: @hesers\n\nНажмите кнопку ниже 👇", b.as_markup(), "support")
    await callback.answer()

@dp.callback_query(F.data == "start_chat")
async def start_chat(callback: CallbackQuery, state: FSMContext):
    await state.set_state(States.waiting_broadcast); await state.update_data(chat_mode=True)
    await replace_message(callback, "💬 <b>Чат с поддержкой</b>\n\nНапишите сообщение, админ ответит.\n\nДля отмены — кнопка ниже.", back_btn("support"))
    await callback.answer()

@dp.callback_query(F.data.startswith("reply_user_"))
async def reply_user(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS: return
    await state.update_data(reply_to=callback.data.replace("reply_user_", "")); await state.set_state(States.waiting_broadcast)
    await callback.message.edit_text(callback.message.text + "\n\n✉️ <b>Напишите ответ:</b>", reply_markup=back_btn("back_admin"))
    await callback.answer()

@dp.message(States.waiting_broadcast)
async def handle_broadcast_or_chat(message: Message, state: FSMContext):
    ds = await state.get_data()
    
    if ds.get("chat_mode"):
        for aid in ADMIN_IDS:
            try:
                info = f"👤 {message.from_user.first_name} (@{message.from_user.username or 'нет'})\n🆔 <code>{message.from_user.id}</code>"
                kb = InlineKeyboardBuilder(); kb.button(text="✉️ Ответить", callback_data=f"reply_user_{message.from_user.id}")
                if message.text: await bot.send_message(aid, f"📩 <b>Поддержка</b>\n\n{info}\n\n💬 {message.text}", reply_markup=kb.as_markup(), parse_mode="HTML")
                elif message.photo: await bot.send_photo(aid, message.photo[-1].file_id, caption=f"📩 <b>Поддержка</b>\n\n{info}", reply_markup=kb.as_markup(), parse_mode="HTML")
                else: await message.copy_to(aid)
            except: pass
        await message.answer("✅ Отправлено! Админ ответит.", parse_mode="HTML"); await state.clear(); return
    
    if ds.get("reply_to"):
        try:
            if message.text: await bot.send_message(int(ds["reply_to"]), f"📩 <b>Ответ поддержки:</b>\n\n💬 {message.text}", parse_mode="HTML")
            elif message.photo: await bot.send_photo(int(ds["reply_to"]), message.photo[-1].file_id, caption="📩 <b>Ответ поддержки:</b>", parse_mode="HTML")
            else: await message.copy_to(int(ds["reply_to"]))
            await message.answer("✅ Ответ отправлен!")
        except: await message.answer("❌ Не удалось отправить.")
        await state.clear(); return
    
    if message.from_user.id not in ADMIN_IDS: return
    data = await load_data(); success, total = 0, len(data.get("users", {}))
    for uid in data.get("users", {}):
        try: await message.copy_to(int(uid)); success += 1
        except: pass
        await asyncio.sleep(0.05)
    await message.answer(f"📢 ✅ {success}/{total}", reply_markup=admin_menu()); await state.clear()

# ========== АДМИН ==========
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    data = await load_data(); users = data.get("users", {})
    await replace_message(callback, f"📊 <b>Статистика</b>\n\n👥 {len(users)}\n🔑 {sum(len(u.get('licenses',[])) for u in users.values())}\n📢 В канале: {sum(1 for u in users.values() if u.get('in_channel'))}\n🔨 Забанено: {sum(1 for u in users.values() if u.get('banned'))}\n💰 {sum(u.get('balance_rub',0) for u in users.values()):.2f} ₽", back_btn("back_admin"))
    await callback.answer()

@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    data = await load_data(); users = data.get("users", {})
    if not users: await replace_message(callback, "👥 Нет пользователей.", back_btn("back_admin")); return
    su = sorted(users.items(), key=lambda x: (-len(x[1].get("licenses", [])), -x[1].get("balance_rub", 0)))
    text = f"👥 <b>Пользователи ({len(users)}):</b>\n\n"
    for uid, u in su[:20]:
        ls = "🟢" if any(l.get("duration_days", 0) >= 99999 or parse_date(l.get("expiration_date", "")) > datetime.datetime.now() for l in u.get("licenses", [])) else "🔴"
        text += f"{ls} <b>{u.get('first_name','?')}</b>\n   🆔 <code>{uid}</code> | 💰 {u.get('balance_rub',0):.0f}₽ | 🔑 {len(u.get('licenses',[]))} | 👥 {u.get('referrals',0)}\n   📢 {'✅' if u.get('in_channel') else '❌'} | 🔨 {'🔨' if u.get('banned') else '✅'} | 📅 {u.get('joined','')[:10]}\n\n"
    b = InlineKeyboardBuilder()
    for uid, u in su[:15]: b.button(text=f"{u.get('first_name','?')} (ID: {uid})", callback_data=f"user_info_{uid}")
    b.button(text="‹ Назад", callback_data="back_admin"); b.adjust(1)
    await replace_message(callback, text, b.as_markup()); await callback.answer()

@dp.callback_query(F.data.startswith("user_info_"))
async def user_info(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS: return
    uid = callback.data.replace("user_info_", "")
    u = (await load_data())["users"].get(uid)
    if not u: await callback.answer("Не найден!"); return
    lic_text = ""; ac, ec = 0, 0
    for l in u.get("licenses", []):
        exp = parse_date(l.get("expiration_date", "")); dur = l.get("duration_days", 0)
        if l.get("status") == "banned": ls = "🚫"
        elif dur >= 99999: ls = "♾️"; ac += 1
        elif exp > datetime.datetime.now(): ls = "✅"; ac += 1
        else: ls = "❌"; ec += 1
        rem = max(0, (exp - datetime.datetime.now()).days) if dur < 99999 else "∞"
        gift = f" | 🎁 от {(await load_data())['users'].get(l.get('gifted_by',''),{}).get('first_name','?')}" if l.get("gifted_by") else ""
        lic_text += f"  {ls} <code>{l['key'][:20]}...</code>\n     📦 {l.get('product','?')} | ⏱ {dur}д | 🕐 {rem}\n     🖥 HWID: {'✅' if l.get('hwid') else '❌'}{gift}\n\n"
    left, _ = get_hwid_resets_left(u)
    text = f"👤 <b>{u.get('first_name','?')}</b>\n🆔 <code>{uid}</code>\n📞 @{u.get('username','?')}\n\n💰 {u.get('balance_rub',0):.2f} ₽\n📢 В канале: {'✅ Да' if u.get('in_channel') else '❌ Нет'}\n🔨 Забанен: {'🔨 Да' if u.get('banned') else '✅ Нет'}\n👥 Рефералов: {u.get('referrals',0)}\n🔄 HWID: {left}/{HWID_RESET_LIMIT}\n📅 {u.get('joined','')[:10]}\n\n🔑 <b>Лицензии ({len(u.get('licenses',[]))}) — ✅{ac} ❌{ec}:</b>\n{lic_text or '  Нет\n'}"
    b = InlineKeyboardBuilder()
    for t, c in [("🔄 Сбросить ключи",f"reset_keys_{uid}"),("🔄 Сбросить HWID лимит",f"reset_hwid_limit_{uid}"),("💳 Пополнить",f"addbal_{uid}"),("🔓 Разбанить" if u.get('banned') else "🔨 Забанить",f"{'unban' if u.get('banned') else 'ban'}_user_{uid}"),("‹ Назад","admin_users")]: b.button(text=t, callback_data=c)
    b.adjust(1)
    await replace_message(callback, text, b.as_markup()); await callback.answer()

@dp.callback_query(F.data.startswith("ban_user_"))
async def ban_btn(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    uid = cb.data.replace("ban_user_", ""); data = await load_data()
    if uid in data["users"]:
        if await ban_user_from_channel(int(uid)): data["users"][uid]["banned"], data["users"][uid]["in_channel"] = True, False; await save_data(data); await replace_message(cb, f"🔨 {data['users'][uid].get('first_name','?')} забанен!", back_btn("admin_users"))
        else: await cb.answer("❌ Ошибка!", show_alert=True)
    await cb.answer()

@dp.callback_query(F.data.startswith("unban_user_"))
async def unban_btn(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    uid = cb.data.replace("unban_user_", ""); data = await load_data()
    if uid in data["users"]:
        if await unban_user_from_channel(int(uid)): data["users"][uid]["banned"] = False; await save_data(data); await replace_message(cb, f"🔓 {data['users'][uid].get('first_name','?')} разбанен!", back_btn("admin_users"))
        else: await cb.answer("❌ Ошибка!", show_alert=True)
    await cb.answer()

@dp.callback_query(F.data.startswith("reset_hwid_limit_"))
async def reset_hwid_limit_btn(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    uid = cb.data.replace("reset_hwid_limit_", ""); data = await load_data()
    if uid in data["users"]: data["users"][uid]["hwid_resets"] = []; await save_data(data); await replace_message(cb, "✅ Лимит сброшен!", back_btn("admin_users"))
    await cb.answer("✅")

@dp.callback_query(F.data.startswith("reset_keys_"))
async def reset_keys_btn(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    uid = cb.data.replace("reset_keys_", ""); data = await load_data()
    if uid not in data["users"]: await cb.answer("❌ Не найден!"); return
    u = data["users"][uid]; name = u.get("first_name", "?"); cnt = len(u.get("licenses", []))
    u["licenses"] = []; banned = await ban_user_from_channel(int(uid)); u["banned"], u["in_channel"] = True, False; await save_data(data)
    try: await bot.send_message(int(uid), "🔨 Лицензии сброшены. Вы забанены.")
    except: pass
    await replace_message(cb, f"✅ Ключи <b>{name}</b> сброшены! ({cnt} шт.)\n" + ("🔨 Забанен" if banned else "⚠️ Не удалось забанить!"), back_btn("admin_users"))
    await cb.answer("✅")

@dp.callback_query(F.data.startswith("addbal_"))
async def addbal_btn(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    await replace_message(cb, f"💳 <code>/addbalance {cb.data.replace('addbal_','')} сумма</code>", back_btn(f"user_info_{cb.data.replace('addbal_','')}"))
    await cb.answer()

@dp.callback_query(F.data == "admin_payments")
async def admin_payments(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    await replace_message(cb, f"💳 <b>СБП:</b>\n\n{PAYMENT_DETAILS['sbp']}\n\n<code>/setsbp Текст</code>", back_btn("back_admin"))
    await cb.answer()

@dp.message(Command("setsbp"))
async def set_sbp(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    PAYMENT_DETAILS["sbp"] = msg.text.replace("/setsbp ", ""); await msg.answer("✅ СБП обновлены!")

@dp.callback_query(F.data == "admin_photos")
async def admin_photos(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    data = await load_data(); photos = data.get("section_photos", SECTION_PHOTOS)
    text = "🖼 <b>Фото разделов:</b>\n\n" + "\n".join([f"{'✅' if photos.get(s) else '❌'} {s}" for s in ["main","profile","shop","support"]]) + "\n\nВыберите раздел:"
    b = InlineKeyboardBuilder()
    for t, c in [("🏠 Главная","main"),("👤 Профиль","profile"),("🛒 Магазин","shop"),("📞 Поддержка","support")]: b.button(text=t, callback_data=f"set_photo_{c}")
    b.button(text="‹ Назад", callback_data="back_admin"); b.adjust(2)
    await replace_message(cb, text, b.as_markup()); await cb.answer()

@dp.callback_query(F.data.startswith("set_photo_"))
async def set_photo_section(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id not in ADMIN_IDS: return
    sec = cb.data.replace("set_photo_", ""); await state.update_data(photo_section=sec); await state.set_state(States.waiting_photo_section)
    names = {"main":"🏠 Главная","profile":"👤 Профиль","shop":"🛒 Магазин","support":"📞 Поддержка"}
    has = (await load_data()).get("section_photos", {}).get(sec)
    await replace_message(cb, f"📸 <b>{names.get(sec,sec)}</b>\n\nТекущее: {'✅ Есть' if has else '❌ Нет'}\n\n• Отправьте фото\n• <code>удалить</code> — убрать", back_btn("admin_photos"))
    await cb.answer()

@dp.message(States.waiting_photo_section, F.text)
async def delete_section_photo(msg: Message, state: FSMContext):
    if msg.from_user.id not in ADMIN_IDS: return
    if msg.text.lower() != "удалить": await msg.answer("❌ Отправьте фото или <code>удалить</code>"); return
    sec = (await state.get_data()).get("photo_section")
    if not sec: await state.clear(); return
    data = await load_data(); data.setdefault("section_photos", SECTION_PHOTOS.copy()); data["section_photos"][sec] = None; await save_data(data)
    await msg.answer(f"✅ Фото удалено!"); await state.clear()

@dp.callback_query(F.data == "admin_channel")
async def admin_channel(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS: return
    await replace_message(cb, f"📢 Канал: {load_channel() or 'нет'}\n<code>/setchannel @name</code>", back_btn("back_admin"))
    await cb.answer()

@dp.message(Command("setchannel"))
async def set_channel_cmd(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    try: save_channel(msg.text.split()[1]); await msg.answer("✅ Сохранён!")
    except: await msg.answer("❌ /setchannel @name")

@dp.message(Command("addbalance"))
async def add_balance_cmd(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    try:
        parts = msg.text.split(); uid, amt = parts[1], float(parts[2])
        data = await load_data()
        if uid in data["users"]: data["users"][uid]["balance_rub"] += amt; await save_data(data); await msg.answer(f"✅ +{amt} ₽ → {uid}")
        else: await msg.answer("❌ Не найден!")
    except: await msg.answer("❌ /addbalance ID сумма")

@dp.message(Command("resetkeys"))
async def reset_keys_cmd(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    try:
        uid = msg.text.split()[1]; data = await load_data()
        if uid in data["users"]:
            u = data["users"][uid]; cnt = len(u.get("licenses", [])); u["licenses"] = []
            banned = await ban_user_from_channel(int(uid)); u["banned"], u["in_channel"] = True, False; await save_data(data)
            await msg.answer(f"✅ Ключи {u.get('first_name','?')} сброшены! ({cnt} шт.)" + ("\n🔨 Забанен" if banned else "\n⚠️ Не удалось!"))
        else: await msg.answer("❌ Не найден!")
    except: await msg.answer("❌ /resetkeys ID")

@dp.message(Command("check_expired"))
async def check_expired_cmd(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    data = await load_data(); cnt = 0
    for uid, u in data.get("users", {}).items():
        expired = True
        for l in u.get("licenses", []):
            if l.get("duration_days", 0) >= 99999: expired = False; break
            try:
                if datetime.datetime.now() < parse_date(l["expiration_date"]): expired = False; break
            except: continue
        if (not u.get("licenses") or expired) and not u.get("banned"):
            if await ban_user_from_channel(int(uid)): u["banned"], u["in_channel"], cnt = True, False, cnt + 1
    await save_data(data); await msg.answer(f"🔨 Забанено: <b>{cnt}</b>")

@dp.message(Command("check_channel"))
async def check_channel_cmd(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    data = await load_data(); upd = 0
    for uid in list(data.get("users", {}).keys()):
        try:
            is_in = (await bot.get_chat_member(PRIVATE_CHANNEL_ID, int(uid))).status == "member"
            if data["users"][uid].get("in_channel") != is_in: data["users"][uid]["in_channel"] = is_in; upd += 1
        except: data["users"][uid]["in_channel"] = False; upd += 1
    await save_data(data); await msg.answer(f"✅ Обновлено: <b>{upd}</b>")

@dp.message(Command("users"))
async def users_list_cmd(msg: Message):
    if msg.from_user.id not in ADMIN_IDS: return
    users = (await load_data()).get("users", {})
    text = f"👥 <b>Пользователи ({len(users)}):</b>\n\n"
    for uid, u in sorted(users.items(), key=lambda x: -len(x[1].get("licenses", [])))[:20]: text += f"<code>{uid}</code> | {u.get('first_name','?')} | 🔑{len(u.get('licenses',[]))} | 💰{u.get('balance_rub',0):.0f}₽\n"
    await msg.answer(text)

@dp.my_chat_member()
async def chat_member_update(update: types.ChatMemberUpdated):
    if update.chat.id != PRIVATE_CHANNEL_ID: return
    uid = str(update.from_user.id); data = await load_data()
    if uid in data["users"]: data["users"][uid]["in_channel"] = update.new_chat_member.status == "member"; await save_data(data)

@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery, state: FSMContext):
    await state.clear(); await replace_message(cb, "🎮 <b>Clamcy License Shop</b>", main_menu(), "main"); await cb.answer()

@dp.callback_query(F.data == "back_admin")
async def back_admin(cb: CallbackQuery, state: FSMContext):
    await state.clear(); await replace_message(cb, "👑 <b>Админ-панель</b>", admin_menu(), "main"); await cb.answer()

# 🚀 ЗАПУСК ДЛЯ RENDER
async def main():
    if not os.path.exists(DATA_FILE): await save_data({"users": {}, "pending_deposits": {}, "crypto_invoices": {}, "section_photos": SECTION_PHOTOS.copy(), "notified_users": []})
    
    # API сервер
    app = web.Application(); app.router.add_post('/api', handle_api)
    runner = web.AppRunner(app); await runner.setup()
    
    # Render использует PORT из переменных окружения
    port = int(os.getenv("PORT", 8080))
    await web.TCPSite(runner, '0.0.0.0', port).start()
    print(f"✅ API запущен на порту {port}")
    
    print("✅ Clamcy Bot запущен!")
    asyncio.create_task(check_licenses_and_notify())
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
