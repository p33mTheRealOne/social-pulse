# social-pulse

social-pulse takes a link to a public TikTok, Instagram, Facebook, X or YouTube post and prints its likes, comments, reposts, shares, saves and views. You can run it in the terminal or as a small HTTP API.

It does not drive a browser and it does not need developer API keys. It sends plain HTTP requests with a Chrome-like TLS fingerprint, reads the numbers from the page data, and falls back to yt-dlp when a page will not parse. Every platform comes back in the same format, and you can ask for only the fields you want.

The pages and endpoints it reads are undocumented and change without warning, so it will break now and then. The [limitations](#limitations) section lists what to expect.

## What you get from each platform

A `-` in the table output (and `null` in JSON) means the platform did not provide that number. It does not mean zero.

| Platform | Supported links | Likes | Comments | Reposts | Shares | Saves | Views | Cookies needed? |
|---|---|---|---|---|---|---|---|---|
| TikTok | video links, `vm.tiktok.com` short links | yes | yes | yes | yes | yes | yes | no |
| X (Twitter) | `x.com` and `twitter.com` status links | yes | yes (replies) | yes | n/a | yes (bookmarks) | yes | no |
| Instagram | reels and posts | yes | yes | with cookies | with cookies | n/a | with cookies (the app's play count) | for reposts, shares and views |
| Facebook | reels, videos, public posts | yes (all reactions) | yes | n/a | yes | n/a | videos only | not for public videos; plain posts usually |
| YouTube | videos, Shorts, `youtu.be` links | yes | yes (exact count) | n/a | n/a | n/a | yes | no, unless YouTube asks you to sign in |

On 2026-11-15 I compared the output with the apps for a TikTok video, an X post, a YouTube video and Short, a Facebook reel and post, and an Instagram reel. The Facebook post and the Instagram reel were fetched with cookies. Instagram photo and carousel posts, and Facebook posts without cookies, are untested.

## Install

You need Python 3.11 or newer. It is not on PyPI yet, so install from a clone.

macOS and Linux:

    git clone https://github.com/YOUR-USERNAME/social-pulse.git
    cd social-pulse
    python3 -m venv venv
    source venv/bin/activate
    pip install -e .

Windows (cmd):

    git clone https://github.com/YOUR-USERNAME/social-pulse.git
    cd social-pulse
    python -m venv venv
    venv\Scripts\activate
    pip install -e .

For the HTTP API, install with `pip install -e ".[api]"` instead. Platforms change often, so update the two libraries that do the fetching every so often:

    pip install -U yt-dlp curl_cffi

## Quick start

Put the link in double quotes. Links usually contain `&`, and without quotes your shell cuts the command at the first one.

    social-pulse "https://www.tiktok.com/@noimpurity/video/7687658250057075990"

The output looks like this (the numbers here are placeholders):

    +----------------------------------------------------------------------------+
    | Platform | Author   | Likes  | Comments | Reposts | Shares | Saves | Views  |
    | tiktok   | someuser | 10,500 | 315      | 0       | 1,755  | 1,386 | 26,700 |
    +----------------------------------------------------------------------------+

A link copied straight from the browser works too, tracking parameters included:

    social-pulse "https://www.tiktok.com/@noimpurity/video/7687658250057075990?is_from_webapp=1&sender_device=pc"

For TikTok, Instagram and X the query string is dropped before anything is fetched.

To get only some fields, as JSON:

    social-pulse "https://www.tiktok.com/@noimpurity/video/7687658250057075990" --fields likes,saves --json

To process a list of links and save a CSV (the file format is described under [links file](#links-file)):

    social-pulse --file links.txt -o report.csv

## Command reference

    social-pulse [URL] [options]

| Option | What it does |
|---|---|
| `URL` | One post or video link. Optional when you use `--file`. |
| `--file`, `-f FILE` | Text file with one link per line. |
| `--fields`, `-F LIST` | Comma-separated list from `author,likes,comments,reposts,shares,saves,views`. Default is all of them. Aliases: `bookmarks` for saves, `retweets` for reposts, `plays` for views, `replies` for comments, `reactions` for likes. |
| `--json` | Print JSON instead of a table. With several links you get a list. |
| `--output`, `-o FILE` | Save a report. The extension picks the format, `.csv` or `.json`. |
| `--cookies FILE` | Your own browser cookies in Netscape `cookies.txt` format. See [cookies](#cookies). |
| `--proxy URL` | HTTP or SOCKS5 proxy, for example `socks5://127.0.0.1:9050`. |
| `--local-only` | Never call third-party services. This only affects X, where you then get likes and replies and nothing else. |
| `--debug` | Print what each source returned and save the raw pages to `./pulse-debug/`. |
| `--version` | Print the version. |

The exit code is 0 on success and 1 if any link failed (the other links are still printed). Bad usage gives 2.

### Links file

    # TikTok
    https://www.tiktok.com/@noimpurity/video/7687658250057075990

    # YouTube
    https://youtu.be/VIDEO_ID
    https://youtube.com/shorts/SHORT_ID

One link per line, no quotes. Empty lines and lines starting with `#` are skipped.

## Cookies

Most platforms work without them. Instagram needs your login session to give you reposts, shares and the same play count the app shows, and Facebook posts that are not videos usually need it as well.

1. Log in to the site in your browser.
2. Export your cookies in Netscape `cookies.txt` format with a browser extension built for that.
3. Save the file where you run the command and pass it in:

       social-pulse "https://www.instagram.com/reel/CODE/" --cookies cookies.txt

Each cookie is only sent to the domain it belongs to. A cookies file gives access to your account, so do not share it or commit it (`.gitignore` already skips `cookies*.txt`) and delete it when you are done. Automated use can get an account limited, so a spare account is the safer choice.

## Output formats

The table, JSON and CSV all carry the same fields. JSON looks like this (placeholder numbers):

    {
      "platform": "youtube",
      "post_id": "VIDEO_ID",
      "url": "https://youtu.be/VIDEO_ID",
      "author": "@channel",
      "likes": 12480,
      "comments": 312,
      "reposts": null,
      "shares": null,
      "saves": null,
      "views": 150230
    }

`platform`, `post_id` and `url` are always there. With `--fields`, the remaining fields are cut down to the ones you asked for.

## HTTP API

Run it as a web service if you want other people to use it without installing anything.

Start it on your own machine:

    pip install -e ".[api]"
    export PULSE_API_KEYS=my-secret-key        # on Windows cmd: set PULSE_API_KEYS=my-secret-key
    pulse-api                                   # serves http://127.0.0.1:8000, interactive docs at /docs

Then call it:

    curl -H "X-API-Key: my-secret-key" \
      "http://127.0.0.1:8000/v1/metrics?url=https://www.tiktok.com/@noimpurity/video/7687658250057075990&fields=likes,saves"

    curl -X POST http://127.0.0.1:8000/v1/metrics/batch \
      -H "X-API-Key: my-secret-key" -H "Content-Type: application/json" \
      -d '{"urls": ["https://www.tiktok.com/@noimpurity/video/7687658250057075990", "https://youtu.be/VIDEO_ID"], "fields": ["likes", "saves"]}'

A response looks like this:

    {"platform": "youtube", "post_id": "VIDEO_ID", "url": "https://youtu.be/VIDEO_ID",
     "likes": 12480, "views": 150230,
     "fetched_at": "2026-11-15T10:00:00+00:00", "cached": false, "warnings": []}

| Endpoint | What it does |
|---|---|
| `GET /v1/metrics?url=...&fields=...&local_only=...` | One link. |
| `POST /v1/metrics/batch` | Up to 10 links as `{"urls": [...], "fields": [...]}`. A link that fails does not stop the others. |
| `GET /v1/fields` | Lists the fields you can select. |
| `GET /health` | Health check. |

Errors: 400 for a link it does not support, 401 for a missing or wrong key, 422 for an invalid `fields` value, 429 when you hit the rate limit (check `Retry-After`), 502 when fetching from the platform failed, 503 when the server has no keys configured.

| Environment variable | Meaning | Default |
|---|---|---|
| `PULSE_API_KEYS` | Comma-separated keys that clients send in the `X-API-Key` header | required |
| `PULSE_ALLOW_ANONYMOUS` | `1` lets calls through without a key, for local testing only | off |
| `PULSE_RATE_LIMIT` | Requests per minute per key. A batch counts one per link. | 30 |
| `PULSE_CACHE_TTL` | Seconds to cache identical requests | 60 |
| `PULSE_PROXY` | Proxy for all outgoing requests | none |
| `PULSE_COOKIES_FILE` | A cookies file on the server, see the warning below | none |
| `PULSE_LOCAL_ONLY` | `1` stops it from using third-party services | off |
| `HOST`, `PORT` | Address and port to listen on | `127.0.0.1`, `8000` |

With Docker:

    docker build -t social-pulse .
    docker run -p 8000:8000 -e PULSE_API_KEYS=my-secret-key social-pulse

If you put it on the public internet:

- Set `PULSE_API_KEYS`, put it behind HTTPS and leave the rate limit on.
- Cloud servers have datacenter IP addresses, and TikTok, Instagram and Facebook block those much more often than home connections. You may need a proxy (`PULSE_PROXY`).
- `PULSE_COOKIES_FILE` makes every caller's request run as your logged-in account. That puts the account at risk and may break the platform's terms. The API never accepts cookies from callers.
- The rate limiter and the cache live in memory, so they only work with a single instance.

## Use it from Python

    from pulse.router import fetch

    m = fetch("https://www.tiktok.com/@noimpurity/video/7687658250057075990", fields=("likes", "saves"))
    print(m.likes, m.saves)     # m is a pydantic PostMetrics object

Failures raise `pulse.models.PulseError`. A link from an unsupported site raises its subclass `UnsupportedURL`.

## How it works

Each platform has an ordered list of sources. They run in that order and the results are merged field by field, with the earlier source winning. The chain stops as soon as the fields you asked for are filled.

| Platform | Sources, in order |
|---|---|
| TikTok | page data (tried with several browser TLS profiles), the same page through yt-dlp's HTTP session, yt-dlp |
| X | the public embed endpoint (likes, replies), api.fxtwitter.com (reposts, bookmarks, views; third party), yt-dlp |
| Instagram | the logged-in JSON API (only with cookies), yt-dlp (reels), page and embed metadata |
| Facebook | yt-dlp (videos), page data and og:description |
| YouTube | yt-dlp, then a separate lookup of the exact comment count |

Requests use browser-like TLS fingerprints through `curl_cffi`. Short links are resolved first. Every request and every redirect has to stay on the supported platforms' domains.

## Troubleshooting

| Problem | What to do |
|---|---|
| `'xyz' is not recognized as an internal or external command` | The link was not in double quotes. Add them. |
| A number shows `-` | The platform does not expose it (see the table), the creator hid it, or the request was blocked. Run with `--debug`. |
| `HTTP 403`, a captcha, or empty results | You are being rate limited or blocked. Wait, try `--proxy`, avoid datacenter IPs, and update with `pip install -U yt-dlp curl_cffi`. |
| Instagram reposts, shares or views are missing | Pass `--cookies cookies.txt` from a logged-in session. |
| Instagram redirects to the login page | It did not accept your cookies. They may have expired or been exported while you were logged out, so export them again. |
| YouTube asks you to sign in | Pass `--cookies`. |
| Numbers are a little different from the app | The counts move constantly, and some platforms round them (9.4K comes back as 9,400). |
| Garbled text when saving output to a file on Windows | Run `set PYTHONIOENCODING=utf-8` first. |

For anything else, run with `--debug`. It prints what each source returned (cookie values are never shown) and saves the raw pages to `./pulse-debug/`. Delete that folder when you are done, since the pages can contain personal data.

## Limitations

It depends on undocumented pages and endpoints, so parts of it will stop working from time to time. Updating yt-dlp and curl_cffi fixes some of those breakages and not others.

It only reads public content. Private, deleted, age-restricted and region-locked posts fail. If a creator hides their likes or comments you get `null`.

Some platforms send rounded numbers (10,500 or 9.4K), and you get what they send. The counts also keep changing, so compare with the app at the same moment.

Per platform:

- Instagram: reposts, shares and the app's play count need a logged-in session. Without cookies the views come from an older counter that can be lower than the app's number, and you get a warning. Saves are never public, and photo and carousel posts have no views.
- Facebook: likes is the total number of reactions. Views exist for videos only, and saves are not public.
- X: reposts, bookmarks and views come from api.fxtwitter.com, a third-party service that receives the post's author handle and ID. `--local-only` avoids it, and then you get likes and replies. X has no share count.
- YouTube: no shares or saves. The exact comment count takes one extra request, and if that fails you get yt-dlp's rounded number.

Datacenter IPs get blocked far more often than home connections. The tool is meant for single links and small batches, not for scraping at scale.

Untested so far: Instagram photo and carousel posts, Facebook posts without cookies, and the Docker image under real traffic. The Python import name is `pulse`.

## Privacy and security

Nothing leaves your machine unless you host the API yourself, and there is no telemetry. Cookies are read from the file you pass, sent only to their own domain, and never logged. With `--debug` you only see cookie names.

The HTTP API needs a key and never accepts cookies from callers. Outgoing requests and redirects are limited to the supported platforms, so the API cannot be used to reach arbitrary or internal addresses.

Each result includes the post author's public handle next to the counts. If you store or publish data about people, privacy law may apply to you.

## Legal

This project is not affiliated with TikTok, Meta (Instagram and Facebook), X Corp or Google (YouTube), and none of them endorse it. It reads publicly visible pages. Automated access can conflict with a platform's terms of service, and running a public service on top of it adds more risk. Read the terms that apply to you, respect rate limits, stick to public content, and use it at your own risk. This is not legal advice.

## Development

    pip install -e ".[dev]"
    pytest -q          # offline, no network needed
    ruff check .

Layout:

    pulse/
      cli.py            terminal interface (typer and rich)
      api.py            HTTP API (FastAPI)
      router.py         platform detection, source order, merging
      http.py           requests with TLS impersonation, cookie file parser, host allowlist
      models.py         PostMetrics schema, field selection
      debug.py          helpers for --debug
      extractors/       tiktok, twitter, instagram, facebook, youtube, meta (yt-dlp)
    tests/              offline tests and fixtures
    Dockerfile, .github/workflows/tests.yml

[CONTRIBUTING.md](CONTRIBUTING.md) explains how to add a platform or fix a parser. Report security problems as described in [SECURITY.md](SECURITY.md).

## Not done yet

- An optional source that uses the official YouTube Data API when you have a key.
- A PyPI release.

## License

[MIT](LICENSE)
