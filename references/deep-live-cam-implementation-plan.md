# Deep-Live-Cam Replication Implementation Plan

## Goal

Turn the research in [deep-live-cam-research.md](F:\ai-creator-studio\references\deep-live-cam-research.md) into a concrete build plan for this repository.

This plan is intentionally repo-specific:

- which files to create
- which existing files to shrink
- implementation order
- testing checkpoints
- risk notes

The target is **higher precision live face swap** in our existing browser -> gateway -> worker architecture.

## Current State in This Repo

Relevant current files:

- worker:
  - [main.py](F:\ai-creator-studio\apps\worker\src\main.py)
- gateway:
  - [session.ts](F:\ai-creator-studio\apps\gateway\src\routes\session.ts)
  - [session-workflow.ts](F:\ai-creator-studio\apps\gateway\src\services\session-workflow.ts)
- web:
  - [studio-client.tsx](F:\ai-creator-studio\apps\web\src\components\studio-client.tsx)
- shared contracts:
  - [index.ts](F:\ai-creator-studio\packages\shared-types\src\index.ts)

Current good parts we should preserve:

- session lifecycle
- worker reservation contract
- avatar upload flow
- live preview websocket transport
- worker health/status reporting

Current weak point:

- too much logic is still inside [main.py](F:\ai-creator-studio\apps\worker\src\main.py)

## High-Level Architecture We Should Move To

Create this structure under `apps/worker/src`:

```text
apps/worker/src/
  main.py
  runtime/
    __init__.py
    provider_config.py
    metrics.py
  pipeline/
    __init__.py
    analyser.py
    swapper.py
    masking.py
    compositor.py
    enhancer.py
    tracker.py
    types.py
  transport/
    __init__.py
    preview_socket.py
    worker_api.py
```

## Why This Split

- `main.py` should only bootstrap the app and state
- `runtime/` should own provider/model/session configuration
- `pipeline/` should own image intelligence
- `transport/` should own HTTP/websocket request handling

This keeps future work like:

- mouth preservation
- body segmentation
- enhancer caching
- performance mode

from piling into one file.

## Phase 0: Refactor for Safety

Goal:

- move existing logic out of `main.py` without changing behavior

### Files to create

1. `apps/worker/src/pipeline/types.py`
2. `apps/worker/src/pipeline/analyser.py`
3. `apps/worker/src/pipeline/swapper.py`
4. `apps/worker/src/pipeline/masking.py`
5. `apps/worker/src/pipeline/compositor.py`
6. `apps/worker/src/runtime/provider_config.py`
7. `apps/worker/src/runtime/metrics.py`

### Files to edit

1. [main.py](F:\ai-creator-studio\apps\worker\src\main.py)

### Work items

1. Move provider/model initialization out of `FaceSwapPipeline.__init__`
2. Move face analysis setup to `analyser.py`
3. Move swap model loading to `swapper.py`
4. Move current blend helpers to `masking.py` and `compositor.py`
5. Leave the preview websocket route working exactly as it does now

### Definition of done

- same preview behavior
- same API shape
- same worker status fields
- no visible quality regression

### Risk

- medium

### Why this phase first

Because Phases 1-3 get messy fast if we keep coding directly in `main.py`.

## Phase 1: Deep-Live-Cam Precision Core

Goal:

- reproduce the biggest visible quality wins from Deep-Live-Cam

### Main features

1. aligned-space swap with `paste_back=False`
2. custom paste-back
3. 106-point face mask
4. mouth preservation
5. configurable blend opacity

### Files to create or expand

1. `apps/worker/src/pipeline/analyser.py`
2. `apps/worker/src/pipeline/swapper.py`
3. `apps/worker/src/pipeline/masking.py`
4. `apps/worker/src/pipeline/compositor.py`
5. `apps/worker/src/pipeline/types.py`

### Work items

#### 1. Add pipeline data types

Create shared structures for:

- `DetectedFace`
- `TargetFaceAnalysis`
- `SourceFaceProfile`
- `SwapResult`
- `FaceMaskSet`
- `FrameProcessResult`

Suggested fields:

- bbox
- 5-point landmarks
- 106-point landmarks
- embedding
- alignment matrix
- inverse matrix
- quality flags

#### 2. Build a source face profile object

Current avatar handling only stores a single `source_face` object.

Replace that with a richer source profile:

