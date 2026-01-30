from app.supervisor import Supervisor
import uasyncio as asyncio

sup = Supervisor()
asyncio.run(sup.run())

