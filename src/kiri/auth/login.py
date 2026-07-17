import time


async def login(provider, say):
    device = await provider.begin_login()
    minutes = max(1, int((device.expires_at - time.time()) // 60))
    await say(
        f"{provider.name} login needed.\n"
        f"open {device.verification_uri}\n"
        f"code: {device.user_code}\n"
        f"(expires in {minutes}m -- pick up where we left off)"
    )
    await provider.finish_login(device)
    await say(f"{provider.name} authorized.")
