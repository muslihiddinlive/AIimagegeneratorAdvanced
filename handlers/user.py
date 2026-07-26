from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message, BufferedInputFile, CallbackQuery, ReplyKeyboardRemove,
    PreCheckoutQuery, LabeledPrice,
)
from aiogram.fsm.context import FSMContext

from config import DB_GROUP_ID, SUPERADMIN_IDS, STARS_CURRENCY
from state import store, UNLIMITED
from moderation import contains_banned
from pollinations import generate_image
from stable_horde import generate_image as stable_horde_generate
from image_search import search_logo_image
from text_overlay import add_text_overlay
from groq_preprocessor import (
    optimize_prompt,
    understand_and_route,
    validate_prompt_length,
    build_length_error_message,
    PromptTooLongError,
)
from codes import redeem
from keyboards import (
    main_menu, tariff_purchase_kb, admin_start_menu, admin_panel,
    mandatory_gate_kb, bonus_gate_kb,
)
from states import RequestTariff, UserContact
from queue_worker import gen_queue

router = Router()

_bot_username_cache = {"value": None}


async def _get_bot_username(bot: Bot) -> str:
    if not _bot_username_cache["value"]:
        me = await bot.get_me()
        _bot_username_cache["value"] = me.username
    return _bot_username_cache["value"]


def _left_text(user_id: int) -> str:
    left = store.remaining_limit(user_id)
    return "♾ Cheksiz" if left >= UNLIMITED else str(left)


