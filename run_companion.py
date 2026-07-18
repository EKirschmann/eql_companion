#!/usr/bin/env python3
"""Single-process launcher for the packaged EQL Companion.

Starts the FastAPI server (which serves BOTH the API and the static UI)
and opens the dashboard. Used by the bundled executable; also runnable
directly for a production-mode single-window experience.
"""
import threading
import time
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8000


def _open_when_ready():
    import urllib.request
    url = f"http://{HOST}:{PORT}/"
    for _ in range(60):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    # prefer a native window (WebView2 on Win10/11) if pywebview is present,
    # else the default browser
    try:
        import webview  # pywebview
        webview.create_window("EQL Companion", url, width=1500, height=950)
        webview.start()
    except Exception:
        webbrowser.open(url)


if __name__ == "__main__":
    threading.Thread(target=_open_when_ready, daemon=True).start()
    uvicorn.run("backend.main:app", host=HOST, port=PORT, log_level="warning")
