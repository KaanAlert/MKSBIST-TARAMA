import os
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, date
from io import BytesIO
import schedule
import time
import pytz

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.pdfgen import canvas

TOKEN   = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
TZ      = pytz.timezone("Europe/Istanbul")

# ============================================================
# PORTFOY BILGILERI
# ============================================================

BASLANGIC_TARIHI = date(2026, 3, 2)

PORTFOY = [
    {"hisse": "KRSTL", "adet": 1706, "maliyet": 10.22},
    {"hisse": "LMKDC", "adet": 514,  "maliyet": 30.40},
    {"hisse": "ESCOM", "adet": 2834, "maliyet": 5.14},
    {"hisse": "A1CAP", "adet": 285,  "maliyet": 17.58},
    {"hisse": "ISGSY", "adet": 70,   "maliyet": 107.30},
]

# ============================================================
# YARDIMCI FONKSIYONLAR
# ============================================================

def simdi():
    return datetime.now(TZ)

def yahoo_sembol(h):
    return f"{h}.IS"

def para_fmt(tutar):
    return f"{tutar:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")

def yuzde_fmt(yuzde):
    isaretli = f"{yuzde:+.2f}".replace(".", ",")
    return f"%{isaretli}"

# ============================================================
# VERI CEK
# ============================================================

def kapanis_al(hisse, onceki=False):
    try:
        df = yf.download(yahoo_sembol(hisse), period="10d", interval="1d",
                        progress=False, auto_adjust=True)
        if df is None or len(df) < 2:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return float(df['Close'].iloc[-2] if onceki else df['Close'].iloc[-1])
    except:
        return None

# ============================================================
# HESAPLA
# ============================================================

def hesapla():
    sonuclar = []
    toplam_maliyet   = 0
    toplam_deger     = 0
    gunluk_kz_toplam = 0

    for p in PORTFOY:
        hisse   = p["hisse"]
        adet    = p["adet"]
        maliyet = p["maliyet"]

        kapanis = kapanis_al(hisse) or maliyet
        onceki  = kapanis_al(hisse, onceki=True) or maliyet

        maliyet_toplam = adet * maliyet
        guncel_deger   = adet * kapanis
        kz_tl          = guncel_deger - maliyet_toplam
        kz_yuzde       = ((kapanis - maliyet) / maliyet) * 100
        gunluk_kz      = adet * (kapanis - onceki)

        toplam_maliyet   += maliyet_toplam
        toplam_deger     += guncel_deger
        gunluk_kz_toplam += gunluk_kz

        sonuclar.append({
            "hisse":          hisse,
            "maliyet":        maliyet,
            "adet":           adet,
            "kapanis":        kapanis,
            "maliyet_toplam": maliyet_toplam,
            "guncel_deger":   guncel_deger,
            "kz_tl":          kz_tl,
            "kz_yuzde":       kz_yuzde,
            "gunluk_kz":      gunluk_kz,
        })

    aylik_kz        = toplam_deger - toplam_maliyet
    toplam_kz_yuzde = ((toplam_deger - toplam_maliyet) / toplam_maliyet) * 100

    return sonuclar, {
        "toplam_maliyet":  toplam_maliyet,
        "toplam_deger":    toplam_deger,
        "gunluk_kz":       gunluk_kz_toplam,
        "aylik_kz":        aylik_kz,
        "toplam_kz_yuzde": toplam_kz_yuzde,
    }

# ============================================================
# RENK PALETI
# ============================================================

C_MAVI     = colors.HexColor("#1A1AFF")
C_BEYAZ    = colors.white
C_SIYAH    = colors.HexColor("#1A1A1A")
C_GRI_ACIK = colors.HexColor("#F8F8F8")
C_GRI_ORTA = colors.HexColor("#E0E0E0")
C_YESIL    = colors.HexColor("#1A7A1A")
C_KIRMIZI  = colors.HexColor("#CC0000")

# ============================================================
# PDF OLUSTUR
# ============================================================

