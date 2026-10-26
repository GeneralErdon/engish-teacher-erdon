"""Downloads one model into a Hugging Face cache folder, in a process of its own.

`HfModelFiles` runs `python -m vt_api.adapters.model_download <model_id> <cache_dir>` with
`HF_HUB_DISABLE_XET=1`, and ends the process to cancel the download.
"""

import os
import sys
from pathlib import Path

import huggingface_hub


def main(argv: list[str]) -> int:
    model_id, cache_dir = argv
    if hasattr(os, "nice"):  # not on Windows
        os.nice(10)  # the conversation comes first
    huggingface_hub.snapshot_download(repo_id=model_id, cache_dir=Path(cache_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
