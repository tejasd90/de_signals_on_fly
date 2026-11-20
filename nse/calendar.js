// nse/calendar.js
// ─────────────────────────────────────────────────────────────────────────────
// NSE/BSE F&O session rules. The lists are his, from
// explosion_after_premium_eroded_signal/utils.js (to 2026-01-26); the 2026 dates after
// that are from the exchange circular and are CHECKED AGAINST THE DATA by group.js,
// which builds each expiry's calendar from the days that actually have candles and
// reports any weekday with no data that is missing from this list.
// ─────────────────────────────────────────────────────────────────────────────
'use strict';

const HOLIDAYS = new Set(["2022-01-26","2022-03-01","2022-03-18","2022-04-14","2022-04-15","2022-05-03","2022-08-09","2022-08-15","2022-08-31","2022-10-05","2022-10-24","2022-10-26","2022-11-08","2023-01-26","2023-03-07","2023-03-30","2023-04-04","2023-04-07","2023-04-14","2023-05-01","2023-08-15","2023-09-19","2023-10-02","2023-10-24","2023-11-14","2023-11-27","2023-12-25","2024-01-22","2024-01-26","2024-03-08","2024-03-25","2024-03-29","2024-04-11","2024-04-17","2024-05-01","2024-05-20","2024-06-17","2024-07-17","2024-08-15","2024-10-02","2024-11-01","2024-11-15","2024-11-20","2024-12-25","2025-02-26","2025-03-14","2025-03-31","2025-04-10","2025-04-14","2025-04-18","2025-05-01","2025-08-15","2025-08-27","2025-10-02","2025-10-21","2025-10-22","2025-11-05","2025-12-25","2026-01-15","2026-01-26"].concat([
    '2026-03-03', '2026-03-26', '2026-03-31', '2026-04-03', '2026-04-14', '2026-05-01', '2026-05-28',
    '2026-06-26', '2026-09-14', '2026-10-02', '2026-10-20', '2026-11-10', '2026-11-24', '2026-12-25',
]));
// Sessions that are not normal trading days (Muhurat, Saturday mock/special sessions).
const SPECIAL_EXCLUDE = new Set(['2022-10-24', '2023-11-12', '2024-03-02', '2024-05-18', '2024-11-01', '2025-10-21', '2026-11-08']);
// Weekend days that WERE full sessions.
const SPECIAL_INCLUDE = new Set(['2024-01-20']);

const OPEN_MIN = 9 * 60 + 15;      // 09:15
const CLOSE_MIN = 15 * 60 + 30;    // 15:30, the close before the closing-session change
// From this date the derivatives session runs to 15:40 (closing-session change; seen in the data:
// every day from 2026-08-03 has minutes 15:30..15:39, none before).
const LONG_CLOSE_FROM = '2026-08-03';
const LONG_CLOSE_MIN = 15 * 60 + 40;
function closeMin(day) { return day >= LONG_CLOSE_FROM ? LONG_CLOSE_MIN : CLOSE_MIN; }

function dow(day) { return new Date(day + 'T00:00:00Z').getUTCDay(); }
function isWeekend(day) { const d = dow(day); return d === 0 || d === 6; }

/** A normal session day by the rules alone (the data decides whether it happened). */
function isSessionDay(day) {
    if (SPECIAL_EXCLUDE.has(day) || HOLIDAYS.has(day)) return false;
    if (isWeekend(day)) return SPECIAL_INCLUDE.has(day);
    return true;
}

function addDays(day, n) {
    const d = new Date(day + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
}
/** Monday of the week the day falls in. */
function weekStart(day) { const d = dow(day); return addDays(day, d === 0 ? -6 : 1 - d); }

function pad(n) { return n < 10 ? '0' + n : '' + n; }
function tsOf(day, minuteOfDay) { return day + 'T' + pad(Math.floor(minuteOfDay / 60)) + ':' + pad(minuteOfDay % 60) + ':00+05:30'; }

module.exports = { HOLIDAYS, SPECIAL_EXCLUDE, SPECIAL_INCLUDE, OPEN_MIN, CLOSE_MIN, LONG_CLOSE_FROM, LONG_CLOSE_MIN, closeMin,
    isWeekend, isSessionDay, addDays, weekStart, tsOf, dow };
