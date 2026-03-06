import os
import logging
import sqlite3
import random
import asyncio
import traceback
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
from telegram.error import BadRequest, Forbidden

# --- LOAD CONFIG ---
load_dotenv()
TOKEN = os.getenv("TOKEN")
OWNER_ID = 8298238837 
LOG_GROUP_ID = -1003031295203
QRIS_DATA = "00020101021126610014COM.GO-JEK.WWW01189360091436446025500210G6446025500303UMI51440014ID.CO.QRIS.WWW0215ID10254092891920303UMI5204581253033605802ID5925Bajigur Mas GONDRONG, SRN6007CIREBON61054515162070703A016304A4C2"

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
    db_query('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, 
        username TEXT, 
        points INTEGER DEFAULT 0, 
        max_tc INTEGER DEFAULT 0,
        balance INTEGER DEFAULT 0,
        spin_count INTEGER DEFAULT 0
    )''', commit=True)
    db_query('''CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY, title TEXT)''', commit=True)
    db_query('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''', commit=True)
    
    columns = [row[1] for row in db_query("PRAGMA table_info(users)", fetchall=True)]
    if "balance" not in columns: db_query("ALTER TABLE users ADD COLUMN balance INTEGER DEFAULT 0", commit=True)
    if "spin_count" not in columns: db_query("ALTER TABLE users ADD COLUMN spin_count INTEGER DEFAULT 0", commit=True)
    if "max_tc" not in columns: db_query("ALTER TABLE users ADD COLUMN max_tc INTEGER DEFAULT 0", commit=True)

    defaults = [
        ('fsub_id', '-1002856616933'),
        ('fsub_link', 'https://t.me/addlist/Ld2g4xk8AAwyOTg1'),
        ('fsub_btn', '🚪 Join Channel'),
        ('fsub_status', 'on'),
        ('fsub_msg', '<b>⚠️ AKSES TERBATAS</b>\n\nUntuk menggunakan fitur bot dan bermain di grup, Anda wajib bergabung ke Channel kami melalui link di bawah! {mention}')
    ]
    for k, v in defaults:
        db_query("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v), commit=True)

init_db()

def get_setting(key):
    res = db_query("SELECT value FROM settings WHERE key=?", (key,), fetchone=True)
    return res[0] if res else ""

def set_setting(key, value):
    db_query("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)), commit=True)

# --- DATA PERMAINAN ---
rooms = {}
SOLO_ROOMS = {} 
BANNED_NAMES = ["andre", "asep", "udin", "budi", "siti", "ani", "agus", "eko", "bambang", "dedi", "rudi", "dewi", "sari", "maman", "cecep", "joko", "anwar", "andika", "fajar", "rizky", "putra", "putri", "ayu", "lestari", "fitri", "indra", "toto", "ahmad", "muhammad", "dani", "bayu", "deni", "nina", "maya", "rio", "angga"]
DICTIONARY_FILE = "list_10.0.0.txt"

def load_dictionary():
    if not os.path.exists(DICTIONARY_FILE): 
        open(DICTIONARY_FILE, 'w').close()
        return set()
    with open(DICTIONARY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip().lower() for line in f if line.strip())

dictionary = load_dictionary()

def get_level_info(tc):
    if tc <= 20: return "Easy", 3, "🟢"
    elif tc <= 40: return "Medium", 4, "🟡"
    elif tc <= 60: return "Hard", 5, "🔴"
    elif tc <= 80: return "Harapan 3", 6, "🥉"
    elif tc <= 100: return "Harapan 2", 7, "🥈"
    elif tc <= 120: return "Jawara Harapan", 8, "🥇"
    elif tc <= 140: return "Legend Kata", 9, "🏆"
    else: return "WNI (Warga Negara Indonesia)", 10, "🏅"

# --- UTILS ---
def is_owner(user_id): return user_id == OWNER_ID

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, BadRequest) and "Message is not modified" in str(context.error): return
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    log_msg = (f"⚠️ <b>DETEKSI ERROR SISTEM</b>\n\n<b>Error:</b> <code>{context.error}</code>\n\n<b>Traceback:</b>\n<code>{tb_string[-2000:]}</code>")
    try: await context.bot.send_message(LOG_GROUP_ID, log_msg, parse_mode=ParseMode.HTML)
    except: pass

async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = update.my_chat_member
    if res.chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        if res.new_chat_member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]:
            db_query("INSERT OR IGNORE INTO groups (id, title) VALUES (?, ?)", (res.chat.id, res.chat.title), commit=True)
            log_txt = (f"📥 <b>BOT MASUK GRUP BARU</b>\n\n<b>Grup:</b> {res.chat.title}\n<b>ID:</b> <code>{res.chat.id}</code>")
            try: await context.bot.send_message(LOG_GROUP_ID, log_txt, parse_mode=ParseMode.HTML)
            except: pass

