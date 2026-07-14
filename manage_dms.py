"""
Enumerate your DM conversations, flag the ones that are affection / sexual /
relationship-flavored (by message content and/or who the other person is), and
— after review — delete the entire thread.

Same review-first concept as the rest of the toolkit. It uses X's 1.1 DM API
with your session cookies.

Signals a conversation is flagged on:
  * message text matches the affection/sexual keyword set (reused from
    delete_matching_tweets.py), and/or
  * the other participant's profile trips the egirl/camgirl/promo classifier
    (reused from manage_follows.py).

Usage:
    # List flagged conversations (dry run):
    python manage_dms.py --list

    # Show every conversation with its top message keywords:
    python manage_dms.py --list --all

    # Save flagged set for review:
    python manage_dms.py --list --json dms.json

    # Review dms.json (remove threads you want to KEEP), then delete the rest:
    python manage_dms.py --from-json dms.json --delete --yes

NOTE: X exposes no gender field, so "inter-gender" can't be detected directly.
This flags by affectionate/sexual *content* and by egirl/promo *partner*, which
is the closest reliable proxy. Review before deleting — deletion removes the
whole thread from your side and cannot be undone.

Cookies come from cookies.json (auth_token + ct0), same as the other tools.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import delete_matching_tweets as dt      # reuse the keyword matcher
import manage_follows as mf              # reuse cookies/client + egirl classifier

HERE = Path(__file__).parent
COOKIES_FILE = HERE / "cookies.json"
API = "https://x.com/i/api/1.1/dm"


def get_json(client, url, params=None):
    while True:
        r = client.get(url, params=params)
        if r.status_code == 429:
            reset = int(r.headers.get("x-rate-limit-reset", time.time() + 60))
            wait = max(1, reset - int(time.time()))
            print(f"  rate limited, sleeping {wait}s...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()


def fetch_inbox(client, debug=False):
    """Return (conversations, users, messages_by_conv) across the whole inbox."""
    conversations = {}
    users = {}
    messages = {}   # conversation_id -> list[str]

    def absorb(state):
        conversations.update(state.get("conversations", {}) or {})
        users.update(state.get("users", {}) or {})
        for e in state.get("entries", []) or []:
            msg = e.get("message")
            if not msg:
                continue
            cid = msg.get("conversation_id")
            text = msg.get("message_data", {}).get("text")
            if cid and text:
                messages.setdefault(cid, []).append(text)

    init = get_json(client, f"{API}/inbox_initial_state.json", {
        "include_conversation_info": "true",
        "include_groups": "true",
        "filter_low_quality": "false",
        "nsfw_filtering_enabled": "false",
        "dm_users": "false",
    })
    state = init.get("inbox_initial_state", init)
    absorb(state)
    if debug:
        print(f"  initial: {len(conversations)} convs, {len(messages)} with text")

    # Paginate both inbox timelines (trusted + untrusted/low-quality).
    for kind in ("trusted", "untrusted"):
        cursor = state.get("inbox_timelines", {}).get(kind, {}).get("min_entry_id")
        while cursor:
            page = get_json(client, f"{API}/inbox_timeline/{kind}.json", {
                "max_id": cursor,
                "include_conversation_info": "true",
                "include_groups": "true",
                "filter_low_quality": "false",
                "nsfw_filtering_enabled": "false",
            })
            tl = page.get("inbox_timeline", page)
            absorb(tl)
            new_cursor = tl.get("min_entry_id")
            status = tl.get("status")
            if debug:
                print(f"  {kind}: cursor={cursor} status={status} "
                      f"total_convs={len(conversations)}")
            if not new_cursor or new_cursor == cursor or status == "AT_END":
                break
            cursor = new_cursor

    return conversations, users, messages


def fetch_conversation_text(client, conv_id, debug=False):
    """Pull the full message history text for one conversation."""
    texts = []
    max_id = None
    pages = 0
    while True:
        params = {
            "context": "FETCH_DM_CONVERSATION",
            "include_conversation_info": "true",
        }
        if max_id:
            params["max_id"] = max_id
        data = get_json(client, f"{API}/conversation/{conv_id}.json", params)
        conv = data.get("conversation_timeline", data)
        entries = conv.get("entries", []) or []
        min_id = None
        for e in entries:
            msg = e.get("message")
            if msg:
                t = msg.get("message_data", {}).get("text")
                if t:
                    texts.append(t)
            eid = (e.get("message") or e.get("conversation_read_marker")
                   or {}).get("id")
            if eid:
                eid = int(eid)
                min_id = eid if min_id is None else min(min_id, eid)
        pages += 1
        status = conv.get("status")
        if not entries or status == "AT_END" or not min_id or pages > 40:
            break
        max_id = str(min_id)
    if debug:
        print(f"    {conv_id}: {len(texts)} messages")
    return texts


def delete_conversation(client, conv_id):
    r = client.post(
        f"{API}/conversation/{conv_id}/delete.json",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    if r.status_code == 429:
        reset = int(r.headers.get("x-rate-limit-reset", time.time() + 60))
        return "ratelimit", max(1, reset - int(time.time()))
    if r.status_code not in (200, 204):
        return "http_error", f"{r.status_code} {r.text[:180]}"
    return "ok", None


def partner_account(conv, users, self_id):
    """Build an account dict for the OTHER participant (for egirl scoring)."""
    for p in conv.get("participants", []):
        uid = p.get("user_id")
        if uid and uid != self_id:
            u = users.get(uid, {})
            url = ""
            urls = u.get("entities", {}).get("url", {}).get("urls", [])
            if urls:
                url = urls[0].get("expanded_url") or ""
            return {
                "id": uid,
                "screen_name": u.get("screen_name"),
                "name": u.get("name"),
                "description": u.get("description", ""),
                "url": url,
            }
    return None


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(
        description="Flag and delete affection/sexual DM threads.")
    ap.add_argument("--list", action="store_true", help="scan and classify")
    ap.add_argument("--deep", action="store_true",
                    help="fetch full message history per conversation "
                         "(more thorough, more requests)")
    ap.add_argument("--all", action="store_true",
                    help="include every conversation, not just flagged")
    ap.add_argument("--json", default=None, help="write flagged set for review")
    ap.add_argument("--from-json", default=None,
                    help="delete from a reviewed JSON file (no re-scan)")
    ap.add_argument("--delete", action="store_true", help="actually delete")
    ap.add_argument("--yes", action="store_true", help="skip confirmation")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    cookies = mf.load_cookies()
    client = mf.make_client(cookies)

    if args.from_json:
        flagged = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        print(f"Loaded {len(flagged)} reviewed threads from {args.from_json}")
        _delete(client, flagged, args)
        return

    if not args.list:
        sys.exit("Pass --list (or --from-json FILE).")

    self_id = mf.get_self_rest_id(cookies)
    match = dt.build_matcher()
    egirl = mf.build_classifier()

    print("Fetching DM inbox ...")
    conversations, users, messages = fetch_inbox(client, debug=args.debug)
    print(f"Found {len(conversations)} conversations.\n")

    flagged = []
    for cid, conv in conversations.items():
        partner = partner_account(conv, users, self_id)

        texts = messages.get(cid, [])
        if args.deep:
            texts = fetch_conversation_text(client, cid, debug=args.debug) or texts
        blob = "\n".join(texts)

        content_hits = match(blob)
        e_score, e_reasons = egirl(partner) if partner else (0, [])
        hit = bool(content_hits) or e_score >= mf.THRESHOLD

        if args.all or hit:
            reasons = []
            if content_hits:
                reasons.append("content:" + ",".join(content_hits[:8]))
            if e_score >= mf.THRESHOLD:
                reasons.append(f"partner-egirl({e_score}):" + ",".join(e_reasons[:4]))
            flagged.append({
                "conversation_id": cid,
                "type": conv.get("type"),
                "partner": partner,
                "message_count": len(texts),
                "content_hits": content_hits,
                "partner_egirl_score": e_score,
                "reasons": reasons,
            })

    flagged.sort(key=lambda c: len(c["content_hits"]) + c["partner_egirl_score"],
                 reverse=True)
    label = "conversations" if args.all else "flagged"
    print(f"{len(flagged)} {label}:\n")
    for c in flagged:
        p = c["partner"] or {}
        print(f"  {c['conversation_id']}  @{p.get('screen_name','?')} "
              f"({c['message_count']} msgs)")
        for r in c["reasons"]:
            print(f"       {r}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(flagged, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nWrote {len(flagged)} threads to {args.json}")

    if not args.delete:
        print("\nDry run (no --delete). Review, then delete with --from-json.")
        return

    _delete(client, flagged, args)


def _delete(client, threads, args):
    if not threads:
        print("Nothing to delete.")
        return
    if not args.delete:
        print("Pass --delete to actually remove these threads.")
        return
    if not args.yes:
        ans = input(f"\nDelete {len(threads)} entire DM threads? This removes "
                    f"them from your inbox and cannot be undone. Type 'yes': ")
        if ans.strip().lower() != "yes":
            print("Aborted.")
            return

    ok = err = 0
    for c in threads:
        cid = c["conversation_id"]
        while True:
            status, info = delete_conversation(client, cid)
            if status == "ratelimit":
                print(f"  rate limited, sleeping {info}s...")
                time.sleep(info)
                continue
            break
        if status == "ok":
            ok += 1
            print(f"  deleted {cid}")
        else:
            err += 1
            print(f"  FAILED {cid}: {status} {info}")
        time.sleep(0.5)

    print(f"\nDone. Deleted {ok}, failed {err}.")


if __name__ == "__main__":
    main()
