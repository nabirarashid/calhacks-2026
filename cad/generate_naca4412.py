#!/usr/bin/env python3
"""Generate a closed, unit-chord, inverted NACA 4412 profile as ASCII DXF."""

import math
import sys
from pathlib import Path


DEFAULT_OUTPUT = Path(__file__).parent / "assets" / "naca4412_inverted_unit.dxf"
DEFAULT_R12_OUTPUT = Path(__file__).parent / "assets" / "naca4412_inverted_unit_r12.dxf"
POINT_COUNT = 81
CAMBER = 0.04
CAMBER_POSITION = 0.4
THICKNESS = 0.12


def profile_points():
    """Return closed-loop coordinates, with 81 cosine-spaced stations per side."""
    upper = []
    lower = []
    for i in range(POINT_COUNT):
        theta = math.pi * i / (POINT_COUNT - 1)
        x = (1.0 - math.cos(theta)) / 2.0
        yt = 5.0 * THICKNESS * (
            0.2969 * math.sqrt(x)
            - 0.1260 * x
            - 0.3516 * x * x
            + 0.2843 * x ** 3
            - 0.1036 * x ** 4
        )
        if x < CAMBER_POSITION:
            yc = CAMBER / (CAMBER_POSITION ** 2) * (2.0 * CAMBER_POSITION * x - x * x)
            dyc = 2.0 * CAMBER / (CAMBER_POSITION ** 2) * (CAMBER_POSITION - x)
        else:
            yc = CAMBER / ((1.0 - CAMBER_POSITION) ** 2) * (
                (1.0 - 2.0 * CAMBER_POSITION) + 2.0 * CAMBER_POSITION * x - x * x
            )
            dyc = 2.0 * CAMBER / ((1.0 - CAMBER_POSITION) ** 2) * (CAMBER_POSITION - x)
        angle = math.atan(dyc)
        xu = x - yt * math.sin(angle)
        yu = yc + yt * math.cos(angle)
        xl = x + yt * math.sin(angle)
        yl = yc - yt * math.cos(angle)
        # Invert about the chord axis. Traversal runs LE to TE, then TE to LE.
        upper.append((xu, -yu))
        lower.append((xl, -yl))
    loop = upper + list(reversed(lower[1:]))
    loop.append(loop[0])
    return loop


def dxf_text(points):
    lines = [
        "0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1015",
        "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES", "0",
        "LWPOLYLINE", "100", "AcDbEntity", "8", "0", "100",
        "AcDbPolyline", "90", str(len(points)), "70", "1",
    ]
    for x, y in points:
        lines.extend(("10", "{:.12f}".format(x), "20", "{:.12f}".format(y)))
    lines.extend(("0", "ENDSEC", "0", "EOF", ""))
    return "\n".join(lines)


def r12_dxf_text(points):
    """Serialize the same closed loop as plain R12 LINE entities."""
    lines = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009",
             "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        lines.extend(("0", "LINE", "8", "0", "10", "{:.12f}".format(x1),
                      "20", "{:.12f}".format(y1), "30", "0.0",
                      "11", "{:.12f}".format(x2), "21", "{:.12f}".format(y2),
                      "31", "0.0"))
    lines.extend(("0", "ENDSEC", "0", "EOF", ""))
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    if args and args[0] == "--r12":
        output = Path(args[1]) if len(args) > 1 else DEFAULT_R12_OUTPUT
        content = r12_dxf_text(profile_points())
    else:
        output = Path(args[0]) if args else DEFAULT_OUTPUT
        content = dxf_text(profile_points())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(content)


if __name__ == "__main__":
    main()
