import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

# Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *YouTube Shorts Bot*\n\n"
        "Send me a YouTube link!\n"
        "I'll give you 3 timestamp suggestions for shorts.\n\n"
        "⚡ Fast & Free!",
        parse_mode='Markdown'
    )

# Process YouTube link
async def process_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    
    if 'youtube.com' not in url and 'youtu.be' not in url:
        await update.message.reply_text("❌ Send a valid YouTube link!")
        return
    
    msg = await update.message.reply_text("⏳ Processing...")
    
    try:
        # Get video info (without downloading)
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Video')
            duration = info.get('duration', 0)
        
        if duration < 60:
            await msg.edit_text("❌ Video too short! Need at least 1 minute.")
            return
        
        # Calculate 3 best timestamps
        safe_start = int(duration * 0.1)
        safe_end = int(duration * 0.9)
        usable = safe_end - safe_start
        
        gap = usable / 4
        
        timestamps = [
            int(safe_start + gap * 1),
            int(safe_start + gap * 2),
            int(safe_start + gap * 3)
        ]
        
        # Send results
        result = f"✅ *Video Found!*\n\n📹 {title[:50]}...\n\n"
        result += "🎬 *3 Best Moments for Shorts:*\n\n"
        
        for i, ts in enumerate(timestamps, 1):
            mins = ts // 60
            secs = ts % 60
            timestamp = f"{mins}:{secs:02d}"
            
            # Create timestamped URL
            ts_url = f"{url}&t={ts}s"
            
            result += f"*Short {i}:*\n"
            result += f"⏱️ Start at: {timestamp}\n"
            result += f"🔗 [Direct Link]({ts_url})\n"
            result += f"📏 Cut: 40-50 seconds\n\n"
        
        result += "💡 *How to use:*\n"
        result += "1. Click timestamp link\n"
        result += "2. Download from that point\n"
        result += "3. Cut 40-50 seconds\n"
        result += "4. Upload as short!\n\n"
        result += "🔄 Send another link!"
        
        await msg.edit_text(result, parse_mode='Markdown', disable_web_page_preview=True)
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit_text(f"❌ Error processing video.\nTry another link!")

# Main
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found!")
        return
    
    logger.info("🤖 Bot starting...")
    
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_link))
    
    logger.info("✅ Bot running!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
