"""
image_styles.py - Xử lý nền ảnh KHÔNG cần tách nền.
 
5 phương án:
  1. blur_card   : nền mờ lấy từ chính ảnh + ảnh rõ nét ở giữa (khuyên dùng)
  2. studio_card : ảnh trong khung bo góc, đổ bóng, trên nền studio (gradient / sàn gỗ)
  3. vignette    : chỉnh tông + làm tối/mờ dần ở viền ảnh
  4. outpaint    : mở rộng nền xung quanh ảnh (offline: phản chiếu + làm mờ;
                   hoặc gắn API AI inpaint/outpaint của bạn qua tham số api_fn)
  5. photo tips  : phân tích ảnh (nền có trơn không, sáng, nét, độ phân giải...)
                   và trả về lời khuyên chụp lại -> luôn có trong kết quả ("photo_tips")
 
Ngoài ra: style="frame" là kiểu khung viền + họa tiết cũ dành cho phụ kiện.
 
Cần: pillow, numpy. (opencv-python là tuỳ chọn, chỉ dùng để đo độ nét chính xác hơn.)
 
Cách dùng:
    from image_styles import process_image_with_gans
    res = process_image_with_gans(base64_str, category="Thời trang", style="blur_card")
"""
import base64
import io
 
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter
 
STYLES = ("blur_card", "studio_card", "vignette", "outpaint", "frame", "auto")
DEFAULT_CANVAS = (1080, 1350)  # tỉ lệ 4:5, hợp ảnh sản phẩm / mạng xã hội
 
 
# ----------------------------------------------------------------------------
# TIỆN ÍCH CHUNG
# ----------------------------------------------------------------------------
def _fit(img, box_w, box_h):
    """Thu/phóng ảnh cho vừa khung (giữ tỉ lệ)."""
    s = min(box_w / img.width, box_h / img.height)
    return img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
 
 
def _cover(img, w, h):
    """Phóng ảnh phủ kín khung rồi cắt giữa."""
    s = max(w / img.width, h / img.height)
    r = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
    left, top = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((left, top, left + w, top + h))
 
 
def _rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m
 
 
def _paste_card(canvas, photo, center=None, radius=None, shadow=True, border=0):
    """Dán `photo` lên `canvas` dạng card bo góc có bóng đổ. Trả về canvas (RGBA)."""
    W, H = canvas.size
    radius = radius if radius is not None else max(12, int(min(photo.size) * 0.035))
    x = (W - photo.width) // 2 if center is None else center[0] - photo.width // 2
    y = (H - photo.height) // 2 if center is None else center[1] - photo.height // 2
 
    mask = _rounded_mask(photo.size, radius)
 
    if shadow:
        sh = Image.new("L", (W, H), 0)
        sh.paste(mask, (x, y + int(H * 0.012)))
        sh = sh.filter(ImageFilter.GaussianBlur(max(8, int(min(W, H) * 0.025))))
        sh = sh.point(lambda v: int(v * 0.55))
        black = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        black.putalpha(sh)
        canvas.alpha_composite(black)
 
    card = photo.convert("RGBA")
    if border:
        framed = Image.new("RGBA", (photo.width + 2 * border, photo.height + 2 * border), (255, 255, 255, 255))
        framed.paste(card, (border, border))
        card = framed
        mask = _rounded_mask(card.size, radius + border)
        x -= border
        y -= border
    canvas.paste(card, (x, y), mask)
    return canvas
 
 
# ----------------------------------------------------------------------------
# PHƯƠNG ÁN 1: NỀN MỜ TỪ CHÍNH ẢNH
# ----------------------------------------------------------------------------
def style_blur_card(img, canvas_size=DEFAULT_CANVAS, margin=0.08, blur=0.035, darken=0.72, saturation=1.1):
    W, H = canvas_size
    bg = _cover(img.convert("RGB"), W, H).filter(ImageFilter.GaussianBlur(max(8, int(W * blur))))
    bg = ImageEnhance.Brightness(bg).enhance(darken)
    bg = ImageEnhance.Color(bg).enhance(saturation)
    canvas = bg.convert("RGBA")
    photo = _fit(img.convert("RGB"), int(W * (1 - 2 * margin)), int(H * (1 - 2 * margin)))
    return _paste_card(canvas, photo)
 
 
