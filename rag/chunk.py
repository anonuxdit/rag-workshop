"""แบ่งเอกสารเป็น chunk พร้อม metadata (เวิร์กช็อป 1)

แต่ละ chunk เป็น dict ที่มีอย่างน้อย:
chunk_id ("<doc_id>#<ลำดับ>"), doc_id, title, section, status, effective_date, text
"""
from rag.ingest import load_docs

MAX_CHARS = 600


def split_sections(body: str, default: str) -> list[tuple[str, list[str]]]:
    """แยกเนื้อหาเป็น (ชื่อหัวข้อ, บรรทัด) ตามหัวข้อ ## ข้ามบรรทัดหัวเรื่อง # และบรรทัดว่าง"""
    sections, name, lines = [], default, []
    for line in body.splitlines():
        if line.startswith("## "):
            if lines:
                sections.append((name, lines))
            name, lines = line[3:].strip(), []
        elif line.strip() and not line.startswith("# "):
            lines.append(line.strip())
    if lines:
        sections.append((name, lines))
    return sections


def pack_lines(lines: list[str], budget: int) -> list[str]:
    """รวมบรรทัดเป็นก้อนยาวไม่เกิน budget ตัดตามบรรทัด บรรทัดที่ยาวเกินถูกตัดตามจำนวนตัวอักษร"""
    pieces = []
    for line in lines:
        pieces += [line[i:i + budget] for i in range(0, len(line), budget)]
    parts, cur = [], ""
    for p in pieces:
        if cur and len(cur) + 1 + len(p) > budget:
            parts.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur:
        parts.append(cur)
    return parts


def chunk_docs(docs: list[dict] | None = None, max_chars: int = MAX_CHARS) -> list[dict]:
    if docs is None:
        docs = load_docs()
    chunks = []
    for doc in docs:
        meta = {k: v for k, v in doc.items() if k != "body"}
        n = 0
        for section, lines in split_sections(doc["body"], doc["title"]):
            # ใส่ชื่อเอกสารและหัวข้อไว้ต้น text เพื่อให้ค้นเจอด้วยคำในหัวข้อ
            header = f"{doc['title']} · {section}\n"
            for part in pack_lines(lines, max_chars - len(header)):
                n += 1
                chunks.append({**meta, "chunk_id": f"{doc['doc_id']}#{n}",
                               "section": section, "text": header + part})
    return chunks


if __name__ == "__main__":
    cs = chunk_docs()
    print(len(cs), "chunks · ยาวสุด", max(len(c["text"]) for c in cs), "ตัวอักษร")
