# IHSG Screener

Screener harian saham Bursa Efek Indonesia. Mengirim BUY ALERT ke Telegram hanya
bila kondisi teknikal bullish **dan** sentimen berita positif menurut IndoBERT.

Ini screener pasca-market untuk ditinjau manusia, bukan sistem eksekusi order.

## Instalasi

```bash
python -m pip install -e ".[dev]"
copy .env.example .env
```

Isi `.env` dengan API key NewsAPI, token bot Telegram, dan Chat ID tujuan.

Catatan: `torch` versi default PyPI membundel CUDA (~2,5 GB). Untuk beban kerja
ini GPU tidak memberi manfaat apa pun, jadi wheel CPU-only sudah cukup dan jauh
lebih kecil:

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

## Konfigurasi

- `config/watchlist.yaml` — daftar emiten beserta nama perusahaan dan alias untuk
  pencarian berita. Nama perusahaan wajib: mencari hanya dengan kode emiten
  memberi recall berita yang buruk.
- `config/settings.yaml` — parameter strategi, ambang sentimen, cooldown, sumber
  berita, timeout. Semua yang biasa disetel ada di sini; kode tidak perlu disentuh.

### Sumber berita

`news.source` menentukan dari mana berita diambil:

- **`rss` (bawaan)** — feed media finansial Indonesia (Kontan, CNBC Indonesia,
  Detik Finance, Tempo, Liputan6). Gratis, tanpa kuota, tanpa delay. Feed
  diambil sekali per run lalu disaring per emiten, jadi biayanya tidak bertambah
  saat watchlist diperbesar. Tambah atau kurangi feed lewat `news.feeds`.
- **`newsapi`** — memerlukan `NEWSAPI_KEY`. Tersedia, tetapi cakupan berita
  pasar modal berbahasa Indonesia pada tier gratis sangat tipis: pada pengujian
  2026-08-25, kata "saham" tidak mengembalikan satu artikel pun dalam tiga hari.

Mengaktifkan indikator tambahan cukup mengubah `enabled: true` pada aturan yang
diinginkan di bawah `technical.rules`. Emiten dinyatakan bullish hanya bila
seluruh aturan aktif lulus.

## Penggunaan

```bash
python -m ihsg_screener.cli --dry-run          # tanpa kirim & tanpa tulis DB
python -m ihsg_screener.cli --tickers BBRI     # batasi ke emiten tertentu
python -m ihsg_screener.cli --force            # abaikan cooldown dedup
python -m ihsg_screener.cli                    # run sesungguhnya
```

Gunakan `--dry-run` setiap kali mengubah parameter strategi: hasilnya terlihat
tanpa mengotori riwayat maupun mengirim notifikasi.

## Exit code

| Kode | Arti |
|---|---|
| 0 | Normal (termasuk hari libur bursa: tidak ada data baru) |
| 1 | Selesai tetapi terdegradasi (mis. kuota NewsAPI habis) |
| 2 | Fatal (konfigurasi tidak valid, model tidak dapat dipakai, run lain aktif, kesalahan tak terduga) |

## Penjadwalan

Windows Task Scheduler, jalankan `run_scanner.bat` pukul 18:00 WIB Senin–Jumat.
IDX tutup pukul 16:00 dan data EOD butuh waktu mengendap; menjalankan pukul 16:05
berisiko memperoleh bar yang belum final.

Hari libur bursa tidak perlu didaftarkan: sistem memeriksa umur bar terbaru dan
berhenti lebih awal bila datanya belum diperbarui.

Di Linux/VPS:

```cron
0 18 * * 1-5 cd /path/ke/Scrapping && python -m ihsg_screener.cli >> logs/cron.log 2>&1
```

## Pengujian

```bash
python -m pytest                      # seluruh tes, tanpa jaringan
python -m pytest -m integration       # verifikasi model & API asli
```

Tidak ada tes biasa yang menyentuh jaringan.

## Arsitektur

```
providers/  → menyentuh dunia luar (yfinance, NewsAPI, IndoBERT)
core/       → logika murni, tanpa I/O — di sinilah keputusan dibuat
notifiers/  → Telegram
storage/    → SQLite: riwayat scan, alert, dedup
pipeline.py → merangkai semuanya; provider disuntikkan sebagai argumen
```

`core/` tidak boleh mengimpor pustaka jaringan; aturan ini ditegakkan oleh
`tests/test_architecture.py`.

Design lengkap: `docs/superpowers/specs/2026-08-25-ihsg-screener-design.md`
