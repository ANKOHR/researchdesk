from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from researchdesk.core import (
    contradiction_pairs,
    extract_claims,
    fetch_url_cached,
    ingest_corpus,
    load_index,
    render_html,
    render_markdown,
    source_graph,
)
from researchdesk.fixtures import DOCUMENTS, FIXTURE_SEED, generate_fixtures

ROOT = Path(__file__).resolve().parents[1]


def _make_corpus(path: Path) -> dict:
    generate_fixtures(path)
    return ingest_corpus(path)


def _passage_map(index: dict) -> dict[tuple[str, int], str]:
    return {(item["source_id"], item["position"]): item["text"] for item in index["passages"]}


def test_fixture_generator_is_deterministic_and_plants_required_evidence(tmp_path: Path) -> None:
    first = generate_fixtures(tmp_path / "one")
    second = generate_fixtures(tmp_path / "two")
    files_a = {item.name: item.read_bytes() for item in first.iterdir() if item.is_file()}
    files_b = {item.name: item.read_bytes() for item in second.iterdir() if item.is_file()}
    assert files_a == files_b
    assert len(DOCUMENTS) == 14
    assert FIXTURE_SEED == 1729
    assert all("Project Aurora" in record["body"] for record in DOCUMENTS.values())
    assert sum(record["body"].count("replaceable cobalt-free cell") for record in DOCUMENTS.values()) == 3
    index = ingest_corpus(first)
    all_claims = extract_claims(index, "Project Aurora")
    pairs = contradiction_pairs(all_claims)
    assert {pair["assertion_key"] for pair in pairs} >= {
        "project aurora offline mode",
        "project aurora replaceable battery pack",
    }
    assert any("private garden on the roof" in claim["text"] for claim in all_claims)


