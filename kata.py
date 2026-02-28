import os
import logging
import sqlite3
import random
import asyncio
import traceback
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
    # Tambahkan kolom max_tc untuk menyimpan rekor level tertinggi user
    db_query('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, points INTEGER DEFAULT 0, max_tc INTEGER DEFAULT 0)''', commit=True)
    db_query('''CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY, title TEXT)''', commit=True)
    db_query('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''', commit=True)
    
    # Update tabel lama jika kolom max_tc belum ada
    try:
        db_query("ALTER TABLE users ADD COLUMN max_tc INTEGER DEFAULT 0", commit=True)
    except:
        pass

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

# --- LOGIKA LEVEL DINAMIS ---
def get_level_info(tc):
    """Mengembalikan (Nama Level, Minimal Huruf, Emoji)"""
    if tc <= 20: return "Easy", 3, "🟢"
    elif tc <= 40: return "Medium", 4, "🟡"
    elif tc <= 60: return "Hard", 5, "🔴"
    elif tc <= 80: return "Harapan 3", 6, "🥉"
    elif tc <= 100: return "Harapan 2", 7, "🥈"
    elif tc <= 120: return "Jawara Harapan", 8, "🥇"
    elif tc <= 140: return "Legend Kata", 9, "🏆"
    else: return "WNI (Warga Negara Indonesia)", 10, "🏅"

# --- UTILS & GRUP LOGS PINTAR ---
def is_owner(user_id): return user_id == OWNER_ID

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    log_msg = (f"⚠️ <b>DETEKSI ERROR SISTEM</b>\n\n"
               f"<b>Error:</b> <code>{context.error}</code>\n\n"
               f"<b>Traceback:</b>\n<code>{tb_string[-2000:]}</code>")
    try: await context.bot.send_message(LOG_GROUP_ID, log_msg, parse_mode=ParseMode.HTML)
    except: pass

async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = update.my_chat_member
    if res.chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        if res.new_chat_member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]:
            db_query("INSERT OR IGNORE INTO groups (id, title) VALUES (?, ?)", (res.chat.id, res.chat.title), commit=True)
            log_txt = (f"📥 <b>BOT MASUK GRUP BARU</b>\n\n"
                       f"<b>Grup:</b> {res.chat.title}\n"
                       f"<b>ID:</b> <code>{res.chat.id}</code>\n"
                       f"<b>Oleh:</b> {update.effective_user.full_name}")
            try: await context.bot.send_message(LOG_GROUP_ID, log_txt, parse_mode=ParseMode.HTML)
            except: pass

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
        except: return False
    return True

async def send_fsub_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mention = update.effective_user.mention_html()
    text = get_setting('fsub_msg').replace("{mention}", mention)
    kb = [[InlineKeyboardButton(get_setting('fsub_btn'), url=get_setting('fsub_link'))],
          [InlineKeyboardButton("✅ Saya Sudah Join", url=f"https://t.me/{context.bot.username}?start=mulai")]]
    try: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    except: pass

def update_points(user_id, username, amount, tc_reached=0):
    un = username.replace("@", "") if username else "Player"
    db_query("INSERT OR IGNORE INTO users (id, username, points, max_tc) VALUES (?, ?, 0, 0)", (user_id, un), commit=True)
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
        p_id = room['players'][room['turn']]
        p_name = room['player_names'].get(p_id, "Pemain")
        try: await context.bot.send_message(cid, f"⏰ <b>Waktu Habis!</b>\n{p_name} dilewati karena tidak menjawab dalam 45 detik!", parse_mode=ParseMode.HTML)
        except: pass
        room['turn'] = (room['turn'] + 1) % len(room['players'])
        await next_turn_msg(context, cid)

async def next_turn_msg(context, cid):
    if cid not in rooms: return
    room = rooms[cid]
    next_p = room['players'][room['turn']]
    mention = f"<a href='tg://user?id={next_p}'>{room['player_names'][next_p]}</a>"
    suffix = room['suffix']
    
    # Ambil info level saat ini
    lvl_name, min_h, lvl_emo = get_level_info(room['turn_count'])
    
    try:
        await context.bot.send_message(
            cid, 
            f"📊 Level: {lvl_emo} <b>{lvl_name}</b> (Min {min_h} Huruf)\n"
            f"🔄 Giliran: {mention}\n"
            f"Sambung kata dari: <b>{suffix.upper()}</b>\n"
            f"⏱ Waktu: 45 Detik!", 
            parse_mode=ParseMode.HTML
        )
    except: pass
    if context.job_queue:
        for j in context.job_queue.get_jobs_by_name(f"timer_{cid}"): j.schedule_removal()
        context.job_queue.run_once(timeout_handler, 45, chat_id=cid, name=f"timer_{cid}")

