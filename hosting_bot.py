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

# ⚙️ НАСТРОЙКИ (Render сам передаст переменные окружения)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8786847551:AAHvx_gUGlcWM5Eq_7d6D_hKXLsXdP2mb-4")
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

# ========== ФУНКЦИИ ==========
async def replace_message(callback: CallbackQuery, text: str, markup=None, section: str = None):
    try:
        if section:
            data = await load_data()
            photo_id = data.get("section_photos", SECTION_PHOTOS).get(section)
            if photo_id:
                try:
                    await callback.message.edit_media(types.InputMediaPhoto(media=photo_id, caption=text, parse_mode="HTML"), reply_markup=markup)
                    return