def test_extraction_returns_stable_source_ids_and_positions(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    first = _make_corpus(corpus)
    claims = extract_claims(first, "battery cell")
    expected_paths = {"01-lab-note-aya.md", "02-lab-note-ben.txt", "03-supplier-brief.md"}
    assert {claim["source_path"] for claim in claims} == expected_paths
    assert all(claim["position"] == 1 for claim in claims)
    first_ids = {doc["path"]: doc["source_id"] for doc in first["documents"]}
    second = ingest_corpus(corpus)
    second_ids = {doc["path"]: doc["source_id"] for doc in second["documents"]}
    assert first_ids == second_ids
    assert first["corpus_hash"] == second["corpus_hash"]


def test_both_planted_contradictions_are_reported_side_by_side(tmp_path: Path) -> None:
    index = _make_corpus(tmp_path / "corpus")
    report = render_markdown(index, "Project Aurora")
    assert report.count("| Supports | Opposes |") == 2
    assert "supports offline mode" in report
    assert "does not support offline mode" in report
    assert "includes a replaceable battery pack" in report
    assert "does not include a replaceable battery pack" in report
    assert "## Contradictions" in report


def test_end_to_end_report_has_agreement_conflicts_unverified_and_boundary(tmp_path: Path) -> None:
    index = _make_corpus(tmp_path / "corpus")
    report = render_markdown(index, "Project Aurora")
    findings = report.split("## Contradictions", 1)[0]
    unverified = report.split("## UNVERIFIED", 1)[1]
    assert "Repeated textual findings" in findings
    assert "replaceable cobalt-free cell" in findings
    assert "offline mode" in report
    assert "private garden on the roof" in unverified
    assert "Rule-based matching only" in report
    assert "No LLM or AI reading comprehension" in report
    assert "Every citation resolves to an ingested passage" in report


def test_every_report_citation_resolves_to_exact_ingested_quote(tmp_path: Path) -> None:
    index = _make_corpus(tmp_path / "corpus")
    report = render_markdown(index, "Project Aurora")
    passages = _passage_map(index)
    found = re.findall(r'\[([a-z0-9-]+)#(\d{4})\]\s+"([^"]*)"', report)
    assert found
    assert len(found) == len(re.findall(r"\[[a-z0-9-]+#\d{4}\]", report))
    for source_id, position, quote in found:
        assert passages[(source_id, int(position))] == quote


def test_single_source_weak_claim_is_unverified_and_not_a_main_finding(tmp_path: Path) -> None:
    index = _make_corpus(tmp_path / "corpus")
    report = render_markdown(index, "roof garden")
    main_section = report.split("## UNVERIFIED", 1)[0]
    unverified_section = report.split("## UNVERIFIED", 1)[1]
    assert "private garden on the roof" not in main_section
    assert "private garden on the roof" in unverified_section
    assert "UNVERIFIED" in unverified_section


def test_markdown_and_html_reports_are_byte_deterministic(tmp_path: Path) -> None:
    index = _make_corpus(tmp_path / "corpus")
    md_a = render_markdown(index, "Project Aurora").encode("utf-8")
    md_b = render_markdown(index, "Project Aurora").encode("utf-8")
    html_a = render_html(index, "Project Aurora").encode("utf-8")
    html_b = render_html(index, "Project Aurora").encode("utf-8")
    assert md_a == md_b
    assert html_a == html_b
    assert b"rule-based" in html_a
    assert b"Every citation resolves to an ingested passage" in html_a


def test_ingest_text_markdown_and_url_cache(tmp_path: Path) -> None:
    corpus = tmp_path / "fixture-corpus"
    generate_fixtures(corpus)
    index = ingest_corpus(corpus)
    assert len(index["documents"]) == 14
    assert {Path(item["path"]).suffix for item in index["documents"]} == {".md", ".txt"}
    assert [item["position"] for item in index["passages"] if item["source_path"] == "01-lab-note-aya.md"] == [1, 2]
    assert next(item for item in index["passages"] if item["source_path"] == "01-lab-note-aya.md" and item["position"] == 1)["text"] == "Project Aurora battery uses a replaceable cobalt-free cell."
    assert len({item["source_id"] for item in index["documents"]}) == 14

    cache = tmp_path / "cache"
    calls: list[str] = []
    fixture_payload = corpus.joinpath("01-lab-note-aya.md").read_bytes()

    def transport(url: str) -> bytes:
        calls.append(url)
        return fixture_payload

    local_url = corpus.joinpath("01-lab-note-aya.md").resolve().as_uri()
    payload_a, meta_a = fetch_url_cached(local_url, cache, transport, date(2026, 9, 28))
    payload_b, meta_b = fetch_url_cached(local_url, cache, transport, date(2026, 9, 29))
    assert payload_a == payload_b == fixture_payload
    assert len(calls) == 1
    assert meta_a["fetched_on"] == meta_b["fetched_on"] == "2026-09-28"
    assert len(list(cache.glob("*.bin"))) == 1


def test_graph_exposes_agreement_and_contradiction_edges(tmp_path: Path) -> None:
    index = _make_corpus(tmp_path / "corpus")
    graph = source_graph(index, "Project Aurora")
    relations = [edge["type"] for topic in graph["topics"] for edge in topic["relations"]]
    assert "agrees" in relations
    assert "contradicts" in relations


def test_cli_smoke_for_every_subcommand(tmp_path: Path) -> None:
    corpus = tmp_path / "cli-corpus"
    output = tmp_path / "report.html"

    def invoke(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "researchdesk", *args],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )

    assert "synthetic" in invoke("fixtures", "--out", str(corpus)).stdout
    assert "passages" in invoke("ingest", str(corpus)).stdout
    query = json.loads(invoke("query", "battery cell", "--corpus", str(corpus)).stdout)
    assert len(query["claims"]) == 3
    assert "offline mode" in invoke("report", "Project Aurora", "--corpus", str(corpus)).stdout
    assert "rule-based" in invoke("report", "offline mode", "--format", "html", "--corpus", str(corpus), "--out", str(output)).stdout or output.exists()
    graph = json.loads(invoke("sources", "--corpus", str(corpus)).stdout)
    assert graph["topics"]
    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")
    help_text = invoke("--help").stdout
    assert "does not use an LLM" in help_text
    assert len((corpus / "rd-audit.jsonl").read_text(encoding="utf-8").splitlines()) >= 3


def test_cli_query_and_report_audit_records_contain_counts_and_hash(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    _make_corpus(corpus)
    command = [sys.executable, "-m", "researchdesk"]
    subprocess.run(command + ["query", "offline mode", "--corpus", str(corpus)], cwd=ROOT, check=True, capture_output=True)
    subprocess.run(command + ["report", "offline mode", "--corpus", str(corpus)], cwd=ROOT, check=True, capture_output=True)
    events = [json.loads(line) for line in (corpus / "rd-audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(events) == 2
    assert all(event["query"] == "offline mode" for event in events)
    assert all(event["corpus_hash"] == load_index(corpus)["corpus_hash"] for event in events)
    assert all(event["claims_returned"] == 2 and event["contradictions_found"] == 1 for event in events)
