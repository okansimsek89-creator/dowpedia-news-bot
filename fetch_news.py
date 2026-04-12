import os
import json
import time
import requests
import google.generativeai as genai
from datetime import datetime

# ==========================================
# AYARLAR VE API ANAHTARLARI
# ==========================================
# GitHub Actions Secrets'dan API anahtarlarını alıyoruz
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not FINNHUB_API_KEY or not GEMINI_API_KEY:
    print("HATA: API anahtarları bulunamadı. Lütfen GitHub Secrets'ı kontrol edin.")
    exit(1)

# Gemini API'yi yapılandır
genai.configure(api_key=GEMINI_API_KEY)
# En güncel ve hızlı model olan gemini-3-flash-preview kullanıyoruz
model = genai.GenerativeModel('gemini-3-flash-preview')

# Dow Jones 30 Sembolleri
DOW_SYMBOLS = [
    "AAPL", "MSFT", "JPM", "V", "JNJ", "WMT", "PG", "UNH", "HD", "INTC",
    "VZ", "CVX", "KO", "CSCO", "MRK", "DIS", "MCD", "BA", "AXP", "IBM",
    "GS", "NKE", "TRV", "CAT", "CRM", "AMGN", "HON", "MMM", "DOW", "WBA"
]

# Kaydedilecek dosya yolu
DATA_FILE = "public/haberler.json"
LOG_FILE = "news_logs.json"

# ==========================================
# YARDIMCI FONKSİYONLAR
# ==========================================

def clean_json_string(text):
    """Gemini'den gelen metni temizleyip sadece saf JSON kısmını alır."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    
    # Başındaki ve sonundaki olası gereksiz boşlukları/karakterleri temizle
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    if start_idx != -1 and end_idx != -1:
        text = text[start_idx:end_idx + 1]
    return text

def save_log(status, message, details=None):
    """Çalışma raporunu JSON dosyasına kaydeder."""
    try:
        logs = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    logs = json.loads(content)
        
        new_log = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": status,
            "message": message,
            "details": details or []
        }
        
        logs = [new_log] + logs
        logs = logs[:50]
        
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Log yazma hatası: {e}")

def get_market_news():
    """Finnhub'dan piyasa haberlerini çeker."""
    url = f"https://finnhub.io/api/v1/news?category=general&token={FINNHUB_API_KEY}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Finnhub hatası: {e}")
        return []

def get_priority_score(item):
    """Belli başlı anahtar kelimelere göre haberin önem puanını hesaplar."""
    headline = item.get('headline', '').lower()
    summary = item.get('summary', '').lower()
    text = headline + " " + summary
    
    score = 0
    # Öncelik 1: Trump (10 puan)
    if "trump" in text:
        score += 10
        
    # Öncelik 2: Fed ve Merkez Bankaları (8 puan)
    central_banks = ["fed", "federal reserve", "ecb", "european central bank", "bank of japan", "boj", "pboc", "rbi", "central bank", "merkez bankası"]
    if any(cb in text for cb in central_banks):
        score += 8
        
    # Öncelik 3: Avrupa Haberleri (6 puan)
    europe = ["europe", "european", "eu ", "eurozone", "avrupa"]
    if any(e in text for e in europe):
        score += 6
        
    # Öncelik 4: Petrol ve Enerji (5 puan)
    energy = ["oil", "crude", "petroleum", "energy market", "petrol"]
    if any(en in text for en in energy):
        score += 5
        
    return score

def is_recent(timestamp, hours=48):
    """Haberin belirtilen saatten daha yeni olup olmadığını kontrol eder."""
    current_time = time.time()
    news_time = timestamp
    return (current_time - news_time) < (hours * 3600)

def generate_article(source_news):
    """Gemini ile makale üretir (NYT/Washington Post stiline uygun)."""
    prompt = f"""
    Act as a Senior Financial Correspondent for The New York Times or The Washington Post. 
    Write a serious, professional financial news article based on the summary provided below.
    
    CRITICAL INSTRUCTIONS:
    1. STYLE: Use financial expert (Financı) seriousness and analytical depth. Focus on market implications.
    2. FORMATTING: DO NOT use Markdown headers like '###' or '**'. Use plain text with clear paragraph breaks.
    3. PUNCTUATION: Use standard journalistic punctuation. Avoid unnecessary quotes for emphasis (e.g. do not write 'shadow wars' unless it's a direct quote).
    4. LENGTH: The article MUST be between 500 and 700 words long.
    5. OUTPUT: Output MUST be a valid JSON object.
    
    JSON STRUCTURE:
    {{
        "en": {{ "title": "Headline", "content": "Full article text...", "keywords": [], "tags": [] }},
        "zh": {{ "title": "文章标题", "content": "正文内容...", "keywords": [], "tags": [] }}
    }}
    
    SOURCE NEWS:
    Headline: {source_news.get('headline', '')}
    Summary: {source_news.get('summary', '')}
    """

    try:
        # Güvenlik ayarlarını gevşeterek engellenme riskini azaltıyoruz
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
        
        response = model.generate_content(prompt, safety_settings=safety_settings)
        if not response.text:
            return None
            
        cleaned_text = clean_json_string(response.text)
        return json.loads(cleaned_text)
    except Exception as e:
        print(f"Gemini üretim hatası: {e}")
        return None

