from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import SUPERADMIN_ID, TARIFF_ORDER, TARIFF_LABELS
from state import store, UNLIMITED
from codes import generate_code
from keyboards import (
    admin_panel, cancel_kb, users_list_kb, user_detail_kb,
    tariff_choice_kb, manage_admins_kb, words_kb, tariffs_kb,
    tariff_field_kb, channels_kb,
)
from states import (
    GenCode, TariffGrant, TariffEdit, Broadcast, WordsManage,
    SendToUser, AdminAdd, ChannelSetup,
)

router = Router()


def is_admin(user_id: int) -> bool:
    return store.is_admin_user(user_id)


def is_superadmin(user_id: int) -> bool:
    """Faqat asosiy egasi - adminlarni tayinlash/olib tashlash va kanal sozlamalari shu darajaga tegishli."""
    return user_id == SUPERADMIN_ID


def allowed_grant_tariffs(caller_id: int) -> list[str]:
    if is_superadmin(caller_id):
        return TARIFF_ORDER
    if is_admin(caller_id):
        return [name for name in TARIFF_ORDER
                if store.data.get("tariffs", {}).get(name, {}).get("grantable_by") == "admin"]
    return []


def _fmt_limit(uid: int) -> str:
    left = store.remaining_limit(uid)
    return "♾ Cheksiz" if left >= UNLIMITED else str(left)


@router.callback_query(F.data == "admcancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🛠 Admin panel:", reply_markup=admin_panel())
    await call.answer()


# ---------- Userlar ro'yxati va kartochkasi ----------

