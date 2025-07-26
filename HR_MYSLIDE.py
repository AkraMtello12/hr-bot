# -*- coding: utf-8 -*-
import logging
from datetime import datetime, date, timedelta, time
import calendar
import os
import json
import pytz # <-- إضافة جديدة للتعامل مع المناطق الزمنية
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
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
# يتم جلب توكن التليجرام ورابط قاعدة بيانات Firebase من متغيرات البيئة
# أو استخدام قيم افتراضية إذا لم تكن موجودة.
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
FIREBASE_DATABASE_URL = os.getenv("FIREBASE_DATABASE_URL", "https://hr-myslide-default-rtdb.europe-west1.firebasedatabase.app")

# --- إعداد اتصال Firebase ---
# محاولة الاتصال بقاعدة بيانات Firebase باستخدام بيانات الاعتماد.
# يتم البحث عن بيانات الاعتماد كمتغير بيئة JSON أو كملف محلي.
try:
    firebase_creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if firebase_creds_json:
        print("INFO: Reading Firebase credentials from environment variable.")
        cred_dict = json.loads(firebase_creds_json)
        cred = credentials.Certificate(cred_dict)
    else:
        print("INFO: Using local 'firebase-credentials.json' file.")
        cred = credentials.Certificate("firebase-credentials.json")

    # تهيئة تطبيق Firebase إذا لم يكن مهيئًا بالفعل
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_DATABASE_URL})
    print("SUCCESS: Firebase connected successfully!")
except Exception as e:
    # طباعة رسالة خطأ والخروج إذا فشل الاتصال بـ Firebase
    print(f"ERROR: Could not connect to Firebase. Reason: {e}")
    exit()

# إعداد التسجيل لرؤية الأخطاء والمشاكل
# يتم تكوين نظام التسجيل (logging) لعرض الرسائل المعلوماتية والأخطاء.
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- تعريف حالات المحادثات الموحدة ---
# تحديد حالات المحادثة المختلفة لـ ConversationHandler.
# كل حالة تمثل خطوة معينة في تدفق المحادثة.
(
    CHOOSING_ACTION,
    # حالات الإجازة اليومية
    FD_ENTERING_NAME, FD_ENTERING_REASON, FD_CHOOSING_DURATION_TYPE, FD_SELECTING_DATES, FD_CONFIRMING_LEAVE,
    # حالات الإذن الساعي
    HL_CHOOSING_TYPE, HL_SELECTING_DATE, HL_SELECTING_TIME, HL_ENTERING_NAME, HL_ENTERING_REASON, HL_CONFIRMING_LEAVE,
    # حالات صندوق الاقتراحات
    SUGGESTION_ENTERING, SUGGESTION_CONFIRMING_ANONYMITY
) = range(14)

