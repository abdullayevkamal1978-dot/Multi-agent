# research-swarm

**LangGraph üzerinde çalışan çok-ajanlı derin araştırma sistemi.**
Bir konu verirsiniz; sistem planlar, paralel olarak web'de arar, sayfaları okur,
kaynaklar arasındaki **çelişkileri** bulur ve atıflı bir rapor üretir.

Saatler süren "mənbə tap → oxu → qeyd et → xülasə çıxar" döngüsünü dakikalara indirir.

---

## Neden bu, "LLM'e sor" demekten farklı?

Tek bir LLM çağrısı kaynakları okuyamaz, birbiriyle karşılaştıramaz ve çelişkileri
gizler. Bu proje işi **uzmanlaşmış ajanlara böler** ve en önemlisi **çapraz kontrol**
adımını ayrı bir ajan olarak çalıştırır: aynı olgu hakkında iki kaynak uyuşmuyorsa bu
gizlenmez, `## Contradictions and disagreements` başlığı altında kaynağıyla birlikte
raporlanır. Çelişki bulunamaması da geçerli ve değerli bir sonuçtur.

---

## Hızlı başlangıç

```bash
uv sync --extra google --extra dev     # veya: pip install -e ".[google]"

# Hiç API anahtarı olmadan tüm hattı çalıştır (mock mod):
uv run research-swarm "solid-state battery commercialization timeline" --mock

# Gerçek LLM ile:
cp .env.example .env                   # anahtarları doldur
uv run research-swarm "konu" --out report.md --json report.json
```

---

## Hangi anahtar ne için gerekli?

| Katman | Ne yapar | Zorunlu mu? |
|---|---|---|
| **LLM** (Gemini / OpenAI / Anthropic) | Planlama, claim çıkarımı, çelişki tespiti, sentez | Gerçek sonuçlar için evet |
| **Arama** (Exa / Tavily / SerpAPI / Gemini grounding) | Kaynak bulma | Gerçek sonuçlar için evet |

### "Sadece Gemini anahtarı yeterli mi?" — ölçülmüş cevap

**LLM için evet.** `langchain-google-genai` ile test edildi, canlı çalışıyor.

**Arama için hayır.** Gemini'nin yerleşik *Google Search grounding* özelliği ücretsiz
katmanda kapalı. Bu depoda canlı olarak doğrulandı:

```
429 RESOURCE_EXHAUSTED — You exceeded your current quota, please check your plan and billing details.
```

Yani tek Gemini anahtarıyla: **LLM gerçek, arama mock** olur. Gerçek web sonuçları için
ikisinden birini yapın:

1. Ücretsiz bir arama anahtarı ekleyin — **Exa** (yeni hesaba $20 kredi, aylık $10) veya
   **Tavily** ücretsiz katman. `EXA_API_KEY` / `TAVILY_API_KEY` yeterli.
2. Gemini faturalandırmasını açın, sonra `SEARCH_PROVIDER=gemini` ayarlayın.

> Not: `mock` arama + gerçek LLM kombinasyonunda **0 claim** beklemelisiniz. Mock sayfalar
> kendilerini açıkça "kurgusal demo" olarak işaretler ve gerçek bir LLM doğru şekilde
> onlardan olgu çıkarmayı reddeder. Bu bilinçli bir dürüstlük kararıdır — sahte olgular
> ürettirip rapora yazdırmaktansa boş dönmek doğrudur.

Desteklenen sağlayıcılar: `gemini` `openai` `anthropic` · arama: `exa` `tavily` `serpapi` `gemini` `mock`.
`LLM_PROVIDER` / `SEARCH_PROVIDER` boş bırakılırsa hangi anahtar varsa otomatik seçilir.

---

## Mimari

```
                          ┌───────────────┐
        START ───────────▶│   PLANNER     │  konuyu alt sorulara böler
                          └───────┬───────┘
                                  │  Send() ile koşullu kenar → fan-out
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
       ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
       │ RESEARCHER  │     │ RESEARCHER  │ ... │ RESEARCHER  │   ← PARALEL
       │ ara→oku→    │     │ ara→oku→    │     │ ara→oku→    │
       │ claim çıkar │     │ claim çıkar │     │ claim çıkar │
       └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
              └───────────────────┼───────────────────┘
                                  ▼   örtük join: tüm dallar beklenir
                          ┌───────────────┐
                          │  CROSS-CHECK  │  kaynaklar arası çelişkiler
                          └───────┬───────┘
                                  ▼
                          ┌───────────────┐
                          │  SYNTHESIZER  │  bulgular + özet + açık sorular
                          └───────┬───────┘
                                  ▼
                                 END  →  Markdown + JSON rapor
```

