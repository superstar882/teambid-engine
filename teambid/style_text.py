"""Text matching shared by the keep-original-style file handlers (style_tex.py now; .docx and PDF later).

key() is the form of a text that survives the trip through a PDF: line breaks, words split with a hyphen at a line
end, dash and quote styles, ligatures (ﬁ), an underscore pdfTeX draws as a line (it reads back as a space) and
**bold** marks are all ignored. Two texts with the same key are the same words.
"""
import re
import unicodedata

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})
_IGNORED = re.compile(r"[\s\-‐‑‒–—|•·_]+")


def key(text):
    s = unicodedata.normalize("NFKC", str(text or "")).translate(_QUOTES).replace("**", "")
    return _IGNORED.sub("", s).casefold()
