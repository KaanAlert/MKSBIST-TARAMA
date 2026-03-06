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
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

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
    """1.234,56 TL formatı"""
    return f"{tutar:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")

def yuzde_fmt(yuzde):
    """% formatı"""
    return f"%{yuzde:+.2f}".replace(".", ",")

# ============================================================
# VERİ ÇEK
# ============================================================

def kapanis_fiyati_al(hisse):
    """Güncel kapanış fiyatını çek"""
    try:
        df = yf.download(yahoo_sembol(hisse), period="5d", interval="1d",
                        progress=False, auto_adjust=True)
        if df is None or len(df) == 0:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return float(df['Close'].iloc[-1])
    except:
        return None

def onceki_kapanis_al(hisse):
    """Bir önceki günün kapanış fiyatını çek"""
    try:
        df = yf.download(yahoo_sembol(hisse), period="10d", interval="1d",
                        progress=False, auto_adjust=True)
        if df is None or len(df) < 2:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return float(df['Close'].iloc[-2])
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

        kapanis  = kapanis_fiyati_al(hisse)
        onceki   = onceki_kapanis_al(hisse)

        if kapanis is None:
            kapanis = maliyet
        if onceki is None:
            onceki = maliyet

        maliyet_toplam = adet * maliyet
        guncel_deger   = adet * kapanis
        kz_tl          = guncel_deger - maliyet_toplam
        kz_yuzde       = ((kapanis - maliyet) / maliyet) * 100

        # Günlük K/Z (önceki kapanışa göre)
        gunluk_kz = adet * (kapanis - onceki)

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

    # Aylık K/Z = toplam deger - toplam maliyet (ayın başından bugüne)
    aylik_kz  = toplam_deger - toplam_maliyet
    toplam_kz_yuzde = ((toplam_deger - toplam_maliyet) / toplam_maliyet) * 100

    return sonuclar, {
        "toplam_maliyet":   toplam_maliyet,
        "toplam_deger":     toplam_deger,
        "gunluk_kz":        gunluk_kz_toplam,
        "aylik_kz":         aylik_kz,
        "toplam_kz_yuzde":  toplam_kz_yuzde,
    }

# ============================================================
# RENK PALETİ
# ============================================================

C_MAVI       = colors.HexColor("#1A1AFF")   # PDF'deki mavi
C_MAVI_KOYU  = colors.HexColor("#0000CC")
C_BEYAZ      = colors.white
C_GRI        = colors.HexColor("#F5F5F5")
C_YESIL      = colors.HexColor("#155724")
C_YESIL_BG   = colors.HexColor("#D4EDDA")
C_KIRMIZI    = colors.HexColor("#721C24")
C_KIRMIZI_BG = colors.HexColor("#F8D7DA")
C_SIYAH      = colors.HexColor("#1A1A1A")
C_CIZGI      = colors.HexColor("#CCCCCC")

# ============================================================
# PDF OLUŞTUR
# ============================================================

