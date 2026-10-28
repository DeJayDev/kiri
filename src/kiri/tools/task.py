from kiri.engine import agent
from kiri.engine.context import Session
from kiri.scheduling import events
from kiri.tools.reload import Restart

SCHEMA = {
    "name": "task",
    "description": (
        "Hand a self-contained piece of work to a sub-agent with a fresh context and "
        "the same tools. It sees only the prompt, so put everything it needs there."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The whole job, written for a reader with no other context."},
            "wait": {
                "type": "boolean",
                "description": (
                    "True to get its answer back here before you reply; several waited tasks run at once. "
                    "False to run it in the background and have it message the owner itself when done."
                ),
            },
        },
        "required": ["prompt", "wait"],
    },
}


async def _drop(_message):
    pass


def build(channel_id, base_system, tools):
    async def task(args):
        if not args["wait"]:
            events.put(args["prompt"])
            return "started in the background; it will message the owner when done"
        try:
            return await agent.run(Session(channel_id, base_system), args["prompt"], tools(), _drop)
        except Restart:
            return "error: reload is not available inside a task; reload from the main conversation"

    return task
