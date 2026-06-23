# pdf-to-clean-md

**A PDF-to-Markdown converter that doesn't hand you half a problem.**

PDF→Markdown tools love to promise "perfect extraction" and then hand you a `.md` file with watermark text repeated in every paragraph, accented characters turned into random symbols, tables with shuffled columns, and entire paragraphs out of order. You trade the work of reading the PDF for the work of fixing the Markdown — and if you use AI to do that cleanup, you pay tokens for it too.

This project was built against exactly that scenario, using real PDFs that broke those tools: corrupted fonts, watermarks on every page, multi-column infoboxes, dot-leader tables of contents. Every fix in here exists because a real case exposed a failure — and was tested against that case until it worked, not "should work in theory."

**Two ways to use it:** a GUI desktop app (Windows `.exe`, no installation required) and a Python CLI script for automation and pipelines.

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

- **You won't notice the watermark — because it won't be there.** Detection by identical line, by shared prefix, by structural format, and by repeating suffix (covers footers where the page number changes but the fixed text repeats). In one real case, **23% of the raw PDF was repeated noise** — removed in under a second, with zero AI involved.
- **Broken fonts stop being your problem.** When a PDF has a corrupted character map (accents turning into symbols), most tools just hand you the garbage and move on. This script detects it and falls back to real OCR on the rendered page, reading what's actually there visually — instead of guessing which broken symbol used to be which letter.
- **Reading order preserved — not whatever order the PDF stored it in internally.** Layout-aware extraction: in a direct test, it correctly fixed 10 of 11 sections that came out scrambled with naive extraction.
- **Infobox content doesn't vanish.** Multi-column, multi-box, messy layouts — the script runs a second full-page OCR pass and **automatically merges** recovered content only when there's a real, measurable gain (an objective comparison, not a guess), and flags it for review whenever column order can't be guaranteed.
- **Language detected automatically.** The script reads the first few pages and determines the language by stopword frequency (no external library, no API call). Works correctly across Portuguese, English, and Spanish — including in batch mode when a set of PDFs contains documents in different languages. Manual override always available.
- **Three languages, one flag.** `--idioma pt|en|es|auto` (default: auto), tested end-to-end on all three.
- **Zero AI tokens in the cleanup.** Every fix is regex and heuristics tested against real data, not an API call. You pay in local processing time, not credits.

## What this is NOT

Not magic. PDFs with very messy layouts can still leave a detail or two for manual review — and the script tells you where, instead of handing you a silent failure dressed up as success. Attempts to over-generalize some fixes already caused regressions during testing (one of them ended up deleting legitimate technical data from hex tables) — they were reverted before making it in here. That's the standard this project holds itself to: test against real data before declaring victory. See [Known limitations](#known-limitations).

## Option 1: Windows Desktop App (no Python required)

Download the latest release from the [Releases](../../releases) page, extract the zip, and run `PDF_para_Markdown.exe` with a double-click. No Python, no Tesseract, no pip — everything is bundled inside.

**Features:**
- Select one or more PDFs via button or drag-and-drop
- Language auto-detected per file — works correctly when a batch contains documents in different languages
- Manual language override via dropdown (Auto-detect / Português / English / Español)
- Optional "Keep OCR backup file" checkbox
- Background processing — the UI stays responsive during conversion
- Real-time log with per-file status
- Progress bar (1/N → 2/N → ... → 100%)
- Opens the output folder automatically when done

## Option 2: Python CLI (cross-platform)

### Installation

```bash
pip install pymupdf4llm pymupdf pytesseract pillow
```

You also need **Tesseract OCR** installed on your system (it's not just a Python package):
- **Windows:** [official installer](https://github.com/UB-Mannheim/tesseract/wiki) — check the language packs you'll need during setup.
- **Linux (Debian/Ubuntu):** `apt-get install tesseract-ocr tesseract-ocr-por tesseract-ocr-eng tesseract-ocr-spa`

### Usage

```bash
# Language auto-detected (default)
python3 pdf_to_clean_md.py input.pdf output.md

# Force a specific language
python3 pdf_to_clean_md.py input.pdf output.md --idioma en
python3 pdf_to_clean_md.py input.pdf output.md --idioma es
python3 pdf_to_clean_md.py input.pdf output.md --idioma pt

# Also save the raw full-page OCR backup
python3 pdf_to_clean_md.py input.pdf output.md --manter-backup
```

## Building the .exe yourself

If you want to build the Windows executable from source:

1. Install Python 3.10+ and Tesseract with the `por`, `eng`, and `spa` language packs
2. Install dependencies: `pip install pymupdf4llm pymupdf pytesseract pillow tkinterdnd2 pyinstaller`
3. Run `build.bat` (double-click) — the executable will be generated in `dist\PDF_para_Markdown\`

## How it works

1. **Extraction** — `pymupdf4llm`, layout-aware; automatically falls back to OCR if the text layer is corrupted.
2. **Language detection** — reads the first 4 pages via fitz (no OCR, very fast), counts stopword hits per language, picks the winner. Falls back to Portuguese if the PDF is fully scanned with no text layer.
3. **Deterministic cleanup** — repeated watermark/headers (exact, prefix, structural, and suffix patterns), table cell residue, misclassified headings, glued table of contents entries.
4. **Full-page OCR** — a safety net that runs without cropping the page (avoids losing boxes during automatic cropping).
5. **Automatic merging** — only inserts recovered content when there's a real, measurable gain, always flagged for review.

## Known limitations

- 3+ consecutive headings with no body text between them (e.g., a misinterpreted credits table) aren't auto-corrected — the risk of fixing the wrong item outweighs the benefit.
- Content recovered via full-page OCR can come out with columns out of their original visual order (OCR reads line by line, across columns) — that's why it's always flagged, never silently inserted.
- Tested and calibrated for Portuguese, English, and Spanish. Other languages may work (the architecture is generic), but haven't been validated.
- PDFs that require OCR take longer to process (1–3 minutes for 15–30 pages) — that's the cost of not relying on AI to work around corrupted fonts.
- PDFs that are fully scanned with no text layer receive Portuguese as the language fallback in auto-detection mode. Use `--idioma` to override.
- Table cleanup fixes are deliberately conservative: they cover the confirmed case (noise glued to the end of a cell that already has real content), and deliberately do NOT treat "a whole cell that's just short text" as noise — that would break legitimate technical tables (hex values, codes, IDs).

## License

MIT

## Contributing

Issues and PRs with real cases that break the script are more welcome than theoretical suggestions — that's how every fix in here was born.
