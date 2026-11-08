import json, os, re, threading, time, webbrowser
import urllib.request, urllib.error, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import social
import governance       # Import mô-đun kiểm duyệt rủi ro chuyên biệt
import gans_integration # Import mô-đun tích hợp GANs Studio

BASE = "https://generativelanguage.googleapis.com/v1beta"
HERE = os.path.dirname(os.path.abspath(__file__))

# Lấy cổng PORT tự động từ biến môi trường của Render (mặc định 5000 nếu chạy local)
PORT = int(os.environ.get("PORT", 5000))


def call(url, body=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": {"message": str(e)}}


def friendly(status, msg):
    if status == 400 and re.search("API key", msg or "", re.I):
        return "API key không hợp lệ. Hãy tạo key mới tại aistudio.google.com và dán lại."
    if status == 403:
        return "Key không có quyền dùng Gemini (hoặc khu vực/tài khoản bị chặn). Chi tiết: " + msg
    if status == 429:
        return "Đã hết hạn mức miễn phí tạm thời. Đợi 1 phút rồi thử lại. Chi tiết: " + msg
    if status == 404:
        return "Model không tồn tại với key này. Chi tiết: " + msg
    return msg or ("Lỗi HTTP %s" % status)


def err_msg(d):
    return (d.get("error") or {}).get("message", "") if isinstance(d, dict) else ""


_cache = {"models": None}


def pick_models(k):
    """Lấy danh sách model Flash dùng được, ưu tiên bản lite (nhanh nhất). Chỉ hỏi Google 1 lần."""
    if _cache["models"]:
        return _cache["models"], None
    st, d = call("%s/models?pageSize=200&key=%s" % (BASE, k), timeout=30)
    if st != 200:
        return None, friendly(st, err_msg(d))
    names = [m["name"].replace("models/", "") for m in d.get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    names = [n for n in names if "flash" in n and not re.search("image|tts|live|audio|robotics|exp", n)]
    names.sort(reverse=True)
    names.sort(key=lambda n: "lite" not in n)
    _cache["models"] = names[:4] or ["gemini-flash-lite-latest", "gemini-flash-latest"]
    return _cache["models"], None


def generate(key, mime, image, prompt):
    k = urllib.parse.quote(key)
    try:
        models, err = pick_models(k)
    except Exception as e:
        return {"ok": False, "error": "Máy tính của bạn không kết nối được tới Google: %s. "
                "Hãy tắt VPN/proxy, thử mạng khác (4G) hoặc kiểm tra tường lửa, phần mềm diệt virus." % e}
    if err:
        return {"ok": False, "error": err}

    enhanced_prompt = f"""{prompt}
Hãy đóng vai một chuyên gia content marketing chuyên nghiệp. Hãy viết một bài đăng quảng cáo mạng xã hội (Facebook/Instagram) thật chi tiết, dài dặn, sinh động, ngôn từ thu hút, bắt trend và truyền cảm hứng mua sắm dựa trên hình ảnh sản phẩm.

Lưu ý cấu trúc trả về bắt buộc:
- Dòng 1: "Sản phẩm: <tên sản phẩm>"
- Dòng 2: "Danh mục: <chọn 1 trong các loại: Thời trang, Mỹ phẩm, Đồ ăn, Đồ gia dụng, Phụ kiện, Điện tử>"
- Nội dung bài viết chi tiết ở các dòng tiếp theo (viết dài khoảng 3-4 đoạn, mô tả nổi bật ưu điểm, phong cách và kêu gọi hành động mua hàng mạnh mẽ).
- Phần cuối bài viết **bắt buộc** phải có:
  1. Danh sách các hashtag (#) bắt trend, liên quan và phù hợp với sản phẩm.
  2. Đoạn thông tin liên hệ cố định sau:
Hotline: 0347929157
Địa chỉ: 71 Ngũ Hành Sơn
Email: Shopping@gmail.com
"""

    parts = [{"inline_data": {"mime_type": mime, "data": image}}, {"text": enhanced_prompt}]
    fast = {"maxOutputTokens": 1024, "temperature": 0.8, "thinkingConfig": {"thinkingBudget": 0}}
    plain = {"maxOutputTokens": 1024, "temperature": 0.8}
    last = ""
    for m in models:
        for cfg in (fast, plain):
            try:
                st, d = call("%s/models/%s:generateContent?key=%s" % (BASE, m, k),
                           {"contents": [{"parts": parts}], "generationConfig": cfg})
            except Exception as e:
                return {"ok": False, "error": "Gọi Google bị gián đoạn: %s" % e}
            if st != 400 or cfg is plain:
                break
        if st == 200:
            try:
                text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
            except Exception:
                text = ""
            if not text:
                return {"ok": False, "error": "AI không trả về nội dung: " + json.dumps(d)[:300]}
            
            risk_score, risk_level = governance.evaluate_content_risk(text)
            
            return {
                "ok": True, 
                "text": text, 
                "model": m,
                "governance": {
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "message": "Kiểm duyệt tự động hoàn tất theo mô hình BPM." if risk_level == "LOW" else "Nội dung có chứa từ khóa nhạy cảm, khuyến nghị kiểm duyệt thủ công."
                }
            }
        last = friendly(st, err_msg(d)) + " [model: %s]" % m
        if st not in (404, 429, 503):
            break
    _cache["models"] = None
    return {"ok": False, "error": last}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = self.path.split("?")[0]
        if route.startswith("/api/"):
            try:
                res = social.handle_get(route)
                self._send(200, json.dumps(res).encode("utf-8"), "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}).encode("utf-8"), "application/json; charset=utf-8")
            return
        
        html_path = os.path.join(HERE, "ai-marketing.html")
        if route in ("/", "/index.html") and os.path.exists(html_path):
            with open(html_path, "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        else:
            self._send(404, b"Khong tim thay ai-marketing.html cung thu muc voi server.py", "text/html; charset=utf-8")

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n).decode() or "{}")
        except Exception:
            req = {}

        if self.path == "/api/gans/process":
            try:
                image_data = req.get('image')
                if not image_data:
                    out = {"status": "error", "message": "Không tìm thấy dữ liệu ảnh"}
                else:
                    out = gans_integration.process_image_with_gans(image_data)
            except Exception as e:
                out = {"status": "error", "message": str(e)}
            return self._send(200, json.dumps(out).encode(), "application/json; charset=utf-8")

        if self.path.startswith("/api/social/"):
            try:
                out = social.handle_post(self.path, req)
            except Exception as e:
                out = {"ok": False, "error": "Yêu cầu không hợp lệ: %s" % e}
            return self._send(200, json.dumps(out).encode(), "application/json; charset=utf-8")

        if self.path != "/api/generate":
            return self._send(404, b"{}", "application/json")

        try:
            out = generate(req["key"], req.get("mime", "image/jpeg"), req["image"], req["prompt"])
        except Exception as e:
            out = {"ok": False, "error": "Yêu cầu không hợp lệ: %s" % e}
        self._send(200, json.dumps(out).encode(), "application/json; charset=utf-8")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    # Bắt buộc bind thẳng vào "0.0.0.0" sử dụng biến môi trường PORT của Render
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    social.start_worker()
    print(f"Đang chạy server tại cổng {PORT}")
    threading.Thread(target=lambda: (time.sleep(1), webbrowser.open(f"http://127.0.0.1:{PORT}")), daemon=True).start()
    srv.serve_forever()