# linkedin-match

A [Claude Code skill](https://docs.claude.com/en/docs/claude-code/skills) that
matches you to open jobs at companies where you already have a LinkedIn
connection — a warm intro — and scores each job against your CV. Produces
either a fast keyword-ranked CSV/JSON, or a shareable AI-scored HTML report
(via Sonnet subagents). Fully self-contained: no other repo, no API key.

Full behavior lives in [SKILL.md](SKILL.md) — that's what Claude actually reads.

## Install

```
/plugin marketplace add hanegbi/linkedin-match
/plugin install linkedin-match@linkedin-match
```

Then just say `/linkedin-match` in a chat.

<details>
<summary>Manual install (no update tracking, but works anywhere)</summary>

```
git clone https://github.com/hanegbi/linkedin-match.git ~/.claude/skills/linkedin-match
```

Restart Claude Code, then run `/linkedin-match`.
</details>

No separate build step — the skill sets up its own Python venv the first time
it runs, in a workdir you choose.

## Requirements

- Python 3.13+
- Internet access (scrapes job postings + reads the public techmap dataset)
- Claude Code (or another client that supports Agent subagents) for the
  AI-scored report; the keyword flow works anywhere

## License

MIT — see [LICENSE.txt](LICENSE.txt).
