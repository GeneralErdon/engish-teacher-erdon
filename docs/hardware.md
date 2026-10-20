# Hardware, GPUs and remote access

## What actually needs a GPU?

| Service | GPU needed? | Notes |
|---|---|---|
| `llm` | **Strongly recommended** | The only heavy component. A 12–14B model at Q4 needs ~8–10 GB VRAM. |
| `stt` | Optional | Whisper `large-v3-turbo` is fast on GPU; `small`/`base` run fine on CPU with lower accuracy. |
| `tts` | No | Kokoro (82M params) runs faster than real time on a modern CPU. |
| `pron` | No | wav2vec2 phoneme inference on a few-second clip takes well under a second on CPU. |
| `api`, `ui`, `desktop` | No | |

So "the AMD problem" is really an **LLM (and optionally STT) problem**, not a voice problem. Ollama and llama.cpp only serve text; speech goes through `stt` and `tts`.

## Profiles

| Profile | LLM | STT | Platforms |
|---|---|---|---|
| `cpu` | llama.cpp server (CPU, small model) | Speaches CPU (`small.en`) | All |
| `nvidia` | Ollama (CUDA) | Speaches CUDA (`large-v3-turbo`) | Linux, Windows via WSL2 |
| `amd` | llama.cpp server built with **Vulkan** (`/dev/dri` passed through) | whisper.cpp built with Vulkan (`docker/whisper-vulkan`) or Speaches CPU | **Linux only** |
| `external` | Your native Ollama / LM Studio at `http://host.docker.internal:<port>/v1` | Speaches CPU | macOS, Windows + AMD, anyone who already runs a model server |

### Why not Ollama in Docker for AMD?

You can: `ollama/ollama:rocm` with `/dev/kfd` and `/dev/dri` works on Linux **if** the ROCm version inside the image supports your GPU. RDNA 4 (e.g. RX 9060 XT, `gfx1200`) support depends on the ROCm release, so check AMD's compatibility matrix for your exact card. **Vulkan has no such dependency**, which is why it is the default for the `amd` profile. Do not use `HSA_OVERRIDE_GFX_VERSION` as a workaround: it can load code on unvalidated hardware.

### Why `external` for macOS and Windows + AMD?

- Docker on macOS has **no GPU access**, so run Ollama/LM Studio natively to use Metal.
- Docker on Windows exposes NVIDIA GPUs through WSL2, but **AMD GPUs are not reliably available** inside containers. Run LM Studio (Vulkan backend, works on most AMD cards) or Ollama (if your card is on its supported list) natively on Windows and point voice-tutor at it.

On Linux, the `api` service needs this to reach the host (Docker Desktop adds it automatically; `compose.yaml` already includes it):

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

## Suggested models by VRAM

| VRAM | Chat model (Q4) | STT |
|---|---|---|
| CPU only | 3–4B instruct | `small.en` |
| 8 GB | 7–8B instruct | `large-v3-turbo` |
| 12–16 GB | 12–14B instruct (e.g. Gemma 3 12B, Qwen3 14B or newer equivalents) | `large-v3-turbo` |

Always leave ~2 GB of headroom when STT shares the GPU with the LLM.

## Remote access

Browsers require a **secure context** for `getUserMedia`: `http://localhost` works, `http://192.168.x.x` does not.

**Option A: Caddy with a local CA (LAN)** *(Phase 3, not available yet: the `https` profile is still a TODO in `compose.yaml`)*
```bash
docker compose --profile cpu --profile https up -d
```
Caddy issues a certificate from its internal CA. Install Caddy's root certificate on each client device once (instructions printed in the logs).

**Option B: Tailscale**
```bash
tailscale serve --bg 8080
```
Gives you a valid HTTPS URL inside your tailnet with no certificate setup.

Do not expose voice-tutor to the public internet: it has no authentication.
