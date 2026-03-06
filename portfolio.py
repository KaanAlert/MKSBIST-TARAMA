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
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfgen import canvas
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate

TOKEN   = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
TZ      = pytz.timezone("Europe/Istanbul")

# ============================================================
# PORTFÖY BİLGİLERİ
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
# YARDIMCI FONKSİYONLAR
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
# VERİ ÇEK
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
# RENK PALETİ (Tasarımla birebir)
# ============================================================

C_MAVI      = colors.HexColor("#1A1AFF")
C_BEYAZ     = colors.white
C_SIYAH     = colors.HexColor("#1A1A1A")
C_GRI_ACIK  = colors.HexColor("#F8F8F8")
C_GRI_ORTA  = colors.HexColor("#E0E0E0")
C_YESIL     = colors.HexColor("#1A7A1A")
C_KIRMIZI   = colors.HexColor("#CC0000")
C_CIZGI     = colors.HexColor("#CCCCCC")

# ============================================================
# LOGO ÇİZ (Canvas ile - ok işareti + metin)
# ============================================================

def logo_ciz(c, x, y, genislik=4*cm, yukseklik=2*cm):
    """Yatirim Defterim logosu - ok + metin"""
    # Ok kutucuğu (mavi kare içinde beyaz ok)
    kutu_boyut = 1.2*cm
    c.setFillColor(C_MAVI)
    c.roundRect(x, y - kutu_boyut + 0.3*cm, kutu_boyut, kutu_boyut, 3, fill=1, stroke=0)

    # Beyaz ok işareti
    c.setFillColor(C_BEYAZ)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x + 0.22*cm, y - kutu_boyut + 0.65*cm, "↗")

    # YATIRIM yazısı
    c.setFillColor(C_MAVI)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x + kutu_boyut + 0.3*cm, y - 0.1*cm, "YATIRIM")

    # DEFTERİM yazısı
    c.setFillColor(colors.HexColor("#555555"))
    c.setFont("Helvetica", 7)
    c.drawString(x + kutu_boyut + 0.3*cm, y - 0.55*cm, "DEFTERİM")

# ============================================================
# PDF OLUŞTUR (Canvas tabanlı - tam kontrol)
# ============================================================

