#!/usr/bin/env python3
"""Self-tests for the template itself. Run locally or in CI:

    python3 selftest.py

Two things are guarded here, both because they broke once and neither
announced itself:

1. Class options must have a visible effect, and must not leave LaTeX
   complaining. We shipped a version that declared the base-size options with
   an early ``\\ProcessOptions`` placed before ``\\LoadClass``. The size was
   applied correctly and ``numbered`` kept working -- the class's own later
   ``\\ProcessOptions`` still sees ``\\@classoptionslist`` -- but ``\\LoadClass``
   resets the used-option bookkeeping, so at ``\\begin{document}`` LaTeX
   reported ``Unused global option(s): [10pt]`` on every build. Cosmetic, but
   it is the kind of warning that trains people to ignore warnings, and
   Overleaf surfaces it on the submission dialog.

2. The compliance checker must FAIL a non-compliant build. A checker that has
   silently stopped checking is worse than no checker, because it reads as a
   green light. So we strip trb2027.sty, rebuild, and assert a non-zero exit.

Every assertion is made against the built PDF, never the source.
"""
from __future__ import annotations

import collections
import re
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent
failures: list[str] = []


def build(cwd: Path) -> Path:
    subprocess.run(["latexmk", "-C"], cwd=cwd, capture_output=True)
    r = subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "main.tex"],
                       cwd=cwd, capture_output=True, text=True)
    pdf = cwd / "main.pdf"
    if not pdf.exists():
        raise RuntimeError(f"build produced no PDF\n{r.stdout[-2000:]}")
    return pdf


def dominant_font_pt(pdf: Path) -> float:
    """Most common declared Tf size across the content streams."""
    raw = pdf.read_bytes()
    counts: collections.Counter = collections.Counter()
    for m in re.finditer(rb"stream\r?\n", raw):
        s, e = m.end(), raw.find(b"endstream", m.end())
        try:
            data = zlib.decompress(raw[s:e])
        except zlib.error:
            continue
        for t in re.finditer(rb"/[A-Za-z0-9+.\-]+\s+([\d.]+)\s+Tf", data):
            counts[round(float(t.group(1)), 1)] += 1
    if not counts:
        raise RuntimeError("no readable content streams")
    return counts.most_common(1)[0][0]


def left_margin_numerals(pdf: Path, page: int = 2) -> int:
    """Count numerals sitting left of the 1-inch text block, i.e. line numbers."""
    xml = subprocess.run(["pdftotext", "-bbox", "-f", str(page), "-l", str(page),
                          str(pdf), "-"], capture_output=True, text=True).stdout
    n = 0
    for m in re.finditer(r'xMin="([\d.]+)"[^>]*>([^<]*)</word>', xml):
        if float(m.group(1)) < 72.0 and re.fullmatch(r"\d{1,2}", m.group(2).strip()):
            n += 1
    return n


def set_class_options(tex: Path, options: str) -> None:
    s = tex.read_text()
    # Count the substitutions rather than comparing strings: rewriting the line
    # to the value it already holds is a no-op, not a failure.
    s2, n = re.subn(r"^\\documentclass\[[^\]]*\]\{trbunofficial\}",
                    rf"\\documentclass[{options}]{{trbunofficial}}", s,
                    count=1, flags=re.M)
    assert n == 1, "could not find the \\documentclass line to rewrite"
    tex.write_text(s2)


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  -- {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def test_class_options(work: Path) -> None:
    print("\nClass options have a visible effect")
    cases = [("10pt,numbered", 10.0, True),
             ("12pt,numbered", 12.0, True),
             ("10pt", 10.0, False)]
    for options, expect_pt, expect_lines in cases:
        set_class_options(work / "main.tex", options)
        pdf = build(work)
        log = (work / "main.log").read_text(errors="replace")

        check(f"[{options}] no unused global option",
              "Unused global option" not in log)

        got_pt = dominant_font_pt(pdf)
        check(f"[{options}] base font is {expect_pt} pt",
              got_pt == expect_pt, f"dominant = {got_pt} pt")

        n = left_margin_numerals(pdf)
        if expect_lines:
            check(f"[{options}] line numbers present", n >= 5, f"{n} numerals")
        else:
            check(f"[{options}] line numbers absent without `numbered`",
                  n == 0, f"{n} numerals")


def test_checker_rejects_noncompliant(work: Path) -> None:
    """Strip the compliance layer; the checker must fail the result."""
    print("\nChecker still catches a build without trb2027.sty")
    tex = work / "main.tex"
    set_class_options(tex, "10pt,numbered")
    s = tex.read_text()
    s = re.sub(r"^\\usepackage\{trb2027\}.*$", r"\\usepackage{siunitx}", s,
               count=1, flags=re.M)
    s = s.replace("\\trbabstractsection", "\\textbf")
    s = s.replace("\\trbdataavailability{", "\\section*{Data Availability}{")
    s = s.replace("\\trbaidisclosure{", "\\section*{AI Disclosure}{")
    tex.write_text(s)
    build(work)

    r = subprocess.run([sys.executable, str(work / "check_trb_compliance.py"),
                        str(work / "main.pdf")], capture_output=True, text=True)
    check("checker exits non-zero on top-right page numbers", r.returncode != 0,
          f"exit {r.returncode}")
    check("checker names the page-number problem",
          "Page numbers centred at the bottom" in r.stdout and "FAIL" in r.stdout)


def main() -> int:
    for tool in ("latexmk", "pdftotext", "pdfinfo"):
        if not shutil.which(tool):
            print(f"error: {tool} not found")
            return 2

    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "t"
        shutil.copytree(REPO, work, ignore=shutil.ignore_patterns(".git", "*.pdf.bak"))
        test_class_options(work)
        test_checker_rejects_noncompliant(work)

    print(f"\n{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
