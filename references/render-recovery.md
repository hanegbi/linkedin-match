# Recovering a JS-rendered career page

Some career pages render their job list entirely client-side — a plain HTTP GET
(what the scraper does by default) sees an empty shell, nothing to parse. This
recovery path uses the **Playwright MCP tool** (`mcp__playwright__*`) to render
the page for real and feed the result into the same job-extraction logic the
scraper's static-HTML path already uses.

This is **not** part of the automatic scrape. It requires Claude to be present
and driving a browser interactively, so use it only when the user asks about a
specific company that's stuck at `needs_manual` — never as a bulk pass over
every unresolved company, which would mean one browser session per company and
take far too long. If the Playwright MCP server isn't set up in this session,
say so and stop; don't try to install it yourself.

## Steps

1. Check the company's cache entry has a real `careers_url` (if it's `skipped`
   with no `careers_url` at all, this won't help — see the other entry in
   [troubleshooting.md](troubleshooting.md) instead, resolution never got that far).

2. `mcp__playwright__browser_navigate` to the `careers_url`.

3. Check for a job-board iframe — many sites embed a third-party ATS widget
   rather than listing jobs directly:
   ```
   mcp__playwright__browser_evaluate
   function: () => Array.from(document.querySelectorAll('iframe')).map(f => f.src)
   ```

4. Capture the rendered HTML with `mcp__playwright__browser_evaluate`, using its
   `filename` option to save straight to a file instead of returning it as text
   (keeps it out of the conversation):
   ```
   function: () => document.documentElement.outerHTML
   filename: rendered.html
   ```
   If step 3 found a job-board iframe, `browser_navigate` directly to that
   iframe's `src` URL and repeat this capture for it too — cross-origin iframe
   content isn't reachable from the parent page's own JS context, so it needs
   its own navigation and its own capture.

5. Run the recovery script against whichever capture actually has the job data
   (usually the iframe's, when there is one):
   ```
   .venv/Scripts/python.exe "$SKILL/scripts/recover_rendered_page.py" \
     --company "<exact name from the connections CSV>" \
     --url "<the URL that HTML was rendered from>" \
     --html-file rendered.html
   ```
   It prints `{company, found, source, jobs, titles}`. `url` matters even for
   the iframe case — pass the iframe's own URL, not the parent page's, so
   relative links inside it resolve correctly. If `found` is false, try the
   other capture (main page vs. iframe) before giving up.

6. If `found` is true, the company's cache entry now has real jobs. Re-run
   `report.py prep` (and `build`, if nothing new needs scoring) to pick it up
   in the report — same as after any other cache change.

## Why this needs a script instead of just reading the MCP snapshot

The MCP tool renders the page and hands back HTML; `recover_rendered_page.py`
runs the exact same `parse_job_links()` logic (chrome/nav exclusion, count-badge
and login-link filtering, generic-CTA title backfill) the static-HTML scrape
path already uses — reusing tested code instead of Claude eyeballing raw HTML
and guessing at job titles by hand.