def check_similarity(new_headline, new_summary, existing_articles):
    """Gemini kullanarak yeni haberin mevcut haberlerle benzerliğini kontrol eder."""
    if not existing_articles:
        return False
        
    # Son 15 haberin başlığını karşılaştırma için alalım
    recent_titles = []
    for art in existing_articles[:15]:
        title = art.get('en', {}).get('title', '')
        if title:
            recent_titles.append(title)
            
    if not recent_titles:
        return False
        
    titles_str = "\n".join([f"- {t}" for t in recent_titles])
    
    prompt = f"""
    You are a professional financial news editor. I will give you a list of recent headlines and a new news candidate. 
    Decide if the new news is semantically the SAME story or covers the SAME event as any of the recent headlines. 
    We want to avoid duplicate news articles about the same event.

    RECENT HEADLINES:
    {titles_str}

    NEW CANDIDATE:
    Headline: {new_headline}
    Summary: {new_summary}

    Is this new candidate ALREADY COVERED by any of the recent headlines? 
    Respond ONLY with 'YES' if it is a duplicate/similar story, or 'NO' if it is a unique news story.
    """

    try:
        response = model.generate_content(prompt)
        answer = response.text.strip().upper()
        # "YES" kelimesini ara
        return "YES" in answer
    except Exception as e:
        print(f"Benzerlik kontrolü hatası: {e}")
        return False

def main():
    single_headline = os.environ.get("SINGLE_HEADLINE")
    single_summary = os.environ.get("SINGLE_SUMMARY")
    
    print("Haber robotu v3.0 (Anlamsal Kontrol Aktif) çalışıyor...")
    try:
        if single_headline:
            print(f"ÖZEL HABER MODI AKTİF: {single_headline}")
            raw_news = [{
                "headline": single_headline,
                "summary": single_summary or "",
                "datetime": int(time.time()),
                "source": "MANUAL_TRIGGER"
            }]
        else:
            raw_news = get_market_news()

        if not raw_news:
            save_log("Error", "Finnhub'dan veri alınamadı.")
            return

        existing_news = []
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                existing_news = json.load(f)
        
        existing_titles_lower = [n.get('en', {}).get('title', '').lower() for n in existing_news]
        
        # Haberleri puanla ve tarihe göre sırala
        scored_news = []
        for item in raw_news:
            timestamp = item.get('datetime', 0)
            score = get_priority_score(item)
            
            if score > 0:
                if is_recent(timestamp, 48):
                    scored_news.append((score, timestamp, item))
            else:
                if is_recent(timestamp, 24):
                    scored_news.append((0, timestamp, item))
        
        scored_news.sort(key=lambda x: (x[0], x[1]), reverse=True)
        
        new_articles = []
        processed_count = 0
        
        for score, ts, item in scored_news:
            if processed_count >= 1: break 
            
            headline = item.get('headline', '')
            summary = item.get('summary', '')
            if len(summary) < 40: continue
            
            # 1. Aşama: Basit başlık kontrolü
            if any(headline.lower() in t or t in headline.lower() for t in existing_titles_lower):
                print(f"Haber atlandı (Mükerrer Başlık): {headline}")
                save_log("Warning", f"Benzer haber olduğu için haber oluşturulmadı (Başlık Eşleşmesi).", [headline])
                continue

            # 2. Aşama: Gemini ile Anlamsal Benzerlik Kontrolü
            print(f"Semantik kontrol yapılıyor: {headline}")
            if check_similarity(headline, summary, existing_news):
                print(f"Haber atlandı (Semantik Benzerlik): {headline}")
                save_log("Warning", f"Benzer haber olduğu için haber oluşturulmadı (Anlamsal Benzerlik).", [headline])
                continue

            print(f"Seçilen Haber (Puan: {score}): {headline}")
            article = generate_article(item)
            
            if article:
                ticker = "DIA"
                for s in DOW_SYMBOLS:
                    if s in headline: ticker = s; break
                
                new_item = {
                    "id": str(int(time.time() * 1000)) + str(processed_count),
                    "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                    "ticker": ticker,
                    "en": article.get("en", {}),
                    "zh": article.get("zh", {})
                }
                new_articles.append(new_item)
                processed_count += 1
                time.sleep(2)

        if new_articles:
            final_list = (new_articles + existing_news)
            
            # 20 HABER SINIRI VE ARŞİVLEME MANTIĞI
            if len(final_list) > 20:
                current_20 = final_list[:20]
                archived_news = final_list[20:]
                
                # Arşiv dizinini kontrol et ve oluştur
                ARCHIVE_DIR = "public/archive"
                if not os.path.exists(ARCHIVE_DIR):
                    os.makedirs(ARCHIVE_DIR)
                
                # Arşiv dosyasını kaydet (Zaman damgalı)
                archive_timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                archive_file = f"{ARCHIVE_DIR}/news_archive_{archive_timestamp}.json"
                
                with open(archive_file, 'w', encoding='utf-8') as af:
                    json.dump(archived_news, af, ensure_ascii=False, indent=2)
                
                final_list = current_20
                archive_msg = f" {len(archived_news)} eski haber arşive taşındı ({archive_file})."
            else:
                archive_msg = ""

            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(final_list, f, ensure_ascii=False, indent=2)
            
            save_log("Success", f"{len(new_articles)} yeni haber başarıyla eklendi.{archive_msg}", [new_articles[0]['en']['title']])
            print(f"Bitti.{archive_msg}")
        else:
            # Sadece kritik bir hata yoksa ve hiçbir haber üretilmediyse log düş
            save_log("Warning", "Yeni haber üretilmedi (Kriterlere uygun veya özgün haber bulunamadı).")

    except Exception as e:
        save_log("Error", f"Sistem hatası: {str(e)}")

if __name__ == "__main__":
    main()
