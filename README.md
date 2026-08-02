# TRB Annual Meeting LaTeX template — 2027 cycle

A working LaTeX setup for TRB Annual Meeting papers, plus a script that checks
the **built PDF** against the format rules before you submit.

This is a thin layer over [`chiehrosswang/TRB_LaTeX_tex`][upstream], which is
the template most people use and which this repository does not replace. What
is added here came out of preparing one real 2027-cycle submission and hitting
things the stock setup does not cover.

```bash
git clone https://github.com/cnpcshangbo/trb-2027-latex-template
cd trb-2027-latex-template
latexmk -pdf main.tex
python3 check_trb_compliance.py main.pdf
```

[![Open in Overleaf](https://img.shields.io/badge/Open%20in-Overleaf-46A247?logo=overleaf&logoColor=white)](https://www.overleaf.com/docs?snip_uri=https://github.com/cnpcshangbo/trb-2027-latex-template/archive/refs/heads/main.zip)

---

## What this adds over the upstream template

Upstream v5.0 already handles the 2027 structured abstract, the title page, the
author/ORCID block, and page counting. **Use it directly if that is all you
need.** The four things below are what it does not do.

### 1. Page numbers centred at the bottom

The one that would actually have cost us. The 2027 submission checklist asks for
page numbers *centered at the bottom of each page*. `trbunofficial.cls` v5.0
defines:

```latex
\newpagestyle{main}{\sethead{\@AuthorHeaders}{}{\thepage}}
```

— which puts the number **top-right**, in the running header. Upstream's own
template documents this as intended. `trb2027.sty` moves it to the footer and
keeps the author running head on the left. Our co-author caught this by reading
the checklist against a built PDF; nothing in the build warns you.

### 2. 10 pt as a class option

Upstream hardcodes `12pt`. TRB allows *"Times New Roman, 10-point font or
larger"*, and on our 20-page paper dropping to 10 pt returned **three pages**,
which went into larger figures. Both sizes are compliant — this is a trade, not
a fix:

| | 12 pt | 10 pt |
|---|---|---|
| Pages (our paper) | 20, exactly at the limit | 17 |
| Typographic hierarchy | body 12 pt, captions 10 pt | everything at the 10 pt floor |

```latex
\documentclass[10pt,numbered]{trbunofficial}   % or [12pt,numbered]
```

Line numbers also move from `\small` to `\normalsize`, because at a 10 pt base
`\small` renders 9 pt — under the floor.

### 3. Guards for two silent number-corrupting bugs

Both of these look correct in the `.tex` and are only visible in the PDF:

- **`\numrange{0.34}{0.43}` renders "0.34 to 0.43", not an en dash.** siunitx v3
  defaults `range-phrase` to the literal word " to ". We shipped a draft with
  twelve of these before a reviewer caught it.
- **`\num{40,793}` can render "40.793"** — the comma read as a decimal marker.
  Off by a factor of 1000, and plausible enough to survive proofreading.

`trb2027.sty` sets `range-phrase`, `group-separator`, and
`group-minimum-digits`. Write `\num{40793}` and let the package place the comma.

### 4. A compliance checker that reads the PDF

`check_trb_compliance.py` checks the artifact you actually submit, not the
source. It verifies page count, page size, margins, **page-number placement**,
line numbers, structured-abstract word count and headings, and the 10 pt font
floor.

Removing `trb2027.sty` and rebuilding makes it say:

```
  [FAIL] Page numbers centred at the bottom
         page 2: no page number in the bottom band
         page 3: no page number in the bottom band
         Stock trbunofficial.cls puts the number top-right. Load trb2027.sty,
         or apply its \renewpagestyle{main} override.
```

Only `pdfinfo` and `pdftotext` are needed (poppler-utils, which ships with TeX
Live and MacTeX). `pip install pymupdf` is optional and upgrades font
measurement from declared sizes to exactly-as-rendered.

---

## The figure trap

Not a code fix — a habit, and the most common reason TRB papers have unreadable
figures.

**Author each figure at the width it will be displayed at.** A figure authored
6.5 in wide and included at `width=\linewidth` keeps its 10 pt labels at 10 pt.
The same figure included at `width=0.6\linewidth` renders them at **6 pt**.

Shrinking with `\includegraphics[width=...]` scales the text down with
everything else. The fix is to regenerate the figure smaller, not to include it
smaller:

```python
fig, ax = plt.subplots(figsize=(6.5, 2.6))   # 6.5 in == \linewidth at 1 in margins
plt.rcParams.update({"font.size": 10.0})
```

Then check: `pdfinfo figures/yours.pdf` should report a width close to the
468 pt (6.5 in) it is displayed at. We had figures rendering at 2.5–5.6 pt this
way, and they looked fine in the source.

---

## Dependencies

A standard TeX Live install covers it. On a minimal Debian/Ubuntu box:

```bash
sudo apt-get install -y texlive-latex-recommended texlive-latex-extra \
  texlive-fonts-recommended texlive-fonts-extra texlive-science \
  texlive-plain-generic latexmk poppler-utils
```

`texlive-plain-generic` is easy to miss and the failure is opaque: the class
loads `newtxmath` for Times-like math, which inputs `binhex.tex` from that
package, and without it the build dies with ``File `binhex.tex' not found``.

`poppler-utils` supplies `pdfinfo` and `pdftotext` for the checker.
Optionally `pip install pymupdf` for exact font measurement.

---

## Files

| File | What it is |
|---|---|
| `main.tex` | Skeleton paper — structured abstract, figure, table, end matter |
| `trb2027.sty` | The compliance layer described above |
| `trbunofficial.cls` | Upstream v5.0 **plus two marked changes** (font-size option, line-number font) |
| `upstream/trbunofficial-v5.0-upstream.cls` | Pristine upstream copy, for diffing |
| `trb.bst` | Upstream, unmodified — Chicago author–date |
| `check_trb_compliance.py` | PDF format checker |
| `references.bib` | Three example entries |
| `figures/example_figure.pdf` | Demonstrates the display-size rule |

To re-sync with upstream:

```bash
diff -u upstream/trbunofficial-v5.0-upstream.cls trbunofficial.cls
```

Both local changes are commented `LOCAL CHANGE` in the file.

---

## Accuracy and scope

**The rules encoded here are our reading, not TRB's authority.** They come from
the *2027 TRB Annual Meeting Paper Submission Checklist* and TRB's
[Instructions for Authors][trb]. TRB changes requirements between cycles, and
the constants at the top of `check_trb_compliance.py` (20 pages, 300 words,
10 pt, the five abstract headings) are the ones to update when they do.

**Check the official checklist yourself before submitting.** A passing run of
this script means it found nothing wrong among the things it knows how to look
at — not that your paper is compliant. Neither this template nor upstream is
endorsed by TRB.

Corrections are welcome, particularly from anyone with the current cycle's
checklist in hand. Open an issue.

---

## Credits and licence

The class and bibliography style are by **David R. Pritchard**, **Gregory S.
Macfarlane**, and **C. Ross Wang**, from [`chiehrosswang/TRB_LaTeX_tex`][upstream]
(MIT). That is the substance of this template; the layer on top is small by
comparison. Their MIT notice is preserved in
[`NOTICE-upstream-MIT.txt`](NOTICE-upstream-MIT.txt).

The additions in this repository are MIT licensed — see [`LICENSE`](LICENSE).

Assembled while preparing a 2027 TRB Annual Meeting submission by Bo Shang and
Yiqiao Li, Department of Civil Engineering, The City College of New York, CUNY.

[upstream]: https://github.com/chiehrosswang/TRB_LaTeX_tex
[trb]: https://trb.secure-platform.com/a/page/TRBPaperReview
