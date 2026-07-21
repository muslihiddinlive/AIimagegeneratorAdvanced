import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from config import (
    BOT_TOKEN, WEBHOOK_PATH, WEBHOOK_URL, WEBHOOK_SECRET, WEBHOOK_HOST, PORT,
)
from state import store
from queue_worker import gen_queue
from handlers import admin, user

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

# TARTIB MUHIM:
# 1) admin - inline callbacklar va FSM holatlari (masalan broadcast matni kutish)
# 2) user  - /start, oddiy matn (prompt sifatida)
dp.include_router(admin.router)
dp.include_router(user.router)


async def health(request: web.Request) -> web.Response:
    """UptimeRobot va Render uchun oddiy health-check"""
    return web.Response(text="OK")


async def on_startup(app: web.Application):
    # Guruhdagi pin qilingan bot_state.html dan holatni tiklaymiz
    await store.load(bot)

    # Rasm generatsiya navbatini ishga tushiramiz (bitta worker, ketma-ket bajaradi)
    gen_queue.start()

    if not WEBHOOK_HOST:
        logging.warning(
            "WEBHOOK_HOST (RENDER_EXTERNAL_URL) topilmadi - webhook o'rnatilmadi! "
            "Render'da bu avtomatik bo'lishi kerak."
        )
        return

    await bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
    logging.info(f"Webhook o'rnatildi: {WEBHOOK_URL}")


async def on_shutdown(app: web.Application):
    # MUHIM: bot.delete_webhook() ATAYLAB chaqirilmaydi.
    # Render bepul tarifida xizmat uxlab qolganda shu funksiya ishga tushadi;
    # agar shu yerda webhookni o'chirsak, Telegram uni qayerga yuborishni
    # bilmay qoladi va xizmatni HECH NARSA qayta uyg'otolmaydi. Webhook
    # Telegram tomonda saqlanib qolsa, keyingi POST so'rovining o'zi
    # Render xizmatini tabiiy tarzda uyg'otadi.
    await bot.session.close()


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", health)

    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    )
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
