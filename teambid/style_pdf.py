"""Tailor a member's own resume PDF in place: each job's bullets are reworded and reordered where they stand.

Reading: the text lines (with every letter's position) and the bullet signs (inside the line, a separate one-character
line, or a small drawn dot) give each confirmed bullet its lines. Laying out: a bullet that only moves keeps its own
lines, each word (or letter) at its original x; a reworded one wraps anew in the job's width; each job flows through
its own lines and page breaks. Fonts: the PDF's own font when it measures and reads back the letters as the original
did, else the same family installed online (or a metric-compatible one), else a wide-coverage font. Safety: a job is
reordered only when no bullet is fixed (each found whole with its own sign, no link, no italics or mixed styles), and
fixed bullets are never erased or redrawn; a job nothing changes in is left alone; links are put back after erasing;
every redrawn bullet must read back word for word, and every other word of the PDF must still be where it was, or the
build fails (and the RenderCV resume is used).
Bullets only for now: the headline, summary and skills of a PDF stay as they are.
Design: docs/superpowers/specs/2026-11-05-keep-original-style-design.md (PDF in place).
"""
import functools
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from statistics import median

from .style_text import key

BULLETS = set("•●▪◦‣∙·-–—*►➤✓✔○■□➢❖")
ROUND = set("•●∙\uf0b7")  # round signs a drawn dot can stand in for (U+F0B7: Word's Symbol-font bullet)
SANS = re.compile(r"(?i)helvetica|arial|nimbussan|liberationsans|calibri|carlito|roboto|inter|dejavusans|poppins|"
                  r"rubik|opensans|lato|sourcesans|segoe|verdana|tahoma|montserrat|sans")
LIGATURES = re.compile("[ﬀ-ﬆ]")
MIN_SPACE = 0.7          # justified text may squeeze its spaces this far, about as much as LaTeX does
FALLBACK = "DejaVu Sans"  # wide coverage (≈ → € ' ...), on every Ubuntu runner
# a PDF's font family -> the family to look for when the PDF's own copy can't be used (metric-compatible where it exists)
ALIAS = {"calibri": "Carlito", "cambria": "Caladea", "arial": "Liberation Sans", "helvetica": "Liberation Sans",
         "nimbussanl": "Liberation Sans", "nimbussans": "Liberation Sans", "times": "Liberation Serif",
         "timesnewroman": "Liberation Serif", "nimbusromno9l": "Liberation Serif", "couriernew": "Liberation Mono",
         "liberationsans": "Liberation Sans", "liberationserif": "Liberation Serif", "dejavusans": "DejaVu Sans",
         "opensans": "Open Sans", "sourcesanspro": "Source Sans Pro"}


def _fitz():
    import fitz
    return fitz


def _is_sign(text):
    t = text.strip()
    return bool(t) and all(c in BULLETS for c in t)


def _is_lead(span):
    """A span that begins with a typed sign and a space ("- Built", "• Built", "– Built"): Word's typed bullets and
    HTML-to-PDF resumes write the sign into the line's text."""
    t = span["text"]
    return len(t) > 2 and t[0] in BULLETS and t[1].isspace() and bool(t[2:].strip())


def _after_sign(chars):
    """How many characters a typed sign takes at the start of a span: the sign and the spaces after it."""
    n = 1
    while n < len(chars) and chars[n]["c"].isspace():
        n += 1
    return n


def _body(lines, mark, n):
    """Line n of a bullet as [(span, its characters)], without the bullet's own sign (and a typed sign's spaces)."""
    out = []
    for s in lines[n]["spans"]:
        cs = s["chars"]
        if n == 0 and mark and s is mark.get("span"):
            if mark["kind"] == "inline":
                continue
            if mark["kind"] == "lead":
                cs = cs[_after_sign(cs):]
        out.append((s, cs))
    return out


def _is_bold(span):
    return bool(span["flags"] & 16) or bool(re.search(r"(?i)bold|black|heavy|semi-?bold|demi", span["font"]))


def _plain(text):
    """Ligature characters spelled out (ﬁ -> fi): fonts other than the original may not have them, and ATS read fi."""
    return LIGATURES.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), text)


def family(name):
    """'ABCDEF+Calibri-Bold' -> 'Calibri', 'Roboto,Bold' -> 'Roboto', 'ArialMT' -> 'Arial'."""
    base = re.split(r"[-,]", (name or "").split("+")[-1])[0]
    return re.sub(r"(MT|PS)$", "", base)


@functools.lru_cache(maxsize=None)
def system_font(name, bold):
    """An installed font file of this family (or its metric-compatible stand-in), via fontconfig; None if none.
    Cached: every word of a redrawn bullet asks, and fc-match is a process each time."""
    fam = family(name)
    want = ALIAS.get(fam.replace(" ", "").lower(), fam)
    if not want or not shutil.which("fc-match"):
        return None
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}\n%{family}", f"{want}:weight={200 if bold else 80}"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    path, _, families = out.partition("\n")
    return path if path and want.replace(" ", "").lower() in families.replace(" ", "").lower() else None


def _roundtrip(buf, chars):
    """The characters this font draws AND reads back as themselves once re-embedded."""
    fitz = _fitz()
    chars = sorted(chars)
    with fitz.open() as d:
        p = d.new_page(width=40 * (len(chars) + 2), height=60)
        p.insert_font(fontname="F0", fontbuffer=buf)
        for n, c in enumerate(chars):
            p.insert_text((10 + n * 30, 40), c, fontname="F0", fontsize=12)
        got = [ch["c"] for b in p.get_text("rawdict")["blocks"] for l in b.get("lines", []) for s in l["spans"]
               for ch in s["chars"] if not ch["c"].isspace()]
    return {c for c, g in zip(chars, got) if c == g} if len(got) == len(chars) else set()


