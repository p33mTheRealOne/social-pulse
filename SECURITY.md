# Security policy

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting (Security tab, "Report a vulnerability")
instead of a public issue. Examples in scope: bypassing the host allowlist (SSRF), API key or
rate-limit bypass, leaking cookies or other secrets.

## Handling your own secrets

- A `cookies.txt` file gives access to your account. Never share it, commit it, or paste it into an issue.
- `--debug` writes full pages to `./pulse-debug/`. Delete that folder when you are done.
- If a cookie leaks, log out of the site everywhere and log in again so the old cookie expires.
