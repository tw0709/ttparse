"""Chromium browser-backed DEBUG adapter. The original ttparse.py is not imported."""
from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ST_URL = "http://comci.net:4082/st"
EMPTY_TIMETABLE = "시간표 데이터 비었거나 없음"
TIMEOUT_MS = int(os.environ.get("TTPARSE_BROWSER_TIMEOUT_MS", "150000"))
NAV_TIMEOUT_MS = int(os.environ.get("TTPARSE_NAVIGATION_TIMEOUT_MS", "120000"))
_last_error = None

class ChromiumClient:
    def __init__(self, diagnostics_dir="diagnostics"):
        self.folder = Path(diagnostics_dir)
        self.started = time.monotonic()
        self.requests = {}
        self.responses = []
        self.school = None
        self.page = None
        self.pw = None
        self.browser = None
        self.context = None
        self.diag = {"engine": "chromium-playwright", "site": ST_URL,
                     "created_utc": datetime.now(timezone.utc).isoformat(),
                     "phases": [], "network": [], "alerts": [], "js_errors": []}

    def phase(self, name):
        self.diag["phases"].append({"name": name, "elapsed_ms": round(1000*(time.monotonic()-self.started))})

    def on_request(self, request):
        self.requests[request] = (time.monotonic(), {"method": request.method, "url": request.url, "type": request.resource_type})

    def on_finish(self, request, failed=False):
        entry = self.requests.pop(request, None)
        if not entry:
            return
        start, rec = entry
        rec["elapsed_ms"] = round(1000*(time.monotonic()-start))
        if failed:
            rec["failed"] = str(request.failure)[:500]
        else:
            try:
                response = request.response()
                rec["status"] = response.status if response else None
            except Exception:
                pass
        self.diag["network"].append(rec)

    def on_dialog(self, dialog):
        self.diag["alerts"].append({"type": dialog.type, "message": dialog.message[:500]})
        dialog.dismiss()

    def __enter__(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.pw = sync_playwright().start()
        try:
            kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
            path = os.environ.get("TTPARSE_CHROMIUM_EXECUTABLE")
            if path:
                kwargs["executable_path"] = path
            self.browser = self.pw.chromium.launch(**kwargs)
            self.context = self.browser.new_context(locale="ko-KR", timezone_id="Asia/Seoul",
                                                    viewport={"width": 1366, "height": 900})
            self.page = self.context.new_page()
            self.page.set_default_timeout(TIMEOUT_MS)
            self.page.set_default_navigation_timeout(NAV_TIMEOUT_MS)
            self.page.on("request", self.on_request)
            self.page.on("requestfinished", lambda r: self.on_finish(r))
            self.page.on("requestfailed", lambda r: self.on_finish(r, True))
            self.page.on("response", lambda r: self.responses.append(r) if urlsplit(r.url).hostname in ("comci.net","www.comci.net") else None)
            self.page.on("dialog", self.on_dialog)
            self.page.on("pageerror", lambda e: self.diag["js_errors"].append(str(e)[:1000]))
            self.page.on("console", lambda m: self.diag["js_errors"].append(m.text[:800]) if m.type == "error" else None)
            self.phase("navigate")
            self.page.goto(ST_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            self.page.locator("#sc").wait_for(state="attached", timeout=TIMEOUT_MS)
            self.phase("site_ready")
            return self
        except Exception:
            self.save("failed")
            self.close()
            raise

    def search_school(self, name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("School name is empty")
        self.phase("school_search")
        # Initial HTML ALREADY contains two 'tr.검색' rows (header + help).
        # Waiting for >=2 rows returns instantly, before the AJAX response.
        table = self.page.locator("#학교명단검색")
        previous_html = table.inner_html()
        self.page.locator("#sc").fill(name)
        # The page's real search handler is attached to onchange. Dispatch
        # one change, avoiding the duplicate AJAX caused by blur + click.
        self.page.locator("#sc").dispatch_event("change")

        # school_ra() / 학교명단_출력하기() replaces the table markup
        # *after* QAjaxSchool returns and the browser decodes enc5.
        # This also completes for valid zero-result searches.
        try:
            self.page.wait_for_function(
                """previous => {
                    const table = document.getElementById('학교명단검색');
                    return !!table && table.innerHTML !== previous;
                }""",
                arg=previous_html,
                timeout=min(TIMEOUT_MS, 60000),
            )
        except Exception as exc:
            self.diag["search_result_timeout"] = {
                "school": name,
                "alerts": self.diag["alerts"][-5:],
                "js_errors": self.diag["js_errors"][-5:],
                "requests": self.diag["network"][-10:],
                "table_text": table.inner_text()[:1000],
            }
            raise TimeoutError(
                "School search did not update its result table; "
                "inspect network, alerts and screenshot in diagnostics"
            ) from exc
        self.phase("school_search_rendered")
        links = self.page.locator("#학교명단검색 a[onclick^='sc_disp']")
        rows = links.evaluate_all("""els => els.map((e,i) => ({
            index:i, name:(e.textContent||'').trim(),
            onclick:e.getAttribute('onclick')||''
        }))""")
        self.diag["school_result_names"] = [r["name"] for r in rows][:25]
        normalize = lambda x: x.replace(" ", "")
        matches = [r for r in rows if normalize(r["name"]) == normalize(name)]
        if not matches:
            matches = [r for r in rows if normalize(name) in normalize(r["name"])]
        if not matches:
            raise LookupError(f"No matching school in search results: {name}")
        first = matches[0]
        m = re.fullmatch(r"\s*sc_disp\s*\(\s*(\d+)\s*\)\s*;?\s*", first["onclick"])
        if not m:
            raise ValueError("Unexpected school link onclick structure")
        self.school = {"code": int(m.group(1)), "index": first["index"], "name": first["name"]}
        self.diag["school_code"] = self.school["code"]
        self.phase("school_found")
        return self.school["code"]

    def timetable(self, code, grade, cls, dow):
        grade, cls, dow = int(grade), int(cls), int(dow)
        if grade < 1 or cls < 1 or dow not in (1,2,3,4,5) or not str(code).isdigit():
            raise ValueError("Invalid timetable parameters")
        self.phase("open_timetable")
        if self.school and str(self.school["code"]) == str(code):
            if self.page.locator("#학교찾기").is_visible():
                self.page.locator("#학교명단검색 a[onclick^='sc_disp']").nth(self.school["index"]).click()
        else:
            self.page.evaluate("""([code,cl])=>{
                localStorage.setItem('sc',code);
                localStorage.setItem('scnm','디버그 학교');
                localStorage.setItem('ba',cl);
                localStorage.removeItem('hour');
            }""", [str(code),f"{grade}-{cls}"])
            self.page.reload(wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        self.page.locator(f"#ba option[value='{grade}-{cls}']").wait_for(state="attached", timeout=TIMEOUT_MS)
        self.page.locator("#ba").select_option(f"{grade}-{cls}")
        self.page.wait_for_function("""([g,c])=>{
            const t=document.querySelector('#hour table');
            if(!t)return false;
            const row=t.querySelector('tr');
            const title=(row?row.textContent:'').replace(/\s+/g,'');
            return title.includes('제'+g+'학년'+c+'반시간표')
                && t.querySelectorAll('tr').length>=3;
        }""", arg=[grade,cls], timeout=TIMEOUT_MS)
        self.phase("timetable_rendered")
        periods = []
        period_no = 0
        for row in self.page.locator("#hour table tr").all():
            cells = row.locator("td")
            if cells.count() != 6:
                continue
            first = cells.nth(0)
            if "교시" not in (first.get_attribute("class") or "") or not re.search(r"\d", first.inner_text()):
                continue
            period_no += 1
            text = cells.nth(dow).inner_text().strip()
            subject = next((x.strip() for x in text.splitlines() if x.strip()), "")
            if subject:
                periods.append(f"{period_no}교시: {subject}")
        if not period_no:
            raise RuntimeError("Rendered timetable contains no period rows")
        self.diag["period_rows"] = period_no
        self.diag["nonempty_periods"] = len(periods)
        self.diag["grade_class_dow"] = [grade,cls,dow]
        self.phase("done")
        return periods or EMPTY_TIMETABLE

    def save(self, status):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.diag["status"] = status
        self.diag["elapsed_ms"] = round((time.monotonic()-self.started)*1000)
        if self.page and not self.page.is_closed():
            try:
                (self.folder/"page.html").write_text(self.page.content(), encoding="utf-8")
            except Exception as e:
                self.diag["page_error"] = str(e)[:500]
            try:
                self.page.screenshot(path=str(self.folder/"page.png"), full_page=True, timeout=15000)
            except Exception as e:
                self.diag["screenshot_error"] = str(e)[:500]
            folder = self.folder/"responses"
            folder.mkdir(exist_ok=True)
            for i,response in enumerate(self.responses, 1):
                try:
                    raw=response.body()
                    if len(raw)>2000000: continue
                    p=f"{i:03d}"
                    (folder/(p+".raw")).write_bytes(raw)
                    (folder/(p+".txt")).write_text(raw.decode("cp949",errors="replace"), encoding="utf-8")
                    self.diag.setdefault("responses",[]).append({
                        "url":response.url,"http_status":response.status,
                        "bytes":len(raw),"text_file":f"responses/{p}.txt"
                    })
                except Exception as e:
                    self.diag.setdefault("response_capture_errors",[]).append(str(e)[:500])
        (self.folder/"diagnostics.json").write_text(
            json.dumps(self.diag,ensure_ascii=False,indent=2),encoding="utf-8")

    def close(self):
        try:
            if self.context: self.context.close()
            if self.browser: self.browser.close()
        finally:
            if self.pw: self.pw.stop()

    def __exit__(self, exc_type, exc, tb):
        try: self.save("failed" if exc_type else "ok")
        finally: self.close()
        return False

def get_last_error():
    return _last_error

def _public_call(action):
    global _last_error
    _last_error = None
    try:
        with ChromiumClient() as client:
            return action(client)
    except Exception as e:
        _last_error = f"{type(e).__name__}: {e}"
        return None

def find_school_code(search_query):
    return _public_call(lambda c: c.search_school(search_query))

def find_tt_data(school_code, grd, cls, dow):
    return _public_call(lambda c: c.timetable(school_code,grd,cls,dow))