class Fonts:
    """Picks the font each piece of text is drawn with, and remembers what it learned."""

    def __init__(self, doc, lines, allow_embedded=True):
        self.doc, self.lines, self.allow = doc, lines, allow_embedded
        self.cache, self.good, self.trust, self.reads = {}, {}, {}, {}

    def _own(self, page_no, name):
        base = name.split("+")[-1]
        if base not in self.cache:
            self.cache[base] = None
            for f in self.doc[page_no].get_fonts():
                if f[3].split("+")[-1] == base:
                    try:
                        _, ext, _, buf = self.doc.extract_font(f[0])
                        if buf and ext not in ("n/a", ""):
                            self.cache[base] = (_fitz().Font(fontbuffer=buf), buf, f"tb{f[0]}")
                    except Exception:
                        pass
                    break
        return self.cache[base]

    def _trusted(self, name, font):
        """The PDF's own font measures its letters as the PDF placed them (some generators embed fonts whose widths
        disagree with how they were printed: then every redraw would come out unevenly spaced)."""
        base = name.split("+")[-1]
        if base not in self.trust:
            errs = []
            for l in self.lines:
                for s in l["spans"]:
                    if s["font"].split("+")[-1] != base:
                        continue
                    for a, b in zip(s["chars"], s["chars"][1:]):
                        if not a["c"].isspace() and not b["c"].isspace():
                            errs.append(abs(b["origin"][0] - a["origin"][0] - font.text_length(a["c"], fontsize=s["size"])))
                    if len(errs) > 400:
                        break
            self.trust[base] = bool(errs) and sum(e <= 0.35 for e in errs) >= 0.9 * len(errs)
        return self.trust[base]

    def own(self, page_no, name, text, sign=False):
        """The PDF's own font for text, when it's trusted and draws and reads back every character; else None.
        sign: a bullet sign, drawn alone at its own spot, so the letter-spacing trust doesn't apply (and a sign-only
        font has no letter pairs to measure)."""
        if not self.allow or not name or LIGATURES.search(text):
            return None            # a re-embedded font's ligature glyphs read back right but may not draw right
        f = self._own(page_no, name)
        if not f or (not sign and not self._trusted(name, f[0])):
            return None
        chars = {c for c in text if not c.isspace()}
        good, bad = self.good.setdefault(name.split("+")[-1], (set(), set()))
        todo = chars - good - bad
        if todo:
            ok = _roundtrip(f[1], {c for c in todo if f[0].has_glyph(ord(c))})
            good.update(ok)
            bad.update(todo - ok)
        return f if chars <= good else None

    def installed(self, name, bold, text):
        path = system_font(name, bold)
        if not path:
            return None
        if path not in self.cache:
            buf = Path(path).read_bytes()
            self.cache[path] = (_fitz().Font(fontbuffer=buf), buf, f"tbs{len(self.cache)}")
        f = self.cache[path]
        return f if all(f[0].has_glyph(ord(c)) for c in text if not c.isspace()) else None

    def pick(self, page_no, name, text, bold, own=True):
        """(fitz.Font, font file bytes or None, font name to draw with, is it the PDF's own font) for text."""
        f = self.own(page_no, name, text) if own else None
        if f:
            return f + (True,)
        f = self.installed(name, bold, _plain(text)) or self.installed(FALLBACK, bold, _plain(text))
        if f:
            return f + (False,)
        b14 = ("hebo" if bold else "helv") if SANS.search(name or "") else ("tibo" if bold else "tiro")
        return (_fitz().Font(b14), None, b14, False)


