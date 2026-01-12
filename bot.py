import os
import asyncio
import subprocess
import random
import time
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
import whisper
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip
import requests

# ============== CONFIGURATION ==============
BOT_TOKEN = os.environ.get("BOT_TOKEN")
TEMP_DIR = Path("temp")
OUTPUT_DIR = Path("output")

# Create directories
TEMP_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============== PROXY ROTATION ==============
class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.current_index = 0
        self.load_proxies()
    
    def load_proxies(self):
        """Load free proxies from API"""
        try:
            response = requests.get(
                "https://api.proxyscrape.com/v2/?request=get&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
            )
            proxies = response.text.strip().split('\n')
            self.proxies = [f"http://{p}" for p in proxies[:10]]
            logger.info(f"Loaded {len(self.proxies)} proxies")
        except:
            logger.warning("Could not load proxies, continuing without proxy")
            self.proxies = []
    
    def get_next(self):
        if not self.proxies:
            return None
        proxy = self.proxies[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.proxies)
        return proxy

proxy_manager = ProxyManager()

# ============== VIDEO DOWNLOADER ==============
async def download_video(url: str, output_path: str):
    """Download YouTube video with proxy rotation"""
    
    ydl_opts = {
        'format': 'best[height<=1080]',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    # Try with proxy
    proxy = proxy_manager.get_next()
    if proxy:
        ydl_opts['proxy'] = proxy
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Video')
            duration = info.get('duration', 0)
            return output_path, title, duration
    except Exception as e:
        logger.error(f"Download error: {e}")
        # Retry without proxy
        if proxy:
            ydl_opts.pop('proxy', None)
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    title = info.get('title', 'Video')
                    duration = info.get('duration', 0)
                    return output_path, title, duration
            except:
                pass
        return None, None, None

# ============== SCENE ANALYZER ==============
def analyze_scenes(video_path: str, duration: int, num_clips: int = 3):
    """Find best moments in video"""
    
    if duration < 60:
        # Video too short, use full video
        return [(0, min(duration, 50))]
    
    # Avoid first and last 10%
    safe_start = duration * 0.1
    safe_end = duration * 0.9
    usable_duration = safe_end - safe_start
    
    # Calculate segments
    segment_length = 45  # 45 seconds per short
    segments = []
    
    if usable_duration < segment_length * num_clips:
        # Not enough content, space out evenly
        gap = usable_duration / (num_clips + 1)
        for i in range(num_clips):
            start = safe_start + gap * (i + 1)
            end = min(start + segment_length, safe_end)
            segments.append((start, end))
    else:
        # Plenty of content, select strategically
        gap = usable_duration / (num_clips + 1)
        for i in range(num_clips):
            start = safe_start + gap * (i + 1) - (segment_length / 2)
            start = max(safe_start, start)
            end = min(start + segment_length, safe_end)
            segments.append((start, end))
    
    return segments

# ============== WHISPER TRANSCRIPTION ==============
def transcribe_audio(audio_path: str):
    """Transcribe audio using Whisper AI"""
    try:
        model = whisper.load_model("base")  # Use base model for speed
        result = model.transcribe(audio_path, language="hi")  # Hindi by default
        return result['text'], result.get('segments', [])
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return "", []

# ============== SUBTITLE GENERATOR ==============
def generate_ass_subtitles(segments, output_path: str, video_width=1080, video_height=1920):
    """Generate ASS subtitle file with Instagram-style cyan subtitles"""
    
    ass_header = f"""[Script Info]
Title: Auto-generated subtitles
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Impact,70,&H00FFD900,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,10,10,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    dialogues = []
    for seg in segments:
        start = seg.get('start', 0)
        end = seg.get('end', start + 2)
        text = seg.get('text', '').strip().upper()
        
        if text:
            # Format time for ASS
            start_time = format_ass_time(start)
            end_time = format_ass_time(end)
            
            # Split long text into multiple lines
            words = text.split()
            if len(words) > 6:
                mid = len(words) // 2
                line1 = ' '.join(words[:mid])
                line2 = ' '.join(words[mid:])
                text = f"{line1}\\N{line2}"
            
            dialogue = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}"
            dialogues.append(dialogue)
    
    # Write ASS file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(ass_header)
        f.write('\n'.join(dialogues))
    
    return output_path

def format_ass_time(seconds):
    """Convert seconds to ASS time format (H:MM:SS.CS)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int((seconds % 1) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

# ============== VIDEO EDITOR ==============
async def create_short_with_subtitles(video_path: str, start: float, end: float, subtitle_segments, output_path: str, clip_num: int):
    """Create vertical short with burned subtitles"""
    
    try:
        # Load video
        video = VideoFileClip(video_path).subclip(start, end)
        
        # Resize to vertical 9:16 format
        target_width = 1080
        target_height = 1920
        
        # Calculate crop dimensions
        video_aspect = video.w / video.h
        target_aspect = target_width / target_height
        
        if video_aspect > target_aspect:
            # Video is wider, crop width
            new_width = int(video.h * target_aspect)
            x1 = (video.w - new_width) // 2
            video = video.crop(x1=x1, width=new_width)
        else:
            # Video is taller, crop height
            new_height = int(video.w / target_aspect)
            y1 = (video.h - new_height) // 2
            video = video.crop(y1=y1, height=new_height)
        
        # Resize to target resolution
        video = video.resize((target_width, target_height))
        
        # Create subtitle file for this segment
        temp_audio = str(TEMP_DIR / f"audio_{clip_num}.mp3")
        video.audio.write_audiofile(temp_audio, logger=None)
        
        # Transcribe audio
        text, segments = transcribe_audio(temp_audio)
        
        if segments:
            # Adjust segment times relative to clip
            adjusted_segments = []
            for seg in segments:
                adjusted_segments.append({
                    'start': seg['start'],
                    'end': seg['end'],
                    'text': seg['text']
                })
            
            # Generate ASS subtitle
            ass_path = str(TEMP_DIR / f"subtitles_{clip_num}.ass")
            generate_ass_subtitles(adjusted_segments, ass_path, target_width, target_height)
            
            # Save video temporarily
            temp_video = str(TEMP_DIR / f"temp_{clip_num}.mp4")
            video.write_videofile(temp_video, codec='libx264', audio_codec='aac', logger=None)
            video.close()
            
            # Burn subtitles using FFmpeg
            subprocess.run([
                'ffmpeg', '-i', temp_video,
                '-vf', f"ass={ass_path}",
                '-c:v', 'libx264', '-preset', 'medium',
                '-c:a', 'aac', '-b:a', '128k',
                '-y', output_path
            ], check=True, capture_output=True)
            
            # Cleanup temp files
            os.remove(temp_video)
            os.remove(temp_audio)
            os.remove(ass_path)
        else:
            # No subtitles, just save video
            video.write_videofile(output_path, codec='libx264', audio_codec='aac', logger=None)
            video.close()
        
        return output_path
    
    except Exception as e:
        logger.error(f"Error creating short: {e}")
        return None

# ============== BOT HANDLERS ==============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    welcome_msg = """
🎬 *YouTube Shorts Generator Bot* 🎬

✨ *Features:*
• Download long YouTube videos
• Create 3 viral shorts automatically
• Add Instagram-style subtitles (cyan color)
• Vertical 9:16 format ready to upload

📝 *How to use:*
Just send me a YouTube video link!

🚀 Processing takes 10-15 minutes for best quality.

Send a link to get started! 👇
"""
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def process_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process YouTube link and create shorts"""
    
    url = update.message.text
    
    # Validate URL
    if 'youtube.com' not in url and 'youtu.be' not in url:
        await update.message.reply_text("❌ Please send a valid YouTube link!")
        return
    
    # Start processing
    status_msg = await update.message.reply_text(
        "⏳ *Processing your video...*\n\n"
        "📥 Step 1/5: Downloading video...",
        parse_mode='Markdown'
    )
    
    try:
        # Download video
        video_id = str(int(time.time()))
        video_path = str(TEMP_DIR / f"video_{video_id}.mp4")
        
        downloaded_path, title, duration = await download_video(url, video_path)
        
        if not downloaded_path:
            await status_msg.edit_text("❌ Failed to download video. Please try another link.")
            return
        
        await status_msg.edit_text(
            f"✅ Downloaded: {title[:50]}...\n\n"
            f"🎬 Step 2/5: Analyzing best moments...",
            parse_mode='Markdown'
        )
        
        # Analyze scenes
        segments = analyze_scenes(downloaded_path, duration, num_clips=3)
        
        await status_msg.edit_text(
            f"✅ Found 3 best moments!\n\n"
            f"✂️ Step 3/5: Creating shorts...",
            parse_mode='Markdown'
        )
        
        # Create shorts
        shorts = []
        for i, (start, end) in enumerate(segments):
            await status_msg.edit_text(
                f"🎥 Creating short {i+1}/3...\n"
                f"⏱️ This may take 3-5 minutes...",
                parse_mode='Markdown'
            )
            
            output_path = str(OUTPUT_DIR / f"short_{video_id}_{i+1}.mp4")
            
            result = await create_short_with_subtitles(
                downloaded_path, start, end, [], output_path, i+1
            )
            
            if result:
                shorts.append(result)
        
        # Cleanup
        if os.path.exists(downloaded_path):
            os.remove(downloaded_path)
        
        if not shorts:
            await status_msg.edit_text("❌ Failed to create shorts. Please try another video.")
            return
        
        await status_msg.edit_text(
            f"📤 Step 5/5: Uploading shorts...\n"
            f"⏳ Please wait...",
            parse_mode='Markdown'
        )
        
        # Send shorts
        for i, short_path in enumerate(shorts):
            caption = f"🎬 *Short {i+1}/3*\n\n📹 Ready to upload!\n✨ Subtitles included"
            
            with open(short_path, 'rb') as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption=caption,
                    parse_mode='Markdown',
                    supports_streaming=True,
                    width=1080,
                    height=1920
                )
            
            # Cleanup
            os.remove(short_path)
            await asyncio.sleep(2)
        
        await status_msg.edit_text(
            "✅ *Done!* 3 viral shorts created! 🎉\n\n"
            "📲 Download and upload to YouTube/Instagram!\n\n"
            "🔄 Send another link to create more shorts!",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Processing error: {e}")
        await status_msg.edit_text(
            f"❌ Error occurred: {str(e)}\n\n"
            f"Please try another video or contact support."
        )

# ============== MAIN ==============
def main():
    """Start the bot"""
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found in environment variables!")
        return
    
    logger.info("🤖 Starting YouTube Shorts Bot...")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_youtube_link))
    
    # Start bot
    logger.info("✅ Bot is running 24/7...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
