# Design: IHSG Screener — Teknikal + Sentimen AI

Tanggal: 2026-08-25
Status: Disetujui untuk perencanaan implementasi

## 1. Tujuan

Sistem pemindai harian untuk saham Bursa Efek Indonesia yang memicu "BUY ALERT" ke
Telegram hanya ketika dua kondisi terpenuhi bersamaan: momentum teknikal bullish
berdasarkan data End-of-Day, dan sentimen berita berbahasa Indonesia yang positif
menurut model IndoBERT.

Sistem ini adalah **screener pasca-market**, bukan sistem eksekusi order dan bukan
sistem intraday. Keluarannya adalah notifikasi untuk ditinjau manusia.

## 2. Ruang lingkup

Termasuk:
- Pengambilan data OHLCV EOD untuk watchlist statis 20-45 emiten
- Perhitungan indikator teknikal dan evaluasi aturan yang dapat dikonfigurasi
- Pengambilan berita berbahasa Indonesia per emiten dan analisis sentimen IndoBERT
- Gate keputusan AND, notifikasi Telegram, deduplikasi, dan riwayat scan di SQLite
- Antarmuka CLI dan kesiapan penjadwalan otomatis

Tidak termasuk (v1), dengan rincian di §2.1:
- Antarmuka web (direncanakan sebagai Project 2)
- Screening valuasi dan evaluasi performa sinyal (direncanakan sebagai Project 3)
- Eksekusi order atau integrasi broker (tidak direncanakan)
- Data intraday atau streaming (tidak direncanakan)

## 2.1 Peta project

Kebutuhan penuh yang disepakati mencakup antarmuka web dan screening valuasi.
Keduanya sengaja dipisah menjadi project tersendiri, bukan dimasukkan ke v1.

**Project 1 — Engine (dokumen ini).**
CLI, cron, Telegram. Selesai ketika SQLite terisi hasil scan yang benar.

**Project 2 — Antarmuka web.**
FastAPI membaca database yang sama. Bertahap: dashboard baca-saja → editor
watchlist & settings → pemicu scan manual.

**Project 3 — Valuasi & evaluasi performa.**
Provider data fundamental, aturan "murah" berbasis PER/PBV, snapshot harga
lanjutan, beserta grafiknya.

Urutan ini bukan preferensi melainkan ketergantungan: Project 2 tidak memiliki
apa pun untuk ditampilkan sampai Project 1 mengisi database, dan Project 3 tidak
dapat dievaluasi sampai tersedia riwayat alert yang cukup untuk diukur.

Beberapa kebutuhan yang tampak seperti fitur web sebenarnya menembus batas ke
luar web, dan dicatat di sini agar tidak salah tempat saat direncanakan:

| Kebutuhan | Letak sebenarnya |
|---|---|
| Dashboard riwayat & alert | Murni web, baca SQLite |
| Editor watchlist & settings | Murni web, tulis YAML + validasi |
| Tombol scan manual | Web + **job runner latar** (status job, penguncian) |
| Evaluasi performa sinyal | **Perubahan engine**: snapshot harga H+5/H+20 harus dikumpulkan harian; web hanya menggambarnya |
| Grafik saham murah berpotensi naik | **Provider baru**: valuasi bukan persoalan tampilan |

**Batas arsitektur yang disiapkan sejak v1.** Tidak ada satu pun dari ketiga
project yang menuntut perubahan pada `core/`:

- Web menjadi entry point kedua yang sejajar dengan `cli.py`, mengimpor
  `storage/repository.py` dan `models.py` yang sama. Karena keduanya satu
  bahasa, tidak ada skema database atau format yang perlu didefinisikan dua kali.
- `providers/fundamentals.py` berdiri sejajar dengan `market.py`.
- Aturan valuasi masuk ke registry aturan yang sudah ada (§7) seperti aturan
  teknikal lainnya.

**Batasan yang mengikat Project 2:** halaman web tidak boleh menjalankan
inferensi IndoBERT secara sinkron di dalam request. Memuat model beberapa ratus
megabyte lalu melakukan inferensi akan menahan request puluhan detik sekaligus
menahan memori di proses web server. Scan tetap dikerjakan proses terjadwal yang
menulis ke SQLite; web membaca hasilnya. Pemicu scan manual menjalankan job
terpisah, bukan bekerja di dalam request.

