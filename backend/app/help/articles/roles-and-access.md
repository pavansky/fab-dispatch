---
title: Accounts, roles and access
summary: Signing in, what viewers and dispatchers can do, and access to fabs.
section: Reference
order: 3
keywords: [sign in, signin, login, log in, sign out, logout, account, password, magic link, email, role, roles, viewer, dispatcher, permission, permissions, access, admin, cannot, can't, disabled, greyed out, forbidden, fab access]
---

# Accounts, roles and access

## Signing in

On the hosted app, choose **Try it as a guest**, or enter your email and choose **Email me a sign-in
code**. A one-time code arrives by email; type it in, or open the link in the same email. It's the
same step whether it's your first visit or not: there's no sign-up and no password. Running
locally, choose **Continue as Dispatcher** or **Continue as Viewer** (local demo only; the hosted app
refuses it).

**Sign out** is in the user menu (your initial, top right). On phones, the theme switch is there too.

## Roles

| | Viewer | Dispatcher |
|---|---|---|
| Generate shifts, compare strategies, explore every view | ✓ | ✓ |
| What-ifs (weights, report a job, off shift) | ✓ | ✓ |
| Watch and join live shifts | ✓ | ✓ |
| Start and drive live shifts, report tool-downs | | ✓ |
| Run benchmarks and optimality gaps | | ✓ |

If a button is greyed out with a note about the dispatcher role, ask your administrator for it.
The server enforces roles too, not just the screen.

## Fab access

Each account can see specific fabs. The fab picker in the top bar lists only yours. A link to a fab
or shift you can't access behaves as if it doesn't exist.
