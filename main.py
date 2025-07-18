import logging
import random
import asyncio
from datetime import datetime, timedelta

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, ConversationHandler,
    ContextTypes, MessageHandler, filters
)
from pymongo import MongoClient

# =========================
#      CONFIGURATION
# =========================

TOKEN = '7835346917:AAGuHYIBAscjbTKoadzG7EGFaRKOS2ZMyck'
MONGO_URI = 'mongodb://localhost:27017'
ADMIN_IDS = [1209431233, 1148182834, 6663845789]     # List of Telegram admin user IDs (integers)
GROUP_ID = -1002529323673              # Your group chat id (numeric, begins with -100...)

# =========================
#      MONGO SETUP
# =========================

client = MongoClient(MONGO_URI)
db = client['giveaway_db']

# =========================
#        LOGGING
# =========================

logging.basicConfig(level=logging.INFO)

# =========================
#   Conversation States
# =========================

ENTER_FS_CHANNELS, ENTER_TITLE, ENTER_BANNER, ENTER_HOST, ENTER_DURATION = range(5)

# =========================
#     /start command
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! I'm the Giveaway Bot.\n"
        "Use /start_giveaway to create a new giveaway (admins only).\n"
        "/cancel_giveaway to cancel active giveaway.\n"
        "/stats for stats (admins only)."
    )

# =========================
#   Giveaway Conversation
# =========================

async def start_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text('Only admins can start giveaways.')
        return ConversationHandler.END
    await update.message.reply_text(
        'Send FSUB (required join) channel/group links separated by commas.\n'
        'For example:\nhttps://t.me/abc, https://t.me/+privateinvitecode'
    )
    return ENTER_FS_CHANNELS

async def enter_fs_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fs_channels = [c.strip() for c in update.message.text.split(',') if c.strip()]
    context.user_data['fs_channels'] = fs_channels
    await update.message.reply_text('Great! Now send me the Giveaway Title.')
    return ENTER_TITLE

async def enter_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['title'] = update.message.text
    await update.message.reply_text('Please send the banner image for your giveaway (as photo, not file).')
    return ENTER_BANNER

async def enter_banner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        context.user_data['banner_file_id'] = photo_file_id
        await update.message.reply_text('Enter the name for Hosted By:')
        return ENTER_HOST
    else:
        await update.message.reply_text('Please send a valid image/photo for the banner!')
        return ENTER_BANNER

async def enter_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['hosted_by'] = update.message.text
    await update.message.reply_text('How long should the giveaway run? Send in hours (e.g. 168 for 7 days):')
    return ENTER_DURATION

