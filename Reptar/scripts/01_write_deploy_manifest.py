from __future__ import annotations

from reptar.manifest import write_deploy_manifest


def main() -> int:
    p = write_deploy_manifest()
    print(f"Wrote: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
