#!/bin/sh
# Starts whisper.cpp's server on the model VT_STT_GPU_MODEL ("org/name/file", as in the Hugging Face
# cache the api shares: /models/models--<org>--<name>/snapshots/<revision>/<file>).
# The api asks the server to load other models later, so this only picks the first one.
# MODELS_ROOT and WHISPER_SERVER exist for the test (services/api/tests/unit/test_stt_gpu_start.py).
set -eu

model="${VT_STT_GPU_MODEL:-ggerganov/whisper.cpp/ggml-small.en-q8_0.bin}"
repo="${model%/*}"
file="${model##*/}"
dir="${MODELS_ROOT:-/models}/models--$(printf '%s' "$repo" | sed 's|/|--|g')"

if [ ! -d "$dir" ]; then
    echo "stt-gpu: $dir not found: the model $model is not downloaded (is ./data/models mounted?)" >&2
    exit 1
fi
# The revision refs/main names, else the first snapshot that has the file, as the api's
# snapshot_path does: a later download of another file may have moved refs/main to a revision this
# file was never fetched under, and the one-shot download does not run again on a restart.
path=""
if [ -r "$dir/refs/main" ]; then
    path="$dir/snapshots/$(cat "$dir/refs/main")/$file"
fi
if [ ! -f "$path" ]; then
    path=""
    for candidate in "$dir"/snapshots/*/"$file"; do
        if [ -f "$candidate" ]; then
            path="$candidate"
            break
        fi
    done
fi
if [ -z "$path" ]; then
    echo "stt-gpu: $file is in no snapshot of $dir: the model $model is not downloaded" >&2
    exit 1
fi

exec "${WHISPER_SERVER:-whisper-server}" --host 0.0.0.0 --port 8080 --request-path /v1 --inference-path /audio/transcriptions -m "$path"
