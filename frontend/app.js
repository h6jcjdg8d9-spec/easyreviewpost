"use strict";

const API = "";

// ── Palette presets ───────────────────────────────────────────────────────────
const PALETTES = [
    { id: "amber",   name: "Amber & Night",  color1: "#F5A623", color2: "#1A1A2E" },
    { id: "indigo",  name: "Indigo & Slate", color1: "#4B6BFB", color2: "#2D3748" },
    { id: "rose",    name: "Rose & Blush",   color1: "#E8476A", color2: "#2D1B2E" },
    { id: "emerald", name: "Emerald & Ink",  color1: "#10B981", color2: "#064E3B" },
];

// ── Style presets ─────────────────────────────────────────────────────────────
const STYLES = [
    {
        id: "classic", name: "Classic", desc: "Serif · timeless",
        sampleFont: `bold italic 16px 'Playfair Display', Georgia, serif`,
        headingFn: (sz) => `bold italic ${sz}px 'Playfair Display', Georgia, serif`,
        bodyFn:    (sz) => `400 ${sz}px 'Playfair Display', Georgia, serif`,
        loadFonts: ["bold italic 1px 'Playfair Display'", "400 1px 'Playfair Display'"],
    },
    {
        id: "handwritten", name: "Handwritten", desc: "Script · personal",
        sampleFont: `700 16px 'Caveat', cursive`,
        headingFn: (sz) => `700 ${sz}px 'Caveat', cursive`,
        bodyFn:    (sz) => `400 ${sz}px 'Caveat', cursive`,
        loadFonts: ["700 1px 'Caveat'", "400 1px 'Caveat'"],
    },
    {
        id: "slab", name: "Slab", desc: "Heavy · bold",
        sampleFont: `700 16px 'Roboto Slab', serif`,
        headingFn: (sz) => `700 ${sz}px 'Roboto Slab', serif`,
        bodyFn:    (sz) => `400 ${sz}px 'Roboto Slab', serif`,
        loadFonts: ["700 1px 'Roboto Slab'", "400 1px 'Roboto Slab'"],
    },
    {
        id: "condensed", name: "Condensed", desc: "Tight · high-impact",
        sampleFont: `700 16px 'Barlow Condensed', sans-serif`,
        headingFn: (sz) => `700 ${sz}px 'Barlow Condensed', sans-serif`,
        bodyFn:    (sz) => `700 ${sz}px 'Barlow Condensed', sans-serif`,
        loadFonts: ["700 1px 'Barlow Condensed'"],
    },
];

// ── Platform configs (replaces LAYOUT_CONFIGS) ────────────────────────────────
const PLATFORM_CONFIGS = {
    instagram: {
        label: "Instagram",   size: "1080 × 1350",
        w: 1080, h: 1350,
        padR: 0.0815, starsR: 0.195, textR: 0.290,
        divR: 0.778, authorR: 0.833, attrR: 0.884, bizR: 0.951,
    },
    facebook: {
        label: "Facebook",    size: "1080 × 1350",
        w: 1080, h: 1350,
        padR: 0.0815, starsR: 0.195, textR: 0.290,
        divR: 0.778, authorR: 0.833, attrR: 0.884, bizR: 0.951,
    },
    linkedin: {
        label: "LinkedIn",    size: "1200 × 1200",
        w: 1200, h: 1200,
        padR: 0.0815, starsR: 0.195, textR: 0.290,
        divR: 0.778, authorR: 0.833, attrR: 0.884, bizR: 0.951,
    },
    gpost: {
        label: "Business Post", size: "720 × 720",
        w: 720,  h: 720,
        padR: 0.0815, starsR: 0.195, textR: 0.290,
        divR: 0.778, authorR: 0.833, attrR: 0.884, bizR: 0.951,
    },
};

const PLATFORM_ICONS = {
    instagram: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="0.5" fill="currentColor" stroke="none"/></svg>`,
    facebook:  `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/></svg>`,
    linkedin:  `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"/><rect x="2" y="9" width="4" height="12"/><circle cx="4" cy="4" r="2"/></svg>`,
    gpost:     `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>`,
};


// ── Excerpt cache + AI fetch ───────────────────────────────────────────────────
const excerptCache = new Map();

