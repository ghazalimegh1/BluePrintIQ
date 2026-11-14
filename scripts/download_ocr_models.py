from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise SystemExit(
            "PaddleOCR is not installed; run python -m pip install -r requirements-vision-ocr.txt."
        ) from exc

    cache_dir = Path(
        os.getenv("PADDLE_PDX_CACHE_HOME", str(Path.home() / ".paddlex"))
    )
    PaddleOCR(
        lang="en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device="cpu",
        enable_mkldnn=False,
        cpu_threads=1,
    )
    print(f"English PaddleOCR models are cached under: {cache_dir / 'official_models'}")


if __name__ == "__main__":
    main()
