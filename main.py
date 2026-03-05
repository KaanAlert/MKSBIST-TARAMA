import os
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
from io import BytesIO
import schedule
import pytz

# reportlab imports
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.graphics import renderPM
from reportlab.graphics.shapes import Drawing
import subprocess

TOKEN   = os.environ.get("TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
TZ      = pytz.timezone("Europe/Istanbul")

# ============================================================
# HİSSE LİSTELERİ
# ============================================================

BIST50 = [
    "AEFES", "AKBNK", "ALARK", "ARCLK", "ASELS",
    "ASTOR", "BIMAS", "BRSAN", "BTCIM", "CCOLA",
    "CIMSA", "DOAS",  "DOHOL", "DSTKF", "EKGYO",
    "ENKAI", "EREGL", "FROTO", "GARAN", "GUBRF",
    "HALKB", "HEKTS", "ISCTR", "KCHOL", "KONTR",
    "KRDMD", "KUYAS", "MAVI",  "MGROS", "MIATK",
    "OYAKC", "PASEU", "PETKM", "PGSUS", "SAHOL",
    "SASA",  "SISE",  "SOKM",  "TAVHL", "TCELL",
    "THYAO", "TOASO", "TRALT", "TRMET", "TSKB",
    "TTKOM", "TUPRS", "ULKER", "VAKBN", "YKBNK"
]

OZEL_HISSELER = [
    "KRSTL", "ALARK", "ESCOM", "A1CAP", "ISGSY",
    "LMKDC", "BULGS", "MIATK", "ORGE",  "YEOTK",
    "DESA",  "TUKAS", "VAKKO"
]

def yahoo_sembol(h): return f"{h}.IS"

# ============================================================
# GUN ADI
# ============================================================
GUNLER = {
    "Monday": "PAZARTESI", "Tuesday": "SALI", "Wednesday": "CARSAMBA",
    "Thursday": "PERSEMBE", "Friday": "CUMA", "Saturday": "CUMARTESI",
    "Sunday": "PAZAR"
}
def gun_adi():
    return GUNLER.get(datetime.now(TZ).strftime("%A"), "")

def simdi():
    return datetime.now(TZ)

# ============================================================
# İNDİKATÖR HESAPLAMALARI
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
    diff  = hh - ll
    rdiff = df['Close'] - (hh + ll) / 2
    avgrel  = rdiff.ewm(span=smooth, adjust=False).mean().ewm(span=smooth, adjust=False).mean()
    avgdiff = diff.ewm(span=smooth, adjust=False).mean().ewm(span=smooth, adjust=False).mean()
    smi = pd.Series(np.where(avgdiff != 0, avgrel / (avgdiff / 2) * 100, 0), index=df.index)
    sinyal = smi.ewm(span=sig_len, adjust=False).mean()
    return smi.iloc[-1] > sinyal.iloc[-1]

def hesapla_mfi(df, period=14):
    if df['Volume'].iloc[-period:].sum() == 0:
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

def hesapla_hacim(df, period=20):
    if len(df) < period + 2:
        return "N/A", "N/A", 0
    if df['Volume'].iloc[-period-1:-1].sum() == 0:
        return "N/A", "N/A", 0
    ort = df['Volume'].iloc[-period-1:-1].mean()
    mev = df['Volume'].iloc[-1]
    if ort == 0:
        return "N/A", "N/A", 0

    def format_hacim(v):
        if v >= 1_000_000_000:
            return f"{round(v/1_000_000_000, 1)}MR"
        elif v >= 1_000_000:
            return f"{round(v/1_000_000, 1)}MN"
        elif v >= 1_000:
            return f"{round(v/1_000, 1)}K"
        return str(int(v))

    oran = mev / ort
    return format_hacim(ort), format_hacim(mev), oran

def hacim_renk(oran):
    if oran == 0:
        return colors.HexColor("#F5F5F5"), colors.HexColor("#999999")
    if oran >= 1.2:
        return colors.HexColor("#D4EDDA"), colors.HexColor("#155724")  # Yesil
    if oran <= 0.8:
        return colors.HexColor("#F8D7DA"), colors.HexColor("#721C24")  # Kirmizi
    return colors.HexColor("#FFF3CD"), colors.HexColor("#856404")      # Sari

def pozisyon(smi_al, wt_al, macd_al):
    al  = sum([smi_al, wt_al, macd_al])
    sat = 3 - al
    if al == 3:  return "GUCLU AL"
    if al == 2:  return "AL"
    if sat == 3: return "GUCLU SAT"
    if sat == 2: return "SAT"
    return "BEKLE"

# ============================================================
# ANALİZ
# ============================================================

def analiz_et(liste):
    sonuclar = []
    for hisse in liste:
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
            h_ort, h_mev, h_oran = hesapla_hacim(df)

            sonuclar.append({
                "Hisse":     hisse,
                "SMI":       "AL" if smi_al  else "SAT",
                "WT":        "AL" if wt_al   else "SAT",
                "MACD":      "AL" if macd_al else "SAT",
                "Pozisyon":  poz,
                "MFI_Trend": mfi_trend,
                "MFI_Val":   mfi_val,
                "H_Ort":     h_ort,
                "H_Mev":     h_mev,
                "H_Oran":    h_oran,
                "smi_al":    smi_al,
                "wt_al":     wt_al,
                "macd_al":   macd_al,
            })
        except Exception as e:
            print(f"{hisse} hata: {e}")
    return sonuclar

# ============================================================
# RENK PALETİ
# ============================================================

C_BASLIK_BG   = colors.HexColor("#1B2A4A")
C_BASLIK_TEXT = colors.HexColor("#FFFFFF")
C_SUTUN_BG    = colors.HexColor("#2E4A7A")
C_SUTUN_TEXT  = colors.HexColor("#E8F0FE")
C_HISSE_BG    = colors.HexColor("#EEF2FF")
C_HISSE_TEXT  = colors.HexColor("#1B2A4A")
C_SATIR1      = colors.HexColor("#FFFFFF")
C_SATIR2      = colors.HexColor("#F5F7FF")
C_AL_BG       = colors.HexColor("#D4EDDA")
C_AL_TEXT     = colors.HexColor("#155724")
C_GUCLU_AL_BG = colors.HexColor("#28A745")
C_GUCLU_AL_TX = colors.HexColor("#FFFFFF")
C_SAT_BG      = colors.HexColor("#F8D7DA")
C_SAT_TEXT    = colors.HexColor("#721C24")
C_GUCLU_SAT_BG= colors.HexColor("#DC3545")
C_GUCLU_SAT_TX= colors.HexColor("#FFFFFF")
C_BEKLE_BG    = colors.HexColor("#FFF3CD")
C_BEKLE_TEXT  = colors.HexColor("#856404")
C_POZ_BG      = colors.HexColor("#C8F7C5")
C_POZ_TEXT    = colors.HexColor("#1A6B19")
C_NEG_BG      = colors.HexColor("#FADBD8")
C_NEG_TEXT    = colors.HexColor("#922B21")
C_GRID        = colors.HexColor("#C5D0E8")

def sinyal_renk(s):
    return (C_AL_BG, C_AL_TEXT) if s == "AL" else (C_SAT_BG, C_SAT_TEXT)

def poz_renk(p):
    if p == "GUCLU AL":  return C_GUCLU_AL_BG, C_GUCLU_AL_TX
    if p == "AL":        return C_AL_BG,        C_AL_TEXT
    if p == "GUCLU SAT": return C_GUCLU_SAT_BG, C_GUCLU_SAT_TX
    if p == "SAT":       return C_SAT_BG,       C_SAT_TEXT
    return C_BEKLE_BG, C_BEKLE_TEXT

def mfi_trend_renk(t):
    return (C_POZ_BG, C_POZ_TEXT) if t == "POZITIF" else (C_NEG_BG, C_NEG_TEXT)

def mfi_val_renk(v):
    if v is None: return C_SATIR1, colors.HexColor("#999999")
    if v >= 80:   return colors.HexColor("#DC3545"), colors.white
    if v >= 60:   return C_AL_BG,  C_AL_TEXT
    if v <= 20:   return colors.HexColor("#6F42C1"), colors.white
    if v <= 40:   return C_SAT_BG, C_SAT_TEXT
    return C_BEKLE_BG, C_BEKLE_TEXT

# ============================================================
# PDF OLUŞTUR
# ============================================================

def baslik_olustur():
    now = simdi()
    return f"MKS TARAMA   {now.strftime('%d.%m.%Y')} {gun_adi()}"

def pdf_dosya_adi():
    now = simdi()
    return f"MKS_TARAMA_{now.strftime('%d%m%Y')}_{now.strftime('%H%M')}.pdf"

def tablo_satir_stili(sonuclar, baslangic_row=1):
    stil = []
    for i, r in enumerate(sonuclar, start=baslangic_row):
        bg1, tx1 = sinyal_renk(r['SMI'])
        stil += [('BACKGROUND',(1,i),(1,i),bg1),('TEXTCOLOR',(1,i),(1,i),tx1),('FONTNAME',(1,i),(1,i),'Helvetica-Bold')]
        bg2, tx2 = sinyal_renk(r['WT'])
        stil += [('BACKGROUND',(2,i),(2,i),bg2),('TEXTCOLOR',(2,i),(2,i),tx2),('FONTNAME',(2,i),(2,i),'Helvetica-Bold')]
        bg3, tx3 = sinyal_renk(r['MACD'])
        stil += [('BACKGROUND',(3,i),(3,i),bg3),('TEXTCOLOR',(3,i),(3,i),tx3),('FONTNAME',(3,i),(3,i),'Helvetica-Bold')]
        bg4, tx4 = poz_renk(r['Pozisyon'])
        stil += [('BACKGROUND',(4,i),(4,i),bg4),('TEXTCOLOR',(4,i),(4,i),tx4),('FONTNAME',(4,i),(4,i),'Helvetica-Bold')]
        bg5, tx5 = mfi_trend_renk(r['MFI_Trend'])
        stil += [('BACKGROUND',(5,i),(5,i),bg5),('TEXTCOLOR',(5,i),(5,i),tx5),('FONTNAME',(5,i),(5,i),'Helvetica-Bold')]
        bg6, tx6 = mfi_val_renk(r['MFI_Val'])
        stil += [('BACKGROUND',(6,i),(6,i),bg6),('TEXTCOLOR',(6,i),(6,i),tx6),('FONTNAME',(6,i),(6,i),'Helvetica-Bold')]
        bg7, tx7 = hacim_renk(r['H_Oran'])
        stil += [('BACKGROUND',(7,i),(7,i),bg7),('TEXTCOLOR',(7,i),(7,i),tx7),('FONTNAME',(7,i),(7,i),'Helvetica-Bold')]
    return stil

def tablo_olustur(sonuclar, col_w):
    headers = ["HISSE", "SMI", "WT", "MACD", "POZISYON", "MFI TREND", "MFI DEGER", "HACIM (ORT/MEV)"]
    data = [headers]
    for r in sonuclar:
        mfi_str = str(r['MFI_Val']) if r['MFI_Val'] is not None else "N/A"
        h_str   = f"{r['H_Ort']}/{r['H_Mev']}" if r['H_Ort'] != "N/A" else "N/A"
        data.append([
            r['Hisse'],
            r['SMI'], r['WT'], r['MACD'],
            r['Pozisyon'],
            r['MFI_Trend'],
            mfi_str,
            h_str,
        ])

    tablo = Table(data, colWidths=col_w, repeatRows=1)
    stil = [
        ('BACKGROUND',   (0,0),(-1,0),  C_SUTUN_BG),
        ('TEXTCOLOR',    (0,0),(-1,0),  C_SUTUN_TEXT),
        ('FONTNAME',     (0,0),(-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0,0),(-1,0),  8.5),
        ('ALIGN',        (0,0),(-1,0),  'CENTER'),
        ('TOPPADDING',   (0,0),(-1,0),  6),
        ('BOTTOMPADDING',(0,0),(-1,0),  6),
        ('FONTSIZE',     (0,1),(-1,-1), 8),
        ('ALIGN',        (0,1),(-1,-1), 'CENTER'),
        ('VALIGN',       (0,0),(-1,-1), 'MIDDLE'),
        ('TOPPADDING',   (0,1),(-1,-1), 4),
        ('BOTTOMPADDING',(0,1),(-1,-1), 4),
        ('GRID',         (0,0),(-1,-1), 0.4, C_GRID),
        ('BACKGROUND',   (0,1),(0,-1),  C_HISSE_BG),
        ('TEXTCOLOR',    (0,1),(0,-1),  C_HISSE_TEXT),
        ('FONTNAME',     (0,1),(0,-1),  'Helvetica-Bold'),
        ('ALIGN',        (0,1),(0,-1),  'LEFT'),
    ]
    stil += tablo_satir_stili(sonuclar)
    tablo.setStyle(TableStyle(stil))
    return tablo

def pdf_olustur(bist50_sonuc, ozel_sonuc):
    buffer  = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        rightMargin=1.2*cm, leftMargin=1.2*cm,
        topMargin=1.2*cm,   bottomMargin=1.2*cm,
    )

    styles = getSampleStyleSheet()
    baslik_stil = ParagraphStyle('B', fontSize=13, textColor=C_BASLIK_TEXT,
                                 alignment=TA_CENTER, fontName='Helvetica-Bold', spaceAfter=2)
    alt_stil    = ParagraphStyle('A', fontSize=7.5, textColor=colors.HexColor("#8899BB"),
                                 alignment=TA_CENTER, fontName='Helvetica', spaceAfter=6)
    bolum_stil  = ParagraphStyle('S', fontSize=9, textColor=C_BASLIK_TEXT,
                                 fontName='Helvetica-Bold', spaceBefore=8, spaceAfter=4)
    legend_stil = ParagraphStyle('L', fontSize=6.5, textColor=colors.HexColor("#888888"),
                                 fontName='Helvetica-Oblique')
    veri_stil   = ParagraphStyle('V', fontSize=8, textColor=colors.HexColor("#333333"),
                                 fontName='Helvetica-Bold', alignment=TA_CENTER)

    story = []

    # Ana baslik
    baslik_data = [[Paragraph(baslik_olustur(), baslik_stil)]]
    baslik_tablo = Table(baslik_data, colWidths=[25.6*cm])
    baslik_tablo.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1), C_BASLIK_BG),
        ('TOPPADDING',(0,0),(-1,-1), 8),
        ('BOTTOMPADDING',(0,0),(-1,-1), 8),
    ]))
    story.append(baslik_tablo)
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph("SMI | WaveTrend | MACD | MFI   -   4 Saatlik Grafik Analizi", alt_stil))

    # BIST 50 tablosu
    story.append(Paragraph("BIST 50", bolum_stil))
    col_w = [2.6*cm, 2.2*cm, 2.2*cm, 2.2*cm, 3.2*cm, 2.6*cm, 2.4*cm, 3.0*cm]
    story.append(tablo_olustur(bist50_sonuc, col_w))

    # Ozet
    story.append(Spacer(1, 0.3*cm))
    gal  = [r['Hisse'] for r in bist50_sonuc if r['Pozisyon'] == "GUCLU AL"]
    gsat = [r['Hisse'] for r in bist50_sonuc if r['Pozisyon'] == "GUCLU SAT"]
    ozet_stil = ParagraphStyle('O', fontSize=7.5, textColor=colors.HexColor("#333333"),
                               fontName='Helvetica', spaceAfter=2)
    if gal:  story.append(Paragraph(f"GUCLU AL: {', '.join(gal)}", ozet_stil))
    if gsat: story.append(Paragraph(f"GUCLU SAT: {', '.join(gsat)}", ozet_stil))

    # Özel hisseler tablosu
    if ozel_sonuc:
        story.append(Spacer(1, 0.4*cm))
        story.append(Paragraph("OZEL HISSELER", bolum_stil))
        story.append(tablo_olustur(ozel_sonuc, col_w))

    # Legend
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        "MFI: 80+ Asiri Alim | 60-80 Guclu | 40-60 Notr | 20-40 Zayif | 0-20 Asiri Satim   |   "
        "MFI Trend: POZITIF=Yukselis | NEGATIF=Dusus   |   "
        "Hacim: Yesil=Ort.Ustu | Sari=Normal | Kirmizi=Ort.Alti",
        legend_stil
    ))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(f"Veri Saati: {simdi().strftime('%H:%M')}", veri_stil))

    doc.build(story)
    buffer.seek(0)
    return buffer

