import logging
import random
import threading
from datetime import datetime, timedelta
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, ChatMember)
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler, ConversationHandler, CallbackContext)
from pymongo import MongoClient

TOKEN = '7835346917:AAGuHYIBAscjbTKoadzG7EGFaRKOS2ZMyck'
MONGO_URI = 'mongodb+srv://Cenzo:Cenzo123@cenzo.azbk1.mongodb.net/'
ADMIN_IDS = [1209431233, 1148182834, 6663845789]
GROUP_ID = -1002529323673

client = MongoClient(MONGO_URI)
db = client['giveaway_db']

logging.basicConfig(level=logging.INFO)

ENTER_FS_CHANNELS, ENTER_TITLE, ENTER_BANNER, ENTER_HOST, ENTER_DURATION = range(5)

def start(update, context):
    update.message.reply_text(
        "Welcome to the Giveaway Bot!\n"
        "• /start_giveaway - New giveaway (admin only)\n"
        "• /cancel_giveaway - Cancel giveaway\n"
        "• /stats - Show stats\n"
        "• /help - Show this help"
    )

def help_command(update, context):
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
        "- FSUB: accept ANY t.me group/channel/join link"
    )
    update.message.reply_text(text, parse_mode=ParseMode.HTML)

def start_giveaway(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        update.message.reply_text("Only admins can start a giveaway.")
        return ConversationHandler.END
    context.user_data.clear()
    update.message.reply_text("Send FSUB channel/group links separated by commas.\nExample: https://t.me/abc, https://t.me/+invite")
    return ENTER_FS_CHANNELS

def enter_fs_channels(update, context):
    fs_channels = [c.strip() for c in update.message.text.split(',') if c.strip()]
    context.user_data['fs_channels'] = fs_channels
    update.message.reply_text("Now send the Giveaway Title.")
    return ENTER_TITLE

def enter_title(update, context):
    context.user_data['title'] = update.message.text
    update.message.reply_text("Send banner image (photo, not file).")
    return ENTER_BANNER

def enter_banner(update, context):
    if update.message.photo:
        context.user_data['banner_file_id'] = update.message.photo[-1].file_id
        update.message.reply_text("Who is Hosting? (send host name or username)")
        return ENTER_HOST
    else:
        update.message.reply_text('Please send an image/photo for the banner!')
        return ENTER_BANNER

def enter_host(update, context):
    context.user_data['hosted_by'] = update.message.text
    update.message.reply_text('Giveaway duration? (in hours e.g. 48)')
    return ENTER_DURATION

def enter_duration(update, context):
    try:
        hours = int(update.message.text)
    except:
        update.message.reply_text("Enter a valid number (hours).")
        return ENTER_DURATION
    context.user_data['duration_hours'] = hours

    fs_channels = context.user_data['fs_channels']
    title = context.user_data['title']
    banner_file_id = context.user_data['banner_file_id']
    hosted_by = context.user_data['hosted_by']

    channel_list_disp = '\n'.join([f'- {link}' for link in fs_channels])

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🎉 Participate", callback_data="join_giveaway")]])
    msg = context.bot.send_photo(
        chat_id=GROUP_ID,
        photo=banner_file_id,
        caption=(
            f"🎁 <b>GIVEAWAY:</b> {title}\n\n"
            f"<b>Required:</b>\n{channel_list_disp}\n\n"
            f"<b>Hosted By:</b> {hosted_by}\n"
            f"<b>Entries:</b> 0\n"
            f"<b>Ends in:</b> {hours} hour(s).\n"
            "\nClick below to enter!"
        ),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    end_time = datetime.utcnow() + timedelta(hours=hours)
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
    threading.Thread(target=wait_and_end_giveaway, args=(insert.inserted_id, end_time, context.bot)).start()
    update.message.reply_text('✅ Giveaway posted in group!')
    return ConversationHandler.END

def wait_and_end_giveaway(giveaway_id, end_time, bot):
    delay = (end_time - datetime.utcnow()).total_seconds()
    if delay > 0:
        threading.Event().wait(delay)
    give = db.giveaways.find_one({'_id': giveaway_id})
    if give and give['active'] and not give.get('cancelled', False):
        end_giveaway(give, bot)

def join_giveaway_callback(update, context):
    query = update.callback_query
    user = query.from_user
    giveaway = db.giveaways.find_one({'chat_id': GROUP_ID, 'message_id': query.message.message_id, 'active': True, 'cancelled': False})
    if not giveaway:
        query.answer('This giveaway is over or cancelled.')
        return

    if user.id in [e['user_id'] for e in giveaway['entries']]:
        query.answer('Already joined!', show_alert=True)
        return

    msg_count = db.msg_count.find_one({'chat_id': GROUP_ID, 'user_id': user.id}) or {}
    if msg_count.get('count', 0) < 100:
        query.answer('You need at least 100 msgs in the group!', show_alert=True)
        return

    for ch_link in giveaway['fs_channels']:
        import time; time.sleep(0.5)
        try:
            identifier = ch_link.split('t.me/')[1] if 't.me/' in ch_link else ch_link
            if identifier.startswith('+'):
                identifier = ch_link  # invite link
            member = context.bot.get_chat_member(identifier, user.id)
            if member.status in [ChatMember.LEFT, ChatMember.KICKED]:
                query.answer(f'You must join {ch_link}!', show_alert=True)
                return
        except Exception:
            query.answer(f'Cannot verify: {ch_link}', show_alert=True)
            return

    db.giveaways.update_one({'_id': giveaway['_id']}, {'$push': {'entries': {
        'user_id': user.id, 'username': user.username, 'first_name': user.first_name
    }}})

    entry_count = len(giveaway['entries']) + 1
    chan_disp = '\n'.join([f'- {l}' for l in giveaway['fs_channels']])
    try:
        query.edit_message_caption(
            caption=(
                f"🎁 <b>GIVEAWAY:</b> {giveaway['title']}\n\n"
                f"<b>Required:</b>\n{chan_disp}\n\n"
                f"<b>Hosted By:</b> {giveaway['hosted_by']}\n"
                f"<b>Entries:</b> {entry_count}\n"
                f"<b>Ends at:</b> {giveaway['end_time'].strftime('%Y-%m-%d %H:%M UTC')}\n"
                "\nClick below to enter!"
            ),
            reply_markup=query.message.reply_markup,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        pass
    query.answer('Registered!')

def end_giveaway(giveaway, bot):
    admins = [a['user']['id'] for a in bot.get_chat_administrators(GROUP_ID)]
    entries = giveaway['entries']
    eligible_users = []
    for e in entries:
        try:
            m = bot.get_chat_member(GROUP_ID, e['user_id'])
            if e['user_id'] not in admins and not m.user.is_bot and m.status in ['member', 'administrator', 'creator']:
                eligible_users.append(e)
        except Exception:
            continue
    winner = random.choice(eligible_users) if eligible_users else None
    db.giveaways.update_one({'_id': giveaway['_id']}, {'$set': {'active': False}})
    chan_disp = '\n'.join([f'- {l}' for l in giveaway['fs_channels']])
    if winner:
        winner_tag = f"@{winner['username']}" if winner.get('username') else winner.get('first_name','Anonymous')
        caption = (
            f"🎁 <b>GIVEAWAY ENDED:</b> {giveaway['title']}\n\n"
            f"<b>Required:</b>\n{chan_disp}\n\n"
            f"<b>Hosted By:</b> {giveaway['hosted_by']}\n"
            f"<b>Entries:</b> {len(giveaway['entries'])}\n"
            f"<b>Winner:</b> {winner_tag}\n"
            "Congratulations! 🥳"
        )
    else:
        caption = (
            f"🎁 <b>GIVEAWAY ENDED:</b> {giveaway['title']}\n\n"
            f"<b>Required:</b>\n{chan_disp}\n\n"
            f"<b>Hosted By:</b> {giveaway['hosted_by']}\n"
            f"<b>Entries:</b> {len(giveaway['entries'])}\n"
            "<b>No eligible winner.</b>"
        )
    try:
        bot.edit_message_caption(
            chat_id=GROUP_ID,
            message_id=giveaway['message_id'],
            caption=caption,
            parse_mode=ParseMode.HTML)
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

def count_messages(update, context):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if chat_id == GROUP_ID:
        db.msg_count.update_one({'chat_id': GROUP_ID, 'user_id': user_id}, {'$inc': {'count': 1}}, upsert=True)

def cancel_giveaway(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        update.message.reply_text("Admins only.")
        return
    giveaway = db.giveaways.find_one({'chat_id': GROUP_ID, 'active': True, 'cancelled': False})
    if not giveaway:
        update.message.reply_text("No active giveaway!")
        return
    db.giveaways.update_one({'_id': giveaway['_id']}, {'$set': {'active': False, 'cancelled': True}})
    try:
        context.bot.edit_message_caption(
            chat_id=GROUP_ID,
            message_id=giveaway['message_id'],
            caption=f"❌ <b>GIVEAWAY CANCELLED:</b> {giveaway['title']}\n\n"
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

def stats(update, context):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        update.message.reply_text("Admins only.")
        return
    all_giveaways = list(db.giveaways.find({'chat_id': GROUP_ID}))
    if not all_giveaways:
        update.message.reply_text("No giveaways yet!")
        return
    text_lines = [f"📊 <b>STATS</b> Total: {len(all_giveaways)}\n"]
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
            eligible = [e for e in entries if e['user_id'] not in ADMIN_IDS]
            if eligible:
                winner = eligible[-1]
        winner_str = (f"@{winner['username']}" if winner and winner.get('username') else winner['first_name']
                      if winner else "No winner")
        text_lines.append(
            f"<b>{idx}) {g.get('title','No title')}</b>\nStatus: {status}\n"
            f"Host: {g.get('hosted_by','')}\nEntries: {len(entries)}\nWinner: {winner_str}\n"
        )
    big_text = '\n'.join(text_lines)
    try:
        context.bot.send_message(user_id, big_text, parse_mode=ParseMode.HTML)
        update.message.reply_text("Stats sent to your DM.")
    except: update.message.reply_text("Stats DM blocked, sending here...\n"+big_text, parse_mode=ParseMode.HTML)

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start_giveaway', start_giveaway)],
        states={
            ENTER_FS_CHANNELS: [MessageHandler(Filters.text & (~Filters.command), enter_fs_channels)],
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

if __name__ == "__main__":
    main()
        
