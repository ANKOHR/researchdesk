"""Command line interface for ResearchDesk."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import (
    append_audit,
    contradiction_pairs,
    extract_claims,
    ingest_corpus,
    ingest_url,
    load_index,
    render_html,
    render_markdown,
    source_graph,
)
from .fixtures import FIXTURE_SEED, generate_fixtures

HONESTY = (
    "ResearchDesk uses rule-based matching only. It does not use an LLM or AI reading comprehension. "
    "It invents no sources, quotes, or citations, and every citation resolves to an ingested passage."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="researchdesk",
        description=f"Evidence-backed reports from ingested passages. {HONESTY}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fixture_parser = subparsers.add_parser("fixtures", help="write the deterministic synthetic corpus")
    fixture_parser.add_argument("--out", required=True, type=Path, help="output directory")

    ingest_parser = subparsers.add_parser("ingest", help="ingest local text or Markdown files, or fetch and cache one URL")
    ingest_parser.add_argument("source", help="corpus directory or URL")
    ingest_parser.add_argument("--corpus", type=Path, help="workspace directory for URL ingestion; local directory is used by default")
    ingest_parser.add_argument("--cache-dir", type=Path, help="URL cache directory, defaults inside the workspace")

    query_parser = subparsers.add_parser("query", help="extract matching claims from the ingested corpus")
    query_parser.add_argument("topic", help="topic words; every keyword must occur in the passage")
    query_parser.add_argument("--corpus", type=Path, default=Path.cwd(), help="ingested corpus directory, default: current directory")

    report_parser = subparsers.add_parser("report", help="write a citation-grounded Markdown or HTML report")
    report_parser.add_argument("topic", help="topic words; every keyword must occur in the passage")
    report_parser.add_argument("--format", choices=("md", "html"), default="md", help="report format")
    report_parser.add_argument("--corpus", type=Path, default=Path.cwd(), help="ingested corpus directory, default: current directory")
    report_parser.add_argument("--out", type=Path, help="write report to this file instead of standard output")

    sources_parser = subparsers.add_parser("sources", help="show source agreement and contradiction relationships")
    sources_parser.add_argument("--topic", help="limit graph to passages matching all topic keywords")
    sources_parser.add_argument("--corpus", type=Path, default=Path.cwd(), help="ingested corpus directory, default: current directory")
    return parser


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _query_payload(corpus: Path, topic: str) -> dict:
    index = load_index(corpus)
    claims = extract_claims(index, topic)
    pairs = contradiction_pairs(claims)
    audit = append_audit(corpus, topic, index, claims, pairs)
    return {
        "query": topic,
        "corpus_hash": index["corpus_hash"],
        "claims": claims,
        "contradictions": pairs,
        "audit": audit,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "fixtures":
            root = generate_fixtures(args.out)
            sys.stdout.write(_dump({"synthetic": True, "directory": str(root.resolve()), "documents": 14, "fixture_seed": FIXTURE_SEED}))
            return 0
        if args.command == "ingest":
            if args.source.startswith(("https://", "http://", "file://")):
                corpus = args.corpus or Path.cwd()
                index = ingest_url(args.source, corpus, args.cache_dir)
            else:
                if args.corpus is not None:
                    parser.error("--corpus is only used when ingesting a URL")
                index = ingest_corpus(Path(args.source))
                corpus = Path(args.source)
            sys.stdout.write(_dump({
                "corpus": str(corpus.resolve()),
                "corpus_hash": index["corpus_hash"],
                "sources": len(index["documents"]),
                "passages": len(index["passages"]),
            }))
            return 0
        if args.command == "query":
            sys.stdout.write(_dump(_query_payload(args.corpus, args.topic)))
            return 0
        if args.command == "report":
            payload = _query_payload(args.corpus, args.topic)
            index = load_index(args.corpus)
            if args.format == "html":
                result = render_html(index, args.topic, payload["claims"])
            else:
                result = render_markdown(index, args.topic, payload["claims"])
            if args.out:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(result, encoding="utf-8", newline="\n")
            else:
                sys.stdout.write(result)
            return 0
        if args.command == "sources":
            index = load_index(args.corpus)
            graph = source_graph(index, args.topic)
            if args.topic:
                claims = extract_claims(index, args.topic)
                pairs = contradiction_pairs(claims)
                append_audit(args.corpus, args.topic, index, claims, pairs)
            sys.stdout.write(_dump(graph))
            return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