async def check_fsub(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if is_owner(user_id) or get_setting('fsub_status') == 'off': return True
    ids_str = get_setting('fsub_id')
    if not ids_str: return True
    for chat_id in ids_str.split():
        try:
            member = await context.bot.get_chat_member(chat_id=int(chat_id), user_id=user_id)
            if member.status not in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]: return False
        except: return False
    return True

async def send_fsub_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mention = update.effective_user.mention_html()
    text = get_setting('fsub_msg').replace("{mention}", mention)
    kb = [[InlineKeyboardButton(get_setting('fsub_btn'), url=get_setting('fsub_link'))],
          [InlineKeyboardButton("✅ Saya Sudah Join", url=f"https://t.me/{context.bot.username}?start=mulai")]]
    try: await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    except: pass

def update_points(user_id, username, amount, tc_reached=0):
    un = username.replace("@", "") if username else "Player"
    db_query("INSERT OR IGNORE INTO users (id, username, points, max_tc, balance, spin_count) VALUES (?, ?, 0, 0, 0, 0)", (user_id, un), commit=True)
    db_query("UPDATE users SET points = MAX(0, points + ?), username = ?, max_tc = MAX(max_tc, ?) WHERE id = ?", (amount, un, tc_reached, user_id), commit=True)

# --- GAME ENGINE ---
async def finish_game(context, cid):
    if cid not in rooms: return
    try: await context.bot.send_message(cid, "<b>🏁 PERMAINAN BERAKHIR</b>", parse_mode=ParseMode.HTML)
    except: pass
    rooms.pop(cid, None)
    if context.job_queue:
        for j in context.job_queue.get_jobs_by_name(f"timer_{cid}"): j.schedule_removal()

async def timeout_handler(context: ContextTypes.DEFAULT_TYPE):
    cid = context.job.chat_id
    if cid in rooms and rooms[cid]['active']:
        room = rooms[cid]
        if not room['players']: return await finish_game(context, cid)
        p_id = room['players'][room['turn']]
        p_name = room['player_names'].get(p_id, "Pemain")
        try: await context.bot.send_message(cid, f"⏰ <b>Waktu Habis!</b>\n{p_name} dilewati karena tidak menjawab dalam 45 detik!", parse_mode=ParseMode.HTML)
        except: pass
        room['turn'] = (room['turn'] + 1) % len(room['players'])
        await next_turn_msg(context, cid)

async def next_turn_msg(context, cid):
    if cid not in rooms: return
    room = rooms[cid]
    if not room['players']: return await finish_game(context, cid)
    room['turn'] %= len(room['players'])
    next_p = room['players'][room['turn']]
    mention = f"<a href='tg://user?id={next_p}'>{room['player_names'][next_p]}</a>"
    suffix = room['suffix']
    lvl_name, min_h, lvl_emo = get_level_info(room['turn_count'])
    try:
        await context.bot.send_message(cid, f"📊 Level: {lvl_emo} <b>{lvl_name}</b> (Min {min_h} Huruf)\n🔄 Giliran: {mention}\nSambung kata dari: <b>{suffix.upper()}</b>\n⏱ Waktu: 45 Detik!", parse_mode=ParseMode.HTML)
    except: pass
    if context.job_queue:
        for j in context.job_queue.get_jobs_by_name(f"timer_{cid}"): j.schedule_removal()
        context.job_queue.run_once(timeout_handler, 45, chat_id=cid, name=f"timer_{cid}")

