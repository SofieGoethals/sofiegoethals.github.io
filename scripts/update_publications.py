#!/usr/bin/env python3
"""
Fetch Sofie Goethals' publications from Semantic Scholar and:

  1. Write _data/scholar_pubs.yml  — raw data + last_updated date
  2. Insert new pub-entry blocks into content/publications.md
     directly inside Journal / Conference / Preprints sections
  3. Update _data/news.yml with entries for newly detected papers
  4. Print a report of preprints that have since been published

Uses <!-- SYNC:journal -->, <!-- SYNC:conference -->, <!-- SYNC:preprints -->
as insertion anchors in publications.md.
"""

import os
import re
import sys
import time
from datetime import datetime

import requests
import yaml

# ── Config ────────────────────────────────────────────────────────
AUTHOR_NAME  = "Sofie Goethals"
AFFIL_KEYS   = ["antwerp", "columbia"]
SS_BASE      = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = (
    "title,year,venue,journal,authors,"
    "externalIds,openAccessPdf,publicationTypes,citationCount"
)

REPO_ROOT    = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SCHOLAR_YML  = os.path.join(REPO_ROOT, "_data", "scholar_pubs.yml")
NEWS_YML     = os.path.join(REPO_ROOT, "_data", "news.yml")
PUBS_MD      = os.path.join(REPO_ROOT, "content", "publications.md")


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
            time.sleep(0.5)
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

    for candidate in candidates:
        affs = [a.get("name", "").lower() for a in candidate.get("affiliations", [])]
        if any(kw in aff for kw in AFFIL_KEYS for aff in affs):
            print(f"  Matched by affiliation: {candidate['name']} (id={candidate['authorId']})")
            return candidate["authorId"]

    for candidate in candidates:
        if candidate.get("name", "").lower() == AUTHOR_NAME.lower():
            print(f"  Matched by name: {candidate['name']} (id={candidate['authorId']})")
            return candidate["authorId"]

    if candidates:
        print(f"  Using first result: {candidates[0]['name']} (id={candidates[0]['authorId']})")
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
    types   = paper.get("publicationTypes") or []
    ext_ids = paper.get("externalIds") or {}
    venue   = (paper.get("venue") or "").lower()
    if "JournalArticle" in types or "Conference" in types or "Book" in types:
        return False
    if ext_ids.get("DOI"):
        return False
    return bool(ext_ids.get("ArXiv") or "Preprint" in types or
                re.search(r"arxiv|preprint|ssrn", venue))


def _section_for(paper: dict) -> str:
    types = paper.get("publicationTypes") or []
    if "JournalArticle" in types:
        return "journal"
    if "Conference" in types:
        return "conference"
    if _is_preprint(paper):
        return "preprints"
    # Fallback: has DOI with no conference/journal type → treat as journal
    ext_ids = paper.get("externalIds") or {}
    if ext_ids.get("DOI"):
        return "journal"
    return "preprints"


def paper_to_entry(paper: dict) -> dict:
    ext_ids = paper.get("externalIds") or {}
    journal = paper.get("journal") or {}
    authors = [a.get("name", "") for a in (paper.get("authors") or [])]
    types   = paper.get("publicationTypes") or []

    url = ""
    if ext_ids.get("DOI"):
        url = f"https://doi.org/{ext_ids['DOI']}"
    elif ext_ids.get("ArXiv"):
        url = f"https://arxiv.org/abs/{ext_ids['ArXiv']}"

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
        "section":     _section_for(paper),
        "pub_types":   types,
    }


# ── Title normalisation for dedup ─────────────────────────────────
def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _word_overlap(a: str, b: str) -> int:
    return len(set(a.split()) & set(b.split()))


# ── Extract existing titles from publications.md ──────────────────
def existing_titles_in_md(content: str) -> set:
    """
    Return a set of normalised titles already present in publications.md.
    Matches both:
      <p><strong>Authors</strong> (year). Title. <em>Venue</em>.</p>
    and plain text between </strong> and the next <em> or end of sentence.
    """
    norms = set()
    # Extract the text between </strong>...<em> or </strong>....<br or end-of-line
    for m in re.finditer(r'</strong>\s*\([^)]+\)\.\s*(.+?)(?:<em>|\.?\s*</p>)', content, re.DOTALL):
        raw = m.group(1).strip().rstrip('.')
        norms.add(_norm(raw))
    # Also grab the full <p> text for broad matching
    for m in re.finditer(r'<p><strong>.+?</p>', content, re.DOTALL):
        norms.add(_norm(m.group(0)))
    return norms


# ── Build pub-entry HTML ──────────────────────────────────────────
def _html_for_pub(pub: dict) -> str:
    authors = pub.get("authors", "")
    year    = pub.get("year", "")
    title   = pub.get("title", "")
    venue   = pub.get("venue", "")
    url     = pub.get("url", "")
    pdf_url = pub.get("pdf_url", "")
    is_pre  = pub.get("is_preprint", False)

    year_str  = f" ({year})." if year else "."
    venue_str = f" <em>{venue}</em>." if venue else ""
    title_str = f'<a href="{url}" target="_blank">{title}</a>' if url else title

    lines = [
        '<div class="pub-entry">',
        f"<p><strong>{authors}</strong>{year_str} {title_str}.{venue_str}</p>",
        '<div class="pub-links">',
    ]

    if url:
        badge = "badge-arxiv" if "arxiv" in url else "badge-doi"
        icon  = "fas fa-archive" if "arxiv" in url else "fas fa-external-link-alt"
        label = "arXiv" if "arxiv" in url else "DOI"
        lines.append(f'  <a class="pub-link-badge {badge}" href="{url}" target="_blank">'
                     f'<i class="{icon}"></i> {label}</a>')

    if pdf_url and pdf_url != url:
        lines.append(f'  <a class="pub-link-badge badge-pdf" href="{pdf_url}" target="_blank">'
                     f'<i class="fas fa-file-pdf"></i> PDF</a>')

    lines += ["</div>", "</div>", ""]
    return "\n".join(lines)


