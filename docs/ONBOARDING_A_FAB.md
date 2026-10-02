# Onboarding a new fab

A fab is **data, not code**. Adding one is a JSON file and a pull request; the engine, API and UI
need no changes. The profile is validated at startup and in CI, so a broken profile fails the
build, not a shift.

## 1. Write the profile

Copy `backend/app/fabs/profiles/fab2-200mm-analog.json` to `backend/app/fabs/profiles/<fab-id>.json`.

| Field | What to put |
|---|---|
| `id` | Stable, lowercase, e.g. `fab3-300mm-memory`. Used in URLs and access lists. |
| `name`, `description` | Shown in the fab switcher. |
| `floor.width`, `floor.height` | Floor plan size in metres. |
| `shift.start_hour`, `shift.length_min` | e.g. `6` and `480` for 8-hour shifts from 06:00. |
| `walk_m_per_min` | Walking speed in cleanroom garb (55–65 is typical). |
| `constraint_family` | The bottleneck tool family (usually lithography/photo). |
| `families[]` | One per tool family: `id`, `label`, tool-ID `prefix`, bay rectangle `area` `[x0, y0, x1, y1]` (must lie inside the floor), the `pm_task` text, and a `faults` catalogue. |
| `faults` | Per fault code: typical `symptoms`, and `causes` with `fix`, `mean_min`, `sd_min`. These drive the repair-history predictions. |
| `presets` | Planning drills, e.g. `normal`, `<constraint>_crunch`, `excursion`: job mix per family, constraint-certified engineer share, share of unplanned downs, response SLAs in minutes. |

## 2. Validate locally

```bash
cd backend
pytest -q tests/test_fabs.py tests/test_constraints.py   # schema, generation, hard constraints on every preset
```

Then start the app. The new fab appears in the switcher; generate a shift and check the floor plan
and the workforce view.

## 3. Grant access

Users see the fabs listed in their Supabase `app_metadata.fabs` (or `FAB_DEFAULT_FABS` if unset).
Set it in Supabase → Authentication → Users → *user* → app metadata, e.g.

```json
{ "role": "dispatcher", "fabs": ["fab3-300mm-memory"] }
```

`role` is `viewer` or `dispatcher`. Users can't edit `app_metadata` themselves; admins can.

## 4. Give it its own database (optional)

To keep the fab's data in a separate database, add it to `FAB_TENANT_DATABASES`:

```bash
FAB_TENANT_DATABASES='{"fab3-300mm-memory": "postgresql://user:pass@host:5432/fab3"}'
```

Its schema is created on first use, and `/api/health` reports every database it checks. Fabs not
listed share the default database, isolated by `fab_id`.

## 5. Ship it

Open a pull request (template: *Onboard a new fab*), let CI pass, merge to `main`, verify in UAT
with the fab's key users, then release. See [ENVIRONMENTS.md](ENVIRONMENTS.md).

Profiles can also live outside the repo: point `FAB_PROFILES_DIR` at a directory of JSON files.
