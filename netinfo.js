// netinfo.js
// ─────────────────────────────────────────────────────────────────────────────
// LAN addresses for the startup banner.
//
// Node's http.listen(port) already binds 0.0.0.0, so every viewer is reachable
// from the LAN without any change. What was missing is simply being TOLD the
// address — and a chart host that follows the page rather than being pinned to
// localhost, which on a phone resolves to the phone itself.
// ─────────────────────────────────────────────────────────────────────────────

'use strict';

const os = require('os');

/** Non-internal IPv4 addresses, most-likely-LAN first. */
function lanAddresses() {
    const out = [];
    for (const [name, addrs] of Object.entries(os.networkInterfaces())) {
        for (const a of addrs || []) {
            if (a.family !== 'IPv4' || a.internal) continue;
            out.push({ name, address: a.address });
        }
    }
    // Private ranges first: a VPN or docker bridge is rarely the one wanted.
    const priv = a => /^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)/.test(a.address);
    return out.sort((a, b) => (priv(b) - priv(a)));
}

/** Startup banner listing every address the page can be reached on. */
function banner(title, port, extraLines = []) {
    const lines = [];
    lines.push('');
    lines.push(`${title}`);
    lines.push(`  local   http://localhost:${port}`);
    for (const { name, address } of lanAddresses()) {
        lines.push(`  lan     http://${address}:${port}   (${name})`);
    }
    for (const l of extraLines) lines.push(`  ${l}`);
    lines.push('');
    lines.push('  Open the lan address on a phone on the same network.');
    lines.push('');
    return lines.join('\n');
}

module.exports = { lanAddresses, banner };
