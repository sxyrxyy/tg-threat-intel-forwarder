import os
import time
import json
import datetime
import urllib.request
import urllib.error
import telebot

# ==============================
# CONFIG – EDIT THESE CONSTANTS
# ==============================
BOT_TOKEN = "123"

# Chat to monitor (threat actor / source)
SOURCE_CHAT_ID = -123

# Output directory for all saved files
OUTPUT_DIR = "output"

# Offset tracking — persisted across runs so getUpdates resumes where it left off
OFFSET_FILE = os.path.join(OUTPUT_DIR, "offset.txt")

# Raw updates dump
UPDATES_RAW_FILE = os.path.join(OUTPUT_DIR, "updates_raw.json")

# Discovered entities
DISCOVERED_FILE = os.path.join(OUTPUT_DIR, "discovered.json")

# Media download directory
MEDIA_DIR = os.path.join(OUTPUT_DIR, "media")

# Which media types to auto-download from updates (stickers excluded)
DOWNLOAD_MEDIA_TYPES = {"photo", "video", "document", "audio", "voice", "video_note", "animation"}

# ==============================

BASE_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
BASE_FILE = f"https://api.telegram.org/file/bot{BOT_TOKEN}"


# ─────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────

def ensure_dirs():
    for d in [OUTPUT_DIR, MEDIA_DIR]:
        os.makedirs(d, exist_ok=True)


def ts(t):
    try:
        return datetime.datetime.fromtimestamp(t, datetime.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(t)


def api_get(endpoint, params=None):
    url = f"{BASE_API}/{endpoint}"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url += "?" + query
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def object_to_dict(obj):
    if isinstance(obj, dict):
        return {k: object_to_dict(v) for k, v in obj.items()}
    elif hasattr(obj, "__dict__"):
        return {k: object_to_dict(v) for k, v in obj.__dict__.items()}
    elif isinstance(obj, list):
        return [object_to_dict(item) for item in obj]
    return obj


def uname(u):
    if not u:
        return "(none)"
    nm = " ".join(x for x in [u.get("first_name"), u.get("last_name")] if x)
    un = f"@{u['username']}" if u.get("username") else ""
    return (nm + " " + un).strip() or f"[{u.get('id')}]"


# ─────────────────────────────────────────────
# Offset persistence
# ─────────────────────────────────────────────

def load_offset():
    try:
        return int(open(OFFSET_FILE).read().strip())
    except Exception:
        return None


def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))
    print(f"[*] Offset saved: {offset}")


# ─────────────────────────────────────────────
# Discovered entities (users + chats across runs)
# ─────────────────────────────────────────────

def load_discovered():
    try:
        return json.load(open(DISCOVERED_FILE, encoding="utf-8"))
    except Exception:
        return {"users": {}, "chats": {}}


def save_discovered(disc):
    with open(DISCOVERED_FILE, "w", encoding="utf-8") as f:
        json.dump(disc, f, ensure_ascii=False, indent=2)


def merge_discovered(disc, updates):
    """Walk all updates and absorb any new users/chats into disc."""
    def walk(o):
        if isinstance(o, dict):
            if "id" in o and ("first_name" in o or "username" in o) and "is_bot" in o:
                uid = str(o["id"])
                if uid not in disc["users"]:
                    disc["users"][uid] = {k: o.get(k) for k in
                        ("id", "is_bot", "first_name", "last_name", "username",
                         "is_premium", "language_code")}
            if "id" in o and "type" in o and o["type"] in ("group", "supergroup", "channel"):
                cid = str(o["id"])
                if cid not in disc["chats"]:
                    disc["chats"][cid] = {k: o.get(k) for k in
                        ("id", "title", "type", "username")}
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for u in updates:
        walk(u)


# ─────────────────────────────────────────────
# Ask helpers
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# 1. RECON
# ─────────────────────────────────────────────

def recon_chat(tb, chat_id, label=""):
    label = label or str(chat_id)
    print(f"\n[*] Recon: {label} ({chat_id})")
    result = {}

    try:
        chat = tb.get_chat(chat_id)
        result["chat"] = object_to_dict(chat)
        title       = getattr(chat, "title", None) or "(no title)"
        chat_type   = getattr(chat, "type",  None) or "(no type)"
        invite_link = getattr(chat, "invite_link", None) or "(no invite link)"
        print(f"  Title:       {title}")
        print(f"  Type:        {chat_type}")
        print(f"  Invite link: {invite_link}")
    except Exception as e:
        print(f"  [!] get_chat failed: {e}")

    try:
        count = tb.get_chat_members_count(chat_id)
        result["member_count"] = count
        print(f"  Members:     {count}")
    except Exception as e:
        print(f"  [!] get_chat_members_count failed: {e}")

    try:
        admins = tb.get_chat_administrators(chat_id)
        result["admins"] = object_to_dict(admins)
        print(f"  Admins ({len(admins)}):")
        for a in admins:
            u = a.user
            nm = uname(object_to_dict(u))
            print(f"    - {nm}  [{u.id}]  status={a.status}  bot={u.is_bot}")
    except Exception as e:
        print(f"  [!] get_chat_administrators failed: {e}")

    return result


