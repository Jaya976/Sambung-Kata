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
    ContextTypes
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

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('bungkata.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, points INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY, title TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('fsub_id', '-1002856616933')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('fsub_link', 'https://t.me/addlist/Ld2g4xk8AAwyOTg1')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('fsub_btn', '🚪 Join Channel')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('fsub_status', 'off')")
    conn.commit()
    conn.close()

init_db()

def get_setting(key):
    conn = sqlite3.connect('bungkata.db'); c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    res = c.fetchone(); conn.close()
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
    text = "AKSES TERBATAS\n\nUntuk menggunakan fitur bot dan bermain di grup, Anda wajib bergabung ke Channel kami melalui link di bawah!"
    kb = [[InlineKeyboardButton(get_setting('fsub_btn'), url=get_setting('fsub_link'))], [InlineKeyboardButton("Saya Sudah Join", callback_data="check_fsub_again")]]
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=InlineKeyboardMarkup(kb))

def get_user_points(user_id):
    conn = sqlite3.connect('bungkata.db'); c = conn.cursor()
    c.execute("SELECT points FROM users WHERE id=?", (user_id,))
    res = c.fetchone(); conn.close()
    return res[0] if res else 0

def update_points(user_id, username, amount):
    conn = sqlite3.connect('bungkata.db'); c = conn.cursor()
    un = username.replace("@", "") if username else "Player"
    c.execute("INSERT OR IGNORE INTO users (id, username, points) VALUES (?, ?, 0)", (user_id, un))
    c.execute("UPDATE users SET points = MAX(0, points + ?), username = ? WHERE id = ?", (amount, un, user_id))
    conn.commit(); conn.close()

# --- GAME ENGINE ---
async def finish_game(context, cid):
    if cid not in rooms: return
    room = rooms[cid]
    if room.get('is_tournament'):
        sorted_scores = sorted(room['t_scores'].items(), key=lambda x: x[1], reverse=True)
        if sorted_scores:
            winner_id = sorted_scores[0][0]; prize = room.get('pool', 0)
            txt = "HASIL TURNAMEN SAMBUNG KATA\n━━━━━━━━━━━━━━━━━━━━\n"
            for i, (p_id, score) in enumerate(sorted_scores):
                txt += f"{i+1}. {room['player_names'].get(p_id, 'Pemain')} — {score} pts\n"
            update_points(winner_id, room['player_names'].get(winner_id), prize)
            txt += f"\nJuara 1: {room['player_names'].get(winner_id)}\nHadiah Taruhan: {prize} 💰"
            await context.bot.send_message(cid, txt + "\n🏁 Turnamen Selesai!")
    else:
        await context.bot.send_message(cid, "🏁 PERMAINAN BERAKHIR")
    rooms.pop(cid, None); used_words_global.pop(cid, None)
    for j in context.job_queue.get_jobs_by_name(f"timer_{cid}"): j.schedule_removal()

async def timeout_handler(context: ContextTypes.DEFAULT_TYPE):
    cid = context.job.chat_id
    if cid in rooms and rooms[cid]['active']:
        room = rooms[cid]; room['turn'] %= len(room['players'])
        p_name = room['player_names'].get(room['players'][room['turn']], "Pemain")
        room['players'].pop(room['turn'])
        await context.bot.send_message(cid, f"💀 GAME OVER!\n{p_name} dikeluarkan karena tidak absen/menjawab!")
        if len(room['players']) < 2: await finish_game(context, cid)
        else:
            room['turn'] %= len(room['players'])
            next_p = room['players'][room['turn']]
            hint = f"huruf: {room['last_word'][-1].upper()}" if room['last_word'] else "Bebas"
            await context.bot.send_message(cid, f"🔄 Giliran: {room['player_names'][next_p]}\nHint {hint}")
            schedule_timer(context, cid)

def schedule_timer(context, chat_id):
    for j in context.job_queue.get_jobs_by_name(f"timer_{chat_id}"): j.schedule_removal()
    context.job_queue.run_once(timeout_handler, 60, chat_id=chat_id, name=f"timer_{chat_id}")