**Definisi "murah" untuk Project 3:** valuasi, yaitu PER dan PBV rendah — bukan
harga nominal rendah per lembar. Pembedaan ini disengaja: saham berharga nominal
rendah di IDX sebagian besar berlikuiditas tipis dan kerap tidak murah secara
valuasi.

## 3. Keputusan arsitektur

| Keputusan | Pilihan | Alasan |
|---|---|---|
| Lingkungan eksekusi | Lokal / VPS | IndoBERT dimuat in-process; tanpa batas disk dan tanpa biaya API inferensi |
| Struktur | Berlapis: providers / core / notifiers | `core/` bebas I/O sehingga logika keputusan dapat diuji tanpa jaringan |
| Persistensi | SQLite file tunggal | Dedup alert + riwayat scan tanpa server database |
| Strategi teknikal | Aturan pluggable, v1 aktif SMA | Menambah RSI/MACD nanti tanpa mengubah kode |
| Watchlist | File YAML statis | Mudah diedit, aman terhadap kuota NewsAPI |
| Abstraksi provider | Injeksi argumen, bukan ABC formal | Hanya ada satu implementasi per provider; ABC belum berbayar |

**Aturan struktural yang mengikat:** modul di bawah `core/` tidak boleh mengimpor
`yfinance`, `requests`, `transformers`, atau `sqlite3`. Pelanggaran aturan ini
adalah sinyal bahwa logika keputusan sedang bocor ke lapisan I/O.

## 4. Struktur project

```
Scrapping/
├── src/ihsg_screener/
│   ├── __init__.py
│   ├── config.py                  # .env + settings.yaml -> Settings
│   ├── models.py                  # dataclass antar lapisan
│   ├── providers/
│   │   ├── market.py              # yfinance -> DataFrame OHLCV
│   │   ├── news.py                # NewsAPI -> list[Article]
│   │   └── sentiment_engine.py    # memuat & menjalankan IndoBERT
│   ├── core/
│   │   ├── indicators.py          # sma/rsi/macd/bbands, pandas murni
│   │   ├── strategy.py            # aturan aktif -> TechnicalSignal
│   │   ├── textproc.py            # pembersihan, relevansi, pemotongan
│   │   └── sentiment.py           # agregasi skor -> SentimentVerdict
│   ├── notifiers/telegram.py
│   ├── storage/
│   │   ├── schema.sql
│   │   └── repository.py
│   ├── pipeline.py                # orkestrator
│   └── cli.py                     # entry point
├── config/
│   ├── settings.yaml
│   └── watchlist.yaml
├── tests/                         # mencerminkan struktur src/
├── data/scanner.db                # gitignored
├── logs/                          # gitignored
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

Pemisahan sentimen menjadi dua file disengaja: `providers/sentiment_engine.py`
memuat bobot model dan menjalankan inferensi, sedangkan `core/sentiment.py`
hanya menerima daftar `(label, skor)` dan memutuskan verdict. Aturan bisnis
berada di file kedua sehingga dapat diuji tanpa menginstal `torch`.

## 5. Data model (`models.py`)

Semua dataclass bersifat frozen.

```
Ticker            : symbol, name, aliases[]
Article           : title, description, url, source, published_at
TechnicalSignal   : symbol, is_bullish, close, indicators{}, passed_rules[],
                    failed_rules[], as_of
