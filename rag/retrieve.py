"""ค้นคืน chunk ที่เกี่ยวข้องกับคำถาม (เวิร์กช็อป 2 และ 4) ทำงานในเครื่องทั้งหมด ไม่เรียก API

python -m rag.retrieve "คำถาม" -k 4 [--method tfidf|hybrid] [--include-superseded] [--json]
"""
import argparse
import json
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from rag.chunk import chunk_docs

# คำพ้องจากคำถามชุด dev ที่ tfidf พลาดอันดับ 1 เท่านั้น (ห้ามเพิ่มจากชุด test)
# Q35 "รถอีวี" / "เสียบชาร์จ" → เอกสารใช้ "รถยนต์ไฟฟ้า" / "จุดชาร์จ"
# Q31 "ลืมรหัสผ่าน" → เอกสารให้ "รีเซ็ต" ผ่าน Self-Service Password
SYNONYMS = {
    "อีวี": "รถยนต์ไฟฟ้า",
    "ev": "รถยนต์ไฟฟ้า",
    "เสียบชาร์จ": "จุดชาร์จ",
    "ลืมรหัสผ่าน": "รีเซ็ต Self-Service Password",
}

HYBRID_WEIGHT = 0.3         # สัดส่วนของ BM25 ในคะแนนรวม ที่เหลือเป็น TF-IDF (เลือกจากชุด dev: 0.2–0.4 ให้ผลเท่ากัน)
SUPERSEDED_PENALTY = 0.8    # ลดคะแนนฉบับเดิมเมื่อค้นแบบรวม superseded ให้ฉบับปัจจุบันขึ้นก่อน


def expand_query(query: str) -> str:
    extra = [v for k, v in SYNONYMS.items() if k in query.lower()]
    return " ".join([query, *extra])


def tokenize(text: str) -> list[str]:
    """ตัดคำภาษาไทยด้วย pythainlp (newmm) ตัดช่องว่างและเครื่องหมายวรรคตอนออก"""
    from pythainlp.tokenize import word_tokenize
    return [t.lower() for t in word_tokenize(text, engine="newmm") if re.search(r"\w", t)]


def normalize(scores: np.ndarray) -> np.ndarray:
    top = scores.max()
    return scores / top if top > 0 else scores


class Retriever:
    def __init__(self, chunks: list[dict] | None = None, method: str = "tfidf"):
        """method="tfidf": TF-IDF ระดับตัวอักษร (W2) · method="hybrid": วิธีที่ปรับปรุงแล้ว (W4)"""
        if method not in ("tfidf", "hybrid"):
            raise ValueError(f"method={method!r} ไม่รองรับ")
        self.chunks = chunks if chunks is not None else chunk_docs()
        self.method = method
        docs = [f"{c['title']} {c['section']} {c['text']}" for c in self.chunks]
        # ภาษาไทยไม่เว้นวรรคระหว่างคำ จึงใช้ n-gram ระดับตัวอักษรแทนการตัดคำ
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        self.matrix = self.vectorizer.fit_transform(docs)
        if method == "hybrid":
            from rank_bm25 import BM25Okapi
            self.bm25 = BM25Okapi([tokenize(d) for d in docs])

    def scores(self, query: str) -> np.ndarray:
        if self.method == "tfidf":
            return cosine_similarity(self.vectorizer.transform([query]), self.matrix)[0]
        query = expand_query(query)
        tfidf = cosine_similarity(self.vectorizer.transform([query]), self.matrix)[0]
        bm25 = self.bm25.get_scores(tokenize(query))
        combined = (1 - HYBRID_WEIGHT) * normalize(tfidf) + HYBRID_WEIGHT * normalize(bm25)
        superseded = np.array([c["status"] != "active" for c in self.chunks])
        return np.where(superseded, combined * SUPERSEDED_PENALTY, combined)

    def search(self, query: str, k: int = 4, include_superseded: bool = True) -> list[dict]:
        """คืน chunk k อันที่คะแนนสูงสุด เรียงจากมากไปน้อย แต่ละอันเพิ่มช่อง "score" """
        scores = self.scores(query)
        results = []
        for i in scores.argsort()[::-1]:
            c = self.chunks[i]
            if not include_superseded and c["status"] != "active":
                continue
            results.append({**c, "score": float(scores[i])})
            if len(results) == k:
                break
        return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=4)
    ap.add_argument("--method", default="tfidf", choices=["tfidf", "hybrid"])
    ap.add_argument("--include-superseded", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = Retriever(method=a.method).search(a.query, a.k, a.include_superseded)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
    for r in res:
        print(f"[{r['score']:.3f}] {r['chunk_id']} ({r['status']}) {r['title']} · {r['section']}")
        print("   " + r["text"].split("\n", 1)[-1].replace("\n", "\n   "))


if __name__ == "__main__":
    main()
