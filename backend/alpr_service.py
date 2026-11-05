import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("PADDLEOCR_HOME", str(Path.home() / ".paddleocr"))

from backend.config import (
    DEEP_OCR_CONFIDENCE_THRESHOLD,
    DEFAULT_MODEL_LABEL,
    ENABLE_DEEP_OCR_RETRY,
    ENABLE_OPENAI_VISION,
    ENABLE_PADDLE_FALLBACK,
    ENABLE_PADDLE_OCR,
    ENABLE_VISION_IN_AUTO,
    FAST_MODE,
    OCR_ACCURACY_MODE,
)
from backend.ocr_quality import assess_ocr_quality, clamp_confidence
from backend.plate_format import (
    format_confirmed_plate,
    is_top_only_plate,
    looks_like_vn_bottom,
    looks_like_vn_top,
    normalize_generic_plate_text,
    normalize_plate_text,
    normalize_vn_top,
)
from backend.storage import save_annotated_image

try:
    import cv2
except Exception:
    cv2 = None

try:
    import easyocr
except Exception:
    easyocr = None

try:
    from paddleocr import PaddleOCR
except Exception:
    PaddleOCR = None

try:
    from backend.openai_vision_adapter import active_ai_settings, run_openai_vision
except Exception:
    active_ai_settings = None
    run_openai_vision = None


def _vision_enabled(auto: bool = False) -> bool:
    if active_ai_settings is not None:
        try:
            settings = active_ai_settings()
        except Exception:
            settings = None
        if settings is not None:
            return bool(getattr(settings, "enabled", False)) and (
                bool(getattr(settings, "in_auto", False)) or not auto
            )
    return bool(ENABLE_OPENAI_VISION) and (bool(ENABLE_VISION_IN_AUTO) or not auto)


try:
    import site

    user_site = site.getusersitepackages()
    if user_site and user_site not in sys.path:
        sys.path.append(user_site)
except Exception:
    pass

try:
    from fast_alpr import ALPR
    from fast_alpr.alpr import BaseOCR, OcrResult
except Exception:
    ALPR = None
    BaseOCR = object
    OcrResult = None


def repair_vn_top(text: str):
    s = normalize_vn_top(text)
    if (
        re.fullmatch(r"\d{2}[A-Z]", s)
        or re.fullmatch(r"\d{2}[A-Z]{2}", s)
        or re.fullmatch(r"\d{2}[A-Z]\d", s)
        or re.fullmatch(r"\d{2}[A-Z]{2}\d", s)
    ):
        return s
    if len(s) >= 3 and s[:2].isdigit():
        tail = s[2:]
        if not tail:
            return s
        first = tail[0]
        fix_map = {"8": "B", "6": "G", "0": "D", "2": "Z", "5": "S"}
        fixed = fix_map.get(first, first)
        candidate = s[:2] + fixed + tail[1:]
        if (
            re.fullmatch(r"\d{2}[A-Z]", candidate)
            or re.fullmatch(r"\d{2}[A-Z]{2}", candidate)
            or re.fullmatch(r"\d{2}[A-Z]\d", candidate)
            or re.fullmatch(r"\d{2}[A-Z]{2}\d", candidate)
        ):
            return candidate
    return s


def repair_vn_bottom(text: str):
    s = normalize_plate_text(text)
    if re.fullmatch(r"\d{4}", s) or re.fullmatch(r"\d{5}", s):
        return s
    if len(s) == 5:
        sub_map = {"B": "8", "S": "5", "Z": "2", "G": "6", "I": "1", "L": "1", "O": "0", "D": "0"}
        repaired = "".join(sub_map.get(ch, ch) for ch in s)
        if re.fullmatch(r"\d{5}", repaired):
            return repaired
    return s


def score_full_plate(text: str, conf: float):
    norm = normalize_generic_plate_text(text)
    if not norm:
        return -999.0
    score = clamp_confidence(conf) * 100.0
    if format_confirmed_plate(text):
        return score + 300
    if re.fullmatch(r"\d{2}[A-Z]\d{5}", norm):
        score += 260
    elif re.fullmatch(r"\d{2}[A-Z]{2}\d{4}", norm):
        score += 255
    elif re.fullmatch(r"\d{2}[A-Z]{2}\d{5}", norm):
        score += 260
    elif re.fullmatch(r"\d{2}[A-Z]\d{4,5}", norm):
        score += 180
    elif looks_like_vn_top(norm):
        score += 60
    elif looks_like_vn_bottom(norm):
        score += 40
    if 6 <= len(norm) <= 9:
        score += 45
    elif len(norm) <= 3:
        score -= 50
    if any(ch.isalpha() for ch in norm[4:]):
        score -= 35
    if len(norm) >= 2 and not norm[:2].isdigit():
        score -= 60
    return score


