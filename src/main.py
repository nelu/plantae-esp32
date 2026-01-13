try:
    from app.supervisor import start
    start()
except Exception as e:
    # Robust logging for failures at boot
    print("Fatal boot error:", e)
    # Optional: hardware watchdog or auto-reset logic
    # machine.reset()
