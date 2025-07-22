from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import asyncio
import os
import re
import csv
from datetime import datetime
from collections import defaultdict
import telegram.error
import httpx
import traceback
import time

# --- Config ---
BOT_TOKEN = "8159393827:AAEefQOzsXg4feBoNa1EPrRWr4wqgbS7ZQM"

# --- State ---
user_state = {}
user_current_menu = {}
user_last_submenu_item = {}
user_last_seen_date = {}
user_active_task = {}
user_write_message_count = defaultdict(lambda: {"date": "", "count": 0})
user_busy_timestamp = {}

# --- Load Write Message count from CSV ---
def load_write_message_log():
    if not os.path.exists("write_message_log.csv"):
        return

    with open("write_message_log.csv", "r", encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if len(row) < 3:
                continue
            user_id, datetime_str, _ = row
            date_str = datetime_str.split()[0]
            if date_str == datetime.now().strftime("%Y-%m-%d"):
                user_id = int(user_id)
                user_write_message_count[user_id]["date"] = date_str
                user_write_message_count[user_id]["count"] += 1

# --- Load Menu Structure ---
def load_menu_structure(filepath):
    menu = {}
    current_category = None
    if not os.path.exists(filepath):
        print(f"[DEBUG] Menu file '{filepath}' not found.")
        return menu

    with open(filepath, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            if not line.startswith("-"):
                current_category = line
                menu[current_category] = []
            else:
                submenu_item = line.lstrip("-").strip()
                if current_category:
                    menu[current_category].append(submenu_item)
    return menu

# --- Build Keyboard ---
def build_keyboard(buttons, add_back=False):
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    if add_back:
        rows.append(["⬅ Back"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# --- Safe Reply Text ---
async def safe_reply_text(message, text):
    for attempt in range(3):
        try:
            await message.reply_text(text, parse_mode="Markdown")
            return
        except Exception as e:
            print(f"[DEBUG] Markdown failed (attempt {attempt+1}): {e}")
    try:
        await message.reply_text(text)
    except Exception as e:
        print(f"[ERROR] Plain text also failed: {e}")

# --- Show Main Menu ---
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    user_state[user_id] = "main_menu"
    user_current_menu[user_id] = None
    user_last_submenu_item[user_id] = None
    user_active_task[user_id] = None
    context.user_data["is_busy"] = False

    keyboard = build_keyboard(list(menu_structure.keys()))
    await update.message.reply_text("📋 *Main Menu* \nPlease select a category:", reply_markup=keyboard, parse_mode="Markdown")

# --- Send Announcement ---
async def send_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    path = "texts/Announcement.txt"
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as file:
            content = file.read().strip()
        if content:
            for page in content.split("===PAGEBREAK==="):
                await safe_reply_text(update.message, page.strip())
                await asyncio.sleep(2)

# --- Send from Text File ---
async def send_from_textfile(update: Update, context: ContextTypes.DEFAULT_TYPE, filename_base: str):
    user_id = update.effective_chat.id
    path = f"texts/{filename_base}.txt"
    if not os.path.exists(path):
        await safe_reply_text(update.message, f"⚠️ No text file found for '{filename_base}'")
        return

    with open(path, 'r', encoding='utf-8') as file:
        content = file.read().strip()
    if not content:
        await safe_reply_text(update.message, f"⚠️ No content in '{filename_base}'")
        return

    for page in content.split("===PAGEBREAK==="):
        if user_state.get(user_id) == "main_menu":
            return
        match = re.match(r"#image:(.+?)\r?\n(.*)", page.strip(), re.DOTALL)
        if match:
            image_name, caption = match.groups()
            image_path = f"images/{image_name.strip()}"
            if os.path.exists(image_path):
                try:
                    with open(image_path, "rb") as img:
                        await update.message.reply_photo(photo=img, caption=caption.strip(), parse_mode="Markdown")
                except Exception as e:
                    await safe_reply_text(update.message, f"❌ Image error: {e}")
                    await safe_reply_text(update.message, caption.strip())
            else:
                await safe_reply_text(update.message, f"⚠️ Image not found: {image_name}")
                await safe_reply_text(update.message, caption.strip())
        else:
            await safe_reply_text(update.message, page.strip())
        await asyncio.sleep(2)

# --- Submenu Action ---
async def handle_submenu_action(update: Update, context: ContextTypes.DEFAULT_TYPE, item):
    user_id = update.effective_chat.id
    try:
        context.user_data["is_busy"] = True
        user_busy_timestamp[user_id] = datetime.now().timestamp()
        await send_from_textfile(update, context, item)
    except Exception as e:
        print(f"[ERROR] First attempt failed for user {user_id}: {e}")
        traceback.print_exc()
        try:
            await send_from_textfile(update, context, item)
        except Exception as e:
            await update.message.reply_text("❌ Failed twice. Try again later.")
            print(f"[FATAL] Second attempt failed: {e}")
    finally:
        context.user_data["is_busy"] = False
        user_busy_timestamp.pop(user_id, None)

# --- Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("[ERROR] Exception during update:")
    traceback.print_exc()

# --- Message Handler ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    text = update.message.text.strip()
    now = datetime.now().timestamp()

    print(f"[DEBUG] User {user_id} sent: {text}")

    if text == "⬅ Back":
        print(f"[DEBUG] User {user_id} pressed Back — resetting to main menu")
        user_state[user_id] = "main_menu"
        user_current_menu[user_id] = None
        user_last_submenu_item[user_id] = None
        context.user_data["is_busy"] = False
        await show_main_menu(update, context)
        return

    if context.user_data.get("is_busy", False):
        if now - user_busy_timestamp.get(user_id, now) > 20:
            print(f"[TIMEOUT] Resetting is_busy for user {user_id}")
            context.user_data["is_busy"] = False
            user_busy_timestamp.pop(user_id, None)
            await update.message.reply_text("⚠️ Previous request timed out.")
        else:
            await update.message.reply_text("⏳ Please wait for your current request to finish.")
        return

    if user_id not in user_state:
        user_state[user_id] = "main_menu"

    today_str = datetime.now().strftime("%Y-%m-%d")
    if user_last_seen_date.get(user_id) != today_str:
        user_last_seen_date[user_id] = today_str
        await send_announcement(update, context)


    # --- Main Menu Handling ---
    if text in menu_structure:
        if user_current_menu.get(user_id) == text:
            print(f"[DEBUG] User {user_id} pressed same main menu: '{text}' — ignored")
            return
        print(f"[DEBUG] User {user_id} entered main menu: '{text}'")
        user_current_menu[user_id] = text
        user_state[user_id] = text
        user_last_submenu_item[user_id] = None
        submenu_buttons = menu_structure[text]
        keyboard = build_keyboard(submenu_buttons, add_back=True)
        await update.message.reply_text(f"📂 *{text}*\nSelect an option:", reply_markup=keyboard, parse_mode="Markdown")
        return

    # --- Submenu Handling ---
    current_menu = user_current_menu.get(user_id)
    if current_menu and text in menu_structure.get(current_menu, []):
        if user_last_submenu_item.get(user_id) == text:
            print(f"[DEBUG] User {user_id} re-triggered same submenu: '{text}' — ignored")
            return

        print(f"[DEBUG] User {user_id} selected submenu item: '{text}'")
        user_last_submenu_item[user_id] = text

        if text == "Write a Message":
            user_state[user_id] = "awaiting_message"
            await update.message.reply_text(
                "✉️ *Type your message below.*\nYou may submit up to *2 messages per day.*",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove()
            )
            return

        user_active_task[user_id] = context.application.create_task(
            handle_submenu_action(update, context, text)
        )
        return

    # --- Message Submission ---
    if user_state.get(user_id) == "awaiting_message":
        msg = text
        if msg.lower() == "back" or msg == "⬅ Back":
            await update.message.reply_text("↩️ Message cancelled.", reply_markup=build_keyboard(list(menu_structure.keys())))
            user_state[user_id] = "main_menu"
            user_current_menu[user_id] = None
            user_last_submenu_item[user_id] = None
            return

        if len(msg.split()) < 10:
            await update.message.reply_text("⚠️ Please enter at least *10 words*. Try again or type ⬅ Back.", parse_mode="Markdown")
            return

        count = user_write_message_count[user_id]
        if count["date"] != today_str:
            count["date"] = today_str
            count["count"] = 0

        if count["count"] >= 2:
            await update.message.reply_text("⚠️ You already submitted *2 messages today.* Try again tomorrow.", parse_mode="Markdown")
            await show_main_menu(update, context)
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("write_message_log.csv", "a", newline='', encoding='utf-8') as file:
            csv.writer(file).writerow([user_id, timestamp, msg])

        count["count"] += 1
        await update.message.reply_text("✅ *Your message was submitted anonymously.* Thank you!", parse_mode="Markdown")
        await show_main_menu(update, context)
        return

    await show_main_menu(update, context)

# --- Start Command ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    user_state[user_id] = "main_menu"
    await show_main_menu(update, context)

# --- Ensure Connection ---
async def ensure_connected(app: Application):
    while True:
        try:
            await app.bot.get_me()
            print("[INFO] Bot is connected.")
            break
        except Exception as e:
            print(f"[WARN] Bot not connected: {e}. Retrying in 5s...")
            await asyncio.sleep(5)

# --- Main Entry ---
def main():
    global menu_structure
    menu_structure = load_menu_structure("texts/Main Menu.txt")
    load_write_message_log()

    for attempt in range(5):
        try:
            app = Application.builder().token(BOT_TOKEN).post_init(ensure_connected).build()
            app.add_handler(CommandHandler("start", start))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
            app.add_error_handler(error_handler)
            print("Bot is running...")
            app.run_polling(stop_signals=None)
            break
        except Exception as e:
            print(f"[RETRY] Failed to start bot (attempt {attempt+1}/5): {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
