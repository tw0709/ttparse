from __future__ import annotations

import hashlib
import html
import json
import re
import traceback
from pathlib import Path
from typing import Any

import requests


ST_URL = "http://comci.net:4082/st"

SCHOOL_NAME = "부원중학교"
GRADE = 1
CLASS_NO = 1
DOW = 1

TIMEOUT_SECONDS = 20


DIAG_DIR = Path("diagnostics")
RESPONSES_DIR = DIAG_DIR / "responses"

RAW_PATH = DIAG_DIR / "st_source.raw"
TEXT_PATH = DIAG_DIR / "st_source.html"
JSON_PATH = DIAG_DIR / "diagnostics.json"
TRACEBACK_PATH = DIAG_DIR / "traceback.txt"


# http://example.com/a
# https://example.com/a
# //example.com/a
# example.com:4082/a
SITE_VALUE_PATTERN = (
    r'(?:(?:https?:)?//[^"\'\s<>]+'
    r'|(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}'
    r'(?::\d+)?(?:/[^"\'\s<>]*)?)'
)

# /abc
# ./123?456l
# ../foo
RELATIVE_VALUE_PATTERN = (
    r'(?:(?:\./|\.\./|/)[^"\'\s<>]+)'
)


# var foo = "http://..."
# foo: "/abc"
ASSIGN_RE = re.compile(
    rf'(?P<name>[$A-Za-z_][\w$]*)'
    rf'\s*(?:=|:)\s*["\']'
    rf'(?P<value>{SITE_VALUE_PATTERN}|{RELATIVE_VALUE_PATTERN})'
    rf'["\']'
)


# var servers = [
#     "http://a",
#     "http://b"
# ]
ARRAY_ASSIGN_RE = re.compile(
    r'(?P<name>[$A-Za-z_][\w$]*)'
    r'\s*(?:=|:)\s*'
    r'\[(?P<body>.*?)\]',
    re.DOTALL,
)


STRING_NETWORK_VALUE_RE = re.compile(
    rf'["\']'
    rf'(?P<value>{SITE_VALUE_PATTERN}|{RELATIVE_VALUE_PATTERN})'
    rf'["\']'
)


DIRECT_SITE_RE = re.compile(
    SITE_VALUE_PATTERN
)

DIRECT_RELATIVE_RE = re.compile(
    RELATIVE_VALUE_PATTERN
)


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """
    컴시간 응답을 사람이 읽을 수 있는 문자열로 디코딩한다.

    원본 bytes 자체는 별도로 .raw 파일에 저장되므로,
    여기서 어떤 인코딩을 쓰더라도 원본은 손실되지 않는다.
    """

    for encoding in (
        "cp949",
        "euc-kr",
        "utf-8",
    ):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            pass

    return (
        raw.decode(
            "utf-8",
            errors="replace",
        ),
        "utf-8(replace)",
    )


def clean_value(value: str) -> str:
    """
    JS/HTML 안에서 발견한 URL 비슷한 값을 정리한다.
    """

    value = html.unescape(
        value.strip()
    )

    # http:\/\/example.com 같은 JS escape 처리
    value = value.replace(
        r"\/",
        "/",
    )

    return value.rstrip(
        ");,]"
    )


def add_mapping(
    mapping: dict[str, list[str]],
    value: str,
    variable: str | None,
) -> None:

    value = clean_value(value)

    if not value:
        return

    # URL/endpoint 값을 key로 사용하므로
    # 같은 값은 자동으로 중복 제거됨.
    if value not in mapping:
        mapping[value] = []

    # 같은 URL을 여러 변수가 가리키는 경우
    # 변수 이름은 모두 보존한다.
    if (
        variable
        and variable not in mapping[value]
    ):
        mapping[value].append(
            variable
        )


