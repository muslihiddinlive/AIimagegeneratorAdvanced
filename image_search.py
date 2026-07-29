"""
Ma'lum brend/logo/shaxs rasmlarini internetdan (Wikipedia/Wikimedia orqali)
qidirish.

Ikki bosqichli qidiruv:
  1) Wikipedia'ning "File:" nom fazosida to'g'ridan-to'g'ri qidiramiz - bu
     "Nike logo", "Windows logo" kabi so'rovlar uchun ANIQ rasmiy logotip
     fayliga (odatda SVG/PNG, masalan "File:Windows logo - 2021.svg") olib
     boradi - maqolaning tasodifiy skrinshoti emas.
  2) Fayl topilmasa (masalan real shaxs/joy so'ralganda), oddiy maqola
     qidiruvi + shu maqolaning asosiy rasmiga (pageimage) o'tamiz.
"""
import logging

import aiohttp

logger = logging.getLogger("image_search")

_WIKI_API = "https://en.wikipedia.org/w/api.php"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"


async def _search_file_namespace(session: aiohttp.ClientSession, api_url: str, query: str) -> bytes | None:
    """"File:" nom fazosida to'g'ridan-to'g'ri qidiradi (logolar uchun eng aniq usul)."""
    search_params = {
        "action": "query", "list": "search", "srsearch": f"{query} logo",
        "srnamespace": 6, "format": "json", "srlimit": 5,
    }
    async with session.get(api_url, params=search_params) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()

    results = data.get("query", {}).get("search", [])
    file_title = None
    for r in results:
        title = r.get("title", "")
        if title.lower().endswith((".svg", ".png", ".jpg", ".jpeg")):
            file_title = title
            break
    if not file_title:
        return None

    img_params = {
        "action": "query", "titles": file_title, "prop": "imageinfo",
        "iiprop": "url", "iiurlwidth": 1024, "format": "json",
    }
    async with session.get(api_url, params=img_params) as resp:
        if resp.status != 200:
            return None
        img_data = await resp.json()

    pages = img_data.get("query", {}).get("pages", {})
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        url = infos[0].get("thumburl") or infos[0].get("url")
        if url:
            async with session.get(url) as img_resp:
                if img_resp.status == 200:
                    return await img_resp.read()
    return None


async def _search_article_pageimage(session: aiohttp.ClientSession, query: str) -> bytes | None:
    """Oddiy Wikipedia maqolasi qidiruvi + shu maqolaning asosiy rasmi (fallback)."""
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
        if thumb:
            async with session.get(thumb) as img_resp:
                if img_resp.status == 200:
                    return await img_resp.read()
    return None


async def search_logo_image(query: str) -> bytes | None:
    """Berilgan nom bo'yicha tayyor rasm qidiradi:
    1) Wikipedia File: nom fazosi (logolar uchun eng aniq)
    2) Wikimedia Commons File: nom fazosi (Wikipedia'da topilmasa)
    3) Wikipedia maqola-rasmi (shaxs/joy/umumiy holatlar uchun)
    Hech narsa topilmasa None - chaqiruvchi tomon AI generatsiyaga o'tadi."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            result = await _search_file_namespace(session, _WIKI_API, query)
            if result:
                return result

            result = await _search_file_namespace(session, _COMMONS_API, query)
            if result:
                return result

            return await _search_article_pageimage(session, query)
    except Exception as e:
        logger.warning(f"[image_search] qidiruvda xato ({query!r}): {e}")
        return None
