# Evaluation

The project publishes numbers, not adjectives. Two evaluations feed the README results table.

## 1. Mispronunciation detection

- **Dataset:** [L2-ARCTIC](https://psi.engr.tamu.edu/l2-arctic-corpus/): non-native English speech with manually annotated phone substitutions, deletions and insertions. We report the **Spanish-L1 speakers** first (the primary audience), then all speakers.
- **Task:** for each annotated utterance, score the audio against its prompt text in drill mode.
- **Metrics:** precision, recall and F1 of "mispronounced or missing" at phoneme level; per-phoneme confusion for the 10 most frequent errors.
- **Command:** `just eval-pron /path/to/l2-arctic`.

The dataset is **not** redistributed. The script expects you to download it yourself.

## 2. Latency

- **Setup:** 50 scripted turns replayed from WAV fixtures through the real WebSocket on the reference machine.
- **Metrics (p50 / p95, ms):** VAD end → transcript; transcript → first LLM token; first token → first audio byte; voice-to-voice.
- **Command:** `just eval-latency` (with `VT_PROFILE=amd` in `.env` on the reference machine).

## Reporting

Both scripts write `eval/results/latest.json` (with hardware, model ids, versions and git SHA). `scripts/render_results.py` updates the block between `<!-- results:start -->` and `<!-- results:end -->` in the README. CI checks that the table matches the JSON.

## Licenses

Check before publishing results or images:

| Asset | Check |
|---|---|
| L2-ARCTIC | Research licence terms: do not redistribute audio |
| wav2vec2 phoneme checkpoint | Model card licence (varies by checkpoint) |
| Kokoro-82M | Model card licence |
| Whisper | Model card licence |
| Chat model | Model card licence and acceptable-use policy |
