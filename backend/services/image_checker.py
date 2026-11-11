"""Vision engine of the Multimodal Compliance Inspector (OpenCV + NumPy).

Checks: brand-palette conformance (k-means dominant colours in CIELAB, ΔE), WCAG text contrast on detected text
regions, minimum resolution, alt-text quality (WCAG 1.1.1), logo clear-space, and a text-vs-image co-verification
(heuristic colour evidence, upgraded to a VLM opinion when an API key is configured).
"""
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from backend import config
from backend.services import llm


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lab(rgb):
    px = np.uint8([[list(rgb)]])
    l, a, b = cv2.cvtColor(px, cv2.COLOR_RGB2LAB)[0, 0].astype(float)
    return np.array([l * 100 / 255, a - 128, b - 128])


def _lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(float(x)) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(c1, c2):
    a, b = _lum(c1), _lum(c2)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def suggest_contrast_color(fg, bg, target_ratio=4.5):
    fg = np.array(fg, dtype=float)
    bg = np.array(bg, dtype=float)
    best_color = None
    min_dist = float("inf")

    # Darken towards black [0, 0, 0]
    for t in np.linspace(0, 1, 256):
        cand = np.clip(fg * (1.0 - t), 0, 255)
        if contrast_ratio(cand, bg) >= target_ratio:
            dist = float(np.linalg.norm(cand - fg))
            if dist < min_dist:
                min_dist = dist
                best_color = cand
            break

    # Lighten towards white [255, 255, 255]
    for t in np.linspace(0, 1, 256):
        cand = np.clip(fg + (255.0 - fg) * t, 0, 255)
        if contrast_ratio(cand, bg) >= target_ratio:
            dist = float(np.linalg.norm(cand - fg))
            if dist < min_dist:
                min_dist = dist
                best_color = cand
            break

    if best_color is not None:
        c = tuple(int(round(x)) for x in best_color)
        return "#%02X%02X%02X" % c
    return None


def load_rgb(path):
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    return np.array(img.convert("RGB"))


def _issue(rule_key, category, severity, message, source, quote, bbox=None, suggestion=None):
    return {"category": category, "rule_key": rule_key, "severity": severity, "message": message, "start": None, "end": None,
            "match": rule_key + (str(bbox) if bbox else ""), "excerpt": "", "suggestion": suggestion, "auto_fix": False,
            "citation": {"source": source, "quote": quote, "doc_title": None, "score": None}, "bbox": bbox}