def pdf_olustur(sonuclar, ozet):
    buffer = BytesIO()
    w, h = A4

    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle("Portfolio Statement")

    margin_x    = 2*cm
    margin_y    = 2*cm
    ic_genislik = w - 2 * margin_x

    y = h - margin_y

    # ---- STATEMENT NO (top right) ----
    now        = simdi()
    ekstre_no  = now.strftime("%Y%m%d")
    ekstre_txt = f"STATEMENT NO: {ekstre_no}"
    c.setFillColor(C_SIYAH)
    c.setFont("Helvetica-Bold", 10)
    ekstre_w = c.stringWidth(ekstre_txt, "Helvetica-Bold", 10)
    c.drawString(w - margin_x - ekstre_w, y, ekstre_txt)

    # ---- Portfolio start date (top left) ----
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(margin_x, y, f"Portfolio Start: {BASLANGIC_TARIHI.strftime('%d.%m.%Y')}")

    y -= 0.5*cm

    # ---- Data date (right) ----
    tarih_txt = f"Data Date: {now.strftime('%d.%m.%Y %H:%M')}"
    c.setFont("Helvetica", 8)
    tarih_w = c.stringWidth(tarih_txt, "Helvetica", 8)
    c.drawString(w - margin_x - tarih_w, y, tarih_txt)

    y -= 1.2*cm

    # ---- MAIN TABLE ----
    col_w = [
        ic_genislik * 0.12,  # STOCK
        ic_genislik * 0.15,  # COST
        ic_genislik * 0.08,  # QTY
        ic_genislik * 0.17,  # CLOSE PRICE
        ic_genislik * 0.17,  # VALUE
        ic_genislik * 0.17,  # P / L
        ic_genislik * 0.14,  # P/L %
    ]

    headers = ["STOCK", "COST", "QTY", "CLOSE\nPRICE", "VALUE", "P / L", "P/L %"]

    satir_y  = y
    satir_h  = 1.1*cm
    baslik_h = 1.4*cm

    # Header row
    c.setFillColor(C_MAVI)
    c.rect(margin_x, satir_y - baslik_h, ic_genislik, baslik_h, fill=1, stroke=0)

    c.setFillColor(C_BEYAZ)
    c.setFont("Helvetica-Bold", 8.5)
    x_pos = margin_x
    for header, cw in zip(headers, col_w):
        hx    = x_pos + cw / 2
        lines = header.split("\n")
        if len(lines) == 2:
            c.drawCentredString(hx, satir_y - baslik_h / 2 + 2,  lines[0])
            c.drawCentredString(hx, satir_y - baslik_h / 2 - 8, lines[1])
        else:
            c.drawCentredString(hx, satir_y - baslik_h / 2 - 3, header)
        x_pos += cw

    satir_y -= baslik_h

    # Data rows
    for idx, r in enumerate(sonuclar):
        c.setFillColor(C_BEYAZ if idx % 2 == 0 else C_GRI_ACIK)
        c.rect(margin_x, satir_y - satir_h, ic_genislik, satir_h, fill=1, stroke=0)

        c.setStrokeColor(C_GRI_ORTA)
        c.setLineWidth(0.5)
        c.line(margin_x, satir_y - satir_h, w - margin_x, satir_y - satir_h)

        cells = [
            r['hisse'],
            para_fmt(r['maliyet']),
            str(r['adet']),
            para_fmt(r['kapanis']),
            para_fmt(r['guncel_deger']),
            para_fmt(r['kz_tl']),
            yuzde_fmt(r['kz_yuzde']),
        ]

        x_pos = margin_x
        for i, (metin, cw) in enumerate(zip(cells, col_w)):
            if i in (5, 6):
                c.setFillColor(C_YESIL if r['kz_tl'] >= 0 else C_KIRMIZI)
                c.setFont("Helvetica-Bold", 8.5)
            elif i == 0:
                c.setFillColor(C_SIYAH)
                c.setFont("Helvetica-Bold", 8.5)
            else:
                c.setFillColor(C_SIYAH)
                c.setFont("Helvetica", 8.5)

            c.drawCentredString(x_pos + cw / 2, satir_y - satir_h / 2 - 3, metin)
            x_pos += cw

        satir_y -= satir_h

    # ---- SUMMARY TABLE (bottom right) ----
    ozet_y       = satir_y - 0.6*cm
    ozet_x       = w - margin_x - 8*cm
    ozet_col1    = 5.5*cm
    ozet_col2    = 2.5*cm
    ozet_satir_h = 0.85*cm

    ozet_rows = [
        ("DAILY P / L AVG",  para_fmt(ozet['gunluk_kz']),    ozet['gunluk_kz'] >= 0),
        ("MONTHLY P / L",    para_fmt(ozet['aylik_kz']),     ozet['aylik_kz'] >= 0),
        ("TOTAL",            para_fmt(ozet['toplam_deger']), None),
    ]

    for i, (label, value, pozitif) in enumerate(ozet_rows):
        son_satir = (i == len(ozet_rows) - 1)

        c.setFillColor(C_MAVI if son_satir else C_GRI_ACIK)
        c.rect(ozet_x, ozet_y - ozet_satir_h, ozet_col1 + ozet_col2, ozet_satir_h, fill=1, stroke=0)
        c.setStrokeColor(C_GRI_ORTA)
        c.setLineWidth(0.5)
        c.rect(ozet_x, ozet_y - ozet_satir_h, ozet_col1 + ozet_col2, ozet_satir_h, fill=0, stroke=1)

        c.setFillColor(C_BEYAZ if son_satir else C_SIYAH)
        c.setFont("Helvetica-Bold" if son_satir else "Helvetica", 9 if son_satir else 8.5)
        c.drawString(ozet_x + 0.3*cm, ozet_y - ozet_satir_h / 2 - 3, label)

        font_size = 9 if son_satir else 8.5
        if son_satir:
            c.setFillColor(C_BEYAZ)
        elif pozitif is True:
            c.setFillColor(C_YESIL)
        elif pozitif is False:
            c.setFillColor(C_KIRMIZI)
        else:
            c.setFillColor(C_SIYAH)
        c.setFont("Helvetica-Bold", font_size)
        val_w = c.stringWidth(value, "Helvetica-Bold", font_size)
        c.drawString(ozet_x + ozet_col1 + ozet_col2 - val_w - 0.3*cm,
                     ozet_y - ozet_satir_h / 2 - 3, value)

        ozet_y -= ozet_satir_h

    # ---- FOOTER ----
    c.setFillColor(colors.HexColor("#999999"))
    c.setFont("Helvetica-Oblique", 6.5)
    c.drawString(margin_x, margin_y,
                 "* Prices based on Yahoo Finance closing data. Daily P/L calculated vs previous close.")

    c.save()
    buffer.seek(0)
    return buffer

