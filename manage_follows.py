"""
Enumerate your following / followers and flag likely "egirl / camgirl / promo"
accounts, then (after review) unfollow them and/or remove them as followers.

Same concept as delete_matching_tweets.py: it talks to X's GraphQL/1.1 API with
your session cookies, classifies each account with a keyword+signal heuristic,
writes a review file, and only acts when you confirm.

Usage:
    # List following accounts flagged as egirl/promo (dry run):
    python manage_follows.py --list following

    # List flagged followers:
    python manage_follows.py --list followers

    # Save the flagged set for review:
    python manage_follows.py --list following --json follows.json

    # Review follows.json (delete entries you want to KEEP), then act:
    python manage_follows.py --from-json follows.json --unfollow --yes
    python manage_follows.py --from-json follows.json --remove-follower --yes

Two independent actions:
    --unfollow          stop following the account (friendships/destroy)
    --remove-follower   force the account to stop following YOU (RemoveFollower)
You can pass either or both.

Cookies are read from cookies.json (auth_token + ct0 required), same as
delete_matching_tweets.py.
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

# Bootstrapped from the live client-web bundle (see docs/refreshing-query-ids.md).
QID_FOLLOWING = "PEIBUtChvR2i_NZCxbK3fA"
QID_FOLLOWERS = "18SNsfvwgu2CYIweeUVHAw"
QID_REMOVE_FOLLOWER = "QpNfg0kpPRfjROQ_9eOLXA"

# --- Classifier ------------------------------------------------------------
# An account is FLAGGED if its total signal score >= THRESHOLD. Each matched
# signal contributes its weight and is recorded as a reason, so you can see
# exactly why something was flagged. This is heuristic and WILL have false
# positives/negatives -- always review before acting.
THRESHOLD = 2

# Strong signals (weight 2): rarely appear outside adult/promo accounts.
STRONG_BIO = [
    "onlyfans", "only fans", "0nlyfans", "0nlyf4ns", "0nlyfan",
    "fansly", "manyvids", "fanvue", "fancentro", "myfans",
    "cam girl", "camgirl", "e-girl", "egirl", "e girl",
    "findom", "financial dominatrix", "sexting", "sext", "sextape",
    "premium snap", "premium snapchat", "snapchat premium", "snap premium",
    "sub to my", "subscribe to my", "link in bio for", "spicy content",
    "nsfw", "18+", "🔞", "explicit content", "adult content", "content creator 🔞",
    "of:", "of🔗", "of 🔗", "of link", "my of", "join my of",
    "sugar baby", "sugar daddy", "selling content", "custom content",
    "dm for rates", "dm for menu", "menu in dm", "prices in dm", "rates in dm",
    "allmylinks", "fans.ly",
]
# Weaker signals (weight 1): suggestive but common; need corroboration.
WEAK_BIO = [
    "link in bio", "dm me", "dms open", "open dms", "collab", "promo",
    "wishlist", "cashapp", "$", "venmo", "throne", "spoil me", "spoil",
    "kitten", "brat", "goddess", "princess", "babygirl", "baby girl",
    "daddy", "mommy", "slut", "whore", "naughty", "🍑", "🍆", "💦", "😈",
    "come play", "let's play", "join me", "exclusive content", "vip",
    "creator", "model", "collabs", "telegram", "join my", "free trial",
]
# Signals in the display name / handle (weight 1 each).
NAME_SIGNALS = [
    "onlyfans", "🔞", "💦", "😈", "🍑", "🍆", "egirl", "e-girl", "cam",
    "baby", "babe", "kitten", "goddess", "princess", "angel", "slut", "brat",
    "mommy", "doll", "vixen", "bunny", "spicy", "naughty", "xo",
]


def build_classifier():
    def norm(s):
        return (s or "").lower()

    def classify(acct):
        bio = norm(acct.get("description"))
        name = norm(acct.get("name"))
        handle = norm(acct.get("screen_name"))
        url = norm(acct.get("url"))
        blob_name = name + " " + handle
        score = 0
        reasons = []

        for kw in STRONG_BIO:
            if kw in bio or kw in url:
                score += 2
                reasons.append(f"bio:{kw}(2)")
        for kw in WEAK_BIO:
            if kw in bio or kw in url:
                score += 1
                reasons.append(f"bio:{kw}")
        for kw in NAME_SIGNALS:
            if kw in blob_name:
                score += 1
                reasons.append(f"name:{kw}")

        # Link-aggregator bios (linktree/allmylinks/beacons) are a very common
        # adult-promo pattern; nudge them up.
        if any(d in url for d in ("linktr.ee", "allmylinks", "beacons", "throne")):
            score += 1
            reasons.append("link-aggregator")

        return score, sorted(set(reasons))

    return classify


# Junk / spam / low-activity detection. Same scoring idea as the egirl
# classifier: sum weighted signals, flag at/above JUNK_THRESHOLD, record why.
JUNK_THRESHOLD = 3


def build_junk_classifier():
    def classify(a):
        score = 0
        reasons = []
        st = a.get("statuses_count")
        fav = a.get("favourites_count")
        followers = a.get("followers_count")
        friends = a.get("friends_count")
        bio = (a.get("description") or "").strip()

        if a.get("default_profile_image"):
            score += 2
            reasons.append("no-avatar(2)")
        if st == 0:
            score += 2
            reasons.append("never-posts(2)")
        elif st is not None and st < 10:
            score += 1
            reasons.append(f"low-posts({st})")
        if not bio:
            score += 1
            reasons.append("empty-bio")
        if followers == 0:
            score += 1
            reasons.append("no-followers")
        if fav == 0 and (st or 0) < 10:
            score += 1
            reasons.append("no-interactions")
        # Classic follow-spam ratio: follows a ton, almost nobody follows back.
        if friends and friends > 1500 and followers is not None \
                and followers < friends / 20:
            score += 2
            reasons.append(f"follow-spam({friends}/{followers})(2)")
        if a.get("default_profile") and (st or 0) < 20:
            score += 1
            reasons.append("default-profile+low-activity")

        return score, sorted(set(reasons))

    return classify


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
    return httpx.Client(cookies=cookies, headers=headers, http2=True, timeout=30)


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


def get_self_rest_id(cookies):
    m = re.search(r"(\d{5,})", cookies.get("twid", ""))
    if m:
        return m.group(1)
    sys.exit("Could not determine your user id from the twid cookie.")


def iter_accounts(client, rest_id, kind, debug=False):
    """Yield account dicts from your Following or Followers list."""
    qid = QID_FOLLOWING if kind == "following" else QID_FOLLOWERS
    op = "Following" if kind == "following" else "Followers"
    cursor = None
    seen = set()
    while True:
        variables = {"userId": rest_id, "count": 100,
                     "includePromotedContent": False}
        if cursor:
            variables["cursor"] = cursor
        params = {"variables": json.dumps(variables),
                  "features": json.dumps(FEATURES)}
        r = client.get(f"https://x.com/i/api/graphql/{qid}/{op}", params=params)
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
            acct = _extract_user(entry)
            if not acct or acct["id"] in seen:
                continue
            seen.add(acct["id"])
            page_count += 1
            yield acct

        if debug:
            rem = r.headers.get("x-rate-limit-remaining")
            print(f"  page: +{page_count} (total {len(seen)}), rate-remaining={rem}")
        if not new_cursor or new_cursor == cursor or page_count == 0:
            break
        cursor = new_cursor


def _find_entries(data):
    try:
        tl = data["data"]["user"]["result"]["timeline"]["timeline"]
    except (KeyError, TypeError):
        return []
    entries = []
    for ins in tl.get("instructions", []):
        if ins.get("type") == "TimelineAddEntries":
            entries.extend(ins.get("entries", []))
    return entries


def _extract_user(entry):
    content = entry.get("content", {})
    ic = content.get("itemContent", {})
    if ic.get("itemType") != "TimelineUser":
        return None
    res = ic.get("user_results", {}).get("result", {})
    rest_id = res.get("rest_id")
    if not rest_id:
        return None
    legacy = res.get("legacy", {})
    core = res.get("core", {})
    persp = res.get("relationship_perspectives", {}) or {}
    # Newer payloads move name/screen_name/created_at into `core`.
    screen_name = legacy.get("screen_name") or core.get("screen_name")
    name = legacy.get("name") or core.get("name")
    created_at = legacy.get("created_at") or core.get("created_at")
    # Bio URL (expanded) if present.
    url = ""
    urls = (legacy.get("entities", {}).get("url", {}).get("urls", []))
    if urls:
        url = urls[0].get("expanded_url") or urls[0].get("display_url") or ""
    return {
        "id": rest_id,
        "screen_name": screen_name,
        "name": name,
        "description": legacy.get("description", ""),
        "url": url,
        "created_at": created_at,
        "statuses_count": legacy.get("statuses_count"),
        "followers_count": legacy.get("followers_count"),
        "friends_count": legacy.get("friends_count"),
        "media_count": legacy.get("media_count"),
        "favourites_count": legacy.get("favourites_count"),
        "default_profile_image": legacy.get("default_profile_image"),
        "default_profile": legacy.get("default_profile"),
        "is_blue_verified": res.get("is_blue_verified"),
        # Mutual-follow flags from MY perspective:
        "i_follow_them": bool(persp.get("following")),
        "they_follow_me": bool(persp.get("followed_by")),
    }


def unfollow(client, user_id):
    # Unfollow uses the legacy 1.1 endpoint (form-encoded), not GraphQL.
    r = client.post(
        "https://x.com/i/api/1.1/friendships/destroy.json",
        data={"user_id": user_id},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    return _status(r)


def remove_follower(client, user_id):
    r = client.post(
        f"https://x.com/i/api/graphql/{QID_REMOVE_FOLLOWER}/RemoveFollower",
        json={"variables": {"target_user_id": user_id},
              "queryId": QID_REMOVE_FOLLOWER},
    )
    return _status(r)


def _status(r):
    if r.status_code == 429:
        reset = int(r.headers.get("x-rate-limit-reset", time.time() + 60))
        return "ratelimit", max(1, reset - int(time.time()))
    if r.status_code != 200:
        return "http_error", f"{r.status_code} {r.text[:180]}"
    try:
        body = r.json()
    except Exception:
        return "ok", None
    if isinstance(body, dict) and body.get("errors"):
        return "api_error", body["errors"]
    return "ok", None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(
        description="Scan your following/followers and flag accounts to remove.")
    ap.add_argument("--list", choices=["following", "followers"],
                    help="which relationship to scan and classify")
    ap.add_argument("--mode", choices=["egirl", "junk", "both"], default="egirl",
                    help="what to flag: egirl/camgirl/promo, junk/spam/inactive, "
                         "or both (default: egirl)")
    ap.add_argument("--non-mutual", action="store_true",
                    help="only flag non-mutual accounts: when scanning "
                         "following, ones who don't follow you back; when "
                         "scanning followers, ones you don't follow back")
    ap.add_argument("--json", default=None,
                    help="write the flagged set to this file (for review)")
    ap.add_argument("--from-json", default=None,
                    help="act on a reviewed JSON file (no re-scan)")
    ap.add_argument("--unfollow", action="store_true",
                    help="unfollow the accounts (stop following them)")
    ap.add_argument("--remove-follower", action="store_true",
                    help="remove the accounts as YOUR followers")
    ap.add_argument("--all", action="store_true",
                    help="include every account, not just flagged ones")
    ap.add_argument("--yes", action="store_true", help="skip confirmation")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    cookies = load_cookies()
    client = make_client(cookies)

    if args.from_json:
        flagged = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        print(f"Loaded {len(flagged)} reviewed accounts from {args.from_json}")
        _act(client, flagged, args)
        return

    if not args.list:
        sys.exit("Pass --list following|followers (or --from-json FILE).")

    egirl = build_classifier()
    junk = build_junk_classifier()
    rest_id = get_self_rest_id(cookies)
    print(f"Scanning {args.list} (mode={args.mode}"
          f"{', non-mutual only' if args.non_mutual else ''}) "
          f"for user {rest_id} ...")

    flagged = []
    total = skipped_mutual = 0
    for acct in iter_accounts(client, rest_id, args.list, debug=args.debug):
        total += 1

        # Non-mutual filter.
        if args.non_mutual:
            if args.list == "following" and acct["they_follow_me"]:
                skipped_mutual += 1
                continue
            if args.list == "followers" and acct["i_follow_them"]:
                skipped_mutual += 1
                continue

        e_score, e_reasons = egirl(acct)
        j_score, j_reasons = junk(acct)
        if args.mode == "egirl":
            score, reasons, hit = e_score, e_reasons, e_score >= THRESHOLD
        elif args.mode == "junk":
            score, reasons, hit = j_score, j_reasons, j_score >= JUNK_THRESHOLD
        else:  # both
            score = e_score + j_score
            reasons = e_reasons + j_reasons
            hit = e_score >= THRESHOLD or j_score >= JUNK_THRESHOLD

        if args.all or hit:
            acct = dict(acct, score=score, reasons=reasons,
                        egirl_score=e_score, junk_score=j_score,
                        relationship=args.list)
            flagged.append(acct)

    flagged.sort(key=lambda a: a["score"], reverse=True)
    label = "accounts" if args.all else "flagged"
    extra = f" ({skipped_mutual} mutual skipped)" if args.non_mutual else ""
    print(f"\nScanned {total} {args.list}{extra}; {len(flagged)} {label}.\n")
    for a in flagged:
        mut = ("mutual" if a["i_follow_them"] and a["they_follow_me"]
               else "they→you" if a["they_follow_me"]
               else "you→them" if a["i_follow_them"] else "none")
        print(f"  @{a['screen_name']}  [{mut}] (score {a['score']}: "
              f"{', '.join(a['reasons']) or 'n/a'})")
        bio = (a['description'] or '').replace('\n', ' ')[:100]
        if bio:
            print(f"       {bio}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(flagged, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote {len(flagged)} accounts to {args.json}")

    if not (args.unfollow or args.remove_follower):
        print("\nDry run (no --unfollow/--remove-follower). Review, then act "
              "with --from-json.")
        return

    _act(client, flagged, args)


def _act(client, accounts, args):
    if not accounts:
        print("Nothing to act on.")
        return
    if not (args.unfollow or args.remove_follower):
        print("Specify --unfollow and/or --remove-follower.")
        return

    actions = []
    if args.unfollow:
        actions.append(("unfollow", unfollow))
    if args.remove_follower:
        actions.append(("remove-follower", remove_follower))

    verb = " + ".join(a[0] for a in actions)
    if not args.yes:
        ans = input(f"\n{verb} on {len(accounts)} accounts? Irreversible-ish. "
                    f"Type 'yes': ")
        if ans.strip().lower() != "yes":
            print("Aborted.")
            return

    ok = err = 0
    for a in accounts:
        for name, fn in actions:
            while True:
                status, info = fn(client, a["id"])
                if status == "ratelimit":
                    print(f"  rate limited, sleeping {info}s...")
                    time.sleep(info)
                    continue
                break
            if status == "ok":
                ok += 1
                print(f"  {name} @{a['screen_name']} ok")
            else:
                err += 1
                print(f"  {name} @{a['screen_name']} FAILED: {status} {info}")
            time.sleep(0.5)

    print(f"\nDone. {ok} actions ok, {err} failed.")


if __name__ == "__main__":
    main()