class _ConflictingReadings(Exception):
    def __init__(self, readings):
        self.readings = tuple(readings)


@dataclass(frozen=True)
class _LocalOcrConflict:
    """The fast-alpr OCR interface with explicit disagreement evidence."""

    candidates: tuple
    text: str = ""
    confidence: float = 0.0
    ocr_disagreement: bool = True
    region: str | None = None
    region_confidence: float | None = None


def _select_local_reading(readings):
    readings = [(text, clamp_confidence(conf)) for text, conf in readings if text]
    identities = {
        normalize_generic_plate_text(text) for text, _ in readings if format_confirmed_plate(text)
    }
    if len(identities) > 1:
        raise _ConflictingReadings(readings)
    if identities:
        full = next(iter(identities))
        for text, _ in readings:
            partial = normalize_generic_plate_text(text)
            if re.fullmatch(r"\d{2}[A-Z]{1,2}\d?", partial) and not full.startswith(partial):
                raise _ConflictingReadings(readings)
    return max(readings, key=lambda row: score_full_plate(*row), default=("", 0.0))


class EasyOCRVNOCR(BaseOCR):
    _shared_reader = None

    def __init__(self) -> None:
        if easyocr is None:
            raise RuntimeError("easyocr is not installed")
        if EasyOCRVNOCR._shared_reader is None:
            EasyOCRVNOCR._shared_reader = easyocr.Reader(["en"], gpu=False)
        self.reader = EasyOCRVNOCR._shared_reader

    def _enhance(self, image, force_full: bool = False):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image.copy()
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        blur = cv2.bilateralFilter(gray, 5, 35, 35)
        sharp = cv2.addWeighted(gray, 1.6, blur, -0.6, 0)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(sharp)
        if FAST_MODE and not force_full:
            return [("clahe", clahe)]
        _, otsu = cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adaptive = cv2.adaptiveThreshold(
            clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 9
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        morph = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, kernel)
        return [
            ("clahe", clahe),
            ("otsu", otsu),
            ("adaptive", adaptive),
            ("morph", morph),
            ("sharp", sharp),
        ]

    def _ocr_candidates(self, image, force_full: bool = False):
        if image is None or image.size == 0:
            return []
        candidates = []
        for _, variant in self._enhance(image, force_full=force_full):
            try:
                rows = self.reader.readtext(
                    variant,
                    detail=1,
                    paragraph=False,
                    batch_size=1,
                    decoder="greedy",
                    allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-",
                    width_ths=0.7,
                    link_threshold=0.2,
                    text_threshold=0.55,
                    low_text=0.3,
                )
            except Exception:
                rows = []
            if rows:
                line_text = " ".join(
                    item[1].strip() for item in rows if len(item) >= 3 and item[1].strip()
                )
                if line_text:
                    # A confident top row must not hide an unreadable bottom row.
                    line_conf = min(clamp_confidence(item[2]) for item in rows if len(item) >= 3)
                    candidates.append((line_text, line_conf))
            for row in rows:
                if len(row) >= 3:
                    _, text, conf = row
                    candidates.append((text.strip(), float(conf)))
        dedup = {}
        for text, conf in candidates:
            norm = normalize_generic_plate_text(text)
            if not norm:
                continue
            score = score_full_plate(text, conf)
            if norm not in dedup or score > dedup[norm][0]:
                dedup[norm] = (score, text, conf)
        sorted_rows = sorted(dedup.values(), key=lambda x: (x[0], x[2]), reverse=True)
        return [(text, conf) for _, text, conf in sorted_rows]

    def _ocr_best(self, image, force_full: bool = False):
        candidates = self._ocr_candidates(image, force_full=force_full)
        if not candidates:
            return "", 0.0
        return _select_local_reading(candidates)

    def _split_vertical_plate(self, image, top_ratio=0.52, overlap_ratio=0.34, top_trim=0.08):
        h, w = image.shape[:2]
        if h <= 0 or w <= 0:
            return image, image
        top_cut = int(h * top_trim)
        base = image[top_cut:, :] if top_cut < h else image
        hh, _ = base.shape[:2]
        top = base[: max(1, int(hh * top_ratio)), :]
        bottom = base[max(0, int(hh * overlap_ratio)) :, :]
        return top, bottom

    def _combine_from_candidates(self, top_rows, bottom_rows):
        readings = []
        for t_text, t_conf in top_rows[:6]:
            top = normalize_generic_plate_text(t_text)
            if not re.fullmatch(r"\d{2}[A-Z]{1,2}\d?", top):
                continue
            for b_text, b_conf in bottom_rows[:8]:
                bottom = normalize_generic_plate_text(b_text)
                if not re.fullmatch(r"\d{4,5}", bottom):
                    continue
                # Keep the original strings until strict validation: stripping a
                # '?' or replacing B/8 would hide uncertainty before validation.
                combined = format_confirmed_plate(f"{t_text.strip()} {b_text.strip()}")
                if combined:
                    readings.append(
                        (combined, min(clamp_confidence(t_conf), clamp_confidence(b_conf)))
                    )
        return _select_local_reading(readings)

    def _needs_rescue_ocr(
        self, text: str, conf: float, ratio: float, has_bottom_rows: bool
    ) -> bool:
        assessment = assess_ocr_quality(text or "", conf)
        normalized_len = len(assessment.normalized_text or "")
        if not text:
            return True
        if conf < 0.86:
            return True
        if not assessment.is_usable:
            return True
        if ratio < 2.2 and (
            has_bottom_rows
            or assessment.plate_type in {"vn_partial_top", "vn_partial_bottom", "unknown"}
        ):
            return True
        if normalized_len < 8:
            return True
        if conf < DEEP_OCR_CONFIDENCE_THRESHOLD:
            return True
        return False

    def _predict_core(self, cropped_plate, force_full: bool = False):
        if cropped_plate is None:
            return None

        h, w = cropped_plate.shape[:2]
        ratio = w / max(h, 1)

        if ratio >= 2.2:
            text, conf = self._ocr_best(cropped_plate, force_full=force_full)
            text = format_confirmed_plate(text) or text
            return OcrResult(text=text, confidence=conf) if text else None

        split_configs = (
            [
                (0.52, 0.34, 0.08),
            ]
            if FAST_MODE and not force_full
            else [
                (0.52, 0.34, 0.08),
                (0.48, 0.30, 0.03),
                (0.56, 0.38, 0.10),
            ]
        )
        combinations = []
        last_bottom_rows = []
        for top_ratio, overlap_ratio, top_trim in split_configs:
            top, bottom = self._split_vertical_plate(
                cropped_plate, top_ratio=top_ratio, overlap_ratio=overlap_ratio, top_trim=top_trim
            )
            top_rows = self._ocr_candidates(top, force_full=force_full)
            bottom_rows = self._ocr_candidates(bottom, force_full=force_full)
            last_bottom_rows = bottom_rows
            combined_text, combined_conf = self._combine_from_candidates(top_rows, bottom_rows)
            combinations.append((combined_text, combined_conf))
        best_combo = _select_local_reading(combinations)
        if best_combo[0] and (
            force_full
            or not FAST_MODE
            or not self._needs_rescue_ocr(
                best_combo[0], best_combo[1], ratio, bool(last_bottom_rows)
            )
        ):
            return OcrResult(text=best_combo[0], confidence=best_combo[1])

        full_text, full_conf = self._ocr_best(cropped_plate, force_full=force_full)
        full_text = format_confirmed_plate(full_text) or full_text
        # Any completed alternative already observed remains evidence even if
        # another crop/full-frame reading scores higher.
        _select_local_reading([best_combo, (full_text, full_conf)])
        if full_text and not (
            is_top_only_plate(full_text)
            and last_bottom_rows
            and any(looks_like_vn_bottom(t) for t, _ in last_bottom_rows[:4])
        ):
            if (
                force_full
                or not FAST_MODE
                or not self._needs_rescue_ocr(full_text, full_conf, ratio, bool(last_bottom_rows))
            ):
                return OcrResult(text=full_text, confidence=full_conf)

        top, bottom = self._split_vertical_plate(
            cropped_plate, top_ratio=0.50, overlap_ratio=0.28, top_trim=0.0
        )
        extra_top_rows = self._ocr_candidates(top, force_full=force_full) + self._ocr_candidates(
            cv2.resize(top, None, fx=1.3, fy=1.3, interpolation=cv2.INTER_CUBIC),
            force_full=force_full,
        )
        extra_bottom_rows = self._ocr_candidates(
            bottom, force_full=force_full
        ) + self._ocr_candidates(
            cv2.resize(bottom, None, fx=1.4, fy=1.4, interpolation=cv2.INTER_CUBIC),
            force_full=force_full,
        )
        combined_text, combined_conf = self._combine_from_candidates(
            extra_top_rows, extra_bottom_rows
        )
        selected_text, selected_conf = _select_local_reading(
            [best_combo, (full_text, full_conf), (combined_text, combined_conf)]
        )
        return OcrResult(text=selected_text, confidence=selected_conf) if selected_text else None

    def _result_payload_score(self, result, ratio: float = 0.0) -> tuple[int, float, int]:
        if result is None:
            return (0, 0.0, 0)
        text = getattr(result, "text", "") or ""
        conf = float(getattr(result, "confidence", 0.0) or 0.0)
        assessment = assess_ocr_quality(text, conf)
        penalty = 1 if self._needs_rescue_ocr(text, conf, ratio, False) else 0
        return (
            1 if assessment.is_usable else 0,
            conf - penalty,
            len(assessment.normalized_text or text),
        )

    def predict(self, cropped_plate):
        try:
            return self._predict_checked(cropped_plate)
        except _ConflictingReadings as exc:
            return _LocalOcrConflict(candidates=exc.readings)

    def _predict_checked(self, cropped_plate):
        if cropped_plate is None:
            return None
        h, w = cropped_plate.shape[:2]
        ratio = w / max(h, 1)
        fast_result = self._predict_core(cropped_plate, force_full=False)
        if not ENABLE_DEEP_OCR_RETRY or not FAST_MODE:
            return fast_result
        fast_text = getattr(fast_result, "text", "") if fast_result is not None else ""
        fast_conf = (
            float(getattr(fast_result, "confidence", 0.0) or 0.0)
            if fast_result is not None
            else 0.0
        )
        if not self._needs_rescue_ocr(fast_text, fast_conf, ratio, False):
            return fast_result
        deep_result = self._predict_core(cropped_plate, force_full=True)
        _select_local_reading(
            [
                (item.text, item.confidence)
                for item in (fast_result, deep_result)
                if item is not None
            ]
        )
        return max(
            [item for item in [fast_result, deep_result] if item is not None],
            key=lambda item: self._result_payload_score(item, ratio),
            default=fast_result,
        )


