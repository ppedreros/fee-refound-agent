"""The version `/health` reports (SPEC-platform): `APP_VERSION` when it is set (compose and the
deploy pass it), else the commit of the checkout the app runs from, else "dev".

The commit is read from `.git` directly, without running git.
"""

import re
from pathlib import Path

from backend.core.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
_SHA = re.compile(r"[0-9a-f]{40}")


def app_version(settings: Settings, root: Path = REPO_ROOT) -> str:
    return settings.app_version or git_sha(root) or "dev"


def git_sha(root: Path) -> str | None:
    git = root / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref = head.removeprefix("ref: ")
            loose = git / ref
            if loose.is_file():
                head = loose.read_text(encoding="utf-8").strip()
            else:
                packed = (git / "packed-refs").read_text(encoding="utf-8").splitlines()
                head = next((line.split()[0] for line in packed if line.endswith(f" {ref}")), "")
    except OSError:
        return None
    return head[:7] if _SHA.fullmatch(head) else None
