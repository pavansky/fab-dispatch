"""Builds the branded Supabase Auth email templates in templates/ from one layout.

Run after editing copy or style:  python3 supabase/build_templates.py
Then apply each file in Supabase: Authentication -> Emails -> Templates (see README.md).

Email-client-safe on purpose: table layout, inline styles, no images or web fonts (often
blocked), a hidden preview line, a button plus a plain-link fallback, and a 6-digit code
where the flow supports one. Variables like {{ .ConfirmationURL }} are Supabase's (Go templates).
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).parent / "templates"
INK, SIGNAL, SIGNAL_TEXT, PAGE, LINE, MUTED, BODY = (
    "#020202",
    "#ef6f2e",
    "#b8460c",
    "#f5f5f5",
    "#e2dfdd",
    "#8a8380",
    "#4d4947",
)
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
SITE = "fab-dispatch.vercel.app"

TEMPLATES = {
    "confirmation": {
        "subject": "Confirm your email · Fab Dispatch",
        "preheader": "One click and you're in: compare five dispatch strategies on a live fab shift.",
        "eyebrow": "Welcome",
        "title": "Confirm your email",
        "intro": "Thanks for trying Fab Dispatch, the engine that sends the right equipment engineer to every "
        "tool-down. Confirm this address to open your workspace.",
        "button": "Confirm and sign in",
        "url": "{{ .ConfirmationURL }}",
        "code": True,
        "why": "someone signed up for Fab Dispatch with {{ .Email }}",
    },
    "magic_link": {
        "subject": "Your sign-in link · Fab Dispatch",
        "preheader": "Your secure sign-in link for Fab Dispatch. It works once and expires in an hour.",
        "eyebrow": "Sign in",
        "title": "Your sign-in link",
        "intro": "Use the button to sign in to Fab Dispatch. No password needed; the link works once.",
        "button": "Sign in to Fab Dispatch",
        "url": "{{ .ConfirmationURL }}",
        "code": True,
        "why": "a sign-in was requested for {{ .Email }}",
    },
    "recovery": {
        "subject": "Reset your password · Fab Dispatch",
        "preheader": "Choose a new password for Fab Dispatch. The link expires in an hour.",
        "eyebrow": "Account",
        "title": "Reset your password",
        "intro": "We received a request to reset the password for this account. Choose a new one with the button "
        "below.",
        "button": "Choose a new password",
        "url": "{{ .ConfirmationURL }}",
        "code": False,
        "why": "a password reset was requested for {{ .Email }}",
    },
    "invite": {
        "subject": "You're invited to Fab Dispatch",
        "preheader": "You've been invited to dispatch maintenance engineers with Fab Dispatch.",
        "eyebrow": "Invitation",
        "title": "You're invited",
        "intro": "You've been invited to Fab Dispatch: compare allocation strategies on your fab's shifts, run "
        "live dispatch with your team, and see why every engineer was chosen.",
        "button": "Accept the invitation",
        "url": "{{ .ConfirmationURL }}",
        "code": False,
        "why": "an administrator invited {{ .Email }}",
    },
    "email_change": {
        "subject": "Confirm your new email · Fab Dispatch",
        "preheader": "Confirm the new email address for your Fab Dispatch account.",
        "eyebrow": "Account",
        "title": "Confirm your new email",
        "intro": "Confirm that {{ .NewEmail }} should replace {{ .Email }} on your Fab Dispatch account.",
        "button": "Confirm new email",
        "url": "{{ .ConfirmationURL }}",
        "code": False,
        "why": "an email change was requested for {{ .Email }}",
    },
    "reauthentication": {
        "subject": "Your verification code · Fab Dispatch",
        "preheader": "Your Fab Dispatch verification code.",
        "eyebrow": "Security",
        "title": "Confirm it's you",
        "intro": "Enter this code to finish the change to your Fab Dispatch account.",
        "button": None,
        "url": None,
        "code": True,
        "why": "a sensitive change was requested for {{ .Email }}",
    },
}


def _mark() -> str:
    """The brand mark (ink tile, orange square) drawn with table cells: no image to block."""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:separate">'
        f'<tr><td width="28" height="28" align="center" valign="middle" bgcolor="{INK}" '
        f'style="width:28px;height:28px;background:{INK};border-radius:5px">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto"><tr>'
        f'<td width="10" height="10" bgcolor="{SIGNAL}" style="width:10px;height:10px;background:{SIGNAL};'
        f'border-radius:2px;font-size:0;line-height:0">&nbsp;</td></tr></table></td></tr></table>'
    )


def render(t: dict) -> str:
    button = ""
    if t["button"]:
        button = f"""
          <tr><td style="padding:8px 0 0">
            <table role="presentation" cellpadding="0" cellspacing="0"><tr>
              <td bgcolor="{INK}" style="background:{INK};border-radius:3px">
                <a href="{t["url"]}" target="_blank" style="display:inline-block;padding:13px 22px;font:600 13px {MONO};letter-spacing:.06em;text-transform:uppercase;color:#ffffff;text-decoration:none">{t["button"]} &rarr;</a>
              </td></tr></table>
          </td></tr>"""
    code = ""
    if t["code"]:
        label = "Or enter this code" if t["button"] else "Your code"
        code = f"""
          <tr><td style="padding:24px 0 0">
            <p style="margin:0 0 8px;font:600 11px {MONO};letter-spacing:.08em;text-transform:uppercase;color:{MUTED}">{label}</p>
            <p style="margin:0;display:inline-block;padding:10px 16px;border:1px solid {LINE};border-radius:3px;background:{PAGE};font:600 24px {MONO};letter-spacing:.3em;color:{INK}">{{{{ .Token }}}}</p>
          </td></tr>"""
    fallback = ""
    if t["url"]:
        fallback = f"""
          <tr><td style="padding:28px 0 0">
            <div style="border-top:1px solid {LINE};padding-top:18px">
              <p style="margin:0 0 6px;font:13px/1.5 {SANS};color:{MUTED}">Button not working? Paste this link into your browser:</p>
              <p style="margin:0;font:12px/1.5 {MONO};color:{SIGNAL_TEXT};word-break:break-all"><a href="{t["url"]}" style="color:{SIGNAL_TEXT}">{t["url"]}</a></p>
            </div>
          </td></tr>"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<title>{t["subject"]}</title>
