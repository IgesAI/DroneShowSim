from __future__ import annotations

from app.geometry.mesh import icosphere_obj
from app.models import AnimationClip, Asset, Cue, DroneProfile, Formation, FormationGenerationSettings, ShowProject, Timeline, Transition

COBRA_LOGO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120">
  <path d="M20 90 C 40 40, 70 20, 110 28 C 150 36, 175 20, 185 18" fill="none" stroke="#ff3b3b" stroke-width="7"/>
  <path d="M110 28 C 130 10, 160 8, 178 22" fill="none" stroke="#ff3b3b" stroke-width="6"/>
  <path d="M118 34 C 140 55, 155 70, 168 78" fill="none" stroke="#ff3b3b" stroke-width="5"/>
  <path d="M20 90 C 35 100, 55 108, 80 104" fill="none" stroke="#ff3b3b" stroke-width="6"/>
  <circle cx="176" cy="16" r="3.2" fill="#ff3b3b"/>
</svg>"""

MOTORCYCLE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 120">
  <circle cx="50" cy="88" r="22" fill="none" stroke="#f4f1ea" stroke-width="5"/>
  <circle cx="170" cy="88" r="22" fill="none" stroke="#f4f1ea" stroke-width="5"/>
  <path d="M50 88 L 92 88 L 118 48 L 168 52 L 170 88" fill="none" stroke="#f4f1ea" stroke-width="5"/>
  <path d="M118 48 L 108 22 L 128 18" fill="none" stroke="#f4f1ea" stroke-width="5"/>
  <path d="M108 36 L 78 58 L 96 58" fill="none" stroke="#f4f1ea" stroke-width="4"/>
  <circle cx="128" cy="10" r="7" fill="none" stroke="#f4f1ea" stroke-width="4"/>
  <path d="M108 28 L 86 22" fill="none" stroke="#f4f1ea" stroke-width="4"/>
  <path d="M112 30 L 142 34" fill="none" stroke="#f4f1ea" stroke-width="4"/>
</svg>"""


def cobra_project(count: int = 250, seed: int = 1) -> ShowProject:
    settings = FormationGenerationSettings(mode="feature", widthM=90, heightM=42, depthM=0, seed=seed)
    volume = FormationGenerationSettings(mode="surface", widthM=48, heightM=48, depthM=48, seed=seed)
    assets = [
        Asset(id="asset_logo", name="Cobra logo", kind="svg", content=COBRA_LOGO),
        Asset(id="asset_bike", name="Motorcycle", kind="svg", content=MOTORCYCLE),
        Asset(id="asset_orb", name="Orb", kind="obj", content=icosphere_obj(1)),
        Asset(id="asset_text", name="COBRA", kind="text", content="COBRA"),
    ]
    formations = [
        Formation(id="frm_logo", name="COBRA LOGO", sourceAssetId="asset_logo", generationSettings=settings),
        Formation(id="frm_bike", name="MOTORCYCLE", sourceAssetId="asset_bike", generationSettings=settings),
        Formation(id="frm_orb", name="ORB", sourceAssetId="asset_orb", generationSettings=volume),
        Formation(id="frm_text", name="COBRA", sourceAssetId="asset_text", generationSettings=settings.model_copy(update={"widthM": 110, "heightM": 28})),
    ]
    cues = [
        Cue(id="cue_logo", formationId="frm_logo", startTime=0, holdDuration=5),
        Cue(id="cue_bike", formationId="frm_bike", startTime=0, holdDuration=7),
        Cue(id="cue_orb", formationId="frm_orb", startTime=0, holdDuration=6),
        Cue(id="cue_text", formationId="frm_text", startTime=0, holdDuration=6),
    ]
    transitions = [
        Transition(id="tr_1", fromFormationId="frm_logo", toFormationId="frm_bike", startTime=0, duration=6, durationMode="auto", type="morph"),
        Transition(id="tr_2", fromFormationId="frm_bike", toFormationId="frm_orb", startTime=0, duration=6, durationMode="auto", type="morph"),
        Transition(id="tr_3", fromFormationId="frm_orb", toFormationId="frm_text", startTime=0, duration=6, durationMode="auto", type="morph"),
    ]
    return ShowProject(
        id="show_cobra_demo",
        name="Cobra Demo",
        droneProfile=DroneProfile(count=count),
        assets=assets,
        formations=formations,
        timeline=Timeline(
            cues=cues,
            transitions=transitions,
            animations=[
                AnimationClip(
                    id="anim_flip",
                    name="Backflip",
                    kind="rigid",
                    formationId="frm_bike",
                    cueOffset=1.2,
                    duration=4.0,
                    motion="backflip",
                    amplitude=1.0,
                )
            ],
        ),
    )
