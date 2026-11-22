# go24 technology

Instagram sayfası **go24 technology** için otomatik teknoloji haberleri: Karadağca + İngilizce, her gün akış gönderisi ve hikâye.

## Nasıl çalışır

1. **İçerik (Claude, her sabah):** Haberleri seçer, iki kaynaktan doğrular, iki dilde yazar ve `drafts/<tarih>.json` dosyasını bu depoya yükler.
2. **Görseller (GitHub Actions, taslak gelince):** `.github/workflows/build.yml` fotoğrafları indirir (resmi basın görseli ya da Pexels/Unsplash), kartları üretir (`media/<tarih>/`), yayın sırasını yazar (`queue/<tarih>.json`) ve `media/<tarih>/preview.jpg` önizlemesini çıkarır.
3. **Yayın (GitHub Actions, her 15 dakikada bir):** `.github/workflows/publish.yml`, saati gelen gönderiyi Instagram'ın resmi API'siyle paylaşır ve sonucu `state/published.json` dosyasına yazar.

## Klasörler

| Klasör | İçerik |
| --- | --- |
| `go24/render.py` | Haber kartı şablonları (akış 1080×1350, hikâye 1080×1920) |
| `go24/build_day.py` | Günün taslağından görselleri ve yayın sırasını üretir |
| `go24/images.py` | Haber fotoğrafını indirir (resmi basın sayfasının görseli ya da doğrudan bağlantı) |
| `drafts/` | Claude'un günlük taslakları |
| `go24/publish.py` | Instagram'a paylaşan program |
| `config.json` | Saatler, saat dilimi, onay modu |
| `queue/` | Yayın sırası |
| `media/` | Paylaşılacak görseller |
| `state/` | Neyin paylaşıldığı; yenilenen anahtar şifreli olarak (`token.enc`) |
| `brand/logo.png` | Logo (varsa yazı yerine kullanılır) |

## Gizli bilgiler (Settings → Secrets and variables → Actions)

- `IG_ACCESS_TOKEN`: Meta uygulamasından alınan uzun süreli Instagram erişim anahtarı.
- `TOKEN_KEY`: Uzun, rastgele bir cümle. Anahtar her hafta otomatik yenilenir ve bununla şifrelenip saklanır.

Anahtar hiçbir zaman depoya açık olarak yazılmaz ve kayıtlarda görünmez.

## Elle kullanım

- **Test / hemen paylaş:** Actions → *Publish to Instagram* → *Run workflow* → `post_id` alanına gönderinin kimliğini yaz.
- **Ne paylaşılacağını görmek:** Aynı yerde *dry run* kutusunu işaretle.
- **Durdurmak:** Actions → *Publish to Instagram* → `...` → *Disable workflow*.
- **Onay modu (şu an açık):** `config.json` içinde `"require_approval": true` iken yalnızca `queue/` içinde `"approved": true` işaretli gönderiler paylaşılır. İlk günler birlikte kontrol ediyoruz; sonra `false` yapılacak.

## Saatler (Europe/Podgorica)

Akış: 12:30 · Hikâyeler: 08:30, 11:30, 15:30, 19:30. `config.json` içinden değiştirilebilir.

Yazı tipi: Inter (SIL Open Font License 1.1), bkz. `fonts/LICENSE-Inter.txt`.
