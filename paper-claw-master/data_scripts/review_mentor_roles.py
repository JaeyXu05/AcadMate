"""复核 raw 中未核验导师：先用存量主页文本，再只联网刷新仍无法判断的主页。"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

from build_rag import _profile_mentor_role


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = REPO_ROOT / "data" / "ustc_mentors_raw.json"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "mentor_role_overrides.json"
USER_AGENT = "Paper-Claw USTC mentor role review"


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
        elif tag in {"p", "div", "li", "br", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1
        elif tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        lines = [" ".join(html.unescape(x).split()) for x in "".join(self.parts).splitlines()]
        return "\n".join(x for x in lines if x)


def _fetch_visible_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:  # noqa: S310 - URLs come from USTC raw data
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("profile exceeds 2MB")
    parser = _TextParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    return parser.text()


def _snippet(text: str, role: str) -> str:
    match = re.search(rf".{{0,80}}{re.escape(role)}.{{0,100}}", text, re.S)
    return " ".join(match.group(0).split()) if match else role


def main() -> None:
    parser = argparse.ArgumentParser(description="复核未核验导师角色")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--offline", action="store_true", help="只检查存量 profile_text")
    args = parser.parse_args()

    payload = json.loads(args.raw.read_text(encoding="utf-8"))
    pending = [r for r in payload.get("records", []) if not r.get("mentor_role_verified")]
    verified: dict[str, dict] = {}
    unresolved: list[dict] = []

    for record in pending:
        faculty_id = str(record.get("faculty_id") or "")
        name = str(record.get("name") or "")
        profile_url = str(record.get("profile_url") or "")
        text = str(record.get("profile_text") or "")
        role = _profile_mentor_role(name, text)
        source = "stored_official_profile"
        error = ""
        if not role and not args.offline and profile_url:
            try:
                text = _fetch_visible_text(profile_url)
                role = _profile_mentor_role(name, text)
                source = "refreshed_official_profile"
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
            if args.delay:
                time.sleep(args.delay)
        if role:
            verified[faculty_id] = {
                "name": name,
                "mentor_role": role,
                "source": source,
                "source_uri": profile_url,
                "evidence_snippet": _snippet(text, role),
                "confidence": 0.97,
            }
        else:
            unresolved.append({
                "faculty_id": faculty_id,
                "name": name,
                "academic_title": record.get("academic_title") or "",
                "college": record.get("college") or record.get("unit") or "",
                "profile_url": profile_url,
                "error": error,
                "review_status": "pending",
            })
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "USTC official faculty profiles",
        "verified_count": len(verified),
        "unresolved_count": len(unresolved),
        "verified": verified,
        "unresolved": unresolved,
    }
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"导师角色复核：确认 {len(verified)}，待人工 {len(unresolved)}，写入 {args.output}")


if __name__ == "__main__":
    main()