def analyze_image(path, alt_text, copy_text, palette, min_contrast=4.5, min_width=800):
    rgb = load_rgb(path)
    h, w = rgb.shape[:2]
    issues, metrics = [], {"width": w, "height": h}

    # ---- alt text (WCAG 1.1.1)
    alt = (alt_text or "").strip()
    src = "WCAG 2.1 AA 1.1.1 · Brand Guidelines §7 Accessibility"
    if not alt:
        issues.append(_issue("img-alt-missing", "accessibility", "high", "Image has no alt text.", src,
                             "Every image must have a meaningful text alternative (WCAG 1.1.1)."))
    elif len(alt) < 10 or re.match(r"^(image|picture|photo|img)\b", alt, re.I) or re.search(r"\.(png|jpe?g)$", alt, re.I):
        issues.append(_issue("img-alt-weak", "accessibility", "medium",
                             "Alt text is too short or generic (avoid “image of…”, filenames).", src,
                             "Describe what the image conveys in context, not that it is an image."))

    # ---- resolution
    if w < min_width:
        issues.append(_issue("img-resolution", "visual", "minor", f"Image is {w}px wide; brand minimum is {min_width}px.",
                             "Brand Guidelines §5 Visual Identity", "Assets must be at least 800px wide for web use."))

    # ---- palette conformance
    small = cv2.resize(rgb, (max(1, int(w * min(1, 200 / max(w, h)))), max(1, int(h * min(1, 200 / max(w, h))))), interpolation=cv2.INTER_AREA)
    z = small.reshape(-1, 3).astype(np.float32)
    cv2.setRNGSeed(7)
    k = min(6, max(1, len(np.unique(z, axis=0))))
    _, labels, centers = cv2.kmeans(z, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 15, 0.5), 3, cv2.KMEANS_PP_CENTERS)
    labels = labels.flatten()
    pal = [(p["name"], p["hex"], _lab(_hex_to_rgb(p["hex"]))) for p in palette]
    sh, sw = small.shape[:2]
    dom = []
    for ci in np.argsort(-np.bincount(labels, minlength=k)):
        pct = float((labels == ci).mean() * 100)
        c = tuple(int(v) for v in centers[ci])
        hsv = cv2.cvtColor(np.uint8([[list(c)]]), cv2.COLOR_RGB2HSV)[0, 0] / np.array([179.0, 255.0, 255.0])
        neutral = hsv[1] < 0.14 or hsv[2] < 0.12
        d, nearest = min(((float(np.linalg.norm(_lab(c) - pl)), (n, hx)) for n, hx, pl in pal), key=lambda t: t[0]) if pal else (0, ("", ""))
        ok = neutral or d <= 24
        dom.append({"hex": "#%02X%02X%02X" % c, "pct": round(pct, 1), "ok": bool(ok), "neutral": bool(neutral), "nearest": nearest[1], "delta_e": round(d, 1)})
        if not ok and pct >= 7:
            ys, xs = np.where(labels.reshape(sh, sw) == ci)
            bbox = [int(xs.min() * w / sw), int(ys.min() * h / sh), int((xs.max() - xs.min() + 1) * w / sw), int((ys.max() - ys.min() + 1) * h / sh)]
            issues.append(_issue("img-palette", "visual", "medium",
                                 f"Colour {dom[-1]['hex']} covers {pct:.0f}% of the image and is off-palette (ΔE {d:.0f} from {nearest[0]} {nearest[1]}).",
                                 "Brand Guidelines §5 Visual Identity", "Use only the approved brand palette for dominant colours.",
                                 bbox, f"Recolour towards {nearest[1]}"))
    metrics["dominant_colors"] = dom

    # ---- WCAG contrast on text-like regions
    scale = min(1.0, 1200 / max(w, h))
    g = cv2.cvtColor(cv2.resize(rgb, None, fx=scale, fy=scale) if scale < 1 else rgb, cv2.COLOR_RGB2GRAY)
    rgb_s = cv2.resize(rgb, None, fx=scale, fy=scale) if scale < 1 else rgb
    grad = cv2.morphologyEx(g, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    # fixed low threshold (not Otsu) so faint, low-contrast text is still found as an edge region
    _, bw = cv2.threshold(grad, 12, 255, cv2.THRESH_BINARY)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5)))
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = sorted((cv2.boundingRect(c) for c in cnts), key=lambda r: -r[2] * r[3])
    checked, worst = 0, []
    for x, y, rw, rh in regions:
        if rw < 30 or not (6 <= rh <= 140) or rw / rh < 1.8 or checked >= 10:
            continue
        roi_g, roi = g[y:y + rh, x:x + rw], rgb_s[y:y + rh, x:x + rw]
        t, mask = cv2.threshold(roi_g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        frac = float((mask > 0).mean())
        if not 0.04 < frac < 0.96:
            continue
        a, b = roi[mask > 0].mean(axis=0), roi[mask == 0].mean(axis=0)
        fg, bg = (a, b) if frac < 0.5 else (b, a)
        checked += 1
        bbox = [int(x / scale), int(y / scale), int(rw / scale), int(rh / scale)]
        orig_h = bbox[3]
        if orig_h < 14:
            issues.append(_issue("img-text-small", "accessibility", "medium",
                                 f"Text height ({orig_h}px) is under 14px, which impairs legibility.",
                                 "Brand Guidelines §7 Accessibility",
                                 "Text in graphics must be at least 14px for legibility.", bbox,
                                 "Increase font size to at least 14px."))

        ratio = contrast_ratio(fg, bg)
        need = 3.0 if orig_h >= 28 else min_contrast
        worst.append(round(ratio, 2))
        if ratio < need:
            sug_hex = suggest_contrast_color(fg, bg, 4.5)
            sug_text = f"Change text colour to {sug_hex}" if sug_hex else "Darken the text or lighten the background."
            issues.append(_issue("img-contrast", "accessibility", "high",
                                 f"Text contrast {ratio:.1f}:1 is below the WCAG AA minimum of {need}:1.",
                                 "WCAG 2.1 AA 1.4.3 · Brand Guidelines §7 Accessibility",
                                 "Text must have a contrast ratio of at least 4.5:1 (3:1 for large text).", bbox,
                                 sug_text))
    metrics["text_regions_checked"], metrics["contrast_ratios"] = checked, worst[:8]

    # ---- logo clear space
    issues += _logo_check(rgb)

    # ---- multimodal co-verification
    issues += _co_verify(path, rgb, " ".join([alt, copy_text or ""]))
    return {"issues": issues, "metrics": metrics}


def _logo_check(rgb):
    logos = [p for p in Path(config.LOGO_DIR).glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
    if not logos:
        return []
    h, w = rgb.shape[:2]
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    best = (0, None)
    for lp in logos[:3]:
        t = cv2.cvtColor(load_rgb(lp), cv2.COLOR_RGB2GRAY)
        for s in np.linspace(0.08, 0.6, 12):
            tw = int(w * s)
            th = int(t.shape[0] * tw / t.shape[1])
            if tw < 16 or th < 8 or tw >= w or th >= h:
                continue
            res = cv2.matchTemplate(g, cv2.resize(t, (tw, th)), cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            if mx > best[0]:
                best = (mx, (loc[0], loc[1], tw, th))
    if best[0] < 0.72:
        return []
    x, y, tw, th = best[1]
    clear = int(0.25 * th)
    edges = cv2.Canny(g, 80, 160)
    x0, y0, x1, y1 = max(0, x - clear), max(0, y - clear), min(w, x + tw + clear), min(h, y + th + clear)
    ring = edges[y0:y1, x0:x1].copy()
    ring[(y - y0):(y - y0 + th), (x - x0):(x - x0 + tw)] = 0
    density = float((ring > 0).mean())
    if min(x, y, w - x - tw, h - y - th) < clear or density > 0.03:
        return [_issue("img-logo-clearspace", "visual", "medium", "Logo clear-space (¼ logo height) is violated.",
                       "Brand Guidelines §5 Visual Identity", "Keep clear space equal to ¼ of the logo height on all sides.", [x, y, tw, th])]
    return []


_CLAIM_VISUAL = re.compile(r"eco|recycl|sustainab|compost|plant[- ]based|kraft|green", re.I)


def _co_verify(path, rgb, text):
    claims = list({m.group(0).lower() for m in re.finditer(r"[^.!?\n]*(?:eco|recycl|sustainab|compost|plant[- ]based)[^.!?\n]*", text, re.I)})
    if not claims or not _CLAIM_VISUAL.search(text):
        return []
    src = "Brand Guidelines §3 Claims · Multimodal co-verification"
    vlm = llm.verify_image_claims(path, [c.strip() for c in claims])
    if vlm:
        return [_issue("mm-claim-mismatch", "multimodal", "high", f"Image does not visibly support: “{v['claim']}” — {v.get('reason', '')}",
                       src, "Claims about packaging or materials must be visible in the supporting image.")
                for v in vlm if not v.get("supported")]
    hsv = cv2.cvtColor(cv2.resize(rgb, (160, 160)), cv2.COLOR_RGB2HSV)
    hh, ss, vv = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = ((hh >= 35) & (hh <= 85) & (ss > 60) & (vv > 50)).mean()
    kraft = ((hh >= 8) & (hh <= 25) & (ss > 60) & (vv > 80) & (vv < 230)).mean()
    if green + kraft < 0.04:
        return [_issue("mm-claim-mismatch", "multimodal", "medium",
                       "Text claims eco/recyclable materials but the image shows no green or kraft/natural-material cues "
                       "(heuristic check — please confirm manually).", src,
                       "Claims about packaging or materials must be visible in the supporting image.")]
    return []