</head>
<body style="margin:0;padding:0;background:{PAGE}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{PAGE}">{t["preheader"]}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{PAGE}" style="background:{PAGE}">
  <tr><td align="center" style="padding:40px 16px">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px">
      <tr><td style="padding:0 4px 20px">
        <table role="presentation" cellpadding="0" cellspacing="0"><tr>
          <td valign="middle">{_mark()}</td>
          <td valign="middle" style="padding-left:12px;font:600 13px {MONO};letter-spacing:.08em;text-transform:uppercase;color:{INK}">Fab Dispatch</td>
        </tr></table>
      </td></tr>
      <tr><td bgcolor="#ffffff" style="background:#ffffff;border:1px solid {LINE};border-top:3px solid {SIGNAL};border-radius:4px;padding:32px 32px 28px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr><td>
            <p style="margin:0 0 10px;font:600 11px {MONO};letter-spacing:.08em;text-transform:uppercase;color:{SIGNAL_TEXT}">&#9679; {t["eyebrow"]}</p>
            <h1 style="margin:0 0 14px;font:600 26px/1.15 {SANS};letter-spacing:-.02em;color:{INK}">{t["title"]}</h1>
            <p style="margin:0 0 22px;font:15px/1.6 {SANS};color:{BODY}">{t["intro"]}</p>
          </td></tr>{button}{code}{fallback}
        </table>
      </td></tr>
      <tr><td style="padding:20px 4px 0">
        <p style="margin:0 0 8px;font:12px/1.6 {SANS};color:{MUTED}">You're receiving this because {t["why"]}. If that wasn't you, ignore this email: nothing changes until the link is used, and it expires.</p>
        <p style="margin:0;font:600 11px {MONO};letter-spacing:.06em;text-transform:uppercase;color:{MUTED}">Fab Dispatch &middot; Maintenance dispatch for semiconductor fabs &middot; <a href="{{{{ .SiteURL }}}}" style="color:{MUTED}">{SITE}</a></p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>
"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, t in TEMPLATES.items():
        (OUT / f"{name}.html").write_text(render(t))
        print(f"{name:18} {t['subject']}")


if __name__ == "__main__":
    main()
