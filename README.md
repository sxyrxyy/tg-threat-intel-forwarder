# Telegram Threat Chat Archiver

Small Python tool to **inspect** a Telegram bot + chat and **forward/archive messages** from a source chat (e.g. threat actor channel) into your own destination chat.

The script:

- Shows detailed info about:
  - The bot (`get_me`)
  - The source chat (`get_chat`)
  - The chat administrators (`get_chat_administrators`)
- Prints a **parsed summary**:
  - Bot name, username, ID
  - Group title, ID, type
  - Invite link (if available)
  - Admin list (bot + humans)
- Forwards messages from a **source chat** to a **destination chat**, with:
  - Configurable start / max message ID
  - Normal mode (step 1) or fast mode (step 15)
  - Adjustable delay between messages
  - Basic error handling + backoff
- Optionally creates a new invite link for the source chat (if the bot is allowed).
- 
---

## Features

- 📡 **Recon mode**
  - `get_me` to inspect the bot
  - `get_chat` to inspect the source chat
  - `get_chat_administrators` to list admins
  - Pretty-printed JSON + a clean human-readable summary

- 📥 **Archiving / Forwarding**
  - Pull messages from a source chat and forward them into your own “archive” chat
  - Configurable:
    - `start_msg_id`
    - `max_msg_id`
    - `fast_mode` (step 15)
    - `delay_sec` between forwards
  - Stops after too many consecutive errors (e.g. reached the end of messages)

- 🧩 **Simple configuration**
  - Bot token, source chat ID, destination chat ID are hardcoded at the top of the script
  - Runtime prompts for everything else

- `pyTelegramBotAPI` (for `telebot`)

Install dependencies:

```bash
pip install pyTelegramBotAPI