def pdf_olustur(sonuclar, ozet):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm,   bottomMargin=2*cm,
    )

    story = []

    # ---- STİLLER ----
    baslik_stil = ParagraphStyle("BS", fontSize=22, textColor=C_MAVI,
                                 fontName="Helvetica-Bold", alignment=TA_RIGHT, spaceAfter=4)
    ekstre_stil = ParagraphStyle("ES", fontSize=10, textColor=C_SIYAH,
                                 fontName="Helvetica-Bold", alignment=TA_RIGHT, spaceAfter=2)
    tarih_stil  = ParagraphStyle("TS", fontSize=8, textColor=colors.HexColor("#666666"),
                                 fontName="Helvetica", alignment=TA_RIGHT)
    normal_stil = ParagraphStyle("NS", fontSize=9, textColor=C_SIYAH, fontName="Helvetica")
    ozet_stil   = ParagraphStyle("OS", fontSize=9, textColor=C_SIYAH,
                                 fontName="Helvetica-Bold", alignment=TA_RIGHT)

    # ---- ÜSTE: LOGO ALANI + BAŞLIK ----
    now = simdi()
    ekstre_no = now.strftime("%Y%m%d")

    logo_data = [[
        Paragraph("<b>YATIRIM</b><br/>DEFTERİM", ParagraphStyle(
            "LOGO", fontSize=14, textColor=C_MAVI, fontName="Helvetica-Bold")),
        Paragraph("PORTFÖY EKSTRE", baslik_stil)
    ]]
    logo_tablo = Table(logo_data, colWidths=[8*cm, 9*cm])
    logo_tablo.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN',  (0,0), (0,0),   'LEFT'),
        ('ALIGN',  (1,0), (1,0),   'RIGHT'),
    ]))
    story.append(logo_tablo)
    story.append(HRFlowable(width="100%", thickness=2, color=C_MAVI, spaceAfter=6))
    story.append(HRFlowable(width="100%", thickness=1, color=C_MAVI, spaceAfter=10))

    # Ekstre No + Tarih
    info_data = [[
        Paragraph("", normal_stil),
        Paragraph(f"<b>EKSTRE NO: {ekstre_no}</b>", ekstre_stil)
    ]]
    info_tablo = Table(info_data, colWidths=[8*cm, 9*cm])
    info_tablo.setStyle(TableStyle([('ALIGN', (1,0), (1,0), 'RIGHT')]))
    story.append(info_tablo)

    tarih_data = [[
        Paragraph(f"Portföy Başlangıç: {BASLANGIC_TARIHI.strftime('%d.%m.%Y')}", normal_stil),
        Paragraph(f"Veri Tarihi: {now.strftime('%d.%m.%Y %H:%M')}", tarih_stil)
    ]]
    tarih_tablo = Table(tarih_data, colWidths=[8*cm, 9*cm])
    story.append(tarih_tablo)
    story.append(Spacer(1, 0.6*cm))

    # ---- ANA TABLO ----
    headers = ["HİSSE", "MALİYET", "ADET", "KAPANIS", "TUTAR", "KAR / ZARAR", "K/Z %"]
    data = [headers]

    for r in sonuclar:
        kz_str  = para_fmt(r['kz_tl'])
        yuz_str = yuzde_fmt(r['kz_yuzde'])
        data.append([
            r['hisse'],
            para_fmt(r['maliyet']),
            str(r['adet']),
            para_fmt(r['kapanis']),
            para_fmt(r['guncel_deger']),
            kz_str,
            yuz_str,
        ])

    col_w = [2.5*cm, 2.8*cm, 1.8*cm, 2.8*cm, 3.0*cm, 2.8*cm, 2.0*cm]
    tablo = Table(data, colWidths=col_w, repeatRows=1)

    stil = [
        # Başlık satırı
        ('BACKGROUND',   (0,0), (-1,0), C_MAVI),
        ('TEXTCOLOR',    (0,0), (-1,0), C_BEYAZ),
        ('FONTNAME',     (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',     (0,0), (-1,0), 9),
        ('ALIGN',        (0,0), (-1,0), 'CENTER'),
        ('TOPPADDING',   (0,0), (-1,0), 8),
        ('BOTTOMPADDING',(0,0), (-1,0), 8),
        # Veri satırları
        ('FONTSIZE',     (0,1), (-1,-1), 8.5),
        ('ALIGN',        (0,1), (-1,-1), 'CENTER'),
        ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',   (0,1), (-1,-1), 7),
        ('BOTTOMPADDING',(0,1), (-1,-1), 7),
        ('GRID',         (0,0), (-1,-1), 0.5, C_CIZGI),
        # Hisse sütunu sola
        ('ALIGN',        (0,1), (0,-1), 'LEFT'),
        ('FONTNAME',     (0,1), (0,-1), 'Helvetica-Bold'),
        # Zebra
        ('BACKGROUND',   (0,1), (-1,1), C_BEYAZ),
        ('BACKGROUND',   (0,2), (-1,2), C_GRI),
        ('BACKGROUND',   (0,3), (-1,3), C_BEYAZ),
        ('BACKGROUND',   (0,4), (-1,4), C_GRI),
        ('BACKGROUND',   (0,5), (-1,5), C_BEYAZ),
    ]

    # K/Z renklendirme
    for i, r in enumerate(sonuclar, start=1):
        if r['kz_tl'] >= 0:
            stil += [
                ('TEXTCOLOR', (5,i), (5,i), C_YESIL),
                ('TEXTCOLOR', (6,i), (6,i), C_YESIL),
                ('FONTNAME',  (5,i), (6,i), 'Helvetica-Bold'),
            ]
        else:
            stil += [
                ('TEXTCOLOR', (5,i), (5,i), C_KIRMIZI),
                ('TEXTCOLOR', (6,i), (6,i), C_KIRMIZI),
                ('FONTNAME',  (5,i), (6,i), 'Helvetica-Bold'),
            ]

    tablo.setStyle(TableStyle(stil))
    story.append(tablo)
    story.append(Spacer(1, 0.5*cm))

    # ---- ÖZET TABLO ----
    gunluk_kz = ozet['gunluk_kz']
    aylik_kz  = ozet['aylik_kz']
    toplam    = ozet['toplam_deger']
    kz_yuzde  = ozet['toplam_kz_yuzde']

    def ozet_renk(deger):
        return C_YESIL if deger >= 0 else C_KIRMIZI

    ozet_data = [
        ["GÜNLÜK KAR / ZARAR", para_fmt(gunluk_kz)],
        ["AYLIK KAR / ZARAR",  para_fmt(aylik_kz)],
        ["TOPLAM DEĞER",       para_fmt(toplam)],
        ["TOPLAM K/Z %",       yuzde_fmt(kz_yuzde)],
    ]

    ozet_tablo = Table(ozet_data, colWidths=[5*cm, 4*cm], hAlign='RIGHT')
    ozet_stil_list = [
        ('FONTSIZE',     (0,0), (-1,-1), 8.5),
        ('ALIGN',        (0,0), (0,-1),  'LEFT'),
        ('ALIGN',        (1,0), (1,-1),  'RIGHT'),
        ('TOPPADDING',   (0,0), (-1,-1), 5),
        ('BOTTOMPADDING',(0,0), (-1,-1), 5),
        ('GRID',         (0,0), (-1,-1), 0.5, C_CIZGI),
        # Son satır (TOPLAM) mavi arka plan
        ('BACKGROUND',   (0,2), (-1,2), C_MAVI),
        ('TEXTCOLOR',    (0,2), (-1,2), C_BEYAZ),
        ('FONTNAME',     (0,2), (-1,2), 'Helvetica-Bold'),
        ('FONTSIZE',     (0,2), (-1,2), 9),
    ]

    # Günlük ve Aylık K/Z rengi
    ozet_stil_list += [
        ('TEXTCOLOR', (1,0), (1,0), ozet_renk(gunluk_kz)),
        ('FONTNAME',  (1,0), (1,0), 'Helvetica-Bold'),
        ('TEXTCOLOR', (1,1), (1,1), ozet_renk(aylik_kz)),
        ('FONTNAME',  (1,1), (1,1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (1,3), (1,3), ozet_renk(kz_yuzde)),
        ('FONTNAME',  (0,3), (1,3), 'Helvetica-Bold'),
    ]

    ozet_tablo.setStyle(TableStyle(ozet_stil_list))
    story.append(ozet_tablo)

    # Alt not
    story.append(Spacer(1, 0.8*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_CIZGI))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "* Fiyatlar Yahoo Finance kapanış verilerine göre hesaplanmaktadır. "
        "Günlük K/Z bir önceki kapanışa göre hesaplanmaktadır.",
        ParagraphStyle("NOT", fontSize=7, textColor=colors.HexColor("#999999"),
                      fontName="Helvetica-Oblique")
    ))

    doc.build(story)
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

def ozet_mesaj_olustur(sonuclar, ozet):
    now = simdi()
    mesaj = f"📊 *PORTFÖY EKSTRE - {now.strftime('%d.%m.%Y')}*\n\n"
    mesaj += "`Hisse  | Kapanis | K/Z TL     | K/Z %`\n"
    mesaj += "`" + "-"*40 + "`\n"
    for r in sonuclar:
        h    = r['hisse'].ljust(6)
        kap  = f"{r['kapanis']:.2f}".ljust(7)
        kztl = f"{r['kz_tl']:+.0f}TL".ljust(10)
        kzp  = f"{r['kz_yuzde']:+.1f}%".ljust(6)
        mesaj += f"`{h} | {kap} | {kztl} | {kzp}`\n"

    mesaj += f"\n*Günlük K/Z:* {para_fmt(ozet['gunluk_kz'])}"
    mesaj += f"\n*Aylık K/Z:* {para_fmt(ozet['aylik_kz'])}"
    mesaj += f"\n*Toplam Değer:* {para_fmt(ozet['toplam_deger'])}"
    mesaj += f"\n*Toplam K/Z %:* {yuzde_fmt(ozet['toplam_kz_yuzde'])}"
    return mesaj

# ============================================================
# ANA FONKSİYON
# ============================================================

def ekstre_gonder():
    print(f"Ekstre hazirlaniyor... {simdi().strftime('%H:%M')}")
    sonuclar, ozet = hesapla()

    # Metin özet
    telegram_metin_gonder(ozet_mesaj_olustur(sonuclar, ozet))

    # PDF
    now       = simdi()
    dosya_adi = f"PORTFOY_EKSTRE_{now.strftime('%d%m%Y')}.pdf"
    pdf_buf   = pdf_olustur(sonuclar, ozet)
    telegram_pdf_gonder(pdf_buf, dosya_adi)
    print(f"Ekstre tamamlandi: {simdi().strftime('%H:%M')}")

# ============================================================
# ZAMANLAMA — TR Saati 18:30 (UTC 15:30)
# ============================================================

schedule.every().day.at("15:30").do(ekstre_gonder)  # UTC = TR 18:30

print("Portfoy botu baslatildi. Her gun 18:30 TR saatinde ekstre gonderilecek.")
ekstre_gonder()  # Baslarken bir kez calistir

while True:
    schedule.run_pending()
    time.sleep(30)