ArticleSentiment  : article, label, score
SentimentVerdict  : label, score, analyzed_count, rejected_count, per_article[]
ScanResult        : symbol, technical?, sentiment?, decision, reason, run_id, ts
```

`Decision` adalah enum:
`BUY_ALERT`, `REJECTED_TECHNICAL`, `REJECTED_SENTIMENT`, `SKIPPED_NO_NEWS`,
`SKIPPED_DUPLICATE`, `SKIPPED_NO_DATA`, `ERROR`.

Setiap emiten dalam watchlist menghasilkan tepat satu `ScanResult` per run,
termasuk yang gagal. Ini memungkinkan pembedaan antara "tidak ada yang bullish"
dan "kuota NewsAPI habis di tengah jalan" — dua kondisi yang sama-sama
menghasilkan nol alert tetapi menuntut respons berbeda.

## 6. Alur eksekusi

```
1. Muat Settings dan watchlist            -> gagal: exit 2
2. Batch download OHLCV (satu panggilan yfinance untuk semua ticker)
3. Cek kesegaran bar terakhir              -> basi: exit 0, "tidak ada data baru"
4. Per ticker: indicators -> strategy.evaluate() -> TechnicalSignal
5. Filter bullish                          -> sisanya REJECTED_TECHNICAL
6. Cek dedup terhadap SQLite               -> dalam cooldown: SKIPPED_DUPLICATE
7. Jika kandidat > 0: muat IndoBERT (lazy)
8. Per kandidat: news -> textproc -> inferensi -> SentimentVerdict
9. Gate AND -> kirim Telegram -> catat ke DB
10. Tulis ringkasan run
```

Dua penempatan yang bersifat menentukan:

- **Dedup dijalankan sebelum pengambilan berita.** Jika dedup ditaruh sebelum
  pengiriman Telegram, kuota NewsAPI dan waktu inferensi tetap terbakar untuk
  alert yang akan dibuang.
- **IndoBERT dimuat malas.** Pada hari tanpa kandidat, run selesai dalam hitungan
  detik tanpa menyentuh `torch`, alih-alih membayar 10-30 detik startup.

## 7. Lapisan teknikal

`core/indicators.py` menghitung SMA, RSI, MACD, dan Bollinger Bands dalam satu
pass pandas. Implementasi menggunakan pandas murni tanpa `pandas-ta` atau
`TA-Lib`: keduanya menambah risiko instalasi di Windows dan kompatibilitas
NumPy, sementara indikator yang dibutuhkan hanya beberapa puluh baris.

`core/strategy.py` mengevaluasi daftar aturan yang diaktifkan lewat
`settings.yaml`. Setiap aturan adalah fungsi `(DataFrame, params) -> bool`
terdaftar dalam registry. v1 mengaktifkan satu aturan:

```yaml
technical:
  min_bars: 60
  lookback_days: 180
  rules:
    sma_cross:
      enabled: true
      fast: 5
      slow: 20
    rsi_not_overbought:
      enabled: false
      period: 14
      max: 70
    macd_bullish:
      enabled: false
      fast: 12
      slow: 26
      signal: 9
```

Emiten dinyatakan bullish bila **semua** aturan yang aktif lulus. Aturan yang
gagal dicatat di `TechnicalSignal.failed_rules` agar alasan penolakan terlihat.

`lookback_days: 180` memberi ruang cukup untuk MACD(26) dan indikator lain yang
mungkin diaktifkan kemudian, bukan sekadar minimum untuk SMA20.

## 8. Lapisan berita & pemrosesan teks

Tersedia dua sumber berita, dipilih lewat `news.source`. Keduanya memakai
antarmuka `fetch(ticker) -> list[Article]` yang sama, sehingga `pipeline.py`
tidak perlu tahu mana yang sedang dipakai.

**`providers/rss_news.py` (bawaan).** Mengambil beberapa feed RSS media
finansial Indonesia **sekali per run**, lalu menyaringnya per emiten dari
kumpulan yang sama. Biayanya karena itu sebanding dengan jumlah feed, bukan
jumlah emiten, dan tidak ada kuota harian. Kegagalan satu feed diisolasi:
feed yang mati, membalas 403, atau mengembalikan XML rusak dicatat sebagai
peringatan dan dilewati, tanpa menjatuhkan sumber lain. Item yang lebih tua
dari `news.max_age_hours` dibuang; item tanpa `pubDate` dipertahankan, karena
lebih baik menilai artikel yang mungkin lama daripada membuang yang mungkin
baru. Parsing memakai `xml.etree.ElementTree` dari pustaka standar, sehingga
tidak menambah dependensi.

**`providers/news.py` (alternatif).** Memanggil NewsAPI `/v2/everything` dengan `language=id`,
diurutkan `publishedAt`, dibatasi `page_size` sesuai konfigurasi. Query dibangun
dari nama perusahaan dan alias, bukan hanya kode ticker, karena pencarian
`"BBRI"` saja memberi recall yang buruk untuk berita Indonesia.

`core/textproc.py` memproses dalam urutan berikut:

1. Buang artikel dengan judul/deskripsi `"[Removed]"` yang dikembalikan NewsAPI
2. Bersihkan tag HTML, entitas, URL, penanda `"… [+1423 chars]"`, dan suffix
   sumber (`" - Detikcom"`, `" | CNBC Indonesia"`)
3. **Filter relevansi:** terima artikel yang menyebut emiten **di judul**;
   penyebutan yang hanya ada di deskripsi diterima juga, kecuali artikelnya
   rangkuman pasar. Artikel yang memuat lebih dari lima kode emiten berbeda
   (empat huruf kapital, di luar akronim seperti `IHSG`/`BUMN`/`RUPS`)
   diperlakukan sebagai rangkuman dan ditolak. RSS memperbesar volume artikel,
   sehingga ia juga memperbesar risiko artikel "asing lego 10 saham ini"
   mendikte verdict satu emiten
4. Gabungkan sebagai `"{judul}. {deskripsi}"` dengan judul di depan
5. Serahkan pemotongan ke tokenizer dengan `truncation=True, max_length=512`

Pemotongan **tidak** dilakukan per karakter. Batas 512 bersatuan token, dan satu
token bahasa Indonesia rata-rata 3-4 karakter; pemotongan karakter memotong di
posisi yang salah. Judul ditempatkan di depan agar yang terbuang saat pemotongan
adalah ekor deskripsi, bagian dengan sinyal sentimen paling sedikit.

Filter relevansi bersifat wajib, bukan opsional: artikel yang menyebut kode
emiten sekali dalam tabel ringkasan pasar akan menghasilkan verdict yang
sebenarnya mengukur sentimen berita lain.

## 9. Lapisan sentimen

`providers/sentiment_engine.py`:
- Memuat pipeline `text-classification` HuggingFace sekali per proses
- Saat inisialisasi, membaca `model.config.id2label` dan memetakannya ke
  `POSITIF` / `NETRAL` / `NEGATIF`
- Bila pemetaan tidak dikenali (misalnya model hanya mengembalikan
  `LABEL_0/1/2`), inisialisasi **gagal dengan pesan eksplisit** alih-alih
  menebak. Tebakan yang salah membalik seluruh gate sentimen tanpa memunculkan
  error apa pun di log.
- Menjalankan inferensi secara batch untuk seluruh artikel satu emiten

`core/sentiment.py` mengagregasi hasil menjadi verdict, dikendalikan konfigurasi:

```yaml
sentiment:
  model: wong39/indobert-sentiment-classifier
  articles_per_ticker: 3
  min_articles: 1
  min_avg_score: 0.60
  neutral_weight: 0.0
  veto_on_strong_negative: true
  strong_negative_threshold: 0.80
