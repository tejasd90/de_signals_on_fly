// chart_url.js
// ─────────────────────────────────────────────────────────────────────────────
// Deep links into the chart app on :3000/de.
//
// Six viewers (serve_multibaggers, serve_signals_cal, serve_query, serve_trades,
// serve_calibrate and serve_signals) each grew their own private copy of this
// before it was a module. Those are left alone — this exists so the two grid
// viewers do not become copies seven and eight.
//
// THE HOST PLACEHOLDER
// The URL is built on the server, which does not know which hostname the browser
// used to reach it — localhost, a LAN IP, whatever. So the host is emitted as a
// placeholder and swapped for `location.hostname` in the page. That is what lets
// a chart link opened from a phone on the LAN resolve to the phone's view of the
// chart app rather than to the server's idea of "localhost".
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const expiryMod = require('./expiry');

const CHART_HOST_PLACEHOLDER = '__CHART_HOST__';
const CHART_BASE = `http://${CHART_HOST_PLACEHOLDER}:3000/de`;

// Context before the firing, and a little past settlement so the last candle is
// not flush against the right edge. Same values the older viewers use.
const CHART_LEAD_CANDLES = 40;
const CHART_TAIL_MINUTES = 30;

function pad(n) { return String(n).padStart(2, '0'); }

/** The chart app wants IST wall-clock with an explicit +0530 offset. */
function istOf(ms) {
    const d = new Date(ms + (5 * 60 + 30) * 60000);
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}` +
           `T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:00+0530`;
}

/**
 * @param {string} spot     BTC / ETH / XAUT
 * @param {string} expiry   'YYYY-MM-DD'
 * @param {string} symbol   e.g. C-BTC-74800-280826
 * @param {number} startMs  the firing's entry, in ms
 * @param {number} duration candle duration in minutes
 */
function chartUrl(spot, expiry, symbol, startMs, duration) {
    const from = istOf(startMs - CHART_LEAD_CANDLES * duration * 60000);
    const to   = istOf(expiryMod.expiryMillis(spot, expiry) + CHART_TAIL_MINUTES * 60000);
    return `${CHART_BASE}/${expiry}/${symbol}/${from}/${to}/${duration}`;
}

/** Client-side snippet, injected into each page's script block. */
const CLIENT_HELPER = `
const CHART_HOST=location.hostname;
function fixChartUrl(u){ return String(u||'').replace('${CHART_HOST_PLACEHOLDER}',CHART_HOST); }
function symLinks(syms,urls){
  return syms.map((s,i)=>urls&&urls[i]
    ? '<a href="'+esc(fixChartUrl(urls[i]))+'" target="_blank" rel="noopener">'+esc(s)+' \\u2197</a>'
    : esc(s)).join('  ');
}`;

module.exports = { CHART_BASE, CHART_HOST_PLACEHOLDER, CHART_LEAD_CANDLES,
                   CHART_TAIL_MINUTES, chartUrl, istOf, CLIENT_HELPER };
