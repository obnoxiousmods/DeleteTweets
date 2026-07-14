# How it works

This document explains what happens under the hood when you run
`delete_matching_tweets.py`.

## The private GraphQL API

X's web client (the react app at x.com) is powered by an internal GraphQL API:

```
https://x.com/i/api/graphql/<queryId>/<OperationName>
```

- **`OperationName`** is a human-readable name like `UserTweets` or
  `DeleteTweet`.
- **`queryId`** is a *persisted query hash* — a short opaque string that X's
  servers map to a specific stored GraphQL document. It changes every time X
  ships a new build of the web app.

Reads (`UserTweets`) are `GET` requests with two URL-encoded query params:

- `variables` — JSON: which user, page size, pagination cursor, etc.
- `features` — JSON: a big bag of feature flags the server requires. If a
  required flag is missing you get a `400` telling you which one.

Writes (`DeleteTweet`, `DeleteRetweet`) are `POST` requests with a JSON body:

```json
{ "variables": { "tweet_id": "123", "dark_request": false }, "queryId": "..." }
```

## Authentication

There is no OAuth dance here. The tool reuses your **logged-in browser
session**:

- Cookie `auth_token` — your session credential.
- Cookie `ct0` — the CSRF token.
- Header `x-csrf-token` — must equal the `ct0` cookie.
- Header `authorization: Bearer <token>` — a **public** bearer token hardcoded
  into X's web bundle (the same for every user; it just identifies the web
  client). It is included in the script.

Because these are exactly what your browser sends, the requests look like normal
web-client traffic.

## Enumerating your tweets

`UserTweets` returns your Posts tab in pages. Each response is a deeply nested
"timeline" structure containing `instructions`, which contain `entries`. Two
entry shapes matter:

- **`TimelineTimelineItem`** — a single tweet.
- **`TimelineTimelineModule`** — a group (e.g. a self-thread) holding several
  tweets.
- A special **cursor entry** (`entryId` starting with `cursor-bottom-`) carries
  the token for the next page.

The tool walks `instructions → entries`, pulls the tweet out of each item, and
records the bottom cursor. It then requests the next page with that cursor and
repeats until the cursor stops advancing or a page yields no new tweets.

### The tweet object

For each tweet the useful fields are:

- `rest_id` — the tweet's ID.
- `legacy.full_text` — the tweet text (for long "note tweets" the real text is
  under `note_tweet.note_tweet_results.result.text`).
- `legacy.retweeted_status_result` — **present only for reposts**; its
  `result.rest_id` is the *original* tweet's ID.
- `core.user_results.result...screen_name` — the author handle.

## Keyword matching

Each tweet's text is tested against two keyword lists:

- **Word keywords** via a single compiled regex with `\b` word boundaries, so
  short words don't match inside longer ones (`her` ≠ `there`).
- **Phrase keywords** via case-insensitive substring search, for multi-word
  phrases and emoji.

A tweet matches if it hits **any** keyword. The set of hit keywords is recorded
so you can see *why* each tweet was flagged.

## Deleting

- **Original tweet** → `POST DeleteTweet` with `tweet_id = rest_id`.
- **Repost** → `POST DeleteRetweet` with `source_tweet_id = ` the original
  tweet's ID (from `retweeted_status_result`). Deleting a repost is really
  "undo retweet", which is why it needs the *original* ID, not the repost's.

The tool inspects each match's `is_retweet` / `source_id` and calls the right
operation automatically.

## What about replies?

`UserTweets` is the **Posts** tab: your original tweets and your reposts. It
does **not** include standalone replies you made to other people's tweets — the
X web app fetches those through a different operation
(`UserTweetsAndReplies`). At the time of writing, the `UserTweetsAndReplies`
query ID published in the web bundle returns `404` against the API host (its
hash lives in an out-of-sync lazy-loaded chunk), so this tool sticks to
`UserTweets`. If you need to sweep replies too, refresh a working
`UserTweetsAndReplies` query ID (see
[refreshing-query-ids.md](refreshing-query-ids.md)) and add it as a second
enumeration source.

## Rate limiting

Every response carries `x-rate-limit-limit`, `x-rate-limit-remaining`, and
`x-rate-limit-reset` (a Unix timestamp). `UserTweets` allows ~50 requests per
15-minute window. On a `429`, the tool computes `reset - now` and sleeps that
long before retrying, so a large account scans across multiple windows without
intervention.
