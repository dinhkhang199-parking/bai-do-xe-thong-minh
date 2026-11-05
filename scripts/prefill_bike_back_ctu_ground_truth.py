import argparse
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app_service import process_plate_image

DATASET_DIR = Path(
    os.getenv("ITS_CTU_DATASET_DIR", str(ROOT / "data" / "datasets" / "bike_back_ctu"))
)
OUT_CSV = ROOT / "data" / "benchmark" / "ground_truth" / "bike_back_ctu_ground_truth_prefilled.csv"
REVIEW_MD = ROOT / "data" / "benchmark" / "review" / "bike_back_ctu_ground_truth_review.md"


def main():
    parser = argparse.ArgumentParser(
        description="Legacy CTU dataset utility; use field_evaluate.py for independent evaluation."
    )
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    args = parser.parse_args()
    images = sorted([p for p in args.dataset_dir.glob("*.jpg") if p.is_file()])
    if not images:
        raise SystemExit(
            f"No JPG files found in {args.dataset_dir}; supply --dataset-dir or ITS_CTU_DATASET_DIR"
        )

    rows = []
    review_lines = [
        "# Bike_back_ctu Ground Truth Review",
        "",
        "Gợi ý OCR để phát triển; không phải nhãn người review độc lập cho tập test.",
        "",
    ]

    for idx, image_path in enumerate(images, start=1):
        try:
            processed = process_plate_image(
                str(image_path), ocr_engine="fast-alpr-easyocr", use_hardcase=False
            )
            ocr = processed.ocr
            suggestion = (ocr.get("text") or "").strip()
            raw_text = (ocr.get("raw_text") or "").strip()
            plate_type = (ocr.get("plate_type") or "").strip()
            conf = float(ocr.get("confidence", 0.0) or 0.0)
            usable = bool(ocr.get("is_usable", False))
            note = (ocr.get("quality_note") or "").strip()
        except Exception as exc:
            suggestion = ""
            raw_text = ""
            plate_type = ""
            conf = 0.0
            usable = False
            note = f"exception: {type(exc).__name__}: {exc}"

        rows.append(
            {
                "file": image_path.name,
                "expected_plate": "",
                "ocr_suggestion": suggestion,
                "raw_text": raw_text,
                "plate_type": plate_type,
                "confidence": conf,
                "is_usable": usable,
                "label": "todo",
                "notes": note,
            }
        )

        review_lines.extend(
            [
                f"## {idx}. {image_path.name}",
                f"- OCR suggestion: `{suggestion or '(empty)'}`",
                f"- Raw text: `{raw_text or '(empty)'}`",
                f"- Plate type: `{plate_type or '(unknown)'}`",
                f"- Confidence: `{conf:.2f}`",
                f"- Usable: `{usable}`",
                f"- Note: {note or '-'}",
                "",
            ]
        )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "file",
                "expected_plate",
                "ocr_suggestion",
                "raw_text",
                "plate_type",
                "confidence",
                "is_usable",
                "label",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    REVIEW_MD.write_text("\n".join(review_lines), encoding="utf-8")
    print(OUT_CSV)
    print(REVIEW_MD)
    print(f"count={len(rows)}")


if __name__ == "__main__":
    main()
