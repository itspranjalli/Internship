"""Record the end-to-end product demo — docs/demo/EDB_workflow_demo_v2.webm / .mp4.

    .venv/bin/python docs/demo/record_demo.py            # record
    .venv/bin/python docs/demo/record_demo.py --check    # selectors only, no video

What it does: starts the real FastAPI app (served from webui/dist) against a
throwaway SQLite file, drives the real React UI with Playwright, and records the
browser. Nothing is mocked — the figures on screen come from the deterministic
pipeline running on sample_data/, and the assistant answers come from the real
FR-12 router. No model endpoint is attached, so the assistant runs on its
offline path; the questions chosen below are the ones it answers from the
computed claim rows, so the flow never stalls mid-take.

The overlay (step caption + synthetic-data watermark) is injected into the page
at record time only. The app itself is untouched.
"""
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))   # docs/demo -> docs -> repo root
OUT_DIR = HERE
SHOTS = os.path.join(HERE, "img", "demo")
VIDEO_TMP = os.path.join(HERE, "_video_tmp")
NAME = "EDB_workflow_demo_v2"

W, H = 1280, 900
CHECK = "--check" in sys.argv

# the assistant questions used in the take, in order. Each is answered from the
# computed rows (verified with a dry run before recording), so every reply shows
# the "figures verified" badge rather than a fallback.
QUESTIONS = [
    "how many people qualify?",
    "why is Kelvin Ong Wei Sheng excluded?",
    "what is Lim Jia Hao's claim amount?",
    "fetch the evidence for ANS-001",
]

OVERLAY_JS = r"""
(() => {
  if (document.getElementById('demo-overlay')) return;
  const style = document.createElement('style');
  style.textContent = `
    #demo-overlay { position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147483647;
      font: 600 17px/1.35 -apple-system, Segoe UI, Roboto, sans-serif;
      color: #fff; background: linear-gradient(to top, rgba(11,15,23,.94), rgba(11,15,23,.80));
      padding: 14px 26px 16px; display: flex; align-items: baseline; gap: 14px;
      transition: opacity .25s; pointer-events: none; }
    #demo-overlay .n { font-weight: 800; color: #7FB0E0; letter-spacing: .04em; font-size: 13px; }
    #demo-overlay .sub { font-weight: 400; font-size: 14px; color: #C8D6E8; }
    #demo-mark { position: fixed; bottom: 68px; right: 16px; z-index: 2147483647;
      font: 700 10px/1 -apple-system, Segoe UI, Roboto, sans-serif; letter-spacing: .09em;
      color: #8a6d1f; background: #fdf3e3; border: 1px solid #e3c987; border-radius: 999px;
      padding: 6px 11px; pointer-events: none; }
    .demo-spot { outline: 3px solid #1F4E79 !important; outline-offset: 3px;
      border-radius: 8px; box-shadow: 0 0 0 9999px rgba(11,15,23,.05); }
  `;
  document.head.appendChild(style);
  const bar = document.createElement('div');
  bar.id = 'demo-overlay';
  bar.innerHTML = '<span class="n"></span><span class="t"></span><span class="sub"></span>';
  document.body.appendChild(bar);
  const mark = document.createElement('div');
  mark.id = 'demo-mark';
  mark.textContent = 'SYNTHETIC DEMO DATA';
  document.body.appendChild(mark);

  // The evidence drawer prints the absolute path of the source workbook, which
  // is a local home directory. Keep the file name, drop the machine's path —
  // this is display-only, at record time; the app is untouched.
  const PREFIX = window.__DEMO_REPO__;
  if (PREFIX) {
    const scrub = (root) => {
      const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const hits = [];
      while (w.nextNode()) if (w.currentNode.nodeValue.includes(PREFIX)) hits.push(w.currentNode);
      hits.forEach(n => { n.nodeValue = n.nodeValue.split(PREFIX + '/').join(''); });
    };
    scrub(document.body);
    new MutationObserver(() => scrub(document.body))
      .observe(document.body, { childList: true, subtree: true, characterData: true });
  }
})();
"""


def caption(page, n, title, sub="", pos="bottom"):
    """Set the caption bar. ``pos='top'`` moves it out of the way of the chat
    input, which sits at the bottom of the viewport."""
    page.evaluate(
        """([n, t, s, pos]) => {
            const bar = document.getElementById('demo-overlay');
            if (!bar) return;
            bar.style.opacity = '1';
            const top = pos === 'top';
            bar.style.top = top ? '0' : 'auto';
            bar.style.bottom = top ? 'auto' : '0';
            bar.style.background = top
              ? 'linear-gradient(to bottom, rgba(11,15,23,.94), rgba(11,15,23,.80))'
              : 'linear-gradient(to top, rgba(11,15,23,.94), rgba(11,15,23,.80))';
            const mark = document.getElementById('demo-mark');
            if (mark) { mark.style.bottom = top ? '16px' : '68px'; }
            bar.querySelector('.n').textContent = n;
            bar.querySelector('.t').textContent = t;
            bar.querySelector('.sub').textContent = s;
        }""",
        [n, title, sub, pos],
    )


