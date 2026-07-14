# Examples

Runnable snippets that use the tool's internals. Run them from the **repo
root** so they can find `cookies.json` and import the main module.

| File | What it shows |
| --- | --- |
| [01_dry_run.py](01_dry_run.py) | Enumerate + match + print. Deletes nothing. The safest first run. |
| [02_review_then_delete.py](02_review_then_delete.py) | The review-first workflow in code: `scan` writes `matches.json`, you edit it, `delete` removes what's left. |

```bash
# from the repo root:
python examples/01_dry_run.py

python examples/02_review_then_delete.py scan
#   ... edit matches.json, remove anything to keep ...
python examples/02_review_then_delete.py delete
```

Prefer the CLI for day-to-day use — these exist to illustrate the moving parts:

```bash
python delete_matching_tweets.py --json matches.json      # scan + save
python delete_matching_tweets.py --from-json matches.json --delete --yes
```
