# -*- coding: utf-8 -*-
import logging
from datetime import datetime, date, timedelta, time
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
(
    MAIN_MENU,
    # إجازة يومية
    FD_ENTERING_NAME, FD_ENTERING_REASON, FD_CHOOSING_DURATION_TYPE, FD_SELECTING_DATES, FD_CONFIRMING_LEAVE,
    # إجازة ساعية
    HL_CHOOSING_TYPE, HL_SELECTING_TIME, HL_ENTERING_NAME, HL_ENTERING_REASON, HL_CONFIRMING_LEAVE,
    # صندوق الاقتراحات
    SUGGESTION_ENTERING_MESSAGE, SUGGESTION_CHOOSE_ANONYMITY,
    # لوحة تحكم المدير
    MANAGER_CHOOSING_VIEW,
    # سبب الرفض
    AWAITING_REJECTION_REASON
) = range(15) # التصحيح: تم تغيير القيمة من 16 إلى 15


# --- دوال إنشاء التقويم والوقت ---
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
    
    control_row = []
    if selection_mode == 'multiple' and selected_dates:
        control_row.append(InlineKeyboardButton("✅ تم الاختيار", callback_data="CAL_DONE"))
    control_row.append(InlineKeyboardButton("⬅️ عودة", callback_data="back_to_duration_type"))
    keyboard.append(control_row)
    
    return InlineKeyboardMarkup(keyboard)

def create_time_keyboard(leave_type: str) -> InlineKeyboardMarkup:
    keyboard = []
    if leave_type == 'late':
        keyboard = [[InlineKeyboardButton("9:30 AM", callback_data="TIME_9:30 AM"), InlineKeyboardButton("10:00 AM", callback_data="TIME_10:00 AM")],[InlineKeyboardButton("10:30 AM", callback_data="TIME_10:30 AM"), InlineKeyboardButton("11:00 AM", callback_data="TIME_11:00 AM")],[InlineKeyboardButton("11:30 AM", callback_data="TIME_11:30 AM"), InlineKeyboardButton("12:00 PM", callback_data="TIME_12:00 PM")],[InlineKeyboardButton("12:30 PM", callback_data="TIME_12:30 PM"), InlineKeyboardButton("1:00 PM", callback_data="TIME_1:00 PM")],[InlineKeyboardButton("1:30 PM", callback_data="TIME_1:30 PM"), InlineKeyboardButton("2:00 PM", callback_data="TIME_2:00 PM")],]
    elif leave_type == 'early':
        keyboard = [[InlineKeyboardButton("11:00 AM", callback_data="TIME_11:00 AM"), InlineKeyboardButton("11:30 AM", callback_data="TIME_11:30 AM")],[InlineKeyboardButton("12:00 PM", callback_data="TIME_12:00 PM"), InlineKeyboardButton("12:30 PM", callback_data="TIME_12:30 PM")],[InlineKeyboardButton("1:00 PM", callback_data="TIME_1:00 PM"), InlineKeyboardButton("1:30 PM", callback_data="TIME_1:30 PM")],[InlineKeyboardButton("2:00 PM", callback_data="TIME_2:00 PM"), InlineKeyboardButton("2:30 PM", callback_data="TIME_2:30 PM")],[InlineKeyboardButton("3:00 PM", callback_data="TIME_3:00 PM"), InlineKeyboardButton("3:30 PM", callback_data="TIME_3:30 PM")],]
    
    keyboard.append([InlineKeyboardButton("⬅️ عودة", callback_data="back_to_hourly_type")])
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

def get_all_managers_ids():
    manager_ids = []
    ref = db.reference('/users')
    users = ref.get() or {}
    for user_data in users.values():
        role = user_data.get("role")
        if user_data and (role == "team_leader" or role == "hr"):
            manager_ids.append(user_data.get("telegram_id"))
    return list(set(manager_ids))

