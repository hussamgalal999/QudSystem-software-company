#!/usr/bin/env python3
"""Issue a one-time Qudron approval token from an owner-only environment."""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from approval_service import ApprovalTokenIssuer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", required=True)
    parser.add_argument("--resource-id", required=True)
    parser.add_argument("--ttl-seconds", type=int, default=300)
    args = parser.parse_args()
    actor = getpass.getuser().strip()
    if not actor:
        parser.error("the authenticated operating-system user could not be determined")
    issuer = ApprovalTokenIssuer.from_environment()
    token = issuer.issue(
        action=args.action,
        resource_id=args.resource_id,
        approved_by=f"os-user:{actor}",
        ttl_seconds=args.ttl_seconds,
    )
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
