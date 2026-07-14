# Getting your cookies

The tool authenticates as you using two cookies from a logged-in x.com session:
`auth_token` and `ct0`. Here's how to grab them.

> 🔐 **`auth_token` is a full login credential.** Anyone who holds it is logged
> in as you. Treat it like a password: don't paste it into websites, don't
> commit it, don't share it. Keep it only in your local `cookies.json` (which is
> gitignored).

## Chrome / Edge / Brave

1. Log in to <https://x.com>.
2. Press `F12` to open DevTools.
3. Go to the **Application** tab.
4. In the left sidebar: **Storage → Cookies → `https://x.com`**.
5. Find these rows and copy their **Value** column:
   - `auth_token`
   - `ct0`
   - `twid` (looks like `u%3D1234567890` — the digits after `u=` are your user
     ID; URL-decoding `%3D` gives `=`)

## Firefox

1. Log in to <https://x.com>.
2. Press `F12` → **Storage** tab.
3. **Cookies → `https://x.com`**.
4. Copy the values of `auth_token`, `ct0`, and `twid`.

## Alternative: copy as cURL

Some people find it easiest to:

1. Open DevTools → **Network** tab.
2. Reload your profile page.
3. Right-click any request to `x.com` → **Copy → Copy as cURL**.
4. The `-b '...'` / `-H 'cookie: ...'` chunk contains all your cookies; pull
   `auth_token`, `ct0`, and `twid` out of it.

## Fill in cookies.json

```bash
cp cookies.example.json cookies.json
```

```json
{
  "auth_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "ct0": "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy...",
  "twid": "u=1234567890",
  "lang": "en"
}
```

Notes:

- `auth_token` is 40 hex characters.
- `ct0` is long (100+ characters). Copy the whole thing.
- `twid` is optional but recommended. If present it must be `u=<digits>`; the
  tool extracts the digits as your user ID. If omitted, the tool can't figure
  out which account to scan and will exit with
  `Could not determine your user id`.
- If you copied a URL-encoded `twid` like `u%3D1234567890`, decode it to
  `u=1234567890`.

## When cookies expire

Sessions don't last forever. If you start getting `401`/`403` errors, log in
again in your browser, re-copy `auth_token` and `ct0`, and update
`cookies.json`. Logging out of X in the browser invalidates the token.
