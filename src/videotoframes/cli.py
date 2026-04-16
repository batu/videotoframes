"""videotoframes — video to curated key frames.

Pure utility, no AI. Single-decode pipeline: ffmpeg + PySceneDetect + imagehash.dhash.

See ../../docs/slab-project.md for shared project context.
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="videotoframes", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    extract = sub.add_parser("extract", help="Extract curated key frames from a video.")
    extract.add_argument("video", help="Path to MP4 input")
    extract.add_argument("--out", required=True, help="Output frames/ directory")

    manifest = sub.add_parser("manifest", help="Print manifest for an existing frames/ dir.")
    manifest.add_argument("frames_dir")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    # Implementations land during the Worked stage of this card.
    print(f"videotoframes {args.command}: not yet implemented", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
