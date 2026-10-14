# SPDX-License-Identifier: GPL-2.0-or-later
"""Photo loader with priorities - the page on screen always goes first.

A plain thread pool works first-come-first-served: after flipping through a few pages,
the photos of the page you now look at wait behind the prefetch of pages you already left.
Here every request has a priority (0 = page on screen, 1 = next page, 2 = the one after ...);
asking again for a photo that is still waiting moves it up. Worker threads download the photo
AND cut out the thumbnail (QImage, safe off the GUI thread), so the window only has to show it.

Finished thumbnails are kept (the last `keep` of them), so a page that was loaded in the
background appears at once when you go to it - nothing is decoded again.
"""

import heapq
import itertools
import threading
from collections import OrderedDict
from concurrent.futures import Future


class PriorityLoader:
    def __init__(self, threads, work, keep=0):
        """work(key, *args) runs in a worker thread; its result goes into the Future.
        keep: how many finished results to remember (0 = none)."""
        self._work = work
        self._keep = keep
        self._done = OrderedDict()          # key -> result, newest last
        self._heap = []                     # (priority, order, key)
        self._jobs = {}                     # key -> [priority, Future, args]
        self._order = itertools.count()
        self._cv = threading.Condition()
        self._stop = False
        self._threads = [threading.Thread(target=self._run, daemon=True, name=f'sign-review-{i}')
                         for i in range(threads)]
        for t in self._threads:
            t.start()

    # ── submit() : ask for one photo; returns a Future ────────────────────────────────────────
    def submit(self, key, priority, *args):
        with self._cv:
            if key in self._done:                     # finished before -> ready at once
                self._done.move_to_end(key)
                fut = Future()
                fut.set_result(self._done[key])
                return fut
            job = self._jobs.get(key)
            if job is not None:                       # waiting or running already
                if priority < job[0] and not job[1].running() and not job[1].done():
                    job[0] = priority                 # move it up the queue
                    heapq.heappush(self._heap, (priority, next(self._order), key))
                    self._cv.notify()
                return job[1]
            fut = Future()
            self._jobs[key] = [priority, fut, args]
            heapq.heappush(self._heap, (priority, next(self._order), key))
            self._cv.notify()
            return fut

    # ── demote() : the user moved on - everything still waiting drops back ───────────────────
    def demote(self, by=10):
        """Called on every page change, before the new page's requests: old requests are not
        thrown away (you may come back), they just wait behind the new page."""
        with self._cv:
            self._heap = [(p + by, o, k) for p, o, k in self._heap]
            heapq.heapify(self._heap)
            for job in self._jobs.values():
                if not job[1].running():
                    job[0] += by

    def pending(self):
        with self._cv:
            return sum(1 for j in self._jobs.values() if not j[1].running())

    def shutdown(self):
        with self._cv:
            self._stop = True
            for job in self._jobs.values():
                job[1].cancel()
            self._jobs.clear()
            self._done.clear()
            self._heap = []
            self._cv.notify_all()

    # ── the worker threads ────────────────────────────────────────────────────────────────────
    def _run(self):
        while True:
            with self._cv:
                while not self._stop:
                    # skip heap entries that are stale (job moved up -> pushed again, or finished)
                    while self._heap:
                        p, _, key = self._heap[0]
                        job = self._jobs.get(key)
                        if (job is None or job[0] != p or job[1].running()
                                or not job[1].set_running_or_notify_cancel()):
                            heapq.heappop(self._heap)
                            if job is not None and job[1].cancelled():
                                self._jobs.pop(key, None)
                            continue
                        heapq.heappop(self._heap)
                        break
                    else:
                        self._cv.wait()
                        continue
                    break
                if self._stop:
                    return
            try:
                result = self._work(key, *job[2])
            except BaseException as e:            # never kill the worker
                with self._cv:
                    self._jobs.pop(key, None)
                job[1].set_exception(e)
                continue
            with self._cv:
                self._jobs.pop(key, None)
                if self._keep and result is not None and not self._stop:
                    self._done[key] = result
                    self._done.move_to_end(key)
                    while len(self._done) > self._keep:
                        self._done.popitem(last=False)
            job[1].set_result(result)