# ============================================================
# TELEGRAM
# ============================================================

def png_olustur(bist50_sonuc):
    """BIST 50 tablosunu dikey PNG olarak olustur (Twitter icin)"""
    from reportlab.lib.pagesizes import A4
    buffer_pdf = BytesIO()
    doc = SimpleDocTemplate(
        buffer_pdf, pagesize=A4,
        rightMargin=1*cm, leftMargin=1*cm,
        topMargin=1*cm,   bottomMargin=1*cm,
    )
    styles = getSampleStyleSheet()
    baslik_stil = ParagraphStyle("BP", fontSize=11, textColor=C_BASLIK_TEXT,
                                  alignment=TA_CENTER, fontName="Helvetica-Bold", spaceAfter=2)
    alt_stil    = ParagraphStyle("AP", fontSize=6.5, textColor=colors.HexColor("#8899BB"),
                                  alignment=TA_CENTER, fontName="Helvetica", spaceAfter=6)
    veri_stil   = ParagraphStyle("VP", fontSize=7, textColor=colors.HexColor("#333333"),
                                  fontName="Helvetica-Bold", alignment=TA_CENTER)
    story = []

    # Baslik
    baslik_data = [[Paragraph(baslik_olustur(), baslik_stil)]]
    baslik_tablo = Table(baslik_data, colWidths=[19*cm])
    baslik_tablo.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1), C_BASLIK_BG),
        ("TOPPADDING",(0,0),(-1,-1), 7),
        ("BOTTOMPADDING",(0,0),(-1,-1), 7),
    ]))
    story.append(baslik_tablo)
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph("SMI | WaveTrend | MACD | MFI   -   4 Saatlik", alt_stil))

    # Tablo - dikey icin dar kolonlar
    col_w = [2.2*cm, 1.8*cm, 1.8*cm, 1.8*cm, 2.8*cm, 2.2*cm, 2.0*cm, 2.4*cm]
    story.append(tablo_olustur(bist50_sonuc, col_w))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(f"Veri Saati: {simdi().strftime('%H:%M')}", veri_stil))

    doc.build(story)

    # PDF'i PNG'ye cevir (ghostscript ile)
    buffer_pdf.seek(0)
    tmp_pdf = "/tmp/twitter_tablo.pdf"
    tmp_png = "/tmp/twitter_tablo.png"
    with open(tmp_pdf, "wb") as f:
        f.write(buffer_pdf.read())

    subprocess.run([
        "gs", "-dNOPAUSE", "-dBATCH", "-sDEVICE=png16m",
        "-r150", f"-sOutputFile={tmp_png}", tmp_pdf
    ], capture_output=True)

    with open(tmp_png, "rb") as f:
        return BytesIO(f.read())