# --- COMMAND HANDLERS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if update.effective_chat.type == Chat.PRIVATE:
        update_points(uid, update.effective_user.first_name, 0)
    if not await check_fsub(uid, context): return await send_fsub_msg(update, context)
    
    text = (" 👋 Hallo, ayok kita main sambung kata!\n\n"
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
            "• /withdraw - Tukar poin menjadi saldo\n"
            "• /peraturan - Aturan & tingkatan level\n"
            "• /help - Panduan lengkap bot\n\n"
            "⚠️𝖣𝗂𝖽𝗎𝗄𝗎𝗇𝗀 𝖮𝗅𝖾𝗁: <a href='https://t.me/drakwebot'>𝖣𝗋𝖺𝗄𝗐𝖾𝖻 𝖦𝖺𝗆𝖾</a>")
    
    kb = [[InlineKeyboardButton("➕ MASUKKAN KE GRUP", url=f"https://t.me/{context.bot.username}?startgroup=start")],
          [InlineKeyboardButton("👨‍💻 Developer", url=f"tg://user?id={OWNER_ID}"), InlineKeyboardButton("⚡ Support", url="https://t.me/bungkata")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML, disable_web_page_preview=True)

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
            "💰 <b>HADIAH (WITHDRAW):</b>\n"
            "Kumpulkan poin global. Poin dapat ditukar dengan saldo jika sudah mencapai 500 poin di perintah /withdraw.\n\n"
            "🎁 <b>DONASI:</b>\n"
            "Jika kamu menyukai bot ini dan ingin memberikan donasi kepada Developer (Dev.TJ) Sambung-Kata kamu bisa mengirimkan nya ke nomor Gopay yang tersedia!\n\n"
            "<b>Gopay:</b> <code>089678824963</code> a/n TJ\n\n"
            "🛠 <b>SUPPORT:</b> Hubungi @bungkata")
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

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
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def withdraw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    res = db_query("SELECT points FROM users WHERE id=?", (uid,), fetchone=True)
    points = res[0] if res else 0
    if points < 500:
        await update.message.reply_text(f"❌ <b>POIN TIDAK CUKUP!</b>\n\nPoin Anda: <code>{points}</code>\nMinimal penukaran: <b>500 Poin</b>.", parse_mode=ParseMode.HTML)
    else:
        update_points(uid, update.effective_user.first_name, -500)
        text = "💰 <b>Withdraw Tukar Poin Menjadi Saldo</b>\n500 Poin telah dipotong dari saldo Anda."
        kb = [[InlineKeyboardButton("💳 Pilih ATM", url="https://withdrawbot.xo.je/index.php")], [InlineKeyboardButton("🎟️ Ambil Vocer", url=f"tg://user?id={OWNER_ID}")]]
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def gabung_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id; room = rooms.get(cid)
    if not room: return await update.message.reply_text("❌ Tidak ada pendaftaran aktif.")
    if uid in room['players']: return await update.message.reply_text("❌ Anda sudah masuk pendaftaran.")
    if not await check_fsub(uid, context): return await send_fsub_msg(update, context)
    room['players'].append(uid); room['player_names'][uid] = update.effective_user.first_name; room['mistakes'][uid] = 0
    await update.message.reply_text(f"✅ <b>{update.effective_user.first_name}</b> masuk ke arena!", parse_mode=ParseMode.HTML)

