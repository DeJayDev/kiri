import asyncio
import sys


def main():
    # Imported inside the entrypoint so importing the package itself stays cheap
    # and free of circular-import hazards at package-init time.
    from kiri import app, db, usage

    args = sys.argv[1:]
    if args and args[0] == "usage":
        db.bind()
        usage.print_tally()
        return
    asyncio.run(app.start())