```

Aturan agregasi: verdict `POSITIF` bila skor rata-rata berbobot melewati
`min_avg_score`, jumlah artikel relevan memenuhi `min_articles`, dan — bila
`veto_on_strong_negative` aktif — tidak ada satu pun artikel negatif dengan
keyakinan di atas `strong_negative_threshold`. Veto ada karena satu berita buruk
berkeyakinan tinggi (misalnya suspensi atau gagal bayar) tidak boleh tertutup
oleh dua berita positif yang lemah.

Emiten tanpa artikel relevan menghasilkan `SKIPPED_NO_NEWS`, bukan verdict
netral. Ketiadaan berita bukan bukti sentimen apa pun.

## 10. Notifikasi

`notifiers/telegram.py` mengirim pesan ke `sendMessage` berisi ticker, harga
penutupan, aturan teknikal yang lulus beserta nilainya, ringkasan sentimen, dan
tautan ke artikel yang dianalisis.

**Format pesan memakai `parse_mode: HTML`, bukan Markdown.** Nama indikator dan
aturan mengandung underscore (`sma_cross`, `sma_fast`, `sma_slow`), yang di
Markdown Telegram adalah penanda italic. Jumlah underscore yang ganjil membuat
parser gagal menemukan penutupnya dan menolak **seluruh** pesan dengan
`400 Bad Request: can't parse entities`. Ditemukan pada run sungguhan pertama
2026-08-25: setiap alert nyata akan gagal terkirim, sementara seluruh tes unit
tetap hijau karena `format_alert` diuji sebagai string murni dan `send` diuji
terhadap sesi palsu. Di HTML underscore tidak bermakna, dan hanya tiga karakter
yang perlu di-escape.

Pencatatan alert ke database dilakukan **setelah** respons HTTP 200 diterima.
Jika pengiriman gagal, alert tidak ditandai terkirim sehingga muncul kembali di
run berikutnya, alih-alih hilang diam-diam.

## 11. Persistensi

SQLite di `data/scanner.db`.

