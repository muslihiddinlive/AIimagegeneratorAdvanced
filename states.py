from aiogram.fsm.state import State, StatesGroup


class GenCode(StatesGroup):
    """Superadmin panelidan tarif-kod yaratish. Tarif inline tugma orqali FSM
    data'ga yoziladi, so'ng shu state kutiladi (kunlar soni)."""
    waiting_days = State()


class TariffGrant(StatesGroup):
    """Foydalanuvchi kartochkasidan to'g'ridan-to'g'ri tarif berish."""
    waiting_days = State()


class TariffEdit(StatesGroup):
    """Superadmin tarif parametrini (kunlik limit/narx/referal) inline tahrirlaydi."""
    waiting_value = State()


class Broadcast(StatesGroup):
    waiting_text = State()


class SendToUser(StatesGroup):
    """Admin muayyan userga shaxsiy xabar yozadi."""
    waiting_text = State()


class WordsManage(StatesGroup):
    waiting_add = State()


class AdminAdd(StatesGroup):
    """Superadmin yangi admin qo'shadi (inline tugma + user_id kiritish)."""
    waiting_id = State()


class ChannelSetup(StatesGroup):
    """Majburiy/bonus kanal username'ini kiritish."""
    waiting_mandatory = State()
    waiting_bonus = State()


class RequestTariff(StatesGroup):
    waiting_message = State()


class TariffCreate(StatesGroup):
    """Superadmin butunlay YANGI tarif joriy etadi (nomi, label, kunlik limit,
    narx, referal talabi - ketma-ket so'raladi)."""
    waiting_key = State()
    waiting_label = State()
    waiting_daily_limit = State()
    waiting_price = State()
    waiting_ref_required = State()


class CustomCode(StatesGroup):
    """"API key" - sotuvga chiqariladigan bir martalik maxsus kod: nomi
    (ko'rsatiladigan label), kunlik limiti va necha kunga amal qilishi aniq
    ketma-ket so'raladi, so'ng shu parametrlar bilan 16 xonali kod yaratiladi."""
    waiting_name = State()
    waiting_limit = State()
    waiting_days = State()


class KnowledgeUpload(StatesGroup):
    """Superadmin bot uchun "bilim" (o'zi haqida, dasturchisi haqida, kanali
    haqida va h.k.) yuklaydi - MD fayl yoki oddiy matn xabar sifatida."""
    waiting_content = State()


class UserContact(StatesGroup):
    """Oddiy foydalanuvchi "Adminga murojaat" tugmasi orqali yozadi."""
    waiting_message = State()
