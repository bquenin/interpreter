"""Multiprocessing wrapper for OCR backends that hold the GIL.

PaddlePaddle (used by PaddleOCR) holds the GIL during inference, causing
UI responsiveness issues. This module runs OCR in a separate process to
avoid GIL contention with the main thread.
"""

import multiprocessing as mp
from multiprocessing import Queue
from typing import Any

import numpy as np

from ... import log

logger = log.get_logger()


def _ocr_worker(
    input_queue: Queue,
    output_queue: Queue,
    backend_class: type,
    source_language: Any,
    confidence_threshold: float,
):
    """Worker function that runs in a separate process.

    Args:
        input_queue: Queue to receive (frame, request_id) tuples.
        output_queue: Queue to send (result, request_id) tuples.
        backend_class: The OCR backend class to instantiate.
        source_language: Source language for OCR.
        confidence_threshold: OCR confidence threshold.
    """
    import os
    import sys

    # Import torch FIRST before paddle/paddleocr to avoid DLL loading issues on Windows
    # This must happen before any paddle imports
    try:
        import torch
    except ImportError:
        pass

    # Import here to avoid issues with multiprocessing
    import time

    # Instantiate and load the backend in this process
    backend = backend_class(source_language)
    backend.load()
    backend.confidence_threshold = confidence_threshold

    # Signal that we're ready
    output_queue.put(("ready", None))

    while True:
        try:
            item = input_queue.get()
            if item is None:  # Shutdown signal
                break

            frame, request_id, mode = item
            start = time.perf_counter()

            if mode == "text":
                result = backend.extract_text(frame)
            else:  # "regions"
                result = backend.extract_text_regions(frame)

            elapsed_ms = int((time.perf_counter() - start) * 1000)
            output_queue.put((result, request_id, elapsed_ms))

        except Exception as e:
            # Send error back
            output_queue.put((f"error:{e}", request_id, 0))


class OCRProcess:
    """Runs OCR in a separate process to avoid GIL contention.

    Usage:
        ocr_proc = OCRProcess(PaddleOCRBackend, Language.ENGLISH, 0.6)
        ocr_proc.start()
        ocr_proc.submit_frame(frame, request_id, "text")
        result, req_id, elapsed_ms = ocr_proc.get_result(timeout=5.0)
        ocr_proc.stop()
    """

    def __init__(
        self,
        backend_class: type,
        source_language: Any,
        confidence_threshold: float = 0.6,
    ):
        self._backend_class = backend_class
        self._source_language = source_language
        self._confidence_threshold = confidence_threshold

        self._process: mp.Process | None = None
        self._input_queue: Queue | None = None
        self._output_queue: Queue | None = None
        self._running = False

    def start(self) -> bool:
        """Start the OCR process.

        Returns:
            True if started successfully, False otherwise.
        """
        if self._running:
            return True

        # Use 'spawn' to avoid issues with forking and CUDA/etc
        ctx = mp.get_context("spawn")
        self._input_queue = ctx.Queue()
        self._output_queue = ctx.Queue()

        self._process = ctx.Process(
            target=_ocr_worker,
            args=(
                self._input_queue,
                self._output_queue,
                self._backend_class,
                self._source_language,
                self._confidence_threshold,
            ),
            daemon=True,
        )
        self._process.start()

        # Wait for ready signal
        try:
            result, _ = self._output_queue.get(timeout=60.0)  # Model loading can be slow
            if result == "ready":
                self._running = True
                logger.info("OCR process started")
                return True
            else:
                logger.error("OCR process failed to start", result=result)
                return False
        except Exception as e:
            logger.error("OCR process startup timeout", error=str(e))
            self.stop()
            return False

    def stop(self):
        """Stop the OCR process."""
        if not self._running:
            return

        self._running = False

        # Send shutdown signal
        if self._input_queue:
            try:
                self._input_queue.put(None)
            except Exception:
                pass

        # Wait for process to finish
        if self._process:
            self._process.join(timeout=5.0)
            if self._process.is_alive():
                self._process.terminate()
            self._process = None

        self._input_queue = None
        self._output_queue = None
        logger.info("OCR process stopped")

    def submit_frame(self, frame: np.ndarray, request_id: int, mode: str = "text"):
        """Submit a frame for OCR processing.

        Args:
            frame: Image as numpy array (H, W, 4) in BGRA format.
            request_id: Unique ID to match results with requests.
            mode: "text" for extract_text, "regions" for extract_text_regions.
        """
        if not self._running or not self._input_queue:
            return

        self._input_queue.put((frame, request_id, mode))

    def get_result(self, timeout: float = 5.0) -> tuple[Any, int, int] | None:
        """Get a result from the OCR process.

        Args:
            timeout: How long to wait for a result.

        Returns:
            (result, request_id, elapsed_ms) or None if timeout.
        """
        if not self._running or not self._output_queue:
            return None

        try:
            return self._output_queue.get(timeout=timeout)
        except Exception:
            return None

    def set_confidence_threshold(self, threshold: float):
        """Update confidence threshold (takes effect on next frame)."""
        self._confidence_threshold = threshold
        # Note: This doesn't update the running process - would need IPC for that
        # For now, threshold changes require restart

    @property
    def is_running(self) -> bool:
        """Check if the OCR process is running."""
        return self._running
