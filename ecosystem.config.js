module.exports = {
  apps : [{
    name: "bot-kata",
    script: "./kata.py",
    cwd: "/root/bot_kata",
    interpreter: "/root/bot_kata/venv/bin/python",
    env: {
      NODE_ENV: "production",
    }
  }]
}
