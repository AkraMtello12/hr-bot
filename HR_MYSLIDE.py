# -*- coding: utf-8 -*-

import logging

from datetime import datetime, date, time

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



# حالات محادثة الإجازة اليومية

(

    FD_ENTERING_NAME,

    FD_ENTERING_REASON,

    FD_CHOOSING_DURATION_TYPE,

    FD_SELECTING_DATES,

    FD_CONFIRMING_LEAVE,

) = range(5)



# حالات محادثة الإجازة الساعية

(

    HL_CHOOSING_TYPE,

    HL_SELECTING_TIME,

    HL_ENTERING_NAME,

    HL_ENTERING_REASON,

    HL_CONFIRMING_LEAVE,

) = range(5, 10)





# --- دوال إنشاء التقويم ---

def create_advanced_calendar(year: int, month: int, selection_mode: str, selected_dates: list) -> InlineKeyboardMarkup:

    # ... (This function remains the same)

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



# --- دوال إنشاء أزرار الوقت (محدثة) ---

def create_time_keyboard(leave_type: str) -> InlineKeyboardMarkup:

    keyboard = []

    if leave_type == 'late':

        # أوقات الوصول المتأخر الجديدة (9:30 - 14:00)

        keyboard = [

            [InlineKeyboardButton("9:30 AM", callback_data="TIME_9:30 AM"), InlineKeyboardButton("10:00 AM", callback_data="TIME_10:00 AM")],

            [InlineKeyboardButton("10:30 AM", callback_data="TIME_10:30 AM"), InlineKeyboardButton("11:00 AM", callback_data="TIME_11:00 AM")],

            [InlineKeyboardButton("11:30 AM", callback_data="TIME_11:30 AM"), InlineKeyboardButton("12:00 PM", callback_data="TIME_12:00 PM")],

            [InlineKeyboardButton("12:30 PM", callback_data="TIME_12:30 PM"), InlineKeyboardButton("1:00 PM", callback_data="TIME_1:00 PM")],

            [InlineKeyboardButton("1:30 PM", callback_data="TIME_1:30 PM"), InlineKeyboardButton("2:00 PM", callback_data="TIME_2:00 PM")],

        ]

    elif leave_type == 'early':

        # أوقات المغادرة المبكرة الجديدة (11:00 - 15:30)

        keyboard = [

            [InlineKeyboardButton("11:00 AM", callback_data="TIME_11:00 AM"), InlineKeyboardButton("11:30 AM", callback_data="TIME_11:30 AM")],

            [InlineKeyboardButton("12:00 PM", callback_data="TIME_12:00 PM"), InlineKeyboardButton("12:30 PM", callback_data="TIME_12:30 PM")],

            [InlineKeyboardButton("1:00 PM", callback_data="TIME_1:00 PM"), InlineKeyboardButton("1:30 PM", callback_data="TIME_1:30 PM")],

            [InlineKeyboardButton("2:00 PM", callback_data="TIME_2:00 PM"), InlineKeyboardButton("2:30 PM", callback_data="TIME_2:30 PM")],

            [InlineKeyboardButton("3:00 PM", callback_data="TIME_3:00 PM"), InlineKeyboardButton("3:30 PM", callback_data="TIME_3:30 PM")],

        ]

    return InlineKeyboardMarkup(keyboard)





# --- دوال مساعدة أخرى ---

def get_predefined_user(telegram_id: str):

    ref = db.reference('/users')

    users = ref.get() or {}

    for user_data in users.values():

        if user_data and str(user_data.get("telegram_id", "")) == telegram_id:

            return user_data

    return None



def get_all_team_leaders_ids():

    leader_ids = []

    ref = db.reference('/users')

    users = ref.get() or {}

    for user_data in users.values():

        if user_data and user_data.get("role") == "team_leader":

            leader_ids.append(user_data.get("telegram_id"))

    return leader_ids