# --- معالجات الأوامر الرئيسية والميزات الجديدة ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    predefined_user = get_predefined_user(str(user.id))
    
    keyboard = []
    message = f"أهلاً بك يا {user.first_name}."

    if predefined_user and predefined_user.get("role") in ["hr", "team_leader"]:
        keyboard.append([InlineKeyboardButton("📋 عرض طلبات الإجازات", callback_data="manager_view_requests")])
        if predefined_user.get("role") == "hr":
            message += " أنت مسجل كمدير الموارد البشرية."
        else:
            message += " أنت مسجل كقائد فريق."
    
    keyboard.extend([
        [InlineKeyboardButton("🕒 إجازة ساعية", callback_data="start_hourly_leave")],
        [InlineKeyboardButton("🗓️ طلب إجازة", callback_data="start_full_day_leave")],
        [InlineKeyboardButton("💡 صندوق الاقتراحات", callback_data="start_suggestion")]
    ])
    
    if not predefined_user:
         keyboard.append([InlineKeyboardButton("📂 طلباتي", callback_data="my_requests")])

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(message + "\n\nالرجاء اختيار الخدمة المطلوبة:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(message + "\n\nالرجاء اختيار الخدمة المطلوبة:", reply_markup=InlineKeyboardMarkup(keyboard))

async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    message = "📜 **سجل طلباتك:**\n\n"
    found_requests = False
    
    all_leaves_ref = db.reference('/').get()
    
    fd_leaves = all_leaves_ref.get('full_day_leaves', {})
    user_fd_leaves = {k: v for k, v in fd_leaves.items() if v.get('employee_telegram_id') == user_id}
    if user_fd_leaves:
        found_requests = True
        message += "--- **إجازات يومية** ---\n"
        for _, req in user_fd_leaves.items():
            message += f"▫️ **المدة:** {req.get('date_info', 'N/A')}\n"
            message += f"   **الحالة:** {req.get('status', 'N/A')}\n"
            if req.get('status') == 'rejected' and req.get('rejection_reason'):
                message += f"   **سبب الرفض:** {req.get('rejection_reason')}\n"
            message += "\n"

    hl_leaves = all_leaves_ref.get('hourly_leaves', {})
    user_hl_leaves = {k: v for k, v in hl_leaves.items() if v.get('employee_telegram_id') == user_id}
    if user_hl_leaves:
        found_requests = True
        message += "--- **إجازات ساعية** ---\n"
        for _, req in user_hl_leaves.items():
            message += f"▫️ **التفاصيل:** {req.get('time_info', 'N/A')}\n"
            message += f"   **التاريخ:** {req.get('date', 'N/A')}\n"
            message += f"   **الحالة:** {req.get('status', 'N/A')}\n"
            if req.get('status') == 'rejected' and req.get('rejection_reason'):
                message += f"   **سبب الرفض:** {req.get('rejection_reason')}\n"
            message += "\n"
            
    if not found_requests:
        message = "لم تقم بتقديم أي طلبات بعد."
        
    keyboard = [[InlineKeyboardButton("⬅️ عودة للقائمة الرئيسية", callback_data="back_to_main")]]
    await query.edit_message_text(message, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def manager_view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("⏳ الطلبات المعلقة", callback_data="view_pending")],
        [InlineKeyboardButton("✅ الطلبات الموافق عليها", callback_data="view_approved")],
        [InlineKeyboardButton("❌ الطلبات المرفوضة", callback_data="view_rejected")],
        [InlineKeyboardButton("⬅️ عودة للقائمة الرئيسية", callback_data="back_to_main")]
    ]
    await query.edit_message_text("الرجاء اختيار نوع الطلبات التي تريد عرضها:", reply_markup=InlineKeyboardMarkup(keyboard))

