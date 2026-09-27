#!/usr/bin/env bash
#
# Nối Alertmanager với Telegram.
#
#   1. Chat @BotFather -> /newbot -> copy token
#   2. Ghi token vào  monitoring/alertmanager/secrets/bot_token
#      (file này đã gitignore, token không bao giờ vào repo)
#   3. Nhắn cho bot của bạn một câu bất kỳ  <- BẮT BUỘC, nếu không
#      getUpdates sẽ rỗng và script không tìm được chat id
#   4. ./scripts/setup_telegram.sh
#
# Script tự tìm chat id, vá vào alertmanager.yml, restart, rồi bắn một alert
# thử để bạn biết chắc là đường đi thông.
#
set -euo pipefail

cd "$(dirname "$0")/.."
TOKEN_FILE=monitoring/alertmanager/secrets/bot_token
CONFIG=monitoring/alertmanager/alertmanager.yml

[[ -f $TOKEN_FILE ]] || { echo "Không thấy $TOKEN_FILE"; exit 1; }
TOKEN=$(tr -d '[:space:]' < "$TOKEN_FILE")
case "$TOKEN" in
  ""|*PLACEHOLDER*) echo "Token vẫn là placeholder. Ghi token thật vào $TOKEN_FILE trước."; exit 1;;
esac

# Token hợp lệ chưa? getMe là cách rẻ nhất để hỏi, và không gửi gì cho ai.
BOT=$(curl -fsS "https://api.telegram.org/bot${TOKEN}/getMe" \
      | sed -n 's/.*"username":"\([^"]*\)".*/\1/p') \
  || { echo "Telegram từ chối token này (401). Kiểm tra lại đã copy đủ chưa."; exit 1; }
echo "  bot: @${BOT}"

CHAT=$(curl -fsS "https://api.telegram.org/bot${TOKEN}/getUpdates" \
       | sed -n 's/.*"chat":{"id":\(-\{0,1\}[0-9]*\).*/\1/p' | tail -1)
[[ -n $CHAT ]] || { echo "getUpdates rỗng. Nhắn cho @${BOT} một câu rồi chạy lại."; exit 1; }
echo "  chat id: ${CHAT}"

sed -i '' "s/^\( *chat_id: \).*/\1${CHAT}/" "$CONFIG"
grep -n "chat_id:" "$CONFIG" | sed 's/^/  đã vá: /'

docker compose restart alertmanager >/dev/null
sleep 5
docker compose exec -T alertmanager amtool check-config /etc/alertmanager/alertmanager.yml | head -1

echo "  bắn alert thử..."
ENDS=$(date -u -v+2M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '+2 minutes' +%Y-%m-%dT%H:%M:%SZ)
curl -fsS -XPOST http://127.0.0.1:19093/api/v2/alerts -H 'Content-Type: application/json' -d "[{
  \"labels\": {\"alertname\":\"TelegramTest\",\"severity\":\"critical\",\"job\":\"wdbc-api\"},
  \"annotations\": {\"summary\":\"Kiểm tra đường Alertmanager -> Telegram\",
                    \"description\":\"Nhận được tin này nghĩa là cấu hình đã đúng.\"},
  \"endsAt\": \"${ENDS}\"}]" >/dev/null

echo "  đã gửi. Chờ ~10s (group_wait của severity=critical) rồi xem Telegram."
echo "  Không thấy gì thì soi lỗi:  docker compose logs --tail 20 alertmanager | grep -i notify"
