import gc

try:
    import uos as os
except ImportError:
    import os


def _url_is_http(url: str) -> bool:
    return url.split(":", 1)[0] in ("http", "https")


def _safe_entry_name(name: str) -> str:
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    name = name.lstrip("/")
    if not name:
        return ""

    parts = []
    for part in name.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            raise ValueError("Unsafe path in flash archive")
        parts.append(part)
    return "/".join(parts)


def _mkdir(path: str) -> None:
    try:
        os.mkdir(path)
    except OSError as err:
        if getattr(err, "errno", None) != 17:
            raise


def _mkdir_parents(path: str) -> None:
    parent, _, _ = path.rpartition("/")
    if not parent:
        return

    current = ""
    for part in parent.split("/"):
        if not part:
            continue
        current = (current + "/" + part) if current else part
        _mkdir(current)


def _download_to_file(url: str, filename: str, chunk_size: int = 512, **kw) -> None:
    if _url_is_http(url):
        import requests

        response = requests.get(url, **kw)
        code = response.status_code
        if code != 200:
            response.close()
            raise ValueError("HTTP Error: %s" % code)
        try:
            with open(filename, "wb") as out:
                while True:
                    chunk = response.raw.read(chunk_size)
                    if not chunk:
                        break
                    out.write(chunk)
        finally:
            response.close()
        return

    with open(url, "rb") as src, open(filename, "wb") as out:
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            out.write(chunk)


def _extract_tar_gz(filename: str, chunk_size: int = 512, verbose: bool = True) -> None:
    import deflate
    import tarfile

    with open(filename, "rb") as in_file:
        gzip_stream = deflate.DeflateIO(in_file, deflate.GZIP)
        tar_stream = tarfile.TarFile(fileobj=gzip_stream)
        for member in tar_stream:
            raw_name = member.name
            entry_name = _safe_entry_name(raw_name)
            if not entry_name:
                continue

            is_dir = raw_name.endswith("/")
            if is_dir:
                _mkdir_parents(entry_name)
                _mkdir(entry_name)
                continue

            _mkdir_parents(entry_name)
            file_obj = tar_stream.extractfile(member)
            if file_obj is None:
                raise ValueError("Unable to extract flash archive entry")
            with open(entry_name, "wb") as out:
                written = 0
                while True:
                    data = file_obj.read(chunk_size)
                    if not data:
                        break
                    written += out.write(data)

            if verbose:
                print("Flash file '%s' (%s B) installed." % (entry_name, written))


def install_from_tar_url(
    url: str,
    tmp_filename: str = ".ota-flash.tar.gz",
    chunk_size: int = 512,
    verbose: bool = True,
    **kw
) -> None:
    gc.collect()
    if verbose:
        print("Downloading flash archive %s..." % url)
    _download_to_file(url, tmp_filename, chunk_size=chunk_size, **kw)

    try:
        if verbose:
            print("Installing flash archive %s..." % tmp_filename)
        _extract_tar_gz(tmp_filename, chunk_size=chunk_size, verbose=verbose)
    finally:
        try:
            os.remove(tmp_filename)
        except OSError:
            pass

    if verbose:
        print("Flash filesystem update complete.")
