# -*- coding: utf-8 -*-
import logging
from datetime import datetime, date, time, timedelta
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

# --- قسم الإعدادات ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8022986919:AAEPa_fgGad_MbmR5i35ZmBLWGgC8G1xmIo") 
FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL", "https://hr-myslide-default-rtdb.europe-west1.firebasedatabase.app") 

# --- إعداد اتصال Firebase ---
try:
    firebase_creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if firebase_creds_json:
        cred_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(cred_dict)
    else:
        cred = credentials.Certificate("firebase-credentials.json")

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DATABASE_URL})
    print("Firebase connected successfully!")
except Exception as e:
    print(f"Error connecting to Firebase: {e}")
    exit()

# إعداد التسجيل
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- تعريف حالات المحادثة ---
# إجازة يومية
(FD_ENTERING_NAME, FD_ENTERING_REASON, FD_CHOOSING_DURATION_TYPE, FD_SELECTING_DATES, FD_CONFIRMING_LEAVE) = range(5)
# إجازة ساعية
(HL_CHOOSING_TYPE, HL_SELECTING_TIME, HL_ENTERING_NAME, HL_ENTERING_REASON, HL_CONFIRMING_LEAVE) = range(5, 10)
# سبب الرفض
AWAITING_REJECTION_REASON = range(10, 11)[0]


# --- دوال مساعدة ---
# (دوال التقويم والوقت تبقى كما هي)
def create_advanced_calendar(year: int, month: int, selection_mode: str, selected_dates: list) -> InlineKeyboardMarkup:
    # ... (code for calendar remains the same)
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
    # ... (code for time keyboard remains the same)
    keyboard = []
    if leave_type == 'late':
        keyboard = [[InlineKeyboardButton("9:30 AM", callback_data="TIME_9:30 AM"), InlineKeyboardButton("10:00 AM", callback_data="TIME_10:00 AM")],[InlineKeyboardButton("10:30 AM", callback_data="TIME_10:30 AM"), InlineKeyboardButton("11:00 AM", callback_data="TIME_11:00 AM")],[InlineKeyboardButton("11:30 AM", callback_data="TIME_11:30 AM"), InlineKeyboardButton("12:00 PM", callback_data="TIME_12:00 PM")],[InlineKeyboardButton("12:30 PM", callback_data="TIME_12:30 PM"), InlineKeyboardButton("1:00 PM", callback_data="TIME_1:00 PM")],[InlineKeyboardButton("1:30 PM", callback_data="TIME_1:30 PM"), InlineKeyboardButton("2:00 PM", callback_data="TIME_2:00 PM")],]
    elif leave_type == 'early':
        keyboard = [[InlineKeyboardButton("11:00 AM", callback_data="TIME_11:00 AM"), InlineKeyboardButton("11:30 AM", callback_data="TIME_11:30 AM")],[InlineKeyboardButton("12:00 PM", callback_data="TIME_12:00 PM"), InlineKeyboardButton("12:30 PM", callback_data="TIME_12:30 PM")],[InlineKeyboardButton("1:00 PM", callback_data="TIME_1:00 PM"), InlineKeyboardButton("1:30 PM", callback_data="TIME_1:30 PM")],[InlineKeyboardButton("2:00 PM", callback_data="TIME_2:00 PM"), InlineKeyboardButton("2:30 PM", callback_data="TIME_2:30 PM")],[InlineKeyboardButton("3:00 PM", callback_data="TIME_3:00 PM"), InlineKeyboardButton("3:30 PM", callback_data="TIME_3:30 PM")],]
    return InlineKeyboardMarkup(keyboard)

def get_predefined_user(telegram_id: str):
    ref = db.reference('/users')
    users = ref.get() or {}
    for user_data in users.values():
        if user_data and str(user_data.get("telegram_id", "")) == telegram_id:
            return user_data
    return None