```sql
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL,      -- ok | degraded | fatal
    scanned      INTEGER DEFAULT 0,
    candidates   INTEGER DEFAULT 0,
    alerts       INTEGER DEFAULT 0,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS scan_results (
    id              INTEGER PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    symbol          TEXT NOT NULL,
    as_of           TEXT NOT NULL,
    decision        TEXT NOT NULL,
    reason          TEXT,
    close           REAL,
    indicators      TEXT,            -- JSON
    sentiment_label TEXT,
    sentiment_score REAL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    symbol      TEXT NOT NULL,
    as_of       TEXT NOT NULL,
    close       REAL NOT NULL,
    payload     TEXT NOT NULL,       -- JSON snapshot lengkap
    sent_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_symbol_sent ON alerts(symbol, sent_at);
CREATE INDEX IF NOT EXISTS idx_scan_run ON scan_results(run_id);
```

Dedup: emiten dilewati bila terdapat baris di tabel `alerts` untuk simbol
tersebut dalam N hari terakhir, dengan N diambil dari kunci `alerts.cooldown_days`
di `settings.yaml`.

## 12. Konfigurasi

`.env` memuat **hanya rahasia**: `NEWSAPI_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`. File `.env.example` disertakan; `.env` masuk `.gitignore`.

`config/settings.yaml` memuat seluruh parameter yang dapat disetel. Blok
`technical` (§7) dan `sentiment` (§9) sudah diuraikan di atas; sisanya:

```yaml
news:
  page_size: 3
  max_requests_per_run: 40      # budget kuota lokal, di bawah 100/hari NewsAPI
  lookback_days: 3
  language: id

alerts:
  cooldown_days: 5              # jeda sebelum simbol yang sama boleh dialert lagi

http:
  timeout_seconds: 15
  retries: 3
  backoff_base_seconds: 2

runtime:
  db_path: data/scanner.db
  log_dir: logs
  lock_file: data/scanner.lock
```

`config/watchlist.yaml`:

```yaml
tickers:
  - symbol: BBRI.JK
    name: Bank Rakyat Indonesia
    aliases: [BBRI, BRI]
  - symbol: TLKM.JK
    name: Telkom Indonesia
    aliases: [TLKM, Telkom]
```

Pemisahan ini disengaja: parameter strategi akan sering diubah, dan itu tidak
boleh berarti mengedit kode atau membuka file yang berisi token.

`config.py` memvalidasi keduanya saat startup dan gagal keras bila ada yang
kurang, bukan gagal belakangan saat hendak mengirim Telegram.

## 13. Penanganan error

Prinsip: satu emiten bermasalah tidak boleh menjatuhkan seluruh run.

| Tingkat | Contoh | Respons |
|---|---|---|
| Fatal | Token kosong, YAML rusak | Abort sebelum kerja apa pun, exit 2 |
| Global terdegradasi | NewsAPI 429, kuota habis | Hentikan tahap berita, sisa kandidat `ERROR`, run tetap diselesaikan, status `degraded`, exit 1 |
| Per-emiten | Data kosong, bar kurang, 0 artikel | Catat `ScanResult` beralasan, lanjut ke emiten berikutnya |
| Transien | Timeout, DNS, 5xx | Retry 3x, exponential backoff + jitter (`tenacity`) |

Ketentuan tambahan:

- **Setiap panggilan HTTP wajib menetapkan `timeout` eksplisit.** Untuk proses
  terjadwal tanpa pengawasan, proses menggantung lebih berbahaya daripada proses
  gagal: yang gagal terlihat di log dan berakhir, yang menggantung menumpuk
  hingga run berikutnya bertabrakan.
- **Budget kuota lokal.** `news.max_requests_per_run` dijaga penghitung di sisi
  aplikasi, sehingga sistem berhenti pada batas yang ditetapkan sendiri, bukan
  karena penolakan NewsAPI di tengah jalan dengan status kandidat yang kabur.
- **Validasi eksplisit hasil `yf.download()` batch.** Ticker tidak valid atau
  delisted tidak melempar exception; kolomnya kembali berisi NaN seluruhnya.
  `providers/market.py` memeriksa jumlah bar dan kesegaran harga penutupan
  secara eksplisit, bukan mengandalkan try/except.
- **Pembungkus terluar.** `pipeline.run()` dibungkus penangkap exception yang
  tetap menulis ringkasan run ke DB dan log apa pun yang terjadi.

