# Devops-Skills-WordCloud

![Daily Skills Word Cloud](skills_cloud.png)

---------------------------------------

Pull live job postings from multiple job boards, measure how often specific
skills actually show up, and render a clean word-cloud image — plus the raw
numbers, so you're not stuck staring at a picture.

## What changed from a single hardcoded script

| Problem in the original | Fix here |
|---|---|
| One API (Remotive), hardcoded URL | Pluggable `JobSource` classes — Remotive, RemoteOK, Arbeitnow ship by default. Add your own by subclassing `JobSource`. One source failing (rate limit, outage) doesn't kill the run — the others still contribute. |
| One skill list, baked into the code, DevOps-only | Skills live in an external JSON **taxonomy** file. Swap `--category devops` for `--category data_science`, or write your own taxonomy for any field. |
| Counted every mention, so one wordy posting could dominate | Counts **document frequency** — did this posting mention the skill at all — so keyword-stuffed listings can't fake a trend. Raw mention data is still there if you want it. |
| Fixed power-scaling (`**1.35`) baked in | `--scaling {linear,sqrt,log,power}` — pick how counts map to word size. |
| Picture only, numbers thrown away | Every run also writes `<output>.json` and `<output>.csv` with per-skill counts and percentages, so you can chart it yourself, drop it in a report, or track it over time. |
| Hard-edged mask, banded colors, default thin font | Supersampled + anti-aliased mask, a continuous color gradient (not brightness bands), and automatic bold-font detection. |

## Install

```bash
pip install requests beautifulsoup4 wordcloud pillow numpy matplotlib
```

## Quick start

```bash
# DevOps roles, default sources, default styling
python job_skills_cloud.py --category devops

# Data science roles, filtered by title, sunset theme
python job_skills_cloud.py --category data_science --query "data scientist" --theme sunset

# Only query one source, log-scaled sizing, bigger canvas
python job_skills_cloud.py --sources remotive --scaling log --width 3200 --height 1800
```

Outputs (default names, overridable with `--output`):

- `skills_cloud.png` — the image
- `skills_cloud.json` — `{skill, postings_mentioning, pct_of_postings}` for every skill found
- `skills_cloud.csv` — same data, spreadsheet-friendly

## Run it daily with GitHub Actions

This repo is set up to run automatically once a day and commit a fresh
`skills_cloud.png` (+ `.json`/`.csv`) back into the repo — see
`.github/workflows/daily_cloud.yml`.

Setup:

1. Push this repo to GitHub.
2. In **Settings → Actions → General → Workflow permissions**, make sure
   "Read and write permissions" is enabled (the workflow needs it to push
   the updated image back).
3. That's it — it runs at midnight UTC, or trigger it immediately from the
   **Actions** tab via "Run workflow" (`workflow_dispatch`).

`main.py` is the entry point the workflow calls. It wraps
`job_skills_cloud.py` with fixed defaults (DevOps, classic circular style)
so the workflow doesn't need any CLI flags. Everything is overridable via
environment variables set in the workflow's `env:` block — see the
docstring at the top of `main.py` for the full list (`SKILLS_CATEGORY`,
`SKILLS_THEME`, `SKILLS_SHAPE`, `SKILLS_LIMIT`, etc.). To track a different
tech domain instead, change `SKILLS_CATEGORY` to another file in
`taxonomies/` (or add your own — see below) and commit.

If you rename the output file via `SKILLS_OUTPUT`, update the `git add`
line in the workflow to match, or the commit step won't pick it up.

## Bring your own skill list

Copy `taxonomies/devops.json` and edit it. Each entry is:

```json
{ "display": "Kubernetes", "aliases": ["kubernetes", "k8s"] }
```

`display` is what's rendered in the cloud; `aliases` are the regex-safe
terms matched (case-insensitive, whole-word) in job text. Point at it with
`--taxonomy path/to/yours.json`, or drop it in `taxonomies/` and use
`--category yourname`.

## Add a new job source

Subclass `JobSource`, implement `fetch(query, limit) -> list[str]` returning
plain-text descriptions, and register it in `SOURCE_REGISTRY`. See
`RemotiveSource` / `RemoteOKSource` / `ArbeitnowSource` for the pattern —
each is under 20 lines.

## Caching while you iterate

`--cache jobs.json` saves fetched postings on first run and reuses them on
later runs, so you can re-style the image (`--theme`, `--scaling`) without
re-hitting the APIs every time.

## Notes

- All three default sources are free and require no API key.
- Network errors, rate limits, or a malformed response from one source are
  logged as warnings and skipped — the run continues with whatever sources
  succeeded. If *every* source fails, the tool exits with an error rather
  than silently producing an empty image.