# ── Insert new papers into publications.md ────────────────────────
def update_publications_md(new_pubs: list):
    with open(PUBS_MD, encoding="utf-8") as f:
        content = f.read()

    existing = existing_titles_in_md(content)
    added_by_section = {"journal": 0, "conference": 0, "preprints": 0}
    changed = False

    # Group new pubs by section, newest first
    by_section: dict[str, list] = {"journal": [], "conference": [], "preprints": []}
    for pub in new_pubs:
        title = pub.get("title", "").strip()
        if not title:
            continue
        nt = _norm(title)
        # Skip if title already in MD (exact or high-overlap match)
        if nt in existing or any(_word_overlap(nt, e) >= 6 for e in existing):
            continue
        section = pub.get("section", "preprints")
        if section in by_section:
            by_section[section].append(pub)

    for section, pubs in by_section.items():
        if not pubs:
            continue
        marker = f"<!-- SYNC:{section} -->"
        if marker not in content:
            print(f"  Warning: marker '{marker}' not found in publications.md — skipping {section}")
            continue

        # Sort by year descending so newest appears first
        pubs.sort(key=lambda p: p.get("year") or 0, reverse=True)

        block = ""
        for pub in pubs:
            html = _html_for_pub(pub)
            block += html
            print(f"  + {section}: {pub['title'][:65]}...")
            added_by_section[section] += 1

        content = content.replace(marker, block + marker)
        changed = True

    if changed:
        with open(PUBS_MD, "w", encoding="utf-8") as f:
            f.write(content)
        total = sum(added_by_section.values())
        print(f"  Inserted {total} new entries into publications.md "
              f"({added_by_section['journal']} journal, "
              f"{added_by_section['conference']} conference, "
              f"{added_by_section['preprints']} preprints)")
    else:
        print("  publications.md is already up to date.")


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


# ── News update ───────────────────────────────────────────────────
def _already_in_news(title: str, news_norms: list) -> bool:
    nt = _norm(title)
    return any(_word_overlap(nt, nn) >= 6 for nn in news_norms)


def update_news(new_pubs: list, old_pub_titles: set):
    news = _load_yaml(NEWS_YML)
    if not isinstance(news, list):
        news = []

    news_norms = [_norm(item.get("text", "")[:120]) for item in news]
    added = 0

    for pub in new_pubs:
        title = pub.get("title", "").strip()
        if not title:
            continue
        if _norm(title) in old_pub_titles:
            continue
        if _already_in_news(title, news_norms):
            continue

        year  = pub.get("year") or datetime.utcnow().year
        now   = datetime.utcnow()
        month = now.strftime("%m") if year == now.year else "01"
        url   = pub.get("url", "") or pub.get("pdf_url", "")
        venue = pub.get("venue", "")
        emoji = "📝" if pub.get("is_preprint") else "📄"
        kind  = "New preprint" if pub.get("is_preprint") else "New publication"
        text  = f"{kind}: [{title}]({url})" if url else f"{kind}: {title}"
        if venue:
            text += f" in *{venue}*"
        text += "!"

        entry = {"date": f"{year}-{month}", "emoji": emoji, "text": text}
        news.insert(0, entry)
        news_norms.insert(0, _norm(text[:120]))
        print(f"  + News: {title[:65]}...")
        added += 1

    if added:
        _save_yaml(NEWS_YML, news)
        print(f"  Wrote {added} new news entries to {NEWS_YML}")
    else:
        print("  No new news entries needed.")


# ── Graduated preprint detection ──────────────────────────────────
def report_graduated_preprints(pubs: list):
    preprints = [p for p in pubs if p.get("is_preprint")]
    published = [p for p in pubs if not p.get("is_preprint")]
    pub_norms = {_norm(p["title"]) for p in published if p.get("title")}

    graduated = []
    for pre in preprints:
        nt = _norm(pre.get("title", ""))
        if nt in pub_norms or any(_word_overlap(nt, pn) >= 7 for pn in pub_norms):
            graduated.append(pre["title"])

    if graduated:
        print("\n These preprints appear to have been published — "
              "consider removing them from the Preprints section in publications.md:")
        for t in graduated:
            print(f"    • {t}")
    return graduated


# ── Main ──────────────────────────────────────────────────────────
def main():
    old_data      = _load_yaml(SCHOLAR_YML) or {}
    old_pubs      = old_data.get("publications", []) if isinstance(old_data, dict) else []
    old_pub_norms = {_norm(p.get("title", "")) for p in old_pubs if p.get("title")}

    author_id  = find_author_id()
    raw_papers = fetch_all_papers(author_id)
    print(f"  Total papers fetched: {len(raw_papers)}")

    pubs = [paper_to_entry(p) for p in raw_papers if p.get("title")]
    pubs.sort(key=lambda x: x.get("year") or 0, reverse=True)

    # Save scholar_pubs.yml (used for "last synced" date in publications.md)
    _save_yaml(SCHOLAR_YML, {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%d"),
        "author_id":    author_id,
        "publications": pubs,
    })
    print(f"\nWrote {len(pubs)} publications to {SCHOLAR_YML}")

    # Insert new papers directly into publications.md
    print("\nUpdating publications.md...")
    update_publications_md(pubs)

    # Update news.yml
    print("\nUpdating news.yml...")
    update_news(pubs, old_pub_norms)

    # Report graduated preprints
    report_graduated_preprints(pubs)


if __name__ == "__main__":
    main()