async def keluar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id
    if update.effective_chat.type == Chat.PRIVATE:
        if uid in SOLO_ROOMS: SOLO_ROOMS.pop(uid); return await update.message.reply_text("🛑 <b>Game Solo Dihentikan.</b>", parse_mode=ParseMode.HTML)
        return
    room = rooms.get(cid)
    if not room or uid not in room['players']: return
    idx = room['players'].index(uid); is_turn = (room['active'] and room['turn'] == idx)
    room['players'].pop(idx); room['player_names'].pop(uid, None); room['mistakes'].pop(uid, None)
    await update.message.reply_text(f"🏃 <b>{update.effective_user.first_name}</b> keluar.", parse_mode=ParseMode.HTML)
    if len(room['players']) < 2: await finish_game(context, cid)
    elif room['active'] and is_turn: room['turn'] %= len(room['players']); await next_turn_msg(context, cid)

async def mulai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id
    if update.effective_chat.type == Chat.PRIVATE:
        if uid in SOLO_ROOMS: return await update.message.reply_text("❌ Game Solo sedang berjalan!", parse_mode=ParseMode.HTML)
        start_char = random.choice("abcdefghijklmnopqrstuvwxyz")
        SOLO_ROOMS[uid] = {'suffix': start_char, 'used_words': {}, 'turn_count': 0}
        await update.message.reply_text(f"🎮 <b>SOLO MODE: AKTIF</b>\n\nSambung kata dari: <b>{start_char.upper()}</b>\n\n<i>(Kirim jawaban langsung)</i>", parse_mode=ParseMode.HTML)
        return
    if cid in rooms: return await update.message.reply_text("❌ Game sudah berjalan!", parse_mode=ParseMode.HTML)
    rooms[cid] = {'creator': uid, 'players': [uid], 'player_names': {uid: update.effective_user.first_name}, 'active': False, 'suffix': '', 'turn': 0, 'turn_count': 0, 'used_words': {}, 'mistakes': {}, 'ganti_limit': {}, 'usir_limit': 1}
    kb = [[InlineKeyboardButton("🚪 Gabung", callback_data="join"), InlineKeyboardButton("🏃 Keluar", callback_data="leave")], [InlineKeyboardButton("▶️ Play", callback_data="play")]]
    await update.message.reply_text(f"🎮 <b>ROOM DIBUKA</b>\n\n<b>Pemain:</b>\n1. {update.effective_user.first_name}", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id; uid = update.effective_user.id
    if update.effective_chat.type == Chat.PRIVATE:
        if uid in SOLO_ROOMS: SOLO_ROOMS.pop(uid); return await update.message.reply_text("🏁 <b>Game Solo Berhasil Dihentikan.</b>", parse_mode=ParseMode.HTML)
    room = rooms.get(cid)
    if room and (uid == room['creator'] or is_owner(uid)): await finish_game(context, cid)

async def usir_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id; room = rooms.get(cid)
    if room and room['active']:
        if room['usir_limit'] <= 0:
            return await update.message.reply_text("❌ Jatah /usir sudah habis untuk permainan ini!", parse_mode=ParseMode.HTML)
        
        room['usir_limit'] -= 1
        p_id = room['players'][room['turn']]; p_name = room['player_names'].get(p_id, "Pemain")
        room['players'].pop(room['turn'])
        room['player_names'].pop(p_id, None)
        await update.message.reply_text(f"👋 <b>{p_name}</b> diusir dari permainan!", parse_mode=ParseMode.HTML)
        if len(room['players']) < 2: await finish_game(context, cid)
        else: room['turn'] %= len(room['players']); await next_turn_msg(context, cid)

async def ganti_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id; room = rooms.get(cid)
    if room and room['active'] and uid == room['players'][room['turn']]:
        if room['ganti_limit'].get(uid, 0) >= 1: 
            return await update.message.reply_text("❌ Kamu sudah menggunakan fitur /ganti dalam permainan ini!", parse_mode=ParseMode.HTML)
        
        room['ganti_limit'][uid] = 1; room['suffix'] = random.choice("abcdefghijklmnopqrstuvwxyz")
        await update.message.reply_text(f"🔄 HURUF BARU: <b>{room['suffix'].upper()}</b>", parse_mode=ParseMode.HTML)

# --- ADMIN COMMANDS ---
async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    status = get_setting('fsub_status')
    btn_toggle = "🟢 ON" if status == "on" else "🔴 OFF"
    text = "⚙️ <b>FSUB SETTINGS MENU</b>\nAtur konfigurasi join wajib di bawah ini:"
    kb = [[InlineKeyboardButton(f"Fsub: {btn_toggle}", callback_data="set_toggle"), InlineKeyboardButton("🆔 Set ID", callback_data="set_id")],
          [InlineKeyboardButton("📝 Set Text", callback_data="set_msg"), InlineKeyboardButton("🔗 Set Link", callback_data="set_link")],
          [InlineKeyboardButton("🏷️ Set Nama", callback_data="set_btn"), InlineKeyboardButton("❌ Tutup", callback_data="set_close")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    text = "⚠️ <b>KONFIRMASI RESET TOTAL TOP SCORE?</b>\nApakah Anda yakin ingin menghapus semua poin pemain ke 0?"
    kb = [[InlineKeyboardButton("✅ ACC (Reset)", callback_data="reset_acc"), InlineKeyboardButton("❌ Reject (Batal)", callback_data="set_close")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    u = db_query("SELECT COUNT(*) FROM users", fetchone=True)[0]
    g = db_query("SELECT COUNT(*) FROM groups", fetchone=True)[0]
    await update.message.reply_text(f"📊 <b>STATISTIK BOT</b>\nUser: {u}\nGrup: {g}", parse_mode=ParseMode.HTML)

async def edit_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    try:
        target = context.args[0].replace("@", "")
        op = context.args[1]
        val = int(context.args[2])
        if target.isdigit():
            db_query(f"UPDATE users SET points = MAX(0, points {op} ?) WHERE id = ?", (val, int(target)), commit=True)
        else:
            db_query(f"UPDATE users SET points = MAX(0, points {op} ?) WHERE username = ?", (val, target), commit=True)
        await update.message.reply_text(f"✅ Berhasil mengubah poin {target}!")
    except:
        await update.message.reply_text("Format: /e [ID/User] [+ / -] [Poin]")

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = db_query("SELECT username, points, max_tc FROM users ORDER BY points DESC LIMIT 10", fetchall=True)
    txt = "🏆 <b>TOP 10 GLOBAL PLAYERS</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, r in enumerate(res): 
        # Ambil emoji berdasarkan rekor max_tc user tersebut
        _, _, emo = get_level_info(r[2])
        txt += f"{i+1}. {emo} {r[0]} — <code>{r[1]}</code> pts\n"
    kb = [[InlineKeyboardButton("📈 Score Saya", callback_data="my_score")]]
    await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

# --- BROADCAST PINTAR ---
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    is_group = "bcgroup" in update.message.text
    msg = update.message.reply_to_message
    text_val = " ".join(context.args)
    if not msg and not text_val: return await update.message.reply_text("❌ <b>GAGAL:</b> Tulis pesan atau reply untuk broadcast!")
    targets = db_query(f"SELECT id FROM {'groups' if is_group else 'users'}", fetchall=True)
    s, f = 0, 0
    st_msg = await update.message.reply_text(f"🚀 Broadcast ke {len(targets)} target...")
    for i, t in enumerate(targets):
        try:
            if is_group:
                try:
                    chat = await context.bot.get_chat(t[0])
                    if chat.type == Chat.CHANNEL: continue 
                except: pass
            
            if msg: await msg.copy(t[0])
            else: await context.bot.send_message(t[0], text_val, parse_mode=ParseMode.HTML)
            s += 1
        except: f += 1
        if (i+1) % 20 == 0: 
            try: await st_msg.edit_text(f"⏳ <b>Progres:</b> {s} Sukses, {f} Gagal.")
            except: pass
        await asyncio.sleep(0.05)
    await st_msg.edit_text(f"✅ <b>BROADCAST SELESAI!</b>\n\n🟢 Sukses: {s}\n🔴 Gagal: {f}", parse_mode=ParseMode.HTML)

# --- CALLBACK LOGIC ---
async def cb_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; data = q.data; cid = q.message.chat_id
    room = rooms.get(cid)
    
    if data == "reset_acc":
        db_query("UPDATE users SET points = 0", commit=True)
        return await q.edit_message_text("✅ <b>RESET BERHASIL!</b> Seluruh poin Top Global dikembalikan ke 0.")
    if data == "set_toggle":
        set_setting('fsub_status', "off" if get_setting('fsub_status') == "on" else "on")
        return await q.message.delete()
    if data in ["set_id", "set_link", "set_msg", "set_btn"]:
        context.user_data['editing'] = {"set_id": "fsub_id", "set_link": "fsub_link", "set_msg": "fsub_msg", "set_btn": "fsub_btn"}[data]
        return await q.edit_message_text(f"📝 Kirim nilai baru untuk <b>{data}</b>.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Batal", callback_data="back_settings")]]), parse_mode=ParseMode.HTML)
    if data == "back_settings": context.user_data.clear(); return await q.message.delete()
    if data == "set_close": return await q.message.delete()
    
    if data == "my_score":
        res = db_query("SELECT points, max_tc FROM users WHERE id=?", (uid,), fetchone=True)
        pts = res[0] if res else 0
        mtc = res[1] if res else 0
        _, _, emo = get_level_info(mtc)
        txt = (f"📈 <b>SCORE PERSONAL ANDA</b>\n━━━━━━━━━━━━━━━━━━━━\n"
               f"Nama: {q.from_user.first_name}\n"
               f"Level Record: {emo} (Q-{mtc})\n"
               f"Total Poin: <code>{pts}</code>\n\n"
               f"<i>Gunakan menu ini untuk melihat score yang tidak tercatat di Top 10.</i>")
        return await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kembali ke Top 10", callback_data="back_top")]]), parse_mode=ParseMode.HTML)
    if data == "back_top":
        res = db_query("SELECT username, points, max_tc FROM users ORDER BY points DESC LIMIT 10", fetchall=True)
        txt = "🏆 <b>TOP 10 GLOBAL PLAYERS</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        for i, r in enumerate(res): 
            _, _, emo = get_level_info(r[2])
            txt += f"{i+1}. {emo} {r[0]} — <code>{r[1]}</code> pts\n"
        return await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📈 Score Saya", callback_data="my_score")]]), parse_mode=ParseMode.HTML)
    
    if data == "join" and room and not room['active'] and uid not in room['players']:
        if not await check_fsub(uid, context): return await q.answer("Join channel dulu!", show_alert=True)
        room['players'].append(uid); room['player_names'][uid] = q.from_user.first_name; room['mistakes'][uid] = 0
        plist = "\n".join([f"{i+1}. {room['player_names'][p]}" for i,p in enumerate(room['players'])])
        await q.edit_message_text(f"🎮 <b>ROOM DIBUKA</b>\n\n<b>Pemain:</b>\n{plist}", reply_markup=q.message.reply_markup, parse_mode=ParseMode.HTML)
    if data == "leave" and room and not room['active'] and uid in room['players']:
        room['players'].remove(uid); room['player_names'].pop(uid, None); room['mistakes'].pop(uid, None)
        plist = "\n".join([f"{i+1}. {room['player_names'][p]}" for i,p in enumerate(room['players'])]) or "(Kosong)"
        await q.edit_message_text(f"🎮 <b>ROOM DIBUKA</b>\n\n<b>Pemain:</b>\n{plist}", reply_markup=q.message.reply_markup, parse_mode=ParseMode.HTML)
    if data == "play" and room:
        if uid != room['creator']: return await q.answer("❌ Hanya Leader yang bisa memulai permainan!", show_alert=True)
        if len(room['players']) < 2: return await q.answer("Minimal 2 pemain!", show_alert=True)
        room['active'] = True; room['suffix'] = random.choice("abcdefghijklmnopqrstuvwxyz"); await q.message.delete(); await next_turn_msg(context, cid)

# --- GAME LOGIC ---
async def handle_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    u = update.effective_user; cid = update.effective_chat.id; room = rooms.get(cid)
    
    # Input Admin untuk Settings
    if 'editing' in context.user_data and is_owner(u.id):
        if not update.message.text: return
        set_setting(context.user_data['editing'], update.message.text); context.user_data.clear()
        return await update.message.reply_text("✅ Berhasil disimpan! Gunakan /settings untuk melihat.", parse_mode=ParseMode.HTML)

    # SOLO MODE LOGIC
    if update.effective_chat.type == Chat.PRIVATE and u.id in SOLO_ROOMS:
        if not update.message.text: return
        solo = SOLO_ROOMS[u.id]; word = update.message.text.strip().lower()
        
        # Cek Min Huruf Solo
        _, min_l_solo, _ = get_level_info(solo['turn_count'])
        
        if word in solo['used_words'] and datetime.now() < solo['used_words'][word]:
            return await update.message.reply_text("❌ Kata ini sudah digunakan! (Limit 30m)", parse_mode=ParseMode.HTML)
        if word in BANNED_NAMES or word not in dictionary or not word.startswith(solo['suffix']) or len(word) < min_l_solo:
            update_points(u.id, u.first_name, -1, solo['turn_count']); return await update.message.reply_text(f"❌ Salah! Min {min_l_solo} huruf. -1 Poin", parse_mode=ParseMode.HTML)
        
        solo['used_words'][word] = datetime.now() + timedelta(minutes=30)
        
        # Logika Suffix Dinamis
        if len(word) == 6: s_len = 2
        elif len(word) == 7: s_len = 3
        elif len(word) == 10: s_len = 4
        else: s_len = 3 if len(word) >= 5 else 2
        
        solo['suffix'] = word[-s_len:]; solo['turn_count'] += 1
        update_points(u.id, u.first_name, 1, solo['turn_count'])
        return await update.message.reply_text(f"✅ Benar! Sambung: <b>{solo['suffix'].upper()}</b>", parse_mode=ParseMode.HTML)

    # GROUP MODE LOGIC
    if not room or not room['active'] or u.id != room['players'][room['turn']]: return
    if not update.message.reply_to_message or update.message.reply_to_message.from_user.id != context.bot.id: return
    if not update.message.text: return
    
    word = update.message.text.strip().lower(); tc = room['turn_count']
    if word in room['used_words'] and datetime.now() < room['used_words'][word]:
        return await update.message.reply_text("❌ Kata ini sudah digunakan di grup ini! (Limit 30m)", parse_mode=ParseMode.HTML)

    # Get Level Info
    lvl_name, min_l, lvl_emo = get_level_info(tc)

    # LOGIKA SALAH: Poin Berkurang & Lempar Giliran
    if word in BANNED_NAMES or len(word) < min_l or word not in dictionary or (room['suffix'] and not word.startswith(room['suffix'])):
        update_points(u.id, u.first_name, -5, tc)
        room['mistakes'][u.id] = room['mistakes'].get(u.id, 0) + 1
        
        err_msg = "❌ Jawaban Salah!"
        if word in BANNED_NAMES: err_msg = "❌ Larangan: Nama orang!"
        elif len(word) < min_l: err_msg = f"❌ Minimal {min_l} huruf untuk level {lvl_name}!"
        elif word not in dictionary: err_msg = "❌ Tidak ada di kamus!"
        elif not word.startswith(room['suffix']): err_msg = f"❌ Harus diawali '{room['suffix'].upper()}'!"

        if room['mistakes'][u.id] >= 3:
            await update.message.reply_text(f"💀 {u.first_name} tereliminasi! (Salah 3x)", parse_mode=ParseMode.HTML)
            room['players'].pop(room['turn'])
            if len(room['players']) < 2: return await finish_game(context, cid)
        else:
            await update.message.reply_text(f"{err_msg}\nPoin -5. Giliran dilempar!", parse_mode=ParseMode.HTML)
            room['turn'] = (room['turn'] + 1) % len(room['players'])
        
        return await next_turn_msg(context, cid)

    # SUCCESS LOGIC
    room['used_words'][word] = datetime.now() + timedelta(minutes=30)
    
    # Logika Suffix Dinamis
    if len(word) == 6: s_len = 2
    elif len(word) == 7: s_len = 3
    elif len(word) == 10: s_len = 4
    else: s_len = 3 if len(word) >= 5 else 2
    
    room['suffix'] = word[-s_len:]; room['turn_count'] += 1; room['turn'] = (room['turn'] + 1) % len(room['players'])
    update_points(u.id, u.first_name, 10, room['turn_count']); await next_turn_msg(context, cid)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("peraturan", peraturan_command))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("mulai", mulai_cmd))
    app.add_handler(CommandHandler("withdraw", withdraw_cmd))
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
    app.add_handler(ChatMemberHandler(track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_error_handler(error_handler)
    print(">>> BOT PROFESSIONAL ONLINE <<<"); app.run_polling()

if __name__ == '__main__': main()
