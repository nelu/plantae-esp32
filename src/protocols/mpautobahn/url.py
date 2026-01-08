def parse_ws_url(url: str):
    """
    Parse ws/wss URL without urllib.
    Returns: (scheme, host, port, path_with_query)
    """
    if url.startswith("ws://"):
        scheme, rest, default_port = "ws", url[5:], 80
    elif url.startswith("wss://"):
        scheme, rest, default_port = "wss", url[6:], 443
    else:
        raise ValueError("unsupported scheme: %r" % url)

    slash = rest.find("/")
    if slash == -1:
        hostport, path = rest, "/"
    else:
        hostport, path = rest[:slash], rest[slash:] or "/"

    if ":" in hostport:
        host, port_s = hostport.rsplit(":", 1)
        if not port_s:
            raise ValueError("bad port: %r" % url)
        port = int(port_s)
    else:
        host, port = hostport, default_port

    if not host:
        raise ValueError("missing host: %r" % url)

    return (scheme, host, port, path)
