# Managing DM threads

`manage_dms.py` enumerates your Direct Message conversations, flags the ones
that look affection / sexual / relationship-flavored, and — after review —
**deletes the entire thread** from your side. Same review-first model as the
rest of the toolkit.

> ⚠️ Deleting a DM conversation removes the whole thread **from your inbox** and
> cannot be undone. (The other person may still have their copy.) Always review
> the flagged list before deleting.

## How a thread gets flagged

Each conversation is scored on two independent signals:

1. **Message content** — the combined message text is run through the same
   affection/sexual keyword matcher used by `delete_matching_tweets.py`
   (`WORD_KEYWORDS` + `PHRASE_KEYWORDS`). Any hit flags the thread and the
   matched keywords are shown.
2. **Who the other person is** — the other participant's profile is run through
   the egirl/camgirl/promo classifier from `manage_follows.py`. A high partner
   score flags the thread even if the text is tame.

A thread is flagged if **either** signal fires.

> **On "inter-gender":** X's API exposes no gender field, so gender can't be
> detected directly. This tool uses affectionate/sexual **content** plus an
> egirl/promo **partner** profile as the practical proxy. Review the results.

## Shallow vs. deep

- By default, classification uses the recent messages X returns in the inbox
  payload (fast, usually enough).
- `--deep` fetches the **full message history** of every conversation before
  classifying (more thorough, many more requests). Use it when you want to catch
  older threads whose recent messages are innocuous.

## Workflow

```bash
# 1. Dry run — list flagged threads:
python manage_dms.py --list

# 2. See every conversation with its top keywords:
python manage_dms.py --list --all

# 3. Thorough scan, saved for review:
python manage_dms.py --list --deep --json dms.json

# 4. Open dms.json and delete any thread you want to KEEP.

# 5. Delete the rest (whole threads):
python manage_dms.py --from-json dms.json --delete --yes
```

## Flags

| Flag | Effect |
| --- | --- |
| `--list` | Scan and classify conversations |
| `--deep` | Fetch full history per conversation (thorough) |
| `--all` | Include every conversation, not just flagged |
| `--json FILE` | Write flagged threads for review |
| `--from-json FILE` | Delete from a reviewed file (no re-scan) |
| `--delete` | Actually delete (default is dry run) |
| `--yes` | Skip the confirmation prompt |
| `--debug` | Inbox pagination progress |

## API notes

- Inbox: `GET 1.1/dm/inbox_initial_state.json`, paginated via
  `1.1/dm/inbox_timeline/{trusted,untrusted}.json`.
- Per-thread history: `GET 1.1/dm/conversation/{id}.json`.
- Delete thread: `POST 1.1/dm/conversation/{id}/delete.json`.

These are the legacy 1.1 DM endpoints the web client still uses; they are not
part of the GraphQL query-ID set, so they don't go stale the same way.
