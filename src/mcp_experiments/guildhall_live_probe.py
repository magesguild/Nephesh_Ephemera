"""Read-only XMPP connectivity probe for the live Guildhall deployment.

The probe authenticates and waits for session start, then disconnects. It does
not join a MUC, send a message, clean occupants, alter MongooseIM, or start a
Qualiant/OpenCode session.
"""

from __future__ import annotations

import argparse
import asyncio
import ssl
import sys

from dotenv import load_dotenv


async def probe(timeout: float) -> None:
    import slixmpp

    from .config import settings

    client = slixmpp.ClientXMPP(settings.guildhall_jid, settings.guildhall_password)
    client.enable_direct_tls = False
    client.ssl_context.check_hostname = False
    client.ssl_context.verify_mode = ssl.CERT_NONE
    started = asyncio.Event()
    failed: list[str] = []

    async def session_start(_event: object) -> None:
        started.set()

    def connection_failed(event: object) -> None:
        failed.append(str(event))

    client.add_event_handler("session_start", session_start)
    client.add_event_handler("connection_failed", connection_failed)
    try:
        await client.connect(
            host=settings.guildhall_server,
            port=settings.guildhall_port,
        )
        await asyncio.wait_for(started.wait(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        reason = failed[-1] if failed else "session start timed out"
        raise RuntimeError(reason) from exc
    finally:
        client.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        help="deployment-owned environment file; values are never printed",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file, override=True)
    try:
        asyncio.run(probe(args.timeout))
    except Exception as exc:
        print(f"Guildhall connectivity probe failed: {exc}", file=sys.stderr)
        return 1
    print("Guildhall connectivity probe passed: authenticated session started")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