| Ajan | Girdi | Çıktı (tipli) |
|---|---|---|
| **Planner** | konu | `ResearchPlan` — alt sorular + her biri için 2-4 arama sorgusu |
| **Researcher** (×N, paralel) | bir alt soru | `Source[]` + `Claim[]` |
| **Cross-check** | tüm claim'ler + kaynaklar | `Contradiction[]` (severity + çözüm kararı) |
| **Synthesizer** | claim'ler + çelişkiler | `Finding[]` + yönetici özeti + açık sorular |

Tüm ajan çıktıları **Pydantic şemasıyla** zorlanır (`with_structured_output`) — ajanlar
düzyazı değil, tipli veri alışverişi yapar.

---

## Akış, adım adım

1. **Planla** — konu, birbirinden bağımsız 4-6 alt soruya bölünür. En az bir alt soru
   anaakım görüşü *sorgulayacak* şekilde istenir ki çelişki yüzeye çıksın.
2. **Fan-out** — `Send()` ile her alt soru için bir dal açılır.
3. **Ara** — her dal kendi sorgularını paralel çalıştırır, sonuçlar URL'ye göre tekilleştirilir.
4. **Oku** — sayfalar eşzamanlı indirilir, HTML script/style/nav gürültüsünden arındırılır,
   disk önbelleğine yazılır.
5. **Claim çıkar** — LLM kaynak metinlerinden atomik, kaynak kimliği taşıyan iddialar çıkarır.
6. **Join** — tüm dallar bitene kadar beklenir; `operator.add` reducer'ları sonuçları birleştirir.
7. **Çapraz kontrol** — claim'ler karşılaştırılır; gerçek olgusal çatışmalar bulunur,
   şiddetleri belirlenir ve her biri için bir çözüm kararı verilir.
8. **Sentezle** — bulgular, yönetici özeti ve cevaplanamayan sorular **paralel** üretilir.
9. **Raporla** — Markdown + JSON çıktısı.

---

## Kullanım

### CLI

```bash
# Mock mod (anahtarsız, ağsız)
uv run research-swarm "quantum error correction progress" --mock

# Dosyaya yaz
uv run research-swarm "konu" --out out/report.md --json out/report.json

# Sağlayıcı/model seç, plan boyutunu ayarla
uv run research-swarm "konu" --provider gemini --model gemini-3.8-flash \
    --search exa --max-subquestions 6 --results-per-query 5 --concurrency 8

# Sadece raporu bas
uv run research-swarm "konu" --quiet
```

`--out` / `--json` verilmezse rapor doğrudan stdout'a yazılır; ilerleme günlükleri stderr'e gider.

### Python API

```python
import asyncio
from research_swarm import Settings, run_research

async def main():
    settings = Settings(llm_provider="gemini", search_provider="exa", max_subquestions=5)
    report = await run_research("tidal energy economics", settings)

    print(report.executive_summary)
    for finding in report.findings:
        print(finding.heading, finding.source_ids, finding.confidence)
    for c in report.contradictions:
        print(f"[{c.severity}] {c.description} -> {c.resolution}")
    print(report.stats.model_dump())

asyncio.run(main())
```

Canlı ilerleme için `on_event=(node_name, update) -> None` geri çağrısını verin.

---

## Tasarım kararları

**1. Paralellik `Send()` ile, `asyncio.gather` ile değil.**
Grafik seviyesinde fan-out kullanılıyor; her dal ayrı bir grafik düğümü olduğu için
durumu, hataları ve ilerlemeyi ayrı ayrı izlenebiliyor. Dal içinde de arama/sayfa okuma
işlemleri kendi içinde eşzamanlı.

**2. Kaynak kimlikleri URL'ye göre paylaştırılır.**
Naif yaklaşımda iki farklı dal aynı sayfayı bulduğunda rapora **iki kopya** düşer.
`Runtime.citation_ids()` normalleştirilmiş URL'ye göre kimlik verir; fan-in'de
`dedupe_by_id()` tekilleştirir. Bu, `tests/test_citations.py` ile doğrulanır.

**3. Her dal hata izole eder.**
Bir arama sorgusu, bir sayfa indirmesi veya bir alt soru çökerse yalnızca o dal boş döner;
`errors` kanalına kaydedilir ve `## Run warnings` altında raporlanır. Grafik devam eder.
Planner bile çökse rapor üretilir (canlı testte gözlemlendi).

**4. Mock mod birinci sınıf vatandaş.**
`MockLLM` prompt'un saf fonksiyonudur — deterministik ve ağsız. Bu sayede tüm grafik,
gerçek durum geçişleriyle, CI'da ve anahtarsız test edilebilir. Ölçtüğümüz paralellik
sonuçları bu moddan geliyor.