def telegram_foto_gonder(png_buffer, dosya_adi):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    r = requests.post(
        url,
        data={"chat_id": CHAT_ID, "caption": f"Twitter Gorseli - {dosya_adi}"},
        files={"photo": (dosya_adi.replace(".pdf",".png"), png_buffer, "image/png")}
    )
    print(f"PNG: {r.status_code} {simdi().strftime('%H:%M')}")

def telegram_metin_gonder(mesaj):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": mesaj, "parse_mode": "Markdown"})
    print(f"Metin: {r.status_code} {simdi().strftime('%H:%M')}")

def telegram_pdf_gonder(pdf_buffer, dosya_adi):
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    r = requests.post(
        url,
        data={"chat_id": CHAT_ID, "caption": dosya_adi},
        files={"document": (dosya_adi, pdf_buffer, "application/pdf")}
    )
    print(f"PDF: {r.status_code} {simdi().strftime('%H:%M')}")

def mesaj_olustur(sonuclar, baslik):
    now = simdi()
    mesaj = f"*{baslik} - {now.strftime('%d.%m.%Y')} {gun_adi()} {now.strftime('%H:%M')}*\n\n"
    mesaj += "`Hisse  |SMI|WT |MACD|Pozisyon   |MFI |Val `\n"
    mesaj += "`" + "-"*46 + "`\n"
    for r in sonuclar:
        h   = r['Hisse'].ljust(6)
        smi = r['SMI'][:3].ljust(3)
        wt  = r['WT'][:2].ljust(3)
        mac = r['MACD'][:3].ljust(4)
        poz = r['Pozisyon'][:10].ljust(10)
        mft = r['MFI_Trend'][:4].ljust(4)
        mfv = str(r['MFI_Val'] or "N/A").ljust(4)
        mesaj += f"`{h}|{smi}|{wt}|{mac}|{poz}|{mft}|{mfv}`\n"
    gal  = [r['Hisse'] for r in sonuclar if r['Pozisyon'] == "GUCLU AL"]
    gsat = [r['Hisse'] for r in sonuclar if r['Pozisyon'] == "GUCLU SAT"]
    if gal:  mesaj += f"\n*GUCLU AL:* {', '.join(gal)}"
    if gsat: mesaj += f"\n*GUCLU SAT:* {', '.join(gsat)}"
    return mesaj