async function getExcerpt(text) {
    if (!text || text.length < 80) return text;
    if (excerptCache.has(text)) return excerptCache.get(text);
    try {
        const data = await post("/api/excerpt", { text });
        excerptCache.set(text, data.excerpt);
        return data.excerpt;
    } catch {
        const fallback = extractExcerpt(text, 2);
        excerptCache.set(text, fallback);
        return fallback;
    }
}

// ── App state ─────────────────────────────────────────────────────────────────
const state = {
    paletteId:    "amber",
    customPalette: null,
    styleId:      "classic",
    platformId:   "instagram",
    placeId:      null,
    logoImage:    null,
    bgImage:      null,
};

// Step completion gates (require explicit user action)
const stepCompleted = { step1: false, step2: false, step3: false, step4: false };

let currentReviews      = [];
let currentBusinessName = "";

// ── Font / palette helpers ────────────────────────────────────────────────────
function getHeadingFont(sz) {
    const style = STYLES.find(s => s.id === state.styleId);
    return style ? style.headingFn(sz) : `bold italic ${sz}px Georgia, serif`;
}

function getBodyFont(sz) {
    const style = STYLES.find(s => s.id === state.styleId);
    return style ? style.bodyFn(sz) : `500 ${sz}px 'Helvetica Neue', Arial, sans-serif`;
}

function hexToRGB(hex) {
    const h = hex.replace("#", "");
    return {
        r: parseInt(h.slice(0, 2), 16),
        g: parseInt(h.slice(2, 4), 16),
        b: parseInt(h.slice(4, 6), 16),
    };
}

function isValidHex(h) { return /^#[0-9A-Fa-f]{6}$/.test(h); }

function getCanvasPalette() {
    let color1 = "#F5A623", color2 = "#1A1A2E";
    if (state.paletteId === "custom" && state.customPalette) {
        if (isValidHex(state.customPalette.color1)) color1 = state.customPalette.color1;
        if (isValidHex(state.customPalette.color2)) color2 = state.customPalette.color2;
    } else {
        const pal = PALETTES.find(p => p.id === state.paletteId);
        if (pal) { color1 = pal.color1; color2 = pal.color2; }
    }
    return {
        color1,
        color2,
        textPrimary: "#FFFFFF",
        textMuted:   "rgba(255,255,255,0.70)",
        textDim:     "rgba(255,255,255,0.25)",
        divider:     "rgba(255,255,255,0.15)",
    };
}

// ── DOM refs ──────────────────────────────────────────────────────────────────
const fetchBtn         = document.getElementById("fetch-btn");
const ctaHint          = document.getElementById("cta-hint");
const lookupError      = document.getElementById("lookup-error");
const statusMsg        = document.getElementById("status-msg");
const reviewsGrid      = document.getElementById("reviews-grid");
const outputEmpty      = document.getElementById("output-empty");
const outputActions    = document.getElementById("output-actions");
const searchInput      = document.getElementById("business-search");
const searchDropdown   = document.getElementById("search-dropdown");

window.addEventListener("load", () => searchInput.focus());

// ── Cookie helpers ────────────────────────────────────────────────────────────
function getCookie(name) {
    const val   = `; ${document.cookie}`;
    const parts = val.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
}

function setCookie(name, value, days) {
    document.cookie = `${name}=${value}; max-age=${days * 86400}; path=/; SameSite=Lax`;
}

// ── Modal ─────────────────────────────────────────────────────────────────────
function openAutoModal() {
    const modal = document.getElementById("auto-modal");
    // Pre-fill business name if one is selected
    const bizDisplay = document.getElementById("auto-biz-display");
    if (typeof currentBusinessName !== "undefined" && currentBusinessName) bizDisplay.value = currentBusinessName;
    modal.classList.remove("hidden");
}
function closeAutoModal() { document.getElementById("auto-modal").classList.add("hidden"); }

// ── Stripe return (runs on page load if ?session_id= is present) ──────────────
async function handleStripeReturn() {
    const params    = new URLSearchParams(window.location.search);
    const sessionId = params.get("session_id");
    if (!sessionId) return;

    try {
        const data = await post("/api/unlock-session", { session_id: sessionId });
        if (data.token) {
            setCookie("erp_custom_unlocked", data.token, 3650); // ~10 years
            window.history.replaceState({}, "", window.location.pathname);
        }
    } catch (e) {
        console.warn("Stripe session verification failed:", e);
    }
}

// ── CTA unlock state ──────────────────────────────────────────────────────────
function updateCTAState() {
    if (!stepCompleted.step1) {
        fetchBtn.disabled   = true;
        ctaHint.textContent = "Paste your URL first to get started";
        ctaHint.classList.remove("hidden");
    } else {
        fetchBtn.disabled   = false;
        ctaHint.textContent = "Ready when you are.";
        ctaHint.classList.remove("hidden");
    }
}

// ── Phase 1: Business search ──────────────────────────────────────────────────
let searchTimer = null;

searchInput.addEventListener("input", () => {
    const q = searchInput.value.trim();
    clearTimeout(searchTimer);

    if (q.length < 3) {
        closeDropdown();
        return;
    }

    searchTimer = setTimeout(() => doSearch(q), 300);
});

searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDropdown();
});

