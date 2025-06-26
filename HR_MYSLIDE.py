# -*- coding: utf-8 -*-
import logging
from datetime import datetime, date, timedelta
import calendar
import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
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
# الرجاء استبدال القيم أدناه بالقيم الخاصة بك أو استخدام متغيرات البيئة
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8022986919:AAEPa_fgGad_MbmR5i35ZmBLWGgC8G1xmIo")
FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL", "https://hr-myslide-default-rtdb.europe-west1.firebasedatabase.app")

# --- إعداد اتصال Firebase ---
try:
    firebase_creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if firebase_creds_json:
        print("INFO: Reading Firebase credentials from environment variable.")
        cred_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(cred_dict)
    else:
        print("INFO: Using local 'firebase-credentials.json' file.")
        cred = credentials.Certificate("firebase-credentials.json")

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DATABASE_URL})
    print("SUCCESS: Firebase connected successfully!")
except Exception as e:
    print(f"ERROR: Could not connect to Firebase. Reason: {e}")
    exit()

# إعداد التسجيل لرؤية الأخطاء والمشاكل
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- تعريف حالات المحادثات ---
# حالات محادثة الإجازة اليومية
(
    FD_ENTERING_NAME,
    FD_ENTERING_REASON,
    FD_CHOOSING_DURATION_TYPE,
    FD_SELECTING_DATES,
    FD_CONFIRMING_LEAVE,
) = range(5)

# حالات محادثة الإجازة الساعية (الإذن) - تم التعديل
(
    HL_CHOOSING_TYPE,
    HL_SELECTING_DATE,
    HL_SELECTING_TIME,
    HL_ENTERING_NAME,
    HL_ENTERING_REASON,
    HL_CONFIRMING_LEAVE,
) = range(5, 11)

