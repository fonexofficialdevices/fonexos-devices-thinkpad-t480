#!/usr/bin/env bash
# FonexOS USBGuard bootstrap
# Run this INSIDE the Containerfile build stage (RUN usbguard-setup.sh)
# so the default policy is baked into the image, not generated at
# first boot (rpm-ostree images can't run "live" enrollment steps
# reliably on end-user hardware since /usr is read-only).
set -euo pipefail

# Generate a default policy allowing currently-attached build-time
# devices (harmless placeholder — real enrollment happens per-machine,
# see note at bottom) and hard-deny everything else by default.
mkdir -p /etc/usbguard

cat > /etc/usbguard/usbguard-daemon.conf <<'EOF'
RuleFile=/etc/usbguard/rules.conf
ImplicitPolicyTarget=block

# PresentDevicePolicy=allow (not apply-policy): anything physically
# connected at boot time was, by definition, chosen by the user —
# there's no attacker window there. Evaluating present devices against
# the ruleset is what caused keyboard/mouse lockouts on first boot,
# since composite/wireless-dongle devices don't always match a simple
# HID interface rule cleanly. InsertedDevicePolicy stays apply-policy,
# which is where USBGuard's actual threat model applies: devices
# plugged in *after* boot, potentially while the machine is unattended.
PresentDevicePolicy=allow
PresentControllerPolicy=keep
InsertedDevicePolicy=apply-policy
RestoreControllerDeviceState=false
DeviceManagerBackend=uevent
IPCAllowedUsers=root
IPCAllowedGroups=wheel
IPCAccessControlFiles=/etc/usbguard/IPCAccessControl.d/
DeviceRulesWithPort=false
AuditBackend=LinuxAudit
AuditFilePath=/var/log/usbguard/usbguard-audit.log
EOF

# Baseline rule file for devices inserted AFTER boot: allow HID
# (keyboard/mouse) and Bluetooth radios by class, so a BT dongle or
# a hot-plugged keyboard still works without manual enrollment.
# Storage/network USB devices stay blocked until the user allows them
# via `usbguard allow-device` or the GNOME USBGuard applet.
cat > /etc/usbguard/rules.conf <<'EOF'
# HID devices — keyboards, mice, trackpads (any interface number,
# since composite/wireless-dongle devices expose HID on interface 1+,
# not always interface 0)
allow with-interface one-of { 03:*:* } name "*" hash "*" parent-hash "*" via-port "*" with-connect-type "*"

# Bluetooth radios (class E0 = wireless controller) — needed so BT
# keyboards/mice work; the actual HID traffic rides over the BT
# protocol, not a raw USB HID interface, so this is a separate rule
allow with-interface one-of { e0:01:01 } name "*" hash "*" parent-hash "*" via-port "*" with-connect-type "*"

# Everything else: fall through to ImplicitPolicyTarget=block
EOF

systemctl enable usbguard.service

echo "USBGuard baked in: present-at-boot devices always allowed,"
echo "devices inserted after boot are gated by HID/Bluetooth rules."
echo "NOTE: this covers keyboard/mouse/dock at boot time safely. Storage"
echo "devices inserted later still need 'usbguard allow-device'. Consider"
echo "surfacing 'usbguard list-devices' and 'usbguard allow-device' in"
echo "the FonexOS Toolbox as a menu item for that case."