# ============================================================
# HACSİM UYARISI (15 dakikada bir kontrol)
# ============================================================

onceki_uyari = {}  # hisse -> son uyari zamani

def hacim_uyari_kontrol():
    global onceki_uyari
    tum_liste = BIST50 + OZEL_HISSELER
    uyarilar = []

    for hisse in tum_liste:
        try:
            df = yf.download(yahoo_sembol(hisse), period="60d", interval="4h",
                             progress=False, auto_adjust=True)
            if df is None or len(df) < 25:
                continue
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

            _, _, h_oran = hesapla_hacim(df)
            if h_oran >= 2.5:
                son_uyari = onceki_uyari.get(hisse)
                simdi_ts  = simdi()
                # Ayni hisse icin 4 saat bekle
                if son_uyari is None or (simdi_ts - son_uyari).seconds > 14400:
                    smi_al  = hesapla_smiio(df)
                    wt_al   = hesapla_wavetrend(df)
                    macd_al = hesapla_macd(df)
                    poz     = pozisyon(smi_al, wt_al, macd_al)
                    _, h_mev, _ = hesapla_hacim(df)
                    uyarilar.append(f"{hisse} | {poz} | Hacim: {round(h_oran,1)}x")
                    onceki_uyari[hisse] = simdi_ts
        except:
            pass

    if uyarilar:
        mesaj = f"🚨 *HACIM ANOMALISI!*\n_{simdi().strftime('%H:%M')}_\n\n"
        for u in uyarilar:
            mesaj += f"`{u}`\n"
        telegram_metin_gonder(mesaj)
        print(f"Hacim uyarisi gonderildi: {len(uyarilar)} hisse")

