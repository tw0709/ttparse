
<div align="center">

# ttparse

**컴시간 알리미 시간표를 Python으로.**

컴시간 알리미의 시간표 데이터를 조회하는 비공식 Python 모듈입니다.

[![Health Check](https://github.com/tw0709/ttparse/actions/workflows/ttparse-health-check.yml/badge.svg?branch=main)](https://github.com/tw0709/ttparse/actions/workflows/ttparse-health-check.yml)
<img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/Unofficial-64748B?style=flat-square" alt="Unofficial">

<sub>© 2026 강태웅</sub>

<sub>위 Health Check는 ttparse_debug.py 기준입니다.</sub>

</div>

---

## 소개

**ttparse**는 컴시간 알리미에서 시간표 데이터를 가져와 Python 프로그램에서 사용할 수 있도록 만든 모듈입니다.

학교 이름으로 학교 코드를 검색하고, 학년·반·요일을 지정해 시간표를 조회할 수 있습니다.

> [!TIP]
> `ttparse_debug.py`는 ChatGPT를 활용하여 유지보수하고 있습니다.
> 
> 만약 `ttparse.py`가 작동하지 않을 시, `ttparse_debug.py` 사용을 고려해보세요.

## 사용 방법

### 1. 학교 코드 검색

```python
import ttparse

code = ttparse.find_school_code("부원중학교")
print(code)
```

검색 결과가 없거나 오류가 발생하면 `None`이 반환됩니다.

### 2. 시간표 조회

```python
import ttparse

code = ttparse.find_school_code("부원중학교")

if code is not None:
    timetable = ttparse.find_tt_data(code, 1, 1, 1)
    print(timetable)
```

**매개변수**

| 매개변수 | 설명 |
|:---|:---|
| `school_code` | 학교 코드 |
| `grd` | 학년 |
| `cls` | 반 |
| `dow` | 요일 (월요일 1 ~ 금요일 5) |

**반환값**

| 반환값 | 설명 |
|:---|:---|
| `list` | 교시별 시간표 |
| `None` | 조회 실패 |
| `"시간표 데이터 비었거나 없음"` | 시간표가 비어 있음 |

> [!TIP]
> 비어 있는 교시는 결과에서 제외됩니다.
>
> 오류 상황에 따라 예외가 발생할 수도 있으므로, 실제 프로그램에서는 예외 처리를 권장합니다.

---

## 작동 상태

<div align="center">

[![ttparse Health Check](https://github.com/tw0709/ttparse/actions/workflows/ttparse-health-check.yml/badge.svg?branch=main)](https://github.com/tw0709/ttparse/actions/workflows/ttparse-health-check.yml)

**[GitHub Actions 실행 기록](https://github.com/tw0709/ttparse/actions/workflows/ttparse-health-check.yml)**

<sub>위 Health Check는 ttparse_debug.py 기준입니다.</sub>
</div>

GitHub Actions를 통해 시간표 조회 기능을 점검합니다.

상태 배지는 최근 점검 결과를 나타내며, 모든 환경에서의 정상 작동을 보장하지는 않습니다.

---

## 이용 및 책임 안내

> [!IMPORTANT]
> **ttparse는 컴시간 알리미의 공식 프로젝트가 아닙니다.**
>
> 본 프로젝트는 컴시간 알리미와 공식적인 제휴·협력 관계에 있지 않으며, 해당 서비스의 지원이나 보증을 받지 않습니다.

컴시간 알리미의 데이터, 서비스 및 관련 권리는 각 권리자에게 귀속됩니다.

사용자는 본 모듈을 이용하면서 관련 법령, 제3자의 권리 및 적용 가능한 서비스 이용약관을 준수해야 합니다.

본 모듈을 이용한 데이터의 수집·저장·재배포 등 사용자 자신의 행위에 관한 법적 책임은 관련 법령과 구체적인 사실관계에 따라 사용자에게 발생할 수 있습니다.

개발자는 관련 법령이 허용하는 범위에서 외부 서비스의 변경·장애, 데이터 오류 및 본 모듈의 이용으로 발생하는 손해에 대한 책임을 제한합니다.

---

## 저작권 및 출처 표기

본 프로젝트의 저작권 보호 대상 코드와 문서에 관한 권리는 해당 권리자에게 귀속됩니다.

ttparse를 사용하는 프로젝트를 공개할 경우 README와 프로그램 내부의 사용자가 충분히 볼 수 있는 위치에 다음 문구를 표기해 주세요.

```text
Powered by ttparse
https://github.com/tw0709/ttparse
```

---

## 관련 프로젝트

<div align="center">

### Changeback

**반의 시간표를, 바탕화면에.**

ttparse를 활용한 Windows 바탕화면 시간표 프로그램입니다.
(동일 개발자 제작)

[![Changeback](https://img.shields.io/badge/View-Changeback-2563EB?style=for-the-badge)](https://github.com/tw0709/changeback)


</div>

---

<div align="center">

**ttparse**

<sub>Copyright © 2026 강태웅. All rights reserved.</sub>

[GitHub](https://github.com/tw0709/ttparse) · [Actions](https://github.com/tw0709/ttparse/actions) · [Changeback](https://github.com/tw0709/changeback)

</div>
