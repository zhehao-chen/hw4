# Issue triage runbook

Whoever is on the support rotation that week owns triage. Go through new
issues every weekday morning; every issue should have a label within one
working day of being opened.

## 1. Label it

Pick exactly one:

| Label | Use when |
| --- | --- |
| `bug` | Something documented or previously working does not work |
| `feature` | A request for new behaviour, a new option or a new format |
| `question` | The reporter wants to know how something works; no change is expected |
| `docs` | The documentation is wrong, missing something, or out of date |

Add `needs-info` as well if you cannot act on it yet. If an issue is really two
issues, ask the reporter to split it.

## 2. Reproduce (bugs only)

- Ask for the version (`GET /api/v1/health` returns it), the user's locale and
  time zone if dates or emails are involved, and a small sample file with
  personal data removed.
- Reproduce on staging with the same input before going further.
- Do not ask for real bank statements. A redacted sample with three or four
  rows is almost always enough.

## 3. Find the owning code

Reporters often name the part of the product where they saw the symptom, which
is not always where the cause is. Confirm in the code before assigning.

| Area | Start in |
| --- | --- |
| Uploads and imports | `src/api/uploads.ts`, `src/ingest/` |
| Reports and exports | `src/api/reports.ts`, `src/export/`, `src/exportUtils.ts` |
| Emails | `src/notifications/` |
| Accounts and login | `src/api/auth.ts`, `src/api/users.ts` |
| Web components | `src/components/` |
| Configuration and deploys | `config/`, `docs/CONFIG.md` |

Write the file you think is responsible in a comment on the issue, with a line
or two on why.

## 4. Prioritise

- **P1**: data loss, wrong amounts in the ledger, or a security problem. Tell
  the on-call engineer the same day.
- **P2**: a feature is broken and there is no workaround.
- **P3**: everything else, including most feature requests.

## 5. Reply

Thank the reporter, say what label and priority you gave it, and what happens
next. For questions, answer directly and close once the reporter confirms.
Never close a bug as "cannot reproduce" without asking for more information at
least once.
