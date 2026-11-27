"""Explicit, additive imports of existing Earning call Markdown, not report QA."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import release_store as store
import server
from scripts import build_static_site as static

ACTION = "import_existing_earning_call_markdown"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def import_directory(import_id: str) -> Path:
    require(bool(store.RELEASE_ID_RE.fullmatch(import_id)), "Invalid Markdown import ID")
    directory = store.WORK / "markdown-imports" / import_id
    directory.resolve().relative_to((store.ROOT / ".oppday-work").resolve())
    directory.resolve().relative_to((store.WORK / "markdown-imports").resolve())
    return directory


def check_authorization(authorization: dict, import_id: str, quarter: str) -> None:
    require(authorization.get("action") == ACTION
            and authorization.get("importId") == import_id
            and authorization.get("quarter") == quarter
            and authorization.get("preserveOriginals") is True
            and authorization.get("preserveHistory") is True
            and authorization.get("revoked") is not True
            and bool(authorization.get("userRequest")),
            "Explicit current Markdown-only import authorization is required")


def addition_event_date(authorization: dict, quarter: str) -> str | None:
    if "additionEventDate" not in authorization:
        return None
    selected = authorization["additionEventDate"]
    require(quarter == "3Q69" and isinstance(selected, str)
            and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", selected) is not None,
            "Date-scoped Markdown intake requires a 3Q69 ISO event date")
    date.fromisoformat(selected)
    return selected


def verify_scheduled_status_hash(quarter: str, authorization: dict) -> None:
    policy = authorization.get('sourceAliasPolicy')
    if policy in ('3q69-scheduled-verified-youtube-autocaption-v2',
                  '3q69-manual-date-scoped-verified-autocaption-v2'):
        require(quarter == '3Q69', 'Automatic autocaption policy is limited to 3Q69')
        if policy == '3q69-manual-date-scoped-verified-autocaption-v2':
            require(addition_event_date(authorization, quarter) is not None,
                    'Manual autocaption evidence requires an authorized addition date')
        return
    if policy in ('3q69-scheduled-verified-youtube-autocaption-v1',
                  '3q69-manual-date-scoped-verified-autocaption-v1'):
        require(quarter == '3Q69', 'Automatic autocaption policy is limited to 3Q69')
        if policy == '3q69-manual-date-scoped-verified-autocaption-v1':
            require(addition_event_date(authorization, quarter) is not None,
                    'Manual autocaption evidence requires an authorized addition date')
        path = summary_root(quarter).parent / f'workflow_status_{quarter}.csv'
        require(path.is_file() and store.sha256(path) == authorization.get('sourceAliasStatusSha256'),
                'Autocaption workflow status changed since admission')


def summary_root(quarter: str) -> Path:
    require(bool(re.fullmatch(r"[1-4]Q\d{2}", quarter)), "Invalid Markdown import quarter")
    profile = store.read_json(store.PROFILE)
    return Path(profile["oppdayRoot"]) / quarter / "Oppday" / server.SUMMARY_DIR_NAME


def read_markdown(path: Path, ticker: str, quarter: str) -> tuple[str, str]:
    before = path.stat()
    data = path.read_bytes()
    text = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    require(bool(text.strip()) and "\x00" not in text and "\ufffd" not in text,
            "Markdown is empty or has invalid text")
    descriptive_suffix = (r"(?:\s+—\s+YouTube autocaption)?"
                          if path.name == f"{ticker}-Earning call-{quarter}-YouTube-autocaption.md" else "")
    require(bool(re.match(rf"^#\s+{re.escape(ticker)}\s+Earning call\s+{quarter}{descriptive_suffix}\s*$",
                          text.splitlines()[0], re.IGNORECASE)),
            f"Markdown heading differs from its ticker/quarter: {path}")
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
            "Markdown changed while being read")
    return hashlib.sha256(data).hexdigest(), text


def accepted_source_aliases(job: dict) -> list[dict]:
    aliases = job.get("sourceAliases", [])
    if "additionEventDate" not in job:
        return aliases
    accepted_sources = {Path(entry["originalPath"]).resolve() for entry in job["entries"]
                        if entry["disposition"] in ("add", "preserve_existing")}
    return [alias for alias in aliases
            if alias_summary_path(job["quarter"], alias).resolve() in accepted_sources]


def source_aliases(quarter: str, authorization: dict | None = None) -> list[dict]:
    """Inherit only hash-bound accepted aliases, plus explicit current exceptions."""
    inherited = []
    if store.CURRENT.exists():
        release = store.release_directory(store.current_pointer()["releaseId"])
        manifest_path = release / "manifest.json"
        if manifest_path.exists():
            manifest = store.read_json(manifest_path)
            import_id = manifest.get("markdownImportId")
            if import_id:
                directory = import_directory(import_id)
                job = store.read_json(directory / "import.json")
                proof = manifest["markdownImportVerification"]
                require(store.sha256(directory / "import.json") == proof["requestSha256"]
                        and store.sha256(directory / "authorization.json") == proof["authorizationSha256"],
                        "Accepted source alias evidence changed")
                if job["quarter"] == quarter:
                    inherited = accepted_source_aliases(job)
    result = {}
    for alias in inherited + (authorization or {}).get("sourceAliases", []):
        require(set(alias) in ({"ticker", "eventDate", "filename", "sha256"},
                               {"ticker", "eventDate", "filename", "sha256", "nestedEvent"}), "Invalid source alias fields")
        ticker, name = alias["ticker"], alias["filename"]
        require(bool(re.fullmatch(r"[A-Z0-9&.\-]+", ticker))
                and ticker not in ('.', '..')
                and Path(name).name == name and "/" not in name and "\\" not in name
                and Path(name).suffix == ".md" and bool(re.fullmatch(r"[a-f0-9]{64}", alias["sha256"])),
                "Invalid source alias identity")
        date.fromisoformat(alias["eventDate"])
        if "nestedEvent" in alias:
            event = alias["nestedEvent"]
            match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-(\d+)-([A-Za-z0-9-]+)", event)
            require(match is not None and match[1] == alias["eventDate"], "Invalid nested alias event")
        key = (ticker, alias["eventDate"])
        require(key not in result or result[key] == alias, "Conflicting source alias")
        result[key] = alias
    return sorted(result.values(), key=lambda alias: (alias["eventDate"], alias["ticker"]))


def alias_summary_path(quarter: str, alias: dict) -> Path:
    root = summary_root(quarter)
    ticker, name = alias['ticker'], alias['filename']
    require(bool(re.fullmatch(r'[A-Z0-9&.\-]+', ticker)) and ticker not in ('.', '..')
            and Path(name).name == name and '/' not in name and '\\' not in name,
            'Invalid source alias identity')
    date.fromisoformat(alias['eventDate'])
    event_root = root / alias['eventDate']
    require(event_root.resolve().is_relative_to(root.resolve()), 'Summary event escapes summary root')
    if "nestedEvent" in alias:
        match = re.fullmatch(r'(\d{4}-\d{2}-\d{2})-(\d+)-([A-Za-z0-9-]+)', alias['nestedEvent'])
        require(match is not None and match[1] == alias['eventDate'], 'Invalid nested alias event')
        path = event_root / ticker / alias['nestedEvent'] / name
    else:
        path = event_root / name
    require(path.resolve().is_relative_to(event_root.resolve()), 'Summary alias escapes event root')
    return path


def alias_for(path: Path, quarter: str, aliases: list[dict]) -> dict | None:
    root = summary_root(quarter)
    return next((alias for alias in aliases
                 if path.resolve() == alias_summary_path(quarter, alias).resolve()), None)


def source_metadata(path: Path, quarter: str, aliases: list[dict], status_row=None) -> dict:
    alias = alias_for(path, quarter, aliases)
    identity = path.with_name(f"{alias['ticker']}-Earning call-{quarter}.md") if alias else path
    meta = server.detect_current_file(identity, quarter, summary_root(quarter), status_row)
    require(meta is not None, "Unapproved Markdown filename")
    return meta


def verify_alias_sources(quarter: str, alias: dict) -> None:
    root = summary_root(quarter)
    summary = alias_summary_path(quarter, alias)
    primary = (root.parent / summary.relative_to(root)) if 'nestedEvent' in alias else root.parent / alias['eventDate'] / alias['ticker'] / alias['filename']
    event_root = root.parent / alias['eventDate']
    stock_root = event_root / alias['ticker']
    require(event_root.resolve().is_relative_to(root.parent.resolve())
            and stock_root.resolve().is_relative_to(event_root.resolve())
            and primary.resolve().is_relative_to(stock_root.resolve()), 'Primary alias escapes stock root')
    standard = f"{alias['ticker']}-Earning call-{quarter}.md"
    summary_event = root / alias['eventDate']
    sources = [(summary, summary_event), (primary, stock_root)]
    sources += [(p, allowed) for p, allowed in ((summary.with_name(standard), summary_event),
                                                  (primary.with_name(standard), stock_root)) if p.exists()]
    for source, allowed in sources:
        require(source.resolve().is_relative_to(allowed.resolve()), 'Source alias escapes its event or stock root')
        require(store.sha256(source) == alias['sha256'], 'Source alias hash changed or copies differ')
        read_markdown(source, alias['ticker'], quarter)


def discover(quarter: str, aliases: list[dict] | None = None) -> list[Path]:
    root = summary_root(quarter)
    paths = sorted(root.rglob(f"*-Earning call-{quarter}.md"))
    aliases = source_aliases(quarter) if aliases is None else aliases
    approved_paths = {alias_summary_path(quarter, alias).resolve() for alias in aliases}
    unexpected = sorted(path for path in root.rglob(f"*-Earning call-{quarter}*.md")
                        if not path.name.endswith(f"-Earning call-{quarter}.md")
                        and path.resolve() not in approved_paths)
    require(not unexpected, "Unapproved Earning call filenames: " + "; ".join(map(str, unexpected)))
    for alias in aliases:
        path = alias_summary_path(quarter, alias)
        canonical = path.with_name(f"{alias['ticker']}-Earning call-{quarter}.md")
        require(path != canonical, "Source alias must use a nonstandard filename")
        verify_alias_sources(quarter, alias)
        # A later standard-named copy may coexist only with the exact approved
        # bytes. Keep the bound original and its one stable reader identity.
        if canonical in paths:
            paths.remove(canonical)
        paths.append(path)
    require(bool(paths), "No Earning call Markdown files found")
    return sorted(paths)


REGISTRATION_PATTERN = r"(?:\bSET[ \t]+(?:registration|ทะเบียน)|ทะเบียน[ \t]+SET)[ \t]+(\d+)\b"
ALIAS_REGISTRATION_PATTERN = r"(?:\bSET[ \t]+(?:registration|ทะเบียน)|ทะเบียน(?:[ \t]+SET)?)[ \t]+(\d+)\b"


def autocaption_header_event_dates(text: str) -> set[str]:
    """Read explicitly labelled event dates, excluding fiscal-period dates."""
    months = {name: i for i, name in enumerate(('มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
              'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม'), 1)}
    label = re.compile(r'\bSET[ \t]+Opportunity[ \t]+Day\b|\bOppday\b|\bEvent[ \t]+date\b|'
                       r'\bEarnings[ \t]+Call\b|นำเสนอ', re.I)
    date_pattern = re.compile(r'[ \t]*(?::[ \t]*)?(?:วันที่[ \t]*)?'
                              r'(?:(\d{4}-\d{2}-\d{2})|(\d{1,2})[ \t]+('
                              + '|'.join(months) + r')[ \t]+(\d{4}))(?!\d)')
    result = set()
    for line in text.splitlines()[:8]:
        for match in label.finditer(line):
            value = date_pattern.match(line, match.end())
            require(value is not None, "Autocaption event date label has no valid date")
            require(not re.match(r'[ \t]*(?:ถึง|และ|to|and|[-–—/,;&])[ \t]*\d', line[value.end():], re.I),
                    "Autocaption event date must not be a range or multiple dates")
            if value[1]:
                result.add(date.fromisoformat(value[1]).isoformat())
            else:
                year = int(value[4])
                result.add(date(year - 543 if year >= 2400 else year,
                                months[value[3]], int(value[2])).isoformat())
    return result


def source_event(path: Path, quarter: str, ticker: str) -> str:
    """Accept the standard dated path or an explicitly identified nested event."""
    parts = path.relative_to(summary_root(quarter)).parts
    require(len(parts) in (2, 4), "Markdown must be in a dated event folder")
    event = parts[0]
    date.fromisoformat(event)
    if len(parts) == 4:
        require(parts[1] == ticker, "Nested event ticker folder differs")
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-(\d+)-([A-Za-z0-9-]+)", parts[2])
        require(match is not None and match[1] == event, "Nested event identity differs")
        _, text = read_markdown(path, ticker, quarter)
        header = '\n'.join(text.splitlines()[:10])
        # Do not mistake company registration or an ordinary mention of
        # registration for an event identifier. Retain standalone numeric
        # references as conflicts when a SET identifier is also present.
        explicit = r'(?:\bSET[ \t]+(?:registration|ทะเบียน)|(?<![ก-๙])ทะเบียน[ \t]+SET)'
        standalone = r'(?<![ก-๙])ทะเบียน(?:[ \t]+SET)?'
        registrations = set(re.findall(explicit + r'[ \t]+(\d+)\b', header, re.I))
        all_registrations = set(re.findall(r'(?:' + explicit + '|' + standalone + r')[ \t]+(\d+)\b', header, re.I))
        markers = re.search(explicit, header, re.I)
        # A unique nested folder can identify a source even when its report
        # omits a registration.  If a number is printed it must agree; cases
        # with multiple same-day events retain the stricter checks below.
        require(not markers or registrations == all_registrations == {match[2]},
                "Nested event registration differs from Markdown")
    return event


def accepted_event_keys(quarter: str) -> set[tuple[str, str]]:
    release = store.release_directory(store.current_pointer()['releaseId'])
    index = store.read_json(release / 'public/data/index.json')
    return {(item['symbol'], item['eventDate']) for item in index['items'] if item.get('quarter') == quarter}


def discover_scheduled_autocaption_aliases(quarter: str, *, require_workflow_registration: bool = True) -> list[dict]:
    """Bind the specifically authorized 3Q69 filename variant to source bytes.

    This is called only by the scheduled admission path. Generic imports still
    require explicit aliases, and previously accepted hashes are never renewed.
    """
    require(quarter == "3Q69", "Automatic autocaption policy is limited to 3Q69")
    root = summary_root(quarter)
    aliases = source_aliases(quarter)
    for alias in aliases:
        verify_alias_sources(quarter, alias)
    known = {(a['ticker'], a['eventDate']): a for a in aliases}
    known_paths = {alias_summary_path(quarter, a).resolve() for a in aliases}
    status = (server.read_workflow_status(root.parent / f"workflow_status_{quarter}.csv")
              if require_workflow_registration else None)
    accepted = accepted_event_keys(quarter)
    pattern = re.compile(rf"([A-Z0-9&.\-]+)-Earning call-{quarter}-YouTube-autocaption\.md")
    for path in sorted(root.rglob(f"*-Earning call-{quarter}-YouTube-autocaption.md")):
        if path.resolve() in known_paths:
            continue
        match = pattern.fullmatch(path.name)
        require(match is not None, "Invalid autocaption filename")
        ticker = match[1]
        event = source_event(path, quarter, ticker)
        require((ticker, event) not in known, "Conflicting automatic alias for the same ticker and event date")
        require((ticker, event) not in accepted, "Cannot automatically rebind an accepted event to a new source filename")
        digest, text = read_markdown(path, ticker, quarter)
        dates = autocaption_header_event_dates(text)
        require(dates == {event}, "Autocaption event date missing or differs from Markdown header")
        if require_workflow_registration:
            rows = [row for row in status['by_ticker'].get(ticker, []) if row['_event_date'] == event]
            registrations = set(re.findall(ALIAS_REGISTRATION_PATTERN,
                                           '\n'.join(text.splitlines()[:10]), re.I))
            require(len(registrations) == 1, "Autocaption header needs one event registration")
            registration = next(iter(registrations))
            require(len([row for row in rows if row['_registration_id'] == registration]) == 1,
                    "Autocaption event registration missing, ambiguous or differs from workflow status")
        alias = {'ticker': ticker, 'eventDate': event, 'filename': path.name, 'sha256': digest}
        parts = path.relative_to(root).parts
        if len(parts) == 4:
            alias['nestedEvent'] = parts[2]
        require(path.resolve() == alias_summary_path(quarter, alias).resolve(), "Autocaption source path differs")
        verify_alias_sources(quarter, alias)
        aliases.append(alias)
        known[(ticker, event)] = alias
        known_paths.add(path.resolve())
    return sorted(aliases, key=lambda a: (a['eventDate'], a['ticker']))


def event_registration(text: str) -> str:
    # The identifying header, not incidental references later in a report.
    header = "\n".join(text.splitlines()[:8])
    matches = set(re.findall(REGISTRATION_PATTERN, header, re.I))
    all_matches = set(re.findall(ALIAS_REGISTRATION_PATTERN, header, re.I))
    require(len(matches) == 1 and matches == all_matches, "Same-day events require one header registration")
    return next(iter(matches))


def registered_event_id(quarter: str, ticker: str, event_date: str, registration: str) -> str:
    require(bool(re.fullmatch(r"\d+", registration)), "Invalid event registration")
    return server.item_id([quarter, quarter, ticker, event_date,
                           f"{ticker}-Earning call-{quarter}", "event-registration-v1", registration])


def create_request(import_id: str, quarter: str, authorization: dict, *, expected_inventory: dict | None = None) -> dict:
    directory = import_directory(import_id)
    require(not directory.exists(), "Use a new immutable Markdown import ID")
    check_authorization(authorization, import_id, quarter)
    selected_date = addition_event_date(authorization, quarter)
    verify_scheduled_status_hash(quarter, authorization)
    root = summary_root(quarter)
    previous_id = store.current_pointer()["releaseId"]
    previous = store.release_directory(previous_id)
    index_path = previous / "public/data/index.json"
    baseline = store.read_json(index_path)
    baseline_by_id = {item["id"]: item for item in baseline["items"]}
    status = server.read_workflow_status(root.parent / f"workflow_status_{quarter}.csv")
    independent_sources = authorization.get('sourceAliasPolicy') in (
        '3q69-scheduled-verified-youtube-autocaption-v2',
        '3q69-manual-date-scoped-verified-autocaption-v2')
    if independent_sources:
        require(quarter == '3Q69', 'Automatic autocaption policy is limited to 3Q69')
    aliases = source_aliases(quarter, authorization)
    entries = []
    paths = discover(quarter, aliases)
    cohorts = {}
    for path in paths:
        meta = source_metadata(path, quarter, aliases)
        cohorts.setdefault((meta['symbol'], meta['eventDate']), []).append(path)
    for path in paths:
        match = re.fullmatch(rf"([A-Z0-9&.\-]+)-Earning call-{quarter}", path.stem)
        alias = alias_for(path, quarter, aliases)
        require(match is not None or alias is not None, "Invalid Earning call Markdown filename")
        ticker = alias["ticker"] if alias else match[1]
        event_date = source_event(path, quarter, ticker)
        digest, text = read_markdown(path, ticker, quarter)
        cohort = cohorts[(ticker, event_date)]
        candidates = [r for r in status['by_ticker'].get(ticker, []) if r['_event_date'] == event_date]
        registration = None
        if len(cohort) > 1 or (len(candidates) > 1 and not independent_sources):
            registration = event_registration(text)
            if len(path.relative_to(root).parts) == 4:
                require(path.parent.name.split('-')[3] == registration,
                        "Nested event registration differs from header")
            matches = [r for r in candidates if r['_registration_id'] == registration]
            require(len(matches) == 1, "Same-day event registration has missing or ambiguous workflow status")
            row = matches[0]
        elif independent_sources:
            # Workflow metadata is optional and is used only when unambiguous
            # for this exact ticker and date; never borrow another event's row.
            row = candidates[0] if len(candidates) == 1 else None
        else:
            row = server.find_workflow_row(status, ticker, event_date)
        meta = source_metadata(path, quarter, aliases, row)
        groups = {}
        server.add_group(groups, meta, path)
        item = next(iter(groups.values()))
        legacy_id = item['id']
        # Preserve a previously accepted event-bound ID even after the cohort changes.
        if registration is None:
            header_text = "\n".join(text.splitlines()[:8])
            headers = set(re.findall(REGISTRATION_PATTERN, header_text, re.I))
            all_headers = (headers if independent_sources else
                           set(re.findall(ALIAS_REGISTRATION_PATTERN, header_text, re.I)))
            require(not headers or headers == all_headers and len(headers) == 1,
                    "Header event registration is ambiguous")
            registration = next(iter(headers)) if headers else None
        event_id = registered_event_id(quarter, ticker, event_date, registration) if registration else None
        if event_id in baseline_by_id:
            item['id'] = event_id
        elif len(cohort) > 1:
            legacy_text = None
            if legacy_id in baseline_by_id:
                legacy_text = store.read_json(previous / 'public/data/items' / f'{legacy_id}.json')['item'].get('markdown')
            if legacy_text is not None:
                use_legacy = legacy_text == static.redact_local_paths(text)
            else:
                standard = [p for p in cohort if len(p.relative_to(root).parts) == 2]
                use_legacy = path == (standard[0] if len(standard) == 1 else sorted(cohort)[0])
            if not use_legacy:
                item['id'] = event_id
        disposition = "defer" if selected_date and event_date != selected_date else "add"
        payload_sha = None
        if item["id"] in baseline_by_id:
            payload_path = previous / "public/data/items" / f"{item['id']}.json"
            accepted = store.read_json(payload_path)["item"]
            require(accepted.get("markdown") == static.redact_local_paths(text),
                    "Existing accepted Markdown differs; history cannot be overwritten")
            disposition, payload_sha = "preserve_existing", store.sha256(payload_path)
        entries.append({"itemId": item["id"], "ticker": ticker, "quarter": quarter,
                        "eventDate": item["eventDate"], "runId": item["runId"],
                        "registrationId": item["registrationId"], "workflowStatus": item["workflowStatus"],
                        "originalPath": str(path), "sha256": digest, "disposition": disposition,
                        "baselinePayloadSha256": payload_sha})
        if item['id'] != legacy_id:
            entries[-1]['identityScheme'] = 'event-registration-v1'
    require(len({entry['itemId'] for entry in entries}) == len(entries),
            "Multiple events share a ticker and date; distinct identity required")
    for (ticker, event_date), cohort in cohorts.items():
        if len(cohort) > 1:
            same = [e for e in entries if (e['ticker'], e['eventDate']) == (ticker, event_date)]
            require(len({e['registrationId'] for e in same}) == len(same),
                    'Same-day events have duplicate registrations')
            legacy = server.item_id([quarter, quarter, ticker, event_date, f'{ticker}-Earning call-{quarter}'])
            require(legacy not in baseline_by_id or any(e['itemId'] == legacy for e in same),
                    'Existing accepted Markdown differs; history cannot be overwritten')
    job = {"schemaVersion": 1, "kind": "existing-earning-call-markdown-import",
           "importId": import_id, "quarter": quarter, "createdAt": datetime.now(timezone.utc).isoformat(),
           "baseReleaseId": previous_id, "baseIndexSha256": store.sha256(index_path), "entries": entries,
           "pdfValidation": "not_requested", "semanticValidation": "not_recertified_existing_source"}
    if selected_date is not None:
        job["additionEventDate"] = selected_date
    same_day = [e for e in entries if len(cohorts[(e['ticker'], e['eventDate'])]) > 1]
    if same_day:
        job['sameDayWorkflowRows'] = [
            {k: e[k] for k in ('ticker', 'eventDate', 'registrationId', 'runId', 'workflowStatus')}
            for e in same_day]
    if aliases:
        job["sourceAliases"] = aliases
    if expected_inventory is not None:
        require({entry['originalPath']: entry['sha256'] for entry in entries} == expected_inventory,
                'Source inventory changed during admission')
    verify_scheduled_status_hash(quarter, authorization)
    directory.mkdir(parents=True)
    store.write_json_atomic(directory / "authorization.json", authorization)
    store.write_json_atomic(directory / "import.json", job)
    return job


def load_request(import_id: str, *, require_complete_inventory: bool = True) -> tuple[dict, dict, list[tuple[dict, str]]]:
    directory = import_directory(import_id)
    job = store.read_json(directory / "import.json")
    require(job.get("schemaVersion") == 1 and job.get("kind") == "existing-earning-call-markdown-import"
            and job.get("importId") == import_id, "Markdown import identity differs")
    authorization = store.read_json(directory / "authorization.json")
    check_authorization(authorization, import_id, job["quarter"])
    selected_date = addition_event_date(authorization, job["quarter"])
    require(job.get("additionEventDate") == selected_date
            and ("additionEventDate" in job) == (selected_date is not None),
            "Requested Markdown addition date differs from authorization")
    if require_complete_inventory:
        verify_scheduled_status_hash(job['quarter'], authorization)
    require(job.get("pdfValidation") == "not_requested"
            and job.get("semanticValidation") == "not_recertified_existing_source",
            "An MD import cannot claim report/PDF QA")
    base = store.release_directory(job["baseReleaseId"])
    require(store.sha256(base / "public/data/index.json") == job["baseIndexSha256"], "Import baseline changed")
    baseline = store.read_json(base / "public/data/index.json")
    baseline_by_id = {item["id"]: item for item in baseline["items"]}
    root = summary_root(job["quarter"])
    entries = job["entries"]
    aliases = job.get("sourceAliases", [])
    # Each exception must be explicitly approved or inherited from this request's baseline.
    approved = list(authorization.get("sourceAliases", []))
    base_manifest = base / "manifest.json"
    if base_manifest.exists():
        prior_import = store.read_json(base_manifest).get("markdownImportId")
        if prior_import:
            approved += accepted_source_aliases(store.read_json(import_directory(prior_import) / "import.json"))
    require(all(alias in approved for alias in aliases), "Unapproved source alias")
    require(bool(entries) and len({entry["itemId"] for entry in entries}) == len(entries),
            "Missing or duplicate Markdown import entries")
    groups = {}
    for entry in entries:
        groups.setdefault((entry['ticker'], entry['eventDate']), []).append(entry)
    duplicate_entries = [e for group in groups.values() if len(group) > 1 for e in group]
    if duplicate_entries:
        fields = ('ticker', 'eventDate', 'registrationId', 'runId', 'workflowStatus')
        captured = job.get('sameDayWorkflowRows', [])
        require(len(captured) == len(duplicate_entries)
                and sorted(tuple(r.get(k) for k in fields) for r in captured)
                == sorted(tuple(e.get(k) for k in fields) for e in duplicate_entries),
                'Same-day workflow evidence differs')
        for group in groups.values():
            if len(group) > 1:
                require(len({e['registrationId'] for e in group}) == len(group),
                        'Same-day events have duplicate registrations')
        if require_complete_inventory:
            status = server.read_workflow_status(root.parent / f"workflow_status_{job['quarter']}.csv")
            for entry in duplicate_entries:
                rows = [r for r in status['by_ticker'].get(entry['ticker'], [])
                        if r['_event_date'] == entry['eventDate']
                        and r['_registration_id'] == entry['registrationId']]
                require(len(rows) == 1 and rows[0]['_run_id'] == entry['runId']
                        and rows[0]['_conclusion_status'] == entry['workflowStatus'],
                        'Same-day workflow status differs or is ambiguous')
    if require_complete_inventory:
        require({path.resolve() for path in discover(job["quarter"], aliases)}
                == {Path(entry["originalPath"]).resolve() for entry in entries},
                "Markdown cohort changed; prepare a new import request")
    checked = []
    for entry in entries:
        ticker = entry["ticker"]
        require(bool(re.fullmatch(r"[A-Z0-9&.\-]+", ticker)) and entry["quarter"] == job["quarter"],
                "Markdown ticker/quarter differs")
        date.fromisoformat(entry["eventDate"])
        if entry["itemId"] in baseline_by_id:
            require(entry["disposition"] == "preserve_existing", "MD imports cannot replace history")
        else:
            require(entry["baselinePayloadSha256"] is None, "New Markdown cannot carry an accepted payload hash")
            expected_disposition = "defer" if selected_date and entry["eventDate"] != selected_date else "add"
            require(entry["disposition"] == expected_disposition,
                    "Markdown disposition differs from its authorized addition date")
            if expected_disposition == "defer" and not require_complete_inventory:
                # The immutable request binds the inventory observed at preparation;
                # unpublished sources are not dependencies of the accepted release.
                continue
        canonical = root / entry["eventDate"] / f"{ticker}-Earning call-{job['quarter']}.md"
        source = Path(entry["originalPath"])
        alias = alias_for(source, job['quarter'], aliases)
        canonical.resolve().relative_to(root.resolve())
        require(source.resolve().is_relative_to(root.resolve()), "Markdown source escapes summary root")
        require(source_event(source, job["quarter"], ticker) == entry["eventDate"], "Event date differs")
        expected_name = alias["filename"] if alias else canonical.name
        require(source.name == expected_name, "Noncanonical Markdown filename")
        if alias:
            require(source.resolve() == alias_summary_path(job['quarter'], alias).resolve(), "Noncanonical alias source")
        expected_id = server.item_id([job["quarter"], job["quarter"], ticker, entry["eventDate"], canonical.stem])
        scheme = entry.get('identityScheme')
        require(scheme in (None, 'event-registration-v1'), 'Unknown Markdown identity scheme')
        if scheme:
            _, identity_text = read_markdown(source, ticker, job['quarter'])
            registration = event_registration(identity_text)
            require(entry['registrationId'] == registration, 'Event registration metadata differs')
            expected_id = registered_event_id(job['quarter'], ticker, entry['eventDate'], registration)
        require(entry["itemId"] == expected_id, "Markdown record ID differs")
        digest, text = read_markdown(source, ticker, job["quarter"])
        if len(groups[(ticker, entry['eventDate'])]) > 1:
            require(event_registration(text) == entry['registrationId'],
                    'Same-day event registration metadata differs')
        if alias:
            verify_alias_sources(job['quarter'], alias)
        require(digest == entry["sha256"], "Original Markdown hash changed")
        if entry["disposition"] == "preserve_existing":
            payload = base / "public/data/items" / f"{entry['itemId']}.json"
            require(store.sha256(payload) == entry["baselinePayloadSha256"]
                    and store.read_json(payload)["item"].get("markdown") == static.redact_local_paths(text),
                    "Accepted historical Markdown differs")
        checked.append((entry, text))
    return job, baseline, checked


def select_items(import_id: str) -> list[dict]:
    job, _, checked = load_request(import_id)
    items = []
    for entry, _ in checked:
        if entry["disposition"] != "add":
            continue
        path = Path(entry["originalPath"])
        meta = source_metadata(path, entry["quarter"], job.get("sourceAliases", []))
        meta.update({key: entry[key] for key in ("runId", "registrationId", "workflowStatus")})
        groups = {}
        server.add_group(groups, meta, path)
        item = next(iter(groups.values()))
        item['id'] = entry['itemId']
        item.update(primaryMarkdownId=item["files"][0]["id"], primaryPdfId=None)
        items.append(item)
    return items


def verify_import(import_id: str, items: list[dict], *, require_complete_inventory: bool = True) -> dict:
    job, _, checked = load_request(import_id, require_complete_inventory=require_complete_inventory)
    expected = {entry["itemId"]: entry for entry, _ in checked if entry["disposition"] == "add"}
    require(len(items) == len(expected) and {item["id"] for item in items} == set(expected),
            "Markdown import selection differs")
    for item in items:
        entry = expected[item["id"]]
        require(all(item.get(key) == entry[key] for key in ("quarter", "eventDate", "runId", "registrationId", "workflowStatus"))
                and item["symbol"] == entry["ticker"], "Imported Markdown metadata differs")
        files = item["files"]
        require(len(files) == 1 and files[0]["extension"] == ".md" and not item["hasPdf"]
                and item["primaryPdfId"] is None and item["hasMarkdown"] is True
                and item["primaryMarkdownId"] == files[0]["id"], "MD-only imports cannot include PDFs or other files")
        file = files[0]
        original = Path(entry["originalPath"])
        require(file["id"] == server.file_id(original) and file["name"] == original.name
                and store.sha256(Path(file["path"])) == entry["sha256"], "Imported Markdown bytes/identity differ")
    directory = import_directory(import_id)
    return {"pass": True, "kind": "explicit-existing-markdown-import", "importId": import_id,
            "authorizationSha256": store.sha256(directory / "authorization.json"),
            "requestSha256": store.sha256(directory / "import.json"),
            "cohortItemIds": sorted(entry["itemId"] for entry, _ in checked if entry["disposition"] != "defer"),
            "selectedItemIds": sorted(expected), "baseReleaseId": job["baseReleaseId"],
            "pdfValidation": "not_requested", "semanticValidation": "not_recertified_existing_source"}


def verify_prepared_release(release_id: str, manifest: dict) -> dict:
    directory = store.release_directory(release_id)
    proof = manifest["markdownImportVerification"]
    selected = manifest["selectedItemIds"]
    local = store.read_json(directory / "index.local.json")
    items = [item for item in local["items"] if item["id"] in selected]
    # Later arrivals belong to another request, not this immutable release or rollback.
    current = verify_import(manifest["markdownImportId"], items, require_complete_inventory=False)
    require(current == proof and current["selectedItemIds"] == sorted(selected)
            and current["baseReleaseId"] == manifest["previousReleaseId"],
            "Markdown import evidence changed; prepare a new release ID")
    base = store.release_directory(current["baseReleaseId"])
    baseline = store.read_json(base / "public/data/index.json")
    candidate = store.read_json(directory / "public/data/index.json")
    candidate_by_id = {item["id"]: item for item in candidate["items"]}
    for old in baseline["items"]:
        require(candidate_by_id.get(old["id"]) == old, "Markdown import changed historical metadata")
        name = f"{old['id']}.json"
        require(store.sha256(base / "public/data/items" / name)
                == store.sha256(directory / "public/data/items" / name), "Markdown import changed a historical payload")
    require(set(candidate_by_id) == {item["id"] for item in baseline["items"]} | set(selected),
            "Markdown import added unexpected records")
    return current


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-id", required=True)
    parser.add_argument("--quarter", required=True)
    parser.add_argument("--authorization-file", type=Path, required=True)
    args = parser.parse_args()
    from scripts.release_snapshot import release_lock
    with release_lock():
        job = create_request(args.import_id, args.quarter, store.read_json(args.authorization_file))
    print(json.dumps(job, ensure_ascii=False))


if __name__ == "__main__":
    main()
