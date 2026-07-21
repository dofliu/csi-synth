"""
csi_synth — Physically-grounded synthetic WiFi CSI generator.

A "digital-twin"-style simulator for developing and testing the analysis
pipeline (preprocessing -> features -> model) BEFORE real Intel AX211
hardware data is available.

IMPORTANT — scientific honesty:
    Synthetic CSI is for pipeline development and algorithm validation only.
    Any model trained on synthetic data MUST be re-validated on real captured
    CSI. Never report synthetic results as experimental measurements.

Quick start:
    from csi_synth import Room, Node, Person, RadioConfig, generate_csi
    from csi_synth import NoiseConfig, apply_noise, estimate_rate

    room = Room(5, 4)
    tx, rx = Node(0.6, 2.0), Node(4.4, 2.0)
    person = Person(2.5, 2.0, breathing={"rate_bpm": 15, "amplitude_mm": 5})
    clean = generate_csi(room, tx, rx, person, duration=30)
    noisy = apply_noise(clean, NoiseConfig(snr_db=25))
    print(estimate_rate(noisy, band=(0.1, 0.6))["bpm"])
"""
from .geometry import Room, Node, Person
from .generator import RadioConfig, CSIResult, generate_csi, C
from .noise import NoiseConfig, apply_noise
from .estimate import estimate_rate, bandpass
from .scenarios import make_scenario, build_dataset, POSTURES

__version__ = "0.1.0"
__all__ = [
    "Room", "Node", "Person",
    "RadioConfig", "CSIResult", "generate_csi", "C",
    "NoiseConfig", "apply_noise",
    "estimate_rate", "bandpass",
    "make_scenario", "build_dataset", "POSTURES",
]

# physics-realism layer (optional)
from .realism import (
    RespirationModel, BodySegment, RealismConfig,
    default_body, generate_csi_realistic,
)

# clinical respiratory-event layer (Stage 2)
from .clinical import (
    SleepBreathingModel, ClinicalEvent, generate_clinical_csi,
    NORMAL, HYPOPNEA, APNEA_OSA, APNEA_CSA, EVENT_NAMES, ahi, default_night,
)

# polygon rooms with ray-traced multipath + edge diffraction (Stage 3)
from .polygon import (
    PolygonRoom, rect_room, l_room, generate_polygon_csi,
)
from .polygon import partition_room, slanted_room

# interactive digital-twin export loader (bridge to the same estimate pipeline)
from .twin_import import load_twin_csi, resample_uniform

# posture-aware subcarrier selection (PASS, contribution C2)
from .pass_select import (
    select_sensitive, band_energy_per_subcarrier, estimate_rate_subs, fused_snr_eff,
    detect_transitions, stable_segments, posture_fingerprint, classify_posture,
    learn_posture_profiles, PostureProfile, PASSTracker,
)

# dual-task vital-sign model (rate regression + event classification, C3)
from .dual_task import (
    make_dataset, window_features, motion_only_predict, DualTaskMLP, FEATURE_NAMES,
)

# real-capture loader (CSIKit → same CSIResult pipeline; CSIKit is optional)
from .realdata import load_real_csi, load_streams, csidata_to_result, load_amplitude_csv
