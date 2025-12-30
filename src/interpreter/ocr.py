"""OCR module using MeikiOCR for Japanese game text extraction."""

from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image

# Detection thresholds
DEFAULT_CONFIDENCE_THRESHOLD = 0.6  # Minimum avg confidence per line (0.0-1.0)
DUPLICATE_OVERLAP_THRESHOLD = 0.5   # Lines with >50% bbox overlap are duplicates
SPATIAL_PROXIMITY_MULTIPLIER = 1.5  # Gap threshold = height * this value

# Punctuation characters to exclude from confidence calculation
# These often have lower OCR confidence but shouldn't invalidate the line
PUNCTUATION = set('。、！？・…「」『』（）【】〈〉《》～ー－—.!?,;:\'"()-~')


@dataclass
class OCRResult:
    """Result from OCR extraction with optional bounding box."""
    text: str
    bbox: Optional[dict] = None  # {"x": int, "y": int, "width": int, "height": int}


class OCR:
    """Extracts Japanese text from images using MeikiOCR.

    MeikiOCR is specifically trained on Japanese video game text,
    providing significantly better accuracy on pixel fonts than
    general-purpose OCR.
    """

    def __init__(self, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD, debug: bool = False):
        """Initialize OCR (lazy loading of model).

        Args:
            confidence_threshold: Minimum average confidence per line (0.0-1.0).
                Lines below this threshold are filtered out.
            debug: If True, print per-character confidence scores.
        """
        self._model = None
        self._confidence_threshold = confidence_threshold
        self._debug = debug

    def load(self) -> None:
        """Load the MeikiOCR model."""
        if self._model is not None:
            return

        print("Loading MeikiOCR...")
        from meikiocr import MeikiOCR
        self._model = MeikiOCR()
        print("MeikiOCR ready.")

    def _run_ocr_and_filter(self, image: Image.Image) -> list[dict]:
        """Run OCR and filter results by confidence threshold.

        This is the common logic shared between extract_text() and extract_text_regions().

        Args:
            image: PIL Image to extract text from.

        Returns:
            List of line dicts: [{"text": str, "bbox": [x1, y1, x2, y2]}, ...]
            Lines are deduplicated but not sorted or clustered.
        """
        if self._model is None:
            self.load()

        img_array = np.array(image.convert('RGB'))
        results = self._model.run_ocr(img_array)

        lines = []
        for result in results:
            chars = result.get('chars', [])
            text = result.get('text', '')

            if not chars or not text:
                continue

            non_punct_chars = [c for c in chars if c['char'] not in PUNCTUATION]

            if non_punct_chars:
                avg_conf = sum(c['conf'] for c in non_punct_chars) / len(non_punct_chars)
            elif chars:
                avg_conf = sum(c['conf'] for c in chars) / len(chars)
            else:
                continue

            if self._debug and chars:
                char_info = ' '.join(f"{c['char']}({c['conf']:.2f})" for c in chars)
                status = "✓" if avg_conf >= self._confidence_threshold else "✗"
                punct_note = f" (excl {len(chars) - len(non_punct_chars)} punct)" if len(non_punct_chars) < len(chars) else ""
                print(f"[DBG] {char_info} → avg: {avg_conf:.2f}{punct_note} {status}")

            if avg_conf >= self._confidence_threshold:
                char_bboxes = [c['bbox'] for c in chars if c.get('bbox') and len(c['bbox']) == 4]
                if char_bboxes:
                    min_x = min(b[0] for b in char_bboxes)
                    min_y = min(b[1] for b in char_bboxes)
                    max_x = max(b[2] for b in char_bboxes)
                    max_y = max(b[3] for b in char_bboxes)
                    lines.append({
                        'text': text,
                        'bbox': [min_x, min_y, max_x, max_y],
                    })

        return self._deduplicate_lines(lines)

    def extract_text(self, image: Image.Image) -> str:
        """Extract Japanese text from an image.

        Args:
            image: PIL Image to extract text from.

        Returns:
            Extracted text string.
        """
        lines = self._run_ocr_and_filter(image)
        if not lines:
            return ""

        # Sort by position (top-to-bottom, left-to-right) for correct reading order
        lines = sorted(lines, key=lambda l: (l['bbox'][1], l['bbox'][0]))

        # Concatenate all text (no spatial clustering for banner mode)
        return self._clean_text(''.join(line['text'] for line in lines))

    def extract_text_with_bbox(self, image: Image.Image) -> OCRResult:
        """Extract Japanese text from an image with bounding box.

        Args:
            image: PIL Image to extract text from.

        Returns:
            OCRResult with extracted text and combined bounding box.
        """
        # Use extract_text_regions and combine into single result
        regions = self.extract_text_regions(image)
        if not regions:
            return OCRResult(text="", bbox=None)

        # Combine all regions into one
        text = " ".join(r.text for r in regions if r.text)

        # Compute combined bbox
        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = 0, 0
        for r in regions:
            if r.bbox:
                min_x = min(min_x, r.bbox["x"])
                min_y = min(min_y, r.bbox["y"])
                max_x = max(max_x, r.bbox["x"] + r.bbox["width"])
                max_y = max(max_y, r.bbox["y"] + r.bbox["height"])

        bbox = None
        if min_x < float('inf'):
            bbox = {
                "x": int(min_x),
                "y": int(min_y),
                "width": int(max_x - min_x),
                "height": int(max_y - min_y),
            }

        return OCRResult(text=text, bbox=bbox)

    def extract_text_regions(self, image: Image.Image) -> list[OCRResult]:
        """Extract Japanese text regions from an image with spatial clustering.

        Lines that are spatially close are grouped into the same region.
        This handles screens with multiple separate text areas.

        Args:
            image: PIL Image to extract text from.

        Returns:
            List of OCRResult objects, one per detected text region.
        """
        lines = self._run_ocr_and_filter(image)
        if not lines:
            return []

        # Cluster lines by spatial proximity
        clusters = self._cluster_lines(lines)

        # Convert clusters to OCRResult objects
        regions = []
        for cluster in clusters:
            # Sort lines top-to-bottom for reading order
            cluster.sort(key=lambda line: line['bbox'][1])

            # Combine text from lines
            text = ''.join(line['text'] for line in cluster)
            text = self._clean_text(text)

            if not text:
                continue

            # Compute bbox for this cluster
            min_x = min(line['bbox'][0] for line in cluster)
            min_y = min(line['bbox'][1] for line in cluster)
            max_x = max(line['bbox'][2] for line in cluster)
            max_y = max(line['bbox'][3] for line in cluster)

            bbox = {
                "x": int(min_x),
                "y": int(min_y),
                "width": int(max_x - min_x),
                "height": int(max_y - min_y),
            }

            regions.append(OCRResult(text=text, bbox=bbox))

        return regions

    def _deduplicate_lines(self, lines: list[dict]) -> list[dict]:
        """Remove duplicate/overlapping line detections.

        If two lines have bboxes that overlap significantly (>50%),
        keep only the longer one.

        Args:
            lines: List of line dicts with 'text' and 'bbox' keys.

        Returns:
            Deduplicated list of lines.
        """
        if len(lines) <= 1:
            return lines

        # Sort by text length (descending) so we prefer longer detections
        lines = sorted(lines, key=lambda l: len(l['text']), reverse=True)

        kept = []
        for line in lines:
            x1, y1, x2, y2 = line['bbox']
            line_area = (x2 - x1) * (y2 - y1)

            # Check if this line overlaps significantly with any kept line
            is_duplicate = False
            for kept_line in kept:
                kx1, ky1, kx2, ky2 = kept_line['bbox']

                # Calculate intersection
                ix1 = max(x1, kx1)
                iy1 = max(y1, ky1)
                ix2 = min(x2, kx2)
                iy2 = min(y2, ky2)

                if ix1 < ix2 and iy1 < iy2:
                    intersection_area = (ix2 - ix1) * (iy2 - iy1)
                    if line_area > 0 and intersection_area / line_area > DUPLICATE_OVERLAP_THRESHOLD:
                        is_duplicate = True
                        break

            if not is_duplicate:
                kept.append(line)

        return kept

    def _cluster_lines(self, lines: list[dict]) -> list[list[dict]]:
        """Cluster lines based on spatial proximity.

        Lines are grouped if they are close horizontally and vertically.

        Args:
            lines: List of line dicts with 'text' and 'bbox' keys.

        Returns:
            List of clusters, where each cluster is a list of line dicts.
        """
        if not lines:
            return []

        # Sort by position (top-to-bottom, left-to-right)
        lines = sorted(lines, key=lambda line: (line['bbox'][1], line['bbox'][0]))

        clusters = []

        for line in lines:
            x1, y1, x2, y2 = line['bbox']
            line_width = x2 - x1
            line_height = y2 - y1

            h_threshold = line_height * SPATIAL_PROXIMITY_MULTIPLIER

            # Find a cluster this line belongs to
            merged = False
            for cluster in clusters:
                for existing in cluster:
                    ex1, ey1, ex2, ey2 = existing['bbox']

                    # Check vertical overlap - must actually overlap
                    y_overlap = not (y2 <= ey1 or y1 >= ey2)

                    # Check horizontal proximity
                    h_gap = min(abs(x1 - ex2), abs(x2 - ex1))
                    h_close = h_gap < h_threshold

                    if y_overlap and h_close:
                        cluster.append(line)
                        merged = True
                        break

                if merged:
                    break

            if not merged:
                clusters.append([line])

        return clusters

    def _cluster_characters(self, chars: list[dict]) -> list[list[dict]]:
        """Cluster characters based on spatial proximity.

        Characters are grouped if they are close horizontally and vertically.

        Args:
            chars: List of character dicts with 'char' and 'bbox' keys.

        Returns:
            List of clusters, where each cluster is a list of character dicts.
        """
        if not chars:
            return []

        # Sort by position (top-to-bottom, left-to-right)
        chars = sorted(chars, key=lambda c: (c['bbox'][1], c['bbox'][0]))

        clusters = []

        for char in chars:
            x1, y1, x2, y2 = char['bbox']
            char_width = x2 - x1
            char_height = y2 - y1

            h_threshold = char_width * SPATIAL_PROXIMITY_MULTIPLIER

            # Find a cluster this character belongs to
            merged = False
            for cluster in clusters:
                for existing in cluster:
                    ex1, ey1, ex2, ey2 = existing['bbox']

                    # Check vertical overlap - must actually overlap, not just be close
                    # Characters are on same line if their y-ranges overlap
                    y_overlap = not (y2 <= ey1 or y1 >= ey2)

                    # Check horizontal proximity
                    h_gap = min(abs(x1 - ex2), abs(x2 - ex1))
                    h_close = h_gap < h_threshold

                    if y_overlap and h_close:
                        cluster.append(char)
                        merged = True
                        break

                if merged:
                    break

            if not merged:
                # Start a new cluster
                clusters.append([char])

        # Merge clusters that should be connected
        # (a character might bridge two previously separate clusters)
        merged_clusters = self._merge_overlapping_clusters(clusters)

        return merged_clusters

    def _merge_overlapping_clusters(self, clusters: list[list[dict]]) -> list[list[dict]]:
        """Merge clusters that are spatially connected.

        Args:
            clusters: List of character clusters.

        Returns:
            Merged list of clusters.
        """
        if len(clusters) <= 1:
            return clusters

        # Keep merging until no more merges possible
        changed = True
        while changed:
            changed = False
            new_clusters = []

            for cluster in clusters:
                merged = False

                for existing in new_clusters:
                    if self._clusters_should_merge(cluster, existing):
                        existing.extend(cluster)
                        merged = True
                        changed = True
                        break

                if not merged:
                    new_clusters.append(cluster)

            clusters = new_clusters

        return clusters

    def _clusters_should_merge(self, c1: list[dict], c2: list[dict]) -> bool:
        """Check if two clusters should be merged based on proximity."""
        for char1 in c1:
            x1, y1, x2, y2 = char1['bbox']
            char_width = x2 - x1
            h_threshold = char_width * SPATIAL_PROXIMITY_MULTIPLIER

            for char2 in c2:
                ex1, ey1, ex2, ey2 = char2['bbox']

                # Must actually overlap vertically
                y_overlap = not (y2 <= ey1 or y1 >= ey2)
                h_gap = min(abs(x1 - ex2), abs(x2 - ex1))
                h_close = h_gap < h_threshold

                if y_overlap and h_close:
                    return True

        return False

    def _clean_text(self, text: str) -> str:
        """Clean extracted text.

        Args:
            text: Raw extracted text.

        Returns:
            Cleaned text.
        """
        if not text:
            return ""

        # Remove extra whitespace
        text = " ".join(text.split())

        # Strip leading/trailing whitespace
        text = text.strip()

        return text

    def is_loaded(self) -> bool:
        """Check if the model is loaded.

        Returns:
            True if model is loaded, False otherwise.
        """
        return self._model is not None
