"""
Review sweep + graphic generation + email delivery.
Called daily via /api/sweep (hit by Render cron job).
"""

import io
import os
import textwrap
import math
from datetime import datetime, timezone

import resend
from PIL import Image, ImageDraw, ImageFont

resend.api_key = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL     = os.getenv("FROM_EMAIL", "auto@easyreviewpost.com")


# ── Graphic generation ─────────────────────────────────────────────────────────

GRAD_COLORS = [
    ((99, 102, 241), (30, 27, 75)),    # indigo
    ((245, 158, 11), (120, 53, 15)),   # amber
    ((236, 72, 153), (131, 24, 67)),   # rose
    ((16, 185, 129), (6, 78, 59)),     # emerald
]

def _lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _gradient_image(w, h, c1, c2):
    img = Image.new("RGB", (w, h))
    px  = img.load()
    for y in range(h):
        for x in range(w):
            t = (x / w + y / h) / 2
            px[x, y] = _lerp_color(c1, c2, t)
    return img


def _load_font(size, bold=False):
    """Try to load a system font, fall back to default."""
    candidates = (
        ["/System/Library/Fonts/Helvetica.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
        if bold else
        ["/System/Library/Fonts/Helvetica.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    )
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, line = [], ""
    for word in words:
        test = f"{line} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_width and line:
            lines.append(line)
            line = word
        else:
            line = test
    if line:
        lines.append(line)
    return lines


def generate_review_png(review_text, author, business_name, palette_index=0):
    """Return PNG bytes for a single review graphic (1080x1350)."""
    W, H    = 1080, 1350
    c1, c2  = GRAD_COLORS[palette_index % len(GRAD_COLORS)]
    img     = _gradient_image(W, H, c1, c2)
    draw    = ImageDraw.Draw(img, "RGBA")

    # Vignette overlay
    vignette = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd       = ImageDraw.Draw(vignette)
    for i in range(200):
        alpha = int(120 * (i / 200) ** 2)
        vd.rectangle([i, i, W - i, H - i], outline=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), vignette).convert("RGB")
    draw = ImageDraw.Draw(img)

    # White card
    pad    = 80
    card_x = pad
    card_y = int(H * 0.12)
    card_w = W - pad * 2
    card_h = int(H * 0.75)
    r      = 32
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                            radius=r, fill=(255, 255, 255), outline=(230, 230, 230), width=1)

    inner_x = card_x + 70
    inner_w = card_w - 140
    y_cursor = card_y + 70

    # Stars
    star_font = _load_font(52)
    stars     = "★★★★★"
    sb        = draw.textbbox((0, 0), stars, font=star_font)
    star_x    = card_x + (card_w - (sb[2] - sb[0])) // 2
    draw.text((star_x, y_cursor), stars, font=star_font, fill=(245, 158, 11))
    y_cursor += (sb[3] - sb[1]) + 48

    # Quote text
    quote_font = _load_font(38)
    lines      = _wrap_text(draw, f'"{review_text}"', quote_font, inner_w)
    max_lines  = 7
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip() + "…\""
    for line in lines:
        lb = draw.textbbox((0, 0), line, font=quote_font)
        lx = card_x + (card_w - (lb[2] - lb[0])) // 2
        draw.text((lx, y_cursor), line, font=quote_font, fill=(30, 30, 30))
        y_cursor += (lb[3] - lb[1]) + 10
    y_cursor += 40

    # Divider
    draw.line([(inner_x, y_cursor), (inner_x + inner_w, y_cursor)],
              fill=(220, 220, 220), width=1)
    y_cursor += 32

    # Author
    author_font = _load_font(30, bold=True)
    ab          = draw.textbbox((0, 0), author, font=author_font)
    ax          = card_x + (card_w - (ab[2] - ab[0])) // 2
    draw.text((ax, y_cursor), author, font=author_font, fill=(50, 50, 50))
    y_cursor += (ab[3] - ab[1]) + 16

    # Business name
    biz_font = _load_font(26)
    bb       = draw.textbbox((0, 0), business_name, font=biz_font)
    bx       = card_x + (card_w - (bb[2] - bb[0])) // 2
    draw.text((bx, y_cursor), business_name, font=biz_font, fill=(140, 140, 140))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── Email delivery ─────────────────────────────────────────────────────────────

def send_review_email(to_email, business_name, reviews_with_images):
    """
    Send an email with review graphics attached.
    reviews_with_images: list of {"author": str, "text": str, "png_bytes": bytes}
    """
    attachments = []
    for i, r in enumerate(reviews_with_images):
        attachments.append({
            "filename": f"review-{i+1}.png",
            "content":  list(r["png_bytes"]),  # Resend expects list of ints
        })

    count    = len(reviews_with_images)
    plural   = "review" if count == 1 else "reviews"
    names    = " · ".join(r["author"] for r in reviews_with_images[:3])
    if count > 3:
        names += f" + {count - 3} more"

    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
      <h2 style="font-size:22px;margin-bottom:4px">
        {count} new 5-star {plural} for {business_name} 🌟
      </h2>
      <p style="color:#666;margin-top:0">{names}</p>
      <p style="font-size:14px;color:#888">
        Your graphics are attached — ready to post anywhere.
      </p>
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
      <p style="font-size:12px;color:#aaa">
        You're receiving this because you subscribed to Auto on
        <a href="https://easyreviewpost.com" style="color:#6366F1">easyreviewpost.com</a>.
      </p>
    </div>
    """

    resend.Emails.send({
        "from":        FROM_EMAIL,
        "to":          [to_email],
        "subject":     f"🌟 {count} new {plural} for {business_name}",
        "html":        html,
        "attachments": attachments,
    })