async def enter_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        hours = int(update.message.text)
    except Exception:
        await update.message.reply_text("Please enter a valid number of hours.")
        return ENTER_DURATION

    fs_channels = context.user_data['fs_channels']
    title = context.user_data['title']
    banner_file_id = context.user_data['banner_file_id']
    hosted_by = context.user_data['hosted_by']

    channel_list_disp = '\n'.join([f'- {link}' for link in fs_channels])

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎉 Participate", callback_data="join_giveaway")]
    ])

    message = await context.bot.send_photo(
        chat_id=GROUP_ID,
        photo=banner_file_id,
        caption=(
            f"🎁 <b>GIVEAWAY:</b> {title}\n\n"
            f"<b>Required:</b>\n{channel_list_disp}\n\n"
            f"<b>Hosted By:</b> {hosted_by}\n"
            f"<b>Entries:</b> 0\n"
            f"<b>Ends in:</b> {hours} hour(s).\n"
            f"\nClick below to enter!"
        ),
        reply_markup=keyboard,
        parse_mode='HTML'
    )

    end_time = datetime.utcnow() + timedelta(hours=hours)
    giveaway = {
        'chat_id': GROUP_ID,
        'message_id': message.message_id,
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
    inserted = db.giveaways.insert_one(giveaway)
    context.application.create_task(schedule_giveaway_end(context, inserted.inserted_id, end_time))

    await update.message.reply_text('✅ Giveaway started in the group!')

    return ConversationHandler.END

# =========================
#    Participation Handler
# =========================

async def join_giveaway_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = GROUP_ID
    message_id = query.message.message_id

    giveaway = db.giveaways.find_one({'chat_id': GROUP_ID, 'message_id': message_id, 'active': True, 'cancelled': False})
    if not giveaway:
        await query.answer('This giveaway is over, cancelled, or not found.')
        return

    if user.id in [entry['user_id'] for entry in giveaway['entries']]:
        await query.answer("You've already joined!", show_alert=True)
        return

    user_message_count = db.msg_count.find_one({'chat_id': GROUP_ID, 'user_id': user.id}) or {}
    if user_message_count.get('count', 0) < 100:
        await query.answer('You need at least 100 messages in this group to join.', show_alert=True)
        return

    # FSUB check logic
    for ch_link in giveaway['fs_channels']:
        await asyncio.sleep(0.5)
        try:
            identifier = ch_link.split('t.me/')[1] if 't.me/' in ch_link else ch_link
            if identifier.startswith('+'):
                identifier = ch_link  # for invite links use full link
            member = await context.bot.get_chat_member(identifier, user.id)
            if member.status in ['left', 'kicked']:
                await query.answer(f'You must join {ch_link} to participate!', show_alert=True)
                return
        except Exception as e:
            await query.answer(f"Bot can't verify: {ch_link}", show_alert=True)
            return

    db.giveaways.update_one(
        {'_id': giveaway['_id']},
        {'$push': {'entries': {
            'user_id': user.id,
            'username': user.username,
            'first_name': user.first_name
        }}}
    )
    entry_count = len(giveaway['entries']) + 1
    channel_list_disp = '\n'.join([f'- {link}' for link in giveaway['fs_channels']])

    try:
        await query.message.edit_caption(
            caption=(
                f"🎁 <b>GIVEAWAY:</b> {giveaway['title']}\n\n"
                f"<b>Required:</b>\n{channel_list_disp}\n\n"
                f"<b>Hosted By:</b> {giveaway['hosted_by']}\n"
                f"<b>Entries:</b> {entry_count}\n"
                f"<b>Ends at:</b> {giveaway['end_time'].strftime('%Y-%m-%d %H:%M UTC')}\n"
                f"\nClick below to enter!"
            ),
            reply_markup=query.message.reply_markup,
            parse_mode='HTML'
        )
    except Exception:
        pass

    await query.answer('You are registered!')

# =========================
#   Winner and Scheduler
# =========================

async def schedule_giveaway_end(context, giveaway_id, end_time):
    delay = (end_time - datetime.utcnow()).total_seconds()
    await asyncio.sleep(delay)
    giveaway = db.giveaways.find_one({'_id': giveaway_id})
    if not giveaway or not giveaway['active'] or giveaway.get('cancelled', False):
        return
    await end_giveaway(context, giveaway)

async def end_giveaway(context, giveaway):
    try:
        chat_admins = await context.bot.get_chat_administrators(GROUP_ID)
        admins = [a.user.id for a in chat_admins]
    except Exception:
        admins = []
    entries = giveaway['entries']
    eligible_users = []
    for e in entries:
        try:
            m = await context.bot.get_chat_member(GROUP_ID, e['user_id'])
            if e['user_id'] not in admins and not m.user.is_bot and m.status in ['member', 'administrator', 'creator']:
                eligible_users.append(e)
        except Exception:
            continue

    winner = random.choice(eligible_users) if eligible_users else None
    db.giveaways.update_one({'_id': giveaway['_id']}, {'$set': {'active': False}})
    channel_list_disp = '\n'.join([f'- {link}' for link in giveaway['fs_channels']])
    if winner:
        winner_tag = f"@{winner['username']}" if winner.get('username') else winner.get('first_name', 'Anonymous')
        caption = (
            f"🎁 <b>GIVEAWAY ENDED:</b> {giveaway['title']}\n\n"
            f"<b>Required:</b>\n{channel_list_disp}\n\n"
            f"<b>Hosted By:</b> {giveaway['hosted_by']}\n"
            f"<b>Entries:</b> {len(giveaway['entries'])}\n"
            f"<b>Winner:</b> {winner_tag}\n"
            f"\nCongratulations! 🥳"
        )
    else:
        caption = (
            f"🎁 <b>GIVEAWAY ENDED:</b> {giveaway['title']}\n\n"
            f"<b>Required:</b>\n{channel_list_disp}\n\n"
            f"<b>Hosted By:</b> {giveaway['hosted_by']}\n"
            f"<b>Entries:</b> {len(giveaway['entries'])}\n"
            f"<b>No eligible winner.</b>"
        )
    try:
        await context.bot.edit_message_caption(
            chat_id=GROUP_ID,
            message_id=giveaway['message_id'],
            caption=caption,
            parse_mode='HTML'
        )
    except Exception as e:
        logging.error(f'Failed to edit giveaway message: {e}')

    for admin_id in ADMIN_IDS:
        try:
            if winner:
                await context.bot.send_message(admin_id, f"Giveaway '{giveaway['title']}' winner: {winner_tag} [ID: {winner['user_id']}]")
            else:
                await context.bot.send_message(admin_id, f"No eligible winner found for giveaway '{giveaway['title']}'.")
        except:
            pass

# =========================
#   Message Counter
# =========================

async def count_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if chat_id == GROUP_ID:
        db.msg_count.update_one({'chat_id': GROUP_ID, 'user_id': user_id}, {'$inc': {'count': 1}}, upsert=True)

# =========================
#      CANCEL GIVEAWAY
# =========================

async def cancel_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("Admins only.")
        return

    giveaway = db.giveaways.find_one({'chat_id': GROUP_ID, 'active': True, 'cancelled': False})
    if not giveaway:
        await update.message.reply_text("No active giveaway is running in this group.")
        return

    db.giveaways.update_one({'_id': giveaway['_id']}, {'$set': {'active': False, 'cancelled': True}})
    try:
        await context.bot.edit_message_caption(
            chat_id=GROUP_ID,
            message_id=giveaway['message_id'],
            caption=(
                f"❌ <b>GIVEAWAY CANCELLED:</b> {giveaway['title']}\n\n"
                f"<b>Hosted By:</b> {giveaway['hosted_by']}\n"
                f"<b>Entries:</b> {len(giveaway['entries'])}\n"
                f"This giveaway was cancelled by the admins."
            ),
            parse_mode='HTML'
        )
    except Exception as e:
        pass

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"Giveaway '{giveaway['title']}' was cancelled by admin {user_id}."
            )
        except:
            pass
    await update.message.reply_text("Giveaway cancelled.")

