import asyncio
import sys


def main():
    # Imported inside the entrypoint so importing the package itself stays cheap
    # and free of circular-import hazards at package-init time.
    from kiri import app, auth, db, usage

    args = sys.argv[1:]
    command = args[0] if args else None

    if command == "usage":
        db.bind()
        usage.print_tally()
        return
    if command == "auth":
        auth.run(args[1:])
        return
    if command == "mcp":
        auth.mcp(args[1:])
        return
    asyncio.run(app.start())