def get_detector_choices(external_model_dir: Path):
    choices = [(DEFAULT_MODEL_LABEL, None)]
    for model_path in sorted(external_model_dir.glob("*.pt")):
        choices.append((f"External: {model_path.name}", str(model_path)))
    return choices


_ALPR_INSTANCE_CACHE = {}
_PADDLE_OCR_READER = None


def _score_ocr_payload(payload: dict) -> tuple[int, float, int]:
    text = (payload.get("text") or "").strip()
    assessment = assess_ocr_quality(
        text or payload.get("raw_text") or "", float(payload.get("confidence", 0.0) or 0.0)
    )
    return (
        1 if assessment.is_usable else 0,
        float(payload.get("confidence", 0.0) or 0.0),
        len(assessment.normalized_text or text),
    )


def _build_candidate_payload(result) -> dict | None:
    ocr = getattr(result, "ocr", None)
    detection = getattr(result, "detection", None)
    if ocr is None:
        return None
    if getattr(ocr, "ocr_disagreement", False):
        return {
            "text": "",
            "raw_text": "",
            "confidence": 0.0,
            "is_usable": False,
            "review_required": True,
            "ocr_disagreement": True,
            "candidates": list(getattr(ocr, "candidates", ())),
            "quality_note": "Các lần đọc OCR không thống nhất; cần đối chiếu ảnh.",
        }
    raw_text = getattr(ocr, "text", "") or ""
    conf = clamp_confidence(getattr(ocr, "confidence", 0.0) or 0.0)
    formatted = format_confirmed_plate(raw_text) or raw_text
    assessment = assess_ocr_quality(raw_text, conf)
    bbox = None
    if detection is not None:
        for attr in ("bbox", "box", "xyxy", "xywh"):
            value = getattr(detection, attr, None)
            if value is not None:
                try:
                    bbox = list(value)
                except Exception:
                    bbox = str(value)
                break
    return {
        "text": formatted,
        "raw_text": raw_text,
        "confidence": conf,
        "is_usable": assessment.is_usable
        and bool(format_confirmed_plate(raw_text))
        and normalize_generic_plate_text(raw_text) == normalize_generic_plate_text(formatted),
        "quality_note": assessment.quality_note,
        "normalized_text": assessment.normalized_text,
        "formatted_text": assessment.formatted_text,
        "plate_type": assessment.plate_type,
        "bbox": bbox,
        "detector_confidence": float(getattr(detection, "confidence", 0.0) or 0.0)
        if detection is not None
        else 0.0,
    }


