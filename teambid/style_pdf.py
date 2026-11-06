"""Tailor a member's own resume PDF in place: each job's bullets are reworded and reordered where they stand.

Reading: the text lines (with every letter's position) and the bullet signs (inside the line, a separate one-character
line, or a small drawn dot) give each confirmed bullet its lines. Laying out: a bullet that only moves keeps its own
lines, each word (or letter) at its original x; a reworded one wraps anew in the job's width; each job flows through
its own lines and page breaks. Fonts: the PDF's own font when it measures and reads back the letters as the original
did, else the same family installed online (or a metric-compatible one), else a wide-coverage font. Safety: a job is
reordered only when every bullet was found whole with its own sign and none holds a link; links are put back after
erasing; every redrawn bullet must read back as its text, or the build fails (and the RenderCV resume is used).
Bullets only for now: the headline, summary and skills of a PDF stay as they are.
Design: docs/superpowers/specs/2026-11-05-keep-original-style-design.md (PDF in place).
"""
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from statistics import median

from .style_text import key

BULLETS = set("•●▪◦‣∙·-–—*►➤✓✔○■□➢❖")
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


def _is_bold(span):
    return bool(span["flags"] & 16) or bool(re.search(r"(?i)bold|black|heavy|semi-?bold|demi", span["font"]))


def _plain(text):
    """Ligature characters spelled out (ﬁ -> fi): fonts other than the original may not have them, and ATS read fi."""
    return LIGATURES.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), text)


def family(name):
    """'ABCDEF+Calibri-Bold' -> 'Calibri', 'Roboto,Bold' -> 'Roboto', 'ArialMT' -> 'Arial'."""
    base = re.split(r"[-,]", (name or "").split("+")[-1])[0]
    return re.sub(r"(MT|PS)$", "", base)


def system_font(name, bold):
    """An installed font file of this family (or its metric-compatible stand-in), via fontconfig; None if none."""
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
    d = fitz.open()
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
        self.cache, self.good, self.trust = {}, {}, {}

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

    def own(self, page_no, name, text):
        """The PDF's own font for text, when it's trusted and draws and reads back every character; else None."""
        if not self.allow or not name or LIGATURES.search(text):
            return None            # a re-embedded font's ligature glyphs read back right but may not draw right
        f = self._own(page_no, name)
        if not f or not self._trusted(name, f[0]):
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


def _marks(doc, lines):
    """Bullet signs that aren't part of their text line: separate one-character lines, and small drawn dots."""
    marks = [{"page": l["page"], "rect": l["bbox"], "kind": "text", "span": l["spans"][0]} for l in lines if _is_sign(l["text"])]
    for pno, page in enumerate(doc):
        for dr in page.get_drawings():
            r = dr["rect"]
            if dr.get("fill") and 0.8 < r.width < 8 and 0.8 < r.height < 8 and abs(r.width - r.height) < 1.5:
                marks.append({"page": pno, "rect": r, "fill": dr["fill"],
                              "kind": "circle" if all(i[0] == "c" for i in dr["items"]) else "rect"})
    return marks


