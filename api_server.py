"""
Tashqi dasturchilar uchun HTTP API.

Boshqalar o'z botiga yoki ilovasiga "AI ning rasm-generatsiya API'si" sifatida
ulab qo'yishlari mumkin bo'lgan endpoint. Har bir chaqiruv API kalit orqali
autentifikatsiya qilinadi, kalitga tegishli kunlik limitdan bittasi
ishlatiladi, va yaratilgan rasm ADMIN DB guruhiga ham log sifatida yuboriladi
(kim qancha ishlatganini kuzatib borish uchun).

Foydalanish:
    GET/POST /api/generate?key=RasmYaratuvchiRobot_XXXXXX&prompt=...

Javob:
    200  -> rasm baytlari (Content-Type: image/jpeg)
    400  -> {"error": "..."}               (prompt yo'q / juda uzun)
    401  -> {"error": "invalid_key"} yoki {"error": "revoked"} yoki {"error": "expired"}
    429  -> {"error": "limit_exceeded", "daily_limit": N, "used_today": N}
    500  -> {"error": "generation_failed"}
"""

import logging

from aiohttp import web

from state import store
from pollinations import generate_image
from groq_preprocessor import optimize_prompt, validate_prompt_length, PromptTooLongError
from config import DB_GROUP_ID, INTERNAL_PROXY_SECRET

logger = logging.getLogger("api_server")

_STATUS_BY_REASON = {
    "invalid": 401,
    "revoked": 401,
    "expired": 401,
    "limit": 429,
}


async def _extract_params(request: web.Request) -> tuple[str | None, str | None]:
    """key va prompt'ni query paramdan, header'dan (X-API-Key) yoki JSON
    bodydan (POST) o'qiydi - qaysi biri bilan chaqirish qulay bo'lsa shu
    ishlaydi."""
    key = request.query.get("key") or request.headers.get("X-API-Key")
    prompt = request.query.get("prompt")

    if request.method == "POST" and (not key or not prompt):
        try:
            body = await request.json()
        except Exception:
            body = {}
        key = key or body.get("key")
        prompt = prompt or body.get("prompt")

    return key, prompt


async def handle_generate(request: web.Request) -> web.Response:
    # Faqat Vercel proxy orqali kelgan so'rovlarni qabul qilamiz (agar sozlangan
    # bo'lsa). Bu Render manzili qandaydir tarzda ma'lum bo'lib qolsa ham,
    # to'g'ridan-to'g'ri chaqirishning oldini oladi.
    if INTERNAL_PROXY_SECRET:
        if request.headers.get("X-Proxy-Secret") != INTERNAL_PROXY_SECRET:
            return web.json_response({"error": "forbidden"}, status=403)

    key, prompt = await _extract_params(request)

    if not key:
        return web.json_response({"error": "missing_key"}, status=400)
    if not prompt or not prompt.strip():
        return web.json_response({"error": "missing_prompt"}, status=400)

    try:
        validate_prompt_length(prompt)
    except PromptTooLongError as e:
        return web.json_response(
            {"error": "prompt_too_long", "length": e.length, "limit": e.limit}, status=400,
        )

    ok, reason, info = store.consume_api_key(key)
    if not ok:
        status = _STATUS_BY_REASON.get(reason, 401)
        payload = {"error": reason}
        if reason == "limit" and info:
            payload["daily_limit"] = info["daily_limit"]
            payload["used_today"] = info["used_today"]
        return web.json_response(payload, status=status)

    bot = request.app["bot"]
    try:
        optimized = await optimize_prompt(prompt)
        image_bytes = await generate_image(optimized)
    except Exception as e:
        # Generatsiya bizning tomondan xato bo'lgani uchun ishlatilgan
        # limitni tashqi dasturchiga qaytaramiz - uning aybi emas.
        store.refund_api_key(key)
        logger.exception(f"API generatsiya xatosi: {e}")
        return web.json_response({"error": "generation_failed"}, status=500)

    # Admin DB guruhiga log (kim, qancha limit qolgani, qaysi prompt bilan)
    try:
        from aiogram.types import BufferedInputFile
        remaining = info["daily_limit"] - info["used_today"]
        caption = (
            f"🔌 <b>API orqali generatsiya</b>\n"
            f"🏷 Key nomi: {info['name']}\n"
            f"🔑 Key: <code>{key}</code>\n"
            f"📊 Bugungi qolgan limit: {remaining}/{info['daily_limit']}\n"
            f"📈 Jami generatsiya: {info['total_generated']}\n"
            f"📝 Prompt: {optimized[:200]}"
        )
        await bot.send_photo(
            DB_GROUP_ID,
            BufferedInputFile(image_bytes, filename="api_generated.jpg"),
            caption=caption,
        )
    except Exception as e:
        logger.warning(f"API generatsiyani DB guruhga log qilib bo'lmadi: {e}")

    return web.Response(body=image_bytes, content_type="image/jpeg")


def register_api_routes(app: web.Application):
    app.router.add_get("/api/generate", handle_generate)
    app.router.add_post("/api/generate", handle_generate)
