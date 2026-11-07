# Deploy on Railway (GitHub se, ek baar)

## 1. GitHub
1. GitHub par **private** repo banao (secrets ke liye private rakho).
2. Zip extract karke is folder ka content repo me upload karo (ya `git init && git add . && git commit && git push`).
   `.gitignore` already database aur secrets ko bahar rakhta hai.

## 2. Railway
1. railway.com -> **New Project -> Deploy from GitHub repo** -> apna repo chuno. Dockerfile apne aap detect hoga.
2. Service -> **Settings -> Volumes -> Add Volume**, mount path: `/data`  (bina volume ke har deploy par users/orders delete ho jaayenge).
3. Service -> **Variables -> Raw Editor**: `railway.variables.example` paste karke values bharo. `GMAIL_APP_PASSWORD` sirf yahin dalo.
4. Service -> **Settings -> Networking -> Generate Domain**. Jo URL mile wo `PUBLIC_URL` me dalo (ya apna domain: CNAME record Railway ke diye target par). Variables save -> redeploy.
5. Health check `/api/health` hai; green hote hi site live.

## 3. Gmail App Password
Google Account -> Security -> 2-Step Verification ON -> App passwords -> naam "qrstudio" -> 16 letter ka password -> Railway `GMAIL_APP_PASSWORD`.
Gmail Settings -> Forwarding and POP/IMAP -> IMAP enabled hona chahiye.

## 4. Live check (pehle ₹1 se)
1. Site par signup karo (ADMIN_EMAILS wali email se), `/admin` khol ke "Payment mailbox" connected dikhna chahiye.
2. Order banao, exact amount (paise ke saath) Fam se pay karo, Fam ka email aane do, UTR dalo, download unlock hona chahiye.
3. Agar match na ho: Gmail me Fam email -> Show original -> `From:` aur `Authentication-Results` dekho, `FAM_SENDER_DOMAINS` usse match karo (dkim=pass hona chahiye).

## 5. Dhyan rakho
- `/admin` -> "Download backup" se hafte me database backup lo.
- Logs: Railway -> Deployments -> View logs (startup warnings yahin dikhte hain).
- Zyada traffic par `WEB_CONCURRENCY=2` set karo.

## Domain + Google SEO (qr.teamdev.sbs)
1. Railway -> Settings -> Networking -> **Custom Domain** -> `qr.teamdev.sbs`. Jo CNAME target dikhe wo DNS me `qr` naam se add karo. Variables: `PUBLIC_URL` aur `SITE_URL` = `https://qr.teamdev.sbs`.
2. https://search.google.com/search-console -> Add property -> URL prefix `https://qr.teamdev.sbs` -> HTML tag method. Meta tag ka `content="..."` wali value `GOOGLE_SITE_VERIFICATION` me daalo, redeploy, Verify dabao.
3. Search Console -> Sitemaps -> `sitemap.xml` submit. Phir URL Inspection se `/` aur `/qr/upi-qr-code-poster` ke liye "Request indexing".
4. Bing Webmaster Tools me bhi import/add karo (`BING_SITE_VERIFICATION`).
5. Instagram bio me site link, aur apni invite link share karo. Index hone me 1-4 hafte lag sakte hain.
6. Alerts: BotFather se bot banao, `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` set karo; Admin -> Settings me "Send test".
7. Referral: 3 invites me se koi 1 paid kare to 1 free download (₹49 tak). Config: `QS__referral__invites_needed`, `QS__referral__credit_max_rupees`.