async def display_requests_by_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    status = query.data.split('_')[1] 
    
    user_id = str(query.from_user.id)
    user_info = get_predefined_user(user_id)
    is_hr = user_info and user_info.get('role') == 'hr'
    
    await query.edit_message_text(f"جاري جلب الطلبات ({status})...")
    found_requests = False

    fd_leaves_ref = db.reference('/full_day_leaves').order_by_child('status').equal_to(status).get() or {}
    if fd_leaves_ref:
        found_requests = True
        await query.message.reply_text(f"--- **طلبات الإجازة اليومية ({status})** ---")
        for req_id, req in fd_leaves_ref.items():
            message = (f"من: {req['employee_name']}\n"
                       f"السبب: {req['reason']}\n"
                       f"المدة: {req['date_info']}")
            keyboard = None
            if status == 'pending' and is_hr:
                keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_fd_{req_id}"), 
                             InlineKeyboardButton("❌ رفض", callback_data=f"reject_fd_{req_id}")]]
            await query.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

    hl_leaves_ref = db.reference('/hourly_leaves').order_by_child('status').equal_to(status).get() or {}
    if hl_leaves_ref:
        found_requests = True
        await query.message.reply_text(f"--- **طلبات الإجازة الساعية ({status})** ---")
        for req_id, req in hl_leaves_ref.items():
            message = (f"من: {req['employee_name']}\n"
                       f"السبب: {req['reason']}\n"
                       f"التفاصيل: {req['time_info']}")
            keyboard = None
            if status == 'pending' and is_hr:
                keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_hourly_{req_id}"), 
                             InlineKeyboardButton("❌ رفض", callback_data=f"reject_hourly_{req_id}")]]
            await query.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
    
    if not found_requests:
        await query.message.reply_text(f"لا توجد طلبات ({status}) حالياً.")

    await query.message.reply_text("للعودة لقائمة عرض الطلبات:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ عودة", callback_data="manager_view_requests")]]))

# --- بداية معالج محادثة صندوق الاقتراحات ---
async def start_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ عودة للقائمة الرئيسية", callback_data="back_to_main")]]
    await query.edit_message_text("أهلاً بك في صندوق الاقتراحات والشكاوى.\n\nتفضل بكتابة اقتراحك أو شكواك. سيتم إرسالها إلى مدير الموارد البشرية.", reply_markup=InlineKeyboardMarkup(keyboard))
    return SUGGESTION_ENTERING_MESSAGE

