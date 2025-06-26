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

def get_all_managers_ids():
    manager_ids = []
    ref = db.reference('/users')
    users = ref.get() or {}
    for user_data in users.values():
        role = user_data.get("role")
        if user_data and (role == "team_leader" or role == "hr"):
            manager_ids.append(user_data.get("telegram_id"))
    return list(set(manager_ids)) 

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
    keyboard = []
    message = f"أهلاً بك يا {user.first_name}."
    if predefined_user:
        role = predefined_user.get("role")
        if role == "hr":
            message += " أنت مسجل كمدير الموارد البشرية."
            keyboard.append([InlineKeyboardButton("📋 الطلبات المعلقة", callback_data="hr_pending_requests")])
        elif role == "team_leader":
            message += " أنت مسجل كقائد فريق."
    keyboard.extend([
        [InlineKeyboardButton("🕒 إجازة ساعية", callback_data="start_hourly_leave")],
        [InlineKeyboardButton("🗓️ طلب إجازة يومية", callback_data="start_full_day_leave")],
        [InlineKeyboardButton("📂 طلباتي", callback_data="my_requests")]
    ])
    await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))

async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    message = "📜 **سجل طلباتك:**\n\n"
    found_requests = False
    fd_leaves_ref = db.reference('/full_day_leaves').order_by_child('employee_telegram_id').equal_to(user_id).get()
    if fd_leaves_ref:
        found_requests = True
        message += "--- **إجازات يومية** ---\n"
        for _, req in fd_leaves_ref.items():
            message += f"▫️ **المدة:** {req.get('date_info', 'N/A')}\n"
            message += f"   **الحالة:** {req.get('status', 'N/A')}\n"
            if req.get('status') == 'rejected' and req.get('rejection_reason'):
                message += f"   **سبب الرفض:** {req.get('rejection_reason')}\n"
            message += "\n"
    hl_leaves_ref = db.reference('/hourly_leaves').order_by_child('employee_telegram_id').equal_to(user_id).get()
    if hl_leaves_ref:
        found_requests = True
        message += "--- **إجازات ساعية** ---\n"
        for _, req in hl_leaves_ref.items():
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
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("جاري جلب الطلبات المعلقة...")
    found_requests = False
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

# --- آلية الإجازة الساعية ---
async def start_hourly_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("🌅 بداية الدوام (تأخير)", callback_data="hourly_late")],[InlineKeyboardButton("🌇 نهاية الدوام (مغادرة مبكرة)", callback_data="hourly_early")]]
    await query.edit_message_text("اختر نوع الإجازة الساعية:", reply_markup=InlineKeyboardMarkup(keyboard))
    return HL_CHOOSING_TYPE

async def choose_hourly_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    leave_type = query.data.split('_')[1]
    context.user_data['hourly_leave_type'] = leave_type
    message = "متى ستصل إلى الدوام؟" if leave_type == 'late' else "متى ستغادر من الدوام؟"
    await query.edit_message_text(text=message, reply_markup=create_time_keyboard(leave_type))
    return HL_SELECTING_TIME

async def select_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    selected_time = query.data.split('_', 1)[1]
    context.user_data['selected_time'] = selected_time
    type_text = "تأخير صباحي" if context.user_data['hourly_leave_type'] == 'late' else "مغادرة مبكرة"
    await query.edit_message_text(f"تم اختيار: {type_text} - الساعة {selected_time}.")
    await query.message.reply_text("الرجاء إدخال اسمك الكامل:")
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

# --- آلية الإجازة اليومية ---
async def start_full_day_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("حسناً، لطلب إجازة يوم كامل أو أكثر، الرجاء إدخال اسمك الكامل:")
    return FD_ENTERING_NAME

async def fd_enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['employee_name'] = update.message.text
    await update.message.reply_text("شكراً لك. الآن الرجاء إدخال سبب الإجازة:")
    return FD_ENTERING_REASON

async def fd_enter_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['leave_reason'] = update.message.text
    keyboard = [[InlineKeyboardButton("🗓️ يوم واحد", callback_data="duration_single")],[InlineKeyboardButton("🔁 أيام متتالية", callback_data="duration_range")],[InlineKeyboardButton("➕ أيام متفرقة", callback_data="duration_multiple")],]
    await update.message.reply_text("تم تسجيل السبب. الآن، كيف هي مدة إجازتك؟", reply_markup=InlineKeyboardMarkup(keyboard))
    return FD_CHOOSING_DURATION_TYPE

async def fd_choose_duration_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
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

# --- آلية سبب الرفض ومعالجات HR ---
async def start_rejection_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['rejection_info'] = query.data 
    await query.edit_message_text("الرجاء إدخال سبب الرفض (أو أرسل /skip للتجاوز).")
    return AWAITING_REJECTION_REASON

async def save_rejection_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    reason = update.message.text
    rejection_info = context.user_data.pop('rejection_info', None)
    if not rejection_info: return ConversationHandler.END
    await process_rejection(context, rejection_info, reason)
    await update.message.reply_text(f"تم تسجيل سبب الرفض وإبلاغ الموظف.")
    return ConversationHandler.END
    
