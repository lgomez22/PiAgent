# Security Policy

## Supported Versions

PiAgent currently supports security updates for the latest release-candidate/stable line.

| Version | Supported |
| ------- | --------- |
| 0.3.0-rc1 | ✅ |
| 0.2.6      | ✅ |
| < 0.2.6    | ❌ |

## Reporting a Vulnerability

Please report suspected vulnerabilities privately and include:

- PiAgent version (`version` command output)
- Reproduction steps
- Expected vs actual behavior
- Any relevant logs (redact API keys and secrets)

Do **not** disclose secrets (`moltbook_*`, `gsk_*`, `PROMPTINTEL_API_KEY`) in reports.

If the issue involves account suspension/challenge handling, attach relevant entries from:

- `~/.config/piagent/api.log`
- `~/.config/piagent/agent.log`
