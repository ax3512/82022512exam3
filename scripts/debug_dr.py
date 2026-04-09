import sys, re
sys.path.insert(0, r'C:\Users\my\ia-chatbot-v3')
from docx import Document
from docx.oxml.ns import qn

fpath = r'C:\Users\my\Downloads\IA-BILL_MOBILE202411-DR-2024-61061 펫 상조 Care 상품 개발 요청의 건 (부가서비스)(신규배치 및 연동).docx'
doc = Document(fpath)
body = doc.element.body
meta_tables = []
table_iter = iter(doc.tables)

for i, e in enumerate(body):
    tag = e.tag.split("}")[-1]
    if tag == "p":
        pPr = e.find(qn("w:pPr"))
        if pPr is not None:
            pStyle = pPr.find(qn("w:pStyle"))
            if pStyle is not None:
                val = pStyle.get(qn("w:val"), "")
                if re.match(r"Heading\s*\d", val) or val.isdigit():
                    print(f"HEADING FOUND at element {i}: style={val}")
                    break
    elif tag == "tbl":
        try:
            meta_tables.append(next(table_iter))
        except StopIteration:
            break

print(f"meta_tables count: {len(meta_tables)}")
if meta_tables:
    t0 = meta_tables[0]
    print(f"t0 rows={len(t0.rows)} cols={len(t0.rows[0].cells)}")
    print(f"t0(1,1)={t0.rows[1].cells[1].text[:80]!r}")
else:
    print("NO META TABLES - early return in extract_meta!")
