import asyncio
import urllib.parse
import aiohttp

from config import POLLINATIONS_URL, GEN_QUEUE_WORKERS

# bir vaqtda ketadigan parallel so'rovlar sonini cheklaymiz - navbat
# (queue_worker.py) workerlari bilan bir xil songa moslangan, shunda ikkalasi
# ham bir-biriga to'siq bo'lmaydi
_semaphore = asyncio.Semaphore(GEN_QUEUE_WORKERS)


async def generate_image(prompt: str, width: int = 1024, height: int = 1024) -> bytes:
    encoded = urllib.parse.quote(prompt)
    url = POLLINATIONS_URL.format(prompt=encoded)
    # `model` ni ANIQ belgilaymiz - Pollinations'ning "default" modeli vaqt
    # o'tishi bilan ogohlantirishsiz o'zgarishi mumkin, shuning uchun sifat
    # natijasi barqaror bo'lishi uchun aniq nomini yozamiz.
    params = {"width": width, "height": height, "nologo": "true", "model": "flux"}

    async with _semaphore:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"pollinations status={resp.status} body={body[:300]!r}")
                return await resp.read()
