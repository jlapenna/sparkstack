#!/bin/bash
set -e

echo "Removing ufw..."
apt-get purge -y ufw

echo "Installing and configuring iptables-persistent..."
DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent

echo "Inserting SSH bypass rule..."
# Protect port 222
# Remove old restricted rule if it exists
iptables -D INPUT -p tcp --dport 222 -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true

if ! iptables -C INPUT -p tcp --dport 222 -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 1 -p tcp --dport 222 -j ACCEPT
    echo "SSH bypass rule inserted for port 222."
else
    echo "SSH bypass rule already exists for port 222."
fi

# Protect port 8234
# Remove old restricted rule if it exists
iptables -D INPUT -p tcp --dport 8234 -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true

if ! iptables -C INPUT -p tcp --dport 8234 -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 1 -p tcp --dport 8234 -j ACCEPT
    echo "SSH bypass rule inserted for port 8234."
else
    echo "SSH bypass rule already exists for port 8234."
fi

echo "Saving rules permanently..."
netfilter-persistent save

echo "Done! Firewall is correctly configured and SSH is protected."