def _is_good_enough(payload: dict | None) -> bool:
    if (
        not payload
        or payload.get("is_usable") is False
        or payload.get("ambiguous")
        or payload.get("ocr_disagreement")
    ):
        return False
    text = (payload.get("text") or "").strip()
    conf = float(payload.get("confidence", 0.0) or 0.0)
    assessment = assess_ocr_quality(text or payload.get("raw_text") or "", conf)
    return bool(
        assessment.is_usable and len(assessment.normalized_text or text) >= 8 and conf >= 0.80
    )


def _get_paddle_reader():
    global _PADDLE_OCR_READER
    if PaddleOCR is None or not (ENABLE_PADDLE_OCR or ENABLE_PADDLE_FALLBACK):
        return None
    if _PADDLE_OCR_READER is None:
        init_variants = [
            {"use_angle_cls": False, "lang": "en", "show_log": False},
            {"use_angle_cls": False, "lang": "en"},
            {"lang": "en"},
            {},
        ]
        for kwargs in init_variants:
            try:
                _PADDLE_OCR_READER = PaddleOCR(**kwargs)
                break
            except TypeError:
                continue
            except ValueError:
                continue
            except Exception:
                continue
    return _PADDLE_OCR_READER


def _run_openai_vision_payload(image_path: str, detector_label: str, annotated_path: str):
    if not ENABLE_OPENAI_VISION or run_openai_vision is None:
        return None
    openai_payload = run_openai_vision(image_path)
    if not openai_payload:
        return None
    payload = dict(openai_payload)
    payload.update(
        {
            "message": f"{detector_label} • OpenAI vision • {payload.get('quality_note', '')}",
            "used_ocr": bool(payload.get("text")),
            "annotated_path": annotated_path,
            "detector_label": detector_label,
            "ocr_engine": "openai-vision",
        }
    )
    return payload


