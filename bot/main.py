import sqlite3
import asyncio
import os
from telegram import ReplyKeyboardRemove, Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from datetime import datetime

from db import init_db, save_timezone_for_chat, get_timezone_for_chat

import pytz
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

TIMEZONE_CHOICE = 1
TIMEZONES = TIMEZONES = ["UTC", "Europe/London", "Europe/Rome", "America/New_York", "America/Los_Angeles", "Asia/Shanghai", "Asia/Tokyo"]

# Constants for conversation states
AWAITING_SCHEDULE_MESSAGE, AWAITING_CRON_MESSAGE = range(2)

def get_env_data_as_dict(path: str) -> dict:
    try:
        with open(path, 'r') as f:
            return dict(tuple(line.replace('\n', '').split('='))
                for line in f.readlines() if not line.startswith('#'))
    except OSError as e:
        return {}

envData = get_env_data_as_dict('.env')

# Set timezone
# local_tz = pytz.timezone(os.getenv('TZ', 'UTC'))

# SQLite setup
BOT_TOKEN = os.getenv('BOT_TOKEN', envData.get('BOT_TOKEN'))
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required")

DB_NAME = 'data/crondule.db'

# Scheduler setup
scheduler = BackgroundScheduler(timezone=pytz.utc)
scheduler.start()

# Store temporary user context (schedule -> message)
user_context = {}

def save_job_to_db(job_id, chat_id, job_type, trigger, message, next_run_time):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO jobs (job_id, chat_id, type, trigger, message, next_run_time)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (job_id, chat_id, job_type, trigger, message, next_run_time))

def delete_job_from_db(job_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))

def load_jobs_from_db():
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute("SELECT job_id, chat_id, type, trigger, message FROM jobs").fetchall()
        for job_id, chat_id, job_type, trigger, message in rows:
            if job_type == "schedule":
                run_time = datetime.fromisoformat(trigger)
                scheduler.add_job(
                    send_message,
                    trigger=DateTrigger(run_date=run_time),
                    kwargs={"chat_id": chat_id, "message": message, "type": job_type, "job_id": job_id},
                    name=job_type,
                    id=job_id
                )
                logging.info(f"Loaded scheduled job {job_id} for chat {chat_id} at {run_time}")
            elif job_type == "cron":
                cron = CronTrigger.from_crontab(trigger)
                scheduler.add_job(
                    send_message,
                    trigger=cron,
                    kwargs={"chat_id": chat_id, "message": message},
                    name=job_type,
                    id=job_id
                )
                logging.info(f"Loaded cron job {job_id} for chat {chat_id} with trigger {trigger}")

# Schedule message sender
def send_message(chat_id, message, type=None, job_id=None):
    from telegram import Bot  # Lazy import
    bot = Bot(BOT_TOKEN)
    try:
        asyncio.run(bot.send_message(chat_id=chat_id, text=message))
    except Exception as e:
        logging.error(f"Failed to send message to {chat_id}: {e}")
    else:
        # If it's a one-time scheduled job, delete it from DB
        if type == "schedule" and job_id:
            delete_job_from_db(job_id)

async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[tz] for tz in TIMEZONES]
    markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    message = (
        "🌍 Please choose your timezone below.\n\n"
        "If you're not sure what to do, check this list: "
        "[List of timezones](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)"
    )
    await update.message.reply_text(message, reply_markup=markup, parse_mode="Markdown")
    return TIMEZONE_CHOICE

async def handle_timezone_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chosen = update.message.text.strip()

    if chosen not in pytz.all_timezones:
        await update.message.reply_text("Invalid timezone. Please try again.")
        return TIMEZONE_CHOICE

    save_timezone_for_chat(chat_id, chosen)
    markup = ReplyKeyboardRemove()
    await update.message.reply_text(f"✅ Timezone set to {chosen}.", reply_markup=markup)
    return ConversationHandler.END

# My commands
async def set_my_commands(application):
    await application.bot.setMyCommands([
        ("start", "Start the bot"),
        ("settimezone", "Set your timezone"),
        ("schedule", "Schedule a message"),
        ("cron", "Schedule a message with cron syntax"),
        ("list", "List scheduled messages"),
        ("delete", "Delete a scheduled message"),
        ("cancel", "Cancel the current operation")
    ])

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Use /settimezone to select your timezone.")

# /list command
async def list_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    chat_tz = get_timezone_for_chat(update.message.chat_id)
    with sqlite3.connect(DB_NAME) as conn:
        rows = conn.execute("""
            SELECT job_id, type, trigger, message, next_run_time
            FROM jobs
            WHERE chat_id = ?
        """, (chat_id,)).fetchall()

    if not rows:
        await update.message.reply_text("No jobs scheduled.")
        return

    lines = []
    for job_id, job_type, trigger, message, next_run_time in rows:
        local_time = datetime.fromisoformat(next_run_time).astimezone(chat_tz).strftime("%Y-%m-%d %H:%M %Z")
        lines.append(
            f"🆔 {job_id}\n📅 {local_time}\n🔁 {job_type}\n📝 {message[:40]}..."
        )

    await update.message.reply_text("\n\n".join(lines))


