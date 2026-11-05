import argparse
import csv
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = Path(
    os.getenv("ITS_CTU_DATASET_DIR", str(ROOT / "data" / "datasets" / "bike_back_ctu"))
)
OUT_CSV = ROOT / "data" / "benchmark" / "ground_truth" / "bike_back_ctu_ground_truth_template.csv"


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

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "expected_plate", "label", "notes"])
        writer.writeheader()
        for image_path in images:
            writer.writerow(
                {
                    "file": image_path.name,
                    "expected_plate": "",
                    "label": "todo",
                    "notes": "fill manually",
                }
            )

    print(OUT_CSV)
    print(f"count={len(images)}")


if __name__ == "__main__":
    main()
