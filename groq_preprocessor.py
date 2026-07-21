"""
Groq preprocessing qatlami.

Pollinations.ai o'zbek tilini va imlo xatoli/murakkab promptlarni yaxshi
tushunmagani uchun, rasm generatsiya qilishdan OLDIN foydalanuvchi promptini
Groq (llama-3.3-70b-versatile / llama-3.1-8b-instant) orqali:
  1) imlo xatolaridan tozalaydi,
  2) qisqartiradi,
  3) yuqori sifatli inglizchaga tarjima qiladi.

Bu modul ikkita muammoni ham hal qiladi:
  - Groq Free Tier RPM/TPM limitiga urilib qolmaslik uchun so'rovlar orasida
    minimal interval (throttling/queue) qo'yiladi.
  - 429 (Too Many Requests) kelsa, `retry-after` header'ini o'qib,
    exponential backoff bilan avtomatik qayta urinadi.

Chaqiruvchi tomon (handlers/user.py) uchun yagona kirish nuqtasi:

    optimized = await optimize_prompt(raw_prompt)

`optimized` har doim STRIKT 300 belgidan kam bo'lishi kafolatlanadi
(Groq buzsa ham, server tomonda xavfsizlik uchun qat'iy kesiladi).
Groq umuman ishlamay qolsa (tarmoq, auth, barcha retry tugagan), bot
to'xtab qolmasligi uchun mahalliy fallback (oddiy tozalash + kesish)
ishlatiladi - shunda foydalanuvchi baribir natija oladi, faqat tarjimasiz.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import aiohttp

from config import (
    GROQ_API_KEY,
    GROQ_API_URL,
    GROQ_MODEL,
    GROQ_MAX_RETRIES,
    GROQ_MIN_INTERVAL_SECONDS,
    GROQ_OUTPUT_MAX_LEN,
    GROQ_REQUEST_TIMEOUT_SECONDS,
    PROMPT_MAX_INPUT_LEN,
)

logger = logging.getLogger("groq_preprocessor")


class PromptTooLongError(Exception):
    """Foydalanuvchi promptining belgi limitidan oshganini bildiradi."""

    def __init__(self, length: int, limit: int):
        self.length = length
        self.limit = limit
        super().__init__(f"prompt too long: {length} > {limit}")


class GroqUnavailableError(Exception):
    """Groq barcha retrylardan keyin ham javob bermaganda ko'tariladi
    (chaqiruvchi tomon buni ushlab, fallback ishlatishi mumkin)."""


def validate_prompt_length(prompt: str) -> None:
    """
    1-band: foydalanuvchi promptining MAX 500 belgi limitini tekshiradi.
    Oshsa - foydalanuvchiga tushunarli xabar chiqarish uchun ishlatiladigan
    PromptTooLongError'ni ko'taradi.
    """
    length = len(prompt)
    if length > PROMPT_MAX_INPUT_LEN:
        raise PromptTooLongError(length=length, limit=PROMPT_MAX_INPUT_LEN)


def build_length_error_message(err: PromptTooLongError) -> str:
    """Foydalanuvchiga ko'rsatiladigan chiroyli va aniq xatolik matni."""
    ortiqcha = err.length - err.limit
    return (
        "✋ <b>Prompt juda uzun</b>\n\n"
        f"Sizning matningiz: <b>{err.length}</b> belgi\n"
        f"Ruxsat etilgan limit: <b>{err.limit}</b> belgi\n"
        f"Kamida <b>{ortiqcha}</b> belgi qisqartiring.\n\n"
        "💡 Iltimos, rasm tavsifini qisqaroq va aniqroq yozib qayta yuboring."
    )


