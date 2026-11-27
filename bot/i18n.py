"""Interface texts. Question content itself comes from the DB and is not translated."""

DEFAULT_LANGUAGE = "uz"

LANGUAGES = {
    "uz": "🇺🇿 O'zbekcha",
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
}

TEXTS: dict[str, dict[str, str]] = {
    "choose_language": {
        "uz": "Tilni tanlang:",
        "ru": "Выберите язык:",
        "en": "Choose a language:",
    },
    "welcome": {
        "uz": "Assalomu alaykum, {name}! 👋\nBu bot orqali testlarga tayyorlanishingiz mumkin.\n\n"
              "📘 <b>Amaliyot</b> — istalgan sondagi savollar, javob darhol tekshiriladi.\n"
              "📝 <b>Imtihon</b> — {exam} ta tasodifiy savol, natija oxirida.",
        "ru": "Здравствуйте, {name}! 👋\nЭтот бот поможет подготовиться к тестам.\n\n"
              "📘 <b>Практика</b> — любое количество вопросов, ответ проверяется сразу.\n"
              "📝 <b>Экзамен</b> — {exam} случайных вопросов, результат в конце.",
        "en": "Hello, {name}! 👋\nThis bot helps you prepare for tests.\n\n"
              "📘 <b>Practice</b> — any number of questions, answers are checked instantly.\n"
              "📝 <b>Exam</b> — {exam} random questions, results at the end.",
    },
    "choose_theme": {
        "uz": "Mavzuni tanlang:",
        "ru": "Выберите тему:",
        "en": "Choose a theme:",
    },
    "no_themes": {
        "uz": "Hozircha mavzular yo'q. Administrator savollarni yuklashi kerak.",
        "ru": "Пока нет тем. Администратор должен загрузить вопросы.",
        "en": "No themes yet. An administrator needs to import questions.",
    },
    "choose_mode": {
        "uz": "<b>{theme}</b>\nSavollar soni: {n}\n\nRejimni tanlang:",
        "ru": "<b>{theme}</b>\nКоличество вопросов: {n}\n\nВыберите режим:",
        "en": "<b>{theme}</b>\nQuestions: {n}\n\nChoose a mode:",
    },
    "mode_practice": {"uz": "📘 Amaliyot", "ru": "📘 Практика", "en": "📘 Practice"},
    "mode_exam": {"uz": "📝 Imtihon ({n} ta)", "ru": "📝 Экзамен ({n})", "en": "📝 Exam ({n})"},
    "mode_practice_short": {"uz": "Amaliyot", "ru": "Практика", "en": "Practice"},
    "mode_exam_short": {"uz": "Imtihon", "ru": "Экзамен", "en": "Exam"},
    "choose_count": {
        "uz": "Nechta savol yechmoqchisiz? Tugmani bosing yoki 1 dan {max} gacha son yuboring.",
        "ru": "Сколько вопросов хотите решить? Нажмите кнопку или отправьте число от 1 до {max}.",
        "en": "How many questions? Tap a button or send a number from 1 to {max}.",
    },
    "all_questions": {"uz": "Hammasi ({n})", "ru": "Все ({n})", "en": "All ({n})"},
    "invalid_count": {
        "uz": "Iltimos, 1 dan {max} gacha son yuboring.",
        "ru": "Пожалуйста, отправьте число от 1 до {max}.",
        "en": "Please send a number from 1 to {max}.",
    },
    "question_header": {
        "uz": "{mode} · {theme}\nSavol {i}/{n}",
        "ru": "{mode} · {theme}\nВопрос {i}/{n}",
        "en": "{mode} · {theme}\nQuestion {i}/{n}",
    },
    "correct": {"uz": "✅ To'g'ri!", "ru": "✅ Верно!", "en": "✅ Correct!"},
    "wrong": {
        "uz": "❌ Noto'g'ri. To'g'ri javob: {letter}",
        "ru": "❌ Неверно. Правильный ответ: {letter}",
        "en": "❌ Wrong. Correct answer: {letter}",
    },
    "answer_saved": {
        "uz": "Javobingiz: {letter}",
        "ru": "Ваш ответ: {letter}",
        "en": "Your answer: {letter}",
    },
    "stop": {"uz": "⏹ To'xtatish", "ru": "⏹ Остановить", "en": "⏹ Stop"},
    "stopped": {
        "uz": "Test to'xtatildi.",
        "ru": "Тест остановлен.",
        "en": "Test stopped.",
    },
    "no_active": {
        "uz": "Faol test yo'q.",
        "ru": "Нет активного теста.",
        "en": "No active test.",
    },
    "stale_button": {
        "uz": "Bu savol allaqachon yopilgan.",
        "ru": "Этот вопрос уже закрыт.",
        "en": "This question is already closed.",
    },
    "result_title": {
        "uz": "🏁 <b>Natija</b> — {mode} · {theme}",
        "ru": "🏁 <b>Результат</b> — {mode} · {theme}",
        "en": "🏁 <b>Result</b> — {mode} · {theme}",
    },
    "result_score": {
        "uz": "To'g'ri javoblar: <b>{c}/{n}</b> ({p}%)",
        "ru": "Правильных ответов: <b>{c}/{n}</b> ({p}%)",
        "en": "Correct answers: <b>{c}/{n}</b> ({p}%)",
    },
    "result_answered": {
        "uz": "Javob berilgan: {a}/{n}",
        "ru": "Отвечено: {a}/{n}",
        "en": "Answered: {a}/{n}",
    },
    "review_title": {
        "uz": "📋 <b>Xatolar tahlili</b>",
        "ru": "📋 <b>Разбор ошибок</b>",
        "en": "📋 <b>Mistakes review</b>",
    },
    "review_perfect": {
        "uz": "🎉 Barcha javoblar to'g'ri!",
        "ru": "🎉 Все ответы верные!",
        "en": "🎉 All answers are correct!",
    },
    "review_yours": {"uz": "Sizning javobingiz", "ru": "Ваш ответ", "en": "Your answer"},
    "review_correct": {"uz": "To'g'ri javob", "ru": "Правильный ответ", "en": "Correct answer"},
    "not_answered": {"uz": "javob berilmagan", "ru": "нет ответа", "en": "not answered"},
    "again": {"uz": "🔁 Yana", "ru": "🔁 Ещё раз", "en": "🔁 Again"},
    "menu": {"uz": "🏠 Menyu", "ru": "🏠 Меню", "en": "🏠 Menu"},
    "back": {"uz": "⬅️ Orqaga", "ru": "⬅️ Назад", "en": "⬅️ Back"},
    "continue": {
        "uz": "▶️ Davom etish ({i}/{n})",
        "ru": "▶️ Продолжить ({i}/{n})",
        "en": "▶️ Continue ({i}/{n})",
    },
    "btn_results": {"uz": "📊 Natijalarim", "ru": "📊 Мои результаты", "en": "📊 My results"},
    "btn_language": {"uz": "🌐 Til", "ru": "🌐 Язык", "en": "🌐 Language"},
    "results_title": {
        "uz": "📊 <b>Oxirgi natijalar</b>",
        "ru": "📊 <b>Последние результаты</b>",
        "en": "📊 <b>Recent results</b>",
    },
    "results_empty": {
        "uz": "Hali yakunlangan testlar yo'q.",
        "ru": "Пока нет завершённых тестов.",
        "en": "No finished tests yet.",
    },
    "help": {
        "uz": "/start — bosh menyu\n/stop — joriy testni to'xtatish\n/results — natijalarim\n/top — top natijalar\n"
              "/profile — profil\n/language — tilni o'zgartirish\n/logout — tizimdan chiqish",
        "ru": "/start — главное меню\n/stop — остановить текущий тест\n/results — мои результаты\n"
              "/top — лучшие результаты\n/profile — профиль\n/language — сменить язык\n/logout — выйти",
        "en": "/start — main menu\n/stop — stop the current test\n/results — my results\n/top — top results\n"
              "/profile — profile\n/language — change language\n/logout — log out",
    },
}

