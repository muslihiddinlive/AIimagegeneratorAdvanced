"""
"Database" qatlami.

Ishlash printsipi:
- Butun bot holati (userlar, tariflar, kodlar, taqiqlangan so'zlar, adminlar,
  kanal sozlamalari, rasm keshi) bitta JSON obyekt sifatida RAMda saqlanadi (CACHE).
- Har bir o'zgarishdan SAVE_DEBOUNCE_SECONDS soniya o'tib (bir nechta o'zgarish
  ketma-ket kelsa - bittasiga birlashtirilib) shu JSON chiroyli HTML hisobot
  ichiga (jadval + embed JSON) o'raladi, `bot_state.html` fayli sifatida DB
  guruhiga yuboriladi va PIN qilinadi (DATABASE, doimiy saqlash).
- Bot qayta ishga tushganda guruhdagi pin qilingan xabardan HTML faylni o'qib,
  ichidagi JSON'ni ajratib olib cache'ni tiklaydi.

Limit tizimi TARIF asosida: har user "free"/"pro"/"plus"/"vip" tarifga ega,
har tarifning o'z kunlik limiti bor. Ustiga bonus-kanal orqali +2 doimiy bonus
qo'shilishi mumkin (bir marta, hammaga bir xil).
"""

import asyncio
import html as html_lib
import json
import io
import secrets
import string
from datetime import date, timedelta
from aiogram import Bot
from aiogram.types import BufferedInputFile

from config import (
    DB_GROUP_ID, STATE_FILENAME, SUPERADMIN_IDS, SAVE_DEBOUNCE_SECONDS,
    DEFAULT_TARIFFS, TARIFF_ORDER, TARIFF_LABELS, BANNED_WORDS, BONUS_LIMIT_AMOUNT,
    DEFAULT_CUSTOM_KNOWLEDGE,
)

UNLIMITED = 10 ** 9  # superadmin/admin uchun "cheksiz" limit ko'rsatkichi

_DEFAULT_STATE = {
    "users": {},            # str(user_id) -> user dict
    "admins": [],           # superadmin belgilagan qo'shimcha adminlar
    "tariffs": DEFAULT_TARIFFS,   # superadmin o'zgartira oladigan tarif sozlamalari
    "custom_knowledge": DEFAULT_CUSTOM_KNOWLEDGE,  # superadmin MD/matn orqali yuklaydigan "bot bilimi"
    "tariff_order": list(TARIFF_ORDER),   # superadmin YANGI tarif qo'shsa shu yerga qo'shiladi
    "tariff_labels": dict(TARIFF_LABELS),  # tarif nomi -> ko'rsatiladigan label (emoji bilan)
    "codes": {},             # code -> {"tariff", "days", "used", "used_by"}
    "api_keys": {},          # full_key -> {"name","daily_limit","used_today","last_reset",
                             #              "total_generated","created_at","expires_at","active"}
    "banned_words": list(BANNED_WORDS),  # to'liq runtime-tahrirlanadigan (add/remove) ro'yxat
    "image_cache": [],       # admin/superadmin DB ga tashlagan rasmlar: {file_id, by, at, caption}
    "mandatory_channel": None,  # username (@ siz), bo'lmasa None
    "bonus_channel": None,      # username (@ siz), bo'lmasa None
    "pinned_message_id": None,
}

_JSON_START = '<script type="application/json" id="state-json">'
_JSON_END = "</script>"