# --- COMMAND HANDLERS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id
    if update.effective_chat.type == Chat.PRIVATE:
        update_points(uid, update.effective_user.first_name, 0)
    if not await check_fsub(uid, context): return await send_fsub_msg(update, context)
    
    text1 = (" 👋 Hallo, ayok kita main sambung kata!\n\n"
            "Kamu bisa tambahkan bot ini kedalam grup kamu❗\n\n"
            "🕹️ KONTROL PERMAINAN:\n"
            "• /mulai - Memulai game (Grup / Private)\n"
            "• /gabung - Ikut bermain (Grup)\n"
            "• /keluar - Berhenti bermain\n"
            "• /ganti - Ganti huruf awal (Limit 1x)\n"
            "• /stop - Paksa berhenti permainan\n"
            "• /usir - Mengeluarkan pemain pasif\n\n"
            "🏆 MENU POIN & HADIAH:\n"
            "• /top - Lihat 10 pemain terbaik dunia\n"
            "• /spin - Event Ramadhan Spin\n"
            "• /donasi - Support Developer\n"
            "• /peraturan - Aturan & tingkatan level\n"
            "• /help - Panduan lengkap bot\n\n"
            "⚠️𝖣𝗂𝖽𝗎𝗄𝗎𝗇𝗀 𝖮𝗅𝖾𝗁: <a href='https://t.me/drakwebot'>𝖣𝗋𝖺𝗄𝗐𝖾𝖻 𝖦𝖺𝗆𝖾</a>")
    
    kb1 = [[InlineKeyboardButton("➕ MASUKKAN KE GRUP", url=f"https://t.me/{context.bot.username}?startgroup=start")],
          [InlineKeyboardButton("👨‍💻 Developer", url=f"tg://user?id={OWNER_ID}"), InlineKeyboardButton("⚡ Support", url="https://t.me/bungkata")]]
    await update.effective_message.reply_text(text1, reply_markup=InlineKeyboardMarkup(kb1), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    text2 = "🏃‍♀️<b>Raih Segera Akun Anda Kedalam Level Paling Sulit Level (🏅WNI)</b>"
    kb2 = [[InlineKeyboardButton("📖 Kamus", url="https://t.me/kbbibot")]]
    msg2 = await update.effective_message.reply_text(text2, reply_markup=InlineKeyboardMarkup(kb2), parse_mode=ParseMode.HTML)
    try: await context.bot.pin_chat_message(chat_id=cid, message_id=msg2.message_id)
    except: pass

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("❓ <b>PANDUAN LENGKAP BOT SAMBUNG KATA</b>\n\n"
            "Bot ini adalah bot kecerdasan kata yang menggunakan database kamus resmi Bahasa Indonesia. Tujuan game ini adalah menyambung kata dari akhiran kata lawan.\n\n"
            "💡 <b>CARA BERMAIN:</b>\n"
            "1. Masukkan bot ke grup Anda.\n"
            "2. Ketik /mulai untuk membuka pendaftaran.\n"
            "3. Pemain lain mengetik /gabung.\n"
            "4. Leader mengetik 'Play' pada tombol.\n"
            "5. Bot memberikan huruf akhiran, Anda wajib <b>REPLY</b> pesan bot tersebut dengan kata yang benar.\n\n"
            "👤 <b>MODE SOLO:</b>\n"
            "Anda bisa bermain sendiri di chat pribadi dengan mengetik /mulai. Berguna melatih kosakata dan menambah poin global (+1 Benar / -1 Salah).\n\n"
            "💰 <b>HADIAH (SPIN):</b>\n"
            "Kumpulkan poin global. Poin dapat ditukar menjadi saldo keberuntungan melalui menu /spin.\n\n"
            "🎁 <b>DONASI:</b>\n"
            "Jika kamu menyukai bot ini dan ingin memberikan donasi kepada Developer (Dev.TJ) Sambung-Kata kamu bisa mengirimkan nya ke nomor Gopay yang tersedia!\n\n"
            "<b>Gopay:</b> <code>089678824963</code> a/n TJ\n\n"
            "🛠 <b>SUPPORT:</b> Hubungi @bungkata")
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

async def peraturan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("📖 <b>PERATURAN PERMAINAN</b>\n━━━━━━━━━━━━━━━\n"
            "1. ⏱️ <b>Waktu:</b> 45 detik untuk menjawab.\n"
            "2. 📊 <b>Minimal Huruf (Level System):</b>\n"
            "• 🟢 Easy: 3 Huruf (Q 1-20)\n"
            "• 🟡 Medium: 4 Huruf (Q 21-40)\n"
            "• 🔴 Hard: 5 Huruf (Q 41-60)\n"
            "• 🥉 Harapan 3: 6 Huruf (Q 61-80)\n"
            "• 🥈 Harapan 2: 7 Huruf (Q 81-100)\n"
            "• 🥇 Jawara Harapan: 8 Huruf (Q 101-120)\n"
            "• 🏆 Legend Kata: 9 Huruf (Q 121-140)\n"
            "• 🏅 WNI: 10 Huruf (Q 141+)\n\n"
            "3. 🚫 <b>Larangan:</b>\n"
            "• Dilarang menggunakan nama orang.\n"
            "• Dilarang kata yang sudah dipakai (Limit 30 menit).\n"
            "• Wajib Reply pesan bot saat di dalam Grup.\n\n"
            "4. 💀 <b>Eliminasi:</b>\n"
            "Salah sebanyak 3 kali atau tidak menjawab tepat waktu akan membuat Anda keluar otomatis.")
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)