def get_all_managers_ids():
    """الحصول على قائمة بمعرفات المدراء وقادة الفرق."""
    manager_ids = []
    ref = db.reference('/users')
    users = ref.get() or {}
    for user_data in users.values():
        role = user_data.get("role")
        if user_data and (role == "team_leader" or role == "hr"):
            manager_ids.append(user_data.get("telegram_id"))
    return list(set(manager_ids)) # إزالة التكرار

def get_hr_telegram_id():
    ref = db.reference('/users')
    users = ref.get() or {}
    for user_data in users.values():
        if user_data and user_data.get("role") == "hr":
            return user_data.get("telegram_id")
    return None

# --- معالج الأوامر الرئيسية والميزات الجديدة ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    predefined_user = get_predefined_user(str(user.id))
    
    keyboard = []
    message = f"أهلاً بك يا {user.first_name}."

    if predefined_user:
        role = predefined_user.get("role")
        if role == "hr":
            message += " أنت مسجل كمدير الموارد البشرية."
            keyboard.append([InlineKeyboardButton("📋 الطلبات المعلقة", callback_data="hr_pending_requests")])
        elif role == "team_leader":
            message += " أنت مسجل كقائد فريق."
    
    # الأزرار المشتركة للجميع
    keyboard.extend([
        [InlineKeyboardButton("🕒 إجازة ساعية", callback_data="start_hourly_leave")],
        [InlineKeyboardButton("🗓️ طلب إجازة يومية", callback_data="start_full_day_leave")],
        [InlineKeyboardButton("📂 طلباتي", callback_data="my_requests")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup)

# ... (كل معالجات المحادثات السابقة تبقى كما هي)
# ... (Full Day Leave Conversation Handlers: start_full_day_leave, fd_enter_name, etc.)
# ... (Hourly Leave Conversation Handlers: start_hourly_leave, choose_hourly_type, etc.)

async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض للموظف سجل طلباته."""
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    
    message = "📜 **سجل طلباتك:**\n\n"
    found_requests = False

    # البحث في الإجازات اليومية
    fd_leaves_ref = db.reference('/full_day_leaves').order_by_child('employee_telegram_id').equal_to(user_id).get()
    if fd_leaves_ref:
        found_requests = True
        message += "--- **إجازات يومية** ---\n"
        for key, req in fd_leaves_ref.items():
            message += f"▫️ **المدة:** {req.get('date_info', 'N/A')}\n"
            message += f"   **الحالة:** {req.get('status', 'N/A')}\n"
            if req.get('status') == 'rejected' and req.get('rejection_reason'):
                message += f"   **سبب الرفض:** {req.get('rejection_reason')}\n"
            message += "\n"

    # البحث في الإجازات الساعية
    hl_leaves_ref = db.reference('/hourly_leaves').order_by_child('employee_telegram_id').equal_to(user_id).get()
    if hl_leaves_ref:
        found_requests = True
        message += "--- **إجازات ساعية** ---\n"
        for key, req in hl_leaves_ref.items():
            message += f"▫️ **التفاصيل:** {req.get('time_info', 'N/A')}\n"
            message += f"   **التاريخ:** {req.get('date', 'N/A')}\n"
            message += f"   **الحالة:** {req.get('status', 'N/A')}\n"
            if req.get('status') == 'rejected' and req.get('rejection_reason'):
                message += f"   **سبب الرفض:** {req.get('rejection_reason')}\n"
            message += "\n"
            
    if not found_requests:
        message = "لم تقم بتقديم أي طلبات بعد."

    await query.edit_message_text(message, parse_mode='Markdown')

async def hr_pending_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض لمدير الموارد البشرية الطلبات المعلقة."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("جاري جلب الطلبات المعلقة...")
    found_requests = False

    # جلب الإجازات اليومية المعلقة
    fd_leaves_ref = db.reference('/full_day_leaves').order_by_child('status').equal_to('pending').get()
    if fd_leaves_ref:
        found_requests = True
        await query.message.reply_text("--- **طلبات الإجازة اليومية المعلقة** ---")
        for req_id, req in fd_leaves_ref.items():
            hr_message = (f"من: {req['employee_name']}\n"
                          f"السبب: {req['reason']}\n"
                          f"المدة: {req['date_info']}")
            keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_fd_{req_id}"), 
                         InlineKeyboardButton("❌ رفض", callback_data=f"reject_fd_{req_id}")]]
            await query.message.reply_text(hr_message, reply_markup=InlineKeyboardMarkup(keyboard))

    # جلب الإجازات الساعية المعلقة
    hl_leaves_ref = db.reference('/hourly_leaves').order_by_child('status').equal_to('pending').get()
    if hl_leaves_ref:
        found_requests = True
        await query.message.reply_text("--- **طلبات الإجازة الساعية المعلقة** ---")
        for req_id, req in hl_leaves_ref.items():
            hr_message = (f"من: {req['employee_name']}\n"
                          f"السبب: {req['reason']}\n"
                          f"التفاصيل: {req['time_info']}")
            keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_hourly_{req_id}"), 
                         InlineKeyboardButton("❌ رفض", callback_data=f"reject_hourly_{req_id}")]]
            await query.message.reply_text(hr_message, reply_markup=InlineKeyboardMarkup(keyboard))

    if not found_requests:
        await query.message.reply_text("لا توجد طلبات معلقة حالياً.")

# --- آلية سبب الرفض ---
async def start_rejection_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ محادثة إدخال سبب الرفض."""
    query = update.callback_query
    await query.answer()
    
    # تخزين معلومات الطلب للمرحلة التالية
    context.user_data['rejection_info'] = query.data 
    
    await query.edit_message_text("الرجاء إدخال سبب الرفض (أو أرسل /skip للتجاوز).")
    return AWAITING_REJECTION_REASON

async def save_rejection_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يحفظ سبب الرفض ويكمل عملية الرفض."""
    reason = update.message.text
    
    # استرجاع معلومات الطلب
    rejection_info = context.user_data.pop('rejection_info', None)
    if not rejection_info:
        await update.message.reply_text("حدث خطأ ما. الرجاء المحاولة مرة أخرى.")
        return ConversationHandler.END

    _, leave_type, request_id = rejection_info.split("_", 2)
    db_path = f"/{leave_type}_leaves/{request_id}"
    leave_ref = db.reference(db_path)
    
    # تحديث قاعدة البيانات
    leave_ref.update({"status": "rejected", "rejection_reason": reason})
    
    # إعلام الموظف
    leave_request = leave_ref.get()
    date_info = leave_request.get('date_info', leave_request.get('time_info', 'N/A'))
    await context.bot.send_message(
        chat_id=leave_request["employee_telegram_id"],
        text=f"للأسف، تم رفض طلب إجازتك لـِ: {date_info}.\n**السبب:** {reason}"
    )
    
    await update.message.reply_text(f"تم تسجيل سبب الرفض وإبلاغ الموظف.")
    return ConversationHandler.END
    
async def skip_rejection_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يتجاوز إدخال سبب الرفض."""
    # نفس منطق الحفظ ولكن بدون سبب
    rejection_info = context.user_data.pop('rejection_info', None)
    if not rejection_info: return ConversationHandler.END
    _, leave_type, request_id = rejection_info.split("_", 2)
    db_path = f"/{leave_type}_leaves/{request_id}"
    leave_ref = db.reference(db_path)
    leave_ref.update({"status": "rejected"})
    leave_request = leave_ref.get()
    date_info = leave_request.get('date_info', leave_request.get('time_info', 'N/A'))
    await context.bot.send_message(
        chat_id=leave_request["employee_telegram_id"],
        text=f"للأسف، تم رفض طلب إجازتك لـِ: {date_info}."
    )
    await update.message.reply_text("تم رفض الطلب.")
    return ConversationHandler.END


# --- المهام المجدولة (الإشعارات التلقائية) ---
async def daily_on_leave_summary(context: ContextTypes.DEFAULT_TYPE):
    """يرسل ملخصاً يومياً بالموظفين المجازين."""
    logger.info("Running daily on-leave summary job.")
    today_str = date.today().strftime('%d/%m/%Y')
    on_leave_today = []

    # البحث في الإجازات اليومية
    all_leaves = db.reference('/full_day_leaves').order_by_child('status').equal_to('approved').get()
    if all_leaves:
        for req in all_leaves.values():
            # هذا منطق بسيط، يمكن تطويره ليدعم النطاقات والأيام المتفرقة بدقة
            if today_str in req.get('date_info', ''):
                on_leave_today.append(req['employee_name'])
    
    if not on_leave_today:
        logger.info("No employees on leave today.")
        return

    message = f"☀️ **تقرير الإجازات اليومي ({today_str})** ☀️\n\n"
    message += "الموظفون التاليون في إجازة اليوم:\n"
    for name in on_leave_today:
        message += f"- {name}\n"
    
    manager_ids = get_all_managers_ids()
    for manager_id in manager_ids:
        try:
            await context.bot.send_message(chat_id=manager_id, text=message)
        except Exception as e:
            logger.error(f"Failed to send daily summary to {manager_id}: {e}")

async def send_leave_reminders(context: ContextTypes.DEFAULT_TYPE):
    """يرسل تذكيرات للموظفين الذين تبدأ إجازتهم غداً."""
    logger.info("Running leave reminder job.")
    tomorrow_str = (date.today() + timedelta(days=1)).strftime('%d/%m/%Y')
    
    all_leaves = db.reference('/full_day_leaves').order_by_child('status').equal_to('approved').get()
    if all_leaves:
        for req in all_leaves.values():
            # هذا منطق بسيط، يمكن تطويره ليكون أكثر دقة
            if req.get('date_info', '').startswith(tomorrow_str) or req.get('date_info', '').startswith(f"من {tomorrow_str}"):
                try:
                    await context.bot.send_message(
                        chat_id=req['employee_telegram_id'],
                        text=f"👋 تذكير: إجازتك تبدأ غداً! نتمنى لك وقتاً ممتعاً."
                    )
                except Exception as e:
                    logger.error(f"Failed to send reminder to {req['employee_telegram_id']}: {e}")


def main() -> None:
    """يبدأ البوت ويقوم بجدولة المهام."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # إضافة المهام المجدولة
    job_queue = application.job_queue
    # تحديد المنطقة الزمنية لتشغيل المهام في الوقت الصحيح
    tz = pytz.timezone('Asia/Riyadh') 
    job_queue.run_daily(daily_on_leave_summary, time=time(8, 0, 0, tzinfo=tz)) # 8:00 صباحاً
    job_queue.run_daily(send_leave_reminders, time=time(18, 0, 0, tzinfo=tz)) # 6:00 مساءً

    # ... (بقية المعالجات تبقى كما هي)
    # ... (Full Day & Hourly Leave Conversations)
    
    # معالج سبب الرفض
    rejection_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_rejection_flow, pattern="^reject_")],
        states={
            AWAITING_REJECTION_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_rejection_reason),
                CommandHandler('skip', skip_rejection_reason)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)], # يمكن تعديل هذا
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(my_requests, pattern="^my_requests$"))
    application.add_handler(CallbackQueryHandler(hr_pending_requests, pattern="^hr_pending_requests$"))

    # إضافة معالجات المحادثات الرئيسية
    # application.add_handler(full_day_leave_conv)
    # application.add_handler(hourly_leave_conv)
    
    # تعديل معالج موافقة مدير الموارد البشرية، وربط الرفض بالمحادثة الجديدة
    application.add_handler(CallbackQueryHandler(hr_action_handler, pattern="^approve_"))
    application.add_handler(rejection_conv)


    print("Bot is running with PRO features...")
    application.run_polling()

if __name__ == "__main__":
    main()
