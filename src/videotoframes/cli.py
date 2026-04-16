"""videotoframes CLI entry point.

Stdlib argparse, lazy subcommand imports — cold-start `--help` must
stay under 200ms, which means NO cv2/scenedetect imports at this
module's top level.

See ../../docs/slab-project.md for shared project context.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="videotoframes",
        description="Video → curated key frames + manifest. Standalone CLI, no AI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser(
        "extract",
        help="Extract curated key frames from a video.",
    )
    extract.add_argument("video", type=Path, help="Path to input video (MP4).")
    extract.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory (created; refuses to overwrite without --force).",
    )
    extract.add_argument(
        "--fps",
        type=int,
        default=60,
        help="FPS to normalize the input to before detection (default: 60).",
    )
    extract.add_argument(
        "--force",
        action="store_true",
        help="Overwrite --out if it already exists.",
    )

    manifest_cmd = sub.add_parser(
        "manifest",
        help="Print the manifest.yaml from a frames directory.",
    )
    manifest_cmd.add_argument(
        "frames_dir",
        type=Path,
        help="Directory produced by `videotoframes extract`.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "extract":
        # Lazy import — cv2/scenedetect are heavy, --help must not pay
        # their cost.
        from videotoframes.commands.extract import run_extract

        return run_extract(
            args.video,
            args.out,
            fps=args.fps,
            force=args.force,
        )

    if args.command == "manifest":
        from videotoframes.commands.manifest import run_manifest

        return run_manifest(args.frames_dir)

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