def get_hr_telegram_id():

    ref = db.reference('/users')

    users = ref.get() or {}

    for user_data in users.values():

        if user_data and user_data.get("role") == "hr":

            return user_data.get("telegram_id")

    return None



# --- معالجات الأوامر الرئيسية ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    user = update.effective_user

    predefined_user = get_predefined_user(str(user.id))

    if predefined_user:

        # رسائل ترحيب للمدراء

        role = predefined_user.get("role")

        if role == "hr":

            await update.message.reply_text(f"أهلاً بك يا {user.first_name}! أنت مسجل كمدير الموارد البشرية.")

        elif role == "team_leader":

            await update.message.reply_text(f"أهلاً بك يا {user.first_name}! أنت مسجل كقائد فريق.")

    else:

        # الواجهة الرئيسية للموظف

        keyboard = [

            [InlineKeyboardButton("🕒 إجازة ساعية", callback_data="start_hourly_leave")],

            [InlineKeyboardButton("🗓️ طلب إجازة", callback_data="start_full_day_leave")]

        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(

            f"أهلاً بك يا {user.first_name} في بوت طلبات الإجازة. الرجاء اختيار نوع الطلب:",

            reply_markup=reply_markup

        )

# ---- بداية معالج محادثة الإجازة الساعية ----

async def start_hourly_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    query = update.callback_query

    await query.answer()

    keyboard = [

        [InlineKeyboardButton("🌅 بداية الدوام (تأخير)", callback_data="hourly_late")],

        [InlineKeyboardButton("🌇 نهاية الدوام (مغادرة مبكرة)", callback_data="hourly_early")]

    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text("اختر نوع الإجازة الساعية:", reply_markup=reply_markup)

    return HL_CHOOSING_TYPE



async def choose_hourly_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    query = update.callback_query

    await query.answer()

    leave_type = query.data.split('_')[1] # late or early

    context.user_data['hourly_leave_type'] = leave_type

    

    message = "متى ستصل إلى الدوام؟" if leave_type == 'late' else "متى ستغادر من الدوام؟"

    

    await query.edit_message_text(

        text=message,

        reply_markup=create_time_keyboard(leave_type)

    )

    return HL_SELECTING_TIME



async def select_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    query = update.callback_query

    await query.answer()

    selected_time = query.data.split('_', 1)[1]

    context.user_data['selected_time'] = selected_time

    

    leave_type = context.user_data['hourly_leave_type']

    type_text = "تأخير صباحي" if leave_type == 'late' else "مغادرة مبكرة"

    

    await query.edit_message_text(f"تم اختيار: {type_text} - الساعة {selected_time}.")

    await query.message.reply_text("الرجاء إدخال اسمك الكامل:")

    return HL_ENTERING_NAME



async def enter_hourly_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    context.user_data['employee_name'] = update.message.text

    await update.message.reply_text("شكراً لك. الآن الرجاء إدخال سبب الإجازة الساعية:")

    return HL_ENTERING_REASON



async def enter_hourly_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    context.user_data['hourly_reason'] = update.message.text

    

    leave_type = context.user_data['hourly_leave_type']

    type_text = "الوصول الساعة" if leave_type == 'late' else "المغادرة الساعة"

    

    summary = (

        f"--- ملخص طلب إجازة ساعية ---\n"

        f"اسم الموظف: {context.user_data['employee_name']}\n"

        f"السبب: {context.user_data['hourly_reason']}\n"

        f"التاريخ: {date.today().strftime('%d/%m/%Y')}\n"

        f"الوقت: {type_text} {context.user_data['selected_time']}\n\n"

        "هل تريد تأكيد الطلب؟"

    )

    keyboard = [[InlineKeyboardButton("✅ تأكيد", callback_data="confirm_send"), InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(summary, reply_markup=reply_markup)

    return HL_CONFIRMING_LEAVE



async def confirm_hourly_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    query = update.callback_query

    await query.answer()



    if query.data == "cancel":

        await query.edit_message_text("تم إلغاء الطلب.")

        context.user_data.clear()

        return ConversationHandler.END



    user = update.effective_user

    leaves_ref = db.reference('/hourly_leaves') # حفظ في قسم منفصل

    new_leave_ref = leaves_ref.push()

    request_id = new_leave_ref.key

    

    leave_type = context.user_data['hourly_leave_type']

    type_text = "تأخير صباحي" if leave_type == 'late' else "مغادرة مبكرة"

    

    new_leave_ref.set({

        "employee_name": context.user_data['employee_name'],

        "employee_telegram_id": str(user.id),

        "reason": context.user_data['hourly_reason'],

        "date": date.today().strftime('%d/%m/%Y'),

        "time_info": f"{type_text} - {context.user_data['selected_time']}",

        "status": "pending",

        "request_time": datetime.now().isoformat(),

    })



    hr_chat_id = get_hr_telegram_id()

    if not hr_chat_id:

        await query.edit_message_text("خطأ: لا يمكن العثور على مدير الموارد البشرية.")

        return ConversationHandler.END



    hr_message = (

        f"📣 طلب إجازة ساعية جديد 📣\n\n"

        f"من الموظف: {context.user_data['employee_name']}\n"

        f"السبب: {context.user_data['hourly_reason']}\n"

        f"التفاصيل: {type_text} اليوم الساعة {context.user_data['selected_time']}\n\n"

        "الرجاء اتخاذ إجراء:"

    )

    keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_hourly_{request_id}"), InlineKeyboardButton("❌ رفض", callback_data=f"reject_hourly_{request_id}")]]

    reply_markup = InlineKeyboardMarkup(keyboard)



    try:

        await context.bot.send_message(chat_id=hr_chat_id, text=hr_message, reply_markup=reply_markup)

        await query.edit_message_text("✅ تم إرسال طلبك بنجاح.")

    except Exception as e:

        logger.error(f"Failed to send hourly leave to HR: {e}")

        await query.edit_message_text("حدث خطأ أثناء إرسال الطلب.")



    context.user_data.clear()

    return ConversationHandler.END



# ---- نهاية معالج محادثة الإجازة الساعية ----



# ---- بداية معالج محادثة الإجازة اليومية ----

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

    keyboard = [

        [InlineKeyboardButton("🗓️ يوم واحد", callback_data="duration_single")],

        [InlineKeyboardButton("🔁 أيام متتالية", callback_data="duration_range")],

        [InlineKeyboardButton("➕ أيام متفرقة", callback_data="duration_multiple")],

    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("تم تسجيل السبب. الآن، كيف هي مدة إجازتك؟", reply_markup=reply_markup)

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



    if query.data == "cancel":

        await query.edit_message_text("تم إلغاء الطلب.")

        context.user_data.clear()

        return ConversationHandler.END



    user = update.effective_user

    leaves_ref = db.reference('/full_day_leaves') # حفظ في قسم منفصل

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

        

        # --- التعديل: إرسال إشعار لقادة الفرق في كلتا الحالتين ---

        leader_ids = get_all_team_leaders_ids()

        if leader_ids:

            # تخصيص رسالة الإشعار بناءً على نوع الإجازة

            notification_message = f"🔔 تنبيه: الموظف ({employee_name}) لديه إذن لـِ: {date_info}."

            

            for leader_id in leader_ids:

                try:

                    await context.bot.send_message(chat_id=leader_id, text=notification_message)

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

    

    # معالج محادثة الإجازة اليومية

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

    

    # معالج محادثة الإجازة الساعية

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

    # تعديل النمط للتمييز بين نوعي الإجازة في رد المدير

    application.add_handler(CallbackQueryHandler(hr_action_handler, pattern="^(approve|reject)_(fd|hourly)_"))



    print("Bot is running with DUAL leave system (Full-day & Hourly)...")

    application.run_polling()



if __name__ == "__main__":

    main()