# ----------------------------------------------------------------------------
# PHƯƠNG ÁN 2: CARD TRÊN NỀN STUDIO
# ----------------------------------------------------------------------------
def _studio_background(W, H, floor="wood"):
    """Tường xám khói (gradient) + sàn (wood | none)."""
    canvas = Image.new("RGBA", (W, H), (38, 38, 38, 255))
    d = ImageDraw.Draw(canvas)
    wall_h = int(H * 0.78) if floor == "wood" else H
    for y in range(wall_h):
        s = int(34 + (y / max(1, wall_h)) * 30)
        d.line([(0, y), (W, y)], fill=(s, s, s, 255))
    if floor == "wood":
        for y in range(wall_h, H):
            f = (y - wall_h) / max(1, H - wall_h)
            d.line([(0, y), (W, y)], fill=(int(96 - f * 46), int(64 - f * 32), int(44 - f * 26), 255))
        # vài đường ván gỗ mờ cho có chiều sâu
        for i in range(1, 8):
            xx = int(W * i / 8)
            d.line([(xx, wall_h), (xx + int((xx - W / 2) * 0.35), H)], fill=(25, 15, 10, 70), width=2)
    # ánh sáng nhẹ ở giữa tường
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse([int(W * 0.1), int(H * 0.05), int(W * 0.9), int(H * 0.8)], fill=60)
    glow = glow.filter(ImageFilter.GaussianBlur(int(W * 0.12)))
    white = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    white.putalpha(glow)
    canvas.alpha_composite(white)
    return canvas
 
 
def style_studio_card(img, canvas_size=DEFAULT_CANVAS, margin=0.09, floor="wood"):
    W, H = canvas_size
    canvas = _studio_background(W, H, floor)
    photo = _fit(img.convert("RGB"), int(W * (1 - 2 * margin)), int(H * (1 - 2 * margin)))
    return _paste_card(canvas, photo, border=max(4, int(W * 0.006)))
 
 
