# Heim-PC LAN-Durchsatz — 2026-05-18

Datum: 2026-05-18
Host: net-chico (Heim-PC)
Interface: enp6s0

## Befund

Link-Speed: 1000/full
Gemessener Durchsatz: ca. 900–937 Mbit/s

Vorheriger Zustand: Speed: 100Mb/s (beobachtet in früherer Session, jetzt superseded).

## Evidence

Belegt durch:
- lokaler Session-Log: `net-chico-reverse-only-iperf3-2026-05-18.log` (nicht eingecheckt)
- `ethtool enp6s0` Ausgabe: `Speed: 1000Mb/s`, `Duplex: Full`
- `iperf3` Reverse-Durchsatz: ca. 900–937 Mbit/s

Output-Snippet (gekürzt):

```text
$ ethtool enp6s0 | grep -E 'Speed|Duplex'
Speed: 1000Mb/s
Duplex: Full

$ iperf3 -R <ziel-host>   # Platzhalter: mehrere relevante Messläufe (gekürzt)
[ ID] Interval           Transfer     Bitrate
[  5]   0.00-10.00  sec  1.05 GBytes   900 Mbits/sec
[  5]   0.00-10.00  sec  1.09 GBytes   937 Mbits/sec
```

## Gate-Status

Heim-PC-Link-Speed-Gate: **geschlossen** (1000/full, LAN-Durchsatz ca. 900–937 Mbit/s belegt).