class _GroqRateLimiter:
    """
    Groq Free Tier'ning TPM/RPM limitiga urilib qolmaslik uchun so'rovlar
    orasida minimal interval qo'yadigan oddiy async throttle.

    Bir nechta foydalanuvchi bir vaqtda rasm so'rasa ham, Groq'ga ketadigan
    so'rovlar FIFO tartibda, bir-biridan kamida `min_interval` soniya farq
    bilan ketishini kafolatlaydi (debounce/queue mexanizmi).
    """

    def __init__(self, min_interval: float):
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_call_at: float = 0.0

    async def wait_turn(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call_at
            wait_for = self._min_interval - elapsed
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_call_at = time.monotonic()


_rate_limiter = _GroqRateLimiter(GROQ_MIN_INTERVAL_SECONDS)

_SYSTEM_PROMPT = (
    "You are a prompt-optimizing engine for an AI image generator. "
    "You receive raw user input, which may be in Uzbek, may contain typos, "
    "may be informal or verbose. Your job:\n"
    "1. Fix spelling/grammar mistakes.\n"
    "2. Translate the meaning into English if it is not already in English.\n"
    "3. Rewrite it as a concise, vivid, high-quality image-generation prompt.\n"
    f"4. The final English prompt MUST be strictly under {GROQ_OUTPUT_MAX_LEN} characters.\n"
    "Reply with ONLY the final English prompt text - no greetings, no quotes, "
    "no markdown, no explanations, no labels like 'Prompt:'."
)


def _strip_wrapping(text: str) -> str:
    """Groq ba'zan qo'shib yuboradigan qo'shtirnoq/markdown izlarini tozalaydi."""
    cleaned = text.strip()
    cleaned = cleaned.strip("`")
    if len(cleaned) >= 2 and cleaned[0] in "\"'" and cleaned[-1] in "\"'":
        cleaned = cleaned[1:-1].strip()
    for prefix in ("Prompt:", "prompt:", "Final prompt:", "English prompt:"):
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = cleaned[len(prefix):].strip()
    return cleaned


def _hard_enforce_max_len(text: str, max_len: int) -> str:
    """
    Xavfsizlik zaxirasi (defense in depth): Groq talabni buzsa ham,
    yakuniy natija HAR DOIM `max_len` dan kam bo'lishini kafolatlaydi.
    So'z chegarasidan kesishga harakat qiladi, aks holda qattiq kesadi.
    """
    if len(text) < max_len:
        return text
    truncated = text[: max_len - 1]
    last_space = truncated.rfind(" ")
    if last_space > max_len * 0.5:
        truncated = truncated[:last_space]
    return truncated.strip()


def _local_fallback(prompt: str) -> str:
    """
    Groq butunlay ishlamay qolganda (tarmoq/auth/barcha retry tugagan)
    ishlatiladigan oxirgi chora: tarjimasiz, lekin bot to'xtamasligi uchun
    oddiy tozalash + qattiq kesish.
    """
    normalized = " ".join(prompt.split())
    return _hard_enforce_max_len(normalized, GROQ_OUTPUT_MAX_LEN)


@dataclass
class _GroqCallResult:
    content: str


async def _call_groq_once(session: aiohttp.ClientSession, prompt: str) -> _GroqCallResult:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 150,
        "stream": False,
    }
    timeout = aiohttp.ClientTimeout(total=GROQ_REQUEST_TIMEOUT_SECONDS)

    async with session.post(GROQ_API_URL, headers=headers, json=payload, timeout=timeout) as resp:
        if resp.status == 429:
            retry_after_header = resp.headers.get("retry-after")
            body = await resp.text()
            raise _GroqRateLimitedError(retry_after_header, body[:300])

        if resp.status >= 500:
            body = await resp.text()
            raise _GroqServerError(resp.status, body[:300])

        if resp.status != 200:
            body = await resp.text()
            # 4xx (401/400 va h.k.) qayta urinib bo'lmaydigan xatolar -
            # retry qilish ma'nosiz, darhol chiqib ketamiz.
            raise GroqUnavailableError(f"groq status={resp.status} body={body!r}")

        data = await resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise GroqUnavailableError(f"groq unexpected response shape: {data!r}") from e

        return _GroqCallResult(content=content)


