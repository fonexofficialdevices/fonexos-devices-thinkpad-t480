#!/bin/bash

set -ouex pipefail

# Copy the contents of system_files/ of the git repo to /
## MUST NOT BE DELETED!
cp -avf "/ctx/system_files"/. /

### Install packages

# Remove default apps that are not needed
dnf remove firefox gnome-backgrounds gnome-maps gnome-weather gnome-logs desktop-backgrounds-gnome f44-backgrounds f44-backgrounds-* -y

# Replace default weather app with Mousam (Doesn't work)
# dnf5 install flatpak -y
# flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
# flatpak install flathub io.github.amit9838.mousam -y

# Add Mozilla Nightly repo and install Firefox Nightly
dnf config-manager addrepo --id=mozilla --set=baseurl=https://packages.mozilla.org/rpm/firefox --set=gpgkey=https://packages.mozilla.org/rpm/firefox/signing-key.gpg --set=repo_gpgcheck=0
dnf makecache --refresh
dnf install -y firefox-nightly

# Group install development tools
dnf5 -y group install development-tools

# Install utilities and gnome-rounded-blur build dependencies
dnf5 install -y \
    tmux \
    dnf5-plugins \
    fastfetch \
    bubblewrap \
    procps-ng \
    curl \
    git \
    make \
    gcc \
    kitty \
    bc \
    meson \
    glib2-devel \
    mutter-devel \
    gobject-introspection \
    gcc-c++

# Install utilities for screensaver
dnf5 install -y python3-gobject gtk4 libadwaita rsms-inter-vf-fonts

### Build and Install gnome-rounded-blur
echo "--------------------------------------------------------"
echo "Building and installing gnome-rounded-blur"
echo "--------------------------------------------------------"

BUILD_DIR="/tmp/gnome-rounded-blur-build"
REPO="https://github.com/kancko/gnome-rounded-blur"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"
git clone "$REPO" repo
cd repo

# Calculate Mutter API version adjustments
MUTTER_SYS_VER=$(mutter --version | grep -o -P '(?<=mutter ).*' | sed -e 's/"//g' -e "s/'//g" -e 's/\..*//g')
HARDCODE_MUTTER_SYS_VER=$(cat meson.build | grep -o -P '(?<=mutter_req = ).*' | sed -e 's/"//g' -e "s/'//g" -e 's/\..*//g' -e 's/>//g' -e 's/=//g' -e 's/ //g')
MUTTER_API_REPO_VER=$(cat meson.build | grep -o -P '(?<=mutter_api_version = ).*' | sed -e 's/"//g' -e "s/'//g" -e 's/ //g')

if [[ "$MUTTER_SYS_VER" -ge "$HARDCODE_MUTTER_SYS_VER" ]]; then
    DIFF_VALUE=$(echo "$MUTTER_SYS_VER - $HARDCODE_MUTTER_SYS_VER" | bc)
    DIFF_VALUE_2=$(echo "$MUTTER_API_REPO_VER + $DIFF_VALUE" | bc)
    sed -i -e '0,/'"mutter_api_version = ""$MUTTER_API_REPO_VER"'/{s/'"$MUTTER_API_REPO_VER"'/'"$DIFF_VALUE_2"'/g}' meson.build
else
    DIFF_VALUE=$(echo "$HARDCODE_MUTTER_SYS_VER - $MUTTER_SYS_VER" | bc)
    DIFF_VALUE_2=$(echo "$MUTTER_API_REPO_VER - $DIFF_VALUE" | bc)
    sed -i -e '0,/'"mutter_req = ""$HARDCODE_MUTTER_SYS_VER"'/{s/'"$HARDCODE_MUTTER_SYS_VER"'/'"$MUTTER_SYS_VER"'/g}' meson.build
    sed -i -e '0,/'"mutter_api_version = ""$MUTTER_API_REPO_VER"'/{s/'"$MUTTER_API_REPO_VER"'/'"$DIFF_VALUE_2"'/g}' meson.build
fi

# Build and install directly to /usr/lib64
echo "Building and installing library..."
meson setup build --prefix=/usr --libdir=lib64
meson compile -C build
meson install -C build

# Clean up workspace
cd /
rm -rf "$BUILD_DIR"

#### Example for enabling a System Unit File
systemctl enable podman.socket
