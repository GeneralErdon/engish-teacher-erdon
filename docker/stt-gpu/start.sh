#!/bin/sh
# Starts whisper.cpp's server on the model VT_STT_GPU_MODEL ("org/name/file", as in the Hugging Face
# cache the api shares: /models/models--<org>--<name>/snapshots/<revision>/<file>).
# The api asks the server to load other models later, so this only picks the first one.
set -eu

model="${VT_STT_GPU_MODEL:-ggerganov/whisper.cpp/ggml-small.en-q8_0.bin}"
repo="${model%/*}"
file="${model##*/}"
dir="/models/models--$(printf '%s' "$repo" | sed 's|/|--|g')"

if [ ! -r "$dir/refs/main" ]; then
    echo "stt-gpu: $dir/refs/main not found: the model $model is not downloaded (is ./data/models mounted?)" >&2
    exit 1
fi
rev="$(cat "$dir/refs/main")"
path="$dir/snapshots/$rev/$file"
if [ ! -f "$path" ]; then
    echo "stt-gpu: $path not found: the model $model is not downloaded" >&2
    exit 1
fi

exec whisper-server --host 0.0.0.0 --port 8080 --request-path /v1 --inference-path /audio/transcriptions -m "$path"
