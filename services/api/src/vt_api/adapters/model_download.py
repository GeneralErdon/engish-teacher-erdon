"""Downloads one model, a repository or one file of it, into a Hugging Face cache folder, in a
process of its own.

`HfModelFiles` runs `python -m vt_api.adapters.model_download <model_id> <cache_dir>` with
`HF_HUB_DISABLE_XET=1`, and ends the process to cancel the download.
"""

import os
import sys
from pathlib import Path

import huggingface_hub

from vt_api.domain.speech import split_model_id


def main(argv: list[str]) -> int:
    model_id, cache_dir = argv
    if hasattr(os, "nice"):  # not on Windows
        os.nice(10)  # the conversation comes first
    repo_id, file = split_model_id(model_id)
    if file is None:
        huggingface_hub.snapshot_download(repo_id=repo_id, cache_dir=Path(cache_dir))
    else:  # one file of a repository whose files are separate models
        huggingface_hub.snapshot_download(
            repo_id=repo_id, cache_dir=Path(cache_dir), allow_patterns=[file]
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
