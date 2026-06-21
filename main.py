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
USER_STATES = {}  # Tracks if a user is allowed to generate a link right now

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
        CREATE TABLE IF NOT EXISTS banned_users (user_id INTEGER PRIMARY KEY)
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

def is_banned(user_id):
    conn = sqlite3.connect('file_store.db')
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,))
    banned = cursor.fetchone()
    conn.close()
    return banned is not None

def set_bot_menu_commands():
    commands = [
        types.BotCommand("start", "🚀 Start the bot or fetch stored items"),
        types.BotCommand("genlink", "🔗 Generate a share link for files/media"),
        types.BotCommand("broadcast", "📢 Broadcast message to users (Admin Only)"),
        types.BotCommand("ban", "🔨 Ban a user (Admin Only)"),
        types.BotCommand("unban", "😇 Unban a user (Admin Only)")
    ]
    bot.set_my_commands(commands)

@bot.message_handler(func=lambda message: is_banned(message.from_user.id))
def handle_banned(message):
    bot.reply_to(message, "❌ You are banned from using this bot.")

# --- START COMMAND (RETRIEVAL & CREDIT) ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    register_user(message.from_user.id)
    text_args = message.text.split()
    
    # If downloading/fetching content via a link
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

    # Standard /start message with your signature credit
    bot.reply_to(message, "Bot running made by @HarshInfo")

# --- GENLINK STEP TRIGGER ---
@bot.message_handler(commands=['genlink'])
def genlink_cmd(message):
    register_user(message.from_user.id)
    USER_STATES[message.from_user.id] = "waiting_for_media"  # Turn on listener state for this user
    bot.reply_to(message, "🔄 **Send Media text or anything**", parse_mode="Markdown")

# --- ALBUM DELAY HANDLING ---
def process_delayed_album_save(chat_id, user_id, group_id, reply_to_msg_id):
    time.sleep(1.5)  # Wait for full dynamic delivery album buffer
    
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
    
    # Turn off listener state now that link is handed out
    USER_STATES.pop(user_id, None)

# --- MASTER CATCH FILTER (ONLY RESPONDS IF STATE IS ACTIVE) ---
@bot.message_handler(content_types=['photo', 'video', 'audio', 'document', 'text', 'sticker', 'voice', 'video_note'])
def catch_all_media(message):
    user_id = message.from_user.id
    register_user(user_id)
    
    # Strictly ignore any regular chatter unless they hit /genlink first!
    if USER_STATES.get(user_id) != "waiting_for_media":
        return

    # If it is part of a combined album media pack
    if message.media_group_id:
        group_id = message.media_group_id
        
        if group_id not in ALBUM_COLLECTOR:
            ALBUM_COLLECTOR[group_id] = [message]
            t = threading.Thread(target=process_delayed_album_save, args=(message.chat.id, user_id, group_id, message.message_id))
            t.start()
        else:
            ALBUM_COLLECTOR[group_id].append(message)
            
    # If it's a single item (text, file, photo, etc.)
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
        
        # Turn off listener state immediately
        USER_STATES.pop(user_id, None)

# --- ADMIN POWER COMMANDS ---
@bot.message_handler(commands=['broadcast'])
def broadcast_cmd(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "🚫 This command is restricted to Admins.")
        return
    
    command_text = message.text.split(maxsplit=1)
    if len(command_text) < 2:
        bot.reply_to(message, "⚠️ Usage: `/broadcast Your message text here`")
        return
    
    broadcast_msg = command_text[1]
    conn = sqlite3.connect('file_store.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM bot_users")
    users = cursor.fetchall()
    conn.close()
    
    success_count = 0
    for user in users:
        try:
            bot.send_message(user[0], broadcast_msg)
            success_count += 1
        except Exception:
            pass
            
    bot.reply_to(message, f"📢 Broadcast complete. Sent successfully to {success_count} active users.")

@bot.message_handler(commands=['ban'])
def ban_cmd(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "🚫 Restricted to Admins.")
        return
    try:
        user_id_to_ban = int(message.text.split()[1])
        conn = sqlite3.connect('file_store.db')
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id_to_ban,))
        conn.commit()
        conn.close()
        bot.reply_to(message, f"🔨 User `{user_id_to_ban}` has been banned.", parse_mode="Markdown")
    except (IndexError, ValueError):
        bot.reply_to(message, "⚠️ Usage: `/ban USER_ID`")

@bot.message_handler(commands=['unban'])
def unban_cmd(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "🚫 Restricted to Admins.")
        return
    try:
        user_id_to_unban = int(message.text.split()[1])
        conn = sqlite3.connect('file_store.db')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id_to_unban,))
        conn.commit()
        conn.close()
        bot.reply_to(message, f"😇 User `{user_id_to_unban}` unbanned.", parse_mode="Markdown")
    except (IndexError, ValueError):
        bot.reply_to(message, "⚠️ Usage: `/unban USER_ID`")

if __name__ == '__main__':
    init_db()
    set_bot_menu_commands()
    print("🚀 Your Advanced Storage Bot is running smoothly...")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)
          