def extract_network_hints(
    source: str,
) -> dict[str, Any]:
    """
    /st 원문에서 네트워크 관련 값을 최대한 수집한다.

    같은 URL/endpoint 값은 한 번만 반환하고,
    같은 값을 참조하는 변수는 variables 배열에 모두 넣는다.
    """

    sites: dict[str, list[str]] = {}
    endpoints: dict[str, list[str]] = {}

    # ------------------------------------
    # 1. 변수/객체 속성 직접 대입
    # ------------------------------------

    for match in ASSIGN_RE.finditer(
        source
    ):

        name = match.group(
            "name"
        )

        value = clean_value(
            match.group("value")
        )

        if value.startswith(
            (
                "/",
                "./",
                "../",
            )
        ):
            target = endpoints
        else:
            target = sites

        add_mapping(
            target,
            value,
            name,
        )

    # ------------------------------------
    # 2. 배열 안 URL
    # ------------------------------------

    for match in ARRAY_ASSIGN_RE.finditer(
        source
    ):

        name = match.group(
            "name"
        )

        body = match.group(
            "body"
        )

        for item in STRING_NETWORK_VALUE_RE.finditer(
            body
        ):

            value = clean_value(
                item.group("value")
            )

            if value.startswith(
                (
                    "/",
                    "./",
                    "../",
                )
            ):
                target = endpoints
            else:
                target = sites

            add_mapping(
                target,
                value,
                name,
            )

    # ------------------------------------
    # 3. 변수에 안 들어있는 URL도 수집
    # ------------------------------------

    for match in DIRECT_SITE_RE.finditer(
        source
    ):
        add_mapping(
            sites,
            match.group(0),
            None,
        )

    # ------------------------------------
    # 4. 상대 endpoint도 수집
    # ------------------------------------

    for match in DIRECT_RELATIVE_RE.finditer(
        source
    ):
        add_mapping(
            endpoints,
            match.group(0),
            None,
        )

    # ------------------------------------
    # 최종 중복 없는 목록
    # ------------------------------------

    all_unique = list(
        sites
    )

    all_unique.extend(
        value
        for value in endpoints
        if value not in sites
    )

    return {
        "sites": [
            {
                "value": value,
                "variables": variables,
            }
            for value, variables
            in sites.items()
        ],

        "relative_endpoints": [
            {
                "value": value,
                "variables": variables,
            }
            for value, variables
            in endpoints.items()
        ],

        "all_unique_network_values":
            all_unique,
    }


def write_json(
    data: dict[str, Any],
) -> None:

    JSON_PATH.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def save_response_body(
    index: int,
    url: str,
    response: requests.Response,
) -> dict[str, Any]:
    """
    ttparse가 실제 요청해서 받은 응답을 그대로 저장한다.
    """

    raw = response.content

    text, decoded_as = decode_bytes(
        raw
    )

    raw_name = (
        f"{index:03d}.raw"
    )

    text_name = (
        f"{index:03d}.txt"
    )

    raw_file = (
        RESPONSES_DIR
        / raw_name
    )

    text_file = (
        RESPONSES_DIR
        / text_name
    )

    raw_file.write_bytes(
        raw
    )

    text_file.write_text(
        text,
        encoding="utf-8",
    )

    return {
        "url": url,

        "status_code":
            response.status_code,

        "raw_file":
            f"responses/{raw_name}",

        "text_file":
            f"responses/{text_name}",

        "size_bytes":
            len(raw),

        "sha256":
            hashlib.sha256(
                raw
            ).hexdigest(),

        "decoded_as":
            decoded_as,
    }