def spot(page, locator, ms=900):
    """Briefly outline an element so the viewer's eye lands where the click did."""
    try:
        locator.scroll_into_view_if_needed(timeout=3000)
        handle = locator.element_handle(timeout=3000)
        if handle is None:
            return
        page.evaluate("el => el.classList.add('demo-spot')", handle)
        page.wait_for_timeout(ms)
        page.evaluate("el => el.classList.remove('demo-spot')", handle)
    except Exception as exc:                      # a demo must never die on a highlight
        print(f"    (spot skipped: {exc.__class__.__name__})")


def free_port(preferred=8011):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def start_server(port, db_path):
    env = dict(os.environ)
    env["EDB_DB_PATH"] = db_path
    env["EDB_LLM_BASE_URL"] = ""          # offline path — no model endpoint in this take
    proc = subprocess.Popen(
        [os.path.join(REPO, ".venv", "bin", "uvicorn"), "edb_claim.api.server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    import urllib.request
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).read()
            return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise SystemExit("server did not come up")


def shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    page.screenshot(path=os.path.join(SHOTS, f"{name}.png"))


def run(page):
    step = page.get_by_role("button", name="Continue")

    # ---------------------------------------------------------------- landing
    caption(page, "1", "The starting point — HR's own documents",
            "timesheets, the researcher list, payroll; nothing new to key in")
    page.wait_for_timeout(3200)
    shot(page, "01_landing")

    checklist = page.get_by_text("Required · in order").first
    spot(page, checklist, 1400)
    page.mouse.wheel(0, 260)
    page.wait_for_timeout(1600)
    page.mouse.wheel(0, -260)
    page.wait_for_timeout(600)

    caption(page, "1", "Running it on the synthetic staff list",
            "20 people across two entities, with deliberate problems planted in")
    sample = page.get_by_text("or explore with sample data").first
    spot(page, sample, 900)
    sample.click()

    # ---------------------------------------------------------------- analysing
    caption(page, "2", "Reading the documents",
            "parse, check completeness, apply the rules, calculate, write the trail")
    page.wait_for_timeout(1200)
    shot(page, "02_analyzing")
    page.get_by_text("Document check").first.wait_for(timeout=120_000)
    page.wait_for_timeout(1500)

    # ---------------------------------------------------------------- doc check
    caption(page, "3", "What is on file, and what is missing",
            "one row per person, one column per required document")
    page.wait_for_timeout(2600)
    shot(page, "03_doccheck")
    page.mouse.wheel(0, 420)
    page.wait_for_timeout(2200)

    gate = page.get_by_text("required document(s) still missing").first
    if gate.count():
        caption(page, "3", "A missing payslip stops the claim",
                "continue is blocked until the document arrives — or HR signs off on the gap")
        spot(page, gate, 1800)
        ack = page.get_by_text("I understand — continue without these documents").first
        spot(page, ack, 700)
        ack.click()
        page.wait_for_timeout(1200)
        shot(page, "04_gate_acknowledged")

    step.scroll_into_view_if_needed()
    step.click()
    page.wait_for_timeout(1400)

    # ---------------------------------------------------------------- eligibility
    caption(page, "4", "Who can be claimed — and why not",
            "seven checks per person, each with its reason and its source cell")
    page.wait_for_timeout(2800)
    shot(page, "05_eligibility")
    page.mouse.wheel(0, 360)
    page.wait_for_timeout(1800)

    person = page.get_by_text("Kelvin Ong Wei Sheng").first
    if person.count():
        caption(page, "4", "Nobody is dropped quietly",
                "an HR job title fails the role check — reported, with the cell it came from")
        spot(page, person, 1200)
        person.click()
        page.wait_for_timeout(2600)
        shot(page, "06_exclusion_reason")
    page.mouse.wheel(0, -360)
    page.wait_for_timeout(600)

    step.scroll_into_view_if_needed()
    step.click()
    page.wait_for_timeout(1400)

    # ---------------------------------------------------------------- claim
    caption(page, "5", "The claim amount, month by month",
            "capped salary × time on the project × the support rate")
    page.wait_for_timeout(2800)
    shot(page, "07_claim")
    page.mouse.wheel(0, 400)
    page.wait_for_timeout(2400)

    lim = page.get_by_text("Lim Jia Hao").first
    if lim.count():
        caption(page, "5", "Every figure opens up",
                "each month shows the working, and each value names its cell")
        spot(page, lim, 1000)
        lim.click()
        page.wait_for_timeout(3000)
        shot(page, "08_calc_detail")

        # the audit question — "where did this number come from?" — one click deep
        payslip = page.get_by_role("button", name="payslip").first
        if payslip.count():
            caption(page, "5", "From a figure to the cell it came from",
                    "the same trail the auditor samples, opened from the claim itself")
            spot(page, payslip, 900)
            payslip.click()
            page.wait_for_timeout(4000)
            shot(page, "08b_evidence_drawer")
            page.keyboard.press("Escape")
            close = page.locator("div.fixed.inset-0 button").first
            if close.count():
                close.click()
            page.wait_for_timeout(1200)
    page.mouse.wheel(0, 500)
    page.wait_for_timeout(2200)
    shot(page, "09_variance")

    step.scroll_into_view_if_needed()
    step.click()
    page.wait_for_timeout(1400)

    # ---------------------------------------------------------------- grant
    caption(page, "6", "Where the claim sits against the grant",
            "the ceiling, the disbursement gate and the reporting dates")
    page.wait_for_timeout(3000)
    shot(page, "10_grant")
    page.mouse.wheel(0, 380)
    page.wait_for_timeout(2000)

    step.scroll_into_view_if_needed()
    step.click()
    page.wait_for_timeout(1600)

    # ---------------------------------------------------------------- pack
    caption(page, "7", "The submission pack",
            "the filled EDB template, the auditor's evidence pack, HR's list of things to fix")
    page.wait_for_timeout(3400)
    shot(page, "11_pack")

    # ---------------------------------------------------------------- assistant
    caption(page, "8", "Asking the claim questions, in plain English",
            "figures come from the computed rows — the assistant never invents one",
            pos="top")
    ask = page.get_by_role("button", name="Ask")
    spot(page, ask, 900)
    ask.click()
    page.wait_for_timeout(1500)

    box = page.get_by_placeholder("Ask about the claim or a person…")
    for i, q in enumerate(QUESTIONS, 1):
        box.click()
        box.type(q, delay=38)
        page.wait_for_timeout(400)
        box.press("Enter")
        page.wait_for_timeout(4200)
        shot(page, f"12_chat_{i}")

    caption(page, "8", "Every answer is checked before it is shown",
            "✓ figures verified — and any doubt is shown with a plain reason", pos="top")
    page.wait_for_timeout(2600)

    # the last answer lists its sources; each one opens the cell behind it
    cite = page.locator("button").filter(has_text=".xlsx ·").first
    if cite.count():
        caption(page, "9", "Answers cite their sources",
                "\"fetch the evidence\" returns the documents and cells HR can hand over",
                pos="top")
        spot(page, cite, 1100)
        cite.click()
        page.wait_for_timeout(4000)
        shot(page, "13_chat_evidence")
        close = page.locator("div.fixed.inset-0 button").first
        if close.count():
            close.click()                 # the drawer closes on its X, not on Escape
        page.wait_for_timeout(1200)

    caption(page, "", "Upload to audit-ready submission — synthetic data, entirely on this machine",
            "", pos="top")
    page.wait_for_timeout(3200)
    shot(page, "14_close")


def main():
    from playwright.sync_api import sync_playwright

    port = free_port()
    db = os.path.join(VIDEO_TMP, "demo.db")
    shutil.rmtree(VIDEO_TMP, ignore_errors=True)
    os.makedirs(VIDEO_TMP, exist_ok=True)
    server = start_server(port, db)
    print(f"server up on :{port}")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            ctx_args = dict(viewport={"width": W, "height": H},
                            device_scale_factor=1, reduced_motion="no-preference")
            if not CHECK:
                ctx_args.update(record_video_dir=VIDEO_TMP,
                                record_video_size={"width": W, "height": H})
            ctx = browser.new_context(**ctx_args)
            ctx.add_init_script(f"window.__DEMO_REPO__ = {REPO!r};")
            ctx.add_init_script(OVERLAY_JS)          # survives any re-render
            page = ctx.new_page()
            page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
            page.evaluate(f"window.__DEMO_REPO__ = {REPO!r};")
            page.evaluate(OVERLAY_JS)
            page.wait_for_timeout(1200)

            run(page)

            video = page.video
            ctx.close()                              # flushes the video file
            browser.close()

            if CHECK:
                print(f"\ncheck run complete — screenshots in {SHOTS}")
                return
            src = video.path()
            webm = os.path.join(OUT_DIR, f"{NAME}.webm")
            shutil.move(src, webm)
            print(f"\nwrote {webm}")

            mp4 = os.path.join(OUT_DIR, f"{NAME}.mp4")
            # PowerPoint cannot play webm; H.264 + faststart embeds cleanly
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", webm,
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22",
                            "-movflags", "+faststart", mp4], check=True)
            print(f"wrote {mp4}")
    finally:
        server.send_signal(signal.SIGINT)
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(VIDEO_TMP, ignore_errors=True)


if __name__ == "__main__":
    main()
