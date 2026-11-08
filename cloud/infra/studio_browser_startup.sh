#!/bin/bash
# Persistent trial browser; desktop ports are accessible only through SSH.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends chromium xvfb openbox x11vnc novnc websockify python3-venv ca-certificates fonts-liberation curl
id studio >/dev/null 2>&1 || useradd --create-home --home-dir /var/lib/studio --shell /bin/bash studio
install -d -o studio -g studio -m 700 /var/lib/studio/profile /var/lib/studio/.config
cat > /etc/systemd/system/studio-display.service <<'EOF'
[Unit]
Description=Private Studio browser display
After=network.target
[Service]
User=studio
ExecStart=/usr/bin/Xvfb :99 -screen 0 1440x1000x24 -nolisten tcp
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/studio-window-manager.service <<'EOF'
[Unit]
Description=Studio window manager
After=studio-display.service
Requires=studio-display.service
[Service]
User=studio
Environment=DISPLAY=:99
ExecStart=/usr/bin/openbox
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/studio-browser.service <<'EOF'
[Unit]
Description=Persistent YouTube Studio browser
After=studio-display.service studio-window-manager.service network-online.target
Requires=studio-display.service
[Service]
User=studio
Environment=DISPLAY=:99
Environment=HOME=/var/lib/studio
ExecStart=/usr/bin/chromium --user-data-dir=/var/lib/studio/profile --no-first-run --disable-dev-shm-usage --start-maximized https://studio.youtube.com/
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/studio-vnc.service <<'EOF'
[Unit]
Description=Loopback-only Studio desktop
After=studio-display.service
Requires=studio-display.service
[Service]
User=studio
ExecStart=/usr/bin/x11vnc -display :99 -localhost -rfbport 5900 -forever -shared -nopw
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
cat > /etc/systemd/system/studio-web-desktop.service <<'EOF'
[Unit]
Description=Loopback-only Studio web desktop
After=studio-vnc.service
Requires=studio-vnc.service
[Service]
User=studio
ExecStart=/usr/bin/websockify --web=/usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now studio-display studio-window-manager studio-browser studio-vnc studio-web-desktop
printf 'ready\n' > /var/lib/studio/setup-status
