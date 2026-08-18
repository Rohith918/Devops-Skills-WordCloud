#!/usr/bin/env python3
"""
job_skills_cloud.py
====================
Fetch live job postings from multiple free/no-auth job-board APIs, mine them
for how often specific skills appear, and render a high-quality word cloud
image (plus the raw numbers) so you can see what actually shows up in
today's job market.

Why this exists
----------------
The original version of this script hardcoded one API (Remotive) and one
skill list (DevOps). That breaks the moment you want a different job
category, a different data source, or want to reuse the numbers somewhere
else. This version fixes that:

  * Skill list lives in an external JSON "taxonomy" file -> swap it for any
    domain (frontend, data science, product management, whatever) without
    touching code. Two example taxonomies ship in ./taxonomies/.
  * Job postings are pulled from a pluggable list of sources (Remotive,
    RemoteOK, Arbeitnow by default). If one API is down or rate-limited,
    the others still contribute -- the tool degrades instead of failing.
  * Skills are counted per-posting (did this job mention it at least once?)
    rather than per-mention, so one wordy posting can't fake a trend.
  * Frequencies, not just the picture, are saved to JSON/CSV so you can
    plug them into your own dashboard, spreadsheet, or blog post.
  * The image itself is antialiased (supersampled mask), uses a smooth
    color gradient instead of hard brightness bands, and picks a bold
    system font automatically so text doesn't fall back to a thin default.

Usage
-----
    python job_skills_cloud.py --category devops --limit 300
    python job_skills_cloud.py --taxonomy taxonomies/data_science.json --query "data scientist"
    python job_skills_cloud.py --sources remotive,remoteok --scaling sqrt --theme sunset

Run `python job_skills_cloud.py --help` for every option.

Dependencies: requests, beautifulsoup4, wordcloud, pillow, numpy, matplotlib
    pip install requests beautifulsoup4 wordcloud pillow numpy matplotlib
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFilter
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from wordcloud import WordCloud

try:
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors

    HAVE_MATPLOTLIB = True
except ImportError:  # pragma: no cover - matplotlib ships with wordcloud anyway
    HAVE_MATPLOTLIB = False

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%H:%M:%S"
)
log = logging.getLogger("job_skills_cloud")

HERE = Path(__file__).resolve().parent
DEFAULT_TAXONOMY = HERE /  "devops.json"


def _requests_session(retries: int = 3, backoff: float = 0.6) -> requests.Session:
    """A requests session with sane retries/backoff so a single flaky API
    call doesn't kill the whole run."""
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "job-skills-cloud/1.0 (+https://github.com/)"})
    return session


# --------------------------------------------------------------------------
# Job sources -- pluggable. Add a new one by subclassing JobSource.
# --------------------------------------------------------------------------


class JobSource(ABC):
    """Common interface for a job-board API. Each source fetches raw
    postings and returns plain-text descriptions only -- HTML stripped."""

    name: str = "base"

    def __init__(self, session: requests.Session, timeout: int = 15):
        self.session = session
        self.timeout = timeout

    @abstractmethod
    def fetch(self, query: str, limit: int) -> list[str]:
        """Return up to `limit` plain-text job descriptions matching query."""

    def _strip_html(self, html: str) -> str:
        return BeautifulSoup(html or "", "html.parser").get_text(separator=" ")


class RemotiveSource(JobSource):
    name = "remotive"
    URL = "https://remotive.com/api/remote-jobs"

    def fetch(self, query: str, limit: int) -> list[str]:
        params = {"search": query, "limit": limit} if query else {"limit": limit}
        resp = self.session.get(self.URL, params=params, timeout=self.timeout)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        return [self._strip_html(j.get("description", "")) for j in jobs[:limit]]


