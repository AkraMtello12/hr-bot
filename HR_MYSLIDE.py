# -*- coding: utf-8 -*-
import logging
from datetime import datetime, date, time
import calendar
import os
import json
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
import firebase_admin
from firebase_admin import credentials, db

# --- قسم الإعدادات (Firebase and Telegram) ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8022986919:AAEPa_fgGad_MbmR5i35ZmBLWGgC8G1xmIo")
FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL", "https://hr-myslide-default-rtdb.europe-west1.firebasedatabase.app")

# --- إعداد اتصال Firebase ---
try:
    firebase_creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if firebase_creds_json:
        print("Found Firebase credentials in environment variable.")
        cred_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(cred_dict)
    else:
        print("Using local 'firebase-credentials.json' file.")
        cred = credentials.Certificate("firebase-credentials.json")

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DATABASE_URL})
    print("Firebase connected successfully!")
except Exception as e:
    print(f"Error connecting to Firebase: {e}")
    exit()

# إعداد التسجيل لرؤية الأخطاء
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- تعريف حالات المحادثة ---
# إجازة يومية
(FD_ENTERING_NAME, FD_ENTERING_REASON, FD_CHOOSING_DURATION_TYPE, FD_SELECTING_DATES, FD_CONFIRMING_LEAVE) = range(5)
# إجازة ساعية
(HL_CHOOSING_TYPE, HL_SELECTING_TIME, HL_ENTERING_NAME, HL_ENTERING_REASON, HL_CONFIRMING_LEAVE) = range(5, 10)
# صندوق الاقتراحات
(SUGGESTION_ENTERING_NAME, SUGGESTION_ENTERING_MESSAGE) = range(10, 12)


# --- دوال إنشاء التقويم والوقت ---
# (تبقى كما هي)
def create_advanced_calendar(year: int, month: int, selection_mode: str, selected_dates: list) -> InlineKeyboardMarkup:
    cal = calendar.Calendar()
    month_name = calendar.month_name[month]
    today = date.today()
    keyboard = []
    header_row = [
        InlineKeyboardButton("<", callback_data=f"CAL_NAV_{year}_{month-1}" if month > 1 else f"CAL_NAV_{year-1}_12"),
        InlineKeyboardButton(f"{month_name} {year}", callback_data="CAL_IGNORE"),
        InlineKeyboardButton(">", callback_data=f"CAL_NAV_{year}_{month+1}" if month < 12 else f"CAL_NAV_{year+1}_1"),
    ]
    keyboard.append(header_row)
    days_row = [InlineKeyboardButton(day, callback_data="CAL_IGNORE") for day in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]]
    keyboard.append(days_row)
    for week in cal.monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
            else:
                current_day = date(year, month, day)
                is_disabled = current_day < today or (selection_mode == 'range' and selected_dates and current_day < selected_dates[0])
                day_text = str(day)
                if current_day in selected_dates:
                    day_text = f"*{day}*"
                if is_disabled:
                    row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
                else:
                    row.append(InlineKeyboardButton(day_text, callback_data=f"CAL_DAY_{year}_{month}_{day}"))
        keyboard.append(row)
    if selection_mode == 'multiple' and selected_dates:
        keyboard.append([InlineKeyboardButton("✅ تم الاختيار", callback_data="CAL_DONE")])
    return InlineKeyboardMarkup(keyboard)

def create_time_keyboard(leave_type: str) -> InlineKeyboardMarkup:
    keyboard = []
    if leave_type == 'late':
        keyboard = [[InlineKeyboardButton("9:30 AM", callback_data="TIME_9:30 AM"), InlineKeyboardButton("10:00 AM", callback_data="TIME_10:00 AM")],[InlineKeyboardButton("10:30 AM", callback_data="TIME_10:30 AM"), InlineKeyboardButton("11:00 AM", callback_data="TIME_11:00 AM")],[InlineKeyboardButton("11:30 AM", callback_data="TIME_11:30 AM"), InlineKeyboardButton("12:00 PM", callback_data="TIME_12:00 PM")],[InlineKeyboardButton("12:30 PM", callback_data="TIME_12:30 PM"), InlineKeyboardButton("1:00 PM", callback_data="TIME_1:00 PM")],[InlineKeyboardButton("1:30 PM", callback_data="TIME_1:30 PM"), InlineKeyboardButton("2:00 PM", callback_data="TIME_2:00 PM")],]
    elif leave_type == 'early':
        keyboard = [[InlineKeyboardButton("11:00 AM", callback_data="TIME_11:00 AM"), InlineKeyboardButton("11:30 AM", callback_data="TIME_11:30 AM")],[InlineKeyboardButton("12:00 PM", callback_data="TIME_12:00 PM"), InlineKeyboardButton("12:30 PM", callback_data="TIME_12:30 PM")],[InlineKeyboardButton("1:00 PM", callback_data="TIME_1:00 PM"), InlineKeyboardButton("1:30 PM", callback_data="TIME_1:30 PM")],[InlineKeyboardButton("2:00 PM", callback_data="TIME_2:00 PM"), InlineKeyboardButton("2:30 PM", callback_data="TIME_2:30 PM")],[InlineKeyboardButton("3:00 PM", callback_data="TIME_3:00 PM"), InlineKeyboardButton("3:30 PM", callback_data="TIME_3:30 PM")],]
    return InlineKeyboardMarkup(keyboard)

# --- دوال مساعدة أخرى ---
def get_predefined_user(telegram_id: str):
    ref = db.reference('/users')
    users = ref.get() or {}
    for user_data in users.values():
        if user_data and str(user_data.get("telegram_id", "")) == telegram_id:
            return user_data
    return None