def _lines(doc):
    fitz = _fitz()
    out = []
    for pno, page in enumerate(doc):
        links = [l["from"] for l in page.get_links()]
        for b in page.get_text("rawdict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    s["text"] = "".join(c["c"] for c in s["chars"])
                spans = [s for s in l["spans"] if s["text"]]
                if spans:
                    r = fitz.Rect(l["bbox"])
                    out.append({"page": pno, "bbox": r, "spans": spans, "text": "".join(s["text"] for s in spans),
                                "link": any(r.intersects(k) for k in links)})
    return out


def _is_dot(dr):
    r = dr["rect"]
    return bool(dr.get("fill")) and 0.8 < r.width < 8 and 0.8 < r.height < 8 and abs(r.width - r.height) < 1.5


def _marks(doc, lines, drawings):
    """Bullet signs that aren't part of their text line: separate one-character lines, and small drawn dots."""
    marks = [{"page": l["page"], "rect": l["bbox"], "kind": "text", "span": l["spans"][0]} for l in lines if _is_sign(l["text"])]
    for pno, drs in enumerate(drawings):
        for dr in drs:
            if _is_dot(dr):
                marks.append({"page": pno, "rect": dr["rect"], "fill": dr["fill"],
                              "kind": "circle" if all(i[0] == "c" for i in dr["items"]) else "rect"})
    return marks


def _art_in(line, drawings):
    """Whether a drawing that isn't a dot sits inside this line: an underscore LaTeX draws as a rule, an underline,
    a strike-through. It would stay put while the line's words moved or changed. Drawings bigger than the line (a
    background, a table's border) aren't the line's, and stay put rightly."""
    lb = line["bbox"]
    return any(not _is_dot(dr) and r.width <= lb.width + 2 and r.height <= lb.height + 2
               and r.x0 < lb.x1 - 0.5 and r.x1 > lb.x0 + 0.5 and r.y0 < lb.y1 - 0.5 and r.y1 > lb.y0 + 0.5
               for dr in drawings[line["page"]] for r in [dr["rect"]])


def read(doc, pieces):
    """The confirmed bullets (keep_style.confirm) found in the PDF, by job.
    -> [{"id", "reorder", "bullets": [{"id", "text" (with **bold**), "piece", "lines", "mark", "link", "fixed"}], "_lines"}]
    A bullet is found only when it starts and ends exactly on line boundaries, over lines no other bullet claimed;
    anything else stays as it is. A bullet is fixed (never reworded, its job never reordered) when it holds a link,
    italics or mixed sizes or colors, a drawing (_art_in), or has no sign of its own."""
    lines = _lines(doc)
    drawings = [page.get_drawings() for page in doc]
    marks = _marks(doc, lines, drawings)
    text_lines = [l for l in lines if not _is_sign(l["text"])]
    # a typed sign ("* Built") isn't part of the bullet's words: key() drops "-" and "•" but not "*" or "►"
    keys = [key(l["text"][_after_sign(l["spans"][0]["chars"]):] if _is_lead(l["spans"][0]) else l["text"])
            for l in text_lines]
    starts, pos = [], 0
    for k in keys:
        starts.append(pos)
        pos += len(k)
    by_start = {s: n for n, s in enumerate(starts)}
    by_end = {s + len(k): n for n, (s, k) in enumerate(zip(starts, keys))}
    hay = "".join(keys)
    used = set()

    def spot(k, start):
        """Where k sits on whole lines that no other bullet claimed, searching from start; -1 if nowhere."""
        i = hay.find(k, start)
        while i >= 0:
            if i in by_start and i + len(k) in by_end and used.isdisjoint(range(by_start[i], by_end[i + len(k)] + 1)):
                return i
            i = hay.find(k, i + 1)
        return -1

    jobs, at = [], 0
    for ji, job in enumerate(pieces.get("jobs", [])):
        found = []
        for bi, text in enumerate(job.get("bullets", [])):
            k = key(text)
            if len(k) < 8:
                continue
            i = spot(k, at)
            if i < 0:
                i = spot(k, 0)
            if i < 0:
                continue
            a, z = by_start[i], by_end[i + len(k)]
            used.update(range(a, z + 1))
            ls = text_lines[a:z + 1]
            at = i + len(k)
            mark, sp0 = None, ls[0]["spans"][0]
            if _is_sign(sp0["text"]):
                mark = {"kind": "inline", "span": sp0}
            elif _is_lead(sp0):
                mark = {"kind": "lead", "span": sp0, "char": sp0["chars"][0]}
            else:
                lb = ls[0]["bbox"]
                for m in marks:
                    cy = (m["rect"].y0 + m["rect"].y1) / 2
                    if m["page"] == ls[0]["page"] and lb.y0 - 1 <= cy <= lb.y1 + 1 and m["rect"].x1 <= lb.x0 + 1 \
                            and lb.x0 - m["rect"].x1 < 25:
                        mark = m
                        break
            runs, first = [], None
            for n in range(len(ls)):
                for s, cs in _body(ls, mark, n):
                    first = first or s
                    runs.append(("".join(c["c"] for c in cs), _is_bold(s)))
                runs.append((" ", False))
            # a bold run's own spaces stay outside its marks: some exporters draw "using" then " C#" (space in bold)
            shown = "".join(f"{' ' if t[:1].isspace() else ''}**{t.strip()}**{' ' if t[-1:].isspace() else ''}"
                            if b and t.strip() else t for t, b in runs)
            shown = re.sub(r"\*\*(\s*)\*\*", r"\1", re.sub(r"\s+", " ", shown)).strip()
            spans = [s for l in ls for s in l["spans"] if s["text"].strip() and not _is_sign(s["text"])]
            styled = any(s["flags"] & 2 or abs(s["size"] - first["size"]) > 0.6 or s["color"] != first["color"] for s in spans)
            link = any(l["link"] for l in ls)
            art = any(_art_in(l, drawings) for l in ls)
            # no sign of its own: the piece may be only part of a bullet, and rewording it would garble the rest
            found.append({"id": f"r{ji}b{bi}", "text": shown, "piece": text, "lines": ls, "mark": mark,
                          "link": link, "fixed": styled or link or art or not mark})
        if found:
            reorder = not any(b["fixed"] for b in found)
            jobs.append({"id": f"r{ji}", "bullets": found, "reorder": reorder, "_lines": lines})
    return jobs


def find(path, pieces):
    """The confirmed pieces found in the member's PDF, as the doc keep_style works with (bullets only for now)."""
    fitz = _fitz()
    with fitz.open(path) as d:
        jobs, pages = read(d, pieces), d.page_count
    meta = pieces.get("jobs", [])
    return {"ext": ".pdf", "_path": str(path), "_pieces": pieces, "pages": pages, "headline": None, "summary": None,
            "skills": [], "skills_move": False,
            "jobs": [{"id": j["id"], "reorder": j["reorder"],
                      **{k: meta[int(j["id"][1:])].get(k, "") for k in ("title", "company", "start", "end")},
                      "bullets": [{"id": b["id"], "text": b["text"], "fixed": b["fixed"], "piece": b["piece"]}
                                  for b in j["bullets"]]} for j in jobs]}


def _text_x(b, n):
    """Where line n of bullet b's text starts, after its sign: its first letter's x."""
    return next((c["origin"][0] for s, cs in _body(b["lines"], b["mark"], n) if not _is_sign(s["text"])
                 for c in cs if not c["c"].isspace()), b["lines"][n]["bbox"].x0)


def _style(job):
    """How the job's bullets are set: size, width, justification, line spacing per page, where it may flow. The text
    style is the job's most common one (by letters), so a bold or colored lead-in doesn't become every rewording's.
    Where the text starts comes from the bullets that may be redrawn: a fixed one (a paragraph without a sign, say)
    can start somewhere else, even where the other bullets' signs are."""
    ls = [l for b in job["bullets"] for l in b["lines"]]
    base = lambda l: l["spans"][0]["origin"][1]
    first = job["bullets"][0]["lines"][0]
    free = [b for b in job["bullets"] if not b["fixed"]] or job["bullets"]
    x_first = _text_x(free[0], 0)
    weight = {}
    for b in job["bullets"]:
        for n in range(len(b["lines"])):
            for s, cs in _body(b["lines"], b["mark"], n):
                if not _is_sign(s["text"]):
                    k = (_is_bold(s), s["font"], s["size"], s["color"])
                    weight[k] = weight.get(k, 0) + sum(not c["c"].isspace() for c in cs)
    common = lambda bold: max(((v, k) for k, v in weight.items() if k[0] == bold), default=(0, None))[1]
    body = common(False) or common(True)
    bold = common(True)
    size = body[2]
    full = [l for b in job["bullets"] for l in b["lines"][:-1]]
    right = median([l["bbox"].x1 for l in full]) if full else max(l["bbox"].x1 for l in ls)
    justified = len(full) >= 3 and sum(abs(l["bbox"].x1 - right) < 1.5 for l in full) >= 0.8 * len(full)
    regions, gaps, pitches = {}, {}, {}
    for l in ls:
        top, bottom = regions.get(l["page"], (base(l), base(l)))
        regions[l["page"]] = (min(top, base(l)), max(bottom, base(l)))
    for p, n in zip(job["bullets"], job["bullets"][1:]):
        if p["lines"][-1]["page"] == n["lines"][0]["page"]:
            gaps.setdefault(n["lines"][0]["page"], []).append(base(n["lines"][0]) - base(p["lines"][-1]))
    for b in job["bullets"]:
        for a, c in zip(b["lines"], b["lines"][1:]):
            if a["page"] == c["page"]:
                pitches.setdefault(c["page"], []).append(base(c) - base(a))
    allp = [v for vs in pitches.values() for v in vs] or [size * 1.25]
    allg = [v for vs in gaps.values() for v in vs] or [median(allp)]
    pitch_at = {pg: median(pitches.get(pg) or allp) for pg in regions}       # LaTeX stretches gaps per page
    between_at = {pg: median(gaps.get(pg) or allg) for pg in regions}
    slack = {}
    for pg, (top, bottom) in regions.items():
        # a page's last line may sit a little lower when nothing is printed below it there (a moved bullet gap can
        # land on the page break); the job's last page never grows, the next heading follows it
        below = any(l["page"] == pg and l["bbox"].y0 > bottom + 2 for l in job["_lines"])
        slack[pg] = 0.5 if pg == max(regions) or below else (between_at[pg] - pitch_at[pg]) + 0.5
    later = [_text_x(b, n) for b in free for n in range(1, len(b["lines"]))]
    return {"size": size, "font": body[1], "bold_font": bold[1] if bold else body[1], "color": body[3],
            "right": right, "justified": justified, "regions": regions, "pitch_at": pitch_at, "between_at": between_at,
            "slack": slack, "x_first": x_first, "x_next": median(later) if later else x_first,
            "page": first["page"]}


def _words(text):
    """'Built **C#** APIs,' -> [[('Built', False)], [('C#', True), (',', False)], ...]"""
    words, cur = [], []
    for n, seg in enumerate(_plain(str(text)).split("**")):
        for m, part in enumerate(seg.split(" ")):
            if m > 0 and cur:
                words.append(cur)
                cur = []
            if part:
                cur.append((part, n % 2 == 1))
    if cur:
        words.append(cur)
    return words


def _new_lines(text, st, fonts, bullet=None):
    """A reworded bullet wrapped into the job's width: lines of (x, text, font, size, color, x-scale). It starts where
    its own bullet's text starts (bullet given), so it stays clear of its own sign. None when one word alone is wider
    than the column (it would run past the right edge)."""
    size, words = st["size"], _words(text)
    x_first = _text_x(bullet, 0) if bullet else st["x_first"]
    x_next = median(_text_x(bullet, n) for n in range(1, len(bullet["lines"]))) \
        if bullet and len(bullet["lines"]) > 1 else st["x_next"]
    letters = {b: "".join(t for w in words for t, bb in w if bb == b) for b in (False, True)}
    fp = {b: fonts.pick(st["page"], st["bold_font"] if b else st["font"], letters[b] + " ", b) for b in (False, True)}
    width = lambda r: fp[r[1]][0].text_length(r[0], fontsize=size)
    space = fp[False][0].text_length(" ", fontsize=size)
    squeeze = MIN_SPACE if st["justified"] else 1.0
    avail = lambda: st["right"] - (x_first if not lines else x_next)
    lines, cur, w = [], [], 0.0
    for word in words:
        ww = sum(width(r) for r in word)
        if cur and w + space * squeeze + ww > avail() + 0.01:
            lines.append(cur)
            cur, w = [], 0.0
        if not cur and ww > avail() + 0.01:
            return None
        w = w + (space * squeeze if cur else 0) + ww
        cur.append(word)
    if cur:
        lines.append(cur)
    out = []
    for n, line in enumerate(lines):
        x0 = x_first if n == 0 else x_next
        ws = [sum(width(r) for r in word) for word in line]
        gap = space
        if st["justified"] and n < len(lines) - 1 and len(line) > 1:
            gap = (st["right"] - x0 - sum(ws)) / (len(line) - 1)
        items, x = [], x0
        for word, wwid in zip(line, ws):
            rx = x
            for t, b in word:
                items.append((rx, t, fp[b], size, st["color"], 1.0))
                rx += width((t, b))
            x += wwid + gap
        out.append(items)
    return out


def _old_lines(bullet, fonts):
    """A moved bullet's own lines, each word where it was. In the PDF's own font: as printed (letter by letter where
    a letter advanced differently). In another font: ligatures spelled out and the word fitted to its original width
    (squeezed as needed, stretched by 15% at most: never wider than its own space, so words can't overlap or touch).
    None when a word would have to be squeezed below 60%: that font can't stand in for this one."""
    out = []
    for n, l in enumerate(bullet["lines"]):
        items = []
        for s, cs in _body(bullet["lines"], bullet["mark"], n):
            word = []
            for c in cs + [None]:
                if c is not None and not c["c"].isspace():
                    word.append(c)
                    continue
                if word:
                    t = "".join(ch["c"] for ch in word)
                    adv = [b["origin"][0] - a["origin"][0] for a, b in zip(word, word[1:])]
                    # two letters at one spot: one glyph (a ligature like fl) read back as several letters; that
                    # word can't be redrawn letter by letter in the PDF's font
                    shared = any(a < 0.5 for a in adv)
                    f = fonts.pick(l["page"], s["font"], t, _is_bold(s), own=not shared)
                    x0, size = word[0]["origin"][0], s["size"]
                    if f[3]:
                        mine = [f[0].text_length(ch["c"], fontsize=size) for ch in word[:-1]]
                        if all(abs(a - m) <= 0.35 for a, m in zip(adv, mine)):
                            items.append((x0, t, f, size, s["color"], 1.0))
                        else:
                            items += [(ch["origin"][0], ch["c"], f, size, s["color"], 1.0) for ch in word]
                    else:
                        t = _plain(t)
                        want = word[-1]["bbox"][2] - x0
                        got = f[0].text_length(t, fontsize=size)
                        if got and want / got < 0.6:
                            return None
                        items.append((x0, t, f, size, s["color"], min(want / got, 1.15) if got else 1.0))
                word = []
        out.append(items)
    return out


def _flow(job, order, texts, changed, st, fonts):
    """The job's bullets in this order through its own lines and page breaks: [(page, y, items, bullet or None)],
    bullet set on a bullet's first line. None when they don't fit (or a bullet can't be set: _new_lines/_old_lines)."""
    pages = sorted(st["regions"])
    by_id = {b["id"]: b for b in job["bullets"]}
    pi, y, first, out = 0, st["regions"][pages[0]][0], True, []
    for bid in order:
        b = by_id[bid]
        lines = _new_lines(texts[bid], st, fonts, b) if bid in changed else _old_lines(b, fonts)
        if lines is None:
            return None
        for n, items in enumerate(lines):
            if not first:
                y += st["between_at"][pages[pi]] if n == 0 else st["pitch_at"][pages[pi]]
            first = False
            if y > st["regions"][pages[pi]][1] + st["slack"][pages[pi]]:
                pi += 1
                if pi >= len(pages):
                    return None
                y = st["regions"][pages[pi]][0]
            out.append((pages[pi], y, items, b if n == 0 else None))
    return out


def _fix_tounicode(doc, names):
    """PyMuPDF writes a re-embedded font's glyph->character table from the font's cmap, where the hyphen glyph also
    stands for the soft hyphen and the space for the no-break space, and it picks those: "end-to-end" would read back
    as "end\\xadto\\xadend". Point them at "-" and " ", in the fonts this edit inserted, and only as the character a glyph
    maps TO (never a glyph number that happens to be AD or A0), and only in one-glyph entries (bfchar): in a bfrange
    the last value is where a whole run of glyphs starts, and moving it would shift every glyph in the run."""
    def one(m):
        t = re.sub(rb"(<[0-9A-Fa-f]+>\s+)<00[Aa][Dd]>(?=\s*[\r\n])", rb"\1<002D>", m.group(0))
        return re.sub(rb"(<[0-9A-Fa-f]+>\s+)<00[Aa]0>(?=\s*[\r\n])", rb"\1<0020>", t)

    for xref in {f[0] for page in doc for f in page.get_fonts() if f[4] in names}:
        t = doc.xref_get_key(xref, "ToUnicode")
        if t[0] != "xref":
            continue
        n = int(t[1].split()[0])
        s = doc.xref_stream(n)
        new = re.sub(rb"beginbfchar.*?endbfchar", one, s, flags=re.S)
        if new != s:
            doc.update_stream(n, new)


def _lay_out(jobs, plan, fonts):
    """Where each job's bullets go. -> (todo, kept, order): todo = [(bullets to erase and redraw, flow)], kept =
    reworded bullet ids that keep their text, order = {job id: its bullet ids as they'll stand}."""
    todo, kept, used = [], [], {}
    for job in jobs:
        ids = [b["id"] for b in job["bullets"]]
        used[job["id"]] = ids
        fixed = {b["id"] for b in job["bullets"] if b["fixed"]}
        asked = {i for i in ids if plan.get("text", {}).get(i)}
        kept += sorted(asked & fixed)                       # a fixed bullet's text never changes
        changed = asked - fixed
        if fixed == set(ids):
            continue                                        # nothing in this job may be redrawn
        st = _style(job)
        own = {b["id"]: b["text"] for b in job["bullets"]}
        texts = {**own, **{i: plan["text"][i] for i in changed}}
        if fixed:
            # a job with a fixed bullet stays where it is and its fixed bullets aren't touched: a rewording of another
            # bullet there is used only if it keeps exactly its number of lines (it's redrawn on them, from where its
            # own text starts)
            for b in job["bullets"]:
                if b["id"] in changed:
                    new = _new_lines(texts[b["id"]], st, fonts, b)
                    if new and len(new) == len(b["lines"]):
                        todo.append(([b], [(l["page"], l["spans"][0]["origin"][1], items, b if n == 0 else None)
                                           for n, (l, items) in enumerate(zip(b["lines"], new))]))
                    else:
                        kept.append(b["id"])
            continue
        order = plan.get("order", {}).get(job["id"]) if job["reorder"] else None
        order = order if order and sorted(order) == sorted(ids) else ids
        # rewordings that don't fit go back to their own text one at a time, the one that grew most first; a job left
        # with nothing to change isn't erased and redrawn at all
        grew = lambda i: (len(texts[i].replace("**", "")) - len(own[i].replace("**", "")), i)
        ch, flow = set(changed), None
        while order != ids or ch:
            flow = _flow(job, order, texts, ch, st, fonts)
            if flow or not ch:
                break
            ch.remove(max(ch, key=grew))
        if flow:
            kept += sorted(changed - ch)
            todo.append((job["bullets"], flow))
            used[job["id"]] = list(order)
        else:
            kept += sorted(changed)                         # nothing fits: the job stays exactly as it is
    return todo, kept, used


def _words_at(page):
    """The page's words as [(Rect, text)], each box the letters' own outline: the font's line-height box would reach
    into the next line where the leading is tight."""
    fitz = _fitz()
    return [(fitz.Rect(w[:4]), w[4])
            for w in page.get_text("words", flags=fitz.TEXTFLAGS_WORDS | fitz.TEXT_ACCURATE_BBOXES)]


def _untouched(doc, todo):
    """Every word of the PDF outside the bullet lines and signs about to be erased: {page: [(Rect, text)]}."""
    fitz = _fitz()
    gone = {}
    for bullets, _ in todo:
        for b in bullets:
            for l in b["lines"]:
                gone.setdefault(l["page"], []).append(l["bbox"] + (-0.5, -0.5, 0.5, 0.5))
            m = b["mark"]
            if m and m["kind"] == "text":
                gone.setdefault(m["page"], []).append(m["rect"] + (-0.5, -0.5, 0.5, 0.5))
    inside = lambda pno, r: any(g.contains(fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)) for g in gone.get(pno, []))
    return {pno: [(r, t) for r, t in _words_at(page) if not inside(pno, r)] for pno, page in enumerate(doc)}


