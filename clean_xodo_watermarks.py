#!/usr/bin/env python3
"""
clean_xodo_watermark.py — strip the Xodo/PDFTron free-tier watermark from a PDF.

Copyright © 2026 sherlockholmesat221b
Licensed under the GNU General Public License v3.0 (GPLv3).

Made with love by sherlockholmesat221b
(https://github.com/sherlockholmesat221b)

For files too large or too many to run through the in-browser tool
comfortably. Uses pikepdf (libqpdf), which is written in C++ and streams
objects rather than holding everything as parsed JS objects, so it handles
large files (hundreds of MB, hundreds of pages) comfortably.

What it does, and why each step is safe:

  1. Restores each page's true /MediaBox and /CropBox from the
     /xodo_watermark_mediabox marker Xodo itself stashes before expanding
     the page to fit its watermark band - the band ends up outside the
     visible/printable page, cropped away by definition. This only runs
     once nothing else is left in that band (see step 3): the watermark
     itself is already gone by step 2, so the crop is purely cosmetic and
     is skipped rather than risk clipping one of your own annotations.

  2. Empties the one Form XObject per page whose /OC (Optional Content)
     tag points at an OCG literally named "Watermark" - this is the actual
     header/footer overlay. Only direct children of the page's own
     Resources/XObject dict are ever touched, never anything living inside
     an annotation's own appearance stream, so a pasted image or stamp can
     never be mistaken for this.

  3. Removes only the annotation Xodo explicitly self-tags via its own
     /TrnCustomData key containing "xodo_watermark_link" - never a blanket
     text/keyword match, so real hyperlinks and your own annotations are
     left alone regardless of how many of them there are.

  4. Sweeps every remaining indirect object for a stray /OC pointing at
     that same "Watermark" OCG and detaches just the tag (never the
     object) - an object with no /OC is simply always visible, exactly as
     it already was, so this cannot hide or alter anything.

  5. Strips the bare /PDFTRON {/Private /Watermark} metadata key wherever
     it appears (on an object's own dict, or inside its /PieceInfo) - this
     is non-standard vendor metadata every compliant PDF reader already
     ignores, so removing it cannot change how anything renders.

  6. Deletes the /xodo_watermark and /xodo_watermark_page_count flags that
     sit directly on the document catalog - this looks like the actual
     flag Xodo's own app reads to show "This file contains Xodo watermark".

  7. Blanks the name on any now-orphaned "Watermark" OCG definition, and
     drops /OCProperties and /PieceInfo from the catalog (view-layer /
     metadata dicts, not content).

  8. By default, rebuilds the file by copying only pages (and therefore
     only objects actually reachable from them) into a fresh PDF. This is
     the one step the browser tool can't easily do - it drops the dead
     objects left behind by steps 2-7 (an emptied form, a detached OCG
     definition, a removed annotation's now-unreferenced dict) instead of
     leaving them as inert bloat. Use --no-rebuild to skip this and keep
     the original file structure otherwise untouched.

Usage:
    pip install pikepdf
    python3 clean_xodo_watermark.py input.pdf
    python3 clean_xodo_watermark.py input.pdf -o output.pdf
    python3 clean_xodo_watermark.py *.pdf                 # batch, in place suffix
    python3 clean_xodo_watermark.py input.pdf --no-rebuild # keep dead objects
"""

import argparse
import sys
from pathlib import Path

try:
    import pikepdf
except ImportError:
    sys.exit("Missing dependency. Install it with:  pip install pikepdf")


def _lower(v):
    """Best-effort plain lowercase string for a pikepdf Name/String value."""
    try:
        return str(v).lstrip("/").lower()
    except Exception:
        return ""


def _is_watermark_ocg(d):
    try:
        return "watermark" in _lower(d.get("/Name", ""))
    except Exception:
        return False


def _oc_is_watermark(oc):
    if oc is None:
        return False
    t = oc.get("/Type")
    if t == pikepdf.Name("/OCG"):
        return _is_watermark_ocg(oc)
    if t == pikepdf.Name("/OCMD"):
        ocgs = oc.get("/OCGs")
        if ocgs is None:
            return False
        if isinstance(ocgs, pikepdf.Array):
            return any(_is_watermark_ocg(g) for g in ocgs)
        return _is_watermark_ocg(ocgs)
    return False


def _strip_pdftron_watermark_tag(d):
    changed = 0
    try:
        pt = d.get("/PDFTRON")
        if pt is not None and "watermark" in _lower(pt.get("/Private", "")):
            del d["/PDFTRON"]
            changed += 1
    except Exception:
        pass
    try:
        pi = d.get("/PieceInfo")
        if pi is not None:
            pt = pi.get("/PDFTRON")
            if pt is not None and "watermark" in _lower(pt.get("/Private", "")):
                del pi["/PDFTRON"]
                changed += 1
                if len(pi.keys()) == 0:
                    del d["/PieceInfo"]
    except Exception:
        pass
    return changed


