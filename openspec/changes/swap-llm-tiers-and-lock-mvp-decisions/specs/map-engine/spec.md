## MODIFIED Requirements

### Requirement: Minimum interface surface

The `MapEngine` interface SHALL expose at least the following methods, each with stable semantics: `init(container, viewport)`, `setViewport(v)`, `flyTo(target, durationMs?)`, `addMarkers(layerId, markers)`, `addPath(layerId, coords, style?)`, `clearLayer(layerId)`, and `destroy()`. Additional methods MAY be added later as optional members.

The previously-required `onCameraChange(cb)` callback method is **removed from the V1 interface** and deferred to v2. V1 drives the camera deterministically via `flyTo` (one fly-to per tour stop) and does not need to react to user-driven camera changes. v2 will re-introduce camera-change observation if a feature like "show what's currently on screen" is added.

#### Scenario: MaplibreEngine provides every V1 interface method
- **WHEN** `MaplibreEngine` is instantiated
- **THEN** calling each method from the V1 interface (`init`, `setViewport`, `flyTo`, `addMarkers`, `addPath`, `clearLayer`, `destroy`) either executes or returns a well-typed Promise, with no `undefined is not a function` errors

#### Scenario: V1 interface does NOT include onCameraChange
- **WHEN** an application component attempts `engine.onCameraChange(cb)` in V1
- **THEN** the TypeScript compiler reports the method as missing from the `MapEngine` interface; the build fails before runtime

#### Scenario: Adding onCameraChange in v2 is a non-breaking interface extension
- **WHEN** v2 re-adds `onCameraChange` as an optional method on the interface
- **THEN** existing V1 components compile unchanged because they never referenced the method