TEXTS.update({
    # ---- registration / login
    "reg_intro": {
        "uz": "📝 Botdan foydalanish uchun ro'yxatdan o'ting.",
        "ru": "📝 Чтобы пользоваться ботом, пройдите регистрацию.",
        "en": "📝 Please register to use the bot.",
    },
    "reg_ask_name": {
        "uz": "Ism va familiyangizni kiriting:",
        "ru": "Введите имя и фамилию:",
        "en": "Enter your full name:",
    },
    "reg_invalid_name": {
        "uz": "Ism 3–100 belgidan iborat bo'lishi kerak. Qaytadan kiriting:",
        "ru": "Имя должно содержать 3–100 символов. Введите ещё раз:",
        "en": "The name must be 3–100 characters. Please try again:",
    },
    "reg_ask_phone": {
        "uz": "Telefon raqamingizni yuborish uchun pastdagi tugmani bosing 👇",
        "ru": "Нажмите кнопку ниже, чтобы отправить номер телефона 👇",
        "en": "Tap the button below to share your phone number 👇",
    },
    "reg_share_phone": {"uz": "📱 Raqamni yuborish", "ru": "📱 Отправить номер", "en": "📱 Share phone number"},
    "reg_phone_not_own": {
        "uz": "Iltimos, o'zingizning raqamingizni tugma orqali yuboring.",
        "ru": "Пожалуйста, отправьте свой номер с помощью кнопки.",
        "en": "Please share your own number using the button.",
    },
    "reg_ask_group": {
        "uz": "Guruhingizni kiriting (masalan, 5-kurs IX):",
        "ru": "Введите вашу группу (например, 5-kurs IX):",
        "en": "Enter your group (e.g. 5-kurs IX):",
    },
    "reg_invalid_group": {
        "uz": "Guruh nomi 1–50 belgidan iborat bo'lishi kerak. Qaytadan kiriting:",
        "ru": "Название группы должно содержать 1–50 символов. Введите ещё раз:",
        "en": "The group must be 1–50 characters. Please try again:",
    },
    "reg_done": {
        "uz": "✅ Ro'yxatdan o'tdingiz!",
        "ru": "✅ Регистрация завершена!",
        "en": "✅ You're registered!",
    },
    "logged_out": {
        "uz": "🔒 Siz tizimdan chiqqansiz. Davom etish uchun kiring.",
        "ru": "🔒 Вы вышли из системы. Войдите, чтобы продолжить.",
        "en": "🔒 You're logged out. Log in to continue.",
    },
    "btn_login": {"uz": "🔐 Kirish", "ru": "🔐 Войти", "en": "🔐 Log in"},
    "logout_done": {
        "uz": "👋 Tizimdan chiqdingiz. Qaytish uchun /start bosing.",
        "ru": "👋 Вы вышли. Чтобы вернуться, нажмите /start.",
        "en": "👋 You've logged out. Send /start to log back in.",
    },
    # ---- profile
    "btn_profile": {"uz": "👤 Profil", "ru": "👤 Профиль", "en": "👤 Profile"},
    "profile": {
        "uz": "👤 <b>Profil</b>\n\nIsm: {name}\nTelefon: {phone}\nGuruh: {group}",
        "ru": "👤 <b>Профиль</b>\n\nИмя: {name}\nТелефон: {phone}\nГруппа: {group}",
        "en": "👤 <b>Profile</b>\n\nName: {name}\nPhone: {phone}\nGroup: {group}",
    },
    "btn_edit_profile": {"uz": "✏️ Tahrirlash", "ru": "✏️ Изменить", "en": "✏️ Edit"},
    "btn_logout": {"uz": "🚪 Chiqish", "ru": "🚪 Выйти", "en": "🚪 Log out"},
    # ---- leaderboard
    "btn_top": {"uz": "🏆 Top natijalar", "ru": "🏆 Лучшие результаты", "en": "🏆 Top results"},
    "top_choose_theme": {
        "uz": "🏆 Qaysi mavzu bo'yicha top natijalarni ko'rasiz?",
        "ru": "🏆 Выберите тему для просмотра лучших результатов:",
        "en": "🏆 Choose a theme to see the top results:",
    },
    "top_title": {
        "uz": "🏆 <b>Top natijalar</b> — {theme}\n<i>Imtihon, har bir foydalanuvchining eng yaxshi natijasi</i>",
        "ru": "🏆 <b>Лучшие результаты</b> — {theme}\n<i>Экзамен, лучший результат каждого пользователя</i>",
        "en": "🏆 <b>Top results</b> — {theme}\n<i>Exam, each user's best attempt</i>",
    },
    "top_empty": {
        "uz": "Bu mavzu bo'yicha hali imtihon natijalari yo'q.",
        "ru": "По этой теме пока нет результатов экзамена.",
        "en": "No exam results for this theme yet.",
    },
    "top_you": {
        "uz": "Sizning o'rningiz: <b>{rank}</b> — {c}/{n} ({p}%)",
        "ru": "Ваше место: <b>{rank}</b> — {c}/{n} ({p}%)",
        "en": "Your rank: <b>{rank}</b> — {c}/{n} ({p}%)",
    },
    "top_you_none": {
        "uz": "Siz bu mavzu bo'yicha hali imtihon topshirmagansiz.",
        "ru": "Вы ещё не сдавали экзамен по этой теме.",
        "en": "You haven't taken this exam yet.",
    },
    "btn_webapp": {"uz": "📱 Mini App", "ru": "📱 Mini App", "en": "📱 Mini App"},
    # ---- Mini App only
    "web_open_in_telegram": {
        "uz": "Ilovani Telegram bot orqali oching.",
        "ru": "Откройте приложение через Telegram-бота.",
        "en": "Please open this app from the Telegram bot.",
    },
    "web_error": {
        "uz": "Xatolik yuz berdi. Qayta urinib ko'ring.",
        "ru": "Что-то пошло не так. Попробуйте ещё раз.",
        "en": "Something went wrong. Please try again.",
    },
    "web_retry": {"uz": "Qayta urinish", "ru": "Повторить", "en": "Retry"},
    "web_name_label": {"uz": "Ism va familiya", "ru": "Имя и фамилия", "en": "Full name"},
    "web_group_label": {"uz": "Guruh", "ru": "Группа", "en": "Group"},
    "web_phone_label": {"uz": "Telefon raqam", "ru": "Номер телефона", "en": "Phone number"},
    "web_waiting_phone": {
        "uz": "Telegram raqamingizni tasdiqlashini kutyapmiz…",
        "ru": "Ждём подтверждения номера от Telegram…",
        "en": "Waiting for Telegram to confirm your number…",
    },
    "web_phone_in_chat": {
        "uz": "Telegram versiyangiz ilovadan raqam yuborishni qo'llab-quvvatlamaydi. "
              "Ro'yxatdan o'tishni bot chatida yakunlang.",
        "ru": "Ваша версия Telegram не позволяет отправить номер из приложения. Завершите регистрацию в чате бота.",
        "en": "Your Telegram version can't share contacts from the app. Please finish registration in the bot chat.",
    },
    "web_phone_declined": {
        "uz": "Ro'yxatdan o'tish uchun telefon raqam kerak.",
        "ru": "Для регистрации нужен номер телефона.",
        "en": "A phone number is required to register.",
    },
    "web_continue": {"uz": "Davom etish", "ru": "Продолжить", "en": "Continue"},
    "web_choose_count": {
        "uz": "Nechta savol? (1–{max})",
        "ru": "Сколько вопросов? (1–{max})",
        "en": "How many questions? (1–{max})",
    },
    "web_start": {"uz": "Boshlash", "ru": "Начать", "en": "Start"},
    "web_next": {"uz": "Keyingi", "ru": "Далее", "en": "Next"},
    "web_results_btn": {"uz": "Natijani ko'rish", "ru": "Посмотреть результат", "en": "See result"},
    "web_stop_confirm": {
        "uz": "Testni to'xtatasizmi?",
        "ru": "Остановить тест?",
        "en": "Stop the test?",
    },
    "web_logout_confirm": {
        "uz": "Tizimdan chiqasizmi?",
        "ru": "Выйти из системы?",
        "en": "Log out?",
    },
    "web_time": {"uz": "Vaqt", "ru": "Время", "en": "Time"},
    "web_you": {"uz": "siz", "ru": "вы", "en": "you"},
})

