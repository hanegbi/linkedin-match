# linkedin-match

A [Claude Code skill](https://docs.claude.com/en/docs/claude-code/skills) that
matches a job seeker to open roles at companies where they already have a
LinkedIn contact — a warm intro — and scores fit against their CV. Produces a
fast keyword-matched CSV/JSON, or a shareable AI-scored HTML report using Sonnet
subagents. Fully self-contained: no other repo or API key needed.

Full behavior is documented in [SKILL.md](SKILL.md) — that's what Claude reads.

## Install

This repo is also a Claude Code plugin marketplace (of one plugin), which is the
recommended way to install a skill that lives in its own repo — it gets you
update tracking (`/plugin marketplace update`) instead of a plain, un-tracked
folder copy:

```
/plugin marketplace add hanegbi/linkedin-match
/plugin install linkedin-match@linkedin-match
```

Then in a chat run `/linkedin-match`.

**Alternative — manual clone (no plugin tracking, but works anywhere):**

```
git clone <this-repo-url> ~/.claude/skills/linkedin-match
```

(Windows: `C:\Users\<you>\.claude\skills\linkedin-match`) Restart Claude Code (or
start a new session) so it picks up the skill, then run `/linkedin-match`.

Either way, no separate build step — the skill sets up its own Python venv the
first time it runs, from a workdir you choose.

## Requirements

- Python 3.13+
- Internet access (scrapes job postings and reads the public techmap dataset)
- Claude Code (or another client that supports Agent subagents) for the
  AI-scored report flow — the keyword-match flow works anywhere

## License

MIT — see [LICENSE.txt](LICENSE.txt).
