"""Render the technical deep-dive deck to docs/demo/EDB_Technical_Deep_Dive.pptx.

Diagrams become native autoshapes and connectors — editable in PowerPoint, and
crisp at any zoom — using the geometry solved in diagrams.py, the same geometry
the web renderer consumes.

    .venv/bin/python docs/demo/deck/render_pptx.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

import diagrams as D
from content import SLIDES
from pptx_kit import (AMBER, CODE_ACC, CODE_FG, Deck, EDB, EDB_DK, GREEN, GREY,
                      INK, LIGHT, MONO, RED, RULE, WHITE, IMG)

ADVANCE_EM = 0.70   # widest plausible monospace advance, in em

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "EDB_Technical_Deep_Dive.pptx")

# diagram node styling by semantic kind
TINT_LLM = RGBColor(0xFD, 0xF3, 0xE3)
TINT_DATA = RGBColor(0xEA, 0xF0, 0xF7)
TINT_OUT = RGBColor(0xEA, 0xF6, 0xEE)
NODE_STYLE = {
    D.CORE:    dict(fill=LIGHT, line=EDB, fg=INK, sub=GREY),
    D.SURFACE: dict(fill=WHITE, line=EDB, fg=EDB_DK, sub=GREY),
    D.SEAL:    dict(fill=EDB, line=EDB_DK, fg=WHITE, sub=RGBColor(0xC8, 0xD6, 0xE8)),
    D.LLM:     dict(fill=TINT_LLM, line=AMBER, fg=RGBColor(0x7A, 0x2F, 0x05), sub=GREY),
    D.DATA:    dict(fill=TINT_DATA, line=GREY, fg=INK, sub=GREY),
    D.OUT:     dict(fill=TINT_OUT, line=GREEN, fg=RGBColor(0x10, 0x50, 0x24), sub=GREY),
    D.GROUP:   dict(fill=None, line=RULE, fg=GREY, sub=GREY),
    D.NOTE:    dict(fill=WHITE, line=GREY, fg=GREY, sub=GREY),
}

deck = Deck()


def set_deck(d):
    """Point the renderers at another Deck — build_final_deck.py fills the
    hand-authored template rather than building a deck from scratch."""
    global deck
    deck = d

# diagram canvas on the slide
DX, DY = Inches(0.55), Inches(1.80)
DW, DH = Inches(12.25), Inches(4.55)


def nx(x):
    return DX + DW * (x / 100.0)


def ny(y):
    return DY + DH * (y / 100.0)


# --------------------------------------------------------------------- slides
def render_title(s, sl=None):
    sl = sl or deck.slide(INK)
    deck.box(sl, 0, Inches(3.05), deck.SW, Pt(3), fill=EDB)
    deck.text(sl, Inches(0.9), Inches(1.05), Inches(11.5), Inches(0.4),
              [[(s["eyebrow"], 12, True, RGBColor(0x8F, 0xB2, 0xD8))]])
    lines = s["title"].split("\n")
    deck.text(sl, Inches(0.9), Inches(1.5), Inches(11.6), Inches(1.6),
              [[(ln, 40, True, WHITE)] for ln in lines], space=2)
    deck.text(sl, Inches(0.9), Inches(3.35), Inches(11.5), Inches(0.6),
              [[(s["subtitle"], 19, False, RGBColor(0xC8, 0xD6, 0xE8))]])
    deck.text(sl, Inches(0.9), Inches(4.35), Inches(11.5), Inches(0.9),
              [[(s["meta"], 13, False, RGBColor(0x9F, 0xB0, 0xC4))]], space=4)
    deck.text(sl, Inches(0.9), Inches(6.75), Inches(11.5), Inches(0.4),
              [[(s["foot"], 11, False, RGBColor(0x6E, 0x80, 0x96))]])


def render_bullets(s, sl=None):
    sl = sl or deck.slide()
    deck.header(sl, s["kicker"], s["title"])
    h = Inches(4.55) if s.get("note") else Inches(5.1)
    deck.bullets(sl, s["items"], Inches(0.9), Inches(1.85), Inches(11.5), h,
                 size=14.5, gap=12)
    if s.get("note"):
        _note(sl, s["note"])
    deck.footer(sl)


def _note(sl, text, top=Inches(6.42)):
    deck.box(sl, Inches(0.9), top, Inches(11.5), Pt(2), fill=EDB)
    deck.text(sl, Inches(0.9), top + Inches(0.1), Inches(11.5), Inches(0.55),
              [[(text, 10, False, GREY)]])


def render_table(s, sl=None):
    sl = sl or deck.slide()
    deck.header(sl, s["kicker"], s["title"])
    y = Inches(1.78)
    if s.get("intro"):
        tb = deck.text(sl, Inches(0.9), y, Inches(11.5), Inches(0.7),
                       [[(s["intro"], 11.5, False, GREY)]])
        y += Inches(0.68)
    widths = [Inches(v) for v in s["col_w"]]
    total = sum(widths)
    n = len(s["rows"])
    row_h = Inches(0.30) if n <= 11 else Inches(0.255)
    size = 10.5 if n <= 11 else 9.8
    colors = {}
    hc = s.get("highlight_col")
    if hc is not None:
        for i, r in enumerate(s["rows"]):
            v = str(r[hc])
            if "CONFIRMED" in v or v == "yes":
                colors[(i, hc)] = GREEN
            elif "ASSUMED" in v or v == "none":
                colors[(i, hc)] = AMBER
            elif v == "0":
                colors[(i, hc)] = RED
            else:
                colors[(i, hc)] = EDB_DK
    end = deck.table(sl, Inches(0.9), y, total, s["cols"], s["rows"],
                     col_w=widths, size=size, row_h=row_h, cell_colors=colors)
    if s.get("bullets"):
        deck.bullets(sl, s["bullets"], Inches(0.9), end + Inches(0.12),
                     Inches(11.5), Inches(1.0), size=10.5, gap=5)
    if s.get("note"):
        _note(sl, s["note"], top=Inches(6.5))
    deck.footer(sl)


def render_code(s, sl=None):
    sl = sl or deck.slide()
    deck.header(sl, s["kicker"], s["title"])
    y = Inches(1.78)
    if s.get("intro"):
        deck.text(sl, Inches(0.9), y, Inches(11.5), Inches(0.62),
                  [[(s["intro"], 11.5, False, GREY)]])
        y += Inches(0.62)
    lines = _code_lines(s["code"])
    has_side = bool(s.get("bullets"))
    cw = Inches(7.05) if has_side else Inches(11.5)
    size, ch = _fit_code(lines, cw)
    deck.code(sl, Inches(0.9), y, cw, ch, lines, size=size)
    if has_side:
        deck.bullets(sl, s["bullets"], Inches(8.2), y - Inches(0.04),
                     Inches(4.25), Inches(4.5), size=10.5, gap=8)
    elif s.get("table_rows"):
        widths = [Inches(v) for v in s["table_col_w"]]
        deck.table(sl, Inches(0.9), y + ch + Inches(0.22), sum(widths),
                   s["table_cols"], s["table_rows"], col_w=widths,
                   size=10.5, row_h=Inches(0.29))
    if s.get("note"):
        _note(sl, s["note"], top=Inches(6.5))
    deck.footer(sl)


def _code_lines(code):
    return [(t, CODE_ACC if (isinstance(l, tuple) and l[1] == "acc") else CODE_FG)
            for l in code for t in [l[0] if isinstance(l, tuple) else l]]


def _fit_code(lines, cw, max_size=11.5, min_size=8.5):
    """Pick a monospace size whose longest line fits cw, and the height it needs.

    ADVANCE_EM is set for the WIDEST mono a viewer might substitute, not for
    Consolas itself (~0.55). Being pessimistic only makes text slightly smaller;
    being optimistic makes it overflow, which is far worse.

    Without this, a long line soft-wraps inside the text frame and the block
    renders taller than the dark panel behind it — the text spills onto the white
    slide. Consolas advances ~0.55 em per character.
    """
    longest = max((len(t) for t, _ in lines), default=1)
    avail = cw / 914400.0 - 0.52          # EMU -> inches, minus panel padding
    size = min(max_size, avail * 72.0 / (ADVANCE_EM * longest))
    size = max(min_size, size)
    line_h = size * 1.42 / 72.0
    return size, Inches(line_h * len(lines) + 0.30)


def render_stats(s, sl=None):
    sl = sl or deck.slide()
    deck.header(sl, s["kicker"], s["title"])
    y = Inches(1.78)
    if s.get("intro"):
        deck.text(sl, Inches(0.9), y, Inches(11.5), Inches(0.6),
                  [[(s["intro"], 11.5, False, GREY)]])
        y += Inches(0.6)
    n = len(s["stats"])
    gap = Inches(0.2)
    w = (Inches(11.5) - gap * (n - 1)) / n
    for i, (val, label, note) in enumerate(s["stats"]):
        color = GREEN if val == "OK" else EDB
        deck.stat(sl, Inches(0.9) + (w + gap) * i, y, w, Inches(1.5),
                  val, label, note, color=color)
    y += Inches(1.72)
    if s.get("code"):
        lines = _code_lines(s["code"])
        size, ch = _fit_code(lines, Inches(11.5))
        deck.code(sl, Inches(0.9), y, Inches(11.5), ch, lines, size=size)
    if s.get("note"):
        _note(sl, s["note"], top=Inches(6.5))
    deck.footer(sl)


def render_image(s, sl=None):
    sl = sl or deck.slide()
    deck.header(sl, s["kicker"], s["title"])
    path = os.path.join(IMG, s["img"])
    if s.get("crop"):
        path = _crop(path, s["crop"])
    deck.img_fit(sl, path, Inches(0.9), Inches(1.8), Inches(6.5), Inches(4.5))
    if s.get("bullets"):
        deck.bullets(sl, s["bullets"], Inches(7.65), Inches(1.78),
                     Inches(4.8), Inches(4.6), size=11, gap=10)
    if s.get("note"):
        _note(sl, s["note"], top=Inches(6.5))
    deck.footer(sl)


def _crop(path, box):
    """Crop a screenshot to a fractional box; sticky headers make full-page
    captures awkward, and cropping beats re-capturing at a fixed scroll offset."""
    try:
        from PIL import Image
    except ImportError:
        return path
    im = Image.open(path)
    W, H = im.size
    l, t, r, b = box
    # a build artifact, so keep it out of the committed screenshot directory
    tmp = tempfile.mkdtemp(prefix="edb_deck_")
    out = os.path.join(tmp, "crop_" + os.path.basename(path))
    im.crop((int(W * l), int(H * t), int(W * r), int(H * b))).save(out)
    return out


def render_split(s, sl=None):
    sl = sl or deck.slide()
    deck.header(sl, s["kicker"], s["title"])
    top = Inches(1.82)
    h = Inches(4.45) if s.get("note") else Inches(4.9)
    w = Inches(5.65)
    for x, head, items, col in ((Inches(0.9), s["left_head"], s["left"], EDB),
                                (Inches(6.78), s["right_head"], s["right"], EDB_DK)):
        deck.box(sl, x, top, w, Inches(0.5), fill=col)
        deck.text(sl, x + Inches(0.15), top, w - Inches(0.2), Inches(0.5),
                  [[(head, 12.5, True, WHITE)]], anchor=MSO_ANCHOR.MIDDLE)
        deck.box(sl, x, top + Inches(0.5), w, h - Inches(0.5), fill=LIGHT)
        deck.bullets(sl, items, x + Inches(0.2), top + Inches(0.66),
                     w - Inches(0.42), h - Inches(0.8), size=10.5, gap=8)
    if s.get("note"):
        _note(sl, s["note"], top=Inches(6.45))
    deck.footer(sl)


def render_eval(s, sl=None):
    sl = sl or deck.slide()
    deck.header(sl, s["kicker"], s["title"])
    # headline band — the number and its scope, together
    deck.box(sl, Inches(0.9), Inches(1.8), Inches(11.5), Inches(0.92), fill=LIGHT)
    deck.box(sl, Inches(0.9), Inches(1.8), Pt(5), Inches(0.92), fill=AMBER)
    deck.text(sl, Inches(1.15), Inches(1.88), Inches(7.4), Inches(0.42),
              [[(s["headline"], 19, True, EDB_DK)]])
    deck.text(sl, Inches(1.15), Inches(2.28), Inches(7.4), Inches(0.34),
              [[(s["subhead"], 11, False, GREY)]], font=MONO)
    deck.text(sl, Inches(8.75), Inches(1.9), Inches(3.5), Inches(0.75),
              [[(s["claim"], 12, True, AMBER)]], anchor=MSO_ANCHOR.MIDDLE)
    # the substance
    deck.bullets(sl, s["body"], Inches(0.9), Inches(2.92), Inches(7.55),
                 Inches(3.4), size=10.5, gap=8)
    # quote + corollary
    qx = Inches(8.72)
    deck.box(sl, qx, Inches(2.92), Inches(3.68), Inches(1.28), fill=INK)
    deck.text(sl, qx + Inches(0.18), Inches(3.0), Inches(3.32), Inches(0.8),
              [[(s["quote"], 11.5, True, RGBColor(0xE6, 0xEE, 0xF8))]])
    deck.text(sl, qx + Inches(0.18), Inches(3.82), Inches(3.32), Inches(0.32),
              [[(s["quote_src"], 8.5, False, RGBColor(0x9F, 0xB0, 0xC4))]])
    deck.box(sl, qx, Inches(4.32), Inches(3.68), Inches(1.02), fill=TINT_LLM)
    deck.text(sl, qx + Inches(0.15), Inches(4.4), Inches(3.4), Inches(0.9),
              [[(s["corollary"], 10, False, RGBColor(0x7A, 0x2F, 0x05))]])
    # probe taxonomy
    ty = Inches(5.48)
    deck.text(sl, qx, ty - Inches(0.2), Inches(3.68), Inches(0.2),
              [[("33 PROBES", 8.5, True, GREY)]])
    tw = Inches(3.68) / len(s["taxonomy"])
    for i, (cnt, lab) in enumerate(s["taxonomy"]):
        x = qx + tw * i
        deck.box(sl, x, ty, tw - Pt(2), Inches(0.62), fill=LIGHT)
        deck.text(sl, x, ty + Inches(0.04), tw - Pt(2), Inches(0.26),
                  [[(cnt, 13, True, EDB)]], align=PP_ALIGN.CENTER)
        deck.text(sl, x, ty + Inches(0.3), tw - Pt(2), Inches(0.3),
                  [[(lab, 7, False, GREY)]], align=PP_ALIGN.CENTER)
    _note(sl, s["note"], top=Inches(6.42))
    deck.footer(sl)


def render_closing(s, sl=None):
    sl = sl or deck.slide()
    deck.header(sl, s["kicker"], s["title"])
    top = Inches(1.82)
    h = Inches(3.05)
    w = Inches(3.72)
    cols = [(Inches(0.9), s["solid_head"], s["solid"], GREEN),
            (Inches(4.78), s["open_head"], s["open"], AMBER),
            (Inches(8.66), s["gaps_head"], s["gaps"], GREY)]
    for x, head, items, col in cols:
        deck.box(sl, x, top, w, Inches(0.46), fill=col)
        deck.text(sl, x + Inches(0.14), top, w - Inches(0.2), Inches(0.46),
                  [[(head, 12, True, WHITE)]], anchor=MSO_ANCHOR.MIDDLE)
        deck.box(sl, x, top + Inches(0.46), w, h - Inches(0.46), fill=LIGHT)
        deck.bullets(sl, items, x + Inches(0.18), top + Inches(0.6),
                     w - Inches(0.38), h - Inches(0.72), size=9.5, gap=6,
                     marker_color=col)
    deck.box(sl, Inches(0.9), Inches(5.15), Inches(11.5), Inches(1.15), fill=INK)
    deck.text(sl, Inches(0.9), Inches(5.15), Inches(11.5), Inches(1.15),
              [[(s["close"], 22, True, WHITE)]],
              align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    deck.footer(sl)


# ------------------------------------------------------------------ diagrams
def render_diagram(s, sl=None):
    dg = D.ALL[s["key"]]
    sl = sl or deck.slide()
    deck.header(sl, s["kicker"], s["title"])

    # containers first so nodes sit on top
    for n in dg["nodes"]:
        if n["kind"] == D.GROUP:
            _node(sl, n)

    # the hard-boundary rule (component map)
    if dg.get("barrier"):
        by = ny(dg["barrier"]["y"])
        deck.box(sl, nx(0), by, DW, Pt(2.5), fill=AMBER)
        deck.text(sl, nx(0), by + Inches(0.05), DW, Inches(0.26),
                  [[(dg["barrier"]["label"], 9, True, AMBER)]])

    # the vertical no-import barrier (trust boundary)
    if dg.get("vbarrier"):
        bx = nx(dg["vbarrier"]["x"])
        for k in range(11):
            yy = ny(4) + (DH * 0.62) * k / 11.0
            deck.box(sl, bx, yy, Pt(2.5), Inches(0.2), fill=RED)
        deck.text(sl, bx - Inches(0.62), ny(dg["vbarrier"].get("label_y", 68)), Inches(1.3), Inches(0.3),
                  [[(dg["vbarrier"]["label"], 8.5, True, RED)]], align=PP_ALIGN.CENTER)

    for n in dg["nodes"]:
        if n["kind"] != D.GROUP:
            _node(sl, n)

    for e in dg["edges"]:
        pts = D.edge_points(dg, e)
        dashed = e["style"] == "dashed"
        col = AMBER if dashed else EDB
        for i in range(len(pts) - 1):
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            last = i == len(pts) - 2
            deck.connector(sl, nx(x1), ny(y1), nx(x2), ny(y2),
                           color=col, arrow=last, dashed=dashed,
                           width=Pt(1.25))
        if e.get("label"):
            _edge_label(sl, pts, e["label"], col)

    if dg.get("footnotes"):
        fx = nx(2)
        fy = ny(77)
        deck.text(sl, fx, fy, DW - Inches(0.4), Inches(0.9),
                  [[("GUARDRAILS   ", 9, True, GREY)] +
                   [(" ·  ".join(dg["footnotes"]), 9.5, False, INK)]])
    if dg.get("caption"):
        _note(sl, dg["caption"], top=Inches(6.5))
    deck.footer(sl)


def _edge_label(sl, pts, label, col):
    """Place the label beside the longest segment, offset perpendicular to it, so
    it never lands on top of a node it merely passes."""
    best, blen, vert = 0, -1.0, False
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        ln = abs(x2 - x1) + abs(y2 - y1)
        if ln > blen:
            best, blen, vert = i, ln, abs(y2 - y1) > abs(x2 - x1)
    (x1, y1), (x2, y2) = pts[best], pts[best + 1]
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    if vert:
        l, t, align = nx(mx) + Inches(0.07), ny(my) - Inches(0.12), PP_ALIGN.LEFT
    else:
        l, t, align = nx(mx) - Inches(0.8), ny(my) - Inches(0.26), PP_ALIGN.CENTER
    deck.text(sl, l, t, Inches(1.6), Inches(0.22),
              [[(label, 8, True, col)]], align=align)


def _node(sl, n):
    st = NODE_STYLE[n["kind"]]
    l, t = nx(n["x"]), ny(n["y"])
    w = DW * (n["w"] / 100.0)
    h = DH * (n["h"] / 100.0)
    if n["kind"] == D.GROUP:
        shp = deck.box(sl, l, t, w, h, fill=None, line=st["line"], line_w=Pt(1.25))
        deck.text(sl, l, t + Inches(0.06), w, Inches(0.26),
                  [[(n["label"], 9.5, True, st["fg"])]], align=PP_ALIGN.CENTER)
        return shp
    shp = deck.box(sl, l, t, w, h, fill=st["fill"], line=st["line"],
                   shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    sub = n.get("sub")
    label_sz = 11 if h > Inches(0.7) else 10
    runs = [[(n["label"], label_sz, True, st["fg"])]]
    if sub:
        for ln in sub.split("\n"):
            runs.append([(ln, 8.2, False, st["sub"])])
    deck.text(sl, l + Inches(0.08), t + Inches(0.05), w - Inches(0.16), h - Inches(0.1),
              runs, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, space=1)
    return shp


RENDERERS = {
    "title": render_title, "bullets": render_bullets, "table": render_table,
    "code": render_code, "diagram": render_diagram, "stats": render_stats,
    "image": render_image, "split": render_split, "eval": render_eval,
    "closing": render_closing,
}


def main():
    for i, s in enumerate(SLIDES, 1):
        fn = RENDERERS.get(s["kind"])
        if fn is None:
            raise SystemExit(f"slide {i}: unknown kind {s['kind']!r}")
        fn(s)
    deck.save(OUT)
    print(f"wrote {OUT}  ({len(SLIDES)} slides)")


if __name__ == "__main__":
    main()
