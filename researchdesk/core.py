"""Ingestion, deterministic matching, provenance, graphs, and reports."""

from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

INDEX_DIR = ".researchdesk"
INDEX_NAME = "index.json"
AUDIT_NAME = "rd-audit.jsonl"
SUPPORTED_SUFFIXES = {".md", ".txt"}
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into",
    "is", "it", "of", "on", "or", "the", "to", "was", "were", "with",
}
NEGATIVE_TERMS = {
    "not", "no", "never", "without", "lacks", "lack", "failed", "fail", "cannot",
    "unavailable", "unsupported", "delayed", "doesnt", "isnt", "wasnt", "wont",
}
POSITIVE_TERMS = {
    "support", "supports", "supported", "include", "includes", "included", "provide",
    "provides", "provided", "enable", "enables", "enabled", "available", "approved",
    "successful", "compliant", "opened", "launched", "meets", "passed", "reached",
    "contains", "uses", "used", "ships", "shipped",
}
ASSERTION_CUES = STOPWORDS | NEGATIVE_TERMS | POSITIVE_TERMS | {
    "only", "does", "do", "did", "has", "have", "had", "can", "could", "would",
    "should", "will", "may", "might", "must", "not", "more", "less", "very",
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _tokens(text: str) -> list[str]:
    return [item.casefold() for item in TOKEN_RE.findall(text)]


def topic_keywords(topic: str) -> list[str]:
    words = [word for word in _tokens(topic) if word not in STOPWORDS]
    return words or _tokens(topic)


def normalize_markdown(text: str) -> str:
    output: list[str] = []
    in_fence = False
    in_comment = False
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("```") or line.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("<!--"):
            in_comment = "-->" not in line
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.startswith("#"):
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
        line = line.replace("**", "").replace("__", "").replace("`", "")
        line = re.sub(r"^\s*(?:[-*+]\s+|>\s*)", "", line)
        line = " ".join(line.split())
        if line:
            output.append(line)
    joined = " ".join(output)
    return joined.strip()


def split_passages(text: str) -> list[str]:
    normalized = normalize_markdown(text)
    return [part.strip() for part in SENTENCE_RE.split(normalized) if part.strip()]


def classify_stance(text: str) -> str:
    words = set(_tokens(text))
    if words & NEGATIVE_TERMS:
        return "opposes"
    if words & POSITIVE_TERMS:
        return "supports"
    return "neutral"


def assertion_key(text: str) -> str:
    words = _tokens(text)
    kept = [word for word in words if word not in ASSERTION_CUES and not word.isdigit()]
    return " ".join(kept) or " ".join(words)


def _source_id(relative_path: str) -> str:
    digest = _sha256(relative_path.replace("\\", "/").casefold().encode("utf-8"))[:12]
    return f"src-{digest}"


def _manifest(corpus_dir: Path) -> dict:
    path = corpus_dir / "rd-manifest.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("sources", {})


def ingest_corpus(corpus_dir: str | Path) -> dict:
    root = Path(corpus_dir).resolve()
    if not root.is_dir():
        raise ValueError(f"Corpus directory does not exist: {root}")
    manifest = _manifest(root)
    file_paths = sorted(
        (p for p in root.rglob("*") if p.is_file() and p.suffix.casefold() in SUPPORTED_SUFFIXES
         and INDEX_DIR not in p.relative_to(root).parts),
        key=lambda p: p.relative_to(root).as_posix().casefold(),
    )
    documents: list[dict] = []
    passages: list[dict] = []
    for path in file_paths:
        rel = path.relative_to(root).as_posix()
        record = manifest.get(rel, {})
        quality = record.get("quality", "strong")
        if quality not in {"strong", "weak"}:
            raise ValueError(f"Invalid source quality for {rel}: {quality}")
        source_id = _source_id(rel)
        title = record.get("title", path.stem.replace("-", " ").replace("_", " "))
        document_passages = split_passages(path.read_text(encoding="utf-8-sig"))
        documents.append({
            "source_id": source_id,
            "path": rel,
            "title": title,
            "quality": quality,
        })
        for position, quote in enumerate(document_passages, start=1):
            passages.append({
                "source_id": source_id,
                "source_path": rel,
                "title": title,
                "quality": quality,
                "position": position,
                "text": quote,
            })
    corpus_hash = _sha256(_canonical_json({"documents": documents, "passages": passages}))
    index = {
        "schema_version": 1,
        "corpus_hash": corpus_hash,
        "documents": documents,
        "passages": passages,
    }
    index_dir = root / INDEX_DIR
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / INDEX_NAME).write_text(
        json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return index


def load_index(corpus_dir: str | Path) -> dict:
    path = Path(corpus_dir) / INDEX_DIR / INDEX_NAME
    if not path.exists():
        raise FileNotFoundError(f"No ingested index at {path}. Run 'researchdesk ingest' first.")
    index = json.loads(path.read_text(encoding="utf-8"))
    if index.get("schema_version") != 1:
        raise ValueError("Unsupported ResearchDesk index schema")
    return index


def extract_claims(index: dict, topic: str) -> list[dict]:
    keywords = topic_keywords(topic)
    claims = []
    for passage in index["passages"]:
        content_words = set(_tokens(passage["text"]))
        if not keywords or not all(word in content_words for word in keywords):
            continue
        claims.append({
            **passage,
            "matched_topic": topic,
            "stance": classify_stance(passage["text"]),
            "assertion_key": assertion_key(passage["text"]),
        })
    return claims


def _claim_key(claim: dict) -> tuple[str, str]:
    return (" ".join(_tokens(claim["text"])), claim["stance"])


def contradiction_pairs(claims: Iterable[dict]) -> list[dict]:
    groups: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for claim in claims:
        groups[claim["assertion_key"]][claim["stance"]].append(claim)
    pairs = []
    for key in sorted(groups):
        supports = groups[key].get("supports", [])
        opposes = groups[key].get("opposes", [])
        for supporting in supports:
            for opposing in opposes:
                if supporting["source_id"] == opposing["source_id"]:
                    continue
                pairs.append({"assertion_key": key, "supports": supporting, "opposes": opposing})
    return pairs


def source_graph(index: dict, topic: str | None = None) -> dict:
    claims = []
    if topic:
        claims = extract_claims(index, topic)
    else:
        for passage in index["passages"]:
            claims.append({
                **passage,
                "matched_topic": assertion_key(passage["text"]),
                "stance": classify_stance(passage["text"]),
                "assertion_key": assertion_key(passage["text"]),
            })
    by_key: dict[str, list[dict]] = defaultdict(list)
    for claim in claims:
        by_key[claim["assertion_key"]].append(claim)
    topics = []
    for key in sorted(by_key):
        group = by_key[key]
        sources = sorted(group, key=lambda item: (item["source_id"], item["position"]))
        relations = []
        for left_index, left in enumerate(sources):
            for right in sources[left_index + 1:]:
                if left["source_id"] == right["source_id"]:
                    continue
                if {left["stance"], right["stance"]} == {"supports", "opposes"}:
                    relation = "contradicts"
                elif left["stance"] == right["stance"]:
                    relation = "agrees"
                else:
                    continue
                relations.append({
                    "type": relation,
                    "source_a": left["source_id"],
                    "position_a": left["position"],
                    "source_b": right["source_id"],
                    "position_b": right["position"],
                })
        topics.append({
            "topic": key,
            "sources": [{
                "source_id": claim["source_id"],
                "source_path": claim["source_path"],
                "position": claim["position"],
                "stance": claim["stance"],
                "quote": claim["text"],
            } for claim in sources],
            "relations": relations,
        })
    return {"corpus_hash": index["corpus_hash"], "topics": topics}


def _citation(claim: dict) -> str:
    return f"[{claim['source_id']}#{claim['position']:04d}]"


def _markdown_quote(claim: dict) -> str:
    quote = claim["text"].replace("|", "\\|").replace("\n", " ")
    return f'{_citation(claim)} "{quote}"'


def _partition_claims(claims: list[dict], pairs: list[dict]) -> tuple[dict, list[dict]]:
    contradiction_ids = set()
    for pair in pairs:
        contradiction_ids.add((pair["supports"]["source_id"], pair["supports"]["position"]))
        contradiction_ids.add((pair["opposes"]["source_id"], pair["opposes"]["position"]))
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for claim in claims:
        if (claim["source_id"], claim["position"]) in contradiction_ids:
            continue
        groups[_claim_key(claim)].append(claim)
    findings = {"supports": [], "opposes": [], "neutral": []}
    unverified = []
    for _, group in sorted(groups.items(), key=lambda item: item[0]):
        strong_sources = {item["source_id"] for item in group if item["quality"] == "strong"}
        if len(strong_sources) >= 2:
            findings[group[0]["stance"]].append(group)
        else:
            unverified.extend(group)
    for stance in findings:
        findings[stance].sort(key=lambda group: (_claim_key(group[0]), group[0]["source_id"]))
    unverified.sort(key=lambda claim: (claim["source_id"], claim["position"]))
    return findings, unverified


def render_markdown(index: dict, topic: str, claims: list[dict] | None = None) -> str:
    selected = extract_claims(index, topic) if claims is None else claims
    pairs = contradiction_pairs(selected)
    findings, unverified = _partition_claims(selected, pairs)
    lines = [
        f"# ResearchDesk report for `{topic}`",
        "",
        "> Rule-based matching only. No LLM or AI reading comprehension is used. Every citation resolves to an ingested passage. No source, quote, or citation is invented.",
        f"> Corpus SHA-256: `{index['corpus_hash']}`",
        "",
        "## Repeated textual findings (not independently verified)",
        "",
    ]
    labels = {"supports": "Supporting claims", "opposes": "Opposing claims", "neutral": "Neutral claims"}
    has_findings = False
    for stance in ("supports", "opposes", "neutral"):
        groups = findings[stance]
        if not groups:
            continue
        has_findings = True
        lines.extend([f"### {labels[stance]}", ""])
        for group in groups:
            lines.append(f"- {_markdown_quote(group[0])}")
            for claim in group[1:]:
                lines.append(f"  - Corroborates: {_markdown_quote(claim)}")
        lines.append("")
    if not has_findings:
        lines.extend(["No repeated, non-contested claims matched this topic.", ""])
    lines.extend(["## Contradictions", "", "Opposing source statements are shown together. Neither side is treated as established.", ""])
    if pairs:
        for pair in pairs:
            left = pair["supports"]
            right = pair["opposes"]
            lines.extend([
                f"### Opposing evidence: `{pair['assertion_key']}`",
                "",
                "| Supports | Opposes |",
                "| --- | --- |",
                f"| {_markdown_quote(left)} | {_markdown_quote(right)} |",
                "",
            ])
    else:
        lines.extend(["No opposing stance pairs matched this topic.", ""])
    lines.extend(["## UNVERIFIED", "", "Claims without matching wording from at least two strong sources are shown here and are not presented as established findings.", ""])
    if unverified:
        for claim in unverified:
            distinct_sources = {item["source_id"] for item in selected if _claim_key(item) == _claim_key(claim)}
            reason = "single-source evidence" if len(distinct_sources) == 1 else "fewer than two strong sources"
            lines.append(f"- {_markdown_quote(claim)} ({reason}; UNVERIFIED)")
    else:
        lines.append("No single-source claims matched this topic.")
    lines.append("")
    return "\n".join(lines)


def render_html(index: dict, topic: str, claims: list[dict] | None = None) -> str:
    markdown = render_markdown(index, topic, claims)
    escaped = html.escape(markdown)
    body = "<pre>" + escaped + "</pre>"
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>ResearchDesk report: {html.escape(topic)}</title>\n"
        "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#18202a}"
        ".banner{padding:1rem;background:#fff3cd;border:1px solid #e0c36b;border-radius:.4rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}</style>\n"
        "</head>\n<body>\n"
        "<aside class=\"banner\"><strong>Honesty boundary:</strong> This synthesis is rule-based. It does not use an LLM or AI reading comprehension. Every citation resolves to an ingested passage.</aside>\n"
        f"{body}\n</body>\n</html>\n"
    )


