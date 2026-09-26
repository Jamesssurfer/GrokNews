# scripts/parser.py — GrokNews Critical Developments Report
#
# Converts ONE raw narrative report into the structured dict logger.py needs.
# Best-effort extraction for the style in GrokNews.txt:
#   - **Month Day, Year** date header
#   - Opening summary paragraph
#   - Numbered ### sections (Geopolitics, Trade Wars, Currency, Energy, etc.)
#   - Bold sub-headings inside sections
#   - Highest-priority indicators list
#   - Outlook summary
#
# Multiple stories in one file must be separated by a line containing only "===".

import re
from datetime import datetime, timezone

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _strip_refs(text):
    if not text:
        return ""
    t = text
    t = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1', t)
    t = re.sub(r'\[[\d,\.\s]+\]', '', t)
    t = re.sub(r'\[\s*\]', '', t)
    t = re.sub(r'\s{2,}', ' ', t).strip()
    if t and not t.endswith((".", "!", "?", '"')):
        t += "."
    return t


def _split_stories(raw_text):
    normalized = raw_text.replace("\r\n", "\n")
    parts = re.split(r'\n===\n|^===\n|\n===$', normalized)
    return [p.strip() for p in parts if p.strip()]


def _find_header_and_date(text):
    # Prefer bold date: **September 25, 2026**
    m = re.search(r'\*\*(\w+)\s+(\d{1,2}),\s*(\d{4})\*\*', text)
    if m:
        month_name, day, year = m.groups()
        month = MONTHS.get(month_name.lower())
        if month:
            try:
                weekday = datetime(int(year), month, int(day)).strftime("%A")
            except ValueError:
                weekday = "Unknown"
            header = f"{weekday}, {month_name} {day}, {year}'s Report"
            return header, (int(year), month, int(day))

    m = re.search(r'(\w+),\s*(\w+)\s+(\d{1,2}),\s*(\d{4})', text)
    if m:
        weekday, month_name, day, year = m.groups()
        month = MONTHS.get(month_name.lower())
        if month:
            header = f"{weekday}, {month_name} {day}, {year}'s Report"
            return header, (int(year), month, int(day))

    m = re.search(r'(\w+)\s+(\d{1,2}),\s*(\d{4})', text)
    if m:
        month_name, day, year = m.groups()
        month = MONTHS.get(month_name.lower())
        if month:
            try:
                weekday = datetime(int(year), month, int(day)).strftime("%A")
            except ValueError:
                weekday = "Unknown"
            header = f"{weekday}, {month_name} {day}, {year}'s Report"
            return header, (int(year), month, int(day))

    return None, None


def _opening_summary(text):
    body = re.sub(r'^===?\s*', '', text)
    body = re.sub(r'^\*\*[^*]+\*\*\s*', '', body)
    body = body.strip()
    m = re.search(r'\n###\s+', body)
    if m:
        body = body[:m.start()]
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', body) if p.strip()]
    if paragraphs:
        return _strip_refs(paragraphs[0])
    return ""


def _headline_from_summary(summary):
    if not summary:
        return ""
    m = re.match(r'^([^.!?]+[.!?])', summary)
    if m and len(m.group(1)) > 30:
        return m.group(1).strip()
    return summary[:140].rstrip() + ("..." if len(summary) > 140 else "")


def _parse_subsections(section_body):
    """Split a section body on **Bold Title** lines into subsections."""
    subsections = []
    # Allow match at start of body OR after a newline (first subhead often
    # sits flush at the top after the ### heading consumed trailing newlines).
    parts = re.split(r'(?:^|\n)\*\*([^*]+)\*\*\s*\n', section_body.strip())
    # parts[0] is preamble before first bold subhead; then (title, body, title, body, ...)
    if len(parts) == 1:
        text = _strip_refs(section_body.strip())
        if text:
            return [{"title": "", "text": text}]
        return []

    preamble = parts[0].strip()
    if preamble:
        subsections.append({"title": "", "text": _strip_refs(preamble)})

    i = 1
    while i < len(parts) - 1:
        title = parts[i].strip()
        body = parts[i + 1].strip()
        subsections.append({
            "title": title,
            "text": _strip_refs(body),
        })
        i += 2
    return subsections



def _parse_sections(text):
    """Extract numbered ### sections."""
    sections = []
    # Match ### N. Title  or  ### Title
    pattern = re.compile(
        r'###\s*(?:(\d+)\.\s*)?(.+?)\s*\n',
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    for idx, m in enumerate(matches):
        number = int(m.group(1)) if m.group(1) else idx + 1
        title = m.group(2).strip()
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()

        # Don't let monitoring/outlook leak into last numbered section
        # (those often appear after section 7 without a ### heading)
        if re.search(r'\*\*Highest-priority|\*\*Outlook summary\*\*', body, re.I):
            cut = re.search(r'\n\*\*(?:Highest-priority|Outlook summary)', body, re.I)
            if cut:
                body = body[:cut.start()].strip()

        subsections = _parse_subsections(body)
        sections.append({
            "number": number,
            "title": title,
            "subsections": subsections,
            "text": _strip_refs(body) if not any(s.get("title") for s in subsections) else "",
        })
    return sections


def _monitoring_priorities(text):
    items = []
    m = re.search(
        r'\*\*Highest-priority[^*]*\*\*\s*\n((?:\s*[-*•].+\n?)+)',
        text,
        re.IGNORECASE,
    )
    if m:
        for line in m.group(1).split('\n'):
            line = line.strip()
            if re.match(r'^[-*•]\s+', line):
                item = re.sub(r'^[-*•]\s+', '', line).strip()
                if item:
                    items.append(_strip_refs(item))
    return items


def _outlook(text):
    m = re.search(
        r'\*\*Outlook summary\*\*\s*\n(.+?)(?=\n\nThis report can be updated|\n\nLet me know|\Z)',
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return _strip_refs(m.group(1).strip())
    m = re.search(r'\*\*Outlook summary\*\*\s*:?\s*(.+?)(?=\n\n|\Z)', text, re.IGNORECASE | re.DOTALL)
    if m:
        return _strip_refs(m.group(1).strip())
    return ""


def parse_story(text):
    header, ymd = _find_header_and_date(text)
    if not header or not ymd:
        raise ValueError("could not find a date or Report header anywhere in this story")

    year, month, day = ymd
    timestamp = f"{year:04d}-{month:02d}-{day:02d}T20:00:00+00:00"

    summary = _opening_summary(text)
    headline = _headline_from_summary(summary)
    sections = _parse_sections(text)
    monitoring = _monitoring_priorities(text)
    outlook = _outlook(text)

    return {
        "timestamp": timestamp,
        "header": header,
        "headline": headline,
        "summary": summary,
        "sections": sections,
        "monitoring_priorities": monitoring,
        "outlook": outlook,
    }


def parse_stories(raw_text):
    events, errors = [], []
    for block in _split_stories(raw_text):
        try:
            events.append(parse_story(block))
        except Exception as e:
            snippet = block.strip().split("\n")[0][:80]
            errors.append((snippet, e))
    return events, errors