def pdf_olustur(sonuclar, ozet):
    buffer = BytesIO()
    w, h = A4  # 595 x 842 pt

    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle("Portfoy Ekstre")

    margin_x = 2*cm
    margin_y = 2*cm
    ic_genislik = w - 2 * margin_x

    y = h - margin_y  # Başlangıç Y

    # ---- LOGO (Sol üst) ----
    logo_ciz(c, margin_x, y - 0.2*cm)

    # ---- PORTFÖY EKSTRE (Sağ üst - büyük) ----
    c.setFillColor(C_MAVI)
    c.setFont("Helvetica-Bold", 22)
    baslik = "PORTFÖY EKSTRE"
    baslik_genislik = c.stringWidth(baslik, "Helvetica-Bold", 22)
    c.drawString(w - margin_x - baslik_genislik, y - 0.5*cm, baslik)

    y -= 1.8*cm

    # ---- ÇİFT YATAY ÇİZGİ ----
    c.setStrokeColor(C_MAVI)
    c.setLineWidth(2.5)
    c.line(margin_x, y, w/2 - 0.5*cm, y)
    c.line(w/2 + 0.5*cm, y, w - margin_x, y)
    y -= 0.25*cm
    c.setLineWidth(1)
    c.line(margin_x, y, w/2 - 0.5*cm, y)
    c.line(w/2 + 0.5*cm, y, w - margin_x, y)

    y -= 1.0*cm

    # ---- EKSTRE NO ----
    now = simdi()
    ekstre_no = now.strftime("%Y%m%d")
    c.setFillColor(C_SIYAH)
    c.setFont("Helvetica-Bold", 10)
    ekstre_txt = f"EKSTRE NO: {ekstre_no}"
    ekstre_w = c.stringWidth(ekstre_txt, "Helvetica-Bold", 10)
    c.drawString(w - margin_x - ekstre_w, y, ekstre_txt)

    # Portföy başlangıç tarihi (sol)
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(margin_x, y, f"Portföy Başlangıcı: {BASLANGIC_TARIHI.strftime('%d.%m.%Y')}")

    y -= 0.4*cm
    c.setFont("Helvetica", 8)
    tarih_txt = f"Veri Tarihi: {now.strftime('%d.%m.%Y %H:%M')}"
    tarih_w = c.stringWidth(tarih_txt, "Helvetica", 8)
    c.drawString(w - margin_x - tarih_w, y, tarih_txt)

    y -= 1.0*cm

    # ---- ANA TABLO ----
    # Sütun genişlikleri (toplam = ic_genislik)
    col_w = [
        ic_genislik * 0.14,  # HİSSE
        ic_genislik * 0.17,  # MALİYET
        ic_genislik * 0.10,  # ADET
        ic_genislik * 0.19,  # TUTAR
        ic_genislik * 0.22,  # KAR/ZARAR
        ic_genislik * 0.18,  # K/Z%
    ]

    headers = ["HİSSE", "MALİYET", "ADET", "TUTAR", "KAR / ZARAR", "K / Z %"]
    data = [headers]

    for r in sonuclar:
        data.append([
            r['hisse'],
            para_fmt(r['maliyet']),
            str(r['adet']),
            para_fmt(r['guncel_deger']),
            para_fmt(r['kz_tl']),
            yuzde_fmt(r['kz_yuzde']),
        ])

    satir_y = y
    satir_h = 1.1*cm
    baslik_h = 1.3*cm

    # Başlık satırı
    x_pos = margin_x
    c.setFillColor(C_MAVI)
    c.rect(margin_x, satir_y - baslik_h, ic_genislik, baslik_h, fill=1, stroke=0)

    c.setFillColor(C_BEYAZ)
    c.setFont("Helvetica-Bold", 9)
    for i, (header, cw) in enumerate(zip(headers, col_w)):
        hx = x_pos + cw/2
        c.drawCentredString(hx, satir_y - baslik_h/2 - 3, header)
        x_pos += cw

    satir_y -= baslik_h

    # Veri satırları
    for idx, r in enumerate(sonuclar):
        # Zebra
        if idx % 2 == 0:
            c.setFillColor(C_BEYAZ)
        else:
            c.setFillColor(C_GRI_ACIK)
        c.rect(margin_x, satir_y - satir_h, ic_genislik, satir_h, fill=1, stroke=0)

        # Alt çizgi
        c.setStrokeColor(C_GRI_ORTA)
        c.setLineWidth(0.5)
        c.line(margin_x, satir_y - satir_h, w - margin_x, satir_y - satir_h)

        x_pos = margin_x
        satirlar = [
            r['hisse'],
            para_fmt(r['maliyet']),
            str(r['adet']),
            para_fmt(r['guncel_deger']),
            para_fmt(r['kz_tl']),
            yuzde_fmt(r['kz_yuzde']),
        ]

        for i, (metin, cw) in enumerate(zip(satirlar, col_w)):
            # K/Z rengi
            if i == 4 or i == 5:
                c.setFillColor(C_YESIL if r['kz_tl'] >= 0 else C_KIRMIZI)
                c.setFont("Helvetica-Bold", 8.5)
            elif i == 0:
                c.setFillColor(C_SIYAH)
                c.setFont("Helvetica-Bold", 8.5)
            else:
                c.setFillColor(C_SIYAH)
                c.setFont("Helvetica", 8.5)

            mx = x_pos + cw/2
            c.drawCentredString(mx, satir_y - satir_h/2 - 3, metin)
            x_pos += cw

        satir_y -= satir_h

    # ---- ÖZET TABLO (Sağ alt) ----
    ozet_y = satir_y - 0.6*cm
    ozet_x = w - margin_x - 8*cm
    ozet_col1 = 5.5*cm
    ozet_col2 = 2.5*cm
    ozet_satir_h = 0.85*cm

    ozet_satirlar = [
        ("GÜNLÜK KAR / ZARAR ORTALAMA", para_fmt(ozet['gunluk_kz']), ozet['gunluk_kz'] >= 0),
        ("AYLIK KAR / ZARAR",           para_fmt(ozet['aylik_kz']),  ozet['aylik_kz'] >= 0),
        ("TOPLAM",                       para_fmt(ozet['toplam_deger']), None),
    ]

    for i, (etiket, deger, pozitif) in enumerate(ozet_satirlar):
        son_satir = (i == len(ozet_satirlar) - 1)

        # Arka plan
        if son_satir:
            c.setFillColor(C_MAVI)
        else:
            c.setFillColor(C_GRI_ACIK)
        c.rect(ozet_x, ozet_y - ozet_satir_h, ozet_col1 + ozet_col2, ozet_satir_h, fill=1, stroke=0)

        # Çizgi
        c.setStrokeColor(C_GRI_ORTA)
        c.setLineWidth(0.5)
        c.rect(ozet_x, ozet_y - ozet_satir_h, ozet_col1 + ozet_col2, ozet_satir_h, fill=0, stroke=1)

        # Etiket
        if son_satir:
            c.setFillColor(C_BEYAZ)
            c.setFont("Helvetica-Bold", 9)
        else:
            c.setFillColor(C_SIYAH)
            c.setFont("Helvetica", 8.5)
        c.drawString(ozet_x + 0.3*cm, ozet_y - ozet_satir_h/2 - 3, etiket)

        # Değer
        if son_satir:
            c.setFillColor(C_BEYAZ)
            c.setFont("Helvetica-Bold", 9)
        elif pozitif is True:
            c.setFillColor(C_YESIL)
            c.setFont("Helvetica-Bold", 8.5)
        elif pozitif is False:
            c.setFillColor(C_KIRMIZI)
            c.setFont("Helvetica-Bold", 8.5)
        else:
            c.setFillColor(C_SIYAH)
            c.setFont("Helvetica-Bold", 8.5)

        deger_w = c.stringWidth(deger, "Helvetica-Bold", 8.5 if not son_satir else 9)
        c.drawString(ozet_x + ozet_col1 + ozet_col2 - deger_w - 0.3*cm,
                     ozet_y - ozet_satir_h/2 - 3, deger)

        ozet_y -= ozet_satir_h

    # ---- ALT NOT ----
    c.setFillColor(colors.HexColor("#999999"))
    c.setFont("Helvetica-Oblique", 6.5)
    c.drawString(margin_x, margin_y,
                 "* Fiyatlar Yahoo Finance kapanış verilerine göre hesaplanmaktadır. "
                 "Günlük K/Z bir önceki kapanışa göre hesaplanmaktadır.")

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
        data={"chat_id": CHAT_ID, "caption": f"📊 Portföy Ekstre - {dosya_adi}"},
        files={"document": (dosya_adi, pdf_buffer, "application/pdf")}
    )
    print(f"Ekstre PDF: {r.status_code} {simdi().strftime('%H:%M')}")