class Store:
    def __init__(self):
        self.data = json.loads(json.dumps(_DEFAULT_STATE))  # deep copy
        self._loaded = False
        self._save_task: asyncio.Task | None = None

    # ---------- persistence ----------

    async def load(self, bot: Bot):
        """Guruhdagi pin qilingan bot_state.html (yoki eski bot_state.json) faylini o'qib,
        cache'ni tiklaydi. Eski formatlardan yangisiga o'tishda ma'lumot yo'qolib
        ketmasligi uchun moslashtirib olamiz."""
        try:
            chat = await bot.get_chat(DB_GROUP_ID)
            pinned = chat.pinned_message
            if pinned and pinned.document and pinned.document.file_name in (STATE_FILENAME, "bot_state.json"):
                file = await bot.get_file(pinned.document.file_id)
                buf = io.BytesIO()
                await bot.download_file(file.file_path, destination=buf)
                buf.seek(0)
                raw = buf.read().decode("utf-8")

                if pinned.document.file_name == "bot_state.json":
                    loaded = json.loads(raw)
                else:
                    start = raw.index(_JSON_START) + len(_JSON_START)
                    end = raw.index(_JSON_END, start)
                    loaded = json.loads(raw[start:end])

                for k, v in _DEFAULT_STATE.items():
                    loaded.setdefault(k, json.loads(json.dumps(v)))

                for u in loaded.get("users", {}).values():
                    u.setdefault("images_generated", 0)
                    u.setdefault("generated_images", [])
                    u.setdefault("tariff", "free")
                    u.setdefault("tariff_until", None)
                    u.setdefault("ref_count", 0)
                    u.setdefault("referred_by", None)
                    u.setdefault("bonus_limit", 0)
                    u.setdefault("bonus_claimed", False)
                    u.setdefault("full_name", None)

                for c in loaded.get("codes", {}).values():
                    if "tariff" not in c:
                        c["tariff"] = "pro"
                    c.setdefault("days", None)

                # eski premium-emoji/reaksiya kalitlari endi ishlatilmaydi - shunchaki tashlab yuboramiz
                loaded.pop("custom_emojis", None)
                loaded.pop("reaction_admins", None)
                loaded.pop("reaction_emoji_id", None)

                if pinned.document.file_name == "bot_state.json":
                    loaded["pinned_message_id"] = None
                else:
                    loaded["pinned_message_id"] = pinned.message_id
                self.data = loaded
        except Exception as e:
            print(f"[state] load xatosi (birinchi ishga tushirish bo'lishi mumkin): {e}")
        self._loaded = True

    def schedule_save(self, bot: Bot):
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
        self._save_task = asyncio.create_task(self._debounced_save(bot))

    async def _debounced_save(self, bot: Bot):
        try:
            await asyncio.sleep(SAVE_DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            return
        try:
            await self.save(bot)
        except Exception as e:
            print(f"[state] debounced save xatosi: {e}")

    async def save(self, bot: Bot):
        payload = self._build_html()
        file = BufferedInputFile(payload, filename=STATE_FILENAME)

        msg_id = self.data.get("pinned_message_id")
        try:
            if msg_id:
                from aiogram.types import InputMediaDocument
                await bot.edit_message_media(
                    chat_id=DB_GROUP_ID,
                    message_id=msg_id,
                    media=InputMediaDocument(media=file, caption="🗄 bot_state.html (avto-yangilanadi)"),
                )
            else:
                raise ValueError("pinned_message_id yo'q")
        except Exception:
            sent = await bot.send_document(
                DB_GROUP_ID, file, caption="🗄 bot_state.html (avto-yangilanadi)"
            )
            self.data["pinned_message_id"] = sent.message_id
            try:
                await bot.pin_chat_message(DB_GROUP_ID, sent.message_id, disable_notification=True)
            except Exception as e:
                print(f"[state] pin qilishda xato: {e}")
            payload = self._build_html()
            try:
                from aiogram.types import InputMediaDocument
                await bot.edit_message_media(
                    chat_id=DB_GROUP_ID,
                    message_id=sent.message_id,
                    media=InputMediaDocument(
                        media=BufferedInputFile(payload, filename=STATE_FILENAME),
                        caption="🗄 bot_state.html (avto-yangilanadi)",
                    ),
                )
            except Exception as e:
                print(f"[state] ikkinchi yozishda xato: {e}")

    def _build_html(self) -> bytes:
        d = self.data
        users = d.get("users", {})

        def esc(v):
            return html_lib.escape(str(v)) if v is not None else "—"

        user_rows = []
        for uid, u in sorted(users.items(), key=lambda kv: -kv[1].get("images_generated", 0)):
            tag = " ⭐" if int(uid) in (set(SUPERADMIN_IDS) | set(d.get("admins", []))) else ""
            name = (f"@{u['username']}" if u.get("username") else u.get("full_name")) or "—"
            user_rows.append(
                "<tr>"
                f"<td>{esc(uid)}{tag}</td>"
                f"<td>{esc(name)}</td>"
                f"<td>{esc(u.get('first_seen', '—'))}</td>"
                f"<td>{esc(u.get('images_generated', 0))}</td>"
                f"<td>{esc(u.get('tariff', 'free'))}</td>"
                f"<td>{esc(u.get('tariff_until') or 'doimiy')}</td>"
                f"<td>{esc(u.get('bonus_limit', 0))}</td>"
                f"<td>{esc(u.get('ref_count', 0))}</td>"
                f"<td>{'🚫' if u.get('banned') else '—'}</td>"
                "</tr>"
            )
        users_table = "\n".join(user_rows) or "<tr><td colspan='9'>—</td></tr>"

        code_rows = []
        for code, c in d.get("codes", {}).items():
            code_rows.append(
                "<tr>"
                f"<td>{esc(code)}</td>"
                f"<td>{esc(c.get('tariff'))}</td>"
                f"<td>{esc(c.get('days') or 'doimiy')}</td>"
                f"<td>{'✅ ishlatilgan (' + esc(c.get('used_by')) + ')' if c.get('used') else '🟢 band emas'}</td>"
                "</tr>"
            )
        codes_table = "\n".join(code_rows) or "<tr><td colspan='4'>—</td></tr>"

        tariff_rows = []
        for name, t in d.get("tariffs", {}).items():
            tariff_rows.append(
                "<tr>"
                f"<td>{esc(name)}</td><td>{esc(t.get('daily_limit'))}</td>"
                f"<td>{esc(t.get('price_stars'))}</td><td>{esc(t.get('ref_required'))}</td>"
                f"<td>{esc(t.get('grantable_by'))}</td>"
                "</tr>"
            )
        tariffs_table = "\n".join(tariff_rows)

        admins = d.get("admins", [])
        admin_rows = "".join(f"<li>{esc(a)}</li>" for a in admins) or "<li>—</li>"
        cache = d.get("image_cache", [])
        words = d.get("banned_words", [])

        html_out = f"""<!DOCTYPE html>
<html lang="uz"><head><meta charset="utf-8"><title>Bot Database</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;background:#0f1115;color:#e6e6e6;padding:24px}}
h1{{color:#7dd3fc}} h2{{color:#7dd3fc;margin-top:36px}}
table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #2c2f36;padding:6px 10px;font-size:13px;text-align:left}}
th{{background:#1b1e25}}
tr:nth-child(even){{background:#151821}}
.meta{{color:#9aa4b2;font-size:13px}}
</style></head><body>
<h1>🗄 Bot Database</h1>
<p class="meta">Superadmin(lar): {esc(', '.join(str(i) for i in SUPERADMIN_IDS))} | Yangilangan: {esc(date.today())}</p>
<p class="meta">📢 Majburiy kanal: {esc(d.get('mandatory_channel') or '—')} | 🎁 Bonus kanal: {esc(d.get('bonus_channel') or '—')}</p>

<h2>💳 Tariflar</h2>
<table><tr><th>Nomi</th><th>Kunlik limit</th><th>Narx (stars)</th><th>Referal talabi</th><th>Kim beradi</th></tr>
{tariffs_table}
</table>

<h2>👥 Userlar ({len(users)} ta)</h2>
<table><tr><th>ID</th><th>Username</th><th>Qo'shilgan</th><th>Rasmlar</th><th>Tarif</th><th>Muddat</th><th>Bonus</th><th>Refs</th><th>Ban</th></tr>
{users_table}
</table>

<h2>🔑 Kodlar ({len(d.get('codes', {}))} ta)</h2>
<table><tr><th>Kod</th><th>Tarif</th><th>Kun</th><th>Holat</th></tr>
{codes_table}
</table>

<h2>🛠 Adminlar</h2>
<ul>{admin_rows}</ul>

<h2>🚫 Taqiqlangan so'zlar ({len(words)} ta)</h2>
<p class="meta">{esc(", ".join(words))}</p>

<h2>🖼 Rasm keshi ({len(cache)} ta)</h2>
<p class="meta">Adminlar tomonidan DB ga qo'lda tashlangan rasmlar soni.</p>

<script type="application/json" id="state-json">
{json.dumps(d, ensure_ascii=False)}
</script>
</body></html>"""
        return html_out.encode("utf-8")

    # ---------- ruxsatlar ----------

    def is_admin_user(self, user_id: int) -> bool:
        return user_id in SUPERADMIN_IDS or user_id in self.data.get("admins", [])

    def is_unlimited(self, user_id: int) -> bool:
        return self.is_admin_user(user_id)

    # ---------- user helpers ----------

    def get_user(self, user_id: int, username: str | None = None, full_name: str | None = None) -> dict:
        uid = str(user_id)
        if uid not in self.data["users"]:
            self.data["users"][uid] = {
                "id": user_id,
                "username": username,
                "full_name": full_name,
                "first_seen": str(date.today()),
                "tariff": "free",
                "tariff_until": None,   # None = muddatsiz; aks holda "YYYY-MM-DD"
                "used_today": 0,
                "last_reset": str(date.today()),
                "banned": False,
                "prompts": [],
                "images_generated": 0,
                "generated_images": [],
                "ref_count": 0,
                "referred_by": None,
                "bonus_limit": 0,
                "bonus_claimed": False,
            }
        else:
            u = self.data["users"][uid]
            if username:
                u["username"] = username
            if full_name:
                u["full_name"] = full_name
            u.setdefault("full_name", None)
            u.setdefault("images_generated", 0)
            u.setdefault("generated_images", [])
            u.setdefault("tariff", "free")
            u.setdefault("tariff_until", None)
            u.setdefault("ref_count", 0)
            u.setdefault("referred_by", None)
            u.setdefault("bonus_limit", 0)
            u.setdefault("bonus_claimed", False)
        return self.data["users"][uid]

    def display_name(self, uid: str) -> str:
        """Ko'rsatish uchun eng yaxshi mavjud ism: @username > full_name > ID."""
        u = self.data["users"].get(uid, {})
        if u.get("username"):
            return f"@{u['username']}"
        if u.get("full_name"):
            return u["full_name"]
        return f"id{uid}"

    def _reset_if_new_day(self, user: dict):
        today = str(date.today())
        if user["last_reset"] != today:
            user["last_reset"] = today
            user["used_today"] = 0
        if user.get("tariff_until") and user["tariff_until"] < today:
            user["tariff"] = "free"
            user["tariff_until"] = None

    def tariff_daily_limit(self, tariff_name: str) -> int:
        t = self.data.get("tariffs", {}).get(tariff_name)
        if not t:
            t = DEFAULT_TARIFFS.get(tariff_name, DEFAULT_TARIFFS["free"])
        return t["daily_limit"]

    # ---------- tariflar (dinamik: superadmin yangi tarif qo'sha oladi) ----------

    def tariff_order(self, include_hidden: bool = False) -> list[str]:
        """Ko'rsatish tartibidagi tarif nomlari ro'yxati. `include_hidden=False`
        bo'lsa, bir martalik "API key" kodlar uchun yaratilgan yashirin
        tariflar (masalan sotuvga chiqarilmagan maxsus limit-paketlar)
        ro'yxatga chiqmaydi."""
        order = self.data.get("tariff_order", list(TARIFF_ORDER))
        if include_hidden:
            return order
        tariffs = self.data.get("tariffs", {})
        return [name for name in order if not tariffs.get(name, {}).get("hidden")]

    def tariff_label(self, name: str) -> str:
        return self.data.get("tariff_labels", {}).get(name, name)

    def add_tariff(
        self, name: str, label: str, daily_limit: int, price_stars: int = 0,
        ref_required: int = 0, grantable_by: str = "superadmin", hidden: bool = False,
    ) -> bool:
        """Superadmin yangi tarif joriy etadi (yoki mavjud "API key" uchun
        yashirin bir martalik tarif yaratadi). `name` ichki kalit (masalan
        "gold" yoki "key_a1b2c3"), `label` foydalanuvchiga ko'rsatiladigan
        chiroyli nom (masalan "🥇 Gold" yoki admin bergan nom)."""
        tariffs = self.data.setdefault("tariffs", {})
        if name in tariffs:
            return False
        tariffs[name] = {
            "daily_limit": daily_limit,
            "price_stars": price_stars,
            "ref_required": ref_required,
            "grantable_by": grantable_by,
            "hidden": hidden,
        }
        self.data.setdefault("tariff_labels", {})[name] = label
        order = self.data.setdefault("tariff_order", list(TARIFF_ORDER))
        if name not in order:
            order.append(name)
        return True

    def delete_tariff(self, name: str) -> tuple[bool, str]:
        """Tarifni butunlay o'chiradi. "free" tarifi o'chirilmaydi (u -
        tizimning asosiy fallback tarifi). Shu tarifda turgan userlar
        avtomatik "free"ga o'tkaziladi."""
        if name == "free":
            return False, "free_protected"
        if name not in self.data.get("tariffs", {}):
            return False, "not_found"

        self.data["tariffs"].pop(name, None)
        self.data.get("tariff_labels", {}).pop(name, None)
        order = self.data.get("tariff_order", [])
        if name in order:
            order.remove(name)

        migrated = 0
        for u in self.data.get("users", {}).values():
            if u.get("tariff") == name:
                u["tariff"] = "free"
                u["tariff_until"] = None
                migrated += 1

        return True, f"{migrated}"

    # ---------- Tashqi API kalitlari (boshqalar o'z botiga ulab ishlatadi) ----------

    API_KEY_PREFIX = "RasmYaratuvchiRobot_"

    # Kuchli, keng alifbo: katta+kichik lotin harflar, raqamlar, xavfsiz
    # belgilar va vizual jihatdan lotin harflariga o'xshash kirill harflari
    # (masalan kirill "с" lotin "c"ga o'xshaydi) - bu brute-force/lug'at
    # hujumini deyarli imkonsiz qiladi va vizual "o'xshash harf" chalkashligi
    # orqali qo'lda taxmin qilishni ham qiyinlashtiradi.
    _LATIN = string.ascii_uppercase + string.ascii_lowercase
    _DIGITS = string.digits
    _SYMBOLS = "!@$^*-.~()₽"
    _CYRILLIC_LOOKALIKE = "аеорсухАЕОРСУХ"
    _API_KEY_SUFFIX_CHARS = _LATIN + _DIGITS + _SYMBOLS + _CYRILLIC_LOOKALIKE
    _API_KEY_SUFFIX_LEN = 14  # ~82^14 ehtimolli variant - amalda taxmin qilib bo'lmaydi

    def _random_api_suffix(self) -> str:
        return "".join(secrets.choice(self._API_KEY_SUFFIX_CHARS) for _ in range(self._API_KEY_SUFFIX_LEN))

    def generate_api_key(self, name: str, daily_limit: int, days: int = 0) -> str:
        """Tashqi dasturchiga beriladigan API kalit yaratadi. Format:
        RasmYaratuvchiRobot_XXXXXX (XXXXXX - 6 xonali harf+raqam, HAR DOIM
        unikal). `days=0` bo'lsa muddatsiz."""
        keys = self.data.setdefault("api_keys", {})
        while True:
            full_key = f"{self.API_KEY_PREFIX}{self._random_api_suffix()}"
            if full_key not in keys:
                break
        expires_at = str(date.today() + timedelta(days=days)) if days else None
        keys[full_key] = {
            "name": name,
            "daily_limit": daily_limit,
            "used_today": 0,
            "last_reset": str(date.today()),
            "total_generated": 0,
            "created_at": str(date.today()),
            "expires_at": expires_at,
            "active": True,
        }
        return full_key

    def get_api_key(self, full_key: str) -> dict | None:
        return self.data.get("api_keys", {}).get(full_key)

    def consume_api_key(self, full_key: str) -> tuple[bool, str, dict | None]:
        """API so'rov kelganda chaqiriladi: kalitni tekshiradi, kunlik
        hisobni kerak bo'lsa reset qiladi va limitdan bittasini ishlatadi.
        Qaytaradi: (muvaffaqiyat, sabab, kalit-ma'lumoti).
        sabab: "ok" | "invalid" | "revoked" | "expired" | "limit"."""
        info = self.data.get("api_keys", {}).get(full_key)
        if not info:
            return False, "invalid", None
        if not info.get("active", True):
            return False, "revoked", info
        if info.get("expires_at") and str(date.today()) > info["expires_at"]:
            return False, "expired", info

        today = str(date.today())
        if info["last_reset"] != today:
            info["last_reset"] = today
            info["used_today"] = 0

        if info["used_today"] >= info["daily_limit"]:
            return False, "limit", info

        info["used_today"] += 1
        info["total_generated"] = info.get("total_generated", 0) + 1
        return True, "ok", info

    def refund_api_key(self, full_key: str):
        """Generatsiya server xatosi bilan muvaffaqiyatsiz tugasa, ishlatilgan
        limitni qaytaradi - tashqi dasturchi o'zining aybi bilan bo'lmagan
        xato uchun limitidan yo'qotmasin."""
        info = self.data.get("api_keys", {}).get(full_key)
        if info and info["used_today"] > 0:
            info["used_today"] -= 1
            info["total_generated"] = max(0, info.get("total_generated", 1) - 1)

    def revoke_api_key(self, full_key: str) -> bool:
        info = self.data.get("api_keys", {}).get(full_key)
        if not info:
            return False
        info["active"] = False
        return True

    def list_api_keys(self) -> dict:
        return self.data.get("api_keys", {})

    # ---------- Bot "bilimi" (superadmin MD/matn orqali yuklaydi) ----------

    def get_custom_knowledge(self) -> str:
        return self.data.get("custom_knowledge", "")

    def set_custom_knowledge(self, text: str):
        self.data["custom_knowledge"] = text

    def find_api_key_by_suffix(self, suffix: str) -> str | None:
        """Callback_data'da to'liq keyni tashish shart emas (uzun bo'ladi),
        shuning uchun faqat 6 xonali suffiks orqali topamiz."""
        prefix = self.API_KEY_PREFIX
        full = f"{prefix}{suffix}"
        return full if full in self.data.get("api_keys", {}) else None

    def remaining_limit(self, user_id: int) -> int:
        if self.is_unlimited(user_id):
            return UNLIMITED
        user = self.get_user(user_id)
        self._reset_if_new_day(user)
        daily = self.tariff_daily_limit(user.get("tariff", "free")) + user.get("bonus_limit", 0)
        return max(0, daily - user["used_today"])

    def consume_limit(self, user_id: int, amount: int = 1):
        user = self.get_user(user_id)
        self._reset_if_new_day(user)
        user["used_today"] += amount

    def log_prompt(self, user_id: int, prompt: str, blocked: bool = False):
        user = self.get_user(user_id)
        user["prompts"].append({"prompt": prompt, "at": str(date.today()), "blocked": blocked})
        user["prompts"] = user["prompts"][-50:]

    def log_image(self, user_id: int, file_id: str, prompt: str):
        user = self.get_user(user_id)
        user["images_generated"] = user.get("images_generated", 0) + 1
        user.setdefault("generated_images", []).append(
            {"file_id": file_id, "prompt": prompt, "at": str(date.today())}
        )
        user["generated_images"] = user["generated_images"][-20:]

    def grant_tariff(self, user_id: int, tariff_name: str, days: int | None = None):
        """Superadmin/admin userga tarif beradi. days=None -> muddatsiz."""
        user = self.get_user(user_id)
        user["tariff"] = tariff_name
        user["tariff_until"] = str(date.today() + timedelta(days=days)) if days else None

    def set_banned(self, user_id: int, banned: bool):
        self.get_user(user_id)["banned"] = banned

    def all_banned_words(self) -> list:
        return list(self.data.get("banned_words", []))

    def top_users(self, n: int = 10) -> list[tuple[str, dict]]:
        users = self.data.get("users", {})
        ranked = sorted(users.items(), key=lambda kv: -kv[1].get("images_generated", 0))
        return [(uid, u) for uid, u in ranked if u.get("images_generated", 0) > 0][:n]

    # ---------- referal tizimi ----------

    def register_referral(self, referrer_id: int, new_user_id: int) -> tuple[bool, str | None]:
        if referrer_id == new_user_id:
            return False, None
        if str(referrer_id) not in self.data["users"]:
            return False, None
        new_user = self.get_user(new_user_id)
        if new_user.get("referred_by"):
            return False, None

        new_user["referred_by"] = referrer_id
        referrer = self.get_user(referrer_id)
        referrer["ref_count"] = referrer.get("ref_count", 0) + 1

        upgraded_to = None
        order = self.tariff_order(include_hidden=True)
        current_idx = order.index(referrer.get("tariff", "free")) if referrer.get("tariff", "free") in order else 0
        for name in reversed(order):
            req = self.data.get("tariffs", {}).get(name, {}).get("ref_required", 0)
            if req and referrer["ref_count"] >= req and order.index(name) > current_idx:
                referrer["tariff"] = name
                referrer["tariff_until"] = None
                upgraded_to = name
                break
        return True, upgraded_to

    # ---------- kanal tizimi ----------

    def set_mandatory_channel(self, username: str):
        self.data["mandatory_channel"] = username.lstrip("@").strip()

    def clear_mandatory_channel(self):
        self.data["mandatory_channel"] = None

    def set_bonus_channel(self, username: str):
        self.data["bonus_channel"] = username.lstrip("@").strip()

    def clear_bonus_channel(self):
        self.data["bonus_channel"] = None

    def claim_bonus(self, user_id: int) -> bool:
        """Bonus kanalga a'zo bo'lgani uchun +BONUS_LIMIT_AMOUNT bir martalik, doimiy bonus."""
        user = self.get_user(user_id)
        if user.get("bonus_claimed"):
            return False
        user["bonus_claimed"] = True
        user["bonus_limit"] = user.get("bonus_limit", 0) + BONUS_LIMIT_AMOUNT
        return True

    # ---------- taqiqlangan so'zlar (endi to'liq tahrirlanadigan) ----------

    def add_banned_word(self, word: str) -> bool:
        word = word.strip()
        if not word:
            return False
        words = self.data.setdefault("banned_words", [])
        if word in words:
            return False
        words.append(word)
        return True

    def remove_banned_word_at(self, index: int) -> str | None:
        words = self.data.get("banned_words", [])
        if 0 <= index < len(words):
            return words.pop(index)
        return None

    # ---------- rasm keshi ----------

    def add_image_cache(self, file_id: str, by: int, caption: str | None = None):
        self.data.setdefault("image_cache", []).append({
            "file_id": file_id, "by": by, "at": str(date.today()), "caption": caption or "",
        })
        self.data["image_cache"] = self.data["image_cache"][-500:]


store = Store()
