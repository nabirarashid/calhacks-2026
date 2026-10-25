"""Put the demo wing back to its baseline design (PLAN.md A6). Run: make reset-wing"""
import os

from cad import variables

UNITS = {"aoa_deg": "deg", "span_mm": "mm", "chord_mm": "mm", "flap_angle_deg": "deg", "flap_chord_frac": "",
         "endplate_height_mm": "mm"}
BASELINE = {"aoa_deg": 6.0, "span_mm": 850.0, "chord_mm": 280.0, "flap_angle_deg": 10.0, "flap_chord_frac": 0.3,
            "endplate_height_mm": 200.0}

if __name__ == "__main__":
    os.environ.setdefault("DARWIN_ONSHAPE_WRITE_DOCS", "DARWIN_DOC_WING")
    ref = variables.apply_values(os.environ["DARWIN_DOC_WING"], BASELINE, UNITS)
    print("wing reset:", ref.status, ref.error or "")