def _payload_identity(payload: dict | None) -> str:
    if not payload:
        return ""
    return normalize_generic_plate_text(payload.get("text") or payload.get("raw_text") or "")


def _candidate_conflict(a: dict | None, b: dict | None) -> bool:
    a_norm = _payload_identity(a)
    b_norm = _payload_identity(b)
    return bool(a_norm and b_norm and a_norm != b_norm)


def _fusion_rank(payload: dict) -> tuple[int, float, int, int]:
    text = payload.get("text") or payload.get("raw_text") or ""
    conf = float(payload.get("confidence", 0.0) or 0.0)
    assessment = assess_ocr_quality(text, conf)
    engine = payload.get("ocr_engine") or payload.get("engine") or ""
    engine_bonus = 2 if engine == "openai-vision" else 1 if engine == "paddleocr" else 0
    return (
        1 if assessment.is_usable else 0,
        score_full_plate(text, conf),
        len(assessment.normalized_text or text),
        engine_bonus,
    )


def _fuse_ocr_candidates(
    candidates: list[dict | None], detector_label: str, annotated_path: str
) -> dict | None:
    # Ambiguous scenes cannot be resolved by ranking an unrelated engine's guess.
    for item in candidates:
        if item and (item.get("ambiguous") or item.get("ocr_disagreement")):
            return dict(item)
    payloads = [
        dict(item) for item in candidates if item and (item.get("text") or item.get("raw_text"))
    ]
    if not payloads:
        return None
    for item in payloads:
        item.setdefault("annotated_path", annotated_path)
        item.setdefault("detector_label", detector_label)
    selected = max(payloads, key=_fusion_rank)
    identities = {_payload_identity(item) for item in payloads if _payload_identity(item)}
    selected = dict(selected)
    selected["candidates"] = payloads
    selected["fusion_sources"] = [
        item.get("ocr_engine") or item.get("engine") or "unknown" for item in payloads
    ]
    selected["vision_disagreement"] = len(identities) > 1 and any(
        (item.get("ocr_engine") == "openai-vision") for item in payloads
    )
    selected["ocr_disagreement"] = len(identities) > 1
    if selected["ocr_disagreement"]:
        selected["review_required"] = True
        selected["is_usable"] = False
        selected["quality_note"] = "Các engine OCR không thống nhất, cần đối chiếu ảnh"
        selected["message"] = f"{detector_label} • OCR fusion • bất đồng kết quả giữa các engine"
    else:
        selected["message"] = selected.get("message") or f"{detector_label} • OCR fusion"
    selected["ocr_engine"] = (
        "vision-fusion"
        if any(item.get("ocr_engine") == "openai-vision" for item in payloads)
        else selected.get("ocr_engine", "fusion")
    )
    selected["used_ocr"] = bool(selected.get("text"))
    selected["annotated_path"] = annotated_path
    selected["detector_label"] = detector_label
    return selected


