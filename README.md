# QR Studio by TeamDev

Stylish QR posters. Free editing and watermarked preview, paid clean download (UPI only, confirmed from Fampay emails by UTR).

```
qrstudio/
  start.sh              sudo ./start.sh  -> installs, starts 24/7 (systemd, auto-restart, boots with the server)
  requirements.txt
  backend/
    config.json         all backend settings (like a .env)
    app/                Starlette API: auth, QRs, themes, orders, payments, admin
    scripts/gen_themes.py   builds the 18 built-in themes into backend/assets/themes
    tests/e2e.py        82 end-to-end checks against a running server
    data/               SQLite db, uploads, exports (back this folder up; on Railway this is the Volume)
  frontend/
    config.json         site name, owner, support email
    *.html, assets/     landing, themes, pricing, login, signup, studio, theme-maker, dashboard, admin, terms, privacy, 404
```

## Run

    sudo ./start.sh            # first run: venv + dependencies + themes (about 2 min), then starts the service
    sudo ./start.sh status | logs | restart | stop | uninstall
    ./start.sh dev             # foreground with auto-reload, for development

## Before going live (edit backend/config.json)

1. `server.public_url` and `security.allowed_origins` -> your https domain. Set `security.cookie_secure` to `true` once HTTPS works.
2. `server.trust_proxy_headers` -> `true` if nginx/Cloudflare sits in front (so rate limits see real IPs).
3. `payments.upi_id` -> the Fam UPI ID that receives money. `admin.emails` (empty by default) -> who gets the /admin page.
4. Payments: `payments.mode` is `mock` (shows a "Simulate payment" button). Switch to `live`, then fill `payments.imap`:
   `enabled: true`, `user` = the Gmail that receives Fam emails, `app_password` = a Gmail App Password
   (Google Account -> Security -> 2-Step Verification -> App passwords), IMAP enabled in Gmail settings.
   `allowed_senders` must hold the exact domain Fam sends from (famapp.in in your screenshot). Check one real email's
   "Show original" to confirm the From domain and that Gmail shows `dkim=pass`. Emails that fail this are ignored.
5. Put nginx or Caddy in front for HTTPS (Caddy: `yourdomain { reverse_proxy 127.0.0.1:8000 }`).
6. Edit Terms and Privacy (frontend/terms.html, privacy.html) and have a lawyer review them.

## How payment matching works

Each order gets a unique amount with paise (e.g. 39.95). The Gmail poller stores every verified Fam email (amount, UTR, time).
The customer pastes the UTR; it unlocks only if the UTR exists, is unused, the amount matches the order to the paise,
and the payment is newer than the order and under `payment_valid_minutes` old. A UTR can unlock one order, ever.
Admin page can add a missed payment by hand.

## Preview protection

Previews are rendered on the server at 640x960 with a diagonal watermark over the whole poster (QR included) and a per-user tag.
The clean image is never sent before payment; it is rendered on demand after the order is paid. Right-click/drag are blocked in the
page as a deterrent only. A user can always screenshot a preview, but the screenshot stays watermarked and low resolution.

## Railway / GitHub
See DEPLOY.md. Settings can come from environment variables (see railway.variables.example), so no secrets live in the repo.

## Admin, backup and payments (v2)
- `/admin` tabs: Overview, Orders (mark paid / unpaid), Payments, Users, QRs, Payment test, Backup, Activity, Settings.
- Backup: Admin -> Backup downloads one zip (database + logos + custom themes). The same page restores it (needs the admin password and the word RESTORE). A daily database copy is also kept in the data folder.
- Payment test: any amount, same matching path as customers. Test orders never count as revenue.
- Payments unlock automatically when the Fam email arrives and exactly one open order has that amount. Fallbacks: UTR, Fam Transaction ID, or "My payment has no UTR" (Fam to Fam).
- Unpaid previews contain a scrambled, unscannable QR. `python3 backend/tests/decoy_check.py` proves it.
- Tests (server on localhost in mock mode, fresh data, `ADMIN_EMAILS=adm@x.com`): `tests/e2e.py`, `tests/payments_extra.py`, `tests/decoy_check.py`.
