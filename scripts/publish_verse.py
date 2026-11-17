"""Publish today's Open Heavens memory verse to verses.json.

Runs on GitHub Actions every night. It only reads the verse *reference*
(e.g. "Psalm 40:2") from two public Open Heavens sites, checks they agree,
then takes the verse *text* from the public-domain KJV bundled in this repo.
"""
import datetime, html, json, os, re, sys, urllib.request
from zoneinfo import ZoneInfo

BOOKS = ["Genesis","Exodus","Leviticus","Numbers","Deuteronomy","Joshua","Judges","Ruth","1 Samuel","2 Samuel","1 Kings","2 Kings","1 Chronicles","2 Chronicles","Ezra","Nehemiah","Esther","Job","Psalm","Proverbs","Ecclesiastes","Song of Solomon","Isaiah","Jeremiah","Lamentations","Ezekiel","Daniel","Hosea","Joel","Amos","Obadiah","Jonah","Micah","Nahum","Habakkuk","Zephaniah","Haggai","Zechariah","Malachi","Matthew","Mark","Luke","John","Acts","Romans","1 Corinthians","2 Corinthians","Galatians","Ephesians","Philippians","Colossians","1 Thessalonians","2 Thessalonians","1 Timothy","2 Timothy","Titus","Philemon","Hebrews","James","1 Peter","2 Peter","1 John","2 John","3 John","Jude","Revelation"]
CHUNKS = [5, 17, 22, 39, 43, 44, 58, 66]          # last book number in each b/KJV-<n>.json
ALIASES = {"psalms": "psalm", "song of songs": "song of solomon", "songs of solomon": "song of solomon",
           "revelations": "revelation", "canticles": "song of solomon"}
ROMAN = {"i": "1", "ii": "2", "iii": "3", "first": "1", "second": "2", "third": "3", "1st": "1", "2nd": "2", "3rd": "3"}

SOURCES = [
    ("flatimes.com", "https://flatimes.com/category/open-heavens/feed/"),
    ("flatimes.com", "https://flatimes.com/feed/"),
    ("openheavens.com.ng", "https://www.openheavens.com.ng/feeds/posts/default?alt=rss&max-results=25"),
    ("openheavensdaily.com", "https://www.openheavensdaily.com/feeds/posts/default?alt=rss&max-results=25"),
    ("openheavensdaily.com", "https://www.openheavensdaily.com/feed/"),
    ("rccgonline.org", "https://rccgonline.org/feed/"),
]

BOOK_RE = "|".join(sorted({re.escape(b) for b in BOOKS} | {"Psalms", "Song of Songs", "Revelations"}, key=len, reverse=True))
REF_RE = re.compile(r"(?:(1|2|3|I{1,3}|First|Second|Third|1st|2nd|3rd)\s*)?(" + BOOK_RE.replace(r"1\ ", "").replace(r"2\ ", "").replace(r"3\ ", "") + r")\s*(\d{1,3})\s*[:.]\s*(\d{1,3})(?:\s*[-–—]\s*(\d{1,3}))?", re.I)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (memorize verse bot; github.com/franciscaoganyaoroge/memorize)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def book_index(prefix, name):
    n = name.lower().strip()
    n = ALIASES.get(n, n)
    if prefix:
        n = ROMAN.get(prefix.lower(), prefix) + " " + n
    for i, b in enumerate(BOOKS):
        if b.lower() == n:
            return i
    return None


def find_reference(text):
    """Return (book_index, chapter, verse, verse_end) from the MEMORISE line, or None."""
    t = plain(text)
    m = re.search(r"MEMORI[SZ]E\s*[:\-–]?(.{0,400})", t, re.I)
    if not m:
        return None
    for r in REF_RE.finditer(m.group(1)):
        bi = book_index(r.group(1), r.group(2))
        if bi is not None:
            v1 = int(r.group(4)); v2 = int(r.group(5)) if r.group(5) else None
            return (bi, int(r.group(3)), v1, v2 if v2 and v2 > v1 else None)
    return None


def plain(text):
    # feeds often carry the post HTML escaped (&lt;p&gt;), so unescape, strip tags, and repeat
    t = text
    for _ in range(2):
        t = re.sub(r"<[^>]+>", " ", html.unescape(t))
    return re.sub(r"\s+", " ", t)


def find_after(label_re, text, maxlen=200):
    m = re.search(label_re + r"\s*[:\-–]?\s*(.{0," + str(maxlen) + r"})", text, re.I)
    return m.group(1) if m else ""


