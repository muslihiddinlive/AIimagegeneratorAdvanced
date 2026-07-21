import asyncio
import urllib.parse
import aiohttp

from config import POLLINATIONS_URL

# bir vaqtda ketadigan parallel so'rovlar sonini cheklaymiz
_semaphore = asyncio.Semaphore(5)


async def generate_image(prompt: str, width: int = 1024, height: int = 1024) -> bytes:
    encoded = urllib.parse.quote(prompt)
    url = POLLINATIONS_URL.format(prompt=encoded)
    params = {"width": width, "height": height, "nologo": "true"}

    async with _semaphore:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"pollinations status={resp.status} body={body[:300]!r}")
                return await resp.read()
