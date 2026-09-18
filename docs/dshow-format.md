# `.dshow` format

A `.dshow` file is a ZIP archive, not an opaque binary.

```
cobra-show.dshow
  manifest.json
  project.json
  assets/
  formations/
  trajectories/
  lights/
  audio/
  reports/safety.json
```

`manifest.json`

```json
{
  "format": "dshow",
  "version": "0.1.0",
  "name": "Cobra Show",
  "coordinateSystem": "DSHOW_LOCAL_RH",
  "units": "SI",
  "droneCount": 250,
  "schemaVersion": "0.1.0",
  "compilerVersion": "0.1.0"
}
```

Metadata stays JSON. Large arrays can later move to Float32 / MessagePack / Arrow without changing the logical model.
