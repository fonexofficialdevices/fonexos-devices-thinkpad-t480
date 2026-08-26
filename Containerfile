## FonexOS CONTAINERFILE!

# Allow build scripts to be referenced without being copied into the final image
FROM scratch AS ctx
COPY build_files /
COPY system_files /system_files

# Base Image
FROM quay.io/fedora/fedora-silverblue:latest
## Other possible base images include:
# FROM ghcr.io/ublue-os/bazzite:testing
# FROM ghcr.io/ublue-os/aurora:stable
# FROM ghcr.io/ublue-os/bluefin-nvidia-open:stable
# 
# ... and so on, here are more base images
# Universal Blue Images: https://github.com/orgs/ublue-os/packages
# Fedora base image: quay.io/fedora/fedora-bootc:44
# CentOS base images: quay.io/centos-bootc/centos-bootc:stream10

### [IM]MUTABLE /opt
## Some bootable images, like Fedora, have /opt symlinked to /var/opt, in order to
## make it mutable/writable for users. However, some packages write files to this directory,
## thus its contents might be wiped out when bootc deploys an image, making it troublesome for
## some packages. Eg, google-chrome, docker-desktop.
##
## Uncomment the following line if one desires to make /opt immutable and be able to be used
## by the package manager.

# RUN rm /opt && mkdir /opt

### MODIFICATIONS
## make modifications desired in your image and install packages by modifying the build.sh script
## the following RUN directive does all the things required to run "build.sh" as recommended.

RUN --mount=type=bind,from=ctx,source=/,target=/ctx \
    --mount=type=cache,dst=/var/cache \
    --mount=type=cache,dst=/var/log \
    --mount=type=tmpfs,dst=/tmp \
    /ctx/build.sh
    
# Cachy won't be presented on the optimized image.
# Asterisks when using sudo 
RUN echo "Defaults pwfeedback" >> /etc/sudoers

# DCONF
RUN dconf update

# ============================================================================
# 2. Automating Homebrew
# =============================================================================
# (development-tools group + firefox/fastfetch/bubblewrap/procps-ng/curl/git/sudo
#  are now installed once in build.sh)

# Setup Homebrew path globally, but ONLY evaluate if the install has actually finished
RUN echo 'if [ -f /home/linuxbrew/.linuxbrew/bin/brew ]; then eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv bash)"; fi' > /etc/profile.d/homebrew.sh

# Create the background installation script
# Note: Dynamically finds UID 1000 (the first user created in setup) instead of hardcoding 'ttd'
RUN mkdir -p /usr/libexec && \
    echo '#!/bin/bash' > /usr/libexec/install-homebrew-auto.sh && \
    echo 'until curl -sI https://github.com > /dev/null; do sleep 2; done' >> /usr/libexec/install-homebrew-auto.sh && \
    echo 'TARGET_USER=$(getent passwd 1000 | cut -d: -f1)' >> /usr/libexec/install-homebrew-auto.sh && \
    echo 'if [ -z "$TARGET_USER" ]; then exit 1; fi' >> /usr/libexec/install-homebrew-auto.sh && \
    echo 'mkdir -p /var/home/linuxbrew' >> /usr/libexec/install-homebrew-auto.sh && \
    echo 'chown -R $TARGET_USER:$TARGET_USER /var/home/linuxbrew' >> /usr/libexec/install-homebrew-auto.sh && \
    echo 'su - $TARGET_USER -c "NONINTERACTIVE=1 /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""' >> /usr/libexec/install-homebrew-auto.sh && \
    echo 'systemctl disable homebrew-setup.service' >> /usr/libexec/install-homebrew-auto.sh && \
    chmod +x /usr/libexec/install-homebrew-auto.sh

# Create the systemd service
RUN echo '[Unit]' > /etc/systemd/system/homebrew-setup.service && \
    echo 'Description=Unattended Homebrew Installation' >> /etc/systemd/system/homebrew-setup.service && \
    echo 'After=network-online.target' >> /etc/systemd/system/homebrew-setup.service && \
    echo 'Wants=network-online.target' >> /etc/systemd/system/homebrew-setup.service && \
    echo '' >> /etc/systemd/system/homebrew-setup.service && \
    echo '[Service]' >> /etc/systemd/system/homebrew-setup.service && \
    echo 'Type=oneshot' >> /etc/systemd/system/homebrew-setup.service && \
    echo 'ExecStart=/usr/libexec/install-homebrew-auto.sh' >> /etc/systemd/system/homebrew-setup.service && \
    echo 'RemainAfterExit=yes' >> /etc/systemd/system/homebrew-setup.service && \
    echo '' >> /etc/systemd/system/homebrew-setup.service && \
    echo '[Install]' >> /etc/systemd/system/homebrew-setup.service && \
    echo 'WantedBy=multi-user.target' >> /etc/systemd/system/homebrew-setup.service