document.addEventListener("click", (e) => {
    if (!searchInput.contains(e.target) && !searchDropdown.contains(e.target)) {
        closeDropdown();
    }
});

async function doSearch(q) {
    try {
        const data = await get(`/api/search?query=${encodeURIComponent(q)}`);
        renderDropdown(data.results);
    } catch {
        closeDropdown();
    }
}

function renderDropdown(results) {
    if (!results || results.length === 0) {
        closeDropdown();
        return;
    }
    searchDropdown.innerHTML = "";
    results.forEach(r => {
        const li = document.createElement("li");
        li.className = "search-result-item";
        li.innerHTML = `<span class="result-name">${esc(r.name)}</span><span class="result-address">${esc(r.address)}</span>`;
        li.addEventListener("click", () => selectBusiness(r));
        searchDropdown.appendChild(li);
    });
    searchDropdown.classList.remove("hidden");
}

function closeDropdown() {
    searchDropdown.classList.add("hidden");
    searchDropdown.innerHTML = "";
}

function selectBusiness(place) {
    state.placeId       = place.place_id;
    currentBusinessName = place.name;
    searchInput.value   = place.name;
    closeDropdown();
    lookupError.classList.add("hidden");
    renderBusinessConfirm(place);
    stepCompleted.step1 = true;
    updateCTAState();
    clearReviewsGrid();
    document.querySelectorAll(".step-col:not(:first-child)").forEach(col => col.classList.add("unlocked"));
}

// ── Phase 2: Generate graphics ────────────────────────────────────────────────
fetchBtn.addEventListener("click", async () => {
    if (!state.placeId) return;

    setGenerateLoading(true);
    clearReviewsGrid();

    try {
        showStatus("Fetching reviews…");
        const data    = await post("/api/reviews", { place_id: state.placeId });
        const reviews = data.reviews;

        if (reviews.length === 0) {
            showStatus("No 5-star reviews found for this business.");
        } else {
            await renderReviews(reviews, currentBusinessName);
            console.log('graphics_generated fired', { business_name: currentBusinessName, review_count: reviews.length });
            gtag('event', 'graphics_generated', {
                'business_name': currentBusinessName,
                'review_count': reviews.length,
            });
            setTimeout(() => reviewsGrid.scrollIntoView({ behavior: "smooth", block: "start" }), 100);
        }
    } catch (err) {
        showStatus(err.message, true);
    } finally {
        setGenerateLoading(false);
    }
});

