import os
import logging
import sqlite3
import random
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Chat
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ChatMemberHandler
)
from telegram.error import BadRequest

# --- LOAD CONFIG ---
load_dotenv()
TOKEN = os.getenv("TOKEN")
OWNER_ID = 8298238837 
LOG_GROUP_ID = -1003031295203

# --- KONFIGURASI LOGGING ---
logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.WARNING)

# --- DATABASE SETUP ---
def db_query(query, params=(), fetchone=False, fetchall=False, commit=False):
    conn = sqlite3.connect('bungkata.db')
    c = conn.cursor()
    try:
        c.execute(query, params)
        res = None
        if fetchone: res = c.fetchone()
        if fetchall: res = c.fetchall()
        if commit: conn.commit()
        return res
    finally:
        conn.close()

def init_db():
    db_query('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, points INTEGER DEFAULT 0)''', commit=True)
    db_query('''CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY, title TEXT)''', commit=True)
    db_query('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''', commit=True)
    
    defaults = [
        ('fsub_id', '-1002856616933'),
        ('fsub_link', 'https://t.me/addlist/Ld2g4xk8AAwyOTg1'),
        ('fsub_btn', '🚪 Join Channel'),
        ('fsub_status', 'on')
    ]
    for k, v in defaults:
        db_query("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v), commit=True)

init_db()

def get_setting(key):
    res = db_query("SELECT value FROM settings WHERE key=?", (key,), fetchone=True)
    return res[0] if res else ""

# --- DATA PERMAINAN ---
rooms = {}
BANNED_NAMES = ["andre", "asep", "udin", "budi", "siti", "ani", "agus", "eko", "bambang", "dedi", "rudi", "dewi", "sari", "maman", "cecep", "joko", "anwar", "andika", "fajar", "rizky", "putra", "putri", "ayu", "lestari", "fitri", "indra", "toto", "ahmad", "muhammad", "dani", "bayu", "deni", "nina", "maya", "rio", "angga"]
DICTIONARY_FILE = "list_10.0.0.txt"

def load_dictionary():
    if not os.path.exists(DICTIONARY_FILE): 
        open(DICTIONARY_FILE, 'w').close()
        return set()
    with open(DICTIONARY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip().lower() for line in f if line.strip())

dictionary = load_dictionary()

# --- UTILS ---
def is_owner(user_id): return user_id == OWNER_ID

async def check_fsub(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if is_owner(user_id) or get_setting('fsub_status') == 'off': return True
    ids_str = get_setting('fsub_id')
    if not ids_str: return True
    target_ids = ids_str.split()
    for chat_id in target_ids:
        try:
            member = await context.bot.get_chat_member(chat_id=int(chat_id), user_id=user_id)
            if member.status not in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                return False
        except:
            return False
    return True

async def send_fsub_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "<b>⚠️ AKSES TERBATAS</b>\n\nUntuk menggunakan fitur bot dan bermain di grup, Anda wajib bergabung ke Channel kami melalui link di bawah!"
    kb = [
        [InlineKeyboardButton(get_setting('fsub_btn'), url=get_setting('fsub_link'))],
        [InlineKeyboardButton("✅ Saya Sudah Join", url="https://t.me/bungkatabot?start=mulai")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

def update_points(user_id, username, amount):
    un = username.replace("@", "") if username else "Player"
    db_query("INSERT OR IGNORE INTO users (id, username, points) VALUES (?, ?, 0)", (user_id, un), commit=True)
    db_query("UPDATE users SET points = MAX(0, points + ?), username = ? WHERE id = ?", (amount, un, user_id), commit=True)

async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = update.my_chat_member
    if res.chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        if res.new_chat_member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]:
            db_query("INSERT OR IGNORE INTO groups (id, title) VALUES (?, ?)", (res.chat.id, res.chat.title), commit=True)

# --- GAME ENGINE ---
async def finish_game(context, cid):
    if cid not in rooms: return
    await context.bot.send_message(cid, "<b>🏁 PERMAINAN BERAKHIR</b>", parse_mode=ParseMode.HTML)
    rooms.pop(cid, None)
    if context.job_queue:
        for j in context.job_queue.get_jobs_by_name(f"timer_{cid}"): j.schedule_removal()

async def timeout_handler(context: ContextTypes.DEFAULT_TYPE):
    cid = context.job.chat_id
    if cid in rooms and rooms[cid]['active']:
        room = rooms[cid]
        p_id = room['players'][room['turn']]
        p_name = room['player_names'].get(p_id, "Pemain")
        await context.bot.send_message(cid, f"⏰ <b>Waktu Habis!</b>\n{p_name} dilewati karena tidak menjawab dalam 45 detik!", parse_mode=ParseMode.HTML)
        room['turn'] = (room['turn'] + 1) % len(room['players'])
        await next_turn_msg(context, cid)

async def next_turn_msg(context, cid):
    if cid not in rooms: return
    room = rooms[cid]
    next_p = room['players'][room['turn']]
    mention = f"<a href='tg://user?id={next_p}'>{room['player_names'][next_p]}</a>"
    suffix = room['suffix']
    await context.bot.send_message(cid, f"🔄 Giliran: {mention}\nSambung kata dari: <b>{suffix.upper()}</b>\n⏱ Waktu: 45 Detik!", parse_mode=ParseMode.HTML)
    if context.job_queue:
        for j in context.job_queue.get_jobs_by_name(f"timer_{cid}"): j.schedule_removal()
        context.job_queue.run_once(timeout_handler, 45, chat_id=cid, name=f"timer_{cid}")

# --- COMMAND HANDLERS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if update.effective_chat.type == Chat.PRIVATE:
        update_points(uid, update.effective_user.first_name, 0)
        await context.bot.send_message(LOG_GROUP_ID, f"👤 <b>USER START BOT</b>\n<b>Nama:</b> {update.effective_user.first_name}\n<b>ID:</b> <code>{uid}</code>", parse_mode=ParseMode.HTML)
    if not await check_fsub(uid, context): return await send_fsub_msg(update, context)
    
    text = ("👋Hallo ayok kita main sambung kata, kamu bisa tambahkan bot ini kedalam grup kamu❗\n\n"
            "- /mulai - memulai permainan di dalam grup\n"
            "- /gabung - bergabung kedalam permainan\n"
            "- /keluar - keluar dari permainan yang sedang berjalan\n"
            "- /ganti - ganti kata untuk di jawab.\n"
            "- /top - top global 10 pemain\n"
            "- /stop - menghentikan permainan yang sedang berjalan\n"
            "- /peraturan - peraturan ketika bermain\n"
            "- /usir - mengusir pemain pasif\n"
            "- /donasi - berdonasi untuk bot\n"
            "- /help - bantuan")
    
    kb = [[InlineKeyboardButton("➕ Masukkan Ke Grup", url=f"https://t.me/{context.bot.username}?startgroup=start")],
          [InlineKeyboardButton("👨‍💻 Developer", url=f"tg://user?id={OWNER_ID}"), InlineKeyboardButton("⚡ Support", url="https://t.me/bungkata")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("⚙️ <b>BANTUAN</b>\n━━━━━━━━━━━━━━\n"
            "• Bot Sambung Kata adalah bot yang menyambungkan kata dari kata awal yang diberi oleh bot lalu melanjutkan kata terakhir lawan.\n"
            "• Bot Sambung Kata dapat mengasah otak untuk mengetahui lebih dalam dari kamus KBBI.\n"
            "• Bot sambung kata dapat mengisi waktu luang kamu didalam aplikasi Telegram.")
    kb = [[InlineKeyboardButton("👨‍💻 Hubungi Pembuat", url=f"tg://user?id={OWNER_ID}")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def peraturan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("📖 <b>PERATURAN</b>\n━━━━━━━━━━━━━━━\n"
            "1. Waktu: 45 Detik.\n"
            "2. Minimal Huruf (Tingkatan Level):\n"
            "• 🟢 1-20 Easy: 2 Huruf\n"
            "• 🟡 21-40 Medium: 3 Huruf\n"
            "• 🔴 41-60 Hard: 4 Huruf\n"
            "• 🟣 61-80 Super Hard: 5 Huruf\n"
            "• 💎 81-100 Epic: 6 Huruf\n"
            "• 🏆 101-120 Master: 7 Huruf\n"
            "• 👑 121-140 Grand Master: 8 Huruf\n"
            "• 🇮🇩 141+ WNI: 9 Huruf\n\n"
            "3. Wajib Reply pesan bot.\n"
            "4. Salah = Giliran dilempar ke pemain berikutnya & Poin -5.\n"
            "5. Kata yang sudah digunakan kena limit 10 menit per-grup.\n"
            "6. Kata limit dijawab = Poin -10 & Giliran dilempar.\n"
            "7. Game Over = Jika salah 3x berturut-turut.")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def donasi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Saya Tidak Mempunyai Qris Pribadi Jika Ingin Berdonasi Silahkan Transfer Ke Dana / GOPAY / OVO ( 089678824963 )", parse_mode=ParseMode.HTML)

async def gabung_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id; room = rooms.get(cid)
    if not room: return await update.message.reply_text("❌ Tidak ada room aktif.")
    if uid in room['players']: return await update.message.reply_text("❌ Kamu sudah bergabung.")
    if not await check_fsub(uid, context): return await send_fsub_msg(update, context)
    room['players'].append(uid); room['player_names'][uid] = update.effective_user.first_name; room['mistakes'][uid] = 0
    await update.message.reply_text(f"✅ <b>{update.effective_user.first_name}</b> bergabung!", parse_mode=ParseMode.HTML)

async def keluar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id; room = rooms.get(cid); uid = update.effective_user.id
    if not room or uid not in room['players']: return
    idx = room['players'].index(uid); is_turn = (room['active'] and room['turn'] == idx)
    room['players'].pop(idx); room['player_names'].pop(uid, None); room['mistakes'].pop(uid, None)
    await update.message.reply_text(f"🏃 <b>{update.effective_user.first_name}</b> keluar dari permainan.", parse_mode=ParseMode.HTML)
    if len(room['players']) < 2: await finish_game(context, cid)
    elif room['active']:
        if idx < room['turn']: room['turn'] -= 1
        if is_turn: room['turn'] %= len(room['players']); await next_turn_msg(context, cid)

async def mulai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    if cid in rooms: return await update.message.reply_text("❌ Game sedang berjalan di grup ini!", parse_mode=ParseMode.HTML)
    rooms[cid] = {'creator': update.effective_user.id, 'players': [update.effective_user.id], 'player_names': {update.effective_user.id: update.effective_user.first_name}, 'active': False, 'suffix': '', 'turn': 0, 'turn_count': 0, 'used_words': {}, 'mistakes': {}, 'ganti_limit': {}}
    kb = [[InlineKeyboardButton("🚪 Gabung", callback_data="join"), InlineKeyboardButton("🏃 Keluar", callback_data="leave")], [InlineKeyboardButton("▶️ Play", callback_data="play")]]
    await update.message.reply_text(f"🎮 <b>ROOM DIBUKA</b>\n\n1. {update.effective_user.first_name}", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id; room = rooms.get(cid)
    if room:
        if update.effective_user.id == room['creator'] or is_owner(update.effective_user.id):
            await finish_game(context, cid)
        else:
            await update.message.reply_text("❌ Hanya Leader (pembuat room) yang bisa menghentikan permainan!", parse_mode=ParseMode.HTML)

async def usir_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id; room = rooms.get(cid)
    if room and room['active']:
        p_id = room['players'][room['turn']]; p_name = room['player_names'].get(p_id, "Pemain")
        room['players'].pop(room['turn'])
        await update.message.reply_text(f"👋 <b>{p_name}</b> diusir karena pasif!", parse_mode=ParseMode.HTML)
        if len(room['players']) < 2: await finish_game(context, cid)
        else: room['turn'] %= len(room['players']); await next_turn_msg(context, cid)

async def ganti_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id; room = rooms.get(cid)
    if room and room['active'] and uid == room['players'][room['turn']]:
        if room['ganti_limit'].get(uid, 0) >= 1:
            return await update.message.reply_text("❌ Kamu sudah menggunakan jatah /ganti (Limit 1x)!", parse_mode=ParseMode.HTML)
        room['ganti_limit'][uid] = 1
        room['suffix'] = random.choice("abcdefghijklmnopqrstuvwxyz")
        await update.message.reply_text(f"🔄 HURUF BARU: <b>{room['suffix'].upper()}</b>", parse_mode=ParseMode.HTML)

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = db_query("SELECT username, points FROM users ORDER BY points DESC LIMIT 10", fetchall=True)
    txt = "🏆 <b>TOP 10 GLOBAL</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(res): txt += f"{i+1}. {r[0]} — <code>{r[1]}</code> pts\n"
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)

# --- ADMIN COMMANDS ---
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    u = db_query("SELECT COUNT(*) FROM users", fetchone=True)[0]
    g = db_query("SELECT COUNT(*) FROM groups", fetchone=True)[0]
    await update.message.reply_text(f"📊 <b>STATISTIK BOT</b>\n\nTotal User: {u}\nTotal Grup: {g}", parse_mode=ParseMode.HTML)

async def edit_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    try:
        t, op, v = context.args[0].replace("@",""), context.args[1], int(context.args[2])
        db_query(f"UPDATE users SET points = MAX(0, points {op} ?) WHERE username=? OR id=?", (v, t, t), commit=True)
        await update.message.reply_text(f"✅ Sukses edit poin {t}!", parse_mode=ParseMode.HTML)
    except: await update.message.reply_text("Format: /e [user] [+ / -] [poin]", parse_mode=ParseMode.HTML)

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    kb = [[InlineKeyboardButton("✅ Ya", callback_data="confirm_reset"), InlineKeyboardButton("❌ Tidak", callback_data="cancel_reset")]]
    await update.message.reply_text("⚠️ <b>RESET SELURUH POIN USER?</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    if not update.message.reply_to_message and not context.args: return await update.message.reply_text("❌ Pesan kosong!", parse_mode=ParseMode.HTML)
    is_group = "bcgroup" in update.message.text; targets = db_query("SELECT id FROM " + ("groups" if is_group else "users"), fetchall=True)
    s = 0
    for t in targets:
        try:
            if is_group:
                chat = await context.bot.get_chat(t[0])
                if chat.type not in [Chat.GROUP, Chat.SUPERGROUP]: continue
            if update.message.reply_to_message: await update.message.reply_to_message.copy(t[0])
            else: await context.bot.send_message(t[0], " ".join(context.args))
            s += 1
        except: pass
    await update.message.reply_text(f"✅ Selesai disiarkan ke {s} target!", parse_mode=ParseMode.HTML)

# --- GAME LOGIC ---
async def handle_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; cid = update.effective_chat.id; room = rooms.get(cid)
    if not update.message or not update.message.text or update.message.text.startswith('/') or not room or not room['active']: return
    if not update.message.reply_to_message or update.message.reply_to_message.from_user.id != context.bot.id: return
    if u.id != room['players'][room['turn']]: return
    
    word = update.message.text.strip().lower(); tc = room['turn_count']
    
    if word in room['used_words'] and datetime.now() < room['used_words'][word]:
        update_points(u.id, u.first_name, -10)
        room['turn'] = (room['turn'] + 1) % len(room['players'])
        await update.message.reply_text(f"❌ Kata <b>{word.upper()}</b> limit 10 menit! Poin -10 & Giliran dilempar.", parse_mode=ParseMode.HTML)
        return await next_turn_msg(context, cid)
    
    if tc <= 20: min_l, lv = 2, "🟢 Easy"
    elif tc <= 40: min_l, lv = 3, "🟡 Medium"
    elif tc <= 60: min_l, lv = 4, "🔴 Hard"
    elif tc <= 80: min_l, lv = 5, "🟣 Super Hard"
    elif tc <= 100: min_l, lv = 6, "💎 Epic"
    elif tc <= 120: min_l, lv = 7, "🏆 Master"
    elif tc <= 140: min_l, lv = 8, "👑 Grand Master"
    else: min_l, lv = 9, "🇮🇩WNI🇮🇩"

    err = ""
    if word in BANNED_NAMES: err = "❌ Larangan: Nama manusia!"
    elif len(word) < min_l: err = f"❌ Minimal {min_l} huruf!"
    elif word not in dictionary: err = "❌ Tidak ada di kamus!"
    elif room['suffix'] and not word.startswith(room['suffix']): err = f"❌ Harus mulai dengan: {room['suffix'].upper()}!"
    
    if err:
        update_points(u.id, u.first_name, -5); room['mistakes'][u.id] = room['mistakes'].get(u.id, 0) + 1
        if room['mistakes'][u.id] >= 3:
            await update.message.reply_text(f"💀 <b>GAME OVER!</b>\n{u.first_name} kalah! (Poin -5)", parse_mode=ParseMode.HTML)
            room['players'].pop(room['turn'])
            if len(room['players']) < 2: return await finish_game(context, cid)
            room['turn'] %= len(room['players'])
        else:
            await update.message.reply_text(f"{err}\nPoin -5. Dilempar! ({room['mistakes'][u.id]}/3)", parse_mode=ParseMode.HTML)
            room['turn'] = (room['turn'] + 1) % len(room['players'])
        return await next_turn_msg(context, cid)

    room['mistakes'][u.id] = 0; room['used_words'][word] = datetime.now() + timedelta(minutes=10)
    room['suffix'] = word[-3:] if len(word) >= 7 else word[-2:]; room['turn_count'] += 1
    room['turn'] = (room['turn'] + 1) % len(room['players']); update_points(u.id, u.first_name, 10)
    await update.message.reply_text(f"✅ <b>BENAR!</b>\nLv: {lv}\nPoint: +10", parse_mode=ParseMode.HTML); await next_turn_msg(context, cid)

# --- SETTINGS MENU ---
async def send_settings_menu(upd, ctx):
    text = f"⚙️ <b>SETTINGS FSUB</b>\n\nStatus: {get_setting('fsub_status').upper()}\nID: <code>{get_setting('fsub_id')}</code>\nLink: {get_setting('fsub_link')}\nBtn: {get_setting('fsub_btn')}"
    kb = [[InlineKeyboardButton("Toggle Status", callback_data="st_toggle")], [InlineKeyboardButton("Edit ID", callback_data="st_id"), InlineKeyboardButton("Edit Link", callback_data="st_link")], [InlineKeyboardButton("Edit Tombol", callback_data="st_btn")], [InlineKeyboardButton("❌ Tutup", callback_data="st_close")]]
    if isinstance(upd, Update): await upd.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    else: 
        try: await upd.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
        except: pass

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_owner(update.effective_user.id): await send_settings_menu(update, context)

# --- CALLBACK LOGIC ---
async def cb_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; cid = q.message.chat_id; room = rooms.get(cid)
    if q.data == "join":
        if room and not room['active'] and uid not in room['players']:
            if not await check_fsub(uid, context): 
                try: await q.answer("Join channel dulu!", show_alert=True)
                except: pass
                return
            room['players'].append(uid); room['player_names'][uid] = q.from_user.first_name
            plist = "\n".join([f"{i+1}. {room['player_names'][p]}" for i,p in enumerate(room['players'])])
            try: await q.edit_message_text(f"🎮 <b>ROOM DIBUKA</b>\n\nBersiap:\n{plist}", reply_markup=q.message.reply_markup, parse_mode=ParseMode.HTML)
            except: pass
    elif q.data == "leave":
        if room and not room['active'] and uid in room['players']:
            room['players'].remove(uid); plist = "\n".join([f"{i+1}. {room['player_names'][p]}" for i,p in enumerate(room['players'])]) or "(Kosong)"
            try: await q.edit_message_text(f"🎮 <b>ROOM DIBUKA</b>\n\nBersiap:\n{plist}", reply_markup=q.message.reply_markup, parse_mode=ParseMode.HTML)
            except: pass
    elif q.data == "play":
        if room:
            if uid != room['creator']: 
                try: await q.answer("🙏Kamu Bukan Leader", show_alert=True)
                except: pass
                return
            if len(room['players']) < 2: 
                try: await q.answer("Minimal 2 pemain!", show_alert=True)
                except: pass
                return
            room['active'] = True; room['suffix'] = random.choice("abcdefghijklmnopqrstuvwxyz")
            await q.message.delete(); await next_turn_msg(context, cid)
    elif q.data == "st_toggle":
        v = "off" if get_setting("fsub_status") == "on" else "on"; db_query("UPDATE settings SET value=? WHERE key='fsub_status'", (v,), commit=True)
        await send_settings_menu(q, context)
    elif q.data.startswith("st_"):
        if q.data == "st_close": await q.message.delete()
        else: 
            context.user_data['edit'] = q.data.split("_")[1]
            try: await q.edit_message_text("Kirim nilai baru (atau klik Batal):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Batal", callback_data="st_back")]]), parse_mode=ParseMode.HTML)
            except: pass
    elif q.data == "st_back": 
        context.user_data.pop('edit', None)
        await send_settings_menu(q, context)
    elif q.data == "confirm_reset":
        db_query("UPDATE users SET points = 0", commit=True); await q.edit_message_text("✅ Reset Poin Seluruh User Sukses!", parse_mode=ParseMode.HTML)
    elif q.data == "cancel_reset": await q.edit_message_text("❌ Reset dibatalkan.", parse_mode=ParseMode.HTML)
    elif q.data == "check_fsub_again":
        if await check_fsub(uid, context): await q.message.delete()
        else: 
            try: await q.answer("Belum join!", show_alert=True)
            except: pass

async def settings_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id) or 'edit' not in context.user_data: return
    key = context.user_data.pop('edit'); db_query(f"UPDATE settings SET value=? WHERE key='fsub_{key}'", (update.message.text,), commit=True)
    await update.message.reply_text("✅ Berhasil Diperbarui!", parse_mode=ParseMode.HTML); await send_settings_menu(update, context)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("peraturan", peraturan_command))
    app.add_handler(CommandHandler("donasi", donasi_cmd))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("mulai", mulai_cmd))
    app.add_handler(CommandHandler("gabung", gabung_cmd))
    app.add_handler(CommandHandler("keluar", keluar_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("usir", usir_cmd))
    app.add_handler(CommandHandler("ganti", ganti_cmd))
    app.add_handler(CommandHandler("bcuser", broadcast_cmd))
    app.add_handler(CommandHandler("bcgroup", broadcast_cmd))
    app.add_handler(CommandHandler("e", edit_point))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CallbackQueryHandler(cb_logic))
    app.add_handler(ChatMemberHandler(track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, settings_input))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all))
    print(">>> BOT PROFESSIONAL ONLINE <<<"); app.run_polling()

if __name__ == '__main__': main()
