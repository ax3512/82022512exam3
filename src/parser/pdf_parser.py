"""PdfParser — PDF를 파트별 섹션 단위로 분리한다.

V2: 새 IA PDF 포맷 지원 (멀티 파트: 계약/기기/BILL/INV/DT플랫폼/고객청구)
- 파트 태그 기반 분리
- 지정 파트(기본 BILL)만 추출
- 섹션 번호 태그 기반 분할 (1.ISSUE / 2.사용자관점 / 3.개발자관점)
- 4.매뉴얼, 5.Risk, 6.체크리스트는 스킵
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from src.parser.docx_parser import Section, ParseResult


# ── 상수/패턴 ────────────────────────────────────────────────────

_DR_RE = re.compile(r"DR-\d{4}-\d{4,6}")
_SYS_RE = re.compile(r"IA-([A-Z_]+?)(\d{6})-")

# 알려진 파트명
_KNOWN_PARTS = ["계약", "기기", "BILL", "INV", "DT플랫폼", "고객/청구", "CRM", "ORDER"]

# 스킵할 섹션 번호 (매뉴얼, Risk, 체크리스트, 케이토피아)
_SKIP_SECTIONS = {"4", "5", "6"}
_SKIP_KEYWORDS = ["Risk", "메뉴얼", "Check List", "체크리스트", "케이토피아"]

# 섹션 유형 매핑
SECTION_TYPE_MAP = {
    "issue": "이슈사항",
    "이슈 사항": "이슈사항",
    "이슈사항": "이슈사항",
    "요구사항": "요구사항",
    "과제 분석": "과제분석",
    "과제분석": "과제분석",
    "구현 방안": "구현방안",
    "구현방안": "구현방안",
    "검증 방안": "검증방안",
    "검증방안": "검증방안",
    "테스트방법": "검증방안",
    "테스트케이스": "검증방안",
    "사용자 관점": "과제분석",
    "사용자관점": "과제분석",
    "업무 규칙": "과제분석",
    "업무규칙": "과제분석",
    "개발자 관점": "구현방안",
    "개발자관점": "구현방안",
    "db object": "DB참조",
    "기준정보": "DB참조",
    "참조 레퍼런스": "DB참조",
}


def _detect_section_type(heading_path: str) -> str:
    """heading_path에서 section_type 추론. 하위 헤딩(마지막)을 우선 체크."""
    # "2. 사용자 관점 > 2-1-1-3 구현 방안" → 마지막 "구현 방안"을 먼저 체크
    parts = heading_path.split(">")
    # 역순으로 체크 (하위 → 상위)
    for part in reversed(parts):
        lower = part.strip().lower()
        for keyword, stype in SECTION_TYPE_MAP.items():
            if keyword.lower() in lower:
                return stype
    return "default"


def _extract_dr_from_filename(file_path: Path) -> dict[str, str]:
    fname = file_path.name
    info: dict[str, str] = {"dr_number": "", "system": "", "target_year_month": "", "part": "", "file_name": fname}

    dr_match = _DR_RE.search(fname)
    if dr_match:
        info["dr_number"] = dr_match.group()

    sys_match = _SYS_RE.search(fname)
    if sys_match:
        info["system"] = sys_match.group(1)
        info["target_year_month"] = sys_match.group(2)
        info["part"] = sys_match.group(1).split('_')[0]

    return info


def _extract_tables_from_page(page: fitz.Page) -> list[str]:
    tables_md: list[str] = []
    try:
        tabs = page.find_tables()
        for tab in tabs:
            data = tab.extract()
            if not data:
                continue
            rows: list[str] = []
            for row in data:
                cells = [str(c).strip().replace("\n", " ") if c else "" for c in row]
                rows.append("| " + " | ".join(cells) + " |")
            if len(rows) >= 2:
                col_count = len(data[0]) if data[0] else 1
                header_sep = "| " + " | ".join(["---"] * col_count) + " |"
                rows.insert(1, header_sep)
            tables_md.append("\n".join(rows))
    except AttributeError:
        pass
    return tables_md


# ── 파트 경계 감지 ────────────────────────────────────────────────

def _find_part_boundaries(all_lines: list[str]) -> list[dict]:
    """텍스트에서 파트 태그 + 섹션 번호 경계를 찾는다.

    Returns: [{"part": "BILL", "section_num": "2", "section_title": "사용자 관점", "line_idx": 123}, ...]
    """
    boundaries = []

    for i, line in enumerate(all_lines):
        stripped = line.strip()
        if stripped not in _KNOWN_PARTS:
            continue

        # 다음 비어있지 않은 라인에서 섹션 번호 확인
        next_num = ""
        next_title = ""
        for j in range(i + 1, min(i + 5, len(all_lines))):
            next_stripped = all_lines[j].strip()
            if not next_stripped:
                continue
            # "1" or "1." or "2" or "2." 등
            num_match = re.match(r'^(\d+)\.?\s*$', next_stripped)
            if num_match:
                next_num = num_match.group(1)
                # 그 다음 라인에서 제목 찾기
                for k in range(j + 1, min(j + 3, len(all_lines))):
                    t = all_lines[k].strip()
                    if t:
                        next_title = t
                        break
                break
            # "1. ISSUE" or "2.  사용자 관점" 같은 한 줄 형태
            num_match2 = re.match(r'^(\d+)\.\s+(.+)$', next_stripped)
            if num_match2:
                next_num = num_match2.group(1)
                next_title = num_match2.group(2).strip()
                break
            break

        if next_num:
            boundaries.append({
                "part": stripped,
                "section_num": next_num,
                "section_title": next_title,
                "line_idx": i,
            })

    return boundaries


def _should_skip_section(section_num: str, section_title: str) -> bool:
    """매뉴얼/Risk/체크리스트 등 스킵 대상인지 판단."""
    if section_num in _SKIP_SECTIONS:
        return True
    for kw in _SKIP_KEYWORDS:
        if kw.lower() in section_title.lower():
            return True
    return False


# ── 메인 파서 ─────────────────────────────────────────────────────

def parse_pdf(file_path: str | Path, target_part: str = "") -> ParseResult:
    """PDF 파일을 파싱하여 메타정보 + 섹션 리스트를 반환한다.

    Args:
        target_part: 추출할 파트명 (빈값이면 파일명에서 추출, 예: 'BILL')
    """
    file_path = Path(file_path)
    doc = fitz.open(str(file_path))

    # ── 1) 메타 정보 ──
    meta_info = _extract_dr_from_filename(file_path)
    dr_number = meta_info["dr_number"]
    if not target_part:
        target_part = meta_info.get("part", "")

    meta: dict[str, Any] = {
        "dr_number": dr_number,
        "title": "",
        "system": meta_info["system"],
        "target_year_month": meta_info["target_year_month"],
        "part": target_part,
        "doc_version": "",
        "file_name": meta_info["file_name"],
        "file_path": str(file_path),
        "page_count": len(doc),
    }

    # ── 2) 전체 텍스트 + 테이블 추출 ──
    all_lines: list[str] = []
    all_tables: list[str] = []

    for page in doc:
        text = page.get_text("text")
        if text:
            all_lines.extend(text.split("\n"))
        tables_md = _extract_tables_from_page(page)
        all_tables.extend(tables_md)

    doc.close()

    # DR번호 보완
    if not dr_number:
        for line in all_lines[:50]:
            dr_match = _DR_RE.search(line)
            if dr_match:
                dr_number = dr_match.group()
                meta["dr_number"] = dr_number
                break

    # 제목 추출: "[DR-XXXX-XXXXX] 제목" 패턴
    for line in all_lines[:30]:
        stripped = line.strip()
        title_match = re.match(r'\[DR-\d{4}-\d{4,6}\]\s*(.+)', stripped)
        if title_match:
            meta["title"] = title_match.group(1).strip()
            break

    if not meta["title"]:
        # fallback: 파일명에서 DR번호 뒤의 텍스트
        fname = meta_info["file_name"]
        dr_m = _DR_RE.search(fname)
        if dr_m:
            after_dr = fname[dr_m.end():].strip()
            after_dr = re.sub(r'\s*(\(\d+\))?\s*\.pdf$', '', after_dr, flags=re.IGNORECASE).strip()
            if after_dr:
                meta["title"] = after_dr

    # ── 3) 파트 경계 감지 ──
    boundaries = _find_part_boundaries(all_lines)

    if not boundaries:
        # 파트 태그가 없으면 BILL 단독 문서 — 섹션 번호로 직접 분할
        print(f"  ⚠️ 파트 태그 미감지 → {target_part or 'unknown'} 단독 문서로 처리")
        # 섹션 번호 패턴으로 boundary 생성: "1.\nISSUE" 또는 "2.\n 사용자 관점"
        for i, line in enumerate(all_lines):
            stripped = line.strip()
            num_match = re.match(r'^(\d+)\.\s*$', stripped)
            if num_match:
                next_title = ""
                for j in range(i + 1, min(i + 3, len(all_lines))):
                    t = all_lines[j].strip()
                    if t:
                        next_title = t
                        break
                boundaries.append({
                    "part": target_part,
                    "section_num": num_match.group(1),
                    "section_title": next_title,
                    "line_idx": i,
                })
        if not boundaries:
            return _parse_as_single_part(all_lines, all_tables, meta, dr_number, target_part)
        # target_part가 비어있으면 파일명에서 추출한 값 사용
        if not target_part:
            target_part = meta_info.get("part", "")
            meta["part"] = target_part
        print(f"  📋 BILL 단독 섹션 {len(boundaries)}개 감지")

    print(f"  📋 파트 경계 {len(boundaries)}개 감지:")
    for b in boundaries:
        skip = "⏭️ SKIP" if _should_skip_section(b["section_num"], b["section_title"]) else ""
        print(f"    [{b['part']}] {b['section_num']}. {b['section_title']} (line {b['line_idx']}) {skip}")

    # ── 4) target_part 섹션만 추출 ──
    sections: list[Section] = []
    section_order = 0

    # target_part에 해당하는 boundary들 필터
    target_boundaries = [b for b in boundaries if b["part"] == target_part]

    if not target_boundaries:
        print(f"  ⚠️ {target_part} 파트 없음")
        return ParseResult(meta=meta, sections=[])

    # 각 target_part boundary에서 다음 boundary까지의 텍스트 추출
    for bi, boundary in enumerate(target_boundaries):
        section_num = boundary["section_num"]
        section_title = boundary["section_title"]

        # 스킵 대상 체크
        if _should_skip_section(section_num, section_title):
            continue

        start_idx = boundary["line_idx"]

        # 끝 인덱스: 다음 파트 태그가 나오는 곳 (같은 파트의 다른 섹션 또는 다른 파트)
        end_idx = len(all_lines)
        for next_b in boundaries:
            if next_b["line_idx"] > start_idx:
                # 다음 boundary가 스킵 대상이 아닌 다른 파트거나 같은 파트의 다른 섹션
                end_idx = next_b["line_idx"]
                break

        # 텍스트 추출
        chunk_lines = all_lines[start_idx:end_idx]
        content = "\n".join(l.strip() for l in chunk_lines if l.strip()).strip()

        # 파트 태그 자체 제거 (첫 줄)
        if content.startswith(target_part):
            content = content[len(target_part):].strip()

        if len(content) < 20:
            continue

        # 3000자 초과 시 하위 헤딩으로 분할
        if len(content) > 3000:
            sub_sections = _split_large_section(content, target_part, section_num, section_title, meta, dr_number, section_order)
            sections.extend(sub_sections)
            section_order += len(sub_sections)
        else:
            heading_path = f"{section_num}. {section_title}" if section_title else f"섹션 {section_num}"
            section_id = f"{dr_number}::{meta.get('target_year_month', '')}::{target_part}::{heading_path}"

            sections.append(Section(
                section_id=section_id,
                dr_number=dr_number,
                title=meta.get("title", ""),
                heading_number=section_num,
                heading_title=section_title,
                heading_path=heading_path,
                level=1,
                section_type=_detect_section_type(heading_path),
                content=content,
                content_length=len(content),
                tables_count=0,
                order=section_order,
            ))
            section_order += 1

    print(f"  ✅ {target_part} 파트: {len(sections)}개 섹션 추출")
    return ParseResult(meta=meta, sections=sections)


def _split_large_section(content: str, part: str, section_num: str, section_title: str,
                         meta: dict, dr_number: str, start_order: int) -> list[Section]:
    """3000자 초과 섹션을 하위 헤딩 기반으로 분할."""
    # 하위 번호 패턴: "2-1", "2-1-1", "3-1" 등
    sub_heading_re = re.compile(r'^(\d+-\d+(?:-\d+)*)\s+(.+)$', re.MULTILINE)
    matches = list(sub_heading_re.finditer(content))

    if not matches:
        # 하위 헤딩 없으면 3000자 단위로 잘라서 반환
        chunks = []
        for i in range(0, len(content), 3000):
            chunk = content[i:i+3000].strip()
            if len(chunk) < 20:
                continue
            suffix = f" (part {i//3000 + 1})" if i > 0 else ""
            heading_path = f"{section_num}. {section_title}{suffix}"
            section_id = f"{dr_number}::{meta.get('target_year_month', '')}::{part}::{heading_path}"
            chunks.append(Section(
                section_id=section_id,
                dr_number=dr_number,
                title=meta.get("title", ""),
                heading_number=section_num,
                heading_title=section_title + suffix,
                heading_path=heading_path,
                level=1,
                section_type=_detect_section_type(heading_path),
                content=chunk,
                content_length=len(chunk),
                tables_count=0,
                order=start_order + len(chunks),
            ))
        return chunks

    # 하위 헤딩 기반 분할
    sections = []

    # 첫 하위 헤딩 전 내용
    before_first = content[:matches[0].start()].strip()
    if len(before_first) >= 20:
        heading_path = f"{section_num}. {section_title}"
        section_id = f"{dr_number}::{meta.get('target_year_month', '')}::{part}::{heading_path}"
        sections.append(Section(
            section_id=section_id,
            dr_number=dr_number,
            title=meta.get("title", ""),
            heading_number=section_num,
            heading_title=section_title,
            heading_path=heading_path,
            level=1,
            section_type=_detect_section_type(heading_path),
            content=before_first,
            content_length=len(before_first),
            tables_count=0,
            order=start_order + len(sections),
        ))

    # 각 하위 헤딩별
    for mi, m in enumerate(matches):
        sub_num = m.group(1)
        sub_title = m.group(2).strip()
        start = m.end()
        end = matches[mi + 1].start() if mi + 1 < len(matches) else len(content)
        sub_content = content[start:end].strip()

        if len(sub_content) < 20:
            continue

        heading_path = f"{section_num}. {section_title} > {sub_num} {sub_title}"
        section_id = f"{dr_number}::{meta.get('target_year_month', '')}::{part}::{heading_path}"

        sections.append(Section(
            section_id=section_id,
            dr_number=dr_number,
            title=meta.get("title", ""),
            heading_number=f"{section_num}.{sub_num}",
            heading_title=sub_title,
            heading_path=heading_path,
            level=2,
            section_type=_detect_section_type(heading_path),
            content=sub_content,
            content_length=len(sub_content),
            tables_count=0,
            order=start_order + len(sections),
        ))

    return sections


def _parse_as_single_part(all_lines: list[str], all_tables: list[str],
                          meta: dict, dr_number: str, part: str) -> ParseResult:
    """파트 태그가 없는 PDF — 기존 heading 기반 파싱."""
    sections: list[Section] = []
    heading_stack: list[tuple[int, str]] = []
    current_heading_number = ""
    current_heading_title = ""
    current_level = 0
    current_content_parts: list[str] = []
    current_order = 0

    _HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s+(.+)$")

    def _flush():
        nonlocal current_content_parts
        if not current_heading_title:
            return
        content = "\n".join(current_content_parts).strip()
        if not content:
            current_content_parts = []
            return

        path_parts = [h[1] for h in heading_stack]
        heading_path = " > ".join(path_parts)

        sections.append(Section(
            section_id=f"{dr_number}::{meta.get('target_year_month', '')}::{part}::{heading_path}",
            dr_number=dr_number,
            title=meta.get("title", ""),
            heading_number=current_heading_number,
            heading_title=current_heading_title,
            heading_path=heading_path,
            level=current_level,
            section_type=_detect_section_type(heading_path),
            content=content,
            content_length=len(content),
            tables_count=0,
            order=current_order,
        ))
        current_content_parts = []

    for line in all_lines:
        stripped = line.strip()
        if not stripped:
            continue

        m = _HEADING_RE.match(stripped)
        if m:
            _flush()
            number = m.group(1)
            title = m.group(2).strip()
            level = number.count(".") + 1
            current_heading_number = number
            current_heading_title = title
            current_level = level
            current_order += 1

            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
        else:
            if current_heading_title:
                current_content_parts.append(stripped)

    _flush()
    return ParseResult(meta=meta, sections=sections)