class _GroqRateLimitedError(Exception):
    def __init__(self, retry_after_header: str | None, body: str):
        self.retry_after_header = retry_after_header
        self.body = body
        super().__init__(f"429 retry-after={retry_after_header} body={body!r}")


class _GroqServerError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"groq {status}: {body!r}")


def _parse_retry_after(header_value: str | None, fallback: float) -> float:
    if not header_value:
        return fallback
    try:
        return max(float(header_value), 0.0)
    except ValueError:
        return fallback


async def _call_groq_with_retry(prompt: str) -> str:
    """
    3-band: rate limit boshqaruvi.
    - Har bir chaqiruvdan oldin throttle navbatida kutadi (RPM/TPM himoyasi).
    - 429 kelsa: retry-after (yoki shu bo'lmasa exponential backoff) bilan
      qayta urinadi, GROQ_MAX_RETRIES martagacha.
    - 5xx kelsa: ham exponential backoff bilan qayta urinadi.
    - 4xx (auth, bad request) kelsa: darhol to'xtaydi, qayta urinmaydi.
    """
    last_error: Exception | None = None

    async with aiohttp.ClientSession() as session:
        for attempt in range(GROQ_MAX_RETRIES + 1):
            await _rate_limiter.wait_turn()
            try:
                result = await _call_groq_once(session, prompt)
                return result.content
            except _GroqRateLimitedError as e:
                last_error = e
                backoff = _parse_retry_after(
                    e.retry_after_header, fallback=(2 ** attempt) * 1.5
                )
                logger.warning(
                    "[groq] 429 oldik (urinish %s/%s), %.1fs kutib qayta urinamiz",
                    attempt + 1, GROQ_MAX_RETRIES, backoff,
                )
                await asyncio.sleep(backoff)
            except _GroqServerError as e:
                last_error = e
                backoff = (2 ** attempt) * 1.0
                logger.warning(
                    "[groq] server xatosi %s (urinish %s/%s), %.1fs kutib qayta urinamiz",
                    e.status, attempt + 1, GROQ_MAX_RETRIES, backoff,
                )
                await asyncio.sleep(backoff)
            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                last_error = e
                backoff = (2 ** attempt) * 1.0
                logger.warning(
                    "[groq] tarmoq xatosi %s (urinish %s/%s), %.1fs kutib qayta urinamiz",
                    e, attempt + 1, GROQ_MAX_RETRIES, backoff,
                )
                await asyncio.sleep(backoff)
            except GroqUnavailableError:
                raise

    raise GroqUnavailableError(f"barcha retry tugadi: {last_error}")


async def optimize_prompt(raw_prompt: str) -> str:
    """
    Yagona kirish nuqtasi: xom (o'zbekcha/xato) promptni tozalab,
    inglizchaga tarjima qilib, STRIKT <300 belgi qilib qaytaradi.

    Groq butunlay ishlamasa ham, bu funksiya baribir bot ishlashda
    davom etishi uchun mahalliy fallback qiymatini qaytaradi (xato
    ko'tarmaydi) - shuning uchun chaqiruvchi tomon try/except shart emas,
    lekin xohlasa loglar orqali kuzatib borishi mumkin.
    """
    if not GROQ_API_KEY:
        logger.warning("[groq] GROQ_API_KEY sozlanmagan, mahalliy fallback ishlatilmoqda")
        return _local_fallback(raw_prompt)

    try:
        raw_content = await _call_groq_with_retry(raw_prompt)
    except GroqUnavailableError as e:
        logger.error("[groq] optimallashtirish muvaffaqiyatsiz, fallback ishlatilmoqda: %s", e)
        return _local_fallback(raw_prompt)

    cleaned = _strip_wrapping(raw_content)
    if not cleaned:
        logger.warning("[groq] bo'sh javob qaytdi, fallback ishlatilmoqda")
        return _local_fallback(raw_prompt)

    return _hard_enforce_max_len(cleaned, GROQ_OUTPUT_MAX_LEN)