async def suggestion_enter_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['suggestion_message'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("👤 إظهار اسمي", callback_data="suggestion_named")],
        [InlineKeyboardButton("🔒 إرسال كرسالة مجهولة", callback_data="suggestion_anonymous")],
        [InlineKeyboardButton("⬅️ عودة", callback_data="back_to_suggestion_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("شكراً لك. كيف تريد إرسال هذه الرسالة؟", reply_markup=reply_markup)
    return SUGGESTION_CHOOSE_ANONYMITY

async def suggestion_choose_anonymity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == 'back_to_suggestion_start':
        await start_suggestion(update, context)
        return SUGGESTION_ENTERING_MESSAGE

    is_anonymous = query.data == 'suggestion_anonymous'
    suggestion_message = context.user_data.get('suggestion_message')
    user = update.effective_user
    sender_name = "موظف مجهول" if is_anonymous else user.full_name
    
    db.reference('/suggestions').push({
        "sender_name": sender_name,
        "sender_telegram_id": str(user.id),
        "is_anonymous": is_anonymous,
        "message": suggestion_message,
        "submission_time": datetime.now().isoformat()
    })

    hr_chat_id = get_hr_telegram_id()
    if hr_chat_id:
        hr_message = (f"📬 رسالة جديدة في صندوق الاقتراحات 📬\n\n"
                      f"**من:** {sender_name}\n\n"
                      f"**نص الرسالة:**\n{suggestion_message}")
        try:
            await context.bot.send_message(chat_id=hr_chat_id, text=hr_message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to send suggestion to HR: {e}")

    await query.edit_message_text("✅ شكراً لك. تم إرسال رسالتك بنجاح إلى الإدارة.")
    context.user_data.clear()
    return ConversationHandler.END

# --- بداية معالج محادثة الإجازة الساعية ---
async def start_hourly_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🌅 بداية الدوام (تأخير)", callback_data="hourly_late")],
        [InlineKeyboardButton("🌇 نهاية الدوام (مغادرة مبكرة)", callback_data="hourly_early")],
        [InlineKeyboardButton("⬅️ عودة للقائمة الرئيسية", callback_data="back_to_main")]
    ]
    await query.edit_message_text("اختر نوع الإجازة الساعية:", reply_markup=InlineKeyboardMarkup(keyboard))
    return HL_CHOOSING_TYPE

async def choose_hourly_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == 'back_to_main':
        await start(update, context)
        return ConversationHandler.END

    leave_type = query.data.split('_')[1] 
    context.user_data['hourly_leave_type'] = leave_type
    message = "متى ستصل إلى الدوام؟" if leave_type == 'late' else "متى ستغادر من الدوام؟"
    await query.edit_message_text(text=message, reply_markup=create_time_keyboard(leave_type))
    return HL_SELECTING_TIME

async def select_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == 'back_to_hourly_type':
        await start_hourly_leave(update, context)
        return HL_CHOOSING_TYPE

    selected_time = query.data.split('_', 1)[1]
    context.user_data['selected_time'] = selected_time
    type_text = "تأخير صباحي" if context.user_data['hourly_leave_type'] == 'late' else "مغادرة مبكرة"
    await query.edit_message_text(f"تم اختيار: {type_text} - الساعة {selected_time}.")
    await query.message.reply_text("الرجاء إدخال اسمك الكامل: (للإلغاء أرسل /cancel)")
    return HL_ENTERING_NAME

async def enter_hourly_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['employee_name'] = update.message.text
    await update.message.reply_text("شكراً لك. الآن الرجاء إدخال سبب الإجازة الساعية:")
    return HL_ENTERING_REASON

async def enter_hourly_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['hourly_reason'] = update.message.text
    type_text = "الوصول الساعة" if context.user_data['hourly_leave_type'] == 'late' else "المغادرة الساعة"
    summary = (f"--- ملخص طلب إجازة ساعية ---\n"
               f"اسم الموظف: {context.user_data['employee_name']}\n"
               f"السبب: {context.user_data['hourly_reason']}\n"
               f"التاريخ: {date.today().strftime('%d/%m/%Y')}\n"
               f"الوقت: {type_text} {context.user_data['selected_time']}\n\n"
               "هل تريد تأكيد الطلب؟")
    keyboard = [[InlineKeyboardButton("✅ تأكيد", callback_data="confirm_send"), InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]]
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard))
    return HL_CONFIRMING_LEAVE

async def confirm_hourly_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "cancel": return await cancel_conversation(update, context)
    user = update.effective_user
    leaves_ref = db.reference('/hourly_leaves')
    new_leave_ref = leaves_ref.push()
    request_id = new_leave_ref.key
    type_text = "تأخير صباحي" if context.user_data['hourly_leave_type'] == 'late' else "مغادرة مبكرة"
    new_leave_ref.set({ "employee_name": context.user_data['employee_name'], "employee_telegram_id": str(user.id), "reason": context.user_data['hourly_reason'], "date": date.today().strftime('%d/%m/%Y'), "time_info": f"{type_text} - {context.user_data['selected_time']}", "status": "pending", "request_time": datetime.now().isoformat()})
    hr_chat_id = get_hr_telegram_id()
    if not hr_chat_id:
        await query.edit_message_text("خطأ: لا يمكن العثور على مدير الموارد البشرية.")
        return ConversationHandler.END
    hr_message = (f"📣 طلب إجازة ساعية جديد 📣\n\n"
                  f"من الموظف: {context.user_data['employee_name']}\n"
                  f"السبب: {context.user_data['hourly_reason']}\n"
                  f"التفاصيل: {type_text} اليوم الساعة {context.user_data['selected_time']}\n\n"
                  "الرجاء اتخاذ إجراء:")
    keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_hourly_{request_id}"), InlineKeyboardButton("❌ رفض", callback_data=f"reject_hourly_{request_id}")]]
    try:
        await context.bot.send_message(chat_id=hr_chat_id, text=hr_message, reply_markup=InlineKeyboardMarkup(keyboard))
        await query.edit_message_text("✅ تم إرسال طلبك بنجاح.")
    except Exception as e:
        logger.error(f"Failed to send hourly leave to HR: {e}")
        await query.edit_message_text("حدث خطأ أثناء إرسال الطلب.")
    context.user_data.clear()
    return ConversationHandler.END

