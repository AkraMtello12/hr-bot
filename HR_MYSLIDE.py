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
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8022986919:AAEPa_fgGad_MbmR5i35ZmBLWGgC8G1xmIo")
FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL", "https://hr-myslide-default-rtdb.europe-west1.firebasedatabase.app") 

# --- إعداد اتصال Firebase (يعمل على Render/Railway وعلى الجهاز المحلي) ---
try:
    firebase_creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if firebase_creds_json:
        print("Found Firebase credentials in environment variable.")
        cred_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(cred_dict)
    else:
        print("Using local 'firebase-credentials.json' file.")
        FIREBASE_CREDENTIALS_FILE = "firebase-credentials.json"
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_FILE)

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {
            'databaseURL': FIREBASE_DATABASE_URL
        })
    print("Firebase connected successfully!")
except Exception as e:
    print(f"Error connecting to Firebase: {e}")
    exit()

# إعداد التسجيل لرؤية الأخطاء
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# حالات المحادثة
(
    ENTERING_NAME,
    ENTERING_REASON,
    SELECTING_DATE_RANGE,
    CONFIRMING_LEAVE,
) = range(4)


# --- دوال إنشاء التقويم التفاعلي ---
def create_calendar(year: int, month: int, start_date: date | None = None) -> InlineKeyboardMarkup:
    cal = calendar.Calendar()
    month_name = calendar.month_name[month]
    today = date.today()
    
    header_row = [
        InlineKeyboardButton("<", callback_data=f"CAL_NAV_{year}_{month-1}" if month > 1 else f"CAL_NAV_{year-1}_12"),
        InlineKeyboardButton(f"{month_name} {year}", callback_data="CAL_IGNORE"),
        InlineKeyboardButton(">", callback_data=f"CAL_NAV_{year}_{month+1}" if month < 12 else f"CAL_NAV_{year+1}_1"),
    ]
    
    days_row = [InlineKeyboardButton(day, callback_data="CAL_IGNORE") for day in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]]
    keyboard = [header_row, days_row]
    
    for week in cal.monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
            else:
                current_day = date(year, month, day)
                is_disabled = current_day < today or (start_date and current_day < start_date)
                day_text = str(day)
                if start_date and current_day == start_date:
                    day_text = f"[{day}]"

                if is_disabled:
                    row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
                else:
                    row.append(InlineKeyboardButton(day_text, callback_data=f"CAL_DAY_{year}_{month}_{day}"))
        keyboard.append(row)
        
    return InlineKeyboardMarkup(keyboard)

# --- دوال مساعدة أخرى ---
def get_predefined_user(telegram_id: str) -> dict | None:
    ref = db.reference('/users')
    users = ref.get()
    if not users: return None
    for user_data in users.values():
        if user_data and str(user_data.get("telegram_id", "")) == telegram_id:
            return user_data
    return None

def get_all_team_leaders_ids() -> list:
    leader_ids = []
    ref = db.reference('/users')
    users = ref.get()
    if not users: return []
    for user_data in users.values():
        if user_data and user_data.get("role") == "team_leader":
            leader_ids.append(user_data.get("telegram_id"))
    return leader_ids

def get_hr_telegram_id() -> str | None:
    ref = db.reference('/users')
    users = ref.get()
    if not users: return None
    for user_data in users.values():
        if user_data and user_data.get("role") == "hr":
            return user_data.get("telegram_id")
    return None

# --- معالجات الأوامر والمحادثة ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    today = date.today()
    await update.message.reply_text(
        "تم تسجيل السبب. الآن الرجاء اختيار تاريخ **البدء** من التقويم:",
        reply_markup=create_calendar(today.year, today.month)
    )
    return SELECTING_DATE_RANGE

