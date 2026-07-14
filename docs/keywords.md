# Designing your keyword set

Matching is only as good as your keyword list. This doc covers how the two lists
behave and how to avoid nuking posts you meant to keep.

## The two lists

At the top of `delete_matching_tweets.py`:

### `WORD_KEYWORDS` — word-boundary matches

Compiled into one regex with `\b...\b` around the alternation. Matches whole
words only, case-insensitive:

- `"her"` matches *her* — but **not** *there*, *other*, *where*, *herd*.
- `"love"` matches *love* — but **not** *clover* or *glove*.

Good for single words where you want the word itself, not any string containing
it.

### `PHRASE_KEYWORDS` — substring matches

Plain case-insensitive `in` checks. Matches anywhere, including inside other
text:

- `"i miss"` matches *i miss*, *i missed*, *…and i miss her…*
- `"❤"` matches any tweet containing that emoji.

Good for multi-word phrases and emoji, where word boundaries don't apply.

A tweet is flagged if it hits **any** keyword in **either** list. The matched
keywords are recorded in each result's `hits` field so you can see why.

## Broad vs. tight

There's a real tradeoff:

| | Broad net (`her`, `she`, `need`, `fuck`, `miss`, `girl`...) | Tight net (`babe`, `i love you`, `my girl`, `alyssa`, 🥰) |
| --- | --- | --- |
| Catches | almost everything relevant, plus lots that isn't | mostly the posts you actually mean |
| False positives | many — news, memes, venting, jokes | few |
| Best paired with | **review-first** (`--json` then edit then `--from-json`) | can be run more directly |

Very common words will match a large fraction of an active account. For example
`fuck` and `need` appear in tons of everyday tweets that have nothing to do with
your target. **If you use a broad net, always review-first** — scan into
`matches.json`, open it, and delete the objects you want to keep before running
`--from-json`.

## Reducing false positives

- Prefer **specific phrases** over bare words: `"my girl"`, `"i miss you"`,
  `"love you"` instead of `girl`, `miss`, `love`.
- Add the **specific name(s)** involved — a name is the highest-signal keyword
  you have.
- Move risky broad words to their own run so you can review them in isolation.
- Use `--no-retweets` if the person's name only appears because you reposted
  others, not in your own words.
- Use `--show-all` to eyeball how a keyword behaves across your whole timeline
  before committing.

## Example: layered approach

```bash
# Pass 1 — high-confidence terms, review, delete.
#   (edit the lists down to names + unambiguous phrases first)
python delete_matching_tweets.py --json pass1.json
#   review pass1.json, then:
python delete_matching_tweets.py --from-json pass1.json --delete --yes

# Pass 2 — broaden the lists, review much more carefully.
python delete_matching_tweets.py --json pass2.json
#   carefully prune pass2.json, then:
python delete_matching_tweets.py --from-json pass2.json --delete --yes
```

## Matching caveats

- Matching is **case-insensitive** but otherwise literal — no stemming. Add
  each inflection you care about (`love`, `loved`, `loving`, `loves`).
- Accented / stylized unicode variants (e.g. fancy fonts) won't match plain
  ASCII keywords.
- Emoji skin-tone / ZWJ variants may differ from a bare emoji; add the specific
  form you use.