# Enable the service so it is primed for the first boot
RUN systemctl enable homebrew-setup.service

# =============================================================================
# 4. Installing kitty and removing default terminals
# =============================================================================

RUN dnf5 remove ptyxis gnome-console gnome-terminal -y && \
    dnf5 clean all && \
    update-desktop-database /usr/share/applications

# =============================================================================
# 5. Install/Remove software and add tweaks
# =============================================================================

# REMOVE LIBREOFFICE
RUN dnf5 group remove libreoffice -y || true && \
    dnf5 remove "libreoffice*" -y

RUN gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true

# Compile the custom gschema overrides for fonts and themes
RUN glib-compile-schemas /usr/share/glib-2.0/schemas

# Blur My Shell extension
RUN dnf5 -y install gnome-shell-extension-blur-my-shell 
RUN gnome-extensions enable blur-my-shell@aunetx

# Dash to Dock extension
RUN dnf5 -y install gnome-shell-extension-dash-to-dock

# =============================================================================
# 6. Install Howdy for facial recognition
# =============================================================================

# Pull the Fedora 44 repository file directly to avoid copr plugin issues
ADD https://copr.fedorainfracloud.org/coprs/ronnypfannschmidt/howdy-beta/repo/fedora-44/ronnypfannschmidt-howdy-beta-fedora-44.repo /etc/yum.repos.d/howdy-beta.repo

RUN dnf5 -y install howdy howdy-gtk howdy-authselect && \
    dnf5 clean all

# Ensure world-readable permissions for wallpapers and XML files
RUN chmod -R 644 /usr/share/backgrounds/fonexos/* && \
    chmod 644 /usr/share/gnome-background-properties/* && \
    glib-compile-schemas /usr/share/glib-2.0/schemas

# NO.7 #    
#### SYSTEM HARDENING!!!!!!

# ---------------------------------------------------------------------
# 1. hardened_malloc — install while still upstream-identified, since
#    it may pull from a COPR depending on which build you use
# ---------------------------------------------------------------------
RUN dnf5 install -y dnf5-plugins
RUN dnf5 copr enable -y secureblue/hardened_malloc fedora-43-x86_64
RUN dnf5 install -y hardened_malloc
 
# Preload system-wide (skip this line if you'd rather make it opt-in
# per-app via an env var — system-wide preload can break some
# proprietary Flatpaks that assume glibc malloc behavior)

# LD_PRELOAD=/usr/lib64/libhardened_malloc.so /usr/bin/firefox-nightly
 
# ---------------------------------------------------------------------
# 2. USBGuard
# ---------------------------------------------------------------------
COPY usbguard-setup.sh /tmp/usbguard-setup.sh
RUN dnf5 install -y usbguard && \
    chmod +x /tmp/usbguard-setup.sh && \
    /tmp/usbguard-setup.sh && \
    rm /tmp/usbguard-setup.sh
 
# ---------------------------------------------------------------------
# 4. Kernel args (bootc kargs.d) — see caveat inside the file about
#    NOT shipping this in the main CachyOS-based image
# ---------------------------------------------------------------------

# INCLUDED INSIDE system_files!
 
# ---------------------------------------------------------------------
# 5. Telemetry hosts block
# ---------------------------------------------------------------------
COPY hosts-blocklist.txt /tmp/hosts-blocklist.txt
RUN cat /tmp/hosts-blocklist.txt >> /etc/hosts && \
    rm /tmp/hosts-blocklist.txt
 
# ---------------------------------------------------------------------
# 6. Mask cockpit (local admin web console — unnecessary attack surface
#    on a desktop image; skip this line if you actually want cockpit
#    for remote fleet management of FonexOS machines)
# ---------------------------------------------------------------------
RUN systemctl mask cockpit.socket
 
# ---------------------------------------------------------------------
# 7. Attack-surface trims — remove unused filesystem drivers/protocols
#    Test each removal against real hardware before shipping; silent
#    breakage here won't show up until someone plugs in the one weird
#    device that needed the module you dropped.
# ---------------------------------------------------------------------
RUN rm -f /usr/lib/modules/*/kernel/drivers/firewire/* 2>/dev/null || true
 
# =====================================================================
# gotcha checklist before you rebuild:
# - COPY steps need the source files in your build context directory
# - test USBGuard on real hardware first (teammate's machine) — a
#   default-deny policy that blocks HID wrong = unusable machine
# - verify sysctl values actually load: `sysctl -a | grep kptr_restrict`
#   after boot, since silent sysctl.d parse failures are exactly the
#   kind of thing that's bitten you before (GNOME background XML case)
# =====================================================================

#############

# Apply Fonex-icons
RUN gtk-update-icon-cache -f /usr/share/icons/Fonex-icons/
RUN gsettings set org.gnome.desktop.interface icon-theme "Fonex-icons"

### LINTING
## Verify final image and contents are correct.
RUN bootc container lint