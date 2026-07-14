"""
Example 01 — Dry run: enumerate and print matches, delete nothing.

This is the safest way to see what the tool would act on. It imports the
enumeration + matching logic directly instead of shelling out, so you can see
how the pieces fit together.

Run:  python examples/01_dry_run.py
(Expects ../cookies.json relative to the repo root, i.e. run from repo root.)
"""

import sys
from pathlib import Path

# Make the top-level module importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import delete_matching_tweets as dt


def main():
    cookies = dt.load_cookies()
    client = dt.make_client(cookies)
    match = dt.build_matcher()
    rest_id = dt.get_self_rest_id(client, cookies)

    print(f"Scanning user {rest_id} ...")
    total = matched = 0
    for tw in dt.iter_own_tweets(client, rest_id, debug=True):
        total += 1
        hits = match(tw["text"])
        if hits:
            matched += 1
            kind = "RT" if tw["is_retweet"] else "  "
            preview = tw["text"].replace("\n", " ")[:100]
            print(f"[{kind}] {tw['id']} ({', '.join(hits)}) :: {preview}")

    print(f"\n{matched}/{total} tweets matched. Nothing was deleted (dry run).")


if __name__ == "__main__":
    main()
