from app.formation.sample import generate_formation
from app.geometry.svg import _hex_rgb, sample_svg
from app.models import FormationGenerationSettings


def test_parses_hex_rgb_and_named():
    assert _hex_rgb("#ff0000") == (1.0, 0.0, 0.0)
    assert _hex_rgb("rgb(0, 255, 0)") == (0.0, 1.0, 0.0)
    assert _hex_rgb("blue")[2] > 0.8
    assert _hex_rgb("none") is None


def test_svg_keeps_per_path_colors():
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40">
      <g stroke="#ff0000"><path d="M0 10 H 100"/></g>
      <path d="M0 30 H 100" style="stroke:#00ff00"/>
    </svg>"""
    samples = sample_svg(svg, 200)
    reds = [s for s in samples if s.color[0] > 0.9 and s.color[1] < 0.15]
    greens = [s for s in samples if s.color[1] > 0.9 and s.color[0] < 0.15]
    assert reds and greens


def test_formation_uses_sampled_color_not_override():
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 20">
      <path d="M0 10 H 80" stroke="#1122ff" fill="none"/>
    </svg>"""
    f = generate_formation(
        formation_id="f",
        name="blue",
        asset_id="a",
        content=svg,
        kind="svg",
        count=10,
        settings=FormationGenerationSettings(seed=1, widthM=40, heightM=10, depthM=1),
        min_sep_m=0.4,
    )
    blues = [p for p in f.points if p.color[2] > 0.8 and p.color[0] < 0.2]
    assert blues
