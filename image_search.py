"""
Ma'lum brend/logo rasmlarini internetdan (Wikipedia orqali) qidirish.

Taniqli brendlar (Tesla, Microsoft, Apple va h.k.) uchun deyarli har doim
Wikipedia maqolasida rasmiy logotip bor - shuning uchun bu bepul, kalitsiz
yechim: avval mavjud, sifatli rasmni topishga harakat qilamiz, faqat
topilmasa AI orqali generatsiya qilishga o'tamiz.
"""
import logging

import aiohttp

logger = logging.getLogger("image_search")

_WIKI_API = "https://en.wikipedia.org/w/api.php"


async def search_logo_image(query: str) -> bytes | None:
    """Berilgan nom (masalan "Tesla logo") bo'yicha Wikipedia'dan tayyor
    rasm qidiradi. Hech narsa topilmasa None qaytaradi (chaqiruvchi tomon
    keyin AI generatsiyaga o'tishi kerak)."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            search_params = {
                "action": "query", "list": "search", "srsearch": query,
                "format": "json", "srlimit": 1,
            }
            async with session.get(_WIKI_API, params=search_params) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            results = data.get("query", {}).get("search", [])
            if not results:
                return None
            title = results[0]["title"]

            img_params = {
                "action": "query", "titles": title, "prop": "pageimages",
                "format": "json", "pithumbsize": 1024,
            }
            async with session.get(_WIKI_API, params=img_params) as resp:
                if resp.status != 200:
                    return None
                img_data = await resp.json()

            pages = img_data.get("query", {}).get("pages", {})
            for page in pages.values():
                thumb = (page.get("thumbnail") or {}).get("source")
                if not thumb:
                    continue
                async with session.get(thumb) as img_resp:
                    if img_resp.status == 200:
                        return await img_resp.read()
            return None
    except Exception as e:
        logger.warning(f"[image_search] qidiruvda xato ({query!r}): {e}")
        return None
