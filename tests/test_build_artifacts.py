import re
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath


def test_sdist_excludes_local_worktree_metadata(tmp_path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--sdist",
            "--outdir",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    (sdist_path,) = tmp_path.glob("*.tar.gz")

    with tarfile.open(sdist_path, mode="r:gz") as archive:
        members = archive.getmembers()
        assert all(".git" not in PurePosixPath(member.name).parts for member in members)

        for member in members:
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            assert extracted is not None
            contents = extracted.read()
            assert re.search(rb"gitdir:\s*(?:/|[A-Za-z]:[\\/])", contents) is None
