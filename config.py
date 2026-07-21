import os
import secrets
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_GROUP_ID = int(os.getenv("DB_GROUP_ID", "0"))


def _parse_id_list(raw: str) -> list[int]:
    """"123456789" yoki "123456789,987654321" kabi vergul bilan ajratilgan
    ID ro'yxatini xavfsiz tarzda int listga aylantiradi. Noto'g'ri
    yozilgan qism bo'lsa, o'sha qism tashlab yuboriladi (bot crash bo'lmaydi)."""
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            print(f"[config] SUPERADMIN_IDS ichida noto'g'ri qiymat e'tiborga olinmadi: {part!r}")
    return ids


# Bir nechta teng huquqli superadmin uchun: SUPERADMIN_IDS=123456789,987654321
# Eski SUPERADMIN_ID (bitta ID) hali ham ishlaydi - orqaga moslik uchun.
_raw_superadmin_ids = os.getenv("SUPERADMIN_IDS") or os.getenv("SUPERADMIN_ID", "0")
SUPERADMIN_IDS = _parse_id_list(_raw_superadmin_ids) or [0]

# Orqaga moslik: eski kod/loglarda bitta ID kutilgan joylar uchun (masalan
# ko'rsatish maqsadida) - har doim ro'yxatdagi birinchisini bildiradi.
SUPERADMIN_ID = SUPERADMIN_IDS[0]

# ============================
# WEBHOOK sozlamalari (Render uchun)
# ============================
# Render "Web Service" har bir deploy'da RENDER_EXTERNAL_URL degan
# environment variable'ni O'ZI avtomatik beradi (masalan
# https://sening-servising.onrender.com) - qo'lda kiritish shart emas.
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_HOST", ""))
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# Telegram har bir webhook so'roviga shu tokenni header'da qo'shib yuboradi -
# bu orqali so'rov chindan Telegramdan kelayotganini tekshiramiz.
# Render Environment Variables'ga o'zing tasodifiy uzun satr qo'yishing tavsiya
# qilinadi (masalan: openssl rand -hex 32); bo'lmasa har restart'da yangi
# tasodifiy qiymat generatsiya qilinadi (ishlayveradi, lekin beqaror).
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET") or secrets.token_urlsafe(32)

# Render "$PORT" environment variable orqali qaysi portni tinglash kerakligini beradi
PORT = int(os.getenv("PORT", "10000"))

# Har bir userga sutkalik standart limit (endi tariflar orqali - pastga qarang)
DEFAULT_DAILY_LIMIT = 2

# Tarif tizimi: kunlik limit, narx (Telegram Stars), qancha referal kerakligi va
# kim bera olishi. Superadmin bularni admin panel (inline tugmalar) orqali
# istagancha o'zgartira oladi (bazadagi nusxasi o'zgaradi, shu yerdagi qiymat - default).
DEFAULT_TARIFFS = {
    "free": {"daily_limit": 2, "price_stars": 0, "ref_required": 0, "grantable_by": "auto"},
    "pro":  {"daily_limit": 5, "price_stars": 15, "ref_required": 5, "grantable_by": "admin"},
    "plus": {"daily_limit": 10, "price_stars": 25, "ref_required": 15, "grantable_by": "superadmin"},
    "vip":  {"daily_limit": 20, "price_stars": 50, "ref_required": 0, "grantable_by": "superadmin"},
}
TARIFF_ORDER = ["free", "pro", "plus", "vip"]
TARIFF_LABELS = {"free": "🆓 Free", "pro": "⭐ Pro", "plus": "💎 Plus", "vip": "👑 VIP"}

# Bonus kanalga a'zo bo'lgan har bir userga bir martalik, doimiy +N limit
BONUS_LIMIT_AMOUNT = 2

# Guruhga pin qilinadigan "database" fayl nomi (HTML - ko'rinishi chiroyli,
# ichida esa qayta tiklash uchun JSON embed qilingan)
STATE_FILENAME = "bot_state.html"

# Har bir o'zgarishdan keyin nechchi soniyadan so'ng DB faylga yozilsin
# (bir nechta o'zgarish ketma-ket kelsa, bittasiga birlashtirib saqlaydi)
SAVE_DEBOUNCE_SECONDS = 2

# Taqiqlangan so'zlar (butun so'z sifatida tekshiriladi, substring emas).
# "am" kabi juda qisqa/keng tarqalgan so'zlar yolg'on signal berishi mumkin -
# xohlasang keyinchalik bu ro'yxatni kengaytirish/torayтirish kerak bo'ladi.
BANNED_WORDS = [
    "18+",
    "porn",
    "sex",
    "xxx",
    "am",
    "jinsiy aloqa",
    "jinsiy azo",
    "yalang'och",
    "yalangoch",
    "kiyimsiz",
]

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"

# ============================
# Groq preprocessing sozlamalari
# ============================
# Pollinations o'zbek tilini/imlo xatolarini yaxshi tushunmagani uchun,
# rasm generatsiyadan oldin prompt shu orqali tozalanadi va inglizchaga
# tarjima qilinadi (groq_preprocessor.py).
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Foydalanuvchi yuborishi mumkin bo'lgan xom promptning MAX belgi soni
PROMPT_MAX_INPUT_LEN = 500

# Groq qaytaradigan tayyor inglizcha promptning MAX belgi soni (strikt)
GROQ_OUTPUT_MAX_LEN = 300

# Groq so'rovlari orasidagi minimal interval (soniya) - llama-3.3-70b-versatile
# Free Tier TPM (6000 token/daqiqa) limitiga urilib qolmaslik uchun throttle.
GROQ_MIN_INTERVAL_SECONDS = float(os.getenv("GROQ_MIN_INTERVAL_SECONDS", "3.8"))

# 429/5xx/tarmoq xatolarida necha marta qayta urinilsin (exponential backoff)
GROQ_MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "4"))

# Bitta Groq so'roviga ajratilgan max kutish vaqti (soniya)
GROQ_REQUEST_TIMEOUT_SECONDS = float(os.getenv("GROQ_REQUEST_TIMEOUT_SECONDS", "20"))
