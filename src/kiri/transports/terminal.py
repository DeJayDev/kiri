import asyncio
import sys
from contextlib import asynccontextmanager

from kiri.transports.base import Inbound, Transport

_CHANNEL = 0


def _picked(answer, options, multi_select):
    numbers = answer.split(",") if multi_select else [answer]
    labels = []
    for number in numbers:
        number = number.strip()
        if not number.isdigit() or not 1 <= int(number) <= len(options):
            return None
        labels.append(options[int(number) - 1]["label"])
    return ", ".join(labels)


class Terminal(Transport):
    name = "terminal"

    @classmethod
    def missing(cls):
        return None

    async def run(self, on_message):
        print("kiri terminal. ctrl-d to quit, 'stop' to cancel a running turn.")
        while True:
            try:
                line = await asyncio.to_thread(input, "\n> ")
            except (EOFError, KeyboardInterrupt):
                print()
                return

            if not line.strip():
                continue

            task = await on_message(Inbound(channel_id=_CHANNEL, text=line))
            # One person, one prompt: wait rather than race the next prompt.
            if task:
                await task

    async def send(self, channel_id, text):
        print(text or "(no output)", flush=True)

    async def ask(self, channel_id, question, options, multi_select):
        lines = [question]
        for index, option in enumerate(options, 1):
            description = option.get("description")
            suffix = f" -- {description}" if description else ""
            lines.append(f"  {index}) {option['label']}{suffix}")
        lines.append("pick by number, or type your own answer.")
        print("\n".join(lines), flush=True)

        # Safe to read stdin here: run() awaits the turn before prompting again,
        # so nothing else is reading.
        answer = (await asyncio.to_thread(input, "\n? ")).strip()
        return _picked(answer, options, multi_select) or answer

    @asynccontextmanager
    async def typing(self, channel_id):
        yield

    async def notify_owner(self, text):
        print(text, file=sys.stderr, flush=True)
