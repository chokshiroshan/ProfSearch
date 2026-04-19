# Security Policy

## Supported Versions

ProfSearch is in alpha (0.1.x). Only the latest release on `main` receives security fixes.

## Reporting a Vulnerability

Please report suspected vulnerabilities **privately**, not via public GitHub issues.

- Email: chokshiroshan@gmail.com
- Subject line: `[ProfSearch Security]` followed by a short description.

Include, where possible:

- ProfSearch version (`profsearch --version`) and commit SHA.
- The affected component (scraper, matcher, web route, CLI command, etc.).
- A proof-of-concept or reproduction steps.
- The impact you believe this has (data exposure, RCE, credential leak, etc.).
- Whether you would like credit in the fix announcement.

You should receive an acknowledgement within 5 working days. We aim to provide a fix or mitigation plan within 30 days for confirmed issues.

## Scope

In scope:

- The ProfSearch Python package, CLI, and web UI.
- The default pipeline stages and their handling of scraped or external-API data.
- Any bundled seed data or config defaults.

Out of scope:

- Vulnerabilities in third-party sites scraped by ProfSearch — report those to the upstream site.
- Vulnerabilities in dependencies — report those upstream, but feel free to CC us so we can pin a safe version.
- Findings that require already-compromised local access (e.g., a malicious `config.toml`).

## Disclosure

We prefer coordinated disclosure. Once a fix is released, we will credit the reporter (with permission) in the release notes.