async def skip_rejection_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    rejection_info = context.user_data.pop('rejection_info', None)
    if not rejection_info: return ConversationHandler.END
    await process_rejection(context, rejection_info, None)
    await update.message.reply_text("تم رفض الطلب.")
    return ConversationHandler.END

async def hr_approval_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, leave_type, request_id = query.data.split("_", 2)
    db_path = f"/{leave_type}_leaves/{request_id}"
    leave_ref = db.reference(db_path)
    leave_request = leave_ref.get()

    if not leave_request or leave_request.get("status") != "pending":
        await query.edit_message_text("هذا الطلب تمت معالجته بالفعل.")
        return

    leave_ref.update({"status": "approved"})
    date_info = leave_request.get('date_info', leave_request.get('time_info', 'N/A'))
    employee_name = leave_request.get('employee_name', 'موظف')
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
    
    await query.edit_message_text(text=f"{query.message.text}\n\n--- [ {response_text} ] ---")

async def process_rejection(context: ContextTypes.DEFAULT_TYPE, rejection_info: str, reason: str | None):
    _, leave_type, request_id = rejection_info.split("_", 2)
    db_path = f"/{leave_type}_leaves/{request_id}"
    leave_ref = db.reference(db_path)
    update_data = {"status": "rejected"}
    if reason:
        update_data["rejection_reason"] = reason
    leave_ref.update(update_data)
    
    leave_request = leave_ref.get()
    date_info = leave_request.get('date_info', leave_request.get('time_info', 'N/A'))
    rejection_message = f"للأسف، تم رفض طلب إجازتك لـِ: {date_info}."
    if reason:
        rejection_message += f"\n**السبب:** {reason}"
    await context.bot.send_message(chat_id=leave_request["employee_telegram_id"], text=rejection_message, parse_mode='Markdown')

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


# --- المهام المجدولة ---
async def daily_on_leave_summary(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running daily on-leave summary job.")
    today = date.today()
    on_leave_today = []
    all_leaves = db.reference('/full_day_leaves').order_by_child('status').equal_to('approved').get() or {}
    for req in all_leaves.values():
        date_info = req.get('date_info', '')
        try:
            if "من" in date_info:
                start_str, end_str = date_info.replace("من ", "").split(" إلى ")
                start_date = datetime.strptime(start_str, '%d/%m/%Y').date()
                end_date = datetime.strptime(end_str, '%d/%m/%Y').date()
                if start_date <= today <= end_date:
                    on_leave_today.append(req['employee_name'])
            elif date.today() == datetime.strptime(date_info, '%d/%m/%Y').date():
                 on_leave_today.append(req['employee_name'])
        except (ValueError, IndexError):
            continue
    if not on_leave_today:
        logger.info("No employees on leave today.")
        return
    message = f"☀️ **تقرير الإجازات اليومي ({today.strftime('%d/%m/%Y')})** ☀️\n\nالموظفون التاليون في إجازة اليوم:\n"
    message += "\n".join(f"- {name}" for name in on_leave_today)
    manager_ids = get_all_managers_ids()
    for manager_id in manager_ids:
        try:
            await context.bot.send_message(chat_id=manager_id, text=message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to send daily summary to {manager_id}: {e}")

async def send_leave_reminders(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running leave reminder job.")
    tomorrow = date.today() + timedelta(days=1)
    all_leaves = db.reference('/full_day_leaves').order_by_child('status').equal_to('approved').get() or {}
    for req in all_leaves.values():
        date_info = req.get('date_info', '')
        try:
            start_date_str = date_info.split(" إلى ")[0].replace("من ", "")
            start_date = datetime.strptime(start_date_str, '%d/%m/%Y').date()
            if start_date == tomorrow:
                await context.bot.send_message(chat_id=req['employee_telegram_id'], text=f"👋 تذكير: إجازتك تبدأ غداً! نتمنى لك وقتاً ممتعاً.")
        except (ValueError, IndexError):
            continue

def main() -> None:
    """يبدأ البوت ويقوم بجدولة المهام."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    job_queue = application.job_queue
    tz = pytz.timezone('Asia/Riyadh') 
    job_queue.run_daily(daily_on_leave_summary, time=time(8, 0, 0, tzinfo=tz))
    job_queue.run_daily(send_leave_reminders, time=time(18, 0, 0, tzinfo=tz))

    # المعالجات
    full_day_conv = ConversationHandler(
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
    
    hourly_conv = ConversationHandler(
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

    rejection_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_rejection_flow, pattern="^reject_")],
        states={
            AWAITING_REJECTION_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_rejection_reason),
                CommandHandler('skip', skip_rejection_reason)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(my_requests, pattern="^my_requests$"))
    application.add_handler(CallbackQueryHandler(hr_pending_requests, pattern="^hr_pending_requests$"))
    application.add_handler(full_day_conv)
    application.add_handler(hourly_conv)
    application.add_handler(CallbackQueryHandler(hr_approval_handler, pattern="^approve_"))
    application.add_handler(rejection_conv)

    print("Bot is running with ALL PRO features...")
    application.run_polling()

if __name__ == "__main__":
    main()