# ---- group battles (group messages use the group's language; popups use the player's)
TEXTS.update({
    "grp_intro": {
        "uz": "👋 Salom! Men test botman. Bu guruhda ⚔️ <b>bellashuv</b> o'tkazish mumkin: hamma bir vaqtda bir xil "
              "{n} ta savolga javob beradi, har biriga {s} soniya. To'g'ri va tez javob ko'proq ball beradi.\n\n"
              "Qatnashish uchun avval men bilan shaxsiy chatda ro'yxatdan o'ting.",
        "ru": "👋 Привет! Я тестовый бот. В этой группе можно провести ⚔️ <b>батл</b>: все одновременно отвечают на "
              "одни и те же {n} вопросов, по {s} секунд на каждый. За верный и быстрый ответ — больше очков.\n\n"
              "Чтобы участвовать, сначала зарегистрируйтесь в личном чате со мной.",
        "en": "👋 Hi! I'm a test bot. This group can play ⚔️ <b>battles</b>: everyone answers the same {n} questions "
              "at the same time, {s} seconds each. Fast correct answers earn more points.\n\n"
              "To play, register in a private chat with me first.",
    },
    "grp_help": {
        "uz": "⚔️ <b>Bellashuv</b>\n/battle — bellashuv boshlash\n/battle_stop — bekor qilish (boshlovchi yoki admin)\n"
              "/language — guruh tili (adminlar)\n\n{n} ta savol, har biriga {s} soniya. To'g'ri javob 500–1000 ball "
              "beradi: qanchalik tez bo'lsa, shuncha ko'p.",
        "ru": "⚔️ <b>Батл</b>\n/battle — начать батл\n/battle_stop — отменить (организатор или админ)\n"
              "/language — язык группы (админы)\n\n{n} вопросов, по {s} секунд. Верный ответ даёт 500–1000 очков: "
              "чем быстрее, тем больше.",
        "en": "⚔️ <b>Battle</b>\n/battle — start a battle\n/battle_stop — cancel it (starter or admin)\n"
              "/language — group language (admins)\n\n{n} questions, {s} seconds each. A correct answer gives "
              "500–1000 points: the faster, the more.",
    },
    "btn_battle_new": {"uz": "⚔️ Bellashuv boshlash", "ru": "⚔️ Начать батл", "en": "⚔️ Start battle"},
    "btn_register": {"uz": "📝 Ro'yxatdan o'tish", "ru": "📝 Регистрация", "en": "📝 Register"},
    "battle_need_register": {
        "uz": "{name}, bellashuvni boshlash uchun avval bot bilan shaxsiy chatda ro'yxatdan o'ting.",
        "ru": "{name}, чтобы начать батл, сначала зарегистрируйтесь в личном чате с ботом.",
        "en": "{name}, to start a battle, register in a private chat with the bot first.",
    },
    "battle_choose_theme": {
        "uz": "⚔️ {name}, bellashuv mavzusini tanlang:",
        "ru": "⚔️ {name}, выберите тему батла:",
        "en": "⚔️ {name}, choose a theme for the battle:",
    },
    "battle_already_active": {
        "uz": "Bu guruhda bellashuv allaqachon ketmoqda.",
        "ru": "В этой группе уже идёт батл.",
        "en": "A battle is already running in this group.",
    },
    "battle_lobby": {
        "uz": "⚔️ <b>Bellashuv</b> · {theme}\n{n} ta savol · har biriga {s} soniya\nBoshlovchi: {name}\n\n"
              "<b>Ishtirokchilar ({k}):</b>\n{players}\n\n"
              "Qatnashish uchun «Qo'shilish»ni bosing. {name} «Boshlash»ni bosganda yoki 2 daqiqadan so'ng "
              "avtomatik boshlanadi (kamida {min} kishi).",
        "ru": "⚔️ <b>Батл</b> · {theme}\n{n} вопросов · по {s} секунд\nОрганизатор: {name}\n\n"
              "<b>Участники ({k}):</b>\n{players}\n\n"
              "Нажмите «Присоединиться», чтобы участвовать. Батл начнётся, когда {name} нажмёт «Начать», или "
              "автоматически через 2 минуты (минимум {min} участника).",
        "en": "⚔️ <b>Battle</b> · {theme}\n{n} questions · {s} s each\nStarted by {name}\n\n"
              "<b>Players ({k}):</b>\n{players}\n\n"
              "Tap Join to play. It starts when {name} taps Start, or automatically in 2 minutes "
              "(at least {min} players).",
    },
    "btn_join": {"uz": "➕ Qo'shilish", "ru": "➕ Присоединиться", "en": "➕ Join"},
    "btn_start": {"uz": "▶️ Boshlash", "ru": "▶️ Начать", "en": "▶️ Start"},
    "btn_cancel": {"uz": "✖️ Bekor qilish", "ru": "✖️ Отменить", "en": "✖️ Cancel"},
    "battle_started": {
        "uz": "⚔️ <b>Bellashuv boshlandi!</b> · {theme}\nIshtirokchilar: {players}\nOmad! 🍀",
        "ru": "⚔️ <b>Батл начался!</b> · {theme}\nУчастники: {players}\nУдачи! 🍀",
        "en": "⚔️ <b>Battle started!</b> · {theme}\nPlayers: {players}\nGood luck! 🍀",
    },
    "battle_question_header": {
        "uz": "⚔️ {theme} — savol {i}/{n} · ⏱ {s} soniya",
        "ru": "⚔️ {theme} — вопрос {i}/{n} · ⏱ {s} с",
        "en": "⚔️ {theme} — question {i}/{n} · ⏱ {s} s",
    },
    "battle_answered": {"uz": "Javob berdi: {a}/{p}", "ru": "Ответили: {a}/{p}", "en": "Answered: {a}/{p}"},
    "battle_correct_count": {
        "uz": "✅ To'g'ri javob berdi: {c}/{p}",
        "ru": "✅ Ответили верно: {c}/{p}",
        "en": "✅ Correct: {c}/{p}",
    },
    "battle_top": {"uz": "🏆 Hozircha:", "ru": "🏆 Сейчас:", "en": "🏆 So far:"},
    "battle_points": {"uz": "ball", "ru": "очк.", "en": "pts"},
    "battle_cancelled": {
        "uz": "✖️ Bellashuv bekor qilindi.",
        "ru": "✖️ Батл отменён.",
        "en": "✖️ Battle cancelled.",
    },
    "battle_cancelled_players": {
        "uz": "✖️ Bellashuv bekor qilindi: yetarli ishtirokchi qo'shilmadi (kamida {min}).",
        "ru": "✖️ Батл отменён: недостаточно участников (минимум {min}).",
        "en": "✖️ Battle cancelled: not enough players joined (at least {min}).",
    },
    "battle_results_title": {
        "uz": "🏁 <b>Bellashuv natijalari</b> — {theme}",
        "ru": "🏁 <b>Итоги батла</b> — {theme}",
        "en": "🏁 <b>Battle results</b> — {theme}",
    },
    "battle_results_footer": {
        "uz": "Har bir ishtirokchiga xatolar tahlili shaxsiy chatda yuborildi.",
        "ru": "Каждому участнику отправлен разбор ошибок в личном чате.",
        "en": "Each player got a mistakes review in a private chat.",
    },
    "battle_no_battle": {
        "uz": "Hozir faol bellashuv yo'q.",
        "ru": "Сейчас нет активного батла.",
        "en": "There's no active battle right now.",
    },
    "battle_dm_title": {
        "uz": "⚔️ <b>Bellashuv tahlili</b> — {theme}\nO'rin: <b>{rank}/{total}</b> · {points} ball · "
              "to'g'ri: {c}/{n}",
        "ru": "⚔️ <b>Разбор батла</b> — {theme}\nМесто: <b>{rank}/{total}</b> · {points} очк. · "
              "верно: {c}/{n}",
        "en": "⚔️ <b>Battle review</b> — {theme}\nRank: <b>{rank}/{total}</b> · {points} pts · "
              "correct: {c}/{n}",
    },
    "battle_dm_registered": {
        "uz": "✅ Tayyor! Guruhga qayting va «➕ Qo'shilish» tugmasini bosing.",
        "ru": "✅ Готово! Вернитесь в группу и нажмите «➕ Присоединиться».",
        "en": "✅ All set! Go back to the group and tap ➕ Join.",
    },
    "grp_language_admin_only": {
        "uz": "Guruh tilini faqat adminlar o'zgartira oladi.",
        "ru": "Язык группы могут менять только админы.",
        "en": "Only group admins can change the group language.",
    },
    "grp_language_set": {
        "uz": "Guruh tili: {name}",
        "ru": "Язык группы: {name}",
        "en": "Group language: {name}",
    },
    # popups (player's own language)
    "toast_joined": {"uz": "Siz qo'shildingiz! ✅", "ru": "Вы в игре! ✅", "en": "You're in! ✅"},
    "toast_already_joined": {"uz": "Siz allaqachon qo'shilgansiz.", "ru": "Вы уже участвуете.",
                             "en": "You've already joined."},
    "toast_need_players": {"uz": "Kamida {min} ishtirokchi kerak.", "ru": "Нужно минимум {min} участника.",
                           "en": "At least {min} players are needed."},
    "toast_not_lobby": {"uz": "Bu bellashuvga qo'shilish yopilgan.", "ru": "Набор в этот батл закрыт.",
                        "en": "This battle is no longer open."},
    "toast_not_allowed": {"uz": "Buni faqat boshlovchi yoki admin qila oladi.",
                          "ru": "Это может сделать только организатор или админ.",
                          "en": "Only the starter or a group admin can do this."},
    "toast_only_starter": {"uz": "Buni faqat bellashuvni boshlagan kishi qila oladi.",
                           "ru": "Это может сделать только тот, кто начал батл.",
                           "en": "Only the person who started the battle can do this."},
    "toast_not_player": {"uz": "Siz bu bellashuvda qatnashmayapsiz. Keyingisiga qo'shiling!",
                         "ru": "Вы не участвуете в этом батле. Присоединяйтесь к следующему!",
                         "en": "You're not in this battle. Join the next one!"},
    "toast_answer_saved": {"uz": "Javobingiz qabul qilindi: {letter}", "ru": "Ответ принят: {letter}",
                           "en": "Answer saved: {letter}"},
    "toast_already_answered": {"uz": "Siz allaqachon javob bergansiz.", "ru": "Вы уже ответили.",
                               "en": "You've already answered."},
    "toast_too_late": {"uz": "Bu savol uchun vaqt tugadi.", "ru": "Время на этот вопрос вышло.",
                       "en": "Time's up for this question."},
    "toast_battle_active": {"uz": "Bu guruhda bellashuv allaqachon ketmoqda.", "ru": "В группе уже идёт батл.",
                            "en": "A battle is already running here."},
})

