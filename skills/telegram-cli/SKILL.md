______________________________________________________________________

## name: telegram-cli description: Send Telegram messages directly using the Telegram Bot API via curl. homepage: https://core.telegram.org/bots/api metadata: { "openclaw": { "emoji": "✈️" } }

# telegram-cli

Use this skill when you need to send messages to a Telegram chat, group, or channel manually.
Even though it's called `telegram-cli`, you do not need a dedicated CLI binary. You can execute `curl` commands directly against the Telegram Bot REST API.

## Sending Messages

To send a message, use the `run_command` tool to execute `curl`.
You will need a Telegram Bot Token and the target Chat ID.

### Example Usage:

```bash
curl -s -X POST "https://api.telegram.org/bot<BOT_TOKEN>/sendMessage" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "<CHAT_ID>",
    "text": "Hello from the agent!",
    "parse_mode": "MarkdownV2"
  }'
```

### Notes

- **Bot Token**: The token is exported in your environment variables. You can access it directly via `$TELEGRAM_BOT_TOKEN` in your shell commands rather than looking for a `.env` file.
- **Chat ID**: If you are messaging a user, you need their numeric Chat ID. For supergroups, it will be a negative number (e.g., `-100123456789`).
- **Formatting**: Use `parse_mode="MarkdownV2"` or `HTML` if you need formatted text, but remember to escape special characters if using MarkdownV2.