# ============================================================
# TELEGRAM
# ============================================================

def telegram_pdf_gonder(pdf_buffer, dosya_adi):
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    r = requests.post(
        url,
        data={"chat_id": CHAT_ID, "caption": f"Portfolio Statement - {dosya_adi}"},
        files={"document": (dosya_adi, pdf_buffer, "application/pdf")}
    )
    print(f"PDF sent: {r.status_code} {simdi().strftime('%H:%M')}")

def telegram_metin_gonder(mesaj):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "Markdown"})
    print(f"Text sent: {r.status_code} {simdi().strftime('%H:%M')}")

def ozet_mesaj(sonuclar, ozet):
    now = simdi()
    mesaj  = f"*PORTFOLIO STATEMENT - {now.strftime('%d.%m.%Y')}*\n\n"
    mesaj += "`Stock  | Close    | P/L TL      | P/L%`\n"
    mesaj += "`" + "-"*42 + "`\n"
    for r in sonuclar:
        h   = r['hisse'].ljust(6)
        kap = f"{r['kapanis']:.2f}".ljust(8)
        kzt = f"{r['kz_tl']:+.0f}TL".ljust(11)
        kzp = f"{r['kz_yuzde']:+.1f}%"
        mesaj += f"`{h} | {kap} | {kzt} | {kzp}`\n"
    mesaj += f"\n*Daily P/L:* {para_fmt(ozet['gunluk_kz'])}"
    mesaj += f"\n*Monthly P/L:* {para_fmt(ozet['aylik_kz'])}"
    mesaj += f"\n*Total Value:* {para_fmt(ozet['toplam_deger'])}"
    mesaj += f"\n*Total P/L:* {yuzde_fmt(ozet['toplam_kz_yuzde'])}"
    return mesaj

# ============================================================
# MAIN
# ============================================================

def ekstre_gonder():
    print(f"Preparing statement... {simdi().strftime('%H:%M')}")
    sonuclar, ozet = hesapla()
    telegram_metin_gonder(ozet_mesaj(sonuclar, ozet))
    now       = simdi()
    dosya_adi = f"PORTFOLIO_{now.strftime('%d%m%Y')}.pdf"
    pdf_buf   = pdf_olustur(sonuclar, ozet)
    telegram_pdf_gonder(pdf_buf, dosya_adi)
    print(f"Done: {simdi().strftime('%H:%M')}")

# ============================================================
# SCHEDULE -- TR 18:00 (UTC 15:00)
# ============================================================

schedule.every().day.at("15:00").do(ekstre_gonder)

print("Portfolio bot started. Statement will be sent daily at 18:00 TR time.")
ekstre_gonder()

while True:
    schedule.run_pending()
    time.sleep(30)
