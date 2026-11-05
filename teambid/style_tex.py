"""Tailor a member's own LaTeX resume in place: find the pieces, put the new text back, build the PDF.

Only the text of the pieces changes (bullets, summary, headline, the order of skills). The preamble, header, links,
icons and every other byte of the file stay as they were.
Design: docs/superpowers/specs/2026-11-05-keep-original-style-design.md
"""
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .style_text import key

# control symbols that print one character (\% -> %); others (\\ line break, ...) make a piece move-only
ESCAPES = {"%": "%", "&": "&", "#": "#", "_": "_", "$": "$", "{": "{", "}": "}", " ": " ", ",": " ", ";": " ", "/": ""}
SKIP_ARG = {"vspace", "hspace", "label", "color", "phantom"}          # their argument isn't text
TEX_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
           "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "<": r"\textless{}", ">": r"\textgreater{}",
           "|": r"\textbar{}", "–": "--", "—": "---"}     # < > | print as other glyphs in the default OT1 font


def _mask(src):
    """src with comments blanked out, same length, so a position found in it is the same position in src."""
    return re.sub(r"(?<!\\)%[^\n]*", lambda m: " " * len(m.group(0)), src)


def _close(s, i):
    """s[i] is '{' -> index of the matching '}'."""
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise ValueError("unbalanced braces in the .tex file")


def to_plain(src):
    """A LaTeX snippet -> (plain text with **bold**, simple). simple is False when the snippet uses anything besides
    \\textbf and escaped characters (a link, italics, a line break): such a piece may move but is never reworded."""
    s = _mask(src)
    out, i, simple = [], 0, True
    while i < len(s):
        c = s[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+)\*?\s*|\\(.)", s[i:], re.S)
            name, after = m.group(1), i + m.end()
            if name in {"textbf", "href", "url"} | SKIP_ARG and s.startswith("{", after):
                j = _close(s, after)
                if name == "href" and s.startswith("{", j + 1):        # \href{url}{text}: only the text shows
                    after, j = j + 1, _close(s, j + 1)
                inner, ok = to_plain(s[after + 1:j]) if name not in SKIP_ARG else ("", True)
                out.append(f"**{inner}**" if name == "textbf" and inner else inner)
                simple = simple and ok and name == "textbf"
                i = j + 1
                continue
            if name:
                simple = False
            elif m.group(2) in ESCAPES:
                out.append(ESCAPES[m.group(2)])
            else:
                simple = False
            i = after
            continue
        if c in "{}":
            i += 1
            continue
        for tok, rep in (("---", "—"), ("--", "–"), ("``", '"'), ("''", '"'), ("~", " ")):
            if s.startswith(tok, i):
                out.append(rep)
                i += len(tok)
                break
        else:
            out.append(c)
            i += 1
    text = re.sub(r"\s+", " ", "".join(out)).strip()
    return re.sub(r"\*\*(\s*)\*\*", r"\1", text), simple        # **A** **B** -> **A B**


def to_tex(text):
    """Plain text with **bold** -> LaTeX. Special characters are escaped, so the result always compiles."""
    parts = str(text).split("**")
    if len(parts) % 2 == 0:              # an unpaired ** : drop the marks, keep the words
        parts = ["".join(parts)]
    out = []
    for i, part in enumerate(parts):
        esc = "".join(TEX_ESC.get(c, c) for c in part)
        out.append(f"\\textbf{{{esc}}}" if i % 2 and part else esc)
    return "".join(out)
