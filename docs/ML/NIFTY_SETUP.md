# NIFTY / Indian F&O: access and first steps (20 Nov 2026)

Supersedes the logistics in `INDIA_PLAN.md` §0 for the option work. The data stays on the VM (the Mac has about
7 GB free); the analysis runs there, driven over SSH from the Mac session.

## 1. Access (one-time, done by him on the VM over RDP)

VM: an Azure Windows machine (address and username are kept out of this public repo). On 20 Nov port 3389 (RDP) answers and
port 22 (SSH) does not.

In PowerShell **as Administrator** on the VM:

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
New-NetFirewallRule -Name sshd -DisplayName "OpenSSH Server" -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

Key login, so no password is ever typed into a chat or a file. The public key is printed by
`cat ~/.ssh/id_ed25519_nifty_vm.pub` on the Mac (the private half never leaves the Mac). If the user is an
administrator on the VM (usual on Azure):

```powershell
Add-Content -Path C:\ProgramData\ssh\administrators_authorized_keys -Value "<the one-line public key>"
icacls.exe C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"
```

If not an administrator, put the line in `C:\Users\<user>\.ssh\authorized_keys` instead.

In the Azure portal: VM → Networking → Add inbound port rule → TCP 22, **Source = "My IP address"** (not Any).
A home IP that changes means editing this rule again.

Test from the Mac: `ssh -i ~/.ssh/id_ed25519_nifty_vm <user>@<vm-address> hostname`

Also needed on the VM: Python 3.11+ and git (both have Windows installers; `winget install Python.Python.3.12 Git.Git`).

## 2. First session on the VM

1. **Inventory, read-only:** where the data is, format, instruments (NIFTY / BANKNIFTY / SENSEX options, futures,
   spot, VIX), date range, bar size, whether volume and OI are present, gaps, how expiries and strikes are named.
   Nothing is moved, renamed or deleted.
2. **Clean store** beside the raw data (parquet, one schema: `ts, o, h, l, c, volume, oi` per contract), with a
   check report. Raw files stay untouched.
3. **Daily job** to keep it current from Kite, once he confirms how the existing collection runs.
4. **Clone this repo** on the VM and add an NSE adapter that produces the same rows `htf_squeeze.py` reads, so the
   crypto and NIFTY tests run the same code.

## 3. What gets tested first, and what is needed from him

The 6h–1w parabolic `otm_red_squeeze` (`HTF_SQUEEZE.md`). On crypto the shape did not select winners, but the
definition was never checked against a case he picked (Bounds, last bullet). So, before any statistics:

- **10–20 cases from him:** contract, timeframe, and the bar where he would say "this is it". The NIFTY 1:500 moves
  he mentioned on 11 Nov and the OCT 22600/22700 CE charts of 26–27 Oct are the natural start.
- Check the detector fires at his bar; if not, fix the coding first.
- Then count how often the corrected pattern appears with no move (matched controls, CIs by expiry), on traded
  prices with volume and OI, which NIFTY has and Delta does not.
- Costs for NSE options (brokerage, STT, exchange charges, slippage) replace the 8.26% Delta figure; never a
  shared constant.
