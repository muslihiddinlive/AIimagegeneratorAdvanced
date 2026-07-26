"""
Stable Horde orqali rasm generatsiyasi.

Stable Horde - ko'ngillilar (community) GPU tarmog'i orqali BEPUL Stable
Diffusion rasm generatsiyasi taqdim etadi.
  AFZALLIGI: butunlay bepul, hech qanday to'lov/kredit karta kerak emas.
  KAMCHILIGI: tezlik ko'ngillilar mavjudligiga bog'liq - Pollinations kabi
  "darhol" emas, odatda 10-60 soniya, navbat holatiga qarab bir necha
  daqiqagacha cho'zilishi mumkin.

Ish jarayoni (async job model):
  1. POST /generate/async  - so'rov yuboriladi, ishga "id" beriladi
  2. GET  /generate/check/{id} - tayyor bo'lguncha davriy so'raladi (polling)
  3. GET  /generate/status/{id} - tayyor bo'lganda rasm URL keladi (r2=true)
"""
import asyncio
import base64
import logging

import aiohttp

from config import (
    STABLE_HORDE_API_KEY, STABLE_HORDE_API_URL,
    STABLE_HORDE_MAX_WAIT_SECONDS, STABLE_HORDE_POLL_INTERVAL_SECONDS,
)

logger = logging.getLogger("stable_horde")


class StableHordeError(Exception):
    pass


class StableHordeTimeoutError(StableHordeError):
    """Navbat juda uzoq davom etdi (ko'ngillilar band) - fallback ishlatilsin."""


async def generate_image(prompt: str, width: int = 512, height: int = 512) -> bytes:
    """Stable Horde orqali rasm generatsiya qiladi va bayt sifatida qaytaradi.
    Xato/timeout bo'lsa mos exception ko'taradi - chaqiruvchi tomon
    (masalan Pollinations'ga) fallback qilishi kerak."""
    headers = {
        "apikey": STABLE_HORDE_API_KEY or "0000000000",  # "0000000000" = anonim, past prioritet
        "Content-Type": "application/json",
        "Client-Agent": "RasmYaratuvchiRobot:1.0:telegram-bot",
    }
    payload = {
        "prompt": prompt,
        "params": {
            "width": width,
            "height": height,
            "steps": 25,
            "cfg_scale": 7,
            "sampler_name": "k_euler",
            "n": 1,
        },
        "models": ["stable_diffusion"],
        "nsfw": False,
        "censor_nsfw": True,
        "r2": True,  # rasmni bevosita URL sifatida qaytarish (base64 o'rniga)
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{STABLE_HORDE_API_URL}/generate/async", json=payload, headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status not in (200, 202):
                body = await resp.text()
                raise StableHordeError(f"submit status={resp.status} body={body[:300]!r}")
            data = await resp.json()
            job_id = data.get("id")
            if not job_id:
                raise StableHordeError(f"job id qaytmadi: {data!r}")

        elapsed = 0.0
        done = False
        while elapsed < STABLE_HORDE_MAX_WAIT_SECONDS:
            await asyncio.sleep(STABLE_HORDE_POLL_INTERVAL_SECONDS)
            elapsed += STABLE_HORDE_POLL_INTERVAL_SECONDS
            try:
                async with session.get(
                    f"{STABLE_HORDE_API_URL}/generate/check/{job_id}",
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    check = await resp.json()
            except Exception as e:
                logger.warning(f"[stable_horde] check so'rovida xato: {e}")
                continue
            if check.get("faulted"):
                raise StableHordeError(f"generatsiya muvaffaqiyatsiz (faulted): {check!r}")
            if check.get("done"):
                done = True
                break

        if not done:
            # Vaqt tugadi - kudos tejash uchun ishni bekor qilishga harakat qilamiz.
            try:
                async with session.delete(
                    f"{STABLE_HORDE_API_URL}/generate/status/{job_id}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ):
                    pass
            except Exception:
                pass
            raise StableHordeTimeoutError(
                f"{STABLE_HORDE_MAX_WAIT_SECONDS}s ichida tayyor bo'lmadi (ko'ngillilar band)"
            )

        async with session.get(
            f"{STABLE_HORDE_API_URL}/generate/status/{job_id}",
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            status = await resp.json()

        generations = status.get("generations") or []
        if not generations:
            raise StableHordeError(f"generations bo'sh: {status!r}")

        img_field = generations[0].get("img")
        if not img_field:
            raise StableHordeError("rasm maydoni (img) topilmadi")

        if img_field.startswith("http"):
            async with session.get(img_field, timeout=aiohttp.ClientTimeout(total=20)) as img_resp:
                return await img_resp.read()

        return base64.b64decode(img_field)
