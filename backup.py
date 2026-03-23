import telebot
import os
from dotenv import load_dotenv

# load_dotenv() gunanya untuk baca file .env jika di lokal/Termux
# Di Railway, dia akan otomatis ambil dari tab Variables
load_dotenv()

TOKEN = os.getenv("TOKEN")
OWNER_ID = os.getenv("OWNER_ID") # Pastikan di Railway namanya OWNER_ID

bot = telebot.TeleBot(TOKEN)

def kirim_ke_telegram():
    try:
        # Cek apakah file database ada
        if os.path.exists('bungkata.db'):
            with open('bungkata.db', 'rb') as doc:
                bot.send_document(OWNER_ID, doc, caption="Ini Backup Database dari Railway!")
            print("Database berhasil terkirim!")
        else:
            print("File bungkata.db tidak ditemukan di server.")
    except Exception as e:
        print(f"Terjadi kesalahan: {e}")

if __name__ == "__main__":
    kirim_ke_telegram()