# --- دوال إنشاء واجهات المستخدم (التقويم والأزرار) ---
def create_advanced_calendar(year: int, month: int, selection_mode: str, selected_dates: list, back_callback: str) -> InlineKeyboardMarkup:
    """
    إنشاء تقويم تفاعلي مع أزرار تنقل وزر رجوع.
    يسمح باختيار تاريخ واحد، نطاق من التواريخ، أو تواريخ متعددة.
    """
    cal = calendar.Calendar()
    # أسماء الشهور باللغة العربية
    month_names_ar = ["", "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
    month_name = month_names_ar[month]
    today = date.today()
    keyboard = []

    # صف الرأس للتقويم (أزرار التنقل بين الشهور واسم الشهر والسنة)
    header_row = [
        InlineKeyboardButton("‹", callback_data=f"CAL_NAV_{year}_{month-1}" if month > 1 else f"CAL_NAV_{year-1}_12"),
        InlineKeyboardButton(f"{month_name} {year}", callback_data="CAL_IGNORE"), # زر غير تفاعلي لعرض الشهر والسنة
        InlineKeyboardButton("›", callback_data=f"CAL_NAV_{year}_{month+1}" if month < 12 else f"CAL_NAV_{year+1}_1"),
    ]
    keyboard.append(header_row)

    # صف أسماء الأيام (غير تفاعلي)
    # تم تعديل أسماء الأيام لتكون أكثر شيوعاً في الاستخدام العربي
    days_row = [InlineKeyboardButton(day, callback_data="CAL_IGNORE") for day in ["إثنين", "ثلاثاء", "أربعاء", "خميس", "جمعة", "سبت", "أحد"]]
    keyboard.append(days_row)

    # إضافة أيام الشهر إلى التقويم
    for week in cal.monthdayscalendar(year, month):
        row = []
        for day_num in week:
            if day_num == 0:
                # أيام خارج الشهر الحالي
                row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
            else:
                current_day = date(year, month, day_num)
                # تعطيل الأيام الماضية أو الأيام التي تسبق تاريخ البدء في وضع النطاق
                is_disabled = current_day < today or (selection_mode == 'range' and selected_dates and current_day < selected_dates[0])
                day_text = str(day_num)
                # تمييز الأيام المختارة
                if current_day in selected_dates:
                    day_text = f"*{day_num}*"

                if is_disabled:
                    row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE")) # زر فارغ للأيام المعطلة
                else:
                    row.append(InlineKeyboardButton(day_text, callback_data=f"CAL_DAY_{year}_{month}_{day_num}"))
        keyboard.append(row)

    # زر "تم الاختيار" لوضع الاختيار المتعدد
    if selection_mode == 'multiple' and selected_dates:
        keyboard.append([InlineKeyboardButton("✅ تم الاختيار", callback_data="CAL_DONE")])

    # أزرار الرجوع والقائمة الرئيسية
    keyboard.append([InlineKeyboardButton("➡️ رجوع", callback_data=back_callback), InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def create_weekly_calendar(start_date: date, back_callback: str) -> InlineKeyboardMarkup:
    """
    إنشاء تقويم لمدة أسبوع واحد بدءًا من تاريخ محدد.
    يتم تعطيل الأيام الماضية.
    """
    keyboard = []
    # أسماء الأيام باللغة العربية
    days_ar = ["إثنين", "ثلاثاء", "أربعاء", "خميس", "جمعة", "سبت", "أحد"]
    
    row1 = []
    row2 = []
    for i in range(7):
        current_day = start_date + timedelta(days=i)
        day_name = days_ar[current_day.weekday()]
        button_text = f"{day_name} {current_day.day}"
        callback_data = f"HL_DATE_{current_day.isoformat()}"
        
        # تعطيل الأيام الماضية
        if current_day < date.today():
            if len(row1) < 4:
                row1.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
            else:
                row2.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
        else:
            if len(row1) < 4:
                row1.append(InlineKeyboardButton(button_text, callback_data=callback_data))
            else:
                row2.append(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    keyboard.append(row1)
    if row2: # إضافة الصف الثاني فقط إذا كان يحتوي على أزرار
        keyboard.append(row2)
    
    # أزرار الرجوع والقائمة الرئيسية
    keyboard.append([InlineKeyboardButton("➡️ رجوع", callback_data=back_callback), InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(keyboard)


def create_time_keyboard(leave_type: str, back_callback: str) -> InlineKeyboardMarkup:
    """
    إنشاء لوحة مفاتيح لاختيار الوقت مع زر رجوع.
    تختلف خيارات الوقت بناءً على نوع الإذن (تأخير صباحي أو مغادرة مبكرة).
    """
    keyboard = []
    if leave_type == 'late':
        keyboard = [
            [InlineKeyboardButton("9:30 ص", callback_data="TIME_9:30 AM"), InlineKeyboardButton("10:00 ص", callback_data="TIME_10:00 AM")],
            [InlineKeyboardButton("10:30 ص", callback_data="TIME_10:30 AM"), InlineKeyboardButton("11:00 ص", callback_data="TIME_11:00 AM")],
            [InlineKeyboardButton("11:30 ص", callback_data="TIME_11:30 AM"), InlineKeyboardButton("12:00 م", callback_data="TIME_12:00 PM")],
            [InlineKeyboardButton("12:30 م", callback_data="TIME_12:30 PM"), InlineKeyboardButton("1:00 م", callback_data="TIME_1:00 PM")],
            [InlineKeyboardButton("1:30 م", callback_data="TIME_1:30 PM"), InlineKeyboardButton("2:00 م", callback_data="TIME_2:00 PM")],
        ]
    elif leave_type == 'early':
        keyboard = [
            [InlineKeyboardButton("11:00 ص", callback_data="TIME_11:00 AM"), InlineKeyboardButton("11:30 ص", callback_data="TIME_11:30 AM")],
            [InlineKeyboardButton("12:00 م", callback_data="TIME_12:00 PM"), InlineKeyboardButton("12:30 م", callback_data="TIME_12:30 PM")],
            [InlineKeyboardButton("1:00 م", callback_data="TIME_1:00 PM"), InlineKeyboardButton("1:30 م", callback_data="TIME_1:30 PM")],
            [InlineKeyboardButton("2:00 م", callback_data="TIME_2:00 PM"), InlineKeyboardButton("2:30 م", callback_data="TIME_2:30 PM")],
            [InlineKeyboardButton("3:00 م", callback_data="TIME_3:00 PM"), InlineKeyboardButton("3:30 م", callback_data="TIME_3:30 PM")],
        ]
    
    # أزرار الرجوع والقائمة الرئيسية
    keyboard.append([InlineKeyboardButton("➡️ رجوع", callback_data=back_callback), InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

# --- دوال مساعدة (قاعدة البيانات) ---
def get_predefined_user(telegram_id: str):
    """جلب بيانات المستخدم المعرف مسبقاً من Firebase بناءً على Telegram ID."""
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
    """جلب جميع معرفات Telegram لقادة الفرق من Firebase."""
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
    """جلب معرف Telegram لمدير الموارد البشرية من Firebase."""
    try:
        ref = db.reference('/users')
        users = ref.get() or {}
        for user_data in users.values():
            if user_data and user_data.get("role") == "hr":
                return user_data.get("telegram_id")
    except Exception as e:
        logger.error(f"Error fetching HR ID: {e}")
    return None

# --- دوال المحادثة الرئيسية ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    نقطة البداية الرئيسية للبوت ومُنشئ القائمة الرئيسية.
    تختلف القائمة المعروضة بناءً على دور المستخدم (موظف عادي، قائد فريق، موارد بشرية).
    """
    user = update.effective_user
    predefined_user = get_predefined_user(str(user.id))

    # منطق مدير الموارد البشرية: يتلقى الإشعارات ولا يستخدم القائمة لتقديم الطلبات
    if predefined_user and predefined_user.get("role") == "hr":
        # استخدام update.message.reply_text إذا كان التفاعل الأول رسالة، وإلا update.callback_query.edit_message_text
        if update.message:
            await update.message.reply_text(
                f"أهلاً وسهلاً، {user.first_name}! تم تسجيل دخولك بصلاحيات [مدير الموارد البشرية].\n\n"
                "سوف تتلقى هنا طلبات الإجازات والأذونات والاقتراحات للموافقة عليها أو رفضها."
            )
        elif update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                f"أهلاً وسهلاً، {user.first_name}! تم تسجيل دخولك بصلاحيات [مدير الموارد البشرية].\n\n"
                "سوف تتلقى هنا طلبات الإجازات والأذونات والاقتراحات للموافقة عليها أو رفضها."
            )
        return ConversationHandler.END # مدير الموارد البشرية لا يمر عبر تدفق المحادثة العادي

    # تحديد القائمة بناءً على الدور
    if predefined_user and predefined_user.get("role") == "team_leader":
        # قائمة قادة الفرق
        keyboard = [
            [InlineKeyboardButton("💡 صندوق الاقتراحات والشكاوي", callback_data="req_suggestion")]
        ]
        message_text = f"أهلاً بك يا قائد الفريق {user.first_name}!\n\nيمكنك استخدام صندوق الاقتراحات والشكاوي للتواصل المباشر مع الموارد البشرية."
    else:
        # قائمة الموظفين العاديين
        keyboard = [
            [InlineKeyboardButton("🕒 طلب إذن (ساعي)", callback_data="req_hourly")],
            [InlineKeyboardButton("🗓️ طلب إجازة (يومي)", callback_data="req_daily")],
            [InlineKeyboardButton("💡 صندوق الاقتراحات والشكاوي", callback_data="req_suggestion")]
        ]
        message_text = f"أهلاً بك {user.first_name} في نظام طلبات الإجازة والأذونات.\n\nاختر الخدمة التي تريدها من القائمة أدناه:"

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # إرسال أو تعديل الرسالة مع القائمة
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=message_text, reply_markup=reply_markup)
        
    return CHOOSING_ACTION

# ---- مسار صندوق الاقتراحات والشكاوي ----
async def start_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يبدأ تدفق صندوق الاقتراحات، ويطلب من المستخدم إدخال رسالته."""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "أهلاً بك في صندوق الاقتراحات والشكاوي.\n\n"
        "يرجى كتابة رسالتك كاملة هنا. سيتم إرسالها إلى مدير الموارد البشرية."
        "\n\n*ملاحظة: سيتم إرسال رسالتك كمجهول. إذا كنت ترغب في إرسالها باسمك، يرجى كتابة اسمك ضمن نص الرسالة.*", # ملاحظة جديدة
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN # لتنسيق الملاحظة
    )
    return SUGGESTION_ENTERING

async def enter_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """يستقبل رسالة المستخدم ويعرض خيارات الخصوصية (الآن فقط خيار مجهول)."""
    message_text = update.message.text
    context.user_data['suggestion_text'] = message_text

    keyboard = [
        [InlineKeyboardButton("🔒 إرسال كرسالة مجهولة", callback_data="sugg_anonymous")], # تم إزالة خيار إظهار الاسم
        [InlineKeyboardButton("➡️ رجوع (لتعديل الرسالة)", callback_data="sugg_back_to_edit")],
        [InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")] # زر الرجوع للقائمة الرئيسية
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "شكراً لك على رسالتك. يرجى تأكيد الإرسال:", # تم تعديل النص ليناسب الخيار الوحيد
        reply_markup=reply_markup
    )
    return SUGGESTION_CONFIRMING_ANONYMITY

async def confirm_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يؤكد الإرسال، يحفظ الاقتراح في Firebase، ويرسله إلى مدير الموارد البشرية.
    يتم الإرسال دائمًا بشكل مجهول الآن.
    """
    query = update.callback_query
    await query.answer()
    
    # لم نعد بحاجة للتحقق من 'choice' لأن الخيار الوحيد هو 'sugg_anonymous'
    suggestion_text = context.user_data.get('suggestion_text')
    if not suggestion_text:
        await query.edit_message_text("حدث خطأ ما: لم يتم العثور على نص الاقتراح. يرجى المحاولة مرة أخرى من البداية.")
        return await start(update, context)

    user = update.effective_user
    hr_chat_id = get_hr_telegram_id()

    if not hr_chat_id:
        await query.edit_message_text("⚠️ خطأ إداري: لا يمكن العثور على حساب مدير الموارد البشرية. لم يتم إرسال الرسالة. يرجى التواصل مع الإدارة.")
        return ConversationHandler.END

    # دائماً يتم الإرسال كمجهول
    sender_info = "المرسل: رسالة من موظف (مجهول)"
    sender_name_for_db = "Anonymous"
    sender_id_for_db = 'N/A' # لا يتم حفظ ID المستخدم للرسائل المجهولة
    
    hr_message = f"📬 رسالة جديدة في صندوق الاقتراحات 📬\n\n**{sender_info}**\n\n---\n{suggestion_text}\n---"
    
    # حفظ في Firebase
    try:
        suggestions_ref = db.reference('/suggestions')
        suggestions_ref.push().set({
            'message': suggestion_text,
            'sender_name': sender_name_for_db,
            'sender_id': sender_id_for_db,
            'sent_at': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Firebase error saving suggestion: {e}")
        await query.edit_message_text("حدث خطأ أثناء حفظ رسالتك. يرجى المحاولة لاحقًا.")
        return ConversationHandler.END

    # إرسال إلى الموارد البشرية
    try:
        await context.bot.send_message(chat_id=hr_chat_id, text=hr_message, parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text("✅ تم إرسال رسالتك بنجاح. شكراً لمساهمتك.")
    except Exception as e:
        logger.error(f"Failed to send suggestion to HR: {e}")
        await query.edit_message_text("حدث خطأ أثناء إرسال الرسالة إلى المدير. يرجى المحاولة لاحقًا.")

    context.user_data.clear() # مسح بيانات المستخدم بعد اكتمال العملية
    return ConversationHandler.END


# ---- مسار طلب الإجازة الساعية (الإذن) ----
async def start_hourly_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الأولى: اختيار نوع الإذن (تأخير صباحي أو مغادرة مبكرة)."""
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
    """الخطوة الثانية: طلب اختيار تاريخ الإذن من التقويم الأسبوعي."""
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
    """الخطوة الثالثة: معالجة اختيار التاريخ وطلب تحديد الوقت."""
    query = update.callback_query
    await query.answer()
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
    """الخطوة الرابعة: حفظ الوقت المختار وطلب إدخال اسم الموظف."""
    query = update.callback_query
    await query.answer()
    selected_time = query.data.split('_', 1)[1]
    context.user_data['selected_time'] = selected_time
    date_str = context.user_data['hourly_selected_date'].strftime('%A، %d %B %Y') # تحسين تنسيق التاريخ
    await query.edit_message_text(
        f"تم تحديد الإذن في تاريخ {date_str} الساعة {selected_time}.\n\n"
        "الآن، يرجى إدخال اسمك الكامل لتوثيق طلبك:" # تحسين النص
    )
    return HL_ENTERING_NAME

async def enter_hourly_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الخامسة: حفظ اسم الموظف وطلب إدخال سبب الإذن."""
    context.user_data['employee_name'] = update.message.text
    await update.message.reply_text("شكراً لك. يرجى الآن توضيح سبب هذا الإذن:")
    return HL_ENTERING_REASON

async def enter_hourly_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة السادسة: حفظ سبب الإذن وعرض ملخص الطلب للتأكيد."""
    context.user_data['hourly_reason'] = update.message.text
    leave_type = context.user_data['hourly_leave_type']
    type_text = "تأخير صباحي" if leave_type == 'late' else "مغادرة مبكرة"
    time_label = "وقت الوصول" if leave_type == 'late' else "وقت المغادرة"
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
    """
    الإجراء الأخير في طلب الإذن الساعي:
    يحفظ الطلب في Firebase ويرسله إلى مدير الموارد البشرية وقادة الفرق.
    """
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("تم إلغاء الطلب بنجاح.") # تحسين النص
        context.user_data.clear()
        return ConversationHandler.END

    user = update.effective_user
    leaves_ref = db.reference('/hourly_leaves')
    new_leave_ref = leaves_ref.push()
    request_id = new_leave_ref.key # الحصول على مفتاح الطلب الجديد
    leave_type = context.user_data['hourly_leave_type']
    type_text = "تأخير صباحي" if leave_type == 'late' else "مغادرة مبكرة"
    time_info = f"{type_text} - {context.user_data['selected_time']}"
    selected_date_obj = context.user_data['hourly_selected_date']
    
    # حفظ بيانات الطلب في Firebase
    new_leave_ref.set({
        "employee_name": context.user_data['employee_name'],
        "employee_telegram_id": str(user.id),
        "reason": context.user_data['hourly_reason'],
        "date": selected_date_obj.strftime('%d/%m/%Y'),
        "time_info": time_info,
        "status": "pending", # حالة الطلب الأولية
        "request_time": datetime.now().isoformat(),
    })

    hr_chat_id = get_hr_telegram_id()
    if not hr_chat_id:
        await query.edit_message_text("⚠️ خطأ إداري: لا يمكن العثور على حساب مدير الموارد البشرية. يرجى مراجعة الإدارة.")
        return ConversationHandler.END

    selected_date_str = selected_date_obj.strftime('%d/%m/%Y')
    # رسالة الإشعار لمدير الموارد البشرية
    hr_message = (f"📣 **طلب إذن ساعي جديد** 📣\n\n"
                  f"**من الموظف:** {context.user_data['employee_name']}\n"
                  f"**النوع:** {type_text}\n"
                  f"**التفاصيل:** بتاريخ {selected_date_str}، الساعة {context.user_data['selected_time']}\n"
                  f"**السبب:** {context.user_data['hourly_reason']}\n\n"
                  "يرجى اتخاذ الإجراء المناسب.")
    # أزرار الموافقة والرفض لمدير الموارد البشرية
    keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_hourly_{request_id}"), InlineKeyboardButton("❌ رفض", callback_data=f"reject_hourly_{request_id}")]]
    
    try:
        await context.bot.send_message(chat_id=hr_chat_id, text=hr_message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text("✅ تم إرسال طلبك بنجاح. سيتم إعلامك بالرد قريباً.")
    except Exception as e:
        logger.error(f"Failed to send hourly leave to HR: {e}")
        await query.edit_message_text("حدث خطأ أثناء إرسال الطلب. يرجى المحاولة مرة أخرى.")

    context.user_data.clear()
    return ConversationHandler.END

# ---- مسار طلب الإجازة اليومية ----
async def start_full_day_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الأولى: طلب إدخال اسم الموظف لطلب الإجازة اليومية."""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("➡️ رجوع", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("لتسجيل طلب إجازة، يرجى إدخال اسمك الكامل:", reply_markup=reply_markup)
    return FD_ENTERING_NAME

async def fd_enter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الثانية: حفظ اسم الموظف وطلب إدخال سبب الإجازة."""
    context.user_data['employee_name'] = update.message.text
    keyboard = [[InlineKeyboardButton("➡️ رجوع (لتعديل الاسم)", callback_data="fd_back_to_name")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("شكراً لك. الآن، يرجى توضيح سبب الإجازة:", reply_markup=reply_markup)
    return FD_ENTERING_REASON

async def fd_enter_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الخطوة الثالثة: حفظ سبب الإجازة وطلب تحديد مدة الإجازة (يوم واحد، أيام متتالية، أيام متفرقة)."""
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
    """الخطوة الرابعة: إعداد التقويم بناءً على نوع مدة الإجازة المختارة."""
    query = update.callback_query
    await query.answer()
    duration_type = query.data.split('_')[1]
    context.user_data['duration_type'] = duration_type
    context.user_data['selected_dates'] = [] # إعادة تعيين التواريخ المختارة
    today = date.today()
    message = "الرجاء اختيار تاريخ الإجازة من التقويم:"
    if duration_type == 'range': message = "الرجاء اختيار تاريخ **البدء** للإجازة:" # تحسين النص
    elif duration_type == 'multiple': message = "اختر الأيام المتفرقة التي ترغب بها ثم اضغط '✅ تم الاختيار':" # تحسين النص
    await query.edit_message_text(text=message, reply_markup=create_advanced_calendar(today.year, today.month, duration_type, [], back_callback="fd_back_to_duration_type"), parse_mode=ParseMode.MARKDOWN)
    return FD_SELECTING_DATES

async def fd_calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالجة تفاعلات التقويم (اختيار الأيام، التنقل بين الشهور، تأكيد الاختيار)."""
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
                # اختيار تاريخ البدء
                selected_dates.append(selected_day)
                await query.edit_message_text(
                    f"تاريخ البدء: {selected_day.strftime('%d/%m/%Y')}\n\nالرجاء اختيار تاريخ **الانتهاء** للإجازة:", # تحسين النص
                    reply_markup=create_advanced_calendar(year, month, duration_type, selected_dates, back_callback="fd_back_to_duration_type"),
                    parse_mode=ParseMode.MARKDOWN
                )
                return FD_SELECTING_DATES
            else:
                # اختيار تاريخ الانتهاء
                if selected_day < selected_dates[0]:
                    await query.answer("تاريخ الانتهاء يجب أن يكون بعد تاريخ البدء.", show_alert=True) # رسالة تنبيه
                    return FD_SELECTING_DATES
                selected_dates.append(selected_day)
                return await show_fd_confirmation(query, context)
        elif duration_type == 'multiple':
            # إضافة أو إزالة الأيام في وضع الاختيار المتعدد
            if selected_day in selected_dates:
                selected_dates.remove(selected_day)
            else:
                selected_dates.append(selected_day)
            # إعادة عرض التقويم مع التواريخ المحدثة
            await query.edit_message_text(
                "اختر الأيام المتفرقة التي ترغب بها ثم اضغط '✅ تم الاختيار':", # تحسين النص
                reply_markup=create_advanced_calendar(year, month, duration_type, selected_dates, back_callback="fd_back_to_duration_type")
            )
            return FD_SELECTING_DATES
    elif action == "NAV":
        # التنقل بين الشهور
        year, month = map(int, parts[2:])
        await query.edit_message_text(query.message.text, reply_markup=create_advanced_calendar(year, month, duration_type, selected_dates, back_callback="fd_back_to_duration_type"))
        return FD_SELECTING_DATES
    elif action == "DONE":
        # تأكيد اختيار الأيام المتعددة
        if not selected_dates:
            await query.answer("لم يتم اختيار أي تاريخ. يرجى اختيار يوم واحد على الأقل.", show_alert=True) # رسالة تنبيه
            return FD_SELECTING_DATES
        return await show_fd_confirmation(query, context)
    return FD_SELECTING_DATES

async def show_fd_confirmation(query, context):
    """يعرض ملخص طلب الإجازة اليومية للمراجعة قبل التأكيد النهائي."""
    duration_type = context.user_data['duration_type']
    selected_dates = sorted(context.user_data.get('selected_dates', []))
    if not selected_dates:
        await query.edit_message_text("لم يتم اختيار أي تاريخ. تم إلغاء الطلب.")
        return ConversationHandler.END
        
    date_info_str = ""
    if duration_type == 'single':
        date_info_str = selected_dates[0].strftime('%d/%m/%Y')
    elif duration_type == 'range':
        date_info_str = f"من {selected_dates[0].strftime('%d/%m/%Y')} إلى {selected_dates[-1].strftime('%d/%m/%Y')}"
    elif duration_type == 'multiple':
        date_info_str = ", ".join([d.strftime('%d/%m/%Y') for d in selected_dates])
    context.user_data['final_date_info'] = date_info_str
    
    summary = (f"📋 **ملخص طلب الإجازة** 📋\n\n"
               f"👤 **اسم الموظف:** {context.user_data['employee_name']}\n"
               f"📝 **السبب:** {context.user_data['leave_reason']}\n"
               f"🗓️ **التاريخ/المدة:** {date_info_str}\n\n"
               "يرجى مراجعة التفاصيل بعناية. هل تود تأكيد وإرسال الطلب؟") # تحسين النص
               
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد وإرسال", callback_data="confirm_send"), InlineKeyboardButton("❌ إلغاء الطلب", callback_data="cancel")],
        [InlineKeyboardButton("➡️ رجوع (لتعديل التواريخ)", callback_data="fd_back_to_calendar")]
    ]
    await query.edit_message_text(text=summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    return FD_CONFIRMING_LEAVE

async def confirm_full_day_leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    الإجراء الأخير في طلب الإجازة اليومية:
    يحفظ الطلب في Firebase ويرسله إلى مدير الموارد البشرية.
    """
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("تم إلغاء الطلب بنجاح.") # تحسين النص
        context.user_data.clear()
        return ConversationHandler.END

    user = update.effective_user
    leaves_ref = db.reference('/full_day_leaves')
    new_leave_ref = leaves_ref.push()
    request_id = new_leave_ref.key # الحصول على مفتاح الطلب الجديد
    new_leave_ref.set({
        "employee_name": context.user_data['employee_name'],
        "employee_telegram_id": str(user.id),
        "reason": context.user_data['leave_reason'],
        "date_info": context.user_data['final_date_info'],
        "status": "pending", # حالة الطلب الأولية
        "request_time": datetime.now().isoformat(),
    })
    
    hr_chat_id = get_hr_telegram_id()
    if not hr_chat_id:
        await query.edit_message_text("⚠️ خطأ إداري: لا يمكن العثور على حساب مدير الموارد البشرية. يرجى مراجعة الإدارة.") # تحسين النص
        return ConversationHandler.END
        
    # رسالة الإشعار لمدير الموارد البشرية
    hr_message = (f"📣 **طلب إجازة يومية جديد** 📣\n\n" # تحسين النص
                  f"**من:** {context.user_data['employee_name']}\n"
                  f"**السبب:** {context.user_data['leave_reason']}\n"
                  f"**التاريخ/المدة:** {context.user_data['final_date_info']}\n\n"
                  "يرجى اتخاذ الإجراء المناسب.")
                  
    # أزرار الموافقة والرفض لمدير الموارد البشرية
    keyboard = [[InlineKeyboardButton("✅ موافقة", callback_data=f"approve_fd_{request_id}"), InlineKeyboardButton("❌ رفض", callback_data=f"reject_fd_{request_id}")]]
    
    try:
        await context.bot.send_message(chat_id=hr_chat_id, text=hr_message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text("✅ تم إرسال طلبك بنجاح. سيتم إعلامك بالرد قريباً.")
    except Exception as e:
        logger.error(f"Failed to send full day leave to HR: {e}")
        await query.edit_message_text("حدث خطأ أثناء إرسال الطلب. يرجى المحاولة مرة أخرى.")
        
    context.user_data.clear()
    return ConversationHandler.END

# --- معالج إجراءات المدير ---
async def hr_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    يتعامل مع أفعال مدير الموارد البشرية (الموافقة أو الرفض) على طلبات الإجازات والأذونات.
    يرسل إشعاراً للموظف وقادة الفرق المعنيين.
    """
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    action = parts[0] # "approve" أو "reject"
    leave_type_key = parts[1] # "fd" أو "hourly"
    
    # استخراج معرف الطلب من البيانات
    prefix = f"{action}_{leave_type_key}_"
    request_id = query.data[len(prefix):]
    
    # تحديد مسار قاعدة البيانات بناءً على نوع الإجازة
    leave_type_db = "full_day_leaves" if leave_type_key == "fd" else "hourly_leaves"
    db_path = f"/{leave_type_db}/{request_id}"
    leave_ref = db.reference(db_path)
    leave_request = leave_ref.get()

    if not leave_request:
        await query.edit_message_text("❌ خطأ فني: لم يتم العثور على هذا الطلب. قد يكون قد تم حذفه أو أن المعرّف غير صحيح.")
        logger.error(f"Could not find leave request at path: {db_path}")
        return

    # التحقق مما إذا كان الطلب قد تمت معالجته بالفعل
    if leave_request.get("status") != "pending":
        status_ar = "مقبول ✅" if leave_request.get("status") == "approved" else "مرفوض ❌"
        await query.answer(f"تنبيه: هذا الطلب تمت معالجته بالفعل وحالته الآن: {status_ar}", show_alert=True)
        return

    employee_name = leave_request.get('employee_name', 'موظف')
    hr_user = query.from_user # المدير الذي اتخذ الإجراء
    
    full_date_info = ""
    leader_message_intro = ""
    if leave_type_key == 'fd':
        full_date_info = leave_request.get('date_info', 'غير محدد')
        leader_message_intro = f"تم منح الموظف ({employee_name}) موافقة بخصوص غياب في التاريخ/ التواريخ التالية:"
    else: # hourly
        leave_date = leave_request.get('date', 'بتاريخ اليوم')
        time_details = leave_request.get('time_info', 'وقت غير محدد')
        full_date_info = f"{time_details} بتاريخ {leave_date}"
        leader_message_intro = f"تم منح الموظف ({employee_name}) موافقة بخصوص إذن:"

    if action == "approve":
        leave_ref.update({"status": "approved"})
        response_text = "✅ تمت الموافقة على الطلب"
        user_notification = f"🎉 تهانينا! تمت الموافقة على طلبك بخصوص: **{full_date_info}**."
        
        # إرسال إشعار لقادة الفرق عند الموافقة
        leader_ids = get_all_team_leaders_ids()
        if leader_ids:
            leader_notification = f"🔔 إشعار إجازة/إذن 🔔\n\n{leader_message_intro}\n`{full_date_info}`" # تحسين النص
            for leader_id in leader_ids:
                try:
                    await context.bot.send_message(chat_id=leader_id, text=leader_notification, parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    logger.error(f"Failed to send notification to Team Leader {leader_id}: {e}")
            response_text += "\n(تم إشعار قادة الفرق)"
            
    else: # action == "reject"
        leave_ref.update({"status": "rejected"})
        response_text = "❌ تم رفض الطلب"
        user_notification = f"للأسف، تم رفض طلبك بخصوص: **{full_date_info}**. يرجى مراجعة مديرك المباشر."
    
    # إرسال إشعار للموظف صاحب الطلب
    try:
        await context.bot.send_message(chat_id=leave_request["employee_telegram_id"], text=user_notification, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Failed to send notification to employee {leave_request['employee_telegram_id']}: {e}")
        
    # تحديث رسالة المدير الأصلية بحالة الطلب ومن قام بالمعالجة
    original_message = query.message.text
    final_text = f"{original_message}\n\n--- [ {response_text} بواسطة: {hr_user.first_name} ] ---"
    await query.edit_message_text(text=final_text)

# --- قسم التذكيرات (جديد) ---
def parse_start_date(date_info: str) -> date | None:
    """
    تحليل نص تاريخ الإجازة لاستخراج تاريخ البدء.
    يعالج الحالات: يوم واحد، نطاق، أيام متعددة.
    """
    try:
        # الحالة: "من 01/08/2024 إلى 05/08/2024"
        if "من" in date_info:
            date_str = date_info.split(" ")[1]
            return datetime.strptime(date_str, "%d/%m/%Y").date()
        # الحالة: "01/08/2024, 03/08/2024"
        elif "," in date_info:
            date_str = date_info.split(",")[0].strip()
            return datetime.strptime(date_str, "%d/%m/%Y").date()
        # الحالة: "01/08/2024"
        else:
            return datetime.strptime(date_info, "%d/%m/%Y").date()
    except (ValueError, IndexError) as e:
        logger.error(f"Could not parse date from string '{date_info}': {e}")
        return None

async def check_upcoming_leaves(context: ContextTypes.DEFAULT_TYPE):
    """
    مهمة يومية للتحقق من الإجازات القادمة وإرسال تذكيرات.
    تعمل هذه المهمة كل يوم في الساعة 9 مساءً.
    """
    logger.info("Running daily job: check_upcoming_leaves")
    today = date.today()
    tomorrow = today + timedelta(days=1)
    
    # جلب قائمة المستلمين (مدير الموارد البشرية وقادة الفرق)
    recipient_ids = set(get_all_team_leaders_ids())
    hr_id = get_hr_telegram_id()
    if hr_id:
        recipient_ids.add(hr_id)
        
    if not recipient_ids:
        logger.warning("No recipients (HR/Team Leaders) found for reminders.")
        return

    # 1. التحقق من الإجازات اليومية
    try:
        full_day_leaves = db.reference('/full_day_leaves').get() or {}
        for leave_id, leave_data in full_day_leaves.items():
            if leave_data and leave_data.get("status") == "approved":
                start_date = parse_start_date(leave_data.get("date_info", ""))
                if start_date and start_date == tomorrow:
                    employee_name = leave_data.get("employee_name", "غير معروف")
                    date_info = leave_data.get("date_info", "")
                    reminder_message = (
                        f"📢 **تذكير بإجازة قادمة** 📢\n\n"
                        f"نود تذكيركم بأن الموظف: **{employee_name}** سيكون في إجازة تبدأ غداً.\n\n"
                        f"**التفاصيل:** {date_info}"
                    )
                    for chat_id in recipient_ids:
                        try:
                            await context.bot.send_message(chat_id=chat_id, text=reminder_message, parse_mode=ParseMode.MARKDOWN)
                        except Exception as e:
                            logger.error(f"Failed to send reminder to {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Error checking full day leaves for reminders: {e}")

    # 2. التحقق من الإجازات الساعية (الأذونات)
    try:
        hourly_leaves = db.reference('/hourly_leaves').get() or {}
        for leave_id, leave_data in hourly_leaves.items():
            if leave_data and leave_data.get("status") == "approved":
                try:
                    leave_date = datetime.strptime(leave_data.get("date", ""), "%d/%m/%Y").date()
                    if leave_date == tomorrow:
                        employee_name = leave_data.get("employee_name", "غير معروف")
                        time_info = leave_data.get("time_info", "")
                        date_str = leave_data.get("date", "")
                        reminder_message = (
                            f"📢 **تذكير بإذن قادم** 📢\n\n"
                            f"نود تذكيركم بأن الموظف: **{employee_name}** لديه إذن غداً.\n\n"
                            f"**التفاصيل:** {time_info} بتاريخ {date_str}"
                        )
                        for chat_id in recipient_ids:
                            try:
                                await context.bot.send_message(chat_id=chat_id, text=reminder_message, parse_mode=ParseMode.MARKDOWN)
                            except Exception as e:
                                logger.error(f"Failed to send reminder to {chat_id}: {e}")
                except (ValueError, TypeError) as e:
                    logger.error(f"Could not parse date for hourly leave {leave_id}: {e}")
    except Exception as e:
        logger.error(f"Error checking hourly leaves for reminders: {e}")

# --- دوال الإلغاء والرجوع ---
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دالة عامة لإلغاء أي عملية محادثة جارية."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("تم إلغاء العملية بنجاح.")
    context.user_data.clear() # مسح بيانات المستخدم
    return ConversationHandler.END

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دالة الرجوع إلى القائمة الرئيسية من داخل المحادثة، ومسح بيانات المستخدم."""
    context.user_data.clear()
    return await start(update, context)

async def back_to_hourly_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة اختيار نوع الإذن (تأخير/مغادرة)."""
    return await start_hourly_leave(update, context)

async def back_to_hourly_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة اختيار تاريخ الإذن الساعي."""
    query = update.callback_query
    # إعادة بناء بيانات الاستدعاء لتوجيهها إلى دالة اختيار النوع الصحيحة
    query.data = f"hourly_{context.user_data['hourly_leave_type']}"
    return await choose_hourly_type(update, context)

async def back_to_hourly_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة إدخال سبب الإذن الساعي."""
    query = update.callback_query
    await query.answer()
    await query.delete_message() # حذف الرسالة الحالية لتجنب التكرار
    await query.message.reply_text("تم التراجع. يرجى إدخال سبب الإذن مرة أخرى:")
    return HL_ENTERING_REASON

async def back_to_daily_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة إدخال الاسم لطلب الإجازة اليومية."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("تم التراجع. يرجى إدخال اسمك الكامل مرة أخرى:")
    return FD_ENTERING_NAME

async def back_to_daily_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة إدخال سبب الإجازة اليومية."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("تم التراجع. يرجى إدخال سبب الإجازة مرة أخرى:")
    return FD_ENTERING_REASON
    
async def back_to_daily_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة اختيار نوع مدة الإجازة اليومية."""
    query = update.callback_query
    await query.answer()
    # إعادة إنشاء رسالة اختيار المدة
    keyboard = [
        [InlineKeyboardButton("🗓️ يوم واحد", callback_data="duration_single")],
        [InlineKeyboardButton("🔁 أيام متتالية", callback_data="duration_range")],
        [InlineKeyboardButton("➕ أيام متفرقة", callback_data="duration_multiple")],
        [InlineKeyboardButton("➡️ رجوع (لتعديل السبب)", callback_data="fd_back_to_reason")],
        [InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("تم التراجع. يرجى الآن تحديد مدة الإجازة:", reply_markup=reply_markup) # تحسين النص
    return FD_CHOOSING_DURATION_TYPE

async def back_to_daily_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة التقويم لطلب الإجازة اليومية."""
    query = update.callback_query
    # إعادة بناء بيانات الاستدعاء لتوجيهها إلى دالة اختيار المدة الصحيحة
    query.data = f"duration_{context.user_data['duration_type']}"
    return await fd_choose_duration_type(update, context)

# --- دالة جديدة للرجوع في قسم الاقتراحات ---
async def back_to_suggestion_entering(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """الرجوع إلى خطوة إدخال رسالة الاقتراح."""
    query = update.callback_query
    await query.answer()
    # حذف الرسالة الحالية التي تحتوي على خيارات التأكيد
    await query.edit_message_text(
        "تم التراجع. يرجى إعادة كتابة رسالتك كاملة هنا:"
        "\n\n*ملاحظة: سيتم إرسال رسالتك كمجهول. إذا كنت ترغب في إرسالها باسمك، يرجى كتابة اسمك ضمن نص الرسالة.*",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("القائمة الرئيسية ↩️", callback_data="main_menu")]]), # إضافة زر القائمة الرئيسية
        parse_mode=ParseMode.MARKDOWN
    )
    # مسح نص الاقتراح السابق من user_data لتجنب إرسال النص القديم عن طريق الخطأ
    context.user_data.pop('suggestion_text', None)
    return SUGGESTION_ENTERING

async def post_init(application: Application) -> None:
    """دالة يتم استدعاؤها بعد تهيئة البوت لوضع الأوامر الثابتة مثل /start."""
    await application.bot.set_my_commands([
        BotCommand("start", "العودة إلى القائمة الرئيسية")
    ])

def main() -> None:
    """الدالة الرئيسية لتشغيل البوت."""
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    # --- جدولة مهمة التذكير اليومية (تعديل جديد) ---
    job_queue = application.job_queue
    
    # تحديد المنطقة الزمنية (سوريا، UTC+3)
    syria_tz = pytz.timezone('Asia/Damascus')
    
    # جدولة المهمة لتعمل كل يوم الساعة 21:00 (9 مساءً) بتوقيت سوريا
    # يجب أن يكون كائن الوقت مدركًا للمنطقة الزمنية
    job_time = time(21, 0, 0, tzinfo=syria_tz)
    job_queue.run_daily(check_upcoming_leaves, time=job_time)
    
    # --- معالج المحادثة الموحد ---
    # يحدد هذا المعالج تدفق المحادثة بالكامل وحالاتها المختلفة.
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)], # نقطة الدخول: أمر /start
        states={
            CHOOSING_ACTION: [
                CallbackQueryHandler(start_hourly_leave, pattern="^req_hourly$"),
                CallbackQueryHandler(start_full_day_leave, pattern="^req_daily$"),
                CallbackQueryHandler(start_suggestion, pattern="^req_suggestion$"),
            ],
            # حالات صندوق الاقتراحات
            SUGGESTION_ENTERING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_suggestion),
                CallbackQueryHandler(back_to_main_menu, pattern="^main_menu$"), # إضافة معالج لزر القائمة الرئيسية
            ],
            SUGGESTION_CONFIRMING_ANONYMITY: [
                CallbackQueryHandler(confirm_suggestion, pattern="^sugg_anonymous$"), # فقط خيار المجهول
                CallbackQueryHandler(back_to_suggestion_entering, pattern="^sugg_back_to_edit$"), # معالج زر الرجوع الجديد
                CallbackQueryHandler(back_to_main_menu, pattern="^main_menu$"), # إضافة معالج لزر القائمة الرئيسية
            ],
            # حالات الإجازة الساعية
            HL_CHOOSING_TYPE: [
                CallbackQueryHandler(choose_hourly_type, pattern="^hourly_"),
            ],
            HL_SELECTING_DATE: [
                CallbackQueryHandler(select_hourly_date, pattern="^HL_DATE_"),
                CallbackQueryHandler(back_to_hourly_type, pattern="^hl_back_to_type$"),
            ],
            HL_SELECTING_TIME: [
                CallbackQueryHandler(select_time, pattern="^TIME_"),
                CallbackQueryHandler(back_to_hourly_date, pattern="^hl_back_to_date_selection$"),
            ],
            HL_ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_hourly_name)],
            HL_ENTERING_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_hourly_reason)],
            HL_CONFIRMING_LEAVE: [
                CallbackQueryHandler(confirm_hourly_leave, pattern="^confirm_send$"),
                CallbackQueryHandler(confirm_hourly_leave, pattern="^cancel$"), # معالج الإلغاء هنا أيضاً
                CallbackQueryHandler(back_to_hourly_reason, pattern="^hl_back_to_reason$"),
            ],
            # حالات الإجازة اليومية
            FD_ENTERING_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, fd_enter_name),
                CallbackQueryHandler(back_to_main_menu, pattern="^main_menu$"), # زر الرجوع من هنا
            ],
            FD_ENTERING_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, fd_enter_reason),
                CallbackQueryHandler(back_to_daily_name, pattern="^fd_back_to_name$"),
            ],
            FD_CHOOSING_DURATION_TYPE: [
                CallbackQueryHandler(fd_choose_duration_type, pattern="^duration_"),
                CallbackQueryHandler(back_to_daily_reason, pattern="^fd_back_to_reason$"),
            ],
            FD_SELECTING_DATES: [
                CallbackQueryHandler(fd_calendar_callback, pattern="^CAL_"),
                CallbackQueryHandler(back_to_daily_duration, pattern="^fd_back_to_duration_type$"),
            ],
            FD_CONFIRMING_LEAVE: [
                CallbackQueryHandler(confirm_full_day_leave, pattern="^confirm_send$"),
                CallbackQueryHandler(confirm_full_day_leave, pattern="^cancel$"), # معالج الإلغاء هنا أيضاً
                CallbackQueryHandler(back_to_daily_calendar, pattern="^fd_back_to_calendar$"),
            ],
        },
        fallbacks=[
            CommandHandler('start', start), # يسمح بالعودة إلى البداية في أي وقت
            CallbackQueryHandler(back_to_main_menu, pattern="^main_menu$"), # معالج زر القائمة الرئيسية العام
            CallbackQueryHandler(cancel_conversation, pattern="^cancel$") # معالج زر الإلغاء العام
        ],
        allow_reentry=True # يسمح بإعادة دخول المحادثة من أي نقطة
    )

    # إضافة المعالجات إلى التطبيق
    application.add_handler(conv_handler)
    # معالج خاص لإجراءات مدير الموارد البشرية (الموافقة/الرفض)
    application.add_handler(CallbackQueryHandler(hr_action_handler, pattern="^(approve|reject)_(fd|hourly)_"))

    print("Bot is running with Reminders and Suggestions Box feature...")
    application.run_polling() # بدء تشغيل البوت

if __name__ == "__main__":
    main()
