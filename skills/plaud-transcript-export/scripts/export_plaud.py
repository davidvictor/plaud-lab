#!/usr/bin/env python3
"""Export Plaud transcripts and summaries through Plaud Web's internal API."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import os
import random
import re
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_BASE = "https://api.plaud.ai"
WEB_ORIGIN = "https://web.plaud.ai"
USER_AGENT = "plaud-lab-export/1.0"


class PlaudExportError(RuntimeError):
    pass


@dataclass
class ExportConfig:
    api_base: str
    auth_token: str | None
    cookie: str | None
    output: Path
    include_trash: str
    limit: int
    skip: int
    delay: float
    timezone: str
    language: str
    device_id: str | None
    pld_user: str | None
    web_origin: str
    metadata_only: bool
    timeout: int


def gzip_or_text(data: bytes) -> str:
    if len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B:
        data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


def random_request_id() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(12))


def normalize_bearer(token: str | None) -> str | None:
    if token is None:
        return None
    token = token.strip()
    if not token:
        return None
    if token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}"


def base_headers(config: ExportConfig) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": USER_AGENT,
        "Origin": config.web_origin,
        "Referer": f"{config.web_origin}/",
        "app-language": config.language,
        "app-platform": "web",
        "edit-from": "web",
        "timezone": config.timezone,
    }
    auth = normalize_bearer(config.auth_token)
    if auth:
        headers["Authorization"] = auth
    if config.cookie:
        headers["Cookie"] = config.cookie
    if config.device_id:
        headers["x-device-id"] = config.device_id
    if config.pld_user:
        headers["x-pld-user"] = config.pld_user
    return headers


def request_json(
    url: str,
    config: ExportConfig,
    *,
    method: str = "GET",
    body: Any | None = None,
) -> dict[str, Any]:
    headers = base_headers(config)
    headers["X-Request-ID"] = random_request_id()
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=config.timeout) as response:
            payload = gzip_or_text(response.read())
    except urllib.error.HTTPError as exc:
        detail = gzip_or_text(exc.read())
        raise PlaudExportError(f"HTTP {exc.code} for {url}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise PlaudExportError(f"Network error for {url}: {exc}") from exc
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PlaudExportError(f"Non-JSON response for {url}: {payload[:500]}") from exc
    if parsed.get("status") not in (None, 0):
        raise PlaudExportError(
            f"Plaud status {parsed.get('status')} for {url}: {parsed.get('msg', '')}"
        )
    return parsed


def download_text(url: str, timeout: int) -> tuple[int | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = getattr(response, "status", None)
            text = gzip_or_text(response.read())
            return status, text
    except urllib.error.HTTPError as exc:
        detail = gzip_or_text(exc.read())
        raise PlaudExportError(f"Artifact HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise PlaudExportError(f"Artifact network error: {exc}") from exc


def slugify(value: str, fallback: str = "untitled") -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return (slug or fallback)[:90]


def iso_from_ms(value: Any) -> str:
    try:
        return dt.datetime.fromtimestamp(int(value) / 1000, tz=dt.UTC).isoformat()
    except Exception:
        return ""


def format_ms(value: Any) -> str:
    try:
        total = int(value) // 1000
    except Exception:
        total = 0
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def sanitize_detail(value: Any) -> Any:
    if isinstance(value, list):
        return [sanitize_detail(item) for item in value]
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if key == "data_link" and isinstance(item, str):
                try:
                    parsed = urllib.parse.urlparse(item)
                    query = urllib.parse.parse_qs(parsed.query)
                    sanitized[key] = {
                        "present": True,
                        "host": parsed.netloc,
                        "path": parsed.path,
                        "expires_seconds": (query.get("X-Amz-Expires") or [""])[0],
                        "signed_at": (query.get("X-Amz-Date") or [""])[0],
                    }
                except Exception:
                    sanitized[key] = {"present": True}
            else:
                sanitized[key] = sanitize_detail(item)
        return sanitized
    return value


def frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for key in (
        "id",
        "title",
        "start_time_utc",
        "duration_ms",
        "duration_text",
        "is_trash",
        "is_trans",
        "is_summary",
        "scene",
        "serial_number",
        "source_url",
    ):
        value = meta.get(key)
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif value is None:
            rendered = "null"
        else:
            rendered = json.dumps(value)
        lines.append(f"{key}: {rendered}")
    lines.extend(["---", ""])
    return "\n".join(lines)


def transcript_markdown(segments: Any) -> str:
    if not isinstance(segments, list):
        return str(segments or "_No transcript content found._\n")
    blocks = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = format_ms(segment.get("start_time") or segment.get("startTime") or 0)
        end = format_ms(segment.get("end_time") or segment.get("endTime") or 0)
        speaker = (
            segment.get("speaker")
            or segment.get("original_speaker")
            or segment.get("speaker_name")
            or "Speaker"
        )
        content = str(segment.get("content") or segment.get("text") or "").strip()
        blocks.append(f"[{start} - {end}] {speaker}: {content}")
    return "\n\n".join(blocks) + ("\n" if blocks else "_No transcript content found._\n")


def outline_markdown(items: Any) -> str:
    if not isinstance(items, list):
        if items:
            return "```json\n" + json.dumps(items, indent=2, ensure_ascii=False) + "\n```\n"
        return "_No outline found._\n"
    lines = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = format_ms(item.get("start_time") or 0)
        end = format_ms(item.get("end_time") or 0)
        topic = item.get("topic") or item.get("title") or ""
        lines.append(f"- [{start} - {end}] {topic}".rstrip())
    return "\n".join(lines) + ("\n" if lines else "_No outline found._\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def list_url(config: ExportConfig) -> str:
    trash_map = {"active": "0", "trash": "1", "all": "2"}
    params = {
        "skip": str(config.skip),
        "limit": str(config.limit),
        "is_trash": trash_map[config.include_trash],
        "sort_by": "start_time",
        "is_desc": "true",
    }
    return f"{config.api_base.rstrip('/')}/file/simple/web?{urllib.parse.urlencode(params)}"


def artifact_basename(data_type: str, parsed: Any) -> str:
    name = slugify(data_type, "artifact")
    extension = "json" if parsed is not None else ("md" if "note" in data_type else "txt")
    return f"{name}.{extension}"


def export(config: ExportConfig) -> dict[str, Any]:
    if not config.auth_token and not config.cookie:
        raise PlaudExportError("Set PLAUD_AUTH_TOKEN or PLAUD_COOKIE, or pass --auth-token/--cookie.")

    export_dir = config.output
    for name in (
        "metadata",
        "files",
        "transcripts",
        "summaries",
        "polished-transcripts",
        "outlines",
        "raw",
    ):
        (export_dir / name).mkdir(parents=True, exist_ok=True)

    file_list = request_json(list_url(config), config)
    files = file_list.get("data_file_list") or []
    write_json(export_dir / "metadata" / "file-list.sanitized.json", file_list)

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    content_counts: dict[str, int] = {}

    for index, item in enumerate(files, start=1):
        file_id = item.get("id")
        if not file_id:
            continue
        title = item.get("filename") or file_id
        start_iso = iso_from_ms(item.get("start_time"))
        slug = f"{start_iso[:10] or 'unknown-date'}-{slugify(title)}-{str(file_id)[:8]}"
        raw_dir = export_dir / "raw" / str(file_id)
        raw_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "id": file_id,
            "title": title,
            "start_time_utc": start_iso,
            "duration_ms": item.get("duration") or 0,
            "duration_text": format_ms(item.get("duration") or 0),
            "is_trash": bool(item.get("is_trash")),
            "is_trans": bool(item.get("is_trans")),
            "is_summary": bool(item.get("is_summary")),
            "scene": item.get("scene"),
            "serial_number": item.get("serial_number"),
            "source_url": f"{config.web_origin}/file/{file_id}",
        }

        row = dict(meta)
        row["slug"] = slug
        try:
            detail_url = f"{config.api_base.rstrip('/')}/file/detail/{file_id}"
            detail = request_json(detail_url, config)
            write_json(raw_dir / "detail.sanitized.json", sanitize_detail(detail))
            write_json(raw_dir / "file-list-entry.json", item)

            original = None
            polished = None
            summary = ""
            outline = None
            artifact_types: list[str] = []

            for content in (detail.get("data") or {}).get("content_list") or []:
                data_type = str(content.get("data_type") or "unknown")
                artifact_types.append(data_type)
                content_counts[data_type] = content_counts.get(data_type, 0) + 1

                metadata = {
                    key: content.get(key)
                    for key in (
                        "data_id",
                        "data_type",
                        "task_status",
                        "err_code",
                        "err_msg",
                        "data_title",
                        "data_tab_name",
                    )
                }
                link = content.get("data_link")
                if isinstance(link, str):
                    parsed_link = urllib.parse.urlparse(link)
                    query = urllib.parse.parse_qs(parsed_link.query)
                    metadata["has_link"] = True
                    metadata["link_host"] = parsed_link.netloc
                    metadata["link_path"] = parsed_link.path
                    metadata["expires_seconds"] = (query.get("X-Amz-Expires") or [""])[0]
                    metadata["signed_at"] = (query.get("X-Amz-Date") or [""])[0]
                else:
                    metadata["has_link"] = False

                parsed_artifact = None
                text_artifact = None
                if not config.metadata_only and link and content.get("task_status") == 1:
                    status, text_artifact = download_text(link, config.timeout)
                    metadata["fetch_status"] = status
                    metadata["byte_length"] = len(text_artifact.encode("utf-8"))
                    try:
                        parsed_artifact = json.loads(text_artifact)
                    except json.JSONDecodeError:
                        parsed_artifact = None
                    if parsed_artifact is not None:
                        write_json(raw_dir / artifact_basename(data_type, parsed_artifact), parsed_artifact)
                    else:
                        write_text(raw_dir / artifact_basename(data_type, parsed_artifact), text_artifact)

                write_json(raw_dir / f"{slugify(data_type, 'artifact')}.metadata.json", metadata)

                artifact_value = parsed_artifact if parsed_artifact is not None else text_artifact
                if data_type == "transaction":
                    original = artifact_value
                elif data_type == "transaction_polish":
                    polished = artifact_value
                elif data_type == "auto_sum_note":
                    summary = text_artifact or ""
                elif data_type == "outline":
                    outline = artifact_value

            fm = frontmatter(meta)
            transcript_body = transcript_markdown(original)
            summary_body = summary or "_No summary content found._\n"
            outline_body = outline_markdown(outline)

            combined = (
                fm
                + f"# {title}\n\n"
                + "## Metadata\n\n"
                + f"- File ID: `{file_id}`\n"
                + f"- Plaud URL: {meta['source_url']}\n"
                + f"- Start time UTC: {meta['start_time_utc']}\n"
                + f"- Duration: {meta['duration_text']}\n"
                + f"- Trash: {meta['is_trash']}\n"
                + f"- Transcript available: {meta['is_trans']}\n"
                + f"- Summary available: {meta['is_summary']}\n\n"
                + f"## Summary\n\n{summary_body}\n\n"
                + f"## Outline\n\n{outline_body}\n\n"
                + f"## Transcript\n\n{transcript_body}"
            )
            write_text(export_dir / "files" / f"{slug}.md", combined)
            write_text(
                export_dir / "transcripts" / f"{slug}.md",
                fm + f"# {title}\n\n## Transcript\n\n{transcript_body}",
            )
            row["file_markdown"] = f"files/{slug}.md"
            row["transcript_markdown"] = f"transcripts/{slug}.md"

            if summary:
                write_text(
                    export_dir / "summaries" / f"{slug}.md",
                    fm + f"# {title}\n\n{summary}",
                )
                row["summary_markdown"] = f"summaries/{slug}.md"
            if polished is not None:
                write_text(
                    export_dir / "polished-transcripts" / f"{slug}.md",
                    fm + f"# {title}\n\n## Polished Transcript\n\n{transcript_markdown(polished)}",
                )
                row["polished_markdown"] = f"polished-transcripts/{slug}.md"
            if outline is not None:
                write_text(
                    export_dir / "outlines" / f"{slug}.md",
                    fm + f"# {title}\n\n## Outline\n\n{outline_body}",
                )
                row["outline_markdown"] = f"outlines/{slug}.md"
            row["content_types"] = "|".join(artifact_types)
        except Exception as exc:
            errors.append({"file_id": str(file_id), "title": str(title), "error": str(exc)})
            row["error"] = str(exc)

        rows.append(row)
        if config.delay and index < len(files):
            time.sleep(config.delay)

    index_payload = {
        "exported_at": dt.datetime.now(dt.UTC).isoformat(),
        "source": list_url(config),
        "file_count": len(files),
        "exported_count": len(rows),
        "errors": errors,
        "content_type_counts": content_counts,
        "files": rows,
    }
    write_json(export_dir / "index.json", index_payload)

    fieldnames = sorted({key for row in rows for key in row})
    with (export_dir / "index.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return index_payload


def parse_args(argv: list[str]) -> ExportConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=os.getenv("PLAUD_API_BASE", API_BASE))
    parser.add_argument("--auth-token", default=os.getenv("PLAUD_AUTH_TOKEN"))
    parser.add_argument("--cookie", default=os.getenv("PLAUD_COOKIE"))
    parser.add_argument("--output", default=os.getenv("PLAUD_OUTPUT"))
    parser.add_argument("--include-trash", choices=("active", "trash", "all"), default="all")
    parser.add_argument("--limit", type=int, default=99999)
    parser.add_argument("--skip", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--timezone", default=os.getenv("PLAUD_TIMEZONE", "UTC"))
    parser.add_argument("--language", default=os.getenv("PLAUD_LANGUAGE", "en"))
    parser.add_argument("--device-id", default=os.getenv("PLAUD_DEVICE_ID"))
    parser.add_argument("--pld-user", default=os.getenv("PLAUD_USER_ID"))
    parser.add_argument("--web-origin", default=os.getenv("PLAUD_WEB_ORIGIN", WEB_ORIGIN))
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args(argv)

    output = args.output
    if not output:
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        output = f"plaud-export-{stamp}"

    return ExportConfig(
        api_base=args.api_base,
        auth_token=args.auth_token,
        cookie=args.cookie,
        output=Path(output),
        include_trash=args.include_trash,
        limit=args.limit,
        skip=args.skip,
        delay=args.delay,
        timezone=args.timezone,
        language=args.language,
        device_id=args.device_id,
        pld_user=args.pld_user,
        web_origin=args.web_origin.rstrip("/"),
        metadata_only=args.metadata_only,
        timeout=args.timeout,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        config = parse_args(sys.argv[1:] if argv is None else argv)
        result = export(config)
    except PlaudExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130

    print(json.dumps({
        "output": str(config.output),
        "file_count": result["file_count"],
        "exported_count": result["exported_count"],
        "error_count": len(result["errors"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
