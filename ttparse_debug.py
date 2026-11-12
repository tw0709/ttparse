"""ttparse: Comcigan /st protocol adapter (2026-11-12 capture).

Public API is compatible with the original project's two functions.

LIMITATION: The captured /st source uses an enc5 response and calls HChange,
but does not contain HChange's implementation or any sample enc5 response.
Install a verified decoder with set_response_decoder() before making API calls
if the server responds with enc5. Unknown formats are never silently guessed.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote, urljoin

import requests

ST_URL = "http://comci.net:4082/st"
TIMEOUT_SECONDS = 20
EMPTY_TIMETABLE = "시간표 데이터 비었거나 없음"

_log = logging.getLogger(__name__)
_last_error: str | None = None
_response_decoder: Callable[[str], str | dict[str, Any]] | None = None

# This is the exact wrapper observed in the workflow's 2026-11-10 through 11-12
# /st captures. Its evaluated input is a hex-encoded XOR string. We parse the
# data, not eval the untrusted JavaScript.
_OBF_RE = re.compile(
    r'\[\[\s*0\s*,\s*["\']([0-9a-fA-F]+)["\']\s*\]\]\s*,\s*(\d+)\s*\)',
    re.S,
)


@dataclass(frozen=True)
class Protocol:
    school_endpoint: str
    timetable_endpoint: str
    school_prefix: str
    timetable_prefix: str
    token: str
    daily_field: str
    subjects_field: str
    modified_field: str | None


def get_last_error() -> str | None:
    """Return the most recent failure reason (the public API still returns None)."""
    return _last_error


def set_response_decoder(decoder: Callable[[str], str | dict[str, Any]] | None) -> None:
    """Set a VERIFIED implementation of the server's HChange/enc5 decoder.

    A decoder receives the original response (e.g. 'enc5:...') and returns
    plaintext JSON as a string or parsed dictionary. Not necessary for JSON
    responses. Do not fabricate a decoder from an unverified guess.
    """
    global _response_decoder
    _response_decoder = decoder


def _error(exc: Exception) -> None:
    global _last_error
    _last_error = f"{type(exc).__name__}: {exc}"
    _log.warning("ttparse: %s", _last_error)


def decode_st_scripts(html: str) -> str:
    """Recursively decode the observed XOR/hex blocks without executing JS.

    Returns the original HTML plus extracted scripts. Deduplicates blocks,
    processes at most 5 decoding rounds, and bounds output growth.
    """
    if not isinstance(html, str):
        raise TypeError("html must be str")
    result = html
    seen: set[tuple[str, int]] = set()
    for _ in range(5):
        new_scripts: list[str] = []
        for match in _OBF_RE.finditer(result):
            data, raw_key = match.groups()
            key = int(raw_key)
            ident = (data, key)
            if ident in seen:
                continue
            seen.add(ident)
            if len(data) % 4:
                raise ValueError("Invalid /st obfuscation block length")
            if len(data) > 4_000_000:
                raise ValueError("/st obfuscation block exceeds safety limit")
            plain = "".join(
                chr(int(data[j:j + 4], 16) ^ ((key + (j // 4) * 13) & 255))
                for j in range(0, len(data), 4)
            )
            new_scripts.append(plain)
        if not new_scripts:
            break
        result += "\n" + "\n".join(new_scripts)
        if len(result) > 5_000_000:
            raise ValueError("/st expanded source exceeds safety limit")
    return result


def _one(regex: str, text: str, purpose: str, flags: int = re.S) -> str:
    match = re.search(regex, text, flags)
    if not match:
        raise ValueError(f"/st source is missing {purpose}")
    return match.group(1)


def _parse_protocol(source: str) -> Protocol:
    # Restrict patterns to the actual AJAX helper declarations, not unrelated
    # strings elsewhere in the page.
    school = _one(
        r'(function\s+QAjaxSchool\s*\([^)]*\)\s*\{.*?)(?=function\s+QAjaxTimetable\s*\()',
        source, "QAjaxSchool()",
    )
    tt_start = re.search(r'function\s+QAjaxTimetable\s*\(', source)
    if tt_start is None:
        raise ValueError("/st source is missing QAjaxTimetable()")
    timetable = source[tt_start.start():tt_start.start() + 1600]

    school_endpoint = _one(
        r'url\s*:\s*["\'](\./\d+\?)["\']\s*\+', school,
        "school AJAX endpoint",
    )
    tt_endpoint = _one(
        r'url\s*:\s*["\'](\./\d+\?)["\']\s*\+', timetable,
        "timetable AJAX endpoint",
    )
    prefix = _one(
        r'btoa\s*\(\s*["\'](\d+l)["\']\s*\+', school,
        "school search prefix",
    )
    tt_prefix = _one(
        r'sc_data\s*\(\s*["\'](\d+_)["\']\s*,',
        source, "timetable sc prefix",
    )
    token = _one(
        r'window\.__HourRequestToken\s*=\s*["\']([^"\']+)["\']',
        source, "X-Hour-Token",
    )
    daily = _one(
        r'일일자료\s*=\s*Q자료\s*\(\s*자료\.자료(\d+)',
        source, "daily timetable field",
    )
    subjects = _one(
        r'과목명\s*=\s*Q과목명\s*\(\s*자료\.자료(\d+)',
        source, "subject name field",
    )
    mod_match = re.search(
        r"da1\s*=\s*(?:QnmsbChange\s*\(\s*)?H시간표\.자료(\d+)", source
    )
    return Protocol(
        school_endpoint=school_endpoint,
        timetable_endpoint=tt_endpoint,
        school_prefix=prefix,
        timetable_prefix=tt_prefix,
        token=token,
        daily_field="자료" + daily,
        subjects_field="자료" + subjects,
        modified_field=("자료" + mod_match.group(1)) if mod_match else None,
    )


def _decode_page_bytes(data: bytes) -> str:
    for encoding in ("cp949", "euc-kr", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _load_protocol(session: requests.Session) -> Protocol:
    response = session.get(ST_URL, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    source = decode_st_scripts(_decode_page_bytes(response.content))
    return _parse_protocol(source)


def _js_btoa_ascii(value: str) -> str:
    # Both payload templates use URL-escaped (ASCII) school names or numeric
    # codes. JavaScript btoa() is a Latin-1 function, *not* UTF-8 encode.
    return base64.b64encode(value.encode("latin-1")).decode("ascii")


def _school_request(protocol: Protocol, name: str) -> str:
    # JS: encodeURIComponent(btoa(prefix + encodeURIComponent(sc) + '_enc5'))
    # quote() unreserved-character behavior agrees for Korean names.
    js_escaped = quote(name, safe="-_.!~*'()")
    payload = protocol.school_prefix + js_escaped + "_enc5"
    encoded = quote(_js_btoa_ascii(payload), safe="-_.!~*'()")
    return urljoin(ST_URL, protocol.school_endpoint + encoded)


def _timetable_request(protocol: Protocol, code: int | str) -> str:
    # JS: btoa((sc + sc2) + '_0_1_enc5'); original page uses sc='18066_'
    payload = protocol.timetable_prefix + str(code) + "_0_1_enc5"
    encoded = _js_btoa_ascii(payload)
    return urljoin(ST_URL, protocol.timetable_endpoint + encoded)


def _request_data(session: requests.Session, url: str, token: str) -> dict[str, Any]:
    resp = session.get(
        url,
        timeout=TIMEOUT_SECONDS,
        headers={"X-Hour-Token": token, "Referer": ST_URL},
    )
    resp.raise_for_status()
    body = resp.content.rstrip(b"\x00")
    try:
        raw = body.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        raw = body.decode("cp949").strip()
    if not raw or raw in (".", "[]", "{}"):
        return {}

    if raw.startswith("enc5:"):
        if _response_decoder is None:
            raise RuntimeError(
                "Server returned enc5, but the captured /st source does not "
                "define HChange() and contains no enc5 response sample. "
                "Register a verified decoder with set_response_decoder()."
            )
        decoded = _response_decoder(raw)
    else:
        decoded = raw

    if isinstance(decoded, dict):
        return decoded
    if not isinstance(decoded, str):
        raise TypeError("Response decoder must return JSON text or dict")
    # A server may add NUL padding, but do not silently accept invalid JSON.
    data = json.loads(decoded.rstrip("\x00").strip())
    if not isinstance(data, dict):
        raise ValueError("Decoded API data must be an object")
    return data


def _school_from_search(data: dict[str, Any]) -> int | None:
    rows = data.get("학교검색")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, list) or not row:
            continue
        try:
            marker = int(row[0])
            if marker == 0:
                continue  # matches browser's 학교명단_출력하기
            pos = marker // 6347 + 2
            value = row[pos]
            # Browser uses QnmsbChange(value), absent from stored capture.
            # Accept numeric values, never guess an unknown value transform.
            code = int(value)
            if code > 0:
                return code
        except (TypeError, ValueError, IndexError):
            continue
    return None


def find_school_code(search_query: str) -> int | None:
    """Return the first matching school code, or None if unavailable.

    After failure, call get_last_error() for a diagnostic message.
    """
    global _last_error
    _last_error = None
    try:
        if not isinstance(search_query, str) or not search_query.strip():
            raise ValueError("search_query must be a nonempty string")
        with requests.Session() as session:
            p = _load_protocol(session)
            data = _request_data(session, _school_request(p, search_query), p.token)
        code = _school_from_search(data)
        if code is None:
            raise ValueError("School search returned no usable school code")
        return code
    except (requests.RequestException, ValueError, RuntimeError, TypeError) as exc:
        _error(exc)
        return None


def _subject_value(subjects: list[Any] | dict[str, Any], index: int) -> str | None:
    try:
        value = subjects[index] if isinstance(subjects, list) else subjects[str(index)]
        return str(value) if value is not None else None
    except (TypeError, IndexError, KeyError):
        return None


def _parse_timetable(data: dict[str, Any], p: Protocol, grade: int, cls: int, dow: int):
    try:
        periods = data[p.daily_field][grade][cls][dow]
        subjects = data[p.subjects_field]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Timetable/subject fields do not match current /st source") from exc
    if not isinstance(periods, list) or len(periods) <= 1:
        return EMPTY_TIMETABLE
    sep = int(data.get("분리") or 100)
    if sep <= 0:
        raise ValueError("Invalid subject delimiter")
    result: list[str] = []
    for period, encoded in enumerate(periods[1:], 1):
        if not encoded or encoded == "0":
            continue
        # Browser splitData() groups from right in blocks of 3 digits.
        digits = str(encoded).lstrip(">").strip()
        if not digits.isdecimal():
            raise ValueError(f"Unexpected period encoding at {period}")
        teacher_code = int(digits[-3:])
        subject_code = int(digits[-6:-3] or 0) + 1000 * int(digits[-9:-6] or 0)
        if not teacher_code:
            continue
        subject_name = _subject_value(subjects, subject_code % sep)
        if subject_name is None:
            raise ValueError(f"Unknown subject ID {subject_code % sep} at period {period}")
        result.append(f"{period}교시: {subject_name}")
    return result or EMPTY_TIMETABLE


def find_tt_data(school_code: int | str, grd: int, cls: int, dow: int):
    """Return ['1교시: 과목', ...], EMPTY_TIMETABLE, or None on errors."""
    global _last_error
    _last_error = None
    try:
        grd, cls, dow = int(grd), int(cls), int(dow)
        if grd < 1 or cls < 1 or not 1 <= dow <= 5:
            raise ValueError("Expected grade >= 1, class >= 1, weekday 1..5")
        if not str(school_code).isdigit():
            raise ValueError("school_code must contain digits")
        with requests.Session() as session:
            p = _load_protocol(session)
            data = _request_data(session, _timetable_request(p, school_code), p.token)
        if not data:
            return EMPTY_TIMETABLE
        return _parse_timetable(data, p, grd, cls, dow)
    except (requests.RequestException, ValueError, RuntimeError, TypeError) as exc:
        _error(exc)
        return None