def _disturbed(doc, before, drawn):
    """Words outside the redrawn bullets that are gone, moved or changed since before (_untouched), or that a drawn
    line lies on (0.3 pt of touching allowed)."""
    bad, over = [], {}
    for rects in drawn.values():
        for p, r in rects:
            over.setdefault(p, []).append(r)
    for pno, words in before.items():
        now = {}
        for r, t in _words_at(doc[pno]):
            now.setdefault(t, []).append(r)
        for r, t in words:
            if not any(max(abs(a - b) for a, b in zip(r, q)) <= 1.0 for q in now.get(t, [])):
                bad.append(f"lost {t!r}")
            elif any((r + (0.3, 0.3, -0.3, -0.3)).intersects(d) for d in over.get(pno, [])):
                bad.append(f"drawn over {t!r}")
    return bad


def _glyph_box(x0, x1, y, size):
    """A sign's box from its advance and baseline, set like a drawn line's (_draw), so the two compare."""
    return _fitz().Rect(x0, y - 0.75 * size, x1, y + 0.25 * size)


def _sign_at(b):
    """Where bullet b's sign is in the PDF: (page, box)."""
    m = b["mark"]
    if m["kind"] in ("circle", "rect"):
        return m["page"], _fitz().Rect(m["rect"])
    cs = [m["char"]] if m["kind"] == "lead" else [c for c in m["span"]["chars"] if not c["c"].isspace()]
    box = _glyph_box(min(c["bbox"][0] for c in cs), max(c["bbox"][2] for c in cs), cs[0]["origin"][1], m["span"]["size"])
    return m.get("page", b["lines"][0]["page"]), box


