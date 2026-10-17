"""Wait for the local server to become ready before opening the demo in a browser.

Started by start.bat as an optional convenience; uvicorn itself remains foreground.
"""
import time
import urllib.error
import urllib.request
import webbrowser

URL = 'http://127.0.0.1:8000'


def main():
    for _ in range(80):
        try:
            with urllib.request.urlopen(URL + '/apiv2/health', timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(URL)
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)


if __name__ == '__main__':
    main()
