"""Current acceptance of explicitly authorized existing Earning call documents.

These receipts describe new checks, never reconstructed producer history.
Normal production runs continue to require their original provenance.
"""
from __future__ import annotations

import importlib.util
import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import release_store as store

SEMANTIC_VALIDATOR = Path(r"C:\Users\USER\.codex\skills\oppday-conclusion\scripts\validate_semantic_coverage.py")
WORKFLOW_SCRIPTS = Path(r"C:\Users\USER\.codex\skills\multiagent-oppday\scripts")
IDENTITY = ("run_id", "registration_id", "ticker", "event_date", "quarter")
SOURCE_ROLES = ("transcript_md", "transcript_pdf", "presentation_pdf")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def qualification_directory(qualification_id: str) -> Path:
    _require(bool(store.RELEASE_ID_RE.fullmatch(qualification_id)), "Invalid qualification ID")
    root = store.WORK / "requalification"
    directory = root / qualification_id
    store.WORK.resolve().relative_to(store.ROOT.resolve())
    directory.resolve().relative_to(store.WORK.resolve())
    directory.resolve().relative_to(root.resolve())
    _require(directory.is_dir(), "Qualification directory is unavailable")
    return directory


def official_quarter(quarter: str) -> tuple[int, int]:
    sys.path.insert(0, str(WORKFLOW_SCRIPTS))
    from workflow_common import parse_quarter
    parsed = parse_quarter(quarter)
    return parsed.gregorian_year, parsed.number