def _prepare_vision_candidate(
    vision_payload: dict, detector_label: str, annotated_path: str
) -> dict:
    payload = dict(vision_payload or {})
    payload.setdefault("ocr_engine", "openai-vision")
    payload.setdefault("engine", "openai-vision")
    payload.setdefault("message", f"{detector_label} • OpenAI vision")
    payload.setdefault("used_ocr", bool(payload.get("text")))
    payload.setdefault("annotated_path", annotated_path)
    payload.setdefault("detector_label", detector_label)
    return payload


def _run_paddle_ocr(image_path: str, detector_label: str, annotated_path: str):
    reader = _get_paddle_reader()
    if reader is None:
        return None

    raw_result = None
    try:
        if hasattr(reader, "ocr"):
            raw_result = reader.ocr(image_path, cls=True) or []
        elif hasattr(reader, "predict"):
            raw_result = reader.predict(input=image_path) or []
        else:
            return None
    except TypeError:
        try:
            if hasattr(reader, "ocr"):
                raw_result = reader.ocr(image_path) or []
            else:
                return None
        except Exception:
            return None
    except Exception:
        return None

    candidates = []

    if isinstance(raw_result, list):
        for item in raw_result:
            if isinstance(item, dict):
                rec_texts = item.get("rec_texts") or []
                rec_scores = item.get("rec_scores") or []
                for idx, text in enumerate(rec_texts):
                    raw_text = str(text or "").strip()
                    conf = float(rec_scores[idx] or 0.0) if idx < len(rec_scores) else 0.0
                    formatted = format_confirmed_plate(raw_text) or raw_text
                    if raw_text:
                        candidates.append((formatted, raw_text, conf))
                continue

            for row in item or []:
                if not row or len(row) < 2:
                    continue
                text_conf = row[1]
                if not text_conf or len(text_conf) < 2:
                    continue
                raw_text = str(text_conf[0] or "").strip()
                conf = float(text_conf[1] or 0.0)
                formatted = format_confirmed_plate(raw_text) or raw_text
                if raw_text:
                    candidates.append((formatted, raw_text, conf))

    if not candidates:
        return None

    full_candidates = {
        normalize_generic_plate_text(raw) for _, raw, _ in candidates if format_confirmed_plate(raw)
    }
    if len(full_candidates) > 1:
        return {
            "text": "",
            "confidence": 0.0,
            "is_usable": False,
            "ambiguous": True,
            "review_required": True,
            "plate_count": len(full_candidates),
            "ocr_engine": "paddleocr",
            "annotated_path": annotated_path,
            "detector_label": detector_label,
            "quality_note": "Có nhiều biển số; hãy chọn ảnh chỉ có một xe hoặc nhập tay sau khi đối chiếu.",
        }

    best_text, best_raw, best_conf = max(
        candidates,
        key=lambda item: score_full_plate(item[0] or item[1], item[2]),
    )
    assessment = assess_ocr_quality(best_raw, best_conf)
    return {
        "text": best_text,
        "confidence": best_conf,
        "message": f"{detector_label} • PaddleOCR • {assessment.quality_note}",
        "used_ocr": bool(best_text),
        "annotated_path": annotated_path,
        "detector_label": detector_label,
        "raw_text": best_raw,
        "is_usable": assessment.is_usable,
        "quality_note": assessment.quality_note,
        "normalized_text": assessment.normalized_text,
        "ocr_engine": "paddleocr",
    }