async def donasi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = ("🎁 <b>DONASI</b> 🎁 \n"
            "Donasi ini digunakan untuk kebutuhan bot agar bot tetap hidup.\n"
            "Jika kamu menyukai bot ini silahkan berdonasi melalui qris manual dibawah.")
    kb = [[InlineKeyboardButton("🎁 Donasi", callback_data="donasi_qris")]]
    if update.effective_message: await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    else: await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def spin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != Chat.PRIVATE:
        return await update.effective_message.reply_text("❌ Fitur /spin hanya dapat digunakan di Private Chat bot.")
    text = "🏆 <b>Spinwells Event Ramadhan</b>"
    kb = [[InlineKeyboardButton("🎡 Spin", callback_data="spin_go")],
          [InlineKeyboardButton("✅ Cek Saldo", callback_data="spin_cek")],
          [InlineKeyboardButton("💰 Withdraw", callback_data="spin_wd")]]
    await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def gabung_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id; room = rooms.get(cid)
    if not room: return await update.effective_message.reply_text("❌ Tidak ada pendaftaran aktif.")
    if uid in room['players']: return await update.effective_message.reply_text("❌ Anda sudah masuk pendaftaran.")
    if not await check_fsub(uid, context): return await send_fsub_msg(update, context)
    room['players'].append(uid); room['player_names'][uid] = update.effective_user.first_name; room['mistakes'][uid] = 0
    await update.effective_message.reply_text(f"✅ <b>{update.effective_user.first_name}</b> masuk ke arena!", parse_mode=ParseMode.HTML)

async def keluar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id
    if update.effective_chat.type == Chat.PRIVATE:
        if uid in SOLO_ROOMS: SOLO_ROOMS.pop(uid); return await update.effective_message.reply_text("🛑 <b>Game Solo Dihentikan.</b>", parse_mode=ParseMode.HTML)
        return
    room = rooms.get(cid)
    if not room or uid not in room['players']: return
    idx = room['players'].index(uid); is_turn = (room['active'] and room['turn'] == idx)
    room['players'].pop(idx); room['player_names'].pop(uid, None); room['mistakes'].pop(uid, None)
    await update.effective_message.reply_text(f"🏃 <b>{update.effective_user.first_name}</b> keluar.", parse_mode=ParseMode.HTML)
    if len(room['players']) < 2: await finish_game(context, cid)
    elif room['active']: 
        room['turn'] %= len(room['players'])
        if is_turn: await next_turn_msg(context, cid)