def _signs(jobs, todo):
    """Each job's signs of the bullets that stay where they are: {job id: ([its bullet ids], [(page, box, bullet id,
    a drawn dot that must still be there)])}. _draw adds the signs it draws."""
    erased = {b["id"] for bullets, _ in todo for b in bullets}
    return {j["id"]: ([b["id"] for b in j["bullets"]],
                      [(*_sign_at(b), b["id"], b["mark"]["kind"] in ("circle", "rect"))
                       for b in j["bullets"] if b["mark"] and b["id"] not in erased]) for j in jobs}


def _signs_hit(doc, drawn, signs):
    """Signs a drawn line of their job lies on (0.3 pt of touching allowed), and drawn dots left alone that are gone or
    moved. key() ignores "•" and "-", so the read-back can't see a sign printed over a word. Signs that are text are
    words, so _disturbed already checks the ones left alone are still there."""
    bad, art = [], {}
    for ids, boxes in signs.values():
        rects = [(p, r) for i in ids for p, r in drawn.get(i, [])]
        for p, box, bid, dot in boxes:
            if any(q == p and (box + (0.3, 0.3, -0.3, -0.3)).intersects(r) for q, r in rects):
                bad.append(f"text over the sign of {bid}")
            if dot:
                if p not in art:
                    art[p] = [dr["rect"] for dr in doc[p].get_drawings() if dr.get("fill")]
                if not any(max(abs(a - c) for a, c in zip(box, r)) <= 1.0 for r in art[p]):
                    bad.append(f"lost the sign of {bid}")
    return bad