// ── API helpers ───────────────────────────────────────────────────────────────
async function post(path, body) {
    const res  = await fetch(`${API}${path}`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
    return data;
}

async function get(path) {
    const res  = await fetch(`${API}${path}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Error ${res.status}`);
    return data;
}

// ── Render reviews ────────────────────────────────────────────────────────────
async function renderReviews(reviews, businessName) {
    currentReviews      = reviews;
    currentBusinessName = businessName;

    // Pre-fetch AI excerpts for all reviews in parallel before drawing
    showStatus("Crafting your graphics…");
    await Promise.allSettled(
        reviews.map(async (r) => { r._excerpt = await getExcerpt(r.text); })
    );
    hideStatus();

    const tpl = document.getElementById("review-card-tpl");
    reviewsGrid.classList.remove("hidden");
    outputEmpty.classList.add("hidden");
    outputActions.classList.remove("hidden");

    reviews.forEach((review) => {
        const node = tpl.content.cloneNode(true);

        node.querySelector(".card-stars").textContent  = starChars(review.rating);
        node.querySelector(".card-author").textContent = review.author;
        node.querySelector(".card-date").textContent   = review.timestamp
            ? formatDate(review.timestamp)
            : review.relative_time;
        node.querySelector(".card-text").textContent   = review.text;

        reviewsGrid.appendChild(node);
        const card   = reviewsGrid.lastElementChild;
        const canvas = card.querySelector(".preview-canvas");

        const style = STYLES.find(s => s.id === state.styleId) || STYLES[0];
        const loads = (style.loadFonts || []).map(f => document.fonts.load(f));
        Promise.all(loads).then(() => drawGraphic(canvas, review, businessName));

        card.querySelector(".btn-download").addEventListener("click", () => {
            const off = document.createElement("canvas");
            drawGraphic(off, review, businessName);
            downloadPNG(off, review.author);
            gtag("event", "download_individual");
        });

        const confirm = card.querySelector(".copy-confirm");
        card.querySelector(".btn-copy").addEventListener("click", async () => {
            await navigator.clipboard.writeText(buildCaption(review, businessName));
            confirm.classList.remove("hidden");
            setTimeout(() => confirm.classList.add("hidden"), 2000);
        });
    });
}

function redrawAll() {
    const cards = reviewsGrid.querySelectorAll(".review-card");
    cards.forEach((card, i) => {
        const review = currentReviews[i];
        if (!review) return;
        drawGraphic(card.querySelector(".preview-canvas"), review, currentBusinessName);
    });
}

// ── Rounded rect path ─────────────────────────────────────────────────────────
function roundRectPath(ctx, x, y, w, h, r) {
    if (typeof ctx.roundRect === "function") {
        ctx.beginPath();
        ctx.roundRect(x, y, w, h, r);
    } else {
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + r);
        ctx.lineTo(x + w, y + h - r);
        ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
        ctx.lineTo(x + r, y + h);
        ctx.quadraticCurveTo(x, y + h, x, y + h - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
    }
}

// ── Sentence excerpt ──────────────────────────────────────────────────────────
function extractExcerpt(text, maxSentences) {
    if (!text) return "";
    const sentences = text.match(/[^.!?]+[.!?]+(?:\s|$)/g);
    if (!sentences || sentences.length <= maxSentences) return text.trim();
    return sentences.slice(0, maxSentences).join("").trim();
}

// ── Canvas graphic ────────────────────────────────────────────────────────────
function drawGraphic(canvas, review, businessName) {
    const layout  = PLATFORM_CONFIGS[state.platformId] || PLATFORM_CONFIGS.instagram;
    const palette = getCanvasPalette();
    const W   = layout.w;
    const H   = layout.h;
    const ref = Math.min(W, H);
    canvas.width  = W;
    canvas.height = H;
    const ctx = canvas.getContext("2d");
    const cx  = W / 2;

    // 1. 135° diagonal gradient — color1 top-left to color2 bottom-right
    const bgGrad = ctx.createLinearGradient(0, 0, W, H);
    bgGrad.addColorStop(0, palette.color1);
    bgGrad.addColorStop(1, palette.color2);
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, W, H);

    // 2. Inner vignette — draws the eye toward the card
    const gradRadius = Math.max(W, H) * 0.72;
    const vigGrad = ctx.createRadialGradient(cx, H * 0.5, gradRadius * 0.38, cx, H * 0.5, gradRadius);
    vigGrad.addColorStop(0, "rgba(0,0,0,0)");
    vigGrad.addColorStop(1, "rgba(0,0,0,0.28)");
    ctx.fillStyle = vigGrad;
    ctx.fillRect(0, 0, W, H);

    // 3. Floating white card — dual-layer shadow
    const cardX = Math.round(W * 0.11);
    const cardY = Math.round(H * 0.11);
    const cardW = W - cardX * 2;
    const cardH = H - cardY * 2;
    const cardR = Math.round(ref * 0.033);

    // Outer (deep, dramatic lift) — 0 20px 60px rgba(0,0,0,0.25)
    ctx.save();
    ctx.shadowColor   = "rgba(0,0,0,0.25)";
    ctx.shadowBlur    = Math.round(ref * 0.056);
    ctx.shadowOffsetY = Math.round(H * 0.019);
    roundRectPath(ctx, cardX, cardY, cardW, cardH, cardR);
    ctx.fillStyle = "#FFFFFF";
    ctx.fill();
    ctx.restore();

    // Inner (tight accent) — 0 4px 16px rgba(0,0,0,0.15)
    ctx.save();
    ctx.shadowColor   = "rgba(0,0,0,0.15)";
    ctx.shadowBlur    = Math.round(ref * 0.015);
    ctx.shadowOffsetY = Math.round(H * 0.004);
    roundRectPath(ctx, cardX, cardY, cardW, cardH, cardR);
    ctx.fillStyle = "#FFFFFF";
    ctx.fill();
    ctx.restore();

    // Card border — crisp white edge
    ctx.save();
    roundRectPath(ctx, cardX, cardY, cardW, cardH, cardR);
    ctx.strokeStyle = "rgba(255,255,255,0.8)";
    ctx.lineWidth   = Math.max(1, Math.round(ref * 0.0014));
    ctx.stroke();
    ctx.restore();

    // Inner glow — clip to card, stroke bleeds inward
    ctx.save();
    roundRectPath(ctx, cardX, cardY, cardW, cardH, cardR);
    ctx.clip();
    roundRectPath(ctx, cardX, cardY, cardW, cardH, cardR);
    ctx.strokeStyle = "rgba(255,255,255,0.5)";
    ctx.lineWidth   = Math.max(2, Math.round(ref * 0.003));
    ctx.stroke();
    ctx.restore();

    // Card content bounds
    const padCard = Math.round(ref * 0.059);
    const ix      = cardX + padCard;
    const iy      = cardY + padCard;
    const iw      = cardW - padCard * 2;
    const ibot    = cardY + cardH - padCard;

    // 4. Metadata sizes and gaps (all ref-scaled)
    const starSz = Math.round(ref * 0.037);  // ~20px display
    const nameSz = Math.round(ref * 0.026);  // ~14px display
    const dateSz = Math.round(ref * 0.022);  // ~12px display
    const bizSz  = Math.round(ref * 0.020);  // ~11px display
    const gapQ   = Math.round(ref * 0.044);  // 24px gap: quote → stars
    const gapNm  = Math.round(ref * 0.015);  // 8px gap: stars → name
    const gapDt  = Math.round(ref * 0.007);  // 4px gap: name → date
    const gapBz  = Math.round(ref * 0.030);  // 16px gap: date → biz

    const metaH = Math.round(starSz * 1.2)
                + gapNm + Math.round(nameSz * 1.3)
                + gapDt + Math.round(dateSz * 1.3)
                + gapBz + Math.round(bizSz  * 1.4);

    // divY: top of metadata block
    const divY = ibot - metaH;

    // 6. Stars (centered)
    let metaY = divY;
    ctx.save();
    ctx.font         = `${starSz}px Arial, sans-serif`;
    ctx.fillStyle    = "#F59E0B";
    ctx.textAlign    = "center";
    ctx.textBaseline = "top";
    ctx.fillText("★".repeat(Math.min(5, Math.max(1, review.rating))), cx, metaY);
    ctx.restore();
    metaY += Math.round(starSz * 1.2) + gapNm;

    // Name (bold, centered)
    ctx.save();
    ctx.font         = `700 ${nameSz}px 'Helvetica Neue', Arial, sans-serif`;
    ctx.fillStyle    = "#111827";
    ctx.textAlign    = "center";
    ctx.textBaseline = "top";
    ctx.fillText(review.author || "Reviewer", cx, metaY);
    ctx.restore();
    metaY += Math.round(nameSz * 1.3) + gapDt;

    // Date (gray, centered)
    const dateStr = review.timestamp ? formatDate(review.timestamp) : (review.relative_time || "");
    ctx.save();
    ctx.font         = `400 ${dateSz}px 'Helvetica Neue', Arial, sans-serif`;
    ctx.fillStyle    = "#9CA3AF";
    ctx.textAlign    = "center";
    ctx.textBaseline = "top";
    ctx.fillText(dateStr, cx, metaY);
    ctx.restore();
    metaY += Math.round(dateSz * 1.3) + gapBz;

    // Business name or logo (centered, light gray italic)
    if (state.logoImage) {
        const maxW  = Math.round(iw * 0.30);
        const maxH  = Math.round(bizSz * 1.4);
        const scale = Math.min(maxW / state.logoImage.width, maxH / state.logoImage.height, 1);
        const lw    = Math.round(state.logoImage.width  * scale);
        const lh    = Math.round(state.logoImage.height * scale);
        ctx.save();
        ctx.globalAlpha = 0.60;
        ctx.drawImage(state.logoImage, Math.round(cx - lw / 2), metaY, lw, lh);
        ctx.restore();
    } else if (businessName) {
        ctx.save();
        ctx.font         = `italic 400 ${bizSz}px 'Helvetica Neue', Arial, sans-serif`;
        ctx.fillStyle    = "#B0B8C4";
        ctx.textAlign    = "center";
        ctx.textBaseline = "top";
        ctx.fillText(businessName, cx, metaY);
        ctx.restore();
    }

    // 7. Quote — hero text, centered in upper zone (iy → divY - gapQ)
    const quoteAvailH = divY - gapQ - iy;
    const quoteW      = iw;
    const excerpt     = review._excerpt || extractExcerpt(review.text, 3);
    const quoteStr    = `\u201C${excerpt}\u201D`;

    const { fontSize, lines } = fitText(ctx, quoteStr, quoteW, quoteAvailH, getHeadingFont);
    const lineH  = Math.round(fontSize * 1.55);
    const blockH = lines.length * lineH;
    const textY  = iy + Math.max(0, Math.floor((quoteAvailH - blockH) / 2));

    ctx.save();
    ctx.font         = getHeadingFont(fontSize);
    ctx.fillStyle    = "#374151";
    ctx.textAlign    = "center";
    ctx.textBaseline = "top";
    lines.forEach((line, i) => ctx.fillText(line, cx, textY + i * lineH));
    ctx.restore();
}

