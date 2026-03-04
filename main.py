import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
from io import BytesIO
import schedule

# reportlab imports
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

TOKEN   = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# ============================================================
# BIST 30 HİSSELERİ
# ============================================================
BIST30 = [
    "AKBNK", "ARCLK", "ASELS", "BIMAS", "DOHOL",
    "EKGYO", "EREGL", "FROTO", "GARAN", "HALKB",
    "ISCTR", "KCHOL", "TRMET", "TRALT", "KRDMD",
    "MGROS", "ODAS",  "PETKM", "PGSUS", "SAHOL",
    "SASA",  "SISE",  "TAVHL", "TCELL", "THYAO",
    "TKFEN", "TOASO", "TTKOM", "TUPRS", "VAKBN"
]

def yahoo_sembol(hisse):
    return f"{hisse}.IS"

# ============================================================
# İNDİKATÖR HESAPLAMALARI (TradingView ile birebir)
# ============================================================

def hesapla_wavetrend(df, n1=10, n2=21):
    ap  = (df['High'] + df['Low'] + df['Close']) / 3
    esa = ap.ewm(span=n1, adjust=False).mean()
    d   = (ap - esa).abs().ewm(span=n1, adjust=False).mean()
    ci  = (ap - esa) / (0.015 * d)
    wt1 = ci.ewm(span=n2, adjust=False).mean()
    wt2 = wt1.rolling(4).mean()
    wt_yesil = wt1.iloc[-1] > wt2.iloc[-1]
    return "AL" if wt_yesil else "SAT", wt_yesil

