# Vpn Setup Guide

## Metadata
- created: unknown
- aliases: none
- source: /Users/hotuongvinh/ai_projects/wiki-cli/datasets/employee_onboarding/documents/VPN_Setup_Guide.pdf

## Related
- (no outgoing references found)

## Referenced By
- [It Onboarding Sop](it_onboarding_sop.md)

## Body
VPN Setup Guide
Overview
ThisguideexplainshowtosetupandconnecttotheAcmeCorpVPNforsecure
remote access to company resources.
Prerequisites
• Company-issued laptop with administrator access.
• Internet connection (minimum 25 Mbps download, 5 Mbps upload).
• MFA device or authenticator app (Microsoft Authenticator or similar).
Installation
Windows
1. Open the Company Portal app (pre-installed on company laptops).
2. Search for “Acme VPN Client” and click “Install.”
3. Follow the installation wizard. Click “Yes” when prompted for adminis-
trator access.
4. Once installed, restart your laptop.
macOS
1. Open Self Service (pre-installed on company laptops).
2. Search for “Acme VPN Client” and click “Install.”
3. Follow the installation prompts.
4. Once installed, restart your Mac.
Linux
Contact IT Support for Linux VPN setup instructions.
Configuration
First-Time Setup
1. OpentheAcmeVPNClient(searchfor“AcmeVPN”intheStartmenuor
Applications folder).
2. Click “Add Connection” and enter:
• Server Address: vpn.acmecorp.com
• Port: 443
• Protocol: IKEv2
3. Click “Save.”
4. Enter your company credentials (email@acmecorp.com and password).
5. Complete MFA authentication via your registered device.
6. Click “Connect.”
1

Connecting
Daily Use
| 1. Open     | the         | Acme VPN    | Client. |         |          |            |            |            |     |
| ----------- | ----------- | ----------- | ------- | ------- | -------- | ---------- | ---------- | ---------- | --- |
| 2. Click    | the         | connection  | profile | “Acme   | Corp     | VPN.”      |            |            |     |
| 3. Enter    | credentials |             | if not  | saved.  |          |            |            |            |     |
| 4. Complete |             | MFA prompt. |         |         |          |            |            |            |     |
| 5. Wait     | for         | “Connected” | status. |         |          |            |            |            |     |
| Quick       | Connect     | (Tray       | Icon)   |         |          |            |            |            |     |
| • Windows:  |             | Right-click | the     | VPN     | icon in  | the system | tray →     | “Connect.” |     |
| • macOS:    |             | Click the   | VPN     | icon in | the menu | bar →      | “Connect.” |            |     |
Disconnecting
| • Open | the     | VPN client | and  | click          | “Disconnect.” |     |     |     |     |
| ------ | ------- | ---------- | ---- | -------------- | ------------- | --- | --- | --- | --- |
| • Or   | use the | tray/menu  | icon | to disconnect. |               |     |     |     |     |
Troubleshooting
| Cannot         | Connect    |        |     |     |                  |                           |              |          |     |
| -------------- | ---------- | ------ | --- | --- | ---------------- | ------------------------- | ------------ | -------- | --- |
| Issue          |            |        |     |     | Solution         |                           |              |          |     |
| “Server        | not found” |        |     |     | Check            | internet                  | connection.  | Ensure   |     |
|                |            |        |     |     | vpn.acmecorp.com |                           | is correct.  |          |     |
| Authentication |            | failed |     |     | Verify           | credentials.              | Reset        | password | if  |
|                |            |        |     |     | needed           | at password.acmecorp.com. |              |          |     |
| MFA not        | working    |        |     |     | Contact          | IT                        | to reset MFA |          |     |
configuration.
| Connection | timeout |     |     |     | Try   | a different | network.   | Some | public |
| ---------- | ------- | --- | --- | --- | ----- | ----------- | ---------- | ---- | ------ |
|            |         |     |     |     | Wi-Fi | blocks      | VPN ports. |      |        |
Slow Connection
| • Use     | a wired             | Ethernet     | connection |               | instead | of Wi-Fi.   |     |     |     |
| --------- | ------------------- | ------------ | ---------- | ------------- | ------- | ----------- | --- | --- | --- |
| • Close   | bandwidth-intensive |              |            | applications. |         |             |     |     |     |
| • Connect |                     | to a network | with       | at least      | 50      | Mbps speed. |     |     |     |
Split Tunneling
Bydefault,onlycompanytraﬀic(internalsites,fileservers,email)goesthrough
the VPN. Regular internet traﬀic uses your local connection. To change this
setting:
| 1. Open | VPN | Client | → Settings. |     |     |     |     |     |     |
| ------- | --- | ------ | ----------- | --- | --- | --- | --- | --- | --- |
2

| 2. Under “Split    | Tunneling,” |            | select       | “Route      | all     | traﬀic through | VPN” (not | rec- |
| ------------------ | ----------- | ---------- | ------------ | ----------- | ------- | -------------- | --------- | ---- |
| ommended           | unless      | required). |              |             |         |                |           |      |
| Security Reminders |             |            |              |             |         |                |           |      |
| • Never share      | your        | VPN        | credentials. |             |         |                |           |      |
| • Always           | disconnect  | from       | VPN          | when        | not in  | use.           |           |      |
| • Do not           | use public  | or         | unsecured    | Wi-Fi       | without | VPN.           |           |      |
| • Report           | lost or     | stolen     | devices      | immediately | to      | IT.            |           |      |
• TheVPNautomaticallydisconnectsafter8hoursofinactivityforsecurity.
Contact
| • IT Portal:     | it.acmecorp.com         |        |         |          |     |      |     |     |
| ---------------- | ----------------------- | ------ | ------- | -------- | --- | ---- | --- | --- |
| • IT Support:    | extension               |        | 4200    |          |     |      |     |     |
| • Email:         | it-support@acmecorp.com |        |         |          |     |      |     |     |
| Document Version | 2.0                     | — Last | Updated | February |     | 2026 |     |     |
3

## Notes
_(add your own notes here -- preserved on recompile)_
