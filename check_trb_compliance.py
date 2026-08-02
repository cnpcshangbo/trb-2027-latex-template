#!/usr/bin/env python3
"""Check a built PDF against the TRB Annual Meeting format rules.

Every check runs against the RENDERED PDF, never against the LaTeX source.
That is deliberate: the failures that actually get papers bounced are ones the
source looks innocent for. Two we hit ourselves --

  * ``\\numrange{0.34}{0.43}`` renders "0.34 to 0.43", not an en dash, because
    siunitx v3 defaults ``range-phrase`` to a literal " to ".
  * ``\\num{40,793}`` renders "40.793" when the comma is read as a decimal
    marker -- wrong by 1000x, and plausible enough to survive proofreading.

Neither is visible in the .tex. Check the artifact you are actually submitting.

Usage:
    python3 check_trb_compliance.py main.pdf
    python3 check_trb_compliance.py main.pdf --max-pages 20

Requires poppler-utils (pdfinfo, pdftotext), which ships with every TeX
distribution and most Linux/macOS setups. If PyMuPDF is importable it is used
for exact font measurement; it is optional but recommended.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import collections
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

# TRB rules this script knows how to check. Sources:
#   "2027 TRB Annual Meeting Paper Submission Checklist" (the authoritative PDF,
#   distributed via the TRB author resource page) and
#   https://trb.secure-platform.com/a/page/TRBPaperReview
# TRB changes these between cycles. Verify against the current checklist before
# trusting anything here -- this script encodes our reading, not TRB's authority.
MAX_PAGES = 20
MAX_ABSTRACT_WORDS = 300
MIN_FONT_PT = 10.0
ABSTRACT_HEADINGS = ["Objectives", "Methods", "Findings", "Novelty",
                     "Practical Applications"]
LETTER_PT = (612.0, 792.0)  # 8.5 x 11 in
MARGIN_PT = 72.0            # 1 in

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = RED = YELLOW = DIM = RESET = ""

results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str) -> None:
    results.append((status, name, detail))
    mark = {"PASS": f"{GREEN}PASS{RESET}", "FAIL": f"{RED}FAIL{RESET}",
            "WARN": f"{YELLOW}WARN{RESET}", "INFO": f"{DIM}info{RESET}"}[status]
    print(f"  [{mark}] {name}")
    for line in detail.splitlines():
        if line.strip():
            print(f"         {DIM}{line}{RESET}")


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout


# ----------------------------------------------------------------------
# Geometry: page size, count, margins
# ----------------------------------------------------------------------
def check_pages(pdf: str, max_pages: int) -> int:
    info = run(["pdfinfo", pdf])
    pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
    size = re.search(r"Page size:\s+([\d.]+) x ([\d.]+)", info)
    w, h = float(size.group(1)), float(size.group(2))

    record("PASS" if pages <= max_pages else "FAIL",
           f"Page count -- {pages} of {max_pages} allowed",
           "Counts title page, abstract, text, references, figures and tables."
           if pages <= max_pages else
           f"Over by {pages - max_pages} page(s). Everything counts: title page, "
           f"abstract, text, acknowledgments, references, figures, tables.")

    ok = abs(w - LETTER_PT[0]) < 2 and abs(h - LETTER_PT[1]) < 2
    record("PASS" if ok else "FAIL", "Page size -- US Letter",
           f"{w:.0f} x {h:.0f} pt (expected {LETTER_PT[0]:.0f} x {LETTER_PT[1]:.0f}, 8.5 x 11 in)")
    return pages


def words_with_boxes(pdf: str, first: int | None = None, last: int | None = None):
    """Yield (page_number, text, x0, y0, x1, y1) for every word."""
    cmd = ["pdftotext", "-bbox"]
    if first:
        cmd += ["-f", str(first)]
    if last:
        cmd += ["-l", str(last)]
    xml = run(cmd + [pdf, "-"])
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return
    ns = {"x": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    page_tag = f"{{{ns['x']}}}page" if ns else "page"
    word_tag = f"{{{ns['x']}}}word" if ns else "word"
    for n, page in enumerate(root.iter(page_tag), start=first or 1):
        for w in page.iter(word_tag):
            yield (n, (w.text or ""), float(w.get("xMin")), float(w.get("yMin")),
                   float(w.get("xMax")), float(w.get("yMax")))


def check_page_numbers(pdf: str, pages: int) -> None:
    """TRB asks for page numbers centred at the bottom of each page.

    trbunofficial.cls v5.0 puts them top-right instead, so this check is the
    reason trb2027.sty exists. We look for a word that is just the page number,
    sitting in the bottom sixth of the page, horizontally centred.
    """
    centre_x = LETTER_PT[0] / 2
    bad, checked = [], 0
    for n in range(2, min(pages, 8) + 1):  # page 1 is the title page
        found = None
        for _, text, x0, y0, x1, _y1 in words_with_boxes(pdf, n, n):
            if text.strip() == str(n) and y0 > LETTER_PT[1] * 0.83:
                found = ((x0 + x1) / 2, y0)
                break
        checked += 1
        if found is None:
            bad.append(f"page {n}: no page number in the bottom band")
        elif abs(found[0] - centre_x) > 12:
            bad.append(f"page {n}: at x={found[0]:.1f}, off-centre by "
                       f"{found[0] - centre_x:+.1f} pt (centre is {centre_x:.0f})")
    if not checked:
        record("WARN", "Page numbers", "document too short to check")
    elif bad:
        record("FAIL", "Page numbers centred at the bottom",
               "\n".join(bad) + "\n\nStock trbunofficial.cls puts the number top-right. "
               "Load trb2027.sty, or apply its \\renewpagestyle{main} override.")
    else:
        record("PASS", f"Page numbers centred at the bottom ({checked} pages sampled)",
               f"within 12 pt of the {centre_x:.0f} pt centre line")


def check_margins(pdf: str, pages: int) -> None:
    """Line numbers legitimately sit outside the text block, so measure the
    text body only -- otherwise every numbered page looks like a margin bust."""
    worst_left, worst_right, worst_top, worst_bot = 999.0, 999.0, 999.0, 999.0
    for n in range(2, min(pages, 6) + 1):
        xs = [(x0, x1) for _, t, x0, _, x1, _ in words_with_boxes(pdf, n, n)
              if not re.fullmatch(r"\d{1,3}", t.strip())]
        ys = [(y0, y1) for _, t, _, y0, _, y1 in words_with_boxes(pdf, n, n)
              if not re.fullmatch(r"\d{1,3}", t.strip())]
        if not xs:
            continue
        worst_left = min(worst_left, min(a for a, _ in xs))
        worst_right = min(worst_right, LETTER_PT[0] - max(b for _, b in xs))
        worst_top = min(worst_top, min(a for a, _ in ys))
        worst_bot = min(worst_bot, LETTER_PT[1] - max(b for _, b in ys))
    tol = 6.0
    ok = all(m >= MARGIN_PT - tol for m in (worst_left, worst_right, worst_top, worst_bot))
    record("PASS" if ok else "WARN", "Margins -- 1 inch (72 pt)",
           f"tightest: left {worst_left:.0f}, right {worst_right:.0f}, "
           f"top {worst_top:.0f}, bottom {worst_bot:.0f} pt "
           f"(numerals excluded -- line numbers sit outside the text block by design)")


def check_line_numbers(pdf: str, pages: int) -> None:
    hits = 0
    for n in range(2, min(pages, 6) + 1):
        left = [t for _, t, x0, _, _, _ in words_with_boxes(pdf, n, n)
                if x0 < MARGIN_PT and re.fullmatch(r"\d{1,2}", t.strip())]
        if len(left) >= 5:
            hits += 1
    sampled = min(pages, 6) - 1
    record("PASS" if hits == sampled else "WARN",
           f"Line numbers present ({hits}/{sampled} pages sampled)",
           "TRB restarts numbering on each page; the `numbered` class option does this."
           if hits == sampled else
           "Fewer than 5 numerals found in the left margin on some pages.")


# ----------------------------------------------------------------------
# Abstract
# ----------------------------------------------------------------------
def check_abstract(pdf: str) -> None:
    text = run(["pdftotext", "-f", "1", "-l", "3", pdf, "-"])
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.M)  # strip line numbers
    m = re.search(r"ABSTRACT|Abstract", text)
    if not m:
        record("WARN", "Structured abstract", "no ABSTRACT heading found in the first 3 pages")
        return
    tail = text[m.end():]
    end = re.search(r"Keywords|KEYWORDS|INTRODUCTION|Introduction", tail)
    body = tail[:end.start()] if end else tail[:3000]

    n = len(body.split())
    record("PASS" if n <= MAX_ABSTRACT_WORDS else "FAIL",
           f"Abstract length -- {n} of {MAX_ABSTRACT_WORDS} words",
           "" if n <= MAX_ABSTRACT_WORDS else f"Over by {n - MAX_ABSTRACT_WORDS} words.")

    missing = [h for h in ABSTRACT_HEADINGS if h.lower() not in body.lower()]
    record("PASS" if not missing else "FAIL",
           "Structured abstract headings",
           "all five present: " + ", ".join(ABSTRACT_HEADINGS) if not missing
           else "missing: " + ", ".join(missing))


# ----------------------------------------------------------------------
# Fonts
# ----------------------------------------------------------------------
def check_fonts_exact(pdf: str) -> bool:
    """Exact per-span measurement via PyMuPDF, if it happens to be installed."""
    try:
        import fitz  # type: ignore
    except ImportError:
        return False
    sizes: collections.Counter = collections.Counter()
    examples: dict[float, str] = {}
    doc = fitz.open(pdf)
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    if not span["text"].strip():
                        continue
                    pt = round(span["size"], 1)
                    sizes[pt] += len(span["text"])
                    examples.setdefault(pt, span["text"].strip()[:40])
    report_font_sizes(sizes, examples, exact=True)
    return True


def check_fonts_declared(pdf: str) -> None:
    """No PyMuPDF: read the font sizes the PDF itself declares.

    Every ``Tf`` operator in a content stream names a font and a size in points.
    That is the size the text is set at, so no estimation is involved -- unlike
    word bounding boxes, whose height depends on which glyphs the word happens
    to contain (a rotated axis label measures as tall as the label is long).

    One caveat, stated plainly: text inside an embedded figure lives in the
    figure's own stream, so its declared size is what the figure was AUTHORED
    at. That equals what the reader sees only when the figure is included at
    1:1 -- which is exactly why this template tells you to author figures at
    their display size. Install PyMuPDF (``pip install pymupdf``) if you want
    post-scaling sizes measured exactly.
    """
    import zlib

    raw = Path(pdf).read_bytes()
    sizes: collections.Counter = collections.Counter()
    for m in re.finditer(rb"stream\r?\n", raw):
        s0 = m.end()
        e0 = raw.find(b"endstream", s0)
        if e0 < 0:
            continue
        try:
            data = zlib.decompress(raw[s0:e0])
        except zlib.error:
            continue
        for t in re.finditer(rb"/[A-Za-z0-9+.\-]+\s+([\d.]+)\s+Tf", data):
            try:
                pt = round(float(t.group(1)), 1)
            except ValueError:
                continue
            if 0 < pt < 100:           # ignore degenerate/placeholder sizes
                sizes[pt] += 1
    if not sizes:
        record("WARN", "Font sizes",
               "no readable content streams (object streams or encryption?) -- "
               "install PyMuPDF for a reliable check")
        return
    report_font_sizes(sizes, {}, exact=False)


def report_font_sizes(sizes, examples, exact: bool) -> None:
    method = ("exact, as rendered (PyMuPDF)" if exact else
              "declared Tf sizes from the content streams (no PyMuPDF installed)")
    unit = "chars" if exact else "ops"
    lines = [f"method: {method}", "distribution:"]
    for pt, count in sorted(sizes.items(), reverse=True):
        flag = "  <-- below 10 pt" if pt < MIN_FONT_PT - 0.3 else ""
        ex = f" e.g. {examples[pt]!r}" if pt in examples else ""
        lines.append(f"   {pt:5.1f} pt  x{count:<6d} {unit}{ex}{flag}")

    small = {pt: c for pt, c in sizes.items() if pt < MIN_FONT_PT - 0.3}
    total_small, total = sum(small.values()), sum(sizes.values())
    if not small:
        record("PASS", "Font sizes -- all text at 10 pt or larger", "\n".join(lines))
        return

    # Math sub/superscripts scale with the base size and cannot be raised in any
    # LaTeX document, so they are called out rather than failed outright.
    share = total_small / total
    lines += [
        "",
        f"{total_small} of {total} ({share:.1%}) fall below 10 pt.",
        "If these are math sub/superscripts they are unavoidable -- they track the",
        "base size and every LaTeX paper has them. If they are captions, table",
        "cells or figure labels, fix them: drop \\small/\\footnotesize (trb2027.sty",
        "neutralises both), and regenerate figures at their DISPLAY size rather",
        "than shrinking them with \\includegraphics[width=...].",
    ]
    record("WARN" if share < 0.12 else "FAIL", "Font sizes -- 10 pt floor", "\n".join(lines))


def check_figure_scaling(pdf: str) -> None:
    """Figures scaled down on inclusion shrink their labels below the floor.

    A figure authored at 10 pt and included at width=0.6\\linewidth renders its
    labels at 6 pt. The fix is to regenerate at display size, not to bump the
    font inside the figure. We cannot see \\includegraphics from the PDF, so
    this is a pointer rather than a test.
    """
    record("INFO", "Figure text",
           "Check that each figure is included at ~1:1. If natural width (pdfinfo\n"
           "on the figure PDF) is much smaller than the width it is displayed at,\n"
           "its labels are being scaled -- regenerate at display size instead.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES)
    a = ap.parse_args()

    for tool in ("pdfinfo", "pdftotext"):
        if not shutil.which(tool):
            print(f"{RED}error{RESET}: {tool} not found -- install poppler-utils")
            return 2

    print(f"\nTRB Annual Meeting format check -- {a.pdf}\n")
    pages = check_pages(a.pdf, a.max_pages)
    check_page_numbers(a.pdf, pages)
    check_margins(a.pdf, pages)
    check_line_numbers(a.pdf, pages)
    check_abstract(a.pdf)
    if not check_fonts_exact(a.pdf):
        check_fonts_declared(a.pdf)
    check_figure_scaling(a.pdf)

    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    print(f"\n{len(results)} checks: "
          f"{GREEN}{sum(1 for r in results if r[0] == 'PASS')} pass{RESET}, "
          f"{YELLOW}{len(warns)} warn{RESET}, {RED}{len(fails)} fail{RESET}")
    print(f"\n{DIM}These checks encode our reading of the TRB rules, not TRB's authority.\n"
          f"Verify against the current cycle's official submission checklist.{RESET}\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
