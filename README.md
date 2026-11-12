# Telegram Channel Random Reaction Bot

Lima bot memasang **5 reaction acak yang berbeda** pada setiap post baru di satu channel Telegram.

Emoji diambil dari `reactions.txt`. Bot memilih dari emoji yang memang diizinkan di channel, jadi reaction tidak ditolak karena setting channel.

## Cara kerja

- Bot 1 menjadi **controller**: polling `getUpdates` dengan `allowed_updates=["channel_post"]`.
- Bot 1 sampai Bot 5 masing-masing memanggil `setMessageReaction` dengan token sendiri.
- Bot 2 sampai Bot 5 tidak perlu polling atau webhook.
- Kelima bot tetap harus admin channel. Bot tidak bisa menjadi subscriber biasa di channel.
- Emoji difilter dengan `available_reactions` channel. Kalau channel hanya mengizinkan sebagian emoji, hanya bagian itu yang dipakai.
- Post yang sudah ada sebelum bot start dilewati. Bot hanya bereaksi ke post baru selama bot berjalan. Post saat bot mati tidak diproses ulang.
- Di Render, bot membuka port HTTP kecil untuk health check dan keepalive. Di Fly.io atau VPS, port tidak dibuka kalau `PORT` kosong.

## Setup

### 1. Buat 5 bot

Buka [@BotFather](https://t.me/BotFather), jalankan `/newbot` lima kali. Simpan lima token. Kelima bot harus berbeda; token duplikat ditolak saat start.

### 2. Isi konfigurasi

```bash
cd /home/darfinstar/projectReactionBot
cp .env.example .env
nano .env
```

Isi `TG_TOKENS` dengan lima token, dipisah koma:

```dotenv
TG_TOKENS=111:AAA,222:BBB,333:CCC,444:DDD,555:EEE
CHANNEL_ID=@nama_channel
```

- Channel publik: isi `@username`.
- Channel privat: kosongkan dulu `CHANNEL_ID`, jalankan bot, posting satu kali, lalu lihat `id=-100...` di log. Setelah itu isi `CHANNEL_ID` dan restart.
- Kalau `CHANNEL_ID` kosong, bot memproses channel apa pun yang mengirim `channel_post`. Isi `CHANNEL_ID` kalau bot dipasang di lebih dari satu channel.

### 3. Tambahkan kelima bot sebagai admin

Buka channel:

```text
Channel > Administrators > Add Admin
```

Tambahkan kelima bot. Permission boleh dikosongkan. Yang penting statusnya admin, bukan member biasa.

### 4. Atur reaction channel

Buka:

```text
Channel > Reactions
```

- Pilih **All reactions**, atau **Selected reactions** yang memuat emoji dari `reactions.txt`.
- Set **Maximum Number of Reactions** minimal **5**. Lebih aman **10**, supaya reaction subscriber tidak berebut slot dengan bot.
- Kalau limit di bawah 5, bot hanya bisa memasang sebanyak limit tersebut.

### 5. Install dan jalankan

```bash
cd /home/darfinstar/projectReactionBot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python bot.py
```

Saat start, bot akan:

- login kelima token,
- menghapus webhook bot controller,
- mengecek apakah kelima bot admin channel (kalau `CHANNEL_ID` diisi),
- menampilkan jumlah emoji yang cocok dan limit reaction per post.

### 6. Deploy gratis 100% di Render

Render Free Web Service tidur setelah 15 menit tanpa inbound traffic. Bot ini sekarang membuka health endpoint di `/`, jadi service bisa dijaga tetap hidup dengan ping eksternal setiap 10 menit.

Batas free Render:

- **750 instance hours/bulan**. Satu service yang selalu hidup memakai sekitar 730-744 jam, jadi masih muat.
- Tidak perlu kartu kredit.
- Cold start setelah restart sekitar 1 menit. Post saat bot mati tidak diproses ulang.
- Render bisa menangguhkan free service yang membanjiri traffic. Bot ini hanya long polling, jadi traffic-nya kecil.

1. Buka Render Dashboard, pilih **New > Blueprint**, lalu hubungkan repo `arfinstar22/bot-reaction`. Render membaca `render.yaml` dan membuat web service free di region Singapura.

2. Saat diminta, isi environment variable:

```text
TG_TOKENS=111:AAA,222:BBB,333:CCC,444:DDD,555:EEE
CHANNEL_ID=@nama_channel
```

Jangan taruh token di `render.yaml` atau repo.

3. Tunggu deploy selesai. Salin URL service, bentuknya `https://<nama>.onrender.com`.

4. Buat ping eksternal supaya service tidak tidur. Pakai [cron-job.org](https://cron-job.org) atau UptimeRobot:

```text
URL: https://<nama>.onrender.com/
Method: GET
Interval: setiap 10 menit
```

Cek manual dulu:

```bash
curl -i https://<nama>.onrender.com/
```

Harus balas `200 ok`. Kalau cron berjalan, Render melihat inbound traffic sebelum batas 15 menit dan service tetap hidup.

5. Cek log Render. Cari baris:

```text
health server di port ...
login @bot...
admin ok
menunggu post baru
```

Kalau `TG_TOKENS` kosong atau jumlahnya bukan 5, proses berhenti dan log menampilkan error. Perbaiki environment variable lalu deploy ulang.

**Catatan free 100%:** Render tidak meminta kartu untuk free web service. Ini kebijakan Render dan bisa berubah. Ping keepalive bukan garansi uptime; kalau Render restart atau cron telat, post selama downtime tidak diproses ulang.

### 7. Alternatif: Fly.io

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

### 8. Alternatif gratis

- **Oracle Cloud Always Free**: VM ARM yang selalu hidup. Jalankan bot dengan systemd seperti di bawah. Butuh kartu untuk verifikasi dan setup SSH.
- **Cloudflare Workers**: gratis dan selalu hidup, tapi bot harus diubah dari long polling ke webhook. Bukan pengganti langsung untuk kode ini.

### 9. Jalankan permanen di VPS dengan systemd

Edit `reactionbot.service` kalau user atau path berbeda. Lalu:

```bash
sudo cp reactionbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now reactionbot
journalctl -u reactionbot -f
```

## Mengubah daftar emoji

Edit `reactions.txt`, satu emoji per baris. Baris `#` adalah komentar. Restart bot setelah mengubah file.

Bot memilih 5 emoji **berbeda** secara acak per post. Kalau daftar yang diizinkan channel kurang dari 5, bot memakai sebanyak yang tersedia.

## Test

```bash
.venv/bin/python -m unittest -v
```

## Troubleshooting

**`409 Conflict`**
Ada proses lain yang polling bot controller, atau webhook masih aktif. Hentikan proses lain. Script menghapus webhook controller otomatis saat start.

**`401 Unauthorized`**
Token salah atau sudah di-revoke. Buat token baru lewat BotFather.

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
render.yaml           blueprint Render free web service
Dockerfile            image untuk Fly.io
fly.toml              konfigurasi app Fly.io
.dockerignore         file yang tidak masuk image
reactionbot.service   unit systemd untuk VPS
requirements.txt      dependency Python
```
