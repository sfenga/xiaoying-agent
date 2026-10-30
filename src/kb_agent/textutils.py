"""文本处理工具:分句、数值提取、字符 bigram 特征。供检索与 Mock 策略共用。"""
from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional

# 按。;;!!??分句,保留结尾标点
_SENT_SPLIT = re.compile(r"(?<=[。;;!!??])")
# 数值提取:数字 + 单位(工作日/天/日/元/小时/个月/次/%)
_VALUE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(个工作日|天|日|元|小时|个月|次|%)")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_RUN = re.compile(r"[A-Za-z0-9]+")
_STRIP = re.compile(r"[\s,。;;!!??、,()()「」《》\-\u3000]+")


def split_sentences(text: str) -> List[str]:
    """把一段文本切成句子(保留结尾标点),去掉空句。"""
    parts = [p.strip() for p in _SENT_SPLIT.split(text)]
    return [p for p in parts if p]


def extract_value(sentence: str) -> Optional[str]:
    """从句子中提取第一个「数字+单位」,如 "30 天";无则返回 None。"""
    m = _VALUE_RE.search(sentence)
    if not m:
        return None
    return f"{m.group(1)} {m.group(2)}"


def tokenize(text: str) -> List[str]:
    """文本 -> 特征序列:CJK 串取字符 bigram(长度 1 时退化为 unigram),ASCII 串取小写单词。"""
    feats: List[str] = []
    cleaned = _STRIP.sub(" ", text)
    for run in _CJK_RUN.findall(cleaned):
        if len(run) == 1:
            feats.append(run)
        else:
            feats.extend(run[i : i + 2] for i in range(len(run) - 1))
    for run in _ASCII_RUN.findall(cleaned):
        feats.append(run.lower())
    return feats


def bigram_counter(text: str) -> Counter:
    return Counter(tokenize(text))


def contains_any(text: str, terms: List[str]) -> bool:
    return any(t and t in text for t in terms)


def count_distinct_terms(text: str, terms: List[str]) -> int:
    """terms 中出现在 text 里的不同词个数。"""
    return sum(1 for t in terms if t and t in text)
