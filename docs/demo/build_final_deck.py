"""Fill the hand-authored presenter template into docs/demo/EDB_Final_Deck.pptx.

    .venv/bin/python docs/demo/build_final_deck.py

The template (``docs/demo/edb automation final template.pptx``) is never written
to: it is copied first, and the copy is filled. Section dividers, the three
slides already pasted in from the technical deep-dive (12 DB schema, 14
evaluation, 16 models) and the demo-video slide (22) are left exactly as they
are — only the empty content slides named in final_content.FILL are touched.

Content lives in deck/final_content.py; diagrams in deck/diagrams.py; the
shapes are drawn by the same renderers that build the deep-dive deck.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "deck"))

import render_pptx                                  # noqa: E402
from final_content import FILL, INSERTS             # noqa: E402
from pptx_kit import (Deck, clear_slide, move_slide,        # noqa: E402
                      strip_placeholders)

TEMPLATE = os.path.join(HERE, "edb automation final template.pptx")
OUT = os.path.join(HERE, "EDB_Final_Deck.pptx")


def _title_of(slide):
    for sh in slide.shapes:
        if sh.has_text_frame and sh.text_frame.text.strip():
            return sh.text_frame.text.strip().splitlines()[0][:64]
    return ""


def main():
    shutil.copyfile(TEMPLATE, OUT)
    deck = Deck.open(OUT, footer=None)
    # the imported deep-dive slides carry a bare 26pt title and no footer; match them
    deck.plain_header = True
    render_pptx.set_deck(deck)
    # the title-only header frees ~0.3" the deep-dive's header band needed, so the
    # diagram canvas starts higher and runs taller here
    render_pptx.DY = render_pptx.Inches(1.52)
    render_pptx.DH = render_pptx.Inches(4.88)
    prs = deck.prs

    for n, spec in sorted(FILL.items()):
        sl = prs.slides[n - 1]
        if spec.get("clear"):
            clear_slide(sl)          # replaces a slide pasted in from another deck
        else:
            strip_placeholders(sl, empty_only=not spec.get("strip_all"))
        render_pptx.RENDERERS[spec["kind"]](spec, sl=sl)
        print(f"  filled slide {n:>2}  {spec['kind']:<8} {spec['title']}")

    # appended, then moved into place — python-pptx cannot insert
    for spec, target in INSERTS:
        render_pptx.RENDERERS[spec["kind"]](spec)
        move_slide(prs, len(prs.slides._sldIdLst) - 1, target)
        print(f"  inserted at {target + 1:>2}  {spec['kind']:<8} {spec['title']}")

    deck.save(OUT)

    print(f"\nwrote {OUT}  ({len(prs.slides)} slides)\n")
    for i, sl in enumerate(prs.slides, 1):
        print(f"  {i:>2}  {sl.slide_layout.name:<18} {len(sl.shapes):>3} shapes  "
              f"{_title_of(sl)}")


if __name__ == "__main__":
    main()
