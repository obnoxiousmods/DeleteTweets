# Managing following & followers

`manage_follows.py` scans your **following** or **followers** list, classifies
each account, and — after review — **unfollows** them and/or **removes them as
your follower**. Same review-first model as the tweet tool.

## Two independent actions

| Flag | Effect | API used |
| --- | --- | --- |
| `--unfollow` | You stop following the account | `POST 1.1/friendships/destroy.json` |
| `--remove-follower` | The account stops following **you** | GraphQL `RemoveFollower` |

You can pass either or both in one run. Removing a follower does **not** block
them; it just forces them off your followers list.

## Two classifiers

### `--mode egirl` (default)

Flags likely egirl / camgirl / adult-promo accounts using weighted signals on
the bio, display name, handle, and bio URL:

- **Strong (weight 2):** `onlyfans`, `fansly`, `camgirl`, `findom`, `nsfw`,
  `18+`, `🔞`, `sub to my`, `link in bio for`, `allmylinks`, etc.
- **Weak (weight 1):** `link in bio`, `dms open`, `spoil me`, `kitten`, `brat`,
  `goddess`, `daddy`, `🍑`, `🍆`, `💦`, `creator`, `model`, `telegram`, etc.
- **Name/handle (weight 1 each):** `onlyfans`, `🔞`, `egirl`, `baby`, `slut`,
  `vixen`, `bunny`, `spicy`, etc.
- **Link aggregator (+1):** linktr.ee / allmylinks / beacons / throne in the bio
  URL.

Flagged at total score **≥ 2**.

### `--mode junk`

Flags junk / spam / inactive accounts from profile stats:

- **No avatar** (default profile image): +2
- **Never posts** (`statuses_count == 0`): +2, or **< 10 posts**: +1
- **Empty bio**: +1
- **Zero followers**: +1
- **No interactions** (0 likes and few posts): +1
- **Follow-spam ratio** (follows > 1500 but < 5% follow back): +2
- **Default profile + low activity**: +1

Flagged at total score **≥ 3**.

### `--mode both`

Flags an account if it trips **either** classifier. Scores are summed in the
output.

## Mutual-status filter

Every account is labeled with its relationship to you:

- `mutual` — you follow each other
- `you→them` — you follow them, they don't follow back
- `they→you` — they follow you, you don't follow back
- `none` — neither (only appears with `--all`)

`--non-mutual` narrows the scan:

- with `--list following` → only accounts that **don't follow you back**
- with `--list followers` → only accounts **you don't follow back**

This is exactly the "I follow and they don't follow me" / "they follow me and
I don't follow them" cleanup.

## Workflow

```bash
# 1. Dry run — see what's flagged among accounts you follow:
python manage_follows.py --list following --mode both

# 2. Save for review (e.g. non-mutual junk you follow):
python manage_follows.py --list following --mode junk --non-mutual --json follows.json

# 3. Open follows.json, delete any account you want to KEEP.

# 4. Act on the rest — unfollow them:
python manage_follows.py --from-json follows.json --unfollow --yes

# Clean up junk followers (remove them as your follower):
python manage_follows.py --list followers --mode junk --json junkfollowers.json
python manage_follows.py --from-json junkfollowers.json --remove-follower --yes
```

## Flags

| Flag | Effect |
| --- | --- |
| `--list following\|followers` | Which relationship to scan |
| `--mode egirl\|junk\|both` | Which classifier(s) to apply (default `egirl`) |
| `--non-mutual` | Only non-mutual accounts (see above) |
| `--all` | Include every account, not just flagged |
| `--json FILE` | Write the flagged set for review |
| `--from-json FILE` | Act on a reviewed file (no re-scan) |
| `--unfollow` | Unfollow the accounts |
| `--remove-follower` | Remove the accounts as your follower |
| `--yes` | Skip the confirmation prompt |
| `--debug` | Per-page progress |

## Tuning

All keyword lists and thresholds are near the top of `manage_follows.py`
(`STRONG_BIO`, `WEAK_BIO`, `NAME_SIGNALS`, `THRESHOLD`, `JUNK_THRESHOLD`).
These heuristics **will** misfire on some legit accounts (e.g. a normal person
with a linktree, or a lurker who never posts). That's what review-first is for —
always scan to `--json`, read it, prune, then act.
