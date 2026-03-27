#!/bin/bash
set -e
echo ""
echo "🔄 GitHub থেকে আপডেট শুরু হচ্ছে..."
echo "═══════════════════════════════════════"

cp config.py /tmp/config_backup.py
echo "💾 config.py backup OK"

git fetch origin
git reset --hard origin/main
echo "✅ Pull সম্পন্ন"

cp /tmp/config_backup.py config.py
echo "✅ config.py restore OK"

pip install -q -r requirements.txt
echo "✅ Packages ready"

pkill -f "bgutil-pot" 2>/dev/null || true
pkill -f "node.*main.js" 2>/dev/null || true
sleep 1
if command -v bgutil-pot &>/dev/null; then
    nohup bgutil-pot server --host 127.0.0.1 --port 4416 > /tmp/bgutil.log 2>&1 &
    sleep 2
    echo "✅ bgutil POT server চালু (port 4416)"
fi

warp-cli connect 2>/dev/null && echo "✅ WARP connected" || echo "⚠️ WARP connect failed"

if screen -list 2>/dev/null | grep -q "bot"; then
    screen -S bot -X quit && sleep 2
    screen -dmS bot python3 main.py
    echo "✅ Bot (screen) restart OK"
elif command -v pm2 &>/dev/null && pm2 list 2>/dev/null | grep -q "bot"; then
    pm2 restart bot && echo "✅ Bot (pm2) restart OK"
elif systemctl is-active --quiet bot 2>/dev/null; then
    systemctl restart bot && echo "✅ Bot (systemd) restart OK"
else
    echo "⚠️  Bot manually restart করুন: python3 main.py"
fi

echo ""
echo "🎉 আপডেট সম্পন্ন!"
