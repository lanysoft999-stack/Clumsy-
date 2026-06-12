# Вставь перед строкой bot.infinity_polling():
# ========== АНТИ-СОН ==========
def keep_alive():
    """Пингует Telegram API каждые 5 минут"""
    while True:
        time.sleep(300)
        try:
            requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
        except:
            pass

threading.Thread(target=keep_alive, daemon=True).start()
