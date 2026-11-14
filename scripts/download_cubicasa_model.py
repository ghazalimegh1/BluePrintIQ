from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import gdown


ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPOSITORY = "https://github.com/CubiCasa/CubiCasa5k.git"
CHECKPOINT_FILE_ID = "1gRB7ez1e4H7a9Y09lLqRuna0luZO5VRK"
DEFAULT_SOURCE_DIR = ROOT / "runtime" / "cubicasa-source"
DEFAULT_CHECKPOINT = ROOT / "runtime" / "models" / "model_best_val_loss_var.pkl"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download the official non-commercial CubiCasa5K model source and checkpoint."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    args = parser.parse_args()

    source_dir = args.source_dir.expanduser().resolve()
    if not (source_dir / "floortrans" / "models").is_dir():
        if source_dir.exists() and any(source_dir.iterdir()):
            raise SystemExit(
                f"Source directory exists but is not a CubiCasa checkout: {source_dir}"
            )
        source_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", SOURCE_REPOSITORY, str(source_dir)],
            check=True,
        )

    checkpoint = args.checkpoint.expanduser().resolve()
    if not checkpoint.is_file():
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        downloaded = gdown.download(
            id=CHECKPOINT_FILE_ID,
            output=str(checkpoint),
            quiet=False,
        )
        if downloaded is None or not checkpoint.is_file() or checkpoint.stat().st_size < 1_000_000:
            raise SystemExit("CubiCasa checkpoint download failed or returned an invalid file.")

    print(f"CubiCasa source: {source_dir}")
    print(f"CubiCasa checkpoint: {checkpoint}")
    print("Set STOA_CUBICASA_SOURCE_DIR and STOA_CUBICASA_CHECKPOINT to these paths.")
    print("CubiCasa5K is CC BY-NC 4.0; use only in eligible non-commercial work and retain attribution.")


if __name__ == "__main__":
    main()