async def _is_channel_member(bot: Bot, username: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(f"@{username}", user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        print(f"[channel] a'zolikni tekshirishda xato (@{username}, {user_id}): {e}")
        return False


async def _check_mandatory(message: Message, bot: Bot) -> bool:
    """True qaytsa - davom etsa bo'ladi. False bo'lsa, allaqachon foydalanuvchiga xabar yuborilgan."""
    mandatory = store.data.get("mandatory_channel")
    if not mandatory:
        return True
    if store.is_admin_user(message.from_user.id):
        return True
    if await _is_channel_member(bot, mandatory, message.from_user.id):
        return True
    await message.answer(
        f"📢 Botdan foydalanish uchun avval kanalga a'zo bo'ling:\n@{mandatory}\n\n"
        f"A'zo bo'lgach, tugmani bosing:",
        reply_markup=mandatory_gate_kb(mandatory),
    )
    return False


async def _generate_job(message: Message, bot: Bot, prompt: str, user_id: int, status: Message, route):
    img_bytes = None
    source = "generated"

    # overlay_text bo'lsa - bu maxsus banner/nom talab qiladi, tayyor rasm
    # qidirish mantiqsiz (o'sha aniq matn internetda tayyor holda bo'lmaydi).
    if route.is_known_subject and route.search_query and not route.overlay_text:
        try:
            await status.edit_text(f"🔎 \"{route.search_query}\" internetdan qidirilmoqda...")
        except Exception:
            pass
        img_bytes = await search_logo_image(route.search_query)
        if img_bytes:
            source = "search"

    if img_bytes is None:
        try:
            await status.edit_text("⏳ Rasm tayyorlanmoqda (biroz vaqt olishi mumkin)...")
        except Exception:
            pass
        try:
            img_bytes = await stable_horde_generate(route.image_prompt)
            source = "stable_horde"
        except Exception as e:
            print(f"[generate] Stable Horde xatosi, Pollinations'ga o'tamiz: {type(e).__name__}: {e}")
            try:
                img_bytes = await generate_image(route.image_prompt)
                source = "pollinations"
            except Exception as e2:
                print(f"[generate] Pollinations ham ishlamadi (prompt={route.image_prompt!r}): {type(e2).__name__}: {e2}")
                try:
                    await status.edit_text("❌ Xatolik yuz berdi. Birozdan so'ng qaytadan urinib ko'ring.")
                except Exception:
                    pass
                return

    if route.overlay_text:
        # AI matnni deyarli hech qachon to'g'ri chizolmaydi - shuning uchun
        # fon AI'da tayyorlanadi, aniq matn esa shu yerda dasturiy chiziladi.
        img_bytes = add_text_overlay(img_bytes, route.overlay_text)
        source += "+overlay"

    store.consume_limit(user_id, 1)
    store.log_prompt(user_id, prompt, blocked=False)

    caption_prefix = "🔎 Internetdan topilgan tayyor rasm!" if source == "search" else "✅ Tayyor!"
    photo = BufferedInputFile(img_bytes, filename="result.png")
    sent_photo = await message.answer_photo(
        photo, caption=f"{caption_prefix}\nQolgan limit: {_left_text(user_id)}"
    )
    try:
        await status.delete()
    except Exception:
        pass

    if sent_photo.photo:
        store.log_image(user_id, sent_photo.photo[-1].file_id, prompt)
    store.schedule_save(bot)

    try:
        await bot.send_photo(
            DB_GROUP_ID,
            BufferedInputFile(img_bytes, filename="log.png"),
            caption=(
                f"🖼 Yangi generatsiya ({source})\n"
                f"👤 {message.from_user.full_name} (@{message.from_user.username or '—'}) [id: {user_id}]\n"
                f"📝 Prompt: {prompt}"
            ),
        )
    except Exception as e:
        print(f"[log] guruhga yuborishda xato: {e}")


async def _do_generate(message: Message, bot: Bot, prompt: str):
    user = message.from_user

    try:
        validate_prompt_length(prompt)
    except PromptTooLongError as e:
        await message.answer(build_length_error_message(e))
        return

    u = store.get_user(user.id, user.username, user.full_name)

    if u.get("banned"):
        await message.answer("🚫 Siz botdan foydalanishdan taqiqlangansiz.")
        return

    if not await _check_mandatory(message, bot):
        return

    try:
        await bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    # Groq: bu chat xabarimi yoki rasm so'roviмi - va agar rasm bo'lsa, bu
    # ma'lum brend/logo bo'lib, avval internetdan qidirish kerakmi - shularni
    # aniqlaydi. Groq ishlamasa ham, ichida xavfsiz fallback bor (rasm deb
    # hisoblanadi), bot hech qachon shu yerda to'xtab qolmaydi.
    route = await understand_and_route(prompt, store.get_custom_knowledge())

    if route.type == "chat":
        await message.answer(route.chat_reply)
        return

    remaining = store.remaining_limit(user.id)
    if remaining <= 0:
        await message.answer(
            "🚫 Sutkalik limitingiz tugagan.\n"
            "Ko'proq limit kerak bo'lsa \"💳 Tarif sotib olish\" tugmasidan foydalaning."
        )
        return

    banned = contains_banned(prompt, store.all_banned_words())
    if banned:
        store.consume_limit(user.id, 1)
        store.log_prompt(user.id, prompt, blocked=True)
        store.schedule_save(bot)
        await message.answer(
            "⛔️ So'rovingiz axloqiy qoidalarga zid so'z/ibora tutgani uchun rad etildi.\n"
            "Limitingizdan 1 ta ayirildi."
        )
        return

    position = gen_queue.peek_position()
    if position > 0:
        status = await message.answer(f"⏳ Navbatga qo'shildingiz. Sizdan oldin {position} ta so'rov bor.")
    else:
        status = await message.answer("⏳ Boshlanmoqda...")

    async def job():
        await _generate_job(message, bot, prompt, user.id, status, route)

    await gen_queue.enqueue(job)


async def _generate_job_api(message: Message, bot: Bot, prompt: str, key: str, status: Message):
    try:
        await status.edit_text("🧠 Prompt optimallashtirilmoqda...")
    except Exception:
        pass

    optimized_prompt = await optimize_prompt(prompt)

    try:
        await status.edit_text("⏳ Rasm tayyorlanmoqda, biroz kuting...")
    except Exception:
        pass

    try:
        img_bytes = await generate_image(optimized_prompt)
    except Exception as e:
        print(f"[genapi] Pollinations xatosi (prompt={optimized_prompt!r}): {type(e).__name__}: {e}")
        store.refund_api_key(key)  # bizning xatomiz uchun limitni qaytaramiz
        try:
            await status.edit_text("❌ Xatolik yuz berdi. Birozdan so'ng qaytadan urinib ko'ring.")
        except Exception:
            pass
        return

    info = store.get_api_key(key) or {}
    remaining = info.get("daily_limit", 0) - info.get("used_today", 0)

    photo = BufferedInputFile(img_bytes, filename="result.png")
    await message.reply_photo(
        photo, caption=f"✅ Tayyor!\n🔑 {info.get('name', key)}\n📊 Bugungi qolgan limit: {remaining}/{info.get('daily_limit', 0)}"
    )
    try:
        await status.delete()
    except Exception:
        pass
    store.schedule_save(bot)

    try:
        await bot.send_photo(
            DB_GROUP_ID,
            BufferedInputFile(img_bytes, filename="api_log.png"),
            caption=(
                f"🔌 API orqali generatsiya\n"
                f"🏷 Key nomi: {info.get('name', '—')}\n"
                f"🔑 <code>{key}</code>\n"
                f"📊 Qolgan limit: {remaining}/{info.get('daily_limit', 0)}\n"
                f"📝 Prompt: {prompt}"
            ),
        )
    except Exception as e:
        print(f"[genapi log] guruhga yuborishda xato: {e}")


@router.message(Command("genapi"))
async def cmd_genapi(message: Message, bot: Bot, command: CommandObject):
    """Tashqi dasturchilar uchun - Telegram ICHIDA ishlaydigan API. Hech qanday
    HTTP domen/URL ochilmaydi - so'rov to'g'ridan-to'g'ri shu botga (DM yoki
    bot qo'shilgan guruhga /genapi@BotUsername orqali) keladi, javob ham shu
    yerning o'zida (rasm) qaytadi. API key'siz umuman ishlamaydi."""
    args = command.args
    if not args or len(args.split(maxsplit=1)) < 2:
        await message.reply(
            "🔌 Foydalanish:\n<code>/genapi &lt;key&gt; &lt;prompt&gt;</code>\n\n"
            "Masalan:\n<code>/genapi RasmYaratuvchiRobot_ab12cd chiroyli gul, kunbotar fon</code>"
        )
        return

    key, prompt = args.split(maxsplit=1)
    key = key.strip()
    prompt = prompt.strip()

    try:
        validate_prompt_length(prompt)
    except PromptTooLongError as e:
        await message.reply(build_length_error_message(e))
        return

    ok, reason, info = store.consume_api_key(key)
    if not ok:
        texts = {
            "invalid": "❌ API key noto'g'ri yoki topilmadi.",
            "revoked": "🚫 Bu API key bekor qilingan.",
            "expired": "⌛️ Bu API keyning muddati tugagan.",
            "limit": f"🚫 Kunlik limit tugagan ({info['used_today']}/{info['daily_limit']}). Ertaga yangilanadi.",
        }
        await message.reply(texts.get(reason, "❌ Xatolik yuz berdi."))
        return

    position = gen_queue.peek_position()
    if position > 0:
        status = await message.reply(f"⏳ Navbatga qo'shildi. Sizdan oldin {position} ta so'rov bor.")
    else:
        status = await message.reply("⏳ Rasm tayyorlanmoqda, biroz kuting...")

    async def job():
        await _generate_job_api(message, bot, prompt, key, status)

    await gen_queue.enqueue(job)


@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot, state: FSMContext, command: CommandObject):
    await state.clear()
    is_new = str(message.from_user.id) not in store.data["users"]
    store.get_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    if is_new and command.args and command.args.startswith("ref"):
        try:
            referrer_id = int(command.args[3:])
            ok, upgraded = store.register_referral(referrer_id, message.from_user.id)
            if ok and upgraded:
                label = store.tariff_label(upgraded)
                try:
                    await bot.send_message(
                        referrer_id,
                        f"🎉 Tabriklaymiz! Siz yetarlicha referal keltirdingiz va avtomatik {label} tarifiga o'tkazildingiz!",
                    )
                except Exception:
                    pass
        except ValueError:
            pass

    store.schedule_save(bot)

    if store.is_admin_user(message.from_user.id):
        await message.answer("👋 Xush kelibsiz, Admin!", reply_markup=ReplyKeyboardRemove())
        await message.answer("📋 Barcha funksiyalar:", reply_markup=admin_start_menu())
        return

    bonus_available = bool(store.data.get("bonus_channel")) and not store.get_user(message.from_user.id).get("bonus_claimed")
    await message.answer(
        "👋 Xush kelibsiz!\n\n"
        "🎨 Rasm yaratish uchun pastdagi tugmadan foydalaning yoki to'g'ridan-to'g'ri prompt yozing.\n"
        "Har kuni bepul limitingiz bor.",
        reply_markup=main_menu(bonus_available),
    )


@router.message(F.text == "🎨 Rasm yaratish")
async def btn_generate(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Qanday rasm yaratay? Promptni yozib yuboring (masalan: sunset over mountains).")


@router.message(F.text == "📊 Limitim")
async def btn_limit(message: Message, state: FSMContext):
    await state.clear()
    u = store.get_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    tariff = store.tariff_label(u.get("tariff", "free"))
    await message.answer(f"💳 Tarifingiz: {tariff}\n📊 Bugun {_left_text(message.from_user.id)} ta rasm yaratish imkoniyati qoldi.")


@router.message(F.text == "🔑 Kod kiritish")
async def btn_code(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("16 xonali kodni yuboring:")


@router.message(F.text == "🏆 Reyting")
async def btn_rating(message: Message, state: FSMContext):
    await state.clear()
    top = store.top_users(10)
    if not top:
        await message.answer("Hozircha reyting bo'sh — birinchi bo'lib rasm yarating! 🎨")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 Top 10 (eng ko'p rasm yaratganlar):\n"]
    for i, (uid, u) in enumerate(top):
        rank = medals[i] if i < 3 else f"{i + 1}."
        name = u.get("username") or f"id{uid}"
        lines.append(f"{rank} @{name} — {u.get('images_generated', 0)} ta rasm")
    await message.answer("\n".join(lines))


@router.message(F.text == "🔗 Referal havolam")
async def btn_referral(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    u = store.get_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    username = await _get_bot_username(bot)
    link = f"https://t.me/{username}?start=ref{message.from_user.id}"
    pro_req = store.data["tariffs"]["pro"]["ref_required"]
    plus_req = store.data["tariffs"]["plus"]["ref_required"]
    await message.answer(
        f"🔗 Sizning referal havolangiz:\n{link}\n\n"
        f"👥 Hozirgi referallaringiz: {u.get('ref_count', 0)} ta\n\n"
        f"{pro_req} ta referal → ⭐ Pro tarifi avtomatik beriladi\n"
        f"{plus_req} ta referal → 💎 Plus tarifi avtomatik beriladi"
    )


@router.message(F.text == "🎁 Bonus olish")
async def btn_bonus(message: Message, state: FSMContext):
    await state.clear()
    bonus = store.data.get("bonus_channel")
    if not bonus:
        await message.answer("Hozircha bonus kanal o'rnatilmagan.")
        return
    u = store.get_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if u.get("bonus_claimed"):
        await message.answer("✅ Siz bonusni allaqachon olgansiz.")
        return
    await message.answer(
        f"🎁 Kanalga a'zo bo'lsangiz +2 ta doimiy limit olasiz:\n@{bonus}",
        reply_markup=bonus_gate_kb(bonus),
    )


@router.callback_query(F.data == "checkbonus")
async def cb_check_bonus(call: CallbackQuery, bot: Bot):
    bonus = store.data.get("bonus_channel")
    if not bonus:
        return await call.answer("Bonus kanal o'rnatilmagan.", show_alert=True)
    u = store.get_user(call.from_user.id, call.from_user.username, call.from_user.full_name)
    if u.get("bonus_claimed"):
        await call.answer("✅ Siz bonusni allaqachon olgansiz.", show_alert=True)
        return
    if not await _is_channel_member(bot, bonus, call.from_user.id):
        await call.answer("❌ Siz hali kanalga a'zo emassiz.", show_alert=True)
        return
    store.claim_bonus(call.from_user.id)
    store.schedule_save(bot)
    await call.message.edit_text("✅ Tabriklaymiz! +2 ta doimiy limit qo'shildi.")
    await call.answer()


@router.callback_query(F.data == "closemsg")
async def cb_close_msg(call: CallbackQuery):
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data == "checkmandatory")
async def cb_check_mandatory(call: CallbackQuery, bot: Bot):
    mandatory = store.data.get("mandatory_channel")
    if not mandatory:
        await call.message.edit_text("✅ Endi botdan foydalanishingiz mumkin.")
        return await call.answer()
    if await _is_channel_member(bot, mandatory, call.from_user.id):
        await call.message.edit_text("✅ Obuna tasdiqlandi! Endi rasm so'rovingizni yuboring.")
    else:
        await call.answer("❌ Siz hali kanalga a'zo emassiz.", show_alert=True)
        return
    await call.answer()


@router.message(F.text == "✉️ Adminga murojaat")
async def btn_admin_contact(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(UserContact.waiting_message)
    await message.answer("✍️ Adminga qanday xabar/muammo yozmoqchisiz?")


@router.message(UserContact.waiting_message)
async def admin_contact_message(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    text = (
        f"📨 Yangi murojaat!\n"
        f"👤 {user.full_name} (@{user.username or '—'}) [id: {user.id}]\n"
        f"✍️ Xabar: {message.text}"
    )
    sent_to_any = False
    for admin_id in SUPERADMIN_IDS + store.data.get("admins", []):
        try:
            await bot.send_message(admin_id, text)
            sent_to_any = True
        except Exception:
            pass
    if sent_to_any:
        await message.answer("✅ Murojaatingiz adminga yuborildi.")
    else:
        await message.answer("❌ Hozircha yuborib bo'lmadi, keyinroq urinib ko'ring.")


# ---------- Admin/superadmin uchun: /start dagi inline menyu ----------

@router.callback_query(F.data.startswith("ustart:"))
async def cb_ustart(call: CallbackQuery, state: FSMContext, bot: Bot):
    action = call.data.split(":", 1)[1]
    await state.clear()

    if action == "generate":
        await call.message.answer("Qanday rasm yaratay? Promptni yozib yuboring (masalan: sunset over mountains).")

    elif action == "limit":
        u = store.get_user(call.from_user.id, call.from_user.username, call.from_user.full_name)
        tariff = store.tariff_label(u.get("tariff", "free"))
        await call.message.answer(f"💳 Tarifingiz: {tariff}\n📊 Bugun {_left_text(call.from_user.id)} ta rasm yaratish imkoniyati qoldi.")

    elif action == "code":
        await call.message.answer("16 xonali kodni yuboring:")

    elif action == "rating":
        top = store.top_users(10)
        if not top:
            await call.message.answer("Hozircha reyting bo'sh — birinchi bo'lib rasm yarating! 🎨")
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines = ["🏆 Top 10 (eng ko'p rasm yaratganlar):\n"]
            for i, (uid, u) in enumerate(top):
                rank = medals[i] if i < 3 else f"{i + 1}."
                name = u.get("username") or f"id{uid}"
                lines.append(f"{rank} @{name} — {u.get('images_generated', 0)} ta rasm")
            await call.message.answer("\n".join(lines))

    elif action == "referral":
        u = store.get_user(call.from_user.id, call.from_user.username, call.from_user.full_name)
        username = await _get_bot_username(bot)
        link = f"https://t.me/{username}?start=ref{call.from_user.id}"
        pro_req = store.data["tariffs"]["pro"]["ref_required"]
        plus_req = store.data["tariffs"]["plus"]["ref_required"]
        await call.message.answer(
            f"🔗 Sizning referal havolangiz:\n{link}\n\n"
            f"👥 Hozirgi referallaringiz: {u.get('ref_count', 0)} ta\n\n"
            f"{pro_req} ta referal → ⭐ Pro tarifi avtomatik beriladi\n"
            f"{plus_req} ta referal → 💎 Plus tarifi avtomatik beriladi"
        )

    elif action == "tariff":
        t = store.data["tariffs"]
        lines = ["💳 Mavjud tariflar:\n"]
        for name in store.tariff_order():
            if name == "free":
                continue
            info = t[name]
            label = store.tariff_label(name)
            lines.append(
                f"{label}: kuniga {info['daily_limit']} ta rasm — {info['price_stars']} ⭐/oy "
                f"yoki {info['ref_required']} ta referal"
            )
        lines.append("\nTanlang, admin bilan bog'lanamiz:")
        await call.message.answer("\n".join(lines), reply_markup=tariff_purchase_kb())

    elif action == "contact":
        await state.set_state(UserContact.waiting_message)
        await call.message.answer("✍️ Adminga qanday xabar/muammo yozmoqchisiz?")

    elif action == "bonus":
        bonus = store.data.get("bonus_channel")
        if not bonus:
            await call.message.answer("Hozircha bonus kanal o'rnatilmagan.")
        else:
            u = store.get_user(call.from_user.id, call.from_user.username, call.from_user.full_name)
            if u.get("bonus_claimed"):
                await call.message.answer("✅ Siz bonusni allaqachon olgansiz.")
            else:
                await call.message.answer(
                    f"🎁 Kanalga a'zo bo'lsangiz +2 ta doimiy limit olasiz:\n@{bonus}",
                    reply_markup=bonus_gate_kb(bonus),
                )

    elif action == "adminpanel":
        if not store.is_admin_user(call.from_user.id):
            await call.answer("🚫 Ruxsat yo'q.", show_alert=True)
            return
        await call.message.answer("🛠 Admin panel:", reply_markup=admin_panel())

    await call.answer()


@router.callback_query(F.data.startswith("tariffreq:"))
async def cb_tariff_request(call: CallbackQuery, bot: Bot):
    tariff = call.data.split(":", 1)[1]
    label = store.tariff_label(tariff)
    info = store.data["tariffs"].get(tariff, {})
    user = call.from_user
    text = (
        f"💳 Yangi tarif so'rovi!\n"
        f"👤 {user.full_name} (@{user.username or '—'}) [id: {user.id}]\n"
        f"🎫 So'ralgan tarif: {label} ({info.get('price_stars')} ⭐/oy yoki {info.get('ref_required')} referal)"
    )
    sent_to_any = False
    for admin_id in SUPERADMIN_IDS + store.data.get("admins", []):
        try:
            await bot.send_message(admin_id, text)
            sent_to_any = True
        except Exception:
            pass
    if sent_to_any:
        await call.message.answer(f"✅ {label} tarifi uchun so'rovingiz adminga yuborildi. Tez orada bog'lanishadi.")
    else:
        await call.message.answer("❌ Hozircha yuborib bo'lmadi, keyinroq urinib ko'ring.")
    await call.answer()


@router.callback_query(F.data.startswith("tariffbuy:"))
async def cb_tariff_buy(call: CallbackQuery, bot: Bot):
    """Telegram Stars orqali haqiqiy to'lov: invoice yuboriladi, foydalanuvchi
    to'lasa Telegram o'zi Stars'ni botni ro'yxatdan o'tkazgan akkauntning
    balansiga o'tkazadi (bu bot kodi ichidan boshqarilmaydigan, Telegram
    platforma darajasidagi jarayon)."""
    tariff = call.data.split(":", 1)[1]
    info = store.data["tariffs"].get(tariff)
    if not info or info.get("price_stars", 0) <= 0:
        await call.answer("Bu tarif Stars orqali sotib olinmaydi.", show_alert=True)
        return
    label = store.tariff_label(tariff)
    price = info["price_stars"]
    await call.answer()
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=f"{label} tarifi",
        description=f"{label} — kuniga {info['daily_limit']} ta rasm generatsiya qilish imkoniyati.",
        payload=f"tariff:{tariff}",
        currency=STARS_CURRENCY,
        prices=[LabeledPrice(label=label, amount=price)],
    )


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_q: PreCheckoutQuery):
    # Stars to'lovlarida amalda tekshirish shart emas (limit tugab qolish kabi
    # holat yo'q), shuning uchun har doim tasdiqlaymiz.
    await pre_checkout_q.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, bot: Bot):
    payment = message.successful_payment
    payload = payment.invoice_payload  # "tariff:<name>"
    user_id = message.from_user.id

    try:
        _, tariff = payload.split(":", 1)
    except ValueError:
        tariff = None

    if tariff and tariff in store.data.get("tariffs", {}):
        store.grant_tariff(user_id, tariff, days=30)
        store.schedule_save(bot)
        label = store.tariff_label(tariff)
        await message.answer(
            f"✅ To'lov qabul qilindi! Sizga {label} tarifi 30 kunga berildi.\n"
            f"⭐ To'langan: {payment.total_amount} Stars."
        )
    else:
        await message.answer(f"✅ To'lov qabul qilindi (⭐ {payment.total_amount}), lekin tarif aniqlanmadi — admin bilan bog'laning.")

    text = (
        f"⭐ Yangi Stars to'lovi!\n"
        f"👤 {message.from_user.full_name} (@{message.from_user.username or '—'}) [id: {user_id}]\n"
        f"💰 Miqdor: {payment.total_amount} {payment.currency}\n"
        f"🎫 Tarif: {tariff or '—'}\n"
        f"🧾 Telegram Charge ID: {payment.telegram_payment_charge_id}"
    )
    for admin_id in SUPERADMIN_IDS + store.data.get("admins", []):
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass
    try:
        await bot.send_message(DB_GROUP_ID, text)
    except Exception:
        pass


@router.message(F.text == "💳 Tarif sotib olish")
async def btn_tariff(message: Message, state: FSMContext):
    await state.clear()
    t = store.data["tariffs"]
    lines = ["💳 Mavjud tariflar:\n"]
    for name in store.tariff_order():
        if name == "free":
            continue
        info = t[name]
        label = store.tariff_label(name)
        lines.append(
            f"{label}: kuniga {info['daily_limit']} ta rasm — {info['price_stars']} ⭐/oy "
            f"yoki {info['ref_required']} ta referal"
        )
    lines.append("\nTanlang, admin bilan bog'lanamiz:")
    await message.answer("\n".join(lines), reply_markup=tariff_purchase_kb())


@router.message(RequestTariff.waiting_message)
async def tariff_request(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    text = (
        f"💳 Yangi murojaat (tarif)!\n"
        f"👤 {user.full_name} (@{user.username or '—'}) [id: {user.id}]\n"
        f"✍️ Xabar: {message.text}"
    )
    sent_to_any = False
    for admin_id in SUPERADMIN_IDS + store.data.get("admins", []):
        try:
            await bot.send_message(admin_id, text)
            sent_to_any = True
        except Exception:
            pass
    if sent_to_any:
        await message.answer("✅ So'rovingiz adminga yuborildi. Tez orada javob berishadi.")
    else:
        await message.answer("❌ Hozircha yuborib bo'lmadi, keyinroq urinib ko'ring.")


# 16 xonali kod yoki oddiy matn -> avval kod sifatida tekshiramiz, aks holda prompt sifatida rasm yaratamiz
@router.message(F.text & ~F.text.startswith("/"))
async def free_text(message: Message, bot: Bot):
    text = message.text.strip()

    if len(text) == 16 and text.replace(" ", "").isalnum():
        ok, msg, entry = redeem(store.data, text, message.from_user.id)
        if ok:
            store.grant_tariff(message.from_user.id, entry["tariff"], entry.get("days"))
            store.schedule_save(bot)
        await message.answer(msg)
        return

    await _do_generate(message, bot, text)
