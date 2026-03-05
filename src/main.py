from app.supervisor import Supervisor
import machine, sys
import uasyncio as asyncio
from logging import LOG

try:
    sup = Supervisor()
    asyncio.run(sup.run())
except Exception as e:
    LOG.error("Fatal error in main:")
    sys.print_exception(e)



