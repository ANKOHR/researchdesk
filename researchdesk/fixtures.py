"""Create a deterministic synthetic corpus for demos and tests."""

from __future__ import annotations

import json
import random
from pathlib import Path

FIXTURE_SEED = 1729

DOCUMENTS = {
    "01-lab-note-aya.md": {
        "title": "Lab note by Aya Bell",
        "quality": "strong",
        "body": (
            "Project Aurora battery uses a replaceable cobalt-free cell.\n"
            "Project Aurora pilot opened on 14 April 2026."
        ),
    },
    "02-lab-note-ben.txt": {
        "title": "Lab note by Ben Ives",
        "quality": "strong",
        "body": (
            "Project Aurora battery uses a replaceable cobalt-free cell.\n"
            "Project Aurora pilot opened on 14 April 2026."
        ),
    },
    "03-supplier-brief.md": {
        "title": "Supplier brief from Glasswing Works",
        "quality": "strong",
        "body": "Project Aurora battery uses a replaceable cobalt-free cell.",
    },
    "04-field-report-lin.md": {
        "title": "Field report by Lin Orro",
        "quality": "strong",
        "body": "Project Aurora supports offline mode.\nProject Aurora includes a replaceable battery pack.",
    },
    "05-field-report-mara.md": {
        "title": "Field report by Mara Venn",
        "quality": "strong",
        "body": "Project Aurora does not support offline mode.\nProject Aurora does not include a replaceable battery pack.",
    },
    "06-accessibility-review.md": {
        "title": "Accessibility review by Neri Sol",
        "quality": "strong",
        "body": "Project Aurora includes tactile controls on the left edge.",
    },
    "07-clinic-trial.txt": {
        "title": "Clinic trial summary",
        "quality": "strong",
        "body": "Project Aurora trial enrolled 48 volunteers at Larkspur Clinic.",
    },
    "08-operations-memo.md": {
        "title": "Operations memo by Dax Rill",
        "quality": "strong",
        "body": "Project Aurora pilot opened on 14 April 2026.\nProject Aurora ships in a paper sleeve.",
    },
    "09-community-letter.md": {
        "title": "Community letter by Edda Pike",
        "quality": "strong",
        "body": "Project Aurora uses a paper sleeve for shipping.",
    },
    "10-repair-ledger.txt": {
        "title": "Repair ledger",
        "quality": "strong",
        "body": "Project Aurora repair parts are stocked in Fen Harbor.",
    },
    "11-independent-audit.md": {
        "title": "Independent audit by Olan Reed",
        "quality": "strong",
        "body": "Project Aurora battery passed the salt mist test in June 2026.",
    },
    "12-unverified-rumor.md": {
        "title": "Unconfirmed neighborhood note",
        "quality": "weak",
        "body": "Project Aurora has a private garden on the roof.",
    },
    "13-design-journal.md": {
        "title": "Design journal by Pella Moss",
        "quality": "strong",
        "body": "Project Aurora uses recycled paper in its quick start card.",
    },
    "14-logistics-slip.txt": {
        "title": "Logistics slip",
        "quality": "strong",
        "body": "Project Aurora cartons leave from West Quay depot.",
    },
}


def generate_fixtures(out_dir: str | Path) -> Path:
    """Write the fixed fictional corpus and return its directory."""
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    records = list(DOCUMENTS.items())
    random.Random(FIXTURE_SEED).shuffle(records)
    manifest = {"fixture_seed": FIXTURE_SEED, "sources": {}}
    for filename, record in records:
        target.joinpath(filename).write_text(record["body"] + "\n", encoding="utf-8", newline="\n")
        manifest["sources"][filename] = {
            "title": record["title"],
            "quality": record["quality"],
        }
    target.joinpath("rd-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target
