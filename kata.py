import os
import logging
import sqlite3
import random
import asyncio
import traceback
import html
import re
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
from telegram.error import Forbidden, BadRequest, NetworkError, TimedOut, RetryAfter

# --- LOAD CONFIG ---
load_dotenv()
TOKEN = os.getenv("TOKEN")
OWNER_ID = 8298238837 
LOG_GROUP_ID = -1003031295203
MIN_WITHDRAW = 5000 

# --- KONFIGURASI LOGGING ---
logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.ERROR)

# --- DATABASE SETUP (SQL PROTAG STYLE) ---
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
used_words_global = {} 
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
    if is_owner(user_id): return True
    if get_setting('fsub_status') == 'off': return True
    try:
        fsub_id = int(get_setting('fsub_id'))
        member = await context.bot.get_chat_member(chat_id=fsub_id, user_id=user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except: return False

async def send_fsub_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "<b>⚠️ AKSES TERBATAS</b>\n\nUntuk menggunakan fitur bot dan bermain di grup, Anda wajib bergabung ke Channel kami melalui link di bawah!"
    kb = [[InlineKeyboardButton(get_setting('fsub_btn'), url=get_setting('fsub_link'))], [InlineKeyboardButton("✅ Saya Sudah Join", callback_data="check_fsub_again")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

def get_user_points(user_id):
    res = db_query("SELECT points FROM users WHERE id=?", (user_id,), fetchone=True)
    return res[0] if res else 0

def update_points(user_id, username, amount):
    un = username.replace("@", "") if username else "Player"
    db_query("INSERT OR IGNORE INTO users (id, username, points) VALUES (?, ?, 0)", (user_id, un), commit=True)
    db_query("UPDATE users SET points = MAX(0, points + ?), username = ? WHERE id = ?", (amount, un, user_id), commit=True)

# --- LOGS HANDLER ---
async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if result.new_chat_member.status == ChatMemberStatus.MEMBER:
        msg = f"<b>➕ BOT MASUK GRUP BARU</b>\n<b>Judul:</b> {result.chat.title}\n<b>ID:</b> <code>{result.chat.id}</code>"
        await context.bot.send_message(LOG_GROUP_ID, msg, parse_mode=ParseMode.HTML)
        db_query("INSERT OR IGNORE INTO groups (id, title) VALUES (?, ?)", (result.chat.id, result.chat.title), commit=True)

# --- GAME ENGINE ---
async def finish_game(context, cid):
    if cid not in rooms: return
    room = rooms[cid]
    if room.get('is_tournament'):
        sorted_scores = sorted(room['t_scores'].items(), key=lambda x: x[1], reverse=True)
        if sorted_scores:
            winner_id = sorted_scores[0][0]; prize = room.get('pool', 0)
            txt = "<b>HASIL TURNAMEN SAMBUNG KATA</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            for i, (p_id, score) in enumerate(sorted_scores):
                txt += f"{i+1}. {room['player_names'].get(p_id, 'Pemain')} — {score} pts\n"
            update_points(winner_id, room['player_names'].get(winner_id), prize)
            txt += f"\nJuara 1: {room['player_names'].get(winner_id)}\nHadiah Taruhan: {prize} 💰"
            await context.bot.send_message(cid, txt + "\n🏁 Turnamen Selesai!", parse_mode=ParseMode.HTML)
    else:
        await context.bot.send_message(cid, "<b>🏁 PERMAINAN BERAKHIR</b>", parse_mode=ParseMode.HTML)
    rooms.pop(cid, None); used_words_global.pop(cid, None)
    if context.job_queue:
        for j in context.job_queue.get_jobs_by_name(f"timer_{cid}"): j.schedule_removal()

async def timeout_handler(context: ContextTypes.DEFAULT_TYPE):
    cid = context.job.chat_id
    if cid in rooms and rooms[cid]['active']:
        room = rooms[cid]
        p_id = room['players'][room['turn']]
        p_name = room['player_names'].get(p_id, "Pemain")
        await context.bot.send_message(cid, f"⏰ <b>Waktu Habis!</b>\n{p_name} dianggap Miss karena tidak menjawab selama 45 detik!", parse_mode=ParseMode.HTML)
        room['turn'] = (room['turn'] + 1) % len(room['players'])
        await next_turn_msg(context, cid)

async def next_turn_msg(context, cid):
    room = rooms[cid]
    next_p = room['players'][room['turn']]
    mention = f"<a href='tg://user?id={next_p}'>{room['player_names'][next_p]}</a>"
    suffix = room['suffix']
    await context.bot.send_message(cid, f"🔄 Giliran: {mention}\nSambung kata dari: <b>{suffix.upper()}</b>\n⏱ Waktu: 45 Detik!", parse_mode=ParseMode.HTML)
    schedule_timer(context, cid)

def schedule_timer(context, chat_id):
    if not context.job_queue: return
    for j in context.job_queue.get_jobs_by_name(f"timer_{chat_id}"): j.schedule_removal()
    context.job_queue.run_once(timeout_handler, 45, chat_id=chat_id, name=f"timer_{chat_id}")

# --- COMMANDS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if update.effective_chat.type == Chat.PRIVATE:
        update_points(uid, update.effective_user.first_name, 0)
        await context.bot.send_message(LOG_GROUP_ID, f"👤 <b>USER START BOT</b>\n<b>Nama:</b> {update.effective_user.first_name}\n<b>ID:</b> <code>{uid}</code>", parse_mode=ParseMode.HTML)
    
    if not await check_fsub(uid, context): return await send_fsub_msg(update, context)
    
    text = ("👋Hallo ayok kita main sambung kata, kamu bisa tambahkan bot ini kedalam grup kamu❗\n\n"
            "- /mulai - memulai permainan di dalam grup\n"
            "- /turnamen - mode kompetisi (Hadiah Taruhan)\n"
            "- /gabung - bergabung kedalam permainan\n"
            "- /keluar - keluar dari permainan yang sedang berjalan\n"
            "- /withdraw - tukar poin jadi saldo (Private Chat)\n"
            "- /ganti - ganti kata untuk di jawab.\n"
            "- /top - top global 10 pemain\n"
            "- /stop - menghentikan permainan yang sedang berjalan\n"
            "- /peraturan - peraturan ketika bermain\n"
            "- /usir - mengusir pemain pasif\n"
            "- /donasi - berdonasi untuk bot\n"
            "- /help - bantuan")
    kb = [[InlineKeyboardButton("➕ Masukkan Ke Grup", url=f"https://t.me/{context.bot.username}?startgroup=start")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def donasi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Saya Tidak Mempunyai Qris Pribadi Jika Ingin Berdonasi Silahkan Transfer Ke Dana / GOPAY / OVO ( 089678824963 )")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("⚙️ BANTUAN\n━━━━━━━━━━━━━━\n"
            "• Bot Sambung Kata adalah bot yang menyambungkan kata dari kata awal yang diberi oleh bot lalu melanjutkan kata terakhir lawan.\n"
            "• Bot Sambung Kata dapat mengasah otak untuk mengetahui lebih dalam dari kamus KBBI.\n"
            "• Bot sambung kata dapat mengisi waktu luang kamu didalam aplikasi Telegram.")
    kb = [[InlineKeyboardButton("👨‍💻 Hubungi Pembuat", url=f"tg://user?id={OWNER_ID}")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def peraturan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("📖 PERATURAN\n━━━━━━━━━━━━━━━\n"
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
            "3. Wajib Reply pesan bot\n"
            "4. Salah = Giliran dilempar ke pemain berikutnya.\n"
            "5. Game Over = Jika salah 3x berturut-turut.\n"
            "6. Pemenang Turnamen mendapatkan semua taruhan.")
    await update.message.reply_text(text)

async def gabung_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id; room = rooms.get(cid)
    if not room: return await update.message.reply_text("❌ Tidak ada room aktif.")
    if uid in room['players']: return await update.message.reply_text("❌ Kamu sudah bergabung.")
    if not await check_fsub(uid, context): return await send_fsub_msg(update, context)
    
    if room['is_tournament']:
        stake_val = list(room['stakes'].values())[0] if room['stakes'] else 100
        if get_user_points(uid) < stake_val:
            return await update.message.reply_text(f"❌ Poin tidak cukup ({stake_val}💰).")
        update_points(uid, update.effective_user.first_name, -stake_val)
        room['pool'] += stake_val; room['stakes'][uid] = stake_val; room['t_scores'][uid] = 0
    
    room['players'].append(uid); room['player_names'][uid] = update.effective_user.first_name
    await update.message.reply_text(f"✅ {update.effective_user.first_name} bergabung ke dalam permainan!")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    is_group = "bcgroup" in update.message.text
    targets = db_query("SELECT id FROM groups" if is_group else "SELECT id FROM users", fetchall=True)
    if not targets: return await update.message.reply_text("Tidak ada target.")
    
    prog_msg = await update.message.reply_text("<b>🚀 Memulai Penyiaran...</b>", parse_mode=ParseMode.HTML)
    s, f, total = 0, 0, len(targets)
    for i, t in enumerate(targets):
        try:
            if update.message.reply_to_message: await update.message.reply_to_message.copy(t[0])
            else: await context.bot.send_message(t[0], " ".join(context.args))
            s += 1
        except: f += 1
        if i % 15 == 0 or i == total - 1:
            await prog_msg.edit_text(f"<b>⏳ Sedang Menyiarkan...</b>\n\n✅ Sukses: <code>{s}</code>\n❌ Gagal: <code>{f}</code>\n📊 Progress: <code>{i+1}/{total}</code>", parse_mode=ParseMode.HTML)
        await asyncio.sleep(0.05)
    await prog_msg.edit_text(f"<b>📢 Broadcast Selesai!</b>\n\n✅ Berhasil: {s}\n❌ Gagal: {f}", parse_mode=ParseMode.HTML)

# --- GAME LOGIC ---
async def handle_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; cid = update.effective_chat.id
    if update.effective_chat.type != Chat.PRIVATE:
        db_query("INSERT OR IGNORE INTO groups (id, title) VALUES (?, ?)", (cid, update.effective_chat.title), commit=True)
    
    if not update.message or not update.message.text or update.message.text.startswith('/') or cid not in rooms or not rooms[cid]['active']: return
    room = rooms[cid]
    if not update.message.reply_to_message or update.message.reply_to_message.from_user.id != context.bot.id: return
    if u.id != room['players'][room['turn']]: return
    
    word = update.message.text.strip().lower()
    tc = room['turn_count']
    
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
        # Logika 3x Salah Berturut-turut
        room['mistakes'][u.id] = room['mistakes'].get(u.id, 0) + 1
        if room['mistakes'][u.id] >= 3:
            await update.message.reply_text(f"💀 <b>GAME OVER!</b>\n{u.first_name} dikeluarkan karena 3x salah berturut-turut!", parse_mode=ParseMode.HTML)
            room['players'].pop(room['turn'])
            if len(room['players']) < 2:
                await finish_game(context, cid)
                return
        else:
            await update.message.reply_text(f"{err}\nJawaban salah ({room['mistakes'][u.id]}/3)! Giliran dilempar.")
            room['turn'] = (room['turn'] + 1) % len(room['players'])
        
        await next_turn_msg(context, cid)
        return

    # Reset mistake counter jika benar
    room['mistakes'][u.id] = 0
    room['suffix'] = word[-3:] if len(word) >= 7 else word[-2:]
    room['turn_count'] += 1
    room['turn'] = (room['turn'] + 1) % len(room['players'])
    
    if room['is_tournament']: room['t_scores'][u.id] = room['t_scores'].get(u.id, 0) + 10
    else: update_points(u.id, u.first_name, 10)
    
    await update.message.reply_text(f"✅ <b>BENAR!</b>\nLv: {lv}\nPoint: +10", parse_mode=ParseMode.HTML)
    await next_turn_msg(context, cid)

# --- MULAI LOGIC ---
async def mulai_cmd(update, context): await mulai_logic(update, context, False)
async def turnamen_cmd(update, context): await mulai_logic(update, context, True)

async def mulai_logic(u, c, is_t):
    if u.effective_chat.type == Chat.PRIVATE: return 
    cid = u.effective_chat.id
    if cid in rooms: return await u.message.reply_text("❌ Room aktif!")
    if not await check_fsub(u.effective_user.id, c): return await send_fsub_msg(u, c)
    
    rooms[cid] = {'creator': u.effective_user.id, 'players': [u.effective_user.id], 'player_names': {u.effective_user.id: u.effective_user.first_name}, 'active': False, 'suffix': "", 'turn': 0, 'is_tournament': is_t, 't_scores': {}, 'pool': 0, 'stakes': {}, 'turn_count': 0, 'ganti_used': False, 'mistakes': {}}
    
    if is_t:
        kb = [[InlineKeyboardButton("100💰", callback_data="stake_100"), InlineKeyboardButton("500💰", callback_data="stake_500"), InlineKeyboardButton("1000💰", callback_data="stake_1000")], [InlineKeyboardButton("▶️MULAI SEKARANG🎮", callback_data="play")]]
        await u.message.reply_text("💰Turnamen Dibuka🎮\n\nPemain yang bergabung:", reply_markup=InlineKeyboardMarkup(kb))
    else:
        kb = [[InlineKeyboardButton("🚪 Gabung", callback_data="join"), InlineKeyboardButton("🏃 Keluar", callback_data="leave")], [InlineKeyboardButton("▶️ Play", callback_data="play")]]
        await u.message.reply_text(f"🎮 ROOM DIBUKA\n\nBersiap:\n1. {u.effective_user.first_name}", reply_markup=InlineKeyboardMarkup(kb))

async def cb_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; cid = q.message.chat_id; uid = q.from_user.id; room = rooms.get(cid)
    if q.data == "check_fsub_again":
        if await check_fsub(uid, context): await q.message.delete()
        else: await q.answer("Belum join!", show_alert=True)
    elif q.data == "confirm_reset":
        db_query("DELETE FROM users", commit=True)
        db_query("DELETE FROM groups", commit=True)
        await q.edit_message_text("✅ Database berhasil direset total!")
    elif q.data == "cancel_reset":
        await q.edit_message_text("❌ Reset dibatalkan.")
    elif q.data.startswith("stake_"):
        if not room or room['active'] or uid in room['players']: return
        amt = int(q.data.split("_")[1])
        if get_user_points(uid) < amt: return await q.answer("Poin tidak cukup!", show_alert=True)
        update_points(uid, q.from_user.first_name, -amt); room['players'].append(uid); room['player_names'][uid] = q.from_user.first_name; room['pool'] += amt; room['stakes'][uid] = amt; room['t_scores'][uid] = 0; room['mistakes'][uid] = 0
        plist = "\n".join([f"- bersiap {room['player_names'][p]} {room['stakes'][p]}💰" for p in room['players']])
        await q.edit_message_text(f"💰Turnamen Dibuka🎮\n\n{plist}", reply_markup=q.message.reply_markup)
    elif q.data == "join":
        if room and uid not in room['players']:
            room['players'].append(uid); room['player_names'][uid] = q.from_user.first_name; room['mistakes'][uid] = 0
            plist = "\n".join([f"{i+1}. {room['player_names'][p]}" for i, p in enumerate(room['players'])])
            await q.edit_message_text(f"🎮 ROOM DIBUKA\n\nBersiap:\n{plist}", reply_markup=q.message.reply_markup)
    elif q.data == "play":
        if room and uid == room['creator'] and len(room['players']) >= 2:
            room['active'] = True; random.shuffle(room['players'])
            room['suffix'] = random.choice("abcdefghijklmnopqrstuvwxyz")
            await q.message.delete(); await next_turn_msg(context, cid)

# --- ADMIN RESET COMMAND ---
async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    kb = [[InlineKeyboardButton("✅ Ya, Reset", callback_data="confirm_reset"), InlineKeyboardButton("❌ Tidak", callback_data="cancel_reset")]]
    await update.message.reply_text("⚠️ <b>KONFIRMASI RESET</b>\n\nApakah Anda yakin ingin menghapus seluruh data User dan Grup dari database?", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

# --- OTHER COMMANDS ---
async def top_cmd(u, c):
    res = db_query("SELECT username, points FROM users ORDER BY points DESC LIMIT 10", fetchall=True)
    txt = "🏆 <b>TOP 10 PEMAIN GLOBAL</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(res): txt += f"{i+1}. {r[0]} — <code>{r[1]}</code> pts\n"
    await u.message.reply_text(txt, parse_mode=ParseMode.HTML)

async def stop_game_cmd(u, c):
    room = rooms.get(u.effective_chat.id)
    if room:
        member = await c.bot.get_chat_member(u.effective_chat.id, u.effective_user.id)
        if is_owner(u.effective_user.id) or u.effective_user.id == room['creator'] or member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await finish_game(c, u.effective_chat.id)

async def usir_cmd(u, c):
    room = rooms.get(u.effective_chat.id)
    if room and room['active']:
        p_id = room['players'][room['turn']]
        p_name = room['player_names'].get(p_id, "Pemain")
        room['players'].pop(room['turn'])
        await u.message.reply_text(f"👋 {p_name} diusir dari permainan!")
        if len(room['players']) < 2: await finish_game(c, u.effective_chat.id)
        else: room['turn'] %= len(room['players']); await next_turn_msg(c, u.effective_chat.id)

async def keluar_cmd(u, c):
    cid = u.effective_chat.id; room = rooms.get(cid)
    if not room or u.effective_user.id not in room['players']: return
    uid = u.effective_user.id; idx = room['players'].index(uid); room['players'].pop(idx); room['player_names'].pop(uid, None)
    await u.message.reply_text(f"🏃 {u.effective_user.first_name} keluar dari permainan.")
    if len(room['players']) < 2: await finish_game(c, cid)
    elif room['active']: room['turn'] %= len(room['players'])

async def ganti_cmd(u, c):
    room = rooms.get(u.effective_chat.id)
    if room and room['active'] and u.effective_user.id == room['players'][room['turn']] and not room['ganti_used']:
        room['suffix'] = random.choice("abcdefghijklmnopqrstuvwxyz"); room['ganti_used'] = True
        await u.message.reply_text(f"🔄 HURUF BARU: <b>{room['suffix'].upper()}</b>", parse_mode=ParseMode.HTML)

async def withdraw_cmd(u, c):
    if u.effective_chat.type != Chat.PRIVATE: return
    args = c.args
    if len(args) < 3: return await u.message.reply_text("💰 Format: /withdraw [pts] [metode] [nomor]")
    try:
        pts = int(args[0]); curr = get_user_points(u.effective_user.id)
        if pts < MIN_WITHDRAW or curr < pts: return await u.message.reply_text(f"❌ Poin tidak cukup. Minimal {MIN_WITHDRAW}.")
        update_points(u.effective_user.id, u.effective_user.first_name, -pts)
        await c.bot.send_message(OWNER_ID, f"💰 WD REQUEST\nUser: {u.effective_user.first_name}\nID: {u.effective_user.id}\nJumlah: {pts}\nMetode: {args[1]}\nNomor: {' '.join(args[2:])}")
        await u.message.reply_text("✅ Permintaan withdraw dikirim ke owner!")
    except: pass

async def edit_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    try:
        target = context.args[0].replace("@", "")
        op = context.args[1]; val = int(context.args[2])
        res = db_query("SELECT id, username FROM users WHERE username=? OR id=?", (target, target), fetchone=True)
        if res:
            uid, uname = res
            db_query(f"UPDATE users SET points = MAX(0, points {op} ?) WHERE id=?", (val, uid), commit=True)
            await update.message.reply_text(f"✅ Berhasil edit poin {uname} {op}{val}.")
        else: await update.message.reply_text("❌ User tidak ditemukan.")
    except: await update.message.reply_text("Format: /e [username/id] [+ / -] [jumlah]")

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    args = context.args
    if not args:
        text = (f"⚙️ PENGATURAN FSUB\n\nStatus: {get_setting('fsub_status').upper()}\n"
                f"ID: {get_setting('fsub_id')}\nLink: {get_setting('fsub_link')}\nBtn: {get_setting('fsub_btn')}\n\n"
                "Gunakan: /settings [status/id/link/btn] [nilai]")
        return await update.message.reply_text(text)
    k, v = args[0].lower(), " ".join(args[1:])
    if k in ["status", "id", "link", "btn"]:
        db_query(f"UPDATE settings SET value=? WHERE key='fsub_{k}'", (v,), commit=True)
        await update.message.reply_text(f"✅ {k} berhasil diupdate!")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    u_count = db_query("SELECT COUNT(*) FROM users", fetchone=True)[0]
    g_count = db_query("SELECT COUNT(*) FROM groups", fetchone=True)[0]
    await update.message.reply_text(f"📊 STATISTIK BOT\n\nTotal User: {u_count}\nTotal Grup: {g_count}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("peraturan", peraturan_command))
    app.add_handler(CommandHandler("mulai", mulai_cmd))
    app.add_handler(CommandHandler("turnamen", turnamen_cmd))
    app.add_handler(CommandHandler("gabung", gabung_cmd))
    app.add_handler(CommandHandler("keluar", keluar_cmd))
    app.add_handler(CommandHandler("bcuser", broadcast_cmd))
    app.add_handler(CommandHandler("bcgroup", broadcast_cmd))
    app.add_handler(CommandHandler("e", edit_point))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("usir", usir_cmd))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("stop", stop_game_cmd))
    app.add_handler(CommandHandler("ganti", ganti_cmd))
    app.add_handler(CommandHandler("withdraw", withdraw_cmd))
    app.add_handler(CommandHandler("donasi", donasi_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CallbackQueryHandler(cb_logic))
    app.add_handler(ChatMemberHandler(track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all))
    print(">>> BOT SAMBUNG KATA PRO ONLINE <<<")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__': main()