# /delete <job_id> command
async def delete_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /delete <job_id>")
        return

    job_id = context.args[0]
    job = scheduler.get_job(job_id)
    if job:
        scheduler.remove_job(job_id)
        delete_job_from_db(job_id)
        await update.message.reply_text(f"Deleted job {job_id}")
    else:
        delete_job_from_db(job_id)
        await update.message.reply_text("Job not found.")


# /schedule command
async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send the date and time in the format: YYYY-MM-DD HH:MM")
    return AWAITING_SCHEDULE_MESSAGE

# /cron command
async def cron(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send the crontab syntax (e.g., '0 9 * * *' for 9AM every day)")
    return AWAITING_CRON_MESSAGE

# After date/time, expect the message to send
async def receive_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_tz = get_timezone_for_chat(update.message.chat_id)
    try:
        user_input = update.message.text.strip()
        local_dt = datetime.strptime(user_input, "%Y-%m-%d %H:%M")
        local_dt = chat_tz.localize(local_dt)
        utc_dt = local_dt.astimezone(pytz.utc)

        now_utc = datetime.now(pytz.utc)
        delta = (utc_dt - now_utc).total_seconds()

        if delta <= 0:
            await update.message.reply_text("The time must be in the future.")
            return ConversationHandler.END

        # Save in context for later message capture
        user_context[update.message.chat_id] = ("schedule", utc_dt.isoformat())

        await update.message.reply_text(
            f"Message will be sent in {int(delta // 60)} minutes at {local_dt.strftime('%Y-%m-%d %H:%M %Z')}.\nNow send the message."
        )
    except Exception as e:
        await update.message.reply_text(f"Invalid format or error: {e}")
        return ConversationHandler.END

    return ConversationHandler.END

# After cron syntax, expect the message to send
async def receive_cron(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cron_syntax = update.message.text.strip()
    try:
        parts = cron_syntax.split()
        if len(parts) != 5:
            raise ValueError("Invalid cron syntax")

        user_context[update.message.chat_id] = ("cron", cron_syntax)
        await update.message.reply_text("Now send the message you want to send on that cron schedule.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return ConversationHandler.END
    return ConversationHandler.END

# Final handler to capture the message to send
async def capture_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id not in user_context:
        return

    mode, schedule_str = user_context.pop(chat_id)
    message = update.message.text

    sanitized_chat_id = f"m{abs(chat_id)}" if str(chat_id).startswith('-') else str(chat_id)
    job_time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_id = f"job_{sanitized_chat_id}{job_time_str}"
    # job_id = f"{chat_id}_{int(datetime.now().timestamp())}"
    if mode == "schedule":
        run_time = datetime.fromisoformat(schedule_str)
        scheduler.add_job(
            send_message,
            trigger=DateTrigger(run_date=run_time),
            kwargs={"chat_id": chat_id, "message": message, "type": mode, "job_id": job_id},
            name="schedule",
            id=job_id
        )
        save_job_to_db(job_id, chat_id, mode, run_time.isoformat(), message, run_time.isoformat())
    else:  # cron
        chat_tz = get_timezone_for_chat(chat_id)
        minute, hour, dom, month, dow = schedule_str.split()
        trigger = CronTrigger(minute=minute, hour=hour, day=dom, month=month, day_of_week=dow, timezone=chat_tz)
        scheduler.add_job(
            send_message,
            trigger=trigger,
            kwargs={"chat_id": chat_id, "message": message},
            name="cron",
            id=job_id
        )
        next_run = trigger.get_next_fire_time(None, datetime.now(pytz.utc))

        save_job_to_db(
            job_id,
            chat_id,
            mode,
            f"{minute} {hour} {dom} {month} {dow}",
            message,
            next_run.isoformat()
        )

    await update.message.reply_text("Message scheduled!")

# Fallback
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# Bot setup
def main():
    init_db()

    load_jobs_from_db()
    
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(set_my_commands).build()

    app.add_handler(CommandHandler("start", start))

    timezone_convo = ConversationHandler(
        entry_points=[CommandHandler("settimezone", set_timezone)],
        states={
            TIMEZONE_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_timezone_choice)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(timezone_convo)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("schedule", schedule),
                      CommandHandler("cron", cron)],
        states={
            AWAITING_SCHEDULE_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_schedule)],
            AWAITING_CRON_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cron)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    app.add_handler(conv_handler)

    app.add_handler(CommandHandler("list", list_jobs))
    app.add_handler(CommandHandler("delete", delete_job))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, capture_message))

    app.run_polling()

if __name__ == "__main__":
    main()

