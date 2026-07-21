import secrets
import string

ALPHABET = string.ascii_uppercase + string.digits


def generate_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(16))


def redeem(store_data: dict, code: str, user_id: int) -> tuple[bool, str, dict | None]:
    """
    Kodni tekshiradi va bir martalik ishlatadi (faqat validatsiya - effektni
    chaqiruvchi tomon store.grant_tariff() orqali qo'llaydi).
    Qaytaradi: (muvaffaqiyatli_mi, xabar, kod_yozuvi{tariff, days})
    """
    code = code.strip().upper()
    entry = store_data["codes"].get(code)
    if not entry:
        return False, "❌ Bunday kod topilmadi.", None
    if entry["used"]:
        return False, "❌ Bu kod allaqachon ishlatilgan.", None

    entry["used"] = True
    entry["used_by"] = user_id

    days_text = f"{entry['days']} kunga" if entry.get("days") else "muddatsiz"
    msg = f"✅ Kod qabul qilindi! Tarifingiz: {entry['tariff'].upper()} ({days_text})."
    return True, msg, entry
