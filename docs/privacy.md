# Privacy and data

Fab Dispatch is a demonstration product: fabs, engineers, faults and repair histories are
**synthetic**. This page lists the personal data the hosted app handles, why, and for how long.

## What's stored

| Data | Why | Kept |
|---|---|---|
| Email address (Supabase Auth) | To sign you in with a link or code | Until the account is deleted |
| Guest accounts | Anonymous id only, no email | Deleted after 30 days without a sign-in or any live-shift activity |
| Live shifts you start, with your email as creator | Audit trail of who changed what | 30 days after last change |
| "Who's watching" presence (email, last seen) | Showing collaborators on a live shift | 1 day |
| Assistant feedback (user id, question, note) | Improving answers | 180 days |
| Cached plans | Speed | 7 days |
| Retry keys for live actions | Avoiding double-applied actions | 24 hours |

Deletion runs daily. A guest account is deleted once it has gone 30 days without signing in,
refreshing its session, starting or changing a live shift, or watching one; its shifts, if any are
still within their own 30 days, keep the guest's anonymous label. The database is closed to
Supabase's public API; only the app's server can read it.

## In your browser

Local storage holds your session (the Supabase access and refresh tokens, kept there by the
Supabase client library, so a script running on the page could read them; the app's Content
Security Policy exists to keep such scripts out), your theme, chosen fab and whether you've seen
the tour. No advertising or tracking cookies, and no analytics.

## Services involved

| Service | Role |
|---|---|
| Vercel | Hosting the app and API |
| Supabase | Database and sign-in |
| Google (Gmail) | Sending sign-in emails |
| Cloudflare Turnstile | Telling people from bots at sign-in |
| Google Fonts | Fonts |
| GitHub | Source code, issues and discussions |

No data goes to an AI provider: the assistant runs inside the app. An optional language model is
off on the hosted app (see [AI transparency](ai.md)).

## Your choices

Sign out at any time from the user menu. To delete your account, open the user menu and choose
**Delete my account**. It takes effect immediately:

- your assistant feedback, presence and pending requests are deleted;
- your email in shared shift history is replaced with "a deleted user" (the fab keeps the record of
  what happened, without your identity);
- your sign-in account is removed.

Questions about your data: [support](support.md).
