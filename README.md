# Telegram Channel Random Reaction Bot

Beberapa bot memasang **satu reaction acak per bot** pada setiap post baru di satu channel Telegram. Jumlah bot mengikuti jumlah token di `TG_TOKENS`.

Emoji diambil dari `reactions.txt`. Bot memilih dari emoji yang memang diizinkan di channel, jadi reaction tidak ditolak karena setting channel.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/arfinstar22/bot-reaction)

## Cara kerja

- Bot 1 menjadi **controller**: di Render otomatis memakai **webhook** (`RENDER_EXTERNAL_URL/webhook`) supaya Telegram langsung membangunkan service dan mengirim `channel_post` walau service sempat tidur; di VPS/lokal memakai polling `getUpdates` dengan `allowed_updates=["channel_post"]`.
- Setiap bot memanggil `setMessageReaction` dengan token sendiri, satu reaction per post.
- Hanya bot 1 yang menerima update (webhook/polling). Bot lain tidak perlu polling atau webhook.
- Semua bot harus admin channel. Bot tidak bisa menjadi subscriber biasa di channel.
- Emoji difilter dengan `available_reactions` channel. Kalau channel hanya mengizinkan sebagian emoji, hanya bagian itu yang dipakai.
- Jumlah **jenis emoji unik** dibatasi `max_reaction_count` channel (secara default disisakan 1 slot lewat `RESERVE_SLOTS=1`, jadi dari limit 11 dipakai maksimal 10 jenis agar 1 bot dari `projectTumbnail` tidak bentrok). Kalau jumlah bot lebih banyak dari batas jenis itu, semua bot tetap ikut bereaksi dengan menumpuk emoji dari jenis yang terpilih.
- Bot hanya bereaksi pada post **rich article** dari projectTumbnail, yaitu post yang punya field `rich_message`. Stiker, teks biasa, foto, video, album, dan service message dilewati.
- Post yang sudah ada sebelum bot start dilewati. Bot hanya bereaksi ke post baru selama bot berjalan. Post saat bot mati tidak diproses ulang.
- Di Render, bot membuka port HTTP kecil untuk health check dan keepalive. Di Fly.io atau VPS, port tidak dibuka kalau `PORT` kosong.

## Setup

### 1. Buat bot

