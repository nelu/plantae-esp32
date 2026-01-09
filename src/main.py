

def main():
    import time
    print("BOOT: Waiting 3s for network cleanup...")
    time.sleep(3)
    
    import uasyncio as asyncio
    from app.supervisor import Supervisor
    
    sup = Supervisor("config.json")
    asyncio.run(sup.run())

main()
