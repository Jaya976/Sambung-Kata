import telebot
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
OWNER_ID = os.getenv("OWNER_ID")

bot = telebot.TeleBot(TOKEN)

def kirim_langsung():
    try:
        if os.path.exists('bungkata.db'):
            with open('bungkata.db', 'rb') as doc:
                bot.send_document(OWNER_ID, doc, caption="INI DATABASE KAMU!")
            print("BERHASIL TERKIRIM!")
        else:
            print("FILE DB TIDAK ADA")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    kirim_langsung()
    # JANGAN tambahkan bot.polling() di sini!
