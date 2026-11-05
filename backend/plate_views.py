"""Optional local plate crops for vision requests; never downloads detector weights."""

import io
import os
import threading
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _detector():
    path = Path(
        os.getenv("ITS_PLATE_DETECTOR_PATH")
        or Path.home()
        / ".cache/open-image-models/yolo-v9-t-384-license-plate-end2end/yolo-v9-t-384-license-plates-end2end.onnx"
    )
    if not path.is_file():
        return None
    try:
        import onnxruntime as ort
        from open_image_models.detection.core.yolo_v9.inference import YoloV9Detector

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        return YoloV9Detector(
            path, ["plate"], providers=["CPUExecutionProvider"], sess_options=options
        )
    except Exception:
        return None


def _find_boxes(image):
    detector = _detector()
    if detector is None:
        return []
    import numpy as np

    frame = np.array(image.convert("RGB"))[:, :, ::-1].copy()
    regions = [(0, 0, image.width, image.height)]
    # The 384px detector can lose a small plate after full-frame downsampling.
    # Four overlapping tiles preserve detail, including plates near tile seams.
    # Keep the whole-frame pass to retain context and count other vehicles.
    if max(image.size) >= 1200:
        tile_w, tile_h = round(image.width * 0.6), round(image.height * 0.6)
        regions += [
            (x, y, x + tile_w, y + tile_h)
            for y in (0, image.height - tile_h)
            for x in (0, image.width - tile_w)
        ]
    boxes = []
    with _LOCK:
        for left, top, right, bottom in regions:
            for item in detector.predict(frame[top:bottom, left:right]):
                if item.confidence < 0.5:
                    continue
                x1, y1, x2, y2 = item.bounding_box.clamp(right - left, bottom - top)
                if x2 > x1 and y2 > y1:
                    boxes.append((x1 + left, y1 + top, x2 + left, y2 + top))
    return _merge_duplicate_boxes(boxes)


def _merge_duplicate_boxes(boxes):
    """Suppress overlapping observations of the same plate, never join neighbors."""
    kept = []
    for box in sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True):
        area = (box[2] - box[0]) * (box[3] - box[1])
        if area <= 0:
            continue
        duplicate = False
        for other in kept:
            overlap = max(0, min(box[2], other[2]) - max(box[0], other[0])) * max(
                0, min(box[3], other[3]) - max(box[1], other[1])
            )
            other_area = (other[2] - other[0]) * (other[3] - other[1])
            if (
                overlap / (area + other_area - overlap) >= 0.4
                or overlap / min(area, other_area) >= 0.85
            ):
                duplicate = True
                break
        if not duplicate:
            kept.append(box)
    return kept


def crop_views(image_path, finder=None, *, include_enhanced=True):
    """Return raw and gently enhanced views only for an unambiguous single ROI."""
    try:
        with Image.open(image_path) as original:
            if original.width * original.height > 20000000:
                return []
            image = ImageOps.exif_transpose(original).convert("RGB")
        boxes = (finder or _find_boxes)(image)
        if len(boxes) != 1:
            return []
        x1, y1, x2, y2 = boxes[0]
        if x2 - x1 < 12 or y2 - y1 < 8:
            return []
        dx = max(2, round((x2 - x1) * 0.10))
        dy = max(2, round((y2 - y1) * 0.12))
        crop = image.crop(
            (
                max(0, x1 - dx),
                max(0, y1 - dy),
                min(image.width, x2 + dx),
                min(image.height, y2 + dy),
            )
        )
        scale = min(4.0, 1200 / max(crop.size))
        if scale != 1:
            crop = crop.resize(
                (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
                Image.Resampling.LANCZOS,
            )
        views = [("Ảnh cắt phóng to vùng biển số từ ảnh gốc", crop)]
        if include_enhanced:
            enhanced = (
                ImageEnhance.Contrast(ImageOps.grayscale(crop))
                .enhance(1.4)
                .filter(ImageFilter.UnsharpMask(radius=1.2, percent=120, threshold=3))
                .convert("RGB")
            )
            views.append(("Cùng vùng biển số, tăng tương phản để đối chiếu", enhanced))
        return views
    except Exception:
        # Full-frame vision remains usable when the optional local detector fails.
        return []


def encode_crop_views(image_path, *, include_enhanced=True):
    import base64

    result = []
    for label, image in crop_views(image_path, include_enhanced=include_enhanced):
        stream = io.BytesIO()
        image.save(stream, format="JPEG", quality=95)
        result.append((label, base64.b64encode(stream.getvalue()).decode("ascii")))
    return result
