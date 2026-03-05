import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
from io import BytesIO
import schedule
import locale

# reportlab imports
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

TOKEN   = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

BIST30 = [
    "AKBNK", "ARCLK", "ASELS", "BIMAS", "DOHOL",
    "EKGYO", "EREGL", "FROTO", "GARAN", "HALKB",
    "ISCTR", "KCHOL", "TRMET", "TRALT", "KRDMD",
    "MGROS", "ODAS",  "PETKM", "PGSUS", "SAHOL",
    "SASA",  "SISE",  "TAVHL", "TCELL", "THYAO",
    "TKFEN", "TOASO", "TTKOM", "TUPRS", "VAKBN"
]

def yahoo_sembol(h): return f"{h}.IS"

# ============================================================
# GUN ADI (Turkce)
# ============================================================
GUNLER = {
    "Monday": "PAZARTESI", "Tuesday": "SALI", "Wednesday": "CARSAMBA",
    "Thursday": "PERSEMBE", "Friday": "CUMA", "Saturday": "CUMARTESI",
    "Sunday": "PAZAR"
}

def gun_adi():
    return GUNLER.get(datetime.now().strftime("%A"), datetime.now().strftime("%A"))

# ============================================================
# INDIKTOR HESAPLAMALARI
# ============================================================

def hesapla_wavetrend(df, n1=10, n2=21):
    ap  = (df['High'] + df['Low'] + df['Close']) / 3
    esa = ap.ewm(span=n1, adjust=False).mean()
    d   = (ap - esa).abs().ewm(span=n1, adjust=False).mean()
    ci  = (ap - esa) / (0.015 * d)
    wt1 = ci.ewm(span=n2, adjust=False).mean()
    wt2 = wt1.rolling(4).mean()
    return wt1.iloc[-1] > wt2.iloc[-1]

