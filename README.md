# DeleteTweets

A small toolkit for cleaning up **your own** X (Twitter) account — talking
directly to X's internal GraphQL / 1.1 APIs using your browser session cookies.
No developer account, no API keys, no paid tier.

Every tool follows the same **review-first** model: scan, classify, write the
matches to a file you read and prune, then act on what's left. Nothing is
removed until you confirm.

## The tools

| Script | What it does |
| --- | --- |
| [`delete_matching_tweets.py`](delete_matching_tweets.py) | Enumerate your posts and delete the ones matching a keyword set (originals + reposts). → [docs](docs/keywords.md) |
| [`manage_follows.py`](manage_follows.py) | Scan following/followers, flag egirl/camgirl/promo **or** junk/spam/inactive/non-mutual accounts, then unfollow / remove-follower. → [docs](docs/managing-follows.md) |
| [`manage_dms.py`](manage_dms.py) | Enumerate DM threads, flag affection/sexual ones (by content + partner profile), then delete whole threads. → [docs](docs/managing-dms.md) |

> ⚠️ **These actions are permanent.** There is no undo, no trash, no recycle
> bin. Each tool defaults to a **dry run** and makes you review the exact list
> before anything is removed. Keep it that way until you're sure.

The rest of this README focuses on the tweet tool; the follows and DM tools work
the same way and are documented in [docs/](docs/).

---

## Table of contents

