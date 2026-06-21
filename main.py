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
CUSTOM_BATCH_COLLECTOR = {} # Tracks multi-select items for custom batches

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
        types.BotCommand("batch", "📦 Bulk store a channel range (First & Last post)"),
        types.BotCommand("custom_batch", "🗂️ Select and forward multiple files at once"),
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
    
    if message.reply_to_message:
        trigger_broadcast_sending(message, target_msg=message.reply_to_message)
        return

    command_text = message.text.split(maxsplit=1)
    if len(command_text) < 2:
        bot.reply_to(message, "Type a message to send Everywhere bot exists")
        bot.register_next_step_handler(message, process_manual_next_step_broadcast)
        return
    
    inline_text = command_text[1]
    trigger_broadcast_sending(message, text_payload=inline_text)

def process_manual_next_step_broadcast(message):
    register_user(message.from_user.id)
    if not is_admin(message.from_user.id):
        return
    trigger_broadcast_sending(message)

# --- METHOD 1: BATCH CHANNEL RANGE ENGINE ---
@bot.message_handler(commands=['batch'])
def batch_cmd(message):
    register_user(message.from_user.id)
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Only @HarshInfo Can use this command")
        return
    
    bot.reply_to(message, "📦 **Forward the FIRST message from your target channel:**", parse_mode="Markdown")
    bot.register_next_step_handler(message, process_batch_first_msg)

def process_batch_first_msg(message):
    if not is_admin(message.from_user.id):
        return
    if not message.forward_from_chat:
        bot.reply_to(message, "❌ Please **forward** a real file/post from a channel.")
        return
        
    chat_id = message.forward_from_chat.id
    first_msg_id = message.forward_from_message_id
    
    bot.reply_to(message, "📦 **Now forward the LAST message from that same channel:**", parse_mode="Markdown")
    bot.register_next_step_handler(message, process_batch_last_msg, chat_id, first_msg_id)

def process_batch_last_msg(message, chat_id, first_msg_id):
    if not is_admin(message.from_user.id):
        return
    if not message.forward_from_chat or message.forward_from_chat.id != chat_id:
        bot.reply_to(message, "❌ Error: The last message must belong to the **same channel**.")
        return
        
    last_msg_id = message.forward_from_message_id
    start_id = min(first_msg_id, last_msg_id)
    end_id = max(first_msg_id, last_msg_id)
    
    unique_key = generate_unique_key(8)
    conn = sqlite3.connect('file_store.db')
    cursor = conn.cursor()
    
    for msg_id in range(start_id, end_id + 1):
        cursor.execute("INSERT INTO stored_messages (unique_key, chat_id, message_id) VALUES (?, ?, ?)", 
                       (unique_key, chat_id, msg_id))
                       
    conn.commit()
    conn.close()
    
    bot_username = bot.get_me().username
    share_link = f"https://t.me/{bot_username}?start={unique_key}"
    total_count = (end_id - start_id) + 1
    
    bot.reply_to(message, f"✅ **Successfully batched {total_count} items!**\n\n🔗 Your Bulk Share Link:\n`{share_link}`", parse_mode="Markdown")

# --- METHOD 2: CUSTOM BATCH MULTI-FORWARD COLLECTOR ---
@bot.message_handler(commands=['custom_batch'])
def custom_batch_cmd(message):
    register_user(message.from_user.id)
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Only @HarshInfo Can use this command")
        return
        
    USER_STATES[message.from_user.id] = "waiting_for_custom_batch"
    CUSTOM_BATCH_COLLECTOR[message.from_user.id] = []
    
    bot.reply_to(message, "🗂️ **Custom Batch Mode Activated!**\n\nHighlight and forward all files you want to save. Send **`/done`** when you are completely finished forwarding.", parse_mode="Markdown")

@bot.message_handler(commands=['done'])
def custom_batch_done(message):
    user_id = message.from_user.id
    if USER_STATES.get(user_id) != "waiting_for_custom_batch":
        return
        
    saved_list = CUSTOM_BATCH_COLLECTOR.get(user_id, [])
    if not saved_list:
        bot.reply_to(message, "❌ You didn't forward any items. Session cancelled.")
        USER_STATES.pop(user_id, None)
        CUSTOM_BATCH_COLLECTOR.pop(user_id, None)
        return
        
    unique_key = generate_unique_key(8)
    conn = sqlite3.connect('file_store.db')
    cursor = conn.cursor()
    
    for chat_id, msg_id in saved_list:
        cursor.execute("INSERT INTO stored_messages (unique_key, chat_id, message_id) VALUES (?, ?, ?)", 
                       (unique_key, chat_id, msg_id))
                       
    conn.commit()
    conn.close()
    
    bot_username = bot.get_me().username
    share_link = f"https://t.me/{bot_username}?start={unique_key}"
    
    bot.reply_to(message, f"✅ **Successfully packaged {len(saved_list)} selected files!**\n\n🔗 Your Custom Share Link:\n`{share_link}`", parse_mode="Markdown")
    
    # Clear session states
    USER_STATES.pop(user_id, None)
    CUSTOM_BATCH_COLLECTOR.pop(user_id, None)

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

# --- GLOBAL SINGLE MESSAGE SAVE UTILITY ---
def save_single_message_to_db(message_obj, custom_text=None):
    unique_key = generate_unique_key(8)
    conn = sqlite3.connect('file_store.db')
    cursor = conn.cursor()
    
    if custom_text:
        temp_msg = bot.send_message(chat_id=message_obj.chat.id, text=custom_text)
        cursor.execute("INSERT INTO stored_messages (unique_key, chat_id, message_id) VALUES (?, ?, ?)", 
                       (unique_key, temp_msg.chat.id, temp_msg.message_id))
    else:
        cursor.execute("INSERT INTO stored_messages (unique_key, chat_id, message_id) VALUES (?, ?, ?)", 
                       (unique_key, message_obj.chat.id, message_obj.message_id))
        
    conn.commit()
    conn.close()
    
    bot_username = bot.get_me().username
    share_link = f"https://t.me/{bot_username}?start={unique_key}"
    bot.reply_to(message_obj, f"✅ **Stored successfully!**\n\n🔗 Your Shareable Link:\n`{share_link}`", parse_mode="Markdown")

# --- GENLINK CONTROLLER ---
@bot.message_handler(commands=['genlink'])
def genlink_cmd(message):
    register_user(message.from_user.id)
    
    if message.reply_to_message:
        save_single_message_to_db(message.reply_to_message)
        return

    command_text = message.text.split(maxsplit=1)
    if len(command_text) < 2:
        USER_STATES[message.from_user.id] = "waiting_for_media"  
        bot.reply_to(message, "🔄 **Send Media text or anything**", parse_mode="Markdown")
        return
    
    inline_text_payload = command_text[1]
    save_single_message_to_db(message, custom_text=inline_text_payload)

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
    
    # Intercept if user is running a multi-selection forward batch
    if USER_STATES.get(user_id) == "waiting_for_custom_batch":
        # Log the message tracking info silently to the session cache
        if message.forward_from_chat:
            CUSTOM_BATCH_COLLECTOR[user_id].append((message.forward_from_chat.id, message.forward_from_message_id))
        else:
            CUSTOM_BATCH_COLLECTOR[user_id].append((message.chat.id, message.message_id))
        return

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
        save_single_message_to_db(message)
        USER_STATES.pop(user_id, None)

if __name__ == '__main__':
    init_db()
    set_bot_menu_commands()
    print("🚀 Your Advanced Storage Bot is running smoothly...")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)
    