def hesapla_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df['Close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow, adjust=False).mean()
    macd     = ema_fast - ema_slow
    sig      = macd.ewm(span=signal, adjust=False).mean()
    macd_yesil = macd.iloc[-1] > sig.iloc[-1]
    return "AL" if macd_yesil else "SAT", macd_yesil

def hesapla_smiio(df, length=13, smooth=5, sig_len=3):
    ll      = df['Low'].rolling(length).min()
    hh      = df['High'].rolling(length).max()
    diff    = hh - ll
    rdiff   = df['Close'] - (hh + ll) / 2
    avgrel  = rdiff.ewm(span=smooth, adjust=False).mean().ewm(span=smooth, adjust=False).mean()
    avgdiff = diff.ewm(span=smooth, adjust=False).mean().ewm(span=smooth, adjust=False).mean()
    smi     = np.where(avgdiff != 0, avgrel / (avgdiff / 2) * 100, 0)
    smi_s   = pd.Series(smi, index=df.index)
    sinyal  = smi_s.ewm(span=sig_len, adjust=False).mean()
    smiio_yesil = smi_s.iloc[-1] > sinyal.iloc[-1]
    return "AL" if smiio_yesil else "SAT", smiio_yesil

def pozisyon_belirle(smi_al, wt_al, macd_al):
    al_sayisi  = sum([smi_al, wt_al, macd_al])
    sat_sayisi = 3 - al_sayisi
    if al_sayisi == 3:
        return "GUCLU AL"
    elif al_sayisi == 2:
        return "AL"
    elif sat_sayisi == 3:
        return "GUCLU SAT"
    elif sat_sayisi == 2:
        return "SAT"
    else:
        return "BEKLE"

# ============================================================
# VERİ ÇEK VE ANALİZ ET
# ============================================================

def analiz_et():
    sonuclar = []
    for hisse in BIST30:
        try:
            df = yf.download(yahoo_sembol(hisse), period="6mo", interval="1d",
                             progress=False, auto_adjust=True)
            if df is None or len(df) < 50:
                continue
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

            smi_sinyal, smi_al   = hesapla_smiio(df)
            wt_sinyal,  wt_al    = hesapla_wavetrend(df)
            macd_sinyal, macd_al = hesapla_macd(df)
            poz = pozisyon_belirle(smi_al, wt_al, macd_al)

            sonuclar.append({
                "Hisse":   hisse,
                "SMI":     smi_sinyal,
                "WT":      wt_sinyal,
                "MACD":    macd_sinyal,
                "Pozisyon": poz,
                "smi_al":  smi_al,
                "wt_al":   wt_al,
                "macd_al": macd_al,
            })
        except Exception as e:
            print(f"{hisse} hata: {e}")
    return sonuclar

# ============================================================
# TELEGRAM METİN MESAJI
# ============================================================

def mesaj_olustur(sonuclar):
    tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
    mesaj = f"*BIST 30 SINYAL TABLOSU*\n{tarih}\n\n"
    mesaj += "`Hisse  | SMI | WT  | MACD | Pozisyon    `\n"
    mesaj += "`" + "-"*44 + "`\n"

    for r in sonuclar:
        hisse = r['Hisse'].ljust(6)
        smi   = r['SMI'].ljust(3)
        wt    = r['WT'].ljust(3)
        macd  = r['MACD'].ljust(4)
        poz   = r['Pozisyon'].ljust(11)
        mesaj += f"`{hisse} | {smi} | {wt} | {macd} | {poz}`\n"

    guclu_al  = [r['Hisse'] for r in sonuclar if r['Pozisyon'] == "GUCLU AL"]
    guclu_sat = [r['Hisse'] for r in sonuclar if r['Pozisyon'] == "GUCLU SAT"]

    if guclu_al:
        mesaj += f"\n*GUCLU AL:* {', '.join(guclu_al)}"
    if guclu_sat:
        mesaj += f"\n*GUCLU SAT:* {', '.join(guclu_sat)}"

    return mesaj

# ============================================================
# PDF OLUŞTUR
# ============================================================

YESIL   = colors.HexColor("#0d6e3f")
KIRMIZI = colors.HexColor("#8b0000")
MAVI    = colors.HexColor("#0a3d6b")
KOYU    = colors.HexColor("#001a33")
ALTIN   = colors.HexColor("#4a90d9")
SATIR1  = colors.HexColor("#071526")
SATIR2  = colors.HexColor("#0a1f33")

def sinyal_renk(sinyal):
    return YESIL if sinyal == "AL" else KIRMIZI

def poz_renk(poz):
    if poz in ("GUCLU AL", "AL"):
        return YESIL
    elif poz in ("GUCLU SAT", "SAT"):
        return KIRMIZI
    return MAVI

def poz_emoji(poz):
    return {
        "GUCLU AL":  "GUCLU AL",
        "AL":        "AL",
        "GUCLU SAT": "GUCLU SAT",
        "SAT":       "SAT",
        "BEKLE":     "BEKLE",
    }.get(poz, poz)

def pdf_olustur(sonuclar):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )

    styles = getSampleStyleSheet()
    baslik_style = ParagraphStyle(
        'Baslik', parent=styles['Title'],
        fontSize=16, textColor=ALTIN,
        alignment=TA_CENTER, spaceAfter=4,
    )
    tarih_style = ParagraphStyle(
        'Tarih', parent=styles['Normal'],
        fontSize=10, textColor=colors.white,
        alignment=TA_CENTER, spaceAfter=12,
    )
    ozet_stil = ParagraphStyle(
        'Ozet', parent=styles['Normal'],
        fontSize=10, textColor=colors.white, spaceAfter=6,
    )

    story = []
    tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
    story.append(Paragraph("BIST 30 SINYAL TABLOSU", baslik_style))
    story.append(Paragraph(f"Guncelleme: {tarih}", tarih_style))
    story.append(Spacer(1, 0.3*cm))

    # Tablo verisi
    tablo_data = [["HISSE", "SMI", "WT", "MACD", "POZISYON"]]
    for r in sonuclar:
        tablo_data.append([
            r['Hisse'],
            "AL" if r['SMI']  == "AL" else "SAT",
            "AL" if r['WT']   == "AL" else "SAT",
            "AL" if r['MACD'] == "AL" else "SAT",
            poz_emoji(r['Pozisyon']),
        ])

    tablo = Table(tablo_data, colWidths=[3.2*cm, 3*cm, 3*cm, 3*cm, 4.3*cm])

    stil = [
        # Başlık
        ('BACKGROUND',   (0, 0), (-1, 0),  KOYU),
        ('TEXTCOLOR',    (0, 0), (-1, 0),  ALTIN),
        ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, 0),  10),
        ('ALIGN',        (0, 0), (-1, 0),  'CENTER'),
        ('BOTTOMPADDING',(0, 0), (-1, 0),  8),
        ('TOPPADDING',   (0, 0), (-1, 0),  8),
        # Tüm veri hücreleri
        ('FONTSIZE',     (0, 1), (-1, -1), 9),
        ('ALIGN',        (0, 1), (-1, -1), 'CENTER'),
        ('VALIGN',       (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING',(0, 1), (-1, -1), 6),
        ('TOPPADDING',   (0, 1), (-1, -1), 6),
        ('GRID',         (0, 0), (-1, -1), 0.5, colors.HexColor("#1a3a5c")),
        # Hisse sütunu
        ('BACKGROUND',   (0, 1), (0, -1),  MAVI),
        ('TEXTCOLOR',    (0, 1), (0, -1),  colors.white),
        ('FONTNAME',     (0, 1), (0, -1),  'Helvetica-Bold'),
    ]

    for i, r in enumerate(sonuclar, start=1):
        # Satır arkaplanı (zebra)
        bg = SATIR2 if i % 2 == 0 else SATIR1
        stil.append(('BACKGROUND', (0, i), (0, i), MAVI))
        # SMI
        stil.append(('BACKGROUND', (1, i), (1, i), sinyal_renk(r['SMI'])))
        stil.append(('TEXTCOLOR',  (1, i), (1, i), colors.white))
        # WT
        stil.append(('BACKGROUND', (2, i), (2, i), sinyal_renk(r['WT'])))
        stil.append(('TEXTCOLOR',  (2, i), (2, i), colors.white))
        # MACD
        stil.append(('BACKGROUND', (3, i), (3, i), sinyal_renk(r['MACD'])))
        stil.append(('TEXTCOLOR',  (3, i), (3, i), colors.white))
        # Pozisyon
        stil.append(('BACKGROUND', (4, i), (4, i), poz_renk(r['Pozisyon'])))
        stil.append(('TEXTCOLOR',  (4, i), (4, i), colors.white))
        stil.append(('FONTNAME',   (4, i), (4, i), 'Helvetica-Bold'))

    tablo.setStyle(TableStyle(stil))
    story.append(tablo)

    story.append(Spacer(1, 0.5*cm))
    guclu_al  = [r['Hisse'] for r in sonuclar if r['Pozisyon'] == "GUCLU AL"]
    guclu_sat = [r['Hisse'] for r in sonuclar if r['Pozisyon'] == "GUCLU SAT"]
    if guclu_al:
        story.append(Paragraph(f"GUCLU AL: {', '.join(guclu_al)}", ozet_stil))
    if guclu_sat:
        story.append(Paragraph(f"GUCLU SAT: {', '.join(guclu_sat)}", ozet_stil))

    doc.build(story)
    buffer.seek(0)
    return buffer

# ============================================================
# TELEGRAM GÖNDER
# ============================================================

def telegram_metin_gonder(mesaj):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "Markdown"})
    if r.status_code == 200:
        print(f"Metin gonderildi: {datetime.now().strftime('%H:%M')}")
    else:
        print(f"Metin hatasi: {r.text}")