## 14. Pengujian

`pytest`, struktur `tests/` mencerminkan `src/`. Aturan tunggal: **tidak ada tes
yang menyentuh jaringan.**

- `core/indicators.py` diuji terhadap nilai yang dihitung manual pada deret
  sintetis, bukan terhadap outputnya sendiri
- `core/strategy.py` diuji dengan DataFrame yang dirancang untuk melewati dan
  menggagalkan tiap aturan
- `core/textproc.py` diuji dengan judul berisi HTML, URL, penanda potongan
  NewsAPI, dan artikel tidak relevan
- `core/sentiment.py` diuji dengan daftar `(label, skor)` sintetis, termasuk
  kasus veto negatif kuat
- `providers/` diuji dengan fixture JSON hasil rekaman respons asli
- `pipeline.py` diuji end-to-end dengan provider palsu yang disuntikkan; inilah
  yang membuktikan gate AND menolak kombinasi bullish + sentimen negatif
- Tes yang membutuhkan jaringan ditandai `@pytest.mark.integration` dan dilewati
  secara default

## 15. Otomatisasi & operasional

CLI:

| Flag | Fungsi |
|---|---|
| `--dry-run` | Jalankan penuh, tampilkan hasil, tanpa kirim Telegram dan tanpa tulis DB |
| `--tickers BBRI,TLKM` | Batasi ke emiten tertentu |
| `--force` | Abaikan dedup |
| `--verbose` | Log level DEBUG |
| `--config PATH` | Lokasi settings alternatif |

Operasional:
- **Lock file** mencegah dua run tumpang tindih
- **Logging** ke `logs/` dengan rotasi harian, sekaligus ke stdout
- **Exit code**: `0` normal, `1` selesai tetapi terdegradasi, `2` fatal
- **Penjadwalan**: Windows Task Scheduler memanggil wrapper `.bat`; di VPS,
  entri cron setara

**Penanganan hari libur bursa** dilakukan dengan memeriksa tanggal bar terakhir,
bukan dengan memelihara kalender libur IDX. Bila data terbaru bukan berasal dari
hari perdagangan yang diharapkan, run berhenti lebih awal dengan status "tidak
ada data baru". Satu pemeriksaan ini menangani akhir pekan, libur nasional, dan
cuti bersama sekaligus, tanpa pemeliharaan tahunan.

**Waktu jalan yang disarankan: 18:00-19:00 WIB.** IDX tutup pukul 16:00 dan data
EOD yfinance membutuhkan waktu untuk mengendap; menjalankan pukul 16:05 berisiko
memperoleh bar yang belum final.

## 16. Dependensi

Runtime: `yfinance`, `pandas`, `requests`, `transformers`, `torch`,
`pyyaml`, `python-dotenv`, `tenacity`

Pengembangan: `pytest`, `pytest-cov`, `ruff`

Python 3.12 (terpasang: 3.12.6). Dependensi dikelola lewat `pyproject.toml`,
dipasang dengan `pip install -e ".[dev]"`.

## 17. Risiko & asumsi yang perlu diverifikasi saat implementasi

1. ~~**Ketersediaan model.**~~ **TERSELESAIKAN 2026-08-25 — risiko terbukti.**
   `wong39/indobert-sentiment-classifier` **tidak ada** di HuggingFace Hub.
   Penggantinya: `intanm/indonesian_financial_sentiment_analysis`
   (`id2label: {0: NEGATIVE, 1: NEUTRAL, 2: POSITIVE}`), dipilih setelah menguji
   tiga kandidat pada judul berita saham Indonesia.

   Dua catatan dari pengujian itu yang layak diingat:

   - Kandidat terpopuler, `w11wo/indonesian-roberta-base-sentiment-classifier`
     (85.513 unduhan), menjawab NETRAL untuk **seluruh** enam judul uji dengan
     keyakinan di atas 0,98 — termasuk suspensi saham dan gagal bayar obligasi.
     Memilih berdasarkan popularitas akan menghasilkan gate sentimen yang
     meloloskan segalanya tanpa memunculkan satu pun error.
   - `apriandito/indobert-sentiment-classifier` dan
     `intanm/indonesian_financial_sentiment_analysis` sama-sama benar 5 dari 6,
     tetapi salah di tempat berbeda. `apriandito` menilai *"BEI suspensi saham
     WSKT karena gagal bayar obligasi"* sebagai NETRAL (0,97), sehingga veto
     tidak akan aktif justru pada kasus yang veto itu ada untuknya.
     `intanm` menangkapnya (NEGATIVE 0,90) dan hanya melewatkan berita dividen.
     Arah kesalahan menentukan pilihan: melewatkan peluang jauh lebih murah
     daripada meloloskan saham bermasalah ke dalam sinyal beli.

   Nama model tetap bersifat konfigurasi, sehingga penggantian di kemudian hari
   tidak menyentuh kode.
