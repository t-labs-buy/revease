#!/usr/bin/env python3
"""shift.py — build the Refract images and push them to a Docker Hub registry.

The three services live in ONE repo, distinguished by an image tag prefix:

    tlabsdoc/revease:api-<tag>
    tlabsdoc/revease:worker-<tag>
    tlabsdoc/revease:web-<tag>

Examples
--------
    # Build + push all three as ...:api-v1 / :worker-v1 / :web-v1 (and *-latest)
    python shift.py --tag v1

    # Just the web image, remote-host API base, don't push (build only)
    python shift.py --service web --api-base http://10.0.0.5:8000 --no-push

    # Push exactly one tag name to the repo root: tlabsdoc/revease:demo
    #   (single combined tag is not meaningful for 3 images; use per-service tags)
    python shift.py --tag demo --service all

    # Multi-arch build+push (amd64 + arm64) via buildx
    python shift.py --tag v1 --platform linux/amd64,linux/arm64

Run `docker login` once beforehand (or pass nothing and it will prompt to).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_REPO = "tlabsdoc/revease"

# service -> (dockerfile, extra build args)
SERVICES: dict[str, str] = {
    "api": "infra/docker/api.Dockerfile",
    "worker": "infra/docker/worker.Dockerfile",
    "web": "infra/docker/web.Dockerfile",
}


def sh(cmd: list[str]) -> None:
    print("\n\033[36m$ " + " ".join(cmd) + "\033[0m", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def ensure_docker() -> None:
    if shutil.which("docker") is None:
        sys.exit("error: docker CLI not found on PATH")


def image_ref(repo: str, service: str, tag: str) -> str:
    return f"{repo}:{service}-{tag}"


def build_and_push(
    service: str,
    repo: str,
    tag: str,
    *,
    push: bool,
    platform: str | None,
    api_base: str,
    whisper: bool,
    also_latest: bool,
) -> None:
    dockerfile = SERVICES[service]
    tags = [tag] + (["latest"] if also_latest and tag != "latest" else [])
    refs = [image_ref(repo, service, t) for t in tags]

    build_args: list[str] = []
    if service == "web":
        build_args += ["--build-arg", f"NEXT_PUBLIC_API_BASE={api_base}"]
    if service == "worker":
        build_args += ["--build-arg", f"WHISPER={'1' if whisper else '0'}"]

    tag_flags: list[str] = []
    for r in refs:
        tag_flags += ["-t", r]

    if platform:
        # buildx builds (and pushes in the same step) for one or more platforms.
        cmd = ["docker", "buildx", "build", "--platform", platform,
               "-f", dockerfile, *tag_flags, *build_args]
        cmd += ["--push"] if push else ["--load"]
        cmd += ["."]
        sh(cmd)
        return

    sh(["docker", "build", "-f", dockerfile, *tag_flags, *build_args, "."])
    if push:
        for r in refs:
            sh(["docker", "push", r])


def main() -> int:
    p = argparse.ArgumentParser(description="Build & push Refract images to Docker Hub.")
    p.add_argument("--tag", default="latest", help="image tag suffix, e.g. v1 (default: latest)")
    p.add_argument("--repo", default=DEFAULT_REPO, help=f"registry repo (default: {DEFAULT_REPO})")
    p.add_argument("--service", default="all", choices=["all", *SERVICES],
                   help="which image to build (default: all)")
    p.add_argument("--api-base", default="http://localhost:8000",
                   help="NEXT_PUBLIC_API_BASE baked into the web image")
    p.add_argument("--platform", default=None,
                   help="buildx platforms, e.g. linux/amd64,linux/arm64 (enables buildx + --push)")
    p.add_argument("--no-whisper", action="store_true",
                   help="build the worker without faster-whisper (lighter image)")
    p.add_argument("--no-latest", action="store_true",
                   help="do not also tag/push <service>-latest")
    push_grp = p.add_mutually_exclusive_group()
    push_grp.add_argument("--push", dest="push", action="store_true", default=True,
                          help="push after building (default)")
    push_grp.add_argument("--no-push", dest="push", action="store_false",
                          help="build only, do not push")
    args = p.parse_args()

    ensure_docker()
    services = list(SERVICES) if args.service == "all" else [args.service]

    print(f"Repo:      {args.repo}")
    print(f"Tag:       {args.tag}" + ("" if args.no_latest else "  (+ latest)"))
    print(f"Services:  {', '.join(services)}")
    print(f"Push:      {args.push}" + (f"  platform={args.platform}" if args.platform else ""))

    for svc in services:
        build_and_push(
            svc, args.repo, args.tag,
            push=args.push,
            platform=args.platform,
            api_base=args.api_base,
            whisper=not args.no_whisper,
            also_latest=not args.no_latest,
        )

    print("\n\033[32m✓ done.\033[0m")
    if args.push:
        print("Pushed:")
        for svc in services:
            print(f"  {image_ref(args.repo, svc, args.tag)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as e:
        sys.exit(f"\n\033[31m✗ command failed ({e.returncode})\033[0m")
    except KeyboardInterrupt:
        sys.exit(130)
