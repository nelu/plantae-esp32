def run():
    import time
    print("BOOT: Waiting 5s for network cleanup...")
    time.sleep(5)
    
    import uasyncio as asyncio
    from app.supervisor import Supervisor
    
    sup = Supervisor("config.json")
    asyncio.run(sup.run())

