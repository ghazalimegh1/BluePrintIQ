from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


MODELS = {
    "grounding-dino-tiny": "IDEA-Research/grounding-dino-tiny",
    "sam2.1-hiera-small": "facebook/sam2.1-hiera-small",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache the public specialist vision checkpoints used by STOA."
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=sorted(MODELS),
        required=True,
        help="Select the checkpoints to download; Qwen is remote-only on the target machine.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Optional Hugging Face cache directory. Defaults to the standard HF cache.",
    )
    args = parser.parse_args()
    for model_key in args.models:
        model_id = MODELS[model_key]
        options = {
            "repo_id": model_id,
            "allow_patterns": [
                "*.json",
                "*.safetensors",
                "*.txt",
                "*.model",
                "*.tiktoken",
                "*.vocab",
                "*.merges",
            ],
        }
        if args.cache_dir:
            options["cache_dir"] = str(args.cache_dir)
        path = snapshot_download(**options)
        print(f"Cached {model_id} at {path}")


if __name__ == "__main__":
    main()
