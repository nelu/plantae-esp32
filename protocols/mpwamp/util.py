import urandom

def rid():
    return urandom.getrandbits(31)
