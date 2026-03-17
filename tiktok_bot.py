"""
TikTok Downloader Telegram Bot

Instructions to install dependencies:
1. Ensure you have Python 3.8+ installed.
2. It's recommended to create a virtual environment:
   python -m venv venv
   # On Windows: venv\\Scripts\\activate
   # On macOS/Linux: source venv/bin/activate
3. Install the required packages via pip:
   pip install python-telegram-bot yt-dlp

Instructions to run the bot:
1. Talk to @BotFather on Telegram to create a new bot and get the BOT TOKEN.
2. Replace the 'YOUR_BOT_TOKEN_HERE' placeholder below with your actual token.
3. Run the script from your terminal:
   python tiktok_bot.py
"""

import os
import re
import logging
import asyncio
import tempfile
import httpx
from telegram import Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

# -----------------------------------------------------------------------------
# Configuration & Setup
# -----------------------------------------------------------------------------

# Replace this with your actual Telegram Bot Token from @BotFather
BOT_TOKEN = "8728062030:AAEKjYTbIPU6RdG4dVw58mDHZ6seSlRaXlY"

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
# Adjust httpx logging to Warning to prevent spam
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Maximum file size for Telegram bots is 50MB
MAX_FILE_SIZE = 50 * 1024 * 1024

# Regex pattern to validate TikTok links (handles short and long URLs)
TIKTOK_REGEX = re.compile(
    r'(https?://)?(www\.)?(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)/[A-Za-z0-9_/@\.\-]+'
)