def youtube_id(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.hostname == "youtu.be":
        return parsed.path.strip("/")
    if parsed.hostname not in ("youtube.com", "www.youtube.com"):
        return ""
    if parsed.path.startswith("/embed/"):
        return parsed.path.removeprefix("/embed/").strip("/")
    return parse_qs(parsed.query).get("v", [""])[0]


def delivery_target(profile: dict, ticker: str, quarter: str) -> Path:
    sys.path.insert(0, str(WORKFLOW_SCRIPTS))
    from publishing import load_valuation_map, resolve_valuation_target
    from workflow_common import parse_quarter
    target, _ = resolve_valuation_target(
        valuation_map=load_valuation_map(Path(profile["valuationMap"]), allow_missing=True),
        ticker=ticker, quarter=parse_quarter(quarter), default_valuation_root=Path(profile["valuationRoot"]))
    return target


def verify_deliveries(job: dict, profile: dict) -> str:
    event = Path(profile["oppdayRoot"]) / job["quarter"] / "Oppday" / job["event_date"] / job["ticker"]
    csv_path = event.parent.parent / f"workflow_status_{job['quarter']}.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if (row.get("run_id"), row.get("registration_id"))
                == (job["run_id"], str(job["registration_id"]))]
    _require(len(rows) == 1, "Qualified delivery status identity is absent or ambiguous")
    row = rows[0]
    _require(row.get("ticker") == job["ticker"] and row.get("event_date") == job["event_date"]
             and row.get("quarter") == job["quarter"] and row.get("hash_status") == "pass"
             and row.get("valuation_status", "").startswith("done_"), "Qualified delivery status did not pass")
    target = delivery_target(profile, job["ticker"], job["quarter"])
    for prefix in ("conclusion", "presentation", "transcript"):
        binding = job["source_binding"][prefix + "_pdf"]
        name = Path(binding["path"]).name
        source = event / name
        destination = target / name
        _require(Path(row.get(prefix + "_source_path", "")).resolve() == source.resolve()
                 and Path(row.get(prefix + "_target_path", "")).resolve() == destination.resolve(),
                 "Qualified delivery source/target paths differ from the canonical document roles")
        digest = binding["sha256"]
        _require(row.get(prefix + "_sha256_source") == row.get(prefix + "_sha256_target") == digest
                 == store.sha256(source) == store.sha256(destination), "Qualified delivery hashes differ")
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def run_semantic_validator(job: dict, folder: Path) -> dict:
    spec = importlib.util.spec_from_file_location("oppday_current_semantic_validator", SEMANTIC_VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_semantic_coverage(
        markdown_path=Path(job["source_binding"]["conclusion_md"]["path"]),
        ledger_path=folder / "semantic_coverage.json",
        qa_coverage_path=folder / "qa_coverage.json",
        expected_identity={key: job[key] for key in IDENTITY},
        expected_source_hashes=job["input_sha256"],
        expected_source_paths={role: job["source_binding"][role]["path"] for role in SOURCE_ROLES},
    )


def select_items(qualification_id: str, tickers: list[str], raw_items: list[dict]) -> list[dict]:
    directory = qualification_directory(qualification_id)
    _require(bool(tickers) and len(tickers) == len(set(tickers)), "Select an exact nonempty unique ticker set")
    result = []
    for ticker in tickers:
        _require(ticker.isalnum() and ticker == ticker.upper(), "Invalid qualification ticker")
        job = store.read_json(directory / ticker / "qualification_job.json")
        (directory / ticker).resolve().relative_to(directory.resolve())
        selected = [item for item in raw_items if (item.get("runId"), str(item.get("registrationId")), item.get("symbol"), item.get("quarter"))
                    == (job["run_id"], str(job["registration_id"]), ticker, job["quarter"])]
        _require(len(selected) == 1, "Qualification selection is absent, stale or ambiguous")
        result.extend(selected)
    return result


def verify_qualification(qualification_id: str, items: list[dict]) -> dict:
    directory = qualification_directory(qualification_id)
    authorization = store.read_json(directory / "authorization.json")
    assignments = store.read_json(directory / "review-assignments.json")
    _require(authorization.get("qualificationId") == qualification_id
             and authorization.get("action") == "review_then_publish_passed_only"
             and authorization.get("preserveOriginals") is True
             and authorization.get("revoked") is not True
             and authorization.get("originalProducerEvidenceReconstructed") is False,
             "Explicit current requalification authorization is required")
    _require(assignments.get("qualificationId") == qualification_id
             and assignments.get("authorizationSha256") == store.sha256(directory / "authorization.json"),
             "Reviewer assignments are not bound to the current authorization")
    _require(bool(items), "An empty qualification is not a release")
    results = []
    profile = store.read_json(store.PROFILE)
    oppday_root = Path(profile["oppdayRoot"])
    for item in items:
        ticker = item["symbol"]
        _require(ticker in authorization.get("tickerSet", []), "Ticker is outside the authorized qualification")
        _require(ticker.isalnum(), "Invalid qualification ticker")
        folder = directory / ticker
        folder.resolve().relative_to(directory.resolve())
        job = store.read_json(folder / "qualification_job.json")
        _require(job.get("kind") == "existing-earning-call-current-requalification"
                 and job.get("qualification_id") == qualification_id
                 and job.get("historical_producer_qa_available") is False,
                 "Current qualification cannot impersonate historical producer QA")
        expected_identity = {"run_id": item.get("runId"), "registration_id": item.get("registrationId"),
                             "ticker": ticker, "quarter": item["quarter"], "event_date": item["eventDate"]}
        _require(all(str(expected_identity[key]) == str(job[key]) for key in IDENTITY),
                 "Qualification record identity differs")
        _require(job.get("curator_task_id") == authorization.get("curatorTaskId"), "Qualification curator differs")
        binding = job["source_binding"]
        _require(set(binding) == {"conclusion_md", "conclusion_pdf", *SOURCE_ROLES}, "Qualification source roles differ")
        for role, entry in binding.items():
            frozen = Path(entry["path"])
            frozen.resolve().relative_to(folder.resolve())
            frozen.resolve().relative_to((folder / "sources").resolve())
            event = oppday_root / job["quarter"] / "Oppday" / job["event_date"] / ticker
            if role.startswith("conclusion_"):
                extension = ".md" if role.endswith("_md") else ".pdf"
                original = oppday_root / job["quarter"] / "Oppday" / "สรุป oppday" / job["event_date"] / f"{ticker}-Earning call-{job['quarter']}{extension}"
            else:
                extension = ".md" if role.endswith("_md") else ".pdf"
                source_kind = role.removesuffix("_md").removesuffix("_pdf")
                original = event / f"{ticker}_{source_kind}_{job['quarter']}{extension}"
            _require(Path(entry["originalPath"]).resolve() == original.resolve(), "Qualification source is outside its canonical document role")
            _require(store.sha256(frozen) == entry["sha256"] == store.sha256(Path(entry["originalPath"])),
                     "A frozen or original qualification source changed: " + role)
        _require(job.get("input_sha256") == {role: binding[role]["sha256"] for role in SOURCE_ROLES},
                 "Qualification source hash map differs")
        for extension, role in ((".md", "conclusion_md"), (".pdf", "conclusion_pdf")):
            selected = [entry for entry in item["files"] if entry["extension"] == extension]
            _require(len(selected) == 1 and store.sha256(Path(selected[0]["path"])) == binding[role]["sha256"],
                     "Scanned summary differs from the currently reviewed artifact")
        _require(len(item["files"]) == 2, "Qualification imports only one exact summary MD/PDF pair")
        official = store.read_json(folder / "official-event.json")
        year, round_number = official_quarter(job["quarter"])
        _require((str(official.get("id")), official.get("symbol"), official.get("year"), official.get("round"))
                 == (str(job["registration_id"]), ticker, year, round_number),
                 "Official event identity differs")
        _require(str(official.get("meeting_date", "")).startswith(job["event_date"])
                 and job.get("official_presentation_sha256") == binding["presentation_pdf"]["sha256"],
                 "Official Presentation/event binding differs")
        transcript_text = Path(binding["transcript_md"]["path"]).read_text(encoding="utf-8-sig")
        source_urls = [line.removeprefix("Source:").strip() for line in transcript_text.splitlines() if line.startswith("Source:")]
        official_video_id = youtube_id(str(official.get("video_link", "")))
        _require(bool(official_video_id) and len(source_urls) == 1 and youtube_id(source_urls[0]) == official_video_id,
                 "Delivered Transcript video identity differs from its official event")
        handoff = store.read_json(folder / "semantic_review_handoff.json")
        blocker_path = folder / "review_findings.json"
        if blocker_path.is_file():
            blocker = store.read_json(blocker_path)
            if (blocker.get("terminal") is True and blocker.get("pass") is False
                    and blocker.get("qualification_id") == qualification_id
                    and all(str(blocker.get(key)) == str(job[key]) for key in IDENTITY)
                    and blocker.get("markdown_sha256") == binding["conclusion_md"]["sha256"]
                    and blocker.get("pdf_sha256") == binding["conclusion_pdf"]["sha256"]):
                raise ValueError("An unresolved terminal review blocks these exact qualification artifacts")
        reviewer_id = assignments.get("reviewers", {}).get(ticker, {}).get("taskId")
        _require(bool(reviewer_id) and handoff.get("reviewer_task_id") == reviewer_id
                 and reviewer_id != job["curator_task_id"], "Actual independent reviewer identity is required")
        _require(handoff.get("terminal") is True and handoff.get("pass") is True
                 and handoff.get("qualification_id") == qualification_id,
                 "Current independent review did not pass")
        _require(all(str(handoff.get(key)) == str(job[key]) for key in IDENTITY), "Reviewer handoff identity differs")
        _require(datetime.fromisoformat(handoff["completed_at"]) >= datetime.fromisoformat(job["created_at"]),
                 "Reviewer completion predates the current qualification job")
        _require(handoff.get("author_task_id") == job["curator_task_id"]
                 and handoff.get("input_sha256") == job["input_sha256"], "Reviewer source/curator binding differs")
        expected_hashes = {
            "markdown_sha256": binding["conclusion_md"]["sha256"],
            "pdf_sha256": binding["conclusion_pdf"]["sha256"],
            "qa_coverage_sha256": store.sha256(folder / "qa_coverage.json"),
            "semantic_coverage_sha256": store.sha256(folder / "semantic_coverage.json"),
        }
        _require(all(handoff.get(key) == value for key, value in expected_hashes.items()), "Reviewer artifacts are stale or changed")
        semantic = run_semantic_validator(job, folder)
        _require(semantic.get("status") == "pass"
                 and semantic.get("author_task_id") == job["curator_task_id"]
                 and semantic.get("reviewer_task_id") == reviewer_id, "Strict semantic/Q&A validation did not pass")
        inspection_dir = directory / "pdf-inspections" / ticker
        inspection = store.read_json(inspection_dir / "inspection-binding.json")
        pdf_qa = store.read_json(inspection_dir / "pdf-qa.json")
        _require(inspection.get("historical_render_manifest_available") is False
                 and inspection.get("kind") == "current-inspection-of-existing-delivered-pdf-not-original-render-provenance",
                 "Existing PDF inspection cannot claim historical rendering provenance")
        _require(pdf_qa.get("pass") is True and pdf_qa.get("markdown_sha256") == expected_hashes["markdown_sha256"]
                 and pdf_qa.get("pdf_sha256") == expected_hashes["pdf_sha256"], "Existing PDF QA is missing, failed or stale")
        visual = store.read_json(folder / "visual_review.json")
        _require(all(str(visual.get(key)) == str(job[key]) for key in IDENTITY)
                 and visual.get("terminal") is True
                 and visual.get("qualification_id") == qualification_id
                 and visual.get("reviewer_task_id") == reviewer_id
                 and visual.get("markdown_sha256") == expected_hashes["markdown_sha256"]
                 and visual.get("pdf_sha256") == expected_hashes["pdf_sha256"]
                 and datetime.fromisoformat(visual["completed_at"]) >= datetime.fromisoformat(job["created_at"]),
                 "Visual receipt identity/source/date binding differs")
        _require(datetime.fromisoformat(handoff["completed_at"]) >= datetime.fromisoformat(visual["completed_at"]),
                 "Reviewer handoff predates its visual inspection")
        _require(handoff.get("visual_review_sha256") == store.sha256(folder / "visual_review.json"),
                 "Reviewer handoff does not bind the current visual receipt")
        _require(visual.get("pass") is True and not visual.get("findings"), "Current visual inspection did not pass")
        _require(set(pdf_qa["visual_review_required_pages"]).issubset(visual.get("visual_reviewed_pages", [])),
                 "Required existing PDF pages were not visually inspected")
        inspected_images = visual.get("inspected_images", [])
        _require(bool(inspected_images) and set(pdf_qa["contact_sheets"]).issubset(inspected_images),
                 "All PDF contact sheets must be inspected")
        for image in inspected_images:
            path = Path(image)
            path.resolve().relative_to(directory.resolve())
            _require(path.is_file(), "An inspected PDF image is missing")
        delivery_status_hash = verify_deliveries(job, profile)
        results.append({"ticker": ticker, "runId": job["run_id"], "registrationId": job["registration_id"],
                        "reviewerTaskId": reviewer_id, "reviewHandoffSha256": store.sha256(folder / "semantic_review_handoff.json"),
                        "qualificationJobSha256": store.sha256(folder / "qualification_job.json"),
                        "officialEventSha256": store.sha256(folder / "official-event.json"),
                        "visualReviewSha256": store.sha256(folder / "visual_review.json"),
                        "pdfQaSha256": store.sha256(inspection_dir / "pdf-qa.json"),
                        "deliveryStatusRowSha256": delivery_status_hash})
    return {"pass": True, "kind": "current-existing-earning-call-qualification", "qualificationId": qualification_id,
            "authorizationSha256": store.sha256(directory / "authorization.json"),
            "reviewAssignmentsSha256": store.sha256(directory / "review-assignments.json"),
            "historicalProducerQaReconstructed": False, "audioRecognitionAccuracyReverified": False, "items": results}


def verify_prepared_release(release_id: str, manifest: dict) -> dict | None:
    qualification_id = manifest.get("qualificationId")
    if not qualification_id:
        return None
    directory = store.release_directory(release_id)
    index = store.read_json(directory / "index.local.json")
    selected_ids = manifest.get("selectedItemIds", [])
    _require(bool(selected_ids) and len(selected_ids) == len(set(selected_ids)), "Qualified release selection is invalid")
    items = [item for item in index["items"] if item["id"] in selected_ids]
    _require(len(items) == len(selected_ids), "Qualified release selection differs from its snapshot")
    if manifest.get("readerFilePolicy") == "markdown-only-v1":
        from scripts.build_static_site import public_item
        from scripts.release_snapshot import markdown_reader_item
        admitted = manifest.get("admissionItems") or []
        _require(len(admitted) == len(selected_ids) and {item["id"] for item in admitted} == set(selected_ids),
                 "Qualified source admission set differs")
        admitted_by_id = {item["id"]: item for item in admitted}
        for reader in items:
            source = markdown_reader_item(admitted_by_id[reader["id"]])
            _require(public_item(reader) == public_item(source)
                     and store.sha256(Path(reader["files"][0]["path"]))
                     == store.sha256(Path(source["files"][0]["path"])),
                     "Qualified reader Markdown differs from its reviewed source")
        items = admitted
    proof = verify_qualification(qualification_id, items)
    _require(proof == manifest.get("qualificationVerification"), "Qualification evidence changed; prepare a new release ID")
    return proof
