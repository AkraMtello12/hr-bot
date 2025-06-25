# -*- coding: utf-8 -*-
import logging
from datetime import datetime, date, timedelta
import calendar
import os
import json
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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TELEGRAM_API_TOKEN") 
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

# حالات المحادثة الجديدة
(
    ENTERING_NAME,
    ENTERING_REASON,
    CHOOSING_DURATION_TYPE,
    SELECTING_DATES,
    CONFIRMING_LEAVE,
) = range(5)

# --- دوال إنشاء التقويم المطور ---
def create_advanced_calendar(year: int, month: int, selection_mode: str, selected_dates: list) -> InlineKeyboardMarkup:
    cal = calendar.Calendar()
    month_name = calendar.month_name[month]
    today = date.today()
    keyboard = []

    # صف العنوان والتنقل
    header_row = [
        InlineKeyboardButton("<", callback_data=f"CAL_NAV_{year}_{month-1}" if month > 1 else f"CAL_NAV_{year-1}_12"),
        InlineKeyboardButton(f"{month_name} {year}", callback_data="CAL_IGNORE"),
        InlineKeyboardButton(">", callback_data=f"CAL_NAV_{year}_{month+1}" if month < 12 else f"CAL_NAV_{year+1}_1"),
    ]
    keyboard.append(header_row)

    # صف أيام الأسبوع
    days_row = [InlineKeyboardButton(day, callback_data="CAL_IGNORE") for day in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]]
    keyboard.append(days_row)

    # صفوف الأيام
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
                    day_text = f"*{day}*" # علامة لتحديد يوم مختار

                if is_disabled:
                    row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
                else:
                    row.append(InlineKeyboardButton(day_text, callback_data=f"CAL_DAY_{year}_{month}_{day}"))
        keyboard.append(row)
    
    # إضافة زر "تم الاختيار" في وضع الأيام المتفرقة
    if selection_mode == 'multiple' and selected_dates:
        keyboard.append([InlineKeyboardButton("✅ تم الاختيار", callback_data="CAL_DONE")])

    return InlineKeyboardMarkup(keyboard)

# --- دوال مساعدة أخرى ---
def get_predefined_user(telegram_id: str) -> dict | None:
    ref = db.reference('/users')
    users = ref.get() or {}
    for user_data in users.values():
        if user_data and str(user_data.get("telegram_id", "")) == telegram_id:
            return user_data
    return None

def get_all_team_leaders_ids() -> list:
    leader_ids = []
    ref = db.reference('/users')
    users = ref.get() or {}
    for user_data in users.values():
        if user_data and user_data.get("role") == "team_leader":
            leader_ids.append(user_data.get("telegram_id"))
    return leader_ids

def get_hr_telegram_id() -> str | None:
    ref = db.reference('/users')
    users = ref.get() or {}
    for user_data in users.values():
        if user_data and user_data.get("role") == "hr":
            return user_data.get("telegram_id")
    return None

