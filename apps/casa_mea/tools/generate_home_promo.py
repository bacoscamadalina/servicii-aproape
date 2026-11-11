#!/usr/bin/env python3
"""Generate the localized, narrated home-page promotion films with FFmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = APP_ROOT / "services" / "static" / "services"
VIDEO_ROOT = STATIC_ROOT / "video"
PRESENTER_IMAGE = VIDEO_ROOT / "promo-presenter.webp"
NARRATION_ROOT = APP_ROOT / "tools" / "assets"
DISPLAY_FONT = STATIC_ROOT / "fonts" / "NimbusSansNarrow-Bold.otf"
BODY_FONT = STATIC_ROOT / "fonts" / "Carlito-Regular.ttf"
BODY_BOLD_FONT = STATIC_ROOT / "fonts" / "Carlito-Bold.ttf"

COLORS = {
    "paper": "#eeeee8", "deep_paper": "#dfe5dc", "white": "#fffefa",
    "ink": "#1f3331", "soft_ink": "#526964", "green": "#365e55",
    "brick": "#bd6749", "line": "#aeb6b0",
}

COPY = {
    "ro": {
        "narration": (
            "Bună! Dacă ai un proiect pentru casă, Servicii Aproape te ajută să găsești "
            "firme care lucrează în zona ta. Alegi județul, localitatea și serviciul de care "
            "ai nevoie. Compari firmele, iar în profilurile complete găsești descrierea, "
            "datele de contact și fotografii ale lucrărilor. Când ai găsit firma potrivită, "
            "o poți contacta direct sau îi poți trimite o solicitare de ofertă. Simplu, "
            "local și ușor de verificat."
        ),
        "presenter_title": "GĂSEȘTI FIRMA POTRIVITĂ,", "presenter_subtitle": "APROAPE DE TINE.",
        "presenter_body": "Un ghid rapid prin ServiciiAproape.",
        "search_title": "Spune-ne unde și ce ai nevoie.",
        "county": "JUDEȚ", "county_value": "Neamț", "locality": "LOCALITATE",
        "locality_value": "Piatra-Neamț", "service": "SERVICIU",
        "service_value": "Construcții & renovări", "search": "CAUTĂ FIRME",
        "results_title": "Compară profilurile complete.", "result_one": "CONSTRUCT NORD SRL",
        "result_two": "CASA VERDE PRO SRL", "complete": "PROFIL COMPLET",
        "details": "Descriere  •  contact  •  lucrări", "contact": "CONTACTEAZĂ",
        "closing": "GATA SĂ ÎNCEPI?",
        "closing_body": "Alege localitatea și serviciul. Noi îți arătăm opțiunile.",
        "cta": "ÎNCEPE CĂUTAREA",
    },
    "en": {
        "narration": (
            "Hello! If you have a home project, Servicii Aproape helps you find companies "
            "working in your area. Choose your county, locality, and the service you need. "
            "Compare companies, then open complete profiles to see descriptions, contact "
            "details, and photographs of completed work. Once you find the right company, "
            "contact it directly or send a quote request. Simple, local, and easy to check."
        ),
        "presenter_title": "FIND THE RIGHT COMPANY,", "presenter_subtitle": "CLOSE TO HOME.",
        "presenter_body": "A quick guide to ServiciiAproape.",
        "search_title": "Tell us where and what you need.",
        "county": "COUNTY", "county_value": "Neamț", "locality": "LOCALITY",
        "locality_value": "Piatra-Neamț", "service": "SERVICE",
        "service_value": "Construction & renovation", "search": "FIND COMPANIES",
        "results_title": "Compare complete profiles.", "result_one": "CONSTRUCT NORD SRL",
        "result_two": "CASA VERDE PRO SRL", "complete": "COMPLETE PROFILE",
        "details": "Description  •  contact  •  projects", "contact": "CONTACT",
        "closing": "READY TO START?",
        "closing_body": "Choose the place and service. We will show you the options.",
        "cta": "START SEARCHING",
    },
}


def _escape(value: str | Path) -> str:
    """Escape text for one FFmpeg filter argument without invoking a shell."""

    return str(value).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _text(value: str, *, x: str, y: int, size: int, color: str, font: Path = BODY_FONT) -> str:
    """Return a consistently styled FFmpeg drawtext filter."""

    return (
        f"drawtext=fontfile='{_escape(font)}':text='{_escape(value)}':"
        f"x={x}:y={y}:fontsize={size}:fontcolor={color}:borderw=0:text_shaping=1"
    )


def _brand_filters(*, light: bool = False) -> list[str]:
    """Return the persistent masthead shared by every scene."""

    foreground = COLORS["white"] if light else COLORS["ink"]
    return [
        f"drawbox=x=64:y=56:w=42:h=42:color={COLORS['green']}:t=fill",
        f"drawbox=x=72:y=69:w=26:h=21:color={COLORS['paper']}:t=4",
        f"drawbox=x=64:y=112:w=1152:h=2:color={foreground}:t=fill",
        _text("Servicii", x="124", y=55, size=34, color=foreground, font=DISPLAY_FONT),
        _text("Aproape", x="234", y=55, size=34, color=COLORS["brick"], font=DISPLAY_FONT),
    ]


def _graphic_scenes(copy: dict[str, str]) -> list[str]:
    """Build the search, comparison and closing chapters."""

    search = _brand_filters() + [
        _text(copy["search_title"], x="64", y=154, size=54, color=COLORS["ink"], font=DISPLAY_FONT),
    ]
    fields = (
        (64, 246, 220, copy["county"], copy["county_value"]),
        (304, 246, 300, copy["locality"], copy["locality_value"]),
        (624, 246, 360, copy["service"], copy["service_value"]),
    )
    for x, y, width, label, value in fields:
        search.extend([
            f"drawbox=x={x}:y={y}:w={width}:h=128:color={COLORS['white']}:t=fill",
            f"drawbox=x={x}:y={y}:w={width}:h=128:color={COLORS['line']}:t=2",
            _text(label, x=str(x + 18), y=y + 18, size=17, color=COLORS["soft_ink"], font=BODY_BOLD_FONT),
            _text(value, x=str(x + 18), y=y + 62, size=27, color=COLORS["ink"], font=BODY_BOLD_FONT),
        ])
    search.extend([
        f"drawbox=x=1004:y=246:w=212:h=128:color={COLORS['brick']}:t=fill",
        _text(copy["search"], x="1040", y=292, size=24, color=COLORS["white"], font=BODY_BOLD_FONT),
        f"drawbox=x=64:y=460:w=1152:h=112:color={COLORS['deep_paper']}:t=fill",
        _text("01", x="92", y=495, size=22, color=COLORS["brick"], font=BODY_BOLD_FONT),
        _text("02", x="344", y=495, size=22, color=COLORS["brick"], font=BODY_BOLD_FONT),
        _text("03", x="668", y=495, size=22, color=COLORS["brick"], font=BODY_BOLD_FONT),
        f"drawbox=x=740:y=528:w=430:h=3:color={COLORS['green']}:t=fill",
    ])

    results = _brand_filters() + [
        _text(copy["results_title"], x="64", y=150, size=54, color=COLORS["ink"], font=DISPLAY_FONT),
        f"drawbox=x=64:y=238:w=1152:h=160:color={COLORS['green']}:t=fill",
        f"drawbox=x=90:y=273:w=78:h=78:color={COLORS['paper']}:t=fill",
        _text("CN", x="108", y=291, size=30, color=COLORS["green"], font=DISPLAY_FONT),
        _text(copy["result_one"], x="198", y=268, size=34, color=COLORS["white"], font=DISPLAY_FONT),
        _text(copy["complete"], x="198", y=316, size=16, color="#cddbd3", font=BODY_BOLD_FONT),
        _text(copy["details"], x="470", y=317, size=20, color=COLORS["white"]),
        f"drawbox=x=1014:y=275:w=170:h=76:color={COLORS['brick']}:t=fill",
        _text(copy["contact"], x="1040", y=299, size=20, color=COLORS["white"], font=BODY_BOLD_FONT),
        f"drawbox=x=64:y=420:w=1152:h=126:color={COLORS['white']}:t=fill",
        f"drawbox=x=90:y=444:w=68:h=68:color={COLORS['deep_paper']}:t=fill",
        _text("CV", x="105", y=458, size=27, color=COLORS["ink"], font=DISPLAY_FONT),
        _text(copy["result_two"], x="188", y=447, size=31, color=COLORS["ink"], font=DISPLAY_FONT),
        _text(copy["details"], x="188", y=489, size=19, color=COLORS["soft_ink"]),
    ]

    closing = _brand_filters() + [
        _text(copy["closing"], x="64", y=210, size=82, color=COLORS["ink"], font=DISPLAY_FONT),
        _text(copy["closing_body"], x="64", y=340, size=29, color=COLORS["soft_ink"]),
        f"drawbox=x=64:y=438:w=318:h=78:color={COLORS['green']}:t=fill",
        _text(copy["cta"], x="96", y=462, size=22, color=COLORS["white"], font=BODY_BOLD_FONT),
        f"drawbox=x=1110:y=446:w=56:h=4:color={COLORS['brick']}:t=fill",
        f"drawbox=x=1162:y=432:w=4:h=32:color={COLORS['brick']}:t=fill",
    ]
    return [",".join(scene) for scene in (search, results, closing)]


def _generate(locale: str) -> None:
    """Generate one narrated MP4 and its matching static poster."""

    if not PRESENTER_IMAGE.exists():
        raise FileNotFoundError(f"Missing presenter asset: {PRESENTER_IMAGE}")

    copy = COPY[locale]
    VIDEO_ROOT.mkdir(parents=True, exist_ok=True)
    narration = NARRATION_ROOT / f"home-promo-narration-{locale}.flac"
    output = VIDEO_ROOT / f"servicii-aproape-home-{locale}.mp4"
    poster = VIDEO_ROOT / f"servicii-aproape-home-{locale}.webp"
    if not narration.exists():
        raise FileNotFoundError(f"Missing locally generated narration: {narration}")

    presenter = [
        "scale=1280:720:force_original_aspect_ratio=increase", "crop=1280:720",
        "zoompan=z='min(zoom+0.00017,1.025)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=210:s=1280x720:fps=30",
        "drawbox=x=650:y=0:w=630:h=720:color=#1f3331@0.91:t=fill", *_brand_filters(light=True),
        _text(copy["presenter_title"], x="704", y=236, size=52, color=COLORS["white"], font=DISPLAY_FONT),
        _text(copy["presenter_subtitle"], x="704", y=294, size=52, color=COLORS["brick"], font=DISPLAY_FONT),
        _text(copy["presenter_body"], x="704", y=386, size=25, color="#dfe5dc"),
        f"drawbox=x=704:y=444:w=88:h=6:color={COLORS['brick']}:t=fill",
    ]
    graphics = _graphic_scenes(copy)
    filters = ";".join([
        f"[0:v]{','.join(presenter)}[s0]",
        *[f"[{index}:v]{scene}[s{index}]" for index, scene in enumerate(graphics, start=1)],
        "[s0][s1]xfade=transition=fade:duration=0.6:offset=6.4[x1]",
        "[x1][s2]xfade=transition=fade:duration=0.6:offset=13.8[x2]",
        "[x2][s3]xfade=transition=fade:duration=0.6:offset=21.2,format=yuv420p[outv]",
        "[4:a]loudnorm=I=-16:TP=-1.5:LRA=7,afade=t=in:st=0:d=0.2,apad=whole_dur=29.2[outa]",
    ])
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-t", "7", "-i", str(PRESENTER_IMAGE)]
    for _ in graphics:
        command.extend(["-f", "lavfi", "-i", "color=c=#eeeee8:s=1280x720:d=8:r=30"])
    command.extend([
        "-i", str(narration), "-filter_complex", filters, "-map", "[outv]", "-map", "[outa]",
        "-t", "29.2", "-c:v", "libx264", "-preset", "slow", "-crf", "24",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output),
    ])
    subprocess.run(command, check=True)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "1", "-i", str(output),
        "-frames:v", "1", "-c:v", "libwebp", "-quality", "84", str(poster),
    ], check=True)


def main() -> None:
    """Regenerate both language variants from the same visual contract."""

    for locale in COPY:
        _generate(locale)


if __name__ == "__main__":
    main()
