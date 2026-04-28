## ADDED Requirements

### Requirement: Stable MapEngine interface

The frontend SHALL define a single `MapEngine` TypeScript interface that the application code imports. Concrete engine implementations SHALL live under `apps/web/src/map/engines/` and SHALL NOT be imported directly by any React component, hook, or page. Swapping engines MUST be possible by changing a single factory call.

#### Scenario: Component imports only the MapEngine interface
- **WHEN** a React component needs to interact with the map
- **THEN** the component imports from `@/map` only and receives a `MapEngine` instance from the factory

#### Scenario: Swap from MapLibre to Google tiles is a one-file change
- **WHEN** the project upgrades to Google Photorealistic 3D Tiles
- **THEN** only `apps/web/src/map/index.ts` (the factory) and the new engine file change; application components are untouched

### Requirement: MapLibre implementation as v1 default

The `MaplibreEngine` SHALL be the default engine selected by the factory when `VITE_MAP_ENGINE` is unset or equals `"maplibre"`. It SHALL use `maplibre-gl` with an OpenStreetMap-derived style that includes extruded 3D buildings, and it SHALL run entirely on free data with no API key required.

#### Scenario: Default startup uses MapLibre
- **WHEN** the frontend starts without `VITE_MAP_ENGINE` set
- **THEN** the factory returns a `MaplibreEngine` and the app renders a 3D OSM map without any network calls to Google

### Requirement: GoogleTilesEngine is stubbed and upgrade-ready

A `GoogleTilesEngine` class SHALL exist as a compile-clean stub that implements the `MapEngine` interface and throws `NotImplementedError` from every runtime method. The factory SHALL select it when `VITE_MAP_ENGINE="google-3d"` and a `VITE_GOOGLE_MAP_TILES_API_KEY` is present. This stub establishes the upgrade path before any real Google integration is written.

#### Scenario: Selecting Google engine without a key fails loudly
- **WHEN** the frontend starts with `VITE_MAP_ENGINE="google-3d"` and no API key set
- **THEN** the factory throws a descriptive error on construction, not on first method call

#### Scenario: Selecting Google engine today throws NotImplementedError at runtime
- **WHEN** the frontend starts with `VITE_MAP_ENGINE="google-3d"` and an API key set, and a component calls `engine.flyTo(...)`
- **THEN** the stub throws `NotImplementedError` with a link to the tasks file entry that tracks the v2 upgrade

### Requirement: Minimum interface surface

The `MapEngine` interface SHALL expose at least the following methods, each with stable semantics: `init(container, viewport)`, `setViewport(v)`, `flyTo(target, durationMs?)`, `addMarkers(layerId, markers)`, `addPath(layerId, coords, style?)`, `clearLayer(layerId)`, `onCameraChange(cb)` returning an unsubscribe function, and `destroy()`. Additional methods MAY be added later as optional members.

#### Scenario: MaplibreEngine provides every interface method
- **WHEN** `MaplibreEngine` is instantiated
- **THEN** calling each method from the interface either executes or returns a well-typed Promise, with no `undefined is not a function` errors

### Requirement: No direct MapLibre imports outside the engine module

The project SHALL enforce via ESLint that files outside `apps/web/src/map/engines/` may NOT `import` from `maplibre-gl` or any sub-path. CI SHALL fail the build when this rule is violated.

#### Scenario: Violating import is blocked by lint
- **WHEN** a component in `apps/web/src/components/` imports `maplibre-gl`
- **THEN** `npm run lint` fails with a rule-specific error message