def load_fast_alpr(model_path: str | None = None):
    if ALPR is None or easyocr is None:
        return None
    cache_key = model_path or "__default__"
    if cache_key in _ALPR_INSTANCE_CACHE:
        return _ALPR_INSTANCE_CACHE[cache_key]
    try:
        kwargs = {"ocr": EasyOCRVNOCR()}
        if model_path:
            kwargs["detector_model"] = model_path
        instance = ALPR(**kwargs)
        _ALPR_INSTANCE_CACHE[cache_key] = instance
        return instance
    except TypeError:
        try:
            kwargs = {"ocr": EasyOCRVNOCR()}
            if model_path:
                kwargs["model_path"] = model_path
            instance = ALPR(**kwargs)
            _ALPR_INSTANCE_CACHE[cache_key] = instance
            return instance
        except Exception:
            return None
    except Exception:
        return None


def _load_runtime_frame(image_path: str):
    frame = cv2.imread(image_path)
    if frame is None:
        return None
    h, w = frame.shape[:2]
    longest_side = max(h, w)
    max_side = 1600 if FAST_MODE else 1920
    if longest_side > max_side:
        scale = max_side / float(longest_side)
        frame = cv2.resize(
            frame, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA
        )
    return frame


def run_alpr(image_path: str, detector_model: str | None = None, ocr_engine: str = "auto"):
    detector_label = DEFAULT_MODEL_LABEL if not detector_model else Path(detector_model).name
    requested_engine = (ocr_engine or "auto").strip().lower()

    ai_status = None
    ai_error = None
    auto_vision_payload = None

    def fallback_result(payload):
        if ai_status is not None:
            payload = dict(payload)
            payload.update(ai_status=ai_status, ai_error=ai_error, review_required=True)
        return payload

    vision_wanted = requested_engine == "openai-vision" or (
        requested_engine == "auto" and _vision_enabled(auto=True)
    )
    vision_enabled_now = _vision_enabled(auto=(requested_engine == "auto"))
    if vision_wanted and run_openai_vision is not None and vision_enabled_now:
        try:
            vision_payload = run_openai_vision(image_path)
        except Exception as exc:
            if requested_engine == "openai-vision":
                raise RuntimeError(f"OpenAI vision failed: {exc}") from exc
            vision_payload = None
            ai_status = "unavailable"
            ai_error = "AI vision unavailable"
        if vision_payload is not None:
            if vision_payload.get("ai_analysis") is not None or vision_payload.get("ai_status"):
                payload = dict(vision_payload)
                payload.setdefault("ocr_engine", "openai-vision")
                payload.setdefault("engine", "openai-vision")
                payload.setdefault("detector_label", detector_label)
                payload.setdefault("annotated_path", image_path)
                payload.setdefault("used_ocr", bool(payload.get("text")))
                return payload
            auto_vision_payload = vision_payload

    if cv2 is None:
        result = {
            "text": "",
            "confidence": 0.0,
            "message": "OpenCV unavailable",
            "used_ocr": False,
            "annotated_path": image_path,
            "detector_label": detector_label,
        }
        if ai_status is not None:
            result["ai_status"] = ai_status
            result["ai_error"] = ai_error
            result["review_required"] = True
        return result

    frame = _load_runtime_frame(image_path)
    if frame is None:
        return fallback_result(
            {
                "text": "",
                "confidence": 0.0,
                "message": "Invalid image",
                "used_ocr": False,
                "annotated_path": image_path,
                "detector_label": detector_label,
            }
        )

    alpr = load_fast_alpr(detector_model)
    results = []
    annotated_path = image_path

    if alpr is not None:
        try:
            drawn = alpr.draw_predictions(frame)
            results = drawn.results or []
            try:
                annotated_path = save_annotated_image(cv2, drawn.image, "alpr")
            except OSError:
                # Annotation is optional; never repeat recognition after a disk error.
                annotated_path = image_path
        except Exception:
            try:
                results = alpr.predict(image_path) or []
            except Exception:
                results = []
            annotated_path = image_path

    fast_payload = None
    if results:
        candidates = [
            payload for payload in (_build_candidate_payload(item) for item in results) if payload
        ]
        if len(results) > 1:
            return fallback_result(
                {
                    "text": "",
                    "confidence": 0.0,
                    "is_usable": False,
                    "used_ocr": False,
                    "ambiguous": True,
                    "review_required": True,
                    "plate_count": len(results),
                    "ocr_engine": "fast-alpr-easyocr",
                    "candidates": candidates,
                    "annotated_path": annotated_path,
                    "detector_label": detector_label,
                    "quality_note": "Có nhiều biển số; hãy chọn ảnh chỉ có một xe hoặc nhập tay sau khi đối chiếu.",
                }
            )
        conflict = next((item for item in candidates if item.get("ocr_disagreement")), None)
        if conflict:
            return fallback_result(
                dict(
                    conflict,
                    used_ocr=False,
                    annotated_path=annotated_path,
                    detector_label=detector_label,
                    ocr_engine="fast-alpr-easyocr",
                )
            )
        best = max(candidates, key=_score_ocr_payload) if candidates else None
        if best:
            det_conf = float(best.get("detector_confidence", 0.0) or 0.0)
            fast_payload = {
                "text": best.get("text", ""),
                "confidence": best.get("confidence", 0.0),
                "message": f"{detector_label} • fast-alpr (det {det_conf:.2f}) • {best.get('quality_note', '')}",
                "used_ocr": bool(best.get("text")),
                "annotated_path": annotated_path,
                "detector_label": detector_label,
                "raw_text": best.get("raw_text", ""),
                "is_usable": bool(best.get("is_usable")),
                "quality_note": best.get("quality_note", ""),
                "normalized_text": best.get("normalized_text", ""),
                "ocr_engine": "fast-alpr-easyocr",
                "candidates": candidates,
            }

    if requested_engine == "paddleocr":
        paddle_payload = _run_paddle_ocr(image_path, detector_label, annotated_path)
        if paddle_payload:
            return fallback_result(paddle_payload)
        if fast_payload:
            return fallback_result(fast_payload)
    elif requested_engine in {"easyocr", "fast-alpr", "fast-alpr-easyocr"}:
        if fast_payload:
            return fallback_result(fast_payload)
        paddle_payload = _run_paddle_ocr(image_path, detector_label, annotated_path)
        if paddle_payload:
            return fallback_result(paddle_payload)
    else:
        if _is_good_enough(fast_payload) and not OCR_ACCURACY_MODE:
            return fallback_result(fast_payload)
        paddle_payload = None
        if ENABLE_PADDLE_FALLBACK or ENABLE_PADDLE_OCR:
            paddle_payload = _run_paddle_ocr(image_path, detector_label, annotated_path)
        vision_candidate = None
        if auto_vision_payload is not None:
            vision_candidate = _prepare_vision_candidate(
                auto_vision_payload, detector_label, annotated_path
            )
        fused_payload = _fuse_ocr_candidates(
            [fast_payload, paddle_payload, vision_candidate], detector_label, annotated_path
        )
        if fused_payload:
            return fallback_result(fused_payload)

    missing = []
    if ALPR is None:
        missing.append("fast-alpr")
    if easyocr is None:
        missing.append("easyocr")
    if PaddleOCR is None:
        missing.append("paddleocr")
    return fallback_result(
        {
            "text": "",
            "confidence": 0.0,
            "message": (f"Thiếu {', '.join(missing)}" if missing else "OCR failed"),
            "used_ocr": False,
            "annotated_path": annotated_path,
            "detector_label": detector_label,
            "raw_text": "",
            "is_usable": False,
            "quality_note": "Không có kết quả OCR",
            "ocr_engine": "unavailable",
        }
    )