# --- بداية معالج محادثة الإجازة اليومية ---
async def start_full_day_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ عودة للقائمة الرئيسية", callback_data="back_to_main")]]
    await query.edit_message_text("حسناً، لطلب إجازة يوم كامل أو أكثر، الرجاء إدخال اسمك الكامل:", reply_markup=InlineKeyboardMarkup(keyboard))
    return FD_ENTERING_NAME

async def fd_enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['employee_name'] = update.message.text
    await update.message.reply_text("شكراً لك. الآن الرجاء إدخال سبب الإجازة:")
    return FD_ENTERING_REASON

async def fd_enter_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['leave_reason'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🗓️ يوم واحد", callback_data="duration_single")],
        [InlineKeyboardButton("🔁 أيام متتالية", callback_data="duration_range")],
        [InlineKeyboardButton("➕ أيام متفرقة", callback_data="duration_multiple")],
        [InlineKeyboardButton("⬅️ عودة", callback_data="back_to_fd_name")]
    ]
    await update.message.reply_text("تم تسجيل السبب. الآن، كيف هي مدة إجازتك؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return FD_CHOOSING_DURATION_TYPE

async def fd_choose_duration_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "back_to_fd_name":
        await query.edit_message_text("الرجاء إدخال اسمك الكامل مرة أخرى:")
        return FD_ENTERING_NAME

    duration_type = query.data.split('_')[1]
    context.user_data['duration_type'] = duration_type
    context.user_data['selected_dates'] = []
    today = date.today()
    message = "الرجاء اختيار تاريخ الإجازة:"
    if duration_type == 'range': message = "الرجاء اختيار تاريخ **البدء**:"
    elif duration_type == 'multiple': message = "اختر الأيام ثم اضغط 'تم الاختيار':"
    await query.edit_message_text(text=message, reply_markup=create_advanced_calendar(today.year, today.month, duration_type, []))
    return FD_SELECTING_DATES

async def fd_calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    callback_data = query.data

    if callback_data == "back_to_duration_type":
        keyboard = [
            [InlineKeyboardButton("🗓️ يوم واحد", callback_data="duration_single")],
            [InlineKeyboardButton("🔁 أيام متتالية", callback_data="duration_range")],
            [InlineKeyboardButton("➕ أيام متفرقة", callback_data="duration_multiple")],
            [InlineKeyboardButton("⬅️ عودة", callback_data="back_to_fd_name")]
        ]
        await query.edit_message_text("كيف هي مدة إجازتك؟", reply_markup=InlineKeyboardMarkup(keyboard))
        return FD_CHOOSING_DURATION_TYPE

    parts = callback_data.split("_")
    action = parts[1]
    duration_type = context.user_data.get('duration_type')
    selected_dates = context.user_data.get('selected_dates', [])
    if action == "DAY":
        year, month, day = map(int, parts[2:])
        selected_day = date(year, month, day)
        if duration_type == 'single':
            context.user_data['selected_dates'] = [selected_day]
            return await show_fd_confirmation(query, context)
        elif duration_type == 'range':
            if not selected_dates:
                selected_dates.append(selected_day)
                await query.edit_message_text(f"تاريخ البدء: {selected_day.strftime('%d/%m/%Y')}\n\nاختر تاريخ **الانتهاء**:", reply_markup=create_advanced_calendar(year, month, duration_type, selected_dates))
                return FD_SELECTING_DATES
            else:
                if selected_day < selected_dates[0]: return FD_SELECTING_DATES
                selected_dates.append(selected_day)
                return await show_fd_confirmation(query, context)
        elif duration_type == 'multiple':
            if selected_day in selected_dates: selected_dates.remove(selected_day)
            else: selected_dates.append(selected_day)
            await query.edit_message_text("اختر الأيام ثم اضغط 'تم الاختيار':", reply_markup=create_advanced_calendar(year, month, duration_type, selected_dates))
            return FD_SELECTING_DATES
    elif action == "NAV":
        year, month = map(int, parts[2:])
        await query.edit_message_text(query.message.text, reply_markup=create_advanced_calendar(year, month, duration_type, selected_dates))
        return FD_SELECTING_DATES
    elif action == "DONE":
        if not selected_dates: return FD_SELECTING_DATES
        return await show_fd_confirmation(query, context)
    return FD_SELECTING_DATES

async def show_fd_confirmation(query, context):
    duration_type = context.user_data['duration_type']
    selected_dates = sorted(context.user_data.get('selected_dates', []))
    if not selected_dates:
        await query.edit_message_text("لم يتم اختيار تاريخ. تم إلغاء الطلب.")
        return ConversationHandler.END
    date_info_str = ""
    if duration_type == 'single': date_info_str = selected_dates[0].strftime('%d/%m/%Y')
    elif duration_type == 'range': date_info_str = f"من {selected_dates[0].strftime('%d/%m/%Y')} إلى {selected_dates[-1].strftime('%d/%m/%Y')}"
    elif duration_type == 'multiple': date_info_str = ", ".join([d.strftime('%d/%m/%Y') for d in selected_dates])
    context.user_data['final_date_info'] = date_info_str
    summary = (f"--- ملخص الطلب ---\n"
               f"الاسم: {context.user_data['employee_name']}\n"
               f"السبب: {context.user_data['leave_reason']}\n"
               f"التاريخ/المدة: {date_info_str}\n\n"
               "هل تريد تأكيد الطلب؟")
    keyboard = [[InlineKeyboardButton("✅ تأكيد", callback_data="confirm_send"), InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]]
    await query.edit_message_text(text=summary, reply_markup=InlineKeyboardMarkup(keyboard))
    return FD_CONFIRMING_LEAVE

async def confirm_full_day_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "cancel": return await cancel_conversation(update, context)
    user = update.effective_user
    leaves_ref = db.reference('/full_day_leaves')
    new_leave_ref = leaves_ref.push()
    request_id = new_leave_ref.key
    new_leave_ref.set({"employee_name": context.user_data['employee_name'],"employee_telegram_id": str(user.id),"reason": context.user_data['leave_reason'],"date_info": context.user_data['final_date_info'],"status": "pending","request_time": datetime.now().isoformat(),})
    hr_chat_id = get_hr_telegram_id()
    if not hr_chat_id:
        await query.edit_message_text("خطأ: لا يمكن العثور على مدير الموارد البشرية.")
        return ConversationHandler.END
    hr_message = (f"📣 طلب إجازة جديد 📣\n\n"
                  f"من: {context.user_data['employee_name']}\n"
                  f"السبب: {context.user_data['leave_reason']}\n"
                  f"التاريخ/المدة: {context.user_data['final_date_info']}\n\n"
                  "الرجاء اتخاذ إجراء:")
    keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_fd_{request_id}"), InlineKeyboardButton("❌ رفض", callback_data=f"reject_fd_{request_id}")]]
    try:
        await context.bot.send_message(chat_id=hr_chat_id, text=hr_message, reply_markup=InlineKeyboardMarkup(keyboard))
        await query.edit_message_text("✅ تم إرسال طلبك بنجاح.")
    except Exception as e:
        logger.error(f"Failed to send full day leave to HR: {e}")
        await query.edit_message_text("حدث خطأ أثناء إرسال الطلب.")
    context.user_data.clear()
    return ConversationHandler.END

# --- معالج إجراءات الموارد البشرية (مطور) ---
async def hr_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    action = parts[0]
    leave_type = parts[1]
    request_id = parts[2]
    
    db_path = f"/{leave_type}_leaves/{request_id}"
    leave_ref = db.reference(db_path)
    leave_request = leave_ref.get()

    if not leave_request or leave_request.get("status") != "pending":
        await query.edit_message_text("هذا الطلب تمت معالجته بالفعل.")
        return

    date_info = leave_request.get('date_info', leave_request.get('time_info', 'غير محدد'))
    employee_name = leave_request.get('employee_name', 'موظف')

    if action == "approve":
        leave_ref.update({"status": "approved"})
        response_text = "✅ تمت الموافقة على الطلب."
        await context.bot.send_message(chat_id=leave_request["employee_telegram_id"], text=f"تهانينا! تمت الموافقة على طلب إجازتك لـِ: {date_info}.")
        
        leader_ids = get_all_managers_ids() # تم التعديل ليشمل المدراء أيضاً
        if leader_ids:
            notification_message = f"🔔 تنبيه: الموظف ({employee_name}) لديه إذن لـِ: {date_info}."
            
            for leader_id in leader_ids:
                try:
                    await context.bot.send_message(chat_id=leader_id, text=notification_message)
                except Exception as e:
                    logger.error(f"Failed to send notification to {leader_id}: {e}")
            response_text += "\nتم إرسال إشعار للمسؤولين."
    else: # reject
        leave_ref.update({"status": "rejected"})
        response_text = "❌ تم رفض الطلب."
        await context.bot.send_message(chat_id=leave_request["employee_telegram_id"], text=f"للأسف، تم رفض طلب إجازتك لـِ: {date_info}.")
    
    original_message = query.message.text
    await query.edit_message_text(text=f"{original_message}\n\n--- [ {response_text} ] ---")

# --- دالة الإلغاء العامة ---
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("تم إلغاء العملية.")
    else:
        await update.message.reply_text("تم إلغاء العملية.")
    context.user_data.clear()
    return ConversationHandler.END

def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    full_day_leave_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_full_day_leave, pattern="^start_full_day_leave$")],
        states={
            FD_ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, fd_enter_name)],
            FD_ENTERING_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, fd_enter_reason)],
            FD_CHOOSING_DURATION_TYPE: [CallbackQueryHandler(fd_choose_duration_type, pattern="^duration_|^back_to_fd_name$")],
            FD_SELECTING_DATES: [CallbackQueryHandler(fd_calendar_callback, pattern="^CAL_|^back_to_duration_type$")],
            FD_CONFIRMING_LEAVE: [CallbackQueryHandler(confirm_full_day_leave, pattern="^confirm_send$")],
        },
        fallbacks=[CallbackQueryHandler(cancel_conversation, pattern="^cancel$")],
    )
    
    hourly_leave_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_hourly_leave, pattern="^start_hourly_leave$")],
        states={
            HL_CHOOSING_TYPE: [CallbackQueryHandler(choose_hourly_type, pattern="^hourly_|^back_to_main$")],
            HL_SELECTING_TIME: [CallbackQueryHandler(select_time, pattern="^TIME_|^back_to_hourly_type$")],
            HL_ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_hourly_name)],
            HL_ENTERING_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_hourly_reason)],
            HL_CONFIRMING_LEAVE: [CallbackQueryHandler(confirm_hourly_leave, pattern="^confirm_send$")],
        },
        fallbacks=[CallbackQueryHandler(cancel_conversation, pattern="^cancel$")],
    )

    suggestion_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_suggestion, pattern="^start_suggestion$")],
        states={
            SUGGESTION_ENTERING_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, suggestion_enter_message)],
            SUGGESTION_CHOOSE_ANONYMITY: [CallbackQueryHandler(suggestion_choose_anonymity, pattern="^suggestion_|^back_to_suggestion_start$")],
        },
        fallbacks=[CallbackQueryHandler(cancel_conversation, pattern="^cancel$")],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(start, pattern="^back_to_main$"))
    application.add_handler(full_day_leave_conv)
    application.add_handler(hourly_leave_conv)
    application.add_handler(suggestion_conv)
    application.add_handler(CallbackQueryHandler(hr_action_handler, pattern="^(approve|reject)_(fd|hourly)_"))
    application.add_handler(CallbackQueryHandler(my_requests, pattern="^my_requests$"))
    application.add_handler(CallbackQueryHandler(manager_view_requests, pattern="^manager_view_requests$"))
    application.add_handler(CallbackQueryHandler(display_requests_by_status, pattern="^view_"))

    print("Bot is running with Back Button and Manager Dashboard...")
    application.run_polling()

if __name__ == "__main__":
    main()
