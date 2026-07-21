import re


def contains_banned(text: str, banned_words: list[str]) -> str | None:
    """
    Matnda taqiqlangan so'z/ibora bor-yo'qligini tekshiradi.
    Butun so'z/ibora sifatida (substring emas) tekshiradi, shunda masalan
    "Amerika" so'zidagi "am" ushlab qolinmaydi.
    Topilgan so'zni qaytaradi, topilmasa None.
    """
    lowered = text.lower()
    for word in banned_words:
        w = word.lower().strip()
        if not w:
            continue
        if " " in w:
            # ko'p so'zli ibora - to'g'ridan-to'g'ri substring qidiramiz
            if w in lowered:
                return word
        else:
            # bitta so'z - so'z chegarasi bilan tekshiramiz
            pattern = r"(?<![a-z0-9'’‘])" + re.escape(w) + r"(?![a-z0-9'’‘])"
            if re.search(pattern, lowered):
                return word
    return None
