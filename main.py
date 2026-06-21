import sqlite3
import telebot
from telebot import types
import random
import string
import threading
import time

# Initialize Bot
API_TOKEN = '8811186023:AAEpQVkWQegBTsoblpsnXIIxtGlLTntpP-U'
bot = telebot.TeleBot(API_TOKEN)

# Master Admin Setup
ADMINS = [8276411342]  

# Temporary memory trackers
ALBUM_COLLECTOR = {}
USER_STATES = {}  

def generate_unique_key(length=8):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def init_db():
    conn = sqlite3.connect('file_store.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stored_messages (
            unique_key TEXT,
            chat_id INTEGER,
            message_id INTEGER,
            media_group_id TEXT DEFAULT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_users (user_id INTEGER PRIMARY KEY)
    ''')
    conn.commit()
    conn.close()

def register_user(user_id):
    conn = sqlite3.connect('file_store.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO bot_users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def is_admin(user_id):
    return user_id in ADMINS

def set_bot_menu_commands():
    commands = [
        types.BotCommand("start", "🚀 Start the bot or fetch stored items"),
        types.BotCommand("genlink", "🔗 Generate a share link for files/media"),
        types.BotCommand("broadcast", "📢 Broadcast message to users (Admin Only)")
    ]
    bot.set_my_commands(commands)

# --- GLOBAL ASYNC BROADCAST HANDLER ---
def async_broadcast_engine(users, original_message, text_payload=None):
    for user in users:
        target_user_id = user[0]
        try:
            if text_payload:
                bot.send_message(target_user_id, text_payload)
            else:
                # This explicitly clones photos, videos, text, or files perfectly
                bot.copy_message(chat_id=target_user_id, from_chat_id=original_message.chat.id, message_id=original_message.message_id)
        except Exception:
            pass

def trigger_broadcast_sending(message, text_payload=None, target_msg=None):
    conn = sqlite3.connect('file_store.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM bot_users")
    users = cursor.fetchall()
    conn.close()
    
    msg_to_copy = target_msg if target_msg else message
    threading.Thread(target=async_broadcast_engine, args=(users, msg_to_copy, text_payload)).start()
    bot.reply_to(message, "Message Sent To Everywhere bot exists ✅")

# --- BROADCAST CONTROLLER ---
@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(message):
    register_user(message.from_user.id)
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Only @HarshInfo Can use this command")
        return
    
    # Pathway 1: /broadcast by replying to an existing media/text message
    if message.reply_to_message:
        trigger_broadcast_sending(message, target_msg=message.reply_to_message)
        return

    command_text = message.text.split(maxsplit=1)
    
    # Pathway 2: /broadcast completely blank (prompts for next message)
    if len(command_text) < 2:
        bot.reply_to(message, "Type a message to send Everywhere bot exists")
        bot.register_next_step_handler(message, process_manual_next_step_broadcast)
        return
    
    # Pathway 3: Inline /broadcast <message>
    inline_text = command_text[1]
    trigger_broadcast_sending(message, text_payload=inline_text)

def process_manual_next_step_broadcast(message):
    register_user(message.from_user.id)
    if not is_admin(message.from_user.id):
        return
    trigger_broadcast_sending(message)

# --- START COMMAND ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    register_user(message.from_user.id)
    text_args = message.text.split()
    
    if len(text_args) > 1:
        unique_key = text_args[1]
        conn = sqlite3.connect('file_store.db')
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id, message_id FROM stored_messages WHERE unique_key = ?", (unique_key,))
        results = cursor.fetchall()
        conn.close()
        
        if results:
            for chat_id, msg_id in results:
                try:
                    bot.copy_message(chat_id=message.chat.id, from_chat_id=chat_id, message_id=msg_id)
                except Exception:
                    pass
            return
        else:
            bot.reply_to(message, "❌ Link expired or invalid.")
            return

    bot.reply_to(message, "Bot running made by @HarshInfo")

# --- GENLINK STEP TRIGGER ---
@bot.message_handler(commands=['genlink'])
def genlink_cmd(message):
    register_user(message.from_user.id)
    USER_STATES[message.from_user.id] = "waiting_for_media"  
    bot.reply_to(message, "🔄 **Send Media text or anything**", parse_mode="Markdown")

# --- ALBUM DELAY HANDLING ---
def process_delayed_album_save(chat_id, user_id, group_id, reply_to_msg_id):
    time.sleep(1.0)  
    
    messages_to_save = ALBUM_COLLECTOR.pop(group_id, [])
    if not messages_to_save:
        return
        
    unique_key = generate_unique_key(8)
    conn = sqlite3.connect('file_store.db')
    cursor = conn.cursor()
    
    for msg in messages_to_save:
        cursor.execute("INSERT INTO stored_messages (unique_key, chat_id, message_id, media_group_id) VALUES (?, ?, ?, ?)", 
                       (unique_key, msg.chat.id, msg.message_id, group_id))
        
    conn.commit()
    conn.close()
    
    bot_username = bot.get_me().username
    share_link = f"https://t.me/{bot_username}?start={unique_key}"
    
    bot.send_message(
        chat_id, 
        f"✅ **Stored {len(messages_to_save)} items successfully!**\n\n🔗 Your Multi-Media Link:\n`{share_link}`", 
        parse_mode="Markdown",
        reply_to_message_id=reply_to_msg_id
    )
    USER_STATES.pop(user_id, None)

# --- MASTER CATCH FILTER ---
@bot.message_handler(content_types=['photo', 'video', 'audio', 'document', 'text', 'sticker', 'voice', 'video_note'])
def catch_all_media(message):
    user_id = message.from_user.id
    register_user(user_id)
    
    if USER_STATES.get(user_id) != "waiting_for_media":
        return

    if message.media_group_id:
        group_id = message.media_group_id
        if group_id not in ALBUM_COLLECTOR:
            ALBUM_COLLECTOR[group_id] = [message]
            t = threading.Thread(target=process_delayed_album_save, args=(message.chat.id, user_id, group_id, message.message_id))
            t.start()
        else:
            ALBUM_COLLECTOR[group_id].append(message)
    else:
        unique_key = generate_unique_key(8)
        conn = sqlite3.connect('file_store.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO stored_messages (unique_key, chat_id, message_id) VALUES (?, ?, ?)", 
                       (unique_key, message.chat.id, message.message_id))
        conn.commit()
        conn.close()
        
        bot_username = bot.get_me().username
        share_link = f"https://t.me/{bot_username}?start={unique_key}"
        bot.reply_to(message, f"✅ **Stored successfully!**\n\n🔗 Your Shareable Link:\n`{share_link}`", parse_mode="Markdown")
        USER_STATES.pop(user_id, None)

if __name__ == '__main__':
    init_db()
    set_bot_menu_commands()
    print("🚀 Your Advanced Storage Bot is running smoothly...")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)
        
