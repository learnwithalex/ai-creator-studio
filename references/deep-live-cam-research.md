# Deep-Live-Cam Research Notes

## Purpose

This document captures an in-depth review of the [`hacksider/Deep-Live-Cam`](https://github.com/hacksider/Deep-Live-Cam) project and translates its strongest ideas into an implementation blueprint for this codebase.

The goal is not to copy its code directly. The repo is published under **AGPL-3.0**, so copying implementation code into this project would create licensing obligations we likely do not want. We should treat it as a reference design and reimplement the ideas in our own architecture.

## Executive Summary

`Deep-Live-Cam` gets high precision from a **stack of small, compounding engineering decisions**, not from a single magical model.

The biggest takeaways:

1. It uses `InsightFace` correctly and aggressively:
   - `buffalo_l` for detection, recognition, and 106-point landmarks.
   - `inswapper_128` for the actual face swap.

2. It avoids unnecessary work:
   - detection-only path when recognition/landmarks are not needed.
   - skip landmark inference unless the active features actually require it.
   - reuse cached enhancement results between live frames.

3. It improves realism after the swap:
   - better face masks from 106-point landmarks.
   - mouth preservation.
   - optional Poisson blending.
   - color transfer / lighting matching.
   - post-swap sharpening and enhancement.

4. It improves speed with targeted low-level optimizations:
   - FP16 swap model when safe.
   - custom fast paste-back.
   - cached feathered alpha masks.
   - provider-specific tuning.
   - CUDA graph replay.

5. It is architected as a **processor pipeline**, not a monolithic function:
   - analyser
   - face swapper
   - face masking
   - enhancer
   - post-processing
   - mapping/multi-face logic

That architecture is the main lesson for us.

## High-Value Source Files

These are the most relevant files reviewed from the repo:

- README:
  - <https://github.com/hacksider/Deep-Live-Cam/blob/main/README.md>
- Face analyser:
  - <https://github.com/hacksider/Deep-Live-Cam/blob/main/modules/face_analyser.py>
- Frame processor loader:
  - <https://github.com/hacksider/Deep-Live-Cam/blob/main/modules/processors/frame/core.py>
- Face swapper:
  - <https://github.com/hacksider/Deep-Live-Cam/blob/main/modules/processors/frame/face_swapper.py>
- Face masking:
  - <https://github.com/hacksider/Deep-Live-Cam/blob/main/modules/processors/frame/face_masking.py>
- Face enhancer:
  - <https://github.com/hacksider/Deep-Live-Cam/blob/main/modules/processors/frame/face_enhancer.py>

## What Deep-Live-Cam Is Actually Doing

## 1. Correct base model stack

`Deep-Live-Cam` is still fundamentally built on the same family of open models we are using:

- `InsightFace FaceAnalysis`
- `buffalo_l`
- `inswapper_128`

This matters because it means:

- our current direction is not wrong
- the quality gap is mostly in **pipeline quality**, **masking**, **tracking**, **blending**, and **runtime engineering**
- not in replacing `inswapper_128` immediately

## 2. The analyser is smarter than a naive `FaceAnalysis.get()`

One of the most important ideas is in `modules/face_analyser.py`.

### What they do

- initialize `FaceAnalysis` with:
  - `allowed_modules=['detection', 'recognition', 'landmark_2d_106']`
- run a custom `_analyse_faces(frame)` instead of blindly calling `fa.get(frame)`
- only enable `landmark_2d_106` when current features need it

### Why it matters

Not every frame needs:

- embeddings
- 106 landmarks
- full face analysis

For pure face swap, they note landmarks are not always necessary. For features like:

- mouth masking
- enhancement alignment
- richer masks

they do need them.

### Implication for our codebase

Right now our worker treats analysis as a single lump. We should split:

- `detect_faces_fast(frame)`
- `analyse_faces_for_swap(frame)`
- `analyse_faces_for_masking(frame)`
- `analyse_faces_for_enhancement(frame)`

and only pay for the expensive path when needed.

## 3. They have a detection-only fast path

`detect_one_face_fast(frame)` and `detect_many_faces_fast(frame)` exist specifically to skip recognition and landmarks when they are not needed.

### Why it matters

This is one of the cleanest examples of “precision and speed are both architecture problems.”

When you process live video:

- not every stage needs every face attribute
- doing full analysis on every frame is wasted work

### Implication for us

We should introduce:

- a fast tracker/detector pass for every frame
- a slower re-analysis cadence every `N` frames
- landmark/embedding refresh only when:
  - face moved significantly
  - identity changed
  - quality dropped

## 4. They optimize provider behavior per hardware target

This is one of the most advanced parts of the repo.

### What they do

- provider-aware initialization
- Apple Silicon optimization path for the detector
- CoreML partition tuning
- DirectML locking
- CUDA graph replay for swap inference
- FP16 vs FP32 model choice depending on hardware

### Why it matters

They are not treating ONNX Runtime as a black box. They are tuning inference by provider:

- CUDA
- CoreML
- DirectML

### Implication for us

Our current worker is still “generic InsightFace on CUDA/CPU.” To reach Deep-Live-Cam-style precision and throughput, we need a provider abstraction layer.

Suggested module:

- `apps/worker/src/runtime/providers.py`

Responsibilities:

- detect provider capabilities
- choose provider config
- choose FP16 vs FP32 swap model
- enable optional CUDA graph mode
- expose session/perf metadata for `/health`

## 5. They use FP16 model selection intentionally

In `face_swapper.py`, the project prefers `inswapper_128_fp16.onnx` on modern GPUs and falls back to `inswapper_128.onnx` otherwise.

### Why it matters

This is a free or near-free speedup on supported hardware:

- lower memory bandwidth
- faster inference
- usually enough precision for production swap quality

### Implication for us

We should support:

- `SWAP_MODEL_PATH_FP32`
- `SWAP_MODEL_PATH_FP16`
- auto-pick based on provider and hardware

This should be inside the provider/session builder, not spread through business logic.

## 6. They do custom paste-back instead of default `paste_back=True`

This is one of the most important quality/performance insights.

### What they do

They call the swapper with:

- `paste_back=False`

Then they run a custom `_fast_paste_back(...)`.

That custom path:

- avoids redundant normalization/cropping
- restricts work to the face region
- uses cached feathered alpha templates
- supports mouth masking, opacity, and downstream blending

### Why it matters

The stock paste-back is simple but gives away control over:

- edge softness
- region constraints
- mouth preservation
- custom masks
- performance tuning

### Implication for us

This is the single most important quality upgrade we should copy conceptually.

We should stop relying only on:

- `swapper.get(..., paste_back=True)`

and move to:

1. aligned swap output
2. affine matrix
3. custom paste-back
4. mask-aware compositing
5. optional mouth restore
6. optional Poisson blend

## 7. They build masks from 106-point landmarks

In `face_masking.py`, `create_face_mask(face, frame)` uses:

- `face.landmark_2d_106`
- convex hull
- outward padding
- gaussian blur

This is better than bbox-based masking.

### Why it matters

Bbox masks usually produce:

- forehead leakage
- cheek/ear mismatch
- jawline cut artifacts
- hairline halos

Landmark-driven masks follow the face geometry much more closely.

### Implication for us

Our current blend path is still too coarse. We should upgrade from:

- bbox + ellipse mask

to:

- 106-point convex-hull-based face region
- configurable expansion
- separate feathering for jawline vs forehead

## 8. They preserve the original mouth

This is a very important realism trick.

### What they do

`create_lower_mouth_mask(...)`:

- uses mouth landmarks from the 106-point set
- expands them with configurable size/bias
- extracts a mouth cutout from the original frame
- pastes the original mouth back onto the swapped face

### Why it matters

Mouth regions are one of the fastest ways for a swap to look fake:

- teeth
- inner mouth darkness
- lip motion
- speech shape

Preserving the original mouth often improves:

- lip-sync realism
- talking-head quality
- “not sticker pasted” perception

### Implication for us

We should implement mouth preservation before attempting full body work.

This should be optional and tunable:

- enabled by default for live preview
- adjustable mouth mask size
- maybe auto-disabled when mouth is mostly closed

## 9. They optionally use Poisson blending

After swapping and masking, they optionally run `cv2.seamlessClone(...)`.

### Why it matters

Poisson blending can help with:

- lighting mismatch
- boundary seams
- color transition issues

But it can also cost time and sometimes oversoften results.

### Implication for us

We should implement Poisson blending as:

- optional
- quality mode only
- not always-on in low-latency mode

## 10. They add enhancement after swapping

Their `face_enhancer.py` uses:

- GFPGAN ONNX
- aligned face crops
- 5-point FFHQ template
- paste-back after enhancement

### Important insight

This is not just “super resolution.” It is:

1. align swapped face
2. enhance the aligned crop
3. inverse transform back to frame

That usually gives better detail than enhancing the entire frame blindly.

### Implication for us

We should add a second-stage enhancer module after swap:

- `GFPGAN` or `GPEN` ONNX
- on aligned face crop
- only on the swapped face region

This can be:

- disabled in low-latency mode
- enabled in quality mode
- maybe sampled every 2nd frame with cache reuse

## 11. They cache enhancement in live mode

This is one of the smartest runtime tricks in the repo.

`face_enhancer.py` caches:

- enhanced face
- affine matrix
- frame count

and runs enhancement every `N` frames, reusing cached output in between.

### Why it matters

Enhancement is expensive.

But consecutive frames in a live talking-head stream are often very similar.

### Implication for us

We should do exactly this conceptually:

- swap every frame or near every frame
- enhance every `2` or `3` frames
- reuse the last enhanced result between enhancement intervals

This gives a better perceived quality/latency tradeoff.

## 12. They track multiple faces by embeddings and mapping

`face_swapper.py` has logic for:

- `many_faces`
- `map_faces`
- source/target pairing
- embedding-based live mapping

### Why it matters

High precision is not just single-face quality. It also means:

- stable identity assignment across frames
- correct source-to-target matching
- less jumping between faces

### Implication for us

Even if MVP stays single-face, we should architect for:

- face IDs
- embedding cache
- temporal assignment
- track continuity

This avoids rewriting the worker later.

## 13. They smooth and sharpen after swap

There is a post-processing pass that handles:

- sharpening on swapped bbox regions
- interpolation with previous frame result

### Why it matters

This stabilizes output and can hide small temporal inconsistencies.

### Implication for us

We should add:

- optional mild sharpen on final face ROI
- temporal smoothing / interpolation
- track-aware smoothing so the face does not shimmer

## Architectural Differences vs Our Current Codebase

## Our current state

Today our worker is still mostly monolithic:

- one `FaceSwapPipeline` in [apps/worker/src/main.py](F:\ai-creator-studio\apps\worker\src\main.py)
- direct `InsightFace` call
- custom blend pass
- live JPEG preview transport

This was the right short-term move to get working output quickly.

## Where we are behind Deep-Live-Cam

We currently do **not** have:

1. separate analyser / swapper / masking / enhancer modules
2. detection-only fast path
3. optional landmark skipping
4. custom aligned-space paste-back with cached alpha template
5. mouth preservation
6. Poisson blending option
7. enhancer stage
8. temporal enhancement caching
9. embedding-based multi-face assignment
10. provider-specific runtime tuning beyond simple CUDA/CPU selection

## What we already have that is still useful

We should keep:

- gateway/session lifecycle
- preview websocket transport
- current worker reservation model
- current avatar upload flow
- current status reporting

Those pieces are still valid.

## Recommended Re-Architecture for Our Worker

We should refactor `apps/worker/src/main.py` into a module tree like this:

```text
apps/worker/src/
  main.py
  runtime/
    providers.py
    sessions.py
  pipeline/
    analyser.py
    swapper.py
    masking.py
    enhancer.py
    tracker.py
    compositor.py
    postprocess.py
  preview/
    websocket_preview.py
  models/
    registry.py
```

## Proposed responsibilities

### `pipeline/analyser.py`

- initialize `FaceAnalysis`
- expose:
  - `detect_one_face_fast`
  - `detect_many_faces_fast`
  - `analyse_faces`
- decide whether landmark model is needed for current pipeline mode

### `pipeline/swapper.py`

- load FP16 or FP32 `inswapper_128`
- perform aligned swap with `paste_back=False`
- return:
  - swapped aligned face
  - inverse affine / transform metadata
  - target face metadata

### `pipeline/masking.py`

- build face mask from `landmark_2d_106`
- build lower-mouth mask
- apply original mouth restore
- optional poisson blend
- optional opacity control

### `pipeline/enhancer.py`

- load GFPGAN/GPEN ONNX
- align face to template
- run enhancement
- paste enhanced face back
- temporal cache for live mode

### `pipeline/tracker.py`

- cache active face tracks
- assign stable target ID across frames
- embedding similarity / bbox proximity matching
- support future multi-face routing

### `pipeline/compositor.py`

- face-region lighting correction
- color transfer
- blend stacking order

### `pipeline/postprocess.py`

- sharpening
- temporal smoothing
- interpolation options

## Precision Features We Should Implement First

This is the best order to match Deep-Live-Cam quality without destabilizing the system.

## Phase 1: high-impact swap realism

1. custom paste-back with `paste_back=False`
2. 106-landmark face mask
3. mouth preservation
4. optional opacity slider
5. optional Poisson blend

Expected impact:

- biggest visible realism jump
- lower “sticker” look
- better speaking-face quality

## Phase 2: live stability

1. detection-only fast path
2. landmark skipping when not needed
3. temporal face tracking
4. sharpen + temporal smoothing

Expected impact:

- lower latency
- less flicker
- more stable identity placement

## Phase 3: quality mode

1. GFPGAN/GPEN ONNX enhancer
2. enhancement caching every `N` frames
3. quality/performance mode toggle

Expected impact:

- cleaner facial detail
- better eyes/skin/mouth sharpness
- manageable latency tradeoff

## Phase 4: advanced mapping

1. multiple target faces
2. embedding-based source/target mapping
3. track persistence over time

Expected impact:

- production readiness for multi-person scenes

## Exact Replication Recommendations for This Repo

## Recommendation 1: stop expanding `main.py`

Do not keep adding quality logic into the current `FaceSwapPipeline` in `main.py`.

Reason:

- we will quickly end up with Deep-Live-Cam complexity inside one file
- the current file is already carrying:
  - pipeline logic
  - preview transport
  - health/reserve/release API
  - old WebRTC code

We should split concerns now.

## Recommendation 2: introduce explicit pipeline modes

Add worker modes:

- `preview-fast`
- `preview-balanced`
- `preview-quality`

Each mode should define:

- detection cadence
- whether enhancer is enabled
- whether mouth preservation is enabled
- whether Poisson blend is enabled
- JPEG preview quality and resolution

## Recommendation 3: store richer face objects in session state

Current source avatar state should become:

- source face embedding
- source 5-point landmarks
- source 106-point landmarks if available
- aligned source crop
- metadata about image quality

This supports:

- better swap
- better enhancer alignment
- better multi-face extension later

## Recommendation 4: add quality diagnostics to `/health`

We already expose some worker state. Extend it with:

- current provider
- swap model variant (`fp16` / `fp32`)
- enhancer enabled
- mouth mask enabled
- average processing ms
- average encode ms
- cached enhancement hit rate

This will make tuning much easier.

## Recommendation 5: benchmark every stage separately

Deep-Live-Cam’s real strength is that it knows where the time goes.

We should measure separately:

- camera frame receive
- JPEG decode
- detection
- full analysis
- swap inference
- mask creation
- enhancer inference
- final blend
- JPEG encode
- websocket send

Without this, we will keep guessing.

## A Practical Roadmap for Our Codebase

## Sprint 1

Goal: replicate the biggest Deep-Live-Cam quality wins.

Tasks:

1. split worker into `analyser.py`, `swapper.py`, `masking.py`
2. implement `paste_back=False` swap path
3. implement 106-point face mask
4. implement mouth restoration
5. add mode flags

## Sprint 2

Goal: match live smoothness.

Tasks:

1. detection-only fast path
2. track-aware face assignment
3. temporal smoothing
4. better performance telemetry

## Sprint 3

Goal: quality mode.

Tasks:

1. GFPGAN ONNX aligned enhancer
2. temporal enhancement cache
3. per-mode controls

## Why This Matters for “High Precision”

The repo shows that “precision” is not only:

- a better source image
- a better swap model

It is mostly:

- correct face geometry
- correct aligned-space processing
- correct mask shape
- mouth preservation
- lighting consistency
- temporal stability
- hardware-aware inference

That is the real lesson to carry over.

## Final Recommendation

If we want to reproduce `Deep-Live-Cam` quality in this codebase, we should not chase a different primary model first.

We should:

1. keep `InsightFace + inswapper_128`
2. re-architect the worker around modular processors
3. implement their strongest quality and runtime ideas in our own code
4. add enhancer and tracking after masking/paste-back are in place

That path gives the highest chance of reaching similar precision without rewriting the whole product around a different foundation.

## Sources

- Deep-Live-Cam repository:
  - <https://github.com/hacksider/Deep-Live-Cam>
- README:
  - <https://github.com/hacksider/Deep-Live-Cam/blob/main/README.md>
- Face analyser:
  - <https://github.com/hacksider/Deep-Live-Cam/blob/main/modules/face_analyser.py>
- Face swapper:
  - <https://github.com/hacksider/Deep-Live-Cam/blob/main/modules/processors/frame/face_swapper.py>
- Face masking:
  - <https://github.com/hacksider/Deep-Live-Cam/blob/main/modules/processors/frame/face_masking.py>
- Face enhancer:
  - <https://github.com/hacksider/Deep-Live-Cam/blob/main/modules/processors/frame/face_enhancer.py>
