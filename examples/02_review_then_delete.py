"""
Example 02 — The recommended review-first workflow, as code.

Step 1 writes matches to a JSON file. You then open that file and remove any
entry you want to KEEP. Step 2 deletes whatever remains.

This mirrors:
    python delete_matching_tweets.py --json matches.json
    # (edit matches.json)
    python delete_matching_tweets.py --from-json matches.json --delete --yes

Run step 1:  python examples/02_review_then_delete.py scan
Run step 2:  python examples/02_review_then_delete.py delete
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import delete_matching_tweets as dt

OUT = Path(__file__).resolve().parent.parent / "matches.json"


def scan():
    cookies = dt.load_cookies()
    client = dt.make_client(cookies)
    match = dt.build_matcher()
    rest_id = dt.get_self_rest_id(client, cookies)

    matches = []
    for tw in dt.iter_own_tweets(client, rest_id, debug=True):
        hits = match(tw["text"])
        if hits:
            matches.append(dict(tw, hits=hits))

    OUT.write_text(json.dumps(matches, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"Wrote {len(matches)} matches to {OUT}")
    print("Open it, delete any entries you want to KEEP, then run: "
          "python examples/02_review_then_delete.py delete")


def delete():
    cookies = dt.load_cookies()
    client = dt.make_client(cookies)
    matches = json.loads(OUT.read_text(encoding="utf-8"))

    print(f"About to remove {len(matches)} items from {OUT}.")
    if input("Type 'yes' to proceed: ").strip().lower() != "yes":
        print("Aborted.")
        return

    ok = err = 0
    for tw in matches:
        status, info = dt.remove(client, tw)
        if status == "ok":
            ok += 1
            print(f"removed {tw['id']}")
        else:
            err += 1
            print(f"FAILED {tw['id']}: {status} {info}")
    print(f"Done. Removed {ok}, failed {err}.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    {"scan": scan, "delete": delete}.get(cmd, scan)()