@router.callback_query(F.data == "admusers")
async def cb_users(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    users = store.data["users"]
    if not users:
        await call.message.edit_text("Hozircha userlar yo'q.", reply_markup=cancel_kb())
        return await call.answer()
    await call.message.edit_text(
        f"👥 Userlar ({len(users)} ta). Batafsil ko'rish uchun bosing:",
        reply_markup=users_list_kb(users, page=0),
    )
    await call.answer()


@router.callback_query(F.data.startswith("admuserspage:"))
async def cb_users_page(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    page = int(call.data.split(":")[1])
    users = store.data["users"]
    await call.message.edit_text(
        f"👥 Userlar ({len(users)} ta). Batafsil ko'rish uchun bosing:",
        reply_markup=users_list_kb(users, page=page),
    )
    await call.answer()


async def _render_user_detail(call: CallbackQuery, uid: str):
    users = store.data["users"]
    u = users.get(uid)
    if not u:
        return await call.message.edit_text("Topilmadi.", reply_markup=cancel_kb())
    left = _fmt_limit(int(uid))
    tariff = u.get("tariff", "free")
    tariff_text = TARIFF_LABELS.get(tariff, tariff)
    tariff_text += f" ({u['tariff_until']} gacha)" if u.get("tariff_until") else " (doimiy)"
    ban_text = "ha" if u.get("banned") else "yo'q"
    display_name = (f"@{u['username']}" if u.get("username") else u.get("full_name")) or f"id{uid}"
    text = (
        f"👤 <b>{display_name}</b>\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"📅 Qo'shilgan: {u.get('first_seen', '—')}\n"
        f"🖼 Yaratgan rasmlar: {u.get('images_generated', 0)}\n"
        f"💳 Tarif: {tariff_text}\n"
        f"🎁 Bonus: {u.get('bonus_limit', 0)}\n"
        f"⏳ Hozir qolgan limit: {left}\n"
        f"🔗 Referallari: {u.get('ref_count', 0)} ta\n"
        f"🚫 Ban: {ban_text}"
    )
    await call.message.edit_text(text, reply_markup=user_detail_kb(uid))


@router.callback_query(F.data.startswith("admuser:"))
async def cb_user_detail(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    uid = call.data.split(":", 1)[1]
    await _render_user_detail(call, uid)
    await call.answer()


@router.callback_query(F.data.startswith("admban:"))
async def cb_toggle_ban(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        return await call.answer()
    uid = call.data.split(":", 1)[1]
    u = store.data["users"].get(uid)
    if not u:
        return await call.answer("Topilmadi.", show_alert=True)
    u["banned"] = not u.get("banned", False)
    store.schedule_save(bot)
    await _render_user_detail(call, uid)
    await call.answer("✅ Yangilandi.")


@router.callback_query(F.data.startswith("admimgs:"))
async def cb_user_images(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        return await call.answer()
    uid = call.data.split(":", 1)[1]
    u = store.data["users"].get(uid)
    if not u or not u.get("generated_images"):
        await call.answer("Bu user hali rasm yaratmagan.", show_alert=True)
        return
    await call.answer()
    for img in u["generated_images"][-6:]:
        try:
            await bot.send_photo(
                call.from_user.id, img["file_id"],
                caption=f"📝 {img['prompt'][:200]}\n🗓 {img['at']}",
            )
        except Exception as e:
            print(f"[admin] userimages yuborishda xato: {e}")


@router.callback_query(F.data.startswith("admmsguser:"))
async def cb_msg_user(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer()
    uid = call.data.split(":", 1)[1]
    await state.set_state(SendToUser.waiting_text)
    await state.update_data(target_uid=int(uid))
    await call.message.answer(f"✍️ [{uid}] ga yuboriladigan xabarni yozing:", reply_markup=cancel_kb())
    await call.answer()


@router.message(SendToUser.waiting_text)
async def do_msg_user(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    target = data.get("target_uid")
    try:
        await bot.send_message(target, f"📩 Admindan xabar:\n\n{message.text}")
        await message.answer("✅ Yuborildi.")
    except Exception as e:
        await message.answer(f"❌ Yuborib bo'lmadi: {e}")


# ---------- Tarif berish (userga, kodsiz) ----------

@router.callback_query(F.data.startswith("admgrantopen:"))
async def cb_grant_open(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    uid = call.data.split(":", 1)[1]
    allowed = allowed_grant_tariffs(call.from_user.id)
    if not allowed:
        return await call.answer("Sizga tarif berish huquqi berilmagan.", show_alert=True)
    await call.message.edit_text("Qaysi tarifni berasiz?", reply_markup=tariff_choice_kb("admgrant", allowed, uid))
    await call.answer()


@router.callback_query(F.data.startswith("admgrant:"))
async def cb_grant_tariff(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer()
    _, tariff, uid = call.data.split(":", 2)
    if tariff not in allowed_grant_tariffs(call.from_user.id):
        return await call.answer("Sizga bu tarifni berish huquqi yo'q.", show_alert=True)
    await state.set_state(TariffGrant.waiting_days)
    await state.update_data(target_uid=int(uid), tariff=tariff)
    await call.message.answer("Necha kunga beriladi? (0 = muddatsiz)", reply_markup=cancel_kb())
    await call.answer()


@router.message(TariffGrant.waiting_days)
async def tariff_grant_days(message: Message, state: FSMContext, bot: Bot):
    try:
        days = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Raqam kiriting (0 = muddatsiz).")
    data = await state.get_data()
    await state.clear()
    store.grant_tariff(data["target_uid"], data["tariff"], days if days > 0 else None)
    store.schedule_save(bot)
    label = TARIFF_LABELS.get(data["tariff"], data["tariff"])
    muddat = f"{days} kunga" if days > 0 else "muddatsiz"
    await message.answer(f"✅ User {data['target_uid']} ga {label} tarifi berildi ({muddat}).")
    try:
        await bot.send_message(data["target_uid"], f"🎁 Sizga {label} tarifi berildi ({muddat}).")
    except Exception:
        pass


# ---------- Broadcast ----------

@router.callback_query(F.data == "admbroadcast")
async def cb_broadcast(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer()
    await state.set_state(Broadcast.waiting_text)
    await call.message.answer("Barcha userlarga yuboriladigan xabar matnini kiriting:", reply_markup=cancel_kb())
    await call.answer()


@router.message(Broadcast.waiting_text)
async def do_broadcast(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    if not message.text:
        return await message.answer("❌ Matn yuboring.")
    sent, failed = 0, 0
    for uid in store.data["users"].keys():
        try:
            await bot.send_message(int(uid), message.text)
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"📢 Yuborildi: {sent} ta, xato: {failed} ta.")


# ---------- Tarif-kod yaratish ----------

@router.callback_query(F.data == "admgencode")
async def cb_gencode(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    allowed = allowed_grant_tariffs(call.from_user.id)
    if not allowed:
        return await call.answer("Sizga kod yaratish huquqi berilmagan.", show_alert=True)
    await call.message.edit_text("Kod qaysi tarifni bersin?", reply_markup=tariff_choice_kb("admgencodetariff", allowed))
    await call.answer()


@router.callback_query(F.data.startswith("admgencodetariff:"))
async def cb_gencode_tariff(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer()
    tariff = call.data.split(":", 1)[1]
    if tariff not in allowed_grant_tariffs(call.from_user.id):
        return await call.answer("Sizga bu tarifni berish huquqi yo'q.", show_alert=True)
    await state.set_state(GenCode.waiting_days)
    await state.update_data(tariff=tariff)
    await call.message.answer("Kod necha kunga amal qiladi? (0 = muddatsiz)", reply_markup=cancel_kb())
    await call.answer()


@router.message(GenCode.waiting_days)
async def gencode_days(message: Message, state: FSMContext, bot: Bot):
    try:
        days = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Raqam kiriting (0 = muddatsiz).")
    data = await state.get_data()
    await state.clear()
    code = generate_code()
    store.data["codes"][code] = {"tariff": data["tariff"], "days": days if days > 0 else None, "used": False}
    store.schedule_save(bot)
    label = TARIFF_LABELS.get(data["tariff"], data["tariff"])
    muddat = f"{days} kunga" if days > 0 else "muddatsiz"
    await message.answer(f"✅ Kod yaratildi:\n\n<code>{code}</code>\n\n{label} tarifi, {muddat}.")


# ---------- Tariflar sozlamasi (to'liq inline tahrirlash) ----------

@router.callback_query(F.data == "admtariffs")
async def cb_tariffs(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    await call.message.edit_text("💳 Tariflar (tahrirlash uchun bosing):", reply_markup=tariffs_kb(store.data["tariffs"]))
    await call.answer()


@router.callback_query(F.data.startswith("tariffedit:"))
async def cb_tariff_edit(call: CallbackQuery):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Faqat superadmin tarif sozlamalarini o'zgartira oladi.", show_alert=True)
    name = call.data.split(":", 1)[1]
    label = TARIFF_LABELS.get(name, name)
    await call.message.edit_text(f"{label} - qaysi qiymatni o'zgartiramiz?", reply_markup=tariff_field_kb(name))
    await call.answer()


@router.callback_query(F.data.startswith("tariffeditfield:"))
async def cb_tariff_edit_field(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Faqat superadmin.", show_alert=True)
    _, name, field = call.data.split(":", 2)
    await state.set_state(TariffEdit.waiting_value)
    await state.update_data(tariff=name, field=field)
    field_names = {"daily_limit": "kunlik limit", "price_stars": "narx (stars)", "ref_required": "referal talabi"}
    await call.message.answer(f"Yangi qiymat ({field_names.get(field, field)}):", reply_markup=cancel_kb())
    await call.answer()


@router.message(TariffEdit.waiting_value)
async def tariff_edit_value(message: Message, state: FSMContext, bot: Bot):
    try:
        value = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Raqam kiriting.")
    data = await state.get_data()
    await state.clear()
    store.data["tariffs"][data["tariff"]][data["field"]] = value
    store.schedule_save(bot)
    await message.answer(f"✅ {data['tariff']}.{data['field']} = {value}", reply_markup=tariffs_kb(store.data["tariffs"]))


# ---------- Taqiqlangan so'zlar (to'liq inline) ----------

@router.callback_query(F.data == "admwords")
async def cb_words(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    words = store.data.get("banned_words", [])
    await call.message.edit_text(
        f"🚫 Taqiqlangan so'zlar ({len(words)} ta). O'chirish uchun bosing:",
        reply_markup=words_kb(words),
    )
    await call.answer()


@router.callback_query(F.data == "wordadd")
async def cb_word_add(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer()
    await state.set_state(WordsManage.waiting_add)
    await call.message.answer("Qo'shiladigan so'zni yuboring:", reply_markup=cancel_kb())
    await call.answer()


@router.message(WordsManage.waiting_add)
async def word_add_value(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    if store.add_banned_word(message.text):
        store.schedule_save(bot)
        await message.answer(f"✅ Qo'shildi: {message.text.strip()}")
    else:
        await message.answer("Bu so'z allaqachon ro'yxatda bor yoki bo'sh.")
    words = store.data.get("banned_words", [])
    await message.answer(f"🚫 Taqiqlangan so'zlar ({len(words)} ta):", reply_markup=words_kb(words))


@router.callback_query(F.data.startswith("worddel:"))
async def cb_word_del(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        return await call.answer()
    index = int(call.data.split(":", 1)[1])
    removed = store.remove_banned_word_at(index)
    if removed:
        store.schedule_save(bot)
    words = store.data.get("banned_words", [])
    await call.message.edit_text(f"🚫 Taqiqlangan so'zlar ({len(words)} ta):", reply_markup=words_kb(words))
    await call.answer("✅ O'chirildi." if removed else "Topilmadi.")


# ---------- Kanal sozlamalari (faqat superadmin) ----------

@router.callback_query(F.data == "admchannels")
async def cb_channels(call: CallbackQuery):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Faqat superadmin uchun.", show_alert=True)
    d = store.data
    mandatory_text = f"@{d['mandatory_channel']}" if d.get("mandatory_channel") else "— (o'chirilgan)"
    bonus_text = f"@{d['bonus_channel']}" if d.get("bonus_channel") else "— (o'chirilgan)"
    text = (
        "📡 Kanal sozlamalari:\n\n"
        f"📢 Majburiy kanal: {mandatory_text}\n"
        f"🎁 Bonus kanal: {bonus_text}\n\n"
        "Majburiy kanalga a'zo bo'lmagan userlar rasm yarata olmaydi.\n"
        "Bonus kanalga a'zo bo'lgan har bir user bir martalik +2 doimiy limit oladi.\n\n"
        "⚠️ Bot shu kanallarda ADMIN bo'lishi shart (a'zolikni tekshirish uchun)."
    )
    await call.message.edit_text(text, reply_markup=channels_kb(d.get("mandatory_channel"), d.get("bonus_channel")))
    await call.answer()


@router.callback_query(F.data.startswith("chanset:"))
async def cb_chan_set(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Faqat superadmin uchun.", show_alert=True)
    kind = call.data.split(":", 1)[1]
    if kind == "mandatory":
        await state.set_state(ChannelSetup.waiting_mandatory)
    else:
        await state.set_state(ChannelSetup.waiting_bonus)
    await call.message.answer(
        "Kanal username'ini yuboring (masalan: @mychannel).\n"
        "⚠️ Kanal PUBLIC bo'lishi va bot unda ADMIN bo'lishi shart.",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(ChannelSetup.waiting_mandatory)
async def chan_set_mandatory(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    store.set_mandatory_channel(message.text)
    store.schedule_save(bot)
    await message.answer(f"✅ Majburiy kanal o'rnatildi: @{store.data['mandatory_channel']}")


@router.message(ChannelSetup.waiting_bonus)
async def chan_set_bonus(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    store.set_bonus_channel(message.text)
    store.schedule_save(bot)
    await message.answer(f"✅ Bonus kanal o'rnatildi: @{store.data['bonus_channel']}")


@router.callback_query(F.data.startswith("chanclear:"))
async def cb_chan_clear(call: CallbackQuery, bot: Bot):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Faqat superadmin uchun.", show_alert=True)
    kind = call.data.split(":", 1)[1]
    if kind == "mandatory":
        store.clear_mandatory_channel()
    else:
        store.clear_bonus_channel()
    store.schedule_save(bot)
    d = store.data
    await call.message.edit_text(
        "📡 Kanal sozlamalari yangilandi.",
        reply_markup=channels_kb(d.get("mandatory_channel"), d.get("bonus_channel")),
    )
    await call.answer("✅ O'chirildi.")


# ---------- Adminlarni boshqarish (faqat superadmin) ----------

@router.callback_query(F.data == "admmanageadmins")
async def cb_manage_admins(call: CallbackQuery):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Faqat superadmin uchun.", show_alert=True)
    admins = store.data.get("admins", [])
    await call.message.edit_text("🛠 Adminlar ro'yxati (bosilsa o'chiriladi):", reply_markup=manage_admins_kb(admins))
    await call.answer()


@router.callback_query(F.data == "admaddadmin")
async def cb_add_admin_open(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Faqat superadmin uchun.", show_alert=True)
    await state.set_state(AdminAdd.waiting_id)
    await call.message.answer("Yangi admin ID raqamini yuboring:", reply_markup=cancel_kb())
    await call.answer()


@router.message(AdminAdd.waiting_id)
async def add_admin_value(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    try:
        uid = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Raqam kiriting.")
    lst = store.data.setdefault("admins", [])
    if uid not in lst:
        lst.append(uid)
        store.schedule_save(bot)
    await message.answer(f"✅ Admin qo'shildi: {uid}. U endi superadmin qila oladigan hamma ishni qila oladi.")
    await message.answer("🛠 Adminlar ro'yxati:", reply_markup=manage_admins_kb(lst))


@router.callback_query(F.data.startswith("admdeladmin:"))
async def cb_del_admin_btn(call: CallbackQuery, bot: Bot):
    if not is_superadmin(call.from_user.id):
        return await call.answer("Faqat superadmin uchun.", show_alert=True)
    uid = int(call.data.split(":", 1)[1])
    lst = store.data.setdefault("admins", [])
    if uid in lst:
        lst.remove(uid)
        store.schedule_save(bot)
    await cb_manage_admins(call)


# ---------- Admin/superadmin DB ga rasm tashlaydi -> keshlanadi ----------

@router.message(F.photo)
async def cache_admin_photo(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    from config import DB_GROUP_ID
    photo = message.photo[-1]
    store.add_image_cache(photo.file_id, message.from_user.id, message.caption)
    store.schedule_save(bot)
    try:
        await bot.send_photo(
            DB_GROUP_ID, photo.file_id,
            caption=f"🖼 Admin keshi\n👤 {message.from_user.full_name} [id: {message.from_user.id}]\n"
                    f"📝 {message.caption or '—'}",
        )
    except Exception as e:
        print(f"[cache] DB ga yuborishda xato: {e}")
    await message.answer("✅ Rasm keshga saqlandi va DB guruhiga yuborildi.")