**5. Bağımlılıklar hafif tutulur.**
Search sağlayıcıları ham `httpx` ile konuşur (SDK sürüm kayması yok). HTML→metin
dönüşümü için trafilatura/readability yerine küçük bir `html.parser` tabanlı çıkarıcı var.

---

## Ölçümler

Paralellik gerçekten ölçüldü (`tests/test_parallelism.py`, her arama çağrısına 0.25s gecikme
enjekte edilerek):

```
arama çağrısı       : 8
tepe eşzamanlılık   : 5
sıralı olsaydı      : 2.00s
gerçek duvar saati  : 0.51s
hızlanma            : 3.9x
```

Test yalnızca zamana değil, **gözlenen tepe eşzamanlılığa** da bakar — meşgul bir makinede
zamanlama tek başına zayıf bir kanıttır.

Gerçek Gemini gecikmesi (ücretsiz kota, `gemini-3.8-flash`):

| Yapılandırma | Planlama çağrısı |
|---|---|
| `GEMINI_THINKING_BUDGET=0` | 68s |
| varsayılan (düşünme açık) | 109s |

Mutlak sürelerde asıl belirleyici ücretsiz kotanın kısıtlaması. `GEMINI_THINKING_BUDGET=0`
iyi tanımlanmış çıkarım görevlerinde ölçülebilir şekilde daha hızlı (~%40); varsayılan
olarak boş bırakıldı, yani sağlayıcının kendi kararı geçerli.

---

## Test

```bash
uv run pytest -q          # 49 test, tamamı ağsız ve anahtarsız
```

Kapsam: model doğrulama, HTML çıkarımı + önbellek, sağlayıcı çözümleme, mock LLM
determinizmi, uçtan uca grafik, atıf çözümlemesi, eşzamanlı kimlik tahsisi, paralellik
ölçümü, Markdown/JSON render ve bozuk-girdi davranışı.

---

## Proje yapısı

```
src/research_swarm/
  models.py              Pydantic şemaları (Plan, Source, Claim, Contradiction, Report)
  config.py              ortam değişkenleri + sağlayıcı çözümleme
  state.py               LangGraph durum şeması (operator.add reducer'ları)
  graph.py               StateGraph topolojisi + Send() fan-out
  runner.py              uçtan uca giriş noktası
  report.py              Markdown / JSON render
  cli.py                 komut satırı arayüzü
  llm.py                 LangChain sağlayıcıları + MockLLM protokolü
  mock_llm.py            deterministik çevrimdışı LLM
  agents/
    runtime.py           enjekte edilen bağımlılıklar, atıf kayıt defteri, yardımcılar
    planner.py           konu → alt sorular
    researcher.py        ara → oku → claim çıkar (paralel çalışan birim)
    contradiction.py     kaynaklar arası çelişki tespiti
    synthesizer.py       bulgular + özet + açık sorular
  providers/
    base.py              SearchProvider protokolü + fabrika
    tavily.py exa.py serpapi.py gemini_grounding.py mock.py
    fetch.py             eşzamanlı sayfa okuyucu + HTML→metin + disk önbelleği
    http.py              paylaşılan httpx istemcisi, yeniden deneme, backoff
tests/                   pytest paketi (hepsi çevrimdışı)
examples/quickstart.py   çalıştırılabilir örnek
```

---

## Sınırlar (dürüst liste)

- **Gerçek arama sağlayıcıları canlı test edilmedi.** `tavily`, `exa`, `serpapi` ve
  `gemini_grounding` uygulandı ama elde yalnızca Gemini anahtarı olduğu için yalnızca
  `mock` arama uçtan uca doğrulandı. İlk gerçek anahtarınızda beklenmedik alan adı
  farklılıkları çıkabilir.
- **Gemini grounding ücretsiz kotada 429 döndü** — kod yolu hazır, kota yok.
- **`mock` arama + gerçek LLM = 0 claim** (yukarıda açıklandı).
- Sayfa okuma `robots.txt`'e saygı duymaz; üretimde bir politika katmanı eklenmelidir.
- Rapor doğruluğu kaynak kalitesine bağlıdır; atıf kimlikleri LLM'in prompt'ta gördüğü
  kaynaklarla sınırlandırılır ama **uydurma atıf** riski tamamen ortadan kalkmaz —
  her bulgunun `source_ids`'i kaynak listesine karşı doğrulanır, içerik doğrulanmaz.

## Sonraki adımlar

- Gerçek arama sağlayıcısıyla canlı doğrulama + entegrasyon testi
- `langgraph-checkpoint` ile kesintiye dayanıklı (resumable) uzun koşular
- Alaka/credibility puanlama ajanı (şu an sıralama sağlayıcıya bırakılıyor)
- Raporu PDF/HTML olarak dışa aktarma