def _erase(doc, todo):
    """Erase the bullets about to be redrawn: drawn dot signs first (and only the line art they cover whole), then the
    text in thin bands that leave all line art alone, so underlines and rules in bullet lines survive. Links that
    erasing deletes are put back."""
    fitz = _fitz()
    dots, bands = {}, {}
    # the x-height band: it meets every letter of the line (MuPDF erases each letter whose box it touches) but never a
    # letter of the next line, whose boxes reach into this line when the leading is tight
    band = lambda x0, x1, y, size: fitz.Rect(x0 - 0.5, y - 0.62 * size, x1 + 0.5, y - 0.08 * size)
    for bullets, _ in todo:
        for b in bullets:
            for l in b["lines"]:
                bands.setdefault(l["page"], []).append(band(l["bbox"].x0, l["bbox"].x1, l["spans"][0]["origin"][1],
                                                            max(s["size"] for s in l["spans"])))
            m = b["mark"]
            if m and m["kind"] == "text":
                bands.setdefault(m["page"], []).append(band(m["rect"].x0, m["rect"].x1, m["span"]["origin"][1],
                                                            m["span"]["size"]))
            elif m and m["kind"] in ("circle", "rect"):
                r = m["rect"]
                dots.setdefault(m["page"], []).append(fitz.Rect(r.x0 - 0.3, r.y0 - 0.3, r.x1 + 0.3, r.y1 + 0.3))
    for pno, page in enumerate(doc):
        if pno not in dots and pno not in bands:
            continue
        links = page.get_links()
        for rects, art in ((dots, fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED), (bands, fitz.PDF_REDACT_LINE_ART_NONE)):
            if rects.get(pno):
                for r in rects[pno]:
                    page.add_redact_annot(r)
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=art)
        have = {(round(l["from"].x0), round(l["from"].y0), l.get("uri"), l.get("page")) for l in page.get_links()}
        for l in links:
            if (round(l["from"].x0), round(l["from"].y0), l.get("uri"), l.get("page")) not in have:
                page.insert_link(l)


