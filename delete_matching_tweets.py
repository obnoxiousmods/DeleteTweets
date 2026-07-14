"""
Enumerate your own tweets and delete the ones matching affection/relationship
keywords. Talks directly to X's GraphQL API using cookies you provide.

Usage:
    python delete_matching_tweets.py                 # dry run: list matches only
    python delete_matching_tweets.py --delete --yes  # actually delete matches
    python delete_matching_tweets.py --show-all      # dump every tweet + match flag

Cookies are read from cookies.json (auth_token + ct0 required).
Query IDs / bearer token below were bootstrapped from the live x.com JS bundle
(main.bcd2a32a.js) on 2026-07-14; refresh them if X returns 404s on the ops.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
COOKIES_FILE = HERE / "cookies.json"

BEARER = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttf"
    "k8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# Bootstrapped from the live client-web bundle (see module docstring).
# NOTE: the UserTweetsAndReplies hash in the bundle 404s against the API host
# (its persisted-query hash lives in an out-of-sync lazy chunk), so we use
# UserTweets. That is the "Posts" tab: original posts + reposts. Standalone
# replies to other people are not enumerated by this op.
QID_USER_TWEETS = "6r5OLCC_wFH4CpRyXKuAmQ"
QID_USER_BY_SCREEN_NAME = "2qvSHpkWTMS9i0zJAwDNiA"
QID_DELETE_TWEET = "nxpZCY2K-I6QoFHAHeojFQ"
QID_DELETE_RETWEET = "ZyZigVsNiFO6v1dEks1eWg"

# --- Keyword set -----------------------------------------------------------
# Two kinds of matches:
#   WORD_KEYWORDS  -> matched on word boundaries (so "her" won't hit "there").
#   PHRASE_KEYWORDS-> matched as substrings (multi-word / already specific).
# All matching is case-insensitive.
WORD_KEYWORDS = [
    # --- the name (and diminutives) ---
    "alyssa", "alyssas", "lyssa", "lyss", "lissa", "aly", "aly",
    # --- relationship / people ---
    "her", "hers", "she", "shes",
    "gf", "girlfriend", "bf", "boyfriend", "wife", "wifey", "husband", "hubby",
    "girl", "girlie", "woman", "lady", "partner", "gal", "chick",
    "ex", "date", "dating", "valentine", "anniversary", "relationship",
    "together", "couple", "fiance", "fiancee", "betrothed",
    # --- affection ---
    "love", "loved", "loves", "loving", "lovely", "lover", "loveable", "luv",
    "adore", "adored", "adores", "adoring", "adorable",
    "appreciate", "appreciated", "appreciates", "appreciation",
    "babe", "baby", "babygirl", "bae", "boo", "boobear",
    "sweetheart", "sweetie", "sweet", "sweets", "honey", "hun", "hunny",
    "darling", "dear", "dearest", "cutie", "cutiepie", "crush",
    "queen", "princess", "angel", "goddess", "muse", "sunshine", "starlight",
    "gorgeous", "beautiful", "pretty", "cute", "stunning", "hottie", "gorg",
    "precious", "treasure", "soulmate", "prince", "king",
    # --- longing / need ---
    "miss", "missed", "missing", "misses",
    "need", "needed", "needing", "needs",
    "want", "wanted", "wanting", "wants",
    "crave", "craved", "craving", "craves", "yearn", "yearning",
    "ache", "aching", "wish", "wished", "longing", "pining",
    # --- physical / affectionate acts ---
    "kiss", "kisses", "kissing", "kissed", "hug", "hugs", "hugging", "hugged",
    "cuddle", "cuddles", "cuddling", "cuddled", "snuggle", "snuggles",
    "hold", "holding", "embrace", "touch", "touching",
    # --- sexual ---
    "cum", "cumming", "cums", "came", "fuck", "fucking", "fucked", "fucks",
    "horny", "naked", "nude", "nudes", "sex", "sexy", "sexual", "moan",
    "moaning", "daddy", "mommy", "mami", "wet", "hard", "suck", "sucking",
    "dick", "cock", "pussy", "tits", "boobs", "ass", "thighs", "lips",
    "bed", "bedroom", "sleepover", "slut", "whore",
    # --- emotional bond ---
    "heart", "hearts", "soul", "forever", "always", "mine", "yours",
    "smile", "smiling", "eyes", "cozy", "warmth", "obsessed", "devoted",
    "mwah", "muah", "xoxo", "cutiepie",
]
PHRASE_KEYWORDS = [
    # longing
    "i miss", "miss you", "miss her", "missing you", "missing her",
    "miss u", "missed you", "i miss her", "i miss you",
    "i need", "need you", "i need you", "need u", "i want you", "want you",
    "want u", "i want", "cant stop thinking", "can't stop thinking",
    "thinking of you", "think of you", "thinking about you", "think about you",
    "wish you were", "wish u were", "come back",
    # love
    "i love you", "love you", "love u", "luv u", "ily", "i love her",
    "love her", "i adore", "adore you", "i appreciate", "appreciate you",
    "i'm in love", "im in love", "in love", "falling for", "fell for",
    "head over heels", "make love", "making love",
    # possessive / pet
    "my girl", "my gf", "my babe", "my baby", "my love", "my queen",
    "my princess", "my angel", "my everything", "my other half",
    "my better half", "my heart", "my world", "my person", "my boo",
    "my sweetheart", "my darling", "my alyssa", "my woman", "my wife",
    "the love of my life", "you complete me", "you make me",
    # compliments
    "so cute", "so beautiful", "so gorgeous", "so pretty", "so sexy",
    "your smile", "your eyes", "your laugh", "prettiest", "most beautiful",
    # dates / intimacy
    "date night", "good night babe", "goodnight babe", "good morning babe",
    "good morning beautiful", "goodnight beautiful", "with you", "next to you",
    "wake up next to", "hold you", "kiss you", "cuddle you",
    # emoji
    "❤", "♥", "😍", "🥰", "😘", "😗", "😙", "😚", "💋", "💕", "💖", "💗",
    "💘", "💙", "💚", "💛", "🧡", "💜", "🤍", "🖤", "💝", "💞", "💓", "💌",
    "😻", "🥹", "🫶", "🥺", "👩‍❤️‍👨", "💑", "😩", "🍑", "🍆", "💦",
]


def build_matcher():
    word_re = re.compile(
        r"\b(" + "|".join(re.escape(w) for w in WORD_KEYWORDS) + r")\b",
        re.IGNORECASE,
    )
    phrases = [p.lower() for p in PHRASE_KEYWORDS]

    def match(text):
        if not text:
            return []
        hits = set(m.group(1).lower() for m in word_re.finditer(text))
        low = text.lower()
        for p in phrases:
            if p in low:
                hits.add(p)
        return sorted(hits)

    return match


def load_cookies():
    if not COOKIES_FILE.exists():
        sys.exit(f"Missing {COOKIES_FILE}")
    cookies = json.loads(COOKIES_FILE.read_text())
    if not cookies.get("auth_token") or not cookies.get("ct0"):
        sys.exit("cookies.json needs both auth_token and ct0")
    return cookies


def make_client(cookies):
    headers = {
        "authorization": BEARER,
        "x-csrf-token": cookies["ct0"],
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "content-type": "application/json",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
        ),
        "referer": "https://x.com/",
        "origin": "https://x.com",
    }
    return httpx.Client(
        base_url="https://x.com/i/api/graphql",
        cookies=cookies,
        headers=headers,
        http2=True,
        timeout=30,
    )


FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}


def get_self_rest_id(client, cookies):
    twid = cookies.get("twid", "")
    m = re.search(r"(\d{5,})", twid)
    if m:
        return m.group(1)
    sys.exit("Could not determine your user id from the twid cookie.")


def iter_own_tweets(client, rest_id, debug=False):
    """Yield (tweet_id, screen_name, full_text) for the account's own posts."""
    cursor = None
    seen = set()
    while True:
        variables = {
            "userId": rest_id,
            "count": 100,
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": False,
            "withVoice": True,
        }
        if cursor:
            variables["cursor"] = cursor
        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(FEATURES),
        }
        url = f"/{QID_USER_TWEETS}/UserTweets"
        r = client.get(url, params=params)
        remaining = r.headers.get("x-rate-limit-remaining")
        if r.status_code == 429:
            reset = int(r.headers.get("x-rate-limit-reset", time.time() + 60))
            wait = max(1, reset - int(time.time()))
            print(f"  rate limited, sleeping {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        data = r.json()

        entries = _find_entries(data)
        new_cursor = None
        page_count = 0
        for entry in entries:
            eid = entry.get("entryId", "")
            if eid.startswith("cursor-bottom-"):
                new_cursor = entry["content"].get("value")
                continue
            for tw in _extract_tweets(entry):
                if tw["id"] in seen:
                    continue
                seen.add(tw["id"])
                page_count += 1
                yield tw

        if debug:
            print(f"  page: +{page_count} tweets (total {len(seen)}), "
                  f"rate-remaining={remaining}")

        if not new_cursor or new_cursor == cursor or page_count == 0:
            break
        cursor = new_cursor


def _find_entries(data):
    """Pull timeline entries out of the UserTweetsAndReplies response."""
    try:
        instructions = (
            data["data"]["user"]["result"]["timeline_v2"]["timeline"]["instructions"]
        )
    except (KeyError, TypeError):
        # Some responses key it as "timeline" instead of "timeline_v2".
        try:
            instructions = (
                data["data"]["user"]["result"]["timeline"]["timeline"]["instructions"]
            )
        except (KeyError, TypeError):
            return []
    entries = []
    for ins in instructions:
        if ins.get("type") == "TimelineAddEntries":
            entries.extend(ins.get("entries", []))
        elif ins.get("type") == "TimelineReplaceEntry":
            e = ins.get("entry")
            if e:
                entries.append(e)
    return entries


def _extract_tweets(entry):
    """Yield tweet dicts from a timeline entry (item or module).

    Each dict: {id, screen_name, text, is_retweet, source_id}.
    For retweets, source_id is the ORIGINAL tweet id (needed by DeleteRetweet).
    """
    out = []
    content = entry.get("content", {})
    items = []
    if content.get("entryType") == "TimelineTimelineItem" or "itemContent" in content:
        items.append(content.get("itemContent", {}))
    if content.get("entryType") == "TimelineTimelineModule":
        for it in content.get("items", []):
            items.append(it.get("item", {}).get("itemContent", {}))
    for ic in items:
        if ic.get("itemType") != "TimelineTweet":
            continue
        res = ic.get("tweet_results", {}).get("result", {})
        if res.get("__typename") == "TweetWithVisibilityResults":
            res = res.get("tweet", {})
        rest_id = res.get("rest_id")
        legacy = res.get("legacy", {})
        if not rest_id or not legacy:
            continue
        sn = (
            res.get("core", {})
            .get("user_results", {})
            .get("result", {})
            .get("legacy", {})
            .get("screen_name")
            or res.get("core", {})
            .get("user_results", {})
            .get("result", {})
            .get("core", {})
            .get("screen_name")
        )
        # Retweet detection: retweeted_status_result holds the original tweet.
        rt = legacy.get("retweeted_status_result", {}).get("result", {})
        if rt.get("__typename") == "TweetWithVisibilityResults":
            rt = rt.get("tweet", {})
        is_retweet = bool(rt)
        source_id = rt.get("rest_id") if is_retweet else None

        # Note tweets (long form) carry text elsewhere.
        text = legacy.get("full_text", "")
        note = (
            res.get("note_tweet", {})
            .get("note_tweet_results", {})
            .get("result", {})
            .get("text")
        )
        if note:
            text = note
        out.append({
            "id": rest_id,
            "screen_name": sn,
            "text": text,
            "is_retweet": is_retweet,
            "source_id": source_id,
        })
    return out


def _post(client, qid, name, variables):
    r = client.post(f"/{qid}/{name}", json={"variables": variables, "queryId": qid})
    if r.status_code == 429:
        reset = int(r.headers.get("x-rate-limit-reset", time.time() + 60))
        return "ratelimit", max(1, reset - int(time.time()))
    if r.status_code != 200:
        return "http_error", f"{r.status_code} {r.text[:180]}"
    body = r.json()
    if body.get("errors"):
        return "api_error", body["errors"]
    return "ok", None


def remove(client, tw):
    """Delete an original tweet, or un-retweet a repost, as appropriate."""
    if tw["is_retweet"] and tw["source_id"]:
        return _post(client, QID_DELETE_RETWEET, "DeleteRetweet",
                     {"source_tweet_id": tw["source_id"], "dark_request": False})
    return _post(client, QID_DELETE_TWEET, "DeleteTweet",
                 {"tweet_id": tw["id"], "dark_request": False})


def main():
    # Windows consoles default to cp1252 and crash on emoji; force UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true",
                    help="actually delete matching tweets (default: dry run)")
    ap.add_argument("--yes", action="store_true",
                    help="skip the confirmation prompt")
    ap.add_argument("--no-retweets", action="store_true",
                    help="skip retweets/reposts (default: include them)")
    ap.add_argument("--show-all", action="store_true",
                    help="print every tweet and whether it matched")
    ap.add_argument("--json", default=None,
                    help="write the matched list to this JSON file (for review)")
    ap.add_argument("--from-json", default=None,
                    help="delete from a previously saved --json file (no re-scan). "
                         "Respects --delete/--yes; skips enumeration entirely.")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    cookies = load_cookies()
    client = make_client(cookies)

    # --- Delete from a reviewed JSON file, no enumeration (saves rate limit) ---
    if args.from_json:
        matches = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        print(f"Loaded {len(matches)} reviewed items from {args.from_json}")
        _run_deletion(client, matches, args)
        return

    match = build_matcher()

    rest_id = get_self_rest_id(client, cookies)
    print(f"Scanning tweets for user id {rest_id} ...")

    matches = []
    total = 0
    n_retweets = 0
    for tw in iter_own_tweets(client, rest_id, debug=args.debug):
        total += 1
        if tw["is_retweet"]:
            n_retweets += 1
            if args.no_retweets:
                continue
        hits = match(tw["text"])
        if args.show_all:
            flag = ("MATCH " + ",".join(hits)) if hits else "-"
            preview = tw["text"].replace("\n", " ")[:80]
            print(f"[{flag}] {tw['id']} {preview}")
        if hits:
            tw = dict(tw, hits=hits)
            matches.append(tw)

    print(f"\nScanned {total} tweets ({n_retweets} retweets); "
          f"{len(matches)} matched.\n")
    for tw in matches:
        preview = tw["text"].replace("\n", " ")[:110]
        kind = "RT" if tw["is_retweet"] else "  "
        print(f"  [{kind}] {tw['id']}  ({', '.join(tw['hits'])})")
        print(f"        {preview}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(matches, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nWrote {len(matches)} matches to {args.json}")

    _run_deletion(client, matches, args)


def _run_deletion(client, matches, args):
    if not matches:
        print("Nothing to delete.")
        return

    if not args.delete:
        print(f"\nDry run. Re-run with --delete --yes to remove these "
              f"{len(matches)} items.")
        return

    if not args.yes:
        ans = input(f"\nDelete these {len(matches)} items? This is "
                    f"irreversible. Type 'yes': ")
        if ans.strip().lower() != "yes":
            print("Aborted.")
            return

    ok = err = 0
    for tw in matches:
        while True:
            status, info = remove(client, tw)
            if status == "ratelimit":
                print(f"  rate limited, sleeping {info}s...")
                time.sleep(info)
                continue
            break
        if status == "ok":
            ok += 1
            print(f"  removed {tw['id']}")
        else:
            err += 1
            print(f"  FAILED {tw['id']}: {status} {info}")
        time.sleep(0.5)

    print(f"\nDone. Removed {ok}, failed {err}.")


if __name__ == "__main__":
    main()
