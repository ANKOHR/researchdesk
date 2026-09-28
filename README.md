# ResearchDesk

ResearchDesk is a local research workspace that indexes text and Markdown passages, matches a user topic with deterministic rules, compares source statements, and generates reports with source IDs, passage positions, and exact ingested quotes.

> ResearchDesk reads the way a good analyst reads: every claim has a source, every source has a quote, and when the sources disagree, it shows you the disagreement instead of hiding it.

ResearchDesk is a rule-based provenance tool. It does not use an LLM, learned model, or AI reading comprehension.

## Quickstart

Requires Python 3.10 or later. Runtime code uses only the Python standard library. Install the test extra to run the test suite.

```powershell
python -m pip install -e ".[test]"
python -m researchdesk fixtures --out .\sample-corpus
python -m researchdesk ingest .\sample-corpus
python -m researchdesk query "Project Aurora" --corpus .\sample-corpus
python -m researchdesk report "Project Aurora" --corpus .\sample-corpus --format md --out .\aurora-report.md
python -m researchdesk report "Project Aurora" --corpus .\sample-corpus --format html --out .\aurora-report.html
python -m researchdesk sources --corpus .\sample-corpus
python -m pytest
```

The fixture command writes 14 short documents about a fictional project and people. It includes repeated statements, two planted opposing statement pairs, and a single-source weak note. Fixture output is deterministic. The fixed seed is 1729 and is used only to choose a repeatable file write order.

Local text and Markdown files can be ingested from any corpus directory. To fetch one URL and cache its raw bytes, pass the URL as the ingest source and choose a workspace:

```powershell
python -m researchdesk ingest "file:///C:/path/to/local-fixture.txt" --corpus .\url-workspace
```

The URL cache is stored under `.researchdesk/url-cache` by default. Its metadata records the URL, fetch date, and raw-byte SHA-256. A later ingest of the same URL uses the cache. HTTP and HTTPS are supported for an explicit user request. Tests use a stub transport and do not access the network.

## Architecture

```text
local .txt/.md files or one URL
              |
              v
normalization and sentence passage splitting
              |
              v
.researchdesk/index.json
  stable source IDs, passage positions, source quality, corpus hash
              |
       +------+------+
       |             |
       v             v
topic keyword     assertion and stance
matching           comparison
       |             |
       +------+------+
              v
query JSON, source graph, Markdown report, or HTML report
              |
              v
rd-audit.jsonl
```

The index is rebuilt by `ingest`. Source IDs are derived from normalized relative paths. Passage positions start at 1 and follow document order. A corpus hash covers the indexed document metadata and passage text. Reports and source graphs are computed from the stored index at request time. Audit entries record the query, corpus hash, number of matched claims, number of contradiction pairs, and UTC timestamp.

## Honesty boundary

ResearchDesk never invents sources, quotes, or citations. Report citations use the source ID and 1-based passage position from the ingested index. The quoted text is the indexed passage text. A citation that does not resolve to that passage is a build failure.

Claims are matched by topic keywords and simple stance rules. Every non-stopword keyword in the topic must appear in a passage. A repeated finding means the same normalized sentence appeared in at least two distinct sources. A contradiction candidate means two passages have the same simple assertion key and the stance matcher assigns opposite polarity. These rules can miss real relationships or flag a false relationship. They do not verify whether a source statement is true.

Claims without matching wording from at least two strong sources are placed in `UNVERIFIED` and are not presented as established findings. Opposing statements are shown beside one another and marked as contradictions, not resolved in favor of either source. Repeated wording is textual corroboration only, not proof of truth. Reports say that matching is rule-based and that no LLM or AI reading comprehension was used. The HTML report displays this boundary in a visible banner.

ResearchDesk does not browse for sources or understand documents. It only compares the local passages it has ingested. For reliable conclusions, a person must inspect the cited passages and assess the source quality and context.

## CLI reference

Run `python -m researchdesk --help` for the top-level help. The help text states the rule-based and no-invention boundary.

### `fixtures`

```text
researchdesk fixtures --out DIRECTORY
```

Writes the deterministic, clearly synthetic 14-document corpus and its `rd-manifest.json` quality metadata.

### `ingest`

```text
researchdesk ingest DIRECTORY
researchdesk ingest URL --corpus WORKSPACE [--cache-dir DIRECTORY]
```

Parses `.txt` and `.md` documents, normalizes whitespace and Markdown formatting, ignores Markdown headings, and stores one indexed passage per sentence. It writes `.researchdesk/index.json`. URL bytes are cached with their fetch date before they are indexed.

### `query`

```text
researchdesk query "TOPIC WORDS" [--corpus DIRECTORY]
```

Prints JSON with the matched topic, exact passage text, source ID, relative source path, 1-based position, source quality, stance, assertion key, contradiction pairs, corpus hash, and audit event. Every keyword in the topic must occur in a passage.

### `report`

```text
researchdesk report "TOPIC WORDS" [--format md|html] [--corpus DIRECTORY] [--out FILE]
```

Writes Markdown to standard output by default. The report separates repeated textual findings, opposing evidence, and `UNVERIFIED` claims. Contradictions show the exact opposing quotes side by side. Each quote has a citation in the form `[source-id#0001]`. HTML output has a visible honesty banner. Report bytes do not contain a generation timestamp, so the same index and topic produce byte-identical output.

### `sources`

```text
researchdesk sources [--topic "TOPIC WORDS"] [--corpus DIRECTORY]
```

Prints a JSON source graph. Without `--topic`, each assertion key found in the index is listed with its source passages and same-stance or opposing-stance relationships. With `--topic`, only passages matching all topic keywords are included.

## Data and limitations

`.researchdesk/index.json` is a derived local index and can be regenerated with `ingest`. `rd-audit.jsonl` is append-only for query, report, and topic-filtered source-graph requests. It contains timestamps, so the audit log is not expected to be byte-identical across runs. Generated report content is deterministic for the same indexed corpus and topic.

Markdown headings are treated as document structure and skipped. Paragraph content is whitespace-normalized and split at sentence punctuation. The sentence splitter and stance matcher are intentionally small, transparent heuristics. They are not language understanding systems.
