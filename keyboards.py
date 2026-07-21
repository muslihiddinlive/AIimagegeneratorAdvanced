from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)


def main_menu(bonus_available: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="🎨 Rasm yaratish"), KeyboardButton(text="📊 Limitim")],
        [KeyboardButton(text="🔑 Kod kiritish"), KeyboardButton(text="🏆 Reyting")],
        [KeyboardButton(text="💳 Tarif sotib olish"), KeyboardButton(text="🔗 Referal havolam")],
        [KeyboardButton(text="✉️ Adminga murojaat")],
    ]
    if bonus_available:
        keyboard.append([KeyboardButton(text="🎁 Bonus olish")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def admin_start_menu() -> InlineKeyboardMarkup:
    """Admin/superadmin /start bosganda - hammasi (oddiy user funksiyalari + admin panel) inline tugmalarda."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎨 Rasm yaratish", callback_data="ustart:generate")],
        [InlineKeyboardButton(text="📊 Limitim", callback_data="ustart:limit"),
         InlineKeyboardButton(text="🏆 Reyting", callback_data="ustart:rating")],
        [InlineKeyboardButton(text="🔑 Kod kiritish", callback_data="ustart:code"),
         InlineKeyboardButton(text="🔗 Referal havolam", callback_data="ustart:referral")],
        [InlineKeyboardButton(text="💳 Tarif sotib olish", callback_data="ustart:tariff"),
         InlineKeyboardButton(text="✉️ Adminga murojaat", callback_data="ustart:contact")],
        [InlineKeyboardButton(text="🎁 Bonus olish", callback_data="ustart:bonus")],
        [InlineKeyboardButton(text="🛠 Admin panel", callback_data="ustart:adminpanel")],
    ])


def admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admusers")],
        [InlineKeyboardButton(text="📢 Habar yuborish (broadcast)", callback_data="admbroadcast")],
        [InlineKeyboardButton(text="🔑 Tarif-kod yaratish", callback_data="admgencode")],
        [InlineKeyboardButton(text="💳 Tariflar sozlamasi", callback_data="admtariffs")],
        [InlineKeyboardButton(text="🚫 Taqiqlangan so'zlar", callback_data="admwords")],
        [InlineKeyboardButton(text="📡 Kanal sozlamalari", callback_data="admchannels")],
        [InlineKeyboardButton(text="🛠 Adminlar (superadmin)", callback_data="admmanageadmins")],
    ])


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admcancel")]
    ])


def users_list_kb(users: dict, page: int = 0, per_page: int = 15) -> InlineKeyboardMarkup:
    items = list(users.items())
    start = page * per_page
    chunk = items[start:start + per_page]
    rows = []
    for uid, u in chunk:
        name = u.get("username") and f"@{u['username']}" or u.get("full_name") or uid
        label = f"👤 {name} | 🖼{u.get('images_generated', 0)}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"admuser:{uid}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"admuserspage:{page - 1}"))
    if start + per_page < len(items):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"admuserspage:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="❌ Yopish", callback_data="admcancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_detail_kb(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎫 Tarif berish", callback_data=f"admgrantopen:{uid}")],
        [InlineKeyboardButton(text="🖼 Yaratgan rasmlari", callback_data=f"admimgs:{uid}")],
        [InlineKeyboardButton(text="✉️ Xabar yozish", callback_data=f"admmsguser:{uid}")],
        [InlineKeyboardButton(text="🚫 Ban/Unban", callback_data=f"admban:{uid}")],
        [InlineKeyboardButton(text="🔙 Ro'yxatga", callback_data="admusers")],
    ])


def tariff_choice_kb(callback_prefix: str, tariffs: list, uid: str = "") -> InlineKeyboardMarkup:
    from config import TARIFF_LABELS
    suffix = f":{uid}" if uid else ""
    rows = [
        [InlineKeyboardButton(text=TARIFF_LABELS.get(t, t), callback_data=f"{callback_prefix}:{t}{suffix}")]
        for t in tariffs
    ]
    rows.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admcancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def manage_admins_kb(admins: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="admaddadmin")]]
    rows += [[InlineKeyboardButton(text=f"❌ {a}", callback_data=f"admdeladmin:{a}")] for a in admins]
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admcancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tariff_purchase_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Pro so'rash", callback_data="tariffreq:pro")],
        [InlineKeyboardButton(text="💎 Plus so'rash", callback_data="tariffreq:plus")],
        [InlineKeyboardButton(text="👑 VIP so'rash", callback_data="tariffreq:vip")],
    ])


# ---------- Taqiqlangan so'zlar (to'liq inline boshqaruv) ----------

def words_kb(words: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="➕ So'z qo'shish", callback_data="wordadd")]]
    for i, w in enumerate(words):
        label = w if len(w) <= 20 else w[:20] + "…"
        rows.append([InlineKeyboardButton(text=f"❌ {label}", callback_data=f"worddel:{i}")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admcancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- Tariflar - inline tahrirlash ----------

def tariffs_kb(tariffs: dict) -> InlineKeyboardMarkup:
    from config import TARIFF_LABELS, TARIFF_ORDER
    rows = []
    for name in TARIFF_ORDER:
        t = tariffs.get(name, {})
        label = TARIFF_LABELS.get(name, name)
        rows.append([InlineKeyboardButton(
            text=f"✏️ {label}: {t.get('daily_limit')}/kun, {t.get('price_stars')}⭐, {t.get('ref_required')}ref",
            callback_data=f"tariffedit:{name}",
        )])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admcancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tariff_field_kb(name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Kunlik limit", callback_data=f"tariffeditfield:{name}:daily_limit")],
        [InlineKeyboardButton(text="⭐ Narx (stars)", callback_data=f"tariffeditfield:{name}:price_stars")],
        [InlineKeyboardButton(text="🔗 Referal talabi", callback_data=f"tariffeditfield:{name}:ref_required")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admtariffs")],
    ])


# ---------- Kanal sozlamalari ----------

def channels_kb(mandatory: str | None, bonus: str | None) -> InlineKeyboardMarkup:
    rows = []
    if mandatory:
        rows.append([InlineKeyboardButton(text=f"❌ Majburiy kanalni o'chirish (@{mandatory})", callback_data="chanclear:mandatory")])
    else:
        rows.append([InlineKeyboardButton(text="📢 Majburiy kanal o'rnatish", callback_data="chanset:mandatory")])
    if bonus:
        rows.append([InlineKeyboardButton(text=f"❌ Bonus kanalni o'chirish (@{bonus})", callback_data="chanclear:bonus")])
    else:
        rows.append([InlineKeyboardButton(text="🎁 Bonus kanal o'rnatish", callback_data="chanset:bonus")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admcancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mandatory_gate_kb(username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Kanalga o'tish", url=f"https://t.me/{username}")],
        [InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="checkmandatory")],
    ])


def bonus_gate_kb(username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Kanalga o'tish", url=f"https://t.me/{username}")],
        [InlineKeyboardButton(text="✅ Tekshirish", callback_data="checkbonus")],
    ])
