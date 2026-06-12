# Команда /admin видна только админу, для других скрыта

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS:
        # Не отвечаем вообще — пользователь не узнает о команде
        return
    
    admin_mode[uid] = True
    bot.send_message(uid, "👑 <b>Админ-панель активирована!</b>", reply_markup=admin_keyboard())


# В setup_menu() добавим команду только для админов:

def setup_menu():
    # Общие команды для всех
    commands = [BotCommand("start", "🚀 Главное меню")]
    
    # Секретная команда только для админов
    try:
        for aid in ADMIN_IDS:
            bot.set_my_commands(
                commands + [BotCommand("admin", "👑 Админ-панель")],
                scope=telebot.types.BotCommandScopeChat(aid)
            )
        # Для остальных — только start
        bot.set_my_commands(commands, scope=telebot.types.BotCommandScopeDefault())
    except Exception as e:
        logger.error(f"Setup menu: {e}")
    
    try:
        bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except:
        pass