async def mulai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id
    if update.effective_chat.type == Chat.PRIVATE:
        if uid in SOLO_ROOMS: return await update.effective_message.reply_text("❌ Game Solo sedang berjalan!", parse_mode=ParseMode.HTML)
        start_char = random.choice("abcdefghijklmnopqrstuvwxyz")
        SOLO_ROOMS[uid] = {'suffix': start_char, 'used_words': {}, 'turn_count': 0}
        await update.effective_message.reply_text(f"🎮 <b>SOLO MODE: AKTIF</b>\n\nSambung kata dari: <b>{start_char.upper()}</b>", parse_mode=ParseMode.HTML)
        return
    if cid in rooms: return await update.effective_message.reply_text("❌ Game sudah berjalan!", parse_mode=ParseMode.HTML)
    rooms[cid] = {'creator': uid, 'players': [uid], 'player_names': {uid: update.effective_user.first_name}, 'active': False, 'suffix': '', 'turn': 0, 'turn_count': 0, 'used_words': {}, 'mistakes': {}, 'ganti_limit': {}, 'usir_limit': 1}
    kb = [[InlineKeyboardButton("🚪 Gabung", callback_data="join"), InlineKeyboardButton("🏃 Keluar", callback_data="leave")], [InlineKeyboardButton("▶️ Play", callback_data="play")]]
    await context.bot.send_message(chat_id=cid, text=f"🎮 <b>ROOM DIBUKA</b>\n\n<b>Pemain:</b>\n1. {update.effective_user.first_name}", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id; uid = update.effective_user.id
    if update.effective_chat.type == Chat.PRIVATE:
        if uid in SOLO_ROOMS: SOLO_ROOMS.pop(uid); return await update.effective_message.reply_text("🏁 <b>Game Solo Berhasil Dihentikan.</b>", parse_mode=ParseMode.HTML)
    room = rooms.get(cid)
    if room and (uid == room['creator'] or is_owner(uid)): await finish_game(context, cid)

async def usir_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id; room = rooms.get(cid)
    if room and room['active']:
        if room['usir_limit'] <= 0: return await update.effective_message.reply_text("❌ Jatah /usir habis!", parse_mode=ParseMode.HTML)
        room['usir_limit'] -= 1
        p_id = room['players'][room['turn']]; p_name = room['player_names'].get(p_id, "Pemain")
        room['players'].pop(room['turn']); room['player_names'].pop(p_id, None)
        await update.effective_message.reply_text(f"👋 <b>{p_name}</b> diusir!", parse_mode=ParseMode.HTML)
        if len(room['players']) < 2: await finish_game(context, cid)
        else: room['turn'] %= len(room['players']); await next_turn_msg(context, cid)

async def ganti_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id; room = rooms.get(cid)
    if room and room['active'] and uid == room['players'][room['turn']]:
        if room['ganti_limit'].get(uid, 0) >= 1: return await update.effective_message.reply_text("❌ Limit ganti habis!")
        room['ganti_limit'][uid] = 1; room['suffix'] = random.choice("abcdefghijklmnopqrstuvwxyz")
        await update.effective_message.reply_text(f"🔄 HURUF BARU: <b>{room['suffix'].upper()}</b>", parse_mode=ParseMode.HTML)

# --- ADMIN COMMANDS ---
async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    status = get_setting('fsub_status'); btn_toggle = "🟢 ON" if status == "on" else "🔴 OFF"
    kb = [[InlineKeyboardButton(f"Fsub: {btn_toggle}", callback_data="set_toggle"), InlineKeyboardButton("🆔 Set ID", callback_data="set_id")],
          [InlineKeyboardButton("📝 Set Text", callback_data="set_msg"), InlineKeyboardButton("🔗 Set Link", callback_data="set_link")],
          [InlineKeyboardButton("🏷️ Set Nama", callback_data="set_btn"), InlineKeyboardButton("❌ Tutup", callback_data="set_close")]]
    await update.effective_message.reply_text("⚙️ <b>FSUB SETTINGS</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    kb = [[InlineKeyboardButton("✅ ACC (Reset)", callback_data="reset_acc"), InlineKeyboardButton("❌ Batal", callback_data="set_close")]]
    await update.effective_message.reply_text("⚠️ <b>RESET TOTAL TOP SCORE?</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    u = db_query("SELECT COUNT(*) FROM users", fetchone=True)[0]
    g = db_query("SELECT COUNT(*) FROM groups", fetchone=True)[0]
    await update.effective_message.reply_text(f"📊 <b>STATISTIK BOT</b>\nUser: {u}\nGrup: {g}", parse_mode=ParseMode.HTML)

async def edit_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    try:
        target = context.args[0].replace("@", ""); op = context.args[1]; val = int(context.args[2])
        if target.isdigit(): db_query(f"UPDATE users SET points = MAX(0, points {op} ?) WHERE id = ?", (val, int(target)), commit=True)
        else: db_query(f"UPDATE users SET points = MAX(0, points {op} ?) WHERE username = ?", (val, target), commit=True)
        await update.effective_message.reply_text(f"✅ Berhasil mengubah poin {target}!")
    except: 
        if update.effective_message: await update.effective_message.reply_text("Format: /e [ID/User] [+ / -] [Poin]")

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = db_query("SELECT username, points, max_tc FROM users ORDER BY points DESC LIMIT 10", fetchall=True)
    txt = "🏆 <b>TOP 10 GLOBAL PLAYERS</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(res): _, _, emo = get_level_info(r[2]); txt += f"{i+1}. {emo} {r[0]} — <code>{r[1]}</code> pts\n"
    kb = [[InlineKeyboardButton("📈 Score Saya", callback_data="my_score")]]
    await update.effective_message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    is_group = "bcgroup" in update.effective_message.text; msg = update.effective_message.reply_to_message; text_val = " ".join(context.args)
    if not msg and not text_val: return await update.effective_message.reply_text("❌ Pesan kosong!")
    targets = db_query(f"SELECT id FROM {'groups' if is_group else 'users'}", fetchall=True)
    s, f = 0, 0; st_msg = await update.effective_message.reply_text(f"🚀 Memulai Broadcast...")
    for t in targets:
        try:
            chat_info = await context.bot.get_chat(t[0])
            if chat_info.type == Chat.CHANNEL: continue
            if msg: await msg.copy(t[0])
            else: await context.bot.send_message(t[0], text_val, parse_mode=ParseMode.HTML)
            s += 1
        except: f += 1
        await asyncio.sleep(0.05)
    await st_msg.edit_text(f"✅ <b>Selesai!</b>\n🟢 Sukses: {s}\n🔴 Gagal: {f}")

# --- CALLBACK LOGIC ---
async def cb_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; data = q.data; cid = q.message.chat_id
    room = rooms.get(cid)
    
    if data == "donasi_qris":
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={QRIS_DATA}"
        try: await q.message.delete()
        except: pass
        kb = [[InlineKeyboardButton("🔙 Kembali", callback_data="donasi_back")]]
        await context.bot.send_photo(chat_id=cid, photo=qr_url, caption="Terimakasih untuk anda yang sudah berdonasi di bot Sambung-Kata ini.", reply_markup=InlineKeyboardMarkup(kb))
        return await q.answer()

    if data == "donasi_back":
        try: await q.message.delete()
        except: pass
        return await donasi_cmd(update, context)

    if data == "spin_back":
        text = "🏆 <b>Spinwells Event Ramadhan</b>"
        kb = [[InlineKeyboardButton("🎡 Spin", callback_data="spin_go")], [InlineKeyboardButton("✅ Cek Saldo", callback_data="spin_cek")], [InlineKeyboardButton("💰 Withdraw", callback_data="spin_wd")]]
        return await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    if data == "spin_cek":
        res = db_query("SELECT balance, spin_count, points FROM users WHERE id=?", (uid,), fetchone=True)
        bal, sc, pts = res if res else (0, 0, 0)
        txt = (f"<b>Cek Saldo Kamu:</b>\n💰 Balance: Rp{bal:,}\n🎡 Spin: {sc}×\n🪙 Poin: {pts:,}")
        kb = [[InlineKeyboardButton("🔙 Kembali", callback_data="spin_back")]]
        return await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    if data == "spin_go":
        res = db_query("SELECT points, spin_count FROM users WHERE id=?", (uid,), fetchone=True)
        pts, sc = res if res else (0, 0)
        if pts < 1000: return await q.answer("❌ Poin Top Global kurang! (Min 1.000)", show_alert=True)
        db_query("UPDATE users SET points = points - 1000, spin_count = spin_count + 1 WHERE id = ?", (uid,), commit=True)
        prices = [100, 200, 500, 1000, 5000, 10000, 20000, 50000, 100000]
        for i in range(1, 8):
            bar = "▒" * i + "░" * (8-i); rand_price = random.choice(prices)
            try: await q.edit_message_text(f"⚙️Spin [{bar}] Rp. {rand_price:,}", parse_mode=ParseMode.HTML)
            except: pass
            await asyncio.sleep(0.15)
        new_sc = sc + 1; rand = random.random() * 100; reward = 0
        if new_sc > 100 and rand < 0.1: reward = random.choice([20000, 50000, 80000, 100000])
        else:
            if rand < 40: reward = 0
            elif rand < 70: reward = random.choice([100, 200, 500])
            elif rand < 90: reward = random.choice([1000, 2000])
            else: reward = random.choice([5000, 10000])
        db_query("UPDATE users SET balance = balance + ? WHERE id = ?", (reward, uid), commit=True)
        res_txt = f"🎉 HASIL SPIN: <b>Rp{reward:,}</b>" if reward > 0 else "💨 HASIL SPIN: <b>Zonkk!</b>"
        kb = [[InlineKeyboardButton("🎡 Spin Lagi", callback_data="spin_go")], [InlineKeyboardButton("🔙 Kembali", callback_data="spin_back")]]
        return await q.edit_message_text(f"🏆 <b>Spinwells Event Ramadhan</b>\n\n{res_txt}", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    if data == "spin_wd":
        res = db_query("SELECT balance FROM users WHERE id=?", (uid,), fetchone=True)
        if (res[0] if res else 0) < 50000: return await q.answer(f"❌ Balance kurang! (Minimal Rp50.000).", show_alert=True)
        context.user_data['state'] = 'wd_input'
        wd_text = ("Kirimkan format withdraw untuk admin Transfer\nGunakan Bank Indonesia Agar Transfer Tidak Terkena Biaya Admin.\n\n"
                   "Format:\nNama Bank:\nNomor Rekening:\nNama Pemilik Rekening:\nTotal Withdraw:\n\n"
                   "Contoh:\nNama Bank: BRI\nNomor Rekening: 101112131414\nNama Pemilik Rekening: Akhmad syahroni\nTotal Withdraw: rp. 50.000\n\n"
                   "Isi format tersebut lalu kirimkan di bot Sambung-kata.")
        return await q.edit_message_text(wd_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Batal", callback_data="spin_back")]]), parse_mode=ParseMode.HTML)

    try:
        if data == "reset_acc": db_query("UPDATE users SET points = 0", commit=True); return await q.edit_message_text("✅ Reset Berhasil!")
        if data == "set_toggle": set_setting('fsub_status', "off" if get_setting('fsub_status') == "on" else "on"); return await q.message.delete()
        if data in ["set_id", "set_link", "set_msg", "set_btn"]:
            context.user_data['editing'] = {"set_id": "fsub_id", "set_link": "fsub_link", "set_msg": "fsub_msg", "set_btn": "fsub_btn"}[data]
            return await q.edit_message_text(f"📝 Kirim nilai baru untuk <b>{data}</b>.")
        if data == "set_close": return await q.message.delete()
        if data == "my_score":
            res = db_query("SELECT points, max_tc FROM users WHERE id=?", (uid,), fetchone=True); pts, mtc = res if res else (0,0); _, _, emo = get_level_info(mtc)
            return await q.edit_message_text(f"📈 <b>SCORE ANDA</b>\nLevel: {emo} ({mtc})\nPoin: {pts}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kembali", callback_data="back_top")]]), parse_mode=ParseMode.HTML)
        if data == "back_top":
            res = db_query("SELECT username, points, max_tc FROM users ORDER BY points DESC LIMIT 10", fetchall=True); txt = "🏆 <b>TOP 10 GLOBAL PLAYERS</b>\n"
            for i, r in enumerate(res): _, _, emo = get_level_info(r[2]); txt += f"{i+1}. {emo} {r[0]} — {r[1]} pts\n"
            return await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📈 Score Saya", callback_data="my_score")]]), parse_mode=ParseMode.HTML)
        if data == "join" and room and not room['active'] and uid not in room['players']:
            if not await check_fsub(uid, context): return await q.answer("Join channel dulu!", show_alert=True)
            room['players'].append(uid); room['player_names'][uid] = q.from_user.first_name; room['mistakes'][uid] = 0; plist = "\n".join([f"{i+1}. {room['player_names'][p]}" for i,p in enumerate(room['players'])])
            return await q.edit_message_text(f"🎮 <b>ROOM DIBUKA</b>\n\n<b>Pemain:</b>\n{plist}", reply_markup=q.message.reply_markup, parse_mode=ParseMode.HTML)
        if data == "leave" and room and not room['active'] and uid in room['players']:
            room['players'].remove(uid); room['player_names'].pop(uid, None); plist = "\n".join([f"{i+1}. {room['player_names'][p]}" for i,p in enumerate(room['players'])]) or "(Kosong)"
            return await q.edit_message_text(f"🎮 <b>ROOM DIBUKA</b>\n\n<b>Pemain:</b>\n{plist}", reply_markup=q.message.reply_markup, parse_mode=ParseMode.HTML)
        if data == "play" and room:
            if uid != room['creator']: return await q.answer("Hanya Leader!", show_alert=True)
            if len(room['players']) < 2: return await q.answer("Min 2 pemain!", show_alert=True)
            room['active'] = True; room['suffix'] = random.choice("abcdefghijklmnopqrstuvwxyz"); await q.message.delete(); await next_turn_msg(context, cid)
    except: pass

# --- HANDLERS ---
async def handle_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_obj = update.effective_message
    if not msg_obj: return
    u = update.effective_user; cid = update.effective_chat.id; room = rooms.get(cid)
    
    if is_owner(u.id) and msg_obj.reply_to_message:
        reply = msg_obj.reply_to_message; msg_text = reply.text or reply.caption or ""
        if "WD_ID:" in msg_text:
            try:
                target_uid = int(msg_text.split("WD_ID:")[1].split("\n")[0].strip())
                await context.bot.copy_message(chat_id=target_uid, from_chat_id=cid, message_id=msg_obj.message_id)
                return await msg_obj.reply_text("✅ Bukti/Balasan berhasil dikirim ke user.")
            except: pass

    if context.user_data.get('state') == 'wd_input':
        # --- LOGIKA PENARIKAN SALDO YANG DINAMIS ---
        text_input = msg_obj.text or ""
        
        # Ekstrak angka dari teks input (khusus baris Total Withdraw)
        requested_amount = 0
        match = re.search(r"Total Withdraw:\D*(\d+[\d\.]*)", text_input, re.IGNORECASE)
        if match:
            # Hilangkan titik (format ribuan) dan ubah ke integer
            raw_amount = match.group(1).replace(".", "")
            if raw_amount.isdigit(): requested_amount = int(raw_amount)
        
        # Cek saldo user di database
        res = db_query("SELECT balance FROM users WHERE id=?", (u.id,), fetchone=True)
        current_balance = res[0] if res else 0
        
        if requested_amount < 50000:
            return await msg_obj.reply_text("❌ <b>GAGAL:</b> Minimal penarikan adalah Rp50.000!")
        
        if requested_amount > current_balance:
            return await msg_obj.reply_text(f"❌ <b>GAGAL:</b> Saldo Anda tidak cukup!\nSaldo Anda: Rp{current_balance:,}\nPermintaan: Rp{requested_amount:,}")
        
        # Potong saldo sesuai permintaan, bukan semuanya!
        db_query("UPDATE users SET balance = balance - ? WHERE id = ?", (requested_amount, u.id), commit=True)
        
        report = (f"💰 <b>PENGAJUAN WITHDRAW</b>\nUser: {u.mention_html()}\nWD_ID: {u.id}\n"
                  f"Saldo Awal: Rp{current_balance:,}\n"
                  f"Ditarik: Rp{requested_amount:,}\n"
                  f"Sisa Saldo: Rp{current_balance - requested_amount:,}\n\n"
                  f"Data:\n{text_input}")
                  
        await context.bot.send_message(OWNER_ID, report, parse_mode=ParseMode.HTML)
        context.user_data.clear()
        return await msg_obj.reply_text(f"✅ <b>Berhasil!</b>\nPenarikan Rp{requested_amount:,} telah diajukan kepada Owner.\nMohon tunggu dalam waktu 1×24 jam.")

    if 'editing' in context.user_data and is_owner(u.id):
        set_setting(context.user_data['editing'], msg_obj.text); context.user_data.clear(); return await msg_obj.reply_text("✅ Disimpan!")

    if update.effective_chat.type == Chat.PRIVATE and u.id in SOLO_ROOMS:
        if not msg_obj.text: return
        solo = SOLO_ROOMS[u.id]; word = msg_obj.text.strip().lower(); _, min_l_solo, _ = get_level_info(solo['turn_count'])
        if word in solo['used_words'] and datetime.now() < solo['used_words'][word]: return await msg_obj.reply_text("❌ Dipakai!")
        if word in BANNED_NAMES or word not in dictionary or not word.startswith(solo['suffix']) or len(word) < min_l_solo:
            update_points(u.id, u.first_name, -1, solo['turn_count']); return await msg_obj.reply_text("❌ SALAH!")
        solo['used_words'][word] = datetime.now() + timedelta(minutes=30); s_len = 3 if len(word) >= 5 else 2; solo['suffix'] = word[-s_len:]; solo['turn_count'] += 1; update_points(u.id, u.first_name, 1, solo['turn_count'])
        return await msg_obj.reply_text(f"✅ BENAR!\nSambung: <b>{solo['suffix'].upper()}</b>", parse_mode=ParseMode.HTML)

    if not room or not room['active']: return
    if u.id != room['players'][room['turn']]: return
    if not msg_obj.reply_to_message or msg_obj.reply_to_message.from_user.id != context.bot.id: return
    if not msg_obj.text: return
    word = msg_obj.text.strip().lower(); tc = room['turn_count']; lvl_name, min_l, lvl_emo = get_level_info(tc)
    
    if word in room['used_words'] and datetime.now() < room['used_words'][word]: return await msg_obj.reply_text("❌ Sudah dipakai!")
    
    if word in BANNED_NAMES or len(word) < min_l or word not in dictionary or (room['suffix'] and not word.startswith(room['suffix'])):
        update_points(u.id, u.first_name, -5, tc)
        room['mistakes'][u.id] = room['mistakes'].get(u.id, 0) + 1
        if room['mistakes'][u.id] >= 3:
            await msg_obj.reply_text(f"💀 {u.first_name} tereliminasi!"); room['players'].pop(room['turn'])
            if len(room['players']) < 2: return await finish_game(context, cid)
            room['turn'] %= len(room['players'])
        else: await msg_obj.reply_text("❌ JAWABAN SALAH! (-5 Poin)"); room['turn'] = (room['turn'] + 1) % len(room['players'])
        return await next_turn_msg(context, cid)
    
    room['used_words'][word] = datetime.now() + timedelta(minutes=30); s_len = 3 if len(word) >= 5 else 2; room['suffix'] = word[-s_len:]; room['turn_count'] += 1; room['turn'] = (room['turn'] + 1) % len(room['players']); update_points(u.id, u.first_name, 10, room['turn_count'])
    await msg_obj.reply_text(f"✅ BENAR! +10 Poin."); await next_turn_msg(context, cid)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("peraturan", peraturan_command))
    app.add_handler(CommandHandler("donasi", donasi_cmd))
    app.add_handler(CommandHandler("spin", spin_cmd))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("mulai", mulai_cmd))
    app.add_handler(CommandHandler("gabung", gabung_cmd))
    app.add_handler(CommandHandler("keluar", keluar_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("usir", usir_cmd))
    app.add_handler(CommandHandler("ganti", ganti_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("e", edit_point))
    app.add_handler(CommandHandler("bcuser", broadcast_cmd))
    app.add_handler(CommandHandler("bcgroup", broadcast_cmd))
    app.add_handler(CallbackQueryHandler(cb_logic))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL | filters.Sticker.ALL, handle_all))
    app.add_handler(ChatMemberHandler(track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_error_handler(error_handler)
    print(">>> BOT PROFESSIONAL ONLINE <<<"); app.run_polling()

if __name__ == '__main__':
    main()
