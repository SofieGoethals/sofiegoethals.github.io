#!/usr/bin/env python3
"""
Fetch Sofie Goethals' publications from the Semantic Scholar API
(free, no auth, no rate-limit blocks) and:

  1. Write _data/scholar_pubs.yml  — full publication list
  2. Update _data/news.yml         — add entries for newly detected papers
  3. Print a report of preprints that have since been published
     (so they can be manually removed from the Preprints section)

Semantic Scholar API docs: https://api.semanticscholar.org/api-docs/
"""

import json
import os
import re
import sys
import time
from datetime import datetime

import requests
import yaml

# ── Config ────────────────────────────────────────────────────────
AUTHOR_NAME   = "Sofie Goethals"
AFFIL_KEYS    = ["antwerp", "columbia"]          # used to disambiguate
SS_BASE       = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS  = (
    "title,year,venue,journal,authors,"
    "externalIds,openAccessPdf,publicationTypes,citationCount"
)

REPO_ROOT   = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SCHOLAR_YML = os.path.join(REPO_ROOT, "_data", "scholar_pubs.yml")
NEWS_YML    = os.path.join(REPO_ROOT, "_data", "news.yml")


# ── HTTP helpers ──────────────────────────────────────────────────
def _get(endpoint: str, params: dict = None) -> dict:
    url = f"{SS_BASE}/{endpoint}"
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=30,
                                headers={"User-Agent": "academic-site-bot/1.0"})
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 10))
                print(f"  Rate limited — waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            time.sleep(0.5)   # be polite
            return resp.json()
        except requests.RequestException as e:
            print(f"  Request error (attempt {attempt+1}/3): {e}")
            time.sleep(3)
    raise RuntimeError(f"Failed to fetch {url} after 3 attempts")


# ── Author lookup ─────────────────────────────────────────────────
def find_author_id() -> str:
    print(f"Looking up '{AUTHOR_NAME}' on Semantic Scholar...")
    data = _get("author/search", {
        "query": AUTHOR_NAME,
        "fields": "authorId,name,affiliations",
        "limit": 10,
    })
    candidates = data.get("data", [])

    # Prefer a candidate with a known affiliation keyword
    for candidate in candidates:
        affs = [a.get("name", "").lower() for a in candidate.get("affiliations", [])]
        if any(kw in aff for kw in AFFIL_KEYS for aff in affs):
            print(f"  ✓ Matched by affiliation: {candidate['name']} "
                  f"(id={candidate['authorId']})")
            return candidate["authorId"]

    # Fallback: first result with an exact name match
    for candidate in candidates:
        if candidate.get("name", "").lower() == AUTHOR_NAME.lower():
            print(f"  ✓ Matched by name: {candidate['name']} "
                  f"(id={candidate['authorId']})")
            return candidate["authorId"]

    if candidates:
        print(f"  ⚠ Using first result: {candidates[0]['name']} "
              f"(id={candidates[0]['authorId']})")
        return candidates[0]["authorId"]

    raise RuntimeError(f"Author '{AUTHOR_NAME}' not found on Semantic Scholar")


# ── Paper fetch ───────────────────────────────────────────────────
def fetch_all_papers(author_id: str) -> list:
    papers, offset = [], 0
    while True:
        data = _get(f"author/{author_id}/papers", {
            "fields": PAPER_FIELDS, "limit": 100, "offset": offset
        })
        batch = data.get("data", [])
        papers.extend(batch)
        print(f"  Fetched {len(papers)} papers so far...")
        if len(batch) < 100:
            break
        offset += 100
    return papers


# ── Paper classification ──────────────────────────────────────────
def _is_preprint(paper: dict) -> bool:
    types    = paper.get("publicationTypes") or []
    ext_ids  = paper.get("externalIds") or {}
    venue    = (paper.get("venue") or "").lower()
    is_arxiv = "ArXiv" in ext_ids
    is_published = (
        "JournalArticle" in types
        or "Conference"  in types
        or "Book"        in types
        or ext_ids.get("DOI")
    )
    if is_published:
        return False
    return is_arxiv or "Preprint" in types or re.search(r"arxiv|preprint|ssrn", venue) is not None


def paper_to_entry(paper: dict) -> dict:
    ext_ids   = paper.get("externalIds") or {}
    journal   = paper.get("journal") or {}
    authors   = [a.get("name", "") for a in (paper.get("authors") or [])]
    types     = paper.get("publicationTypes") or []

    # Best URL: DOI → arXiv → nothing
    url = ""
    if ext_ids.get("DOI"):
        url = f"https://doi.org/{ext_ids['DOI']}"
    elif ext_ids.get("ArXiv"):
        url = f"https://arxiv.org/abs/{ext_ids['ArXiv']}"

    # Best PDF
    pdf_url = ""
    oa = paper.get("openAccessPdf")
    if oa and oa.get("url"):
        pdf_url = oa["url"]
    elif ext_ids.get("ArXiv"):
        pdf_url = f"https://arxiv.org/pdf/{ext_ids['ArXiv']}"

    venue = paper.get("venue") or journal.get("name") or ""

    return {
        "title":       paper.get("title", ""),
        "authors":     ", ".join(authors),
        "venue":       venue,
        "year":        paper.get("year"),
        "url":         url,
        "pdf_url":     pdf_url,
        "arxiv_id":    ext_ids.get("ArXiv", ""),
        "doi":         ext_ids.get("DOI", ""),
        "citations":   paper.get("citationCount", 0),
        "is_preprint": _is_preprint(paper),
        "pub_types":   types,
    }


# ── YAML helpers ─────────────────────────────────────────────────
def _load_yaml(path: str):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_yaml(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False,
                  default_flow_style=False, width=120)


# ── Title normalisation for dedup ─────────────────────────────────
def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _word_overlap(a: str, b: str) -> int:
    return len(set(a.split()) & set(b.split()))


def _already_in_news(title: str, news_norms: list) -> bool:
    nt = _norm(title)
    return any(_word_overlap(nt, nn) >= 6 for nn in news_norms)


# ── News update ───────────────────────────────────────────────────
def update_news(new_pubs: list, old_pub_titles: set):
    """Prepend a news entry for every publication not seen before."""
    news = _load_yaml(NEWS_YML)
    if not isinstance(news, list):
        news = []

    news_norms = [_norm(item.get("text", "")[:120]) for item in news]
    added = 0

    for pub in new_pubs:
        title = pub.get("title", "").strip()
        if not title:
            continue
        # Skip if it was in the previous Scholar run
        if _norm(title) in old_pub_titles:
            continue
        # Skip if already mentioned in news
        if _already_in_news(title, news_norms):
            continue

        year    = pub.get("year") or datetime.utcnow().year
        # Use current month only when the paper was published this year
        # (Semantic Scholar only gives us year-level granularity)
        now = datetime.utcnow()
        month = now.strftime("%m") if year == now.year else "01"
        venue   = pub.get("venue", "")
        url     = pub.get("url", "") or pub.get("pdf_url", "")
        preprint = pub.get("is_preprint", False)

        emoji   = "📝" if preprint else "📄"
        kind    = "New preprint" if preprint else "New publication"
        text    = f"{kind}: [{title}]({url})" if url else f"{kind}: {title}"
        if venue:
            text += f" in *{venue}*"
        text += "!"

        entry = {"date": f"{year}-{month}", "emoji": emoji, "text": text}
        news.insert(0, entry)
        news_norms.insert(0, _norm(text[:120]))
        print(f"  + News entry: {title[:65]}...")
        added += 1

    if added:
        _save_yaml(NEWS_YML, news)
        print(f"  Wrote {added} new news entries to {NEWS_YML}")
    else:
        print("  No new news entries needed.")


# ── Graduated preprint detection ──────────────────────────────────
def report_graduated_preprints(pubs: list):
    """
    Identify arXiv preprints that now also appear as a published paper
    so the user can remove them from the manual Preprints section.
    """
    preprints  = [p for p in pubs if p.get("is_preprint")]
    published  = [p for p in pubs if not p.get("is_preprint")]
    pub_norms  = {_norm(p["title"]) for p in published if p.get("title")}

    graduated = []
    for pre in preprints:
        nt = _norm(pre.get("title", ""))
        # Check exact norm match OR high word overlap with any published title
        if nt in pub_norms or any(_word_overlap(nt, pn) >= 7 for pn in pub_norms):
            graduated.append(pre["title"])

    if graduated:
        print("\n⚠️  These preprints appear to have been published — "
              "consider removing them from the Preprints section in publications.md:")
        for t in graduated:
            print(f"    • {t}")
    return graduated


# ── Main ──────────────────────────────────────────────────────────
def main():
    # Load previous data for diff
    old_data      = _load_yaml(SCHOLAR_YML) or {}
    old_pubs      = old_data.get("publications", []) if isinstance(old_data, dict) else []
    old_pub_norms = {_norm(p.get("title", "")) for p in old_pubs if p.get("title")}

    # Fetch fresh data
    author_id = find_author_id()
    raw_papers = fetch_all_papers(author_id)
    print(f"  Total papers fetched: {len(raw_papers)}")

    pubs = [paper_to_entry(p) for p in raw_papers if p.get("title")]
    pubs.sort(key=lambda x: x.get("year") or 0, reverse=True)

    # Save scholar_pubs.yml
    _save_yaml(SCHOLAR_YML, {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%d"),
        "author_id":    author_id,
        "publications": pubs,
    })
    print(f"\nWrote {len(pubs)} publications to {SCHOLAR_YML}")

    # Update news.yml
    update_news(pubs, old_pub_norms)

    # Report graduated preprints
    report_graduated_preprints(pubs)


if __name__ == "__main__":
    main()
