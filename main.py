import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.enums import ParseMode

BOT_TOKEN = "8648830104:AAEc8EFi1lqoOCMLh5N4UxxbHoVtOsSEL84"

API_URL = "https://api.delirius.store/download/instagram?url="

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "👋 Send me an Instagram link.\n\n"
        "I will download the video or images for you."
    )


async def fetch_instagram(url: str):
    api = f"{API_URL}{url}"

    async with aiohttp.ClientSession() as session:
        async with session.get(api) as resp:
            data = await resp.json()
            return data


@dp.message()
async def downloader(message: Message):
    url = message.text.strip()

    if "instagram.com" not in url:
        await message.reply("❌ Send a valid Instagram link.")
        return

    await message.reply("⏳ Downloading...")

    try:
        data = await fetch_instagram(url)

        if not data.get("status"):
            await message.reply("❌ Failed to fetch media.")
            return

        media_list = data.get("data", [])

        for media in media_list:
            media_url = media["url"]
            media_type = media["type"]

            if media_type == "video":
                await message.answer_video(media_url)

            elif media_type == "image":
                await message.answer_photo(media_url)

            else:
                await message.answer_document(media_url)

    except Exception as e:
        await message.reply(f"❌ Error: {e}")


async def main():
    print("Bot started...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