def do_recon(tb):
    print("\n=== BOT IDENTITY ===")
    print(f"  Current offset : {load_offset() or '(none)'}")
    try:
        me = tb.get_me()
        d  = object_to_dict(me)
        print(json.dumps(d, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[!] get_me failed: {e}")

    disc = load_discovered()
    known_chats = {
        SOURCE_CHAT_ID: "Source chat",
    }
    # add anything found in previous update drains
    for cid_str, info in disc["chats"].items():
        cid = int(cid_str)
        if cid not in known_chats:
            known_chats[cid] = info.get("title") or cid_str

    results = {}
    for chat_id, label in known_chats.items():
        results[chat_id] = recon_chat(tb, chat_id, label)
        time.sleep(0.5)

    out = os.path.join(OUTPUT_DIR, "recon.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n[+] Recon saved -> {out}")


# ─────────────────────────────────────────────
# 2. DRAIN UPDATES
# ─────────────────────────────────────────────

def drain_updates(acknowledge=True):
    """
    Pull all pending updates via getUpdates pagination.
    acknowledge=True advances the offset (marks updates as read).
    acknowledge=False uses a negative offset trick to peek without consuming.
    Returns list of update dicts.
    """
    offset = load_offset()
    if offset:
        print(f"[*] Resuming from saved offset: {offset}")
    else:
        print("[*] No saved offset — starting from oldest pending update")

    all_updates = []
    batch_offset = offset

    while True:
        params = {"limit": "100", "timeout": "0"}
        if batch_offset is not None:
            params["offset"] = str(batch_offset)
        data = api_get("getUpdates", params)
        if not data.get("ok"):
            print(f"[!] getUpdates error: {data}")
            break
        batch = data.get("result", [])
        if not batch:
            break
        all_updates.extend(batch)
        batch_offset = batch[-1]["update_id"] + 1
        print(f"  fetched {len(batch)} (total {len(all_updates)}), next offset {batch_offset}")
        time.sleep(0.3)

    if not all_updates:
        print("[*] No new updates.")
        return []

    # de-dupe
    uniq = {u["update_id"]: u for u in all_updates}
    all_updates = [uniq[k] for k in sorted(uniq)]

    # merge into or append to existing raw file
    existing = []
    try:
        existing = json.load(open(UPDATES_RAW_FILE, encoding="utf-8"))
    except Exception:
        pass
    existing_ids = {u["update_id"] for u in existing}
    new_only = [u for u in all_updates if u["update_id"] not in existing_ids]
    merged = existing + new_only
    merged.sort(key=lambda u: u["update_id"])

    with open(UPDATES_RAW_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"[+] Raw updates saved -> {UPDATES_RAW_FILE}  ({len(merged)} total, {len(new_only)} new)")

    if acknowledge and batch_offset:
        save_offset(batch_offset)

    # update discovered entities
    disc = load_discovered()
    merge_discovered(disc, all_updates)
    save_discovered(disc)
    newly_found_chats = [v for k, v in disc["chats"].items()
                         if int(k) != SOURCE_CHAT_ID]
    if newly_found_chats:
        print(f"[+] New chats discovered in updates:")
        for c in newly_found_chats:
            print(f"    - {c.get('title') or c.get('id')}  [{c.get('id')}]  ({c.get('type')})")

    return new_only


# ─────────────────────────────────────────────
# English translations keyed by update_id
# ─────────────────────────────────────────────

EN = {
    123637648: "@tyty_tyt9 what's up",
    123637649: "Kudryavy [Curly] has sat down to get started",
    123637650: "https://bar-group-israel.com/bar_kol_haaretz/library/apps/details/com.delivery.bar.group.ltd/",
    123637651: "",
    123637652: "<photo>",
    123637653: "what is this?",
    123637654: "yeah I'll start now",
    123637655: "Cloudflare was down",
    123637656: "and those bastards were scanning",
    123637657: "holy shit 😂",
    123637658: "<photo>",
    123637659: "iPhone",
    123637660: "😁",
    123637661: "damn",
    123637662: "the old lady man)))",
    123637663: "she'll obviously never install it",
    123637664: "stupid",
    123637665: "these damn people",
    123637666: "lol",
    123637667: "old lady with iPhone",
    123637668: "stupid",
    123637669: "hahahaha",
    123637670: "damn",
    123637671: "first time I've seen something like this",
    123637672: "<sticker>",
    123637673: "damn her",
    123637674: "holy sh",
    123637675: "<sticker>",
    123637676: "her husband contacted them)))",
    123637677: "<sticker>",
    123637678: "<sticker>",
    123637679: "<sticker>",
    123637680: "))))))))))))))))))))",
    123637681: "damn lol",
    123637682: "damn",
    123637683: "@tyty_tyt9 what category are you going to DM?",
    123637684: "?",
    123637685: "Who told you I'm not going to DM?",
    123637686: "I was asking whether you guys were going to DM",
    123637687: "he's talking about categories",
    123637688: "TV",
    123637689: "😂😂😂😂 bowling pin [loser])))",
    123637690: "<sticker>",
    123637691: "everyone has iPhones now )))))",
    123637692: "they're driving me nuts",
    123637693: "Nobody wants to download",
    123637694: "Barely any motivation left",
    123637695: "They say do it yourselves",
    123637696: "same crap here",
    123637697: "🤦‍♂️",
    123637698: "They're completely pissing me off",
    123637699: "damn",
    123637700: "this is just nonsense",
    123637701: "almost no point in even messaging",
    123637702: "then there was no point in me fixing anything either 👍",
    123637703: "you wanted to DM for half an hour and pocket $10k?)",
    123637704: "or do you have other suggestions?",
    123637705: "lol",
    123637706: "what's wrong with you",
    123637707: "what do you mean DM for half an hour?",
    123637708: "FYI I do 15-20 DMs per half hour",
    123637709: "what's your deal",
    123637710: "👍",
    123637711: "just sat down to work",
    123637712: "and how many did you DM?)",
    123637713: "I've already been DMing for 2 hours",
    123637714: "let's not bullshit each other",
    123637715: "11 DMs sent",
    123637716: "one with iPhone",
    123637717: "waiting on 1",
    123637718: "another one is being difficult",
    123637719: "DMing on",
    123637720: "I'll keep DMing too",
    123637721: "just telling it like it is",
    123637722: "they don't want to install",
    123637723: "that's all",
    123637724: "already a significant number",
    123637725: "same here... plus I don't know Hebrew. Imagine what it's like for me — writing without mistakes in a language I don't speak, translating multiple times. Grinding away, no other choice! Once we have money we'll run paid traffic",
    123637726: "for now we're doing it manually",
    123637727: "I asked — any other suggestions?",
    123637728: "I'm also blown away by having to DM in Hebrew",
    123637729: "no other way out.. gotta make profit to move forward",
    123637730: "well apparently not for now",
    123637731: "[VICTIM MSG] I can't download the app. It doesn't seem to be in the App Store.",
    123637732: "iPhone.",
    123637733: "gotcha damn",
    123637734: "😂",
    123637735: "<sticker>",
    123637736: "[COVER STORY] Unfortunately I'm not very tech-savvy with these apps... If you need a TV you can order delivery or come see it in person :)",
    123637737: "I'm completely exhausted",
    123637738: "More than 10 people already say they won't install",
    123637739: "what's wrong with them?",
    123637740: "what's the reason",
    123637741: "they just don't want to",
    123637742: "that's all",
    123637743: "apparently they don't want to sell",
    123637744: ")",
    123637745: "try a different category",
    123637746: "T-shirts for 20 shekels",
    123637747: "what am I supposed to pick then",
    123637748: "I've already got 3 iPhone refusals",
    123637749: "yeah )))) do all that for 20 shekels ))))",
    123637750: "I've got more than 5.",
    123637751: "Either they won't install or they have iPhone",
    123637752: "just keep DMing then.. until someone with Android agrees",
    123637753: "Alright )",
    123637754: "We'll see",
    123637755: "Delivery category has been phished",
    123637756: "everyone is scared",
    123637757: "Yeah",
    123637758: "Someone warned them somewhere",
    123637759: "Most likely",
    123637760: "maybe I'll deploy the PWA and Heron will pour traffic",
    123637761: "we say there was a technical problem",
    123637762: "go ahead and deploy it",
    123637763: "it wasn't working",
    123637764: "he won't pour traffic",
    123637765: "can't know for sure",
    123637766: "I'll ask in the chat",
    123637767: "ok go ahead",
    123637768: "yeah the delivery category has been completely phished",
    123637769: "that's why they're scared",
    123637770: "of any links, files etc.",
    123637771: "Understood",
    123637772: "But it wasn't like this before",
    123637773: "I'm saying someone warned them somewhere",
    123637774: "after we started",
    123637775: ".",
    123637776: "yeah here",
    123637777: "Dear HAREL SHALOM,  We are pleased to tell you that the server you ordered has now been set up and is operational.   Server Details ============================= Bronze IP: 51.89.204.18 Username: root Password: 3v8k7A0xdS Server name: vps12601",
    123637778: "yeah",
    123637779: "yeah most likely",
    123637780: "but we didn't even do anything yet lmao 😂",
    123637781: "yeah lol",
    123637782: "wild",
    123637783: "well we did something",
    123637784: "They cancelled that other thing",
    123637785: "<photo>",
    123637786: "<sticker>",
    123637787: "that bastard won't pour traffic to the PWA anymore",
    123637788: "<sticker>",
    123637789: "damn",
    123637790: "what's wrong with this guy",
    123637791: "he's a pain in the ass",
    123637792: "damn",
    123637793: "<sticker>",
    123637794: "won't be able to do anything",
    123637795: "yeah",
    123637796: "lol",
    123637797: "put up a 100MB build",
    123637798: "for direct delivery",
    123637799: "direct",
    123637800: "to the landing page",
    123637801: "nobody's gonna download",
    123637802: "they won't figure out the installation",
    123637803: "understood yeah",
    123637804: "pick categories with bigger ticket items",
    123637805: "they get phished less often... so they're less cautious",
    123637806: "<sticker>",
    123637807: "damn",
    123637808: "+",
    123637809: "I'll try",
    123637810: "I'm DMing baby cribs, tables for now",
    123637811: "damn where do I find an icon",
    123637812: "for the game [app]",
    123637813: "damn",
    123637814: "holy shit 😂",
    123637815: "no idea",
    123637816: "only old ones left",
    123637817: "<photo>",
    123637818: "I'll put this one for now",
    123637819: "+ need creatives",
    123637820: "damn",
    123637821: "yeah",
    123637822: "there aren't any lol",
    123637823: "damn",
    123637824: "I'll try to make some",
    123637825: "<photo>",
    123637826: "he's pissing me off",
    123637827: "completely",
    123637828: "at least catch some Kali [Linux clients] damn",
    123637829: "to launch traffic)))",
    123637830: "yeah that's an option",
    123637831: "is everything working there?",
    123637832: "idiot",
    123637833: "screw him",
    123637834: "going to the blacklist",
    123637835: "should be yeah",
    123637836: "I'll change the file later",
    123637837: "for now I'll just keep sending them",
    123637838: "you can download it on GoodPlayStore to check",
    123637839: "in theory should be fine",
    123637840: "<photo>",
    123637841: "stupid [expletive]",
    123637842: "oh god",
    123637843: "what's wrong with this guy",
    123637844: "always",
    123637845: "damn",
    123637846: "<voice>",
    123637847: "please change it from Flexible to Full",
    123637848: "I'll do it now",
    123637849: "yeah lol",
    123637850: "doesn't know anything",
    123637851: "looks like he's running traffic with AI",
    123637852: "moron",
    123637853: "stupid",
    123637854: "that's arbi [traffic buyer]",
    123637855: "is pouring [traffic]",
    123637856: "hahahaha",
    123637857: "just some idiots",
    123637858: "damn",
    123637859: "Hector literally can't handle the landing page",
    123637860: "figure it out",
    123637861: "stupid",
    123637862: "🛡️ Domain: happygamenow.top  Current mode: Full  Off: SSL disabled, data unencrypted.  Flexible: Visitors see https but server receives http.  Full: Fully encrypted end-to-end.",
    123637863: "lol",
    123637864: "damn",
    123637865: "<sticker>",
    123637866: "<sticker>",
    123637867: "<sticker>",
    123637868: "<sticker>",
    123637869: "damn",
    123637870: "https://happygamenow.top",
    123637871: "<sticker>",
    123637872: "that's me",
    123637873: "iPhone",
    123637874: "damn",
    123637875: "guy with Xiaomi [can't install]",
    123637876: "<sticker>",
    123637877: "stupid Hector",
    123637878: "go to hell",
    123637879: "<sticker>",
    123637880: "bastard is driving me nuts, moron",
    123637881: "80 leads and 1 log [install]",
    123637882: "as usual",
    123637883: "lol",
    123637884: "how can this even be",
    123637885: "lol",
    123637886: "what the hell",
    123637887: "crypter is working",
    123637888: "dropper is working",
    123637889: "ACB [anti-detect browser] is being served",
    123637890: "I've been sitting for several hours now",
    123637891: "0",
    123637892: "how many DMs have you sent?",
    123637893: "a lot",
    123637894: "very",
    123637895: "a lot",
    123637896: "let's go I'll give you some photos",
    123637897: "try",
    123637898: "to make",
    123637899: "creatives",
    123637900: "the AI ones have become garbage",
    123637901: "AI",
    123637902: "they don't want to do anything",
    123637903: "damn",
    123637904: "why??????? you shared the creatives there",
    123637905: "yeah it won't do it I know",
    123637906: "and those are supposed to be normal creatives?",
    123637907: "only Hector would pour traffic to such garbage",
    123637908: "damn",
    123637909: "looks like Hector went and bought himself a bot mobile",
    123637910: "lol",
    123637911: "hahahaha",
    123637912: "damn",
    123637913: "all makes sense",
    123637914: "and what if there's Leumi [Bank Leumi]",
    123637915: "do you have IB [internet banking]?",
    123637916: "it says that through internet banking withdrawals only go to the drop account — names must match: when you send SEPA the IB and bank must show the same name etc.",
    123637917: "what did I say",
    123637918: "and where did Leumi come from",
    123637919: "!!!",
    123637920: "SEPA doesn't matter, I know which banks don't check the name",
    123637921: "exactly internet banking",
    123637922: "checks [the name]",
    123637923: "well he's still sitting and DMing",
    123637924: "as you can see",
    123637925: "I don't understand",
    123637926: "I'll do the internet banking on a victim [mammoth]",
    123637927: "me too",
    123637928: "understood",
    123637929: "[VICTIM REPLY] Sorry, I don't sell using this method, there's a lot of fraud. :)",
    123637930: ":)",
    123637931: "well they've been phished alright",
    123637932: "of course",
    123637933: "apparently",
    123637934: "mine",
    123637935: "m",
    123637936: "who is this jerk",
    123637937: "??????????????????",
    123637938: "hope everything's working there",
    123637939: "or I'll just delete Telegram",
    123637940: "damn",
    123637941: "what kind of bot is this",
    123637942: "check",
    123637943: "the time",
    123637944: "lol",
    123637945: "delete Telegram later",
    123637946: "oh",
    123637947: "hahaha",
    123637948: "damn",
    123637949: "god what a brainless creature going by the name Hector",
    123637950: "<photo>",
    123637951: "stupid bastard",
    123637952: "scoundrel",
    123637953: "<photo>",
    123637954: "LMAOOO",
    123637955: "damn",
    123637956: "he never poured traffic for me",
    123637957: "to the PWA",
    123637958: "LOL",
    123637959: "go to hell",
    123637960: "he poured traffic to the landing once",
    123637961: "damn",
    123637962: "Hector",
    123637963: "what's his deal lol?",
    123637964: "giving him the PWA now",
    123637965: "so we don't sit here with nothing",
    123637966: "would've blocked him long ago",
    123637967: "still has the nerve to make demands",
    123637968: "that guy will never stop writing",
    123637969: "always",
    123637970: "will buy a new",
    123637971: "account",
    123637972: "he's a pain in the ass lol",
    123637973: "stupid [expletive]",
    123637974: "nobody will install",
    123637975: "that's what I gather",
    123637976: "no idea what's wrong with these people",
    123637977: "nobody replied",
    123637978: "<sticker>",
    123637979: "<photo>",
    123637980: "oh god",
    123637981: "oh god",
    123637982: "I can't take this",
    123637983: ".....",
    123637984: "bro we're going to need cloaking there",
    123637985: "is there a cloaker",
    123637986: "for $40 yes",
    123637987: "already expired",
    123637988: "great [sarcastic]",
    123637989: "how is he going to launch on FB then",
    123637990: "damn",
    123637991: "<sticker>",
    123637992: "maybe Heron has a cloaker 🤔",
    123637993: "doubtful",
    123637994: "damn",
    123637995: "what kind of traffic buyer has no cloaker",
    123637996: "he's not a traffic buyer at all",
    123637997: "no idea what he does",
    123637998: "just clicks buttons and that's it",
    123637999: "he just has money",
    123638000: "damn",
    123638001: "how will he pour traffic then",
    123638002: "useless",
    123638003: "what do you mean pour",
    123638004: "didn't get it",
    123638005: "you mean the cloaker",
    123638006: "yes",
    123638007: "FB will ban [the ads]",
    123638008: "you know it yourself",
    123638009: "<photo>",
    123638010: "they're running these",
    123638011: "in the",
    123638012: "FB [Facebook]",
    123638013: "ad library targeting Hungary",
    123638014: "<sticker>",
    123638015: "<photo>",
    123638016: "Kudryavy [Curly] made this 😂",
    123638017: "what even is this lmao",
    123638018: "hahahaha",
    123638019: "not bad",
    123638020: "well they run this kind of stuff targeting Hungary 😂",
    123638021: ")))))))))",
    123638022: "well that's not an APK",
    123638023: "apparently",
    123638024: "understood yeah",
    123638025: "<photo>",
    123638026: "I can't damn",
    123638027: "[COPYING VICTIM] Why are you calling me names? Bro I don't talk to you like that",
    123638028: "[COPYING VICTIM] Have you ever seen me address you that way",
    123638029: "[COPYING VICTIM] I want to be treated the same way I treat others",
    123638030: "[COPYING VICTIM] Stop it",
    123638031: "[COPYING VICTIM] I don't use such expressions myself",
    123638032: "lol",
    123638033: "acting like a girl now",
    123638034: "damn idiot",
    123638035: "<photo>",
    123638036: "<sticker>",
    123638037: "lol",
    123638038: "damn these people",
    123638039: "Clown",
    123638040: "ah I see",
    123638041: "stupid [expletive]",
    123638042: "<audio>",
    123638043: "what is she saying?",
    123638044: "@tyty_tyt9",
    123638045: "done",
    123638046: "it's working now",
    123638047: "what?",
    123638048: "mine wouldn't recognize [it]",
    123638049: "the app finally woke up",
    123638050: "[VICTIM REPLY] I'm trying to install the app through Google but Google says it's unsafe so I'm cancelling the order. If you want call the courier here. Everything's fine, I'm not installing the app.",
    123638051: "lol",
    123638052: "unknown",
    123638053: "sources",
    123638054: "apparently",
    123638055: "yeah probably",
    123638056: "this delivery category is driving me nuts)))",
    123638057: "<sticker>",
    123638058: "if Google then use GoodPlayStore",
    123638059: "why",
    123638060: "she didn't even download it",
    123638061: "then what unknown sources warning even",
    123638062: "if she didn't download",
    123638063: "wt? lol",
    123638064: "unknown sources",
    123638065: "[prompt] when installing APK",
    123638066: "I don't understand",
    123638067: "what APK if you're saying she didn't download!!!",
    123638068: "or do you mean Chrome",
    123638069: "Chrome error",
    123638070: "inside the PWA it IS Chrome — if she's never installed an APK from it before then it asks for unknown sources permission",
    123638071: "and if she has a Xiaomi it will say it's unsafe",
    123638072: "+",
    123638073: "inside the PWA it IS Chrome — if she's never installed an APK from it before then it asks for unknown sources permission [EDIT]",
    123638074: "and if she has a Xiaomi it will say it's unsafe [EDIT]",
    123638075: "<photo>",
    123638076: "lol",
}

# ─────────────────────────────────────────────
# 3. GENERATE SUMMARY
# ─────────────────────────────────────────────

def generate_summary():
    try:
        updates = json.load(open(UPDATES_RAW_FILE, encoding="utf-8"))
    except Exception:
        print("[!] No updates file found. Run 'Drain updates' first.")
        return

    disc   = load_discovered()
    users  = disc.get("users", {})
    chats  = disc.get("chats", {})
    kinds  = {}
    lines_raw = []
    lines_en  = []

    for upd in updates:
        uid  = upd["update_id"]
        kind = next((k for k in upd if k != "update_id"), "?")
        kinds[kind] = kinds.get(kind, 0) + 1
        msg  = upd.get(kind) if isinstance(upd.get(kind), dict) else {}
        frm  = msg.get("from") or {}
        ch   = msg.get("chat") or {}

        txt = msg.get("text") or msg.get("caption") or ""
        media = next((m for m in
            ("photo","video","document","sticker","voice","audio",
             "animation","video_note","poll","contact","location")
            if m in msg), "")
        if not txt and media:
            txt = f"<{media}>"
        if "new_chat_members" in msg:
            txt = "JOINED: " + ", ".join(uname(object_to_dict(x)) for x in msg["new_chat_members"])
        if "left_chat_member" in msg:
            txt = "LEFT: " + uname(msg["left_chat_member"])

        when   = ts(msg.get("date")) if msg.get("date") else ""
        header = (f"[{uid}] {when} | {kind} | "
                  f"{uname(frm)} | in {ch.get('title') or ch.get('id')}")

        lines_raw.append(f"{header}\n      {txt[:300].replace(chr(10), ' ')}")

        txt_en = EN.get(uid, txt)   # fall back to original if no translation
        lines_en.append(f"{header}\n      {txt_en[:300].replace(chr(10), ' ')}")

    def write_file(path, lines, lang_label):
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"UPDATES SUMMARY {lang_label} — {len(updates)} updates\n")
            if updates:
                f.write(f"Range: {updates[0]['update_id']} -> {updates[-1]['update_id']}\n\n")
            f.write("Update types:\n")
            for k, v in sorted(kinds.items(), key=lambda x: -x[1]):
                f.write(f"  {k}: {v}\n")
            f.write(f"\nDistinct users: {len(users)}\n")
            for u in users.values():
                flags = ("PREMIUM " if u.get("is_premium") else "") + ("BOT" if u.get("is_bot") else "")
                f.write(f"  - {uname(u)}  [{u.get('id')}]  {flags}\n")
            f.write(f"\nDistinct chats: {len(chats)}\n")
            for c in chats.values():
                f.write(f"  - {c.get('title') or '(no title)'}  [{c.get('id')}]  ({c.get('type')})\n")
            f.write("\n" + "=" * 70 + f"\nCHRONOLOGICAL LOG {lang_label}\n" + "=" * 70 + "\n")
            f.write("\n".join(lines))
        print(f"[+] {lang_label} summary -> {path}")

    write_file(os.path.join(OUTPUT_DIR, "updates_summary.txt"),    lines_raw, "[RU/HE]")
    write_file(os.path.join(OUTPUT_DIR, "updates_summary_EN.txt"), lines_en,  "[EN]")


# ─────────────────────────────────────────────
# 4. PROBE DISCOVERED ENTITIES
# ─────────────────────────────────────────────

def probe_discovered(tb):
    disc = load_discovered()
    users = disc.get("users", {})
    chats = disc.get("chats", {})

    # getChat for each discovered chat not already in recon
    known = {SOURCE_CHAT_ID}
    for cid_str, info in chats.items():
        cid = int(cid_str)
        if cid in known:
            continue
        print(f"\n[*] Probing chat: {info.get('title') or cid}  [{cid}]")
        try:
            chat = tb.get_chat(cid)
            cd = object_to_dict(chat)
            info.update({k: cd.get(k) for k in
                ("title", "type", "invite_link", "description", "username")
                if cd.get(k)})
            print(f"  invite_link: {cd.get('invite_link') or '(none)'}")
            print(f"  description: {cd.get('description') or '(none)'}")
        except Exception as e:
            print(f"  [!] get_chat failed: {e}")
        try:
            count = tb.get_chat_members_count(cid)
            info["member_count"] = count
            print(f"  members: {count}")
        except Exception:
            pass
        try:
            admins = tb.get_chat_administrators(cid)
            info["admins"] = object_to_dict(admins)
            print(f"  admins ({len(admins)}):")
            for a in admins:
                u = a.user
                print(f"    - {uname(object_to_dict(u))}  [{u.id}]  status={a.status}")
        except Exception as e:
            print(f"  [!] get_chat_administrators failed: {e}")
        time.sleep(0.5)

    # getUserProfilePhotos + getChatMember for each discovered user
    chat_ids = [SOURCE_CHAT_ID] + [int(k) for k in chats]
    for uid_str, uinfo in users.items():
        uid = int(uid_str)
        if uinfo.get("is_bot"):
            continue
        print(f"\n[*] Probing user: {uname(uinfo)}  [{uid}]")

        try:
            photos = api_get("getUserProfilePhotos", {"user_id": str(uid), "limit": "5"})
            pcount = photos.get("result", {}).get("total_count", 0)
            uinfo["profile_photo_count"] = pcount
            print(f"  profile photos: {pcount}")
        except Exception as e:
            print(f"  [!] getUserProfilePhotos failed: {e}")

        for cid in chat_ids:
            try:
                data = api_get("getChatMember", {"chat_id": str(cid), "user_id": str(uid)})
                status = data.get("result", {}).get("status", "unknown")
                chat_title = chats.get(str(cid), {}).get("title") or str(cid)
                uinfo.setdefault("memberships", {})[str(cid)] = status
                print(f"  [{cid}] {chat_title}: {status}")
            except Exception:
                pass
            time.sleep(0.2)

    save_discovered(disc)
    out = os.path.join(OUTPUT_DIR, "discovered.json")
    print(f"\n[+] Discovered entities saved -> {out}")


# ─────────────────────────────────────────────
# 5. DOWNLOAD MEDIA
# ─────────────────────────────────────────────

def download_media(filter_uid=None):
    try:
        updates = json.load(open(UPDATES_RAW_FILE, encoding="utf-8"))
    except Exception:
        print("[!] No updates file. Run 'Drain updates' first.")
        return

    downloaded = 0
    skipped    = 0

    for upd in updates:
        kind = next((k for k in upd if k != "update_id"), None)
        msg  = upd.get(kind) if isinstance(upd.get(kind), dict) else {}
        frm  = msg.get("from") or {}
        if filter_uid and frm.get("id") != filter_uid:
            continue

        for mtype in DOWNLOAD_MEDIA_TYPES:
            if mtype not in msg:
                continue
            raw = msg[mtype]
            if isinstance(raw, list):
                raw = raw[-1]   # largest photo
            if not isinstance(raw, dict):
                continue

            file_id   = raw.get("file_id")
            unique_id = raw.get("file_unique_id", "")[:12]
            date      = msg.get("date", 0)
            if not file_id:
                continue

            # check if already downloaded (match on unique_id in filename)
            existing = [f for f in os.listdir(MEDIA_DIR) if unique_id in f]
            if existing:
                skipped += 1
                continue

            try:
                info = api_get("getFile", {"file_id": file_id})
                if not info.get("ok"):
                    continue
                file_path = info["result"]["file_path"]
                ext  = file_path.rsplit(".", 1)[-1] if "." in file_path else "bin"
                sender_tag = (frm.get("username") or str(frm.get("id", "unknown")))
                fname = f"{mtype}_{date}_{unique_id}_{sender_tag}.{ext}"
                dest  = os.path.join(MEDIA_DIR, fname)
                dl_url = f"{BASE_FILE}/{file_path}"
                urllib.request.urlretrieve(dl_url, dest)
                size = os.path.getsize(dest)
                print(f"  [+] {fname}  ({size} bytes)")
                downloaded += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"  [!] Failed to download file_id={file_id}: {e}")

    print(f"\n[+] Downloaded: {downloaded}  |  Skipped (already saved): {skipped}")
    print(f"[+] Media dir: {MEDIA_DIR}")