# --- COMMANDS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == Chat.PRIVATE:
        update_points(update.effective_user.id, update.effective_user.first_name, 0)
    if not await check_fsub(update.effective_user.id, context): return await send_fsub_msg(update, context)
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
            "- /help - bantuan")
    kb = [[InlineKeyboardButton("➕ Masukkan Ke Grup", url=f"https://t.me/{context.bot.username}?startgroup=start")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("⚙️ BANTUAN\n━━━━━━━━━━━━━━\n"
            "• Bot Sambung Kata adalah bot yang menyambungkan kata dari kata awal yang diberi oleh bot lalu melanjutkan kata terakhir lawan.\n"
            "• Bot Sambung Kata dapat mengasah otak untuk mengetahui lebih dalam dari kamus KBBI.\n"
            "• Bot sambung kata dapat mengisi waktu luang kamu didalam aplikasi Telegram.")
    kb = [[InlineKeyboardButton("👨‍💻 Hubungi Pembuat", url=f"tg://user?id={OWNER_ID}")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def peraturan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("📖 PERATURAN\n━━━━━━━━━━━━━━━\n"
            "1. Waktu: 60 Detik.\n"
            "2. Minimal Huruf (Tingkatan Level):\n"
            "• 🟢 1-20 Easy: 2 Huruf\n"
            "• 🟡 21-40 Medium: 3 Huruf\n"
            "• 🔴 41-60 Hard: 4 Huruf\n"
            "• 🟣 61-80 Super Hard: 5 Huruf\n"
            "• 💎 81-100 Epic: 6 Huruf\n"
            "• 🏆 101-120 Master: 7 Huruf\n"
            "• 👑 121+ Grand Master: 8 Huruf\n\n"
            "3. Wajib Reply pesan bot\n"
            "4. Salah = -5 poin (Hanya mode /mulai).\n"
            "5. Pemenang Turnamen mendapatkan semua taruhan.")
    await update.message.reply_text(text)

async def gabung_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; cid = update.effective_chat.id; room = rooms.get(cid)
    if not room: return await update.message.reply_text("❌ Tidak ada room aktif.")
    if uid in room['players']: return await update.message.reply_text("❌ Kamu sudah bergabung.")
    
    if room['is_tournament']:
        stake_val = list(room['stakes'].values())[0] if room['stakes'] else 100
        if get_user_points(uid) < stake_val:
            return await update.message.reply_text(f"❌ Poin tidak cukup ({stake_val}💰).")
        update_points(uid, update.effective_user.first_name, -stake_val)
        room['pool'] += stake_val; room['stakes'][uid] = stake_val; room['t_scores'][uid] = 0
    
    room['players'].append(uid); room['player_names'][uid] = update.effective_user.first_name
    await update.message.reply_text(f"✅ {update.effective_user.first_name} bergabung ke dalam permainan!")

async def edit_point(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    try:
        target = context.args[0].replace("@", "")
        op = context.args[1] # + atau -
        val = int(context.args[2])
        conn = sqlite3.connect('bungkata.db'); c = conn.cursor()
        c.execute("SELECT id, username FROM users WHERE username=? OR id=?", (target, target))
        res = c.fetchone()
        if res:
            uid, uname = res
            c.execute(f"UPDATE users SET points = MAX(0, points {op} ?) WHERE id=?", (val, uid))
            conn.commit(); await update.message.reply_text(f"✅ Berhasil edit poin {uname} ({uid}) {op}{val}.")
        else: await update.message.reply_text("❌ User tidak ditemukan di database.")
        conn.close()
    except: await update.message.reply_text("Format: /e [username/id] [+ / -] [jumlah]")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    conn = sqlite3.connect('bungkata.db'); c = conn.cursor()
    u_count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    g_count = c.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
    conn.close()
    await update.message.reply_text(f"📊 STATISTIK BOT\n\nTotal User: {u_count}\nTotal Grup: {g_count}")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    is_group = "bcgroup" in update.message.text; args = context.args
    if not args and not update.message.reply_to_message: return await update.message.reply_text("Kirim pesan atau reply pesan.")
    conn = sqlite3.connect('bungkata.db'); c = conn.cursor()
    targets = c.execute("SELECT id FROM groups" if is_group else "SELECT id FROM users").fetchall(); conn.close()
    s, f = 0, 0
    for t in targets:
        try:
            if update.message.reply_to_message: await update.message.reply_to_message.copy(t[0])
            else: await context.bot.send_message(t[0], " ".join(args))
            s += 1; await asyncio.sleep(0.05)
        except: f += 1
    await update.message.reply_text(f"📢 Broadcast Selesai!\nSukses: {s} | Gagal: {f}")

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id): return
    args = context.args
    if not args:
        text = (f"⚙️ PENGATURAN FSUB\n\nStatus: {get_setting('fsub_status').upper()}\n"
                f"ID: {get_setting('fsub_id')}\nLink: {get_setting('fsub_link')}\nBtn: {get_setting('fsub_btn')}\n\n"
                "Gunakan: /settings [status/id/link/btn] [nilai]")
        return await update.message.reply_text(text)
    k, v = args[0].lower(), " ".join(args[1:])
    conn = sqlite3.connect('bungkata.db'); c = conn.cursor()
    if k in ["status", "id", "link", "btn"]:
        c.execute(f"UPDATE settings SET value=? WHERE key='fsub_{k}'", (v,))
        conn.commit(); await update.message.reply_text(f"✅ {k} berhasil diupdate!")
    conn.close()

# --- GAME LOGIC ---
async def handle_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; cid = update.effective_chat.id
    if update.effective_chat.type != Chat.PRIVATE:
        conn = sqlite3.connect('bungkata.db'); c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO groups (id, title) VALUES (?, ?)", (cid, update.effective_chat.title))
        conn.commit(); conn.close()
    
    if not update.message or not update.message.text or update.message.text.startswith('/') or cid not in rooms or not rooms[cid]['active']: return
    room = rooms[cid]; room['turn'] %= len(room['players'])
    
    if not update.message.reply_to_message or update.message.reply_to_message.from_user.id != context.bot.id: return
    if u.id != room['players'][room['turn']]: return
    
    word = update.message.text.strip().lower()
    room['turn_count'] += 1; tc = room['turn_count']
    
    if tc <= 20: min_l, lv = 2, "🟢 Easy"
    elif tc <= 40: min_l, lv = 3, "🟡 Medium"
    elif tc <= 60: min_l, lv = 4, "🔴 Hard"
    elif tc <= 80: min_l, lv = 5, "🟣 Super Hard"
    elif tc <= 100: min_l, lv = 6, "💎 Epic"
    elif tc <= 120: min_l, lv = 7, "🏆 Master"
    else: min_l, lv = 8, "👑 Grand Master"

    err = ""
    if word in BANNED_NAMES: err = "❌ Larangan: Nama manusia!"
    elif len(word) < min_l: err = f"❌ Minimal {min_l} huruf!"
    elif word not in dictionary: err = "❌ Tidak ada di kamus!"
    elif room['last_word'] and not word.startswith(room['last_word'][-1]): err = f"❌ Harus mulai huruf {room['last_word'][-1].upper()}!"
    
    if err:
        if not room['is_tournament']: update_points(u.id, u.first_name, -5)
        await update.message.reply_text(err)
        room['turn'] = (room['turn'] + 1) % len(room['players'])
        await update.message.reply_text(f"🔄 Giliran: {room['player_names'][room['players'][room['turn']]]}")
        schedule_timer(context, cid); return

    room['last_word'] = word; room['turn'] = (room['turn'] + 1) % len(room['players'])
    if room['is_tournament']: room['t_scores'][u.id] = room['t_scores'].get(u.id, 0) + 10
    else: update_points(u.id, u.first_name, 10)
    
    await update.message.reply_text(f"✅ BENAR!\nLv: {lv}\n🔄 Giliran: {room['player_names'][room['players'][room['turn']]]}\nLanjut: {word[-1].upper()}")
    schedule_timer(context, cid)

# --- MULAI LOGIC ---
async def mulai_cmd(update, context): await mulai_logic(update, context, False)
async def turnamen_cmd(update, context): await mulai_logic(update, context, True)

async def mulai_logic(u, c, is_t):
    if u.effective_chat.type == Chat.PRIVATE: return # Hanya bisa di grup
    cid = u.effective_chat.id
    if cid in rooms: return await u.message.reply_text("❌ Room aktif!")
    if not await check_fsub(u.effective_user.id, c): return await send_fsub_msg(u, c)
    
    rooms[cid] = {'creator': u.effective_user.id, 'players': [], 'player_names': {}, 'active': False, 'last_word': "", 'turn': 0, 'is_tournament': is_t, 't_scores': {}, 'pool': 0, 'stakes': {}, 'turn_count': 0, 'ganti_used': False}
    
    if is_t:
        kb = [[InlineKeyboardButton("100💰", callback_data="stake_100"), InlineKeyboardButton("500💰", callback_data="stake_500"), InlineKeyboardButton("1000💰", callback_data="stake_1000")], [InlineKeyboardButton("▶️MULAI SEKARANG🎮", callback_data="play")]]
        await u.message.reply_text("💰Turnamen Dibuka🎮\n\nPemain yang bergabung:", reply_markup=InlineKeyboardMarkup(kb))
    else:
        rooms[cid]['players'] = [u.effective_user.id]; rooms[cid]['player_names'][u.effective_user.id] = u.effective_user.first_name
        kb = [[InlineKeyboardButton("🚪 Gabung", callback_data="join"), InlineKeyboardButton("🏃 Keluar", callback_data="leave")], [InlineKeyboardButton("▶️ Play", callback_data="play")]]
        await u.message.reply_text(f"🎮 ROOM DIBUKA\n\nBersiap:\n1. {u.effective_user.first_name}", reply_markup=InlineKeyboardMarkup(kb))

async def cb_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; cid = q.message.chat_id; uid = q.from_user.id; room = rooms.get(cid)
    if q.data == "check_fsub_again":
        if await check_fsub(uid, context): await q.message.delete()
        else: await q.answer("Belum join!", show_alert=True)
    elif q.data.startswith("stake_"):
        if not room or room['active'] or uid in room['players']: return
        amt = int(q.data.split("_")[1])
        if get_user_points(uid) < amt: return await q.answer("Poin tidak cukup!", show_alert=True)
        update_points(uid, q.from_user.first_name, -amt); room['players'].append(uid); room['player_names'][uid] = q.from_user.first_name; room['pool'] += amt; room['stakes'][uid] = amt; room['t_scores'][uid] = 0
        plist = "\n".join([f"- bersiap {room['player_names'][p]} {room['stakes'][p]}💰" for p in room['players']])
        await q.edit_message_text(f"💰Turnamen Dibuka🎮\n\n{plist}", reply_markup=q.message.reply_markup)
    elif q.data == "join":
        if room and uid not in room['players']:
            room['players'].append(uid); room['player_names'][uid] = q.from_user.first_name
            plist = "\n".join([f"{i+1}. {room['player_names'][p]}" for i, p in enumerate(room['players'])])
            await q.edit_message_text(f"🎮 ROOM DIBUKA\n\nBersiap:\n{plist}", reply_markup=q.message.reply_markup)
    elif q.data == "play":
        if room and uid == room['creator'] and len(room['players']) >= 2:
            room['active'] = True; random.shuffle(room['players']); char = random.choice("abcdefghijklmnopqrstuvwxyz").upper(); room['last_word'] = char.lower()
            await q.edit_message_text(f"▶️ DIMULAI!\nGiliran: {room['player_names'][room['players'][0]]}\nHuruf: {char}"); schedule_timer(context, cid)

async def top_cmd(u, c):
    conn = sqlite3.connect('bungkata.db'); res = conn.cursor().execute("SELECT username, points FROM users ORDER BY points DESC LIMIT 10").fetchall(); conn.close()
    txt = "🏆 TOP 10 PEMAIN\n"
    for i, r in enumerate(res): txt += f"{i+1}. {r[0]} — {r[1]} pts\n"
    await u.message.reply_text(txt)

async def stop_game_cmd(u, c):
    room = rooms.get(u.effective_chat.id)
    if room:
        member = await c.bot.get_chat_member(u.effective_chat.id, u.effective_user.id)
        if is_owner(u.effective_user.id) or u.effective_user.id == room['creator'] or member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await finish_game(c, u.effective_chat.id)

async def usir_cmd(u, c):
    room = rooms.get(u.effective_chat.id)
    if room and room['active']:
        p_name = room['player_names'].get(room['players'][room['turn']], "Pemain")
        room['players'].pop(room['turn'])
        await u.message.reply_text(f"👋 {p_name} diusir dari permainan!")
        if len(room['players']) < 2: await finish_game(c, u.effective_chat.id)
        else: room['turn'] %= len(room['players']); schedule_timer(c, u.effective_chat.id)

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
        char = random.choice("abcdefghijklmnopqrstuvwxyz").upper(); room['last_word'] = char.lower(); room['ganti_used'] = True
        await u.message.reply_text(f"🔄 HURUF BARU: {char}")

async def withdraw_cmd(u, c):
    if u.effective_chat.type != Chat.PRIVATE: return
    args = c.args
    if len(args) < 3: return await u.message.reply_text("💰 Format: /withdraw [pts] [metode] [nomor]")
    try:
        pts = int(args[0]); curr = get_user_points(u.effective_user.id)
        if pts < MIN_WITHDRAW or curr < pts: return await u.message.reply_text("❌ Poin tidak cukup.")
        update_points(u.effective_user.id, u.effective_user.first_name, -pts)
        await c.bot.send_message(OWNER_ID, f"💰 WD REQUEST\nUser: {u.effective_user.first_name}\nID: {u.effective_user.id}\nJumlah: {pts}\nMetode: {args[1]}\nNomor: {' '.join(args[2:])}")
        await u.message.reply_text("✅ Permintaan dikirim!")
    except: pass

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
    app.add_handler(CallbackQueryHandler(cb_logic))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all))
    print(">>> BOT 100% CLEAN ONLINE <<<")
    app.run_polling()

if __name__ == '__main__': main()
