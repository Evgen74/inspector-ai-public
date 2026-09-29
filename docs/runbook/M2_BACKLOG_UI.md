# M2 backlog — UI issues seen in the live D1 walkthrough (2026-09-29)

Found by the lead while clicking through the running product (web :5173, API :3000). Owners per `CLAUDE.md`.

| # | Screen | Issue | Owner |
|---|---|---|---|
| 1 | Верификация → object list | Indication shows the raw enum `NONE` instead of the Russian label and colour chip; «Тип проверки» is empty («—») although the protocol is FULL. | AG-05 |
| 2 | Verification evidence card | «Расхождение» shows raw JSON (`Δ {"actual":"","expected":"В10.3","direction":"ABSENT"}`); render it as Russian text, e.g. «В РД отсутствует В10.3». | AG-05 |
| 3 | Verification evidence card | «Согласованное изменение: NONE» must read «нет». | AG-05 |
| 4 | Protocol view vs verification | Protocol v3 (run m1-ag00-integ-tyumen) shows every decision as «⏳ Ожидает», while the verification workspace (protocol «версия 1») shows 10 confirmed and 3 rejected. The protocol view must reflect the decisions of the same process, or clearly show which version the decisions belong to. | AG-08 + AG-05 |
| 5 | Dashboard | «Подтв.» counts finding groups (3) while verification counts atomic findings (10); label the unit or show both. | AG-08 |
| 6 | Dashboard / API | Stale demo imports (`m1-ago0-import-smoke`, `d1-fixture-tyumen`) still exist in the dev DB. The ordering fix (commit 868dc7d) stops them from shadowing real runs; add an admin action to archive fixture runs. | AG-00 |
| 7 | Evidence viewer | «Облака изменений (0)» on F0201/F0202 although AG-02B detects the revision cloud on F0202 p17 (IoU 0.711); check that layout artifacts reach the viewer. | AG-08 + AG-02B |