def details(body):
    """Topic-independent extras: the Bible reading reference and the Bible in One Year reading (references only)."""
    t = plain(body)
    read = None
    seg = find_after(r"\bREAD\b", t, 120)
    r = REF_RE.search(seg)
    if r:
        bi = book_index(r.group(1), r.group(2))
        if bi is not None:
            v1 = int(r.group(4)); v2 = int(r.group(5)) if r.group(5) else None
            read = [bi, int(r.group(3)), v1, v2 if v2 and v2 > v1 else v1]
    byear = find_after(r"BIBLE\s+IN\s+ONE\s+YEAR", t, 60)
    byear = re.split(r"\s{2,}|\b(?:MESSAGE|HYMN|PRAYER|ACTION|KEY|Open Heaven)\b", byear)[0].strip(" .:-–") if byear else ""
    if not re.search(r"\d", byear or ""): byear = ""
    return read, byear[:60]


def items(feed_xml):
    for it in re.findall(r"<item\b.*?</item>", feed_xml, re.S | re.I):
        title = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", (re.search(r"<title>(.*?)</title>", it, re.S) or [None, ""])[1]))
        yield title, it


def reference_from(feed_url, day):
    """Find today's post (title like 'Open Heaven 16 November 2026') in a feed and read its memory verse."""
    pats = [f"{day.day} {day:%B} {day.year}", f"{day.day}th {day:%B} {day.year}", f"{day:%B} {day.day}, {day.year}"]
    feed = fetch(feed_url)
    for title, body in items(feed):
        tl = title.lower()
        if "open heaven" in tl and "teen" not in tl and "prayer" not in tl and any(p.lower() in tl for p in pats):
            ref = find_reference(body)
            if ref:
                topic = title.split("–")[-1].split(" - ")[-1].strip()
                read, byear = details(body)
                return ref, topic, title, read, byear
    return None


def kjv_text(bi, ch, v1, v2):
    book = bi + 1
    chunk = next(i for i, last in enumerate(CHUNKS) if book <= last)
    data = json.load(open(f"b/KJV-{chunk}.json", encoding="utf-8"))
    verses = list(data[str(book)][ch - 1])
    if book == 19 and v1 == 1:   # Psalms: drop the heading ("A Psalm of David.") that this data puts in verse 1
        verses[0] = re.sub(r"^(?:(?:To the chief Musician|A Psalm|A Song|Maschil|Michtam|Shiggaion|A Prayer|Of David|A Praise)[^.]*\.\s*)+", "", verses[0])
    return " ".join(verses[v1 - 1:(v2 or v1)]).strip()


def ref_str(bi, ch, v1, v2):
    return f"{BOOKS[bi]} {ch}:{v1}{'-' + str(v2) if v2 else ''} (KJV)"


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    day = datetime.datetime.now(ZoneInfo("America/Chicago")).date()
    if os.environ.get("FOR_DATE"):
        day = datetime.date.fromisoformat(os.environ["FOR_DATE"])
    d = day.isoformat()
    feed = json.load(open("verses.json", encoding="utf-8"))
    existing = next((f for f in feed if f.get("d") == d), None)
    if existing and existing.get("topic") and not dry:
        print(f"{d}: already published with details, nothing to do.")
        return 0

    found = {}
    for site, url in SOURCES:
        if site in found:
            continue
        try:
            r = reference_from(url, day)
            if r:
                found[site] = r
                print(f"{site}: {ref_str(*r[0])}  (topic: {r[1]})")
            else:
                print(f"{site}: today's post not found in {url}")
        except Exception as e:
            print(f"{site}: could not read {url}: {e}")

    refs = {r[0] for r in found.values()}
    if not refs:
        print("No source has today's memory verse yet. Not publishing.")
        return 1
    if len(refs) > 1:
        print("Sources disagree on the reference. Not publishing:", {s: ref_str(*r[0]) for s, r in found.items()})
        return 1
    ref = refs.pop()
    if len(found) < 2:
        print(f"Only one source ({list(found)[0]}) had today's verse; publishing it.")

    text = kjv_text(*ref)
    entry = {"r": ref_str(*ref), "t": text, "d": d}
    best = next(iter(found.values()))
    topic, read, byear = best[1], best[3], best[4]
    if topic and len(topic) <= 80 and not re.search(r"open heaven|\d{4}", topic, re.I): entry["topic"] = topic
    if read:
        b, c, v1, v2 = read
        entry["read"] = f"{BOOKS[b]} {c}:{v1}" + (f"-{v2}" if v2 != v1 else "")
        entry["readRef"] = [b + 1, c, v1, v2]
    if byear: entry["byear"] = byear
    print("Entry:", json.dumps(entry, ensure_ascii=False))
    if dry:
        print("Dry run: not writing.")
        return 0
    # if today's verse is already there (e.g. published by hand), just add the extra details to it

    if existing and existing.get("r") and existing["r"] != entry["r"]:
        # Francisca chose a different verse by hand: keep her verse, only add the day's details
        entry = {**existing, **{k: v for k, v in entry.items() if k not in ("r", "t")}}
    feed = [f for f in feed if f.get("d") != d]
    feed.insert(0, entry)
    feed.sort(key=lambda f: f["d"], reverse=True)
    json.dump(feed[:60], open("verses.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a").write(f"ref={entry['r']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