async def calendar_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    logger.info(f"Calendar callback received: {callback_data}")

    parts = callback_data.split("_")
    action = parts[1]

    if action == "DAY":
        year, month, day = map(int, parts[2:])
        selected_day = date(year, month, day)

        if 'start_date' not in context.user_data:
            context.user_data['start_date'] = selected_day
            await query.edit_message_text(
                f"تاريخ البدء المحدد: {selected_day.strftime('%d/%m/%Y')}\n\n"
                "الآن الرجاء اختيار تاريخ **الانتهاء** من التقويم:",
                reply_markup=create_calendar(selected_day.year, selected_day.month, start_date=selected_day)
            )
            return SELECTING_DATE_RANGE
        else:
            start_date = context.user_data['start_date']
            end_date = selected_day
            
            if end_date < start_date:
                await context.bot.answer_callback_query(query.id, "تاريخ الانتهاء يجب أن يكون بعد تاريخ البدء!", show_alert=True)
                return SELECTING_DATE_RANGE
                
            context.user_data['end_date'] = end_date
            final_date_str = f"من {start_date.strftime('%d/%m/%Y')} إلى {end_date.strftime('%d/%m/%Y')}"
            context.user_data['leave_date_range'] = final_date_str

            await query.edit_message_text(f"تم اختيار المدة: {final_date_str}")
            
            summary = (
                f"--- ملخص الطلب ---\n"
                f"اسم الموظف: {context.user_data['employee_name']}\n"
                f"سبب الإجازة: {context.user_data['leave_reason']}\n"
                f"المدة: {final_date_str}\n\n"
                "هل تريد تأكيد الطلب وإرساله للموارد البشرية؟"
            )
            keyboard = [[InlineKeyboardButton("✅ تأكيد وإرسال", callback_data="confirm_send"), InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(summary, reply_markup=reply_markup)
            return CONFIRMING_LEAVE

    elif action == "NAV":
        year, month = map(int, parts[2:])
        start_date = context.user_data.get('start_date')
        await query.edit_message_text(
            query.message.text,
            reply_markup=create_calendar(year, month, start_date=start_date)
        )
        return SELECTING_DATE_RANGE
        
    elif action == "IGNORE":
        return SELECTING_DATE_RANGE

async def confirm_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("تم إلغاء الطلب.")
        context.user_data.clear()
        return ConversationHandler.END

    user = update.effective_user
    leaves_ref = db.reference('/leaves')
    new_leave_ref = leaves_ref.push()
    request_id = new_leave_ref.key
    
    new_leave_ref.set({
        "employee_name": context.user_data['employee_name'],
        "employee_telegram_id": str(user.id),
        "reason": context.user_data['leave_reason'],
        "date_range": context.user_data['leave_date_range'],
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
        f"المدة: {context.user_data['leave_date_range']}\n\n"
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
    query = update.callback_query
    await query.answer()
    action, request_id = query.data.split("_", 1)
    leave_ref = db.reference(f'/leaves/{request_id}')
    leave_request = leave_ref.get()

    if not leave_request or leave_request.get("status") != "pending":
        await query.edit_message_text("هذا الطلب لم يعد متاحاً أو تمت معالجته بالفعل.")
        return

    date_info = leave_request.get('date_range', 'غير محدد')

    if action == "approve":
        leave_ref.update({"status": "approved"})
        response_text = "✅ تمت الموافقة على الطلب."
        await context.bot.send_message(chat_id=leave_request["employee_telegram_id"], text=f"تهانينا! تمت الموافقة على طلب إجازتك للمدة {date_info}.")
        
        leader_ids = get_all_team_leaders_ids()
        if leader_ids:
            for leader_id in leader_ids:
                try:
                    await context.bot.send_message(
                        chat_id=leader_id,
                        text=f"🔔 تنبيه: الموظف ({leave_request.get('employee_name')}) سيكون في إجازة خلال المدة: {date_info}."
                    )
                except Exception as e:
                    logger.error(f"Failed to send message to Team Leader {leader_id}: {e}")
            response_text += "\nتم إرسال إشعار لقادة الفرق."
    else: # reject
        leave_ref.update({"status": "rejected"})
        response_text = "❌ تم رفض الطلب."
        await context.bot.send_message(chat_id=leave_request["employee_telegram_id"], text=f"للأسف، تم رفض طلب إجازتك للمدة {date_info}.")
    
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
            SELECTING_DATE_RANGE: [CallbackQueryHandler(calendar_callback_handler, pattern="^CAL_")],
            CONFIRMING_LEAVE: [CallbackQueryHandler(confirm_leave, pattern="^confirm_send$")],
        },
        fallbacks=[CallbackQueryHandler(cancel_conversation, pattern="^cancel$")],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(hr_action_handler, pattern="^(approve|reject)_"))

    print("Bot is running with Date Range Calendar...")
    application.run_polling()


if __name__ == "__main__":
    main()