# ----------------------------------------------------------------------------
# PHƯƠNG ÁN 3: CHỈNH TÔNG + VIGNETTE (giữ nguyên kích thước ảnh)
# ----------------------------------------------------------------------------
def style_vignette(img, strength=0.55, edge_blur=6, brightness=1.05, contrast=1.08,
                   color=1.06, warm=0.03):
    rgb = img.convert("RGB")
    rgb = ImageEnhance.Brightness(rgb).enhance(brightness)
    rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
    rgb = ImageEnhance.Color(rgb).enhance(color)
 
    a = np.asarray(rgb).astype(np.float32)
    h, w = a.shape[:2]
    # tông ấm nhẹ (tăng đỏ, giảm xanh dương)
    a[..., 0] *= 1 + warm
    a[..., 2] *= 1 - warm
 
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / np.sqrt(2)
    edge = np.clip((d - 0.35) / 0.65, 0, 1) ** 1.8          # 0 ở giữa -> 1 ở mép
    darkened = a * (1 - strength * edge)[..., None]
 
    # mép ảnh mờ dần để tường xấu ở rìa bớt lộ
    blurred = np.asarray(rgb.filter(ImageFilter.GaussianBlur(edge_blur))).astype(np.float32)
    blurred = blurred * (1 - strength * edge)[..., None]
    k = np.clip(edge * 1.2, 0, 1)[..., None]
    out = darkened * (1 - k) + blurred * k
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).convert("RGBA")
 
 
# ----------------------------------------------------------------------------
# PHƯƠNG ÁN 4: MỞ RỘNG NỀN (OUTPAINT)
# ----------------------------------------------------------------------------
def _outpaint_classic(img, canvas_size):
    """
    Offline, không cần AI: đặt ảnh vừa khung, phần canvas trống được lấp bằng ảnh phản chiếu
    rồi làm mờ mạnh + chuyển tiếp mềm. Không phải AI thật nhưng liền mạch, không bị lộ viền.
    """
    W, H = canvas_size
    photo = _fit(img.convert("RGB"), W, H)
    px, py = (W - photo.width) // 2, (H - photo.height) // 2
 
    arr = np.asarray(photo)
    pad = ((py, H - photo.height - py), (px, W - photo.width - px), (0, 0))
    # reflect cần pad <= kích thước ảnh; lặp nếu cần
    padded = arr
    for _ in range(4):
        cur_h, cur_w = padded.shape[:2]
        need = ((max(0, (H - cur_h) // 2 + (H - cur_h) % 2), max(0, (H - cur_h) // 2)),
                (max(0, (W - cur_w) // 2 + (W - cur_w) % 2), max(0, (W - cur_w) // 2)), (0, 0))
        if cur_h >= H and cur_w >= W:
            break
        need = tuple((min(a, cur), min(b, cur)) for (a, b), cur in zip(need, (cur_h, cur_w, 1)))
        padded = np.pad(padded, need, mode="reflect")
    full = Image.fromarray(padded).crop((0, 0, W, H)) if padded.shape[:2] != (H, W) else Image.fromarray(padded)
    if full.size != (W, H):
        full = full.resize((W, H), Image.LANCZOS)
 
    blurred = full.filter(ImageFilter.GaussianBlur(max(10, int(min(W, H) * 0.04))))
    blurred = ImageEnhance.Brightness(blurred).enhance(0.85)
 
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rectangle([px, py, px + photo.width - 1, py + photo.height - 1], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(6, int(min(W, H) * 0.012))))
 
    sharp = Image.new("RGB", (W, H))
    sharp.paste(photo, (px, py))
    return Image.composite(sharp, blurred, mask).convert("RGBA")
 
 
def style_outpaint(img, canvas_size=DEFAULT_CANVAS, api_fn=None, prompt="clean studio background, soft light"):
    """
    api_fn (tuỳ chọn): hàm do bạn viết, gọi dịch vụ AI inpaint/outpaint (OpenAI images edit,
    Stability, Replicate, Photoroom...). Chữ ký:
        api_fn(image_png: bytes, mask_png: bytes, prompt: str) -> bytes   # ảnh PNG/JPEG kết quả
    Trong đó ảnh gửi đi là canvas đã đặt ảnh gốc ở giữa, mask trắng = vùng cần AI vẽ thêm.
    Nếu api_fn lỗi hoặc không truyền -> tự dùng phương án offline.
    """
    W, H = canvas_size
    if api_fn is not None:
        try:
            photo = _fit(img.convert("RGB"), W, H)
            px, py = (W - photo.width) // 2, (H - photo.height) // 2
            canvas = Image.new("RGB", (W, H), (128, 128, 128))
            canvas.paste(photo, (px, py))
            mask = Image.new("L", (W, H), 255)
            ImageDraw.Draw(mask).rectangle([px, py, px + photo.width - 1, py + photo.height - 1], fill=0)
            b_img, b_mask = io.BytesIO(), io.BytesIO()
            canvas.save(b_img, "PNG")
            mask.save(b_mask, "PNG")
            result = Image.open(io.BytesIO(api_fn(b_img.getvalue(), b_mask.getvalue(), prompt))).convert("RGB")
            if result.size != (W, H):
                result = result.resize((W, H), Image.LANCZOS)
            # luôn dán lại ảnh gốc để chắc chắn không bị AI làm biến dạng sản phẩm
            result.paste(photo, (px, py))
            return result.convert("RGBA")
        except Exception as e:
            print(f"[outpaint] API lỗi, dùng phương án offline: {e}")
    return _outpaint_classic(img, canvas_size)
 
 
# ----------------------------------------------------------------------------
# PHƯƠNG ÁN 5: PHÂN TÍCH ẢNH + LỜI KHUYÊN CHỤP
# ----------------------------------------------------------------------------
def analyze_photo(img):
    """Trả về {'ok': bool, 'metrics': {...}, 'tips': [...]} bằng tiếng Việt."""
    rgb = img.convert("RGB")
    a = np.asarray(rgb).astype(np.float32)
    h, w = a.shape[:2]
    gray = a.mean(axis=2)
 
    # nền có trơn không: độ lệch chuẩn của dải viền trái/phải/trên
    b = max(2, int(min(h, w) * 0.06))
    border = np.concatenate([gray[:, :b].ravel(), gray[:, -b:].ravel(), gray[:b, :].ravel()])
    border_std = float(border.std())
 
    brightness = float(gray.mean())
 
    try:
        import cv2
        sharp = float(cv2.Laplacian(gray.astype(np.uint8), cv2.CV_64F).var())
    except Exception:
        gy, gx = np.gradient(gray)
        sharp = float((gx ** 2 + gy ** 2).var() ** 0.5)
 
    tips = []
    if min(w, h) < 800:
        tips.append(f"Ảnh khá nhỏ ({w}x{h}px). Nên chụp/tải ảnh cạnh ngắn tối thiểu 1000px để không bị vỡ khi phóng.")
    if border_std > 38:
        tips.append("Nền sau lưng nhiều chi tiết/loang lổ. Hãy chụp trước một bức tường trơn (trắng, xám, be) hoặc tấm vải nền để ảnh gọn hơn.")
    if brightness < 80:
        tips.append("Ảnh hơi tối. Chụp gần cửa sổ hoặc ánh sáng ban ngày, tránh ngược sáng.")
    elif brightness > 190:
        tips.append("Ảnh bị cháy sáng. Giảm ánh sáng trực tiếp hoặc chụp lúc dịu nắng.")
    if sharp < 60:
        tips.append("Ảnh có vẻ bị mờ/rung. Giữ máy chắc (hoặc dùng chân máy) và lau ống kính trước khi chụp.")
    if w > h * 1.2:
        tips.append("Ảnh nằm ngang. Với ảnh thời trang nên chụp dọc (4:5) để thấy trọn người và dễ đưa vào khung sản phẩm.")
    if not tips:
        tips.append("Ảnh gốc ổn: nền gọn, đủ sáng và đủ nét.")
 
    return {
        "ok": len(tips) == 1 and tips[0].startswith("Ảnh gốc ổn"),
        "metrics": {"width": w, "height": h, "background_variation": round(border_std, 1),
                    "brightness": round(brightness, 1), "sharpness": round(sharp, 1)},
        "tips": tips,
    }
 
 
# ----------------------------------------------------------------------------
# KIỂU KHUNG VIỀN CŨ (PHỤ KIỆN)
# ----------------------------------------------------------------------------
def style_frame(img):
    width, height = img.size
    bg = Image.new("RGBA", (width, height), (254, 243, 199, 255))
    alpha = img.convert("RGBA").split()[3]
    sh = Image.new("L", (width, height), 0)
    sh.paste(alpha, (0, 8))
    sh = sh.filter(ImageFilter.GaussianBlur(15)).point(lambda v: int(v * 0.4))
    black = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    black.putalpha(sh)
    bg.alpha_composite(black)
    bg.alpha_composite(img.convert("RGBA"))
 
    d = ImageDraw.Draw(bg)
    m, L, c = 15, 30, (219, 39, 119, 255)
    d.rectangle([m, m, width - m, height - m], outline=c, width=4)
    d.rectangle([m + 6, m + 6, width - m - 6, height - m - 6], outline=(244, 114, 182, 180), width=2)
    for cx, cy, dx, dy in [(m, m, 1, 1), (width - m, m, -1, 1), (m, height - m, 1, -1), (width - m, height - m, -1, -1)]:
        d.line([cx, cy, cx + dx * L, cy], fill=c, width=6)
        d.line([cx, cy, cx, cy + dy * L], fill=c, width=6)
    return bg
 
 
# ----------------------------------------------------------------------------
# HÀM CHÍNH (giữ tên cũ để thay thế trực tiếp)
# ----------------------------------------------------------------------------
def process_image_with_gans(image_data, category="Thời trang", style="blur_card",
                            canvas_size=DEFAULT_CANVAS, api_fn=None):
    """
    style: blur_card | studio_card | vignette | outpaint | frame | auto
      auto -> Thời trang: blur_card ; phụ kiện/khác: frame
    """
    print(f"[ImageStyles] Danh mục [{category}] - kiểu [{style}]")
    try:
        if style not in STYLES:
            return {"status": "error", "message": f"style không hợp lệ: {style}. Chọn một trong {STYLES}"}
 
        if "," in image_data:
            image_data = image_data.split(",")[1]
        img = Image.open(io.BytesIO(base64.b64decode(image_data)))
        img = ImageOps_exif(img).convert("RGBA")
 
        cat = (category or "").lower()
        is_fashion = any(k in cat for k in ("thời trang", "clothes", "apparel"))
        if style == "auto":
            style = "blur_card" if is_fashion else "frame"
 
        tips = analyze_photo(img)
 
        if style == "blur_card":
            final = style_blur_card(img, canvas_size)
        elif style == "studio_card":
            final = style_studio_card(img, canvas_size)
        elif style == "vignette":
            final = style_vignette(img)
        elif style == "outpaint":
            final = style_outpaint(img, canvas_size, api_fn=api_fn)
        else:
            final = style_frame(img)
 
        out = io.BytesIO()
        final.convert("RGB").save(out, format="JPEG", quality=95)
        b64 = base64.b64encode(out.getvalue()).decode("utf-8")
        return {
            "status": "success",
            "model": f"BG-Style-{style}",
            "message": f"Đã xử lý ảnh danh mục [{category}] với kiểu [{style}].",
            "processed_image": f"data:image/jpeg;base64,{b64}",
            "photo_tips": tips,
        }
    except Exception as e:
        print(f"[ImageStyles] Lỗi: {e}")
        return {"status": "error", "message": f"Không thể xử lý ảnh: {e}"}
 
 
def ImageOps_exif(img):
    """Xoay ảnh đúng chiều theo EXIF (ảnh chụp điện thoại hay bị xoay)."""
    from PIL import ImageOps
    return ImageOps.exif_transpose(img)
 