def _reads_back(f, text, seen):
    """Font f (as Fonts has them) draws text so that it reads back as itself in the tailored PDF. A font can give one
    glyph several characters and PyMuPDF may write another one ("·" in Arial reads back as "ꞏ", glued to the next
    word); a built-in font only has Latin-1. Signs aren't read back after drawing, so this is checked first."""
    if (f[2], text) not in seen:
        if not f[1]:
            seen[f[2], text] = all(ord(c) < 256 for c in text)
        else:
            fitz = _fitz()
            with fitz.open() as d:
                p = d.new_page()
                p.insert_font(fontname="tbs0", fontbuffer=f[1])
                p.insert_text((20, 40), text, fontname="tbs0", fontsize=12)
                _fix_tounicode(d, {"tbs0"})                 # as the tailored PDF gets it
                with fitz.open("pdf", d.tobytes()) as again:
                    seen[f[2], text] = again[0].get_text().strip() == text
    return seen[f[2], text]


def _sign(page, b, dy, fonts, put):
    """Draw bullet b's sign moved down by dy, keeping its glyph: the PDF's own font (the standard Symbol font built in,
    when the PDF didn't embed it), else DejaVu Sans, each only if the sign reads back as itself, else (for a round
    sign) a dot of about its size, else the Symbol font's bullet. A typed sign ("- ") is text like the rest of its
    line, drawn as fonts.pick has it. -> the box it was drawn in (_glyph_box for text)."""
    fitz = _fitz()
    m, l0 = b["mark"], b["lines"][0]
    if m["kind"] == "circle":
        r = fitz.Rect(m["rect"]) + (0, dy, 0, dy)
        page.draw_circle((r.x0 + r.width / 2, r.y0 + r.height / 2), r.width / 2, color=None, fill=m["fill"])
        return r
    if m["kind"] == "rect":
        r = fitz.Rect(m["rect"]) + (0, dy, 0, dy)
        page.draw_rect(r, color=None, fill=m["fill"])
        return r
    s, pg = m["span"], m.get("page", l0["page"])
    if m["kind"] == "lead":
        ch = m["char"]
        t = ch["c"]
        ways = [fonts.own(pg, s["font"], t, sign=True), fonts.pick(pg, s["font"], t, _is_bold(s))]
    else:
        ch = next(c for c in s["chars"] if not c["c"].isspace())
        t = s["text"].strip()
        # the standard Symbol font a PDF needn't embed is that same font built in (its bullet reads back as "·")
        symbol = (fitz.Font("symb"), None, "symb") if family(s["font"]).lower() == "symbol" else None
        ways = [fonts.own(pg, s["font"], t, sign=True), symbol, fonts.installed(FALLBACK, False, t)]
    f = next((w for w in ways if w and _reads_back(w, t, fonts.reads)), None)
    x, y, size = ch["origin"][0], ch["origin"][1] + dy, s["size"]
    if not f and set(t) <= ROUND:
        # a bullet's dot is about two thirds of its advance wide and sits about a third of the size above the line
        bb = fitz.Rect(ch["bbox"])
        d = min(0.7 * bb.width, 0.45 * size)
        c = fitz.Point(bb.x0 + bb.width / 2, y - 0.32 * size)
        page.draw_circle(c, d / 2, color=None, fill=fitz.sRGB_to_pdf(s["color"]))
        return fitz.Rect(c.x - d / 2, c.y - d / 2, c.x + d / 2, c.y + d / 2)
    if not f:
        t, f = "•", (fitz.Font("symb"), None, "symb")
    put(page, x, y, t, f, size, s["color"])
    return _glyph_box(x, x + f[0].text_length(t, fontsize=size), y, size)


