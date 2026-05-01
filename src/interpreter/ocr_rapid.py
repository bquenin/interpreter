"""Chinese OCR backend using RapidOCR."""

import numpy as np
from numpy.typing import NDArray

from . import log
from .ocr import DEFAULT_CONFIDENCE_THRESHOLD, OCRResult

logger = log.get_logger()


def bgra_to_rgb(frame: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Convert BGRA numpy array to RGB numpy array."""
    rgb = frame[:, :, [2, 1, 0]]
    return np.ascontiguousarray(rgb)


class ChineseOCR:
    """Extracts Chinese text from images using RapidOCR."""

    def __init__(self, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD, debug: bool = False):
        self._engine = None
        self._confidence_threshold = confidence_threshold
        self._debug = debug

    @property
    def confidence_threshold(self) -> float:
        return self._confidence_threshold

    @confidence_threshold.setter
    def confidence_threshold(self, value: float) -> None:
        self._confidence_threshold = value

    def load(self) -> None:
        if self._engine is not None:
            return

        logger.info("loading rapidocr")
        from rapidocr import RapidOCR

        self._engine = RapidOCR()
        logger.info("rapidocr ready")

    def _quad_to_bbox(self, box) -> dict | None:
        if box is None or len(box) == 0:
            return None

        xs = [int(point[0]) for point in box]
        ys = [int(point[1]) for point in box]
        min_x = min(xs)
        min_y = min(ys)
        max_x = max(xs)
        max_y = max(ys)

        if min_x < 0 or min_y < 0 or max_x <= min_x or max_y <= min_y:
            return None

        return {
            "x": min_x,
            "y": min_y,
            "width": max_x - min_x,
            "height": max_y - min_y,
        }

    def _run_ocr(self, image: NDArray[np.uint8]) -> list[OCRResult]:
        if self._engine is None:
            self.load()

        img_array = bgra_to_rgb(image)
        output = self._engine(img_array)

        if not output or getattr(output, "boxes", None) is None or getattr(output, "txts", None) is None:
            return []

        scores = getattr(output, "scores", None)
        if scores is None:
            scores = [1.0] * len(output.txts)

        results = []
        for box, text, score in zip(output.boxes, output.txts, scores, strict=False):
            text = (text or "").strip()
            if not text:
                continue
            if score is not None and score < self._confidence_threshold:
                if self._debug:
                    logger.debug("rapidocr rejected", text=text, score=score)
                continue

            bbox = self._quad_to_bbox(box)
            if bbox is None:
                continue

            results.append(OCRResult(text=text, bbox=bbox))

        results.sort(key=lambda region: (region.bbox["y"], region.bbox["x"]))
        return results

    def extract_text(self, image: NDArray[np.uint8]) -> str:
        return " ".join(region.text for region in self._run_ocr(image) if region.text)

    def extract_text_regions(self, image: NDArray[np.uint8]) -> list[OCRResult]:
        return self._run_ocr(image)

    def is_loaded(self) -> bool:
        return self._engine is not None
