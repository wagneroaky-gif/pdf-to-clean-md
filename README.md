[README.md](https://github.com/user-attachments/files/29211003/README.md)
# pdf-to-clean-md

**A PDF-to-Markdown converter that doesn't hand you half a problem.**

PDF→Markdown tools love to promise "perfect extraction" and then hand you a `.md` file with watermark text repeated in every paragraph, accented characters turned into random symbols, tables with shuffled columns, and entire paragraphs out of order. You trade the work of reading the PDF for the work of fixing the Markdown — and if you use AI to do that cleanup, you pay tokens for it too.

This script was built against exactly that scenario, using real PDFs that broke those tools: corrupted fonts, watermarks on every page, multi-column infoboxes, dot-leader tables of contents. Every fix in here exists because a real case exposed a failure — and was tested against that case until it worked, not "should work in theory."

## Before / After (real cases, not made up)

**Watermark surviving on every page:**
```
BEFORE:
the eggs are nQt subjected to heat treatmRnt in their natural
form, this bacteria can develop normally.

O 152364978 MQB

This is not the only important disease in microbiology,
there are several others we will get to know a little better.

O 152364978 MQB

AFTER:
This is not the only important disease in microbiology,
there are several others we will get to know a little better.
```
Watermark removed and encoding corrected in the same pass — no need to manually map character by character.

**Table with residue glued to the values (real extraction artifact):**
```
BEFORE:
|Bacteria |0.90 to 0.91 282|
|Yeasts |0.85 to 0.87 O 1|
|Molds |0.80 LH|

AFTER:
|Bacteria |0.90 to 0.91|
|Yeasts |0.85 to 0.87|
|Molds |0.80|
```

**Entire table of contents collapsing into one unreadable line:**
```
BEFORE:
Chapter 1. Preface.......................... 3 Chapter 2. Product
Introduction.......... 5 Overview.......... 5 Packing List..........5
Hardware Introduction..........6 Chapter 3. Power Supply..........8

AFTER:
Chapter 1. Preface.......................... 3
Chapter 2. Product Introduction.......... 5
Overview.......... 5
Packing List..........5
Hardware Introduction..........6
Chapter 3. Power Supply..........8
```

## Why this matters to you

- **You won't notice the watermark — because it won't be there.** Detection by identical line, by shared prefix, and by structural format (covers even cases where the page number changes but the rest of the footer repeats). In one real case, **23% of the raw PDF was repeated noise** — removed in under a second, with zero AI involved.
- **Broken fonts stop being your problem.** When a PDF has a corrupted character map (accents turning into symbols), most tools just hand you the garbage and move on. This script detects it and falls back to real OCR on the rendered page, reading what's actually there visually — instead of guessing which broken symbol used to be which letter.
- **Reading order preserved — not whatever order the PDF stored it in internally.** Layout-aware extraction: in a direct test, it correctly fixed 10 of 11 sections that came out scrambled with naive extraction.
- **Infobox content doesn't vanish.** Multi-column, multi-box, messy layouts — the script runs a second full-page OCR pass and **automatically merges** recovered content only when there's a real, measurable gain (an objective comparison, not a guess), and flags it for review whenever column order can't be guaranteed. Honest about what it doesn't know, instead of making something up.
- **Three languages, one flag.** `--language pt|en|es`, tested end-to-end on all three — not "should work," but "ran and was checked."
- **Zero AI tokens in the cleanup.** Every fix is regex and heuristics tested against real data, not an API call. You pay in local processing time, not credits.

## What this is NOT

Not magic. PDFs with very messy layouts can still leave a detail or two for manual review — and the script tells you where, instead of handing you a silent failure dressed up as success. Attempts to over-generalize some fixes already caused regressions during testing (one of them ended up deleting legitimate technical data from hex tables) — they were reverted before making it in here. That's the standard this project holds itself to: test against real data before declaring victory. See [Known limitations](#known-limitations).

## Installation

```bash
pip install pymupdf4llm pymupdf pytesseract pillow
```

You also need **Tesseract OCR** installed on your system (it's not just a Python package):
- **Windows:** [official installer](https://github.com/UB-Mannheim/tesseract/wiki) — check the language packs you'll need during setup.
- **Linux (Debian/Ubuntu):** `apt-get install tesseract-ocr tesseract-ocr-por tesseract-ocr-eng tesseract-ocr-spa`

## Usage

```bash
python3 pdf_to_clean_md.py input.pdf output.md
python3 pdf_to_clean_md.py input.pdf output.md --idioma en
python3 pdf_to_clean_md.py input.pdf output.md --idioma es
python3 pdf_to_clean_md.py input.pdf output.md --manter-backup   # also saves the raw full-page OCR backup
```

## How it works

1. **Extraction** — `pymupdf4llm`, layout-aware; automatically falls back to OCR if the text layer is corrupted.
2. **Deterministic cleanup** — repeated watermark/headers, table cell residue, misclassified headings, glued table of contents.
3. **Full-page OCR** — a safety net that runs without cropping the page (avoids losing boxes during automatic cropping).
4. **Automatic merging** — only inserts recovered content when there's a real, measurable gain, always flagged for review.

## Known limitations

- 3+ consecutive headings with no body text between them (e.g., a misinterpreted credits table) aren't auto-corrected — the risk of fixing the wrong item outweighs the benefit.
- Content recovered via full-page OCR can come out with columns out of their original visual order (OCR reads line by line, across columns) — that's why it's always flagged, never silently inserted.
- Tested and calibrated for Portuguese, English, and Spanish. Other languages may work (the architecture is generic), but haven't been validated.
- PDFs that require OCR take longer to process (1–3 minutes for 15–30 pages) — that's the cost of not relying on AI to work around corrupted fonts.
- Table cleanup fixes are deliberately conservative: they cover the confirmed case (noise glued to the end of a cell that already has real content), and deliberately do NOT try to treat "a whole cell that's just short text" as noise — that would break legitimate technical tables (hex values, codes, IDs).

## License

MIT

## Contributing

Issues and PRs with real cases that break the script are more welcome than theoretical suggestions — that's how every fix in here was born.