class RemoteOKSource(JobSource):
    name = "remoteok"
    URL = "https://remoteok.com/api"

    def fetch(self, query: str, limit: int) -> list[str]:
        resp = self.session.get(self.URL, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        # RemoteOK's first element is a metadata/legal blob, not a job.
        jobs = [d for d in data if isinstance(d, dict) and d.get("description")]
        if query:
            q = query.lower()
            jobs = [
                j
                for j in jobs
                if q in (j.get("position", "") + " " + j.get("description", "")).lower()
            ]
        return [self._strip_html(j.get("description", "")) for j in jobs[:limit]]


class ArbeitnowSource(JobSource):
    name = "arbeitnow"
    URL = "https://www.arbeitnow.com/api/job-board-api"

    def fetch(self, query: str, limit: int) -> list[str]:
        out: list[str] = []
        url = self.URL
        # Simple pagination until we have enough or the API stops giving links.
        while url and len(out) < limit:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            jobs = payload.get("data", [])
            if query:
                q = query.lower()
                jobs = [
                    j
                    for j in jobs
                    if q in (j.get("title", "") + " " + j.get("description", "")).lower()
                ]
            out.extend(self._strip_html(j.get("description", "")) for j in jobs)
            url = (payload.get("links") or {}).get("next")
        return out[:limit]


SOURCE_REGISTRY: dict[str, type[JobSource]] = {
    "remotive": RemotiveSource,
    "remoteok": RemoteOKSource,
    "arbeitnow": ArbeitnowSource,
}


def fetch_job_descriptions(
    sources: Iterable[str], query: str, limit_per_source: int, timeout: int = 15
) -> list[str]:
    """Pull descriptions from every requested source. A failing source is
    logged and skipped -- it never aborts the whole run."""
    session = _requests_session()
    all_jds: list[str] = []
    for name in sources:
        cls = SOURCE_REGISTRY.get(name)
        if cls is None:
            log.warning("Unknown source '%s' -- skipping. Known: %s", name, list(SOURCE_REGISTRY))
            continue
        source = cls(session, timeout=timeout)
        try:
            t0 = time.time()
            jds = source.fetch(query, limit_per_source)
            log.info("Fetched %d postings from %s (%.1fs)", len(jds), name, time.time() - t0)
            all_jds.extend(jd for jd in jds if jd and jd.strip())
        except requests.exceptions.RequestException as exc:
            log.warning("Source '%s' failed: %s -- continuing with other sources", name, exc)
        except (ValueError, KeyError) as exc:
            log.warning("Source '%s' returned unexpected data: %s", name, exc)
    return all_jds


# --------------------------------------------------------------------------
# Skill taxonomy + extraction
# --------------------------------------------------------------------------


@dataclass
class Skill:
    display: str
    aliases: list[str]


@dataclass
class Taxonomy:
    name: str
    skills: list[Skill] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Taxonomy":
        data = json.loads(Path(path).read_text())
        skills = [Skill(display=s["display"], aliases=s["aliases"]) for s in data["skills"]]
        return cls(name=data.get("name", Path(path).stem), skills=skills)


def extract_skill_frequencies(
    jds: list[str], taxonomy: Taxonomy, scaling: str = "sqrt", power: float = 1.35
) -> tuple[dict[str, int], dict[str, float]]:
    """Count how many *distinct postings* mention each skill (document
    frequency), then scale for display.

    Document frequency instead of raw mention count matters: a single
    keyword-stuffed posting shouldn't be able to make a rare skill look
    dominant. Raw counts are still returned so callers can do their own
    analysis.
    """
    raw_counts: dict[str, int] = {s.display: 0 for s in taxonomy.skills}

    # Longer alias phrases first so "ci/cd" doesn't get shadowed by a
    # shorter overlapping pattern, and precompile everything once.
    compiled: list[tuple[str, re.Pattern]] = []
    for skill in taxonomy.skills:
        for alias in sorted(skill.aliases, key=len, reverse=True):
            compiled.append((skill.display, re.compile(rf"(?<!\w){alias}(?!\w)", re.IGNORECASE)))

    for jd in jds:
        seen_this_posting: set[str] = set()
        for display, pattern in compiled:
            if display in seen_this_posting:
                continue
            if pattern.search(jd):
                seen_this_posting.add(display)
        for display in seen_this_posting:
            raw_counts[display] += 1

    raw_counts = {k: v for k, v in raw_counts.items() if v > 0}
    if not raw_counts:
        return {}, {}

    max_count = max(raw_counts.values())
    if scaling == "linear":
        scaled = {k: v / max_count for k, v in raw_counts.items()}
    elif scaling == "sqrt":
        scaled = {k: (v / max_count) ** 0.5 for k, v in raw_counts.items()}
    elif scaling == "log":
        scaled = {k: np.log1p(v) / np.log1p(max_count) for k, v in raw_counts.items()}
    elif scaling == "power":
        scaled = {k: (v / max_count) ** power for k, v in raw_counts.items()}
    else:
        raise ValueError(f"Unknown scaling '{scaling}'")

    return raw_counts, scaled


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

THEMES: dict[str, list[str]] = {
    # Each theme is a list of hex colors sampled low -> high frequency
    # (used for the smooth gradient color_func).
    "aurora": ["#64748b", "#818cf8", "#c084fc", "#38bdf8"],
    "sunset": ["#78716c", "#f59e0b", "#f97316", "#ef4444"],
    "forest": ["#6b7280", "#4ade80", "#22c55e", "#15803d"],
    "mono": ["#94a3b8", "#64748b", "#334155", "#0f172a"],
}

# "classic" is a different visual family entirely: white background, each
# word gets a color cycled from a qualitative palette independent of its
# size (matplotlib's tab10 palette), matching the familiar look most
# wordcloud galleries use. It intentionally ignores THEMES/gradient logic.
CLASSIC_PALETTE = "tab10"

BOLD_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:\\Windows\\Fonts\\arialbd.ttf",
]