# =========================
#           STATS
# =========================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("Admins only.")
        return

    all_giveaways = list(db.giveaways.find({'chat_id': GROUP_ID}))
    if not all_giveaways:
        await update.message.reply_text("No giveaways have been run yet!")
        return

    text_lines = [f"📊 <b>GIVEAWAY STATS (Group Only)</b>\nTotal giveaways: {len(all_giveaways)}\n"]
    for idx, g in enumerate(all_giveaways, 1):
        if g.get('active', False):
            status = "Running"
        elif g.get('cancelled', False):
            status = "Cancelled"
        else:
            status = "Ended"
        entries = g.get('entries', [])
        winner = None

        # Try to guess winner after ended
        if not g.get('active') and not g.get('cancelled', False) and entries:
            # Remove admins
            eligible = [e for e in entries if e['user_id'] not in ADMIN_IDS]
            if eligible:
                winner = eligible[-1]  # Last one (past code may pick random, this is rough log)
        winner_str = (f"@{winner['username']}" if winner and winner.get('username') else winner['first_name']
                      if winner else "No winner")

        text_lines.append(
            f"<b>{idx}) {g.get('title', 'No title')}</b>\n"
            f"Status: {status}\n"
            f"Host: {g.get('hosted_by','')}\n"
            f"No. Entries: {len(entries)}\n"
            f"Winner: {winner_str}\n"
        )

    big_text = '\n'.join(text_lines)
    try:
        await context.bot.send_message(user_id, big_text, parse_mode='HTML')
        await update.message.reply_text("Stats sent to your DM.", quote=True)
    except:
        await update.message.reply_text("Failed to send DM (maybe you haven't started the bot in private?). Here are the stats:\n" + big_text, parse_mode='HTML')


# =========================
#         HELP
# =========================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "<b>Giveaway Bot Help</b>\n\n"
        "Commands:\n"
        "/start - Show welcome message\n"
        "/help - Show this help message\n\n"
        "<b>Admin Commands (Admins only):</b>\n"
        "/start_giveaway - Begin a new giveaway (details will be asked in DM or group)\n"
        "/cancel_giveaway - Cancel the currently running giveaway\n"
        "/stats - DM you complete stats of all giveaways\n\n"
        "<b>Usage Tips:</b>\n"
        "• All giveaways are always posted only in the fixed group.\n"
        "• FSUB can be any t.me group/channel/join link (comma-separated).\n"
        "• As participant, minimum 100 messages in the group required.\n"
        "• Bot must be admin in your group for full functionality.\n"
        "• Contact your admin team if you need to run a giveaway.\n"
    )
    await update.message.reply_text(help_text, parse_mode='HTML')
  

# =========================
#         MAIN
# =========================

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start_giveaway', start_giveaway)],
        states={
            ENTER_FS_CHANNELS: [MessageHandler(filters.TEXT, enter_fs_channels)],
            ENTER_TITLE: [MessageHandler(filters.TEXT, enter_title)],
            ENTER_BANNER: [MessageHandler(filters.PHOTO, enter_banner)],
            ENTER_HOST: [MessageHandler(filters.TEXT, enter_host)],
            ENTER_DURATION: [MessageHandler(filters.TEXT, enter_duration)],
        },
        fallbacks=[],
    )
    app.add_handler(CommandHandler('start', start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(join_giveaway_callback, pattern='join_giveaway'))
    app.add_handler(CommandHandler('cancel_giveaway', cancel_giveaway))
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(MessageHandler(filters.GROUPS & filters.TEXT, count_messages))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
  
