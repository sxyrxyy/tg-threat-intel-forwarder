# Telegram Intel Framework

A bot-based CLI tool for monitoring a Telegram chat and collecting intelligence to local files. Uses the Telegram Bot API via `pyTelegramBotAPI`.

## Setup

1. Install dependencies:
   ```
   pip install pyTelegramBotAPI
   ```

2. Edit the constants at the top of `main.py`:
   ```python
   BOT_TOKEN      = "..."          # your bot token from @BotFather
   SOURCE_CHAT_ID = -100xxxxxxxxx  # chat to monitor (must have the bot as a member/admin)
   ```

3. Run:
   ```
   python main.py
   ```

## Menu Options

| # | Option | Description |
|---|--------|-------------|
| 1 | Recon | Calls `getMe`, `getChat`, `getChatAdministrators` for the source chat and any previously discovered chats. Saves to `output/recon.json`. |
| 2 | Drain updates | Pulls all pending updates via `getUpdates` pagination, saves raw JSON, advances the offset, and discovers new users/chats. Resumes from the last saved offset across runs. |
| 3 | Generate summary | Parses `updates_raw.json` into a chronological human-readable log. Produces `updates_summary.txt` (original language) and `updates_summary_EN.txt` (with English translations where available). |
| 4 | Probe entities | Enriches every discovered user and chat: profile photo count, membership status across known chats, invite links, member counts, admin lists. Updates `discovered.json`. |
| 5 | Download media | Downloads all photos, videos, documents, audio, voice, video notes, and animations from stored updates into `output/media/`. Skips already-downloaded files. Can filter by sender UID. |
| 6 | Create invite link | Generates a new invite link for the source chat via `createChatInviteLink`. |

## Output Files

```
output/
├── offset.txt          # last acknowledged update_id (resume point)
├── updates_raw.json    # all raw update objects, de-duped and sorted
├── discovered.json     # users and chats found across all updates
├── recon.json          # recon results for all known chats
├── updates_summary.txt     # chronological log (original language)
├── updates_summary_EN.txt  # chronological log (English translations)
└── media/              # downloaded media files
```

## Notes

- The bot must be a member (ideally admin) of `SOURCE_CHAT_ID` to receive updates and run recon.
- Offset is persisted to `output/offset.txt` so draining resumes where it left off after a restart.
- Stickers are intentionally excluded from media downloads.