def _pick_font() -> str | None:
    for candidate in BOLD_FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    if HAVE_MATPLOTLIB:
        # Fall back to whatever bold sans-serif matplotlib bundles.
        try:
            import matplotlib.font_manager as fm

            for f in fm.fontManager.ttflist:
                if "bold" in f.name.lower() or f.weight in (700, "bold"):
                    return f.fname
        except Exception:  # pragma: no cover
            pass
    return None  # wordcloud falls back to its own default


def _make_color_func(theme: str, freqs: dict[str, float]):
    """Smooth gradient color function (continuous, not banded-by-font-size)
    driven by each word's *frequency value* rather than rendered pixel size,
    so the mapping stays correct regardless of layout."""
    colors = THEMES.get(theme, THEMES["aurora"])
    if HAVE_MATPLOTLIB:
        cmap = mcolors.LinearSegmentedColormap.from_list(theme, colors)
    max_freq = max(freqs.values()) if freqs else 1.0

    def color_func(word, font_size=None, position=None, orientation=None, random_state=None, **kwargs):
        val = freqs.get(word, 0) / max_freq if max_freq else 0
        if HAVE_MATPLOTLIB:
            r, g, b, _ = cmap(val)
            return f"rgb({int(r * 255)},{int(g * 255)},{int(b * 255)})"
        # Fallback: pick nearest bucket from the theme list.
        idx = min(int(val * (len(colors) - 1)), len(colors) - 1)
        return colors[idx]

    return color_func


def create_rounded_mask(width: int, height: int, radius: int = 80, supersample: int = 4) -> np.ndarray:
    """Rounded-rectangle mask, drawn at `supersample`x resolution and
    downscaled with anti-aliasing so the edge is smooth instead of jagged
    (wordcloud masks are otherwise pixel-hard)."""
    big = (width * supersample, height * supersample)
    img = Image.new("L", big, 255)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(0, 0), big], radius=radius * supersample, fill=0)
    img = img.resize((width, height), Image.LANCZOS)
    return np.array(img)


def create_circle_mask(diameter: int, supersample: int = 4) -> np.ndarray:
    """Perfect circle mask, anti-aliased the same way as the rounded rect."""
    big = diameter * supersample
    img = Image.new("L", (big, big), 255)
    draw = ImageDraw.Draw(img)
    draw.ellipse([(0, 0), (big, big)], fill=0)
    img = img.resize((diameter, diameter), Image.LANCZOS)
    return np.array(img)


def generate_cloud(
    frequencies: dict[str, float],
    output_file: str,
    theme: str = "aurora",
    shape: str = "rounded_rect",
    width: int = 2400,
    height: int = 1350,
    background: str | None = None,
) -> None:
    if not frequencies:
        log.warning("No skills found in the fetched postings -- nothing to render.")
        return

    if shape == "circle":
        diameter = min(width, height)
        mask = create_circle_mask(diameter)
        width = height = diameter
    else:
        mask = create_rounded_mask(width, height, radius=int(min(width, height) * 0.09))

    font_path = _pick_font()
    if font_path:
        log.info("Using font: %s", font_path)

    is_classic = theme == "classic"
    bg = background or ("white" if is_classic else "#090d16")

    wc_kwargs = dict(
        width=width,
        height=height,
        scale=2,
        background_color=bg,
        mask=mask,
        prefer_horizontal=0.90,
        min_font_size=16,
        max_font_size=int(height * 0.17),
        margin=6,
        relative_scaling=0.45,
        collocations=False,
        font_path=font_path,
    )
    if is_classic:
        # Qualitative palette cycled per word, independent of size -- the
        # familiar multi-hue wordcloud look, rather than our frequency-driven
        # gradient.
        wc_kwargs["colormap"] = CLASSIC_PALETTE
    else:
        wc_kwargs["color_func"] = _make_color_func(theme, frequencies)

    wc = WordCloud(**wc_kwargs).generate_from_frequencies(frequencies)

    # Light unsharp mask keeps letterforms crisp after the 2x internal scale.
    img = wc.to_image().filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3))
    img.save(output_file)
    log.info("Saved image: %s", output_file)


