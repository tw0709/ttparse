import requests
import urllib
import urllib.parse
import re
import json
import base64
def decode_st_scripts(html):
    try:
        blocks = re.findall(
            r'\[\[\s*0\s*,\s*"([0-9A-Fa-f]+)"\s*\]\]\s*,\s*(\d+)\s*\)',
            html
        )
        if not blocks:
            return None
        decoded = []
        for data, key in blocks:
            key = int(key)
            decoded.append("".join(
                chr(int(data[i:i+4], 16) ^ ((key + (i//4)*13) & 255))
                for i in range(0, len(data), 4)
            ))
        return html + "\n" + "\n".join(decoded)
    except Exception:
        return None

def find_school_code(search_query):
    try:
        key_search_url = "http://comci.net:4082/st"
        key_response = requests.get(key_search_url)
        key_response.encoding = "euc-kr"
        match = re.findall(r"\./\d+\?\d+l",key_response.text)
        if not match:
            source = decode_st_scripts(key_response.text)
            if source is None:
                return None
            match = re.findall(r"\./\d+\?\d+l",source)
        if not match:
            return None
        safe_query = urllib.parse.quote(search_query.encode("cp949"))
        school_search_key = match[0].lstrip(".")
        code_search_url = (f"http://comci.net:4082"f"{school_search_key}{safe_query}")
        code_response = requests.get(code_search_url)
        code_response.encoding = "utf-8"
        if code_response.text in ["", " ", ".", "{}", "[]"]:
            return None
        editcode = code_response.text.rstrip("\x00")
        code_data = json.loads(editcode)
        return code_data["학교검색"][0][3]
    except Exception:
        return None
def find_tt_data(school_code,grd:int,cls:int,dow:int):
    """grd: 학년, cls: 반, dow: 요일(1-5)"""
    search_url = "http://comci.net:4082/st"
    response = requests.get(search_url)
    response.encoding="euc-kr"
    source = response.text
    keymatch = re.findall(r"\./\d+\?\d+l",source)

    if not keymatch:
        source = decode_st_scripts(source)
        if source is None:
            return None
        keymatch = re.findall(r"\./\d+\?\d+l",source)
    if not keymatch:
        return None
    key=keymatch[0].lstrip(".").split("?")[0] #학교 찾기용 코드
    codematch = re.findall(r"'(\d+)_',",source)
    if not codematch:
        return None
    code = codematch[0]
    base64_key=base64.b64encode(f"{code}_{school_code}_0_1".encode("utf-8"))
    tt_code = re.findall(r"일일자료\s*=\s*Q자료\(자료\.자료(\d+)",source)
    if not tt_code:
        return None
    tt_code = tt_code[0]
    sbj_code = re.findall(r"과목명\s*=\s*Q과목명\(자료\.자료(\d+)",source)
    if not sbj_code:
        return None
    sbj_code = sbj_code[0]
    tt_url = f"http://comci.net:4082{key}?{str(base64_key).lstrip("b'").rstrip("'")}"
    tt_response = requests.get(tt_url)
    tt_response.encoding="utf-8"
    if tt_response.text in [None, "", " ", ".", "{}", "[]"]:
        return None
    edit_tt=tt_response.text.rstrip("\x00")
    tt_data=json.loads(edit_tt)
    if len(tt_data[f"자료{tt_code}"][grd][cls][dow]) <= 1:
        return "시간표 데이터 비었거나 없음"
    tt_editdata=tt_data[f"자료{tt_code}"][grd][cls][dow][1:]
    tt_finaldata=[]
    for i in range(len(tt_editdata)):
        if isinstance(tt_editdata[i],int):
            if len(str(tt_editdata[i])) % 4 == 0 and tt_editdata[i] != 0:
                tt_finaldata.append(f"{i+1}교시: "+tt_data[f"자료{sbj_code}"][int(str(tt_editdata[i])[:2][::-1])])
            elif tt_editdata[i] != 0:
                tt_finaldata.append(f"{i+1}교시: "+tt_data[f"자료{sbj_code}"][int(str(tt_editdata[i])[:2])])
                
            else: pass
        else:
            tt_int=int(tt_editdata[i].lstrip(">"))
            if len(str(tt_int)) % 4 == 0 and tt_int != 0:
                tt_finaldata.append(f"{i+1}교시: "+tt_data[f"자료{sbj_code}"][int(str(tt_int)[:2][::-1])])
            elif tt_int != 0:
                tt_finaldata.append(f"{i+1}교시: "+tt_data[f"자료{sbj_code}"][int(str(tt_int)[:2])])
            else: pass
    return tt_finaldata