- full face object from InsightFace
- normalized source crop
- source embedding
- source landmarks
- source quality metadata

Why:

- mouth restore and enhancement will want richer geometry
- later multi-avatar support becomes easier

#### 3. Implement aligned swap

In `swapper.py`:

- stop relying only on `swapper.get(..., paste_back=True)`
- perform aligned swap path
- return:
  - swapped aligned face
  - target face metadata
  - transform info for paste-back

Important:

- do not copy Deep-Live-Cam code directly
- recreate the concept with our own implementation

#### 4. Implement 106-point mask generation

In `masking.py`:

- build a convex-hull face mask from `landmark_2d_106`
- support expansion controls:
  - forehead expansion
  - cheek expansion
  - jaw feather
- output:
  - full face mask
  - feathered alpha mask

#### 5. Implement mouth preservation

In `masking.py`:

- derive lower-mouth mask from mouth landmarks
- restore the original mouth region from the target frame
- make it optional by env/config

Suggested controls:

- `MOUTH_PRESERVE_ENABLED=true`
- `MOUTH_MASK_SCALE=1.0`
- `MOUTH_MASK_Y_OFFSET=0.0`

#### 6. Implement custom paste-back and compositing

In `compositor.py`:

- place swapped aligned face back into frame
- apply face mask
- apply mouth restore if enabled
- apply color matching
- apply opacity control
- optional `seamlessClone` support behind a flag

Suggested controls:

- `FACE_BLEND_STRENGTH`
- `FACE_COLOR_MATCH_STRENGTH`
- `POISSON_BLEND_ENABLED`

### Definition of done

- visibly cleaner jawline and forehead edges
- better speaking-mouth realism
- less “sticker” effect

### Risk

- high

### Why it is worth it

This phase likely produces the largest visual quality jump.

## Phase 2: Performance and Stability

Goal:

- make the higher-quality pipeline still usable live

### Main features

1. detection-only fast path
2. selective landmark inference
3. temporal face tracking
4. performance metrics

### Files to create or expand

1. `apps/worker/src/pipeline/analyser.py`
2. `apps/worker/src/pipeline/tracker.py`
3. `apps/worker/src/runtime/metrics.py`

### Work items

#### 1. Add fast detection pass

Expose:

- `detect_one_face_fast(frame)`
- `detect_many_faces_fast(frame)`

Use these for frames that do not require full re-analysis.

#### 2. Add selective analysis cadence

Only run full analysis when:

- a face is new
- tracking confidence dropped
- mouth preserve needs fresh landmarks
- enhancer needs fresh alignment
- a periodic refresh interval is hit

Suggested envs:

- `FULL_ANALYSIS_INTERVAL=3`
- `LANDMARK_REFRESH_INTERVAL=2`

#### 3. Add target face tracking

In `tracker.py`:

- combine bbox proximity + embedding similarity
- maintain stable `track_id`
- smooth bbox/landmark jitter over time

This is important even in single-face mode because it stabilizes masks and blending.

#### 4. Add metrics collection

In `runtime/metrics.py`, track:

- decode ms
- detect ms
- analyse ms
- swap ms
- blend ms
- encode ms
- total frame ms
- preview roundtrip estimate

Expose summarized stats in `/health`.

### Definition of done

- lower latency regression after Phase 1
- less jitter
- better consistency frame to frame

### Risk

- medium

## Phase 3: Enhancement Layer

Goal:

- move toward Deep-Live-Cam “quality mode”

### Main features

1. aligned face enhancement
2. periodic enhancement cache reuse
3. quality/performance modes

### Files to create or expand

1. `apps/worker/src/pipeline/enhancer.py`
2. `apps/worker/src/pipeline/compositor.py`
3. `apps/worker/src/pipeline/types.py`

### Work items

#### 1. Add enhancer model abstraction

Support one of:

- GFPGAN ONNX
- GPEN ONNX

Keep it modular so we can swap later.

#### 2. Enhance aligned face crop only

Do not enhance the whole frame.

Process:

1. align target face
2. run enhancer on aligned crop
3. inverse paste back into frame

#### 3. Add enhancement frame cache

Cache by track:

- last enhanced face crop
- last transform
- last frame index

Suggested config:

- `ENHANCER_INTERVAL=2`

This means:

- enhance every 2nd frame
- reuse previous enhanced result between intervals

#### 4. Add pipeline modes

Suggested worker modes:

- `fast`
- `balanced`
- `quality`

