"""Build local, code-authored pixel panoramas for the sign-in journey."""

from html import escape
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "frontend" / "web" / "assets"


def build(light=False):
    p = (
        dict(
            sky="#fff0d6",
            hills="#bda5bf",
            ground="#dfbf9f",
            leaf="#ce8e59",
            tree="#8c6465",
            road="#796d88",
            line="#ffdfad",
            water="#83a8b5",
            window="#ffdfa1",
        )
        if light
        else dict(
            sky="#142b46",
            hills="#33536e",
            ground="#98becd",
            leaf="#39777a",
            tree="#536079",
            road="#243b54",
            line="#b2dce8",
            water="#285578",
            window="#f4da9a",
        )
    )
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="7680" height="640" viewBox="0 0 7680 640" shape-rendering="crispEdges">'
    ]
    out.append(
        '<defs><filter id="bridge-led" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="3"/><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>'
    )

    def rect(x, y, w, h, c):
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{c}"/>')

    def path(d, c, stroke=None, sw=1):
        out.append(
            f'<path d="{d}" fill="{c}"'
            + (f' stroke="{stroke}" stroke-width="{sw}"' if stroke else "")
            + "/>"
        )

    def text(x, y, value, size=24, c="#e5e8e4"):
        out.append(
            f'<text x="{x}" y="{y}" text-anchor="middle" font-family="Arial,sans-serif" font-size="{size}" font-weight="700" fill="{c}">{escape(value)}</text>'
        )

    def tree(x, y, s=1):
        out.append(f'<g transform="translate({x} {y}) scale({s})">')
        rect(-5, 0, 10, 110, p["tree"])
        path(
            "M-18 0H18V12H34V28H46V44H30V50H50V66H62V80H22V88H-22V80H-62V66H-50V50H-30V44H-46V28H-34V12H-18Z",
            p["leaf"],
        )
        if not light:
            path("M-18 0H18V12H34V20H-34V12H-18ZM-38 48H38V56H50V64H-50V56H-38Z", "#c6e0e7")
        out.append("</g>")

    def lamp(x, y):
        rect(x, y, 6, 140, p["tree"])
        rect(x, y, 38, 6, p["tree"])
        rect(x + 26, y + 6, 20, 18, p["window"])

    def bench(x, y):
        rect(x, y, 90, 10, p["tree"])
        rect(x, y - 30, 90, 24, p["tree"])
        rect(x + 8, y + 10, 8, 25, p["tree"])
        rect(x + 74, y + 10, 8, 25, p["tree"])

    rect(0, 0, 7680, 640, p["sky"])
    for i in range(48):
        x = i * 160
        path(
            f"M{x} 410V{290 - i % 4 * 22}H{x + 40}V{250 - i % 3 * 18}H{x + 90}V300H{x + 135}V410Z",
            p["hills"],
        )
    rect(0, 450, 7680, 190, p["ground"])
    # The supplied reference is the visual authority for this building.
    white = "#e3e6e0"
    stone = "#bbc5cb"
    red = "#a32e43"
    darkred = "#762638"
    glass = "#486371"
    gold = "#d4b762"
    rect(210, 164, 860, 314, white)
    rect(235, 204, 810, 192, darkred)
    for y in range(208, 392, 7):
        rect(235, y, 810, 3, red)
    rect(234, 400, 812, 73, glass)
    for x in range(240, 1040, 66):
        rect(x, 400, 4, 73, stone)
    for x in [222, 1050]:
        rect(x, 190, 18, 288, white)
        rect(x - 7, 466, 32, 12, stone)
    for x in [350, 540, 740, 930]:
        rect(x, 192, 16, 280, white)
        rect(x - 7, 191, 30, 10, stone)
        rect(x - 6, 461, 28, 9, white)
        rect(x - 10, 471, 36, 9, stone)
    rect(196, 170, 888, 20, stone)
    rect(202, 145, 876, 32, white)
    text(640, 168, "ĐẠI HỌC GIAO THÔNG VẬN TẢI THÀNH PHỐ HỒ CHÍ MINH", 20, red)
    path("M198 140 640 40 1082 140Z", white, stone, 8)
    path("M220 132 640 51 1060 132", "none", stone, 4)
    rect(590, 264, 100, 112, gold)
    rect(599, 273, 82, 94, "#c4a953")
    # Raised abstract relief marks follow the gold central panel in the photo.
    for i in range(15):
        rect(610 + i * 17 % 58, 280 + i * 29 % 75, 12, 9, gold)
    for i in range(5):
        rect(198 - i * 8, 480 + i * 7, 884 + i * 16, 7, white)
    for x in [197, 1080]:
        rect(x, 455, 22, 28, stone)
        for dx in [-6, 7, 20]:
            rect(x + dx, 446, 14, 13, red)
    for x in [90, 1190]:
        tree(x, 335, 1.2)
    # Park, riverside, shopfronts, avenue and a bus stop complete the long route.
    for i in range(9):
        tree(1360 + i * 138, 330 + (i % 2) * 25, 0.85 + (i % 3) * 0.15)
    for x in [1470, 1770, 2200]:
        bench(x, 468)
        lamp(x + 100, 322)
    rect(2570, 365, 1260, 117, p["water"])
    rect(2600, 385, 1200, 8, stone)
    for x in range(2610, 3800, 65):
        rect(x, 385, 5, 98, stone)
    rect(2600, 478, 1200, 8, stone)
    # Ba Son's distinctive single curved pylon and cable-stayed main span.
    rect(2600, 350, 1200, 14, p["tree"])
    rect(2600, 346, 1200, 5, white)
    path("M3422 470Q3488 304 3312 146L3330 140Q3532 310 3450 470Z", white if light else "#c2b4f0")
    rect(3408, 463, 60, 19, stone)
    led_blue = "#9d88bd" if light else "#6ce5ff"
    led_pink = "#c9927d" if light else "#d3a3ff"
    if not light:
        out.append('<g filter="url(#bridge-led)">')
    path("M3436 466Q3500 304 3321 144", "none", led_pink, 5)

    def cable_to(x, level, color):
        t = level
        px = (1 - t) ** 2 * 3436 + 2 * (1 - t) * t * 3510 + t * t * 3321
        py = (1 - t) ** 2 * 470 + 2 * (1 - t) * t * 308 + t * t * 143
        path(f"M{px:.1f} {py:.1f}L{x} 347", "none", color, 2.5)

    for i in range(16):
        cable_to(2610 + i * 49, 0.99 - i * 0.024, led_blue if i % 2 else led_pink)
    for i in range(7):
        cable_to(3500 + i * 48, 0.65 + i * 0.055, led_blue if i % 2 else led_pink)
    rect(2600, 345, 1200, 4, led_blue)
    rect(2600, 360, 1200, 3, led_pink)
    for x in range(2610, 3800, 30):
        rect(x, 344, 4, 6, "#e4f8ff" if not light else white)
    if not light:
        out.append("</g>")
    for x in [2640, 2910, 3680, 3770]:
        lamp(x, 370)
        if not light:
            out.append(
                f'<circle cx="{x + 36}" cy="385" r="12" fill="#ffe3a1" opacity=".5" filter="url(#bridge-led)"/>'
            )
    if not light:
        out.append('<g opacity=".3">')
        for i in range(24):
            rect(
                2620 + i * 49, 375 + i % 4 * 26, 28 + i % 3 * 9, 3, led_blue if i % 2 else led_pink
            )
        out.append("</g>")
    text(3660, 455, "CẦU BA SON", 24, white)
    for i in range(5):
        x = 3930 + i * 225
        h = 200 + (i % 3) * 45
        rect(x, 480 - h, 200, h, white if i % 2 else p["tree"])
        rect(x - 6, 474 - h, 212, 12, red)
        for wy in range(510 - h, 410, 47):
            for wx in [x + 20, x + 83, x + 145]:
                rect(wx, wy, 30, 26, p["window"])
        for j in range(10):
            rect(x + j * 20, 410, 20, 17, p["leaf"] if j % 2 else white)
        if i == 2:
            text(x + 100, 453, "CÀ PHÊ", 22, p["window"])
    for i in range(10):
        tree(5210 + i * 120, 334 + (i % 2) * 28, 1.05)
    for x in [5350, 5800, 6200]:
        lamp(x, 325)
    for x in [6510, 6820, 7400, 7560]:
        tree(x, 340, 1)
    rect(6860, 360, 410, 14, red)
    for x in [6880, 7230]:
        rect(x, 373, 8, 110, stone)
    rect(6890, 388, 330, 80, glass)
    bench(6980, 464)
    text(7060, 355, "UTH · VÕ OANH", 22, p["window"])
    # A continuous road and repeating lane pattern make the seam invisible.
    rect(0, 520, 7680, 120, p["road"])
    rect(0, 518, 7680, 5, p["line"])
    rect(0, 625, 7680, 5, p["line"])
    for x in range(0, 7680, 160):
        rect(x, 575, 80, 4, p["line"])
    for i in range(32):
        x = 160 + i * 240
        path(f"M{x} 116l12 6 12-6 12 6 12-6v7l-12 8-12-8-12 8-12-8Z", p["tree"])
    out.append("</svg>")
    (ASSETS / ("uth-route-light.svg" if light else "uth-route-dark.svg")).write_text(
        "\n".join(out), encoding="utf-8"
    )


if __name__ == "__main__":
    build()
    build(True)
