#!/usr/bin/env python3
"""
main.py
=======
Entry point for the Daily Job Skills WordCloud GitHub Action
(.github/workflows/daily_cloud.yml). It just calls job_skills_cloud.main()
with fixed, sane defaults so the workflow doesn't need to know or pass any
CLI flags -- everything is configurable through repo variables/env instead,
so you can tweak the schedule's behavior without touching code.

Env vars (all optional -- shown with their defaults):
    SKILLS_CATEGORY   devops        which taxonomies/<name>.json to use
    SKILLS_SOURCES     remotive,remoteok,arbeitnow
    SKILLS_QUERY       ""           title/keyword filter passed to each source
    SKILLS_LIMIT       300          max postings pulled PER source
    SKILLS_THEME       classic      classic | aurora | sunset | forest | mono
    SKILLS_SHAPE       circle       circle | rounded_rect
    SKILLS_SCALING     sqrt         linear | sqrt | log | power
    SKILLS_WIDTH       1600
    SKILLS_HEIGHT      1600
    SKILLS_OUTPUT      skills_cloud.png   must match the filename committed
                                           in daily_cloud.yml
    SKILLS_CACHE       (unset)      optional path to cache fetched postings
                                     as JSON, for local testing without
                                     re-hitting the APIs every run

To point the daily run at a different tech domain, either set
SKILLS_CATEGORY to another file already in taxonomies/, or add a new
taxonomy JSON there (see README.md) and set SKILLS_CATEGORY to its name.
"""

import os
import sys

from job_skills_cloud import main as run

if __name__ == "__main__":
    args = [
        "--category", os.environ.get("SKILLS_CATEGORY", "devops"),
        "--sources", os.environ.get("SKILLS_SOURCES", "remotive,remoteok,arbeitnow"),
        "--query", os.environ.get("SKILLS_QUERY", ""),
        "--limit", os.environ.get("SKILLS_LIMIT", "300"),
        "--theme", os.environ.get("SKILLS_THEME", "classic"),
        "--shape", os.environ.get("SKILLS_SHAPE", "circle"),
        "--scaling", os.environ.get("SKILLS_SCALING", "sqrt"),
        "--width", os.environ.get("SKILLS_WIDTH", "1600"),
        "--height", os.environ.get("SKILLS_HEIGHT", "1600"),
        "--output", os.environ.get("SKILLS_OUTPUT", "skills_cloud.png"),
    ]
    if os.environ.get("SKILLS_CACHE"):
        args += ["--cache", os.environ["SKILLS_CACHE"]]
    sys.exit(run(args))
