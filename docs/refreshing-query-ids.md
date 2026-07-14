# Refreshing the query IDs

X assigns each GraphQL operation a **query ID** (a persisted-query hash). These
rotate whenever X ships a new build of their web app. When an ID goes stale the
API returns **`404 Not Found`** for that operation. Here's how to get the
current IDs.

The three this tool uses:

```python
QID_USER_TWEETS    = "6r5OLCC_wFH4CpRyXKuAmQ"   # UserTweets
QID_DELETE_TWEET   = "nxpZCY2K-I6QoFHAHeojFQ"   # DeleteTweet
QID_DELETE_RETWEET = "ZyZigVsNiFO6v1dEks1eWg"   # DeleteRetweet
```

## Step 1 — find the current web bundle

Fetch your profile HTML with a logged-in session and look for the
`client-web` JavaScript bundles it references:

```bash
curl -s 'https://x.com/YOUR_HANDLE' \
  -H 'user-agent: Mozilla/5.0 ... Chrome/150.0.0.0 Safari/537.36' \
  -b 'auth_token=YOUR_AUTH_TOKEN; ct0=YOUR_CT0' \
  -o profile.html

grep -oE 'https://abs\.twimg\.com/responsive-web/client-web[^"]*\.js' profile.html | sort -u
```

You'll get a handful of URLs like:

```
https://abs.twimg.com/responsive-web/client-web/main.<hash>.js
https://abs.twimg.com/responsive-web/client-web/vendor.<hash>.js
```

The operation definitions live in `main.<hash>.js` (and sometimes lazy-loaded
chunks). Download it:

```bash
curl -s -o main.js https://abs.twimg.com/responsive-web/client-web/main.<hash>.js
```

## Step 2 — extract the query IDs

Each operation is registered in the bundle as an object literal that pairs a
`queryId` with an `operationName`:

```bash
grep -oE '\{queryId:"[A-Za-z0-9_-]+",operationName:"(UserTweets|DeleteTweet|DeleteRetweet)"' main.js | sort -u
```

Output looks like:

```
{queryId:"6r5OLCC_wFH4CpRyXKuAmQ",operationName:"UserTweets"
{queryId:"nxpZCY2K-I6QoFHAHeojFQ",operationName:"DeleteTweet"
{queryId:"ZyZigVsNiFO6v1dEks1eWg",operationName:"DeleteRetweet"
```

Copy the IDs into `delete_matching_tweets.py`.

> **Watch the pairing.** A loose grep can misalign `queryId` with the wrong
> `operationName`. Match the whole `{queryId:"...",operationName:"..."}` object
> as shown above so each ID is tied to its real operation.

## Step 3 — (optional) verify the bearer token

The public web bearer token is also in the bundle. It rarely changes, but to
confirm:

```bash
grep -oE 'AAAAAAAAA[A-Za-z0-9%_-]{80,}' main.js | sort -u | head
```

If it differs from `BEARER` in the script, update it (URL-decode `%3D` → `=`).

## Step 4 — sanity-check the operation

Confirm the new ID actually works before trusting it:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -G \
  "https://x.com/i/api/graphql/<NEW_ID>/UserTweets" \
  --data-urlencode 'variables={"userId":"<your id>","count":20,"includePromotedContent":false}' \
  --data-urlencode 'features={"responsive_web_graphql_timeline_navigation_enabled":true}' \
  -H 'authorization: Bearer <token>' \
  -H 'x-csrf-token: <ct0>' \
  -H 'x-twitter-active-user: yes' -H 'x-twitter-auth-type: OAuth2Session' \
  -b 'auth_token=<auth_token>; ct0=<ct0>'
```

`200` = good. `404` = wrong/stale ID. `400` = ID is fine but you're missing a
required feature flag (the body names it). `429` = rate limited, wait.

## Ops whose bundle ID 404s

A few operations (`UserTweetsAndReplies`, `Followers`) publish a persisted-query
hash in the main bundle that 404s against the API — the live hash lives in an
on-demand chunk that's out of sync with the metadata table. The tools work
around these:

- **Tweets:** `manage`/`delete_matching_tweets.py` uses `UserTweets` (Posts tab)
  instead of `UserTweetsAndReplies`.
- **Followers:** `manage_follows.py` falls back to the legacy
  `GET 1.1/followers/list.json` (cursor-paginated, full user objects incl.
  `following`/`followed_by` flags). `Following` still uses GraphQL.

If you want the GraphQL versions, capture the real hash from the network tab
while loading that exact page in a logged-in browser, then slot it in.