# ============================================================
# ANA FONKSİYON
# ============================================================

def tablo_gonder():
    print(f"Analiz basliyor... {simdi().strftime('%H:%M')}")
    bist50_sonuc = analiz_et(BIST50)
    ozel_sonuc   = analiz_et(OZEL_HISSELER)

    if not bist50_sonuc:
        print("Veri alinamadi.")
        return

    # Metin
    telegram_metin_gonder(mesaj_olustur(bist50_sonuc, "BIST 50"))
    if ozel_sonuc:
        telegram_metin_gonder(mesaj_olustur(ozel_sonuc, "OZEL HISSELER"))

    # PDF
    dosya_adi = pdf_dosya_adi()
    pdf_buf = pdf_olustur(bist50_sonuc, ozel_sonuc)
    telegram_pdf_gonder(pdf_buf, dosya_adi)

    # PNG (Twitter icin)
    try:
        png_buf = png_olustur(bist50_sonuc)
        telegram_foto_gonder(png_buf, dosya_adi)
    except Exception as e:
        print(f"PNG hatasi: {e}")

    print(f"Tamamlandi: {simdi().strftime('%H:%M')}")

# ============================================================
# ZAMANLAMA — Türkiye Saati
# ============================================================

schedule.every().day.at("06:00").do(tablo_gonder)   # UTC = TR 09:00
schedule.every().day.at("07:00").do(tablo_gonder)   # UTC = TR 10:00
schedule.every().day.at("09:00").do(tablo_gonder)   # UTC = TR 12:00
schedule.every().day.at("11:00").do(tablo_gonder)   # UTC = TR 14:00
schedule.every().day.at("13:00").do(tablo_gonder)   # UTC = TR 16:00
schedule.every().day.at("15:00").do(tablo_gonder)   # UTC = TR 18:00
schedule.every().day.at("15:10").do(tablo_gonder)   # UTC = TR 18:10
schedule.every(15).minutes.do(hacim_uyari_kontrol)  # Hacim anomali kontrolu

print("Bot baslatildi.")
print("Tablo saatleri: 09:00 10:00 12:00 14:00 16:00 18:00 18:10 (TR saati)")
print("Hacim anomali kontrolu: her 15 dakikada bir")
tablo_gonder()  # Baslarken bir kere calistir

while True:
    schedule.run_pending()
    time.sleep(30)