Buka [@BotFather](https://t.me/BotFather), jalankan `/newbot` untuk setiap bot. Simpan semua token. Token harus berbeda; token duplikat ditolak saat start.

Jumlah bot bebas (batas admin channel Telegram 50 akun). Channel dengan limit 11 membatasi **11 jenis emoji unik** per post, bukan total bot, jadi 20 bot di repo ini + 1 bot di `projectTumbnail` bisa semuanya aktif dengan sebagian emoji bertumpuk (x2, x3, dst.). Set `RESERVE_SLOTS=0` di `.env` jika tidak perlu menyisakan 1 slot untuk bot lain.

**Menambah bot nanti** tidak perlu ubah kode:

1. Buat bot baru lewat @BotFather.
2. Tambahkan bot itu sebagai admin channel.
3. Tambahkan tokennya ke `TG_TOKENS`, tetap dipisah koma.
4. Simpan env dan redeploy. Jumlah reaction otomatis mengikuti jumlah token.

### 2. Isi konfigurasi

```bash
cd /home/darfinstar/projectReactionBot
cp .env.example .env
nano .env
```

Isi `TG_TOKENS` dengan semua token, dipisah koma:

```dotenv
TG_TOKENS=111:AAA,222:BBB,333:CCC,444:DDD,555:EEE
CHANNEL_ID=@nama_channel
```

- Channel publik: isi `@username`.
- Channel privat: isi ID lengkap dengan prefix `-100`, contoh `CHANNEL_ID=-1001234567890`.
- Kalau belum tahu ID: kosongkan `CHANNEL_ID`, posting satu kali, lihat `id=-100...` di log, lalu isi dan restart.
- Angka polos seperti `3955448047` bukan ID channel. Telegram memakai `-1003955448047`.
- Kalau `CHANNEL_ID` kosong, bot memproses channel apa pun yang mengirim `channel_post`. Isi `CHANNEL_ID` kalau bot dipasang di lebih dari satu channel.

### 3. Tambahkan semua bot sebagai admin

Buka channel:

```text
Channel > Administrators > Add Admin
```

Tambahkan semua bot. Permission boleh dikosongkan. Yang penting statusnya admin, bukan member biasa.

### 4. Atur reaction channel

Buka:

```text
Channel > Reactions
```

- Pilih **All reactions**, atau **Selected reactions** yang memuat emoji dari `reactions.txt`.
- Set **Maximum Number of Reactions** ke **11** (batas maksimal channel Telegram). Secara default bot menyisakan 1 slot (`RESERVE_SLOTS=1`) sehingga maksimal 10 jenis dipakai oleh bot di repo ini dan 1 slot aman untuk bot `projectTumbnail` / subscriber.
- Kalau limit di bawah jumlah bot, semua bot tetap bereaksi dengan menumpuk emoji pada jenis yang tersedia.

### 5. Install dan jalankan

```bash
cd /home/darfinstar/projectReactionBot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python bot.py
```

Saat start, bot akan:

- login semua token,
- menghapus webhook bot controller,
- mengecek apakah semua bot admin channel (kalau `CHANNEL_ID` diisi),
- menampilkan jumlah emoji yang cocok dan limit reaction per post.

### 6. Deploy gratis di Oracle Cloud Always Free

Oracle Always Free memberi VM yang selalu hidup tanpa biaya bulanan. Kartu dipakai untuk verifikasi akun. Jangan upgrade ke Pay As You Go dan jangan buat resource di luar kuota Always Free.

**Risiko reclaim:** Oracle boleh menghentikan instance Always Free yang dianggap idle. Bot ini ringan, jadi CPU dan network-nya kecil. Instance bisa dihentikan Oracle setelah 7 hari idle. Kalau butuh jaminan lebih besar, pakai Render free + cron di bagian berikut.

1. Buat akun Oracle Cloud. Pilih home region terdekat. Jangan upgrade akun.

2. Buka **Compute > Instances > Create instance**:

```text
Image: Ubuntu 24.04
Shape: VM.Standard.E2.1.Micro (AMD) atau VM.Standard.A1.Flex 1 OCPU / 6 GB (ARM)
SSH key: tambahkan public key milikmu
Public IPv4: yes
```

3. Masuk ke VM:

```bash
ssh ubuntu@<public-ip>
```

4. Install bot:

```bash
sudo apt update
sudo apt install -y git python3-venv
git clone https://github.com/arfinstar22/bot-reaction.git
cd bot-reaction
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env
```

Isi `TG_TOKENS` dengan semua token dan `CHANNEL_ID` dengan `@nama_channel`.

5. Pasang service:

```bash
bash install-service.sh
```

Script membuat unit systemd sesuai user dan path VM, lalu enable dan start service.

6. Lihat log:

```bash
journalctl -u reactionbot -f
```

Cari `login @bot...`, `admin ok`, dan `menunggu post baru`. Kalau `CHANNEL_ID` kosong, posting satu kali lalu salin `id=-100...` dari log ke `.env`, kemudian:

```bash
sudo systemctl restart reactionbot
```

Oracle hanya butuh port SSH 22 masuk. Bot memakai koneksi keluar untuk long polling; tidak perlu membuka port 80 atau 443.

Untuk update kode:

```bash
cd ~/bot-reaction
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart reactionbot
```

### 7. Alternatif gratis: Render (webhook otomatis)

Render Free Web Service tidur setelah 15 menit tanpa inbound traffic. Di Render, `RENDER_EXTERNAL_URL` terisi otomatis sehingga bot langsung memakai mode **webhook** (`/webhook`). Saat ada post baru di channel, Telegram langsung mengirim request ke `/webhook` untuk membangunkan service dan memproses reaction tanpa kehilangan post.

Batas free Render:

- **750 instance hours/bulan** per workspace. Dengan mode webhook tanpa cron 24/7, service boleh tidur saat tidak ada post sehingga hemat kuota jam gratis (penting jika akun Render juga menjalankan bot lain seperti `projectTumbnail`).
- Tidak perlu kartu kredit.
- Cold start setelah tidur sekitar 15-60 detik; Telegram otomatis mengulang pengiriman webhook jika request pertama timeout saat container masih booting.

1. Buka Render Dashboard, pilih **New > Blueprint**, lalu hubungkan repo `arfinstar22/bot-reaction`. Render membaca `render.yaml` dan membuat web service free di region Singapura.

2. Saat diminta, isi environment variable:

```text
TG_TOKENS=111:AAA,222:BBB,333:CCC,444:DDD,555:EEE
CHANNEL_ID=@nama_channel
```

Jangan taruh token di `render.yaml` atau repo.

3. Tunggu deploy selesai. Salin URL service, bentuknya `https://<nama>.onrender.com`.

4. (Opsional) Kalau ingin respons instan tanpa cold start dan kuota 750 jam masih cukup, buat ping eksternal ke `https://<nama>.onrender.com/` tiap 10 menit lewat [cron-job.org](https://cron-job.org) atau UptimeRobot.

Cek manual dulu:

```bash
curl -i https://<nama>.onrender.com/
```

Harus balas `200 ok`.

5. Cek log Render. Cari baris:

```text
health server di port ...
login @bot...
mode webhook aktif: https://<nama>.onrender.com/webhook
admin ok
webhook siap; menunggu post baru
```

Kalau `TG_TOKENS` kosong atau berisi token duplikat, proses berhenti dan log menampilkan error. Perbaiki environment variable lalu deploy ulang.

**Catatan free 100%:** Render tidak meminta kartu untuk free web service. Ini kebijakan Render dan bisa berubah. Jika ingin memaksa mode polling di Render, set `WEBHOOK_URL=polling`.

### 8. Alternatif: Fly.io

Fly.io **bukan free 100%**. Butuh kartu kredit setelah trial. Mesin terkecil `shared-cpu-1x` 256MB sekitar **US$2.19/bulan** di AS, **US$2.78/bulan** di Singapura. Fly membebaskan tagihan personal di bawah **US$5/bulan**, tapi kebijakan itu bisa berubah. Pakai jalur ini hanya kalau setuju dengan syarat kartu.

1. Login:

```bash
flyctl auth login
```

2. Ganti `app = "..."` di `fly.toml` dengan nama unik global. Lalu buat app dengan nama yang sama:

```bash
flyctl apps create reactionbot-darfinstar
```

3. Set token sebagai secrets. Jangan taruh token di `fly.toml`:

```bash
flyctl secrets set TG_TOKENS='111:AAA,222:BBB,333:CCC,444:DDD,555:EEE' CHANNEL_ID='@nama_channel'
```

Kalau `CHANNEL_ID` mau dikosongkan, hilangkan bagian `CHANNEL_ID=...`.

4. Deploy:

```bash
flyctl deploy
```

Build dilakukan di server Fly. Docker lokal tidak perlu jalan.

5. Cek status dan log:

```bash
flyctl status
flyctl logs
```

Fly menjalankan satu Machine 256MB tanpa port HTTP. Machine ini hidup terus, jadi bot tidak tidur seperti Render free.

### 9. Alternatif lain

- **Oracle Cloud Always Free**: VM ARM yang selalu hidup. Jalankan bot dengan systemd seperti di bawah. Butuh kartu untuk verifikasi dan setup SSH.
- **Cloudflare Workers**: gratis dan selalu hidup, tapi bot harus diubah dari long polling ke webhook. Bukan pengganti langsung untuk kode ini.

### 10. Jalankan permanen di VPS dengan systemd

Edit `reactionbot.service` kalau user atau path berbeda. Lalu:

```bash
sudo cp reactionbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now reactionbot
journalctl -u reactionbot -f
```

## Mengubah daftar emoji

Edit `reactions.txt`, satu emoji per baris. Baris `#` adalah komentar. Restart bot setelah mengubah file.

Bot memilih hingga `max_reaction_count - RESERVE_SLOTS` jenis emoji unik per post (default maksimal 10 jenis jika limit channel 11). Kalau jumlah bot lebih banyak dari batas jenis tersebut, tiap bot mengambil acak dari jenis yang sudah terpilih sehingga beberapa emoji muncul bertumpuk. Kalau daftar yang diizinkan channel lebih sedikit, bot memakai sebanyak yang tersedia.

## Test

```bash
.venv/bin/python -m unittest -v
```

## Troubleshooting

**`409 Conflict`**
Ada proses lain yang polling bot controller, atau webhook masih aktif. Hentikan proses lain. Script menghapus webhook controller otomatis saat start.

**`401 Unauthorized`**
Token salah atau sudah di-revoke. Buat token baru lewat BotFather.

**`400 Bad Request: chat not found`**
`CHANNEL_ID` salah. Channel numerik wajib memakai prefix `-100`, contoh `-1003955448047`, bukan `3955448047`. Pastikan juga semua bot sudah admin channel.

**`CHAT_ADMIN_REQUIRED` atau `not enough rights`**
Bot belum admin channel. Tambahkan lewat `Channel > Administrators`.

**`REACTION_INVALID`**
Emoji tidak diizinkan di channel. Aktifkan emoji itu di `Channel > Reactions`, atau hapus dari `reactions.txt`.

**Reaction cuma muncul 3 atau 4**
Cek **Maximum Number of Reactions** di channel. Set minimal 5.

**Bot tidak menerima post**
Pastikan Bot 1 admin channel. `channel_post` hanya dikirim ke admin.

**Render balas `502` atau service tidur**
Ping cron tidak berjalan atau URL salah. Cek job cron, lalu buka URL health secara manual. Service free butuh inbound traffic sebelum 15 menit.

**`MESSAGE_ID_INVALID`**
Post sudah dihapus atau itu service message yang tidak bisa direaction. Error ini aman diabaikan.

## Keamanan

`.env` berisi token bot. Jangan commit ke Git. Kalau token bocor, revoke lewat `/revoke` di BotFather.

## File

```text
bot.py                program utama + health endpoint
reactions.txt         daftar emoji
test_bot.py           unit test logika filter, pemilihan emoji, dan health endpoint
.env.example          contoh konfigurasi
install-service.sh    installer systemd untuk Oracle/VPS
render.yaml           blueprint Render free web service
Dockerfile            image untuk Fly.io
fly.toml              konfigurasi app Fly.io
.dockerignore         file yang tidak masuk image
reactionbot.service   unit systemd manual untuk VPS
requirements.txt      dependency Python
```
