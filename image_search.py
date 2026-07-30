"""
Ma'lum brend/logo/shaxs rasmlarini internetdan qidirish.

Uch bosqichli qidiruv (tezlik va aniqlik bo'yicha kamayish tartibida):
  1) Simple Icons (github.com/simple-icons/simple-icons) - ~3450 ta brend
     uchun RASMIY, aniq SVG logotiplar, MIT litsenziyali, fayl nomi orqali
     to'g'ridan-to'g'ri (qidiruv emas, ANIQ moslik) - eng tez va ishonchli,
     lekin har bir brend yo'q (masalan Amazon, Microsoft asosiy logotipi yo'q).
  2) Wikipedia "File:" nom fazosi - to'g'ridan-to'g'ri rasmiy logotip fayliga
     olib boradi (Simple Icons'da topilmagan brendlar uchun).
  3) Wikimedia Commons "File:" nom fazosi, so'ng Wikipedia maqola-rasmi -
     oxirgi zaxira (shaxs/joy/umumiy holatlar uchun).
"""
import logging
import re

import aiohttp

logger = logging.getLogger("image_search")

_WIKI_API = "https://en.wikipedia.org/w/api.php"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_SIMPLE_ICONS_BASE = "https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons"

_SUFFIX_WORDS = re.compile(
    r"\b(logo|logotype|logotip|icon|emblem|emblema|brend|brand|belgisi|nishoni|company|inc|corporation)\b",
    re.IGNORECASE,
)


def _slugify(name: str) -> str:
    """Simple Icons'ning fayl nomlash konvensiyasiga taxminiy moslashtirish:
    kichik harf, maxsus belgilarni olib tashlash/almashtirish, bo'shliqsiz."""
    name = _SUFFIX_WORDS.sub("", name).strip()
    name = name.lower()
    name = (
        name.replace("+", "plus").replace("#", "sharp").replace("&", "and")
        .replace(".", "").replace("'", "")
    )
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


async def _try_simple_icons(session: aiohttp.ClientSession, query: str) -> bytes | None:
    slug = _slugify(query)
    if not slug:
        return None
    svg_url = f"{_SIMPLE_ICONS_BASE}/{slug}.svg"
    # Telegram SVG'ni to'g'ridan-to'g'ri "photo" sifatida qabul qilmaydi, shuning
    # uchun bepul wsrv.nl proxy orqali PNG'ga aylantirib olamiz (o'zimizda hech
    # qanday cairo/tizim kutubxonasi kerak emas - Render'da ishlashi kafolatlanadi).
    proxy_url = f"https://wsrv.nl/?url={svg_url}&w=1024&h=1024&fit=contain&bg=white&output=png"
    try:
        async with session.get(proxy_url) as resp:
            if resp.status == 200 and "image" in resp.headers.get("content-type", ""):
                return await resp.read()
    except Exception as e:
        logger.warning(f"[image_search] Simple Icons/wsrv.nl xatosi ({slug!r}): {e}")
    return None


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
    1) Simple Icons (aniq, rasmiy, tezkor - ~3450 brend)
    2) Wikipedia File: nom fazosi (Simple Icons'da yo'q brendlar uchun)
    3) Wikimedia Commons File: nom fazosi
    4) Wikipedia maqola-rasmi (shaxs/joy/umumiy holatlar uchun)
    Hech narsa topilmasa None - chaqiruvchi tomon AI generatsiyaga o'tadi."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            result = await _try_simple_icons(session, query)
            if result:
                logger.info(f"[image_search] Simple Icons'da topildi: {query!r}")
                return result

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
