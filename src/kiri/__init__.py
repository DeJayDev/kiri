import asyncio

from . import app


def main():
    asyncio.run(app.start())
