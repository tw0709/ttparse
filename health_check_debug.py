"""Isolated diagnostics for the experimental Comcigan adapter.

Does not import or execute the original ttparse.py. Network response bodies
and relevant metadata are saved under diagnostics/ as GitHub Actions artifacts.
Run: python health_check_debug.py
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

import ttparse_debug as ttparse
# Reuse only the extractor; health_check.main() is never run on import.
from health_check import extract_network_hints

ROOT = Path('diagnostics')
RESPONSE_DIR = ROOT / 'responses'
ST_URL = ttparse.ST_URL
SCHOOL_NAME = os.getenv('TTPARSE_TEST_SCHOOL', '부원중학교')
GRADE = int(os.getenv('TTPARSE_TEST_GRADE', '1'))
CLASS_NO = int(os.getenv('TTPARSE_TEST_CLASS', '1'))
DOW = int(os.getenv('TTPARSE_TEST_DOW', '1'))
# From repository README; only a diagnostic probe if school lookup fails.
PROBE_SCHOOL_CODE = os.getenv('TTPARSE_PROBE_SCHOOL_CODE', '62491')
TIMEOUT = 20


def _decode_bytes(raw: bytes) -> tuple[str, str]:
    for codec in ('cp949', 'euc-kr', 'utf-8-sig'):
        try:
            return raw.decode(codec), codec
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace'), 'utf-8(replace)'


def _write_json(data: dict[str, Any]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'diagnostics.json').write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8',
    )


def _save_response(index: int, response: requests.Response) -> dict[str, Any]:
    RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    raw = response.content
    body, codec = _decode_bytes(raw)
    filename = f'{index:03d}'
    (RESPONSE_DIR / f'{filename}.raw').write_bytes(raw)
    (RESPONSE_DIR / f'{filename}.txt').write_text(body, encoding='utf-8')
    return {
        'url': response.url,
        'status_code': response.status_code,
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'decoded_as': codec,
        'raw_file': f'responses/{filename}.raw',
        'text_file': f'responses/{filename}.txt',
        'content_type': response.headers.get('Content-Type'),
        'body_prefix': body[:30],
    }


def _public_protocol(protocol: ttparse.Protocol) -> dict[str, Any]:
    d = dataclasses.asdict(protocol)
    d['token_present'] = bool(d.pop('token', ''))
    # Token remains only in the server HTML capture, not diagnostics.json.
    return d


def _probe_timetable(diag: dict[str, Any]) -> None:
    """Capture an independent response even if school search cannot decode.

    A probe is diagnostic, never evidence of successful timetable parsing.
    """
    if not PROBE_SCHOOL_CODE.isdecimal():
        diag['timetable_probe_note'] = 'No numeric probe school code available'
        return
    try:
        with requests.Session() as s:
            p = ttparse._load_protocol(s)
            url = ttparse._timetable_request(p, PROBE_SCHOOL_CODE)
            response = s.get(
                url,
                headers={'X-Hour-Token': p.token, 'Referer': ST_URL},
                timeout=TIMEOUT,
            )
            diag['timetable_probe'] = {
                'school_code': PROBE_SCHOOL_CODE,
                'status_code': response.status_code,
                'note': 'Diagnostic probe only; not a successful timetable parse',
            }
    except Exception as exc:
        diag['timetable_probe_error'] = f'{type(exc).__name__}: {exc}'


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    diag: dict[str, Any] = {
        'adapter': 'ttparse_debug.py',
        'original_ttparse_imported': False,
        'utc_checked_at': datetime.now(timezone.utc).isoformat(),
        'school': SCHOOL_NAME,
        'grade': GRADE,
        'class': CLASS_NO,
        'dow': DOW,
        'runtime_requests': [],
        'status': 'unknown',
    }
    original_request = requests.sessions.Session.request
    counter = 0

    def instrumented_request(self, method, url, **kwargs):
        nonlocal counter
        kwargs.setdefault('timeout', TIMEOUT)
        try:
            response = original_request(self, method, url, **kwargs)
        except Exception as exc:
            diag['runtime_requests'].append({
                'method': method,
                'url': str(url),
                'request_error': f'{type(exc).__name__}: {exc}',
            })
            raise
        counter += 1
        record = _save_response(counter, response)
        record['method'] = method
        # Do not log request headers or tokens.
        diag['runtime_requests'].append(record)
        return response

    # requests.Session.get and requests.get both invoke Session.request.
    requests.sessions.Session.request = instrumented_request
    try:
        # Capture actual server bytes, plus an easily inspected text copy.
        with requests.Session() as s:
            response = s.get(ST_URL, timeout=TIMEOUT)
            response.raise_for_status()
            (ROOT / 'st_source.raw').write_bytes(response.content)
            source, codec = _decode_bytes(response.content)
            (ROOT / 'st_source.html').write_text(source, encoding='utf-8')
            diag['st_decoded_as'] = codec
            diag['st_http_status'] = response.status_code
            diag['st_sha256'] = hashlib.sha256(response.content).hexdigest()

        diag['network_hints'] = extract_network_hints(source)
        decoded = ttparse.decode_st_scripts(source)
        (ROOT / 'st_decoded.txt').write_text(decoded, encoding='utf-8')
        diag['decoded_network_hints'] = extract_network_hints(decoded)
        proto = ttparse._parse_protocol(decoded)
        diag['current_protocol'] = _public_protocol(proto)

        # Never import ttparse.py: use the isolated debug adapter only.
        school_code = ttparse.find_school_code(SCHOOL_NAME)
        diag['school_code'] = school_code
        if school_code is None:
            diag['find_school_code_error'] = ttparse.get_last_error()
            _probe_timetable(diag)
            raise RuntimeError('find_school_code() returned None: '
                               + str(ttparse.get_last_error()))

        result = ttparse.find_tt_data(school_code, GRADE, CLASS_NO, DOW)
        if result is None:
            diag['find_tt_data_error'] = ttparse.get_last_error()
            raise RuntimeError('find_tt_data() returned None: '
                               + str(ttparse.get_last_error()))

        # An empty timetable is a NORMAL successful result.
        diag['special_empty_timetable_result'] = (
            result == ttparse.EMPTY_TIMETABLE
        )
        diag['status'] = 'ok'
        diag['result_type'] = type(result).__name__
        _write_json(diag)
        print('ttparse DEBUG health check: OK')
        return 0
    except Exception:
        details = traceback.format_exc()
        diag['status'] = 'failed'
        diag['exception'] = details
        (ROOT / 'traceback.txt').write_text(details, encoding='utf-8')
        _write_json(diag)
        print('===== TTPARSE_DEBUG_HEALTHCHECK_FAILED =====')
        print(details.rstrip())
        print('===== DEBUG_RUNTIME_REQUESTS_BEGIN =====')
        print(json.dumps(diag['runtime_requests'], ensure_ascii=False, indent=2))
        print('===== DEBUG_RUNTIME_REQUESTS_END =====')
        print('See diagnostics/ artifact for /st source and response bodies.')
        return 1
    finally:
        requests.sessions.Session.request = original_request


if __name__ == '__main__':
    raise SystemExit(main())
