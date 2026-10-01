# Supabase Auth: emails, sender and guest access

Fab Dispatch uses Supabase Auth in UAT and production. Four things are configured in the Supabase
dashboard rather than in code; this is how, and why.

## 1. Branded emails

`templates/` holds the six Auth emails, generated from one layout by `build_templates.py` so they
stay consistent. They use email-safe HTML (tables, inline styles, no images or web fonts), a hidden
preview line, a button with a plain-link fallback, and the 6-digit code where the flow supports it
(the sign-in screen accepts the code, which helps when the email is opened on another device).

| Template (Supabase name) | File | Subject |
|---|---|---|
| Confirm sign up | `confirmation.html` | Confirm your email · Fab Dispatch |
| Magic link | `magic_link.html` | Your sign-in link · Fab Dispatch |
| Reset password | `recovery.html` | Reset your password · Fab Dispatch |
| Invite user | `invite.html` | You're invited to Fab Dispatch |
| Change email address | `email_change.html` | Confirm your new email · Fab Dispatch |
| Reauthentication | `reauthentication.html` | Your verification code · Fab Dispatch |

To change them: edit `TEMPLATES` in `build_templates.py`, run `python3 supabase/build_templates.py`,
then in Supabase open **Authentication → Emails → Templates**, and for each template paste the
subject and the file's contents.

## 2. A sender that reaches everyone

Supabase's built-in email service **only delivers to members of the Supabase organisation**, and
about two emails an hour. Anyone else signing up never receives the email. Production needs a custom
SMTP sender. The free option used here is Gmail (about 500 emails a day):

1. On the Google account that will send: turn on **2-Step Verification**, then create an **App
   password** (Google Account → Security → App passwords). Keep it private; it isn't your Google password.
2. In Supabase: **Authentication → Emails → SMTP Settings → Enable custom SMTP**:
   - Sender email: the Gmail address · Sender name: `Fab Dispatch`
   - Host `smtp.gmail.com` · Port `465` · Username: the Gmail address · Password: the app password
3. **Authentication → Rate Limits:** raise "emails sent per hour" from the custom-SMTP default (30)
   if you expect more sign-ups.

For a fab's own deployment, use the company's mail service or a transactional provider (Resend,
Postmark, SES) on the fab's domain, so emails come from that domain.

## 3. Guest access

**Authentication → Sign In / Providers → Allow anonymous sign-ins: on.** The sign-in screen then
shows **Try it as a guest**. Guests get the role in `FAB_GUEST_ROLE` (see
[ENVIRONMENTS.md](../docs/ENVIRONMENTS.md)); set it to `none` to refuse them. Supabase rate-limits
anonymous sign-ins per IP address.

## 4. CAPTCHA (Cloudflare Turnstile, free)

Stops bots from creating guest accounts or flooding sign-in emails. Turn it on in this order: the
app first, then Supabase. Once Supabase requires CAPTCHA, every sign-in without a token is rejected.

1. **Cloudflare → Turnstile → Add widget:** hostname `fab-dispatch.vercel.app` (add `localhost` to
   try it locally), mode **Managed**. Copy the **site key** (public) and the **secret key** (private).
2. **The app:** set `FAB_TURNSTILE_SITE_KEY` to the site key in Vercel (Production and Preview) and
   redeploy. The sign-in screen then loads the widget, usually invisibly, and sends its token with
   every sign-in. Without the key, nothing changes.
3. **Supabase → Authentication → Attack Protection → Enable CAPTCHA protection:** provider
   **Turnstile**, paste the **secret key**, save.

Cloudflare's test site key `1x00000000000000000000AA` always passes and works on any host, which is
handy for checking the setup locally.

## URLs

**Authentication → URL Configuration:** Site URL `https://fab-dispatch.vercel.app`, plus redirect URLs
for UAT (`https://fab-dispatch-git-main-*.vercel.app`), previews and `http://localhost:5173`.