# -----------------------------------------------------------------------------
# Handlers
# -----------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /start command.
    Sends a friendly welcome message to the user.
    """
    welcome_text = (
        "👋 Welcome to the TikTok Downloader Bot!\n\n"
        "Send me any TikTok video link, and I will download it for you.\n"
        "Type /help for more instructions."
    )
    await update.message.reply_text(welcome_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /help command.
    Explains how to use the bot.
    """
    help_text = (
        "🤖 *How to use this bot:*\n"
        "1. Open TikTok and find a video you like.\n"
        "2. Click the 'Share' button and choose 'Copy Link'.\n"
        "3. Paste the link here and send it to me.\n"
        "4. Wait a few moments while I process and download the video.\n\n"
        "Note: I can only download public videos that are under 50MB."
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /about command.
    Shows the developer's name and bot purpose.
    """
    about_text = (
        "ℹ️ *About this Bot*\n\n"
        "This bot was created to easily download TikTok videos without watermarks directly through Telegram.\n\n"
        "👨‍💻 *Developer:* @Vann\\_Sakkk"
    )
    # Using MarkdownV2 is recommended but it requires escaping certain characters like underscores
    await update.message.reply_text(about_text, parse_mode='Markdown')

def yt_dlp_download(url: str, output_path: str) -> dict:
    """
    Synchronous function to download the video using yt-dlp.
    We run this in a separate thread so it doesn't block the async event loop.
    """
    # yt-dlp options specifically tailored for TikTok (prioritizes no-watermark)
    ydl_opts = {
        'outtmpl': output_path,
        'format': 'bestvideo+bestaudio/best',
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # Extract info and download the video
        info = ydl.extract_info(url, download=True)
        return info

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Main message handler that processes incoming messages.
    It validates the URL, downloads the video, and sends it back.
    """
    # Simply ignore if the message has no text
    if not update.message or not update.message.text:
        return

    message_text = update.message.text
    
    # 1. Validate if the message contains a valid TikTok link
    match = TIKTOK_REGEX.search(message_text)
    if not match:
        await update.message.reply_text(
            "❌ That doesn't look like a valid TikTok link. Please send a valid TikTok URL.",
            reply_to_message_id=update.message.message_id
        )
        return

    tiktok_url = match.group(0)
    
    # 2. Let the user know we are processing
    status_msg = await update.message.reply_text(
        "⏳ Processing your link... Please wait.",
        reply_to_message_id=update.message.message_id
    )

    # 3. Check if it's a photo slideshow using TikWM API
    try:
        async with httpx.AsyncClient() as client:
            api_resp = await client.post("https://www.tikwm.com/api/", data={"url": tiktok_url, "hd": 1}, timeout=15.0)
            api_data = api_resp.json()
            if api_data.get('code') == 0 and 'images' in api_data.get('data', {}):
                images = api_data['data']['images']
                await status_msg.edit_text(f"📸 Detected a slideshow with {len(images)} pictures. Downloading images...")
                
                # Create a temporary directory to store images locally before sending
                temp_dir = tempfile.mkdtemp()
                downloaded_paths = []
                try:
                    for idx, img_url in enumerate(images):
                        if idx >= 30: # Limit to 30 images
                            break
                        r = await client.get(img_url, timeout=10.0)
                        if r.status_code == 200:
                            path = os.path.join(temp_dir, f"img_{idx}.jpg")
                            with open(path, 'wb') as f:
                                f.write(r.content)
                            downloaded_paths.append(path)
                    
                    # Split into chunks of 10 for Telegram's MediaGroup limit
                    await status_msg.edit_text("📤 Uploading pictures to Telegram...")
                    for i in range(0, len(downloaded_paths), 10):
                        chunk = downloaded_paths[i:i+10]
                        
                        # Open all files in this chunk
                        opened_files = [open(p, 'rb') for p in chunk]
                        media_group = [InputMediaPhoto(media=f) for f in opened_files]
                        
                        try:
                            await update.message.reply_media_group(
                                media=media_group,
                                reply_to_message_id=update.message.message_id if i == 0 else None
                            )
                        finally:
                            # Safely close files after sending
                            for f in opened_files:
                                f.close()
                                
                    await status_msg.delete()
                    logger.info(f"Successfully sent {len(downloaded_paths)} images for {tiktok_url}")
                    return
                finally:
                    # Cleanup images directory
                    for p in downloaded_paths:
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except: pass
                    if os.path.exists(temp_dir):
                        try:
                            os.rmdir(temp_dir)
                        except: pass
    except Exception as e:
        logger.warning(f"TikWM fetch failed, falling back to yt-dlp: {e}")

    # Fallback to standard yt-dlp video downloading flow
    await status_msg.edit_text("⏳ Downloading video... Please wait.")

    # 4. Create a temporary directory to store the video securely
    temp_dir = tempfile.mkdtemp()
    output_temp_path = os.path.join(temp_dir, 'video.mp4')

    try:
        # Run the blocking yt-dlp download in a separate thread
        logger.info(f"User {update.effective_user.id if update.effective_user else 'unknown'} requested download for: {tiktok_url}")
        
        await asyncio.to_thread(yt_dlp_download, tiktok_url, output_temp_path)
        
        # Check if file was successfully created
        if not os.path.exists(output_temp_path):
            raise Exception("File was not downloaded. The video might be private or deleted.")
            
        # 4. Check the file size to ensure it respects Telegram limits
        file_size = os.path.getsize(output_temp_path)
        if file_size > MAX_FILE_SIZE:
            await status_msg.edit_text("❌ The video is too large to send over Telegram (exceeds 50MB limit).")
            return
            
        # Update status message before uploading
        await status_msg.edit_text("📤 Uploading video to Telegram...")
        
        # 6. Send the video file back to the user
        with open(output_temp_path, 'rb') as video_file:
            await update.message.reply_video(
                video=video_file,
                caption="Here is your video! 🎥",
                reply_to_message_id=update.message.message_id
            )
            
        # Delete the status message once successfully sent
        await status_msg.delete()
        logger.info(f"Successfully sent video for {tiktok_url}")

    except Exception as e:
        logger.error(f"Error downloading {tiktok_url}: {e}")
        error_msg = f"❌ An error occurred while processing your request:\n{str(e)}"
        
        # Depending on the error text, we can provide a friendly message
        if "Private video" in str(e) or "bot" in str(e).lower():
            error_msg = "❌ Cannot download this video. It might be private or unavailable."
            
        await status_msg.edit_text(error_msg)

    finally:
        # 6. Clean up: Delete the temporary file and directory
        if os.path.exists(output_temp_path):
            try:
                os.remove(output_temp_path)
            except Exception as e:
                logger.error(f"Failed to delete temp video file: {e}")
                
        if os.path.exists(temp_dir):
            try:
                os.rmdir(temp_dir)
            except Exception as e:
                logger.error(f"Failed to delete temp directory: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    # Give user a generic fallback message
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ An unexpected error occurred. Please try again later."
            )
        except Exception:
            pass

# -----------------------------------------------------------------------------
# Main Application Execution
# -----------------------------------------------------------------------------

def main() -> None:
    """Start the bot application."""
    # Ensure a token has been set before starting
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or not BOT_TOKEN:
        logger.error("Please replace YOUR_BOT_TOKEN_HERE with your Bot Token!")
        return

    # Create the Telegram Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", about_command))

    # Register the main message handler to process text (for URLs)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Register error handler
    application.add_error_handler(error_handler)

    logger.info("Bot is starting up...")
    
    # Run the application (starts polling for updates)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
