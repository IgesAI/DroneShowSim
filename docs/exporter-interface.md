# Exporter interface

Exporters convert `.dshow` → vendor bytes. They never mutate the project.

Order:

1. Internal JSON debug
2. Generic CSV
3. VVIZ (visualization only)
4. Skybrush-compatible CSV ZIP
5. Other vendors

Internal trajectories are min-jerk segments. The exporter chooses the sample rate (25 / 50 / 100 Hz), then converts coordinates and units.
