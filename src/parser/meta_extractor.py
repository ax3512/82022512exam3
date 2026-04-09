"""메타 테이블 파싱 — docx 상단 5개 테이블에서 문서 메타정보 추출."""
from __future__ import annotations
from typing import Any
from docx.table import Table


def _cell(table: Table, row: int, col: int) -> str:
    """안전하게 셀 텍스트 반환."""
    try:
        return table.rows[row].cells[col].text.strip()
    except (IndexError, AttributeError):
        return ""


def extract_meta(tables: list[Table], file_path: str = "") -> dict[str, Any]:
    """상단 메타 테이블 5개에서 문서 메타정보를 추출한다.

    Table 0: 문서명, 문서ID, 문서버전
    Table 1: 요청자, 요청부서, 요청일자
    Table 2: SR 일람
    Table 3: 제/개정 이력
    Table 4: 요청내용 구분, 요청 목적, 비즈니스 요구사항
    """
    meta: dict[str, Any] = {
        "dr_number": "",
        "title": "",
        "doc_version": "",
        "author": "",
        "system": "",
        "target_year_month": "",
        "requester": "",
        "requester_dept": "",
        "purpose": "",
        "business_requirement": "",
        "file_path": file_path,
    }

    import re, os

    # 파일명 fallback (테이블 없거나 내부에 DR번호 없을 때)
    def _fallback_from_filename():
        if not file_path:
            return
        fname = os.path.basename(file_path)
        meta['file_name'] = fname
        dr_m = re.search(r'DR-\d{4}-\d{4,6}', fname)
        if dr_m and not meta['dr_number']:
            meta['dr_number'] = dr_m.group()
        sys_m = re.search(r'IA-([A-Z_]+?)(\d{6})-', fname)
        if sys_m and not meta['system']:
            meta['system'] = sys_m.group(1)
            meta['target_year_month'] = sys_m.group(2)

    if len(tables) < 1:
        _fallback_from_filename()
        return meta

    # --- Table 0: 문서명, 문서ID ---
    t0 = tables[0]
    doc_id = _cell(t0, 1, 1)        # 문서ID
    meta["title"] = _cell(t0, 4, 1)  # 문서제목
    meta["doc_version"] = _cell(t0, 0, 3)  # 문서버전
    meta["author"] = _cell(t0, 1, 3)  # 작성자

    # DR번호 추출: 문서ID에서 DR-XXXX-XXXXX 패턴
    dr_match = re.search(r'DR-\d{4}-\d{4,6}', doc_id)
    if dr_match:
        meta['dr_number'] = dr_match.group()

    # 시스템/연월 추출: IA-BILL_MOBILE202510-DR-...
    sys_match = re.search(r'IA-([A-Z_]+?)(\d{6})-', doc_id)
    if sys_match:
        meta['system'] = sys_match.group(1)
        meta['target_year_month'] = sys_match.group(2)

    # 파일명에서도 추출 (파일명 년월이 문서 내부와 다르면 파일명 우선)
    _fallback_from_filename()
    # 파일명의 년월이 문서 내부와 다르면 파일명 우선 (작성자가 파일명만 변경하는 경우 대응)
    if file_path:
        fname = os.path.basename(file_path)
        fn_ym = re.search(r'IA-[A-Z_]+?(\d{6})-', fname)
        if fn_ym and meta['target_year_month'] and fn_ym.group(1) != meta['target_year_month']:
            meta['target_year_month'] = fn_ym.group(1)

    # part 추출: system (BILL_MOBILE → BILL, ORDER_MOBILE → ORDER)
    if meta.get('system'):
        meta['part'] = meta['system'].split('_')[0]
    else:
        meta['part'] = ''

    # --- Table 1: 요청자, 요청부서 ---
    if len(tables) >= 2:
        t1 = tables[1]
        meta["requester"] = _cell(t1, 0, 1)
        meta["requester_dept"] = _cell(t1, 0, 3)

    # --- Table 4: 요청 목적, 비즈니스 요구사항 ---
    if len(tables) >= 5:
        t4 = tables[4]
        meta["purpose"] = _cell(t4, 1, 1)
        meta["business_requirement"] = _cell(t4, 2, 1)

    return meta
