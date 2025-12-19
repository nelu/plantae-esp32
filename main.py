import uasyncio as asyncio
from app.supervisor import Supervisor

def main():
    sup = Supervisor("config.json")
    asyncio.run(sup.run())

#main()