def telegram_pdf_gonder(pdf_buffer):
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    tarih = datetime.now().strftime("%d%m%Y_%H%M")
    dosya_adi = f"BIST30_{tarih}.pdf"
    r = requests.post(
        url,
        data={"chat_id": CHAT_ID, "caption": "BIST 30 Sinyal Tablosu (PDF)"},
        files={"document": (dosya_adi, pdf_buffer, "application/pdf")}
    )
    if r.status_code == 200:
        print(f"PDF gonderildi: {datetime.now().strftime('%H:%M')}")
    else:
        print(f"PDF hatasi: {r.text}")

# ============================================================
# ANA FONKSİYON — SAATLİK
# ============================================================

def saatlik_gonder():
    print(f"Analiz basliyor... {datetime.now().strftime('%H:%M')}")
    sonuclar = analiz_et()
    if not sonuclar:
        print("Veri alinamadi.")
        return
    telegram_metin_gonder(mesaj_olustur(sonuclar))
    telegram_pdf_gonder(pdf_olustur(sonuclar))

# Her saat başı çalıştır
schedule.every().hour.at(":00").do(saatlik_gonder)

print("Bot baslatildi. Her saat basi sinyal gonderilecek.")
print("Ilk analiz basliyor...")
saatlik_gonder()

while True:
    schedule.run_pending()
    time.sleep(30)