def get_hr_telegram_id():
    ref = db.reference('/users')
    users = ref.get() or {}
    for user_data in users.values():
        if user_data and user_data.get("role") == "hr":
            return user_data.get("telegram_id")
    return None

# --- معالجات الأوامر الرئيسية والميزات الجديدة ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    predefined_user = get_predefined_user(str(user.id))
    keyboard = [
        [InlineKeyboardButton("🕒 إجازة ساعية", callback_data="start_hourly_leave")],
        [InlineKeyboardButton("🗓️ طلب إجازة", callback_data="start_full_day_leave")],
        [InlineKeyboardButton("💡 صندوق الاقتراحات", callback_data="start_suggestion")]
    ]
    message = f"أهلاً بك يا {user.first_name}."
    if predefined_user:
        role = predefined_user.get("role")
        if role == "hr":
            message += " أنت مسجل كمدير الموارد البشرية."
        elif role == "team_leader":
            message += " أنت مسجل كقائد فريق."
    
    await update.message.reply_text(message + "\n\nالرجاء اختيار الخدمة المطلوبة:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- بداية معالج محادثة صندوق الاقتراحات ---
async def start_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("أهلاً بك في صندوق الاقتراحات والشكاوى.\n\nالرجاء إدخال اسمك الكامل:")
    return SUGGESTION_ENTERING_NAME

async def suggestion_enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['suggestion_user_name'] = update.message.text
    await update.message.reply_text("شكراً لك. الآن تفضل بكتابة اقتراحك أو شكواك. سيتم إرسالها مباشرةً إلى مدير الموارد البشرية.")
    return SUGGESTION_ENTERING_MESSAGE

async def suggestion_enter_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    suggestion_message = update.message.text
    user_name = context.user_data.get('suggestion_user_name', 'موظف')
    user = update.effective_user
    
    # حفظ الاقتراح في Firebase
    suggestions_ref = db.reference('/suggestions')
    suggestions_ref.push({
        "employee_name": user_name,
        "employee_telegram_id": str(user.id),
        "message": suggestion_message,
        "submission_time": datetime.now().isoformat()
    })

    # إرسال الرسالة إلى مدير الموارد البشرية
    hr_chat_id = get_hr_telegram_id()
    if hr_chat_id:
        hr_message = (
            f"📬 رسالة جديدة في صندوق الاقتراحات 📬\n\n"
            f"**من الموظف:** {user_name}\n\n"
            f"**نص الرسالة:**\n{suggestion_message}"
        )
        try:
            await context.bot.send_message(chat_id=hr_chat_id, text=hr_message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to send suggestion to HR: {e}")

    await update.message.reply_text("✅ شكراً لك. تم إرسال رسالتك بنجاح إلى الإدارة.")
    
    context.user_data.clear()
    return ConversationHandler.END

# ... (بقية معالجات الإجازات تبقى كما هي)
# ... (Full Day & Hourly Leave Conversation Handlers)

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles cancelling any conversation."""
    message = "تم إلغاء العملية."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=message)
    else:
        await update.message.reply_text(text=message)
    
    context.user_data.clear()
    return ConversationHandler.END

def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # معالج محادثة صندوق الاقتراحات
    suggestion_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_suggestion, pattern="^start_suggestion$")],
        states={
            SUGGESTION_ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggestion_enter_name)],
            SUGGESTION_ENTERING_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggestion_enter_message)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)], # يمكن للمستخدم كتابة /cancel
    )
    
    # ... (بقية معالجات المحادثات تبقى كما هي)
    full_day_leave_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_full_day_leave, pattern="^start_full_day_leave$")],
        states={
            FD_ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, fd_enter_name)],
            FD_ENTERING_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, fd_enter_reason)],
            FD_CHOOSING_DURATION_TYPE: [CallbackQueryHandler(fd_choose_duration_type, pattern="^duration_")],
            FD_SELECTING_DATES: [CallbackQueryHandler(fd_calendar_callback, pattern="^CAL_")],
            FD_CONFIRMING_LEAVE: [CallbackQueryHandler(confirm_full_day_leave, pattern="^confirm_send$")],
        },
        fallbacks=[CallbackQueryHandler(cancel_conversation, pattern="^cancel$")],
    )
    
    hourly_leave_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_hourly_leave, pattern="^start_hourly_leave$")],
        states={
            HL_CHOOSING_TYPE: [CallbackQueryHandler(choose_hourly_type, pattern="^hourly_")],
            HL_SELECTING_TIME: [CallbackQueryHandler(select_time, pattern="^TIME_")],
            HL_ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_hourly_name)],
            HL_ENTERING_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_hourly_reason)],
            HL_CONFIRMING_LEAVE: [CallbackQueryHandler(confirm_hourly_leave, pattern="^confirm_send$")],
        },
        fallbacks=[CallbackQueryHandler(cancel_conversation, pattern="^cancel$")],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(full_day_leave_conv)
    application.add_handler(hourly_leave_conv)
    application.add_handler(suggestion_conv) # إضافة المعالج الجديد
    application.add_handler(CallbackQueryHandler(hr_action_handler, pattern="^(approve|reject)_(fd|hourly)_"))

    print("Bot is running with Suggestion Box feature...")
    application.run_polling()

# ... (بقية الدوال تبقى كما هي)
# ... (fd_enter_name, hr_action_handler, main, etc.)

if __name__ == "__main__":
    main()
