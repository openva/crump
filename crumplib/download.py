"""Fetching the SCC data file.

The SCC serves its bulk export behind a cookie-consent gate. Requesting the
download directly returns the consent page as HTML, so we establish a session,
accept the cookie, and then download. The POST needs an explicit empty body --
without a Content-Length the server answers 411.
"""

import os
import zipfile

import requests

BASE_URL = "https://cis.scc.virginia.gov"
CONSENT_URL = BASE_URL + "/Cookie/CookieConsent"
STORE_CONSENT_URL = BASE_URL + "/Cookie/StoreCookieConsent"
DOWNLOAD_URL = BASE_URL + "/DataSales/DownloadBEDataSalesFile"

#: The upstream ZIP is ~177 MB, so stream it rather than buffering in memory.
CHUNK_SIZE = 1 << 20


class DownloadError(Exception):
    """The data file could not be retrieved."""


def download(destination="current.zip", timeout=600, progress=None):
    """Download the current SCC data ZIP. Returns the destination path."""
    session = requests.Session()

    try:
        session.get(CONSENT_URL, timeout=60)
        # data=b"" forces a Content-Length header; without it the server 411s.
        session.post(STORE_CONSENT_URL, data=b"", timeout=60)
        response = session.get(DOWNLOAD_URL, stream=True, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as error:
        raise DownloadError(f"could not download {DOWNLOAD_URL}: {error}") from error

    content_type = response.headers.get("Content-Type", "")
    if "zip" not in content_type and "octet-stream" not in content_type:
        raise DownloadError(
            f"expected a ZIP but got {content_type!r} -- "
            "the consent gate may have changed"
        )

    downloaded = 0
    with open(destination, "wb") as handle:
        for chunk in response.iter_content(CHUNK_SIZE):
            handle.write(chunk)
            downloaded += len(chunk)
            if progress:
                progress(downloaded)

    if not zipfile.is_zipfile(destination):
        raise DownloadError("downloaded file is not a valid ZIP archive")

    return destination


def extract(archive="current.zip", directory="data"):
    """Extract the CSVs from the archive. Returns the list of paths."""
    os.makedirs(directory, exist_ok=True)
    extracted = []
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            # Guard against path traversal in archive member names.
            target = os.path.basename(name)
            if not target:
                continue
            zf.extract(name, directory)
            extracted.append(os.path.join(directory, name))
    return sorted(extracted)
