"""The version /health reports (SPEC-platform): APP_VERSION when set, else the checkout's commit,
read from .git without running git, else "dev"."""

from pathlib import Path

from backend.core.version import git_sha

SHA = "2df19160c5e2a0f6d3b7c94a1e8f2b6d7c0a9e31"


def test_a_branch_checkout_gives_its_commit(tmp_path: Path) -> None:
    (tmp_path / ".git" / "refs" / "heads").mkdir(parents=True)
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / ".git" / "refs" / "heads" / "main").write_text(SHA + "\n")

    assert git_sha(tmp_path) == "2df1916"


def test_a_packed_ref_is_found_too(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / ".git" / "packed-refs").write_text(f"# pack-refs\n{SHA} refs/heads/main\n")

    assert git_sha(tmp_path) == "2df1916"


def test_a_detached_head_is_its_own_commit(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text(SHA + "\n")

    assert git_sha(tmp_path) == "2df1916"


def test_no_checkout_gives_nothing(tmp_path: Path) -> None:
    assert git_sha(tmp_path) is None
