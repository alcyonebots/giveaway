import logging
import random
import threading
import time
import re
from datetime import datetime, timedelta, timezone

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ParseMode,
    ChatMember
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackQueryHandler,
    ConversationHandler,
    CallbackContext
)
from pymongo import MongoClient

TOKEN = '7835346917:AAGuHYIBAscjbTKoadzG7EGFaRKOS2ZMyck'
MONGO_URI = 'mongodb+srv://Cenzo:Cenzo123@cenzo.azbk1.mongodb.net/'
ADMIN_IDS = [1209431233, 1148182834, 6663845789]
GROUP_ID = -1002529323673

client = MongoClient(MONGO_URI)
db = client['giveaway_db']

logging.basicConfig(level=logging.INFO)

ENTER_FS_COUNT, ENTER_FS_CHANNELS, ENTER_TITLE, ENTER_BANNER, ENTER_HOST, ENTER_DURATION = range(6)

IST = timezone(timedelta(hours=5, minutes=30))

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Welcome to the Giveaway Bot!\n"
        "• /start_giveaway - New giveaway (admin only)\n"
        "• /cancel_giveaway - Cancel giveaway\n"
        "• /stats - Show stats\n"
        "• /help - Show this help"
    )

def help_command(update: Update, context: CallbackContext):
    text = (
        "<b>Giveaway Bot Help</b>\n\n"
        "Commands:\n"
        "/start - Show welcome message\n"
        "/help - Show this help message\n"
        "<b>Admin Commands (Admins only):</b>\n"
        "/start_giveaway - Create a new giveaway\n"
        "/cancel_giveaway - Cancel the running giveaway\n"
        "/stats - Get all giveaway stats\n\n"
        "<b>How it works:</b>\n"
        "- Giveaway will always post in the fixed group\n"
        "- User must have 100+ msgs in group\n"
        "- FSUB: now only supports public @ usernames"
    )
    update.message.reply_text(text, parse_mode=ParseMode.HTML)