# ─────────────────────────────────────────────
# MAIN MENU
# ─────────────────────────────────────────────

def print_status():
    offset = load_offset()
    try:
        raw_count = len(json.load(open(UPDATES_RAW_FILE, encoding="utf-8")))
    except Exception:
        raw_count = 0
    disc = load_discovered()
    n_users = len(disc.get("users", {}))
    n_chats = len(disc.get("chats", {}))
    print(f"\n  Saved offset : {offset or '(none)'}")
    print(f"  Stored updates : {raw_count}")
    print(f"  Discovered users : {n_users}  |  chats : {n_chats}")


MENU = """
╔══════════════════════════════════════════╗
║        Telegram Intel Framework          ║
╠══════════════════════════════════════════╣
║  1. Recon  (bot + all known chats)       ║
║  2. Drain updates  (getUpdates + save)   ║
║  3. Generate summary  (txt log)          ║
║  4. Probe discovered entities            ║
║  5. Download media from updates          ║
║  6. Create invite link  (source chat)    ║
║  0. Exit                                 ║
╚══════════════════════════════════════════╝"""


def main():
    ensure_dirs()
    print("=== Telegram Intel Framework ===")
    print(f"Token : {'SET' if BOT_TOKEN else 'MISSING'}")
    print(f"Source: {SOURCE_CHAT_ID}")
    print_status()

    if not BOT_TOKEN:
        print("[-] BOT_TOKEN is empty. Set it at the top of the script.")
        return

    tb = telebot.TeleBot(BOT_TOKEN)

    while True:
        print(MENU)
        choice = input("Choice: ").strip()

        if choice == "1":
            do_recon(tb)

        elif choice == "2":
            drain_updates(acknowledge=True)

        elif choice == "3":
            generate_summary()

        elif choice == "4":
            probe_discovered(tb)

        elif choice == "5":
            print("Filter by sender UID (leave blank for all):")
            raw = input("  UID: ").strip()
            fuid = int(raw) if raw.isdigit() else None
            download_media(filter_uid=fuid)

        elif choice == "6":
            try:
                link = tb.create_chat_invite_link(SOURCE_CHAT_ID)
                print(f"\n[+] Invite link: {link.invite_link}")
            except Exception as e:
                print(f"[!] Failed: {e}")

        elif choice == "0":
            print("Bye.")
            break

        else:
            print("Unknown option.")


if __name__ == "__main__":
    main()