def append_audit(corpus_dir: str | Path, topic: str, index: dict, claims: list[dict], pairs: list[dict]) -> dict:
    event = {
        "query": topic,
        "corpus_hash": index["corpus_hash"],
        "claims_returned": len(claims),
        "contradictions_found": len(pairs),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    audit_path = Path(corpus_dir) / AUDIT_NAME
    with audit_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def fetch_url_cached(
    url: str,
    cache_dir: str | Path,
    transport: Callable[[str], bytes] | None = None,
    fetched_on: date | None = None,
) -> tuple[bytes, dict]:
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    key = _sha256(url.encode("utf-8"))
    raw_path = cache / f"{key}.bin"
    meta_path = cache / f"{key}.json"
    if raw_path.exists() and meta_path.exists():
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        payload = raw_path.read_bytes()
        if metadata.get("url") == url and metadata.get("sha256") == _sha256(payload):
            return payload, metadata
    if transport is None:
        request = urllib.request.Request(url, headers={"User-Agent": "ResearchDesk/0.1"})
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read()
    else:
        payload = transport(url)
    if not isinstance(payload, bytes):
        raise TypeError("URL transport must return bytes")
    metadata = {
        "url": url,
        "fetched_on": (fetched_on or datetime.now(timezone.utc).date()).isoformat(),
        "sha256": _sha256(payload),
    }
    raw_path.write_bytes(payload)
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return payload, metadata


def ingest_url(url: str, corpus_dir: str | Path, cache_dir: str | Path | None = None) -> dict:
    root = Path(corpus_dir)
    root.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) if cache_dir else root / INDEX_DIR / "url-cache"
    payload, metadata = fetch_url_cached(url, cache)
    key = _sha256(url.encode("utf-8"))[:16]
    suffix = Path(urllib.parse.urlparse(url).path).suffix.casefold()
    if suffix not in SUPPORTED_SUFFIXES:
        suffix = ".txt"
    local_path = root / f"url-{key}{suffix}"
    local_path.write_bytes(payload)
    (root / f"url-{key}.url.json").write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return ingest_corpus(root)
