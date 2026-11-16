# Contributing

Thanks for helping. Platforms change their pages often, so fixes are welcome.

## Setup

    git clone https://github.com/YOUR-USERNAME/social-pulse.git
    cd social-pulse
    python -m venv venv
    source venv/bin/activate        # Windows: venv\Scripts\activate
    pip install -e ".[dev]"
    pytest -q                       # offline, no network
    ruff check .

## Rules

- **Never commit secrets or personal data**: no cookies, no `pulse-debug/` files, no real account IDs.
  Test fixtures must be synthetic or scrubbed. `.gitignore` already excludes the usual files.
- Code and config files are ASCII only and contain no emoji (a test enforces this).
- Parsers are pure functions (`parse(text, url)`) so they can be tested offline. Add a test with every fix.
- New hosts must be added to `ALLOWED_SUFFIXES` in `pulse/http.py`; requests to other hosts are blocked on purpose.

## Adding a platform

1. Create `pulse/extractors/<name>.py` with a pure `parse()` and an `extract()`.
2. Register domains, pipeline and supported fields in `pulse/router.py`.
3. Add the host to `ALLOWED_SUFFIXES` in `pulse/http.py`.
4. Add a fixture and tests.

## Reporting a broken platform

Open an issue with the template and include the output of `--debug` (scrubbed of personal data).