// ── Text fitting ──────────────────────────────────────────────────────────────
function fitText(ctx, text, maxWidth, maxHeight, fontFn) {
    const sizes = [52, 44, 38, 32, 26, 22, 18];

    for (const fontSize of sizes) {
        ctx.font = fontFn(fontSize);
        const lh    = Math.round(fontSize * 1.55);
        const lines = wrapText(ctx, text, maxWidth);
        if (lines.length * lh <= maxHeight) return { fontSize, lines };
    }

    const fontSize = sizes[sizes.length - 1];
    ctx.font       = fontFn(fontSize);
    const lh       = Math.round(fontSize * 1.55);
    const maxLines = Math.floor(maxHeight / lh);
    const lines    = wrapText(ctx, text, maxWidth).slice(0, maxLines);

    if (lines.length === maxLines) {
        const last = lines[lines.length - 1];
        if (!text.endsWith(last.replace(/\u2026"$/, "").trimEnd())) {
            lines[lines.length - 1] = truncateToFit(ctx, last, maxWidth, "\u2026\u201D");
        }
    }
    return { fontSize, lines };
}

function wrapText(ctx, text, maxWidth) {
    const words = text.split(" ");
    const lines = [];
    let cur     = "";
    for (const word of words) {
        const test = cur ? `${cur} ${word}` : word;
        if (ctx.measureText(test).width > maxWidth && cur) {
            lines.push(cur);
            cur = word;
        } else {
            cur = test;
        }
    }
    if (cur) lines.push(cur);
    return lines;
}

function truncateToFit(ctx, line, maxWidth, suffix) {
    let t = line;
    while (t.length > 0 && ctx.measureText(t + suffix).width > maxWidth) {
        t = t.slice(0, -1).trimEnd();
    }
    return t + suffix;
}

// ── Download ──────────────────────────────────────────────────────────────────
function downloadPNG(canvas, authorName) {
    const slug = authorName.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
    const a    = document.createElement("a");
    a.download = `review-${slug}.png`;
    a.href     = canvas.toDataURL("image/png");
    a.click();
}

// ── Caption builder ───────────────────────────────────────────────────────────
function buildCaption(review, businessName) {
    const stars = "\u2B50".repeat(review.rating);
    return [
        stars,
        "",
        `"${review.text}"`,
        "",
        `\u2014 ${review.author}`,
        "",
        businessName ? `\uD83D\uDCCD ${businessName}` : "",
        "",
        "#customerreviews #5starreview #clientlove #testimonial",
    ].filter((l, i, arr) => !(l === "" && (!arr[i - 1] || arr[i - 1] === ""))).join("\n").trim();
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function renderBusinessConfirm(place) {
    document.getElementById("biz-name-display").textContent    = place.name;
    document.getElementById("biz-address-display").textContent = place.address || "";
    document.getElementById("biz-confirmed").classList.remove("hidden");
}

function showLookupError(msg) {
    lookupError.textContent = msg;
    lookupError.classList.remove("hidden");
}

function showStatus(msg, isError = false) {
    statusMsg.textContent = msg;
    statusMsg.className   = `status-msg${isError ? " error" : ""}`;
    statusMsg.classList.remove("hidden");
}

function hideStatus() { statusMsg.classList.add("hidden"); }

function clearReviewsGrid() {
    reviewsGrid.classList.add("hidden");
    reviewsGrid.innerHTML = "";
    outputActions.classList.add("hidden");
    outputEmpty.classList.remove("hidden");
    currentReviews = [];
    hideStatus();
}


function setGenerateLoading(on) {
    const canGenerate = stepCompleted.step1 && state.datePreset !== null;
    fetchBtn.disabled = on || !canGenerate;
    fetchBtn.querySelector(".btn-text").textContent = on ? "Generating…" : "easyreviewpost →";
}

function starChars(n) { return "\u2605".repeat(n) + "\u2606".repeat(5 - n); }

function formatDate(ts) {
    return new Date(ts * 1000).toLocaleDateString("en-US", {
        year: "numeric", month: "long", day: "numeric",
    });
}

function esc(str) {
    return String(str)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── Panel init ────────────────────────────────────────────────────────────────
function initPanel() {

    // ── Subscription nudge link ────────────────────────────────────────────────
    document.getElementById("sub-nudge-link").addEventListener("click", (e) => {
        e.preventDefault();
        openAutoModal();
    });

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { closeAutoModal(); }
    });

    // ── Auto modal ───────────────────────────────────────────────────────────────
    document.getElementById("auto-modal-close").addEventListener("click", closeAutoModal);
    document.getElementById("auto-modal").addEventListener("click", (e) => {
        if (e.target === e.currentTarget) closeAutoModal();
    });
    document.getElementById("btn-auto-subscribe").addEventListener("click", async () => {
        const btn   = document.getElementById("btn-auto-subscribe");
        const email = document.getElementById("auto-email-input").value.trim();
        if (!email) { document.getElementById("auto-email-input").focus(); return; }
        btn.disabled    = true;
        btn.textContent = "Redirecting…";
        try {
            const data = await post("/api/create-checkout-subscription", { email, place_id: state.placeId });
            window.location.href = data.url;
        } catch (err) {
            btn.disabled    = false;
            btn.textContent = "Start for $9 / month";
        }
    });

    // ── Compact palette rows ────────────────────────────────────────────────────
    const paletteList = document.getElementById("palette-list");

    PALETTES.forEach(pal => {
        const row       = document.createElement("button");
        row.type        = "button";
        row.className   = "palette-row";
        row.dataset.pal = pal.id;

        row.innerHTML = `
            <div class="palette-row-swatches">
                <span class="palette-row-swatch" style="background:${pal.color1}"></span>
                <span class="palette-row-swatch" style="background:${pal.color2}"></span>
            </div>
        `;

        row.addEventListener("click", () => {
            paletteList.querySelectorAll(".palette-row").forEach(r => r.classList.remove("active"));
            document.getElementById("palette-custom-btn").classList.remove("active");
            row.classList.add("active");
            state.paletteId = pal.id;
            stepCompleted.step2 = true;
            redrawAll();
        });

        paletteList.appendChild(row);
    });

    // Custom palette
    const paletteCustomBtn  = document.getElementById("palette-custom-btn");
    const paletteCustomWrap = document.getElementById("palette-custom-wrap");

    paletteCustomBtn.addEventListener("click", () => {
        const open = paletteCustomBtn.classList.toggle("active");
        paletteCustomWrap.classList.toggle("hidden", !open);
        if (open) {
            paletteList.querySelectorAll(".palette-row").forEach(r => r.classList.remove("active"));
            state.paletteId = "custom";
            stepCompleted.step2 = true;
        }
    });

    function applyCustomPalette() {
        state.customPalette = {
            color1: document.getElementById("custom-color1").value,
            color2: document.getElementById("custom-color2").value,
        };
        redrawAll();
    }

    ["custom-color1", "custom-color2"].forEach(id =>
        document.getElementById(id).addEventListener("input", applyCustomPalette)
    );

    // ── Style cards ─────────────────────────────────────────────────────────────
    const fontList = document.getElementById("font-list");

    STYLES.forEach(style => {
        const card          = document.createElement("button");
        card.type           = "button";
        card.className      = "style-card";
        card.dataset.styleId = style.id;

        card.innerHTML = `
            <span class="style-card-name" style="font:${style.sampleFont}">${esc(style.name)}</span>
            <span class="style-card-desc">${esc(style.desc)}</span>
        `;

        card.addEventListener("click", () => {
            fontList.querySelectorAll(".style-card").forEach(c => c.classList.remove("active"));
            card.classList.add("active");
            state.styleId = style.id;
            stepCompleted.step3 = true;
            const loads = (style.loadFonts || []).map(f => document.fonts.load(f));
            Promise.all(loads).then(() => redrawAll());
        });

        fontList.appendChild(card);
    });

    // ── Platform options ────────────────────────────────────────────────────────
    const platformList = document.getElementById("platform-list");

    Object.entries(PLATFORM_CONFIGS).forEach(([id, pc]) => {
        const btn          = document.createElement("button");
        btn.type           = "button";
        btn.className      = "platform-option";
        btn.dataset.platform = id;
        btn.innerHTML      = `
            <span class="platform-icon-wrap">${PLATFORM_ICONS[id]}</span>
            <span class="platform-name">${esc(pc.label)}</span>
            <span class="platform-size">(${esc(pc.size)})</span>
        `;

        btn.addEventListener("click", () => {
            platformList.querySelectorAll(".platform-option").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            state.platformId = id;
            if (!stepCompleted.step4) {
                stepCompleted.step4 = true;
                updateCTAState();
            }
            redrawAll();
        });

        platformList.appendChild(btn);
    });

    // ── Download All ────────────────────────────────────────────────────────────
    document.getElementById("download-all-btn").addEventListener("click", () => {
        const cards = reviewsGrid.querySelectorAll(".review-card");
        cards.forEach((card, i) => {
            const review = currentReviews[i];
            if (!review) return;
            const off = document.createElement("canvas");
            drawGraphic(off, review, currentBusinessName);
            setTimeout(() => downloadPNG(off, review.author), i * 250);
        });
        gtag("event", "download_all");
    });

    // ── Email send ──────────────────────────────────────────────────────────────
    document.getElementById("email-send-btn").addEventListener("click", async () => {
        const email    = document.getElementById("email-input").value.trim();
        const feedback = document.getElementById("email-feedback");
        const btn      = document.getElementById("email-send-btn");
        if (!email || !currentReviews.length) return;

        btn.disabled    = true;
        btn.textContent = "Sending…";
        feedback.classList.add("hidden");

        const graphics = currentReviews.map(review => {
            const off = document.createElement("canvas");
            drawGraphic(off, review, currentBusinessName);
            return { author: review.author, png_b64: off.toDataURL("image/png") };
        });

        try {
            await post("/api/email-graphics", {
                email,
                business_name: currentBusinessName,
                graphics,
            });
            gtag("event", "graphic_emailed");
            feedback.textContent = `Sent to ${email}!`;
        } catch {
            feedback.textContent = "Something went wrong — try again.";
        }

        feedback.classList.remove("hidden");
        btn.disabled    = false;
        btn.textContent = "Send";
        setTimeout(() => feedback.classList.add("hidden"), 5000);
    });
}

// ── Boot ──────────────────────────────────────────────────────────────────────
initPanel();
handleStripeReturn(); // async — exchanges ?session_id= for token if returning from Stripe
updateCTAState();
