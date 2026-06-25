from ..tools import build as build_registry
from . import agent


async def run_turn(session, text, store, mcp_tools):
    # The single path both live DMs and scheduled jobs run through: assemble the
    # tools for this channel, then run the agent loop.
    registry = build_registry(store, session.channel_id, mcp_tools)
    return await agent.run(session, text, registry)
