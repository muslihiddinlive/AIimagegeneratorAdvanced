# AI Rasm Generatsiya Boti (Pollinations.ai asosida)

## O'rnatish

```bash
pip install -r requirements.txt --break-system-packages
cp .env.example .env
# .env faylini to'ldiring: BOT_TOKEN, DB_GROUP_ID, SUPERADMIN_ID
python main.py
```

**Guruhni sozlash:**
1. Botni DB_GROUP_ID sifatida ishlatmoqchi bo'lgan guruhga qo'shing.
2. Botga **admin** huquqi bering, kamida: "Xabarlarni pin qilish" va "Fayl yuborish" ruxsatlari bo'lsin.
3. Bot birinchi marta ishga tushganda o'zi `bot_state.json` yaratib guruhga pin qiladi.

## Xususiyatlar

- `/generate <prompt>` yoki oddiy matn yuborish orqali rasm yaratish
- Har bir userga sutkalik bepul limit (standart: 5 ta)
- Taqiqlangan so'z aniqlansa: rasm yaratilmaydi, limitdan 1 ta ayiriladi
- Admin panel: `/admin` (faqat superadmin va superadmin qo'shgan adminlar)
  - Userlar ro'yxati va ularning promptlari
  - Broadcast (hammaga xabar)
  - Foydalanuvchiga to'g'ridan-to'g'ri limit berish (kodsiz)
  - Bir martalik 16 xonali kod yaratish (limit miqdori + necha kunga)
  - Taqiqlangan so'zlarni boshqarish: `/addword`, `/delword`
  - Custom (premium) emoji: `/addemoji`, `/delemoji`
  - Premium reaksiya bosiladigan adminlar: `/addreactionadmin`, `/delreactionadmin`, `/setreactionemoji`
  - Admin qo'shish/olib tashlash: `/addadmin`, `/deladmin`
- "💳 Tarif sotib olish" tugmasi — user yozgan xabar to'g'ridan-to'g'ri barcha adminlarga yuboriladi
- Database sifatida Telegram guruh ishlatiladi: butun holat (`bot_state.json`) guruhda pin qilingan xabar sifatida saqlanadi, runtime'da RAM'da keshlanadi
- Har bir generatsiya (rasm + prompt + user) DB guruhiga log sifatida yuboriladi

## Yangi qo'shilgan imkoniyatlar

- **Multi-worker navbat** — bir vaqtda `GEN_QUEUE_WORKERS` tagacha (default: 10)
  rasm PARALLEL generatsiya qilinadi. 11-chi so'rov kelsa, avtomatik FIFO
  navbatga tushadi va birinchi bo'shagan workerga o'tadi. `.env`da
  `GEN_QUEUE_WORKERS` orqali oshirish/kamaytirish mumkin.
- **Taqiqlangan so'zlar ro'yxati default bo'sh** — Pollinations.ai o'zining
  ichki NSFW-moderatsiyasiga tayanamiz. Admin panel orqali (`/admwords`)
  xohlasa o'zi so'z qo'shishi mumkin, lekin standart holatda hech narsa
  bloklanmaydi.
- **Telegram Stars orqali haqiqiy to'lov** — "💳 Tarif sotib olish" endi
  narxli tariflar uchun to'g'ridan-to'g'ri Stars invoice yuboradi
  (`currency=XTR`). To'lov muvaffaqiyatli bo'lsa, tarif userga AVTOMATIK
  30 kunga beriladi, admin/superadminlarga va DB guruhiga xabar ketadi.
  ⚠️ **Muhim:** Telegram Stars har doim botni @BotFather'da RO'YXATDAN
  O'TKAZGAN akkauntning Stars balansiga tushadi — bu Telegram platformasi
  qoidasi, bot kodi orqali boshqa "superadmin"ga yo'naltirib bo'lmaydi.
  Agar bir nechta superadmin bo'lsa, pul faqat bot egasiga tushadi.
- **Superadmin yangi tarif joriy eta oladi** — Admin panel → 💳 Tariflar
  sozlamasi → ➕ Yangi tarif yaratish: kalit, label, kunlik limit, narx
  (Stars), referal talabini ketma-ket kiritadi.
- **"API key" (maxsus sotuv kodi)** — Admin panel → 🔐 API key: nomi,
  kunlik limiti va necha kunga amal qilishini aniq kiritib, 16 xonali
  bir martalik kod generatsiya qiladi (umumiy tariflar ro'yxatida
  ko'rinmaydi, faqat shu kodni ishlatgan userga tegishli).

## Muhim eslatmalar (halol aytilishi kerak bo'lgan cheklovlar)

1. **Pollinations.ai'ning o'z NSFW-filtri** endi yagona himoya qatlami —
   bot darajasidagi so'z-filtri o'chirilgan (yuqoriga qarang). Agar
   Pollinations filtri o'zgarsa/zaiflashsa, bot buni bilmaydi.
2. **Premium custom emoji reaksiya** — Telegram bot API orqali `set_message_reaction`
   custom emoji bilan har doim ishlashi kafolatlanmagan; bu chat sozlamalariga
   (`available_reactions`) bog'liq. Ishlamasa, oddiy emoji reaksiyaga fallback qiladi.
3. **Telegram guruhni "database" sifatida ishlatish** — bu ishlaydigan, ammo
   noan'anaviy yechim: yuqori yozish tezligida (concurrent yozishlar) race condition
   xavfi bor, chunki har bir `store.save()` butun faylni qayta yuboradi. Katta
   foydalanuvchi soni uchun haqiqiy DB (SQLite/Postgres) ancha barqaror bo'ladi.
4. **Pollinations.ai** — bepul, lekin rasmiy SLA yo'q; ba'zida sekinlashishi yoki
   vaqtincha ishlamay qolishi mumkin, shuning uchun xato handling qo'shilgan.
5. Kod hozircha rate-limit/concurrency uchun semaphore (5 parallel) va per-request
   timeout (60s) bilan himoyalangan, lekin juda yuqori yuklamada (yuzlab bir vaqtdagi
   user) qo'shimcha optimizatsiya (masalan navbat/worker pool) kerak bo'lishi mumkin.