def read(doc, pieces):
    """The confirmed bullets (keep_style.confirm) found in the PDF, by job.
    -> [{"id", "reorder", "bullets": [{"id", "text" (with **bold**), "piece", "lines", "mark", "link", "fixed"}], "_lines"}]
    A bullet is found only when it starts and ends exactly on line boundaries; anything else stays as it is."""
    lines = _lines(doc)
    marks = _marks(doc, lines)
    text_lines = [l for l in lines if not _is_sign(l["text"])]
    keys = [key(l["text"]) for l in text_lines]
    starts, pos = [], 0
    for k in keys:
        starts.append(pos)
        pos += len(k)
    by_start = {s: n for n, s in enumerate(starts)}
    by_end = {s + len(k): n for n, (s, k) in enumerate(zip(starts, keys))}
    hay = "".join(keys)
    jobs, at = [], 0
    for ji, job in enumerate(pieces.get("jobs", [])):
        found = []
        for bi, text in enumerate(job.get("bullets", [])):
            k = key(text)
            if len(k) < 8:
                continue
            i = hay.find(k, at)
            if i < 0:
                i = hay.find(k)
            if i < 0 or i not in by_start or i + len(k) not in by_end:
                continue
            ls = text_lines[by_start[i]:by_end[i + len(k)] + 1]
            at = i + len(k)
            mark, sp0 = None, ls[0]["spans"][0]
            if _is_sign(sp0["text"]):
                mark = {"kind": "inline", "span": sp0}
            else:
                lb = ls[0]["bbox"]
                for m in marks:
                    cy = (m["rect"].y0 + m["rect"].y1) / 2
                    if m["page"] == ls[0]["page"] and lb.y0 - 1 <= cy <= lb.y1 + 1 and m["rect"].x1 <= lb.x0 + 1 \
                            and lb.x0 - m["rect"].x1 < 25:
                        mark = m
                        break
            runs, first = [], None
            for l in ls:
                for s in l["spans"]:
                    if mark and mark["kind"] == "inline" and s is mark["span"]:
                        continue
                    first = first or s
                    runs.append((s["text"], _is_bold(s)))
                runs.append((" ", False))
            shown = "".join(f"**{t.strip()}**{' ' if t.endswith(' ') else ''}" if b and t.strip() else t for t, b in runs)
            shown = re.sub(r"\*\*(\s*)\*\*", r"\1", re.sub(r"\s+", " ", shown)).strip()
            spans = [s for l in ls for s in l["spans"] if s["text"].strip() and not _is_sign(s["text"])]
            styled = any(s["flags"] & 2 or abs(s["size"] - first["size"]) > 0.6 or s["color"] != first["color"] for s in spans)
            found.append({"id": f"r{ji}b{bi}", "text": shown, "piece": text, "lines": ls, "mark": mark,
                          "link": any(l["link"] for l in ls), "fixed": styled or any(l["link"] for l in ls)})
        if found:
            reorder = all(b["mark"] for b in found) and not any(b["link"] for b in found)
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


def _style(job):
    """How the job's bullets are set: size, width, justification, line spacing per page, where it may flow."""
    ls = [l for b in job["bullets"] for l in b["lines"]]
    base = lambda l: l["spans"][0]["origin"][1]
    first = job["bullets"][0]["lines"][0]
    t0 = next(s for s in first["spans"] if s["text"].strip() and not _is_sign(s["text"]))
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
    allp = [v for vs in pitches.values() for v in vs] or [t0["size"] * 1.25]
    allg = [v for vs in gaps.values() for v in vs] or [median(allp)]
    pitch_at = {pg: median(pitches.get(pg) or allp) for pg in regions}       # LaTeX stretches gaps per page
    between_at = {pg: median(gaps.get(pg) or allg) for pg in regions}
    slack = {}
    for pg, (top, bottom) in regions.items():
        # a page's last line may sit a little lower when nothing is printed below it there (a moved bullet gap can
        # land on the page break); the job's last page never grows, the next heading follows it
        below = any(l["page"] == pg and l["bbox"].y0 > bottom + 2 for l in job["_lines"])
        slack[pg] = 0.5 if pg == max(regions) or below else (between_at[pg] - pitch_at[pg]) + 0.5
    later = [l["spans"][0]["origin"][0] for b in job["bullets"] for l in b["lines"][1:]]
    bold = next((s["font"] for l in ls for s in l["spans"] if _is_bold(s)), None)
    return {"size": t0["size"], "font": t0["font"], "bold_font": bold or t0["font"], "color": t0["color"],
            "right": right, "justified": justified, "regions": regions, "pitch_at": pitch_at, "between_at": between_at,
            "slack": slack, "x_first": t0["origin"][0], "x_next": median(later) if later else t0["origin"][0],
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


def _new_lines(text, st, fonts):
    """A reworded bullet wrapped into the job's width: lines of (x, text, font, size, color, x-scale)."""
    size, words = st["size"], _words(text)
    letters = {b: "".join(t for w in words for t, bb in w if bb == b) for b in (False, True)}
    fp = {b: fonts.pick(st["page"], st["bold_font"] if b else st["font"], letters[b] + " ", b) for b in (False, True)}
    width = lambda r: fp[r[1]][0].text_length(r[0], fontsize=size)
    space = fp[False][0].text_length(" ", fontsize=size)
    squeeze = MIN_SPACE if st["justified"] else 1.0
    lines, cur, w = [], [], 0.0
    for word in words:
        avail = st["right"] - (st["x_first"] if not lines else st["x_next"])
        ww = sum(width(r) for r in word)
        if cur and w + space * squeeze + ww > avail + 0.01:
            lines.append(cur)
            cur, w = [], 0.0
        w = w + (space * squeeze if cur else 0) + ww
        cur.append(word)
    if cur:
        lines.append(cur)
    out = []
    for n, line in enumerate(lines):
        x0 = st["x_first"] if n == 0 else st["x_next"]
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
    a letter advanced differently). In another font: ligatures spelled out and the word fitted to its original width."""
    out = []
    for n, l in enumerate(bullet["lines"]):
        items = []
        for s in l["spans"]:
            if n == 0 and bullet["mark"] and bullet["mark"]["kind"] == "inline" and s is bullet["mark"]["span"]:
                continue
            word = []
            for c in s["chars"] + [None]:
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
                        sx = want / got if got and 0.85 <= want / got <= 1.15 else 1.0
                        items.append((x0, t, f, size, s["color"], sx))
                word = []
        out.append(items)
    return out


def _flow(job, order, texts, changed, st, fonts):
    """The job's bullets in this order through its own lines and page breaks: [(page, y, items, bullet or None)],
    bullet set on a bullet's first line. None when they don't fit."""
    pages = sorted(st["regions"])
    by_id = {b["id"]: b for b in job["bullets"]}
    pi, y, first, out = 0, st["regions"][pages[0]][0], True, []
    for bid in order:
        b = by_id[bid]
        lines = _new_lines(texts[bid], st, fonts) if bid in changed else _old_lines(b, fonts)
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
    maps TO (never a glyph number that happens to be AD or A0)."""
    for xref in {f[0] for page in doc for f in page.get_fonts() if f[4] in names}:
        t = doc.xref_get_key(xref, "ToUnicode")
        if t[0] != "xref":
            continue
        n = int(t[1].split()[0])
        s = doc.xref_stream(n)
        new = re.sub(rb"(<[0-9A-Fa-f]+>\s+)<00[Aa][Dd]>(?=\s*[\r\n])", rb"\1<002D>", s)
        new = re.sub(rb"(<[0-9A-Fa-f]+>\s+)<00[Aa]0>(?=\s*[\r\n])", rb"\1<0020>", new)
        if new != s:
            doc.update_stream(n, new)