# --- دوال إنشاء واجهات المستخدم (التقويم والأزرار) ---
def create_advanced_calendar(year: int, month: int, selection_mode: str, selected_dates: list, back_callback: str) -> InlineKeyboardMarkup:
    """إنشاء تقويم تفاعلي مع أزرار تنقل وزر رجوع."""
    cal = calendar.Calendar()
    month_names_ar = ["", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
    month_name = month_names_ar[month]
    today = date.today()
    keyboard = []

    header_row = [
        InlineKeyboardButton("‹", callback_data=f"CAL_NAV_{year}_{month-1}" if month > 1 else f"CAL_NAV_{year-1}_12"),
        InlineKeyboardButton(f"{month_name} {year}", callback_data="CAL_IGNORE"),
        InlineKeyboardButton("›", callback_data=f"CAL_NAV_{year}_{month+1}" if month < 12 else f"CAL_NAV_{year+1}_1"),
    ]
    keyboard.append(header_row)

    days_row = [InlineKeyboardButton(day, callback_data="CAL_IGNORE") for day in ["اثنين", "ثلاثاء", "أربعاء", "خميس", "جمعة", "سبت", "أحد"]]
    keyboard.append(days_row)

    for week in cal.monthdayscalendar(year, month):
        row = []
        for day_num in week:
            if day_num == 0:
                row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
            else:
                current_day = date(year, month, day_num)
                is_disabled = current_day < today or (selection_mode == 'range' and selected_dates and current_day < selected_dates[0])
                day_text = str(day_num)
                if current_day in selected_dates:
                    day_text = f"*{day_num}*"

                if is_disabled:
                    row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
                else:
                    row.append(InlineKeyboardButton(day_text, callback_data=f"CAL_DAY_{year}_{month}_{day_num}"))
        keyboard.append(row)

    if selection_mode == 'multiple' and selected_dates:
        keyboard.append([InlineKeyboardButton("✅ تم الاختيار", callback_data="CAL_DONE")])

    keyboard.append([InlineKeyboardButton("➡️ رجوع", callback_data=back_callback), InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def create_weekly_calendar(start_date: date, back_callback: str) -> InlineKeyboardMarkup:
    """إنشاء تقويم لمدة أسبوع واحد بدءًا من تاريخ محدد."""
    keyboard = []
    days_ar = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    
    row = []
    for i in range(7):
        current_day = start_date + timedelta(days=i)
        day_name = days_ar[current_day.weekday()]
        # Format: 'الخميس 26'
        button_text = f"{day_name} {current_day.day}"
        callback_data = f"HL_DATE_{current_day.isoformat()}"
        row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    # Split into two rows for better layout
    keyboard.append(row[:4])
    keyboard.append(row[4:])
    
    keyboard.append([InlineKeyboardButton("➡️ رجوع", callback_data=back_callback), InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(keyboard)


def create_time_keyboard(leave_type: str, back_callback: str) -> InlineKeyboardMarkup:
    """إنشاء لوحة مفاتيح لاختيار الوقت مع زر رجوع."""
    keyboard = []
    if leave_type == 'late':
        keyboard = [
            [InlineKeyboardButton("9:30 AM", callback_data="TIME_9:30 AM"), InlineKeyboardButton("10:00 AM", callback_data="TIME_10:00 AM")],
            [InlineKeyboardButton("10:30 AM", callback_data="TIME_10:30 AM"), InlineKeyboardButton("11:00 AM", callback_data="TIME_11:00 AM")],
            [InlineKeyboardButton("11:30 AM", callback_data="TIME_11:30 AM"), InlineKeyboardButton("12:00 PM", callback_data="TIME_12:00 PM")],
            [InlineKeyboardButton("12:30 PM", callback_data="TIME_12:30 PM"), InlineKeyboardButton("1:00 PM", callback_data="TIME_1:00 PM")],
            [InlineKeyboardButton("1:30 PM", callback_data="TIME_1:30 PM"), InlineKeyboardButton("2:00 PM", callback_data="TIME_2:00 PM")],
        ]
    elif leave_type == 'early':
        keyboard = [
            [InlineKeyboardButton("11:00 AM", callback_data="TIME_11:00 AM"), InlineKeyboardButton("11:30 AM", callback_data="TIME_11:30 AM")],
            [InlineKeyboardButton("12:00 PM", callback_data="TIME_12:00 PM"), InlineKeyboardButton("12:30 PM", callback_data="TIME_12:30 PM")],
            [InlineKeyboardButton("1:00 PM", callback_data="TIME_1:00 PM"), InlineKeyboardButton("1:30 PM", callback_data="TIME_1:30 PM")],
            [InlineKeyboardButton("2:00 PM", callback_data="TIME_2:00 PM"), InlineKeyboardButton("2:30 PM", callback_data="TIME_2:30 PM")],
            [InlineKeyboardButton("3:00 PM", callback_data="TIME_3:00 PM"), InlineKeyboardButton("3:30 PM", callback_data="TIME_3:30 PM")],
        ]
    
    keyboard.append([InlineKeyboardButton("➡️ رجوع", callback_data=back_callback), InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

# --- دوال مساعدة (قاعدة البيانات والتنقل) ---
def get_predefined_user(telegram_id: str):
    """جلب بيانات المستخدمين المعرفين مسبقاً (مدراء وقادة فرق)."""
    try:
        ref = db.reference('/users')
        users = ref.get() or {}
        for user_data in users.values():
            if user_data and str(user_data.get("telegram_id", "")) == telegram_id:
                return user_data
    except Exception as e:
        logger.error(f"Error fetching predefined user: {e}")
    return None

def get_all_team_leaders_ids():
    """جلب معرفات تليجرام لجميع قادة الفرق."""
    leader_ids = []
    try:
        ref = db.reference('/users')
        users = ref.get() or {}
        for user_data in users.values():
            if user_data and user_data.get("role") == "team_leader":
                leader_ids.append(user_data.get("telegram_id"))
    except Exception as e:
        logger.error(f"Error fetching team leaders: {e}")
    return leader_ids

def get_hr_telegram_id():
    """جلب معرف تليجرام لمدير الموارد البشرية."""
    try:
        ref = db.reference('/users')
        users = ref.get() or {}
        for user_data in users.values():
            if user_data and user_data.get("role") == "hr":
                return user_data.get("telegram_id")
    except Exception as e:
        logger.error(f"Error fetching HR ID: {e}")
    return None

async def display_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دالة لعرض القائمة الرئيسية، سواء كرسالة جديدة أو تعديل رسالة قائمة."""
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("🕒 طلب إذن (ساعي)", callback_data="start_hourly_leave")],
        [InlineKeyboardButton("🗓️ طلب إجازة (يومي)", callback_data="start_full_day_leave")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = f"أهلاً بك {user.first_name} في نظام طلبات الإجازة والأذونات.\n\nاختر الخدمة التي تريدها من القائمة:"

    query = update.callback_query
    if query:
        await query.answer()
        try:
            await query.edit_message_text(text=message_text, reply_markup=reply_markup)
        except Exception as e: # Handle case where message is too old to edit
            logger.warning(f"Could not edit message, sending new one. Reason: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=message_text, reply_markup=reply_markup)

async def return_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إنهاء المحادثة الحالية والعودة إلى القائمة الرئيسية."""
    await display_main_menu(update, context)
    context.user_data.clear()
    return ConversationHandler.END

# --- معالجات الأوامر الرئيسية ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج الأمر /start, يعرض رسائل ترحيب مختلفة بناءً على دور المستخدم."""
    user = update.effective_user
    predefined_user = get_predefined_user(str(user.id))
    if predefined_user:
        role = predefined_user.get("role")
        if role == "hr":
            await update.message.reply_text(f"أهلاً وسهلاً، {user.first_name}! تم تسجيل دخولك بصلاحيات [مدير الموارد البشرية].")
        elif role == "team_leader":
            await update.message.reply_text(f"أهلاً وسهلاً، {user.first_name}! تم تسجيل دخولك بصلاحيات [قائد فريق].")
    else:
        await display_main_menu(update, context)

# ---- بداية محادثة الإجازة الساعية (الإذن) ----
async def start_hourly_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الأولى: اختيار نوع الإذن."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🌅 إذن تأخير صباحي", callback_data="hourly_late")],
        [InlineKeyboardButton("🌇 إذن مغادرة مبكرة", callback_data="hourly_early")],
        [InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("يرجى تحديد نوع الإذن المطلوب:", reply_markup=reply_markup)
    return HL_CHOOSING_TYPE

async def choose_hourly_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الثانية: طلب اختيار تاريخ الإذن."""
    query = update.callback_query
    await query.answer()
    leave_type = query.data.split('_')[1]
    context.user_data['hourly_leave_type'] = leave_type

    message = "ممتاز. الآن يرجى اختيار تاريخ الإذن من الأسبوع الحالي:"
    today = date.today()
    
    await query.edit_message_text(
        text=message,
        reply_markup=create_weekly_calendar(start_date=today, back_callback="hl_back_to_type")
    )
    return HL_SELECTING_DATE

async def select_hourly_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الثالثة: معالجة اختيار التاريخ وطلب الوقت."""
    query = update.callback_query
    await query.answer()
    
    # استخراج التاريخ من بيانات الرد
    selected_date_iso = query.data.split('_', 2)[2]
    selected_date_obj = date.fromisoformat(selected_date_iso)
    context.user_data['hourly_selected_date'] = selected_date_obj
    
    leave_type = context.user_data['hourly_leave_type']
    date_str = selected_date_obj.strftime('%d/%m/%Y')
    message = f"تاريخ الإذن المحدد: {date_str}.\n\n"
    message += "يرجى تحديد وقت الوصول المتوقع:" if leave_type == 'late' else "يرجى تحديد وقت المغادرة:"
    
    await query.edit_message_text(
        text=message,
        reply_markup=create_time_keyboard(leave_type, back_callback="hl_back_to_date_selection")
    )
    return HL_SELECTING_TIME

async def select_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الرابعة: طلب إدخال اسم الموظف."""
    query = update.callback_query
    await query.answer()
    selected_time = query.data.split('_', 1)[1]
    context.user_data['selected_time'] = selected_time
    date_str = context.user_data['hourly_selected_date'].strftime('%A, %d %B %Y')
    await query.message.reply_text(
        f"تم تحديد الإذن في تاريخ {date_str} الساعة {selected_time}.\n\n"
        "الآن، يرجى إدخال اسمك الكامل لتوثيق الطلب:"
    )
    await query.delete_message()
    return HL_ENTERING_NAME

async def enter_hourly_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الخامسة: طلب إدخال سبب الإذن."""
    context.user_data['employee_name'] = update.message.text
    await update.message.reply_text("شكراً لك. يرجى الآن توضيح سبب هذا الإذن:")
    return HL_ENTERING_REASON

async def enter_hourly_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة السادسة: عرض ملخص الطلب للتأكيد."""
    context.user_data['hourly_reason'] = update.message.text
    leave_type = context.user_data['hourly_leave_type']
    type_text = "تأخير صباحي" if leave_type == 'late' else "مغادرة مبكرة"
    time_label = "وقت الوصول" if leave_type == 'late' else "وقت المغادرة"
    
    # استخدام التاريخ المختار
    selected_date_str = context.user_data['hourly_selected_date'].strftime('%d/%m/%Y')
    
    summary = (f"📋 **ملخص طلب الإذن** 📋\n\n"
               f"👤 **اسم الموظف:** {context.user_data['employee_name']}\n"
               f"🏷️ **نوع الإذن:** {type_text}\n"
               f"🗓️ **التاريخ:** {selected_date_str}\n"
               f"⏰ **{time_label}:** {context.user_data['selected_time']}\n"
               f"📝 **السبب:** {context.user_data['hourly_reason']}\n\n"
               "يرجى مراجعة التفاصيل. هل تود تأكيد وإرسال الطلب؟")
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد وإرسال", callback_data="confirm_send"), InlineKeyboardButton("❌ إلغاء الطلب", callback_data="cancel")],
        [InlineKeyboardButton("➡️ رجوع (لتعديل السبب)", callback_data="hl_back_to_reason")]
    ]
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    return HL_CONFIRMING_LEAVE

async def confirm_hourly_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الإجراء الأخير: حفظ الطلب في Firebase وإرساله للموارد البشرية."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("تم إلغاء الطلب.")
        context.user_data.clear()
        return ConversationHandler.END

    user = update.effective_user
    leaves_ref = db.reference('/hourly_leaves')
    new_leave_ref = leaves_ref.push()
    request_id = new_leave_ref.key
    leave_type = context.user_data['hourly_leave_type']
    type_text = "تأخير صباحي" if leave_type == 'late' else "مغادرة مبكرة"
    time_info = f"{type_text} - {context.user_data['selected_time']}"
    
    # استخدام التاريخ المختار
    selected_date_obj = context.user_data['hourly_selected_date']
    
    new_leave_ref.set({
        "employee_name": context.user_data['employee_name'],
        "employee_telegram_id": str(user.id),
        "reason": context.user_data['hourly_reason'],
        "date": selected_date_obj.strftime('%d/%m/%Y'),
        "time_info": time_info,
        "status": "pending",
        "request_time": datetime.now().isoformat(),
    })

    hr_chat_id = get_hr_telegram_id()
    if not hr_chat_id:
        await query.edit_message_text("⚠️ خطأ إداري: لا يمكن العثور على حساب مدير الموارد البشرية. يرجى مراجعة الإدارة.")
        return ConversationHandler.END

    # استخدام التاريخ المختار في رسالة المدير
    selected_date_str = selected_date_obj.strftime('%d/%m/%Y')
    hr_message = (f"📣 **طلب إذن ساعي جديد** 📣\n\n"
                  f"**من الموظف:** {context.user_data['employee_name']}\n"
                  f"**النوع:** {type_text}\n"
                  f"**التفاصيل:** بتاريخ {selected_date_str}، الساعة {context.user_data['selected_time']}\n"
                  f"**السبب:** {context.user_data['hourly_reason']}\n\n"
                  "يرجى اتخاذ الإجراء المناسب.")
    keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_hourly_{request_id}"), InlineKeyboardButton("❌ رفض", callback_data=f"reject_hourly_{request_id}")]]
    
    try:
        await context.bot.send_message(chat_id=hr_chat_id, text=hr_message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text("✅ تم إرسال طلبك بنجاح. سيتم إعلامك بالرد قريباً.")
    except Exception as e:
        logger.error(f"Failed to send hourly leave to HR: {e}")
        await query.edit_message_text("حدث خطأ أثناء إرسال الطلب. يرجى المحاولة مرة أخرى.")

    context.user_data.clear()
    return ConversationHandler.END

# ---- بداية محادثة الإجازة اليومية ----
async def start_full_day_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الأولى: طلب إدخال اسم الموظف."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("لتسجيل طلب إجازة، يرجى إدخال اسمك الكامل:")
    return FD_ENTERING_NAME

async def fd_enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الثانية: طلب إدخال سبب الإجازة."""
    context.user_data['employee_name'] = update.message.text
    await update.message.reply_text("شكراً لك. الآن، يرجى توضيح سبب الإجازة:")
    return FD_ENTERING_REASON

async def fd_enter_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الثالثة: اختيار نوع مدة الإجازة."""
    context.user_data['leave_reason'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🗓️ يوم واحد", callback_data="duration_single")],
        [InlineKeyboardButton("🔁 أيام متتالية", callback_data="duration_range")],
        [InlineKeyboardButton("➕ أيام متفرقة", callback_data="duration_multiple")],
        [InlineKeyboardButton("➡️ رجوع (لتعديل السبب)", callback_data="fd_back_to_reason")],
        [InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("تم تسجيل السبب. يرجى الآن تحديد مدة الإجازة:", reply_markup=reply_markup)
    return FD_CHOOSING_DURATION_TYPE

async def fd_choose_duration_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الرابعة: عرض التقويم لاختيار التواريخ."""
    query = update.callback_query
    await query.answer()
    duration_type = query.data.split('_')[1]
    context.user_data['duration_type'] = duration_type
    context.user_data['selected_dates'] = []
    today = date.today()
    message = "الرجاء اختيار تاريخ الإجازة من التقويم:"
    if duration_type == 'range': message = "الرجاء اختيار تاريخ **البدء**:"
    elif duration_type == 'multiple': message = "اختر الأيام ثم اضغط '✅ تم الاختيار':"
    await query.edit_message_text(text=message, reply_markup=create_advanced_calendar(today.year, today.month, duration_type, [], back_callback="fd_back_to_duration_type"), parse_mode=ParseMode.MARKDOWN)
    return FD_SELECTING_DATES

async def fd_calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة التفاعل مع التقويم (اختيار يوم أو التنقل)."""
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
                await query.edit_message_text(f"تاريخ البدء: {selected_day.strftime('%d/%m/%Y')}\n\nالرجاء اختيار تاريخ **الانتهاء**:", reply_markup=create_advanced_calendar(year, month, duration_type, selected_dates, back_callback="fd_back_to_duration_type"), parse_mode=ParseMode.MARKDOWN)
                return FD_SELECTING_DATES
            else:
                if selected_day < selected_dates[0]: return FD_SELECTING_DATES
                selected_dates.append(selected_day)
                return await show_fd_confirmation(query, context)
        elif duration_type == 'multiple':
            if selected_day in selected_dates: selected_dates.remove(selected_day)
            else: selected_dates.append(selected_day)
            await query.edit_message_text("اختر الأيام ثم اضغط '✅ تم الاختيار':", reply_markup=create_advanced_calendar(year, month, duration_type, selected_dates, back_callback="fd_back_to_duration_type"))
            return FD_SELECTING_DATES
    elif action == "NAV":
        year, month = map(int, parts[2:])
        await query.edit_message_text(query.message.text, reply_markup=create_advanced_calendar(year, month, duration_type, selected_dates, back_callback="fd_back_to_duration_type"))
        return FD_SELECTING_DATES
    elif action == "DONE":
        if not selected_dates: return FD_SELECTING_DATES
        return await show_fd_confirmation(query, context)
    return FD_SELECTING_DATES

async def show_fd_confirmation(query, context):
    """الخطوة الخامسة: عرض ملخص الإجازة اليومية للتأكيد."""
    duration_type = context.user_data['duration_type']
    selected_dates = sorted(context.user_data.get('selected_dates', []))
    if not selected_dates:
        await query.edit_message_text("لم يتم اختيار أي تاريخ. تم إلغاء الطلب.")
        return ConversationHandler.END
        
    date_info_str = ""
    if duration_type == 'single': date_info_str = selected_dates[0].strftime('%d/%m/%Y')
    elif duration_type == 'range': date_info_str = f"من {selected_dates[0].strftime('%d/%m/%Y')} إلى {selected_dates[-1].strftime('%d/%m/%Y')}"
    elif duration_type == 'multiple': date_info_str = ", ".join([d.strftime('%d/%m/%Y') for d in selected_dates])
    context.user_data['final_date_info'] = date_info_str
    
    summary = (f"📋 **ملخص طلب الإجازة** 📋\n\n"
               f"👤 **الاسم:** {context.user_data['employee_name']}\n"
               f"📝 **السبب:** {context.user_data['leave_reason']}\n"
               f"🗓️ **التاريخ/المدة:** {date_info_str}\n\n"
               "يرجى مراجعة التفاصيل. هل تود تأكيد وإرسال الطلب؟")
               
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد وإرسال", callback_data="confirm_send"), InlineKeyboardButton("❌ إلغاء الطلب", callback_data="cancel")],
        [InlineKeyboardButton("➡️ رجوع (لتعديل التواريخ)", callback_data="fd_back_to_calendar")]
    ]
    await query.edit_message_text(text=summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    return FD_CONFIRMING_LEAVE

async def confirm_full_day_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الإجراء الأخير: حفظ الإجازة اليومية في Firebase وإرسالها للموارد البشرية."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("تم إلغاء الطلب.")
        context.user_data.clear()
        return ConversationHandler.END

    user = update.effective_user
    leaves_ref = db.reference('/full_day_leaves')
    new_leave_ref = leaves_ref.push()
    request_id = new_leave_ref.key
    new_leave_ref.set({
        "employee_name": context.user_data['employee_name'],
        "employee_telegram_id": str(user.id),
        "reason": context.user_data['leave_reason'],
        "date_info": context.user_data['final_date_info'],
        "status": "pending",
        "request_time": datetime.now().isoformat(),
    })
    
    hr_chat_id = get_hr_telegram_id()
    if not hr_chat_id:
        await query.edit_message_text("⚠️ خطأ إداري: لا يمكن العثور على حساب مدير الموارد البشرية.")
        return ConversationHandler.END
        
    hr_message = (f"📣 **طلب إجازة جديد** 📣\n\n"
                  f"**من:** {context.user_data['employee_name']}\n"
                  f"**السبب:** {context.user_data['leave_reason']}\n"
                  f"**التاريخ/المدة:** {context.user_data['final_date_info']}\n\n"
                  "يرجى اتخاذ الإجراء المناسب.")
                  
    keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_fd_{request_id}"), InlineKeyboardButton("❌ رفض", callback_data=f"reject_fd_{request_id}")]]
    
    try:
        await context.bot.send_message(chat_id=hr_chat_id, text=hr_message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text("✅ تم إرسال طلبك بنجاح. سيتم إعلامك بالرد قريباً.")
    except Exception as e:
        logger.error(f"Failed to send full day leave to HR: {e}")
        await query.edit_message_text("حدث خطأ أثناء إرسال الطلب. يرجى المحاولة مرة أخرى.")
        
    context.user_data.clear()
    return ConversationHandler.END

# --- معالج إجراءات الموارد البشرية (مطور ومعدل) ---
async def hr_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة قرارات الموافقة/الرفض من قبل الموارد البشرية."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    action = parts[0]
    leave_type_key = parts[1]
    
    prefix = f"{action}_{leave_type_key}_"
    request_id = query.data[len(prefix):]
    
    leave_type_db = "full_day_leaves" if leave_type_key == "fd" else "hourly_leaves"
    db_path = f"/{leave_type_db}/{request_id}"
    leave_ref = db.reference(db_path)
    leave_request = leave_ref.get()

    if not leave_request:
        await query.edit_message_text("❌ خطأ فني: لم يتم العثور على هذا الطلب. قد يكون قد تم حذفه أو أن المعرّف غير صحيح.")
        logger.error(f"Could not find leave request at path: {db_path}")
        return

    if leave_request.get("status") != "pending":
        status_ar = "مقبول ✅" if leave_request.get("status") == "approved" else "مرفوض ❌"
        await query.answer(f"تنبيه: هذا الطلب تمت معالجته بالفعل وحالته الآن: {status_ar}", show_alert=True)
        return

    employee_name = leave_request.get('employee_name', 'موظف')
    hr_user = query.from_user
    
    # --- بناء رسائل الإشعارات بناءً على نوع الإجازة ---
    full_date_info = ""
    leader_message_intro = ""
    if leave_type_key == 'fd':
        full_date_info = leave_request.get('date_info', 'غير محدد')
        # الصيغة الجديدة المطلوبة لإشعار قادة الفرق
        leader_message_intro = f"تم منح الموظف ({employee_name}) موافقة بخصوص غياب في التاريخ/ التواريخ التالية:"
    else: # hourly
        leave_date = leave_request.get('date', 'بتاريخ اليوم')
        time_details = leave_request.get('time_info', 'وقت غير محدد')
        # دمج التاريخ والوقت في رسالة واحدة واضحة
        full_date_info = f"{time_details} بتاريخ {leave_date}"
        leader_message_intro = f"تم منح الموظف ({employee_name}) موافقة بخصوص إذن:"

    if action == "approve":
        leave_ref.update({"status": "approved"})
        response_text = "✅ تمت الموافقة على الطلب"
        user_notification = f"🎉 تهانينا! تمت الموافقة على طلبك بخصوص: **{full_date_info}**."
        
        leader_ids = get_all_team_leaders_ids()
        if leader_ids:
            leader_notification = f"{leader_message_intro}\n`{full_date_info}`"
            for leader_id in leader_ids:
                try:
                    await context.bot.send_message(chat_id=leader_id, text=leader_notification, parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    logger.error(f"Failed to send notification to Team Leader {leader_id}: {e}")
            response_text += "\n(تم إشعار قادة الفرق)"
            
    else:  # reject
        leave_ref.update({"status": "rejected"})
        response_text = "❌ تم رفض الطلب"
        user_notification = f"للأسف، تم رفض طلبك بخصوص: **{full_date_info}**. يرجى مراجعة مديرك المباشر."
    
    try:
        await context.bot.send_message(chat_id=leave_request["employee_telegram_id"], text=user_notification, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Failed to send notification to employee {leave_request['employee_telegram_id']}: {e}")
        
    original_message = query.message.text
    final_text = f"{original_message}\n\n--- [ {response_text} بواسطة: {hr_user.first_name} ] ---"
    await query.edit_message_text(text=final_text)

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """إلغاء المحادثة الحالية عند الضغط على زر الإلغاء."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("تم إلغاء العملية بنجاح.")
    context.user_data.clear()
    return ConversationHandler.END

# --- دوال الرجوع (Back Handlers) ---
async def hl_back_to_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة إدخال سبب الإذن."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("يرجى الآن توضيح سبب هذا الإذن:")
    return HL_ENTERING_REASON

async def hl_back_to_date_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة اختيار تاريخ الإذن."""
    query = update.callback_query
    await query.answer()
    query.data = f"hourly_{context.user_data['hourly_leave_type']}"
    return await choose_hourly_type(update, context)

async def fd_back_to_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة إدخال سبب الإجازة اليومية."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("شكراً لك. الآن، يرجى توضيح سبب الإجازة:")
    return FD_ENTERING_REASON
    
async def fd_back_to_duration_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة اختيار نوع مدة الإجازة."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🗓️ يوم واحد", callback_data="duration_single")],
        [InlineKeyboardButton("🔁 أيام متتالية", callback_data="duration_range")],
        [InlineKeyboardButton("➕ أيام متفرقة", callback_data="duration_multiple")],
        [InlineKeyboardButton("➡️ رجوع (لتعديل السبب)", callback_data="fd_back_to_reason")],
        [InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")],
    ]
    await query.edit_message_text("يرجى الآن تحديد مدة الإجازة:", reply_markup=InlineKeyboardMarkup(keyboard))
    return FD_CHOOSING_DURATION_TYPE

async def fd_back_to_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة التقويم."""
    query = update.callback_query
    await query.answer()
    # Re-call the function that shows the calendar
    query.data = f"duration_{context.user_data['duration_type']}"
    return await fd_choose_duration_type(update, context)


def main() -> None:
    """الدالة الرئيسية لتشغيل البوت."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # --- تعريف محادثات الإجازات ---
    full_day_leave_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_full_day_leave, pattern="^start_full_day_leave$")],
        states={
            FD_ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, fd_enter_name)],
            FD_ENTERING_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, fd_enter_reason)],
            FD_CHOOSING_DURATION_TYPE: [
                CallbackQueryHandler(fd_choose_duration_type, pattern="^duration_"),
                CallbackQueryHandler(fd_back_to_reason, pattern="^fd_back_to_reason$"),
            ],
            FD_SELECTING_DATES: [
                CallbackQueryHandler(fd_calendar_callback, pattern="^CAL_"),
                CallbackQueryHandler(fd_back_to_duration_type, pattern="^fd_back_to_duration_type$"),
            ],
            FD_CONFIRMING_LEAVE: [
                CallbackQueryHandler(confirm_full_day_leave, pattern="^confirm_send$"),
                CallbackQueryHandler(fd_back_to_calendar, pattern="^fd_back_to_calendar$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_conversation, pattern="^cancel$"),
            CallbackQueryHandler(return_to_main_menu, pattern="^main_menu$")
        ],
    )
    
    hourly_leave_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_hourly_leave, pattern="^start_hourly_leave$")],
        states={
            HL_CHOOSING_TYPE: [CallbackQueryHandler(choose_hourly_type, pattern="^hourly_")],
            HL_SELECTING_DATE: [
                CallbackQueryHandler(select_hourly_date, pattern="^HL_DATE_"),
                CallbackQueryHandler(start_hourly_leave, pattern="^hl_back_to_type$"),
            ],
            HL_SELECTING_TIME: [
                CallbackQueryHandler(select_time, pattern="^TIME_"),
                CallbackQueryHandler(hl_back_to_date_selection, pattern="^hl_back_to_date_selection$"),
            ],
            HL_ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_hourly_name)],
            HL_ENTERING_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_hourly_reason)],
            HL_CONFIRMING_LEAVE: [
                CallbackQueryHandler(confirm_hourly_leave, pattern="^confirm_send$"),
                CallbackQueryHandler(hl_back_to_reason, pattern="^hl_back_to_reason$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_conversation, pattern="^cancel$"),
            CallbackQueryHandler(return_to_main_menu, pattern="^main_menu$")
        ],
    )

    # إضافة المعالجات إلى التطبيق
    application.add_handler(CommandHandler("start", start))
    application.add_handler(full_day_leave_conv)
    application.add_handler(hourly_leave_conv)
    application.add_handler(CallbackQueryHandler(hr_action_handler, pattern="^(approve|reject)_(fd|hourly)_"))

    print("Bot is running with weekly calendar for hourly leaves...")
    application.run_polling()

if __name__ == "__main__":
    main()
