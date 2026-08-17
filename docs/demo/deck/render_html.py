"""Render the technical deep-dive deck to a self-contained HTML page.

Same content.py spine and same diagrams.py geometry as render_pptx.py — the two
media cannot drift, because neither owns the content or the layout maths.

Design system ("audit ledger"): cool blue-biased paper, EDB navy as the accent
because it is the actual scheme brand, hairline ledger rules, and three type
roles that each mean something — sans for the document's own voice, mono for
anything the machine produced (paths, figures, code, status chips), serif italic
for the one line the harness says about itself.

    .venv/bin/python docs/demo/deck/render_html.py
"""
import base64
import html
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import diagrams as D
from content import SLIDES

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(os.path.dirname(HERE), "img")
OUT = os.path.join(HERE, "edb_technical_deck.html")

# diagram canvas: normalized 0-100 -> viewBox units
VBW, VBH = 1000.0, 470.0

KIND_CLASS = {
    D.CORE: "n-core", D.SURFACE: "n-surface", D.SEAL: "n-seal",
    D.LLM: "n-llm", D.DATA: "n-data", D.OUT: "n-out", D.GROUP: "n-group",
}


def e(s):
    return html.escape(str(s), quote=True)


def data_uri(name, max_w=1500, crop=None):
    path = os.path.join(IMG, name)
    if not os.path.exists(path):
        return None
    try:
        from PIL import Image
    except ImportError:
        with open(path, "rb") as fh:
            return "data:image/png;base64," + base64.b64encode(fh.read()).decode()
    im = Image.open(path)
    if crop:
        W, H = im.size
        l, t, r, b = crop
        im = im.crop((int(W * l), int(H * t), int(W * r), int(H * b)))
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------- svg
def svg_diagram(key):
    dg = D.ALL[key]

    def X(x):
        return round(x * VBW / 100.0, 1)

    def Y(y):
        return round(y * VBH / 100.0, 1)

    parts = [
        f'<svg role="img" aria-label="{e(dg["title"])}" viewBox="0 0 {int(VBW)} {int(VBH)}" '
        f'class="dg">',
        '<defs>'
        '<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,1 L9,5 L0,9 z" fill="context-stroke"/></marker>'
        '</defs>',
    ]

    # containers first
    for n in dg["nodes"]:
        if n["kind"] == D.GROUP:
            parts.append(
                f'<rect class="n-group" x="{X(n["x"])}" y="{Y(n["y"])}" '
                f'width="{X(n["w"])}" height="{Y(n["h"])}" rx="8"/>')
            parts.append(
                f'<text class="glabel" x="{X(n["x"] + n["w"] / 2)}" '
                f'y="{Y(n["y"]) + 17}" text-anchor="middle">{e(n["label"])}</text>')

    if dg.get("barrier"):
        by = Y(dg["barrier"]["y"])
        parts.append(f'<line class="barrier" x1="0" y1="{by}" x2="{int(VBW)}" y2="{by}"/>')
        parts.append(f'<text class="barrier-t" x="2" y="{by + 15}">'
                     f'{e(dg["barrier"]["label"])}</text>')

    if dg.get("vbarrier"):
        bx = X(dg["vbarrier"]["x"])
        parts.append(f'<line class="vbarrier" x1="{bx}" y1="{Y(4)}" x2="{bx}" y2="{Y(66)}"/>')
        parts.append(f'<text class="vbarrier-t" x="{bx}" y="{Y(dg["vbarrier"].get("label_y", 69))}" text-anchor="middle">'
                     f'{e(dg["vbarrier"]["label"])}</text>')

    # edges under nodes so a line never crosses a label
    for ed in dg["edges"]:
        pts = D.edge_points(dg, ed)
        d = " ".join(f"{X(x)},{Y(y)}" for x, y in pts)
        cls = "edge dashed" if ed["style"] == "dashed" else "edge"
        parts.append(f'<polyline class="{cls}" points="{d}" marker-end="url(#ar)"/>')
        if ed.get("label"):
            parts.append(_edge_label(pts, ed["label"], X, Y))

    for n in dg["nodes"]:
        if n["kind"] == D.GROUP:
            continue
        cls = KIND_CLASS[n["kind"]]
        parts.append(
            f'<rect class="{cls}" x="{X(n["x"])}" y="{Y(n["y"])}" '
            f'width="{X(n["w"])}" height="{Y(n["h"])}" rx="7"/>')
        cx = X(n["x"] + n["w"] / 2)
        subs = (n.get("sub") or "").split("\n") if n.get("sub") else []
        subs = [s for s in subs]
        total = 1 + len(subs)
        # vertically centre the label block inside the box
        line_h = 14.5
        top = Y(n["y"] + n["h"] / 2) - (total * line_h) / 2 + 12
        parts.append(f'<text class="nlabel {cls}-t" x="{cx}" y="{round(top, 1)}" '
                     f'text-anchor="middle">{e(n["label"])}</text>')
        for i, s in enumerate(subs):
            if not s.strip():
                continue
            parts.append(
                f'<text class="nsub {cls}-t" x="{cx}" '
                f'y="{round(top + line_h * (i + 1), 1)}" text-anchor="middle">{e(s)}</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def _edge_label(pts, label, X, Y):
    best, blen, vert = 0, -1.0, False
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        ln = abs(x2 - x1) + abs(y2 - y1)
        if ln > blen:
            best, blen, vert = i, ln, abs(y2 - y1) > abs(x2 - x1)
    (x1, y1), (x2, y2) = pts[best], pts[best + 1]
    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    if vert:
        return (f'<text class="elabel" x="{X(mx) + 6}" y="{Y(my)}" '
                f'text-anchor="start">{e(label)}</text>')
    return (f'<text class="elabel" x="{X(mx)}" y="{Y(my) - 6}" '
            f'text-anchor="middle">{e(label)}</text>')


# ------------------------------------------------------------------ slides
def bullet_list(items, cls="blist"):
    out = [f'<ul class="{cls}">']
    for it in items:
        if isinstance(it, tuple):
            out.append(f"<li><b>{e(it[0])}</b> {e(it[1])}</li>")
        else:
            out.append(f"<li>{e(it)}</li>")
    out.append("</ul>")
    return "\n".join(out)


def code_block(code):
    rows = []
    for ln in code:
        txt, acc = (ln[0], True) if isinstance(ln, tuple) else (ln, False)
        cls = ' class="c-acc"' if acc else ""
        rows.append(f"<span{cls}>{e(txt) or '&nbsp;'}</span>")
    return '<div class="codewrap"><pre class="code">' + "\n".join(rows) + "</pre></div>"


def status_chip(v):
    v = str(v)
    if "CONFIRMED" in v or v == "yes":
        k = "ok"
    elif "ASSUMED" in v or v == "none":
        k = "warn"
    elif v == "0":
        k = "crit"
    else:
        k = "neutral"
    return f'<span class="chip chip-{k}">{e(v)}</span>'


NUMERIC = set("0123456789,.$%")


def table_block(cols, rows, highlight=None):
    out = ['<div class="tablewrap"><table><thead><tr>']
    for c in cols:
        out.append(f"<th>{e(c)}</th>")
    out.append("</tr></thead><tbody>")
    for r in rows:
        out.append("<tr>")
        for j, cell in enumerate(r):
            s = str(cell)
            if highlight is not None and j == highlight:
                out.append(f"<td>{status_chip(s)}</td>")
            elif j == 0:
                out.append(f'<td class="k">{e(s)}</td>')
            elif s and set(s) <= NUMERIC:
                out.append(f'<td class="num">{e(s)}</td>')
            else:
                out.append(f"<td>{e(s)}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def render_slide(i, s):
    k = s["kind"]
    kicker = s.get("kicker", "")
    title = s.get("title", "")
    head = ""
    if k != "title":
        head = (f'<header class="shead"><p class="kicker">{e(kicker)}</p>'
                f'<h2>{e(title)}</h2></header>')
    body = []

    if k == "title":
        body.append(f'''<div class="hero">
<p class="eyebrow">{e(s["eyebrow"])}</p>
<h1>{"<br>".join(e(l) for l in s["title"].split(chr(10)))}</h1>
<p class="sub">{e(s["subtitle"])}</p>
<p class="meta">{e(s["meta"])}</p>
<dl class="topstats">
  <div><dt>tests passing</dt><dd class="num">131</dd></div>
  <div><dt>support rate</dt><dd class="num">60%</dd></div>
  <div><dt>method A oracle</dt><dd class="num">$7,310.87</dd></div>
  <div><dt>evidence refs</dt><dd class="num">312</dd></div>
</dl>
<p class="foot">{e(s["foot"])}</p></div>''')

    elif k == "bullets":
        body.append(bullet_list(s["items"], "blist lead"))

    elif k == "table":
        if s.get("intro"):
            body.append(f'<p class="intro">{e(s["intro"])}</p>')
        body.append(table_block(s["cols"], s["rows"], s.get("highlight_col")))
        if s.get("bullets"):
            body.append(bullet_list(s["bullets"]))

    elif k == "code":
        if s.get("intro"):
            body.append(f'<p class="intro">{e(s["intro"])}</p>')
        if s.get("bullets"):
            body.append('<div class="two"><div>' + code_block(s["code"]) + "</div><div>"
                        + bullet_list(s["bullets"]) + "</div></div>")
        else:
            body.append(code_block(s["code"]))
            if s.get("table_rows"):
                body.append(table_block(s["table_cols"], s["table_rows"]))

    elif k == "stats":
        if s.get("intro"):
            body.append(f'<p class="intro">{e(s["intro"])}</p>')
        cards = []
        for val, label, note in s["stats"]:
            mark = "ok" if val == "OK" else "accent"
            cards.append(f'<div class="stat stat-{mark}"><p class="sv num">{e(val)}</p>'
                         f'<p class="sl">{e(label)}</p><p class="sn">{e(note)}</p></div>')
        body.append('<div class="stats">' + "".join(cards) + "</div>")
        if s.get("code"):
            body.append(code_block(s["code"]))

    elif k == "diagram":
        dg = D.ALL[s["key"]]
        # footnotes live in HTML, not in the SVG: <text> cannot wrap, and the
        # guardrail list is far wider than the viewBox.
        guards = ""
        if dg.get("footnotes"):
            chips = "".join(f"<li>{e(g)}</li>" for g in dg["footnotes"])
            guards = (f'<div class="guards"><p class="guardh">Guardrails</p>'
                      f'<ul>{chips}</ul></div>')
        body.append('<figure class="fig">' + svg_diagram(s["key"]) + guards
                    + f'<figcaption>{e(dg["caption"])}</figcaption></figure>')

    elif k == "image":
        uri = data_uri(s["img"], crop=s.get("crop"))
        shot = (f'<figure class="shot"><img src="{uri}" alt="Live capture of the '
                f'Method A vs Method B cross-check table in the running app"/></figure>'
                if uri else "")
        body.append('<div class="two wide-left">' + shot + "<div>"
                    + bullet_list(s["bullets"]) + "</div></div>")

    elif k == "split":
        body.append(f'''<div class="two">
<section class="panel"><h3>{e(s["left_head"])}</h3>{bullet_list(s["left"])}</section>
<section class="panel panel-alt"><h3>{e(s["right_head"])}</h3>{bullet_list(s["right"])}</section>
</div>''')

    elif k == "eval":
        tax = "".join(f'<div><dt class="num">{e(c)}</dt><dd>{e(l)}</dd></div>'
                      for c, l in s["taxonomy"])
        body.append(f'''<div class="headline">
  <div><p class="hl">{e(s["headline"])}</p>
       <p class="hlsub">{e(s["subhead"])}</p></div>
  <p class="hlclaim">{e(s["claim"])}</p>
</div>
<div class="two">
  <div>{bullet_list(s["body"])}</div>
  <div class="evalside">
    <blockquote><p>{e(s["quote"])}</p><cite>{e(s["quote_src"])}</cite></blockquote>
    <p class="corollary">{e(s["corollary"])}</p>
    <dl class="tax"><p class="taxh">33 probes</p>{tax}</dl>
  </div>
</div>''')

    elif k == "closing":
        def col(headn, items, mark):
            lis = []
            for it in items:
                if isinstance(it, tuple):
                    lis.append(f"<li><b>{e(it[0])}</b> {e(it[1])}</li>")
                else:
                    lis.append(f"<li>{e(it)}</li>")
            return (f'<section class="panel mark-{mark}"><h3>{e(headn)}</h3>'
                    f'<ul class="blist">{"".join(lis)}</ul></section>')
        body.append('<div class="three">'
                    + col(s["solid_head"], s["solid"], "ok")
                    + col(s["open_head"], s["open"], "warn")
                    + col(s["gaps_head"], s["gaps"], "neutral")
                    + "</div>")
        body.append(f'<p class="close">{e(s["close"])}</p>')

    if s.get("note"):
        body.append(f'<p class="note">{e(s["note"])}</p>')

    cls = "slide" + (" slide-title" if k == "title" else "")
    return (f'<section class="{cls}" id="s{i}" data-n="{i}" '
            f'aria-label="{e(title or "Title")}">'
            f'<div class="inner">{head}{"".join(body)}</div>'
            f'<p class="pnum num">{i:02d} / {len(SLIDES)}</p></section>')


def nav():
    out = ['<nav class="rail" aria-label="Slides">',
           '<p class="railtitle">EDB RIS(C)<br><span>technical deep-dive</span></p>',
           '<ol>']
    for i, s in enumerate(SLIDES, 1):
        label = s.get("title", "Title") if s["kind"] != "title" else "Title"
        out.append(f'<li><a href="#s{i}"><span class="rn num">{i:02d}</span>'
                   f'<span class="rt">{e(label)}</span></a></li>')
    out.append("</ol></nav>")
    return "\n".join(out)


CSS = """
:root{
  --ground:#F5F8FC; --surface:#FFFFFF; --raise:#EEF3F9;
  --ink:#0B1220; --muted:#596373; --faint:#8794A6;
  --accent:#1F4E79; --accent-soft:#E7EFF7;
  --ok:#1A7F37; --ok-soft:#E8F4EC;
  --warn:#B54708; --warn-soft:#FDF3E7;
  --crit:#B42318; --crit-soft:#FDECEA;
  --rule:#DBE3ED; --hair:#E9EEF5;
  --code-bg:#0E1626; --code-fg:#D7E3F4; --code-acc:#7FB0E0;
  --sans:"Helvetica Neue",Helvetica,"Segoe UI",system-ui,-apple-system,Arial,sans-serif;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#080C13; --surface:#101825; --raise:#16202F;
    --ink:#E7EEF8; --muted:#9CAABD; --faint:#78889C;
    --accent:#7FB0E0; --accent-soft:#14243A;
    --ok:#5FC27E; --ok-soft:#11251A;
    --warn:#E5A24E; --warn-soft:#2A1D0E;
    --crit:#EC7C70; --crit-soft:#2B1412;
    --rule:#222E42; --hair:#1A2434;
    --code-bg:#070B12; --code-fg:#CBDAEE; --code-acc:#8CBCEA;
  }
}
:root[data-theme="dark"]{
  --ground:#080C13; --surface:#101825; --raise:#16202F;
  --ink:#E7EEF8; --muted:#9CAABD; --faint:#78889C;
  --accent:#7FB0E0; --accent-soft:#14243A;
  --ok:#5FC27E; --ok-soft:#11251A;
  --warn:#E5A24E; --warn-soft:#2A1D0E;
  --crit:#EC7C70; --crit-soft:#2B1412;
  --rule:#222E42; --hair:#1A2434;
  --code-bg:#070B12; --code-fg:#CBDAEE; --code-acc:#8CBCEA;
}

*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--sans); font-size:16px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}
.num{font-variant-numeric:tabular-nums}
b{font-weight:640}

/* ---- layout: fixed ledger rail + snapping panels ---- */
.wrap{display:grid; grid-template-columns:236px minmax(0,1fr);}
.rail{
  position:sticky; top:0; height:100vh; overflow-y:auto;
  border-right:1px solid var(--rule); background:var(--surface);
  padding:24px 0 32px; font-size:12px;
}
.railtitle{
  margin:0 20px 18px; font-family:var(--mono); font-size:11px;
  letter-spacing:.09em; text-transform:uppercase; color:var(--accent); line-height:1.7;
}
.railtitle span{color:var(--faint)}
.rail ol{list-style:none; margin:0; padding:0}
.rail a{
  display:grid; grid-template-columns:30px 1fr; gap:8px; align-items:baseline;
  padding:6px 20px; color:var(--muted); text-decoration:none;
  border-left:2px solid transparent;
}
.rail a:hover{background:var(--raise); color:var(--ink)}
.rail a:focus-visible{outline:2px solid var(--accent); outline-offset:-2px}
.rail .rn{font-family:var(--mono); font-size:10.5px; color:var(--faint)}
.rail li.on a{border-left-color:var(--accent); color:var(--ink); background:var(--accent-soft)}
.rail li.on .rn{color:var(--accent)}

main{scroll-snap-type:y proximity}
.slide{
  scroll-snap-align:start; min-height:100vh; padding:56px 48px 40px;
  border-bottom:1px solid var(--hair); position:relative;
  display:flex; flex-direction:column; justify-content:center;
}
.inner{width:100%; max-width:1180px; margin:0 auto}
.pnum{position:absolute; right:26px; bottom:18px; font-family:var(--mono);
      font-size:10.5px; color:var(--faint); letter-spacing:.05em}

/* ---- headings ---- */
.shead{margin-bottom:26px; padding-bottom:14px; border-bottom:2px solid var(--accent)}
.kicker{margin:0 0 6px; font-family:var(--mono); font-size:11px; letter-spacing:.12em;
        text-transform:uppercase; color:var(--accent)}
h2{margin:0; font-size:clamp(24px,2.5vw,34px); line-height:1.15; letter-spacing:-.02em;
   font-weight:680; text-wrap:balance}
h3{margin:0 0 12px; font-size:14px; letter-spacing:.01em; font-weight:660}

/* ---- title slide ---- */
.slide-title{background:var(--surface)}
.hero{max-width:1000px}
.eyebrow{margin:0 0 26px; font-family:var(--mono); font-size:11px; letter-spacing:.14em;
         text-transform:uppercase; color:var(--accent)}
h1{margin:0 0 22px; font-size:clamp(34px,5vw,62px); line-height:1.04;
   letter-spacing:-.035em; font-weight:700; text-wrap:balance}
.sub{margin:0 0 8px; font-size:clamp(16px,1.6vw,21px); color:var(--muted)}
.meta{margin:0 0 34px; font-family:var(--mono); font-size:12px; color:var(--faint);
      line-height:1.9}
.topstats{display:flex; flex-wrap:wrap; gap:0; margin:0 0 34px; padding:18px 0;
          border-top:1px solid var(--rule); border-bottom:1px solid var(--rule)}
.topstats div{padding-right:44px; margin-right:44px; border-right:1px solid var(--hair)}
.topstats div:last-child{border-right:0}
.topstats dt{margin:0 0 4px; font-family:var(--mono); font-size:10px; letter-spacing:.1em;
             text-transform:uppercase; color:var(--faint)}
.topstats dd{margin:0; font-size:26px; font-weight:680; letter-spacing:-.02em;
             color:var(--accent)}
.foot{margin:0; font-family:var(--mono); font-size:11px; color:var(--faint)}

/* ---- prose ---- */
.intro{margin:0 0 18px; max-width:78ch; color:var(--muted); font-size:14.5px}
.blist{list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:11px}
.blist li{position:relative; padding-left:18px; font-size:14px; color:var(--muted);
          max-width:72ch}
.blist li::before{content:""; position:absolute; left:0; top:.55em; width:7px; height:2px;
                  background:var(--accent)}
.blist li b{color:var(--ink)}
.blist.lead li{font-size:15.5px; gap:14px}
.note{margin:22px 0 0; padding-top:12px; border-top:1px solid var(--rule);
      font-size:12.5px; color:var(--faint); max-width:100ch}

/* ---- columns ---- */
.two{display:grid; grid-template-columns:1fr 1fr; gap:28px; align-items:start}
.two.wide-left{grid-template-columns:1.35fr 1fr}
.three{display:grid; grid-template-columns:repeat(3,1fr); gap:20px; align-items:start}
@media (max-width:1040px){.two,.two.wide-left,.three{grid-template-columns:1fr}}

.panel{background:var(--surface); border:1px solid var(--rule); border-radius:6px;
       padding:20px 22px}
.panel h3{padding-bottom:10px; border-bottom:1px solid var(--hair); color:var(--accent)}
.panel-alt h3{color:var(--ink)}
.mark-ok h3{color:var(--ok)} .mark-warn h3{color:var(--warn)}
.mark-neutral h3{color:var(--muted)}

/* ---- table: ledger ruling, no zebra ---- */
.tablewrap{overflow-x:auto; border:1px solid var(--rule); border-radius:6px;
           background:var(--surface)}
table{border-collapse:collapse; width:100%; font-size:13px; min-width:640px}
th{text-align:left; padding:11px 14px; font-family:var(--mono); font-size:10.5px;
   letter-spacing:.09em; text-transform:uppercase; color:var(--faint);
   border-bottom:1px solid var(--rule); white-space:nowrap; font-weight:600}
td{padding:9px 14px; border-bottom:1px solid var(--hair); color:var(--muted);
   vertical-align:top}
tbody tr:last-child td{border-bottom:0}
td.k{font-family:var(--mono); font-size:12px; color:var(--ink)}
td.num{font-family:var(--mono); text-align:right; font-variant-numeric:tabular-nums;
       color:var(--ink); white-space:nowrap}
.chip{display:inline-block; padding:2px 8px; border-radius:3px; font-family:var(--mono);
      font-size:10px; letter-spacing:.07em; text-transform:uppercase; white-space:nowrap}
.chip-ok{background:var(--ok-soft); color:var(--ok)}
.chip-warn{background:var(--warn-soft); color:var(--warn)}
.chip-crit{background:var(--crit-soft); color:var(--crit)}
.chip-neutral{background:var(--raise); color:var(--muted)}

/* ---- code ---- */
.codewrap{overflow-x:auto; border-radius:6px; background:var(--code-bg)}
.code{margin:0; padding:18px 20px; font-family:var(--mono); font-size:12.5px;
      line-height:1.62; color:var(--code-fg); white-space:pre}
.code span{display:block}
.code .c-acc{color:var(--code-acc)}

/* ---- stats ---- */
.stats{display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:22px}
@media (max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{background:var(--surface); border:1px solid var(--rule); border-left:3px solid var(--accent);
      border-radius:5px; padding:14px 16px}
.stat-ok{border-left-color:var(--ok)}
.sv{margin:0 0 4px; font-size:26px; font-weight:690; letter-spacing:-.02em; color:var(--accent)}
.stat-ok .sv{color:var(--ok)}
.sl{margin:0 0 6px; font-size:12.5px; font-weight:640; color:var(--ink)}
.sn{margin:0; font-size:11.5px; color:var(--faint); line-height:1.45}

/* ---- diagram ---- */
.fig{margin:0}
.fig figcaption{margin-top:14px; padding-top:12px; border-top:1px solid var(--rule);
                font-size:12.5px; color:var(--faint); max-width:100ch}
.dg{width:100%; height:auto; display:block}
.dg rect{stroke-width:1.2}
.n-core{fill:var(--raise); stroke:var(--accent)}
.n-surface{fill:var(--surface); stroke:var(--accent)}
.n-seal{fill:var(--accent); stroke:var(--accent)}
.n-llm{fill:var(--warn-soft); stroke:var(--warn)}
.n-data{fill:var(--accent-soft); stroke:var(--muted)}
.n-out{fill:var(--ok-soft); stroke:var(--ok)}
rect.n-group{fill:none; stroke:var(--rule); stroke-dasharray:5 4}
.nlabel{font-family:var(--sans); font-size:12.5px; font-weight:670; fill:var(--ink)}
.nsub{font-family:var(--sans); font-size:10px; fill:var(--muted)}
.n-seal-t{fill:var(--surface)}
text.n-seal-t.nsub{fill:var(--accent-soft)}
.n-llm-t{fill:var(--warn)}
text.n-llm-t.nsub{fill:var(--muted)}
.n-out-t{fill:var(--ok)}
text.n-out-t.nsub{fill:var(--muted)}
.glabel{font-family:var(--mono); font-size:10px; letter-spacing:.09em; fill:var(--faint)}
.edge{fill:none; stroke:var(--accent); stroke-width:1.4}
.edge.dashed{stroke:var(--warn); stroke-dasharray:5 4}
.elabel{font-family:var(--mono); font-size:9.5px; fill:var(--accent)}
.barrier{stroke:var(--warn); stroke-width:2}
.barrier-t{font-family:var(--mono); font-size:9.5px; fill:var(--warn); font-weight:600}
.vbarrier{stroke:var(--crit); stroke-width:2; stroke-dasharray:6 5}
.vbarrier-t{font-family:var(--mono); font-size:9px; fill:var(--crit); font-weight:600}
.guards{display:flex; gap:14px; align-items:baseline; margin-top:14px; flex-wrap:wrap}
.guardh{margin:0; font-family:var(--mono); font-size:9.5px; letter-spacing:.11em;
        text-transform:uppercase; color:var(--faint); white-space:nowrap}
.guards ul{list-style:none; display:flex; flex-wrap:wrap; gap:8px; margin:0; padding:0}
.guards li{font-family:var(--mono); font-size:10.5px; color:var(--ink);
           background:var(--raise); border:1px solid var(--rule); border-radius:3px;
           padding:3px 8px}

/* ---- screenshot ---- */
.shot{margin:0; border:1px solid var(--rule); border-radius:6px; overflow:hidden;
      background:var(--surface)}
.shot img{display:block; width:100%; height:auto; max-height:64vh; object-fit:contain}

/* ---- eval slide ---- */
.headline{display:grid; grid-template-columns:1.7fr 1fr; gap:24px; align-items:center;
          background:var(--surface); border:1px solid var(--rule);
          border-left:4px solid var(--warn); border-radius:6px; padding:18px 22px;
          margin-bottom:22px}
@media (max-width:1040px){.headline{grid-template-columns:1fr}}
.hl{margin:0 0 4px; font-size:clamp(18px,2vw,24px); font-weight:680; letter-spacing:-.02em}
.hlsub{margin:0; font-family:var(--mono); font-size:12px; color:var(--muted)}
.hlclaim{margin:0; font-size:14px; font-weight:640; color:var(--warn)}
.evalside{display:flex; flex-direction:column; gap:16px}
blockquote{margin:0; background:var(--code-bg); border-radius:6px; padding:18px 20px}
blockquote p{margin:0 0 10px; font-family:var(--serif); font-style:italic;
             font-size:16px; line-height:1.45; color:var(--code-fg)}
blockquote cite{font-family:var(--mono); font-size:10.5px; font-style:normal;
                color:var(--code-acc)}
.corollary{margin:0; background:var(--warn-soft); border-radius:6px; padding:14px 16px;
           font-size:12.5px; color:var(--warn); line-height:1.5}
.tax{display:grid; grid-template-columns:repeat(5,1fr); gap:8px; margin:0}
.taxh{grid-column:1/-1; margin:0; font-family:var(--mono); font-size:9.5px;
      letter-spacing:.1em; text-transform:uppercase; color:var(--faint)}
.tax div{background:var(--surface); border:1px solid var(--rule); border-radius:4px;
         padding:8px 4px; text-align:center}
.tax dt{font-size:17px; font-weight:680; color:var(--accent)}
.tax dd{margin:2px 0 0; font-size:9px; color:var(--faint); line-height:1.25}

.close{margin:24px 0 0; padding:26px; text-align:center; background:var(--code-bg);
       color:var(--code-fg); border-radius:6px; font-size:22px; font-weight:670;
       letter-spacing:-.01em}

a:focus-visible,section:focus-visible{outline:2px solid var(--accent); outline-offset:3px}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media (max-width:820px){
  .wrap{grid-template-columns:1fr}
  .rail{position:static; height:auto; border-right:0; border-bottom:1px solid var(--rule)}
  .rail ol{display:flex; flex-wrap:wrap}
  .rail .rt{display:none}
  .slide{padding:36px 20px 48px; min-height:auto}
}
"""

JS = """
(function(){
  var slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
  var items  = Array.prototype.slice.call(document.querySelectorAll('.rail li'));
  var cur = 0;
  if ('IntersectionObserver' in window){
    var io = new IntersectionObserver(function(es){
      es.forEach(function(en){
        if (en.isIntersecting){
          cur = slides.indexOf(en.target);
          items.forEach(function(li,i){ li.classList.toggle('on', i===cur); });
        }
      });
    }, {rootMargin:'-45% 0px -45% 0px'});
    slides.forEach(function(s){ io.observe(s); });
  }
  function go(n){
    n = Math.max(0, Math.min(slides.length-1, n));
    slides[n].scrollIntoView({behavior:'smooth', block:'start'});
  }
  document.addEventListener('keydown', function(ev){
    var t = ev.target.tagName;
    if (t === 'INPUT' || t === 'TEXTAREA') return;
    switch(ev.key){
      case 'ArrowDown': case 'ArrowRight': case 'PageDown': case ' ': case 'j':
        ev.preventDefault(); go(cur+1); break;
      case 'ArrowUp': case 'ArrowLeft': case 'PageUp': case 'k':
        ev.preventDefault(); go(cur-1); break;
      case 'Home': ev.preventDefault(); go(0); break;
      case 'End':  ev.preventDefault(); go(slides.length-1); break;
    }
  });
})();
"""


def main():
    parts = [
        "<title>EDB RIS(C) Claim Automation — Technical Deep-Dive</title>",
        f"<style>{CSS}</style>",
        '<div class="wrap">', nav(), "<main>",
    ]
    for i, s in enumerate(SLIDES, 1):
        parts.append(render_slide(i, s))
    parts += ["</main></div>", f"<script>{JS}</script>"]
    doc = "\n".join(parts)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"wrote {OUT}  ({len(SLIDES)} slides, {len(doc)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
