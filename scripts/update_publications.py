#!/usr/bin/env python3
"""
Fetch publications from Google Scholar and:
  1. Write _data/scholar_pubs.yml with the full publication list
  2. Add news entries to _data/news.yml for any newly detected publications
  3. Remove preprints from _data/publications_preprints.yml that have since been published

Google Scholar profile: https://scholar.google.com/citations?user=3yM14pcAAAAJ
"""

import yaml
import time
import sys
import os
import re
from datetime import datetime

SCHOLAR_ID = "3yM14pcAAAAJ"
REPO_ROOT   = os.path.join(os.path.dirname(__file__), "..")
SCHOLAR_YML = os.path.join(REPO_ROOT, "_data", "scholar_pubs.yml")
NEWS_YML    = os.path.join(REPO_ROOT, "_data", "news.yml")

# Preprint arXiv IDs that are known to be published (won't appear as preprint news)
KNOWN_PUBLISHED_ARXIV = set()


# ── helpers ──────────────────────────────────────────────────────────────────

def _load_yaml(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _normalise_title(title):
    """Lowercase, strip punctuation for fuzzy comparison."""
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def _titles_in_news(news_items):
    """Return set of normalised title fragments already in news.yml."""
    titles = set()
    for item in news_items:
        text = item.get("text", "")
        titles.add(_normalise_title(text[:80]))
    return titles


def _already_in_news(title, news_titles):
    """Fuzzy check: is a publication title already mentioned in news?"""
    norm = _normalise_title(title[:80])
    for t in news_titles:
        # 6-word overlap is enough
        words_a = set(norm.split())
        words_b = set(t.split())
        if len(words_a & words_b) >= 6:
            return True
    return False


# ── Google Scholar fetch ──────────────────────────────────────────────────────

def fetch_publications():
    try:
        from scholarly import scholarly, ProxyGenerator
    except ImportError:
        print("ERROR: Install scholarly with:  pip install scholarly")
        sys.exit(1)

    print(f"Fetching Google Scholar profile for ID: {SCHOLAR_ID}")
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
                "title":     bib.get("title", ""),
                "authors":   bib.get("author", ""),
                "venue":     bib.get("venue", bib.get("journal", bib.get("booktitle", ""))),
                "year":      int(bib.get("pub_year", 0)) if bib.get("pub_year") else None,
                "abstract":  bib.get("abstract", ""),
                "url":       filled.get("pub_url", ""),
                "eprint":    filled.get("eprint_url", ""),
                "citations": filled.get("num_citations", 0),
                "is_preprint": bool(re.search(r"arxiv|preprint|biorxiv|ssrn", bib.get("venue", ""), re.I)),
            }
            publications.append(entry)
            print(f"  ✓ {entry['title'][:70]}...")
            time.sleep(1)
        except Exception as e:
            print(f"  ✗ Could not fill publication: {e}")
            continue

    publications.sort(key=lambda x: x.get("year") or 0, reverse=True)
    return publications


# ── Detect new publications and update news.yml ───────────────────────────────

def update_news(new_pubs, old_pubs):
    """Add news.yml entries for publications that are new since the last run."""
    old_titles = {_normalise_title(p.get("title", "")) for p in old_pubs}

    news_data  = _load_yaml(NEWS_YML)
    news_items = news_data if isinstance(news_data, list) else []
    news_titles = _titles_in_news(news_items)

    added = 0
    for pub in new_pubs:
        title = pub.get("title", "")
        if not title:
            continue
        norm = _normalise_title(title)
        # Only add if truly new (not in previous Scholar run) AND not already in news
        if norm in old_titles:
            continue
        if _already_in_news(title, news_titles):
            continue

        year  = pub.get("year") or datetime.utcnow().year
        month = datetime.utcnow().strftime("%m")
        venue = pub.get("venue", "")
        url   = pub.get("url", "") or pub.get("eprint", "")

        is_preprint = pub.get("is_preprint", False)
        emoji = "📄" if not is_preprint else "📝"
        pub_type = "New preprint" if is_preprint else "New publication"

        if url:
            text = f"{pub_type}: [{title}]({url})"
        else:
            text = f"{pub_type}: {title}"
        if venue:
            text += f" in *{venue}*"
        text += "!"

        entry = {
            "date":  f"{year}-{month}",
            "emoji": emoji,
            "text":  text,
        }
        # Prepend to news list (most recent first)
        news_items.insert(0, entry)
        news_titles.add(_normalise_title(text[:80]))
        print(f"  + News entry added: {title[:60]}...")
        added += 1

    if added > 0:
        _save_yaml(NEWS_YML, news_items)
        print(f"Added {added} news entries to {NEWS_YML}")
    else:
        print("No new news entries needed.")


# ── Remove graduated preprints ────────────────────────────────────────────────

def flag_graduated_preprints(publications):
    """
    Print a report of arXiv papers that also appear as journal/conference
    publications — these are preprints that have since been published and
    should be manually removed from the Preprints section in publications.md.
    """
    preprints   = [p for p in publications if p.get("is_preprint")]
    published   = [p for p in publications if not p.get("is_preprint")]
    pub_titles  = {_normalise_title(p.get("title", "")) for p in published}

    graduated = []
    for pre in preprints:
        norm = _normalise_title(pre.get("title", ""))
        words = set(norm.split())
        for pt in pub_titles:
            pt_words = set(pt.split())
            if len(words & pt_words) >= 6:
                graduated.append(pre["title"])
                break

    if graduated:
        print("\n⚠️  The following preprints appear to have been published "
              "and can be removed from the Preprints section in publications.md:")
        for t in graduated:
            print(f"    • {t}")
    return graduated


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Load previous publications for diffing
    old_data = _load_yaml(SCHOLAR_YML)
    old_pubs = old_data.get("publications", []) if isinstance(old_data, dict) else []

    # Fetch fresh data
    pubs = fetch_publications()

    # Write updated scholar_pubs.yml
    _save_yaml(SCHOLAR_YML, {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%d"),
        "scholar_id":   SCHOLAR_ID,
        "publications": pubs,
    })
    print(f"\nWrote {len(pubs)} publications to {SCHOLAR_YML}")

    # Update news
    update_news(pubs, old_pubs)

    # Report graduated preprints
    flag_graduated_preprints(pubs)