def _render(path, pieces, plan, allow_embedded):
    """Draw the plan into a fresh copy of the PDF. -> (doc, todo, kept, drawn): todo = [(bullets, flow)] drawn,
    kept = reworded bullet ids that didn't fit, drawn = {bullet id: [(page, rect)] of its drawn lines}."""
    fitz = _fitz()
    doc = fitz.open(path)
    jobs = read(doc, pieces)
    fonts = Fonts(doc, jobs[0]["_lines"] if jobs else [], allow_embedded)
    todo, kept = [], []
    for job in jobs:
        st = _style(job)
        ids = [b["id"] for b in job["bullets"]]
        order = plan.get("order", {}).get(job["id"]) if job["reorder"] else None
        order = order if order and sorted(order) == sorted(ids) else ids
        texts = {b["id"]: b["text"] for b in job["bullets"]}
        changed = {i for i in ids if plan.get("text", {}).get(i)} - {b["id"] for b in job["bullets"] if b["fixed"]}
        texts.update({i: plan["text"][i] for i in changed})
        if any(b["link"] for b in job["bullets"]):
            # a job with a linked bullet stays where it is: a reworded bullet changes only if it keeps its exact lines
            for b in job["bullets"]:
                if b["id"] in changed:
                    new = _new_lines(texts[b["id"]], st, fonts)
                    if len(new) == len(b["lines"]):
                        todo.append(([b], [(l["page"], l["spans"][0]["origin"][1], items, b if n == 0 else None)
                                           for n, (l, items) in enumerate(zip(b["lines"], new))]))
                    else:
                        kept.append(b["id"])
            continue
        for ch, od in ((changed, order), (set(), order), (set(), ids)):
            flow = _flow(job, od, texts, ch, st, fonts)
            if flow:
                kept += sorted(changed - ch)
                todo.append((job["bullets"], flow))
                break
    vector = set()
    for bullets, flow in todo:
        for b in bullets:
            for l in b["lines"]:
                r = l["bbox"]
                doc[l["page"]].add_redact_annot(fitz.Rect(r.x0 - 0.5, r.y0 + 0.8, r.x1 + 0.5, r.y1 - 0.8))
            m = b["mark"]
            if m and m["kind"] != "inline":
                r = m["rect"]
                doc[m["page"]].add_redact_annot(fitz.Rect(r.x0 - 0.3, r.y0 - 0.3, r.x1 + 0.3, r.y1 + 0.3))
                if m["kind"] != "text":
                    vector.add(m["page"])
    for pno, page in enumerate(doc):
        links = page.get_links()                     # erasing text under a link deletes the link: put them back
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED if pno in vector
                              else fitz.PDF_REDACT_LINE_ART_NONE)
        have = {(round(l["from"].x0), round(l["from"].y0), l.get("uri"), l.get("page")) for l in page.get_links()}
        for l in links:
            if (round(l["from"].x0), round(l["from"].y0), l.get("uri"), l.get("page")) not in have:
                page.insert_link(l)
    inserted, drawn = set(), {}

    def put(page, pno, x, y, t, f, size, color, sx=1.0):
        if f[1] and (pno, f[2]) not in inserted:
            page.insert_font(fontname=f[2], fontbuffer=f[1])
            inserted.add((pno, f[2]))
        morph = (fitz.Point(x, y), fitz.Matrix(sx, 1)) if abs(sx - 1) > 0.002 else None
        page.insert_text((x, y), t, fontname=f[2], fontsize=size, color=fitz.sRGB_to_pdf(color), morph=morph)

    for bullets, flow in todo:
        current = None
        for pno, y, items, b in flow:
            page = doc[pno]
            current = b or current
            if items:
                x0 = min(i[0] for i in items)
                x1 = max(i[0] + i[2][0].text_length(i[1], fontsize=i[3]) * max(1.0, i[5]) for i in items)
                size = items[0][3]
                drawn.setdefault(current["id"], []).append((pno, fitz.Rect(x0 - 0.5, y - 0.75 * size, x1 + 0.5, y + 0.25 * size)))
            if b and b["mark"]:
                m, l0 = b["mark"], b["lines"][0]
                dy = y - l0["spans"][0]["origin"][1]
                if m["kind"] in ("inline", "text"):
                    # the sign in the PDF's own font, else the Symbol font's bullet (a text font's would be a tiny dot)
                    s = m["span"]
                    f = fonts.own(l0["page"], s["font"], s["text"]) or (fitz.Font("symb"), None, "symb")
                    put(page, pno, s["origin"][0], s["origin"][1] + dy, s["text"].strip(), f, s["size"], s["color"])
                elif m["kind"] == "circle":
                    r = fitz.Rect(m["rect"]) + (0, dy, 0, dy)
                    page.draw_circle((r.x0 + r.width / 2, r.y0 + r.height / 2), r.width / 2, color=None, fill=m["fill"])
                else:
                    page.draw_rect(fitz.Rect(m["rect"]) + (0, dy, 0, dy), color=None, fill=m["fill"])
            for x, t, f, size, color, sx in items:
                put(page, pno, x, y, t, f, size, color, sx)
    doc.subset_fonts()
    _fix_tounicode(doc, {name for _, name in inserted})
    return doc, todo, kept, drawn


