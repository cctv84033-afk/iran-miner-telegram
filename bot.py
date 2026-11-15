import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not WEBAPP_URL.startswith("https://"):
        await update.message.reply_text("آدرس HTTPS مینی‌اپ را در WEBAPP_URL تنظیم کنید.")
        return
    keyboard = [[InlineKeyboardButton("ورود به Iran Miner", web_app=WebAppInfo(url=WEBAPP_URL))]]
    await update.message.reply_text(
        "به Iran Miner خوش آمدید.\nاین نسخه نمایشی است؛ موجودی‌ها اعتبار آزمایشی‌اند و برداشت واقعی انجام نمی‌شود.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN را در متغیر محیطی تنظیم کنید.")
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.run_polling()

if __name__ == "__main__":
    main()
