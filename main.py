import asyncio
import aiohttp
import os
import uuid
import subprocess
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

INSTAGRAM_API = "https://api.delirius.store/download/instagram?url="
TIKTOK_API = "https://api.delirius.store/download/tiktok?url="
YOUTUBE_API = "https://api.delirius.store/download/ytmp4"

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "👋 <b>Instagram / TikTok / YouTube Downloader</b>\n\n"
        "Send an Instagram, TikTok or YouTube link and I will download the media."
    )


async def fetch_data(url: str):
    """
    Query the delirius API for the given URL.
    For YouTube: call the ytmp4 endpoint with query params (format=720).
    For TikTok/Instagram: call the respective endpoints.
    """
    u = (url or "").lower()
    is_tiktok = any(x in u for x in ("tiktok", "tiktokcdn", "vm.tiktok"))
    is_youtube = any(x in u for x in ("youtube.com", "youtu.be", "youtube"))

    async with aiohttp.ClientSession() as session:
        if is_youtube:
            # Use params so the youtube url is properly passed and format set to 720
            async with session.get(YOUTUBE_API, params={"url": url, "format": "720"}) as resp:
                if resp.status != 200:
                    return {"status": False}
                return await resp.json()
        if is_tiktok:
            api = f"{TIKTOK_API}{url}"
        else:
            api = f"{INSTAGRAM_API}{url}"
        async with session.get(api) as resp:
            if resp.status != 200:
                return {"status": False}
            return await resp.json()


async def download_file(url: str):
    """
    Download a remote file to a temp path and return the filename.
    Uses a total timeout and cleans up partial files on error.
    Raises RuntimeError on failure with a message including the URL and the original error.
    """
    filename = f"/tmp/{uuid.uuid4().hex}"
    timeout = aiohttp.ClientTimeout(total=120)  # 120 seconds total
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; InstaDownloader/1.0; +https://github.com)"
    }
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    raise ValueError(f"Download failed (status={resp.status}) for {url}")
                with open(filename, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 256):
                        if not chunk:
                            continue
                        f.write(chunk)
    except Exception as exc:
        # remove partial file if present, then re-raise with context
        try:
            if os.path.exists(filename):
                os.remove(filename)
        except Exception:
            pass
        raise RuntimeError(f"download error for {url}: {exc}") from exc

    try:
        size = os.path.getsize(filename)
    except OSError:
        size = 0
    if size == 0:
        if os.path.exists(filename):
            os.remove(filename)
        raise ValueError("Downloaded file is empty")
    return filename


def create_thumbnail(video_path: str):
    thumb = f"{video_path}.jpg"
    command = [
        "ffmpeg",
        "-ss", "00:00:01",
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        thumb
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return thumb


def parse_media(api_json, original_url: str):
    """
    Normalize the API response into a list of {'url': ..., 'type': ...}
    Supports:
     - YouTube ytmp4 (data.download -> video)
     - existing Instagram/TikTok shapes used previously
    """
    out = []
    data = api_json.get("data")

    # YouTube ytmp4 returns data.download with direct mp4 link
    if isinstance(data, dict) and data.get("download"):
        out.append({"url": data.get("download"), "type": "video"})
        return out

    if isinstance(data, list):
        for m in data:
            murl = m.get("url")
            mtype = m.get("type", "document")
            if murl:
                out.append({"url": murl, "type": mtype})
        return out

    if isinstance(data, dict):
        meta = data.get("meta", {})
        media = meta.get("media", [])
        for m in media:
            mtype = m.get("type")
            if mtype == "video":
                url = m.get("org") or m.get("hd") or m.get("wm")
                if url:
                    out.append({"url": url, "type": "video"})
            elif mtype == "image":
                images = m.get("images", [])
                for img in images:
                    if img:
                        out.append({"url": img, "type": "image"})
                audio = m.get("audio")
                if audio:
                    out.append({"url": audio, "type": "audio"})
            else:
                for k in ("url", "org", "hd", "wm"):
                    if m.get(k):
                        out.append({"url": m.get(k), "type": mtype or "document"})
                        break
        return out

    if isinstance(api_json, dict) and api_json.get("url"):
        out.append({"url": api_json.get("url"), "type": "document"})
    return out


@dp.message()
async def downloader(message: Message):
    url = (message.text or "").strip()
    if not url:
        await message.reply("❌ Please send a valid Instagram, TikTok or YouTube link.")
        return
    u = url.lower()
    if ("instagram.com" not in u) and ("tiktok" not in u) and ("youtube.com" not in u) and ("youtu.be" not in u):
        await message.reply("❌ Please send a valid Instagram, TikTok or YouTube link.")
        return
    status = await message.reply("⏳ Fetching media...")
    try:
        data = await fetch_data(url)
        if not data.get("status"):
            await status.edit_text("❌ Failed to fetch media.")
            return
        media_list = parse_media(data, url)
        if not media_list:
            await status.edit_text("❌ No media found.")
            return
        await status.edit_text("📥 Downloading...")
        downloaded_files = []
        for media in media_list:
            murl = media.get("url")
            mtype = media.get("type", "document")
            if not murl:
                continue
            try:
                file_path = await download_file(murl)
                downloaded_files.append((file_path, mtype))
            except Exception as e:
                # Provide URL + real error to aid debugging (and manual testing)
                await message.reply(f"⚠️ Skipped a file (download failed) for {murl}: {e}")
        if not downloaded_files:
            await status.edit_text("❌ Nothing downloaded.")
            return
        await status.edit_text("⬆ Uploading...")
        for file_path, media_type in downloaded_files:
            file = FSInputFile(file_path)
            try:
                if media_type == "video":
                    thumb = create_thumbnail(file_path)
                    thumb_file = FSInputFile(thumb) if os.path.exists(thumb) else None
                    await message.answer_video(
                        video=file,
                        thumbnail=thumb_file,
                        supports_streaming=True
                    )
                    if thumb_file and os.path.exists(thumb):
                        os.remove(thumb)
                elif media_type == "image":
                    await message.answer_photo(file)
                elif media_type == "audio":
                    await message.answer_audio(file)
                else:
                    await message.answer_document(file)
            except Exception as e:
                await message.reply(f"❌ Telegram send failed: {e}")
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
        await status.delete()
    except Exception as e:
        await message.reply(f"❌ Error: {e}")


async def main():
    print("🚀 Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