def _wrong(doc, todo, kept, drawn, plan, links_before):
    """Bullets that don't read back, from where they were drawn, as exactly their text (and "links" if one was lost).
    Clip rects make this independent of reading order, so two-column resumes check right too."""
    bad = []
    for bullets, _ in todo:
        for b in bullets:
            if b["id"] not in drawn:
                continue
            new = plan.get("text", {}).get(b["id"]) if b["id"] not in kept and not b["fixed"] else None
            got = "".join(doc[p].get_text("text", clip=r) for p, r in drawn[b["id"]])
            if key(got) != key(_plain((new or b["text"]).replace("**", ""))):
                bad.append(b["id"])
    if sum(len(p.get_links()) for p in doc) != links_before:
        bad.append("links")
    return bad


def build(doc, plan, folder, base):
    """Write the tailored PDF into folder. -> {"pdf", "pages", "paper", "kept": [bullet ids whose rewording didn't
    fit and kept their text]}. Raises ValueError when the result doesn't read back, even without the PDF's own fonts."""
    fitz = _fitz()
    with fitz.open(doc["_path"]) as d:
        links_before = sum(len(p.get_links()) for p in d)
    bad = []
    for allow in (True, False):
        out, todo, kept, drawn = _render(doc["_path"], doc["_pieces"], plan, allow)
        bad = _wrong(out, todo, kept, drawn, plan, links_before)
        if not bad:
            folder = Path(folder)
            folder.mkdir(parents=True, exist_ok=True)
            pdf = folder / f"{base}.pdf"
            out.save(pdf, garbage=3, deflate=True)
            width, pages = out[0].rect.width, out.page_count
            out.close()
            return {"pdf": str(pdf), "pages": pages, "paper": "A4" if abs(width - 595) < 6 else "Letter", "kept": kept}
        out.close()
    raise ValueError(f"the tailored PDF didn't read back as written ({', '.join(bad[:4])})")