def clean(path: Path, out_path: Path, rebuild: bool = True) -> dict:
    pdf = pikepdf.open(path)
    stats = {
        "mediabox_restored": 0,
        "header_forms_removed": 0,
        "watermark_links_removed": 0,
        "oc_tags_detached": 0,
        "pdftron_tags_stripped": 0,
        "catalog_flags_removed": 0,
    }

    for page in pdf.pages:
        # 1. Remove the watermark's own overlay form and its self-tagged
        #    link annotation first, before deciding whether to crop -
        #    otherwise the watermark's own objects would always look like
        #    a reason not to.
        res = page.get("/Resources")
        if res and "/XObject" in res:
            for key in list(res["/XObject"].keys()):
                xo = res["/XObject"][key]
                if _oc_is_watermark(xo.get("/OC")):
                    xo.write(b"")
                    if "/OC" in xo:
                        del xo["/OC"]
                    stats["header_forms_removed"] += 1

        annots = page.get("/Annots")
        if annots:
            for i in range(len(annots) - 1, -1, -1):
                tcd = annots[i].get("/TrnCustomData")
                if tcd is not None and "xodo_watermark" in _lower(tcd):
                    del annots[i]
                    stats["watermark_links_removed"] += 1

        # 2. Only now decide whether to restore the true page size. The
        # watermark is already gone either way - this crop is purely
        # cosmetic, so it only runs when nothing else (your own ink, a
        # stamp, a link) is left reaching into the padding band it would
        # otherwise cut off.
        marker = page.get("/xodo_watermark_mediabox")
        if marker is not None:
            coords = [float(x) for x in str(marker).split(",")]
            del page["/xodo_watermark_mediabox"]

            if len(coords) == 4:
                tx0, ty0, tx1, ty1 = coords
                eps = 0.5  # tolerance for float rounding
                overlaps_band = False

                remaining = page.get("/Annots")
                if remaining:
                    for a in remaining:
                        rect = a.get("/Rect")
                        if rect is None or len(rect) != 4:
                            continue
                        try:
                            rx0, ry0, rx1, ry1 = (float(v) for v in rect)
                        except Exception:
                            continue
                        if rx0 < tx0 - eps or rx1 > tx1 + eps or ry0 < ty0 - eps or ry1 > ty1 + eps:
                            overlaps_band = True
                            break

                if not overlaps_band:
                    box = pikepdf.Array(coords)
                    page["/MediaBox"] = box
                    if "/CropBox" in page:
                        page["/CropBox"] = box
                    stats["mediabox_restored"] += 1
                else:
                    stats["mediabox_skipped_overlap"] = stats.get("mediabox_skipped_overlap", 0) + 1

    for obj in pdf.objects:
        try:
            if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)) and "/OC" in obj:
                if _oc_is_watermark(obj.get("/OC")):
                    del obj["/OC"]
                    stats["oc_tags_detached"] += 1
        except Exception:
            pass

    for obj in pdf.objects:
        try:
            if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
                stats["pdftron_tags_stripped"] += _strip_pdftron_watermark_tag(obj)
        except Exception:
            pass

    root = pdf.Root
    for k in ("/OCProperties", "/PieceInfo", "/xodo_watermark", "/xodo_watermark_page_count"):
        if k in root:
            del root[k]
            stats["catalog_flags_removed"] += 1

    for obj in pdf.objects:
        try:
            if (
                isinstance(obj, pikepdf.Dictionary)
                and obj.get("/Type") == pikepdf.Name("/OCG")
                and _is_watermark_ocg(obj)
            ):
                obj["/Name"] = pikepdf.String("")
                if "/PDFTRON" in obj:
                    del obj["/PDFTRON"]
        except Exception:
            pass

    if rebuild:
        # Copy only objects actually reachable from the page tree into a
        # fresh file, dropping dead husks left by the steps above.
        # object_stream_mode=generate keeps the compact compressed-xref /
        # object-stream layout modern PDF writers (including Xodo's own)
        # use by default - pikepdf.Pdf.new() otherwise falls back to an
        # old-style uncompressed xref table, which is usually bigger than
        # just leaving the dead objects in place.
        fresh = pikepdf.Pdf.new()
        fresh.pages.extend(pdf.pages)
        fresh.save(out_path, object_stream_mode=pikepdf.ObjectStreamMode.generate)
    else:
        pdf.save(out_path)

    return stats


def main():
    ap = argparse.ArgumentParser(description="Strip the Xodo/PDFTron watermark from one or more PDFs.")
    ap.add_argument("inputs", nargs="+", type=Path, help="PDF file(s) to clean")
    ap.add_argument("-o", "--output", type=Path, help="Output path (single-input only; default: <name>_clean.pdf)")
    ap.add_argument("--no-rebuild", action="store_true", help="Skip the final reachability rebuild (keeps dead objects, slightly faster)")
    args = ap.parse_args()

    if args.output and len(args.inputs) > 1:
        sys.exit("--output can only be used with a single input file")

    for src in args.inputs:
        if not src.exists():
            print(f"skip: {src} (not found)", file=sys.stderr)
            continue
        dst = args.output or src.with_name(src.stem + "_clean.pdf")
        try:
            stats = clean(src, dst, rebuild=not args.no_rebuild)
        except Exception as e:
            print(f"FAILED: {src} -> {e}", file=sys.stderr)
            continue

        before = src.stat().st_size
        after = dst.stat().st_size
        print(f"{src.name} -> {dst.name}  ({before:,} -> {after:,} bytes)")
        for k, v in stats.items():
            if v:
                print(f"    {k}: {v}")


if __name__ == "__main__":
    main()
