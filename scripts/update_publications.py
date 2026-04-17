#!/usr/bin/env python3
"""
Fetch publications from Google Scholar and write them to _data/scholar_pubs.yml.

Uses the `scholarly` library (pip install scholarly).
Run locally or via GitHub Actions (see .github/workflows/update_scholar.yml).

Google Scholar profile: https://scholar.google.com/citations?user=3yM14pcAAAAJ
"""

import yaml
import time
import sys
import os
from datetime import datetime

SCHOLAR_ID = "3yM14pcAAAAJ"
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "_data", "scholar_pubs.yml")


def fetch_publications():
    try:
        from scholarly import scholarly, ProxyGenerator
    except ImportError:
        print("ERROR: Install scholarly with:  pip install scholarly")
        sys.exit(1)

    print(f"Fetching Google Scholar profile for ID: {SCHOLAR_ID}")

    # Use free proxies to avoid being blocked — not guaranteed but helps in CI
    pg = ProxyGenerator()
    scholarly.use_proxy(pg)

    try:
        author = scholarly.search_author_id(SCHOLAR_ID)
        author = scholarly.fill(author, sections=["publications"])
    except Exception as e:
        print(f"ERROR fetching author profile: {e}")
        sys.exit(1)

    publications = []
    for pub in author.get("publications", []):
        try:
            filled = scholarly.fill(pub)
            bib = filled.get("bib", {})

            entry = {
                "title":   bib.get("title", ""),
                "authors": bib.get("author", ""),
                "venue":   bib.get("venue", bib.get("journal", bib.get("booktitle", ""))),
                "year":    int(bib.get("pub_year", 0)) if bib.get("pub_year") else None,
                "abstract": bib.get("abstract", ""),
                "url":     filled.get("pub_url", ""),
                "eprint":  filled.get("eprint_url", ""),
                "citations": filled.get("num_citations", 0),
            }
            publications.append(entry)
            print(f"  ✓ {entry['title'][:70]}...")
            time.sleep(1)   # be polite
        except Exception as e:
            print(f"  ✗ Could not fill publication: {e}")
            continue

    # Sort by year descending
    publications.sort(key=lambda x: x.get("year") or 0, reverse=True)
    return publications


def write_yaml(publications):
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    data = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%d"),
        "scholar_id": SCHOLAR_ID,
        "publications": publications,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    print(f"\nWrote {len(publications)} publications to {OUTPUT_FILE}")


if __name__ == "__main__":
    pubs = fetch_publications()
    write_yaml(pubs)