2. **Recall NewsAPI.** **TERBUKTI BERMASALAH 2026-08-25 — belum terselesaikan.**
   Probe langsung terhadap tier gratis:

   | query | `language=id` | rentang | hasil |
   |---|---|---|---|
   | `"Bank Rakyat Indonesia" OR BBRI OR BRI` | ya | 3 hari | 1 |
   | `"Bank Rakyat Indonesia" OR BBRI OR BRI` | ya | 25 hari | 13 |
   | `BBRI` | ya | 25 hari | **0** |
   | `saham` | ya | 3 hari | **0** |
   | `Indonesia` | ya | 3 hari | 32 |
   | `Indonesia` | tidak | 3 hari | 187 |

   Kata `saham` sendiri tidak mengembalikan apa pun dalam tiga hari: cakupan
   berita pasar modal berbahasa Indonesia di tier gratis praktisnya kosong.
   Kode emiten saja juga nihil, mengonfirmasi keputusan §8 untuk menyertakan
   nama perusahaan dalam query.

   Akibatnya gate sentimen kelaparan: pada scan nyata 2026-08-25, dua dari tiga
   kandidat bullish berakhir `SKIPPED_NO_NEWS`.

   **TERSELESAIKAN 2026-08-25** dengan `providers/rss_news.py`, sumber berita
   berbasis RSS media finansial Indonesia. Pada watchlist yang sama:

   | emiten | NewsAPI (3 hari) | RSS (5 feed) |
   |---|---:|---:|
   | BBRI | 1 | 6 |
   | BBCA | 0 | 1 |
   | TLKM | 0 | 3 |
   | ASII | 0 | 1 |
   | ANTM | 0 | 8 |

   Setelah RSS diaktifkan, tidak ada lagi kandidat yang berakhir
   `SKIPPED_NO_NEWS`. Biayanya pun berubah sifat: satu permintaan per feed per
   run, bukan satu per emiten, sehingga watchlist 45 emiten tetap memerlukan
   lima permintaan HTTP dan tidak ada kuota harian yang bisa habis.

   `NewsProvider` tetap dipertahankan dan dapat dipilih lewat `news.source`.
3. ~~**Kualitas data yfinance untuk saham IDX.**~~ **TERSELESAIKAN 2026-08-25.**
   Kelima emiten watchlist awal (BBRI, BBCA, TLKM, ASII, ANTM) mengembalikan 175
   bar bersih dan lolos validasi; gate teknikal berjalan normal di atasnya.
   Emiten berlikuiditas rendah belum diuji dan masih perlu diperhatikan saat
   watchlist diperluas.
4. **Ambang sentimen belum terkalibrasi.** `min_avg_score: 0.60` adalah titik
   awal, bukan nilai tervalidasi. Riwayat di `scan_results` menjadi dasar
   kalibrasi setelah sistem berjalan beberapa minggu.
5. **Ketersediaan data fundamental untuk Project 3.** Field valuasi yfinance
   (`trailingPE`, `priceToBook`) kerap kosong atau basi untuk emiten IDX, dan
   endpoint `.info` tidak sestabil data harga. Perlu diuji terhadap sampel
   watchlist sebelum Project 3 direncanakan; bila cakupannya tidak memadai,
   sumber data fundamental alternatif menjadi keputusan tersendiri.

## 18. Kriteria selesai v1

- `pytest` lulus seluruhnya tanpa akses jaringan
- `--dry-run` menghasilkan keputusan yang benar untuk watchlist penuh
- Satu alert nyata terkirim ke Telegram dan tercatat di `alerts`
- Run kedua di hari yang sama tidak mengirim alert duplikat
- Menjalankan tanpa internet berakhir dengan exit code bermakna dan log jelas,
  tanpa traceback yang tidak tertangani
- README memuat langkah instalasi, konfigurasi, dan penjadwalan
