# ttparse
컴시간 알리미에서 시간표 데이터를 가져옵니다.
>[!WARNING]
>사용시 LICENSE, README 등에 ttparse를 사용했다는 사실을 밝혀주세요.

>[!NOTE]
>이 모듈을 사용한 [Changeback](https://github.com/tw0709/changeback)을 확인해보세요!

## 사용법
### 1. find_school_code(검색어:str)
- 해당 검색어로 학교를 검색하고 **가장 먼저 나오는 결과값**의 학교 코드를 반환합니다.
- 만약 검색결과가 없거나 검색 도중 오류가 생기면 None이 반환됩니다.


### 2. find_tt_data(학교코드:int, 학년:int, 반:int, 요일:int)
- 시간표 데이터를 찾아 리스트로 반환합니다.
  - 형식 : ["1교시 : 과목명", "2교시 : 과목명", ...]
>[!IMPORTANT]
>단, 특정 교시가 비었을때는 건너뜁니다.
>단2, 해당 날짜 시간표가 아예 비었을때는 "시간표 데이터 비었거나 없음" 이 반환됩니다.

>[!TIP]
>요일은 월요일:1, 화요일:2 ... 의 형식입니다.
***
## 예시 코드
```python
import ttparse
print(ttparse.find_school_code("부원중학교"))
print(ttparse.find_tt_data(find_school_code("부원중학교"), 1, 1, 1))
```
결과값
```
62491
['1교시: 과학', '2교시: 국어', '3교시: 영어', '4교시: 학스', '5교시: 주제A', '6교시: 주제A']
```