def _draw(doc, todo, fonts, signs):
    """Draw each flow: its words, and each bullet's sign moved with its first line (added to signs, see _signs). ->
    (drawn, names of the fonts inserted): drawn = {bullet id: [(page, rect)] of its drawn lines}."""
    fitz = _fitz()
    inserted, drawn = set(), {}
    job_of = {i: j for j, (ids, _) in signs.items() for i in ids}

    def put(page, x, y, t, f, size, color, sx=1.0):
        if f[1] and (page.number, f[2]) not in inserted:
            page.insert_font(fontname=f[2], fontbuffer=f[1])
            inserted.add((page.number, f[2]))
        morph = (fitz.Point(x, y), fitz.Matrix(sx, 1)) if abs(sx - 1) > 0.002 else None
        page.insert_text((x, y), t, fontname=f[2], fontsize=size, color=fitz.sRGB_to_pdf(color), morph=morph)

    helv = (fitz.Font("helv"), None, "helv", False)

    def space(page, x, y, width, size, color):
        """A real space in the gap between two words drawn apart. Readers (ATS parsers too) otherwise guess spaces
        from the gaps, and MuPDF never guesses one after "→" or "≈". Helvetica's space: every reader has it, and
        it's squeezed to the gap so it never reaches the next word."""
        sx = min(width / helv[0].text_length(" ", fontsize=size), 1.0)
        put(page, x, y, " ", helv, size, color, max(sx, 0.05))

    for bullets, flow in todo:
        current = None
        for pno, y, items, b in flow:
            page = doc[pno]
            current = b or current
            if items:
                x0 = min(i[0] for i in items)
                x1 = max(i[0] + i[2][0].text_length(i[1], fontsize=i[3]) * i[5] for i in items)
                size = max(i[3] for i in items)
                drawn.setdefault(current["id"], []).append((pno, fitz.Rect(x0 - 0.5, y - 0.75 * size, x1 + 0.5, y + 0.25 * size)))
            if b and b["mark"]:
                box = _sign(page, b, y - b["lines"][0]["spans"][0]["origin"][1], fonts, put)
                signs[job_of[b["id"]]][1].append((pno, box, b["id"], False))
            end = None
            for x, t, f, size, color, sx in items:
                if end is not None and x - end > 0.1 * size:
                    space(page, end, y, x - end, size, color)
                put(page, x, y, t, f, size, color, sx)
                end = x + f[0].text_length(t, fontsize=size) * sx
    return drawn, {name for _, name in inserted}


def _render(path, pieces, plan, allow_embedded):
    """Draw the plan into a fresh copy of the PDF. -> (doc, todo, kept, drawn, order, before, signs): todo, kept and
    order as _lay_out has them, drawn as _draw has it, before = the words left alone (_untouched), signs = every
    job's signs as they stand now (_signs)."""
    fitz = _fitz()
    doc = fitz.open(path)
    try:
        jobs = read(doc, pieces)
        fonts = Fonts(doc, jobs[0]["_lines"] if jobs else [], allow_embedded)
        todo, kept, order = _lay_out(jobs, plan, fonts)
        for bullets, _ in todo:
            for b in bullets:
                if b["mark"] and b["mark"].get("span"):     # read each sign's font now: erasing can drop it
                    fonts._own(b["mark"].get("page", b["lines"][0]["page"]), b["mark"]["span"]["font"])
        before, signs = _untouched(doc, todo), _signs(jobs, todo)
        _erase(doc, todo)
        drawn, inserted = _draw(doc, todo, fonts, signs)
        doc.subset_fonts()
        _fix_tounicode(doc, inserted)
        return doc, todo, kept, drawn, order, before, signs
    except Exception:
        doc.close()                                 # Windows keeps an open file locked
        raise


def _wrong(doc, todo, kept, drawn, plan, links_before, before, signs):
    """What doesn't read back as it should: each redrawn bullet whose words, read from where they were drawn, aren't
    exactly its text's words (so two words glued together or one split apart count), "links" if one was lost, each
    word outside the redrawn bullets that's gone, moved or drawn over (_disturbed), and each sign drawn over or lost
    (_signs_hit). Clip rects make this independent of reading order, so two-column resumes check right too."""
    bad = []
    for bullets, _ in todo:
        for b in bullets:
            if b["id"] not in drawn:
                continue
            new = plan.get("text", {}).get(b["id"]) if b["id"] not in kept and not b["fixed"] else None
            got = [key(w[4]) for p, r in drawn[b["id"]] for w in doc[p].get_text("words", clip=r)]
            want = [key(w) for w in _plain((new or b["text"]).replace("**", "")).split()]
            if [g for g in got if g] != [w for w in want if w]:
                bad.append(b["id"])
    if sum(len(p.get_links()) for p in doc) != links_before:
        bad.append("links")
    return bad + _disturbed(doc, before, drawn) + _signs_hit(doc, drawn, signs)


def build(doc, plan, folder, base):
    """Write the tailored PDF into folder. -> {"pdf", "pages", "paper", "kept": [bullet ids whose rewording didn't
    fit and kept their text], "order": {job id: its bullet ids as drawn (the original order where it stayed)}}.
    Raises ValueError when the result doesn't read back, even without the PDF's own fonts."""
    fitz = _fitz()
    with fitz.open(doc["_path"]) as d:
        links_before = sum(len(p.get_links()) for p in d)
    bad = []
    for allow in (True, False):
        out, todo, kept, drawn, order, before, signs = _render(doc["_path"], doc["_pieces"], plan, allow)
        try:
            bad = _wrong(out, todo, kept, drawn, plan, links_before, before, signs)
            if not bad:
                folder = Path(folder)
                folder.mkdir(parents=True, exist_ok=True)
                pdf = folder / f"{base}.pdf"
                out.save(pdf, garbage=3, deflate=True)
                width, pages = out[0].rect.width, out.page_count
                return {"pdf": str(pdf), "pages": pages, "paper": "A4" if abs(width - 595) < 6 else "Letter",
                        "kept": kept, "order": order}
        finally:
            out.close()
    raise ValueError(f"the tailored PDF didn't read back as written ({', '.join(bad[:4])})")

