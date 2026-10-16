"""Exact in-memory BM25 over chunk text, with positive IDF and fixed tokenization."""
from collections import Counter, defaultdict
import math
import re
import unicodedata

K1 = 1.2
B = 0.75
TOKENIZER_VERSION = "nfkc-casefold-alphanumeric-v1"


def tokenize(text: str) -> list[str]:
    # Keep letters/numbers; split underscores, hyphens, and other punctuation.
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())


class BM25Index:
    def __init__(self, texts: list[str], k1: float = K1, b: float = B):
        if not math.isfinite(k1) or k1 <= 0 or not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError("BM25 requires finite k1 > 0 and 0 <= b <= 1")
        self.k1, self.b = k1, b
        self.lengths = []
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for index, text in enumerate(texts):
            terms = Counter(tokenize(text))
            self.lengths.append(sum(terms.values()))
            for term, frequency in terms.items():
                self.postings[term].append((index, frequency))
        self.count = len(texts)
        self.average_length = sum(self.lengths) / self.count if self.count else 0.0

    def scores(self, query: str) -> list[float]:
        scores = [0.0] * self.count
        if not self.average_length:
            return scores
        # Query multiplicity does not increase the weight of a repeated word.
        for term in sorted(set(tokenize(query))):
            postings = self.postings.get(term, [])
            if not postings:
                continue
            idf = math.log1p((self.count - len(postings) + 0.5) / (len(postings) + 0.5))
            for index, frequency in postings:
                normalization = self.k1 * (1 - self.b + self.b * self.lengths[index] / self.average_length)
                scores[index] += idf * frequency * (self.k1 + 1) / (frequency + normalization)
        return scores
