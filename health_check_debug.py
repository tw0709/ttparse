"""Runs Chromium browser-based ttparse DEBUG; never imports original ttparse.py."""
import json
import os
import traceback
from pathlib import Path
from ttparse_debug import ChromiumClient, EMPTY_TIMETABLE

SCHOOL = os.environ.get("TTPARSE_TEST_SCHOOL","부원중학교")
GRADE = int(os.environ.get("TTPARSE_TEST_GRADE","1"))
CLS = int(os.environ.get("TTPARSE_TEST_CLASS","1"))
DOW = int(os.environ.get("TTPARSE_TEST_DOW","1"))
DIAG = Path(os.environ.get("TTPARSE_DIAGNOSTICS_DIR","diagnostics"))

def main():
    DIAG.mkdir(parents=True,exist_ok=True)
    try:
        with ChromiumClient(DIAG) as c:
            code = c.search_school(SCHOOL)
            result = c.timetable(code,GRADE,CLS,DOW)
            if result is None:
                raise RuntimeError("Timetable lookup returned None")
            c.diag["empty_timetable"] = result == EMPTY_TIMETABLE
            c.diag["timetable_result"] = result
        print("ttparse Chromium DEBUG health check: OK")
        return 0
    except Exception:
        trace=traceback.format_exc()
        (DIAG/"traceback.txt").write_text(trace,encoding="utf-8")
        print("===== TTPARSE_CHROMIUM_DEBUG_FAILURE =====")
        print(trace)
        p=DIAG/"diagnostics.json"
        if p.exists():
            try:
                data=json.loads(p.read_text(encoding="utf-8"))
                print("PHASES",json.dumps(data.get("phases",[]),ensure_ascii=False))
                print("NETWORK",json.dumps(data.get("network",[]),ensure_ascii=False))
                print("ALERTS",json.dumps(data.get("alerts",[]),ensure_ascii=False))
                print("JS_ERRORS",json.dumps(data.get("js_errors",[]),ensure_ascii=False))
            except Exception as e:
                print("Diagnostics summary error:",repr(e))
        return 1

if __name__=="__main__":
    raise SystemExit(main())