def save_data(raw_counts: dict[str, int], total_postings: int, out_stem: Path) -> None:
    """Persist the numbers behind the picture so they're reusable --
    dashboards, spreadsheets, a follow-up chart, whatever."""
    json_path = out_stem.with_suffix(".json")
    csv_path = out_stem.with_suffix(".csv")

    ranked = sorted(raw_counts.items(), key=lambda kv: kv[1], reverse=True)
    payload = {
        "total_postings_analyzed": total_postings,
        "skills": [
            {"skill": name, "postings_mentioning": count, "pct_of_postings": round(100 * count / total_postings, 1)}
            for name, count in ranked
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2))

    with csv_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["skill", "postings_mentioning", "pct_of_postings"])
        for row in payload["skills"]:
            writer.writerow([row["skill"], row["postings_mentioning"], row["pct_of_postings"]])

    log.info("Saved data: %s, %s", json_path, csv_path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Mine live job postings for skill frequency and render a word cloud.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY, help="Path to a skills taxonomy JSON file")
    p.add_argument("--category", type=str, default=None, help="Shortcut: use taxonomies/<category>.json")
    p.add_argument("--query", type=str, default="", help="Search term / job title filter passed to each source")
    p.add_argument(
        "--sources",
        type=str,
        default="remotive,remoteok,arbeitnow",
        help=f"Comma-separated sources to query. Available: {', '.join(SOURCE_REGISTRY)}",
    )
    p.add_argument("--limit", type=int, default=200, help="Max postings to pull PER source")
    p.add_argument("--scaling", choices=["linear", "sqrt", "log", "power"], default="sqrt", help="How counts map to word size")
    p.add_argument(
        "--theme",
        choices=list(THEMES) + ["classic"],
        default="aurora",
        help="Color theme. 'classic' = white background, qualitative multi-hue palette",
    )
    p.add_argument("--shape", choices=["rounded_rect", "circle"], default="rounded_rect", help="Mask shape")
    p.add_argument("--width", type=int, default=2400)
    p.add_argument("--height", type=int, default=1350)
    p.add_argument("--output", type=Path, default=Path("skills_cloud.png"), help="Output image path; data files share its stem")
    p.add_argument("--cache", type=Path, default=None, help="Optional path to cache/reuse fetched job text as JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    taxonomy_path = Path(f"taxonomies/{args.category}.json") if args.category else args.taxonomy
    if not taxonomy_path.exists():
        log.error("Taxonomy file not found: %s", taxonomy_path)
        return 1
    taxonomy = Taxonomy.load(taxonomy_path)
    log.info("Loaded taxonomy '%s' (%d skills)", taxonomy.name, len(taxonomy.skills))

    jds: list[str] = []
    if args.cache and args.cache.exists():
        log.info("Loading cached postings from %s", args.cache)
        jds = json.loads(args.cache.read_text())
    else:
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        jds = fetch_job_descriptions(sources, args.query, args.limit)
        if args.cache:
            args.cache.write_text(json.dumps(jds))
            log.info("Cached %d postings to %s", len(jds), args.cache)

    if not jds:
        log.error("No job postings retrieved from any source -- nothing to analyze.")
        return 1
    log.info("Analyzing %d total postings", len(jds))

    raw_counts, scaled_freqs = extract_skill_frequencies(jds, taxonomy, scaling=args.scaling)
    if not raw_counts:
        log.warning("None of the taxonomy's skills were found in the fetched postings.")
        return 0

    top = sorted(raw_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    log.info("Top skills: %s", ", ".join(f"{k} ({v})" for k, v in top))

    generate_cloud(
        scaled_freqs,
        str(args.output),
        theme=args.theme,
        shape=args.shape,
        width=args.width,
        height=args.height,
    )
    save_data(raw_counts, len(jds), args.output.with_suffix(""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
