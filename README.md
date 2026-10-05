# xodo-cleaner

Removes the free-tier "Made with Xodo" watermark from a PDF — the visible
header band, and every detection flag Xodo's own app reads (the
`/xodo_watermark` catalog flag, its `/PDFTRON` metadata tags, the Optional
Content Group named "Watermark", and the self-tagged link annotation).
Your own ink, stamps, pasted images, and links are left untouched; if
anything you drew reaches into the space Xodo added for its watermark, the
page is left at its current size instead of risking a clip.

**[Use it here](https://sherlockholmesat221b.github.io/xodo-cleaner/)** — runs
entirely in your browser, nothing is uploaded.

## Files

- **`index.html`** — the web version above. A single static file, no build
  step, no dependencies beyond [pdf-lib](https://pdf-lib.js.org/) loaded
  from a CDN.
- **[`clean_xodo_watermark.py`](./clean_xodo_watermark.py)** — a
  command-line version for files too large for a browser tab to hold
  comfortably (roughly 50–80 MB+), or for cleaning a batch of files at once.
  Uses [pikepdf](https://pikepdf.readthedocs.io/).

  ```bash
  pip install pikepdf
  python3 clean_xodo_watermark.py input.pdf
  python3 clean_xodo_watermark.py *.pdf          # batch
  ```

## Running it yourself / publishing a copy

This is a plain static site, so GitHub Pages needs nothing but the file:

1. Push `index.html` to the repo (root, or a `/docs` folder — either works).
2. Repo **Settings → Pages → Source**, pick the branch and folder it's in.
3. Your copy is live at `https://<you>.github.io/<repo>/` a minute or two
   later.

No build step, no config file, nothing to install.

## How it works

Every step keys off something Xodo itself marks as watermark-related, never
a blanket keyword match — see the comments in `clean_xodo_watermark.py` for
the full breakdown of each pass.