GROUP_COMMAND_DESCRIPTIONS = {
    "battle": {"uz": "Bellashuv boshlash", "ru": "Начать батл", "en": "Start a battle"},
    "battle_stop": {"uz": "Bellashuvni bekor qilish", "ru": "Отменить батл", "en": "Cancel the battle"},
    "language": {"uz": "Guruh tili", "ru": "Язык группы", "en": "Group language"},
    "help": {"uz": "Yordam", "ru": "Помощь", "en": "Help"},
}

COMMAND_DESCRIPTIONS = {
    "start": {"uz": "Bosh menyu", "ru": "Главное меню", "en": "Main menu"},
    "top": {"uz": "Top natijalar", "ru": "Лучшие результаты", "en": "Top results"},
    "profile": {"uz": "Profil", "ru": "Профиль", "en": "Profile"},
    "logout": {"uz": "Tizimdan chiqish", "ru": "Выйти", "en": "Log out"},
    "stop": {"uz": "Testni to'xtatish", "ru": "Остановить тест", "en": "Stop the test"},
    "results": {"uz": "Natijalarim", "ru": "Мои результаты", "en": "My results"},
    "language": {"uz": "Tilni o'zgartirish", "ru": "Сменить язык", "en": "Change language"},
    "help": {"uz": "Yordam", "ru": "Помощь", "en": "Help"},
}


def normalize_language(code: str | None) -> str:
    code = (code or "").split("-")[0].lower()
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def t(lang: str | None, key: str, **kwargs) -> str:
    entry = TEXTS[key]
    text = entry.get(lang or DEFAULT_LANGUAGE) or entry[DEFAULT_LANGUAGE]
    return text.format(**kwargs) if kwargs else text


def all_texts(lang: str | None) -> dict[str, str]:
    """Every interface text in one language (raw templates), for the Mini App frontend."""
    lang = normalize_language(lang)
    return {key: entry.get(lang) or entry[DEFAULT_LANGUAGE] for key, entry in TEXTS.items()}
