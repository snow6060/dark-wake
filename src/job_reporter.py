import sys
import threading
import time


class Reporter:
    def __init__(self, echo=True):
        self.echo, self.pct, self.stage = echo, 0.0, ""
        self.lines, self.done, self.error = [], False, None
        self._lock = threading.Lock()
        self._last = -1

    def _draw(self):
        if self.echo:
            n = int(self.pct // 4)
            sys.stderr.write(f"\r[{'#' * n}{'-' * (25 - n)}] {self.pct:5.1f}%  {self.stage[:48]:<48}")
            sys.stderr.flush()

    def log(self, msg):
        with self._lock:
            self.lines.append(f"{time.strftime('%H:%M:%S')}  {msg}")
            if self.echo:
                sys.stderr.write("\r" + " " * 90 + "\r" + self.lines[-1] + "\n")
                self._draw()

    def progress(self, pct, stage=None):
        with self._lock:
            self.pct = max(self.pct, min(float(pct), 100.0))
            if stage:
                self.stage = stage
            if int(self.pct * 2) != self._last:
                self._last = int(self.pct * 2)
                self._draw()

    def finish(self):
        self.progress(100, "Done")
        self.done = True
        if self.echo:
            sys.stderr.write("\n")

    def fail(self, msg):
        self.error, self.done = msg, True
        self.log(f"ERROR: {msg}")

    def snapshot(self, since=0):
        with self._lock:
            return {"pct": round(self.pct, 1), "stage": self.stage, "done": self.done, "error": self.error,
                    "lines": self.lines[since:], "next": len(self.lines)}