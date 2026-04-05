import asyncio
import aiohttp
import os
import uuid
import subprocess

from aiogram import Bot, Dispatcher
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = "8648830104:AAEc8EFi1lqoOCMLh5N4UxxbHoVtOsSEL84"

INSTAGRAM_API = "https://api.delirius.store/download/instagram?url="
TIKTOK_API = "https://api.delirius.store/download/tiktok?url="

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()


# START COMMAND
@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "👋 <b>Instagram / TikTok Downloader</b>\n\n"
        "Send an Instagram or TikTok link and I will download the media."
    )


# FETCH FROM DELIRIUS API (auto-select endpoint)
async def fetch_api(url: str):

    if "tiktok.com" in url or "vm.tiktok.com" in url:
        api = f"{TIKTOK_API}{url}"
    else:
        api = f"{INSTAGRAM_API}{url}"

    async with aiohttp.ClientSession() as session:
        async with session.get(api) as resp:
            return await resp.json()


# STREAM DOWNLOAD FILE
async def download_file(url):

    filename = f"/tmp/{uuid.uuid4().hex}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:

            with open(filename, "wb") as f:

                async for chunk in resp.content.iter_chunked(1024 * 256):
                    f.write(chunk)

    return filename


# CREATE VIDEO THUMBNAIL
def create_thumbnail(video_path):

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


# MAIN DOWNLOADER
@dp.message()
async def downloader(message: Message):

    url = (message.text or "").strip()

    if not url or ("instagram.com" not in url and "tiktok.com" not in url and "vm.tiktok.com" not in url):
        await message.reply("❌ Please send a valid Instagram or TikTok link.")
        return

    status = await message.reply("⏳ Fetching media...")

    try:

        data = await fetch_api(url)

        if not data or not data.get("status"):
            await status.edit_text("❌ Failed to fetch media.")
            return

        # Normalize different API shapes into a list of media dicts with keys: url, type
        media_list = []

        # TikTok response: data is a dict with meta.media list
        if "tiktok.com" in url or "vm.tiktok.com" in url:

            d = data.get("data", {}) or {}
            meta_media = d.get("meta", {}).get("media", [])

            for m in meta_media:
                mtype = m.get("type")

                if mtype == "video":
                    # prefer original (org) then hd then wm
                    vurl = m.get("org") or m.get("hd") or m.get("wm")
                    if vurl:
                        media_list.append({"url": vurl, "type": "video"})

                elif mtype == "image":
                    images = m.get("images", []) or []
                    for img in images:
                        media_list.append({"url": img, "type": "image"})

                    # sometimes there's a separate audio file we can also download
                    audio = m.get("audio")
                    if audio:
                        media_list.append({"url": audio, "type": "audio"})

                else:
                    # fallback: try to find any direct url fields
                    for key in ("org", "hd", "wm", "url"):
                        if m.get(key):
                            media_list.append({"url": m.get(key), "type": mtype or "file"})
                            break

        else:
            # Instagram response: data is already a list of media dicts {url, type}
            media_list = data.get("data", []) or []

        if not media_list:
            await status.edit_text("❌ No media found.")
            return

        await status.edit_text("📥 Downloading...")

        downloaded_files = []

        for media in media_list:

            # some items might be simple strings (older API shapes), normalize
            if isinstance(media, str):
                file_path = await download_file(media)
                downloaded_files.append((file_path, "file"))
            else:
                url_to_dl = media.get("url") or media.get("org") or media.get("hd") or media.get("wm")
                mtype = media.get("type") or "file"

                if not url_to_dl:
                    continue

                file_path = await download_file(url_to_dl)
                downloaded_files.append((file_path, mtype))

        await status.edit_text("⬆ Uploading...")

        for file_path, media_type in downloaded_files:

            file = FSInputFile(file_path)

            if media_type == "video":

                thumb = create_thumbnail(file_path)

                # send video with thumbnail
                try:
                    await message.answer_video(
                        video=file,
                        thumbnail=FSInputFile(thumb) if os.path.exists(thumb) else None,
                        supports_streaming=True
                    )
                except Exception:
                    # fallback to sending as document if answer_video fails
                    await message.answer_document(file)

                if os.path.exists(thumb):
                    os.remove(thumb)

            elif media_type == "image":

                try:
                    await message.answer_photo(file)
                except Exception:
                    await message.answer_document(file)

            elif media_type == "audio":

                try:
                    await message.answer_audio(file)
                except Exception:
                    await message.answer_document(file)

            else:

                await message.answer_document(file)

            if os.path.exists(file_path):
                os.remove(file_path)

        await status.delete()

    except Exception as e:

        await message.reply(f"❌ Error: {e}")


# RUN BOT
async def main():

    print("🚀 Bot started")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