def hesapla_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df['Close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig  = macd.ewm(span=signal, adjust=False).mean()
    return macd.iloc[-1] > sig.iloc[-1]

def hesapla_smiio(df, length=13, smooth=5, sig_len=3):
    ll = df['Low'].rolling(length).min()
    hh = df['High'].rolling(length).max()
    diff = hh - ll
    rdiff = df['Close'] - (hh + ll) / 2
    avgrel  = rdiff.ewm(span=smooth, adjust=False).mean().ewm(span=smooth, adjust=False).mean()
    avgdiff = diff.ewm(span=smooth, adjust=False).mean().ewm(span=smooth, adjust=False).mean()
    smi = pd.Series(np.where(avgdiff != 0, avgrel / (avgdiff / 2) * 100, 0), index=df.index)
    sinyal = smi.ewm(span=sig_len, adjust=False).mean()
    return smi.iloc[-1] > sinyal.iloc[-1]

def hesapla_mfi(df, period=14):
    """
    MFI hesapla. Son 2 MFI degerine gore trend: pozitif/negatif.
    MFI degeri 0-100 arasi doner.
    """
    # Volume kontrolu
    if df['Volume'].iloc[-14:].sum() == 0:
        return None, "N/A"

    tp = (df['High'] + df['Low'] + df['Close']) / 3
    mf = tp * df['Volume']

    pos_mf = pd.Series(np.where(tp > tp.shift(1), mf, 0), index=df.index)
    neg_mf = pd.Series(np.where(tp < tp.shift(1), mf, 0), index=df.index)

    pos_sum = pos_mf.rolling(period).sum()
    neg_sum = neg_mf.rolling(period).sum()

    mfi = 100 - (100 / (1 + pos_sum / neg_sum.replace(0, np.nan)))

    mfi_son    = round(mfi.iloc[-1], 1)
    mfi_onceki = round(mfi.iloc[-2], 1)

    trend = "POZITIF" if mfi_son > mfi_onceki else "NEGATIF"

    return mfi_son, trend

def pozisyon(smi_al, wt_al, macd_al):
    al  = sum([smi_al, wt_al, macd_al])
    sat = 3 - al
    if al == 3:   return "GUCLU AL"
    if al == 2:   return "AL"
    if sat == 3:  return "GUCLU SAT"
    if sat == 2:  return "SAT"
    return "BEKLE"

# ============================================================
# ANALIZ
# ============================================================

def analiz_et():
    sonuclar = []
    for hisse in BIST30:
        try:
            df = yf.download(yahoo_sembol(hisse), period="60d", interval="4h",
                             progress=False, auto_adjust=True)
            if df is None or len(df) < 50:
                continue
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

            smi_al  = hesapla_smiio(df)
            wt_al   = hesapla_wavetrend(df)
            macd_al = hesapla_macd(df)
            poz     = pozisyon(smi_al, wt_al, macd_al)
            mfi_val, mfi_trend = hesapla_mfi(df)

            sonuclar.append({
                "Hisse":     hisse,
                "SMI":       "AL" if smi_al  else "SAT",
                "WT":        "AL" if wt_al   else "SAT",
                "MACD":      "AL" if macd_al else "SAT",
                "Pozisyon":  poz,
                "MFI_Trend": mfi_trend,
                "MFI_Val":   mfi_val,
                "smi_al":    smi_al,
                "wt_al":     wt_al,
                "macd_al":   macd_al,
            })
        except Exception as e:
            print(f"{hisse} hata: {e}")
    return sonuclar

# ============================================================
# RENK PALETI - Acik/Profesyonel Tema
# ============================================================

# Baslik renkleri
C_BASLIK_BG   = colors.HexColor("#1B2A4A")   # Koyu lacivert baslik
C_BASLIK_TEXT = colors.HexColor("#FFFFFF")

# Sutun basliklari
C_SUTUN_BG    = colors.HexColor("#2E4A7A")
C_SUTUN_TEXT  = colors.HexColor("#E8F0FE")

# Hisse sutunu
C_HISSE_BG    = colors.HexColor("#EEF2FF")
C_HISSE_TEXT  = colors.HexColor("#1B2A4A")

# Satir renkleri (zebra)
C_SATIR1      = colors.HexColor("#FFFFFF")
C_SATIR2      = colors.HexColor("#F5F7FF")

# AL renkleri - acik yesil tonlar
C_AL_BG       = colors.HexColor("#D4EDDA")
C_AL_TEXT     = colors.HexColor("#155724")
C_GUCLU_AL_BG = colors.HexColor("#28A745")
C_GUCLU_AL_TX = colors.HexColor("#FFFFFF")

# SAT renkleri - acik kirmizi tonlar
C_SAT_BG      = colors.HexColor("#F8D7DA")
C_SAT_TEXT    = colors.HexColor("#721C24")
C_GUCLU_SAT_BG= colors.HexColor("#DC3545")
C_GUCLU_SAT_TX= colors.HexColor("#FFFFFF")

# BEKLE
C_BEKLE_BG    = colors.HexColor("#FFF3CD")
C_BEKLE_TEXT  = colors.HexColor("#856404")

# MFI
C_POZ_BG      = colors.HexColor("#C8F7C5")
C_POZ_TEXT    = colors.HexColor("#1A6B19")
C_NEG_BG      = colors.HexColor("#FADBD8")
C_NEG_TEXT    = colors.HexColor("#922B21")

# Grid
C_GRID        = colors.HexColor("#C5D0E8")

def sinyal_renk(sinyal):
    return (C_AL_BG, C_AL_TEXT) if sinyal == "AL" else (C_SAT_BG, C_SAT_TEXT)

def poz_renk(poz):
    if poz == "GUCLU AL":  return C_GUCLU_AL_BG,  C_GUCLU_AL_TX
    if poz == "AL":        return C_AL_BG,         C_AL_TEXT
    if poz == "GUCLU SAT": return C_GUCLU_SAT_BG,  C_GUCLU_SAT_TX
    if poz == "SAT":       return C_SAT_BG,        C_SAT_TEXT
    return C_BEKLE_BG, C_BEKLE_TEXT

def mfi_trend_renk(trend):
    return (C_POZ_BG, C_POZ_TEXT) if trend == "POZITIF" else (C_NEG_BG, C_NEG_TEXT)

def mfi_val_renk(val):
    if val >= 80: return colors.HexColor("#DC3545"), colors.white   # Asiri alim
    if val >= 60: return C_AL_BG, C_AL_TEXT                         # Guclu
    if val <= 20: return colors.HexColor("#6F42C1"), colors.white   # Asiri satim
    if val <= 40: return C_SAT_BG, C_SAT_TEXT                       # Zayif
    return C_BEKLE_BG, C_BEKLE_TEXT                                 # Notr

# ============================================================
# PDF OLUSTUR
# ============================================================

def baslik_olustur():
    now  = datetime.now()
    tarih = now.strftime("%d.%m.%Y")
    saat  = now.strftime("%H:%M")
    gun   = gun_adi()
    return f"MKS TARAMA   {tarih} {gun} {saat}"

def pdf_dosya_adi():
    now = datetime.now()
    return f"MKS_TARAMA_{now.strftime('%d%m%Y')}_{now.strftime('%H%M')}.pdf"

def pdf_olustur(sonuclar):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1.2*cm,
        leftMargin=1.2*cm,
        topMargin=1.2*cm,
        bottomMargin=1.2*cm,
    )

    styles = getSampleStyleSheet()

    baslik_style = ParagraphStyle(
        'Baslik',
        fontSize=14,
        textColor=C_BASLIK_TEXT,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        spaceAfter=2,
    )
    alt_baslik_style = ParagraphStyle(
        'AltBaslik',
        fontSize=8,
        textColor=colors.HexColor("#8899BB"),
        alignment=TA_CENTER,
        fontName='Helvetica',
        spaceAfter=8,
    )

    story = []

    # Baslik kutusu
    baslik_data = [[Paragraph(baslik_olustur(), baslik_style)]]
    baslik_tablo = Table(baslik_data, colWidths=[26*cm])
    baslik_tablo.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), C_BASLIK_BG),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('ROUNDEDCORNERS', [4, 4, 4, 4]),
    ]))
    story.append(baslik_tablo)
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph("SMI | WaveTrend | MACD | MFI   -   Gunluk Grafik Analizi", alt_baslik_style))

    # Ana tablo
    headers = ["HISSE", "SMI", "WT", "MACD", "POZISYON", "MFI TREND", "MFI DEGER"]
    tablo_data = [headers]

    for r in sonuclar:
        mfi_str = f"{r['MFI_Val']}"
        tablo_data.append([
            r['Hisse'],
            "AL" if r['SMI']  == "AL" else "SAT",
            "AL" if r['WT']   == "AL" else "SAT",
            "AL" if r['MACD'] == "AL" else "SAT",
            r['Pozisyon'],
            r['MFI_Trend'],
            mfi_str,
        ])

    col_w = [3*cm, 2.8*cm, 2.8*cm, 2.8*cm, 3.8*cm, 3.2*cm, 3.2*cm]
    tablo = Table(tablo_data, colWidths=col_w, repeatRows=1)

    stil = [
        # Sutun basliklari
        ('BACKGROUND',   (0,0), (-1,0),  C_SUTUN_BG),
        ('TEXTCOLOR',    (0,0), (-1,0),  C_SUTUN_TEXT),
        ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0,0), (-1,0),  9),
        ('ALIGN',        (0,0), (-1,0),  'CENTER'),
        ('TOPPADDING',   (0,0), (-1,0),  7),
        ('BOTTOMPADDING',(0,0), (-1,0),  7),
        # Veri satirlari
        ('FONTSIZE',     (0,1), (-1,-1), 8.5),
        ('ALIGN',        (0,1), (-1,-1), 'CENTER'),
        ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING',   (0,1), (-1,-1), 5),
        ('BOTTOMPADDING',(0,1), (-1,-1), 5),
        ('GRID',         (0,0), (-1,-1), 0.4, C_GRID),
        # Hisse sutunu
        ('BACKGROUND',   (0,1), (0,-1),  C_HISSE_BG),
        ('TEXTCOLOR',    (0,1), (0,-1),  C_HISSE_TEXT),
        ('FONTNAME',     (0,1), (0,-1),  'Helvetica-Bold'),
        ('ALIGN',        (0,1), (0,-1),  'LEFT'),
    ]

    # Zebra + dinamik renkler
    for i, r in enumerate(sonuclar, start=1):
        zebra = C_SATIR1 if i % 2 == 0 else C_SATIR2
        # SMI
        bg, tx = sinyal_renk(r['SMI'])
        stil += [('BACKGROUND',(1,i),(1,i),bg), ('TEXTCOLOR',(1,i),(1,i),tx),
                 ('FONTNAME',(1,i),(1,i),'Helvetica-Bold')]
        # WT
        bg, tx = sinyal_renk(r['WT'])
        stil += [('BACKGROUND',(2,i),(2,i),bg), ('TEXTCOLOR',(2,i),(2,i),tx),
                 ('FONTNAME',(2,i),(2,i),'Helvetica-Bold')]
        # MACD
        bg, tx = sinyal_renk(r['MACD'])
        stil += [('BACKGROUND',(3,i),(3,i),bg), ('TEXTCOLOR',(3,i),(3,i),tx),
                 ('FONTNAME',(3,i),(3,i),'Helvetica-Bold')]
        # Pozisyon
        bg, tx = poz_renk(r['Pozisyon'])
        stil += [('BACKGROUND',(4,i),(4,i),bg), ('TEXTCOLOR',(4,i),(4,i),tx),
                 ('FONTNAME',(4,i),(4,i),'Helvetica-Bold')]
        # MFI Trend
        bg, tx = mfi_trend_renk(r['MFI_Trend'])
        stil += [('BACKGROUND',(5,i),(5,i),bg), ('TEXTCOLOR',(5,i),(5,i),tx),
                 ('FONTNAME',(5,i),(5,i),'Helvetica-Bold')]
        # MFI Deger
        bg, tx = mfi_val_renk(r['MFI_Val'])
        stil += [('BACKGROUND',(6,i),(6,i),bg), ('TEXTCOLOR',(6,i),(6,i),tx),
                 ('FONTNAME',(6,i),(6,i),'Helvetica-Bold')]

    tablo.setStyle(TableStyle(stil))
    story.append(tablo)

    # Alt bilgi
    story.append(Spacer(1, 0.4*cm))
    guclu_al  = [r['Hisse'] for r in sonuclar if r['Pozisyon'] == "GUCLU AL"]
    guclu_sat = [r['Hisse'] for r in sonuclar if r['Pozisyon'] == "GUCLU SAT"]

    ozet_stil = ParagraphStyle('Ozet', fontSize=8, textColor=colors.HexColor("#333333"),
                               fontName='Helvetica', spaceAfter=3)
    if guclu_al:
        story.append(Paragraph(f"GUCLU AL: {', '.join(guclu_al)}", ozet_stil))
    if guclu_sat:
        story.append(Paragraph(f"GUCLU SAT: {', '.join(guclu_sat)}", ozet_stil))

    # MFI aciklama
    legend_stil = ParagraphStyle('Legend', fontSize=7, textColor=colors.HexColor("#888888"),
                                 fontName='Helvetica-Oblique')
    story.append(Paragraph(
        "MFI: 80+ Asiri Alim | 60-80 Guclu | 40-60 Notr | 20-40 Zayif | 0-20 Asiri Satim   |   "
        "MFI Trend: POZITIF=Son deger oncekinden yuksek | NEGATIF=Son deger oncekinden dusuk",
        legend_stil
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer

# ============================================================
# TELEGRAM METIN
# ============================================================

def mesaj_olustur(sonuclar):
    now = datetime.now()
    baslik = f"MKS TARAMA {now.strftime('%d.%m.%Y')} {gun_adi()} {now.strftime('%H:%M')}"
    mesaj = f"*{baslik}*\n\n"
    mesaj += "`Hisse  |SMI|WT |MACD|Pozisyon   |MFI|Val`\n"
    mesaj += "`" + "-"*46 + "`\n"
    for r in sonuclar:
        h   = r['Hisse'].ljust(6)
        smi = r['SMI'][:3].ljust(3)
        wt  = r['WT'][:2].ljust(3)
        mac = r['MACD'][:3].ljust(4)
        poz = r['Pozisyon'][:10].ljust(10)
        mft = r['MFI_Trend'].ljust(3)
        mfv = str(r['MFI_Val']).ljust(4)
        mesaj += f"`{h}|{smi}|{wt}|{mac}|{poz}|{mft}|{mfv}`\n"

    guclu_al  = [r['Hisse'] for r in sonuclar if r['Pozisyon'] == "GUCLU AL"]
    guclu_sat = [r['Hisse'] for r in sonuclar if r['Pozisyon'] == "GUCLU SAT"]
    if guclu_al:  mesaj += f"\n*GUCLU AL:* {', '.join(guclu_al)}"
    if guclu_sat: mesaj += f"\n*GUCLU SAT:* {', '.join(guclu_sat)}"
    return mesaj

# ============================================================
# TELEGRAM GONDER
# ============================================================

def telegram_metin_gonder(mesaj):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "Markdown"})
    print(f"Metin: {r.status_code} {datetime.now().strftime('%H:%M')}")

def telegram_pdf_gonder(pdf_buffer, dosya_adi):
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    r = requests.post(
        url,
        data={"chat_id": CHAT_ID, "caption": dosya_adi},
        files={"document": (dosya_adi, pdf_buffer, "application/pdf")}
    )
    print(f"PDF: {r.status_code} {datetime.now().strftime('%H:%M')}")

# ============================================================
# ANA FONKSIYON
# ============================================================

def saatlik_gonder():
    print(f"Analiz basliyor... {datetime.now().strftime('%H:%M')}")
    sonuclar = analiz_et()
    if not sonuclar:
        print("Veri alinamadi.")
        return
    telegram_metin_gonder(mesaj_olustur(sonuclar))
    dosya_adi = pdf_dosya_adi()
    telegram_pdf_gonder(pdf_olustur(sonuclar), dosya_adi)

schedule.every().hour.at(":00").do(saatlik_gonder)

print("Bot baslatildi. Her saat basi sinyal gonderilecek.")
saatlik_gonder()

while True:
    schedule.run_pending()
    time.sleep(30)