- [How it works](#how-it-works)
- [Safety model](#safety-model)
- [Install](#install)
- [Get your cookies](#get-your-cookies)
- [Quick start](#quick-start)
- [The review-first workflow (recommended)](#the-review-first-workflow-recommended)
- [Command reference](#command-reference)
- [Customizing keywords](#customizing-keywords)
- [Retweets vs. original tweets](#retweets-vs-original-tweets)
- [Rate limits](#rate-limits)
- [Refreshing the query IDs](#refreshing-the-query-ids)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [More docs](#more-docs)
- [Legal / disclaimer](#legal--disclaimer)

---

## How it works

X's website is a single-page app that talks to a private GraphQL API at
`https://x.com/i/api/graphql/<queryId>/<OperationName>`. Every action the web
client can take — loading your posts, deleting a tweet, undoing a retweet — is
one of these operations. Each is identified by a **query ID** (a persisted-query
hash) that changes whenever X ships a new build of their web bundle.

This tool uses three operations:

| Operation        | Purpose                                        |
| ---------------- | ---------------------------------------------- |
| `UserTweets`     | Paginate through your Posts tab (originals + reposts) |
| `DeleteTweet`    | Delete one of your original tweets             |
| `DeleteRetweet`  | Undo a repost (un-retweet the original)        |

Authentication is just your logged-in browser session: the `auth_token` and
`ct0` cookies, plus the `ct0` value echoed back as the `x-csrf-token` header.
That's exactly what your browser sends, so from X's side the requests are
indistinguishable from you clicking around the site.

The flow:

```
cookies.json ──► authenticate ──► UserTweets (paginate) ──► keyword filter
                                                                   │
                                          matches.json ◄───────────┘
                                                 │
                                    (you review the list)
                                                 │
                                                 ▼
                       DeleteTweet / DeleteRetweet  (one call per match)
```

For a deeper dive see [docs/how-it-works.md](docs/how-it-works.md).

## Safety model

Because this is irreversible, the tool is built to make an accidental mass
delete hard:

1. **Dry run by default.** Running with no flags only *lists* matches. Nothing
   is deleted unless you pass `--delete`.
2. **Explicit confirmation.** Even with `--delete`, it prompts you to type
   `yes` unless you also pass `--yes`.
3. **Review-first.** `--json matches.json` writes the full match list to a file
   you can open and read. `--from-json matches.json` then deletes *exactly*
   that reviewed list — no re-scanning, no surprises.
4. **Secrets stay local.** `cookies.json` and `matches.json` are in
   `.gitignore`. Never commit them.

## Install

Requires **Python 3.9+**.

```bash
git clone https://github.com/obnoxiousmods/DeleteTweets
cd DeleteTweets
pip install -r requirements.txt
```

## Get your cookies

You need two cookie values from a logged-in x.com session: `auth_token` and
`ct0`.

1. Log in to <https://x.com> in your browser.
2. Open DevTools (`F12`) → **Application** (Chrome) or **Storage** (Firefox) →
   **Cookies** → `https://x.com`.
3. Copy the **Value** of `auth_token` and `ct0`.
4. Copy `cookies.example.json` to `cookies.json` and paste them in:

```bash
cp cookies.example.json cookies.json
```

```json
{
  "auth_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "ct0": "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy...",
  "twid": "u=1234567890",
  "lang": "en"
}
```

`twid` (your numeric user ID, shown as `u=<digits>`) is optional but
recommended — the tool reads it to know which account to scan. If it's missing,
the tool can't determine your ID.

Full walkthrough with screenshots-in-words: [docs/getting-cookies.md](docs/getting-cookies.md).

> 🔐 Your `auth_token` is a full login credential. Anyone who has it **is** you
> on X. Never paste it into a website, never commit it, never share it.

## Quick start

```bash
# 1. Dry run — list everything that matches, delete nothing:
python delete_matching_tweets.py

# 2. Same, but also save the match list for review:
python delete_matching_tweets.py --json matches.json

# 3. Open matches.json, read it, delete anything you want to KEEP from the file.

# 4. Delete exactly what's left in the file:
python delete_matching_tweets.py --from-json matches.json --delete --yes
```

## The review-first workflow (recommended)

Because a full scan of a large account uses most of one rate-limit window
(see [Rate limits](#rate-limits)), the intended pattern is **scan once, review,
then delete from the saved file:**

```bash
# Step 1 — enumerate + filter, write the list, delete nothing (dry run).
python delete_matching_tweets.py --json matches.json --debug
```

`matches.json` now contains an array like:

```json
[
  {
    "id": "1737283910000000001",
    "screen_name": "yourhandle",
    "text": "i miss alyssa so much ❤",
    "is_retweet": false,
    "source_id": null,
    "hits": ["alyssa", "miss", "❤", "i miss"]
  }
]
```

```bash
# Step 2 — open matches.json and DELETE any object you want to KEEP.
#          Whatever remains is what will be removed. Then:
python delete_matching_tweets.py --from-json matches.json --delete --yes
```

`--from-json` skips enumeration entirely (so it doesn't touch the read rate
limit) and removes each item — routing originals to `DeleteTweet` and reposts to
`DeleteRetweet` automatically.

## Command reference

| Flag             | Effect                                                                 |
| ---------------- | ---------------------------------------------------------------------- |
| *(none)*         | Dry run: scan, filter, print matches. Deletes nothing.                 |
| `--json FILE`    | Also write matches to `FILE` (for review / `--from-json`).             |
| `--from-json FILE` | Skip scanning; load `FILE` and act on it. Pairs with `--delete`.     |
| `--delete`       | Actually delete. Without it, everything is a dry run.                   |
| `--yes`          | Skip the interactive "type yes" confirmation.                          |
| `--no-retweets`  | Ignore reposts; only consider your original tweets.                    |
| `--show-all`     | Print every scanned tweet with its match flag (verbose).               |
| `--debug`        | Print per-page pagination + rate-limit progress.                       |

Examples:

```bash
# Preview, originals only, verbose:
python delete_matching_tweets.py --no-retweets --show-all

# One-shot scan-and-delete with confirmation prompt (no review file):
python delete_matching_tweets.py --delete

# Scan-and-delete everything matching, no prompt (careful!):
python delete_matching_tweets.py --delete --yes
```

## Customizing keywords

Keywords live at the top of `delete_matching_tweets.py` in two lists:

- **`WORD_KEYWORDS`** — matched on **word boundaries**, so `"her"` matches the
  word *her* but not *there* / *other* / *where*. Case-insensitive.
- **`PHRASE_KEYWORDS`** — matched as **substrings**, for multi-word phrases and
  emoji (`"i miss"`, `"love you"`, `"❤"`, `"🥰"`). Case-insensitive.

Edit those lists to fit your situation. A match on **any** keyword flags the
tweet. See [docs/keywords.md](docs/keywords.md) for tips on avoiding false
positives (e.g. broad words like `her`, `she`, `need`, `fuck` will match a lot
of unrelated posts — that's why review-first exists).

## Retweets vs. original tweets

The Posts tab (`UserTweets`) returns both your original tweets and your
reposts. They are removed differently:

- **Original tweet** → `DeleteTweet` with the tweet's own ID.
- **Repost** → `DeleteRetweet` with the *original* tweet's ID (`source_id`).

The tool detects which is which (via the `retweeted_status_result` field) and
routes each item correctly. Pass `--no-retweets` to leave reposts alone.

## Rate limits

`UserTweets` is limited to roughly **50 requests per 15-minute window**, and
each page holds ~20 tweets. So an account with ~800 posts costs ~40 requests —
about one full scan per window. The tool reads the `x-rate-limit-*` response
headers and, if it hits `429`, **sleeps until the reset time** and resumes
automatically.

This is the main reason to scan once into `matches.json` and then delete with
`--from-json`: deletion uses `DeleteTweet` / `DeleteRetweet`, which have their
own separate budgets, so you don't spend read quota re-scanning.

## Refreshing the query IDs

Query IDs are pinned near the top of the script:

```python
QID_USER_TWEETS    = "6r5OLCC_wFH4CpRyXKuAmQ"
QID_DELETE_TWEET   = "nxpZCY2K-I6QoFHAHeojFQ"
QID_DELETE_RETWEET = "ZyZigVsNiFO6v1dEks1eWg"
```

X rotates these when they ship a new web build. If you start getting `404`
errors on an operation, the ID is stale. Grab the current ones from the live
web bundle — full procedure in
[docs/refreshing-query-ids.md](docs/refreshing-query-ids.md).

## Troubleshooting

| Symptom                              | Cause / fix                                                       |
| ------------------------------------ | ---------------------------------------------------------------- |
| `404 Not Found` on an operation      | Query ID is stale — [refresh it](docs/refreshing-query-ids.md).  |
| `401` / `403`                        | Cookies expired or wrong. Re-copy `auth_token` + `ct0`.          |
| `Could not determine your user id`   | Add `twid` (`u=<digits>`) to `cookies.json`.                     |
| `429` and it just sits there         | Expected — it's sleeping until the rate-limit reset. Let it run. |
| Emoji crash on Windows               | The script forces UTF-8 output; use an up-to-date Python 3.9+.   |
| Matched way too much                 | Your keyword net is too broad — tighten it, use review-first.    |

## FAQ

**Does this work on protected/private accounts?** Yes — it uses your own
session, so it sees exactly what you see.

**Will it delete replies?** `UserTweets` covers the Posts tab (originals +
reposts). Standalone replies to other people aren't enumerated by this
operation. See [docs/how-it-works.md](docs/how-it-works.md#what-about-replies).

**Can I run it on someone else's account?** No — deletion requires being logged
in as the account owner. It only ever acts on *your* authenticated session.

**Is my password involved?** No. Only cookies. The tool never sees or needs your
password.

## More docs

- [docs/how-it-works.md](docs/how-it-works.md) — the API, pagination, response shape
- [docs/getting-cookies.md](docs/getting-cookies.md) — extracting `auth_token` / `ct0`
- [docs/keywords.md](docs/keywords.md) — designing a keyword set, avoiding false positives
- [docs/managing-follows.md](docs/managing-follows.md) — following/followers cleanup (egirl + junk + non-mutual)
- [docs/managing-dms.md](docs/managing-dms.md) — DM thread cleanup
- [docs/refreshing-query-ids.md](docs/refreshing-query-ids.md) — updating stale query IDs
- [examples/](examples/) — runnable snippets

## Legal / disclaimer

This tool automates actions **on your own account** that you can already perform
by hand in the X web app. It is intended for managing your own content. Using
X's private API and automating actions may be contrary to the X Terms of
Service; you use this at your own risk. The authors take no responsibility for
suspended accounts, deleted data you wanted to keep, or any other consequences.
**There is no undo — always review before you delete.**