Map them to:

- analysis cadence
- preview resolution
- enhancement on/off
- poisson blend on/off
- mouth preserve on/off

### Definition of done

- sharper eyes/skin/mouth
- manageable latency in balanced mode

### Risk

- medium-high

## Phase 4: Upper-Body Foundations

Goal:

- prepare for body-aware compositing without promising full body swap yet

### Main features

1. person/upper-body segmentation
2. neck/shoulder-aware blending
3. torso-aware color continuity

### Files to create

1. `apps/worker/src/pipeline/body_masking.py`
2. `apps/worker/src/pipeline/segmentation.py`

### Work items

1. integrate a person segmentation model
2. isolate head/neck/upper torso
3. allow compositing decisions that account for neck and shirt boundary

### Why this phase is separate

Because it is not required to make face swaps look much better, and it adds new model/runtime cost.

## Exact File-by-File Plan

## `apps/worker/src/main.py`

### Change

Shrink it into:

- app bootstrap
- worker state
- route registration
- orchestration glue

### Remove from this file over time

- face analysis logic
- swap logic
- mask generation
- compositing logic
- enhancement logic

### Keep here

- `WorkerState`
- `health`, `reserve`, `release`
- preview websocket route
- heartbeat loop

## `apps/worker/src/pipeline/analyser.py`

### Add

- provider-aware `FaceAnalysis` setup
- detection-only fast path
- full analysis path
- source avatar analysis path

### Notes

- this module should own the `allowed_modules` decision
- this is where we avoid wasted analysis work

## `apps/worker/src/pipeline/swapper.py`

### Add

- swap model session creation
- FP16/FP32 selection
- aligned swap call
- metadata return structure

### Notes

- this module should not do final compositing

## `apps/worker/src/pipeline/masking.py`

### Add

- 106-point face mask builder
- lower-mouth mask builder
- mask feather utilities

### Notes

- keep it pure and testable

## `apps/worker/src/pipeline/compositor.py`

### Add

- face-region color correction
- custom paste-back
- alpha blend
- optional Poisson blend
- mouth restore layering

## `apps/worker/src/pipeline/enhancer.py`

### Add

- aligned face enhancer
- enhancer result cache

## `apps/worker/src/pipeline/tracker.py`

### Add

- track IDs
- per-track smoothing
- embedding-aware assignment

## `apps/worker/src/runtime/provider_config.py`

### Add

- provider detection
- CUDA/CPU selection
- FP16 eligibility
- future CoreML/OpenVINO hooks

## `apps/worker/src/runtime/metrics.py`

### Add

- stage timing helpers
- moving averages
- `/health` export payload

## Suggested Implementation Order

This is the order I recommend we code it.

1. Phase 0 refactor
2. source face profile object
3. aligned swapper
4. 106-point mask
5. mouth preservation
6. custom compositor
7. metrics
8. fast detection path
9. tracking
10. enhancer

This order minimizes the chance of losing the working preview while we raise quality.

## Testing Plan

## Manual checkpoints

After each major step:

1. start worker
2. start session in Studio
3. verify:
   - preview still streams
   - latency is acceptable
   - face remains aligned during motion
   - mouth looks natural while speaking

## Diagnostic checks

Add health checks for:

- provider
- avatar face loaded
- swap model loaded
- analysis cadence
- average stage timings
- current mode

## Regression checks

Watch for:

- black preview
- face not detected after refactor
- mask detached from moving face
- huge latency increase
- mouth restore flickering

## Risks and How to Manage Them

## Risk 1: worker complexity grows too fast

Mitigation:

- do Phase 0 first
- keep pure functions in pipeline modules

## Risk 2: quality improves but latency becomes unusable

Mitigation:

- add metrics before enhancer
- ship `fast`, `balanced`, `quality` modes

## Risk 3: mouth preservation looks worse on some frames

Mitigation:

- make it togglable
- gate it by mouth confidence / face angle later

## Risk 4: enhancer makes flicker worse

Mitigation:

- add track-aware cache reuse
- do not enhance every frame in live mode

## Recommendation

The right next action is:

1. execute **Phase 0** immediately
2. then build **Phase 1** in this order:
   - source face profile
   - aligned swapper
   - 106-point mask
   - mouth preservation
   - custom compositor

That gives us the fastest path toward Deep-Live-Cam-style precision while keeping the codebase maintainable.