# --- معالجات الأوامر والمحادثة ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (تبقى كما هي)
    user = update.effective_user
    predefined_user = get_predefined_user(str(user.id))
    if predefined_user:
        role = predefined_user.get("role")
        if role == "hr":
            await update.message.reply_text(f"أهلاً بك يا {user.first_name}! أنت مسجل كمدير الموارد البشرية.")
        elif role == "team_leader":
            await update.message.reply_text(f"أهلاً بك يا {user.first_name}! أنت مسجل كقائد فريق.")
    else:
        keyboard = [[InlineKeyboardButton("📝 تقديم طلب إجازة", callback_data="start_request")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"أهلاً بك يا {user.first_name} في بوت طلبات الإجازة.", reply_markup=reply_markup)

async def start_request_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("حسناً، لنبدأ. الرجاء إدخال اسمك الكامل:")
    return ENTERING_NAME

async def enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['employee_name'] = update.message.text
    await update.message.reply_text("شكراً لك. الآن الرجاء إدخال سبب الإجازة:")
    return ENTERING_REASON

async def enter_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['leave_reason'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🗓️ يوم واحد", callback_data="duration_single")],
        [InlineKeyboardButton("🔁 أيام متتالية", callback_data="duration_range")],
        [InlineKeyboardButton("➕ أيام متفرقة", callback_data="duration_multiple")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("تم تسجيل السبب. الآن، كيف هي مدة إجازتك؟", reply_markup=reply_markup)
    return CHOOSING_DURATION_TYPE

async def choose_duration_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    duration_type = query.data.split('_')[1] # single, range, multiple
    context.user_data['duration_type'] = duration_type
    context.user_data['selected_dates'] = [] # تهيئة قائمة التواريخ المختارة
    
    today = date.today()
    message = "الرجاء اختيار تاريخ الإجازة من التقويم:"
    if duration_type == 'range':
        message = "الرجاء اختيار تاريخ **البدء** من التقويم:"
    elif duration_type == 'multiple':
        message = "الرجاء اختيار الأيام التي تريدها، ثم اضغط 'تم الاختيار':"

    await query.edit_message_text(
        text=message,
        reply_markup=create_advanced_calendar(today.year, today.month, duration_type, [])
    )
    return SELECTING_DATES

async def calendar_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
            selected_dates = [selected_day]
            context.user_data['selected_dates'] = selected_dates
            return await show_confirmation(query, context)

        elif duration_type == 'range':
            if not selected_dates: # اختيار تاريخ البدء
                selected_dates.append(selected_day)
                await query.edit_message_text(
                    f"تاريخ البدء المحدد: {selected_day.strftime('%d/%m/%Y')}\n\n"
                    "الآن الرجاء اختيار تاريخ **الانتهاء**:",
                    reply_markup=create_advanced_calendar(year, month, duration_type, selected_dates)
                )
                return SELECTING_DATES
            else: # اختيار تاريخ الانتهاء
                if selected_day < selected_dates[0]:
                    await context.bot.answer_callback_query(query.id, "تاريخ الانتهاء يجب أن يكون بعد تاريخ البدء!", show_alert=True)
                    return SELECTING_DATES
                selected_dates.append(selected_day)
                return await show_confirmation(query, context)

        elif duration_type == 'multiple':
            if selected_day in selected_dates:
                selected_dates.remove(selected_day)
            else:
                selected_dates.append(selected_day)
            
            await query.edit_message_text(
                "الرجاء اختيار الأيام التي تريدها، ثم اضغط 'تم الاختيار':",
                reply_markup=create_advanced_calendar(year, month, duration_type, selected_dates)
            )
            return SELECTING_DATES

    elif action == "NAV":
        year, month = map(int, parts[2:])
        await query.edit_message_text(
            query.message.text,
            reply_markup=create_advanced_calendar(year, month, duration_type, selected_dates)
        )
        return SELECTING_DATES
        
    elif action == "DONE":
        if not selected_dates:
            await context.bot.answer_callback_query(query.id, "الرجاء اختيار يوم واحد على الأقل!", show_alert=True)
            return SELECTING_DATES
        return await show_confirmation(query, context)

    return SELECTING_DATES

async def show_confirmation(query, context):
    """دالة لتوحيد عرض ملخص الطلب."""
    duration_type = context.user_data['duration_type']
    selected_dates = context.user_data.get('selected_dates', [])
    
    if not selected_dates:
        await query.edit_message_text("لم يتم اختيار أي تاريخ. تم إلغاء الطلب.")
        return ConversationHandler.END

    date_info_str = ""
    if duration_type == 'single':
        date_info_str = selected_dates[0].strftime('%d/%m/%Y')
    elif duration_type == 'range':
        start, end = selected_dates
        date_info_str = f"من {start.strftime('%d/%m/%Y')} إلى {end.strftime('%d/%m/%Y')}"
    elif duration_type == 'multiple':
        # فرز التواريخ وعرضها
        selected_dates.sort()
        date_info_str = ", ".join([d.strftime('%d/%m/%Y') for d in selected_dates])
        
    context.user_data['final_date_info'] = date_info_str
    
    summary = (
        f"--- ملخص الطلب ---\n"
        f"اسم الموظف: {context.user_data['employee_name']}\n"
        f"سبب الإجازة: {context.user_data['leave_reason']}\n"
        f"التاريخ/المدة: {date_info_str}\n\n"
        "هل تريد تأكيد الطلب وإرساله للموارد البشرية؟"
    )
    keyboard = [[InlineKeyboardButton("✅ تأكيد وإرسال", callback_data="confirm_send"), InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=summary, reply_markup=reply_markup)
    return CONFIRMING_LEAVE

async def confirm_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("تم إلغاء الطلب.")
        context.user_data.clear()
        return ConversationHandler.END

    # ... (بقية الدالة تبقى كما هي تقريباً)
    user = update.effective_user
    leaves_ref = db.reference('/leaves')
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
        await query.edit_message_text("حدث خطأ: لا يمكن العثور على مدير الموارد البشرية.")
        context.user_data.clear()
        return ConversationHandler.END

    hr_message = (
        f"📣 طلب إجازة جديد 📣\n\n"
        f"من الموظف: {context.user_data['employee_name']}\n"
        f"السبب: {context.user_data['leave_reason']}\n"
        f"التاريخ/المدة: {context.user_data['final_date_info']}\n\n"
        "الرجاء اتخاذ إجراء:"
    )
    keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_{request_id}"), InlineKeyboardButton("❌ رفض", callback_data=f"reject_{request_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(chat_id=hr_chat_id, text=hr_message, reply_markup=reply_markup)
        await query.edit_message_text("✅ تم إرسال طلبك بنجاح. سيتم إعلامك بالقرار.")
    except Exception as e:
        logger.error(f"Failed to send message to HR: {e}")
        await query.edit_message_text("حدث خطأ أثناء إرسال الطلب.")

    context.user_data.clear()
    return ConversationHandler.END

async def hr_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (تبقى كما هي)
    query = update.callback_query
    await query.answer()
    action, request_id = query.data.split("_", 1)
    leave_ref = db.reference(f'/leaves/{request_id}')
    leave_request = leave_ref.get()

    if not leave_request or leave_request.get("status") != "pending":
        await query.edit_message_text("هذا الطلب لم يعد متاحاً أو تمت معالجته بالفعل.")
        return

    date_info = leave_request.get('date_info', 'غير محدد')

    if action == "approve":
        leave_ref.update({"status": "approved"})
        response_text = "✅ تمت الموافقة على الطلب."
        await context.bot.send_message(chat_id=leave_request["employee_telegram_id"], text=f"تهانينا! تمت الموافقة على طلب إجازتك لـِ: {date_info}.")
        
        leader_ids = get_all_team_leaders_ids()
        if leader_ids:
            for leader_id in leader_ids:
                try:
                    await context.bot.send_message(
                        chat_id=leader_id,
                        text=f"🔔 تنبيه: الموظف ({leave_request.get('employee_name')}) سيكون في إجازة: {date_info}."
                    )
                except Exception as e:
                    logger.error(f"Failed to send message to Team Leader {leader_id}: {e}")
            response_text += "\nتم إرسال إشعار لقادة الفرق."
    else: # reject
        leave_ref.update({"status": "rejected"})
        response_text = "❌ تم رفض الطلب."
        await context.bot.send_message(chat_id=leave_request["employee_telegram_id"], text=f"للأسف، تم رفض طلب إجازتك لـِ: {date_info}.")
    
    original_message = query.message.text
    await query.edit_message_text(text=f"{original_message}\n\n--- [ {response_text} ] ---")

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("تم إلغاء العملية.")
    context.user_data.clear()
    return ConversationHandler.END

def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_request_from_button, pattern="^start_request$")],
        states={
            ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_name)],
            ENTERING_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_reason)],
            CHOOSING_DURATION_TYPE: [CallbackQueryHandler(choose_duration_type, pattern="^duration_")],
            SELECTING_DATES: [CallbackQueryHandler(calendar_callback_handler, pattern="^CAL_")],
            CONFIRMING_LEAVE: [CallbackQueryHandler(confirm_leave, pattern="^confirm_send$")],
        },
        fallbacks=[CallbackQueryHandler(cancel_conversation, pattern="^cancel$")],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(hr_action_handler, pattern="^(approve|reject)_"))

    print("Bot is running with Advanced Calendar Options...")
    application.run_polling()


if __name__ == "__main__":
    main()
