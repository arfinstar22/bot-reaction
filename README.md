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

### 6. Deploy selalu aktif dengan Fly.io

Ini opsi yang disarankan. Bot tetap long polling, tidak butuh domain, HTTPS, atau webhook. `flyctl` sudah terpasang di mesin ini.

Biaya mesin terkecil `shared-cpu-1x` 256MB sekitar **US$2.19/bulan** di region AS, **US$2.78/bulan** di Singapura. Fly saat ini membebaskan tagihan personal organization di bawah **US$5/bulan**; cek syarat terbaru di dashboard. Butuh kartu kredit setelah masa trial.

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

Fly akan menjalankan satu Machine 256MB tanpa port HTTP. Machine ini hidup terus, jadi bot tidak tidur seperti Render free.

Kalau nanti mengubah kode atau `reactions.txt`, deploy ulang:

```bash
flyctl deploy
```

### 7. Kalau tetap mau Render

Jangan pakai **Render Free Web Service**. Service itu tidur setelah 15 menit tanpa inbound traffic. Bot ini tidak punya HTTP server, jadi tidak akan membangunkan dirinya sendiri.

Yang benar di Render: **Background Worker** dengan plan berbayar, mulai **US$7/bulan**. Background worker Render tidak punya tipe gratis. Buat `New > Background Worker`, hubungkan repo Git, lalu:

```text
Build Command: pip install -r requirements.txt
Start Command: python bot.py
```

Tambahkan environment variable `TG_TOKENS` dan `CHANNEL_ID`. Render worker tidak butuh port HTTP. Dockerfile juga bisa dipakai kalau memilih runtime Docker.

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

**`MESSAGE_ID_INVALID`**
Post sudah dihapus atau itu service message yang tidak bisa direaction. Error ini aman diabaikan.

## Keamanan

`.env` berisi token bot. Jangan commit ke Git. Kalau token bocor, revoke lewat `/revoke` di BotFather.

## File

```text
bot.py                program utama
reactions.txt         daftar emoji
test_bot.py           unit test logika filter dan pemilihan emoji
.env.example          contoh konfigurasi
Dockerfile            image untuk Fly.io / Render
fly.toml              konfigurasi app Fly.io
.dockerignore         file yang tidak masuk image
reactionbot.service   unit systemd untuk VPS
requirements.txt      dependency Python
```