def start_giveaway(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        update.message.reply_text("Only admins can start a giveaway.")
        return ConversationHandler.END
    context.user_data.clear()
    update.message.reply_text("How many FSUB channels/groups do you want to add? (Type 0 for none, public @username only)")
    return ENTER_FS_COUNT

def enter_fs_count(update: Update, context: CallbackContext):
    try:
        fs_count = int(update.message.text)
        if fs_count < 0 or fs_count > 10:
            update.message.reply_text("Enter a number from 0 to 10.")
            return ENTER_FS_COUNT
    except:
        update.message.reply_text("Enter number only (0-10).")
        return ENTER_FS_COUNT
    context.user_data['fs_count'] = fs_count
    context.user_data['fs_channels'] = []
    if fs_count == 0:
        update.message.reply_text("No FSUB. Now send the Giveaway Title.")
        return ENTER_TITLE
    update.message.reply_text(f"Send @username for FSUB 1:")
    context.user_data['fsub_step'] = 1
    return ENTER_FS_CHANNELS

def enter_fs_channels(update: Update, context: CallbackContext):
    fsubs = context.user_data['fs_channels']
    uname = update.message.text.strip()
    # Validate username
    if not (uname.startswith('@') and len(uname) > 1 and uname[1:].replace('_','').isalnum()):
        update.message.reply_text("Please send a valid @username (starts with @, letters, digits, underscore).")
        return ENTER_FS_CHANNELS
    fsubs.append(uname)
    if len(fsubs) < context.user_data['fs_count']:
        update.message.reply_text(f"Send @username for FSUB {len(fsubs)+1}:")
        return ENTER_FS_CHANNELS
    update.message.reply_text("Now send the Giveaway Title.")
    return ENTER_TITLE

def enter_title(update: Update, context: CallbackContext):
    context.user_data['title'] = update.message.text
    update.message.reply_text("Send banner image (photo, not file).")
    return ENTER_BANNER

def enter_banner(update: Update, context: CallbackContext):
    if update.message.photo:
        context.user_data['banner_file_id'] = update.message.photo[-1].file_id
        update.message.reply_text("Who is Hosting? (send host name or username)")
        return ENTER_HOST
    update.message.reply_text('Please send an image/photo for the banner!')
    return ENTER_BANNER

def enter_host(update: Update, context: CallbackContext):
    context.user_data['hosted_by'] = update.message.text
    update.message.reply_text('Giveaway duration? (in format: 30m / 1h / 3d / 1w)')
    return ENTER_DURATION

def enter_duration(update: Update, context: CallbackContext):
    txt = update.message.text.strip().lower()
    match = re.match(r"^(\d{1,4})([mhdw])$", txt)
    if not match:
        update.message.reply_text("Please enter duration like 30m / 1h / 3d / 1w (m=minutes, h=hours, d=days, w=weeks)")
        return ENTER_DURATION

    val, typ = int(match[1]), match[2]
    if typ == "m":
        delta = timedelta(minutes=val)
    elif typ == "h":
        delta = timedelta(hours=val)
    elif typ == "d":
        delta = timedelta(days=val)
    elif typ == "w":
        delta = timedelta(weeks=val)
    else:
        update.message.reply_text("Invalid format. Use like 30m / 1h / 3d / 1w.")
        return ENTER_DURATION

    context.user_data['duration_delta'] = delta

    fs_channels = context.user_data['fs_channels']
    title = context.user_data['title']
    banner_file_id = context.user_data['banner_file_id']
    hosted_by = context.user_data['hosted_by']

    requirement_caption = ""
    if fs_channels:
        channel_list_disp = '\n'.join([uname for uname in fs_channels])
        requirement_caption = f"<b>Required Channel To Join:</b>\n{channel_list_disp}\n\n"

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🎉 Participate", callback_data="join_giveaway")]])
    end_time = datetime.utcnow() + delta
    ist_end_time = end_time.replace(tzinfo=timezone.utc).astimezone(IST)

    msg = context.bot.send_photo(
        chat_id=GROUP_ID,
        photo=banner_file_id,
        caption=(
            f"🎁 <b>GIVEAWAY:</b> {title}\n\n"
            f"{requirement_caption}"
            f"<b>Hosted By:</b> {hosted_by}\n"
            f"<b>Entries:</b> 0\n"
            f"<b>Ends at:</b> {ist_end_time.strftime('%Y-%m-%d %H:%M IST')}\n"
            "\nClick below to enter!"
        ),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    giveaway = {
        'chat_id': GROUP_ID,
        'message_id': msg.message_id,
        'fs_channels': fs_channels,
        'title': title,
        'banner_file_id': banner_file_id,
        'hosted_by': hosted_by,
        'entries': [],
        'end_time': end_time,
        'creator_id': update.effective_user.id,
        'active': True,
        'cancelled': False,
    }
    insert = db.giveaways.insert_one(giveaway)

    threading.Thread(target=wait_and_end_giveaway, args=(insert.inserted_id, end_time, context.bot), daemon=True).start()

    update.message.reply_text('✅ Giveaway posted in group!')
    return ConversationHandler.END

def wait_and_end_giveaway(giveaway_id, end_time, bot):
    delay = (end_time - datetime.utcnow()).total_seconds()
    if delay > 0:
        time.sleep(delay)
    give = db.giveaways.find_one({'_id': giveaway_id})
    if give and give['active'] and not give.get('cancelled', False):
        end_giveaway(give, bot)

def join_giveaway_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user = query.from_user
    giveaway = db.giveaways.find_one({
        'chat_id': GROUP_ID,
        'message_id': query.message.message_id,
        'active': True,
        'cancelled': False
    })
    if not giveaway:
        query.answer('This giveaway is over or cancelled.')
        return

    if user.id in [e['user_id'] for e in giveaway['entries']]:
        query.answer('Already joined!', show_alert=True)
        return

    msg_count = db.msg_count.find_one({'chat_id': GROUP_ID, 'user_id': user.id}) or {}
    if msg_count.get('count', 0) < 10:
        query.answer('You need at least 10 msgs in the group!', show_alert=True)
        return

    # FSUB check
    for uname in giveaway['fs_channels']:
        # Remove `@` for get_chat_member
        uname_noat = uname[1:]
        try:
            member = context.bot.get_chat_member(uname_noat, user.id)  # Correct: use uname without @
            if member.status in [ChatMember.LEFT, ChatMember.KICKED]:
                query.answer('You must join all required channels/groups to participate!', show_alert=True)
                return
        except Exception:
            # Could be if bot isn't admin/public access error
            query.answer(f"Bot must be admin/member in {uname} (public group/channel only)!", show_alert=True)
            return

    db.giveaways.update_one({'_id': giveaway['_id']}, {'$push': {'entries': {
        'user_id': user.id,
        'username': user.username,
        'first_name': user.first_name
    }}})
    entry_count = len(giveaway['entries']) + 1

    if giveaway['fs_channels']:
        chan_disp = '\n'.join([uname for uname in giveaway['fs_channels']])
        requirement_caption = f"<b>Required Channel To Join:</b>\n{chan_disp}\n\n"
    else:
        requirement_caption = ""

    ist_end_time = giveaway['end_time'].replace(tzinfo=timezone.utc).astimezone(IST)

    try:
        query.edit_message_caption(
            caption=(
                f"🎁 <b>GIVEAWAY:</b> {giveaway['title']}\n\n"
                f"{requirement_caption}"
                f"<b>Hosted By:</b> {giveaway['hosted_by']}\n"
                f"<b>Entries:</b> {entry_count}\n"
                f"<b>Ends at:</b> {ist_end_time.strftime('%Y-%m-%d %H:%M IST')}\n"
                "\nClick below to enter!"
            ),
            reply_markup=query.message.reply_markup,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass

    query.answer('Registered!')

def end_giveaway(giveaway, bot):
    admins = [a.user.id for a in bot.get_chat_administrators(GROUP_ID)]
    entries = giveaway['entries']
    eligible_users = []
    for e in entries:
        try:
            m = bot.get_chat_member(GROUP_ID, e['user_id'])
            # Allow both admins and members to win
            if not m.user.is_bot and m.status in ['member', 'administrator', 'creator']:
                eligible_users.append(e)
        except Exception:
            continue
    winner = random.choice(eligible_users) if eligible_users else None

    if giveaway['fs_channels']:
        chan_disp = '\n'.join([uname for uname in giveaway['fs_channels']])
        requirement_caption = f"<b>Required Channel To Join:</b>\n{chan_disp}\n\n"
    else:
        requirement_caption = ""

    db.giveaways.update_one({'_id': giveaway['_id']}, {'$set': {'active': False}})

    if winner:
        winner_tag = f"@{winner['username']}" if winner.get('username') else winner.get('first_name', 'Anonymous')
        caption = (
            f"🎁 <b>GIVEAWAY ENDED:</b> {giveaway['title']}\n\n"
            f"{requirement_caption}"
            f"<b>Hosted By:</b> {giveaway['hosted_by']}\n"
            f"<b>Entries:</b> {len(giveaway['entries'])}\n"
            f"<b>Winner:</b> {winner_tag}\n"
            "Congratulations! 🥳"
        )
    else:
        caption = (
            f"🎁 <b>GIVEAWAY ENDED:</b> {giveaway['title']}\n\n"
            f"{requirement_caption}"
            f"<b>Hosted By:</b> {giveaway['hosted_by']}\n"
            f"<b>Entries:</b> {len(giveaway['entries'])}\n"
            "<b>No eligible winner.</b>"
        )
    try:
        bot.edit_message_caption(
            chat_id=GROUP_ID,
            message_id=giveaway['message_id'],
            caption=caption,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logging.error('Edit after end:', exc_info=e)

    for admin_id in ADMIN_IDS:
        try:
            if winner:
                bot.send_message(admin_id, f"Giveaway '{giveaway['title']}' winner: {winner_tag} [ID: {winner['user_id']}]")
            else:
                bot.send_message(admin_id, f"No winner for giveaway '{giveaway['title']}'.")
        except:
            pass

def count_messages(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if chat_id == GROUP_ID:
        db.msg_count.update_one({'chat_id': GROUP_ID, 'user_id': user_id}, {'$inc': {'count': 1}}, upsert=True)

def cancel_giveaway(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        update.message.reply_text("Admins only.")
        return
    giveaway = db.giveaways.find_one({'chat_id': GROUP_ID, 'active': True, 'cancelled': False})
    if not giveaway:
        update.message.reply_text("No active giveaway!")
        return
    db.giveaways.update_one({'_id': giveaway['_id']}, {'$set': {'active': False, 'cancelled': True}})

    if giveaway['fs_channels']:
        chan_disp = '\n'.join([uname for uname in giveaway['fs_channels']])
        requirement_caption = f"<b>Required Channel To Join:</b>\n{chan_disp}\n\n"
    else:
        requirement_caption = ""

    try:
        context.bot.edit_message_caption(
            chat_id=GROUP_ID,
            message_id=giveaway['message_id'],
            caption=f"❌ <b>GIVEAWAY CANCELLED:</b> {giveaway['title']}\n\n"
                    f"{requirement_caption}"
                    f"<b>Hosted By:</b> {giveaway['hosted_by']}\n"
                    f"<b>Entries:</b> {len(giveaway['entries'])}\n"
                    "This giveaway was cancelled.",
            parse_mode=ParseMode.HTML
        )
    except: pass
    for admin_id in ADMIN_IDS:
        try:
            context.bot.send_message(admin_id, f"Giveaway '{giveaway['title']}' cancelled by {user_id}.")
        except: pass
    update.message.reply_text("Giveaway cancelled.")

def stats(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        update.message.reply_text("Admins only.")
        return
    all_giveaways = list(db.giveaways.find({'chat_id': GROUP_ID}))
    if not all_giveaways:
        update.message.reply_text("No giveaways yet!")
        return

    text_lines = [f"📊 <b>STATS</b> Total Giveaways: {len(all_giveaways)}\n"]

    for idx, g in enumerate(all_giveaways, 1):
        if g.get('active', False):
            status = "Running"
        elif g.get('cancelled', False):
            status = "Cancelled"
        else:
            status = "Ended"
        entries = g.get('entries', [])
        winner = None
        if not g.get('active') and not g.get('cancelled', False) and entries:
            # Pick last eligible user in entries as winner for stats (approximation)
            eligible = []
            for e in entries:
                if e['user_id'] not in ADMIN_IDS:
                    eligible.append(e)
            if eligible:
                winner = eligible[-1]
        winner_str = (f"@{winner['username']}" if winner and winner.get('username') else winner['first_name']
                      if winner else "No winner")
        text_lines.append(
            f"<b>{idx}) {g.get('title','No title')}</b>\n"
            f"Status: {status}\n"
            f"Host: {g.get('hosted_by','')}\n"
            f"Entries: {len(entries)}\n"
            f"Winner: {winner_str}\n"
        )
    big_text = '\n'.join(text_lines)
    try:
        context.bot.send_message(user_id, big_text, parse_mode=ParseMode.HTML)
        update.message.reply_text("Stats sent to your DM.")
    except:
        update.message.reply_text("Failed to send DM. Here are the stats:\n" + big_text, parse_mode=ParseMode.HTML)

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start_giveaway', start_giveaway)],
        states={
            ENTER_FS_COUNT:   [MessageHandler(Filters.text & (~Filters.command), enter_fs_count)],
            ENTER_FS_CHANNELS:[MessageHandler(Filters.text & (~Filters.command), enter_fs_channels)],
            ENTER_TITLE:      [MessageHandler(Filters.text & (~Filters.command), enter_title)],
            ENTER_BANNER:     [MessageHandler(Filters.photo, enter_banner)],
            ENTER_HOST:       [MessageHandler(Filters.text & (~Filters.command), enter_host)],
            ENTER_DURATION:   [MessageHandler(Filters.text & (~Filters.command), enter_duration)],
        },
        fallbacks=[],
    )

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('help', help_command))
    dp.add_handler(conv_handler)
    dp.add_handler(CallbackQueryHandler(join_giveaway_callback, pattern='join_giveaway'))
    dp.add_handler(CommandHandler('cancel_giveaway', cancel_giveaway))
    dp.add_handler(CommandHandler('stats', stats))
    dp.add_handler(MessageHandler(Filters.group & Filters.text, count_messages))

    print("Bot running...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
  