def main() -> int:

    DIAG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    RESPONSES_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    diagnostics: dict[str, Any] = {
        "st_url": ST_URL,

        "school_name":
            SCHOOL_NAME,

        "grade":
            GRADE,

        "class":
            CLASS_NO,

        "dow":
            DOW,

        "status":
            "unknown",

        "runtime_requests": [],
    }

    source = ""

    network_hints: dict[str, Any] = {
        "sites": [],
        "relative_endpoints": [],
        "all_unique_network_values": [],
    }

    try:

        # =====================================================
        # 1. /st 원본 확보
        # =====================================================

        st_response = requests.get(
            ST_URL,
            timeout=TIMEOUT_SECONDS,
        )

        diagnostics[
            "st_http_status"
        ] = st_response.status_code

        st_response.raise_for_status()

        st_raw = st_response.content

        # 진짜 서버 응답 bytes 그대로
        RAW_PATH.write_bytes(
            st_raw
        )

        source, detected_encoding = (
            decode_bytes(
                st_raw
            )
        )

        # 분석하기 편한 UTF-8 버전
        TEXT_PATH.write_text(
            source,
            encoding="utf-8",
        )

        diagnostics[
            "st_decoded_as"
        ] = detected_encoding

        diagnostics[
            "st_size_bytes"
        ] = len(st_raw)

        diagnostics[
            "st_sha256"
        ] = hashlib.sha256(
            st_raw
        ).hexdigest()

        # =====================================================
        # 2. /st 내부 사이트/endpoint 탐색
        # =====================================================

        network_hints = (
            extract_network_hints(
                source
            )
        )

        diagnostics[
            "network_hints"
        ] = network_hints

        # =====================================================
        # 3. ttparse requests.get 가로채기
        # =====================================================
        #
        # ttparse가 실제로 어디에 요청했는지,
        # 서버가 뭘 돌려줬는지 기록한다.
        #
        # 같은 URL은 딱 한 번만 저장한다.
        # =====================================================

        real_get = requests.get

        seen_urls: set[str] = set()

        request_index = 0

        def instrumented_get(
            url,
            *args,
            **kwargs,
        ):

            nonlocal request_index

            kwargs.setdefault(
                "timeout",
                TIMEOUT_SECONDS,
            )

            url_text = str(
                url
            )

            try:

                response = real_get(
                    url,
                    *args,
                    **kwargs,
                )

            except Exception as exc:

                if url_text not in seen_urls:

                    seen_urls.add(
                        url_text
                    )

                    diagnostics[
                        "runtime_requests"
                    ].append(
                        {
                            "url":
                                url_text,

                            "request_error":
                                repr(exc),
                        }
                    )

                raise

            if url_text not in seen_urls:

                seen_urls.add(
                    url_text
                )

                request_index += 1

                response_info = (
                    save_response_body(
                        request_index,
                        url_text,
                        response,
                    )
                )

                diagnostics[
                    "runtime_requests"
                ].append(
                    response_info
                )

            return response

        # ttparse도 같은 requests 모듈을 사용하므로
        # 이것만 바꾸면 내부 요청까지 기록된다.
        requests.get = instrumented_get

        # =====================================================
        # 4. 최신 ttparse 테스트
        # =====================================================

        # import 단계 자체에서 깨지는 것도 예외 처리됨.
        import ttparse

        # Keep the original /st response unchanged while also preserving
        # the decoded script for troubleshooting future parser changes.
        # Diagnostic decoding must not cause a healthy parser to fail.
        try:
            decoded_source = ttparse.decode_st_scripts(source)
            if decoded_source is not None:
                decoded_path = DIAG_DIR / "st_decoded.txt"
                decoded_path.write_text(
                    decoded_source,
                    encoding="utf-8",
                )
                diagnostics["decoded_st_source_file"] = str(decoded_path)
            else:
                diagnostics["decoded_st_source_note"] = (
                    "No supported encoded script block found"
                )
        except Exception as exc:
            diagnostics["decoded_st_source_error"] = repr(exc)

        school_code = (
            ttparse.find_school_code(
                SCHOOL_NAME
            )
        )

        diagnostics[
            "school_code"
        ] = school_code

        if school_code is None:

            raise RuntimeError(
                "find_school_code() returned None"
            )

        result = (
            ttparse.find_tt_data(
                school_code,
                GRADE,
                CLASS_NO,
                DOW,
            )
        )

        # 사용자 지정 규칙:
        #
        # None        -> 고장
        # 예외        -> 고장
        #
        # "시간표 데이터 비었거나 없음"
        #             -> 정상
        #
        # 기타 non-None
        #             -> 정상

        if result is None:

            raise RuntimeError(
                "find_tt_data() returned None"
            )

        diagnostics[
            "status"
        ] = "ok"

        diagnostics[
            "special_empty_timetable_result"
        ] = (
            result
            == "시간표 데이터 비었거나 없음"
        )

        write_json(
            diagnostics
        )

        # 시간표 반환값 자체는 일부러 출력하지 않는다.
        print(
            "ttparse health check: OK"
        )

        return 0

    except Exception:

        tb_text = (
            traceback.format_exc()
        )

        TRACEBACK_PATH.write_text(
            tb_text,
            encoding="utf-8",
        )

        diagnostics[
            "status"
        ] = "failed"

        diagnostics[
            "exception"
        ] = tb_text

        diagnostics[
            "network_hints"
        ] = network_hints

        write_json(
            diagnostics
        )

        # =====================================================
        # GitHub Actions 로그에 사고현장 전부 출력
        # =====================================================

        print(
            "===== TTPARSE_HEALTHCHECK_FAILED ====="
        )

        print(
            tb_text.rstrip()
        )

        print(
            "===== UNIQUE_NETWORK_VALUES_BEGIN ====="
        )

        print(
            json.dumps(
                network_hints,
                ensure_ascii=False,
                indent=2,
            )
        )

        print(
            "===== UNIQUE_NETWORK_VALUES_END ====="
        )

        print(
            "===== RUNTIME_REQUESTS_BEGIN ====="
        )

        print(
            json.dumps(
                diagnostics.get(
                    "runtime_requests",
                    [],
                ),
                ensure_ascii=False,
                indent=2,
            )
        )

        print(
            "===== RUNTIME_REQUESTS_END ====="
        )

        # /st 현재 원문 전체
        print(
            "===== COMCI_ST_SOURCE_BEGIN ====="
        )

        print(
            source
        )

        print(
            "===== COMCI_ST_SOURCE_END ====="
        )

        print(
            "===== DIAGNOSTICS_JSON_BEGIN ====="
        )

        print(
            json.dumps(
                diagnostics,
                ensure_ascii=False,
                indent=2,
            )
        )

        print(
            "===== DIAGNOSTICS_JSON_END ====="
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