def telegram_metin_gonder(mesaj):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "Markdown"})
    print(f"Ekstre Metin: {r.status_code} {simdi().strftime('%H:%M')}")

def ozet_mesaj(sonuclar, ozet):
    now = simdi()
    mesaj = f"📊 *PORTFÖY EKSTRE - {now.strftime('%d.%m.%Y')}*\n\n"
    mesaj += "`Hisse  | Kapanis  | K/Z TL      | K/Z%`\n"
    mesaj += "`" + "-"*42 + "`\n"
    for r in sonuclar:
        h   = r['hisse'].ljust(6)
        kap = f"{r['kapanis']:.2f}".ljust(8)
        kzt = f"{r['kz_tl']:+.0f}TL".ljust(11)
        kzp = f"{r['kz_yuzde']:+.1f}%"
        mesaj += f"`{h} | {kap} | {kzt} | {kzp}`\n"
    mesaj += f"\n*Gunluk K/Z:* {para_fmt(ozet['gunluk_kz'])}"
    mesaj += f"\n*Aylik K/Z:* {para_fmt(ozet['aylik_kz'])}"
    mesaj += f"\n*Toplam Deger:* {para_fmt(ozet['toplam_deger'])}"
    mesaj += f"\n*Toplam K/Z:* {yuzde_fmt(ozet['toplam_kz_yuzde'])}"
    return mesaj

# ============================================================
# ANA FONKSİYON
# ============================================================

def ekstre_gonder():
    print(f"Ekstre hazirlaniyor... {simdi().strftime('%H:%M')}")
    sonuclar, ozet = hesapla()
    telegram_metin_gonder(ozet_mesaj(sonuclar, ozet))
    now = simdi()
    dosya_adi = f"PORTFOY_EKSTRE_{now.strftime('%d%m%Y')}.pdf"
    pdf_buf = pdf_olustur(sonuclar, ozet)
    telegram_pdf_gonder(pdf_buf, dosya_adi)
    print(f"Ekstre tamamlandi: {simdi().strftime('%H:%M')}")

# ============================================================
# ZAMANLAMA — TR 18:30 (UTC 15:30)
# ============================================================

schedule.every().day.at("15:30").do(ekstre_gonder)

print("Portfoy botu baslatildi. Her gun 18:30 TR saatinde ekstre gonderilecek.")
ekstre_gonder()

while True:
    schedule.run_pending()
    time.sleep(30)
